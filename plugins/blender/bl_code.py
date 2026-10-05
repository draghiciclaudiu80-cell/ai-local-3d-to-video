"""Runs INSIDE Blender (background) — the AI's OWN Python, only when the user switched "Python code" on in the chat.
    blender -b --factory-startup --disable-autoexec --python bl_code.py -- job.json <output folder>
The code was already checked by app.security.check_code (only bpy / bmesh / mathutils / math / random / itertools /
collections; no files, network, system calls or hidden attributes). Here it also runs with restricted built-ins and a
guarded import. Then the app's own code takes over: every visible mesh = a part (grouped by part(... group=)), fit
check, STL per part, GLB, rendered picture. Errors come back with the exact line in "model_code.py" and what the code
printed, so the AI can fix it (like a programmer reading a traceback). 1 unit = 1 mm, Z up, the front faces -Y."""
import builtins
import collections
import contextlib
import io
import itertools
import json
import math
import random
import re
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
import mathutils
from mathutils import Euler, Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
OUT = Path(argv[1])
scene = bpy.context.scene
coll = scene.collection
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
_origin = bpy.data.objects.new("world origin", None)
coll.objects.link(_origin)
SOLVER = "MANIFOLD" if "MANIFOLD" in [e.identifier for e in bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items] else "EXACT"


def say(s: str) -> None:
    sys.__stdout__.write(s + "\n")
    sys.__stdout__.flush()


# ---------------------------------------------------------------- helpers for the AI (documented in the blender-python skill)
def _new(fill, name, loc, rot):
    bm = bmesh.new()
    fill(bm)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.location = Vector(loc)
    ob.rotation_euler = Euler([math.radians(a) for a in rot])
    return ob


def _apply(ob, retry_exact=True):
    """All modifiers applied into the mesh (a MANIFOLD boolean that empties the mesh is retried with EXACT)."""
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    if not len(me.polygons) and retry_exact and any(m.type == "BOOLEAN" for m in ob.modifiers):
        bpy.data.meshes.remove(me)
        for m in ob.modifiers:
            if m.type == "BOOLEAN":
                m.solver = "EXACT"
        return _apply(ob, False)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    if old.users == 0:
        bpy.data.meshes.remove(old)
    return ob


def box(size, *more, loc=(0, 0, 0), rot=(0, 0, 0), name="box", bevel=0):
    """A box of size [x, y, z] mm, centred on loc. box(x, y, z, loc=…) works too (the model wrote that 4x in a row);
    box(20) = a 20 mm cube."""
    if isinstance(size, (int, float)):
        size, more = ((size, *more[:2]) if len(more) >= 2 else (size, size, size)), more[2:]
    if more:  # box((x, y, z), (px, py, pz), (rx, ry, rz)) — positional loc / rot
        loc, rot = more[0], (more[1] if len(more) > 1 else rot)
    sx, sy, sz = size
    ob = _new(lambda bm: (bmesh.ops.create_cube(bm, size=1.0), bmesh.ops.scale(bm, vec=Vector((sx, sy, sz)), verts=bm.verts)),
              name, loc, rot)
    return _bevel(ob, bevel) if bevel else ob


def cylinder(radius, depth, loc=(0, 0, 0), rot=(0, 0, 0), name="cylinder", segments=64, bevel=0):
    """A cylinder along Z (depth = its height), centred on loc. rot=(0, 90, 0) lays it along X."""
    ob = _new(lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius, radius2=radius, depth=depth),
              name, loc, rot)
    return _bevel(ob, bevel) if bevel else ob


def cone(radius1, radius2, depth, loc=(0, 0, 0), rot=(0, 0, 0), name="cone", segments=64):
    return _new(lambda bm: bmesh.ops.create_cone(bm, cap_ends=True, segments=segments, radius1=radius1,
                                                 radius2=max(radius2, 0.01), depth=depth), name, loc, rot)


def sphere(radius, loc=(0, 0, 0), name="sphere", segments=48):
    return _new(lambda bm: bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=max(8, segments // 2), radius=radius),
                name, loc, (0, 0, 0))


def torus(major, minor, loc=(0, 0, 0), rot=(0, 0, 0), name="torus", segments=64):
    """A ring lying flat (in XY) around loc: major = ring radius, minor = tube radius. rot=(90, 0, 0) stands it up."""
    def fill(bm):
        n2 = max(12, segments // 3)
        ring = [[bm.verts.new(((major + minor * math.cos(b)) * math.cos(a), (major + minor * math.cos(b)) * math.sin(a),
                               minor * math.sin(b))) for b in (2 * math.pi * j / n2 for j in range(n2))]
                for a in (2 * math.pi * i / segments for i in range(segments))]
        for i in range(segments):
            for j in range(n2):
                bm.faces.new((ring[i][j], ring[(i + 1) % segments][j], ring[(i + 1) % segments][(j + 1) % n2], ring[i][(j + 1) % n2]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _new(fill, name, loc, rot)


def _boolean(target, others, op):
    for o in others:
        m = target.modifiers.new(op.lower(), "BOOLEAN")
        m.operation, m.object, m.solver = op, o, SOLVER
    _apply(target)
    for o in others:  # used up: HIDDEN (not deleted), so code that touches it again can't crash; hidden = not exported
        o.hide_render, o.display_type, o["lai_used"] = True, "WIRE", True
        o.hide_set(True)
    return target


def cut(target, *cutters):
    """Subtract the cutters from target (holes, pockets); the cutters are deleted. Returns target."""
    return _boolean(target, cutters, "DIFFERENCE")


def join(target, *others):
    """Merge the others into target (one solid); the others are deleted. Returns target."""
    return _boolean(target, others, "UNION")


def move(ob, x=0, y=0, z=0):
    ob.location += Vector((x, y, z))
    return ob


def rotate(ob, x=0, y=0, z=0):
    ob.rotation_euler = Euler((ob.rotation_euler.x + math.radians(x), ob.rotation_euler.y + math.radians(y),
                               ob.rotation_euler.z + math.radians(z)))
    return ob


def copy(ob, name=None):
    c = ob.copy()
    c.data = ob.data.copy()
    coll.objects.link(c)
    if name:
        c.name = name
    return c


def array(ob, count, offset):
    """count copies in a row, offset [dx, dy, dz] mm apart, merged into ob."""
    m = ob.modifiers.new("array", "ARRAY")
    m.count, m.use_relative_offset, m.use_constant_offset = int(count), False, True
    m.constant_offset_displacement = offset
    return _apply(ob)


def mirror(ob, axis="x"):
    """ob plus its mirror image across the world's centre plane (x: left/right, y: front/back, z: up/down)."""
    m = ob.modifiers.new("mirror", "MIRROR")
    m.use_axis = [axis == a for a in "xyz"]
    m.mirror_object = _origin
    return _apply(ob)


def _bevel(ob, width, segments=3):
    m = ob.modifiers.new("bevel", "BEVEL")
    m.width, m.segments, m.limit_method = width, segments, "ANGLE"
    return _apply(ob)


bevel = _bevel


def smooth(ob):
    for p in ob.data.polygons:
        p.use_smooth = True
    return ob


def color(ob, hexcolor, metal=0.0):
    ob["lai_color"], ob["lai_metal"] = str(hexcolor), float(metal)
    return ob


def part(ob, name=None, group=None, reference=False):
    """Mark ob as a printed piece; objects with the same group become ONE piece; reference=True = a part to buy."""
    if name:
        ob.name = name
    ob["lai_group"], ob["lai_ref"] = group or name or ob.name, bool(reference)
    return ob


# ---------------------------------------------------------------- whole features in one call (a 4B model got these wrong
# by hand: a pot "hollowed" with a centred cutter = a sealed void; its lid joined INTO the pot; handles as loose parts)
def _bounds(ob):
    vs = [ob.matrix_world @ v.co for v in ob.data.vertices] or [ob.location.copy()]
    return Vector([min(v[i] for v in vs) for i in range(3)]), Vector([max(v[i] for v in vs) for i in range(3)])


def _bake(ob):
    """Rotation / scale into the mesh (the object keeps its place), so "top" means the world's top."""
    _apply(ob)
    loc = ob.matrix_basis.to_translation()
    ob.data.transform(Matrix.Translation(-loc) @ ob.matrix_basis)
    ob.rotation_euler, ob.scale, ob.location = (0, 0, 0), (1, 1, 1), loc
    return ob


def _outline(ob):
    """The body's own outline, measured at its TOP rim (handles sit lower, so they don't count) ->
    (centre, size x, size y, top z, round?)."""
    lo, hi = _bounds(ob)
    band = max(0.5, 0.015 * (hi.z - lo.z))
    rim = [p for p in (ob.matrix_world @ v.co for v in ob.data.vertices) if p.z > hi.z - band] or [lo, hi]
    rlo = Vector([min(p[i] for p in rim) for i in range(2)])
    rhi = Vector([max(p[i] for p in rim) for i in range(2)])
    c, dx, dy = (rlo + rhi) / 2, rhi.x - rlo.x, rhi.y - rlo.y
    d = [(p.xy - c).length for p in rim]
    far = max(d or [0])
    rnd = abs(dx - dy) <= 0.03 * max(dx, dy, 1e-6) and sum(1 for x in d if x > far * 0.98) > 12  # a box: only 4 corners
    return Vector((c.x, c.y, (lo.z + hi.z) / 2)), dx, dy, hi.z, rnd


def _is_round(ob):
    return _outline(ob)[4]


def hollow(ob, wall=2, open="top"):
    """Makes ob a CONTAINER: walls `wall` mm thick, the outside stays the same. open="top" (a pot, box, cup),
    "bottom", or None (closed all round - a sealed inside, rarely wanted). Returns ob."""
    _bake(ob)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    zs = [v.co.z for v in bm.verts]
    if open in ("top", "bottom") and zs:
        lim, sign, tol = (max(zs), 1, 0.01 * (max(zs) - min(zs)) + 1e-3) if open == "top" else (min(zs), -1, 0.01 * (max(zs) - min(zs)) + 1e-3)
        faces = [f for f in bm.faces if f.normal.z * sign > 0.99 and abs(f.calc_center_median().z - lim) < tol]
        bmesh.ops.delete(bm, geom=faces, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    m = ob.modifiers.new("hollow", "SOLIDIFY")
    m.thickness, m.offset, m.use_even_offset, m.use_rim = float(wall), -1.0, True, True
    return _apply(ob, False)


def lid(ob, wall=2, thickness=3, gap=0.4, lip=6, knob=True, lift=10, name="lid"):
    """A SEPARATE lid for a hollowed ob (open top): a plate as big as ob's outside + a lip that fits into the opening
    with `gap` mm of play (use the same wall as hollow()) + a knob. Shown `lift` mm above ob, not touching it.
    Returns the lid: part(the_lid, "lid"). Never join() it to ob."""
    c, dx, dy, ztop, rnd = _outline(ob)
    z0 = ztop + lift
    zt = z0 + lip + thickness / 2
    if rnd:
        r = max(dx, dy) / 2
        top = cylinder(r, thickness, loc=(c.x, c.y, zt), name=name)
        if lip > 0 and r - 2 * wall - gap > 1:
            ring = cylinder(r - wall - gap, lip, loc=(c.x, c.y, z0 + lip / 2))
            join(top, cut(ring, cylinder(r - 2 * wall - gap, lip + 2, loc=(c.x, c.y, z0 + lip / 2))))
    else:
        top = box((dx, dy, thickness), loc=(c.x, c.y, zt), name=name)
        ix, iy = dx - 2 * (wall + gap), dy - 2 * (wall + gap)
        if lip > 0 and ix - 2 * wall > 1 and iy - 2 * wall > 1:
            ring = box((ix, iy, lip), loc=(c.x, c.y, z0 + lip / 2))
            join(top, cut(ring, box((ix - 2 * wall, iy - 2 * wall, lip + 2), loc=(c.x, c.y, z0 + lip / 2))))
    if knob:
        kr = max(4.0, min(12.0, 0.1 * min(dx, dy)))
        join(top, cylinder(kr, 10, loc=(c.x, c.y, z0 + lip + thickness + 4.5)))
    top.name = name
    return top


def handle(ob, side="+x", z=None, reach=None, thick=None):
    """A loop handle on ob's side ("+x", "-x", "+y", "-y"), merged INTO ob: one printed piece, no gap, no collision.
    z = its height (default: 2/3 up), reach = how far it sticks out (mm), thick = its thickness. Returns ob."""
    _apply(ob)
    lo, hi = _bounds(ob)
    c, dx, dy, _, rnd = _outline(ob)  # the body without the handles it already has
    ax, sgn = side[-1].lower(), -1 if str(side).startswith("-") else 1
    reach = float(reach or max(12.0, 0.15 * min(dx, dy)))
    t = float(thick or max(3.0, reach * 0.22))
    z = lo.z + (hi.z - lo.z) * 0.66 if z is None else z
    if ax == "x":
        at, rot = (c.x + sgn * dx / 2, c.y, z), (90, 0, 0)
    else:
        at, rot = (c.x, c.y + sgn * dy / 2, z), (90, 0, 90)
    loop = torus(reach, t, loc=at, rot=rot, name="handle")
    sink = 0.8  # the ends go 0.8 mm into the wall: merged, but never through a thin wall
    tall = (hi.z - lo.z) + 4 * reach
    if rnd:
        inside = cylinder(max(dx, dy) / 2 - sink, tall, loc=(c.x, c.y, c.z))
    else:
        inside = box((dx - 2 * sink, dy - 2 * sink, tall), loc=(c.x, c.y, c.z))
    cut(loop, inside)
    return join(ob, loop)


# ---------------------------------------------------------------- PicoGK's shapes in Blender (so a PicoGK design can be
# translated into Blender Python and then changed): same sizes, same gear teeth, same thread path. All centred on loc.
def _prism(points, height, name, loc, rot):
    """A flat outline [[x, y], ...] made `height` thick, centred on loc."""
    def fill(bm):
        vs = [bm.verts.new((float(x), float(y), -height / 2)) for x, y in points]
        f = bm.faces.new(vs)
        ext = bmesh.ops.extrude_face_region(bm, geom=[f])
        bmesh.ops.translate(bm, vec=Vector((0, 0, height)), verts=[v for v in ext["geom"] if isinstance(v, bmesh.types.BMVert)])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _new(fill, name, loc, rot)


def extrude(points, height, loc=(0, 0, 0), rot=(0, 0, 0), name="extrude"):
    return _prism(points, height, name, loc, rot)


def tube(radius, wall, depth, loc=(0, 0, 0), rot=(0, 0, 0), name="tube", segments=64):
    """A pipe: outer radius, wall thickness, length along Z, centred on loc."""
    t = cylinder(radius, depth, loc=loc, rot=rot, name=name, segments=segments)
    return cut(t, cylinder(max(radius - wall, 0.05), depth + 2, loc=loc, rot=rot, segments=segments))


def _gear_profile(z, m, backlash=0.15):  # PicoGK's involute (20 degrees), point for point
    z = max(int(z), 6)
    rp, alpha = m * z / 2, math.radians(20)
    ra, rf, rb = rp + m, max(rp - 1.25 * m, 0.3), rp * math.cos(alpha)
    inv = lambda a: math.tan(a) - a  # noqa: E731
    psi = math.pi / (2 * z) - backlash / (2 * rp)
    theta = lambda r: max(psi + inv(alpha) - inv(math.acos(max(-1.0, min(1.0, rb / max(r, rb))))), 0.004)  # noqa: E731
    pts, n = [], 8
    for k in range(z):
        phi = 2 * math.pi * k / z
        for i in range(n + 1):
            r = rf + (ra - rf) * i / n
            pts.append((r * math.cos(phi - theta(r)), r * math.sin(phi - theta(r))))
        pts.append((ra * math.cos(phi), ra * math.sin(phi)))
        for i in range(n, -1, -1):
            r = rf + (ra - rf) * i / n
            pts.append((r * math.cos(phi + theta(r)), r * math.sin(phi + theta(r))))
        a0, a1 = phi + theta(rf), phi + 2 * math.pi / z - theta(rf)
        for i in (1, 2):
            pts.append((rf * math.cos(a0 + (a1 - a0) * i / 3), rf * math.sin(a0 + (a1 - a0) * i / 3)))
    return pts


def gear(teeth, module, height, bore=0, loc=(0, 0, 0), rot=(0, 0, 0), backlash=0.15, name="gear"):
    """A spur gear (involute, 20 degrees): pitch diameter = module x teeth; two gears mesh at (t1 + t2) x module / 2."""
    g = _prism(_gear_profile(teeth, module, backlash), height, name, loc, rot)
    return cut(g, cylinder(bore, height + 2, loc=loc, rot=rot)) if bore > 0 else g


def helix(radius, wire, height, turns, loc=(0, 0, 0), rot=(0, 0, 0), name="helix"):
    """A coil (spring, or a round THREAD on a core of the same radius): wire radius `wire` wound on `radius`, rising
    `height` in `turns`, centred on loc, starting at +X."""
    # Built by hand as a CLOSED tube (a bevelled curve left its ends open -> booleans ignored it: threads vanished)
    n, m = max(8, int(math.ceil(turns * 36))), 16
    rise = height / (2 * math.pi * turns) if turns else 0.0

    def fill(bm):
        rings = []
        for i in range(n + 1):
            t = 2 * math.pi * turns * i / n
            p = Vector((radius * math.cos(t), radius * math.sin(t), -height / 2 + height * i / n))
            out = Vector((math.cos(t), math.sin(t), 0))                       # away from the axis
            along = Vector((-radius * math.sin(t), radius * math.cos(t), rise)).normalized()
            side = along.cross(out).normalized()
            rings.append([bm.verts.new(p + wire * (math.cos(2 * math.pi * j / m) * out + math.sin(2 * math.pi * j / m) * side))
                          for j in range(m)])
        for a, b in zip(rings, rings[1:]):
            for j in range(m):
                bm.faces.new((a[j], a[(j + 1) % m], b[(j + 1) % m], b[j]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _new(fill, name, loc, rot)


def revolve(points, loc=(0, 0, 0), rot=(0, 0, 0), name="revolve", segments=64):
    """A profile [[r, z], ...] turned around the Z axis (bottles, nozzles, pistons); z as given, from loc."""
    def fill(bm):
        vs = [bm.verts.new((float(r), 0.0, float(z))) for r, z in points]
        f = bm.faces.new(vs)
        bmesh.ops.spin(bm, geom=[f, *f.edges, *vs], angle=2 * math.pi, steps=segments, axis=(0, 0, 1),
                       cent=(0, 0, 0), use_merge=True)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _new(fill, name, loc, rot)


def rod(start, end, radius, round_ends=False, name="rod"):
    """A round bar from `start` to `end` (world points): pins, shafts, axles, arms at any angle."""
    a, b = Vector(start), Vector(end)
    d = b - a
    ob = cylinder(radius, max(d.length, 0.01), loc=tuple((a + b) / 2), name=name)
    ob.rotation_euler = d.to_track_quat("Z", "Y").to_euler() if d.length > 1e-6 else Euler((0, 0, 0))
    if round_ends:
        join(ob, sphere(radius, loc=tuple(a)), sphere(radius, loc=tuple(b)))
    return ob


def intersect(target, *others):
    """Keep only where target and the others overlap."""
    return _boolean(target, others, "INTERSECT")


# ---------------------------------------------------------------- run the AI's code (restricted)
ALLOWED = {"bpy", "bmesh", "mathutils", "math", "random", "itertools", "collections"}


def _import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name.split(".")[0] not in ALLOWED:
        raise ImportError(f"'{name}' can't be imported here (only {', '.join(sorted(ALLOWED))})")
    return builtins.__import__(name, globals, locals, fromlist, level)


SAFE = {n: getattr(builtins, n) for n in (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "frozenset", "int", "isinstance", "iter",
    "len", "list", "map", "max", "min", "next", "pow", "print", "range", "repr", "reversed", "round", "set", "slice", "sorted",
    "str", "sum", "tuple", "zip", "chr", "ord", "hex", "bin", "hash", "object", "super", "type", "staticmethod",
    "classmethod", "property", "Exception", "ValueError", "RuntimeError", "TypeError", "IndexError", "KeyError",
    "ZeroDivisionError", "AttributeError", "NameError", "StopIteration", "AssertionError", "True", "False", "None")}
SAFE["__import__"] = _import
ns = {"__builtins__": SAFE, "__name__": "model_code", "bpy": bpy, "bmesh": bmesh, "mathutils": mathutils, "math": math,
      "random": random, "itertools": itertools, "collections": collections, "Vector": Vector, "Matrix": Matrix,
      "Euler": Euler, "Quaternion": Quaternion, "radians": math.radians, "degrees": math.degrees, "pi": math.pi,
      "box": box, "cylinder": cylinder, "cone": cone, "sphere": sphere, "torus": torus, "cut": cut, "join": join,
      "move": move, "rotate": rotate, "copy": copy, "array": array, "mirror": mirror, "bevel": bevel, "smooth": smooth,
      "color": color, "part": part, "hollow": hollow, "tube": tube, "extrude": extrude, "gear": gear, "helix": helix,
      "revolve": revolve, "rod": rod, "intersect": intersect,
      "make_lid": lid, "add_handle": handle}  # not "lid"/"handle": the model writes lid = lid(pot) and breaks it
printed = io.StringIO()
say("PROGRESS: 0/1 running the code")
try:
    with contextlib.redirect_stdout(printed):
        exec(compile(job["code"], "model_code.py", "exec"), ns)  # noqa: S102 — checked code, restricted namespace
except BaseException as e:  # noqa: BLE001 — the error goes back to the AI to fix
    tb = traceback.extract_tb(e.__traceback__)
    mine = [f for f in tb if f.filename == "model_code.py"]
    line = mine[-1].lineno if mine else getattr(e, "lineno", None)
    src = job["code"].splitlines()
    say("RESULT: " + json.dumps({"error": f"{type(e).__name__}: {e}", "line": line,
                                 "code_line": src[line - 1].strip() if line and 0 < line <= len(src) else "",
                                 "printed": printed.getvalue()[-1500:]}))
    sys.exit(0)

# ---------------------------------------------------------------- the app's part: parts, fit check, STL, GLB, picture
objs = [o for o in scene.objects if o.type == "MESH" and not o.hide_render and o.display_type not in ("WIRE", "BOUNDS")
        and not o.hide_get()]
if not objs:
    say("RESULT: " + json.dumps({"error": "the code made no visible mesh objects (nothing to export)",
                                 "printed": printed.getvalue()[-1500:]}))
    sys.exit(0)
PALETTE = ["#4ad696", "#5aa9ff", "#ffb347", "#ff6f91", "#c39bff", "#7fdbda", "#f9f871", "#ff9671"]
dg = bpy.context.evaluated_depsgraph_get()
groups = collections.OrderedDict()
for o in objs:
    groups.setdefault(str(o.get("lai_group", o.name)), []).append(o)
bodies = []
for k, (gname, members) in enumerate(groups.items()):
    say(f"PROGRESS: {k}/{len(groups)} {gname}")
    bm = bmesh.new()
    for o in members:
        me = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=False, depsgraph=dg)
        me.transform(o.matrix_world)
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    open_edges = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    volume = abs(bm.calc_volume())  # world mm3 — "solid or hollow?" for the app's checks
    me = bpy.data.meshes.new(gname)
    bm.to_mesh(me)
    bm.free()
    first = members[0]
    hx = str(first.get("lai_color") or ("#9aa0a6" if first.get("lai_ref") else PALETTE[k % len(PALETTE)]))
    if not (len(hx) == 7 and hx.startswith("#")):
        hx = PALETTE[k % len(PALETTE)]
    srgb = tuple(int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)) + (1.0,)
    mat = bpy.data.materials.new(gname)
    mat.diffuse_color, mat.metallic, mat.roughness = srgb, float(first.get("lai_metal", 0)), 0.45
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = tuple(c ** 2.2 for c in srgb[:3]) + (1.0,)
            bsdf.inputs["Metallic"].default_value = float(first.get("lai_metal", 0))
    except (AttributeError, TypeError):
        pass
    me.materials.append(mat)
    body = bpy.data.objects.new(gname, me)
    body.color = srgb
    coll.objects.link(body)
    bodies.append({"obj": body, "name": gname, "reference": bool(first.get("lai_ref")), "open_edges": open_edges, "color": hx,
                   "volume": volume})
for o in objs:
    bpy.data.objects.remove(o, do_unlink=True)


def fit(bodies):
    """-> (boxes, trees, clashes): every pair of separate pieces that runs into each other."""
    dg = bpy.context.evaluated_depsgraph_get()
    boxes = []
    for b in bodies:
        vs = [v.co for v in b["obj"].data.vertices] or [Vector((0, 0, 0))]
        boxes.append((Vector([min(v[i] for v in vs) for i in range(3)]), Vector([max(v[i] for v in vs) for i in range(3)])))
    trees = [BVHTree.FromObject(b["obj"], dg) for b in bodies]
    clashes = []
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            (a0, a1), (b0, b1) = boxes[i], boxes[j]
            if any(a1[k] < b0[k] or b1[k] < a0[k] for k in range(3)):
                continue
            n = len(trees[i].overlap(trees[j]))
            if n:
                clashes.append({"a": bodies[i]["name"], "b": bodies[j]["name"], "crossing_faces": n})
    return boxes, trees, clashes


def _vol(ob):
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    v = abs(bm.calc_volume())
    bm.free()
    return v


# Nothing is delivered with pieces running into each other. The AI gets the list to fix it itself; if some are
# still there, the app fixes them the way a person would, then checks again:
ATTACHED = re.compile(r"handle|knob|leg|feet|foot|spout|ear|hook|bracket|rib|grip|stand|mount|clip|tab", re.I)
LIFTS = re.compile(r"lid|cover|cap\b", re.I)  # comes off upwards


def _zr(ob):
    zs = [(ob.matrix_world @ v.co).z for v in ob.data.vertices] or [ob.location.z]
    return min(zs), max(zs)


def fix_fit(bodies, clashes, cut_only=False):
    """cut_only: a later round only cuts gaps — a lift can push a part into a third one (a lock's key lifted off its
    pin went into the box), and lifting again could go on forever."""
    done = []
    for c in clashes:
        a = next((b for b in bodies if b["name"] == c["a"]), None)
        b = next((x for x in bodies if x["name"] == c["b"]), None)
        if not a or not b:
            continue  # already merged away
        la, lb = LIFTS.search(a["name"]), LIFTS.search(b["name"])
        aa, ab = ATTACHED.search(a["name"]) and not la, ATTACHED.search(b["name"]) and not lb
        if cut_only:
            la = lb = aa = ab = None
        if (aa or ab) and not (a["reference"] or b["reference"]):  # a handle belongs to its pot: one piece
            keep, extra = (b, a) if aa and not ab else (a, b) if ab and not aa else sorted((a, b), key=lambda x: -x["volume"])
            m = keep["obj"].modifiers.new("merge", "BOOLEAN")
            m.operation, m.object, m.solver = "UNION", extra["obj"], SOLVER
            _apply(keep["obj"])
            bpy.data.objects.remove(extra["obj"], do_unlink=True)
            bodies.remove(extra)
            keep["volume"] = _vol(keep["obj"])
            done.append(f"merged '{extra['name']}' into '{keep['name']}' (it's one piece with it)")
            continue
        if la or lb:  # a lid sitting in / on its box: lifted until it's clear
            lid_b, other = (a, b) if la else (b, a)
            lo_l = min((lid_b["obj"].matrix_world @ v.co).z for v in lid_b["obj"].data.vertices)
            hi_o = max((other["obj"].matrix_world @ v.co).z for v in other["obj"].data.vertices)
            up = hi_o - lo_l + 1.0
            lid_b["obj"].data.transform(Matrix.Translation((0, 0, up)))
            done.append(f"lifted '{lid_b['name']}' {up:.1f} mm so it sits clear of '{other['name']}'")
            continue
        za, zb = _zr(a["obj"]), _zr(b["obj"])  # STACKED (a body standing in its base, a top on a column): lift the upper
        up_b, lo_b = (a, b) if za[0] + za[1] > zb[0] + zb[1] else (b, a)  # one — and all that sits above it — until clear
        zu, zl = _zr(up_b["obj"]), _zr(lo_b["obj"])
        pen = zl[1] - zu[0]
        if not cut_only and 0 < pen <= 0.35 * (zu[1] - zu[0]) and not up_b["reference"]:
            mid = (zu[0] + zu[1]) / 2
            for x in bodies:
                if x is up_b or (x is not lo_b and sum(_zr(x["obj"])) / 2 >= mid):
                    x["obj"].data.transform(Matrix.Translation((0, 0, pen + 0.4)))
            done.append(f"lifted '{up_b['name']}' {pen + 0.4:.1f} mm so it stands clear on '{lo_b['name']}'")
            continue
        big, small = sorted((a, b), key=lambda x: -x["volume"])  # a pin through a plate: a 0.4 mm gap around the pin
        if big["reference"]:
            big, small = small, big
        shell = small["obj"].copy()
        shell.data = small["obj"].data.copy()
        coll.objects.link(shell)
        s = shell.modifiers.new("gap", "SOLIDIFY")
        s.thickness, s.offset, s.use_even_offset = 0.4, 1.0, True
        _apply(shell, False)
        m1 = big["obj"].modifiers.new("gap", "BOOLEAN")
        m1.operation, m1.object, m1.solver = "DIFFERENCE", small["obj"], SOLVER
        m2 = big["obj"].modifiers.new("gap2", "BOOLEAN")
        m2.operation, m2.object, m2.solver = "DIFFERENCE", shell, SOLVER
        _apply(big["obj"])
        bpy.data.objects.remove(shell, do_unlink=True)
        big["volume"] = _vol(big["obj"])
        done.append(f"cut a 0.4 mm gap in '{big['name']}' around '{small['name']}'")
    return done


say(f"PROGRESS: fit {len(bodies)}")
boxes, trees, clashes = fit(bodies)
raw_clashes, fixed = clashes, []
for rnd in range(3) if job.get("fix_fit", True) else ():  # fixed, checked again, until nothing touches
    if not clashes:
        break
    say("PROGRESS: fit fixing the collisions")
    fixed += fix_fit(bodies, clashes, cut_only=rnd > 0)
    boxes, trees, clashes = fit(bodies)  # tested again: what's delivered is what was checked
out_bodies = []
for k, b in enumerate(bodies):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    b["obj"].select_set(True)
    bpy.context.view_layer.objects.active = b["obj"]
    stl = OUT / f"body{k}.stl"
    bpy.ops.wm.stl_export(filepath=str(stl), export_selected_objects=True, global_scale=1.0, apply_modifiers=True)
    lo, hi = boxes[k]
    # Can things go in? A ray straight down through the middle: it hits the floor of an open container, the top of a
    # solid or closed one (a centred cutter once made a sealed void: it looked solid and nothing could go in).
    mid = (lo + hi) / 2
    hit = trees[k].ray_cast(Vector((mid.x, mid.y, hi.z + 1)), Vector((0, 0, -1)))
    depth = (hi.z - hit[0].z) if hit[0] is not None else (hi.z - lo.z)
    boxv = max((hi.x - lo.x) * (hi.y - lo.y) * (hi.z - lo.z), 1e-6)
    _, odx, ody, _, rnd = _outline(b["obj"])  # its own size at the rim: handles don't count as "too wide"
    out_bodies.append({"name": b["name"], "stl": str(stl), "triangles": sum(len(p.vertices) - 2 for p in b["obj"].data.polygons),
                       "reference": b["reference"], "size_mm": [round(hi[i] - lo[i], 1) for i in range(3)],
                       "open_edges": b["open_edges"], "color": b["color"], "fill": round(b["volume"] / boxv, 2),
                       "open_top": bool(depth > max(3.0, 0.25 * (hi.z - lo.z))), "inside_depth_mm": round(depth, 1),
                       "outline_mm": [round(odx, 1), round(ody, 1)], "round": bool(rnd)})
glb = OUT / "model.glb"
try:
    root = bpy.data.objects.new("model (m)", None)
    coll.objects.link(root)
    for b in bodies:
        b["obj"].parent = root
    root.scale = (0.001, 0.001, 0.001)
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=False)
    root.scale = (1, 1, 1)
    for b in bodies:
        b["obj"].parent = None
except Exception as e:  # noqa: BLE001
    say(f"glb failed: {e}")
    glb = None
render = OUT / "render.png"
try:
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light, sh.color_type, sh.show_shadows, sh.show_cavity = "STUDIO", "MATERIAL", True, True
        scene.display.render_aa = "8"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
    scene.world = scene.world or bpy.data.worlds.new("world")
    scene.world.color = (0.86, 0.88, 0.86)
    lo = Vector([min(bx[0][i] for bx in boxes) for i in range(3)])
    hi = Vector([max(bx[1][i] for bx in boxes) for i in range(3)])
    c, diag = (lo + hi) / 2, max((hi - lo).length, 1.0)
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    coll.objects.link(cam)
    d = Vector((0.9, -1.6, 0.85)).normalized()
    cam.location = c + d * diag * 2
    q = (c - cam.location).to_track_quat("-Z", "Y")
    cam.rotation_euler = q.to_euler()
    right, up = q @ Vector((1, 0, 0)), q @ Vector((0, 1, 0))
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    w = max(p.dot(right) for p in corners) - min(p.dot(right) for p in corners)
    h = max(p.dot(up) for p in corners) - min(p.dot(up) for p in corners)
    cam.data.type, cam.data.ortho_scale = "ORTHO", max(w, h * 4 / 3) * 1.08
    cam.data.clip_start, cam.data.clip_end = diag * 0.01, diag * 10
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 960, 720, 100
    scene.render.filepath = str(render)
    bpy.ops.render.render(write_still=True)
except Exception as e:  # noqa: BLE001
    say(f"render failed: {e}")
    render = None
result = {"name": job.get("name") or "model", "bodies": out_bodies, "collisions": clashes,
          "raw_collisions": raw_clashes, "fit_fixed": list(dict.fromkeys(fixed)),
          "checked_pairs": len(bodies) * (len(bodies) - 1) // 2,
          "engine": f"Blender {bpy.app.version_string} ({str(job.get('engine_label') or 'AI code')[:60]})",
          "printed": printed.getvalue()[-1500:]}
if len(out_bodies) == 1:
    result.update({"stl": out_bodies[0]["stl"], "triangles": out_bodies[0]["triangles"], "size_mm": out_bodies[0]["size_mm"]})
if render and render.exists():
    result["render"] = str(render)
if glb and Path(glb).exists():
    result["glb"] = str(glb)
say("RESULT: " + json.dumps(result))
