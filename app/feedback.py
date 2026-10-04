"""👍 / 👎 under every answer (the reward buttons). A liked answer is kept as a GOOD example, a disliked one as a BAD
example with what was wrong. The chat model's weights can't be retrained on this PC, so it learns the way the rules and
lessons work: on a similar question later it is shown the liked answer (answer like this) and what was disliked and why
(don't do that again). Every rating is also written to data/feedback/feedback.jsonl — one {prompt, completion, label}
per line, the KTO format — ready if the model is ever fine-tuned on a bigger computer."""
import json
import re
import time

from . import db, memory, wipe
from .config import DATA

FILE = DATA / "feedback" / "feedback.jsonl"
REASONS = {  # the one-click reasons under 👎 (the user mostly uses the mouse)
    "wrong": "it was wrong (wrong facts or numbers)",
    "made_up": "it made things up or said it did something it didn't",
    "not_asked": "it didn't do what was asked",
    "off_topic": "it mixed in things that don't belong to the question",
    "long": "it was too long",
    "short": "it was too short, not enough detail",
}
NEAR = 0.55  # how alike (meaning) a new question must be before an example is shown — a wrong example misleads
NEAR_WORDS = 0.5  # the same by shared words when the memory model is off


def _extra(s) -> dict:
    try:
        d = json.loads(s or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def rate(chat_id: str, msg_id: int, rating: int, reason: str = "") -> dict:
    """1 = 👍, -1 = 👎, 0 = take it back. The question is the user's message just before the answer."""
    m = db.q("SELECT content, extra FROM messages WHERE id=? AND chat_id=? AND role='assistant'", (msg_id, chat_id))
    if not m:
        raise ValueError("That answer isn't there any more")
    extra = _extra(m[0]["extra"])
    extra.pop("rating", None)
    extra.pop("reason", None)
    if rating:
        rating = 1 if rating > 0 else -1
        q = db.q("SELECT content FROM messages WHERE chat_id=? AND id<? AND role='user' ORDER BY id DESC LIMIT 1",
                 (chat_id, msg_id))
        reason = (REASONS.get(reason, reason) or "").strip()[:300] if rating < 0 else ""
        db.run("INSERT OR REPLACE INTO ratings(msg_id, chat_id, rating, question, answer, reason, created) "
               "VALUES (?,?,?,?,?,?,?)", (msg_id, chat_id, rating, q[0]["content"] if q else "", m[0]["content"] or "",
                                          reason, time.time()))
        extra["rating"] = rating
        if reason:
            extra["reason"] = reason
    else:
        db.run("DELETE FROM ratings WHERE msg_id=?", (msg_id,))
    db.run("UPDATE messages SET extra=? WHERE id=?", (json.dumps(extra), msg_id))
    export()
    return {"ok": True, "rating": rating, "reason": reason if rating < 0 else ""}


def forget(msg_id: int) -> None:
    """Memory page ✕: the example goes; its chat (if it's still there) shows the buttons unpressed again."""
    r = db.q("SELECT chat_id FROM ratings WHERE msg_id=?", (msg_id,))
    if not r:
        return
    try:
        rate(r[0]["chat_id"], msg_id, 0)
    except ValueError:  # the chat was deleted: the example stays only here
        db.run("DELETE FROM ratings WHERE msg_id=?", (msg_id,))
        export()


def listing() -> list[dict]:
    return [{**r, "question": r["question"][:200], "answer": r["answer"][:240]} for r in
            db.q("SELECT msg_id, chat_id, rating, question, answer, reason, created FROM ratings ORDER BY created DESC")]


def export() -> None:
    """The training file, rewritten after every rating (one short line per rated answer)."""
    rows = db.q("SELECT question, answer, rating, reason, created FROM ratings ORDER BY created")
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_name(FILE.name + ".new")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"prompt": r["question"], "completion": r["answer"], "label": r["rating"] > 0,
                                **({"reason": r["reason"]} if r["reason"] else {}),
                                "time": time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created"]))},
                               ensure_ascii=False) + "\n")
    wipe.shred(FILE)  # the old copy is overwritten, not just unlinked (a deleted chat's answers leave no trace)
    tmp.replace(FILE)


def _short(t: str, n: int) -> str:
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


def _words(t: str) -> set:
    return set(re.findall(r"[a-zăâîșțşţ]{4,}", (t or "").lower()))


async def recall(text: str) -> list[str]:
    """Notes for the model: the closest liked answer (answer like this) and the closest disliked one (not like that)."""
    rows = db.q("SELECT msg_id, rating, question, answer, reason, vec FROM ratings")
    if not rows or not text.strip():
        return []
    qv = None
    if memory.emb.model():
        todo = [r for r in rows if not r["vec"]]
        if todo:  # what an example is about: its question + the start of the answer (a bare "it doesn't work" says little)
            vecs = await memory.emb.embed([f"{r['question']}\n{r['answer'][:300]}" for r in todo])
            for r, v in zip(todo, vecs or []):
                r["vec"] = memory.pack(v)
                db.run("UPDATE ratings SET vec=? WHERE msg_id=?", (r["vec"], r["msg_id"]))
        qv = (await memory.emb.embed([text], query=True) or [None])[0]
    mine = _words(text)
    best = {1: (0.0, None), -1: (0.0, None)}
    for r in rows:
        if qv and r["vec"]:
            s = memory.cos(qv, memory.unpack(r["vec"]))
            ok = s >= NEAR
        else:
            theirs = _words(r["question"])
            s = len(mine & theirs) / max(1, len(mine | theirs))
            ok = s >= NEAR_WORDS
        if ok and s > best[r["rating"]][0]:
            best[r["rating"]] = (s, r)
    notes = []
    good, bad = best[1][1], best[-1][1]
    if good:
        notes.append(f"The user LIKED this answer to a similar question («{_short(good['question'], 160)}»). Answer the "
                     f"same way (approach, detail, format), but with THIS question's own facts and numbers:\n"
                     f"«{_short(good['answer'], 700)}»")
    if bad:
        why = bad["reason"] or "it wasn't good (wrong, made up or not what was asked)"
        notes.append(f"The user DISLIKED an answer to a similar question («{_short(bad['question'], 160)}»): {why}. "
                     f"Don't make that mistake again. That answer began: «{_short(bad['answer'], 160)}»")
    return notes
