"""Native save/unlock confirmations return to selection without fabricating a live player."""
import struct

import pytest

from gbox import mercs_bot
from gbox.mercs import engine, lessons
from gbox.mercs.titles import re5_ps3 as R
from test_re5_mercs import SPLAYER, with_ui, world


def modal(alert=9, *, player=False):
    memory = world(timer=50.58083724975586)
    if not player:
        memory.u32(SPLAYER + 0x28, 0)
    with_ui(memory, [("uIdAlert00", {R.ALERT_ID: alert})], line=0)
    unit = R.ui_units(memory)["uIdAlert00"]
    memory.put(unit + 0x16, b"\x01\x00")  # live save-success receipt, 2026-10-25
    return memory, unit


def unlock_notice(memory=None, *, index=0, mask=3, player=False, line=0):
    if memory is None:
        memory = world(timer=0. if player else 50.)
        if not player:
            memory.u32(SPLAYER + 0x28, 0)
    with_ui(memory, [("uIdMerceEd00", {0x290: mask, 0x294: index})], line=line)
    unit = R.ui_units(memory, range(R.N_LINES))["uIdMerceEd00"]
    memory.put(unit + 0x16, b"\x03\x06")
    memory.put(unit + 0x28C, bytes.fromhex("3dcccccd"))
    memory.put(unit + 0x298, b"\x01")
    memory.u32(R.S_BIOPAD, 0x38000000)
    memory.u32(0x38000000 + R.PAD_CONFIRM, 0x4000)
    for address, code in R.MERCE_NOTICE_CODE:
        memory.put(address, code)
    return memory, unit


@pytest.mark.parametrize("player", [False, True])
@pytest.mark.parametrize("alert,where,key", [(9, "alert_ok", "cross"),
                                              (8, "alert_ok", "cross"),
                                              (0x22, "alert_signin", "circle")])
def test_known_alert_overrides_round_fields_with_or_without_player(player, alert, where, key):
    memory, _ = modal(alert, player=player)
    snap = R.snapshot(memory)
    driver = R.RE5PS3(clock=lambda: 1000.)
    assert driver.screen(memory, snap) == where
    assert driver.menu_handoff(memory, snap, where) is True
    assert R.step(R.screen(memory)) == key


@pytest.mark.parametrize("alert", [0, 0x13, 0xDEAD])
def test_unknown_or_loading_alert_never_authorizes_input_or_handoff(alert):
    memory, _ = modal(alert)
    snap = R.snapshot(memory)
    driver = R.RE5PS3()
    where = driver.screen(memory, snap)
    assert where in ("loading", "alert")
    assert driver.menu_handoff(memory, snap, where) is False
    assert R.step(R.screen(memory)) is None


@pytest.mark.parametrize("change", ["vtable", "id", "state", "read_error"])
def test_alert_transition_or_unreadable_memory_invalidates_handoff(change):
    memory, unit = modal()
    driver = R.RE5PS3()
    snap = R.snapshot(memory)
    assert driver.screen(memory, snap) == "alert_ok"
    if change == "vtable":
        memory.u32(unit, 0x015AB6E8)
    elif change == "id":
        memory.u32(unit + R.ALERT_ID, 0x13)
    elif change == "state":
        memory.put(unit + 0x16, b"\x02\x00")
    else:
        memory.rd = lambda *_: (_ for _ in ()).throw(OSError("unreadable"))
    assert driver.menu_handoff(memory, snap, "alert_ok") is False


def test_alert_recycled_during_native_read_cannot_authorize_a_press():
    memory, unit = modal()
    original = memory.rd

    def racing(address, size):
        data = original(address, size)
        if address == unit and size == R.ALERT_ID + 4:
            memory.u32(unit + R.ALERT_ID, 0x13)
        return data

    memory.rd = racing
    observed = R.alert_screen(memory)
    assert observed["where"] == "alert"
    assert R.step(observed) is None


class Clock:
    def __init__(self):
        self.t = 1.

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


class IdleBrain:
    def tick(self, _):
        raise AssertionError("a playerless modal must not invoke combat")

    def save(self):
        pass


@pytest.mark.parametrize("alert,expected", [(9, "round"), (0x13, "lost"), (0xDEAD, "lost")])
def test_round_engine_hands_only_known_native_modal_to_menu_navigation(tmp_path, monkeypatch, alert, expected):
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "lessons")
    memory, _ = modal(alert)
    clock, sent, stats = Clock(), [], {}
    driver = R.RE5PS3(clock=clock)
    result = engine.play_round({"map_id": "BLUS30491"}, memory, sent.extend,
                              lambda: clock.t > 40., stats, driver=driver, brain=IdleBrain(),
                              clock=clock, sleep=clock.sleep, learn_dir=tmp_path)
    assert result == expected
    assert not any(row["down"] for row in sent)
    assert not R.snapshot(memory)["player"]
    if expected == "round":
        assert clock.t < engine.LOST_S
        nav = mercs_bot.Navigator(sent.extend, R.step, sleep=clock.sleep, clock=clock, stats=stats)
        assert nav.tick(R.screen(memory)) is None
        clock.sleep(nav.STABLE_S + .01)
        assert nav.tick(R.screen(memory)) == "cross"
        assert [row for row in sent if row["down"]] == [{"key": "cross", "down": True}]
    else:
        assert clock.t > engine.LOST_S


def test_playerless_black_screen_still_uses_the_lost_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "lessons")
    memory = world(timer=50.)
    memory.u32(SPLAYER + 0x28, 0)
    clock, sent = Clock(), []
    result = engine.play_round({"map_id": "BLUS30491"}, memory, sent.extend,
                              lambda: clock.t > 40., {}, driver=R.RE5PS3(clock=clock), brain=IdleBrain(),
                              clock=clock, sleep=clock.sleep, learn_dir=tmp_path)
    assert result == "lost" and clock.t > engine.LOST_S
    assert not any(row["down"] for row in sent)


def test_distinct_native_notice_identity_gets_its_own_stability_window():
    memory, unit = modal(9)
    clock, sent = Clock(), []
    nav = mercs_bot.Navigator(sent.extend, R.step, sleep=clock.sleep, clock=clock)
    assert nav.tick(R.screen(memory)) is None
    clock.sleep(nav.STABLE_S + .01)
    assert nav.tick(R.screen(memory)) == "cross"
    clock.sleep(nav.RETRY_S + .01)
    memory.u32(unit + R.ALERT_ID, 8)
    assert nav.tick(R.screen(memory)) is None  # both are alert_ok, but not the same native notice
    clock.sleep(nav.STABLE_S + .01)
    assert nav.tick(R.screen(memory)) == "cross"


@pytest.mark.parametrize("selector,fields,expected", [
    ("uIdStartUp22", {R.SELECT_CURSOR: 0}, "dright"),
    ("uIdStartUp01", {R.MENU_SUB: 1, R.EXTRA_CURSOR: 0}, "ddown"),
])
def test_confirmation_chain_stops_at_native_character_or_mode_selection(monkeypatch, selector, fields, expected):
    monkeypatch.setattr(R, "ROSTER", R.Roster())
    R.ROSTER.pick = 2
    memory = world(timer=0.)
    clock, sent, stats = Clock(), [], {}
    boot = mercs_bot.Boot(R, memory, sent.extend, sleep=clock.sleep, clock=clock, stats=stats)

    def settle():
        assert boot.tick() is None
        clock.sleep(mercs_bot.Navigator.STABLE_S + .01)
        assert boot.tick() is None
        clock.sleep(mercs_bot.Navigator.RETRY_S + .01)

    settle()
    assert [row["key"] for row in sent if row["down"]] == ["start"]
    memory.u32(SPLAYER + 0x28, 0)
    with_ui(memory, [("uIdAlert00", {R.ALERT_ID: 9})], line=0)
    settle()
    _, unit = unlock_notice(memory)
    settle()
    memory.u32(unit + 0x294, 1)
    settle()
    assert [row["key"] for row in sent if row["down"]] == ["start", "cross", "cross", "cross"]
    assert boot.nav.confirmation_started is not None
    with_ui(memory, [(selector, fields)], line=0)
    settle()
    assert boot.nav.confirmation_started is None
    assert stats["confirmation_chain"] == "complete: native selection screen"
    assert [row["key"] for row in sent if row["down"]][-1] == expected


@pytest.mark.parametrize("bound", ["time", "presses"])
def test_known_confirmation_chain_has_a_finite_bound(monkeypatch, bound):
    memory, _ = modal()
    clock, sent = Clock(), []
    boot = mercs_bot.Boot(R, memory, sent.extend, sleep=clock.sleep, clock=clock)
    monkeypatch.setattr(boot.nav, "CONFIRMATION_MAX_PRESSES", 2)
    monkeypatch.setattr(boot.nav, "CONFIRMATION_MAX_S", 1. if bound == "time" else 120.)
    why = None
    for _ in range(10):
        why = boot.tick()
        if why:
            break
        clock.sleep(1.3)
    assert "confirmation chain" in why
    assert len([row for row in sent if row["down"]]) <= 2


def test_unknown_screen_inside_confirmation_chain_cannot_use_cold_boot_cross():
    memory, _ = modal()
    clock, sent = Clock(), []
    boot = mercs_bot.Boot(R, memory, sent.extend, sleep=clock.sleep, clock=clock)
    assert boot.tick() is None
    clock.sleep(.6)
    assert boot.tick() is None
    assert [row["key"] for row in sent if row["down"]] == ["cross"]
    with_ui(memory, [], line=0)
    for _ in range(5):
        clock.sleep(2.)
        assert boot.tick() is None
    assert [row["key"] for row in sent if row["down"]] == ["cross"]


def test_unknown_notice_changes_cannot_extend_confirmation_chain_forever():
    memory, unit = modal()
    clock, sent = Clock(), []
    boot = mercs_bot.Boot(R, memory, sent.extend, sleep=clock.sleep, clock=clock)
    assert boot.tick() is None
    for offset in range(1, 5):
        clock.sleep(20.)
        memory.u32(unit + R.ALERT_ID, 0x100 + offset)
        assert boot.tick() is None
    clock.sleep(41.)
    assert "confirmation chain" in boot.tick()
    assert not sent


def test_signin_keeps_its_existing_circle_action_and_is_not_an_unlock_confirmation():
    memory, _ = modal(0x22)
    scr = R.screen(memory)
    assert R.step(scr) == "circle" and scr["confirmation"] is False


@pytest.mark.parametrize("line", [0, 1])
def test_native_unlock_notice_requires_full_native_page_evidence(line):
    memory, _ = unlock_notice(index=23, mask=1 << 23, line=line)
    scr = R.screen(memory)
    assert scr["where"] == "unlock_notice" and scr["unlock_ready"] is True
    assert scr["unlock_index"] == 23 and R.step(scr) == "cross"
    driver = R.RE5PS3()
    snap = R.snapshot(memory)
    assert driver.screen(memory, snap) == "unlock_notice"
    assert driver.menu_handoff(memory, snap, "unlock_notice") is True


@pytest.mark.parametrize("change", ["signature", "outer", "inner", "inactive", "fade", "index",
                                     "mask_empty", "mask_unset", "mask_unknown", "confirm", "pad"])
def test_unknown_or_unready_result_notice_never_confirms(change):
    memory, unit = unlock_notice()
    if change == "signature": memory.put(R.MERCE_NOTICE_CODE[0][0], b"\x00")
    elif change == "outer": memory.put(unit + 0x17, b"\x05")
    elif change == "inner": memory.put(unit + 0x16, b"\x04")
    elif change == "inactive": memory.put(unit + 0x298, b"\x00")
    elif change == "fade": memory.put(unit + 0x28C, struct.pack(">f", .05))
    elif change == "index": memory.u32(unit + 0x294, 24)
    elif change == "mask_empty": memory.u32(unit + 0x290, 0)
    elif change == "mask_unset": memory.u32(unit + 0x290, 2)
    elif change == "mask_unknown": memory.u32(unit + 0x290, 0x80000001)
    elif change == "confirm": memory.u32(0x38000000 + R.PAD_CONFIRM, 0x2000)
    else: memory.u32(R.S_BIOPAD, 0)
    scr = R.screen(memory)
    assert scr["unlock_ready"] is False and R.step(scr) is None


@pytest.mark.parametrize("race", ["state", "index", "confirm"])
def test_unlock_page_transition_during_guard_reads_never_confirms(race):
    memory, unit = unlock_notice()
    original = memory.rd

    def racing(address, size):
        data = original(address, size)
        if address == 0x38000000 + R.PAD_CONFIRM:
            if race == "state": memory.put(unit + 0x16, b"\x04")
            elif race == "index": memory.u32(unit + 0x294, 1)
            else: memory.u32(address, 0x2000)
        return data

    memory.rd = racing
    assert R.step(R.screen(memory)) is None


def test_unreadable_known_result_unit_does_not_fall_back_to_start():
    memory, unit = unlock_notice(player=True)
    original = memory.rd
    memory.rd = lambda address, size: (_ for _ in ()).throw(OSError("unreadable")) \
        if address == unit and size == 0x29C else original(address, size)
    scr = R.screen(memory)
    assert scr["where"] == "results_wait" and R.step(scr) is None


def test_unlock_notice_with_player_preserves_terminal_score_tally():
    memory, _ = unlock_notice(player=True)
    driver = R.RE5PS3()
    snap = R.snapshot(memory)
    assert driver.screen(memory, snap) == "results"
    assert driver.result_ready(snap, 1.) is False
    assert driver.result_ready(snap, 3.1) is True
    assert R.step(R.screen(memory)) == "cross"


def test_playerless_unlock_notice_hands_off_without_combat_or_unknown_boot_input(tmp_path, monkeypatch):
    monkeypatch.setattr(lessons, "ROOT", tmp_path / "lessons")
    memory, _ = unlock_notice()
    clock, sent = Clock(), []
    result = engine.play_round({"map_id": "BLUS30491"}, memory, sent.extend,
                              lambda: clock.t > 40., {}, driver=R.RE5PS3(clock=clock), brain=IdleBrain(),
                              clock=clock, sleep=clock.sleep, learn_dir=tmp_path)
    assert result == "round" and clock.t < engine.LOST_S
    assert not sent


def test_unlock_fadeout_waits_before_the_next_pending_notice():
    memory, unit = unlock_notice()
    clock, sent = Clock(), []
    nav = mercs_bot.Navigator(sent.extend, R.step, sleep=clock.sleep, clock=clock)
    assert nav.tick(R.screen(memory)) is None
    clock.sleep(nav.STABLE_S + .01)
    assert nav.tick(R.screen(memory)) == "cross"
    memory.put(unit + 0x16, b"\x04")
    clock.sleep(2.)
    assert nav.tick(R.screen(memory)) is None
    memory.u32(unit + 0x294, 1)
    memory.put(unit + 0x16, b"\x03")
    assert nav.tick(R.screen(memory)) is None
    clock.sleep(nav.STABLE_S + .01)
    assert nav.tick(R.screen(memory)) == "cross"
    assert [row["key"] for row in sent if row["down"]] == ["cross", "cross"]
