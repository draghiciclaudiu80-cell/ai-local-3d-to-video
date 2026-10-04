"""Skills: expert instructions the AI loads when a message needs them (like Claude's skills). A skill is a folder with
a SKILL.md:
    ---
    name: Foam-dart blasters
    description: one line — shown in the Skills menu
    triggers: nerf, blaster, dart          (words that switch it on; "/<folder name>" in the chat forces it)
    for: 3d, chat                          (3d = the 3D designer's plan + design, chat = normal answers)
    ---
    the instructions (short, numbers that work, examples)
Built-in skills live in <app>/skills; your own folders are added in Memory › Skills (settings "skill_dirs"); switched
off ones are in settings "skills_off". No code runs — a skill is only text the model reads."""
import re
from pathlib import Path

from .config import ROOT, load_settings, save_settings

BUILTIN = ROOT / "skills"
MAX_CHARS = 3000  # one skill's text (a small model's context is ~8k tokens)


def _parse(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip()
    split = lambda v: [x.strip().strip("\"'") for x in re.split(r"[,\[\]]", v or "") if x.strip().strip("\"'")]  # noqa: E731
    sid = path.parent.name
    return {"id": sid, "name": meta.get("name") or sid, "description": meta.get("description", ""),
            "triggers": split(meta.get("triggers")), "for": split(meta.get("for")) or ["chat", "3d"],
            "body": body.strip()[:MAX_CHARS], "path": str(path.parent)}


def all_skills() -> list[dict]:
    s = load_settings()
    off = set(s.get("skills_off") or [])
    out, seen = [], set()
    for base, builtin in [(BUILTIN, True)] + [(Path(d), False) for d in s.get("skill_dirs") or []]:
        files = [base / "SKILL.md"] if (base / "SKILL.md").exists() else sorted(base.glob("*/SKILL.md"))
        for f in files:
            sk = _parse(f)
            if sk and sk["id"] not in seen:
                seen.add(sk["id"])
                out.append({**sk, "builtin": builtin, "enabled": sk["id"] not in off})
    return out


def get(sid: str) -> dict | None:
    return next((s for s in all_skills() if s["id"] == sid), None)


def matched(text: str, where: str, forced: list[str] | None = None, limit: int = 2) -> list[dict]:
    """The skills a message needs: the ones named with /<id>, then the ones whose words appear (most hits first)."""
    t = re.sub(r"\b3\s+d\b", "3d", text.lower())
    hits = []
    for s in all_skills():
        if not s["enabled"] or where not in s["for"]:
            continue
        if forced and s["id"] in forced:
            hits.append((99, s))
            continue
        n = sum(1 for w in s["triggers"] if re.search(rf"(?<![a-z0-9]){re.escape(w.lower())}(?![a-z0-9])", t))
        if n:
            hits.append((n, s))
    return [s for _, s in sorted(hits, key=lambda x: -x[0])][:limit]


def as_text(found: list[dict]) -> str:
    return "\n\n".join(f"SKILL “{s['name']}” (expert instructions — follow them):\n{s['body']}" for s in found)


def set_enabled(sid: str, on: bool) -> None:
    s = load_settings()
    off = set(s.get("skills_off") or [])
    (off.discard if on else off.add)(sid)
    save_settings({"skills_off": sorted(off)})


def add_dir(path: str) -> None:
    p = Path(path.strip().strip('"'))
    if not ((p / "SKILL.md").exists() or any(p.glob("*/SKILL.md"))):
        raise ValueError("That folder has no SKILL.md (or sub-folders with one)")
    s = load_settings()
    dirs = [d for d in s.get("skill_dirs") or [] if Path(d) != p] + [str(p)]
    save_settings({"skill_dirs": dirs})


def remove(sid: str) -> None:
    sk = get(sid)
    if sk and not sk["builtin"]:
        s = load_settings()
        keep = [d for d in s.get("skill_dirs") or [] if Path(d) != Path(sk["path"]) and Path(d) != Path(sk["path"]).parent]
        save_settings({"skill_dirs": keep})
