"""Local AI's Blender plugin (run by the app: run.py <recipe.json> <output folder>).

Security: the AI never sends code. Its recipe is DATA — every field is checked here (shape names from a fixed list,
numbers clamped, colours as #rrggbb, short texts) and only then handed to the app's own fixed Blender script
(bl_runner.py). Blender runs in the background with factory settings (no add-ons, no user preferences), with auto-run
scripts off, and writes only into the output folder.
Prints "PROGRESS: …" lines while it works and one "RESULT: {json}" line at the end."""
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHAPES = {"box", "cylinder", "sphere", "cone", "torus", "text"}
LOOK = ["%ProgramFiles%/Blender Foundation/Blender */blender.exe", "%ProgramFiles(x86)%/Steam/steamapps/common/Blender/blender.exe",
        "%LOCALAPPDATA%/Programs/Blender Foundation/Blender */blender.exe"]


def blender_exe() -> str | None:
    win = os.name == "nt"
    bundled = HERE.parent.parent / "engines" / "blender" / ("blender.exe" if win else "blender")  # inside the app folder
    if bundled.exists():  # the tested version wins over an older one installed on that PC
        return str(bundled)
    if not win:  # Linux: the installer puts Blender in engines/blender; else one on the system
        import shutil
        return shutil.which("blender")
    found = [p for pat in LOOK for p in glob.glob(os.path.expandvars(pat))]
    key = lambda p: [int(x) for x in re.findall(r"\d+", Path(p).parent.name)] or [0]  # noqa: E731 — newest version first
    return sorted(found, key=key, reverse=True)[0] if found else None


def num(v, d: float, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = d
    return min(max(x, lo), hi) if x == x else d


def vec(v, d=(0.0, 0.0, 0.0), lo=-5000.0, hi=5000.0) -> list[float]:
    if isinstance(v, str):
        v = [x for x in re.split(r"[,;\s\[\]]+", v) if x]
    if not isinstance(v, (list, tuple)) or len(v) < 3:
        return list(d)
    return [num(v[i], d[i], lo, hi) for i in range(3)]


def color(v, d: str) -> str:
    v = str(v or "").strip()
    return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else d


def shape_fields(p: dict) -> dict | None:
    s = str(p.get("shape") or "").lower()
    if s not in SHAPES:
        return None
    q = {"shape": s, "location": vec(p.get("location") or p.get("center")), "rotation": vec(p.get("rotation"), lo=-360, hi=360)}
    if s == "box":
        q["size"] = vec(p.get("size"), (20, 20, 20), 0.2, 5000)
    elif s in ("cylinder", "cone"):
        q["radius"] = num(p.get("radius"), 10, 0.1, 2500)
        q["radius2"] = num(p.get("radius2", q["radius"] if s == "cylinder" else 0.01), 0.01, 0.01, 2500)
        q["depth"] = num(p.get("depth") or p.get("height"), 20, 0.1, 5000)
    elif s == "sphere":
        q["radius"] = num(p.get("radius"), 10, 0.1, 2500)
    elif s == "torus":
        q["major"] = num(p.get("major") or p.get("radius"), 20, 0.2, 2500)
        q["minor"] = num(p.get("minor") or p.get("radius2"), 5, 0.1, q["major"])
    elif s == "text":
        q["text"] = re.sub(r"[\x00-\x1f]", "", str(p.get("text") or "Text"))[:40]
        q["font_size"] = num(p.get("font_size"), 20, 1, 1000)
        q["depth"] = num(p.get("depth"), 3, 0.2, 500)
    return q


def clean_part(p: dict, i: int) -> dict | None:
    if not isinstance(p, dict):
        return None
    q = shape_fields(p)
    if not q:
        return None
    q["name"] = re.sub(r"[^\w .\-()]", "", str(p.get("name") or f"part {i + 1}"))[:40] or f"part {i + 1}"
    thin = min(q["size"]) if q["shape"] == "box" else min(q.get("radius", 5), q.get("depth", 10), q.get("minor", 5) * 2)
    q["bevel"] = num(p.get("bevel"), 0, 0, max(0.0, thin * 0.45))
    q["smooth"] = bool(p.get("smooth"))
    q["subdivide"] = int(num(p.get("subdivide"), 0, 0, 2))
    q["cut"] = [c for c in (shape_fields(c) for c in (p.get("cut") or [])[:12] if isinstance(c, dict)) if c and c["shape"] != "text"]
    a = p.get("array") if isinstance(p.get("array"), dict) else {}
    if a:
        q["array"] = {"count": int(num(a.get("count"), 1, 1, 50)), "offset": vec(a.get("offset"), (0, 0, 0))}
    m = str(p.get("mirror") or "").lower()
    q["mirror"] = m if m in ("x", "y", "z") else ""
    q["reference"] = bool(p.get("reference"))
    q["color"] = color(p.get("color"), "#9aa0a6" if q["reference"] else "#c8a27a")
    q["metal"] = num(p.get("metal"), 0, 0, 1)
    q["group"] = re.sub(r"[^\w .\-()]", "", str(p.get("group") or q["name"]))[:40] or q["name"]
    return q


def cabinet(o: dict) -> tuple[list[dict], str]:
    """A parametric cabinet: panels (a cut list), drawers on top (front + open box), doors underneath, handles to buy.
    X = width, Y = depth (the FRONT faces -Y), Z up. 2 mm gaps around drawers and doors, 13 mm for drawer runners."""
    W, H, D = num(o.get("width"), 500, 150, 3000), num(o.get("height"), 500, 150, 3000), num(o.get("depth"), 300, 120, 1500)
    t = num(o.get("board"), 18, 3, 40)
    nd, nt = int(num(o.get("drawers"), 2, 0, 6)), int(num(o.get("doors"), 2, 0, 2))
    wood, dark = color(o.get("color"), "#c8a27a"), color(o.get("handle_color"), "#333333")
    back, g, run = 6.0, 2.0, 13.0
    wi, y0, y1 = W - 2 * t, -D / 2, D / 2 - back            # inside width, front edge, front of the back panel
    box = lambda name, x0, x1, yy0, yy1, z0, z1, **k: {"name": name, "shape": "box", "size": [x1 - x0, yy1 - yy0, z1 - z0],  # noqa: E731
                                                        "location": [(x0 + x1) / 2, (yy0 + yy1) / 2, (z0 + z1) / 2], "color": wood, **k}
    parts = [box("left side", -W / 2, -W / 2 + t, y0, D / 2, 0, H, bevel=1),
             box("right side", W / 2 - t, W / 2, y0, D / 2, 0, H, bevel=1),
             box("top", -W / 2 + t + 0.3, W / 2 - t - 0.3, y0, y1 - 0.3, H - t, H, bevel=1),
             box("bottom", -W / 2 + t + 0.3, W / 2 - t - 0.3, y0, y1 - 0.3, 0, t, bevel=1),
             box("back panel", -W / 2 + t + 0.3, W / 2 - t - 0.3, y1, D / 2, t + 0.3, H - t - 0.3, color="#b8936c")]
    inner0, inner1 = t, H - t
    split = inner1 - (inner1 - inner0) * (0.42 if nt else 1.0) if nd else inner0  # drawers above, doors below
    if nd and nt:
        parts.append(box("shelf", -W / 2 + t + 0.3, W / 2 - t - 0.3, y0 + t + g + 0.5, y1 - 0.3, split - t, split, bevel=1))
        zone_d, zone_t = (split, inner1), (inner0, split - t)
    else:
        zone_d, zone_t = (inner0, inner1), (inner0, inner1)
    if nd:
        hd = (zone_d[1] - zone_d[0]) / nd
        for i in range(nd):
            zb, zt = zone_d[0] + i * hd, zone_d[0] + (i + 1) * hd
            gname = f"drawer {nd - i}"
            parts.append(box(f"{gname} front", -wi / 2 + g, wi / 2 - g, y0, y0 + t, zb + g, zt - g, bevel=1.5, group=gname))
            bh = max(20.0, zt - zb - 2 * g - 20)
            bx0, bx1, by0, by1, bz0 = -wi / 2 + run, wi / 2 - run, y0 + t, y1 - 10, zb + g + 6
            parts.append(box(f"{gname} box", bx0, bx1, by0, by1, bz0, bz0 + bh, group=gname, color="#d8bc98",
                             cut=[{"shape": "box", "size": [bx1 - bx0 - 24, by1 - by0 - 12, bh], "location": [0, (by0 + by1) / 2, bz0 + 6 + bh / 2]}]))
            parts.append({"name": f"{gname} handle (buy)", "shape": "cylinder", "radius": 5, "depth": min(120.0, wi * 0.3),
                          "location": [0, y0 - 0.5 - 6, (zb + zt) / 2], "rotation": [0, 90, 0], "color": dark, "metal": 0.8,
                          "reference": True, "bevel": 1})
    if nt and zone_t[1] - zone_t[0] > 60:
        if not nd:  # doors only: a shelf inside, set back so the doors close
            mid = (zone_t[0] + zone_t[1]) / 2
            parts.append(box("inner shelf", -W / 2 + t + 0.3, W / 2 - t - 0.3, y0 + t + g + 0.5, y1 - 0.3, mid - t / 2, mid + t / 2, bevel=1))
        dw = (wi - (nt + 1) * g) / nt
        for i in range(nt):
            x0 = -wi / 2 + g + i * (dw + g)
            parts.append(box(f"door {i + 1}", x0, x0 + dw, y0, y0 + t, zone_t[0] + g, zone_t[1] - g, bevel=1.5))
            hx = x0 + dw - 30 if (nt == 2 and i == 0) else x0 + 30 if nt == 2 else x0 + dw - 30
            hl = min(160.0, (zone_t[1] - zone_t[0]) * 0.4)
            parts.append({"name": f"door {i + 1} handle (buy)", "shape": "cylinder", "radius": 5, "depth": hl,
                          "location": [hx, y0 - 0.5 - 6, zone_t[1] - g - 40 - hl / 2], "color": dark, "metal": 0.8,
                          "reference": True, "bevel": 1})
    notes = (f"Cabinet {W:g} x {H:g} x {D:g} mm (W x H x D) from {t:g} mm boards, back {back:g} mm. {nd} drawer(s) above, "
             f"{nt} door(s) below. 2 mm gaps around fronts, {run:g} mm each side for drawer runners. Each panel is its own part "
             "(a cut list); handles are to buy. Scale it down in the slicer to print a model.")
    return parts, notes


MEDIA = (HERE.parent.parent / "data" / "media").resolve()


def code_mode(r: dict, out: Path) -> dict:
    """The AI's own Blender Python — ONLY when the user switched "Python code" on (read from the app's settings file,
    which the AI can't change), and only after the app's safety check (app.security.check_code) allowed it."""
    try:
        on = json.loads((HERE.parent.parent / "data" / "settings.json").read_text(encoding="utf-8")).get("python_code") is True
    except (OSError, ValueError):
        on = False
    if not on:
        return {"error": "Python code is switched off (the chat's “Python code” button)"}
    sys.path.insert(0, str(HERE.parent.parent))
    from app.security import check_code
    code = str(r.get("code") or "")
    problems = check_code(code)
    if problems:
        return {"error": "refused by the safety check", "refused": problems}
    exe = blender_exe()
    if not exe:
        return {"error": "Blender isn't installed on this PC"}
    name = re.sub(r"[^\w .\-()]", "", str(r.get("name") or "model"))[:60] or "model"
    f = out / "job.json"
    f.write_text(json.dumps({"name": name, "code": code}), encoding="utf-8")
    res = run_blender(exe, "bl_code.py", f, out, timeout=150)
    res["recipe"] = {"name": name, "engine": "blender", "mode": "code", "code": code}
    return res


def run_blender(exe: str, script: str, recipe_file: Path, out: Path, timeout: float | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PYTHON")}  # Blender's own Python, nothing else
    p = subprocess.Popen([exe, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1",
                          "--python", str(HERE / script), "--", str(recipe_file), str(out)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore",
                         env=env, cwd=str(out), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    import threading
    late = threading.Timer(timeout, p.kill) if timeout else None  # an endless loop in the AI's code ends here
    if late:
        late.start()
    lines = []
    for x in p.stdout:
        if x.startswith("PROGRESS:"):
            print(x.rstrip(), flush=True)
        else:
            lines.append(x.rstrip())
    p.wait()
    if late:
        late.cancel()
        if not late.is_alive() and p.returncode not in (0, None) and not any(x.startswith("RESULT:") for x in lines):
            return {"error": f"the code ran longer than {timeout:.0f} s and was stopped (an endless loop, or far too many parts?)"}
    line = next((x[7:] for x in reversed(lines) if x.startswith("RESULT:")), None)
    return json.loads(line) if line else {"error": "Blender stopped: " + " | ".join(lines[-6:])[-400:]}


def finish(r: dict, out: Path) -> dict:
    """The app's own request (not the AI's): render + GLB for a model PicoGK built. Only STL files in the app's
    media folder are accepted."""
    items = []
    for b in (r.get("bodies") or [])[:60]:
        p = Path(str(b.get("stl") or "")).resolve()
        if p.suffix.lower() != ".stl" or MEDIA not in p.parents or not p.exists():
            continue
        items.append({"name": re.sub(r"[^\w .\-()]", "", str(b.get("name") or p.stem))[:40] or p.stem, "stl": str(p),
                      "color": color(b.get("color"), "#9aa0a6"), "reference": bool(b.get("reference"))})
    if not items:
        return {"error": "no parts to finish"}
    exe = blender_exe()
    if not exe:
        return {"error": "Blender isn't installed on this PC"}
    f = out / "finish.json"
    f.write_text(json.dumps({"name": str(r.get("name") or "model")[:60], "bodies": items}), encoding="utf-8")
    return run_blender(exe, "bl_finish.py", f, out)


def cut(r: dict, out: Path) -> dict:
    """The app's own request: cut the parts that are too big for the printer's plate into pieces that fit (bl_cut.py).
    Only STL files in the app's media folder are accepted; the plate size is clamped to sane numbers."""
    items = []
    for b in (r.get("bodies") or [])[:40]:
        p = Path(str(b.get("stl") or "")).resolve()
        if p.suffix.lower() != ".stl" or MEDIA not in p.parents or not p.exists():
            continue
        items.append({"name": re.sub(r"[^\w .\-()/]", "", str(b.get("name") or p.stem))[:40] or p.stem, "stl": str(p),
                      "color": color(b.get("color"), "#4ad696"), "reference": bool(b.get("reference"))})
    if not items:
        return {"error": "no parts to cut"}
    try:
        bed = [min(2000.0, max(30.0, float(x))) for x in (r.get("bed") or [220, 220, 250])][:3]
    except (TypeError, ValueError):
        bed = [220.0, 220.0, 250.0]
    exe = blender_exe()
    if not exe:
        return {"error": "Blender isn't installed on this PC (it does the cutting)"}
    f = out / "cut.json"
    f.write_text(json.dumps({"name": str(r.get("name") or "model")[:60], "bodies": items, "bed": bed,
                             "margin": 2.0, "pin": "printed" if r.get("pin") == "printed" else "filament"}), encoding="utf-8")
    return run_blender(exe, "bl_cut.py", f, out, timeout=280)


def main() -> None:
    try:
        r = json.load(open(sys.argv[1], encoding="utf-8"))
        if isinstance(r, str):
            r = json.loads(r)
        if r.get("mode") == "finish":
            print("RESULT: " + json.dumps(finish(r, Path(sys.argv[2]))))
            return
        if r.get("mode") == "cut":
            print("RESULT: " + json.dumps(cut(r, Path(sys.argv[2]))))
            return
        if r.get("mode") == "code":
            print("RESULT: " + json.dumps(code_mode(r, Path(sys.argv[2]))))
            return
        name = re.sub(r"[^\w .\-()]", "", str(r.get("name") or "Blender model"))[:60] or "Blender model"
        notes = ""
        if str(r.get("template") or "").lower() == "cabinet":
            raw, notes = cabinet(r.get("options") if isinstance(r.get("options"), dict) else {})
        else:
            raw = r.get("parts")
            if isinstance(raw, str):
                raw = json.loads(raw)
        parts = [q for q in (clean_part(p, i) for i, p in enumerate((raw or [])[:40])) if q]  # the same checks for all
        if not parts:
            raise ValueError("the design has no parts")
        exe = blender_exe()
        if not exe:
            raise ValueError("Blender isn't installed on this PC")
    except Exception as e:  # noqa: BLE001
        print("RESULT: " + json.dumps({"error": str(e)[:300]}))
        return
    out = Path(sys.argv[2])
    recipe = {"name": name, "engine": "blender", "template": r.get("template") or "none", "options": r.get("options") or {},
              "parts": parts, **({"notes": notes} if notes else {})}
    (out / "recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    result = run_blender(exe, "bl_runner.py", out / "recipe.json", out)
    result["recipe"] = recipe
    if notes:
        result["notes"] = notes
    print("RESULT: " + json.dumps(result))


main()
