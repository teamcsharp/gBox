"""Tests for gbox.sf64_inventory against the owned Star Fox 64 (USA) Rev A ROM.

The ROM image is a build artifact kept outside the repo; tests skip unless it
exists (set SF64_ROM to override the default cache path).
"""

import hashlib
import json
import os
import struct

import pytest

from gbox import sf64_inventory as sf

ROM_PATH = os.environ.get("SF64_ROM") or os.path.expanduser(
    "~/gbox-cache/59a2755566b669ed/rom.z64")


def _rom():
    return sf.load_rom(ROM_PATH)


needs_rom = pytest.mark.skipif(
    not os.path.exists(ROM_PATH), reason="owned ROM not cached")


@needs_rom
def test_owned_build_identity():
    ident = sf.rom_identity(_rom())
    assert ident["size"] == 0xC00000
    assert ident["md5"] == sf.REV_A_IDENTITY["md5"]
    assert ident["sha1"] == sf.REV_A_IDENTITY["sha1"]
    assert ident["sha256"] == sf.REV_A_IDENTITY["sha256"]
    assert ident["name"] == "STARFOX64"
    assert ident["build"] == "US Rev A (1.1)"


@needs_rom
def test_load_rom_normalizes_v64():
    # the owned .n64 member is v64; loading it must give the same z64 bytes
    v64_path = os.path.expanduser(
        "~/gbox-cache/59a2755566b669ed/src7z/Star Fox 64 (USA).n64")
    if os.path.exists(v64_path):
        assert sf.load_rom(v64_path) == _rom()


@needs_rom
def test_file_table_location_and_entries():
    rom = _rom()
    ft = sf.find_file_table(rom)
    assert ft == sf.FILE_TABLE_US11
    entries = sf.parse_file_table(rom, ft)
    assert len(entries) == 64
    assert entries[0][0] == 0  # makerom
    # packed ranges are inside the 12 MiB retail image and non-decreasing
    prev = 0
    for v_begin, p_begin, p_end, flag in entries:
        assert 0 <= p_begin < p_end <= len(rom)
        assert p_begin >= prev
        assert flag in (0, 1)
        prev = p_begin
    # v offsets match the splat segment map for this build
    by_name = {sf.FILE_NAMES_US[i]: e for i, e in enumerate(entries)}
    assert by_name["ast_common"][0] == 0x873CB0
    assert by_name["ast_arwing"][0] == 0x8BFC00
    assert by_name["ast_map"][0] == 0xC48F40
    assert by_name["ovl_unused"][0] == 0xEFFA40
    # the uncompressed files are exactly comptool's decomp_inds minus 0..5
    raw = {i for i, e in enumerate(entries) if e[3] == 0}
    assert raw == sf.UNCOMPRESSED_RAW | {0, 1, 2, 3, 4, 5}


@needs_rom
def test_mio0_decode_all_files():
    rom = _rom()
    ft = sf.find_file_table(rom)
    entries = sf.parse_file_table(rom, ft)
    decoded = 0
    for i, entry in enumerate(entries):
        data = sf.decode_file(rom, entry)
        if entry[3] == 1:
            decoded += 1
            dest_size = struct.unpack(">I", rom[entry[1] + 4:entry[1] + 8])[0]
            assert len(data) == dest_size
    assert decoded == 51
    # spot check the ast_common size we measured
    by_name = {sf.FILE_NAMES_US[i]: e for i, e in enumerate(entries)}
    common = sf.decode_file(rom, by_name["ast_common"])
    assert len(common) == 0x32C10


def test_mio0_synthetic_blob():
    # "AAAAB": raw 'A', backref (len 3, dist 1) -> 'AAA', raw 'B'
    blob = (b"MIO0" + struct.pack(">III", 5, 20, 22)
            + b"\xa0" + b"\x00" * 3 + b"\x00\x00" + b"AB")
    assert sf.mio0_decompress(blob) == b"AAAAB"


def test_mio0_rejects_bad_header():
    with pytest.raises(ValueError):
        sf.mio0_decompress(b"NOTMIO0" + b"\x00" * 16)


@needs_rom
def test_rebuild_uncompressed_matches_decomp_reference():
    out = sf.rebuild_uncompressed(_rom())
    assert hashlib.md5(out).hexdigest() == sf.UNCOMPRESSED_MD5


@needs_rom
def test_inventory_manifest():
    manifest = sf.inventory(ROM_PATH, archive_sha256="b7726c67db890eb2ae87de78de512629480c80af965699c4c9bab63b19d80389")
    assert manifest["container"]["file_count"] == 64
    assert manifest["container"]["mio0_compressed_files"] == 51
    assert manifest["container"]["uncompressed_md5_verified"] is True
    names = [f["name"] for f in manifest["files"]]
    for name in sf.FILE_NAMES_US:
        assert name in names
    assert manifest["roster"]["playable_pilots"] == [
        "Fox McCloud", "Falco Lombardi", "Slippy Toad", "Peppy Hare"]
    assert set(manifest["roster"]["star_wolf_team"]) == {
        "Wolf O'Donnell", "Leon Powalski", "Pigma Dengar", "Andrew Oikonny"}
    assert manifest["roster"]["playable_vehicles"] == [
        "Arwing", "Landmaster", "Blue Marine"]
    text = json.dumps(manifest)  # must serialize
    assert '"ast_radio"' in text
