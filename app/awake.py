"""Keeps the PC awake while the app is WORKING (an answer, a picture/video, a 3D build, a download, computer use) —
and lets it sleep normally when it's idle.

Why: the Legion Go went to sleep after 3 idle minutes on battery (5 on the charger) and that froze a Blender job
halfway. A Windows power request ("system required") stops the IDLE sleep; the screen may still turn off, the work
goes on behind it. It shows in `powercfg /requests` as "Local AI is working". The power button or closing the
device still puts it to sleep — that's the user's choice and nothing overrides it.
Linux (Bazzite & co.): the same with systemd's sleep lock — `systemd-inhibit --what=idle:sleep` runs while the app
works (`systemd-inhibit --list` shows "Local AI")."""
import ctypes
import shutil
import subprocess
import sys
import threading
import time

IS_WIN = sys.platform == "win32"
CHECK_EVERY = 15  # s — well under the shortest sleep timeout (3 min)
state = {"on": False, "why": [], "since": None, "ok": IS_WIN or bool(shutil.which("systemd-inhibit")), "error": ""}
_lock = threading.Lock()
_started = False
_SYSTEM_REQUIRED, _EXECUTION_REQUIRED = 1, 3  # POWER_REQUEST_TYPE
_handle = None
_inhibit: subprocess.Popen | None = None  # Linux: the running systemd-inhibit

if IS_WIN:
    from ctypes import wintypes

    class _Reason(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("Flags", wintypes.DWORD), ("SimpleReasonString", wintypes.LPWSTR)]


def _request(on: bool) -> None:
    """Sets / clears the power request. Falls back to SetThreadExecutionState (this thread holds it)."""
    global _handle, _inhibit
    if not IS_WIN:  # Linux: hold systemd's idle + sleep lock while working
        if on and (_inhibit is None or _inhibit.poll() is not None):
            _inhibit = subprocess.Popen(["systemd-inhibit", "--what=idle:sleep", "--who=Local AI", "--mode=block",
                                         "--why=Local AI is working (an answer, a picture, a video or a 3D build)",
                                         "sleep", "infinity"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        start_new_session=True)
        elif not on and _inhibit is not None:
            _inhibit.terminate()
            _inhibit = None
        return
    k = ctypes.windll.kernel32
    if _handle is None:
        k.PowerCreateRequest.restype = wintypes.HANDLE
        k.PowerCreateRequest.argtypes = [ctypes.POINTER(_Reason)]
        why = _Reason(0, 1, "Local AI is working (an answer, a picture, a video or a 3D build)")
        h = k.PowerCreateRequest(ctypes.byref(why))
        _handle = h if h and h != wintypes.HANDLE(-1).value else False
    if _handle:
        for t in (_SYSTEM_REQUIRED, _EXECUTION_REQUIRED):
            (k.PowerSetRequest if on else k.PowerClearRequest)(wintypes.HANDLE(_handle), t)
    else:  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED (| nothing = back to normal)
        k.SetThreadExecutionState(0x80000001 if on else 0x80000000)


def _loop(working) -> None:
    while True:
        try:
            why = [str(x) for x in working() or []]
            with _lock:
                if bool(why) != state["on"]:
                    _request(bool(why))
                    state.update(on=bool(why), since=time.time() if why else None)
                    print("keep-awake:", "ON — " + ", ".join(why) if why else "off (idle, the PC may sleep again)")
                state["why"] = why
        except Exception as e:  # noqa: BLE001 — never takes the app down
            state["error"] = repr(e)
        time.sleep(CHECK_EVERY)


def start(working) -> None:
    """working() -> a list of what's running now ([] = idle). Checked every 15 s in its own thread."""
    global _started
    if _started or not state["ok"]:
        return
    _started = True
    threading.Thread(target=_loop, args=(working,), daemon=True, name="keep-awake").start()


def stop() -> None:
    with _lock:
        if state["on"]:
            _request(False)
            state.update(on=False, why=[], since=None)
