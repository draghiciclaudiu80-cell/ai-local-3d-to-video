"""PicoGK plugin runner: python run.py <input.json> <output folder>
1) repairs what models send (lists as text "[0,0,0]" / "0, 0, 0", a parts list sent as one JSON string — that crashed
   a real chat), 2) expands a ready-made functional design ("template": dart_blaster / centrifugal_pump / gear_pair /
   box_with_lid, handcuffs) into its parts, 3) turns screw holes and threads (Create › 3D) into the cuts and coils the
   engine knows, 4) runs the 3D engine, 5) prints its RESULT plus the full recipe (for Edit in 3D)."""
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from templates import TEMPLATES, _hexagon  # noqa: E402

ENGINES = HERE.parent.parent / "engines"
RUNNER = ENGINES / "picogk" / "Runner" / "bin" / "Release" / "net9.0" / "Runner.exe"
NUM_LIST = re.compile(r"\s*\[?\s*-?\d+(\.\d+)?(\s*[,; ]\s*-?\d+(\.\d+)?){1,2}\s*\]?\s*")
# Screw holes that print well (the same numbers as the FreeCAD plugin and skills/threads-fasteners): diameter in mm
CLEARANCE = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 8.6, "M10": 10.6}
TAP = {"M2": 1.7, "M2.5": 2.2, "M3": 2.6, "M4": 3.5, "M5": 4.3, "M6": 5.1, "M8": 6.9, "M10": 8.7}
INSERT = {"M2": 3.2, "M2.5": 3.6, "M3": 4.1, "M4": 5.6, "M5": 6.4, "M6": 8.0, "M8": 10.0, "M10": 12.0}
INSERT_LEN = {"M2": 4.0, "M2.5": 5.0, "M3": 5.7, "M4": 8.1, "M5": 9.5, "M6": 12.7, "M8": 12.7, "M10": 15.0}
NUT_AF = {"M2": 4.3, "M2.5": 5.3, "M3": 5.8, "M4": 7.3, "M5": 8.3, "M6": 10.3, "M8": 13.3, "M10": 16.3}
NUT_H = {"M2": 1.9, "M2.5": 2.3, "M3": 2.7, "M4": 3.5, "M5": 4.3, "M6": 5.5, "M8": 6.8, "M10": 8.7}
CBORE = {"M2": (4.4, 2.2), "M2.5": (5.0, 2.7), "M3": (6.5, 3.2), "M4": (8.0, 4.2), "M5": (9.5, 5.2), "M6": (11.0, 6.2),
         "M8": (14.0, 8.2), "M10": (17.5, 10.2)}
CSINK = {"M2": 4.4, "M2.5": 5.4, "M3": 7.1, "M4": 9.4, "M5": 11.6, "M6": 13.8, "M8": 18.3, "M10": 22.4}
PLAY = 0.3  # mm all round between a printed thread and its partner (the bolt and nut template's tested value)


def fix(v):
    if isinstance(v, str):
        s = v.strip()
        if s[:1] in "[{":
            try:
                return fix(json.loads(s))
            except ValueError:
                pass
        if NUM_LIST.fullmatch(s):
            return [float(x) for x in re.split(r"[,;\s]+", s.strip("[] ")) if x]
        return v
    if isinstance(v, list):
        return [fix(x) for x in v]
    if isinstance(v, dict):
        return {k: fix(x) for k, x in v.items()}
    return v


def expand(r: dict) -> dict:
    name = str(r.get("template") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if name in TEMPLATES:
        opts = r.get("options") if isinstance(r.get("options"), dict) else {}
        out = TEMPLATES[name](opts)
        if r.get("name"):
            out["name"] = r["name"]
        out["template"], out["options"] = name, opts
        return out
    for bd in r.get("bodies") or [r]:  # a curved pipe given only from/to (no path points): a straight one
        for q in bd.get("parts") or []:
            if isinstance(q, dict) and q.get("shape") == "curved_pipe" and len(q.get("points") or []) < 2 and q.get("from") and q.get("to"):
                q["points"] = [q["from"], q["to"]]
            # a box-like shape without a size ("a 50 mm cube filled with…"): use its height for all three sides
            if isinstance(q, dict) and q.get("shape") in ("box", "tpms", "lattice", "gyroid") and not q.get("size") and q.get("height"):
                q["size"] = [q["height"]] * 3
    if not r.get("parts") and not r.get("bodies"):
        raise ValueError("the design has no parts (and no known template: " + ", ".join(TEMPLATES) + ")")
    return r


def _num(v, d: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return d
    return min(max(x, lo), hi) if x == x else d


def _v3(v, d=(0.0, 0.0, 0.0)) -> list[float]:
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return list(d)
    return [_num(v[i], d[i], -5000, 5000) for i in range(3)]


def _turn(v, deg) -> list[float]:
    """v turned like the parts: X first, then Y, then Z (degrees)."""
    x, y, z = v
    a, b, c = (math.radians(_num(t, 0, -360, 360)) for t in (list(deg or []) + [0, 0, 0])[:3])
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    return [x, y, z]


def _aim(D) -> list[float]:
    """The turn [x, y, 0] (degrees) that points a part's up (Z) along the unit direction D."""
    a = -math.degrees(math.asin(max(-1.0, min(1.0, D[1]))))
    b = math.degrees(math.atan2(D[0], D[2])) if abs(D[1]) < 1 - 1e-9 else 0.0
    return [round(a, 6) + 0.0, round(b, 6) + 0.0, 0.0]


def _round_pitch(d: float) -> float:
    """A round (knuckle) thread's pitch for diameter d: coarse on purpose, fine threads don't print."""
    return max(2.5, round(d / 4 * 2) / 2) if d >= 8 else max(1.0, round(d / 4 * 4) / 4)


def _reach(parts: list) -> float:
    """About how far a 'through' hole must go: the size of everything in this body, plus some."""
    lo, hi = [1e9] * 3, [-1e9] * 3
    for q in parts:
        if not isinstance(q, dict):
            continue
        own = q.get("shape") in ("rod", "curved_pipe")
        pts = ([q.get("from"), q.get("to")] + list(q.get("points") or [])) if own else [q.get("center")]
        ext = [_num(x, 0, 0, 5000) for x in (q.get("size") or [])] if isinstance(q.get("size"), list) else []
        e = max(ext + [_num(q.get(k), 0, 0, 5000) for k in ("radius", "height", "radius2")] + [1.0])
        for pt in pts:
            if isinstance(pt, (list, tuple)) and len(pt) >= 3:
                c = _v3(pt)
                lo, hi = [min(lo[i], c[i] - e) for i in range(3)], [max(hi[i], c[i] + e) for i in range(3)]
    return math.dist(lo, hi) + 20 if lo[0] < 1e9 else 400.0


def _hole_parts(h: dict, far: float) -> list[dict]:
    """A screw hole (a point on the surface + the drilling direction) -> the cuts that make it."""
    size = h.get("for") if h.get("for") in CLEARANCE else None
    fit = h.get("fit") if h.get("fit") in ("clearance", "tap", "insert", "nut", "thread") else "clearance"
    depth = _num(h.get("depth"), 0, 0, 3000)
    D = _v3(h.get("dir"), (0.0, 0.0, -1.0))
    L = math.sqrt(sum(x * x for x in D)) or 1.0
    D = [x / L for x in D]
    at, rot = _v3(h.get("at")), _aim(D)
    start = [at[i] - D[i] for i in range(3)]  # 1 mm outside the surface
    cut = lambda **k: {"op": "subtract", "rotate": rot, **k}  # noqa: E731
    if fit == "thread":  # a round printed thread (pairs with a printed bolt)
        d = float(size[1:]) if size else _num(h.get("diameter"), 8, 2, 500)
        P = _num(h.get("pitch"), _round_pitch(d), 0.5, 12)
        w, length = 0.25 * P, (depth or far) + 1
        rc, n = d / 2 - w, int(math.ceil(length / P)) + 2
        return [cut(shape="cylinder", radius=rc + PLAY, height=length, center=start),
                cut(shape="helix", radius=rc, radius2=w + PLAY, height=n * P, turns=n,
                    center=[start[i] - D[i] * P for i in range(3)])]
    if size:
        d = {"clearance": CLEARANCE, "tap": TAP, "insert": INSERT, "nut": CLEARANCE}[fit][size]
        if fit == "tap" and not depth:
            depth = round(3 * float(size[1:]), 1)  # a screw cuts ~3x its size into plastic
        if fit == "insert":
            depth = depth or INSERT_LEN[size] + 1
    else:
        d = _num(h.get("diameter"), 3, 0.3, 500)
    out = [cut(shape="cylinder", radius=d / 2, height=(depth or far) + 1, center=start)]
    if size and h.get("head") == "counterbore":
        out.append(cut(shape="cylinder", radius=CBORE[size][0] / 2, height=CBORE[size][1] + 1, center=start))
    elif size and h.get("head") == "countersink":
        cs = CSINK[size]
        out += [cut(shape="cylinder", radius=cs / 2, height=1.0, center=start),
                cut(shape="cone", radius=cs / 2, radius2=d / 2, height=(cs - d) / 2, center=at)]
    if size and fit == "nut":
        out.append(cut(shape="extrude", points=_hexagon(NUT_AF[size]), height=NUT_H[size] + 1, center=start))
    return out


def _thread_parts(q: dict) -> list[dict]:
    """A cylinder with "thread" -> its core + a round coil (added: a threaded rod; cut away: a threaded hole)."""
    r, h = _num(q.get("radius"), 10, 0.5, 1500), _num(q.get("height"), 20, 0.5, 3000)
    th = q.get("thread") if isinstance(q.get("thread"), dict) else {}
    P = _num(th.get("pitch"), _round_pitch(2 * r), 0.5, 12)
    w, c0, rot = 0.25 * P, _v3(q.get("center")), q.get("rotate") or [0, 0, 0]
    up, plain = _turn((0, 0, 1), rot), {k: v for k, v in q.items() if k != "thread"}
    if q.get("op") == "subtract":
        n, z0 = int(math.ceil(h / P)) + 2, -P
        core = {**plain, "radius": r - w + PLAY}
        coil = {"op": "subtract", "shape": "helix", "radius": r - w, "radius2": w + PLAY}
    else:
        n = max(1, int((h - P) // P))
        z0 = (h - n * P) / 2
        core = {**plain, "radius": r - w}
        coil = {"op": "add" if q.get("op") != "intersect" else "intersect", "shape": "helix", "radius": r - w, "radius2": w}
    coil.update(height=n * P, turns=n, rotate=rot, center=[c0[i] + up[i] * z0 for i in range(3)])
    if q.get("repeat"):
        coil["repeat"] = q["repeat"]
    return [core, coil]


def lower(recipe: dict) -> dict:
    """The design as the engine builds it: holes -> cuts, threaded cylinders -> core + coil. The SAVED design keeps
    them as holes / threads (Edit in 3D shows them as such)."""
    r = json.loads(json.dumps(recipe))
    for bd in r.get("bodies") or [r]:
        if not isinstance(bd, dict):
            continue
        parts = []
        for q in bd.get("parts") or []:
            parts += _thread_parts(q) if isinstance(q, dict) and q.get("thread") and q.get("shape") == "cylinder" else [q]
        hs = [h for h in (bd.pop("holes", None) or [])[:60] if isinstance(h, dict)]
        if hs:
            far = _reach(parts)
            for h in hs:
                parts += _hole_parts(h, far)
        bd["parts"] = parts
    return r


def blender_exe() -> str | None:
    win = os.name == "nt"
    bundled = ENGINES / "blender" / ("blender.exe" if win else "blender")
    if bundled.exists():
        return str(bundled)
    import glob
    import shutil
    found = sorted(glob.glob(os.path.expandvars("%ProgramFiles%/Blender Foundation/Blender */blender.exe"))) if win else []
    return found[-1] if found else shutil.which("blender")


def via_blender(recipe: dict, out: str) -> dict:
    """Linux (PicoGK has no Linux version) — or a copy without PicoGK's engine: the SAME design, translated to Blender
    Python by the app's own translator (only numbers and quoted names go in — never anyone's code; the app's code
    check runs on it too), then built by the Blender plugin's runner: parts, fit check (+ automatic fixes), STL per
    part, rendered picture, GLB. Lattices / gyroids / LEAP 71's library shapes have no Blender version: left out."""
    root = HERE.parent.parent
    sys.path.insert(0, str(root))
    from app.security import check_code
    from app.translate3d import recipe_to_code
    code, skipped = recipe_to_code(recipe)
    if "part(" not in code:
        return {"error": "this design only uses shapes that need PicoGK's engine (Windows): " + ", ".join(skipped)}
    problems = check_code(code)
    if problems:
        return {"error": "the translated design didn't pass the code check", "refused": problems}
    exe = blender_exe()
    if not exe:
        return {"error": "Blender isn't installed (on Linux it builds the 3D designs) — run install.sh again"}
    job = Path(out) / "job.json"
    job.write_text(json.dumps({"name": str(recipe.get("name") or "model")[:60], "code": code,
                               "engine_label": "PicoGK design, translated"}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}  # Blender's own Python only
    p = subprocess.Popen([exe, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1", "--python",
                          str(root / "plugins" / "blender" / "bl_code.py"), "--", str(job), out],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore",
                         env=env, cwd=out, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = []
    for x in p.stdout:
        if x.startswith("PROGRESS:"):
            print(x.rstrip(), flush=True)
        else:
            lines.append(x.rstrip())
    p.wait()
    line = next((x[7:] for x in reversed(lines) if x.startswith("RESULT:")), None)
    result = json.loads(line) if line else {"error": "Blender stopped: " + " | ".join(lines[-6:])[-400:]}
    if skipped and not result.get("error"):
        result["skipped"] = skipped
    return result


def main() -> None:
    try:
        raw = fix(json.load(open(sys.argv[1], encoding="utf-8")))
        only = isinstance(raw, dict) and raw.pop("expand_only", False)
        recipe = expand(raw)
        if only:  # Create › 3D only wants the parts (a ready-made design opened for editing): no build
            print("RESULT: " + json.dumps({"full": recipe}))
            return
        built = lower(recipe)  # holes and threads as the cuts / coils the engine knows
    except Exception as e:  # noqa: BLE001
        print("RESULT: " + json.dumps({"error": str(e)}))
        return
    # no PicoGK engine here (Linux): built in Blender instead. LOCALAI_VIA_BLENDER=1 tests that route on Windows.
    if os.name != "nt" or not RUNNER.exists() or os.environ.get("LOCALAI_VIA_BLENDER") == "1":
        result = via_blender(built, sys.argv[2])
        result["recipe"] = recipe
        notes = [recipe["notes"]] if recipe.get("notes") else []
        if result.get("skipped"):
            notes.append("Left out (these shapes need PicoGK's engine on Windows): " + ", ".join(result["skipped"]) + ".")
        if notes:
            result["notes"] = " ".join(notes)
        print("RESULT: " + json.dumps(result))
        return
    big = {"rover_wheel": 0.8, "heat_exchanger": 0.6}  # very detailed library designs: millions of triangles at fine voxels
    shapes = [q.get("shape") for bd in (built.get("bodies") or [built]) for q in bd.get("parts") or [] if isinstance(q, dict)]
    if not built.get("voxel") and any(x in big for x in shapes):
        built["voxel"] = max(big[x] for x in shapes if x in big)
    full = Path(sys.argv[2]) / "recipe.json"
    full.write_text(json.dumps(built), encoding="utf-8")
    env = {**os.environ, "DOTNET_ROOT": str(ENGINES / "dotnet"), "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1"}
    p = subprocess.Popen([str(RUNNER), str(full), sys.argv[2]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="ignore", env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = []
    for x in p.stdout:  # "PROGRESS: 2/9 left cuff jaw" goes straight on to the app (progress bar); the rest is kept
        if x.startswith("PROGRESS:"):
            print(x.rstrip(), flush=True)
        else:
            out.append(x.rstrip())
    p.wait()
    line = next((x[7:] for x in reversed(out) if x.startswith("RESULT:")), None)
    result = json.loads(line) if line else {"error": "\n".join(out)[-400:] or "the 3D engine stopped"}
    result["recipe"] = recipe
    if recipe.get("notes"):
        result["notes"] = recipe["notes"]
    print("RESULT: " + json.dumps(result))


main()
