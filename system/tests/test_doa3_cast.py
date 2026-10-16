"""Focused tests for gbox.doa3_cast: XPR0 walk, CAT sections, slot inventory,
the AFS patch path and the measured MDL geometry decoder. Fixtures mirror the
byte layout observed in the owned USA build (kas00.xpr / kas00.cat,
loadfile.afs)."""
import struct
from pathlib import Path

import pytest

from gbox import doa3_cast
from gbox.doa3_inventory import afs_table, entry_rooms, read_afs


# ----------------------------------------------------------------- fixtures

def make_xpr(mdl_size: int = 64, words: list[int] | None = None,
             total: int | None = None) -> bytes:
    """An XPR0 shaped like kas00: user-data MDL pair at 0x0C, second pair at
    0x18, descriptor count at 0x20, raw descriptor words, then the MDL payload
    and an unparsed trailing region."""
    words = words if words is not None else [0x48, 0x14C, 0x16BC, 0x3F54, 0x4190]
    hsize = 0x24 + 4 * len(words)
    mdl_end = hsize + mdl_size
    if total is None:
        total = mdl_end + 16
    out = bytearray(total)
    struct.pack_into("<4sII", out, 0, b"XPR0", total, hsize)
    struct.pack_into("<II", out, 12, 0x80000000, mdl_size)
    out[20:24] = b"MDL\x00"
    struct.pack_into("<II", out, 0x18, 0x48, 87)
    struct.pack_into("<I", out, 0x20, len(words))
    for i, w in enumerate(words):
        struct.pack_into("<I", out, 0x24 + 4 * i, w)
    out[hsize:hsize + mdl_size] = bytes((i * 7) & 0xFF for i in range(mdl_size))
    return bytes(out)


def make_cat(header: tuple[int, ...] | None = None) -> bytes:
    """A CAT companion shaped like kas00: 8 header words and a LNK marker."""
    header = header or (1, 0x14, 0x5C0, 0x9A40, 0x4F5C0, 0x100, 1, 0x18)
    body = bytearray(max(0x9A40 + 4, header[4] + 4))
    struct.pack_into("<8I", body, 0, *header)
    body[0x9A40:0x9A44] = b"LNK\x00"
    return bytes(body)


def make_cat_lnk(size: int = 0x100, at: int = 0x9A40) -> bytes:
    """A CAT companion with a fully-formed LNK section (name + 6-word header)."""
    body = bytearray(at + 8 + 4 * doa3_cast.LNK_HEADER_WORDS + 4)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x5C0, 0x9A40, 0x4F5C0, 0x100, 1, 0x18)
    body[at:at + 4] = b"LNK\x00"
    body[at + 4:at + 8] = b"0100"
    struct.pack_into("<6I", body, at + 8, *doa3_cast.LNK_HEADER, size, 0, 0)
    return bytes(body)


def make_cat_lnk_body(c0: int = 9, entries: list[int] | None = None,
                      c1: int = 3, sub_offsets: list[int] | None = None,
                      size: int = 0x40000) -> bytes:
    """A CAT with a LNK section whose body holds the C0/C1 table structure."""
    at = 0x9A40
    if entries is None:
        entries = [0x28, 0xFFFFFFFF, 0x183A, 0x6242, 0xFFFFFFFF,
                   0x9AE0, 0x11A7A, 0x1A274, 0x2F1E0][:c0]
    if sub_offsets is None:
        sub_offsets = [0x522, 0x9DE, 0xE9A, 0x1356][:c1 + 1]
    bo = at + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    body = bytearray(bo + size)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x5C0, at, bo + size, 0x100, 1, 0x18)
    body[at:at + 4] = b"LNK\x00"
    body[at + 4:at + 8] = b"0100"
    struct.pack_into("<6I", body, at + 8, *doa3_cast.LNK_HEADER, size, 0, 0)
    struct.pack_into("<I", body, bo, c0)
    struct.pack_into(f"<{c0}I", body, bo + 4, *entries)
    sub = bo + 4 + 4 * c0
    struct.pack_into("<I", body, sub, c1)
    struct.pack_into(f"<{c1 + 1}I", body, sub + 4, *sub_offsets)
    return bytes(body)


def make_cat_lnk_groups(at: int = 0x9A40, size: int = 0x4000) -> bytes:
    """A CAT whose LNK body has C0 entries pointing at real link-group blocks
    ``{N, header_size=4*(N+3), N+1 cumulative lengths}``.

    Block 0 is the C1 sub-table (C0 entry 0 -> body+0x10 = 4+4*3): N=2, header
    0x14, lengths [0x40, 0x80, 0xC0]. Block 2 (C0 entry 2 -> body+0x200): N=1,
    header 0x10, lengths [0x30, 0x60]. C0 entry 1 is the -1 sentinel."""
    c0 = 3
    entries = [0x10, 0xFFFFFFFF, 0x200]
    bo = at + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    body = bytearray(bo + size)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x5C0, at, bo + size, 0x100, 1, 0x18)
    body[at:at + 4] = b"LNK\x00"
    body[at + 4:at + 8] = b"0100"
    struct.pack_into("<6I", body, at + 8, *doa3_cast.LNK_HEADER, size, 0, 0)
    struct.pack_into("<I", body, bo, c0)
    struct.pack_into(f"<{c0}I", body, bo + 4, *entries)
    # block 0 (the sub-table) at bo + 0x10
    struct.pack_into("<I", body, bo + 0x10, 2)                 # N = 2
    struct.pack_into("<I", body, bo + 0x14, 4 * (2 + 3))       # header_size = 0x14
    struct.pack_into("<3I", body, bo + 0x18, 0x40, 0x80, 0xC0)  # N+1 = 3 lengths
    # block 2 at bo + 0x200
    struct.pack_into("<I", body, bo + 0x200, 1)                # N = 1
    struct.pack_into("<I", body, bo + 0x204, 4 * (1 + 3))      # header_size = 0x10
    struct.pack_into("<2I", body, bo + 0x208, 0x30, 0x60)      # N+1 = 2 lengths
    return bytes(body)


def make_cat_lnk_sections(polys: list[list[int]] | None = None,
                          residual_u16: int = 4, stride: int = 24,
                          n_sections: int = 2, at: int = 0x9A40,
                          size: int = 0x4000) -> bytes:
    """A CAT whose LNK body has one link-group block (also the C1 sub-table)
    with a data region shaped like the measured kas00 blocks: a link table
    (count-prefixed polygon list + zero terminator + residual) followed by
    N equal-length flat u16 triangle sections (stride bytes, a multiple of 6).

    The single C0 entry (index 0) points at ``body + 8`` (the C1 sub-table the
    body parser reads), so the block header ``{N, header_size, N+1 lengths}``
    must satisfy ``header_size < lens[0] < lens[1] < ...`` for ``cat_lnk_body``
    to accept it - hence the default link table is larger than ``4*(N+3)``.
    """
    bo = at + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    polys = polys if polys is not None else [[5, 6], [7, 8, 9]]
    table = []
    for p in polys:
        table.append(len(p))
        table += p
    table.append(0)                      # polygon-list terminator
    table += [0] * residual_u16          # unresolved residual u16
    link_table_bytes = 2 * len(table)
    N = n_sections
    header_size = 4 * (N + 3)
    if link_table_bytes <= header_size:
        raise ValueError("fixture link table must exceed the block header size")
    lens = [link_table_bytes]
    for _ in range(n_sections):
        lens.append(lens[-1] + stride)
    block = bo + 8                       # C0 entry 0 -> body + 8 (the C1 sub-table)
    body = bytearray(bo + size)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x5C0, at, bo + size, 0x100, 1, 0x18)
    body[at:at + 4] = b"LNK\x00"
    body[at + 4:at + 8] = b"0100"
    struct.pack_into("<6I", body, at + 8, *doa3_cast.LNK_HEADER, size, 0, 0)
    struct.pack_into("<I", body, bo, 1)          # C0 = 1
    struct.pack_into("<I", body, bo + 4, 8)      # entry 0 -> body + 8
    struct.pack_into("<I", body, block, N)
    struct.pack_into("<I", body, block + 4, header_size)
    struct.pack_into(f"<{N + 1}I", body, block + 8, *lens)
    data_start = block + header_size
    struct.pack_into(f"<{len(table)}H", body, data_start, *table)
    tri = [1, 2, 3, 2, 3, 4] * (stride // 6)
    for k in range(N):
        struct.pack_into(f"<{len(tri)}H", body,
                         data_start + link_table_bytes + k * stride, *tri)
    return bytes(body)


def make_afs(entries: list[bytes]) -> bytes:
    """Minimal AFS without a CRI name directory: header, offset/size table, data."""
    n = len(entries)
    head_len = 16 + 8 * n
    offsets, sizes, cur = [], [], head_len
    for blob in entries:
        offsets.append(cur)
        sizes.append(len(blob))
        cur += len(blob)
    out = bytearray(cur)
    struct.pack_into("<4sI", out, 0, b"AFS\x00", n)
    for i, (o, s) in enumerate(zip(offsets, sizes)):
        struct.pack_into("<II", out, 8 + 8 * i, o, s)
    for blob, o in zip(entries, offsets):
        out[o:o + len(blob)] = blob
    return bytes(out)


def make_manifest() -> dict:
    """Two complete families, one family with a missing cat, one costume-less."""
    return {"game_id": "b8edf7040116f3aa", "title": "Dead or Alive 3 (USA)",
            "roster_expected": doa3_cast.ROSTER,
            "fighter_families": [
                {"nick": "kasumi", "code": "kas", "mot": ["kasumi.mot", "m_kasumi.mot"],
                 "costumes": {"kas00": {"xpr": 1, "cat": 2}, "kas01": {"xpr": 3, "cat": 4}},
                 "complete_costumes": ["kas00", "kas01"]},
                {"nick": "tina", "code": "tin", "mot": ["tina.mot"],
                 "costumes": {"tin00": {"xpr": 5, "cat": 6}, "tin01": {"xpr": 7}},
                 "complete_costumes": ["tin00"]},
                {"nick": "tengu", "code": None, "mot": [], "costumes": {},
                 "complete_costumes": []},
            ]}


def make_geo_xpr(vcount: int = 4, icount: int = 6, mat_face_off: int = 0,
                 mat_face_count: int | None = None, flags: int = 0x80000000,
                 ref: int = 0x25, tail: int = 0, packets_extra: int = 1) -> bytes:
    """An XPR0 with one OBJ shaped like the measured kas00 record: pinned
    fields at OBJ+0x10..+0x1F, a material chain from OBJ+0x60 ending in
    [0x00000000, 0x12345678] exactly 8 bytes before the u16 strip buffer, and
    a 32-byte f32x8 vertex buffer starting at header_size."""
    mat_face_count = icount - 2 if mat_face_count is None else mat_face_count
    length_words = doa3_cast.MAT_HEADER_WORDS + 4 * (packets_extra + 1)
    obj = 0x30                                            # table_end (0x2C) + 4
    mat_off = obj + doa3_cast.MAT_HEADER_BASE
    iptr = mat_off + 4 * length_words + 8
    hsize = iptr + 2 * icount
    total = hsize + 32 * vcount + 8
    out = bytearray(total)
    struct.pack_into("<4sII", out, 0, b"XPR0", total, hsize)
    struct.pack_into("<II", out, 12, 0x80000000, 32 * vcount)
    out[0x14:0x18] = b"MDL\x00"
    struct.pack_into("<4I", out, 0x18, 1, 0, 1, 1)   # obj, tex, unk, dup
    struct.pack_into("<I", out, 0x28, obj)           # object pointer table
    struct.pack_into("<I", out, 0x2C, 0)             # zero table terminator
    out[obj:obj + 4] = b"OBJ\x00"
    struct.pack_into("<4I", out, obj + 0x10, vcount, hsize, icount, iptr)
    m = mat_off
    header_words = [flags, length_words] + [0x3F800000 + i for i in range(31)]
    struct.pack_into(f"<{doa3_cast.MAT_HEADER_WORDS}I", out, m, *header_words)
    pkt = m + 4 * doa3_cast.MAT_HEADER_WORDS
    for i in range(packets_extra):
        struct.pack_into("<4I", out, pkt + 16 * i, 0x80, 0, 0, 0)  # zero-face packets
    struct.pack_into("<4I", out, pkt + 16 * packets_extra, ref, mat_face_off,
                     mat_face_count, tail)
    mend = m + 4 * length_words
    out[mend:mend + 4] = b"\x00\x00\x00\x00"
    struct.pack_into("<I", out, mend + 4, doa3_cast.MAT_TERMINATOR)
    struct.pack_into(f"<{icount}H", out, iptr, *[i % vcount for i in range(icount)])
    verts = []
    for i in range(vcount):
        verts += [float(i), float(i), 0.0, 0.0, 0.0, 1.0, 0.0, float(i) / vcount]
    struct.pack_into(f"<{8 * vcount}f", out, hsize, *verts)
    return bytes(out)


# ----------------------------------------------------------------- XPR0

def test_xpr_resources_mirrors_observed_layout():
    blob = make_xpr()
    res = doa3_cast.xpr_resources(blob)
    assert res["magic"] == "XPR0"
    assert res["header_size"] == 0x38
    assert res["mdl"] == {"type": 0x80000000, "size": 64, "tag": "MDL",
                          "offset": 0x38, "end": 0x78}
    assert res["second_pair"] == {"type": 0x48, "size": 87}
    assert res["descriptor_count"] == 5
    assert res["descriptor_words"] == [0x48, 0x14C, 0x16BC, 0x3F54, 0x4190]
    assert res["trailing_size"] == 16
    assert doa3_cast.xpr_mdl(blob)[0] == 0 and len(doa3_cast.xpr_mdl(blob)) == 64


def test_xpr_resources_rejects_non_xpr():
    with pytest.raises(ValueError, match="not an XPR0"):
        doa3_cast.xpr_resources(b"\x00" * 0x30)


def test_xpr_resources_rejects_mdl_outside_resource():
    blob = make_xpr(mdl_size=64, total=0x60)   # mdl_end 0x78 > total 0x60
    with pytest.raises(ValueError, match="outside the resource"):
        doa3_cast.xpr_resources(blob)


def test_xpr_resources_rejects_non_mdl_tag():
    blob = bytearray(make_xpr())
    blob[20:24] = b"ZZZZ"
    with pytest.raises(ValueError, match="tag"):
        doa3_cast.xpr_resources(bytes(blob))


def test_xpr_resources_caps_descriptor_words():
    blob = make_xpr(words=[0] * 5000)  # header larger than the descriptor window
    res = doa3_cast.xpr_resources(blob)
    assert res["descriptor_count"] == 5000
    assert len(res["descriptor_words"]) == doa3_cast.MAX_HEADER_WORDS


# ----------------------------------------------------------------- CAT

def test_cat_sections_mirrors_observed_header_and_marker():
    res = doa3_cast.cat_sections(make_cat())
    assert res["version"] == 1
    assert res["header"][0] == 0x14
    assert res["header"][1] == 0x5C0
    assert res["lnk_markers"] == [0x9A40]
    assert res["layout"] == "offsets"
    assert res["lnk_offset_hint"] == 0x9A40
    assert res["fixed"] == [0x100, 1, 0x18]
    assert res["section_offsets"] == [0x14, 0x5C0, 0x9A40, 0x4F5C0]


def test_cat_sections_rejects_missing_fixed_signature():
    # word@0x14 must be 0x100 and word@0x18 must be 1 on every measured costume;
    # a first word of 2 alone is not a valid rejection reason anymore.
    with pytest.raises(ValueError, match="signature"):
        doa3_cast.cat_sections(make_cat(header=(2, 0x14, 1, 1, 1, 1, 1, 1)))


def test_cat_sections_accepts_id_block_layout():
    # Type-B costumes (zack, tina, ayane, ...) store an unresolved 20-byte ID
    # block in the first five words; they must not be rejected as "wrong version".
    body = make_cat(header=(0xB041D1, 0x5821A, 0x3EAEE, 0x2539A, 0x6F9AE,
                            0x100, 1, 0x18))
    res = doa3_cast.cat_sections(body)
    assert res["layout"] == "id_block"
    assert res["id_block"] == [0xB041D1, 0x5821A, 0x3EAEE, 0x2539A, 0x6F9AE]
    assert "lnk_offset_hint" not in res
    assert res["lnk_markers"] == [0x9A40]


def test_cat_sections_rejects_mismatched_lnk_hint():
    body = make_cat(header=(1, 0x14, 0x5C0, 0x9A40 + 4, 0x4F5C0, 0x100, 1, 0x18))
    with pytest.raises(ValueError, match="does not match"):
        doa3_cast.cat_sections(body)


def test_cat_sections_without_markers():
    body = bytearray(0x30)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x18, 0x20, 0x24, 0x100, 1, 0x18)
    res = doa3_cast.cat_sections(bytes(body))
    assert res["lnk_markers"] == []
    assert res["layout"] == "offsets"
    assert res["lnk_offset_hint"] == 0x20


def test_cat_lnk_decodes_pinned_header():
    res = doa3_cast.cat_lnk(make_cat_lnk(size=0x100))
    assert res is not None
    assert res["offset"] == 0x9A40
    assert res["name"] == "0100"
    assert res["header"] == [2, 16, 32, 0x100, 0, 0]
    assert res["size"] == 0x100
    assert res["body_offset"] == 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS


def test_cat_lnk_absent_returns_none():
    body = bytearray(0x30)
    struct.pack_into("<8I", body, 0, 1, 0x14, 1, 0x20, 1, 0x100, 1, 0x18)
    assert doa3_cast.cat_lnk(bytes(body)) is None


def test_cat_lnk_rejects_truncated_section():
    # LNK marker at the very end with no room for the name/header after it.
    body = bytearray(0x9A40 + 4)
    struct.pack_into("<8I", body, 0, 1, 0x14, 0x5C0, 0x9A40, 0x9A44, 0x100, 1, 0x18)
    body[0x9A40:0x9A44] = b"LNK\x00"
    with pytest.raises(ValueError, match="truncated"):
        doa3_cast.cat_lnk(bytes(body))


def test_cat_lnk_rejects_bad_name():
    body = bytearray(make_cat_lnk())
    body[0x9A40 + 4:0x9A40 + 8] = b"0200"
    with pytest.raises(ValueError, match="name"):
        doa3_cast.cat_lnk(bytes(body))


def test_cat_lnk_rejects_bad_header():
    body = bytearray(make_cat_lnk())
    struct.pack_into("<I", body, 0x9A40 + 8, 3)   # first header word must be 2
    with pytest.raises(ValueError, match="header"):
        doa3_cast.cat_lnk(bytes(body))


def test_cat_lnk_rejects_unaligned_size():
    body = bytearray(make_cat_lnk())
    struct.pack_into("<I", body, 0x9A40 + 8 + 12, 0x101)
    with pytest.raises(ValueError, match="4-aligned"):
        doa3_cast.cat_lnk(bytes(body))


def test_cat_lnk_body_decodes_structure():
    res = doa3_cast.cat_lnk_body(make_cat_lnk_body())
    assert res is not None
    assert res["link_group_count"] == 9
    assert res["link_group_entries"][0] == 0x28
    assert res["link_group_entries"][1] == 0xFFFFFFFF
    assert res["sub_table_offset"] == 4 + 4 * 9
    assert res["sub_table_count"] == 3
    assert res["sub_table_offsets"] == [0x522, 0x9DE, 0xE9A, 0x1356]


def test_cat_lnk_body_absent_returns_none():
    body = bytearray(0x30)
    struct.pack_into("<8I", body, 0, 1, 0x14, 1, 0x20, 1, 0x100, 1, 0x18)
    assert doa3_cast.cat_lnk_body(bytes(body)) is None


def test_cat_lnk_body_rejects_zero_group_count():
    body = bytearray(make_cat_lnk_body())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    struct.pack_into("<I", body, bo, 0)
    with pytest.raises(ValueError, match="link-group count"):
        doa3_cast.cat_lnk_body(bytes(body))


def test_cat_lnk_body_rejects_out_of_body_offset():
    body = make_cat_lnk_body(entries=[0x28, 0xFFFFFFFF, 0x183A, 0x6242, 0xFFFFFFFF,
                                      0x9AE0, 0x11A7A, 0x1A274, 0x500000])
    with pytest.raises(ValueError, match="exceeds"):
        doa3_cast.cat_lnk_body(body)


def test_cat_lnk_body_rejects_non_increasing_sub_offsets():
    body = make_cat_lnk_body(sub_offsets=[0x522, 0x522, 0xE9A, 0x1356])
    with pytest.raises(ValueError, match="strictly increasing"):
        doa3_cast.cat_lnk_body(body)


def test_cat_lnk_body_rejects_sub_offsets_exceeding_size():
    body = make_cat_lnk_body(sub_offsets=[0x522, 0x9DE, 0xE9A, 0x500000])
    with pytest.raises(ValueError, match="exceeds"):
        doa3_cast.cat_lnk_body(body)


# ----------------------------------------------------------------- LNK groups

def test_cat_lnk_groups_decodes_blocks():
    res = doa3_cast.cat_lnk_groups(make_cat_lnk_groups())
    assert res is not None
    assert res["link_group_count"] == 3
    by_index = {g["index"]: g for g in res["groups"]}
    assert by_index[1] == {"index": 1, "present": False}
    g0 = by_index[0]
    assert g0["present"] and g0["count"] == 2
    assert g0["header_size"] == 4 * (2 + 3)
    assert g0["data_offsets"] == [0x40, 0x80, 0xC0]
    assert g0["data_bytes"] == 0xC0
    g2 = by_index[2]
    assert g2["present"] and g2["count"] == 1
    assert g2["header_size"] == 4 * (1 + 3)
    assert g2["data_offsets"] == [0x30, 0x60]


def test_cat_lnk_groups_absent_returns_none():
    body = bytearray(0x30)
    struct.pack_into("<8I", body, 0, 1, 0x14, 1, 0x20, 1, 0x100, 1, 0x18)
    assert doa3_cast.cat_lnk_groups(bytes(body)) is None


def test_cat_lnk_groups_rejects_bad_header_size():
    body = bytearray(make_cat_lnk_groups())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    struct.pack_into("<I", body, bo + 0x14, 0x18)   # block 0 header_size 0x18 != 0x14
    with pytest.raises(ValueError, match="header size"):
        doa3_cast.cat_lnk_groups(bytes(body))


def test_cat_lnk_groups_rejects_non_increasing_lengths():
    body = bytearray(make_cat_lnk_groups())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    struct.pack_into("<3I", body, bo + 0x18, 0x40, 0x40, 0xC0)
    with pytest.raises(ValueError, match="strictly increasing"):
        doa3_cast.cat_lnk_groups(bytes(body))


def test_cat_lnk_groups_rejects_lengths_exceeding_body():
    body = bytearray(make_cat_lnk_groups())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    struct.pack_into("<3I", body, bo + 0x18, 0x40, 0x80, 0x500000)
    with pytest.raises(ValueError, match="exceeds"):
        doa3_cast.cat_lnk_groups(bytes(body))


def test_cat_lnk_groups_rejects_truncated_block():
    body = bytearray(make_cat_lnk_groups())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    # point C0 entry 2 at the last 4 bytes of the body, so the block header
    # (12 bytes) runs past the end of the file
    struct.pack_into("<I", body, bo + 4 + 4 * 2, 0x4000 - 4)
    with pytest.raises(ValueError, match="truncated"):
        doa3_cast.cat_lnk_groups(bytes(body))


# ----------------------------------------------------------------- LNK sections

def test_cat_lnk_sections_decodes_partition():
    res = doa3_cast.cat_lnk_sections(make_cat_lnk_sections())
    assert res is not None
    assert res["link_group_count"] == 1
    g = res["groups"][0]
    assert g["present"] and g["index"] == 0
    assert g["link_table_bytes"] == 24
    assert g["polygon_count"] == 2
    assert g["polygons"] == [[5, 6], [7, 8, 9]]
    assert g["link_table_residual_bytes"] == 8
    assert g["link_sections"] == 2
    assert g["link_section_stride"] == 24
    assert g["triangles_per_section"] == 4


def test_cat_lnk_sections_absent_returns_none():
    body = bytearray(0x30)
    struct.pack_into("<8I", body, 0, 1, 0x14, 1, 0x20, 1, 0x100, 1, 0x18)
    assert doa3_cast.cat_lnk_sections(bytes(body)) is None


def test_cat_lnk_sections_rejects_unequal_strides():
    body = bytearray(make_cat_lnk_sections())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    block = bo + 8
    struct.pack_into("<I", body, block + 8 + 2 * 4, 78)   # lens[2]: 48..78 = 30 vs 24..48 = 24
    with pytest.raises(ValueError, match="not equal length"):
        doa3_cast.cat_lnk_sections(bytes(body))


def test_cat_lnk_sections_rejects_non_triangle_stride():
    body = bytearray(make_cat_lnk_sections())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    block = bo + 8
    struct.pack_into("<I", body, block + 8 + 4, 46)       # lens[1]: stride 22
    struct.pack_into("<I", body, block + 8 + 8, 68)       # lens[2]: stride 22
    with pytest.raises(ValueError, match="not a whole number of triangles"):
        doa3_cast.cat_lnk_sections(bytes(body))


def test_cat_lnk_sections_rejects_unaligned_link_table():
    body = bytearray(make_cat_lnk_sections())
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    block = bo + 8
    struct.pack_into("<I", body, block + 8, 25)           # lens[0] odd (> header_size)
    with pytest.raises(ValueError, match="u16-aligned"):
        doa3_cast.cat_lnk_sections(bytes(body))


def test_cat_lnk_sections_rejects_unterminated_polygon_list():
    body = bytearray(make_cat_lnk_sections(polys=[[5, 6]], residual_u16=7))
    bo = 0x9A40 + 8 + 4 * doa3_cast.LNK_HEADER_WORDS
    data_start = bo + 8 + 4 * (2 + 3)                     # block + header_size (20)
    struct.pack_into("<H", body, data_start + 6, 300)     # terminator u16[3] -> n=300
    with pytest.raises(ValueError, match="beyond"):
        doa3_cast.cat_lnk_sections(bytes(body))


def test_cat_sections_rejects_non_increasing_offsets():
    body = make_cat(header=(1, 0x14, 0x9A40, 0x9A40, 0x4F5C0, 0x100, 1, 0x18))
    with pytest.raises(ValueError, match="increasing"):
        doa3_cast.cat_sections(body)


# ----------------------------------------------------------------- slots

def test_slot_inventory_counts_and_gaps():
    inv = doa3_cast.slot_inventory(make_manifest())
    assert inv["slot_count"] == 3
    assert inv["costume_total"] == 3
    by_nick = {s["nick"]: s for s in inv["slots"]}
    assert by_nick["kasumi"]["costume_count"] == 2
    assert by_nick["tina"]["costume_count"] == 1
    assert by_nick["tengu"]["costume_count"] == 0 and by_nick["tengu"]["hidden"]
    gaps = {(g["slot"], g["kind"]) for g in inv["coverage_gaps"]}
    assert ("tina", "no_complete_costumes") not in gaps  # tin00 is complete
    assert ("tengu", "no_complete_costumes") in gaps
    assert ("tengu", "display_name_pending") in gaps
    assert inv["display_mapping"] == "pending"
    assert inv["unlock_all"] == "pending"


def test_cast_writer_status_is_honest():
    st = doa3_cast.cast_writer_status()
    assert st["xpr0_parser"] and st["cat_parser"] and st["afs_patch_path"]
    assert st["mdl_geometry_decode"] and st["mdl_geometry_encode"]
    assert st["mdl_descriptor_table"]
    assert st["cat_lnk_groups"]
    assert st["cat_lnk_sections"]
    assert st["bin_body_header"]
    assert "no-op" in st["mdl_geometry_encode_note"]
    assert not st["donor_retarget"] and not st["playable"]


# ----------------------------------------------------------------- AFS patch

def test_afs_patch_entry_roundtrip(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 32, b"C" * 16]))
    before = afs.read_bytes()
    doa3_cast.afs_patch_entry(afs, 1, b"X" * 20)
    after = afs.read_bytes()
    assert len(after) == len(before)                       # in place, same layout
    table = afs_table(after, len(after))
    assert table["sizes"][1] == 20
    assert after[table["offsets"][1]:table["offsets"][1] + 20] == b"X" * 20
    # zero padding fills the rest of the room; neighbours are untouched
    assert after[table["offsets"][0]:table["offsets"][0] + 16] == b"A" * 16
    assert after[table["offsets"][2]:table["offsets"][2] + 16] == b"C" * 16
    rooms = entry_rooms(table["offsets"], table["sizes"], len(after))
    assert after[table["offsets"][1] + 20:table["offsets"][1] + rooms[1]] == b"\x00" * (rooms[1] - 20)


def test_afs_patch_entry_refuses_oversize_and_leaves_file(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 16]))
    before = afs.read_bytes()
    with pytest.raises(ValueError, match="exceeds the entry room"):
        doa3_cast.afs_patch_entry(afs, 0, b"X" * 64)
    assert afs.read_bytes() == before


def test_afs_patch_entry_refuses_empty_slot(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"", b"B" * 16]))
    with pytest.raises(ValueError, match="empty"):
        doa3_cast.afs_patch_entry(afs, 0, b"X")


def test_read_afs_roundtrip_sees_patched_entry(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 32]))
    doa3_cast.afs_patch_entry(afs, 1, b"Y" * 24)
    parsed = read_afs(afs)
    assert parsed["count"] == 2
    assert parsed["entries"][1]["size"] == 24
    assert parsed["entries"][1]["magic"].startswith("Y")


# ----------------------------------------------------------------- review-gap fixes

def test_xpr_resources_rejects_short_fixed_header():
    blob = make_xpr()
    with pytest.raises(ValueError, match="too short"):
        doa3_cast.xpr_resources(blob[:0x20])


def test_xpr_roundtrip_is_byte_preserving():
    blob = make_xpr(mdl_size=256, words=[0x48, 0x14C, 0x16BC, 0x3F54, 0x4190, 0x97DC])
    assert doa3_cast.xpr_roundtrip(blob) == blob


def test_xpr_resources_rejects_misaligned_header():
    blob = bytearray(make_xpr())
    struct.pack_into("<I", blob, 8, 0x39)  # header_size not 4-byte aligned
    with pytest.raises(ValueError, match="aligned"):
        doa3_cast.xpr_resources(bytes(blob))


def test_afs_patch_entry_stages_output_and_keeps_original(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 32]))
    before = afs.read_bytes()
    out = tmp_path / "loadfile.patched.afs"
    room = doa3_cast.afs_patch_entry(afs, 0, b"Z" * 8, out=out)
    assert room == 16
    assert afs.read_bytes() == before                  # source untouched
    patched = afs_table(out.read_bytes(), len(before))
    assert patched["sizes"][0] == 8
    assert out.read_bytes()[patched["offsets"][0]:patched["offsets"][0] + 8] == b"Z" * 8


def test_afs_patch_entry_refuses_source_digest_mismatch(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16]))
    before = afs.read_bytes()
    with pytest.raises(ValueError, match="digest mismatch"):
        doa3_cast.afs_patch_entry(afs, 0, b"Z" * 8, expected_sha256="0" * 64)
    assert afs.read_bytes() == before


def test_afs_patch_entry_refuses_no_source_change(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(make_afs([b"A" * 16, b"B" * 32]))
    before = afs.read_bytes()
    with pytest.raises(ValueError, match="no source change"):
        doa3_cast.afs_patch_entry(afs, 1, b"B" * 32)
    assert afs.read_bytes() == before


def test_afs_patch_entry_rejects_malformed_and_truncated(tmp_path):
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(b"NOTAFS" + bytes(64))
    with pytest.raises(ValueError, match="not an AFS"):
        doa3_cast.afs_patch_entry(afs, 0, b"X")
    afs.write_bytes(b"AFS\x00" + struct.pack("<I", 4) + struct.pack("<8I", *[0] * 8))
    with pytest.raises(ValueError, match="truncated"):
        doa3_cast.afs_patch_entry(afs, 0, b"X")


def test_afs_patch_entry_rejects_name_directory_out_of_bounds(tmp_path):
    n = 1
    head_len = 16 + 8 * n
    out = bytearray(head_len + 0x800)
    struct.pack_into("<4sI", out, 0, b"AFS\x00", n)
    struct.pack_into("<II", out, 8, head_len, 0x100)          # entry 0 inside the archive
    struct.pack_into("<II", out, 8 + 8 * n, head_len + 0x800, 48 * n)  # name dir past EOF
    afs = tmp_path / "loadfile.afs"
    afs.write_bytes(bytes(out))
    with pytest.raises(ValueError, match="name directory"):
        doa3_cast.afs_patch_entry(afs, 0, b"X")


# ----------------------------------------------------------------- MDL geometry

def test_mdl_geometry_decodes_measured_obj_layout():
    blob = make_geo_xpr()
    geo = doa3_cast.costume_geometry(blob)
    assert geo["object_count"] == 1
    assert geo["vertex_total"] == 4
    assert geo["triangle_total"] == 4                     # 6 strip indices -> 4 tris
    obj = geo["objects"][0]
    assert obj["header"][4:8] == [4, obj["vertex_offset"], 6, obj["index_offset"]]
    assert obj["vertex_offset"] == 0x30 + 0x60 + 4 * 41 + 8 + 12
    assert obj["index_offset"] == 0x30 + 0x60 + 4 * 41 + 8
    assert obj["vertex_count"] == 4 and obj["index_count"] == 6
    mat = obj["materials"][0]
    assert mat["length_words"] == 41 and mat["packet_count"] == 2
    assert mat["header"][0] == 0x80000000 and mat["header"][1] == 41
    assert mat["ref"] == 0x25 and mat["face_off"] == 0 and mat["face_count"] == 4 and mat["tail"] == 0
    assert obj["vertices"][1][:3] == (1.0, 1.0, 0.0)
    assert obj["vertices"][1][3:6] == (0.0, 0.0, 1.0)    # unit normal
    sanity = doa3_cast.vertex_sanity(geo)
    assert sanity["normal_length_mean"] == pytest.approx(1.0)
    assert sanity["normal_length_std"] == pytest.approx(0.0, abs=1e-9)


def test_xpr_geometry_roundtrip_is_byte_preserving():
    blob = make_geo_xpr()
    assert doa3_cast.xpr_geometry_roundtrip(blob) == blob


def test_geometry_roundtrip_holds_with_multi_packet_material():
    blob = make_geo_xpr(packets_extra=7, tail=1)
    assert doa3_cast.xpr_geometry_roundtrip(blob) == blob


def test_geometry_rejects_index_out_of_vertex_range():
    blob = bytearray(make_geo_xpr())
    iptr = doa3_cast.costume_geometry(bytes(blob))["objects"][0]["index_offset"]
    struct.pack_into("<H", blob, iptr + 4, 0xFFFF)       # index beyond vcount
    with pytest.raises(ValueError, match="outside the OBJ vertex range"):
        doa3_cast.costume_geometry(bytes(blob))


def test_geometry_rejects_face_range_overflow():
    blob = make_geo_xpr(mat_face_off=4, mat_face_count=6)  # 4+6 > icount 6
    with pytest.raises(ValueError, match="exceeds the OBJ index count"):
        doa3_cast.costume_geometry(blob)


def test_geometry_rejects_bad_terminator():
    blob = bytearray(make_geo_xpr())
    geo = doa3_cast.costume_geometry(bytes(blob))["objects"][0]
    mend = geo["index_offset"] - 4
    struct.pack_into("<I", blob, mend, 0xDEADBEEF)
    with pytest.raises(ValueError, match="terminated"):
        doa3_cast.costume_geometry(bytes(blob))


def test_geometry_rejects_material_length_not_33_plus_4_packets():
    blob = bytearray(make_geo_xpr())
    m = doa3_cast.costume_geometry(bytes(blob))["objects"][0]["materials"][0]["offset"]
    struct.pack_into("<I", blob, m + 4, 34)              # 34-33 = 1 not divisible by 4
    with pytest.raises(ValueError, match="33 \\+ 4\\*packets"):
        doa3_cast.costume_geometry(bytes(blob))


def test_geometry_rejects_missing_presence_bit():
    blob = make_geo_xpr(flags=0x01)  # nonzero flags, 0x80 presence bit cleared
    with pytest.raises(ValueError, match="presence bit"):
        doa3_cast.costume_geometry(blob)


def test_geometry_rejects_truncated_vertex_buffer():
    blob = bytearray(make_geo_xpr())
    struct.pack_into("<I", blob, 0x30 + 0x10, 10_000)  # vcount grows past the file
    with pytest.raises(ValueError, match="vertex buffer extends outside"):
        doa3_cast.costume_geometry(bytes(blob))


def test_export_obj_writes_measured_groups(tmp_path):
    geo = doa3_cast.costume_geometry(make_geo_xpr())
    out = tmp_path / "geo.obj"
    faces = doa3_cast.export_obj(geo, out)
    text = out.read_text()
    assert faces == 4
    assert "o OBJ_0" in text and "g OBJ_0_mat_" in text
    assert text.count("\nv ") == 4 and text.count("\nvn ") == 4
    assert text.count("\nf ") == 4


def test_mdl_chunk_rejects_non_increasing_object_table():
    blob = bytearray(make_geo_xpr())
    struct.pack_into("<I", blob, 0x18, 2)              # obj_count 2
    struct.pack_into("<I", blob, 0x24, 2)              # dup 2
    struct.pack_into("<2I", blob, 0x28, 0x2C, 0x2C)    # non-increasing table
    with pytest.raises(ValueError, match="strictly increasing"):
        doa3_cast.mdl_chunk(bytes(blob))


# ----------------------------------------------------------------- MDL data descriptors

def make_descriptor_xpr(vcount: int = 4, icount: int = 6,
                        tex_sizes: tuple[int, ...] = (0x40, 0x20)) -> bytes:
    """An XPR0 with one OBJ and a valid header-tail descriptor table: one
    vertex descriptor {0x00800001, 0, 0}, len(tex_sizes) texture descriptors
    {0x00040001, cumulative_offset, 0, format, 0}, a 0xFFFFFFFF terminator and
    0xAD fill, then a vertex buffer and the texture data region."""
    ntex = len(tex_sizes)
    mat_face_count = icount - 2
    length_words = doa3_cast.MAT_HEADER_WORDS + 4 * 2   # extra packet + face packet
    obj = 0x30
    mat_off = obj + doa3_cast.MAT_HEADER_BASE
    iptr = mat_off + 4 * length_words + 8
    tail = doa3_cast.VERTEX_DESC_BYTES + doa3_cast.TEXTURE_DESC_BYTES * ntex + 4
    hsize = iptr + 2 * icount + tail
    vertex_bytes = 32 * vcount
    gap = 0x20
    total = hsize + vertex_bytes + gap + sum(tex_sizes)
    out = bytearray(total)
    struct.pack_into("<4sII", out, 0, b"XPR0", total, hsize)
    struct.pack_into("<II", out, 12, 0x80000000, vertex_bytes)
    out[0x14:0x18] = b"MDL\x00"
    struct.pack_into("<4I", out, 0x18, 1, ntex, 1, 1)  # obj=1, tex=ntex, unk=1, dup=1
    struct.pack_into("<I", out, 0x28, obj)
    struct.pack_into("<I", out, 0x2C, 0)
    out[obj:obj + 4] = b"OBJ\x00"
    struct.pack_into("<4I", out, obj + 0x10, vcount, hsize, icount, iptr)
    m = mat_off
    header_words = [0x80000000, length_words] + [0x3F800000 + i for i in range(31)]
    struct.pack_into(f"<{doa3_cast.MAT_HEADER_WORDS}I", out, m, *header_words)
    pkt = m + 4 * doa3_cast.MAT_HEADER_WORDS
    struct.pack_into("<4I", out, pkt, 0x80, 0, 0, 0)              # zero-face packet
    struct.pack_into("<4I", out, pkt + 16, 0x25, 0, mat_face_count, 0)  # face packet
    mend = m + 4 * length_words
    out[mend:mend + 4] = b"\x00\x00\x00\x00"
    struct.pack_into("<I", out, mend + 4, doa3_cast.MAT_TERMINATOR)
    struct.pack_into(f"<{icount}H", out, iptr, *[i % vcount for i in range(icount)])
    p = iptr + 2 * icount                                  # header tail begins at last_end
    struct.pack_into("<3I", out, p, doa3_cast.VERTEX_DESC_FLAG, 0, 0)
    p += doa3_cast.VERTEX_DESC_BYTES
    cum = vertex_bytes + gap
    for sz in tex_sizes:
        struct.pack_into("<5I", out, p, doa3_cast.TEXTURE_DESC_FLAG, cum, 0, 0x06710F2A, 0)
        cum += sz
        p += doa3_cast.TEXTURE_DESC_BYTES
    struct.pack_into("<I", out, p, doa3_cast.DESC_TERMINATOR)
    p += 4
    out[p:hsize] = bytes([doa3_cast.DESC_PAD_BYTE]) * (hsize - p)
    verts = []
    for i in range(vcount):
        verts += [float(i), float(i), 0.0, 0.0, 0.0, 1.0, 0.0, float(i) / vcount]
    struct.pack_into(f"<{8 * vcount}f", out, hsize, *verts)
    return bytes(out)


def test_mdl_descriptor_table_parses_vertex_and_texture():
    blob = make_descriptor_xpr(tex_sizes=(0x40, 0x20))
    table = doa3_cast.mdl_descriptor_table(blob)
    assert table["vertex_descriptors"] == [0]
    assert table["vertex_byte_total"] == 4 * 32
    assert table["texture_count"] == 2
    assert table["first_texture_gap"] == 0x20
    assert table["last_texture_size"] == 0x20
    assert table["texture_descriptors"][0]["offset"] == 4 * 32 + 0x20
    assert table["texture_descriptors"][1]["offset"] == 4 * 32 + 0x20 + 0x40
    assert table["texture_descriptors"][0]["format"] == 0x06710F2A
    assert table["pad_is_ad_fill"] and table["pad_bytes"] >= 0


def test_mdl_descriptor_table_offsets_match_vertex_chain():
    # three OBJs worth of vertices is exercised through cumulative checks; use a
    # single-OBJ fixture and confirm the vertex offset equals the running total.
    blob = make_descriptor_xpr(vcount=8, icount=6, tex_sizes=(0x80,))
    table = doa3_cast.mdl_descriptor_table(blob)
    assert table["vertex_descriptors"] == [0]
    assert table["vertex_byte_total"] == 8 * 32
    assert table["last_texture_size"] == 0x80


def test_mdl_descriptor_table_rejects_missing_terminator():
    blob = bytearray(make_descriptor_xpr(tex_sizes=(0x40,)))
    table = doa3_cast.mdl_descriptor_table(bytes(blob))
    term = table["terminator_offset"]
    struct.pack_into("<I", blob, term, 0xDEADBEEF)
    with pytest.raises(ValueError, match="terminated"):
        doa3_cast.mdl_descriptor_table(bytes(blob))


def test_mdl_descriptor_table_rejects_tex_count_mismatch():
    blob = bytearray(make_descriptor_xpr(tex_sizes=(0x40,)))
    struct.pack_into("<I", blob, 0x1C, 3)              # tex_count 3 vs 1 descriptor
    with pytest.raises(ValueError, match="texture descriptor count"):
        doa3_cast.mdl_descriptor_table(bytes(blob))


def test_mdl_descriptor_table_rejects_nonzero_pad_words():
    blob = bytearray(make_descriptor_xpr(tex_sizes=(0x40,)))
    table = doa3_cast.mdl_descriptor_table(bytes(blob))
    # last descriptor is 20 bytes before the terminator; zero_b is its 5th word.
    p = table["terminator_offset"] - doa3_cast.TEXTURE_DESC_BYTES + 16
    struct.pack_into("<I", blob, p, 1)
    with pytest.raises(ValueError, match="pad words"):
        doa3_cast.mdl_descriptor_table(bytes(blob))


def test_mdl_descriptor_table_rejects_non_increasing_offsets():
    blob = bytearray(make_descriptor_xpr(tex_sizes=(0x40, 0x40)))
    table = doa3_cast.mdl_descriptor_table(bytes(blob))
    # force the second texture offset equal to the first
    p = table["terminator_offset"] - doa3_cast.TEXTURE_DESC_BYTES + 4
    first = table["texture_descriptors"][0]["offset"]
    struct.pack_into("<I", blob, p, first)
    with pytest.raises(ValueError, match="strictly increasing"):
        doa3_cast.mdl_descriptor_table(bytes(blob))


# ----------------------------------------------------------------- BIN body

def make_bin_body(header_size: int = 0x88, pointers: list[int] | None = None,
                  total: int | None = None) -> bytes:
    """A ``<nick>.bin`` body shaped like the measured files: word 0 is the header
    byte size, the remaining words are in-file section pointers (0 allowed), and
    the body data follows immediately after the header."""
    n = header_size // 4
    pointers = list(pointers) if pointers is not None else [0] * (n - 1)
    total = total if total is not None else header_size + 0x100
    out = bytearray(total)
    struct.pack_into("<I", out, 0, header_size)
    for k, w in enumerate(pointers, start=1):
        struct.pack_into("<I", out, 4 * k, w)
    return bytes(out)


def test_bin_header_parses_0x88_body():
    res = doa3_cast.bin_header(make_bin_body(0x88))
    assert res["header_size"] == 0x88
    assert res["word_count"] == 34
    assert res["version"] == "0x88"
    assert res["data_offset"] == 0x88
    assert res["words"][0] == 0x88


def test_bin_header_parses_0x84_body():
    res = doa3_cast.bin_header(make_bin_body(0x84))
    assert res["header_size"] == 0x84
    assert res["word_count"] == 33


def test_bin_header_accepts_in_file_pointers():
    pointers = [0x90, 0, 0x100, 0] + [0] * 29
    res = doa3_cast.bin_header(make_bin_body(0x88, pointers=pointers))
    assert res["words"][1] == 0x90 and res["words"][3] == 0x100


def test_bin_header_rejects_unknown_size():
    with pytest.raises(ValueError, match="not one of"):
        doa3_cast.bin_header(make_bin_body(0x80))


def test_bin_header_rejects_out_of_file_pointer():
    with pytest.raises(ValueError, match="not an in-file pointer"):
        doa3_cast.bin_header(make_bin_body(0x88, pointers=[0xFFFF0000] + [0] * 32))


def test_bin_header_rejects_too_short():
    with pytest.raises(ValueError, match="too short"):
        doa3_cast.bin_header(b"\x00")


def test_bin_header_rejects_header_exceeding_file():
    with pytest.raises(ValueError, match="exceeds"):
        doa3_cast.bin_header(struct.pack("<I", 0x88))


def test_bin_header_holds_on_all_owned_bodies():
    # The owned loadfile.afs carries 20 fighter bodies: 18 with a 0x88 header and
    # 2 (suiken/gokei = Brad Wong / Christie) with a 0x84 header. Every header word
    # is an in-file pointer or 0. Pinned against the owned build; skipped when the
    # cache is absent.
    afs_path = Path.home() / "gbox-cache/b8edf7040116f3aa/extract/Dead or Alive 3/loadfile.afs"
    if not afs_path.is_file():
        pytest.skip("owned DOA3 loadfile.afs not present")
    from gbox import doa3_inventory
    af = doa3_inventory.read_afs(afs_path)
    fams = doa3_inventory.fighter_families(af["entries"])
    assert fams, "owned loadfile.afs should yield fighter families"
    sizes: dict[int, int] = {}
    with open(afs_path, "rb") as f:
        for fam in fams:
            e = next(x for x in af["entries"] if x["index"] == fam["bin"])
            f.seek(e["offset"])
            res = doa3_cast.bin_header(f.read(e["size"]))
            sizes[res["header_size"]] = sizes.get(res["header_size"], 0) + 1
    assert sizes == {0x88: 18, 0x84: 2}
