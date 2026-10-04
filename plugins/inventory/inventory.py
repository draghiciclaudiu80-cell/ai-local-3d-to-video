"""Parts inventory (like InvenTree / PartsBox, kept simple): what you have, how many and where — screws, bearings,
electronics, filament, tools. inventory.py <input.json> <outdir>. The list lives in <app>/data/inventory.json (only on
this PC). Actions: list, find, add, use, set, remove, check (do I have the parts for a list?). Prints "RESULT: {json}"
shaped like a calculator card so the chat shows it the same way."""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data"
FILE = Path(os.environ.get("LOCALAI_INVENTORY") or DATA / "inventory.json")  # tests point it elsewhere
UNITS = {"pcs", "pc", "pieces", "piece", "x", "buc", "bucati", "m", "cm", "mm", "kg", "g", "l", "ml", "rolls", "roll",
         "spools", "spool", "packs", "pack", "boxes", "box", "sets", "set", "meters", "metres", "pairs"}


def load() -> list[dict]:
    try:
        return json.loads(FILE.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []


def save(items: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"items": items}, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FILE)


def norm(s: str) -> str:
    """"10K Ω resistors" -> "10k resistor"; "M3x10 screws" -> "m3x10 screw"."""
    s = str(s or "").lower().replace("ω", "").replace("ohms", "").replace("ohm", "").replace("µ", "u")
    s = re.sub(r"(\d)\s+(k|m|u|n|p)(?=\b|f|h)", r"\1\2", s)  # "10 k" -> "10k", "100 nF" -> "100nf"
    s = re.sub(r"(\d)\s*[x×]\s*(\d)", r"\1x\2", s)
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in re.findall(r"[a-z0-9.]+", s)]
    return " ".join(w for w in words if w not in ("a", "an", "the", "of", "my", "some", "pcs", "pc", "piece", "buc"))


def score(item: dict, q: str) -> float:
    words = norm(q).split()
    if not words:
        return 0
    hay = " ".join(norm(item.get(k, "")) for k in ("name", "value", "package", "category", "location", "note"))
    hits = sum(1 for w in words if re.search(rf"(?<![a-z0-9.]){re.escape(w)}(?![a-z0-9.])", hay))
    return hits / len(words)


def best(items: list[dict], q: str, need: float = 0.99):
    ranked = sorted(((score(it, q), it) for it in items), key=lambda x: -x[0])
    return ranked[0][1] if ranked and ranked[0][0] >= need else None


def qty_of(x) -> float:
    if isinstance(x, (int, float)):
        return float(x)
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)", str(x or ""))
    return float(m.group(1).replace(",", ".")) if m else 0.0


def show(it: dict) -> str:
    q = it.get("qty", 0)
    q = int(q) if float(q).is_integer() else q
    bits = [f"{q} {it.get('unit') or 'pcs'}"]
    for k in ("location", "value", "package"):
        if it.get(k):
            bits.append(f"{k}: {it[k]}")
    if it.get("min") and qty_of(it.get("qty")) <= qty_of(it["min"]):
        bits.append(f"⚠ low (min {it['min']})")
    return " · ".join(bits)


def main() -> None:
    try:
        p = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        p = {}
    action = str(p.get("action") or "list").lower()
    query = str(p.get("query") or "").strip()
    req = p.get("items") or []
    if isinstance(req, dict):
        req = [req]
    req = [r if isinstance(r, dict) else {"name": str(r)} for r in req if r]
    q_low = str(p.get("question") or "").lower()
    said = ("check" if re.search(r"\bcheck\b|\benough\b|parts for|do i have everything", q_low) else
            "find" if re.search(r"\bhow many\b|\bdo i (?:still )?have\b|\bwhere (?:is|are)\b|\bfind\b|\bin stock\b|am in stoc|\bce\b.*\bam\b", q_low) else
            "add" if re.search(r"\b(?:bought|got|received|ordered|add|added|new)\b|\bam cumparat\b", q_low) else
            "use" if re.search(r"\b(?:used|took|take out|used up|consumed|gone)\b|\bam folosit\b", q_low) else None)
    if said and said != action and not (said == "find" and action == "list"):
        action = said  # the user's words were clear ("do I have any M3 screws?" is a look-up, not a parts check)
    if action == "find" and said == "find":  # the user's words, not the model's list (it invented "M3x5 screws")
        query = re.sub(r"\b(how many|do i (still )?have( any| some)?|where (is|are)( my| the)?|in stock|find|my|any|some|"
                       r"are there|is there|left)\b|\?", " ", q_low).strip() or query
    if action == "find" and not query:
        query = " ".join(str(r.get("name", "")) for r in req) or re.sub(
            r"\b(how many|do i (still )?have( any)?|where (is|are)( my)?|in stock|find|my|any|\?)\b|\?", " ", q_low).strip()
    items = load()
    lines, notes, verdict = [], [], ""
    changed = False
    if action in ("add", "use", "set", "remove", "delete"):
        for r in req:
            name = str(r.get("name") or "").strip()
            if not name:
                continue
            q = qty_of(r.get("qty", 1 if action != "set" else 0))
            it = best(items, " ".join(str(r.get(k, "")) for k in ("name", "value", "package") if r.get(k)))
            if action == "add":
                if it:
                    it["qty"] = qty_of(it.get("qty")) + q
                else:
                    it = {"id": uuid.uuid4().hex[:8], "name": name, "qty": q}
                    items.append(it)
                for k in ("unit", "category", "location", "note", "value", "package", "supplier", "price", "min"):
                    if r.get(k) not in (None, ""):
                        it[k] = r[k]
                lines.append([it["name"], f"+{fmt(q)} → {show(it)}"])
            elif not it:
                notes.append(f"“{name}” isn't in the inventory.")
                continue
            elif action == "use":
                it["qty"] = max(0.0, qty_of(it.get("qty")) - q)
                lines.append([it["name"], f"−{fmt(q)} → {show(it)}"])
            elif action == "set":
                it["qty"] = q
                if r.get("location"):
                    it["location"] = r["location"]
                lines.append([it["name"], f"now {show(it)}"])
            else:
                items.remove(it)
                lines.append([it["name"], "removed from the list"])
            it["updated"] = time.strftime("%Y-%m-%d")
            changed = True
        if changed:
            save(items)
        title = {"add": "Added to your parts", "use": "Taken from your parts", "set": "Inventory updated"}.get(action, "Removed from your parts")
    elif action == "check":
        title = "Do you have the parts?"
        short = 0
        for r in req:
            name = str(r.get("name") or "")
            need = qty_of(r.get("qty", 1)) or 1
            it = best(items, name, 0.6)
            have = qty_of(it.get("qty")) if it else 0
            ok = have >= need
            short += not ok
            lines.append([name, f"{'✓' if ok else '✗'} need {fmt(need)}, have {fmt(have)}" + (f" ({it['name']}, {it.get('location', '')})" if it else "")])
        verdict = "You have everything." if req and not short else f"Missing {short} of {len(req)}." if req else "No parts list given."
    else:
        title = "Your parts" if not query else f"Parts matching “{query}”"
        found = [it for it in items if not query or score(it, query) >= 0.5]
        found.sort(key=lambda it: (str(it.get("category") or "~"), it["name"].lower()))
        for it in found[:60]:
            lines.append([it["name"] + (f" ({it['category']})" if it.get("category") else ""), show(it)])
        if not found:
            verdict = "Nothing like that in the inventory." if query else "The inventory is empty — tell me what you have (e.g. “add 50 M3x10 screws, drawer A1”)."
        elif len(found) > 60:
            notes.append(f"Showing 60 of {len(found)}.")
        low = [it["name"] for it in items if it.get("min") and qty_of(it.get("qty")) <= qty_of(it["min"])]
        if low and not query:
            notes.append("Running low: " + ", ".join(low[:10]))
    out = {"calculator": True, "calc": "inventory", "group": "inventory", "title": title, "lines": lines, "notes": notes,
           "warnings": [], **({"verdict": verdict} if verdict else {}), "count": len(items)}
    out["text"] = "\n".join([title] + [f"- {a}: {b}" for a, b in lines] + ([verdict] if verdict else []) + notes) \
        + f"\n({len(items)} kinds of parts in the inventory; saved on this PC)"
    print("RESULT: " + json.dumps(out))


def fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


if __name__ == "__main__":
    main()
