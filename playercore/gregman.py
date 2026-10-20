#!/usr/bin/env python3
"""Greg Local - GUI manager.

Buttons for the things you actually do, plus a live status line and a log pane.
Thin skin over gregctl.py so there's exactly one source of truth.
"""
import os
import re
import subprocess
import sys
import threading
import time

try:
    import tkinter as tk
    from tkinter import scrolledtext, messagebox
except Exception as exc:  # noqa: BLE001
    print("tkinter unavailable: %r" % (exc,))
    raise SystemExit(1)

HERE = os.environ.get("GREG_HOME", os.path.dirname(os.path.abspath(__file__)))

def _find(name):
    """Repo split: runtime files sit beside us, voice/ holds gdiscord.py."""
    for p in (os.path.join(HERE, name), os.path.join(HERE, os.pardir, "voice", name)):
        if os.path.exists(p):
            return os.path.abspath(p)
    return os.path.join(HERE, name)

CTL = os.path.join(HERE, "gregctl.py")
BOTLOG = os.path.join(HERE, "gdiscord.log")
CTX = os.path.join(HERE, "greg_context.md")
CTX_URL = os.environ.get("CONTEXT_URL", "http://127.0.0.1:18082/greg_context.md")
BRAIN_URL = os.environ.get("BRAIN_URL", "http://127.0.0.1:18082/brain/")   # brain/ source files, served by the VPS daemon
PAUSE = os.path.join(HERE, "paused.flag")
PY = sys.executable or "python"
# Spawned helpers must not flash a console window (we run under pythonw).
NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

if "--selftest" in sys.argv:
    print("tkinter TkVersion =", tk.TkVersion)
    print("python  =", PY)
    print("here    =", HERE, "exists:", os.path.isdir(HERE))
    print("gregctl =", os.path.exists(CTL))
    raise SystemExit(0)


class Manager:
    def __init__(self, root):
        self.root = root
        self.busy = False
        root.title("Greg Local - Manager")
        root.geometry("880x560")

        bar = tk.Frame(root, padx=8, pady=8)
        bar.pack(fill="x")

        self.status = tk.StringVar(value="status: (loading...)")
        tk.Label(root, textvariable=self.status, anchor="w", justify="left",
                 font=("Consolas", 10), padx=8).pack(fill="x")

        buttons = [
            ("Start", self.on_start),
            ("Stop", self.on_stop),
            ("Restart", lambda: self.ctl("restart")),
            ("Rejoin VC", lambda: self.ctl("rejoin")),
            ("Status", lambda: self.ctl("status")),
            ("Pause", lambda: self.ctl("pause")),
            ("Resume", lambda: self.ctl("resume")),
            ("Reset history", self.on_reset),
            ("Reload brain", lambda: self.ctl("lmload")),
            ("Unload brain", lambda: self.ctl("lmunload")),
            ("Refresh context", self.on_refresh_ctx),
            ("Last transcript", lambda: self.ctl("logs")),
            ("Clear", self.on_clear),
            ("Open folder", self.on_open_folder),
            ("Open brain", self.on_open_brain),
        ]
        row = tk.Frame(bar)
        row.pack(fill="x")
        for i, (label, fn) in enumerate(buttons):
            tk.Button(row, text=label, width=14, command=fn).grid(
                row=i // 7, column=i % 7, padx=3, pady=3, sticky="ew")
        for c in range(7):
            row.columnconfigure(c, weight=1)

        tk.Label(root, text="output / log", anchor="w", padx=8).pack(fill="x")
        self.logtxt = scrolledtext.ScrolledText(root, height=22, font=("Consolas", 9),
                                               wrap="word")
        self.logtxt.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.say("Greg Local manager ready.")

        self.refresh_status()
        self.show_log_tail()

    # ---- plumbing ---------------------------------------------------------
    def say(self, text):
        self.logtxt.insert("end", text if text.endswith("\n") else text + "\n")
        self.logtxt.see("end")

    def run_bg(self, fn):
        if self.busy:
            self.say("(busy - wait for the current action)")
            return
        self.busy = True
        threading.Thread(target=lambda: (fn(), setattr(self, "busy", False)),
                         daemon=True).start()

    def ctl(self, *args):
        def job():
            self.say("> gregctl.py " + " ".join(args))
            try:
                r = subprocess.run([PY, CTL, *args], cwd=HERE, capture_output=True,
                                   text=True, timeout=900, creationflags=NO_WIN)
                out = (r.stdout or "") + (r.stderr or "")
                self.root.after(0, lambda: self.say(out.strip() or "(no output)"))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.say("ERROR: %r" % (exc,)))
            self.root.after(0, self.refresh_status)
        self.run_bg(job)

    def refresh_status(self):
        """Status straight from files + flags - NO subprocess.

        Spawning a console app every tick is what made Windows flash a
        terminal. Reading a file cannot flash, so the periodic path never
        shells out at all. The Status button still does a full gregctl check.
        """
        def job():
            hb_line = None
            try:
                with open(BOTLOG, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[-300:]
                for ln in reversed(lines):
                    if "[hb]" in ln:
                        hb_line = ln.strip()
                        break
            except OSError:
                pass

            try:
                age = time.time() - os.path.getmtime(BOTLOG)
                age_txt = "log %.0fs old" % age
                alive = age < 90
            except OSError:
                age_txt = "no log"
                alive = False

            txt = "bot: %s (%s) | paused: %s | last hb: %s" % (
                "ALIVE" if alive else "STALE",
                age_txt,
                "YES" if os.path.exists(PAUSE) else "no",
                hb_line or "(none yet)")
            self.root.after(0, lambda: self.status.set(txt))

        threading.Thread(target=job, daemon=True).start()
        self.root.after(5000, self.refresh_status)

    def show_log_tail(self):
        try:
            with open(BOTLOG, "r", encoding="utf-8", errors="replace") as fh:
                lines = [l.rstrip() for l in fh.readlines()[-25:]]
            self.say("--- last 25 lines of gdiscord.log ---")
            self.say("\n".join(lines))
        except OSError as exc:
            self.say("no bot log yet (%s)" % exc)

    # ---- actions ----------------------------------------------------------
    def on_start(self):
        self.ctl("start")

    def on_stop(self):
        if messagebox.askyesno("Stop Greg Local", "Stop the bot and watchdog?"):
            self.ctl("stop")

    def on_reset(self):
        if messagebox.askyesno("Reset history", "Wipe its conversation history on the next thing it hears?"):
            self.ctl("reset")

    def on_refresh_ctx(self):
        def job():
            tmp = CTX + ".tmp"
            try:
                r = subprocess.run(["curl", "-s", "-m", "20", "-o", tmp, CTX_URL],
                                   cwd=HERE, capture_output=True, text=True, timeout=45,
                                   creationflags=NO_WIN)
                size = os.path.getsize(tmp) if os.path.exists(tmp) else 0
                if size > 2000:
                    os.replace(tmp, CTX)
                    self.root.after(0, lambda: self.say("context refreshed (%d bytes)" % size))
                else:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    self.root.after(0, lambda: self.say("fetch short/failed (%d bytes) - kept old copy" % size))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: self.say("context error: %r" % (exc,)))
        self.run_bg(job)

    def on_clear(self):
        self.logtxt.delete("1.0", "end")
        self.say("pane cleared.")

    def on_open_brain(self):
        """Open the brain/ library in the browser (served off the VPS daemon).

        The mini-files live on the VPS, not on this PC - the bot only ever holds
        the built greg_context.md - so this is how you read/edit-check them
        without a shell.
        """
        try:
            os.startfile(BRAIN_URL)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self.say("open brain failed: %r" % (exc,))

    def on_open_folder(self):
        try:
            os.startfile(HERE)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            self.say("open folder failed: %r" % (exc,))


if __name__ == "__main__":
    root = tk.Tk()
    Manager(root)
    root.mainloop()
