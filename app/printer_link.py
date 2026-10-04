"""Sending a print to the 3D printer itself. The Ender-3 V3 SE has a USB port and a microSD slot — no Wi-Fi, LAN or
Bluetooth (a Bluetooth-serial adapter shows up as a serial port, so it works the same way). Four ways:
- "usb": the G-code streamed over the USB cable, line by line — Marlin's own host protocol (numbered + checksummed
  lines, "ok" before the next one, "Resend: N" honoured), like OctoPrint / Pronterface. The PC must stay on.
- "usb_sd": copied over the USB cable onto the printer's own SD card (M28 … M29), then started (M23 / M24): the
  printer prints by itself, the PC may go.
- "card": copied onto an SD card in this PC's card reader (then the card goes into the printer).
- "network": uploaded to a print server on the LAN (OctoPrint, or Klipper's Moonraker) and started.
No extra packages: serial ports are opened with the system's own calls (Windows: kernel32 through ctypes; Linux:
termios). A print only ever starts from the user's own click (the AI prepares it, never starts it)."""
import ctypes
import glob
import os
import re
import shutil
import string
import subprocess
import threading
import time
from pathlib import Path

import httpx

from .config import MEDIA, NO_WINDOW, load_settings, save_settings
from .plat import IS_WIN

BAUD = 115200
JOB: dict = {}          # the one print going on (one printer)
_lock = threading.Lock()


# ---------------------------------------------------------------- where the printer can be
def ports() -> list[dict]:
    """Serial ports (the printer's USB cable, a Bluetooth-serial adapter): [{"port", "name"}]."""
    if IS_WIN:
        import winreg
        found = []
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
                i = 0
                while True:
                    try:
                        found.append(winreg.EnumValue(k, i)[1])
                        i += 1
                    except OSError:
                        break
        except OSError:
            return []
        names = {}
        if found:  # friendly names ("USB-SERIAL CH340 (COM3)") — a second or two, only when the list is asked for
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                      "Get-CimInstance Win32_PnPEntity -Filter \"Name like '%(COM%'\" | ForEach-Object Name"],
                                     capture_output=True, text=True, timeout=8, creationflags=NO_WINDOW).stdout
                for line in out.splitlines():
                    m = re.search(r"\((COM\d+)\)", line)
                    if m:
                        names[m.group(1)] = line.strip()
            except (OSError, subprocess.TimeoutExpired):
                pass
        return [{"port": p, "name": names.get(p, p)} for p in sorted(found, key=lambda x: int(re.sub(r"\D", "", x) or 0))]
    out = []
    by_id = {os.path.realpath(p): os.path.basename(p) for p in glob.glob("/dev/serial/by-id/*")}
    for p in sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/rfcomm*")):
        out.append({"port": p, "name": by_id.get(os.path.realpath(p), p)})
    return out


def drives() -> list[dict]:
    """Removable drives (an SD card in a card reader, a USB stick): [{"path", "name", "free_gb"}]."""
    out = []
    if IS_WIN:
        k32 = ctypes.windll.kernel32
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if k32.GetDriveTypeW(root) != 2:  # DRIVE_REMOVABLE
                continue
            label = ctypes.create_unicode_buffer(261)
            ok = k32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
            if not ok:
                continue  # an empty card reader
            try:
                free = shutil.disk_usage(root).free / 1e9
            except OSError:
                continue
            out.append({"path": root, "name": f"{label.value or 'SD card'} ({letter}:)", "free_gb": round(free, 1)})
        return out
    user = os.environ.get("USER", "")
    for base in (f"/run/media/{user}", f"/media/{user}", "/media"):
        for d in sorted(glob.glob(base + "/*")):
            if os.path.ismount(d):
                try:
                    out.append({"path": d, "name": os.path.basename(d), "free_gb": round(shutil.disk_usage(d).free / 1e9, 1)})
                except OSError:
                    pass
    return out


def to_card(gcode: Path, drive: str, name: str) -> dict:
    """Copies the G-code onto the SD card (then: eject, put it in the printer, choose the file on its screen)."""
    if not any(d["path"] == drive for d in drives()):
        raise ValueError("That card isn't there any more — put it back in and try again")
    safe = re.sub(r"[^\w \-().]", "", name).strip() or "print.gcode"
    if not safe.lower().endswith(".gcode"):
        safe += ".gcode"
    dst = Path(drive) / safe
    shutil.copyfile(gcode, dst)
    with open(dst, "rb+") as f:  # really on the card before it's pulled out
        os.fsync(f.fileno())
    return {"saved": str(dst), "name": safe}


def eject(drive: str) -> bool:
    """Safely removes the card (Windows' own Eject; Linux: udisksctl)."""
    try:
        if IS_WIN:
            letter = drive[:2]
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(New-Object -ComObject Shell.Application).Namespace(17).ParseName('{letter}').InvokeVerb('Eject')"],
                           timeout=20, creationflags=NO_WINDOW)
            return True
        dev = subprocess.run(["findmnt", "-no", "SOURCE", drive], capture_output=True, text=True, timeout=10).stdout.strip()
        subprocess.run(["udisksctl", "unmount", "-b", dev], timeout=20)
        subprocess.run(["udisksctl", "power-off", "-b", re.sub(r"p?\d+$", "", dev)], timeout=20)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------- the serial port, with the system's own calls
class _WinSerial:
    def __init__(self, port: str, baud: int):
        from ctypes import wintypes as w

        class DCB(ctypes.Structure):
            _fields_ = [("DCBlength", w.DWORD), ("BaudRate", w.DWORD), ("flags", w.DWORD), ("wReserved", w.WORD),
                        ("XonLim", w.WORD), ("XoffLim", w.WORD), ("ByteSize", w.BYTE), ("Parity", w.BYTE),
                        ("StopBits", w.BYTE), ("XonChar", ctypes.c_char), ("XoffChar", ctypes.c_char),
                        ("ErrorChar", ctypes.c_char), ("EofChar", ctypes.c_char), ("EvtChar", ctypes.c_char),
                        ("wReserved1", w.WORD)]

        class TIMEOUTS(ctypes.Structure):
            _fields_ = [("ReadIntervalTimeout", w.DWORD), ("ReadTotalTimeoutMultiplier", w.DWORD),
                        ("ReadTotalTimeoutConstant", w.DWORD), ("WriteTotalTimeoutMultiplier", w.DWORD),
                        ("WriteTotalTimeoutConstant", w.DWORD)]
        k = self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.restype = w.HANDLE
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
        k.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
        k.WriteFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
        k.CloseHandle.argtypes = [w.HANDLE]
        k.GetCommState.argtypes = k.SetCommState.argtypes = [w.HANDLE, ctypes.c_void_p]
        k.SetCommTimeouts.argtypes = [w.HANDLE, ctypes.c_void_p]
        h = k.CreateFileW("\\\\.\\" + port, 0xC0000000, 0, None, 3, 0, None)  # read + write, OPEN_EXISTING
        if not h or h == ctypes.c_void_p(-1).value:
            raise OSError(f"{port} can't be opened (unplugged, or another program like Creality Print has it open)")
        self.h = h
        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        k.GetCommState(h, ctypes.byref(dcb))
        dcb.BaudRate, dcb.ByteSize, dcb.Parity, dcb.StopBits = baud, 8, 0, 0
        dcb.flags = 0x1 | (1 << 4) | (1 << 12)  # binary, DTR on, RTS on — no flow control
        if not k.SetCommState(h, ctypes.byref(dcb)):
            self.close()
            raise OSError(f"{port}: the port settings were refused")
        t = TIMEOUTS(0xFFFFFFFF, 0xFFFFFFFF, 100, 0, 3000)  # read: what's there, or wait up to 0.1 s for it
        k.SetCommTimeouts(h, ctypes.byref(t))
        self._w = w

    def read(self) -> bytes:
        buf = ctypes.create_string_buffer(4096)
        n = self._w.DWORD(0)
        if not self.k.ReadFile(self.h, buf, 4096, ctypes.byref(n), None):
            raise OSError("the printer's USB connection was lost")
        return buf.raw[:n.value]

    def write(self, data: bytes) -> None:
        n = self._w.DWORD(0)
        while data:
            if not self.k.WriteFile(self.h, data, len(data), ctypes.byref(n), None):
                raise OSError("the printer's USB connection was lost")
            data = data[n.value:]

    def close(self) -> None:
        if getattr(self, "h", None):
            self.k.CloseHandle(self.h)
            self.h = None


class _PosixSerial:
    def __init__(self, port: str, baud: int):
        import termios
        try:
            fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except PermissionError as e:
            raise OSError(f"{port}: no permission — on Linux add yourself to the 'dialout' group once: "
                          "sudo usermod -aG dialout $USER (then log out and in)") from e
        a = termios.tcgetattr(fd)
        speed = getattr(termios, f"B{baud}")
        a[0], a[1], a[3] = 0, 0, 0  # raw: no input / output / line processing
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = speed
        a[6][termios.VMIN], a[6][termios.VTIME] = 0, 0
        termios.tcsetattr(fd, termios.TCSANOW, a)
        termios.tcflush(fd, termios.TCIOFLUSH)
        self.fd = fd

    def read(self) -> bytes:
        import select
        r, _, _ = select.select([self.fd], [], [], 0.1)
        if not r:
            return b""
        try:
            data = os.read(self.fd, 4096)
        except BlockingIOError:
            return b""
        if not data:
            raise OSError("the printer's USB connection was lost")
        return data

    def write(self, data: bytes) -> None:
        import select
        view = memoryview(data)
        while view:
            try:
                view = view[os.write(self.fd, view):]
            except BlockingIOError:
                select.select([], [self.fd], [], 1)

    def close(self) -> None:
        if getattr(self, "fd", None) is not None:
            os.close(self.fd)
            self.fd = None


def open_port(port: str, baud: int = BAUD):
    return _WinSerial(port, baud) if IS_WIN else _PosixSerial(port, baud)


# ---------------------------------------------------------------- Marlin's host protocol
class PrinterError(RuntimeError):
    pass


SLOW = re.compile(r"^(M109|M190|M191|G28|G29|M303|G4|M400|M600|M0|M1)\b")  # heating / homing / levelling: minutes


class Marlin:
    """One printer on a serial link: numbered + checksummed lines, "ok" before the next, resends honoured."""

    def __init__(self, link, on_temps=None, on_line=None):
        self.link, self.buf, self.n, self.sent = link, b"", 0, {}
        self.on_temps, self.on_line = on_temps, on_line

    def _readline(self, timeout: float) -> str | None:
        """One line from the printer (None: nothing within timeout seconds)."""
        end = time.time() + timeout
        while True:
            if b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                line = raw.decode("utf-8", "ignore").strip()
                if line:
                    return line
                continue
            if time.time() >= end:
                return None
            data = self.link.read()
            if data:
                self.buf += data
            else:
                time.sleep(0.005)

    def _temps(self, line: str) -> None:
        t = re.search(r"T:\s*([\d.]+)\s*/\s*([\d.]+)", line)
        b = re.search(r"B:\s*([\d.]+)\s*/\s*([\d.]+)", line)
        if (t or b) and self.on_temps:
            self.on_temps({**({"nozzle": [float(t.group(1)), float(t.group(2))]} if t else {}),
                           **({"bed": [float(b.group(1)), float(b.group(2))]} if b else {})})

    def raw(self, text: str) -> None:
        self.link.write((text + "\n").encode())

    def send(self, cmd: str, timeout: float | None = None) -> list[str]:
        """Sends one command and waits for its "ok" (heating / homing may take minutes: "busy" keeps it alive)."""
        self.n += 1
        body = f"N{self.n} {cmd}"
        cs = 0
        for ch in body.encode():
            cs ^= ch
        self.sent[self.n] = f"{body}*{cs}\n"
        self.sent.pop(self.n - 200, None)
        self.link.write(self.sent[self.n].encode())
        limit = timeout or (1800 if SLOW.match(cmd) else 120)
        deadline, got = time.time() + limit, []
        while time.time() < deadline:
            line = self._readline(min(1.0, max(0.0, deadline - time.time())))
            if line is None:
                continue
            low = line.lower()
            if self.on_line:
                self.on_line(line)
            self._temps(line)
            if low.startswith("ok"):
                return got
            if low.startswith(("resend:", "rs:", "rs ")):
                n = int(re.sub(r"\D", "", line.split(":", 1)[-1].split()[0]) or self.n)
                for k in range(n, self.n + 1):  # the printer missed some lines: from there again
                    if k in self.sent:
                        self.link.write(self.sent[k].encode())
                continue
            if low.startswith("error:") and not any(w in low for w in ("checksum", "line number", "linenumber", "no line")):
                raise PrinterError(line[6:].strip() or line)
            if "busy" in low:  # still working on it (heating, homing): keep waiting
                deadline = time.time() + limit
                continue
            got.append(line)
        raise PrinterError(f"the printer didn't answer “{cmd[:20]}” in time")

    def hello(self) -> str:
        """After opening the port: the board may restart (DTR) — wait, then number lines from 0 and ask who it is."""
        end = time.time() + 2.5
        while time.time() < end:  # its start-up text
            self._readline(end - time.time())
        self.n = -1
        self.send("M110 N0")
        self.n = 0
        info = " ".join(self.send("M115", 10))
        m = re.search(r"MACHINE_TYPE:([^\n]+?)(?:\s+EXTRUDER_COUNT|$)", info) or re.search(r"FIRMWARE_NAME:(\S+)", info)
        return m.group(1).strip() if m else "a Marlin printer"


def commands(gcode: Path):
    """The G-code's commands, comments and blank lines left out."""
    with open(gcode, encoding="utf-8", errors="ignore") as f:
        for line in f:
            cmd = line.split(";", 1)[0].strip()
            if cmd:
                yield cmd


# ---------------------------------------------------------------- the print job (one at a time)
def status() -> dict:
    j = JOB
    if not j:
        return {"state": "idle"}
    out = {k: j.get(k) for k in ("state", "mode", "name", "port", "printer", "sent", "total", "temps", "message", "started", "error")}
    out["pct"] = round(100 * (j.get("sent") or 0) / max(j.get("total") or 1, 1), 1)
    out["elapsed"] = round(time.time() - j["started"]) if j.get("started") else 0
    return out


def active() -> bool:
    return JOB.get("state") in ("connecting", "heating", "printing", "uploading", "paused")


def start(gcode: Path, mode: str, port: str, name: str) -> dict:
    """Starts a print in the background (mode usb = streamed, usb_sd = onto the printer's card then started)."""
    with _lock:
        if active():
            raise ValueError("A print is already going — stop it first")
        total = sum(1 for _ in commands(gcode))
        JOB.clear()
        JOB.update(state="connecting", mode=mode, name=name, port=port, sent=0, total=total, temps={}, message="Connecting…",
                   started=time.time(), stop=False, pause=False, error=None, printer=None)
    threading.Thread(target=_run, args=(gcode, mode, port, name), daemon=True).start()
    return status()


def control(action: str) -> dict:
    if not active():
        raise ValueError("No print is going")
    if action == "pause":
        JOB["pause"] = True
    elif action == "resume":
        JOB["pause"] = False
    elif action == "cancel":
        JOB["stop"] = True
        JOB["message"] = "Stopping…"
    return status()


def _sd_name(name: str) -> str:
    """An 8.3 name for the printer's own card (what M28 / M23 want)."""
    base = re.sub(r"[^A-Za-z0-9]", "", name).upper()[:6] or "PRINT"
    return f"{base}AI.GCO"


def _run(gcode: Path, mode: str, port: str, name: str) -> None:
    link = None
    try:
        link = open_port(port)
        m = Marlin(link, on_temps=lambda t: JOB["temps"].update(t))
        JOB["printer"] = m.hello()
        if mode == "usb_sd":
            fname = _sd_name(name)
            JOB.update(state="uploading", message=f"Copying it onto the printer's SD card as {fname}…")
            said = " ".join(m.send(f"M28 {fname}", 20)).lower()
            if "open failed" in said or "error" in said:
                raise PrinterError("the printer couldn't open a file on its SD card (is a card in it?)")
            for cmd in commands(gcode):
                if JOB["stop"]:
                    m.send("M29", 20)
                    raise PrinterError("stopped")
                m.send(cmd, 30)
                JOB["sent"] += 1
            m.send("M29", 30)
            m.send(f"M23 {fname}", 20)
            m.send("M24", 20)
            JOB.update(state="done", message=f"On the printer's SD card ({fname}) and printing — you can unplug the USB now.")
            return
        JOB.update(state="printing", message="Printing over USB — keep the PC on and the cable in.")
        lifted = False
        for cmd in commands(gcode):
            while JOB["pause"] and not JOB["stop"]:
                if not lifted:
                    m.send("G91")
                    m.send("G1 Z5 F600")
                    m.send("G90")
                    lifted, JOB["state"], JOB["message"] = True, "paused", "Paused (nozzle lifted 5 mm)."
                time.sleep(0.3)
            if lifted and not JOB["pause"]:
                m.send("G91")
                m.send("G1 Z-5 F600")
                m.send("G90")
                lifted, JOB["state"], JOB["message"] = False, "printing", "Printing over USB — keep the PC on and the cable in."
            if JOB["stop"]:
                for c in ("M104 S0", "M140 S0", "M107", "G91", "G1 Z10 F600", "G90", "M84"):  # cool down, lift, motors off
                    m.send(c, 60)
                JOB.update(state="cancelled", message="Stopped: heaters off, nozzle lifted.")
                return
            if SLOW.match(cmd):
                JOB["state"] = "heating" if cmd.startswith(("M109", "M190")) else "printing"
            m.send(cmd)
            JOB["sent"] += 1
            if JOB["state"] == "heating" and not SLOW.match(cmd):
                JOB["state"] = "printing"
        JOB.update(state="done", message="Done.")
    except (OSError, PrinterError, ValueError) as e:
        JOB.update(state="cancelled" if str(e) == "stopped" else "error", error=str(e)[:300],
                   message="Stopped." if str(e) == "stopped" else f"It stopped: {e}"[:300])
    finally:
        if link:
            link.close()


# ---------------------------------------------------------------- a print server on the LAN (OctoPrint / Moonraker)
def to_network(gcode: Path, name: str) -> dict:
    s = load_settings().get("printer_link") or {}
    url, key, kind = str(s.get("url") or "").rstrip("/"), str(s.get("key") or ""), s.get("kind")
    if not url.startswith(("http://", "https://")):
        raise ValueError("No print server set (Settings: its address, e.g. http://192.168.1.50)")
    safe = (re.sub(r"[^\w\-.]", "_", name) or "print") + ("" if name.lower().endswith(".gcode") else ".gcode")
    with open(gcode, "rb") as f:
        if kind == "moonraker":
            r = httpx.post(f"{url}/server/files/upload", files={"file": (safe, f, "application/octet-stream")},
                           data={"root": "gcodes", "print": "true"}, timeout=600)
        else:
            r = httpx.post(f"{url}/api/files/local", headers={"X-Api-Key": key}, files={"file": (safe, f, "application/octet-stream")},
                           data={"select": "true", "print": "true"}, timeout=600)
    if r.status_code >= 300:
        raise ValueError(f"The print server said {r.status_code}: {r.text[:200]}")
    return {"sent": safe, "server": url}


def set_link(body: dict) -> dict:
    s = load_settings()
    cur = s.get("printer_link") or {}
    kind = body.get("kind") if body.get("kind") in ("usb", "octoprint", "moonraker") else cur.get("kind", "usb")
    s["printer_link"] = {"kind": kind, "port": str(body.get("port", cur.get("port", "")))[:60],
                         "url": str(body.get("url", cur.get("url", "")))[:200], "key": str(body.get("key", cur.get("key", "")))[:200]}
    save_settings(s)
    return s["printer_link"]


def media_file(url: str, suffix: str) -> Path:
    f = MEDIA / Path(str(url)).name
    if f.suffix.lower() != suffix or not f.is_file():
        raise ValueError("That file isn't there any more — make the G-code again")
    return f
