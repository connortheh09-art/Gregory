"""Generation-bound IPC for ONE foreground capture. No commands or DB writes."""
import json
import math
import os
from pathlib import Path
import time
import uuid
from contextlib import contextmanager

from greg_capture_process import identity, require_identity


@contextmanager
def command_writer_lock(path):
    """Separate stdlib lifetime lock: Recorder remains optional in ordinary mode."""
    with Path(path).open('a+b') as handle:
        if os.name=='nt':
            import msvcrt
            if handle.seek(0,2)==0:handle.write(b'0');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            if os.name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)


class CaptureStopped(RuntimeError):
    pass


def write_json(path, value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    if path.is_symlink() or temporary.is_symlink():raise ValueError('symlinked capture status')
    with temporary.open('w',encoding='utf8') as out:
        json.dump(value,out,allow_nan=False);out.flush();os.fsync(out.fileno())
    if os.name=='nt' and path.exists():
        # MoveFileEx (used by os.replace) still refuses replacing an open target
        # on Windows. ReplaceFileW supports our delete-sharing read snapshots.
        import ctypes as C
        from ctypes import wintypes as W
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.ReplaceFileW.argtypes=[W.LPCWSTR,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_void_p,C.c_void_p]
        kernel.ReplaceFileW.restype=W.BOOL
        if not kernel.ReplaceFileW(str(path),str(temporary),None,0,None,None):
            raise C.WinError(C.get_last_error())
    else:os.replace(temporary,path)


@contextmanager
def _status_reader(path):
    """Permit atomic replacement while this read holds the old snapshot open.

    Windows CRT opens omit FILE_SHARE_DELETE; a simultaneous os.replace then
    fails with access denied despite correct ACLs. Request ordinary read access
    plus share-read/write/delete; no extra access or permission changes.
    """
    if os.name!='nt':
        with path.open('rb') as source:yield source
        return
    import ctypes as C
    from ctypes import wintypes as W
    import msvcrt
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
    kernel.CreateFileW.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    handle=kernel.CreateFileW(str(path),0x80000000,7,None,3,0x200000,None)
    if handle==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
    try:fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle);raise
    with os.fdopen(fd,'rb') as source:yield source


def read_json(path):
    path=Path(path)
    # ReplaceFileW can briefly return PATH-MISSING or SHARING-VIOLATION to
    # concurrent opens even with delete-sharing. Only those observed Windows
    # races get a small total read budget. Never reuse cached content, renew
    # its timestamps, retry access-denied, or bypass downstream identity/age.
    deadline=time.monotonic()+.1
    while True:
        if path.is_symlink():raise ValueError('symlinked capture input')
        try:
            with _status_reader(path) as source:raw=source.read(65537)
            break
        except OSError as exc:
            if (os.name!='nt' or getattr(exc,'winerror',None) not in (2,32)
                    or time.monotonic()>=deadline):raise
            time.sleep(.005)
    if len(raw)>65536:raise ValueError('oversized capture input')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('capture object required')
    return value


def fresh(stamp, now, budget):
    try:return type(stamp) in (int,float) and math.isfinite(stamp) and 0<=now-stamp<=budget
    except OverflowError:return False


def binding(value):
    return {k:value[k] for k in ('trial','supervisor','game','bridge','started_utc','recorder_db')}


def validate_control(value, *, trial, bridge, pinned=None, now=None):
    now=time.time() if now is None else now
    if (value.get('kind')!='gregory.capture.control.v1' or value.get('trial')!=trial or
            value.get('bridge')!=bridge or value.get('ok') is not True or
            not fresh(value.get('utc'),now,3) or type(value.get('baseline_ready')) is not bool or
            type(value.get('stop_requested')) is not bool):
        raise CaptureStopped('capture supervisor stale, failed or wrong generation')
    try:
        current=binding(value)
        if pinned is not None and current!=pinned:raise CaptureStopped('capture binding changed')
        if value['sample_utc'] is None:
            if value['baseline_ready'] or not fresh(value['started_utc'],now,15):
                raise CaptureStopped('first complete sample unavailable')
        elif not fresh(value['sample_utc'],now,15):
            raise CaptureStopped('last completed sample stale')
    except KeyError as exc:raise CaptureStopped('incomplete capture control') from exc
    if value['stop_requested']:raise CaptureStopped('supervisor requested stop')
    return current


def healthy_recorder(health):
    return (health.get('status')=='ready' and health.get('thread_alive') is True and
        all(type(health.get(k)) is int and health[k]==0
            for k in ('dropped','invalid','errors','quarantined')))


def validate_health(value, *, trial, bridge, recorder_db, pinned_run=None, now=None):
    now=time.time() if now is None else now
    if (value.get('kind')!='gregory.capture.health.v1' or value.get('trial')!=trial or
            value.get('bridge')!=bridge or value.get('writer_owned') is not True or
            value.get('recorder_db')!=str(Path(recorder_db).resolve()) or
            not fresh(value.get('utc'),now,3) or not isinstance(value.get('run_id'),str) or
            not value['run_id'] or (pinned_run is not None and value['run_id']!=pinned_run)):
        raise CaptureStopped('bridge/recorder health stale or unbound')
    if value.get('phase')=='running' and not healthy_recorder(value.get('recorder',{})):
        raise CaptureStopped('Recorder writer dead or unhealthy')
    if value.get('phase') not in ('running','closed','incomplete'):
        raise CaptureStopped('invalid bridge lifecycle')
    return value['run_id']


class CaptureGate:
    """Called on the writer/main thread; data-only producer threads cannot use it.

    The caller holds the OS cmd.writer.lock for the complete bridge lifetime.
    Parent process generation + trial identity remain pinned after first receipt.
    """
    def __init__(self, control, health, trial):
        if uuid.UUID(trial).hex!=trial:raise ValueError('canonical trial UUID required')
        self.control=Path(control);self.health=Path(health);self.trial=trial
        if (self.health.exists() or self.health.is_symlink() or
                self.health.parent.resolve()!=self.control.parent.resolve()):
            raise ValueError('fresh private health path beside control required')
        self.bridge=identity(os.getpid());self.pinned=None;self.created=time.monotonic()
        self.last_publish=None;self.recorder=None

    def _publish(self, *, force=False, receipt=None):
        now=time.monotonic()
        if not force and self.last_publish is not None and now-self.last_publish<.5:return
        health=self.recorder.health()
        value=dict(kind='gregory.capture.health.v1',trial=self.trial,bridge=self.bridge,
            recorder_db=str(self.recorder.path.resolve()),run_id=self.recorder.run_id,
            recorder=health,writer_owned=True,utc=time.time(),phase='running')
        if receipt is not None:
            value.update(phase='closed' if receipt.get('fully_drained') else 'incomplete',final=receipt)
        write_json(self.health,value);self.last_publish=now

    def check(self, recorder):
        self.recorder=recorder
        if not healthy_recorder(recorder.health()):raise CaptureStopped('Recorder thread unavailable')
        self._publish()
        try:value=read_json(self.control)
        except FileNotFoundError:
            if self.pinned is None and time.monotonic()-self.created<=10:return False
            raise CaptureStopped('supervisor control missing') from None
        current=validate_control(value,trial=self.trial,bridge=self.bridge,pinned=self.pinned)
        require_identity(value['supervisor'])
        require_identity(value['game'])
        if str(recorder.path.resolve())!=value['recorder_db']:raise CaptureStopped('Recorder path rebound')
        self.pinned=current
        return value['baseline_ready']

    def await_baseline(self, recorder):
        started=time.monotonic()
        while time.monotonic()-started<=135:
            if self.check(recorder):return
            time.sleep(.1)
        raise CaptureStopped('full inactive baseline unavailable')

    def finish(self, recorder, receipt, *, primary=None):
        try:
            self.recorder=recorder;self._publish(force=True,receipt=receipt)
        except BaseException as exc:
            if primary is None:raise
            if hasattr(primary,'add_note'):
                primary.add_note('capture health publication failed: '+type(exc).__name__)
