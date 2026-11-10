"""BHD5 name-region decoder for Armored Core V (Xbox 360).

Companion to acv_inventory.py (XISO walk + BHD5 file records) and
acv_bdt_magic_scan.py (BDT magic stream-scan verdict).

The BHD5 binder (bind/dvdbnd5.bhd, 338,640 B, sha256 7656d45f...) stores
no names: every file is keyed by a 32-bit hash.  The 0x10..0x58a0 region
("directory/name region") therefore holds the bucket index that maps
hash -> file record.  Layout, big endian, all verified against the owned
ISO (sha256 d028051a...6189):

  0x00  "BHD5"
  0x04  u32 0
  0x08  u32 version (1)
  0x0C  u32 bhd_size            (338640 == 0x52AD0)
  0x10  u32 bucketCount         (2833)
  0x14  u32 bucketsOffset       (0x18)
  0x18  bucketCount x (u32 fileCount, u32 recordsOffset)  -> ends at 0x58A0
  0x58A0 file-table records: u32 hash, u32 size, u64 offset (19,747 x 16 B
          -> 0x52AD0, the end of the BHD)

Bounded invariants (ValueError on violation):
  - magic and bhd_size agree with the actual byte count,
  - the bucket table starts at bucketsOffset >= 0x18 and
    bucketsOffset + 8*bucketCount <= len(bhd),
  - every bucket's record range [recordsOffset, recordsOffset +
    16*fileCount) lies inside the BHD and is 16-byte aligned,
  - the bucket record ranges tile one contiguous, gap-free, overlap-free
    region (on ACV: 0x58A0..0x52AD0) and their file counts sum to the
    total record count,
  - placement: record hash % bucketCount == its bucket index (verified for
    all 19,747 owned records) and per-bucket counts match the table.

Read-only: nothing here touches the disc or the binder.
"""

from __future__ import annotations

import struct

BHD5_MAGIC = b"BHD5"
HEADER_SIZE = 0x18
RECORD_SIZE = 16

# ACV geometry, verified against the owned ISO (recorded in
# acv_inventory.py and the BDT stream-scan evidence).
ACV_BHD_SIZE = 338640          # 0x52AD0
ACV_BUCKET_COUNT = 2833
ACV_BUCKETS_OFFSET = 0x18
ACV_NAME_REGION_END = 0x58A0   # bucketsOffset + 8 * bucketCount
ACV_RECORDS_START = 0x58A0
ACV_RECORDS_END = 0x52AD0      # recordsStart + 16 * 19747
ACV_RECORD_COUNT = 19747


def parse_bhd5_name_region(bhd: bytes) -> dict:
    """Decode the BHD5 header + bucket (name-hash) region 0x10..bucketsEnd.

    Returns a dict with the header fields, the per-bucket
    (file_count, records_offset) table, and the tiling geometry of the
    record region the buckets reference.  Raises ValueError on any
    bound violation (see module docstring).
    """
    if len(bhd) < HEADER_SIZE or bhd[:4] != BHD5_MAGIC:
        raise ValueError("not a BHD5 binder")
    _, version, bhd_size, bucket_count, buckets_off = struct.unpack_from(
        ">IIIII", bhd, 4)
    if bhd_size != len(bhd):
        raise ValueError("BHD5 size field %d != actual %d" % (bhd_size, len(bhd)))
    if bucket_count == 0:
        raise ValueError("bucketCount is zero")
    if buckets_off < HEADER_SIZE:
        raise ValueError("bucketsOffset 0x%x below header end" % buckets_off)
    buckets_end = buckets_off + 8 * bucket_count
    if buckets_end > len(bhd):
        raise ValueError("bucket table out of range (end 0x%x > 0x%x)"
                         % (buckets_end, len(bhd)))

    buckets = []
    ranges = []
    for i in range(bucket_count):
        count, roff = struct.unpack_from(">II", bhd, buckets_off + 8 * i)
        if roff & (RECORD_SIZE - 1):
            raise ValueError("bucket %d recordsOffset 0x%x not 16-byte aligned"
                             % (i, roff))
        rstart = roff
        rend = roff + RECORD_SIZE * count
        if rstart < buckets_off:
            raise ValueError("bucket %d record range overlaps name region" % i)
        if rend > len(bhd):
            raise ValueError("bucket %d record range out of BHD (end 0x%x)"
                             % (i, rend))
        buckets.append({"index": i, "file_count": count,
                        "records_offset": roff})
        ranges.append((rstart, rend, i))

    # Tiling: sorted ranges must be contiguous (no gap, no overlap).
    ranges.sort()
    for prev, nxt in zip(ranges, ranges[1:]):
        if prev[1] != nxt[0]:
            raise ValueError("bucket record ranges do not tile: gap/overlap "
                             "between 0x%x and 0x%x" % (prev[1], nxt[0]))
    records_start, records_end = ranges[0][0], ranges[-1][1]
    total_records = sum(b["file_count"] for b in buckets)
    if (records_end - records_start) != RECORD_SIZE * total_records:
        raise ValueError("tiling extent != 16 * total record count")

    return {
        "bhd_size": bhd_size,
        "version": version,
        "bucket_count": bucket_count,
        "buckets_offset": buckets_off,
        "name_region_end": buckets_end,
        "buckets": buckets,
        "records_start": records_start,
        "records_end": records_end,
        "record_count": total_records,
    }


def check_record_placement(records: list[dict], name_region: dict) -> int:
    """Verify records against the bucket table decoded from the name region.

    records: [{"hash", "size", "offset", "bucket"}] as produced by
    acv_inventory.parse_bhd5_buckets (offset is the BDT payload offset, not a
    BHD position).  Checks hash % bucketCount == bucket for every record and
    that per-bucket record counts equal the table's fileCount.  Returns the
    number of records checked; ValueError on any violation.
    """
    bucket_count = name_region["bucket_count"]
    per_bucket = [0] * bucket_count
    for rec in records:
        b = rec["bucket"]
        if not (0 <= b < bucket_count):
            raise ValueError("record bucket %r out of range" % (b,))
        if rec["hash"] % bucket_count != b:
            raise ValueError("record hash 0x%08x selects bucket %d but sits "
                             "in bucket %d" % (rec["hash"],
                                               rec["hash"] % bucket_count, b))
        per_bucket[b] += 1
    for bk in name_region["buckets"]:
        if per_bucket[bk["index"]] != bk["file_count"]:
            raise ValueError("bucket %d has %d records, table says %d"
                             % (bk["index"], per_bucket[bk["index"]],
                                bk["file_count"]))
    return len(records)
