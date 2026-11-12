"""RE6: only the heal hint's own prompts are skipped - a counter asking for R must be pressed.

The operator, 2026-11-12: "the most important thing about that game is countering the attacks of the enemies with the
QTE events ... if there's any sort of flag that comes up for a counter from an enemy attack, that the bot is able to
instantly press that key and counter it because I see them all the time being told to press R2 and they miss the QTE."

The skip was by KEY ALONE (PROMPT_SKIP_KEYS held "r" and "y"), so every R prompt was dropped unless his health was low
enough for the tablet heal - counters included. The heal hint is identified by its types (1 / 26, button 34, at 780 /
900 health), so the skip now checks the type.
"""
from gbox.mercs.titles import re6_switch as R


def test_an_item_pickup_is_never_answered():
    assert R.prompt_skipped({"key": "y", "type": 5})
    assert R.prompt_skipped({"key": "y", "type": 1})


def test_the_heal_hint_is_skipped_by_its_types():
    assert R.prompt_skipped({"key": "r", "type": 1})
    assert R.prompt_skipped({"key": "r", "type": 26})


def test_a_counter_asking_for_r_is_pressed():
    for typ in (0, 2, 3, 7, 8, 0x12, 0x17, 25):
        assert not R.prompt_skipped({"key": "r", "type": typ}), f"an R prompt of type {typ} must be answered"


def test_the_other_buttons_are_untouched():
    for key in ("a", "b", "x", "zr", "zl", "l", "up", "down", "left", "right", "stick"):
        assert not R.prompt_skipped({"key": key, "type": 8}), key


def test_an_empty_prompt_is_not_skipped_out_of_hand():
    assert not R.prompt_skipped({})
    assert not R.prompt_skipped(None)
