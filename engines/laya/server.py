"""The REAL Laya (Convai Innovations, Apache 2.0) — a 421M / 322M decision model (encoder + decision head), not a chat
model. Local AI runs it here, in its own Python (engines/laya/venv, CPU PyTorch), on 127.0.0.1 only.

POST /decide  {"state": "...", "questions": {name: {"type": "choice", "instructions": "...", "criteria": {...}}}, "lang": "en"|"auto"}
  -> the laya SDK's predict() result: answers[name] = {choice, probabilities, confidence, answer_confidence, ...}
     plus "model" (which checkpoint answered) and "ms".
POST /v1/systemone — the same, Jev-compatible body ({"state": {...}, "questions": {...}}).
GET /health -> {"ok": true, "loaded": [...]}
English goes to the fine-tuned typed-decisions checkpoint, Romanian / other languages to the multilingual one."""
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ.setdefault("LAYA_THREADS", str(max(2, (os.cpu_count() or 8) // 2)))
os.environ["HF_HUB_OFFLINE"] = "1"          # never goes online: the models are already on this PC
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import torch  # noqa: E402
import laya  # noqa: E402

torch.set_num_threads(int(os.environ["LAYA_THREADS"]))
MODELS = Path(sys.argv[1])            # models/laya-real
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8776
agents, lock = {}, threading.Lock()
RO = re.compile(r"[ăâîșşțţ]|\b(și|si|să|sa|că|ca|fă|fa|mi|îmi|imi|pentru|este|care|vreau|poți|poti|cum|ce|un|o|pe|la|cu|din|nu|da)\b", re.I)


def agent(name: str):
    with lock:
        if name not in agents:
            t = time.time()
            agents[name] = laya.load(str(MODELS / name), device="cpu")
            print(f"loaded {name} in {time.time() - t:.1f}s", flush=True)
        return agents[name]


def pick(text: str, lang: str) -> str:
    if lang == "en" or (lang == "auto" and len(RO.findall(text)) < 2):
        return "typed-decisions"
    return "multilingual"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code: int, obj: dict):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"ok": True, "loaded": list(agents), "pid": os.getpid()})

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            state = req.get("state", "")
            text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
            name = req.get("model") or pick(text, req.get("lang", "auto"))
            t = time.time()
            out = agent(name).predict(state, req["questions"])
            out["model"], out["ms"] = name, round((time.time() - t) * 1000)
            self._send(200, out)
        except Exception as e:  # noqa: BLE001
            self._send(400, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    pre = os.environ.get("LAYA_PRELOAD")
    if pre:  # the checkpoint the app chose (a folder name in models/laya-real); "1" = the default one
        agent(pre if pre != "1" and (MODELS / pre).is_dir() else "typed-decisions")
    print(f"laya on 127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
