"""The agent-only research shell barrage: launcher ring mechanics behind the ring chooser's shell kinds."""
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from gbox.mercs import interventions as I


def test_shell_barrage_args_are_agent_only_and_bounded():
    ok = I.shell_barrage_args({'kind': 'shell1304', 'count': 4, 'radius_cm': 700.0, 'allow_unverified': True}, 'probe')
    assert ok == {'kind': 'shell1304', 'count': 4, 'radius_cm': 700.0, 'allow_unverified': True}
    for source in ('viewer', 'operator', ''):
        with pytest.raises(ValueError, match='agent research'):
            I.shell_barrage_args({'allow_unverified': True}, source)
    for args in ({'kind': 'shell1304', 'allow_unverified': False},
                 {'kind': 'hand', 'allow_unverified': True},
                 {'kind': 'shell1304', 'count': 0, 'allow_unverified': True},
                 {'kind': 'shell1304', 'count': 17, 'allow_unverified': True},
                 {'kind': 'shell1304', 'radius_cm': 600.0, 'allow_unverified': True},
                 {'kind': 'shell1304', 'radius_cm': 3000.0, 'allow_unverified': True},
                 {'kind': 'shell1304', 'point': [0., 0., 0.], 'allow_unverified': True}):
        with pytest.raises(ValueError):
            I.shell_barrage_args(args, 'probe')


@pytest.mark.parametrize('source,pending,expected_calls', [('probe', False, 1), ('viewer', False, 0),
                                                           ('probe', True, 0)])
def test_the_shell_barrage_runs_under_the_shared_owner_when_idle(monkeypatch, source, pending, expected_calls):
    from gbox.mercs.titles import re6_switch_native as N, re6_switch_shell_probe as P
    life, running, calls, results = [2], [True], [], []

    class FakeRE6(SimpleNamespace):
        pass

    stats = {'round_evidence_id': 'round-a'}
    if pending == 'blocked':
        stats['mine_allocation_blocked_reason'] = 'uncertain native allocation; no further automatic bombs in this life'
    elif pending:
        stats['mine_deadline_pending'] = 1
        stats['mine_avoid_positions'] = [[0., 0., 0.]]
    ctl = FakeRE6(pid=123, identity=(123, 99), ready=lambda: (456, life[0]), ad=SimpleNamespace())
    monkeypatch.setattr(N, 'Controller', FakeRE6)
    monkeypatch.setattr(I, 'native_controller', lambda _: ctl)

    def barrage(controller, *, count, radius_cm, kind, cancelled):
        assert controller is ctl and count == 4 and radius_cm == 700.0 and kind == 'shell1304'
        assert cancelled() is False
        calls.append(controller)
        return {'op': 'shell_barrage', 'kind': kind, 'requested': count, 'spawned': count, 'armed': count,
                'detonated': 0, 'verified': False, 'state': 'uncertain', 'ring': []}

    monkeypatch.setattr(P, 'barrage', barrage)

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/claim'):
            assert 're6_shell_barrage' in body['capabilities']
            assert 're6_shell_probe' in body['capabilities']
            return httpx.Response(200, json={'requests': [{'id': 'bar', 'claim': 'once',
                'op': 're6_shell_barrage', 'source': source,
                'args': {'kind': 'shell1304', 'count': 4, 'radius_cm': 700.0, 'allow_unverified': True},
                'expires': time.time() + 10, 'epoch': body['epoch']}]})
        results.extend(body['results'])
        running[0] = False
        return httpx.Response(200, json={})

    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    I.worker_loop('sid', 'http://fixture', {}, SimpleNamespace(), lambda: stats, lambda: running[0])
    assert len(calls) == expected_calls
    if expected_calls:
        assert results[0]['result']['op'] == 'shell_barrage'
        assert results[0]['result']['verified'] is False
    elif pending:
        assert results[0]['result']['state'] == 'failed'


@pytest.mark.parametrize('kind,pending,barrage_calls,ring_calls', [
    ('shell1304', False, 1, 0),
    ('shell1304', True, 1, 0),          # pending remote bombs no longer refuse the operator's click
    ('shell1303', 'blocked', 0, 0),     # an uncertain native allocation still does
    ('flash', False, 0, 1),
])
@pytest.mark.parametrize('allow', [True, False])
def test_the_ring_button_routes_launcher_kinds_to_the_research_barrage(monkeypatch, kind, pending, barrage_calls,
                                                                      ring_calls, allow):
    # The operator's chooser row for a launcher shell kind carries allow_unverified; the worker turns it into the
    # research barrage (idle-gated, honest receipt), while every other kind still uses the native grenade_ring.
    from gbox.mercs.titles import re6_switch_native as N, re6_switch_shell_probe as P
    life, running, calls, results, rings = [2], [True], [], [], []

    class FakeRE6(SimpleNamespace):
        pass

    stats = {'round_evidence_id': 'round-a'}
    if pending == 'blocked':
        stats['mine_allocation_blocked_reason'] = 'uncertain native allocation; no further automatic bombs in this life'
    elif pending:
        stats['mine_deadline_pending'] = 1
        stats['mine_avoid_positions'] = [[0., 0., 0.]]
    ctl = FakeRE6(pid=123, identity=(123, 99), ready=lambda: (456, life[0]), ad=SimpleNamespace())
    ctl.grenade_ring = lambda k, allow_unverified=False: (rings.append(k) or
                                                          {'state': 'confirmed', 'verified': True, 'op': 'grenade_ring'})
    monkeypatch.setattr(N, 'Controller', FakeRE6)
    monkeypatch.setattr(I, 'native_controller', lambda _: ctl)

    def barrage(controller, *, count, radius_cm, kind, cancelled):
        assert controller is ctl and count == 8 and radius_cm == 800.0
        calls.append(kind)
        return {'op': 'shell_barrage', 'kind': kind, 'requested': count, 'spawned': 8, 'armed': 8,
                'detonated': 0, 'verified': False, 'state': 'uncertain', 'ring': []}

    monkeypatch.setattr(P, 'barrage', barrage)

    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/claim'):
            return httpx.Response(200, json={'requests': [{'id': 'ring', 'claim': 'once',
                'op': 'grenade_ring', 'source': 'probe',
                'args': {'kind': kind, 'allow_unverified': allow},
                'expires': time.time() + 10, 'epoch': body['epoch']}]})
        results.extend(body['results'])
        running[0] = False
        return httpx.Response(200, json={})

    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))
    I.worker_loop('sid', 'http://fixture', {}, SimpleNamespace(), lambda: stats, lambda: running[0])
    assert len(calls) == barrage_calls and len(rings) == ring_calls
    if barrage_calls:
        assert results[0]['result']['op'] == 'grenade_ring'
        assert results[0]['result']['verified'] is False
        assert stats['shell_rings'] == 1 and stats['shell_ring_shells'] == 8
    if pending == 'blocked':
        assert results[0]['result']['state'] == 'failed'
    if ring_calls:
        assert rings == ['flash'] and stats['grenade_rings'] == 1
