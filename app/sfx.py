"""Sound effects for videos: Sony AI's Woosh video-to-audio model (engines/woosh, its own CPU Python).

The model WATCHES each clip and makes the sounds that fit what is seen (steps, rain, a door, a kiss, a room's
quiet hum...), steered by a short description. It makes 8 s at 24 fps, so every clip (Wan: 16 fps, max 5 s) is
first turned into 24 fps and held on its last frame up to 8 s; the sound is then cut back to the clip's length.
One engine process for all clips of a job; it exits afterwards (it needs ~5 GB of RAM while it runs).
Weights are CC-BY-NC 4.0: fine for personal use, not for selling."""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .config import DATA, ENGINES, NO_WINDOW
from .plat import kill_tree, spawn, venv_python

ROOT = ENGINES / "woosh"
PY = venv_python(ROOT / "venv")
NEEDED = ["checkpoints/Woosh-DVFlow-8s", "checkpoints/TextConditionerV", "checkpoints/Woosh-AE"]


def ready() -> bool:
    """Installed and complete (the venv, the three models with their weights, Synchformer, roberta's tokenizer)."""
    return (PY.exists() and (ROOT / "run_sfx.py").exists()
            and all(any((ROOT / d).glob("weights.*")) for d in NEEDED)
            and (ROOT / "checkpoints" / "synchformer_state_dict.pth").exists()
            and any((ROOT / "home" / "hub").glob("models--roberta-large/snapshots/*/vocab.json")))


def _ffmpeg(*args: str) -> None:
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-400:])


def _secs(p: Path) -> float:
    import imageio_ffmpeg
    return float(imageio_ffmpeg.count_frames_and_secs(str(p))[1])


def _lift(wav: Path, secs: float, target_db: float = -24.0, most_db: float = 30.0) -> float:
    """dB to ADD so quiet sounds can be heard: a bedroom scene came out at -58 dBFS (silent on laptop speakers);
    waves at -14 stay as they are (never turned down; at most +30 dB so pure hiss isn't blown up)."""
    import wave

    import numpy as np
    with wave.open(str(wav)) as w:
        n = min(w.getnframes(), int(w.getframerate() * secs))
        x = np.frombuffer(w.readframes(n), np.int16).astype(np.float32) / 32768
    rms_db = 20 * np.log10(float(np.sqrt(np.mean(x ** 2))) + 1e-9) if len(x) else target_db
    return float(min(most_db, max(0.0, target_db - rms_db)))


def make(clips: list[tuple[Path, str]], cancelled=lambda: False, status=lambda s: None,
         timeout: float = 1200) -> list[Path]:
    """clips: [(video file, what the sound should be)] -> one WAV per clip, as long as the clip (the caller
    shreds them). Raises RuntimeError with a short reason when it can't."""
    if not ready():
        raise RuntimeError("the sound-effects model isn't installed")
    tmp = Path(tempfile.mkdtemp(prefix="sfx-", dir=DATA))
    items, lengths, outs = [], [], []
    for i, (video, text) in enumerate(clips):
        d = _secs(video)
        lengths.append(d)
        prep = tmp / f"in{i}.mp4"  # 24 fps, 8 s (the last frame held), small: the model looks at 224 px
        _ffmpeg("-i", str(video), "-an", "-vf", f"fps=24,scale=-2:256,tpad=stop_mode=clone:stop_duration={max(0.0, 8.2 - d):.2f}",
                "-t", "8.1", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(prep))
        items.append({"video": str(prep), "text": text[:300], "out": str(tmp / f"raw{i}.wav"), "seed": 1234 + i})
    job = tmp / "job.json"
    job.write_text(json.dumps({"items": items}), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}  # its own Python, nothing of ours
    proc = spawn([str(PY), str(ROOT / "run_sfx.py"), str(job)], cwd=str(ROOT), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW)
    t0, tail, result = time.time(), [], None
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            tail = (tail + [line])[-12:]
            if line.startswith("PROGRESS:"):
                step = line[9:].strip()
                status("Loading the sound model…" if step == "loading" else f"Making the sounds (clip {step})…")
            elif line.startswith("RESULT:"):
                result = json.loads(line[7:])
            if cancelled() or time.time() - t0 > timeout:
                raise RuntimeError("stopped" if cancelled() else "the sound model took too long")
        proc.wait(30)
        if proc.returncode != 0 or not result:
            raise RuntimeError("the sound model failed: " + " | ".join(tail[-3:])[:300])
        for i, d in enumerate(lengths):  # back to the clip's length, soft end, 44.1 kHz stereo like the rest
            out = tmp / f"sfx{i}.wav"
            gain = _lift(Path(items[i]["out"]), d)
            _ffmpeg("-i", items[i]["out"], "-af", f"atrim=0:{d:.3f},afade=t=out:st={max(0.0, d - 0.25):.3f}:d=0.25,"
                    f"volume={gain:.1f}dB,alimiter=limit=0.89:level=false,"
                    "aresample=44100,aformat=channel_layouts=stereo", "-c:a", "pcm_s16le", str(out))
            outs.append(out)
        return outs
    finally:
        if proc.poll() is None:
            kill_tree(proc.pid)
        for f in tmp.glob("*"):
            if f not in outs:
                f.unlink(missing_ok=True)
        if not outs:
            tmp.rmdir()


def cleanup(files: list[Path]) -> None:
    """The WAVs from make() and their folder."""
    from . import wipe
    for f in files:
        wipe.shred(f)
    for d in {f.parent for f in files}:
        try:
            d.rmdir()
        except OSError:
            pass
