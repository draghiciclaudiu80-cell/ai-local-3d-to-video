"""Electronics and PCB calculators (what KiCad's PCB Calculator has, and the everyday ones): Ohm's law, voltage
dividers, LED resistors, resistor colour codes, E-series values, RC / LC, 555 timers, regulators (LM317, fixed, buck),
batteries, wire gauge, PCB track width (IPC-2221), vias, electrical spacing (IPC-2221B), track impedance (microstrip,
stripline, coplanar), attenuators, fusing current, capacitors, op-amp gain and dB."""
import math
import re

from units import Inputs, Out, fmt, parse

RHO_CU = 1.72e-8  # Ω·m at 20 °C
ALPHA_CU = 0.00393
OZ = 34.79e-6  # m of copper per oz/ft²
E = {
    "E6": [1.0, 1.5, 2.2, 3.3, 4.7, 6.8],
    "E12": [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2],
    "E24": [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1],
    "E96": [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54,
            1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43,
            2.49, 2.55, 2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83,
            3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.90, 6.04,
            6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76],
}


def ohms(r: float) -> str:
    if r is None:
        return "—"
    if r >= 1e6:
        return f"{fmt(r / 1e6)} MΩ"
    if r >= 1e3:
        return f"{fmt(r / 1e3)} kΩ"
    return f"{fmt(r)} Ω"


def unit(v: float, u: str) -> str:
    """1.5e-6 F -> 1.5 µF."""
    if v is None:
        return "—"
    for f, p in ((1e9, "G"), (1e6, "M"), (1e3, "k"), (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")):
        if abs(v) >= f * 0.9999:
            return f"{fmt(v / f)} {p}{u}"
    return f"{fmt(v)} {u}"


def nearest(value: float, series: str = "E24", up: bool = False, down: bool = False):
    if not value or value <= 0:
        return None
    dec = 10 ** math.floor(math.log10(value))
    cands = [b * dec * k for b in E[series] for k in (0.1, 1, 10)]
    if up:
        return min((c for c in cands if c >= value * 0.9999), default=None)
    if down:
        return max((c for c in cands if c <= value * 1.0001), default=None)
    return min(cands, key=lambda c: abs(math.log(c / value)))


def ohm_law(inp: Inputs) -> dict:
    o = Out()
    v = inp.num(["voltage", "v", "u"], "voltage", "voltage", hints=["v ", "volt"])
    i = inp.num(["current", "i", "amps"], "current", "current", hints=["a ", "amp", "ma"])
    r = inp.num(["resistance", "r", "resistor"], "resistance", "resistance", hints=["ohm", "Ω", "k "])
    p = inp.num(["power", "p", "watts"], "power", "power", hints=["w ", "watt"])
    known = sum(x is not None for x in (v, i, r, p))
    if known < 2:
        inp.missing.append("two of: voltage, current, resistance, power")
        return o.done()
    if v is not None and i is not None:
        r, p = (v / i if i else None), v * i
    elif v is not None and r is not None:
        i = v / r
        p = v * i
    elif i is not None and r is not None:
        v = i * r
        p = v * i
    elif p is not None and v is not None:
        i = p / v
        r = v / i
    elif p is not None and i is not None:
        v = p / i
        r = v / i
    elif p is not None and r is not None:
        i = math.sqrt(p / r)
        v = i * r
    o.add("Voltage", unit(v, "V"))
    o.add("Current", unit(i, "A"))
    o.add("Resistance", ohms(r))
    o.add("Power", unit(p, "W") + (f" → use a ≥ {fmt(nearest(p * 2, 'E6', up=True) or p * 2)} W part" if p and p > 0.05 else ""))
    return o.done()


def divider(inp: Inputs) -> dict:
    o = Out()
    vin = inp.num(["vin", "input", "input_voltage", "supply"], "voltage", "input voltage", need=True, hints=["in", "from", "supply", "input"])
    vout = inp.num(["vout", "output", "output_voltage", "target"], "voltage", "output voltage", hints=["out", "to ", "output", "down to"])
    r1 = inp.num(["r1", "top", "upper"], "resistance", "R1", text_ok=False)
    r2 = inp.num(["r2", "bottom", "lower"], "resistance", "R2", text_ok=False)
    series = inp.text(["series"], "E24").upper()
    series = series if series in E else "E24"
    volts = [q for q in inp.qs if "voltage" in q["kinds"]]
    if len(volts) >= 2 and (not vin or not vout):  # "12 V to 3.3 V": the bigger one goes in
        vals = sorted(parse(f"{q['v']} {q['unit']}", "voltage") for q in volts)
        vin, vout = vin or vals[-1], vout or vals[0]
        inp.missing[:] = [m for m in inp.missing if m != "input voltage"]
    if not vin:
        return o.done()
    if r1 and r2:
        vout = vin * r2 / (r1 + r2)
    elif vout and (r1 or r2):
        if r1:
            r2 = r1 * vout / (vin - vout)
        else:
            r1 = r2 * (vin - vout) / vout
    elif vout:
        r2 = 10e3
        r1 = r2 * (vin - vout) / vout
        inp.assumed.append("R2 = 10 kΩ")
    else:
        inp.missing.append("the output voltage (or both resistors)")
        return o.done()
    o.add("Exact", f"R1 (top) {ohms(r1)}, R2 (bottom) {ohms(r2)} → Vout {unit(vin * r2 / (r1 + r2), 'V')}")
    s1, s2 = nearest(r1, series), nearest(r2, series)
    o.add(f"Nearest {series} values", f"R1 {ohms(s1)}, R2 {ohms(s2)} → Vout {unit(vin * s2 / (s1 + s2), 'V')}")
    o.add("Current through it", unit(vin / (r1 + r2), "A"))
    o.note("Only for signals (an ADC input, a sensor): the output sags when something draws current — use a regulator to power things.")
    return o.done()


LED_VF = [("infrared", 1.3), ("ir ", 1.3), ("red", 2.0), ("orange", 2.1), ("yellow", 2.1), ("amber", 2.1), ("green", 2.2),
          ("blue", 3.1), ("white", 3.1), ("uv", 3.4), ("pink", 3.1), ("purple", 3.2)]


def led(inp: Inputs) -> dict:
    o = Out()
    vs = inp.num(["supply", "vin", "voltage", "supply_voltage"], "voltage", "supply voltage", need=True, hints=["v ", "volt", "supply", "from"])
    colour = inp.text(["colour", "color", "led", "type"], "", [w for w, _ in LED_VF])
    vf = inp.num(["vf", "forward_voltage", "led_voltage"], "voltage", "LED voltage", text_ok=False)
    if not vf:
        vf = next((v for w, v in LED_VF if w.strip() in colour), None)
        if vf is None:
            vf = 2.0
            inp.assumed.append("red LED (2.0 V)")
    i = inp.num(["current", "i", "led_current"], "current", "LED current", default=0.01, hints=["ma", "current"], show="10 mA")
    n = int(inp.num(["count", "leds", "number", "in_series"], "count", "LEDs in series", default=1, text_ok=False) or 1)
    if not vs:
        return o.done()
    drop = vs - vf * n
    if drop <= 0:
        o.warn(f"{fmt(vs)} V isn't enough for {n} LED(s) of {fmt(vf)} V in series.")
        return o.done()
    r = drop / i
    rs = nearest(r, "E12", up=True)
    o.add("Resistor", f"{ohms(r)} → use {ohms(rs)} (E12, next up)")
    o.add("Real current", unit(drop / rs, "A"))
    p = drop * drop / rs
    o.add("Resistor power", f"{unit(p, 'W')} → a {'0.25' if p < 0.12 else '0.5' if p < 0.25 else '1'} W resistor is fine")
    o.note("5–10 mA is plenty bright for an indicator; 20 mA is the usual maximum for a 5 mm LED.")
    return o.done()


COLOURS = ["black", "brown", "red", "orange", "yellow", "green", "blue", "violet", "grey", "white"]
RO = {"negru": "black", "maro": "brown", "rosu": "red", "roșu": "red", "portocaliu": "orange", "galben": "yellow",
      "verde": "green", "albastru": "blue", "violet": "violet", "mov": "violet", "gri": "grey", "gray": "grey",
      "alb": "white", "auriu": "gold", "argintiu": "silver", "purple": "violet"}
TOL = {"brown": "±1 %", "red": "±2 %", "green": "±0.5 %", "blue": "±0.25 %", "violet": "±0.1 %", "grey": "±0.05 %",
       "gold": "±5 %", "silver": "±10 %"}


def resistor_code(inp: Inputs) -> dict:
    o = Out()
    s = (inp.text(["bands", "colors", "colours", "code"], "") + " " + inp.question).lower()
    words = [RO.get(w, w) for w in re.findall(r"[a-zăâîșț]+", s)]
    bands = [w for w in words if w in COLOURS + ["gold", "silver"]]
    val = inp.num(["value", "resistance", "r"], "resistance", "value", hints=["ohm", "Ω", "k"])
    if len(bands) >= 3 and not (val and len(bands) < 3):
        digits = 3 if len(bands) >= 5 else 2
        try:
            num = int("".join(str(COLOURS.index(b)) for b in bands[:digits]))
            mult_b = bands[digits]
            mult = {"gold": 0.1, "silver": 0.01}.get(mult_b, 10 ** COLOURS.index(mult_b) if mult_b in COLOURS else 1)
        except ValueError:
            o.warn("Those colours don't make a valid code (gold / silver can't be a digit).")
            return o.done()
        tol = TOL.get(bands[digits + 1], "±20 %") if len(bands) > digits + 1 else "±20 % (no tolerance band)"
        o.add("Value", f"{ohms(num * mult)} {tol}")
        o.add("Bands read", " – ".join(bands))
        return o.done()
    if val:
        sig = f"{val:.3g}"
        mant = float(sig)
        exp = math.floor(math.log10(mant)) if mant > 0 else 0
        d2 = round(mant / 10 ** (exp - 1))
        d3 = round(mant / 10 ** (exp - 2))
        if d2 >= 100:
            d2 //= 10
            exp += 1
        four = [COLOURS[d2 // 10], COLOURS[d2 % 10], (COLOURS[exp - 1] if 0 <= exp - 1 <= 9 else "gold" if exp - 1 == -1 else "silver"), "gold"]
        five = [COLOURS[(d3 // 100) % 10], COLOURS[(d3 // 10) % 10], COLOURS[d3 % 10],
                (COLOURS[exp - 2] if 0 <= exp - 2 <= 9 else "gold" if exp - 2 == -1 else "silver"), "brown"]
        o.add(f"{ohms(val)} as 4 bands (±5 %)", " – ".join(four))
        o.add("As 5 bands (±1 %)", " – ".join(five))
        return o.done()
    inp.missing.append("the colour bands (e.g. brown black orange gold) or a value to turn into colours")
    return o.done()


def e_series(inp: Inputs) -> dict:
    o = Out()
    v = inp.num(["value", "resistance", "r", "capacitance"], "resistance", "value", need=True, hints=["ohm", "Ω", "k", "value"])
    if not v:
        return o.done()
    for s in ("E6", "E12", "E24", "E96"):
        lo, hi = nearest(v, s, down=True), nearest(v, s, up=True)
        o.add(s, f"{ohms(lo)} / {ohms(hi)} (nearest {ohms(nearest(v, s))}, {((nearest(v, s) / v) - 1) * 100:+.1f} %)")
    return o.done()


def rc(inp: Inputs) -> dict:
    o = Out()
    r = inp.num(["resistance", "r", "resistor"], "resistance", "resistance", hints=["ohm", "Ω", "k"])
    c = inp.num(["capacitance", "c", "capacitor"], "capacitance", "capacitance", hints=["f", "uf", "nf", "pf"])
    f = inp.num(["frequency", "cutoff", "fc", "f"], "frequency", "cutoff frequency", hints=["hz", "khz", "cutoff"])
    if r and c:
        tau = r * c
        o.add("Time constant τ = RC", unit(tau, "s"))
        o.add("Charges to 63 % / 99 %", f"{unit(tau, 's')} / {unit(5 * tau, 's')}")
        o.add("Filter cutoff (−3 dB)", unit(1 / (2 * math.pi * tau), "Hz"))
    elif f and c:
        r = 1 / (2 * math.pi * f * c)
        o.add("Resistor for that cutoff", f"{ohms(r)} (E24: {ohms(nearest(r))})")
    elif f and r:
        c = 1 / (2 * math.pi * f * r)
        o.add("Capacitor for that cutoff", f"{unit(c, 'F')} (E12: {unit(nearest(c, 'E12'), 'F')})")
    else:
        inp.missing.append("two of: resistor, capacitor, cutoff frequency")
    return o.done()


def lc(inp: Inputs) -> dict:
    o = Out()
    l_ = inp.num(["inductance", "l", "inductor"], "inductance", "inductance", hints=["h", "uh", "mh"])
    c = inp.num(["capacitance", "c", "capacitor"], "capacitance", "capacitance", hints=["f", "uf", "nf", "pf"])
    f = inp.num(["frequency", "f", "resonance"], "frequency", "frequency", hints=["hz", "khz", "mhz"])
    if l_ and c:
        o.add("Resonant frequency", unit(1 / (2 * math.pi * math.sqrt(l_ * c)), "Hz"))
        o.add("Impedance √(L/C)", ohms(math.sqrt(l_ / c)))
    elif f and c:
        o.add("Inductor", unit(1 / ((2 * math.pi * f) ** 2 * c), "H"))
    elif f and l_:
        o.add("Capacitor", unit(1 / ((2 * math.pi * f) ** 2 * l_), "F"))
    else:
        inp.missing.append("two of: inductor, capacitor, frequency")
    return o.done()


def timer555(inp: Inputs) -> dict:
    o = Out()
    mono = bool(re.search(r"mono|one.?shot|single pulse|delay", (inp.text(["mode"], "") + " " + inp.question).lower()))
    r1 = inp.num(["r1", "ra"], "resistance", "R1", text_ok=False)
    r2 = inp.num(["r2", "rb"], "resistance", "R2", text_ok=False)
    c = inp.num(["capacitance", "c", "capacitor"], "capacitance", "capacitor", hints=["f", "uf", "nf"])
    f = inp.num(["frequency", "f"], "frequency", "frequency", hints=["hz", "khz"])
    t = inp.num(["time", "delay", "pulse", "duration"], "time", "pulse time", hints=["second", "sec", "ms", "delay"])
    if mono:
        r = r1 or inp.num(["resistance", "r"], "resistance", "R", hints=["ohm", "Ω", "k"])
        if r and c:
            o.add("Pulse length (monostable)", unit(1.1 * r * c, "s"))
        elif t and c:
            o.add("R for that pulse", ohms(t / (1.1 * c)))
        elif t:
            c = 100e-6 if t > 1 else 10e-6 if t > 0.05 else 100e-9
            o.add("Pick", f"C {unit(c, 'F')} and R {ohms(t / (1.1 * c))}")
        else:
            inp.missing.append("R and C (or the pulse time you want)")
        return o.done()
    if r1 and r2 and c:
        fr = 1.44 / ((r1 + 2 * r2) * c)
        o.add("Frequency (astable)", unit(fr, "Hz"))
        o.add("Duty cycle", f"{fmt((r1 + r2) / (r1 + 2 * r2) * 100)} % high")
        o.add("High / low time", f"{unit(0.693 * (r1 + r2) * c, 's')} / {unit(0.693 * r2 * c, 's')}")
    elif f:
        c = c or (10e-6 if f < 10 else 100e-9 if f < 5000 else 1e-9)
        r1 = r1 or 1e3
        r2 = (1.44 / (f * c) - r1) / 2
        if r2 <= 0:
            o.warn("That frequency is too high for this C and R1 — use a smaller capacitor.")
            return o.done()
        o.add("For that frequency", f"R1 {ohms(r1)}, R2 {ohms(r2)} (E24 {ohms(nearest(r2))}), C {unit(c, 'F')}")
    else:
        inp.missing.append("R1, R2 and C (or the frequency you want)")
    return o.done()


THETA = {"to-92": 200, "sot-23": 250, "sot-223": 90, "to-252": 70, "dpak": 70, "to-263": 50, "d2pak": 50, "to-220": 50,
         "to-3": 35, "soic": 120, "sop-8": 120}  # °C/W junction to air, no heatsink, small copper area (rough)
REGS = [("lm317", 1.25, 2.5), ("lm7805", 5.0, 2.0), ("7805", 5.0, 2.0), ("7812", 12.0, 2.0), ("7809", 9.0, 2.0),
        ("ams1117-3.3", 3.3, 1.2), ("ams1117", 3.3, 1.2), ("ld1117", 3.3, 1.1), ("lm1117", 3.3, 1.2), ("ht7333", 3.3, 0.1),
        ("mcp1700", 3.3, 0.2), ("ap2112", 3.3, 0.25), ("xc6206", 3.3, 0.25)]


def regulator(inp: Inputs) -> dict:
    o = Out()
    low = (inp.text(["regulator", "part", "type", "chip"], "") + " " + inp.question).lower()
    vin = inp.num(["vin", "input", "input_voltage", "supply"], "voltage", "input voltage", need=True, hints=["in", "from", "input", "supply"])
    vout = inp.num(["vout", "output", "output_voltage"], "voltage", "output voltage", hints=["out", "to ", "output"])
    i = inp.num(["current", "load", "iout", "i"], "current", "load current", need=True, hints=["a ", "ma", "amp", "load", "current"])
    if not (vin and i):
        return o.done()
    buck = bool(re.search(r"buck|switch|dc.?dc|step.?down|lm2596|mp1584|xl4015", low))
    part = next(((n, v, d) for n, v, d in REGS if n in low), None)
    if "lm317" in low or (not vout and not part):
        r1 = inp.num(["r1"], "resistance", "R1", default=240.0, text_ok=False, show="240 Ω")
        r2 = inp.num(["r2"], "resistance", "R2", text_ok=False)
        if r2 and not vout:
            vout = 1.25 * (1 + r2 / r1) + 50e-6 * r2
        if vout:
            r2 = r2 or (vout - 1.25) / (1.25 / r1 + 50e-6)
            o.add("LM317 resistors", f"R1 {ohms(r1)}, R2 {ohms(r2)} (E24 {ohms(nearest(r2))} → {fmt(1.25 * (1 + nearest(r2) / r1) + 50e-6 * nearest(r2))} V)")
        dropout = 2.5
    elif part:
        vout = vout or part[1]
        dropout = part[2]
        o.add("Regulator", f"{part[0].upper()}: {fmt(vout)} V out, needs ≥ {fmt(vout + dropout)} V in")
    else:
        dropout = 2.0
    if not vout:
        inp.missing.append("the output voltage")
        return o.done()
    if buck:
        eta = inp.num(["efficiency"], "number", "efficiency", default=0.85, text_ok=False, show="85 %")
        eta = eta / 100 if eta > 1 else eta
        pin = vout * i / eta
        o.add("Buck converter", f"input current {unit(pin / vin, 'A')}, heat {unit(pin - vout * i, 'W')} (efficiency {int(eta * 100)} %)")
        f = inp.num(["frequency", "switching_frequency"], "frequency", "switching frequency", default=500e3, text_ok=False, show="500 kHz")
        lval = (vin - vout) * (vout / vin) / (f * 0.3 * i)
        o.add("Inductor (30 % ripple)", unit(lval, "H"))
        return o.done()
    p = (vin - vout) * i
    o.add("Heat in the regulator", f"{unit(p, 'W')} (({fmt(vin)} − {fmt(vout)}) V × {unit(i, 'A')}); efficiency {fmt(vout / vin * 100)} %")
    if vin < vout + dropout:
        o.warn(f"Not enough headroom: it needs about {fmt(vout + dropout)} V in.")
    pkg = next((k for k in THETA if k in low), "to-220")
    if pkg not in low:
        inp.assumed.append("TO-220 package without a heatsink")
    ta = inp.num(["ambient", "ambient_temperature"], "temp", "air temperature", default=25.0, text_ok=False, show="25 °C")
    tj = ta + p * THETA[pkg]
    o.add("Chip temperature", f"≈ {fmt(tj)} °C ({pkg.upper()}, {THETA[pkg]} °C/W)")
    o.verdict = ("OK without a heatsink." if tj < 100 else "Needs a heatsink (or a buck converter)." if tj < 150
                 else "Far too hot: use a buck (switching) converter.")
    if p > 1:
        o.note("Over ~1 W a buck converter is the better choice: it wastes far less as heat.")
    return o.done()


CHEM = [("lifepo4", 3.2, 3.6, 2.5, "LiFePO4"), ("lipo", 3.7, 4.2, 3.3, "LiPo"), ("li-ion", 3.6, 4.2, 3.0, "Li-ion"),
        ("18650", 3.6, 4.2, 3.0, "Li-ion 18650"), ("nimh", 1.2, 1.4, 1.0, "NiMH"), ("lead", 2.0, 2.15, 1.75, "lead-acid"),
        ("alkaline", 1.5, 1.6, 1.0, "alkaline")]


def battery(inp: Inputs) -> dict:
    o = Out()
    low = (inp.text(["chemistry", "type", "battery"], "") + " " + inp.question).lower()
    chem = next((c for c in CHEM if c[0] in low), None)
    cells = re.search(r"\b(\d{1,2})\s?s(?:\d?p)?\b", low)
    cap = inp.num(["capacity", "mah", "ah"], "charge", "capacity", hints=["mah", "ah", "capacity"])
    wh = inp.num(["energy", "wh"], "energy", "energy", text_ok=False)
    volt = inp.num(["voltage", "v"], "voltage", "voltage", hints=["v ", "volt"])
    if not volt and cells:
        per = chem[1] if chem else 3.7
        volt = int(cells.group(1)) * per
        inp.assumed.append(f"{cells.group(1)} cells × {fmt(per)} V = {fmt(volt)} V")
    if not (cap or wh):
        inp.missing.append("the battery capacity (mAh or Wh)")
        return o.done()
    if not wh:
        if not volt:
            volt = chem[1] if chem else 3.7
            inp.assumed.append(f"{fmt(volt)} V")
        wh = cap * volt
    elif not cap and volt:
        cap = wh / volt
    usable = inp.num(["usable", "depth_of_discharge"], "number", "usable share", default=0.8, text_ok=False, show="80 %")
    usable = usable / 100 if usable > 1 else usable
    o.add("Battery", f"{fmt(wh)} Wh" + (f" = {fmt(cap * 1000)} mAh at {fmt(volt)} V" if cap and volt else ""))
    load_w = inp.num(["power", "load_power", "watts"], "power", "load power", hints=["w ", "watt"])
    load_a = inp.num(["current", "load", "draw", "amps"], "current", "load current", hints=["a ", "ma", "amp", "draw"])
    if not load_w and load_a and volt:
        load_w = load_a * volt
    if load_w:
        o.add("Run time", f"{fmt(wh * usable / load_w * 60)} min ({fmt(wh * usable / load_w)} h) at {fmt(load_w)} W, using {int(usable * 100)} %")
    crate = re.search(r"\b(\d{1,3})\s?c\b", low)
    if crate and cap:
        o.add("Max current", f"{fmt(int(crate.group(1)) * cap)} A ({crate.group(1)}C)")
    chg = inp.num(["charge_current", "charger"], "current", "charge current", text_ok=False)
    if chg and cap:
        o.add("Charge time", f"≈ {fmt(cap / chg * 1.2)} h at {fmt(chg)} A")
    if chem:
        o.note(f"{chem[4]}: {chem[1]} V nominal, {chem[2]} V full, don't go under {chem[3]} V per cell.")
    return o.done()


AWG = [(30, 0.0509, 0.86), (28, 0.0810, 1.4), (26, 0.129, 2.2), (24, 0.205, 3.5), (22, 0.326, 7), (20, 0.518, 11),
       (18, 0.823, 16), (16, 1.31, 22), (14, 2.08, 32), (12, 3.31, 41), (10, 5.26, 55), (8, 8.37, 73), (6, 13.3, 101),
       (4, 21.2, 135)]  # AWG, mm², amps for short chassis wiring in air
METRIC_WIRE = [0.14, 0.25, 0.34, 0.5, 0.75, 1.0, 1.5, 2.5, 4, 6, 10, 16, 25, 35]


def wire(inp: Inputs) -> dict:
    o = Out()
    i = inp.num(["current", "amps", "i", "load"], "current", "current", need=True, hints=["a ", "amp", "current", "ma"])
    length = inp.num(["length", "distance", "run"], "length", "wire length (one way)", default=1.0, hints=["long", "length", "m ", "meter", "metre", "away"], show="1 m one way")
    volt = inp.num(["voltage", "v", "supply"], "voltage", "voltage", default=12.0, hints=["v ", "volt"], show="12 V")
    drop = inp.num(["drop", "max_drop", "voltage_drop"], "number", "allowed drop %", default=3.0, text_ok=False, show="3 %")
    if not i:
        return o.done()
    dv = volt * drop / 100
    area = 2 * length * i * RHO_CU / dv * 1e6  # mm², there and back
    heat = next(((g, a) for g, a, amp in AWG if amp >= i), None)  # the thinnest that doesn't overheat
    area = max(area, heat[1] if heat else area)
    awg = next(((g, a) for g, a, amp in AWG if a >= area), None)
    metric = next((a for a in METRIC_WIRE if a >= area), None)
    o.add("Wire needed", f"≥ {fmt(area)} mm² → {fmt(metric)} mm² or AWG {awg[0] if awg else '—'} (for {fmt(i)} A, {fmt(length)} m away, ≤ {fmt(drop)} % drop at {fmt(volt)} V)")
    if awg:
        r = 2 * length * RHO_CU / (awg[1] * 1e-6)
        o.add("In that wire", f"drop {fmt(i * r)} V, heat {fmt(i * i * r)} W")
    return o.done()


def _copper(inp: Inputs):
    t = inp.num(["thickness", "copper", "copper_thickness"], "length", "copper", text_ok=False)
    oz = re.search(r"(\d(?:[.,]\d)?)\s*oz", inp.question.lower())
    if not t:
        t = float(oz.group(1).replace(",", ".")) * OZ if oz else OZ
        if not oz:
            inp.assumed.append("1 oz copper (35 µm)")
    return t


def trace_width(inp: Inputs) -> dict:
    o = Out()
    i = inp.num(["current", "amps", "i"], "current", "current", need=True, hints=["a ", "amp", "current", "ma"])
    if not i:
        return o.done()
    rise = inp.num(["temperature_rise", "rise", "delta_t", "dt"], "temp", "temperature rise", default=10.0, hints=["rise", "°c"], show="10 °C")
    t = _copper(inp)
    inner = bool(re.search(r"inner|internal|interior", (inp.text(["layer"], "") + " " + inp.question).lower()))
    k = 0.024 if inner else 0.048
    area_mil2 = (i / (k * rise ** 0.44)) ** (1 / 0.725)
    w = area_mil2 / (t / 2.54e-5) * 2.54e-5  # m
    o.add("Track width", f"{fmt(w * 1000)} mm ({fmt(w / 2.54e-5)} mil) on an {'inner' if inner else 'outer'} layer, {fmt(t / OZ)} oz, +{fmt(rise)} °C (IPC-2221)")
    length = inp.num(["length", "track_length"], "length", "track length", hints=["long", "length"])
    if length:
        r = RHO_CU * (1 + ALPHA_CU * (25 + rise - 20)) * length / (w * t)
        o.add(f"Over {fmt(length * 1000)} mm", f"{fmt(r * 1000)} mΩ, drop {fmt(i * r * 1000)} mV, heat {fmt(i * i * r * 1000)} mW")
    o.note("Make power tracks wider than this where you can; inner layers need about 2.6× the width (they can't cool).")
    return o.done()


def via(inp: Inputs) -> dict:
    o = Out()
    d = inp.num(["drill", "hole", "diameter", "via_diameter", "d"], "length", "via drill", default=0.0003, hints=["drill", "hole", "via", "diameter"], show="0.3 mm")
    plating = inp.num(["plating", "plating_thickness"], "length", "plating", default=25e-6, text_ok=False, show="25 µm")
    board = inp.num(["board_thickness", "thickness", "board"], "length", "board thickness", default=0.0016, hints=["board", "thick"], show="1.6 mm")
    rise = inp.num(["temperature_rise", "rise"], "temp", "temperature rise", default=10.0, text_ok=False, show="10 °C")
    a = math.pi * plating * (d - plating)  # copper ring in the hole
    area_mil2 = a / (2.54e-5 ** 2)
    imax = 0.048 * rise ** 0.44 * area_mil2 ** 0.725
    r = RHO_CU * board / a
    o.add("Via", f"Ø{fmt(d * 1000)} mm drill, {fmt(plating * 1e6)} µm plating, {fmt(board * 1000)} mm board")
    o.add("Current per via", f"≈ {fmt(imax)} A for +{fmt(rise)} °C (IPC-2221)")
    o.add("Resistance", f"{fmt(r * 1000)} mΩ")
    i = inp.num(["current", "amps"], "current", "current", hints=["a ", "amp", "current"])
    if i:
        o.add("Vias needed", f"{math.ceil(i / imax)} for {fmt(i)} A")
    return o.done()


# IPC-2221B table 6-1, minimum spacing (mm) by peak voltage: B1 inner, B2 outer uncoated (≤3050 m), B3 outer uncoated
# (>3050 m), B4 outer coated, A5 outer + conformal coat on the assembly, A6 outer component lead uncoated, A7 coated lead
SPACING = [(15, [0.05, 0.1, 0.1, 0.05, 0.13, 0.13, 0.13]), (30, [0.05, 0.1, 0.1, 0.05, 0.13, 0.25, 0.13]),
           (50, [0.1, 0.6, 0.6, 0.13, 0.13, 0.4, 0.13]), (100, [0.1, 0.6, 1.5, 0.13, 0.13, 0.5, 0.13]),
           (150, [0.2, 0.6, 3.2, 0.4, 0.4, 0.8, 0.4]), (170, [0.2, 1.25, 3.2, 0.4, 0.4, 0.8, 0.4]),
           (250, [0.2, 1.25, 6.4, 0.4, 0.4, 0.8, 0.4]), (300, [0.2, 1.25, 12.5, 0.4, 0.4, 0.8, 0.8]),
           (500, [0.25, 2.5, 12.5, 0.8, 0.8, 1.5, 0.8])]
PER_VOLT = [0.0025, 0.005, 0.025, 0.00305, 0.00305, 0.00305, 0.00305]
SP_NAMES = ["B1 inner layer", "B2 outer, no coating", "B3 outer, no coating, above 3050 m", "B4 outer, solder-masked / coated",
            "A5 outer, assembly coated", "A6 component lead, no coating", "A7 component lead, coated"]


def clearance(inp: Inputs) -> dict:
    o = Out()
    v = inp.num(["voltage", "v", "peak_voltage"], "voltage", "voltage (peak)", need=True, hints=["v ", "volt", "vac", "vdc", "mains"])
    if not v:
        return o.done()
    if re.search(r"\bac\b|vac|mains|230|240", inp.question.lower()) and v < 400:
        v = v * math.sqrt(2)
        inp.assumed.append(f"AC → peak {fmt(v)} V")
    row = next((r for top, r in SPACING if v <= top), None)
    vals = row if row else [a + (v - 500) * b for a, b in zip(SPACING[-1][1], PER_VOLT)]
    for name, val in zip(SP_NAMES, vals):
        o.add(name, f"{fmt(val)} mm")
    o.note("IPC-2221B minimums. For mains (230 V) safety barriers use the appliance standards instead: about 3 mm creepage for "
           "basic and 6 mm for reinforced insulation, plus slots in the board.")
    return o.done()


def _kk(k: float) -> float:
    """K(k)/K(k') (Hilberg's approximation, < 3 ppm error)."""
    kp = math.sqrt(1 - k * k)
    if k <= 0.7071:
        return math.pi / math.log(2 * (1 + math.sqrt(kp)) / (1 - math.sqrt(kp)))
    return math.log(2 * (1 + math.sqrt(k)) / (1 - math.sqrt(k))) / math.pi


def z_microstrip(w, h, t, er):
    """Hammerstad quasi-static microstrip with the Bahl–Garg thickness correction. -> (Z0, εeff)."""
    if t > 0:
        we = w + (t / math.pi) * (1 + math.log(2 * h / t)) if w / h >= 1 / (2 * math.pi) else w + (t / math.pi) * (1 + math.log(4 * math.pi * w / t))
    else:
        we = w
    u = we / h
    if u <= 1:
        eeff = (er + 1) / 2 + (er - 1) / 2 * ((1 + 12 / u) ** -0.5 + 0.04 * (1 - u) ** 2)
        z = 60 / math.sqrt(eeff) * math.log(8 / u + u / 4)
    else:
        eeff = (er + 1) / 2 + (er - 1) / 2 * (1 + 12 / u) ** -0.5
        z = 120 * math.pi / (math.sqrt(eeff) * (u + 1.393 + 0.667 * math.log(u + 1.444)))
    return z, eeff


def z_stripline(w, b, t, er):
    return 60 / math.sqrt(er) * math.log(4 * b / (0.67 * math.pi * (0.8 * w + t))), er


def z_cpwg(w, s, h, er):
    """Grounded coplanar waveguide (Wadell)."""
    k = w / (w + 2 * s)
    k1 = math.tanh(math.pi * w / (4 * h)) / math.tanh(math.pi * (w + 2 * s) / (4 * h))
    r, r1 = _kk(k), _kk(k1)
    eeff = (1 + er * r1 / r) / (1 + r1 / r)
    return 60 * math.pi / math.sqrt(eeff) / (r + r1), eeff


def impedance(inp: Inputs) -> dict:
    o = Out()
    low = (inp.text(["type", "line", "geometry"], "") + " " + inp.question).lower()
    kind = "stripline" if "stripline" in low or "inner" in low else "cpwg" if re.search(r"coplanar|cpw", low) else "microstrip"
    er = inp.num(["er", "dielectric_constant", "permittivity", "dk"], "number", "εr", default=4.5, hints=["er", "dk", "εr"], show="4.5 (FR-4)")
    h = inp.num(["height", "h", "dielectric", "dielectric_thickness", "board_thickness"], "length", "dielectric height", hints=["height", "dielectric", "prepreg", "core", "board", "thick"])
    if not h:
        h = 0.0016 if not re.search(r"4.?layer|four layer|jlc", low) else 0.0002104
        inp.assumed.append(f"dielectric {fmt(h * 1000)} mm ({'2-layer 1.6 mm board' if h > 0.001 else 'JLC 4-layer top to the plane below'})")
    t = _copper(inp)
    w = inp.num(["width", "w", "track_width", "trace_width"], "length", "track width", hints=["wide", "width", "track", "trace"])
    gap = inp.num(["gap", "spacing", "s"], "length", "gap to ground", text_ok=False)
    target = inp.num(["target", "impedance", "z0", "z"], "resistance", "target impedance", hints=["ohm", "Ω", "impedance"])
    diff = bool(re.search(r"diff|usb|lvds|ethernet|pair", low))

    def z_of(width):
        if kind == "stripline":
            return z_stripline(width, h, t, er)
        if kind == "cpwg":
            return z_cpwg(width, gap or 0.0002, h, er)
        return z_microstrip(width, h, t, er)
    if kind == "cpwg" and not gap:
        inp.assumed.append("gap to the ground pour 0.2 mm")
    def zdiff(width):
        z1, _ = z_of(width)
        s_ = gap or width  # the pair's spacing: the given gap, else = the track width
        return 2 * z1 * (1 - 0.347 * math.exp(-2.9 * s_ / h)) if kind == "stripline" else 2 * z1 * (1 - 0.48 * math.exp(-0.96 * s_ / h))
    if w and not target:
        z, eeff = z_of(w)
    else:
        target = target or (90 if diff else 50)
        f_ = zdiff if diff else (lambda width: z_of(width)[0])
        lo, hi = 1e-6, 0.02
        for _ in range(80):
            mid = math.sqrt(lo * hi)
            if f_(mid) > target:
                lo = mid
            else:
                hi = mid
        w = math.sqrt(lo * hi)
        z, eeff = z_of(w)
    names = {"microstrip": "microstrip (outer layer over a plane)", "stripline": "stripline (inner layer between two planes)",
             "cpwg": "coplanar waveguide with ground"}
    o.add("Line", f"{names[kind]}, εr {fmt(er)}, dielectric {fmt(h * 1000)} mm, copper {fmt(t * 1e6)} µm")
    o.add("Track width", f"{fmt(w * 1000)} mm ({fmt(w / 2.54e-5)} mil)")
    o.add("Single track" if diff else "Impedance", f"{fmt(z)} Ω (effective εr {fmt(eeff)}, delay {fmt(math.sqrt(eeff) / 0.299792458)} ps per mm)")
    if diff:
        o.add("Differential pair", f"≈ {fmt(zdiff(w))} Ω: two {fmt(w * 1000)} mm tracks {fmt((gap or w) * 1000)} mm apart (USB wants 90 Ω, Ethernet 100 Ω)")
    o.note("Closed-form estimate (±5–10 %); ask your board maker for their stackup and use their impedance calculator for the final value.")
    return o.done()


def attenuator(inp: Inputs) -> dict:
    o = Out()
    db = inp.num(["db", "attenuation", "loss"], "number", "attenuation (dB)", need=True, hints=["db"])
    z0 = inp.num(["impedance", "z0", "z"], "resistance", "impedance", default=50.0, hints=["ohm", "Ω"], show="50 Ω")
    if not db:
        return o.done()
    k = 10 ** (db / 20)
    o.add("Pi pad", f"shunt {ohms(z0 * (k + 1) / (k - 1))} – series {ohms(z0 * (k * k - 1) / (2 * k))} – shunt {ohms(z0 * (k + 1) / (k - 1))}")
    o.add("T pad", f"series {ohms(z0 * (k - 1) / (k + 1))} – shunt {ohms(2 * z0 * k / (k * k - 1))} – series {ohms(z0 * (k - 1) / (k + 1))}")
    return o.done()


def fusing(inp: Inputs) -> dict:
    o = Out()
    w = inp.num(["width", "track_width", "trace_width"], "length", "track width", hints=["wide", "width", "track"])
    d = inp.num(["diameter", "wire_diameter"], "length", "wire diameter", text_ok=False)
    t = inp.num(["time", "duration", "seconds"], "time", "time", default=1.0, hints=["second", "sec", "ms"], show="1 s")
    ta = inp.num(["ambient"], "temp", "ambient", default=25.0, text_ok=False, show="25 °C")
    if w:
        area = w * _copper(inp)
    elif d:
        area = math.pi * d * d / 4
    else:
        inp.missing.append("the track width (or the wire diameter)")
        return o.done()
    cmil = area / (math.pi / 4 * 2.54e-5 ** 2)
    i = cmil * math.sqrt(math.log10(1 + (1083 - ta) / (234 + ta)) / (33 * t))
    o.add("Fuses (melts) at", f"≈ {fmt(i)} A for {fmt(t)} s (Onderdonk, copper)")
    o.note("That's when the copper melts — design for far less (see track width).")
    return o.done()


def capacitor(inp: Inputs) -> dict:
    o = Out()
    c = inp.num(["capacitance", "c", "capacitor"], "capacitance", "capacitance", need=True, hints=["f", "uf", "nf", "pf", "farad"])
    v = inp.num(["voltage", "v"], "voltage", "voltage", hints=["v ", "volt"])
    f = inp.num(["frequency", "f"], "frequency", "frequency", hints=["hz", "khz"])
    if not c:
        return o.done()
    if v:
        o.add("Charge", unit(c * v, "C"))
        o.add("Energy stored", unit(0.5 * c * v * v, "J"))
    if f:
        o.add(f"Reactance at {unit(f, 'Hz')}", ohms(1 / (2 * math.pi * f * c)))
    r = inp.num(["resistance", "r"], "resistance", "resistance", hints=["ohm", "Ω", "k"])
    if r:
        o.add("Through that resistor", f"τ = {unit(r * c, 's')}, full in ≈ {unit(5 * r * c, 's')}")
    if not (v or f or r):
        inp.missing.append("the voltage (energy), frequency (reactance) or resistor (charge time)")
    return o.done()


def opamp(inp: Inputs) -> dict:
    o = Out()
    low = inp.question.lower() + " " + inp.text(["config", "type", "mode"], "")
    inv = bool(re.search(r"\binvert", low)) and not re.search(r"non[\s-]?invert", low)
    rf = inp.num(["rf", "feedback", "r2"], "resistance", "Rf", text_ok=False)
    rg = inp.num(["rg", "rin", "r1", "input_resistor"], "resistance", "Rg", text_ok=False)
    gain = inp.num(["gain", "g"], "number", "gain", hints=["gain", "times", "x "])
    if rf and rg:
        g = -rf / rg if inv else 1 + rf / rg
        o.add("Gain", f"{fmt(g)} ({fmt(20 * math.log10(abs(g)))} dB, {'inverting' if inv else 'non-inverting'})")
    elif gain:
        rg = rg or 10e3
        rf = abs(gain) * rg if inv else (abs(gain) - 1) * rg
        o.add("Resistors", f"Rg {ohms(rg)}, Rf {ohms(rf)} (E24 {ohms(nearest(rf))}) for gain {fmt(gain)} ({'inverting' if inv else 'non-inverting'})")
    else:
        inp.missing.append("the gain you want (or Rf and Rg)")
        return o.done()
    gbw = inp.num(["gbw", "gain_bandwidth"], "frequency", "gain-bandwidth", text_ok=False)
    if gbw:
        o.add("Bandwidth", unit(gbw / abs(gain or (rf / rg)), "Hz"))
    return o.done()


def decibel(inp: Inputs) -> dict:
    o = Out()
    low = inp.question.lower()
    db = inp.num(["db"], "number", "dB", hints=["db"])
    dbm = inp.num(["dbm"], "number", "dBm", text_ok=False)
    mm = re.search(r"(-?\d+(?:[.,]\d+)?)\s*dbm\b", low)
    if mm and dbm is None:
        dbm = float(mm.group(1).replace(",", "."))
    ratio = inp.num(["ratio"], "number", "ratio", text_ok=False)
    p = inp.num(["power", "watts"], "power", "power", hints=["w ", "mw", "watt"])
    if dbm is not None:
        w = 10 ** (dbm / 10) / 1000
        o.add(f"{fmt(dbm)} dBm", f"{unit(w, 'W')} = {unit(math.sqrt(w * 50), 'V')} rms on 50 Ω")
    elif p:
        o.add(f"{unit(p, 'W')}", f"{fmt(10 * math.log10(p * 1000))} dBm")
    elif db is not None:
        o.add(f"{fmt(db)} dB", f"power × {fmt(10 ** (db / 10))}, voltage × {fmt(10 ** (db / 20))}")
    elif ratio:
        o.add(f"Ratio {fmt(ratio)}", f"{fmt(10 * math.log10(ratio))} dB as power, {fmt(20 * math.log10(ratio))} dB as voltage")
    else:
        inp.missing.append("a dB value, a dBm value, a power or a ratio")
    return o.done()


CALCS = {
    "ohm": (ohm_law, "Ohm's law and power", "ohm ohms law voltage current resistance power watts amps legea lui ohm"),
    "divider": (divider, "Voltage divider (with real resistor values)", "divider voltage divider resistor divider r1 r2 vout scale down divizor"),
    "led": (led, "LED resistor", "led resistor led current forward voltage rezistenta led"),
    "resistor_code": (resistor_code, "Resistor colour code ↔ value", "colour color code bands brown black red orange resistor color cod culori"),
    "e_series": (e_series, "Nearest standard resistor values (E6–E96)", "e12 e24 e96 e series standard value nearest resistor value"),
    "rc": (rc, "RC time constant and filter cutoff", "rc time constant filter cutoff low pass high pass charge capacitor resistor"),
    "lc": (lc, "LC resonance", "lc resonance resonant tank inductor capacitor frequency"),
    "timer555": (timer555, "555 timer (astable / monostable)", "555 timer astable monostable blink frequency duty ne555"),
    "regulator": (regulator, "Regulators: LM317, 7805 / AMS1117 heat, buck converter", "regulator lm317 7805 ams1117 ldo buck converter step down heat dissipation stabilizator"),
    "battery": (battery, "Battery run time, energy, C-rating", "battery runtime mah wh lipo li-ion 18650 cells 3s 4s run time how long baterie acumulator"),
    "wire": (wire, "Wire size for a current (mm² / AWG)", "wire gauge awg mm2 cable size current voltage drop sarma cablu"),
    "trace_width": (trace_width, "PCB track width for a current (IPC-2221)", "trace track width pcb current ipc-2221 copper oz traseu cablaj"),
    "via": (via, "PCB via current and resistance", "via vias pcb plating drill current"),
    "clearance": (clearance, "PCB electrical spacing for a voltage (IPC-2221B)", "clearance spacing creepage pcb voltage isolation ipc distance between tracks"),
    "impedance": (impedance, "PCB track impedance (microstrip / stripline / coplanar)", "impedance 50 ohm microstrip stripline coplanar usb differential rf trace controlled impedance"),
    "attenuator": (attenuator, "Pi / T attenuator pads", "attenuator pad pi tee db rf attenuation"),
    "fusing": (fusing, "Fusing current of a track or wire", "fusing current melt burn fuse trace wire onderdonk"),
    "capacitor": (capacitor, "Capacitor charge, energy, reactance", "capacitor energy charge reactance farad supercap condensator"),
    "opamp": (opamp, "Op-amp gain resistors", "op amp opamp gain amplifier inverting non-inverting feedback amplificator"),
    "decibel": (decibel, "dB / dBm conversions", "db dbm decibel gain loss ratio"),
}
