"""Regression tests for gbox.acv_bhd5_names (BHD5 name-region decoder).

Locks the 0x10..0x58a0 directory/name region of bind/dvdbnd5.bhd for
Armored Core V: header fields, the 2833-bucket table, and the tiling of
the 19,747 16-byte hash records across 0x58A0..0x52AD0.  The synthetic
and bounded-consistency tests run without the ISO; the owned-image test
skips when the image is not mounted and is the acceptance check on an
ISO-capable host (in-range bucket offsets, counts, and hash placement).
"""
import hashlib
import os
import struct

import pytest

import gbox.acv_bhd5_names as names
from gbox import acv_inventory as acv
from gbox.acv_bdt_magic_scan import SCAN

ISO_PATH = os.environ.get(
    "ACV_ISO",
    "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/"
    "Armored Core V.iso",
)
XISO_SECTOR = 2048


def _make_bhd(bucket_layout, buckets_off=0x18, magic=b"BHD5"):
    """Synthetic BHD5: bucket_layout = list of (file_count, records_offset)."""
    n = len(bucket_layout)
    table_end = buckets_off + 8 * n
    rec_end = max(o + 16 * c for c, o in bucket_layout)
    size = max(table_end, rec_end)
    body = bytearray(table_end)
    for i, (count, roff) in enumerate(bucket_layout):
        struct.pack_into(">II", body, buckets_off + 8 * i, count, roff)
    blob = magic + struct.pack(">IIIII", 0, 1, size, n, buckets_off) + bytes(body[0x18:])
    return blob + b"\x00" * (size - len(blob))


def test_name_region_synthetic_decode():
    # two buckets tiling 0x30..0x50 (2 records), name region 0x18..0x30
    bhd = _make_bhd([(1, 0x30), (1, 0x40)])
    nr = names.parse_bhd5_name_region(bhd)
    assert nr["version"] == 1
    assert nr["bucket_count"] == 2
    assert nr["buckets_offset"] == 0x18
    assert nr["name_region_end"] == 0x28
    assert nr["records_start"] == 0x30
    assert nr["records_end"] == 0x50
    assert nr["record_count"] == 2
    assert [(b["file_count"], b["records_offset"]) for b in nr["buckets"]] == \
        [(1, 0x30), (1, 0x40)]


def test_name_region_rejects_bound_violations():
    good = _make_bhd([(1, 0x30), (1, 0x40)])
    with pytest.raises(ValueError):
        names.parse_bhd5_name_region(good[:4].replace(b"BHD5", b"BHD6")
                                     + good[4:])
    # bhd_size field disagrees with actual length
    bad = bytearray(good)
    struct.pack_into(">I", bad, 0x0C, len(good) + 16)
    with pytest.raises(ValueError):
        names.parse_bhd5_name_region(bytes(bad))
    # bucket table out of range (bucketCount too large)
    bad = bytearray(good)
    struct.pack_into(">I", bad, 0x10, 100)
    with pytest.raises(ValueError):
        names.parse_bhd5_name_region(bytes(bad))
    # record range out of BHD
    bad = bytearray(good)
    struct.pack_into(">I", bad, 0x18 + 4, 0x900)  # second bucket offset
    with pytest.raises(ValueError):
        names.parse_bhd5_name_region(bytes(bad))
    # unaligned recordsOffset
    bad = bytearray(good)
    struct.pack_into(">I", bad, 0x18 + 4, 0x44)
    with pytest.raises(ValueError):
        names.parse_bhd5_name_region(bytes(bad))
    # gap between bucket ranges (bucket 1 starts after 0x40+16)
    bad = bytearray(good)
    struct.pack_into(">I", bad, 0x18 + 4, 0x50)
    with pytest.raises(ValueError):
        names.parse_bhd5_name_region(bytes(bad))


def test_check_record_placement_synthetic():
    bhd = _make_bhd([(2, 0x30), (1, 0x50)])
    nr = names.parse_bhd5_name_region(bhd)
    records = [
        {"hash": 10, "size": 100, "offset": 0, "bucket": 0},
        {"hash": 12, "size": 50, "offset": 0, "bucket": 0},
        {"hash": 11, "size": 80, "offset": 0, "bucket": 1},
    ]
    assert names.check_record_placement(records, nr) == 3
    with pytest.raises(ValueError):   # hash selects bucket 1, sits in 0
        names.check_record_placement([dict(records[0], hash=11)] + records[1:], nr)
    with pytest.raises(ValueError):   # per-bucket count mismatch
        names.check_record_placement(records[:2], nr)


def test_acv_geometry_bounded_consistency():
    """ISO-free arithmetic check of the recorded ACV name-region geometry."""
    assert names.ACV_BUCKETS_OFFSET + 8 * names.ACV_BUCKET_COUNT == \
        names.ACV_NAME_REGION_END == names.ACV_RECORDS_START
    assert names.ACV_RECORDS_START + 16 * names.ACV_RECORD_COUNT == \
        names.ACV_RECORDS_END == names.ACV_BHD_SIZE == 0x52AD0
    # cross-check the committed BDT stream-scan geometry
    assert SCAN["records"] == names.ACV_RECORD_COUNT
    assert SCAN["bdt_size"] == 3298094700
    assert SCAN["bdt_lba"] == 12314
    assert SCAN["dcx_delta_min"] == 0 and SCAN["dcx_delta_median"] == 0
    assert SCAN["dcx_out_region"] == 0
    # every magic hit in the scan is inside the BDT
    for hit in SCAN["hits"].values():
        assert all(0 <= p < SCAN["bdt_size"] for p in hit["first16"])


def _reader(handle):
    def read(lba, nbytes):
        handle.seek(lba * XISO_SECTOR)
        return handle.read(nbytes)

    return read


@pytest.mark.skipif(not os.path.exists(ISO_PATH),
                    reason="owned ACV image not mounted")
def test_owned_image_bhd5_name_region():
    """Owned ISO: decode the name region and verify every record in range."""
    with open(ISO_PATH, "rb") as handle:
        reader = _reader(handle)
        root_lba, root_size = acv.xiso_root(reader)
        by_path = {e["path"]: e
                   for e in acv.parse_xiso_directory(reader, root_lba,
                                                     root_size)}
        bhd_entry = by_path["bind/dvdbnd5.bhd"]
        bdt_size = by_path["bind/dvdbnd.bdt"]["size"]
        handle.seek(bhd_entry["lba"] * XISO_SECTOR)
        bhd = handle.read(bhd_entry["size"])

    assert bhd[:4] == b"BHD5"
    assert hashlib.sha256(bhd).hexdigest() == acv.ACV_DVDBND5_BHD_SHA256

    nr = names.parse_bhd5_name_region(bhd)
    assert nr["bucket_count"] == names.ACV_BUCKET_COUNT == 2833
    assert nr["buckets_offset"] == names.ACV_BUCKETS_OFFSET == 0x18
    assert nr["name_region_end"] == names.ACV_NAME_REGION_END == 0x58A0
    assert nr["records_start"] == names.ACV_RECORDS_START == 0x58A0
    assert nr["records_end"] == names.ACV_RECORDS_END == 0x52AD0
    assert nr["record_count"] == names.ACV_RECORD_COUNT == 19747

    # every parsed record: bounded in BDT, placement consistent with hash
    int_recs = acv.parse_bhd5_buckets(bhd, bdt_size)
    assert len(int_recs) == 19747
    checked = names.check_record_placement(int_recs, nr)
    assert checked == 19747
    assert all(r["offset"] + r["size"] <= bdt_size for r in int_recs)
