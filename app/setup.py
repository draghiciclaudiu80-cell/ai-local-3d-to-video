"""Settings › This PC: a setup check for whatever PC the app folder is on now (a copy on another PC, another drive).
Each check -> ok / warn (works, but something is missing or slower) / bad (needs fixing), a plain-words detail, and
a fix: a button the app can do itself ("shortcut", "drop_dirs") or a hint where to go. Nothing is installed or
downloaded by the check itself."""
import ctypes
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import DATA, ENGINES, NO_WINDOW, ROOT, load_settings, save_settings
from .plat import IS_WIN, exe, lib_env, memory_gb

EXE = ROOT / "Local AI.exe" if IS_WIN else ROOT / "start.sh"  # the starter
LINUX_BROWSERS = [  # an app window (no tabs / address bar) needs a Chromium-type browser; else the normal browser opens
    ("chromium-browser", None), ("chromium", None), ("google-chrome", None), ("google-chrome-stable", None),
    ("brave-browser", None), ("microsoft-edge", None), ("vivaldi", None),
    ("flatpak", "org.chromium.Chromium"), ("flatpak", "com.google.Chrome"), ("flatpak", "com.brave.Browser"),
    ("flatpak", "com.microsoft.Edge"), ("flatpak", "io.github.ungoogled_software.ungoogled_chromium"),
    ("flatpak", "com.vivaldi.Vivaldi")]


def linux_browser() -> list[str] | None:
    """The command that starts a Chromium-type browser on Linux (a flatpak one too), or None."""
    have_flatpak = shutil.which("flatpak")
    apps = ""
    if have_flatpak:
        try:
            apps = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True, text=True,
                                  timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            apps = ""
    for cmd, app in LINUX_BROWSERS:
        if app is None and shutil.which(cmd):
            return [shutil.which(cmd)]
        if app and have_flatpak and app in apps.split():
            return ["flatpak", "run", app]
    return None


def _ram_gb() -> float:
    if not IS_WIN:
        return memory_gb()[0]

    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullTotalPhys / 2 ** 30


_gpu_cache: list[str] | None = None


def gpus() -> list[str]:
    """The graphics chips llama.cpp can use (Vulkan) — asked once per start (~1 s)."""
    global _gpu_cache
    if _gpu_cache is None:
        try:
            out = subprocess.run([str(exe(ENGINES / "llama", "llama-server")), "--list-devices"], capture_output=True,
                                 text=True, encoding="utf-8", errors="ignore", timeout=30, creationflags=NO_WINDOW,
                                 env=lib_env(ENGINES / "llama"))
            _gpu_cache = [m.group(1).strip() for m in re.finditer(r"^\s*Vulkan\d+:\s*(.+?)(?:\(|$)", out.stdout + out.stderr, re.M)]
        except (OSError, subprocess.SubprocessError):
            _gpu_cache = []
    return _gpu_cache


def _desktop_dirs() -> list[Path]:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    dirs = [home / "Desktop", home / "OneDrive" / "Desktop", Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop"]
    return [d for d in dirs if d.exists()]


def _ps(script: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], capture_output=True,
                       text=True, encoding="utf-8", errors="ignore", timeout=60, creationflags=NO_WINDOW)
    return r.stdout.strip()


def _linux_desktop() -> Path:
    try:
        d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        d = ""
    return Path(d) if d and Path(d).exists() else Path.home() / "Desktop"


def _linux_entries() -> list[Path]:
    return [Path.home() / ".local/share/applications/local-ai.desktop", _linux_desktop() / "local-ai.desktop"]


def shortcuts() -> list[dict]:
    """Desktop / Start menu shortcuts that point into THIS app folder."""
    if not IS_WIN:  # Linux: .desktop files (the app menu + the desktop)
        found = []
        for f in _linux_entries():
            try:
                t = f.read_text(encoding="utf-8")
            except OSError:
                continue
            if str(EXE) in t:
                found.append({"file": str(f), "target": str(EXE), "starter": True})
        return found
    places = [str(d) for d in _desktop_dirs()] + [str(Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs")]
    lst = ",".join("'" + p.replace("'", "''") + "'" for p in places)
    out = _ps("$w = New-Object -ComObject WScript.Shell; foreach ($d in @(" + lst + ")) { if (Test-Path $d) { "
              "Get-ChildItem $d -Filter *.lnk | ForEach-Object { $s = $w.CreateShortcut($_.FullName); "
              "'{0}|{1}' -f $_.FullName, $s.TargetPath } } }")
    found = []
    for line in out.splitlines():
        if "|" in line:
            path, target = line.split("|", 1)
            if target and os.path.normcase(target).startswith(os.path.normcase(str(ROOT))):
                found.append({"file": path, "target": target, "starter": os.path.normcase(target) == os.path.normcase(str(EXE))})
    return found


def make_shortcuts() -> list[str]:
    """A 'Local AI' shortcut on the desktop and in the Start menu, pointing at Local AI.exe in this folder (old
    shortcuts into this folder are updated to the starter too)."""
    if not IS_WIN:  # Linux: the app menu entry + a desktop icon (marked trusted so a double-click starts it)
        made = []
        for f in _linux_entries():
            try:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("[Desktop Entry]\nType=Application\nName=Local AI\nComment=Private AI on this PC\n"
                             f"Exec=\"{EXE}\"\nPath={ROOT}\nIcon={ROOT / 'icon.png'}\nTerminal=false\n"
                             "Categories=Utility;Education;\n", encoding="utf-8")
                f.chmod(0o755)
                subprocess.run(["gio", "set", str(f), "metadata::trusted", "true"], capture_output=True, timeout=10)
                made.append(str(f))
            except (OSError, subprocess.SubprocessError):
                pass
        return made
    made, existing = [], shortcuts()
    on_desktop = [x for x in existing if "Start Menu" not in x["file"]]
    targets = [str(_desktop_dirs()[0] / "Local AI.lnk")] if _desktop_dirs() and not on_desktop else []  # no 2nd icon
    targets.append(str(Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Local AI.lnk"))
    targets += [x["file"] for x in existing if not x["starter"]]  # old shortcuts into this folder -> the starter
    for lnk in [t for t in dict.fromkeys(targets) if t]:
        q = lambda s: s.replace("'", "''")  # noqa: E731
        _ps(f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}'); $s.TargetPath = '{q(str(EXE))}'; "
            f"$s.WorkingDirectory = '{q(str(ROOT))}'; $s.IconLocation = '{q(str(ROOT / 'icon.ico'))}'; "
            "$s.Description = 'Local AI - private AI on this PC'; $s.Save()")
        if Path(lnk).exists():
            made.append(lnk)
    return made


def check() -> dict:
    from . import memory, plugins
    from .laya import laya
    from .models import active_path
    s = load_settings()
    items = []

    def add(name, state, detail, fix=None, hint=None):
        items.append({"name": name, "state": state, "detail": detail, **({"fix": fix} if fix else {}), **({"hint": hint} if hint else {})})

    add("App folder", "ok", str(ROOT) + (f" (moved here from {s['app_root']})" if s.get("app_root") and s["app_root"] != str(ROOT) else ""))
    if IS_WIN:
        add("Starter (Local AI.exe)", "ok" if EXE.exists() else "bad",
            "double-click it to start the app from this folder" if EXE.exists() else "missing — run tools\\launcher\\build.cmd")
        add("Python (bundled)", "ok" if (ROOT / "engines/python/python.exe").exists() else "warn",
            "engines\\python — the app doesn't need a Python installed on the PC" if (ROOT / "engines/python/python.exe").exists()
            else "not bundled: this copy uses a Python installed on the PC")
    else:
        add("Starter (start.sh)", "ok" if EXE.exists() else "bad",
            "the app menu entry \u201cLocal AI\u201d runs it" if EXE.exists() else "missing — run install.sh again")
        py = sorted((ROOT / "engines/python").glob("*/bin/python3*")) + sorted((ROOT / "engines/python").glob("bin/python3*"))
        add("Python (bundled)", "ok" if py else "warn",
            "engines/python — the app doesn't use the system's Python" if py else "missing — run install.sh again")
    sc = shortcuts()
    add("Shortcuts", "ok" if any(x["starter"] for x in sc) else "warn",
        f"{len(sc)} shortcut(s) to this folder" + ("" if any(x["starter"] for x in sc) else " — none uses the starter yet"),
        fix=None if any(x["starter"] for x in sc) else "shortcut")
    if IS_WIN:
        edge = any(Path(p, "Microsoft/Edge/Application/msedge.exe").exists()
                   for p in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")) if p)
        add("App window (Microsoft Edge)", "ok" if edge else "warn",
            "opens as its own private window" if edge else "Edge not found: the app opens in your normal browser instead")
    else:
        br = linux_browser()
        add("App window", "ok" if br else "warn", ("opens as its own window with " + br[-1].rsplit("/", 1)[-1]) if br else
            "no Chromium-type browser: the app opens as a tab in your normal browser",
            hint=None if br else "optional: install Chromium from the software store (Discover / Bazaar) for an app window")
    g, ram = gpus(), _ram_gb()
    add("Graphics chip", "ok" if g else "warn", ", ".join(g) if g else "no Vulkan graphics found: the chat runs on the processor "
        "(slower) and pictures / videos may not render", hint=None if g else "update the graphics driver (Vulkan)")
    add("Memory (RAM)", "ok" if ram >= 8 else "warn", f"{ram:.0f} GB usable by " + ("Windows" if IS_WIN else "Linux")
        + " (a built-in graphics chip keeps part of it)"
        + ("" if ram >= 8 else " — pick small models (the Models page shows what fits)"))
    free = shutil.disk_usage(ROOT).free / 2 ** 30
    add("Free disk space", "ok" if free >= 10 else "warn", f"{free:.0f} GB free on this drive")
    from . import voice
    from .models import installed_voices
    vs = installed_voices()
    add("Voice (speech)", "ok" if vs else "warn", f"{len(vs)} voice(s) installed" if vs else "none on this PC",
        hint=None if vs else "Models page › Voice")
    stt = s["active"].get("transcription") or "base"
    add("Speech-to-text", "ok" if voice.whisper_installed(stt) else "warn",
        f"Whisper {stt}" if voice.whisper_installed(stt) else "none on this PC",
        hint=None if voice.whisper_installed(stt) else "Models page › Transcription")
    for kind, label in (("text", "Chat model"), ("vision", "Computer-use (vision) model"), ("image", "Picture model"),
                        ("video", "Video model")):
        p = active_path(kind)
        state = "ok" if p else ("bad" if kind == "text" else "warn")
        add(label, state, (Path(p).name if p and ("/" in p or "\\" in p) else p) or "none on this PC",
            hint=None if p else "Models page \u203a " + {"text": "Text", "vision": "Computer use", "image": "Image", "video": "Video"}[kind])
    add("Memory model (meaning search)", "ok" if memory.emb.model() else "warn",
        "found" if memory.emb.model() else "missing: memory still works by words, not by meaning")
    add("Laya (fast decisions)", "ok" if laya.available() else "warn",
        "the real Laya is ready" if laya.available() else "missing: the chat model makes the decisions (a bit slower)")
    tor_exe = exe(ENGINES / "tor", "tor")
    add("Tor (private web)", "ok" if tor_exe.exists() else "warn",
        "built in" if tor_exe.exists() else "missing: web searches can't be private")
    pg, bl = plugins.get("picogk"), plugins.get("blender")
    if IS_WIN:
        add("3D engine (PicoGK)", "ok" if pg and pg["ready"] else "warn", "built in (with its own .NET)" if pg and pg["ready"] else "not set up")
        add("Blender (optional)", "ok" if bl and bl["ready"] else "warn",
            "found — furniture, rendered pictures, GLB files" if bl and bl["ready"] else "not installed: 3D still works with PicoGK",
            hint=None if bl and bl["ready"] else "install Blender from blender.org if you want it")
    else:  # PicoGK has no Linux version: its proven designs are translated and built in Blender
        add("3D engine (Blender)", "ok" if bl and bl["ready"] else "bad",
            "builds every 3D design (PicoGK's proven designs are translated for it; lattices / gyroids need Windows)"
            if bl and bl["ready"] else "missing — run install.sh again (it downloads Blender)")
    fc = plugins.get("freecad")
    add("Precise CAD (FreeCAD)", "ok" if fc and fc["ready"] else "warn",
        "found — exact holes for screws, STEP files for CNC" if fc and fc["ready"] else
        ("not installed: precise parts are built with the other engines" if IS_WIN else "missing — run install.sh again"),
        hint=None if fc and fc["ready"] else ("install FreeCAD from freecad.org (free)" if IS_WIN else None))
    from . import slicer  # G-code for the user's own printer, offline
    pr = slicer.printer()
    add(f"3D printing ({pr['name'].replace('Creality ', '')})", "ok" if slicer.orca() else "warn",
        f"OrcaSlicer found — G-code / 3MF for the {pr['bed'][0]} × {pr['bed'][1]} mm plate, sent over USB or to the SD card"
        if slicer.orca() else ("OrcaSlicer not installed: no G-code (STL files still work)" if IS_WIN else "missing — run install.sh again"),
        hint=None if slicer.orca() else ("install OrcaSlicer from orcaslicer.com (free, works offline)" if IS_WIN else None))
    missing = [d for d in s.get("model_dirs") or [] if not Path(d).exists()]
    if missing:
        add("Model folders", "warn", f"{len(missing)} folder(s) from the other PC don't exist here: " + "; ".join(missing[:3]),
            fix="drop_dirs")
    else:
        add("Model folders", "ok", f"{len(s.get('model_dirs') or [])} folder(s) searched for models")
    bad = sum(i["state"] == "bad" for i in items)
    warn = sum(i["state"] == "warn" for i in items)
    return {"items": items, "bad": bad, "warn": warn, "pending": bool(s.get("setup_pending")),
            "moved_from": s.get("app_root") if s.get("app_root") != str(ROOT) else None}


def fix(action: str) -> dict:
    if action == "shortcut":
        return {"made": make_shortcuts()}
    if action == "drop_dirs":
        s = load_settings()
        keep = [d for d in s.get("model_dirs") or [] if Path(d).exists()]
        save_settings({"model_dirs": keep})
        return {"kept": keep}
    if action == "seen":
        save_settings({"setup_pending": False})
        return {"ok": True}
    raise ValueError("unknown fix")
