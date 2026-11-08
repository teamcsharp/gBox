"""DOA5 Last Round CHRT character-table reader (windows_native / PS3 USRDIR .lnk).

Verified against chara_rtm.lnk (79,450,112 B; sha256
b3b2a2c80af74b923c367957714a6de9a747425f40ff6c0620dd2a5d70f7ef0c) extracted
from the owned Dead or Alive 5 - Last Round (Japan) PS3_GAME/USRDIR
(request #2450, 2026-11-07):

  offset  field                    value
  0x00    magic                    b'CHRT'
  0x0C    u32BE count              368 (0x170)  == chara_rtm.bin LFMO entry count
  0x14    u32BE total_bytes        0x04BC5000   == file size - 0x800
  0x1C    u32BE base               0x00000800
  0x20..  count x 32-byte records, big-endian u32:
          +0x00 reserved           0   (all records)
          +0x04 field_a            > 0 (semantics unresolved)
          +0x08 reserved           0
          +0x0C field_b            address-like
          +0x10 reserved           0
          +0x14 field_b_dup        == field_b (all records)
          +0x18 reserved           0
          +0x1C reserved           0

All 368 records are field-consistent (reserved words zero, dup == field_b,
0 <= field_b < file size). field_a is NOT a plain byte length: treating
it as a size makes 367/367 adjacent-pair regions overlap and
sum(field_a) = 0x38A776000 (37.5 GB) >> file size. Only table geometry and
per-record invariants are asserted here; field semantics stay open.
"""
from __future__ import annotations

MAGIC = b"CHRT"
HEADER_SIZE = 0x20
RECORD_STRIDE = 32
RESERVED_WORDS = (0, 2, 4, 6, 7)
FIELD_A_WORD = 1
FIELD_B_WORD = 3
FIELD_B_DUP_WORD = 5


def parse_header(buf):
    """Return (count, total_bytes, base). Raises ValueError on bad magic."""
    if buf[:4] != MAGIC:
        raise ValueError("bad magic %r (want CHRT)" % (bytes(buf[:4]),))
    count = int.from_bytes(buf[0x0C:0x10], "big")
    total_bytes = int.from_bytes(buf[0x14:0x18], "big")
    base = int.from_bytes(buf[0x1C:0x20], "big")
    return count, total_bytes, base


def table_end(buf):
    """File offset just past the last block record."""
    count, _, _ = parse_header(buf)
    return HEADER_SIZE + count * RECORD_STRIDE


def parse_records(buf):
    """Yield one dict per block record (index, field_a, field_b,
    field_b_dup, reserved_zero, words)."""
    count, _, _ = parse_header(buf)
    for i in range(count):
        o = HEADER_SIZE + i * RECORD_STRIDE
        w = [int.from_bytes(buf[o + 4 * k: o + 4 * k + 4], "big") for k in range(8)]
        yield {
            "index": i,
            "field_a": w[FIELD_A_WORD],
            "field_b": w[FIELD_B_WORD],
            "field_b_dup": w[FIELD_B_DUP_WORD],
            "reserved_zero": all(w[k] == 0 for k in RESERVED_WORDS),
            "words": w,
        }


def verify(buf):
    """Whole-table consistency report.

    Checks per record: reserved words zero, field_a > 0,
    0 <= field_b < file size, field_b_dup == field_b.
    Does NOT assume field_a is a byte size (see module docstring).
    """
    n = len(buf)
    count, total, base = parse_header(buf)
    bad = []
    recs = list(parse_records(buf))
    for r in recs:
        i = r["index"]
        if not r["reserved_zero"]:
            bad.append((i, "reserved_nonzero"))
        if r["field_a"] <= 0:
            bad.append((i, "field_a_nonpos"))
        if r["field_b"] >= n:
            bad.append((i, "field_b_oob"))
        if r["field_b_dup"] != r["field_b"]:
            bad.append((i, "dup_mismatch"))
    return {
        "n": n,
        "count": count,
        "total_bytes_field": total,
        "base_field": base,
        "table_start": HEADER_SIZE,
        "table_end": table_end(buf),
        "records": len(recs),
        "bad": bad,
        "sum_field_a": sum(r["field_a"] for r in recs),
        "min_field_b": min(r["field_b"] for r in recs),
        "max_field_b_plus_a": max(r["field_b"] + r["field_a"] for r in recs),
    }
