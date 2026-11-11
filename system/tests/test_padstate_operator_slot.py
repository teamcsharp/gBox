"""gbox.padstate.operator_slot: which XInput slot the operator's pad is on, and remembering it.

The first version referenced `xinput` -- a name that only existed as a local import inside `watch_xinput` -- so every call
raised `NameError` and killed the mirror thread; the worker it ran in died with a traceback storm. This version takes the
read function as a parameter.

It also **remembers** the slot, because detection needs movement and the worker log showed the consequence of not doing so:
a restart with the pad still picked slot 0, the dead virtual pad, and the mirror watched nothing until the operator moved.
"""
import pytest

from gbox import padstate


@pytest.fixture(autouse=True)
def clean_memory():
    padstate.reset_slot_memory()
    yield
    padstate.reset_slot_memory()


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


def test_the_slot_is_remembered_so_a_quiet_pad_does_not_fall_back_to_the_dead_one():
    """The worker's own failure mode: pad found on 1, operator pauses, restart detects nothing and picks 0."""
    st = State()
    read = fake_read({0: Gamepad(), 1: Gamepad(buttons=0x1000)})
    assert padstate.operator_slot(None, st, read=read, samples=1, gap=0) == 1
    # now the pad is still, but it is still on slot 1 and still answers: keep watching it, not slot 0
    quiet = fake_read({0: Gamepad(), 1: Gamepad()})
    assert padstate.operator_slot(None, st, read=quiet, samples=1, gap=0) == 1


def test_remembering_does_not_override_a_slot_that_stopped_answering():
    st = State()
    read = fake_read({1: Gamepad(buttons=0x1000)})
    assert padstate.operator_slot(None, st, read=read, samples=1, gap=0) == 1
    moved = fake_read({2: Gamepad(lx=-20000)})
    assert padstate.operator_slot(None, st, read=moved, samples=1, gap=0) == 2


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
