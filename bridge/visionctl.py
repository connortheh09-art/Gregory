#!/usr/bin/env python3
"""visionctl — start/stop/status for the constant-vision sensor on the PC.

  python visionctl.py start [--interval 2] [--threshold 5] [--model qwen/qwen3-vl-8b]
  python visionctl.py status
  python visionctl.py stop

Runs vision_loop.py detached (no console) so it survives the shell, writes a pid
file and a log. Companion to gregctl.py for the voice bot.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(r"C:\Users\Conman\Downloads\openclaw")
LOOP = BASE / "vision_loop.py"
SUP = BASE / "vision_supervisor.py"
VDIR = BASE / "vision"
PID = VDIR / "vision.pid"
LOG = VDIR / "vision_loop.log"

DETACHED = 0x00000008          # DETACHED_PROCESS
NO_WINDOW = 0x08000000         # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200         # CREATE_NEW_PROCESS_GROUP


def alive(pid: int) -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except Exception:
        return False
    return str(pid) in out


def read_pid() -> int | None:
    if PID.exists():
        try:
            return int(PID.read_text().strip())
        except ValueError:
            return None
    return None


def do_start(a) -> int:
    pid = read_pid()
    if pid and alive(pid):
        print(f"already running (pid {pid})")
        return 0
    VDIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(SUP),
           "--interval", str(a.interval),
           "--threshold", str(a.threshold),
           "--model", a.model]
    if a.prompt_file:
        cmd += ["--prompt-file", a.prompt_file]
    if a.save_frames:
        cmd.append("--save-frames")
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"\n--- start {__import__('datetime').datetime.now().isoformat(timespec='seconds')} ---\n")
        p = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=DETACHED | NO_WINDOW | NEW_GROUP,
                             cwd=str(BASE), close_fds=True)
    PID.write_text(str(p.pid))
    print(f"started supervisor pid {p.pid}; log -> {LOG}")
    return 0


def do_stop() -> int:
    pid = read_pid()
    if not pid:
        print("not running (no pid file)")
        return 0
    if alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True, timeout=20)
        print(f"stopped pid {pid}")
    else:
        print(f"stale pid {pid} (not running)")
    try:
        PID.unlink()
    except OSError:
        pass
    return 0


def do_status() -> int:
    pid = read_pid()
    if pid and alive(pid):
        print(f"RUNNING pid {pid}")
        if LOG.exists():
            tail = LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
            for line in tail:
                print("   " + line)
    else:
        print("STOPPED")
    state = VDIR / "vision_state.log"
    if state.exists():
        lines = state.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        print(f"captions logged: {len(lines)}")
        if lines:
            print("   last: " + lines[-1])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--interval", type=float, default=2.0)
    s.add_argument("--threshold", type=int, default=5)
    s.add_argument("--model", default="auto",
                   help="'auto' = use whatever LM Studio already has loaded")
    s.add_argument("--save-frames", action="store_true")
    s.add_argument("--prompt-file", default="",
                   help="caption question file (e.g. minecraft_prompt.txt)")
    sub.add_parser("stop")
    sub.add_parser("status")
    a = ap.parse_args()
    if a.cmd == "start":
        return do_start(a)
    if a.cmd == "stop":
        return do_stop()
    return do_status()


if __name__ == "__main__":
    raise SystemExit(main())
