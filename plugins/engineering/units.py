"""Units, quantities and materials shared by the calculator plugins (engineering, fluids, electronics).

Everything is worked out in SI (m, N, kg, Pa, W, m/s, m3/s, s); values come in as numbers or as text with a unit
("20 cm", "5 kg", "2 bar", "1/2 in", "M5", "12x30 mm") and go out in the units people use (mm, N·m, kg·cm, bar...).
A value the AI didn't fill in is looked for in the user's own words (the question), next to a hint word."""
import json
import math
import re
from pathlib import Path

G = 9.80665
HERE = Path(__file__).resolve().parent

# kind -> {unit: factor to SI}. Keys are written the way norm_unit() leaves them (lower case, no spaces / dots / ·).
UNITS = {
    "length": {"m": 1, "meter": 1, "meters": 1, "metre": 1, "metres": 1, "mm": 1e-3, "millimeter": 1e-3,
               "millimeters": 1e-3, "millimetre": 1e-3, "millimetres": 1e-3, "cm": 1e-2, "centimeter": 1e-2,
               "centimeters": 1e-2, "km": 1e3, "in": 0.0254, "inch": 0.0254, "inches": 0.0254, '"': 0.0254,
               "ft": 0.3048, "foot": 0.3048, "feet": 0.3048, "um": 1e-6, "µm": 1e-6, "micron": 1e-6, "microns": 1e-6,
               "dm": 0.1, "mil": 2.54e-5, "mils": 2.54e-5, "thou": 2.54e-5},
    "force": {"n": 1, "newton": 1, "newtons": 1, "kn": 1e3, "kgf": G, "kg": G, "kgs": G, "kilo": G, "kilos": G,
              "g": G / 1000, "gf": G / 1000, "grams": G / 1000, "gram": G / 1000, "lbf": 4.44822, "lb": 4.44822,
              "lbs": 4.44822, "t": G * 1000, "ton": G * 1000, "tonne": G * 1000, "tons": G * 1000, "dan": 10},
    "mass": {"kg": 1, "kgs": 1, "kilo": 1, "kilos": 1, "kilogram": 1, "kilograms": 1, "g": 1e-3, "gram": 1e-3,
             "grams": 1e-3, "gr": 6.479891e-5, "grain": 6.479891e-5, "grains": 6.479891e-5, "mg": 1e-6, "t": 1000,
             "tonne": 1000, "ton": 1000, "tons": 1000, "lb": 0.453592, "lbs": 0.453592, "oz": 0.0283495},
    "torque": {"nm": 1, "newtonmeter": 1, "newtonmeters": 1, "nmm": 1e-3, "ncm": 1e-2, "kgcm": G / 100,
               "kgfcm": G / 100, "kgm": G, "kgfm": G, "gcm": G / 1e5, "gfcm": G / 1e5, "lbfin": 0.112985,
               "lbin": 0.112985, "inlb": 0.112985, "inlbs": 0.112985, "lbft": 1.35582, "lbfft": 1.35582,
               "ftlb": 1.35582, "ftlbs": 1.35582, "ozin": 0.00706155, "ozfin": 0.00706155, "knm": 1e3},
    "pressure": {"pa": 1, "kpa": 1e3, "mpa": 1e6, "gpa": 1e9, "bar": 1e5, "bars": 1e5, "mbar": 100, "psi": 6894.76,
                 "atm": 101325, "n/mm2": 1e6, "n/m2": 1, "kn/m2": 1e3, "mh2o": 9806.65, "mwc": 9806.65,
                 "mmh2o": 9.80665, "mmhg": 133.322, "torr": 133.322, "ksi": 6.89476e6, "kgf/cm2": 98066.5,
                 "barg": 1e5, "psig": 6894.76},
    "power": {"w": 1, "watt": 1, "watts": 1, "kw": 1e3, "mw": 1e-3, "hp": 745.7, "ps": 735.5, "cv": 735.5},
    "speed": {"m/s": 1, "mps": 1, "mm/s": 1e-3, "cm/s": 1e-2, "m/min": 1 / 60, "mm/min": 1 / 60000, "km/h": 1 / 3.6,
              "kmh": 1 / 3.6, "kph": 1 / 3.6, "mph": 0.44704, "ft/s": 0.3048, "fps": 0.3048, "ft/min": 0.00508,
              "in/s": 0.0254, "in/min": 0.0254 / 60},
    "flow": {"m3/s": 1, "l/s": 1e-3, "lps": 1e-3, "l/min": 1 / 60000, "lpm": 1 / 60000, "lmin": 1 / 60000,
             "l/h": 1 / 3.6e6, "lph": 1 / 3.6e6, "m3/h": 1 / 3600, "m3/min": 1 / 60, "ml/s": 1e-6, "ml/min": 1 / 6e7,
             "cc/s": 1e-6, "cc/min": 1 / 6e7, "gpm": 6.30902e-5, "gal/min": 6.30902e-5, "gph": 1.05150e-6,
             "cfm": 4.71947e-4, "ft3/min": 4.71947e-4, "cm3/s": 1e-6, "mm3/s": 1e-9},
    "rpm": {"rpm": 1, "rev/min": 1, "r/min": 1, "turns/min": 1, "rps": 60, "rev/s": 60, "hz": 60, "rad/s": 60 / (2 * math.pi)},
    "angle": {"deg": 1, "°": 1, "degree": 1, "degrees": 1, "grade": 1, "grad": 1, "rad": 180 / math.pi},
    "voltage": {"v": 1, "volt": 1, "volts": 1, "mv": 1e-3, "vdc": 1, "vac": 1},  # no "kv": that is motor KV
    "current": {"a": 1, "amp": 1, "amps": 1, "ampere": 1, "amperes": 1, "ma": 1e-3, "ua": 1e-6, "µa": 1e-6},
    "resistance": {"ohm": 1, "ohms": 1, "ω": 1, "r": 1, "kohm": 1e3, "kohms": 1e3, "kω": 1e3, "k": 1e3,
                   "mohm": 1e6, "mω": 1e6, "meg": 1e6},
    "capacitance": {"f": 1, "mf": 1e-3, "uf": 1e-6, "µf": 1e-6, "nf": 1e-9, "pf": 1e-12},
    "inductance": {"h": 1, "mh": 1e-3, "uh": 1e-6, "µh": 1e-6, "nh": 1e-9},
    "charge": {"ah": 1, "mah": 1e-3},  # Ah
    "energy": {"wh": 1, "kwh": 1e3, "j": 1 / 3600, "kj": 1 / 3.6, "mj": 1000 / 3.6},  # Wh
    "density": {"kg/m3": 1, "g/cm3": 1000, "g/cc": 1000, "g/ml": 1000, "kg/l": 1000, "kg/dm3": 1000, "lb/ft3": 16.0185},
    "viscosity": {"pas": 1, "pa*s": 1, "mpas": 1e-3, "cp": 1e-3, "centipoise": 1e-3, "p": 0.1, "poise": 0.1},
    "kinvisc": {"m2/s": 1, "cst": 1e-6, "mm2/s": 1e-6, "centistokes": 1e-6, "st": 1e-4},
    "time": {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "ms": 1e-3, "us": 1e-6, "µs": 1e-6, "min": 60,
             "mins": 60, "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600,
             "hours": 3600, "day": 86400, "days": 86400, "year": 3.15576e7, "years": 3.15576e7},
    "accel": {"m/s2": 1, "g": G, "mm/s2": 1e-3},
    "volume": {"m3": 1, "l": 1e-3, "liter": 1e-3, "liters": 1e-3, "litre": 1e-3, "litres": 1e-3, "ml": 1e-6,
               "cl": 1e-5, "dl": 1e-4, "cm3": 1e-6, "cc": 1e-6, "mm3": 1e-9, "dm3": 1e-3, "gal": 3.78541e-3,
               "gallon": 3.78541e-3, "gallons": 3.78541e-3, "ft3": 0.0283168, "in3": 1.63871e-5},
    "area": {"m2": 1, "mm2": 1e-6, "cm2": 1e-4, "dm2": 1e-2, "in2": 6.4516e-4, "ft2": 0.092903},
    "stiffness": {"n/m": 1, "n/mm": 1e3, "kn/m": 1e3, "lbf/in": 175.127, "lb/in": 175.127, "kg/mm": G * 1000},
    "frequency": {"hz": 1, "khz": 1e3, "mhz": 1e6, "ghz": 1e9},
    "temp": {},
}
DEFAULT_UNIT = {"length": "mm", "force": "N", "mass": "kg", "torque": "Nm", "pressure": "bar", "power": "W",
                "speed": "m/s", "flow": "l/min", "rpm": "rpm", "angle": "deg", "voltage": "V", "current": "A",
                "resistance": "ohm", "capacitance": "uF", "inductance": "uH", "charge": "mAh", "energy": "Wh",
                "density": "kg/m3", "viscosity": "mPas", "kinvisc": "cSt", "time": "s", "accel": "m/s2", "volume": "l",
                "area": "mm2", "stiffness": "N/mm", "frequency": "Hz"}
TEMP_UNITS = {"c": "c", "°c": "c", "degc": "c", "celsius": "c", "f": "f", "°f": "f", "degf": "f", "fahrenheit": "f",
              "k": "k", "kelvin": "k"}


def norm_unit(u: str) -> str:
    u = (u or "").strip().lower().replace("²", "2").replace("³", "3").replace("·", "").replace("×", "x")
    u = re.sub(r"(?<=[a-zµ])[.\- ](?=[a-zµ])", "", u)  # "kg.cm", "N-m", "kg cm" -> kgcm / nm
    u = u.replace(" ", "").replace("^", "").replace("per", "/")
    return u.rstrip(".")


NUM = r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:e[-+]?\d+)?"


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _lookup(unit: str, kind: str):
    """Factor to SI for a unit of this kind; tries the whole unit text, then its first words ("mm thick" -> mm)."""
    table = UNITS.get(kind, {})
    words = unit.split()
    for cand in [unit] + [" ".join(words[:n]) for n in (3, 2, 1) if len(words) > n - 1]:
        u = norm_unit(cand)
        if not u:
            continue
        if u in table:
            return table[u]
        if u.endswith("s") and u[:-1] in table:  # "newtons", "bars"
            return table[u[:-1]]
    return None


def parse(value, kind: str, unit: str = ""):
    """A value as SI for its kind: 20 (+ default unit) or "20 cm" / "1/2 in" / "5,5 mm". None if there's no number
    or its unit isn't one of this kind ("2 m/s" asked as rpm)."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _to_si(float(value), unit or DEFAULT_UNIT.get(kind, ""), kind)
    s = str(value).strip()
    m = re.match(r"^\s*(\d+)\s+(\d+)\s*/\s*(\d+)\s*(.*)$", s)  # 1 1/4 in
    if m and float(m.group(3)):
        return _to_si(float(m.group(1)) + float(m.group(2)) / float(m.group(3)), m.group(4) or unit, kind)
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*(.*)$", s)  # 1/2 in
    if m and float(m.group(2)):
        return _to_si(float(m.group(1)) / float(m.group(2)), m.group(3) or unit, kind)
    m = re.match(rf"^\s*(?:approx\.?|about|~|≈)?\s*({NUM})\s*(.*)$", s, re.I)
    if not m:
        return None
    u = re.split(r"\s+(?:of|at|for|per|with|on|in)\s+|[,;(]", m.group(2).strip())[0].strip() if m.group(2) else ""
    return _to_si(_num(m.group(1)), u or unit or DEFAULT_UNIT.get(kind, ""), kind)


def _to_si(v: float, unit: str, kind: str):
    u = norm_unit(unit)
    if kind == "temp":
        t = TEMP_UNITS.get(u, "c")
        return (v - 32) * 5 / 9 if t == "f" else v - 273.15 if t == "k" else v
    if kind == "angle" and u in ("%", "percent"):  # a slope given in percent
        return math.degrees(math.atan(v / 100))
    if kind in ("count", "number", "ratio"):
        return v
    if not u:
        return v
    f = _lookup(unit, kind)
    return None if f is None else v * f


KEY_UNIT = re.compile(r"_(mm|cm|m|in|n|kn|kg|g|nm|kgcm|bar|psi|mpa|kpa|pa|w|kw|rpm|deg|v|a|ma|mah|ah|wh|lmin|l_min|"
                      r"lpm|ls|m3h|s|min|h|ms|mms|kmh|c|f|nmm|gpa|uf|nf|pf|uh|mh|ohm|kohm|hz|khz|oz|um|mil|cc|fps|gr)$")


def norm_key(k: str) -> tuple[str, str]:
    """"length_mm" -> ("length", "mm"); "Pipe Diameter (mm)" -> ("pipediameter", "mm")."""
    k = str(k).strip().lower()
    unit = ""
    m = re.search(r"\(([^)]+)\)\s*$", k) or re.search(r"\[([^\]]+)\]\s*$", k)
    if m:
        unit, k = m.group(1), k[:m.start()]
    k = k.strip().replace("-", "_").replace(" ", "_")
    m = KEY_UNIT.search(k)
    if m and len(k) > len(m.group(0)):
        unit = unit or {"lmin": "l/min", "l_min": "l/min", "ls": "l/s", "m3h": "m3/h", "mms": "mm/s", "kmh": "km/h"}.get(m.group(1), m.group(1))
        k = k[:m.start()]
    return re.sub(r"[^a-z0-9]", "", k), unit


# ------------------------------------------------------------------ finding numbers in the user's own words
KIND_OF: dict[str, list[str]] = {}
for _k, _t in UNITS.items():
    for _u in _t:
        KIND_OF.setdefault(_u, []).append(_k)
NUM_RE = re.compile(r"(?<![A-Za-z0-9_.,/])((?:\d+\s+)?\d+\s*/\s*\d+(?![\d.])|\d+(?:[.,]\d+)?(?:e[-+]?\d+)?|[.,]\d+)")
UNIT_RE = re.compile(r"\s?([a-zA-Zµ°%\"”Ωω²³·]+(?:\s?[./·]\s?[a-zA-Z0-9²³]+)*)")
WORD_RE = re.compile(r"[A-Za-zÀ-ž°µ]+(?:[-'][A-Za-z]+)*|[,;:!?()]|\.(?!\d)")
STOP = {"a", "an", "the", "my", "of", "and", "with", "at", "is", "are", "it", "its", "on", "in", "for", "by", "about",
        "around", "approx", "approximately", "roughly", "some", "each", "only", "just", "that", "this", "be", "will",
        "can", "would", "than", "then", "or", "x", "if", "i", "has", "have", "we", "our", "your", "me", "de", "la", "cu",
        "si", "și", "un", "o", "pe", "din"}
PRE_ONLY = {"from", "to", "into", "at", "via", "under", "over", "below", "above"}
LENGTH_POST = {"long", "length", "high", "height", "tall", "wide", "width", "thick", "thickness", "deep", "depth",
               "diameter", "dia", "diam", "bore", "across", "span", "stroke", "apart", "away", "up", "down", "radius",
               "od", "id", "wall", "gap", "round", "inside", "outside", "lungime", "inaltime", "latime", "grosime",
               "adancime", "diametru"}
LEXICON = LENGTH_POST | {
    "zero", "zeroed", "zeroing", "scope", "sight", "wind", "crosswind", "breeze", "bc", "coefficient", "range", "distance",
    "tank", "reservoir", "fill", "refill", "bottle", "scuba", "rise", "lift", "climb", "slope", "incline", "hill", "ramp",
    "temperature", "temp", "ambient", "rpm", "speed", "velocity", "torque", "load", "payload", "weight", "weighs", "weigh",
    "mass", "force", "pressure", "voltage", "current", "power", "frequency", "capacity", "flow", "head", "lead", "pitch",
    "module", "modul", "teeth", "coils", "turns", "travel", "compression", "deflection", "free", "solid", "rod", "inner",
    "outer", "hole", "outlet", "nozzle", "orifice", "span", "zone", "kill", "step", "every", "max", "min", "cut", "shots",
    "supply", "input", "output", "in", "out", "efficiency", "gain", "cutoff", "rate", "stiffness", "time", "delay",
    "closing", "consumption", "uses", "use", "draws", "draw", "limit", "steps", "microsteps", "requested", "asked",
    "measured", "actual", "extruded", "expected", "layer", "wire", "cells", "elevation", "altitude", "spring"}
COUNT_NOUNS = {"bolt", "bolts", "screw", "screws", "motor", "motors", "wheel", "wheels", "tooth", "teeth", "coil", "coils",
               "turn", "turns", "cell", "cells", "shot", "shots", "piece", "pieces", "pc", "pcs", "elbow", "elbows", "valve",
               "valves", "fitting", "fittings", "layer", "layers", "led", "leds", "link", "links", "joint", "joints",
               "servo", "servos", "leg", "legs", "hole", "holes", "cylinder", "cylinders", "pulley", "pulleys", "gear",
               "gears", "blade", "blades", "fill", "fills", "stage", "stages", "times", "starts", "bends", "tees",
               "via", "vias", "nuts", "washers", "people", "persons", "dinti", "suruburi", "roti", "motoare"}


def _value(s: str) -> float:
    s = s.strip()
    if "/" in s:
        parts = s.replace("/", " / ").split()
        if len(parts) == 4:  # 1 1/4
            return float(parts[0]) + float(parts[1]) / float(parts[3])
        return float(parts[0]) / float(parts[2]) if float(parts[2]) else 0.0
    return _num(s)


def _known(u: str):
    if not u:
        return None
    if u in ("%", "percent"):
        return ["percent", "angle"]
    if u in ('"', "”"):
        return ["length"]
    kinds = list(KIND_OF.get(u, [])) or (list(KIND_OF.get(u[:-1], [])) if u.endswith("s") and len(u) > 2 else [])
    if u in TEMP_UNITS or u in ("°", "°c", "°f"):
        kinds = kinds + ["temp"] if u not in ("°",) else ["angle", "temp"]
    return kinds or None


def quantities(text: str) -> list[dict]:
    """Every number in a text with its unit and the word it belongs to: "200 mm long" -> long, "zero at 30 m" -> zero,
    "scope height 50 mm" -> height (+ "scope height"), "4 elbows" -> a count of elbows."""
    text = text or ""
    words = [(m.group(0).lower(), m.start(), m.end()) for m in WORD_RE.finditer(text)]
    out = []
    for m in NUM_RE.finditer(text):
        try:
            v = _value(m.group(1))
        except (ValueError, ZeroDivisionError):
            continue
        uend, unit, kinds, noun = m.end(), "", None, None
        um = UNIT_RE.match(text, m.end())
        if um and not (um.end() < len(text) and text[um.end()].isdigit()):  # "M5" after a number isn't a unit
            cand = um.group(1)
            if cand.lower() == "mc" and re.match(r"\s+(?:long|length|lung|tall|high|wide|reach)\b", text[um.end():], re.I):
                cand = "cm"  # "30 mc long" = 30 cm (the chat's arm got a x30 safety factor and a made-up 50 mm length)
            nu = norm_unit(cand.rstrip("."))
            kinds = _known(nu)
            if not kinds:  # "kg cm", "N m", "ft lb": a unit written as two words
                um2 = re.match(r"\s([a-zA-Z]+)", text[um.end():])
                if um2:
                    k2 = _known(norm_unit(cand + um2.group(1)))
                    if k2:
                        kinds, nu, uend = k2, norm_unit(cand + um2.group(1)), um.end() + um2.end()
            if kinds:
                unit = nu
                uend = max(uend, um.end())
            elif cand.lower() in COUNT_NOUNS or cand.lower().rstrip("s") in COUNT_NOUNS:
                kinds, noun, uend = ["count", "number"], cand.lower(), um.end()
        if not kinds:
            kinds = ["number", "count"]
        q = {"v": v, "unit": unit, "kinds": kinds, "pos": m.start(), "end": uend, "used": False, "noun": noun}
        q["bind"], q["bind2"], q["strong"] = _bind(text, q, words)
        out.append(q)
    return out


def _bind(text: str, q: dict, words) -> tuple:
    if q["noun"]:
        return q["noun"], None, True
    nxt = next(((w, s) for w, s, e in words if s >= q["end"]), None)
    after = None
    if nxt and nxt[0] not in ",;:!?()." and not re.search(r"\d", text[q["end"]:nxt[1]]) and nxt[1] - q["end"] <= 3:
        after = nxt[0]
    before, before2 = None, None
    prev = [(w, s, e) for w, s, e in words if e <= q["pos"]]
    seen = []
    for w, s, e in reversed(prev[-5:]):
        if w in ",;:!?().":
            break
        if re.search(r"\d", text[e:q["pos"]]) and seen == [] and text[e:q["pos"]].strip():
            break  # another number sits between
        if w in STOP and not seen:
            continue
        seen.append(w)
        if len(seen) == 2:
            break
    if seen:
        before = seen[0]
        before2 = f"{seen[1]} {seen[0]}" if len(seen) > 1 else None
    # "strong" = a size word that tells lengths apart ("200 mm long" is not a diameter): such a number is only taken by
    # a field that names that word; everything else may also go to the one field of its kind that's left
    is_len = "length" in q["kinds"]
    if after and is_len and after in LENGTH_POST:
        return after, None, True
    if before and (before in LEXICON or before in PRE_ONLY or (before2 and before2 in LEXICON)):
        return before, before2, bool(is_len and before in LENGTH_POST)
    if after and after not in STOP and after not in PRE_ONLY:
        return after, None, False  # "a 20 mm hole", "1/2 inch pipe", "20 rpm speed"
    return (before, before2, False) if before else (None, None, False)


def _matches(q: dict, hints) -> bool:
    b, b2 = q.get("bind"), q.get("bind2")
    if not b:
        return False
    for h in hints:
        h = h.strip().lower()
        if not h:
            continue
        if h == b or h == b2:
            return True
        if len(h) >= 4 and len(b) >= 4 and (b.startswith(h) or h.startswith(b)):
            return True
    return False


def from_text(qs: list[dict], text: str, kind: str, hints: list[str], lone: bool = True):
    """The quantity of this kind that belongs to one of the hint words — or the only one of its kind when nothing
    else claims it. Marks it used."""
    cands = [q for q in qs if kind in q["kinds"] and not q["used"]]
    if not cands:
        return None
    best = next((q for q in cands if _matches(q, hints)), None)
    if best is None and lone and len(cands) == 1 and not cands[0]["strong"]:
        best = cands[0]
    if best is None:
        return None
    best["used"] = True
    if kind in ("number", "count", "percent"):
        return best["v"]
    return _to_si(best["v"], best["unit"], kind) if best["unit"] else _to_si(best["v"], DEFAULT_UNIT.get(kind, ""), kind)


def claim(qs: list[dict], pos: int) -> None:
    """A calculator read this number itself (a regex): nobody else may use it."""
    for q in qs:
        if q["pos"] <= pos < max(q["end"], q["pos"] + 1):
            q["used"] = True


# secondary values the user rarely gives: the small model sometimes makes them up ("safety factor 4" from "4 bolts") —
# its value only counts when the user's words mention one of these
AUTO_GUARD = {
    "safety factor": ["safety", "factor", "sf", "siguran"], "efficiency": ["efficien", "eficien"],
    "pump efficiency": ["efficien", "eficien"], "drive efficiency": ["efficien", "eficien"],
    "friction": ["friction", "mu", "frecare"], "tyre grip": ["grip", "friction", "mu", "aderen"],
    "acceleration": ["accel"], "microsteps": ["microstep"], "motor steps per turn": ["step", "0.9", "1.8"],
    "steps": ["step"], "full steps per turn": ["step", "0.9", "1.8"], "shear planes": ["plane", "double"],
    "discharge coefficient": ["cd", "coefficient", "discharge"], "usable share": ["usable", "dod", "depth of"],
    "temperature": ["°", "temp", "deg", "hot", "cold", "warm", "celsius", "fahrenheit", "grade"],
    "air temperature": ["°", "temp", "ambient", "hot", "cold"], "ambient": ["°", "temp", "ambient"],
    "number of bolts": ["bolt", "screw", "x ", "pcs"],
}


class Inputs:
    """What the calculators read: the AI's fields (any spelling, any unit) first, then the user's words."""

    def __init__(self, values: dict, question: str = ""):
        self.raw: dict[str, tuple] = {}
        for k, v in (values or {}).items():
            if isinstance(v, dict) and "value" in v:  # {"bore": {"value": 50, "unit": "mm"}}
                v = f"{v.get('value', '')} {v.get('unit', '')}".strip()
            nk, unit = norm_key(k)
            if nk and v not in (None, "", [], {}):
                self.raw[nk] = (v, unit)
        self.question = question or ""
        self.qs = quantities(self.question)
        self.assumed: list[str] = []
        self.missing: list[str] = []

    def _raw(self, names):
        for n in names:
            for n2 in (re.sub(r"[^a-z0-9]", "", n.lower()), norm_key(n)[0]):
                if n2 in self.raw:
                    return self.raw[n2]
        return None

    def has(self, *names) -> bool:
        return self._raw(names) is not None

    def num(self, names, kind: str, label: str, default=None, hints=None, unit: str = "", need=False, show: str = "",
            text_ok: bool = True, lone: bool = True):
        """A number in SI. names = field spellings; hints = the words a number in the question belongs to."""
        r = self._raw(names)
        v = None
        hs = list(hints or []) + [n.replace("_", " ") for n in names if len(n) > 2]
        guard = AUTO_GUARD.get(label)
        if r is not None and guard and self.question and not any(g in self.question.lower() for g in guard):
            r = None  # a value the user never mentioned: the default (and saying so) beats a made-up one
        lone = lone and not guard  # and never the one stray number ("30 mc long" became a x30 safety factor)
        if r is not None:
            val, kunit = r
            if isinstance(val, list):
                val = val[0] if val else None
            v = parse(val, kind, kunit or unit or DEFAULT_UNIT.get(kind, ""))
            if v is not None and self.question and text_ok:
                uv = self._user_value(v, kind)
                if uv is not None:
                    v = uv  # the user's number in the user's unit: a bare "30" from the model for "30 cm" is 0.3 m, not 30 mm
                else:
                    mine = next((q for q in self.qs if kind in q["kinds"] and not q["used"] and _matches(q, hs)), None)
                    if mine:  # the user's own number for this field wins over the model's (it mixed in an earlier message)
                        mine["used"] = True
                        v = mine["v"] if kind in ("number", "count", "percent") else \
                            _to_si(mine["v"], mine["unit"] or DEFAULT_UNIT.get(kind, ""), kind)
        if v is None and self.question and text_ok:
            v = from_text(self.qs, self.question, kind, hs, lone)
        if v is None:
            if default is not None:
                self.assumed.append(f"{label} = {show or default}")
                return default
            if need:
                self.missing.append(label)
            return None
        return v

    def _seen(self, v: float, kind: str) -> bool:
        """Is this value (SI) one of the numbers in the user's words? Marks it used so no other field takes it."""
        return self._user_value(v, kind) is not None

    def _user_value(self, v: float, kind: str):
        """The user's own value (SI, in the user's unit) behind a value the model passed — also when the model dropped
        the unit (a bare 30 for "30 cm") — or None. Marks it used so no other field takes it."""
        for q in self.qs:
            if not (kind in q["kinds"] or "number" in q["kinds"]):
                continue
            if kind in ("number", "count", "percent"):
                mine, vals = q["v"], [q["v"]]
            else:
                mine = _to_si(q["v"], q["unit"] or DEFAULT_UNIT.get(kind, ""), kind)
                vals = [mine, _to_si(q["v"], DEFAULT_UNIT.get(kind, ""), kind)]
            if any(x is not None and abs(x - v) <= 0.011 * max(abs(v), 1e-12) for x in vals):
                q["used"] = True
                return mine
        return None

    def text(self, names, default: str = "", words: list[str] | None = None) -> str:
        r = self._raw(names)
        if r is not None and not isinstance(r[0], (dict, list)):
            return str(r[0]).strip().lower()
        low = self.question.lower()
        for w in words or []:
            if re.search(rf"(?<![a-z]){re.escape(w)}", low):
                return w
        return default

    def nums(self, names, kind: str, unit: str = "", hints=None) -> list[float]:
        """A list of numbers ([200, 150], "200, 150 mm", "200 and 150 mm"). With hints: when none of the model's
        numbers is in the user's words but the user gave one for these words, the user's wins (a made-up "50 mm")."""
        out = self._nums(names, kind, unit)
        if not (out and self.question):
            return out
        users = [self._user_value(x, kind) for x in out]
        if hints and all(u is None for u in users):
            mine = next((q for q in self.qs if kind in q["kinds"] and not q["used"] and _matches(q, hints)), None)
            if mine:
                mine["used"] = True
                return [_to_si(mine["v"], mine["unit"] or DEFAULT_UNIT.get(kind, ""), kind)]
        return [u if u is not None else x for u, x in zip(users, out)]

    def _nums(self, names, kind: str, unit: str = "") -> list[float]:
        r = self._raw(names)
        if r is None:
            return []
        val, kunit = r
        items = [str(x) for x in val] if isinstance(val, list) else re.split(r"\s*(?:,|;|\band\b|\+|/)\s*", str(val))
        out, last_unit = [], ""
        for it in reversed([x for x in items if x.strip()]):  # "200, 150 mm": the unit at the end counts for all
            m = re.match(rf"^\s*({NUM})\s*(.*)$", it)
            if not m:
                continue
            last_unit = m.group(2).strip() or last_unit
            out.append(parse(f"{m.group(1)} {last_unit}".strip(), kind, kunit or unit or DEFAULT_UNIT.get(kind, "")))
        return [x for x in reversed(out) if x is not None]


# ------------------------------------------------------------------ showing numbers
def fmt(v, digits: int = 3) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "—"
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1e7 or a < 1e-4:
        return f"{v:.{digits}g}"
    d = max(0, digits - 1 - int(math.floor(math.log10(a))))
    s = f"{v:.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def show(v, kind: str) -> str:
    """SI -> the unit people use for that size."""
    if v is None:
        return "—"
    a = abs(v)
    if kind == "length":
        return f"{fmt(v * 1000)} mm" if a < 1 else f"{fmt(v)} m"
    if kind == "force":
        return f"{fmt(v)} N (≈ {fmt(v / G)} kg)" if a < 1000 else f"{fmt(v / 1000)} kN (≈ {fmt(v / G)} kg)"
    if kind == "torque":
        return f"{fmt(v)} N·m (≈ {fmt(v / G * 100)} kg·cm)"
    if kind == "pressure":
        return f"{fmt(v / 1e5)} bar ({fmt(v / 1e3)} kPa, {fmt(v / 6894.76)} psi)"
    if kind == "stress":
        return f"{fmt(v / 1e6)} MPa"
    if kind == "power":
        return f"{fmt(v)} W" if a < 1000 else f"{fmt(v / 1000)} kW ({fmt(v / 745.7)} hp)"
    if kind == "speed":
        return f"{fmt(v)} m/s ({fmt(v * 3.6)} km/h)" if a >= 0.1 else f"{fmt(v * 1000)} mm/s"
    if kind == "flow":
        return f"{fmt(v * 60000)} l/min ({fmt(v * 3600)} m³/h)"
    if kind == "mass":
        return f"{fmt(v * 1000)} g" if a < 1 else f"{fmt(v)} kg"
    if kind == "time":
        if a < 120:
            return f"{fmt(v)} s"
        if a < 7200:
            return f"{fmt(v / 60)} min"
        if a < 3 * 86400:
            return f"{fmt(v / 3600)} h"
        return f"{fmt(v / 86400)} days"
    if kind == "volume":
        return f"{fmt(v * 1e6)} cm³" if a < 1e-3 else f"{fmt(v * 1000)} l"
    if kind == "energy":
        return f"{fmt(v)} Wh"
    return fmt(v)


def pick_up(v: float, sizes):
    """The first standard size at or above v."""
    return next((s for s in sizes if s >= v - 1e-9), None)


# ------------------------------------------------------------------ materials (typical values for estimates)
# name: density kg/m3, E GPa, yield (or design strength) MPa, tensile MPa, expansion 1e-6/K, Poisson, words, note
MATERIALS = {
    "steel": (7850, 200, 250, 400, 12, 0.3, "steel mild s235 structural carbon iron a36 otel", "mild steel (S235)"),
    "steel s355": (7850, 210, 355, 510, 12, 0.3, "s355 high-strength structural", "structural steel S355"),
    "steel c45": (7850, 210, 430, 650, 11.5, 0.3, "c45 1045 ck45 medium-carbon shaft", "C45 / 1045 shaft steel (normalised)"),
    "steel 42crmo4": (7850, 210, 650, 900, 11.5, 0.3, "42crmo4 4140 alloy chromoly crmo quenched", "42CrMo4 / 4140 (quenched and tempered)"),
    "stainless": (8000, 193, 215, 505, 17.3, 0.29, "stainless inox 304 316 a2 a4 x5crni18", "stainless 304 / 316 (annealed)"),
    "aluminium": (2700, 69, 240, 290, 23.4, 0.33, "aluminium aluminum alu 6061 6082 t6 aluminiu", "aluminium 6061 / 6082-T6"),
    "aluminium 7075": (2810, 71.7, 503, 572, 23.4, 0.33, "7075", "aluminium 7075-T6"),
    "aluminium cast": (2680, 71, 160, 240, 21, 0.33, "cast-aluminium silumin alsi", "cast aluminium (AlSi)"),
    "brass": (8500, 100, 250, 400, 20, 0.34, "brass alama", "brass CuZn39Pb3"),
    "bronze": (8800, 110, 200, 400, 18, 0.34, "bronze bronz", "tin bronze"),
    "copper": (8960, 117, 70, 220, 17, 0.34, "copper cupru", "copper (annealed)"),
    "titanium": (4430, 114, 880, 950, 8.6, 0.34, "titanium titan ti6al4v grade-5", "titanium Ti-6Al-4V"),
    "cast iron": (7200, 100, 140, 200, 11, 0.26, "cast-iron grey gray fonta gjl", "grey cast iron (brittle: no yield)"),
    "pla": (1240, 3.5, 45, 50, 68, 0.36, "pla", "printed PLA (in the layer plane; across layers about half; soft above ~55 °C)"),
    "petg": (1270, 2.1, 40, 48, 60, 0.38, "petg pet-g pet", "printed PETG (across layers about half; soft above ~75 °C)"),
    "abs": (1040, 2.1, 35, 40, 90, 0.35, "abs", "printed ABS (across layers about half; soft above ~95 °C)"),
    "asa": (1070, 2.0, 35, 42, 95, 0.35, "asa", "printed ASA"),
    "nylon": (1140, 2.0, 45, 60, 85, 0.39, "nylon polyamide pa6 pa12 pa", "nylon / PA (dry; weaker when it has taken up water)"),
    "pc": (1200, 2.3, 55, 62, 68, 0.37, "polycarbonate pc", "polycarbonate"),
    "pom": (1410, 2.8, 60, 65, 110, 0.35, "pom acetal delrin", "POM / acetal"),
    "tpu": (1210, 0.026, 8, 35, 150, 0.48, "tpu flexible", "TPU 95A (flexible — not for stiff parts)"),
    "pla cf": (1290, 5.5, 45, 50, 40, 0.35, "pla-cf cf-pla carbon-pla", "printed carbon-filled PLA (stiffer, not stronger)"),
    "acrylic": (1180, 3.2, 60, 70, 75, 0.37, "acrylic pmma plexiglass plexi perspex", "acrylic / PMMA (brittle)"),
    "wood": (500, 11, 24, 80, 5, 0.3, "wood softwood pine spruce fir timber brad molid lemn", "softwood C24 (along the grain)"),
    "oak": (700, 12, 30, 90, 5, 0.3, "oak hardwood beech stejar fag", "hardwood D30 (along the grain)"),
    "plywood": (680, 7, 25, 40, 6, 0.3, "plywood birch ply placaj", "birch plywood (rough)"),
    "mdf": (750, 3.5, 15, 18, 10, 0.25, "mdf fibreboard", "MDF"),
    "carbon": (1600, 100, 600, 1200, 0.5, 0.3, "carbon fibre fiber cf pultruded", "carbon fibre tube (pultruded, along the tube)"),
    "glass": (2500, 70, 30, 40, 9, 0.22, "glass sticla", "glass (brittle)"),
    "concrete": (2400, 30, 3, 3, 12, 0.2, "concrete beton", "concrete (tension ~3 MPa; compression ~30)"),
}


def material(name: str, default: str = "steel"):
    """(key, row) for a material name; FreeCAD's library is asked when it isn't one of the common ones."""
    q = (name or "").lower().strip()
    if not q:
        return default, MATERIALS[default]
    if q in MATERIALS:
        return q, MATERIALS[q]
    best, score = None, 0
    words = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", q)
    for k, row in MATERIALS.items():
        hay = (k + " " + row[6]).split()
        s = sum(3 if w == k else 2 if w in hay else 0 for w in words)
        s += sum(1 for w in words if len(w) > 3 and any(h.startswith(w) for h in hay))
        if s > score:
            best, score = k, s
    if best:
        return best, MATERIALS[best]
    row = _freecad(q)
    if row:
        return q, row
    return default, MATERIALS[default]


def _freecad(q: str):
    try:
        data = json.loads((HERE.parent / "materials" / "materials.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    words = [w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 1]
    rows = [r for r in data["materials"] if words and all(w in r["name"].lower() for w in words)]
    if not rows:
        return None
    r = rows[0]

    def num(k):
        m = re.match(r"\s*([\d.]+(?:e-?\d+)?)", str(r.get(k) or ""))
        return float(m.group(1)) if m else 0.0
    dens, e = num("density"), num("youngsModulus") / 1000
    ys, uts = num("yieldStrength"), num("ultimateTensileStrength")
    alpha = num("thermalExpansionCoefficient")
    alpha = alpha * 1e6 if alpha and alpha < 1e-3 else alpha
    if not dens or not e:
        return None
    return (dens, e, ys or uts * 0.6, uts or ys / 0.6, alpha or 12, num("poissonRatio") or 0.3, q, f"{r['name']} (FreeCAD library)")


class Out:
    """What a calculator answers: lines [label, value], notes, warnings and one-line verdict."""

    def __init__(self):
        self.lines, self.notes, self.warnings, self.verdict = [], [], [], ""

    def add(self, label: str, value: str):
        self.lines.append([label, value])

    def note(self, s: str):
        self.notes.append(s)

    def warn(self, s: str):
        self.warnings.append(s)

    def done(self) -> dict:
        return {"lines": self.lines, "notes": self.notes, "warnings": self.warnings,
                **({"verdict": self.verdict} if self.verdict else {})}
