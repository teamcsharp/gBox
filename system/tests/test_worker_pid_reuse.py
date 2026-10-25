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
    def alive(pid, *, recorded_at, recorded_identity):
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



BOOT = 'a6c783be-d083-4254-91bf-7ad96fd020a1'
OLD_BOOT = 'bb2c69a0-5dba-49d4-bb85-31a45575bd98'
IDENTITY = {'boot_id': BOOT, 'start_ticks': 100050}


def linux_process_query(monkeypatch, *, error=None, platform='linux'):
    calls = []
    def kill(pid, signal):
        calls.append((pid, signal))
        if error is not None:
            raise error
    monkeypatch.setattr(worker_results, 'os', SimpleNamespace(name='posix', kill=kill))
    monkeypatch.setattr(worker_results, 'sys', SimpleNamespace(platform=platform))
    return calls


def linux_identity_query(monkeypatch, identity):
    calls = []
    def query(pid):
        calls.append(pid)
        if isinstance(identity, Exception):
            raise identity
        return identity
    monkeypatch.setattr(worker_results, 'linux_process_identity', query)
    return calls


@pytest.mark.parametrize('current,expected', [
    (IDENTITY, True), (IDENTITY | {'start_ticks': 100051}, False),
    (IDENTITY | {'boot_id': OLD_BOOT}, False),
    (None, True), ({}, True), (IDENTITY | {'start_ticks': True}, True),
    (IDENTITY | {'start_ticks': -1}, True), (IDENTITY | {'start_ticks': 2**64}, True),
    (IDENTITY | {'start_ticks': '100050'}, True), (IDENTITY | {'boot_id': 'invalid'}, True),
])
def test_linux_releases_only_proven_different_native_identity(monkeypatch, current, expected):
    signals = linux_process_query(monkeypatch)
    queries = linux_identity_query(monkeypatch, current)
    assert worker_results._pid_alive(42, recorded_identity=IDENTITY) is expected
    assert signals == [(42, 0)] and queries == [42]


@pytest.mark.parametrize('recorded', [None, {}, 1000, True, {'boot_id': BOOT},
                                     IDENTITY | {'start_ticks': True}, IDENTITY | {'boot_id': 'invalid'}])
def test_linux_unknown_or_legacy_identity_remains_protected(monkeypatch, recorded):
    linux_process_query(monkeypatch)
    queries = linux_identity_query(monkeypatch, IDENTITY | {'start_ticks': 200000})
    assert worker_results._pid_alive(42, recorded_at=1000, recorded_identity=recorded) is True
    assert queries == []


@pytest.mark.parametrize('recorded_at', [1, 1000, 2**60, -1, float('nan'), None])
def test_linux_wall_clock_jump_cannot_release_the_same_process(monkeypatch, recorded_at):
    linux_process_query(monkeypatch)
    linux_identity_query(monkeypatch, IDENTITY)
    assert worker_results._pid_alive(42, recorded_at=recorded_at, recorded_identity=IDENTITY) is True
    assert worker_results._pid_alive(42, recorded_at=recorded_at) is True


def test_linux_absent_process_needs_no_identity_query(monkeypatch):
    signals = linux_process_query(monkeypatch, error=ProcessLookupError('gone'))
    queries = linux_identity_query(monkeypatch, IDENTITY)
    assert worker_results._pid_alive(42, recorded_identity=IDENTITY) is False
    assert signals == [(42, 0)] and queries == []


def test_linux_exit_between_queries_releases_stale_protection(monkeypatch):
    calls = []
    def kill(pid, signal):
        calls.append((pid, signal))
        if len(calls) > 1:
            raise ProcessLookupError('exited during query')
    monkeypatch.setattr(worker_results, 'os', SimpleNamespace(name='posix', kill=kill))
    monkeypatch.setattr(worker_results, 'sys', SimpleNamespace(platform='linux'))
    linux_identity_query(monkeypatch, FileNotFoundError('gone'))
    assert worker_results._pid_alive(42, recorded_identity=IDENTITY) is False
    assert calls == [(42, 0), (42, 0)]


@pytest.mark.parametrize('kill_error', [None, PermissionError('signal query denied')])
@pytest.mark.parametrize('query_error', [PermissionError('metadata denied'),
                                        FileNotFoundError('procfs unavailable'),
                                        ProcessLookupError('unverified failure'), RuntimeError('failed')])
def test_linux_uncertain_identity_query_preserves_live_protection(monkeypatch, kill_error, query_error):
    linux_process_query(monkeypatch, error=kill_error)
    linux_identity_query(monkeypatch, query_error)
    assert worker_results._pid_alive(42, recorded_identity=IDENTITY) is True


def test_linux_denied_signal_query_can_still_prove_reuse_read_only(monkeypatch):
    signals = linux_process_query(monkeypatch, error=PermissionError('denied'))
    linux_identity_query(monkeypatch, IDENTITY | {'start_ticks': 200000})
    assert worker_results._pid_alive(42, recorded_identity=IDENTITY) is False
    assert signals == [(42, 0)]


def test_other_posix_platforms_keep_existing_existence_check(monkeypatch):
    signals = linux_process_query(monkeypatch, platform='darwin')
    queries = linux_identity_query(monkeypatch, IDENTITY | {'start_ticks': 200000})
    assert worker_results._pid_alive(42, recorded_identity=IDENTITY) is True
    assert signals == [(42, 0)] and queries == []


def test_linux_manifest_check_is_read_only_and_retains_live_and_legacy(tmp_path, monkeypatch):
    manifest = tmp_path / 'running.json'
    saved = json.dumps({'old': {'pid': 42, 'ts': 1000,
                                'linux_identity': IDENTITY | {'start_ticks': 100}},
                        'live': {'pid': 42, 'ts': 1, 'linux_identity': IDENTITY},
                        'legacy': {'pid': 42, 'ts': 1}, 'unknown': {'pid': 42}})
    manifest.write_text(saved)
    outbox = worker_results.ResultOutbox(tmp_path, 'http://localhost:8765', 'test')
    signals = linux_process_query(monkeypatch)
    queries = linux_identity_query(monkeypatch, IDENTITY)
    assert set(outbox.protected_sessions(manifest)) == {'live', 'legacy', 'unknown'}
    assert signals == [(42, 0)] * 4 and queries == [42, 42]
    assert manifest.read_text() == saved


def procfs_files(monkeypatch, *, stat=None, boot=BOOT.encode() + b'\n'):
    import io
    if stat is None:
        stat = b'42 (name with ) parentheses) S ' + b'0 ' * 18 + b'100050 0 0\n'
    paths = []
    def read(path, mode):
        assert mode == 'rb'
        paths.append(path)
        return io.BytesIO({'/proc/42/stat': stat, '/proc/sys/kernel/random/boot_id': boot}[path])
    monkeypatch.setattr(worker_results, 'open', read, raising=False)
    return paths


def test_linux_procfs_parser_reads_raw_ticks_without_wall_clock_or_tick_frequency(monkeypatch):
    paths = procfs_files(monkeypatch)
    monkeypatch.setattr(worker_results, 'os', SimpleNamespace())
    monkeypatch.setattr(worker_results, 'time', SimpleNamespace())
    assert worker_results.linux_process_identity(42) == IDENTITY
    assert paths == ['/proc/42/stat', '/proc/sys/kernel/random/boot_id']


@pytest.mark.parametrize('changes', [
    {'stat': b'43 (other pid) S ' + b'0 ' * 18 + b'100050'},
    {'stat': b'42 missing delimiters'}, {'stat': b'42 (short) S'},
    {'stat': b'42 (negative) S ' + b'0 ' * 18 + b'-1'},
    {'stat': b'42 (huge) S ' + b'0 ' * 40000},
    {'boot': b'not-a-uuid'}, {'boot': b''}, {'boot': b'\xff'}, {'boot': b' ' * 65},
])
def test_linux_procfs_uncertainty_cannot_prove_process_reuse(monkeypatch, changes):
    procfs_files(monkeypatch, **changes)
    assert worker_results._linux_pid_reused(42, IDENTITY) is False


def test_track_emulator_records_native_identity_and_preserves_other_records(tmp_path, monkeypatch):
    from gbox import tools
    config = SimpleNamespace(runtime=tmp_path)
    path = tools._running_file(config)
    path.write_text(json.dumps({'existing': {'pid': 55, 'ts': 1}}))
    monkeypatch.setattr(tools, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(tools, 'time', SimpleNamespace(time=lambda: 2000))
    calls = linux_identity_query(monkeypatch, IDENTITY)
    tools.track_emulator(config, 'new', 42)
    assert json.loads(path.read_text()) == {'existing': {'pid': 55, 'ts': 1},
        'new': {'pid': 42, 'ts': 2000, 'linux_identity': IDENTITY}}
    assert calls == [42]
    tools.track_emulator(config, 'new', None, add=False)
    assert json.loads(path.read_text()) == {'existing': {'pid': 55, 'ts': 1}}
    assert calls == [42]


@pytest.mark.parametrize('error', [PermissionError('denied'), FileNotFoundError('gone'), ValueError('invalid')])
def test_failed_launch_identity_capture_retains_legacy_protection(tmp_path, monkeypatch, error):
    from gbox import tools
    config = SimpleNamespace(runtime=tmp_path)
    monkeypatch.setattr(tools, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(tools, 'time', SimpleNamespace(time=lambda: 2000))
    linux_identity_query(monkeypatch, error)
    tools.track_emulator(config, 'new', 42)
    record = json.loads(tools._running_file(config).read_text())['new']
    assert record == {'pid': 42, 'ts': 2000}
    linux_process_query(monkeypatch)
    assert worker_results._pid_alive(record['pid'], recorded_at=record['ts']) is True
