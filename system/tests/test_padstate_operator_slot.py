"""gbox.padstate.operator_slot: which XInput slot the operator's pad is on.

This exists because the first version referenced `xinput` -- a name that only existed as a local import inside
`watch_xinput` -- so every call raised `NameError` and killed the mirror thread. The worker it ran in died with a
traceback storm. These tests fail on that version and pass on this one.
"""
import pytest

from gbox import padstate


class Gamepad:
    def __init__(self, buttons=0, lx=0, ly=0, rx=0, ry=0):
        self.buttons, self.lx, self.ly, self.rx, self.ry = buttons, lx, ly, rx, ry


class State:
    def __init__(self, gamepad=None):
        self.gamepad = gamepad or Gamepad()


def fake_read(active: dict):
    """A stand-in for `xinput.read`: ``active`` maps slot -> Gamepad for slots that answer."""
    def read(get_state, slot, st):
        if slot not in active:
            return None
        st.gamepad = active[slot]
        return st
    return read


def test_the_first_slot_that_reports_input_wins():
    st = State()
    read = fake_read({0: Gamepad(), 1: Gamepad(buttons=0x1000)})
    assert padstate.operator_slot(None, st, read=read, samples=1, gap=0) == 1


def test_a_moved_stick_counts_as_input_because_that_is_how_the_real_pad_was_found():
    st = State()
    read = fake_read({0: Gamepad(), 2: Gamepad(lx=20000)})
    assert padstate.operator_slot(None, st, read=read, samples=1, gap=0) == 2


def test_no_pad_at_all_falls_back_to_slot_zero():
    st = State()
    read = fake_read({0: Gamepad()})
    assert padstate.operator_slot(None, st, read=read, samples=2, gap=0) == 0


def test_an_empty_slot_that_refuses_to_answer_is_skipped():
    st = State()
    read = fake_read({3: Gamepad(ry=-20000)})
    assert padstate.operator_slot(None, st, read=read, samples=1, gap=0) == 3


def test_calling_it_without_injecting_read_does_not_raise_nameerror():
    """The regression itself: on the broken version this raised `NameError: name 'xinput' is not defined`."""
    st = State()
    try:
        got = padstate.operator_slot(None, st, samples=1, gap=0)
    except NameError as exc:                     # the exact failure that killed the worker
        pytest.fail(f"operator_slot raised NameError again: {exc}")
    except Exception:                            # noqa: BLE001 - no XInput on this machine is fine
        pytest.skip("XInput is not available here")
    assert got in (0, 1, 2, 3)
