"""Focused tests for the DOA5LR char_dat native reader.

Validates the structural parser against both owned-source samples:
  - entry 0018 (58,484 B)  - preserved sample
  - entry 0940 (7,357,824 B) - extracted payload
"""
import hashlib
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gbox.doa5lr_char_dat import (  # noqa: E402
    CharDatError,
    extract_section,
    parse_char_dat,
)

HERE = os.path.dirname(__file__)
SAMPLE18 = "/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/char_entry_0018.payload.bin"
SAMPLE940 = os.path.join(HERE, "..", "inventory", "doa5lr", "evidence", "char_entry_0940.char_dat")


def _load(path):
    return open(path, "rb").read()


def test_entry0018_structure():
    d = _load(SAMPLE18)
    assert len(d) == 58484
    info = parse_char_dat(d)
    assert info["sha256"] == hashlib.sha256(d).hexdigest()
    assert info["byte_order"] == "big-endian"
    # header invariants
    assert info["outer_header"]["hdr_size"] == 48
    assert info["outer_header"]["data_ptr"] == 0x40
    assert info["inner_header"]["n_sections"] == 7
    assert info["inner_header"]["n_entries"] == 6
    # section bounds (verified topology)
    sec = info["sections"]
    # n_sec=7: 5 active pointers + 1 null + 1 count => 5 sections,
    # plus the leading data region (0x10..first ptr) = 6 ranges
    assert len(sec) == 6
    assert sec[0]["start"] == 0x10
    assert sec[0]["end"] == 0xBB40
    assert sec[1]["size"] == 32      # 8 u32 record
    assert sec[2]["size"] == 272     # 136 u16
    assert sec[3]["size"] == 512     # 128 u32
    assert sec[4]["size"] == 64      # 32 u32
    assert sec[5]["end"] == len(d)   # trailing data ends at EOF
    # block tables: 6 consecutive
    bt = info["block_tables"]
    assert [b["start"] for b in bt] == [0x310, 0x400, 0x510, 0x5C0, 0x6E0, 0x7F0]
    assert bt[0]["u16_count"] == 120
    assert bt[1]["u16_count"] == 136
    assert bt[2]["u16_count"] == 88
    assert bt[3]["u16_count"] == 144
    assert bt[4]["u16_count"] == 136
    assert bt[5]["u16_count"] == 144
    # block5 ends at the extra-table marker; extra table runs to geometry
    assert bt[5]["end"] == 0x910
    assert info["extra_table"]["start"] == 0x910
    assert info["extra_table"]["end"] == info["geometry_table"]["start"]
    return info


def test_entry0940_structure():
    d = _load(SAMPLE940)
    assert len(d) == 7357824
    info = parse_char_dat(d)
    assert info["sha256"] == hashlib.sha256(d).hexdigest()
    # same header invariants as 0018
    assert info["outer_header"]["hdr_size"] == 48
    assert info["inner_header"]["n_sections"] == 7
    assert info["inner_header"]["n_entries"] == 6
    sec = info["sections"]
    # small record sections identical in size
    assert sec[1]["size"] == 32
    assert sec[2]["size"] == 272
    assert sec[3]["size"] == 512
    assert sec[4]["size"] == 64
    assert sec[5]["end"] == len(d)
    # geometry/texture topology: geometry < texture < sec0
    assert info["geometry_table"]["start"] == 0x63C0
    assert info["texture_table"]["start"] == 0xB6E0
    assert info["texture_table"]["end"] == sec[0]["end"]
    assert info["geometry_table"]["start"] < info["texture_table"]["start"]
    # block tables: 6 consecutive, each multiple of 2 bytes
    bt = info["block_tables"]
    assert len(bt) == 6
    for b in bt:
        assert b["size"] % 2 == 0
        assert b["start"] < b["end"]
    # block0 is first, before geometry
    assert bt[0]["start"] == 0x310
    assert bt[0]["end"] == 0x460
    # block5 ends at the extra-table marker (0xC30), not at geometry
    assert bt[5]["end"] == 0xC30
    assert info["extra_table"]["start"] == 0xC30
    assert info["extra_table"]["end"] == info["geometry_table"]["start"]
    return info


def test_rejects_corrupt_magic():
    d = bytearray(_load(SAMPLE18))
    d[0] = 0x00
    try:
        parse_char_dat(bytes(d))
        assert False, "expected CharDatError"
    except CharDatError:
        pass


def test_rejects_truncated():
    d = _load(SAMPLE18)
    try:
        parse_char_dat(d[:100])
        assert False, "expected CharDatError"
    except CharDatError:
        pass


def test_extract_section_roundtrip():
    d = _load(SAMPLE18)
    info = parse_char_dat(d)
    # sec2 (136 u16 table) extracted byte-exact
    raw = extract_section(d, 2)
    assert len(raw) == 272
    assert raw == d[0xBB60:0xBC70]
    # trailing data
    raw5 = extract_section(d, 5)
    assert len(raw5) == info["trailing_data"]["size"]
    assert raw5 == d[info["trailing_data"]["start"]:]
    return True


def test_block0_sparse_pattern():
    """Block0 uses sparse (0/offset) u16 pairs - verify the pattern holds."""
    d = _load(SAMPLE18)
    b0 = struct.unpack_from(">120H", d, 0x310)
    evens = [b0[2 * k] for k in range(60)]
    odds = [b0[2 * k + 1] for k in range(60)]
    # first 36 even entries are 0; odd entries carry small offsets (< 17000)
    assert all(e == 0 for e in evens[:36])
    assert max(odds[:36]) < 17000
    # after the sparse region, even/odd are both dense data
    assert any(e != 0 for e in evens[36:])
    return {"sha256": hashlib.sha256(d).hexdigest()}


def main():
    tests = [
        test_entry0018_structure,
        test_entry0940_structure,
        test_rejects_corrupt_magic,
        test_rejects_truncated,
        test_extract_section_roundtrip,
        test_block0_sparse_pattern,
    ]
    failed = 0
    for t in tests:
        try:
            r = t()
            print(f"PASS {t.__name__}")
            if r:
                print("  sha256:", r["sha256"][:16] + "...")
        except Exception as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
