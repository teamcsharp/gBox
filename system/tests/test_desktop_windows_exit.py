"""A signalled process handle proves exit even while its PID remains listed."""
import ctypes
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest

from gbox import desktop_supervisor as S


@pytest.mark.parametrize('handle,wait,error,exit_code,query_ok,expected', [
    (123, 0, 0, 259, True, True), (123, 258, 0, 259, True, False),
    (123, 258, 0, 15, True, True), (123, 0xffffffff, 5, 0, False, False),
    (0, 0, 87, 0, False, True), (0, 0, 5, 0, False, False), (0, 0, 6, 0, False, False),
])
def test_native_exit_check_keeps_denied_failed_and_live_processes_protected(monkeypatch, handle, wait, error, exit_code, query_ok, expected):
    opened, closed = [], []
    def get_code(h, out):
        out._obj.value = exit_code
        return query_ok
    kernel = SimpleNamespace(
        OpenProcess=lambda rights, inherit, pid: opened.append((rights, inherit, pid)) or handle,
        WaitForSingleObject=lambda h, ms: wait,
        GetExitCodeProcess=get_code,
        CloseHandle=lambda h: closed.append(h) or True)
    monkeypatch.setattr(S.sys, 'platform', 'win32')
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *a, **kw: kernel, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error, raising=False)
    assert S.windows_exited(456) is expected
    assert opened == [(0x00101000, False, 456)]  # no terminate/read-memory rights
    assert closed == ([123] if handle else [])


def test_wait_only_releases_confirmed_native_exits(monkeypatch):
    gone, live, denied = (SimpleNamespace(pid=p) for p in (1, 2, 3))
    monkeypatch.setattr(S.sys, 'platform', 'win32')
    monkeypatch.setattr(S, 'windows_exited', lambda pid: pid == 1)
    assert S.wait_processes([gone, live, denied], 0) == ([gone], [live, denied])


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows retained-handle regression')
def test_exited_python_with_retained_popen_handle_does_not_block_recovery():
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        process = psutil.Process(child.pid)
        witness = (process.pid, process.create_time())
        assert not S.windows_exited(child.pid)
        child.terminate()
        child.wait(timeout=5)
        # Popen still owns the handle here; PID disappearance is not required.
        assert S.windows_exited(child.pid)
        assert not S.same_process(process, witness)
        assert S.wait_processes([process], .2) == ([process], [])
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
