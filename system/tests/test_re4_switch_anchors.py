"""RE4 Switch's RAM readers: the round clock found by its fall against wall time, the unit census by class vtable.

Recorded bytes (tests/fixtures/re4sw_bss_menu.json, lilspark 2026-11-09, the title and main menu) pin the one thing a
menu must never do - pass for a running round clock - and synthetic memories built to the measured layout (module base,
bss rows, the clock cluster's 0x30 stride, the code-derived unit health at +0x3c2) pin the finders' arithmetic.
"""
import json
import struct
from pathlib import Path

import pytest

from gbox.mercs.titles import re4_switch as D

B = 0x3CA7C04000
FIXTURE = Path(__file__).parent / "fixtures" / "re4sw_bss_menu.json"


class Mem:
    """A guest memory of a few regions; rd() outside them raises like the adapter does."""

    def __init__(self, regions=None, signature=True):
        self.regions = {a: bytearray(d) for a, d in (regions or {}).items()}
        if signature:
            self.regions[B + D.SIG_OFF] = bytearray(D.SIGNATURE)

    def rd(self, a, n):
        for start, d in self.regions.items():
            if start <= a and a + n <= start + len(d):
                return bytes(d[a - start:a - start + n])
        raise ValueError(f"{a:#x} is not mapped")

    def put_f32(self, a, v):
        for start, d in self.regions.items():
            if start <= a < start + len(d):
                struct.pack_into("<f", d, a - start, v)
                return
        raise KeyError(hex(a))


def bss_mem(clock_off=0x1274710, value=118.4):
    """The bss's first row with a clock cluster: copies 0x30 apart from clock_off (2026-11-05's shape)."""
    m = Mem({B + 0xB00000: bytes(0x77D000)})
    for k in range(4):
        m.put_f32(B + clock_off + 0x30 * k, value + 0.001 * k)
    return m


def tick_clock(m, clock_off, value):
    for k in range(4):
        m.put_f32(B + clock_off + 0x30 * k, value + 0.001 * k)


def test_the_measured_layout_is_recorded():
    assert D.KNOWN_BASES == (0x3CA7C04000,)
    assert D.BSS_ROWS[0] == (0xB00000, 0x77D000) and D.BSS_ROWS[-1][0] + D.BSS_ROWS[-1][1] == D.BSS_END == 0x1CC0000
    assert all(a + n == b for (a, n), (b, _) in zip(D.BSS_ROWS, D.BSS_ROWS[1:])), "the rows tile the span"
    assert all(D.BSS_ROWS[0][0] <= off < D.BSS_ROWS[0][0] + D.BSS_ROWS[0][1] for off in D.CLOCK_HINTS)
    assert (D.U_HP, D.U_TYPE) == (0x3C2, 0x3CE)


def test_the_known_base_is_confirmed_by_one_signature_read():
    m = Mem()
    assert D.module_base(m) == B and m.module_base == B


def test_no_signature_no_base():
    class Rowless(Mem):
        adapter = None

    assert D.module_base(Rowless(signature=False)) is None


def test_a_falling_float_is_the_clock_and_a_still_one_is_not():
    before = [(B + 0xB00000, struct.pack("<4f", 118.4, 30.0, 0.5, 200.0))]
    after = [(B + 0xB00000, struct.pack("<4f", 117.4, 29.98, 0.5, 199.0))]
    got = D.clock_candidates(before, after, 1.0)
    assert [a for a, *_ in got] == [B + 0xB00000], got       # 30.0 fell 0.02 (a menu timer), 200 is out of range


@pytest.mark.parametrize("drop,dt,found", [(1.0, 1.0, True), (0.55, 1.0, False), (1.5, 1.0, False), (4.0, 4.0, True)])
def test_the_fall_must_match_the_wall_time(drop, dt, found):
    before = [(B, struct.pack("<f", 100.0))]
    after = [(B, struct.pack("<f", 100.0 - drop))]
    assert bool(D.clock_candidates(before, after, dt)) is found


def test_the_cluster_is_taken_over_a_stray_countdown():
    """The copies agree within a few ms (a tie at 0.01 s: the lowest address); a lone countdown elsewhere loses."""
    cands = [(0x40, 110.0, 109.001), (0x10, 110.0, 109.000), (0x70, 110.0, 109.002), (0x900, 50.0, 49.0)]
    assert D.pick_clock(cands) == 0x10
    assert D.pick_clock([(0x900, 50.0, 49.0)]) == 0x900
    assert D.pick_clock([]) is None


def test_recorded_menu_bytes_hold_no_round_clock():
    """Real bytes from the title and main menu: nothing there falls like a round clock, whatever the gap."""
    fx = json.loads(FIXTURE.read_text())
    before = [(fx["base"] + int(off, 16), bytes.fromhex(s["menu1"])) for off, s in fx["slices"].items()]
    after = [(fx["base"] + int(off, 16), bytes.fromhex(s["menu2"])) for off, s in fx["slices"].items()]
    assert any(b != a for (_, b), (_, a) in zip(before, after)), "the recorded slices did change between the reads"
    for dt in (0.8, 1.0, 2.0, 4.0, 8.0):
        assert D.clock_candidates(before, after, dt) == []


def test_recorded_game_state_pointer_points_into_the_module():
    """module + 0xb25d78 (the score routine's game state, FUN_002cccc0) read as a pointer back into main's data."""
    fx = json.loads(FIXTURE.read_text())
    ptr = struct.unpack("<Q", bytes.fromhex(fx["game_state_ptr"]["menu2"]))[0]
    assert fx["base"] + D.DATA_OFF <= ptr < fx["base"] + D.BSS_END


def test_the_clock_finder_finds_follows_and_loses_the_clock():
    m = bss_mem(value=119.5)
    f = D.ClockFinder()
    assert f.observe(m, B, 100.0) is None                   # the first read of the search
    assert f.observe(m, B, 100.5) is None                   # too soon to tell a clock
    tick_clock(m, 0x1274710, 118.5)
    assert f.observe(m, B, 101.0) == pytest.approx(118.5, abs=0.01)
    assert f.addr in (B + 0x1274710 + 0x30 * k for k in range(4))
    tick_clock(m, 0x1274710, 60.25)
    assert f.observe(m, B, 160.0) == pytest.approx(60.25, abs=0.01)
    m.put_f32(f.addr, float("nan"))
    assert f.observe(m, B, 161.0) is None and f.addr is None


def test_a_held_clock_is_searched_for_again():
    m = bss_mem(value=119.5)
    f = D.ClockFinder()
    f.observe(m, B, 0.0)
    tick_clock(m, 0x1274710, 118.5)
    assert f.observe(m, B, 1.0) is not None
    f.observe(m, B, 2.0)
    assert f.observe(m, B, 2.0 + D.CLOCK_STALE_S + 0.1) == pytest.approx(118.5, abs=0.01)
    assert f.addr is None, "a paused clock is confirmed again by its fall before it is trusted"


def test_a_clock_found_anywhere_in_the_bss_not_only_at_the_hints():
    m = bss_mem(clock_off=0xC00010, value=119.0)
    f = D.ClockFinder()
    f.observe(m, B, 0.0)
    tick_clock(m, 0xC00010, 117.0)
    assert f.observe(m, B, 2.0) == pytest.approx(117.0, abs=0.01)
    assert B + 0xC00010 <= f.addr < B + 0xC00010 + 0x30 * 4


def test_a_menu_snapshot_does_not_search():
    m = bss_mem()
    snap = D.snapshot(m, now=0.0, search=False)
    assert snap["timer"] is None and getattr(m, "re4_clock").sample is None
    assert snap["player"] is None and snap["enemies"] == []


def unit(vt, hp, pos, uid, typ=0, size=0x600):
    raw = bytearray(size)
    struct.pack_into("<Q", raw, 0, B + vt)
    struct.pack_into("<I", raw, D.U_ID, uid)
    struct.pack_into("<H", raw, D.U_HP, hp)
    raw[D.U_TYPE] = typ
    struct.pack_into("<3f", raw, 0x4D0, *pos)
    struct.pack_into("<f", raw, 0x4F0, 0.5)
    return bytes(raw)


def test_unit_addresses_finds_objects_by_their_vtable_word():
    heap = bytearray(0x4000)
    heap[0x100:0x700] = unit(0xAED3B0, 1000, (1.0, 2.0, 3.0), 7)
    heap[0x2000:0x2600] = unit(0xAE7050, 1800, (0.0, 0.0, 0.0), 9)
    found = D.unit_addresses([(0x5D55000000, bytes(heap))], {B + 0xAED3B0: 0xAED3B0})
    assert found == {0xAED3B0: [0x5D55000100]}


@pytest.fixture
def mapped(monkeypatch):
    """The constants a live round will fill (re4sw_round_probe.py), set for the test."""
    monkeypatch.setattr(D, "PLAYER_CLASS", 0xAE0000)
    monkeypatch.setattr(D, "ENEMY_CLASSES", (0xAED3B0,))
    monkeypatch.setattr(D, "U_POS", 0x4D0)
    monkeypatch.setattr(D, "U_YAW", 0x4F0)
    monkeypatch.setattr(D, "HEAP_WINDOWS", ((0x5D55000000, 0x5D55010000),))
    monkeypatch.setattr(D, "UNIT_SCAN_CHUNK", 0x4000)


def test_the_snapshot_reads_the_player_and_the_ganados_once_mapped(mapped):
    heap = bytearray(0x10000)
    heap[0x0000:0x0600] = unit(0xAE0000, 1000, (-3668.2, 40.9, 6021.7), 1)
    heap[0x1000:0x1600] = unit(0xAED3B0, 400, (-3000.0, 40.0, 6000.0), 2)
    heap[0x2000:0x2600] = unit(0xAED3B0, 400, (-3000.0, 40.0, 6000.0), 2)     # the same Ganado through a second view
    heap[0x3000:0x3600] = unit(0xAED3B0, 0, (-2000.0, 40.0, 6000.0), 3)       # a dead one: kept, hp 0
    heap[0x4000:0x4600] = unit(0xAE7050, 1800, (-3540.0, 190.0, 5880.0), 4)   # a spawn marker: not a unit
    m = Mem({B + 0xB00000: bytes(0x77D000), 0x5D55000000: bytes(heap)})
    snap = D.snapshot(m, now=0.0)
    assert snap["player"]["pos"] == pytest.approx((-3668.2, 40.9, 6021.7), abs=0.01)
    assert snap["player"]["hp"] == 1000 and snap["player"]["rot"] == pytest.approx(0.5)
    assert sorted((e["id"], e["hp"]) for e in snap["enemies"]) == [(2, 400), (3, 0)]
    # the shape the RE4 map / mesh walker plugs into (re5_switch's): player pos/rot/hp/hp_max, enemies slot/ptr/pos/hp
    assert {"pos", "rot", "hp", "hp_max"} <= set(snap["player"])
    assert [e["slot"] for e in snap["enemies"]] == [0, 1]
    assert all({"slot", "ptr", "pos", "hp", "hp_max"} <= set(e) for e in snap["enemies"])
    assert {"timer", "kills", "combo", "combo_timer"} <= set(snap)
    assert m.re4_units.pool is not None and m.re4_units.scans == 1


def test_a_unit_whose_position_is_not_finite_is_dropped(mapped):
    heap = bytearray(0x10000)
    heap[0x0000:0x0600] = unit(0xAE0000, 1000, (float("nan"), 0.0, 0.0), 1)
    m = Mem({B + 0xB00000: bytes(0x77D000), 0x5D55000000: bytes(heap)})
    assert D.snapshot(m, now=0.0)["player"] is None


def test_unmapped_classes_read_no_units():
    m = Mem({B + 0xB00000: bytes(0x77D000)})
    assert D.PLAYER_CLASS is None and D.ENEMY_CLASSES == () and D.U_POS is None
    snap = D.snapshot(m, now=0.0)
    assert snap["player"] is None and snap["enemies"] == [] and m.re4_units.scans == 0
