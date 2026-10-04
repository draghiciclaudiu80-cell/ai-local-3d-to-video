"""Plugins: tools you add yourself (Memory › Documents & plugins); the main model (or Laya) uses them.

A plugin is a folder with a plugin.json:
  {"id": "mytool", "name": "My tool", "description": "what it does — the AI reads this to decide when to use it",
   "triggers": ["word", "two words"],          # a message with one of these starts it directly (any model, Laya too)
   "run": ["{python}", "{plugin}/main.py", "{input}", "{outdir}"],
   "timeout": 120,
   "parameters": {JSON schema of what the AI fills in},
   "instructions": "how the AI fills the parameters in (short examples help small models)"}
Placeholders: {python} (the app's Python), {plugin} (the plugin's folder), {engines}, {root}, {input} (a JSON file
with the parameters), {outdir} (an empty folder for its files). The plugin prints one line "RESULT: {json}" (or just
JSON). Special result keys the app shows in the chat: "stl" (a 3D model: preview + 3D view + download), "image".
Plugins run programs on this PC — only add folders you trust. Built-in ones live in <app>/plugins."""
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import db, mirror3d, wipe
from .config import DATA, ENGINES, MEDIA, NO_WINDOW, ROOT, load_settings, save_settings
from .plat import kill_tree, spawn

BUILTIN = ROOT / "plugins"
DOTNET = ENGINES / "dotnet"


def _load(folder: Path, builtin: bool) -> dict | None:
    try:
        m = json.loads((folder / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not m.get("id") or not m.get("run"):
        return None
    m["id"] = re.sub(r"[^a-z0-9_]", "_", str(m["id"]).lower())[:40]
    m["path"], m["builtin"] = str(folder), builtin
    exe = _expand(m["run"][0], m, "", "")
    m["ready"] = not exe.lower().endswith(".exe") or Path(exe).exists()
    if m.get("requires"):  # e.g. Blender: one of these programs must be installed ("C:/Program Files/…/Blender */blender.exe")
        import glob
        m["ready"] = m["ready"] and any(glob.glob(os.path.expandvars(_expand(str(p), m, "", ""))) for p in m["requires"])
    m["enabled"] = load_settings().get("plugins_on", {}).get(m["id"], True)
    return m


def all_plugins() -> list[dict]:
    out, seen = [], set()
    folders = [(p, True) for p in sorted(BUILTIN.iterdir()) if p.is_dir()] if BUILTIN.exists() else []
    folders += [(Path(p), False) for p in load_settings().get("plugin_dirs", [])]
    for folder, builtin in folders:
        m = _load(folder, builtin)
        if m and m["id"] not in seen:
            seen.add(m["id"])
            out.append(m)
    return out


def get(pid: str) -> dict | None:
    return next((p for p in all_plugins() if p["id"] == pid), None)


def add(folder: str) -> dict:
    f = Path(folder.strip().strip('"'))
    m = _load(f, False) if f.is_dir() else None
    if not m:
        raise ValueError("That folder has no valid plugin.json (it needs at least \"id\" and \"run\").")
    if get(m["id"]):
        raise ValueError(f"A plugin called '{m['id']}' is already added.")
    save_settings({"plugin_dirs": load_settings().get("plugin_dirs", []) + [str(f)]})
    return m


def remove(pid: str) -> None:
    m = get(pid)
    if m and not m["builtin"]:
        save_settings({"plugin_dirs": [d for d in load_settings().get("plugin_dirs", []) if Path(d) != Path(m["path"])]})


def set_enabled(pid: str, on: bool) -> None:
    save_settings({"plugins_on": {**load_settings().get("plugins_on", {}), pid: bool(on)}})


def usable() -> list[dict]:
    return [p for p in all_plugins() if p["enabled"] and p["ready"]]


REQUEST = {"type": "object", "properties": {"request": {"type": "string", "description": "what to make or change, in the "
                                                        "user's words, with every size"}}, "required": ["request"]}


def slim(p: dict) -> bool:
    """Offered to the main model SHORT (only "request"): the 3D engines and every plugin with a long form. The app fills
    the real form itself when the model calls it (agent.plugin_params, with the full form + instructions)."""
    return p["id"] in ENGINES_3D or len(json.dumps(p.get("parameters") or {})) > 500


def tools() -> list[dict]:
    """Every usable plugin, as a tool the main model can call. The full forms were ~6,700 of the ~8,400 tokens of tools
    the model re-reads before an answer (Bonsai 27B reads ~65 tokens a second = 2 minutes; Qwen 3.5 4B ~20 s)."""
    out = []
    for p in usable():
        desc, params = f"{p.get('name', p['id'])}: {p.get('description', '')}", p.get("parameters") or REQUEST
        if slim(p):
            cut = desc.find(". ", 80, 320)
            desc, params = (desc[:cut + 1] if cut > 0 else desc[:320]) + " Pass the user's request; the app does the rest.", REQUEST
        out.append({"type": "function", "function": {"name": f"plugin_{p['id']}", "description": desc, "parameters": params}})
    return out


ENGINES_3D = ("picogk", "blender", "freecad")
# a request to MAKE something (-> a 3D engine) vs a question that wants NUMBERS (-> a calculator plugin)
DESIGN_WORDS = re.compile(r"\b(make|design|build|create|model|draw|generate|sketch|fă|fa-mi|construie\w*|proiecteaz\w*|"
                          r"deseneaz\w*|modeleaz\w*|creeaz\w*)\b", re.I)
ASKS = re.compile(r"\?|\b(how (much|many|long|fast|strong|thick|big|far|high|deep|hot|tight|heavy)|what(?:'s| is| are| size| "
                  r"torque| module| width| diameter| pressure| flow| current| resistor| value| hole| fit| wire| gauge| energy| "
                  r"speed| rpm)|which|calculate|calc|compute|work out|estimate|figure out|check|will (it|they|this|that|my|the)|"
                  r"can (it|they|this|my|the)|is (it|that|this) (enough|strong|ok)|enough|do i need|should i|cât|cat (e|este|"
                  r"trebuie|face|tine)|ce (cuplu|presiune|debit|diametru|rezisten|sarma)|calculea)", re.I)


def _hits(p: dict, t: str) -> bool:
    if any(re.search(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])", t) for w in p.get("triggers") or []):
        return True
    return any(re.search(rx, t) for rx in p.get("trigger_re") or [])


NUMBER_UNIT = re.compile(r"\d(?:[.,]\d+)?\s*(?:mm|cm|m|km|in|inch|inches|ft|kg|g|gr|grains?|n|kn|nm|n·m|kgcm|kg\s?cm|rpm|bar|"
                         r"psi|mpa|kpa|w|kw|hp|v|a|ma|mah|ah|wh|ohms?|k|uf|nf|pf|hz|khz|mhz|l/min|lpm|l/s|m3/h|gpm|m/s|"
                         r"km/h|fps|°c|°|deg|degrees|cc|l|litres?|liters?|%|oz|teeth|t|s)(?![a-z])", re.I)


def calculator_for(text: str) -> dict | None:
    """A question with numbers and engineering words but no trigger phrase ("my arm is 20 cm and lifts 100 g, which
    servo?"): the calculator plugin whose keywords fit best — instead of the router guessing "search the web"."""
    t = text.lower()
    if DESIGN_WORDS.search(t) or not ASKS.search(t) or not NUMBER_UNIT.search(t):
        return None
    best, score = None, 0
    for p in usable():
        if p.get("kind") != "calculator" or not p.get("keywords"):
            continue
        s = sum(len(w) for w in p["keywords"] if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t))
        if s > score:
            best, score = p, s
    return best if score >= 6 else None


def triggered(text: str) -> dict | None:
    """The plugin a message names by its words. A calculator wins a QUESTION ("what gear ratio do 20 and 60 teeth give?"),
    a 3D engine wins a request to make something ("make a gear pair")."""
    t = re.sub(r"\b3\s+d\b", "3d", text.lower())  # voice typing: "make it in 3 d"
    hits = [p for p in usable() if _hits(p, t)]
    if not hits:
        return None
    answer = [p for p in hits if p["id"] not in ENGINES_3D]
    design = [p for p in hits if p["id"] in ENGINES_3D]
    making = bool(DESIGN_WORDS.search(t))
    if answer and (not design or (ASKS.search(t) and not making)):
        return answer[0]
    if design:
        return design[0]
    return None if making and answer[0].get("kind") == "calculator" else answer[0]


def _expand(s: str, m: dict, inp: str, outdir: str) -> str:
    return (s.replace("{python}", sys.executable).replace("{plugin}", m["path"]).replace("{engines}", str(ENGINES))
            .replace("{root}", str(ROOT)).replace("{input}", inp).replace("{outdir}", outdir))


# A plugin run in progress (a 3D build): the chat and Create › 3D show a progress bar with a Stop button.
# phase "design" = the AI is writing the plan (the bar creeps), "build" = the engine reports "part 2 of 9", "fit", "save".
RUNS: dict[str, dict] = {}


def run_start(rid: str, text: str = "The AI is planning the design…", phase: str = "design") -> None:
    for k in [k for k, r in RUNS.items() if time.time() - r["started"] > 1800]:  # forget old ones
        RUNS.pop(k, None)
    RUNS[rid] = {"phase": phase, "text": text, "pct": 0.02, "started": time.time(), "stop": False, "done": False, "proc": None,
                 "touched": time.time()}


def run_set(rid: str | None, **kw) -> None:
    if rid and rid in RUNS:
        RUNS[rid].update(kw, touched=time.time())


def _dead(r: dict) -> bool:
    """No engine running and no news for 10 minutes: its chat crashed (the bar hung at 95 % and kept the PC awake)."""
    return not r.get("proc") and time.time() - r.get("touched", r["started"]) > 600


def run_state(rid: str) -> dict:
    r = RUNS.get(rid)
    if not r:
        return {"pending": True}
    t = time.time() - r["started"]
    pct = r["pct"]
    if r["phase"] == "design" and not r["done"]:  # no real steps while the AI writes: a slow creep up to 25 %
        pct = max(pct, 0.25 * (1 - 2.718 ** (-t / 40)))
    return {"text": r["text"], "pct": round(min(pct, 1), 3), "elapsed": round(t), "done": r["done"], "stopped": r["stop"],
            "phase": r["phase"]}


def run_stop(rid: str) -> bool:
    """Stop button: the AI's planning is cancelled (agent checks the flag), the 3D engine is killed with its children."""
    r = RUNS.get(rid)
    if not r or r["done"]:
        return False
    r["stop"], r["text"] = True, "Stopping…"
    if r.get("proc") and r["proc"].poll() is None:
        kill_tree(r["proc"].pid)
    return True


def active() -> list[dict]:
    """3D designs / builds going on now (the sidebar's "Stop everything" and the progress dock show them)."""
    return [{"id": k, **{x: run_state(k)[x] for x in ("text", "pct", "elapsed")}}
            for k, r in list(RUNS.items()) if not r["done"] and not r["stop"] and not _dead(r)]


def stop_all() -> int:
    return sum(run_stop(x["id"]) for x in active())


def _progress_line(rid: str | None, line: str) -> None:
    """"PROGRESS: 2/9 left cuff jaw" -> building part 3 of 9 (25-90 %); "PROGRESS: fit 9" -> the fit check (90 %)."""
    x = line[9:].strip()
    if x.startswith("threads"):  # FreeCAD cuts the screw threads last (a few seconds each)
        run_set(rid, phase="build", pct=0.85, text="Cutting the screw threads…")
        return
    if x.startswith("fit"):
        w = (x.split() + ["0"])[1]
        if not w.isdigit():  # "fit fixing the collisions" (a crash here once stopped reading Blender -> it hung)
            run_set(rid, phase="build", pct=0.93, text="Fixing the pieces that run into each other, then checking again…")
            return
        n = int(w)
        run_set(rid, phase="build", pct=0.9, text=f"Checking that the parts fit ({n * (n - 1) // 2} pairs)…")
        return
    try:
        i, n = (int(v) for v in x.split()[0].split("/"))
    except (ValueError, IndexError):
        return
    name = x.split(" ", 1)[1] if " " in x else ""
    run_set(rid, phase="build", pct=0.25 + 0.65 * i / max(n, 1),
            text=f"Building part {i + 1} of {n}{': ' + name if name and n > 1 else ''}…")


def import_stl(src: Path, name: str) -> dict:
    """An STL from the sandbox -> a Gallery 3D model (preview + 3D view). The file is only read, never run."""
    gid = uuid.uuid4().hex[:12]
    stl = MEDIA / f"model-{gid}.stl"
    tri = read_stl(src)
    write_stl(stl, tri)  # re-written from the parsed triangles: nothing else of the original file comes along
    view = _view_copy(tri, stl)
    preview([(view if view is not None else tri, PALETTE[0])], stl.with_suffix(".png"))
    db.add_gallery(gid, "model", stl.name, f"{name} (from the sandbox)"[:80])
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    return {"stl": f"/media/{stl.name}", "preview": f"/media/{stl.with_suffix('.png').name}", "name": name[:80],
            "size_mm": [round(float(x), 1) for x in hi - lo], "triangles": int(len(tri)),
            "grams": round(stl_volume(tri) / 1000 * PLA, 1), **({"view": f"/media/{stl.stem}.view.stl"} if view is not None else {})}


def blender_finish(gid: str, name: str, m3: dict, rid: str | None = None) -> None:
    """Another engine (PicoGK) built it; Blender — if installed and switched on — renders a real picture in the parts'
    colours (it becomes the preview) and writes one GLB (colours, for other 3D apps; added to the zip)."""
    b = get("blender")
    if not b or not b["enabled"] or not b["ready"]:
        return
    items = [{"name": p.get("name") or name, "stl": str(MEDIA / Path(p.get("view") or p["stl"]).name),  # light copy is plenty
              "color": p.get("color") or "#4ad696", "reference": bool(p.get("reference"))}
             for p in (m3.get("parts") or [{"name": name, "stl": m3["stl"], "view": m3.get("view")}]) if p.get("stl")]
    work = DATA / "plugin-runs" / ("finish-" + uuid.uuid4().hex[:10])
    out = work / "out"
    out.mkdir(parents=True)
    (work / "in.json").write_text(json.dumps({"mode": "finish", "name": name, "bodies": items}), encoding="utf-8")
    run_set(rid, pct=0.97, text="Blender is rendering the picture and the GLB…")
    try:
        p = spawn([sys.executable, str(Path(b["path"]) / "run.py"), str(work / "in.json"), str(out)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore",
                             creationflags=NO_WINDOW)
        run_set(rid, proc=p)  # the Stop button reaches it too
        txt, _ = p.communicate(timeout=240)
        line = next((x[7:] for x in reversed(txt.splitlines()) if x.startswith("RESULT:")), "{}")
        r = json.loads(line)
        if r.get("render") and Path(r["render"]).exists():
            shutil.copyfile(r["render"], MEDIA / f"model-{gid}.png")
        if r.get("glb") and Path(r["glb"]).exists():
            glb = MEDIA / f"model-{gid}.glb"
            shutil.move(r["glb"], glb)
            m3["glb"] = f"/media/{glb.name}"
            zp = MEDIA / f"model-{gid}.zip"
            if zp.exists():
                import zipfile
                with zipfile.ZipFile(zp, "a", zipfile.ZIP_DEFLATED) as z:
                    if f"{safe_zip_name(name)}.glb" not in z.namelist():
                        z.write(glb, f"{safe_zip_name(name)}.glb")
        m3["finished_by"] = r.get("engine")
    except (subprocess.TimeoutExpired, OSError, ValueError):
        kill_tree(p.pid) if "p" in locals() else None
    finally:
        run_set(rid, proc=None)
        wipe.shred_tree(work)


def fits_bed(size, bed) -> bool:
    """Fits the plate (turning it on the plate is allowed: x / y may swap)."""
    if not size or len(size) < 3:
        return True
    x, y, z = (float(v) for v in size[:3])
    return z <= bed[2] + 0.01 and ((x <= bed[0] + 0.01 and y <= bed[1] + 0.01) or (y <= bed[0] + 0.01 and x <= bed[1] + 0.01))


def too_big_parts(m3: dict, bed) -> list[str]:
    parts = m3.get("parts") or [{"name": m3.get("name"), "size_mm": m3.get("size_mm")}]
    return [str(p.get("name") or "model") for p in parts if not p.get("reference") and not fits_bed(p.get("size_mm"), bed)]


def cut_to_fit(m3: dict, bed=None, pin: str = "filament", rid: str | None = None) -> dict:
    """A model with parts too big for the printer's plate -> a NEW Gallery model where those parts are cut into pieces
    that fit, with holes for alignment pins in the cut faces (Blender's exact booleans; bl_cut.py). The original stays.
    -> {"model3d": the cut model, "notes": ...} or {"fits": True} or {"error": ...}."""
    bed = [float(x) for x in (bed or load_settings().get("printer_bed") or [220, 220, 250])][:3]
    b = get("blender")
    if not b or not b["ready"]:
        return {"error": "Blender isn't installed, and it does the cutting"}
    parts = m3.get("parts") or [{"name": m3.get("name") or "model", "stl": m3.get("stl"), "size_mm": m3.get("size_mm")}]
    if not too_big_parts({"parts": parts}, bed):
        return {"fits": True}
    work = DATA / "plugin-runs" / ("cut-" + uuid.uuid4().hex[:10])
    out = work / "out"
    out.mkdir(parents=True)
    bodies = []
    for p in parts:
        src = MEDIA / Path(str(p.get("stl") or "")).name  # the full STL, not the light view copy
        if p.get("stl") and src.exists():
            bodies.append({"name": p.get("name") or "part", "stl": str(src), "color": p.get("color"),
                           "reference": bool(p.get("reference"))})
    name = f"{m3.get('name') or 'model'} (cut to fit)"[:80]
    (work / "in.json").write_text(json.dumps({"mode": "cut", "name": name, "bodies": bodies, "bed": bed, "pin": pin}), encoding="utf-8")
    run_set(rid, phase="build", pct=0.5, text="Cutting it into pieces that fit the printer…")
    try:
        p = spawn([sys.executable, str(Path(b["path"]) / "run.py"), str(work / "in.json"), str(out)],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore",
                             creationflags=NO_WINDOW)
        run_set(rid, proc=p)
        txt, _ = p.communicate(timeout=300)
        line = next((x[7:] for x in reversed(txt.splitlines()) if x.startswith("RESULT:")), "{}")
        r = json.loads(line)
        if r.get("error") or not r.get("bodies"):
            return {"error": r.get("error") or "the cutter made nothing"}
        pieces = []
        for i, piece in enumerate(r["bodies"]):  # the parts that already fit are COPIED (the original model keeps its files)
            f = Path(piece["stl"])
            if MEDIA in f.resolve().parents:
                dst = out / f"keep_{i}.stl"
                shutil.copyfile(f, dst)
                f = dst
            tri = read_stl(f)
            if not len(tri):
                continue
            lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
            pieces.append({**piece, "stl": str(f), "size_mm": [round(float(v), 1) for v in hi - lo], "triangles": int(len(tri))})
        gid = uuid.uuid4().hex[:12]
        notes = (r.get("notes") or "") + f" Each piece fits the {bed[0]:g} × {bed[1]:g} × {bed[2]:g} mm plate."
        recipe = {"name": name, "engine": "blender", "mode": "cut", "from": m3.get("stl"), "bed": bed}
        cut_m3 = _assembly(gid, name, pieces, {"notes": notes}, recipe)  # (it adds the Gallery entry too)
        cut_m3.update(name=name, recipe=recipe, plugin="blender", cut_from=m3.get("stl"))
        return {"model3d": cut_m3, "notes": notes, "pieces": len(pieces)}
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        if "p" in locals():
            kill_tree(p.pid)
        return {"error": f"cutting failed: {e}"[:200]}
    finally:
        run_set(rid, proc=None)
        wipe.shred_tree(work)


SIDES = ["left ↔ right", "front ↔ back", "up ↔ down"]


def mirror_model(m3: dict, axis: int = 0) -> dict:
    """⇋ A mirrored copy of a built model — a left hand from a right hand, a left leg from a right one. Works on ANY
    model, also a sculpted mesh nobody can edit as parts: every part's triangles flipped across the model's middle, their
    winding reversed (the outside stays outside). A PicoGK / FreeCAD design also gets its recipe mirrored (mirror3d.py,
    the editor's math), so Edit in 3D and rebuilding still work on the copy. A NEW Gallery model; the original stays.
    -> {"model3d": ..., "editable": bool} or {"error": ...}."""
    axis = axis if axis in (0, 1, 2) else 0
    parts = m3.get("parts") or [{"name": m3.get("name") or "model", "stl": m3.get("stl")}]
    tris = []
    for p in parts:
        src = MEDIA / Path(str(p.get("stl") or "")).name  # only a file of the app's own (no paths from outside)
        if p.get("stl") and src.is_file():
            t = read_stl(src)
            if len(t):
                tris.append((p, t))
    if not tris:
        return {"error": "this model's files aren't there any more"}
    pts = np.concatenate([t.reshape(-1, 3) for _, t in tris])
    mid = (pts.min(0) + pts.max(0)) / 2
    work = DATA / "plugin-runs" / ("mirror-" + uuid.uuid4().hex[:10])
    work.mkdir(parents=True)
    try:
        bodies = []
        for i, (p, t) in enumerate(tris):
            t = t.astype(np.float32).copy()
            t[..., axis] = 2 * mid[axis] - t[..., axis]
            t = t[:, [0, 2, 1], :]  # reversed winding: a mirror turns a mesh inside out, this turns it back
            f = work / f"m{i}.stl"
            write_stl(f, t)
            lo, hi = t.reshape(-1, 3).min(0), t.reshape(-1, 3).max(0)
            bodies.append({"name": p.get("name") or f"part {i + 1}", "stl": str(f), "color": p.get("color"),
                           "reference": bool(p.get("reference")), "size_mm": [round(float(v), 1) for v in hi - lo],
                           "triangles": int(len(t))})
        full = None  # the design saved next to the model is the full one (every part and hole)
        j = MEDIA / (Path(str(m3.get("stl") or "")).stem + ".json")
        try:
            full = json.loads(j.read_text(encoding="utf-8")) if j.is_file() else None
        except (OSError, ValueError):
            full = None
        rec = mirror3d.mirror_recipe(full if isinstance(full, dict) else m3.get("recipe"), axis, [float(x) for x in mid])
        name = f"{m3.get('name') or 'model'} (mirrored)"[:80]
        if rec:
            rec["name"] = name
        notes = (f"A mirror image ({SIDES[axis]}) of “{m3.get('name') or 'the model'}” — the original stays."
                 + ("" if rec else " (A mesh: print it as it is; it can't be edited as parts.)"))
        recipe = rec or {"name": name, "engine": "mesh", "mode": "mirror", "axis": axis, "from": m3.get("stl")}
        out = _assembly(uuid.uuid4().hex[:12], name, bodies, {"notes": notes, "collisions": m3.get("collisions") or [],
                                                             "checked_pairs": m3.get("checked_pairs")}, recipe, rec)
        out.update(name=name, recipe=recipe, mirror_of=m3.get("stl"),
                   plugin=("freecad" if rec.get("engine") == "freecad" else "picogk") if rec else "mesh")
        return {"model3d": out, "editable": bool(rec), "notes": notes}
    except (OSError, ValueError) as e:
        return {"error": f"mirroring failed: {e}"[:200]}
    finally:
        wipe.shred_tree(work)


def code_to_recipe(code: str, name: str = "design") -> dict:
    """A Python-code (Blender) design as shapes Create › 3D can edit: its code replayed with RECORDING building blocks
    (plugins/blender/code_recipe.py — no Blender, the same code check, only math / random). -> {"recipe"} or {"error"}."""
    work = DATA / "plugin-runs" / ("edit-" + uuid.uuid4().hex[:10])
    work.mkdir(parents=True)
    try:
        (work / "in.json").write_text(json.dumps({"code": code, "name": name}), encoding="utf-8")
        subprocess.run([sys.executable, str(BUILTIN / "blender" / "code_recipe.py"), str(work / "in.json"), str(work / "out.json")],
                       timeout=60, capture_output=True, creationflags=NO_WINDOW)
        out = work / "out.json"
        return json.loads(out.read_text(encoding="utf-8")) if out.exists() else {"error": "the design's code couldn't be read as parts"}
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        return {"error": f"couldn't read the design: {e}"[:200]}
    finally:
        wipe.shred_tree(work)


def safe_zip_name(name: str) -> str:
    return re.sub(r"[^\w .\-()]", "", str(name))[:60].strip() or "model"


def discard(m3: dict) -> None:
    """A design the app replaced itself (the fix step built a better one): its files and Gallery entry go."""
    stem = Path(str(m3.get("stl", ""))).stem
    if not stem.startswith("model-"):
        return
    db.run("DELETE FROM gallery WHERE id=?", (stem[6:],))
    for f in [*MEDIA.glob(stem + ".*"), *MEDIA.glob(stem + "-*")]:
        wipe.shred(f)


def expand(pid: str, params: dict) -> dict | None:
    """A design as its parts, without building it (a ready-made design's template expanded, holes placed by face turned
    into points) — what Create › 3D needs to edit it. None = it couldn't."""
    m = get(pid)
    if not m or not m["enabled"] or not m["ready"]:
        return None
    work = DATA / "plugin-runs" / ("x-" + uuid.uuid4().hex[:10])
    outdir = work / "out"
    outdir.mkdir(parents=True)
    inp = work / "input.json"
    inp.write_text(json.dumps({**params, "expand_only": True}), encoding="utf-8")
    try:
        p = subprocess.run([_expand(a, m, str(inp), str(outdir)) for a in m["run"]], capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", cwd=m["path"], timeout=60, creationflags=NO_WINDOW)
        line = next((x[7:] for x in reversed(p.stdout.splitlines()) if x.startswith("RESULT:")), "{}")
        full = json.loads(line).get("full")
        return full if isinstance(full, dict) else None
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    finally:
        wipe.shred_tree(work)


def run(pid: str, params: dict, rid: str | None = None, finish: bool = True, pretty: bool = True) -> dict:
    """Runs a plugin with the AI's parameters; its files go to the gallery / chat. Blocking: call in a thread.
    rid = a progress entry (RUNS) the page shows; its Stop button kills the run. pretty=False: no Blender picture / GLB
    afterwards (Create › 3D's quick rebuilds)."""
    if rid and rid not in RUNS:
        run_start(rid, "Starting the 3D engine…", "build")
    run_set(rid, phase="build", pct=max(0.25, RUNS.get(rid, {}).get("pct", 0)), text="Starting the 3D engine…")
    m = get(pid)
    if not m or not m["enabled"]:
        return {"error": f"plugin '{pid}' isn't available"}
    if not m["ready"]:
        return {"error": f"{m.get('name', pid)} isn't set up yet"}
    work = DATA / "plugin-runs" / uuid.uuid4().hex[:12]
    outdir = work / "out"
    outdir.mkdir(parents=True)
    inp = work / "input.json"
    inp.write_text(json.dumps(params), encoding="utf-8")
    env = {**os.environ, "DOTNET_ROOT": str(DOTNET), "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    try:
        p = spawn([_expand(a, m, str(inp), str(outdir)) for a in m["run"]], stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore", env=env, cwd=m["path"],
                             creationflags=NO_WINDOW)
        run_set(rid, proc=p)
        late = threading.Timer(int(m.get("timeout", 120)), lambda: kill_tree(p.pid))
        late.start()
        lines, err = [], []
        reader = threading.Thread(target=lambda: err.extend(p.stderr), daemon=True)  # stderr must not fill up and block
        reader.start()
        for x in p.stdout:
            if x.startswith("PROGRESS:"):
                try:
                    _progress_line(rid, x)
                except (ValueError, IndexError):  # an odd progress line must never stop the reading (the engine hangs)
                    pass
            else:
                lines.append(x)
        p.wait()
        reader.join(5)
        timed_out = not late.is_alive() and p.returncode != 0
        late.cancel()
        if RUNS.get(rid, {}).get("stop"):
            return {"error": "stopped", "stopped": True}
        if timed_out:
            raise subprocess.TimeoutExpired(m["run"], int(m.get("timeout", 120)))
        run_set(rid, pct=0.95, text="Saving the parts and the preview…")
        out, errors = "".join(lines).strip(), "".join(err)
        line = next((x[7:] for x in reversed(out.splitlines()) if x.startswith("RESULT:")), out)
        try:
            result = json.loads(line)
        except ValueError:
            result = {"output": out[-3000:]} if p.returncode == 0 else {"error": (errors or out)[-500:] or "it failed"}
        if not isinstance(result, dict):
            result = {"output": result}
        result["params"] = params  # what the plugin was given (a 3D design's recipe: "make it taller" starts from it)
        gid = uuid.uuid4().hex[:12]
        if isinstance(result.get("recipe"), dict):  # what the plugin really built (a template expanded into its parts)
            params = result["params"] = result.pop("recipe")
        editable = result.pop("full", None)  # FreeCAD: every part and hole one by one (a template stays short above)
        editable = editable if isinstance(editable, dict) else params
        name = str(result.get("name") or params.get("name") or m.get("name") or "3D model")[:80]
        bodies = [b for b in result.pop("bodies", None) or [] if Path(str(b.get("stl", ""))).exists()]
        if len(bodies) > 1:  # an assembly: every part its own STL, one colour each, a zip, and the fit check
            result["model3d"] = _assembly(gid, name, bodies, result, params, editable)
            result.pop("stl", None)
        elif result.get("stl") and Path(result["stl"]).exists():
            stl = MEDIA / f"model-{gid}.stl"
            shutil.move(result.pop("stl"), stl)
            tri = read_stl(stl)
            view = _view_copy(tri, stl)
            preview([(view if view is not None else tri, PALETTE[0])], stl.with_suffix(".png"))
            stl.with_suffix(".json").write_text(json.dumps(editable), encoding="utf-8")  # the recipe: "Edit in 3D" reopens it
            db.add_gallery(gid, "model", stl.name, name)
            result["model3d"] = {"stl": f"/media/{stl.name}", "preview": f"/media/{stl.with_suffix('.png').name}", "recipe": params,
                                 "name": name, "size_mm": result.get("size_mm"), "triangles": result.get("triangles"),
                                 "grams": round(stl_volume(tri) / 1000 * PLA, 1),
                                 **({"view": f"/media/{stl.stem}.view.stl"} if view is not None else {})}
        m3 = result.get("model3d")
        if m3 and pid != "blender" and finish and pretty and not result.get("glb") and not RUNS.get(rid or "", {}).get("stop"):
            blender_finish(gid, name, m3, rid)  # PicoGK's parts through Blender too: a real picture + a GLB (the chat
            # finishes its final one itself; on Linux Blender built it already — picture + GLB came with it)
        if m3 and result.get("render") and Path(result["render"]).exists():  # Blender's rendered picture = the preview
            shutil.copyfile(result.pop("render"), MEDIA / f"model-{gid}.png")
        if m3 and result.get("glb") and Path(result["glb"]).exists():  # a GLB (colours, one file) for other 3D apps
            glb = MEDIA / f"model-{gid}.glb"
            shutil.move(result.pop("glb"), glb)
            m3["glb"] = f"/media/{glb.name}"
            zp = MEDIA / f"model-{gid}.zip"
            if zp.exists():
                import zipfile
                with zipfile.ZipFile(zp, "a", zipfile.ZIP_DEFLATED) as z:
                    z.write(glb, f"{safe_zip_name(name)}.glb")
        if m3 and result.get("step") and Path(result["step"]).exists():  # FreeCAD: one exact CAD file (CNC / other CAD)
            step = MEDIA / f"model-{gid}.step"
            shutil.move(result.pop("step"), step)
            m3["step"] = f"/media/{step.name}"
            if result.get("holes"):
                m3.setdefault("holes", result["holes"])
            zp = MEDIA / f"model-{gid}.zip"
            if zp.exists():
                import zipfile
                with zipfile.ZipFile(zp, "a", zipfile.ZIP_DEFLATED) as z:
                    z.write(step, f"{safe_zip_name(name)} (whole).step")
        if result.get("image") and Path(result["image"]).exists():
            img = MEDIA / f"plugin-{gid}{Path(result['image']).suffix}"
            shutil.move(result.pop("image"), img)
            db.add_gallery(gid, "image", img.name, str(result.get("name") or params)[:80])
            result["picture"] = f"/media/{img.name}"
        if m3:
            result["full"] = editable  # Create › 3D carries on editing exactly what was built
        return result
    except subprocess.TimeoutExpired:
        return {"error": f"{m.get('name', pid)} took too long and was stopped"}
    except OSError as e:
        return {"error": str(e)[:300]}
    except Exception as e:  # noqa: BLE001 — saving went wrong: an error the AI can fix, never a crashed chat
        return {"error": f"saving the 3D model failed: {e}"[:300]}
    finally:
        run_set(rid, proc=None, **({"done": True, "pct": 1.0} if finish else {}))  # finish=False: a step of a longer plan
        wipe.shred_tree(work)


PALETTE = [(74, 214, 150), (90, 169, 255), (255, 179, 71), (255, 111, 145), (195, 155, 255), (127, 219, 218),
           (249, 248, 113), (255, 150, 113), (160, 200, 120), (230, 120, 220)]
REFERENCE = (150, 156, 165)  # things you buy (spring, motor, pins): grey
PLA = 1.24  # g/cm3
STL_DT = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
VIEW_MAX = 220_000  # triangles the 3D view gets per part (the full file stays for printing)


def read_stl(path: Path) -> np.ndarray:
    data = Path(path).read_bytes()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + n * 50 == len(data):  # binary STL (the size must match exactly)
            return np.frombuffer(data, dtype=STL_DT, count=n, offset=84)["v"].astype(np.float32)
    if data[:5].lower() == b"solid":  # text (ASCII) STL, common in downloads
        v = re.findall(rb"vertex\s+(\S+)\s+(\S+)\s+(\S+)", data)
        if v and len(v) % 3 == 0:
            return np.array(v, dtype=np.float32).reshape(-1, 3, 3)
    raise ValueError("this is not a readable STL file")


def write_stl(path: Path, tri: np.ndarray) -> None:
    arr = np.zeros(len(tri), dtype=STL_DT)
    arr["v"] = tri
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    arr["n"] = nrm / (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12)
    with open(path, "wb") as f:
        f.write(b"Local AI / PicoGK".ljust(80, b" ") + struct.pack("<I", len(tri)))
        f.write(arr.tobytes())


def stl_volume(tri: np.ndarray) -> float:
    t = tri.astype(np.float64)
    return abs(float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum()) / 6)


def decimate(tri: np.ndarray, target: int) -> np.ndarray:
    """Fewer triangles, same shape (vertex clustering) — for the 3D view and the preview only."""
    if len(tri) <= target:
        return tri
    v = tri.reshape(-1, 3).astype(np.float64)
    lo = v.min(0)
    area = float(np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1).sum()) / 2
    cell = max((area / (target / 2)) ** 0.5, 1e-3)
    out = tri
    for _ in range(8):
        k = np.floor((v - lo) / cell).astype(np.int64)
        n = k.max(0) + 1
        key = (k[:, 0] * n[1] + k[:, 1]) * n[2] + k[:, 2]
        uniq, inv = np.unique(key, return_inverse=True)
        cnt = np.bincount(inv)
        rep = np.stack([np.bincount(inv, weights=v[:, j]) / cnt for j in range(3)], 1)
        f = inv.reshape(-1, 3)
        f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
        out = rep[f].astype(np.float32)
        if len(out) <= target * 1.25:
            break
        cell *= 1.35
    return out


def _view_copy(tri: np.ndarray, stl: Path):
    if len(tri) <= VIEW_MAX:
        return None
    view = decimate(tri, VIEW_MAX)
    write_stl(stl.with_name(stl.stem + ".view.stl"), view)
    return view


def _assembly(gid: str, name: str, bodies: list[dict], result: dict, params: dict, editable: dict | None = None) -> dict:
    import zipfile
    parts, shown, total = [], [], None
    zpath = MEDIA / f"model-{gid}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for i, b in enumerate(bodies):
            stl = MEDIA / f"model-{gid}-{i}.stl"
            shutil.move(b["stl"], stl)
            tri = read_stl(stl)
            if not len(tri):  # a piece cut / joined away to nothing: skipped (a drone's empty part crashed the save)
                stl.unlink(missing_ok=True)
                continue
            view = _view_copy(tri, stl)
            hx = str(b.get("color") or "")  # Blender gives each piece its real colour
            color = (tuple(int(hx[k:k + 2], 16) for k in (1, 3, 5)) if re.fullmatch(r"#[0-9a-fA-F]{6}", hx)
                     else REFERENCE if b.get("reference") else PALETTE[i % len(PALETTE)])
            shown.append((decimate(view if view is not None else tri, 60_000), color))
            safe = re.sub(r"[^\w ()+-]", "", b["name"]).strip() or f"part {i + 1}"
            z.write(stl, f"{i + 1:02d} {safe}.stl")
            if b.get("step") and Path(str(b["step"])).exists():  # FreeCAD: the exact CAD file of each part too
                z.write(b["step"], f"{i + 1:02d} {safe}.step")
            vol = stl_volume(tri)
            parts.append({"name": b["name"], "stl": f"/media/{stl.name}", "size_mm": b.get("size_mm"), "triangles": b.get("triangles"),
                          "color": "#%02x%02x%02x" % color, "reference": bool(b.get("reference")),
                          "grams": None if b.get("reference") else round(vol / 1000 * PLA, 1),
                          **({"view": f"/media/{stl.stem}.view.stl"} if view is not None else {}),
                          **{k: b[k] for k in ("fill", "open_top", "inside_depth_mm", "outline_mm", "round", "holes") if k in b}})
            lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
            total = (lo, hi) if total is None else (np.minimum(total[0], lo), np.maximum(total[1], hi))
        if result.get("notes"):
            z.writestr("00 read me.txt", result["notes"] + "\n\nParts:\n" + "\n".join(
                f"- {p['name']}: {' x '.join(str(round(x)) for x in p['size_mm'] or [])} mm" + (" (buy this)" if p["reference"] else f", ~{p['grams']} g PLA")
                for p in parts))
    whole = MEDIA / f"model-{gid}.stl"  # the gallery's file: the whole assembly (light copy) to look at
    write_stl(whole, np.concatenate([t for t, _ in shown]))
    preview(shown, whole.with_suffix(".png"))
    whole.with_suffix(".json").write_text(json.dumps(editable or params), encoding="utf-8")
    info = {"parts": parts, "collisions": result.get("collisions") or [], "checked_pairs": result.get("checked_pairs"),
            "notes": result.get("notes"), "zip": f"/media/{zpath.name}",
            **({"gaps": result["gaps"]} if result.get("gaps") else {}),  # FreeCAD: the exact gaps between parts (mm)
            **({"raw_collisions": result["raw_collisions"]} if result.get("raw_collisions") else {}),
            **({"fit_fixed": result["fit_fixed"]} if result.get("fit_fixed") else {})}  # the app fixed these itself
    (MEDIA / f"model-{gid}.parts.json").write_text(json.dumps(info), encoding="utf-8")
    db.add_gallery(gid, "model", whole.name, name)
    size = [round(float(x), 1) for x in total[1] - total[0]] if total else None
    return {"stl": f"/media/{whole.name}", "preview": f"/media/{whole.with_suffix('.png').name}", "recipe": params,
            "name": name, "size_mm": size, "triangles": sum(p["triangles"] or 0 for p in parts), **info}


def preview_stl(stl: Path, png: Path, size: int = 640) -> None:
    preview([(read_stl(stl), PALETTE[0])], png, size)


def preview(parts: list, png: Path, size: int = 640) -> None:
    """A shaded picture of a model — each part in its colour — seen from the front-right, a bit from above.
    Drawn on the processor (no graphics card needed)."""
    tri = np.concatenate([t for t, _ in parts]).astype(np.float64)
    cols = np.concatenate([np.tile(np.array(c, dtype=np.float64), (len(t), 1)) for t, c in parts])
    tri -= (tri.reshape(-1, 3).max(0) + tri.reshape(-1, 3).min(0)) / 2
    az, el = np.radians(35), np.radians(28)
    rz = np.array([[np.cos(az), -np.sin(az), 0], [np.sin(az), np.cos(az), 0], [0, 0, 1]])
    s_, c_ = np.sin(el), np.cos(el)
    rx = np.array([[1, 0, 0], [0, s_, c_], [0, -c_, s_]])  # view: x right, y up, z towards the viewer (Z stays up)
    v = tri @ (rx @ rz).T
    nrm = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
    nrm /= np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-12
    if (nrm[:, 2] > 0).mean() < 0.2:  # unusual winding: normals point inwards
        nrm = -nrm
    keep = nrm[:, 2] > 0
    v, nrm, cols = v[keep], nrm[keep], cols[keep]
    big = size * 2
    pts = v[:, :, :2] * np.array([1, -1])
    lo, hi = pts.reshape(-1, 2).min(0), pts.reshape(-1, 2).max(0)
    pts = (pts - (lo + hi) / 2) * (big * 0.86 / max((hi - lo).max(), 1e-6)) + big / 2
    light = np.array([-0.4, 0.6, 0.7])
    shade = 0.35 + 0.65 * np.clip(nrm @ (light / np.linalg.norm(light)), 0, 1)
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in np.argsort(v[:, :, 2].mean(1)):  # far first
        d.polygon([tuple(q) for q in pts[i]], fill=tuple(int(x) for x in cols[i] * shade[i]) + (255,))
    img.resize((size, size), Image.LANCZOS).save(png)
