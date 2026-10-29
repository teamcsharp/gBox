"""Focused pytest for the #5972 emergency flashbang.

The bug: `_flashbang_throw` re-read `self.commands.current()` every tick, and since the
ONE fresh `flashbang` was consumed by `_operator_command`, the second read returned
`cmd=None` (stale), so the throw never fired.  The fix introduces a persistent state
machine `self.flashbang` (arm-once in _operator_command, ticked in the loop) that does
NOT re-read the reader.

Drives the arm+tick pair against a minimal object, proving the equip-tap and ZL-throw
actually emit, plus the RE6 `_emergency_flashbang` throw-at-feet path and its guards.
"""
import sys

import pytest

sys.path.insert(0, "/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/9b62ade91d2b4aed/system")

import gbox.mercs.directives as directives
import gbox.mercs.titles.re5_switch as r5
import gbox.mercs.titles.re6_switch as r6


# --- RE5 -------------------------------------------------------------------------

class Fake5:
    """Minimal stand-in carrying just the state the two RE5 methods touch."""

    def __init__(self):
        self.stats = {}
        self.flashbang = None
        self.gun_downs = 0

    def _gun_down(self):
        self.gun_downs += 1


Fake5._emergency_flashbang_arm = r5.Bot._emergency_flashbang_arm
Fake5._flashbang_throw = r5.Bot._flashbang_throw

QUICK = r5.QUICK
EQUIP_ACK_S = r5.EQUIP_ACK_S


def fresh_inventory(hand=False, rounds=1, grid=1):
    idw = (3 << 8) | 0x08
    return [{"slot": 1, "id": idw, "type": 3, "item": 0x08, "rounds": rounds,
             "grid": grid, "hand": hand, "cap": 2}]


def arm(f, hand):
    f._emergency_flashbang_arm({"ptr": 0xAAA}, {"inventory": fresh_inventory(hand=hand)}, now=10.0)


def test_re5_in_hand_arm_throws_immediately():
    f = Fake5()
    arm(f, hand=True)
    assert f.flashbang is not None, "arm did not set state"
    assert f.stats["emergency_flashes"] == 1, "flash counter"
    act = f._flashbang_throw({"ptr": 0xAAA}, {"inventory": fresh_inventory(hand=True)}, now=10.0)
    assert act == {"hold": ("zl",)}, f"expected ZL throw, got {act!r}"
    assert f.gun_downs >= 1, "_gun_down not called for the in-hand throw"


def test_re5_equip_then_throw_progression():
    f = Fake5()
    arm(f, hand=False)
    assert f.flashbang is not None and not f.flashbang["in_hand"]
    # tick 1: not in hand, within EQUIP_ACK_S gap -> tap the D-pad key
    act1 = f._flashbang_throw({"ptr": 0xAAA}, {"inventory": fresh_inventory(hand=False)}, now=20.0)
    assert act1 == {"tap": QUICK[1]}, f"expected equip tap, got {act1!r}"
    # grenade now in hand -> ZL throw
    act2 = f._flashbang_throw({"ptr": 0xAAA}, {"inventory": fresh_inventory(hand=True)}, now=20.0)
    assert act2 == {"hold": ("zl",)}, f"expected ZL throw after equip, got {act2!r}"


def test_re5_no_grenade_clears_cleanly():
    f = Fake5()
    f._emergency_flashbang_arm({"ptr": 0xAAA}, {"inventory": []}, now=30.0)
    assert f.flashbang is None, "arm should clear when no grenade"
    assert f.stats["emergency_flash_no_grenade"] == 1
    assert f._flashbang_throw({"ptr": 0xAAA}, {"inventory": []}, now=30.0) is None


def test_re5_rapid_rearm_restarts_a_fresh_throw():
    f = Fake5()
    arm(f, hand=True)
    arm(f, hand=True)  # second click re-arms
    assert f.stats["emergency_flashes"] == 2, "re-arm should increment counter"
    act = f._flashbang_throw({"ptr": 0xAAA}, {"inventory": fresh_inventory(hand=True)}, now=40.1)
    assert act == {"hold": ("zl",)}, "re-arm should still throw"


# --- RE6 -------------------------------------------------------------------------

class _FakeReader:
    def __init__(self, cmd, fresh):
        self.cmd, self.fresh = cmd, fresh

    def current(self, stats, now):
        return self.cmd, self.fresh


class Fake6:
    def __init__(self):
        self.stats = {}
        self.commands = None
        self.nade = None

    def _go(self, doing, act, out, why=""):
        return (doing, act, out, why)


Fake6._emergency_flashbang = r6.Bot._emergency_flashbang
FLASH_TYPE = r6.NADE_TYPES["flash"]


def p6(nades, pos=(100.0, 0.0, 200.0), equipped=0):
    return {"pos": pos, "nades": nades, "equipped": equipped}


def test_re6_fresh_flashbang_throws_at_own_feet():
    f = Fake6()
    f.commands = _FakeReader("flashbang", True)
    nades = {FLASH_TYPE: (3, 2)}
    out = f._emergency_flashbang(p6(nades), None, now=10.0)
    assert out is not None, "emergency flashbang should return a throw"
    doing, act, keys, why = out
    assert doing == "nade" and act == "nade_flash"
    assert keys == {"hold": ("zl", "zr")}, f"bad keys {keys!r}"
    assert f.nade is not None and f.nade["kind"] == "flash" and f.nade["index"] == 3
    assert f.nade["to"] == (100.0, 200.0), "must throw at own feet (px,pz)"
    assert f.stats["emergency_flashes"] == 1


def test_re6_throw_in_progress_is_guarded():
    f = Fake6()
    f.commands = _FakeReader("flashbang", True)
    f.nade = {"kind": "flash", "index": 3, "phase": "face"}
    nades = {FLASH_TYPE: (3, 2)}
    assert f._emergency_flashbang(p6(nades), None, now=10.0) is None
    assert f.stats.get("emergency_flashes", 0) == 0


def test_re6_no_grenade_is_guarded():
    f = Fake6()
    f.commands = _FakeReader("flashbang", True)
    nades = {FLASH_TYPE: (3, 0)}
    assert f._emergency_flashbang(p6(nades), None, now=10.0) is None
    assert f.stats["emergency_flash_no_grenade"] == 1


@pytest.mark.parametrize("cname,fresh", [("rush", True), ("flashbang", False)])
def test_re6_ignores_non_flashbang_or_stale(cname, fresh):
    f = Fake6()
    f.commands = _FakeReader(cname, fresh)
    nades = {FLASH_TYPE: (3, 2)}
    assert f._emergency_flashbang(p6(nades), None, now=10.0) is None
