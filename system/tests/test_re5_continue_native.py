"""Continue navigation follows native readiness and the observed No cursor, never a sent-key latch."""
import pytest

from gbox.mercs.titles import re5_ps3 as R
from test_re5_mercs import MAIN, SPLAYER, with_continue, world


def dialog(mem):
    return R.ui_units(mem, range(R.N_LINES))["uIdGameover00"]


def test_death_animation_cannot_consume_the_only_no_selection_press():
    mem = with_continue(world(hp=0), state=0)
    unit = dialog(mem)
    for state in (0, 1):
        mem.put(unit + R.CONTINUE_STATE, bytes([state]))
        scr = R.screen(mem)
        assert scr["where"] == "dead" and scr["continue_ready"] is False
        assert R.step(scr) is None
    mem.put(unit + R.CONTINUE_STATE, b"\x02")
    scr = R.screen(mem)
    assert scr["continue_ready"] is True and scr["cursor"] == 0
    assert R.step(scr) == "dright"
    R.pressed(scr, "dright")
    # A sent or dropped Right is not evidence that the native cursor moved.
    assert R.step(R.screen(mem)) == "dright"
    mem.u32(unit + R.CONTINUE_CHOICE, 1)
    assert R.step(R.screen(mem)) == "cross"
    mem.put(unit + R.CONTINUE_STATE, b"\x03")
    assert R.step(R.screen(mem)) is None


def test_dialog_is_observed_after_the_dead_player_is_destroyed():
    mem = with_continue(world(hp=0), choice=1)
    mem.u32(SPLAYER + 0x28, 0)
    scr = R.screen(mem)
    assert scr["where"] == "dead" and scr["continue_ready"] is True
    assert R.step(scr) == "cross"


@pytest.mark.parametrize("change", ["signature", "choice", "blocked", "other_mode", "main_missing", "unit_reused"])
def test_unverified_or_blocked_continue_dialog_never_confirms(change):
    mem = with_continue(world(hp=0), choice=1)
    unit = dialog(mem)
    if change == "signature":
        mem.put(R.CONTINUE_CODE[0][0], b"\x00")
    elif change == "choice":
        mem.u32(unit + R.CONTINUE_CHOICE, 2)
    elif change == "blocked":
        mem.u32(unit + R.CONTINUE_BLOCKED, 0x22)
    elif change == "other_mode":
        mem.u32(MAIN + 0x182DC, 0x100)
    elif change == "main_missing":
        mem.u32(R.S_MAIN, 0)
    else:
        mem.u32(unit, 0x015AB738)  # type metadata is not the actual Gameover unit vtable
    assert R.step(R.screen(mem)) is None


def test_racing_menu_transition_or_failed_read_never_confirms():
    mem = with_continue(world(hp=0), choice=1)
    unit, original = dialog(mem), mem.rd
    def raced(address, length):
        if address == R.CONTINUE_CODE[0][0]:
            mem.put(unit + R.CONTINUE_STATE, b"\x03")
        return original(address, length)
    mem.rd = raced
    assert R.step(R.screen(mem)) is None
    mem.rd = lambda *_: (_ for _ in ()).throw(OSError("stopped"))
    assert R.step(R.continue_screen(mem)) is None


def test_dead_bot_waits_for_ram_and_only_confirms_the_read_back_no_choice():
    now = [10.0]
    mem = world(hp=0)
    bot = R.Bot(mem, clock=lambda: now[0])
    assert bot.tick(R.snapshot(mem)) == {"hold": set()}
    with_continue(mem, state=1)
    assert bot.tick(R.snapshot(mem)) == {"hold": set()}
    unit = dialog(mem)
    mem.put(unit + R.CONTINUE_STATE, b"\x02")
    assert bot.tick(R.snapshot(mem)) == {"tap": "dright"}
    now[0] += 2
    assert bot.tick(R.snapshot(mem)) == {"tap": "dright"}
    assert bot.stats.get("continue_declined", 0) == 0
    mem.u32(unit + R.CONTINUE_CHOICE, 1)
    now[0] += 2
    assert bot.tick(R.snapshot(mem)) == {"tap": "cross"}
    assert bot.stats["continue_declined"] == 1
    mem.put(unit + R.CONTINUE_STATE, b"\x03")
    now[0] += 2
    assert bot.tick(R.snapshot(mem)) == {"hold": set()}


@pytest.mark.parametrize("scr", [
    {"where": "dead"},
    {"where": "dead", "continue_ready": False, "cursor": 1},
    {"where": "dead", "continue_ready": True, "cursor": None},
    {"where": "dead", "continue_ready": True, "cursor": True},
    {"where": "dead", "continue_ready": True, "cursor": 2},
])
def test_incomplete_menu_observations_cannot_press(scr):
    assert R.step(scr) is None
