#!/usr/bin/env python3
"""Windows read-only sampler. Source only: not yet target-qualified.

No kill, restart or reconnect logic. On failure writes ok=false; collector's
heartbeat gate stops the lane, and the supervisor closes the game normally.
"""
import argparse
from contextlib import closing
import csv
import ctypes
from ctypes import wintypes as w
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gregory_core.canary_preflight import Monitor


def process_memory(pid):
    if os.name != 'nt': raise RuntimeError('Windows sampler requires target qualification')
    class Counters(ctypes.Structure):
        _fields_ = [('cb', w.DWORD), ('PageFaultCount', w.DWORD)] + [(name, ctypes.c_size_t) for name in (
            'PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage',
            'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage', 'PrivateUsage')]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]; kernel.OpenProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
    handle = kernel.OpenProcess(0x410, False, pid)
    if not handle: raise ctypes.WinError(ctypes.get_last_error())
    try:
        counters = Counters(); counters.cb = ctypes.sizeof(counters)
        created, exited, kern, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kern), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), ctypes.sizeof(counters)):
            raise ctypes.WinError(ctypes.get_last_error())
        return dict(pid=pid, start=(created.dwHighDateTime << 32) | created.dwLowDateTime,
                    ws=counters.WorkingSetSize, private=counters.PrivateUsage)
    finally: kernel.CloseHandle(handle)


def available_memory():
    if os.name != 'nt': raise RuntimeError('Windows sampler requires target qualification')
    class Status(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('load', w.DWORD)] + [(name, ctypes.c_ulonglong) for name in (
            'total', 'available', 'total_page', 'available_page', 'total_virtual', 'available_virtual', 'extended')]
    status = Status(); status.length = ctypes.sizeof(status)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Status)]
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)): raise ctypes.WinError(ctypes.get_last_error())
    return status.available


def last_state(path):
    with Path(path).open('rb') as handle:
        handle.seek(0, 2); size = handle.tell(); handle.seek(max(0, size - 262144))
        lines = handle.read(262144).splitlines()
    for line in reversed(lines):
        try:
            value = json.loads(line)
            if isinstance(value, dict): return value
        except (ValueError, UnicodeError): continue
    raise ValueError('no readable state sample')


def atomic_status(path, value):
    path = Path(path); temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf8') as handle:
        json.dump(value, handle); handle.flush(); os.fsync(handle.fileno())
    os.replace(temporary, path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('game-pid', 'bridge-pid'): p.add_argument('--'+flag, type=int, required=True)
    for flag in ('csv', 'status', 'state', 'recorder-db', 'active-marker', 'supervisor-marker'):
        p.add_argument('--'+flag, required=True)
    a = p.parse_args()
    # Explicit PIDs must be discovered/reviewed at Gate B/C, never guessed here.
    if a.game_pid <= 0 or a.bridge_pid <= 0 or a.game_pid == a.bridge_pid: p.error('distinct discovered PIDs required')
    if Path(a.status).exists(): p.error('fresh status path required')
    if Path(a.active_marker).exists(): p.error('sampler must start before the active marker exists')
    monitor = Monitor(); started = time.monotonic(); active_started = None
    source = Path(a.recorder_db).resolve()
    fields = ['utc', 'elapsed', 'active', 'game_pid', 'game_start', 'game_ws', 'game_private',
        'bridge_pid', 'bridge_start', 'bridge_ws', 'bridge_private', 'available', 'state_age',
        'alive', 'supervised', 'recorder_ok', 'map', 'gamemode', 'recorder_bytes', 'wal_bytes', 'event_count']
    with Path(a.csv).open('x', newline='', encoding='utf8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); handle.flush()
        try:
            while True:
                elapsed = time.monotonic() - started
                if Path(a.active_marker).exists() and active_started is None: active_started = time.monotonic()
                game, bridge = process_memory(a.game_pid), process_memory(a.bridge_pid)
                state = last_state(a.state)
                with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=.25)) as db:
                    count = db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
                    bad = db.execute("SELECT COUNT(*) FROM events WHERE event_type IN ('recorder.loss','recorder.degraded')").fetchone()[0]
                sample = dict(elapsed=elapsed, active=0 if active_started is None else time.monotonic() - active_started,
                    game_pid=game['pid'], game_start=game['start'], game_ws=game['ws'], game_private=game['private'],
                    bridge_pid=bridge['pid'], bridge_start=bridge['start'], bridge_ws=bridge['ws'], bridge_private=bridge['private'],
                    available=available_memory(), state_age=time.time() - state['serverTime'],
                    alive=state.get('dead') is False, supervised=Path(a.supervisor_marker).is_file(), recorder_ok=not bad)
                status = monitor.accept(sample)
                row = dict(sample, utc=datetime.now(timezone.utc).isoformat(), map=state.get('map'), gamemode=state.get('mode'),
                    recorder_bytes=source.stat().st_size, wal_bytes=Path(str(source)+'-wal').stat().st_size if Path(str(source)+'-wal').exists() else 0,
                    event_count=count)
                writer.writerow(row); handle.flush(); os.fsync(handle.fileno())
                atomic_status(a.status, dict(kind='gregory.canary.monitor.v1', utc_seconds=time.time(),
                    bridge_pid=a.bridge_pid, ok=True, **status))
                time.sleep(5)
        except BaseException as exc:
            try:
                atomic_status(a.status, dict(kind='gregory.canary.monitor.v1', utc_seconds=time.time(),
                    bridge_pid=a.bridge_pid, baseline_ready=False, ok=False, stop_reason=type(exc).__name__))
            except BaseException as publication:
                # A broken status destination cannot replace the original cause.
                # Includes a SECOND interrupt during best-effort publication;
                # the original exception/interrupt is re-raised below, unchanged.
                # The consumer still fails closed when its heartbeat expires.
                try:
                    print(json.dumps(dict(type='monitor_failure_publication_failed',
                        original_error=type(exc).__name__, publication_error=type(publication).__name__)),
                        file=sys.stderr, flush=True)
                except BaseException:
                    pass
            raise


if __name__ == '__main__': main()
