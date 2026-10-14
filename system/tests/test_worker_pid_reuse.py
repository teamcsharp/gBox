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
