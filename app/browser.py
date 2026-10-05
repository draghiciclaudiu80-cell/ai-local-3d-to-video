"""The app's own web browser (Computer use › Browser): a private Microsoft Edge (Chromium on Linux) running HIDDEN
(headless) with its own profile in data/browser, driven through the DevTools protocol. Its tabs show up in the app as
live pictures you can click, scroll and type into; the AI uses the same browser for web tasks — no hiding the app
window, nothing clicked on your desktop. Pages are untrusted: what the AI reads from them is data, never orders.
Downloads are blocked. Optionally through Tor (the same SOCKS port as the web search)."""
import asyncio
import json
import shutil
import socket
import subprocess
from pathlib import Path
from urllib.parse import quote_plus

import httpx
from websockets.asyncio.client import connect

from .config import DATA, LOGS, NO_WINDOW, load_settings
from .plat import IS_WIN, kill_tree, spawn

PROFILE = DATA / "browser"
SIZE = (1280, 800)  # the page size the browser draws (CSS pixels)
HOME = "https://duckduckgo.com/"
KEYS = {"enter": ("Enter", 13, "\r"), "return": ("Enter", 13, "\r"), "tab": ("Tab", 9, ""), "backspace": ("Backspace", 8, ""),
        "escape": ("Escape", 27, ""), "esc": ("Escape", 27, ""), "delete": ("Delete", 46, ""), "del": ("Delete", 46, ""),
        "up": ("ArrowUp", 38, ""), "down": ("ArrowDown", 40, ""), "left": ("ArrowLeft", 37, ""), "right": ("ArrowRight", 39, ""),
        "arrowup": ("ArrowUp", 38, ""), "arrowdown": ("ArrowDown", 40, ""), "arrowleft": ("ArrowLeft", 37, ""),
        "arrowright": ("ArrowRight", 39, ""), "home": ("Home", 36, ""), "end": ("End", 35, ""), "pageup": ("PageUp", 33, ""),
        "pagedown": ("PageDown", 34, ""), "space": (" ", 32, " ")}
MODS = {"alt": 1, "ctrl": 2, "control": 2, "meta": 4, "win": 4, "cmd": 4, "shift": 8}
# The app maker's use test (test_html): no dialogs that would hang the tab, no form sending the page away, and
# __phase(what) adds "(when <what>)" to the errors that happen while it's being done.
USE_SETUP = ("window.alert=()=>{};window.confirm=()=>true;window.prompt=()=>'';window.print=()=>{};window.open=()=>null;"
             "addEventListener('submit',e=>e.preventDefault(),true);window.__phase=l=>{const e=window.__errs||[];"
             "for(let i=window.__from||0;i<e.length;i++)if(window.__label&&!/ \\(when /.test(e[i]))e[i]+=' (when '+"
             "window.__label+')';window.__from=e.length;window.__label=l};")
USE_CONTROLS = r"""(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms)),vis=e=>!e.disabled&&e.getClientRects().length>0;
let b=0,k=0;
for(const el of [...document.querySelectorAll('button,[role=button],input[type=button],input[type=submit]')].filter(vis).slice(0,24)){
 __phase('pressing the “'+((el.innerText||el.value||el.title||el.id||'?').trim().slice(0,30))+'” button');
 try{el.click()}catch(e){__errs.push(String(e))}b++;await s(60)}
for(const i of [...document.querySelectorAll('input,select,textarea')].filter(vis).filter(i=>!['button','submit','file','hidden','reset','image'].includes(i.type)).slice(0,16)){
 __phase('changing the '+(i.id||i.name||i.type||'')+' control');
 try{if(i.tagName==='SELECT'){if(i.options.length>1)i.selectedIndex=(i.selectedIndex+1)%i.options.length}
  else if(i.type==='checkbox'||i.type==='radio')i.checked=!i.checked;
  else if(i.type==='range'||i.type==='number'){const lo=i.min!==''?+i.min:0,hi=i.max!==''?+i.max:lo+10;i.value=String(Math.round(lo+(hi-lo)*0.7))}
  else if(i.type==='color')i.value='#3366ff';else if(i.type==='date')i.value='2026-01-15';else if(i.type==='time')i.value='12:30';
  else i.value='test 12';
  i.dispatchEvent(new Event('input',{bubbles:true}));i.dispatchEvent(new Event('change',{bubbles:true}));
  if(i.type==='text'||i.tagName==='TEXTAREA')i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
 }catch(e){__errs.push(String(e))}k++;await s(40)}
__phase('');return JSON.stringify([b,k])})()"""
# Things piled up: 4+ visible items with the SAME box but different text (a solitaire's 29 face-up cards all at one
# spot passed every error check). A face-down pile (no text / the same back) is fine.
LAYOUT_PROBE = r"""(()=>{const g=new Map();for(const e of document.body.querySelectorAll('*')){if(e.children.length>3)continue;
const r=e.getBoundingClientRect();if(r.width<8||r.height<8)continue;const s=getComputedStyle(e);
if(s.visibility==='hidden'||+s.opacity===0)continue;const k=[r.left,r.top,r.width,r.height].map(Math.round).join(',');
if(!g.has(k))g.set(k,[]);g.get(k).push((e.innerText||'').trim().replace(/\s+/g,' ').slice(0,12))}
let w=null;for(const[k,t]of g){const d=[...new Set(t.filter(Boolean))];if(t.length>=4&&d.length>=3&&(!w||t.length>w.n)){
const[x,y]=k.split(',');w={n:t.length,x:+x,y:+y,ex:d.slice(0,3)}}}return JSON.stringify(w)})()"""
USE_KEYS = [("ArrowLeft", "ArrowLeft", 37, "", 0), ("ArrowRight", "ArrowRight", 39, "", 0), ("ArrowUp", "ArrowUp", 38, "", 0),
            ("ArrowDown", "ArrowDown", 40, "", 0), (" ", "Space", 32, " ", 0), ("Enter", "Enter", 13, "\r", 0),
            ("a", "KeyA", 65, "a", 0), ("w", "KeyW", 87, "w", 0), ("z", "KeyZ", 90, "", 2), ("Escape", "Escape", 27, "", 0)]


def engine() -> list[str] | None:
    """The browser program: Edge on Windows (always there on Windows 10 / 11), Chromium / Chrome / Edge on Linux."""
    if IS_WIN:
        import os
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            p = Path(base or "-") / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if p.exists():
                return [str(p)]
        return None
    for name in ("chromium", "chromium-browser", "google-chrome", "microsoft-edge"):
        if shutil.which(name):
            return [shutil.which(name)]
    return None


def as_url(text: str) -> str:
    """What was typed in the address bar -> a page: an address as it is, anything else a private search."""
    t = text.strip()
    if not t:
        return HOME
    if t.startswith(("http://", "https://", "about:")):
        return t
    if " " not in t and "." in t.split("/")[0]:
        return "https://" + t
    return "https://duckduckgo.com/?q=" + quote_plus(t)


class CDP:
    """One DevTools connection (a tab or the browser itself): numbered requests, answers matched by number."""

    def __init__(self, ws):
        self.ws, self.n, self.wait = ws, 0, {}
        self.reader = asyncio.ensure_future(self._read())

    async def _read(self):
        try:
            async for msg in self.ws:
                d = json.loads(msg)
                fut = self.wait.pop(d.get("id"), None)
                if fut and not fut.done():
                    fut.set_result(d)
        except Exception:  # noqa: BLE001 — the tab closed: every waiting request fails below
            pass
        for fut in self.wait.values():
            if not fut.done():
                fut.set_exception(ConnectionError("the tab closed"))

    @property
    def alive(self) -> bool:
        return not self.reader.done()

    async def send(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        self.n += 1
        fut = asyncio.get_running_loop().create_future()
        self.wait[self.n] = fut
        await self.ws.send(json.dumps({"id": self.n, "method": method, "params": params or {}}))
        d = await asyncio.wait_for(fut, timeout)
        if "error" in d:
            raise RuntimeError(d["error"].get("message", "browser error"))
        return d.get("result", {})

    async def close(self):
        self.reader.cancel()
        try:
            await self.ws.close()
        except Exception:  # noqa: BLE001
            pass


class Browser:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self.tor = False
        self.active: str | None = None
        self.conns: dict[str, CDP] = {}
        self.lock = asyncio.Lock()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def ensure(self, tor: bool | None = None) -> None:
        """Starts the hidden browser (or restarts it when Tor was switched on / off: that's a start option)."""
        if tor is None:  # no choice given (e.g. the AI's task): an open browser stays as you set it
            want_tor = self.tor if self.running() else load_settings().get("tor", True)
        else:
            want_tor = tor
        async with self.lock:
            if self.running() and self.tor == want_tor:
                return
            urls = [t["url"] for t in await self._list()] if self.running() else []
            await self._stop()
            exe = engine()
            if not exe:
                raise RuntimeError("No browser found for the app's browser (Microsoft Edge / Chromium)")
            if want_tor:
                from .tor import tor as tor_proc
                await asyncio.to_thread(tor_proc.ready)  # starts Tor if needed (connected in ~10-30 s)
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self.port = s.getsockname()[1]
            PROFILE.mkdir(parents=True, exist_ok=True)
            args = [*exe, "--headless=new", f"--remote-debugging-port={self.port}", "--remote-debugging-address=127.0.0.1",
                    f"--user-data-dir={PROFILE}", f"--window-size={SIZE[0]},{SIZE[1]}", "--no-first-run",
                    "--no-default-browser-check", "--disable-sync", "--disable-background-networking", "--no-pings",
                    "--disable-features=msImplicitSignin,msEdgeShoppingAssistant,msEdgeCollections",
                    "--disable-extensions", "about:blank"]
            if want_tor:
                from .tor import PORT as TOR_PORT
                args.insert(1, f"--proxy-server=socks5://127.0.0.1:{TOR_PORT}")  # names are looked up through Tor too
            self.proc = spawn(args, stdout=open(LOGS / "browser.log", "w", encoding="utf-8", errors="ignore"),
                              stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            self.tor = want_tor
            async with httpx.AsyncClient(timeout=2) as c:
                for _ in range(60):
                    try:
                        ver = (await c.get(f"http://127.0.0.1:{self.port}/json/version")).json()
                        break
                    except (httpx.HTTPError, ValueError):
                        await asyncio.sleep(0.5)
                else:
                    raise RuntimeError("The browser didn't start (see data/logs/browser.log)")
            b = CDP(await connect(ver["webSocketDebuggerUrl"], max_size=None, open_timeout=10))
            try:  # nothing gets downloaded behind your back
                await b.send("Browser.setDownloadBehavior", {"behavior": "deny"})
            finally:
                await b.close()
            tabs = await self._list()
            self.active = tabs[0]["id"] if tabs else None
            pages = [u for u in urls if not u.startswith("about:")]
            for i, u in enumerate(pages):  # Tor switched: the same pages again (the first in the empty start tab)
                if i == 0 and self.active:
                    await (await self._cdp()).send("Page.navigate", {"url": u})
                else:
                    await self.new_tab(u)

    async def _list(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"http://127.0.0.1:{self.port}/json/list")
        return [t for t in r.json() if t.get("type") == "page"]

    async def tabs(self) -> list[dict]:
        if not self.running():
            return []
        tabs = await self._list()
        if tabs and self.active not in {t["id"] for t in tabs}:
            self.active = tabs[0]["id"]
        return [{"id": t["id"], "title": t.get("title") or t.get("url"), "url": t.get("url"),
                 "active": t["id"] == self.active} for t in tabs]

    async def _cdp(self, tid: str | None = None) -> CDP:
        tid = tid or self.active
        c = self.conns.get(tid)
        if c and c.alive:
            return c
        tab = next((t for t in await self._list() if t["id"] == tid), None)
        if not tab:
            raise RuntimeError("That tab is closed")
        c = CDP(await connect(tab["webSocketDebuggerUrl"], max_size=None, open_timeout=10))
        self.conns[tid] = c
        await c.send("Page.enable")
        return c

    async def new_tab(self, url: str = "about:blank") -> str:
        async with httpx.AsyncClient(timeout=10) as c:  # an empty tab first, then the page (no address quoting games)
            t = (await c.put(f"http://127.0.0.1:{self.port}/json/new")).json()
        self.active = t["id"]
        if url and url != "about:blank":
            await (await self._cdp(t["id"])).send("Page.navigate", {"url": url})
        return t["id"]

    async def close_tab(self, tid: str, keep_one: bool = True) -> None:
        c = self.conns.pop(tid, None)
        if c:
            await c.close()
        async with httpx.AsyncClient(timeout=5) as h:
            await h.get(f"http://127.0.0.1:{self.port}/json/close/{tid}")
        if self.active == tid:
            rest = [t for t in await self._list() if t["id"] != tid]
            self.active = rest[0]["id"] if rest else None
        if not self.active and keep_one:
            await self.new_tab(HOME)

    async def test_html(self, html: str, wait: float = 1.8) -> dict:
        """The Coder checks its own work (Raven's designer rule): the app is opened in a hidden tab — offline, a data:
        address — and USED like a person would: drawn on, every button pressed, the controls changed, keys pressed (a
        painting app passed a load-only check and broke on the first stroke). -> {errors (with what was being done),
        blank, elements, used}"""
        import base64 as b64
        if not self.running():
            await self.ensure(tor=False)  # no Tor needed for a page that never goes online
        probe = ("<script>window.__errs=[];addEventListener('error',e=>__errs.push((e.message||'error')+(e.lineno?' (line '"
                 "+e.lineno+')':'')));addEventListener('unhandledrejection',e=>__errs.push('promise: '+((e.reason&&e.reason"
                 ".message)||e.reason)));</script>")
        page = html.replace("<head>", "<head>" + probe, 1) if "<head>" in html else probe + html
        before = self.active
        tid = await self.new_tab()
        try:
            c = await self._cdp(tid)
            await c.send("Page.navigate", {"url": "data:text/html;base64," + b64.b64encode(page.encode()).decode()})
            await asyncio.sleep(wait)
            r = await c.send("Runtime.evaluate", {"returnByValue": True, "expression":
                "JSON.stringify({errors: window.__errs || ['the app\\'s script never ran'], text: (document.body && "
                "document.body.innerText || '').trim().length, elements: document.body ? document.body.querySelectorAll('*')"
                ".length : 0, canvas: document.querySelectorAll('canvas').length})"})
            info = json.loads((r.get("result") or {}).get("value") or "{}")
            used, shot, layout = [], "", []
            if not info.get("errors") and info.get("elements", 0) >= 3:  # it loads: look at it, then use it
                try:  # what the user sees first: a picture for the model to look at, and the pile-up check
                    pile = json.loads((await c.send("Runtime.evaluate", {"returnByValue": True, "expression": LAYOUT_PROBE})
                                       ).get("result", {}).get("value") or "null")
                    if pile:
                        layout = [f"{pile['n']} things are drawn exactly on top of each other at x={pile['x']}, y={pile['y']} "
                                  f"(e.g. {', '.join('“' + t + '”' for t in pile['ex'])}) — only the top one can be seen: "
                                  "lay them out (in columns / rows / spread a little) so each one shows"]
                    pic = await c.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70, "clip": {
                        "x": 0, "y": 0, "width": SIZE[0], "height": SIZE[1], "scale": 0.8}}, timeout=20)
                    shot = pic.get("data") or ""
                except (RuntimeError, ValueError, KeyError, asyncio.TimeoutError):
                    pass
                try:
                    used = await self._use_app(c)
                    r = await c.send("Runtime.evaluate", {"returnByValue": True,
                                                          "expression": "JSON.stringify(window.__errs || [])"})
                    info["errors"] = json.loads((r.get("result") or {}).get("value") or "[]")
                except (RuntimeError, ValueError, asyncio.TimeoutError):
                    pass  # the use test couldn't run: the load check still counts
        finally:
            await self.close_tab(tid, keep_one=False)
            if before:
                self.active = before
        errors = list(dict.fromkeys(str(e)[:220] for e in info.get("errors", [])))  # a game loop repeats its error
        return {"errors": errors[:6] + layout, "used": used, "shot": shot,
                "blank": not info.get("text") and not info.get("canvas") and info.get("elements", 0) < 3,
                "elements": info.get("elements", 0)}

    async def _use_app(self, c: "CDP") -> list[str]:
        """~4 seconds of use with real mouse and key events; each error gets a note of what was being done."""
        async def ev(expr: str, wait_for: bool = False):
            r = await c.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": wait_for},
                             timeout=30)
            return (r.get("result") or {}).get("value")
        await ev(USE_SETUP)
        used = []
        rects = json.loads(await ev(
            "(()=>{const c=[...document.querySelectorAll('canvas')].filter(c=>c.getClientRects().length);"
            "if(c[0])c[0].scrollIntoView({block:'center'});return JSON.stringify(c.slice(0,2).map(c=>{"
            "const r=c.getBoundingClientRect();return [r.left,r.top,r.width,r.height]}).filter(r=>r[2]>20&&r[3]>20))})()") or "[]")
        for x, y, w, h in rects:  # a stroke across each canvas, like drawing (or aiming, dragging)
            await ev("__phase('drawing on the canvas')")
            pts = [(x + w * fx, y + h * fy) for fx, fy in ((.3, .3), (.4, .36), (.5, .44), (.6, .5), (.66, .6))]
            mouse = {"button": "left", "buttons": 1, "clickCount": 1}
            await c.send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": pts[0][0], "y": pts[0][1], **mouse})
            for px, py in pts[1:]:
                await c.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": px, "y": py, **mouse})
                await asyncio.sleep(0.02)
            await c.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": pts[-1][0], "y": pts[-1][1],
                                                      **mouse, "buttons": 0})
            used.append("drew on the canvas")
        counts = json.loads(await ev(USE_CONTROLS, True) or "[0, 0]")
        if counts[0]:
            used.append(f"pressed {counts[0]} button(s)")
        if counts[1]:
            used.append(f"changed {counts[1]} control(s)")
        await ev("document.activeElement && document.activeElement.blur && document.activeElement.blur();"
                 "__phase('pressing keys')")
        for key, code, vk, text, mods in USE_KEYS:
            for kind in ("keyDown", "keyUp"):
                await c.send("Input.dispatchKeyEvent", {"type": kind, "key": key, "code": code, "windowsVirtualKeyCode": vk,
                                                        "modifiers": mods, **({"text": text} if text and kind == "keyDown" else {})})
            await asyncio.sleep(0.04)
        used.append("pressed keys")
        await asyncio.sleep(0.8)  # a game loop runs a few frames with the new state
        await ev("__phase('')")
        return used

    async def go(self, text: str) -> str:
        url = as_url(text)
        if not self.active:
            await self.new_tab(url)
        else:
            await (await self._cdp()).send("Page.navigate", {"url": url})
        return url

    async def history(self, step: int) -> None:
        await (await self._cdp()).send("Runtime.evaluate", {"expression": f"history.go({int(step)})"})

    async def reload(self) -> None:
        await (await self._cdp()).send("Page.reload")

    async def shot(self, quality: int = 70) -> bytes:
        import base64
        r = await (await self._cdp()).send("Page.captureScreenshot", {"format": "jpeg", "quality": quality}, timeout=20)
        return base64.b64decode(r["data"])

    async def _xy(self, fx: float, fy: float) -> tuple[float, float]:
        m = await (await self._cdp()).send("Page.getLayoutMetrics")
        v = m.get("cssVisualViewport") or m.get("layoutViewport") or {}
        return max(0.0, min(1.0, fx)) * v.get("clientWidth", SIZE[0]), max(0.0, min(1.0, fy)) * v.get("clientHeight", SIZE[1])

    async def click(self, fx: float, fy: float, button: str = "left", count: int = 1) -> None:
        x, y = await self._xy(fx, fy)
        c = await self._cdp()
        await c.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for n in range(1, count + 1):
            for kind in ("mousePressed", "mouseReleased"):
                await c.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": button, "clickCount": n})

    async def scroll(self, fx: float, fy: float, dy: float) -> None:
        x, y = await self._xy(fx, fy)
        await (await self._cdp()).send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y,
                                                                    "deltaX": 0, "deltaY": dy})

    async def type_text(self, text: str) -> None:
        await (await self._cdp()).send("Input.insertText", {"text": text})

    async def key(self, combo: str) -> None:
        """"enter", "ctrl+a", "shift+tab", "backspace"…"""
        parts = [p.strip().lower() for p in combo.split("+") if p.strip()]
        mods = sum(MODS.get(p, 0) for p in parts[:-1])
        name = parts[-1] if parts else ""
        key, code, text = KEYS.get(name, (name, ord(name.upper()) if len(name) == 1 else 0, name if len(name) == 1 else ""))
        ev = {"key": key, "windowsVirtualKeyCode": code, "modifiers": mods}
        if len(name) == 1:
            ev["code"] = "Key" + name.upper() if name.isalpha() else ""
        c = await self._cdp()
        await c.send("Input.dispatchKeyEvent", {"type": "keyDown", **ev, **({"text": text} if text and not mods else {})})
        await c.send("Input.dispatchKeyEvent", {"type": "keyUp", **ev})

    async def text(self, limit: int = 12000) -> str:
        r = await (await self._cdp()).send("Runtime.evaluate", {"expression": "document.title + '\\n' + location.href + '\\n\\n' + "
                                                                             "(document.body ? document.body.innerText : '')",
                                                                "returnByValue": True})
        return str((r.get("result") or {}).get("value") or "")[:limit]

    async def _stop(self) -> None:
        for c in list(self.conns.values()):
            await c.close()
        self.conns.clear()
        if self.proc is not None and self.proc.poll() is None:
            kill_tree(self.proc.pid)
        self.proc, self.active = None, None

    async def stop(self) -> None:
        async with self.lock:
            await self._stop()

    async def clear(self) -> None:
        """Closes the browser and shreds its profile: cookies, history, logins, cache."""
        await self.stop()
        from . import wipe
        await asyncio.to_thread(wipe.shred_tree, PROFILE)


browser = Browser()
