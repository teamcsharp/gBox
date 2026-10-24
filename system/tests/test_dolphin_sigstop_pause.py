"""Linux Dolphin without its GDB stub pauses by stopping the process tree (MercMode warm pool parks RE4)."""
import signal
from types import SimpleNamespace

import pytest

from gbox import adapters as A


@pytest.mark.skipif(not hasattr(signal, 'SIGSTOP'), reason='POSIX signals')
def test_pause_and_resume_signal_the_whole_tree_without_a_debugger(monkeypatch):
    ad = object.__new__(A.DolphinAdapter)
    ad.dbg, ad.proc = None, SimpleNamespace(pid=10, poll=lambda: None)
    monkeypatch.setattr(A, 'HOST_OS', 'linux')
    monkeypatch.setattr(A.DolphinAdapter, '_tree', lambda self: [10, 11, 12])
    sent = []
    monkeypatch.setattr(A.os, 'kill', lambda pid, sig: sent.append((pid, sig)))
    assert ad.pause() == {'state': 'PAUSED', 'via': 'SIGSTOP', 'processes': 3} and ad.paused
    assert ad.resume()['state'] == 'PLAYING' and not ad.paused
    assert sent == [(p, signal.SIGSTOP) for p in (10, 11, 12)] + [(p, signal.SIGCONT) for p in (10, 11, 12)]


@pytest.mark.skipif(not hasattr(signal, 'SIGSTOP'), reason='POSIX signals')
def test_a_dead_dolphin_cannot_be_paused(monkeypatch):
    ad = object.__new__(A.DolphinAdapter)
    ad.dbg, ad.proc = None, SimpleNamespace(pid=10, poll=lambda: 1)
    monkeypatch.setattr(A, 'HOST_OS', 'linux')
    with pytest.raises(A.Unsupported):
        ad.pause()
