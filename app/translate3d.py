"""PicoGK design (recipe JSON) -> Blender Python that uses the "Python code" building blocks (bl_code.py).

So the AI can start from a PROVEN PicoGK design and change it as code (the user: "use the data from PicoGK in
Blender by translating it to Python"). PicoGK's cylinders / cones / tubes / extrudes / gears / helixes start at their
`center` and point up +Z; Blender's blocks are centred — so the translation moves each one by half its height along
its own (rotated) axis. Rotations use the same order in both (X, then Y, then Z). Patterns ("repeat") are written out.
Lattices, gyroids and LEAP 71's library shapes have no Blender block: they are listed as skipped."""
import json
import math

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP = {"lattice", "gyroid", "tpms", "curved_pipe", "quasicrystal", "rover_wheel", "heat_exchanger"}


def picogk_template(name: str, options: dict | None = None) -> dict | None:
    """A ready-made PicoGK design as its full recipe (plugins/picogk/templates.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("picogk_templates", ROOT / "plugins" / "picogk" / "templates.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = mod.TEMPLATES.get(name)
    return fn(dict(options or {})) if fn else None


def _rot(v, deg):
    """v turned like PicoGK / Blender: X first, then Y, then Z (degrees)."""
    x, y, z = v
    a, b, c = (math.radians(d) for d in (list(deg) + [0, 0, 0])[:3])
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    x, y = x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c)
    return [x, y, z]


def _n(v) -> str:
    return f"{round(float(v), 3):g}"


def _v(v) -> str:
    return "(" + ", ".join(_n(x) for x in v) + ")"


def _copies(p: dict) -> list[tuple[list, list]]:
    """(center, rotate) of the part and of each "repeat" copy (around the up axis through axis_point, or in a row)."""
    c, r = list(p.get("center") or [0, 0, 0]), list(p.get("rotate") or [0, 0, 0])
    rep = p.get("repeat") if isinstance(p.get("repeat"), dict) else None
    if not rep:
        return [(c, r)]
    n = max(1, min(int(rep.get("count", 1)), 200))
    step = rep.get("step")
    if step and any(step):
        return [([c[i] + step[i] * k for i in range(3)], r) for k in range(n)]
    piv, total = list(rep.get("axis_point") or [0, 0, 0]), float(rep.get("angle", 360))
    out = []
    for k in range(n):
        a = total * k / (n if abs(total - 360) < 0.01 else max(n - 1, 1))
        dx, dy = c[0] - piv[0], c[1] - piv[1]
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
        out.append(([piv[0] + dx * ca - dy * sa, piv[1] + dx * sa + dy * ca, c[2]], [r[0], r[1], r[2] + a]))
    return out


def _expr(p: dict, c: list, r: list) -> str | None:
    """One PicoGK part (one copy) as a Blender building-block call, or None when Blender has no such shape."""
    s, h = p.get("shape"), float(p.get("height") or 0)
    rad, rad2 = float(p.get("radius") or 0), float(p.get("radius2") or 0)
    mid = lambda: [c[i] + d for i, d in enumerate(_rot((0, 0, h / 2), r))]  # noqa: E731 — base point -> centre
    rot = f", rot={_v(r)}" if any(abs(x) > 1e-9 for x in r) else ""
    if s == "box":
        e = f"box({_v(p.get('size') or [10, 10, 10])}, loc={_v(c)}{rot})"
        return f"bevel({e}, {_n(p['round'])})" if p.get("round") else e
    if s == "sphere":
        return f"sphere({_n(rad)}, loc={_v(c)})"
    if s == "cylinder":
        return f"cylinder({_n(rad)}, {_n(h)}, loc={_v(mid())}{rot})"
    if s == "cone":
        return f"cone({_n(rad)}, {_n(rad2)}, {_n(h)}, loc={_v(mid())}{rot})"
    if s == "tube":
        return f"tube({_n(rad)}, {_n(p.get('wall') or 1)}, {_n(h)}, loc={_v(mid())}{rot})"
    if s == "torus":
        return f"torus({_n(rad)}, {_n(rad2)}, loc={_v(c)}{rot})"
    if s == "extrude":
        pts = "[" + ", ".join(f"({_n(x)}, {_n(y)})" for x, y, *_ in p.get("points") or []) + "]"
        return f"extrude({pts}, {_n(h)}, loc={_v(mid())}{rot})"
    if s == "revolve":
        pts = "[" + ", ".join(f"({_n(x)}, {_n(y)})" for x, y, *_ in p.get("points") or []) + "]"
        return f"revolve({pts}, loc={_v(c)}{rot})"
    if s == "gear":
        return (f"gear({int(p.get('teeth') or 20)}, {_n(p.get('module') or 1.5)}, {_n(h)}, bore={_n(p.get('bore') or 0)}, "
                f"loc={_v(mid())}{rot})")
    if s == "helix":
        return f"helix({_n(rad)}, {_n(rad2 or 0.5)}, {_n(h)}, {_n(p.get('turns') or 5)}, loc={_v(mid())}{rot})"
    if s == "rod":
        return f"rod({_v(p.get('from') or [0, 0, 0])}, {_v(p.get('to') or [0, 0, h])}, {_n(rad)}" + \
               ("" if p.get("flat") else ", round_ends=True") + ")"
    return None


def recipe_to_code(recipe: dict) -> tuple[str, list[str]]:
    """-> (Blender Python, the shapes it had to skip)."""
    bodies = recipe.get("bodies") or [{"name": recipe.get("name") or "part", "parts": recipe.get("parts") or []}]
    lines = [f"# Translated from PicoGK's design “{recipe.get('name') or 'design'}” — same sizes, "
             "positions and gaps (mm). Change the numbers or add pieces."]
    skipped: list[str] = []
    for i, b in enumerate(bodies, 1):
        var, made = f"b{i}", False
        lines.append(f"\n# {b.get('name') or f'piece {i}'}" + (" (to buy)" if b.get("reference") else ""))
        for p in b.get("parts") or []:
            op = p.get("op", "add")
            for c, r in (_copies(p) if p.get("shape") != "rod" else [(None, None)]):
                e = _expr(p, c, r) if c is not None else _expr(p, [0, 0, 0], [0, 0, 0])
                if e is None:
                    skipped.append(str(p.get("shape")))
                    continue
                if not made:
                    if op != "add":
                        continue  # nothing to cut from yet
                    lines.append(f"{var} = {e}")
                    made = True
                else:
                    fn = {"add": "join", "subtract": "cut", "intersect": "intersect"}.get(op, "join")
                    lines.append(f"{fn}({var}, {e})")
        if made:
            name = json.dumps(str(b.get("name") or f"piece {i}"))
            lines.append(f"part({var}, {name}" + (", reference=True)" if b.get("reference") else ")"))
    return "\n".join(lines) + "\n", sorted(set(skipped))
