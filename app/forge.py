"""The Forge: NEW SKILLS the local AI writes for itself (like Brahma Evo's self-made skills, but safe and yours to approve):
1. you ask in plain words ("make a skill that shows my CPU and RAM use") — in a chat or on the Forge page;
2. the AI writes it as a small Python file of a fixed shape (NAME, DESCRIPTION, INPUTS, run(), a self-test test());
3. the app CHECKS it (anything forbidden is refused before it runs) and RUNS its self-test in the sandbox
   (app/forge_box.py: its own locked process — no files, no network, no programs, 512 MB, 20 s); what fails goes back
   to the AI to fix, 2 rounds — the same harness as the app maker;
4. it arrives as a DRAFT the chat can't use: you try it (its inputs, ▶ Run) and Turn it on — or don't.
Every version is kept as a backup (versions/v1.py, v2.py …). A change is a new draft and the version that's on STAYS on
until you turn the new one on; Undo removes the newest version; any version can be turned (back) on. Skills that are on
are tools for the chat ("skill_<id>"), and run in the same sandbox every time. Saved in data/forge/<id>/."""
import ast
import asyncio
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .config import DATA, NO_WINDOW, load_settings
from .forge_box import ALLOWED, check
from .plat import kill_tree, spawn
from . import codecheck, wipe

DIR = DATA / "forge"
RUNS = DATA / "forge-runs"
BOX = Path(__file__).with_name("forge_box.py")
TIMEOUT = 20
MAKING: dict[str, asyncio.Task] = {}
SYSTEM = f"""You write ONE new skill for a local AI assistant: a small, self-contained Python file in exactly this shape:
NAME = "Short name"
DESCRIPTION = "One sentence: what it does (the assistant reads this to know when to use it)."
INPUTS = {{"seconds": {{"type": "number", "description": "how long to measure", "default": 1}}}}   # {{}} when it needs none
def run(seconds=1):   # its keyword arguments = the INPUTS, each with its default; returns numbers, text, a list or a dict
    ...
def test():           # calls run() and checks the result with assert; it must pass
    ...
It runs in a locked sandbox:
- import ONLY: {", ".join(sorted(ALLOWED))}. No files, no network, no programs (no os, sys, subprocess, requests).
- `import system` gives this PC's numbers (read-only): system.cpu_percent(seconds=0.5) -> float (%),
  system.memory() -> {{"total_gb", "used_gb", "free_gb", "percent"}}, system.disks() -> list of {{"drive", "total_gb",
  "free_gb", "percent_used"}}, system.battery() -> {{"percent", "plugged_in"}} or None, system.uptime_hours() -> float,
  system.info() -> {{"os", "machine", "cpu_cores", "python"}}.
- Never use open, eval, exec, getattr, globals, vars, dir, or any name starting with _ (like __class__).
- It must finish in a few seconds and return plain data. Keep it short and clear (under ~120 lines).
Answer with the file in ONE ```python block and one short sentence before it."""


def _path(sid: str) -> Path:
    return DIR / re.sub(r"[^0-9a-f]", "", sid)


def _load(sid: str) -> dict:
    return json.loads((_path(sid) / "skill.json").read_text(encoding="utf-8"))


def _save(meta: dict) -> None:
    (_path(meta["id"]) / "skill.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")


def code_of(sid: str, version: int | None = None) -> str:
    meta = _load(sid)
    return (_path(sid) / "versions" / f"v{version or meta['versions']}.py").read_text(encoding="utf-8")


def listing() -> list[dict]:
    out = []
    if DIR.exists():
        for d in DIR.iterdir():
            try:
                m = json.loads((d / "skill.json").read_text(encoding="utf-8"))
                out.append({k: m.get(k) for k in ("id", "name", "description", "versions", "active", "updated", "tests")})
            except (OSError, ValueError):
                continue
    return sorted(out, key=lambda m: -(m.get("updated") or 0))


def get(sid: str) -> dict:
    meta = _load(sid)
    return {**meta, "code": code_of(sid), "active_code": code_of(sid, meta["active"]) if meta.get("active") else ""}


def _shape(code: str) -> dict:
    """NAME, DESCRIPTION and INPUTS read from the file as plain values (literal_eval: nothing of it runs here)."""
    out = {"name": "", "description": "", "inputs": {}}
    try:
        for n in ast.parse(code).body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                key = {"NAME": "name", "DESCRIPTION": "description", "INPUTS": "inputs"}.get(n.targets[0].id)
                if key:
                    out[key] = ast.literal_eval(n.value)
    except (SyntaxError, ValueError):
        pass
    if not isinstance(out["inputs"], dict):
        out["inputs"] = {}
    out["inputs"] = {str(k)[:40]: v for k, v in list(out["inputs"].items())[:8] if isinstance(v, dict)}
    return out


def _extract(text: str) -> tuple[str | None, str]:
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.S | re.I)
    code = m.group(1) if m else (text.split("```python", 1)[1] if "```python" in text else None)
    return (code.strip() + "\n" if code else None), (text[:m.start()].strip()[:300] if m else "")


def _python() -> str:
    """The app's Python, its console-less twin on Windows (no black window flashes up)."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def box(code: str, mode: str = "test", params: dict | None = None) -> dict:
    """One run in the sandbox (blocking: call in a thread). -> {ok, result | error, seconds, printed}"""
    work = RUNS / uuid.uuid4().hex[:12]
    work.mkdir(parents=True)
    try:
        (work / "skill.py").write_text(code, encoding="utf-8")
        (work / "params.json").write_text(json.dumps(params or {}), encoding="utf-8")
        p = spawn([_python(), "-I", "-X", "utf8", str(BOX), "skill.py", mode, "params.json"], cwd=str(work),
                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        try:
            out, err = p.communicate(timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            kill_tree(p.pid)
            p.communicate()
            return {"ok": False, "error": f"it ran longer than {TIMEOUT} seconds and was stopped"}
        line = next((x for x in reversed(out.decode("utf-8", "ignore").splitlines()) if x.startswith("{")), "")
        if not line:
            return {"ok": False, "error": "the sandbox gave no answer" + (f": {err.decode('utf-8', 'ignore')[-300:]}" if err else "")}
        return json.loads(line)
    finally:
        wipe.shred_tree(work)


async def make(prompt: str, sid: str | None = None) -> dict:
    """A new skill from the words, or (sid) a changed version of it — always a DRAFT, tested in the sandbox."""
    from .agent import chat_model
    from .jobs import renderer
    from .llm import llm
    from .team import clean
    model = chat_model()
    if not model:
        raise RuntimeError("No chat model yet — download one in Models › Text")
    old = code_of(sid) if sid else None
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"The skill now:\n```python\n{old}```\n\nChange it: {prompt}\nReturn the COMPLETE new file."
             if old else f"The new skill: {prompt}"}]

    async def write(messages: list[dict]) -> tuple[str | None, str]:
        while llm.busy > 0:  # a chat answer first
            await asyncio.sleep(0.5)
        await llm.ensure(model, max(int(load_settings()["ctx"]), 8192), not renderer.busy())
        llm.busy += 1
        try:
            r = await llm.complete(messages, temperature=0.3, max_tokens=3000, chat_template_kwargs={"enable_thinking": False})
        finally:
            llm.busy -= 1
        return _extract(clean(r.get("content") or ""))
    code, note = await write(msgs)
    if not code:
        raise RuntimeError("The model didn't write the skill — try saying it more simply")
    problems, tries = [], 0
    for rnd in range(3):  # check (sandbox rules + pyflakes), test in the sandbox, fix — the fix is checked and tested again
        problems = check(code) + codecheck.python_problems(code)
        if not problems:
            res = await asyncio.to_thread(box, code, "test")
            problems = [] if res.get("ok") else [str(res.get("error") or "the test failed")[:400]]
        if not problems or rnd == 2:
            break
        tries += 1
        fixed, _ = await write([msgs[0], {"role": "user", "content": "The skill fails the checks / the sandbox:\n- "
                                          + "\n- ".join(codecheck.with_lines(problems, code))
                                          + f"\n\nThe file:\n```python\n{code}```\nFix exactly that. Return the COMPLETE file."}])
        if fixed:
            code = fixed
    shape = _shape(code)
    sid = sid or uuid.uuid4().hex[:10]
    d = _path(sid)
    (d / "versions").mkdir(parents=True, exist_ok=True)
    meta = _load(sid) if old else {"id": sid, "created": time.time(), "prompts": [], "versions": 0, "active": 0, "tests": {}}
    meta["versions"] += 1
    v = meta["versions"]
    (d / "versions" / f"v{v}.py").write_text(code, encoding="utf-8")
    meta["tests"][str(v)] = not problems
    meta["prompts"] = (meta.get("prompts") or []) + [prompt[:500]]
    meta.update(name=str(shape["name"] or meta.get("name") or prompt[:40]).strip()[:60],
                description=str(shape["description"] or "")[:300], inputs=shape["inputs"], updated=time.time(),
                note=note, receipt=("passed the code check (pyflakes + sandbox rules) and its self-test in the sandbox"
                                    + (f" (fixed in {tries} round(s))" if tries else "")
                                    if not problems else "still fails: " + "; ".join(problems)[:300]))
    _save(meta)
    return get(sid)


def run(sid: str, params: dict | None = None, version: int | None = None) -> dict:
    """▶ Run on the Forge page (the newest version: the draft you're trying)."""
    meta = _load(sid)
    params = {k: v for k, v in (params or {}).items() if k in (meta.get("inputs") or {})}
    return box(code_of(sid, version), "run", params)


def turn_on(sid: str, version: int | None = None) -> dict:
    meta = _load(sid)
    v = int(version or meta["versions"])
    if not (_path(sid) / "versions" / f"v{v}.py").exists():
        raise RuntimeError("That version isn't there")
    if not meta.get("tests", {}).get(str(v)):
        raise RuntimeError("This version didn't pass its self-test — change it (or go back a version) first")
    meta["active"], meta["updated"] = v, time.time()
    _save(meta)
    return get(sid)


def turn_off(sid: str) -> dict:
    meta = _load(sid)
    meta["active"], meta["updated"] = 0, time.time()
    _save(meta)
    return get(sid)


def undo(sid: str) -> dict:
    """Removes the newest version (a change you didn't like). If it was the one that's on, the skill goes off."""
    meta = _load(sid)
    if meta["versions"] < 2:
        raise RuntimeError("There's no earlier version — delete the skill instead")
    v = meta["versions"]
    wipe.shred(_path(sid) / "versions" / f"v{v}.py")
    meta["tests"].pop(str(v), None)
    meta["versions"] -= 1
    if meta.get("active") == v:
        meta["active"] = 0
    meta["prompts"] = meta["prompts"][:-1]
    shape = _shape(code_of(sid))
    meta.update(name=shape["name"] or meta["name"], description=shape["description"] or meta["description"],
                inputs=shape["inputs"], updated=time.time())
    _save(meta)
    return get(sid)


def delete(sid: str) -> None:
    d = _path(sid)
    if d.exists() and DIR in d.parents:
        wipe.shred_tree(d)


# ---------------------------------------------------------------- the chat uses the skills that are ON
def tools() -> list[dict]:
    out = []
    for m in listing():
        if not m.get("active"):
            continue
        try:
            inputs = _shape(code_of(m["id"], m["active"]))["inputs"]
        except OSError:
            continue
        props = {k: {"type": v.get("type") if v.get("type") in ("number", "string", "boolean", "integer") else "string",
                     "description": str(v.get("description") or "")[:150]} for k, v in inputs.items()}
        out.append({"type": "function", "function": {
            "name": f"skill_{m['id']}", "description": f"(A skill you made: {m['name']}) {m.get('description') or ''}"[:400],
            "parameters": {"type": "object", "properties": props}}})
    return out


def call(sid: str, args: dict) -> dict:
    """The chat calls a skill that's on: its approved version, in the sandbox."""
    try:
        meta = _load(sid)
    except (OSError, ValueError):
        return {"error": "that skill isn't there any more"}
    if not meta.get("active"):
        return {"error": f"the skill “{meta.get('name')}” is switched off"}
    args = {k: v for k, v in (args or {}).items() if k in (_shape(code_of(sid, meta["active"]))["inputs"])}
    r = box(code_of(sid, meta["active"]), "run", args)
    return {"skill": meta["name"], **({"result": r.get("result")} if r.get("ok") else {"error": r.get("error")}),
            **({"printed": r["printed"]} if r.get("printed") else {})}
