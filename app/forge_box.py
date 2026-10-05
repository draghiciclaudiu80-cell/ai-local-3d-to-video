"""The Forge's sandbox: runs ONE skill the local AI wrote, in its own Python process, locked down. Started by
app/forge.py as `python -I forge_box.py <skill.py> test|run <params.json>` in an empty folder; prints one JSON line.
The locks, from the outside in:
- its own process (tied to the app's job: it dies with the app), killed after 20 s by the app;
- a nested Windows job (Linux: rlimit): at most 512 MB of memory and NO child processes;
- the code is checked BEFORE it runs (check() below, also used by the app): only harmless modules can be imported,
  no open / eval / exec / __import__ / getattr…, no names starting with "_" (the way out of a Python sandbox);
- while it runs: the same import list is enforced, and the builtins are a short safe list.
So a skill can compute, use time / dates / random / math / json / text, and read this PC's numbers through `system`
(CPU, memory, disks, battery, uptime) — it can't touch files, the network, programs or the app. No app imports here."""
import ast
import json
import os
import sys
import time

ALLOWED = {"math", "statistics", "random", "datetime", "time", "json", "re", "string", "textwrap", "itertools",
           "functools", "collections", "decimal", "fractions", "heapq", "bisect", "calendar", "hashlib", "base64",
           "unicodedata", "dataclasses", "typing", "enum", "copy", "operator", "html", "difflib", "colorsys", "struct",
           "zlib", "binascii", "secrets", "uuid", "system"}
BLOCKED = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals", "vars", "getattr",
           "setattr", "delattr", "memoryview", "help", "exit", "quit", "dir", "__builtins__", "__loader__", "__spec__"}
# attributes that lead from a harmless object to the interpreter's insides (a generator's frame -> the caller's
# globals -> os); anything starting with "_" is refused as well
BLOCKED_ATTRS = {"gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "cr_await", "ag_frame", "ag_code", "ag_await",
                 "f_back", "f_globals", "f_locals", "f_builtins", "f_code", "f_trace", "tb_frame", "tb_next", "mro",
                 "with_traceback", "func_globals", "func_code", "modules", "load_module", "exec_module"}
SAFE_BUILTINS = ["abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable", "chr", "complex", "dict",
                 "divmod", "enumerate", "filter", "float", "format", "frozenset", "hash", "hex", "int", "isinstance",
                 "issubclass", "iter", "len", "list", "map", "max", "min", "next", "oct", "ord", "pow", "print", "range",
                 "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip", "True", "False",
                 "None", "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "ZeroDivisionError",
                 "ArithmeticError", "AssertionError", "RuntimeError", "StopIteration", "LookupError", "OverflowError",
                 "NotImplementedError", "AttributeError", "ImportError", "NameError", "type", "object", "super",
                 "property", "classmethod", "staticmethod"]
MEMORY_MB = 512


def check(code: str) -> list[str]:
    """What's not allowed, before anything runs (empty = fine). Also checks the skill's shape: run() and test()."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax error on line {e.lineno}: {e.msg}"]
    bad = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            bad += [f"line {n.lineno}: “import {a.name}” isn't allowed in the sandbox (allowed: {', '.join(sorted(ALLOWED))})"
                    for a in n.names if a.name.split(".")[0] not in ALLOWED]
        elif isinstance(n, ast.ImportFrom):
            if n.level or (n.module or "").split(".")[0] not in ALLOWED:
                bad.append(f"line {n.lineno}: “from {n.module} import …” isn't allowed in the sandbox")
        elif isinstance(n, ast.Name) and n.id in BLOCKED:
            bad.append(f"line {n.lineno}: “{n.id}” isn't allowed in the sandbox")
        elif isinstance(n, ast.Attribute) and (n.attr.startswith("_") or n.attr in BLOCKED_ATTRS):
            bad.append(f"line {n.lineno}: “.{n.attr}” isn't allowed in the sandbox" + (" (names starting with _)"
                                                                                       if n.attr.startswith("_") else ""))
        elif isinstance(n, (ast.Global, ast.Nonlocal)) and any(x.startswith("_") for x in n.names):
            bad.append(f"line {n.lineno}: names starting with _ aren't allowed in the sandbox")
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    bad += [f"there's no {f}() function" for f in ("run", "test") if f not in funcs]
    return list(dict.fromkeys(bad))[:8]


# ---------------------------------------------------------------- `system`: this PC's numbers, read-only
def _system():
    """A plain object with a few functions — not a module: nothing else (os, ctypes) can be reached through it."""
    import types
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as w
        k32 = ctypes.windll.kernel32

        class Mem(ctypes.Structure):
            _fields_ = [("len", w.DWORD), ("load", w.DWORD), ("total", ctypes.c_uint64), ("avail", ctypes.c_uint64),
                        ("pf_total", ctypes.c_uint64), ("pf_avail", ctypes.c_uint64), ("v_total", ctypes.c_uint64),
                        ("v_avail", ctypes.c_uint64), ("v_ext", ctypes.c_uint64)]

        def memory():
            m = Mem()
            m.len = ctypes.sizeof(Mem)
            k32.GlobalMemoryStatusEx(ctypes.byref(m))
            return {"total_gb": round(m.total / 2**30, 2), "used_gb": round((m.total - m.avail) / 2**30, 2),
                    "free_gb": round(m.avail / 2**30, 2), "percent": round(100 * (m.total - m.avail) / m.total, 1)}

        def _times():
            idle, kern, user = (w.FILETIME(), w.FILETIME(), w.FILETIME())
            k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
            v = [(t.dwHighDateTime << 32) | t.dwLowDateTime for t in (idle, kern, user)]
            return v[0], v[1] + v[2]  # (idle, total): kernel time includes idle

        def disks():
            out, mask = [], k32.GetLogicalDrives()
            for i in range(26):
                root = f"{chr(65 + i)}:\\"
                if mask >> i & 1 and k32.GetDriveTypeW(root) == 3:  # fixed disks
                    free, total = ctypes.c_uint64(), ctypes.c_uint64()
                    if k32.GetDiskFreeSpaceExW(root, ctypes.byref(free), ctypes.byref(total), None) and total.value:
                        out.append({"drive": root, "total_gb": round(total.value / 2**30, 1),
                                    "free_gb": round(free.value / 2**30, 1),
                                    "percent_used": round(100 * (1 - free.value / total.value), 1)})
            return out

        class Power(ctypes.Structure):
            _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("pct", ctypes.c_ubyte), ("saver", ctypes.c_ubyte),
                        ("life", w.DWORD), ("full", w.DWORD)]

        def battery():
            p = Power()
            if not k32.GetSystemPowerStatus(ctypes.byref(p)) or p.flag & 128 or p.pct == 255:
                return None  # no battery (a desktop PC)
            return {"percent": p.pct, "plugged_in": p.ac == 1}

        k32.GetTickCount64.restype = ctypes.c_uint64

        def uptime_hours():
            return round(k32.GetTickCount64() / 3.6e6, 2)
    else:
        def memory():
            info = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    info[k] = int(v.split()[0]) * 1024
            total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
            return {"total_gb": round(total / 2**30, 2), "used_gb": round((total - avail) / 2**30, 2),
                    "free_gb": round(avail / 2**30, 2), "percent": round(100 * (total - avail) / total, 1)}

        def _times():
            with open("/proc/stat") as f:
                v = [int(x) for x in f.readline().split()[1:]]
            return v[3] + v[4], sum(v)

        def disks():
            out = []
            for root in ("/", os.path.expanduser("~")):
                s = os.statvfs(root)
                total, free = s.f_blocks * s.f_frsize, s.f_bavail * s.f_frsize
                if total and not any(d["total_gb"] == round(total / 2**30, 1) for d in out):
                    out.append({"drive": root, "total_gb": round(total / 2**30, 1), "free_gb": round(free / 2**30, 1),
                                "percent_used": round(100 * (1 - free / total), 1)})
            return out

        def battery():
            import glob
            for b in glob.glob("/sys/class/power_supply/BAT*"):
                try:
                    with open(b + "/capacity") as f:
                        pct = int(f.read())
                    with open(b + "/status") as f:
                        st = f.read().strip()
                    return {"percent": pct, "plugged_in": st != "Discharging"}
                except (OSError, ValueError):
                    pass
            return None

        def uptime_hours():
            with open("/proc/uptime") as f:
                return round(float(f.read().split()[0]) / 3600, 2)

    def cpu_percent(seconds: float = 0.5):
        i1, t1 = _times()
        time.sleep(max(0.1, min(float(seconds), 5)))
        i2, t2 = _times()
        return round(100 * (1 - (i2 - i1) / max(1, t2 - t1)), 1)

    def info():
        import platform
        return {"os": f"{platform.system()} {platform.release()}", "machine": platform.machine(),
                "cpu_cores": os.cpu_count(), "python": platform.python_version()}

    return types.SimpleNamespace(cpu_percent=cpu_percent, memory=memory, disks=disks, battery=battery,
                                 uptime_hours=uptime_hours, info=info)


# ---------------------------------------------------------------- the locks
def _lock_down() -> None:
    """At most MEMORY_MB of memory and no child processes, for this process."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as w
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = w.HANDLE
        k32.GetCurrentProcess.restype = w.HANDLE

        class Basic(ctypes.Structure):
            _fields_ = [("user_time", ctypes.c_int64), ("job_time", ctypes.c_int64), ("flags", w.DWORD),
                        ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t), ("procs", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", ctypes.c_uint64 * 6), ("proc_mem", ctypes.c_size_t),
                        ("job_mem", ctypes.c_size_t), ("peak_proc", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        info = Extended()
        info.basic.flags = 0x0100 | 0x0008 | 0x2000  # PROCESS_MEMORY | ACTIVE_PROCESS (1: no children) | KILL_ON_CLOSE
        info.basic.procs = 1
        info.proc_mem = MEMORY_MB << 20
        job = k32.CreateJobObjectW(None, None)
        if not (job and k32.SetInformationJobObject(w.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info))
                and k32.AssignProcessToJobObject(w.HANDLE(job), w.HANDLE(k32.GetCurrentProcess()))):
            raise SystemExit(json.dumps({"ok": False, "error": "the sandbox couldn't lock itself — nothing was run"}))
    else:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEMORY_MB << 20, MEMORY_MB << 20))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))


def _proxies() -> dict:
    """The allowed modules as the skill gets them: their public functions and classes only — never the modules they
    import themselves (uuid.os, statistics.sys, typing.sys would each be a way out)."""
    import importlib
    import types
    out = {}
    for name in sorted(ALLOWED - {"system"}) + ["collections.abc"]:
        try:
            mod = importlib.import_module(name)
        except ImportError:
            continue
        out[name] = types.SimpleNamespace(**{k: v for k, v in vars(mod).items()
                                             if not k.startswith("_") and not isinstance(v, types.ModuleType)})
    if "collections" in out and "collections.abc" in out:
        out["collections"].abc = out["collections.abc"]
    return out


def _builtins(system, proxies: dict) -> dict:
    import builtins

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "system":
            return system
        if level or name not in proxies:
            raise ImportError(f"“{name}” isn't allowed in the sandbox")
        return proxies[name] if fromlist else proxies[name.split(".")[0]]  # "import collections.abc" -> collections
    safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
    safe["__import__"] = guarded_import
    safe["__build_class__"] = builtins.__build_class__  # `class Foo:` in a skill
    safe["__name__"] = "skill"
    return safe


def main() -> None:
    path, mode, params_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(path, encoding="utf-8") as f:
        code = f.read()
    with open(params_path, encoding="utf-8") as f:
        params = json.load(f)
    bad = check(code)
    if bad:
        print(json.dumps({"ok": False, "error": "not allowed: " + "; ".join(bad), "check": bad}))
        return
    system, proxies = _system(), _proxies()  # loaded BEFORE the lock (importing reads files)
    _lock_down()
    printed: list[str] = []
    env = {"__builtins__": _builtins(system, proxies)}
    env["__builtins__"]["print"] = lambda *a, **k: printed.append(" ".join(str(x) for x in a))
    t0 = time.time()
    try:
        exec(compile(code, "skill.py", "exec"), env)  # noqa: S102 — checked above, and locked in
        if mode == "test":
            env["test"]()
            result = "the test passed"
        else:
            result = env["run"](**params)
        json.dumps(result)  # must be plain data (numbers, text, lists, dicts)
        out = {"ok": True, "result": result}
    except AssertionError as e:
        out = {"ok": False, "error": f"the test failed: {e}" if str(e) else "the test failed (an assert)"}
    except MemoryError:
        out = {"ok": False, "error": f"it used more than {MEMORY_MB} MB of memory"}
    except TypeError as e:
        out = {"ok": False, "error": f"TypeError: {e}"}
    except Exception as e:  # noqa: BLE001 — the skill's own error, with its line
        tb, line = e.__traceback__, None
        while tb:
            if tb.tb_frame.f_code.co_filename == "skill.py":
                line = tb.tb_lineno
            tb = tb.tb_next
        out = {"ok": False, "error": f"{type(e).__name__}: {e}" + (f" (line {line})" if line else "")}
    out["seconds"] = round(time.time() - t0, 2)
    out["printed"] = "\n".join(printed)[-2000:]
    print(json.dumps(out, default=str)[:60000])


if __name__ == "__main__":
    main()
