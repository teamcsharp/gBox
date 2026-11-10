"""Focused tests for the Fare Wars BINC*.AFS container probe (request #2453).

Two layers, mirroring the inventory tests:
  * a synthetic in-memory blob proves the parser's structural rules
    (increasing offsets, terminator, record decode);
  * the owned-build test reads the real CT2/BINC1.AFS bytes from the owned
    CSO image (read-only) and asserts the decoded section table and the
    geometry-record run observed in analysis.
"""
import os
import struct

import pytest

from gbox.cso import CSO
from gbox.fare_wars_binc import (
    BINC1_CT2_OFFSET,
    BINC1_CT2_SHA256,
    BINC1_CT2_SIZE,
    OWNED_CSO_REL,
    RECORD_SIZE,
    parse_binc,
)

OWNED_ROOT = os.environ.get(
    "GBOX_HYPERSPIN_ROOT", "/mnt/gbox/hyperspin/Arcade"
)


def _owned_bytes() -> bytes:
    path = os.path.join(OWNED_ROOT, OWNED_CSO_REL)
    if not os.path.exists(path):
        pytest.skip(f"owned image not mounted: {path}")
    with CSO(path) as cso:
        cso.seek(BINC1_CT2_OFFSET)
        return cso.read(BINC1_CT2_SIZE)


def _synthetic() -> bytes:
    rec = struct.pack("<6f", 1.0, -2.5, 3.25, 0.5, -0.125, 8.0)
    rec += struct.pack("<I", 0x0017001E) + struct.pack("<I", 0)
    body = rec * 4
    offsets = [24 + len(body), 24 + len(body) + 16, 24 + len(body) + 32,
               24 + len(body) + 48, 24 + len(body) + 64]
    hdr = struct.pack("<5I", *offsets) + struct.pack("<I", 0)
    tail = b"".join(bytes([i]) * 16 for i in range(1, 17))
    return hdr + body + tail


def test_synthetic_structure():
    parsed = parse_binc(_synthetic())
    assert parsed.sections[0][0] == 24 + 4 * RECORD_SIZE
    assert len(parsed.sections) == 5
    assert len(parsed.records) == 4
    r = parsed.records[0]
    assert r.floats == (1.0, -2.5, 3.25, 0.5, -0.125, 8.0)
    assert r.packed == 0x0017001E and r.pad == 0


def test_synthetic_rejects_bad_header():
    blob = bytearray(_synthetic())
    blob[20:24] = struct.pack("<I", 1)  # terminator not zero
    with pytest.raises(ValueError):
        parse_binc(bytes(blob))
    blob2 = bytearray(_synthetic())
    blob2[0:4] = struct.pack("<I", 10**9)  # out of range
    with pytest.raises(ValueError):
        parse_binc(bytes(blob2))


def test_owned_binc1_ct2_sections():
    data = _owned_bytes()
    assert len(data) == BINC1_CT2_SIZE
    parsed = parse_binc(data)
    starts = [s[0] for s in parsed.sections]
    assert starts == [568, 10553, 50830, 1295804, 1966080]
    assert all(a < b for a, b in parsed.sections)
    assert parsed.sections[-1][1] == BINC1_CT2_SIZE


def test_owned_binc1_ct2_record_run():
    parsed = parse_binc(_owned_bytes())
    # 329 geometry-like 32-byte records observed in analysis (byte 24 through
    # 10552; section 0 proper spans bytes 568..10553); every pad word zero.
    assert len(parsed.records) == 329
    assert all(r.pad == 0 for r in parsed.records)
    # float slots are finite and in a plausible geometry range
    import math
    finite = sum(
        1
        for r in parsed.records
        for f in r.floats
        if math.isfinite(f) and 1e-6 < abs(f) < 1e7
    )
    assert finite > 0.95 * 6 * len(parsed.records)
