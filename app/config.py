"""Paths, ports and user settings. Everything lives inside the app folder, so the folder is portable."""
import json
import subprocess
from pathlib import Path

VERSION = "0.2"
ROOT = Path(__file__).resolve().parent.parent
ENGINES = ROOT / "engines"
MODELS = ROOT / "models"
DATA = ROOT / "data"
MEDIA = DATA / "media"
SOUNDS = DATA / "sounds"
LOGS = DATA / "logs"
for d in (MODELS, DATA, MEDIA, SOUNDS, LOGS):
    d.mkdir(parents=True, exist_ok=True)

APP_PORT = 8770          # the app itself (0.1 used 8765, so both can run)
LLM_PORT = 8771          # bundled llama-server
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Folders scanned for model files. The app only READS files outside its own models folder,
# so models you already have (e.g. from LM Studio) are reused instead of downloaded again.
DEFAULT_MODEL_DIRS = [
    str(MODELS),
    str(Path.home() / ".lmstudio" / "models"),
    str(Path.home() / "projects" / "local-ai-app" / "models"),
]

DEFAULTS = {
    "theme": "system",                      # system | light | dark
    "system_prompt": "You are a helpful assistant running fully offline on the user's own PC. "
                     "Be direct and concise.",
    "ctx": 8192,
    "temperature": 0.7,
    "active": {"text": "", "vision": "", "image": "", "video": "", "voice": "en_US-lessac-medium",
               "transcription": "base"},
    "model_dirs": DEFAULT_MODEL_DIRS,
    "allow_web": False,
    "memory_auto": True,                    # learn lasting facts about the user from chats (Memory page)
    "laya": True,
    "laya_assist": False,
    "laya_only": False,
    "small_model": None,                    # the small model's file (Models page); None = models/small/Qwen3-1.7B
    "laya_model": None,                     # the Laya checkpoint folder (models/laya-real/<name>); None = typed-decisions
    "plugin_dirs": [],                      # plugin folders you added (Memory › Documents & plugins)
    "skill_dirs": [],                       # skill folders you added (Memory › Skills)
    "skills_off": [],                       # skills switched off (the Skills menu / Memory page)
    "app_root": "",                         # where the app folder was last time (moved -> paths are rewritten)
    "machine": "",                          # the PC's name last time (another PC -> the setup check opens once)
    "setup_pending": False,                 # show Settings › This PC once (moved / new PC)
    "python_code": False,                   # the chat's "Python code" button: the AI writes Blender Python (off = recipes)
    "keep_awake": True,                     # no idle sleep while the app is working (answers, renders, 3D, downloads)
    "auto_cut": True,                       # a 3D model too big for the printer's plate is also cut into pieces that fit
    "printer_bed": [220, 220, 250],         # the 3D printer's build volume (mm): bigger parts get a warning
    "printer": "ender3_v3_se",              # the user's 3D printer: app/printers/<id>.json (slicing settings, plate, limits)
    "printer_link": {"kind": "usb", "port": "", "url": "", "key": ""},  # how a print reaches it (USB / OctoPrint / Moonraker)
    "print_fit": None,                      # mm of room parts need to fit together on it (measured with the fit test)
    "plugins_on": {},                       # plugin id -> on/off                     # chat with Laya instead of the main model (sidebar switch)                   # experimental: Laya helps the main model on every message (sidebar switch)                           # Laya: tiny decision model on the processor while the GPU renders                     # web tools ask every time unless this is on
    "tor": True,                            # web searches go through the built-in Tor (see tor.py)
    "web_proxy": "",                        # optional, e.g. socks5://127.0.0.1:9150 (Tor Browser)
    "thinking": True,
    "stt_language": "auto",                 # speech-to-text language: auto or a code like "en", "ro"
}
SETTINGS_FILE = DATA / "settings.json"


def load_settings() -> dict:
    s = json.loads(json.dumps(DEFAULTS))
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if k == "active" and isinstance(v, dict):
                s["active"].update(v)
            elif k in s:
                s[k] = v
    except (OSError, ValueError):
        pass
    return s


def save_settings(changes: dict) -> dict:
    s = load_settings()
    for k, v in changes.items():
        if k == "active" and isinstance(v, dict):
            s["active"].update(v)
        elif k in DEFAULTS:
            s[k] = v
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
    return s


def relocate() -> dict:
    """The app folder moved (another drive or another PC): every saved path inside the OLD folder (active models,
    model / plugin / skill folders, finished jobs) is rewritten to the new place; a different PC opens the setup
    check once (Settings › This PC). Runs at every start; does nothing when nothing changed."""
    import os
    import platform
    s, new, info = load_settings(), str(ROOT), {}
    old = s.get("app_root") or ""
    if old and os.path.normcase(old.rstrip("\\/")) != os.path.normcase(new.rstrip("\\/")):
        def fix(v):
            if isinstance(v, str) and os.path.normcase(v).startswith(os.path.normcase(old.rstrip("\\/")) + os.sep):
                return new + v[len(old.rstrip("\\/")):]
            if isinstance(v, list):
                return [fix(x) for x in v]
            if isinstance(v, dict):
                return {k: fix(x) for k, x in v.items()}
            return v
        save_settings({k: fix(v) for k, v in s.items() if fix(v) != v})
        for f in (DATA / "jobs.json", DATA / "movies.json"):  # finished renders remember their files' full paths
            try:
                raw = f.read_text(encoding="utf-8")
                esc_old, esc_new = json.dumps(old.rstrip("\\/"))[1:-1], json.dumps(new)[1:-1]
                if esc_old in raw:
                    f.write_text(raw.replace(esc_old, esc_new), encoding="utf-8")
            except OSError:
                pass
        info["moved_from"] = old
    machine = platform.node()
    if s.get("machine") and s.get("machine") != machine:
        info["new_pc"] = s.get("machine")
    save_settings({"app_root": new, "machine": machine, **({"setup_pending": True} if info else {})})
    return info


def model_dirs() -> list[Path]:
    """The app's own models folder always comes first — also after the app folder is copied or moved,
    when the saved list still points at the old location."""
    out = [MODELS]
    for d in load_settings()["model_dirs"]:
        p = Path(d)
        if p.exists() and p.resolve() != MODELS.resolve() and p not in out:
            out.append(p)
    return out
