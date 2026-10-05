"""Geometric reasoning (Memory › Reasoning, setting geo_reasoning) — compute, don't guess.
The idea from Sophontic AI (reasoning that follows the structure of the problem, tested by perturbation) can't be
switched on inside a model you already have: that's how a model is TRAINED. What the app can do is make a small model
stop guessing numbers (next-word statistics, where a 4B model fails at sizes, angles and logic) and WORK THEM OUT:
1. the model writes the question as a small program: every quantity a named input (positions and sizes as coordinates
   and vectors, with units), the steps one per line, then the result;
2. the program runs in the Forge sandbox (app/forge_box.py: no files, no network, no programs, 512 MB, 20 s);
3. the PERTURBATION TEST (as in the video): the same program with the inputs changed must react — a hard-coded or
   memorised number doesn't;
4. the chat model answers FROM the computed result; a 📐 card shows the inputs, the steps, the check and the code.
Only for questions that need it (numbers with sizes / units / "how many…", geometry, dates, logic) and that no
calculator plugin already answers; about 10-30 s more. Things to MAKE (pictures, 3D, apps) never come here."""
import ast
import asyncio
import json
import math
import re

from . import codecheck, forge
from .forge_box import check

NUMBER = re.compile(r"\d")
CUES = re.compile(r"\b(how (many|much|far|long|big|tall|wide|deep|heavy|fast|old|often)|calculat\w*|comput\w*|solve|work out|"
                  r"area|volume|perimeter|circumference|diameter|radius|angle|degrees?|distance|length|width|height|depth|"
                  r"weight|mass|density|speed|velocity|percent|ratio|average|mean|sum|total|difference|fits?|clearance|gap|"
                  r"tolerance|torque|force|pressure|cost|price|per|each|times|divided|multiplied|plus|minus|squared?|cubed?|"
                  r"sqrt|root|mm|cm|km|kg|ml|inch\w*|feet|ft|lbs?|days?|weeks?|months?|years?|hours?|minutes?|seconds?|"
                  r"c[aâ]t|c[aâ]te|calculeaz\w*|arie|volum|distan[tț]\w*|unghi\w*|lungime|l[aă][tț]ime|[iî]n[aă]l[tț]ime)\b|%|°|\d\s*[x×*/+^-]\s*\d",
                  re.I)
LOGIC = re.compile(r"\b(older|younger|taller|shorter|faster|slower|heavier|lighter|bigger|smaller) than\b.*\?|"
                   r"\bhow many ways\b|\bprobabilit\w*\b|\bodds\b|\bpuzzle\b|\briddle\b", re.I | re.S)
MAKING = re.compile(r"\b(make|create|build|design|draw|generate|render|print|model|3d|stl|picture|image|photo|video|movie|"
                    r"song|poem|story|app|game|website|f[aă]-?mi|deseneaz\w*|creeaz\w*|construie\w*)\b", re.I)
MAKE_START = re.compile(r"^\s*(please\s+|pls\s+)?((can|could|would|will) you\s+)?(make|create|build|design|draw|generate|"
                        r"render|print|model|write|f[aă]|deseneaz\w*|creeaz\w*|construie\w*)\b", re.I)
COUNTING = re.compile(r"\bhow many\b|\bc[aâ]te\b|\bc[aâ]t de mult\w*\b", re.I)  # counting is worked out, not a calculator
QUESTION = re.compile(r"\?|\b(how|what|which|will|does|do|is|are|can|c[aâ]t|c[aâ]te|ce|cum)\b", re.I)
SYSTEM = """You solve the question by COMPUTING, never by guessing. Write ONE Python file in this shape (the example is
a different question — only copy its SHAPE):
import math
def solve(ladder_m=5.0, foot_from_wall_m=1.5):   # EVERY number in the question is a named input, its value the default
    # the ladder, the wall and the ground make a right triangle; the ladder is the long side
    height_m = math.sqrt(ladder_m ** 2 - foot_from_wall_m ** 2)            # Pythagoras
    angle_deg = math.degrees(math.acos(foot_from_wall_m / ladder_m))      # angle with the ground
    return {"answer": round(height_m, 2), "unit": "m", "steps": {"height_m": round(height_m, 2), "angle_deg": round(angle_deg, 1)}}
def run(**inputs):
    return solve(**inputs)
def test():
    assert solve()["answer"] is not None
Rules: use EVERY number in the question. Think about the shapes: a plate, bed or floor is 2-D (rows AND columns), a box
3-D; gaps go between the items; positions as coordinates (x, y, z), angles in degrees (math.radians to compute); round
only at the end. One step per line with units in comments. Import only math, fractions, decimal, itertools, datetime,
statistics. No input(), no files. The answer: a number, True/False or a short text. ONE ```python block, nothing else."""
FACTORS = (1.37, 0.66, 1.21, 0.83, 1.53, 0.71)  # each input changed by a DIFFERENT amount (the same one keeps ratios)


def needs(text: str) -> bool:
    """A question that needs exact working out (not a request to make something)."""
    t = text.strip()  # "make a 20 mm cube" is made, not computed; "how long will a 20 mm cube take to print?" is computed
    if not 8 <= len(t) <= 1500 or MAKE_START.match(t) or (MAKING.search(t) and not QUESTION.search(t)):
        return False
    return bool(LOGIC.search(t) or (NUMBER.search(t) and CUES.search(t)))


LAYA_CRITERIA = {
    "compute": "the answer needs exact working out with numbers: sizes, distances, angles, areas, volumes, weights, counts, "
               "times, dates, money, speeds, probabilities, or a logic puzzle",
    "words": "no exact working out: an explanation, advice, an opinion, a story, small talk, a fact to look up, or a "
             "request to make something (a picture, a 3D model, an app)"}
EXAMPLES = None  # data/laya/geo-examples.jsonl, set on first use: Laya's decisions + how the working out went


async def should(text: str) -> tuple[bool, str]:
    """Compute this one? Laya (System 1, ~0.4 s on the processor) decides, the word rules are the safety net:
    the rules' clear cases run unless Laya is very sure it's just words; a message with a number the rules missed (a word
    problem, another language) runs when Laya is sure it needs working out. -> (compute?, who decided)."""
    rules = needs(text)
    candidate = rules or (bool(NUMBER.search(text)) and len(text) < 500 and not MAKE_START.match(text.strip()))
    if not candidate:
        return False, "rules"
    from .agent import decide
    from .config import load_settings
    from .laya import laya
    if not (load_settings().get("laya", True) and laya.available()):
        return rules, "rules"
    try:
        probs, who, sure = await decide(f"Message: {text[:400]}", "compute", "Does a good answer to this message need exact "
                                        "working out with numbers or logic, or just words?", LAYA_CRITERIA)
    except Exception:  # noqa: BLE001 — Laya not there / not answering: the rules decide
        return rules, "rules"
    p = probs.get("compute", 0.0) if probs else 0.0
    if not probs:
        return rules, "rules"
    go = p >= 0.75 if not rules else probs.get("words", 0.0) < 0.85
    return go, f"Laya {p:.0%} compute" + ("" if go == rules else " (over the word rules)")


def remember(text: str, decided: str, ran: bool, card: dict | None) -> None:
    """One training example for Laya later: the message, who decided, and whether the working out held up."""
    global EXAMPLES
    import time
    from .config import DATA
    try:
        if EXAMPLES is None:
            EXAMPLES = DATA / "laya" / "geo-examples.jsonl"
            EXAMPLES.parent.mkdir(parents=True, exist_ok=True)
        ok = bool(card) and not str(card.get("check", "")).startswith(("⚠", "failed"))
        with EXAMPLES.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time()), "text": text[:600], "decided": decided, "ran": ran,
                                "label": "compute" if ran and ok else "unclear" if ran else "words",
                                "check": (card or {}).get("check")}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _inputs(code: str) -> dict:
    """solve()'s inputs with their number defaults (read, never run here)."""
    try:
        fn = next(n for n in ast.parse(code).body if isinstance(n, ast.FunctionDef) and n.name == "solve")
    except (SyntaxError, StopIteration):
        return {}
    args = fn.args.args[len(fn.args.args) - len(fn.args.defaults):]
    out = {}
    for a, d in zip(args, fn.args.defaults):
        try:
            v = ast.literal_eval(d)
        except ValueError:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[a.arg] = v
    return out


def _perturbed(inputs: dict) -> dict:
    """The same question with other numbers, like a perturbation test: every input changed by a different factor
    (scaling all of them by the same amount kept "220 / 20" and "301 / 27" at the same answer — a false alarm)."""
    out = {}
    for k, (name, v) in enumerate(inputs.items()):
        f = FACTORS[k % len(FACTORS)]
        if isinstance(v, int):
            nv = round(v * f)
            out[name] = v + 1 if nv == v or (v > 0 and nv <= 0) else nv  # a count stays a count (no 0 or less)
        else:
            out[name] = round(v * f, 4) if v else 0.5
    return out


def _num(x):
    return x if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


async def solve(question: str, context: str = "") -> dict | None:
    """-> the card (answer, unit, steps, inputs, the perturbation check, code) or None when it couldn't be worked out."""
    from .llm import llm

    async def write(messages: list[dict]) -> str | None:
        llm.busy += 1  # a background app / skill waits while the chat works this out
        try:
            r = await llm.complete(messages, temperature=0.2, max_tokens=900, chat_template_kwargs={"enable_thinking": False})
        finally:
            llm.busy -= 1
        text = r.get("content") or ""
        m = re.search(r"```(?:python|py)?\s*\n(.*?)(?:```|$)", text, re.S | re.I)  # (a cut-off block counts too)
        if m:
            return m.group(1).strip() + "\n"
        return text.strip() + "\n" if re.search(r"^def solve\(", text, re.M) else None  # a bare file, no fences
    ask = [{"role": "system", "content": SYSTEM},
           {"role": "user", "content": (f"Earlier in the chat: {context[-600:]}\n\n" if context else "") + f"The question: {question}"}]
    code, res = await write(ask), None
    for _ in range(2):  # check + run; one fix round with the exact error and its line
        if not code:
            return None
        problems = check(code) + codecheck.python_problems(code)
        if not problems:
            res = await asyncio.to_thread(forge.box, code, "run", {})
            if res.get("ok") and isinstance(res.get("result"), dict) and "answer" in res["result"]:
                break
            problems = [str(res.get("error") or "solve() must return a dict with an \"answer\"")[:300]]
        res = None
        code = await write([*ask, {"role": "assistant", "content": f"```python\n{code}```"},
                            {"role": "user", "content": "It fails:\n- " + "\n- ".join(codecheck.with_lines(problems, code))
                                                        + "\nFix it. The COMPLETE file in one ```python block."}])
    if not res:
        return None
    out, inputs = res["result"], _inputs(code)
    card = {"answer": out.get("answer"), "unit": str(out.get("unit") or "")[:30], "inputs": inputs,
            "steps": {str(k)[:40]: v for k, v in list((out.get("steps") or {}).items())[:8]} if isinstance(out.get("steps"), dict) else {},
            "code": code[:4000], "check": "no inputs to change"}
    if inputs:  # the perturbation test: other numbers in -> the answer must react (a hard-coded one doesn't)
        alt = _perturbed(inputs)
        r2 = await asyncio.to_thread(forge.box, code, "run", alt)
        a2 = (r2.get("result") or {}).get("answer") if r2.get("ok") and isinstance(r2.get("result"), dict) else None
        same = a2 == card["answer"]
        card["perturbed"] = {"inputs": alt, "answer": a2}
        card["check"] = ("failed with other numbers: " + str(r2.get("error"))[:120] if not r2.get("ok") else
                         "⚠ the answer did NOT change when the numbers changed — it may be hard-coded"
                         if same and _num(card["answer"]) is not None else
                         "reacts to other numbers ✓" if not same else "same yes/no with bigger numbers (fine)")
    return card


async def edit(prev: dict, question: str) -> dict | None:
    """A follow-up to a worked-out answer ("and with a 3 mm gap?", "what if the bed is 256 mm?"): the idea of Context
    Language Models (UW + Meta, 2026 — the model EDITS its working context instead of rebuilding it) where a small model
    does it reliably: the working context is the last program and its named inputs; the model only says which inputs
    change (a tiny JSON answer), the same program runs again. Seconds instead of a new program. None = not an edit."""
    from .llm import llm
    inputs = prev.get("inputs") or {}
    if not inputs or not prev.get("code"):
        return None
    schema = {"type": "object", "properties": {k: {"type": "number"} for k in inputs}}
    llm.busy += 1
    try:
        r = await llm.complete([
            {"role": "system", "content": "A question was worked out by a program with these named inputs. The user asks a "
                                          "follow-up. Return ONLY the inputs that change, with their new values in the same "
                                          "units, as JSON. Return {} if the follow-up asks something new instead."},
            {"role": "user", "content": f"Inputs: {json.dumps(inputs)}\nFollow-up: {question}"}],
            temperature=0, max_tokens=200, chat_template_kwargs={"enable_thinking": False},
            response_format={"type": "json_schema", "json_schema": {"name": "edit", "schema": schema}})
        asked = json.loads(r.get("content") or "{}")
    except Exception:  # noqa: BLE001 — not an edit after all: a full working out follows
        return None
    finally:
        llm.busy -= 1
    changes = {k: v for k, v in (asked or {}).items() if k in inputs and _num(v) is not None and v != inputs[k]}
    if not changes:
        return None
    new = {**inputs, **{k: (int(v) if isinstance(inputs[k], int) and float(v).is_integer() else v) for k, v in changes.items()}}
    res = await asyncio.to_thread(forge.box, prev["code"], "run", new)
    if not (res.get("ok") and isinstance(res.get("result"), dict) and "answer" in res["result"]):
        return None
    out = res["result"]
    return {"answer": out.get("answer"), "unit": str(out.get("unit") or prev.get("unit") or "")[:30], "inputs": new,
            "steps": {str(k)[:40]: v for k, v in list((out.get("steps") or {}).items())[:8]} if isinstance(out.get("steps"), dict) else {},
            "code": prev["code"], "changed": {k: [inputs[k], new[k]] for k in changes},
            "check": "the same checked program, run again with your change"}


def note(card: dict) -> str:
    """What the chat model gets: the computed result to answer from."""
    steps = "; ".join(f"{k} = {v}" for k, v in card["steps"].items())
    changed = "; ".join(f"{k}: {a} → {b}" for k, (a, b) in (card.get("changed") or {}).items())
    return ("COMPUTED for this question (the app's geometric reasoning: a program ran in the sandbox, then again with "
            f"changed numbers): answer = {card['answer']} {card['unit']}".strip()
            + (f". This follow-up only changed: {changed} (the earlier program, run again)" if changed else "")
            + (f". Steps: {steps}" if steps else "")
            + f". Check: {card['check']}. Your FIRST sentence states exactly this answer: {card['answer']} {card['unit']}."
            " Then show the key steps that lead to exactly this number; never give a different number. If it doesn't fit "
            "the question, say so plainly instead of inventing another one.")


def agrees(reply: str, card: dict) -> bool:
    """Does the written answer keep the computed one? (a 4B model wrote "92 cubes" under a worked-out 100)"""
    a = _num(card.get("answer"))
    if a is None:
        return True  # a yes/no or a text answer: nothing to compare
    want = {f"{a:g}", f"{a:.2f}".rstrip("0").rstrip("."), str(round(a)) if float(a).is_integer() else f"{a:g}"}
    bold = [n.replace(",", ".") for b in re.findall(r"\*\*([^*]{1,80})\*\*", reply) for n in re.findall(r"-?\d+(?:[.,]\d+)?", b)]
    if bold:  # the headline numbers it put in bold must include the answer
        return any(n.rstrip("0").rstrip(".") in want or n in want for n in bold)
    return any(n.replace(",", ".") in want for n in re.findall(r"-?\d+(?:[.,]\d+)?", reply))
