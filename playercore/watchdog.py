"""Watchdog for the local Greg voice bot.

The bot prints a `[hb]` heartbeat every 20s while alive. If the log stops
growing, the process is hung / fell out of the VC -> kill and restart it.

Run detached:  python watchdog.py
"""
import os
import subprocess
import time

HERE = os.environ.get("GREG_HOME", os.path.dirname(os.path.abspath(__file__)))

def _find(name):
    """Repo split: runtime files sit beside us, voice/ holds gdiscord.py."""
    for p in (os.path.join(HERE, name), os.path.join(HERE, os.pardir, "voice", name)):
        if os.path.exists(p):
            return os.path.abspath(p)
    return os.path.join(HERE, name)

LOG = os.path.join(HERE, "gdiscord.log")
SCRIPT = _find("gdiscord.py")
KILL = os.path.join(HERE, "killgdiscord.ps1")
WLOG = os.path.join(HERE, "watchdog.log")

STALE = 60      # log older than this = dead
CHECK = 15      # poll interval
MAX_RESTARTS = 3
WINDOW = 600    # rolling window for the restart cap
DETACHED = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


def wlog(msg):
    try:
        with open(WLOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def start_bot():
    logf = open(LOG, "a")
    subprocess.Popen(["python", SCRIPT], cwd=HERE, stdout=logf,
                     stderr=subprocess.STDOUT, creationflags=DETACHED, close_fds=True)


def kill_bot():
    try:
        subprocess.call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                         "-File", KILL], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, timeout=90)
    except Exception as e:
        wlog("kill err %r" % (e,))


wlog("watchdog up (stale=%ds check=%ds)" % (STALE, CHECK))
restarts = []

while True:
    time.sleep(CHECK)
    try:
        age = time.time() - os.path.getmtime(LOG)
    except OSError:
        age = 1e9

    if age <= STALE:
        continue

    now = time.time()
    recent = [t for t in restarts if now - t < WINDOW]
    if len(recent) >= MAX_RESTARTS:
        wlog("log stale %.0fs but %d restarts in %dmin - backing off 5min"
             % (age, len(recent), WINDOW // 60))
        time.sleep(300)
        continue

    wlog("log stale %.0fs -> restarting bot" % age)
    kill_bot()
    time.sleep(3)
    try:
        if os.path.exists(LOG):
            os.remove(LOG)
    except OSError:
        pass
    start_bot()
    restarts = recent + [now]
    time.sleep(25)
