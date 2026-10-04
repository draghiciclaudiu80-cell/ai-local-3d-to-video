"""Fluids, hydraulics and pneumatics calculators: pipe flow and pressure loss, pipe size, pumps, hydraulic /
pneumatic cylinders, orifices and nozzles, tank draining, hydrostatic pressure and buoyancy, water hammer, air tanks.
Darcy–Weisbach with the Colebrook friction factor, typical fitting K values; water properties by temperature."""
import math
import re

from units import G, Inputs, Out, fmt, parse, pick_up, show

P_ATM = 101325.0
WATER_T = [0, 5, 10, 15, 20, 25, 30, 35, 40, 50, 60, 70, 80, 90, 100]
WATER_RHO = [999.8, 1000.0, 999.7, 999.1, 998.2, 997.0, 995.7, 994.0, 992.2, 988.0, 983.2, 977.8, 971.8, 965.3, 958.4]
WATER_MU = [1.792, 1.519, 1.307, 1.138, 1.002, 0.890, 0.798, 0.719, 0.653, 0.547, 0.467, 0.404, 0.355, 0.315, 0.282]  # mPa·s
OIL_VG = {15: 3.6, 22: 4.3, 32: 5.4, 46: 6.8, 68: 8.7, 100: 11.4, 150: 14.7, 220: 19.0}  # cSt at 40 °C -> at 100 °C (VI ~100)
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                "nine": 9, "ten": 10, "un": 1, "o": 1, "doua": 2, "două": 2, "trei": 3, "patru": 4, "cinci": 5}


def interp(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    for x0, x1, y0, y1 in zip(xs, xs[1:], ys, ys[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return ys[-1]


def fluid(inp: Inputs) -> dict:
    """{name, rho, mu (Pa·s), gas, R} at the temperature asked (20 °C if not said)."""
    words = ["sea water", "seawater", "salt water", "water", "apa", "air", "aer", "nitrogen", "co2", "oil", "ulei",
             "hydraulic", "diesel", "motorina", "petrol", "gasoline", "benzina", "glycol", "antifreeze", "ethanol",
             "alcohol", "milk"]
    name = inp.text(["fluid", "medium", "liquid", "gas"], "", words)
    t = inp.num(["temperature", "temp", "fluid_temperature"], "temp", "temperature", default=20.0,
                hints=["°c", "temperature", "degrees", "temp"], show="20 °C")
    if not name:
        name = "water"
        inp.assumed.append("fluid = water")
    if re.search(r"\bair|aer|nitrogen|co2|gas|pneumat", name):
        r_gas, mu0, label = (296.8, 1.76e-5, "nitrogen") if "nitro" in name else (188.9, 1.47e-5, "CO₂") if "co2" in name else (287.05, None, "air")
        p_abs = inp.num(["absolute_pressure", "pressure_abs", "line_pressure"], "pressure", "line pressure (absolute)", default=P_ATM,
                        text_ok=False, show="1 atm")
        tk = t + 273.15
        mu = mu0 or 1.716e-5 * (tk / 273.15) ** 1.5 * (273.15 + 110.4) / (tk + 110.4)
        return {"name": label, "rho": p_abs / (r_gas * tk), "mu": mu, "gas": True, "R": r_gas, "t": t}
    if re.search(r"oil|ulei|hydraulic", name):
        m = re.search(r"\b(?:vg|iso)\s?(\d{2,3})\b|\b(\d{2,3})\s?cst", inp.question.lower() + " " + name)
        vg = int(m.group(1) or m.group(2)) if m else 46
        if not m:
            inp.assumed.append("oil = ISO VG 46 hydraulic oil")
        n40, n100 = vg, OIL_VG.get(vg, 6.8 * (vg / 46) ** 0.55)
        a1, a2 = math.log10(math.log10(n40 + 0.7)), math.log10(math.log10(n100 + 0.7))
        b = (a1 - a2) / (math.log10(373.15) - math.log10(313.15))
        a = a1 + b * math.log10(313.15)
        nu = 10 ** (10 ** (a - b * math.log10(t + 273.15))) - 0.7  # Walther / ASTM D341
        rho = 870 * (1 - 0.00065 * (t - 15))
        return {"name": f"hydraulic oil ISO VG {vg} ({fmt(nu)} cSt at {fmt(t)} °C)", "rho": rho, "mu": nu * 1e-6 * rho, "gas": False, "t": t}
    fixed = [("diesel|motorina", "diesel", 830, 3.3e-3), ("petrol|gasoline|benzina", "petrol", 740, 5e-4),
             ("glycol|antifreeze", "50 % glycol", 1070, 4e-3), ("ethanol|alcohol", "ethanol", 789, 1.2e-3),
             ("milk", "milk", 1030, 2e-3)]
    for pat, label, rho, mu in fixed:
        if re.search(pat, name):
            return {"name": label, "rho": rho, "mu": mu, "gas": False, "t": t}
    rho, mu = interp(t, WATER_T, WATER_RHO), interp(t, WATER_T, WATER_MU) * 1e-3
    if re.search(r"sea|salt", name):
        return {"name": f"sea water at {fmt(t)} °C", "rho": rho * 1.027, "mu": mu * 1.07, "gas": False, "t": t}
    dens = inp.num(["density", "rho"], "density", "density", text_ok=False)
    visc = inp.num(["viscosity", "dynamic_viscosity", "mu"], "viscosity", "viscosity", text_ok=False)
    return {"name": f"water at {fmt(t)} °C" if not (dens or visc) else "the fluid you gave", "rho": dens or rho,
            "mu": visc or mu, "gas": False, "t": t}


ROUGH = [("galvan", 0.15), ("cast iron", 0.26), ("fonta", 0.26), ("concrete", 1.0), ("beton", 1.0), ("stainless", 0.015),
         ("inox", 0.015), ("steel", 0.045), ("otel", 0.045), ("copper", 0.0015), ("cupru", 0.0015), ("brass", 0.0015),
         ("hdpe", 0.007), ("pex", 0.007), ("pe ", 0.007), ("pp", 0.007), ("pvc", 0.0015), ("plastic", 0.0015),
         ("silicone", 0.0015), ("hose", 0.01), ("furtun", 0.01), ("rubber", 0.01), ("alumin", 0.0015), ("glass", 0.0015)]
K_FIT = [("long radius elbow", 0.3), ("long-radius elbow", 0.3), ("45", 0.4), ("elbow", 0.9), ("cot", 0.9), ("bend", 0.4),
         ("tee branch", 1.8), ("branch", 1.8), ("tee", 0.6), ("ball valve", 0.05), ("gate valve", 0.2), ("globe valve", 10.0),
         ("butterfly", 0.6), ("check valve", 2.0), ("non-return", 2.0), ("non return", 2.0), ("strainer", 2.0),
         ("filter", 2.0), ("robinet", 0.5), ("valve", 0.5), ("entrance", 0.5), ("exit", 1.0), ("coupling", 0.08),
         ("union", 0.08), ("reducer", 0.5)]


def roughness(inp: Inputs):
    s = inp.text(["material", "pipe_material", "pipe", "tube", "hose_type"], "") + " " + inp.question.lower() + " "
    eps = inp.num(["roughness", "epsilon", "absolute_roughness"], "length", "roughness", text_ok=False)
    if eps:
        return eps, "roughness given"
    for w, e in ROUGH:
        if re.search(rf"(?<![a-z]){re.escape(w.strip())}(?![a-z])", s):
            return e / 1000, w.strip()
    inp.assumed.append("smooth plastic pipe (roughness 0.0015 mm)")
    return 0.0015 / 1000, "plastic"


def fittings(inp: Inputs):
    k = inp.num(["k_total", "k_sum", "minor_loss", "minor_losses", "k"], "number", "fitting K", text_ok=False)
    if k is not None:
        return k, f"K = {fmt(k)} (given)"
    raw = inp._raw(["fittings", "fitting", "bends"])
    items = []
    if raw and isinstance(raw[0], dict):
        for name, cnt in raw[0].items():
            kk = next((v for w, v in K_FIT if w in str(name).lower()), 0.5)
            items.append((str(name), float(cnt or 1), kk))
    else:
        s = (str(raw[0]) if raw else "") + " " + inp.question.lower()
        used = set()
        for w, kk in K_FIT:
            for m in re.finditer(rf"(\d+|{'|'.join(NUMBER_WORDS)})?\s*(?:x\s*)?{re.escape(w)}s?\b", s):
                if any(m.start() < e and m.end() > b for b, e in used):
                    continue
                used.add((m.start(), m.end()))
                c = m.group(1)
                n = float(c) if c and c.isdigit() else NUMBER_WORDS.get(c or "", 1)
                items.append((w, n, kk))
    total = sum(n * kk for _, n, kk in items)
    return total, (", ".join(f"{fmt(n)} × {w} (K {kk})" for w, n, kk in items) if items else "no fittings")


def friction(re_n: float, rel: float):
    if re_n < 2300:
        return 64 / re_n, "laminar"
    f = 0.25 / math.log10(rel / 3.7 + 5.74 / re_n ** 0.9) ** 2  # Swamee–Jain, then Colebrook
    for _ in range(30):
        f = (-2 * math.log10(rel / 3.7 + 2.51 / (re_n * math.sqrt(f)))) ** -2
    return f, ("turbulent" if re_n > 4000 else "between laminar and turbulent (rough numbers)")


def _diameter(inp: Inputs, label="inner diameter", need=True):
    d = inp.num(["diameter", "inner_diameter", "id", "pipe_diameter", "bore", "hose_diameter", "d", "pipe_id"], "length",
                label, need=need, hints=["diameter", "pipe", "hose", "tube", "bore", "id", "ø", "inch", "teava", "furtun"])
    if not d:
        m = re.search(r"\b(\d+(?:[.,]\d+)?|\d+/\d+)\s*(?:\"|inch|in\b|”)", inp.question)
        if m:
            d = parse(m.group(1) + " in", "length")
            if d and label in inp.missing:
                inp.missing.remove(label)
    return d


def pipe_flow(inp: Inputs) -> dict:
    o = Out()
    fl = fluid(inp)
    d = _diameter(inp)
    q = inp.num(["flow", "flow_rate", "q", "discharge", "debit"], "flow", "flow rate", hints=["flow", "l/min", "lpm", "m3/h", "gpm", "debit"])
    v = None if q else inp.num(["velocity", "speed"], "speed", "velocity", hints=["velocity", "speed", "m/s"])
    if not d:
        return o.done()
    if not (q or v):
        inp.missing.append("the flow rate (e.g. 20 l/min)")
        return o.done()
    area = math.pi * d * d / 4
    v = v or q / area
    q = q or v * area
    length = inp.num(["length", "pipe_length", "run", "l"], "length", "pipe length", hints=["long", "length", "run", "meter", "metre", " m "])
    dz = inp.num(["elevation", "height", "rise", "lift", "static_head", "dz", "height_difference"], "length", "height difference",
                 default=0.0, hints=["up", "rise", "higher", "lift", "height", "elevation", "floor"], show="0 (level)")
    eps, ename = roughness(inp)
    ksum, kdesc = fittings(inp)
    re_n = fl["rho"] * v * d / fl["mu"]
    f, regime = friction(re_n, eps / d)
    dyn = fl["rho"] * v * v / 2
    per_m = f / d * dyn
    o.add("Flow", f"{show(q, 'flow')} of {fl['name']} in a {fmt(d * 1000)} mm bore ({ename})")
    o.add("Velocity", f"{fmt(v)} m/s")
    o.add("Reynolds number", f"{fmt(re_n, 4)} → {regime}; friction factor {fmt(f, 4)}")
    o.add("Friction loss", f"{show(per_m * 100, 'pressure')} per 100 m")
    total = dz * fl["rho"] * G + ksum * dyn
    if length:
        total += per_m * length
        o.add(f"Loss in {fmt(length)} m of pipe", show(per_m * length, "pressure"))
    if ksum:
        o.add("Fittings", f"{show(ksum * dyn, 'pressure')} ({kdesc})")
    if dz:
        o.add("Lifting the fluid", f"{show(dz * fl['rho'] * G, 'pressure')} for {fmt(dz)} m up")
    head = total / (fl["rho"] * G)
    o.add("Total pressure needed", f"{show(total, 'pressure')} = {fmt(head)} m of {('fluid' if fl['gas'] else 'head')}" + ("" if length else " (+ the pipe length: give it)"))
    eta = inp.num(["efficiency", "pump_efficiency"], "number", "pump efficiency", default=0.6, text_ok=False, show="60 %")
    eta = eta / 100 if eta > 1 else eta
    o.add("Pump power", f"{show(total * q, 'power')} into the fluid → about {show(total * q / eta, 'power')} at the pump shaft")
    if not fl["gas"]:
        if v > 3:
            o.warn(f"{fmt(v)} m/s is fast for a liquid: noisy, wears fittings, water hammer — 0.5–2.5 m/s is normal; use a bigger pipe.")
        elif v < 0.3:
            o.note("Very slow flow: dirt can settle; fine for drains / gravity.")
    elif total > 0.1 * P_ATM:
        o.note("For gases with a big pressure drop the gas expands along the pipe — treat this as a rough figure.")
    return o.done()


STEEL_DN = [(6, 7.0, '1/8"'), (8, 9.2, '1/4"'), (10, 12.5, '3/8"'), (15, 15.8, '1/2"'), (20, 20.9, '3/4"'), (25, 26.6, '1"'),
            (32, 35.1, '1 1/4"'), (40, 40.9, '1 1/2"'), (50, 52.5, '2"'), (65, 62.7, '2 1/2"'), (80, 77.9, '3"'),
            (100, 102.3, '4"'), (125, 128.2, '5"'), (150, 154.1, '6"'), (200, 202.7, '8"')]  # schedule 40 bore
HOSE_DASH = [("-3", 4.8), ("-4", 6.3), ("-5", 7.9), ("-6", 9.5), ("-8", 12.7), ("-10", 15.9), ("-12", 19.0), ("-16", 25.4),
             ("-20", 31.8), ("-24", 38.1), ("-32", 50.8)]  # hydraulic hose inner diameter mm (SAE)
PLASTIC = [(16, 12.4), (20, 16.0), (25, 20.4), (32, 26.2), (40, 32.6), (50, 40.8), (63, 51.4), (75, 61.4), (90, 73.6),
           (110, 90.0), (125, 102.2), (160, 130.8)]  # PE / PP-R pressure pipe OD -> bore (PN10-ish)


def pipe_size(inp: Inputs) -> dict:
    o = Out()
    q = inp.num(["flow", "flow_rate", "q", "debit"], "flow", "flow rate", need=True, hints=["flow", "l/min", "lpm", "m3/h", "gpm"])
    if not q:
        return o.done()
    fl = fluid(inp)
    use = inp.text(["line", "use", "type", "purpose"], "", ["suction", "return", "pressure", "drain", "supply", "garden"])
    hydraulic = "oil" in fl["name"] or "hydraulic" in inp.question.lower()
    vmax = inp.num(["max_velocity", "velocity", "max_speed"], "speed", "max velocity", text_ok=False)
    if not vmax:
        vmax = (1.0 if "suction" in use else 2.5 if "return" in use else 4.5) if hydraulic else \
            (8.0 if fl["gas"] else 1.0 if "suction" in use else 2.0)
        inp.assumed.append(f"max velocity {fmt(vmax)} m/s ({'hydraulic ' if hydraulic else ''}{use or ('compressed air' if fl['gas'] else 'pressure line')})")
    dmin = math.sqrt(4 * q / (math.pi * vmax))
    o.add("Smallest bore", f"{fmt(dmin * 1000)} mm for {show(q, 'flow')} at ≤ {fmt(vmax)} m/s")
    if hydraulic:
        pick = next(((n, i) for n, i in HOSE_DASH if i >= dmin * 1000 - 0.05), None)
        if pick:
            o.add("Hydraulic hose", f"{pick[0]} ({pick[1]} mm bore)")
            bore = pick[1] / 1000
        else:
            bore = dmin
    else:
        st = next(((dn, i, inch) for dn, i, inch in STEEL_DN if i >= dmin * 1000 - 0.05), None)
        pl = next(((od, i) for od, i in PLASTIC if i >= dmin * 1000 - 0.05), None)
        if st:
            o.add("Steel pipe", f"DN{st[0]} ({st[2]}, bore {st[1]} mm)")
        if pl:
            o.add("Plastic pipe (PE / PP-R)", f"Ø{pl[0]} mm outside (bore ≈ {pl[1]} mm)")
        bore = (st[1] / 1000) if st else (pl[1] / 1000 if pl else dmin)
    v = q / (math.pi * bore * bore / 4)
    re_n = fl["rho"] * v * bore / fl["mu"]
    eps, _ = roughness(inp)
    f, _ = friction(re_n, eps / bore)
    o.add("In that size", f"{fmt(v)} m/s, loss {show(f / bore * fl['rho'] * v * v / 2 * 100, 'pressure')} per 100 m")
    return o.done()


def pump(inp: Inputs) -> dict:
    o = Out()
    fl = fluid(inp)
    q = inp.num(["flow", "flow_rate", "q", "debit"], "flow", "flow rate", hints=["flow", "l/min", "lpm", "m3/h", "gpm"])
    h = inp.num(["head", "height", "lift", "h"], "length", "head (height)", hints=["head", "lift", "high", "up", "height", "metri"])
    p = inp.num(["pressure", "dp", "pressure_rise"], "pressure", "pressure", hints=["bar", "psi", "pressure"])
    if p and not h:
        h = p / (fl["rho"] * G)
    pw = inp.num(["power", "motor_power"], "power", "power", hints=["power", "w ", "kw", "hp"])
    eta = inp.num(["efficiency", "pump_efficiency"], "number", "pump efficiency", default=0.6, text_ok=False, show="60 %")
    eta = eta / 100 if eta > 1 else eta
    if not h:
        inp.missing.append("the head (how high it pumps, in m) or the pressure")
        return o.done()
    if q:
        ph = fl["rho"] * G * q * h
        o.add("Power into the water", show(ph, "power"))
        o.add("Pump shaft power", f"{show(ph / eta, 'power')} (pump efficiency {int(eta * 100)} %)")
        o.add("Electrical power", f"{show(ph / eta / 0.85, 'power')} (motor 85 %)")
        volt = inp.num(["voltage"], "voltage", "voltage", hints=["v ", "volt"])
        if volt:
            o.add("Current", f"{fmt(ph / eta / 0.85 / volt)} A at {fmt(volt)} V")
    elif pw:
        q = pw * eta / (fl["rho"] * G * h)
        o.add("Flow it can give", show(q, "flow"))
    else:
        inp.missing.append("the flow rate (or the pump power)")
        return o.done()
    o.add("Head", f"{fmt(h)} m = {show(fl['rho'] * G * h, 'pressure')}")
    n1 = inp.num(["rpm", "rpm1"], "rpm", "rpm", text_ok=False)
    n2 = inp.num(["new_rpm", "rpm2"], "rpm", "new rpm", text_ok=False)
    if n1 and n2:
        r = n2 / n1
        o.add(f"At {fmt(n2)} rpm (affinity laws)", f"flow × {fmt(r)}, head × {fmt(r * r)}, power × {fmt(r ** 3)}")
    o.note("Pick a pump whose curve gives this flow at this head; add the pipe losses (pipe_flow) to the height.")
    return o.done()


BORES_PNEU = [8, 10, 12, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200]
BORES_HYD = [25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250]


def cylinder(inp: Inputs) -> dict:
    o = Out()
    low = (inp.text(["medium", "type", "fluid"], "") + " " + inp.question).lower()
    p = inp.num(["pressure", "supply_pressure", "p"], "pressure", "pressure", hints=["bar", "psi", "pressure", "mpa"])
    air = bool(re.search(r"\bair|pneumat|aer|compressor", low)) or (p is not None and p <= 12e5 and "hydraul" not in low)
    if p is None:
        p = 6e5 if air else 100e5
        inp.assumed.append(f"pressure {fmt(p / 1e5)} bar")
    bore = inp.num(["bore", "piston_diameter", "diameter", "cylinder_diameter", "d"], "length", "bore", hints=["bore", "piston", "diameter", "cylinder", "ø"])
    rod = inp.num(["rod", "rod_diameter", "piston_rod"], "length", "rod diameter", hints=["rod"])
    force = inp.num(["force", "load", "push", "needed_force"], "force", "force needed", hints=["force", "push", "lift", "load", "kg", "ton"])
    eta = inp.num(["efficiency"], "number", "efficiency", default=0.85 if air else 0.9, text_ok=False, show="85 %" if air else "90 %")
    eta = eta / 100 if eta > 1 else eta
    if not bore and force:
        dmin = math.sqrt(4 * force / (math.pi * p * eta))
        std = pick_up(dmin * 1000, BORES_PNEU if air else BORES_HYD)
        o.add("Bore needed", f"{fmt(dmin * 1000)} mm → standard Ø{std} mm" if std else f"{fmt(dmin * 1000)} mm")
        bore = (std or dmin * 1000) / 1000
    if not bore:
        inp.missing.append("the bore (piston diameter) or the force needed")
        return o.done()
    if not rod:
        rod = bore * (0.4 if air else 0.5)
        inp.assumed.append(f"rod Ø{fmt(rod * 1000)} mm")
    a1 = math.pi * bore * bore / 4
    a2 = a1 - math.pi * rod * rod / 4
    o.add("Cylinder", f"{'pneumatic' if air else 'hydraulic'} Ø{fmt(bore * 1000)} / rod Ø{fmt(rod * 1000)} mm at {fmt(p / 1e5)} bar")
    o.add("Push force (extend)", show(p * a1 * eta, "force"))
    o.add("Pull force (retract)", show(p * a2 * eta, "force"))
    if force:
        o.verdict = f"{'OK' if p * a1 * eta >= force else 'TOO WEAK'}: pushes {show(p * a1 * eta, 'force')} vs needed {show(force, 'force')}."
    q = inp.num(["flow", "flow_rate", "pump_flow"], "flow", "flow", hints=["flow", "l/min", "lpm"])
    stroke = inp.num(["stroke", "travel", "length"], "length", "stroke", hints=["stroke", "travel", "long"])
    if q and not air:
        o.add("Speed", f"extend {fmt(q / a1 * 1000)} mm/s, retract {fmt(q / a2 * 1000)} mm/s")
        if stroke:
            o.add("Time per stroke", f"out {fmt(stroke / (q / a1))} s, back {fmt(stroke / (q / a2))} s")
        o.add("Hydraulic power", show(p * q, "power"))
    if stroke:
        o.add("Volume per stroke", f"out {fmt(a1 * stroke * 1e6)} cm³, back {fmt(a2 * stroke * 1e6)} cm³")
        if air:
            free = (a1 + a2) * stroke * (p + P_ATM) / P_ATM
            o.add("Air used per cycle", f"{fmt(free * 1000)} l of free air (out and back)")
            cpm = inp.num(["cycles", "cycles_per_minute", "rate"], "number", "cycles per minute", text_ok=False)
            if cpm:
                o.add("Air consumption", f"{fmt(free * 1000 * cpm)} l/min at {fmt(cpm)} cycles/min")
        e, i = 210e9, math.pi * rod ** 4 / 64
        pcr = math.pi ** 2 * e * i / (2 * stroke) ** 2
        if p * a1 * eta > pcr / 3.5:
            o.warn(f"Long stroke for that rod: it could buckle (safe push ≈ {show(pcr / 3.5, 'force')}) — thicker rod or guide it.")
    return o.done()


def orifice(inp: Inputs) -> dict:
    o = Out()
    fl = fluid(inp)
    d = inp.num(["diameter", "hole", "orifice", "nozzle", "d"], "length", "hole diameter", need=True, hints=["hole", "orifice", "nozzle", "diameter", "jet"])
    dp = inp.num(["pressure", "pressure_drop", "dp"], "pressure", "pressure (drop)", hints=["bar", "psi", "pressure"])
    q = inp.num(["flow", "flow_rate"], "flow", "flow", hints=["flow", "l/min"])
    if not d:
        return o.done()
    nozzle = bool(re.search(r"nozzle|duza|rounded", inp.question.lower()))
    cd = inp.num(["cd", "discharge_coefficient"], "number", "discharge coefficient", default=0.97 if nozzle else 0.62,
                 text_ok=False, show="0.97 (smooth nozzle)" if nozzle else "0.62 (sharp-edged hole)")
    a = math.pi * d * d / 4
    if fl["gas"] and dp:
        p1 = dp + P_ATM
        tk = fl["t"] + 273.15
        g_ = 1.4
        if P_ATM / p1 < 0.528:
            mdot = cd * a * p1 * math.sqrt(g_ / (fl["R"] * tk)) * (2 / (g_ + 1)) ** ((g_ + 1) / (2 * (g_ - 1)))
            how = "choked (sonic) flow"
        else:
            pr = P_ATM / p1
            mdot = cd * a * p1 * math.sqrt(2 * g_ / ((g_ - 1) * fl["R"] * tk) * (pr ** (2 / g_) - pr ** ((g_ + 1) / g_)))
            how = "subsonic flow"
        free = mdot / (P_ATM / (fl["R"] * 293.15))
        o.add(f"Air through Ø{fmt(d * 1000)} mm at {fmt(dp / 1e5)} bar", f"{fmt(free * 60000)} l/min of free air ({how})")
        return o.done()
    if dp:
        q = cd * a * math.sqrt(2 * dp / fl["rho"])
        o.add("Flow", show(q, "flow"))
        o.add("Jet speed", f"{fmt(math.sqrt(2 * dp / fl['rho']) * 0.98)} m/s")
    elif q:
        dp = fl["rho"] / 2 * (q / (cd * a)) ** 2
        o.add("Pressure drop", show(dp, "pressure"))
    else:
        inp.missing.append("the pressure (or the flow)")
    return o.done()


def tank_drain(inp: Inputs) -> dict:
    o = Out()
    dt = inp.num(["tank_diameter", "diameter_tank", "tank"], "length", "tank diameter",
                 hints=["tank", "barrel", "butoi", "rezervor", "diameter", "dia", "across", "drum"], lone=False)
    area = inp.num(["tank_area", "area"], "area", "tank area", text_ok=False)
    w = inp.num(["width"], "length", "width", text_ok=False)
    ln = inp.num(["length"], "length", "length", text_ok=False)
    dh = inp.num(["hole", "hole_diameter", "outlet", "outlet_diameter", "tap"], "length", "outlet hole diameter", need=True, hints=["hole", "outlet", "tap", "drain", "pipe"])
    h1 = inp.num(["height", "level", "water_height", "start_height", "depth"], "length", "water height", need=True, hints=["high", "height", "level", "deep", "full"])
    h2 = inp.num(["end_height", "final_height"], "length", "end height", default=0.0, text_ok=False, show="empty")
    cd = inp.num(["cd"], "number", "discharge coefficient", default=0.6, text_ok=False, show="0.6")
    at = area or (math.pi * dt * dt / 4 if dt else (w * ln if w and ln else None))
    if not at:
        inp.missing.append("the tank size (diameter, or width × length)")
    if not (at and dh and h1):
        return o.done()
    ah = math.pi * dh * dh / 4
    t = at / (cd * ah) * math.sqrt(2 / G) * (math.sqrt(h1) - math.sqrt(max(h2, 0)))
    o.add("Time to drain", f"{show(t, 'time')} (from {fmt(h1)} m to {fmt(h2)} m)")
    o.add("Starting outflow", show(cd * ah * math.sqrt(2 * G * h1), "flow"))
    o.add("Water let out", f"{fmt(at * (h1 - h2) * 1000)} l")
    q_in = inp.num(["inflow", "fill_flow", "fill_rate"], "flow", "fill flow", text_ok=False)
    if q_in:
        o.add("Time to fill it at that inflow", show(at * (h1 - h2) / q_in, "time"))
    return o.done()


def hydrostatic(inp: Inputs) -> dict:
    o = Out()
    fl = fluid(inp)
    depth = inp.num(["depth", "height", "head", "h"], "length", "depth", hints=["deep", "depth", "under", "high", "head", "column"])
    vol = inp.num(["volume", "displacement"], "volume", "volume", hints=["volume", "litre", "liter"])
    mass = inp.num(["mass", "weight"], "mass", "mass", hints=["weigh", "mass", "kg"])
    if depth:
        p = fl["rho"] * G * depth
        o.add(f"Pressure at {fmt(depth)} m", f"{show(p, 'pressure')} (gauge; absolute {fmt((p + P_ATM) / 1e5)} bar)")
        w = inp.num(["width", "wall_width"], "length", "wall width", text_ok=False)
        if w:
            o.add("Force on a vertical wall", f"{show(fl['rho'] * G * w * depth * depth / 2, 'force')} (acts at 1/3 of the height from the bottom)")
        a = inp.num(["area"], "area", "area", text_ok=False)
        if a:
            o.add("Force on that area", show(p * a, "force"))
    if vol:
        fb = fl["rho"] * G * vol
        o.add("Buoyancy (fully under)", f"{show(fb, 'force')} = lifts {fmt(fl['rho'] * vol)} kg")
        if mass:
            o.verdict = (f"It floats, {fmt(mass / (fl['rho'] * vol) * 100)} % under the surface." if mass < fl["rho"] * vol
                         else f"It sinks: {fmt(mass)} kg is more than the {fmt(fl['rho'] * vol)} kg of {fl['name']} it pushes away.")
    if not (depth or vol):
        inp.missing.append("the depth (for pressure) or the volume (for buoyancy)")
    return o.done()


WAVE = [("stainless", 1300), ("steel", 1300), ("otel", 1300), ("ductile", 1200), ("cast iron", 1200), ("copper", 1200),
        ("concrete", 1100), ("pvc", 400), ("hdpe", 280), ("pex", 300), ("pe", 280), ("pp", 350), ("hose", 100), ("rubber", 100)]


def water_hammer(inp: Inputs) -> dict:
    o = Out()
    fl = fluid(inp)
    v = inp.num(["velocity", "speed"], "speed", "flow velocity", hints=["velocity", "m/s", "speed"])
    if not v:
        q = inp.num(["flow", "flow_rate"], "flow", "flow", hints=["flow", "l/min"])
        d = _diameter(inp, need=False)
        if q and d:
            v = q / (math.pi * d * d / 4)
    if not v:
        inp.missing.append("the flow velocity (or flow + pipe diameter)")
        return o.done()
    s = (inp.text(["material", "pipe_material", "pipe"], "") + " " + inp.question).lower()
    a = next((c for w, c in WAVE if w in s), None)
    if a is None:
        a = 1200
        inp.assumed.append("metal pipe (pressure wave 1200 m/s)")
    length = inp.num(["length", "pipe_length"], "length", "pipe length", hints=["long", "length", "m "])
    tc = inp.num(["closing_time", "close_time", "valve_time"], "time", "valve closing time", hints=["close", "closing", "shut"])
    dp = fl["rho"] * a * v
    o.add("Pressure spike if the valve shuts at once", f"{show(dp, 'pressure')} (Joukowsky, wave {a} m/s)")
    if length:
        tcrit = 2 * length / a
        o.add("A 'slow' close must take longer than", f"{fmt(tcrit)} s")
        if tc and tc > tcrit:
            o.add(f"With a {fmt(tc)} s close", f"≈ {show(2 * fl['rho'] * length * v / tc, 'pressure')}")
    o.note("Close valves slowly, keep velocity low, or add an air chamber / arrestor near quick-closing valves.")
    return o.done()


def air_tank(inp: Inputs) -> dict:
    o = Out()
    vol = inp.num(["volume", "tank_volume", "tank", "size"], "volume", "tank volume", need=True, hints=["tank", "litre", "liter", " l ", "cylinder", "bottle"])
    p = inp.num(["pressure", "tank_pressure", "p"], "pressure", "tank pressure", need=True,
                hints=["tank", "pressure", "charged", "filled", "at", "receiver"])
    if not (vol and p):
        return o.done()
    pa = p + P_ATM
    free = vol * pa / P_ATM
    o.add("Free air stored", f"{fmt(free * 1000)} l (at atmospheric pressure)")
    g_ = 1.4
    burst = pa * vol / (g_ - 1) * (1 - (P_ATM / pa) ** ((g_ - 1) / g_))
    o.add("Energy if it bursts", f"{fmt(burst / 1000)} kJ — treat high-pressure tanks with respect")
    use = inp.num(["consumption", "tool_flow", "air_use"], "flow", "air use", hints=["uses", "use", "tool", "consumption", "draws"])
    p_min = inp.num(["min_pressure", "cut_in", "down_to"], "pressure", "lowest useful pressure",
                    hints=["down to", "to", "min", "until", "cut"], lone=False)
    if use:
        usable = vol * (p - (p_min or 0)) / P_ATM
        o.add("Run time", f"{show(usable / use, 'time')} at {fmt(use * 60000)} l/min (down to {fmt((p_min or 0) / 1e5)} bar)")
    comp = inp.num(["compressor", "compressor_flow", "fad"], "flow", "compressor delivery", text_ok=False)
    if comp:
        o.add("Fill time from empty", show(vol * p / P_ATM / comp, "time"))
    o.note("Ideal-gas numbers: real air above ~200 bar holds ~10 % less than this.")
    return o.done()


CALCS = {
    "pipe_flow": (pipe_flow, "Pipe flow: velocity, pressure loss, pump power", "pipe flow pressure drop loss head loss reynolds friction hose tube velocity pierdere presiune teava debit"),
    "pipe_size": (pipe_size, "Pipe / hose size for a flow", "pipe size diameter hose size what pipe dn bore dimension teava"),
    "pump": (pump, "Pump power / flow / head", "pump pompa head lift power affinity"),
    "cylinder": (cylinder, "Hydraulic / pneumatic cylinder: force, speed, air use", "cylinder hydraulic pneumatic ram piston bore rod force cilindru piston"),
    "orifice": (orifice, "Flow through a hole / nozzle / jet", "orifice nozzle jet hole leak spray flow through duza"),
    "tank_drain": (tank_drain, "Tank draining / filling time", "tank drain empty barrel outlet torricelli fill time rezervor"),
    "hydrostatic": (hydrostatic, "Pressure at depth, force on walls, buoyancy", "depth pressure under water hydrostatic buoyancy float sink submerged wall force"),
    "water_hammer": (water_hammer, "Water hammer pressure spike", "water hammer valve shut slam surge spike lovitura de berbec"),
    "air_tank": (air_tank, "Air tank / compressor: stored air, run time, fill time", "air tank compressor receiver compressed air run time scuba bottle cylinder pressure butelie"),
}
