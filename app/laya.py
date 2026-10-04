"""The REAL Laya (Convai Innovations, Apache 2.0): a 421M / 322M decision model — System 1. It never writes text: it
reads a situation and answers typed questions (pick one option, a score, yes / no) with calibrated probabilities and a
confidence, in a fraction of a second on the processor. The chat model (System 2) thinks and writes; Laya decides;
computer use and the plugins are the hands. When Laya isn't sure, the decision goes up to the chat model, or the user
is asked with buttons (see agent.decide).

It runs in its own Python (engines/laya/venv: CPU PyTorch + the laya package) as a small server on 127.0.0.1:8776
(engines/laya/server.py), started when first needed, stopped after 10 idle minutes. Models: models/laya-real/
typed-decisions (English, fine-tuned for typed decisions) and multilingual (Romanian and 100+ languages)."""
import asyncio
import os
import subprocess
import time

import httpx

from .config import ENGINES, LOGS, MODELS, NO_WINDOW
from .plat import kill_tree, venv_python

PORT = 8776
PY = venv_python(ENGINES / "laya" / "venv")
SERVER = ENGINES / "laya" / "server.py"
WEIGHTS = MODELS / "laya-real"


class Laya:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{PORT}"
        self.lock = asyncio.Lock()
        self.last = 0.0

    def available(self) -> bool:
        return PY.exists() and SERVER.exists() and bool(checkpoints())

    def chosen(self) -> str:
        """The Laya checkpoint in use (Models page): the user's pick, else typed-decisions (tested best)."""
        from .config import load_settings
        names = [c["name"] for c in checkpoints()]
        pick = load_settings().get("laya_model")
        return pick if pick in names else ("typed-decisions" if "typed-decisions" in names else (names[0] if names else ""))

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def ensure(self) -> bool:
        if not self.available():
            return False
        async with self.lock:
            if self.running():
                return True
            self.last = time.time()  # the idle clock starts now (it stopped Laya a minute after the app started)
            await self._clear_port()
            log = open(LOGS / "laya.log", "w", encoding="utf-8", errors="ignore")
            self.proc = subprocess.Popen([str(PY), str(SERVER), str(WEIGHTS), str(PORT)], stdout=log,
                                         stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                                         env={**self.env(), "LAYA_PRELOAD": self.chosen() or "1"})
            proc = self.proc
            for _ in range(240):  # loading the model: ~5-20 s the first time
                if self.proc is not proc or proc.poll() is not None:  # it ended, or Stop was pressed meanwhile
                    if self.proc is proc:
                        self.proc = None
                    return False
                try:
                    async with httpx.AsyncClient(timeout=2) as c:
                        if (await c.get(f"{self.url}/health")).status_code == 200:
                            return True
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
            return False

    @staticmethod
    def env() -> dict:
        """A small, closed world: no network, Hugging Face files kept inside engines/laya (not in the user profile)."""
        home = ENGINES / "laya" / "home"
        home.mkdir(exist_ok=True)
        keep = {k: os.environ[k] for k in ("SYSTEMROOT", "SYSTEMDRIVE", "TEMP", "TMP", "NUMBER_OF_PROCESSORS")
                if k in os.environ}
        return {**keep, "PATH": "", "USERPROFILE": str(home), "HOME": str(home), "HF_HOME": str(home / "hf"),
                "LAYA_PRELOAD": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
                "PYTHONIOENCODING": "utf-8"}

    async def ask(self, state: str, name: str, instructions: str, criteria: dict[str, str], lang: str = "en") -> dict:
        """One choice question -> {"probs": {option: p}, "choice", "confidence", "sure" (P of the answer), "model", "ms"}."""
        # "en" = the typed-decisions checkpoint for every message: tested on Romanian too, the multilingual checkpoint was
        # confidently WRONG ("fă un clip cu un câine" -> 3D design, 72%) while the English one just stays unsure -> the
        # chat model decides. lang="auto" still picks multilingual for clearly Romanian text.
        if not await self.ensure():
            raise httpx.HTTPError("Laya isn't available")
        self.last = time.time()
        from .config import load_settings
        pick = load_settings().get("laya_model")  # the user's chosen checkpoint answers everything; else by language
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(f"{self.url}/decide", json={"state": state, "lang": lang, "questions": {
                name: {"type": "choice", "instructions": instructions, "criteria": criteria}},
                **({"model": self.chosen()} if pick else {})})
        out = r.json()
        if r.status_code != 200 or "answers" not in out:
            raise httpx.HTTPError(out.get("error", "Laya failed"))
        a = out["answers"][name]
        probs = {k: float(v) for k, v in (a.get("probabilities") or {}).items()}
        return {"probs": probs, "choice": a.get("choice"), "confidence": float(a.get("confidence") or 0),
                "sure": float(a.get("answer_confidence") or max(probs.values(), default=0)), "model": out.get("model"),
                "ms": out.get("ms")}

    @staticmethod
    def _kill_tree(pid: int) -> None:
        # the venv's python.exe is only a launcher: terminate() killed it and left the real Laya running (~1.5 GB)
        kill_tree(pid)

    async def _clear_port(self) -> None:
        """A Laya server left over (the app crashed / was killed) holds the port: stop it, so the one we start is ours."""
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                pid = (await c.get(f"{self.url}/health")).json().get("pid")
        except (httpx.HTTPError, ValueError, AttributeError):
            return
        if pid:
            self._kill_tree(int(pid))
            await asyncio.sleep(1)

    def stop(self) -> None:
        if self.running():
            self._kill_tree(self.proc.pid)
        self.proc = None

    async def idle_loop(self) -> None:
        """Frees its ~1-2 GB of RAM after 10 minutes without a decision."""
        while True:
            await asyncio.sleep(60)
            if self.running() and time.time() - self.last > 600:
                self.stop()


def checkpoints() -> list[dict]:
    """Laya models on this PC: every folder in models/laya-real with weights + its config (new ones appear here)."""
    import json as _json
    out = []
    if not WEIGHTS.exists():
        return out
    for d in sorted(WEIGHTS.iterdir()):
        if not d.is_dir() or not any((d / f).exists() for f in ("model.safetensors", "pytorch_model.bin")):
            continue
        cfg = {}
        for f in d.glob("*config*.json"):
            try:
                cfg = _json.loads(f.read_text(encoding="utf-8"))
                break
            except (OSError, ValueError):
                pass
        size = sum(x.stat().st_size for x in d.rglob("*") if x.is_file())
        out.append({"name": d.name, "label": cfg.get("model_name") or d.name, "encoder": cfg.get("encoder"),
                    "size": size, "multilingual": "multiling" in d.name.lower() or "xlm" in str(cfg.get("encoder", "")).lower()})
    return out


laya = Laya()
