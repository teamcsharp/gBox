"""Inventory census for Black (USA) PS2 (SLUS_213.76) asset containers.

Verified structural facts (lilspark2 2026-11-05, re-verified 2026-11-10
against extracted owned bytes):
  CHARS/TRANS_CH.BIN  header u32[4] = {count=161, stride=0x10,
                      off_attr1=0xcb0, off_attr2=0xd60}. The 161 ASCII
                      name/slot records (I_030, S_102, U_001, C_001, ...,
                      S_650) are 16-byte NUL-padded strings at 0x2a0. The
                      header's 0xcb0/0xd60 offsets point to per-character
                      attribute/flag tables (single-byte codes 0x04/0x05/
                      0x0b/...), NOT name strings.
  CHARS/TRANS_FP.BIN  header u32[4] = {count=37, stride=0x10, 0x300, 0x330};
                      37 first-person weapon slots; names (_001/_050/_100...)
                      at 0x300/0x330; leading u32 index records at 0x10.
  DATA/ANDY.AKU       u32[5] header {blocks=2, block1_off=0x52a(1322),
                      reserved=0, units=21, payload_size=0x2970(10608)} +
                      float stream.
  LEVELS/LEVEL_00/UNIT_01.BIN  u32 count=24 then internal u32 offsets,
                      first triplet (0x531400, 0x5d74b0, 0x6d53d0) -> float
                      and table blocks inside the 9 MB container.
All data little-endian (PS2 / MIPS LE).
"""
import json
import os
import struct
import sys


def parse_name_table(data, record_offset=0x2A0):
    """Parse a TRANS_*.BIN name/slot registry.

    Header: u32 count, u32 stride (bytes per record).
    Records: count * stride bytes at record_offset; each record is a
    NUL-padded ASCII name slot (stride bytes).
    """
    count, stride = struct.unpack_from("<II", data, 0)
    # Clamp iteration to bytes actually present: truncated fixtures (and short
    # tail blocks in real files) contain fewer than `count` full records; the
    # header count is an upper bound, not a hard size guarantee.
    avail = len(data) - record_offset
    n_read = max(0, min(count, avail // stride))
    names = []
    for i in range(n_read):
        rec = data[record_offset + i * stride: record_offset + (i + 1) * stride]
        names.append(rec.split(b"\x00")[0].decode("ascii", "replace"))
    return {"count": count, "stride": stride, "record_offset": record_offset,
            "names": names}


def parse_unit_container_header(data):
    """UNIT_01.BIN / STUNIT01.BIN header: u32 entry count followed by
    u32 internal offsets (schema beyond the count not yet proven)."""
    count = struct.unpack_from("<I", data, 0)[0]
    n = min(3 * count, (len(data) - 4) // 4)
    offsets = list(struct.unpack_from(f"<{n}I", data, 4))
    return {"count": count, "first_offsets": offsets[:3]}


def parse_ak_header(data):
    """DATA/*.AKU header: u32[5] = {blocks, block1_off, reserved,
    units, payload_size} followed by a float32 stream."""
    return dict(zip(["blocks", "block1_offset", "reserved", "units",
                     "payload_size"], struct.unpack_from("<5I", data, 0)))


def census_paths(root):
    """Census the owned extracted root (read-only)."""
    out = {}
    def try_census(rel, fn, **kw):
        p = os.path.join(root, rel)
        try:
            out[rel] = fn(open(p, "rb").read(), **kw)
        except OSError:
            out[rel] = {"error": "missing"}
    try_census("CHARS/TRANS_CH.BIN", parse_name_table)
    try_census("CHARS/TRANS_FP.BIN", parse_name_table, record_offset=0x10)
    try_census("DATA/ANDY.AKU", parse_ak_header)
    try_census("LEVELS/LEVEL_00/UNIT_01.BIN", parse_unit_container_header)
    try_census("LEVELS/LEVEL_00/STG_0001/STUNIT01.BIN", parse_unit_container_header)
    return out


if __name__ == "__main__":
    print(json.dumps(census_paths(sys.argv[1]), indent=2))
