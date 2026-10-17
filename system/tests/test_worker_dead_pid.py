import psutil

from gbox import worker_results as W


def test_missing_pid_releases_denied_handle_hold(monkeypatch):
    def missing(pid):
        raise psutil.NoSuchProcess(pid)
    monkeypatch.setattr(psutil, 'Process', missing)
    assert W._windows_pid_reused_fallback(123, 1000)


def test_denied_or_live_game_remains_protected(monkeypatch):
    def denied(pid):
        raise psutil.AccessDenied(pid)
    monkeypatch.setattr(psutil, 'Process', denied)
    assert not W._windows_pid_reused_fallback(123, 1000)
    class Live:
        def __init__(self, pid): pass
        def create_time(self): return 900
    monkeypatch.setattr(psutil, 'Process', Live)
    assert not W._windows_pid_reused_fallback(123, 1000)
