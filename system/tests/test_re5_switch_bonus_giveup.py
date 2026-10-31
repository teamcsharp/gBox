"""RE5 Switch time-bonus give-up (damage cluster #5079, bonus_missed): a statue that stands in reach and will not
break (no snap prompt on the live Switch, off his level, or behind a wall) is now capped - a full knife, then the
next open one - instead of being swung at forever while the other statues go missed. The cluster's examples (150 seen
/ 12 taken / 138 missed per round) are the run locked on one unbreakable statue, the other 138 never targeted; this
test rebuilds that situation from the recorded fields and checks the run leaves it and targets the rest.
"""
import math

import pytest

from gbox.mercs.titles import re5_switch as R

KNIFE_TRY_S, KNIFE_RETRIES, BONUS_BLOCK_S, KNIFE_CAP_S = R.KNIFE_TRY_S, R.KNIFE_RETRIES, R.BONUS_BLOCK_S, R.KNIFE_CAP_S


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(R, "PS3_BRAIN", False)
    monkeypatch.setattr(R, "HEAL_ENABLED", False)
    R._BONUS_SCAN.update(at=-1e9, list=None, line=None, full_at=-1e9)


def at(dist, deg, y=0.0):
    a = math.radians(deg)
    return (dist * math.sin(a), y, dist * math.cos(a))


def snap(enemies=(), bonuses=(), timer=100.0):
    return {"player": {"ptr": 0x5D00001000, "pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000,
                       "motion": 0},
            "enemies": [{"ptr": 10 + i, "pos": x, "hp": 800, "hp_max": 800} for i, x in enumerate(enemies)],
            "inventory": [], "timer": timer,
            "bonuses": [{"ptr": 0x5D4A000000 + i, "pos": x, "secs": 60} for i, x in enumerate(bonuses)],
            "laser": {"from": (0, 0, 0), "at": (0, 0, 0), "up": False}}


def bot():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


# the cluster's representative situation: one statue in reach (d < KNIFE_R) with no snap prompt, and a second one open
# a little way off - the live bot used to be locked on the first forever, the second (and the other 136 of the round's
# 138 missed) never targeted.
STUCK = at(80, 0)         # 0.8 m: in reach, facing dead on (err 0 < KNIFE_FACE) - the knife swings, breaks nothing
OTHER = at(1200, 45)      # 12 m off, a second open statue
STUCK_PTR, OTHER_PTR = 0x5D4A000000, 0x5D4A000001
# the cap must fire within a bounded number of ticks, well under the old "forever" behaviour.
TICK_S, MAX_T = 0.1, 200


def run_until_gave_up(b, clock):
    """Drive the bot while both statues stay; return (tick index, act) it gave up on the stuck one (else (None, None))."""
    for k in range(1, MAX_T + 1):
        clock[0] = TICK_S * k
        act = b.tick(snap(bonuses=[STUCK, OTHER]))
        if b._bonus is None and b._bonus_block.get(STUCK_PTR, -1e9) > clock[0]:
            return k, act
    return None, None


def test_an_unbreakable_statue_in_reach_is_gone_after_a_few_swings_not_forever():
    b, clock = bot()
    b.tick(snap(bonuses=[STUCK, OTHER]))                   # locked on the nearest (the stuck one): the knife starts
    gave, act = run_until_gave_up(b, clock)
    assert gave is not None, "the run never gave up: the statue was swung at forever (the cluster's 138 missed)"
    assert clock[0] < TICK_S * 60, "the give-up lingered on the dead one past the cap"
    assert act["hold"] == ("lup",) and "will not break" in b.why


def test_the_run_leaves_the_unbreakable_one_and_targets_the_next():
    b, clock = bot()
    b.tick(snap(bonuses=[STUCK, OTHER]))
    gave, _ = run_until_gave_up(b, clock)
    assert gave is not None
    # on the very next tick the run is on the other open statue, running at it
    clock[0] = TICK_S * (gave + 1)
    b.tick(snap(bonuses=[STUCK, OTHER]))
    assert b._bonus is not None and b._bonus["ptr"] == OTHER_PTR, f"run not on the next open statue: {b._bonus!r}"
    assert "time bonus" in b.why and b.doing == "walk"
    assert b.stats["bonus_runs"] == 2                        # a second run started, after the first gave up


def test_the_give_up_is_blocked_for_the_block_window_then_free():
    b, clock = bot()
    b.tick(snap(bonuses=[STUCK, OTHER]))
    gave, _ = run_until_gave_up(b, clock)
    assert gave is not None
    gave_at = clock[0]
    # right after the give-up the stuck one is blocked: the next run picks the other statue, not the dead one
    clock[0] = gave_at + 0.2
    b.tick(snap(bonuses=[STUCK, OTHER]))
    if b._bonus is not None:
        assert b._bonus["ptr"] != STUCK_PTR, "the blocked statue was re-targeted inside its give-up window"
    # after the block window laps, the run can target the stuck one again (not dropped for the whole round)
    clock[0] = gave_at + BONUS_BLOCK_S + 1.0
    b.tick(snap(bonuses=[STUCK, OTHER]))
    assert b._bonus is not None, "after the block window the run is not back on an open statue"


def test_a_statue_that_breaks_is_still_taken_before_any_give_up():
    # the happy path must not change: a statue that disappears from the scan while he is on it is counted taken
    b, clock = bot()
    b._round_started = b._round_t0 = 0.0
    b.tick(snap(bonuses=[at(70, 3), OTHER]))
    clock[0] = 0.5
    b.tick(snap(bonuses=[at(70, 3)], timer=100.0))         # the second one gone (broken/taken elsewhere)
    assert b.stats["bonuses_taken"] == 1 and b.stats["bonuses_left"] == 1
    clock[0] = 2.0
    b.tick(snap(bonuses=[], timer=104.0))                   # the last one gone: the run ended, taken
    assert b.stats["bonuses_taken"] == 2 and b.stats["bonuses_left"] == 0 and b.stats["bonus_time_s"] == 2.0


def test_a_shown_prompt_is_walked_into_not_capped_by_the_prompt_branch():
    # the live fault: the snap prompt reader reads (prompt_read) but its selected prompt never comes (label 112,
    # "up 23 samples in six minutes, never pressed", bonuses_taken 0) - the run used to walk into that statue
    # forever instead of the knife: now a reader miss falls back to the knife, and a dead one is capped
    b, clock = bot()
    b.tick(snap(bonuses=[STUCK, OTHER]))                   # locked on the stuck one
    gave, act = None, None
    for k in range(1, MAX_T + 1):
        clock[0] = TICK_S * k
        s2 = dict(snap(bonuses=[STUCK, OTHER]))
        s2["prompt_read"] = True                           # the reader reads - but selected_prompt returns None
        act = b.tick(s2)
        if b._bonus is None and b._bonus_block.get(STUCK_PTR, -1e9) > clock[0]:
            gave = k
            break
    assert gave is not None, "the run never gave up: it walked into the no-prompt statue forever (the cluster's fault)"
    # the very last tick still walked into it; on the next one the run is on the other open statue
    clock[0] = TICK_S * (gave + 1)
    b.tick(snap(bonuses=[STUCK, OTHER]))
    assert b._bonus is not None and b._bonus["ptr"] == OTHER_PTR, f"run not on the next open statue: {b._bonus!r}"
    assert b.stats["bonus_runs"] == 2                       # a second run started, after the first gave up


def test_cluster_count_shape_seen_minus_taken():
    # the fault's value is seen - taken; the fix lowers the missed count by giving up early, not by dropping seen
    b, clock = bot()
    b.tick(snap(bonuses=[STUCK, OTHER]))
    gave, _ = run_until_gave_up(b, clock)
    assert gave is not None
    seen, taken = b.stats["bonuses_seen"], b.stats["bonuses_taken"]
    assert seen == 2 and taken == 0 and seen - taken == 2   # both seen, none taken: the fault still counts both misses
    assert b._bonus is not None or b._bonus_block.get(STUCK_PTR, -1e9) > clock[0], \
        "after the give-up the run must be on the live one (or the dead one still inside its block window)"
    assert b._bonus_block.get(STUCK_PTR, -1e9) > clock[0]   # the dead one is the one blocked, the live one targeted
