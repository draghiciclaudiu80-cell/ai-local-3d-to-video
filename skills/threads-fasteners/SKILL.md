---
name: Threads, screws and fasteners
description: Numbers that work in real prints — printed threads, holes for metal screws, heat-set inserts, nut traps, counterbores, bosses — so screwed parts fit the first time.
triggers: screw, screws, bolt, bolts, nut, nuts, thread, threads, threaded, insert, inserts, heat-set, heat set, fastener, fasteners, m2, m3, m4, m5, m6, m8, nut trap, countersink, counterbore, surub, suruburi, piulita, filet
for: 3d, code, chat
---
PRINTED THREADS (the thread itself is printed)
- Use ROUND or trapezoid threads, coarse: pitch at least 1.5 mm and about diameter / 4. Fine metric threads (M3-M6) do not print.
- Play: 0.3 mm on the radius (0.2 for PETG at 0.12 mm layers, 0.4 if it binds). Chamfer both starts 45°.
- Diameter 10 mm and up. Print threads standing up (axis vertical), 0.2 mm layers or finer, 3+ walls.
- Ready-made: bolt_and_nut and threaded_jar (PicoGK), or ask for them "in python code".
- Blender code: bolt = cylinder(rc) + helix(rc, w, len, turns); nut = cut cylinder(rc + 0.3) + cut helix(rc, w + 0.3)
  on the same path (same start, whole turns). w = pitch / 4.

METAL SCREWS IN PRINTED PARTS (hole sizes in mm)
- Clearance (the screw passes freely): M2 2.4 · M2.5 2.9 · M3 3.4 · M4 4.5 · M5 5.5 · M6 6.6 · M8 8.6
- Self-tapping into plastic (screw cuts its thread): M2 1.7 · M2.5 2.2 · M3 2.6 · M4 3.5 · M5 4.3 — 3x d deep
- Heat-set inserts (brass, pressed in with a soldering iron): M2 3.2 · M2.5 3.6 · M3 4.0-4.2 · M4 5.6 · M5 6.4, hole depth = insert length + 1
- Nut traps (hexagon across flats + 0.3): M3 5.8 · M4 7.3 · M5 8.3 · M6 10.3 · M8 13.3; pocket depth = nut height + 0.3 (M3 2.7)
- Counterbore for socket heads: M3 6.5 dia x 3.2 deep · M4 8 x 4.2 · M5 9.5 x 5.2 · M6 11 x 6.2
- Countersink (flat heads): 90°, head diameter + 0.4.

STRENGTH AND PRINTING
- Around every screw: wall at least 2.5 mm, a boss outer diameter 2.5 x d. 4 walls / perimeters where screws go.
- Horizontal holes over 5 mm: use a teardrop (a 45° point at the top) so they print without supports.
- Load along the layers breaks them: screw INTO the layers (screw axis vertical) where you can.
- Replace a printed thread with an insert when it is opened and closed often or carries real load.
