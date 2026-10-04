"""Tor, built in (engines/tor: the official Tor Expert Bundle, signature checked). The chat's web searches, pages,
pictures and videos go through the Tor network: the sites never see your address, and nobody on the way sees what
you search. Every search gets a fresh route (its own circuit), so searches can't be linked to each other. Site names
are looked up inside Tor too (SafeSocks refuses anything else). If Tor isn't connected, searching waits for it and
never goes around it. Tor starts with the app and stops with it; its folder (data/tor) only holds the public list
of Tor relays — nothing about you."""
import os
import secrets
import subprocess
import threading
import time

import httpx

from .config import DATA, ENGINES, LLM_PORT, LOGS, NO_WINDOW, load_settings
from .plat import exe, lib_env

PORT = LLM_PORT + 3  # 8774 (8771 chat, 8772 Laya, 8773 memory)
EXE = exe(ENGINES / "tor", "tor")
DIR = DATA / "tor"


def _q(p) -> str:
    return '"' + str(p).replace("\\", "\\\\") + '"'  # Windows path, backslashes escaped inside quotes


class Tor:
    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.progress = 0
        self.lock = threading.Lock()

    def available(self) -> bool:
        return EXE.exists()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def wanted(self) -> bool:
        s = load_settings()
        return self.available() and s.get("tor", True) and not s.get("web_proxy")

    def start(self) -> None:
        with self.lock:
            if self.running() or not self.available():
                return
            DIR.mkdir(parents=True, exist_ok=True)
            (DIR / "torrc").write_text("\n".join([
                f"SocksPort 127.0.0.1:{PORT}",
                f"DataDirectory {_q(DIR)}",
                f"GeoIPFile {_q(EXE.parent / 'geoip')}",
                f"GeoIPv6File {_q(EXE.parent / 'geoip6')}",
                "ClientOnly 1",           # only uses Tor, never relays traffic for others
                "SafeSocks 1",            # site names are resolved inside Tor: no lookups leak outside
                "AvoidDiskWrites 1",
                "Log notice stdout",      # progress only; Tor never logs where you go
                f"__OwningControllerProcess {os.getpid()}",  # Tor quits if the app is gone
            ]) + "\n", encoding="utf-8")
            self.progress = 0
            self.proc = subprocess.Popen([str(EXE), "-f", str(DIR / "torrc"), "--defaults-torrc", str(DIR / "none")],
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="ignore", creationflags=NO_WINDOW,
                                         env=lib_env(EXE.parent))
            threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        with open(LOGS / "tor.log", "w", encoding="utf-8") as log:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                if "Bootstrapped " in line:
                    try:
                        self.progress = int(line.split("Bootstrapped ")[1].split("%")[0])
                    except (IndexError, ValueError):
                        pass

    def stop(self) -> None:
        if self.running():
            self.proc.terminate()
        self.proc, self.progress = None, 0

    def ready(self, wait: float = 90) -> None:
        """Waits until Tor is connected; raises (so nothing is sent without it) if it can't connect."""
        self.start()
        end = time.time() + wait
        while self.progress < 100:
            if not self.running() or time.time() > end:
                raise httpx.ConnectError(f"Tor isn't connected ({self.progress}%) — nothing was sent. "
                                         "Check the internet connection and try again.")
            time.sleep(0.3)

    def proxy(self) -> str:
        """Fresh random login for each search = a separate Tor circuit for it (Tor isolates by login)."""
        return f"socks5://{secrets.token_hex(6)}:{secrets.token_hex(6)}@127.0.0.1:{PORT}"

    def status(self) -> dict:
        return {"available": self.available(), "on": self.wanted(), "running": self.running(), "progress": self.progress}


tor = Tor()
