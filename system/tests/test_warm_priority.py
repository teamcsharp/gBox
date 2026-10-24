"""A MercMode game booting / parked in the background runs at niceness 10; the swapped-in game goes back to 0."""
from types import SimpleNamespace

from gbox import tools as T


def test_warm_priority_renices_the_tree_on_linux_only(monkeypatch):
    calls = []
    monkeypatch.setattr(T.subprocess, 'run', lambda cmd, **kw: calls.append(cmd))
    ad = SimpleNamespace(proc=SimpleNamespace(pid=4242, poll=lambda: None))
    monkeypatch.setattr(T.sys, 'platform', 'linux')
    T._warm_priority(ad, 10)
    assert calls and calls[-1][:5] == ['sudo', '-n', 'renice', '-n', '10'] and '4242' in calls[-1]
    monkeypatch.setattr(T.sys, 'platform', 'win32')
    T._warm_priority(ad, 0)
    assert len(calls) == 1
    T._warm_priority(SimpleNamespace(proc=SimpleNamespace(pid=1, poll=lambda: 0)), 0)   # an exited emulator: nothing
    assert len(calls) == 1
