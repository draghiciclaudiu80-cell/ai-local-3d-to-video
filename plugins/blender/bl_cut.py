"""Runs INSIDE Blender (the app starts it; no AI code): cuts parts that are too big for the printer's plate into pieces
that fit, and puts holes for alignment pins in the cut faces so the pieces line up when glued.

The grid of cuts is the smallest number of pieces that fit the plate (x / y may swap on a rectangular plate; such a piece
is turned 90° so it is ready to print). Each piece = the part INTERSECTED with its cell box (Blender's exact boolean), so
every piece is a closed solid. Pin holes: on every inner cut face, up to 3 spots where there is solid material all around
(and deep enough on both sides); a hole of the pin's size goes half into each piece. Default pins = short pieces of
1.75 mm filament (hole 2.1 mm, 5 mm deep each side); "printed" makes 4 mm holes and adds printed pins.
blender -b --python bl_cut.py -- job.json outdir  ->  prints "RESULT: {json}"."""
import itertools
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

args = sys.argv[sys.argv.index("--") + 1:]
JOB = json.loads(Path(args[0]).read_text(encoding="utf-8"))
OUT = Path(args[1])
COLORS = ["#4ad696", "#5aa9ff", "#ffb347", "#ff6f91", "#c39bff", "#7fdbda", "#f6d860", "#a0d468"]


def progress(text):
    print(f"PROGRESS: {text}", flush=True)


def clear():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load_stl(path: str):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.wm.stl_import(filepath=path)
    obj = bpy.context.selected_objects[0]
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def bbox(obj):
    vs = [obj.matrix_world @ v.co for v in obj.data.vertices]
    lo = Vector((min(v.x for v in vs), min(v.y for v in vs), min(v.z for v in vs)))
    hi = Vector((max(v.x for v in vs), max(v.y for v in vs), max(v.z for v in vs)))
    return lo, hi


def grid(size, bed, margin):
    """The fewest pieces (then the fewest cut planes) whose size fits the plate."""
    b = [x - margin for x in bed]
    best = None
    for nx, ny, nz in itertools.product(range(1, 10), repeat=3):
        px, py, pz = size[0] / nx, size[1] / ny, size[2] / nz
        if pz > b[2] or not ((px <= b[0] and py <= b[1]) or (py <= b[0] and px <= b[1])):
            continue
        key = (nx * ny * nz, (nx - 1) + (ny - 1) + (nz - 1))
        if best is None or key < best[0]:
            best = (key, (nx, ny, nz))
    return best[1] if best else None


def box_object(lo: Vector, hi: Vector, name="cell"):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    ob.scale = hi - lo
    ob.location = (lo + hi) / 2
    bpy.context.view_layer.update()
    return ob


def boolean(target, tool, op):
    m = target.modifiers.new("b", "BOOLEAN")
    m.operation = op
    m.object = tool
    try:
        m.solver = "MANIFOLD"
    except TypeError:
        m.solver = "EXACT"
    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=m.name)
    if op == "INTERSECT" and not target.data.polygons:
        return False
    return True


def inside(tree: BVHTree, p: Vector) -> bool:
    """Even-odd: count crossings of a ray from p to far away."""
    d = Vector((0.5773, 0.5774, 0.5773))  # a slanted ray: rarely runs along a face or an edge
    hits, o = 0, p.copy()
    for _ in range(64):
        loc, _n, _i, _dist = tree.ray_cast(o, d)
        if loc is None:
            break
        hits += 1
        o = loc + d * 1e-4
    return hits % 2 == 1


def pin_spots(tree, axis: int, at: float, lo2, hi2, r_hole: float, depth: float, want: int = 3):
    """Spots on the cut plane (axis = at) inside the solid, with material all round the hole and deep enough each side."""
    u, v = [a for a in range(3) if a != axis]
    span_u, span_v = hi2[0] - lo2[0], hi2[1] - lo2[1]
    step = max(3.0, min(span_u, span_v) / 24)
    wall = r_hole + 2.2
    ring = [(wall * math.cos(k * math.pi / 4), wall * math.sin(k * math.pi / 4)) for k in range(8)]
    cands = []
    nu, nv = int(span_u / step), int(span_v / step)
    for i in range(1, max(nu, 1)):
        for j in range(1, max(nv, 1)):
            q = [0.0, 0.0, 0.0]
            q[axis], q[u], q[v] = at, lo2[0] + i * step, lo2[1] + j * step
            p = Vector(q)
            if not inside(tree, p):
                continue
            ok = True
            for du, dv in ring:
                r = p.copy()
                r[u] += du
                r[v] += dv
                if not inside(tree, r):
                    ok = False
                    break
            if not ok:
                continue
            for s in (-1, 1):  # the hole's bottom on each side must still be inside the part
                r = p.copy()
                r[axis] += s * (depth + 1.0)
                if not inside(tree, r):
                    ok = False
                    break
            if ok:
                cands.append(p)
    if not cands:
        return []
    c = sum(cands, Vector()) / len(cands)
    picked = [min(cands, key=lambda p: (p - c).length)] if want == 1 else []
    rest = list(cands)
    while len(picked) < want and rest:  # spread them out: the farthest from the ones already picked
        p = max(rest, key=lambda q: min(((q - x).length for x in picked), default=(q - c).length))
        if picked and min((p - x).length for x in picked) < 12:
            break
        picked.append(p)
        rest.remove(p)
    return picked


def cylinder(center: Vector, axis: int, r: float, length: float, name="pin"):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=r, radius2=r, depth=length)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    if axis == 0:
        ob.rotation_euler = (0, math.pi / 2, 0)
    elif axis == 1:
        ob.rotation_euler = (math.pi / 2, 0, 0)
    ob.location = center
    bpy.context.view_layer.update()
    return ob


def export(obj, path: Path):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.wm.stl_export(filepath=str(path), export_selected_objects=True, apply_modifiers=True)


def main():
    bed = [float(x) for x in JOB.get("bed") or [220, 220, 250]]
    margin = float(JOB.get("margin") or 2.0)
    printed_pins = JOB.get("pin") == "printed"
    r_hole = (4.3 if printed_pins else 2.1) / 2
    depth = 5.0
    bodies, notes, cut_parts = [], [], 0
    k_col = 0
    for b in JOB.get("bodies") or []:
        clear()
        obj = load_stl(b["stl"])
        lo, hi = bbox(obj)
        size = hi - lo
        name = b.get("name") or "part"
        fits = size.z <= bed[2] and ((size.x <= bed[0] and size.y <= bed[1]) or (size.y <= bed[0] and size.x <= bed[1]))
        if fits or b.get("reference"):
            bodies.append({"name": name, "stl": b["stl"], "color": b.get("color") or COLORS[k_col % 8],
                           **({"reference": True} if b.get("reference") else {})})
            k_col += 1
            continue
        g = grid([size.x, size.y, size.z], bed, margin)
        if not g:
            notes.append(f"{name} is too big to cut into a sensible number of pieces for this plate.")
            bodies.append({"name": name, "stl": b["stl"], "color": COLORS[k_col % 8]})
            k_col += 1
            continue
        progress(f"cut {name}: {g[0]} × {g[1]} × {g[2]}")
        cut_parts += 1
        tree = BVHTree.FromObject(obj, bpy.context.evaluated_depsgraph_get())
        edges = [[lo[a] + size[a] * i / g[a] for i in range(g[a] + 1)] for a in range(3)]
        cells = {}
        for ix, iy, iz in itertools.product(range(g[0]), range(g[1]), range(g[2])):
            idx = (ix, iy, iz)
            clo = Vector((edges[0][ix], edges[1][iy], edges[2][iz]))
            chi = Vector((edges[0][ix + 1], edges[1][iy + 1], edges[2][iz + 1]))
            for a, i in enumerate(idx):  # the part's outside is never cut: the box reaches past it there
                if i == 0:
                    clo[a] -= 1.0
                if i == g[a] - 1:
                    chi[a] += 1.0
            piece = obj.copy()
            piece.data = obj.data.copy()
            bpy.context.collection.objects.link(piece)
            box = box_object(clo, chi)
            ok = boolean(piece, box, "INTERSECT")
            bpy.data.objects.remove(box, do_unlink=True)
            if ok:
                cells[idx] = piece
            else:
                bpy.data.objects.remove(piece, do_unlink=True)
        pins = 0
        for idx, piece in list(cells.items()):  # pin holes on every inner face shared with the next cell
            for a in range(3):
                nb = list(idx)
                nb[a] += 1
                nb = tuple(nb)
                if nb not in cells:
                    continue
                at = edges[a][idx[a] + 1]
                u, v = [x for x in range(3) if x != a]
                lo2 = (max(edges[u][idx[u]], lo[u]), max(edges[v][idx[v]], lo[v]))
                hi2 = (min(edges[u][idx[u] + 1], hi[u]), min(edges[v][idx[v] + 1], hi[v]))
                for p in pin_spots(tree, a, at, lo2, hi2, r_hole, depth):
                    tool = cylinder(p, a, r_hole, depth * 2)
                    boolean(piece, tool, "DIFFERENCE")
                    boolean(cells[nb], tool, "DIFFERENCE")
                    bpy.data.objects.remove(tool, do_unlink=True)
                    pins += 1
        n = len(cells)
        for k, (idx, piece) in enumerate(sorted(cells.items())):
            plo, phi = bbox(piece)
            ps = phi - plo
            if not (ps.x <= bed[0] and ps.y <= bed[1]) and (ps.y <= bed[0] and ps.x <= bed[1]):
                c = (plo + phi) / 2  # turned 90° on the plate so it's ready to print
                piece.data.transform(Matrix.Translation(c) @ Matrix.Rotation(math.pi / 2, 4, "Z") @ Matrix.Translation(-c))
            path = OUT / f"piece_{len(bodies)}.stl"
            export(piece, path)
            bodies.append({"name": f"{name} {k + 1}/{n}", "stl": str(path), "color": COLORS[k_col % 8]})
            k_col += 1
        if printed_pins and pins:
            pin = cylinder(Vector((0, 0, 0)), 2, r_hole - 0.2 - 0.15, depth * 2 - 0.6, "pins")
            path = OUT / f"pins_{len(bodies)}.stl"
            export(pin, path)
            bodies.append({"name": f"{name} pin (print {pins})", "stl": str(path), "color": "#9aa0a6"})
        notes.append(f"{name}: cut into {n} pieces ({g[0]}×{g[1]}×{g[2]}) to fit the {bed[0]:g}×{bed[1]:g}×{bed[2]:g} mm plate, "
                     f"{pins} pin{'s' if pins != 1 else ''} across the cuts (a hole on each side)"
                     + (" — pins: short pieces of 1.75 mm filament (about 9 mm long) + glue." if not printed_pins
                        else " — print the pins too (one per hole pair) and glue."))
    res = {"name": JOB.get("name") or "cut model", "bodies": bodies, "notes": " ".join(notes), "cut_parts": cut_parts}
    print("RESULT: " + json.dumps(res), flush=True)


main()
