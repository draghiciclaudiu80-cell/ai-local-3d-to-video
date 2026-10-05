"""The agent team (Team page / "use the team" in a chat, OpenDots-style), built like a Raven harness:
- HOST MANAGER: the Planner splits the job into steps with a "done when" each; the plan is checked against rules
  (only switched-on experts, the right expert for 3D / apps / web, no duplicates, at most 5 steps).
- every expert works with a NOTEBOOK (a short memory of the others' work, older steps shortened), a COMPASS (the goal,
  its step, the "done when", its rules and the lessons it learned), a TOOL BELT (only its own tool) and a STAMP: an
  independent JUDGE checks each step before the next expert builds on it; a failed step gets ONE retry with the
  judge's reason, then it's marked failed (never "done" when it wasn't).
- Researcher: searches (through Tor), stops when a new search finds nothing new, OPENS the best pages and keeps an
  audit trail of sources [1], [2]… The 3D designer uses the chat's own 3D pipeline (proven designs, fit check) and the
  Coder the app maker (tested in the browser) — their results land in the chat, the Gallery and Apps.
- GENE BANK: a step that passed after the judge's feedback leaves a lesson for that expert (used next time).
The team works in a chat (the one you asked in, or a new "👥 …" chat), so every result is in one place.
OFF by default (setting team_on): a job is many model turns. Saved in data/team/ (agents.json, jobs.json)."""
import asyncio
import json
import re
import time
import uuid

from .config import DATA, load_settings
from . import db

DIR = DATA / "team"
DEFAULT_AGENTS = [
    {"id": "researcher", "name": "Researcher", "emoji": "🔎", "tool": "web", "on": True,
     "role": "Finds facts on the web (through Tor), opens the best pages and sums them up with the sources."},
    {"id": "engineer", "name": "Engineer", "emoji": "🧮", "tool": "calc", "on": True,
     "role": "Mechanics, electronics, 3D printing and materials: works out sizes, forces and parts with the calculators."},
    {"id": "designer", "name": "3D designer", "emoji": "🧊", "tool": "3d", "on": True,
     "role": "Makes the 3D model of a part or device (printable, fit-checked) — it appears in the chat and the Gallery."},
    {"id": "coder", "name": "Coder", "emoji": "💻", "tool": "app", "on": True,
     "role": "Builds a small app, game or tool as a working web page (tested in the browser; it appears in Apps)."},
    {"id": "writer", "name": "Writer", "emoji": "✍️", "tool": "", "on": True,
     "role": "Writes clear texts: plans, explanations, lists, messages, stories."},
]
RULES = {  # the compass: what each kind of expert must and mustn't do
    "web": "Use ONLY the sources below; put [n] after every claim; say plainly when the sources don't answer it.",
    "calc": "Use the calculator's numbers when there are any; show the key numbers and units; never invent measurements.",
    "3d": "Describe only the parts that were really built and what the fit check found.",
    "app": "Say what the app does and how the browser check went.",
    "": "Use the notebook's facts; don't invent facts, links or numbers; keep to your step. You only write text: never "
        "say you made, saved or created a file, folder, app or model (the Coder and the 3D designer do that).",
}
MAKES = {  # a task that asks to MAKE this goes to the expert with that tool ("write instructions for the 3D part" doesn't)
    "3d": r"^\s*(create|make|design|build|model|generate)\b.{0,50}\b(3d|stl|model|printable|mechanism|part|enclosure|case|bracket)\b",
    "app": r"^\s*(build|make|create|code|write|program|develop)\b.{0,40}\b(app|application|web ?page|website|program|game|tool)\b",
    "web": r"^\s*(search|find|look up|research|browse|check online)\b"}
RUNNING: dict[str, asyncio.Task] = {}
QUEUE: list[dict] = []  # jobs asked for while the team was busy: they start by themselves, one after another
_loop_started = False


def _read(name: str, default):
    try:
        return json.loads((DIR / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def agents() -> list[dict]:
    return _read("agents.json", DEFAULT_AGENTS)


def save_agents(items: list[dict]) -> list[dict]:
    old = {a["id"]: a for a in agents()}
    clean_items = []
    for a in items[:12]:
        name = str(a.get("name") or "").strip()[:40]
        if name:
            aid = re.sub(r"\W+", "-", str(a.get("id") or name).lower())[:30]
            clean_items.append({"id": aid, "name": name, "emoji": str(a.get("emoji") or "🤖")[:4],
                                "role": str(a.get("role") or "")[:600],
                                "tool": a.get("tool") if a.get("tool") in ("web", "calc", "3d", "app", "") else "",
                                "on": bool(a.get("on", True)), "lessons": (old.get(aid) or {}).get("lessons", [])[-5:]})
    _write("agents.json", clean_items)
    return clean_items


def _learn(agent_id: str, lesson: str) -> None:
    """The gene bank: a fix the judge forced is remembered by that expert (last 5)."""
    items = agents()
    for a in items:
        if a["id"] == agent_id and lesson not in (a.get("lessons") or []):
            a["lessons"] = ((a.get("lessons") or []) + [lesson[:240]])[-5:]
    _write("agents.json", items)


def jobs() -> list[dict]:
    return _read("jobs.json", [])


def _save_job(job: dict) -> None:
    items = [j for j in jobs() if j["id"] != job["id"]]
    _write("jobs.json", [job, *items][:40])


def public() -> dict:
    return {"on": bool(load_settings().get("team_on")), "agents": agents(), "jobs": jobs()[:20], "running": list(RUNNING),
            "queued": [j["id"] for j in QUEUE]}


def clean(text: str) -> str:
    """Some models still write their thinking with thinking off ("… </think> D") or leak their end token
    ("…<|im_end|>"), or start with "Here's the final answer for the user:": keep the real answer."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    if "</think>" in text:
        text = max(text.split("</think>"), key=lambda part: len(part.strip()))
    text = re.split(r"<\|(?:im_end|endoftext|eot_id|end)\|>", text.replace("<think>", ""))[0]
    text = re.sub(r"<\|[a-z_]{2,20}\|>", "", text)
    text = re.sub(r"^\s*(?:\*\*)?(?:here(?:'s| is) (?:the|my) (?:final )?(?:answer|result|report|summary)[^:\n]{0,40}:|"
                  r"final answer(?: for the user)?:)(?:\*\*)?\s*", "", text, flags=re.I)
    return text.strip()


def _sentences(text: str, limit: int) -> str:
    """Cut at the end of a sentence, not in the middle of a word ("… a real lock mechanism. A")."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > limit // 3 else cut.rsplit(" ", 1)[0] + "…"


async def _ask(messages: list[dict], max_tokens: int = 900, schema: dict | None = None) -> str:
    """One turn of the chat model (loaded if needed; a chat answer goes first)."""
    from .agent import chat_model
    from .jobs import renderer
    from .llm import llm
    model = chat_model()
    if not model:
        raise RuntimeError("No chat model yet — download one in Models › Text")
    while llm.busy > 0:
        await asyncio.sleep(0.5)
    await llm.ensure(model, int(load_settings()["ctx"]), not renderer.busy())
    extra = {"response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}} if schema else {}
    llm.busy += 1
    try:
        r = await llm.complete(messages, temperature=0.3, max_tokens=max_tokens,
                               chat_template_kwargs={"enable_thinking": False}, **extra)
    finally:
        llm.busy -= 1
    return clean(r.get("content") or "")


def _post(chat_id: str, text: str, extra: dict | None = None) -> None:
    """The team writes into its chat (results, plan, final answer) so everything is in one place."""
    if not chat_id or not db.q("SELECT 1 FROM chats WHERE id=?", (chat_id,)):
        return
    db.run("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
           (chat_id, "assistant", text, json.dumps({"tools": [], **(extra or {})}), time.time()))
    db.run("UPDATE chats SET updated=? WHERE id=?", (time.time(), chat_id))


# ---------------------------------------------------------------- host manager: the plan, checked against rules
async def _plan(goal: str, team: list[dict]) -> list[dict]:
    names = [a["name"] for a in team]
    schema = {"type": "object", "required": ["steps"], "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 5,
              "items": {"type": "object", "required": ["agent", "task", "done_when"], "properties": {
                  "agent": {"type": "string", "enum": names}, "task": {"type": "string", "minLength": 5},
                  "done_when": {"type": "string", "minLength": 5}}}}}}
    who = "\n".join(f"- {a['name']}: {a['role']}" for a in team)
    text = await _ask([{"role": "system", "content": "You are the host manager of a small team of AI experts. Split the job "
                        "into the FEW steps it really needs (1-5), in order; give each to the right expert; write one clear "
                        "task and a short, checkable 'done when' for each. Don't add steps nobody asked for.\nThe experts:\n" + who},
                       {"role": "user", "content": "The job: " + goal}], 700, schema)
    return validate(json.loads(text).get("steps") or [], team, goal)


WANTS_APP = re.compile(r"\b(app|apps|ap|aap|aplica\w*|application|program|software|game|joc|website|web ?page|tool|calculator|"
                       r"notepad|editor|timer|tracker|planner|quiz|interface|ui|dashboard|script|code)\b", re.I)


def validate(steps: list[dict], team: list[dict], goal: str = "") -> list[dict]:
    """Structural rules: known + switched-on experts only, 3D / app / web work goes to the expert with that tool, no
    duplicate tasks, no app nobody asked for (a door lock job got "a web tool to check compatibility": 5 minutes for
    nothing), at most 5 steps."""
    by_name = {a["name"]: a for a in team}
    by_tool = {a.get("tool"): a for a in team if a.get("tool")}
    out, seen = [], set()
    for s in steps:
        agent, task = by_name.get(s.get("agent")), str(s.get("task") or "").strip()[:500]
        if not agent or not task or task.lower() in seen:
            continue
        for tool, rx in MAKES.items():  # "create a 3D model of…" is built by the 3D designer, "build an app…" by the Coder
            if tool in by_tool and agent.get("tool") != tool and re.search(rx, task, re.I):
                agent = by_tool[tool]
                break
        if agent.get("tool") == "app" and goal and not WANTS_APP.search(goal):
            continue
        seen.add(task.lower())
        out.append({"agent": agent["name"], "agent_id": agent["id"], "task": task,
                    "done_when": str(s.get("done_when") or "the step's request is fully answered")[:200],
                    "status": "waiting", "result": "", "outputs": []})
    return out[:5]


# ---------------------------------------------------------------- notebook + compass
def notebook(steps: list[dict], upto: int) -> str:
    """What the others did: the last two steps in full, older ones shortened (the context stays small)."""
    lines = []
    for i, s in enumerate(steps[:upto]):
        full = i >= upto - 2
        res = s["result"] if full else s["result"][:200]
        outs = ", ".join(o.get("label", "") for o in s.get("outputs") or [])
        lines.append(f"[{s['agent']} — {s['status']}] {s['task']}\n{res[:1800]}" + (f"\nMade: {outs}" if outs else ""))
    return "\n\n".join(lines)[-5000:]


def compass(agent: dict, step: dict, goal: str, notes: str, feedback: str = "", found: str = "") -> list[dict]:
    lessons = "\n".join(f"- {x}" for x in agent.get("lessons") or [])
    return [{"role": "system", "content": f"You are {agent['name']}, one expert in a small AI team. {agent['role']}\n"
                                          f"Rules: {RULES.get(agent.get('tool') or '', RULES[''])} Do ONLY your step, "
                                          "well and briefly (under 250 words)."
                                          + (f"\nLessons you learned on earlier jobs:\n{lessons}" if lessons else "")},
            {"role": "user", "content": f"The team's job: {goal}\nYour step: {step['task']}\nDone when: {step['done_when']}\n"
                                        + (f"\nThe notebook (what the others did):\n{notes}\n" if notes else "")
                                        + (f"\nFound for this step:\n{found[:4000]}\n" if found else "")
                                        + (f"\nThe judge rejected your last try: {feedback}\nFix exactly that." if feedback else "")}]


# ---------------------------------------------------------------- the experts' tools
async def _research(task: str) -> tuple[str, list[dict]]:
    """Search, stop when nothing new turns up, OPEN the best pages; -> (text for the model, sources)."""
    from . import security, web
    if not load_settings().get("allow_web"):
        raise RuntimeError("web use isn't allowed in Settings › Internet")
    sources, seen = [], set()
    for q in (task[:200], re.sub(r"\b(find|search|look up|research|summari[sz]e|and|the|for|of|a|an)\b", " ", task, flags=re.I)[:160]):
        hits = await asyncio.to_thread(web.search, q.strip(), 6)
        new = [h for h in hits if h["url"] not in seen]
        if not new:  # Raven: a search that finds nothing new ends the searching
            break
        for h in new:
            seen.add(h["url"])
            sources.append({"n": len(sources) + 1, "title": h["title"], "url": h["url"], "text": h.get("snippet", "")})
        if len(sources) >= 6:
            break
    for s in sources[:2]:  # open the two best pages instead of trusting snippets
        try:
            page = await asyncio.to_thread(web.read, s["url"], 3000)
            s["text"] = (page.get("text") or s["text"])[:3000]
        except Exception:  # noqa: BLE001 — a page that won't open keeps its snippet
            pass
    raw = "\n\n".join(f"[{s['n']}] {s['title']} — {s['url']}\n{s['text']}" for s in sources)
    found, _ = security.untrusted("web pages read by the team's Researcher", raw, "")
    return found, sources


async def _design(task: str, chat_id: str, fix: str = "") -> tuple[str, list[dict]]:
    """The chat's own 3D pipeline (proven designs, fit check, fixes) — its card lands in the chat and the Gallery.
    A FIX — the judge found collisions, or the job is "fix the collision" — changes the chat's last model (the same
    design, its code run again through the fit fixer) instead of drawing a new one: a "fix" job once made a new lock
    with 2 collisions instead of 1."""
    from . import agent as ag
    models, text, errors = [], [], []
    ask = f"fix the collisions in the 3D model: {fix}" if fix else task
    # "/design" = the command route: built like a chat request, and (unlike a button click) not learned as a phrase;
    # a follow-up about the chat's last model goes in as plain words, so the chat treats it as a change of THAT model
    words = ask if ag.design_followup(chat_id, ask) else "/design " + task
    async for ev in ag.chat_stream(chat_id, words, [], True, None, False, None):
        try:
            e = json.loads(ev[6:])
        except ValueError:
            continue
        if e.get("model3d"):
            models.append(e["model3d"])
        if e.get("delta"):
            text.append(e["delta"])
        if e.get("error"):
            errors.append(e["error"])
    outs = [{"kind": "model3d", "id": (re.search(r"model-([0-9a-f]+)", m.get("stl") or "") or [None, None])[1],
             "label": m.get("name", "3D model"), "png": m.get("preview"), "collisions": len(m.get("collisions") or [])}
            for m in models]  # the Gallery id is the file's id (model-<id>.stl)
    return ("".join(text) or "; ".join(errors) or "no model came back").strip()[:3000], outs


async def _code(task: str, goal: str, aid: str | None = None) -> tuple[str, list[dict]]:
    """The app maker (template, use test in the browser, fixes); the folder the user asked for in the JOB ("make a folder
    on my desktop named X and …") gets the project, and the app is named like it. aid: the retry changes that app."""
    from . import apps
    wish = apps.folder_wish(goal) or apps.folder_wish(task)
    a = await apps.make(task, aid, name=wish[0] if wish and wish[0] else None)
    outs = [{"kind": "app", "id": a["id"], "label": a["name"], "ok": a.get("checked_ok", False)}]
    if wish:
        try:
            outs[0]["folder"] = apps.export(a["id"], wish[0], wish[1])
        except RuntimeError as e:
            outs[0]["folder_error"] = str(e)
    return (f"Built the app “{a['name']}” — {a.get('receipt', '')}. {a.get('note') or ''}"
            + (f" Saved as a project in {outs[0]['folder']}." if outs[0].get("folder") else "")).strip(), outs


async def _work(agent: dict, step: dict, job: dict, notes: str, feedback: str) -> tuple[str, list[dict]]:
    from .agent import calc_card, calc_summary, plugin_params
    from . import plugins
    tool, found = agent.get("tool"), ""
    made = [o for o in step.get("outputs") or [] if o.get("kind") in ("model3d", "app")]  # the try the judge rejected
    if tool == "3d":  # a rejected model is FIXED (same design), not drawn again from scratch
        return await _design(step["task"], job["chat"], feedback if feedback and made else "")
    if tool == "app":
        if feedback and made:  # the rejected app is changed, not written again
            return await _code(f"Fix this: {feedback}", job["goal"], made[0]["id"])
        return await _code(step["task"], job["goal"])
    sources: list[dict] = []
    if tool == "web":
        found, sources = await _research(step["task"])
    elif tool == "calc":
        p = plugins.calculator_for(step["task"])
        if p:
            params = await plugin_params(p, step["task"], [], None) or {}
            res = await asyncio.to_thread(plugins.run, p["id"], params)
            if res.get("calculator"):
                found = "Calculator result: " + calc_summary(calc_card(res), step["task"])
    text = await _ask(compass(agent, step, job["goal"], notes, feedback, found), 700)
    if sources:
        text += "\n\nSources:\n" + "\n".join(f"[{s['n']}] {s['title']} — {s['url']}" for s in sources)
    return text, [{"kind": "sources", "label": f"{len(sources)} sources"}] if sources else []


def scoreboard(steps: list[dict]) -> str:
    """What really happened, checked by the app — it opens the Reviewer's answer (a Reviewer once wrote "the collision
    is resolved" about a model with 2 collisions, and "the user reported 0 collisions")."""
    lines = []
    for s in steps:
        facts = []
        for o in s.get("outputs") or []:
            if o["kind"] == "model3d":
                facts.append("3D model in the Gallery — " + (f"⚠ {o['collisions']} pair(s) of parts still touch"
                                                             if o.get("collisions") else "fit check: nothing touches"))
            elif o["kind"] == "app":
                facts.append(f"app “{o['label']}” in Apps — " + ("used and tested ✓" if o.get("ok") else "⚠ still has errors")
                             + (f", saved in {o['folder']}" if o.get("folder") else ""))
            elif o["kind"] == "sources":
                facts.append(o["label"])
        why = f" — the judge: {s['judge']}" if s["status"] != "done" and s.get("judge") else ""
        lines.append(f"- {'✓' if s['status'] == 'done' else '✕'} **{s['agent']}**: {_sentences(s['task'], 100)}{why}"
                     + (f" ({'; '.join(facts)})" if facts else ""))
    ok = sum(s["status"] == "done" for s in steps)
    return f"**{ok} of {len(steps)} steps passed the judge.**\n" + "\n".join(lines)


# ---------------------------------------------------------------- the stamp: an independent judge per step
async def judge(agent: dict, step: dict, text: str, outs: list[dict]) -> tuple[bool, str]:
    tool = agent.get("tool")
    if tool == "3d":
        m = next((o for o in outs if o["kind"] == "model3d"), None)
        if not m:
            return False, "no 3D model was built: " + text[:160]
        return (True, "") if not m.get("collisions") else (False, f"{m['collisions']} pair(s) of parts collide")
    if tool == "app":
        a = next((o for o in outs if o["kind"] == "app"), None)
        return (bool(a and a.get("ok")), "" if a and a.get("ok") else "the app has errors when it runs: " + text[:160])
    if tool == "web" and "[1]" not in text:
        return False, "no sources were cited"
    if len(text.strip()) < 20:
        return False, "the answer is empty"
    try:
        v = json.loads(await _ask([{"role": "system", "content": "You are an independent judge. Check ONE expert's step result: "
                                    "does it really do the task and meet 'done when'? Be strict about missing parts and "
                                    "invented facts; style doesn't matter."},
                                   {"role": "user", "content": f"Task: {step['task']}\nDone when: {step['done_when']}\n\n"
                                                               f"Result:\n{text[:3000]}"}], 160,
                                  {"type": "object", "required": ["ok", "why"], "properties": {
                                      "ok": {"type": "boolean"}, "why": {"type": "string", "maxLength": 400}}}))
        return bool(v.get("ok")), _sentences(str(v.get("why") or ""), 260)
    except (ValueError, KeyError):
        return True, ""  # a broken verdict doesn't fail the step


# ---------------------------------------------------------------- the run
async def _run(job: dict) -> None:
    chat = job["chat"]
    try:
        team = [a for a in agents() if a.get("on")]
        if not team:
            raise RuntimeError("No expert is switched on")
        job["status"] = "planning"; _save_job(job)
        job["steps"] = await _plan(job["goal"], team)
        if not job["steps"]:
            raise RuntimeError("The plan had no usable steps")
        job["status"] = "working"; _save_job(job)
        emo = {a["name"]: a.get("emoji", "🤖") for a in team}
        _post(chat, "👥 **The team's plan**\n" + "\n".join(f"{i + 1}. {emo.get(s['agent'], '🤖')} **{s['agent']}** — {s['task']} "
                                                          f"*(done when: {s['done_when']})*" for i, s in enumerate(job["steps"])),
              {"team_step": job["id"]})
        for i, s in enumerate(job["steps"]):
            agent = next(a for a in team if a["name"] == s["agent"])
            s["status"], s["started"] = "working", time.time(); _save_job(job)
            feedback, ok, why = "", False, ""
            for attempt in (1, 2):
                try:
                    text, outs = await _work(agent, s, job, notebook(job["steps"], i), feedback)
                    ok, why = await judge(agent, s, text, outs)
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 — one expert failing doesn't sink the job
                    text, outs, ok, why = f"Couldn't do it: {str(e)[:200]}", [], False, str(e)[:200]
                s["result"], s["outputs"], s["tries"] = text[:4000], outs, attempt
                if ok:
                    if attempt == 2 and feedback:
                        _learn(agent["id"], f"Earlier a judge said: {feedback}. Get that right the first time.")
                    break
                feedback = why or "it doesn't meet 'done when'"
            s["status"], s["judge"], s["ended"] = ("done" if ok else "failed"), ("" if ok else why), time.time()
            _save_job(job)
            verdict = "✓" if ok else f"✕ (the judge: {why})"
            if agent.get("tool") == "3d":  # the 3D pipeline already wrote its card into the chat: just the verdict
                _post(chat, f"{agent.get('emoji', '🤖')} **{agent['name']}** {verdict} — the 3D model is just above "
                            "(and in the Gallery).", {"team_step": job["id"]})
            else:
                _post(chat, f"{agent.get('emoji', '🤖')} **{agent['name']}** {verdict}\n\n{s['result']}",
                      {"team_step": job["id"],
                       **({"apps": [o for o in outs if o["kind"] == "app"]} if any(o["kind"] == "app" for o in outs) else {})})
        job["status"] = "reviewing"; _save_job(job)
        board = scoreboard(job["steps"])
        text = await _ask([
            {"role": "system", "content": "You are the Reviewer (the final stamp) of a small AI team. Write the final answer "
                                          "for the user: what was done, the results, what failed or is missing. Short, clear, "
                                          "honest. The FACTS are checked by the app and always true: never contradict them, "
                                          "never call a failed step done, never invent what the user said or did."},
            {"role": "user", "content": f"The job: {job['goal']}\n\nFACTS:\n{board}\n\nThe notebook:\n"
                                        f"{notebook(job['steps'], len(job['steps']))}"}], 800)
        job["final"] = board + "\n\n" + text  # the checked facts first, the Reviewer's words after them
        _post(chat, "🧐 **Reviewer — the result**\n\n" + job["final"], {"team_step": job["id"]})
        job["status"] = "done"
    except asyncio.CancelledError:
        job["status"] = "stopped"
    except Exception as e:  # noqa: BLE001
        job["status"], job["error"] = "failed", str(e)[:300]
        _post(chat, f"👥 The team stopped: {job['error']}", {"team_step": job["id"]})
    finally:
        job["ended"] = time.time()
        _save_job(job)
        RUNNING.pop(job["id"], None)
        _next()


def start(goal: str, daily: str = "", chat_id: str | None = None) -> dict:
    """A job for the team. While it's busy with another one, the job WAITS in the queue and starts by itself (a door
    lock asked for during a phone stand job used to be turned away: "stop it or wait")."""
    if not load_settings().get("team_on"):
        raise RuntimeError("The agent team is off — switch it on in Team first (it needs computing power)")
    if not chat_id:  # from the Team page: a chat of its own, so every result is in one place
        chat_id = uuid.uuid4().hex
        db.run("INSERT INTO chats VALUES (?,?,?,?)", (chat_id, ("👥 " + goal.strip())[:60], time.time(), time.time()))
    job = {"id": uuid.uuid4().hex[:10], "goal": goal.strip()[:1000], "status": "waiting", "steps": [], "final": "",
           "created": time.time(), "chat": chat_id, "daily": daily if re.fullmatch(r"\d{2}:\d{2}", daily or "") else ""}
    if RUNNING or QUEUE:
        job["status"], job["ahead"] = "queued", len(RUNNING) + len(QUEUE)
        QUEUE.append(job)
        _save_job(job)
        return job
    _launch(job)
    return job


def _launch(job: dict) -> None:
    RUNNING[job["id"]] = asyncio.get_running_loop().create_task(_run(job))  # (needs the server's loop: async routes)
    _save_job(job)
    _ensure_loop()


def _next() -> None:
    """The job before is over: the next one in the queue starts (if the team is still on)."""
    while QUEUE and not RUNNING:
        job = QUEUE.pop(0)
        if load_settings().get("team_on"):
            job["status"] = "waiting"
            _launch(job)
        else:
            job["status"] = "stopped"
            _save_job(job)


def stop(jid: str) -> None:
    for job in [j for j in QUEUE if j["id"] == jid]:  # a queued job: taken out of the queue
        QUEUE.remove(job)
        job["status"] = "stopped"
        _save_job(job)
    t = RUNNING.get(jid)
    if t:
        t.cancel()


def stop_all() -> int:
    n = len(RUNNING) + len(QUEUE)
    while QUEUE:  # first the queue, or the next job would start the moment the running one stops
        job = QUEUE.pop()
        job["status"] = "stopped"
        _save_job(job)
    for t in list(RUNNING.values()):
        t.cancel()
    return n


def delete(jid: str) -> None:
    stop(jid)
    _write("jobs.json", [j for j in jobs() if j["id"] != jid])


def _ensure_loop() -> None:
    global _loop_started
    if not _loop_started:
        _loop_started = True
        from . import memory
        memory.background(_daily_loop())


async def _daily_loop() -> None:
    """The on-call worker: jobs marked "every day at HH:MM" start again then (only while the team is on and idle)."""
    while True:
        await asyncio.sleep(60)
        if not load_settings().get("team_on") or RUNNING:
            continue
        now, today = time.strftime("%H:%M"), time.strftime("%Y-%m-%d")
        for j in jobs():
            if j.get("daily") == now and j.get("ran_on") != today:
                j["ran_on"] = today
                _save_job(j)
                try:
                    start(j["goal"], j["daily"], j.get("chat"))
                except RuntimeError:
                    pass
                break


def init() -> None:
    """At start: jobs that were running when the app closed are marked stopped; the daily loop starts."""
    for j in jobs():
        if j.get("status") in ("waiting", "queued", "planning", "working", "reviewing"):
            j["status"] = "stopped"
            _save_job(j)
    if any(j.get("daily") for j in jobs()):
        _ensure_loop()
