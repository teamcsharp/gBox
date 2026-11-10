"""The RE4 Switch brain's input contract: shoulder buttons turn, the trigger taps, the d-pad is never touched."""

from gbox.mercs.titles import re4_switch


def _bot(monkey_target=(5.0, 0.0, 0.0)):
    bot = re4_switch.Bot()
    snap = {
        "player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "ptr": 1},
        "enemies": [{"pos": monkey_target, "ptr": 2, "hp": 100}],
    }
    return bot, snap


def test_turning_uses_the_shoulder_buttons_never_the_dpad():
    """The d-pad is item select on RE4, so a turn that pressed it would open the inventory mid-round."""
    assert re4_switch.TURN == {"left": "lleft", "right": "lright"}
    bot, snap = _bot()
    act = bot.tick(snap)
    keys = set(act.get("hold") or ()) | ({act["tap"]} if act.get("tap") else set())
    assert keys, "the bot expected to act on an enemy five metres away"
    assert not (keys & set(re4_switch.DPAD.values())), keys


def test_firing_taps_the_trigger_while_aiming():
    """Measured contract: holding both buttons never released the trigger, so the first cut fired once."""
    bot, snap = _bot()
    # face the enemy using the module own heading convention, so no turn is needed
    snap["player"]["rot"] = re4_switch.heading(5.0, 0.0)
    first = bot.tick(snap, now=10.0)                      # the gun comes up first: no tap as it rises (AIM_READY_S)
    assert first.get("tap") is None and re4_switch.AIM_BTN in set(first.get("hold") or ()), first
    act = bot.tick(snap, now=10.0 + re4_switch.AIM_READY_S)
    assert act.get("tap") == re4_switch.FIRE_BTN, act
    assert re4_switch.AIM_BTN in set(act.get("hold") or ()), act
    assert re4_switch.FIRE_BTN not in set(act.get("hold") or ()), act


def test_the_shot_is_not_taken_through_a_wall_at_long_range():
    """The first brain keeps a 12 m range limit as a stand-in until stage geometry exists."""
    bot, snap = _bot(monkey_target=(40.0, 0.0, 0.0))
    act = bot.tick(snap)
    assert act.get("tap") is None