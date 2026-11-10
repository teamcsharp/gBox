"""The PiP's quick commands on the Switch Mercenaries bots (operator 2026-11-10: "make sure that when I use one of the quick
commands for guidance to the bot, that it's able to take those commands into consideration").

RE4 Switch read every command only into its "why" line; RE6 Switch said "acting: ..." for repetitive / missing / rush and
did nothing. Each command now changes a decision and says what it did in stats directive_status (the PiP shows it beside
the box). Synthetic snapshots only."""
import time

import pytest

from gbox.mercs import directives as DIR
from gbox.mercs.core import doctrine
from gbox.mercs.titles import re4_switch as D4
from gbox.mercs.titles import re6_switch as R6
from test_re6_switch import _fresh_caches, brain, round_guest, run   # noqa: F401 (the autouse cache fixture)
from test_re4_switch_fight import keys, mm, snap


def operator(stats, cmd, sid="quick-cmd"):
    """The command as the worker's poll writes it: the server's newest row into the live stats (directives.apply)."""
    DIR.apply_to_stats(stats, DIR.post(sid, cmd))


# --- RE4 Switch -------------------------------------------------------------------------------------------------------

def re4_bot():
    b = D4.Bot(stats={}, director=False)
    b.reader = doctrine.Reader()                              # the operator's commands, without the doctrine's own
    return b


def test_re4_every_command_is_taken_and_said():
    for cmd in DIR.COMMANDS:
        b = re4_bot()
        operator(b.stats, cmd, sid="re4-said-" + cmd)
        b.tick(snap([((0.0, 0.0, 2000.0), 400)]), now=10.0)
        assert b.stats["directive_active"] == cmd
        assert b.stats["directive_status"].startswith("acting: " + cmd), (cmd, b.stats["directive_status"])
        assert b.stats["directive_taken"] == 1


def test_re4_hunt_runs_to_the_ganado_past_the_guns_range():
    # (ENGAGE_RANGE_CM 12 m > RUN_CM 8 m: past the gun's range he already runs; the command keeps him at it, said)
    b = re4_bot()
    operator(b.stats, "hunt", sid="re4-hunt")
    act = b.tick(snap([((0.0, 0.0, 2000.0), 400)]), now=10.0)
    assert b.doing == "locate" and D4.RUN_BTN in keys(act) and "(hunt)" in b.why
    assert b.stats["directive_status"].startswith("acting: hunt")
    assert b.__dict__["_cmd"] == "hunt"


def test_re4_explore_drops_the_target_and_runs_off_this_spot():
    s = snap([((0.0, 0.0, 300.0), 400)])                       # one in range he would aim at
    b = re4_bot()
    b.tick(s, now=10.0)
    assert b.target == 100
    operator(b.stats, "explore", sid="re4-explore")
    act = b.tick(s, now=10.1)
    assert b.doing == "walk" and "the operator's explore" in b.why
    assert D4.RUN_BTN in keys(act) or "lup" in keys(act) or set(D4.QUICK_TURN) <= keys(act)
    assert b.__dict__["_cmd_blocked"][100] > 10.1
    later = b.tick(s, now=10.1 + D4.CMD_ROAM_S + D4.ESCAPE_ARRIVED_MM)   # the run over: the fight comes back
    assert b.doing != "walk" or "operator" not in b.why


def test_re4_next_area_is_a_one_shot_that_still_runs_its_whole_new_way():
    s = snap([((0.0, 0.0, 300.0), 400)])
    b = re4_bot()
    b.tick(s, now=10.0)
    operator(b.stats, "next_area", sid="re4-next")             # hold 0: the reader hands it over once
    b.tick(s, now=10.1)
    assert b.doing == "walk"
    b.tick(s, now=10.6)
    assert b.doing == "walk" and "next_area" in b.why


def test_re4_repetitive_sets_the_kept_target_aside_for_another():
    s = snap([((0.0, 0.0, 300.0), 400), ((100.0, 0.0, 400.0), 400)])
    b = re4_bot()
    b.tick(s, now=10.0)
    first = b.target
    operator(b.stats, "repetitive", sid="re4-rep")
    b.tick(s, now=10.1)
    b.tick(s, now=10.1 + D4.CMD_ROAM_S + 1.0)
    assert b.target is not None and b.target != first


def test_re4_score_takes_the_quickest_kill():
    near_tough, far_weak = ((0.0, 0.0, 300.0), 2000), ((0.0, 0.0, 600.0), 50)
    b = re4_bot()
    operator(b.stats, "score", sid="re4-score")
    b.tick(snap([near_tough, far_weak]), now=10.0)
    assert b.target == 101 and "score" in b.why


def test_re4_the_doctrines_own_commands_keep_their_old_meaning():
    b = re4_bot()
    b.stats.update(doctrine_directive="explore", doctrine_directive_seq="d1", doctrine_directive_until=time.time() + 5)
    b.tick(snap([((0.0, 0.0, 300.0), 400)]), now=10.0)
    assert "directive_status" not in b.stats and b.doing != "walk"   # no operator escape, no "acting" claim


# --- RE6 Switch -------------------------------------------------------------------------------------------------------

def free(bot):
    bot.held = lambda p, now: False
    return bot


def test_re6_repetitive_sets_the_kept_target_aside_and_takes_another_way():
    bot, clock, s = brain(round_guest(enemies=((0.0, 0.0, 600.0, 700), (300.0, 0.0, 700.0, 700)), cam_yaw=0.0))
    run(free(bot), s, clock, 2)
    kept = bot.target
    assert kept is not None
    operator(bot.stats, "repetitive", sid="re6-rep")
    run(bot, s, clock, 1)
    assert bot.stats["directive_status"].startswith("dropped the target")
    assert bot.blocked.get(kept, 0) > 0 and bot.wall_escape is not None


def test_re6_rush_is_the_hunt_with_the_bomb_due():
    bot, clock, s = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700),), cam_yaw=0.0))
    s["player"].update(bomb={"count": 3, "out": False})
    operator(free(bot).stats, "rush", sid="re6-rush")
    run(bot, s, clock, 1)
    assert bot.mode == "hunt" and bot.stats["directive_status"].startswith("rush: in among them")
    assert bot.mine_due is not None


def test_re6_missing_says_why_nothing_resets():
    bot, clock, s = brain(round_guest(enemies=()))
    operator(free(bot).stats, "missing", sid="re6-missing")
    run(bot, s, clock, 1)
    assert "no learned offset" in bot.stats["directive_status"]
