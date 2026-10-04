"""The user's 3D printers: the built-in one (app/printers, the Ender-3 V3 SE), any printer added from OrcaSlicer's own
library (1000+ tested machine presets that come with OrcaSlicer — flattened into a full profile the slicer's command
line can use, saved in data/printers), and custom printers (a printer you built or changed: another profile's slicing
settings with YOUR plate size). The chosen one (settings "printer") is what the 3D editor's plate, the fit checks, the
cutter and the slicer use. Everything here is local: OrcaSlicer's profile files are read from its install folder."""
import json
import re
import time
from pathlib import Path

from .config import DATA, load_settings, save_settings

BUILTIN = Path(__file__).resolve().parent / "printers"
USER = DATA / "printers"
INDEX = DATA / "orca_index.json"
DEFAULT = "ender3_v3_se"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:48] or "printer"


def _read(f: Path) -> dict | None:
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def current_id() -> str:
    return re.sub(r"[^\w]", "", str(load_settings().get("printer") or DEFAULT)) or DEFAULT


def load(pid: str | None = None, _depth: int = 0) -> dict:
    """A full printer profile (machine / quality / material settings + plate). A custom printer = its base printer's
    settings with its own plate size, nozzle and limits."""
    pid = re.sub(r"[^\w]", "", str(pid or current_id())) or DEFAULT
    data = _read(USER / f"{pid}.json") or _read(BUILTIN / f"{pid}.json") or _read(BUILTIN / f"{DEFAULT}.json")
    if data.get("base") and _depth < 3:  # custom: the base printer's tested slicing settings, this printer's plate
        base = load(data["base"], _depth + 1)
        w, d, h = (float(x) for x in data.get("bed") or base["bed"])
        machine = json.loads(json.dumps(base["machine"]))
        machine["printable_area"] = ["0x0", f"{w:g}x0", f"{w:g}x{d:g}", f"0x{d:g}"]
        machine["printable_height"] = f"{h:g}"
        if data.get("nozzle") and float(data["nozzle"]) != float(base.get("nozzle", 0.4)):
            machine["nozzle_diameter"] = [f"{float(data['nozzle']):g}"]
        out = {**base, "id": data["id"], "name": data["name"], "bed": [w, d, h], "machine": machine,
               "nozzle": data.get("nozzle") or base.get("nozzle"), "limits": data.get("limits") or base.get("limits", {}),
               "custom": True, "base": data["base"]}
        return out
    return data


def listing() -> list[dict]:
    out, seen = [], set()
    for folder, kind in ((BUILTIN, "built-in"), (USER, None)):
        if not folder.exists():
            continue
        for f in sorted(folder.glob("*.json")):
            d = _read(f)
            if not d or d.get("id") in seen:
                continue
            seen.add(d.get("id"))
            if d.get("base"):
                base = _read(USER / f"{d['base']}.json") or _read(BUILTIN / f"{d['base']}.json") or {}
                bed = d.get("bed") or base.get("bed")
            else:
                bed = d.get("bed")
            out.append({"id": d["id"], "name": d["name"], "bed": bed, "nozzle": d.get("nozzle"),
                        "kind": kind or ("custom" if d.get("base") else "OrcaSlicer library")})
    return out


def select(pid: str) -> dict:
    pid = re.sub(r"[^\w]", "", pid)
    if not ((USER / f"{pid}.json").exists() or (BUILTIN / f"{pid}.json").exists()):
        raise ValueError("That printer isn't in the list")
    p = load(pid)
    save_settings({"printer": pid, "printer_bed": p["bed"]})  # the fit checks / cutter read the plate from here too
    return p


def add_custom(name: str, bed: list, base: str | None = None, nozzle: float | None = None,
               nozzle_max: float | None = None, bed_max: float | None = None) -> dict:
    """Your own printer: a plate size (mm) on top of another printer's tested slicing settings."""
    try:
        w, d, h = (float(x) for x in bed)
    except (TypeError, ValueError):
        raise ValueError("The plate needs width, depth and height in mm")
    if not (50 <= w <= 2000 and 50 <= d <= 2000 and 30 <= h <= 2000):
        raise ValueError("The plate size looks wrong (each side 50–2000 mm, height 30–2000 mm)")
    base_id = re.sub(r"[^\w]", "", str(base or current_id()))
    bp = load(base_id)
    if bp.get("base"):  # a custom printer's base is always a real profile
        base_id = bp["base"]
        bp = load(base_id)
    lim = dict(bp.get("limits") or {})
    if nozzle_max:
        lim["nozzle"] = float(nozzle_max)
    if bed_max:
        lim["bed"] = float(bed_max)
    pid = "custom_" + _slug(name or f"{w:g}x{d:g}x{h:g}")
    data = {"id": pid, "name": str(name or f"My printer {w:g}×{d:g}×{h:g}")[:60], "base": base_id, "bed": [w, d, h],
            "nozzle": float(nozzle) if nozzle else bp.get("nozzle", 0.4), "limits": lim, "created": time.time()}
    USER.mkdir(parents=True, exist_ok=True)
    (USER / f"{pid}.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    return data


def remove(pid: str) -> None:
    pid = re.sub(r"[^\w]", "", pid)
    f = USER / f"{pid}.json"
    if not f.exists():
        raise ValueError("Only printers you added can be removed")
    f.unlink()
    if current_id() == pid:
        select(DEFAULT)


# ------------------------------------------------------------------ OrcaSlicer's printer library
def _orca_profiles() -> Path | None:
    from . import slicer
    exe = slicer.orca()
    if not exe:
        return None
    root = Path(exe[0]).parent
    for cand in (root / "resources" / "profiles", root / "usr" / "share" / "OrcaSlicer" / "profiles",
                 root / "resources" / "profiles"):
        if cand.exists():
            return cand
    hits = list(root.rglob("profiles/Creality.json"))[:1]
    return hits[0].parent if hits else None


def _index() -> dict:
    """{(type, name): file} for every preset in OrcaSlicer's library — cached in data/orca_index.json (it's 11 000 files)."""
    prof = _orca_profiles()
    if not prof:
        return {}
    stamp = str(int((prof / "Creality.json").stat().st_mtime)) if (prof / "Creality.json").exists() else "0"
    cached = _read(INDEX)
    if cached and cached.get("stamp") == stamp and cached.get("root") == str(prof):
        return cached
    entries, machines = {}, []
    for f in prof.rglob("*.json"):
        j = _read(f)
        if not isinstance(j, dict) or not j.get("name") or not j.get("type"):
            continue
        entries[f"{j['type']}|{j['name']}"] = str(f.relative_to(prof))
        if j["type"] == "machine" and str(j.get("instantiation", "true")).lower() == "true":
            machines.append(j["name"])
    data = {"stamp": stamp, "root": str(prof), "entries": entries, "machines": sorted(set(machines))}
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(data), encoding="utf-8")
    return data


def library(q: str = "", limit: int = 40) -> list[str]:
    idx = _index()
    words = [w for w in re.findall(r"[a-z0-9.]+", q.lower()) if w]
    names = idx.get("machines", [])
    hits = [n for n in names if all(w in n.lower() for w in words)] if words else names
    hits.sort(key=lambda n: (" 0.4" not in n and "(0.4" not in n, len(n)))  # the usual 0.4 mm nozzle first
    return hits[:limit]


def add_from_library(machine_name: str) -> dict:
    """OrcaSlicer's own presets for that printer → a full local profile (machine + its tested qualities and materials)."""
    idx = _index()
    if not idx:
        raise ValueError("OrcaSlicer isn't installed, so its printer library isn't here")
    root = Path(idx["root"])
    entries = idx["entries"]
    if f"machine|{machine_name}" not in entries:
        raise ValueError(f"OrcaSlicer has no printer called “{machine_name}”")

    def flat(kind: str, name: str, depth: int = 0) -> dict:
        rel = entries.get(f"{kind}|{name}")
        if not rel or depth > 12:
            return {}
        j = _read(root / rel) or {}
        out = {**(flat(kind, j["inherits"], depth + 1) if j.get("inherits") else {}), **j}
        out.pop("inherits", None)
        out["from"] = "system"
        return out

    machine = flat("machine", machine_name)
    qualities, materials = {}, {}
    for key, rel in entries.items():
        kind, name = key.split("|", 1)
        if kind not in ("process", "filament"):
            continue
        j = _read(root / rel) or {}
        if str(j.get("instantiation", "true")).lower() != "true" or machine_name not in (j.get("compatible_printers") or []):
            continue
        if kind == "process":
            full = flat("process", name)
            lh = str(full.get("layer_height") or "")
            label = (re.search(r"(Extra ?Fine|Fine|Optimal|Standard|Draft|Extra ?Draft|Super ?Draft|Strength|Quality|Speed)",
                               name, re.I) or [None, "Profile"])[1].title()
            qualities[f"{label} {float(lh):.2f} mm" if lh else name] = full
        else:
            full = flat("filament", name)
            ftype = str((full.get("filament_type") or ["?"])[0])
            label = ftype + (" High Speed" if re.search(r"high.?speed|hs\b|hyper", name, re.I) else "")
            generic = "generic" in name.lower()
            if label not in materials or generic:
                materials[label] = full
    if not qualities or not materials:
        raise ValueError(f"OrcaSlicer has no ready quality / material presets for “{machine_name}”")
    qualities = dict(sorted(qualities.items(), key=lambda kv: float((re.findall(r"\d+\.\d+", kv[0]) or ["9"])[0])))
    keep = [m for m in ("PLA", "PLA High Speed", "PETG", "ABS", "ASA", "TPU", "PA", "PC") if m in materials]
    materials = {m: materials[m] for m in keep} or materials
    xy = [tuple(float(v) for v in pt.split("x")) for pt in machine.get("printable_area") or ["0x0", "220x0", "220x220", "0x220"]]
    bed = [max(p[0] for p in xy) - min(p[0] for p in xy), max(p[1] for p in xy) - min(p[1] for p in xy),
           float(machine.get("printable_height") or 250)]

    def top(m, key):
        vals = [float(v) for v in (m.get(key) or []) if re.fullmatch(r"\d+(\.\d+)?", str(v))]
        return max(vals) if vals else 0
    limits = {"nozzle": max([top(m, "nozzle_temperature") for m in materials.values()] + [0]) or 300,
              "bed": max([top(m, k) for m in materials.values() for k in ("hot_plate_temp", "textured_plate_temp")] + [0]) or 110}
    default_q = next((k for k in qualities if k.startswith("Standard")), next((k for k in qualities if "0.20" in k), next(iter(qualities))))
    pid = _slug(machine_name)
    data = {"id": pid, "name": machine_name.replace(" nozzle", " nozzle"), "bed": bed,
            "nozzle": float((machine.get("nozzle_diameter") or ["0.4"])[0]), "limits": limits,
            "default_quality": default_q, "default_material": "PLA" if "PLA" in materials else next(iter(materials)),
            "machine": machine, "quality": qualities, "material": materials, "source": "OrcaSlicer library",
            "bed_type": None, "added": time.time()}
    USER.mkdir(parents=True, exist_ok=True)
    (USER / f"{pid}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return {k: data[k] for k in ("id", "name", "bed", "nozzle", "default_quality", "default_material")} | \
        {"qualities": list(qualities), "materials": list(materials)}
