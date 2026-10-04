"""Materials plugin (run by the app: lookup.py <input.json> <output folder>): finds materials in the FreeCAD material
library (materials.json, CC-BY — built by tools/build_materials.py) and, for CNC, works out starting spindle speed and
feed from the library's cutting (surface) speed. Prints "RESULT: {json}"."""
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = json.loads((HERE / "materials.json").read_text(encoding="utf-8"))
ALIAS = {"aluminium": "aluminum", "alu": "aluminum", "inox": "stainless", "otel": "steel", "lemn": "wood", "plexiglass": "acrylic",
         "plexi": "acrylic", "pal": "particle board", "fibreboard": "mdf", "petg": "pet", "abs": "abs", "nylon": "polyamide"}
# chip load per tooth as a share of the tool diameter: conservative STARTING values for hobby CNC routers / mills
CHIP = [(r"mdf|particle|balsa|soft wood|softwood", 0.015), (r"hard wood|hardwood|wood", 0.012), (r"alumin", 0.004),
        (r"brass|bronze|copper", 0.004), (r"steel|iron", 0.0025), (r"acryl|pmma|poly|abs|pla|pet|nylon|plast", 0.01)]


def score(row: dict, words: list[str]) -> int:
    hay = " ".join(str(row.get(k, "")) for k in ("name", "file", "group", "kindOfMaterial", "description")).lower()
    return sum(3 if w in row.get("name", "").lower() else 1 for w in words if w in hay)


def num(v) -> float | None:
    m = re.match(r"\s*([\d.]+)", str(v or ""))
    return float(m.group(1)) if m else None


def main() -> None:
    p = json.load(open(sys.argv[1], encoding="utf-8"))
    q = str(p.get("query") or p.get("material") or "").lower()
    for a, b in ALIAS.items():
        q = re.sub(rf"\b{a}\b", b, q)
    words = [w for w in re.findall(r"[a-z0-9]+", q) if len(w) > 1]
    rows = sorted(DATA["materials"], key=lambda r: -score(r, words))
    found = [r for r in rows if score(r, words) > 0][:5]
    out = {"query": q, "found": [{k: v for k, v in r.items() if k not in ("file",)} for r in found],
           "source": DATA["source"], "license": DATA["license"]}
    d, flutes = num(p.get("tool_diameter")), int(num(p.get("flutes")) or 2)
    max_rpm = num(p.get("max_rpm")) or 24000
    if d:  # CNC starting values from the surface speed: rpm = Vc * 1000 / (pi * d); feed = rpm * flutes * chip load
        mach = [r for r in rows if r.get("surfaceSpeedCarbide") and score(r, words) > 0]
        if "cast" not in q:  # 6061 / 5083 / sheet / bar stock are WROUGHT alloys (the soft card), cast only if said
            mach.sort(key=lambda r: "Wrought" not in r["name"])
        m = mach[0] if mach else None
        if m:
            vc = num(m["surfaceSpeedCarbide"])
            rpm = min(vc * 1000 / (math.pi * d), max_rpm)
            share = next((c for rx, c in CHIP if re.search(rx, (m["name"] + " " + q).lower())), 0.008)
            chip = round(share * d, 3)
            out["cnc"] = {"material": m["name"], "surface_speed_carbide": m["surfaceSpeedCarbide"], "tool_diameter_mm": d,
                          "flutes": flutes, "rpm": round(rpm), "chip_load_mm": chip, "feed_mm_min": round(rpm * flutes * chip),
                          "plunge_mm_min": round(rpm * flutes * chip * 0.3), "note": "starting values for a carbide end mill "
                          "(rpm capped at the spindle's max): cut a test on scrap and listen — raise the feed if it rubs "
                          "or burns, lower it if the machine chatters."}
    print("RESULT: " + json.dumps(out, ensure_ascii=False))


main()
