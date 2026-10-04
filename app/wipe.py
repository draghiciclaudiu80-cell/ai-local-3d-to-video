"""Deleting for good. A deleted chat, picture or video — and the screenshots, previews, voice recordings and
log lines that went with it — is overwritten before it's removed, so recovery tools find nothing: files get
random bytes (and a random name), the database overwrites deleted rows with zeros (secure_delete). On an SSD,
Windows then tells the drive to erase the freed blocks (TRIM)."""
import ctypes
import json
import os
import re
import secrets
import time
from pathlib import Path

from . import db
from .config import DATA, LOGS, MEDIA

SELFCHECK = LOGS / "selfcheck.jsonl"
CHAT_FILES = re.compile(r"/media/(web/[0-9a-f]{12}\.jpg)")  # a chat's own picture / video previews


def shred(p) -> bool:
    """Overwrites a file with random bytes, renames it and deletes it. If Windows won't let go of it (still open
    somewhere), its content is gone anyway."""
    p = Path(p)
    try:
        size = p.stat().st_size
        with open(p, "r+b", buffering=0) as f:
            done = 0
            while done < size:
                n = min(1 << 20, size - done)
                f.write(os.urandom(n))
                done += n
            os.fsync(f.fileno())
        q = p.with_name(secrets.token_hex(8))
        p.rename(q)
        p = q
    except FileNotFoundError:
        return False
    except OSError:
        pass
    try:
        p.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def shred_tree(d: Path, keep_dir: bool = False) -> None:
    if not d.exists():
        return
    for p in sorted(d.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        if p.is_dir():
            try:
                p.rmdir()
            except OSError:
                pass
        else:
            shred(p)
    if not keep_dir:
        try:
            d.rmdir()
        except OSError:
            pass


def drop_lines(path: Path, gone) -> None:
    """Rewrites a log without the lines `gone(line)` picks; the old file is shredded."""
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    keep = [x for x in lines if not gone(x)]
    if len(keep) == len(lines):
        return
    tmp = path.with_name(path.name + "." + secrets.token_hex(4))
    tmp.write_text("".join(keep), encoding="utf-8")
    shred(path)
    tmp.replace(path)


def _chat_of(line: str) -> str:
    try:
        return json.loads(line).get("chat") or ""
    except ValueError:
        return ""


def forget_chat(cid: str) -> None:
    """Before a chat's rows go: its previews and its lines in the self-check log."""
    for row in db.q("SELECT content, extra FROM messages WHERE chat_id=?", (cid,)):
        for name in CHAT_FILES.findall(f"{row['content']} {row['extra'] or ''}"):
            shred(MEDIA / name)
    drop_lines(SELFCHECK, lambda x: _chat_of(x) == cid)


def forget_job(jid: str) -> None:
    shred(LOGS / f"job-{jid}.log")  # it holds the prompt


def checkpoint() -> None:
    """Deleted rows are already zeros; this also empties the database's write-ahead file."""
    try:
        db.q("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:  # noqa: BLE001 — busy: the next one does it
        pass


def _no_index(p: Path) -> None:
    """Windows Search doesn't copy the app's chats / pictures into its index (new files inherit it)."""
    try:
        k = ctypes.windll.kernel32
        a = k.GetFileAttributesW(str(p))
        if a != -1 and a != 0xFFFFFFFF and not a & 0x2000:
            k.SetFileAttributesW(str(p), a | 0x2000)
    except (AttributeError, OSError):
        pass


def sweep(job_ids: set[str]) -> dict:
    """At start: removes for good whatever a deleted item left behind — computer-use screenshots, previews no
    chat uses, logs of deleted renders, self-check lines of deleted chats — and cleans the database's free space."""
    n = 0
    used = set()
    for row in db.q("SELECT content, extra FROM messages WHERE extra LIKE '%/media/web/%' OR content LIKE '%/media/web/%'"):
        used |= set(CHAT_FILES.findall(f"{row['content']} {row['extra'] or ''}"))
    for f in MEDIA.glob("cu-*.png"):  # screenshots of your screen: only needed while that task runs
        n += shred(f)
    for f in (MEDIA / "web").glob("*"):
        if f.is_file() and f"web/{f.name}" not in used:
            n += shred(f)
    keep = job_ids | {g["id"] for g in db.q("SELECT id FROM gallery")}
    for f in LOGS.glob("job-*.log"):
        if f.stem[4:] not in keep:
            n += shred(f)
    att_used = set()  # files added with the chat's + but never sent (or their chat is gone)
    for row in db.q("SELECT extra FROM messages WHERE extra LIKE '%\"attachments\"%'"):
        att_used |= set(re.findall(r'"id": "([0-9a-f]{12})"', row["extra"] or ""))
    for d in (DATA / "attachments").glob("*"):
        if d.is_dir() and d.name not in att_used and time.time() - d.stat().st_mtime > 6 * 3600:
            n += shred_tree(d) or 1
    old_runs = [d for d in (DATA / "plugin-runs").glob("*") if d.is_dir() and time.time() - d.stat().st_mtime > 6 * 3600]
    for d in [*DATA.glob("sfx-*"), *old_runs]:  # work folders of the sound-effects step / 3D runs (a crash or a restart
        if d.is_dir():  # mid-way: two 3D runs had left 124 MB of parts and their request behind)
            shred_tree(d)
            n += 1
    chats = {c["id"] for c in db.q("SELECT id FROM chats")}
    drop_lines(SELFCHECK, lambda x: _chat_of(x) not in chats)
    free = db.q("PRAGMA freelist_count")[0]
    if list(free.values())[0]:
        db.q("VACUUM")  # free space from before secure delete was on
    checkpoint()
    for top, dirs, files in os.walk(DATA):
        dirs[:] = [d for d in dirs if d != "window"]  # the window's own browser files: many, and not ours
        _no_index(Path(top))
        for f in files:
            _no_index(Path(top) / f)
    return {"shredded": n}
