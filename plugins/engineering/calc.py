"""The calculator plugins' runner (engineering, fluids, electronics, airgun): calc.py <input.json> <outdir> <group>.

Input: {"calc": "bolt", "inputs": {...any spelling, any unit...}, "question": "the user's own words"}. The app adds
the question; a value the AI left out is looked for in it. Prints one line "RESULT: {json}" with "calculator": true
(the chat shows it as a card) and a short "text" the AI answers from. Nothing here touches the network or the disk."""
import json
import re
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import airgun  # noqa: E402
import elec  # noqa: E402
import fluids  # noqa: E402
import mech  # noqa: E402
from units import Inputs  # noqa: E402

GROUPS = {"engineering": mech.CALCS, "fluids": fluids.CALCS, "electronics": elec.CALCS, "airgun": airgun.CALCS}
ALL = {k: v for g in GROUPS.values() for k, v in g.items()}
ALIASES = {"bolt_torque": "bolt", "screw": "bolt", "torque_bolt": "bolt", "preload": "bolt", "bolt_strength": "bolt",
           "power_torque": "power", "torque": "power", "power_torque_speed": "power", "gear": "gears", "gear_ratio": "gears",
           "pulley": "belt", "timing_belt": "belt", "lead_screw": "leadscrew", "robot_wheels": "wheels", "vehicle": "wheels",
           "servo": "arm", "servo_torque": "arm", "arm_torque": "arm", "lever": "arm", "deflection": "beam", "shelf": "beam",
           "buckling": "column", "fits": "fit", "tolerance": "fit", "iso_fit": "fit", "printed_fit": "fit",
           "thermal_expansion": "thermal", "expansion": "thermal", "mass": "weight", "impact": "drop", "dc_motor": "motor",
           "e_steps": "esteps", "extruder": "esteps", "rotationdistance": "rotation_distance", "flow_ratio": "flow_calibration",
           "volumetric": "volumetric_flow", "units": "convert", "unit_conversion": "convert",
           "pressure_drop": "pipe_flow", "pressure_loss": "pipe_flow", "head_loss": "pipe_flow", "pipe": "pipe_flow",
           "pipe_diameter": "pipe_size", "hose_size": "pipe_size", "hydraulic_cylinder": "cylinder",
           "pneumatic_cylinder": "cylinder", "nozzle": "orifice", "jet": "orifice", "drain": "tank_drain",
           "buoyancy": "hydrostatic", "pressure_at_depth": "hydrostatic", "compressor": "air_tank", "tank": "air_tank",
           "ohms_law": "ohm", "ohm_law": "ohm", "voltage_divider": "divider", "led_resistor": "led",
           "color_code": "resistor_code", "colour_code": "resistor_code", "eseries": "e_series", "555": "timer555",
           "lm317": "regulator", "ldo": "regulator", "buck": "regulator", "battery_life": "battery", "wire_gauge": "wire",
           "awg": "wire", "track_width": "trace_width", "pcb_trace": "trace_width", "spacing": "clearance",
           "creepage": "clearance", "microstrip": "impedance", "stripline": "impedance", "pad": "attenuator",
           "fuse": "fusing", "op_amp": "opamp", "db": "decibel", "dbm": "decibel",
           "muzzle_energy": "energy", "fpe": "energy", "ballistics": "trajectory", "ballistic": "trajectory",
           "holdover": "trajectory", "chairgun": "trajectory", "mero": "trajectory", "pcp": "pcp_fill", "pcpfill": "pcp_fill",
           "fill": "pcp_fill", "scuba": "pcp_fill"}


def word_score(name: str, q: str) -> int:
    return sum(len(w) for w in ALL[name][2].split() if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", q))


def pick(calc: str, question: str, group: str) -> str | None:
    c = re.sub(r"[^a-z0-9_]", "", str(calc or "").lower().replace(" ", "_").replace("-", "_"))
    chosen = c if c in ALL else ALIASES.get(c) or next((k for k in ALL if c and len(c) > 2 and (k in c or c in k)), None)
    q = question.lower()
    best, score = None, 0
    for name in sorted(ALL, key=lambda n: n not in GROUPS.get(group, {})):
        s = word_score(name, q) + (2 if name in GROUPS.get(group, {}) else 0)
        if s > score:
            best, score = name, s
    if chosen and q.strip() and best and best != chosen and word_score(chosen, q) == 0 and score >= 8:
        return best  # the model picked "motor" for "which servo for my arm": the question's own words win
    return chosen or (best if score > 4 else None)


def render(out: dict) -> str:
    lines = [out.get("title", "")]
    for label, value in out.get("lines", []):
        lines.append(f"- {label}: {value}")
    if out.get("verdict"):
        lines.append("Verdict: " + out["verdict"])
    for w in out.get("warnings", []):
        lines.append("Warning: " + w)
    for n in out.get("notes", []):
        lines.append("Note: " + n)
    if out.get("assumed"):
        lines.append("Assumed (not given): " + "; ".join(out["assumed"]))
    if out.get("missing"):
        lines.append("STILL NEEDED to calculate: " + "; ".join(out["missing"]))
    return "\n".join(x for x in lines if x)


def main(group: str = "engineering") -> None:
    try:
        p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        p = {}
    question = str(p.get("question") or p.get("request") or p.get("__request") or "")
    values = p.get("inputs") or p.get("values") or p.get("parameters") or {}
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except ValueError:
            question, values = (question + " " + values).strip(), {}
    if not isinstance(values, dict):
        values = {}
    flat = {k: v for k, v in p.items() if k not in ("calc", "calculator", "question", "request", "inputs", "values",
                                                     "parameters", "__request", "expand_only", "name")}
    values = {**flat, **values}
    name = pick(str(p.get("calc") or p.get("calculator") or ""), question, group)
    if not name:
        listing = ", ".join(f"{k} ({v[1]})" for k, v in GROUPS.get(group, ALL).items())
        out = {"calculator": True, "error": "no calculator matched the question", "calculators": listing,
               "text": "No calculator matched. Available: " + listing}
    else:
        fn, title, _ = ALL[name]
        inp = Inputs(values, question)
        try:
            res = fn(inp)
        except Exception as e:  # noqa: BLE001 — a calculator bug becomes a message, never a crash
            res = {"lines": [], "warnings": [f"the calculation failed ({type(e).__name__}: {e})"],
                   "trace": traceback.format_exc(limit=3)[-600:]}
        out = {"calculator": True, "calc": name, "group": next((g for g, c in GROUPS.items() if name in c), group),
               "title": title, **res}
        if inp.missing:
            out["missing"] = list(dict.fromkeys(inp.missing))
        if inp.assumed:
            out["assumed"] = list(dict.fromkeys(inp.assumed))
        out["text"] = render(out)
    print("RESULT: " + json.dumps(out))  # ASCII-escaped: Windows pipes aren't UTF-8


if __name__ == "__main__":
    main(sys.argv[3] if len(sys.argv) > 3 else "engineering")
