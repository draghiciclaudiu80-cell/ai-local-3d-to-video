# 3D design with PicoGK — what you can ask

Just talk normally in the chat (typos are fine), or use **Create › 3D**. Everything is made on this PC.
The AI reads this plugin's instructions (plugin.json → "instructions") every time it designs — that's how it knows the
shapes, the ready-made devices and the engineering rules. Add your own knowledge there, or as a new plugin.

## Working devices (several printed parts + a fit check)
- "design a working nerf gun" / "a dart blaster with a 150 mm barrel" → spring-plunger blaster: air chamber, barrel,
  rear cap, plunger, trigger, frame (+ spring, O-ring, 3 mm pin to buy)
- "a small water pump for a 130 DC motor" → impeller, housing, lid (+ motor, 4 M3 screws)
- "two gears, 15 and 40 teeth, module 1" → gear pair on a base plate, at the exact center distance
- "a box with a lid, 100 x 60 x 40 mm" → box + lid with a sliding lip
- "an M16 bolt and nut that I can print" → round thread (prints without supports), 0.3 mm play, nut screwed on
- "a jar with a screw lid, 70 mm inside" → jar + lid with 2 turns of round thread
- "a nerf tommy gun" / "a blaster with a drum that turns when I pull the trigger" → drum blaster: stock, grip, trigger,
  air chamber, 16-dart drum that turns one dart at every shot (index bar + ratchet + detent), finned barrel, front grip
- "a magazine-fed nerf pistol" → the dart blaster + a bolt that feeds darts from a spring-loaded magazine + a magazine catch
- "a spring-loaded magazine for 10 darts" → stick magazine: body with feed lips, follower, 2 springs, baseplate
- "an FPV drone frame" / "a 3 inch cinewhoop with prop guards" → plates, arms, motor pads, stack holes, camera and
  antenna mounts, strap slots (+ motors, props, electronics to buy); every piece fits a 220 mm printer
- "an airsoft impact grenade with caps" → body, weighted striker, pull pin, screw-off plug for a toy ring cap (only toy
  caps: never primers or powder)
- "a drum magazine for 18 darts" → rotating drum, frame with feed / exit holes, clicking flexure detent (+ 6 mm axle)
- "a robotic hand" → palm, 4 fingers x 3 segments, thumb x 2, pin joints, fishing-line tendon channels (+ 3 mm pins)
- "a hand-cranked demo engine" / "a combustion engine model" → crankcase, finned cylinder with a window, piston,
  connecting rod, 2-piece crankshaft, flywheel, crank handle (tested turning at 6 crank angles: 0 collisions)
- "an exoskeleton elbow joint" / "a knee brace" → two cuffs, side hinge, 0-120° stop, strap slots (+ M6 bolt)
Each part is its own STL; "Download all parts (zip)". The **fit check** tests every pair of parts: ✓ = nothing collides.

## Single parts and your own devices
Shapes: sphere, box (rounded), cylinder, cone, tube, torus, extrude (a flat outline), revolve (a turned profile),
gear, helix (spring), rod (from → to), lattice, gyroid — each can be turned (rotate) and copied (around / in a row).
Examples: "a phone stand 80 mm wide", "a 60 mm cube with a 20 mm hole", "a plate with 6 holes on a circle",
"a spring 20 mm wide, 60 mm long", "a pulley with a 5 mm shaft hole".

## From LEAP 71's libraries (compiled into the engine, Apache 2.0)
- **ShapeKernel** — curved_pipe: "a pipe that bends up and to the left", manifolds, handles
- **LatticeLibrary** — lattice types body_centre / octahedron / random, TPMS infill diamond / primitive / lidinoid:
  "a 50 mm cube filled with a diamond lattice"
- **QuasiCrystals** — "a quasicrystal frame 30 mm"
- **RoverWheel** — "a rover wheel" (4 presets or random ones, ~250 mm)
- **HelixHeatX** — "LEAP 71's heat exchanger" (their fixed design)

## Changing a design
Right after a design: "make it taller", "add a hole", "make the walls thicker", "hollow it" — or press
**Edit in 3D** and change any part yourself (blueprint preview, then Build with PicoGK).

## Design rules the AI follows
walls ≥ 1.2 mm · moving parts 0.4–0.5 mm apart · glued / pressed parts 0.2–0.3 mm · holes 0.2 mm bigger
(3 mm pin → 3.2 mm hole) · no overhangs flatter than 45° · parts over 220 × 220 × 250 mm get split.
It's a first design to test-print: print one part, check the fit, then ask for changes.
