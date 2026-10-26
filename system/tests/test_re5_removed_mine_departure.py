"""A witnessed, removed bomb must not strand the player defenseless at a blocked exit."""
from types import SimpleNamespace

import pytest

from gbox.mercs.titles import re5_mines as M, re5_ps3 as R
from test_re5_mine_survival import state
from test_re5_mercs import world, with_prompt, PLAYER, ENEMIES


def blocked_departure(tmp_path, monkeypatch):
    bot = R.Bot(learn_dir=tmp_path, clock=lambda: 1.)
    snap, _ = state()
    snap['bonuses'] = []
    escape = {'actor': 9, 'pos': (0., 0., 0.), 'at': 0., 'hazards': {9: (0., 0., 0.)},
              'detonation_observed': True, 'removal_recorded': True}
    bot.mines = SimpleNamespace(escape=escape, clear_escape=lambda *a: False)
    monkeypatch.setattr(snap['nav'], 'retreat', lambda *a, **kw: None)
    return bot, snap, escape


def test_witnessed_removal_releases_real_controller_and_outer_combat_but_not_plant_lock(tmp_path, monkeypatch):
    bot, snap, escape = blocked_departure(tmp_path, monkeypatch)
    ground = {}
    monkeypatch.setattr(M, 'ground_mines', lambda _: ground)
    monkeypatch.setattr(M, 'settings', lambda: dict(M.DEFAULT, interval_s=3.))
    bot.mines = controller = M.Controller(SimpleNamespace(), bot.stats, lambda *a: None)
    bot.observe_round(snap, 'playing', 0.)
    escape.pop('detonation_observed')
    escape.pop('removal_recorded')
    controller.escape = escape
    controller.scope_player = snap['player']['ptr']
    ground[9] = {'pos': escape['pos'], 'arming_s': 0., 'detonating': True}
    controller.tick(snap, .1)
    assert escape.get('detonation_observed') and not escape.get('removal_recorded')
    ground.clear()

    action = bot.tick(snap)
    assert escape['removal_recorded']
    assert action.get('hold') or action.get('tap')  # normal nearby-enemy handling receives input again
    assert bot.stats['phase'] != 'leave_proximity_bomb'
    assert bot.stats['mine_departure_yielded'] and bot.nav_dynamic_mines == {}
    assert controller.escape is escape and not bot.stats.get('mine_retreats_completed')
    # A safe placement preflight and elapsed cadence still cannot permit another mine at this site.
    snap['mine_placement_safe'] = True
    controller.tick(snap, 10.)
    assert controller.escape is escape and controller.pending is None
    assert not bot.stats.get('mine_attempts')
    assert not controller.clear_escape(11., (599., 0., 0.))
    assert controller.clear_escape(12., (601., 0., 0.))
    assert bot.stats['mine_retreats_completed'] == 1


@pytest.mark.parametrize('fault', ['not_detonated', 'not_removed', 'missing_scan', 'unverified_scan',
                                  'live_actor', 'reused_actor', 'other_mine', 'multiple_retained', 'wrong_actor'])
def test_blocked_departure_never_yields_without_exact_single_removed_hazard(tmp_path, monkeypatch, fault):
    bot, snap, escape = blocked_departure(tmp_path, monkeypatch)
    if fault == 'not_detonated': escape.pop('detonation_observed')
    elif fault == 'not_removed': escape.pop('removal_recorded')
    elif fault == 'missing_scan': snap.pop('ground_mines')
    elif fault == 'unverified_scan': snap['ground_mines'] = M.GroundMines()
    elif fault in ('live_actor', 'reused_actor', 'other_mine'):
        actor = 10 if fault == 'other_mine' else 9
        pos = (2000., 0., 0.) if fault != 'live_actor' else escape['pos']
        snap['ground_mines'] = {actor: {'pos': pos, 'arming_s': 0., 'detonating': False}}
    elif fault == 'multiple_retained': escape['hazards'][10] = (10., 0., 0.)
    else: escape['hazards'] = {10: escape['pos']}
    assert bot._mine_retreat(snap['player'], snap, 1.) == {'hold': set()}
    assert bot.mines.escape is escape and not bot.stats['mine_departure_yielded']
    assert bot.nav_dynamic_mines  # no retained/live obstacle was silently discarded


@pytest.mark.parametrize('blocked', ['missing_mesh', 'off_mesh'])
def test_removed_bomb_allows_defense_when_floor_recovery_has_no_action(tmp_path, monkeypatch, blocked):
    bot, snap, escape = blocked_departure(tmp_path, monkeypatch)
    if blocked == 'missing_mesh': snap['nav'] = None
    else:
        monkeypatch.setattr(snap['nav'], 'find', lambda *a, **kw: None)
        monkeypatch.setattr(bot, '_recover_nav', lambda *a: {'hold': set()})
    bot.nav_dynamic_mines = {('retained', 9): {'pos': escape['pos']}}
    assert bot._mine_retreat(snap['player'], snap, 1.) is None
    assert bot.nav_dynamic_mines == {} and bot.mines.escape is escape
    assert bot.stats['mine_departure_yielded']


def test_released_departure_does_not_leave_optional_navigation_prompt_blocked(tmp_path, monkeypatch):
    bot, snap, _ = blocked_departure(tmp_path, monkeypatch)
    assert bot._mine_retreat(snap['player'], snap, 1.) is None
    assert bot.prompt_ok('square', snap | {'stage_prompt': True}, 1.)
    assert not bot.prompt_ok('square', snap | {'ground_mines': M.GroundMines()}, 1.1)

    memory = with_prompt(world(enemies=[((0., 0., 150.), 0, 800)]), R.BTN_MELEE, PLAYER, ENEMIES[0])
    stats = {'mine_escape_active': True, 'mine_departure_yielded': True}
    source = R.RE5PS3().prompt_source(memory, stats)
    monkeypatch.setattr(R, 'egg_square_blocked', lambda *a: False)
    scan = [{}]
    monkeypatch.setattr(M, 'ground_mines', lambda _: scan[0])
    assert source() == 'square'
    scan[0] = M.GroundMines()
    assert source() is None  # a prior release cannot waive a fresh incomplete observation
    scan[0] = {9: {'pos': (0., 0., 0.)}}
    assert source() is None
    scan[0] = {}
    stats['mine_placement_pending'] = True
    assert source() is None
