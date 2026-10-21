"""gbox.doa3_writer: costume XPR0 re-encode, strips, textures, CAT link disable and the AFS rebuild.

Synthetic fixtures follow the measured costume layout (see gbox.doa3_cast / gbox.doa3_writer docstrings); the
owned-disc identity check (68/68 costumes byte for byte) runs where the disc is present."""
import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import doa3_cast as C
from gbox import doa3_writer as W
from gbox.doa3_inventory import read_afs


def _seed(obj_count: int, textures) -> bytes:
    """Hand-laid costume: obj_count OBJs of 4 vertices / one 2-triangle strip, then the descriptor table."""
    hdr = C.MDL_CHUNK + 0x14 + 4 * obj_count + 4
    records, offsets = bytearray(), []
    mat_words = C.MAT_HEADER_WORDS + 4
    rec_len = C.MAT_HEADER_BASE + 4 * mat_words + 8 + 2 * 6
    for k in range(obj_count):
        offsets.append(hdr + k * rec_len)
    last_end = hdr + obj_count * rec_len
    tail = C.VERTEX_DESC_BYTES * obj_count + C.TEXTURE_DESC_BYTES * len(textures) + 4
    hsize = W._align(last_end + tail, W.HEADER_ALIGN)
    tex_sizes = [W.texture_info(W.texture_word(c, w, h))["size"] for c, w, h in textures]
    data = 32 * 4 * obj_count
    tex_offsets = []
    for size in tex_sizes:
        data = W._align(data, W.TEXTURE_ALIGN)
        tex_offsets.append(data)
        data += size
    total = W._align(hsize + data, W.FILE_ALIGN)
    out = bytearray(total)
    struct.pack_into("<4sII", out, 0, b"XPR0", total, hsize)
    struct.pack_into("<II", out, 0x0C, C.USER_TYPE, last_end - C.MDL_CHUNK)
    out[C.MDL_CHUNK:C.MDL_CHUNK + 4] = C.MDL_TAG
    struct.pack_into("<4I", out, C.MDL_CHUNK + 4, obj_count, len(textures), 1, obj_count)
    struct.pack_into(f"<{obj_count}I", out, C.MDL_CHUNK + 0x14, *offsets)
    for k, start in enumerate(offsets):
        iptr = start + C.MAT_HEADER_BASE + 4 * mat_words + 8
        out[start:start + 4] = C.OBJ_TAG
        struct.pack_into("<7I", out, start + 4, 0, 0, 4, 4, hsize + 128 * k, 6, iptr)
        struct.pack_into("<4f", out, start + 0x50, 0.5, 0.5, 0, 1)
        header = [W.MAT_PRESENT, mat_words] + [0] * 31
        header[C.MAT_WORD_MODE], header[C.MAT_WORD_PACKETS], header[30] = 1, 1, W.MAT_RENDER_DEFAULT
        m = start + C.MAT_HEADER_BASE
        struct.pack_into(f"<{C.MAT_HEADER_WORDS}I", out, m, *header)
        struct.pack_into("<4I", out, m + 4 * C.MAT_HEADER_WORDS, 32 * 4, 0, 2, 0)
        struct.pack_into("<II", out, iptr - 8, 0, C.MAT_TERMINATOR)
        struct.pack_into("<6H", out, iptr, 0, 1, 2, 3, 3, 3)
    p = last_end
    for k in range(obj_count):
        struct.pack_into("<3I", out, p, C.VERTEX_DESC_FLAG, 128 * k, 0)
        p += C.VERTEX_DESC_BYTES
    for (c, w, h), off in zip(textures, tex_offsets):
        struct.pack_into("<5I", out, p, C.TEXTURE_DESC_FLAG, off, 0, W.texture_word(c, w, h), 0)
        p += C.TEXTURE_DESC_BYTES
    struct.pack_into("<I", out, p, C.DESC_TERMINATOR)
    out[p + 4:hsize] = bytes([C.DESC_PAD_BYTE]) * (hsize - p - 4)
    out[hsize:] = bytes([C.DESC_PAD_BYTE]) * (total - hsize)
    for k in range(obj_count):
        verts = []
        for i in range(4):
            verts += [float(i), float(i % 2), 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        struct.pack_into("<32f", out, hsize + 128 * k, *verts)
    for size, off in zip(tex_sizes, tex_offsets):
        out[hsize + off:hsize + off + size] = bytes(size)
    return bytes(out)


def test_seed_is_a_valid_costume_and_reencodes_byte_for_byte():
    seed = _seed(2, ((W.DXT1, 8, 8), (W.DXT5, 4, 4)))
    geo = C.costume_geometry(seed)
    assert geo["object_count"] == 2 and geo["triangle_total"] == 4
    assert C.mdl_descriptor_table(seed)["texture_count"] == 2
    assert W.encode_costume(seed) == seed


def test_texture_words_match_the_native_encoding():
    assert W.texture_word(W.DXT1, 256, 256) == 0x08810C2A          # zac00 texture 7
    assert W.texture_word(W.DXT5, 128, 256) == 0x08710F2A          # zac00 texture 0
    info = W.texture_info(0x06810F2A)
    assert (info["kind"], info["width"], info["height"], info["size"]) == ("DXT5", 256, 64, 256 * 64)
    with pytest.raises(ValueError):
        W.texture_word(W.DXT1, 100, 64)


def test_stripify_round_trips_through_the_costume_decode_rule():
    rng = np.random.default_rng(3)
    # a 6x6 grid of quads, counter-clockwise, in shuffled order
    tris = []
    for y in range(6):
        for x in range(6):
            a, b, c, d = y * 7 + x, y * 7 + x + 1, (y + 1) * 7 + x, (y + 1) * 7 + x + 1
            tris += [(a, b, d), (a, d, c)]
    tris = [tris[i] for i in rng.permutation(len(tris))]
    strips = W.stripify(tris)
    indices, packets = W.strip_buffer(strips)
    decoded = W.decode_buffer(indices, packets)

    def canon(t):
        k = t.index(min(t))
        return t[k:] + t[:k]                                       # rotation keeps the winding
    assert sorted(canon(tuple(t)) for t in decoded) == sorted(canon(tuple(t)) for t in tris)
    assert len(strips) < len(tris)                                  # strips actually join triangles
    assert sum(n for _, n in packets) == len(tris)


def test_replaced_part_keeps_native_vertex_floor_and_decodes():
    seed = _seed(2, ((W.DXT1, 8, 8),))
    verts = np.zeros((3, 8), np.float32)
    verts[:, :3] = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    verts[:, 5] = 1
    word, payload = W.encode_texture(np.full((16, 16, 4), 200, np.uint8))
    blob = W.encode_costume(seed, {1: {"vertices": verts, "materials": [{"texture": 1, "triangles": [(0, 1, 2)]}]}},
                            [(word, payload)])
    geo = C.costume_geometry(blob)
    obj = geo["objects"][1]
    assert obj["vertex_count"] == 4                                 # padded up to the native 4
    assert obj["triangles"] == [(0, 1, 2)]
    assert obj["materials"][0]["texture"] == 1
    table = C.mdl_descriptor_table(blob)
    assert table["texture_count"] == 2 and table["texture_descriptors"][1]["format"] == word
    assert geo["objects"][0]["triangle_count"] == 2                 # the untouched OBJ is native
    sphere = struct.unpack("<4f", blob[obj["offset"] + 0x50:obj["offset"] + 0x60])
    assert sphere[:3] == pytest.approx((0.5, 0.5, 0.0)) and sphere[3] == pytest.approx(0.7071, abs=1e-3)


def test_hidden_part_collapses_every_vertex_and_keeps_its_records():
    seed = _seed(2, ((W.DXT1, 8, 8),))
    blob = W.encode_costume(seed, hide={0})
    a, b = C.costume_geometry(seed)["objects"][0], C.costume_geometry(blob)["objects"][0]
    assert a["index_bytes"] == b["index_bytes"] and a["materials"][0]["header"] == b["materials"][0]["header"]
    assert {v[:3] for v in b["vertices"]} == {b["vertices"][0][:3]}


def test_shrunk_texture_becomes_a_4x4_stand_in():
    seed = _seed(1, ((W.DXT1, 64, 64), (W.DXT5, 32, 32)))
    blob = W.encode_costume(seed, shrink_textures={0})
    table = C.mdl_descriptor_table(blob)
    assert W.texture_info(table["texture_descriptors"][0]["format"])[ "width"] == 4
    assert table["texture_descriptors"][1]["format"] == W.texture_word(W.DXT5, 32, 32)
    assert len(blob) <= len(seed)


def test_encode_texture_picks_dxt5_only_for_alpha():
    opaque = np.zeros((30, 50, 4), np.uint8)
    opaque[..., 3] = 255
    word, data = W.encode_texture(opaque)
    info = W.texture_info(word)
    assert info["kind"] == "DXT1" and (info["width"], info["height"]) == (64, 32) and len(data) == info["size"]
    cut = opaque.copy()
    cut[:4, :4, 3] = 0
    assert W.texture_info(W.encode_texture(cut)[0])["kind"] == "DXT5"


def make_cat_with_links() -> bytes:
    body_groups = 3
    at = 0x40
    size = 0x40
    out = bytearray(at + 8 + 4 * C.LNK_HEADER_WORDS + size + 16)
    struct.pack_into("<8I", out, 0, 1, 0x14, 0x20, at, len(out), 0x100, 1, 0x18)
    out[at:at + 4] = C.LNK_MARKER
    out[at + 4:at + 8] = C.LNK_NAME
    struct.pack_into("<6I", out, at + 8, *C.LNK_HEADER, size, 0, 0)
    body = at + 8 + 4 * C.LNK_HEADER_WORDS
    struct.pack_into(f"<{1 + body_groups}I", out, body, body_groups, 0xFFFFFFFF, 0x20, 0xFFFFFFFF)
    struct.pack_into("<4I", out, body + 16, 1, 4, 8, 12)            # the C1 sub-block table
    return bytes(out)


def test_disable_cat_links_marks_every_group_absent():
    cat = make_cat_with_links()
    assert C.cat_lnk_body(cat)["link_group_entries"] == [0xFFFFFFFF, 0x20, 0xFFFFFFFF]
    out = W.disable_cat_links(cat)
    assert C.cat_lnk_body(out)["link_group_entries"] == [0xFFFFFFFF] * 3
    assert len(out) == len(cat)
    no_lnk = bytes(make_cat_with_links()).replace(C.LNK_MARKER, b"XXX\x00")
    assert W.disable_cat_links(no_lnk) == no_lnk


def make_cri_afs(payloads: list[bytes], names: list[str]) -> bytes:
    """A CRI-style AFS: TOC, the name-directory pair in the 8 bytes before the first entry, 2048-aligned entries,
    the 48-byte name records at the end."""
    n = len(payloads)
    first = 0x800
    offsets, cursor = [], first
    for p in payloads:
        offsets.append(cursor)
        cursor = W._align(cursor + len(p), W.AFS_ALIGN)
    name_dir = cursor
    total = W._align(name_dir + 48 * n, W.AFS_ALIGN)
    out = bytearray(total)
    out[:4] = b"AFS\x00"
    struct.pack_into("<I", out, 4, n)
    for k, (o, p) in enumerate(zip(offsets, payloads)):
        struct.pack_into("<II", out, 8 + 8 * k, o, len(p))
        out[o:o + len(p)] = p
        rec = name_dir + 48 * k
        out[rec:rec + len(names[k])] = names[k].encode()
        struct.pack_into("<I", out, rec + 44, len(p))
    struct.pack_into("<II", out, first - 8, name_dir, 48 * n)
    return bytes(out)


def test_afs_rebuild_in_place_and_moved_entries(tmp_path):
    src = tmp_path / "loadfile.afs"
    src.write_bytes(make_cri_afs([b"A" * 100, b"B" * 3000, b"C" * 10], ["a.xpr", "b.xpr", "c.cat"]))
    before = src.read_bytes()
    out = tmp_path / "out.afs"
    result = W.afs_rebuild(src, out, {0: b"x" * 2048, 2: b"y" * 5000})
    assert result["in_place"] == [0] and result["moved_to_end"] == [2]
    assert src.read_bytes() == before                               # the source is only read
    entries = {e["name"]: e for e in read_afs(out)["entries"]}
    data = out.read_bytes()
    a, b, c = entries["a.xpr"], entries["b.xpr"], entries["c.cat"]
    assert data[a["offset"]:a["offset"] + a["size"]] == b"x" * 2048
    assert data[b["offset"]:b["offset"] + b["size"]] == b"B" * 3000
    assert data[c["offset"]:c["offset"] + c["size"]] == b"y" * 5000 and c["offset"] >= len(before)
    assert not any(e.get("name_size_mismatch") for e in entries.values())


def test_build_disc_links_the_disc_and_points_at_its_xbe(tmp_path):
    disc = tmp_path / "src"
    disc.mkdir()
    (disc / "default.xbe").write_bytes(b"XBEH" + bytes(60))
    (disc / "bgm.afs").write_bytes(b"music")
    (disc / "loadfile.afs").write_bytes(make_cri_afs([b"A" * 100], ["a.xpr"]))
    meta = W.build_disc(disc, tmp_path / "mod", {0: b"z" * 50}, name="doa3_test", game_id=C.GAME_ID,
                        record={"kind": "test"})
    assert meta["image"] == "disc/default.xbe" and meta["kind"] == "test"
    assert (tmp_path / "mod" / "disc" / "bgm.afs").read_bytes() == b"music"
    assert (tmp_path / "mod" / ".gbox-mod.json").is_file()
    entries = read_afs(tmp_path / "mod" / "disc" / "loadfile.afs")["entries"]
    assert entries[0]["size"] == 50


def _owned_loadfile():
    path = Path(os.environ.get("GBOX_DOA3_LOADFILE") or Path.home() / "gBox_alt" / "gbox-cache" / C.GAME_ID
                / "extract" / "Dead or Alive 3" / "loadfile.afs")
    return path if path.is_file() else None


@pytest.mark.skipif(_owned_loadfile() is None, reason="the owned DOA3 loadfile.afs is not on this machine")
def test_owned_costumes_reencode_byte_for_byte():
    afs = _owned_loadfile()
    checked = 0
    with afs.open("rb") as stream:
        for e in read_afs(afs)["entries"]:
            name = e.get("name") or ""
            if not name.endswith(".xpr") or len(name) != 9 or name == "lei04.xpr":
                continue
            stream.seek(e["offset"])
            blob = stream.read(e["size"])
            try:
                C.mdl_chunk(blob)
            except ValueError:
                continue
            assert W.encode_costume(blob) == blob, name
            checked += 1
    assert checked == 68
