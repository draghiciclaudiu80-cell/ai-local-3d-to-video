"""Projects: build a device over many messages, one part at a time, so a big machine can be finished on a small model
without ever sending it the whole history.

The plan (the ordered parts), what is done, each built part's real size and how it joins the others, the buy list and a
short log live in the database PER CHAT (table `projects`). Only a COMPACT summary of all this goes into the model's
context for each message — never the full transcript — so the context stays small no matter how big the build gets, and
the app always knows where it left off. One part is built per message (or per "build the next part" click); when a part
is built its real dimensions are recorded and checked against what the part it joins expects, and bought parts (a valve,
seals, a spring, a CO2 cartridge, a motor, bearings…) go on the buy list instead of being modelled."""
import json
import time

from . import db

ENGINES = ("picogk", "freecad", "blender")
MAX_PARTS = 24


def _load(chat_id: str) -> dict | None:
    r = db.q("SELECT data FROM projects WHERE chat_id=?", (chat_id,))
    if not r:
        return None
    try:
        return json.loads(r[0]["data"])
    except ValueError:
        return None


def get(chat_id: str) -> dict | None:
    p = _load(chat_id)
    return p if p and p.get("status") != "closed" else None


def save(chat_id: str, proj: dict) -> dict:
    proj["updated"] = time.time()
    db.run("INSERT INTO projects(chat_id, data, updated) VALUES (?,?,?) "
           "ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
           (chat_id, json.dumps(proj), proj["updated"]))
    return proj


def delete(chat_id: str) -> None:
    db.run("DELETE FROM projects WHERE chat_id=?", (chat_id,))


def _part(n: int, raw: dict) -> dict:
    return {"n": n, "name": str(raw.get("name") or f"part {n}")[:60],
            "spec": str(raw.get("spec") or raw.get("what") or "")[:400],
            "joins": str(raw.get("joins") or raw.get("fits") or "")[:200],
            "status": "planned", "gid": None, "size_mm": None, "note": "",
            "buy": [str(b)[:60] for b in (raw.get("buy") or []) if b][:6]}


def start(chat_id: str, name: str, goal: str, parts: list[dict], engine: str = "freecad",
          buy: list | None = None) -> dict:
    parts = [p for p in (parts or []) if (p.get("name") or p.get("spec"))][:MAX_PARTS]
    proj = {"name": str(name or "project")[:60], "goal": str(goal or name or "")[:300],
            "engine": engine if engine in ENGINES else "freecad", "status": "building",
            "parts": [_part(i + 1, p) for i, p in enumerate(parts)],
            "buy": list(dict.fromkeys(str(b)[:60] for b in (buy or []) if b))[:20],
            "log": [], "created": time.time()}
    log(proj, f"Started “{proj['name']}”: {len(proj['parts'])} parts planned.")
    return save(chat_id, proj)


def log(proj: dict, line: str) -> None:
    proj.setdefault("log", []).append(f"{time.strftime('%H:%M')} {line}"[:160])
    proj["log"] = proj["log"][-40:]


def next_index(proj: dict) -> int | None:
    """The first part not built and not skipped — the one to make next."""
    return next((i for i, p in enumerate(proj.get("parts", [])) if p["status"] in ("planned", "building")), None)


def part_by_name(proj: dict, text: str) -> int | None:
    t = (text or "").lower()
    hits = [i for i, p in enumerate(proj.get("parts", [])) if p["name"].lower() in t and len(p["name"]) > 2]
    return hits[0] if len(hits) == 1 else None


def add_parts(proj: dict, parts: list[dict]) -> None:
    base = len(proj.get("parts", []))
    for i, raw in enumerate(parts[:MAX_PARTS - base]):
        if raw.get("name") or raw.get("spec"):
            proj["parts"].append(_part(base + i + 1, raw))


def record_built(proj: dict, idx: int, m3: dict, buy: list | None = None) -> None:
    p = proj["parts"][idx]
    p["status"] = "built"
    p["gid"] = (str(m3.get("stl", "")).split("model-")[-1].split(".")[0]) or p["gid"]
    p["size_mm"] = [round(float(x), 1) for x in (m3.get("size_mm") or [])] or p["size_mm"]
    p["grams"] = m3.get("grams")
    for b in buy or []:
        if b and b not in proj["buy"]:
            proj["buy"].append(str(b)[:60])
    log(proj, f"Built {p['name']}" + (f" ({' × '.join(str(x) for x in p['size_mm'])} mm)" if p.get("size_mm") else "") + ".")
    if next_index(proj) is None:
        proj["status"] = "assembled" if proj.get("status") == "building" else proj["status"]


def set_status(proj: dict, idx: int, status: str, note: str = "") -> None:
    proj["parts"][idx]["status"] = status
    if note:
        proj["parts"][idx]["note"] = note[:200]
    log(proj, f"{proj['parts'][idx]['name']}: {status}" + (f" — {note}" if note else "") + ".")


def too_big(proj: dict, bed: list) -> list[str]:
    """Built parts that don't fit the printer plate in any orientation."""
    out = []
    for p in proj.get("parts", []):
        s = p.get("size_mm")
        if p.get("cut"):  # already cut into pieces that fit
            continue
        if s and len(s) == 3:
            d = sorted(s)
            b = sorted(bed)
            if not (d[0] <= b[0] and d[1] <= b[1] and d[2] <= b[2]):
                out.append(f"{p['name']} ({' × '.join(str(x) for x in s)} mm)")
    return out


def summary(proj: dict, bed: list | None = None) -> str:
    """The compact note that goes to the model every message: the goal, every part with its state and size, what's next,
    and the buy list. This is what lets a long build run on a small context — the model reads this, not the whole chat."""
    done = sum(p["status"] == "built" for p in proj["parts"])
    out = [f"PROJECT “{proj['name']}” — {proj.get('goal', '')}",
           f"Engine: {proj['engine']}. {done} of {len(proj['parts'])} parts built."]
    for p in proj["parts"]:
        mark = {"built": "✓", "building": "▶", "skipped": "—"}.get(p["status"], "○")
        size = f" [{' × '.join(str(x) for x in p['size_mm'])} mm]" if p.get("size_mm") else ""
        joins = f" — joins: {p['joins']}" if p["joins"] else ""
        out.append(f"  {mark} {p['n']}. {p['name']}{size}{joins}")
    nxt = next_index(proj)
    if nxt is not None:
        out.append(f"NEXT: part {nxt + 1} — {proj['parts'][nxt]['name']}: {proj['parts'][nxt]['spec']}")
    else:
        out.append("All planned parts are built — ready to assemble (combine them and list what to buy).")
    if proj.get("buy"):
        out.append("To buy (not printed): " + ", ".join(proj["buy"]))
    if bed:
        big = too_big(proj, bed)
        if big:
            out.append("⚠ Too big for the printer plate: " + "; ".join(big) + " — split these.")
    return "\n".join(out)


def card(proj: dict) -> dict:
    """What the chat's Project card shows: the checklist, the buy list, and which buttons make sense now."""
    nxt = next_index(proj)
    return {"name": proj["name"], "goal": proj.get("goal", ""), "engine": proj["engine"], "status": proj["status"],
            "parts": [{"n": p["n"], "name": p["name"], "status": p["status"], "gid": p.get("gid"),
                       "size_mm": p.get("size_mm"), "joins": p.get("joins"), "spec": p.get("spec")} for p in proj["parts"]],
            "buy": proj.get("buy", []),
            "done": sum(p["status"] == "built" for p in proj["parts"]),
            "next": None if nxt is None else {"n": proj["parts"][nxt]["n"], "name": proj["parts"][nxt]["name"]},
            "log": proj.get("log", [])[-6:]}
