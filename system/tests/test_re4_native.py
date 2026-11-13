"""The RE4 native harness controller (E4/E5): the writes, the trigger, the mailbox and its refusal cases.

A fake guest builds the image's real layout - a player unit of class 0xB0C0A0 whose vtable slot +0xA0 holds
main+0x312600, a zero cave, and a mailbox - and a fake dispatcher consumes one published request. No game.
"""
import json
import math
import struct
import types
import threading

import pytest

from gbox.mercs.titles import re4_switch as R
from gbox.mercs.titles import re4_switch_native as N
from gbox.mercs.titles import re6_switch_native as NB
from gbox.mercs.native.re4_82c2a04a import code as CODE

BASE = 0x100000000
PLAYER = 0x200000000
MAILBOX = 0x900000000
PLAYER_VT = BASE + 0xB0C0A0
CAVE = BASE + CODE.CAVE_AT
CLONE = MAILBOX + CODE.CLONE_DATA_OFF + CODE.CLONE_CLASSES.index(0xB0C0A0) * CODE.CLONE_SIZE


def put(mem, at, data):
    mem.update({at + i: b for i, b in enumerate(data)})


def get(mem, at, n):
    return bytes(mem.get(at + i, 0) for i in range(n))


def fake_controller(monkeypatch, *, mailbox=MAILBOX, complete=True, fail_at=None):
    ctl = N.Controller.__new__(N.Controller)
    ctl.lock = threading.RLock()
    ctl.base, ctl.pid, ctl.identity = BASE, 4242, (4242, 7)
    ctl.mailbox, ctl.player, ctl.original, ctl.player_id = mailbox, None, None, None
    ctl.request_generation, ctl.failed = 0, False
    ctl.player_class = None
    mem, writes, installed = {}, [], []
    ctl.mem, ctl.writes, ctl.installed = mem, writes, installed
    ctl.check = ctl.check_build = lambda: None
    ctl.stopped = lambda fn: fn()

    def read(at, n):
        return get(mem, at, n)

    def ad_write(at, data):
        writes.append((at, bytes(data)))
        put(mem, at, data)

    ctl.rd = read
    ctl.q = lambda at: struct.unpack("<Q", read(at, 8))[0]
    ctl.w = lambda at: struct.unpack("<I", read(at, 4))[0]
    ctl.ad = types.SimpleNamespace(address_mode="direct", paused=False,
                                   write_memory=ad_write, read_memory=read, _guest=lambda: (4242, 1))
    ctl.ad._re4_switch_harness = ctl

    # the unit itself
    unit = bytearray(0x400)
    struct.pack_into("<Q", unit, 0, PLAYER_VT)
    struct.pack_into("<Q", unit, 0x110, 7)                       # id
    struct.pack_into("<3f", unit, 0xA4, 1.0, 2.0, 3.0)           # position
    struct.pack_into("<3f", unit, 0xB4, 0.0, 0.0, 0.0)           # rotation
    struct.pack_into("<H", unit, 0x3C2, 100)                     # hp
    struct.pack_into("<H", unit, 0x3C4, 100)                     # hp max
    unit[0x3CE] = 0                                              # type
    put(mem, PLAYER, unit)
    put(mem, BASE + R.S_PLAYER, struct.pack("<Q", PLAYER))
    put(mem, BASE + R.PLAYER_LIFE, struct.pack("<H", 1000))      # his own life field (u16)
    vt = bytearray(32 * 8)
    for slot in range(32):
        struct.pack_into("<Q", vt, slot * 8, BASE + 0x1234)
    struct.pack_into("<Q", vt, CODE.SLOT_TICK, BASE + CODE.ORIGINAL_TICK)
    put(mem, BASE + 0xB0C0A0, vt)                                # the class vtable the player carries (Leon B)

    def fake_install(self, at, data):
        before = get(mem, at, len(data))
        if before == data:
            return
        if any(before):
            raise N.Unavailable("native code padding is occupied")
        installed.append((at, bytes(data)))
        put(mem, at, data)
    monkeypatch.setattr(NB.Controller, "install", fake_install, raising=False)

    requests = {"n": 0}

    def wait(predicate, timeout=1.0):
        state = ctl.w(MAILBOX + CODE.MAILBOX["state"]) if ctl.mailbox else 0
        if not complete:
            raise N.Uncertain("native completion uncertain; request will not be replayed")
        if state == CODE.STATE["requested"]:
            requests["n"] += 1
            put(mem, MAILBOX + CODE.MAILBOX["ticks"], struct.pack("<Q", requests["n"]))   # the dispatcher ticks
            if fail_at is not None and requests["n"] == fail_at:
                raise N.Uncertain(f"native request {fail_at} timed out; not replayed")
            target = ctl.q(MAILBOX + CODE.MAILBOX["target"])
            args = struct.unpack("<7Q", get(mem, MAILBOX + CODE.MAILBOX["args"], 56))
            result = 0 if target == BASE + CODE.SELFTEST_AT else target + sum(args)
            put(mem, MAILBOX + CODE.MAILBOX["result"], struct.pack("<Q", result))
            put(mem, MAILBOX + CODE.MAILBOX["state"], struct.pack("<I", CODE.STATE["done"]))
        return predicate()
    ctl.wait = wait
    return ctl


# ---- E4: the write rule -----------------------------------------------------------------------------------------------

def test_a_write_into_code_or_rodata_is_refused(monkeypatch):
    ctl = fake_controller(monkeypatch)
    for at in (BASE + 0x100, BASE + 0x312600, BASE + 0x655880, BASE + 0x900000):
        with pytest.raises(N.Unavailable, match="code or read-only"):
            ctl.write(at, b"\x00\x00\x00\x00")
    ctl.write(MAILBOX + CODE.MAILBOX["state"], b"\x00\x00\x00\x00")     # .bss/heap is allowed
    assert ctl.writes and ctl.writes[-1][0] == MAILBOX


def test_install_outside_the_cave_is_refused(monkeypatch):
    ctl = fake_controller(monkeypatch)
    with pytest.raises(N.Unavailable, match="outside the vetted cave"):
        ctl.install(BASE + 0x100, b"\x00" * 8)
    with pytest.raises(N.Unavailable, match="outside the vetted cave"):
        ctl.install(CAVE + CODE.CAVE_SIZE, b"\x00" * 8)
    ctl.install(CAVE, b"\x01" * 8)                                       # inside the cave: the base class decides
    assert ctl.installed and ctl.installed[0][0] == CAVE


# ---- E5: the trigger and the mailbox ---------------------------------------------------------------------------------

def test_attach_installs_dispatch_and_clone_and_writes_only_the_vtable_pointer(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    assert [at for at, _data in ctl.installed] == [CAVE, BASE + CODE.FIRST_AID_AT]
    assert ctl.installed[0][1] == CODE.IMAGES["dispatch"]
    clone = get(ctl.mem, CLONE, CODE.CLONE_SIZE)
    assert len(clone) == CODE.CLONE_SIZE
    assert struct.unpack_from("<Q", clone, CODE.SLOT_TICK)[0] == CAVE
    assert struct.unpack_from("<Q", clone, CODE.CLONE_MAILBOX_OFF)[0] == MAILBOX
    assert len(ctl.writes) == 2 and ctl.writes[-1] == (PLAYER, struct.pack("<Q", CLONE))
    assert ctl.q(PLAYER) == CLONE and ctl.attached()

    ctl.detach()
    assert ctl.q(PLAYER) == PLAYER_VT and not ctl.attached()
    assert ctl.writes[-1] == (PLAYER, struct.pack("<Q", PLAYER_VT))


def test_attaching_again_is_a_no_op(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    ctl.attach()
    assert len(ctl.installed) == 2 and len(ctl.writes) == 2


def test_snapshot_retains_only_the_attached_player_generation(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.ad._re4_switch_harness = ctl
    reader = types.SimpleNamespace(adapter=ctl.ad, rd=ctl.rd)
    ctl.attach()
    player = R.player_unit(reader, BASE)
    assert player and player["ptr"] == PLAYER and player["class"] == 0xB0C0A0
    put(ctl.mem, PLAYER + R.U_ID, struct.pack("<I", 8))
    assert R.player_unit(reader, BASE) is None


def test_attach_refuses_without_a_mailbox(monkeypatch):
    ctl = fake_controller(monkeypatch, mailbox=None)
    with pytest.raises(N.Unavailable, match="E3"):
        ctl.attach()
    assert ctl.installed == [] and ctl.writes == []


def test_attach_refuses_a_player_whose_tick_slot_is_not_pinned(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, BASE + 0xB0C0A0 + CODE.SLOT_TICK, struct.pack("<Q", BASE + 0x999))
    with pytest.raises(N.Unavailable, match="tick slot"):
        ctl.attach()
    assert ctl.writes == []


@pytest.mark.parametrize("player_class, original", sorted(CODE.TICK_BY_CLASS.items()))
def test_every_pinned_player_class_keeps_its_own_tick(monkeypatch, player_class, original):
    ctl = fake_controller(monkeypatch)
    table = bytearray(get(ctl.mem, PLAYER_VT, CODE.CLONE_ENTRIES * 8))
    struct.pack_into("<Q", table, CODE.SLOT_TICK, BASE + original)
    put(ctl.mem, BASE + player_class, table)
    put(ctl.mem, PLAYER, struct.pack("<Q", BASE + player_class))
    ctl.attach()
    assert ctl.q(ctl.clone_address + CODE.CLONE_ORIGINAL_OFF) == BASE + original
    assert ctl.q(ctl.clone_address + CODE.SLOT_TICK) == CAVE


def test_foreign_re6_controls_are_not_offered_by_re4(monkeypatch):
    ctl = fake_controller(monkeypatch)
    for name in ("drop_bomb",):
        assert getattr(ctl, name) is None
    assert ctl.equip_primary.__func__ is N.Controller.equip_primary
    assert ctl.launcher_kinds.__func__ is N.Controller.launcher_kinds
    assert all(not r['kind'].startswith('shell') for r in ctl.launcher_kinds())


def test_ring_health_does_not_include_adjacent_max_health(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, BASE + R.PLAYER_LIFE, struct.pack("<HH", 1230, 1680))
    assert ctl.player_life() == 1230


def test_character_change_reuses_code_and_keeps_separate_data_clones(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    old_clone = ctl.clone_address
    previous_bytes = ctl.rd(old_clone, CODE.CLONE_SIZE)
    new_class = 0xB098B0
    next_player = PLAYER + 0x1000
    table = bytearray(get(ctl.mem, PLAYER_VT, CODE.CLONE_ENTRIES * 8))
    struct.pack_into("<Q", table, CODE.SLOT_TICK, BASE + CODE.TICK_BY_CLASS[new_class])
    put(ctl.mem, BASE + new_class, table)
    unit = bytearray(ctl.rd(PLAYER, 0x400))
    struct.pack_into("<Q", unit, 0, BASE + new_class)
    struct.pack_into("<I", unit, R.U_ID, 99)
    put(ctl.mem, next_player, unit)
    put(ctl.mem, BASE + R.S_PLAYER, struct.pack("<Q", next_player))
    ctl.ready()
    ctl.attach()
    assert ctl.player == next_player and ctl.player_id == 99
    assert ctl.clone_address != old_clone and ctl.rd(old_clone, CODE.CLONE_SIZE) == previous_bytes
    assert ctl.q(PLAYER) == PLAYER_VT
    assert ctl.q(next_player) == ctl.clone_address
    assert len(ctl.installed) == 2


def test_attach_refuses_a_cave_that_is_not_empty(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, CAVE, b"\x01")
    with pytest.raises(N.Unavailable, match="padding is occupied"):
        ctl.attach()
    assert ctl.writes == []


def test_a_call_publishes_once_and_reads_the_result(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    result = ctl.call(0x1000, 1, 2, 3)
    assert result == BASE + 0x1000 + 6
    states = [w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["state"]]
    assert len(states) == 1 and struct.unpack("<I", states[0][1])[0] == CODE.STATE["requested"]
    assert ctl.w(MAILBOX + CODE.MAILBOX["state"]) == CODE.STATE["done"]
    assert struct.unpack("<7Q", get(ctl.mem, MAILBOX + CODE.MAILBOX["args"], 56)) == (1, 2, 3, 0, 0, 0, 0)


def test_a_timeout_is_uncertain_and_the_request_is_never_replayed(monkeypatch):
    ctl = fake_controller(monkeypatch, complete=False)
    ctl.attach()
    with pytest.raises(N.Uncertain):
        ctl.call(0x1000, 1)
    states = [struct.unpack("<I", d)[0] for at, d in ctl.writes if at == MAILBOX + CODE.MAILBOX["state"]]
    assert states == [CODE.STATE["requested"], CODE.STATE["idle"]]       # published once, then retired
    with pytest.raises(N.Unavailable, match="uncertain state"):
        ctl.call(0x1000, 1)
    assert len([w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["state"]]) == 2
    ctl.detach()
    ctl.attach()                                                         # a fresh attach clears the refusal
    assert ctl.failed is False


def test_a_changed_generation_is_not_trusted(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()

    def wait_tampered(predicate, timeout=1.0):
        put(ctl.mem, MAILBOX + CODE.MAILBOX["generation"], struct.pack("<Q", 999))
        put(ctl.mem, MAILBOX + CODE.MAILBOX["state"], struct.pack("<I", CODE.STATE["done"]))
        return predicate()
    ctl.wait = wait_tampered
    with pytest.raises(N.Uncertain, match="generation"):
        ctl.call(0x1000)


def test_call_requires_attachment(monkeypatch):
    ctl = fake_controller(monkeypatch)
    with pytest.raises(N.Unavailable, match="not attached"):
        ctl.call(0x1000)


def test_ready_refuses_a_player_of_a_non_unit_class(monkeypatch):
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, PLAYER, struct.pack("<Q", BASE + 0x1000))
    with pytest.raises(N.Unavailable, match="no player unit"):
        ctl.ready()


# ---- F2/F3: the flash op and where it goes off -----------------------------------------------------------------------

def test_flash_at_writes_the_fake_object_and_publishes_the_blast_call(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    receipt = ctl.flash_at(1.0, 2.0, 5003.0)                      # 5000 mm from the player at (1, 2, 3)
    assert receipt["state"] == "confirmed" and receipt["verified"] is False
    assert receipt["pos"] == [1.0, 2.0, 5003.0] and receipt["from_player_cm"] == 500.0
    scratch = MAILBOX + N.SCRATCH_OFF
    written = next(data for at, data in ctl.writes if at == scratch)
    assert struct.unpack_from("<3f", written, N.FLASH_OBJECT_POS) == (1.0, 2.0, 5003.0)
    assert written[N.FLASH_OBJECT_TYPE_BYTE] == 0                  # not 0xD6: the effects are not skipped
    assert ctl.q(MAILBOX + CODE.MAILBOX["target"]) == BASE + N.FLASH_BLAST
    assert ctl.q(MAILBOX + CODE.MAILBOX["args"]) == scratch
    assert ctl.w(MAILBOX + CODE.MAILBOX["state"]) == CODE.STATE["done"]


def test_flash_at_refuses_a_point_at_his_feet(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    with pytest.raises(N.Unavailable, match="minimum is 400 cm"):
        ctl.flash_at(1.0, 2.0, 3.0)
    assert not any(at == MAILBOX + N.SCRATCH_OFF for at, _data in ctl.writes)


def test_place_flash_pushes_the_point_out_to_the_minimum():
    point = N.place_flash((0.0, 0.0, 0.0), [(1000.0, 0.0, 0.0)])
    assert point is not None and math.hypot(point[0], point[2]) == pytest.approx(N.FLASH_MIN_MM)


def test_place_flash_none_when_nobody_is_near():
    assert N.place_flash((0.0, 0.0, 0.0), [(N.FLASH_FROM_MM + 1.0, 0.0, 0.0)]) is None
    assert N.place_flash(None, [(1000.0, 0.0, 0.0)]) is None


def test_place_flash_centre_and_radius_stay_in_the_operator_band():
    point = N.place_flash((0.0, 0.0, 0.0), [(5000.0, 0.0, 0.0), (0.0, 0.0, 6000.0)])
    assert point is not None
    distance = math.hypot(point[0], point[2])
    assert N.FLASH_MIN_MM - 1.0 <= distance <= N.FLASH_MAX_MM + 1.0
    assert point[0] > 0.0 and point[2] > 0.0


def test_flash_now_with_a_point(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    monkeypatch.setattr(N, "harness", lambda ad, mailbox=None: ctl)
    receipt = N.flash_now(None, point=(1.0, 2.0, 5003.0))
    assert receipt["state"] == "confirmed" and receipt["op"] == "flash_at"


def test_flash_now_places_on_the_crowd(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    monkeypatch.setattr(N, "harness", lambda ad, mailbox=None: ctl)
    monkeypatch.setattr(N.R, "snapshot", lambda m, search=True: {
        "player": {"pos": (0.0, 0.0, 0.0)}, "enemies": [{"pos": (5000.0, 0.0, 0.0)}]})
    receipt = N.flash_now(None)
    assert receipt["state"] == "confirmed"
    assert receipt["pos"][0] == pytest.approx(5000.0) and receipt["pos"][2] == pytest.approx(0.0)


def test_flash_now_refuses_when_nobody_is_near(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    monkeypatch.setattr(N, "harness", lambda ad, mailbox=None: ctl)
    monkeypatch.setattr(N.R, "snapshot", lambda m, search=True: {"player": {"pos": (0.0, 0.0, 0.0)},
                                                                 "enemies": []})
    receipt = N.flash_now(None)
    assert receipt["state"] == "unavailable" and "12 m" in receipt["reason"]


# ---- G1/G2: the ring round him ---------------------------------------------------------------------------------------

def _ring_controller(monkeypatch, **kw):
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    ctl = fake_controller(monkeypatch, **kw)
    ctl.attach()
    return ctl


def test_a_flash_ring_places_every_blast_round_him_above_the_floor(monkeypatch):
    ctl = _ring_controller(monkeypatch)
    result = ctl.grenade_ring("flash", count=4, radius_cm=1000.0, inner_cm=100.0)
    assert result["state"] == "confirmed" and result["detonated"] == 4
    assert result["inner_mm"] == 4000.0 and result["radius_mm"] == 10000.0
    assert result["hp_before"] == 1000 and result["self_damage"] == 0
    targets = [w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["target"]]
    assert len(targets) == 4 and all(struct.unpack("<Q", d)[0] == BASE + N.FLASH_BLAST for _a, d in targets)
    for row in result["grenades"]:
        assert row["from_player_cm"] >= 400 and row["radius_mm"] >= 4000


def test_a_hand_ring_uses_the_hand_blast_and_the_7000_floor(monkeypatch):
    ctl = _ring_controller(monkeypatch)
    result = ctl.grenade_ring("hand", count=2, radius_cm=800.0, inner_cm=100.0)
    assert result["state"] == "confirmed" and result["inner_mm"] == 7000.0
    targets = [w for w in ctl.writes if w[0] == MAILBOX + CODE.MAILBOX["target"]]
    assert all(struct.unpack("<Q", d)[0] == BASE + N.HAND_BLAST for _a, d in targets)
    assert all(r["from_player_cm"] >= 700 for r in result["grenades"])


def test_the_incendiary_ring_is_refused_before_any_call(monkeypatch):
    ctl = _ring_controller(monkeypatch)
    before = len(ctl.writes)
    with pytest.raises(N.Unavailable, match="not identified"):
        ctl.grenade_ring("incendiary")
    assert len(ctl.writes) == before


def test_a_failed_blast_makes_the_ring_uncertain_and_stops(monkeypatch):
    ctl = _ring_controller(monkeypatch, fail_at=3)
    result = ctl.grenade_ring("flash", count=5, radius_cm=900.0, inner_cm=400.0)
    assert result["state"] == "uncertain" and result["detonated"] == 2 and "timed out" in result["reason"]


# ---- G4: the barrage -------------------------------------------------------------------------------------------------

def _scatter_controller(monkeypatch, **kw):
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    ctl = fake_controller(monkeypatch, **kw)
    ctl.attach()
    return ctl


def test_a_random_barrage_uses_both_blasts_and_their_floors(monkeypatch):
    ctl = _scatter_controller(monkeypatch)
    result = ctl.grenade_scatter("random", count=6, toward=[(5000.0, 0.0)], kinds=("flash", "hand"),
                                 rng=__import__("random").Random(1))
    assert result["state"] == "confirmed" and result["detonated"] == 6
    assert set(result["kinds"]) == {"flash", "hand"}
    assert result["floors_cm"] == {"flash": 400.0, "hand": 700.0}
    for row in result["rounds"]:
        assert row["dist_cm"] >= (400.0 if row["kind"] == "flash" else 700.0)
        assert row["from_player_cm"] >= (400.0 if row["kind"] == "flash" else 700.0)
    targets = {struct.unpack("<Q", d)[0] for at, d in ctl.writes if at == MAILBOX + CODE.MAILBOX["target"]}
    assert targets == {BASE + N.FLASH_BLAST, BASE + N.HAND_BLAST}
    assert result["hp_before"] == 1000 and result["self_damage"] == 0


def test_an_explicit_hand_barrage_uses_the_hand_blast_and_7000(monkeypatch):
    ctl = _scatter_controller(monkeypatch)
    result = ctl.grenade_scatter("hand", count=3, toward=[(6000.0, 1000.0)])
    assert result["state"] == "confirmed" and result["kinds"] == ["hand"]
    assert all(r["kind"] == "hand" and r["dist_cm"] >= 700.0 for r in result["rounds"])
    targets = {struct.unpack("<Q", d)[0] for at, d in ctl.writes if at == MAILBOX + CODE.MAILBOX["target"]}
    assert targets == {BASE + N.HAND_BLAST}


def test_the_barrage_respects_the_learned_reach_converted_from_cm(monkeypatch):
    ctl = _scatter_controller(monkeypatch)
    result = ctl.grenade_scatter("random", count=4, toward=[(4000.0, 0.0)], safe_cm=1000.0,
                                 rng=__import__("random").Random(3))
    assert result["floors_cm"] == {"flash": 1000.0, "hand": 1000.0}
    assert all(r["dist_cm"] >= 1000.0 for r in result["rounds"])


def test_a_narrowed_draw_uses_only_the_given_kind(monkeypatch):
    ctl = _scatter_controller(monkeypatch)
    result = ctl.grenade_scatter("random", count=3, toward=[(5000.0, 0.0)], kinds=("flash",))
    assert result["kinds"] == ["flash"] and all(r["kind"] == "flash" for r in result["rounds"])


def test_the_incendiary_barrage_is_refused_before_any_call(monkeypatch):
    ctl = _scatter_controller(monkeypatch)
    before = len(ctl.writes)
    with pytest.raises(N.Unavailable, match="not identified"):
        ctl.grenade_scatter("incendiary")
    with pytest.raises(N.Unavailable, match="cannot draw"):
        ctl.grenade_scatter("random", kinds=("nuke",))
    assert len(ctl.writes) == before


def test_a_partial_barrage_is_uncertain_never_confirmed(monkeypatch):
    ctl = _scatter_controller(monkeypatch, fail_at=2)
    result = ctl.grenade_scatter("random", count=4, toward=[(5000.0, 0.0)], kinds=("flash",))
    assert result["state"] == "uncertain" and result["detonated"] == 1 and result["reason"]


def test_the_selftest_call_returns_zero_and_proves_the_path(monkeypatch):
    ctl = fake_controller(monkeypatch)
    ctl.attach()
    out = ctl.selftest()
    assert out["state"] == "confirmed" and out["verified"] is True and out["result"] == 0
    assert out["ticks"] >= 1
    targets = [struct.unpack("<Q", d)[0] for at, d in ctl.writes if at == MAILBOX + CODE.MAILBOX["target"]]
    assert targets[-1] == BASE + CODE.SELFTEST_AT


# ---- E3: the page the watch proves -----------------------------------------------------------------------------------

def test_choose_mailbox_needs_zero_at_every_load():
    loads = [{"stage": 1, "pages": {"0x1cb9000": "00" * 16, "0x1700000": "00" * 16}},
             {"stage": 2, "pages": {"0x1cb9000": "00" * 16, "0x1700000": "01" + "00" * 15}},
             {"stage": 3, "pages": {"0x1cb9000": "00" * 16}}]
    assert N.choose_mailbox(loads) == 0x1CB9000


def test_choose_mailbox_none_when_a_page_is_missing_or_dirty():
    assert N.choose_mailbox(None) is None and N.choose_mailbox([]) is None
    assert N.choose_mailbox([{"pages": {"0x1cb9000": "00" * 16}},
                             {"pages": {"0x1cb9000": "00" * 15 + "01"}}]) is None
    assert N.choose_mailbox([{"pages": {"0x1cb9000": "00" * 16}}, {"pages": {}}]) is None


def test_choose_mailbox_prefers_the_vetted_order():
    loads = [{"pages": {"0x1cb9000": "00" * 16, "0x1cba000": "00" * 16}}]
    assert N.choose_mailbox(loads) == 0x1CB9000


def test_choose_mailbox_accepts_the_published_json_string():
    payload = json.dumps([{"stage": 1, "pages": {"0x1cbb000": "00" * 16}},
                          {"stage": 2, "pages": {"0x1cbb000": "00" * 16}}])
    assert N.choose_mailbox(payload) == 0x1CBB000


# ---- E3: the status path can carry the five pages ----------------------------------------------------------------

def test_the_prepare_refusal_carries_the_five_pages(monkeypatch):
    ctl = fake_controller(monkeypatch, mailbox=None)
    ctl.base = BASE
    with pytest.raises(N.Unavailable) as raised:
        ctl.prepare()
    text = str(raised.value)
    assert "E3" in text and "pages now" in text
    for off in R.BSS_WATCH_PAGES:
        assert f"{off:#x}=" + "00" * R.BSS_WATCH_BYTES in text


def test_the_probe_reports_a_nonzero_page(monkeypatch):
    ctl = fake_controller(monkeypatch, mailbox=None)
    ctl.base = BASE
    page = R.BSS_WATCH_PAGES[2]
    put(ctl.mem, BASE + page, b"\x01" + b"\0" * (R.BSS_WATCH_BYTES - 1))
    text = ctl.bss_watch_probe()
    assert f"{page:#x}=01" + "00" * (R.BSS_WATCH_BYTES - 1) in text
    assert len(text.split(";")) == len(R.BSS_WATCH_PAGES)


# ---- G3's probe path: the incendiary candidate behind allow_unverified ------------------------------------------------

def test_the_incendiary_ring_is_refused_without_the_probe_flag(monkeypatch):
    ctl = _ring_controller(monkeypatch)
    before = len(ctl.writes)
    with pytest.raises(N.Unavailable, match="not identified"):
        ctl.grenade_ring("incendiary")
    assert len(ctl.writes) == before


def test_the_incendiary_probe_calls_the_candidate_fire_and_marks_the_receipt(monkeypatch):
    ctl = _ring_controller(monkeypatch)
    result = ctl.grenade_ring("incendiary", count=2, radius_cm=900.0, inner_cm=400.0, allow_unverified=True)
    assert result["state"] == "confirmed" and result["detonated"] == 2 and result["probe"] is True
    targets = [struct.unpack("<Q", d)[0] for at, d in ctl.writes if at == MAILBOX + CODE.MAILBOX["target"]]
    assert targets == [BASE + N.INCENDIARY_CANDIDATE] * 2
    assert all(r["from_player_cm"] >= 400 for r in result["grenades"])


# ---- the builder every native title's controller goes through -------------------------------------------------------

def test_the_interventions_builder_can_build_the_harness_under_its_create_lock(monkeypatch):
    """interventions.native_controller holds module._CREATE_LOCK while it builds each title's one Controller.

    The harness had no such lock, so the builder skipped it with "module ... has no attribute '_CREATE_LOCK'"
    (live 2026-11-11: an RE4 round's interventions status was unavailable for that reason and the PiP greyed every
    grenade kind). The fake adapter proves the RE4 module is the one the builder takes, under that lock.
    """
    from gbox.mercs import interventions
    built = []

    class FakeController:
        def __init__(self, ad, **kwargs):
            built.append(ad)

    monkeypatch.setattr(N, "Controller", FakeController)
    adapter = types.SimpleNamespace()
    with N._CREATE_LOCK:
        pass                                   # the builder's own protocol: the lock exists and is reentrant-safe here
    ctl = interventions.native_controller(adapter)
    assert isinstance(ctl, FakeController) and built == [adapter]
    assert adapter._re4_switch_harness is ctl


def test_the_committed_mailbox_is_the_three_load_page_in_main_s_known_base():
    """E3's choice, pinned: 0x1700000 was the page all-zero at the three live round-start loads (2026-11-11 11:26,
    session 0569c82d21614288-c655ae564d744afc), and the harness takes the absolute guest address main's known base
    (0x3ca7c04000) plus that page. A no-op change here would leave the harness unable to attach or, worse, pointing
    the dispatcher at a page the game writes."""
    assert N.MAILBOX_AT == N.R.KNOWN_BASES[0] + 0x1700000
    assert N.MAILBOX_AT % 8 == 0


def test_ready_returns_the_player_and_a_generation_for_the_worker_epoch(monkeypatch):
    """interventions' worker unpacks `p, generation = ctl.ready()`; the RE4 controller returned the bare player, so
    the first status read after the mailbox stopped `prepare()` refusing died on "cannot unpack non-iterable int
    object" (live 2026-11-11 11:44). The generation is the player unit's id."""
    ctl = fake_controller(monkeypatch)
    monkeypatch.setattr(N.R, "player_unit", lambda m, b: {"ptr": PLAYER, "id": 7, "vtable": BASE + 0xB0C0A0})
    ctl.check_build = lambda: None
    player, generation = ctl.ready()
    assert (player, generation) == (PLAYER, 7)
    assert ctl.player == PLAYER and ctl.player_id == 7


def test_the_re4_check_guards_the_player_without_the_re6_sp(monkeypatch):
    """The base class's check() reads RE6's `self.sp` and generation offsets; the RE4 controller has neither, so the
    first real selftest died on "'Controller' object has no attribute 'sp'" (live 2026-11-11 12:06, session
    ae2bda4751dc44b1-b3962aa67f134135). The RE4 guard checks the process/build and the bound unit instead."""
    ctl = fake_controller(monkeypatch)
    ctl.player, ctl.player_class, ctl.player_id, ctl.original = PLAYER, 0xB0C0A0, 7, PLAYER_VT
    monkeypatch.setattr(N.R, "read_unit",
                        lambda m, addr: {"ptr": addr, "id": m.q(addr + 0x110) & 0xFFFFFFFF, "vtable": m.q(addr)})
    del ctl.check                          # the fake shadows it with a no-op: exercise the class guard
    ctl.check()                            # no AttributeError, no sp read
    put(ctl.mem, PLAYER, struct.pack("<Q", BASE + 0x999))
    with pytest.raises(N.Unavailable, match="vtable"):
        ctl.check()


def test_the_selftest_reports_the_mailbox_counters_when_the_call_never_completes(monkeypatch):
    """The E6 diagnosis: a call that never completes must return the ticks/state, so "the dispatcher is never invoked"
    (ticks unchanged) and "it runs but the handshake is wrong" (ticks rose) can be told apart live."""
    ctl = fake_controller(monkeypatch, complete=False)
    ctl.attach()
    before = ctl.ticks()
    out = ctl.selftest()
    assert out["state"] == "uncertain" and "native completion uncertain" in out["reason"]
    assert out["ticks_before"] == before and out["ticks"] == before
    assert out["mailbox_state"] is not None and out["attached_after"] is True


def test_the_ring_attaches_the_harness_itself(monkeypatch):
    """The operator's clicks and the bot's own ring failed "the harness is not attached to the player": the status
    path only BINDS the player, nothing put the clone on it. Every native op now attaches on demand."""
    ctl = fake_controller(monkeypatch)
    assert not ctl.attached()
    result = ctl.grenade_ring("flash", count=2, radius_cm=500.0, inner_cm=100.0)
    assert ctl.attached() and result["state"] == "confirmed" and result["detonated"] == 2
    assert ctl.ticks() == 2, "both native calls really ran through the mailbox"
