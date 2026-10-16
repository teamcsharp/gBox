"""GoldenEye 007 (Europe) model reader tests.

Run from the repository root (system/):
    python -m pytest tests/test_goldeneye_reader.py -v

Requires the normalised PAL z64 (sha256 40ff3643...) at
artifacts/source/007_GoldenEye_Europe_norm.z64 (created by the inventory
stage; see gbox/goldeneye_inventory.py).
"""
import hashlib
import json
import struct
import zlib
from pathlib import Path

import pytest

from gbox.goldeneye_files import GoldenEyeROM, GoldenEyeFormatError
from gbox import goldeneye_reader as gr

ROM = Path(__file__).resolve().parent.parent / "artifacts" / "source" / "007_GoldenEye_Europe_norm.z64"

pytestmark = pytest.mark.skipif(not ROM.exists(), reason="normalised PAL z64 not present")


@pytest.fixture(scope="module")
def ge():
    rom = ROM.read_bytes()
    assert hashlib.sha256(rom).hexdigest() == gr.PAL_Z64_SHA256
    return GoldenEyeROM.from_bytes(rom)


def test_csuitbondz_full_decode(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    assert doc["node_count"] == 79
    assert doc["opcode_nodes"] == {"0x01": 1, "0x02": 15, "0x08": 20, "0x09": 1,
                                   "0x0A": 15, "0x0D": 1, "0x17": 1, "0x18": 25}
    skel = doc["skeleton"]
    assert skel is not None and skel["num_joints"] == 16
    assert skel["vram"] == "0x80037190"
    assert len(skel["joints"]) == 16
    # every joint carries an animation bit-stream offset pair
    assert all(j["mtx_a"] >= 0 and j["mtx_b"] >= 0 for j in skel["joints"])
    assert doc["num_switches"] == 7
    assert len(doc["textures"]) == 14


def test_csuitbondz_position_records(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    pos = [n for n in doc["nodes"] if int(n["opcode"], 16) & 0xFF == 0x02]
    assert len(pos) == 15
    first = pos[0]
    assert first["record"]["origin"] == [0.0, 0.0, 0.0]  # root bone at origin
    assert first["record"]["joint_id"] == 1
    # position chains branch (legs/arms); each branch tail legitimately has
    # no child group (pointer 0 -> None).  At least two thirds name a child.
    with_child = sum(1 for n in pos if n["record"]["child_group_node"] is not None)
    assert with_child >= 10
    # payload records are 28-byte structs; chain runs are contiguous in the
    # file but different branches are not, so only check distinctness.
    offs = sorted(n["data_offset"] for n in pos)
    assert len(set(offs)) == 15


def test_csuitbondz_vertex_nodes(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    vnodes = [n for n in doc["nodes"] if int(n["opcode"], 16) & 0xFF == 0x18]
    assert len(vnodes) == 25
    total_verts = sum(n["record"]["num_vertices"] for n in vnodes)
    total_coll = sum(n["record"]["num_collision_vertices"] for n in vnodes)
    assert total_verts > 100 and total_coll > 100
    # every vertex array pointer resolves inside the file and yields records
    model = ge.read_file("CsuitbondZ")
    for n in vnodes:
        assert len(n.get("vertices", [])) == n["record"]["num_vertices"]
        assert len(n["record"]["texture_ids"]) >= 0
    # the two DLs we pinned carry the expected global texture ids
    texture_ids = sorted({t for n in vnodes for t in n["record"]["texture_ids"]})
    assert 1631 in texture_ids and 1643 in texture_ids
    # vertex records decode to plausible 16-bit coordinates
    v = vnodes[0]["vertices"][0]
    assert -1000 < v["xyz"][0] < 1000 and -1000 < v["xyz"][1] < 1000
    assert 0 <= v["rgba"][0] <= 255


def test_all_body_files_parse(ge):
    bodies = ge.body_table()
    assert len(bodies) == 80
    ok = 0
    for b in bodies:
        doc = gr.read_character(ge, b.filename)
        assert doc["node_count"] >= 1
        if doc["skeleton"]:
            assert 0 < doc["skeleton"]["num_joints"] <= 64
        ok += 1
    assert ok == 80


def test_triangle_index_space(ge):
    """The F3D_OLD GBI index space is pinned: every decoded triangle's
    node-local vertex indices fall inside the node's own vertex array."""
    doc = gr.read_character(ge, "CsuitbondZ")
    nodes = gr.parse_nodes(ge.read_file("CsuitbondZ"), doc["root_offset"])
    vnodes = [n for n in nodes if n.op == 0x18]
    total = 0
    for n in vnodes:
        nv = n.record["num_vertices"]
        assert all(0 <= i < nv for t in n.triangles for i in t), \
            f"triangle index out of range at node 0x{n.offset:04X}"
        total += len(n.triangles)
    assert total == 619  # pinned for CsuitbondZ: 619 render triangles
    # the two 64-vertex nodes use G_TRI1 (0xBF) 8-bit x10 indices too
    assert any(n.record["num_vertices"] == 64 and n.triangles for n in vnodes)


def test_gltf_export(ge, tmp_path):
    out = tmp_path / "CsuitbondZ.gltf"
    stats = gr.to_gltf(ge, "CsuitbondZ", out)
    assert stats["joints"] == 16  # implicit root + 15 position (joint) nodes
    assert stats["meshes"] == 25
    assert stats["triangles"] == 619  # real triangles, not a point cloud
    assert stats["vertices"] == 726
    gltf = json.loads(out.read_text())
    assert gltf["asset"]["version"] == "2.0"
    # self-contained: buffer is embedded, no external .bin
    assert gltf["buffers"][0]["uri"].startswith("data:")
    assert gltf["buffers"][0]["byteLength"] > 0
    # rigged: one skin over all 16 joints with inverse bind matrices
    assert len(gltf["skins"]) == 1
    skin = gltf["skins"][0]
    assert skin["joints"] == list(range(16))
    ibm = gltf["accessors"][skin["inverseBindMatrices"]]
    assert ibm["type"] == "MAT4" and ibm["count"] == 16
    # every mesh primitive is an indexed triangle list with per-vertex skinning
    for m in gltf["meshes"]:
        prim = m["primitives"][0]
        for attr in ("POSITION", "COLOR_0", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"):
            assert attr in prim["attributes"]
        assert prim["mode"] == 4 and "indices" in prim
    # mesh nodes reference the skin; joint nodes carry translations
    joint_names = {n["name"] for n in gltf["nodes"][:16]}
    assert joint_names == {f"joint{i}" for i in range(16)}
    assert all("translation" in n for n in gltf["nodes"][:16])
    assert all(n.get("skin") == 0 for n in gltf["nodes"][16:] if "mesh" in n)


def test_roster():
    ros = gr.roster()
    assert len(ros) == 80
    by_key = {r["key"]: r for r in ros}
    assert "CsuitbondZ" in by_key and "CheadbrosnanZ" in by_key
    for r in ros:
        assert r["slug"].startswith("ge_") and r["kind"] == "character"
        assert r["name"] and r["aliases"]
    # the player's tuxedo body and Bond's head are in the cast
    assert by_key["CsuitbondZ"]["slug"] == "ge_csuitbondz"


def test_dedicated_registration():
    from gbox import characters as C
    name = next((n for n, test, _r, _run in C.DEDICATED
                 if test("007 - goldeneye (europe)", "n64")), None)
    assert name == "goldeneye"
    ros = next(r for n, _t, r, _run in C.DEDICATED if n == "goldeneye")()
    assert len(ros) == 80


def test_rejects_foreign_rom():
    with pytest.raises(GoldenEyeFormatError):
        GoldenEyeROM.from_bytes(b"\x80\x37\x12\x40" + b"\0" * 1024)


def test_header_num_matrices_and_records(ge):
    # ModelFileHeader: numMatrices=21 (was mislabelled "num_records"), numRecords=0
    doc = gr.read_character(ge, "CsuitbondZ")
    assert doc["num_matrices"] == 21
    assert doc["num_records"] == 0


def test_point_usage_decodes(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    vnodes = [n for n in doc["nodes"] if int(n["opcode"], 16) & 0xFF == 0x18]
    assert len(vnodes) == 25
    for n in vnodes:
        # one s16 point index per render vertex, in vertex order
        assert "point_usage" in n
        assert len(n["point_usage"]) == n["record"]["num_vertices"]
    torso = max(vnodes, key=lambda n: n["record"]["num_vertices"])
    assert torso["record"]["num_vertices"] == 97
    assert max(torso["point_usage"]) == 96          # point pool is 0..96 (97 points)
    assert torso["point_usage"].count(-1) == 44     # -1 = unskinned/static vertex
    # fully static meshes (e.g. the first-person hand/suit shells) are all -1
    assert any(all(p == -1 for p in n["point_usage"]) for n in vnodes)


def test_group_matrix_map(ge):
    doc = gr.read_character(ge, "CsuitbondZ")
    nodes = gr.parse_nodes(ge.read_file("CsuitbondZ"), doc["root_offset"])
    owner = gr.group_matrix_map(nodes)
    assert set(owner) <= set(range(doc["num_matrices"]))
    assert len(owner) >= 19   # 15 groups own ~20 of 21 matrix slots
    assert all(0 <= j <= 15 for j in owner.values())


def test_image_entries_accumulate():
    # initimages.c image_entries_load: sizes -> cumulative offsets + total
    assert gr.image_entries_accumulate([0x754, 0x16A, 0x974]) == [0, 0x754, 0x8BE, 0x1232]
    assert gr.image_entries_accumulate([]) == [0]


def test_decode_image_rgba16():
    # 1x1 RGBA16 opaque red (R=31,G=0,B=0,A=1 -> 0xF801)
    assert gr.decode_image(b"\xF8\x01", 1, 1, gr.FMT_RGBA, gr.SIZ_16B) == \
        bytes([0xFF, 0x00, 0x00, 0xFF])
    # 1x1 RGBA16 transparent green (0x07C0)
    assert gr.decode_image(b"\x07\xC0", 1, 1, gr.FMT_RGBA, gr.SIZ_16B) == \
        bytes([0x00, 0xFF, 0x00, 0x00])
    # I8: value 0x40 -> 0x40 in all channels, opaque
    assert gr.decode_image(b"\x40", 1, 1, gr.FMT_I, gr.SIZ_8B) == bytes([0x40, 0x40, 0x40, 0xFF])
    # unsupported combo -> None
    assert gr.decode_image(b"\x00", 1, 1, gr.FMT_YUV, gr.SIZ_8B) is None
    # short input -> None (never a partial decode)
    assert gr.decode_image(b"\x00", 2, 2, gr.FMT_RGBA, gr.SIZ_16B) is None


def test_g_textures_table(ge):
    """g_Textures is pinned: 2698 x 8-byte image_entry in the data segment, each
    dataoffset (word0 low 24 bits) a per-image byte size, 0xffff terminator."""
    sizes = gr.g_textures(ge)
    assert len(sizes) == gr.G_TEXTURES_COUNT == 2698
    assert sum(sizes) == 0x2EEF18 == 3075864
    # first three sizes match the n64decomp imagelist.u.csv (COPYICON/X/DELICON)
    assert sizes[:3] == [0x754, 0x16A, 0x974]
    # image_entry is 8 bytes: word0 = {hitSound:4|hitTexture:4, u24 dataoffset}
    p = gr.G_TEXTURES_DATA_OFF
    w0 = (ge.data[p] << 24) | (ge.data[p + 1] << 16) | (ge.data[p + 2] << 8) | ge.data[p + 3]
    assert w0 & 0xFFFFFF == 0x754
    # terminator sits right after the 2698th entry
    t = gr.G_TEXTURES_DATA_OFF + 8 * 2698
    w0t = (ge.data[t] << 24) | (ge.data[t + 1] << 16) | (ge.data[t + 2] << 8) | ge.data[t + 3]
    assert w0t & 0xFFFFFF == gr.G_TEXTURES_TERMINATOR


def test_images_segment_pinned(ge):
    """_imagesSegmentRomStart = 0x8F7848; image data ends exactly at the 0xFF tail."""
    sizes = gr.g_textures(ge)
    off, size = gr.image_rom_span(sizes, 0)
    assert off == gr.IMAGES_ROM_START == 0x8F7848
    assert size == 0x754
    assert gr.IMAGES_ROM_START + sum(sizes) == 0xBE6760
    # the byte at images start is a valid 1-byte image header (bit7/6/0-5)
    hdr = ge.rom[off]
    assert hdr & 0x3F == 0  # COPYICON has no LOD / zlib / explicit-LOD flags


def test_tex_bit_reader():
    """texReadBits is MSB-first; the first byte read is the most significant."""
    br = gr.TexBitReader(bytes([0x12, 0x34]))
    assert [br.read(4) for _ in range(4)] == [0x1, 0x2, 0x3, 0x4]
    br = gr.TexBitReader(bytes([0x80, 0x00]))
    assert br.read(1) == 1 and br.read(15) == 0


def test_tex_read_uncompressed_rgba16():
    """texReadUncompressed RGBA16: bit-packed 5/5/5/1 -> RGBA8888."""
    # format(4)=1, w(8)=1, h(8)=1, comp(4)=0, then 0xF801 (opaque red)
    bits = 0b0001_00000001_00000001_0000_1111100000000001
    br = gr.TexBitReader(bits.to_bytes(5, "big"))
    fmt, w, h, comp = br.read(4), br.read(8), br.read(8), br.read(4)
    assert (fmt, w, h, comp) == (1, 1, 1, 0)
    assert gr.tex_read_uncompressed(br, w, h, fmt) == bytes([0xFF, 0x00, 0x00, 0xFF])


def test_csuitbondz_texture_headers(ge):
    """The 14 CsuitbondZ texture records resolve to real global image headers.

    The pixel bank stores them as a bitstream (format/width/height/compmethod)
    with Huffman/RLE/LOOKUP/zlib compression.  ``decode_model_texture`` now runs
    the full texInflate codec pipeline; a texture whose header overruns its
    recorded byte size (the pre-existing KNOWN ISSUE) reports ``pixels`` None
    with a note rather than a silent partial decode.
    """
    doc = gr.read_character(ge, "CsuitbondZ")
    seen = {}
    for t in doc["textures"]:
        d = gr.decode_model_texture(ge, t["index"])
        assert d["texture_id"] == t["index"]
        assert d["rom_offset"] == gr.IMAGES_ROM_START + gr.image_offsets(gr.g_textures(ge))[t["index"]]
        assert d["size"] == gr.g_textures(ge)[t["index"]]
        seen[t["index"]] = d
    # every texture id is a 12-bit global id (G_SETTEX texture_id field)
    assert all(0 <= i < 0xFFF for i in seen)
    # at least one zlib and one non-zlib codec are represented
    assert any(d.get("is_zlib") for d in seen.values())
    assert any(not d.get("is_zlib") for d in seen.values())
    # a decode either yields width*height*4 RGBA bytes or a note (no partials)
    for d in seen.values():
        if d.get("pixels") is not None:
            assert d["pixel_bytes"] == d["width"] * d["height"] * 4
        else:
            assert "note" in d


def test_g_settex_12bit_mask(ge):
    """G_SETTEX (0xC0) texture ids are the 12-bit texture_id field (w1 & 0xFFF)."""
    doc = gr.read_character(ge, "CsuitbondZ")
    vnodes = [n for n in doc["nodes"] if int(n["opcode"], 16) & 0xFF == 0x18]
    for n in vnodes:
        assert all(0 <= t < 0xFFF for t in n["record"]["texture_ids"])


# ---------------------------------------------------------------- texInflate codecs

def _bits(s: str) -> bytes:
    """Pack a string of '0'/'1' (MSB-first) into bytes, zero-padded to a byte."""
    s += "0" * ((-len(s)) % 8)
    return int(s, 2).to_bytes(len(s) // 8, "big")


def test_tex_get_bit_size():
    # texGetBitSize(decimal) = ceil(log2(decimal))
    assert gr.tex_get_bit_size(1) == 0
    assert gr.tex_get_bit_size(2) == 1
    assert gr.tex_get_bit_size(3) == 2
    assert gr.tex_get_bit_size(4) == 2
    assert gr.tex_get_bit_size(5) == 3
    assert gr.tex_get_bit_size(8) == 3
    assert gr.tex_get_bit_size(9) == 4
    assert gr.tex_get_bit_size(256) == 8


def test_cdiv_truncates_toward_zero():
    assert gr._cdiv(7, 2) == 3
    assert gr._cdiv(-7, 2) == -3   # C truncation, not Python floor
    assert gr._cdiv(-1, 2) == 0


def test_tex_inflate_rle_literals():
    """Literal-only RLE stream: bt=1 rl=1 blocksize=8 then two literals."""
    # btfieldsize=001, rlfieldsize=001, blocksize=1000, then 0 00000101, 0 00001010
    stream = _bits("001" + "001" + "1000" + "0" + "00000101" + "0" + "00001010")
    br = gr.TexBitReader(stream)
    assert gr.tex_inflate_rle(br, 2) == [5, 10]


def test_tex_build_lookup_16bpp():
    """11-bit count then two 16-bit RGBA16 colours."""
    stream = _bits("00000000010" + "1111100000000001" + "0000011111000000")
    br = gr.TexBitReader(stream)
    n, lookup = gr.tex_build_lookup(br, 16)
    assert n == 2 and lookup == [0xF801, 0x07C0]


def test_tex_channels_to_pixels_rgba16():
    """1x1 RGBA16: channels R=31,G=0,B=0,A=1 -> opaque red."""
    rgba = gr.tex_channels_to_pixels([31, 0, 0, 1], 1, 1, 1)
    assert rgba == bytes([0xFF, 0x00, 0x00, 0xFF])


def test_tex_channels_to_pixels_i8():
    """1x1 I8: intensity 0x40 -> 0x40 in all channels, opaque."""
    rgba = gr.tex_channels_to_pixels([0x40], 1, 1, 7)
    assert rgba == bytes([0x40, 0x40, 0x40, 0xFF])


def test_tex_blur_method0_left():
    """texBlur method 0: pixels = (cur + left) % chansize, chansize 256."""
    px = [10, 20]
    gr.tex_blur(px, 2, 1, 0, 256)
    assert px == [10, (20 + 256 * 2 + 10) % 256]


def test_tex_inflate_lookup():
    """1x2 LOOKUP: two indices into a 2-colour RGBA16 lookup -> two pixels."""
    lookup = [0xF801, 0x07C0]
    # bitspercolour = texGetBitSize(2) = 1; indices 0 then 1
    stream = _bits("0" + "1")
    br = gr.TexBitReader(stream)
    rgba = gr.tex_inflate_lookup(br, lookup, 2, 1, 2, 1)
    assert rgba == bytes([0xFF, 0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00, 0x00])


def test_inflate_image_pixels_zlib_ci8():
    """A 1x1 zlib paletted (RGBA16_CI8) image round-trips to opaque red."""
    co = zlib.compressobj(level=9, wbits=-15)
    raw = co.compress(bytes([0])) + co.flush()
    payload = bytes([0x40])  # header byte: bit6 = zlib
    payload += bytes([0x09, 0x00])              # format=9 (RGBA16_CI8), numcolours-1=0
    payload += (0xF801).to_bytes(2, "big")      # palette[0] = opaque red 5551
    payload += bytes([0x01, 0x01])              # width=1, height=1
    payload += b"\x11\x72" + raw                # rarezip magic + raw DEFLATE
    buf = payload + b"\x00" * 4
    result = gr.inflate_image_pixels(buf, 0, len(payload), True)
    assert result is not None
    rgba, w, h, fmt = result
    assert (w, h, fmt) == (1, 1, 9)
    assert rgba == bytes([0xFF, 0x00, 0x00, 0xFF])

