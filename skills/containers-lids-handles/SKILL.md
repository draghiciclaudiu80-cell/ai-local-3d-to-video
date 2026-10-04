---
name: Containers, lids and handles
description: How to design printable pots, boxes, jars, cups and bins — real hollow insides, lids that fit and come off, handles that are one piece with the body, and the right sizes.
triggers: pot, pots, box, boxes, jar, cup, mug, bowl, vase, container, bin, planter, bucket, basket, canister, tin, case, tray, organizer, organiser, holder, lid, lids, cover, cap, handle, handles, handels, knob, cutie, borcan, oala, ghiveci, capac, maner
for: 3d, code, chat
---
WHAT THE USER MEANS
- "20 cm deep / high / tall" = the OUTSIDE height: 200 mm. "15 cm (exterior) diameter" = outside width 150 mm (radius 75).
- "10 x 20 cm and 10 cm high" = 100 x 200 mm footprint, 100 mm high. Always convert cm to mm (x 10) before anything else.
- A pot / box / jar / cup is HOLLOW with an OPEN top (unless they say "solid"). A lid is a SEPARATE piece that comes off.

GOOD NUMBERS (PLA / PETG)
- Walls 2-3 mm (big pots 3 mm), bottom 2-3 mm. Fillet / bevel the outside edges 1-2 mm.
- Lid: plate 3 mm + a lip 5-8 mm deep that goes INTO the opening with 0.3-0.5 mm play all round. A knob or a grip on top.
- Handles: 5-8 mm thick, 20-30 mm reach, at 2/3 of the height. They are ONE piece with the body (merged), never loose parts.
- Print the body upright, the lid upside down (plate on the bed). Nothing needs supports then.

BLENDER CODE (Python code ON) — use the whole-feature blocks, they are always right:
  H, R, WALL = 200, 75, 3                 # a round pot
  pot = cylinder(R, H, loc=(0, 0, H / 2))
  hollow(pot, WALL)                       # open top, walls 3 mm (never a centred cutter: that seals it)
  add_handle(pot, "+x"); add_handle(pot, "-x")
  cover = make_lid(pot, WALL)             # separate, fits the opening, sits above the pot
  part(pot, "pot"); part(cover, "lid")
  For a rectangular box: body = box(W, D, H, loc=(0, 0, H / 2)), then the same hollow / make_lid / part lines.
  Rounded box: bevel(body, 3) BEFORE hollow(). Dividers: box walls inside, join()ed to the body after hollow().

CHECK BEFORE "DONE": the app measures height / diameter / footprint, whether the inside is open and hollow, whether a
separate lid exists, and whether pieces run into each other. Fix what it names; never claim a lid or a hollow inside the
parts list doesn't show.
