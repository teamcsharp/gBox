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
