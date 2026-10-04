"""Local AI's FreeCAD plugin (run by the app: run.py <recipe.json> <output folder>) — precise CAD for mechanical parts:
exact holes for metal screws (sizes from a table that prints well), slots, fillets, chamfers, hollow boxes, an exact
fit check, STEP files (CNC / other CAD) + STL (the printer).

Security: the AI never sends code. Its recipe is DATA — every field is checked here (shapes and hole types from fixed
lists, numbers clamped, names cleaned) and the result is handed, as plain numbers, to the app's own fixed FreeCAD script
(fc_runner.py). FreeCAD runs headless (freecadcmd); its user settings, macros and add-ons point at an empty folder of
this run (nothing of the user's FreeCAD is loaded or changed); it writes only into the output folder.
Prints "PROGRESS: …" lines and one "RESULT: {json}" line."""
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from templates import TEMPLATES  # noqa: E402 — the ready-made, tested designs
ENGINES = HERE.parent.parent / "engines"
WIN = os.name == "nt"
SHAPES = {"box", "cylinder", "tube", "cone", "sphere", "slot", "polygon"}
AXES = {"x", "y", "z"}
DRILL = {"-z", "+z", "-x", "+x", "-y", "+y"}
# Hole sizes that work in FDM prints (the same numbers as skills/threads-fasteners): diameter in mm
CLEARANCE = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 8.6, "M10": 10.6}
TAP = {"M2": 1.7, "M2.5": 2.2, "M3": 2.6, "M4": 3.5, "M5": 4.3, "M6": 5.1, "M8": 6.9, "M10": 8.7}
INSERT = {"M2": 3.2, "M2.5": 3.6, "M3": 4.1, "M4": 5.6, "M5": 6.4, "M6": 8.0, "M8": 10.0, "M10": 12.0}  # heat-set
INSERT_LEN = {"M2": 4.0, "M2.5": 5.0, "M3": 5.7, "M4": 8.1, "M5": 9.5, "M6": 12.7, "M8": 12.7, "M10": 15.0}
NUT_AF = {"M2": 4.3, "M2.5": 5.3, "M3": 5.8, "M4": 7.3, "M5": 8.3, "M6": 10.3, "M8": 13.3, "M10": 16.3}  # +0.3
NUT_H = {"M2": 1.9, "M2.5": 2.3, "M3": 2.7, "M4": 3.5, "M5": 4.3, "M6": 5.5, "M8": 6.8, "M10": 8.7}  # +0.3
CBORE = {"M2": (4.4, 2.2), "M2.5": (5.0, 2.7), "M3": (6.5, 3.2), "M4": (8.0, 4.2), "M5": (9.5, 5.2), "M6": (11.0, 6.2),
         "M8": (14.0, 8.2), "M10": (17.5, 10.2)}  # socket head: (diameter, depth)
CSINK = {"M2": 4.4, "M2.5": 5.4, "M3": 7.1, "M4": 9.4, "M5": 11.6, "M6": 13.8, "M8": 18.3, "M10": 22.4}  # 90°, head + 0.4
FITS = ("clearance", "tap", "insert", "nut", "thread")  # thread = a modelled (printed) ISO thread
PITCH = {"M2": 0.4, "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75,
         "M16": 2.0, "M20": 2.5, "M24": 3.0, "M30": 3.5}  # ISO coarse


def iso_pitch(d: float) -> float:
    """The coarse pitch of the metric size nearest to diameter d."""
    return PITCH[min(PITCH, key=lambda k: abs(float(k[1:]) - d))]


def freecad_cmd() -> list[str] | None:
    """The headless FreeCAD (freecadcmd): the app's own copy, then one installed on this PC."""
    own = ENGINES / "freecad" / "bin" / ("freecadcmd.exe" if WIN else "freecadcmd")
    if own.exists():
        return [str(own)]
    if not WIN and (ENGINES / "freecad" / "AppRun").exists():  # Linux: FreeCAD's AppImage unpacked by install.sh
        return [str(ENGINES / "freecad" / "AppRun"), "freecadcmd"]
    if WIN:
        found = []
        for pat in ("%LOCALAPPDATA%/Programs/FreeCAD */bin/freecadcmd.exe", "%ProgramFiles%/FreeCAD */bin/freecadcmd.exe"):
            found += glob.glob(os.path.expandvars(pat))
        key = lambda p: [int(x) for x in re.findall(r"\d+", Path(p).parent.parent.name)] or [0]  # noqa: E731 — newest first
        return [sorted(found, key=key)[-1]] if found else None
    hit = shutil.which("freecadcmd") or shutil.which("FreeCADCmd")
    return [hit] if hit else None


def num(v, d: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = d
    return min(max(x, lo), hi) if x == x else d


def vec(v, d=(0.0, 0.0, 0.0), lo=-5000.0, hi=5000.0) -> list[float]:
    if isinstance(v, str):
        v = [x for x in re.split(r"[,;\s\[\]]+", v) if x]
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return list(d)
    return [num(v[i], d[i], lo, hi) for i in range(3)]


def name(v, d: str) -> str:
    return re.sub(r"[^\w .\-()+]", "", str(v or d))[:50].strip() or d


def part(p: dict) -> dict | None:
    if not isinstance(p, dict) or str(p.get("shape") or "").lower() not in SHAPES:
        return None
    s = str(p["shape"]).lower()
    q = {"shape": s, "op": p.get("op") if p.get("op") in ("add", "cut", "intersect") else "add",
         "center": vec(p.get("center") or p.get("location")), "rotate": vec(p.get("rotate"), lo=-360, hi=360)}
    if s == "box":
        q["size"] = vec(p.get("size"), (20, 20, 20), 0.05, 3000)
        r = num(p.get("round"), 0, 0, min(q["size"][:2]) / 2 - 0.05)  # rounded vertical corners of this box
        if r > 0.05:
            q["round"] = r
    elif s in ("cylinder", "cone", "tube"):
        q["radius"] = num(p.get("radius"), 10, 0.05, 1500)
        q["height"] = num(p.get("height") or p.get("depth"), 10, 0.05, 3000)
        q["axis"] = p.get("axis") if p.get("axis") in AXES else "z"
        th = p.get("thread")
        if s == "cylinder" and th and q["radius"] >= 0.75:  # threaded outside (added) / inside (cut away): Create › 3D
            q["thread"] = {"pitch": num(th.get("pitch") if isinstance(th, dict) else None, iso_pitch(2 * q["radius"]),
                                        0.25, min(10.0, q["radius"]))}
        if s == "cone":
            q["radius2"] = num(p.get("radius2"), 0.0, 0.0, 1500)
        if s == "tube":
            q["wall"] = num(p.get("wall"), 2, 0.1, q["radius"] - 0.05) if q["radius"] > 0.2 else 0.1
    elif s == "sphere":
        q["radius"] = num(p.get("radius"), 10, 0.05, 1500)
    elif s == "slot":
        q["width"] = num(p.get("width"), 4, 0.2, 500)
        q["length"] = num(p.get("length"), 20, q["width"], 3000)
        q["height"] = num(p.get("height") or p.get("depth"), 5, 0.05, 3000)
        q["axis"] = p.get("axis") if p.get("axis") in AXES else "z"
        q["direction"] = p.get("direction") if p.get("direction") in AXES and p.get("direction") != q["axis"] else \
            ("x" if q["axis"] != "x" else "y")
    elif s == "polygon":
        pts = [[num(a, 0, -3000, 3000), num(b, 0, -3000, 3000)] for a, b, *_ in
               (x for x in (p.get("points") or [])[:60] if isinstance(x, (list, tuple)) and len(x) >= 2)]
        if len(pts) < 3:
            return None
        q["points"], q["height"] = pts, num(p.get("height"), 5, 0.05, 3000)
    return q


AXV = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
FACES = {"top", "bottom", "front", "back", "left", "right"}


def _turn(v, deg):
    """v turned like the parts: X first, then Y, then Z (degrees)."""
    x, y, z = v
    a, b, c = (math.radians(d) for d in (list(deg) + [0, 0, 0])[:3])
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    return (x, y, z)


def _across(D):
    """Two directions across D (u level when it can be) — like the FreeCAD script's frame()."""
    L = math.hypot(D[0], D[1])
    u = (D[1] / L, -D[0] / L, 0.0) if L > 1e-9 else (1.0, 0.0, 0.0)
    return u, (D[1] * u[2] - D[2] * u[1], D[2] * u[0] - D[0] * u[2], D[0] * u[1] - D[1] * u[0])


def _label(v) -> str:
    """A drilling direction as -z / +x … when it is one (else "angled")."""
    for name, a in AXV.items():
        for sign in (1, -1):
            if all(abs(v[i] - sign * a[i]) < 1e-6 for i in range(3)):
                return ("+" if sign > 0 else "-") + name
    return "angled"


def _face(p: dict, face: str):
    """-> (the face's centre, its in-plane directions u, v, the drilling direction INTO the part) for a box or the end
    faces of a cylinder / tube / cone — in world coordinates (the part's rotation included)."""
    c = p["center"]
    if p["shape"] == "box":
        sx, sy, sz = p["size"]
        local = {"top": ((0, 0, sz / 2), (1, 0, 0), (0, 1, 0), (0, 0, -1)),
                 "bottom": ((0, 0, -sz / 2), (1, 0, 0), (0, 1, 0), (0, 0, 1)),
                 "front": ((0, -sy / 2, 0), (1, 0, 0), (0, 0, 1), (0, 1, 0)),
                 "back": ((0, sy / 2, 0), (1, 0, 0), (0, 0, 1), (0, -1, 0)),
                 "left": ((-sx / 2, 0, 0), (0, 1, 0), (0, 0, 1), (1, 0, 0)),
                 "right": ((sx / 2, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 0))}[face]
    elif p["shape"] in ("cylinder", "tube", "cone") and face in ("top", "bottom"):
        a = AXV[p.get("axis", "z")]
        others = [AXV[k] for k in "xyz" if k != p.get("axis", "z")]
        s = 1 if face == "top" else -1
        local = (tuple(s * a[i] * p["height"] / 2 for i in range(3)), others[0], others[1], tuple(-s * a[i] for i in range(3)))
    else:
        return None
    off, u, v, d = (_turn(x, p["rotate"]) for x in local)
    return [c[i] + off[i] for i in range(3)], u, v, d


def holes(raw: list, parts: list[dict]) -> tuple[list[dict], list[str], list[dict]]:
    """-> (holes as plain numbers for the FreeCAD script, notes, the same holes one by one for Create › 3D). Each hole:
    "at" + "axis" (a point on the surface + the drilling direction), "at" + "dir" (any direction: the editor clicks it
    on any surface), or "face" (+ "part", the part's number, and "pos" [u, v] from the face's centre) — the app then
    works out the point and the direction (the AI used to put holes in the air). A pattern = one hole per position."""
    out, notes, edit = [], [], []
    for h in (raw or [])[:60]:
        if not isinstance(h, dict):
            continue
        size, fit = h.get("for") if h.get("for") in CLEARANCE else None, h.get("fit") if h.get("fit") in FITS else "clearance"
        depth = num(h.get("depth"), 0, 0, 3000)  # 0 = through
        q = {"depth": depth, "label": ""}
        head = h.get("head") if size and h.get("head") in ("counterbore", "countersink") else None
        spec = {"fit": fit, "depth": depth, **({"for": size} if size else {}), **({"head": head} if head else {})}
        if size and fit == "thread":  # a modelled ISO thread (prints well from about M6)
            q["d"] = float(size[1:])
            q["thread"] = {"pitch": num(h.get("pitch"), PITCH[size], 0.25, 10)}
            q["label"] = f"{size} thread"
        elif size:
            q["d"] = {"clearance": CLEARANCE, "tap": TAP, "insert": INSERT, "nut": CLEARANCE}[fit][size]
            q["label"] = f"{size} {fit}"
            if fit == "tap" and not depth:
                q["depth"] = round(3 * float(size[1:]), 1)  # a screw cuts ~3x its size into plastic
            if fit == "insert":
                q["depth"] = depth or INSERT_LEN[size] + 1
            if fit == "nut":
                q["nut"] = {"af": NUT_AF[size], "depth": NUT_H[size]}
        else:
            q["d"] = num(h.get("diameter"), 3, 0.3, 500)
            q["label"] = f"Ø{q['d']:g}"
            spec["diameter"] = q["d"]
            if fit == "thread":
                q["thread"] = {"pitch": num(h.get("pitch"), iso_pitch(q["d"]), 0.25, 10)}
                q["label"] += " thread"
        if q.get("thread"):
            spec["pitch"] = q["thread"]["pitch"]
        if head == "counterbore":
            q["cbore"] = {"d": CBORE[size][0], "depth": CBORE[size][1]}
            q["label"] += " + counterbore"
        elif head == "countersink":
            q["csink"] = {"d": CSINK[size]}
            q["label"] += " + countersink"
        face = h.get("face") if h.get("face") in FACES else None
        k = int(num(h.get("part"), 1, 1, max(1, len(parts)))) - 1
        placed = _face(parts[k], face) if face and parts else None
        dv = vec(h.get("dir"), (0.0, 0.0, 0.0), -1000, 1000) if h.get("dir") is not None else (0.0, 0.0, 0.0)
        dl = math.sqrt(sum(x * x for x in dv))
        if placed:
            base, U, V, D = placed
            pos = h.get("pos") if isinstance(h.get("pos"), (list, tuple)) and len(h.get("pos")) >= 2 else [0, 0]
            du0, dv0 = num(pos[0], 0, -3000, 3000), num(pos[1], 0, -3000, 3000)
            base = [base[i] + U[i] * du0 + V[i] * dv0 for i in range(3)]
        elif dl > 1e-9:  # any direction (clicked on a surface in Create › 3D)
            base, D = vec(h.get("at")), tuple(x / dl for x in dv)
            U, V = _across(D)
        else:
            if face:
                notes.append(f"A hole on the {face} face of part {k + 1} was placed by its 'at' point (that part has no such face).")
            axis = h.get("axis") if h.get("axis") in DRILL else "-z"
            base, D = vec(h.get("at")), tuple(float(x) * (1 if axis[0] == "+" else -1) for x in AXV[axis[1]])
            U, V = {"z": (AXV["x"], AXV["y"]), "x": (AXV["y"], AXV["z"]), "y": (AXV["x"], AXV["z"])}[axis[1]]
        pat = h.get("pattern") if isinstance(h.get("pattern"), dict) else {}
        offsets = [(0.0, 0.0)]
        if pat.get("circle"):
            m, r = int(num(pat["circle"], 4, 2, 36)), num(pat.get("radius"), 20, 0.5, 2000)
            offsets = [(r * math.cos(2 * math.pi * i / m), r * math.sin(2 * math.pi * i / m)) for i in range(m)]
        elif pat.get("grid"):
            g = pat.get("grid") if isinstance(pat.get("grid"), (list, tuple)) and len(pat["grid"]) >= 2 else [1, 1]
            nx, ny = int(num(g[0], 1, 1, 20)), int(num(g[1], 1, 1, 20))
            st = pat.get("step") if isinstance(pat.get("step"), (list, tuple)) and len(pat["step"]) >= 2 else [10, 10]
            dx, dy = num(st[0], 10, -2000, 2000), num(st[1], 10, -2000, 2000)
            offsets = [(dx * i, dy * j) for i in range(nx) for j in range(ny)]
        seen = set()
        for du, dv in offsets[:200]:
            p = [round(base[i] + U[i] * du + V[i] * dv, 4) for i in range(3)]
            if tuple(p) in seen:  # a "pattern" with step 0 put holes on top of each other
                continue
            seen.add(tuple(p))
            out.append({**q, "at": p, "dir": [round(x, 6) for x in D], "axis": _label(D)})
            edit.append({**spec, "at": p, "dir": [round(x, 6) for x in D]})
    if len(out) >= 200:
        notes.append("Only the first 200 holes were made.")
    return out, notes, edit


def clean(r: dict) -> tuple[dict, list[str], dict]:
    """-> (the job for the FreeCAD script, notes, the same design as Create › 3D edits it: every part and every hole
    one by one, holes as a point + a direction)."""
    bodies_in = r.get("bodies") if isinstance(r.get("bodies"), list) else [{"name": r.get("name"), "parts": r.get("parts"),
                                                                             "holes": r.get("holes")}]
    bodies, notes, edit = [], [], []
    for i, b in enumerate(bodies_in[:12]):
        if not isinstance(b, dict):
            continue
        parts = [q for q in (part(p) for p in (b.get("parts") or [])[:40]) if q]
        if not parts:
            continue
        if parts[0]["op"] != "add":
            parts[0]["op"] = "add"
        hs, hn, he = holes(b.get("holes"), parts)
        notes += hn
        col = str(b.get("color") or "")
        bodies.append({"name": name(b.get("name"), f"part {i + 1}"), "parts": parts, "holes": hs,
                       "color": col if re.fullmatch(r"#[0-9a-fA-F]{6}", col) else "",
                       "reference": bool(b.get("reference")),
                       "fillet": num(b.get("fillet"), 0, 0, 100), "fillet_edges": b.get("fillet_edges") if b.get("fillet_edges") in ("vertical", "top", "all") else "vertical",
                       "chamfer": num(b.get("chamfer"), 0, 0, 30), "chamfer_edges": b.get("chamfer_edges") if b.get("chamfer_edges") in ("bottom", "top", "both") else "bottom",
                       "shell": num(b.get("shell"), 0, 0, 100), "shell_open": "bottom" if b.get("shell_open") == "bottom" else "top"})
        edit.append({**{k: v for k, v in bodies[-1].items() if k != "holes"}, "holes": he})
    if not bodies:
        raise ValueError("the design has no parts")
    nm = name(r.get("name"), "FreeCAD part")
    return {"name": nm, "bodies": bodies}, notes, {"name": nm, "engine": "freecad", "bodies": edit}


def main() -> None:
    out = Path(sys.argv[2])
    try:
        r = json.load(open(sys.argv[1], encoding="utf-8"))
        if isinstance(r, str):
            r = json.loads(r)
        tname = str(r.get("template") or "").strip().lower().replace(" ", "_").replace("-", "_")
        if tname in TEMPLATES:  # a ready-made design: the template + the options (an edit changes an option)
            opts = r.get("options") if isinstance(r.get("options"), dict) else {}
            full = TEMPLATES[tname](opts)
            if r.get("name") and str(r["name"]).strip().lower().replace(" ", "_") not in TEMPLATES:  # not "l_bracket"
                full["name"] = r["name"]
            saved, tnotes = {"name": full["name"], "template": tname, "options": opts}, [full.get("notes", "")]
        else:  # the AI's own parts (its free-text notes were unreliable: only the engine's notes are shown)
            full, saved, tnotes = r, {k: v for k, v in r.items() if k not in ("notes", "expand_only")}, []
        job, notes, editable = clean(full)
        if r.get("expand_only"):  # Create › 3D only wants the parts (a ready-made design opened for editing): no build
            print("RESULT: " + json.dumps({"full": editable}))
            return
        cmd = freecad_cmd()
        if not cmd:
            raise ValueError("FreeCAD isn't installed (freecad.org) — or switch this plugin off")
    except Exception as e:  # noqa: BLE001
        print("RESULT: " + json.dumps({"error": str(e)[:300]}))
        return
    home = out / "fc-home"  # FreeCAD's settings / macros / add-ons for this run: an empty folder
    home.mkdir(parents=True, exist_ok=True)
    jf = out / "job.json"
    jf.write_text(json.dumps(job), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}  # FreeCAD's own Python only
    env.update(FC_JOB=str(jf), FC_OUT=str(out), FREECAD_USER_HOME=str(home), FREECAD_USER_DATA=str(home / "data"),
               FREECAD_USER_TEMP=str(home / "tmp"))
    p = subprocess.Popen([*cmd, str(HERE / "fc_runner.py")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding="utf-8", errors="ignore", env=env, cwd=str(out),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = []
    for x in p.stdout:
        if x.startswith("PROGRESS:"):
            print(x.rstrip(), flush=True)
        else:
            lines.append(x.rstrip())
    p.wait()
    line = next((x[7:] for x in reversed(lines) if x.startswith("RESULT:")), None)
    result = json.loads(line) if line else {"error": "FreeCAD stopped: " + " | ".join(x for x in lines[-8:] if x)[-400:]}
    result["recipe"] = {**saved, "engine": "freecad"}
    result["full"] = editable  # what "Edit in 3D" opens: every part and hole one by one
    shown = [x for x in tnotes if x] + notes + (result.pop("notes_list", None) or [])
    if shown:
        result["notes"] = " ".join(shown)
    print("RESULT: " + json.dumps(result))


main()
