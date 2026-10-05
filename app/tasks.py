"""Background tasks (like Claude Code's panel): long work runs on its own while you do something else, and it's all
listed in ONE place — an app being made, a new skill, the team's jobs, computer use, 3D builds, pictures / videos,
model downloads — with its status, how long it's been going, Stop and Open. The page polls GET /api/tasks: a task that
finishes shows a notice, and the chat it belongs to refreshes by itself.
Apps and skills asked for in a chat (or on their pages) are made HERE, in the background: the chat answers at once and
the result is posted into that chat when it's ready (like the team does)."""
import asyncio
import json
import time
import uuid

from . import db

JOBS: dict[str, dict] = {}  # this module's own jobs (apps, skills): {id, kind, title, status, started, ended, chat, …}
KEEP = 3 * 3600  # finished tasks stay in the list for 3 hours


def post(chat_id: str, text: str, extra: dict | None = None) -> None:
    """A background job's result as a message in its chat."""
    if not chat_id or not db.q("SELECT 1 FROM chats WHERE id=?", (chat_id,)):
        return
    db.run("INSERT INTO messages(chat_id, role, content, extra, created) VALUES (?,?,?,?,?)",
           (chat_id, "assistant", text, json.dumps({"tools": [], **(extra or {})}), time.time()))
    db.run("UPDATE chats SET updated=? WHERE id=?", (time.time(), chat_id))


def start(kind: str, title: str, coro, chat: str = "", done=None, failed=None) -> dict:
    """Runs coro in the background (needs the server's loop: call from an async route / the chat stream).
    done(result) -> {"note", "open", "text", "extra"} when it finishes: text + extra are posted into the chat;
    failed(error) -> the text to post when it fails."""
    for k in [k for k, j in JOBS.items() if j["status"] != "running" and time.time() - j.get("ended", 0) > KEEP]:
        JOBS.pop(k, None)
    job = {"id": uuid.uuid4().hex[:10], "kind": kind, "title": title.strip()[:90], "status": "running",
           "started": time.time(), "chat": chat or "", "note": "", "open": None}

    async def run():
        try:
            out = (done(await coro) if done else None) or {}
            job.update(status="done", note=out.get("note", ""), open=out.get("open"))
            if out.get("text"):
                post(job["chat"], out["text"], out.get("extra"))
        except asyncio.CancelledError:
            job["status"] = "stopped"
            post(job["chat"], f"■ Stopped: {job['title']}")
        except Exception as e:  # noqa: BLE001 — the job's own error, shown on the task and in the chat
            job.update(status="failed", error=str(e)[:300])
            post(job["chat"], failed(e) if failed else f"✕ {job['title']} — {e}")
        finally:
            job["ended"] = time.time()
            job.pop("task", None)
    job["task"] = asyncio.get_running_loop().create_task(run())
    JOBS[job["id"]] = job
    return public(job)


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k != "task"}


def stop(tid: str) -> bool:
    """Stop by the task's id in the list ("team:…", "computer:…", "3d:…", "render:…", "download:…" or our own)."""
    from . import computer, models, plugins, team
    from .jobs import renderer
    kind, _, rid = tid.partition(":")
    if not rid:
        job = JOBS.get(tid)
        if job and job.get("task"):
            job["task"].cancel()
            return True
        return False
    {"team": team.stop, "computer": computer.stop, "3d": plugins.run_stop, "render": renderer.cancel,
     "download": models.cancel_download}.get(kind, lambda _x: None)(rid)
    return True


def listing() -> list[dict]:
    """Everything going on (and what finished in the last hours), newest first."""
    from . import computer, models, plugins, team
    from .jobs import renderer
    now, out = time.time(), [public(j) for j in JOBS.values()]
    running, queued = set(team.RUNNING), {j["id"] for j in team.QUEUE}
    for j in team.jobs()[:12]:
        st = "running" if j["id"] in running else "queued" if j["id"] in queued else \
            {"done": "done", "failed": "failed"}.get(j["status"], "stopped")
        if st in ("running", "queued") or now - j.get("ended", j["created"]) < KEEP:
            steps = j.get("steps") or []
            out.append({"id": f"team:{j['id']}", "kind": "team", "title": j["goal"][:90], "status": st,
                        "started": j["created"], "ended": j.get("ended"), "chat": j.get("chat", ""),
                        "note": f"{sum(s['status'] in ('done', 'failed') for s in steps)} of {len(steps)} steps" if steps else "",
                        "open": {"page": "chat", "chat": j.get("chat")} if j.get("chat") else {"page": "team"}})
    for t in list(computer.tasks.values()):
        live = t.status in ("thinking", "waiting", "running")
        if live or now - t.created < KEEP:
            out.append({"id": f"computer:{t.id}", "kind": "computer", "title": t.goal[:90],
                        "status": "waiting" if t.status == "waiting" else "running" if live else
                        {"done": "done", "failed": "failed"}.get(t.status, "stopped"),
                        "started": t.created, "note": "waiting for your OK" if t.status == "waiting" else f"step {len(t.steps)}",
                        "open": {"page": "computer"}, "error": t.error})
    for r in plugins.active():
        out.append({"id": f"3d:{r['id']}", "kind": "3d", "title": r["text"][:90], "status": "running",
                    "started": now - (r.get("elapsed") or 0), "note": f"{round(100 * (r.get('pct') or 0))} %",
                    "open": {"page": "gallery"}})
    for j in list(renderer.jobs.values()):
        st = {"queued": "queued", "running": "running", "done": "done", "failed": "failed", "error": "failed"}.get(j["status"], "stopped")
        if st in ("queued", "running") or now - j.get("created", 0) < KEEP:
            out.append({"id": f"render:{j['id']}", "kind": "picture" if j["kind"] == "image" else "video",
                        "title": (j.get("prompt") or "")[:90], "status": st, "started": j.get("created", now),
                        "note": f"{round(100 * (j.get('progress') or 0))} %" if st == "running" else "",
                        "open": {"page": "gallery"}, "error": j.get("error")})
    for d in [d for d in list(models.downloads.values()) if d["status"] == "running"]:  # (the rest: Models page)
        out.append({"id": f"download:{d['id']}", "kind": "download", "title": d.get("name", "a model")[:90],
                    "status": "running", "started": d.get("started", now),
                    "note": f"{round(100 * (d.get('progress') or 0))} %", "open": {"page": "models"}})
    order = {"waiting": 0, "running": 1, "queued": 2}
    return sorted(out, key=lambda x: (order.get(x["status"], 3), -(x.get("started") or 0)))[:40]
