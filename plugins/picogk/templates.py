"""Ready-made FUNCTIONAL designs for the PicoGK plugin. Each returns an assembly recipe (bodies with parts) with real
clearances, so every part prints separately and the fit check proves nothing collides.
Coordinates: millimetres, Z up. X = forward for the blaster; Z = shaft axis for the pump and the gears.
Things you buy (steel spring, O-ring, pins, motor) are included as "reference" bodies so you can see where they go."""
import math

ALONG_X = [0, 90, 0]  # turns a cylinder / tube / helix (built along Z) to point forward (+X)
ALONG_Y = [-90, 0, 0]


def _o(opts: dict, key: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(opts.get(key, default))
    except (TypeError, ValueError):
        v = default
    return min(max(v, lo), hi)


def dart_blaster(o: dict) -> dict:
    """A spring-plunger foam-dart pistol: pull the knob back until the sear clicks, pull the trigger, the piston pushes
    the air through the barrel. Buy: a compression spring (~20 mm wide, ~100 mm long, 1.2 mm wire), an O-ring for the
    groove, a 3 mm pin (or M3 screw) for the trigger, and a small rubber band / spring to push the sear up."""
    if _o(o, "chamber_diameter", 26, 0, 99) < 22:  # an AI once gave the DART size (13.2) here: the spring can't fit
        o = {k: v for k, v in o.items() if k != "chamber_diameter"}
    dart = _o(o, "dart_diameter", 13.0, 8, 30)          # barrel bore (Nerf Elite darts are 12.7 mm)
    blen = _o(o, "barrel_length", 110, 40, 300)
    stroke = _o(o, "stroke", 50, 20, 120)
    cid = _o(o, "chamber_diameter", 26, 16, 50)          # air chamber inner diameter
    wall, slide, gap = 2.4, 0.4, 0.3                     # wall, moving-part clearance, glued-part gap
    rc, rco = cid / 2, cid / 2 + wall                    # chamber inner / outer radius
    spring_c, head = 30.0, 10.0                          # compressed spring length, piston thickness
    front = spring_c + head + stroke + 1                 # front wall of the chamber (x)
    rb = dart / 2 + 2                                    # barrel outer radius
    rod = 5.0
    pis0 = spring_c                                      # piston rear face when primed
    pivot = (pis0 + 6, 0, -(rco + 9))                    # trigger pivot
    tooth_x = (pis0 + head + 1, pis0 + head + 7)         # the sear tooth sits just in front of the primed piston
    cyl = lambda r, h, c, rot=ALONG_X, op="add", **k: {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": rot, **k}
    tube = lambda r, w, h, c, op="add": {"op": op, "shape": "tube", "radius": r, "wall": w, "height": h, "center": list(c), "rotate": ALONG_X}
    box = lambda size, c, op="add", **k: {"op": op, "shape": "box", "size": list(size), "center": list(c), **k}
    bodies = [
        {"name": "air chamber", "parts": [
            tube(rco, wall, front, (0, 0, 0)),
            cyl(rco, 6, (front, 0, 0)),                                         # front wall
            cyl(4, 8, (front - 1, 0, 0), op="subtract"),                        # air hole to the barrel
            tube(rb + gap + 2.5, 2.5, 16, (front + 6, 0, 0)),                   # barrel socket
            box((tooth_x[1] - tooth_x[0] + 2 * slide + 3, 8, 8), ((tooth_x[0] + tooth_x[1]) / 2 - 1, 0, -rc - 1.5), op="subtract"),  # sear slot
        ]},
        {"name": "barrel", "parts": [tube(rb, 2, blen, (front + 6.5, 0, 0))]},
        {"name": "rear cap", "parts": [cyl(rco, 6, (-6 - gap, 0, 0)), cyl(rod + 0.5, 8, (-7, 0, 0), op="subtract")]},
        {"name": "plunger", "parts": [
            cyl(rc - slide, head, (pis0, 0, 0)),                                                    # piston
            {"op": "subtract", "shape": "tube", "radius": rc, "wall": 2.0, "height": 3, "center": [pis0 + 3, 0, 0], "rotate": ALONG_X},  # O-ring groove
            cyl(rod, pis0 + stroke + 15, (-(stroke + 15), 0, 0)),                                   # rod (through the rear cap)
            cyl(12, 10, (-(stroke + 25), 0, 0), round=2),                                           # priming knob
        ]},
        {"name": "trigger", "parts": [
            box((tooth_x[1] - tooth_x[0], 6, 6), ((tooth_x[0] + tooth_x[1]) / 2, 0, -rc + 1.5)),    # sear tooth (catches the piston)
            {"op": "add", "shape": "rod", "from": [(tooth_x[0] + tooth_x[1]) / 2, 0, -rc - 2], "to": [pivot[0], 0, pivot[2]], "radius": 2.8},
            {"op": "add", "shape": "rod", "from": [pivot[0], 0, pivot[2]], "to": [pivot[0] + 5, 0, pivot[2] - 26], "radius": 3.2},  # finger blade
            cyl(4.5, 6, (pivot[0], -3, pivot[2]), rot=ALONG_Y),                                    # boss around the pivot
            cyl(1.65, 10, (pivot[0], -5, pivot[2]), rot=ALONG_Y, op="subtract"),                   # 3 mm pin hole
            box((80, 6, 80), (pivot[0], 0, pivot[2] - 10), op="intersect"),                       # flat sides, 6 mm thick
        ]},
        {"name": "frame", "parts": [
            box((front + 8, 24, rco + 14), (front / 2, 0, -(rco + 14) / 2 - 2), round=2),         # cradle under the chamber
            box((30, 26, 80), (pivot[0] - 30, 0, -rco - 55), rotate=[0, -15, 0], round=5),        # grip
            box((36, 8, 44), (pivot[0] + 8, 0, pivot[2] - 28)),                                    # trigger guard (outside)
            box((32, 10, 38), (pivot[0] + 8, 0, pivot[2] - 28), op="subtract"),                    # ... hollow inside
            cyl(rco + gap, front + 20, (-10, 0, 0), op="subtract"),                                # saddle for the chamber
            box((30, 7 + 2 * slide, 40), (pivot[0] + 2, 0, -rc - 12), op="subtract"),              # slot the trigger moves in
            cyl(1.65, 40, (pivot[0], -20, pivot[2]), rot=ALONG_Y, op="subtract"),                  # pin hole
        ]},
        {"name": "spring (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "helix", "radius": 9, "radius2": 0.8, "height": spring_c - 2, "turns": 12, "center": [0.9, 0, 0], "rotate": ALONG_X}]},
        {"name": "3 mm pin (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "rod", "from": [pivot[0], -12, pivot[2]], "to": [pivot[0], 12, pivot[2]], "radius": 1.5, "flat": True}]},
    ]
    return {"name": "dart blaster", "voxel": 0.3, "bodies": bodies,
            "notes": "Print each part separately. Buy: compression spring ~20 mm x 100 mm (1.2 mm wire), an O-ring for the "
                     f"piston groove (~{cid - 4:.0f} x 2 mm), a 3 mm pin or M3 screw, and a rubber band to push the trigger's "
                     "tooth up. Glue the barrel into the socket and the chamber onto the frame. Prime: pull the knob until "
                     "the tooth clicks in front of the piston. Moving parts have 0.4 mm gaps."}


def revolver_blaster(o: dict) -> dict:
    """A 6-shot revolver foam-dart blaster: the dart_blaster's spring plunger + trigger, and in front of it a revolving
    cylinder (6 chambers) on an axle. Load darts from the front, prime, fire, then turn the cylinder by hand one click
    (a printed flexure detent clicks into 6 dimples) to the next dart. Buy: the dart_blaster's spring, O-ring, 3 mm pin,
    rubber band, and a 6 mm steel rod (or M6 bolt) as the cylinder axle."""
    if _o(o, "chamber_diameter", 32, 0, 99) < 22:  # the dart size given as the air tube's size: ignored
        o = {k: v for k, v in o.items() if k != "chamber_diameter"}
    o = {"chamber_diameter": 32, "barrel_length": 80, **o}  # more air: the dart travels cylinder + barrel (~2:1 air ratio)
    base = dart_blaster(o)
    dart = _o(o, "dart_diameter", 13.0, 8, 30)
    stroke = _o(o, "stroke", 50, 20, 120)
    blen = _o(o, "barrel_length", 80, 30, 300)
    L = _o(o, "cylinder_length", 75, 40, 120)              # Nerf Elite darts are ~72 mm long
    wall, gap, slide = 2.4, 0.3, 0.4
    front = 30.0 + 10.0 + stroke + 1                      # the chamber's front wall (as in dart_blaster)
    rch = dart / 2 + 0.1                                  # cylinder chamber radius
    R = 2 * rch + 2.8                                     # chambers' pitch radius around the axle
    rd = R + rch + wall                                   # cylinder outer radius
    za = -R                                               # axle height (the top chamber lines up with the bore, z = 0)
    d0, d1 = front + 10.4, front + 10.4 + L               # cylinder rear / front face
    rb = dart / 2 + 2                                     # barrel outer radius
    rail_top, rail_bot = za - rd - slide, za - rd - slide - 8
    cyl = lambda r, h, c, op="add", **k: {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_X, **k}
    box = lambda x0, x1, y, z0, z1, op="add", **k: {"op": op, "shape": "box", "size": [x1 - x0, 2 * y, z1 - z0],
                                                     "center": [(x0 + x1) / 2, 0, (z0 + z1) / 2], **k}
    ring = lambda a, r: (r * math.sin(math.radians(a)), za + r * math.cos(math.radians(a)))  # (y, z) around the axle
    bodies = {b["name"]: b for b in base["bodies"]}
    # air chamber: a short nozzle instead of the barrel socket (it blows into the top chamber of the cylinder)
    ch = bodies["air chamber"]
    ch["parts"] = [p for p in ch["parts"] if not (p["shape"] == "tube" and p["op"] == "add" and p is not ch["parts"][0])]
    ch["parts"].append({"op": "add", "shape": "tube", "radius": 6.2, "wall": 2, "height": 4, "center": [front + 6, 0, 0], "rotate": ALONG_X})
    bodies["barrel"]["parts"] = [{"op": "add", "shape": "tube", "radius": rb, "wall": 2, "height": blen, "center": [d1 + slide, 0, 0], "rotate": ALONG_X}]
    ty0, ty1, tz0, tz1 = 7.0, 13.0, rail_bot + 1.4, -31.0    # the detent tongue (a flexure in the front plate)
    dy, dz = ring(150, R + 4)                                 # where its nub meets the cylinder's front face
    bodies["frame"]["parts"] += [
        box(front - 10, front + 4, 12, rail_bot, -30),                     # block down to the rail
        box(front - 10, d1 + slide + 8, 12, rail_bot, rail_top),            # rail under the cylinder
        box(front + 6.4, d0 - slide, 12, rail_bot, -6.6),                   # rear plate (holds the axle)
        box(d1 + slide, d1 + slide + 8, 8, rail_bot, 0),                    # front plate
        cyl(rb + gap + 2.5, 8, (d1 + slide, 0, 0)),                          # ... ring around the barrel
        box(d1 + slide, d1 + slide + 8, 14, rail_bot, -31),                 # ... foot (carries the detent)
        cyl(rb + gap, 10, (d1, 0, 0), op="subtract"),                       # barrel socket
        cyl(3.0 + gap, d1 - front + 16, (front + 6, 0, za), op="subtract"),  # axle holes (rear + front plate)
        {"op": "subtract", "shape": "box", "size": [9, 0.8, tz1 - tz0], "center": [d1 + slide + 4, ty0 - 0.4, (tz0 + tz1) / 2]},
        {"op": "subtract", "shape": "box", "size": [9, 0.8, tz1 - tz0], "center": [d1 + slide + 4, ty1 + 0.4, (tz0 + tz1) / 2]},
        {"op": "subtract", "shape": "box", "size": [8 - 1.6, ty1 - ty0, tz1 - tz0 + 0.2],   # thin the tongue to 1.6 mm
         "center": [d1 + slide + 1.6 + (8 - 1.6) / 2 + 0.1, (ty0 + ty1) / 2, (tz0 + tz1) / 2 + 0.1]},
        {"op": "add", "shape": "sphere", "radius": 1.5, "center": [d1 + 0.6, dy, dz]},        # the nub
    ]
    drum = [cyl(rd, L, (d0, 0, za))]
    drum += [cyl(rch, L + 2, (d0 - 1, *ring(a, R)), op="subtract") for a in range(0, 360, 60)]          # 6 chambers
    drum += [cyl(3.0 + slide, L + 2, (d0 - 1, 0, za), op="subtract")]                                     # axle hole
    drum += [{"op": "subtract", "shape": "sphere", "radius": 1.9, "center": [d1 + 0.6, *ring(a, R + 4)]}
             for a in range(30, 390, 60)]                                                                  # detent dimples
    drum += [cyl(3.0, L + 2, (d0 - 1, *ring(a, rd + 1)), op="subtract") for a in range(30, 390, 60)]     # thumb flutes
    base["bodies"] = list(bodies.values()) + [
        {"name": "revolving cylinder", "parts": drum},
        {"name": "6 mm axle (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "rod", "from": [front + 6.4, 0, za], "to": [d1 + slide + 8, 0, za], "radius": 3.0, "flat": True}]},
    ]
    base["name"] = "revolver blaster"
    base["notes"] = (f"6-shot revolver. Air: plunger {o['chamber_diameter']:.0f} mm x {stroke:.0f} mm stroke (~2:1 to the dart's "
                     "travel). Load darts into the cylinder from the front, prime (pull the knob until the tooth clicks), "
                     "fire, then turn the cylinder one click (a flexure in the front plate clicks into 6 dimples) to line up "
                     "the next dart. Buy: compression spring ~20 x 100 mm, an O-ring for the piston groove, a 3 mm pin, a "
                     "rubber band for the trigger tooth, and a 6 mm steel rod (or M6 bolt) for the cylinder axle. Glue the "
                     "barrel into the front plate and the air chamber onto the frame. Print PETG if you can (the flexure "
                     "lasts longer). Moving parts have 0.4 mm gaps.")
    return base


def centrifugal_pump(o: dict) -> dict:
    """A small centrifugal water pump for a round DC motor: impeller on the motor shaft, housing with a sideways
    outlet, lid with the inlet. Buy: the motor (default 130-size, 20 mm body, 2 mm shaft), 4 M3 screws, and a gasket
    or silicone for the lid and the shaft."""
    di = _o(o, "impeller_diameter", 40, 20, 120)
    blades = int(_o(o, "blades", 6, 3, 12))
    shaft = _o(o, "shaft_diameter", 2.0, 1, 8)
    out_d = _o(o, "outlet_diameter", 6, 3, 25)
    in_d = _o(o, "inlet_diameter", 8, 3, 30)
    motor = _o(o, "motor_diameter", 20.4, 10, 60)
    ri, gap = di / 2, 0.3
    rin = ri + 3.8                          # housing inside radius (room for the water to swirl)
    rout = rin + 2
    top = 16.0                              # housing height
    flange_r = rout + 5.5
    hole_r = rout + 2.8                     # screw circle
    oy = rin - out_d / 2                    # tangential outlet position
    ox = math.sqrt(max(rin * rin - oy * oy, 1)) - 0.5
    bodies = [
        {"name": "impeller", "parts": [
            {"op": "add", "shape": "cylinder", "radius": ri, "height": 2, "center": [0, 0, 3]},
            {"op": "add", "shape": "cylinder", "radius": 4.5, "height": 10, "center": [0, 0, 3]},
            {"op": "add", "shape": "box", "size": [ri - 5, 1.6, 8], "center": [5 + (ri - 5) / 2, 0, 9], "rotate": [0, 0, 18],
             "repeat": {"count": blades, "axis_point": [0, 0, 0]}},
            {"op": "subtract", "shape": "cylinder", "radius": shaft / 2 + 0.1, "height": 12, "center": [0, 0, 2]},
        ]},
        {"name": "housing", "parts": [
            {"op": "add", "shape": "cylinder", "radius": rout, "height": 2, "center": [0, 0, 0]},
            {"op": "add", "shape": "tube", "radius": rout, "wall": 2, "height": top, "center": [0, 0, 0]},
            {"op": "add", "shape": "tube", "radius": flange_r, "wall": flange_r - rin, "height": 2, "center": [0, 0, top - 2]},
            {"op": "add", "shape": "tube", "radius": out_d / 2 + 1.5, "wall": 1.5, "height": 30, "center": [ox, oy, 9], "rotate": ALONG_X},
            {"op": "subtract", "shape": "cylinder", "radius": out_d / 2, "height": 45, "center": [0, oy, 9], "rotate": ALONG_X},
            {"op": "subtract", "shape": "cylinder", "radius": shaft / 2 + 0.6, "height": 6, "center": [0, 0, -2]},
            {"op": "add", "shape": "tube", "radius": motor / 2 + 0.25 + 2, "wall": 2, "height": 26, "center": [0, 0, -26]},  # motor sleeve
            {"op": "subtract", "shape": "cylinder", "radius": 1.6, "height": 6, "center": [hole_r, 0, top - 4],
             "repeat": {"count": 4, "axis_point": [0, 0, 0]}},
        ]},
        {"name": "lid", "parts": [
            {"op": "add", "shape": "cylinder", "radius": flange_r, "height": 3, "center": [0, 0, top + gap]},
            {"op": "add", "shape": "tube", "radius": in_d / 2 + 1.5, "wall": 1.5, "height": 20, "center": [0, 0, top + gap + 3]},
            {"op": "subtract", "shape": "cylinder", "radius": in_d / 2, "height": 6, "center": [0, 0, top - 1]},
            {"op": "subtract", "shape": "cylinder", "radius": 1.6, "height": 6, "center": [hole_r, 0, top - 1],
             "repeat": {"count": 4, "axis_point": [0, 0, 0]}},
        ]},
        {"name": "motor (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "cylinder", "radius": motor / 2, "height": 25, "center": [0, 0, -26]},
            {"op": "add", "shape": "cylinder", "radius": shaft / 2, "height": 12, "center": [0, 0, -1]},
        ]},
    ]
    return {"name": "water pump", "voxel": 0.2, "bodies": bodies,
            "notes": f"Print impeller, housing and lid. Buy: a DC motor ({motor:.0f} mm body, {shaft:g} mm shaft), 4 M3 screws, "
                     "and seal the lid and the shaft hole (gasket or silicone). Press the impeller onto the shaft. "
                     "Water goes in through the lid's pipe and out of the side pipe."}


def gear_pair(o: dict) -> dict:
    """Two meshing spur gears on a base plate, at exactly the right distance (module x (teeth1 + teeth2) / 2)."""
    m = _o(o, "module", 1.5, 0.5, 5)
    z1, z2 = int(_o(o, "teeth1", 12, 6, 120)), int(_o(o, "teeth2", 24, 6, 200))
    t = _o(o, "thickness", 8, 2, 40)
    shaft = _o(o, "shaft_diameter", 3, 1, 20)
    a = m * (z1 + z2) / 2
    ra1, ra2 = m * z1 / 2 + m, m * z2 / 2 + m
    turn2 = 180 / z2 if z2 % 2 == 0 else 0  # a gap of gear 2 faces a tooth of gear 1
    return {"name": "gear pair", "voxel": 0.2, "bodies": [
        {"name": f"gear {z1} teeth", "parts": [{"op": "add", "shape": "gear", "teeth": z1, "module": m, "height": t, "bore": shaft / 2 + 0.1, "center": [0, 0, 0]}]},
        {"name": f"gear {z2} teeth", "parts": [{"op": "add", "shape": "gear", "teeth": z2, "module": m, "height": t, "bore": shaft / 2 + 0.1, "center": [a, 0, 0], "rotate": [0, 0, turn2]}]},
        {"name": "base plate", "parts": [
            {"op": "add", "shape": "box", "size": [a + ra1 + ra2 + 8, 2 * max(ra1, ra2) + 8, 4], "center": [(a + ra2 - ra1) / 2, 0, -3.5], "round": 2},
            {"op": "subtract", "shape": "cylinder", "radius": shaft / 2 + 0.05, "height": 6, "center": [0, 0, -6]},
            {"op": "subtract", "shape": "cylinder", "radius": shaft / 2 + 0.05, "height": 6, "center": [a, 0, -6]}]},
        {"name": "shafts (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "cylinder", "radius": shaft / 2, "height": t + 8, "center": [0, 0, -5]},
            {"op": "add", "shape": "cylinder", "radius": shaft / 2, "height": t + 8, "center": [a, 0, -5]}]},
    ], "notes": f"Center distance {a:g} mm. Print both gears and the plate; use {shaft:g} mm rods as shafts."}


def box_with_lid(o: dict) -> dict:
    L, W, H = _o(o, "length", 80, 20, 300), _o(o, "width", 60, 20, 300), _o(o, "height", 40, 10, 300)
    wall, gap = _o(o, "wall", 2, 1, 6), 0.3
    return {"name": "box with lid", "voxel": 0.25, "bodies": [
        {"name": "box", "parts": [
            {"op": "add", "shape": "box", "size": [L, W, H], "center": [0, 0, H / 2], "round": 2},
            {"op": "subtract", "shape": "box", "size": [L - 2 * wall, W - 2 * wall, H], "center": [0, 0, H / 2 + wall], "round": 1}]},
        {"name": "lid", "parts": [
            {"op": "add", "shape": "box", "size": [L, W, wall], "center": [0, 0, H + gap + wall / 2], "round": 2},
            {"op": "add", "shape": "box", "size": [L - 2 * wall - 2 * gap, W - 2 * wall - 2 * gap, 5], "center": [0, 0, H + gap - 2.5]},
            {"op": "subtract", "shape": "box", "size": [L - 4 * wall - 2 * gap, W - 4 * wall - 2 * gap, 6], "center": [0, 0, H + gap - 3]}]},
    ], "notes": "The lid's lip slides into the box with a 0.3 mm gap."}


def handcuffs(o: dict) -> dict:
    """Toy handcuffs that work: each cuff = a fixed frame + a jaw on a print-in-place hinge (knuckles + pin, 0.4-0.5 mm
    gaps), closed by a lock pin through a catch; the cuffs are joined by a print-in-place chain of rounded links
    (0.9 mm gaps). Cuffs lie flat (Z up), side by side along X, chain between them."""
    ri = _o(o, "wrist_diameter", 60, 40, 100) / 2   # inside of the cuff
    ro, rm, hz = ri + 6, ri + 3, 6.3                   # outside, middle of the bar, half the thickness
    hinge_y = rm
    link = {"size": [22.6, 12.6, 3.6], "round": 1.2}  # outer; hole 15.4 x 5.4 -> the next link hooks through
    hole = {"size": [15.4, 5.4, 20], "round": 1.5}

    def cuff(cx: float, s: int) -> list[dict]:
        """s = +1: the chain side is +X (left cuff), -1: right cuff. Frame = chain half, jaw = outer half."""
        X = lambda dx: cx + s * dx  # noqa: E731
        ring = [{"op": "add", "shape": "cylinder", "radius": ro, "height": 2 * hz, "center": [cx, 0, -hz]},
                {"op": "subtract", "shape": "cylinder", "radius": ri, "height": 2 * hz + 2, "center": [cx, 0, -hz - 1]}]
        frame = ring + [
            {"op": "subtract", "shape": "box", "size": [200, 200, 30], "center": [X(0.25 - 100), 0, 0]},   # keep the chain half
            {"op": "subtract", "shape": "cylinder", "radius": 5, "height": 2 * hz + 2, "center": [cx, hinge_y, -hz - 1]},
            {"op": "add", "shape": "cylinder", "radius": 4.5, "height": 4, "center": [cx, hinge_y, -2]},      # middle knuckle
            {"op": "add", "shape": "box", "size": [5, 5, 4], "center": [X(4.5), hinge_y, 0]},                 # knuckle -> frame
            {"op": "add", "shape": "cylinder", "radius": 1.8, "height": 2 * hz, "center": [cx, hinge_y, -hz]},  # hinge pin
            {"op": "add", "shape": "box", "size": [7, 6, hz - 0.3], "center": [X(-2.5), -rm, -(hz + 0.3) / 2]},  # catch tab
            {"op": "subtract", "shape": "cylinder", "radius": 1.6, "height": 2 * hz + 2, "center": [X(-3), -rm, -hz - 1]},
            {"op": "add", "shape": "box", "center": [X(ro + 7), 0, 0], **link},                                # chain eye
            {"op": "subtract", "shape": "box", "center": [X(ro + 7), 0, 0], **hole}]
        jaw = ring + [
            {"op": "subtract", "shape": "box", "size": [200, 200, 30], "center": [X(100 - 0.25), 0, 0]},   # keep the outer half
            {"op": "subtract", "shape": "cylinder", "radius": 5, "height": 2 * hz + 2, "center": [cx, hinge_y, -hz - 1]},
            {"op": "add", "shape": "cylinder", "radius": 4.5, "height": 2 * hz, "center": [cx, hinge_y, -hz]},   # outer knuckles
            {"op": "add", "shape": "box", "size": [5, 5, 2 * hz], "center": [X(-4.5), hinge_y, 0]},            # knuckles -> jaw
            {"op": "subtract", "shape": "cylinder", "radius": 4.9, "height": 4.8, "center": [cx, hinge_y, -2.4]},  # room for the middle one
            {"op": "subtract", "shape": "cylinder", "radius": 2.2, "height": 2 * hz + 2, "center": [cx, hinge_y, -hz - 1]},  # pin hole
            {"op": "subtract", "shape": "box", "size": [7.4, 8, hz + 0.8], "center": [X(-2.7), -rm, -(hz + 0.8) / 2 + 0.1]},  # over the tab
            {"op": "subtract", "shape": "cylinder", "radius": 1.6, "height": 2 * hz + 2, "center": [X(-3), -rm, -hz - 1]}]
        pin = [{"op": "add", "shape": "cylinder", "radius": 1.2, "height": 2 * hz + 1, "center": [X(-3), -rm, -hz - 0.5]},
               {"op": "add", "shape": "cylinder", "radius": 2.6, "height": 1.5, "center": [X(-3), -rm, hz + 0.5]}]
        side = "left" if s > 0 else "right"
        return [{"name": f"{side} cuff frame", "parts": frame}, {"name": f"{side} cuff jaw", "parts": jaw},
                {"name": f"{side} lock pin", "parts": pin}]

    eye = ro + 7                 # eye centre from the cuff centre
    cx = -(29 + eye)             # eyes at x = +-29, three links between them at a 14.5 mm pitch
    links = []
    for i, x in enumerate((-14.5, 0.0, 14.5)):
        turn = [90, 0, 0] if i != 1 else [0, 0, 0]  # links alternate: standing, flat, standing
        links.append({"name": f"chain link {i + 1}", "parts": [
            {"op": "add", "shape": "box", "center": [x, 0, 0], "rotate": turn, **link},
            {"op": "subtract", "shape": "box", "center": [x, 0, 0], "rotate": turn, **hole}]})
    return {"name": "handcuffs", "voxel": 0.3, "bodies": cuff(cx, 1) + links + cuff(-cx, -1),
            "notes": f"Wrist opening {2 * ri:g} mm. Print flat in one go (supports under the chain). Hinges and chain print "
                     "in place - break them loose gently. The jaw swings open on its hinge; close it and push the lock pin "
                     "through the catch (pull it out to open). A toy / costume prop, not a restraint."}


# ---------------------------------------------------------------- threads, drum, hand, exoskeleton (2026-09-27)
def _hexagon(s: float) -> list:
    """A hexagon (bolt head / nut) with s mm across the flats, flats facing ±Y."""
    r = s / math.sqrt(3)
    return [[round(r * math.cos(math.radians(60 * i)), 3), round(r * math.sin(math.radians(60 * i)), 3)] for i in range(6)]


def _helix(rc: float, wire: float, z0: float, turns: int, pitch: float, op: str = "add") -> dict:
    """A round thread: a wire of radius `wire` wound on radius rc. Always whole turns from a start at a whole number of
    pitches, so a bolt's thread and its nut's channel follow the SAME path (36 straight pieces per turn in both)."""
    return {"op": op, "shape": "helix", "radius": rc, "radius2": wire, "height": turns * pitch, "turns": turns,
            "center": [0, 0, z0]}


def bolt_and_nut(o: dict) -> dict:
    """A printable bolt + nut with a ROUND thread (knuckle thread): no sharp crests to break, no supports, self-cleaning,
    0.3 mm play all round. Pitch is coarse on purpose (about d/4): fine threads don't print."""
    d = _o(o, "diameter", 16, 8, 60)
    L = _o(o, "length", 40, 12, 200)
    P = _o(o, "pitch", max(2.5, round(d / 4 * 2) / 2), 1.5, 10)
    c = _o(o, "clearance", 0.3, 0.15, 0.8)
    w = 0.25 * P                                    # thread wire radius (its depth)
    rc = d / 2 - w                                  # core radius
    s, k, m = 1.5 * d, 0.65 * d, 0.8 * d            # hex across flats, head height, nut height
    n = max(2, int((L - 1.5 * P) // P))             # whole turns on the bolt
    z0 = k + 0.5 * P                                # thread start (whole pitches from here)
    zn = z0 + (n * P - m) - 0.5 * P if n * P > m + P else z0  # the nut sits on the threaded end
    j = math.ceil((z0 - (zn - P)) / P)             # nut channel: same path, started j pitches lower
    zc = z0 - j * P
    tn = math.ceil((zn + m + P - zc) / P)
    cone = lambda r1, r2, h, z, op="subtract": {"op": op, "shape": "cone", "radius": r1, "radius2": r2, "height": h, "center": [0, 0, z]}
    bolt = [{"op": "add", "shape": "extrude", "points": _hexagon(s), "height": k, "center": [0, 0, 0]},
            {"op": "add", "shape": "cylinder", "radius": rc, "height": L, "center": [0, 0, k]},
            _helix(rc, w, z0, n, P),
            {"op": "subtract", "shape": "revolve", "center": [0, 0, 0],  # a 45° chamfer ring at the tip: the nut finds the thread
             "points": [[rc - 1.1, k + L + 0.5], [d / 2 + 2, k + L + 0.5], [d / 2 + 2, k + L - w - 2.6]]}]
    nut = [{"op": "add", "shape": "extrude", "points": _hexagon(s), "height": m, "center": [0, 0, zn]},
           {"op": "subtract", "shape": "cylinder", "radius": rc + c, "height": m + 2, "center": [0, 0, zn - 1]},
           _helix(rc, w + c, zc, tn, P, "subtract"),
           cone(rc + w + c + 0.8, rc + c, 1.2, zn - 0.01), cone(rc + c, rc + w + c + 0.8, 1.2, zn + m - 1.19)]
    return {"name": f"bolt and nut {d:g} mm", "voxel": 0.15 if d < 14 else 0.2, "bodies": [
        {"name": f"bolt {d:g} x {L:g}", "parts": bolt}, {"name": f"nut {d:g}", "parts": nut}],
        "notes": f"Round thread {d:g} mm, pitch {P:g} mm, {c:g} mm play all round (tested value for FDM). Print the bolt "
                 "standing on its head and the nut flat, 0.2 mm layers (0.12 mm below 12 mm), 3+ walls, PETG or PLA. "
                 "Too tight: clearance 0.4. Printed threads are for hand-tight use; for real loads use a metal bolt "
                 "and a heat-set insert or a captured nut."}


def threaded_jar(o: dict) -> dict:
    """A jar with a screw-on lid (2 1/4 turns of round thread, 0.35 mm play). Shown with the lid screwed on."""
    di = _o(o, "diameter", 70, 20, 200)
    H = _o(o, "height", 80, 20, 300)
    wall, P, c = _o(o, "wall", 2.4, 1.6, 5), _o(o, "pitch", 4, 2.5, 8), 0.35
    ro, w, n = di / 2 + wall, 0.25 * _o(o, "pitch", 4, 2.5, 8), 2
    zt = H - 2 - n * P - P                          # thread start (its last turn ends 2 mm under the rim)
    rl = ro + w + c + 2.4                           # lid outer radius
    zs = zt - 1                                     # lid skirt bottom
    top, plate = H + c, 3.0
    j = 1
    zc = zt - j * P
    tn = math.ceil((top + plate - zc) / P)
    jar = [{"op": "add", "shape": "cylinder", "radius": ro, "height": H, "center": [0, 0, 0]},
           {"op": "subtract", "shape": "cylinder", "radius": di / 2, "height": H, "center": [0, 0, wall]},
           _helix(ro, w, zt, n + 1, P)]
    lid = [{"op": "add", "shape": "cylinder", "radius": rl, "height": top - zs, "center": [0, 0, zs]},
           {"op": "subtract", "shape": "cylinder", "radius": ro + c, "height": top - zs + 1, "center": [0, 0, zs - 1]},
           _helix(ro, w + c, zc, tn, P, "subtract"),
           {"op": "add", "shape": "cylinder", "radius": rl, "height": plate, "center": [0, 0, top]},  # the top back on
           {"op": "subtract", "shape": "cylinder", "radius": 1.6, "height": top + plate - zs + 2, "center": [rl + 0.6, 0, zs - 1],
            "repeat": {"count": 30}}]                                                             # grip flutes
    return {"name": "screw-top jar", "voxel": 0.2, "bodies": [{"name": "jar", "parts": jar}, {"name": "screw lid", "parts": lid}],
            "notes": f"Inside {di:g} mm x {H - wall:g} mm deep. Round thread, pitch {P:g} mm, {c:g} mm play; the lid needs "
                     "about 2 turns. Print the jar upright and the lid upside down (top on the bed), no supports."}


def drum_magazine(o: dict) -> dict:
    """A rotating drum magazine for foam darts: N chambers around an axle, a frame with a feed hole (from the air
    nozzle) and an exit hole (to the barrel) lined up with the TOP chamber, and a printed flexure detent that clicks
    into dimples so each chamber stops in line. Turn it by the thumb flutes. Buy: a 6 mm rod or M6 bolt."""
    dart = _o(o, "dart_diameter", 13.0, 8, 30)
    N = int(_o(o, "darts", 12, 8, 24))
    L = _o(o, "length", 75, 40, 120)
    wall, slide = 2.4, 0.4
    rch = dart / 2 + 0.1
    Rp = (2 * rch + 2.6) / (2 * math.sin(math.pi / N))   # chambers' pitch radius (2.6 mm between chambers)
    rd = Rp + rch + wall                                  # drum radius
    ring = lambda a, r: (r * math.sin(math.radians(a)), r * math.cos(math.radians(a)))  # (y, z) around the axle
    cyl = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_X}
    rail_top, rail_bot = -rd - slide, -rd - slide - 8
    xr0, xr1, xf0, xf1 = -slide - 8, -slide, L + slide, L + slide + 8
    bn = 180 - 180 / N                                    # the detent: one of the dimple angles, near the bottom
    yn, zn = ring(bn, Rp + 4)
    half = max(14.0, abs(yn) + 5)
    ztop = Rp + rch + 6
    box = lambda x0, x1, y0, y1, z0, z1, op="add": {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                     "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]}
    drum = [cyl(rd, L, (0, 0, 0))]
    drum += [cyl(rch, L + 2, (-1, *ring(a, Rp)), "subtract") for a in [k * 360 / N for k in range(N)]]
    drum += [cyl(3.0 + slide, L + 2, (-1, 0, 0), "subtract")]
    drum += [{"op": "subtract", "shape": "sphere", "radius": 1.9, "center": [L + 0.6, *ring(b, Rp + 4)]}
             for b in [180 / N + k * 360 / N for k in range(N)]]                                   # detent dimples
    drum += [cyl(3.0, L + 2, (-1, *ring(b, rd + 1)), "subtract") for b in [180 / N + k * 360 / N for k in range(N)]]
    frame = [box(xr0, xf1, -12, 12, rail_bot, rail_top),                                           # rail under the drum
             box(xr0, xr1, -half, half, rail_bot, ztop), box(xf0, xf1, -half, half, rail_bot, ztop),  # rear + front plate
             cyl(3.0 + 0.3, xf1 - xr0 + 2, (xr0 - 1, 0, 0), "subtract"),                          # axle holes
             cyl(6.2, 10, (xr0 - 1, 0, Rp), "subtract"),                                          # feed (air nozzle)
             cyl(rch + 0.3, 10, (xf0 - 1, 0, Rp), "subtract"),                                    # exit (to the barrel)
             {"op": "add", "shape": "tube", "radius": rch + 0.3 + 2, "wall": 2, "height": 10, "center": [xf1, 0, Rp], "rotate": ALONG_X},
             box(xf0 - 0.5, xf1 + 0.5, yn - 3.8, yn - 3.0, zn - 9, zn + 7, "subtract"),           # the flexure's slots
             box(xf0 - 0.5, xf1 + 0.5, yn + 3.0, yn + 3.8, zn - 9, zn + 7, "subtract"),
             box(xf0 + 1.6, xf1 + 0.1, yn - 3.0, yn + 3.0, zn - 9, zn + 7, "subtract"),           # thinned to 1.6 mm
             {"op": "add", "shape": "sphere", "radius": 1.5, "center": [L + 0.6, yn, zn]}]        # its nub
    return {"name": f"drum magazine {N} darts", "voxel": 0.3, "bodies": [
        {"name": f"drum ({N} chambers)", "parts": drum}, {"name": "drum frame", "parts": frame},
        {"name": "6 mm axle (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "rod", "from": [xr0, 0, 0], "to": [xf1, 0, 0], "radius": 3.0, "flat": True}]}],
        "notes": f"{N} darts of {dart:g} mm. The air comes in through the rear hole, the dart leaves through the front "
                 "socket (glue a barrel tube in it) - both line up with the TOP chamber. Turn the drum by its flutes: "
                 "the flexure nub clicks into a dimple at every chamber. Buy a 6 mm rod or M6 bolt as the axle. Print "
                 "the drum standing on its end, the frame on its side; PETG makes the flexure last. For a complete "
                 "gun use revolver_blaster (6 shots) or put this in front of dart_blaster's air chamber."}


def drum_blaster(o: dict) -> dict:
    """A tommy-gun style foam-dart blaster with a DRUM THAT TURNS ON ITS OWN AT EVERY SHOT: the dart_blaster's spring
    plunger + trigger, an N-dart drum in front of the air chamber, a finned barrel, a front grip and a stock.
    Indexing: an index bar on the plunger runs forward under the air chamber; in the last mm of every shot (the spring
    slams the plunger forward) its tip pushes a sawtooth ratchet on the drum's rear face and turns the drum one
    chamber; the flexure detent then stops the next chamber exactly in line. Prime (pull the knob) -> pull the trigger ->
    it fires and the next dart turns in. (A finger moves a printed trigger only 2-5 mm: too little to turn a 16-dart
    drum reliably; the plunger has the whole stroke and its own spring.)"""
    if _o(o, "chamber_diameter", 32, 0, 99) < 22:
        o = {k: v for k, v in o.items() if k != "chamber_diameter"}
    o = {"chamber_diameter": 32, "barrel_length": 150, **o}
    base = dart_blaster(o)
    N = int(_o(o, "darts", 16, 8, 24))
    dart = _o(o, "dart_diameter", 13.0, 8, 30)
    stroke = _o(o, "stroke", 50, 30, 120)
    blen = _o(o, "barrel_length", 150, 90, 400)
    L = _o(o, "drum_length", 75, 40, 120)
    cid = _o(o, "chamber_diameter", 32, 16, 50)
    wall, gap, slide, ht = 2.4, 0.3, 0.4, 4.5          # ht = ratchet tooth height = the pawl's push
    rco = cid / 2 + wall
    front = 30.0 + 10.0 + stroke + 1                   # the air chamber's front wall (as in dart_blaster)
    rch = dart / 2 + 0.1
    Rp = (2 * rch + 2.6) / (2 * math.sin(math.pi / N))
    rd = Rp + rch + wall
    za = -Rp                                           # drum axle: the TOP chamber lines up with the bore (z = 0)
    d0, d1 = front + 10.4 + ht, front + 10.4 + ht + L  # drum rear / front face
    rb = dart / 2 + 2
    ring = lambda a, r: (r * math.sin(math.radians(a)), za + r * math.cos(math.radians(a)))  # (y, z) around the axle
    cyl = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_X}
    B = lambda x0, x1, y0, y1, z0, z1, op="add", **k: {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                       "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], **k}
    rail_top, rail_bot = za - rd - slide, za - rd - slide - 8
    by0, by1, bz0, bz1 = 7.0, 11.0, -23.0, -19.0        # the index bar's cross-section (beside the trigger, under the chamber)
    bodies = {b["name"]: b for b in base["bodies"]}
    # air chamber: a nozzle into the drum's top chamber instead of the barrel socket (longer by the ratchet's height)
    ch = bodies["air chamber"]
    ch["parts"] = [p for p in ch["parts"] if not (p["shape"] == "tube" and p["op"] == "add" and p is not ch["parts"][0])]
    ch["parts"].append({"op": "add", "shape": "tube", "radius": 6.2, "wall": 2, "height": 4 + ht, "center": [front + 6, 0, 0], "rotate": ALONG_X})
    # barrel after the drum, cooling fins past the front grip's rail
    fins = max(0, int((blen - 95) // 10))
    bodies["barrel"]["parts"] = [{"op": "add", "shape": "tube", "radius": rb, "wall": 2, "height": blen, "center": [d1 + slide, 0, 0], "rotate": ALONG_X}]
    if fins:
        bodies["barrel"]["parts"].append({"op": "add", "shape": "tube", "radius": rb + 3, "wall": 3.2, "height": 3,
                                          "center": [d1 + slide + 90, 0, 0], "rotate": ALONG_X, "repeat": {"count": fins, "step": [10, 0, 0]}})
    # the index bar rides on the plunger: its connector hangs from the knob, the bar runs forward under the chamber
    kx = -(stroke + 25)
    tip = d0 - stroke - slide                            # primed; after a shot it stops 0.4 mm short of the drum face
    bodies["plunger"]["parts"] += [B(kx, kx + 10, by0, by1, bz0, -6), B(kx, tip, by0, by1, bz0, bz1)]
    # the drum: N chambers, axle hole, detent dimples (front), thumb flutes, sawtooth ratchet (rear)
    step = 360 / N
    psi = math.degrees(math.atan2((by0 + by1) / 2, (bz0 + bz1) / 2 - za))      # where the pawl meets the ratchet
    rr = math.hypot((by0 + by1) / 2, (bz0 + bz1) / 2 - za)                     # ... and at what radius
    r0, rw = rr - 5.5, 11.0
    a = 2 * math.pi * rr / N                                                     # one tooth's length at the pawl
    drum = [cyl(rd, L, (d0, 0, za))]
    drum += [cyl(rch, L + 2, (d0 - 1, *ring(k * step, Rp)), "subtract") for k in range(N)]
    drum += [cyl(3.0 + slide, L + 2 + ht, (d0 - 1 - ht, 0, za), "subtract")]
    drum += [{"op": "subtract", "shape": "sphere", "radius": 1.9, "center": [d1 + 0.6, *ring(step / 2 + k * step, Rp + 4)]} for k in range(N)]
    drum += [cyl(3.0, L + 2, (d0 - 1, *ring(step / 2 + k * step, rd + 1)), "subtract") for k in range(N)]
    for k in range(N):  # teeth: each rises from the drum face to ht (backwards) over one step; the pawl rests near a top
        th = psi + 2.5 - step + k * step
        y, z = ring(th, r0)
        drum.append({"op": "add", "shape": "extrude", "points": [[0, 0], [a, 0], [a, ht]], "height": rw,
                     "center": [d0, y, z], "rotate": [0, th, 90]})
    drum += [cyl(3.0 + slide, ht + 2, (d0 - ht - 1, 0, za), "subtract")]       # keep the axle hole through the teeth
    # frame: the dart_blaster's grip + cradle, plus the drum's plates and rail, a front grip, a stock, the bar's channel
    xf0, xf1 = d1 + slide, d1 + slide + 8
    bn = 180 - 180 / N
    yn, zn = ring(bn, Rp + 4)
    half = max(14.0, abs(yn) + 5)
    bodies["frame"]["parts"] += [
        B(-4, front + 4, 11, 15, -34, -16), B(-4, front + 4, -15, -11, -34, -16),   # thicker cradle sides (the bar's channel)
        B(front - 10, front + 4, -12, 12, rail_bot, -30),                          # pillar down to the rail
        B(front - 10, xf1, -12, 12, rail_bot, rail_top),                           # rail under the drum
        B(front + 6.4, d0 - ht - slide, -12, 12, rail_bot, -6.6),                  # rear plate (axle; the bar passes)
        B(xf0, xf1, -half, half, rail_bot, 0), cyl(rb + gap + 2.5, 8, (xf0, 0, 0)),  # front plate + ring round the barrel
        cyl(rb + gap, 10, (d1, 0, 0), "subtract"),                                 # barrel socket
        cyl(3.0 + gap, xf1 - front + 2, (front + 5, 0, za), "subtract"),          # axle holes
        B(xf0 - 0.5, xf1 + 0.5, yn - 3.8, yn - 3.0, zn - 9, zn + 7, "subtract"),   # detent flexure: slots,
        B(xf0 - 0.5, xf1 + 0.5, yn + 3.0, yn + 3.8, zn - 9, zn + 7, "subtract"),
        B(xf0 + 1.6, xf1 + 0.1, yn - 3.0, yn + 3.0, zn - 9, zn + 7, "subtract"),   # thinned to 1.6 mm
        {"op": "add", "shape": "sphere", "radius": 1.5, "center": [d1 + 0.6, yn, zn]},  # and its nub
        B(-10, d0 - ht, by0 - slide, by1 + slide, bz0 - slide, bz1 + slide, "subtract"),  # the index bar's channel
        {"op": "subtract", "shape": "cylinder", "radius": 1.8, "height": 40, "center": [30.0 + 6, -20, -(rco + 9)],
         "rotate": ALONG_Y},                                                       # the trigger pin's hole, again
        cyl(1.75, 20, (-19.1, 0, -42), "subtract"), cyl(1.75, 20, (-19.1, 0, -49), "subtract"),  # M4 self-tap (stock)
        cyl(1.3, 7.1, (xf1 - 7, 5, -22), "subtract"), cyl(1.3, 7.1, (xf1 - 7, -5, -22), "subtract"),  # M3 (front grip)
    ]
    # printable pieces (a 473 mm frame fits no printer): the stock and the front grip screw on
    stock = [B(-200, -30.4, -10, 10, -50, -30),                                   # stock bar
             B(-30.4, -19.4, -12, 12, -52, -19.5),                                # mounting plate behind the pistol grip
             B(-214, -198, -15, 15, -105, -14, round=4),                           # butt plate
             B(-31, -19, by0 - slide, by1 + slide, bz0 - slide, bz1 + slide, "subtract"),  # the index bar passes
             cyl(2.25, 14, (-32, 0, -42), "subtract"), cyl(2.25, 14, (-32, 0, -49), "subtract")]  # M4 clearance
    fgrip = [B(xf1 + 0.4, xf1 + 6.4, -10, 10, -rb - gap - 20, -rb - gap),        # tab against the front plate
             B(xf1 + 0.4, xf1 + 70, -8, 8, -rb - gap - 8, -rb - gap),             # rail under the barrel
             B(xf1 + 32, xf1 + 58, -12, 12, -rb - gap - 85, -rb - gap - 6, round=4),  # the grip
             cyl(1.7, 9, (xf1 - 1, 5, -22), "subtract"), cyl(1.7, 9, (xf1 - 1, -5, -22), "subtract")]  # M3 clearance
    base["bodies"] = list(bodies.values()) + [{"name": "stock", "parts": stock}, {"name": "front grip", "parts": fgrip}] + [
        {"name": f"drum ({N} darts)", "parts": drum},
        {"name": "6 mm axle (buy)", "reference": True, "parts": [
            {"op": "add", "shape": "rod", "from": [front + 6.4, 0, za], "to": [xf1, 0, za], "radius": 3.0, "flat": True}]},
    ]
    base["name"] = f"drum blaster ({N} darts)"
    base["notes"] = (f"Tommy-gun style blaster, {N}-dart drum. Load darts into the drum from the front. Prime: pull the knob "
                     "back until the trigger's tooth clicks. Pull the trigger: the plunger slams forward and fires the top "
                     "dart; in the last 4-5 mm of that stroke the index bar under the air chamber pushes the ratchet on the "
                     "drum's back and turns it one chamber, and the flexure detent stops the next dart exactly in line. "
                     "If it turns too little, sand the ratchet teeth smooth or add a drop of dry lubricant. Buy: compression "
                     "spring ~24 x 100 mm, an O-ring for the piston, a 3 mm pin, a rubber band for the trigger tooth, a 6 mm "
                     "rod (or M6 bolt) for the drum axle, 2 x M4 x 30 screws for the stock and 2 x M3 x 12 for the front grip "
                     "(they cut their own thread in the frame). Glue the barrel into the front plate. Every piece fits a "
                     "220 mm printer. Print PETG for the flexure and the index bar. Moving parts have 0.4 mm gaps.")
    return base


DRONE = {  # (H: a 19 mm camera tilted 25° needs 25.3 mm between the plates -> 30 mm standoffs on the 5")
           # hobby standards per prop size: wheelbase, arm width, plate thickness, motor pad, motor bolts (hole r, half
    # pattern), motor centre hole, FC stack (hole r, half pattern), body, standoff height, camera, motor, prop r, battery
    3: dict(wb=140, aw=10, t=4, pad=10, mh=1.1, mp=6, ch=2.8, sh=1.1, sp=10, bw=58, bl=32, H=20, cam=14, mr=9.5, mz=15,
            pr=38.1, bat=(60, 30, 25), stack=27),
    5: dict(wb=225, aw=14, t=6, pad=14.5, mh=1.6, mp=8, ch=3.5, sh=1.6, sp=15.25, bw=80, bl=42, H=30, cam=19, mr=14, mz=18,
            pr=63.5, bat=(75, 35, 35), stack=36),
    7: dict(wb=300, aw=16, t=6.5, pad=16, mh=1.6, mp=9.5, ch=4, sh=1.6, sp=15.25, bw=92, bl=46, H=28, cam=19, mr=16.5, mz=20,
            pr=89, bat=(105, 42, 40), stack=36)}


def fpv_drone(o: dict) -> dict:
    """An FPV quadcopter frame (true X): a bottom plate with 4 arms and motor pads, a top plate on 4 standoffs, a TPU
    camera mount (25° up), an antenna mount, battery strap slots, optional prop guards. Standard hole patterns, so
    shop motors, FC/ESC stack, camera and props fit. Motors, props, stack, camera, battery and standoffs are shown as
    "(buy)". A 7" frame gets bolt-on arms (it would not fit a 220 mm printer in one piece)."""
    size = min(DRONE, key=lambda s: abs(s - _o(o, "props", 5, 2.5, 8)))
    d = DRONE[size]
    guards = bool(o.get("guards")) and size <= 5
    wb, aw, t, pad, H, cam = d["wb"], d["aw"], d["t"], d["pad"], d["H"], d["cam"]
    R = wb / 2
    bw, bl = d["bw"], d["bl"]
    split = wb > 250
    sx = -0.08 * bw                                     # the FC stack sits a little back (the camera is in front)
    Z = lambda r, h, c, op="add", **k: {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), **k}
    B = lambda x0, x1, y0, y1, z0, z1, op="add", **k: {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                       "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], **k}
    motors = [(R * math.cos(math.radians(a)), R * math.sin(math.radians(a)), a) for a in (45, 135, 225, 315)]

    def rot(x, y, a):
        c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
        return x * c - y * s, x * s + y * c

    def motor_holes(mx, my, a, z0, h):
        return ([Z(d["mh"], h, (mx + rx, my + ry, z0), "subtract") for rx, ry in
                 (rot(sx_, sy_, a) for sx_, sy_ in ((d["mp"], d["mp"]), (-d["mp"], d["mp"]), (d["mp"], -d["mp"]), (-d["mp"], -d["mp"])))]
                + [Z(d["ch"], h, (mx, my, z0), "subtract")])

    corners = [(x, y) for x in (bw / 2 - 5, -bw / 2 + 5) for y in (bl / 2 - 4, -bl / 2 + 4)]
    frame = [B(-bw / 2, bw / 2, -bl / 2, bl / 2, 0, t, round=3)]
    arms = []
    for mx, my, a in motors:
        r0 = 0 if not split else math.hypot(bw / 2, bl / 2) - 12      # a bolt-on arm starts under the body's corner
        arm = [{"op": "add", "shape": "box", "size": [R - r0, aw, t], "center": [*[(r0 + R) / 2 * v for v in (math.cos(math.radians(a)), math.sin(math.radians(a)))], t / 2 if not split else -t / 2],
                "rotate": [0, 0, a]}, Z(pad, t, (mx, my, 0 if not split else -t))]
        arm += motor_holes(mx, my, a, -t - 1, 2 * t + 2)
        if split:
            bolts = [(r0 + 4) * math.cos(math.radians(a)), (r0 + 4) * math.sin(math.radians(a))], \
                    [(r0 + 14) * math.cos(math.radians(a)), (r0 + 14) * math.sin(math.radians(a))]
            arm += [Z(1.6, 2 * t + 2, (bx, by, -t - 1), "subtract") for bx, by in bolts]
            frame += [Z(1.6, 2 * t + 2, (bx, by, -t - 1), "subtract") for bx, by in bolts]
            arms.append({"name": f"arm {len(arms) + 1}", "parts": arm})
        else:
            frame += arm
    frame += [Z(d["sh"], t + 2, (sx + x, y, -1), "subtract") for x in (d["sp"], -d["sp"]) for y in (d["sp"], -d["sp"])]  # FC stack
    frame += [Z(1.6, t + 2, (x, y, -1), "subtract") for x, y in corners]                                              # standoffs
    top = [B(-bw / 2, bw / 2, -bl / 2, bl / 2, t + H, t + H + 3, round=3),
           Z(8, 5, (sx, 0, t + H - 1), "subtract")]                                                                      # wires
    top += [Z(1.6, 5, (x, y, t + H - 1), "subtract") for x, y in corners]
    top += [B(x - 2, x + 2, -11, 11, t + H - 1, t + H + 4, "subtract") for x in (-bw * 0.22, bw * 0.22)]               # strap slots
    # the camera mount (TPU): two cheeks and a back wall, the camera tilted 25° up; clamped between the plates
    xc, cz = bw / 2 - 4, t + H / 2
    reach = cam / 2 * (math.cos(math.radians(25)) + math.sin(math.radians(25)))
    cy0, cy1 = cam / 2 + 0.4, cam / 2 + 2.4
    xm0, xm1 = xc - reach - 3.4, xc + 6
    mount = [B(xm0, xm1, cy0, cy1, t + 0.05, t + H - 0.45), B(xm0, xm1, -cy1, -cy0, t + 0.05, t + H - 0.45),
             B(xm0, xm0 + 2.6, -cy1, cy1, t + 0.05, t + H - 0.45),
             {"op": "subtract", "shape": "cylinder", "radius": 1.1, "height": 2 * cy1 + 2, "center": [xc, -cy1 - 1, cz], "rotate": ALONG_Y}]
    # the antenna mount (TPU): on the top plate's back end, a tube pointing up and back (SMA: 6.6 mm hole)
    zt = t + H + 3
    ant = [B(-bw / 2, -bw / 2 + 12, -8, 8, zt + 0.05, zt + 8),
           {"op": "add", "shape": "rod", "from": [-bw / 2 + 6, 0, zt + 6], "to": [-bw / 2 - 12, 0, zt + 24], "radius": 5.5},
           {"op": "subtract", "shape": "rod", "from": [-bw / 2 + 8, 0, zt + 4], "to": [-bw / 2 - 14, 0, zt + 26], "radius": 3.3, "flat": True}]
    bodies = [{"name": "bottom plate + arms" if not split else "bottom plate", "parts": frame}, *arms,
              {"name": "top plate", "parts": top}, {"name": "camera mount (TPU)", "parts": mount},
              {"name": "antenna mount (TPU)", "parts": ant}]
    buy = [{"name": "4 motors (buy)", "parts": [Z(d["mr"], d["mz"], (mx, my, t + 0.05)) for mx, my, _ in motors]},
           {"name": f"4 props {size}\" (buy)", "parts": [Z(d["pr"], 1, (mx, my, t + d["mz"] + 2)) for mx, my, _ in motors]},
           {"name": "FC / ESC stack (buy)", "parts": [B(sx - d["stack"] / 2, sx + d["stack"] / 2, -d["stack"] / 2, d["stack"] / 2, t + 5, t + H - 6)]},
           {"name": "camera (buy)", "parts": [{"op": "add", "shape": "box", "size": [cam, cam - 0.2, cam], "center": [xc, 0, cz], "rotate": [0, -25, 0]}]},
           {"name": "battery (buy)", "parts": [B(-bw / 2 + 12.5, -bw / 2 + 12.5 + d["bat"][0], -d["bat"][1] / 2, d["bat"][1] / 2, zt + 0.05, zt + d["bat"][2])]},
           {"name": f"4 x M3 x {H:g} standoffs (buy)", "parts": [Z(2.5, H - 0.1, (x, y, t + 0.05)) for x, y in corners]}]
    if guards:
        for mx, my, a in motors:
            z0, rr = t + d["mz"] - 6, d["pr"] + 4
            gh = min(14.0, t + H - 0.5 - z0)                                  # the ring stays under the top plate
            g = [{"op": "add", "shape": "tube", "radius": rr, "wall": 1.6, "height": gh, "center": [mx, my, z0]},
                 Z(pad + 4, 2.4, (mx, my, -2.45))]                                                                # hub under the pad
            for s in (0, 120, -120):
                ux, uy = math.cos(math.radians(a + s)), math.sin(math.radians(a + s))
                g.append({"op": "add", "shape": "rod", "from": [mx + ux * (pad + 2.5), my + uy * (pad + 2.5), -1.2],  # clear of the pad
                          "to": [mx + ux * (rr - 0.8), my + uy * (rr - 0.8), z0 + 0.8], "radius": 2.0})
            g += motor_holes(mx, my, a, -3.5, 4)
            bodies.append({"name": f"prop guard {len(bodies) - 3}", "parts": g})
    return {"name": f"fpv drone {size} inch", "voxel": 0.3 if size >= 5 else 0.25, "bodies": bodies + [{"reference": True, **b} for b in buy],
            "notes": f"{size}\" FPV frame, {wb:g} mm motor to motor. Buy: 4 motors ({'12x12 M2' if size == 3 else '16x16 M3'} "
                     f"bolt pattern), {size}\" props, a {'20x20 M2' if size == 3 else '30.5x30.5 M3'} FC + ESC stack, a "
                     f"{'nano (14 mm)' if cam == 14 else 'micro (19 mm)'} FPV camera (M2 screws through the mount), a VTX "
                     f"with an SMA antenna (6.6 mm hole in the antenna mount), 4 x M3 x {H:g} mm standoffs + 8 M3 screws, a "
                     "battery strap (20 mm) through the slots. Motor screws: plate thickness + 3 mm at most (longer ones "
                     "touch the windings). Print the plates and arms in PETG or nylon-CF (5-6 walls, 60 % infill), the "
                     "camera and antenna mounts in TPU. A printed frame is heavier and weaker than carbon: fly it gently "
                     "first. Check your country's drone rules before flying."
                     + (" The arms bolt under the body (2 x M3 each)." if split else "")
                     + (" Prop guards clamp under the motors (the motor screws go through them)." if guards else "")}


def _turn_x(parts: list, deg: float, move: tuple = (0, 0, 0)) -> list:
    """Turns parts around the X axis by deg (then moves them). Only for parts built along X (rotate [0,90,0]: they
    just move) or not rotated (they get rotate [deg,0,0]) — the crank, the flywheel, the connecting rod."""
    a = math.radians(deg)
    mv = lambda p: [p[0] + move[0], p[1] * math.cos(a) - p[2] * math.sin(a) + move[1], p[1] * math.sin(a) + p[2] * math.cos(a) + move[2]]  # noqa: E731
    out = []
    for p in parts:
        q = dict(p)
        if q["shape"] == "rod":
            q["from"], q["to"] = mv(q["from"]), mv(q["to"])
        else:
            q["center"] = mv(q["center"])
            if list(q.get("rotate") or [0, 0, 0]) != ALONG_X:
                q["rotate"] = [deg, 0, 0]
        out.append(q)
    return out


def demo_engine(o: dict) -> dict:
    """A hand-cranked single-cylinder DEMO engine (it shows how an engine works; it does not burn fuel — printed plastic
    softens at about 60 °C): crankcase with a bolted side cover, finned cylinder + head, piston with a wrist pin,
    connecting rod, a two-piece crankshaft (the crank pin glues into the other half, so the rod's big end can go on),
    a flywheel and a crank handle with a spinning grip. crank_angle poses it (0 = piston at the top)."""
    B = _o(o, "bore", 30, 20, 80)                         # under 20 mm the rod doesn't fit the piston
    S = _o(o, "stroke", 30, 12, 80)
    Lr = _o(o, "rod_length", 2 * S, 1.6 * S, 4 * S)
    ang = _o(o, "crank_angle", 0, -360, 360)
    r, g = S / 2, 0.4                                     # crank radius, moving clearance
    rp, rj, rw = max(3.0, B / 7.5), max(4.0, B / 6), max(2.0, B / 12)   # crank pin, journal, wrist pin radii
    ry = min(4.0, B / 7)                                  # the rod's half width (thinner in small bores)
    hp = 0.9 * B                                          # piston height
    wp = 0.45 * hp                                        # wrist pin above the piston's bottom
    # The motion test (6 crank angles) found a wide, short-stroke piston hitting the crank, flywheel and handle: the
    # rod gets as long as it must so the piston's lowest point and the deck stay clear of everything that turns.
    Rw0, be0, xfly, xhandle = r + 2 * rp, rp + g + 4, 16.2, 20.2
    low_need = max(Rw0, be0 + r) + 2
    if B / 2 > xfly:
        low_need = max(low_need, r + 16)                  # the flywheel's reach
    if B / 2 > xhandle:
        low_need = max(low_need, 39.0)                    # the handle + grip's reach
    deck_need = max(39.0 if B / 2 + 10 > xhandle else 0.0, r + 16 if B / 2 + 10 > xfly else 0.0)
    Lr = max(Lr, low_need + wp + S - r, deck_need + wp + 0.35 * S - r)
    top = r + Lr + (hp - wp)                              # piston top at the top of the stroke
    zd = r + Lr - wp - 0.35 * S                           # deck (the piston dips below it at the bottom)
    zh = top + 2                                          # head: 2 mm above the piston at the top
    Rw, wt = r + 2 * rp, 5.0                              # crank webs: radius, thickness
    be = rp + g + 4                                       # big end outer radius
    xb = 4.0                                              # big end half width
    xw0, xw1 = xb + g, xb + g + wt                        # webs
    xp0, xp1 = xw1 + g, xw1 + g + 6                       # side plates (bearings)
    half = max(Rw, B / 2 + 8) + 5
    zb = -(max(Rw, be + r) + 42)                          # base top: the handle (reach ~36) clears it
    X = lambda rad, h, c, op="add": {"op": op, "shape": "cylinder", "radius": rad, "height": h, "center": list(c), "rotate": ALONG_X}
    Z = lambda rad, h, c, op="add", **k: {"op": op, "shape": "cylinder", "radius": rad, "height": h, "center": list(c), **k}
    Bx = lambda x0, x1, y0, y1, z0, z1, op="add", **k: {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                        "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2], **k}
    dflat = lambda x0, x1: Bx(x0, x1, -rj - 1, rj + 1, rj * 0.7, rj + 1, "subtract")   # D-flat on a journal end
    dfill = lambda x0, x1: Bx(x0, x1, -rj - 1, rj + 1, rj * 0.7 + 0.2, rj + 1)       # ... and the D in a bore
    bolts = [(13.5 * B / 30, 13.5 * B / 30), (-13.5 * B / 30, 13.5 * B / 30), (13.5 * B / 30, -13.5 * B / 30), (-13.5 * B / 30, -13.5 * B / 30)]
    # --- fixed parts
    case = [Bx(-45, 45, -half - 12, half + 12, zb - 6, zb, round=2),               # base
            Bx(-xp1, -xp0, -half, half, zb - 1, zd + 1),                         # left side plate (bearing)
            Bx(-B / 2 - 8, B / 2 + 8, -half, half, zd, zd + 6),                   # deck
            X(rj + 0.3, 8, (-xp1 - 1, 0, 0), "subtract"),                         # bearing hole
            Z(B / 2, 8, (0, 0, zd - 1), "subtract")]                              # bore through the deck
    zlow = r + Lr - wp - S                                                        # the piston's lowest point
    travel = Z(B / 2 + g, zd - zlow + 2, (0, 0, zlow - 1), "subtract")            # room for it between the side plates
    case.append(travel)                                                           # (the motion test found it hitting them)
    case += [Z(1.3, 12, (x, y, zd - 6), "subtract") for x, y in bolts]            # M3 pilot holes (cylinder)
    case += [Z(1.3, 10, (xp0 + 3, y, zb - 9), "subtract") for y in (-half + 8, half - 8)]  # ... (cover foot)
    case += [Z(1.7, 8, (xp0 + 3, y, zd - 1), "subtract") for y in (-half + 6, half - 6)]    # M3 clearance (cover top)
    cover = [Bx(xp0, xp1, -half, half, zb + g, zd - g),                          # right side plate (bolted on)
             Bx(xp0, xp1 + 10, -half, half, zb + g, zb + g + 6),                  # its foot
             X(rj + 0.3, 8, (xp0 - 1, 0, 0), "subtract"), travel]
    cover += [Z(1.7, 8, (xp0 + 3, y, zb - 1), "subtract") for y in (-half + 8, half - 8)]
    cover += [Z(1.3, 10, (xp0 + 3, y, zd - 10), "subtract") for y in (-half + 6, half - 6)]
    cyl = [Z(B / 2 + 3.5, zh - zd - 6.3, (0, 0, zd + 6.3)),                      # the cylinder
           Z(B / 2 + 7, 4, (0, 0, zd + 6.3)),                                    # its flange
           {"op": "add", "shape": "tube", "radius": B / 2 + 10, "wall": 7, "height": 2, "center": [0, 0, zd + 14],
            "repeat": {"count": max(1, int((zh - zd - 20) // 6)), "step": [0, 0, 6]}},   # cooling fins
           Z(B / 2, zh - zd - 5, (0, 0, zd + 5), "subtract"),                     # the bore
           Z(B / 2 + 5, 6, (0, 0, zh)),                                          # head
           Z(4, 8, (0, 0, zh + 6)), Z(6, 3, (0, 0, zh + 11))]                    # spark-plug boss (looks)
    cyl += [Z(1.7, 6, (x, y, zd + 5.3), "subtract") for x, y in bolts]
    cyl.append(Bx(-B / 5, B / 5, -B / 2 - 12, -B / 2 + 2, zd + 11, zh - 3, "subtract"))  # a window: watch the piston
    # --- the moving parts, built at the top of the stroke, then posed at crank_angle
    crankA = [X(rj, xp1 + 16 - xw1, (-xp1 - 16, 0, 0)),                          # journal (to the flywheel)
              X(Rw, wt, (-xw1, 0, 0)),                                            # web
              X(rp, xw0 + xw1 - 0.5, (-xw0 - 0.01, 0, r)),                        # crank pin (glues into the other web)
              dflat(-xp1 - 16, -xp1 - 0.2)]                                       # the whole flywheel sits on the flat
    crankB = [X(Rw, wt, (xw0, 0, 0)), X(rp + 0.2, wt + 1, (xw0 - 0.5, 0, r), "subtract"),
              X(rj, xp1 + 18 - xw1, (xw1, 0, 0)), dflat(xp1 + 2, xp1 + 18)]
    fly = [X(r + 14, 10, (-xp1 - 10.4, 0, 0)), X(rj + 0.2, 12, (-xp1 - 11.4, 0, 0), "subtract"), dfill(-xp1 - 10.4, -xp1 - 0.4)]
    fly += [X(5, 12, (-xp1 - 11.4, (r + 5) * math.sin(math.radians(a2)), (r + 5) * math.cos(math.radians(a2))), "subtract")
            for a2 in range(0, 360, 72)]                                          # lightening holes
    xa0, xa1, reach = xp1 + 4.4, xp1 + 10.4, 30.0
    handle = [X(9, xa1 - xa0, (xa0, 0, 0)), Bx(xa0, xa1, -reach, 0, -6, 6),     # hub + arm
              X(rj + 0.2, 8, (xa0 - 1, 0, 0), "subtract"), dfill(xa0, xa1),
              X(4, 24, (xa1, -reach, 0))]                                          # the pin for the grip
    grip = [X(7, 21, (xa1 + 0.4, -reach, 0)), X(4.4, 23, (xa1 - 0.6, -reach, 0), "subtract")]
    rod = [X(be, 2 * xb, (-xb, 0, 0)), X(rp + g, 2 * xb + 2, (-xb - 1, 0, 0), "subtract"),     # big end
           Bx(-3, 3, -ry, ry, be - 1, Lr - rw - 3),                                              # the rod
           X(rw + 4, 2 * xb, (-xb, 0, Lr)), X(rw + g, 2 * xb + 2, (-xb - 1, 0, Lr), "subtract")]  # small end
    zw = r * math.cos(math.radians(ang)) + math.sqrt(Lr ** 2 - (r * math.sin(math.radians(ang))) ** 2)  # wrist pin height
    lift = zw - (r + Lr)
    piston = [Z(B / 2 - g, hp, (0, 0, r + Lr - wp + lift)),
              Bx(-xb - g, xb + g, -B / 2 + 2.5, B / 2 - 2.5, r + Lr - wp - 1 + lift, r + Lr + rw + 4 + g + lift, "subtract"),  # pocket
              X(rw + 0.1, B, (-B / 2, 0, r + Lr + lift), "subtract")]                                                     # pin hole
    pin_ref = [{"op": "add", "shape": "rod", "from": [-(B / 2 - g - 0.6), 0, r + Lr + lift], "to": [B / 2 - g - 0.6, 0, r + Lr + lift],
                "radius": rw - 0.1, "flat": True}]
    gamma = -math.degrees(math.asin(r * math.sin(math.radians(ang)) / Lr))
    pin_at = (0, -r * math.sin(math.radians(ang)), r * math.cos(math.radians(ang)))
    return {"name": "demo engine", "voxel": 0.25, "bodies": [
        {"name": "crankcase", "parts": case}, {"name": "side cover", "parts": cover}, {"name": "cylinder", "parts": cyl},
        {"name": "piston", "parts": piston}, {"name": "connecting rod", "parts": _turn_x(rod, gamma, pin_at)},
        {"name": "crankshaft (flywheel half)", "parts": _turn_x(crankA, ang)},
        {"name": "crankshaft (handle half)", "parts": _turn_x(crankB, ang)},
        {"name": "flywheel", "parts": _turn_x(fly, ang)}, {"name": "crank handle", "parts": _turn_x(handle, ang)},
        {"name": "handle grip", "parts": _turn_x(grip, ang)},
        {"name": f"{2 * rw:g} mm wrist pin (buy)", "reference": True, "parts": pin_ref}],
        "notes": f"Demo engine: bore {B:g} mm, stroke {S:g} mm, rod {Lr:g} mm. Turn the handle: the crankshaft turns, the "
                 "connecting rod pushes the piston up and down in the cylinder, the flywheel keeps it turning smoothly. "
                 "It shows how an engine works; it can't run on fuel (printed plastic softens at ~60 °C). Assembly: put "
                 "the flywheel half of the crank through the crankcase's bearing, slide the connecting rod onto its crank "
                 "pin, glue the handle half's web onto the pin, fit the piston on the small end with the wrist pin (a "
                 f"{2 * rw:g} mm steel pin or a nail) and push it up into the cylinder, bolt the cylinder on (4 x M3 x 12), "
                 "bolt the side cover over the crank (4 x M3 x 12), press the flywheel and the handle onto the D-flats. "
                 "Print the crank halves lying on their webs, everything else flat side down; 0.4 mm gaps on all moving parts."}


def _magazine(N: int, Ld: float, x0: float, push: float = 0.0) -> tuple[list, dict]:
    """A spring-loaded stick magazine for N foam darts lying along X (Nerf Elite: 12.7 mm): the top dart's back end at
    x0, its axis at z = 0 (the bore line), held down by two feed lips 0.45 mm over its edges; the slot between the lips
    lets a 11 mm bolt through; open at the top front (the dart leaves forward) and top back (the bolt comes in).
    push = how far the stack is pressed down (the bolt sitting over it). -> (bodies, sizes)"""
    dd, w, gap = 12.7, 1.8, 0.35
    iw, il = dd + 0.7, Ld + 1.5                                  # inside width / length
    xi0, xi1 = x0 - 0.75, x0 + Ld + 0.75                         # inside, back to front
    zl = 2.6                                                     # the lips' underside
    top_z = -push                                                # the top dart's axis now
    f_top = top_z - (N - 1) * dd - dd / 2 - 0.5                  # the follower's top face
    zf = -(N - 1) * dd - dd / 2 - 0.5 - 10 - 12.5 - 20           # the inside floor (room for a 12.5 mm push)
    zn = -31.5                                                   # the catch notch (back face), where the well's catch is
    B = lambda a0, a1, b0, b1, c0, c1, op="add": {"op": op, "shape": "box", "size": [a1 - a0, b1 - b0, c1 - c0],
                                                  "center": [(a0 + a1) / 2, (b0 + b1) / 2, (c0 + c1) / 2]}
    body = [B(xi0 - w, xi1 + w, -iw / 2 - w, iw / 2 + w, zf, zl + 1.8),
            B(xi0, xi1, -iw / 2, iw / 2, zf - 1, zl, "subtract"),                        # the inside (open bottom)
            B(xi0 - 1, xi1 + w + 1, -5.9, 5.9, zl - 0.1, zl + 2, "subtract"),            # slot between the feed lips
            B(xi1 - 1, xi1 + w + 1, -iw / 2, iw / 2, -dd / 2 - 0.6, zl, "subtract"),     # top front: the dart goes out
            B(xi0 - w - 1, xi0 + 1, -5.9, 5.9, -6.2, zl + 2, "subtract"),                # top back: the bolt comes in
            B(xi0 - w - 0.1, xi0 - w + 1.2, -iw / 2 - w - 1, iw / 2 + w + 1, zn, zn + 3, "subtract"),  # catch notch
            {"op": "subtract", "shape": "cylinder", "radius": 1.1, "height": iw + 2 * w + 2, "center": [(xi0 + xi1) / 2, -iw / 2 - w - 1, zf + 2.5],
             "rotate": ALONG_Y}]                                                           # M2 screw through the baseplate's lip
    follower = [B(xi0 + 0.4, xi1 - 0.4, -iw / 2 + 0.4, iw / 2 - 0.4, f_top - 10, f_top)]
    base = [B(xi0 - w, xi1 + w, -iw / 2 - w, iw / 2 + w, zf - 3.4, zf - 0.4),
            B(xi0 + 0.3, xi1 - 0.3, -iw / 2 + 0.3, iw / 2 - 0.3, zf - 0.4, zf + 4),          # its lip, inside the body
            {"op": "subtract", "shape": "cylinder", "radius": 0.8, "height": iw + 2, "center": [(xi0 + xi1) / 2, -iw / 2 - 1, zf + 2.5],
             "rotate": ALONG_Y}]
    sp_len = (f_top - 10 - 0.9) - (zf + 4 + 0.9)                   # the wire's round ends need the room
    springs = [{"op": "add", "shape": "helix", "radius": 4.6, "radius2": 0.6, "height": sp_len, "turns": max(3, sp_len / 5),
                "center": [x, 0, zf + 4.9]} for x in (xi0 + il * 0.28, xi0 + il * 0.72)]
    darts = [{"op": "add", "shape": "cylinder", "radius": 6.3, "height": Ld, "center": [x0, 0, top_z - k * dd], "rotate": ALONG_X}
             for k in range(N)]
    bodies = [{"name": "magazine", "parts": body}, {"name": "magazine follower", "parts": follower},
              {"name": "magazine baseplate", "parts": base},
              {"name": "2 magazine springs (buy)", "reference": True, "parts": springs},
              {"name": f"{N} darts (buy)", "reference": True, "parts": darts}]
    return bodies, {"xo0": xi0 - w, "xo1": xi1 + w, "yo": iw / 2 + w, "zf": zf, "zn": zn, "top": zl + 1.8}


def dart_magazine(o: dict) -> dict:
    """A spring-loaded stick magazine for foam darts (Nerf Elite 12.7 mm, full 72 mm or half-length): body with feed
    lips, a follower, 2 springs, a screwed-on baseplate, a notch for a magazine catch."""
    N = int(_o(o, "darts", 10, 4, 13))                          # 13 darts = 220 mm tall: the most a printer takes
    Ld = _o(o, "dart_length", 72, 38, 76)
    bodies, _ = _magazine(N, Ld, -Ld / 2)
    return {"name": f"dart magazine ({N})", "voxel": 0.25, "bodies": bodies,
            "notes": f"{N} darts of {Ld:g} mm. Load: press each dart down between the feed lips from the top, flat end to "
                     "the back. Buy 2 compression springs ~9 mm wide, 60-80 mm long (or cut a pen spring set), and an M2 "
                     "x 16 screw for the baseplate. Print the body standing up, 0.2 mm layers; smooth the lips with a file "
                     "if darts stick. The notch on the back is for the blaster's magazine catch."}


def mag_pistol(o: dict) -> dict:
    """A magazine-fed foam-dart blaster: the dart_blaster's spring plunger + trigger, and in front of the air chamber a
    BOLT (an 11 mm air tube sliding on a nozzle) that takes the top dart from a spring-loaded magazine and pushes it
    into the barrel. Prime (knob back until it clicks), pull the bolt back (a dart pops up), push it forward (the dart
    goes into the barrel), pull the trigger. A flexure catch in the magazine well holds the magazine."""
    Ld = _o(o, "dart_length", 72, 38, 76)
    N = int(_o(o, "darts", 8, 4, 14))
    blen = _o(o, "barrel_length", 110, Ld + 20, 300)
    base = dart_blaster({k: v for k, v in o.items() if k not in ("barrel_length", "dart_diameter")})
    stroke = _o(o, "stroke", 50, 20, 120)
    cid = _o(o, "chamber_diameter", 26, 16, 50) if _o(o, "chamber_diameter", 26, 0, 99) >= 22 else 26
    rco = cid / 2 + 2.4
    front = 30.0 + 10.0 + stroke + 1
    br, bi, g = 5.5, 4.0, 0.4                                     # bolt outer / inner radius, clearance
    xm0 = front + Ld + 21                                         # where the top dart's back end sits
    xb0 = xm0 + Ld + 2.95                                         # the barrel's back end = the bolt's front, forward
    Lb = Ld + 13.95                                               # bolt length
    xn1 = xm0 - 1                                                 # the nozzle's end
    push = br + 6.3 + g                                           # the bolt forward presses the stack down this much
    mag, m = _magazine(N, Ld, xm0, push)
    X = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_X}
    B = lambda a0, a1, b0, b1, c0, c1, op="add", **k: {"op": op, "shape": "box", "size": [a1 - a0, b1 - b0, c1 - c0],
                                                       "center": [(a0 + a1) / 2, (b0 + b1) / 2, (c0 + c1) / 2], **k}
    bodies = {b["name"]: b for b in base["bodies"]}
    ch = bodies["air chamber"]  # the barrel socket goes; a nozzle for the bolt comes
    ch["parts"] = [p for p in ch["parts"] if not (p["shape"] == "tube" and p["op"] == "add" and p is not ch["parts"][0])]
    ch["parts"].append({"op": "add", "shape": "tube", "radius": bi - g, "wall": 1.2, "height": xn1 - front - 6, "center": [front + 6, 0, 0], "rotate": ALONG_X})
    rear_f = xb0 - Lb                                             # the bolt's back end, forward
    hx = rear_f + 3                                               # its handle (clear of the magazine's back, exact check)
    bolt = [{"op": "add", "shape": "tube", "radius": br, "wall": br - bi, "height": Lb, "center": [rear_f, 0, 0], "rotate": ALONG_X},
            {"op": "add", "shape": "rod", "from": [hx, bi + 0.6, 0], "to": [hx, 20, 0], "radius": 3.0, "flat": True},
            {"op": "add", "shape": "sphere", "radius": 5.5, "center": [hx, 22, 0]}]                        # the handle
    wx0, wx1 = m["xo0"] - g, m["xo1"] + g                        # the magazine well (inside)
    wy = m["yo"] + g
    rx0, rx1 = front + 6.4, wx1 + 14
    travel = Ld + 3.45
    receiver = [B(rx0, rx1, -11, 11, -9, 9, round=1),
                B(wx0 - 2.4, wx1 + 2.4, -wy - 2.4, wy + 2.4, -34, -8.9),                     # the well's skirt
                X(br + g, wx1 - rx0 + 2, (rx0 - 1, 0, 0), "subtract"),                        # the bolt's bore
                B(wx0, wx1, -wy, wy, -35, m["top"] + g, "subtract"),                          # the well
                X(8.35 + 0.3, rx1 - xb0 + 1, (xb0, 0, 0), "subtract"),                       # barrel socket
                B(hx - travel - 3.4, hx + 3.4, 0, 12, -3.4, 3.4, "subtract"),                # the handle's slot
                B(wx0 - 2.5, wx0 - 1.1, -3.8, -3.0, -34.1, -14, "subtract"),                  # the catch flexure:
                B(wx0 - 2.5, wx0 - 1.1, 3.0, 3.8, -34.1, -14, "subtract"),                    # two slots,
                B(wx0 - 2.5, wx0 - 1.2, -3.0, 3.0, -34.1, -14.4, "subtract")]                 # a 1.2 mm tongue
    receiver += [{"op": "subtract", "shape": "cylinder", "radius": 1.7, "height": 6, "center": [x, 0, -10]} for x in (rx0 + 8, wx0 - 8)]
    catch_z = m["zn"] + 1.5                                       # the nub clicks into the magazine's notch
    receiver.append({"op": "add", "shape": "sphere", "radius": 1.0, "center": [wx0 + 0.2, 0, catch_z]})
    frame_add = [B(front - 10, wx0 - 2.8, -12, 12, -(rco + 14) - 2, -(rco + 1.4)),       # a bar under the chamber
                 B(front + 6.4, wx0 - 2.8, -12, 12, -(rco + 1.4) - 0.01, -9.4)]            # ... up to the receiver
    frame_add += [{"op": "subtract", "shape": "cylinder", "radius": 1.3, "height": 10, "center": [x, 0, -17]} for x in (rx0 + 8, wx0 - 8)]
    bodies["frame"]["parts"] += frame_add
    bodies["barrel"]["parts"] = [{"op": "add", "shape": "tube", "radius": 8.35, "wall": 1.85, "height": blen, "center": [xb0 + 0.4, 0, 0], "rotate": ALONG_X}]
    darts = next(b for b in mag if b["name"].endswith("darts (buy)"))
    darts["parts"].append({"op": "add", "shape": "cylinder", "radius": 6.3, "height": Ld, "center": [xb0 + 0.5, 0, 0], "rotate": ALONG_X})
    base["bodies"] = list(bodies.values()) + [{"name": "receiver", "parts": receiver}, {"name": "bolt", "parts": bolt}] + mag
    base["name"] = "magazine pistol"
    base["notes"] = (f"Magazine-fed blaster, {N}-dart magazine, {Ld:g} mm darts. Use: 1) pull the knob at the back until the "
                     "trigger's tooth clicks, 2) pull the bolt handle back - the next dart pops up between the magazine's lips, "
                     "3) push the bolt forward - it pushes the dart into the barrel and seals on it, 4) pull the trigger. The "
                     "bolt slides on the air nozzle: put a 7 x 1.5 mm O-ring or a wrap of PTFE tape on the nozzle. The magazine "
                     "clicks into the well (a flexure catch) - pull it down to remove it. Buy: the dart_blaster's spring, "
                     "O-ring, 3 mm pin and rubber band; 2 magazine springs; 2 x M3 x 12 screws (receiver to frame); an M2 "
                     "screw for the magazine baseplate. Glue the barrel into the receiver. Print PETG for the bolt and the "
                     "catch. Moving parts have 0.4 mm gaps.")
    return base


def cap_grenade(o: dict) -> dict:
    """An airsoft-style IMPACT noise grenade for TOY RING CAPS (the plastic 8-shot rings for toy cap guns): a weighted
    striker rests on a light spring; when the grenade lands, the striker's inertia drives its pin through the floor
    and pops one cap. A pull-pin (with a ring) blocks the striker until it's pulled. The bottom plug holds the ring
    cap and screws off to reload (turn the ring to the next cap); the top cap screws off to reach the striker."""
    R = _o(o, "diameter", 44, 36, 70) / 2              # body outside radius
    Hb = _o(o, "height", 72, 55, 120)
    rc = _o(o, "cap_radius", 10, 7, 13)                 # where the caps sit on their ring (from the centre)
    wall, g, P, c = 3.0, 0.4, 3.0, 0.35
    ri, w = R - wall, 0.25 * 3.0                         # inside radius, thread wire
    zd0, zd1 = 12.0, 15.0                               # the floor between the striker and the cap
    rest = 8.0                                          # striker above the floor at rest (the spring holds it)
    zs0 = zd1 + rest                                    # striker bottom
    tip_bot = zd0 + 1.5                                 # its pin waits inside the floor's hole
    Z = lambda r, h, cz, op="add", x=0.0, y=0.0: {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": [x, y, cz]}
    B = lambda x0, x1, y0, y1, z0, z1, op="add": {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                  "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]}
    zb, zt = 1.5, Hb - 2 - 2 * P                        # thread starts (bottom, top): 2 turns each
    pin_z = zs0 - 0.6 - 1.8                             # the safety pin: just under the striker
    body = [Z(R, Hb, 0), Z(ri, Hb + 2, -1, "subtract"),
            Z(ri + 0.5, zd1 - zd0, zd0),                                                    # the floor
            Z(2.0, zd1 - zd0 + 2, zd0 - 1, "subtract", -rc, 0),                             # the pin's hole
            B(ri - 1.9, ri + 0.5, -2, 2, zd1, Hb - 12),                                     # key rib (no turning)
            _helix(R, w, zb, 2, P), _helix(R, w, zt, 2, P),                                  # threads
            {"op": "subtract", "shape": "cylinder", "radius": 2.2, "height": 2 * R + 4, "center": [12, -R - 2, pin_z], "rotate": ALONG_Y}]
    striker = [Z(ri - g, Hb - 12 - 1 - zs0, zs0),                                         # the weight (ends under the top cap)
               Z(1.5, zs0 - tip_bot + 0.01, tip_bot, "add", -rc, 0),                      # its pin
               Z(4.3, Hb, zs0 - 1, "subtract"),                                           # hole for an M8 bolt (weight)
               B(ri - 2.4, ri + 1, -2.4, 2.4, zs0 - 1, Hb, "subtract")]                    # slot for the key rib
    spin = [{"op": "add", "shape": "rod", "from": [12, -R - 6, pin_z], "to": [12, R + 1.5, pin_z], "radius": 1.8, "flat": True},
            {"op": "add", "shape": "torus", "radius": 7, "radius2": 1.6, "center": [12, -R - 6 - 7, pin_z], "rotate": [0, 90, 0]}]
    # bottom plug: a skirt that screws on, a floor with sound vents, a boss the ring cap lies on (+ a centring peg)
    pr = R + w + c + 2.2
    boss_top = zd0 - 0.3 - 3.0                          # the ring cap (about 3 mm with its domes) sits here
    plug = [Z(pr, 11 + 3.4, -3.4), Z(R + c, 13, -0.4, "subtract"),
            _helix(R, w + c, zb - P, 4, P, "subtract"),
            Z(14, boss_top + 0.4, -0.4), Z(4.2, 1.5, boss_top)]
    plug += [Z(2.0, 5, -4, "subtract", 16.5 * math.cos(math.radians(a)), 16.5 * math.sin(math.radians(a))) for a in range(0, 360, 60)]
    # top cap: screws on, a dome
    ctop = Hb + c
    cap = [Z(pr, ctop - (zt - 1), zt - 1), Z(pr, 3, ctop), Z(pr * 0.6, 6, ctop + 3),     # skirt, top, fuse head
           Z(R + c, ctop - zt + 2, zt - 2, "subtract"),                                   # the inside: cut LAST
           _helix(R, w + c, zt - P, math.ceil((ctop - zt + P) / P), P, "subtract")]
    spring = [{"op": "add", "shape": "helix", "radius": 6.5, "radius2": 0.5, "height": rest - 1.8, "turns": 3, "center": [0, 0, zd1 + 0.9]}]
    ring = [{"op": "add", "shape": "torus", "radius": rc, "radius2": 1.2, "center": [0, 0, boss_top + 1.6]}]
    weight = [Z(4.0, Hb - 12 - 2 - zs0 - 2, zs0 + 1)]
    return {"name": "cap impact grenade", "voxel": 0.25, "bodies": [
        {"name": "body", "parts": body}, {"name": "striker", "parts": striker}, {"name": "safety pin", "parts": spin},
        {"name": "bottom plug (holds the cap)", "parts": plug}, {"name": "top cap", "parts": cap},
        {"name": "light spring (buy)", "reference": True, "parts": spring},
        {"name": "M8 bolt as weight (buy)", "reference": True, "parts": weight},
        {"name": "toy ring cap (buy)", "reference": True, "parts": ring}],
        "notes": "A noise-maker for airsoft games. Use ONLY toy ring caps (the plastic 8-shot rings for toy cap guns) - never "
                 "shotgun primers, gunpowder or fireworks: the plastic body is not made for them. Load: unscrew the bottom "
                 "plug, put a ring cap on the boss (domes up), screw it back. Push the safety pin in. Pull the pin and throw: "
                 "on landing the weighted striker's pin pops one cap. Turn the ring for the next cap. Buy: a light spring "
                 "(~14 mm wide, ~10 mm long, weak), an M8 x 40 bolt with nuts as the striker's weight. Print PETG, 4 walls, "
                 "100 % infill for the striker. Wear eye protection, it is loud - and follow your field's rules."}


def _turn_y(parts: list, deg: float, pivot: tuple) -> list:
    """Turns parts (built along Z, rotated only around Y) by deg around the Y axis through pivot."""
    a = math.radians(deg)
    def mv(p):
        x, y, z = p[0] - pivot[0], p[1] - pivot[1], p[2] - pivot[2]
        return [x * math.cos(a) + z * math.sin(a) + pivot[0], y + pivot[1], -x * math.sin(a) + z * math.cos(a) + pivot[2]]
    out = []
    for p in parts:
        q = dict(p)
        if q["shape"] == "rod":
            q["from"], q["to"] = mv(q["from"]), mv(q["to"])
        else:
            q["center"] = mv(q["center"])
            r = list(q.get("rotate") or [0, 0, 0])
            q["rotate"] = [r[0], r[1] + deg, r[2]]
        out.append(q)
    return out


def robot_hand(o: dict) -> dict:
    """A tendon-driven robotic hand (e-NABLE / InMoov idea): a palm, 4 fingers of 3 segments and a thumb of 2, pin
    joints (3 mm pins, 0.4 mm play), a fishing-line channel on the palm side (pull = the finger closes) and one on the
    back (elastic = it opens), V-notches so each joint bends about 90 degrees."""
    s = _o(o, "scale", 1.0, 0.6, 2.0)
    pin = _o(o, "pin_diameter", 3.0, 2.0, 5.0)
    fw, t, gap = 16 * s, 16 * s, 0.4
    rj, cz = t / 2, t / 2 + gap                    # joint radius, the zone around each pin
    W, Hp = 4 * fw + 3 * 3 * s + 8 * s, 70 * s
    lengths = [(38, 24, 22), (42, 27, 23), (40, 25, 22), (32, 20, 19)]  # index, middle, ring, little (pin to pin)
    X = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_X}
    B = lambda x0, x1, y0, y1, z0, z1, op="add": {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                  "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]}
    yf, yb = -t / 2 + 3 * s, t / 2 - 3 * s        # tendon channels: front (palm side) and back

    def lower_joint(xc, zj):  # the cheeks on the lower piece, around the pin at zj
        out = []
        for side in (-1, 1):
            x0 = xc + side * fw / 2 - (3 * s if side > 0 else 0)
            out += [B(x0, x0 + 3 * s, -t / 2, t / 2, zj - cz, zj), X(rj, 3 * s, (x0, 0, zj))]
        return out + [B(xc - fw / 2 + 3 * s, xc + fw / 2 - 3 * s, -t / 2 - 1, t / 2 + 1, zj - rj - 0.01, zj + rj + 1, "subtract")]

    def upper_joint(xc, zj):  # the tongue on the upper piece, between the cheeks
        tw = fw / 2 - 3 * s - gap
        return [B(xc - tw, xc + tw, -t / 2, t / 2, zj, zj + cz), X(rj, 2 * tw, (xc - tw, 0, zj))]

    def holes(xc, zj):  # pin hole + the palm-side V-notch that lets the joint bend
        return [X(pin / 2 + 0.25, fw + 2, (xc - fw / 2 - 1, 0, zj), "subtract"),
                {"op": "subtract", "shape": "box", "size": [fw + 2, 2 * cz, 2 * cz], "center": [xc, -t / 2 - cz * 0.35, zj],
                 "rotate": [45, 0, 0]}]

    def channels(xc, z0, z1, blind_top=None):
        top = blind_top if blind_top is not None else z1
        return [{"op": "subtract", "shape": "cylinder", "radius": 1.0 * s, "height": top - z0 + 2, "center": [xc, y, z0 - 1]}
                for y in (yf, yb)]

    bodies, pins = [], []
    palm = [B(-W / 2, W / 2, -t / 2 - 4 * s, t / 2 + 4 * s, 0, Hp)]
    for i, (lp, lm, ld) in enumerate(lengths):
        xc = -W / 2 + 4 * s + fw / 2 + i * (fw + 3 * s)
        lp, lm, ld = lp * s, lm * s, ld * s
        z0 = Hp + cz                                # knuckle pin
        z1, z2, ztop = z0 + lp, z0 + lp + lm, z0 + lp + lm + ld
        palm += lower_joint(xc, z0) + holes(xc, z0) + channels(xc, 0, Hp + cz)
        name = ["index", "middle", "ring", "little"][i]
        bodies.append({"name": f"{name} 1", "parts": upper_joint(xc, z0) + [B(xc - fw / 2, xc + fw / 2, -t / 2, t / 2, z0 + cz, z1 - cz)]
                       + lower_joint(xc, z1) + holes(xc, z0) + holes(xc, z1) + channels(xc, z0 - rj, z1)})
        bodies.append({"name": f"{name} 2", "parts": upper_joint(xc, z1) + [B(xc - fw / 2, xc + fw / 2, -t / 2, t / 2, z1 + cz, z2 - cz)]
                       + lower_joint(xc, z2) + holes(xc, z1) + holes(xc, z2) + channels(xc, z1 - rj, z2)})
        rt = min(rj, (ld - cz) / 2)  # the rounded tip stays above the joint (a short little finger's tip hit it)
        bodies.append({"name": f"{name} 3", "parts": upper_joint(xc, z2) + [B(xc - fw / 2, xc + fw / 2, -t / 2, t / 2, z2 + cz, ztop - rt),
                       X(rt, fw, (xc - fw / 2, 0, ztop - rt))] + holes(xc, z2) + channels(xc, z2 - rj, ztop, ztop - 4 * s)
                       + [X(1.0 * s, fw + 2, (xc - fw / 2 - 1, yf, ztop - 5 * s), "subtract")]})  # knot hole
        pins += [{"op": "add", "shape": "rod", "from": [xc - fw / 2, 0, z], "to": [xc + fw / 2, 0, z], "radius": pin / 2 - 0.05, "flat": True}
                 for z in (z0, z1, z2)]
    # the thumb: built upright at x = 0, then tilted 50 degrees outwards on the palm's -X side (next to the index)
    lt1, lt2, zb = 32 * s, 26 * s, 12 * s
    z0, z1, ztop = zb + cz, zb + cz + lt1, zb + cz + lt1 + lt2
    post = [B(-fw / 2, fw / 2, -t / 2, t / 2, -20 * s, zb)] + lower_joint(0, z0) + holes(0, z0) + channels(0, -20 * s, z0)
    th1 = upper_joint(0, z0) + [B(-fw / 2, fw / 2, -t / 2, t / 2, z0 + cz, z1 - cz)] + lower_joint(0, z1) + holes(0, z0) + holes(0, z1) + channels(0, z0 - rj, z1)
    rt = min(rj, (lt2 - cz) / 2)
    th2 = (upper_joint(0, z1) + [B(-fw / 2, fw / 2, -t / 2, t / 2, z1 + cz, ztop - rt), X(rt, fw, (-fw / 2, 0, ztop - rt))]
           + holes(0, z1) + channels(0, z1 - rj, ztop, ztop - 4 * s) + [X(1.0 * s, fw + 2, (-fw / 2 - 1, yf, ztop - 5 * s), "subtract")])
    tp = [{"op": "add", "shape": "rod", "from": [-fw / 2, 0, z], "to": [fw / 2, 0, z], "radius": pin / 2 - 0.05, "flat": True} for z in (z0, z1)]
    dx, dz = -(W / 2 - 2 * s), 28 * s
    shift = lambda v: [v[0] + dx, v[1], v[2] + dz]  # noqa: E731

    def place(parts):  # tilt the thumb 50 degrees outwards, then move it to the palm's index side
        out = []
        for p in _turn_y(parts, -50, (0, 0, 0)):
            out.append(dict(p, **({"from": shift(p["from"]), "to": shift(p["to"])} if p["shape"] == "rod"
                                  else {"center": shift(p["center"])})))
        return out
    palm += place(post)
    bodies = [{"name": "palm", "parts": palm}] + bodies + [{"name": "thumb 1", "parts": place(th1)}, {"name": "thumb 2", "parts": place(th2)},
              {"name": f"{pin:g} mm pins (buy)", "reference": True, "parts": pins + place(tp)}]
    return {"name": "robotic hand", "voxel": 0.3, "bodies": bodies,
            "notes": f"Tendon hand, {len(bodies) - 2} printed parts. Joints: {pin:g} mm steel pins (or 1.75 mm filament x2) in "
                     f"{pin + 0.4:g} mm holes. Thread fishing line (0.5-0.8 mm) through the palm-side channels and knot it in "
                     "each fingertip's cross hole: pulling closes the finger. Elastic cord in the back channels opens it. "
                     "Pull the lines by hand, with a wrist lever, or with servos (MG996R) under the palm. Print every "
                     "segment standing up (joints horizontal), 3 walls, PLA or PETG."}


def exo_elbow(o: dict) -> dict:
    """An exoskeleton / brace joint for the elbow (or knee): an upper and a lower C-shaped cuff, a side hinge on a
    6 mm bolt, and a range-of-motion stop (a peg in an arc slot: 0 to max_bend degrees). Strap slots for 25 mm straps."""
    Ru = _o(o, "arm_diameter", 90, 50, 200) / 2
    Lc = _o(o, "cuff_length", 110, 50, 250)
    bend = _o(o, "max_bend", 120, 30, 150)
    wall, gap = 3.0, 0.4
    X = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_X}
    B = lambda x0, x1, y0, y1, z0, z1, op="add": {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],
                                                  "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]}
    xa, xb = Ru + 1, Ru + 6                          # upper hinge plate (inner)
    xc, xd = xb + gap, xb + gap + 5                  # lower hinge plate (outer)

    def cuff(z0):
        return [{"op": "add", "shape": "tube", "radius": Ru + wall, "wall": wall, "height": Lc, "center": [0, 0, z0]},
                B(-0.7 * Ru, 0.7 * Ru, -Ru - 8, -0.35 * Ru, z0 - 1, z0 + Lc + 1, "subtract")] + [  # the C opening (front)
                B(-15, 15, Ru - 5, Ru + wall + 5, z, z + 5, "subtract") for z in (z0 + 0.2 * Lc, z0 + 0.8 * Lc - 5)]  # strap slots
    arc = lambda a, r: (r * math.sin(math.radians(a)), r * math.cos(math.radians(a)))  # (y, z) around the hinge
    upper = cuff(40) + [B(xa, xb, -9, 9, 0, 60), X(18, xb - xa, (xa, 0, 0)), X(3.3, 8, (xa - 1, 0, 0), "subtract"),
                        X(3.0, 4.0, (xb, *arc(90, 12)))]                     # the stop peg (into the lower plate's slot)
    lower = cuff(-40 - Lc) + [B(xc, xd, -9, 9, -45, 0), X(18, xd - xc, (xc, 0, 0)), B(xa, xd, -9, 9, -60, -25),
                              X(3.3, 8, (xc - 1, 0, 0), "subtract")]  # 6.6 mm = the standard clearance hole for M6
    lower += [X(3.4, 7, (xc - 1, *arc(90 - bend * k / 12, 12)), "subtract") for k in range(13)]  # the arc slot
    return {"name": "exoskeleton elbow joint", "voxel": 0.3, "bodies": [
        {"name": "upper cuff", "parts": upper}, {"name": "lower cuff", "parts": lower},
        {"name": "M6 bolt (buy)", "reference": True, "parts": [{"op": "add", "shape": "rod", "from": [xa - 3, 0, 0], "to": [xd + 3, 0, 0],
                                                                "radius": 3.0, "flat": True}]}],
        "notes": f"For an arm (or leg) about {2 * Ru:g} mm across with padding. The hinge turns 0 to {bend:g} degrees: a peg "
                 "on the upper plate runs in an arc slot of the lower one. Buy an M6 x 20 bolt + a nyloc nut (+2 washers) and "
                 "25 mm velcro straps; line the cuffs with 3-5 mm foam. Print the cuffs standing up, PETG, 4 walls. "
                 "A passive brace: for a powered exoskeleton, mount a servo or linear actuator between the two bars."}



# ---------------------------------------------------------------- robot arm (hobby servos, sized by the torque it needs)
SERVOS = {  # hobby servo sizes (mm, g). The case L x W x H (H = below its top face); the ears: span E, thickness et, their
    # top ez below the top face; the shaft sits s from one end of the case; boss (br, bh) and horn (hr, ht) above the top
    # face; ear screws (tap radius) and the idler bolt (tap radius: M3 / M4)
    "micro": {"L": 23.0, "W": 12.4, "H": 22.6, "E": 32.4, "et": 2.5, "ez": 4.4, "s": 6.0, "br": 2.7, "bh": 4.0,
              "hr": 8.5, "ht": 2.0, "g": 13, "screw": 0.9, "bolt": 1.25},
    "standard": {"L": 40.7, "W": 19.9, "H": 37.2, "E": 54.5, "et": 2.6, "ez": 8.5, "s": 10.2, "br": 6.0, "bh": 5.5,
                 "hr": 12.0, "ht": 2.5, "g": 60, "screw": 1.25, "bolt": 1.25},
    "large": {"L": 66.0, "W": 30.0, "H": 50.0, "E": 83.0, "et": 3.5, "ez": 11.0, "s": 16.5, "br": 8.0, "bh": 6.5,
              "hr": 19.0, "ht": 3.5, "g": 165, "screw": 1.6, "bolt": 1.7},
}
SERVO_PICKS = [  # (kg·cm it holds, the servo, its size): the first strong enough for the need (x2 margin) is chosen
    (2.2, "MG90S (metal gears, 2.2 kg·cm)", "micro"), (10.0, "MG996R (10 kg·cm)", "standard"),
    (20.0, "DS3218 (20 kg·cm)", "standard"), (35.0, "DS3235 (35 kg·cm at 7.4 V)", "standard"),
    (60.0, "DS5160 (60 kg·cm)", "large"), (150.0, "DS51150 (150 kg·cm)", "large")]
ARM_SIZES = {"micro": (2.4, 4.0, 6.0, 2.5, 0.12), "standard": (3.2, 6.0, 8.0, 3.0, 0.35), "large": (4.0, 8.0, 10.0, 4.0, 0.8)}
# per size: wall, U-plate thickness, crossbar thickness, frame margin around the ears, printed link weight (g per mm)


def _rm(deg) -> list:
    """Turns as a 3x3 matrix (rows): X first, then Y, then Z — like the engines."""
    a, b, c = (math.radians(float(x or 0)) for x in (list(deg or []) + [0, 0, 0])[:3])
    X = [[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]]
    Y = [[math.cos(b), 0, math.sin(b)], [0, 1, 0], [-math.sin(b), 0, math.cos(b)]]
    Z = [[math.cos(c), -math.sin(c), 0], [math.sin(c), math.cos(c), 0], [0, 0, 1]]
    return _mm3(Z, _mm3(Y, X))


def _mm3(A, B) -> list:
    return [[sum(A[i][t] * B[t][j] for t in range(3)) for j in range(3)] for i in range(3)]


def _md(M) -> list:
    """A turn matrix back to [x, y, z] degrees."""
    b = math.asin(max(-1.0, min(1.0, -M[2][0])))
    if abs(M[2][0]) > 0.99999:
        return [0.0, round(math.degrees(b), 4), round(math.degrees(math.atan2(-M[0][1], M[1][1])), 4)]
    return [round(math.degrees(math.atan2(M[2][1], M[2][2])), 4), round(math.degrees(b), 4),
            round(math.degrees(math.atan2(M[1][0], M[0][0])), 4)]


def _place(parts: list, R: list, at) -> list:
    """Parts built in their own frame -> turned by R (a 3x3 matrix, rows) and moved to `at`."""
    mv = lambda v: [round(sum(R[i][j] * v[j] for j in range(3)) + at[i], 4) for i in range(3)]  # noqa: E731
    out = []
    for p in parts:
        q = dict(p)
        if q["shape"] == "rod":
            q["from"], q["to"] = mv(q["from"]), mv(q["to"])
        else:
            q["center"] = mv(q["center"])
            q["rotate"] = _md(_mm3(R, _rm(q.get("rotate") or [0, 0, 0])))
        out.append(q)
    return out


def _qty(o: dict, key: str, default: float, lo: float, hi: float, unit: str) -> float:
    """A size or weight from the options — also "30 cm", "0.3 m", "1 kg", "500 g" (the AI copies the user's words)."""
    v = o.get(key, default)
    if isinstance(v, str):
        import re
        m = re.match(r"\s*(-?\d+(?:[.,]\d+)?)\s*([a-zA-Z]*)", v)
        if not m:
            return default
        x, u = float(m.group(1).replace(",", ".")), m.group(2).lower()
        scale = ({"mm": 1, "cm": 10, "m": 1000, "in": 25.4, "inch": 25.4} if unit == "mm" else
                 {"g": 1, "gr": 1, "kg": 1000, "lb": 453.6, "lbs": 453.6, "oz": 28.35}).get(u, 1)
        v = x * scale
    return _o({key: v}, key, default, lo, hi)


# the servo frames (rows of a matrix whose COLUMNS say where the servo's own X (case length), Y (width), Z (shaft) go)
UP = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]             # base: shaft up, case along +X
SIDE_DOWN = [[0, -1, 0], [0, 0, 1], [-1, 0, 0]]    # shoulder / elbow: shaft along +Y, case hanging down (-Z)
SIDE_BACK = [[-1, 0, 0], [0, 0, 1], [0, 1, 0]]     # gripper: shaft along +Y, case lying back along the forearm (-X)


def robot_arm(o: dict) -> dict:
    """A 4-servo desktop robot arm: base (turns), shoulder, elbow, claw. Each joint like the metal servo-kit arms: the
    servo sits in a frame of one link, the next link is a U-bracket around it, fixed to the horn on one side and turning
    on a bolt (the idler) on the other — so every link stays on the middle line. The servos are sized from the torque
    the arm needs held straight out (payload x reach + the arm's own weight, x2 margin — the engineering calculator's
    formula): micro (MG90S), standard (MG996R / DS3218 / DS3235) or large (DS5160 / DS51150) pockets."""
    reach = _qty(o, "reach", 300, 120, 700, "mm")              # shoulder axis to the claw's tip, arm stretched out
    payload = _qty(o, "payload", 200, 0, 5000, "g")
    want = str(o.get("servo") or "auto").lower()
    want = next((k for k in SERVOS if k in want), "auto")
    gcls = "micro" if payload <= 300 else "standard"           # the claw's own servo
    dg = SERVOS[gcls]
    tj, jh, Lj = (4.0, 8.0, 40.0) if gcls == "micro" else (6.0, 12.0, 60.0)  # claw: thickness, finger height, length
    m_grip = 15 if gcls == "micro" else 45

    def layout(cls):
        d = SERVOS[cls]
        w, tp, tc, m, k = ARM_SIZES[cls]
        cx = d["L"] / 2 - d["s"]
        rc = max(d["s"] + (d["E"] - d["L"]) / 2 + m, d["hr"]) + 2              # U crossbar: clear of the servo frame
        L1min = rc + tc + cx + d["E"] / 2 + m + 5
        cxg = dg["L"] / 2 - dg["s"]
        L2min = rc + tc + 5 + cxg + dg["E"] / 2 + ARM_SIZES[gcls][3]
        L1 = max(L1min, (reach - Lj) / 2)
        L2 = max(L2min, reach - Lj - L1)
        tau = (payload * (L1 + L2 + Lj) + k * L1 * L1 / 2 + d["g"] * L1 + k * L2 * (L1 + L2 / 2)
               + dg["g"] * (L1 + L2) + m_grip * (L1 + L2 + Lj / 2)) / 10000           # kg·cm at the shoulder
        tau_e = (payload * (L2 + Lj) + k * L2 * L2 / 2 + dg["g"] * L2 + m_grip * (L2 + Lj / 2)) / 10000
        return d, w, tp, tc, m, cx, rc, L1, L2, tau, tau_e

    order = ["micro", "standard", "large"]
    cap = {"micro": 2.2, "standard": 35.0, "large": 150.0}
    for cls in ([want] if want in SERVOS else order):
        d, w, tp, tc, m, cx, rc, L1, L2, tau, tau_e = layout(cls)
        if 2 * tau <= cap[cls]:
            break
    pick = lambda need: next((n for c, n, s in SERVO_PICKS if s == cls and c >= need), None)  # noqa: E731
    sv_sh, sv_el = pick(2 * tau), pick(2 * tau_e)
    p, g, bl = 0.3, 0.4, 2.5                     # pocket play, moving gap, idler boss length
    L, W, H, E, et, ez, s, bh, hr, ht = (d[x] for x in ("L", "W", "H", "E", "et", "ez", "s", "bh", "hr", "ht"))
    bw = 2 * (hr + w)                            # U-plate width (covers the horn)
    X = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c), "rotate": ALONG_Y}  # noqa: E731
    Zc = lambda r, h, c, op="add": {"op": op, "shape": "cylinder", "radius": r, "height": h, "center": list(c)}  # noqa: E731
    B = lambda x0, x1, y0, y1, z0, z1, op="add": {"op": op, "shape": "box", "size": [x1 - x0, y1 - y0, z1 - z0],  # noqa: E731
                                                  "center": [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2]}

    def servo(dd):        # the servo itself (bought), in its own frame: shaft = +Z at the origin, on its top face
        c = dd["L"] / 2 - dd["s"]
        return [B(c - dd["L"] / 2, c + dd["L"] / 2, -dd["W"] / 2, dd["W"] / 2, -dd["H"], 0),
                B(c - dd["E"] / 2, c + dd["E"] / 2, -dd["W"] / 2, dd["W"] / 2, -dd["ez"] - dd["et"], -dd["ez"]),
                Zc(dd["br"], dd["bh"], (0, 0, 0)), Zc(dd["hr"], dd["ht"], (0, 0, dd["bh"]))]

    def frame(dd, ww, mm, idler):  # what holds it: a block around the case, the ears resting on its face (+ idler boss)
        c, face = dd["L"] / 2 - dd["s"], -(dd["ez"] + dd["et"])
        bot = -dd["H"] - 1 - ww
        add = [B(c - dd["E"] / 2 - mm, c + dd["E"] / 2 + mm, -dd["W"] / 2 - p - ww, dd["W"] / 2 + p + ww, bot, face - 0.2)]  # 0.2 mm under the ears (touching faces read as a collision)
        if idler:
            add.append(Zc(dd["bolt"] + 3.5, bl + 0.01, (0, 0, bot - bl)))
        return add

    def pocket(dd, ww, idler):  # the cuts: the case (+ play), the ear screws, a cable slot, the idler bolt's tap hole
        c, face = dd["L"] / 2 - dd["s"], -(dd["ez"] + dd["et"])
        off = dd["E"] / 2 - (dd["E"] - dd["L"]) / 4
        cut = [B(c - dd["L"] / 2 - p, c + dd["L"] / 2 + p, -dd["W"] / 2 - p, dd["W"] / 2 + p, -dd["H"] - 1, face + 0.1, "subtract"),
               Zc(dd["screw"], 10, (c - off, 0, face - 9.9), "subtract"), Zc(dd["screw"], 10, (c + off, 0, face - 9.9), "subtract"),
               B(c + dd["L"] / 2 - 9, c + dd["L"] / 2 - 2, 0, dd["W"] / 2 + p + ww + 1, -dd["H"] + 1, -dd["H"] + 8, "subtract")]
        if idler:
            bot = -dd["H"] - 1 - ww
            cut.append(Zc(dd["bolt"] + 0.05, bl + ww - 0.8, (0, 0, bot - bl - 0.1), "subtract"))
        return cut

    # ---- the numbers: Y = the joint axes, centred so each U-bracket is symmetric about y = 0
    y0 = (H + 1 + w + bl + g - bh - ht - 0.2) / 2           # the joint servos' top face (shaft side)
    yA0, yB1 = y0 + bh + ht + 0.2, y0 - H - 1 - w - bl - g  # inner faces of the U's horn plate (A) and idler plate (B)
    yc0, yc1 = y0 - H - 1 - w, y0 - ez - et                 # the frames' slab (floor .. the face the ears sit on)
    zf = H - ez - et + 10                                   # base deck: the base servo's ears sit on it
    zt = zf + ez + et                                       # base servo top face
    ztb, tt = zt + bh + 0.2, 8.0                            # turntable bottom, thickness
    Rb = max(abs(cx - E / 2), abs(cx + E / 2), math.hypot(L - s + p, W / 2 + p), math.hypot(s + p, W / 2 + p)) + w + 2
    Rb = max(Rb, math.hypot(max(abs(yc0), abs(yc1)), W / 2 + p + w) + 2)
    zs = ztb + tt + cx + E / 2 + m - 0.5                    # shoulder axis (its frame 0.5 mm into the disk)
    ze = zs + L1                                            # elbow axis (upper arm straight up)
    xg = L2                                                 # claw servo shaft (forearm straight forward)
    yg0 = -(dg["bh"] + dg["ht"] + 0.2 + tj / 2)             # claw servo top face: its jaw on the middle line
    yj0 = yg0 + dg["bh"] + dg["ht"] + 0.2                   # the jaw slab
    wg, mg = ARM_SIZES[gcls][0], ARM_SIZES[gcls][3]
    cxg = dg["L"] / 2 - dg["s"]
    hy0, hy1 = yg0 - dg["H"] - 1 - wg, yg0 - dg["ez"] - dg["et"]   # the claw servo frame's slab
    hx0 = xg - cxg - dg["E"] / 2 - mg                       # the claw frame's back
    hz0 = ze - dg["W"] / 2 - p - wg                         # ... and its bottom
    zfj = ze - (dg["hr"] + 1.5) - g                         # top of the fixed finger (under the moving jaw's disk)
    sh_at, el_at, base_at, gr_at = (0, y0, zs), (0, y0, ze), (0, 0, zt), (xg, yg0, ze)

    def u_plates(axis_xz, along):  # a U-bracket's two side plates + crossbar, from a joint axis along +Z or +X
        ax, az = axis_xz
        parts = []
        for ya, yb in ((yA0, yA0 + tp), (yB1 - tp, yB1)):
            parts += [X(bw / 2, yb - ya, (ax, ya, az)),
                      (B(ax - bw / 2, ax + bw / 2, ya, yb, az, az + rc + tc) if along == "z" else
                       B(ax, ax + rc + tc, ya, yb, az - bw / 2, az + bw / 2))]
        parts.append(B(ax - bw / 2, ax + bw / 2, yB1 - tp, yA0 + tp, az + rc, az + rc + tc) if along == "z" else
                     B(ax + rc, ax + rc + tc, yB1 - tp, yA0 + tp, az - bw / 2, az + bw / 2))
        return parts

    def joint_holes(axis_xz, along):  # through the horn plate: the horn's centre screw + 2 horn screws; plate B: the bolt
        ax, az = axis_xz
        o = hr * 0.6
        dx, dz = (0, o) if along == "z" else (o, 0)
        return [X(3.0, tp + 1, (ax, yA0 - 0.5, az), "subtract"), X(1.1, tp + 1, (ax + dx, yA0 - 0.5, az + dz), "subtract"),
                X(1.1, tp + 1, (ax - dx, yA0 - 0.5, az - dz), "subtract"),
                X(d["bolt"] + 0.3, tp + 1, (ax, yB1 - tp - 0.5, az), "subtract")]

    # ---- base: flange (4 screws to the table), housing, deck with the base servo's pocket
    base = [Zc(Rb + 14, 4, (0, 0, 0)), {"op": "add", "shape": "tube", "radius": Rb, "wall": w, "height": ztb - g, "center": [0, 0, 0]},
            Zc(Rb - w / 2, 4, (0, 0, zf - 4.2))]  # deck: 0.2 mm under the base servo's ears
    base += _place(pocket(d, w, False)[:3], UP, base_at)
    base += [Zc(2.25, 6, (math.cos(a) * (Rb + 7), math.sin(a) * (Rb + 7), -1), "subtract") for a in (math.pi / 4 * k for k in (1, 3, 5, 7))]
    base.append(B(-Rb - 2, -Rb + w + 2, -5, 5, 4, 14, "subtract"))  # cable out
    # ---- turntable: disk on the base servo's horn + the shoulder servo's frame (with the idler boss)
    turn = [Zc(Rb, tt, (0, 0, ztb))] + _place(frame(d, w, m, True), SIDE_DOWN, sh_at)
    turn += [Zc(hr + 0.4, ht + 0.4, (0, 0, ztb - 0.01), "subtract"), Zc(2.0, tt + 1, (0, 0, ztb - 0.5), "subtract")]
    turn += _place(pocket(d, w, True), SIDE_DOWN, sh_at)
    # ---- upper arm: U around the shoulder servo, a column, the elbow servo's frame on top
    upper = u_plates((0, zs), "z") + [B(-W / 2 - p - w, W / 2 + p + w, yc0, yc1, zs + rc + tc - 1, ze - cx - E / 2 - m + 1)]
    upper += _place(frame(d, w, m, True), SIDE_DOWN, el_at)
    upper += joint_holes((0, zs), "z") + _place(pocket(d, w, True), SIDE_DOWN, el_at)
    # ---- forearm: U around the elbow servo, a beam, the claw servo's frame + the fixed finger
    beam_h = bw * 0.8
    fore = u_plates((0, ze), "x") + [B(rc + tc - 1, hx0 + 1, -bw / 2, bw / 2, ze - beam_h / 2, ze + beam_h / 2),
                                     B(hx0 - 12, hx0 + mg - g, hy0, bw / 2, ze - beam_h / 2, ze + beam_h / 2)]  # bridge (stops behind the ears)
    fore += _place(frame(dg, wg, mg, False), SIDE_BACK, gr_at)
    fore += [B(xg - 12, xg + 4, hy0, hy1, zfj - jh, hz0 + 1),                                  # under the claw servo
             B(xg - 12, xg + 4, hy0, yj0 + tj, zfj - jh, zfj),                                 # ... out to the jaw line
             B(xg - 2, xg + Lj, yj0, yj0 + tj, zfj - jh, zfj)]                                 # the fixed finger
    fore += joint_holes((0, ze), "x") + _place(pocket(dg, wg, False), SIDE_BACK, gr_at)
    # ---- the moving jaw (on the claw servo's horn), drawn 20 degrees open
    ang = math.radians(20)
    jaw = [X(dg["hr"] + 1.5, tj, (xg, yj0, ze)),
           {"op": "add", "shape": "box", "size": [Lj, tj, jh], "rotate": [0, -20, 0],
            "center": [xg + Lj / 2 * math.cos(ang), yj0 + tj / 2, ze + Lj / 2 * math.sin(ang)]},
           X(2.4, tj + 1, (xg, yj0 - 0.5, ze), "subtract")]
    jaw += [X(0.8, tj + 1, (xg + dx, yj0 - 0.5, ze + dz), "subtract") for dx, dz in ((dg["hr"] * 0.6, 0), (-dg["hr"] * 0.6, 0))]
    bolts = [{"op": "add", "shape": "rod", "from": [0, yB1 - tp - 1.5, z], "to": [0, yc0 - bl + (bl + w - 1.2), z],
              "radius": d["bolt"], "flat": True} for z in (zs, ze)]
    bodies = [{"name": "base", "parts": base}, {"name": "turntable", "parts": turn}, {"name": "upper arm", "parts": upper},
              {"name": "forearm", "parts": fore}, {"name": "claw jaw", "parts": jaw},
              {"name": "base servo (buy)", "reference": True, "parts": _place(servo(d), UP, base_at)},
              {"name": "shoulder servo (buy)", "reference": True, "parts": _place(servo(d), SIDE_DOWN, sh_at)},
              {"name": "elbow servo (buy)", "reference": True, "parts": _place(servo(d), SIDE_DOWN, el_at)},
              {"name": "claw servo (buy)", "reference": True, "parts": _place(servo(dg), SIDE_BACK, gr_at)},
              {"name": f"M{3 if d['bolt'] < 1.5 else 4} bolts (buy)", "reference": True, "parts": bolts}]
    real = L1 + L2 + Lj
    weak = 2 * tau > cap[cls]
    notes = (f"Reach {real:.0f} mm (upper arm {L1:.0f}, forearm {L2:.0f}, claw {Lj:.0f}), payload {payload:g} g. "
             f"Shoulder needs {tau:.1f} kg·cm held straight out (x2 margin: {2 * tau:.1f}) -> "
             + (f"{sv_sh}; elbow {tau_e:.1f} kg·cm -> {sv_el}; base: {sv_el or sv_sh}; claw: "
                f"{'MG90S' if gcls == 'micro' else 'MG996R'}. " if not weak else
                (f"more than {cls} servos give ({cap[cls]:g} kg·cm): choose servo \"auto\" or a bigger size. " if cls != "large" else
                 f"MORE than hobby servos give ({cap[cls]:g} kg·cm): shorten the arm, lighten the load, or drive the shoulder "
                 "with a NEMA 17 stepper + 10:1 gearbox (these pockets fit the biggest hobby servos). "))
             + f"Buy: 4 servos (horns come with them), 2 x M{3 if d['bolt'] < 1.5 else 4} x 16 bolts (the shoulder and elbow "
             "turn on them, screwed into the frames' bosses), self-tapping screws for the servo ears and horns, 4 x M4 "
             "screws to fix the base to the table. Electronics: Arduino / ESP32 + a PCA9685 servo board and a 5-6 V supply "
             f"({'1 A' if cls == 'micro' else '2 A per servo' if cls == 'standard' else '3-4 A per servo at 6-7.4 V'}). "
             "Print in PETG or PLA, 4 walls, 40 % infill; lay the arm parts on their sides. Shown: upper arm up, forearm "
             "forward, claw open.")
    return {"name": f"robot arm ({real:.0f} mm, {payload:g} g)", "voxel": 0.4, "bodies": bodies, "notes": notes,
            "sizing": {"servo_size": cls, "shoulder_kgcm": round(tau, 2), "elbow_kgcm": round(tau_e, 2),
                       "upper_arm": round(L1, 1), "forearm": round(L2, 1), "claw": Lj}}


TEMPLATES = {"dart_blaster": dart_blaster, "revolver_blaster": revolver_blaster, "centrifugal_pump": centrifugal_pump, "gear_pair": gear_pair, "box_with_lid": box_with_lid,
             "handcuffs": handcuffs, "bolt_and_nut": bolt_and_nut, "threaded_jar": threaded_jar, "drum_magazine": drum_magazine,
             "robot_hand": robot_hand, "exo_elbow": exo_elbow, "drum_blaster": drum_blaster, "demo_engine": demo_engine,
             "fpv_drone": fpv_drone, "dart_magazine": dart_magazine, "mag_pistol": mag_pistol, "cap_grenade": cap_grenade,
             "robot_arm": robot_arm}
