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
        return dict(state='confirmed', verified=True, placed=n, armed=n, mines=[{'unit': 42}])
    ctl = SimpleNamespace(ready=lambda: (10, 2), grenade_ring=flash, proximity_mines=mines)
    out = execute(ctl, count, ring=ring, allow_unverified=False, allowed=lambda: True,
                  stats=stats, request_id='click', round_id='round')
    assert calls == (['flash', 'mines'] if ring else ['mines'])
    assert out['state'] == 'confirmed'
    assert stats['native_mine_force_receipts'][0]['owner'] == ['round', 10, 2]
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
