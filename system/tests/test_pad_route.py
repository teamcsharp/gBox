"""Tests for the virtual-pad-versus-keyboard routing decision."""

import pytest

from gbox import pad_route


def test_absent_pad_is_keyboard():
    assert pad_route.choose_path(False, lambda: True) == "keyboard"


def test_unproven_pad_is_keyboard():
    assert pad_route.choose_path(True, None) == "keyboard"


def test_reporting_pad_is_vpad():
    assert pad_route.choose_path(True, lambda: True) == "vpad"


def test_silent_pad_is_keyboard():
    assert pad_route.choose_path(True, lambda: False) == "keyboard"


def test_failing_probe_is_keyboard():
    def boom():
        raise RuntimeError("no such device")

    assert pad_route.choose_path(True, boom) == "keyboard"


def test_press_registered_sees_a_button_change():
    assert pad_route.press_registered({"buttons": 0, "lx": 0, "ly": 0}, {"buttons": 0x0400, "lx": 0, "ly": 0})


def test_press_registered_sees_a_stick_change():
    assert pad_route.press_registered({"lx": 0, "ly": 0}, {"lx": 0, "ly": 173})


def test_dead_pad_reports_nothing():
    zeros = {"buttons": 0, "lx": 0, "ly": 0}
    assert not pad_route.press_registered(zeros, dict(zeros))


def test_missing_keys_are_tolerated():
    assert pad_route.press_registered({}, {"buttons": 0x0400})
    assert not pad_route.press_registered({}, {})


def test_slot_reading_reduces_a_pad():
    class Gamepad:
        buttons, lx, ly, rx, ry, lt, rt = 0x0400, 3, -4, 5, -6, 7.5, 8.5

    class State:
        gamepad = Gamepad()

    reading = pad_route.slot_reading(State())
    assert reading == {"buttons": 0x0400, "lx": 3, "ly": -4, "rx": 5, "ry": -6, "lt": 7.5, "rt": 8.5}
    assert pad_route.slot_reading(None) == {}


def test_keyboard_events_translate_known_names_and_pass_unknown():
    keymap = {"z": "e", "dup": "t", "a": "x"}
    events = pad_route.keyboard_events([{"key": "z", "down": True}, {"key": "dup", "down": False}, {"key": "start", "down": True}],
                                       keymap)
    assert [e["key"] for e in events] == ["e", "t", "start"]
    assert [e["down"] for e in events] == [True, False, True]


def test_report_names_the_reason():
    missing = pad_route.report("keyboard", 0, None)
    assert missing["input_path"] == "keyboard"
    assert "does not report" in missing["reason"]
    working = pad_route.report("vpad", 2, True)
    assert working["vpad_slot"] == 2 and "reports its presses" in working["reason"]
