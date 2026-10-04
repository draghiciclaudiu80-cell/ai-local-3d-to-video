"""Printing a picture or a text on a normal (paper) printer — the system's own printing, no dialog boxes:
Windows: paper_print.ps1 (System.Drawing.Printing: a picture fills the page in proportion, a text flows over pages;
"Microsoft Print to PDF" gives a PDF file instead of asking where to save); Linux: CUPS (lp / lpstat)."""
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from . import wipe
from .config import DATA, MEDIA, NO_WINDOW
from .plat import IS_WIN

SCRIPT = Path(__file__).resolve().parent / "paper_print.ps1"
PDF_PRINTERS = ("microsoft print to pdf",)


def _ps(*args: str, timeout: int = 120) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=timeout, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout).strip().splitlines()[-1][:200] if (r.stderr or r.stdout).strip() else "printing failed")
    return r.stdout.strip()


def printers() -> list[dict]:
    """[{name, default}] — the printers this PC knows."""
    try:
        if IS_WIN:
            out = json.loads(_ps("-Kind", "list", timeout=30) or "[]")
            return out if isinstance(out, list) else [out]
        if not shutil.which("lpstat"):
            return []
        names = re.findall(r"^printer (\S+)", subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=15).stdout, re.M)
        d = re.search(r": (\S+)$", subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=15).stdout.strip())
        return [{"name": n, "default": bool(d and d.group(1) == n)} for n in names]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []


def print_file(kind: str, path: Path, printer: str, copies: int = 1) -> dict:
    """kind image / text. Returns {"printed": printer} — or {"pdf": url} for a PDF printer."""
    copies = max(1, min(99, int(copies or 1)))
    if kind == "image" and path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
        from PIL import Image
        png = DATA / "plugin-runs" / f"pic-{uuid.uuid4().hex[:10]}.png"
        png.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(path) as im:
            im.convert("RGB").save(png)
        try:
            return print_file(kind, png, printer, copies)
        finally:
            wipe.shred(png)
    names = [p["name"] for p in printers()]
    if printer not in names:
        raise ValueError("That printer isn't there any more")
    if IS_WIN:
        pdf = None
        if printer.lower() in PDF_PRINTERS:
            pdf = MEDIA / f"print-{uuid.uuid4().hex[:12]}.pdf"
        _ps("-Kind", kind, "-File", str(path), "-Printer", printer, "-Copies", str(copies), *(["-Pdf", str(pdf)] if pdf else []))
        if pdf:
            if not pdf.exists():
                raise ValueError("the PDF wasn't made")
            return {"pdf": f"/media/{pdf.name}", "printer": printer}
        return {"printed": printer, "copies": copies}
    args = ["lp", "-d", printer, "-n", str(copies)] + (["-o", "fit-to-page"] if kind == "image" else []) + [str(path)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise ValueError((r.stderr or "printing failed").strip()[:200])
    return {"printed": printer, "copies": copies}


def print_text(text: str, printer: str, copies: int = 1) -> dict:
    tmp = DATA / "plugin-runs" / f"text-{uuid.uuid4().hex[:10]}.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(text, encoding="utf-8-sig")
    try:
        return print_file("text", tmp, printer, copies)
    finally:
        wipe.shred(tmp)
