#!/usr/bin/env python3
"""keyloop.py - vision -> mouse+keyboard controller with a LOOK->DECIDE->VERIFY->CLICK loop.

Garry's Mod's spawn menu is a pointing task, so this version does what a person does:
  1. LOOK and decide what to do (no clicking yet),
  2. MOVE the cursor to the chosen spot,
  3. LOOK AGAIN - with the big bright cursor visible in the frame - and check it is
     actually on the target,
  4. CLICK only once confirmed.

The cursor is deliberately huge and high-contrast in the game settings so the model can SEE
its own pointer and correct itself, instead of clicking and praying.

Keys are held across the whole decision so movement (and the Q spawn menu) never drops.

  python keyloop.py --goal-file keygoal.txt
  python keyloop.py --dry-run          # decide, never press/click (safe)
Stop: Ctrl+C or drop stop.flag. All keys released on exit.
"""
import argparse
import ctypes
import io
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
STOP_FLAG = os.path.join(HERE, "stop.flag")

SCAN = {
    "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20, "q": 0x10, "e": 0x12, "r": 0x13,
    "f": 0x21, "c": 0x2E, "g": 0x22, "z": 0x2C, "x": 0x2D, "t": 0x14, "tab": 0x0F,
    "1": 0x02, "2": 0x03, "3": 0x04, "4": 0x05, "5": 0x06,
    "space": 0x39, "shift": 0x2A, "ctrl": 0x1D, "alt": 0x38, "enter": 0x1C,
    "up": 0x48, "down": 0x50, "left": 0x4B, "right": 0x4D,
}
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
SM_CXSCREEN, SM_CYSCREEN = 0, 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]


_u32 = ctypes.windll.user32


def _key(scan, up):
    inp = INPUT(type=1, u=_INPUTunion(ki=KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0), 0, None)))
    _u32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def key_down(name):
    if name in SCAN:
        _key(SCAN[name], False)


def key_up(name):
    if name in SCAN:
        _key(SCAN[name], True)


MOUSE_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010)}


def mouse_btn(which, down):
    d, u = MOUSE_FLAGS.get(which, MOUSE_FLAGS["left"])
    _u32.mouse_event(d if down else u, 0, 0, 0, 0)


def mouse_click(which="left", hold=0.05):
    mouse_btn(which, True)
    time.sleep(hold)
    mouse_btn(which, False)


def mouse_abs(x, y):
    """Absolute move through the REAL input path (SetCursorPos teleports behind the game's
    back and its menus read that as a drag)."""
    vx = _u32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = _u32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(1, _u32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    vh = max(1, _u32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    nx = int((x - vx) * 65535 / max(1, vw - 1))
    ny = int((y - vy) * 65535 / max(1, vh - 1))
    _u32.mouse_event(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, nx, ny, 0, 0)


DEFAULT_PROMPT = (
    "You are controlling a PC game through its screen, mouse and keyboard.\n"
    "Your pointer is the BIG BRIGHT HIGH-CONTRAST arrow you can see drawn on the screen.\n"
    "Reply with ONLY a JSON object, no prose:\n"
    '  {"why":"short reason","keys":["q"],"aim":[x,y],"click":false}\n'
    "why   = one short phrase: what you are trying to do this moment.\n"
    "keys  = keys to HOLD. w/a/s/d move, space jumps, shift runs, q holds the Garry's Mod\n"
    "        spawn menu open, e uses.\n"
    "aim   = [x,y] as FRACTIONS 0..1 of THIS image (x across, y down) - where to put the cursor.\n"
    "click = true to left-click at that point.\n"
    "Plan before you click: look at the menu, find the exact row or icon you want, aim at it.\n"
    "Keep holding q the whole time the spawn menu is open. Never aim at the sky."
)

VERIFY_PROMPT = (
    "You are the same player, checking your aim. Your pointer is the BIG BRIGHT arrow.\n"
    'Reply with ONLY JSON: {"on_target":true|false,"click":true|false,"aim":[x,y]}\n'
    "- on_target = is your bright cursor sitting ON the thing you intended (menu row / icon)?\n"
    "- click = true ONLY if it is. If it is not, set click false.\n"
    "- aim = if you are off, give a CORRECTED [x,y] as 0..1 fractions of this image.\n"
    "Be honest. Do not click unless the cursor is actually on the target."
)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def load_prompt(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    return DEFAULT_PROMPT


def resolve_model(root):
    try:
        r = requests.get(root + "/api/v0/models", timeout=10).json()
        best = None
        for m in r.get("data", []):
            if m.get("state") != "loaded":
                continue
            if m.get("type") == "vlm" and "vl" in str(m.get("id", "")).lower():
                return m["id"]
            best = best or m.get("id")
        return best
    except Exception:  # noqa: BLE001
        return None


def ask(root, model, prompt, img_bytes, mime="image/jpeg"):
    import base64
    b64 = base64.b64encode(img_bytes).decode()
    body = {
        "model": model, "temperature": 0.3, "max_tokens": 100,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:" + mime + ";base64," + b64}},
        ]}],
    }
    r = requests.post(root + "/v1/chat/completions", json=body, timeout=120)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def grab(max_width):
    # The game lives on the PRIMARY monitor. Grab ONLY that rect - ImageGrab.grab() with no
    # bbox captures the WHOLE virtual desktop, so the model saw both screens and "the right
    # half of the image" was literally monitor 2, which is why it started clicking over there.
    # The Windows primary monitor is always at virtual (0,0), so this rect is safe.
    pw = _u32.GetSystemMetrics(SM_CXSCREEN)
    ph = _u32.GetSystemMetrics(SM_CYSCREEN)
    img = ImageGrab.grab(bbox=(0, 0, pw, ph))
    fw, fh = img.size
    if max_width and fw > max_width:
        img = img.resize((max_width, max(1, int(fh * max_width / fw))))
    iw, ih = img.size
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue(), fw, fh, iw, ih


def to_screen(ax, ay, fw, fh, iw, ih):
    if ax <= 1.5 and ay <= 1.5:
        # clamp: the model sometimes overshoots the 0..1 range (aim x=1.24 -> 3187px off-screen)
        ax = min(max(ax, 0.0), 1.0)
        ay = min(max(ay, 0.0), 1.0)
        return [ax * fw, ay * fh]              # 0..1 fractions (preferred)
    # Image PIXELS: only accept if actually inside the image we sent. A value outside it means the
    # model is confused about scale (e.g. full-screen 2560 px while we sent a 960 px frame) -
    # scaling that up lands off the monitor, so REJECT it instead (aim=None).
    if 0 <= ax <= iw and 0 <= ay <= ih:
        return [ax * fw / iw, ay * fh / ih]
    return None


def jparse(txt):
    m = re.search(r"\{.*\}", txt or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=0.15, help="min seconds per decision (floor)")
    ap.add_argument("--lm", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="auto")
    ap.add_argument("--prompt-file", default=os.path.join(HERE, "keyloop_prompt.txt"))
    ap.add_argument("--goal", default="Explore the map and move around.")
    ap.add_argument("--goal-file", default=os.path.join(HERE, "keygoal.txt"))
    ap.add_argument("--push-url", default="")
    ap.add_argument("--status-file", default=os.path.join(HERE, "keyloop_status.txt"),
                    help="local 'what my hands just did' feed for the voice bot (no network needed)")
    ap.add_argument("--max-width", type=int, default=960)
    ap.add_argument("--sticky", default="q", help="comma-separated keys held down for the WHOLE run (GMod needs Q held or the menu shuts)")
    ap.add_argument("--no-verify", action="store_true", help="skip the pre-click check (faster, sloppier)")
    ap.add_argument("--dry-run", action="store_true", help="decide but never press keys/clicks")
    ap.add_argument("--turns", type=int, default=0)
    a = ap.parse_args()

    model = resolve_model(a.lm) if a.model == "auto" else a.model
    if not model:
        log("no loaded model found - load one in LM Studio first")
        return 2
    pw = _u32.GetSystemMetrics(SM_CXSCREEN)
    ph = _u32.GetSystemMetrics(SM_CYSCREEN)
    vw = _u32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    vh = _u32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    log(f"keyloop start | model={model} | verify={not a.no_verify} | dry_run={a.dry_run}")
    log(f"screen: primary={pw}x{ph} | virtual desktop={vw}x{vh}"
        + (" | WARNING: multi-monitor - aiming/clicking on the PRIMARY only" if vw > pw or vh > ph else ""))

    prompt = load_prompt(a.prompt_file)
    sticky = [k.strip().lower() for k in a.sticky.split(",") if k.strip().lower() in SCAN]
    held = {"keys": [], "aim": None, "btn": None, "why": ""}
    history = []
    turn = 0
    try:
        # Sticky keys go down ONCE and stay down: releasing Q closes the spawn menu, which is
        # why the menu kept flickering shut between turns.
        if not a.dry_run:
            for k in sticky:
                key_down(k)
        if sticky:
            log("sticky keys held: " + ",".join(sticky))
        while True:
            if os.path.exists(STOP_FLAG):
                log("stop.flag seen - stopping")
                break
            turn += 1
            t0 = time.time()
            goal = a.goal
            try:
                if a.goal_file and os.path.exists(a.goal_file):
                    with open(a.goal_file, "r", encoding="utf-8", errors="replace") as f:
                        g = f.read().strip()
                    if g:
                        goal = g
            except Exception:  # noqa: BLE001
                pass

            # hold the previous decision's movement keys for the whole think (sticky keys already down)
            if not a.dry_run:
                for k in held["keys"]:
                    if k not in sticky:
                        key_down(k)

            # ---- PHASE 1: LOOK and DECIDE (no click yet) ----
            try:
                b1, fw, fh, iw, ih = grab(a.max_width)
                # MEMORY: without this it re-decides from zero every turn and never finishes a
                # sequence - it just right-clicks forever. Feed its own recent moves back in.
                hist = ""
                if history:
                    hist = ("WHAT YOU JUST DID (most recent last):\n" + "\n".join(history[-6:]) +
                            "\nContinue the sequence. If you just right-clicked, the dropdown is open"
                            " RIGHT NOW - do NOT right-click again; find the option and LEFT-click it.\n")
                reply = ask(a.lm, model, "YOUR GOAL RIGHT NOW: " + goal + "\n" + hist + prompt, b1)
                o = jparse(reply) or {}
                keys = [str(k).lower() for k in (o.get("keys") or [])
                        if str(k).lower() in SCAN and str(k).lower() not in sticky]
                aim = o.get("aim") if isinstance(o.get("aim"), (list, tuple)) else None
                btn = "right" if o.get("rclick") else ("left" if o.get("click") else None)
                act = {"keys": keys, "btn": btn, "why": str(o.get("why", ""))[:40], "aim": None}
                if aim and len(aim) == 2:
                    try:
                        act["aim"] = to_screen(float(aim[0]), float(aim[1]), fw, fh, iw, ih)
                    except (TypeError, ValueError):
                        act["aim"] = None
            except Exception as exc:  # noqa: BLE001
                log(f"brain unavailable ({exc}) - holding {a.interval}s")
                act = None

            # ---- PHASE 2: MOVE the cursor there ----
            if act:
                btn = act.get("btn")
                if not a.dry_run and act["aim"]:
                    mouse_abs(*act["aim"])
                    time.sleep(0.07)   # let the game register the move before any button

                # ---- PHASE 3: LOOK AGAIN and VERIFY before committing ----
                if btn and act["aim"] and not a.no_verify:
                    try:
                        b2, fw2, fh2, iw2, ih2 = grab(a.max_width)
                        v = jparse(ask(a.lm, model, VERIFY_PROMPT, b2)) or {}
                        on = bool(v.get("on_target"))
                        want = bool(v.get("click"))
                        vaim = v.get("aim")
                        corrected = False
                        if not a.dry_run and vaim and len(vaim) == 2 and act["aim"]:
                            try:
                                cx, cy = to_screen(float(vaim[0]), float(vaim[1]), fw2, fh2, iw2, ih2)
                                px, py = act["aim"]
                                # Only accept a NEARBY nudge. A "correction" that jumps a quarter of
                                # the screen is the verify model hallucinating, not fixing.
                                if abs(cx - px) < fw2 * 0.15 and abs(cy - py) < fh2 * 0.15:
                                    mouse_abs(cx, cy)
                                    time.sleep(0.05)
                                    act["aim"] = [cx, cy]
                                corrected = True
                            except (TypeError, ValueError):
                                pass
                        # COMMIT. Endless "not quite sure" spawns nothing. If it looked, said it
                        # was a bit off, and gave a corrected spot - go there AND click.
                        if on and want:
                            if not a.dry_run:
                                mouse_click(btn)
                            act["btn"] = btn.upper()
                        elif corrected:
                            if not a.dry_run:
                                mouse_click(btn)
                            act["btn"] = btn.upper() + "(corrected)"
                        else:
                            act["btn"] = "held(off-target)"
                    except Exception as exc:  # noqa: BLE001
                        log(f"verify failed ({exc})")
                        act["btn"] = "skipped"
                elif btn and act["aim"] and not a.dry_run:
                    mouse_click(btn)
                    act["btn"] = btn.upper() + "(no-verify)"
                elif btn:
                    # aim was rejected (model gave coords outside the frame). Do NOT click at a
                    # stale cursor position - that is click-and-pray. Skip and re-aim next turn.
                    act["btn"] = "no-aim(rejected)"

            if not a.dry_run:
                for k in held["keys"]:
                    if k not in sticky:
                        key_up(k)
            if act:
                held = act

            line = ("#%d %s aim=%s click=%s why=%r [%.2fs] goal=%r" % (
                turn, "+".join(held["keys"]) or "-",
                ("(%d,%d)" % (held["aim"][0], held["aim"][1])) if held.get("aim") else "-",
                held.get("btn"), held.get("why", ""), time.time() - t0, goal[:30]))
            desc = []
            if held["keys"]:
                desc.append("held " + "+".join(held["keys"]))
            if held.get("aim"):
                desc.append("moved cursor to (%d,%d)" % (held["aim"][0], held["aim"][1]))
            if held.get("btn"):
                desc.append(str(held["btn"]).lower() + "-clicked there")
            if held.get("why"):
                desc.append("intent: " + str(held["why"]))
            history.append("#%d %s" % (turn, "; ".join(desc) or "did nothing"))
            if len(history) > 8:
                del history[0]
            # Local hand-off for the voice bot: it runs on the SAME machine, so a plain file
            # beats a network round-trip (and the gateway upload/serve dirs don't match).
            if a.status_file:
                try:
                    with open(a.status_file, "w", encoding="utf-8") as sf:
                        sf.write(line + "\n")
                except OSError:
                    pass
            log(line)
            if a.push_url:
                try:
                    requests.post(a.push_url, data=line.encode("utf-8"), timeout=10)
                except Exception:  # noqa: BLE001
                    pass
            if a.turns and turn >= a.turns:
                break
            rest = a.interval - (time.time() - t0)
            if rest > 0:
                time.sleep(rest)
    except KeyboardInterrupt:
        log("interrupted")
    finally:
        for k in SCAN:
            try:
                key_up(k)
            except Exception:  # noqa: BLE001
                pass
        log("all keys released")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
