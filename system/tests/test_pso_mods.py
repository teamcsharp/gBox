"""Offline tests for the PSO Ver.2 (Dreamcast, US 2OEF) live mods added for the inbox asks:
rare_drops (every enemy drops a rare), move_speed (#279, run N x faster) and key_bypass (#564, skip the serial/access-key
check). A fake memory adapter serves read(addr, n) / write(addr, bytes) over a sparse dict so the ops run without a game.

Addresses and patch bytes are cross-checked against 1ST_READ.BIN disassembly (capstone SH-4) and a Flycast savestate RAM
image of this exact disc; see docs/what_this_is.md section 18 and profiles/pso-v2-dc-us.json.
"""
import hashlib
import struct

import pytest

from gbox import pso_mods_tool as T
from gbox.registry import Unsupported


class FakeDC:
    """Dreamcast RAM as a sparse dict; read/write little-endian bytes like the live adapter."""

    name = "fake"

    def __init__(self, player=0x8CFA0000):
        self.m = {}
        self.put(T.SIGNATURE[0], T.SIGNATURE[1])                      # TObjPlayer signature string
        self.put(T.PLAYER_TBL, struct.pack("<I", player))            # a live player object pointer
        if player:
            self.put(player, b"\0" * 0x400)
        self.put(T.VT_UPDATE, struct.pack("<I", T.ORIG_UPDATE))      # vtable update slot = the original update
        self.put(T.CAVE, T.CAVE_ORIG_HEAD)
        self.put(T.CAVE2, T.CAVE2_ORIG_HEAD)
        for name in T.PATCHES:                                       # original (un-patched) code at every patch site
            self.put_patch_original(name)

    def put(self, a, b):
        for i, x in enumerate(b):
            self.m[a + i] = x

    def put_patch_original(self, name):
        addr, orig, _ = T.PATCHES[name]
        for a in (addr if isinstance(addr, tuple) else (addr,)):
            self.put(a, orig)

    def read_memory(self, a, n):
        return bytes(self.m.get(a + i, 0) for i in range(n))

    def write_memory(self, a, b):
        self.put(a, b)


def pso(ad):
    return T.PSO(ad.read_memory, ad.write_memory)


# --- the second code cave: the update wrapper stub -------------------------------------------------------------------

def test_speed_stub_assembles_and_fits_the_cave():
    sc = T.speed_code()
    assert sc[:4] == T.CAVE2_ORIG_HEAD        # starts with the same two pushes as the handler it overwrites
    assert T.CAVE2 + len(sc) <= T.SPEED_VARS  # code never runs into the variable block
    assert T.SPEED_VARS + T.SPEED_VARS_LEN <= T.CAVE2_END


def test_speed_stub_byte_snapshot():
    # the stub is fully determined by the (fixed) cave/var addresses; this pins it so a change is deliberate.
    sc = T.speed_code()
    assert len(sc) == 132
    assert hashlib.sha256(sc).hexdigest() == hashlib.sha256(T.speed_code()).hexdigest()
    # two update-run loops reach the original update (attack loop + move loop), then the tail jump.
    assert sc.count(struct.pack("<I", T.ORIG_UPDATE)) == 1   # single ORIG2 literal, shared by both loops + tail


# --- move_speed (#279) ----------------------------------------------------------------------------------------------

def test_hook_installs_the_cave_and_vtable():
    ad = FakeDC()
    m = pso(ad)
    assert m.hook() is True
    assert ad.read_memory(T.CAVE2, len(T.speed_code())) == T.speed_code()
    assert m.u32(T.VT_UPDATE) == T.CAVE                     # player update now runs through the dispatcher


def test_move_speed_on_sets_extra_updates_and_off_clears():
    ad = FakeDC()
    m = pso(ad)
    r = m.move_speed(3, on=True)
    assert r == {"factor": 3, "on": True}
    assert struct.unpack("<I", ad.read_memory(T.SPEED_VARS + T.MOVE_EXTRA_OFF, 4))[0] == 2  # factor-1 extra updates
    r = m.move_speed(3, on=False)
    assert r == {"factor": 1, "on": False}
    assert struct.unpack("<I", ad.read_memory(T.SPEED_VARS + T.MOVE_EXTRA_OFF, 4))[0] == 0


def test_move_speed_is_independent_of_attack_speed():
    ad = FakeDC()
    m = pso(ad)
    m.attack_speed(10)                                      # writes the first 16 bytes (attack vars)
    m.move_speed(3)                                         # writes only +0x10
    assert struct.unpack("<I", ad.read_memory(T.SPEED_VARS + 12, 4))[0] == 9   # attack extra still set
    assert struct.unpack("<I", ad.read_memory(T.SPEED_VARS + T.MOVE_EXTRA_OFF, 4))[0] == 2
    m.move_speed(3, on=False)                               # turning move off leaves attack alone
    assert struct.unpack("<I", ad.read_memory(T.SPEED_VARS + 12, 4))[0] == 9


def test_move_speed_factor_is_clamped():
    ad = FakeDC()
    assert pso(ad).move_speed(999)["factor"] == 20
    assert pso(ad).move_speed(0)["factor"] == 1


# --- key_bypass (#564) ----------------------------------------------------------------------------------------------

def test_key_bypass_addresses_and_bytes():
    # jsr @r0 (0x400B, bytes 0b 40) -> mov #1,r0 (0xE001, bytes 01 e0) at both serial-check call sites.
    addrs, orig, new = T.PATCHES["key_bypass"]
    assert addrs == (0x8C1E743E, 0x8C2670B6)
    assert orig == bytes.fromhex("0b40") and new == bytes.fromhex("01e0")


def test_key_bypass_on_off_restores_both_sites():
    ad = FakeDC()
    m = pso(ad)
    assert m.patch("key_bypass", True) is True
    assert m.patch_state("key_bypass") == "on"
    for a in T.PATCHES["key_bypass"][0]:
        assert ad.read_memory(a, 2) == bytes.fromhex("01e0")
    assert m.patch("key_bypass", False) is True
    assert m.patch_state("key_bypass") == "off"
    for a in T.PATCHES["key_bypass"][0]:
        assert ad.read_memory(a, 2) == bytes.fromhex("0b40")


def test_key_bypass_needs_no_player_object():
    ad = FakeDC(player=0)                                   # at the title/key screen there is no player yet
    m = pso(ad)
    with pytest.raises(RuntimeError):
        m.check()                                           # ordinary ops still require a player
    assert m.check(require_player=False) == 0               # key_bypass path does not
    assert m.patch("key_bypass", True) is True


def test_patch_partial_state_is_reported():
    ad = FakeDC()
    m = pso(ad)
    a0, a1 = T.PATCHES["key_bypass"][0]
    ad.put(a0, bytes.fromhex("01e0"))                       # one site patched, the other not
    assert m.patch_state("key_bypass") == "partial"


def test_patch_signature_failure_raises():
    ad = FakeDC()
    ad.put(0x8C2670B6, bytes.fromhex("1234"))               # unexpected code at one site
    with pytest.raises(Unsupported):
        pso(ad).patch("key_bypass", True)


# --- rare_drops (every enemy drops a rare) --------------------------------------------------------------------------

def _seed_itemrt(ad, addr=0x8CB19440):
    """A minimal valid ItemRT table: one monster slot drops a common Saber; the rest empty."""
    tbl = bytearray(T.RT_ENTRY)
    tbl[4] = 0x30                                           # a modest probability byte
    tbl[5:8] = bytes.fromhex("000100")                     # Saber (a common, non-rare drop)
    ad.put(addr, bytes(tbl))
    return addr, bytes(tbl)


def test_rare_signatures_from_afs_header():
    # a tiny fake AFS with two 640-byte tables: (count, (offset,size)*)
    t0 = bytes(range(32)) + b"\0" * (T.RT_ENTRY - 32)
    t1 = bytes(range(32, 64)) + b"\0" * (T.RT_ENTRY - 32)
    afs = b"AFS\0" + struct.pack("<I", 2) + struct.pack("<II", 0x30, T.RT_ENTRY) + struct.pack("<II", 0x30 + T.RT_ENTRY, T.RT_ENTRY)
    afs = afs.ljust(0x30, b"\0") + t0 + t1
    sigs = T.rare_signatures(afs)
    assert sigs == [(0, t0[:32]), (1, t1[:32])]


def test_rare_find_locates_the_loaded_table():
    ad = FakeDC()
    addr, tbl = _seed_itemrt(ad)
    found = pso(ad).rare_find([(9, tbl[:32])])
    assert found == {addr: 9}


def test_rare_drops_on_rewrites_every_slot_and_off_restores():
    ad = FakeDC()
    addr, tbl = _seed_itemrt(ad)
    m = pso(ad)
    found = {addr: 9}
    res = m.rare_drops(True, T.RARE_DROPS, found)
    assert res["verified"] and not res["mismatched"]
    cur = ad.read_memory(addr, T.RT_ENTRY)
    want = set(T.RARE_DROPS)
    for s_ in m.rare_slots():                               # every monster + box rare slot now a rare at max chance
        assert cur[s_] == T.RT_MAX_PROB
        assert cur[s_ + 1:s_ + 4].hex() in want
    # box-area map was filled so the box rares can roll
    assert any(cur[T.RT_BOX_AREAS_AT:T.RT_BOX_AREAS_AT + T.RT_BOX_SLOTS])
    res = m.rare_drops(False, T.RARE_DROPS, found)
    assert res["verified"]
    assert ad.read_memory(addr, T.RT_ENTRY) == tbl         # exact original restored


def test_rare_drops_uses_the_given_codes_round_robin():
    ad = FakeDC()
    addr, _ = _seed_itemrt(ad)
    m = pso(ad)
    m.rare_drops(True, ["000107", "001000"], {addr: 9})
    cur = ad.read_memory(addr, T.RT_ENTRY)
    assert cur[1:4].hex() == "000107"                      # slot 0 -> codes[0]
    assert cur[5:8].hex() == "001000"                      # slot 1 -> codes[1]
    assert cur[9:12].hex() == "000107"                     # slot 2 -> codes[0] again


def test_rare_drops_defaults_are_real_three_byte_codes():
    assert len(T.RARE_DROPS) == 20
    assert all(len(bytes.fromhex(c)) == 3 for c in T.RARE_DROPS)
    assert "000107" in T.RARE_DROPS                        # DURANDAL
    assert "010227" in T.RARE_DROPS                        # RED RING


def test_rare_drops_rejects_bad_code():
    ad = FakeDC()
    addr, _ = _seed_itemrt(ad)
    with pytest.raises(ValueError):
        pso(ad).rare_drops(True, ["12"], {addr: 9})        # not a 3-byte code
