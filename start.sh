#!/usr/bin/env bash
# Local AI - start (Linux). The app menu entry / desktop icon "Local AI" runs this.
# Not installed yet? Run  bash install.sh  (in this folder) first.
set -u
APP="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$APP" || exit 1
PY="$APP/engines/python/bin/python3.11"

note() {  # a desktop notification when started from the menu (no terminal), the text otherwise
    if [ -t 1 ]; then echo "$1"; else notify-send "Local AI" "$1" 2>/dev/null || echo "$1"; fi
}

if [ ! -x "$PY" ] || [ ! -e "$APP/.venv/bin/python" -a ! -L "$APP/.venv/bin/python" ]; then
    note "Local AI isn't installed in $APP yet: open a terminal there and run   bash install.sh"
    exit 1
fi
# A Python environment remembers its Python's full path; the folder moved -> point it at this folder's Python again
for v in "$APP/.venv" "$APP"/engines/*/venv; do
    [ -d "$v/bin" ] || continue
    if [ "$(readlink "$v/bin/python")" != "$PY" ]; then
        ln -sfn "$PY" "$v/bin/python"
        sed -i "s|^home = .*|home = $APP/engines/python/bin|" "$v/pyvenv.cfg" 2>/dev/null
    fi
done
exec "$APP/.venv/bin/python" "$APP/localai_linux.py" "$@"
