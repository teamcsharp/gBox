"""A permanently refused center-slot grenade must not repeatedly stop combat."""
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_switch as R


class Policy:
    def __init__(self):
        self.choices = []

    def observe(self, *args):
        pass

    def decide(self, prof, now, p, live, available, **kwargs):
        self.choices.append(set(available))
        kind = next((k for k in ('hand', 'fire', 'flash') if k in available), None)
        return SimpleNamespace(kind=kind, why='crowd', fleeing=False, target=live[0]) if kind else None

    def started(self, now):
        pass


class Equip:
    def __init__(self):
        self.calls = []
        self.failed = None
        self.result = {'state': 'unknown', 'reason': 'previous_request_unconfirmed'}

    def select(self, grid, item):
        self.calls.append((grid, item))
        self.failed = (100, 7, item)
        return dict(self.result)


def setup(*, fire=False):
    b = R.Bot.__new__(R.Bot)
    b.stats = {'round_evidence_id': 'one'}
    b.mines, b.escape, b.native_equip = None, None, Equip()
    b._gun_down = lambda: None
    b._grenade_last = -1e9
    b._flashed_lately = lambda now: False
    b._uc_throws = Policy()
    b._mastery = lambda *args: {'hold': ('zl', 'zr')}
    b._core_error = lambda exc: pytest.fail(str(exc))
    b._infinite_ammo = True
    p = {'ptr': 100, 'generation': 7, 'hp': 1000, 'pos': (0, 0, 0)}
    s = {'player': p, 'mercenaries_phase': R.PHASE_PLAYING, 'inventory': [
        {'type': 1, 'item': 25, 'id': 0x119, 'grid': 3, 'hand': True, 'rounds': 99},
        {'type': 1, 'item': 6, 'id': 0x106, 'grid': 4, 'hand': False, 'rounds': 1}]}
    if fire:
        s['inventory'].append({'type': 1, 'item': 7, 'id': 0x107, 'grid': 6, 'hand': False, 'rounds': 1})
    return b, s


def tick(b, s, now):
    return b._throw_core(s['player'], s, [{'ptr': 500, 'pos': (0, 0, 800), 'hp': 500}], lambda e: 800, now)


def test_center_slot_permanent_refusal_releases_same_tick_and_future_combat():
    b, s = setup()
    assert tick(b, s, 0) is None
    assert b.native_equip.calls == [(4, 0x106)]
    assert b.stats['throw_equip_blocked_count'] == 1
    assert b.stats['throw_equip_blocked_items'] == '0x106'
    assert b.stats['throw_aborts'] == 1
    for now in (1., 5., 10., 20.):
        assert tick(b, s, now) is None  # caller continues combat; no neutral rearm wait
    assert b.native_equip.calls == [(4, 0x106)]
    assert b.stats['throw_aborts'] == 1
    assert b._uc_throws.choices[-1] == set()


def test_another_available_grenade_can_be_chosen_without_erasing_earlier_refusal():
    b, s = setup(fire=True)
    assert tick(b, s, 0) is None
    assert tick(b, s, 5) is None
    assert b.native_equip.calls == [(4, 0x106), (6, 0x107)]
    assert b.native_equip.failed[-1] == 0x107  # a last-failure field alone would lose 0x106
    assert b.stats['throw_equip_blocked_count'] == 2
    for now in (10., 15.):
        assert tick(b, s, now) is None
    assert len(b.native_equip.calls) == 2


def test_positive_same_owner_hand_observation_allows_actual_throw_without_native_replay():
    b, s = setup()
    assert tick(b, s, 0) is None
    s['inventory'][0]['hand'], s['inventory'][1]['hand'] = False, True
    assert tick(b, s, 1) == {'hold': ('zl', 'zr')}
    assert b.stats['throw_equip_blocked_count'] == 0
    assert b.native_equip.calls == [(4, 0x106)]
    assert b.native_equip.failed == (100, 7, 0x106)  # native uncertainty is not cleared
    assert 'grenade_throws' not in b.stats           # an input is still not a proven throw


@pytest.mark.parametrize('change', ['operator', 'menu', 'dead', 'foreign_snapshot', 'two_hands'])
def test_nonlive_or_foreign_hand_observation_cannot_release_refusal(change):
    b, s = setup()
    tick(b, s, 0)
    s['inventory'][0]['hand'], s['inventory'][1]['hand'] = False, True
    if change == 'operator': b.stats['operator_control'] = True
    if change == 'menu': s['mercenaries_phase'] = -1
    if change == 'dead': s['player']['hp'] = 0
    if change == 'two_hands': s['inventory'][0]['hand'] = True
    if change == 'foreign_snapshot':
        p = dict(s['player'])
        s['player'] = s['player'] | {'generation': 99}
        assert b._throw_core(p, s, [], lambda e: 800, 1) is None
    else:
        assert tick(b, s, 1) is None
    assert b.stats['throw_equip_blocked_count'] == 1
    assert b.native_equip.calls == [(4, 0x106)]


@pytest.mark.parametrize('change', ['round', 'player', 'generation'])
def test_new_lifetime_uses_fresh_native_admission(change):
    b, s = setup()
    tick(b, s, 0)
    if change == 'round': b.stats['round_evidence_id'] = 'two'
    if change == 'player': s['player']['ptr'] = 101
    if change == 'generation': s['player']['generation'] = 8
    b.native_equip.result = {'state': 'requested', 'item': 0x106, 'grid': 4}
    assert tick(b, s, 1) == {'hold': ()}
    assert len(b.native_equip.calls) == 2
    assert b.stats['throw_equip_blocked_count'] == 0
    assert 'throw_equip_refusal' not in b.stats


@pytest.mark.parametrize('result', [
    {'state': 'deferred', 'reason': 'busy_motion'},
    {'state': 'deferred', 'reason': 'changed_witness'},
    {'state': 'waiting', 'reason': 'native_hand_not_confirmed'},
    {'state': 'unknown', 'reason': 'preparation_changed'},
])
def test_deferred_or_still_pending_native_request_keeps_existing_bounded_observation(result):
    b, s = setup()
    b.native_equip.result = result
    assert tick(b, s, 0) == {'hold': ()}
    assert tick(b, s, .5) == {'hold': ()}
    assert b.stats['throw_equip_blocked_count'] == 0
    b.native_equip.result = {'state': 'requested', 'item': 0x106, 'grid': 4}
    assert tick(b, s, 1) == {'hold': ()}
    assert len(b.native_equip.calls) == 3
