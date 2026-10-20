"""Greg Local control panel.

Usage:
    python gregctl.py start | stop | restart | status | rejoin
                       | reset | pause | resume | logs

Or just double-click greg.bat (opens a menu).
"""
import os
import subprocess
import sys
import time

HERE = os.environ.get("GREG_HOME", os.path.dirname(os.path.abspath(__file__)))

def _find(name):
    """Repo split: runtime files sit beside us, voice/ holds gdiscord.py."""
    for p in (os.path.join(HERE, name), os.path.join(HERE, os.pardir, "voice", name)):
        if os.path.exists(p):
            return os.path.abspath(p)
    return os.path.join(HERE, name)

BOT = _find("gdiscord.py")
WD = os.path.join(HERE, "watchdog.py")
BOTLOG = os.path.join(HERE, "gdiscord.log")
WDLOG = os.path.join(HERE, "watchdog.log")
FIND = os.path.join(HERE, "findproc.ps1")
KILLP = os.path.join(HERE, "killproc.ps1")
RESET = os.path.join(HERE, "reset.flag")
PAUSE = os.path.join(HERE, "paused.flag")
SHUTDOWN = os.path.join(HERE, "shutdown.flag")
VLOGS = os.path.join(HERE, "voice_logs")
DETACHED = 0x00000008 | 0x08000000

# ---- LM Studio: the bot's brain. Nothing else starts it. --------------------
LMS = r"C:\Users\Conman\.lmstudio\bin\lms.exe"
LM_MODEL = "qwen/qwen3-vl-8b"


def _lms(*args, timeout=300):
    try:
        r = subprocess.run([LMS, *args], capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return "LMS-ERROR: %r" % (e,)


def lm_loaded():
    return LM_MODEL in _lms("ps")


def ensure_lmstudio():
    print("lm studio: checking server...")
    st = _lms("server", "status")
    if "running" not in (st or "").lower():
        print("lm studio: starting server...")
        print(_lms("server", "start").strip())
        time.sleep(3)
    if lm_loaded():
        print("lm studio: %s already loaded" % LM_MODEL)
        return True
    print("lm studio: loading %s (first load takes a minute)..." % LM_MODEL)
    out = _lms("load", LM_MODEL, "--gpu", "max", "--context-length", "16384", "--parallel", "1", "--identifier", LM_MODEL, "-y", timeout=900)
    print((out or "").strip()[-400:])
    ok = lm_loaded()
    print("lm studio: " + ("READY" if ok else "FAILED TO LOAD"))
    return ok


def unload_lmstudio():
    if lm_loaded():
        print(_lms("unload", LM_MODEL).strip() or "lm studio: unloaded")
    else:
        print("lm studio: nothing loaded")



def _ps(script, *args):
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", script, *args],
                          capture_output=True, text=True, timeout=90)


def procs(match):
    out = []
    try:
        r = _ps(FIND, "-Match", match)
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line.isdigit():
                out.append(int(line))
    except Exception:
        pass
    return out


def start_bot():
    with open(BOTLOG, "a", encoding="utf-8") as f:
        subprocess.Popen(["python", BOT], cwd=HERE, stdout=f,
                         stderr=subprocess.STDOUT, creationflags=DETACHED, close_fds=True)


def start_watchdog():
    with open(WDLOG, "a", encoding="utf-8") as f:
        subprocess.Popen(["python", WD], cwd=HERE, stdout=f,
                         stderr=subprocess.STDOUT, creationflags=DETACHED, close_fds=True)


def stop(match):
    try:
        r = _ps(KILLP, "-Match", match)
        print((r.stdout or "").strip() or "(nothing running)")
    except Exception as e:
        print("stop failed:", e)


def last_hb():
    try:
        with open(BOTLOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-500:]
        for ln in reversed(lines):
            if "[hb]" in ln:
                return ln.strip()
    except Exception:
        pass
    return "(no heartbeat yet)"


def status():
    b = procs("gdiscord.py")
    w = procs("watchdog.py")
    print("bot      :", ("RUNNING pid " + ", ".join(map(str, b))) if b else "STOPPED")
    print("watchdog :", ("RUNNING pid " + ", ".join(map(str, w))) if w else "STOPPED")
    print("paused   :", "YES (not listening)" if os.path.exists(PAUSE) else "no")
    print("last hb  :", last_hb())


def logs(n=20):
    try:
        day = time.strftime("%Y-%m-%d")
        p = os.path.join(VLOGS, day + ".txt")
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            for ln in f.readlines()[-n:]:
                print(ln.rstrip())
    except Exception as e:
        print("no transcript:", e)


def do_stop():
    # watchdog first - otherwise it sees the bot go quiet and resurrects it
    stop("watchdog.py")
    with open(SHUTDOWN, "w", encoding="utf-8") as f:
        f.write("1")
    for _ in range(12):
        if not procs("gdiscord.py"):
            print("left the call cleanly")
            unload_lmstudio()
            return
        time.sleep(1)
    stop("gdiscord.py")
    print("force-killed (it was hanging)")
    unload_lmstudio()


def do_start():
    ensure_lmstudio()
    if not procs("gdiscord.py"):
        start_bot()
        print("bot starting...")
    else:
        print("bot already running")
    if not procs("watchdog.py"):
        start_watchdog()
        print("watchdog starting...")
    else:
        print("watchdog already running")
    time.sleep(6)
    status()


MENU = """Greg Local - pick one:
  1) start
  2) stop
  3) restart
  4) status
  5) reset history (cold start)
  6) pause listening
  7) resume listening
  8) show last transcript lines
  q) quit
"""


def main():
    cmd = (sys.argv[1].lower() if len(sys.argv) > 1 else "")
    if not cmd:
        print(MENU)
        cmd = (input("> ").strip() or "q").lower()
        cmd = {"1": "start", "2": "stop", "3": "restart", "4": "status", "5": "reset",
               "6": "pause", "7": "resume", "8": "logs", "q": "quit"}.get(cmd, cmd)

    if cmd == "start":
        try:
            os.remove(SHUTDOWN)
        except OSError:
            pass
        do_start()
    elif cmd == "stop":
        do_stop()
    elif cmd == "restart":
        do_stop()
        time.sleep(2)
        start_bot()
        print("restarting...")
        time.sleep(5)
        status()
    elif cmd == "status":
        status()
    elif cmd == "rejoin":
        print("forcing a clean rejoin...")
        do_stop()
        time.sleep(2)
        start_bot()
        time.sleep(5)
        status()
    elif cmd == "reset":
        open(RESET, "w").write("1")
        print("history will be wiped on the next thing it hears")
    elif cmd == "pause":
        open(PAUSE, "w").write("1")
        print("paused - it will not listen or reply until you resume")
    elif cmd == "resume":
        try:
            os.remove(PAUSE)
        except OSError:
            pass
        print("resumed - listening again")
    elif cmd == "lmload":
        ensure_lmstudio()
    elif cmd == "lmunload":
        unload_lmstudio()
    elif cmd == "logs":
        logs()
    elif cmd in ("q", "quit"):
        pass
    else:
        print("unknown command:", cmd)
        print(MENU)


if __name__ == "__main__":
    main()
    if len(sys.argv) == 1:
        input("\npress enter to close")
