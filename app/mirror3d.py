"""⇋ Mirror for designs (the same math as Create › 3D's ⇋ Mirror, app/static/edit3d.js mirrored()): a part / hole /
whole body flipped across the plane through P square to the world axis k (0 = X: left <-> right, 1 = Y: front <-> back,
2 = Z: up <-> down) — a left hand from a right hand. A mirror isn't a turn, so a shape gets the turn S·R·D, where D flips
it across one of its own planes of symmetry (boxes, cylinders, cones, tubes, gears, spheres are symmetric; an outline's
points are flipped instead). Springs and threads keep their hand (bought / standard)."""
import copy
import math

D2R = math.pi / 180


def _r3(x: float) -> float:
    return math.floor(float(x) * 1000 + 0.5) / 1000 + 0.0  # like JS Math.round: the same numbers as the editor


def _mul(A, B):
    return [[sum(A[i][t] * B[t][j] for t in range(3)) for j in range(3)] for i in range(3)]


def _mv(M, v):
    return [M[i][0] * v[0] + M[i][1] * v[1] + M[i][2] * v[2] for i in range(3)]


def rot_mat(deg) -> list:
    """Turns as 3x3 matrices (rows): X first, then Y, then Z — like the engines."""
    a, b, c = ((float(x or 0) * D2R) for x in (list(deg or []) + [0, 0, 0])[:3])
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return _mul([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]], _mul([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]], [[1, 0, 0], [0, ca, -sa], [0, sa, ca]]))


def mat_deg(M) -> list:
    b = math.asin(max(-1.0, min(1.0, -M[2][0])))
    if abs(M[2][0]) > 0.99999:
        return [0.0, _r3(b / D2R), _r3(math.atan2(-M[0][1], M[1][1]) / D2R)]
    return [_r3(math.atan2(M[2][1], M[2][2]) / D2R), _r3(b / D2R), _r3(math.atan2(M[1][0], M[0][0]) / D2R)]


def mirrored(q: dict, kind: str, k: int, P, fc: bool) -> dict:
    S = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    S[k][k] = -1

    def ref(p):
        p = [float(x or 0) for x in (list(p or []) + [0, 0, 0])[:3]]
        return [_r3(P[i] + _mv(S, [p[j] - P[j] for j in range(3)])[i]) for i in range(3)]

    if kind == "body":
        out = {**q, "parts": [mirrored(p, "part", k, P, fc) for p in q.get("parts") or [] if isinstance(p, dict)]}
        if q.get("holes"):
            out["holes"] = [mirrored(h, "hole", k, P, fc) for h in q["holes"] if isinstance(h, dict)]
        return out
    if kind == "hole":
        d = _mv(S, [float(x or 0) for x in (list(q.get("dir") or [0, 0, -1]) + [0, 0, 0])[:3]])
        n = math.sqrt(sum(x * x for x in d)) or 1.0
        return {**q, "at": ref(q.get("at") or [0, 0, 0]), "dir": [_r3(x / n) for x in d]}
    if q.get("shape") == "rod":
        return {**q, "from": ref(q.get("from") or [0, 0, 0]), "to": ref(q.get("to") or [0, 0, 20])}
    if q.get("shape") == "curved_pipe":
        return {**q, "points": [ref(p) for p in q.get("points") or []]}
    flip_y = fc and q.get("axis") == "x" and q.get("shape") in ("cylinder", "cone", "tube")  # a plane its axis lies in
    D = [[1, 0, 0], [0, -1, 0], [0, 0, 1]] if flip_y else [[-1, 0, 0], [0, 1, 0], [0, 0, 1]]
    out = {**q, "center": ref(q.get("center") or [0, 0, 0]), "rotate": mat_deg(_mul(_mul(S, rot_mat(q.get("rotate"))), D))}
    if isinstance(q.get("points"), list) and q.get("shape") in ("extrude", "polygon"):  # the outline flipped, same winding
        pts = [list(p) for p in q["points"] if isinstance(p, (list, tuple)) and len(p) >= 2]
        out["points"] = [([p[0], _r3(-float(p[1])), *p[2:]] if flip_y else [_r3(-float(p[0])), p[1], *p[2:]]) for p in pts][::-1]
    if isinstance(q.get("repeat"), dict):
        rep = dict(q["repeat"])
        step = rep.get("step")
        if isinstance(step, list) and any(float(x or 0) for x in step):
            rep["step"] = [_r3(x) for x in _mv(S, [float(x or 0) for x in (step + [0, 0, 0])[:3]])]
        else:
            rep["axis_point"] = ref(rep.get("axis_point") or [0, 0, 0])
            a = float(rep.get("angle", 360) or 360)
            if k != 2 and abs(abs(a) - 360) > 0.01:
                rep["angle"] = _r3(-a)  # copies around Z now go the other way
        out["repeat"] = rep
    return out


def mirror_recipe(recipe: dict, k: int, P) -> dict | None:
    """A whole design mirrored (bodies, shapes, holes). None when it has no parts to mirror (a template saved short,
    Blender code, a cut / mirrored mesh)."""
    if not isinstance(recipe, dict) or recipe.get("mode") in ("code", "cut", "mirror") or \
            recipe.get("engine") not in (None, "", "picogk", "freecad"):
        return None
    r = copy.deepcopy(recipe)
    bodies = r.get("bodies") or ([{"name": r.get("name") or "part", **{x: r.get(x) for x in ("parts", "holes", "hollow", "smooth")}}]
                                 if r.get("parts") else [])
    if not bodies:
        return None
    fc = r.get("engine") == "freecad"
    r["bodies"] = [mirrored({k2: v for k2, v in b.items() if v is not None}, "body", k, P, fc) for b in bodies if isinstance(b, dict)]
    for key in ("parts", "holes", "hollow", "smooth", "template", "options"):  # all in bodies now: no template to expand again
        r.pop(key, None)
    return r
