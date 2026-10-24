"""Focused tests for gbox.mkmyth_inventory (MK Mythologies USA, N64 NMYE rev 0)."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct

import pytest

from gbox import mkmyth_inventory as mk

SOURCE = Path(os.environ.get(
    "GBOX_MKMYTH_SOURCE",
    Path.home() / "gbox-cache" / "6d46221997228c6a" / "source.zip"))


def _lui(rt: int, imm: int) -> int:
    return (0x0F << 26) | (rt << 16) | (imm & 0xFFFF)


def _addiu(rt: int, rs: int, imm: int) -> int:
    return (0x09 << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def test_decode_entry_stub_sign_extends_addiu():
    words = [_lui(8, 0x800B), _addiu(8, 8, 0x43C0),
             _lui(9, 0x0024), _addiu(9, 9, -0x7590),
             0, 0, 0, 0, 0, 0,
             _lui(10, 0x8000), _addiu(10, 10, 0x0450),
             _lui(29, 0x802F), 0x01400008, _addiu(29, 29, -0x7C40), 0]
    rom = bytes(0x1000) + struct.pack(">16I", *words)
    e = mk.decode_entry(rom)
    assert e["bss_start"] == 0x800B43C0
    assert e["bss_size"] == 0x238A70
    assert e["main"] == 0x80000450
    assert e["stack_top"] == 0x802E83C0
    assert e["resident_rom_end"] == 0xB4FC0


def test_segment_table_null_record_classes_and_gap():
    rom = bytearray(0x3000)
    struct.pack_into(">2I", rom, 0x1000, 8, 0x10)            # offset table, 2 entries
    struct.pack_into(">2I", rom, 0x1040, 0x1234, 0x80002047)  # packed blob
    tab = 0x2000
    struct.pack_into(">9I", rom, tab, 0x1000, 0x1020, 0, 0, 0, 0, 0x1040, 0x1080, 1)
    struct.pack_into(">3I", rom, tab + 36, 0x1020, 0x1040, 7)  # bad flag ends table
    recs = mk.segment_table(bytes(rom), off=tab, lo=0x1000)
    assert [r["null"] for r in recs] == [False, True, False]
    assert recs[0]["kind"] == "offset_table" and recs[0]["entries"] == 2
    assert recs[2]["kind"] == "packed" and recs[2]["signature"] == "80002000"
    assert recs[2]["flag"] == 1 and recs[2]["word0"] == 0x1234
    cov = mk.coverage(recs, 0x1000, 0x1080)
    assert cov["gaps"] == [(0x1020, 0x1040)] and cov["overlaps"] == []


def test_pointer_strings_stop_at_empty_string():
    rom = bytearray(0x2000)
    rom[0x1800:0x1806] = b"MONK1\0"
    rom[0x1808:0x1810] = b"SHINNOK\0"
    struct.pack_into(">3I", rom, 0x1000, mk.rom_to_ram(0x1800),
                     mk.rom_to_ram(0x1808), mk.rom_to_ram(0x1810))
    assert mk.pointer_strings(bytes(rom), 0x1000, resident_end=0x2000) == ["MONK1", "SHINNOK"]


def test_check_build_refuses_other_roms():
    src = {"z64_sha1": "0" * 40, "z64_md5": mk.KNOWN["z64_md5"],
           "z64_size": mk.KNOWN["z64_size"]}
    with pytest.raises(mk.WrongBuild):
        mk.check_build(src, {"game_code": "NMYE", "version": 0})
    good = {k: mk.KNOWN[k] for k in ("z64_sha1", "z64_md5", "z64_size")}
    with pytest.raises(mk.WrongBuild):
        mk.check_build(good, {"game_code": "NMYP", "version": 0})
    mk.check_build(good, {"game_code": "NMYE", "version": 0})


@pytest.mark.skipif(not SOURCE.is_file(), reason="owned MK Mythologies USA zip not cached")
def test_owned_build_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_N64_ROM_CACHE", str(tmp_path))
    m = mk.inventory(SOURCE)
    s = m["source"]
    assert s["sha256"] == "92bf2f4584c19490297bb902533fe57f8519663128845da654ecece9f8958b9a"
    assert s["byte_order"] == "v64" and s["member_size"] == 0x1000000
    assert s["z64_sha256"] == "9c18254abf6722b95aa782fcd310bd95f6bcf147da66beb77ce32ca90673ffc6"
    h = m["header"]
    assert (h["game_code"], h["version"], h["internal_name"]) == ("NMYE", 0, "MK_MYTHOLOGIES")
    assert h["entry_point"] == 0x80000400
    assert m["boot"] == {"cic": "6102", "ipl3_crc32": "90bb6cb5", "header_crc_matches": True}
    lay = m["layout"]
    assert lay["resident"]["rom_end"] == 0xB4FC0
    assert lay["resident"]["bss_size"] == 0x238A70
    st = lay["segment_table"]
    assert (st["records"], st["real"], st["null_indices"], st["flagged"]) == (144, 143, [118], 58)
    assert st["ram"] == 0x800A4560 and st["kinds"]["offset_table"] == 42
    cov = lay["coverage"]
    assert cov["overlaps"] == [] and cov["high"] == 0xEF6B60
    assert [(g["start"], g["end"], g["kind"]) for g in cov["gaps"]] == [
        (0x947C80, 0xD2DA50, "sn64_sound_bank")]
    assert lay["padding"] == [0xEF6B57, 0x1000000]
    names = [c["name"] for c in m["characters"]["debug_select"]]
    assert len(names) == 25
    assert (names[0], names[13], names[14], names[23], names[24]) == (
        "MONK1", "SCORPION", "UNDEAD SCORP", "QUANCHI", "SHINNOK")
    levels = [x["name"] for x in m["levels"]["debug_select"]]
    assert len(levels) == 11 and levels[0] == "TEMPLE" and levels[-1] == "TEST CHARACTERS"
    assert m["string_hints"]["No more palettes!"] == 0xADE28

# --- character / level resource tables --------------------------------------

CHARACTER_NAMES_EXPECTED = ['MONK1', 'MONK2', 'MONK3', 'MONK4', 'MONK5', 'MONK6', 'HULK MONK', 'FAST MONK', 'WINDGOD', 'WATERGOD', 'FIREGOD', 'GRUNT1', 'GRUNT2', 'SCORPION', 'UNDEAD SCORP', 'PRIS GRUNT1', 'PRIS GRUNT2', 'PRIS GRUNT3', 'PRIS GRUNT4', 'PRIS GRUNT5', 'ASSASSIN1', 'ASSASSIN2', 'ASSASSIN3', 'QUANCHI', 'SHINNOK']

OWNED_ROM_CANDIDATES = [
    Path.home() / "gbox-cache" / "6d46221997228c6a" / "rom.z64",
    Path.home() / "gBox_alt" / "gbox-cache" / "6d46221997228c6a" / "rom.z64",
]
Z64_SHA256 = "9c18254abf6722b95aa782fcd310bd95f6bcf147da66beb77ce32ca90673ffc6"


def _owned_rom() -> bytes:
    for p in OWNED_ROM_CANDIDATES:
        if p.is_file():
            return p.read_bytes()
    pytest.skip("owned MK Mythologies USA rom not cached")


def _synthetic_resource_rom() -> bytes:
    rom = bytearray(0x4000)
    rom[0x1000:0x1006] = b"MONK1\0"
    struct.pack_into(">I", rom, 0x1100, mk.rom_to_ram(0x1000))
    struct.pack_into(">I", rom, 0x1200, mk.rom_to_ram(0x2000))
    struct.pack_into(">I", rom, 0x1300, mk.rom_to_ram(0x2100))
    return bytes(rom)


def test_character_resources_reads_name_and_data_pointer():
    recs = mk.character_resources(_synthetic_resource_rom(),
                                  names_off=0x1100, ptrs_off=0x1200, count=1)
    assert recs[0]["name"] == "MONK1"
    assert recs[0]["data_ram"] == mk.rom_to_ram(0x2000)
    assert recs[0]["region"] == "resident"


def test_character_resources_marks_missing_data_pointer():
    recs = mk.character_resources(_synthetic_resource_rom(),
                                  names_off=0x1100, ptrs_off=0x1200, count=2)
    assert recs[1]["data_ram"] == 0 and recs[1]["region"] == "none"


def test_level_resources_reads_descriptor_records():
    rom = bytearray(_synthetic_resource_rom())
    struct.pack_into(">I", rom, 0x1108, mk.rom_to_ram(0x1000))
    rom = bytes(rom)
    recs = mk.level_resources(rom, names_off=0x1108, desc_off=0x1300, count=1, stride=28)
    assert recs[0]["name"] == "MONK1"
    assert recs[0]["ram"] == mk.rom_to_ram(0x2100)
    assert len(recs[0]["words"]) == 7


def test_owned_build_character_table_maps_debug_ids():
    rom = _owned_rom()
    assert len(rom) == 0x1000000
    assert hashlib.sha256(rom).hexdigest() == Z64_SHA256
    chars = mk.character_resources(rom)
    assert [c["name"] for c in chars] == CHARACTER_NAMES_EXPECTED
    assert chars[0]["data_ram"] == 0x802C1BAC
    assert chars[24]["name"] == "SHINNOK" and chars[24]["data_ram"] == 0
    assert all(c["region"] == "bss" for c in chars if c["data_ram"])


def test_owned_build_level_table_has_twelve_descriptor_records():
    rom = _owned_rom()
    levels = mk.level_resources(rom)
    assert len(levels) == 12
    assert levels[11]["name"] is None and levels[11]["name_ram"] == 0
    assert all(l["name"] for l in levels[:11])
    assert all(0x80000000 <= l["ram"] <= 0x80300000 for l in levels)
    assert len({l["ram"] for l in levels}) > 1


# --- analysis stage: packed-record header + segment families ----------------

def test_packed_header_decodes_unpacked_size_and_ram_dest():
    # synthetic packed record: header {unpacked_size, ram_dest}, then payload
    rom = bytearray(0x40)
    struct.pack_into(">II", rom, 0x10, 0x8000, 0x80002040)   # 8-byte header
    rom[0x18:0x28] = b"\x00" * 16                              # 16-byte payload
    rec = {"start": 0x10, "end": 0x28, "size": 0x18}
    h = mk.packed_header(bytes(rom), rec)
    assert h["unpacked_size"] == 0x8000 and h["ram_dest"] == 0x80002040
    assert h["packed_size"] == 16 and h["ratio"] == round(16 / 0x8000, 3)
    assert h["plausible"] is True


def test_packed_header_rejects_implausible_header():
    rom = bytearray(0x18)
    struct.pack_into(">II", rom, 0x10, 4, 0x11223344)   # unpacked < payload, KUSEG dest
    rec = {"start": 0x10, "end": 0x18, "size": 8}
    h = mk.packed_header(bytes(rom), rec)
    assert h["plausible"] is False


def test_palette_pool_detects_ci_sprite_tluts():
    rom = bytearray(0x40)
    # a few TLUT entries, then the 0x80808000 marker word, then more entries
    entries = [0x0000, 0x7C1F, 0x8080, 0x0000, 0x8080, 0x0000, 0x8080, 0x0000,
               0x7C1F, 0x03E0]
    struct.pack_into(">10H", rom, 0x10, *entries)
    rec = {"start": 0x10, "end": 0x24, "size": 0x14}
    p = mk.palette_pool(bytes(rom), rec)
    assert p["marker_words"] == 3 and p["is_palette_pool"] is False  # needs >=4
    assert p["palette_entries"] == 10 and p["bytes"] == 20


def test_owned_build_analysis_probe():
    rom = _owned_rom()
    fam = mk.segment_families(rom)
    # 143 real records must partition exactly into the four families
    assert sum(len(v) for v in fam.values()) == 143
    assert len(fam["compressed"]) == 58
    probe = mk.analysis_probe(rom)
    assert probe["real_records"] == 143
    assert probe["families"]["compressed"] == 58
    ch = probe["compressed_header"]
    assert ch["count"] == 58
    # 56/58 records carry the {unpacked_size, KSEG0 dest} header; the two
    # exceptions (idx 42, 81) have an 8-byte header with a tiny first word that
    # is NOT an unpacked size (their dest sits at the same offset 0x80000440),
    # i.e. a different record flavour the loader dispatches on.
    assert ch["plausible"] == 56
    # every plausible header claims a KSEG0 destination
    assert all(d >> 24 == 0x80 for d in ch["unique_dests"])
    assert len(ch["unique_dests"]) >= 1
    # the offset-table banks (42 by segment-table kind) are the loader/code
    # relocation tables; segment_families re-classifies them into 40 code_reloc
    # + 2 that landed in palette_pool because their first word is a palette marker
    assert len(fam["code_reloc"]) == 40
    assert len(fam["palette_pool"]) == 14


def test_owned_build_packed_headers_are_consistent():
    rom = _owned_rom()
    recs = [r for r in mk.segment_table(rom, lo=0xB4FC0) if not r["null"] and r["flag"] == 1]
    assert len(recs) == 58
    special = {42, 81}
    for rec in recs:
        h = mk.packed_header(rom, rec)
        if rec["index"] in special:
            # 8-byte-payload "stub" records whose first word is not a size
            assert h["unpacked_size"] == 4 and h["packed_size"] == 8
            continue
        assert h["plausible"], (rec["index"], h)
        # unpacked_size is byte-granular (real sprite/image buffers), so we only
        # assert it is sane, not 4-aligned
        assert h["unpacked_size"] > h["packed_size"]
