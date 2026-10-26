"""Tests for gbox.re6_stage_assets (RE6 PS3 arc/sa/SPK readers).

Hermetic tests build a synthetic ARC v8 in a tmp_path; the SPK header tests
run against fixtures carved from the retail US/Asia dump
(BLUS30855 nativePS3, Mercenaries.sc and sa/PS3/e1050.arc headers).
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "system"))

from gbox import re6_stage_assets as rsa  # noqa: E402

#: Carved from the retail US/Asia dump (BLUS30855 nativePS3): first 0x60
#: bytes of the inflated sc\PS3\Mercenaries SPK pack (sa/PS3/Mercenaries.arc)
#: and of the sa/PS3/e1050.arc container header.
MERCENARIES_SPK_HEADER = bytes.fromhex(
    "004b5053a14be3b6002212e802d30839000002d3000012e90000866900700e60"
    "0018ecb4000252d000265d180003800400070cdc000926800022133400246604"
    "0024a9cc0024cbb000252e5c00252e5c000000000000089500000350000005bc"
)
SA_E1050_HEADER = bytes.fromhex(
    "004352410008000173635c5053335c65313035300000000000000000000000"
    "00000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000002358e1a00044b0000a3c202000000586881cc5b09"
    "7c54d5"
)


def build_arc(entries: list[tuple[str, int, bytes, bool]]) -> bytes:
    """Build a minimal ARC v8 image: (name, type_hash, payload, compress)."""
    header = rsa.ARC_MAGIC + struct.pack(">HH", 8, len(entries))
    table = b""
    body = b""
    offset = 8 + 80 * len(entries)
    for name, type_hash, payload, compress in entries:
        raw = zlib.compress(payload) if compress else payload
        if compress and len(raw) >= len(payload):
            compress = False  # real arcs store incompressible payloads raw
            raw = payload
        csize = len(raw)
        sizeflags = (len(payload) << 3) | (2 if compress else 0)
        table += name.encode("latin-1").ljust(64, b"\0")
        table += struct.pack(">IIII", type_hash, csize, sizeflags, offset)
        body += raw
        offset += csize
    return header + table + body


def test_arc_roundtrip_compressed_and_stored(tmp_path: Path) -> None:
    payload_a = b"stage collision bytes \x00\x01" * 40
    payload_b = b"raw stored payload" * 10
    arc = tmp_path / "mini.arc"
    arc.write_bytes(
        build_arc(
            [
                (r"data\stage\s0101\col", 0x241F5DEB, payload_a, True),
                (r"data\stage\s0101\scr", 0x58A15856, payload_b, False),
            ]
        )
    )
    entries = rsa.read_arc(arc)
    assert [e.name for e in entries] == [r"data\stage\s0101\col", r"data\stage\s0101\scr"]
    assert entries[0].compressed and not entries[1].compressed
    assert entries[0].logical_size == len(payload_a)
    assert rsa.extract_arc_entry(arc, entries[0]) == payload_a
    assert rsa.extract_arc_entry(arc, entries[1]) == payload_b


def test_arc_rejects_bad_magic(tmp_path: Path) -> None:
    bad = tmp_path / "bad.arc"
    bad.write_bytes(b"NOPE" + struct.pack(">HH", 8, 0))
    with pytest.raises(rsa.ArcError, match="magic"):
        rsa.read_arc(bad)


def test_arc_rejects_unsupported_version(tmp_path: Path) -> None:
    bad = tmp_path / "v9.arc"
    bad.write_bytes(rsa.ARC_MAGIC + struct.pack(">HH", 9, 0))
    with pytest.raises(rsa.ArcError, match="version"):
        rsa.read_arc(bad)


def test_scenario_arc_roundtrip(tmp_path: Path) -> None:
    spk = MERCENARIES_SPK_HEADER
    arc = tmp_path / "Mercenaries.arc"
    arc.write_bytes(build_arc([(r"sc\PS3\Mercenaries", 0x02358E1A, spk, True)]))
    name, blob = rsa.read_scenario(arc)
    assert name == r"sc\PS3\Mercenaries"
    assert blob[:4] == rsa.SPK_MAGIC


def test_spk_header_fixture_parses() -> None:
    hdr = MERCENARIES_SPK_HEADER
    assert hdr[:4] == rsa.SPK_MAGIC
    assert struct.unpack_from(">I", hdr, 4)[0] == rsa.SPK_RETAIL_TAG
    # padding beyond the carved header means parse_spk must cope with a short body
    info = rsa.parse_spk(hdr + b"\x00" * 16)
    assert info.tag == rsa.SPK_RETAIL_TAG
    # retail Mercenaries.sc table: 15 distinct sizes before the sentinel repeat
    assert len(info.section_sizes) == 15
    assert info.section_sizes[0] == 0x2D3
    assert info.section_sizes[3] == 0x700E60


def test_spk_rejects_foreign_magic() -> None:
    with pytest.raises(rsa.SpkError, match="magic"):
        rsa.parse_spk(b"NOPE" + b"\x00" * 0x60)


def test_sa_e1050_fixture_header() -> None:
    hdr = SA_E1050_HEADER
    # carved ARC header: magic, version 8, 1 entry, sc\PS3\e1050 table row
    assert hdr[:4] == rsa.ARC_MAGIC
    version, count = struct.unpack_from(">HH", hdr, 4)
    assert (version, count) == (8, 1)
    assert hdr[8:72].split(b"\0")[0] == rb"sc\PS3\e1050"
    type_hash, csize, sizeflags, offset = struct.unpack_from(">IIII", hdr, 72)
    assert type_hash == 0x02358E1A
    assert sizeflags >> 3 == 1341504  # logical size of the SPK body
    assert offset == 8 + 80  # single entry: body starts right after the table


#: Carved from the retail US/Asia dump (BLUS30855): first 0x50 bytes of the
#: inflated data\stage\s0201\scr\scr00\s0201_wood MWS placement file
#: (arc/PS3/e1050.arc) and the first 0x20 bytes of the inflated
#: data\event\e1050\e1050 LDS event setup.
S0201_WOOD_MWS = bytes.fromhex(
    "004d57530edd0081000000034564893e"
    "440dd8d5452303580000000000000000"
    "ededededededededededededc4e4893e"
    "c290295f0000000000000000001b008d"
    "edededededededededededed4564893e"
    "440dd8d5452303580000000000000000"
    "ededededededededededededc4e4893e"
    "c290295f0000000000000000000c008d"
    "edededededededededededed4564893e"
    "440dd8d5452303580000000000000000"
    "ededededededededededededc4e4893e"
    "c290295f0000000000000000002d008d"
    "edededededededededededed"
)
E1050_LDS_HEADER = bytes.fromhex(
    "004c4453001705adb9814f520004f9000000000400014c3401000000"
    "00000000000000000000000001010000"
)


def test_mws_fixture_parses_positions() -> None:
    info = rsa.parse_mws(S0201_WOOD_MWS)
    assert info.version == 0x0EDD
    assert info.flags == 0x0081
    assert len(info.records) == 3
    # first placement record: big-endian f32 world position
    x, y, z = info.records[0].position
    assert round(x, 3) == 3656.578
    assert round(y, 3) == 567.388
    assert round(z, 3) == 2608.209
    # second record repeats the placement at the same world position
    assert info.records[1].position == info.records[0].position
    assert info.records[0].offset == 0x0C
    assert info.records[1].offset == 0x4C


def test_mws_rejects_foreign_magic() -> None:
    with pytest.raises(ValueError, match="magic"):
        rsa.parse_mws(b"NOPE" + b"\x00" * 0x20)


def test_mws_rejects_truncated_records() -> None:
    short = rsa.MWS_MAGIC + struct.pack(">HHI", 0x0EDD, 0x81, 2) + b"\x00" * 0x40
    with pytest.raises(ValueError, match="truncated"):
        rsa.parse_mws(short)


def test_lds_fixture_header_parses() -> None:
    info = rsa.parse_lds(E1050_LDS_HEADER)
    assert info["version"] == 0x17
    assert info["event_id"] == "0x05ad"
    assert info["tag"] == f"0x{rsa.LDS_RETAIL_TAG:08x}"
    assert info["size"] == len(E1050_LDS_HEADER)


def test_lds_rejects_foreign_magic() -> None:
    with pytest.raises(ValueError, match="magic"):
        rsa.parse_lds(b"NOPE" + b"\x00" * 0x20)


def test_new_stage_setup_type_hashes_named() -> None:
    assert rsa.ARC_TYPE_NAMES[0x4C0DB839] == "lds"
    assert rsa.ARC_TYPE_NAMES[0x257D2F7C] == "mws"
    assert rsa.ARC_TYPE_NAMES[0x76820D81] == "tmc"
    assert rsa.ARC_TYPE_NAMES[0x39C52040] == "mcl"
    assert rsa.ARC_TYPE_NAMES[0x6D5AE854] == "lfe"


def test_inventory_reports_stage_placements(tmp_path: Path) -> None:
    arc = tmp_path / "e1050.arc"
    arc.write_bytes(
        build_arc([(r"data\stage\s0201\scr\scr00\s0201_wood", 0x257D2F7C, S0201_WOOD_MWS, True)])
    )
    inv = rsa.inventory(arc)
    assert inv["stage_placements"][0]["records"] == 3
    assert inv["stage_placements"][0]["positions"][0] == [3656.578, 567.388, 2608.209]
