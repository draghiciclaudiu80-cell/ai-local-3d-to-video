"""Robot arm calculations with Peter Corke's Robotics Toolbox for Python (MIT licence), run in its own venv
(engines/robotics/venv): reach and workspace, joint angles for a point (inverse kinematics), where the tool is for
given angles (forward kinematics), joint torques with the servo / stepper to use, and a move animation (GIF).

Arms: a hobby arm from its link lengths (turntable + shoulder / elbow / wrist joints, servo range ±90° unless told) or
one of the toolbox's ready models (UR3/5/10, Panda, Puma560, KR5, IRB140, AL5D, Orion5, Jaco, Mico, Cobra600…).
rtb_run.py <input.json> <outdir>. Prints "RESULT: {json}" shaped like a calculator card (+ "image")."""
import json
import math
import os
import re
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "stubs"))  # xacrodoc stand-in (ROS URDF models aren't used)
sys.path.insert(0, str(HERE.parent / "engineering"))  # units: "200 mm", "0.1 kg"...
os.environ.setdefault("MPLBACKEND", "Agg")
warnings.filterwarnings("ignore")

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import roboticstoolbox as rtb  # noqa: E402
from spatialmath import SE3  # noqa: E402
from units import Inputs, fmt, parse  # noqa: E402

G = 9.80665
SERVOS = [("SG90 (plastic gears)", 1.8, 9), ("MG90S (metal gears)", 2.2, 13.4), ("MG92B", 3.5, 13.8),
          ("Hitec HS-311", 3.7, 43), ("MG995", 10, 55), ("MG996R (6 V)", 11, 55), ("DS3218 (6.8 V)", 21.5, 60),
          ("STS3215 (7.4 V)", 19.5, 55), ("DS3225 (6.8 V)", 25, 60), ("DS3235 (6.8 V)", 35, 65)]  # kg·cm stall, g
STEPPERS = [("NEMA 17, 40 mm long", 0.40), ("NEMA 17, 48 mm", 0.55), ("NEMA 23, 56 mm", 1.26),
            ("NEMA 17 + 5:1 planetary", 2.0), ("NEMA 23, 76 mm", 1.9), ("NEMA 17 + 27:1 planetary", 5.0)]  # N·m
MODELS = {"ur10": "UR10", "ur3": "UR3", "ur5": "UR5", "panda": "Panda", "franka": "Panda", "puma560": "Puma560",
          "puma": "Puma560", "kr5": "KR5", "kuka": "KR5", "irb140": "IRB140", "abb": "IRB140", "al5d": "AL5D",
          "lynxmotion": "AL5D", "orion5": "Orion5", "orion": "Orion5", "jaco": "Jaco", "mico": "Mico",
          "cobra600": "Cobra600", "cobra": "Cobra600", "sawyer": "Sawyer", "lwr4": "LWR4", "lwr": "LWR4",
          "stanford": "Stanford", "planar3": "Planar3", "planar2": "Planar2", "twolink": "TwoLink"}


class Card:
    def __init__(self, title):
        self.title, self.lines, self.notes, self.warnings, self.assumed, self.missing = title, [], [], [], [], []
        self.verdict, self.image = "", None

    def add(self, k, v):
        self.lines.append([k, v])


def length(v, default=None, card=None, label=""):
    x = parse(v, "length", "mm") if v not in (None, "", []) else None
    if x is None and default is not None and card is not None:
        card.assumed.append(f"{label} = {fmt(default * 1000)} mm")
    return default if x is None else x


def mass(v, default=None):
    if v in (None, "", []):
        return default
    if isinstance(v, (int, float)):
        return v / 1000 if v > 5 else v  # a bare number: grams if it's big ("100"), kg if small ("0.2")
    x = parse(v, "mass", "g")
    return default if x is None else x


def numbers(v) -> list:
    if v in (None, "", []):
        return []
    if isinstance(v, (int, float)):
        return [float(v)]
    if isinstance(v, list):
        return [float(re.match(r"\s*(-?\d+(?:[.,]\d+)?)", str(x)).group(1).replace(",", ".")) for x in v
                if re.match(r"\s*-?\d", str(x))]
    return [float(x.replace(",", ".")) for x in re.findall(r"-?\d+(?:[.,]\d+)?", str(v))]


def lengths(v) -> list:
    """[200, 150] / "200, 150 mm" / ["20 cm", "15 cm"] -> metres."""
    if isinstance(v, list) and any(isinstance(x, str) and re.search(r"[a-z]", x) for x in v):
        return [x for x in (parse(x, "length", "mm") for x in v) if x]
    unit = (re.search(r"(mm|cm|m|in)\b", str(v)) or [None, "mm"])[1] if not isinstance(v, list) else "mm"
    return [parse(f"{n} {unit}", "length") for n in numbers(v)]


def point(v, card):
    """"250, 0, 100 mm" / [250, 0, 100] / {"x":..} / "250 mm forward and 100 mm up" -> [x, y, z] in metres."""
    if isinstance(v, dict):
        return [length(v.get(k), 0.0) for k in ("x", "y", "z")]
    s = str(v or "")
    words = {"x": r"(?:forward|front|away|out|ahead|reach|distance|in front)", "y": r"(?:left|right|side|sideways)",
             "z": r"(?:up|high|height|above|tall|down|below)"}
    found = {}
    for ax, w in words.items():
        m = re.search(rf"(-?\d+(?:[.,]\d+)?)\s*(mm|cm|m|in)?\s*(?:to the |the )?{w}|{w}\s*(?:of|:|=)?\s*(-?\d+(?:[.,]\d+)?)\s*(mm|cm|m|in)?", s, re.I)
        if m:
            val = parse(f"{m.group(1) or m.group(3)} {m.group(2) or m.group(4) or 'mm'}", "length")
            if re.search(r"down|below|right", m.group(0), re.I):
                val = -val
            found[ax] = val
    if found:
        return [found.get("x", 0.0), found.get("y", 0.0), found.get("z", 0.0)]
    ns = numbers(v)
    unit = (re.search(r"(mm|cm|m|in)\b", s) or [None, "mm"])[1]
    if len(ns) >= 3:
        return [parse(f"{n} {unit}", "length") for n in ns[:3]]
    if len(ns) == 2:
        return [parse(f"{ns[0]} {unit}", "length"), 0.0, parse(f"{ns[1]} {unit}", "length")]
    return None


def build(p, card):
    """The arm: a toolbox model by name, or a hobby arm from its link lengths. -> (robot, description, custom?)"""
    name = re.sub(r"[\s\-_]", "", str(p.get("robot") or "").lower())
    key = next((k for k in MODELS if k in name), None)
    if key:
        robot = getattr(rtb.models.DH, MODELS[key])()
        return robot, f"{robot.name} ({robot.manufacturer or 'toolbox model'}, {robot.n} joints)", False
    links = lengths(p.get("links") or p.get("link_lengths") or p.get("lengths"))
    if not links:
        one = length(p.get("length") or p.get("arm_length"))
        links = [one] if one else []
    if not links:
        card.missing.append("the arm's link lengths (e.g. 200 and 150 mm) or a robot name (UR5, Panda…)")
        return None, "", True
    base = length(p.get("base_height"), 0.08, card, "base height (turntable to shoulder)")
    span = numbers(p.get("range") or p.get("servo_range"))
    half = math.radians((span[0] if span else 180) / 2)
    if not span:
        card.assumed.append("every joint turns ±90° (a 180° servo)")
    turntable = str(p.get("base_rotation", "yes")).lower() not in ("no", "false", "0", "none")
    lm = [mass(x) for x in (p.get("link_masses") or p.get("masses") or [])]
    lm = [x for x in lm if x is not None]
    if not lm:
        lm = [L * 100 * 1.25 / 1000 for L in links]  # printed PLA link ~1.25 g per cm
        card.assumed.append("printed links weigh ~1.25 g per cm")
    lm = (lm + [lm[-1]] * len(links))[:len(links)]
    jm = [mass(x) for x in (p.get("joint_masses") or p.get("servo_masses") or [])]
    jm = [x for x in jm if x is not None]
    payload = mass(p.get("payload"), 0.0)
    joints = []
    if turntable:
        joints.append(rtb.RevoluteDH(d=base, alpha=math.pi / 2, qlim=[-half, half], m=0.0, r=[0, 0, 0]))
    for i, L in enumerate(links):
        m_link = lm[i]
        x_com = -L / 2 * m_link  # standard DH: the link's frame sits at its far end -> its middle is at -L/2
        m_tot = m_link
        if i + 1 < len(links) and i + 1 < len(jm):  # the next joint's servo sits at this link's end
            m_tot += jm[i + 1]
        if i == len(links) - 1 and payload:
            m_tot += payload  # the load at the tool (the frame origin)
        r = [x_com / m_tot if m_tot else 0.0, 0, 0]
        joints.append(rtb.RevoluteDH(a=L, d=0 if turntable or i else base, alpha=0, qlim=[-half, half], m=m_tot, r=r))
    robot = rtb.DHRobot(joints, name="your arm", gravity=[0, 0, -G])
    desc = (f"{'turntable + ' if turntable else ''}{len(links)} links {', '.join(fmt(L * 1000) + ' mm' for L in links)}"
            f", shoulder {fmt(base * 1000)} mm up, payload {fmt(payload * 1000)} g")
    return robot, desc, True


def pose_png(robot, q, path, title):
    try:
        env = robot.plot(np.array(q, dtype=float), backend="pyplot", block=False)
        plt.gcf().suptitle(title, fontsize=11)
        plt.savefig(path, dpi=110)
        plt.close("all")
        return str(path)
    except Exception:  # noqa: BLE001 — a picture is a bonus
        plt.close("all")
        return None


def stretched(robot, custom):
    """The worst case for gravity: every link held straight out sideways."""
    q = np.zeros(robot.n)
    if not custom:
        q = robot.qz if hasattr(robot, "qz") else q
    return q


def servo_for(t_nm, sf):
    need = t_nm * sf / G * 100
    s = next((f"{n} ({k} kg·cm)" for n, k, _ in SERVOS if k >= need), None)
    st = next((f"{n} ({k} N·m)" for n, k in STEPPERS if k >= t_nm * sf), None)
    return need, s, st


def task_torque(robot, custom, p, card):
    sf = float((numbers(p.get("safety_factor")) or [2])[0])
    q = stretched(robot, custom)
    if not any(float(lk.m or 0) for lk in robot.links):
        card.notes.append(f"The {robot.name} model has no mass data, so its joint torques can't be worked out here.")
        return
    tau = np.abs(robot.gravload(q))
    first = 1 if custom and robot.links[0].alpha else 0  # the turntable carries no gravity torque
    for j in range(first, robot.n):
        need, servo, step = servo_for(float(tau[j]), sf)
        card.add(f"Joint {j + 1}" + (" (shoulder)" if j == first else ""),
                 f"{fmt(float(tau[j]))} N·m = {fmt(float(tau[j]) / G * 100)} kg·cm held straight out → ×{fmt(sf)}: {fmt(need)} kg·cm"
                 + (f"; servo: {servo}" if servo else "; too much for a hobby servo") + (f"; stepper: {step}" if step and not servo else ""))
    shoulder = float(tau[first]) if robot.n > first else 0
    card.verdict = (f"The shoulder needs {fmt(shoulder / G * 100)} kg·cm to hold the arm straight out "
                    f"({fmt(shoulder * sf / G * 100)} kg·cm with a ×{fmt(sf)} margin).")
    card.notes.append("Worst case = the arm held straight out. Moving fast needs more (inertia); servos last longer below ~50 % of stall.")


def task_reach(robot, p, card, out):
    n = 4000
    lo, hi = robot.qlim[0], robot.qlim[1]
    lo = np.where(np.isfinite(lo), lo, -math.pi)
    hi = np.where(np.isfinite(hi), hi, math.pi)
    Q = np.random.default_rng(1).uniform(lo, hi, (n, robot.n))
    pts = np.array([robot.fkine(q).t for q in Q])
    r = np.hypot(pts[:, 0], pts[:, 1])
    card.add("Farthest reach", f"{fmt(r.max() * 1000)} mm out from the base axis")
    card.add("Height range", f"{fmt(pts[:, 2].min() * 1000)} … {fmt(pts[:, 2].max() * 1000)} mm (base = 0)")
    card.add("Reach at table height (z ≈ 0)", f"{fmt(r[np.abs(pts[:, 2]) < 0.01].max() * 1000) if (np.abs(pts[:, 2]) < 0.01).any() else '—'} mm")
    fig, ax = plt.subplots(1, 2, figsize=(9, 4))
    ax[0].scatter(r * 1000, pts[:, 2] * 1000, s=1, alpha=0.35, color="#1f9254")
    ax[0].set_title("Side view: where the tool can be")
    ax[0].set_xlabel("out from the base (mm)")
    ax[0].set_ylabel("height (mm)")
    ax[0].set_aspect("equal")
    ax[1].scatter(pts[:, 0] * 1000, pts[:, 1] * 1000, s=1, alpha=0.35, color="#5a9bd5")
    ax[1].set_title("Top view")
    ax[1].set_xlabel("x (mm)")
    ax[1].set_ylabel("y (mm)")
    ax[1].set_aspect("equal")
    fig.tight_layout()
    path = out / "workspace.png"
    fig.savefig(path, dpi=110)
    plt.close("all")
    card.image = str(path)


def solve_ik(robot, target):
    best = None
    rng = np.random.default_rng(3)
    lo, hi = robot.qlim[0], robot.qlim[1]
    lo = np.where(np.isfinite(lo), lo, -math.pi)
    hi = np.where(np.isfinite(hi), hi, math.pi)
    seeds = [np.zeros(robot.n)] + [rng.uniform(lo, hi) for _ in range(30)]
    for q0 in seeds:
        sol = robot.ikine_LM(SE3(*target), q0=q0, mask=[1, 1, 1, 0, 0, 0], joint_limits=True, ilimit=60, slimit=1)
        err = float(np.linalg.norm(robot.fkine(sol.q).t - np.array(target)))
        inside = bool(np.all(sol.q >= lo - 1e-6) and np.all(sol.q <= hi + 1e-6))
        if best is None or (inside, -err) > (best[2], -best[1]):
            best = (sol.q, err, inside)
        if inside and err < 1e-4:
            break
    return best


def task_ik(robot, p, card, out, custom=True):
    target = point(p.get("target") or p.get("point") or p.get("to"), card)
    if not target:
        card.missing.append("the point to reach (e.g. 250 mm forward, 100 mm up — or x, y, z in mm)")
        return None
    q, err, inside = solve_ik(robot, target)
    deg = np.degrees(q)
    card.add("Target", f"x {fmt(target[0] * 1000)}, y {fmt(target[1] * 1000)}, z {fmt(target[2] * 1000)} mm")
    ok = err < 0.002 and inside
    if ok:
        card.add("Joint angles", ", ".join(f"J{i + 1} {d:+.1f}°" for i, d in enumerate(deg)))
        if custom:
            card.add("Servo positions (0–180°, 90 = middle)", ", ".join(f"{d + 90:.0f}°" for d in deg))
        card.verdict = f"It reaches it (within {fmt(err * 1000, 2)} mm)."
    else:
        card.verdict = (f"It can't reach that point: the closest it gets is {fmt(err * 1000)} mm away"
                        + ("" if inside else " (and only by turning a joint past its limit)") + ".")
    card.image = pose_png(robot, q, out / "pose.png", "reaching the point" if ok else "as close as it gets")
    return q if ok else None


def task_fk(robot, p, card, out):
    ang = numbers(p.get("angles") or p.get("joint_angles"))
    if len(ang) < robot.n:
        card.missing.append(f"{robot.n} joint angles in degrees")
        return
    q = np.radians(ang[:robot.n])
    t = robot.fkine(q).t
    card.add("Joint angles", ", ".join(f"J{i + 1} {a:+.1f}°" for i, a in enumerate(ang[:robot.n])))
    card.add("Tool position", f"x {fmt(t[0] * 1000)}, y {fmt(t[1] * 1000)}, z {fmt(t[2] * 1000)} mm")
    card.image = pose_png(robot, q, out / "pose.png", "at these angles")


def task_move(robot, p, card, out):
    a = numbers(p.get("from_angles") or p.get("start_angles"))
    q0 = np.radians(a[:robot.n]) if len(a) >= robot.n else np.zeros(robot.n)
    if len(a) < robot.n:
        card.assumed.append("starts from the middle position (all joints 0°)")
    b = numbers(p.get("to_angles") or p.get("end_angles"))
    if len(b) >= robot.n:
        q1 = np.radians(b[:robot.n])
    else:
        target = point(p.get("target") or p.get("to") or p.get("point"), card)
        if not target:
            card.missing.append("where to move to (a point in mm, or the end joint angles)")
            return
        q1, err, inside = solve_ik(robot, target)
        if err > 0.002:
            card.warnings.append(f"The end point is out of reach (closest {fmt(err * 1000)} mm) — showing the closest pose.")
        elif not inside:
            card.warnings.append("Reaching that point needs a joint past its limit (±90° servo) — a 270° servo or a different pose would do it.")
    dur = parse(p.get("duration"), "time", "s") or 2.0
    steps = 30
    traj = rtb.jtraj(q0, q1, steps)
    path = out / "move.gif"
    try:
        robot.plot(traj.q, backend="pyplot", movie=str(path), dt=dur / steps)
        plt.close("all")
        card.image = str(path)
    except Exception as e:  # noqa: BLE001
        plt.close("all")
        card.warnings.append(f"The animation couldn't be made ({type(e).__name__}).")
    speed = np.degrees(np.abs(traj.qd).max(axis=0)) * steps / dur / (steps - 1)
    card.add("Move", f"{fmt(dur)} s, smooth start and stop (joint-space)")
    card.add("Fastest joint speed", ", ".join(f"J{i + 1} {s:.0f}°/s" for i, s in enumerate(speed)))
    card.notes.append("Hobby servos turn ~60° in 0.1–0.2 s with no load (≈ 300–600 °/s); keep well below that when carrying something.")


def from_words(p: dict) -> dict:
    """The user's own words fix what the small model got wrong (it picked "reach" for "which servos for 300 g?",
    left the payload out, invented "base height 0 mm")."""
    q = str(p.get("question") or "")
    low = q.lower()
    if not low:
        return p
    p = dict(p)
    tgt = point(q, None) if re.search(r"\b(forward|front|away|ahead|up|high|left|right|down)\b", low) and re.search(r"\d", low) else None
    if tgt:
        p["target"] = q
    if re.search(r"\banimat\w*|\bmov(?:e|es|ing)\b|\bshow\b.{0,30}\bgo(?:ing)? to\b", low):
        p["task"] = "move"
    elif re.search(r"\b(servos?|motors?|steppers?|torque|strong enough|holds?|carr(?:y|ies|ying)|lifts?|lifting|payload)\b", low):
        p["task"] = "check"
    elif tgt and re.search(r"\b(reach|get to|touch|angles?|point|position)\b", low):
        p["task"] = "ik"
    elif re.search(r"\b(workspace|how far|range|area)\b", low):
        p["task"] = "reach"
    inp = Inputs({}, q)
    pay = inp.num(["payload"], "mass", "payload", hints=["carries", "carry", "carrying", "payload", "lift", "lifts", "lifting",
                                                         "holds", "hold", "load", "weighs", "weight", "with"], lone=True)
    if pay:
        p["payload"] = f"{pay * 1000:g} g"
    if not re.search(r"\b(base|shoulder|turntable|height|tall|high up)\b", low) and not re.search(r"\bbase\b", str(p.get("base_height", ""))):
        p.pop("base_height", None)  # not said: the default (and saying so) beats a made-up "0 mm"
    return p


def main():
    p = from_words(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    out = Path(sys.argv[2])
    task = str(p.get("task") or "check").lower()
    card = Card({"check": "Robot arm check", "reach": "Robot arm reach", "ik": "Joint angles for a point",
                 "fk": "Where the tool is", "torque": "Robot arm torques and servos", "move": "Robot arm move"}.get(task, "Robot arm"))
    robot, desc, custom = build(p, card)
    if robot is not None:
        card.add("Arm", desc)
        if task == "reach":
            task_reach(robot, p, card, out)
        elif task == "ik":
            task_ik(robot, p, card, out, custom)
        elif task == "fk":
            task_fk(robot, p, card, out)
        elif task == "torque":
            task_torque(robot, custom, p, card)
            card.image = pose_png(robot, stretched(robot, custom), out / "pose.png", "held straight out (worst case)")
        elif task == "move":
            task_move(robot, p, card, out)
        else:  # check: torques, plus the point if one was given
            task_torque(robot, custom, p, card)
            if p.get("target") or p.get("point"):
                v = card.verdict
                task_ik(robot, p, card, out, custom)
                card.verdict = (card.verdict + " " + v).strip()
            else:
                card.image = pose_png(robot, stretched(robot, custom), out / "pose.png", "held straight out (worst case)")
    res = {"calculator": True, "group": "robotics", "calc": task, "title": card.title, "lines": card.lines,
           "notes": card.notes, "warnings": card.warnings, **({"verdict": card.verdict} if card.verdict else {}),
           **({"assumed": card.assumed} if card.assumed else {}), **({"missing": card.missing} if card.missing else {}),
           "name": f"{card.title}: {desc}"[:80]}
    if card.image and Path(card.image).exists():
        res["image"] = card.image
    lines = [card.title] + [f"- {k}: {v}" for k, v in card.lines] + ([f"Verdict: {card.verdict}"] if card.verdict else [])
    lines += [f"Warning: {w}" for w in card.warnings] + [f"Note: {n}" for n in card.notes]
    if card.assumed:
        lines.append("Assumed: " + "; ".join(card.assumed))
    if card.missing:
        lines.append("STILL NEEDED: " + "; ".join(card.missing))
    res["text"] = "\n".join(lines)
    print("RESULT: " + json.dumps(res))


if __name__ == "__main__":
    main()
