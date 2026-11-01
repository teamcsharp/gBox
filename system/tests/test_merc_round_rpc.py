"""Round-control RPC authorization and exact-session dispatch without network/game I/O."""
import time
import uuid
from types import SimpleNamespace

import pytest

from gbox import tools
from gbox.mercs import round_controls as R


class Store:
    def __init__(self):
        self.rows = {('session', 'worker-one'): {'state': 'running', 'worker_id': 'worker'},
                     ('worker', 'worker'): {'last_seen': time.time()}}
    def get(self, kind, key):
        return self.rows.get((kind, key))


def context(*permissions):
    return SimpleNamespace(config=SimpleNamespace(granted_permissions=set(permissions)))


def mutation(**changes):
    return {'op': 'replay', 'mode': 'once', 'request_id': str(uuid.uuid4()), **changes}


def test_read_only_status_authorization_does_not_require_execute():
    store = Store()
    R.authorize(store, context('read').config, 'worker-one', {'op': 'status'})
    R.authorize(store, context('read').config, 'worker-one', {})


@pytest.mark.parametrize('op', ['replay', 'stages', 'quick_attack'])
def test_server_rejects_mutation_without_execute_permission(op):
    with pytest.raises(PermissionError, match='execute'):
        R.authorize(Store(), context('read').config, 'worker-one', mutation(op=op))
    R.authorize(Store(), context('read', 'execute').config, 'worker-one', mutation(op=op))


@pytest.mark.parametrize('state', [None, 'ended', 'paused'])
def test_missing_or_nonrunning_session_cannot_authorize_status_or_mutation(state):
    store = Store()
    if state is None:
        del store.rows[('session', 'worker-one')]
    else:
        store.rows[('session', 'worker-one')]['state'] = state
    for body in ({'op': 'status'}, mutation()):
        with pytest.raises(ValueError, match='running session'):
            R.authorize(store, context('read', 'execute').config, 'worker-one', body)


@pytest.mark.parametrize('last_seen', [None, 0, -61])
def test_offline_or_unknown_worker_is_refused(last_seen):
    store = Store()
    store.rows[('worker', 'worker')] = {} if last_seen is None else {'last_seen': time.time() + last_seen if last_seen else 0}
    with pytest.raises(ValueError, match='offline'):
        R.authorize(store, context('read', 'execute').config, 'worker-one', {'op': 'status'})


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, 'SESSIONS', {})
    monkeypatch.setattr(R.Controls, 'quick_status', lambda self: {'available': False})
    controls = {}
    for sid in ('worker-one', 'worker-two'):
        c = R.Controls('re4', sid, path=tmp_path / (sid + '.json'))
        c.observed(1, 0)
        controls[sid] = c
        tools.SESSIONS[sid] = (SimpleNamespace(_merc_round_controls=c), {'title': 'Resident Evil 4'})
    return controls


def test_worker_status_read_and_exact_session_mutation_route(sessions):
    report = R.execute('worker-one', {'op': 'status'}, context('read'))
    assert report['available'] and report['session_id'] == 'worker-one'
    body = mutation()
    result = R.execute('worker-two', body, context('read', 'execute'))
    assert result['receipt']['request_id'] == body['request_id'] and result['receipt']['status'] == 'queued'
    assert sessions['worker-two'].once is not None and sessions['worker-one'].once is None


@pytest.mark.parametrize('ctx', [None, context('read')])
def test_worker_rechecks_execute_permission_before_any_mutation(sessions, ctx):
    with pytest.raises(PermissionError, match='execute'):
        R.execute('worker-one', mutation(), ctx)
    assert all(c.once is None for c in sessions.values())


@pytest.mark.parametrize('control_sid', [None, 'old-session'])
def test_uninitialized_or_stale_adapter_returns_definite_rejection(sessions, control_sid):
    ad = tools.SESSIONS['worker-one'][0]
    if control_sid is None:
        del ad._merc_round_controls
    else:
        ad._merc_round_controls.sid = control_sid
    status = R.execute('worker-one', {'op': 'status'}, context('read'))
    assert status['available'] is False and status['session_id'] == 'worker-one'
    body = mutation()
    report = R.execute('worker-one', body, context('execute'))
    assert report['receipt']['request_id'] == body['request_id']
    assert report['receipt']['status'] == 'rejected' and report['receipt']['error'] == report['reason']
    assert all(c.once is None for c in sessions.values())


def test_a_missing_exact_worker_session_never_uses_another_adapter(sessions):
    with pytest.raises(KeyError):
        R.execute('worker-missing', mutation(), context('execute'))
    assert all(c.once is None for c in sessions.values())
