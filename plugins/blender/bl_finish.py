"""Runs INSIDE Blender (background): FINISHES a model another engine built (PicoGK: blasters, pumps, gears, lattices…).
    blender -b --factory-startup --disable-autoexec --python bl_finish.py -- finish.json <output folder>
finish.json = {"name", "bodies": [{"name", "stl" (a file in the app's media folder), "color" "#rrggbb", "reference"}]}
Imports each part's STL, gives it its colour, renders a picture (Workbench, studio light) and writes one GLB of the
whole model (in metres, for other 3D apps). Nothing is changed in the STL files. Prints "RESULT: {json}"."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
recipe = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
OUT = Path(argv[1])
scene = bpy.context.scene
coll = scene.collection


def say(s: str) -> None:
    print(s, flush=True)


def frame(cam, lo: Vector, hi: Vector) -> None:
    """A product shot from front-right-above that FITS the model (orthographic, 8 % margin, 4:3 picture)."""
    c, diag = (lo + hi) / 2, max((hi - lo).length, 1.0)
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


for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

bodies, lo, hi = [], Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
items = recipe["bodies"]
for i, b in enumerate(items):
    say(f"PROGRESS: {i}/{len(items)} {b['name']}")
    before = set(bpy.data.objects)
    bpy.ops.wm.stl_import(filepath=b["stl"])
    new = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not new:
        continue
    ob = new[0]
    ob.name = b["name"]
    hx = b["color"].lstrip("#")
    srgb = (int(hx[0:2], 16) / 255, int(hx[2:4], 16) / 255, int(hx[4:6], 16) / 255, 1.0)
    lin = tuple(c ** 2.2 for c in srgb[:3]) + (1.0,)
    mat = bpy.data.materials.new(b["name"])
    mat.diffuse_color = srgb
    mat.roughness = 0.45
    try:
        mat.use_nodes = True
    except (AttributeError, TypeError):
        pass
    bsdf = mat.node_tree.nodes.get("Principled BSDF") if mat.node_tree else None
    if bsdf:
        bsdf.inputs["Base Color"].default_value = lin
        bsdf.inputs["Roughness"].default_value = 0.45
    ob.data.materials.clear()
    ob.data.materials.append(mat)
    ob.color = srgb
    if len(ob.data.polygons) > 25000:  # the GLB and the picture don't need print detail (the STLs keep it)
        dm = ob.modifiers.new("lighter", "DECIMATE")
        dm.ratio = 25000 / len(ob.data.polygons)
    for v in ob.data.vertices:
        for k in range(3):
            lo[k], hi[k] = min(lo[k], v.co[k]), max(hi[k], v.co[k])
    bodies.append(ob)
if not bodies:
    say("RESULT: " + json.dumps({"error": "no parts could be imported"}))
    sys.exit(0)

say(f"PROGRESS: fit {len(bodies)}")
glb = OUT / "model.glb"
try:  # one GLB, in metres (glTF's unit)
    root = bpy.data.objects.new("model (m)", None)
    coll.objects.link(root)
    for ob in bodies:
        ob.parent = root
    root.scale = (0.001, 0.001, 0.001)
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=False, export_apply=True)
    root.scale = (1, 1, 1)
    for ob in bodies:
        ob.parent = None
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
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.rotation_euler = (math.radians(50), 0, math.radians(30))
        coll.objects.link(sun)
    scene.world = scene.world or bpy.data.worlds.new("world")
    scene.world.color = (0.86, 0.88, 0.86)
    c, diag = (lo + hi) / 2, max((hi - lo).length, 1.0)
    cam = bpy.data.objects.new("camera", bpy.data.cameras.new("camera"))
    coll.objects.link(cam)
    frame(cam, lo, hi)
    scene.camera = cam
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 960, 720, 100
    scene.render.filepath = str(render)
    bpy.ops.render.render(write_still=True)
except Exception as e:  # noqa: BLE001
    say(f"render failed: {e}")
    render = None

result = {"engine": f"Blender {bpy.app.version_string}"}
if render and render.exists():
    result["render"] = str(render)
if glb and Path(glb).exists():
    result["glb"] = str(glb)
say("RESULT: " + json.dumps(result))
