"""Slicing for the user's own 3D printer — offline. OrcaSlicer's command line (free software, AGPL: the copy installed
on this PC, or the app's own in engines/orcaslicer) does the slicing; the printer's settings live IN the app
(app/printers/<printer>.json: OrcaSlicer's tested profiles with every "inherits" merged — tools/make_printer_profile.py),
so there is no account, no first-run login and no internet involved. Gives G-code for the printer's SD card and a 3MF
project that opens in Creality Print / OrcaSlicer. The printer's limits (nozzle / bed temperature) always win."""
import json
import math
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from . import plugins, wipe
from .config import DATA, ENGINES, MEDIA, NO_WINDOW, load_settings
from .plat import IS_WIN, kill_tree, spawn

PRINTERS = Path(__file__).resolve().parent / "printers"
TIMEOUT = 1200  # a big device on fine layers takes minutes


def orca() -> list[str] | None:
    """OrcaSlicer's program: the app's own copy, then one installed on this PC."""
    own = ENGINES / "orcaslicer"
    if IS_WIN:
        for c in (own / "orca-slicer.exe", Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "OrcaSlicer" / "orca-slicer.exe",
                  Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OrcaSlicer" / "orca-slicer.exe"):
            if c.is_file():
                return [str(c)]
        return None
    if (own / "AppRun").exists():  # Linux: the AppImage unpacked by install.sh
        return [str(own / "AppRun")]
    hit = shutil.which("orca-slicer") or shutil.which("OrcaSlicer")
    return [hit] if hit else None


def printer(pid: str | None = None) -> dict:
    """The chosen printer's full profile (built-in, from OrcaSlicer's library, or a custom plate) — printer_profiles."""
    from . import printer_profiles
    return printer_profiles.load(pid)


def info() -> dict:
    """What the print window shows: the printer, its plate, the choices, and whether the slicer is here."""
    p = printer()
    return {"id": p["id"], "name": p["name"], "bed": p["bed"], "nozzle": p["nozzle"], "limits": p.get("limits", {}),
            "custom": bool(p.get("custom")),
            "qualities": list(p["quality"]), "materials": list(p["material"]), "default_quality": p["default_quality"],
            "default_material": p["default_material"], "slicer": bool(orca())}


def stl_size(path: Path) -> list[float]:
    t = plugins.read_stl(path).reshape(-1, 3)
    return [float(x) for x in t.max(0) - t.min(0)] if len(t) else [0.0, 0.0, 0.0]


def too_big(sizes: list[tuple[str, list[float]]], bed: list[float]) -> list[str]:
    """Parts that can't go on the plate (turning them flat on the plate is allowed: x / y may swap)."""
    return [f"“{name}” is {x:.0f} × {y:.0f} × {z:.0f} mm" for name, (x, y, z) in sizes
            if z > bed[2] + 0.01 or not ((x <= bed[0] and y <= bed[1]) or (y <= bed[0] and x <= bed[1]))]


def _settings(p: dict, opts: dict) -> tuple[dict, dict, dict, list[str]]:
    """The printer + quality + material, with the user's choices and the printer's limits applied."""
    notes = []
    q = opts.get("quality") if opts.get("quality") in p["quality"] else p["default_quality"]
    mat = opts.get("material") if opts.get("material") in p["material"] else p["default_material"]
    machine, process, filament = (json.loads(json.dumps(x)) for x in (p["machine"], p["quality"][q], p["material"][mat]))
    try:
        infill = max(0, min(100, int(float(opts.get("infill", 15)))))
        process["sparse_infill_density"] = f"{infill}%"
    except (TypeError, ValueError):
        pass
    sup = opts.get("supports") if opts.get("supports") in ("off", "auto", "tree") else "off"
    process["enable_support"] = "0" if sup == "off" else "1"
    if sup != "off":
        process["support_type"] = "tree(auto)" if sup == "tree" else "normal(auto)"
    if opts.get("brim"):
        process["brim_type"], process["brim_width"] = "outer_only", "5"
    if opts.get("walls"):
        try:
            process["wall_loops"] = str(max(1, min(10, int(opts["walls"]))))
        except (TypeError, ValueError):
            pass
    process["curr_bed_type"] = p.get("bed_type") or "Textured PEI Plate"  # its plate: every material has a real bed
    # temperature there (Orca's default "Cool Plate" gave ABS a cold bed: M190 S0)
    lim = p.get("limits") or {}
    for k, v in list(filament.items()):  # the printer's maximum temperatures win (Creality's ABS preset asks 270 °C)
        cap = lim.get("nozzle") if k.startswith("nozzle_temperature") else lim.get("bed") if "plate_temp" in k else None
        if cap and isinstance(v, list) and v and all(re.fullmatch(r"\d+(\.\d+)?", str(x)) for x in v):
            if any(float(x) > cap for x in v):
                filament[k] = [f"{min(float(x), cap):g}" for x in v]  # (stripping zeros once made 260 °C "26")
                if k == "nozzle_temperature":
                    notes.append(f"{mat} wants {v[0]} °C; this printer goes up to {cap} °C, so it prints at {cap} °C.")
    return machine, process, filament, notes + [f"{mat} {q.split()[-2]} mm"]


def stats(gcode: Path) -> dict:
    """Print time, filament and layers, from the G-code's own notes."""
    size = gcode.stat().st_size
    with open(gcode, "rb") as f:
        head = f.read(8000).decode("utf-8", "ignore")
        f.seek(max(0, size - 400_000))
        tail = f.read().decode("utf-8", "ignore")
    text = head + tail
    g = lambda rx: (re.search(rx, text) or [None, None])[1]  # noqa: E731
    out = {"time": g(r"estimated printing time \(normal mode\) = ([^\n]+)"), "grams": g(r"total filament used \[g\] = ([\d.]+)"),
           "meters": g(r";Filament used:\s*([\d.]+)m"), "layers": g(r"total layer number: (\d+)"), "seconds": g(r";TIME:([\d.]+)")}
    for k in ("grams", "meters", "seconds"):
        out[k] = float(out[k]) if out[k] else None
    out["layers"] = int(out["layers"]) if out["layers"] else None
    return out


def unsafe_temps(gcode: Path, limits: dict) -> list[str]:
    """Last check before a G-code file is handed out: every heater command within the printer's range (a formatting
    bug once turned 260 °C into "26": the nozzle would have been "ready" cold and ground the filament)."""
    bad, noz, bed = [], float(limits.get("nozzle") or 300), float(limits.get("bed") or 120)
    with open(gcode, encoding="utf-8", errors="ignore") as f:
        for line in f:
            m = re.match(r"(M10[49]|M1[49]0)\s.*?S(-?[\d.]+)", line)
            if not m:
                continue
            cmd, t = m.group(1), float(m.group(2))
            if cmd in ("M104", "M109") and t != 0 and not 170 <= t <= noz:
                bad.append(f"{cmd} S{t:g}")
            elif cmd in ("M140", "M190") and not 0 <= t <= bed:
                bad.append(f"{cmd} S{t:g}")
            if len(bad) > 3:
                break
    return bad


def make_gcode(stls: list[Path], opts: dict, rid: str | None = None, name: str = "model") -> dict:
    """STL files -> G-code + 3MF for the printer (all parts arranged on one plate). Blocking: call in a thread."""
    cmd = orca()
    if not cmd:
        return {"error": "OrcaSlicer isn't installed — get it free from orcaslicer.com (or Settings › This PC)"}
    p = printer()
    sizes = [(s.stem, stl_size(s)) for s in stls]
    big = too_big(sizes, p["bed"])
    if big:
        return {"error": f"Too big for the {p['name']} ({p['bed'][0]} × {p['bed'][1]} × {p['bed'][2]} mm): " + "; ".join(big)
                + ". Make it smaller, or split it into parts that fit."}
    machine, process, filament, notes = _settings(p, opts)
    work = DATA / "plugin-runs" / ("slice-" + uuid.uuid4().hex[:10])
    out = work / "out"
    out.mkdir(parents=True)
    files = {"machine": machine, "process": process, "filament": filament}
    for k, v in files.items():
        (work / f"{k}.json").write_text(json.dumps(v), encoding="utf-8")
    plugins.run_set(rid, phase="build", pct=0.05, text=f"OrcaSlicer is slicing it for your {p['name']}…")
    args = [*cmd, "--slice", "0", "--arrange", "1", "--orient", "0",
            "--load-settings", f"{work / 'machine.json'};{work / 'process.json'}", "--load-filaments", str(work / "filament.json"),
            "--export-3mf", "project.3mf", "--outputdir", str(out), *[str(s) for s in stls]]  # (a bare name: a full path made no 3MF)
    t0, proc = time.time(), None
    try:
        proc = spawn(args, cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="ignore", creationflags=NO_WINDOW)
        plugins.run_set(rid, proc=proc)
        while proc.poll() is None:
            t = time.time() - t0
            if t > TIMEOUT:
                kill_tree(proc.pid)
                return {"error": "Slicing took too long and was stopped"}
            plugins.run_set(rid, pct=round(0.05 + 0.85 * (1 - math.exp(-t / 25)), 3))
            time.sleep(0.4)
        said = (proc.stdout.read() if proc.stdout else "") or ""
        if plugins.RUNS.get(rid or "", {}).get("stop"):
            return {"error": "stopped", "stopped": True}
        gcodes = sorted(out.glob("plate_*.gcode"))
        if not gcodes:
            log = " ".join(x.read_text(encoding="utf-8", errors="ignore") for x in out.glob("*.log"))
            why = re.sub(r"\s+", " ", (said + " " + log).replace("Slic3r::CLI::run found error, exit", "")).strip()
            return {"error": "OrcaSlicer couldn't slice it" + (f": {why[-300:]}" if why else f" (code {proc.returncode})")}
        gid = uuid.uuid4().hex[:12]
        safe = re.sub(r"[^\w \-()]", "", name).strip()[:50] or "model"
        mat = notes[-1]
        result = {"printer": p["name"], "settings": mat, "notes": notes[:-1], "plates": len(gcodes), "files": []}
        for g in gcodes:
            bad = unsafe_temps(g, p.get("limits") or {})
            if bad:
                return {"error": "The G-code had a temperature this printer can't use (" + ", ".join(bad) + ") — not saved"}
        for i, g in enumerate(gcodes, 1):
            dst = MEDIA / f"print-{gid}-{i}.gcode"
            shutil.move(str(g), dst)
            st = stats(dst)
            if i == 1:
                result.update(st)
            result["files"].append({"gcode": f"/media/{dst.name}", "name": f"{safe}{f' ({i})' if len(gcodes) > 1 else ''} - "
                                    f"{p['name'].replace('Creality ', '')} - {mat.replace(' mm', 'mm')}.gcode", **st})
        made = next((x for x in (out / "project.3mf", work / "project.3mf") if x.exists()), None)
        if made:
            dst = MEDIA / f"print-{gid}.3mf"
            shutil.move(str(made), dst)
            result["threemf"], result["threemf_name"] = f"/media/{dst.name}", f"{safe} - {p['name'].replace('Creality ', '')}.3mf"
        result["gcode"], result["gcode_name"] = result["files"][0]["gcode"], result["files"][0]["name"]
        return result
    except OSError as e:
        return {"error": f"OrcaSlicer didn't start: {e}"[:300]}
    finally:
        plugins.run_set(rid, proc=None, done=True, pct=1.0)
        wipe.shred_tree(work)
