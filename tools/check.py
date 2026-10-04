"""Quick safety check — run after EVERY change, before restarting the app:
    .venv\\Scripts\\python tools\\check.py
1) no name is used that isn't defined anywhere (a partial edit that deleted a function only fails later, mid-chat)
2) the whole app imports
3) the word rules still understand real messages from the chats (no model needed, < 1 s)."""
import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
bad = 0


def undefined(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf8"))
    defined = set(dir(builtins)) | {"__file__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            defined |= {(a.asname or a.name).split(".")[0] for a in node.names}
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            defined.add(node.id)
        elif isinstance(node, ast.arg):
            defined.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return used - defined


for f in sorted((ROOT / "app").glob("*.py")):
    missing = undefined(f)
    if missing:
        bad += 1
        print(f"MISSING in {f.name}: {sorted(missing)}")

try:
    import app.server  # noqa: F401
    from app.agent import JOIN, LINKS_ASK, chosen, how_many, wants, wants_make
except Exception as e:  # noqa: BLE001
    print("IMPORT FAILED:", e)
    sys.exit(1)

CID = "no-such-chat"
cases = [  # (function, message, expected) — real messages from the chats
    (wants, "saerg the weg for pictures with dogs", "pictures"),
    (wants, "searg the web  for pictusr of a rabit", "pictures"),
    (wants, "cauta pe net poze cu pisici", "pictures"),
    (wants, "seargh in the web for videos of chickens", "videos"),
    (wants, "search the web for the best camera for photos", "web"),
    (wants, "use my computer and search for pictures of pitbulls, google it", None),
    (wants, "hi", None),
    (chosen, "click on the third rabbit from the 12 pictures", 3),
    (chosen, "I said in this chat you have found 12 pictures, the first request that I made. Now select the third one", 3),
    (chosen, "show me the first steps to learn guitar", None),
    (chosen, "open notepad and type the first line", None),
    (chosen, "deschide a treia poza", 3),
    (chosen, "play the second video", 2),
    (lambda t: wants_make(t, CID), "make aphoto of a girl", "image"),
    (lambda t: wants_make(t, CID), "fa imagine", "image"),
    (lambda t: wants_make(t, CID), "generate one more imege of a girl sitin in a park on a bech", "image"),
    (lambda t: wants_make(t, CID), "one more picture of a dog", "image"),
    (lambda t: wants_make(t, CID), "make a video of a dog plaing", "video"),
    (lambda t: wants_make(t, CID), "make a movie about a fox", None),
    (lambda t: wants_make(t, CID), "can you make the picture bigger", None),
    (lambda t: wants_make(t, CID), "imagine a world without cars", None),
    (lambda t: bool(JOIN.search(t)), "make 2 videos so u can merg them togetherafter", True),
    (lambda t: bool(JOIN.search(t)), "uneste clipurile", True),
    (lambda t: bool(JOIN.search(t)), "downlod nu merge", False),
    (how_many, "make 2 videos of a dog runig in the park", 2),
    (how_many, "make a 5 second video of a cat", 1),  # a length, not a count (it made 4 clips)
    (how_many, "make 2 videos of 2 seconds each", 2),
    (lambda t: bool(LINKS_ASK.search(t)), "show me links", True),
    (lambda t: bool(LINKS_ASK.search(t)), "links please", True),
]
from app.agent import ADD_SOUND, NARRATION_WANT, SFX_WANT, refused, wanted_seconds  # noqa: E402
cases += [
    (wanted_seconds, "make a new singel video that is 10 second long no les then that", 10.0),
    (wanted_seconds, "fa un video de 12 secunde", 12.0),
    (wanted_seconds, "make a video of a dog", None),
    (lambda t: bool(ADD_SOUND.search(t)), "add specific noises", True),
    (lambda t: bool(NARRATION_WANT.search(t)), "add specific noises", False),  # noises = effects, NOT a narrator
    (lambda t: bool(SFX_WANT.search(t)), "add sound", True),
    (lambda t: bool(NARRATION_WANT.search(t)), "add a narrator saying hello", True),
    (refused, "No video generation can be performed for this request as it violates safety policies", True),
    (refused, "Two women share a tender kiss on a sunlit bed", False),
]
for fn, text, want in cases:
    got = fn(text)
    if got != want:
        bad += 1
        print(f"WRONG: {text!r} -> {got!r} (expected {want!r})")
# a helper inside a function that ASSIGNS a name the outer function also has, and ALSO adds to it (x.append…),
# hides the outer list: "clips = …" in run_sound made every answer crash ("cannot access local variable 'clips'")
_MUT = {"append", "extend", "update", "add", "insert", "pop", "clear", "remove", "setdefault"}


def _own(fn):  # names assigned in fn's own body (not in functions inside it), minus nonlocal / global
    out, skip = set(), set()
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(n, (ast.Nonlocal, ast.Global)):
            skip |= set(n.names)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        stack.extend(ast.iter_child_nodes(n))
    return out - skip


for f in sorted((ROOT / "app").glob("*.py")):
    for outer in ast.walk(ast.parse(f.read_text(encoding="utf8"))):
        if not isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        outer_names = _own(outer)
        for inner in ast.walk(outer):
            if inner is outer or not isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            mutated = {n.func.value.id for n in ast.walk(inner) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute) and n.func.attr in _MUT and isinstance(n.func.value, ast.Name)}
            hidden = _own(inner) & outer_names & mutated
            if hidden:
                bad += 1
                print(f"HIDDEN OUTER NAME in {f.name}: {inner.name}() assigns {sorted(hidden)} that {outer.name}() uses")
# garbled text: a file read in the wrong encoding and saved again ("…" -> "â€¦") broke Romanian word lists once
import re as _re
for f in [*ROOT.glob("app/*.py"), *ROOT.glob("app/static/*.js"), *ROOT.glob("app/static/*.html"), *ROOT.glob("app/static/*.css"), *ROOT.glob("plugins/*/*.py"), *ROOT.glob("plugins/*/*.json")]:
    t = f.read_text(encoding="utf-8", errors="replace")
    junk = _re.findall("[ÃÂâ][-¿€‚ƒ„…†‡ˆ‰Š‹ŒŽ‘’“”•–—˜™š›œžŸ]", t)
    if junk or "" in t or t.startswith("﻿"):
        print(f"GARBLED TEXT in {f.relative_to(ROOT)}: {len(junk)} spots{' + control chars' if chr(8) in t else ''}")
        bad += 1
# the page's JavaScript must parse: ONE broken line in main.js (a line break inside a string) left the whole app blank
import shutil as _sh
import subprocess as _sp
import tempfile as _tf
_node = _sh.which("node") or next((str(p) for p in [Path.home() / "AppData/Local/hermes/node/node.exe",
                                                      Path("C:/Program Files/nodejs/node.exe")] if p.exists()), None)
if _node:
    with _tf.TemporaryDirectory() as _d:
        for f in ROOT.glob("app/static/*.js"):
            m = Path(_d) / (f.stem + ".mjs")  # checked as a module, the way the page loads it
            m.write_bytes(f.read_bytes())
            r = _sp.run([_node, "--check", str(m)], capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode:
                bad += 1
                print(f"JAVASCRIPT ERROR in app/static/{f.name}: " + " | ".join(x for x in r.stderr.splitlines() if x.strip())[:300])
else:
    print("(no node found: JavaScript not checked)")
print("ALL GOOD" if not bad else f"{bad} PROBLEM(S)")
sys.exit(1 if bad else 0)
