"""Ready-made, parametric FreeCAD designs (exact, tested): the AI picks one and only sets the options the user asked for —
a 4B model placing holes in 3D by itself put them in the air and on top of each other. Each function returns a recipe
(bodies of parts + holes) for run.py; every number has a safe default and limits. Standard sizes are built in
(NEMA motor patterns, Raspberry Pi / Arduino board holes, screw holes from run.py's table)."""
import math

SCREWS = ["M2", "M2.5", "M3", "M4", "M5", "M6", "M8", "M10"]
NEMA = {  # face (mm), hole spacing, centre boss (pilot) diameter, screw
    "nema14": (35.2, 26.0, 22.0, "M3"), "nema17": (42.3, 31.0, 22.0, "M3"), "nema23": (56.4, 47.14, 38.1, "M5")}
BOARDS = {  # board size (x, y) and its mounting holes from the board's lower-left corner, screw
    "raspberry_pi_4": ((85.0, 56.0), [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)], "M2.5"),
    "raspberry_pi_5": ((85.0, 56.0), [(3.5, 3.5), (61.5, 3.5), (3.5, 52.5), (61.5, 52.5)], "M2.5"),
    "arduino_uno": ((68.6, 53.3), [(13.97, 2.54), (15.24, 50.8), (66.04, 7.62), (66.04, 35.56)], "M3"),
}


def n(o: dict, k: str, d: float, lo: float, hi: float) -> float:
    try:
        x = float(o.get(k, d))
    except (TypeError, ValueError):
        x = d
    return min(max(x, lo), hi) if x == x else d


def screw(o: dict, k: str, d: str) -> str:
    v = str(o.get(k) or d).upper().replace(" ", "")
    return v if v in SCREWS else d


def yes(o: dict, k: str, d: bool) -> bool:
    v = o.get(k, d)
    return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "da")


def box(size, center, op="add", round_=0.0):
    p = {"shape": "box", "size": [round(v, 3) for v in size], "center": [round(v, 3) for v in center], "op": op}
    if round_:
        p["round"] = round_
    return p


def cyl(r, h, center, axis="z", op="add"):
    return {"shape": "cylinder", "radius": round(r, 3), "height": round(h, 3), "center": [round(v, 3) for v in center],
            "axis": axis, "op": op}


def hole(at, axis, **kw):
    return {"at": [round(v, 3) for v in at], "axis": axis, **kw}


def gusset(x: float, t: float, size: float, thick: float) -> dict:
    """A triangle in the corner of an L (inner corner at y = t, z = t), `thick` wide along X, centred on x."""
    # polygon outline (u, v) extruded along local Z, turned 90° about Y: world = (x + z_local, v, -u)
    return {"shape": "polygon", "points": [[-t, t], [-t, t + size], [-(t + size), t]], "height": thick,
            "center": [x, 0, 0], "rotate": [0, 90, 0], "op": "add"}


def motor_mount(o: dict) -> dict:
    motor = str(o.get("motor") or "nema17").lower().replace(" ", "").replace("-", "")
    face, pitch, pilot, mscrew = NEMA.get(motor, NEMA["nema17"])
    motor = motor if motor in NEMA else "nema17"
    t = n(o, "thickness", 5, 3, 12)
    flat = str(o.get("style") or "l").lower() == "flat"
    bscrew = screw(o, "base_screw", "M4" if motor != "nema23" else "M5")
    slots = yes(o, "slots", False)
    W = face + 10
    parts, holes = [], []
    if flat:
        L = face + 34
        parts.append(box([L, W, t], [0, 0, t / 2], round_=3))
        zc, top = (0, 0, t), "-z"
        for sx in (-1, 1):
            for sy in (-1, 1):
                p = [sx * pitch / 2, sy * pitch / 2, t]
                if slots:
                    parts.append({"shape": "slot", "length": 3.4 + 6, "width": 3.4 if mscrew == "M3" else 5.5, "height": t + 2,
                                  "center": [p[0], p[1], t / 2], "axis": "z", "direction": "x", "op": "cut"})
                else:
                    holes.append(hole(p, "-z", **{"for": mscrew, "fit": "clearance"}))
        holes.append(hole([0, 0, t], "-z", diameter=pilot + 0.5))
        for sx in (-1, 1):
            for sy in (-1, 1):
                holes.append(hole([sx * (L / 2 - 7), sy * (W / 2 - 7), t], "-z", **{"for": bscrew, "fit": "clearance",
                                                                                    "head": "countersink"}))
        how = (f"{motor.upper()} flat plate {L:g} x {W:g} x {t:g} mm: 4 x {mscrew} for the motor ({pitch:g} mm apart), "
               f"centre hole Ø{pilot + 0.5:g} for the motor's ring, 4 countersunk {bscrew} in the corners.")
    else:  # L: the motor bolts to the back of the upright, its shaft comes out the front; the base screws down
        L = n(o, "base_length", face + 18, face * 0.6, 200)
        zc = t + face / 2 + 1.0  # motor axis height: 1 mm above the base
        Hv = zc + face / 2 + 4
        parts += [box([W, L, t], [0, L / 2, t / 2]), box([W, t, Hv], [0, t / 2, Hv / 2])]
        if yes(o, "gusset", True):  # at the outer sides: 1 mm beside the motor body, never under it
            g = min(L - t - 2, Hv - t - 4) * 0.7
            if g > 4:
                parts += [gusset(-W / 2 + 2, t, g, 4), gusset(W / 2 - 2, t, g, 4)]
        for sx in (-1, 1):
            for sz in (-1, 1):
                p = [sx * pitch / 2, 0, zc + sz * pitch / 2]
                if slots:
                    parts.append({"shape": "slot", "length": 3.4 + 6, "width": 3.4 if mscrew == "M3" else 5.5, "height": t + 2,
                                  "center": [p[0], t / 2, p[2]], "axis": "y", "direction": "z", "op": "cut"})
                else:
                    holes.append(hole(p, "+y", **{"for": mscrew, "fit": "clearance"}))
        holes.append(hole([0, 0, zc], "+y", diameter=pilot + 0.5))
        nb = 2 if int(n(o, "base_holes", 4, 2, 4)) < 4 or L <= 45 else 4  # 2 = at the back only, 4 = back + front
        for sx in (-1, 1):
            for y in ((t + 10, L - 8) if nb == 4 else (L - 8,)):
                holes.append(hole([sx * (W / 2 - 7), y, t], "-z", **{"for": bscrew, "fit": "clearance", "head": "countersink"}))
        how = (f"{motor.upper()} L-mount: the motor bolts to the back of the {t:g} mm upright (4 x {mscrew}, {pitch:g} mm "
               f"apart{', slotted to tension a belt' if slots else ''}), its ring sits in the Ø{pilot + 0.5:g} centre hole "
               f"and the shaft comes out the front; motor axis {zc:.1f} mm above the table. Base: countersunk {bscrew} "
               "screws. Print it standing on the base (no supports).")
    return {"name": f"{motor.upper()} motor mount", "bodies": [{"name": "motor mount", "parts": parts, "holes": holes,
                                                                "chamfer": 0.4}],
            "notes": how + f" Motor screws: {mscrew} x {int(t + 4)} mm."}


def l_bracket(o: dict) -> dict:
    W, A, B = n(o, "width", 40, 12, 300), n(o, "leg_a", 40, 15, 300), n(o, "leg_b", 40, 15, 300)
    t = n(o, "thickness", 5, 2, 20)
    s = screw(o, "screw", "M4")
    k = int(n(o, "holes", 2, 1, 4))
    cs = yes(o, "countersink", True)
    parts = [box([W, A, t], [0, A / 2, t / 2]), box([W, t, B], [0, t / 2, B / 2])]
    if yes(o, "gusset", True) and W >= 25:
        g = min(A, B) * 0.45
        parts += [gusset(-W / 2 + t / 2, t, g, t), gusset(W / 2 - t / 2, t, g, t)]
    xs = [-W / 2 + W * (i + 0.5) / k for i in range(k)]
    head = {"head": "countersink"} if cs else {}
    holes = [hole([x, t + (A - t) / 2, t], "-z", **{"for": s, "fit": "clearance"}, **head) for x in xs] + \
            [hole([x, 0, t + (B - t) / 2], "+y", **{"for": s, "fit": "clearance"}, **head) for x in xs]
    return {"name": "L bracket", "bodies": [{"name": "L bracket", "parts": parts, "holes": holes, "fillet": min(1.5, t / 3),
                                             "fillet_edges": "vertical", "chamfer": 0.4}],
            "notes": f"L bracket {W:g} wide, legs {A:g} and {B:g} mm, {t:g} mm thick; {k} {s} hole(s) per leg"
                     f"{' (countersunk)' if cs else ''}{', with 2 gussets' if len(parts) > 2 else ''}. Print it on its side "
                     "(the L flat on the bed) so the layers run around the corner — that's where it carries load."}


def enclosure(o: dict) -> dict:
    board = str(o.get("board") or "none").lower().replace(" ", "_").replace("-", "_")
    bsize, bholes, bscrew = BOARDS.get(board, (None, None, None))
    w, d, h = (o.get("inner") if isinstance(o.get("inner"), list) and len(o.get("inner")) == 3 else [80, 60, 30])
    w, d, h = (n({"v": w}, "v", 80, 20, 400), n({"v": d}, "v", 60, 20, 400), n({"v": h}, "v", 30, 8, 300))
    wall, floor, lid_t = n(o, "wall", 2.4, 1.6, 6), n(o, "floor", 2.0, 1.2, 6), n(o, "lid", 2.4, 1.6, 6)
    s = screw(o, "screw", "M3")
    fit = "tap" if str(o.get("fit") or "insert").lower() == "tap" else "insert"
    boss = max(2.5 * float(s[1:]), (4.1 if s == "M3" else 3.2 * float(s[1:]) / 2) + 3.4) + 1
    if bsize:  # the board centred, the corner bosses beside it (not under its corners), its parts on top
        w, d, h = max(w, bsize[0] + 2 * (boss + 2)), max(d, bsize[1] + 8), max(h, 28)
    R = n(o, "corner", 3, 0.5, 20)
    W, D, H = w + 2 * wall, d + 2 * wall, h + floor
    parts = [box([W, D, H], [0, 0, H / 2], round_=R),
             box([w, d, h + 1], [0, 0, floor + (h + 1) / 2], op="cut", round_=max(0.5, R - wall))]
    bx, by = w / 2 - boss / 2, d / 2 - boss / 2
    corners = [(sx * bx, sy * by) for sx in (-1, 1) for sy in (-1, 1)]
    parts += [cyl(boss / 2, h, [x, y, floor + h / 2]) for x, y in corners]
    holes = [hole([x, y, floor + h], "-z", **{"for": s, "fit": fit}) for x, y in corners]
    extra = []
    if bsize:
        so = n(o, "standoff", 5, 2, 20)
        ox, oy = -bsize[0] / 2, -bsize[1] / 2  # the board's lower-left corner (board centred)
        for hx, hy in bholes:
            x, y = ox + hx, oy + hy
            parts.append(cyl(3.2 if bscrew == "M2.5" else 3.5, so, [x, y, floor + so / 2]))
            holes.append(hole([x, y, floor + so], "-z", **{"for": bscrew, "fit": "tap"}, depth=so + floor - 0.8))
        extra.append(f"{board.replace('_', ' ')} on {so:g} mm standoffs ({bscrew}, self-tapping)")
    cable = n(o, "cable_hole", 0, 0, 40)
    if cable:
        holes.append(hole([0, D / 2, floor + h / 2], "-y", diameter=cable, depth=wall + 1))
        extra.append(f"a Ø{cable:g} cable hole in the back")
    lid_parts = [box([W, D, lid_t], [0, 0, H + lid_t / 2], round_=R)]
    if yes(o, "vents", False):
        for i in range(-2, 3):
            lid_parts.append({"shape": "slot", "length": w * 0.45, "width": 2.4, "height": lid_t + 2,
                              "center": [0, i * 6, H + lid_t / 2], "axis": "z", "direction": "x", "op": "cut"})
        extra.append("5 vent slots in the lid")
    lid_holes = [hole([x, y, H + lid_t], "-z", **{"for": s, "fit": "clearance", "head": "counterbore"}) for x, y in corners]
    return {"name": "enclosure", "bodies": [
        {"name": "box", "parts": parts, "holes": holes, "chamfer": 0.4},
        {"name": "lid", "parts": lid_parts, "holes": lid_holes, "chamfer": 0.4, "chamfer_edges": "top"}],
        "notes": f"Enclosure: inside {w:g} x {d:g} x {h:g} mm, walls {wall:g} mm, floor {floor:g}, lid {lid_t:g}; 4 corner "
                 f"bosses with {s} {'heat-set inserts' if fit == 'insert' else 'self-tapping holes'}, the lid has counterbored "
                 f"{s} holes" + (f"; {', '.join(extra)}" if extra else "") + f". Screws: {s} x {int(lid_t + 6)} mm. "
                 "Print the box upright and the lid top-down."}


def mounting_plate(o: dict) -> dict:
    size = o.get("size") if isinstance(o.get("size"), list) and len(o.get("size")) >= 2 else [100, 60]
    w, d = n({"v": size[0]}, "v", 100, 15, 500), n({"v": size[1]}, "v", 60, 15, 500)
    t = n(o, "thickness", 5, 1.5, 30)
    s = screw(o, "screw", "M4")
    g = o.get("grid") if isinstance(o.get("grid"), list) and len(o.get("grid")) >= 2 else [2, 2]
    nx, ny = int(n({"v": g[0]}, "v", 2, 1, 12)), int(n({"v": g[1]}, "v", 2, 1, 12))
    m = n(o, "margin", 8, 3, min(w, d) / 2 - 2)
    stx = (w - 2 * m) / (nx - 1) if nx > 1 else 0
    sty = (d - 2 * m) / (ny - 1) if ny > 1 else 0
    x0, y0 = (-w / 2 + m) if nx > 1 else 0, (-d / 2 + m) if ny > 1 else 0
    head = {"head": "countersink"} if yes(o, "countersink", False) else {}
    holes = [hole([x0, y0, t], "-z", **{"for": s, "fit": "clearance"}, **head, pattern={"grid": [nx, ny], "step": [stx, sty]})]
    c = n(o, "center_hole", 0, 0, min(w, d) - 2 * m - 6)
    if c:
        holes.append(hole([0, 0, t], "-z", diameter=c))
    return {"name": "mounting plate", "bodies": [{"name": "plate", "parts": [box([w, d, t], [0, 0, t / 2],
                                                                                   round_=n(o, "corner", 4, 0, min(w, d) / 3))],
                                                  "holes": holes, "chamfer": 0.4}],
            "notes": f"Plate {w:g} x {d:g} x {t:g} mm with {nx * ny} {s} holes ({stx:g} x {sty:g} mm apart, {m:g} mm from the "
                     f"edges){' countersunk' if head else ''}" + (f" and a Ø{c:g} centre hole" if c else "") + "."}


def flange(o: dict) -> dict:
    D, t = n(o, "outer_diameter", 60, 15, 400), n(o, "thickness", 6, 2, 40)
    bore = n(o, "bore", 12, 2, D - 10)
    s = screw(o, "screw", "M4")
    bc = n(o, "bolt_circle", (D + bore) / 2, bore + 2.5 * float(s[1:]), D - 2.5 * float(s[1:]))
    k = int(n(o, "bolts", 4, 2, 16))
    hub_d, hub_h = n(o, "hub_diameter", 0, 0, D), n(o, "hub_height", 10, 2, 80)
    parts = [cyl(D / 2, t, [0, 0, t / 2])]
    top = t
    if hub_d > bore + 4:
        parts.append(cyl(hub_d / 2, hub_h, [0, 0, t + hub_h / 2]))
        top = t + hub_h
    holes = [hole([0, 0, top], "-z", diameter=bore + 0.2),
             hole([0, 0, t], "-z", **{"for": s, "fit": "clearance"}, pattern={"circle": k, "radius": bc / 2})]
    if hub_d > bore + 4 and yes(o, "set_screw", True):
        holes.append(hole([0, hub_d / 2, t + hub_h / 2], "-y", **{"for": "M3", "fit": "tap"}, depth=(hub_d - bore) / 2 + 0.5))
    return {"name": "flange", "bodies": [{"name": "flange", "parts": parts, "holes": holes, "chamfer": 0.4}],
            "notes": f"Flange Ø{D:g} x {t:g} mm, bore Ø{bore + 0.2:g} (shaft {bore:g} + 0.2 play), {k} x {s} on a Ø{bc:g} "
                     "circle" + (f", hub Ø{hub_d:g} x {hub_h:g} with an M3 set screw" if top > t else "") + "."}


def spacer(o: dict) -> dict:
    s = screw(o, "screw", "M3")
    L = n(o, "length", 10, 1, 200)
    od = n(o, "outer_diameter", 2.5 * float(s[1:]) + 1, float(s[1:]) + 2, 60)
    fit = str(o.get("fit") or "clearance").lower()
    fit = fit if fit in ("clearance", "tap", "insert") else "clearance"
    if yes(o, "hex", False):
        r = od / math.sqrt(3)  # across flats = od
        part = {"shape": "polygon", "points": [[r * math.cos(math.radians(60 * i)), r * math.sin(math.radians(60 * i))]
                                               for i in range(6)], "height": L, "center": [0, 0, L / 2]}
    else:
        part = cyl(od / 2, L, [0, 0, L / 2])
    holes = [hole([0, 0, L], "-z", **{"for": s, "fit": fit})]
    if fit != "clearance":  # threaded / insert spacers: from both ends
        holes.append(hole([0, 0, 0], "+z", **{"for": s, "fit": fit}))
    return {"name": "spacer", "bodies": [{"name": "spacer", "parts": [part], "holes": holes}],
            "notes": f"Spacer {'hex ' if part['shape'] == 'polygon' else 'Ø'}{od:g} x {L:g} mm for {s} ({fit}). "
                     "Print it standing up."}


def pipe_clamp(o: dict) -> dict:
    p = n(o, "pipe_diameter", 25, 4, 200)
    wid, wall = n(o, "width", 15, 6, 100), n(o, "wall", 4, 2, 15)
    s = screw(o, "screw", "M4")
    gap = 1.0
    R = p / 2 + 0.2 + wall
    ear = 2.5 * float(s[1:]) + 4
    ex = R + ear / 2 - 1
    eh = 2 * wall + 2
    big = 4 * (R + ear) + 50
    bodies = []
    for name, sz in (("clamp top", 1), ("clamp bottom", -1)):
        parts = [{"shape": "tube", "radius": R, "wall": wall, "height": wid, "center": [0, 0, 0], "axis": "y", "op": "add"},
                 box([2 * ex + ear, wid, eh], [0, 0, 0]),
                 cyl(p / 2 + 0.2, wid + 2, [0, 0, 0], axis="y", op="cut"),
                 box([big, big, big], [0, 0, sz * (big / 2 + gap / 2)], op="intersect")]
        top = eh / 2 if sz > 0 else -gap / 2
        holes = [hole([x, 0, top], "-z", **{"for": s, "fit": "clearance"}) for x in (-ex, ex)]
        if sz < 0:
            holes += [hole([x, 0, -eh / 2], "+z", **{"for": s, "fit": "nut"}) for x in (-ex, ex)]
        bodies.append({"name": name, "parts": parts, "holes": holes, "chamfer": 0.3, "chamfer_edges": "both"})
    return {"name": "pipe clamp", "bodies": bodies,
            "notes": f"Pipe clamp for a Ø{p:g} mm pipe (0.2 mm play), {wid:g} wide, {wall:g} mm walls, two halves with a "
                     f"{gap:g} mm gap so the screws can squeeze it tight; 2 x {s} through the ears, nuts in the bottom "
                     f"half's hexagon pockets. Screws: {s} x {int(eh + 4)} mm."}


def fit_test(o: dict) -> dict:
    """The "micro-gauge": pegs + holes 0.0 / 0.1 / 0.2 / 0.3 / 0.4 mm bigger, so one 15-minute print tells how much room
    THIS printer needs for parts that slide / fit together (instead of printing a whole part to find out). Position k
    has k notches on both strips' front edge; the user says which hole the peg slides into without forcing."""
    d = n(o, "diameter", 10, 4, 25)
    steps = [0.0, 0.1, 0.2, 0.3, 0.4]
    pitch, t, h = d + 8, 4.0, n(o, "peg_height", 8, 4, 20)
    width, depth = pitch * len(steps) + 4, d + 10
    x0 = -pitch * (len(steps) - 1) / 2
    pegs = [box([width, depth, t], [0, 0, t / 2], round_=2)]
    holes_ = [box([width, depth, 6], [0, depth + 8, 3], round_=2)]
    for k, c in enumerate(steps):
        x = x0 + k * pitch
        pegs.append(cyl(d / 2, h, [x, 0, t + h / 2]))  # straight pegs: they measure best
        holes_.append(cyl((d + c) / 2, 8, [x, depth + 8, 3], op="cut"))
        for j in range(k + 1):  # k + 1 notches on the front edge of both strips: which pair belongs together
            nx = x - (k * 1.2) / 2 + j * 1.2
            pegs.append(box([0.6, 1.2, t + 1], [nx, -depth / 2, t / 2], op="cut"))
            holes_.append(box([0.6, 1.2, 7], [nx, 8 + depth / 2, 3], op="cut"))
    return {"name": f"fit test {d:g} mm", "bodies": [{"name": "pegs", "parts": pegs}, {"name": "holes", "parts": holes_}],
            "notes": f"Pegs Ø{d:g} mm; holes {', '.join(f'+{c:g}' for c in steps)} mm (1 to 5 notches on the edge). Print both "
                     "flat, 0.2 mm layers, like your real parts. Push each peg into the hole with the same notches: the "
                     "first one that slides in by hand without wobbling is your printer's fit — tell me “fit 0.2” "
                     "(or whichever) and I'll use it for every part that must fit together."}


TEMPLATES = {"motor_mount": motor_mount, "l_bracket": l_bracket, "enclosure": enclosure, "mounting_plate": mounting_plate,
             "flange": flange, "spacer": spacer, "pipe_clamp": pipe_clamp, "fit_test": fit_test}
