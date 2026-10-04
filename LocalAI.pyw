"""Starts Local AI: runs the server in the background and opens the app in its own window (Microsoft Edge
in app mode — no tabs, no address bar). Closing the window stops everything, including the models."""
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
(ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
log = open(ROOT / "data" / "logs" / "app.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log  # pythonw has no console

import httpx  # noqa: E402

from app.config import APP_PORT, DATA  # noqa: E402

URL = f"http://127.0.0.1:{APP_PORT}"


def running() -> bool:
    try:
        return httpx.get(f"{URL}/api/health", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


def edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return str(p)
    return None


def close_stale_window() -> None:
    """A window left over from a crashed start (its page can't reach the server) would take over the new window
    and make Edge exit at once — and the app with it. Only this app's own Edge profile is closed."""
    profile = str(DATA / "window").replace("'", "''")
    subprocess.run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like "
                    f"'*{profile}*' }} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"],
                   creationflags=0x08000000, timeout=30, check=False)


# Private window: Edge's automatic Microsoft sign-in (and with it sync) is off, and the window can't reach the
# internet at all — only this PC (a dead proxy for everything else; your own PC is always reached directly).
# Links you click open in your normal browser. Tested: without msImplicitSignin off, a new profile signed in by itself.
PRIVATE = ["--no-first-run", "--no-default-browser-check", "--disable-features=Translate,msImplicitSignin",
           "--disable-sync", "--disable-background-networking", "--proxy-server=http://127.0.0.1:9",
           "--proxy-bypass-list=<-loopback>;127.0.0.1;localhost"]


def private_profile() -> None:
    """The window's browser files: if Edge ever signed in to an account there, they're shredded (a fresh, signed-out
    profile is made); its disk cache is shredded at every start (chats / pictures aren't cached any more anyway)."""
    from app import wipe
    prof = DATA / "window"
    try:
        prefs = json.loads((prof / "Default" / "Preferences").read_text(encoding="utf-8"))
        signed_in = bool(prefs.get("account_info")) or bool(prefs.get("sync", {}).get("gaia_id"))
    except (OSError, ValueError):
        signed_in = False
    if signed_in:
        print("window profile was signed in to an account: shredding it")
        wipe.shred_tree(prof)
    for d in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
        wipe.shred_tree(prof / "Default" / d)


def open_window() -> subprocess.Popen | None:
    exe = edge()
    if not exe:  # no Edge: use the normal browser (the app then keeps running until you log off)
        webbrowser.open(URL)
        return None
    return subprocess.Popen([exe, f"--app={URL}", f"--user-data-dir={DATA / 'window'}", "--window-size=1400,900",
                             *PRIVATE])


def main() -> None:
    print(f"\n--- start {time.ctime()}")
    if running():  # already open: just show another window
        open_window()
        return
    try:  # moved to another folder / PC? saved paths follow the folder; a new PC gets the setup check once
        from app.config import relocate
        moved = relocate()
        if moved:
            print("relocated:", moved)
    except Exception as e:  # noqa: BLE001 — never blocks the start
        print("relocate failed:", e)
    import uvicorn
    from app.server import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=APP_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(120):
        if running():
            break
        time.sleep(0.5)
    else:
        print("server did not start")
        return
    try:
        close_stale_window()
    except (OSError, subprocess.SubprocessError) as e:
        print("could not check for an old window:", e)
    try:
        private_profile()
    except Exception as e:  # noqa: BLE001 — never blocks the start
        print("private profile check failed:", e)
    win = open_window()
    if win is None:
        while True:
            time.sleep(3600)
    win.wait()  # the user closed the window
    server.should_exit = True
    time.sleep(3)  # lets the app unload the models cleanly
    print(f"--- stop {time.ctime()}")


if __name__ == "__main__":
    main()
