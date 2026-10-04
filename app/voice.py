"""Speech: Kokoro (natural English voices) and Piper voices for reading aloud / narration, faster-whisper for the
microphone. All run on the CPU and download their model files the first time they're used (or from Models › Voice /
Transcription). Kokoro speaks English only: Romanian text is read by the Romanian Piper voice when it's there."""
import os
import re
import threading
import uuid
import wave
from pathlib import Path

import httpx

from .config import MEDIA, MODELS, load_settings, model_dirs
from .models import (KOKORO, VOICES, WHISPER, WHISPER_FILES, installed_voices, is_whisper_dir, kokoro_files,
                     piper_catalog, repo_files)

HF = "https://huggingface.co"


def _download(url: str, dest: Path) -> None:
    """Stream to .part and rename, so an interrupted download never looks complete."""
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
        r.raise_for_status()
        with open(part, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    part.replace(dest)


def _existing(rel: str) -> Path | None:
    """Voice/whisper files already downloaded into any model folder (e.g. by Local AI 0.1) are reused."""
    for base in model_dirs():
        if (base / rel).exists():
            return base / rel
    return None


def _find_voice(vid: str) -> Path | None:
    for base in model_dirs():
        for p in base.rglob(f"{vid}.onnx"):
            if Path(str(p) + ".json").exists():
                return p
    return None


def voice_installed(vid: str) -> bool:
    return kokoro_files() is not None if vid in KOKORO else _find_voice(vid) is not None


RO_WORDS = re.compile(r"\b(și|si|este|sunt|pentru|că|nu|cu|această|acest|foarte|mulțumesc|multumesc|bună|buna|poți|"
                      r"poti|vreau|asta|aici|acum|dar|sau|mai|care|îți|iti|ești|esti)\b", re.I)


def romanian(text: str) -> bool:
    """Romanian letters, or at least 3 common Romanian words."""
    return bool(re.search(r"[ăâîșşțţ]", text, re.I)) or len(set(m.lower() for m in RO_WORDS.findall(text))) >= 3


def whisper_dir(key: str) -> Path | None:
    """Where a speech-to-text model lives: a built-in size ('small') or a folder path."""
    if key in WHISPER:
        repo = WHISPER[key][3]
        for rel in (f"whisper-{key}", repo.replace("/", "__")):
            d = _existing(rel)
            if d and is_whisper_dir(d):
                return d
        return None
    d = Path(key)
    return d if is_whisper_dir(d) else None


def whisper_installed(key: str) -> bool:
    return whisper_dir(key) is not None


def install_voice(vid: str) -> Path:
    found = _find_voice(vid)
    if found:
        return found
    entry = piper_catalog().get(vid)
    d = MODELS / "piper"
    d.mkdir(exist_ok=True)
    if entry:  # exact file paths from the official voice list
        paths = [p for p in entry["files"] if p.endswith((".onnx", ".onnx.json"))]
    else:
        lang, speaker, q = vid.split("-")
        paths = [f"{lang.split('_')[0]}/{lang}/{speaker}/{q}/{vid}{s}" for s in (".onnx", ".onnx.json")]
    for p in sorted(paths, key=lambda p: p.endswith(".onnx")):  # small .json first
        _download(f"{HF}/rhasspy/piper-voices/resolve/main/{p}", d / p.rsplit("/", 1)[-1])
    return d / f"{vid}.onnx"


def install_whisper(key: str) -> Path:
    found = whisper_dir(key)
    if found:
        return found
    if key not in WHISPER:
        raise FileNotFoundError("That speech-to-text model isn't downloaded")
    repo = WHISPER[key][3]
    d = MODELS / f"whisper-{key}"
    d.mkdir(exist_ok=True)
    # Plain HTTP (huggingface_hub's downloader can hang on Windows). Only the files the model needs —
    # bigger models use vocabulary.json + preprocessor_config.json instead of vocabulary.txt.
    for f in sorted(repo_files(repo), key=lambda f: f["size"]):
        if f["path"] in WHISPER_FILES and not (d / f["path"]).exists():
            _download(f"{HF}/{repo}/resolve/main/{f['path']}", d / f["path"])
    return d


class Voice:
    def __init__(self):
        self._voices: dict = {}
        self._stt: dict = {}
        self._lock = threading.Lock()

    def speak(self, text: str, voice: str | None = None, out: Path | None = None) -> Path:
        s = load_settings()["active"]
        ok = voice and (voice in VOICES or voice in installed_voices() or voice in piper_catalog())
        vid = voice if ok else s.get("voice") or "en_US-lessac-medium"
        if vid in KOKORO and not kokoro_files():
            vid = "en_US-lessac-medium"  # Kokoro's files aren't on this PC (yet)
        if romanian(text) and not vid.startswith("ro_") and _find_voice("ro_RO-mihai-medium"):
            vid = "ro_RO-mihai-medium"  # an English voice reading Romanian sounds broken
        out = out or MEDIA / f"tts-{uuid.uuid4().hex[:10]}.wav"
        if vid in KOKORO:
            return self._kokoro(text, vid[7:], out)
        with self._lock:
            if vid not in self._voices:
                from piper import PiperVoice
                self._voices[vid] = PiperVoice.load(install_voice(vid))
            pv = self._voices[vid]
            with wave.open(str(out), "wb") as wf:  # format set first: a piece with nothing to say (an emoji)
                wf.setnchannels(1)                  # made Piper write no header -> "channels not specified" crash
                wf.setsampwidth(2)
                wf.setframerate(pv.config.sample_rate)
                pv.synthesize_wav(text, wf, set_wav_format=False)
        return out

    def _kokoro(self, text: str, name: str, out: Path) -> Path:
        import numpy as np
        with self._lock:
            if "kokoro" not in self._voices:
                from kokoro_onnx import Kokoro
                model, voices = kokoro_files()
                self._voices["kokoro"] = Kokoro(str(model), str(voices))
            samples, rate = self._voices["kokoro"].create(text, voice=name, speed=1.0,
                                                          lang="en-gb" if name.startswith("b") else "en-us")
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(str(out), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm.tobytes())
        return out

    def transcribe(self, audio: str) -> str:
        s = load_settings()
        key = s["active"].get("transcription") or "base"
        if key not in WHISPER and not whisper_dir(key):
            key = "base"
        lang = s.get("stt_language") or "auto"
        with self._lock:
            if key not in self._stt:
                from faster_whisper import WhisperModel
                threads = max(2, (os.cpu_count() or 4) - 2)  # leave the app responsive
                self._stt[key] = WhisperModel(str(install_whisper(key)), device="cpu", compute_type="int8",
                                              cpu_threads=threads)
            model = self._stt[key]
        # Tuned for short voice messages: a fixed language avoids mis-detection on accents; a gentler voice
        # detector doesn't cut quiet words; not chaining on earlier text stops repeated/hallucinated phrases.
        opts = dict(beam_size=5, vad_filter=True, vad_parameters={"threshold": 0.35, "speech_pad_ms": 500},
                    condition_on_previous_text=False)
        segments, info = model.transcribe(audio, language=None if lang == "auto" else lang, **opts)
        allowed = s.get("stt_auto_languages") or ["en", "ro"]
        if lang == "auto" and info.language not in allowed:
            # Accents get mistaken for other languages (English heard as Bulgarian or French): "detect" picks only
            # between the languages the user speaks. Costs a second pass only when that happens.
            best = max((p for p in info.all_language_probs or [] if p[0] in allowed), key=lambda p: p[1],
                       default=(allowed[0], 0))
            segments, info = model.transcribe(audio, language=best[0], **opts)
        return " ".join(seg.text.strip() for seg in segments).strip()


voice = Voice()
