"""3D AI models (picture -> 3D, text -> 3D, splitting a model into parts) to keep for later: the Models page's 3D tab.
This PC (AMD graphics, no CUDA) can't run them yet — almost all need an NVIDIA card — but they can be downloaded now,
so a stronger PC (or a later version of the app) already has them. They live in models/3d/<author>__<name>, folders
kept, and are never scanned as picture / video models (InSpatio is built on Wan: it would look like a video model)."""
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from . import models as M
from .config import MODELS
from .hardware import hardware

ROOT = MODELS / "3d"
SKIP = (".mp4", ".gif", ".webm", ".mov")  # demo videos some repos carry
TENCENT = "⚠ Tencent's licence excludes the EU (Romania), the UK and South Korea — check it before you use it"
CATALOG = [  # tested on Hugging Face 2026-10-04: all public (no login needed); gated ones (SF3D, SAM 3D) left out
    {"repo": "microsoft/TRELLIS.2-4B", "name": "TRELLIS.2 (4B)", "license": "MIT",
     "does": "picture → detailed 3D model with PBR textures (Microsoft)", "needs": "NVIDIA, about 24 GB"},
    {"repo": "microsoft/TRELLIS-image-large", "name": "TRELLIS", "license": "MIT",
     "does": "picture → 3D mesh, gaussians or radiance field (Microsoft)", "needs": "NVIDIA, 16 GB"},
    {"repo": "VAST-AI/TripoSG", "name": "TripoSG", "license": "MIT",
     "does": "picture → high-detail 3D shape (1.5B)", "needs": "NVIDIA, about 8 GB"},
    {"repo": "stabilityai/TripoSR", "name": "TripoSR", "license": "MIT",
     "does": "picture → 3D mesh in seconds (small, older)", "needs": "NVIDIA about 6 GB — or the processor, slowly"},
    {"repo": "wgsxm/PartCrafter", "name": "PartCrafter", "license": "MIT",
     "does": "picture → 3D model already split into separate parts", "needs": "NVIDIA, about 8 GB (estimate)"},
    {"repo": "nvidia/PartPacker", "name": "PartPacker", "license": "NVIDIA licence — see its page",
     "does": "picture → 3D object built part by part (NVIDIA)", "needs": "NVIDIA (CUDA)"},
    {"repo": "stepfun-ai/Step1X-3D", "name": "Step1X-3D", "license": "Apache 2.0",
     "does": "picture → 3D shape + texture", "needs": "NVIDIA, about 24 GB (estimate)",
     "only": ["Step1X-3D-Geometry-1300m/", "Step1X-3D-Texture/"]},
    {"repo": "blanchon/inspatio-world-v1.5", "name": "InSpatio-World 1.5", "license": "see its page",
     "does": "picture or video → a 3D world you can fly through (Oct 2026)", "needs": "NVIDIA, about 24 GB (estimate)"},
    {"repo": "tencent/Hunyuan3D-2.1", "name": "Hunyuan3D 2.1", "license": TENCENT,
     "does": "picture → 3D shape + PBR paint", "needs": "NVIDIA, 10 GB (shape) / 21 GB (with paint)"},
    {"repo": "tencent/Hunyuan3D-2mini", "name": "Hunyuan3D 2 mini (turbo)", "license": TENCENT,
     "does": "picture → 3D shape, small and fast (0.6B)", "needs": "NVIDIA, about 6 GB",
     "only": ["hunyuan3d-dit-v2-mini-turbo/", "hunyuan3d-vae-v2-mini-turbo/"]},
    {"repo": "tencent/Hunyuan3D-Omni", "name": "Hunyuan3D Omni", "license": TENCENT,
     "does": "3D shape steered by points, a skeleton or a box", "needs": "NVIDIA, 10 GB+ (estimate)"},
    {"repo": None, "name": "Point2Part (CMU)", "license": "", "watch": "https://github.com/henrytsui000/Point2Part",
     "does": "split a 3D model into the parts you point at: closed solids that fit together (Sept 2026)",
     "needs": "not released yet — code and weights “coming soon”"},
]
THREE_D_TAGS = {"image-to-3d", "text-to-3d", "3d", "mesh", "point-cloud", "gaussian-splatting", "3d-generation"}


def folder(repo: str) -> Path:
    return ROOT / repo.replace("/", "__")


def _tree(repo: str) -> list[dict]:
    def fetch():
        r = httpx.get(f"{M.HF}/api/models/{repo}/tree/main", params={"recursive": "true"}, timeout=30)
        r.raise_for_status()
        return [{"path": f["path"], "size": (f.get("lfs") or {}).get("size") or f.get("size", 0)}
                for f in r.json() if f.get("type") == "file"]
    return M._cached("tree3d:" + repo, 600, fetch)


def files_for(repo: str, only: list[str] | None = None) -> list[dict]:
    """What a download takes: every file (minus demo videos), or just the recommended version's folders + the root."""
    return [f for f in _tree(repo) if not f["path"].lower().endswith(SKIP)
            and (not only or "/" not in f["path"] or any(f["path"].startswith(o) for o in only))]


def nvidia() -> bool:
    def fetch():
        try:
            return any(k in g.lower() for g in hardware().get("gpus") or [] for k in ("nvidia", "geforce", "rtx", "quadro"))
        except Exception:  # noqa: BLE001 — unknown hardware: say "can't run here"
            return False
    return M._cached("nvidia", 3600, fetch)  # asking the graphics driver takes seconds


def _verdict() -> tuple[str, str]:
    return ("maybe", "An NVIDIA card was found: it might run, but the app can't start it yet — kept for later") \
        if nvidia() else ("later", "This PC has AMD graphics (no CUDA): it can't run here yet — download it to keep for a stronger PC")


def _download_state(repo: str) -> dict | None:
    d = next((d for d in M.downloads.values() if d["files"] and d["files"][0][0] == repo
              and d["status"] in ("running", "error")), None)
    return {k: d[k] for k in ("id", "status", "progress", "speed", "error")} if d else None


def _present(repo: str, files: list[dict]) -> bool:
    return bool(files) and all((folder(repo) / f["path"]).exists() for f in files)


def installed() -> list[dict]:
    out = []
    if ROOT.exists():
        for d in sorted(ROOT.iterdir()):
            if d.is_dir():
                files = [p for p in d.rglob("*") if p.is_file()]
                out.append({"repo": d.name.replace("__", "/", 1), "name": d.name.split("__", 1)[-1], "folder": str(d),
                            "size": sum(p.stat().st_size for p in files), "files": len(files),
                            "partial": any(p.suffix == ".part" for p in files)})
    return out


def page() -> dict:
    """The 3D tab: models on this PC + the list to download for later."""
    verdict, why = _verdict()
    have = {i["repo"] for i in installed() if not i["partial"]}

    def card(item: dict) -> dict:
        c = {**item, "verdict": verdict, "why": why, "size": None, "present": False, "download": None}
        if item.get("repo"):
            try:
                files = files_for(item["repo"], item.get("only"))
                c["size"], c["present"] = sum(f["size"] for f in files), _present(item["repo"], files)
            except httpx.HTTPError:
                c["present"] = item["repo"] in have  # offline: no sizes, still knows what's here
            c["download"] = _download_state(item["repo"])
        return c
    with ThreadPoolExecutor(6) as pool:
        store = list(pool.map(card, CATALOG))
    return {"installed": installed(), "store": store, "verdict": verdict, "why": why}


def search(query: str) -> list[dict]:
    """Hugging Face: picture-to-3D / text-to-3D models (and anything tagged 3D) matching the words."""
    def fetch():
        keys = [("expand[]", k) for k in ("downloads", "likes", "lastModified", "pipeline_tag", "tags", "gated", "cardData")]
        found = {}
        for extra in ([("pipeline_tag", "image-to-3d")], [("pipeline_tag", "text-to-3d")], []):
            r = httpx.get(f"{M.HF}/api/models", params=[("search", query), ("sort", "downloads"), ("limit", "15"), *keys,
                                                        *extra], timeout=30)
            r.raise_for_status()
            for m in r.json():
                tags = {t.lower() for t in m.get("tags") or []} | {str(m.get("pipeline_tag") or "").lower()}
                if extra or tags & THREE_D_TAGS or "3d" in m["id"].lower():
                    found.setdefault(m["id"], m)
        ms = sorted(found.values(), key=lambda m: -(m.get("downloads") or 0))[:15]
        with ThreadPoolExecutor(8) as pool:
            sizes = list(pool.map(lambda m: sum(f["size"] for f in files_for(m["id"])) if not m.get("gated") else 0, ms))
        return list(zip(ms, sizes))
    verdict, why = _verdict()
    out = []
    for m, size in M._cached(f"search3d:{query.lower()}", 300, fetch):
        card = m.get("cardData") or {}
        lic = " ".join(str(card.get(k) or "") for k in ("license", "license_name")).strip()
        lic = TENCENT if "hunyuan" in (lic + " " + m["id"]).lower() else (f"licence: {lic}" if lic else "")
        out.append({"repo": m["id"], "author": m["id"].split("/")[0], "name": m["id"].split("/")[-1], "license": lic,
                    "downloads": m.get("downloads", 0), "likes": m.get("likes", 0),
                    "updated": (m.get("lastModified") or "")[:10], "task": m.get("pipeline_tag") or "",
                    "gated": bool(m.get("gated")), "size": size, "verdict": verdict, "why": why,
                    "present": folder(m["id"]).exists() and not any(folder(m["id"]).rglob("*.part")),
                    "download": _download_state(m["id"])})
    return out


def download(repo: str, only: list[str] | None = None) -> dict:
    item = next((c for c in CATALOG if c.get("repo") == repo), {})
    files = files_for(repo, only or item.get("only"))
    if not files:
        raise ValueError("No files to download")
    return M.start_download(item.get("name") or repo.split("/")[-1], "3d", [(repo, f["path"], "@3d/" + f["path"]) for f in files],
                            sum(f["size"] for f in files) / 1e9)


def delete(repo: str) -> None:
    d = folder(repo).resolve()
    if ROOT.resolve() not in d.parents or not d.is_dir():
        raise ValueError("Only 3D models this app downloaded can be deleted here")
    import time
    for st in list(M.downloads.values()):
        if st["files"] and st["files"][0][0] == repo:
            M.cancel_download(st["id"])
            for _ in range(50):  # the download thread lets go of its file at the next chunk
                if st["status"] != "running":
                    break
                time.sleep(0.1)
            M.cancel_download(st["id"])  # a stopped download is forgotten
    shutil.rmtree(d)
