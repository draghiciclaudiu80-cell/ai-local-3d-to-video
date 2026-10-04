---
name: Proven designs (what already works)
description: The catalog of tested, fit-checked designs the app can build — when to use each one, its options, what to buy, and how to combine them — so the AI starts from something that works instead of guessing.
triggers: proven, ready made, ready-made, template, tested design, example, tutorial, nerf, blaster, dart, drum, magazine, revolver, pistol, pump, gear, gears, handcuffs, bolt, nut, thread, jar, robot hand, robotic, prosthetic, exoskeleton, brace, knee, elbow, engine, drone, fpv, quadcopter, grenade
for: 3d, code, chat
---
RULE: if one of these fits the request, USE IT (PicoGK builds it with every gap right and the fit check proves nothing
collides). Change it with its options. Only design from scratch when nothing here fits. With "Python code" on, say
"in python code" and the app translates the proven design into Blender Python first — then change that code.

THE CATALOG (template — use it for — main options — to buy)
- dart_blaster — Nerf / foam-dart pistol, spring plunger, trigger + sear — dart_diameter 13, barrel_length, stroke — spring ~20x100 mm, O-ring, 3 mm pin, rubber band
- revolver_blaster — 6-shot revolver blaster (blaster + revolving cylinder + click detent) — none unless asked — + 6 mm rod axle
- drum_blaster — TOMMY GUN / drum-fed blaster: the drum turns one dart at EVERY SHOT (index bar on the plunger pushes a ratchet on the drum), finned barrel, front grip, stock — darts 16, barrel_length 150, stroke 50 — spring ~24x100, O-ring, 3 mm pin, rubber band, 6 mm rod
- mag_pistol — MAGAZINE-FED blaster: bolt (11 mm air tube on a nozzle) pushes the top dart from the magazine into the barrel, flexure magazine catch — darts 8, dart_length 72 (45 = half-length), barrel_length — the dart_blaster's parts + 2 magazine springs, O-ring for the nozzle
- dart_magazine — spring-loaded stick magazine: feed lips (0.45 mm over the dart), follower, 2 springs, baseplate, catch notch — darts 10 (4-13), dart_length 72 — 2 springs ~9 x 70 mm, M2 screw
- fidget_spinner — FIDGET / hand spinner (also typed "figit spiner"): body with 2-6 arms around a 608 bearing, lobes hold 608 bearings as weights (or solid printed lobes), two press-in caps that touch only the centre bearing's inner ring — arms 3, weights "bearings" | "none", arm_length 30 — 608 bearings (22 x 8 x 7 mm): 1 + one per arm
- cap_grenade — airsoft-style IMPACT noise grenade for TOY ring caps only: weighted striker on a light spring, pull pin with a ring, screw-off bottom plug holds the cap ring, screw-off top — diameter 44, height 72 — a weak spring, an M8 bolt (weight), toy ring caps
- fpv_drone — FPV quad frame 3/5/7 inch: arms + motor pads (12x12 M2 / 16x16 M3), 20x20 or 30.5x30.5 stack holes, 25° TPU camera mount, antenna mount, strap slots, optional prop guards; 7" = bolt-on arms — props 5, guards false — motors, props, FC/ESC stack, camera, VTX, battery, standoffs
- drum_magazine — rotating drum for 8-24 darts, feed + exit hole at the top chamber, flexure click — darts 12, dart_diameter 13, length 75 — 6 mm rod / M6 bolt
- centrifugal_pump — small water pump for a DC motor — impeller_diameter 40, blades 6, motor_diameter 20.4 — 130 motor, 4 x M3
- gear_pair — two spur gears on a plate at the exact centre distance — module 1.5, teeth1, teeth2, thickness — 2 steel rods
- box_with_lid — simple box, sliding-lip lid — length, width, height, wall — nothing
- threaded_jar — jar with a SCREW lid (round thread) — diameter (inside) 70, height 80, pitch 4 — nothing
- bolt_and_nut — printable bolt + nut that really screw — diameter 16, length 40, pitch ~d/4, clearance 0.3 — nothing
- handcuffs — two hinged cuffs, lock pins, chain — wrist_diameter 60 — pins
- robot_hand — tendon hand: palm, 4 fingers x 3, thumb x 2, pin joints — scale 1.0, pin_diameter 3 — 3 mm pins, fishing line, elastic, servos
- demo_engine — hand-cranked single-cylinder engine model: piston, connecting rod, 2-piece crankshaft, flywheel, window to watch the piston (a printed engine can't burn fuel) — bore 30, stroke 30, rod_length 60 — 5 mm wrist pin, 8 x M3 x 12
- exo_elbow — exoskeleton / brace joint for elbow or knee, 0-120° stop — arm_diameter 90, cuff_length 110, max_bend 120 — M6 bolt + nyloc, velcro, foam

COMBINING THEM (tutorial ideas)
- A drum-fed blaster that indexes by itself: drum_blaster (don't combine dart_blaster + drum_magazine by hand).
  Why the plunger turns the drum and not the trigger: a finger moves a printed trigger only 2-5 mm, the plunger 50 mm.
- A powered hand: robot_hand + 5 servos pulling the tendons under the palm (MG996R, a servo horn per finger).
- A powered brace: exo_elbow + a servo or linear actuator between the upper and lower bar.
- A gearbox: gear_pair twice (12->24, then 12->24 on the same shaft = 4:1).
- Screwing parts together: bolt_and_nut sizes 12-20 mm for printed bolts; for small screws use metal + heat-set inserts.

WHY THEY WORK (the same rules for your own designs)
Moving parts 0.4-0.5 mm apart, pins in holes 0.4 mm bigger, printed threads round and coarse with 0.3 mm play, parts
you buy shown as "(buy)" in place, every part printable flat without supports, and the fit check at 0 collisions.
