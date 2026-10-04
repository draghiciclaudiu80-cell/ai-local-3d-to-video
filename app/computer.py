"""Computer use with a model that can SEE: screenshot -> the vision model proposes ONE action -> the user
approves it (or turns on auto-approve for this task) -> it runs -> new screenshot.

The Local AI window hides itself while the model looks at the screen and while an action runs — otherwise
the model sees (and clicks) the app instead of your desktop. It comes back for each approval.
Stop any time, or slam the mouse into a screen corner (emergency stop)."""
import base64
import ctypes
import io
import json
import re
import threading
import time
import uuid

from . import wipe
from .config import MEDIA, load_settings
from .llm import llm
from .models import active_path
from .plat import IS_WIN

if IS_WIN:  # Linux: computer use isn't available (Wayland lets no app drive the screen)
    from ctypes import wintypes

MAX_STEPS = 40
SEND_WIDTH = 1280  # screenshots are shrunk to this width before the model sees them
ACTIONS = ["click", "double_click", "right_click", "type", "key", "hotkey", "scroll", "open_app", "wait", "done", "fail"]


def _act(name: str, props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": {"thought": {"type": "string", "maxLength": 240}, "action": {"const": name}, **props},
            "required": ["thought", "action", *required]}


_XY = {"x": {"type": "integer", "minimum": 0, "maximum": 1000}, "y": {"type": "integer", "minimum": 0, "maximum": 1000}}
_TXT = {"type": "string", "minLength": 1}
# One shape per action, enforced by the engine: an action can't arrive without what it needs
# (before, the model could answer "open" with no app name, or "press" with no key).
SCHEMA = {"anyOf": [
    _act("click", _XY, ["x", "y"]), _act("double_click", _XY, ["x", "y"]), _act("right_click", _XY, ["x", "y"]),
    _act("type", {"text": _TXT}, ["text"]), _act("key", {"keys": _TXT}, ["keys"]), _act("hotkey", {"keys": _TXT}, ["keys"]),
    _act("scroll", {"amount": {"type": "integer", "minimum": -20, "maximum": 20}}, ["amount"]),
    _act("open_app", {"app": {"type": "string", "minLength": 2}}, ["app"]),
    _act("wait", {}, []), _act("done", {}, []), _act("fail", {}, [])]}
NEEDS = {"click": ("x", "y"), "double_click": ("x", "y"), "right_click": ("x", "y"), "type": ("text",),
         "key": ("keys",), "hotkey": ("keys",), "scroll": ("amount",), "open_app": ("app",)}

# Windows names people use -> what actually opens it. Opening these directly is instant and never picks the
# wrong search result (searching "My Computer" in Windows 11 suggests Control Panel).
PLACES = {
    "this pc": "shell:MyComputerFolder", "my computer": "shell:MyComputerFolder", "computer": "shell:MyComputerFolder",
    "my pc": "shell:MyComputerFolder", "this computer": "shell:MyComputerFolder",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "windows explorer": "explorer.exe", "files": "explorer.exe",
    "recycle bin": "shell:RecycleBinFolder", "trash": "shell:RecycleBinFolder",
    "downloads": "shell:Downloads", "download": "shell:Downloads", "documents": "shell:Personal",
    "my documents": "shell:Personal", "pictures": "shell:My Pictures", "music": "shell:My Music",
    "videos": "shell:My Video", "desktop": "shell:Desktop",
    "control panel": "control.exe", "settings": "ms-settings:", "windows settings": "ms-settings:",
    "task manager": "taskmgr.exe", "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
    "paint": "mspaint.exe", "command prompt": "cmd.exe", "cmd": "cmd.exe", "powershell": "powershell.exe",
    "terminal": "wt.exe", "windows terminal": "wt.exe", "edge": "microsoft-edge:", "microsoft edge": "microsoft-edge:",
    "browser": "microsoft-edge:", "internet": "microsoft-edge:", "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "snipping tool": "ms-screenclip:", "camera": "microsoft.windows.camera:", "store": "ms-windows-store:",
    "microsoft store": "ms-windows-store:", "clock": "ms-clock:", "wifi settings": "ms-settings:network-wifi",
    "bluetooth": "ms-settings:bluetooth", "display settings": "ms-settings:display", "sound settings": "ms-settings:sound",
}
PROMPT = """You operate a Windows 11 PC to complete the user's task. You see the current screen.
Choose exactly ONE next action.
- To start a program, folder or website, ALWAYS use open_app with its name (e.g. "Notepad", "This PC",
  "Downloads", "Settings", "youtube.com") — it opens it for you. On Windows 11 "My Computer" is called "This PC".
- To WRITE something new in Notepad, Word etc.: if the window title shows an existing file name (anything other
  than "Untitled"), press hotkey ctrl+n first for a new empty page. Never type into the user's existing files.
- Coordinates x and y are on a 0-1000 scale of the screenshot (0,0 = top-left, 1000,1000 = bottom-right);
  point at the centre of what you want to click.
- Prefer the keyboard: type text and numbers (e.g. "12+30=" in Calculator) instead of clicking many small buttons.
- If a step did not change the screen, don't repeat it — try something different.
- Check "the window in front" in the steps below: if the task's program is already open there, don't open it again.
- thought: ONE short sentence.
- When the task is finished, answer done. If it's impossible, answer fail and explain in thought.
- Never type passwords, PINs or payment details — answer fail and ask the user instead.
Actions: click / double_click / right_click (x,y) · type (text) · key (keys, e.g. "enter") ·
hotkey (keys, e.g. "ctrl+s") · scroll (amount, negative = down) · open_app (app) · wait · done · fail
TASK: {task}
STEPS SO FAR:
{history}"""


class Task:
    def __init__(self, goal: str):
        self.id, self.goal = uuid.uuid4().hex[:10], goal
        self.status = "thinking"   # thinking | waiting | running | done | failed | stopped
        self.steps: list[dict] = []
        self.pending: dict | None = None
        self.auto = False
        self.error: str | None = None
        self.decision = threading.Event()
        self.approved = False
        self.shot = ""
        self.shots: list[str] = []
        self.created = time.time()
        self.model_name = ""

    def public(self) -> dict:
        return {"id": self.id, "goal": self.goal, "status": self.status, "steps": self.steps[-30:],
                "pending": self.pending, "auto": self.auto, "error": self.error, "shot": self.shot,
                "model": self.model_name}


tasks: dict[str, Task] = {}


# ---------------------------------------------------------------- windows: hide ours, keep the right one in front
SW_MINIMIZE, SW_RESTORE = 6, 9
LIFT = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
if IS_WIN:
    user32, kernel32, dwmapi = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.dwmapi
    H = wintypes.HWND
    for _f, _a in {"IsWindowVisible": [H], "IsIconic": [H], "GetWindowTextLengthW": [H],
                   "GetWindowTextW": [H, wintypes.LPWSTR, ctypes.c_int], "ShowWindow": [H, ctypes.c_int],
                   "SetWindowPos": [H, H, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint],
                   "SetForegroundWindow": [H], "BringWindowToTop": [H], "GetWindowLongW": [H, ctypes.c_int],
                   "GetWindowThreadProcessId": [H, ctypes.c_void_p],
                   "AttachThreadInput": [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]}.items():
        getattr(user32, _f).argtypes = _a
    user32.GetForegroundWindow.restype = H
    dwmapi.DwmGetWindowAttribute.argtypes = [H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
else:  # Linux: the functions below are never reached (start() refuses), but the names must exist
    user32 = kernel32 = dwmapi = H = None


def _title(h) -> str:
    n = user32.GetWindowTextLengthW(h)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, buf, n + 1)
    return buf.value


def _ours(title: str) -> bool:
    return title == "Local AI" or title.startswith("Local AI - ")


def _app_windows() -> list[int]:
    """Top-level windows showing Local AI (the app window, or a browser tab titled 'Local AI')."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and _ours(_title(hwnd)):
            found.append(hwnd)
        return True
    user32.EnumWindows(each, 0)
    return found


def _windows(minimized: bool = False) -> list[tuple[int, str]]:
    """Real program windows (what Alt+Tab shows), front to back, without Local AI itself."""
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or (user32.IsIconic(hwnd) and not minimized):
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW: tooltips, floating bars
            return True
        cloaked = wintypes.DWORD()  # "visible" but not really on screen (e.g. suspended Store apps)
        dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
        t = _title(hwnd)
        if t and not cloaked.value and not _ours(t):
            found.append((hwnd, t))
        return True
    user32.EnumWindows(each, 0)
    return found


def front_window() -> str:
    """Title of the window in front — tells the model exactly what's open (e.g. 'notes.txt - Notepad').
    Windows can keep our minimized window 'in front'; then it's the top window the model actually sees."""
    h = user32.GetForegroundWindow()
    t = _title(h) if h else ""
    if not t or _ours(t) or user32.IsIconic(h):
        ws = _windows()
        t = ws[0][1] if ws else ""
    return "the desktop" if t == "Program Manager" else t


def screen_locked() -> bool:
    """True on the lock / PIN screen: the normal desktop can't be opened then."""
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    h = user32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not h:
        return True
    user32.CloseDesktop(wintypes.HANDLE(h))
    return False


def _focus(h) -> bool:
    """Puts a window in front WITH the keyboard. Windows stops background programs (like this app's server)
    from doing that: a program we opened stayed BEHIND the current window, the model never saw it and kept
    opening Chrome again. An empty mouse input makes us the last input source, which Windows accepts;
    joining the front window's input queue is the fallback."""
    if user32.IsIconic(h):
        user32.ShowWindow(h, SW_RESTORE)
    for attempt in range(3):
        if attempt == 1:
            user32.mouse_event(0x0001, 0, 0, 0, 0)  # MOUSEEVENTF_MOVE by 0 px: the pointer doesn't move
        me = them = 0
        if attempt == 2:
            me, them = kernel32.GetCurrentThreadId(), user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
            user32.AttachThreadInput(me, them, True)
            user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
        if them:
            user32.AttachThreadInput(me, them, False)
        time.sleep(0.2)
        if user32.GetForegroundWindow() == h:
            return True
    user32.SetWindowPos(h, -1, 0, 0, 0, 0, LIFT)  # refused: at least on top, so the model sees (and can click) it
    user32.SetWindowPos(h, -2, 0, 0, 0, 0, LIFT)
    return False


def hide_app() -> None:
    """Minimizes our window and gives the keyboard to the window under it — otherwise Windows can keep our
    minimized window 'in front' and typed keys would go into Local AI instead of what the model sees."""
    wins = [h for h in _app_windows() if not user32.IsIconic(h)]
    for h in wins:
        user32.ShowWindow(h, SW_MINIMIZE)
    if wins:
        time.sleep(0.7)  # let the minimize animation finish before the screenshot
    fg = user32.GetForegroundWindow()
    if not fg or _ours(_title(fg)) or user32.IsIconic(fg):
        top = _windows()
        if top:
            _focus(top[0][0])


def show_app() -> None:
    """Brings the window back in front (lifted with a brief 'always on top' if Windows refuses the focus)."""
    for h in _app_windows():
        user32.ShowWindow(h, SW_RESTORE)
        _focus(h)


# ---------------------------------------------------------------- seeing + acting
def _screenshot(task: Task):
    import mss
    from PIL import Image
    grab = getattr(mss, "MSS", None) or mss.mss
    with grab() as s:
        raw = s.grab(s.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    real = img.size
    # A new file per step: overwriting one file while the page is loading it breaks the download.
    name = f"cu-{task.id}-{len(task.shots)}.png"
    img.save(MEDIA / name)
    task.shots.append(name)
    task.shot = name
    for old in task.shots[:-3]:
        wipe.shred(MEDIA / old)  # a picture of your screen
    task.shots = task.shots[-3:]
    small = img.resize((SEND_WIDTH, round(real[1] * SEND_WIDTH / real[0])))
    buf = io.BytesIO()
    small.save(buf, format="JPEG", quality=80)
    thumb = list(img.convert("L").resize((320, 200)).tobytes())  # to notice "nothing changed" (small text counts)
    return base64.b64encode(buf.getvalue()).decode(), real, thumb


def _changed(a: list[int] | None, b: list[int]) -> bool:
    """Even a typed word changes a few dozen pixels clearly; screen noise changes none by that much."""
    if a is None:
        return True
    return sum(1 for x, y in zip(a, b) if abs(x - y) > 24) >= 6


def _execute(a: dict, real: tuple[int, int]) -> None:
    import pyautogui
    pyautogui.FAILSAFE = True  # mouse into a corner = emergency stop
    x = round((a.get("x") or 0) / 1000 * real[0])
    y = round((a.get("y") or 0) / 1000 * real[1])
    act = a["action"]
    if act == "click":
        pyautogui.click(x, y)
    elif act == "double_click":
        pyautogui.doubleClick(x, y)
    elif act == "right_click":
        pyautogui.rightClick(x, y)
    elif act == "type":
        pyautogui.write(a["text"], interval=0.02)
    elif act == "key":
        pyautogui.press(_key(a["keys"]))
    elif act == "hotkey":
        pyautogui.hotkey(*[_key(k) for k in a["keys"].split("+") if k.strip()])
    elif act == "scroll":
        pyautogui.scroll(int(a["amount"]) * 100)
    elif act == "open_app":
        return _open(a["app"])
    elif act == "wait":
        time.sleep(2)


def _key(k: str) -> str:
    k = k.strip().lower()
    return {"windows": "win", "return": "enter", "escape": "esc", "control": "ctrl", "del": "delete"}.get(k, k)


BROWSERS = ("Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Brave", "Opera")
WEB = re.compile(r"^(https?://\S+|www\.\S+|[\w-]+(\.[\w-]+)*\.(com|org|net|ro|io|ai|dev|co|uk|de|eu|edu|gov|tv|me|app)(/\S*)?)$")


def _open(name: str) -> str:
    """Opens a program, folder or website: known Windows names and web addresses directly, anything else
    through the Start menu search (works for every installed app)."""
    import os
    import pyautogui
    raw = name.strip().strip('"')
    n = raw.lower().removesuffix(".exe").strip()
    target = PLACES.get(n) or PLACES.get(n.removeprefix("the ").removesuffix(" app").removesuffix(" folder"))
    before = {h for h, _ in _windows(minimized=True)}
    if target:
        os.startfile(target)
        how = f"opened directly: {target}"
    elif WEB.match(n):
        os.startfile(n if n.startswith("http") else "https://" + n)
        how = "opened in the web browser"
    elif os.path.exists(raw):
        os.startfile(raw)
        how = "opened the file/folder"
    else:
        pyautogui.press("win")
        time.sleep(0.8)
        pyautogui.write(raw, interval=0.03)
        time.sleep(1.2)
        pyautogui.press("enter")
        how = "searched the Start menu and pressed Enter"
    # Wait for its window, then bring it to the front (Windows may open it behind the current window).
    new = []
    for _ in range(20):  # up to ~6 s
        time.sleep(0.3)
        new = [w for w in _windows(minimized=True) if w[0] not in before]
        if new:
            break
    if not new:  # nothing new: it was already open (a new tab / the same window) — find it by name
        word = n.split()[-1] if n.split() else n
        web = how == "opened in the web browser"
        new = [(h, t) for h, t in _windows(minimized=True) if n in t.lower() or (len(word) > 2 and word in t.lower())
               or (web and any(b in t for b in BROWSERS))]
    if not new:
        return how + "; no window for it appeared yet"
    time.sleep(0.5)  # let it draw itself
    _focus(new[0][0])
    return how + f"; its window “{_title(new[0][0]) or new[0][1]}” is now in front"


def _describe(a: dict) -> str:
    act = a["action"]
    if act in ("click", "double_click", "right_click"):
        return f"{act.replace('_', ' ')} at ({a.get('x')}, {a.get('y')})"
    if act == "type":
        return f'type "{a.get("text", "")[:60]}"'
    if act in ("key", "hotkey"):
        return f"press {a.get('keys') or a.get('text')}"
    if act == "open_app":
        return f"open {a.get('app') or a.get('text')}"
    if act == "scroll":
        return f"scroll {a.get('amount')}"
    return act


MAIN_LOOP = None  # the server's event loop (set at startup): the model is shared with Chat


def _call(coro):
    import asyncio
    return asyncio.run_coroutine_threadsafe(coro, MAIN_LOOP).result()


def _decide(task: Task, img: str) -> dict:
    history = "\n".join(f"{i + 1}. {st['desc']} -> {st['result']}" for i, st in enumerate(task.steps[-12:])) or "(none)"
    msg = [{"role": "user", "content": [
        {"type": "text", "text": PROMPT.format(task=task.goal, history=history)},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]}]
    for _attempt in range(2):  # a malformed answer gets one retry
        llm.busy += 1
        try:  # thinking off: thinking models otherwise put the answer in their reasoning, not the reply
            reply = _call(llm.complete(msg, temperature=0.1, max_tokens=800, chat_template_kwargs={"enable_thinking": False},
                                       response_format={"type": "json_schema", "json_schema": {"name": "action", "schema": SCHEMA}}))
        finally:
            llm.busy -= 1
        try:
            a = json.loads(reply.get("content") or reply.get("reasoning_content") or "{}")
        except ValueError:
            a = None
        if isinstance(a, dict) and a.get("action") in ACTIONS and \
                all(a.get(k) not in (None, "") for k in NEEDS.get(a["action"], ())):
            return a
    raise RuntimeError("The vision model didn't give a usable answer — try a different model in Models › Computer use")


def _run(task: Task) -> None:
    last_thumb, repeats, still = None, 0, 0
    try:
        model = active_path("vision")
        if not model:
            raise RuntimeError("No model that can see the screen — get one in Models › Computer use")
        task.model_name = model.rsplit("\\", 1)[-1].removesuffix(".gguf")
        ctx = max(8192, int(load_settings()["ctx"]))
        for _ in range(600):  # let a chat finish its reply before its model is swapped for this one
            if llm.busy <= 0:
                break
            time.sleep(0.5)
        for _ in range(MAX_STEPS):
            if task.status == "stopped":
                return
            task.status, task.pending = "thinking", None
            if screen_locked():  # never press keys on the lock screen (they'd go into the PIN box)
                raise RuntimeError("Your PC is locked — unlock it, then start the task again.")
            from .jobs import renderer  # (re)load every step: a render may have unloaded it; share the GPU safely
            _call(llm.ensure(model, ctx, not renderer.busy()))
            hide_app()
            img, real, thumb = _screenshot(task)
            if task.steps and task.steps[-1]["result"] == "done":
                front = task.steps[-1].get("front")
                moved = _changed(last_thumb, thumb) or front != task.steps[-1].get("front_before")
                task.steps[-1]["result"] = ("done — the screen changed" if moved else "done — but NOTHING changed on screen") +                     (f"; the window in front is now “{front}”" if front else "")
                still = 0 if moved else still + 1
            last_thumb = thumb
            if not task.auto:
                show_app()  # back for the user while the model thinks and waits for approval
            if still >= 2:
                raise RuntimeError("Stopped: the last steps didn't change anything on screen, so the model seems stuck. "
                                   "Try describing the task differently.")
            a = _decide(task, img)
            if task.status == "stopped":
                return
            if a["action"] in ("done", "fail"):
                task.steps.append({"desc": a["action"], "thought": a.get("thought", ""), "result": "", "time": time.time()})
                task.status = "done" if a["action"] == "done" else "failed"
                task.error = None if a["action"] == "done" else a.get("thought")
                return
            a["desc"] = _describe(a)
            repeats = repeats + 1 if task.steps and task.steps[-1].get("act") == a["desc"] else 0
            if repeats >= 2:
                raise RuntimeError(f"Stopped: the model wanted to “{a['desc']}” for the third time in a row — it seems stuck. "
                                   "Try describing the task differently.")
            task.pending = a
            if not task.auto:
                task.status = "waiting"
                task.decision.clear()
                task.decision.wait()
                if task.status == "stopped":
                    return
                if not task.approved:
                    task.steps.append({"desc": a["desc"], "act": a["desc"], "thought": a.get("thought", ""),
                                       "result": "skipped", "time": time.time()})
                    continue
            task.status = "running"
            if screen_locked():
                raise RuntimeError("Your PC got locked — stopped before doing anything.")
            hide_app()  # the action must land on your desktop, not on this window
            front_before = front_window()
            try:
                how = _execute(a, real)
            except Exception as e:  # noqa: BLE001 — includes the corner emergency stop
                import pyautogui
                if isinstance(e, pyautogui.FailSafeException):
                    task.status, task.error = "stopped", "Emergency stop: the mouse was moved into a screen corner."
                else:
                    task.status, task.error = "failed", f"That step failed: {e}"
                return
            time.sleep(1.2)  # let the screen update
            front = front_window()
            task.steps.append({"desc": a["desc"] + (f" ({how})" if how else ""), "act": a["desc"], "thought": a.get("thought", ""),
                               "time": time.time(), "result": "done", "front": front, "front_before": front_before})
        task.status, task.error = "failed", f"Stopped after {MAX_STEPS} steps"
    except Exception as e:  # noqa: BLE001
        task.status, task.error = "failed", str(e)[:300]
    finally:
        task.pending = None
        show_app()


def active() -> "Task | None":
    return next((t for t in tasks.values() if t.status in ("thinking", "waiting", "running")), None)


def start(goal: str) -> Task:
    if not IS_WIN:
        raise RuntimeError("Computer use works on Windows only for now — on Linux (Wayland) apps aren't allowed to see "
                           "and control the screen")
    if active():
        raise RuntimeError("A computer task is already running — stop it first")
    t = Task(goal)
    tasks[t.id] = t
    threading.Thread(target=_run, args=(t,), daemon=True).start()
    return t


def decide(tid: str, approve: bool, auto: bool = False) -> None:
    t = tasks[tid]
    t.approved, t.auto = approve, t.auto or auto
    t.decision.set()


def stop(tid: str) -> None:
    t = tasks.get(tid)
    if t:
        t.status = "stopped"
        t.decision.set()
