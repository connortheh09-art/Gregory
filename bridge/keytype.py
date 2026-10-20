"""keytype.py -- send a keystroke or a short ASCII string to the focused window.

Usage:
    py -3 keytype.py tilde
    py -3 keytype.py enter
    py -3 keytype.py type <one-token-text>

Uses SendInput; no third-party deps.
"""
import ctypes
import sys
import time
from ctypes import wintypes

PUL = ctypes.POINTER(ctypes.c_ulong)


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", PUL)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ki", KEYBDINPUT)]


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_TILDE = 0xC0      # OEM_3 (`/~)
VK_ENTER = 0x0D
VK_ESC = 0x1B


def _send(vk=0, scan=0, flags=0):
    inp = INPUT(type=1, ki=KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags,
                                      time=0, dwExtraInfo=None))
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def key(vk):
    _send(vk=vk)
    time.sleep(0.03)
    _send(vk=vk, flags=KEYEVENTF_KEYUP)


def type_text(s):
    for ch in s:
        cp = ord(ch)
        _send(scan=cp, flags=KEYEVENTF_UNICODE)
        _send(scan=cp, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(0.012)


def main():
    if len(sys.argv) < 2:
        print("usage: tilde | enter | esc | type <text>")
        return 2
    cmd = sys.argv[1].lower()
    if cmd == "tilde":
        key(VK_TILDE)
    elif cmd == "enter":
        key(VK_ENTER)
    elif cmd == "esc":
        key(VK_ESC)
    elif cmd == "type":
        type_text(sys.argv[2] if len(sys.argv) > 2 else "")
    else:
        print("unknown:", cmd)
        return 2
    print("sent:", cmd, sys.argv[2] if cmd == "type" and len(sys.argv) > 2 else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
