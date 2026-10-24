"""Focused tests for the DOA2 arcade (NAOMI cart) inventory.

Fixtures are synthesized in the test (independent bytes), so the expectations
are derived from the documented layout, not from the owned ROM.
"""
from __future__ import annotations

import hashlib
import struct
import zipfile
from pathlib import Path

import pytest

from gbox.doa2_arcade_inventory import (GAME_ID, LOAD_BASE_CANDIDATES, build,
                                        count_models, parse_cart_header,
                                        pin_load_base, read_members,
                                        sha256_file)


def _cart_bytes(refs=(0x8C000000, 0x8C000000, 0x8C000030)) -> bytes:
    """A minimal NAOMI cart image: header block plus absolute pointer refs."""
    buf = bytearray(0x200)
    buf[0:5] = b"NAOMI"
    buf[0x10:0x20] = b"TECMO,LTD.      "
    buf[0x30:0x40] = b"DEAD OR ALIVE 2 "
    for i, region in enumerate((b"USA ------", b"EXPORT----", b"KOREA-----", b"AUSTRALIA-")):
        off = 0x50 + 0x20 * i
        buf[off:off + 16] = b"DEAD OR ALIVE 2 "
        buf[off + 16:off + 32] = region.ljust(16)
    for i, ref in enumerate(refs):
        struct.pack_into("<I", buf, 0x100 + 4 * i, ref)
    return bytes(buf)


def test_parse_cart_header_decodes_vendor_title_and_regions():
    h = parse_cart_header(_cart_bytes())
    assert h["magic"] == "NAOMI"
    assert h["vendor"] == "TECMO,LTD."
    assert h["title"] == "DEAD OR ALIVE 2"
    assert [r["region"] for r in h["regions"]] == ["USA", "EXPORT", "KOREA", "AUSTRALIA"]
    assert h["regions"][0]["title"] == "DEAD OR ALIVE 2"


def test_parse_cart_header_rejects_non_naomi_data():
    with pytest.raises(ValueError):
        parse_cart_header(b"NOTNAOMI" + b"\x00" * 0x100)


def test_pin_load_base_picks_the_referenced_candidate():
    data = _cart_bytes()
    base = pin_load_base(data)
    assert base["load_base"] == "0x8c000000"
    assert base["scores"]["0x8c000000"] == 3
    assert base["scores"]["0x8c010000"] == 0
    assert base["margin"] == 3


def test_pin_load_base_refuses_a_tie():
    data = _cart_bytes(refs=(0x8C000000, 0x8C010000))
    with pytest.raises(ValueError):
        pin_load_base(data)


def test_pin_load_base_covers_both_candidates():
    assert LOAD_BASE_CANDIDATES == (0x8C000000, 0x8C010000)


def test_count_models_reports_zero_for_header_only_data():
    result = count_models(_cart_bytes())
    assert result["decoded"] is True
    assert result["count"] == 0


def test_read_members_counts_real_sizes_and_crcs(tmp_path):
    z = tmp_path / "set.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("epr-22207.ic22", b"A" * 32)
        zf.writestr("extra.bin", b"B" * 8)
    members = read_members(z)
    assert [m["name"] for m in members] == ["epr-22207.ic22", "extra.bin"]
    assert [m["bytes"] for m in members] == [32, 8]
    assert all(len(m["crc32"]) == 8 for m in members)


def test_sha256_file_matches_streamed_hash(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"abc" * 1000)
    assert sha256_file(p) == hashlib.sha256(b"abc" * 1000).hexdigest()


def test_build_writes_a_manifest_with_pinned_base(tmp_path):
    z = tmp_path / "set.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("epr-22207.ic22", _cart_bytes())
    manifest = build(z, scan_model=False)
    assert manifest["game_id"] == GAME_ID
    assert manifest["source"]["member"] == "epr-22207.ic22"
    assert manifest["source"]["member_sha256"] == hashlib.sha256(_cart_bytes()).hexdigest()
    assert manifest["load_base"]["load_base"] == "0x8c000000"
    assert manifest["cart_header"]["regions"][0]["region"] == "USA"
    assert manifest["assets"]["members"][0]["bytes"] == len(_cart_bytes())
    assert manifest["assets"]["cart_models"] is None


def test_build_rejects_a_missing_member(tmp_path):
    z = tmp_path / "set.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("other.bin", b"x" * 16)
    with pytest.raises(ValueError):
        build(z, scan_model=False)
