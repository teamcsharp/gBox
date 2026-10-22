"""NFL Blitz 2003 (USA) GC inventory: .ziH + corrupted-local-header ZIP reader.

Runs against the owned-source artifacts extracted read-only from
``NFL Blitz 2003 (USA).gcz`` (sha256 040ae15f...bb439).  Artifacts live in
the scratch cache and are also mirrored under fixtures via env overrides.
"""
import hashlib
import os
import struct
import zlib
from pathlib import Path

import pytest

from gbox import nfl_blitz_2003 as nb

SCRATCH = Path(os.environ.get("BH_AGENT_WORKSPACE", Path.home() / ".hermes/cache/scratch"))
ZIHP = SCRATCH / "nb2003_players.ziH"
ZIP = SCRATCH / "nb2003_players.zip"

needs_artifacts = pytest.mark.skipif(
    not (ZIHP.exists() and ZIP.exists()), reason="owned-source artifacts not cached"
)


def _synthetic_pair():
    """Build a store-method zip with a corrupted local-header signature and
    a matching ziH table; exercise scan/extract/verify paths."""
    payload = bytes(range(256)) * 4
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    name = b"ape.dff"
    lh = bytearray(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                               crc, len(payload), len(payload), len(name), 3))
    lh += name + b"\x00\x00\x00" + payload
    # corrupt the local header magic (as on the real disc)
    lh[2] = 0xFF
    body = bytes(lh)
    # real header stored at a shifted position: keep a valid one too for scan
    good = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0,
                       crc, len(payload), len(payload), len(name), 0) + name + payload
    blob = body + good
    zih = struct.pack("<II", 1, 8 + 24) + struct.pack(">6I", 0, len(payload), 0, 0, len(payload), 0)
    zih += name + b"\x00"
    return blob, zih


def test_synthetic_roundtrip():
    blob, zih = _synthetic_pair()
    table, members = nb.load_container(blob, zih)
    assert table.count == 1 and len(members) == 1
    m = members[-1]  # corrupted leading header is skipped by CRC guard
    assert m.name == "ape.dff"
    assert nb.extract_member(blob, m) == bytes(range(256)) * 4
    with pytest.raises(ValueError):
        nb.parse_zih(b"\x00" * 4)


def test_synthetic_crc_detects_corruption():
    blob, zih = _synthetic_pair()
    _, members = nb.load_container(blob, zih)
    m = members[-1]
    bad = bytearray(blob)
    bad[m.data_offset] ^= 0xFF
    with pytest.raises(ValueError):
        nb.extract_member(bytes(bad), m)


@needs_artifacts
def test_players_container_fully_verifies():
    zi = ZIHP.read_bytes()
    zp = ZIP.read_bytes()
    table, members = nb.load_container(zp, zi)
    assert table.count == 296
    names = [m.name for m in members]
    assert len(set(names)) == 296
    total = 0
    for m in members:
        total += len(nb.extract_member(zp, m))
    assert total == 41_530_512


@needs_artifacts
def test_ape_dff_identity():
    zp = ZIP.read_bytes()
    _, members = nb.load_container(ZIHP.read_bytes(), zp)
    m = next(m for m in members if m.name == "ape.dff")
    data = nb.extract_member(zp, m)
    assert len(data) == 458_492
    assert hashlib.sha256(data).hexdigest().startswith("878165bf6382da46")


@needs_artifacts
def test_zipfile_stdlib_fails_but_reader_works():
    """Documents the corruption: stdlib zipfile cannot open the container."""
    import zipfile
    io = __import__("io")
    with pytest.raises(zipfile.BadZipFile):
        zipfile.ZipFile(io.BytesIO(ZIP.read_bytes())).read("ape.dff")
