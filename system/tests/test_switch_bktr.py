"""gbox.switch_bktr: the BKTR relocation/subsection tables, on synthetic blocks (the real vector is the RE6 update).

The layout is the one measured on 01002A000CD48800 v131072: a 0x4000 block header, the bucket at 0x4000, relocation
entries packed at 0x14 and subsection entries at 0x10.
"""
import struct

from gbox import switch_bktr as B


def relocation_block(entries) -> bytes:
    block = bytearray(0x8000)
    struct.pack_into("<IIQ", block, 0, 0, 1, len(entries) and entries[-1][0] or 0)
    struct.pack_into("<IIQ", block, 0x4000, 0, len(entries), entries[-1][0] if entries else 0)
    for i, (virt, phys, is_patch) in enumerate(entries):
        struct.pack_into("<QQI", block, 0x4010 + i * 0x14, virt, phys, is_patch)
    return bytes(block)


def subsection_block(entries) -> bytes:
    block = bytearray(0x8000)
    struct.pack_into("<IIQ", block, 0, 0, 1, entries[-1][0] if entries else 0)
    struct.pack_into("<IIQ", block, 0x4000, 0, len(entries), entries[-1][0] if entries else 0)
    for i, (offset, ctr_val) in enumerate(entries):
        struct.pack_into("<QII", block, 0x4010 + i * 0x10, offset, 0, ctr_val)
    return bytes(block)


def test_relocation_entries_and_patch_regions():
    entries = [(0x0, 0x0, 1), (0x200, 0x200, 0), (0x400, 0x200, 1), (0x900, 0x700, 0)]
    parsed = B.parse_relocation(relocation_block(entries))
    assert [e["virt"] for e in parsed] == [0x0, 0x200, 0x400, 0x900]
    assert [e["is_patch"] for e in parsed] == [True, False, True, False]
    regions = B.patch_regions(parsed, virtual_end=0x1000)
    assert regions == [{"virt": 0x0, "end": 0x200, "phys": 0x0, "size": 0x200},
                       {"virt": 0x400, "end": 0x900, "phys": 0x200, "size": 0x500}]
    assert B.region_at(regions, 0x300) is None and B.region_at(regions, 0x450)["phys"] == 0x200


def test_subsection_entries_and_lookup():
    parsed = B.parse_subsections(subsection_block([(0x0, 0), (0x4780200, 1)]))
    assert parsed == [{"offset": 0x0, "ctr_val": 0}, {"offset": 0x4780200, "ctr_val": 1}]
    assert B.subsection_at(parsed, 0x296AAF0)["ctr_val"] == 0
    assert B.subsection_at(parsed, 0x4780300)["ctr_val"] == 1


def test_bktr_ctr_layout():
    section_ctr = bytes.fromhex("0100000002000000")
    iv = B.bktr_ctr(section_ctr, 1, 0x4780200)
    assert iv == bytes.fromhex("00000002") + (1).to_bytes(4, "big") + (0x4780200 >> 4).to_bytes(8, "big")


def test_superblock_offsets_read_the_two_headers():
    header = bytearray(0xC00)
    base = 0x400 + 1 * 0x200 + 8
    struct.pack_into("<QQIIII", header, base + 0xE0 + 0x18, 0x4780200, 0x8000, 0x52544B42, 0, 126, 0)
    struct.pack_into("<QQIIII", header, base + 0xE0 + 0x18 + 0x20, 0x4788200, 0x8000, 0x52544B42, 0, 2, 0)
    out = B.superblock_offsets(bytes(header), 1)
    assert out["relocation"]["offset"] == 0x4780200 and out["relocation"]["count"] == 126
    assert out["subsection"]["offset"] == 0x4788200 and out["subsection"]["count"] == 2
