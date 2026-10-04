---
name: Gears, springs and motion
description: Gears, shafts, bearings, cranks, cams, wheels, pumps and motors — the rules for parts that turn and move.
triggers: gear, gears, gearbox, pulley, belt, spring, crank, cam, wheel, wheels, axle, shaft, bearing, motor, rotate, turning, pump, impeller, fan, propeller, ratchet, pawl, angrenaj, roata, motor
for: 3d, chat
---
Gears (printed spur gears, involute 20 degrees):
- module 1-2 mm for small printers (1.5 is a good default); teeth >= 12 on the small gear.
- Centre distance = module x (teeth1 + teeth2) / 2 — exactly. Ratio = teeth2 / teeth1.
- Backlash ~0.15 mm (the gear shape has it); gear thickness >= 3 x module; bore = shaft + 0.2 mm (turning) or a D-flat for a motor.
- Use the ready-made "gear_pair" (module, teeth1, teeth2, thickness, shaft_diameter) — it places them at the right distance.
Shafts and bearings: steel rods / screws are better than printed shafts. Bearing seats: 608 bearing = 22 mm outer, 7 mm thick, 8 mm bore; press fit 0.1 mm tighter.
Springs: buy compression springs (printed springs in PLA lose force fast). Leave space for the spring's solid length (turns x wire diameter).
Ratchet + pawl: teeth like a saw (one steep side), pawl pushed by a flexure or rubber band; 6-12 teeth for indexing a cylinder.
Cranks / cams: pin radius >= 2 mm; cam lift = difference between largest and smallest radius; follower 0.4 mm gap.
Pumps: use "centrifugal_pump" (impeller_diameter, blades, shaft_diameter, inlet/outlet, motor_diameter) — impeller 0.5 mm from the housing, the outlet leaves tangentially.
Wheels: tyre from TPU or an O-ring in a groove; hub with a set-screw nut trap.
Motors: 130-size DC motor = 20.4 mm wide (flat sides 15 mm), 2 mm shaft; N20 gear motor = 12 x 10 mm, 3 mm D-shaft. Always leave 0.3 mm around a bought part.
