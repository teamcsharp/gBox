"""Tests for gbox.ssb64_analysis: EUR<->US file ID map, the fixed VPK0
decoder (content-level), LBRelocDesc chain resolution, and the Mario
probe (one animation script + the FTAttributes model header).

ROM-backed tests need the normalized EUR .z64 ROM and skip otherwise:

    GBOX_SSB64_EUR_ROM=~/gbox-cache/34af4e9323891bd2/rom_norm.z64 pytest
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from gbox import ssb64_analysis as a
from gbox import ssb64_inventory as inv

ROM_ENV = "GBOX_SSB64_EUR_ROM"
ROM_PATH = Path(os.environ[ROM_ENV]) if os.environ.get(ROM_ENV) else None

needs_rom = pytest.mark.skipif(ROM_PATH is None, reason=f"{ROM_ENV} not set")


# ---- no-ROM tests ------------------------------------------------------

def test_eur_us_id_map():
    assert inv.eur_to_us(215) == 202       # MarioMainMotion
    assert inv.eur_to_us(216) == 203       # MarioMain
    assert inv.eur_to_us(263) == 250       # BossMain (shift +13 through 250)
    assert inv.eur_to_us(272) == 255       # shift +17 above US 250
    assert inv.eur_to_us(5) is None        # EUR-only insert span 0..12
    assert inv.eur_to_us(269) is None      # EUR-only insert span 268..271
    assert inv.us_to_eur(202) == 215
    assert inv.us_to_eur(296) == 313       # MarioModel
    assert inv.FIGHTERS["mario"] == (215, 217)
    assert inv.FIGHTERS["boss"] == (262, 263)


def test_ft_attributes_layout_sums_to_file():
    offs = a.ft_attributes_field_offsets()
    total = sum(size for _name, size in a.FTATTRIBUTES_FIELDS)
    assert total == 0x348                      # == 1904 - 0x428
    assert offs["skeleton"] + 4 == total


def test_motion_events_opcode_table():
    assert a.MOTION_EVENTS[0] == "End"
    assert a.MOTION_EVENTS[35] == "Return"
    assert a.MOTION_EVENTS[36] == "Goto"
    assert a.MOTION_EVENTS[43] == "SetTexturePartID"
    assert a.MOTION_EVENTS[47] == "SetSlopeContour"
    assert len(a.MOTION_EVENTS) == 52


class BitWriter:
    def __init__(self):
        self.bits = []

    def write(self, value, count):
        for i in range(count - 1, -1, -1):
            self.bits.append((value >> i) & 1)

    def bytes(self):
        out = bytearray((len(self.bits) + 7) // 8)
        for i, bit in enumerate(self.bits):
            out[i >> 3] |= bit << (7 - (i & 7))
        return bytes(out)


def method1_stream(size, off_leaf_bits, len_leaf_bits, chunks):
    """Build a sample-method-1 VPK0 stream with single-leaf trees."""
    w = BitWriter()
    w.write(0x76706B30, 32)
    w.write(size, 32)
    w.write(1, 8)  # sample method 1
    for leaf_bits in (off_leaf_bits, len_leaf_bits):
        w.write(0, 1)
        w.write(leaf_bits, 8)
        w.write(1, 1)  # node with <2 stack entries ends the tree
    for value, count in chunks:
        w.write(value, count)
    return w.bytes()


def test_vpk0_method1_far_backref_distance_4x_minus_8():
    # dma.c: when the first sample is > 2 the copy distance is
    # value * 4 - 8 (copy_src = out_ptr - value*4 + 8).  Distance 12
    # needs first sample 5; this pinned the decoder bug where the port
    # used `value` directly instead of `value * 4 - 8`.
    literal = b"0123456789AB"
    chunks = []
    for byte in literal:
        chunks += [(0, 1), (byte, 8)]
    chunks += [(1, 1), (5, 3), (3, 2)]  # backref: first sample 5, length 3
    stream = method1_stream(len(literal) + 3, 3, 2, chunks)
    assert inv.vpk0_decode(stream, len(literal) + 3) == literal + b"012"


def test_walk_chain_stops_at_ffff():
    buf = bytearray(16)
    buf[0:4] = bytes.fromhex("00010009")  # slot 0: next=1, words=9
    buf[4:8] = bytes.fromhex("ffff0000")  # slot 1: end
    assert a.walk_chain(bytes(buf), 0) == [(0, 1, 9), (1, 0xFFFF, 0)]


def test_walk_chain_rejects_loop():
    buf = bytearray(8)
    buf[0:4] = bytes.fromhex("00020000")
    buf[4:8] = bytes.fromhex("00000000")  # slot 2 -> back to 0
    with pytest.raises(ValueError):
        a.walk_chain(bytes(buf), 0)


def test_decode_motion_script_commands():
    # SetTexturePartID(2), Wait(2), Return, then a Goto with a pointer slot.
    buf = bytes.fromhex(
        "ac000002"      # SetTexturePartID(2)
        "04000002"      # Wait(2)
        "8c000000"      # Return
        "90000000"      # Goto (opcode 36)
        "00030009")     # slot: next=3, words=9 -> target 0x24
    ops = a.decode_motion_script(buf)
    assert ops[0]["name"] == "SetTexturePartID"
    assert ops[0]["param"] == 2
    assert ops[1]["name"] == "SyncWait"
    assert ops[2]["name"] == "Return"
    assert ops[3]["name"] == "Goto"
    assert ops[4]["slot_words"] == 9
    assert ops[4]["slot_target_off"] == 0x24


# ---- ROM-backed tests --------------------------------------------------

@needs_rom
def test_mario_motion_script_head():
    probe = a.probe_mario(ROM_PATH)
    ops = probe["motion_script_head"]
    assert ops[0] == {"offset": 0, "word": 0xAC000002, "opcode": 43,
                      "name": "SetTexturePartID", "param": 2}
    assert ops[1]["word"] == 0x04000002          # Wait(2)
    assert ops[4]["word"] == 0xAC000002          # SetTexturePartID(2)
    assert ops[6]["word"] == 0xAC000000          # SetTexturePartID(0)
    assert ops[8]["name"] == "Return"
    assert ops[9]["word"] == 0xBC000003          # SetSlopeContour(3)
    assert ops[11]["slot_target_off"] == 0       # Subroutine -> script 0


@needs_rom
def test_mario_main_pre_data_anchors():
    probe = a.probe_mario(ROM_PATH)
    pre = probe["main_pre_data"]
    assert pre["animlock"] == (0x10425200, 0)
    assert pre["setup_parts"] == (0xFFFFFF00, 0)
    assert pre["hiddenparts_0"] == (2, 0, 1, 3)
    # first file handle -> MarioMainMotion's Wait_0x0024 (file 215, +0x24)
    assert pre["file_handles_slots"][0][1] == 9   # 9 words == 0x24 bytes


@needs_rom
def test_mario_ft_attributes_struct_values():
    probe = a.probe_mario(ROM_PATH)
    attrs = probe["main_attrs"]
    assert attrs["struct_offset"] == 0x428
    assert attrs["size"] == pytest.approx(1.12)
    assert attrs["walkslow_anim_length"] == 90.0
    assert attrs["run_speed"] == 44.0
    assert attrs["jumps_max"] == 2
    assert attrs["weight"] == 1.0
    assert attrs["joint_rfoot_id"] == 23
    assert attrs["joint_lfoot_id"] == 18
    assert attrs["joint_itemheavy_id"] == 28
    assert attrs["joint_itemlight_id"] == 17


@needs_rom
def test_mario_intern_chain_targets():
    probe = a.probe_mario(ROM_PATH)
    words = [words for _slot, _next, words in probe["main_intern_slots"]]
    # Modelpart container entries -> pre-data desc tables, then the
    # FTAttributes pointer fields, in chain order (src/relocData/203):
    assert words == [23, 43, 205, 213, 5, 3, 7, 89, 63, 88, 97, 210, 263]
    attrs = probe["main_attrs"]
    assert attrs["setup_parts_slot"] & 0xFFFF == 5       # -> pre-data 0x14
    assert attrs["animlock_slot"] & 0xFFFF == 3          # -> pre-data 0x0C
    assert attrs["hiddenparts_slot"] & 0xFFFF == 7       # -> pre-data 0x1C
    assert attrs["commonparts_container_slot"] & 0xFFFF == 89
    assert attrs["modelparts_container_slot"] & 0xFFFF == 63
    assert attrs["textureparts_container_slot"] & 0xFFFF == 88
    assert attrs["thrown_status_slot"] & 0xFFFF == 97
    assert attrs["sprites_slot"] & 0xFFFF == 210
    assert attrs["skeleton_slot"] & 0xFFFF == 263


@needs_rom
def test_mario_extern_chain_and_jointtree():
    probe = a.probe_mario(ROM_PATH)
    ids = probe["main_extern_file_ids"]
    assert ids[:3] == [215, 373, 217]   # MainMotion, Special2, Special1
    assert all(fid == 313 for fid in ids[3:12])   # modelparts -> MarioModel
    assert probe["dobj_jointtree_file"] == 313
    assert probe["dobj_jointtree_offset"] == 0x2200


@needs_rom
def test_vpk0_content_regression_on_rom():
    # The decoder fix is content-visible: EUR file 215 must decode to the
    # known script bytes (the pre-fix decoder produced garbage here).
    rom = ROM_PATH.read_bytes()
    entry = a.read_table_entry(rom, 215)
    data = a.load_file(rom, entry)
    assert len(data) == 6560
    assert data[:4] == bytes.fromhex("ac000002")
    assert data[0x24:0x28] == bytes.fromhex("bc000003")


@needs_rom
def test_fighter_roster_files_decode():
    rom = ROM_PATH.read_bytes()
    entry = a.read_table_entry(rom, inv.us_to_eur(202))
    assert a.load_file(rom, entry)[:4] == bytes.fromhex("ac000002")
    # every roster fighter's three files decode without error
    for name in inv.ROSTER:
        lo, hi = inv.FIGHTERS[name]
        for fid in range(lo, hi + 1):
            data = a.load_file(rom, a.read_table_entry(rom, fid))
            assert len(data) > 0


def test_eur_us_map_round_trips():
    for us in range(0, 400):
        assert inv.eur_to_us(inv.us_to_eur(us)) == us
    for eur in range(0, 400):
        us = inv.eur_to_us(eur)
        assert us is None or inv.us_to_eur(us) == eur


def test_truncated_inputs_raise_valueerror():
    with pytest.raises(ValueError):
        a.decode_motion_script(bytes.fromhex("90000000"))   # Goto without its slot
    with pytest.raises(ValueError):
        a.parse_ft_attributes_pre_data(bytes(0x20))
    with pytest.raises(ValueError):
        a.parse_ft_attributes(bytes(0x500))
    with pytest.raises(ValueError):
        a.walk_chain(bytes(3), 0)
