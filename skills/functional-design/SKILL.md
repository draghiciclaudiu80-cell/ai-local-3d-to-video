---
name: Functional 3D design
description: How to plan and build WORKING printable devices (moving parts, mechanisms, assemblies) — plan first, then parts, gaps and a fit check.
triggers: working, functional, fictional, fully functional, mechanism, device, assembly, moving part, moving parts, that works, from ground up, from scratch, multi-part, parts that fit, print in place, fonctional, funcțional, functional, mecanism, care merge
for: 3d
---
Work like an engineer, in this order:
0. REQUIREMENTS of THIS device only: what goes in / comes out, sizes, loads, what moves and how far, what must not
   break, slip or leak (a robot arm: reach, payload, number of joints, motors; a pump: flow, pressure, seals). Never copy
   another device's list — a water tap's hot / cold inlets don't belong in an arm.
1. JOB: one sentence — what must it do, what moves, what the user holds / loads / presses.
2. MECHANISM: how it works step by step (e.g. "pull knob -> spring compresses -> tooth catches piston -> trigger lowers tooth -> piston pushes air").
3. PARTS: every separate printed piece with its size in mm and its position (X forward, Z up, 0,0,0 = the main axis / centre). Things you BUY (springs, screws, rods, O-rings, motors, bearings) are "reference" bodies — shown grey, not printed.
4. GAPS: moving parts 0.4 mm apart (sliding, turning), glued / pressed parts 0.2-0.3 mm, print-in-place 0.4-0.5 mm. Never let two bodies overlap — the fit check reports every collision.
5. PRINTABILITY: walls >= 1.6 mm (2.4 for pressure / load), pins >= 3 mm, overhangs <= 45 degrees or add a chamfer, flat face down, holes that must be round print vertical. Text, threads < M6 and springs are better bought.
6. CHECK: after building, read the fit check. A collision = move one of the two parts or add the gap; never "fix" by overlapping.
7. SEALS (only when air or liquid is involved): where each O-ring sits, what surface it presses on, how much it is
   squeezed (~15-25 %), and how it gets in after printing. MANUFACTURING: print orientation of each part, supports,
   assembly order. Only say a model is shown when the 3D tool really built it.

Use a READY-MADE WORKING DESIGN when one fits (they are tested): dart_blaster (spring plunger foam-dart pistol), revolver_blaster (6-shot revolving cylinder), centrifugal_pump, gear_pair, box_with_lid, handcuffs, robot_arm (4 servos: base, shoulder, elbow, claw — options reach, payload), robot_hand, fidget_spinner (608 bearings). Change them with options instead of inventing a worse copy.

Recipe patterns (PicoGK):
- One printed piece = one body: {"name": "lid", "parts": [...]}. Several pieces: {"template": "none", "bodies": [...]}.
- A hole = a "subtract" part AFTER the shape it cuts. A hollow tube = shape "tube" (radius = outside, wall).
- Cylinders / tubes / cones / helixes point up +Z from their "center" (the base); rotate [0,90,0] points them along +X.
- A pin through two parts: hole radius = pin radius + 0.2 (turning) in both, the pin a separate body (or reference if bought).
- Copies: "repeat" {"count": 6, "angle": 360, "axis_point": [x,y,z]} (around Z) or {"count": 4, "step": [dx,dy,dz]} (a row).
- Keep a device under ~15 bodies; name every body for what it is ("trigger", "lid", "axle (buy)").

When something is unknown (a standard size, how a mechanism works), say what you assume in the plan ("assumes 12.7 mm Nerf Elite darts") so the user can correct it.
