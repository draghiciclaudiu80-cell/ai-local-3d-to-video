"""Runs INSIDE Blender (background): the app's fixed script — it never runs anything from the recipe, it only reads
numbers, shape names, colours and short texts (checked before by run.py).
    blender -b --factory-startup --disable-autoexec --python bl_runner.py -- recipe.json <output folder>
Builds each part (box / cylinder / cone / sphere / torus / text), applies array, mirror, cuts (boolean difference),
bevel and subdivision, joins parts of the same "group" into one piece, checks which pieces run into each other,
exports one STL per piece + a GLB of everything, renders a picture, and prints "RESULT: {json}". 1 unit = 1 mm."""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
recipe = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
OUT = Path(argv[1])
scene = bpy.context.scene
coll = scene.collection


def say(s: str) -> None:
    print(s, flush=True)


def rgba(h: str) -> tuple:
    h = h.lstrip("#")
    lin = lambda c: (c / 255) ** 2.2  # noqa: E731 — sRGB -> linear for Blender colours
    return (lin(int(h[0:2], 16)), lin(int(h[2:4], 16)), lin(int(h[4:6], 16)), 1.0)


for o in list(bpy.data.objects):  # factory scene: remove the cube, camera and light
    bpy.data.objects.remove(o, do_unlink=True)
origin = bpy.data.objects.new("world origin", None)  # the mirror centre
coll.objects.link(origin)


def mesh_for(p: dict, name: str):
    bm = bmesh.new()
    s = p["shape"]
    if s == "box":
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=Vector(p["size"]), verts=bm.verts)
    elif s in ("cylinder", "cone"):
        r1, r2 = p["radius"], (p["radius"] if s == "cylinder" else p.get("radius2", 0.01))
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=96 if max(r1, r2) > 20 else 48,
                              radius1=r1, radius2=max(r2, 0.01), depth=p["depth"])
    elif s == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=p["radius"])
    elif s == "torus":
        R, r, n1, n2 = p["major"], p["minor"], 96, 32
        ring = [[bm.verts.new(((R + r * math.cos(b)) * math.cos(a), (R + r * math.cos(b)) * math.sin(a), r * math.sin(b)))
                 for b in (2 * math.pi * j / n2 for j in range(n2))] for a in (2 * math.pi * i / n1 for i in range(n1))]
        for i in range(n1):
            for j in range(n2):
                bm.faces.new((ring[i][j], ring[(i + 1) % n1][j], ring[(i + 1) % n1][(j + 1) % n2], ring[i][(j + 1) % n2]))
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def make(p: dict, name: str):
    if p["shape"] == "text":
        cu = bpy.data.curves.new(name, "FONT")
        cu.body, cu.size, cu.extrude = p["text"], p["font_size"], p["depth"] / 2
        cu.align_x, cu.align_y = "CENTER", "CENTER"
        ob = bpy.data.objects.new(name, cu)
    else:
        ob = bpy.data.objects.new(name, mesh_for(p, name))
    coll.objects.link(ob)
    ob.location = p["location"]
    ob.rotation_euler = [math.radians(a) for a in p.get("rotation", [0, 0, 0])]
    return ob


solvers = [e.identifier for e in bpy.types.BooleanModifier.bl_rna.properties["solver"].enum_items]
parts = recipe["parts"]
objs, cutters = [], []
for i, p in enumerate(parts):
    say(f"PROGRESS: {i}/{len(parts)} {p['name']}")
    ob = make(p, p["name"])
    if p.get("array") and p["array"]["count"] > 1:
        m = ob.modifiers.new("copies", "ARRAY")
        m.count, m.use_relative_offset, m.use_constant_offset = p["array"]["count"], False, True
        m.constant_offset_displacement = p["array"]["offset"]
    if p.get("mirror"):
        m = ob.modifiers.new("mirror", "MIRROR")
        m.use_axis = [p["mirror"] == a for a in "xyz"]
        m.mirror_object = origin
    for k, c in enumerate(p.get("cut") or []):
        co = make(c, f"{p['name']} cut {k + 1}")
        co.hide_render, co.display_type = True, "WIRE"
        cutters.append(co)
        m = ob.modifiers.new(f"cut {k + 1}", "BOOLEAN")
        m.operation, m.object = "DIFFERENCE", co
        m.solver = "MANIFOLD" if "MANIFOLD" in solvers else "EXACT"
    if p.get("bevel", 0) > 0:
        m = ob.modifiers.new("rounded edges", "BEVEL")
        m.width, m.segments, m.limit_method = p["bevel"], 3, "ANGLE"
    if p.get("subdivide"):
        m = ob.modifiers.new("rounder", "SUBSURF")
        m.levels = m.render_levels = p["subdivide"]
    objs.append((p, ob))

dg = bpy.context.evaluated_depsgraph_get()


def baked(ob):
    """World-space mesh with every modifier applied (a failed MANIFOLD cut is retried with the EXACT solver)."""
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=False, depsgraph=dg)
    if not len(me.polygons) and any(m.type == "BOOLEAN" for m in getattr(ob, "modifiers", [])):
        for m in ob.modifiers:
            if m.type == "BOOLEAN":
                m.solver = "EXACT"
        dg.update()
        bpy.data.meshes.remove(me)
        me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg), preserve_all_data_layers=False, depsgraph=dg)
    me.transform(ob.matrix_world)
    return me


groups: dict[str, list] = {}
for p, ob in objs:
    groups.setdefault(p["group"], []).append((p, ob))
bodies = []
for gname, members in groups.items():
    bm = bmesh.new()
    for p, ob in members:
        me = baked(ob)
        if p.get("smooth") or p.get("subdivide") or p["shape"] in ("sphere", "torus"):
            for poly in me.polygons:
                poly.use_smooth = True
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
    me = bpy.data.meshes.new(gname)
    bm.to_mesh(me)
    open_edges = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    bm.free()
    body = bpy.data.objects.new(gname, me)
    first = members[0][0]
    mat = bpy.data.materials.new(gname)
    hx = first["color"].lstrip("#")
    srgb = (int(hx[0:2], 16) / 255, int(hx[2:4], 16) / 255, int(hx[4:6], 16) / 255, 1.0)
    mat.diffuse_color = srgb  # the viewport / Workbench colour is shown as given (linear made it much darker)
    mat.metallic, mat.roughness = first.get("metal", 0), 0.45
    try:  # the node material (EEVEE / GLB); Workbench uses diffuse_color
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = rgba(first["color"])
        bsdf.inputs["Metallic"].default_value = first.get("metal", 0)
        bsdf.inputs["Roughness"].default_value = 0.45
    me.materials.append(mat)
    body.color = srgb
    coll.objects.link(body)
    bodies.append({"obj": body, "name": gname, "reference": bool(first.get("reference")), "open_edges": open_edges,
                   "color": first["color"]})
for _, ob in objs:
    bpy.data.objects.remove(ob, do_unlink=True)
for co in cutters:
    bpy.data.objects.remove(co, do_unlink=True)
dg = bpy.context.evaluated_depsgraph_get()

# fit check: do any two pieces run into each other? (surfaces crossing; a piece fully inside another isn't seen)
say(f"PROGRESS: fit {len(bodies)}")
clashes = []
trees = [BVHTree.FromObject(b["obj"], dg) for b in bodies]
boxes = []
for b in bodies:
    vs = [v.co for v in b["obj"].data.vertices]
    boxes.append((Vector([min(v[i] for v in vs) for i in range(3)]), Vector([max(v[i] for v in vs) for i in range(3)])) if vs
                 else (Vector((0, 0, 0)), Vector((0, 0, 0))))
for i in range(len(bodies)):
    for j in range(i + 1, len(bodies)):
        (a0, a1), (b0, b1) = boxes[i], boxes[j]
        if any(a1[k] < b0[k] or b1[k] < a0[k] for k in range(3)):
            continue
        n = len(trees[i].overlap(trees[j]))
        if n:
            clashes.append({"a": bodies[i]["name"], "b": bodies[j]["name"], "crossing_faces": n})

# export: one STL per piece (mm), a GLB of everything (in metres, for viewers)
out_bodies = []
for k, b in enumerate(bodies):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    b["obj"].select_set(True)
    bpy.context.view_layer.objects.active = b["obj"]
    stl = OUT / f"body{k}.stl"
    bpy.ops.wm.stl_export(filepath=str(stl), export_selected_objects=True, global_scale=1.0, apply_modifiers=True)
    lo, hi = boxes[k]
    tris = sum(len(p.vertices) - 2 for p in b["obj"].data.polygons)
    out_bodies.append({"name": b["name"], "stl": str(stl), "triangles": tris, "reference": b["reference"],
                       "size_mm": [round(hi[i] - lo[i], 1) for i in range(3)], "open_edges": b["open_edges"],
                       "color": b["color"]})
glb = OUT / "model.glb"
try:
    root = bpy.data.objects.new("model (m)", None)
    coll.objects.link(root)
    for b in bodies:
        b["obj"].parent = root
    root.scale = (0.001, 0.001, 0.001)
    dg.update()
    for o in bpy.context.view_layer.objects:
        o.select_set(o.type == "MESH")
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=False)
    root.scale = (1, 1, 1)
    for b in bodies:
        b["obj"].parent = None
    dg.update()
except Exception as e:  # noqa: BLE001 — the STLs matter more
    say(f"glb failed: {e}")
    glb = None

# a rendered picture: Workbench (fast, reliable in the background), studio light, the pieces' colours
render = OUT / "render.png"
try:
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light, sh.color_type, sh.show_shadows, sh.show_cavity = "STUDIO", "MATERIAL", True, True
        scene.display.render_aa = "8"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE"
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        coll.objects.link(sun)
    scene.world = scene.world or bpy.data.worlds.new("world")
    scene.world.color = (0.86, 0.88, 0.86)
    lo = Vector([min(bx[0][i] for bx in boxes) for i in range(3)])
    hi = Vector([max(bx[1][i] for bx in boxes) for i in range(3)])
    c, diag = (lo + hi) / 2, max((hi - lo).length, 1.0)
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    coll.objects.link(cam)
    d = Vector((0.9, -1.6, 0.85)).normalized()  # a product shot from front-right-above that FITS the model
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
except Exception as e:  # noqa: BLE001 — the app draws its own preview then
    say(f"render failed: {e}")
    render = None

result = {"name": recipe.get("name") or "Blender model", "bodies": out_bodies, "collisions": clashes,
          "checked_pairs": len(bodies) * (len(bodies) - 1) // 2, "engine": f"Blender {bpy.app.version_string}"}
if len(out_bodies) == 1:
    result.update({"stl": out_bodies[0]["stl"], "triangles": out_bodies[0]["triangles"], "size_mm": out_bodies[0]["size_mm"]})
if render and render.exists():
    result["render"] = str(render)
if glb and Path(glb).exists():
    result["glb"] = str(glb)
say("RESULT: " + json.dumps(result))
