"""RE4 Switch (HD port) packs through the same readers the GameCube disc uses.

Measured 2026-11-07: bio4/em/*.udas is the SAME UDAS container as the GC/Wii em/*.drs - 0xCAB6BE20 fill, 32-byte
entries (type, size, 0, offset), 0xFFFFFFFF terminator inside the first 0x400 bytes, then a DAT pack with the same
count/tail/offset-table/4-char-extension layout - written LITTLE-endian instead of big-endian. These tests pin that
one reader serves both editions, that the GC path is unchanged, and that an HD pack is inventoried by slot without
its payload being guessed at (the HD BIN header is 0x98, not the GC 0x40/0x60).
"""
import struct

import pytest

from gbox import re4gc_inventory as I


def le_pack(*, n_slots=2, ext=b"BIN\0TPL\0", bin_header=0x98, tpl_magic=0x12345678):
    """A minimal little-endian RE4-Switch UDAS pack: fill, one DAT entry, terminator, a DAT with two slots."""
    blobs = [struct.pack("<I", bin_header) + b"\0" * 12, struct.pack("<I", tpl_magic) + b"\0" * 8]
    base = 16 + 4 * n_slots + 4 * n_slots          # count+tail+pad, the offset table, the extension table
    offs, cursor = [], base
    for b in blobs:
        offs.append(cursor)
        cursor += len(b)
    dat = bytearray()
    dat += struct.pack("<II", n_slots, 0) + b"\0" * 8
    dat += struct.pack(f"<{n_slots}I", *offs)
    dat += ext
    for b in blobs:
        dat += b
    hdr = bytearray(b"\xca\xb6\xbe\x20" * 8)
    hdr += struct.pack("<IIII", 0, len(dat), 0, 0x400) + b"\0" * 16
    hdr += struct.pack("<I", 0xFFFFFFFF)
    hdr += b"\0" * (0x400 - len(hdr))
    return bytes(hdr) + bytes(dat)


def be_pack():
    """The same shape big-endian (the GameCube/Wii layout) so the untouched path keeps being covered."""
    blobs = [struct.pack(">I", 0x40) + b"\0" * 12]
    base = 16 + 4 * 1 + 4 * 1
    dat = bytearray()
    dat += struct.pack(">II", 1, 0) + b"\0" * 8
    dat += struct.pack(">1I", base)
    dat += b"BIN\0"
    dat += blobs[0]
    hdr = bytearray(b"\xca\xb6\xbe\x20" * 8)
    hdr += struct.pack(">IIII", 0, len(dat), 0, 0x400) + b"\0" * 16
    hdr += struct.pack(">I", 0xFFFFFFFF)
    hdr += b"\0" * (0x400 - len(hdr))
    return bytes(hdr) + bytes(dat)


def test_the_same_container_parses_little_endian():
    ents = I.udas_entries(le_pack(), "<")
    assert len(ents) == 1 and ents[0]["type"] == 0 and ents[0]["offset"] == 0x400
    assert ents[0]["size"] > 0


def test_the_endianness_actually_matters():
    # the same bytes read as big-endian must NOT silently produce a plausible table
    with pytest.raises(ValueError):
        I.udas_entries(le_pack(), ">")


def test_the_gamecube_path_is_unchanged():
    ents = I.udas_entries(be_pack())
    assert len(ents) == 1 and ents[0]["type"] == 0


def test_an_hd_pack_is_inventoried_without_guessing_its_payload():
    s = I.pack_summary(le_pack(), endian="<")
    assert s["edition"] == "hd"
    assert s["slots"] == {"BIN": 1, "TPL": 1}
    assert s["errors"] == []
    # listed and sized, never decoded as if it were the GC layout
    assert s["meshes"][0]["decoded"] is False and s["meshes"][0]["header"] == "0x98"
    assert s["textures"][0]["decoded"] is False and s["textures"][0]["magic"] == "0x12345678"


def test_motion_slots_are_counted_for_the_hd_port_too():
    blob = le_pack(ext=b"FCV\0SEQ\0")
    s = I.pack_summary(blob, endian="<")
    assert s["slots"].get("FCV") == 1 and s["slots"].get("SEQ") == 1


def test_a_switch_tree_is_walked_and_a_plain_directory_is_refused(tmp_path):
    em = tmp_path / "bio4" / "em"
    em.mkdir(parents=True)
    (em / "em10.udas").write_bytes(le_pack())
    (em / "pl00.udas").write_bytes(le_pack())
    inv = I.switch_inventory(tmp_path)
    assert inv["title_id"] == I.SWITCH_TITLE
    assert inv["pack_count"] == 2
    assert {r["file"] for r in inv["packs"]} == {"em/em10.udas", "em/pl00.udas"}
    kinds = {r["file"]: r["kind"] for r in inv["packs"]}
    assert kinds == {"em/em10.udas": "enemy/NPC", "em/pl00.udas": "player/partner"}
    assert inv["totals"]["packs"] == 2 and inv["totals"]["errors"] == 0
    with pytest.raises(ValueError, match="not an RE4 Switch RomFS tree"):
        I.switch_inventory(tmp_path / "elsewhere")
