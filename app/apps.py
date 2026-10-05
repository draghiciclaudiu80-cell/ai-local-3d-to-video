"""The app maker (Apps page): describe an app, game or small program — the local chat model writes it as ONE
self-contained HTML file (HTML + CSS + JavaScript), and it runs in a sealed preview: a sandboxed frame without the
app's origin (it can't read your chats, files or the app's API) and a content policy with no network at all.
Change it in plain words; each version is kept. Saved in data/apps/<id>/ (index.html, app.json, versions/)."""
import asyncio
import json
import re
import time
import uuid

from .config import DATA, load_settings
from . import codecheck, wipe

DIR = DATA / "apps"
CSP = ("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; script-src 'unsafe-inline'; "
       "style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; connect-src 'none'\">")
SYSTEM = """You build small apps, games and tools as ONE self-contained HTML file.
Rules:
- Everything inline in that one file: HTML, <style> CSS and <script> JavaScript. No external files, no CDN, no
  images from the internet (draw with canvas / CSS / emoji), no fetch or network calls: it runs offline in a sealed frame.
- It must WORK when opened: no placeholders, no "TODO", every button does something. Test your logic in your head.
- Fit any window size (responsive), dark friendly look, big clear controls; mouse, keyboard and touch where it makes sense.
- Games: a start screen or short instructions, score, restart, smooth animation with requestAnimationFrame.
- Save data with localStorage only if useful (it may be unavailable: wrap it in try/catch).
- Keep it compact (under ~400 lines). Plain modern JavaScript, no frameworks.
Answer with the complete file in ONE ```html block and one short sentence before it about what it does."""
MAKING: dict[str, asyncio.Task] = {}


def _meta_path(aid: str):
    return DIR / aid / "app.json"


def listing() -> list[dict]:
    out = []
    if DIR.exists():
        for d in DIR.iterdir():
            try:
                m = json.loads((d / "app.json").read_text(encoding="utf-8"))
                out.append({k: m.get(k) for k in ("id", "name", "updated", "versions")})
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda m: -(m.get("updated") or 0))


def get(aid: str) -> dict:
    d = DIR / re.sub(r"[^0-9a-f]", "", aid)
    m = json.loads((d / "app.json").read_text(encoding="utf-8"))
    return {**m, "html": (d / "index.html").read_text(encoding="utf-8")}


def sealed(html: str) -> str:
    """The app as the preview runs it: our no-network policy first in <head>."""
    if re.search(r"<head[^>]*>", html, re.I):
        return re.sub(r"(<head[^>]*>)", lambda m: m.group(1) + CSP, html, count=1, flags=re.I)
    return CSP + html


def _extract(text: str) -> tuple[str | None, str]:
    m = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.S | re.I)
    code = m.group(1) if m else None
    if code is None:  # no closing fence: cut off, or a bare file
        m2 = re.search(r"(<!doctype html.*|<html.*)", text, re.S | re.I)
        code = m2.group(1).split("```")[0] if m2 else None
    note = text[:m.start()].strip() if m else ""
    return (code.strip() if code else None), note[:300]


def fix_consts(code: str) -> str:
    """`const redoStack = []` and later `redoStack = []`: a TypeError the moment that line runs (a painting app broke
    on the first stroke). `let` is always safe there, so the app changes it itself instead of spending a model round."""
    for m in list(re.finditer(r"\bconst\s+([A-Za-z_$][\w$]*)\s*=(?!=)", code)):
        n = re.escape(m.group(1))
        if re.search(rf"(?<![\w$.]){n}\s*(?:[-+*/%&|^]|\*\*|<<|>>>?|&&|\|\||\?\?)?=(?![=>])|(?:\+\+|--){n}\b|(?<![\w$.]){n}(?:\+\+|--)",
                     code[m.end():]):
            code = re.sub(rf"\bconst(\s+{n}\s*=(?!=))", r"let\1", code, count=1)
    return code


def _note(note: str) -> str:
    """The model's one sentence before the file, as a description: "Here's a complete painting app …:" -> "A complete
    painting app …"."""
    note = re.sub(r"^(?:here(?:'s| is)|this is|i(?:'ve| have)? (?:made|built|created|written))\s+", "", note.strip(), flags=re.I)
    note = note.rstrip(" :")
    return (note[:1].upper() + note[1:] + ("" if note[-1:] in ".!?" else ".")) if note else ""


def _can_see(model: str) -> bool:
    """The chat model has its image part (an mmproj file next to it): it can look at a screenshot."""
    from pathlib import Path
    from .models import projector_for
    try:
        return bool(projector_for(Path(model)))
    except OSError:
        return False


async def _look(request: str, shot: str, model: str, ctx: int) -> list[str]:
    """The model LOOKS at the app it built (a screenshot from the hidden browser) and names what's visibly wrong — a
    solitaire with all 29 cards in one spot had passed every error check. [] = it looks right (or it couldn't tell)."""
    from .jobs import renderer
    from .llm import llm
    while llm.busy > 0:  # a chat answer first
        await asyncio.sleep(0.5)
    await llm.ensure(model, ctx, not renderer.busy())
    schema = {"type": "object", "required": ["looks_right", "problems"], "properties": {
        "looks_right": {"type": "boolean"},
        "problems": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 160}}}}
    llm.busy += 1
    try:
        r = await llm.complete([
            {"role": "system", "content": "You check an app by LOOKING at a screenshot of it, like a tester. Name only problems "
                                          "you can SEE: things piled in one spot, parts the request needs that are missing "
                                          "(piles, a board, buttons, a score…), overlapping or cut-off text, a broken or empty "
                                          "layout. If it looks right, say so — don't invent problems."},
            {"role": "user", "content": [
                {"type": "text", "text": f"The app was made for: {request[:400]}\nDoes this screenshot look like a working version "
                                         "of it?"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{shot}"}}]}],
            temperature=0.1, max_tokens=300, chat_template_kwargs={"enable_thinking": False},
            response_format={"type": "json_schema", "json_schema": {"name": "look", "schema": schema}})
        v = json.loads(r.get("content") or "{}")
    except Exception:  # noqa: BLE001 — the look is a bonus check: it never fails the build
        return []
    finally:
        llm.busy -= 1
    return [] if v.get("looks_right") else [str(p).strip()[:160] for p in v.get("problems") or [] if str(p).strip()][:4]


async def make(prompt: str, aid: str | None = None, name: str | None = None) -> dict:
    """A new app from the words, or (aid) a changed version of that app. Raven-style Coder harness: read the current
    file before changing it, start from a tested template when one fits, CHECK the result in the hidden browser — loaded
    AND used: drawn on, buttons pressed, keys pressed — and fix it (up to 2 rounds), and end with a receipt of what was
    built and how the check went. name: what the user called it (e.g. the folder they asked for)."""
    from .agent import chat_model
    from .browser import browser
    from .jobs import renderer
    from .llm import llm
    from .team import clean
    model = chat_model()
    if not model:
        raise RuntimeError("No chat model yet — download one in Models › Text")
    old = get(aid) if aid else None
    msgs = [{"role": "system", "content": SYSTEM}]
    if old and template_for(prompt) and REBUILD.search(prompt):  # "make it again from scratch / that really works":
        tpl = template_for(prompt)  # the tested template, not a patch of the broken file (a 4B model kept patching its
        msgs.append({"role": "user", "content": prompt + "\n\nStart from this WORKING template and build the request on it "
                     f"(keep what works, change and add the rest):\n```html\n{tpl}\n```"})  # one-column solitaire 3 times)
    elif old:
        tpl = template_for(prompt)  # "make it a real notepad": the tested notepad as a reference for the change
        msgs.append({"role": "user", "content": f"Here is the app now:\n```html\n{old['html']}\n```\n\nChange it: {prompt}\n"
                                                + (f"\nFor reference, a WORKING app of this kind (use its parts where they fit):\n"
                                                   f"```html\n{tpl}\n```\n" if tpl else "")
                                                + "Return the COMPLETE new file (not just the changes)."})
    else:
        tpl = template_for(prompt)
        msgs.append({"role": "user", "content": prompt + (f"\n\nStart from this WORKING template and build the request on it "
                                                          f"(keep what works, change and add the rest):\n```html\n{tpl}\n```"
                                                          if tpl else "")})
    need = len(json.dumps(msgs)) // 3 + 9000  # the file it writes needs room too
    ctx = max(int(load_settings()["ctx"]), min(32768, 1 << max(13, need.bit_length())))

    async def write(messages: list[dict]) -> tuple[str | None, str]:
        while llm.busy > 0:  # a chat answer first
            await asyncio.sleep(0.5)
        await llm.ensure(model, ctx, not renderer.busy())
        llm.busy += 1
        try:
            r = await llm.complete(messages, temperature=0.4, max_tokens=8000, chat_template_kwargs={"enable_thinking": False})
        finally:
            llm.busy -= 1
        return _extract(clean(r.get("content") or ""))
    code, note = await write(msgs)
    if not code or "<" not in code:
        raise RuntimeError("The model didn't write a file — try saying it more simply")
    if "</html>" not in code.lower() and "</script>" not in code.lower()[-400:] and "</body>" not in code.lower():
        raise RuntimeError("The app got too long for the model and was cut off — ask for a simpler version")
    code = fix_consts(code)
    problems, tries, used = [], 1, []
    for _ in range(2):  # READ it (ids, open tags), open it and USE it like a person would; fix what breaks
        static = codecheck.app_problems(code)
        try:
            report = await browser.test_html(sealed(code))
        except Exception as e:  # noqa: BLE001 — no browser: deliver without the use test, and say so
            problems = static + [f"(not checked in the browser: {str(e)[:80]})"]
            break
        problems = static + report["errors"] + (["the page shows nothing"] if report["blank"] else [])
        used = report.get("used") or used
        if not problems:
            break
        tries += 1
        fixed, _ = await write([msgs[0], {"role": "user", "content": "This app has problems — found by reading the file and by "
                               "opening and using it in the browser (what was being done is in brackets; → is the line):\n- "
                               + "\n- ".join(codecheck.with_lines(problems, code))
                               + f"\n\nThe file:\n```html\n{code}\n```\nFix exactly these. Return the COMPLETE file."}])
        if fixed and "<" in fixed:
            code = fix_consts(fixed)
    else:
        try:  # the last fix gets checked too
            report = await browser.test_html(sealed(code))
            problems = codecheck.app_problems(code) + report["errors"] + (["the page shows nothing"] if report["blank"] else [])
            used = report.get("used") or used
        except Exception:  # noqa: BLE001
            report = {}
    looked = ""
    shot = (report or {}).get("shot") if not problems else ""
    if shot and _can_see(model):  # no errors — now LOOK at it, like a person checking their own work
        seen = await _look(prompt if not old else f"{(old.get('prompts') or [''])[0]} — then changed: {prompt}", shot, model, ctx)
        looked = "looked at it: fine"
        if seen:
            fixed, _ = await write([msgs[0], {"role": "user", "content": "Looking at a screenshot of this app shows:\n- "
                                              + "\n- ".join(seen) + f"\n\nThe file:\n```html\n{code}\n```\nFix exactly these "
                                              "(keep everything that works). Return the COMPLETE file."}])
            looked = "looked at it: " + "; ".join(seen)[:160]
            if fixed and "<" in fixed:
                fixed = fix_consts(fixed)
                try:  # the visual fix must not break anything: tested again, kept only if it's clean
                    again = await browser.test_html(sealed(fixed))
                    if not (codecheck.app_problems(fixed) + again["errors"]) and not again["blank"]:
                        code, tries, looked = fixed, tries + 1, "looked at it and fixed: " + "; ".join(seen)[:140]
                except Exception:  # noqa: BLE001
                    pass
    aid = aid or uuid.uuid4().hex[:10]
    d = DIR / aid
    (d / "versions").mkdir(parents=True, exist_ok=True)
    meta = json.loads(_meta_path(aid).read_text(encoding="utf-8")) if old else \
        {"id": aid, "name": (name or "").strip()[:60] or _name(prompt), "created": time.time(), "prompts": [], "versions": 0}
    if old:  # keep the version before this change
        (d / "versions" / f"v{meta['versions']}.html").write_text(old["html"], encoding="utf-8")
    meta["versions"] = meta.get("versions", 0) + 1
    meta["prompts"] = (meta.get("prompts") or []) + [prompt[:500]]
    meta["updated"], meta["note"] = time.time(), _note(note)
    lines = code.count("\n") + 1
    how = "code read (ids, tags) + " + (f"used in the browser ({', '.join(used)})" if used else "checked in the browser")
    meta["receipt"] = (f"{lines} lines · {how}: no errors" + (f" (fixed in {tries - 1} round(s))" if tries > 1 else "")
                       + (f" · {looked}" if looked else "")
                       if not problems else f"{lines} lines · still has problems: " + "; ".join(problems[:3]))
    meta["checked_ok"] = not problems
    (d / "index.html").write_text(code, encoding="utf-8")
    _meta_path(aid).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return get(aid)


# ---------------------------------------------------------------- tested starting points (like PicoGK's proven designs)
TEMPLATES = {
    "paint": (r"\b(paint\w*|drawing|draw|sketch\w*|doodle|whiteboard|canvas|desen\w*|pictur[aă]|deseneaz\w*)\b", """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Paint</title>
<style>body{margin:0;font-family:system-ui;background:#1e1f22;color:#eee;display:flex;flex-direction:column;height:100vh}
.bar{display:flex;gap:8px;align-items:center;padding:8px;flex-wrap:wrap;background:#2b2d31}
button,input,select{font:inherit;padding:6px 10px;border-radius:8px;border:1px solid #555;background:#3a3c42;color:#eee}
canvas{flex:1;background:#fff;touch-action:none;cursor:crosshair}</style></head>
<body><div class="bar"><input type="color" id="color" value="#222222"><input type="range" id="size" min="1" max="60" value="6">
<button id="pen">Pen</button><button id="eraser">Eraser</button><button id="undo">Undo</button><button id="clear">Clear</button>
<button id="save">Save PNG</button></div><canvas id="c"></canvas>
<script>const c=document.getElementById('c'),g=c.getContext('2d');let drawing=false,erase=false,last=null,history=[];
function fit(){const img=c.width?g.getImageData(0,0,c.width,c.height):null;c.width=c.clientWidth;c.height=c.clientHeight;
g.fillStyle='#fff';g.fillRect(0,0,c.width,c.height);if(img)g.putImageData(img,0,0)}addEventListener('resize',fit);fit();
const pos=e=>{const r=c.getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}};
c.addEventListener('pointerdown',e=>{drawing=true;last=pos(e);history.push(g.getImageData(0,0,c.width,c.height));if(history.length>30)history.shift();c.setPointerCapture(e.pointerId)});
c.addEventListener('pointermove',e=>{if(!drawing)return;const p=pos(e);g.strokeStyle=erase?'#fff':document.getElementById('color').value;
g.lineWidth=+document.getElementById('size').value;g.lineCap='round';g.lineJoin='round';g.beginPath();g.moveTo(last.x,last.y);g.lineTo(p.x,p.y);g.stroke();last=p});
addEventListener('pointerup',()=>drawing=false);
document.getElementById('pen').onclick=()=>erase=false;document.getElementById('eraser').onclick=()=>erase=true;
document.getElementById('undo').onclick=()=>{const h=history.pop();if(h)g.putImageData(h,0,0)};
document.getElementById('clear').onclick=()=>{history.push(g.getImageData(0,0,c.width,c.height));g.fillStyle='#fff';g.fillRect(0,0,c.width,c.height)};
document.getElementById('save').onclick=()=>{const a=document.createElement('a');a.download='painting.png';a.href=c.toDataURL('image/png');a.click()};
</script></body></html>"""),
    "game": (r"\b(game|joc\w*|snake|pong|tetris|flappy|breakout|arkanoid|platformer|shooter|asteroids|racing|jump\w*)\b", """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Game</title>
<style>body{margin:0;background:#111;color:#eee;font-family:system-ui;display:grid;place-items:center;height:100vh}
canvas{background:#000;max-width:100vw;max-height:80vh;border-radius:8px}#hud{display:flex;gap:20px;margin:8px}
button{font:inherit;padding:8px 16px;border-radius:8px;border:0;background:#2e7d32;color:#fff}</style></head>
<body><div><div id="hud"><b>Score: <span id="score">0</span></b><span>Best: <span id="best">0</span></span><button id="start">Start</button></div>
<canvas id="c" width="480" height="480"></canvas><p>Arrow keys / WASD to move · P to pause · on a phone: swipe</p></div>
<script>const c=document.getElementById('c'),g=c.getContext('2d');let state='menu',score=0,best=0,last=0;
try{best=+localStorage.getItem('best')||0}catch(e){}document.getElementById('best').textContent=best;
const keys={};addEventListener('keydown',e=>{keys[e.key.toLowerCase()]=true;if(e.key.toLowerCase()==='p')state=state==='play'?'pause':state==='pause'?'play':state});
addEventListener('keyup',e=>keys[e.key.toLowerCase()]=false);
let player={x:240,y:240,s:16};function reset(){score=0;player={x:240,y:240,s:16};state='play'}
function update(dt){const v=200*dt;if(keys.arrowleft||keys.a)player.x-=v;if(keys.arrowright||keys.d)player.x+=v;
if(keys.arrowup||keys.w)player.y-=v;if(keys.arrowdown||keys.s)player.y+=v;player.x=Math.max(0,Math.min(c.width-player.s,player.x));
player.y=Math.max(0,Math.min(c.height-player.s,player.y));score+=dt*10}
function draw(){g.fillStyle='#000';g.fillRect(0,0,c.width,c.height);g.fillStyle='#4caf50';g.fillRect(player.x,player.y,player.s,player.s);
g.fillStyle='#fff';g.font='20px system-ui';if(state!=='play'){g.fillText(state==='pause'?'Paused':'Press Start',180,240)}
document.getElementById('score').textContent=Math.floor(score)}
function loop(t){const dt=Math.min(0.05,(t-last)/1000||0);last=t;if(state==='play')update(dt);draw();requestAnimationFrame(loop)}
document.getElementById('start').onclick=reset;requestAnimationFrame(loop);
function gameOver(){state='over';best=Math.max(best,Math.floor(score));document.getElementById('best').textContent=best;try{localStorage.setItem('best',best)}catch(e){}}
</script></body></html>"""),
    # Klondike solitaire (a 4B model's own tries: 29 face-up cards in one spot, then one long column — never real rules)
    "solitaire": (r"\b(solitai?re|klondike|patience|pasien[tț][aă])\b", r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Solitaire</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;background:#0f5132;font-family:system-ui;color:#fff;user-select:none}
.bar{display:flex;gap:10px;align-items:center;padding:8px 12px;background:#0b3d26}.bar b{flex:1}
button{font:inherit;padding:6px 12px;border-radius:8px;border:0;background:#198754;color:#fff;cursor:pointer}
#table{--w:min(12vw,96px);padding:14px;display:grid;gap:18px}.row{display:flex;gap:calc(var(--w)*.18)}.gap{flex:1}
.pile{position:relative;width:var(--w);height:calc(var(--w)*1.4);border-radius:8px;border:2px dashed rgba(255,255,255,.25)}
.card{position:absolute;left:0;width:var(--w);height:calc(var(--w)*1.4);border-radius:8px;background:#fff;color:#111;border:1px solid #999;
padding:4px 6px;font-weight:700;font-size:calc(var(--w)*.2);box-shadow:0 1px 3px rgba(0,0,0,.4);cursor:pointer}
.card.red{color:#c62828}.card .big{position:absolute;left:0;right:0;bottom:18%;text-align:center;font-size:calc(var(--w)*.42)}
.card.down{background:repeating-linear-gradient(45deg,#1565c0 0 8px,#1e88e5 8px 16px);border-color:#0d47a1}
.card.sel{outline:3px solid #ffd54f;outline-offset:1px}
#msg{position:fixed;inset:0;display:none;place-items:center;background:rgba(0,0,0,.6);font-size:2rem}#msg.on{display:grid}</style></head>
<body><div class="bar"><b>Solitaire</b><span id="info">Moves: 0</span><button id="undo">Undo</button><button id="new">New game</button></div>
<div id="table"><div class="row" id="top"></div><div class="row" id="cols"></div></div>
<div id="msg"><div>🎉 You won! <button id="again">Play again</button></div></div>
<script>const SUITS=['♠','♥','♦','♣'],RANKS=['A','2','3','4','5','6','7','8','9','10','J','Q','K'],red=s=>s==='♥'||s==='♦';
let S,moves=0,hist=[],sel=null;
function deal(){const d=[];for(const s of SUITS)for(let r=1;r<=13;r++)d.push({s,r,up:false});
 for(let i=d.length-1;i>0;i--){const j=Math.floor(Math.random()*(i+1));[d[i],d[j]]=[d[j],d[i]]}
 S={stock:d,waste:[],found:[[],[],[],[]],cols:[[],[],[],[],[],[],[]]};
 for(let c=0;c<7;c++)for(let k=0;k<=c;k++){const card=S.stock.pop();card.up=k===c;S.cols[c].push(card)}
 moves=0;hist=[];sel=null;document.getElementById('msg').classList.remove('on');draw()}
const snap=()=>{hist.push(JSON.stringify(S));if(hist.length>200)hist.shift()};
function cardEl(card,top){const e=document.createElement('div');e.className='card'+(card.up?(red(card.s)?' red':''):' down');
 if(card.up)e.innerHTML=RANKS[card.r-1]+card.s+'<div class="big">'+card.s+'</div>';e.style.top=top+'px';return e}
function pileEl(kind,i){const p=document.createElement('div');p.className='pile';p.onclick=e=>{if(e.target===p)clickPile(kind,i,-1)};return p}
function draw(){const top=document.getElementById('top'),cols=document.getElementById('cols');top.innerHTML='';cols.innerHTML='';
 const st=pileEl('stock',0);if(S.stock.length){const e=cardEl({up:false},0);e.onclick=()=>clickPile('stock',0,-1);st.append(e)}top.append(st);
 const wa=pileEl('waste',0);if(S.waste.length){const e=cardEl(S.waste[S.waste.length-1],0);if(sel&&sel.kind==='waste')e.classList.add('sel');
  e.onclick=()=>clickPile('waste',0,S.waste.length-1);e.ondblclick=()=>auto('waste',0);wa.append(e)}top.append(wa);
 const g=document.createElement('div');g.className='gap';top.append(g);
 S.found.forEach((f,i)=>{const p=pileEl('found',i);if(f.length){const e=cardEl(f[f.length-1],0);e.onclick=()=>clickPile('found',i,f.length-1);p.append(e)}top.append(p)});
 const w=st.offsetWidth||90;
 S.cols.forEach((col,i)=>{const p=pileEl('col',i);let y=0;col.forEach((c,k)=>{const e=cardEl(c,y);
  if(sel&&sel.kind==='col'&&sel.i===i&&k>=sel.k)e.classList.add('sel');e.onclick=ev=>{ev.stopPropagation();clickPile('col',i,k)};
  if(c.up)e.ondblclick=ev=>{ev.stopPropagation();if(k===col.length-1)auto('col',i)};p.append(e);y+=c.up?w*.3:w*.14});
  p.style.height=(y+w*1.4)+'px';cols.append(p)});
 document.getElementById('info').textContent='Moves: '+moves+' · Stock: '+S.stock.length}
const canStack=(card,onto)=>onto?(onto.up&&red(onto.s)!==red(card.s)&&onto.r===card.r+1):card.r===13;
const canFound=(card,f)=>f.length?(f[f.length-1].s===card.s&&f[f.length-1].r===card.r-1):card.r===1;
function take(){if(sel.kind==='waste')return[S.waste.pop()];if(sel.kind==='found')return[S.found[sel.i].pop()];return S.cols[sel.i].splice(sel.k)}
function selected(){return sel.kind==='waste'?S.waste[S.waste.length-1]:sel.kind==='found'?S.found[sel.i][S.found[sel.i].length-1]:S.cols[sel.i][sel.k]}
function pick(kind,i,k){if(kind==='col'){const c=S.cols[i][k];if(c&&c.up)sel={kind,i,k}}else if(kind==='waste'&&S.waste.length)sel={kind,i:0};
 else if(kind==='found'&&S.found[i].length)sel={kind,i}}
function clickPile(kind,i,k){
 if(kind==='stock'){snap();if(S.stock.length){const c=S.stock.pop();c.up=true;S.waste.push(c)}
  else{S.stock=S.waste.reverse().map(c=>({...c,up:false}));S.waste=[]}sel=null;moves++;draw();return}
 if(sel){const card=selected(),n=sel.kind==='col'?S.cols[sel.i].length-sel.k:1;
  if(kind==='found'&&n===1&&canFound(card,S.found[i])){snap();S.found[i].push(...take());done()}
  else if(kind==='col'&&!(sel.kind==='col'&&sel.i===i)&&canStack(card,S.cols[i][S.cols[i].length-1])){snap();S.cols[i].push(...take());done()}
  else{sel=null;pick(kind,i,k);draw()}return}
 pick(kind,i,k);draw()}
function done(){sel=null;moves++;S.cols.forEach(c=>{if(c.length&&!c[c.length-1].up)c[c.length-1].up=true});draw();
 if(S.found.every(f=>f.length===13))document.getElementById('msg').classList.add('on')}
function auto(kind,i){sel=kind==='col'?{kind,i,k:S.cols[i].length-1}:{kind,i:0};const card=selected();
 const f=S.found.findIndex(f=>canFound(card,f));if(f>=0){snap();S.found[f].push(...take());done()}else{sel=null;draw()}}
document.getElementById('new').onclick=deal;document.getElementById('again').onclick=deal;
document.getElementById('undo').onclick=()=>{if(!hist.length)return;S=JSON.parse(hist.pop());sel=null;draw()};
addEventListener('keydown',e=>{if(e.key==='n')deal();if(e.key==='z')document.getElementById('undo').click()});
addEventListener('resize',draw);deal();
</script></body></html>"""),
    # a text editor like Windows Notepad (a small model made "an app like notepad" into a code editor with a preview)
    "notepad": (r"\b(note ?pad\w*|text editor|editor de text|notes? app|noti[tț]e\w*|wordpad|txt editor)\b", r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Notepad</title>
<style>*{box-sizing:border-box}body{margin:0;height:100vh;display:flex;flex-direction:column;font-family:system-ui;background:#1e1f22;color:#e8e8e8}
.bar,.find,.status{display:flex;gap:6px;align-items:center;padding:6px 8px;background:#2b2d31;flex-wrap:wrap}
button,select,input{font:inherit;font-size:14px;padding:5px 10px;border-radius:6px;border:1px solid #4a4c52;background:#3a3c42;color:#eee}
#name{flex:1;min-width:120px;color:#aaa;font-size:13px;text-align:right}.find{display:none}.find.on{display:flex}
textarea{flex:1;width:100%;resize:none;border:0;outline:0;padding:12px 14px;background:#111214;color:#e8e8e8;font:15px/1.5 Consolas,monospace;tab-size:4}
textarea.nowrap{white-space:pre;overflow-x:auto}.status{gap:16px;font-size:12px;color:#9a9a9a;padding:4px 10px}</style></head>
<body><div class="bar"><button id="new" title="Ctrl+N">New</button><button id="open" title="Ctrl+O">Open…</button>
<button id="save" title="Ctrl+S">Save</button><button id="findBtn" title="Ctrl+F">Find</button>
<label><input type="checkbox" id="wrap" checked> Wrap</label><select id="size"><option>12</option><option>14</option>
<option selected>15</option><option>18</option><option>22</option></select><span id="name">untitled.txt</span>
<input type="file" id="file" accept=".txt,.md,.csv,.log,.json,text/*" hidden></div>
<div class="find" id="find"><input id="q" placeholder="Find"><input id="r" placeholder="Replace with"><button id="next">Next</button>
<button id="rep">Replace</button><button id="all">Replace all</button><button id="closeFind">✕</button></div>
<textarea id="t" spellcheck="false" placeholder="Start typing…"></textarea>
<div class="status"><span id="pos">Ln 1, Col 1</span><span id="count">0 words · 0 characters</span><span id="saved">Saved</span></div>
<script>const $=id=>document.getElementById(id),t=$('t');let name='untitled.txt',dirty=false;
const store={get(){try{return JSON.parse(localStorage.getItem('notepad')||'null')}catch(e){return null}},
 set(v){try{localStorage.setItem('notepad',JSON.stringify(v))}catch(e){}}};
function status(){const before=t.value.slice(0,t.selectionStart).split('\n');
 $('pos').textContent='Ln '+before.length+', Col '+(before[before.length-1].length+1);
 $('count').textContent=(t.value.match(/\S+/g)||[]).length+' words · '+t.value.length+' characters';
 $('saved').textContent=dirty?'● Not saved':'Saved';$('name').textContent=name;document.title=(dirty?'* ':'')+name+' — Notepad'}
function changed(){dirty=true;store.set({name,text:t.value});status()}
function newFile(){if(dirty&&!confirm('Discard the changes?'))return;t.value='';name='untitled.txt';dirty=false;store.set({name,text:''});status();t.focus()}
function saveFile(){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([t.value],{type:'text/plain'}));
 a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);dirty=false;status()}
$('new').onclick=newFile;$('save').onclick=saveFile;$('open').onclick=()=>$('file').click();
$('file').onchange=e=>{const f=e.target.files[0];if(!f)return;const rd=new FileReader();
 rd.onload=()=>{t.value=rd.result;name=f.name;dirty=false;store.set({name,text:t.value});status()};rd.readAsText(f);e.target.value=''};
$('wrap').onchange=()=>t.classList.toggle('nowrap',!$('wrap').checked);$('size').onchange=()=>t.style.fontSize=$('size').value+'px';
$('findBtn').onclick=()=>{$('find').classList.add('on');$('q').focus()};$('closeFind').onclick=()=>$('find').classList.remove('on');
function findNext(){const q=$('q').value;if(!q)return;let i=t.value.indexOf(q,t.selectionEnd);if(i<0)i=t.value.indexOf(q);
 if(i<0)return;t.focus();t.setSelectionRange(i,i+q.length);status()}
$('next').onclick=findNext;
$('rep').onclick=()=>{const q=$('q').value;if(q&&t.value.slice(t.selectionStart,t.selectionEnd)===q){t.setRangeText($('r').value,t.selectionStart,t.selectionEnd,'end');changed()}findNext()};
$('all').onclick=()=>{const q=$('q').value;if(!q)return;t.value=t.value.split(q).join($('r').value);changed()};
t.addEventListener('input',changed);['keyup','click','select'].forEach(ev=>t.addEventListener(ev,status));
t.addEventListener('keydown',e=>{if(e.key==='Tab'){e.preventDefault();t.setRangeText('\t',t.selectionStart,t.selectionEnd,'end');changed()}});
addEventListener('keydown',e=>{if(!(e.ctrlKey||e.metaKey))return;const k=e.key.toLowerCase();
 if(k==='s'){e.preventDefault();saveFile()}else if(k==='o'){e.preventDefault();$('file').click()}
 else if(k==='n'){e.preventDefault();newFile()}else if(k==='f'){e.preventDefault();$('findBtn').click()}});
const last=store.get();if(last){t.value=last.text||'';name=last.name||name}status();t.focus();
</script></body></html>"""),
}


REBUILD = re.compile(r"\b(from scratch|start over|start again|rebuild|redo|re-?make|really works?|that works|from zero|"
                     r"de la zero|din nou de la|again from)\b", re.I)
CARD_BOARD = re.compile(r"\b(solitai?re|klondike|cards?|poker|blackjack|chess|checkers|sudoku|memory game|minesweeper|"
                        r"tic.?tac.?toe|2048|board game|puzzle|crossword|carti|[sș]ah|pasien[tț][aă])\b", re.I)


def template_for(prompt: str) -> str | None:
    """A tested starting point for this kind of app (a small model builds on it far better than from nothing). Card and
    board games are clicked, not steered: the arcade game loop would be the wrong start for them."""
    for key, (pattern, code) in TEMPLATES.items():
        if key == "game" and CARD_BOARD.search(prompt):
            continue
        if re.search(pattern, prompt, re.I):
            return code
    return None


# ---------------------------------------------------------------- a real project folder (Desktop / Documents)
def desktop_dir() -> "Path":
    """The user's real Desktop (Windows may have moved it, e.g. into OneDrive)."""
    from pathlib import Path
    import os
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                p = Path(os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0]))
                if p.is_dir():
                    return p
        except OSError:
            pass
    return Path.home() / "Desktop"


def _split(html: str) -> tuple[str, str, str]:
    """One file -> index.html + style.css + app.js (a normal project you can open and change)."""
    css = "\n".join(m.group(1).strip() for m in re.finditer(r"<style[^>]*>(.*?)</style>", html, re.S | re.I))
    js = "\n\n".join(m.group(1).strip() for m in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I))
    page = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S | re.I)
    page = re.sub(r"<script(?![^>]*\bsrc=)[^>]*>.*?</script>", "", page, flags=re.S | re.I)
    if css:
        page = re.sub(r"</head>", '  <link rel="stylesheet" href="style.css">\n</head>', page, count=1, flags=re.I) \
            if re.search(r"</head>", page, re.I) else '<link rel="stylesheet" href="style.css">\n' + page
    if js:
        page = re.sub(r"</body>", '  <script src="app.js"></script>\n</body>', page, count=1, flags=re.I) \
            if re.search(r"</body>", page, re.I) else page + '\n<script src="app.js"></script>\n'
    return page, css, js


def export(aid: str, name: str = "", where: str = "desktop") -> str:
    """Saves the app as a real project in a NEW (or empty) folder: index.html, style.css, app.js, README.md.
    Never writes over anything that's there — except this app's OWN earlier export (same folder): that one gets the
    new version. -> the folder."""
    from pathlib import Path
    a = get(aid)
    base = desktop_dir() if where == "desktop" else Path.home() / "Documents"
    clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (name or a["name"])).strip(" .")[:60] or "My app"
    target, n = base / clean_name, 2
    while target.exists() and any(target.iterdir()) and str(target) not in (a.get("exports") or []):
        target, n = base / f"{clean_name} ({n})", n + 1  # someone else's folder: never written into — "Name (2)"
        if n > 50:
            raise RuntimeError(f"“{base / clean_name}” and its numbered copies all exist — pick another name.")
    target.mkdir(parents=True, exist_ok=True)
    page, css, js = _split(a["html"])
    (target / "index.html").write_text(page, encoding="utf-8")
    if css:
        (target / "style.css").write_text(css + "\n", encoding="utf-8")
    if js:
        (target / "app.js").write_text(js + "\n", encoding="utf-8")
    (target / "README.md").write_text(
        f"# {a['name']}\n\n{a.get('note') or ''}\n\nOpen **index.html** (double-click) to use it. Change it in Local AI › Apps, "
        f"or edit the files: index.html (layout), style.css (look), app.js (what it does).\n\nAsked for: {(a.get('prompts') or [''])[0]}\n"
        f"Made with Local AI on {time.strftime('%Y-%m-%d')}. {a.get('receipt') or ''}\n", encoding="utf-8")
    meta = json.loads(_meta_path(aid).read_text(encoding="utf-8"))
    meta["exports"] = list(dict.fromkeys([*(meta.get("exports") or []), str(target)]))
    _meta_path(aid).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return str(target)


# typed fast: "make an folder on my destop name notepad revfers" counts too
FOLDER_WORD = r"(?:folder|foler|fodler|floder|foldr|folfer|directory|dosar(?:ul)?)"
FOLDER = re.compile(rf"\b{FOLDER_WORD}\b(?:\s+(?:named|called|name|nmaed|namd|cu numele|numit))?\s*[\"“'«]?([^\"”'»\n,.;:!?]{{2,60}})?", re.I)
NAMED = re.compile(r"\b(?:named|called|name|nmaed|namd|cu numele|numit|numele)\s+[\"“'«]?([^\"”'»\n,.;:!?]{2,60})", re.I)
DESKTOP = re.compile(r"\b(de(?:sk|ks|s|k)\s?t?o?p|ecran)\b", re.I)
FOLDER_END = (r"\s+(?:and|then|to|for|with|that|si|și|pentru|cu|care)\s+|"
              r"\s+(?:on|in|pe|to)\s+(?:my|the)?\s*(?:de(?:sk|ks|s|k)\s?t?o?p|documents?|documente)\b")


def folder_wish(text: str) -> tuple[str, str] | None:
    """"make a folder on my desktop named test painting app" -> ("test painting app", "desktop"); none asked -> None."""
    m = FOLDER.search(text)
    if not m and not DESKTOP.search(text):
        return None
    name = ""
    named = NAMED.search(text[m.start():] if m else text)  # "folder on my desktop name X": the name after "name(d)"
    for got in ((named.group(1),) if named else ()) + ((m.group(1),) if m and m.group(1) else ()):
        got = re.sub(r"^(?:for|pentru)\s+(?:my|the|mele|meu)?\s*", "", got.strip(), flags=re.I)  # "a folder for my photos"
        name = re.split(FOLDER_END, got, maxsplit=1, flags=re.I)[0].strip()
        if name and not re.fullmatch(r"(on|in|pe|my|the|a|an|it|there)(\s.*)?", name, re.I):
            break
        name = ""
    return name, "desktop" if DESKTOP.search(text) or not re.search(r"\bdocuments?\b", text, re.I) else "documents"


def make_folder(name: str, where: str = "desktop") -> tuple[str, bool]:
    """"make a folder on my desktop named X" by itself: made directly (no mouse and keyboard). Never touches one
    that's there. -> (the folder, made now)."""
    from pathlib import Path
    base = desktop_dir() if where == "desktop" else Path.home() / "Documents"
    clean_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")[:60]
    target = base / (clean_name or "New folder")
    n = 2
    while not clean_name and target.exists():  # no name given: "New folder (2)", like Windows does
        target, n = base / f"New folder ({n})", n + 1
    if target.exists():
        return str(target), False
    target.mkdir(parents=True)
    return str(target), True


def _name(prompt: str) -> str:
    words = re.sub(r"\b(?:make|create)\s+(?:an?\s+)?(?:new\s+)?" + FOLDER_WORD + r"\b.*?\b(?:and|then)\s+", "", prompt.strip(),
                   count=1, flags=re.I)  # "make a folder named X and build me a painting app there" -> the app part
    words = re.sub(r"\b(?:on|in|pe)\s+(?:my|the)?\s*de(?:sk|ks|s|k)\s?t?o?p\b|\bthere\b|\buse (?:the )?teams?\s+(?:to\s+)?", " ",
                   words, flags=re.I)
    words = re.sub(r"^\s*(?:please\s+)?(make|mak|create|build|buld|write|design|give me|i want|f[aă]-?mi|f[aă]|creeaz[aă])\s+"
                   r"(me\s+)?(the\s+)?(an?\s+)?", "", words.strip(), flags=re.I)
    words = re.split(r"[:,;(\n]| - | with | that | which | where | cu | care ", words, maxsplit=1)[0].strip()  # "a tip calculator"
    words = re.sub(r"\b(?:ap|aap)\b", "app", re.sub(r"\s+", " ", words), flags=re.I)  # typed fast: "an ap like notepad"
    return (words[:1].upper() + words[1:48]).rstrip(" .,!") or "My app"


def undo(aid: str) -> dict:
    """Back to the version before the last change."""
    d = DIR / aid
    meta = json.loads(_meta_path(aid).read_text(encoding="utf-8"))
    prev = d / "versions" / f"v{meta['versions'] - 1}.html"
    if meta["versions"] < 2 or not prev.exists():
        raise RuntimeError("There's no earlier version")
    (d / "index.html").write_text(prev.read_text(encoding="utf-8"), encoding="utf-8")
    wipe.shred(prev)
    meta["versions"] -= 1
    meta["prompts"] = meta["prompts"][:-1]
    meta["updated"] = time.time()
    _meta_path(aid).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return get(aid)


def rename(aid: str, name: str) -> None:
    meta = json.loads(_meta_path(aid).read_text(encoding="utf-8"))
    meta["name"] = name.strip()[:80] or meta["name"]
    _meta_path(aid).write_text(json.dumps(meta, indent=1), encoding="utf-8")


def delete(aid: str) -> None:
    d = DIR / re.sub(r"[^0-9a-f]", "", aid)
    if d.exists() and DIR in d.parents:
        wipe.shred_tree(d)
