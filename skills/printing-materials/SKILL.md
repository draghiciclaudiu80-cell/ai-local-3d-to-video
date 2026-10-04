---
name: 3D printing and materials
description: Which material, slicer settings, supports, orientation and strength — practical answers for printing the parts.
triggers: pla, petg, tpu, abs, asa, nylon, infill, slicer, cura, prusaslicer, orca, print supports, tree supports, layer height, nozzle, print bed, heated bed, bed adhesion, bed temperature, warping, print settings, how to print, what material, print strength, part strength, filament
for: chat, 3d
---
Materials: PLA = easy, stiff, brittle, softens at ~55 C (not for cars in summer). PETG = tougher, bends before breaking, good for clips / flexures / outdoor. TPU = rubbery (tyres, grips, seals). ABS/ASA = heat + UV resistant, needs an enclosure. Nylon = strongest for gears, absorbs water.
Settings that work (0.4 mm nozzle): layer 0.2 mm (0.12 for fine parts), 3-4 walls for strong parts, infill 15-20 % (40 %+ or 100 % for small loaded parts like pins, triggers, gears), print speed normal.
Strength: parts are weakest BETWEEN layers — orient so the load runs along the layers (a pin or a clip lying flat, not standing up). More walls add more strength than more infill.
Supports: avoid them by design (chamfers, split parts, flat faces down); when needed use tree supports; print-in-place joints need no supports inside the gaps.
Holes print ~0.2 mm small: design them 0.2 mm bigger or drill them. First layer squish makes the bottom 0.1-0.2 mm wider (elephant foot) — add a 0.4 mm chamfer at the bottom edge of close-fitting parts.
Test print first: print one joint / one gap test before a big device.
