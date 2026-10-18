import pytest
from gbox.emulator_freeze import _hold_windows

class Threads:
    def __init__(self, counts=None):
        self.counts = counts or {10: 0, 11: 2, 12: 0}
        self.closed = []; self.calls = []; self.fault = None; self.scans = 0
    def threads(self, pid):
        self.scans += 1
        if self.fault == 'spawn' and self.scans == 2: return [*self.counts, 99]
        return list(self.counts)
    def open(self, tid):
        self.calls.append(('open', tid))
        if self.fault == 'open' and tid == 11: raise OSError('open')
        return tid
    def owner(self, h): return 2 if self.fault == 'owner' and h == 11 else 1
    def suspend(self, h):
        self.calls.append(('suspend', h))
        if self.fault == 'suspend' and h == 11: raise OSError('suspend')
        old = self.counts[h]; self.counts[h] += 1; return old
    def resume(self, h):
        self.calls.append(('resume', h))
        if self.fault == 'resume' and h == 11:
            self.fault = None; raise OSError('transient resume failure')
        assert self.counts[h] > 0
        self.counts[h] -= 1
    def close(self, h): self.closed.append(h)

@pytest.mark.parametrize('failure', [None, 'body', 'open', 'owner', 'suspend', 'spawn', 'identity'])
def test_balances_all_suspensions_and_preserves_prior_pause(failure):
    api = Threads(); initial = dict(api.counts); api.fault = failure; calls = 0
    def identity():
        nonlocal calls
        calls += 1
        return (1, 99 if failure == 'identity' and calls == 2 else 2)
    def run():
        with _hold_windows(api, (1, 2), identity):
            assert api.counts == {k: v + 1 for k, v in initial.items()}
            if failure == 'body': raise ValueError('body')
    if failure:
        with pytest.raises((RuntimeError, OSError, ValueError)): run()
    else: run()
    assert api.counts == initial
    opened = [h for op,h in api.calls if op == 'open' and not (failure == 'open' and h == 11)]
    assert sorted(api.closed) == sorted(opened)
    assert len(api.closed) == len(set(api.closed))

def test_failed_resume_is_retried_without_double_decrement():
    api = Threads(); initial = dict(api.counts)
    with _hold_windows(api, (1, 2), lambda: (1, 2)): api.fault = 'resume'
    assert api.counts == initial
    assert api.calls.count(('resume', 11)) == 2

def test_unrecoverable_resume_still_releases_other_threads():
    api = Threads(); original = api.resume
    def resume(h):
        if h == 11: raise OSError('cannot resume 11')
        original(h)
    api.resume = resume
    with pytest.raises(RuntimeError, match='release failed'):
        with _hold_windows(api, (1, 2), lambda: (1, 2)): pass
    assert api.counts == {10: 0, 11: 3, 12: 0}
    assert api.closed == [12, 11, 10]

@pytest.mark.parametrize('tids', [[], [10,10], list(range(5000))])
def test_invalid_thread_inventory_does_not_open_any_handle(tids):
    api = Threads(); api.threads = lambda pid: tids
    with pytest.raises(RuntimeError, match='inventory'):
        with _hold_windows(api, (1, 2), lambda: (1, 2)): pytest.fail('entered')
    assert not api.calls


def test_direct_memory_read_and_write_share_reentrant_lock():
    import threading
    from gbox.debug import DolphinProcMem
    memory=DolphinProcMem.__new__(DolphinProcMem);memory.lock=threading.RLock()
    memory._host=lambda address,length:address
    memory._raw=lambda address,length:b'x'*length
    with memory.lock:
        assert memory.read(1,2)==b'xx'
        completed=threading.Event()
        thread=threading.Thread(target=lambda:(memory.read(1,1),completed.set()))
        thread.start()
        assert not completed.wait(.03)
    assert completed.wait(1);thread.join()


@pytest.mark.parametrize('operation',['pause','resume'])
def test_adapter_pause_resume_waits_for_native_memory_transaction(monkeypatch,operation):
    import threading
    from types import SimpleNamespace
    from gbox import adapters
    ad=adapters.DolphinWinAdapter.__new__(adapters.DolphinWinAdapter)
    ad.dbg=SimpleNamespace(lock=threading.RLock());ad.proc=SimpleNamespace(pid=123)
    ad.paused_tids=None if operation=='pause' else [1,2]
    entered=threading.Event();completed=threading.Event()
    monkeypatch.setattr(adapters,'win_suspend_emulation',lambda pid:(entered.set() or [1,2]))
    monkeypatch.setattr(adapters,'win_resume_threads',lambda tids:(entered.set() or len(tids)))
    with ad.dbg.lock:
        thread=threading.Thread(target=lambda:(getattr(ad,operation)(),completed.set()))
        thread.start();assert not entered.wait(.03)
    assert completed.wait(1);thread.join();assert entered.is_set()
    assert ad.paused_tids==([1,2] if operation=='pause' else None)


def test_busy_memory_guard_has_bounded_wait_and_releases_only_when_owned():
    from types import SimpleNamespace
    from gbox.emulator_freeze import memory_guard
    class Lock:
        def __init__(self,available):self.available=available;self.calls=[]
        def acquire(self,*,timeout):self.calls.append(('acquire',timeout));return self.available
        def release(self):self.calls.append(('release',))
    lock=Lock(False)
    with pytest.raises(RuntimeError,match='busy'):
        with memory_guard(SimpleNamespace(lock=lock),timeout=.01):pytest.fail('entered')
    assert lock.calls==[('acquire',.01)]
    lock=Lock(True)
    with pytest.raises(ValueError):
        with memory_guard(SimpleNamespace(lock=lock)):raise ValueError('body')
    assert lock.calls==[('acquire',2.0),('release',)]
