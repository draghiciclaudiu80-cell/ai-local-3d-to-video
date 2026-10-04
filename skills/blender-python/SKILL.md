---
name: Blender Python (code mode)
description: How to write Blender Python for Local AI's "Python code" mode — the ready building blocks, the rules, worked examples and the errors that happen most.
triggers: blender python, bpy, bmesh, python code, blender script, write code, script it
for: code, chat
---
You write ONE Python script. The app runs it in Blender 5.2 (background), then exports every visible mesh as a part,
checks the fit, measures it, renders a picture and shows it to the user. Units: 1 = 1 mm. Z is up. FRONT = -Y.
SIZES: always millimetres. 1 cm = 10 mm (20 cm deep = 200). "Deep" / "high" / "tall" = the Z size.

READY BUILDING BLOCKS (already defined — no import needed; they return the object):
  box((x, y, z), loc=(0,0,0), rot=(0,0,0), bevel=0)   # centred on loc; box(x, y, z, loc=…) works too
  cylinder(radius, depth, loc=..., rot=..., bevel=0)  # along Z, centred; rot=(0,90,0) = along X. radius = diameter / 2
  cone(radius1, radius2, depth, loc=...)   sphere(radius, loc=...)   torus(major, minor, loc=..., rot=...)
  cut(target, *cutters) -> holes / pockets        join(target, *others) -> merge into ONE solid (others are used up)
  move(obj, x, y, z)  rotate(obj, x, y, z) (degrees)  copy(obj)  array(obj, count, (dx, dy, dz))  mirror(obj, "x")
  bevel(obj, width_mm)  smooth(obj)  color(obj, "#rrggbb")  part(obj, "name", group=None, reference=False)
PICOGK'S SHAPES (same sizes as PicoGK; all centred on loc):
  tube(radius, wall, depth, loc, rot)       gear(teeth, module, height, bore=0, loc, rot)   # 2 gears mesh at (t1+t2) x module / 2
  helix(radius, wire, height, turns, loc)   # a spring; on a core cylinder of the same radius = a round THREAD
  extrude([(x, y), ...], height, loc, rot)  revolve([(r, z), ...], loc)   rod(start, end, radius)   intersect(a, b)
  Thread that fits: bolt = cylinder(rc) + helix(rc, w); nut hole = cut cylinder(rc + 0.3) + cut helix(rc, w + 0.3) with
  the SAME start height and whole turns. Or ask for "a bolt and nut in python code": the app translates PicoGK's proven one.
WHOLE FEATURES (use these — they are always right):
  hollow(obj, wall)                 # a container: open top, walls `wall` mm, the outside stays the same
  make_lid(obj, wall)               # a SEPARATE fitting lid (plate + lip + knob), already placed above obj: don't move it
  add_handle(obj, "+x")             # a loop handle merged INTO obj (sides "+x", "-x", "+y", "-y"); no collision

ONE PIECE OR SEPARATE?
- Things that are one piece in real life (a pot and its handles, a table and its legs) -> ONE object: join() / add_handle().
- Things that come off or move (a lid, a door, a drawer) -> their OWN object and their own part(). NEVER join() a lid.
- Every final piece gets part(obj, "name") exactly once, with a different name.
- Separate pieces never overlap: leave 0.3-0.5 mm between them.

EXAMPLE — "a pot 20 cm deep, 15 cm diameter, with handles and a lid":
  H, R, WALL = 200, 75, 3
  pot = cylinder(R, H, loc=(0, 0, H / 2))
  hollow(pot, WALL)
  add_handle(pot, "+x")
  add_handle(pot, "-x")
  cover = make_lid(pot, WALL)
  part(color(pot, "#b5651d"), "pot")
  part(cover, "lid")
EXAMPLE — "a box with a lid 200 x 100 x 100 mm":
  W, D, H, WALL = 200, 100, 100, 2.5
  body = box(W, D, H, loc=(0, 0, H / 2))
  hollow(body, WALL)
  cover = make_lid(body, WALL, knob=False)
  part(body, "box")
  part(cover, "lid")

RULES (the app refuses code that breaks them):
- Only import bpy, bmesh, mathutils, math, random, itertools, collections — and you don't need to: all is ready.
- No names starting with "_", no files, no .format(), no bpy.ops (it fails in the background), no export / render.
- Never name a variable like a building block (pot = ..., not box = box(...)). Never define box() etc. yourself.
- cut() and join() use up their cutters / others: never use them again afterwards.
- A helper you made but didn't cut() / join(): obj.hide_render = True, or it becomes a part.
- Sizes as named variables at the top. Keep it short (under 60 lines). No placeholder lines — write real code.

COMMON ERRORS -> FIX:
- NameError -> a typo or used before it was made.     TypeError -> wrong arguments: check the block's signature.
- "'Object' object is not callable" -> a variable has a building block's name: rename it.
- "made no visible mesh objects" -> everything was cut away or joined into something hidden.
- "the pot is solid / closed" -> hollow(pot, WALL) (don't hollow by hand with a centred cutter: that seals it).
- "no separate lid" -> cover = make_lid(pot, WALL) and part(cover, "lid"); never join it.
- "handle runs into the pot" -> build it with add_handle(pot, side) instead of a separate part.
- A size is wrong -> set the variable at the top to the asked size (in mm).
Work like this: write it simply -> run -> read the LAST error line and its line number -> fix exactly that -> run again.
