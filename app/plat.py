"""What differs between Windows and Linux, in one place — the rest of the app is the same on both.

Windows: programs end in .exe, a venv's Python is Scripts\\python.exe, a process tree is stopped with taskkill.
Linux (e.g. Bazzite): no .exe, the Python is bin/python, the engines' own .so libraries sit next to them (their folder
goes on LD_LIBRARY_PATH), processes are stopped through /proc, folders open with xdg-open."""
import os
import signal
import subprocess
import threading
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


_JOB: list = []  # Windows: [(the job handle, kernel32, ntdll)] once made; [None] when it can't be made
_JOB_LOCK = threading.Lock()


def _job():
    """One Windows job for all the app's engines, set to KILL_ON_JOB_CLOSE: when this process ends in ANY way (window
    closed, crash, killed from Task Manager), Windows closes the job and ends every program in it and what they started."""
    with _JOB_LOCK:  # engines start from the server and from the render thread
        if _JOB:
            return _JOB[0]
        _JOB.append(None)
        if IS_WIN:
            try:
                import ctypes
                from ctypes import wintypes as w
                k32, nt = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("ntdll")
                k32.CreateJobObjectW.restype, k32.CreateJobObjectW.argtypes = w.HANDLE, [ctypes.c_void_p, w.LPCWSTR]
                k32.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
                k32.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
                nt.NtResumeProcess.restype, nt.NtResumeProcess.argtypes = ctypes.c_long, [w.HANDLE]

                class Basic(ctypes.Structure):
                    _fields_ = [("user_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", w.DWORD),
                                ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("procs", w.DWORD),
                                ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

                class Extended(ctypes.Structure):
                    _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("proc_mem", ctypes.c_size_t),
                                ("job_mem", ctypes.c_size_t), ("peak_proc", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
                info = Extended()
                info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                job = k32.CreateJobObjectW(None, None)
                if job and k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # 9 = extended
                    _JOB[0] = (job, k32, nt)
            except (OSError, AttributeError):
                pass
    return _JOB[0]


def spawn(args, **kw) -> subprocess.Popen:
    """subprocess.Popen for the app's engines. Windows: the program is tied to the app (the job above) BEFORE it runs a
    single instruction, so whatever it starts is tied too. Killing the app used to leave its engines running: 11
    llama-servers held the graphics memory and every picture failed (out of memory)."""
    j = _job()
    if j is None:
        return subprocess.Popen(args, **kw)
    job, k32, nt = j
    flags = kw.get("creationflags", 0)
    p = subprocess.Popen(args, **{**kw, "creationflags": flags | 0x4})  # 0x4 = CREATE_SUSPENDED
    k32.AssignProcessToJobObject(job, int(p._handle))
    if nt.NtResumeProcess(int(p._handle)) != 0:  # never leave it frozen: start it the plain way instead
        p.kill()
        return subprocess.Popen(args, **kw)
    return p


ENGINE_EXES = {"llama-server", "sd-cli", "sd", "tor", "blender", "runner", "freecadcmd", "orca-slicer"}


def kill_leftovers(root: Path) -> list[str]:
    """At start: this app's own engines still running from a run that didn't close normally (a crash, a forced stop).
    They keep their ports and graphics memory: an orphan 8B chat model blocked every picture (SDXL out of memory) and
    the app talked to an orphan chat server it couldn't unload. Only programs inside this app's engines folder (and
    its engines' Python servers), never the app itself. -> what was stopped."""
    eng, me = str(root / "engines").lower(), {os.getpid(), os.getppid()}
    procs: list[tuple[int, str, str]] = []
    try:
        if IS_WIN:
            ps = ("Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith('"
                  + eng.replace("'", "''") + "') } | ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)|$($_.CommandLine)\" }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                                 creationflags=NO_WINDOW).stdout
            for line in out.splitlines():
                pid, path, cmd = (line.split("|", 2) + ["", ""])[:3]
                if pid.strip().isdigit():
                    procs.append((int(pid), path, cmd))
        else:
            for d in os.listdir("/proc"):
                if d.isdigit():
                    try:
                        path = os.readlink(f"/proc/{d}/exe")
                        with open(f"/proc/{d}/cmdline", "rb") as f:
                            cmd = f.read().replace(b"\0", b" ").decode(errors="ignore")
                    except OSError:
                        continue
                    if path.lower().startswith(eng):
                        procs.append((int(d), path, cmd))
    except (OSError, subprocess.SubprocessError):
        return []
    stopped = []
    for pid, path, cmd in procs:
        name, low = Path(path).stem.lower(), cmd.lower()
        if pid in me or "localai.pyw" in low or "localai_linux" in low:
            continue  # the app itself runs on engines/python
        if name in ENGINE_EXES or ("python" in name and any(k in low for k in ("laya", "woosh", "run_sfx"))):
            kill_tree(pid)
            stopped.append(f"{Path(path).name} ({pid})")
    return stopped


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
