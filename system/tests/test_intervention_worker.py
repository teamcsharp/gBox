"""Exercise the real queue consumer across the brief bot-input handover."""
from types import SimpleNamespace

import httpx
import pytest

from gbox.mercs import interventions as I


@pytest.mark.parametrize('change', ['none', 'player', 'round', 'operator', 'expired', 'stopped', 'no_ack'])
def test_weapon_handover_rechecks_context_and_always_releases_bot(monkeypatch, change):
    ad, stats, results, calls = SimpleNamespace(), {'round_evidence_id': 'round-a'}, [], []
    clock, life, running = [100.0], [2], [True]
    ctl = SimpleNamespace(pid=123, identity=(123, 99), ready=lambda: (456, life[0]),
                          weapon_choices=lambda: [{'item': 25, 'weapon': 'Hydra'}])

    def equip(item, *, expected, allowed):
        assert stats['native_weapon_pending']['generation'] == 2
        assert expected == (456, 2)
        assert allowed()
        calls.append(item)
        return dict(state='confirmed', verified=True, item=item, weapon='Hydra',
                    player=456, player_generation=2, weapon_generation=7)

    ctl.equip_primary = equip
    monkeypatch.setattr(I, 'native_controller', lambda _: ctl)
    monkeypatch.setattr(I.time, 'time', lambda: clock[0])
    monkeypatch.setattr(I.time, 'monotonic', lambda: clock[0])

    def sleep(seconds):
        if seconds != .01:
            return
        assert stats['native_weapon_pending']['until'] == 103
        if change == 'no_ack':
            clock[0] += 1
            return
        stats['native_weapon_pending']['released'] = True
        if change == 'player': life[0] += 1
        if change == 'round': stats['round_evidence_id'] = 'round-b'
        if change == 'operator': stats['operator_control'] = True
        if change == 'expired': clock[0] += 20
        if change == 'stopped': running[0] = False

    monkeypatch.setattr(I.time, 'sleep', sleep)

    def handler(request):
        import json
        body = json.loads(request.content)
        if request.url.path.endswith('/claim'):
            assert body['options']['weapons'][0]['item'] == 25
            return httpx.Response(200, json={'requests': [dict(id='request', claim='claim',
                op='equip_primary', args={'item': 25}, expires=110, epoch=body['epoch'])]})
        assert request.url.path.endswith('/results')
        assert 'native_weapon_pending' not in stats
        results.extend(body['results'])
        running[0] = False
        return httpx.Response(200, json={})

    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    I.worker_loop('sid', 'http://fixture', {}, ad, lambda: stats, lambda: running[0])
    assert len(results) == 1
    assert calls == ([25] if change == 'none' else [])
    assert results[0]['result']['state'] == ('confirmed' if change == 'none' else 'failed')
    assert hasattr(ad, '_merc_primary_weapon') is (change == 'none')


@pytest.mark.parametrize('change', ['none', 'player', 'expired', 'stopped'])
def test_ammo_write_is_fenced_to_claimed_life_and_reports_readback(monkeypatch, change):
    import json
    ad, results, calls = SimpleNamespace(), [], []
    life, running, clock = [2], [True], [100.0]
    ctl = SimpleNamespace(pid=123, identity=(123, 99), ready=lambda: (456, life[0]),
        ammo_status=lambda: {'available': True, 'enabled': False},
        grenade_kinds=lambda: [{'kind': 'flash', 'available': True}])
    def toggle(enabled, *, expected, allowed):
        assert enabled is True and expected == (456, 2) and allowed()
        calls.append(enabled)
        return {'state': 'confirmed', 'verified': True, 'enabled': True}
    ctl.set_infinite_ammo = toggle
    monkeypatch.setattr(I, 'native_controller', lambda _: ctl)
    monkeypatch.setattr(I.time, 'time', lambda: clock[0])
    def handler(request):
        body = json.loads(request.content)
        if request.url.path.endswith('/claim'):
            assert 'set_infinite_ammo' in body['capabilities']
            assert body['options']['infinite_ammo']['enabled'] is False
            assert body['options']['grenade_kinds'][0]['kind'] == 'flash'
            if change == 'player': life[0] = 3
            if change == 'expired': clock[0] = 111
            if change == 'stopped': running[0] = False
            return httpx.Response(200, json={'requests': [{'id': 'click', 'claim': 'once',
                'op': 'set_infinite_ammo', 'args': {'enabled': True}, 'expires': 110, 'epoch': body['epoch']}]})
        results.extend(body['results'])
        running[0] = False
        return httpx.Response(200, json={})
    original = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)))
    I.worker_loop('sid', 'http://fixture', {}, ad, lambda: {}, lambda: running[0])
    assert calls == ([True] if change == 'none' else [])
    assert results[0]['result']['state'] == ('confirmed' if change == 'none' else 'unavailable')
