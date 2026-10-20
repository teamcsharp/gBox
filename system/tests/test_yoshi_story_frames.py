"""Frame-decoder probes for Yoshi's Story sprites (#1323, analysis stage)."""
import os
from pathlib import Path

import pytest

from gbox import yoshi_story_frames as yf

ROM = Path(os.environ.get("GBOX_YS_ROM", Path.home() / "gBox_alt/gbox-cache/14da9d54679e0100/rom.z64"))


def test_prologue_signature_and_tri_decode():
    # G_VTX prologue: 24 verts, 0x180 bytes, from segment 3 offset 0x200.
    assert yf._w(b"\x04\x00\x61\x7f", 0) == 0x0400617F
    # G_TRI2 (gsSP2Triangles) packs two triangles with 6-bit vertex indices.
    assert yf._tri_indices(0xB1000204, 0x00000406) == ((0, 1, 2), (0, 2, 3))


@pytest.fixture(scope="module")
def rom():
    if not ROM.exists():
        pytest.skip("owned Yoshi's Story ROM cache not present")
    data = ROM.read_bytes()
    if data[0x3B:0x3F] != b"NYSE":
        pytest.skip("cached ROM is not NYSE")
    import hashlib
    assert hashlib.sha256(data).hexdigest()=="e8a63388c38f8f0bea37e9b13a97f0898ac5496e08ca2028afb8db9a866e0ce9"
    return data


def test_frame_records_are_prologue_terminated(rom):
    recs = yf.frame_records(rom)
    assert recs, "no frame records found"
    assert recs[0] == 0x9E6C00
    assert len(recs) >= 1180
    assert all(r % yf.FRAME_ALIGN == 0 for r in recs)
    # the CI8 atlas just before the bank contains the prologue pattern by
    # chance but must NOT be counted (it does not start with G_SETTIMG)
    assert 0x9E6800 not in recs


def test_vertex_block_decodes(rom):
    verts = yf.decode_vertices(rom, 0x9E6C00)
    assert len(verts) == 24
    v0 = verts[0]
    assert (v0["x"], v0["y"], v0["z"]) == (-12, -4, 0)
    assert (v0["s"], v0["t"]) == (0, 0)
    assert v0["rgba"] == (0xFF, 0xFF, 0xFF, 0xFF)
    # unused trailing vertices are zero-filled
    assert all(v["x"] == v["y"] == 0 for v in verts[20:])


def test_parse_frame_tiles_and_triangles(rom):
    f = yf.parse_frame(rom, 0x9E6C00)
    assert f["tlut"] == {"seg3": 0x400, "colors": 256}
    assert len(f["tiles"]) == 6
    assert all(t["fmt"] == "CI" and t["bpp"] == 8 for t in f["tiles"])
    assert f["tiles"][0]["seg3"] == 0x8400
    assert f["tiles"][0]["load_units"] == 168
    assert f["tiles"][0]["load_bytes"] == 336
    assert f["tiles"][0]["texels"] == 336
    assert (f["tiles"][0]["width"],f["tiles"][0]["height"]) == (24,14)
    assert len(f["triangles"]) == 12  # 6 quads -> 12 triangles
    # indices stay within the 24-vertex block
    assert all(all(0 <= i < 24 for i in t) for t in f["triangles"])
    # the first five quads use populated vertices; the sixth (tile 0x5400) is a
    # degenerate quad that references the zero-filled verts 20-23 (the frame
    # template always carries 6 quads even when only 5 are drawn).
    used = [i for i, v in enumerate(f["vertices"]) if v["x"] or v["y"]]
    assert all(all(i in used for i in t) for t in f["triangles"][:10])


def test_render_frame_png(rom, tmp_path):
    out = tmp_path / "frame_0x9E6C00.png"
    r = yf.render_frame_png(rom, 0x9E6C00, out)
    assert out.exists()
    assert r["tiles"] == 6 and r["triangles"] == 12
    from PIL import Image
    im = Image.open(out).convert("RGB")
    colours = im.getcolors(maxcolors=1 << 20) or []
    non_bg = [c for n, c in colours if c != (24, 24, 24)]
    assert non_bg, "rendered frame is blank"


def frame():
    # Independent GBI1 encodings: TRI1 indices in word1; B8 ends the list.
    b=bytearray(0x400)
    b[:32]=bytes.fromhex('fd50000003008400 bf00000000020406 b800000000000000 bf00000000303234')
    b[0x3f8:]=bytes.fromhex('0400617f03000200')
    return b

def test_gbi1_triangle_word_and_end_command():
    result=yf.parse_frame(frame(),0)
    assert result['triangles']==[(1,2,3)] and result['textured'] is False

@pytest.mark.parametrize('encoded',['00300204','00800204'])
def test_triangle_indices_do_not_wrap_into_valid_cache(encoded):
    b=frame();b[12:16]=bytes.fromhex(encoded)
    with pytest.raises(ValueError,match='outside frame'):yf.parse_frame(b,0)

def test_negative_offsets_and_truncated_vertices():
    b=frame();assert not yf.prologue(b,-1)
    with pytest.raises(ValueError):yf.decode_vertex(b,-16)
    with pytest.raises(ValueError):yf.decode_vertices(b,-0x200)
    with pytest.raises(ValueError):yf.frame_records(b,-1)
    with pytest.raises(ValueError):yf.parse_frame(b,-0x400)
    with pytest.raises(ValueError):yf.decode_vertex(bytes(15),0)

def test_degenerate_frame_preview_is_bounded_and_explicit(tmp_path):
    result=yf.render_frame_png(frame(),0,tmp_path/'flat.png')
    assert result['size']==(18,18) and result['textured'] is False
    with pytest.raises(ValueError):yf.render_frame_png(frame(),0,tmp_path/'bad.png',scale=0)
    with pytest.raises(ValueError,match='pixel limit'):yf.render_frame_png(frame(),0,tmp_path/'huge.png',scale=10000)

def test_all_owned_frames_have_valid_triangles_and_texture_units(rom):
    records=yf.frame_records(rom)
    for rec in records:
        result=yf.parse_frame(rom,rec)
        assert result['triangles']
        assert all(i<24 for tri in result['triangles'] for i in tri)
        for tile in result['tiles']:
            assert tile['load_units']>0 and tile['load_bytes']>0
            assert tile['texels']*tile['bpp']==tile['load_units']*tile['load_bpp']
