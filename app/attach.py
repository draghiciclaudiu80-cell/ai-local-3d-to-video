"""Files the user attaches in the chat (the + menu: files, photos, videos, a whole folder), like Claude's attachments.

Each file is stored under data/attachments/<id>/ and turned into something the model can use:
- text, code, PDF, Word, Excel, PowerPoint -> its text;  3D files -> size and triangles;  zip -> the list of files;
- video -> about 8-12 frames across the whole clip (the vision model watches them) + what is said (Whisper);
- audio -> what is said;  images -> a picture the vision model sees.
Nothing is ever opened with another program or run. Programs are refused. The text reaches the model framed as
UNTRUSTED DATA (security.untrusted): a file can't give the AI orders."""
import base64
import io
import json
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from . import security
from .config import DATA

ATT = DATA / "attachments"
IMG = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
VID = {"mp4", "mov", "webm", "mkv", "avi", "m4v", "3gp", "wmv"}
AUD = {"mp3", "wav", "m4a", "ogg", "flac", "aac", "opus", "wma"}
MODEL3D = {"stl", "obj", "3mf", "step", "stp", "ply", "gltf", "glb", "gcode"}
DOC = {"pdf", "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub"}
CODE = {"py", "pyw", "js", "mjs", "ts", "tsx", "jsx", "java", "kt", "c", "h", "cpp", "hpp", "cc", "cs", "go", "rs", "rb",
        "php", "swift", "lua", "sh", "bash", "ps1", "psm1", "bat", "cmd", "vbs", "sql", "css", "scss", "less", "ini", "cfg",
        "conf", "toml", "env", "properties", "gradle", "cmake", "mk", "makefile", "dockerfile", "ino", "scad", "glsl",
        "hlsl", "shader", "gd", "tscn", "tres", "vue", "svelte", "r", "m", "pl", "dart", "zig", "nim", "srt", "vtt", "tex",
        "rst", "adoc", "ipynb", "reg", "inf"}
TEXT = security.TEXT_EXT | CODE | {"rtf", "tsv", "jsonl", "geojson"}
BINARY_PROGRAM = {"exe", "msi", "dll", "sys", "com", "scr", "ocx", "drv", "cpl", "apk", "dmg", "pkg", "deb", "rpm", "jar",
                  "pyc", "iso", "img", "vhd", "vhdx", "msix", "appx"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".idea", ".vs", ".vscode", "bin", "obj",
             ".gradle", "target", ".next", ".cache"}
MAX_TEXT = 120_000          # characters kept per file


def kind_of(name: str) -> str:
    n = name.lower()
    ext = n.rsplit(".", 1)[-1] if "." in n else n
    return ("image" if ext in IMG else "video" if ext in VID else "audio" if ext in AUD else "3d" if ext in MODEL3D
            else "doc" if ext in DOC else "zip" if ext in {"zip", "7z", "rar", "tar", "gz"} else "program"
            if ext in BINARY_PROGRAM else "text" if ext in TEXT or n in {"makefile", "dockerfile", "readme", "license"} else "other")


def skip_path(rel: str) -> bool:
    """Folder uploads: build output, git history, packages - never useful to the model."""
    return any(part in SKIP_DIRS for part in re.split(r"[\\/]", rel)[:-1])


def _jpeg(img, side: int = 768) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((side, side))
    b = io.BytesIO()
    img.save(b, "JPEG", quality=82)
    return b.getvalue()


def _office_text(p: Path) -> str:
    """xlsx / pptx / odt: the words inside their XML (good enough to talk about them)."""
    out = []
    with zipfile.ZipFile(p) as z:
        names = [n for n in z.namelist() if re.search(r"(sharedStrings|slides/slide\d+|sheet\d+|content)\.xml$", n)]
        for n in sorted(names)[:80]:
            xml = z.read(n).decode("utf-8", "ignore")
            words = re.sub(r"<[^>]+>", " ", re.sub(r"</(a:p|w:p|text:p|row)>", "\n", xml))
            out.append(f"--- {n}\n" + re.sub(r"[ \t]+", " ", words).strip())
    return "\n".join(out)


def _read_text(p: Path, ext: str) -> str:
    if ext in {"pdf", "docx"}:
        return security.read_text(p)
    if ext in {"xlsx", "pptx", "odt", "ods", "odp", "epub"}:
        return _office_text(p)
    if ext == "ipynb":
        nb = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return "\n\n".join(f"# [{c.get('cell_type')}]\n" + "".join(c.get("source") or []) for c in nb.get("cells", []))
    raw = p.read_bytes()[:MAX_TEXT * 2]
    return raw.decode("utf-8", errors="replace")


def _video(p: Path, d: Path) -> dict:
    """Frames spread over the whole clip (the vision model watches them) + the length."""
    import av
    frames, dur = [], 0.0
    with av.open(str(p)) as c:
        vs = next((s for s in c.streams if s.type == "video"), None)
        if vs is None:
            return {"note": "no picture track", "frames": []}
        dur = float(c.duration / 1_000_000) if c.duration else float((vs.frames or 0) / float(vs.average_rate or 25))
        n = 8 if dur <= 60 else 12
        for i in range(n):
            t = dur * (i + 0.5) / n
            try:
                c.seek(int(t / vs.time_base), stream=vs)  # lands on the keyframe BEFORE t -> decode on up to t
                fr = None
                for f in c.decode(vs):
                    fr = f
                    if f.time is None or f.time >= t - 0.05:
                        break
                if fr is None:
                    continue
            except Exception:  # noqa: BLE001 — a frame that won't decode (PyAV's error names change between versions)
                continue
            if frames and fr.time is not None and abs(fr.time - frames[-1]["t"]) < 0.05:
                continue  # the same frame again (a very short clip)
            name = f"frame{i:02d}.jpg"
            (d / name).write_bytes(_jpeg(fr.to_image(), 512))
            frames.append({"file": name, "t": round(fr.time if fr.time is not None else t, 1)})
    return {"duration": round(dur, 1), "frames": frames}


def _transcript(p: Path) -> str:
    try:
        from .voice import voice
        return voice.transcribe(str(p))[:8000]
    except Exception as e:  # noqa: BLE001 — no Whisper model, no sound track: the frames still work
        print("attachment transcript:", repr(e)[:200])
        return ""


def process(p: Path, kind: str) -> dict:
    ext = p.suffix.lower().lstrip(".")
    try:
        if kind in ("text", "doc"):
            text = _read_text(p, ext)[:MAX_TEXT]
            pages = f", {text.count(chr(12)) + 1} pages" if ext == "pdf" else ""
            return {"text": text, "note": f"{len(text):,} characters{pages}"}
        if kind == "image":
            from PIL import Image
            with Image.open(p) as im:
                w, h = im.size
                (p.parent / "view.jpg").write_bytes(_jpeg(im))
            return {"note": f"{w} x {h} picture", "frames": [{"file": "view.jpg", "t": None}]}
        if kind == "video":
            v = _video(p, p.parent)
            said = _transcript(p)
            return {"note": f"{int(v.get('duration', 0)) // 60}:{int(v.get('duration', 0)) % 60:02d} video, "
                            f"{len(v['frames'])} frames" + (", with speech" if said.strip() else ""),
                    "frames": v["frames"], "transcript": said, "duration": v.get("duration")}
        if kind == "audio":
            said = _transcript(p)
            return {"note": "audio" + (", with speech" if said.strip() else ", no speech found"), "transcript": said}
        if kind == "3d" and ext == "stl":
            from .plugins import read_stl
            tri = read_stl(p)
            if len(tri):
                pts = tri.reshape(-1, 3)
                size = pts.max(0) - pts.min(0)
                return {"note": f"STL, {len(tri):,} triangles, {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm",
                        "text": f"STL model: {len(tri)} triangles, size {size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm"}
        if kind == "3d" and ext in {"obj", "gcode", "gltf"}:
            text = p.read_text(encoding="utf-8", errors="replace")[:MAX_TEXT]
            return {"text": text, "note": f"{ext.upper()} file, {len(text):,} characters"}
        if kind == "zip" and ext == "zip":
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
            bad = [n for n in names if kind_of(n) == "program"]
            return {"text": "Files inside the zip (not unpacked):\n" + "\n".join(names[:400]),
                    "note": f"zip, {len(names)} files" + (f", {len(bad)} programs inside (not opened)" if bad else "")}
        if kind == "program":
            return {"note": "a program — not opened or run (the app never runs files)"}
    except Exception as e:  # noqa: BLE001 — a broken file: say so, don't crash the chat
        return {"note": f"could not read it: {str(e)[:160]}"}
    return {"note": f"{ext or 'file'} — kept, but its contents can't be read here"}


def save(name: str, data: bytes, rel: str = "") -> dict:
    aid = uuid.uuid4().hex[:12]
    d = ATT / aid
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^\w .()\-]", "_", Path(name).name)[:120].strip() or "file"
    (d / safe).write_bytes(data)
    info = {"id": aid, "name": safe, "path": (rel or safe).replace("\\", "/")[:300], "kind": kind_of(safe), "size": len(data)}
    info.update(process(d / safe, info["kind"]))
    (d / "info.json").write_text(json.dumps(info), encoding="utf-8")
    return public(info)


def load(aid: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{12}", aid or ""):
        return None
    f = ATT / aid / "info.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def public(info: dict) -> dict:
    return {k: info.get(k) for k in ("id", "name", "path", "kind", "size", "note")}


def remove(aids: list[str]) -> None:
    from . import wipe
    for aid in aids:
        if re.fullmatch(r"[0-9a-f]{12}", aid or "") and (ATT / aid).exists():
            wipe.shred_tree(ATT / aid)


def _spread(frames: list, n: int) -> list:
    """n frames spread over the whole clip (not just its start)."""
    if len(frames) <= n:
        return frames
    return [frames[round(k * (len(frames) - 1) / max(1, n - 1))] for k in range(n)]


def context(aids: list[str], vision: bool, chat_id: str = "", budget: int = 14000,
            max_frames: int = 12) -> tuple[str, list[str]]:
    """-> (text for the model, framed as untrusted data; pictures for a model that can see).
    A folder = several ids: a tree first, then the readable files, smallest first, within the budget
    (characters of file text) — max_frames = the video frames that fit the model's memory."""
    infos = [i for i in (load(a) for a in aids) if i]
    if not infos:
        return "", []
    images: list[str] = []
    lines = [f"The user attached {len(infos)} file(s):"]
    tree = [f"- {i['path']} ({i['kind']}, {i['size']:,} bytes) — {i.get('note', '')}" for i in infos]
    shown, used = [], 0
    for t in tree:  # a big folder's list may use at most half of the room
        if used + len(t) > budget // 2 and shown:
            break
        shown.append(t)
        used += len(t) + 1
    lines += shown + ([f"- … and {len(tree) - len(shown)} more files"] if len(tree) > len(shown) else [])
    left = budget - used
    texts_left = len([x for x in infos if x.get("text")])
    for i in sorted(infos, key=lambda x: (x["kind"] not in ("text", "doc"), len(x.get("text") or ""))):
        body = ""
        if i.get("text"):
            if left < 300:
                continue  # no room left: the file stays in the list above
            share = max(300, left // max(1, texts_left))  # small files first, so big ones get what the small left over
            texts_left -= 1
            t = i["text"]
            body = t[:share] + (f"\n… (cut: {len(t) - share:,} more characters)" if len(t) > share else "")
        if i.get("transcript"):
            body += f"\nWhat is said in it (speech to text): {i['transcript'][:3000]}"
        if i["kind"] in ("image", "video") and i.get("frames"):
            if vision:
                pics = []
                for fr in _spread(i["frames"], max(1, max_frames)) if i["kind"] == "video" else i["frames"][:1]:
                    f = ATT / i["id"] / fr["file"]
                    if f.exists() and len(images) < max(1, max_frames):  # all pictures together fit the memory
                        images.append("data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode())
                        pics.append(fr)
                if i["kind"] == "image" and not pics:
                    body += "\n(Not shown: no room for more pictures in this message.)"
                if i["kind"] == "video" and pics:
                    body += ("\nThe pictures attached to this message are frames from this video, in order, at: "
                             + ", ".join(f"{fr['t']} s" for fr in pics) + ". Describe what happens across them.")
            elif i["kind"] == "video":
                body += "\n(This chat model can't see pictures: only the speech is available. Pick a model that sees images in Models › Text.)"
        if body:
            lines.append(f"\n=== {i['path']} ===\n{body}")
            left -= len(body)
    framed, _ = security.untrusted("files the user attached", "\n".join(lines), chat_id)
    return framed, images
