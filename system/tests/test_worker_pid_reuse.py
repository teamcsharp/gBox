import json
from types import SimpleNamespace

import pytest

from gbox import worker_results


def kernel(born, success=True):
    def times(handle, created, *_):
        ticks = int((born + 11_644_473_600) * 10_000_000)
        created._obj.dwLowDateTime = ticks & 0xffffffff
        created._obj.dwHighDateTime = ticks >> 32
        return success
    return SimpleNamespace(GetProcessTimes=times)


@pytest.mark.parametrize('born,recorded,expected', [
    (2000, 1000, True), (999, 1000, False), (1000.5, 1000, False),
    (2000, None, False), (2000, float('nan'), False), (2000, '1000', False),
])
def test_only_proven_reused_pids_are_released(born, recorded, expected):
    assert worker_results._windows_pid_reused(kernel(born), 1, recorded) is expected


def test_failed_identity_query_keeps_game_protected():
    assert not worker_results._windows_pid_reused(kernel(2000, success=False), 1, 1000)


def test_ownership_timestamp_is_checked_without_changing_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / 'running.json'
    saved = json.dumps({'old': {'pid': 42, 'ts': 1000}, 'live': {'pid': 43, 'ts': 2000}})
    manifest.write_text(saved)
    queries = []
    def alive(pid, *, recorded_at):
        queries.append((pid, recorded_at))
        return pid == 43
    monkeypatch.setattr(worker_results, '_pid_alive', alive)
    outbox = worker_results.ResultOutbox(tmp_path, 'http://localhost:8765', 'test')
    assert outbox.protected_sessions(manifest) == ['live']
    assert queries == [(43, 2000), (42, 1000)] or queries == [(42, 1000), (43, 2000)]
    assert manifest.read_text() == saved


def denied_process_query(monkeypatch, *, error=5):
    import ctypes
    calls = []
    def open_process(access, inherit, pid):
        calls.append((access, inherit, pid))
        return None
    api = SimpleNamespace(OpenProcess=open_process)
    monkeypatch.setattr(worker_results, 'os', SimpleNamespace(name='nt'))
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: api, raising=False)
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error, raising=False)
    return calls


def process_creation_query(monkeypatch, born):
    import psutil
    calls = []
    def process(pid):
        calls.append(pid)
        def create_time():
            if isinstance(born, Exception):
                raise born
            return born
        return SimpleNamespace(create_time=create_time)
    monkeypatch.setattr(psutil, 'Process', process)
    return calls


@pytest.mark.parametrize('born,expected', [
    (1792108290.22367, False),  # Office SearchFilterHost reused an old emulator PID.
    (1792104343.1925952, True), (1792104342.0, True), (1792104344.0, True),
    (None, True), (float('nan'), True), (float('inf'), True),
    ('1792108290', True), (True, True), (-1, True),
])
def test_access_denied_releases_only_independently_proven_reused_pid(monkeypatch, born, expected):
    native_calls = denied_process_query(monkeypatch)
    fallback_calls = process_creation_query(monkeypatch, born)
    assert worker_results._pid_alive(129400, recorded_at=1792104343.1925952) is expected
    assert native_calls == [(0x1000, False, 129400)]
    assert fallback_calls == [129400]


@pytest.mark.parametrize('recorded', [None, 0, -1, float('nan'), float('inf'), '1000', True])
def test_access_denied_without_valid_ownership_time_stays_protected(monkeypatch, recorded):
    denied_process_query(monkeypatch)
    calls = process_creation_query(monkeypatch, 2000)
    assert worker_results._pid_alive(42, recorded_at=recorded) is True
    assert calls == []


@pytest.mark.parametrize('error', [PermissionError('denied'), ProcessLookupError('gone'), RuntimeError('failed')])
def test_failed_independent_query_stays_protected(monkeypatch, error):
    denied_process_query(monkeypatch)
    process_creation_query(monkeypatch, error)
    assert worker_results._pid_alive(42, recorded_at=1000) is True


@pytest.mark.parametrize('error,expected', [(87, False), (6, True), (0, True)])
def test_other_native_open_failures_preserve_existing_protection(monkeypatch, error, expected):
    denied_process_query(monkeypatch, error=error)
    calls = process_creation_query(monkeypatch, 2000)
    assert worker_results._pid_alive(42, recorded_at=1000) is expected
    assert calls == []


def test_proven_reuse_removes_only_stale_protection_without_mutating_records(tmp_path, monkeypatch):
    manifest = tmp_path / 'running.json'
    saved = json.dumps({'old': {'pid': 129400, 'ts': 1792104343.1925952},
                        'live': {'pid': 129400, 'ts': 1792108290.22367},
                        'unknown': {'pid': 129400}})
    manifest.write_text(saved)
    outbox = worker_results.ResultOutbox(tmp_path, 'http://localhost:8765', 'test')
    denied_process_query(monkeypatch)
    process_creation_query(monkeypatch, 1792108290.22367)
    assert set(outbox.protected_sessions(manifest)) == {'live', 'unknown'}
    assert manifest.read_text() == saved
