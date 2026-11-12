"""Finite-capture process identity and Windows kill-on-close containment.

No elevation, process-name killing or service control. Linux identity support is
for offline subprocess probes only; the capture job itself is Windows-only.
"""
import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess


class JobChild:
    """Direct native child handles, with the small Popen interface we need."""
    def __init__(self,k,info,args):
        self.k=k;self.handle=info.process;self.thread=info.thread
        self.pid=info.pid;self.args=args;self.returncode=None

    def resume(self):
        result=self.k.ResumeThread(self.thread)
        if result==0xffffffff:raise C.WinError(C.get_last_error())
        if result!=1:raise RuntimeError('unexpected initial thread suspension count')
        self.k.CloseHandle(self.thread);self.thread=None

    def poll(self):
        if self.returncode is not None:return self.returncode
        result=self.k.WaitForSingleObject(self.handle,0)
        if result==258:return None
        if result!=0:raise C.WinError(C.get_last_error())
        code=W.DWORD()
        if not self.k.GetExitCodeProcess(self.handle,C.byref(code)):raise C.WinError(C.get_last_error())
        self.returncode=code.value;return self.returncode

    def wait(self,timeout=None):
        if timeout is None:raise ValueError('bounded child wait required')
        result=self.k.WaitForSingleObject(self.handle,min(0xfffffffe,max(0,int(timeout*1000))))
        if result==258:raise subprocess.TimeoutExpired(self.args,timeout)
        if result!=0:raise C.WinError(C.get_last_error())
        return self.poll()

    def kill(self):
        if self.poll() is None and not self.k.TerminateProcess(self.handle,1):
            raise C.WinError(C.get_last_error())

    def close(self):
        for key in ('thread','handle'):
            handle=getattr(self,key,None)
            if handle:self.k.CloseHandle(handle);setattr(self,key,None)


def _kernel():
    k = C.WinDLL('kernel32', use_last_error=True)
    k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; k.OpenProcess.restype = W.HANDLE
    k.CloseHandle.argtypes = [W.HANDLE]; k.CloseHandle.restype = W.BOOL
    k.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)]*4
    k.GetProcessTimes.restype = W.BOOL
    k.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    k.QueryFullProcessImageNameW.restype = W.BOOL
    k.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    k.GetExitCodeProcess.restype = W.BOOL
    return k


def _from_handle(k, handle, pid):
    code = W.DWORD()
    if not k.GetExitCodeProcess(handle, C.byref(code)): raise C.WinError(C.get_last_error())
    if code.value != 259: raise ProcessLookupError(pid)
    stamps = [W.FILETIME() for _ in range(4)]
    if not k.GetProcessTimes(handle, *(C.byref(s) for s in stamps)): raise C.WinError(C.get_last_error())
    text = C.create_unicode_buffer(32768); size = W.DWORD(len(text))
    if not k.QueryFullProcessImageNameW(handle, 0, text, C.byref(size)): raise C.WinError(C.get_last_error())
    return dict(pid=pid, start=(stamps[0].dwHighDateTime << 32)|stamps[0].dwLowDateTime,
                image=os.path.normcase(os.path.realpath(text.value)))


def identity(pid):
    if type(pid) is not int or not 0 < pid < 2**32: raise ValueError('bounded process PID required')
    if os.name != 'nt':
        # Never used by the Windows live runner. Allows real generation tests.
        root = Path('/proc')/str(pid)
        try:
            fields = (root/'stat').read_text().rsplit(')', 1)[1].split()
            if fields[0] == 'Z': raise ProcessLookupError(pid)
            return dict(pid=pid, start=int(fields[19]), image=os.path.realpath(root/'exe'))
        except FileNotFoundError: raise ProcessLookupError(pid) from None
    k = _kernel(); handle = k.OpenProcess(0x1000, False, pid)
    if not handle:
        if C.get_last_error() == 87: raise ProcessLookupError(pid)
        raise C.WinError(C.get_last_error())
    try: return _from_handle(k, handle, pid)
    finally: k.CloseHandle(handle)


def require_identity(expected):
    if not isinstance(expected, dict) or set(expected) != {'pid','start','image'}:
        raise ValueError('exact process identity required')
    if (type(expected['pid']) is not int or not 0 < expected['pid'] < 2**32 or
            type(expected['start']) is not int or not 0 < expected['start'] < 2**64 or
            not isinstance(expected['image'], str) or not expected['image']):
        raise ValueError('invalid process generation')
    if identity(expected['pid']) != expected: raise ValueError('process generation changed')


def read_arguments(expected):
    """Read-only handoff audit for one generation; caller keeps arguments private."""
    if os.name!='nt':raise RuntimeError('Windows handoff audit required')
    k=_kernel();handle=k.OpenProcess(0x1000,False,expected['pid'])
    if not handle:raise C.WinError(C.get_last_error())
    try:
        if _from_handle(k,handle,expected['pid'])!=expected:raise ValueError('audit process generation changed')
        nt=C.WinDLL('ntdll');shell=C.WinDLL('shell32')
        class Unicode(C.Structure):
            _fields_=[('length',W.USHORT),('maximum',W.USHORT),('buffer',C.c_void_p)]
        nt.NtQueryInformationProcess.argtypes=[W.HANDLE,W.ULONG,C.c_void_p,W.ULONG,C.POINTER(W.ULONG)]
        nt.NtQueryInformationProcess.restype=W.LONG
        shell.CommandLineToArgvW.argtypes=[W.LPCWSTR,C.POINTER(C.c_int)]
        shell.CommandLineToArgvW.restype=C.POINTER(W.LPWSTR)
        k.LocalFree.argtypes=[C.c_void_p];k.LocalFree.restype=C.c_void_p
        size=W.ULONG();nt.NtQueryInformationProcess(handle,60,None,0,C.byref(size))
        if not 0<size.value<=1024*1024:raise RuntimeError('unbounded audit arguments')
        buffer=C.create_string_buffer(size.value)
        if nt.NtQueryInformationProcess(handle,60,buffer,len(buffer),C.byref(size))!=0:
            raise RuntimeError('read-only handoff argument query failed')
        u=Unicode.from_buffer(buffer);text=C.wstring_at(u.buffer,u.length//2)
        count=C.c_int();argv=shell.CommandLineToArgvW(text,C.byref(count))
        if not argv:raise C.WinError(C.get_last_error())
        try:return [argv[i] for i in range(count.value)]
        finally:k.LocalFree(C.cast(argv,C.c_void_p))
    finally:k.CloseHandle(handle)


def bridge_processes():
    """Read-only enumeration; return bridge identities, never raw command lines."""
    if os.name != 'nt': raise RuntimeError('Windows bridge enumeration required')
    k = _kernel(); nt = C.WinDLL('ntdll'); shell = C.WinDLL('shell32')
    class Entry(C.Structure):
        _fields_ = [('size',W.DWORD),('usage',W.DWORD),('pid',W.DWORD),('heap',C.c_size_t),
            ('module',W.DWORD),('threads',W.DWORD),('parent',W.DWORD),('priority',W.LONG),
            ('flags',W.DWORD),('exe',W.WCHAR*260)]
    class Unicode(C.Structure):
        _fields_ = [('length',W.USHORT),('maximum',W.USHORT),('buffer',C.c_void_p)]
    k.CreateToolhelp32Snapshot.argtypes=[W.DWORD,W.DWORD]; k.CreateToolhelp32Snapshot.restype=W.HANDLE
    for name in ('Process32FirstW','Process32NextW'):
        fn=getattr(k,name); fn.argtypes=[W.HANDLE,C.POINTER(Entry)]; fn.restype=W.BOOL
    nt.NtQueryInformationProcess.argtypes=[W.HANDLE,W.ULONG,C.c_void_p,W.ULONG,C.POINTER(W.ULONG)]
    nt.NtQueryInformationProcess.restype=W.LONG
    shell.CommandLineToArgvW.argtypes=[W.LPCWSTR,C.POINTER(C.c_int)]
    shell.CommandLineToArgvW.restype=C.POINTER(W.LPWSTR)
    k.LocalFree.argtypes=[C.c_void_p]; k.LocalFree.restype=C.c_void_p
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot == C.c_void_p(-1).value: raise C.WinError(C.get_last_error())
    found=[]
    try:
        entry=Entry();entry.size=C.sizeof(entry);more=k.Process32FirstW(snapshot,C.byref(entry))
        while more:
            if entry.exe.lower() in ('python.exe','pythonw.exe'):
                handle=k.OpenProcess(0x1000,False,entry.pid)
                if not handle:
                    if C.get_last_error()!=87: raise C.WinError(C.get_last_error())
                else:
                    try:
                        size=W.ULONG();nt.NtQueryInformationProcess(handle,60,None,0,C.byref(size))
                        if not 0 < size.value <= 1024*1024: raise RuntimeError('unbounded process command')
                        buffer=C.create_string_buffer(size.value)
                        if nt.NtQueryInformationProcess(handle,60,buffer,len(buffer),C.byref(size)) != 0:
                            raise RuntimeError('process command query failed')
                        u=Unicode.from_buffer(buffer);text=C.wstring_at(u.buffer,u.length//2)
                        count=C.c_int();argv=shell.CommandLineToArgvW(text,C.byref(count))
                        if not argv: raise C.WinError(C.get_last_error())
                        try:
                            if any(Path(argv[i]).name.lower()=='gmod_bridge.py' for i in range(count.value)):
                                found.append(_from_handle(k,handle,entry.pid))
                        finally:k.LocalFree(C.cast(argv,C.c_void_p))
                    except ProcessLookupError: pass  # exited during read-only enumeration
                    finally:k.CloseHandle(handle)
            more=k.Process32NextW(snapshot,C.byref(entry))
    finally:k.CloseHandle(snapshot)
    return found


class WindowsJob:
    """Own ONLY reviewed game + capture processes. Parent death kills the job.

    Disarm is explicit and permitted only after a verified clean child exit and
    with exactly the original game remaining. Otherwise close is fail-closed.
    """
    def __init__(self):
        if os.name != 'nt': raise RuntimeError('capture containment requires Windows qualification')
        self.k = _kernel(); k=self.k
        class Basic(C.Structure):
            _fields_=[('process_time',C.c_int64),('job_time',C.c_int64),('flags',W.DWORD),
                ('min_ws',C.c_size_t),('max_ws',C.c_size_t),('active',W.DWORD),
                ('affinity',C.c_size_t),('priority',W.DWORD),('scheduling',W.DWORD)]
        class IO(C.Structure):
            _fields_=[(name,C.c_uint64) for name in ('read','write','other','read_bytes','write_bytes','other_bytes')]
        class Extended(C.Structure):
            _fields_=[('basic',Basic),('io',IO),('process_memory',C.c_size_t),('job_memory',C.c_size_t),
                ('peak_process',C.c_size_t),('peak_job',C.c_size_t)]
        self.limit_type=Extended
        k.CreateJobObjectW.argtypes=[C.c_void_p,W.LPCWSTR];k.CreateJobObjectW.restype=W.HANDLE
        k.SetInformationJobObject.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD]
        k.SetInformationJobObject.restype=W.BOOL
        k.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];k.AssignProcessToJobObject.restype=W.BOOL
        k.TerminateJobObject.argtypes=[W.HANDLE,W.UINT];k.TerminateJobObject.restype=W.BOOL
        k.QueryInformationJobObject.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]
        k.QueryInformationJobObject.restype=W.BOOL
        self.handle=k.CreateJobObjectW(None,None)
        if not self.handle: raise C.WinError(C.get_last_error())
        try:self._limits(0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        except BaseException:self.close();raise

    def _limits(self, flags):
        value=self.limit_type();value.basic.flags=flags
        if not self.k.SetInformationJobObject(self.handle,9,C.byref(value),C.sizeof(value)):
            raise C.WinError(C.get_last_error())

    def add(self, expected):
        handle=self.k.OpenProcess(0x100|0x1|0x1000,False,expected['pid'])
        if not handle:raise C.WinError(C.get_last_error())
        try:
            if _from_handle(self.k,handle,expected['pid'])!=expected:raise ValueError('job process generation changed')
            if not self.k.AssignProcessToJobObject(self.handle,handle):raise C.WinError(C.get_last_error())
        finally:self.k.CloseHandle(handle)

    def spawn_suspended(self,args,*,env,cwd,stdout):
        """CreateProcessW + JOB_LIST: no executable, unowned-child window.

        Windows 10+ assigns the job as part of creation. CREATE_SUSPENDED lets
        the parent pin identity/control before any bridge code can execute.
        No shell, credentials, elevation or fallback to uncontained Popen.
        Docs: learn.microsoft.com/windows/win32/api/processthreadsapi/
        nf-processthreadsapi-updateprocthreadattribute (JOB_LIST/HANDLE_LIST).
        """
        import msvcrt
        k=self.k
        class Startup(C.Structure):
            _fields_=[('cb',W.DWORD),('reserved',W.LPWSTR),('desktop',W.LPWSTR),('title',W.LPWSTR),
                ('x',W.DWORD),('y',W.DWORD),('width',W.DWORD),('height',W.DWORD),
                ('xchars',W.DWORD),('ychars',W.DWORD),('fill',W.DWORD),('flags',W.DWORD),
                ('show',W.WORD),('reserved_size',W.WORD),('reserved_data',C.c_void_p),
                ('stdin',W.HANDLE),('stdout',W.HANDLE),('stderr',W.HANDLE)]
        class StartupEx(C.Structure):
            _fields_=[('startup',Startup),('attributes',C.c_void_p)]
        class Info(C.Structure):
            _fields_=[('process',W.HANDLE),('thread',W.HANDLE),('pid',W.DWORD),('tid',W.DWORD)]
        k.InitializeProcThreadAttributeList.argtypes=[C.c_void_p,W.DWORD,W.DWORD,C.POINTER(C.c_size_t)]
        k.InitializeProcThreadAttributeList.restype=W.BOOL
        k.UpdateProcThreadAttribute.argtypes=[C.c_void_p,W.DWORD,C.c_size_t,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p]
        k.UpdateProcThreadAttribute.restype=W.BOOL
        k.DeleteProcThreadAttributeList.argtypes=[C.c_void_p]
        k.GetCurrentProcess.restype=W.HANDLE
        k.DuplicateHandle.argtypes=[W.HANDLE,W.HANDLE,W.HANDLE,C.POINTER(W.HANDLE),W.DWORD,W.BOOL,W.DWORD]
        k.DuplicateHandle.restype=W.BOOL
        k.CreateProcessW.argtypes=[W.LPCWSTR,W.LPWSTR,C.c_void_p,C.c_void_p,W.BOOL,W.DWORD,C.c_void_p,W.LPCWSTR,C.c_void_p,C.POINTER(Info)]
        k.CreateProcessW.restype=W.BOOL
        k.ResumeThread.argtypes=[W.HANDLE];k.ResumeThread.restype=W.DWORD
        k.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];k.WaitForSingleObject.restype=W.DWORD
        k.TerminateProcess.argtypes=[W.HANDLE,W.UINT];k.TerminateProcess.restype=W.BOOL
        if not self.handle:raise ValueError('closed job cannot launch a child')
        if not args or not Path(args[0]).is_absolute():raise ValueError('absolute executable required')
        if any('\0' in str(v) for v in args):raise ValueError('NUL in child arguments')
        if any('\0' in str(k)+str(v) or '=' in str(k)[1:] for k,v in env.items()):raise ValueError('invalid child environment')
        command=C.create_unicode_buffer(subprocess.list2cmdline([str(v) for v in args]))
        environment=C.create_unicode_buffer('\0'.join(str(key)+'='+str(value) for key,value in sorted(env.items(),key=lambda x:x[0].upper()))+'\0\0')
        size=C.c_size_t();k.InitializeProcThreadAttributeList(None,2,0,C.byref(size))
        if not 0<size.value<=65536:raise RuntimeError('invalid process attribute allocation')
        attributes=C.create_string_buffer(size.value);initialized=False;duplicates=[];info=Info();child=None
        try:
            if not k.InitializeProcThreadAttributeList(attributes,2,0,C.byref(size)):raise C.WinError(C.get_last_error())
            initialized=True;current=k.GetCurrentProcess()
            with open(os.devnull,'rb') as null:
                for file in (null,stdout):
                    duplicate=W.HANDLE()
                    if not k.DuplicateHandle(current,msvcrt.get_osfhandle(file.fileno()),current,C.byref(duplicate),0,True,2):
                        raise C.WinError(C.get_last_error())
                    duplicates.append(duplicate.value)
            handles=(W.HANDLE*2)(*duplicates);jobs=(W.HANDLE*1)(self.handle)
            for key,value in ((0x20002,handles),(0x2000d,jobs)):
                if not k.UpdateProcThreadAttribute(attributes,0,key,C.byref(value),C.sizeof(value),None,None):
                    raise C.WinError(C.get_last_error())
            startup=StartupEx();startup.startup.cb=C.sizeof(startup);startup.attributes=C.cast(attributes,C.c_void_p)
            startup.startup.flags=0x100;startup.startup.stdin=duplicates[0]
            startup.startup.stdout=startup.startup.stderr=duplicates[1]
            # EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT |
            # CREATE_SUSPENDED | CREATE_NO_WINDOW (no stray console UI).
            if not k.CreateProcessW(str(args[0]),command,None,None,True,0x8000000|0x80000|0x400|4,
                    environment,str(cwd),C.byref(startup),C.byref(info)):
                raise C.WinError(C.get_last_error())
            child=JobChild(k,info,args)
            if child.pid not in self.members():raise RuntimeError('kernel did not bind child to job')
            return child
        except BaseException as primary:
            if child is not None:
                try:child.kill();child.wait(timeout=2)
                except BaseException as secondary:primary.add_note('child cleanup: '+type(secondary).__name__)
                finally:child.close()
            raise
        finally:
            if initialized:k.DeleteProcThreadAttributeList(attributes)
            for handle in duplicates:k.CloseHandle(handle)

    def members(self):
        # Bounded native query: refuse unexpected process fan-out, never truncate.
        class Pids(C.Structure):
            _fields_=[('assigned',W.DWORD),('count',W.DWORD),('pids',C.c_size_t*128)]
        value=Pids()
        if not self.k.QueryInformationJobObject(self.handle,3,C.byref(value),C.sizeof(value),None):
            raise C.WinError(C.get_last_error())
        if value.assigned!=value.count or value.count>128:raise RuntimeError('incomplete job membership')
        return set(value.pids[:value.count])

    def disarm(self, game):
        require_identity(game)
        if self.members()!={game['pid']}:raise RuntimeError('capture producers still in job')
        self._limits(0)

    def terminate(self):
        if not self.k.TerminateJobObject(self.handle,1):raise C.WinError(C.get_last_error())

    def close(self):
        if getattr(self,'handle',None):
            self.k.CloseHandle(self.handle);self.handle=None
