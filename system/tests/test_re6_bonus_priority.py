"""Current-clock time run priority, with the final movement/defense pipeline intact."""
import time

import pytest

from gbox.mercs import directives
from gbox.mercs.titles import re6_switch as R
from test_re6_switch import _fresh_caches, lock_brain, run
from test_re6_switch_parity import command, square, mark


def scene(distance=None, timer=180.):
    enemies = () if distance is None else ((0., 0., distance, 700),)
    bot, clock, snap, writes = lock_brain(enemies)
    # out of BONUS_SHOOT_R: these cases exercise the walked time run; the ranged shot has its own test below
    snap.update(timer=timer, bonuses=[{'ptr': 1234, 'kind': 'time', 'pos': (0., 0., 4000.)}],
                navmesh=square(4000.))
    bot.combo_prev, bot._combo_full = 2, 15.
    snap['combo_timer'] = 8.
    return bot, clock, snap, writes


def test_a_blue_time_crystal_waits_when_the_combo_is_about_to_lapse():
    # Live 2026-11-14: "a time bonus at 2095 cm: the lock on it" was an attributed combo break. The kill comes first.
    bot, clock, snap, writes = scene(2500., timer=180.)
    snap['bonuses'] = [{'ptr': 1234, 'kind': 'time', 'pos': (0., 0., 1200.)}]
    bot._time_bonus_priority = lambda *a, **k: True
    bot._bonus_sight = lambda *a, **k: True
    bot._bonus_shoot = lambda *a, **k: {'hold': ('zl', 'zr')}
    bot._combo_hot_now = True
    assert bot._time_bonus_shot(snap['player'], snap, clock[0]) is None
    assert bot.stats['time_bonus_yields_combo'] == 1
    bot._combo_hot_now = False
    assert bot._time_bonus_shot(snap['player'], snap, clock[0]) == {'hold': ('zl', 'zr')}


def test_a_blue_time_crystal_in_range_is_shot_instead_of_only_walked_to():
    # Operator 2026-11-14: "activating combo time via ... shooting / destroying blue time bonus crystals (RE6)".
    bot, clock, snap, writes = scene(2500., timer=180.)
    snap['bonuses'] = [{'ptr': 1234, 'kind': 'time', 'pos': (0., 0., 1200.)}]
    bot._time_bonus_priority = lambda *a, **k: True
    bot._bonus_sight = lambda *a, **k: True
    bot._bonus_shoot = lambda *a, **k: {'hold': ('zl', 'zr')}
    out = bot._time_bonus_shot(snap['player'], snap, clock[0])
    assert out == {'hold': ('zl', 'zr')} and bot.stats['time_bonus_shots'] == 1


def test_below_the_bank_a_distant_enemy_does_not_stop_the_time_run_and_a_close_one_does():
    # Operator 2026-11-14, the match strategy: "initially go after the time bonuses throughout the level while
    # building initial combo ... once the time is at 5 minutes, the strategy can go into fighting". Below the bank
    # (timer 180) a distant enemy (beyond FIRE_ZONE_R) does not veto the time-bonus run; anything close (hot) does.
    bot, clock, snap, writes = scene(450.)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'
    bot, clock, snap, writes = scene(2500.)                    # visible, but past FIRE_ZONE_R
    out = run(bot, snap, clock, 1)[0]
    assert bot.combo_pace and bot.stats['act'] == 'bonus_run'
    assert set(out.get('hold', ())) & {'lup', 'ldown', 'lleft', 'lright'}
    assert 'zl' not in out.get('hold', ()) and not writes


def test_at_the_five_minute_bank_the_bot_fights_instead_of_running_bonuses():
    # "once the time is at 5 minutes, the strategy can go into fighting, traps and combo maintenance"
    bot, clock, snap, writes = scene(2500., timer=350.)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run' and bot._bonus_clock_ready(snap)


@pytest.mark.parametrize('timer', [0., 120., 180., 299.99, None, float('nan'), True])
def test_time_run_uses_current_finite_clock_without_truthy_zero(timer):
    bot, clock, snap, writes = scene(timer=timer)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'bonus_run'
    assert not bot._bonus_wait(snap)


def test_five_minute_bank_allows_score_then_resumes_time_run_below_threshold():
    bot, clock, snap, writes = scene(timer=300.)
    run(bot, snap, clock, 1)
    assert bot.stats['act'] != 'bonus_run'
    snap['timer'] = 299.9
    run(bot, snap, clock, 1)
    assert bot.stats['act'] == 'bonus_run'


@pytest.mark.parametrize('mode,distance', [('fight', None), ('hunt', None), ('score', None)])
def test_automatic_modes_yield_to_time_run(mode, distance):
    bot, clock, snap, writes = scene(distance)
    command(bot, mode)
    run(bot, snap, clock, 1)
    assert bot.mode == mode and bot.stats['act'] == 'bonus_run'


@pytest.mark.parametrize('mode,distance', [('fight', None), ('hunt', None), ('score', None)])
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
    # Operator 2026-11-14: remote bombs have no proximity trigger (see BOMB_TRAVEL_MIN_CM); the escape's contract is
    # the final floor guard (bomb_escape_output), not staying 250 cm from a bomb - requiring that froze the radial run.
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


def test_no_native_route_never_becomes_a_direct_bonus_walk():
    # the bonus is out of the nav mesh: the bot may face/rotate toward it, but never walks (no stick walk keys) and
    # never writes RAM for it
    bot, clock, snap, writes = scene(None)
    snap['bonuses'][0]['pos'] = (9000., 0., 0.)
    out = run(bot, snap, clock, 1)[0]
    assert not any(k in out.get('hold', ()) for k in ('lup', 'ldown', 'lleft', 'lright'))
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
