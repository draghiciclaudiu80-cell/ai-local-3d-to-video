"""Reads this PC once and rates every model for it, so nothing gets loaded that would freeze the machine."""
import ctypes
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import MODELS, NO_WINDOW


@lru_cache(maxsize=1)
def hardware() -> dict:
    from .plat import IS_WIN
    if not IS_WIN:  # Linux: RAM / CPU from /proc, graphics = what llama.cpp's Vulkan sees (Mesa RADV on AMD)
        from .plat import cpu_name, memory_gb
        from .setup import gpus
        g = gpus()
        return {"cpu": cpu_name(), "gpus": g, "gpu": bool(g), "ram_gb": round(memory_gb()[0])}

    class MEM(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong)] + \
                   [(n, ctypes.c_ulonglong) for n in ("total", "avail", "tpf", "apf", "tv", "av", "ave")]
    m = MEM()
    m.len = ctypes.sizeof(MEM)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    # Installed RAM, not "visible to Windows": an iGPU reserves part of it but models can still use it.
    kb = ctypes.c_ulonglong(0)
    installed = kb.value * 1024 if ctypes.windll.kernel32.GetPhysicallyInstalledSystemMemory(ctypes.byref(kb)) else 0
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "(Get-CimInstance Win32_Processor).Name; (Get-CimInstance Win32_VideoController).Name"],
                         capture_output=True, text=True, creationflags=NO_WINDOW).stdout.strip().splitlines()
    gpus = [g.strip() for g in out[1:] if g.strip()]
    gpu = Path(r"C:\Windows\System32\vulkan-1.dll").exists() and \
        any(k in g for g in gpus for k in ("Radeon", "NVIDIA", "GeForce", "RTX", "Arc"))
    return {"cpu": out[0].strip() if out else "?", "gpus": gpus, "gpu": gpu,
            "ram_gb": round(max(installed, m.total) / 2**30)}


def rate(size_gb: float, needs_gpu: bool = False) -> tuple[str, str]:
    """good = comfortable · tight = fits but uses most memory · no = would overload this PC."""
    hw = hardware()
    need = size_gb * 1.25 + 2  # weights + context/activations + app overhead
    if need > hw["ram_gb"] * 0.9:
        return "no", f"Needs ~{need:.0f} GB memory, this PC has {hw['ram_gb']} GB"
    if needs_gpu and not hw["gpu"]:
        return "tight", "No graphics card found — runs on the CPU, very slow"
    if need > hw["ram_gb"] * 0.6:
        return "tight", "Fits, but uses most of your memory — close other apps"
    return "good", "Runs well on this PC"


def free_disk_gb() -> float:
    return shutil.disk_usage(MODELS).free / 1e9
