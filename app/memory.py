"""Memory 2.0 — ideas from TencentDB Agent Memory (MIT; ideas only, no code): four levels, each linked to its source.

L0 conversation   the chat messages themselves
L1 facts          small lasting facts about the user — said ("remember …") or learned automatically after a chat,
                  each linked to the chat + message it came from
L2 chat summaries the older part of a long chat is summarized instead of dropped (fewer tokens, context kept)
L3 profile        a short "who the user is" built from the facts; it sits at the start of every prompt and only
                  changes when the facts do, so the model's prompt cache keeps working

Search = words (BM25, SQLite full-text) + meaning (EmbeddingGemma 300M on the processor, ~0.07 s per search,
English + Romanian) fused by rank (RRF). Everything stays in data/app.db."""
import array
import asyncio
import json
import re
import subprocess
import time

import httpx

from . import db
from .config import ENGINES, LLM_PORT, LOGS, MODELS, NO_WINDOW, load_settings
from .plat import exe, lib_env
from .llm import llm

PERSONAL = re.compile(r"\b(i|i'm|im|i've|i'd|my|me|mine|myself|eu|meu|mea|mei|mele|mie|sunt|am|îmi|imi|mă|ma)\b", re.I)


# ---------------------------------------------------------------- meaning search engine (on demand, on the CPU)
class Embedder:
    PORT = LLM_PORT + 2
    FILE = "embeddinggemma-300m-qat-Q8_0.gguf"
    IDLE = 600  # stops after 10 idle minutes (~400 MB RAM)

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{self.PORT}"
        self.lock = asyncio.Lock()
        self.used = 0.0

    def model(self):
        p = MODELS / "memory" / self.FILE
        return p if p.exists() else None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def ensure(self) -> bool:
        async with self.lock:
            if self.running():
                return True
            m = self.model()
            if not m:
                return False
            log = open(LOGS / "memory.log", "w", encoding="utf-8", errors="ignore")
            self.proc = subprocess.Popen(
                [str(exe(ENGINES / "llama", "llama-server")), "-m", str(m), "--host", "127.0.0.1", "--port", str(self.PORT),
                 "--embedding", "-ngl", "0", "--device", "none", "-t", "4", "-c", "2048", "-b", "2048", "-ub", "2048"],
                stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW, env=lib_env(ENGINES / "llama"))
            async with httpx.AsyncClient(timeout=2) as c:
                for _ in range(60):
                    if self.proc.poll() is not None:
                        return False
                    try:
                        if (await c.get(f"{self.url}/health")).status_code == 200:
                            return True
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.5)
            return False

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()

    async def embed(self, texts: list[str], query: bool = False) -> list[list[float]] | None:
        """EmbeddingGemma's own prompts: queries and stored texts are marked differently (better matches)."""
        if not texts or not await self.ensure():
            return None
        self.used = time.time()
        items = [(f"task: search result | query: {t}" if query else f"title: none | text: {t}")[:2000] for t in texts]
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{self.url}/v1/embeddings", json={"input": items})
            r.raise_for_status()
        return [d["embedding"] for d in r.json()["data"]]


emb = Embedder()


async def idle_loop() -> None:
    while True:
        await asyncio.sleep(60)
        if emb.running() and time.time() - emb.used > emb.IDLE:
            emb.stop()


_tasks: set = set()


def background(coro) -> None:
    """Runs work in the background and KEEPS a reference to it: asyncio only holds tasks weakly, so a task nobody
    holds can be garbage-collected halfway (the chat summaries silently never happened). Errors go to the log."""
    t = asyncio.get_running_loop().create_task(coro)
    _tasks.add(t)

    def done(task):
        _tasks.discard(task)
        if not task.cancelled() and task.exception():
            print("background task failed:", repr(task.exception()))
    t.add_done_callback(done)


def pack(v: list[float]) -> bytes:
    return array.array("f", v).tobytes()


def unpack(b: bytes) -> list[float]:
    a = array.array("f")
    a.frombytes(b)
    return a.tolist()


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # the server returns normalized vectors


# ---------------------------------------------------------------- tables
def init_db() -> None:
    cols = {r["name"] for r in db.q("PRAGMA table_info(facts)")}
    for name, kind in (("kind", "TEXT DEFAULT 'user'"), ("chat_id", "TEXT"), ("source_msg", "INTEGER"), ("vec", "BLOB")):
        if name not in cols:
            db.run(f"ALTER TABLE facts ADD COLUMN {name} {kind}")
    db.run("CREATE TABLE IF NOT EXISTS summaries(chat_id TEXT PRIMARY KEY, upto_id INTEGER, text TEXT, updated REAL)")
    db.run("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
    db.run("CREATE TABLE IF NOT EXISTS chunk_vecs(chunk_id INTEGER PRIMARY KEY, doc_id TEXT, vec BLOB)")
    db.run("CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT, text TEXT, created REAL, "
           "seen INTEGER DEFAULT 1)")
    seed_lessons()  # an empty lessons memory starts with what was learned fixing this app's designs


def meta(key: str, value: str | None = None) -> str | None:
    if value is not None:
        db.run("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        return value
    r = db.q("SELECT value FROM meta WHERE key=?", (key,))
    return r[0]["value"] if r else None


async def _vectorize_facts() -> None:
    rows = db.q("SELECT id, text FROM facts WHERE vec IS NULL AND COALESCE(kind,'')<>'rule'")
    vecs = await emb.embed([r["text"] for r in rows]) if rows else None
    for r, v in zip(rows, vecs or []):
        db.run("UPDATE facts SET vec=? WHERE id=?", (pack(v), r["id"]))


# ---------------------------------------------------------------- L3 profile
def persona() -> str:
    return meta("persona") or ""


def _facts_key() -> str:
    return str([r["id"] for r in db.q("SELECT id FROM facts WHERE COALESCE(kind,'')<>'rule' ORDER BY id")])


async def _ask_json(prompt: str, schema: dict, max_tokens: int = 300) -> dict:
    r = await llm.complete([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=max_tokens,
                           chat_template_kwargs={"enable_thinking": False},
                           response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}})
    return json.loads(r.get("content") or r.get("reasoning_content") or "{}")


async def refresh_persona(force: bool = False) -> str:
    facts = [r["text"] for r in db.q("SELECT text FROM facts WHERE COALESCE(kind,'')<>'rule' ORDER BY id")]
    if not facts:
        meta("persona", "")
        return ""
    if not force and meta("persona_key") == _facts_key():
        return persona()
    out = await _ask_json(
        "Facts about the user of a personal AI app:\n" + "\n".join(f"- {f}" for f in facts[-60:]) +
        "\nWrite a short profile of the user for the assistant: at most 5 short sentences, English, third person. "
        "Use ONLY what the facts say — add nothing, guess nothing (no feelings or habits that aren't listed). Skip "
        "facts that aren't about the user (e.g. what the assistant will do).",
        {"type": "object", "required": ["profile"], "properties": {"profile": {"type": "string", "maxLength": 800}}})
    meta("persona", out.get("profile", "").strip())
    meta("persona_key", _facts_key())
    return persona()


# ---------------------------------------------------------------- standing rules ("from now on …")
# The user's standing orders, followed in EVERY chat (like Claude's memory of "don't update the backup unless I say").
# Saved as facts of kind "rule", always put in the system prompt (not only when relevant), listed in Memory with Forget.
RULE = re.compile(
    r"^\s*(?:(?:and|also|ok|okay|so|please|pls|pleas)[\s,]+)*(?:"
    r"(?:from now on|for now on|from now|starting now|de acum(?:\s+[iî]nainte|\s+incolo)?|de azi [iî]nainte)\b"
    r"|(?:always|never|mereu|[iî]ntotdeauna|niciodat[aă])\b(?!\s+mind)"
    r"|(?:don'?t|do not|dont|stop|nu mai|nu)\b.{3,160}?\b(?:unless|only when|only if|until|dec[aâ]t|doar c[aâ]nd|doar dac[aă]|"
    r"p[aâ]n[aă] c[aâ]nd)\b"
    r"|only\b.{3,100}?\bwhen i (?:say|ask|tell|want)\b)", re.I)


def is_rule(text: str) -> bool:
    t = text.strip()
    return bool(RULE.search(t)) and not t.endswith("?") and 12 <= len(t) <= 400


def save_rule(text: str) -> tuple[int, str]:
    t = re.sub(r"^\s*/rule\s*", "", text.strip(), flags=re.I)
    t = re.sub(r"^\s*(?:(?:and|also|ok|okay|so|please|pls|pleas)[\s,]+)+", "", t, flags=re.I)[:400]
    old = db.q("SELECT id FROM facts WHERE kind='rule' AND lower(text)=lower(?)", (t,))
    if old:
        return old[0]["id"], t
    return db.insert("INSERT INTO facts(text, created, kind) VALUES (?,?,?)", (t, time.time(), "rule")), t


def rules() -> list[str]:
    return [r["text"] for r in db.q("SELECT text FROM facts WHERE kind='rule' ORDER BY id")]


# ---------------------------------------------------------------- lessons: the AI's OWN mistakes and what fixed them
# Like Claude's feedback memory. Saved when a later try fixed what the test found (a pot "hollowed" into a sealed block,
# a lid joined into its box...), given to the code writer next time for a similar design, listed in Memory with
# Forget. Their own table: never mixed into the facts about the user.
_WORDS = re.compile(r"[a-z]{3,}")
_STOP = {"the", "and", "with", "for", "make", "design", "desine", "printed", "print", "please", "that", "this", "you",
         "your", "can", "want", "need", "some", "into", "from", "has", "was", "not", "use", "one", "part", "parts", "obj"}


# What Claude learned fixing this app's designs (2026-09-27/28): the lessons memory starts with them, so a new install
# doesn't have to make these mistakes first. seen=3 -> always offered to the code writer.
STARTER_LESSONS = [
    ("containers", "Containers: build the solid shape, then hollow(obj, WALL) — a hand-cut, centred cutter sealed a pot shut."),
    ("lids", "Lids: cover = make_lid(body, WALL) and part(cover, \"lid\") — a lid join()ed into the body disappeared."),
    ("sizes", "Sizes: convert cm to mm (x 10) and put every asked size in a variable at the top — \"20 cm deep\" came out 100 mm."),
    ("one piece", "One piece: handles, legs and knobs are add_handle() / join()ed into the body, never a separate part() pushed into it."),
    ("moving parts", "Moving parts: check them at several positions, not only the one shown — an engine's piston hit the "
                     "side plates only when the crank turned past 90°."),
    ("printer size", "Printer size: no part longer than 220 mm — a 473 mm blaster frame had to be split into frame, stock "
                     "and front grip joined with screws."),
    ("mechanisms", "Mechanisms: a finger moves a printed trigger only 2-5 mm; drive bigger motions (a drum turning) from "
                   "something with a long stroke (the plunger's 50 mm)."),
    ("functions", "Building blocks are functions: move(arm, 10, 0, 0), never arm.move(10, 0, 0) — a drone failed 4 tries on it."),
    ("names", "Names: never name a variable like a building block (body = box(...), not box = box(...)), and define "
              "every name before using it."),
    ("proven", "Proven designs first: for a blaster, drum, magazine, gears, pump, hand, brace, bolt, jar, engine or drone "
               "use the tested PicoGK design and change its options — don't guess the mechanism."),
    ("gaps", "Gaps: moving parts 0.4 mm apart, pins in holes 0.4 mm bigger, printed threads round with 0.3 mm play."),
]


def seed_lessons() -> None:
    """Once per install (a flag, so a Forget stays forgotten), next to what it already learned by itself."""
    if meta("starter_lessons") == "1":
        return
    have = {r["text"] for r in db.q("SELECT text FROM lessons")}
    for topic, text in STARTER_LESSONS:
        if text not in have:
            db.run("INSERT INTO lessons(topic, text, created, seen) VALUES (?,?,?,3)", (topic, text, time.time()))
    meta("starter_lessons", "1")


def save_lesson(topic: str, text: str) -> None:
    t = " ".join(text.split())[:300]
    if not t:
        return
    old = db.q("SELECT id FROM lessons WHERE text=?", (t,))
    if old:
        db.run("UPDATE lessons SET seen=seen+1, created=? WHERE id=?", (time.time(), old[0]["id"]))
        return
    db.run("INSERT INTO lessons(topic, text, created, seen) VALUES (?,?,?,1)", (topic[:80], t, time.time()))
    db.run("DELETE FROM lessons WHERE id NOT IN (SELECT id FROM lessons ORDER BY created DESC LIMIT 80)")


def lessons_for(text: str, limit: int = 4) -> list[str]:
    """The lessons that fit this request (shared words), plus the ones that keep coming back (seen 3+ times)."""
    words = set(_WORDS.findall(text.lower())) - _STOP
    scored = []
    for r in db.q("SELECT topic, text, seen FROM lessons"):
        common = words & (set(_WORDS.findall(f"{r['topic']} {r['text']}".lower())) - _STOP)
        if common or r["seen"] >= 3:
            scored.append((len(common) + 0.2 * r["seen"], r["text"]))
    return [t for _, t in sorted(scored, reverse=True)[:limit]]


def all_lessons() -> list[dict]:
    return db.q("SELECT id, topic, text, created, seen FROM lessons ORDER BY created DESC")


def forget_lesson(lid: int) -> None:
    db.run("DELETE FROM lessons WHERE id=?", (lid,))


# ---------------------------------------------------------------- L1 facts learned after a chat
# "facts" that aren't facts: the model once saved "No lasting information about family, pets … was provided."
JUNK = re.compile(r"(?i)\b(no|not|nothing|none|without)\b[^.]{0,80}\b(provided|mentioned|given|shared|said|stated|"
                  r"information|details)\b|see you (next time|again)|acknowledg|greet")


async def learn(chat_id: str, msg_id: int | None, text: str, reply: str) -> list[str]:
    """Lasting facts about the user from what they just said (only when it sounds personal)."""
    if not load_settings().get("memory_auto", True) or not PERSONAL.search(text) or len(text) < 12:
        return []
    known = [r["text"] for r in db.q("SELECT text FROM facts WHERE COALESCE(kind,'')<>'rule' ORDER BY id DESC LIMIT 40")]
    out = await _ask_json(
        "From the user's message below, write down LASTING facts about the user worth remembering for future chats: "
        "name, family, pets, home, job, devices, likes/dislikes, plans, how they want to be answered. Not one-off "
        "requests (\"make a picture\"), not questions, not things about the assistant. English, short, third person "
        "(\"The user …\"). None is fine — return an empty list if nothing lasting was said.\n"
        f"Already known: {known[:20]}\nThe user's message: «{text[:600]}»",
        {"type": "object", "required": ["facts"], "properties": {"facts": {"type": "array", "maxItems": 3,
                                                                            "items": {"type": "string", "maxLength": 160}}}})
    new = [f.strip() for f in out.get("facts", []) if len(f.strip()) > 8 and not JUNK.search(f)]
    if not new:
        return []
    await _vectorize_facts()
    old = [(r["text"], unpack(r["vec"]), r["id"]) for r in db.q("SELECT id, text, vec FROM facts WHERE vec IS NOT NULL AND COALESCE(kind,'')<>'rule'")]
    vecs = await emb.embed(new) or [None] * len(new)
    added = []
    for f, v in zip(new, vecs):
        near = max(((cos(v, ov), t, i) for t, ov, i in old), default=(0, "", 0)) if v else (0, "", 0)
        if near[0] >= 0.78:  # close to something known: the same, a better version, or really different?
            verdict = await consolidate(near[1], f)
            if verdict == "same":
                continue
            if verdict == "more":  # "has a dog" -> "has a pitbull named Rex": keep the detailed one
                db.run("UPDATE facts SET text=?, vec=?, created=?, source_msg=?, chat_id=? WHERE id=?",
                       (f, pack(v), time.time(), msg_id, chat_id, near[2]))
                added.append(f)
                continue
        fid = db.insert("INSERT INTO facts(text, created, kind, chat_id, source_msg, vec) VALUES (?,?,?,?,?,?)",
                        (f, time.time(), "auto", chat_id, msg_id, pack(v) if v else None))
        if v:
            old.append((f, v, fid))
        added.append(f)
    return added


async def consolidate(old: str, new: str) -> str:
    """Decision mode: 'same' (nothing new), 'more' (the new one says more — it replaces the old) or 'different'."""
    try:
        p = await llm.decide(
            "Two facts about the same user. Answer with ONE word:\n"
            "same = the new fact says nothing the old one doesn't (e.g. \"my name is Alex\" / \"The user's name is Alex.\")\n"
            "more = the new fact says the same thing with more detail (e.g. \"has a dog\" / \"has a pitbull named Rex\")\n"
            "different = they are about different things (e.g. \"likes pizza\" / \"likes pasta\")\n"
            f"Old fact: \u00ab{old}\u00bb\nNew fact: \u00ab{new}\u00bb\nWord:", ["same", "more", "different"])
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return "different"
    return max(p, key=p.get)


# ---------------------------------------------------------------- L2 summaries of long chats
def chat_summary(chat_id: str) -> tuple[str, int]:
    r = db.q("SELECT text, upto_id FROM summaries WHERE chat_id=?", (chat_id,))
    return (r[0]["text"], r[0]["upto_id"]) if r else ("", 0)


async def summarize(chat_id: str, upto_id: int) -> None:
    """Everything up to message upto_id (the part the chat window no longer sends) -> one short summary,
    built on the previous summary so nothing old is lost."""
    old, old_upto = chat_summary(chat_id)
    if old_upto >= upto_id:
        return
    rows = db.q("SELECT role, content FROM messages WHERE chat_id=? AND id>? AND id<=? ORDER BY id",
                (chat_id, old_upto, upto_id))
    talk = "\n".join(f"{r['role']}: {r['content'][:300]}" for r in rows)[-6000:]
    out = await _ask_json(
        (f"Summary of the conversation so far: {old}\n" if old else "") + f"More of the conversation:\n{talk}\n"
        "Write the updated summary of the whole conversation as plain sentences (not a title), at most 120 words. "
        "Keep the concrete details: names, places, numbers, prices, dates, what was made or decided, what is still "
        "open (only if the conversation says so — add nothing). Example: \"The user wanted a logo for their bakery "
        "'Sunny'; two versions were made; they chose the blue one.\"",
        {"type": "object", "required": ["summary"], "properties": {"summary": {"type": "string", "maxLength": 1200}}})
    if out.get("summary"):
        db.run("INSERT OR REPLACE INTO summaries VALUES (?,?,?,?)", (chat_id, upto_id, out["summary"].strip(), time.time()))


# ---------------------------------------------------------------- search: words + meaning, fused by rank
def _rrf(*rankings: list, k: int = 60) -> list:
    score: dict = {}
    for ranking in rankings:
        for i, key in enumerate(ranking):
            score[key] = score.get(key, 0) + 1 / (k + i + 1)
    return sorted(score, key=score.get, reverse=True)


def short_fact(t: str, n: int = 320) -> str:
    """A fact as it goes to the model: a long text pasted into memory goes in as its opening only. Whole, its example
    got copied into unrelated answers (a pasted water-tap design guide gave a robot arm "hot inlet / cold inlet")."""
    t = " ".join((t or "").split())
    if len(t) <= n:
        return t
    cut = t[:n]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > n // 3 else cut.rsplit(" ", 1)[0] + " …"


async def recall(text: str) -> list[str]:
    """Notes for the model: the facts and document parts that matter for this message."""
    notes = []
    words = re.findall(r"\w{3,}", text.lower())[:12]
    try:
        qv = (await emb.embed([text], query=True) or [None])[0]
    except httpx.HTTPError:
        qv = None
    # facts: the profile covers the gist; the most relevant ones add the details
    facts = db.q("SELECT id, text, vec FROM facts WHERE COALESCE(kind,'')<>'rule'")
    if persona() and facts:
        await _vectorize_facts()
        facts = db.q("SELECT id, text, vec FROM facts WHERE COALESCE(kind,'')<>'rule'")
        by_meaning = sorted((f for f in facts if f["vec"] and qv), key=lambda f: -cos(qv, unpack(f["vec"])))
        by_meaning = [f["id"] for f in by_meaning if cos(qv, unpack(f["vec"])) >= 0.35][:8]
        by_words = [f["id"] for f in facts if words and any(w in f["text"].lower() for w in words)][:8]
        top = _rrf(by_meaning, by_words)[:5]
        if top:
            texts = {f["id"]: f["text"] for f in facts}
            notes.append("Remembered about the user (relevant now): " + "; ".join(short_fact(texts[i]) for i in top))
    # documents: BM25 + meaning
    by_words, texts = [], {}
    if words:
        try:
            for h in db.q("SELECT c.rowid AS id, c.text, d.name FROM chunks c JOIN documents d ON d.id=c.doc_id "
                          "WHERE chunks MATCH ? ORDER BY rank LIMIT 20", (" OR ".join(f'"{w}"' for w in words),)):
                by_words.append(h["id"])
                texts[h["id"]] = h
        except Exception:  # noqa: BLE001 — odd characters in the query
            pass
    by_meaning = []
    if qv:
        vecs = db.q("SELECT chunk_id, vec FROM chunk_vecs")
        scored = sorted(((cos(qv, unpack(v["vec"])), v["chunk_id"]) for v in vecs), reverse=True)[:20]
        by_meaning = [cid for s, cid in scored if s >= 0.35]
        for cid in by_meaning:
            if cid not in texts:
                r = db.q("SELECT c.rowid AS id, c.text, d.name FROM chunks c JOIN documents d ON d.id=c.doc_id "
                         "WHERE c.rowid=?", (cid,))
                if r:
                    texts[cid] = r[0]
    top = [i for i in _rrf(by_meaning, by_words) if i in texts][:4]
    if top:
        notes.append("From the user's documents (mention the file name):\n" +
                     "\n---\n".join(f"[{texts[i]['name']}] {texts[i]['text']}" for i in top))
    return notes


async def recall_more(text: str, chat_id: str | None) -> list[str]:
    """Laya's deeper look (the message is about the user / something said before): more facts, and what other
    chats were about (their summaries), by meaning + words."""
    notes = []
    words = [w for w in re.findall(r"\w{3,}", text.lower())][:12]
    try:
        qv = (await emb.embed([text], query=True) or [None])[0]
    except httpx.HTTPError:
        qv = None
    facts = db.q("SELECT id, text, vec FROM facts WHERE COALESCE(kind,'')<>'rule'")
    by_meaning = [f["id"] for f in sorted((f for f in facts if f["vec"] and qv), key=lambda f: -cos(qv, unpack(f["vec"])))
                  if cos(qv, unpack(f["vec"])) >= 0.3][:12]
    by_words = [f["id"] for f in facts if words and any(w in f["text"].lower() for w in words)][:12]
    top = _rrf(by_meaning, by_words)[:10]
    if top:
        texts = {f["id"]: f["text"] for f in facts}
        notes.append("Everything remembered that may matter here: " + "; ".join(short_fact(texts[i], 600) for i in top))
    sums = db.q("SELECT chat_id, text FROM summaries WHERE chat_id != ? ORDER BY updated DESC LIMIT 30", (chat_id or "",))
    if sums:
        scored = []
        vecs = (await emb.embed([s["text"] for s in sums])) if qv else None
        for i, s in enumerate(sums):
            sc = (cos(qv, vecs[i]) if vecs else 0) + 0.05 * sum(w in s["text"].lower() for w in words)
            scored.append((sc, s["text"]))
        best = [t for sc, t in sorted(scored, reverse=True)[:2] if sc >= 0.35]
        if best:
            notes.append("From earlier chats with the user: " + " | ".join(best))
    return notes


async def vectorize_document(doc_id: str) -> None:
    rows = db.q("SELECT rowid AS id, text FROM chunks WHERE doc_id=?", (doc_id,))
    for i in range(0, len(rows), 16):
        part = rows[i:i + 16]
        vecs = await emb.embed([r["text"] for r in part])
        if not vecs:
            return
        db.many("INSERT OR REPLACE INTO chunk_vecs VALUES (?,?,?)", [(r["id"], doc_id, pack(v)) for r, v in zip(part, vecs)])


# ---------------------------------------------------------------- after each answer (in the background)
async def after_turn(chat_id: str, msg_id: int | None, text: str, reply: str, dropped_upto: int) -> None:
    """Learn facts, refresh the profile, summarize what fell out of the chat window — quietly, when the model is
    free, never while it renders (the graphics chip is busy then)."""
    from .jobs import renderer
    for _ in range(900):  # up to 15 min: a render (graphics chip busy) or a reply in progress comes first
        if llm.busy <= 0 and not renderer.busy() and llm.running() and llm.gpu:
            break
        await asyncio.sleep(1)
    else:
        return
    try:
        added = await learn(chat_id, msg_id, text, reply)
        if added or (db.q("SELECT 1 FROM facts WHERE COALESCE(kind,'')<>'rule' LIMIT 1") and meta("persona_key") != _facts_key()):
            await refresh_persona()
        if dropped_upto and chat_summary(chat_id)[1] < dropped_upto:
            await summarize(chat_id, dropped_upto)
    except (httpx.HTTPError, ValueError, KeyError, AttributeError) as e:
        print("memory after_turn:", repr(e))
