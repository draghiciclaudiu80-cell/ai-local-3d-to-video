---
name: Foam-dart blasters
description: Spring-plunger Nerf-style blasters — pistols and revolvers: dart sizes, air volume, catch and trigger, revolving cylinders.
triggers: nerf, blaster, dart, darts, foam, plunger, revolver, pistol, dart gun, toy gun, strongarm, cylinder blaster, catch, sear
for: 3d, chat
---
Numbers that work (Nerf Elite darts):
- Dart 12.7 mm wide, ~72 mm long. Barrel / chamber bore 13.0-13.2 mm; barrel length 80-150 mm.
- Air: plunger volume must be about 2x the air the dart pushes out (bore area x the distance the dart travels). Plunger tube 26-35 mm inside, stroke 40-60 mm. Too little air = weak shots.
- Piston: 0.4 mm smaller than the tube, with an O-ring groove (buy the O-ring). Spring: ~20 mm wide, 100 mm long, 1.0-1.4 mm wire (buy).
- Catch (sear): a tooth that rises in front of the primed piston; the trigger pivots on a 3 mm pin and pulls the tooth down; a rubber band or small spring pushes it back up.
- Seal: keep the air path short (nozzle <= 0.4 mm from the next part); every gap leaks.

Revolver (revolving cylinder):
- 6 chambers of 13.2 mm on a pitch circle ~16 mm from the axle; cylinder ~50 mm wide, ~75 mm long (whole darts inside). The TOP chamber lines up with the plunger nozzle behind and the barrel in front; the axle (6 mm steel rod) sits below the bore.
- Indexing: simplest = turn by hand with a detent (a printed flexure in the frame with a nub clicking into 6 dimples on the cylinder face, dimple 0.4 mm bigger than the nub). Auto-indexing (a pawl pushed by the priming stroke on a 6-tooth ratchet) is harder — say so and offer it as a next step.
- Load darts from the front of the cylinder; the frame must leave the lower / side chambers open.

Use the ready-made designs: "dart_blaster" (single shot) and "revolver_blaster" (6-shot). They are tested — give NO options unless the user asked for a size. Options if asked: dart_diameter (the dart, 12.7-13), barrel_length (mm), stroke (mm), cylinder_length (revolver, mm), chamber_diameter = the inside of the AIR / plunger tube (26-35 mm) — NOT the dart chamber. Only design from scratch when the user wants something they can't do.

Safety: a toy — foam darts only, no hard projectiles, don't aim at faces. It doesn't need to look like a real firearm (bright colours are good).
