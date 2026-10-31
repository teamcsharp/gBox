"""RE5 Switch native QTE completion (gbox.mercs.titles.re5_switch_qte): only the shown mode 4 / 6 unit's progress float
is written, set to its own target, so the game's evaluator fires the real callback; stale, changed or non-accumulator
events are never touched (the PS3's tests/test_re5_qte.py on this build's layout)."""
import struct

import pytest

from gbox import mercs_bot, ram_map
from gbox.mercs.titles import re5_switch as R
from gbox.mercs.titles import re5_switch_mods as SM
from gbox.mercs.titles import re5_switch_prompt as P
from gbox.mercs.titles import re5_switch_qte as Q
from tests.test_re5_switch import BASE
from tests.test_re5_switch_mods import Adapter, weapon_guest

CALLBACK, OWNER, SERIAL = BASE + 0x7B0350, 0x5D00380000, 22


@pytest.fixture(autouse=True)
def _fresh_state():
    SM.ORIG.clear()
    R._PROMPT_TABLE.clear()                                       # cached per main base; every fake guest shares BASE
    yield
    SM.ORIG.clear()
    R._PROMPT_TABLE.clear()


class Scene:
    """weapon_guest (a round, Chris, the weapon table) plus sActionButton with one shown display unit."""

    def __init__(self, mode=6, progress=2.0, target=10, motion=107, key=20, label=28):
        self.g = g = weapon_guest(motion=motion)
        for off, sig in Q.SIGNATURES.items():
            g.put(BASE + off, sig)
        g.put(BASE + P.KEY_TABLE, struct.pack("<32I", *P.MASKS))
        R._PROMPT_TABLE.clear()                                   # weapon_guest's snapshot cached the empty table
        self.ab = ab = g.alloc(0x1680)
        g.q(BASE + P.S_ACTION, ab)
        g.q(ab, BASE + P.AB_VT)
        g.put(ab + P.AB_ENABLED, b"\1")
        self.mgr = mgr = ab + P.AB_MGR
        g.put(mgr + P.MGR_ENABLED, b"\1")
        g.i32(mgr + P.MGR_INDEX, 0)
        self.button = self.make_button(mode, target, key, label)
        self.unit = mgr + P.MGR_UNITS[0]
        self.show(self.unit, self.button, mode, progress, target, key)
        self.player = R.snapshot(g)["player"]["ptr"]
        self.ad = Adapter(g)

    def make_button(self, mode, target, key, label, serial=SERIAL):
        g = self.g
        b = g.alloc(0xB0)
        g.q(b, BASE + P.BTN_VT)
        g.q(b + P.BTN_OWNER, OWNER)
        g.put(b + P.BTN_ON, b"\1\1\1\0\0\0")                     # on, +0x11, available; not accepted / muted / new
        g.put(b + P.BTN_PLAYER, struct.pack("<6I", 0, 0, mode, 33, key, label))
        g.i32(b + P.BTN_COUNT, target)
        g.put(b + P.BTN_PLAYERS, struct.pack("<I", 1))
        g.q(b + Q.BTN_CALLBACK, CALLBACK)
        g.put(b + Q.BTN_SERIAL, struct.pack("<I", serial))
        return b

    def show(self, unit, button, mode, progress, target, key, serial=SERIAL):
        g = self.g
        g.put(unit + P.UNIT_SHOWN, b"\1\1")
        g.i32(unit + Q.UNIT_SLOT, 2)
        g.q(unit + P.UNIT_BTN, button)
        g.put(unit + P.UNIT_MODE, struct.pack("<I", mode))
        g.q(unit + P.UNIT_MASK, P.MASKS[key])
        g.put(unit + Q.PROGRESS, struct.pack("<2f", progress, float(target)))
        g.put(unit + Q.UNIT_SERIAL, struct.pack("<I", serial))

    def snap(self):
        return {"player": {"ptr": self.player}, "module_base": BASE}


SCOPE = ("adapter", BASE, "player")


class Memory:
    """The step's memory over the scene: reads straight through, every write recorded."""

    def __init__(self, s, ok=True):
        self.s, self.ok, self.writes = s, ok, []

    def rd(self, a, n):
        return self.s.g.rd(a, n)

    def wr(self, a, data):
        self.writes.append((a, bytes(data)))
        if self.ok:
            self.s.g.put(a, bytes(data))
        return self.ok


def step(helper, s, memory, now=0.0, **kw):
    return helper.step(memory, kw.pop("base", BASE), s.player, s.snap(), now, scope=kw.pop("scope", SCOPE), **kw)


def f32(x):
    return struct.pack("<f", x)


@pytest.mark.parametrize("mode", [4, 6])
def test_progress_reaches_exact_native_target_without_success_or_consumed_writes(mode):
    s = Scene(mode, key=20 if mode == 6 else 4, label=28 if mode == 6 else 60)
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    before = s.g.rd(s.button, 0xB0)
    result = step(helper, s, mem)
    assert result["phase"] == "submitted" and result["progress_verified"] and result["kind"] == Q.MODES[mode]
    assert not result["verified"] and not result["completed"] and not result["native_accepted"]
    assert mem.writes == [(s.unit + Q.PROGRESS, f32(10.0))]
    assert s.g.rd(s.button, 0xB0) == before                      # +0x13 / +0x14 / +0x15 untouched
    assert step(helper, s, mem, 0.1)["phase"] == "pending"
    assert len(mem.writes) == 1


def test_native_acceptance_is_distinct_from_observed_release_from_the_hold():
    s = Scene()
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    step(helper, s, mem)
    s.g.put(s.button + Q.BTN_ACCEPTED, b"\1\1")                 # the game's success path, never our writer
    result = step(helper, s, mem, 0.1)
    assert result["phase"] == "native_accepted" and result["native_accepted"] and not result["completed"]
    s.g.put(s.player + R.P_MOTION, bytes([104]))                 # let go
    result = step(helper, s, mem, 0.2)
    assert result["phase"] == "completed" and result["completed"]
    assert len(mem.writes) == 1


def test_a_mash_without_a_hold_is_accepted_never_completed_by_motion():
    s = Scene(4, key=4, label=60, motion=0)
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    step(helper, s, mem)
    s.g.put(s.button + Q.BTN_ACCEPTED, b"\1\1")
    result = step(helper, s, mem, 0.1)
    assert result["native_accepted"] and not result["completed"]


@pytest.mark.parametrize("change", ["hidden", "player", "descriptor"])
def test_disappeared_prompt_or_changed_player_is_not_success(change):
    s = Scene()
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    step(helper, s, mem)
    if change == "hidden":
        s.g.put(s.unit + P.UNIT_SHOWN, b"\0")
    elif change == "player":
        sp = R.u64(s.g, BASE + R.S_PLAYER)
        s.g.q(sp + R.P_FIRST, s.player + 0x10000)
    else:
        s.g.q(s.button + Q.BTN_CALLBACK, CALLBACK + 4)
    result = step(helper, s, mem, 4.0)
    assert not result["completed"] and not result["native_accepted"]
    assert result["phase"] in ("timeout", "ended_unconfirmed", "native_ready")
    assert len(mem.writes) == 1


@pytest.mark.parametrize("mode", [1, 2, 3, 5, 7, 8, 9])
def test_non_accumulator_modes_keep_the_bots_input(mode):
    s = Scene(mode, key=25 if mode == 5 else 1, label=55 if mode == 5 else 58)
    mem = Memory(s)
    assert step(Q.ProgressHook(SCOPE), s, mem)["phase"] == "waiting" and mem.writes == []


@pytest.mark.parametrize("offset, value", [(Q.BTN_ACCEPTED, b"\1"), (P.BTN_MUTED, b"\1"), (Q.BTN_NEW, b"\1"),
                                           (P.BTN_AVAIL, b"\0"), (Q.BTN_EXCLUDED, b"\1")])
def test_accepted_muted_reset_unavailable_or_excluded_requests_are_never_changed(offset, value):
    s = Scene()
    s.g.put(s.button + offset, value)
    mem = Memory(s)
    assert step(Q.ProgressHook(SCOPE), s, mem)["phase"] == "waiting" and mem.writes == []


def test_the_on_byte_is_not_a_gate():
    s = Scene()                                                   # live: shown Pick up prompts read +0x10 = 0
    s.g.put(s.button + P.BTN_ON, b"\0")
    mem = Memory(s)
    assert step(Q.ProgressHook(SCOPE), s, mem)["phase"] == "submitted" and len(mem.writes) == 1


@pytest.mark.parametrize("progress", [float("nan"), float("inf"), -1.0, 11.0])
def test_invalid_progress_is_not_clamped(progress):
    s = Scene(progress=progress)
    mem = Memory(s)
    assert step(Q.ProgressHook(SCOPE), s, mem)["phase"] == "waiting" and mem.writes == []


@pytest.mark.parametrize("change", ["zero", "negative", "huge", "copied_target", "unit_mode", "duplicate", "hidden",
                                    "button_class", "build", "jump_table", "key_table", "dead", "p2_button",
                                    "player_bits", "serial", "key0", "not_solo_player", "snapshot_p2"])
def test_invalid_target_build_selection_or_player_cannot_write(change):
    s = Scene()
    g, snap_extra = s.g, {}
    if change in ("zero", "negative", "huge"):
        t = {"zero": 0, "negative": -1, "huge": Q.TARGET_MAX + 1}[change]
        g.i32(s.button + P.BTN_COUNT, t)
        g.put(s.unit + Q.TARGET, f32(float(t)))
    elif change == "copied_target":
        g.put(s.unit + Q.TARGET, f32(11.0))
    elif change == "unit_mode":
        g.put(s.unit + P.UNIT_MODE, struct.pack("<I", 4))
    elif change == "duplicate":
        g.put(s.mgr + P.MGR_UNITS[1], g.rd(s.unit, 0x60))
    elif change == "hidden":
        g.put(s.unit + P.UNIT_SHOWN, b"\0")
    elif change == "button_class":
        g.q(s.button, BASE + 0x1C62910)
    elif change == "build":
        g.put(BASE + 0x15F97C, b"bad!")                           # the mode-6 comparison
    elif change == "jump_table":
        g.put(BASE + 0x17504CC + 4 * 5, b"\0\0\0\0")              # mode 6's case moved
    elif change == "key_table":
        g.put(BASE + P.KEY_TABLE + 4, struct.pack("<I", 0x4000))     # square's word is not 0x8000 any more
    elif change == "dead":
        g.put(s.player + R.P_HP, struct.pack("<h", 0))
    elif change == "p2_button":
        g.put(s.button + P.BTN_PLAYER, struct.pack("<I", 1))
    elif change == "player_bits":
        g.put(s.button + P.BTN_PLAYERS, struct.pack("<I", 2))
    elif change == "serial":
        g.put(s.unit + Q.UNIT_SERIAL, struct.pack("<I", SERIAL + 1))
    elif change == "key0":
        g.put(s.button + P.BTN_KEY, struct.pack("<I", 0))
    elif change == "not_solo_player":
        sp = R.u64(g, BASE + R.S_PLAYER)
        g.q(sp + R.P_FIRST, s.player + 0x1000)
    elif change == "snapshot_p2":
        snap_extra = {"player_index": 1}
    mem = Memory(s)
    snap = dict(s.snap(), **snap_extra)
    result = Q.ProgressHook(SCOPE).step(mem, BASE, s.player, snap, 0.0, scope=SCOPE)
    assert result["phase"] == "waiting" and mem.writes == []


def test_scope_change_and_disable_forbid_writes_and_never_restore_old_progress():
    s = Scene()
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    assert step(helper, s, mem, scope=("another",))["phase"] == "rejected" and not mem.writes
    step(helper, s, mem)
    assert step(helper, s, mem, 0.1, enabled=False)["phase"] == "disabled"
    assert step(helper, s, mem, 0.2, scope=None)["phase"] == "rejected"
    assert len(mem.writes) == 1


@pytest.mark.parametrize("change", ["callback", "reset", "progress_reset", "serial"])
def test_a_change_between_the_two_full_fences_rejects(monkeypatch, change):
    s = Scene()
    original, calls = Q.view, [0]

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 1:
            if change == "callback":
                s.g.q(s.button + Q.BTN_CALLBACK, CALLBACK + 8)
            elif change == "reset":
                s.g.put(s.button + Q.BTN_NEW, b"\1")
            elif change == "progress_reset":
                s.g.put(s.unit + Q.PROGRESS, f32(0.0))
            else:
                s.g.put(s.button + Q.BTN_SERIAL, struct.pack("<I", SERIAL + 1))
                s.g.put(s.unit + Q.UNIT_SERIAL, struct.pack("<I", SERIAL + 1))
        return result

    monkeypatch.setattr(Q, "view", changed)
    mem = Memory(s)
    assert step(Q.ProgressHook(SCOPE), s, mem)["phase"] == "waiting" and mem.writes == []


def test_natural_threshold_completion_needs_no_write_and_a_failed_write_is_not_retried():
    s = Scene(progress=10.0)
    mem = Memory(s)
    assert step(Q.ProgressHook(SCOPE), s, mem)["phase"] == "native_ready" and not mem.writes
    s = Scene()
    mem, helper = Memory(s, ok=False), Q.ProgressHook(SCOPE)
    assert step(helper, s, mem)["phase"] == "write_unconfirmed"
    mem.wr = lambda *_: pytest.fail("the same event must not retry an uncertain write")
    assert step(helper, s, mem, 4.0)["phase"] == "timeout"


def test_unreadable_memory_never_becomes_success():
    s = Scene()
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    step(helper, s, mem)
    mem.rd = lambda *_: (_ for _ in ()).throw(OSError("read failed"))
    assert step(helper, s, mem, 0.1)["phase"] == "pending"
    assert step(helper, s, mem, 4.0)["phase"] == "timeout"
    assert len(mem.writes) == 1


def test_an_identical_request_rearms_only_after_observed_native_acceptance_then_reset():
    s = Scene()
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    step(helper, s, mem)
    s.g.put(s.unit + Q.PROGRESS, f32(0.0))
    assert step(helper, s, mem, 0.1)["phase"] == "pending"
    assert len(mem.writes) == 1                                  # progress reset alone is not a new event
    s.g.put(s.button + Q.BTN_ACCEPTED, b"\1\1")
    assert step(helper, s, mem, 0.2)["phase"] == "native_accepted"
    s.g.put(s.button + Q.BTN_ACCEPTED, b"\0\0")
    assert step(helper, s, mem, 0.3)["phase"] == "submitted"
    assert len(mem.writes) == 2


def test_the_first_native_acceptance_seen_after_the_deadline_is_not_attributed_to_this_write():
    s = Scene()
    mem, helper = Memory(s), Q.ProgressHook(SCOPE)
    step(helper, s, mem)
    assert step(helper, s, mem, 3.0)["phase"] == "timeout"
    s.g.put(s.button + Q.BTN_ACCEPTED, b"\1\1")
    s.g.put(s.player + R.P_MOTION, bytes([0]))
    result = step(helper, s, mem, 10.0)
    assert result["phase"] == "timeout" and not result["native_accepted"] and not result["completed"]


@pytest.mark.parametrize("offset", [0x08, 0x1C, 0x24, 0x2C, 0x30, 0x48, 0x50, 0x58, 0x60, 0x9C])
def test_every_event_definition_field_is_in_the_identity(offset):
    s = Scene()
    before = Q.view(Memory(s), BASE, s.player)
    s.g.put(s.button + offset, struct.pack("<I", 0x31) if offset != 0x30 else struct.pack("<i", 10))
    if offset == 0x30:                                            # the count: a different (consistent) target
        s.g.i32(s.button + P.BTN_COUNT, 12)
        s.g.put(s.unit + Q.TARGET, f32(12.0))
    if offset == 0x9C:
        s.g.put(s.unit + Q.UNIT_SERIAL, struct.pack("<I", 0x31))
    try:
        after = Q.view(Memory(s), BASE, s.player)["identity"]
    except Q.Reject:
        return                                                    # no longer a valid event: also never written
    assert after != before["identity"]


# --- the op, the driver's upkeep and the profile -------------------------------------------------------------------
def test_the_op_validates_the_build_and_maintain_writes_only_the_progress():
    s = Scene()
    out = SM.tool_run(s.ad, "instant_qte", None, True)
    assert out["configured"] and out["verified"] and not out["native_outcome_verified"]
    assert out["native_modes"] == [4, 6] and s.ad.writes == []
    caps = out["status"]["capabilities"]["instant_qte"]
    assert caps["available"] and caps["native_modes"] == [4, 6] and out["status"]["instant_qte"]
    snap = R.snapshot(s.g)
    res = SM.maintain(s.ad, snap, clock=lambda: 10.0)
    assert res["qte"]["phase"] == "submitted" and not res["qte"]["completed"] and res["writes"] == 1
    assert s.ad.writes == [(s.unit + Q.PROGRESS, f32(10.0))]
    assert res["qte"]["counts"]["progress_writes"] == 1
    assert SM.maintain(s.ad, snap, clock=lambda: 10.1)["writes"] == 0      # one write per event
    SM.tool_run(s.ad, "instant_qte", None, False)
    s.g.put(s.unit + Q.PROGRESS, f32(0.0))
    assert SM.maintain(s.ad, snap, clock=lambda: 20.0)["writes"] == 0 and len(s.ad.writes) == 1


@pytest.mark.parametrize("alias", ["auto_qte", "auto_qte_ram", "qte_assist", "qte_ram"])
def test_the_ps3_and_re6_names_reach_the_op(alias):
    s = Scene()
    assert SM.tool_run(s.ad, alias, None, True)["op"] == "instant_qte"
    assert SM.ORIG[id(s.ad)]["qte"]["on"]


def test_a_build_that_differs_never_turns_it_on():
    s = Scene()
    s.g.put(BASE + 0x15F5D4, b"\0" * 4)
    out = SM.tool_run(s.ad, "instant_qte", None, True)
    assert out["verified"] is False and not out["configured"] and "signatures" in out["reason"]
    assert not out["status"]["capabilities"]["instant_qte"]["available"]
    assert SM.maintain(s.ad, R.snapshot(s.g))["writes"] == 0 and s.ad.writes == []


def test_maintain_is_cheap_and_silent_while_no_accumulator_is_shown(monkeypatch):
    s = Scene(1, key=1, label=58, motion=0)
    SM.tool_run(s.ad, "instant_qte", None, True)
    monkeypatch.setattr(Q, "view", lambda *a, **k: pytest.fail("no full validation without a mode 4 / 6 unit"))
    res = SM.maintain(s.ad, R.snapshot(s.g))
    assert res["writes"] == 0 and res["verified"] and s.ad.writes == []


def test_the_last_writer_fence_refuses_a_player_change_after_validation(monkeypatch):
    s = Scene()
    SM.tool_run(s.ad, "instant_qte", None, True)
    snap = R.snapshot(s.g)
    original, calls = Q.view, [0]

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        calls[0] += 1
        if calls[0] == 2:                                         # after the second fence, before the write
            sp = R.u64(s.g, BASE + R.S_PLAYER)
            s.g.q(sp + R.P_FIRST, s.player + 0x1000)
        return result

    monkeypatch.setattr(Q, "view", changed)
    res = SM.maintain(s.ad, snap)
    assert res["qte"]["phase"] == "write_unconfirmed" and not res["qte"]["completed"] and s.ad.writes == []


def test_the_operators_off_survives_the_rounds_ops_until_the_operator_turns_it_on():
    s = Scene()
    prof = {"map_id": "010018100CD46000", "platform": "switch"}
    SM.tool_run(s.ad, "instant_qte", None, False, operator=True)            # the panel
    mercs_bot.apply_ops(s.ad, [("instant_qte", {"on": True})], prof)       # the next round's playing_ops
    assert not SM.ORIG[id(s.ad)]["qte"].get("on")
    assert SM.maintain(s.ad, R.snapshot(s.g))["writes"] == 0 and s.ad.writes == []
    assert SM.tool_run(s.ad, "instant_qte", None, True, operator=True)["configured"]
    assert SM.ORIG[id(s.ad)]["qte"]["on"]


def test_turning_it_off_or_revert_all_stops_every_write():
    s = Scene()
    SM.tool_run(s.ad, "instant_qte", None, True)
    assert SM.tool_run(s.ad, "revert_all")["reverted"]["instant_qte"]
    assert not SM.ORIG[id(s.ad)]["qte"]["on"]
    assert SM.maintain(s.ad, R.snapshot(s.g))["writes"] == 0 and s.ad.writes == []


def test_out_of_a_round_nothing_is_read_or_written():
    s = Scene()
    SM.tool_run(s.ad, "instant_qte", None, True)
    assert SM.maintain(s.ad, R.snapshot(s.g), enabled=False)["writes"] == 0
    assert SM.maintain(s.ad, {"player": None})["writes"] == 0 and s.ad.writes == []


def test_the_profile_turns_it_on_for_the_bot_every_round():
    rm = ram_map.find({"game_id": "52d15709be0fda1a", "platform": "switch"})
    assert ["instant_qte", {"on": True}] in rm.spec["mercs"]["playing_ops"]
    s = Scene()
    prof = {"map_id": "010018100CD46000", "platform": "switch"}
    assert mercs_bot.apply_ops(s.ad, [("instant_qte", {"on": True})], prof) == []
    assert SM.ORIG[id(s.ad)]["qte"]["on"] and s.ad.writes == []


def test_the_driver_completes_the_grab_from_its_snapshot_and_reports_it():
    s = Scene()
    SM.tool_run(s.ad, "instant_qte", None, True)
    m = SM.Mem(s.ad)
    drv = R.RE5Switch()
    stats = {}
    drv.brain(m, stats, clock=lambda: 0.0)
    snap = R.snapshot(m)
    assert snap["prompt"]["token"] == "mash:wiggle"               # the bot's own wiggle stays the fallback
    assert drv.screen(m, snap) == "playing"
    assert s.ad.writes == [(s.unit + Q.PROGRESS, f32(10.0))]
    assert stats["qte_native"]["phase"] == "submitted" and stats["qte_native_counts"]["progress_writes"] == 1


def test_a_new_boot_needs_the_op_again():
    s = Scene()
    SM.tool_run(s.ad, "instant_qte", None, True)
    snap = dict(R.snapshot(s.g), module_base=BASE + 0x100000)
    res = SM.maintain(s.ad, snap)
    assert res["qte"]["phase"] == "rejected" and s.ad.writes == []


# --- the press outcomes: read only ---------------------------------------------------------------------------------
def test_press_outcomes_are_counted_without_any_write():
    s = Scene(1, key=1, label=58, motion=0)
    SM.tool_run(s.ad, "instant_qte", None, True)
    snap = R.snapshot(s.g)
    SM.maintain(s.ad, snap)
    s.g.put(s.button + Q.BTN_ACCEPTED, b"\1\1")
    SM.maintain(s.ad, snap)
    SM.maintain(s.ad, snap)                                       # counted once
    other = s.make_button(1, 0, 1, 7, serial=23)                  # a strict press the game failed (wrong key)
    s.show(s.unit, other, 1, 0.0, 0, 1, serial=23)
    s.g.put(other + Q.BTN_STRICT, b"\1")
    s.g.put(other + Q.BTN_EXCLUDED, struct.pack("<I", 1))
    SM.maintain(s.ad, snap)
    third = s.make_button(3, 0, 13, 9, serial=24)                 # a chord that hid unanswered
    s.show(s.unit, third, 3, 0.0, 0, 13, serial=24)
    SM.maintain(s.ad, snap)
    s.g.put(s.unit + P.UNIT_SHOWN, b"\0")
    res = SM.maintain(s.ad, snap)
    assert res["qte"]["press_outcomes"] == {"mode1_accepted": 1, "mode1_failed": 1, "mode3_ended": 1}
    assert s.ad.writes == []
