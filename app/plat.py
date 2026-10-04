"""What differs between Windows and Linux, in one place — the rest of the app is the same on both.

Windows: programs end in .exe, a venv's Python is Scripts\\python.exe, a process tree is stopped with taskkill.
Linux (e.g. Bazzite): no .exe, the Python is bin/python, the engines' own .so libraries sit next to them (their folder
goes on LD_LIBRARY_PATH), processes are stopped through /proc, folders open with xdg-open."""
import os
import signal
import subprocess
import time
from pathlib import Path

IS_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def exe(folder: Path, name: str) -> Path:
    """A program inside the app: llama-server.exe on Windows, llama-server on Linux."""
    return Path(folder) / (name + (".exe" if IS_WIN else ""))


def venv_python(venv: Path) -> Path:
    return Path(venv) / ("Scripts/python.exe" if IS_WIN else "bin/python")


def lib_env(folder: Path, env: dict | None = None) -> dict | None:
    """Linux: the engine's folder on LD_LIBRARY_PATH (llama.cpp / stable-diffusion.cpp / Tor ship their own .so files
    next to the program). Windows: None = the normal environment (DLLs next to the .exe are found anyway)."""
    if IS_WIN:
        return env
    e = dict(env if env is not None else os.environ)
    e["LD_LIBRARY_PATH"] = str(folder) + (os.pathsep + e["LD_LIBRARY_PATH"] if e.get("LD_LIBRARY_PATH") else "")
    return e


def _tree(pid: int) -> list[int]:
    """Linux: the process and all its children (read from /proc), parents first."""
    kids: dict[int, list[int]] = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                with open(f"/proc/{d}/stat", encoding="utf-8", errors="ignore") as f:
                    ppid = int(f.read().rsplit(")", 1)[1].split()[1])
                kids.setdefault(ppid, []).append(int(d))
            except (OSError, ValueError, IndexError):
                pass
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        out.append(p)
        todo += kids.get(p, [])
    return out


def kill_tree(pid: int) -> None:
    """Stops a program and everything it started (a venv's python.exe on Windows is only a launcher: terminate()
    left the real Laya running)."""
    if IS_WIN:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
        return
    procs = _tree(pid)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for p in reversed(procs):  # children first
            try:
                os.kill(p, sig)
            except OSError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(1.5)
            procs = [p for p in procs if os.path.exists(f"/proc/{p}")]
            if not procs:
                return


def open_path(target) -> None:
    """A folder in the file manager (Explorer / Dolphin / Files)."""
    if IS_WIN:
        os.startfile(str(target))  # noqa: S606 — a fixed app folder
    else:
        subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


def memory_gb() -> tuple[float, float]:
    """(total, available) RAM in GB."""
    if IS_WIN:
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                       [(n, ctypes.c_ulonglong) for n in ("total", "avail", "tpf", "apf", "tv", "av", "ave")]
        m = MEM()
        m.len = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 2 ** 30, m.avail / 2 ** 30
    info = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        return 0.0, 0.0
    return info.get("MemTotal", 0) / 2 ** 30, info.get("MemAvailable", info.get("MemFree", 0)) / 2 ** 30


def cpu_name() -> str:
    if IS_WIN:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor).Name"],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip()
        return out.splitlines()[0].strip() if out else "?"
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "?"
