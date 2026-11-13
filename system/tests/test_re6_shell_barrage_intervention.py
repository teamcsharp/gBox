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
    if pending:
        stats['mine_deadline_pending'] = 1
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
