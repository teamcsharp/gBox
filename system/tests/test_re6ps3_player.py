"""RE6 PS3 player-struct locator/decoder (request 3367): RAM-fixture tests, no emulator."""
import struct

from gbox import re6ps3_player as rp


class Mem:
    """Sparse big-endian guest memory, same contract as the Xbox RE6 tests."""

    def __init__(self):
        self.b = {}

    def put(self, a, fmt, *v):
        self.b[a] = struct.pack(fmt, *v)

    def rd(self, a, n):
        buf = bytearray(n)
        for base, d in self.b.items():
            lo, hi = max(a, base), min(a + n, base + len(d))
            if lo < hi:
                buf[lo - a:hi - a] = d[lo - base:hi - base]
        return bytes(buf)


def world(splayer=0x30010000, up=0x31020000, hp=900, hp_max=1000,
          pos=(1.0, 2.0, 3.0), slot=2):
    m = Mem()
    m.put(splayer + rp.OFF_PLAYER_PTR, ">I", up)  # sPlayer + 0x28 holds uPlayer
    m.put(up + rp.OFF_POS, ">3f", *pos)
    m.put(up + rp.OFF_HP, ">hh", hp, hp_max)
    m.put(up + rp.OFF_SLOT, ">I", slot)
    return m


def test_decode_official_layout():
    m = world()
    p = rp.read_player(m, 0x31020000)
    assert p["pos"] == [1.0, 2.0, 3.0]
    assert (p["hp"], p["hp_max"], p["weapon_slot"]) == (900, 1000, 2)
    assert p["pending_fields"] == ["facing", "aim_pitch", "action_state", "ammo"]


def test_locate_splayer_finds_the_chain():
    m = world()
    hits = rp.locate_splayer(m, scan_range=(0x30000000, 0x30100000), stride=0x100)
    assert (0x30010000, 0x31020000) in hits


def test_locate_splayer_rejects_bad_life():
    m = world(hp=5000, hp_max=900)               # hp > hp_max and over ceiling
    assert rp.locate_splayer(m, scan_range=(0x30000000, 0x30100000), stride=0x100) == []


def test_predicate_rejects_garbage_floats():
    m = world(pos=(1e9, 0.0, 0.0))
    assert not rp._looks_like_uplayer(m, 0x31020000)


def test_offsets_cite_the_verified_xbox_map():
    # docs/re6-ram-map-0871eee3b68cdea3.json (request 3023): +0x28 / +0x50 / +0xF20 / +0x3EE8
    assert (rp.OFF_PLAYER_PTR, rp.OFF_POS, rp.OFF_HP, rp.OFF_SLOT) == (0x28, 0x50, 0xF20, 0x3EE8)
    assert rp.EBOOT_SHA256.startswith("161788e7")
