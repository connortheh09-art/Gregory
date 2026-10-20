#!/usr/bin/env python3
"""Watchdog for the constant-vision loop: keeps vision_loop.py alive.

Any args passed here are forwarded to vision_loop.py. If the loop exits for any
reason (crash, AV, model reload), it is restarted after a short delay. Killing
this process's tree (taskkill /T) stops everything.
"""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\Users\Conman\Downloads\openclaw")
LOOP = BASE / "vision_loop.py"
RESTART_DELAY = 5


def log(msg: str) -> None:
    print(f"{datetime.now().strftime('%H:%M:%S')} [supervisor] {msg}", flush=True)


def main() -> int:
    forwarded = sys.argv[1:]
    log(f"starting; loop args={forwarded}")
    while True:
        started = time.time()
        try:
            p = subprocess.Popen([sys.executable, str(LOOP)] + forwarded, cwd=str(BASE))
        except Exception as exc:  # noqa: BLE001
            log(f"could not start loop: {exc}; retrying in {RESTART_DELAY}s")
            time.sleep(RESTART_DELAY)
            continue
        rc = p.wait()
        ran = time.time() - started
        log(f"loop exited rc={rc} after {ran:.0f}s; restarting in {RESTART_DELAY}s")
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    raise SystemExit(main())
