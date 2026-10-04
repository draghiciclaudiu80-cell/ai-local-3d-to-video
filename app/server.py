"""HTTP API + the page. Runs on 127.0.0.1 only."""
import asyncio
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager, closing
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from pydantic import BaseModel

from . import agent, attach, awake, computer, db, feedback, models, paper, plugins, printer_link, printer_profiles, projects, security, setup, skills, slicer, voice as voice_mod, wipe
from . import memory as mem
from .config import DATA, MEDIA, MODELS, SOUNDS, VERSION, load_settings, save_settings
from .hardware import free_disk_gb, hardware, rate
from .jobs import STYLES, make_movie, movie_list, movies, renderer, resume_movies, stitch, stop_all, stop_movie
from .laya import checkpoints as laya_checkpoints, laya
from .plat import open_path
from .llm import llm, small
from .tor import tor
from .voice import voice

STATIC = Path(__file__).resolve().parent / "static"


def _free_gpu() -> None:
    """Before each render: let a chat finish its reply, then unload a GPU chat model (a CPU one can stay)."""
    if not (llm.running() and llm.gpu):
        return
    for _ in range(600):
        if llm.busy <= 0:
            break
        time.sleep(0.5)
    llm.stop(only_gpu=True)
    time.sleep(2)  # the driver needs a moment to give the model's graphics memory back (a render failed without it)


async def warm_chat(delay: float = 0) -> None:
    """Loads the chat model in the background (app start, after the last render) so a message doesn't wait."""
    await asyncio.sleep(delay)
    for _ in range(1200):  # never swap the model in the middle of a reply (it cut a reply off once)
        if llm.busy <= 0:
            break
        await asyncio.sleep(0.5)
    m = agent.chat_model()
    if not m or llm.busy > 0 or renderer.busy() or computer.active() or (llm.running() and llm.gpu and llm.model == m):
        return
    try:
        await llm.ensure(m, int(load_settings()["ctx"]), True)
        small.stop()  # the main model is back on the graphics chip: the small model isn't needed, free its RAM
    except Exception:  # noqa: BLE001 — the next chat message loads it anyway (and shows the error)
        pass


def working_now() -> list[str]:
    """What the app is doing right now — while this isn't empty the PC doesn't idle-sleep (app/awake.py)."""
    if not load_settings().get("keep_awake", True):
        return []
    why = []
    if agent.LIVE:
        why.append(f"answering ({len(agent.LIVE)} chat{'s' if len(agent.LIVE) > 1 else ''})")
    if renderer.busy():
        why.append("making a picture/video")
    if any(mv.get("status") in ("queued", "rendering", "adding sound") for mv in movies.values()):
        why.append("making a movie")
    if plugins.active():
        why.append("building a 3D model")
    if any(d.get("status") == "running" for d in models.downloads.values()):
        why.append("downloading a model")
    if computer.active():
        why.append("using the computer for you")
    if printer_link.active():
        why.append("printing on the 3D printer")  # a USB print stops if the PC sleeps
    return why


@asynccontextmanager
async def lifespan(_app):
    db.init()
    mem.init_db()
    for f in MEDIA.glob("tts-*.wav"):  # leftovers of read-aloud answers (now deleted right after playing)
        wipe.shred(f)
    for mid in [m for m, mv in movies.items() if mv.get("status") == "done" and not (MEDIA / (mv.get("file") or "-")).exists()]:
        stop_movie(mid)  # a finished movie whose file was deleted: its titles / narration go too
    try:
        print("wipe:", wipe.sweep(set(renderer.jobs)))
    except Exception as e:  # noqa: BLE001 — never blocks the start
        print("wipe failed:", e)
    renderer.before_run = _free_gpu
    loop = asyncio.get_running_loop()
    renderer.after_all = lambda: asyncio.run_coroutine_threadsafe(warm_chat(5), loop)
    renderer.start()  # only now (hooks set): importing the app never renders
    computer.MAIN_LOOP = loop
    mem.background(mem.idle_loop())
    mem.background(warm_chat(3))
    resume_movies()
    models.resume_downloads()
    if tor.wanted():
        threading.Thread(target=tor.start, daemon=True).start()  # connected by the time you search
    mem.background(laya.idle_loop())  # the real Laya frees its RAM after 10 idle minutes
    if load_settings().get("laya", True) or load_settings().get("laya_assist"):
        mem.background(laya.ensure())  # ready for the first decision
    awake.start(working_now)  # the Legion Go slept after 3 idle minutes and froze a Blender job halfway
    yield
    awake.stop()
    tor.stop()
    llm.stop()
    laya.stop()
    small.stop()
    mem.emb.stop()
    for j in renderer.jobs.values():
        if j.get("proc"):
            j["proc"].kill()


app = FastAPI(title="Local AI", version=VERSION, lifespan=lifespan)


def need(cond, msg: str, code: int = 400):
    if not cond:
        raise HTTPException(code, msg)


# ---------------------------------------------------------------- status & settings
@app.get("/api/health")
def health():
    return {"version": VERSION, "platform": "windows" if os.name == "nt" else "linux",
            "llm": {"running": llm.running(), "model": Path(llm.model).stem if llm.model else None,
                                        "gpu": llm.gpu, "vision": llm.vision}, "rendering": renderer.busy(),
            "making3d": plugins.active(),  # 3D designs / builds (PicoGK) going on now
            "setup_pending": bool(load_settings().get("setup_pending")),  # moved / new PC: open the setup check once
            "awake": {"on": awake.state["on"], "why": awake.state["why"]},  # keeping the PC out of idle sleep
            "laya": {"assist": bool(load_settings().get("laya_assist")), "only": bool(load_settings().get("laya_only")),
                     "running": laya.running(), "ok": laya.available(), "small_ok": bool(small.model()), "real": True}}


@app.get("/api/settings")
def settings_get():
    return load_settings()


@app.put("/api/settings")
async def settings_put(body: dict):
    out = save_settings(body)
    if "laya_only" in body:  # swap the chat model now (main <-> Laya), not at the next message
        mem.background(warm_chat(0))
    if out.get("laya_assist") or out.get("laya", True):
        mem.background(laya.ensure())  # the real Laya: ready before your next message
    elif "laya" in body or "laya_assist" in body:
        laya.stop()
    if tor.wanted():
        threading.Thread(target=tor.start, daemon=True).start()
    else:
        tor.stop()
    return out


# ---------------------------------------------------------------- Create: reference pictures + 3D design
@app.post("/api/refs/describe")
async def refs_describe(body: dict):
    imgs = [u for u in body.get("images") or [] if isinstance(u, str) and u.startswith("data:image")]
    need(imgs, "Add at least one picture")
    try:
        return {"description": await agent.describe_subject(imgs)}
    except (ValueError, httpx.HTTPError) as e:
        need(False, str(e))


@app.post("/api/design")
async def design(body: dict):
    """Create › 3D: the chosen AI turns words (and the current design) into a PicoGK — or FreeCAD — recipe."""
    fc = body.get("engine") == "freecad"
    p = plugins.get("freecad" if fc else "picogk")
    need(p and p["ready"], "FreeCAD isn't set up" if fc else "PicoGK isn't set up")
    need(str(body.get("request") or "").strip(), "Describe the part first")
    if body.get("agent") in ("small", "laya") and not load_settings().get("laya_only"):
        need(small.model(), "The small model is missing (models/small)")
        complete = small.complete
    else:  # the chat model (in "Laya only" that IS Laya)
        m = agent.chat_model()
        need(m, "No chat model yet")
        if not llm.running() or llm.model != m:
            await llm.ensure(m, int(load_settings()["ctx"]), not renderer.busy())
        complete = llm.complete
    prev = {"recipe": body["recipe"]} if body.get("recipe") else None
    rid = str(body.get("run") or "")[:40] or uuid.uuid4().hex[:12]  # shown in the sidebar / dock, stoppable
    plugins.run_start(rid, "The AI is designing a 3D model…")
    request = str(body["request"])
    sk = skills.matched(request, "3d")  # the same expert instructions the chat's designer uses
    guide, plan = skills.as_text(sk) + (("\n\n" + agent.fit_note()) if agent.fit_note() else ""), ""

    async def stoppable(coro):
        task = asyncio.ensure_future(coro)
        while not task.done():
            await asyncio.wait({task}, timeout=0.5)
            if not task.done() and plugins.RUNS[rid]["stop"]:
                task.cancel()
                return None
        return task.result()
    llm.busy += 1
    try:
        if not prev and agent.DEVICE.search(request):  # a working device: an engineering plan first
            plugins.run_set(rid, text="The AI is writing the engineering plan…")
            plan = await stoppable(agent.design_plan(p, request, [], guide, "", complete)) or ""
            plugins.run_set(rid, text="The AI is turning the plan into parts…")
        recipe = None if plugins.RUNS[rid]["stop"] else await stoppable(
            agent.plugin_params(p, request, [], prev, complete, extra=guide, plan=plan))
        if plugins.RUNS[rid]["stop"]:
            return {"stopped": True}
    finally:
        llm.busy -= 1
        plugins.run_set(rid, done=True)
    need(recipe, "The AI couldn't turn that into a design — describe it more simply, or edit the parts yourself")
    if fc:  # its holes by face / in patterns -> one by one with a point + a direction (what the editor shows)
        recipe = {**recipe, "engine": "freecad"}
        if not recipe.get("template") or recipe.get("template") == "none":
            recipe = await run_in_threadpool(plugins.expand, "freecad", recipe) or recipe
    return {"recipe": recipe, "plan": plan, "skills": [x["name"] for x in sk]}


@app.post("/api/design/expand")
async def design_expand(body: dict):
    """"Edit in 3D" on a ready-made design saved short (template + options): its parts, without building it."""
    r0 = body.get("recipe")
    need(isinstance(r0, dict), "No design")
    eng = "freecad" if r0.get("engine") == "freecad" else "picogk"
    full = await run_in_threadpool(plugins.expand, eng, r0)
    need(full, "That design couldn't be opened for editing")
    return {"recipe": full}


@app.get("/api/printer")
async def printer_get(ports: int = 0):
    """The user's 3D printer: its plate, the slicing choices, how it's connected, the print going on (+ ports / cards)."""
    out = {**slicer.info(), "link": load_settings().get("printer_link") or {"kind": "usb"}, "job": printer_link.status()}
    if ports:
        out["ports"] = await run_in_threadpool(printer_link.ports)
        out["drives"] = await run_in_threadpool(printer_link.drives)
    return out


@app.post("/api/model3d/cut")
async def model3d_cut(body: dict):
    """✂ Cut to fit: the parts too big for the chosen printer's plate -> a new model cut into pieces that fit, with holes
    for alignment pins (the original model stays)."""
    m3 = body.get("model") or {}
    need(isinstance(m3, dict) and (str(m3.get("stl", "")).startswith("/media/") or m3.get("parts")), "Build the model first")
    r = await run_in_threadpool(plugins.cut_to_fit, m3, body.get("bed"), "printed" if body.get("pin") == "printed" else "filament")
    need(not r.get("error"), r.get("error") or "")
    if r.get("fits"):
        return {"fits": True, "model3d": m3}
    return r


@app.post("/api/model3d/editable")
async def model3d_editable(body: dict):
    """Edit in 3D on a Python-code design: its code replayed into the shapes Create › 3D edits (no Blender needed)."""
    code = str(body.get("code") or "")
    need(code.strip(), "This model has no design code to edit")
    r = await run_in_threadpool(plugins.code_to_recipe, code, str(body.get("name") or "design")[:80])
    need(not r.get("error"), r.get("error") or "")
    return r


@app.post("/api/model3d/mirror")
async def model3d_mirror(body: dict):
    """⇋ Mirror copy of a built model (a left hand from a right hand) — any model, also a sculpted mesh that can't be
    edited as parts. A new model in Gallery › 3D (the original stays); with "chat" it's also put in that chat."""
    m3 = body.get("model") or {}
    need(isinstance(m3, dict) and (str(m3.get("stl", "")).startswith("/media/") or m3.get("parts")), "Build the model first")
    axis = body.get("axis") if body.get("axis") in (0, 1, 2) else 0
    r = await run_in_threadpool(plugins.mirror_model, m3, axis)
    need(not r.get("error"), r.get("error") or "")
    cid = body.get("chat")
    if cid and db.q("SELECT id FROM chats WHERE id=?", (str(cid),)):
        text = (f"⇋ Mirrored copy ({plugins.SIDES[axis]}) of “{str(m3.get('name') or '3D model')[:80]}” — the original stays. "
                + ("Download it below, print it, or Edit in 3D." if r.get("editable") else "Download it below or print it."))
        db.run("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
               (str(cid), "assistant", text, json.dumps({"tools": [], "models3d": [r["model3d"]]}), time.time()))
        db.run("UPDATE chats SET updated=? WHERE id=?", (time.time(), str(cid)))
    return r


@app.get("/api/printers")
def printers_list():
    """Every printer the app knows (built-in, added from OrcaSlicer's library, custom) and which one is chosen."""
    return {"current": printer_profiles.current_id(), "printers": printer_profiles.listing()}


@app.post("/api/printers/select")
def printers_select(body: dict):
    try:
        p = printer_profiles.select(str(body.get("id") or ""))
    except ValueError as e:
        need(False, str(e))
    return {"ok": True, **slicer.info(), "id": p["id"]}


@app.post("/api/printers/custom")
def printers_custom(body: dict):
    """A printer you built or changed: your plate size on top of another printer's tested slicing settings."""
    try:
        d = printer_profiles.add_custom(str(body.get("name") or ""), body.get("bed") or [], body.get("base"),
                                        body.get("nozzle"), body.get("nozzle_max"), body.get("bed_max"))
        printer_profiles.select(d["id"])
    except ValueError as e:
        need(False, str(e))
    return {"ok": True, **slicer.info()}


@app.get("/api/printers/library")
async def printers_library(q: str = ""):
    """Search OrcaSlicer's own printer library (1000+ machines) — e.g. "k1 max", "prusa mk4", "bambu a1"."""
    return {"machines": await run_in_threadpool(printer_profiles.library, q, 40)}


@app.post("/api/printers/library")
async def printers_library_add(body: dict):
    try:
        d = await run_in_threadpool(printer_profiles.add_from_library, str(body.get("name") or ""))
        printer_profiles.select(d["id"])
    except ValueError as e:
        need(False, str(e))
    return {"ok": True, "added": d, **slicer.info()}


@app.delete("/api/printers/{pid}")
def printers_remove(pid: str):
    try:
        printer_profiles.remove(pid)
    except ValueError as e:
        need(False, str(e))
    return {"ok": True, "current": printer_profiles.current_id()}


@app.post("/api/printer/link")
def printer_link_set(body: dict):
    return printer_link.set_link(body)


@app.post("/api/slice")
async def slice_model(body: dict):
    """STL(s) of a model -> G-code + 3MF for the user's printer (OrcaSlicer on this PC, offline)."""
    files = []
    for u in (body.get("stls") or ([body["stl"]] if body.get("stl") else []))[:40]:
        f = MEDIA / Path(str(u)).name
        need(f.suffix.lower() == ".stl" and f.is_file() and not f.name.endswith(".view.stl"), "A model file isn't there any more")
        files.append(f)
    need(files, "No model to slice")
    rid = str(body.get("run") or "")[:40] or None
    if rid:
        plugins.run_start(rid, "OrcaSlicer is slicing it…", "build")
    r = await run_in_threadpool(slicer.make_gcode, files, body.get("options") or {}, rid, str(body.get("name") or "model")[:60])
    if r.get("stopped"):
        return {"stopped": True}
    need(not r.get("error"), str(r.get("error")))
    return r


@app.post("/api/printer/send")
async def printer_send(body: dict):
    """The user's own click: this G-code to the printer — over USB (streamed, or onto its SD card), onto an SD card in
    this PC, or to a print server on the LAN."""
    mode = body.get("mode")
    try:
        g = printer_link.media_file(body.get("gcode"), ".gcode")
        name = str(body.get("name") or g.name)[:80]
        if mode == "card":
            return await run_in_threadpool(printer_link.to_card, g, str(body.get("drive") or ""), name)
        if mode == "network":
            return await run_in_threadpool(printer_link.to_network, g, name)
        if mode in ("usb", "usb_sd"):
            port = str(body.get("port") or (load_settings().get("printer_link") or {}).get("port") or "")
            need(port, "Choose the printer's USB port first")
            printer_link.set_link({"kind": "usb", "port": port})
            return printer_link.start(g, mode, port, name)
    except (ValueError, OSError) as e:
        need(False, str(e))
    need(False, "Unknown way to send it")


@app.get("/api/printer/job")
def printer_job():
    return printer_link.status()


@app.post("/api/printer/job/{action}")
def printer_job_action(action: str):
    need(action in ("pause", "resume", "cancel"), "Unknown action")
    try:
        return printer_link.control(action)
    except ValueError as e:
        need(False, str(e))


@app.get("/api/paper/printers")
async def paper_printers():
    return {"printers": await run_in_threadpool(paper.printers)}


@app.post("/api/paper/print")
async def paper_print(body: dict):
    """A picture or a text on a normal (paper) printer — the user's own click."""
    from urllib.parse import unquote
    kind, printer, copies = body.get("kind"), str(body.get("printer") or ""), body.get("copies") or 1
    try:
        if kind == "image":
            f = MEDIA / Path(unquote(str(body.get("url") or "").split("?")[0])).name
            need(f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"), "That picture isn't there any more")
            return await run_in_threadpool(paper.print_file, "image", f, printer, copies)
        if kind == "text":
            text = str(body.get("text") or "")[:200_000]
            need(text.strip(), "Nothing to print")
            return await run_in_threadpool(paper.print_text, text, printer, copies)
    except (ValueError, OSError) as e:
        need(False, str(e))
    need(False, "Unknown kind")


@app.post("/api/printer/eject")
async def printer_eject(body: dict):
    return {"ejected": await run_in_threadpool(printer_link.eject, str(body.get("drive") or ""))}


@app.post("/api/design/build")
async def design_build(body: dict):
    r0 = body.get("recipe")
    need(isinstance(r0, dict) and (r0.get("parts") or r0.get("bodies") or r0.get("template")), "The design has no parts")
    eng = "freecad" if r0.get("engine") == "freecad" else "picogk"  # Create › 3D builds with the design's own engine
    p = plugins.get(eng)
    need(p and p["enabled"] and p["ready"], "FreeCAD isn't set up (freecad.org)" if eng == "freecad" else "PicoGK isn't set up")
    rid = str(body.get("run") or "")[:40] or None  # the page's progress bar polls /api/plugin-runs/<run>
    if rid:
        plugins.run_start(rid, "Starting the 3D engine…", "build")
    r = await run_in_threadpool(plugins.run, eng, r0, rid, True, False)  # quick: no Blender picture / GLB
    if r.get("stopped"):
        return {"stopped": True}
    need(not r.get("error"), str(r.get("error")))
    return r


# ---------------------------------------------------------------- this PC: setup check (moved / new PC)
@app.get("/api/setup")
async def setup_get():
    return await run_in_threadpool(setup.check)


@app.post("/api/setup/{action}")
async def setup_fix(action: str):
    try:
        r = await run_in_threadpool(setup.fix, action)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {**r, "check": await run_in_threadpool(setup.check)}


# ---------------------------------------------------------------- security kernel + sandbox
@app.get("/api/security")
def security_get():
    return {"policy": [{"tool": k, "level": v[0], "rule": v[1]} for k, v in security.TOOL_POLICY.items()],
            "never": security.NOT_POSSIBLE, "recent": security.recent(25), "sandbox": str(security.SANDBOX),
            "files": len(security.files())}


@app.post("/api/security/test")
async def security_test():
    return {"results": await run_in_threadpool(security.self_test)}


@app.get("/api/sandbox")
def sandbox_get():
    return {"files": security.files(), "folder": str(security.SANDBOX)}


@app.post("/api/sandbox/download")
async def sandbox_download(body: dict):
    """You typed the address yourself (Memory › Sandbox): you are the trusted source; file types are still checked."""
    r = await run_in_threadpool(security.download, str(body.get("url") or ""), "you")
    need(not r.get("error"), f"Not downloaded: {r.get('error')}")
    return {**sandbox_get(), "saved": r}


@app.delete("/api/sandbox/{name}")
def sandbox_delete(name: str):
    try:
        security.remove(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return sandbox_get()


@app.post("/api/sandbox/open")
def sandbox_open():
    security.SANDBOX.mkdir(parents=True, exist_ok=True)
    open_path(security.SANDBOX)  # the folder in Explorer / the file manager (Windows: files keep "from the internet")
    return {"ok": True}


@app.post("/api/sandbox/{name}/show3d")
def sandbox_show3d(name: str):
    try:
        p = security.in_sandbox(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    need(p.exists() and p.suffix.lower() == ".stl", "Only STL files can be shown in 3D")
    try:
        return {"model3d": plugins.import_stl(p, p.stem)}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- skills + the composer's Skills menu
COMMAND_LIST = [  # what the Skills menu offers under "Commands" (agent.parse_command understands them)
    {"cmd": "design", "label": "Design a 3D model", "hint": "plans it, builds it with PicoGK, checks the fit"},
    {"cmd": "plan", "label": "Plan first", "hint": "the AI writes a plan before it answers or builds"},
    {"cmd": "picture", "label": "Make a picture", "hint": ""},
    {"cmd": "video", "label": "Make a video clip", "hint": ""},
    {"cmd": "search", "label": "Search the web", "hint": "through Tor"},
    {"cmd": "rule", "label": "Save a rule", "hint": "a standing order it always follows (like 'never … unless I say')"},
    {"cmd": "talk", "label": "Just talk", "hint": "no tools, no pictures, no 3D"},
]


def _skill_list() -> list[dict]:
    return [{k: x[k] for k in ("id", "name", "description", "triggers", "for", "builtin", "enabled", "path")}
            for x in skills.all_skills()]


@app.get("/api/skills")
def skills_get():
    return {"skills": _skill_list(), "commands": COMMAND_LIST,
            "plugins": [{"id": p["id"], "name": p.get("name", p["id"]), "description": p.get("about") or p.get("description", "")}
                        for p in plugins.usable()],
            "rules": db.q("SELECT id, text FROM facts WHERE kind='rule' ORDER BY id")}


@app.post("/api/skills")
def skill_add(body: dict):
    try:
        skills.add_dir(str(body.get("path") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return skills_get()


@app.put("/api/skills/{sid}")
def skill_put(sid: str, body: dict):
    need(skills.get(sid), "No such skill", 404)
    skills.set_enabled(sid, bool(body.get("enabled")))
    return skills_get()


@app.delete("/api/skills/{sid}")
def skill_delete(sid: str):
    skills.remove(sid)
    return skills_get()


@app.get("/api/plugin-runs/{rid}")
def plugin_run_state(rid: str):
    """A 3D build in progress: {text, pct 0-1, elapsed, done, stopped} (the chat's and Create › 3D's progress bar)."""
    return plugins.run_state(rid)


@app.post("/api/plugin-runs/{rid}/stop")
def plugin_run_stop(rid: str):
    return {"stopped": plugins.run_stop(rid)}


# ---------------------------------------------------------------- plugins
def _plugin_list() -> list[dict]:
    return [{k: p.get(k) for k in ("id", "name", "description", "about", "builtin", "enabled", "ready", "path", "triggers")}
            for p in plugins.all_plugins()]


@app.get("/api/plugins")
def plugin_list():
    return _plugin_list()


@app.post("/api/plugins")
def plugin_add(body: dict):
    try:
        plugins.add(str(body.get("path") or ""))
    except ValueError as e:
        need(False, str(e))
    return _plugin_list()


@app.put("/api/plugins/{pid}")
def plugin_toggle(pid: str, body: dict):
    plugins.set_enabled(pid, bool(body.get("enabled")))
    return _plugin_list()


@app.delete("/api/plugins/{pid}")
def plugin_remove(pid: str):
    plugins.remove(pid)  # only forgets the folder; never deletes it
    return _plugin_list()


@app.get("/api/tor")
def tor_status():
    return tor.status()


@app.get("/api/hardware")
def hw():
    return {**hardware(), "free_gb": round(free_disk_gb())}


# ---------------------------------------------------------------- chats
@app.get("/api/chats")
def chats(q: str = ""):
    if q:
        return db.q("SELECT DISTINCT c.id, c.title, c.updated FROM chats c JOIN messages m ON m.chat_id=c.id "
                    "WHERE c.title LIKE ? OR m.content LIKE ? ORDER BY c.updated DESC LIMIT 100", (f"%{q}%", f"%{q}%"))
    return db.q("SELECT id, title, updated FROM chats ORDER BY updated DESC LIMIT 200")


@app.get("/api/chats/{cid}")
def chat_get(cid: str):
    c = db.q("SELECT * FROM chats WHERE id=?", (cid,))
    need(c, "Chat not found", 404)
    w = agent.LIVE.get(cid)  # its answer is still being made (the page left and came back)
    return {**c[0], "messages": db.q("SELECT id, role, content, extra FROM messages WHERE chat_id=? ORDER BY id", (cid,)),
            **({"working": {"status": w["status"], "progress3d": w["progress3d"], "since": round(time.time() - w["started"])}}
               if w else {})}


@app.get("/api/projects/{cid}")
def project_get(cid: str):
    """The chat's build project (the part-by-part plan) for its card, or null if there isn't one."""
    p = projects.get(cid)
    return {"project": projects.card(p) if p else None}


@app.delete("/api/projects/{cid}")
def project_delete(cid: str):
    """Close the project (the chat and its models stay)."""
    projects.delete(cid)
    return {"closed": cid}


@app.delete("/api/chats")
def chats_delete_all():
    """The "Delete all chats" button. What memory learned, documents and the gallery are kept."""
    ids = [c["id"] for c in db.q("SELECT id FROM chats")]
    for cid in ids:
        _chat_delete(cid)
    wipe.checkpoint()
    return {"deleted": len(ids)}


@app.delete("/api/chats/{cid}")
def chat_delete(cid: str):
    _chat_delete(cid)
    wipe.checkpoint()
    return {"deleted": cid}


def _chat_delete(cid: str) -> None:
    """For good (see wipe.py): its previews and self-check lines are shredded, its rows overwritten."""
    for r in db.q("SELECT extra FROM messages WHERE chat_id=? AND extra LIKE '%\"attachments\"%'", (cid,)):
        try:  # the files attached in this chat go with it
            attach.remove([a.get("id") for a in json.loads(r["extra"] or "{}").get("attachments") or []])
        except (ValueError, AttributeError):
            pass
    wipe.forget_chat(cid)
    db.run("DELETE FROM messages WHERE chat_id=?", (cid,))
    db.run("DELETE FROM summaries WHERE chat_id=?", (cid,))  # its memory summary goes with it
    db.run("DELETE FROM projects WHERE chat_id=?", (cid,))  # its build project (parts list, log) goes with it
    if db.q("SELECT 1 FROM ratings WHERE chat_id=? LIMIT 1", (cid,)):  # its 👍 / 👎 examples hold its words: they go too
        db.run("DELETE FROM ratings WHERE chat_id=?", (cid,))
        feedback.export()
    db.run("DELETE FROM chats WHERE id=?", (cid,))


@app.post("/api/chats/{cid}/model3d")
def chat_add_model(cid: str, body: dict):
    """Create › 3D → "Send to chat": the model changed by hand goes back into its chat (the AI can change it further)."""
    need(db.q("SELECT id FROM chats WHERE id=?", (cid,)), "That chat isn't there any more", 404)
    m3, recipe = body.get("model3d"), body.get("recipe")
    need(isinstance(m3, dict) and str(m3.get("stl", "")).startswith("/media/"), "Build the model first")
    keep = ("stl", "preview", "view", "name", "size_mm", "triangles", "grams", "parts", "collisions", "checked_pairs",
            "notes", "zip", "gaps", "step", "glb", "holes")
    m3 = {k: m3[k] for k in keep if k in m3}
    eng = "freecad" if isinstance(recipe, dict) and recipe.get("engine") == "freecad" else "picogk"
    m3.update(recipe=recipe if isinstance(recipe, dict) else {}, plugin=eng)
    size = " × ".join(str(round(x)) for x in m3.get("size_mm") or [] if isinstance(x, (int, float)))
    text = (f"You changed “{str(m3.get('name') or '3D model')[:80]}” by hand in Create › 3D" + (f" ({size} mm)" if size else "")
            + ". Download it below — or tell me what to change next.")
    db.run("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
           (cid, "assistant", text, json.dumps({"tools": [], "models3d": [m3]}), time.time()))
    db.run("UPDATE chats SET updated=? WHERE id=?", (time.time(), cid))
    return {"ok": True}


@app.post("/api/chats/{cid}/rate")
def chat_rate(cid: str, body: dict):
    """👍 / 👎 under an answer: {msg_id, rating: 1 | -1 | 0, reason}. Kept as a good / bad example (feedback.py) —
    it stays when the answer is regenerated (that's usually why it was disliked); it goes when the chat is deleted."""
    try:
        return feedback.rate(cid, int(body.get("msg_id") or 0), int(body.get("rating") or 0), str(body.get("reason") or ""))
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.delete("/api/feedback/{mid}")
def feedback_forget(mid: int):
    feedback.forget(mid)
    return memory()


@app.post("/api/chats/{cid}/truncate")
def chat_truncate(cid: str, body: dict):
    """Removes a message and everything after it (for Regenerate and Edit)."""
    db.run("DELETE FROM messages WHERE chat_id=? AND id>=?", (cid, int(body["from_id"])))
    if not db.q("SELECT id FROM messages WHERE chat_id=? LIMIT 1", (cid,)):
        db.run("DELETE FROM chats WHERE id=?", (cid,))  # nothing left: the chat itself goes too
        return {"ok": True, "deleted_chat": True}
    return {"ok": True}


class ChatIn(BaseModel):
    message: str
    chat_id: str | None = None
    images: list[str] = []   # data: URLs
    tools: bool = True
    voice: bool = False      # the user is talking by voice: short spoken answers
    route: str | None = None  # the user clicked a choice button (picture / 3D / search…): do that, and remember it
    attachments: list[str] = []  # ids from /api/attachments (files, a folder, videos)


@app.post("/api/attachments")
async def attachment_add(file: UploadFile = File(...), path: str = ""):
    """The chat's + menu: one file (a folder = one call per file, with its relative path). Read on this PC only."""
    rel = path or file.filename or "file"
    if attach.skip_path(rel):
        return {"skipped": rel}
    data = await file.read()
    if len(data) > 400 * 1024 * 1024:
        raise HTTPException(413, "That file is over 400 MB")
    return await run_in_threadpool(attach.save, file.filename or "file", data, rel)


@app.post("/api/chat")
async def chat(body: ChatIn):
    text = body.message.strip()
    need(text or body.images or body.attachments, "Empty message")
    atts = [a for a in (attach.load(x) for x in body.attachments[:300]) if a]
    cid = body.chat_id
    if not cid or not db.q("SELECT id FROM chats WHERE id=?", (cid,)):
        cid = uuid.uuid4().hex
        db.run("INSERT INTO chats VALUES (?,?,?,?)", (cid, (text or (atts[0]["name"] if atts else "Image"))[:60], time.time(), time.time()))
    if re.match(r"^\s*(remember|ține minte|tine minte)\b", text, re.I):
        db.run("INSERT INTO facts(text, created) VALUES (?,?)",
               (re.sub(r"^\s*(remember|ține minte|tine minte)\s*(that|că|ca)?\s*[:,]?\s*", "", text, flags=re.I), time.time()))
    msg_id = db.insert("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
                       (cid, "user", text, json.dumps({"images": len(body.images),
                                                      **({"attachments": [attach.public(a) for a in atts]} if atts else {})}),
                        time.time()))
    db.run("UPDATE chats SET updated=? WHERE id=?", (time.time(), cid))
    agent.stop_flags.discard(cid)
    # The answer is made in the BACKGROUND and always saved; this response only relays it. Switching chats, opening
    # another page or reloading used to cut the connection -> the server dropped a 3D job halfway (the user saw an
    # empty chat). Now the page can leave and come back: GET /api/chats/{id} says "working" until it's done.
    q: asyncio.Queue = asyncio.Queue()
    live = agent.LIVE[cid] = {"started": time.time(), "status": "Working…", "progress3d": None, "msg_id": msg_id}

    got: dict = {"text": [], "models3d": []}  # what was streamed so far — kept if the answer crashes before it's saved

    async def pump():
        try:
            async for ev in agent.chat_stream(cid, text, body.images, body.tools, msg_id, body.voice, body.route,
                                              [a["id"] for a in atts]):
                q.put_nowait(ev)
                try:
                    e = json.loads(ev[6:])
                    live["status"] = e.get("status") or live["status"]
                    live["progress3d"] = e.get("progress3d") or live["progress3d"]
                    got["text"] += [e["delta"]] if e.get("delta") else []
                    got["models3d"] += [e["model3d"]] if e.get("model3d") else []
                    got.update({k: e[k] for k in ("code", "plan", "skills") if e.get(k)})
                except ValueError:
                    pass
        except Exception as e:  # noqa: BLE001 — shown in the chat, logged, and never a chat with only the question
            import traceback
            print("chat failed:", repr(e), "\n" + traceback.format_exc()[-1500:])
            q.put_nowait(agent.sse({"error": f"Something went wrong: {e}"}))
            # KeyError('volume_mm3') once crashed after the 3D model was built: the chat kept only the question
            if db.q("SELECT 1 FROM messages WHERE id=?", (msg_id,)) and not db.q(
                    "SELECT 1 FROM messages WHERE chat_id=? AND id>? AND role='assistant'", (cid, msg_id)):
                db.run("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
                       (cid, "assistant", ("".join(got.pop("text")) + f"\n\n(Something went wrong while finishing this "
                                           f"answer: {e}. Press Resend to try again.)").strip(),
                        json.dumps({"tools": [], "stopped": False, "error": repr(e), **{k: v for k, v in got.items() if v}}),
                        time.time()))
        finally:
            if agent.LIVE.get(cid) is live:
                agent.LIVE.pop(cid, None)
            q.put_nowait(None)

    mem.background(pump())

    async def relay():
        while (ev := await q.get()) is not None:
            yield ev
    return StreamingResponse(relay(), media_type="text/event-stream")


@app.post("/api/chat/stop")
def chat_stop(body: dict):
    """The Stop button: the reply stops within a moment; what was written so far is kept."""
    cid = body.get("chat_id") or ""
    agent.stop_flags.add(cid)
    for a in agent.approvals.values():  # a question waiting for the user is answered "no"
        if a.get("chat") == cid:
            a["ok"] = False
            a["event"].set()
    return {"ok": True}


@app.post("/api/approve/{aid}")
def approve(aid: str, body: dict):
    a = agent.approvals.get(aid)
    need(a, "This request already expired", 404)
    a["ok"] = bool(body.get("ok"))
    a["event"].set()
    if body.get("always"):
        save_settings({"allow_web": True})
    return {"ok": a["ok"]}


@app.post("/api/llm/unload")
def llm_unload():
    llm.stop()
    return {"ok": True}


# ---------------------------------------------------------------- models
@app.get("/api/brains")
def brains():
    """The two helper models next to the chat model: the SMALL model (a small chat model on the processor: the 3D
    designer option, "Small model only" chat) and LAYA (the decision model, System 1). Which file / checkpoint, running?"""
    s = load_settings()
    sm = small.model()
    texts = [m for m in models.installed("text") if not models.is_helper(m["path"])]
    choices = []
    for m in sorted(texts, key=lambda m: m["size"]):
        c = models.capabilities(m["path"], m.get("mmproj"))
        if c.get("embedding"):
            continue
        choices.append({"path": m["path"], "name": m["name"], "size": m["size"], "caps": c})
    return {"small": {"running": small.running(), "path": str(sm) if sm else None, "name": sm.stem if sm else None,
                      "size": sm.stat().st_size if sm else 0, "only": bool(s.get("laya_only")), "choices": choices},
            "laya": {"running": laya.running(), "available": laya.available(), "model": laya.chosen(),
                     "fixed": bool(s.get("laya_model")), "on": bool(s.get("laya", True)), "assist": bool(s.get("laya_assist")),
                     "checkpoints": laya_checkpoints(), "act_at": agent.LAYA_ACT}}


@app.post("/api/brains/small")
async def brains_small(body: dict):
    """Start / stop the small model, or use another model file as the small model."""
    act = body.get("action")
    if act == "use":
        path = str(body.get("path") or "")
        need(Path(path).is_file() and path.endswith(".gguf"), "Pick a .gguf model file")
        was = small.running()
        small.stop()
        save_settings({"small_model": path})
        if load_settings().get("laya_only"):
            llm.stop()  # "Small model only" is loaded in the main slot: the next message loads the new one
        if was:
            await small.ensure()
    elif act == "stop":
        small.stop()
    elif act == "start":
        need(small.model(), "No small model file — pick one in the list")
        need(await small.ensure(), "The small model didn't start (see data/logs/small.log)")
    return brains()


@app.post("/api/brains/laya")
async def brains_laya(body: dict):
    """Start / stop Laya, or answer with another Laya checkpoint (a folder in models/laya-real)."""
    act = body.get("action")
    if act == "use":
        name = str(body.get("model") or "")
        need(any(c["name"] == name for c in laya_checkpoints()), "That Laya model isn't in models/laya-real")
        was = laya.running()
        laya.stop()
        save_settings({"laya_model": name})
        if was:
            await laya.ensure()
    elif act == "auto":  # back to the default: typed-decisions (by language when asked)
        laya.stop()
        save_settings({"laya_model": None})
    elif act == "stop":
        laya.stop()
    elif act == "start":
        need(laya.available(), "Laya isn't installed")
        need(await laya.ensure(), "Laya didn't start (see data/logs/laya.log)")
    return brains()


LAYA_TEST = [("make a picture of a cat on a roof", "draw"), ("draw me a dragon", "draw"),
             ("design a phone stand I can 3d print", "design"), ("a gear for my motor that I can 3d print", "design"),
             ("make a video of a dog running on the beach", "film"), ("merge them together", "merge"),
             ("what's the weather in Bucharest tomorrow?", "search"), ("show me photos of pitbulls", "photos"),
             ("find funny cat videos on youtube", "youtube"), ("open Notepad", "computer"),
             ("tell me a joke", "chat"), ("thanks, that's great", "chat")]


@app.post("/api/brains/laya/test")
async def brains_laya_test():
    """Is Laya doing its job? 12 everyday messages with a known right answer: what it picked, how sure, how fast — and
    how often it would act on its own (sure ≥ the app's act line) and be right then."""
    need(laya.available(), "Laya isn't installed")
    rows, right, acted, acted_ok, ms = [], 0, 0, 0, []
    for text, want in LAYA_TEST:
        try:
            r = await laya.ask(f"New message: {text}", "route", "What does the user want the app to do with the new message?",
                               agent.ROUTE_CRITERIA)
        except Exception as e:  # noqa: BLE001
            need(False, f"Laya failed: {e}"[:200])
        ok = r["choice"] == want
        right += ok
        if r["sure"] >= agent.LAYA_ACT:
            acted += 1
            acted_ok += ok
        ms.append(r.get("ms") or 0)
        rows.append({"text": text, "want": want, "got": r["choice"], "sure": round(r["sure"], 2), "ok": ok, "ms": r.get("ms")})
    return {"model": laya.chosen(), "right": right, "total": len(LAYA_TEST), "acted": acted, "acted_right": acted_ok,
            "avg_ms": round(sum(ms) / max(len(ms), 1)), "act_at": agent.LAYA_ACT, "rows": rows,
            "verdict": ("Working well" if acted_ok == acted and right >= 8 else
                        "Working: when unsure it asks the chat model — that's by design" if acted_ok >= acted - 1 else
                        "Not reliable with this checkpoint — switch back to typed-decisions")}


@app.get("/api/models/{modality}")
def models_for(modality: str):
    need(modality in models.MODALITIES, "Unknown model type", 404)
    s = load_settings()
    if modality == "voice":
        active = s["active"].get("voice")
        have = models.installed_voices()
        cat = models.piper_catalog()
        ids = have + [v for v in models.VOICES if v not in have]
        return {"items": [{"id": v, "name": models.voice_label(v, cat), "installed": v in have, "active": v == active,
                           "size_gb": 0.35 if v in models.KOKORO else 0.06, "download": models.dl_state("voice", v)}
                          for v in ids]}
    if modality == "transcription":
        return {"items": models.whisper_models(), "language": s.get("stt_language") or "auto",
                "languages": models.STT_LANGUAGES}
    active = models.active_path(modality)
    inst = []
    for m in models.installed(modality):
        fit, why = rate(m["size"] / 1e9, modality in ("image", "video"))
        problem = None
        if modality == "image":
            problem = models.image_parts(m["path"])[1]
        elif modality == "video":
            problem = models.video_parts(m["path"])[1]
        inst.append({**m, "fit": fit, "why": problem or why, "usable": not problem, "active": m["path"] == active,
                     "fast": any(k in m["file"].lower() for k in ("distill", "lightning", "turbo")),
                     **({"caps": models.capabilities(m["path"], m.get("mmproj"))} if modality in ("text", "vision") else {})})
    store = []
    for cid, mod, name, note, gb, gpu, tags, files in models.CATALOG:
        if mod != modality or models.catalog_installed(files):
            continue
        fit, why = rate(gb, gpu)
        dl = next((d for d in models.downloads.values() if models.same_files(d["files"], files)
                   and d["status"] in ("running", "error")), None)
        store.append({"id": cid, "name": name, "note": note, "size_gb": gb, "tags": tags, "fit": fit, "why": why,
                      "download": dl})
    return {"installed": inst, "store": store}


class ActiveIn(BaseModel):
    modality: str
    value: str


@app.post("/api/models/active")
def models_active(body: ActiveIn):
    need(body.modality in models.MODALITIES, "Unknown model type")
    models.set_active(body.modality, body.value)
    if body.modality == "text" and llm.model and llm.model != body.value:
        llm.stop()  # the next chat loads the new model
    return {"ok": True}


class DownloadIn(BaseModel):
    catalog_id: str | None = None
    repo: str | None = None
    files: list[str] = []
    modality: str = "text"


@app.post("/api/models/download")
def models_download(body: DownloadIn):
    try:
        if body.catalog_id:
            c = next((c for c in models.CATALOG if c[0] == body.catalog_id), None)
            need(c, "Unknown model", 404)
            return models.start_download(c[2], c[1], c[7], c[4])
        need(body.repo and body.files, "Pick a file to download")
        meta = {f["path"]: f["size"] for f in (models.repo_files(body.repo) if body.modality == "transcription"
                                                   else models._tree(body.repo))}
        files = [(body.repo, p, None) for p in body.files]
        return models.start_download(body.repo.split("/")[-1], body.modality, files,
                                     sum(meta.get(p, 0) for p in body.files) / 1e9)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/downloads")
def downloads():
    return [{k: v for k, v in d.items() if k != "files"} for d in models.downloads.values()]


@app.delete("/api/downloads/{did}")
def download_cancel(did: str):
    models.cancel_download(did)
    return {"ok": True}


@app.delete("/api/models/file")
def model_delete(path: str):
    p = Path(path).resolve()
    need(MODELS.resolve() in p.parents and p.is_file(), "Only models this app downloaded can be deleted here", 403)
    for d in list(models.downloads.values()):  # deleting a half-finished file also forgets its download
        if d["status"] != "running" and any(Path(models._local(*f)).name == p.name.removesuffix(".part") for f in d["files"]):
            models.cancel_download(d["id"])
    if llm.model and Path(llm.model).resolve() == p:
        llm.stop()
    proj = models.projector_for(p)
    p.unlink()
    if proj and not any(x for x in p.parent.glob("*.gguf") if not models.is_projector(x.name)):
        proj.unlink()  # the vision add-on is useless without its model
    if p.parent != MODELS and not any(p.parent.iterdir()):
        p.parent.rmdir()
    return {"deleted": str(p)}


@app.get("/api/hf/search")
def hf_search(q: str, modality: str = "text"):
    try:
        if modality == "voice":
            return models.voice_search(q)
        if modality == "transcription":
            return models.whisper_search(q)
        return models.hf_search(q, modality)
    except Exception as e:  # noqa: BLE001 — offline, rate limited...
        raise HTTPException(502, f"Hugging Face search failed: {e}")


@app.get("/api/hf/files")
def hf_files(repo: str):
    try:
        return models.hf_files(repo)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't list files: {e}")


@app.post("/api/voices/{vid}")
def voice_install(vid: str):
    """Get & use: already here -> use it now; otherwise a background download that switches when done."""
    need(vid in models.VOICES or vid in models.piper_catalog(), "Unknown voice", 404)
    if voice_mod.voice_installed(vid):
        models.set_active("voice", vid)
        return {"installed": True}
    try:
        return models.voice_download(vid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/whisper/{size}")
def whisper_install(size: str):
    need(size in models.WHISPER, "Unknown size", 404)
    if voice_mod.whisper_installed(size):
        models.set_active("transcription", size)
        return {"installed": True}
    try:
        return models.whisper_download(size)
    except (ValueError, httpx.HTTPError) as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- create: image, video, movie
class ImageIn(BaseModel):
    prompt: str
    style: str = "None"
    width: int = 0
    height: int = 0
    seed: int = -1
    init: str | None = None     # data: URL — "start from the front picture"
    strength: float = 0.6


class VideoIn(BaseModel):
    prompt: str
    seconds: float = 2
    width: int = 480
    height: int = 272
    seed: int = -1


class MovieIn(BaseModel):
    title: str = "Movie"
    look: str = ""
    scenes: list[dict]
    seconds: float = 2
    voice: str | None = None
    music: str | None = None
    music_volume: float = 0.25
    width: int = 480
    height: int = 272


@app.post("/api/image")
def image(body: ImageIn):
    try:
        init = None
        if body.init:  # saved only while it renders, then wiped (jobs: "temp")
            import base64
            (DATA / "refs").mkdir(exist_ok=True)
            init = str(DATA / "refs" / f"init-{uuid.uuid4().hex[:12]}.png")
            Path(init).write_bytes(base64.b64decode(body.init.split(",", 1)[-1]))
        return {"job": renderer.submit("image", renderer.image_args(body.prompt, body.style, body.width, body.height,
                                                                     body.seed, init, body.strength), body.prompt,
                                       temp=[init] if init else None)}
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))


@app.post("/api/video")
def video(body: VideoIn):
    try:
        return {"job": renderer.submit("video", renderer.video_args(body.prompt, body.seconds, body.width, body.height,
                                                                     body.seed), body.prompt)}
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))


@app.post("/api/movie")
def movie(body: MovieIn):
    try:
        return make_movie(body.title, body.look, body.scenes, body.seconds, body.voice, body.music,
                          body.music_volume, body.width, body.height)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/movies/{mid}")
def movie_stop(mid: str):
    """Stops a movie being made; a finished / stopped / failed one is removed from the list (its clips stay)."""
    need(mid in movies, "Movie not found", 404)
    stop_movie(mid)  # stops it if it's being made, and takes it off the list either way
    return {"stopped": mid}


@app.post("/api/stop-all")
def stop_everything():
    return {"stopped": stop_all(), "stopped_3d": plugins.stop_all()}


@app.get("/api/styles")
def styles():
    return list(STYLES)


@app.get("/api/jobs")
def jobs():
    js = sorted(renderer.jobs.values(), key=lambda j: -j["created"])[:30]
    return {"jobs": [renderer.public(j) for j in js], "waiting": len(renderer.queue), "movies": movie_list()[:10],
            "making3d": plugins.active()}


@app.delete("/api/jobs/{jid}")
def job_delete(jid: str):
    """Cancels a running/queued job; removes a finished one (and its file)."""
    job = renderer.jobs.get(jid)
    if job and job["status"] in ("queued", "running"):
        if job.get("movie") in movies and movies[job["movie"]]["status"] in ("rendering", "adding sound"):
            stop_movie(job["movie"])  # a movie's scene: stop the whole movie, not just this scene
            return {"stopped_movie": job["movie"]}
        renderer.cancel(jid)
        return {"cancelled": jid}
    renderer.forget(jid)
    gallery_delete(jid)
    if job:
        wipe.shred(MEDIA / job["file"])
    return {"deleted": jid}


# ---------------------------------------------------------------- gallery
@app.get("/api/gallery")
def gallery():
    return [g for g in db.q("SELECT * FROM gallery ORDER BY created DESC") if (MEDIA / g["file"]).exists()]


@app.delete("/api/gallery/{gid}")
def gallery_delete(gid: str):
    row = db.q("SELECT file FROM gallery WHERE id=?", (gid,))
    db.run("DELETE FROM gallery WHERE id=?", (gid,))
    if row:
        wipe.shred(MEDIA / row[0]["file"])
        if row[0]["file"].startswith("model-") and row[0]["file"].endswith(".stl"):
            stem = Path(row[0]["file"]).stem  # a 3D model: its preview, recipe, parts, light copies and zip go too
            for f in [*MEDIA.glob(stem + ".*"), *MEDIA.glob(stem + "-*")]:
                wipe.shred(f)
    if gid in renderer.jobs and renderer.jobs[gid]["status"] not in ("queued", "running"):
        renderer.forget(gid)
    if gid not in renderer.jobs:
        wipe.forget_job(gid)  # its log holds the prompt
    if gid in movies and movies[gid]["status"] not in ("rendering", "adding sound"):
        stop_movie(gid)  # a finished movie: its scene list / narration go too (its clips stay in Clips)
    wipe.checkpoint()
    return {"deleted": gid}


@app.post("/api/stitch")
async def stitch_clips(body: dict):
    paths = [MEDIA / Path(f).name for f in body.get("files", [])]
    need(len(paths) >= 2 and all(p.exists() for p in paths), "Pick at least 2 videos")
    gid = uuid.uuid4().hex[:12]
    out = MEDIA / f"movie-{time.strftime('%Y%m%d-%H%M%S')}-{gid}.mp4"
    await run_in_threadpool(stitch, paths, out)
    db.add_gallery(gid, "movie", out.name, body.get("title") or f"Joined {len(paths)} videos")
    return {"file": out.name}


@app.get("/api/sounds")
def sounds():
    return sorted(p.name for p in SOUNDS.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac"))


@app.post("/api/sounds")
async def sound_upload(file: UploadFile = File(...)):
    name = Path(file.filename or "music.mp3").name
    need(Path(name).suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac"), "Use an mp3, wav, ogg, m4a or flac file")
    (SOUNDS / name).write_bytes(await file.read())
    return sounds()


# ---------------------------------------------------------------- voice
def _site(url: str) -> str:
    return urlparse(url if "://" in url else "https://" + url).netloc.removeprefix("www.") or url


def speakable(text: str) -> str:
    """What the voice reads: no code, no markdown signs, and web addresses only as the site's name
    ("istockphoto.com" instead of every letter of https://www.istockphoto.com/photos/...)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # pictures: nothing to read
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  lambda m: _site(m[2]) if re.match(r"(https?://|www\.)", m[1]) else m[1], text)
    text = re.sub(r"(https?://|www\.)[^\s)\]>]+", lambda m: _site(m[0].rstrip(".,;:!?")) + m[0][len(m[0].rstrip(".,;:!?")):], text)
    text = re.sub(r"\b((?:[\w-]+\.)+[a-z]{2,})/[^\s)\]>]*", lambda m: m[1].removeprefix("www."), text)
    return re.sub(r"[*#`_>|]", "", text).strip()[:4000]


@app.post("/api/open")
def open_link(body: dict):
    """Links in the chat open in your normal web browser, not inside the app window."""
    url = str(body.get("url") or "")
    need(urlparse(url).scheme in ("http", "https") and bool(urlparse(url).netloc), "Only web links can be opened")
    webbrowser.open(url)
    return {"ok": True}


@app.post("/api/tts")
async def tts(body: dict):
    text = speakable(body.get("text", ""))
    need(re.search(r"\w", text), "Nothing to read")  # only symbols / emoji: nothing to say
    path = await run_in_threadpool(voice.speak, text, body.get("voice"))
    return FileResponse(path, media_type="audio/wav", background=BackgroundTask(wipe.shred, path))


@app.post("/api/stt")
async def stt(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "a.webm").suffix) as tmp:
        tmp.write(await file.read())
    try:
        return {"text": await run_in_threadpool(voice.transcribe, tmp.name)}
    finally:
        wipe.shred(tmp.name)  # your recorded voice


# ---------------------------------------------------------------- computer use
@app.post("/api/computer/start")
def computer_start(body: dict):
    try:
        return computer.start(body.get("task", "")).public()
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@app.get("/api/computer/tasks")
def computer_tasks():
    return [t.public() for t in sorted(computer.tasks.values(), key=lambda t: -t.created)[:10]]


@app.post("/api/computer/{tid}/decide")
def computer_decide(tid: str, body: dict):
    need(tid in computer.tasks, "Task not found", 404)
    computer.decide(tid, bool(body.get("approve")), bool(body.get("auto")))
    return {"ok": True}


@app.post("/api/computer/{tid}/stop")
def computer_stop(tid: str):
    computer.stop(tid)
    return {"ok": True}


# ---------------------------------------------------------------- memory & documents
@app.get("/api/memory")
def memory():
    return {"facts": db.q("SELECT id, text, kind, created, chat_id FROM facts ORDER BY id"),
            "documents": db.q("SELECT * FROM documents ORDER BY created DESC"),
            "persona": mem.persona(), "summaries": db.q("SELECT COUNT(*) AS n FROM summaries")[0]["n"],
            "auto": load_settings().get("memory_auto", True), "meaning": bool(mem.emb.model()),
            "lessons": mem.all_lessons(),  # what the AI learned from its own mistakes
            "rated": feedback.listing()}  # the answers given 👍 / 👎: good and bad examples


@app.delete("/api/lessons/{lid}")
def lesson_forget(lid: int):
    mem.forget_lesson(lid)
    return memory()


@app.post("/api/memory/persona")
async def memory_persona():
    """Rebuilds the profile (memory level 3) from the facts now."""
    try:
        await mem.refresh_persona(force=True)
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(400, f"The chat model is needed for this: {e}")
    return memory()


@app.post("/api/memory")
def memory_add(body: dict):
    need(body.get("text", "").strip(), "Write something to remember")
    db.run("INSERT INTO facts(text, created) VALUES (?,?)", (body["text"].strip(), time.time()))
    return memory()


@app.delete("/api/memory/{fid}")
def memory_delete(fid: int):
    db.run("DELETE FROM facts WHERE id=?", (fid,))
    return memory()


def _extract(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    if path.suffix.lower() == ".docx":
        import zipfile
        xml = zipfile.ZipFile(path).read("word/document.xml").decode(errors="ignore")
        return re.sub(r"<[^>]+>", " ", xml.replace("</w:p>", "\n"))
    return path.read_text(errors="ignore")


@app.post("/api/documents")
async def doc_upload(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename or "doc.txt").suffix) as tmp:
        tmp.write(await file.read())
    try:
        text = re.sub(r"[ \t]+", " ", await run_in_threadpool(_extract, Path(tmp.name))).strip()
    finally:
        wipe.shred(tmp.name)
    need(text, "No text found in that file")
    did = uuid.uuid4().hex[:12]
    db.run("INSERT INTO documents VALUES (?,?,?,?)", (did, file.filename, len(text), time.time()))
    db.many("INSERT INTO chunks(doc_id, text) VALUES (?,?)", [(did, text[i:i + 1200]) for i in range(0, len(text), 1000)])
    mem.background(mem.vectorize_document(did))  # meaning search for it, in the background
    return memory()


@app.delete("/api/documents/{did}")
def doc_delete(did: str):
    db.run("DELETE FROM chunks WHERE doc_id=?", (did,))
    db.run("DELETE FROM chunk_vecs WHERE doc_id=?", (did,))
    db.run("DELETE FROM documents WHERE id=?", (did,))
    wipe.checkpoint()
    return memory()


# ---------------------------------------------------------------- storage
def _size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


@app.get("/api/storage")
def storage():
    total, used, free = shutil.disk_usage(DATA)
    return {"disk": {"total": total, "free": free}, "models": _size(MODELS), "media": _size(MEDIA),
            "folders": load_settings()["model_dirs"]}


NEEDED_HELPERS = ("t5-v1_1-xxl-encoder", "clip_l.safetensors", "flux_ae.safetensors", "umt5-xxl-encoder",
                  "wan_2.1_vae.safetensors")


@app.get("/api/storage/files")
def storage_files():
    """Every file in the app's models folder, with what it's for — so leftovers can be deleted."""
    used = {Path(m["path"]).resolve() for m in models.scan()}
    used |= {Path(m["mmproj"]).resolve() for m in models.scan() if m.get("mmproj")}
    out = []
    for f in sorted(MODELS.rglob("*")):
        if not f.is_file() or f.name == "registry.json":
            continue
        n = f.name.lower()
        if f.suffix == ".part":
            what = "Unfinished download"
        elif f.resolve() in used:
            what = "Model"
        elif any(h in n for h in NEEDED_HELPERS):
            what = "Helper file (needed by FLUX / Wan)"
        elif f.parent.name == "piper" or f.parent.name.startswith("whisper-"):
            what = "Voice / speech file"
        else:
            what = "Not used by the app"
        out.append({"path": str(f), "name": f.name, "folder": f.parent.name, "size": f.stat().st_size, "what": what})
    return out


@app.post("/api/storage/open")
def storage_open(body: dict):
    target = {"models": MODELS, "media": MEDIA, "data": DATA, "sounds": SOUNDS}.get(body.get("what"))
    need(target, "Unknown folder")
    open_path(target)  # opens the file manager on a fixed app folder
    return {"ok": True}


@app.post("/api/import-v01")
def import_v01():
    """Copies chats, memory, documents and the gallery from Local AI 0.1, if it's on this PC."""
    old = Path.home() / "projects" / "local-ai-app" / "data"
    need((old / "app.db").exists(), "Local AI 0.1 wasn't found on this PC", 404)
    counts = {"chats": 0, "media": 0, "facts": 0}
    with closing(sqlite3.connect(old / "app.db")) as src:
        src.row_factory = sqlite3.Row
        for c in src.execute("SELECT * FROM conversations"):
            if not db.q("SELECT id FROM chats WHERE id=?", (c["id"],)):
                db.run("INSERT INTO chats VALUES (?,?,?,?)", (c["id"], c["title"], c["created"], c["updated"]))
                db.many("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
                        [(m["conv_id"], m["role"], m["content"], "{}", m["created"])
                         for m in src.execute("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (c["id"],))])
                counts["chats"] += 1
        have = {f["text"] for f in db.q("SELECT text FROM facts")}
        for f in src.execute("SELECT text FROM facts"):
            if f["text"] not in have:
                db.run("INSERT INTO facts(text, created) VALUES (?,?)", (f["text"], time.time()))
                counts["facts"] += 1
        for g in src.execute("SELECT * FROM gallery"):
            f = old / "media" / g["file"]
            if f.exists() and not (MEDIA / g["file"]).exists():
                shutil.copy2(f, MEDIA / g["file"])
                db.run("INSERT OR IGNORE INTO gallery VALUES (?,?,?,?,?)",
                       (g["id"], g["kind"], g["file"], g["prompt"] or "", g["created"]))
                counts["media"] += 1
    return counts


# ---------------------------------------------------------------- page
app.mount("/media", StaticFiles(directory=MEDIA), name="media")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


LAST_SEEN = {"t": time.time()}  # the page's last request (Linux in a normal browser tab: the app stops when it's gone)


@app.get("/api/ping")
def ping():
    """The page's heartbeat (every minute, also while hidden): the Linux starter keeps the app running while it comes."""
    return {"ok": True}


@app.middleware("http")
async def fresh_pages(request, call_next):
    """After an update the app window kept running old page code from its cache (a new Save button did nothing).
    no-cache = ask every time; unchanged files still come back as a quick 'not modified'."""
    if request.url.path.startswith("/api/"):
        LAST_SEEN["t"] = time.time()
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    elif request.url.path.startswith(("/api/", "/media/")):
        resp.headers["Cache-Control"] = "no-store"  # chats / pictures / videos never land in the window's disk cache
    return resp


def _page_version() -> str:
    """Changes whenever a page file changes: the page code then has a NEW address, so the app window can't keep
    running an old cached copy after an update (a new Save button once did nothing)."""
    return str(int(max(f.stat().st_mtime for f in STATIC.iterdir() if f.is_file())))


@app.get("/api/page_version")
def page_version():
    """The open window asks now and then: a different number = the app's pages were updated -> a Reload bar."""
    return {"v": _page_version()}


@app.get("/v/{ver}/{name}")
def page_file(ver: str, name: str):
    f = STATIC / Path(name).name
    need(f.is_file(), "Not found", 404)
    kind = {".js": "text/javascript", ".css": "text/css", ".png": "image/png"}.get(f.suffix)
    return FileResponse(f, media_type=kind, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/")
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8").replace('"/static/', f'"/v/{_page_version()}/')
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
