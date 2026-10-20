"""respawn_cam.py - keep the old PC's camera glued to Greg2.

Every time Greg2 dies and respawns, the spectator view on the other machine
detaches and just stares at a corpse. A dead camera means the vision loop
captions nothing useful and the voice brain talks nonsense.

This watches the bot's health via the bot API and, the moment he comes back,
tells the server (over RCON) to re-aim the spectator client at him. Server-side,
so nothing has to be typed or focused on the other PC.

  python respawn_cam.py
"""
from __future__ import annotations
import os

import socket
import struct
import time
from datetime import datetime
from pathlib import Path

import requests

STATE_URL = "http://127.0.0.1:18090/state"
PUSH_URL = os.environ.get("PUSH_URL", "http://127.0.0.1:18083/respawn_cam.txt")
LOG = Path(r"C:\Users\Conman\Downloads\openclaw\respawn_cam.log")

RCON_HOST, RCON_PORT, RCON_PASS = "127.0.0.1", 25575, "openclawmc"
WATCHER = "kailey_idk"
TARGET = "Greg2"
CMD = "execute as %s at @s run spectate %s" % (WATCHER, TARGET)


def log(msg: str) -> None:
    line = "%s %s" % (datetime.now().strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass
    try:
        requests.post(PUSH_URL, data=line.encode("utf-8"), timeout=8)
    except Exception:  # noqa: BLE001
        pass


def rcon(command: str) -> str:
    try:
        with socket.create_connection((RCON_HOST, RCON_PORT), timeout=6) as sock:
            def xchg(pid: int, ptype: int, body: str) -> bytes:
                data = struct.pack("<ii", pid, ptype) + body.encode("utf-8") + b"\x00\x00"
                sock.sendall(struct.pack("<i", len(data)) + data)
                raw = sock.recv(4)
                n = struct.unpack("<i", raw)[0]
                buf = b""
                while len(buf) < n:
                    buf += sock.recv(n - len(buf))
                return buf

            xchg(1, 3, RCON_PASS)          # auth
            resp = xchg(2, 2, command)     # command
            return resp[8:-2].decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return "RCON-ERR %r" % (exc,)


def health():
    try:
        return float(requests.get(STATE_URL, timeout=5).json().get("health", 0))
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    log("respawn-cam watcher start | %r" % CMD)
    # Retry the first attach until the server + RCON are actually up.
    for _ in range(60):
        res = rcon(CMD)
        log("initial attach -> " + repr(res))
        if not res.startswith("RCON-ERR"):
            break
        time.sleep(5)
    prev = health()
    last_sweep = time.time()
    while True:
        time.sleep(3)
        now = health()
        if now is None:
            continue
        if prev is not None and prev < 1 and now >= 1:
            log("respawn detected (health %.2f -> %.2f); re-aiming camera" % (prev, now))
            log("spectate -> " + repr(rcon(CMD)))
        # SAFETY SWEEP: a death can still slip past us (RCON down, process restarted),
        # and a camera left pointed at a death site will caption a void forever.
        # Re-asserting the attach is harmless, so just do it quietly on a timer.
        if time.time() - last_sweep > 90:
            last_sweep = time.time()
            res = rcon(CMD)
            if not res.startswith("Now spectating"):
                log("camera sweep: re-aim -> " + repr(res))
        prev = now


if __name__ == "__main__":
    main()
