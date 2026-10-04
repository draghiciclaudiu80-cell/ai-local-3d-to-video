"""Image/video rendering with stable-diffusion.cpp, one job at a time (the iGPU can't do two).
The queue and movies are saved to disk, so a restart or crash resumes where it stopped."""
import json
import random
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from . import db, wipe
from .config import DATA, ENGINES, LOGS, MEDIA, NO_WINDOW, SOUNDS
from .models import active_path, find_file, image_parts, video_parts
from .plat import exe, lib_env, memory_gb, spawn

STYLES = {
    "None": "",
    "Photo": "photorealistic, 35mm photo, natural light, sharp focus, high detail",
    "Cinematic": "cinematic still, dramatic lighting, anamorphic, film grain, color graded",
    "Anime": "anime style, cel shading, vibrant colors, clean line art",
    "Illustration": "digital illustration, detailed, vibrant, artstation",
    "Oil painting": "oil painting, visible brush strokes, rich texture",
    "3D render": "3D render, soft global illumination, studio lighting",
    "Sketch": "pencil sketch, graphite, cross-hatching, on paper",
    "Neon": "neon lights, cyberpunk, glowing, night, high contrast",
    "Fantasy": "epic fantasy illustration, painterly, magical atmosphere",
    "Portrait": "studio portrait, softbox lighting, shallow depth of field, 85mm",
    "Pixel art": "pixel art, 16-bit, crisp pixels, limited palette",
}
# Share of the progress bar per phase. Measured on a Radeon 780M: for video, decoding (~90 s) takes far
# longer than sampling (~18 s), so it gets most of the bar.
SPANS = {"video": {"load": (0, .1), "sample": (.1, .3), "decode": (.3, .97), "save": (.97, 1)},
         "image": {"load": (0, .15), "sample": (.15, .85), "decode": (.85, .97), "save": (.97, 1)}}
STEP_RE = re.compile(r"\|\s*(\d+)/(\d+)")
# Wan 2.1's own recommended negative prompt (English version, the "style / painting" words left out so styles still
# work) — was "blurry, distorted, low quality, static": faces and hands came out mangled more often
NEGATIVE_VIDEO = ("overexposed, static, still picture, blurred details, subtitles, text, watermark, overall gray, worst "
                  "quality, low quality, JPEG artifacts, ugly, incomplete, extra fingers, poorly drawn hands, poorly "
                  "drawn faces, deformed, disfigured, misshapen limbs, fused fingers, messy background, three legs, "
                  "walking backwards, nudity")


def frames_for(seconds: float) -> int:
    """Wan renders at 16 fps and needs 4n+1 frames."""
    n = int(max(1, min(5, float(seconds or 2))) * 16) + 1
    return max(5, (n - 1) // 4 * 4 + 1)


def free_ram_gb() -> float:
    return memory_gb()[1]  # Windows: GlobalMemoryStatusEx · Linux: /proc/meminfo (app/plat.py)


def live_progress(job: dict) -> float:
    """Decoding prints no step counter: estimate from time (~5x sampling for video). Never goes backwards."""
    p = job.get("progress", 0.0)
    if job.get("status") == "running" and job.get("phase_key") == "decode":
        lo, hi = SPANS[job["kind"]]["decode"]
        expected = max(15.0, job.get("sample_secs", 20.0) * (5 if job["kind"] == "video" else 1))
        p = max(p, lo + (hi - lo) * min(0.95, (time.time() - job["phase_start"]) / expected))
    return p


class Renderer:
    STATE = DATA / "jobs.json"

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.queue: list[str] = []
        self.cv = threading.Condition()
        self.before_run = None  # set by the server: lets a chat finish, then frees the GPU
        self.after_all = None   # set by the server: the queue is empty again -> load the chat model back
        self._started = False
        self._load()

    def start(self) -> None:
        """Starts rendering — called by the server once its hooks are set. Importing the app (tools/check.py, test
        scripts) must never render: the worker used to start at import, so check.py run during a render re-queued
        the running job in its own process (a second sd-cli on the same clip, no GPU hand-over) and saved jobs.json."""
        if not self._started:
            self._started = True
            threading.Thread(target=self._worker, daemon=True).start()

    # ---------- building jobs
    def image_args(self, prompt: str, style: str = "None", width: int = 0, height: int = 0, seed: int = -1,
                   init: str | None = None, strength: float = 0.6) -> list[str]:
        model = active_path("image")
        if not model:
            raise FileNotFoundError("No image model yet — get one in Models › Image")
        parts, problem = image_parts(model)
        if problem:
            raise FileNotFoundError(problem)
        size = parts["size"]
        full = f"{prompt}, {STYLES.get(style, '')}".strip(", ")
        start = []
        if init:  # "start from the front picture": fitted to the picture size first (the engine needs the same size)
            from PIL import Image, ImageOps
            ImageOps.fit(Image.open(init).convert("RGB"), (width or size, height or size)).save(init)
            start = ["-i", init, "--strength", f"{min(max(strength, 0.2), 0.95):.2f}"]
        return [*parts["args"], "-p", full, "--cfg-scale", str(parts["cfg"]), "--sampling-method",
                parts.get("sampler", "euler"), "--steps", str(parts["steps"]), "-W", str(width or size),
                "-H", str(height or size), "-s", str(seed), *start, "--vae-tiling", "--diffusion-fa"]

    def video_args(self, prompt: str, seconds: float = 2, width: int = 480, height: int = 272, seed: int = -1) -> list[str]:
        model = active_path("video")
        if not model:
            raise FileNotFoundError("No video model yet — get one in Models › Video")
        parts, problem = video_parts(model)
        if problem:
            raise FileNotFoundError(problem)
        if seed < 0:  # a known seed (in the job's args): the next shot of a chain reuses it
            seed = random.randint(1, 2**31 - 1)
        return ["-M", "vid_gen", *parts["args"], "-p", prompt, "-n", NEGATIVE_VIDEO,
                "--cfg-scale", str(parts["cfg"]), "--sampling-method", "euler", "--steps", str(parts["steps"]),
                "--flow-shift", "3.0", "-W", str(width), "-H", str(height), "--video-frames",
                str(frames_for(seconds)), "--fps", "16", "-s", str(seed), *video_decoder(parts), "--diffusion-fa"]

    def submit(self, kind: str, args: list[str], prompt: str, movie: str | None = None, temp: list[str] | None = None) -> str:
        jid = uuid.uuid4().hex[:12]
        out = MEDIA / f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}-{jid}.{'png' if kind == 'image' else 'webm'}"
        job = {"id": jid, "kind": kind, "prompt": prompt, "status": "queued", "progress": 0.0, "file": out.name,
               "args": args + ["-o", str(out)], "error": None, "created": time.time(), "movie": movie,
               **({"temp": temp} if temp else {})}  # files wiped when the job ends (your reference picture)
        with self.cv:
            self.jobs[jid] = job
            self.queue.append(jid)
            self._save()
            self.cv.notify()
        return jid

    def cancel(self, jid: str) -> None:
        """The 'cancel' flag is never overwritten by the worker, so a cancel can't be lost in a race."""
        with self.cv:
            job = self.jobs.get(jid)
            if not job:
                return
            job["cancel"], job["status"] = True, "cancelled"
            if jid in self.queue:
                self.queue.remove(jid)
            proc = job.get("proc")
            self._save()
        if proc:
            proc.kill()

    def forget(self, jid: str) -> None:
        with self.cv:
            self.jobs.pop(jid, None)
            self._save()

    def busy(self) -> bool:
        return any(j["status"] in ("queued", "running") for j in self.jobs.values())

    def rendering(self) -> bool:
        """A picture / clip being made or waiting (sd-cli, GPU + lots of RAM) — joins don't count: the sound step of
        a join waited 20 minutes for ITSELF with busy()."""
        return any(j["status"] in ("queued", "running") and not j.get("join") for j in self.jobs.values())

    def public(self, job: dict) -> dict:
        j = {k: v for k, v in job.items() if k not in ("args", "proc")}
        j["progress"] = live_progress(job)
        if job.get("status") == "running" and job.get("phase_key") == "decode" and                 time.time() - job.get("phase_start", time.time()) > 300 and not job.get("note"):
            # Seen on a 16 GB iGPU PC: with memory full, decoding went from 2 to 27 minutes.
            j["note"] = "Decoding is slow because memory is full — closing other apps (browser, games) speeds it up"
        if job.get("started"):
            j["elapsed"] = round((job.get("ended") or time.time()) - job["started"])
            if job["status"] == "running" and j["progress"] > 0.1:
                j["eta"] = round(j["elapsed"] * (1 - j["progress"]) / j["progress"])
        return j

    # ---------- persistence
    def _save(self) -> None:
        keep = {k: {f: v for f, v in j.items() if f != "proc"} for k, j in self.jobs.items()}
        tmp = self.STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"jobs": keep, "queue": self.queue}), encoding="utf-8")
        tmp.replace(self.STATE)

    def _load(self) -> None:
        try:
            state = json.loads(self.STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.jobs = state.get("jobs", {})
        for j in sorted(self.jobs.values(), key=lambda j: j["created"]):
            if j.get("join") and j["status"] in ("queued", "running"):  # a join isn't a render: ask again after a restart
                j.update(status="error", error="The app restarted before the videos were joined — ask again")
                continue
            if j["status"] in ("queued", "running") and not j.get("cancel"):
                j.update(status="queued", progress=0.0, phase=None)
                j.pop("started", None)
                self.queue.append(j["id"])

    # ---------- running
    def _run_once(self, job: dict, args: list[str]) -> tuple[bool, list[str]]:
        with self.cv:
            if job.get("cancel"):
                return False, []
            p = spawn([str(exe(ENGINES / "sd", "sd-cli")), *args], stdout=subprocess.PIPE, env=lib_env(ENGINES / "sd"),
                                 stderr=subprocess.STDOUT, creationflags=NO_WINDOW, text=True, errors="ignore")
            job["proc"] = p
        spans = SPANS[job["kind"]]
        labels = {"load": "Loading the model", "sample": "Generating",
                  "decode": "Decoding frames (longest part)" if job["kind"] == "video" else "Finishing the image",
                  "save": "Saving"}
        steps = int(args[args.index("--steps") + 1]) if "--steps" in args else 0
        phase, tail, buf = "load", [], ""
        job.update(phase=labels[phase], progress=0.0, phase_key=phase, phase_start=time.time())
        with open(LOGS / f"job-{job['id']}.log", "w", encoding="utf-8", errors="ignore", buffering=1) as log:
            while True:
                ch = p.stdout.read(1)
                if not ch:
                    break
                if ch not in "\r\n":
                    buf += ch
                    continue
                if not buf:
                    continue
                low = buf.lower()
                if "|" not in buf:  # a log line: phase changes are announced by these exact messages
                    log.write(buf + "\n")
                    tail = (tail + [buf])[-15:]
                    new = phase
                    if "get_learned_condition completed" in low and phase == "load":
                        new = "sample"
                    elif "sampling completed" in low and phase in ("load", "sample"):
                        new = "decode"
                        job["sample_secs"] = time.time() - job["phase_start"]
                    elif "decode_first_stage completed" in low or "save result" in low:
                        new = "save"
                    if new != phase:
                        phase = new
                        job.update(phase_key=phase, phase_start=time.time())
                    job["phase"] = labels[phase]
                    job["progress"] = max(job["progress"], spans[phase][0])
                m = STEP_RE.search(buf)
                # Only real sampling steps count: loading bars and VAE tile bars (which restart when memory
                # runs out) would make the bar jump.
                if m and (phase == "decode" or (phase == "sample" and int(m.group(2)) != steps)):
                    m = None
                if m and int(m.group(2)):
                    n, total = int(m.group(1)), int(m.group(2))
                    lo, hi = spans[phase]
                    job["progress"] = max(job["progress"], lo + (hi - lo) * n / total)
                    job["phase"] = f"Generating — step {n} of {total}" if phase == "sample" else labels[phase]
                buf = ""
        p.wait()
        return p.returncode == 0 and (MEDIA / job["file"]).exists(), tail

    def _worker(self) -> None:
        while True:
            with self.cv:
                while not self.queue:
                    self.cv.wait()
                jid = self.queue.pop(0)
                job = self.jobs.get(jid)
                if not job or job.get("cancel"):
                    continue
                job["status"], job["started"] = "running", time.time()
                self._save()
            try:
                if self.before_run:
                    self.before_run()
                if job.get("cancel"):
                    continue
                if free_ram_gb() < 2.5:
                    job["note"] = f"Low memory ({free_ram_gb():.1f} GB free) — close other apps to speed this up"
                ok, tail = self._run_once(job, job["args"])
                if not ok and not job.get("cancel") and "alloc" in "\n".join(tail).lower() and "vae" not in "\n".join(tail).lower():
                    # The graphics memory of a model closed a moment ago wasn't given back yet (picture-reading model
                    # right before a render): wait a little and try once more.
                    job["note"] = "Graphics memory was still busy — trying again"
                    time.sleep(6)
                    ok, tail = self._run_once(job, job["args"])
                if not ok and not job.get("cancel") and "vae" in "\n".join(tail).lower():
                    # Out of GPU memory at the final decode: redo it with the decoder on the CPU (slower, safe).
                    job["note"] = "GPU memory was full — retrying with the decoder on the CPU"
                    ok, tail = self._run_once(job, job["args"] + ["--backend", "vae=cpu"])
                if job.get("cancel"):
                    job["status"] = "cancelled"
                elif ok:
                    job["status"], job["progress"] = "done", 1.0
                    db.add_gallery(jid, job["kind"] if not job.get("movie") else "clip", job["file"], job["prompt"])
                else:
                    job["status"], job["error"] = "error", "\n".join(tail[-6:]) or "The renderer stopped"
            except Exception as e:  # noqa: BLE001 — shown in the queue
                job["status"], job["error"] = "error", str(e)
            finally:
                job.pop("proc", None)
                for f in job.pop("temp", None) or []:
                    wipe.shred(f)
                job["ended"] = time.time()
                with self.cv:
                    self._save()
                    idle = not self.queue
                if idle and self.after_all:
                    self.after_all()


def video_decoder(parts: dict) -> list[str]:
    """Turning the finished video into frames was ~75% of a clip's time (and ran out of GPU memory, then crawled
    in tiny tiles). Wan 2.1's tiny decoder (taew2_1, 22 MB) does it in ~6 s instead of ~175 s with the same look
    (tested side by side); without it, direct convolutions + frame-by-frame tiling still halve the time."""
    tae = find_file("taew2_1.safetensors") if "wan_2.1_vae" in " ".join(parts["args"]) else None
    # direct convolutions matter most WITH the tiny decoder: without them its decode took 270 s instead of 6 s
    return ["--tae", str(tae), "--vae-conv-direct", "--temporal-tiling"] if tae else ["--vae-conv-direct", "--temporal-tiling"]


renderer = Renderer()


# ---------------------------------------------------------------- movies: scenes + narration + music
def _ffmpeg(*args: str) -> None:
    import imageio_ffmpeg
    r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-600:])


def _wav_secs(path: Path) -> float:
    import wave
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def _has_audio(path: Path) -> bool:
    import av
    try:
        with av.open(str(path)) as c:
            return bool(c.streams.audio)
    except Exception:  # noqa: BLE001 — unreadable: treat as silent
        return False


def stitch(files: list[Path], out: Path, narrations: list[Path | None] | None = None,
           music: Path | None = None, music_volume: float = 0.25, fade: float = 0.25,
           sounds: list[Path | None] | None = None) -> None:
    """Joins clips into one MP4 with sound — any length: each clip was made on its own, so the GPU never holds
    more than one. A clip's sound = its sound effects (sounds[i]) or its own sound track (joining finished movies
    used to lose theirs), with its narration on top (the last frame is held while the voice is longer); clips
    blend with a short cross-fade instead of a hard cut; optional music loops under everything."""
    import imageio.v3 as iio
    import imageio_ffmpeg
    w, h = iio.improps(files[0], plugin="pyav").shape[1:3][::-1]
    narrations = narrations or [None] * len(files)
    sounds = sounds or [None] * len(files)
    fmt = "aresample=44100,aformat=channel_layouts=stereo,apad"
    with tempfile.TemporaryDirectory() as tmp:
        scenes, durs = [], []
        for i, (f, nar, bg) in enumerate(zip(files, narrations, sounds)):
            vid = imageio_ffmpeg.count_frames_and_secs(str(f))[1]
            dur = max(vid, _wav_secs(nar) + 0.4) if nar else vid
            bed = str(bg) if bg else str(f) if _has_audio(f) else None  # the clip's own sound under the voice
            if bed and nar:
                audio = ["-i", bed, "-i", str(nar)]
                agraph = f"[1:a]{fmt},volume=0.45[b];[2:a]{fmt}[n];[b][n]amix=inputs=2:duration=longest:normalize=0[a]"
            else:
                audio = ["-i", str(nar)] if nar else ["-i", bed] if bed else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
                agraph = f"[1:a]{fmt}[a]"
            scene = Path(tmp) / f"s{i}.mp4"
            _ffmpeg("-i", str(f), *audio, "-filter_complex",
                    f"[0:v]scale={w}:{h},setsar=1,fps=16,tpad=stop_mode=clone:stop_duration={dur - vid:.2f}[v];" + agraph,
                    "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", str(scene))
            scenes.append(scene)
            durs.append(dur)
        n = len(scenes)
        inputs = [a for sc in scenes for a in ("-i", str(sc))]
        fade = min(fade, min(durs) / 3) if n > 1 else 0
        if fade > 0.05:  # cross-fade picture and sound from one clip into the next
            parts, v, a, off = [], "[0:v]", "[0:a]", 0.0
            for i in range(1, n):
                off += durs[i - 1] - fade
                parts += [f"{v}[{i}:v]xfade=transition=fade:duration={fade:.2f}:offset={off:.2f}[v{i}]",
                          f"{a}[{i}:a]acrossfade=d={fade:.2f}[a{i}]"]
                v, a = f"[v{i}]", f"[a{i}]"
            graph = ";".join(parts)
        else:
            graph = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
            v, a = "[v]", "[a]"
        if music:
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            graph += f";[{n}:a]volume={music_volume}[m];{a}[m]amix=inputs=2:duration=first:normalize=0[am]"
            a = "[am]"
        _ffmpeg(*inputs, "-filter_complex", graph, "-map", v, "-map", a,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac", str(out))


def wait_for_renders(cancelled=lambda: False, most: float = 1200) -> None:
    """The sound model needs ~5 GB of RAM: it waits until the picture/clip queue is empty (low RAM made a clip's
    decode crawl: 27 min instead of 2), at most 20 minutes."""
    t0 = time.time()
    while renderer.rendering() and time.time() - t0 < most and not cancelled():
        time.sleep(2)


def add_sound(job: dict, narration: str, music: bool = False, effects: str | None = None, status=lambda s: None) -> dict:
    """Sound on a finished clip -> a NEW MP4 in the Gallery (the original clip stays): sound effects that fit what
    is seen (effects = what they should be, "" = just what's seen; None = none), a narrator only when there are
    words, music when asked and there is some. The last frame is held while the voice is longer than the clip."""
    from . import sfx
    from .voice import voice as tts
    src = MEDIA / job["file"]
    if not src.exists():
        raise FileNotFoundError("That video isn't on this PC anymore")
    tracks = sorted(p for p in SOUNDS.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac")) \
        if music and SOUNDS.exists() else []
    bg, fx_problem = None, ""
    if effects is not None:
        if not sfx.ready():
            fx_problem = "the sound-effects model isn't installed"
        else:
            try:
                status("Waiting for the video queue to finish…" if renderer.rendering() else "Making the sound effects…")
                wait_for_renders()
                bg = sfx.make([(src, effects)], status=status)[0]
                with renderer.cv:  # remembered: joining clips later keeps them
                    job["effects"] = effects
                    renderer._save()
            except (RuntimeError, OSError) as e:
                fx_problem = str(e)[:200]
    nar = tts.speak(narration) if narration.strip() else None
    if not (nar or bg or tracks):
        return {"error": fx_problem or "there was no sound to add", "no_music": music and not tracks}
    out = MEDIA / f"{'narrated' if nar else 'sound'}-{time.strftime('%Y%m%d-%H%M%S')}-{job['id']}.mp4"
    try:
        stitch([src], out, [nar], random.choice(tracks) if tracks else None, sounds=[bg])
    finally:
        if nar:
            wipe.shred(nar)
        if bg:
            sfx.cleanup([bg])
    db.add_gallery(uuid.uuid4().hex[:12], "movie", out.name, (narration or effects or job["prompt"])[:80])
    if narration:
        with renderer.cv:  # remembered: joining clips later reuses the words
            job["narration"] = narration
            renderer._save()
    return {"clip": f"/media/{out.name}", "narration": narration, "effects": bool(bg), "effects_problem": fx_problem,
            "music": bool(tracks), "no_music": music and not tracks}


def join_clips(parts: list[str], title: str, effects: bool | str = False) -> str:
    """Joins a chat's clips (job ids, in order) into ONE video with each clip's narration (and sound effects made
    for each clip when effects is on: True = what's seen, a text = what they should be) — as a job, so the chat
    shows it with progress. Clips still being made are waited for ("make the next one, then merge them")."""
    jid = uuid.uuid4().hex[:12]
    out = MEDIA / f"joined-{time.strftime('%Y%m%d-%H%M%S')}-{jid}.mp4"
    job = {"id": jid, "kind": "video", "prompt": title, "status": "queued", "progress": 0.0, "file": out.name,
           "args": [], "error": None, "created": time.time(), "movie": None, "join": True, "parts": parts,
           "phase": "Waiting for the clips", **({"effects": effects} if effects else {})}
    with renderer.cv:
        renderer.jobs[jid] = job
        renderer._save()
    threading.Thread(target=_join_run, args=(job, parts, out), daemon=True).start()
    return jid


def _join_run(job: dict, parts: list[str], out: Path) -> None:
    from .voice import voice as tts
    temp: list[Path] = []
    try:
        while True:  # the newest clip may still be rendering
            states = [(renderer.jobs.get(p) or {}).get("status") for p in parts]
            if job.get("cancel"):
                job["status"] = "cancelled"
                return
            if any(st in ("error", "cancelled", None) for st in states):
                raise RuntimeError("a clip failed or was removed, so there's nothing to join")
            if all(st == "done" for st in states):
                break
            time.sleep(2)
        job.update(status="running", phase="Joining the clips", started=time.time(), progress=0.5)
        files = [MEDIA / renderer.jobs[p]["file"] for p in parts]
        sounds: list[Path | None] = [None] * len(parts)
        if job.get("effects"):  # sound effects made for each clip (the model watches it)
            from . import sfx
            if not sfx.ready():
                job["note"] = "no sound effects: the sound-effects model isn't installed"
            else:
                def phase(s: str) -> None:
                    job.update(phase=s, progress=max(job.get("progress", 0.5), 0.55))
                phase("Waiting for other renders to finish…")
                wait_for_renders(lambda: bool(job.get("cancel")))
                what = job["effects"] if isinstance(job["effects"], str) else ""
                try:
                    sounds = list(sfx.make([(f, renderer.jobs[p].get("effects") or what) for f, p in zip(files, parts)],
                                           cancelled=lambda: bool(job.get("cancel")), status=phase))
                    temp.extend(s for s in sounds if s)
                except (RuntimeError, OSError) as e:
                    if job.get("cancel"):
                        job["status"] = "cancelled"
                        return
                    job["note"] = f"no sound effects: {str(e)[:160]}"
                job.update(phase="Joining the clips with sound", progress=0.9)
        narr = []
        for p in parts:
            line = renderer.jobs[p].get("narration")
            narr.append(tts.speak(line) if line else None)
            if narr[-1]:
                temp.append(narr[-1])
        stitch(files, out, narr, sounds=sounds)
        db.add_gallery(job["id"], "movie", out.name, job["prompt"])
        job["status"], job["progress"] = "done", 1.0
    except Exception as e:  # noqa: BLE001 — shown in the chat
        job["status"], job["error"] = "error", str(e)[:300]
    finally:
        for f in temp:
            wipe.shred(f)
        for d in {f.parent for f in temp if f.parent.name.startswith("sfx-")}:  # the sound step's own folder
            try:
                d.rmdir()
            except OSError:
                pass
        job["ended"] = time.time()
        with renderer.cv:
            renderer._save()


MOVIES_STATE = DATA / "movies.json"
movies: dict[str, dict] = {}


def save_movies() -> None:
    tmp = MOVIES_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(movies), encoding="utf-8")
    tmp.replace(MOVIES_STATE)


MAX_SCENES = 30


def stop_movie(mid: str) -> None:
    """The Stop button: every scene still waiting or rendering is cancelled and the movie leaves the list, so the
    queue stays clean. Scenes already made stay (Gallery)."""
    mv = movies.pop(mid)
    mv["stopped"] = True
    for jid in mv["jobs"]:
        j = renderer.jobs.get(jid)
        if j and j["status"] in ("queued", "running"):
            renderer.cancel(jid)
            renderer.forget(jid)
    save_movies()


def stop_all() -> int:
    """The "Stop everything" button: every movie being made, every waiting or running render and merge."""
    for mid, mv in list(movies.items()):
        if mv["status"] != "done":  # being made -> stopped; stopped / failed ones -> off the list too
            stop_movie(mid)
    active = [jid for jid, j in list(renderer.jobs.items()) if j["status"] in ("queued", "running")]
    for jid in active:
        renderer.cancel(jid)
    for jid, j in list(renderer.jobs.items()):  # nothing cancelled stays on the list
        if j["status"] == "cancelled":
            renderer.forget(jid)
    return len(active)


def make_movie(title: str, look: str, scenes: list[dict], seconds: float = 2, voice: str | None = None,
               music: str | None = None, music_volume: float = 0.25, width: int = 480, height: int = 272) -> dict:
    """scenes: [{"visual": ..., "narration": ...}]. One seed and one look description for every scene keeps
    characters consistent; renders run in the background and join into one MP4 at the end."""
    scenes = [s for s in scenes if (s.get("visual") or "").strip()]
    if not scenes:
        raise ValueError("Add at least one scene")
    if len(scenes) > MAX_SCENES:  # a pasted text once became a 192-scene movie (hours of rendering)
        raise ValueError(f"That's {len(scenes)} scenes (about {round(len(scenes) * (seconds * 0.5 + 0.3))} minutes of "
                         f"rendering) — at most {MAX_SCENES} per movie. One line = one scene.")
    mid, seed = uuid.uuid4().hex[:12], random.randint(0, 2**31 - 1)
    ids = []
    for s in scenes:
        prompt = f"{look.strip()}. {s['visual'].strip()}" if look.strip() else s["visual"].strip()
        ids.append(renderer.submit("video", renderer.video_args(prompt, seconds, width, height, seed), prompt, mid))
    movies[mid] = {"id": mid, "title": title or "Movie", "status": "rendering", "scenes": len(ids), "done_scenes": 0,
                   "jobs": ids, "file": None, "error": None, "created": time.time(), "seed": seed,
                   "narration": [(s.get("narration") or "").strip() for s in scenes], "voice": voice,
                   "music": music, "music_volume": music_volume}
    save_movies()
    threading.Thread(target=_watch_movie, args=(mid,), daemon=True).start()
    return movies[mid]


def _watch_movie(mid: str) -> None:
    from .voice import voice as tts
    mv = movies[mid]
    while True:
        if mv.get("stopped"):
            return
        states = [renderer.jobs.get(j, {}).get("status", "cancelled") for j in mv["jobs"]]
        if states.count("done") != mv["done_scenes"]:
            mv["done_scenes"] = states.count("done")
            save_movies()
        if any(s in ("error", "cancelled") for s in states):
            mv["status"], mv["error"] = "error", "A scene failed or was cancelled — see the queue"
            save_movies()
            return
        if all(s == "done" for s in states):
            break
        time.sleep(2)
    mv["status"] = "adding sound"
    save_movies()
    temp: list[Path] = []
    try:
        narr = []
        for line in mv["narration"]:
            narr.append(tts.speak(line, mv["voice"]) if line else None)
            if narr[-1]:
                temp.append(narr[-1])
        music = SOUNDS / Path(mv["music"]).name if mv.get("music") else None
        out = MEDIA / f"movie-{time.strftime('%Y%m%d-%H%M%S')}-{mid}.mp4"
        stitch([MEDIA / renderer.jobs[j]["file"] for j in mv["jobs"]], out, narr,
               music if music and music.exists() else None, mv.get("music_volume", 0.25))
        db.add_gallery(mid, "movie", out.name, mv["title"])
        mv["status"], mv["file"] = "done", out.name
    except Exception as e:  # noqa: BLE001
        mv["status"], mv["error"] = "error", str(e)[:300]
    finally:
        for f in temp:
            wipe.shred(f)
        save_movies()


def movie_list() -> list[dict]:
    out = []
    for m in sorted(movies.values(), key=lambda m: -m["created"]):
        m = dict(m)
        p = [live_progress(renderer.jobs[j]) if j in renderer.jobs else 0 for j in m["jobs"]]
        m["progress"] = 1.0 if m["status"] == "done" else round(sum(p) / max(1, len(p)) * 0.97, 3)
        out.append(m)
    return out


def resume_movies() -> None:
    try:
        movies.update(json.loads(MOVIES_STATE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return
    for mid, mv in movies.items():
        if mv["status"] in ("rendering", "adding sound"):
            mv["status"] = "rendering"
            threading.Thread(target=_watch_movie, args=(mid,), daemon=True).start()
