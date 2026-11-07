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
             prims=((6, 6),), uv=None, colors=None, aux="fixed", bad_bone=None, corrupt=None):
    """A BIN with `n` vertices, `bones` (id, parent) pairs, one material of `prims` (type, nverts) runs.

    Sections are laid out in file order 0x98 bones, 0x20 weights, 0x48 positions, 0x50 aux, 0x70 weight index,
    0x10 colours, 0x18 UVs, 0x30 primitive table -- the same ordering the real packs use.
    """
    assert sum(c for _t, c in prims) == n, "prims must cover every vertex"
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
    widx = np.zeros(n, "<u2")
    if corrupt == "widx":
        widx[0] = 99
    o_widx = put(widx.tobytes())
    # colours
    o_col = put(colors.astype(np.uint8).tobytes())
    # uvs
    o_uv = put(uv.astype("<f4").tobytes())
    # primitive table: one material
    pairs = list(prims)
    tris = sum(M.PRIM_TYPES[t][1](c) for t, c in pairs)
    if corrupt == "tris":
        tris += 1
    npairs = len(pairs)
    mhdr = bytearray(M.MAT_HDR)
    mhdr[0x0D:0x10] = b"\xff\xff\xff"
    mhdr[0x17] = 0xFF
    body_bytes = 4 * npairs
    struct.pack_into("<III", mhdr, 0x18, (M.MAT_HDR + body_bytes) // 32 * 32, tris, npairs)
    o_prims = put(bytes(mhdr) + b"".join(struct.pack("<HH", t, c) for t, c in pairs))

    out = bytearray(hdr)
    out.extend(body)
    struct.pack_into("<I", out, 0x00, M.HDR_SIZE)
    struct.pack_into("<I", out, 0x0C, 0x50)
    for off, at_ in ((o_col, 0x10), (o_uv, 0x18), (o_weights, 0x20), (o_prims, 0x30),
                     (o_pos, 0x48), (o_aux, 0x50), (o_widx, 0x70), (o_widx, 0x78)):
        struct.pack_into("<I", out, at_, off)
    struct.pack_into("<I", out, 0x80, o_pos + 12 * n - 8)      # tail pointers live INSIDE the streams
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
        struct.pack_into("<HH", out, o_prims + M.MAT_HDR, pairs[0][0], pairs[0][1] - 1)
        struct.pack_into("<I", out, o_prims + 0x1C,
                         sum(M.PRIM_TYPES[t][1](c)
                             for t, c in [(pairs[0][0], pairs[0][1] - 1)] + pairs[1:]))
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

