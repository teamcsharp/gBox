"""RE4: a failed heal swap must not become the round.

Live 2026-11-12, Waterworld r404: doing=heal "the first aid spray to hand (548 of 1560)" with the round timer frozen at
126.06 across five minutes, hits never completing and shots 14 / hits 2 / kills 8. The swap never confirmed, hp stayed
under HEAL_BELOW, so the abort cleared the state and the next tick started another swap - the bot never fired again and
the game waited with it.

The feature is off (re4_switch.HEAL_ON is False) until it can be watched landing, but the guard is tested so re-enabling
it cannot bring the freeze back.
"""
import pytest

from gbox.mercs.titles import re4_switch as D


def mm(p):
    return tuple(v * D.MM_PER_CM for v in p)


def snap(enemies=(), pos=(0.0, 0.0, 0.0), rot=0.0, hp=1000, **extra):
    return {"player": {"pos": mm(pos), "rot": rot, "hp": hp, "ptr": 1},
            "enemies": [{"pos": mm(p), "hp": h, "ptr": 100 + i} for i, (p, h) in enumerate(enemies)], **extra}


def bot():
    return D.Bot(stats={}, director=False)


def hurt_bot(monkeypatch, hp=400, hp_max=1000):
    monkeypatch.setattr(D, "HEAL_ON", True)
    s = snap([((0.0, 0.0, 500.0), 400)], hp=hp)
    s["player"]["hp_max"] = hp_max
    return bot(), s


def test_the_state_key_does_not_shadow_the_method():
    """The freeze: state under self.__dict__["_heal"] shadowed the _heal method, so the second tick raised
    TypeError('dict' object is not callable) and the round stopped advancing entirely."""
    assert callable(D.Bot._heal)
    b = D.Bot(stats={}, director=False)
    b.__dict__["_heal_state"] = None
    assert callable(b._heal), "an attribute must never take the method's name"


def test_a_failed_swap_blocks_the_retry_and_the_fight_resumes(monkeypatch):
    b, s = hurt_bot(monkeypatch)
    b.tick(s, now=10.0)
    assert b.doing == "heal", "hurt enough to want the spray"
    b.tick(s, now=10.0 + D.HEAL_HAND_S + 0.05)          # HAND_STATE never answers: abort
    assert b.stats.get("heal_aborts") == 1
    # the abort's "back" phase (the gun again) is still the heal's own, so allow it to run out - what must never happen
    # is another SWAP, which is what froze the live round.
    for at in (11.0, 12.0, 13.0, 14.0):
        b.tick(s, now=at)
        assert b.stats.get("heal_aborts") == 1, f"another swap was attempted at {at}"
    assert b.doing != "heal", "past HEAL_BLOCK_S the fight is what he is doing again"


def test_healing_stays_idle_when_he_is_healthy(monkeypatch):
    b, s = hurt_bot(monkeypatch, hp=900, hp_max=1000)
    b.tick(s, now=10.0)
    assert b.doing != "heal" and not b.stats.get("heal_aborts")
