"""Mechanical engineering calculators (the app's "ME consultant"): fasteners, shafts, gears, belts, lead screws,
wheels, arm / servo torque, beams, columns, springs, bearings, fits, heat expansion, weight, motors, drops, 3D-printer
calibration and unit conversion. Textbook formulas (Shigley, Roloff/Matek, ISO tables); results are design estimates
and the notes say where real parts differ."""
import math
import re

from units import G, Inputs, MATERIALS, Out, UNITS, TEMP_UNITS, claim, fmt, material, norm_unit, parse, pick_up, show

# ------------------------------------------------------------------ screws and bolts (ISO 261 / 898-1 / 273)
COARSE = {1.6: 0.35, 2: 0.4, 2.5: 0.45, 3: 0.5, 3.5: 0.6, 4: 0.7, 5: 0.8, 6: 1.0, 7: 1.0, 8: 1.25, 10: 1.5, 12: 1.75,
          14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0, 27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0}
GRADES = {"4.6": (225, 240, 400), "4.8": (310, 340, 420), "5.6": (280, 300, 500), "5.8": (380, 420, 520),
          "6.8": (440, 480, 600), "8.8": (580, 640, 800), "9.8": (650, 720, 900), "10.9": (830, 940, 1040),
          "12.9": (970, 1100, 1220), "a2-50": (210, 210, 500), "a2-70": (450, 450, 700), "a4-70": (450, 450, 700),
          "a4-80": (600, 600, 800)}  # proof, yield (Rp0.2), tensile — MPa; stainless "proof" = Rp0.2
CLEAR_ISO = {1.6: 1.8, 2: 2.4, 2.5: 2.9, 3: 3.4, 4: 4.5, 5: 5.5, 6: 6.6, 8: 9.0, 10: 11.0, 12: 13.5, 14: 15.5,
             16: 17.5, 18: 20, 20: 22, 22: 24, 24: 26, 27: 30, 30: 33}  # ISO 273 medium
# the app's printing table (same numbers as the FreeCAD / PicoGK engines use)
PRINT_CLEAR = {"M2": 2.4, "M2.5": 2.9, "M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6, "M8": 8.6, "M10": 10.6}
PRINT_TAP = {"M2": 1.7, "M2.5": 2.2, "M3": 2.6, "M4": 3.5, "M5": 4.3, "M6": 5.1, "M8": 6.9, "M10": 8.7}
PRINT_INSERT = {"M2": 3.2, "M2.5": 3.6, "M3": 4.1, "M4": 5.6, "M5": 6.4, "M6": 8.0, "M8": 10.0, "M10": 12.0}
INSERT_T = {"M2": 0.2, "M2.5": 0.3, "M3": 0.5, "M4": 1.0, "M5": 1.5, "M6": 2.5, "M8": 4.0}  # rough, by feel
SELF_TAP_T = {"M2": 0.1, "M2.5": 0.15, "M3": 0.25, "M4": 0.5, "M5": 0.8, "M6": 1.2, "M8": 2.0}
THREAD_RE = re.compile(r"\bm\s?(\d+(?:[.,]\d+)?)(?:\s?[x×]\s?(\d+(?:[.,]\d+)?))?(?![\d/³²])", re.I)


def thread(inp: Inputs):
    """(d mm, pitch mm) from "M6", "M8x1", 6, "an m5 screw"."""
    r = inp._raw(["size", "thread", "bolt", "screw", "bolt_size", "screw_size", "metric", "diameter", "d", "m"])
    for s in [inp.question] + ([str(r[0])] if r else []):  # the user's own words first (the model mixes in old messages)
        m = THREAD_RE.search(s)
        if m:
            d = float(m.group(1).replace(",", "."))
            return d, (float(m.group(2).replace(",", ".")) if m.group(2) else COARSE.get(d))
        if r and s == str(r[0]) and s != inp.question:
            v = parse(s, "length", "mm")
            if v:
                d = round(v * 1000, 2)
                return d, COARSE.get(d)
    return None, None


def grade(inp: Inputs):
    for src in (inp.question.lower(), inp.text(["grade", "class", "property_class", "strength_class", "bolt_grade", "strength"], "")):
        m = re.search(r"(?<![\d.])(4\.6|4\.8|5\.6|5\.8|6\.8|8\.8|9\.8|10\.9|12\.9)(?![\d])", src)
        if m:
            return m.group(1)
        m = re.search(r"\b(a[24])[\s-]?(50|70|80)\b", src)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        if re.search(r"stainless|inox|\ba2\b|\ba4\b", src):
            return "a2-70"
    return None


def nut_factor(inp: Inputs, stainless: bool):
    s = inp.text(["lube", "lubrication", "condition", "finish", "coating"], "") + " " + inp.question.lower()
    if re.search(r"moly|mos2|wax|ptfe|teflon", s):
        return 0.11, "waxed / moly / PTFE"
    if re.search(r"\boil|grease|lubric|anti.?seize|copper paste|unsoare|ulei|\bunsa", s):
        return 0.15, "oiled / greased"
    if re.search(r"loctite|threadlock|thread lock|thread-lock", s):
        return 0.17, "with thread locker"
    if re.search(r"zinc|galvani|plated|zincat", s):
        return 0.18, "zinc plated, dry"
    if stainless:
        return 0.30, "stainless, dry (it galls easily — a little grease is better)"
    return 0.20, "plain steel, dry"


def into_kind(inp: Inputs) -> str:
    s = inp.text(["into", "base", "thread_material", "tapped_into", "part_material", "material"], "") + " " + inp.question.lower()
    if re.search(r"insert|heat.?set", s):
        return "insert"
    if re.search(r"print|\bpla\b|petg|\babs\b|plastic|\basa\b|nylon|\b3d\b|plastic", s):
        return "plastic"
    if re.search(r"alumin|\balu\b", s):
        return "aluminium"
    if re.search(r"cast iron|fonta", s):
        return "cast iron"
    if re.search(r"wood|mdf|plywood|lemn", s):
        return "wood"
    return "steel"


def stress_area(d: float, p: float) -> float:
    return math.pi / 4 * (d - 0.9382 * p) ** 2


def bolt(inp: Inputs) -> dict:
    o = Out()
    d, p = thread(inp)
    if not d:
        inp.missing.append("bolt size (M3, M5, M8 …)")
        return o.done()
    if p is None:
        inp.missing.append(f"the thread pitch (M{fmt(d)} isn't a standard coarse size — say e.g. M{fmt(d)}x1)")
        return o.done()
    g = grade(inp)
    if not g:
        g = "8.8"
        inp.assumed.append("grade 8.8 (the usual black or zinc steel bolt)")
    proof, yld, uts = (600, 660, 830) if g == "8.8" and d > 16 else GRADES[g]
    stainless = g.startswith("a")
    a_s = stress_area(d, p)
    k, kname = nut_factor(inp, stainless)
    fp = (0.7 * yld if stainless else 0.75 * proof) * a_s
    t = k * fp * d / 1000
    into = into_kind(inp)
    key = f"M{fmt(d)}"
    o.add("Thread", f"{key} × {fmt(p)} (stress area {fmt(a_s)} mm²)")
    o.add("Grade", f"{g.upper()}: proof {proof} MPa, yield {yld} MPa, tensile {uts} MPa")
    o.add("Clamp force (preload)", show(fp, "force") + (" — 70 % of yield" if stainless else " — 75 % of the proof load"))
    if into in ("plastic", "insert"):
        guide = (INSERT_T if into == "insert" else SELF_TAP_T).get(key)
        o.add("Tightening torque", (f"≈ {fmt(guide)} N·m in printed plastic ({'heat-set insert' if into == 'insert' else 'screwed into the plastic'}) "
                                    "— snug, then stop") if guide else "by feel: snug, then stop")
        o.add("Steel-to-steel torque (reference only)", f"{fmt(t)} N·m — far too much for plastic")
        o.note("In plastic the plastic is the limit, not the bolt: tighten by feel, use a washer, and if an insert turns it's ruined.")
    else:
        f = 0.8 if into == "aluminium" else 1.0
        o.add("Tightening torque", f"{fmt(t * f)} N·m (≈ {fmt(t * f / G * 100)} kg·cm, {fmt(t * f / 1.35582)} lbf·ft) — {kname}")
        o.note({"aluminium": f"Into aluminium: at least 2 × d = {fmt(2 * d)} mm of thread (or a Helicoil); torque lowered to 80 %.",
                "cast iron": f"Into cast iron: at least 1.5 × d = {fmt(1.5 * d)} mm of thread.",
                "wood": "In wood use threaded inserts or a nut with a big washer — these are machine-screw numbers."}
               .get(into, f"Into steel: at least 1 × d = {fmt(d)} mm of thread (a standard nut is enough)."))
    holes = []
    if d in CLEAR_ISO:
        holes.append(f"clearance {fmt(CLEAR_ISO[d])} mm (drilled)")
    holes.append(f"tap drill {fmt(d - p)} mm")
    if key in PRINT_CLEAR:
        holes.append(f"printed: through {PRINT_CLEAR[key]}, self-tap {PRINT_TAP[key]}, heat-set insert {PRINT_INSERT[key]} mm")
    o.add("Holes", "; ".join(holes))
    load = inp.num(["load", "force", "working_load", "tension", "pull", "shear_load", "weight"], "force", "load",
                   hints=["load", "force", "hold", "pull", "carry", "weigh", "support", "kg"])
    if load:
        n = inp.num(["count", "bolts", "number", "quantity", "n", "screws", "number_of_bolts"], "count", "number of bolts",
                    hints=["bolts", "screws", "bolt", "screw"], lone=False)
        mc = re.search(r"(?<![A-Za-z\d.])(\d+)\s*(?:x|×|pcs|pieces)?\s*(?:m\d|bolts?|screws?|suruburi)", inp.question, re.I)
        if n is None and mc:
            n = int(mc.group(1))
            claim(inp.qs, mc.start(1))
        if n is None:
            n = 1
            inp.assumed.append("one bolt")
        n = max(1, int(n))
        planes = max(1, int(inp.num(["planes", "shear_planes"], "count", "shear planes", default=1, text_ok=False) or 1))
        sf = inp.num(["sf", "safety", "safety_factor", "factor_of_safety"], "number", "safety factor", default=2.0, hints=["safety"])
        shear = bool(re.search(r"shear|sideways|side load|slid|lateral|forfec|across",
                               inp.text(["load_type", "direction", "type"], "") + " " + inp.question.lower()))
        per = load / n
        o.add("Load per bolt", show(per, "force"))
        if shear:
            cap = 0.6 * uts * a_s * planes / sf
            o.add("Shear capacity per bolt", f"{show(cap, 'force')} (thread in the shear plane, safety factor {fmt(sf)})")
            o.add("Friction grip per bolt", f"{show(0.2 * fp * planes / sf, 'force')} (clamp force × 0.2): a tight joint holds by friction first")
        else:
            cap = (yld if stainless else proof) * a_s / sf
            o.add("Tension capacity per bolt", f"{show(cap, 'force')} (safety factor {fmt(sf)})")
            if per > fp:
                o.warn("The load is bigger than the clamp force: the joint opens and the bolt works loose — use a bigger or an extra bolt.")
        ok = per <= cap
        o.verdict = (f"{'OK' if ok else 'NOT OK'}: {n} × {key} {g.upper()} {'holds' if ok else 'does not hold'} "
                     f"{show(load, 'force')} {'in shear' if shear else 'in tension'} (safety factor {fmt(sf)}).")
        if not ok:
            for dd in sorted(COARSE):
                if dd <= d:
                    continue
                pr, yl, ut = (600, 660, 830) if g == "8.8" and dd > 16 else GRADES[g]
                aa = stress_area(dd, COARSE[dd])
                if per <= (0.6 * ut * aa * planes if shear else (yl if stainless else pr) * aa) / sf:
                    o.verdict += f" Use M{fmt(dd)} or bigger (or more bolts)."
                    break
    return o.done()


# ------------------------------------------------------------------ power, torque, speed
def power(inp: Inputs) -> dict:
    o = Out()
    p = inp.num(["power", "p", "motor_power"], "power", "power", hints=["power", "motor", "w ", "kw", "hp"])
    t = inp.num(["torque", "t", "moment"], "torque", "torque", hints=["torque", "nm", "kg cm"])
    n = inp.num(["rpm", "speed", "n", "rotational_speed", "revolutions"], "rpm", "rpm", hints=["rpm", "speed", "turn"])
    f = inp.num(["force", "pull", "push", "thrust"], "force", "force", hints=["force", "pull", "push", "lift", "thrust"])
    v = inp.num(["velocity", "linear_speed", "speed_ms", "line_speed"], "speed", "speed", hints=["speed", "velocity", "m/s"])
    if p and n and not t:
        t = p / (2 * math.pi * n / 60)
    elif t and n and not p:
        p = t * 2 * math.pi * n / 60
    elif p and t and not n:
        n = p / t * 60 / (2 * math.pi)
    elif f and v and not p:
        p = f * v
    elif p and v and not f:
        f = p / v
    elif p and f and not v:
        v = p / f
    elif not (p and (t or f)):
        inp.missing.append("two of: power, torque, rpm (or force and speed)")
        return o.done()
    if p:
        o.add("Power", f"{show(p, 'power')} ({fmt(p / 745.7)} hp)")
    if t:
        o.add("Torque", show(t, "torque"))
    if n:
        o.add("Speed", f"{fmt(n)} rpm ({fmt(n * 2 * math.pi / 60)} rad/s)")
    if f:
        o.add("Force", show(f, "force"))
    if v:
        o.add("Linear speed", show(v, "speed"))
    o.note("P = T × ω (ω = 2π·rpm/60); P = F × v. A gearbox multiplies torque by its ratio and divides the speed (losses ~3–10 % per stage).")
    return o.done()


# ------------------------------------------------------------------ shafts
STD_SHAFT = [3, 4, 5, 6, 8, 10, 12, 14, 15, 16, 17, 18, 20, 22, 24, 25, 28, 30, 32, 35, 40, 45, 50, 55, 60, 65, 70, 75,
             80, 90, 100, 110, 120, 140, 160]


def mat(inp: Inputs, default: str = "steel", names=("material", "mat", "made_of", "of")):
    s = inp.text(list(names), "")
    if not s:
        low = inp.question.lower()
        for k, row in MATERIALS.items():
            if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", low) for w in (k + " " + row[6]).split() if len(w) > 2):
                s = k
                break
    if not s:
        inp.assumed.append(f"material = {MATERIALS[default][7]}")
        return default, MATERIALS[default]
    return material(s, default)


def shaft(inp: Inputs) -> dict:
    o = Out()
    t = inp.num(["torque", "t"], "torque", "torque on the shaft", need=True, hints=["torque", "nm"])
    m = inp.num(["bending", "bending_moment", "moment", "m"], "torque", "bending moment", default=0.0, text_ok=False, show="0 (torsion only)")
    if t is None:
        return o.done()
    key, row = mat(inp, "steel c45")
    sy = row[2] * 1e6
    sf = inp.num(["sf", "safety", "safety_factor"], "number", "safety factor", default=2.0, hints=["safety"])
    k = math.sqrt(4 * m * m + 3 * t * t)
    dmin = (16 * sf * k / (math.pi * sy)) ** (1 / 3)
    std = pick_up(dmin * 1000, STD_SHAFT)
    o.add("Material", f"{row[7]} (yield {row[2]} MPa)")
    o.add("Smallest solid shaft", f"{fmt(dmin * 1000)} mm → use Ø{std} mm" if std else f"{fmt(dmin * 1000)} mm")
    d = inp.num(["diameter", "d", "outer_diameter", "shaft_diameter", "od"], "length", "shaft diameter",
                hints=["diameter", "dia", "ø", "od", "thick"], lone=False)
    di = inp.num(["inner", "inner_diameter", "id", "bore"], "length", "inner diameter", default=0.0, text_ok=False, show="solid")
    if d:
        wq = (d ** 4 - di ** 4) / d
        s_eq = 16 * k / (math.pi * wq)
        o.add("Stress in Ø" + fmt(d * 1000), f"{show(s_eq, 'stress')} (von Mises, torsion{' + bending' if m else ''}) → safety factor {fmt(sy / s_eq)}")
        o.verdict = f"{'OK' if sy / s_eq >= sf else 'TOO THIN'}: Ø{fmt(d * 1000)} mm has a safety factor of {fmt(sy / s_eq)} (wanted {fmt(sf)})."
    length = inp.num(["length", "l", "shaft_length"], "length", "length", hints=["long", "length"])
    if length:
        dd = d or (std or dmin * 1000) / 1000
        gmod = row[1] * 1e9 / (2 * (1 + row[5]))
        j = math.pi * (dd ** 4 - di ** 4) / 32
        th = math.degrees(t * length / (gmod * j))
        o.add("Twist", f"{fmt(th)}° over {fmt(length * 1000)} mm ({fmt(th / length)}°/m; precise drives want < 0.25°/m)")
    return o.done()


# ------------------------------------------------------------------ gears (spur, 20°)
LEWIS = [(12, .245), (13, .261), (14, .277), (15, .290), (16, .296), (17, .303), (18, .309), (19, .314), (20, .322),
         (21, .328), (22, .331), (24, .337), (26, .346), (28, .353), (30, .359), (34, .371), (38, .384), (43, .397),
         (50, .409), (60, .422), (75, .435), (100, .447), (150, .460), (300, .472), (100000, .485)]
STD_MODULE = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10, 12]
GEAR_ALLOW = {"steel": 150, "steel s355": 180, "steel c45": 200, "steel 42crmo4": 300, "stainless": 120, "cast iron": 60,
              "brass": 70, "bronze": 80, "aluminium": 70, "aluminium 7075": 120, "pom": 30, "nylon": 25, "pla": 15,
              "petg": 12, "abs": 10, "asa": 10, "pc": 15, "pla cf": 15, "tpu": 2}  # MPa, long-life bending (rough)


def lewis_y(z: float) -> float:
    if z <= LEWIS[0][0]:
        return LEWIS[0][1]
    for (z0, y0), (z1, y1) in zip(LEWIS, LEWIS[1:]):
        if z <= z1:
            return y0 + (y1 - y0) * (z - z0) / (z1 - z0)
    return LEWIS[-1][1]


def teeth_in_text(q: str) -> list[int]:
    """"20 and 40 teeth", "20T / 60T", "z1=17 z2=51" -> [20, 40]."""
    out = [int(x) for x in re.findall(r"\bz\s?\d\s*[=:]\s*(\d+)", q, re.I)]
    if out:
        return out
    m = re.search(r"(\d+)\s*(?:t|teeth|tooth|dinti)?\s*(?:and|&|,|/|to|x|și|si)\s*(\d+)\s*(?:t\b|teeth|tooth|dinti)", q, re.I)
    if m:
        return [int(m.group(1)), int(m.group(2))]
    return [int(x) for x in re.findall(r"(\d+)\s*(?:t\b|teeth|tooth|dinti)", q, re.I)]


def gears(inp: Inputs) -> dict:
    o = Out()
    tt = teeth_in_text(inp.question)
    z1 = inp.num(["teeth1", "z1", "pinion", "driver", "teeth_in", "input_teeth", "small_gear", "gear1"], "count", "teeth", text_ok=False)
    z2 = inp.num(["teeth2", "z2", "driven", "teeth_out", "output_teeth", "big_gear", "gear2", "wheel"], "count", "teeth", text_ok=False)
    if inp.has("teeth") and not (z1 and z2):
        tl = inp.nums(["teeth"], "count")
        z1, z2 = (tl + [None, None])[:2] if len(tl) >= 2 else (z1 or (tl[0] if tl else None), z2)
    z1 = z1 or (tt[0] if tt else None)
    z2 = z2 or (tt[1] if len(tt) > 1 else None)
    if not z1 or not z2:
        inp.missing.append("the number of teeth on both gears")
        return o.done()
    z1, z2 = int(round(z1)), int(round(z2))
    m = inp.num(["module", "mod", "m"], "length", "module", hints=["module", "modul"], text_ok=False)
    mm_ = re.search(r"\bmod(?:ule|ul)?\s*[=:]?\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*mod(?:ule|ul)\b", inp.question, re.I)
    if m is None and mm_:
        m = float((mm_.group(1) or mm_.group(2)).replace(",", ".")) / 1000
        claim(inp.qs, mm_.start(1) if mm_.group(1) else mm_.start(2))
    a = inp.num(["center_distance", "centre_distance", "distance", "centers"], "length", "center distance", hints=["center", "centre", "distance"])
    d1 = inp.num(["pitch_diameter", "d1", "pitch_diameter1"], "length", "pitch diameter", text_ok=False)
    m = m * 1000 if m else (2 * a * 1000 / (z1 + z2) if a else (d1 * 1000 / z1 if d1 else None))
    ratio = z2 / z1
    o.add("Ratio", f"{fmt(ratio)} : 1 ({z1} → {z2} teeth{', speed down, torque up' if ratio > 1 else ', speed up, torque down'})")
    if m:
        o.add("Module", f"{fmt(m)} mm")
        o.add("Pitch diameters", f"{fmt(m * z1)} / {fmt(m * z2)} mm (outside {fmt(m * (z1 + 2))} / {fmt(m * (z2 + 2))}, root {fmt(m * (z1 - 2.5))} / {fmt(m * (z2 - 2.5))})")
        o.add("Center distance", f"{fmt(m * (z1 + z2) / 2)} mm")
    key, row = mat(inp, "pla")
    printed = key in ("pla", "petg", "abs", "asa", "pc", "pla cf", "tpu", "nylon")
    eta = 0.95 if printed else 0.98
    n1 = inp.num(["rpm", "rpm1", "input_rpm", "speed"], "rpm", "input rpm", hints=["rpm", "speed"])
    t1 = inp.num(["torque", "torque1", "input_torque"], "torque", "input torque", hints=["torque", "nm"])
    p = inp.num(["power"], "power", "power", hints=["power", "w ", "kw"])
    if p and n1 and not t1:
        t1 = p / (2 * math.pi * n1 / 60)
    if n1:
        o.add("Output speed", f"{fmt(n1 / ratio)} rpm (input {fmt(n1)} rpm)")
    if t1:
        o.add("Output torque", f"{show(t1 * ratio * eta, 'torque')} (efficiency {int(eta * 100)} %)")
    allow = GEAR_ALLOW.get(key, row[2] * 0.4) * 1e6
    if t1 and m:
        b = inp.num(["face_width", "width", "b", "thickness"], "length", "face width", default=None, hints=["wide", "width", "thick", "face"])
        if not b:
            b = 8 * m / 1000
            inp.assumed.append(f"face width = 8 × module = {fmt(8 * m)} mm")
        d1m = m * z1 / 1000
        ft = 2 * t1 / d1m
        v = math.pi * d1m * (n1 or 60) / 60
        kv = (6.1 + v) / 6.1
        s1 = kv * ft / (b * m / 1000 * lewis_y(z1))
        s2 = kv * ft / (b * m / 1000 * lewis_y(z2))
        o.add("Tooth force", show(ft, "force"))
        o.add("Tooth bending stress", f"small gear {show(s1, 'stress')}, big gear {show(s2, 'stress')} (Lewis, speed factor {fmt(kv)})")
        sf = allow / max(s1, s2)
        o.add("Safety factor", f"{fmt(sf)} ({row[7]}: about {fmt(allow / 1e6)} MPa for long life)")
        o.verdict = f"{'OK' if sf >= 1.5 else 'TOO WEAK'}: module {fmt(m)} × {fmt(b * 1000)} mm wide, safety factor {fmt(sf)}."
    elif t1 and not m:
        k = 8.0
        mm = (2 * t1 * 1.2 / (k * z1 * lewis_y(z1) * allow)) ** (1 / 3) * 1000
        std = pick_up(mm, STD_MODULE)
        o.add("Smallest module for this torque", f"{fmt(mm)} mm → use module {fmt(std)} (face width 8 × module)")
        o.verdict = f"Use module {fmt(std)} or bigger for {show(t1, 'torque')} on a {z1}-tooth gear in {key.upper() if printed else row[7]}."
    if min(z1, z2) < 17:
        o.warn(f"{min(z1, z2)} teeth: under 17 the teeth get undercut (weaker) — use ≥ 17 or profile shift.")
    if printed and m and m < 1:
        o.warn("Printed teeth smaller than module 1 come out poorly with a 0.4 mm nozzle.")
    if printed:
        o.note("Printed gears: 100 % infill or ≥ 4 walls at the teeth, print them flat; PETG / nylon wear better than PLA.")
    return o.done()


# ------------------------------------------------------------------ belts and pulleys
BELTS = {"gt2": 2, "2gt": 2, "gt3": 3, "3gt": 3, "gt5": 5, "htd3m": 3, "htd5m": 5, "htd8m": 8, "3m": 3, "5m": 5, "8m": 8,
         "t2.5": 2.5, "t5": 5, "t10": 10, "at5": 5, "at10": 10, "mxl": 2.032, "xl": 5.08, "l": 9.525}


def belt(inp: Inputs) -> dict:
    o = Out()
    kind = inp.text(["belt", "type", "belt_type", "profile"], "")
    low = (kind + " " + inp.question).lower()
    pitch = next((v for k, v in sorted(BELTS.items(), key=lambda kv: -len(kv[0])) if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", low)), None)
    pv = inp.num(["pitch"], "length", "belt pitch", text_ok=False)
    pitch = pv * 1000 if pv else pitch
    tt = teeth_in_text(inp.question)
    z1 = inp.num(["teeth1", "z1", "pulley1", "motor_pulley", "small_pulley", "driver"], "count", "teeth", text_ok=False) or (tt[0] if tt else None)
    z2 = inp.num(["teeth2", "z2", "pulley2", "driven", "big_pulley"], "count", "teeth", text_ok=False) or (tt[1] if len(tt) > 1 else None)
    d1 = inp.num(["diameter1", "d1", "small_diameter"], "length", "pulley diameter", text_ok=False)
    d2 = inp.num(["diameter2", "d2", "big_diameter"], "length", "pulley diameter", text_ok=False)
    if pitch and z1:
        z2 = z2 or z1
        d1, d2 = pitch * z1 / math.pi / 1000, pitch * z2 / math.pi / 1000
        o.add("Belt", f"{fmt(pitch)} mm pitch; pulleys {int(z1)}T / {int(z2)}T (pitch Ø {fmt(d1 * 1000)} / {fmt(d2 * 1000)} mm)")
    elif d1:
        d2 = d2 or d1
        o.add("Pulleys", f"Ø{fmt(d1 * 1000)} / Ø{fmt(d2 * 1000)} mm (flat / V belt)")
    else:
        inp.missing.append("the belt type and pulley teeth (e.g. GT2, 20T and 60T) or the pulley diameters")
        return o.done()
    ratio = d2 / d1
    o.add("Ratio", f"{fmt(ratio)} : 1")
    c = inp.num(["center_distance", "centre_distance", "distance", "c"], "length", "center distance", hints=["center", "centre", "distance", "apart"])
    length = inp.num(["belt_length", "length", "l"], "length", "belt length", hints=["belt length", "loop", "long"])
    if c:
        length = 2 * c + math.pi * (d1 + d2) / 2 + (d2 - d1) ** 2 / (4 * c)
        o.add("Belt length", f"{fmt(length * 1000)} mm" + (f" = {fmt(length * 1000 / pitch)} teeth → buy {round(length * 1000 / pitch) * pitch:g} mm ({round(length * 1000 / pitch)} teeth)" if pitch else ""))
    elif length:
        b = 2 * length - math.pi * (d1 + d2)
        disc = b * b - 8 * (d2 - d1) ** 2
        if disc < 0 or b <= 0:
            o.warn("That belt is too short for these pulleys.")
            return o.done()
        c = (b + math.sqrt(disc)) / 8
        o.add("Center distance", f"{fmt(c * 1000)} mm for a {fmt(length * 1000)} mm belt")
    if c:
        wrap = 180 - 2 * math.degrees(math.asin(min(1, abs(d2 - d1) / (2 * c))))
        o.add("Wrap on the small pulley", f"{fmt(wrap)}°" + (f" ({fmt((min(z1, z2) if z1 else 0) * wrap / 360)} teeth in mesh)" if pitch and z1 else ""))
        if pitch and z1 and min(z1, z2) * wrap / 360 < 6:
            o.warn("Fewer than 6 teeth in mesh: the belt can skip — bigger small pulley or longer center distance.")
    n = inp.num(["rpm", "input_rpm", "speed"], "rpm", "rpm", hints=["rpm"])
    if n:
        o.add("Output speed", f"{fmt(n / ratio)} rpm")
    if pitch and z1:
        steps = inp.num(["steps", "steps_per_rev", "full_steps"], "count", "motor steps per turn", default=200, text_ok=False)
        micro = inp.num(["microsteps", "microstepping"], "count", "microsteps", default=16, hints=["microstep"])
        travel = pitch * z1
        o.add("Travel per motor turn", f"{fmt(travel)} mm (Klipper rotation_distance = {fmt(travel)})")
        o.add("Steps per mm", f"{fmt(steps * micro / travel)} (Marlin M92, {int(steps)} steps × {int(micro)} microsteps)")
    return o.done()


# ------------------------------------------------------------------ lead screws
def leadscrew(inp: Inputs) -> dict:
    o = Out()
    spec = inp.text(["screw", "spec", "type", "leadscrew", "lead_screw", "designation"], "") + " " + inp.question
    m = re.search(r"\b(?:tr|t)\s?(\d+(?:[.,]\d+)?)\s?[x×]\s?(\d+(?:[.,]\d+)?)(?:\s?\(?p\s?(\d+(?:[.,]\d+)?)\)?)?", spec, re.I)
    d = lead = pitch = None
    if m:
        d, lead = float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
        pitch = float(m.group(3).replace(",", ".")) if m.group(3) else (2.0 if d == 8 and lead == 8 else lead)
    lv = inp.num(["lead", "lead_mm"], "length", "lead (mm per turn)", hints=["lead"])
    lead = lv * 1000 if lv else lead
    dv = inp.num(["diameter", "d", "screw_diameter"], "length", "screw diameter", text_ok=False)
    d = dv * 1000 if dv else d
    if not lead:
        inp.missing.append("the lead (mm per turn, e.g. T8x8 = 8 mm) ")
        return o.done()
    ball = bool(re.search(r"\bball|sfu\d|ballscrew", spec, re.I))
    if ball:
        eta, how = 0.9, "ball screw"
    elif d:
        p_ = pitch or min(lead, 2.0)
        dm = d - p_ / 2
        lam = math.atan(lead / (math.pi * dm))
        mu = inp.num(["friction", "mu"], "number", "friction", default=0.15, text_ok=False, show="0.15 (brass / POM nut, greased)")
        phi = math.atan(mu / math.cos(math.radians(15)))
        eta, how = math.tan(lam) / math.tan(lam + phi), f"trapezoidal, helix {fmt(math.degrees(lam))}°"
    else:
        eta, how = 0.35, "trapezoidal (typical)"
    o.add("Screw", f"{('Ø' + fmt(d) + ' mm, ') if d else ''}lead {fmt(lead)} mm/turn — {how}, efficiency ≈ {fmt(eta * 100)} %")
    t = inp.num(["torque", "motor_torque"], "torque", "motor torque", hints=["torque", "nm", "motor"])
    f = inp.num(["force", "thrust", "load"], "force", "force", hints=["force", "push", "thrust", "load"])
    mass = inp.num(["mass", "weight", "lift"], "mass", "mass lifted", hints=["lift", "weigh", "mass", "carry"])
    if mass and not f:
        f = mass * G * 1.2
        o.add("Load", f"{show(mass, 'mass')} lifted → {show(f, 'force')} incl. 20 % to accelerate")
    if t and not f:
        o.add("Thrust from that torque", show(2 * math.pi * eta * t / (lead / 1000), "force"))
    if f:
        o.add("Torque needed", show(f * lead / 1000 / (2 * math.pi * eta), "torque") + " (add 50–100 % margin for a stepper)")
    n = inp.num(["rpm", "speed"], "rpm", "rpm", hints=["rpm"])
    if n:
        o.add("Linear speed", f"{fmt(n * lead / 60)} mm/s at {fmt(n)} rpm")
    steps = inp.num(["steps", "full_steps"], "count", "steps", default=200, text_ok=False)
    micro = inp.num(["microsteps"], "count", "microsteps", default=16, hints=["microstep"])
    o.add("Steps per mm", f"{fmt(steps * micro / lead)} (Klipper rotation_distance = {fmt(lead)})")
    if ball or eta > 0.5:
        o.note("It back-drives: a vertical axis drops when the motor is off — use a brake or counterweight.")
    else:
        o.note("Self-locking: it holds its position with the motor off.")
    return o.done()


# ------------------------------------------------------------------ wheeled robots / vehicles
CRR = [("sand", 0.25), ("mud", 0.3), ("snow", 0.2), ("grass", 0.1), ("lawn", 0.1), ("dirt", 0.08), ("gravel", 0.05),
       ("carpet", 0.05), ("asphalt", 0.02), ("concrete", 0.015), ("tile", 0.015), ("floor", 0.015), ("wood", 0.015)]


def wheels(inp: Inputs) -> dict:
    o = Out()
    mass = inp.num(["mass", "weight", "robot_mass", "vehicle_mass"], "mass", "total mass", need=True, hints=["weigh", "mass", "kg", "heavy"])
    dia = inp.num(["wheel_diameter", "diameter", "wheel", "d"], "length", "wheel diameter", need=True, hints=["wheel", "diameter", "tyre", "tire"])
    if not (mass and dia):
        return o.done()
    n_all = int(inp.num(["wheels", "number_of_wheels", "wheel_count"], "count", "wheels", default=4, hints=["wheels"]) or 4)
    n_drv = int(inp.num(["driven", "driven_wheels", "motors", "motor_count"], "count", "driven wheels", default=n_all, hints=["motors", "driven"]) or n_all)
    slope = inp.num(["slope", "incline", "angle", "hill"], "angle", "slope", default=0.0,
                    hints=["slope", "incline", "hill", "ramp", "climb", "climbs", "up", "steep"])
    v = inp.num(["speed", "velocity", "top_speed"], "speed", "speed", hints=["speed", "km/h", "m/s"])
    acc = inp.num(["acceleration", "accel"], "accel", "acceleration", default=0.5, text_ok=False, show="0.5 m/s²")
    surface = inp.text(["surface", "ground", "terrain", "floor"], "", [k for k, _ in CRR])
    crr = next((c for k, c in CRR if k in surface), None)
    if crr is None:
        crr = 0.03
        inp.assumed.append("rolling resistance 0.03 (hard ground, rubber wheels)")
    mu = inp.num(["grip", "friction", "mu"], "number", "tyre grip", default=0.7, text_ok=False, show="0.7 (rubber on hard ground)")
    eta = inp.num(["efficiency", "gearbox_efficiency"], "number", "drive efficiency", default=0.8, text_ok=False, show="0.8")
    th = math.radians(slope)
    w = mass * G
    f = w * math.sin(th) + crr * w * math.cos(th) + mass * acc
    r = dia / 2
    t_each = f * r / n_drv
    o.add("Force to push", f"{show(f, 'force')} (slope {fmt(slope)}°, rolling {crr}, accel {fmt(acc)} m/s²)")
    o.add("Torque per driven wheel", f"{show(t_each, 'torque')} — pick motors with ≥ {fmt(t_each * 2)} N·m (2× margin)")
    if v:
        rpm = v / (math.pi * dia) * 60
        o.add("Wheel speed", f"{fmt(rpm)} rpm for {show(v, 'speed')}")
        o.add("Power", f"{show(f * v / eta, 'power')} total ({show(f * v / eta / n_drv, 'power')} per motor)")
    grip = mu * w * math.cos(th) * n_drv / n_all
    o.add("Grip limit", f"{show(grip, 'force')} ({n_drv} of {n_all} wheels driven, grip {mu})")
    ok = f <= grip
    o.verdict = f"{'It climbs' if ok else 'The wheels SLIP'}: needs {show(f, 'force')}, the tyres can push {show(grip, 'force')}."
    climb = math.degrees(math.atan(mu * n_drv / n_all)) if n_drv < n_all else math.degrees(math.atan(mu))
    o.add("Steepest slope by grip", f"≈ {fmt(climb)}°")
    h = inp.num(["cog_height", "center_of_gravity", "cg_height", "height_of_cog"], "length", "height of the centre of mass", text_ok=False)
    wb = inp.num(["wheelbase", "length_between_axles"], "length", "wheelbase", text_ok=False)
    tr = inp.num(["track", "track_width", "width_between_wheels"], "length", "track width", text_ok=False)
    if h and (wb or tr):
        if wb:
            o.add("Tips over going up / down at", f"{fmt(math.degrees(math.atan(wb / 2 / h)))}°")
        if tr:
            o.add("Tips over sideways at", f"{fmt(math.degrees(math.atan(tr / 2 / h)))}°")
    return o.done()


# ------------------------------------------------------------------ arm / servo torque
SERVOS = [("SG90 (plastic gears)", 1.8, 9), ("MG90S (metal gears)", 2.2, 13.4), ("MG92B", 3.5, 13.8),
          ("Hitec HS-311", 3.7, 43), ("MG995", 10, 55), ("MG996R (6 V)", 11, 55), ("DS3218 (6.8 V)", 21.5, 60),
          ("STS3215 (7.4 V)", 19.5, 55), ("DS3225 (6.8 V)", 25, 60), ("DS3235 (6.8 V)", 35, 65)]  # kg·cm stall, grams
STEPPERS = [("NEMA 17, 40 mm long", 0.40), ("NEMA 17, 48 mm", 0.55), ("NEMA 17 + 5:1 planetary", 2.0),
            ("NEMA 23, 56 mm", 1.26), ("NEMA 23, 76 mm", 1.9), ("NEMA 17 + 27:1 planetary", 5.0)]  # N·m holding


def arm(inp: Inputs) -> dict:
    o = Out()
    links = inp.nums(["links", "lengths", "link_lengths", "segments", "arm_lengths"], "length",
                     hints=["long", "length", "arm", "lever", "reach"])
    links = [x for x in links if x and x > 0]  # a "0" link once printed "Joint 2: 0 N·m -> SG90"
    if not links:
        one = inp.num(["length", "arm_length", "arm", "lever", "distance", "radius", "reach"], "length", "arm length",
                      need=True, hints=["long", "length", "arm", "lever", "distance", "reach", "cm"])
        links = [one] if one else []
    if not links:
        return o.done()
    masses = [x for x in inp.nums(["link_masses", "masses", "link_mass", "arm_masses"], "mass") if x and x > 0]  # not a made-up 0
    if not masses:
        lm = inp.num(["arm_mass", "link_weight", "arm_weight", "mass_of_arm"], "mass", "arm mass", text_ok=False)
        if lm:
            masses = [lm] * len(links)
        else:
            masses = [L * 1.25 for L in links]  # printed PLA link ~ 20 x 10 mm, 50 % infill: ~1.25 g per cm
            inp.assumed.append("each printed link weighs ~1.25 g per cm of length")
    masses = (masses + [masses[-1]] * len(links))[:len(links)]
    joints = inp.nums(["joint_masses", "servo_masses", "motor_masses", "servo_mass"], "mass")
    payload = inp.num(["payload", "load", "mass", "weight", "lift"], "mass", "payload", default=0.0,
                      hints=["payload", "lift", "hold", "carry", "weigh", "object", "load"], show="0 (no load)")
    sf = inp.num(["sf", "safety", "safety_factor"], "number", "safety factor", default=2.0, hints=["safety"])
    xs = [sum(links[:i]) for i in range(len(links) + 1)]  # joint positions (arm stretched out flat: the worst case)
    rows = []
    for i in range(len(links)):
        t = payload * G * (xs[-1] - xs[i])
        t += sum(masses[j] * G * ((xs[j] + xs[j + 1]) / 2 - xs[i]) for j in range(i, len(links)))
        t += sum((joints[k] if k < len(joints) else 0) * G * (xs[k] - xs[i]) for k in range(i + 1, len(links)))
        rows.append(t)
    for i, t in enumerate(rows):
        need = t * sf / G * 100  # kg·cm with the safety factor
        servo = next((f"{n} ({s} kg·cm)" for n, s, _ in SERVOS if s >= need), None)
        step = next((f"{n} ({s} N·m)" for n, s in STEPPERS if s >= t * sf), None)
        o.add(f"Joint {i + 1}" + (" (base / shoulder)" if i == 0 and len(rows) > 1 else ""),
              f"{show(t, 'torque')} holding the arm straight out → with ×{fmt(sf)}: {fmt(need)} kg·cm"
              + (f"; servo: {servo}" if servo else "; no hobby servo is enough")
              + (f"; stepper: {step}" if step and not servo else ""))
    o.add("Reach", f"{fmt(xs[-1] * 1000)} mm, payload {show(payload, 'mass')}")
    o.note("Worst case = the arm held straight out sideways. Servo stall torques are datasheet values; run them below ~50 % for long life. "
           "Moving fast needs more (inertia).")
    return o.done()


# ------------------------------------------------------------------ cross sections (beams, columns)
def section(inp: Inputs):
    """(I about the bending axis, W = I / c, area, I_min, description). Sizes in metres."""
    shape = inp.text(["section", "shape", "profile", "cross_section"], "",
                     ["square tube", "rectangular tube", "box section", "tube", "pipe", "round", "rod", "dowel", "bar",
                      "rectangle", "rectangular", "flat", "plank", "board", "square", "solid"])
    dims = inp._raw(["size", "dimensions", "dims", "section_size", "profile_size"])
    if not dims and re.search(r"\d\s*[x×*]\s*\d", shape):
        dims = (shape, "")
    ds = []
    if dims:
        ds = [parse(x + (" " + re.sub(r"[\d.,x×\s]+", "", str(dims[0])) if not re.search(r"[a-z]", x) else ""), "length", "mm")
              for x in re.split(r"\s*[x×*]\s*", re.sub(r"(?i)\s*(mm|cm|m|in)\b", r" \1", str(dims[0])).strip())]
        ds = [x for x in ds if x]
    b = inp.num(["width", "b", "w"], "length", "width", text_ok=False) or (ds[0] if len(ds) >= 2 else None)
    h = inp.num(["height", "h", "depth", "thickness_vertical"], "length", "height", text_ok=False) or (ds[1] if len(ds) >= 2 else None)
    d = inp.num(["diameter", "d", "outer_diameter", "od"], "length", "diameter", text_ok=False)
    t = inp.num(["wall", "wall_thickness", "t", "thickness"], "length", "wall", text_ok=False) or (ds[2] if len(ds) >= 3 else None)
    di = inp.num(["inner_diameter", "id", "inner"], "length", "inner diameter", text_ok=False)
    q = inp.question.lower()
    if not (b or d):  # "a 20x40 mm bar" / "Ø20 tube"
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*[x×]\s*(\d+(?:[.,]\d+)?)(?:\s*[x×]\s*(\d+(?:[.,]\d+)?))?\s*(mm|cm|m|in)?", q)
        if m:
            u = m.group(4) or "mm"
            b, h = parse(f"{m.group(1)} {u}", "length"), parse(f"{m.group(2)} {u}", "length")
            t = parse(f"{m.group(3)} {u}", "length") if m.group(3) else t
        m = re.search(r"(?:ø|dia\w*|diameter)\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|in)?|(\d+(?:[.,]\d+)?)\s*(mm|cm|in)?\s*(?:diameter|dia\b|round|rod|tube|pipe|dowel)", q)
        if m and not b:
            d = parse(f"{m.group(1) or m.group(3)} {m.group(2) or m.group(4) or 'mm'}", "length")
    tube = any(w in shape for w in ("tube", "pipe", "box")) or bool(t and (d or b))
    if d:
        if tube and (t or di):
            dd = di if di else d - 2 * t
            i = math.pi * (d ** 4 - dd ** 4) / 64
            return i, i / (d / 2), math.pi * (d ** 2 - dd ** 2) / 4, i, f"tube Ø{fmt(d * 1000)} × {fmt((d - dd) / 2 * 1000)} mm wall"
        i = math.pi * d ** 4 / 64
        return i, i / (d / 2), math.pi * d * d / 4, i, f"round Ø{fmt(d * 1000)} mm"
    if b and h:
        if tube and t:
            i = (b * h ** 3 - (b - 2 * t) * (h - 2 * t) ** 3) / 12
            i2 = (h * b ** 3 - (h - 2 * t) * (b - 2 * t) ** 3) / 12
            return i, i / (h / 2), b * h - (b - 2 * t) * (h - 2 * t), min(i, i2), f"box tube {fmt(b * 1000)} × {fmt(h * 1000)} × {fmt(t * 1000)} mm"
        return b * h ** 3 / 12, b * h * h / 6, b * h, min(b * h ** 3, h * b ** 3) / 12, f"rectangle {fmt(b * 1000)} wide × {fmt(h * 1000)} high"
    if b and "square" in shape:
        return b ** 4 / 12, b ** 3 / 6, b * b, b ** 4 / 12, f"square {fmt(b * 1000)} mm"
    return None


SUPPORTS = {  # (deflection factor for point load, for uniform load (total W), moment factor point, moment uniform)
    "cantilever": (1 / 3, 1 / 8, 1.0, 0.5),
    "simple": (1 / 48, 5 / 384, 0.25, 0.125),
    "fixed": (1 / 192, 1 / 384, 0.125, 1 / 12),
}


def beam(inp: Inputs) -> dict:
    o = Out()
    length = inp.num(["length", "span", "l", "beam_length"], "length", "length (span)", need=True, hints=["long", "length", "span", "between"])
    load = inp.num(["load", "force", "weight", "mass"], "force", "load", need=True, hints=["load", "weigh", "kg", "carry", "hold", "force", "support"])
    sec = section(inp)
    if not sec:
        inp.missing.append("the cross section (e.g. 20 × 40 mm rectangle, Ø20 rod, 30 × 30 × 2 mm tube)")
    if not (length and load and sec):
        return o.done()
    i, w, area, imin, desc = sec
    sup = inp.text(["support", "supports", "type", "beam_type", "ends"], "", ["cantilever", "one end", "wall", "shelf bracket",
                                                                             "simply", "both ends", "two supports", "fixed", "clamped"])
    kind = "cantilever" if re.search(r"cantilever|one end|wall|bracket|sticking out|overhang", sup) else \
        "fixed" if re.search(r"fixed|clamp|built.?in|welded both", sup) else "simple" if sup else None
    if not kind:
        kind = "simple"
        inp.assumed.append("supported at both ends (say 'cantilever' if it sticks out from one end)")
    lt = inp.text(["load_type", "distribution", "loading"], "", ["uniform", "spread", "evenly", "distributed", "point", "end", "middle", "center", "centre"])
    uniform = bool(re.search(r"uniform|spread|even|distribut|shelf", lt + " " + inp.question.lower()))
    key, row = mat(inp, "steel")
    e, sy = row[1] * 1e9, row[2] * 1e6
    kd = SUPPORTS[kind][1 if uniform else 0]
    km = SUPPORTS[kind][3 if uniform else 2]
    wself = row[0] * area * length * G
    defl = kd * load * length ** 3 / (e * i) + SUPPORTS[kind][1] * wself * length ** 3 / (e * i)
    mom = km * load * length + SUPPORTS[kind][3] * wself * length
    sig = mom / w
    sf = sy / sig
    o.add("Beam", f"{desc}, {fmt(length * 1000)} mm, {row[7]}")
    o.add("Load", f"{show(load, 'force')} {'spread along it' if uniform else ('at the free end' if kind == 'cantilever' else 'in the middle')} "
                  f"(+ own weight {fmt(wself / G * 1000)} g); {'cantilever' if kind == 'cantilever' else 'fixed both ends' if kind == 'fixed' else 'supported at both ends'}")
    o.add("Bends (deflection)", f"{fmt(defl * 1000)} mm (= length / {fmt(length / defl) if defl else '∞'})")
    o.add("Max stress", f"{show(sig, 'stress')} → safety factor {fmt(sf)} (strength {row[2]} MPa)")
    ok_s, ok_d = sf >= 2, defl <= length / 250
    o.verdict = ("OK: strong and stiff enough." if ok_s and ok_d else
                 f"{'TOO WEAK' if not ok_s else 'OK for strength'}{', ' if True else ''}{'bends too much (> length/250)' if not ok_d else 'stiff enough'}.")
    if key in ("pla", "petg", "abs", "asa", "pc", "nylon", "pla cf"):
        o.note("Printed: lay it flat so the layers run along the beam; across the layers it's about half as strong. Plastic creeps under a constant load — keep the stress under ~1/4 of the strength.")
    if key in ("wood", "oak", "plywood", "mdf"):
        o.note("Wood creeps: a shelf loaded for years sags ~1.5–2× more than this.")
    return o.done()


def column(inp: Inputs) -> dict:
    o = Out()
    length = inp.num(["length", "height", "l"], "length", "length", need=True, hints=["long", "length", "tall", "high"])
    sec = section(inp)
    if not sec:
        inp.missing.append("the cross section")
    if not (length and sec):
        return o.done()
    _, _, area, imin, desc = sec
    ends = inp.text(["ends", "support", "end_condition", "fixing"], "", ["fixed-free", "free", "fixed-pinned", "fixed both", "fixed-fixed", "pinned", "hinged"])
    k = 2.0 if "free" in ends else 0.5 if re.search(r"fixed.?fixed|both fixed|fixed both", ends) else 0.7 if "fixed" in ends else 1.0
    if not ends:
        inp.assumed.append("pinned at both ends (K = 1)")
    key, row = mat(inp, "steel")
    e, sy = row[1] * 1e9, row[2] * 1e6
    r = math.sqrt(imin / area)
    lam = k * length / r
    lam_c = math.sqrt(2 * math.pi ** 2 * e / sy)
    pcr = math.pi ** 2 * e * imin / (k * length) ** 2 if lam >= lam_c else area * (sy - (sy * lam / (2 * math.pi)) ** 2 / e)
    o.add("Column", f"{desc}, {fmt(length * 1000)} mm, ends K = {k}, {row[7]}")
    o.add("Buckling load", f"{show(pcr, 'force')} ({'Euler' if lam >= lam_c else 'Johnson (short column)'}, slenderness {fmt(lam)})")
    load = inp.num(["load", "force", "weight"], "force", "load", hints=["load", "weigh", "kg", "carry", "force", "support"])
    sf = inp.num(["sf", "safety"], "number", "safety factor", default=3.0, text_ok=False, show="3 (buckling)")
    o.add("Safe load", show(pcr / sf, "force") + f" (÷ {fmt(sf)})")
    if load:
        o.verdict = f"{'OK' if load <= pcr / sf else 'NOT OK'}: {show(load, 'force')} vs safe {show(pcr / sf, 'force')}."
    return o.done()


# ------------------------------------------------------------------ springs (helical compression)
SPRING_WIRE = {"music": (2211, 0.145, 81.7, 0.45, "music wire"), "hard": (1783, 0.190, 80.0, 0.45, "hard-drawn steel"),
               "oil": (1855, 0.187, 77.2, 0.50, "oil-tempered"), "chrome": (2005, 0.168, 77.2, 0.50, "chrome-vanadium"),
               "stainless": (1867, 0.146, 69.0, 0.35, "stainless 302"), "bronze": (1000, 0.0, 41.4, 0.35, "phosphor bronze")}


def spring(inp: Inputs) -> dict:
    o = Out()
    d = inp.num(["wire", "wire_diameter", "d", "wire_d"], "length", "wire diameter", need=True, hints=["wire"])
    od = inp.num(["outer_diameter", "od", "outside_diameter", "diameter"], "length", "outer diameter", hints=["outer", "outside", "od", "diameter"])
    dm = inp.num(["mean_diameter", "mean", "dm"], "length", "mean diameter", text_ok=False)
    n = inp.num(["coils", "active_coils", "n", "turns"], "count", "active coils", hints=["coils", "turns"])
    rate = inp.num(["rate", "k", "spring_rate", "stiffness"], "stiffness", "spring rate", hints=["rate", "n/mm"])
    if not d:
        return o.done()
    dmean = dm or ((od - d) if od else None)
    if not dmean:
        inp.missing.append("the outer diameter of the spring")
        return o.done()
    wire = inp.text(["material", "wire_material"], "music", ["stainless", "chrome", "oil", "hard", "bronze", "music", "piano"])
    a, m_, gg, share, wname = SPRING_WIRE.get(next((k for k in SPRING_WIRE if k in wire), "music"))
    gmod = gg * 1e9
    c = dmean / d
    if not n and rate:
        n = gmod * d ** 4 / (8 * dmean ** 3 * rate)
        o.add("Active coils for that rate", f"{fmt(n)}")
    if not n:
        inp.missing.append("the number of active coils (or the spring rate you want)")
        return o.done()
    k = gmod * d ** 4 / (8 * dmean ** 3 * n)
    kw = (4 * c - 1) / (4 * c - 4) + 0.615 / c
    sut = a / ((d * 1000) ** m_) * 1e6
    tau_allow = share * sut
    o.add("Spring", f"{wname} Ø{fmt(d * 1000)} mm, outer Ø{fmt((dmean + d) * 1000)} mm, {fmt(n)} active coils (index {fmt(c)})")
    o.add("Rate", f"{fmt(k / 1000)} N/mm ({fmt(k / 1000 / G * 1000)} g per mm)")
    l0 = inp.num(["free_length", "length", "l0"], "length", "free length", hints=["free length", "long", "length"])
    if l0:
        ls = (n + 2) * d
        o.add("Solid length", f"{fmt(ls * 1000)} mm (closed & ground ends) → travel {fmt((l0 - ls) * 1000)} mm, force at solid {show(k * (l0 - ls), 'force')}")
        tau_s = kw * 8 * k * (l0 - ls) * dmean / (math.pi * d ** 3)
        o.add("Stress when fully pressed", f"{show(tau_s, 'stress')} vs allowed {show(tau_allow, 'stress')}")
        if tau_s > tau_allow:
            o.warn("Pressed all the way it takes a set (gets shorter): limit the travel or use thicker wire.")
        if l0 / dmean > 4:
            o.warn("Long and thin (free length > 4 × diameter): it can buckle sideways — put it on a rod or in a tube.")
    f = inp.num(["force", "load"], "force", "force", hints=["force", "load", "push"])
    x = inp.num(["deflection", "compression", "travel", "stroke"], "length", "compression", hints=["compress", "deflect", "travel", "stroke"])
    if x and not f:
        f = k * x
        o.add(f"Force at {fmt(x * 1000)} mm", show(f, "force"))
    elif f and not x:
        o.add(f"Compression at {show(f, 'force')}", f"{fmt(f / k * 1000)} mm")
    if f:
        tau = kw * 8 * f * dmean / (math.pi * d ** 3)
        o.add("Wire stress", f"{show(tau, 'stress')} (allowed ~{show(tau_allow, 'stress')})")
    if c < 4 or c > 12:
        o.warn(f"Spring index {fmt(c)}: 4–12 is easy to make and works well.")
    return o.done()


# ------------------------------------------------------------------ ball bearings (deep groove)
BEARINGS = {"625": (5, 16, 5, 1.14, 0.38), "608": (8, 22, 7, 3.45, 1.37), "61800": (10, 19, 5, 1.72, 0.83),
            "6800": (10, 19, 5, 1.72, 0.83), "6000": (10, 26, 8, 4.75, 1.96), "6001": (12, 28, 8, 5.4, 2.36),
            "6002": (15, 32, 9, 5.85, 2.85), "6003": (17, 35, 10, 6.37, 3.25), "6004": (20, 42, 12, 9.95, 5.0),
            "6005": (25, 47, 12, 11.9, 6.55), "6200": (10, 30, 9, 5.4, 2.36), "6201": (12, 32, 10, 7.28, 3.1),
            "6202": (15, 35, 11, 8.06, 3.75), "6203": (17, 40, 12, 9.95, 4.75), "6204": (20, 47, 14, 13.5, 6.55),
            "6205": (25, 52, 15, 14.8, 7.8)}  # bore, outer, width mm; C, C0 kN (catalogue values, SKF-type)
EY = [(0.014, 0.19, 2.30), (0.028, 0.22, 1.99), (0.056, 0.26, 1.71), (0.084, 0.28, 1.55), (0.11, 0.30, 1.45),
      (0.17, 0.34, 1.31), (0.28, 0.38, 1.15), (0.42, 0.42, 1.04), (0.56, 0.44, 1.00)]


def bearing(inp: Inputs) -> dict:
    o = Out()
    code = inp.text(["bearing", "code", "type", "model"], "")
    m = re.search(r"\b(6[0-9]{3}|618\d\d|625|608)\b", code + " " + inp.question)
    fr = inp.num(["radial", "radial_load", "load", "force"], "force", "radial load", need=True, hints=["load", "radial", "force", "kg"])
    fa = inp.num(["axial", "axial_load", "thrust"], "force", "axial load", default=0.0, hints=["axial", "thrust"], show="0")
    n = inp.num(["rpm", "speed"], "rpm", "rpm", hints=["rpm", "speed"])
    want_h = inp.num(["hours", "life", "life_hours"], "time", "life wanted", text_ok=False)
    c = inp.num(["c", "dynamic_rating", "dynamic_load_rating"], "force", "dynamic rating C", text_ok=False)
    c0 = inp.num(["c0", "static_rating"], "force", "static rating C0", text_ok=False)
    name = None
    if m and m.group(1) in BEARINGS:
        name = m.group(1)
        bd, bo, bw, ck, c0k = BEARINGS[name]
        c, c0 = c or ck * 1000, c0 or c0k * 1000
        o.add("Bearing", f"{name}: {bd} × {bo} × {bw} mm, C = {ck} kN, C0 = {c0k} kN")
    if not fr:
        return o.done()
    if not c:
        bore = inp.num(["bore", "shaft", "inner_diameter"], "length", "shaft diameter", text_ok=False)
        cands = [(k, v) for k, v in BEARINGS.items() if not bore or abs(v[0] - bore * 1000) < 0.5]
        if not cands or not n:
            inp.missing.append("the bearing (e.g. 608, 6201) or its C rating, and the rpm")
            return o.done()
        need_h = want_h / 3600 if want_h else 20000
        for k, v in sorted(cands, key=lambda kv: kv[1][3]):
            l10h = 1e6 / (60 * n) * (v[3] * 1000 / max(fr, 1)) ** 3
            if l10h >= need_h:
                o.add("Smallest bearing that lasts", f"{k} ({v[0]}×{v[1]}×{v[2]} mm): {fmt(l10h)} h ≥ {fmt(need_h)} h")
                break
        else:
            o.warn("None of the common bearings in the list lasts that long — use a bigger series or two bearings.")
        return o.done()
    p = fr
    if fa > 0 and c0:
        ratio = fa / c0
        e, y = EY[0][1:] if ratio <= EY[0][0] else EY[-1][1:]
        for (r0, e0, y0), (r1, e1, y1) in zip(EY, EY[1:]):
            if r0 <= ratio <= r1:
                t = (ratio - r0) / (r1 - r0)
                e, y = e0 + t * (e1 - e0), y0 + t * (y1 - y0)
        if fa / fr > e:
            p = 0.56 * fr + y * fa
    l10 = (c / p) ** 3
    o.add("Equivalent load", show(p, "force"))
    o.add("Life (L10, 90 % survive)", f"{fmt(l10)} million turns" + (f" = {fmt(l10 * 1e6 / (60 * n))} hours at {fmt(n)} rpm" if n else ""))
    if c0:
        p0 = max(fr, 0.6 * fr + 0.5 * fa)
        o.add("Static safety", f"{fmt(c0 / p0)} (≥ 1 normal, ≥ 2 with shocks)")
    if n:
        h = l10 * 1e6 / (60 * n)
        o.verdict = f"{fmt(h)} hours" + (" — fine for hobby machines (5 000–20 000 h is typical)." if h >= 5000 else " — short: bigger bearing or less load.")
    return o.done()


# ------------------------------------------------------------------ fits (ISO 286) and printed fits
RANGES = [3, 6, 10, 18, 30, 50, 80, 120, 180, 250, 315, 400, 500]
IT = {4: [3, 4, 4, 5, 6, 7, 8, 10, 12, 14, 16, 18, 20], 5: [4, 5, 6, 8, 9, 11, 13, 15, 18, 20, 23, 25, 27],
      6: [6, 8, 9, 11, 13, 16, 19, 22, 25, 29, 32, 36, 40], 7: [10, 12, 15, 18, 21, 25, 30, 35, 40, 46, 52, 57, 63],
      8: [14, 18, 22, 27, 33, 39, 46, 54, 63, 72, 81, 89, 97], 9: [25, 30, 36, 43, 52, 62, 74, 87, 100, 115, 130, 140, 155],
      10: [40, 48, 58, 70, 84, 100, 120, 140, 160, 185, 210, 230, 250], 11: [60, 75, 90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
      12: [100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630], 13: [140, 180, 220, 270, 330, 390, 460, 540, 630, 720, 810, 890, 970]}
ES_SHAFT = {"d": [-20, -30, -40, -50, -65, -80, -100, -120, -145, -170, -190, -210, -230],
            "e": [-14, -20, -25, -32, -40, -50, -60, -72, -85, -100, -110, -125, -135],
            "f": [-6, -10, -13, -16, -20, -25, -30, -36, -43, -50, -56, -62, -68],
            "g": [-2, -4, -5, -6, -7, -9, -10, -12, -14, -15, -17, -18, -20], "h": [0] * 13}
EI_SHAFT = {"k": [0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 4, 4, 5], "m": [2, 4, 6, 7, 8, 9, 11, 13, 15, 17, 20, 21, 23],
            "n": [4, 8, 10, 12, 15, 17, 20, 23, 27, 31, 34, 37, 40], "p": [6, 12, 15, 18, 22, 26, 32, 37, 43, 50, 56, 62, 68]}
SUB = [3, 6, 10, 18, 30, 40, 50, 65, 80, 100, 120, 140, 160, 180, 200, 225, 250, 280, 315, 355, 400, 450, 500]
C_SUB = [-60, -70, -80, -95, -110, -120, -130, -140, -150, -170, -180, -200, -210, -230, -240, -260, -280, -300, -330, -360, -400, -440, -480]
R_SUB = [10, 15, 19, 23, 28, 34, 34, 41, 43, 51, 54, 63, 65, 68, 77, 80, 84, 94, 98, 108, 114, 126, 132]
S_SUB = [14, 19, 23, 28, 35, 43, 43, 53, 59, 71, 79, 92, 100, 108, 122, 130, 140, 158, 170, 190, 208, 232, 252]
FIT_WORDS = [("press", "H7/p6", "press fit (needs a press; holds by itself)"), ("interference", "H7/s6", "medium drive fit"),
             ("shrink", "H7/s6", "shrink / drive fit"), ("light press", "H7/k6", "light press / tap in (transition)"),
             ("tap", "H7/k6", "tap in with a mallet (transition)"), ("transition", "H7/k6", "transition fit"),
             ("bearing", "H7/k6", "bearing seat: shaft k6 for a turning shaft, housing H7"),
             ("slid", "H7/g6", "sliding fit (slides and turns, precise)"), ("locat", "H7/h6", "locating fit (snug, assembles by hand)"),
             ("snug", "H7/h6", "snug locating fit"), ("running", "H8/f7", "running fit (turns freely, oiled)"),
             ("rotat", "H8/f7", "running fit (turns freely, oiled)"), ("free", "H9/d9", "free running fit"),
             ("loose", "H11/c11", "loose running fit")]


def _rng(size_mm: float, table=RANGES) -> int:
    return next((i for i, top in enumerate(table) if size_mm <= top), len(table) - 1)


def _shaft(letter: str, grade: int, s: float):
    i, it = _rng(s), IT[grade][_rng(s)]
    if letter == "js":
        return it / 2, -it / 2
    if letter == "c":
        es = C_SUB[_rng(s, SUB)]
        return es, es - it
    if letter in ES_SHAFT:
        es = ES_SHAFT[letter][i]
        return es, es - it
    if letter == "r":
        ei = R_SUB[_rng(s, SUB)]
    elif letter == "s":
        ei = S_SUB[_rng(s, SUB)]
    elif letter == "k":
        ei = EI_SHAFT["k"][i] if 4 <= grade <= 7 else 0
    else:
        ei = EI_SHAFT[letter][i]
    return ei + it, ei


def _hole(letter: str, grade: int, s: float):
    i, it = _rng(s), IT[grade][_rng(s)]
    lo = letter.lower()
    if lo == "h":
        return it, 0
    if lo == "js":
        return it / 2, -it / 2
    if lo in ("c", "d", "e", "f", "g"):
        ei = -_shaft(lo, grade, s)[0]
        return ei + it, ei
    if lo in ("k", "m", "n", "p"):
        delta = it - IT[grade - 1][i] if grade - 1 in IT else 0
        base = EI_SHAFT[lo][i] if lo != "k" or 4 <= grade <= 7 else 0
        es = (-base + delta) if (grade <= 8 and lo in ("k", "m", "n")) or (grade <= 7 and lo == "p") else -base
        if lo in ("k", "n") and grade > 8:
            es = 0
        return es, es - it
    raise KeyError(letter)


def fit(inp: Inputs) -> dict:
    o = Out()
    size = inp.num(["size", "diameter", "nominal", "d", "shaft", "hole", "nominal_size"], "length", "nominal size", need=True,
                   hints=["diameter", "ø", "mm", "shaft", "hole", "pin", "bearing"])
    if not size:
        return o.done()
    s = size * 1000
    words = (inp.text(["fit", "fit_type", "type", "tolerance"], "") + " " + inp.question).lower()
    printed = bool(re.search(r"print|\b3d\b|\bpla\b|petg|\babs\b|fdm|nozzle", words)) or inp.text(["process", "method"], "").startswith("print")
    code = re.search(r"\b([a-z]{1,2})(\d{1,2})\s*/\s*([a-z]{1,2})(\d{1,2})\b", words, re.I)
    if printed:
        try:
            import json as _j
            from pathlib import Path as _P
            pf = _j.loads((_P(__file__).resolve().parents[2] / "data" / "settings.json").read_text(encoding="utf-8")).get("print_fit")
        except (OSError, ValueError):
            pf = None
        gap = float(pf) if pf not in (None, "") else 0.2
        src = f"your printer's fit test ({fmt(gap)} mm)" if pf not in (None, "") else "0.2 mm (default — print a fit test to measure yours)"
        kinds = [("press", -0.1, "press fit (tap in, holds)"), ("snug", 0.0, "snug / sliding fit"), ("slid", 0.0, "sliding fit"),
                 ("rotat", 0.15, "turns freely"), ("running", 0.15, "turns freely"), ("loose", 0.3, "loose")]
        k = next(((w, a, t) for w, a, t in kinds if w in words), ("snug", 0.0, "snug fit"))
        extra = max(0.0, gap + k[1])
        o.add("Printed fit", f"{k[2]}: draw the hole Ø{fmt(s + extra)} mm for a Ø{fmt(s)} mm part (clearance from {src})")
        o.add("Other fits", f"press Ø{fmt(s + max(0, gap - 0.1))} · snug Ø{fmt(s + gap)} · turns freely Ø{fmt(s + gap + 0.15)} · loose Ø{fmt(s + gap + 0.3)} mm")
        o.note("For a pin into a printed hole you can instead make the pin smaller by the same amount. Holes print smaller than drawn, outsides about true.")
        return o.done()
    if code:
        hl, hg, sl, sg = code.group(1), int(code.group(2)), code.group(3), int(code.group(4))
        name = f"{hl.upper()}{hg}/{sl.lower()}{sg}"
    else:
        hit = next(((c, t) for w, c, t in FIT_WORDS if w in words), ("H7/h6", "locating fit"))
        name = hit[0]
        m2 = re.match(r"([A-Z]+)(\d+)/([a-z]+)(\d+)", name)
        hl, hg, sl, sg = m2.group(1), int(m2.group(2)), m2.group(3), int(m2.group(4))
        o.add("Fit chosen", f"{name} — {hit[1]}")
    if s > 500 or hg not in IT or sg not in IT:
        o.warn("Only sizes up to 500 mm and grades IT4–IT13 are in the table.")
        return o.done()
    try:
        hes, hei = _hole(hl, hg, s)
        ses, sei = _shaft(sl.lower(), sg, s)
    except KeyError:
        o.warn(f"{name}: hole letters C–H, JS, K, M, N, P and shaft letters c–h, js, k, m, n, p, r, s are supported.")
        return o.done()
    o.add("Hole", f"Ø{fmt(s)} {hl.upper()}{hg}: {fmt(s + hei / 1000, 6)} … {fmt(s + hes / 1000, 6)} mm ({hei:+g} / {hes:+g} µm)")
    o.add("Shaft", f"Ø{fmt(s)} {sl.lower()}{sg}: {fmt(s + sei / 1000, 6)} … {fmt(s + ses / 1000, 6)} mm ({sei:+g} / {ses:+g} µm)")
    cmin, cmax = hei - ses, hes - sei
    kind = "clearance" if cmin >= 0 else "interference" if cmax <= 0 else "transition"
    o.add("Clearance", f"{cmin:+g} … {cmax:+g} µm → {kind} fit" + (" (negative = interference)" if cmin < 0 else ""))
    o.verdict = f"{name} at Ø{fmt(s)} mm is {'an' if kind[0] in 'aeiou' else 'a'} {kind} fit ({cmin:+g} to {cmax:+g} µm)."
    return o.done()


# ------------------------------------------------------------------ heat expansion, weight, drops, motors
def thermal(inp: Inputs) -> dict:
    o = Out()
    length = inp.num(["length", "size", "l"], "length", "length", need=True, hints=["long", "length", "mm", "m "])
    dt = inp.num(["delta_t", "temperature_change", "dt", "temperature_rise"], "temp", "temperature change", text_ok=False)
    if dt is None:
        t1 = inp.num(["from", "t1", "start_temperature", "cold"], "temp", "start temperature", text_ok=False)
        t2 = inp.num(["to", "t2", "end_temperature", "hot"], "temp", "end temperature", text_ok=False)
        temps = [q for q in inp.qs if "temp" in q["kinds"]]
        if t1 is None and t2 is None and len(temps) >= 2:
            t1, t2 = (parse(f"{q['v']} {q['unit']}", "temp") for q in temps[:2])
        if t1 is not None and t2 is not None:
            dt = t2 - t1
        elif len(temps) == 1:
            dt = parse(f"{temps[0]['v']} {temps[0]['unit']}", "temp")
    if not length or dt is None:
        if dt is None:
            inp.missing.append("the temperature change (°C)")
        return o.done()
    key, row = mat(inp, "aluminium")
    a = row[4] * 1e-6
    dl = a * length * dt
    o.add("Material", f"{row[7]}: expands {row[4]} µm per metre per °C")
    o.add("Change in length", f"{fmt(dl * 1000)} mm on {fmt(length * 1000)} mm for {fmt(dt)} °C")
    o.add("If it can't move", f"stress {show(row[1] * 1e9 * a * abs(dt), 'stress')} (strength {row[2]} MPa)")
    return o.done()


def weight(inp: Inputs) -> dict:
    o = Out()
    shape = inp.text(["shape", "form", "type"], "", ["tube", "pipe", "cylinder", "rod", "round", "sphere", "ball", "plate", "sheet", "box", "block", "cube"])
    key, row = mat(inp, "steel")
    dens = inp.num(["density"], "density", "density", text_ok=False) or row[0]
    count = inp.num(["count", "quantity", "pieces", "number"], "count", "pieces", default=1, hints=["pieces", "pcs", "x "], show="1")
    vol = inp.num(["volume"], "volume", "volume", text_ok=False)
    if not vol:
        d = inp.num(["diameter", "d", "od", "outer_diameter"], "length", "diameter", hints=["diameter", "ø", "dia"])
        length = inp.num(["length", "l", "height", "long"], "length", "length", hints=["long", "length", "high", "tall"])
        if d and ("sphere" in shape or "ball" in shape):
            vol = math.pi / 6 * d ** 3
        elif d and length:
            t = inp.num(["wall", "wall_thickness", "thickness", "t"], "length", "wall", text_ok=False)
            di = inp.num(["inner_diameter", "id", "inner"], "length", "inner diameter", text_ok=False)
            dd = di or ((d - 2 * t) if t else 0)
            vol = math.pi / 4 * (d * d - dd * dd) * length
        else:
            x = inp.num(["x", "width", "a", "w"], "length", "width", text_ok=False)
            y = inp.num(["y", "depth", "b"], "length", "depth", text_ok=False)
            z = inp.num(["z", "thickness", "height", "c", "h"], "length", "thickness", text_ok=False)
            if not (x and y and z):
                m = re.search(r"(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(mm|cm|m|in)?", inp.question.lower())
                if m:
                    u = m.group(4) or "mm"
                    x, y, z = (parse(f"{m.group(i)} {u}", "length") for i in (1, 2, 3))
            if x and y and z:
                vol = x * y * z
    if not vol:
        inp.missing.append("the size (e.g. 200 × 100 × 5 mm, or Ø20 × 300 mm)")
        return o.done()
    mass = vol * dens * count
    o.add("Volume", f"{fmt(vol * 1e6)} cm³" + (f" each × {int(count)}" if count > 1 else ""))
    o.add("Weight", f"{show(mass, 'mass')} ({row[7] if not inp.has('density') else 'density ' + fmt(dens) + ' kg/m³'})")
    if key in ("pla", "petg", "abs", "asa", "pc", "nylon", "tpu", "pla cf"):
        o.note("That's solid plastic; a printed part with 15–20 % infill weighs about 30–50 % of it (the slicer gives the real grams).")
    return o.done()


def drop(inp: Inputs) -> dict:
    o = Out()
    h = inp.num(["height", "drop_height", "h", "fall"], "length", "drop height", need=True, hints=["height", "drop", "fall", "from"])
    m = inp.num(["mass", "weight"], "mass", "mass", need=True, hints=["weigh", "mass", "kg", "g "])
    if not (h and m):
        return o.done()
    v = math.sqrt(2 * G * h)
    e = m * G * h
    o.add("Impact speed", show(v, "speed"))
    o.add("Energy", f"{fmt(e)} J")
    s = inp.num(["stop_distance", "crush", "padding", "stopping_distance"], "length", "stopping distance", text_ok=False)
    if s:
        o.add("Average impact force", f"{show(e / s, 'force')} if it stops in {fmt(s * 1000)} mm")
    else:
        o.note("The force depends on how far it squashes when it hits: 1 mm of give → force ≈ energy / 0.001 m. Padding (foam, TPU) helps a lot.")
    return o.done()


def motor(inp: Inputs) -> dict:
    o = Out()
    kv = inp.num(["kv", "kv_rating"], "number", "KV", hints=["kv"])
    if kv is None:
        m = re.search(r"(\d{2,5})\s*kv\b", inp.question, re.I)
        kv = float(m.group(1)) if m else None
    volt = inp.num(["voltage", "v", "battery_voltage"], "voltage", "voltage", hints=["v ", "volt", "battery"])
    cells = re.search(r"\b(\d)\s?s\b", inp.question, re.I)
    if not volt and cells:
        volt = int(cells.group(1)) * 3.7
        inp.assumed.append(f"{cells.group(1)}S LiPo = {fmt(volt)} V nominal")
    amps = inp.num(["current", "amps", "i"], "current", "current", hints=["amp", "a "])
    ratio = inp.num(["gear_ratio", "gearbox", "ratio", "reduction"], "number", "gear ratio", default=1.0, text_ok=False, show="1 (no gearbox)")
    if kv:
        o.add("Motor", f"{fmt(kv)} KV (Kt = {fmt(9.549 / kv)} N·m per amp)")
        if volt:
            o.add("No-load speed", f"{fmt(kv * volt)} rpm at {fmt(volt)} V" + (f" → {fmt(kv * volt / ratio)} rpm after the {fmt(ratio)}:1 gearbox" if ratio != 1 else ""))
        if amps:
            t = 9.549 / kv * amps
            o.add("Torque at that current", f"{show(t, 'torque')}" + (f" → {show(t * ratio * 0.9, 'torque')} after the gearbox" if ratio != 1 else ""))
            if volt:
                o.add("Electrical power", f"{fmt(volt * amps)} W in")
        return o.done()
    ts = inp.num(["stall_torque", "torque"], "torque", "stall torque", hints=["stall", "torque"])
    n0 = inp.num(["no_load_rpm", "rpm", "speed"], "rpm", "no-load rpm", hints=["rpm", "no load"])
    if ts and n0:
        o.add("Brushed DC motor", f"stall {show(ts, 'torque')}, no-load {fmt(n0)} rpm")
        o.add("Most power", f"{show(ts * n0 * 2 * math.pi / 60 / 4, 'power')} at {fmt(n0 / 2)} rpm and {show(ts / 2, 'torque')}")
        o.note("Torque falls in a straight line from stall (0 rpm) to zero at the no-load speed; run it near or above half speed.")
        return o.done()
    inp.missing.append("KV and voltage (brushless) — or stall torque and no-load rpm (brushed)")
    return o.done()


# ------------------------------------------------------------------ 3D printer calibration (Marlin / Klipper)
def esteps(inp: Inputs) -> dict:
    o = Out()
    cur = inp.num(["steps_per_mm", "esteps", "e_steps", "current", "old"], "number", "current steps/mm", hints=["steps", "e-steps", "esteps", "m92"])
    rd = inp.num(["rotation_distance", "rd"], "number", "rotation_distance", hints=["rotation"])
    asked = inp.num(["requested", "asked", "commanded", "target"], "length", "length asked for", default=0.1, text_ok=False, show="100 mm")
    got = inp.num(["actual", "measured", "extruded", "real"], "length", "length it really pushed", hints=["actual", "measured", "extruded", "only", "real"])
    mark = inp.num(["mark"], "length", "mark", text_ok=False)
    left = inp.num(["remaining", "left"], "length", "remaining", text_ok=False)
    if not got and mark and left is not None:
        got = mark - left
    if not got:
        inp.missing.append("how much filament really went in when you asked for 100 mm")
        return o.done()
    ratio = asked / got
    if cur:
        new = cur * ratio
        o.add("New steps/mm (Marlin)", f"{fmt(new, 5)} → send M92 E{fmt(new, 5)} then M500 to save")
    if rd:
        o.add("New rotation_distance (Klipper)", f"{fmt(rd / ratio, 5)} (in [extruder]; then RESTART)")
    if not (cur or rd):
        o.add("Correction", f"multiply steps/mm by {fmt(ratio, 4)} (or rotation_distance by {fmt(1 / ratio, 4)})")
    o.note("Measure with the hotend hot and extrude slowly (e.g. G1 E100 F100); repeat once to check.")
    return o.done()


def rotation_distance(inp: Inputs) -> dict:
    o = Out()
    steps = inp.num(["full_steps", "steps_per_rev", "motor_steps"], "count", "full steps per turn", default=200, text_ok=False, show="200 (1.8° motor)")
    if re.search(r"0\.9\s*°|0\.9 deg", inp.question):
        steps = 400
    micro = inp.num(["microsteps"], "count", "microsteps", default=16, hints=["microstep"], show="16")
    spm = inp.num(["steps_per_mm", "steps"], "number", "steps/mm", hints=["steps/mm", "steps per mm", "m92"])
    q = inp.question.lower()
    belt = q + " " + inp.text(["belt", "belt_type"])  # the belt picked by the model counts too ("steps per mm" + belt: gt2)
    pitch = next((v for k, v in BELTS.items() if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", belt)), None)
    tt = teeth_in_text(inp.question)
    teeth = inp.num(["teeth", "pulley_teeth", "teeth1", "motor_teeth"], "count", "pulley teeth", text_ok=False) or (tt[0] if tt else None)
    lead = inp.num(["lead"], "length", "lead", hints=["lead"])
    m = re.search(r"\bt\s?8\s?[x×]\s?(\d+)", q)
    if m and not lead:
        lead = float(m.group(1)) / 1000
    if pitch and teeth:
        rd = pitch * teeth
        o.add("rotation_distance", f"{fmt(rd)} ({fmt(pitch)} mm belt × {int(teeth)} teeth)")
    elif lead:
        rd = lead * 1000
        o.add("rotation_distance", f"{fmt(rd)} (lead screw lead)")
    elif spm:
        rd = steps * micro / spm
        o.add("rotation_distance", f"{fmt(rd, 5)} (from {fmt(spm)} steps/mm)")
    else:
        inp.missing.append("the belt + pulley teeth, the lead screw lead, or the current steps/mm")
        return o.done()
    o.add("steps/mm (Marlin)", f"{fmt(steps * micro / rd, 5)} at {int(steps)} steps × {int(micro)} microsteps")
    return o.done()


def flow_calibration(inp: Inputs) -> dict:
    o = Out()
    expected = inp.num(["expected", "wall", "target", "line_width"], "length", "expected wall thickness", hints=["expected", "should", "line width", "target"])
    measured = inp.num(["measured", "actual", "real"], "length", "measured wall thickness", need=True, hints=["measured", "actual", "is ", "got"])
    cur = inp.num(["flow", "flow_ratio", "current_flow", "extrusion_multiplier"], "number", "current flow", default=1.0, text_ok=False, show="100 %")
    if not expected:
        expected = 0.00084
        inp.assumed.append("expected wall = 2 lines × 0.42 mm = 0.84 mm")
    if not measured:
        return o.done()
    cur = cur / 100 if cur > 3 else cur
    new = cur * expected / measured
    o.add("New flow ratio", f"{fmt(new * 100, 4)} % (was {fmt(cur * 100)} %)")
    return o.done()


def volumetric(inp: Inputs) -> dict:
    o = Out()
    speed = inp.num(["speed", "print_speed"], "speed", "print speed", hints=["speed", "mm/s"])
    layer = inp.num(["layer", "layer_height"], "length", "layer height", default=0.0002, hints=["layer"], show="0.2 mm")
    width = inp.num(["width", "line_width"], "length", "line width", default=0.00042, hints=["width", "line"], show="0.42 mm")
    flow = inp.num(["flow", "max_flow", "volumetric"], "flow", "volumetric flow", text_ok=False)
    if speed:
        q = speed * layer * width
        o.add("Volumetric flow", f"{fmt(q * 1e9)} mm³/s at {fmt(speed * 1000)} mm/s, {fmt(layer * 1000)} × {fmt(width * 1000)} mm")
        o.note("Stock hotends manage roughly 10–15 mm³/s of PLA, high-flow ones 25+. Over the limit = thin, weak walls.")
    elif flow:
        o.add("Fastest speed", f"{fmt(flow / (layer * width) * 1000)} mm/s for {fmt(flow * 1e9)} mm³/s")
    else:
        inp.missing.append("the print speed (or the hotend's max flow)")
    return o.done()


# ------------------------------------------------------------------ unit conversion
def convert(inp: Inputs) -> dict:
    o = Out()
    val = inp._raw(["value", "from", "quantity", "amount"])
    to = inp.text(["to", "into", "target_unit", "unit"], "")
    q = inp.question
    if not val:
        m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*([^\d\s][^\s]*(?:\s?[a-z·./²³]+)?)\s+(?:to|in|into|în)\s+([^\s?]+(?:\s?[a-z·./²³]+)?)", q, re.I)
        if m:
            val, to = (f"{m.group(1)} {m.group(2)}", ""), to or m.group(3)
    if not val or not to:
        inp.missing.append("the value with its unit and the unit to convert to (e.g. 20 kg·cm to N·m)")
        return o.done()
    text = str(val[0]) if not val[1] else f"{val[0]} {val[1]}"
    mnum = re.match(r"\s*(-?\d+(?:[.,]\d+)?)\s*(.*)", text)
    if not mnum:
        inp.missing.append("a number to convert")
        return o.done()
    v, u = float(mnum.group(1).replace(",", ".")), mnum.group(2).strip()
    nu, nt = norm_unit(u), norm_unit(to)
    if nu in TEMP_UNITS and nt in TEMP_UNITS:
        c = parse(f"{v} {u}", "temp")
        out = {"c": c, "f": c * 9 / 5 + 32, "k": c + 273.15}[TEMP_UNITS[nt]]
        o.add("Result", f"{fmt(v)} {u} = {fmt(out, 5)} {to}")
        return o.done()
    for kind, table in UNITS.items():
        fu, ft = table.get(nu) or table.get(nu.rstrip("s")), table.get(nt) or table.get(nt.rstrip("s"))
        if fu and ft:
            o.add("Result", f"{fmt(v)} {u} = {fmt(v * fu / ft, 5)} {to}")
            return o.done()
    o.warn(f"I can't convert {u} to {to} (different kinds of quantity, or an unknown unit).")
    return o.done()


CALCS = {
    "bolt": (bolt, "Bolt / screw: torque, clamp force, strength, hole sizes",
             "bolt screw torque tighten tightening preload clamp m2 m3 m4 m5 m6 m8 m10 m12 grade 8.8 10.9 shear thread insert surub strange"),
    "power": (power, "Power ↔ torque ↔ speed", "power torque rpm watt kw hp horsepower speed putere cuplu"),
    "shaft": (shaft, "Shaft diameter for a torque", "shaft axle diameter torsion twist ax arbore"),
    "gears": (gears, "Gear pair: ratio, sizes, output speed / torque, tooth strength", "gear gears teeth tooth module ratio pinion spur angrenaj dinti"),
    "belt": (belt, "Timing / V belt: length, center distance, ratio, steps/mm", "belt gt2 gt3 htd pulley timing belt length curea fulie"),
    "leadscrew": (leadscrew, "Lead screw: thrust, torque, speed, steps/mm", "lead screw leadscrew t8 tr8 trapezoidal ball screw acme thrust surub trapezoidal"),
    "wheels": (wheels, "Wheeled robot / vehicle: motor torque, power, slope, grip", "wheel wheels robot car rover vehicle slope climb hill motor torque drive roti"),
    "arm": (arm, "Robot arm / lever: torque at each joint, servo / stepper choice", "arm servo lever joint payload robot arm hold sg90 mg996r torque kg cm brat"),
    "beam": (beam, "Beam / shelf: bending, stress, safety", "beam shelf bend deflection sag span load bar plank grinda raft"),
    "column": (column, "Column / leg: buckling load", "column buckling buckle leg strut post compression stalp"),
    "spring": (spring, "Compression spring: rate, force, stress", "spring rate coil coils wire compression arc"),
    "bearing": (bearing, "Ball bearing life and choice", "bearing 608 6201 6000 life hours l10 rulment"),
    "fit": (fit, "Fits: ISO 286 (H7/g6 …) and printed fits", "fit tolerance h7 g6 p6 k6 press fit clearance interference sliding toleranta ajustaj"),
    "thermal": (thermal, "Heat expansion", "expansion thermal expand heat temperature grows dilatare"),
    "weight": (weight, "Weight of a part from its size and material", "weight mass weigh heavy kg grams density greutate"),
    "drop": (drop, "Drop / impact: speed, energy, force", "drop fall impact falls dropped"),
    "motor": (motor, "Electric motor: KV, speed, torque, power", "motor kv brushless bldc dc motor stall rpm volt"),
    "esteps": (esteps, "Extruder e-steps / rotation_distance calibration", "esteps e-steps estep extruder calibrate calibration m92 underextrusion"),
    "rotation_distance": (rotation_distance, "Klipper rotation_distance ↔ steps/mm", "rotation_distance rotation distance klipper steps per mm steps/mm microsteps"),
    "flow_calibration": (flow_calibration, "Flow ratio from a measured wall", "flow ratio extrusion multiplier wall thickness flow calibration"),
    "volumetric_flow": (volumetric, "3D printer volumetric flow (mm³/s)", "volumetric flow mm3/s hotend max speed print speed"),
    "convert": (convert, "Unit conversion", "convert conversion unit units to in into transforma"),
}
