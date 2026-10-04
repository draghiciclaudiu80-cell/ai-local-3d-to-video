"""Local AI's fixed FreeCAD script — run headless by run.py:  freecadcmd fc_runner.py  (job = $FC_JOB, output = $FC_OUT).

Builds every body from plain numbers (shapes + add / cut / intersect, fillets, shell, chamfers, holes for screws),
checks how the bodies fit (the EXACT overlap volume and the gap between parts), writes STEP + STL per body and one STEP
of the whole thing. Prints "PROGRESS: …" lines and one "RESULT: {json}" line. Nothing here comes from the AI as code:
the job file was checked and turned into numbers by run.py."""
import json
import math
import os
import re
import traceback

import FreeCAD
import Mesh
import MeshPart
import Part
from FreeCAD import Vector

AX = {"x": Vector(1, 0, 0), "y": Vector(0, 1, 0), "z": Vector(0, 0, 1),
      "+x": Vector(1, 0, 0), "+y": Vector(0, 1, 0), "+z": Vector(0, 0, 1),
      "-x": Vector(-1, 0, 0), "-y": Vector(0, -1, 0), "-z": Vector(0, 0, -1)}
T30 = math.tan(math.radians(30))
PLAY = 0.15  # mm on the radius: a printed thread needs room to turn
notes, missed = [], []


def say(s: str) -> None:
    print(s, flush=True)


def coil(points: list, pitch: float, z0: float, turns: float, r: float):
    """A closed solid: the (radius, z) outline turned like a screw (right-hand) from z0 for `turns` turns. Built from
    flat triangles: FreeCAD's own helical sweeps gave wrong results in booleans (tested M3-M20), flat faces never did."""
    seg = int(min(48, max(16, math.pi / math.acos(max(-1.0, 1 - 0.02 / max(r, 0.1))))))  # <= 0.02 mm off round
    n = int(math.ceil(turns * seg))
    rings = []
    for i in range(n + 1):
        a = 2 * math.pi * i / seg
        c, s, dz = math.cos(a), math.sin(a), z0 + pitch * i / seg
        rings.append([(rr * c, rr * s, z + dz) for rr, z in points])
    k, tris = len(points), []
    for i in range(n):
        A, B = rings[i], rings[i + 1]
        for j in range(k):
            j2 = (j + 1) % k
            tris += [(A[j], B[j], B[j2]), (A[j], B[j2], A[j2])]
    for j in range(1, k - 1):  # the two ends (a convex outline: a fan)
        tris += [(rings[0][0], rings[0][j + 1], rings[0][j]), (rings[-1][0], rings[-1][j], rings[-1][j + 1])]
    sh = Part.Shape()
    sh.makeShapeFromMesh(Mesh.Mesh(tris).Topology, 0.01)
    sol = Part.makeSolid(sh)
    if sol.Volume < 0:
        sol.reverse()
    return sol


def minor(r: float, pitch: float) -> float:
    """A thread's inside radius (ISO: 0.6134 x pitch deep)."""
    return r - 0.6134 * pitch


def thread_tool(t: dict):
    """The helical cut that makes a thread, placed in the part: "outer" = the groove of a threaded rod (r = its outside),
    "inner" = the groove of a threaded hole (r = the screw's outside + play). The part was first built plain (rod at
    full size, hole at the inside size) — the thread is cut last: one boolean (cutting it with the part was 35 s)."""
    r, P, L = t["r"], t["pitch"], t["length"]
    depth, over = 0.6134 * P, 0.3 * 0.6134 * P
    rm = r - depth
    if t["kind"] == "outer":
        root = P / 8
        w = root / 2 + (depth + over) * T30
        prof = [(rm, -root / 2), (r + over, -w), (r + over, w), (rm, root / 2)]
    else:
        crest = P / 16
        w = crest + depth * T30
        prof = [(rm - over, -w), (r, -crest), (r, crest), (rm - over, w)]
    if t["kind"] == "outer" or t.get("clip"):  # only along the part itself: both ends a little short (no neighbour cut)
        z0, turns = w + 0.05, (L - 2 * w - 0.1) / P
    else:  # a drilled hole: from past its mouth (air); a blind one stops short of its bottom
        z0 = -P
        turns = ((L - w - 0.05) - z0) / P if t["blind"] else (L + 2 * P) / P
    if turns < 0.5:
        return None
    tool = coil(prof, P, z0, turns, r)
    tool.Placement = FreeCAD.Placement(t["base"], FreeCAD.Rotation(Vector(0, 0, 1), t["dir"]))
    return tool


def cut_threads(shape, jobs: list, label: str):
    """Every thread of a body, cut last. A thread that can't be made is left plain — and said so."""
    for t in jobs:
        try:
            tool = thread_tool(t)
            if tool is None:
                notes.append(f"A thread on “{label}” was too short to make (left plain).")
                continue
            s = shape.cut(tool)
            if not s.isValid() or not s.Solids or abs(s.Volume - shape.Volume) < 1e-6:
                raise ValueError("bad thread")
            shape = s
        except Exception:  # noqa: BLE001
            notes.append(f"A Ø{2 * t['r']:.1f} mm thread on “{label}” couldn't be made (left plain).")
    return shape


def turned(p: dict, v: Vector, pivot: Vector) -> Vector:
    """Where point v of a part ends up after the part's turn (X, then Y, then Z around its centre)."""
    q = v - pivot
    for i, a in enumerate((Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1))):
        if abs(p["rotate"][i]) > 1e-9:
            q = FreeCAD.Rotation(a, p["rotate"][i]).multVec(q)
    return q + pivot


def frame(a: Vector) -> tuple[Vector, Vector]:
    """Two directions across `a`: u horizontal when possible, v = a x u."""
    u = a.cross(Vector(0, 0, 1))
    if u.Length < 1e-9:
        u = Vector(1, 0, 0)
    u.normalize()
    v = a.cross(u)
    v.normalize()
    return u, v


def make(p: dict, jobs: list | None = None):
    """A part as a solid. A threaded cylinder is made plain here and its thread goes on `jobs` (cut last)."""
    s, c = p["shape"], Vector(*p["center"])
    if s == "box":
        sx, sy, sz = p["size"]
        sh = Part.makeBox(sx, sy, sz, c - Vector(sx / 2, sy / 2, sz / 2))
        if p.get("round"):  # rounded vertical corners of this box alone (always works, unlike rounding the whole body)
            sh = sh.makeFillet(p["round"], [e for e in sh.Edges if e.BoundBox.XLength < 1e-6 and e.BoundBox.YLength < 1e-6])
    elif s in ("cylinder", "cone", "tube"):
        d, h = AX[p["axis"]], p["height"]
        base = c - d * (h / 2)
        if s == "cylinder" and p.get("thread") and p["op"] in ("add", "cut") and jobs is not None:
            pitch = p["thread"]["pitch"]
            r = p["radius"] - PLAY / 2 if p["op"] == "add" else p["radius"] + PLAY
            sh = Part.makeCylinder(r if p["op"] == "add" else minor(r, pitch), h, base, d)
            tip = turned(p, base + d, c) - turned(p, base, c)
            jobs.append({"kind": "outer" if p["op"] == "add" else "inner", "r": r, "pitch": pitch, "length": h,
                         "blind": False, "clip": True, "base": turned(p, base, c), "dir": tip})
        elif s == "cylinder":
            sh = Part.makeCylinder(p["radius"], h, base, d)
        elif s == "cone":
            sh = Part.makeCone(p["radius"], p.get("radius2", 0.0), h, base, d)
        else:
            sh = Part.makeCylinder(p["radius"], h, base, d).cut(
                Part.makeCylinder(max(0.05, p["radius"] - p["wall"]), h, base, d))
    elif s == "sphere":
        sh = Part.makeSphere(p["radius"], c)
    elif s == "slot":  # a stadium (round ends) along `direction`, going `height` deep along `axis`
        L, W, H = p["length"], p["width"], p["height"]
        r, straight = W / 2, max(0.0, p["length"] - p["width"])
        sh = Part.makeCylinder(r, H, Vector(-straight / 2, 0, -H / 2)).fuse(
            Part.makeCylinder(r, H, Vector(straight / 2, 0, -H / 2)))
        if straight > 1e-6:
            sh = sh.fuse(Part.makeBox(straight, W, H, Vector(-straight / 2, -r, -H / 2)))
        sh = sh.removeSplitter()
        x, z = AX[p["direction"]], AX[p["axis"]]
        y = z.cross(x)
        m = FreeCAD.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
        sh.transformShape(m)
        sh.translate(c)
    elif s == "polygon":  # an outline seen from above (its 0,0 goes to `center`), extruded up, centred in height
        pts = [Vector(x, y, 0) for x, y in p["points"]]
        sh = Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(Vector(0, 0, p["height"]))
        sh.translate(c - Vector(0, 0, p["height"] / 2))
    else:
        raise ValueError(f"unknown shape {s}")
    for i, a in enumerate((Vector(1, 0, 0), Vector(0, 1, 0), Vector(0, 0, 1))):  # X, then Y, then Z
        if abs(p["rotate"][i]) > 1e-9:
            sh.rotate(c, a, p["rotate"][i])
    return sh


def pick(shape, which: str) -> list:
    bb, out = shape.BoundBox, []
    for e in shape.Edges:
        eb = e.BoundBox
        top = abs(eb.ZMin - bb.ZMax) < 1e-3 and abs(eb.ZMax - bb.ZMax) < 1e-3
        bottom = abs(eb.ZMin - bb.ZMin) < 1e-3 and abs(eb.ZMax - bb.ZMin) < 1e-3
        if len(shape.ancestorsOfType(e, Part.Face)) < 2:
            continue  # a cylinder's seam line: not a real edge (rounding it fails)
        if which == "vertical":
            ok = e.Curve.TypeId == "Part::GeomLine" and eb.XLength < 1e-4 and eb.YLength < 1e-4 and eb.ZLength > 1e-4
        elif which == "top":
            ok = top
        elif which == "bottom":
            ok = bottom
        elif which == "both":
            ok = top or bottom
        else:
            ok = True
        if ok:
            out.append(e)
    return out


def edges(shape, kind: str, r: float, which: str):
    es = pick(shape, which)
    if not es:
        return shape
    for k in (1.0, 0.5, 0.25):
        try:
            s = shape.makeFillet(r * k, es) if kind == "fillet" else shape.makeChamfer(r * k, es)
            if s.isValid() and s.Volume > 0:
                if k < 1:
                    notes.append(f"The {kind} was made {r * k:g} mm (the full {r:g} mm didn't fit those edges).")
                return s
        except Exception:  # noqa: BLE001 — try smaller
            pass
    notes.append(f"The {kind} of {r:g} mm couldn't be made on the {which} edges (left sharp).")
    return shape


def shell(shape, t: float, side: str):
    bb = shape.BoundBox
    z = bb.ZMax if side == "top" else bb.ZMin
    faces = [f for f in shape.Faces if abs(f.BoundBox.ZMin - z) < 1e-3 and abs(f.BoundBox.ZMax - z) < 1e-3]
    if faces:
        try:
            s = shape.makeThickness(faces, -t, 1e-3)
            if s.isValid() and s.Volume > 0:
                return s
        except Exception:  # noqa: BLE001
            pass
    notes.append(f"It couldn't be made hollow with {t:g} mm walls (left solid) — thinner walls or smaller roundings help.")
    return shape


def through(bb, start: Vector, a: Vector) -> float:
    """How far a line from `start` along `a` runs until it leaves the box bb (a through hole's real length)."""
    t = float("inf")
    for p, d, lo, hi in ((start.x, a.x, bb.XMin, bb.XMax), (start.y, a.y, bb.YMin, bb.YMax), (start.z, a.z, bb.ZMin, bb.ZMax)):
        if abs(d) > 1e-9:
            t = min(t, ((hi if d > 0 else lo) - p) / d)
    return max(1.0, t if t < float("inf") else bb.DiagonalLength) + 0.5


def drill(shape, holes: list, jobs: list):
    """Every hole of a body (one cut). A threaded hole is drilled at the thread's inside size; its thread goes on
    `jobs` (cut last)."""
    far = shape.BoundBox.DiagonalLength * 2 + 10
    cutters, made = [], []
    for h in holes:
        a, at, r = Vector(*h["dir"]) if h.get("dir") else AX[h["axis"]], Vector(*h["at"]), h["d"] / 2
        a.normalize()
        length = h["depth"] or far
        start = at - a * 1.0  # begins 1 mm outside the surface
        thread = None
        if h.get("thread"):  # only as long as the part is thick (a thread through "everything" was 160 mm of coil)
            P, ro = h["thread"]["pitch"], r + PLAY
            thread = {"kind": "inner", "r": ro, "pitch": P, "blind": bool(h["depth"]), "base": start, "dir": a,
                      "length": (length if h["depth"] else through(shape.BoundBox, start, a)) + 1.0}
            r = minor(ro, P)
        c = Part.makeCylinder(r, length + 1.0, start, a)
        if abs(a.z) < 1e-6 and h["d"] >= 5 and not thread:  # a horizontal big hole: a 45° roof (no supports)
            u, v = a.cross(Vector(0, 0, 1)), Vector(0, 0, 1)
            u.normalize()
            k = r / math.sqrt(2)
            pts = [start - u * k + v * k, start + u * k + v * k, start + v * (r * math.sqrt(2))]
            c = c.fuse(Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(a * (length + 1.0)))
        if h.get("cbore"):
            c = c.fuse(Part.makeCylinder(h["cbore"]["d"] / 2, h["cbore"]["depth"] + 1.0, start, a))
        if h.get("csink"):
            D = h["csink"]["d"]
            c = c.fuse(Part.makeCylinder(D / 2, 1.0, start, a)).fuse(Part.makeCone(D / 2, r, (D - h["d"]) / 2, at, a))
        if h.get("nut"):
            R = h["nut"]["af"] / math.sqrt(3)  # hexagon: across flats -> corner radius
            u, v = frame(a)
            pts = [start + u * (R * math.cos(math.radians(60 * k))) + v * (R * math.sin(math.radians(60 * k))) for k in range(6)]
            c = c.fuse(Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(a * (h["nut"]["depth"] + 1.0)))
        if shape.common(c).Volume < 1e-3:
            missed.append(f"{h['label']} at {[round(x, 1) for x in h['at']]}")
            continue
        cutters.append(c)
        if thread:
            jobs.append(thread)
        made.append({"hole": h["label"], "diameter": h["d"], "at": [round(x, 2) for x in h["at"]], "axis": h["axis"]})
    if cutters:
        tool = cutters[0].multiFuse(cutters[1:]) if len(cutters) > 1 else cutters[0]
        shape = shape.cut(tool)
    return shape, made


def build(b: dict):
    shape, jobs = None, []
    for p in b["parts"]:
        s = make(p, jobs)
        if shape is None:
            shape = s
        elif p["op"] == "cut":
            shape = shape.cut(s)
        elif p["op"] == "intersect":
            shape = shape.common(s)
        else:
            shape = shape.fuse(s)
    shape = shape.removeSplitter()
    if b["fillet"] > 0:
        shape = edges(shape, "fillet", b["fillet"], b["fillet_edges"])
    if b["shell"] > 0:
        shape = shell(shape, b["shell"], b["shell_open"])
    if b["chamfer"] > 0:
        shape = edges(shape, "chamfer", b["chamfer"], b["chamfer_edges"])
    made = []
    if b["holes"]:
        shape, made = drill(shape, b["holes"], jobs)
    if jobs:
        say(f"PROGRESS: threads {len(jobs)}")
        shape = cut_threads(shape, jobs, b["name"])
    solids = shape.Solids
    if not solids:
        raise ValueError(f"“{b['name']}” came out empty (the cuts removed everything?)")
    if len(solids) > 1:
        notes.append(f"“{b['name']}” is {len(solids)} separate pieces — parts meant to be one must overlap or touch.")
    return shape, made


def main() -> None:
    job = json.load(open(os.environ["FC_JOB"], encoding="utf-8"))
    out = os.environ["FC_OUT"]
    shapes, bodies = [], []
    n = len(job["bodies"])
    for i, b in enumerate(job["bodies"], 1):
        say(f"PROGRESS: {i}/{n} {b['name']}")
        shape, made = build(b)
        safe = re.sub(r"[^\w ()+-]", "", b["name"]).strip().replace(" ", "_") or f"part{i}"
        step, stl = os.path.join(out, f"{i:02d}_{safe}.step"), os.path.join(out, f"{i:02d}_{safe}.stl")
        shape.exportStep(step)
        mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=0.03, AngularDeflection=0.26, Relative=False)
        mesh.write(stl)
        bb = shape.BoundBox
        shapes.append(shape)
        bodies.append({"name": b["name"], "stl": stl, "step": step, "color": b["color"], "reference": b["reference"],
                       "size_mm": [round(bb.XLength, 2), round(bb.YLength, 2), round(bb.ZLength, 2)],
                       "volume_mm3": round(shape.Volume, 1), "triangles": mesh.CountFacets, "holes": made})
    say(f"PROGRESS: fit {n}")
    clashes, gaps = [], []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = shapes[i], shapes[j]
            ba, bb = a.BoundBox, b.BoundBox
            if ba.XMin > bb.XMax + 2 or bb.XMin > ba.XMax + 2 or ba.YMin > bb.YMax + 2 or bb.YMin > ba.YMax + 2 or \
                    ba.ZMin > bb.ZMax + 2 or bb.ZMin > ba.ZMax + 2:
                continue  # far apart
            v = a.common(b).Volume
            if v > 1e-3:
                clashes.append({"a": bodies[i]["name"], "b": bodies[j]["name"], "volume_mm3": round(v, 3)})
            else:
                d = a.distToShape(b)[0]
                if d < 2:
                    gaps.append({"a": bodies[i]["name"], "b": bodies[j]["name"], "mm": round(d, 3)})
    whole = os.path.join(out, "model.step")
    Part.makeCompound(shapes).exportStep(whole)
    if missed:
        notes.append("These holes didn't touch the part (check where they are): " + "; ".join(missed[:8]) + ".")
    ver = ".".join(FreeCAD.Version()[:3])
    result = {"name": job["name"], "bodies": bodies, "collisions": clashes, "gaps": gaps,
              "checked_pairs": n * (n - 1) // 2, "step": whole, "engine": f"FreeCAD {ver}", "notes_list": notes,
              "missed_holes": missed}
    if n == 1:  # one part: the app takes it as a single model (like Blender's single piece)
        result.update({"stl": bodies[0]["stl"], "size_mm": bodies[0]["size_mm"], "triangles": bodies[0]["triangles"],
                       "holes": bodies[0]["holes"]})
    say("RESULT: " + json.dumps(result))


try:
    main()
except Exception as e:  # noqa: BLE001 — the reason goes back to the app (and to the AI's fix loop)
    say("RESULT: " + json.dumps({"error": f"{type(e).__name__}: {e}"[:300], "trace": traceback.format_exc()[-600:]}))
