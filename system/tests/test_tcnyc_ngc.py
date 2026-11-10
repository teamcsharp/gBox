"""Tests for the TC2 ``.ngc`` probe: hand-built fixture + real-asset check."""
import hashlib
import os
import struct

import pytest

from gbox.tcnyc_ngc import (TC2FormatError, classify, is_hsd_archive,
                            is_tc2_container, parse_tc2_model)


def _blob(count=3, pad=0x10, table=0x70, tail=b"\x01" * 32):
    end = table + count * 0x40
    head = struct.pack(">7I", 9, 0x60000, 0x6C, (4 << 16) | count, table, 1, end + pad)
    head = head.ljust(table, b"\0")
    rec = struct.pack(">16I", *([0] * 15 + [0x3F800000]))
    return head + rec * count + b"\xaa" * pad + tail


def test_signature_and_classify():
    assert is_tc2_container(_blob()) and classify(_blob()) == "tc2_model"
    hs = struct.pack(">I", 64) + b"\0" * 60
    assert is_hsd_archive(hs, 64) and classify(hs, 64) == "hsd"
    assert classify(b"\x11\x22\x33\x44" * 8) == "unknown"


def test_parse_records_and_offsets():
    b = _blob(count=5)
    m = parse_tc2_model(b)
    assert (m.record_count, m.record_type, m.table_offset) == (5, 4, 0x70)
    assert m.data_offset == 0x70 + 5 * 0x40 + 0x10 and m.pad == 0x10
    assert len(m.records) == 5 and m.records[4].floats[15] == 1.0
    assert m.data_size == len(b) - m.data_offset
    assert parse_tc2_model(_blob(pad=0)).pad == 0


def test_rejects_bad_layouts():
    with pytest.raises(TC2FormatError):
        parse_tc2_model(b"\0\5\0\0" + b"\0" * 28)
    with pytest.raises(TC2FormatError):
        parse_tc2_model(_blob(count=3)[:0x90])          # table overruns
    bad = bytearray(_blob())
    struct.pack_into(">I", bad, 0x18, 0x10)             # data offset inside table
    with pytest.raises(TC2FormatError):
        parse_tc2_model(bytes(bad))


_REAL = os.environ.get("TCNYC_NGC_REAL", "/tmp/tcnyc_Body_F_Bum.ngc")


def test_real_target_when_present():
    if not os.path.exists(_REAL):
        pytest.skip("real extracted .ngc not present")
    d = open(_REAL, "rb").read()
    assert hashlib.sha256(d).hexdigest() == \
        "ace343b5f7349da53ea7a518ab51326fe05a74864af4f6b9d5db175e276080a7"
    m = parse_tc2_model(d)
    assert (m.record_count, m.table_offset, m.data_offset, m.pad) == (58, 0x70, 0xF00, 0x10)
    assert all(r.words[3] == 0x3F800000 for r in m.records[:20])
