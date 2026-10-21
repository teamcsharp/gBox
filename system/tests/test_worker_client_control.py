import io
import json
import threading
import os
import subprocess
import sys
import time
import concurrent.futures
from types import SimpleNamespace

import pytest

from gbox import worker_client_control as C

SECRET, REQUEST = 'a' * 64, 'b' * 32


def request(**extra):
    return dict(v=1, secret=SECRET, op='stop_if_idle', id=REQUEST, expires=110, **extra)


def control(*requests):
    output = []
    c = C.Control(SECRET, io.StringIO(''.join(json.dumps(x) + '\n' for x in requests)), output.append,
                  clock=lambda: 100, pid=12)
    c.read()
    return c, output


def test_pipe_reader_never_stops_an_in_flight_claim():
    c, output = control(request())
    stop = threading.Event()
    assert not stop.is_set() and output == []
    # The in-flight claim completes BEFORE the main loop services the queue.
    active = {'newly-claimed-job'}
    outbox = SimpleNamespace(pending_count=lambda: 0, protected_sessions=lambda _: [])
    assert not c.check(lambda: C.idle_reason(active, outbox, {}, None), stop)
    assert not stop.is_set() and 'worker jobs' in output[-1]


def test_only_confirmed_idle_stops_claiming_and_acknowledges_exact_request():
    c, output = control(request())
    stop = threading.Event()
    assert c.check(lambda: None, stop) and stop.is_set()
    result = json.loads(output[-1].removeprefix(C.PREFIX))
    assert result == dict(v=1, secret=SECRET, pid=12, event='stopping', id=REQUEST)


@pytest.mark.parametrize('field,value', [('secret', 'wrong'), ('op', 'kill'), ('v', 2), ('id', '../other')])
def test_unrecognized_or_unowned_requests_cannot_enter_queue(field, value):
    item = request(); item[field] = value
    c, _ = control(item)
    assert not c.check(lambda: pytest.fail('unauthorized inspection'), threading.Event())


@pytest.mark.parametrize('expires', [99, 100, 116, float('nan'), float('inf'), True, '110', None])
def test_expired_or_invalid_request_never_stops_later(expires):
    item = request(); item['expires'] = expires
    c, output = control(item)
    stop = threading.Event()
    assert not c.check(lambda: pytest.fail('expired inspection'), stop)
    assert not stop.is_set() and 'expired' in output[-1]


@pytest.mark.parametrize('busy', ['active', 'session', 'result', 'owned', 'unknown'])
def test_every_owned_activity_or_unknown_inspection_blocks_shutdown(busy):
    def pending():
        if busy == 'unknown': raise OSError('read failed')
        return int(busy == 'result')
    outbox = SimpleNamespace(pending_count=pending, protected_sessions=lambda _: ['sid'] if busy == 'owned' else [])
    c, output = control(request()); stop = threading.Event()
    assert not c.check(lambda: C.idle_reason({'job'} if busy == 'active' else set(), outbox,
                                             {'sid': object()} if busy == 'session' else {}, None), stop)
    assert not stop.is_set() and 'refused' in output[-1]


def test_queue_is_bounded_and_eof_does_not_stop_worker():
    c, _ = control(*([request()] * 20))
    assert c.requests.qsize() == 4
    empty, _ = control()
    assert not empty.check(lambda: None, threading.Event())


def test_slow_idle_inspection_cannot_stop_after_parent_request_expires():
    c, output = control(request()); stop = threading.Event()
    def slow():
        c.clock = lambda: 111
        return None
    assert not c.check(slow, stop)
    assert not stop.is_set() and 'expired during inspection' in output[-1]


def test_read_only_disk_inspection_rejects_owned_and_pending_records(tmp_path, monkeypatch):
    from gbox import config
    source = tmp_path / 'gbox.toml'; source.write_text('')
    runtime = tmp_path / 'runtime'
    monkeypatch.setattr(config, 'load', lambda _: SimpleNamespace(runtime=runtime))
    assert C.inspect_disk(source)['reason'] is None and not runtime.exists()
    runtime.mkdir(); manifest = runtime / 'gbox-running.json'
    manifest.write_text('{"owned": {"pid": 123}}')
    assert C.inspect_disk(source)['reason']
    manifest.write_text('{}')
    result = runtime / 'worker-results' / 'namespace' / 'result.json'
    result.parent.mkdir(parents=True); result.write_text('{}')
    assert C.inspect_disk(source)['reason']


def test_disk_parse_failure_is_not_proof_of_idle(tmp_path, monkeypatch):
    from gbox import config
    source = tmp_path / 'gbox.toml'; source.write_text('')
    monkeypatch.setattr(config, 'load', lambda _: SimpleNamespace(runtime=tmp_path))
    (tmp_path / 'gbox-running.json').write_text('broken')
    with pytest.raises(ValueError): C.inspect_disk(source)


def test_unreadable_result_store_is_not_silently_treated_as_empty(tmp_path, monkeypatch):
    from gbox import config
    source = tmp_path / 'gbox.toml'; source.write_text('')
    (tmp_path / 'worker-results').mkdir()
    monkeypatch.setattr(config, 'load', lambda _: SimpleNamespace(runtime=tmp_path))
    def denied(_): raise PermissionError('fixture denied')
    monkeypatch.setattr(C.os, 'scandir', denied)
    with pytest.raises(PermissionError): C.inspect_disk(source)


def test_control_is_opt_in_and_never_reads_interactive_or_legacy_stdin(monkeypatch):
    monkeypatch.delenv('GBOX_CLIENT_CONTROL', raising=False)
    assert C.from_environment() is None
    monkeypatch.setenv('GBOX_CLIENT_CONTROL', 'a' * 64)
    monkeypatch.setattr(C.sys, 'stdin', SimpleNamespace(isatty=lambda: True))
    assert C.from_environment() is None


def test_real_parent_pipe_exits_cleanly_without_daemon_stdin_lock_or_second_request():
    script = '''from gbox.worker_client_control import from_environment
import threading,time
c=from_environment(); stop=threading.Event()
while not c.check(lambda: None, stop): time.sleep(.01)
'''
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=os.environ | {'GBOX_CLIENT_CONTROL': SECRET})
    try:
        ready = json.loads(proc.stdout.readline().removeprefix(C.PREFIX))
        assert ready['event'] == 'ready' and ready['pid'] == proc.pid
        item = request(); item['expires'] = time.time() + 10
        proc.stdin.write(json.dumps(item) + '\n'); proc.stdin.flush()
        # Keep the parent pipe OPEN while the worker returns normally. A
        # buffered daemon reader can otherwise abort Python during finalization.
        assert proc.wait(timeout=5) == 0
        stopping = json.loads(proc.stdout.readline().removeprefix(C.PREFIX))
        assert stopping['event'] == 'stopping' and stopping['id'] == REQUEST
        assert not proc.stderr.read()
    finally:
        if proc.poll() is None: proc.kill(); proc.wait(timeout=5)
        proc.stdin.close(); proc.stdout.close(); proc.stderr.close()


def test_timed_out_callable_blocks_idle_shutdown_until_it_actually_finishes(tmp_path, monkeypatch):
    from gbox import registry as R
    from gbox.config import Config
    from pydantic import BaseModel
    started, release = threading.Event(), threading.Event()
    def operation(_, ctx):
        started.set()
        release.wait(5)
        return {}
    ctx = R.Ctx(Config(cache_dir=tmp_path / 'cache', data_dir=tmp_path / 'data'))
    tool = R.Tool(name='idle-timeout-proof', version='1', fn=operation, In=BaseModel, Out=BaseModel,
                  timeout_s=.025, retries=0)
    outbox = SimpleNamespace(pending_count=lambda: 0, protected_sessions=lambda _: [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        monkeypatch.setattr(R, '_pool', pool)
        try:
            with pytest.raises(concurrent.futures.TimeoutError): R._execute(tool, None, ctx)
            assert started.is_set() and R.inflight_executions() == 1
            c, output = control(request()); stop = threading.Event()
            # The outer worker job and its result are already settled/empty.
            assert not c.check(lambda: C.idle_reason(set(), outbox, {}, None), stop)
            assert not stop.is_set() and 'callable is still' in output[-1]
        finally:
            release.set()
    assert R.inflight_executions() == 0
    c, _ = control(request()); stop = threading.Event()
    assert c.check(lambda: C.idle_reason(set(), outbox, {}, None), stop) and stop.is_set()
