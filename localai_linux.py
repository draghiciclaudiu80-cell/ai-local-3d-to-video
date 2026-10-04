"""Starts Local AI on Linux (made for Bazzite; Fedora / Ubuntu-like systems too): the server in the background and
the app in its own window — a Chromium-type browser in app mode (no tabs, no address bar), or a tab in your normal
browser when there is none (Bazzite comes with Firefox only; Chromium from the software store gives the app window).

Closing the app window stops everything, including the models. In a normal browser tab (or a Flatpak browser) the
app can't see the window close: it stops by itself when the page has been gone for 5 minutes and nothing is being
made. Started by start.sh (the app menu entry "Local AI" runs it)."""
import json
import os
import signal
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
TERMINAL = sys.stdout is not None and sys.stdout.isatty()
if not TERMINAL:  # started from the app menu: no console, everything goes to the log
    sys.stdout = sys.stderr = log

import httpx  # noqa: E402

from app.config import APP_PORT, DATA  # noqa: E402

URL = f"http://127.0.0.1:{APP_PORT}"
IDLE_STOP = 300  # s: a normal browser tab closed this long (and nothing being made) -> the app stops
# Private window (same as on Windows): no sync / sign-in, no background traffic, and the window itself can't reach the
# internet at all — only this PC (a dead proxy for everything else). Links you click open in your normal browser.
PRIVATE = ["--no-first-run", "--no-default-browser-check", "--disable-features=Translate", "--disable-sync",
           "--disable-background-networking", "--proxy-server=http://127.0.0.1:9",
           "--proxy-bypass-list=<-loopback>;127.0.0.1;localhost"]


def say(msg: str) -> None:
    print(msg, flush=True)
    if TERMINAL:
        log.write(msg + "\n")


def running() -> bool:
    try:
        return httpx.get(f"{URL}/api/health", timeout=1.5).status_code == 200
    except httpx.HTTPError:
        return False


def close_stale_window() -> None:
    """A window left over from a crashed start (its own profile) would take over the new one and exit at once."""
    subprocess.run(["pkill", "-f", f"--user-data-dir={DATA / 'window'}"], capture_output=True, check=False)


def private_profile() -> None:
    """The window's browser files: shredded if it ever signed in to an account; its caches shredded every start."""
    from app import wipe
    prof = DATA / "window"
    try:
        prefs = json.loads((prof / "Default" / "Preferences").read_text(encoding="utf-8"))
        signed_in = bool(prefs.get("account_info")) or bool(prefs.get("sync", {}).get("gaia_id"))
    except (OSError, ValueError):
        signed_in = False
    if signed_in:
        say("window profile was signed in to an account: shredding it")
        wipe.shred_tree(prof)
    for d in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
        wipe.shred_tree(prof / "Default" / d)


def open_window() -> tuple[subprocess.Popen | None, bool]:
    """-> (the browser process, whether closing it means "stop the app")."""
    from app.setup import linux_browser
    br = linux_browser()
    if not br:
        say("no Chromium-type browser: opening a tab in the normal browser")
        if not webbrowser.open(URL):
            subprocess.Popen(["xdg-open", URL], start_new_session=True)
        return None, False
    own = br[0] != "flatpak"  # a Flatpak browser can't use a profile inside the app folder (its sandbox): its own one
    args = [*br, f"--app={URL}", "--window-size=1400,900", "--class=LocalAI", *PRIVATE]
    if own:
        args.insert(len(br), f"--user-data-dir={DATA / 'window'}")
    say("app window: " + " ".join(br))
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return p, own


def main() -> None:
    say(f"\n--- start {time.ctime()} (Linux)")
    if running():  # already open: just show another window
        open_window()
        return
    try:  # moved to another folder / PC? saved paths follow the folder; a new PC gets the setup check once
        from app.config import relocate
        moved = relocate()
        if moved:
            say(f"relocated: {moved}")
    except Exception as e:  # noqa: BLE001 — never blocks the start
        say(f"relocate failed: {e}")
    import uvicorn
    from app import server as srv
    server = uvicorn.Server(uvicorn.Config(srv.app, host="127.0.0.1", port=APP_PORT, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    def stop(*_):
        say(f"--- stop {time.ctime()}")
        server.should_exit = True
        time.sleep(3)  # lets the app unload the models cleanly
        os._exit(0)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    for _ in range(240):
        if running():
            break
        time.sleep(0.5)
    else:
        say("the server did not start — see data/logs/app.log")
        return
    say(f"Local AI is running: {URL}")
    try:
        close_stale_window()
        private_profile()
    except Exception as e:  # noqa: BLE001 — never blocks the start
        say(f"window profile check failed: {e}")
    win, own = open_window()
    if win is not None and own:
        time.sleep(6)
        if win.poll() is None:  # its own window: closing it stops the app
            win.wait()
            stop()
    # a normal browser tab / a Flatpak window: stop when the page has been gone a while and nothing is being made
    while True:
        time.sleep(15)
        gone = time.time() - srv.LAST_SEEN["t"]
        if gone > IDLE_STOP and not srv.working_now():
            say(f"the app page has been closed for {int(gone)} s and nothing is being made: stopping")
            stop()


if __name__ == "__main__":
    main()
