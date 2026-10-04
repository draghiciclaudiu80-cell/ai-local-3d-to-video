"""The bundled llama.cpp server: loads one text/vision model at a time, on the GPU or (while a video
renders) on the CPU so the two never fight over the iGPU's memory."""
import asyncio
import math
import secrets
import subprocess
import threading
from pathlib import Path

import httpx

from .config import ENGINES, LLM_PORT, LOGS, MODELS, NO_WINDOW
from .plat import exe, lib_env, spawn
from .models import projector_for

# The app's llama-servers answer only requests that carry this key (new every run). They allow EVERY website
# (CORS reflects any Origin - tested), so without it any page open in the user's browser could use the models.
ENGINE_KEY = secrets.token_urlsafe(24)
AUTH = {"Authorization": f"Bearer {ENGINE_KEY}"}


class LLM:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.model: str | None = None
        self.gpu = True
        self.vision = False
        self.native_tools = True
        self.busy = 0  # chats streaming right now — renders wait for them before unloading
        self.lock = asyncio.Lock()
        self.plock = threading.Lock()  # the render thread may unload the model while a chat loads one
        self.url = f"http://127.0.0.1:{LLM_PORT}"

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def ensure(self, model: str, ctx: int = 8192, gpu: bool = True) -> None:
        async with self.lock:
            if self.running() and self.model == model and self.gpu == gpu:
                return
            self.stop()
            proj = projector_for(Path(model))
            args = [str(exe(ENGINES / "llama", "llama-server")), "-m", model, "--host", "127.0.0.1",
                    "--port", str(LLM_PORT), "-c", str(ctx), "--jinja",
                    "--cache-ram", "1024",  # saved conversations in RAM: 1 GB, not the default 8 GB (16 GB PC)
                    "--api-key", ENGINE_KEY]
            if proj:
                args += ["--mmproj", str(proj)]
                if "qwen" in Path(model).name.lower() and "vl" in Path(model).name.lower():
                    args += ["--image-min-tokens", "1024"]  # llama.cpp: Qwen-VL points (clicks) accurately from 1024
            # -ngl 0 alone still pushes work to Vulkan; "--device none" keeps CPU mode truly off the GPU.
            args += ["-ngl", "99"] if gpu else ["-ngl", "0", "--device", "none", "--no-op-offload"]
            # Measured on the Legion Go (Z1 Extreme, Vulkan), Llama 8B: 8-bit conversation memory = ~5% faster answers
            # in long chats and ~0.5 GB less memory; bigger reading batch = ~10% faster reading. A small "draft" model
            # (speculative decoding) was SLOWER here (16 -> 13 tokens/s): big and small model share the same memory.
            args += ["-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "-ub", "1024"]
            log = open(LOGS / "llm.log", "w", encoding="utf-8", errors="ignore")
            with self.plock:
                proc = spawn(args, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                                        env=lib_env(ENGINES / "llama"))
                self.proc, self.model, self.gpu, self.vision = proc, model, gpu, bool(proj)
            async with httpx.AsyncClient(timeout=2, headers=AUTH) as c:
                for _ in range(240):
                    if proc.poll() is not None:
                        if self.proc is not proc:
                            raise RuntimeError("The model was unloaded to make room for a render — send again")
                        raise RuntimeError("The model failed to start — see data/logs/llm.log")
                    try:
                        if (await c.get(f"{self.url}/health")).status_code == 200:
                            tpl = (await c.get(f"{self.url}/props")).json().get("chat_template", "")
                            self.native_tools = "tool_call" in tpl or "tools" in tpl
                            return
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(1)
            raise RuntimeError("The model took too long to load")

    def stop(self, only_gpu: bool = False) -> None:
        """only_gpu: used by renders — a model running on the CPU doesn't compete with them, so it stays."""
        with self.plock:
            proc = self.proc
            if proc is None or (only_gpu and not self.gpu):
                return
            self.proc, self.model = None, None
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()

    async def decide(self, prompt: str | tuple[str, str], labels: list[str]) -> dict[str, float]:
        return await decide_at(self.url, prompt, labels)

    async def complete(self, messages: list[dict], **extra) -> dict:
        async with httpx.AsyncClient(timeout=900, headers=AUTH) as c:
            r = await c.post(f"{self.url}/v1/chat/completions", json={"messages": messages, **extra})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]


async def decide_at(url: str, prompt: str | tuple[str, str], labels: list[str]) -> dict[str, float]:
    """Decision mode: the model answers with ONE of the labels, decided in one step (~0.3 s instead of ~3.5 s for a
    written answer), and says how sure it is of each label. Words ("draw", "film"…) instead of letters: small models
    choose letters with a strong bias. prompt = text, or (the fixed instructions, the new part): the fixed part goes in
    its own message so the engine keeps it — hybrid models (Qwen 3.5, Bonsai) only re-use what lies before the LAST user
    message: as one message the 700-token routing question was read again every time (10 s on Bonsai 27B)."""
    one = [{"role": "user", "content": "".join(prompt) if isinstance(prompt, tuple) else prompt}]
    tries = ([{"role": "system", "content": prompt[0]}, {"role": "user", "content": prompt[1]}], one) \
        if isinstance(prompt, tuple) else (one,)
    async with httpx.AsyncClient(timeout=120, headers=AUTH) as c:
        for msgs in tries:  # a template without a system role (Gemma) -> one message
            r = await c.post(f"{url}/v1/chat/completions", json={
                "messages": msgs, "temperature": 0, "max_tokens": 1,
                "chat_template_kwargs": {"enable_thinking": False}, "logprobs": True, "top_logprobs": 20,
                "grammar": "root ::= " + " | ".join(f'"{x}"' for x in labels)})
            if r.status_code < 400:
                break
        r.raise_for_status()
        top = r.json()["choices"][0]["logprobs"]["content"][0]["top_logprobs"]
    out = dict.fromkeys(labels, 0.0)
    for t in top:  # the first piece of a word: give it to the label(s) it starts
        tok = t["token"].strip().lower()
        owners = [x for x in labels if tok and x.startswith(tok)]
        for x in owners:
            out[x] += math.exp(t["logprob"]) / len(owners)
    total = sum(out.values()) or 1.0
    return {k: v / total for k, v in out.items()}


class SmallModel:
    """A small chat model on the PROCESSOR (Qwen3 1.7B, ~1.3 GB RAM): writes short things when asked — the "Small
    model" designer in Create › 3D, and (loaded in the main slot) "Small model only" chat. It used to be called
    "Laya"; the real Laya is a decision model and lives in app/laya.py."""
    PORT = LLM_PORT + 1
    FILE = "Qwen3-1.7B-Q4_K_M.gguf"

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.url = f"http://127.0.0.1:{self.PORT}"
        self.lock = asyncio.Lock()

    def model(self) -> Path | None:
        """The small model the user picked (Models page) — or the default Qwen3 1.7B."""
        from .config import load_settings
        chosen = load_settings().get("small_model")
        if chosen and Path(chosen).is_file():
            return Path(chosen)
        p = MODELS / "small" / self.FILE
        return p if p.exists() else None

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    async def ensure(self) -> bool:
        async with self.lock:
            if self.running():
                return True
            m = self.model()
            if not m:
                return False
            import os
            args = [str(exe(ENGINES / "llama", "llama-server")), "-m", str(m), "--host", "127.0.0.1", "--port",
                    str(self.PORT), "-c", "4096", "--jinja", "-ngl", "0", "--device", "none", "-np", "1",
                    "-t", str(max(2, (os.cpu_count() or 8) // 2)), "--cache-ram", "128", "--api-key", ENGINE_KEY]
            log = open(LOGS / "small.log", "w", encoding="utf-8", errors="ignore")
            self.proc = spawn(args, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                                        env=lib_env(ENGINES / "llama"))
            proc = self.proc
            async with httpx.AsyncClient(timeout=2, headers=AUTH) as c:
                for _ in range(60):
                    if self.proc is not proc or proc.poll() is not None:  # it ended, or Stop was pressed meanwhile
                        return False
                    try:
                        if (await c.get(f"{self.url}/health")).status_code == 200:
                            return True
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.5)
            return False

    async def complete(self, messages: list[dict], **extra) -> dict:
        """A written answer from the small model (e.g. a 3D design recipe in Create › 3D)."""
        if not await self.ensure():
            raise httpx.HTTPError("The small model isn't available")
        async with httpx.AsyncClient(timeout=300, headers=AUTH) as c:
            r = await c.post(f"{self.url}/v1/chat/completions", json={"messages": messages, **extra})
            r.raise_for_status()
            return r.json()["choices"][0]["message"]

    def stop(self) -> None:
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()

    async def decide(self, prompt: str, labels: list[str]) -> dict[str, float]:
        if not await self.ensure():
            raise httpx.HTTPError("Laya isn't available")
        return await decide_at(self.url, prompt, labels)


llm = LLM()
small = SmallModel()
