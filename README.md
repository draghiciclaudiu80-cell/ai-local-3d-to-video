# AI Local — from 3D to long video (beta)

**A private AI that runs entirely on your own PC.** Chat, voice, pictures, video clips and whole movies, working
3D-printable designs, engineering calculators and a robot-arm tool — no account, no subscription, no cloud. Nothing
you type, say or make leaves your computer.

> **Beta.** It works every day on its author's PC (Windows 11, a mid-range AMD graphics card, 16 GB RAM). It needs
> testers — especially people with **bigger PCs who can run bigger models** than the small ones it ships with.
> Please report what works and what doesn't in [Issues](../../issues).

## What it does

- **Chat** with a local model (Qwen 3.5 4B by default — it also looks at pictures you give it), with memory, rules
  and skills, documents (PDF, Word), web search through **Tor** (off until you switch it on), and 👍 / 👎 on every
  answer so it learns what you like.
- **Voice**: talk to it (Whisper) and it answers out loud (Kokoro / Piper voices).
- **Pictures and videos** with stable-diffusion.cpp, and **long videos / movies** joined from clips, with narration and
  sound effects (Sony's Woosh model, optional).
- **3D design that works**: tested ready-made devices (robot arm sized for its load, robotic hand, foam-dart blasters,
  fidget spinner, a door / gate **slide latch with a padlock hasp**, pump, gears, drone frame, boxes with lids…), designs
  built part by part with a fit check (no parts may collide, and the fixer re-checks until nothing touches), an
  editor to change them by hand (move, stretch, holes, threads, **mirror**, Ctrl+click to select several parts),
  **cut to fit** your printer's plate, and **G-code for your printer** with OrcaSlicer — all offline.
- **Engineering calculators** the AI uses by itself: mechanics, fluids, electronics / PCB, airgun energy and
  trajectory, a robot-arm tool (inverse kinematics, servo choice), a parts inventory.
- **Apps** (Create › Apps): describe an app, game or tool — the AI writes it, reads the code (missing element ids, open
  tags), opens and **uses it in a hidden browser** (draws, presses every button, types keys), **looks at a screenshot**
  of it, and fixes what's wrong; tested starting points (paint, notepad, solitaire, games). It runs sealed (no internet,
  no access to your files) and can be saved as a project folder on your Desktop.
- **Forge** (Create › Forge): new skills the AI writes for itself (e.g. "a skill that shows my CPU and RAM use"), checked
  (pyflakes + sandbox rules) and self-tested in a locked sandbox (no files, no internet, no programs, 512 MB). Each one
  stays a **draft until you try it and turn it on**; every version is kept, so you can always go back.
- **Agent team** (Team, off by default): a planner gives each expert (researcher, engineer, 3D designer, coder, writer)
  one step, an independent judge checks every step, a reviewer writes the result — all in a chat. Jobs queue up.
- **Computer use** in the app's **own browser** (tabs, optional Tor — your desktop isn't touched) or on your screen
  (the app shrinks to a corner panel; you approve every step in the chat). **Background tasks**: apps, skills, team jobs,
  3D builds and pictures keep working while you chat, with a notice when each is ready.
- **📐 Geometric reasoning** (Memory › Reasoning, off by default): for questions with sizes, angles, counts, dates or
  logic, the AI writes the problem as a small program, runs it in the sandbox, re-runs it with changed numbers (a
  "perturbation test") and answers from the result; the small Laya model decides when it's needed, and follow-ups ("and
  with a 3 mm gap?") just change the numbers in the same program.
- **Bigger models**: the Models page downloads any GGUF model from Hugging Face and shows what each can do (tools,
  vision, video, thinking) before you pick it. Its **3D** tab finds and downloads picture-to-3D AI models (TRELLIS,
  TripoSG, PartCrafter, Hunyuan3D…) to keep for a stronger PC — most need an NVIDIA card.

## What you need

- **Windows 10 / 11 (64-bit)** or **Linux** (made on Bazzite / Fedora Atomic; Ubuntu works too)
- 16 GB of memory recommended (8 GB minimum)
- about **16 GB** of free disk space (12 GB without the picture model, 21 GB with the sound effects; more for bigger
  models)
- a graphics card helps a lot (AMD, NVIDIA or Intel — Vulkan). Without one it works, just slower.

## Install

**Windows**

1. Click the green **Code** button above → **Download ZIP**, and unpack it to a normal folder (e.g. `C:\AI Local` —
   not OneDrive).
2. Double-click **`INSTALL.cmd`**. It downloads Python, the engines and the models from their official sites (each
   file checked by its SHA-256), builds the starter and makes a desktop icon. About 8 GB for the basics — it asks about
   the optional parts (pictures, 3D printing, exact CAD, sound effects). If the download stops, run it again: it goes on.
3. Start **AI Local** from the desktop. The first start checks your PC (Settings → This PC) and offers fixes.

**Linux**

```bash
git clone https://github.com/draghiciclaudiu80-cell/ai-local-3d-to-video.git
cd ai-local-3d-to-video
bash install.sh            # --no-pictures / --no-sound skip the 3.8 GB / 4.3 GB optional models
```

Everything stays inside the folder (its own Python, engines and models); nothing is installed into the system.

## Good to know

- **Private by design**: the app listens only on `127.0.0.1`, the web is off until you allow it (and then goes
  through Tor), downloaded files land in a sandbox and are never run.
- Your chats, memory and pictures stay in the `data` folder. Delete the folder and they're gone.
- **Safety**: the airgun calculators and the 3D designs (blasters, devices, robot parts) are for hobby use. You are
  responsible for following your country's laws and for what you print and build. Printed parts can break —
  wear eye protection when testing anything with springs, pressure or moving parts.
- The small built-in models make mistakes. Check important numbers; the calculators show their formulas and inputs.

## License

**Free for people, not for companies.** AI Local is released under the
[PolyForm Noncommercial License 1.0.0](LICENSE.md): you may use, change and share it for free for any
**non-commercial** purpose — personal use, hobby projects, study, research, schools, charities. **Commercial use
needs a separate license** — open an issue or contact the author. (Strictly, that makes it *source-available*, not
"open source" in the OSI sense.)

The programs and models it downloads keep their own licenses (Blender GPL, OrcaSlicer AGPL, FreeCAD LGPL, Qwen
Apache-2.0, Woosh weights CC-BY-NC, …) — see [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Support the project ☕

AI Local is made by one person on one ordinary PC. If it's useful to you, a coffee helps buy the hardware to test
bigger models and keep improving it:

**☕ Buy me a coffee — the link is coming soon.**

## Reporting problems

Open an [issue](../../issues) with: your Windows / Linux version, your graphics card and memory, what you did, and what
happened (Settings → This PC shows the useful details). Please don't post your chats or personal files.
