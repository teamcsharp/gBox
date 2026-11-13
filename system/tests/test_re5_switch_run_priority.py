"""The Mercenaries run collects time statues before a distant hunt or combo stand."""
import pytest

from gbox.mercs.titles import re5_switch as R
from tests.test_re5_switch_bonus import at, snap
from tests.test_re5_switch_directives import command, GUN


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setattr(R, 'PS3_BRAIN', False)
    monkeypatch.setattr(R, 'HEAL_ENABLED', False)
    clock = [1.]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    bot._round_started = 0.
    bot._new_round(0.)
    bot._start_facing_done = True
    return bot, clock


@pytest.mark.parametrize('mode', ['hunt', 'rush', 'score'])
@pytest.mark.parametrize('timer', [119., 330.])
def test_mines_spawn_runs_to_time_statue_before_distant_hunt_or_score_stand(runner, mode, timer):
    # Round 43273846 began hunting a foe 25.4 m away, then its kill extensions
    # kept the clock above 120 s for 254 s. Eight time bonuses went untouched.
    b, clock = runner
    s = snap(enemies=[at(2540, 0)], bonuses=[at(2700, -90), at(4000, 20)], timer=timer)
    s.update(combo=20, combo_timer=1.)
    command(b, mode, 60)
    action = b.tick(s)
    assert 'time bonus' in b.why and b._bonus['ptr'] == s['bonuses'][0]['ptr']
    assert {'b', 'lup'} <= set(action['hold']) and 'zl' not in action['hold']
    assert b.stats['bonus_runs'] == 1


def test_bonus_run_precedes_four_metre_crowd_rampage(runner, monkeypatch):
    b, clock = runner
    monkeypatch.setattr(R, 'RAMPAGE', True)
    s = snap(enemies=[at(400, a) for a in (-25, 0, 25)], bonuses=[at(1400, -90)], timer=330.)
    s['inventory'] = [dict(GUN)]
    b.tick(s)
    assert 'time bonus' in b.why and b._bonus is not None
    assert b.stats['rampage_shots'] == 0


def test_point_blank_threat_is_fought_then_same_bonus_run_resumes(runner):
    b, clock = runner
    s = snap(enemies=[at(900, 0)], bonuses=[at(1400, 5)], timer=330.)
    s['inventory'] = [dict(GUN)]
    b.tick(s)
    selected = b._bonus['ptr']
    clock[0] += .2
    s['enemies'][0]['pos'] = at(150, 0)
    action = b.tick(s)
    assert 'time bonus' not in b.why and 'zl' in action.get('hold', ())
    clock[0] += .2
    s['enemies'][0]['hp'] = 0
    b.tick(s)
    assert 'time bonus' in b.why and b._bonus['ptr'] == selected
    assert b.stats['bonus_runs'] == 1


def test_collects_next_bonus_then_returns_to_enemy_hunt_after_last_is_taken(runner):
    b, clock = runner
    s = snap(enemies=[at(2500, 0)], bonuses=[at(1400, -45), at(2800, 60)], timer=330.)
    command(b, 'hunt', 60)
    b.tick(s)
    assert b._bonus['ptr'] == s['bonuses'][0]['ptr']
    s['bonuses'] = s['bonuses'][1:]
    s['player']['pos'] = (0., 0., 100.)
    clock[0] += .2
    b.tick(s)
    assert b._bonus['ptr'] == s['bonuses'][0]['ptr'] and b.stats['bonuses_taken'] == 1
    s['bonuses'] = []
    s['player']['pos'] = (0., 0., 200.)
    clock[0] += .2
    action = b.tick(s)
    assert b.why.startswith('hunt:') and 'lup' in action['hold']
    assert b.stats['bonuses_taken'] == 2 and b.stats['bonuses_left'] == 0


def test_active_escape_precedes_a_new_bonus_route(runner):
    b, clock = runner
    s = snap(enemies=[at(900, 0)], bonuses=[at(1400, 5)], timer=330.)
    b.escape = (.8, 3.)
    b.tick(s)
    assert b.escape == (.8, 3.) and b._bonus is None
    assert 'time bonus' not in b.why
