---
name: CNC machining
description: Designing parts for CNC milling / routing (wood, MDF, plastics, aluminium), tools, feeds and speeds, workholding and G-code basics.
triggers: cnc, mill, milling, milled, router, routing, endmill, end mill, v-bit, vbit, flat end, ball end, g-code, gcode, spindle, feeds, speeds, feed rate, chipload, chip load, pocket, profile cut, carve, carving, engrave, fixture, clamp, workholding, frezare, freza, frezat
for: 3d, chat, code
---
Design for CNC (2.5D router / mill):
- Inside corners can't be sharp: their radius = the tool radius (a 6 mm cutter leaves R3). Add "dog-bone" or "T-bone" relief where a square part must fit into a pocket.
- Outside corners can be sharp. Chamfers need a V-bit; fillets on the top edge need a round-over or ball-end tool.
- Pocket depth <= 3x the tool diameter (deeper = longer, weaker tools). Slots at least the tool width; thin walls >= 1.5 mm in aluminium, >= 3 mm in wood.
- Everything is cut from the top: no undercuts, holes and pockets straight down. Two-sided parts need registration pins / holes for flipping.
- Keep tabs (2-4 small bridges, ~1-2 mm thick) so a profiled part doesn't fly loose at the end.
- Standard tools: 3.175 mm (1/8"), 6 mm, 6.35 mm (1/4") flat end mills; 60/90 degree V-bits; ball ends for 3D surfaces.
Feeds and speeds (use the Materials plugin: it turns FreeCAD's cutting speeds into RPM and feed):
- RPM = cutting speed (m/min) x 1000 / (pi x tool diameter mm), capped at the spindle's maximum.
- Feed (mm/min) = RPM x flutes x chip load. Too small a chip load RUBS and burns (wood) or work-hardens; too big chatters or breaks the tool.
- Starting chip loads (per tooth, carbide): MDF / softwood ~1.5 % of the diameter, hardwood ~1.2 %, plastics ~1 %, aluminium ~0.4 % (with lubrication / air, 1 flute helps chip evacuation), steel only on rigid mills.
- Depth per pass: wood / MDF ~0.5-1x diameter, aluminium on hobby machines 0.1-0.25x diameter. Plunge at ~30 % of the feed or ramp in.
G-code basics: G21 mm, G90 absolute, G0 rapid move, G1 cutting move with F feed, G2 / G3 arcs, M3 S<rpm> spindle on, M5 off. Zero (origin) usually top-left or centre of the stock top. Always simulate the toolpath before cutting and keep a hand near the stop button.
Safety: eye and ear protection, dust extraction for MDF (toxic dust), never leave a running router alone, clamps away from the toolpath.
