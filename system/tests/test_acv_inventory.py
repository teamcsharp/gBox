"""Regression tests for gbox.acv_inventory (Armored Core V XISO + BHD5 binder).

Locks the facts measured against the owned game image
(collections/Microsoft XBOX 360/roms/Armored Core V.iso):
  - the XISO media header layout (magic at LBA 32, root LBA at +0x14,
    root size at +0x18),
  - the identity (sha256) of bind/dvdbnd5.bhd,
  - the location and count of the BHD5 16-byte file-table records, and
    that every record's byte range lies inside bind/dvdbnd.bdt.
"""
import hashlib
import os
import struct

import pytest

import gbox.acv_inventory as acv

ISO_PATH = os.environ.get(
    "ACV_ISO",
    "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Armored Core V.iso",
)
XISO_SECTOR = 2048
EXPECTED_RECORD_COUNT = 19747
EXPECTED_TABLE_OFFSET = 0x58A0


def _reader(handle):
    def read(lba, nbytes):
        handle.seek(lba * XISO_SECTOR)
        return handle.read(nbytes)

    return read


def test_xiso_root_reads_media_header():
    """Synthetic media header: magic at LBA 32, root LBA at +0x14, size at +0x18."""
    header = bytearray(64)
    header[0:20] = acv.MEDIA_MAGIC
    struct.pack_into("<I", header, 0x14, 264)
    struct.pack_into("<I", header, 0x18, 88)
    blob = bytes(header)

    root_lba, root_size = acv.xiso_root(lambda lba, n: blob if lba == 32 else b"")

    assert root_lba == 264
    assert root_size == 88


def test_xiso_root_rejects_non_media():
    with pytest.raises(ValueError):
        acv.xiso_root(lambda lba, n: b"\x00" * 64)


@pytest.mark.skipif(not os.path.exists(ISO_PATH), reason="owned ACV image not mounted")
def test_owned_image_bhd5_file_table():
    """The owned image yields the verified BHD5 binder and file-table geometry."""
    with open(ISO_PATH, "rb") as handle:
        reader = _reader(handle)
        root_lba, root_size = acv.xiso_root(reader)
        entries = acv.parse_xiso_directory(reader, root_lba, root_size)
        by_path = {entry["path"]: entry for entry in entries}
        assert "bind/dvdbnd5.bhd" in by_path
        assert "bind/dvdbnd.bdt" in by_path
        bhd_entry = by_path["bind/dvdbnd5.bhd"]
        bdt_entry = by_path["bind/dvdbnd.bdt"]
        handle.seek(bhd_entry["lba"] * XISO_SECTOR)
        bhd = handle.read(bhd_entry["size"])

    assert bhd[:4] == b"BHD5"
    assert hashlib.sha256(bhd).hexdigest() == acv.ACV_DVDBND5_BHD_SHA256

    table_off, _ = acv.find_bhd5_file_table(bhd, bdt_entry["size"])
    assert table_off == EXPECTED_TABLE_OFFSET

    records = acv.parse_bhd5_files(bhd, bdt_entry["size"], table_off=table_off)
    assert len(records) == EXPECTED_RECORD_COUNT
    assert all(r["offset"] + r["size"] <= bdt_entry["size"] for r in records)


def _make_bhd(buckets):
    """buckets: list of lists of (hash,size,offset)."""
    n = len(buckets)
    table = 0x18
    rec_base = table + 8 * n
    body = b""
    heads = b""
    pos = rec_base
    for b in buckets:
        heads += struct.pack(">II", len(b), pos)
        for r in b:
            body += struct.pack(">IIQ", *r)
        pos += 16 * len(b)
    total = rec_base + len(body)
    return b"BHD5" + struct.pack(">IIIII", 0, 1, total, n, table) + heads + body


def test_parse_bhd5_buckets_synthetic():
    bhd = _make_bhd([[(3, 10, 0)], [], [(5, 20, 16), (8, 4, 64)]])
    recs = acv.parse_bhd5_buckets(bhd, 100)
    assert [(r["hash"], r["bucket"]) for r in recs] == [(3, 0), (5, 2), (8, 2)]
    with pytest.raises(ValueError):
        acv.parse_bhd5_buckets(bhd, 50)
    with pytest.raises(ValueError):
        acv.parse_bhd5_buckets(bhd[:-1], 100)


@pytest.mark.skipif(not os.path.exists(ISO_PATH), reason="owned ACV image not mounted")
def test_owned_image_bhd5_bucket_table():
    with open(ISO_PATH, "rb") as handle:
        reader = _reader(handle)
        root_lba, root_size = acv.xiso_root(reader)
        by_path = {e["path"]: e for e in acv.parse_xiso_directory(reader, root_lba, root_size)}
        bhd_entry = by_path["bind/dvdbnd5.bhd"]
        bdt_size = by_path["bind/dvdbnd.bdt"]["size"]
        handle.seek(bhd_entry["lba"] * XISO_SECTOR)
        bhd = handle.read(bhd_entry["size"])
    assert struct.unpack_from(">II", bhd, 0x10) == (2833, 0x18)
    recs = acv.parse_bhd5_buckets(bhd, bdt_size)
    assert len(recs) == EXPECTED_RECORD_COUNT
    assert all(r["hash"] % 2833 == r["bucket"] for r in recs)
