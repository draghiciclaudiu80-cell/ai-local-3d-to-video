#!/usr/bin/env bash
# Local AI - installer for Linux (made for Bazzite / Fedora Atomic; works on Fedora, Ubuntu and similar too).
#   bash install.sh            install / repair the app IN THIS FOLDER
#   bash install.sh --copy     first copy it to ~/LocalAI (e.g. from a USB stick); an update keeps your data
#   options: --dest DIR (where --copy puts it)  --no-start  --no-freecad (skip FreeCAD, 0.8 GB)
#            --no-orca (skip OrcaSlicer: no G-code for the 3D printer, 0.4 GB)  --yes
#            --no-sound (skip the 4.3 GB sound-effect models when they're downloaded)
# Everything stays inside the app folder: its own Python 3.11 and Python packages, llama.cpp + stable-diffusion.cpp
# (Vulkan = the graphics chip), Tor, Blender, FreeCAD, OrcaSlicer (G-code for the 3D printer). Nothing is installed
# into the system: no sudo, fine on an immutable OS. Downloads about 2.7 GB, each file checked against a pinned SHA-256.
# Then: app menu entry + desktop
# icon, and it starts.
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
COPY=0; DEST="$HOME/LocalAI"; START=1; FREECAD=1; ORCA=1; SOUND=1
while [ $# -gt 0 ]; do
    case "$1" in
        --copy) COPY=1 ;;
        --dest) DEST="$2"; shift ;;
        --no-start) START=0 ;;
        --no-freecad) FREECAD=0 ;;
        --no-orca) ORCA=0 ;;
        --no-sound) SOUND=0 ;;
        --yes|-y) ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "unknown option: $1 (see: bash install.sh --help)"; exit 2 ;;
    esac
    shift
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32m%s\033[0m\n' "$*"; }
warn() { printf '    \033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || die "this installer is for Linux"
[ "$(uname -m)" = x86_64 ] || die "Local AI needs a 64-bit Intel / AMD PC (x86_64); this one is $(uname -m)"
for t in curl tar sha256sum xz df; do
    command -v "$t" >/dev/null || die "the program '$t' is missing (every normal Linux has it - install it with the package manager)"
done

# ---------------------------------------------------------------- 0) copy to ~/LocalAI (from the USB stick)
if [ "$COPY" = 1 ] && [ "$(readlink -f "$DEST")" != "$HERE" ]; then
    step "Copying Local AI to $DEST (the models are big: this takes a few minutes)"
    mkdir -p "$DEST"
    need=$(( $(du -s --block-size=1G "$HERE" | cut -f1) + 6 ))
    free=$(df --output=avail -BG "$DEST" | tail -1 | tr -dc '0-9')
    [ "$free" -ge "$need" ] || die "not enough free space in $DEST: $free GB free, about $need GB needed"
    if command -v rsync >/dev/null; then
        rsync -a --info=progress2 --exclude=/data/ "$HERE/" "$DEST/"
        [ -d "$DEST/data" ] || rsync -a "$HERE/data/" "$DEST/data/"
    else
        for x in "$HERE"/* "$HERE"/.[!.]*; do
            [ -e "$x" ] || continue
            [ "$(basename "$x")" = data ] && [ -d "$DEST/data" ] && continue  # an update keeps your chats & settings
            cp -a "$x" "$DEST/"
        done
    fi
    ok "copied"
    args=(); [ "$START" = 0 ] && args+=(--no-start); [ "$FREECAD" = 0 ] && args+=(--no-freecad); [ "$ORCA" = 0 ] && args+=(--no-orca)
    exec bash "$DEST/install.sh" "${args[@]}"
fi

APP="$HERE"
cd "$APP"
E="$APP/engines"
mkdir -p "$E" "$APP/data"
DL="$E/.downloads"
mkdir -p "$DL"
export UV_CACHE_DIR="$E/.uv-cache" UV_PYTHON_INSTALL_DIR="$E/.uv-python" UV_PYTHON_BIN_DIR="$E/.uv-bin"
export UV_NO_CONFIG=1  # ignore any uv settings of the PC: this install only uses its own folder
chmod +x "$APP/start.sh" "$APP/install.sh" 2>/dev/null || true
free=$(df --output=avail -BG "$APP" | tail -1 | tr -dc '0-9')
need=$(( (FREECAD == 1 ? 11 : 7) + (ORCA == 1 ? 1 : 0) ))
[ "$free" -ge "$need" ] || die "not enough free space next to $APP: $free GB free, about $need GB needed for the downloads"
echo "Installing Local AI in: $APP"

get() {  # url name sha256 - resumable download into engines/.downloads, checked, retried
    local url="$1" out="$DL/$2" sum="$3" try
    if [ -f "$out" ] && echo "$sum  $out" | sha256sum -c --status; then return 0; fi
    for try in 1 2 3 4; do
        curl -fL --connect-timeout 20 --progress-bar -C - -o "$out" "$url" || true
        if [ -f "$out" ] && echo "$sum  $out" | sha256sum -c --status; then ok "$2: checksum OK"; return 0; fi
        warn "$2: download broken or wrong checksum - starting again ($try/4)"
        rm -f "$out"
        sleep 2
    done
    die "could not download $2 correctly from $url"
}

# ---------------------------------------------------------------- 1) uv
step "1/9  uv (fetches Python and the Python packages)"
UV="$E/uv/uv"
if [ ! -x "$UV" ] || ! "$UV" --version 2>/dev/null | grep -q "^uv 0.11.29"; then
    get "https://github.com/astral-sh/uv/releases/download/0.11.29/uv-x86_64-unknown-linux-gnu.tar.gz" uv.tar.gz \
        04f8b82f5d47f0512dcd32c67a4a6f16a0ea27c81537c338fd0ad6b23cebe829
    rm -rf "$E/uv"; mkdir -p "$E/uv"
    tar -xzf "$DL/uv.tar.gz" -C "$E/uv" --strip-components=1
fi
ok "$("$UV" --version)"

# ---------------------------------------------------------------- 2) Python 3.11 (the app's own)
step "2/9  Python 3.11 (the app's own - the system's Python is not touched)"
PY="$E/python/bin/python3.11"
if [ ! -x "$PY" ]; then
    "$UV" python install 3.11.15 --no-bin
    src="$(find "$UV_PYTHON_INSTALL_DIR" -maxdepth 1 -type d -name 'cpython-3.11.15-linux-x86_64-gnu' | head -1)"
    [ -n "$src" ] || die "Python 3.11 wasn't installed"
    rm -rf "$E/python"
    mv "$src" "$E/python"
    rm -rf "$UV_PYTHON_INSTALL_DIR" "$UV_PYTHON_BIN_DIR"
fi
"$PY" -c "import sys, ssl, sqlite3, lzma, zipfile; print('    Python', sys.version.split()[0])" || die "the bundled Python doesn't work"

# ---------------------------------------------------------------- 3) Python packages (3 environments)
step "3/9  Python packages: the app, the real Laya, the sound-effects engine (~1.3 GB, the longest step)"
venv() {  # a working environment on the bundled Python, or a fresh one
    if [ -e "$1/bin/python" ] && [ "$(readlink "$1/bin/python")" = "$PY" ] && "$1/bin/python" -c "pass" 2>/dev/null; then return 0; fi
    rm -rf "$1"
    "$UV" venv --quiet --python "$PY" "$1"
    ln -sfn "$PY" "$1/bin/python"  # always this folder's Python (start.sh repairs it if the folder moves)
}
CPU_TORCH="https://download.pytorch.org/whl/cpu"  # the processor build: the normal one pulls 2+ GB of NVIDIA libraries
venv "$APP/.venv"
"$UV" pip install --python "$APP/.venv/bin/python" -r "$APP/linux/requirements-app.txt"
venv "$E/laya/venv"
"$UV" pip install --python "$E/laya/venv/bin/python" --index-url "$CPU_TORCH" "torch==2.14.0+cpu"
"$UV" pip install --python "$E/laya/venv/bin/python" -r "$APP/linux/requirements-laya.txt"
venv "$E/woosh/venv"
"$UV" pip install --python "$E/woosh/venv/bin/python" --index-url "$CPU_TORCH" \
    "torch==2.8.0+cpu" "torchaudio==2.8.0+cpu" "torchvision==0.23.0+cpu"
"$UV" pip install --python "$E/woosh/venv/bin/python" -r "$APP/linux/requirements-woosh.txt"
"$UV" pip install --python "$E/woosh/venv/bin/python" --no-deps "hear21passt==0.0.26"  # like Woosh's own setup
venv "$E/robotics/venv"  # the robot-arm plugin (Robotics Toolbox for Python, MIT): ~70 MB
"$UV" pip install --python "$E/robotics/venv/bin/python" -r "$APP/linux/requirements-robotics.txt"
"$UV" pip install --python "$E/robotics/venv/bin/python" --no-deps "roboticstoolbox-python==1.4.4" \
    "spatialmath-python==1.1.18" "spatialgeometry==1.4.1" "pgraph-python==0.6.5" "ansitable==1.1.1" "colored==2.3.2" \
    "progress==1.6.1" "typing-extensions==4.16.0"
ok "packages installed"

# ---------------------------------------------------------------- 4) llama.cpp (chat, memory, small model)
step "4/9  llama.cpp b11191 (chat models on the graphics chip - Vulkan)"
if [ ! -x "$E/llama/llama-server" ]; then
    get "https://github.com/ggml-org/llama.cpp/releases/download/b11191/llama-b11191-bin-ubuntu-vulkan-x64.tar.gz" llama.tar.gz \
        0e2018de56a2e23dcdf71c5a4f7ee01889820c29bcb7a7d5db9318bc7c2c6251
    rm -rf "$E/llama"; mkdir -p "$E/llama"
    tar -xzf "$DL/llama.tar.gz" -C "$E/llama" --strip-components=1
fi
ok "llama-server ready"

# ---------------------------------------------------------------- 5) stable-diffusion.cpp (pictures + videos)
step "5/9  stable-diffusion.cpp master-920 (pictures and videos - Vulkan)"
if [ ! -x "$E/sd/sd-cli" ]; then
    get "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-920-2f88688/sd-master-2f88688-bin-Linux-Ubuntu-24.04-x86_64-vulkan.zip" sd.zip \
        81187de7eef5828816858de076c6d7efe4ee29e1536d22f86338960d5119c574
    rm -rf "$E/sd"; mkdir -p "$E/sd"
    "$PY" -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$DL/sd.zip" "$E/sd"
    chmod +x "$E/sd/sd-cli" "$E/sd/sd-server"  # zip files don't keep the "program" mark
fi
ok "sd-cli ready"

# ---------------------------------------------------------------- 6) Tor (private web searches)
step "6/9  Tor 15.0.23 (private web searches - signed by the Tor Project, checksum pinned)"
if [ ! -x "$E/tor/tor" ]; then
    get "https://archive.torproject.org/tor-package-archive/torbrowser/15.0.23/tor-expert-bundle-linux-x86_64-15.0.23.tar.gz" tor.tar.gz \
        08d49de27f542b8f73e2014e064d8320562b5d20019c03d4725c5a5249d97985
    t="$DL/tor-unpack"; rm -rf "$t"; mkdir -p "$t"
    tar -xzf "$DL/tor.tar.gz" -C "$t"
    rm -rf "$E/tor"; mkdir -p "$E/tor"
    cp -a "$t/tor/." "$E/tor/"
    cp "$t/data/geoip" "$t/data/geoip6" "$E/tor/"
    rm -rf "$t"
fi
ok "tor ready"

# ---------------------------------------------------------------- 7) Blender (3D designs, pictures of them, GLB)
step "7/9  Blender 5.2.0 LTS (builds the 3D designs on Linux - about 380 MB)"
if [ ! -x "$E/blender/blender" ]; then
    get "https://download.blender.org/release/Blender5.2/blender-5.2.0-linux-x64.tar.xz" blender.tar.xz \
        96f6c181a30f4950607839dc84d42a354b250d8a0231b098b59b7bc69c351c48
    rm -rf "$E/blender"; mkdir -p "$E/blender"
    tar -xJf "$DL/blender.tar.xz" -C "$E/blender" --strip-components=1
fi
ok "blender ready"

# ---------------------------------------------------------------- 8) FreeCAD (precise CAD: exact screw holes, STEP)
if [ "$FREECAD" = 1 ]; then
    step "8/9  FreeCAD 1.1.4 (precise mechanical parts: exact holes, STEP files - about 820 MB)"
    if [ ! -x "$E/freecad/AppRun" ]; then
        get "https://github.com/FreeCAD/FreeCAD/releases/download/1.1.4/FreeCAD_1.1.4-Linux-x86_64-py311.AppImage" \
            freecad.AppImage f6dc6ba676e5ac96a565ebc8d657232f94c6158e85b4352141bd1a46f6b43434
        chmod +x "$DL/freecad.AppImage"
        rm -rf "$E/freecad" "$DL/squashfs-root"
        (cd "$DL" && ./freecad.AppImage --appimage-extract >/dev/null)  # unpacked: no FUSE needed
        mv "$DL/squashfs-root" "$E/freecad"
    fi
    "$E/freecad/AppRun" freecadcmd --version 2>/dev/null | head -1 | sed 's/^/    /' || warn "FreeCAD didn't start"
else
    step "8/9  FreeCAD skipped (--no-freecad): precise parts are then built with the other engines"
fi

# ---------------------------------------------------------------- 9) OrcaSlicer (G-code for the user's 3D printer, offline)
if [ "$ORCA" = 1 ]; then
    step "9/9  OrcaSlicer 2.4.2 (G-code / 3MF for the 3D printer, sliced here with no account - about 130 MB)"
    if [ ! -x "$E/orcaslicer/AppRun" ]; then
        get "https://github.com/SoftFever/OrcaSlicer/releases/download/v2.4.2/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage" \
            orcaslicer.AppImage d12fb8c8eac1aecd2dfb6377acd48f994f8fa439ed5292fa532dd82880f029fd
        chmod +x "$DL/orcaslicer.AppImage"
        rm -rf "$E/orcaslicer" "$DL/squashfs-root"
        (cd "$DL" && ./orcaslicer.AppImage --appimage-extract >/dev/null)  # unpacked: no FUSE needed
        mv "$DL/squashfs-root" "$E/orcaslicer"
    fi
    [ -x "$E/orcaslicer/AppRun" ] && ok "orcaslicer ready" || warn "OrcaSlicer didn't unpack"
else
    step "9/9  OrcaSlicer skipped (--no-orca): no G-code for the 3D printer (STL files still work)"
fi
if ! id -nG | grep -qw dialout; then  # a 3D printer on USB (/dev/ttyUSB0) needs it - the only step that needs sudo
    warn "To print over the printer's USB cable, allow serial ports once (then log out and in):"
    warn "  grep -q '^dialout:' /etc/group || grep '^dialout:' /usr/lib/group | sudo tee -a /etc/group"
    warn "  sudo usermod -aG dialout \$USER"
fi

# ---------------------------------------------------------------- models (a GitHub copy downloads them; a USB copy has them)
step "Models: chat, memory, small helper, Laya, speech, voices (~7 GB from Hugging Face, every file checked)"
groups="core"; [ "$SOUND" = 1 ] && groups="core,sound"
"$APP/.venv/bin/python" "$APP/tools/get_downloads.py" --os linux --groups "$groups" \
    || die "the models didn't all download - run install.sh again: it goes on where it stopped"

# ---------------------------------------------------------------- checks
step "Checking that everything runs on this PC"
problems=0
for bin in "$E/llama/llama-server" "$E/sd/sd-cli" "$E/tor/tor" "$E/blender/blender"; do
    missing="$(LD_LIBRARY_PATH="$(dirname "$bin")" ldd "$bin" 2>/dev/null | grep "not found" | awk '{print $1}' | tr '\n' ' ')"
    if [ -n "$missing" ]; then warn "$(basename "$bin") needs system libraries that are missing: $missing"; problems=$((problems + 1)); fi
done
gpu="$(LD_LIBRARY_PATH="$E/llama" timeout 60 "$E/llama/llama-server" --list-devices 2>&1 | grep -i "vulkan[0-9]*:" | sed 's/^ *//' | head -3 || true)"
if [ -n "$gpu" ]; then ok "graphics chip (Vulkan): $gpu"; else warn "no Vulkan graphics found: chat runs on the processor (slower), pictures / videos may not work"; fi
"$APP/.venv/bin/python" -c "import fastapi, uvicorn, httpx, faster_whisper, piper, kokoro_onnx, av, onnxruntime, PIL, pypdf" \
    && ok "app packages OK" || { warn "app packages incomplete"; problems=$((problems + 1)); }
"$E/laya/venv/bin/python" -c "import torch, transformers, laya" && ok "Laya packages OK" || { warn "Laya packages incomplete"; problems=$((problems + 1)); }
"$E/woosh/venv/bin/python" -c "import torch, torchaudio, torchvision, hydra, timm, einops" \
    && ok "sound-effects packages OK" || { warn "sound-effects packages incomplete"; problems=$((problems + 1)); }
LD_LIBRARY_PATH="$E/tor" "$E/tor/tor" --version 2>/dev/null | head -1 | sed 's/^/    /' || true
"$E/blender/blender" -b --factory-startup --python-expr "import bpy; print('    Blender', bpy.app.version_string)" 2>/dev/null | grep "Blender" || warn "Blender didn't start"
"$APP/.venv/bin/python" "$APP/tools/check.py" 2>&1 | tail -1 | sed 's/^/    app self-check: /'

# ---------------------------------------------------------------- menu entry, desktop icon, clean up, start
step "App menu entry + desktop icon"
"$APP/.venv/bin/python" - "$APP" <<'PYEOF' || warn "could not make the shortcuts"
import sys
sys.path.insert(0, sys.argv[1])
from app import setup
for f in setup.make_shortcuts():
    print("    made:", f)
PYEOF
rm -rf "$DL" "$UV_CACHE_DIR"  # the downloads were unpacked; the package cache is ~2 GB

if [ "$problems" -gt 0 ]; then
    warn "$problems thing(s) above need attention - the app may still work; run this installer again after fixing them"
fi
printf '\n\033[1;32mLocal AI is installed in %s\033[0m\n' "$APP"
echo "Start it from the app menu (\"Local AI\"), the desktop icon, or:  $APP/start.sh"
echo "Tip: for its own window (no tabs), install Chromium from the software store; without it the app opens in Firefox."
if [ "$START" = 1 ]; then
    echo "Starting it now..."
    nohup "$APP/start.sh" >/dev/null 2>&1 &
fi
