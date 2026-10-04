"""Starts the robot-arm calculator (rtb_run.py) in the Robotics Toolbox's own Python (engines/robotics/venv): numpy,
scipy and matplotlib live there, not in the app's Python. run.py <input.json> <outdir>."""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE.parents[1] / "engines" / "robotics" / "venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

if not PY.exists():
    print('RESULT: {"error": "the Robotics Toolbox isn\'t installed (engines/robotics)"}')
    sys.exit(0)
env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
env.update(MPLBACKEND="Agg", PYTHONIOENCODING="utf-8", MPLCONFIGDIR=str(Path(sys.argv[2]) / "mpl"))
p = subprocess.run([str(PY), str(HERE / "rtb_run.py"), sys.argv[1], sys.argv[2]], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", env=env, timeout=150,
                   creationflags=0x08000000 if os.name == "nt" else 0)
line = next((x for x in reversed(p.stdout.splitlines()) if x.startswith("RESULT:")), None)
print(line or 'RESULT: {"error": ' + __import__("json").dumps((p.stderr or p.stdout or "it failed")[-400:]) + "}")
