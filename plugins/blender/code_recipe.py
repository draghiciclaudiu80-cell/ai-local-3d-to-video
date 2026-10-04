"""Blender Python (the AI's 3D code) -> an editable design: python code_recipe.py <in.json> <out.json>
The code is run with RECORDING versions of bl_code.py's building blocks — no Blender: every box / cylinder / cut / join
/ move / rotate is written down as the shapes Create › 3D edits (PicoGK's: center = a cylinder's base, turns X then Y
then Z), so "Edit in 3D" works on Python-code designs too. Runs only code that passes the app's code check, with no
imports but math / random. Shapes it can't write down (lid, handle) -> an error: that design stays code-only."""
import copy as _copy
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from app.mirror3d import mat_deg, mirrored, rot_mat  # noqa: E402
from app.security import check_code  # noqa: E402


class Unsupported(Exception):
    pass


def _mv(M, v):
    return [M[i][0] * v[0] + M[i][1] * v[1] + M[i][2] * v[2] for i in range(3)]


def _t(M):
    return [[M[j][i] for j in range(3)] for i in range(3)]


def _v3(v, d=(0.0, 0.0, 0.0)):
    v = list(v) if isinstance(v, (list, tuple)) else list(d)
    return [float(x) for x in (v + list(d))[:3]]


OBJS = []


class Ob:
    """One Blender object: its shapes in WORLD coordinates + the origin / turn Blender keeps (move, rotate)."""

    def __init__(self, parts, loc, rot, name):
        self.parts, self.loc, self.rot, self.name = parts, _v3(loc), _v3(rot), str(name)
        self.group, self.ref, self.used = None, False, False
        OBJS.append(self)

    def transform(self, M, about):  # every shape turned by M around `about`
        out = []
        for p in self.parts:
            q = dict(p)
            pt = lambda v: [about[i] + _mv(M, [v[j] - about[j] for j in range(3)])[i] for i in range(3)]  # noqa: E731
            if q["shape"] == "rod":
                q["from"], q["to"] = pt(q["from"]), pt(q["to"])
            else:
                q["center"] = pt(q["center"])
                q["rotate"] = mat_deg([[sum(M[i][t] * rot_mat(q.get("rotate"))[t][j] for t in range(3)) for j in range(3)]
                                       for i in range(3)])
            out.append(q)
        self.parts = out

    def shift(self, d):
        for q in self.parts:
            if q["shape"] == "rod":
                q["from"], q["to"] = [a + b for a, b in zip(q["from"], d)], [a + b for a, b in zip(q["to"], d)]
            else:
                q["center"] = [a + b for a, b in zip(q["center"], d)]


def _base(loc, rot, h):  # Blender centres on loc; PicoGK's cylinders / cones / extrusions start at their base
    R = rot_mat(rot)
    return [loc[i] - _mv(R, [0, 0, h / 2])[i] for i in range(3)]


def _prim(shape, loc, rot, name, h=None, **k):
    loc, rot = _v3(loc), _v3(rot)
    c = _base(loc, rot, h) if h is not None else loc
    p = {"op": "add", "shape": shape, "center": c, "rotate": rot, **k}
    if h is not None:
        p["height"] = float(h)
    return Ob([p], loc, rot, name)


def box(size, *more, loc=(0, 0, 0), rot=(0, 0, 0), name="box", bevel=0):
    if isinstance(size, (int, float)):
        size, more = ((size, *more[:2]) if len(more) >= 2 else (size, size, size)), more[2:]
    if more:
        loc, rot = more[0], (more[1] if len(more) > 1 else rot)
    ob = _prim("box", loc, rot, name, size=[float(x) for x in size])
    if bevel:
        ob.parts[0]["round"] = float(bevel)
    return ob


def cylinder(radius, depth, loc=(0, 0, 0), rot=(0, 0, 0), name="cylinder", segments=64, bevel=0):
    return _prim("cylinder", loc, rot, name, depth, radius=float(radius))


def cone(radius1, radius2, depth, loc=(0, 0, 0), rot=(0, 0, 0), name="cone", segments=64):
    return _prim("cone", loc, rot, name, depth, radius=float(radius1), radius2=max(float(radius2), 0.05))


def sphere(radius, loc=(0, 0, 0), name="sphere", segments=48):
    return _prim("sphere", loc, (0, 0, 0), name, radius=float(radius))


def torus(major, minor, loc=(0, 0, 0), rot=(0, 0, 0), name="torus", segments=64):
    return _prim("torus", loc, rot, name, radius=float(major), radius2=float(minor))


def tube(radius, wall, depth, loc=(0, 0, 0), rot=(0, 0, 0), name="tube", segments=64):
    return _prim("tube", loc, rot, name, depth, radius=float(radius), wall=float(wall))


def extrude(points, height, loc=(0, 0, 0), rot=(0, 0, 0), name="extrude"):
    return _prim("extrude", loc, rot, name, height, points=[[float(x), float(y)] for x, y, *_ in points])


def revolve(points, loc=(0, 0, 0), rot=(0, 0, 0), name="revolve", segments=64):
    return _prim("revolve", loc, rot, name, points=[[float(r), float(z)] for r, z, *_ in points])


def gear(teeth, module, height, bore=0, loc=(0, 0, 0), rot=(0, 0, 0), backlash=0.15, name="gear"):
    return _prim("gear", loc, rot, name, height, teeth=int(teeth), module=float(module), bore=float(bore))


def helix(radius, wire, height, turns, loc=(0, 0, 0), rot=(0, 0, 0), name="helix"):
    return _prim("helix", loc, rot, name, height, radius=float(radius), radius2=float(wire), turns=float(turns))


def rod(start, end, radius, round_ends=False, name="rod"):
    p = {"op": "add", "shape": "rod", "from": _v3(start), "to": _v3(end), "radius": float(radius)}
    if not round_ends:
        p["flat"] = True
    return Ob([p], _v3(start), (0, 0, 0), name)


def _merge(target, others, op):
    for o in others:
        if not isinstance(o, Ob) or o is target:
            continue
        if op == "add":  # a joined piece with its own holes goes FIRST, so its cuts can't eat the target
            mine = [dict(q) for q in o.parts]
            target.parts = (mine + target.parts) if any(q.get("op") == "subtract" for q in mine) else (target.parts + mine)
        else:
            target.parts += [{**q, "op": op} for q in o.parts if q.get("op", "add") == "add"]  # its own holes: left out
        o.used = True
    return target


def _box_of(p):  # a shape's world box: its own box's 8 corners turned and moved
    s, sh = p["shape"], p.get("shape")
    if s == "rod":
        r = p["radius"]
        return [min(a, b) - r for a, b in zip(p["from"], p["to"])], [max(a, b) + r for a, b in zip(p["from"], p["to"])]
    h, r = p.get("height", 0), p.get("radius", 0)
    if s == "box":
        lo, hi = [-x / 2 for x in p["size"]], [x / 2 for x in p["size"]]
    elif s == "sphere":
        lo, hi = [-r] * 3, [r] * 3
    elif s == "torus":
        R = r + p.get("radius2", 0)
        lo, hi = [-R, -R, -p.get("radius2", 0)], [R, R, p.get("radius2", 0)]
    elif s in ("extrude",):
        xs, ys = [q[0] for q in p["points"]], [q[1] for q in p["points"]]
        lo, hi = [min(xs), min(ys), 0], [max(xs), max(ys), h]
    elif s == "revolve":
        R, zs = max(q[0] for q in p["points"]), [q[1] for q in p["points"]]
        lo, hi = [-R, -R, min(zs)], [R, R, max(zs)]
    else:  # cylinder, tube, cone, gear, helix: round, from the base up
        R = max(r, p.get("radius2", 0) if sh == "cone" else 0, p.get("module", 0) * (p.get("teeth", 0) / 2 + 1))
        R += p.get("radius2", 0) if sh == "helix" else 0
        lo, hi = [-R, -R, 0], [R, R, h]
    M, c = rot_mat(p.get("rotate")), p["center"]
    pts = [[c[i] + _mv(M, [x, y, z])[i] for i in range(3)] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    return [min(q[i] for q in pts) for i in range(3)], [max(q[i] for q in pts) for i in range(3)]


def _outline(ob):
    """Like bl_code's: (centre, size x, size y, top z, round?) from the shapes it adds."""
    boxes = [_box_of(q) for q in ob.parts if q.get("op", "add") == "add"]
    lo = [min(b[0][i] for b in boxes) for i in range(3)]
    hi = [max(b[1][i] for b in boxes) for i in range(3)]
    first = next(q for q in ob.parts if q.get("op", "add") == "add")
    rnd = first["shape"] in ("cylinder", "tube", "cone", "sphere", "revolve") and abs(hi[0] - lo[0] - (hi[1] - lo[1])) < 0.03 * max(hi[0] - lo[0], 1e-6)
    return [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2], hi[0] - lo[0], hi[1] - lo[1], hi[2], rnd, lo, hi


def join(target, *others):
    return _merge(target, others, "add")


def cut(target, *cutters):
    return _merge(target, cutters, "subtract")


def intersect(target, *others):
    return _merge(target, others, "intersect")


def move(ob, x=0, y=0, z=0):
    ob.shift([float(x), float(y), float(z)])
    ob.loc = [a + b for a, b in zip(ob.loc, (float(x), float(y), float(z)))]
    return ob


def rotate(ob, x=0, y=0, z=0):  # like Blender: the Euler angles add up, around the object's origin
    old = rot_mat(ob.rot)
    ob.rot = [ob.rot[0] + float(x), ob.rot[1] + float(y), ob.rot[2] + float(z)]
    new = rot_mat(ob.rot)
    ob.transform([[sum(new[i][t] * _t(old)[t][j] for t in range(3)) for j in range(3)] for i in range(3)], ob.loc)
    return ob


def copy(ob, name=None):
    c = Ob(_copy.deepcopy(ob.parts), ob.loc, ob.rot, name or ob.name)
    c.group, c.ref = ob.group, ob.ref
    return c


def array(ob, count, offset):  # Blender's array offset is in the object's own frame
    d = _mv(rot_mat(ob.rot), _v3(offset))
    base = _copy.deepcopy(ob.parts)
    for k in range(1, int(count)):
        tmp = Ob(_copy.deepcopy(base), ob.loc, ob.rot, "tmp")
        tmp.shift([x * k for x in d])
        ob.parts += tmp.parts
        OBJS.remove(tmp)
    return ob


def mirror(ob, axis="x"):  # ob + its mirror image across the world's centre plane
    k = "xyz".index(str(axis).lower()[:1]) if str(axis).lower()[:1] in "xyz" else 0
    ob.parts += [mirrored(p, "part", k, [0, 0, 0], False) for p in _copy.deepcopy(ob.parts)]
    return ob


def bevel(ob, width, segments=3):  # rounded edges: only a plain box keeps them
    if len(ob.parts) == 1 and ob.parts[0]["shape"] == "box":
        ob.parts[0]["round"] = float(width)
    return ob


_bevel = bevel


def smooth(ob):
    return ob


def color(ob, hexcolor, metal=0.0):
    return ob


def part(ob, name=None, group=None, reference=False):
    if name:
        ob.name = str(name)
    ob.group, ob.ref = str(group or name or ob.name), bool(reference)
    return ob


def hollow(ob, wall=2, open="top"):
    """A container: the same shape inside, `wall` smaller, cut out (open at the top / bottom). Plain boxes and
    cylinders only — anything else can't be written down."""
    if len(ob.parts) != 1 or ob.parts[0]["shape"] not in ("box", "cylinder") or any(abs(a) > 1e-6 for a in ob.parts[0].get("rotate") or []):
        raise Unsupported("hollow() on a shape that isn't a plain box or cylinder")
    p, w = ob.parts[0], float(wall)
    top = {"top": 1, "bottom": -1}.get(open, 0)  # 1 = open at the top, -1 = at the bottom, 0 = closed
    if p["shape"] == "box":
        (sx, sy, sz), (cx, cy, cz) = p["size"], p["center"]
        h = sz - 2 * w if not top else sz - w + 1
        inner = {"op": "subtract", "shape": "box", "size": [sx - 2 * w, sy - 2 * w, h], "rotate": [0, 0, 0],
                 "center": [cx, cy, cz + top * (w + 1) / 2]}
    else:  # a PicoGK cylinder starts at its base
        (cx, cy, cz), h = p["center"], p["height"]
        z0, hh = (cz + w, h - 2 * w) if not top else ((cz + w, h - w + 1) if top > 0 else (cz - 1, h - w + 1))
        inner = {"op": "subtract", "shape": "cylinder", "radius": max(p["radius"] - w, 0.1), "height": hh,
                 "center": [cx, cy, z0], "rotate": [0, 0, 0]}
    ob.parts.append(inner)
    return ob


def lid(ob, wall=2, thickness=3, gap=0.4, lip=6, knob=True, lift=10, name="lid"):
    """bl_code's lid(), with the same numbers: a plate as big as ob's outside + a lip into its opening + a knob."""
    c, dx, dy, ztop, rnd, _, _ = _outline(ob)
    z0 = ztop + lift
    zt = z0 + lip + thickness / 2
    if rnd:
        r = max(dx, dy) / 2
        top = cylinder(r, thickness, loc=(c[0], c[1], zt), name=name)
        if lip > 0 and r - 2 * wall - gap > 1:
            ring = cylinder(r - wall - gap, lip, loc=(c[0], c[1], z0 + lip / 2))
            join(top, cut(ring, cylinder(r - 2 * wall - gap, lip + 2, loc=(c[0], c[1], z0 + lip / 2))))
    else:
        top = box((dx, dy, thickness), loc=(c[0], c[1], zt), name=name)
        ix, iy = dx - 2 * (wall + gap), dy - 2 * (wall + gap)
        if lip > 0 and ix - 2 * wall > 1 and iy - 2 * wall > 1:
            ring = box((ix, iy, lip), loc=(c[0], c[1], z0 + lip / 2))
            join(top, cut(ring, box((ix - 2 * wall, iy - 2 * wall, lip + 2), loc=(c[0], c[1], z0 + lip / 2))))
    if knob:
        kr = max(4.0, min(12.0, 0.1 * min(dx, dy)))
        join(top, cylinder(kr, 10, loc=(c[0], c[1], z0 + lip + thickness + 4.5)))
    top.name = name
    return top


def handle(ob, side="+x", z=None, reach=None, thick=None):
    """bl_code's handle(): a loop on ob's side, its ends sunk 0.8 mm into the wall, merged into ob."""
    c, dx, dy, _, rnd, lo, hi = _outline(ob)
    ax, sgn = str(side)[-1].lower(), -1 if str(side).startswith("-") else 1
    reach = float(reach or max(12.0, 0.15 * min(dx, dy)))
    t = float(thick or max(3.0, reach * 0.22))
    z = lo[2] + (hi[2] - lo[2]) * 0.66 if z is None else z
    at, rot = ((c[0] + sgn * dx / 2, c[1], z), (90, 0, 0)) if ax == "x" else ((c[0], c[1] + sgn * dy / 2, z), (90, 0, 90))
    loop = torus(reach, t, loc=at, rot=rot, name="handle")
    tall = (hi[2] - lo[2]) + 4 * reach
    inside = (cylinder(max(dx, dy) / 2 - 0.8, tall, loc=c) if rnd else box((dx - 1.6, dy - 1.6, tall), loc=c))
    cut(loop, inside)
    return join(ob, loop)


def say(*a, **k):
    pass


def fit(*a, **k):
    return []


fix_fit = fit
ALLOWED = {"math": math, "random": random}


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if name in ALLOWED:
        return ALLOWED[name]
    raise ImportError(f"only math and random can be imported here, not {name}")


SAFE = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k) for k in (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int", "isinstance", "len", "list",
    "map", "max", "min", "pow", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip", "Exception",
    "ValueError", "ZeroDivisionError", "IndexError", "KeyError", "TypeError", "True", "False", "None")}
SAFE.update(print=lambda *a, **k: None, __import__=_import)


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    code = str(job.get("code") or "")
    problems = check_code(code)
    if problems:
        out.write_text(json.dumps({"error": "the code didn't pass the code check", "refused": problems}), encoding="utf-8")
        return
    env = {"__builtins__": SAFE, "math": math, "random": random, "pi": math.pi}
    env.update({k: v for k, v in globals().items() if k in (
        "box", "cylinder", "cone", "sphere", "torus", "tube", "extrude", "revolve", "gear", "helix", "rod", "join", "cut",
        "intersect", "move", "rotate", "copy", "array", "mirror", "bevel", "smooth", "color", "part", "hollow", "lid",
        "handle", "say", "fit", "fix_fit")})
    env.update(make_lid=lid, add_handle=handle)  # the names bl_code gives the AI
    try:
        exec(compile(code, "design.py", "exec"), env)  # noqa: S102 — checked above, building blocks only
    except Unsupported as e:
        out.write_text(json.dumps({"error": f"this design uses {e}, which can't be edited as parts"}), encoding="utf-8")
        return
    except Exception as e:  # noqa: BLE001
        out.write_text(json.dumps({"error": f"the code stopped: {type(e).__name__}: {e}"[:300]}), encoding="utf-8")
        return
    groups = {}
    for o in OBJS:
        if o.used or not o.parts:
            continue
        g = groups.setdefault(o.group or o.name, {"name": o.group or o.name, "parts": [], "reference": False})
        g["parts"] += o.parts
        g["reference"] = g["reference"] or o.ref
    bodies = []
    for g in groups.values():
        adds = [p for p in g["parts"] if p.get("op", "add") == "add"]
        if not adds:
            continue
        rest = [p for p in g["parts"] if p is not adds[0]]  # the body starts with something to cut from
        b = {"name": g["name"], "parts": [adds[0]] + rest}
        if g["reference"]:
            b["reference"] = True
        bodies.append(b)
    if not bodies:
        out.write_text(json.dumps({"error": "the code made no parts"}), encoding="utf-8")
        return
    r3 = lambda v: [round(float(x), 3) + 0.0 for x in v]  # noqa: E731
    for b in bodies:
        for p in b["parts"]:
            for key in ("center", "rotate", "from", "to", "size"):
                if key in p:
                    p[key] = r3(p[key])
    out.write_text(json.dumps({"recipe": {"name": str(job.get("name") or "design")[:80], "bodies": bodies}}), encoding="utf-8")


main()
