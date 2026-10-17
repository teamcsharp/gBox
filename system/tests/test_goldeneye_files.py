"""GoldenEye PAL file/body-table and character-model probe tests.

The ROM-backed tests need the owned, normalised PAL z64 (sha256 40ff3643...).
Point GBOX_GOLDENEYE_PAL_Z64 at it, or keep the cached copy at
~/gbox-cache/eecd1708cb2b8d14/rom.z64; otherwise they skip.
"""
from __future__ import annotations

import hashlib
import os
import struct
import zlib
from pathlib import Path

import pytest

from gbox import goldeneye_files as g


def _rom_path() -> Path | None:
    for cand in (
        os.environ.get("GBOX_GOLDENEYE_PAL_Z64", ""),
        str(Path.home() / "gbox-cache/eecd1708cb2b8d14/rom.z64"),
        str(Path(__file__).resolve().parents[1] / "artifacts/source/007_GoldenEye_Europe_norm.z64"),
    ):
        if cand and Path(cand).is_file():
            return Path(cand)
    return None


ROM = _rom_path()
needs_rom = pytest.mark.skipif(ROM is None, reason="owned GoldenEye PAL z64 not available")


def _raw_deflate(payload: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(payload) + c.flush()


def test_rarezip_roundtrip_synthetic():
    payload = bytes(range(256)) * 40
    blob = b"\xAA" * 6 + g.RAREZIP_MAGIC + _raw_deflate(payload) + b"\0" * 8
    out, used = g.rarezip_inflate(blob, 6)
    assert out == payload
    assert blob[6 + used:] == b"\0" * 8


def test_rarezip_rejects_missing_magic_and_truncation():
    with pytest.raises(g.GoldenEyeFormatError):
        g.rarezip_inflate(b"\x11\x73" + _raw_deflate(b"x" * 99), 0)
    stream = g.RAREZIP_MAGIC + _raw_deflate(bytes(4096))
    with pytest.raises(g.GoldenEyeFormatError):
        g.rarezip_inflate(stream[: len(stream) // 2], 0)


def test_walk_nodes_synthetic_tree():
    # root(op1) -> child(op2) -> next sibling(op0x18)
    def node(op, nxt=0, child=0):
        return struct.pack(">HHIIIII", op, 0, 0, 0, nxt, 0, child)
    seg = g.FILE_SEGMENT
    model = node(0x01, child=seg + 0x18) + node(0x02, nxt=seg + 0x30) + node(0x18)
    ops = sorted(op for _, op, _ in g.walk_nodes(model, 0))
    assert ops == [0x01, 0x02, 0x18]
    with pytest.raises(g.GoldenEyeFormatError):
        g.walk_nodes(node(0x01, child=seg + 0x1000), 0)


@pytest.fixture(scope="module")
def ge():
    assert ROM is not None
    return g.GoldenEyeROM.load(ROM)


@needs_rom
def test_owned_pal_identity_and_data_segment(ge):
    assert hashlib.sha256(ge.rom).hexdigest() == g.PAL_Z64_SHA256
    assert ge.rom[0x3B:0x3F] == b"NGEP"
    assert len(ge.data) == g.DATA_SEG_SIZE


@needs_rom
def test_file_table(ge):
    files = ge.file_table()
    assert len(files) == 771
    assert files[0].name == "" and files[-1].name == "ob/ob_end.seg"
    names = {f.name for f in files}
    for n in ("CsuitbondZ", "CnatalyaZ", "CheadbrosnanZ", "UsetupdamZ"):
        assert any(x.rsplit("/", 1)[-1] == n for x in names), n
    for f in files[1:-1]:
        if f.rom_size:
            assert ge.rom[f.rom_offset:f.rom_offset + 2] in (g.RAREZIP_MAGIC,) or not f.name.endswith("Z")


@needs_rom
def test_body_table_and_all_character_files_parse(ge):
    bodies = ge.body_table()
    assert len(bodies) == 80
    assert bodies[0].filename == "CcamguardZ"
    assert bodies[23].filename == "CsuitbondZ"
    assert bodies[-1].filename == "CspicebondZ"
    partial = set()
    for b in bodies:
        p = g.probe_character(ge, b.filename)
        assert p["inflated_size"] > 0
        if not b.is_head and p["skeleton_vram"]:
            assert p["position_nodes"] >= 1
            if p["position_nodes"] < 15:
                partial.add(b.filename)
    # Only the detached first-person hand rig is not a full 15-bone body.
    assert partial <= {"Csuit_lf_handZ"}, partial


@needs_rom
def test_suit_bond_probe_pins_header_and_tree(ge):
    p = g.probe_character(ge, "CsuitbondZ")
    assert p["file_index"] == 109
    assert p["rom_offset"] == 0x74BAB0 and p["rom_size"] == 0x2D90
    assert p["inflated_size"] == 28512
    assert p["inflated_sha256"] == "521bc97bbdd7787fa74f2fda73bc2addb7732810de6301d74c55a1be7c8a7afa"
    assert p["header_vram"] == 0x800375AC
    assert p["skeleton_vram"] == 0x80037190 and p["skeleton_joints"] == 16
    assert (p["num_switches"], p["num_matrices"], p["num_records"], p["num_textures"]) == (7, 21, 0, 14)
    assert p["root_offset"] == 0xC4
    assert p["node_count"] == 79 and p["position_nodes"] == 15 and p["vertex_dl_nodes"] == 25
    assert p["textures"][0] == {"id": 1642, "w": 32, "h": 48, "fmt": 4}


@needs_rom
def test_code_xrefs_locate_loader_functions(ge):
    ft = g.find_code_xrefs(ge.rom, g.FILE_TABLE_VRAM)
    assert {x["function_rom"] for x in ft} >= {0xEEAAC, 0xEEBB4, 0xEED8C, 0xEEFFC}
    bt = g.find_code_xrefs(ge.rom, g.BODY_TABLE_VRAM)
    assert len(bt) >= 10
