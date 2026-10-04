"""Local AI: sound effects for video clips with Sony AI's Woosh-DVFlow-8s (video-to-audio, distilled: 4 steps).

It WATCHES the clip (Synchformer features at 24 fps) and makes the sounds that fit what is seen, steered by a
short description. Weights: CC-BY-NC 4.0 (non-commercial use). Runs offline on the CPU, one process for all
clips of a job (the models load once), then exits (frees the ~5 GB of RAM).

    python run_sfx.py job.json    job = {"items": [{"video": <24 fps, 8 s mp4>, "text": "...", "out": <wav>}]}

Prints "PROGRESS: i/n" lines and a final "RESULT: {...}" line (read by app/sfx.py).
Local changes to the Woosh code: see NOTICE-LocalAI.txt."""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.update(HF_HOME=str(ROOT / "home"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
os.chdir(ROOT)  # the checkpoints name each other as checkpoints/<name>
sys.path.insert(0, str(ROOT / "Woosh"))

import torch  # noqa: E402
import torchaudio  # noqa: E402

torch.set_num_threads(max(2, (os.cpu_count() or 4) - 2))  # leave the app and the chat some CPU

import woosh.utils.synchformer as wsync  # noqa: E402
import woosh.utils.video as wvideo  # noqa: E402
import woosh.module.audioretrieval_module as wtext  # noqa: E402
from transformers import AutoConfig, RobertaModel  # noqa: E402

# Synchformer's weights and Motionformer's .yaml configs are in checkpoints/ (never downloaded at run time)
wvideo.hf_hub_download = wsync.hf_hub_download = lambda *a, **k: str(ROOT / "checkpoints" / "synchformer_state_dict.pth")


class _ConfigOnly(RobertaModel):
    """roberta-large built from its config only: Woosh's TextConditioner checkpoint holds the real weights
    (saves a 1.4 GB download of weights that would be replaced anyway)."""
    @classmethod
    def from_pretrained(cls, name, *args, **kw):
        pool = kw.pop("add_pooling_layer", True)
        return RobertaModel(AutoConfig.from_pretrained(name, **kw), add_pooling_layer=pool)


wtext.RobertaModel = _ConfigOnly

from woosh.components.base import LoadConfig  # noqa: E402
from woosh.inference.flowmap_sampler import sample_euler  # noqa: E402
from woosh.model.flowmap_from_pretrained import FlowMapFromPretrained  # noqa: E402
from woosh.utils.video import SynchformerProcessor  # noqa: E402
from woosh.utils.videoio import extract_video_frames  # noqa: E402


def main() -> None:
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    items = job["items"]
    t0 = time.time()
    print("PROGRESS: loading", flush=True)
    ldm = FlowMapFromPretrained(LoadConfig(path="checkpoints/Woosh-DVFlow-8s")).eval()
    feats = SynchformerProcessor(frame_rate=24).eval()
    loaded = time.time() - t0
    for i, it in enumerate(items):
        print(f"PROGRESS: {i + 1}/{len(items)}", flush=True)
        g = torch.Generator().manual_seed(int(it.get("seed") or 1234 + i))
        with torch.inference_mode():
            frames, rate, _ = extract_video_frames(it["video"], start_time=0, end_time=8)
            f = feats(frames, rate)
            cond = ldm.get_cond({"audio": None, "description": [it.get("text") or ""], "synch_out": f["synch_out"]},
                                no_dropout=True, device="cpu")
            x = sample_euler(model=ldm, noise=torch.randn(1, 128, 801, generator=g), cond=cond, num_steps=4,
                             renoise=[0, 0.5, 0.5, 0.3], cfg=float(it.get("cfg") or 3.0))
            audio = ldm.autoencoder.inverse(x).cpu()[0]
        audio = audio / max(1.0, float(audio.abs().max()))
        torchaudio.save(it["out"], audio, 48000, encoding="PCM_S", bits_per_sample=16)
    print("RESULT: " + json.dumps({"ok": len(items), "load_s": round(loaded, 1), "total_s": round(time.time() - t0, 1)}),
          flush=True)


if __name__ == "__main__":
    main()
