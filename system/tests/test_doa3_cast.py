"""Focused tests for gbox.doa3_cast: XPR0 walk, CAT sections, slot inventory,
the AFS patch path and the measured MDL geometry decoder. Fixtures mirror the
byte layout observed in the owned USA build (kas00.xpr / kas00.cat,
loadfile.afs)."""
import struct

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
    body = bytearray(0x9A40 + 4)
    struct.pack_into("<8I", body, 0, *header)
    body[0x9A40:0x9A44] = b"LNK\x00"
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
    struct.pack_into("<8I", body, 0, 1, 0x14, 1, 0x20, 1, 0x100, 1, 0x18)
    res = doa3_cast.cat_sections(bytes(body))
    assert res["lnk_markers"] == []
    assert res["layout"] == "offsets"
    assert res["lnk_offset_hint"] == 0x20


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
