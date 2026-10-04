"""AI Local's downloader (the online installers run it): the programs and models in manifest.json, from their official
addresses, every file checked by SHA-256 (git SHA-1 for small files) before it's used. Resumes a broken download,
skips what's already there and checked. Python 3.10+ with httpx (the app's own environment).

    python tools/get_downloads.py --os win --groups core,print     (what to get)
    python tools/get_downloads.py --list                           (what there is, and the sizes)
    python tools/get_downloads.py --check                          (only check the addresses still answer)
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # the app folder (this file lives in tools/)
HF = "https://huggingface.co"


def say(t: str) -> None:
    print(t, flush=True)


def human(n: int) -> str:
    return f"{n / 1073741824:.1f} GB" if n >= 1073741824 else f"{max(n, 0) / 1048576:.0f} MB"


def git_sha1(p: Path) -> str:
    h = hashlib.sha1(f"blob {p.stat().st_size}\0".encode())
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def good(p: Path, it: dict) -> bool:
    if not p.exists():
        return False
    if it.get("sha256"):
        return sha256(p) == it["sha256"]
    if it.get("sha1git"):
        return git_sha1(p) == it["sha1git"]
    return bool(it.get("size")) and p.stat().st_size == it["size"]


def fetch(url: str, out: Path, it: dict, label: str) -> None:
    """Downloads url to out (resuming a .part), then checks it; 4 tries."""
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    for attempt in range(1, 5):
        try:
            have = part.stat().st_size if part.exists() else 0
            head = {"Range": f"bytes={have}-"} if have else {}
            with httpx.stream("GET", url, headers=head, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
                if r.status_code == 416:  # already complete
                    pass
                else:
                    r.raise_for_status()
                    if have and r.status_code != 206:  # the server won't resume: start over
                        have = 0
                    total = have + int(r.headers.get("content-length") or 0)
                    last, mode = 0.0, "ab" if have else "wb"
                    with open(part, mode) as f:
                        for chunk in r.iter_bytes(1 << 20):
                            f.write(chunk)
                            have += len(chunk)
                            if time.time() - last > 2:
                                last = time.time()
                                pct = f" {have * 100 // total}%" if total else ""
                                print(f"\r    {label}: {human(have)} of {human(total)}{pct}   ", end="", flush=True)
            print(f"\r    {label}: {human(part.stat().st_size)} — checking…" + " " * 20, flush=True)
            if good(part, it):
                part.replace(out)
                return
            say(f"    {label}: the file didn't match its checksum — downloading it again")
            part.unlink(missing_ok=True)
        except (httpx.HTTPError, OSError) as e:
            say(f"\n    {label}: try {attempt} failed ({str(e)[:120]})")
            time.sleep(3 * attempt)
    raise SystemExit(f"Couldn't download {label} from {url} — check the internet connection and run the installer again.")


def extract(arc: Path, dest: Path, kind: str, strip) -> None:
    """Unpacks into dest. strip: how many leading folders to drop; "auto" = the one top folder, if there's only one."""
    tmp = dest.with_name(dest.name + ".unpack")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if kind == "zip":
        with zipfile.ZipFile(arc) as z:
            for m in z.infolist():  # nothing outside the folder (a hostile archive can't write elsewhere)
                if Path(m.filename).is_absolute() or ".." in Path(m.filename).parts:
                    raise SystemExit(f"{arc.name}: a file in it points outside its folder — not unpacked")
            z.extractall(tmp)
    elif kind == "tar":
        with tarfile.open(arc) as t:
            t.extractall(tmp, filter="data")
    elif kind == "7z":  # Windows 10/11's own tar.exe reads 7z
        r = subprocess.run(["tar", "-xf", str(arc), "-C", str(tmp)], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"{arc.name}: couldn't unpack it ({r.stderr.strip()[:200]})")
    tops = [p for p in tmp.iterdir()]
    n = (1 if len(tops) == 1 and tops[0].is_dir() else 0) if strip in (None, "auto") else int(strip)
    dest.mkdir(parents=True, exist_ok=True)
    for p in tmp.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(tmp).parts[n:]
        if not rel:
            continue
        q = dest.joinpath(*rel)
        q.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(q))
    shutil.rmtree(tmp, ignore_errors=True)


def hf_files(it: dict) -> list[dict]:
    """A Hugging Face folder at a pinned revision, file by file, with each file's checksum."""
    url = f"{HF}/api/models/{it['repo']}/tree/{it['revision']}?recursive=true"
    files = httpx.get(url, timeout=60, follow_redirects=True).raise_for_status().json()
    out = []
    for f in files:
        if f.get("type") != "file":
            continue
        p = f["path"]
        if it.get("include") and not any(p.startswith(x) for x in it["include"]):
            continue
        if any(p == x or p.startswith(x) for x in it.get("exclude", [])):
            continue
        rel = "/".join(p.split("/")[int(it.get("strip") or 0):])
        chk = {"sha256": f["lfs"]["oid"]} if f.get("lfs") else {"sha1git": f.get("oid")}
        out.append({"url": f"{HF}/{it['repo']}/resolve/{it['revision']}/{p}", "rel": rel, "size": f.get("size", 0), **chk})
    return out


def run(it: dict) -> None:
    dest = ROOT / it["dest"]
    mark = dest / f".ok-{it['id']}"
    if mark.exists():
        say(f"  ✓ {it['title']} (already here)")
        return
    say(f"  • {it['title']}")
    if it["kind"] == "hf_tree":
        for f in hf_files(it):
            out = dest / f["rel"]
            if not good(out, f):
                fetch(f["url"], out, f, f["rel"])
    elif it["kind"] == "file":
        out = dest / it["url"].split("/")[-1]
        if not good(out, it):
            fetch(it["url"], out, it, out.name)
    else:  # an archive: downloaded next to the app, checked, unpacked, removed
        arc = ROOT / "downloads" / it["url"].split("/")[-1]
        if not good(arc, it):
            fetch(it["url"], arc, it, arc.name)
        say(f"    unpacking {arc.name}…")
        extract(arc, dest, it["kind"], it.get("strip", "auto"))
        arc.unlink(missing_ok=True)
    dest.mkdir(parents=True, exist_ok=True)
    mark.write_text(time.strftime("%Y-%m-%d %H:%M"), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", default="win" if sys.platform == "win32" else "linux")
    ap.add_argument("--groups", default="core")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    items = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))["items"]
    mine = [i for i in items if i["os"] in ("all", a.os)]
    if a.list:
        for g in sorted({i["group"] for i in mine}):
            n = sum(i.get("size") or 0 for i in mine if i["group"] == g)
            say(f"{g:6} {human(n):>8}  " + ", ".join(i["title"] for i in mine if i["group"] == g))
        return
    if a.check:
        bad = 0
        for i in mine:
            url = f"{HF}/api/models/{i['repo']}/tree/{i['revision']}" if i["kind"] == "hf_tree" else i["url"]
            try:
                code = httpx.head(url, follow_redirects=True, timeout=30).status_code
            except httpx.HTTPError as e:
                code = str(e)[:60]
            ok = code in (200, 206, 405)  # some servers refuse HEAD but serve the file
            bad += not ok
            say(f"{'OK ' if ok else 'BAD'} {code}  {i['id']}")
        raise SystemExit(1 if bad else 0)
    want = set(a.groups.split(","))
    todo = [i for i in mine if i["group"] in want]
    say(f"Getting {len(todo)} items ({', '.join(sorted(want))}) — about {human(sum(i.get('size') or 0 for i in todo))}"
        " plus a few small ones. You can stop and run it again: it goes on where it stopped.")
    for i in todo:
        run(i)
    shutil.rmtree(ROOT / "downloads", ignore_errors=True)
    say("All downloads are here and checked.")


if __name__ == "__main__":
    main()
