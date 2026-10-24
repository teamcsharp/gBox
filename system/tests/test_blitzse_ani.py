"""Focused tests for gbox.blitzse_ani (owned NFL Blitz SE N64 build).

The GENSEQ fixture is the first 96 bytes of the owned ``GENSEQ.ANI`` member
(fs method 5, 1,213,920 B) of the owned source zip
sha256 362bd74a0c9ee3a510dce7154dbd4049bad80897efb95b1d5456bac3e79419fe.
The packed fixture is the first 32 bytes of the owned packed member
``10ffont.wms`` (fs method 4).
"""
import hashlib

import pytest

from gbox.blitzse_ani import GenseqError, genseq, packed_prefix, GENSEQ_TAG, WMS_MAGIC

GENSEQ_HEAD = bytes.fromhex(
    "376a9a4e000000130000000f0000110000000001000000190000000f0000170c00000001000000190000000f00001ec800000001000000180000000f0000268400000001000000180000000f00002df800000001000000180000000f0000356c"
)
GENSEQ_HEAD_SHA256 = "8b1b051dc8cda7e24c845d9a0c92e7d3857773af5b38c995fc061a7988d9ebc9"
PACKED_HEAD = bytes.fromhex("1c776e0204000000180000025b000024002000000000020300555555200ec500")


def test_fixture_is_the_owned_bytes():
    assert hashlib.sha256(GENSEQ_HEAD).hexdigest() == GENSEQ_HEAD_SHA256


def test_genseq_parses_owned_header():
    g = genseq(GENSEQ_HEAD, strict=False)
    assert g["tag"] == GENSEQ_TAG == 0x376A9A4E
    assert g["limbs"] == 15
    assert g["count_field"] == 19
    assert g["table_offset"] == 0x1100
    assert g["scanned"] == 5
    assert g["count_field_matches"] is False


def test_genseq_sequences_are_consistent():
    g = genseq(GENSEQ_HEAD, strict=False)
    seqs = g["sequences"]
    assert [s["frames"] for s in seqs] == [25, 25, 24, 24, 24]
    assert all(s["limbs"] == 15 for s in seqs)
    assert all(s["flag"] == 1 for s in seqs)
    offs = [s["offset"] for s in seqs]
    assert offs == sorted(offs) and len(set(offs)) == len(offs)
    assert offs[0] == 0x170C
    assert all(s["span"] >= 0 for s in seqs)


def test_genseq_rejects_wrong_tag():
    bad = bytearray(GENSEQ_HEAD)
    bad[0] = 0x00
    with pytest.raises(GenseqError):
        genseq(bytes(bad), strict=False)


def test_genseq_rejects_truncated_input():
    with pytest.raises(GenseqError):
        genseq(GENSEQ_HEAD[:8])


def test_genseq_strict_rejects_offsets_past_the_buffer():
    with pytest.raises(GenseqError):
        genseq(GENSEQ_HEAD)


def test_packed_prefix_reports_wms_magic():
    p = packed_prefix(PACKED_HEAD)
    assert p["wms_magic"] is True
    assert p["magic"] == WMS_MAGIC
    assert p["lead"] == PACKED_HEAD[0] == 0x1C
    assert p["literal_len"] == 0x1C
    assert p["literal"].startswith(WMS_MAGIC)
    assert p["literal"] == PACKED_HEAD[1:29]


def test_packed_prefix_rejects_empty():
    with pytest.raises(ValueError):
        packed_prefix(b"")
