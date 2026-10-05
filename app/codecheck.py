"""Checks for the code the local AI writes, BEFORE it runs — the way a programmer (or Claude Code) validates code with a
linter and tests, then fixes the exact line:
- Python skills (the Forge): pyflakes — undefined names, typos in names, a variable used before it's set, a bad
  import — on top of the sandbox's own rules (forge_box.check) and the self-test;
- apps (the app maker): the element-id check (the script asks for an id the page doesn't have: getElementById returns
  null and the app breaks — a small model's most common bug), and an HTML check for <script> / <style> / <textarea>
  left open (the rest of the page disappears into them);
- with_lines(): an error that names a line gets that line's code added, so the model sees exactly what to fix."""
import io
import re
from html.parser import HTMLParser

HARMLESS = re.compile(r"imported but unused|redefinition of unused|assigned to but never used|f-string is missing "
                      r"placeholders|unable to detect undefined names|may be undefined, or defined from star")


def python_problems(code: str, name: str = "skill.py") -> list[str]:
    """pyflakes' real problems ("line 7: undefined name 'cpu_pct'"); style-only notes are left out."""
    try:
        from pyflakes.api import check
        from pyflakes.reporter import Reporter
    except ImportError:  # (an older install without pyflakes: the sandbox's own checks still run)
        return []
    out, err = io.StringIO(), io.StringIO()
    check(code, name, Reporter(out, err))
    found = []
    for line in (out.getvalue() + err.getvalue()).splitlines():
        m = re.match(rf"{re.escape(name)}:(\d+):(?:\d+:?)?\s*(.*)", line)
        if m and m.group(2).strip() and not HARMLESS.search(m.group(2)):
            found.append(f"line {m.group(1)}: {m.group(2).strip()}")
    return list(dict.fromkeys(found))[:6]


class _Open(HTMLParser):
    """Raw-text elements left open: everything after them stops being page (scripts / styles / a textarea's text)."""
    RAW = ("script", "style", "textarea", "title")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.open: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.RAW:
            self.open.append((tag, self.getpos()[0]))

    def handle_endtag(self, tag):
        for i in range(len(self.open) - 1, -1, -1):
            if self.open[i][0] == tag:
                del self.open[i]
                break


def app_problems(html: str) -> list[str]:
    """Problems found by reading the file (no browser needed)."""
    found = []
    p = _Open()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 — a parser hiccup is not the app's problem
        pass
    found += [f"line {ln}: <{tag}> is never closed — add </{tag}>" for tag, ln in p.open[:3]]
    js = "\n".join(re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I))
    have = set(re.findall(r"""\bid\s*=\s*["']([^"'\s>]+)["']""", html))  # in the page AND in strings the script writes
    have |= set(re.findall(r"""\.id\s*=\s*["'`]([\w-]+)["'`]""", js))
    have |= set(re.findall(r"""setAttribute\(\s*["']id["']\s*,\s*["'`]([\w-]+)["'`]""", js))
    asked = re.findall(r"""getElementById\(\s*["'`]([\w-]+)["'`]\s*\)""", js)
    asked += re.findall(r"""querySelector(?:All)?\(\s*["'`]#([\w-]+)["'`]\s*\)""", js)
    if re.search(r"""(?:const|let|var)\s+\$\s*=\s*\(?\s*\w+\s*\)?\s*=>\s*document\.getElementById\(""", js) or \
            re.search(r"""function\s+\$\s*\(\s*\w+\s*\)\s*\{\s*return\s+document\.getElementById\(""", js):
        asked += re.findall(r"""(?<![\w$.])\$\(\s*["'`]([\w-]+)["'`]\s*\)""", js)  # the usual $('id') helper
    for missing in [a for a in dict.fromkeys(asked) if a not in have][:4]:
        line = next((n for n, text in enumerate(html.split("\n"), 1) if re.search(rf"""["'`]#?{re.escape(missing)}["'`]""", text)), 0)
        found.append(f"line {line}: the script asks for the element id “{missing}” but no element has id=\"{missing}\" "
                     "(it gets null) — add that element or use the right id")
    return found


def with_lines(problems: list[str], code: str) -> list[str]:
    """“… (line 67)” / “line 67: …” -> the same, plus that line's code: `redoStack = [];`."""
    lines, out = code.split("\n"), []
    for p in problems:
        m = re.search(r"\bline (\d+)\b", p)
        n = int(m.group(1)) if m else 0
        out.append(f"{p}\n    → line {n}: {lines[n - 1].strip()[:180]}" if 0 < n <= len(lines) and lines[n - 1].strip() else p)
    return out
