# Third-party software and models

AI Local's own code is under the PolyForm Noncommercial License (LICENSE.md). The installers download these from
their official sites; each keeps its own license (follow the links for the full texts). Nothing here is relicensed.

## Programs
| Part | What for | License |
|---|---|---|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | runs the chat / memory / helper models | MIT |
| llama.cpp b11384 + its converter (`tools/laya_convert`: convert_hf_to_gguf.py, conversion/, gguf-py — included unchanged, with its LICENSE) | turns the downloaded Laya model into a GGUF at install time and runs it (~450 MB of RAM instead of ~1.9 GB) | MIT |
| [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp) | pictures and video clips | MIT |
| [Tor](https://www.torproject.org) | private web search | BSD-3-Clause |
| [Blender](https://www.blender.org/about/license/) | builds the 3D designs, cut to fit | GNU GPL |
| [OrcaSlicer](https://github.com/SoftFever/OrcaSlicer) | G-code for 3D printers (optional) | AGPL-3.0 |
| [FreeCAD](https://www.freecad.org) | exact CAD parts, STEP files (optional) | LGPL-2.1-or-later |
| [uv](https://github.com/astral-sh/uv) | installs Python and its packages | Apache-2.0 / MIT |
| [Python](https://www.python.org) | runs the app | PSF License |
| [PyTorch](https://pytorch.org) | Laya, sound effects | BSD-3-Clause |
| [Robotics Toolbox for Python](https://github.com/petercorke/robotics-toolbox-python), Spatial Maths | robot-arm tool | MIT |
| [Laya](https://huggingface.co/convaiinnovations/laya) (Convai Innovations) | decides what you asked for | Apache-2.0 |
| [Woosh](https://github.com/SonyResearch/Woosh) (Sony AI) — code, included with one small change (see engines/woosh/NOTICE-LocalAI.txt) | sound effects for videos (optional) | MIT / Apache-2.0 |
| [PicoGK](https://github.com/leap71/PicoGK) (LEAP 71) — not downloaded by the online installer | 3D engine (optional, Windows) | Apache-2.0 |
| Python packages (FastAPI, Uvicorn, httpx, faster-whisper, piper-tts, kokoro-onnx, onnxruntime, Pillow, PyAV, pyflakes, …) | the app (pyflakes: checks the code the AI writes) | each package's own (MIT / BSD / Apache mostly) |

## Models
| Model | What for | License |
|---|---|---|
| [Qwen 3.5 4B](https://huggingface.co/unsloth/Qwen3.5-4B-GGUF) (Qwen team, GGUF by Unsloth) | the chat model, sees pictures | Apache-2.0 |
| [Qwen3 1.7B](https://huggingface.co/unsloth/Qwen3-1.7B-GGUF) | the small helper model | Apache-2.0 |
| [EmbeddingGemma 300M](https://huggingface.co/ggml-org/embeddinggemma-300m-qat-q8_0-GGUF) (Google) | memory search | Gemma Terms of Use |
| [Whisper small](https://huggingface.co/Systran/faster-whisper-small) (OpenAI, converted by Systran) | speech to text | MIT |
| [Kokoro-82M](https://huggingface.co/fastrtc/kokoro-onnx) | natural voices | Apache-2.0 |
| [Piper voices](https://huggingface.co/rhasspy/piper-voices) | fast voices | per voice — see its MODEL_CARD |
| [SDXL Turbo](https://huggingface.co/stabilityai/sdxl-turbo) (Stability AI, GGUF by OlegSkutte) | makes pictures (optional) | Stability AI Non-Commercial Community License |
| [Laya checkpoints](https://huggingface.co/convaiinnovations/laya) | decision model | Apache-2.0 |
| [Woosh weights](https://github.com/SonyResearch/Woosh) (Sony AI) | sound effects (optional) | CC-BY-NC-4.0 (non-commercial) |
| [Synchformer weights](https://huggingface.co/hkchengrex/MMAudio) (via MMAudio) | sound matched to video (optional) | see the MMAudio repository |

Models you download yourself from the Models page come with their own licenses — check them before commercial use.
