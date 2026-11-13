from types import SimpleNamespace

import pytest

from gbox.mercs.titles.re5_mine_escape import execute


@pytest.mark.parametrize('ring,count', [(False, 1), (True, 5)])
def test_manual_armed_drop_keeps_inputs_free_and_publishes_hazards(ring, count):
    calls, stats = [], {}
    def flash(kind, **kw):
        assert kind == 'flash' and kw['allowed']() and kw['expected'] == (10, 2)
        calls.append('flash')
        return dict(state='confirmed', verified=True, detonated=5)
    def mines(n, **kw):
        assert n == count and kw['allowed']() and kw['expected'] == (10, 2)
        calls.append('mines')
        kw['on_deployed']({'unit': 42, 'generation': 8, 'pos': (0, 0, 0), 'armed_observed': False})
        assert stats['native_mine_force_hazards'][0]['mine']['armed_observed'] is False
        assert 'native_mine_force_receipts' not in stats
        return dict(state='confirmed', verified=True, placed=n, armed=n, mines=[{'unit': 42}])
    ctl = SimpleNamespace(ready=lambda: (10, 2), grenade_ring=flash, proximity_mines=mines)
    out = execute(ctl, count, ring=ring, allow_unverified=False, allowed=lambda: True,
                  stats=stats, request_id='click', round_id='round')
    assert calls == (['flash', 'mines'] if ring else ['mines'])
    assert out['state'] == 'confirmed'
    assert stats['native_mine_force_receipts'][0]['owner'] == ['round', 10, 2]
    assert stats['native_mine_force_hazards'][0]['owner'] == ['round', 10, 2]
    assert 'native_weapon_pending' not in stats


@pytest.mark.parametrize('failure', ['flash', 'changed', 'unarmed', 'partial'])
def test_failed_cover_or_unarmed_mines_never_report_success(failure):
    life, calls, stats = [2], [], {}
    def flash(*a, **kw):
        if failure == 'changed': life[0] = 3
        return dict(state='uncertain' if failure == 'flash' else 'confirmed', verified=True, detonated=5)
    def mines(*a, **kw):
        calls.append('mines')
        return dict(state='confirmed', verified=True, placed=4 if failure == 'partial' else 5,
                    armed=0 if failure == 'unarmed' else 4, mines=[{'unit': 42}])
    ctl = SimpleNamespace(ready=lambda: (10, life[0]), grenade_ring=flash, proximity_mines=mines)
    out = execute(ctl, 5, ring=True, allow_unverified=False, allowed=lambda: True,
                  stats=stats, request_id='click', round_id='round')
    assert out['state'] == 'uncertain' and out['verified'] is False
    assert len(calls) == (0 if failure in ('flash', 'changed') else 1)


def test_player_loss_after_arming_keeps_receipt_without_sending_hazards_to_next_life():
    from gbox.mercs.titles.re5_switch_native import Unavailable
    active, stats = [True], {}
    def ready():
        if not active[0]:
            raise Unavailable('player ended')
        return (10, 2)
    def mines(*a, **kw):
        active[0] = False
        return dict(state='confirmed', verified=True, placed=1, armed=1, mines=[{'unit': 42}])
    ctl = SimpleNamespace(ready=ready, proximity_mines=mines)
    result = execute(ctl, 1, ring=False, allow_unverified=False, allowed=lambda: True,
                     stats=stats, request_id='click', round_id='round')
    assert result['state'] == 'confirmed' and result['armed'] == 1
    assert not stats.get('native_mine_force_receipts')


def test_large_combined_receipt_keeps_flash_and_armed_counts_for_the_button(monkeypatch, tmp_path):
    import json
    from gbox.mercs import interventions as I
    monkeypatch.setattr(I, 'RECEIPT_ROOT', tmp_path)
    result = {'state': 'confirmed', 'verified': True, 'requested': 5, 'placed': 5,
              'armed': 5, 'flash_detonated': 5, 'hp_loss_observed': 0,
              'mines': [{'index': i, 'detail': 'x' * 1000} for i in range(5)]}
    summary = I.completion_receipt(result, session_id='session', request_id='request')
    assert summary['receipt_compacted'] and len(json.dumps(summary)) <= I.RECEIPT_LIMIT
    assert summary['flash_detonated'] == summary['armed'] == 5
    assert summary['hp_loss_observed'] == 0
