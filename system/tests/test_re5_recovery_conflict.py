"""Replay the observed empty-corridor stall without disabling real grab response."""
import math
import pytest
from gbox.mercs.titles import re5_switch as R

@pytest.fixture
def run(monkeypatch):
    for key in ('PS3_BRAIN', 'HEAL_ENABLED', 'MINES', 'CALM'):
        monkeypatch.setattr(R, key, False)
    clock = [0.]
    bot = R.Bot(stats={}, clock=lambda: clock[0])
    bot._round_started = bot._round_t0 = 0.
    return bot, clock

def snapshot(motion=4):
    return {'player': {'ptr': 0x5D00001000, 'pos': (0., 0., 0.), 'rot': 0.,
                       'hp': 1000, 'hp_max': 1000, 'motion': motion, 'aim_pitch': None},
            'enemies': [], 'inventory': [], 'kills': 0,
            'bonuses': [{'ptr': 900, 'pos': (0., 313., 1500.), 'secs': 30}],
            'laser': {'from': (0., 0., 0.), 'at': (0., 0., 0.), 'up': False}}

@pytest.mark.parametrize('motion', [4, 20, 96])
def test_known_non_grab_motion_does_not_repeatedly_mash_in_empty_corridor(run, motion):
    bot, clock = run
    assert motion not in R.MOTION_HELD
    actions = []
    for tick in range(100):
        clock[0] = tick * .08
        actions.append(bot.tick(snapshot(motion)))
        assert bot.doing != 'held'
    assert bot.stats['holds'] == bot.stats['wiggles'] == 0
    assert bot.stats['wall_hits'] > 0
    assert any('ldown' in action.get('hold', ()) for action in actions)

@pytest.mark.parametrize('motion', sorted(R.MOTION_HELD))
def test_real_native_grab_preempts_recovery(run, motion):
    bot, clock = run
    bot._wall_start(snapshot()['player'], 0., preempt=False)
    bot.tick(snapshot(motion))
    assert bot.doing == 'held' and bot._wall_rec is None

def test_missing_motion_retains_bounded_legacy_break_free_fallback(run):
    bot, clock = run
    states = []
    for tick in range(40):
        clock[0] = tick * .08
        bot.tick(snapshot(None))
        states.append(bot.doing)
    assert 'held' in states

def test_actual_break_free_prompt_keeps_priority(run):
    bot, clock = run
    snap = snapshot()
    snap['prompt'] = {'label': R.re5_switch_prompt.LABEL_BREAK_FREE}
    bot.tick(snap)
    assert bot.doing in ('held', 'prompt')
