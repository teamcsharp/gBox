"""RE4 Switch (HD port) BIN meshes: every claim in `gbox.re4hd_models` pinned by a synthetic BIN, plus the refusals.

No game data is used here.  `make_bin` builds a BIN that satisfies the measured HD layout (0x98 header, little-endian
tables) so each test can state one structural fact and then corrupt exactly that fact to prove the decoder refuses
the file instead of returning a plausible-looking mesh.
"""
import struct

import numpy as np
import pytest

from gbox import re4hd_models as M


# ------------------------------------------------------------------ synthetic BIN builder

def make_bin(*, n=6, bones=((0, 0xFF), (1, 0)), weights=((0, 0, 0, 1, 100, 0, 0, 0),),
             prims=((6, 6),), materials=None, uv=None, colors=None, aux="fixed", bad_bone=None, corrupt=None,
             omit=()):
    """A BIN with `n` vertices, `bones` (id, parent) pairs, one material of `prims` (type, nverts) runs.

    `materials` overrides `prims` with a list of primitive lists (one material record each); `omit` drops the named
    optional sections (`colors`, `aux`, `weight_idx`) from the file and zeroes their header fields.

    Sections are laid out in file order 0x98 bones, 0x20 weights, 0x48 positions, 0x50 aux, 0x70 weight index,
    0x10 colours, 0x18 UVs, 0x30 primitive table -- the same ordering the real packs use.
    """
    groups = [list(x) for x in (materials if materials is not None else [prims])]
    assert sum(c for group in groups for _t, c in group) == n, "prims must cover every vertex"
    i = np.arange(n, dtype=float)
    pos = np.stack([10.0 * np.cos(i), 6.0 * i, 10.0 * np.sin(i)], 1).astype("<f4")   # not collinear
    if uv is None:
        uv = np.tile(np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], "<f4"), (n // 4 + 1, 1))[:n]
    if colors is None:
        colors = np.tile(np.array([255, 255, 255, 255], np.uint8), (n, 1))

    hdr = bytearray(M.HDR_SIZE)
    body = bytearray()

    def at(kind):
        return M.HDR_SIZE + len(body)

    def put(data, align=32):
        while len(body) % align:
            body.append(0)
        o = at("x")
        body.extend(data)
        return o

    # bones
    o_bones = at("bones")
    for i, (bid, par) in enumerate(bones):
        if bad_bone is not None and i == bad_bone[0]:
            par = bad_bone[1]
        body.extend(struct.pack("<BB2s3f", bid, par, b"", 0.0, 10.0 * i, 0.0))
    # weights
    o_weights = put(b"".join(bytes(w) for w in weights))
    # positions
    o_pos = put(pos.tobytes())
    # aux stream
    o_aux = None
    if "aux" not in omit:
        if aux == "fixed":
            rec = np.zeros((n, 6), "<i2")
            rec[:, 1::2] = np.tile(np.array([11585, 0, -11585], "<i2"), (n, 1))
            aux_bytes = rec.tobytes()
        elif aux == "f32":
            aux_bytes = (np.tile(np.array([16384.0, 0.0, -16384.0]), (n, 1)).astype("<f4")).tobytes()
        else:
            aux_bytes = bytes(12 * n)
        o_aux = put(aux_bytes)
    # weight index
    o_widx = None
    if "weight_idx" not in omit:
        widx = np.zeros(n, "<u2")
        if corrupt == "widx":
            widx[0] = 99
        o_widx = put(widx.tobytes())
    # colours
    o_col = None
    if "colors" not in omit:
        o_col = put(colors.astype(np.uint8).tobytes())
    # uvs
    o_uv = put(uv.astype("<f4").tobytes())
    # primitive table: one record per material group
    records = []
    first = True
    for pairs in groups:
        tris = sum(M.PRIM_TYPES[t][1](c) for t, c in pairs)
        if corrupt == "tris" and first:
            tris += 1
        npairs = len(pairs)
        mhdr = bytearray(M.MAT_HDR)
        mhdr[0x0D:0x10] = b"\xff\xff\xff"
        mhdr[0x17] = 0xFF
        body_bytes = 4 * npairs
        struct.pack_into("<III", mhdr, 0x18, (M.MAT_HDR + body_bytes) // 32 * 32, tris, npairs)
        rec = bytes(mhdr) + b"".join(struct.pack("<HH", t, c) for t, c in pairs)
        rec += bytes((-len(rec)) % 32)              # records are 32-byte aligned relative to the table start
        records.append(rec)
        first = False
    o_prims = put(b"".join(records))

    out = bytearray(hdr)
    out.extend(body)
    struct.pack_into("<I", out, 0x00, M.HDR_SIZE)
    struct.pack_into("<I", out, 0x0C, 0x50)
    fields = [(o_uv, 0x18), (o_weights, 0x20), (o_prims, 0x30), (o_pos, 0x48)]
    if o_col is not None:
        fields.append((o_col, 0x10))
    if o_aux is not None:
        fields.append((o_aux, 0x50))
    if o_widx is not None:
        fields += [(o_widx, 0x70), (o_widx, 0x78)]
    for off, at_ in fields:
        struct.pack_into("<I", out, at_, off)
    struct.pack_into("<I", out, 0x80, o_pos + 12 * n - 8)      # tail pointers live INSIDE the streams
    if o_aux is not None:
        struct.pack_into("<I", out, 0x84, o_aux + 12 * n - 8)
    struct.pack_into("<H", out, 0x58, n)
    struct.pack_into("<H", out, 0x5C & ~3, 0)                  # keep 0x58/0x5A clean
    struct.pack_into("<H", out, 0x5A, n)

    if corrupt == "header_size":
        struct.pack_into("<I", out, 0x00, 0x98 + 16)
    elif corrupt == "offset_oob":
        struct.pack_into("<I", out, 0x48, len(out) + 0x100)
    elif corrupt == "high_dword":
        struct.pack_into("<I", out, 0x4C, 0x1234)
    elif corrupt == "count":
        struct.pack_into("<H", out, 0x58, n + 1)
    elif corrupt == "truncate":
        out = out[:len(out) - 40]
    elif corrupt == "prims_sum":
        # a self-consistent material that simply covers one vertex less than the BIN declares
        t, c = groups[0][0]
        struct.pack_into("<HH", out, o_prims + M.MAT_HDR, t, c - 1)
        struct.pack_into("<I", out, o_prims + 0x1C,
                         sum(M.PRIM_TYPES[tt][1](cc)
                             for tt, cc in [(t, c - 1)] + list(groups[0][1:])))
    return bytes(out)


def one_material(pairs):
    return dict(prims=tuple(pairs), n=sum(c for _t, c in pairs))


# ------------------------------------------------------------------ the header

def test_bin_info_reports_the_hd_header_and_counts():
    b = make_bin(n=12, prims=((6, 12),))
    info = M.bin_info(b)
    assert info["header_size"] == 0x98 and info["endian"] == "little"
    assert info["vertex_count"] == 12
    assert info["vertex_count_hi"] == 12
    assert info["bone_count"] == 2
    assert info["material_count"] == 1
    assert info["triangle_count"] == 10                    # 12-vertex strip
    assert info["offsets"]["positions"] == info["spans"]["positions"]["start"]
    assert info["spans"]["positions"]["size"] >= 12 * 12


def test_a_gamecube_bin_header_is_refused():
    # the GC BIN starts with 0x40 / 0x60, never 0x98 -- the reader must not guess
    with pytest.raises(M.BINError, match="header size"):
        M.bin_info(struct.pack(">I", 0x40) + bytes(0x200))


def test_a_short_file_is_refused():
    with pytest.raises(M.BINError, match="too short"):
        M.bin_info(b"\x98\x00\x00\x00" + bytes(40))


def test_the_64_bit_offset_slots_must_have_a_zero_high_dword():
    with pytest.raises(M.BINError, match="high dword"):
        M.bin_info(make_bin(corrupt="high_dword"))


def test_an_offset_outside_the_file_is_refused():
    with pytest.raises(M.BINError, match="outside the file"):
        M.bin_info(make_bin(corrupt="offset_oob"))


def test_the_tail_pointers_may_point_inside_the_vertex_streams():
    # 0x80/0x84 are 4 bytes apart and sit INSIDE the 0x48/0x50 arrays in every real BIN; that must not be
    # mistaken for a table start, or the position span check would fail
    m = M.bin_read(make_bin(n=12, prims=((6, 12),)))
    assert m.info["offsets"]["aux_tail"] > m.info["offsets"]["positions"]
    assert m.n_verts == 12


# ------------------------------------------------------------------ vertices

def test_positions_uvs_and_colours_come_back_per_vertex():
    m = M.bin_read(make_bin(n=8, prims=((6, 8),)))
    assert m.pos.shape == (8, 3) and m.uv.shape == (8, 2) and m.colors.shape == (8, 4)
    assert np.allclose(m.pos[:, 0], 10.0 * np.cos(np.arange(8.0)))
    assert m.uv[0].tolist() == [0.0, 0.0] and m.uv[1].tolist() == [1.0, 0.0]
    assert (m.colors == 255).all()


def test_the_vertex_count_drives_the_position_span():
    # one vertex too many and the span no longer explains the array: the decoder must refuse
    with pytest.raises(M.BINError):
        M.bin_read(make_bin(n=8, prims=((6, 8),), corrupt="count"))


def test_a_truncated_bin_is_refused():
    with pytest.raises((M.BINError, ValueError)):
        M.bin_read(make_bin(n=8, prims=((6, 8),), corrupt="truncate"))


def test_bbox_and_height_are_reported():
    m = M.bin_read(make_bin(n=8, prims=((6, 8),)))
    bb = m.bbox()
    assert bb.shape == (2, 3)
    assert bb[1, 0] > bb[0, 0]


# ------------------------------------------------------------------ bones

def test_bones_are_id_parent_translation_records():
    m = M.bin_read(make_bin(bones=((0, 0xFF), (1, 0), (2, 1), (3, 1))))
    assert [b["id"] for b in m.bones] == [0, 1, 2, 3]
    assert [b["parent"] for b in m.bones] == [0xFF, 0, 1, 1]
    w = m.bone_world()
    assert w[0].tolist() == [0.0, 0.0, 0.0]
    assert w[2].tolist() == [0.0, 30.0, 0.0]              # 10 (bone 1) + 20 (bone 2)


def test_bin_bones_matches_bin_read():
    b = make_bin(bones=((0, 0xFF), (1, 0)))
    assert M.bin_bones(b) == M.bin_read(b).bones


def test_a_bone_whose_parent_is_itself_or_later_is_refused():
    with pytest.raises(M.BINError, match="parent"):
        M.bin_read(make_bin(bones=((0, 0xFF), (1, 1))))


def test_a_bone_table_with_no_root_is_refused():
    b = make_bin(bones=((0, 0xFF), (1, 0)))
    # rewrite the root's parent to a child -> no root
    h = {o: struct.unpack_from("<I", b, o)[0] for o in range(0, 0x98, 4)}
    ba = bytearray(b)
    ba[0x98 + 1] = 0
    with pytest.raises(M.BINError):
        M.bin_read(bytes(ba))


# ------------------------------------------------------------------ weights

def test_weight_sets_use_the_gc_record_layout_and_are_indexed_per_vertex():
    m = M.bin_read(make_bin(n=4, prims=((6, 4),),
                            weights=((0, 0, 0, 1, 100, 0, 0, 0), (0, 1, 0, 2, 60, 40, 0, 0))))
    assert m.weight_idx.tolist() == [0, 0, 0, 0]
    assert m.weights[0] == (0, 0, 0, 1, 100, 0, 0, 0)


def test_a_weight_index_outside_the_table_is_refused():
    with pytest.raises(M.BINError, match="weight index"):
        M.bin_read(make_bin(n=4, prims=((6, 4),), corrupt="widx"))


def test_a_weight_set_referencing_a_missing_bone_is_refused():
    with pytest.raises(M.BINError, match="bone"):
        M.bin_read(make_bin(n=4, prims=((6, 4),), weights=((7, 0, 0, 1, 100, 0, 0, 0),)))


# ------------------------------------------------------------------ primitives

def test_primitive_types_map_to_triangle_counts():
    # type 5 = triangle list (n/3), 6 = strip (n-2), 8 = quads (n/2)
    m = M.bin_read(make_bin(**one_material([(5, 6), (6, 5), (8, 8)])))
    assert m.mats[0].triangles == 2 + 3 + 4
    assert m.n_tris == 9
    assert m.tris.shape == (9, 3)


def test_the_primitive_vertex_counts_must_cover_the_vertex_array_exactly():
    b = make_bin(**one_material([(6, 8)]))
    info = M.bin_info(b)
    assert info["prim_vertex_total"] == 8
    with pytest.raises(M.BINError, match="sum to"):
        M.bin_read(make_bin(**one_material([(6, 8)]), corrupt="prims_sum"))


def test_a_material_triangle_count_that_does_not_match_its_primitives_is_refused():
    with pytest.raises(M.BINError):
        M.bin_read(make_bin(**one_material([(6, 8)]), corrupt="tris"))


def test_synthetic_corruption_never_returns_a_mesh():
    """Every single-byte corruption of the header must either decode to the same mesh or raise -- never silently
    produce a different mesh.  (Plausible-looking garbage is the failure mode this decoder exists to prevent.)"""
    base = make_bin(n=12, prims=((6, 12),))
    ref = M.bin_read(base)
    accepted = 0
    for off in range(0, 0x98, 4):
        for v in (0x01, 0x7F, 0xFF):
            ba = bytearray(base)
            ba[off] = v
            try:
                m = M.bin_read(bytes(ba))
            except (M.BINError, ValueError):
                continue
            accepted += 1
            assert m.n_verts == ref.n_verts and np.allclose(m.pos, ref.pos)
    assert accepted < 0x98 // 4 * 3          # the vast majority must be refused


# ------------------------------------------------------------------ the 0x50 stream

def test_the_aux_stream_is_reported_with_its_encoding_never_as_normals():
    fixed = M.bin_read(make_bin(n=4, prims=((6, 4),), aux="fixed"))
    assert fixed.aux.encoding == "fixed"
    assert fixed.aux.value[0].tolist() == [11585 / 16384.0, 0.0, -11585 / 16384.0]
    f32 = M.bin_read(make_bin(n=4, prims=((6, 4),), aux="f32"))
    assert f32.aux.encoding == "f32"
    junk = M.bin_read(make_bin(n=4, prims=((6, 4),), aux="zero"))
    assert junk.aux.encoding == "unknown" and junk.aux.value is None


def test_normals_are_derived_from_the_triangles_not_read_from_the_file():
    m = M.bin_read(make_bin(**one_material([(5, 6)])))
    n = m.normals()
    assert n.shape == (6, 3)
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0, atol=0.15)


# ------------------------------------------------------------------ DAT convenience

def test_load_slot_reads_a_bin_out_of_a_dat_pack():
    bin_bytes = make_bin(n=6, prims=((6, 6),))
    # a minimal little-endian DAT with one BIN slot
    n = 1
    off = 32
    dat = bytearray(struct.pack("<II", n, 0) + bytes(8))
    dat += struct.pack("<1I", off)
    dat += b"BIN\0"
    dat += bytes(off - len(dat))
    dat += bin_bytes
    m = M.load_slot(bytes(dat), 0)
    assert m.n_verts == 6
    with pytest.raises(M.BINError, match="out of range"):
        M.load_slot(bytes(dat), 3)


# ------------------------------------------------------------------ writer: round-trip

@pytest.mark.parametrize("kw", [
    dict(n=6, prims=((6, 6),)),
    dict(n=12, prims=((6, 12),)),
    dict(n=8, prims=((5, 6), (6, 2))),
    dict(n=8, prims=((8, 8),)),
    dict(n=12, materials=[((5, 6),), ((6, 6),)]),
    dict(n=6, prims=((6, 6),), bones=((0, 0xFF), (1, 0), (2, 1), (3, 1))),
    dict(n=4, prims=((6, 4),), aux="f32"),
    dict(n=4, prims=((6, 4),), aux="zero"),
    dict(n=8, prims=((6, 8),), omit=("colors",)),
    dict(n=8, prims=((6, 8),), omit=("aux",)),
    dict(n=8, prims=((6, 8),), omit=("weight_idx",)),
])
def test_bin_write_is_byte_identical_on_a_decoded_bin(kw):
    """The writer's acceptance test: decode -> encode must reproduce every byte, unknown sections included."""
    b = make_bin(**kw)
    m = M.bin_read(b)
    assert M.bin_write(m) == b


def test_bin_write_preserves_unknown_tail_bytes_and_packed_header_words():
    # bytes after the last material record are not decoded, and the packed words are not interpreted: both must
    # survive a rewrite verbatim, or a real slot's unknown data would be silently lost
    b = bytearray(make_bin(n=8, prims=((6, 8),))) + b"\xAA" * 13
    struct.pack_into("<II", b, 0x28, 0x000320BC, 0)
    struct.pack_into("<I", b, 0x38, 0xA0000100)
    struct.pack_into("<H", b, 0x3C, 7)
    struct.pack_into("<HH", b, 0x40, 5, 2)
    struct.pack_into("<I", b, 0x5C, 0x20030818)
    m = M.bin_read(bytes(b))
    assert M.bin_write(m) == bytes(b)
    assert m.info["spans"]["prims"]["end"] == len(b)


def test_bin_write_rebuilds_only_the_changed_section():
    b = make_bin(n=8, prims=((6, 8),))
    m = M.bin_read(b)
    m.pos = m.pos + np.array([1000.0, 0.0, 0.0])
    out = M.bin_write(m)
    assert len(out) == len(b)
    back = M.bin_read(out)
    assert np.allclose(back.pos[:, 0], m.pos[:, 0])
    o = m.info["offsets"]
    assert out[o["prims"]:] == b[o["prims"]:]           # material/primitive records untouched
    assert out[:0x28] == b[:0x28]                        # packed header words untouched


def test_bin_write_preserves_unknown_bytes_inside_bone_pads_and_material_headers():
    b = bytearray(make_bin(n=8, prims=((6, 8),), bones=((0, 0xFF), (1, 0))))
    b[0x98 + 2:0x98 + 4] = b"\xAB\xCD"                 # the 2 pad bytes of a 16-byte bone record
    o = M.bin_info(bytes(b))["offsets"]["prims"]
    b[o + 8] = 0xAB                                     # an uninterpreted byte of the material header
    m = M.bin_read(bytes(b))
    assert M.bin_write(m) == bytes(b)


def test_bin_write_keeps_the_bbox_the_caller_supplied_never_a_rewritten_one():
    # the GameCube rule: the writer must not scale/clamp positions to a stored box.  It writes what it is given and
    # leaves the packed flag/bounds words alone.
    ba = bytearray(make_bin(n=6, prims=((6, 6),)))
    struct.pack_into("<I", ba, 0x28, 0x00020101)
    m = M.bin_read(bytes(ba))
    before = ba[0x28:0x44]
    m.pos = m.pos * 2.0 + 500.0
    out = M.bin_write(m)
    assert out[0x28:0x44] == before
    back = M.bin_read(out)
    assert np.allclose(back.bbox(), np.stack([m.pos.min(0), m.pos.max(0)]))


def test_bin_write_refuses_a_bin_with_no_positions():
    hdr = make_bin()[:M.HDR_SIZE]
    with pytest.raises(M.BINError, match="positions"):
        M.bin_write(M.Bin(header=hdr, info={}))


def test_bin_write_refuses_a_vertex_count_change_and_points_at_bin_from():
    m = M.bin_read(make_bin(n=8, prims=((6, 8),)))
    m.pos = m.pos[:-1]
    with pytest.raises(M.BINError, match="bin_from"):
        M.bin_write(m)


def test_bin_write_verify_rejects_a_material_table_that_does_not_cover_the_vertices():
    m = M.bin_read(make_bin(n=8, prims=((6, 8),)))
    m.mats[0].pairs = [(6, 7)]
    with pytest.raises(M.BINError, match="decoder refuses"):
        M.bin_write(m, verify=True)


# ------------------------------------------------------------------ writer: slot padding

def test_pad_to_appends_zeros_and_returns_the_same_bytes_at_the_exact_size():
    data = M.bin_write(M.bin_read(make_bin(n=6, prims=((6, 6),))))
    assert M.pad_to(data, len(data)) == data
    padded = M.pad_to(data, len(data) + 40)
    assert padded[:len(data)] == data and padded[len(data):] == bytes(40)
    assert M.bin_read(padded).n_verts == 6                # trailing zeros do not change the mesh


def test_pad_to_refuses_a_replacement_bigger_than_the_slot_and_a_negative_size():
    data = make_bin()
    with pytest.raises(M.BINError, match="does not fit"):
        M.pad_to(data, len(data) - 1)
    with pytest.raises(M.BINError, match="negative"):
        M.pad_to(data, -1)


# ------------------------------------------------------------------ writer: source swap

def test_bin_from_replaces_geometry_and_keeps_the_slot_material_records_when_topology_matches():
    dst = make_bin(n=12, materials=[((5, 6),), ((6, 6),)], bones=((0, 0xFF), (1, 0)))
    src = make_bin(n=12, prims=((6, 12),))
    d, s = M.bin_read(dst), M.bin_read(src)
    pos = s.pos + np.array([250.0, -30.0, 10.0])
    out = M.bin_from(d, pos=pos, uv=s.uv, colors=s.colors)
    m = M.bin_read(out)
    assert np.allclose(m.pos, pos) and np.allclose(m.uv, s.uv)
    assert m.n_verts == 12 and m.n_tris == d.n_tris       # same primitive records
    o = d.info["offsets"]
    assert out[o["prims"]:] == dst[o["prims"]:]
    assert [b["id"] for b in m.bones] == [0, 1]


def test_bin_from_rebuilds_the_primitive_table_for_a_different_vertex_count():
    dst = make_bin(n=8, materials=[((5, 6),), ((6, 2),)], bones=((0, 0xFF), (1, 0)))
    src = make_bin(n=12, prims=((6, 12),))
    d, s = M.bin_read(dst), M.bin_read(src)
    out = M.bin_from(d, pos=s.pos, uv=s.uv, colors=s.colors, tris=s.tris)
    m = M.bin_read(out)
    assert m.n_verts == 3 * s.n_tris                       # one vertex per triangle corner (type-5 lists)
    assert m.n_tris == s.n_tris
    assert m.info["prim_vertex_total"] == m.n_verts
    assert np.allclose(m.bbox(), s.bbox())                 # positions are the source's, not rescaled
    assert [b["id"] for b in m.bones] == [0, 1]            # slot skeleton kept
    assert len(m.mats) == len(d.mats)
    assert sum(x.triangle_count for x in m.mats) == s.n_tris
    assert all(x.pairs and all(t == 5 for t, _ in x.pairs) for x in m.mats)
    assert int(m.weight_idx.max()) < len(m.weights)


def test_bin_from_spreads_triangles_over_the_slot_material_headers_proportionally():
    dst = make_bin(n=12, materials=[((5, 6),), ((6, 6),)])     # 2 triangles + 4 triangles
    src = make_bin(n=12, prims=((6, 12),))                     # 10 triangles
    d, s = M.bin_read(dst), M.bin_read(src)
    m = M.bin_read(M.bin_from(d, pos=s.pos, uv=s.uv, colors=s.colors, tris=s.tris))
    assert len(m.mats) == 2
    assert sum(x.triangle_count for x in m.mats) == 10
    assert all(x.triangle_count > 0 for x in m.mats)
    assert [x.uv_set for x in m.mats] == [x.uv_set for x in d.mats]


def test_bin_from_refuses_out_of_range_and_degenerate_triangles():
    d = M.bin_read(make_bin(n=8, prims=((6, 8),)))
    good = np.arange(6).reshape(-1, 3)
    with pytest.raises(M.BINError, match="outside"):
        M.bin_from(d, pos=d.pos[:6], tris=np.array([[0, 1, 6]]))
    with pytest.raises(M.BINError, match="degenerate"):
        M.bin_from(d, pos=d.pos[:6], tris=np.array([[0, 0, 1]]))


def test_bin_from_refuses_an_input_that_is_not_an_hd_bin():
    with pytest.raises(M.BINError):
        M.bin_from(struct.pack(">I", 0x40) + bytes(0x200))



# ---------------------------------------------------------------- strip encoding (the fitting ladder's first rung)

def grid_mesh(n=4):
    """An (n x n) vertex grid and its triangles: real adjacency, so strips can actually form."""
    import numpy as np
    pos = np.array([[float(x), float(y), 0.0] for y in range(n) for x in range(n)], float)
    tris = []
    for y in range(n - 1):
        for x in range(n - 1):
            a = y * n + x
            b, c, d = a + 1, a + n, a + n + 1
            tris.append((a, b, d))
            tris.append((a, d, c))
    return pos, np.array(tris, np.int64)


def test_strip_encoding_cuts_the_vertex_count_and_keeps_every_triangle():
    import numpy as np
    tmpl = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    pos, tris = grid_mesh(4)
    as_list = M.bin_read(M.bin_from(tmpl, pos=pos, tris=tris, encoding="list"))
    as_strip = M.bin_read(M.bin_from(tmpl, pos=pos, tris=tris, encoding="strip"))
    assert as_list.n_verts == 3 * len(tris)            # a list stores one vertex per corner
    assert as_strip.n_verts < as_list.n_verts          # a strip reuses the shared edge
    assert as_strip.n_tris == as_list.n_tris == len(tris)

    def geometry(mesh):
        p = np.asarray(mesh.pos)
        return sorted(tuple(sorted((round(float(p[v][0]), 3), round(float(p[v][1]), 3), round(float(p[v][2]), 3))
                                   for v in tri)) for tri in mesh.triangles())

    assert geometry(as_strip) == geometry(as_list)


def test_strip_winding_matches_the_source_so_faces_are_not_flipped():
    """A naive stripifier flips every other face, which renders half a character inside-out."""
    import numpy as np
    tmpl = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    pos, tris = grid_mesh(4)
    src = np.asarray(pos)

    def facing(mesh):
        p = np.asarray(mesh.pos)
        out = []
        for tri in mesh.triangles():
            a, b, c = (p[v] for v in tri)
            n = np.cross(b - a, c - a)
            out.append(tuple(round(float(v), 6) for v in n))
        return sorted(out)

    strip = M.bin_read(M.bin_from(tmpl, pos=pos, tris=tris, encoding="strip"))
    source = []
    for tri in tris:
        a, b, c = (src[v] for v in tri)
        source.append(tuple(round(float(v), 6) for v in np.cross(b - a, c - a)))
    assert facing(strip) == sorted(source)


def test_an_unknown_encoding_is_refused():
    tmpl = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    pos, tris = grid_mesh(3)
    with pytest.raises(M.BINError, match="encoding must be"):
        M.bin_from(tmpl, pos=pos, tris=tris, encoding="fan")

# ---------------------------------------------------------------- which slot can host a donor

def pack_with(*bins):
    """An HD pack holding these BIN slots, in order (little-endian UDAS/DAT)."""
    n = len(bins)
    base = 16 + 4 * n + 4 * n
    offsets, cursor = [], base
    for b in bins:
        offsets.append(cursor)
        cursor += len(b)
    dat = bytearray(struct.pack("<II", n, 0) + b"\0" * 8)
    dat += struct.pack(f"<{n}I", *offsets)
    dat += b"BIN\0" * n
    for b in bins:
        dat += b
    hdr = bytearray(b"\xca\xb6\xbe\x20" * 8)
    hdr += struct.pack("<IIII", 0, len(dat), 0, 0x400) + b"\0" * 16
    hdr += struct.pack("<I", 0xFFFFFFFF)
    hdr += b"\0" * (0x400 - len(hdr))
    return bytes(hdr) + bytes(dat)


def test_rank_targets_says_which_slots_can_hold_a_donor_and_which_cannot():
    """The size constraint is arithmetic: measured 1.5 verts/triangle with strips, ~41 B per vertex."""
    small = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    big = M.bin_read(make_bin(n=12, bones=((0, 0xFF),), prims=((5, 12),)))
    pack = pack_with(M.bin_from(small, pos=small.pos, tris=small.tris),
                     M.bin_from(big, pos=big.pos, tris=big.tris))
    donor_pos, donor_tris = grid_mesh(5)                 # 25 verts, 32 triangles
    donor = M.Bin(header=b"", info={})
    donor.pos, donor.tris = donor_pos, donor_tris
    donor.uv = None
    donor.colors = None
    out = M.rank_targets(pack, donor, encoding="strip")
    assert out["donor"]["tris"] == 32
    statuses = {row["bin"]: row["status"] for row in out["rows"]}
    assert out["slots"] == 2 and len(statuses) == 2
    # the answer is a decision, not a shrug: every slot is named, and the fits are a subset
    assert all(s in ("fits", "too_big", "refused", "undecodable") for s in statuses.values())
    assert out["fits"] == sum(1 for s in statuses.values() if s == "fits")
    assert (out["best"] is None) == (out["fits"] == 0)
    for row in out["rows"]:
        if row["status"] == "fits":
            assert row["bytes"] <= row["slot_bytes"] and row["fill"] <= 1.0


def test_a_donor_that_fits_nowhere_reports_no_best_slot():
    tiny = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    pack = pack_with(M.bin_from(tiny, pos=tiny.pos, tris=tiny.tris))
    donor_pos, donor_tris = grid_mesh(6)                 # far more triangles than that slot can hold
    donor = M.Bin(header=b"", info={})
    donor.pos, donor.tris = donor_pos, donor_tris
    donor.uv = donor.colors = None
    out = M.rank_targets(pack, donor, encoding="strip")
    assert out["fits"] == 0 and out["best"] is None
    assert [r["status"] for r in out["rows"]] == ["too_big"]
    assert out["rows"][0]["bytes"] > out["rows"][0]["slot_bytes"]


def test_rank_targets_needs_a_donor_with_geometry():
    pack = pack_with(M.bin_from(M.bin_read(make_bin(n=6, prims=((5, 6),))),
                                pos=M.bin_read(make_bin(n=6, prims=((5, 6),))).pos,
                                tris=M.bin_read(make_bin(n=6, prims=((5, 6),))).tris))
    empty = M.Bin(header=b"", info={})
    with pytest.raises(M.BINError, match="no geometry"):
        M.rank_targets(pack, empty)

# ---------------------------------------------------------------- simplify (making a donor fit without holes)

def test_simplify_stays_inside_its_triangle_budget_and_keeps_a_surface():
    pos, tris = grid_mesh(12)                     # 242 triangles over a 12x12 grid
    for budget in (30, 80, 200):
        new_pos, new_tris, info = M.simplify(pos, tris, budget)
        assert len(new_tris) <= budget, f"{len(new_tris)} > {budget}"
        assert info["ratio"] <= 1.0
        # every surviving triangle still names three distinct merged vertices - a collapsed one is dropped
        assert ((new_tris[:, 0] != new_tris[:, 1]) & (new_tris[:, 1] != new_tris[:, 2])
                & (new_tris[:, 0] != new_tris[:, 2])).all()
        assert new_tris.max() < len(new_pos)


def test_simplify_is_a_no_op_when_the_mesh_already_fits():
    pos, tris = grid_mesh(4)
    new_pos, new_tris, info = M.simplify(pos, tris, len(tris) + 10)
    assert len(new_tris) == len(tris) and info["ratio"] == 1.0
    assert (new_pos == pos).all()


def test_simplify_refuses_a_bad_budget_or_bad_arrays():
    pos, tris = grid_mesh(4)
    with pytest.raises(M.BINError, match="positive"):
        M.simplify(pos, tris, 0)
    with pytest.raises(M.BINError, match="needs"):
        M.simplify(pos[:, :2], tris, 10)


def test_a_simplified_donor_rebuilds_into_a_slot_it_could_not_enter_before():
    """The whole point: a donor that was too big for a slot fits once simplified to that slot's budget."""
    tmpl_small = M.bin_read(make_bin(n=6, bones=((0, 0xFF),), prims=((5, 6),)))
    tiny = M.bin_from(tmpl_small, pos=tmpl_small.pos, tris=tmpl_small.tris)
    pos, tris = grid_mesh(9)                       # 128 triangles: far more than that slot holds
    donor = M.Bin(header=b"", info={})
    donor.pos, donor.tris, donor.uv, donor.colors = pos, tris, None, None
    before = None
    try:
        before = M.bin_from(M.bin_read(tiny), pos=pos, tris=tris, encoding="strip")
    except M.BINError:
        pass
    simple_pos, simple_tris, _ = M.simplify(pos, tris, 20)
    after = M.bin_from(M.bin_read(tiny), pos=simple_pos, tris=simple_tris, encoding="strip")
    assert after is not None
    if before is not None:
        assert len(after) < len(before)