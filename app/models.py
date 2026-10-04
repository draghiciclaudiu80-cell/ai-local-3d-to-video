"""Everything about model files: the curated catalog per type, what's on this PC, Hugging Face search,
downloads (resumable) and which model is active for each type."""
import json
import re
import struct
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

import httpx

from .config import DATA, MODELS, load_settings, model_dirs, save_settings
from .hardware import free_disk_gb, rate

HF = "https://huggingface.co"
MODALITIES = ["text", "vision", "image", "video", "voice", "transcription"]

# ---------------------------------------------------------------- curated catalog
# id, modality, name, note, size_gb, needs_gpu, tags, files [(repo, path in repo, local name or None)]
FLUX_PARTS = [("city96/t5-v1_1-xxl-encoder-gguf", "t5-v1_1-xxl-encoder-Q4_K_S.gguf", None),
              ("comfyanonymous/flux_text_encoders", "clip_l.safetensors", None),
              ("Comfy-Org/Lumina_Image_2.0_Repackaged", "split_files/vae/ae.safetensors", "flux_ae.safetensors")]
WAN_PARTS = [("city96/umt5-xxl-encoder-gguf", "umt5-xxl-encoder-Q4_K_M.gguf", None),
             ("Comfy-Org/Wan_2.1_ComfyUI_repackaged", "split_files/vae/wan_2.1_vae.safetensors", None)]
CATALOG = [
    ("qwen35-2b", "text", "Qwen 3.5 2B", "Small and quick. Can also see images.", 1.95, False, ["vision"],
     [("unsloth/Qwen3.5-2B-GGUF", "Qwen3.5-2B-Q4_K_M.gguf", None), ("unsloth/Qwen3.5-2B-GGUF", "mmproj-F16.gguf", None)]),
    ("qwen35-4b", "text", "Qwen 3.5 4B", "Best all-rounder for this size: chat, tools, and it can see images.",
     3.41, False, ["recommended", "vision"],
     [("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf", None), ("unsloth/Qwen3.5-4B-GGUF", "mmproj-F16.gguf", None)]),
    ("nemotron-4b", "text", "Nemotron 3 Nano 4B", "Fast, reliable with tools. Text only.", 2.84, False, [],
     [("lmstudio-community/NVIDIA-Nemotron-3-Nano-4B-GGUF", "NVIDIA-Nemotron-3-Nano-4B-Q4_K_M.gguf", None)]),
    ("qwen35-9b", "text", "Qwen 3.5 9B", "Smarter, slower. Can see images.", 6.6, False, ["vision"],
     [("unsloth/Qwen3.5-9B-GGUF", "Qwen3.5-9B-Q4_K_M.gguf", None), ("unsloth/Qwen3.5-9B-GGUF", "mmproj-F16.gguf", None)]),
    ("qwen3vl-2b", "vision", "Qwen3-VL 2B", "Light screen-reading model for computer use.", 1.93, False, ["vision"],
     [("unsloth/Qwen3-VL-2B-Instruct-GGUF", "Qwen3-VL-2B-Instruct-Q4_K_M.gguf", None),
      ("unsloth/Qwen3-VL-2B-Instruct-GGUF", "mmproj-F16.gguf", None)]),
    ("qwen3vl-4b", "vision", "Qwen3-VL 4B", "More accurate clicks. Recommended for computer use.", 3.34, False,
     ["recommended", "vision"],
     [("unsloth/Qwen3-VL-4B-Instruct-GGUF", "Qwen3-VL-4B-Instruct-Q4_K_M.gguf", None),
      ("unsloth/Qwen3-VL-4B-Instruct-GGUF", "mmproj-F16.gguf", None)]),
    ("sdxl-lightning-q4", "image", "SDXL Lightning 4-step", "Fast, one file. Good first image model.", 2.58, True,
     ["recommended", "fast"], [("mzwing/SDXL-Lightning-GGUF", "sdxl_lightning_4step.q4_0.gguf", None)]),
    ("sdxl-lightning-q8", "image", "SDXL Lightning 4-step (high quality)", "Same model, better detail.", 4.1, True,
     ["fast"], [("mzwing/SDXL-Lightning-GGUF", "sdxl_lightning_4step.q8_0.gguf", None)]),
    ("sdxl-turbo", "image", "SDXL Turbo", "Quick drafts in 1-4 steps.", 4.1, True, ["fast"],
     [("OlegSkutte/sdxl-turbo-GGUF", "sd_xl_turbo_1.0.q8_0.gguf", None)]),
    ("flux-schnell-q3", "image", "FLUX.1 schnell", "Best image quality here, slower (~2 min).", 8.5, True, [],
     [("city96/FLUX.1-schnell-gguf", "flux1-schnell-Q3_K_S.gguf", None), *FLUX_PARTS]),
    ("wan13b-q8", "video", "Wan 2.1 1.3B", "Short video clips (~2 min per second of video).", 5.45, True,
     ["recommended"], [("samuelchristlie/Wan2.1-T2V-1.3B-GGUF", "Wan2.1-T2V-1.3B-Q8_0.gguf", None), *WAN_PARTS]),
    ("wan13b-q4", "video", "Wan 2.1 1.3B (small)", "Smaller file, slightly lower quality.", 4.89, True, [],
     [("Sphelele26/cabangile-wan2.1-t2v-1.3b", "Wan2.1-T2V-1.3B-Q4_K_M.gguf", None), *WAN_PARTS]),
]
# Natural voices: Kokoro-82M (Apache-2.0, ONNX, CPU, faster than real time). English only — Romanian text is read
# by the Romanian Piper voice. One model file + one voices file serve all of them.
KOKORO = {
    "kokoro-af_heart": "English (US) · female, natural — Kokoro (best)",
    "kokoro-af_bella": "English (US) · female, natural — Kokoro",
    "kokoro-am_michael": "English (US) · male, natural — Kokoro",
    "kokoro-am_fenrir": "English (US) · male, deep — Kokoro",
    "kokoro-bf_emma": "English (UK) · female, natural — Kokoro",
    "kokoro-bm_george": "English (UK) · male, natural — Kokoro",
}
KOKORO_REPO = "fastrtc/kokoro-onnx"


def kokoro_files() -> tuple[Path, Path] | None:
    """(model, voices) when Kokoro is on this PC."""
    for d in (MODELS / "kokoro", repo_folder(KOKORO_REPO)):
        if (d / "kokoro-v1.0.onnx").exists() and (d / "voices-v1.0.bin").exists():
            return d / "kokoro-v1.0.onnx", d / "voices-v1.0.bin"
    m = find_file("kokoro-v1.0.onnx")
    return (m, m.parent / "voices-v1.0.bin") if m and (m.parent / "voices-v1.0.bin").exists() else None


VOICES = {
    **KOKORO,
    "en_US-lessac-medium": "English (US) · female, neutral",
    "en_US-amy-medium": "English (US) · female, warm",
    "en_US-ryan-medium": "English (US) · male",
    "en_GB-alan-medium": "English (UK) · male",
    "en_GB-alba-medium": "English (UK) · female",
    "ro_RO-mihai-medium": "Română · male",
    "de_DE-thorsten-medium": "Deutsch · male",
    "fr_FR-siwis-medium": "Français · female",
    "es_ES-davefx-medium": "Español · male",
    "it_IT-paola-medium": "Italiano · female",
}
# Speech-to-text (faster-whisper / CTranslate2). key -> (name, note, size GB, Hugging Face repo)
WHISPER = {
    "tiny": ("Whisper Tiny", "Fastest, least accurate", 0.08, "Systran/faster-whisper-tiny"),
    "base": ("Whisper Base", "Fast, OK accuracy", 0.15, "Systran/faster-whisper-base"),
    "small": ("Whisper Small", "Good accuracy — recommended", 0.49, "Systran/faster-whisper-small"),
    "medium": ("Whisper Medium", "Very accurate, slower", 1.53, "Systran/faster-whisper-medium"),
    "large-v3-turbo": ("Whisper Large v3 Turbo", "Most accurate — best for accents, slowest", 1.62,
                       "deepdml/faster-whisper-large-v3-turbo-ct2"),
}
STT_LANGUAGES = {"auto": "Detect: English or Română", "en": "English", "ro": "Română", "de": "Deutsch", "fr": "Français",
                 "es": "Español", "it": "Italiano", "pt": "Português", "nl": "Nederlands", "pl": "Polski",
                 "hu": "Magyar", "ru": "Русский", "uk": "Українська", "tr": "Türkçe", "el": "Ελληνικά",
                 "ar": "العربية", "hi": "हिन्दी", "zh": "中文", "ja": "日本語", "ko": "한국어"}


# ---------------------------------------------------------------- what's on this PC
@lru_cache(maxsize=512)
def gguf_arch(path: str, mtime: float) -> str | None:
    """Reads general.architecture from a GGUF header without loading the model."""
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return None
            f.read(12)
            (n_kv,) = struct.unpack("<Q", f.read(8))
            for _ in range(min(n_kv, 64)):
                (klen,) = struct.unpack("<Q", f.read(8))
                key = f.read(klen).decode(errors="ignore")
                (vtype,) = struct.unpack("<I", f.read(4))
                if vtype != 8:
                    return None
                (vlen,) = struct.unpack("<Q", f.read(8))
                val = f.read(vlen).decode(errors="ignore")
                if key == "general.architecture":
                    return val
    except (OSError, struct.error):
        return None
    return None


GGUF_SIZES = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
GGUF_FMT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
CAPS_FILE = DATA / "model_caps.json"
VIDEO_FAMILIES = ("qwen2vl", "qwen2.5vl", "qwen25vl", "qwen3vl", "qwen3.5", "qwen35", "internvl", "minicpm-v", "minicpmv",
                  "llava-onevision", "llava-video", "videollama", "gemma3", "gemma-3", "glm-4v", "glm4v", "keye", "mimo-vl")


def gguf_meta(path: str) -> dict:
    """The GGUF header's settings (architecture, name, context length, the chat template…) without loading the model.
    Big arrays (the tokenizer's 150 000 words) are skipped."""
    want_scalar = ("general.architecture", "general.name", "general.size_label", "general.basename", "tokenizer.chat_template")
    out: dict = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return {}
            struct.unpack("<I", f.read(4))
            struct.unpack("<Q", f.read(8))
            (n_kv,) = struct.unpack("<Q", f.read(8))

            def rstr():
                (n,) = struct.unpack("<Q", f.read(8))
                return f.read(n).decode("utf-8", errors="ignore")
            for _ in range(min(n_kv, 4096)):
                key = rstr()
                (vt,) = struct.unpack("<I", f.read(4))
                if vt in GGUF_SIZES:
                    val = struct.unpack(GGUF_FMT[vt], f.read(GGUF_SIZES[vt]))[0]
                    if key.endswith(".context_length") or key in want_scalar:
                        out[key] = val
                elif vt == 8:
                    if key in want_scalar or key.endswith(".context_length"):
                        out[key] = rstr()
                    else:
                        (n,) = struct.unpack("<Q", f.read(8))
                        f.seek(n, 1)
                elif vt == 9:
                    (at,) = struct.unpack("<I", f.read(4))
                    (alen,) = struct.unpack("<Q", f.read(8))
                    if at in GGUF_SIZES:
                        f.seek(GGUF_SIZES[at] * alen, 1)
                    elif at == 8:
                        for _ in range(alen):
                            (n,) = struct.unpack("<Q", f.read(8))
                            f.seek(n, 1)
                    else:
                        return out  # nested arrays: stop here (nothing we need comes after in practice)
                else:
                    return out
    except (OSError, struct.error, ValueError):
        return out
    return out


def capabilities(path: str, mmproj: str | None = None) -> dict:
    """What a chat model can do, for the Models page symbols: 🔧 tools (calls the app's tools by itself), 👁 vision,
    🎬 video (watches a clip's frames), 🧠 thinking, 🎤 hears audio, and its context length. Cached per file."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return {}
    key = f"{p.resolve()}|{int(st.st_mtime)}|{st.st_size}|{mmproj or ''}"
    try:
        cache = json.loads(CAPS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return cache[key]
    meta = gguf_meta(str(p)) if p.suffix == ".gguf" else {}
    arch = str(meta.get("general.architecture") or "")
    tpl = str(meta.get("tokenizer.chat_template") or "")
    name = (p.name + " " + str(meta.get("general.name") or "") + " " + arch).lower().replace("_", "-")
    ctx = next((v for k, v in meta.items() if k.endswith(".context_length")), None)
    tools = bool(re.search(r"tool_call|tools\b|\[TOOL_CALLS\]|<\|python_tag\|>|function_call|<tool_call>|ipython", tpl))
    thinking = bool(re.search(r"<think>|enable_thinking|reasoning_content|<\|channel\|>|thinking", tpl)) or \
        any(w in name for w in ("deepseek-r1", "qwq", "-thinking", "magistral", "phi-4-reasoning", "gpt-oss"))
    vl_name = bool(re.search(r"-vl\b|\bvl-|vision|llava|minicpm-v|moondream|pixtral|smolvlm|gemma-?3(?![0-9])|qwen3\.?5|"
                             r"internvl|glm-4v|mistral-small-3", name)) and "embedding" not in name
    vision = bool(mmproj)
    audio = bool(mmproj and re.search(r"audio|whisper|ultravox|omni", (mmproj or "").lower())) or "omni" in name
    flat = name.replace("-", "").replace(".", "")
    video = vision and any(w.replace("-", "").replace(".", "") in flat for w in VIDEO_FAMILIES)
    caps = {"tools": tools, "thinking": thinking, "vision": vision, "vision_missing": (not vision) and vl_name,
            "video": vision, "video_trained": video, "audio": audio, "context": int(ctx) if isinstance(ctx, int) else None,
            "arch": arch or None, "params": meta.get("general.size_label"), "template": bool(tpl),
            "embedding": "embed" in arch or "embedding" in name}
    cache[key] = caps
    try:
        CAPS_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass
    return caps


COMPONENT_WORDS = ("vae", "encoder", "clip_l", "clip_g", "flux_ae", "t5", "umt5", "text_encoder")
NOT_TEXT = {"t5", "t5encoder", "flux", "sd3", "wan", "ltxv", "clip", "umt5", "nomic-bert", "bert"}
# Stable Diffusion checkpoints converted to GGUF often carry no architecture tag, so names identify them.
IMAGE_WORDS = ("sdxl", "sd_xl", "sd-xl", "sd15", "sd1.5", "sd-1.5", "v1-5", "v1.5", "sd2.1", "sd21", "sd-2", "pony",
               "illustrious", "juggernaut", "realvis", "dreamshaper", "noobai", "animagine", "stable-diffusion")

# Models downloaded through the app remember their type here, whatever their file is called.
REGISTRY = DATA / "registry.json"
_reg_cache: tuple[float, dict] = (0.0, {})


def registry() -> dict:
    global _reg_cache
    try:
        mtime = REGISTRY.stat().st_mtime
    except OSError:
        return {}
    if mtime != _reg_cache[0]:
        try:
            _reg_cache = (mtime, json.loads(REGISTRY.read_text(encoding="utf-8")))
        except ValueError:
            return {}
    return _reg_cache[1]


def register(names: list[str], modality: str) -> None:
    r = dict(registry())
    r.update({n.rsplit("/", 1)[-1].lower(): modality for n in names})
    REGISTRY.write_text(json.dumps(r, indent=1), encoding="utf-8")


def is_projector(name: str) -> bool:
    n = name.lower()
    return n.startswith("mmproj") or "-mmproj" in n or "projector" in n


def projector_for(model: Path) -> Path | None:
    return next(iter(sorted(p for p in model.parent.glob("*.gguf") if is_projector(p.name))), None)


def classify(p: Path) -> tuple[str | None, str | None]:
    """-> (modality, arch). None modality = a helper file (encoder, VAE, projector)."""
    name = p.name.lower()
    if is_projector(name):
        return None, None
    arch = gguf_arch(str(p), p.stat().st_mtime) if p.suffix == ".gguf" else None
    known = registry().get(name)
    if known in ("image", "video"):
        return known, arch or ("wan" if known == "video" else "sd")
    if known in ("text", "vision") and p.suffix == ".gguf":
        return "text", arch
    if arch == "wan" or ("wan" in name and not any(w in name for w in COMPONENT_WORDS)):
        return "video", arch or "wan"
    if arch in ("flux", "sd3") or (not arch and any(w in name for w in IMAGE_WORDS)) or "sdxl" in name or "sd_xl" in name:
        return "image", arch or "sd"
    if any(w in name for w in COMPONENT_WORDS) or arch in NOT_TEXT or p.suffix != ".gguf" or not arch:
        return None, arch
    return "text", arch


def display_name(p: Path) -> str:
    return p.parent.name if p.stem.lower() in ("model", "ggml-model", "weights") else p.stem


def scan() -> list[dict]:
    seen, out = set(), []
    for base in model_dirs():
        for p in base.rglob("*"):
            if p.suffix not in (".gguf", ".safetensors") or not p.is_file() or THREE_D in p.parents:
                continue
            key = (p.name.lower(), p.stat().st_size)
            if key in seen:  # same file in two folders
                continue
            seen.add(key)
            modality, arch = classify(p)
            if not modality:
                continue
            proj = projector_for(p) if modality == "text" else None
            size = p.stat().st_size + (proj.stat().st_size if proj else 0)
            out.append({"path": str(p), "name": display_name(p), "file": p.name, "modality": modality,
                        "arch": arch, "size": size, "vision": bool(proj), "mmproj": str(proj) if proj else None,
                        "owned": MODELS in p.parents, "folder": str(base)})
    return out


def find_file(*patterns: str) -> Path | None:
    """Helper files (encoders, VAEs) are found in any model folder."""
    for base in model_dirs():
        for pat in patterns:
            hit = next((p for p in base.rglob(pat) if p.is_file() and not p.name.endswith(".part")), None)
            if hit:
                return hit
    return None


# ---------------------------------------------------------------- active model per type
def installed(modality: str) -> list[dict]:
    items = scan()
    if modality == "vision":  # anything that can see: VL models + text models with a vision add-on
        return [m for m in items if m["vision"]]
    return [m for m in items if m["modality"] == modality]


def active_path(modality: str) -> str | None:
    """The chosen model, or a sensible default so things work before the user picks anything."""
    chosen = load_settings()["active"].get(modality) or ""
    items = installed(modality)
    if any(m["path"] == chosen for m in items):
        return chosen
    if not items:
        return None
    if modality == "text":
        usable = [m for m in items if m["size"] > 2e9] or items  # tiny models can't use tools
        for pref in ("qwen3.5-4b", "nemotron", "qwen3.5", "qwen"):
            hit = next((m for m in sorted(usable, key=lambda m: m["size"]) if pref in m["file"].lower()), None)
            if hit:
                return hit["path"]
        return sorted(usable, key=lambda m: m["size"])[0]["path"]
    if modality == "video":  # 4-step distilled Wan is ~5x faster
        return (next((m for m in items if "distill" in m["file"].lower()), None) or items[0])["path"]
    if modality == "image":
        usable = [m for m in items if image_parts(m["path"])[1] is None]
        return (usable or items)[0]["path"]
    return sorted(items, key=lambda m: m["size"])[0]["path"]


def set_active(modality: str, value: str) -> None:
    save_settings({"active": {modality: value}})


def image_parts(path: str) -> tuple[dict, str | None]:
    """How to run an image model -> (args, problem). SDXL GGUFs are one file; FLUX needs 3 helpers."""
    p = Path(path)
    _, arch = classify(p)
    if arch == "flux":
        t5 = find_file("t5-v1_1-xxl-encoder-*.gguf")
        clip, vae = find_file("clip_l.safetensors"), find_file("flux_ae.safetensors", "ae.safetensors")
        missing = [n for n, f in (("T5 encoder", t5), ("clip_l", clip), ("FLUX VAE", vae)) if not f]
        if missing:
            return {}, "Missing helper files: " + ", ".join(missing) + " (download FLUX from the store)"
        dev = "dev" in p.name.lower()  # FLUX dev needs ~20 steps; schnell is distilled to 4
        return {"kind": "flux", "args": ["--diffusion-model", str(p), "--t5xxl", str(t5), "--clip_l", str(clip),
                                         "--vae", str(vae)], "steps": 20 if dev else 4, "cfg": 1.0, "size": 512}, None
    if arch == "sd3":
        return {}, "SD 3.5 needs extra text encoders — not supported"
    n = p.name.lower()
    lightning = any(k in n for k in ("lightning", "turbo", "lcm", "hyper"))
    small = any(k in n for k in ("sd15", "sd1.5", "sd-1.5", "v1-5", "v1.5", "sd2", "sd21"))  # SD 1.x/2.x: 512 px
    return {"kind": "sd", "args": ["-m", str(p)], "steps": 4 if lightning else 20, "cfg": 1.0 if lightning else 6.0,
            "size": 512 if small else 768, "sampler": "euler" if lightning else "euler_a"}, None


def video_parts(path: str) -> tuple[dict, str | None]:
    t5 = find_file("umt5-xxl-encoder-*.gguf")
    vae = find_file("wan_2.1_vae.safetensors")
    missing = [n for n, f in (("umt5 encoder", t5), ("Wan VAE", vae)) if not f]
    if missing:
        return {}, "Missing helper files: " + ", ".join(missing) + " (download Wan from the store)"
    distill = "distill" in Path(path).name.lower()
    return {"args": ["--diffusion-model", path, "--t5xxl", str(t5), "--vae", str(vae)],
            "steps": 4 if distill else 20, "cfg": 1.0 if distill else 6.0}, None


# ---------------------------------------------------------------- downloads (resumable)
downloads: dict[str, dict] = {}


def repo_folder(repo: str) -> Path:
    return MODELS / repo.replace("/", "__")


THREE_D = MODELS / "3d"  # 3D AI models (app/models3d.py): kept apart, never scanned as picture / video / chat models


def _local(repo: str, path: str, local: str | None) -> Path:
    if local and local.startswith("@3d/"):  # a 3D model keeps its folders (several files share names like config.json)
        return THREE_D / repo.replace("/", "__") / local[4:]
    return repo_folder(repo) / (local or path.rsplit("/", 1)[-1])


def _all_names() -> set[str]:
    """Names of every model file on this PC (refreshed every few seconds) — searches check many files at once."""
    def fetch():
        return {p.name.lower() for base in model_dirs() for p in base.rglob("*")
                if p.suffix in (".gguf", ".safetensors") and p.is_file() and THREE_D not in p.parents}
    return _cached("names", 5, fetch)


GENERIC = {"model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json",
           "preprocessor_config.json", "model.gguf", "model.safetensors", "readme.md"}


def file_present(repo: str, path: str, local: str | None) -> bool:
    name = local or path.rsplit("/", 1)[-1]
    if _local(repo, path, local).exists():
        return True
    # A same-named file elsewhere only counts for unique names — every Whisper model has a "model.bin".
    return not is_projector(name) and name.lower() not in GENERIC and name.lower() in _all_names()


def catalog_installed(files) -> bool:
    return all(file_present(*f) for f in files)


DL_STATE = DATA / "downloads.json"
_dl_lock = threading.Lock()


def _save_downloads() -> None:
    """Unfinished downloads are saved, so closing the app doesn't lose them: they resume on the next start."""
    with _dl_lock:
        keep = {k: {f: v for f, v in d.items() if f != "cancel"} for k, d in downloads.items()
                if d["status"] in ("running", "error")}
        tmp = DL_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(keep), encoding="utf-8")
        tmp.replace(DL_STATE)


def resume_downloads() -> None:
    try:
        saved = json.loads(DL_STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for did, d in saved.items():
        downloads[did] = d
        if d["status"] == "running":
            d.update(speed=0, error=None)
            threading.Thread(target=_fetch, args=(did,), daemon=True).start()


def same_files(a, b) -> bool:
    return [list(x) for x in a] == [list(x) for x in b]


def _fetch(did: str) -> None:
    st = downloads[did]
    total_all = max(1.0, st["size_gb"] * 1e9)
    base, part = 0, None
    try:
        for i, (repo, path, local) in enumerate(st["files"]):
            dest = _local(repo, path, local)
            st["file"] = f"{i + 1}/{len(st['files'])} · {dest.name}"
            if file_present(repo, path, local):
                found = dest if dest.exists() else find_file(dest.name)
                base += found.stat().st_size if found else 0
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_suffix(dest.suffix + ".part")
            have = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            url = f"{HF}/{repo}/resolve/main/{path}"
            with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                              timeout=httpx.Timeout(30, read=120)) as r:
                if r.status_code == 416:  # already complete
                    part.replace(dest)
                    base += dest.stat().st_size
                    continue
                r.raise_for_status()
                if r.status_code == 200:  # server ignored the range: start over
                    have = 0
                t0, done0 = time.time(), have
                with open(part, "ab" if have else "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        if st.get("cancel"):
                            raise RuntimeError("cancelled")
                        f.write(chunk)
                        have += len(chunk)
                        st["progress"] = min(0.999, (base + have) / total_all)  # across all files of this model
                        st["speed"] = (have - done0) / max(0.5, time.time() - t0)
            part.replace(dest)
            base += dest.stat().st_size
        st["status"], st["progress"] = "done", 1.0
        if st.get("activate"):  # e.g. "Get & use": switch to it as soon as it's here
            set_active(*st["activate"])
    except Exception as e:  # noqa: BLE001 — shown on the model card
        if st.get("cancel"):
            st["status"], st["error"] = "cancelled", None
            if part is not None:
                part.unlink(missing_ok=True)  # a cancelled download leaves nothing behind
        else:
            st["status"], st["error"] = "error", str(e)[:300]
    finally:
        _save_downloads()


def start_download(name: str, modality: str, files: list, size_gb: float, activate: tuple | None = None) -> dict:
    files = [list(f) for f in files]
    for d in downloads.values():  # same files already downloading
        if d["status"] == "running" and same_files(d["files"], files):
            return d
    if size_gb > free_disk_gb() - 2:
        raise ValueError("Not enough free disk space")
    # Remember what each main file is, so it shows under the right tab even with an odd file name.
    main = [p for _, p, loc in files if not is_projector(p.rsplit("/", 1)[-1]) and not is_helper(p)]
    if main and modality in ("text", "vision", "image", "video"):
        register([loc or p for _, p, loc in files if p in main], modality)
    for k in [k for k, d in downloads.items() if d["status"] != "running" and same_files(d["files"], files)]:
        downloads.pop(k)  # a retry replaces the failed entry
    did = uuid.uuid4().hex[:10]
    downloads[did] = {"id": did, "name": name, "modality": modality, "files": files, "status": "running",
                      "progress": 0.0, "speed": 0, "file": "", "error": None, "size_gb": size_gb,
                      "activate": list(activate) if activate else None}
    _save_downloads()
    threading.Thread(target=_fetch, args=(did,), daemon=True).start()
    return downloads[did]


def cancel_download(did: str) -> None:
    d = downloads.get(did)
    if not d:
        return
    if d["status"] == "running":
        d["cancel"] = True
    else:
        downloads.pop(did)
        _save_downloads()


# ---------------------------------------------------------------- Hugging Face search
PIPELINE = {"vision": "image-text-to-text", "video": "text-to-video"}
QUANT_ORDER = ("q4_k_m", "q4_k_s", "q4_0", "iq4_xs", "iq4_nl", "q5_k_m", "q5_0", "q8_0", "q6_k", "q3_k_m")
SPLIT = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
_cache: dict[str, tuple[float, object]] = {}


def is_helper(path: str) -> bool:
    """Files that aren't a model you can use on their own: VAEs, text encoders, draft/speculative heads."""
    n = path.rsplit("/", 1)[-1].lower()
    return any(w in n for w in ("vae", "text_encoder", "text-encoder", "clip_l", "clip_g", "t5xxl", "umt5", "t5-v1",
                                "ae.safetensors", "mtp-", "-mtp", "_mtp", "draft", "eagle", "medusa", "imatrix"))


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val


def judge(modality: str, repo: str, tags: list[str], names: list[str]) -> tuple[str, str]:
    """Can this app run the repo for this type? -> ('ok' | 'maybe' | 'no', reason). Checked BEFORE downloading."""
    s = (repo + " " + " ".join(tags)).lower()
    has_proj = any(is_projector(n.rsplit("/", 1)[-1]) for n in names)
    video_words = ("ltx", "wan2", "wan-2", "wan_2", "hunyuan", "mochi", "cogvideo", "text-to-video")
    if modality in ("text", "vision"):
        if any(k in s for k in video_words + ("flux", "stable-diffusion", "sdxl", "text-to-image")):
            return "no", "This is part of an image or video model, not a chat model"
        if any(k in s for k in ("embed", "rerank", "whisper", "text-to-speech", "-tts", "tts-", "sentence-similarity")):
            return "no", "Not a chat model"
        if modality == "vision" and not has_proj:
            return "no", "Can't see the screen — this repo has no vision add-on"
        return "ok", "Chat model that can also see images" if has_proj else "Chat model"
    if modality == "video":
        if re.search(r"wan[\s_.-]*2[\s_.-]*2", s):
            return "no", "Wan 2.2 isn't supported yet — use a Wan 2.1 1.3B model"
        if any(k in s for k in ("ltx", "hunyuan", "mochi", "cogvideo", "sulphur", "animatediff", "skyreels")):
            return "no", "This video model type (like LTX) isn't supported — use Wan 2.1 1.3B"
        if re.search(r"wan[\s_.-]*2[\s_.-]*1", s):
            if any(k in s for k in ("i2v", "flf2v", "vace", "fun-")):
                return "no", "Only text-to-video Wan works here (this one needs a start image)"
            return "ok", "Wan 2.1 — works (the 14B version is very heavy)" if "14b" in s else "Wan 2.1 — works"
        return "no", "Not a video model this app can run — use Wan 2.1 1.3B"
    if modality == "image":
        if any(k in s for k in video_words):
            return "no", "This is a video model"
        if "flux" in s:
            if any(k in s for k in ("flux.2", "flux2", "kontext", "fill", "redux", "depth", "canny")):
                return "no", "This FLUX variant isn't supported"
            if not (find_file("clip_l.safetensors") and find_file("t5-v1_1-xxl-encoder-*.gguf")):
                return "maybe", "FLUX works, but first get “FLUX.1 schnell” from the list once (it brings the helper files)"
            return "ok", "FLUX — works"
        if any(k in s for k in ("sd3", "stable-diffusion-3", "z-image", "qwen-image", "hidream", "chroma", "lumina",
                                "pixart", "kolors", "sana", "cosmos", "omnigen", "hunyuanimage")):
            return "no", "This image model type isn't supported yet"
        if any(k in s for k in IMAGE_WORDS + ("lightning", "turbo")):
            return "ok", "Stable Diffusion — works"
        return "maybe", "Unknown image model type — it may not work"
    return "no", "Search isn't available for this type"


def _tree(repo: str) -> list[dict]:
    def fetch():
        r = httpx.get(f"{HF}/api/models/{repo}/tree/main", params={"recursive": "true"}, timeout=30)
        r.raise_for_status()
        return [{"path": f["path"], "size": (f.get("lfs") or {}).get("size") or f.get("size", 0)}
                for f in r.json() if f.get("type") == "file" and f["path"].endswith((".gguf", ".safetensors"))]
    return _cached("tree:" + repo, 600, fetch)


def group_files(repo: str, raw: list[dict]) -> list[dict]:
    """Joins split GGUFs (-00001-of-00003) into one entry and labels each file's role."""
    groups: dict[str, dict] = {}
    for f in raw:
        name = f["path"]
        key = SPLIT.sub(".gguf", name)
        g = groups.setdefault(key, {"name": key.rsplit("/", 1)[-1], "paths": [], "size": 0})
        g["paths"].append(name)
        g["size"] += f["size"]
    out = []
    for g in groups.values():
        g["paths"].sort()
        leaf = g["name"]
        g["role"] = "vision" if is_projector(leaf) else "helper" if is_helper(leaf) else "model"
        g["fit"], g["why"] = rate(g["size"] / 1e9)
        g["present"] = all(file_present(repo, p, None) for p in g["paths"])
        out.append(g)
    return out


def recommend(groups: list[dict]) -> tuple[dict | None, dict | None]:
    """The model file most people want (Q4_K_M), plus the vision add-on if the repo has one."""
    models = [g for g in groups if g["role"] == "model"]

    def odd(g):  # 1-step / x0 Lightning variants need special sampler settings: prefer 4-step
        n = g["name"].lower()
        return (0 if "4step" in n else 1 if "8step" in n else 3 if ("1step" in n or "x0" in n) else 2)
    rec = None
    for q in QUANT_ORDER:
        rec = next((g for g in sorted(models, key=lambda g: (odd(g), g["size"])) if q in g["name"].lower()), None)
        if rec:
            break
    rec = rec or (min(models, key=lambda g: g["size"]) if models else None)
    projs = [g for g in groups if g["role"] == "vision"]
    proj = next((g for g in projs if "f16" in g["name"].lower()), None) or (min(projs, key=lambda g: g["size"]) if projs else None)
    return rec, proj


def hf_search(query: str, modality: str) -> list[dict]:
    def fetch():  # what Hugging Face says is cached for a few minutes...
        params = [("search", query), ("filter", "gguf"), ("sort", "downloads"), ("limit", "12")]
        params += [("expand[]", k) for k in ("downloads", "likes", "lastModified", "pipeline_tag", "tags", "gguf", "siblings")]
        if modality in PIPELINE:
            params.append(("pipeline_tag", PIPELINE[modality]))
        r = httpx.get(f"{HF}/api/models", params=params, timeout=30)
        r.raise_for_status()
        found = r.json()
        with ThreadPoolExecutor(8) as pool:  # file sizes for every result at once
            trees = list(pool.map(lambda m: _safe_tree(m["id"]), found))
        return list(zip(found, trees))
    raw = _cached(f"search:{modality}:{query.lower()}", 300, fetch)
    active = Path(active_path(modality) or "").name.lower()
    on_pc = {Path(x["path"]).name.lower(): x["path"] for x in scan()}
    out = []
    for m, tree in raw:  # ...but "on this PC", "active" and download progress are always fresh
        names = [s["rfilename"] for s in m.get("siblings", [])]
        verdict, reason = judge(modality, m["id"], m.get("tags", []), names)
        groups = group_files(m["id"], tree) if tree else []
        rec, proj = recommend(groups)
        with_proj = bool(proj) and modality in ("text", "vision")
        total = (rec["size"] if rec else 0) + (proj["size"] if with_proj else 0)
        fit, why = rate(total / 1e9, modality in ("image", "video")) if rec else ("no", "No model files found")
        want = (rec["paths"] if rec else []) + (proj["paths"] if with_proj else [])
        dl = next((d for d in downloads.values() if d["files"] and d["files"][0][0] == m["id"]
                   and d["status"] in ("running", "error") and {f[1] for f in d["files"]} >= set(want[:1])), None)
        meta = m.get("gguf") or {}
        rec_name = rec["paths"][0].rsplit("/", 1)[-1].lower() if rec else ""
        out.append({"repo": m["id"], "author": m["id"].split("/")[0], "name": m["id"].split("/")[-1],
                    "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                    "updated": (m.get("lastModified") or "")[:10], "params": meta.get("total"),
                    "arch": meta.get("architecture"), "verdict": verdict, "reason": reason,
                    "vision": any(g["role"] == "vision" for g in groups), "rec": rec, "proj": proj if with_proj else None,
                    "total": total, "fit": fit, "why": why,
                    "present": bool(rec and all(file_present(m["id"], p, None) for p in want)),
                    "active": bool(rec_name) and rec_name == active, "path": on_pc.get(rec_name),
                    "download": {k: dl[k] for k in ("id", "status", "progress", "speed", "error")} if dl else None})
    return out


def _safe_tree(repo: str) -> list[dict]:
    try:
        return _tree(repo)
    except httpx.HTTPError:
        return []


def hf_files(repo: str) -> list[dict]:
    groups = group_files(repo, _tree(repo))
    rec, _ = recommend(groups)
    for g in groups:
        g["recommended"] = g is rec
    order = {"model": 0, "vision": 1, "helper": 2}
    return sorted(groups, key=lambda g: (order[g["role"]], not g["recommended"], g["size"]))


# ---------------------------------------------------------------- voices (Piper) — 177 voices, 58 languages
PIPER_JSON = DATA / "piper_voices.json"
QUALITY_ORDER = {"medium": 0, "high": 1, "low": 2, "x_low": 3}


def piper_catalog() -> dict:
    """The official Piper voice list. Kept on disk too, so voice names still show when offline."""
    hit = _cache.get("piper")
    if hit and time.time() - hit[0] < 86400:
        return hit[1]
    try:
        r = httpx.get(f"{HF}/rhasspy/piper-voices/resolve/main/voices.json", follow_redirects=True, timeout=30)
        r.raise_for_status()
        cat = r.json()
        PIPER_JSON.write_text(r.text, encoding="utf-8")
    except (httpx.HTTPError, ValueError):
        try:
            cat = json.loads(PIPER_JSON.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    _cache["piper"] = (time.time(), cat)
    return cat


def voice_label(vid: str, cat: dict | None = None) -> str:
    v = (cat if cat is not None else piper_catalog()).get(vid)
    if not v:
        return VOICES.get(vid, vid)
    lang = v["language"]
    native = f" ({lang['name_native']})" if lang["name_native"] != lang["name_english"] else ""
    extra = f" · {v['num_speakers']} voices" if v.get("num_speakers", 1) > 1 else ""
    return f"{lang['name_english']}{native}, {lang['country_english']} · {v['name']} · {v['quality']}{extra}"


def installed_voices() -> list[str]:
    """Every Piper voice in any model folder (a .onnx file with its .onnx.json next to it) + Kokoro's."""
    found = list(KOKORO) if kokoro_files() else []
    for base in model_dirs():
        for p in base.rglob("*.onnx"):
            if Path(str(p) + ".json").exists() and p.stem not in found:
                found.append(p.stem)
    return found


def voice_search(query: str) -> list[dict]:
    cat, q = piper_catalog(), query.lower().split()
    have, active = installed_voices(), load_settings()["active"].get("voice")
    out = []
    for vid, v in cat.items():
        lang = v["language"]
        hay = " ".join([vid, v["name"], lang["name_english"], lang["name_native"], lang["country_english"],
                        lang["code"], v["quality"]]).lower()
        if all(w in hay for w in q):
            onnx = next((s["size_bytes"] for f, s in v["files"].items() if f.endswith(".onnx")), 60e6)
            out.append({"id": vid, "name": voice_label(vid, cat), "quality": v["quality"], "size_gb": onnx / 1e9,
                        "language": lang["name_english"], "installed": vid in have, "active": vid == active,
                        "download": dl_state("voice", vid)})
    return sorted(out, key=lambda x: (x["language"], QUALITY_ORDER.get(x["quality"], 9), x["id"]))[:60]


def voice_download(vid: str) -> dict:
    if vid in KOKORO:  # all Kokoro voices come in the same two files (~350 MB)
        return start_download("Kokoro natural voices", "voice", [(KOKORO_REPO, "voices-v1.0.bin", None),
                              (KOKORO_REPO, "kokoro-v1.0.onnx", None)], 0.35, activate=("voice", vid))
    entry = piper_catalog().get(vid)
    if entry:
        paths = [p for p in entry["files"] if p.endswith((".onnx", ".onnx.json"))]
        size = sum(entry["files"][p]["size_bytes"] for p in paths) / 1e9
    else:
        lang, speaker, q = vid.split("-")
        paths = [f"{lang.split('_')[0]}/{lang}/{speaker}/{q}/{vid}{x}" for x in (".onnx.json", ".onnx")]
        size = 0.064
    files = [("rhasspy/piper-voices", p, None) for p in sorted(paths, key=lambda p: p.endswith(".onnx"))]
    return start_download(voice_label(vid), "voice", files, size, activate=("voice", vid))


def dl_state(modality: str, value: str) -> dict | None:
    d = next((d for d in downloads.values() if d.get("activate") == [modality, value]
              and d["status"] in ("running", "error")), None)
    return {k: d[k] for k in ("id", "status", "progress", "speed", "error")} if d else None


# ---------------------------------------------------------------- speech-to-text models (faster-whisper)
WHISPER_FILES = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json",
                 "preprocessor_config.json")


def repo_files(repo: str) -> list[dict]:
    """All files of a Hugging Face repo with sizes (cached)."""
    def fetch():
        r = httpx.get(f"{HF}/api/models/{repo}/tree/main", params={"recursive": "true"}, timeout=30)
        r.raise_for_status()
        return [{"path": f["path"], "size": (f.get("lfs") or {}).get("size") or f.get("size", 0)}
                for f in r.json() if f.get("type") == "file"]
    return _cached("files:" + repo, 600, fetch)


def is_whisper_dir(d: Path) -> bool:
    return (d / "model.bin").exists() and (d / "tokenizer.json").exists() and \
        ((d / "vocabulary.txt").exists() or (d / "vocabulary.json").exists())


def whisper_models() -> list[dict]:
    """Built-in sizes (downloaded or not) + any other faster-whisper model found in the model folders."""
    active = load_settings()["active"].get("transcription") or "base"
    out, seen = [], set()
    for key, (name, note, gbs, repo) in WHISPER.items():
        d = next((b / f"whisper-{key}" for b in model_dirs() if is_whisper_dir(b / f"whisper-{key}")), None) or \
            next((b / repo.replace("/", "__") for b in model_dirs() if is_whisper_dir(b / repo.replace("/", "__"))), None)
        if d:
            seen.add(d.resolve())
        out.append({"id": key, "name": name, "note": note, "size_gb": gbs, "installed": bool(d),
                     "active": active == key or (d is not None and active == str(d)), "builtin": True,
                     "download": dl_state("transcription", key)})
    for base in model_dirs():
        for cfg in base.rglob("model.bin"):
            d = cfg.parent
            if d.resolve() in seen or not is_whisper_dir(d):
                continue
            seen.add(d.resolve())
            out.append({"id": str(d), "name": d.name.replace("__", " / "), "note": "Downloaded from Hugging Face",
                        "size_gb": cfg.stat().st_size / 1e9, "installed": True, "active": active == str(d),
                        "builtin": False})
    return out


def whisper_download(key: str) -> dict:
    name, _, gbs, repo = WHISPER[key]
    files = [(repo, f["path"], None) for f in sorted(repo_files(repo), key=lambda f: f["size"]) if f["path"] in WHISPER_FILES]
    return start_download(name, "transcription", files, gbs, activate=("transcription", key))


def whisper_search(query: str) -> list[dict]:
    def fetch():
        params = [("search", query), ("filter", "ctranslate2"), ("sort", "downloads"), ("limit", "15")]
        params += [("expand[]", k) for k in ("downloads", "likes", "lastModified", "siblings")]
        r = httpx.get(f"{HF}/api/models", params=params, timeout=30)
        r.raise_for_status()
        found = r.json()
        with ThreadPoolExecutor(8) as pool:
            sizes = list(pool.map(lambda m: _safe_files(m["id"]), found))
        return list(zip(found, sizes))
    raw = _cached(f"whisper:{query.lower()}", 300, fetch)
    by_repo = {v[3]: k for k, v in WHISPER.items()}
    have = {m["id"]: m for m in whisper_models()}
    out = []
    for m, files in raw:
        names = {s["rfilename"] for s in m.get("siblings", [])}
        ok = {"model.bin", "config.json", "tokenizer.json"} <= names and bool(names & {"vocabulary.txt", "vocabulary.json"})
        size = next((f["size"] for f in files if f["path"] == "model.bin"), 0)
        english = m["id"].lower().endswith(".en") or ".en-" in m["id"].lower()
        reason = ("Speech-to-text model — works" + (" (English only)" if english else "")) if ok else \
            "Not a faster-whisper model (needs model.bin + tokenizer)"
        key = by_repo.get(m["id"])
        local = str(repo_folder(m["id"]))
        state = have.get(key) or have.get(local)
        fit, why = rate(size / 1e9)
        dl = next((d for d in downloads.values() if d["files"] and d["files"][0][0] == m["id"]
                   and d["status"] in ("running", "error")), None)
        out.append({"repo": m["id"], "author": m["id"].split("/")[0], "name": m["id"].split("/")[-1],
                    "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                    "updated": (m.get("lastModified") or "")[:10], "verdict": "ok" if ok else "no", "reason": reason,
                    "size": size, "fit": fit, "why": why, "present": bool(state and state["installed"]),
                    "active": bool(state and state["active"]), "id": key or local,
                    "files": [f["path"] for f in files if f["path"] in WHISPER_FILES],
                    "download": {k: dl[k] for k in ("id", "status", "progress", "speed", "error")} if dl else None})
    return out


def _safe_files(repo: str) -> list[dict]:
    try:
        return repo_files(repo)
    except httpx.HTTPError:
        return []
