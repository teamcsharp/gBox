"""Current-clock time run priority, with the final movement/defense pipeline intact."""
import time

import pytest

from gbox.mercs import directives
from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, lock_brain, run
from test_re6_switch_parity import command, square, mark


def scene(distance=450., timer=180.):
    enemies = () if distance is None else ((0., 0., distance, 700),)
    bot, clock, snap, writes = lock_brain(enemies)
    snap.update(timer=timer, bonuses=[{'ptr': 1234, 'kind': 'time', 'pos': (0., 0., 900.)}],
                navmesh=square(2000.))
    bot.combo_prev, bot._combo_full = 2, 15.
    snap['combo_timer'] = 8.
    return bot, clock, snap, writes


def test_visible_enemy_and_overdue_combo_do_not_starve_time_run():
    bot, clock, snap, writes = scene()
    out = run(bot, snap, clock, 1)[0]
    assert bot.combo_pace and bot.stats['act'] == 'bonus_run'
    assert set(out.get('hold', ())) & {'lup', 'ldown', 'lleft', 'lright'}
    assert 'zl' not in out.get('hold', ()) and not writes


@pytest.mark.parametrize('timer', [0., 120., 180., 299.99, None, float('nan'), True])
def test_time_run_uses_current_finite_clock_without_truthy_zero(timer):
    bot, clock, snap, writes = scene(timer=timer)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'bonus_run'
    assert not bot._bonus_wait(snap)


def test_five_minute_bank_allows_score_then_resumes_time_run_below_threshold():
    bot, clock, snap, writes = scene(timer=300.)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run' and bot._bonus_wait(snap)
    snap['timer'] = 299.9
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'bonus_run'


@pytest.mark.parametrize('mode,distance', [('fight', 450.), ('hunt', 1500.), ('hunt', 450.), ('score', 450.)])
def test_automatic_modes_yield_to_time_run(mode, distance):
    bot, clock, snap, writes = scene(distance)
    command(bot, mode)
    run(bot, snap, clock, 1)
    assert bot.mode == mode and bot.stats['act'] == 'bonus_run'


@pytest.mark.parametrize('mode,distance', [('fight', 450.), ('hunt', 1500.), ('hunt', 450.), ('score', 450.), ('score', 900.)])
def test_explicit_modes_keep_priority_then_expire(mode, distance):
    bot, clock, snap, writes = scene(distance)
    command(bot, mode)
    row = directives.post('re6-time-priority-'+mode, mode)
    directives.apply_to_stats(bot.stats, row)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'
    bot.stats['directive_until'] = time.time()-1
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'bonus_run'
    bot.stats['doctrine_directive_until'] = time.time()-1
    run(bot, snap, clock, 1)
    assert bot.mode is None and bot.stats['act'] == 'bonus_run'


def test_fresh_expired_explicit_command_still_gets_its_single_delivery():
    bot, clock, snap, writes = scene()
    command(bot, 'fight')
    directives.apply_to_stats(bot.stats, {'command': 'fight', 'seq': 'fresh-expired',
                                        'at': time.time()-20, 'until': time.time()-1})
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'bonus_run'


def test_close_enemy_still_preempts_the_time_run():
    bot, clock, snap, writes = scene(250.)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'


def test_recent_ranged_damage_still_preempts_the_time_run():
    bot, clock, snap, writes = scene(900.)
    bot._hz_break_at = 0.
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'ranged_break'


def test_native_remote_escape_retains_final_floor_and_bomb_clearance():
    from gbox.mercs.titles import re6_movement_safety as S
    from test_re6_movement_safety import end
    bot, clock, snap, writes = scene(250.)
    bomb = {'unit': 10, 'generation': 1, 'kind': 'remote', 'pos': [0., 0., -200.],
            'action': 'cWpAction_wp_act_setting'}
    snap.update(throwables=[bomb])
    snap['player'].update(equipped=0, action='cPlAction_pl_act_walk', bomb={'out': True, 'armed': True})
    bot.stats.update(mine_escape_required=True, mine_avoid_positions=[bomb['pos']])
    out = run(bot, snap, clock, 1)[0]
    assert bot.stats['act'] == 'bomb_escape'
    assert set(out['hold']) & S.LEFT and not {'zl', 'zr'} & set(out['hold'])
    assert S._bomb_clear(bot, snap, snap['player']['pos'], end(snap, out['hold']))
    assert bot.stats['bomb_escape_output']['final_hold'] == list(out['hold'])
    assert not writes


def test_explicit_map_goal_precedes_the_time_run(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'MAP_GOAL_LOG', tmp_path / 'goals.jsonl')
    bot, clock, snap, writes = scene(None)
    mark(bot, 'point', 0, (900., 0., 0.))
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'map_goal_walk'


def test_unknown_command_reader_is_not_demoted_to_automatic():
    bot, clock, snap, writes = scene()
    command(bot, 'fight')
    class UnknownReader:
        seen = None  # a similarly named attribute does not prove the native reader contract
        def current(self, *args):
            return 'fight', True
    bot.commands = UnknownReader()
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'


def test_explicit_command_arriving_during_reader_call_keeps_priority(monkeypatch):
    bot, clock, snap, writes = scene()
    command(bot, 'fight')
    original = directives.Reader.current
    def arriving(reader, stats, now=None):
        directives.apply_to_stats(stats, {'command': 'fight', 'seq': 'arriving-during-read',
                                         'at': time.time(), 'until': time.time()+20})
        return original(reader, stats, now)
    monkeypatch.setattr(directives.Reader, 'current', arriving)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'
    assert not bot._mode_is_automatic


def test_grab_and_critical_heal_still_preempt_the_time_run():
    bot, clock, snap, writes = scene()
    snap['player']['state'] = 8
    run(bot, snap, clock, 1)
    assert bot.doing == 'held'
    snap['player'].update(state=0, hp=180, tablets=8)
    run(bot, snap, clock, 1)
    assert bot.doing == 'tablet'


def test_no_native_route_cannot_become_a_direct_bonus_walk():
    bot, clock, snap, writes = scene(None)
    snap['bonuses'][0]['pos'] = (5000., 0., 0.)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run' and bot.stats['bonus_skips'] == 1
    assert not writes


def test_combo_pickups_wait_for_time_bank_but_not_for_missing_or_skipped_time_targets():
    bot, clock, snap, writes = scene(None)
    green = {'ptr': 1235, 'kind': 'combo', 'pos': (0., 0., 100.)}
    snap['bonuses'].append(green)
    snap.update(combo=3, combo_timer=1.)
    p = snap['player']
    assert bot._green_save(p, [], lambda e: 9999., snap, 0.) is None
    snap['timer'] = 300.
    assert bot._green_save(p, [], lambda e: 9999., snap, 1.) == {'tap': 'zr'}
    snap['timer'] = 180.
    bot.bonus_skip[1234] = 10.
    assert bot._green_save(p, [], lambda e: 9999., snap, 2.) == {'tap': 'zr'}


def test_unknown_bonus_kind_never_becomes_a_time_run_target():
    bot, clock, snap, writes = scene(None)
    snap['bonuses'][0]['kind'] = 'unknown'
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'
