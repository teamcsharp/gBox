"""Short, verified process-identity-bound freezes for native data transactions.

Windows holds every existing emulator thread, including UI threads, only while
performing memory work. No window messages or other blocking UI calls belong
inside the context. Every exit attempts to balance all successful suspensions;
unrecoverable OS resume failures are reported explicitly.
"""
from contextlib import contextmanager
import os


class _WindowsThreads:
    def __init__(self):
        import ctypes as C
        from ctypes import wintypes as W
        self.C, self.W = C, W
        k = self.k = C.WinDLL("kernel32", use_last_error=True)
        class Entry(C.Structure):
            _fields_ = [("size", W.DWORD), ("usage", W.DWORD), ("tid", W.DWORD),
                        ("pid", W.DWORD), ("priority", C.c_long),
                        ("delta", C.c_long), ("flags", W.DWORD)]
        self.Entry = Entry
        for name, args, result in (
            ("CreateToolhelp32Snapshot", [W.DWORD,W.DWORD], W.HANDLE),
            ("Thread32First", [W.HANDLE,C.POINTER(Entry)], W.BOOL),
            ("Thread32Next", [W.HANDLE,C.POINTER(Entry)], W.BOOL),
            ("OpenThread", [W.DWORD,W.BOOL,W.DWORD], W.HANDLE),
            ("GetProcessIdOfThread", [W.HANDLE], W.DWORD),
            ("SuspendThread", [W.HANDLE], W.DWORD),
            ("ResumeThread", [W.HANDLE], W.DWORD),
            ("CloseHandle", [W.HANDLE], W.BOOL),
        ):
            fn=getattr(k,name);fn.argtypes=args;fn.restype=result

    def threads(self,pid):
        snap=self.k.CreateToolhelp32Snapshot(4,0)
        if snap in (None,0,self.C.c_void_p(-1).value):raise OSError("Cannot enumerate emulator threads")
        try:
            entry=self.Entry();entry.size=self.C.sizeof(entry);out=[]
            more=self.k.Thread32First(snap,self.C.byref(entry))
            if not more:raise OSError("Cannot read emulator thread snapshot")
            while more:
                if entry.pid==pid:out.append(entry.tid)
                if len(out)>4096:raise RuntimeError("Unexpected emulator thread count")
                more=self.k.Thread32Next(snap,self.C.byref(entry))
            if self.C.get_last_error()!=18:raise OSError("Incomplete emulator thread snapshot")
            return out
        finally:self.k.CloseHandle(snap)

    def open(self,tid):
        handle=self.k.OpenThread(0x0002|0x0800,False,tid)
        if not handle:raise OSError("Cannot hold every emulator thread")
        return handle
    def owner(self,handle):return self.k.GetProcessIdOfThread(handle)
    def suspend(self,handle):
        count=self.k.SuspendThread(handle)
        if count==0xffffffff:raise OSError("Cannot suspend every emulator thread")
        return count
    def resume(self,handle):
        if self.k.ResumeThread(handle)==0xffffffff:raise OSError("Cannot release emulator thread suspension")
    def close(self,handle):self.k.CloseHandle(handle)


@contextmanager
def _hold_windows(api,expected,identity):
    """Retain handles rather than resuming possibly reused thread IDs."""
    held=[];release_errors=[]
    try:
        if identity()!=expected:raise RuntimeError("Emulator process identity changed")
        tids=api.threads(expected[0])
        if not tids or len(tids)>4096 or len(set(tids))!=len(tids):
            raise RuntimeError("Invalid emulator thread inventory")
        for tid in tids:
            handle=api.open(tid)
            try:
                if api.owner(handle)!=expected[0]:raise RuntimeError("Emulator thread changed owner")
                api.suspend(handle)
            except BaseException:
                api.close(handle);raise
            held.append(handle)
        if identity()!=expected or set(api.threads(expected[0]))!=set(tids):
            raise RuntimeError("Emulator threads changed during suspension; no memory edit allowed")
        yield
    finally:
        for handle in reversed(held):
            try:
                try:api.resume(handle)
                except OSError:api.resume(handle)  # retry only a failed, non-decrementing API call
            except BaseException as exc:release_errors.append(str(exc))
            finally:api.close(handle)
        if release_errors:
            raise RuntimeError("Emulator thread release failed: "+"; ".join(release_errors))


@contextmanager
def memory_guard(memory, timeout=2.0):
    lock = getattr(memory, 'lock', None)
    if lock is None or not lock.acquire(timeout=timeout):
        raise RuntimeError("Dolphin memory is busy; no inventory command was queued")
    try: yield
    finally: lock.release()


@contextmanager
def frozen(adapter):
    import psutil
    proc=getattr(adapter,"proc",None)
    if getattr(adapter,"name",None)!="dolphin" or proc is None or proc.poll() is not None:
        raise RuntimeError("An owned running Dolphin process is required")
    pid=proc.pid
    def identity():return (pid,psutil.Process(pid).create_time())
    expected=identity()
    if os.name=="nt":
        memory = adapter.debugger()
        if not hasattr(memory, 'lock'):
            raise RuntimeError("A synchronized direct-memory adapter is required")
        with memory_guard(memory):
            with _hold_windows(_WindowsThreads(),expected,identity):yield expected
    else:
        raise RuntimeError("Strict native inventory transactions currently require Windows Dolphin; the existing GDB halt helper does not prove a stop acknowledgement")
