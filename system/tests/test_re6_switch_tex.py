"""RE6 Switch TEX reader/writer tests.

The synthetic tests need nothing; the ones marked `needs_arc` read the extracted RomFS and skip when it is absent
(`GBOX_RE6_SWITCH_ROMFS` names its root, the folder that holds `nativeNXx64`).
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import mt_arc, re6_switch_tex as X

ROMFS = Path(os.environ.get("GBOX_RE6_SWITCH_ROMFS", r"C:\_tools\gBox\.tmp\re6sw_romfs"))
ARC = ROMFS / "nativeNXx64" / "arc" / "NX" / "uPlTex0000_0.arc"
PACKAGE = ROMFS / "nativeNXx64" / "system" / "app_shader" / "AppShaderPackage.mfx"
needs_arc = pytest.mark.skipif(not ARC.is_file(), reason="the extracted RE6 Switch RomFS is not present")


def _surfaces(path: Path = ARC) -> dict[str, X.Surface]:
    out = {}
    for entry in mt_arc.parse(path.read_bytes()).entries:
        try:
            out[entry.name.rsplit("\\", 1)[-1]] = X.from_arc_entry(entry)
        except X.TexError:
            continue
    return out


def _legacy_tex(rgb, size: int = 8) -> X.Surface:
    """A surface as the pre-fix encoder wrote it: luma in the alpha block, the plain RGB colour in a flat 565 block."""
    r, g, b = rgb
    luma = (r * 299 + g * 587 + b * 114) // 1000
    colour = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    block = bytes((luma, luma, 0, 0, 0, 0, 0, 0)) + struct.pack("<HHI", colour, colour, 0)
    return X.Surface(X.pack_tex(0x2B, size, size, [block * ((size // 4) ** 2)]))


# --- layout and writers (no assets) --------------------------------------------------

def test_storage_sizes_match_the_measured_native_mips():
    # pl0000_50_jacket_MVTF: 128x128 RGBA8, eight mips, 89088 bytes
    sizes = [X.storage_size(*X.mip_grid(128, 128, 0x09, mip)) for mip in range(8)]
    assert sizes == [65536, 16384, 4096, 1024, 512, 512, 512, 512] and sum(sizes) == 89088
    # pl_VTF: 128x4 float32, one mip: four real rows in an eight-row GOB
    assert X.storage_size(*X.mip_grid(128, 4, 0x0E)) == 4096
    # pl0000_00jacket_BM: 1024x1024 0x2B, eleven mips, 1400320 bytes; pl0000_00jacket_MM: 512x512 BC4, ten mips
    assert sum(X.storage_size(*X.mip_grid(1024, 1024, 0x2B, mip)) for mip in range(11)) == 1400320
    assert sum(X.storage_size(*X.mip_grid(512, 512, 0x19, mip)) for mip in range(10)) == 177152
    with pytest.raises(X.TexError):
        X.unit_of(0x14)                                       # seen once in Chris' set, never measured


def test_pack_tex_writes_the_native_header_and_reads_back():
    rng = np.random.default_rng(7)
    for fmt, width, height, mips in ((0x09, 16, 8, 4), (0x0E, 128, 4, 1), (0x2B, 64, 32, 6), (0x19, 16, 16, 3)):
        levels = []
        for mip in range(mips):
            columns, rows, unit = X.mip_grid(width, height, fmt, mip)
            levels.append(rng.integers(0, 256, columns * rows * unit, dtype=np.uint8).tobytes())
        data = X.pack_tex(fmt, width, height, levels)
        assert data[:8] == b"TEX\0\xa1\x20\x00\x20"
        assert struct.unpack_from("<I", data, 12)[0] == 0x00010001 | (fmt << 8)
        surface = X.parse(data)
        assert (surface.format, surface.width, surface.height, surface.mip_count) == (fmt, width, height, mips)
        assert [surface.linear_blocks(mip) for mip in range(mips)] == levels
    with pytest.raises(X.TexError):
        X.pack_tex(0x09, 8, 8, [b"\0" * 10])


def test_a_grey_tile_is_the_native_constant_block():
    blocks = X.encode_albedo(np.full((8, 12, 3), 77, np.uint8))
    assert len(blocks) == 6 * 16
    for index in range(6):
        block = blocks[index * 16:(index + 1) * 16]
        assert block[:8] == bytes((77, 77, 0, 0, 0, 0, 0, 0))              # flat luma, native flat form
        assert block[8:] == X.NEUTRAL_COLOUR_BLOCK == bytes.fromhex("ef7fef7faaaaaaaa")
    c0, c1, indices = struct.unpack("<HHI", X.NEUTRAL_COLOUR_BLOCK)
    assert (c0, c1, indices) == (0x7FEF, 0x7FEF, 0xAAAAAAAA)


def test_chroma_off_keeps_every_second_half_constant():
    yy, xx = np.mgrid[0:32, 0:32]
    image = np.dstack([xx * 8, yy * 8, 255 - xx * 8]).astype(np.uint8)
    blocks = np.frombuffer(X.encode_albedo(image, chroma=False), np.uint8).reshape(-1, 16)
    assert (blocks[:, 8:] == np.frombuffer(X.NEUTRAL_COLOUR_BLOCK, np.uint8)).all()
    coloured = np.frombuffer(X.encode_albedo(image), np.uint8).reshape(-1, 16)
    assert (coloured[:, :8] == blocks[:, :8]).all()               # the luma half does not depend on the switch
    assert not (coloured[:, 8:] == blocks[:, 8:]).all()


@pytest.mark.parametrize("colour", [(255, 0, 0), (0, 0, 255), (0, 255, 0), (255, 255, 255), (0, 0, 0),
                                    (30, 70, 200), (255, 128, 0), (240, 200, 160)])
def test_a_solid_colour_survives_the_albedo_round_trip(colour):
    template = X.pack_tex(0x2B, 16, 16, [bytes(16 * 16), bytes(16 * 4), bytes(16)])
    surface = X.parse(X.solid_albedo(template, colour))
    assert (surface.width, surface.height, surface.mip_count) == (16, 16, 3)
    for mip in range(3):
        rgb, alpha = surface.albedo(mip)
        assert np.abs(rgb.astype(int) - np.asarray(colour)).max() <= 6      # 5-bit chroma
        assert (alpha == 255).all()
    blocks = np.frombuffer(surface.linear_blocks(0), np.uint8).reshape(-1, 16)
    c0 = blocks[:, 8].astype(int) | (blocks[:, 9].astype(int) << 8)
    c1 = blocks[:, 10].astype(int) | (blocks[:, 11].astype(int) << 8)
    assert (c0 >= c1).all() and (((c0 >> 5) & 63) == 63).all()             # native ordering, opaque green


def test_a_picture_survives_the_albedo_round_trip():
    yy, xx = np.mgrid[0:64, 0:64]
    canvas = np.zeros((64, 64, 3), np.uint8)
    canvas[..., 0] = yy * 4
    canvas[..., 1] = 100
    canvas[..., 2] = xx * 4
    canvas[(yy - 32) ** 2 + (xx - 32) ** 2 < 144] = (240, 200, 40)
    template = X.pack_tex(0x2B, 64, 64, [bytes(16 * 256)])
    rgb, _alpha = X.parse(X.replace_albedo(template, canvas)).albedo()
    mse = ((rgb.astype(float) - canvas.astype(float)) ** 2).mean()
    assert 10 * np.log10(255 * 255 / mse) > 30.0


def test_opacity_goes_to_the_green_channel():
    image = np.zeros((4, 4, 4), np.uint8)
    image[..., :3] = 200
    image[..., 3] = 51
    block = X.encode_albedo(image, opacity=True)
    c0 = struct.unpack_from("<H", block, 8)[0]
    assert (c0 >> 5) & 63 == round(51 / 255 * 63) and (c0 >> 11, c0 & 31) == (15, 15)
    opaque = X.encode_albedo(image)
    assert (struct.unpack_from("<H", opaque, 8)[0] >> 5) & 63 == 63


def test_the_model_reproduces_the_colours_of_the_pre_fix_builds():
    """The earlier encoder wrote plain RGB into the colour block. Read as (Cr, opacity, Cb) those bytes give what the
    live frames showed: a white glove pink, Sonic's blue quills teal, and the solid-red probe still red."""
    white, _ = _legacy_tex((255, 255, 255)).albedo(bias=0.5)
    r, g, b = white[0, 0].astype(int)
    assert r > 240 and b > 240 and 100 < g < 140                 # pink / magenta
    quill, _ = _legacy_tex((33, 66, 166)).albedo(bias=0.5)
    r, g, b = quill[0, 0].astype(int)
    assert r < 10 and g > 100 and b > 100 and abs(g - b) < 40    # teal, no longer blue
    red, _ = _legacy_tex((255, 0, 0)).albedo(bias=0.5)
    r, g, b = red[0, 0].astype(int)
    assert r > 250 and g < 40 and b < 5                          # the red probe stays red: it could not tell


def test_ycbcr_is_the_engine_matrix():
    y, cb, cr = X.rgb_to_ycbcr(np.array([1.0, 0.0, 0.0]))
    assert abs(y - 0.299) < 1e-9 and abs(cr - 0.5) < 1e-9 and abs(cb + 0.299 / 1.772) < 1e-9
    assert np.allclose(X.ycbcr_to_rgb(0.5, 0.0, 0.0), [0.5, 0.5, 0.5])
    rgb = np.array([[0.2, 0.7, 0.4], [0.9, 0.1, 0.6]])
    assert np.allclose(X.ycbcr_to_rgb(*X.rgb_to_ycbcr(rgb)), rgb, atol=2e-5)


def test_rgba8_writer_layout_and_box_mips():
    rng = np.random.default_rng(3)
    pixels = rng.integers(0, 256, (16, 32, 4), dtype=np.uint8)
    surface = X.parse(X.rgba8_tex(pixels))
    assert (surface.format, surface.width, surface.height, surface.mip_count) == (0x09, 32, 16, 6)
    assert (surface.texels(0) == pixels).all()
    box = pixels.astype(float).reshape(8, 2, 16, 2, 4).mean((1, 3))
    assert np.abs(surface.texels(1).astype(float) - box).max() <= 0.5
    assert surface.texels(5).shape == (1, 1, 4)
    white = X.parse(X.replace_texels(X.rgba8_tex(pixels, mips=3), np.full((16, 32, 4), 255, np.uint8)))
    assert white.mip_count == 3 and all((white.texels(mip) == 255).all() for mip in range(3))
    with pytest.raises(X.TexError):
        X.rgba8_tex(np.zeros((16, 24, 4), np.uint8))               # not a power of two
    with pytest.raises(X.TexError):
        X.replace_texels(X.rgba8_tex(pixels), np.zeros((8, 8, 4), np.uint8))


def test_float_writer_layout():
    curve = np.linspace(0.0, 1.0, 128 * 4, dtype=np.float32).reshape(4, 128)
    data = X.float_tex(curve)
    assert len(data) == 20 + 4 + 4096
    surface = X.parse(data)
    assert (surface.format, surface.width, surface.height, surface.mip_count) == (0x0E, 128, 4, 1)
    assert surface.texels().dtype == np.float32 and (surface.texels() == curve).all()
    # the four real rows fill half of the eight-row GOB; the other half is zero padding
    payload = np.frombuffer(data, np.uint8, 4096, 24)
    used = np.zeros(4096, bool)
    used[X._addresses(128, 4, 4).reshape(-1)] = True
    assert used.sum() == 2048 and not payload[~used].any()
    ones = X.parse(X.replace_texels(data, np.ones((4, 128))))
    assert (ones.texels() == 1.0).all()
    with pytest.raises(X.TexError):
        X.parse(data).decode()                                    # floats are read with texels(), not as an image


def test_shader_object_names_hash_to_the_measured_ids():
    """Ids read from Leon's texture-set MRL: the upper 20 bits are the name hash the module resolves by."""
    measured = {"tAlbedoMap": 0xCD06F364, "tNormalMap": 0x22660367, "tSpecularMap": 0x0ED1B378,
                "tDetailNormalMap": 0x75A53369, "tAlbedoBlendMap": 0xFF5BE365, "tAlbedoBlend2Map": 0x57C1C3F2,
                "tVtxDisplacement": 0x4934A384, "tVtxDispMask": 0x039C0385, "FAlbedo": 0x1C76E579,
                "FColorMaskAlbedoMapModulate": 0x9F2AAB02, "FAlbedoMap2": 0xEE344B03,
                "FVertexDisplacement": 0x5E6C564E, "FVertexDisplacementCurveUV": 0x69C6B651,
                "CBMaterial": 0x6C801209, "CBColorMask": 0x6F01632C, "CBVertexDisplacement": 0x1541923D}
    for name, value in measured.items():
        assert X.object_hash(name) == value >> 12, name
        assert X._object_name(value, None) == name
    assert X._object_name(0x12345678, None) is None


@needs_arc
def test_describe_lists_the_measured_formats():
    rows = X.describe_arc(mt_arc.parse(ARC.read_bytes()))
    assert len(rows) >= 20
    formats = {row["format"] for row in rows}
    assert {0x19, 0x1F, 0x2B} <= formats
    normal = next(row for row in rows if row["name"].endswith("_NM"))
    assert normal["format"] == 0x1F and normal["block_bytes"] == 16
    albedo = next(row for row in rows if row["name"].endswith("_BM"))
    assert albedo["format"] == 0x2B and albedo["decodable"] is True


@needs_arc
def test_a_normal_map_decodes_to_a_normal_map():
    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("_NM"))
    surface = X.from_arc_entry(entry)
    assert surface.format == 0x1F
    image = surface.decode()
    assert image.size == (surface.width, surface.height)
    colours = {image.getpixel((x, y))[:3] for x in range(0, image.width, 16) for y in range(0, image.height, 16)}
    assert len(colours) > 3


@needs_arc
def test_material_texture_bindings():
    """Each texture-set material lists its texture indices; the body materials map to their part albedos."""
    body_arc = ROMFS / "nativeNXx64" / "arc" / "NX" / "uPlTex0010_2.arc"
    if not body_arc.is_file():
        pytest.skip("the body texture set is not present")
    arc = mt_arc.parse(body_arc.read_bytes())
    sets = X.texture_set_materials(arc)
    row = next(material for texture_set in sets for material in texture_set["materials"]
               if material["name_hash"] == 0x68B3D093)
    assert row["textures"] == [3, 4, 5, 6]                       # hand NM/BM, blood, hand MM
    body = X.body_albedo_paths(arc)
    assert any(path.endswith("pl0010_25_shoes_BM") for path in body["pl_base2"])
    assert any(path.endswith("pl0010_23_bottom_BM") for path in body["pl_base1"])
    assert any(path.endswith("pl0010_24_hand_BM") for path in body["pl_skin"])


@needs_arc
def test_the_texture_set_mrl_lists_the_bindings():
    """Each uPlTex arc ends with an MRL v36 that names 17 texture paths - the binding the body MRL lacks."""
    arc = mt_arc.parse(ARC.read_bytes())
    info = X.texture_set_mrl(arc)
    assert info["version"] == 36
    assert info["materials"] == 10 and info["textures"] == 17
    assert all(path.startswith("data\\chara\\") for path in info["paths"])
    assert any(path.endswith("pl0000_00head_NM") for path in info["paths"])
    assert any(path.endswith("pl_Blood_BM") for path in info["paths"])


@needs_arc
def test_export_textures_writes_pngs(tmp_path):
    rows = X.export_textures(ROMFS, "leon", tmp_path, formats=(0x2B,))
    done = [row for row in rows if row.get("png")]
    assert done and all(row["format"] == 0x2B for row in done)
    assert all(Path(row["png"]).is_file() for row in done)
    assert len(done) >= 5


@needs_arc
def test_the_albedo_encoder_round_trips_through_a_real_tex():
    import numpy as np
    from PIL import Image

    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("eye_BM"))
    template = X.from_arc_entry(entry)
    width, height = template.width, template.height
    yy, xx = np.mgrid[0:height, 0:width]
    canvas = np.zeros((height, width, 3), np.uint8)
    canvas[..., 0] = (yy * 255 // max(1, height - 1)).astype(np.uint8)
    canvas[..., 1] = 100
    canvas[..., 2] = (xx * 255 // max(1, width - 1)).astype(np.uint8)
    canvas[(yy - height // 2) ** 2 + (xx - width // 2) ** 2 < (min(width, height) // 5) ** 2] = (240, 200, 40)
    written = X.replace_albedo(template.data, canvas)
    surface = X.parse(written)
    assert (surface.width, surface.height, surface.mip_count) == (template.width, template.height, template.mip_count)
    assert surface.format == 0x2B
    decoded = np.asarray(surface.decode().convert("L"), float)
    source = np.asarray(Image.fromarray(
        (0.299 * canvas[..., 0] + 0.587 * canvas[..., 1] + 0.114 * canvas[..., 2]).astype(np.uint8)).convert("L"), float)
    mse = ((decoded - source) ** 2).mean()
    assert 10 * np.log10(255 * 255 / mse) > 25.0


@needs_arc
def test_the_albedo_decodes_its_detail_layer():
    """0x2B blocks are BC4 detail (bytes 0-7) + a BC1 half (bytes 8-15); the detail layer must be a real image."""
    arc = mt_arc.parse(ARC.read_bytes())
    entry = next(e for e in arc.entries if e.name.endswith("_BM"))
    surface = X.from_arc_entry(entry)
    assert surface.format == 0x2B
    image = surface.decode()
    assert image.size == (surface.width, surface.height)
    grey = image.convert("L")
    values = [grey.getpixel((x, y)) for x in range(0, grey.width, 32) for y in range(0, grey.height, 32)]
    assert max(values) - min(values) > 32                  # a detail map, not a flat fill
    detail, tint = surface._albedo_layers()
    assert detail.shape == (surface.height, surface.width)
    assert tint.shape == (surface.height, surface.width, 3)


# --- the native data behind the colour model -----------------------------------------

@needs_arc
def test_every_native_surface_repacks_byte_for_byte():
    """Header, block-linear layout and zero padding, for all five measured formats (RGBA8 and float32 included)."""
    seen = set()
    for name, surface in _surfaces().items():
        levels = [surface.linear_blocks(mip) for mip in range(surface.mip_count)]
        assert X.pack_tex(surface.format, surface.width, surface.height, levels) == surface.data, name
        seen.add(surface.format)
    assert seen == {0x09, 0x0E, 0x19, 0x1F, 0x2B}


@needs_arc
def test_the_second_half_of_a_native_albedo_is_chroma_not_a_constant():
    """Only neutral tiles hold the constant block; skin and hair do not, and green carries the opacity."""
    surfaces = _surfaces()
    constant = np.frombuffer(X.NEUTRAL_COLOUR_BLOCK, np.uint8)

    def blocks(name):
        return np.frombuffer(surfaces[name].linear_blocks(0), np.uint8).reshape(-1, 16)

    def share(name):
        return float((blocks(name)[:, 8:] == constant).all(1).mean())

    assert share("pl0000_00eyeCov_BM") == 1.0                    # a black cover: every tile neutral
    assert share("pl0000_10Hand_BM") == 0.0                      # skin: no neutral tile at all
    assert share("pl0000_00head_BM") < 0.2 and share("pl0000_00jacket_BM") < 0.05
    hand = blocks("pl0000_10Hand_BM")
    c0 = hand[:, 8].astype(int) | (hand[:, 9].astype(int) << 8)
    red, green, blue = c0 >> 11, (c0 >> 5) & 63, c0 & 31
    assert (green == 63).all()                                   # opaque
    assert red.mean() > 15.5 > blue.mean()                       # Cr above neutral, Cb below: skin
    hair = blocks("pl0000_00hair_BM")
    hair_green = ((hair[:, 8].astype(int) | (hair[:, 9].astype(int) << 8)) >> 5) & 63
    assert hair_green.min() == 0 and hair_green.max() == 63      # hair cards: the cut-out lives in green


@needs_arc
def test_native_albedos_decode_to_their_own_colours():
    surfaces = _surfaces()
    hand, alpha = surfaces["pl0000_10Hand_BM"].albedo()
    r, g, b = hand.reshape(-1, 3).mean(0)
    assert r > g > b and r - b > 40 and (alpha == 255).all()     # skin tone
    eye, _ = surfaces["pl0000_00eye_BM"].albedo()
    iris = eye[52:76, 52:76].reshape(-1, 3).astype(float).mean(0)
    assert iris[2] > iris[0]                                     # Leon's iris is blue-grey
    cover, _ = surfaces["pl0000_00eyeCov_BM"].albedo()
    assert not cover.any()                                       # neutral tiles decode to exact black
    image = surfaces["pl0000_00head_BM"].decode()
    assert image.mode == "RGBA" and image.size == (1024, 1024)
    face = np.asarray(image)[300:500, 400:620, :3].reshape(-1, 3).astype(float).mean(0)
    assert face[0] > face[1] > face[2] and face[0] > 150


@needs_arc
def test_a_native_albedo_survives_decode_and_re_encode():
    head = _surfaces()["pl0000_00head_BM"]
    rgb, _alpha = head.albedo()
    again = X.parse(X.replace_albedo(head.data, rgb))
    assert (again.width, again.height, again.mip_count, len(again.data)) == (1024, 1024, 11, len(head.data))
    back, _ = again.albedo()
    mse = ((rgb.astype(float) - back.astype(float)) ** 2).mean()
    assert 10 * np.log10(255 * 255 / mse) > 40.0
    grey = np.frombuffer(X.parse(X.replace_albedo(head.data, rgb, chroma=False)).linear_blocks(0),
                         np.uint8).reshape(-1, 16)
    assert (grey[:, 8:] == np.frombuffer(X.NEUTRAL_COLOUR_BLOCK, np.uint8)).all()


@needs_arc
def test_vtf_and_mvtf_are_the_cloth_displacement_inputs_not_colour():
    """The jacket material binds `pl_VTF` to tVtxDisplacement and its `_MVTF` to tVtxDispMask; its colour is the
    albedo, a white diffuse constant and the blood tint whose thresholds are zero at rest."""
    sets = X.texture_set_materials(mt_arc.parse(ARC.read_bytes()))
    body = next(s for s in sets if s["entry"] == "pl0000_0")
    assert body["shader"] == 0xB43F437C
    by_name = {m["name"]: m for m in body["materials"]}
    assert set(by_name) == {"pl_cloth", "pl_cloth1", "pl_base1", "pl_base2", "pl_skin"}
    jacket = by_name["pl_cloth"]
    assert jacket["slots"]["tVtxDisplacement"].endswith("\\pl_VTF")
    assert jacket["slots"]["tVtxDispMask"].endswith("pl0000_50_jacket_MVTF")
    assert jacket["functions"]["FVertexDisplacement"] == "FVertexDisplacementCurveUV"
    assert jacket["slots"]["tAlbedoMap"].endswith("pl0000_00jacket_BM")
    assert jacket["slots"]["tAlbedoBlend2Map"].endswith("pl_Blood_BM")
    assert jacket["functions"]["FAlbedo"] == "FColorMaskAlbedoMapModulate"
    assert jacket["constants"]["CBMaterial"]["fDiffuseColor"] == [1.0, 1.0, 1.0]
    mask = jacket["constants"]["CBColorMask"]
    assert mask["fColorMaskThreshold"] == [0.0] * 4 and mask["fColorMaskOffset"] == [0.0] * 4
    assert [round(v, 2) for v in mask["fColorMaskColor"]] == [0.45, 0.05, 0.09, 1.0]      # blood red
    assert jacket["constants"]["CBVertexDisplacement"]["fVtxDispScale"] == [0.0]
    plain = by_name["pl_base2"]                                   # the shoes/shirt material: no displacement at all
    assert "tVtxDisplacement" not in plain["slots"] and plain["functions"]["FAlbedo"] == "FAlbedoMap2"
    assert plain["functions"]["FVertexDisplacement"] == "FVertexDisplacement"
    assert X.material_bindings(mt_arc.parse(ARC.read_bytes()), "pl_skin")["slots"]["tAlbedoMap"].endswith(
        "pl0000_10Hand_BM")
    assert X.material_bindings(mt_arc.parse(ARC.read_bytes()), "pl_nothing") is None


@needs_arc
def test_the_dirt_variants_bind_differently_named_albedos():
    other = ARC.with_name("uPlTex0000_1.arc")
    if not other.is_file():
        pytest.skip("the second texture variant is not present")
    first = X.material_bindings(mt_arc.parse(ARC.read_bytes()), "pl_cloth")["slots"]["tAlbedoMap"]
    second = X.material_bindings(mt_arc.parse(other.read_bytes()), "pl_cloth")["slots"]["tAlbedoMap"]
    assert first.endswith("pl0000_00jacket_BM") and second.endswith("pl0000_70jacket_d1_BM")


@needs_arc
def test_native_vtf_is_a_float_curve():
    curve = _surfaces()["pl_VTF"]
    assert (curve.format, curve.width, curve.height, curve.mip_count) == (0x0E, 128, 4, 1)
    values = curve.texels()
    assert values.dtype == np.float32 and values.shape == (4, 128)
    assert 0.0 <= values.min() and values.max() < 1.0
    assert not values[1].any() and not values[2].any()            # two unused rows
    for row in (0, 3):                                            # a smooth wave: zero at both ends, three crests
        assert values[row, 0] == 0.0 and values[row, -1] == 0.0 and values[row].max() > 0.8
        steps = np.diff(values[row])
        assert np.abs(steps).max() < 0.07                         # smooth only when de-swizzled
        turns = np.sign(steps[steps != 0])
        assert int((turns[1:] < turns[:-1]).sum()) == 3           # crests
    raster = np.frombuffer(curve.data, "<f4", 128 * 4, curve.start).reshape(4, 128)
    assert np.abs(np.diff(raster, axis=1)).mean() > 3 * np.abs(np.diff(values, axis=1)).mean()
    assert abs(values[0, 1] * 255 - 10) < 0.01                    # the 0.0392 the first reading saw: 10/255
    assert X.float_tex(values) == curve.data                      # the writer reproduces the native file


@needs_arc
def test_native_mvtf_is_an_rgba8_mask_with_box_mips():
    mask = _surfaces()["pl0000_50_jacket_MVTF"]
    assert (mask.format, mask.width, mask.height, mask.mip_count) == (0x09, 128, 128, 8)
    top = mask.texels(0)
    assert (top[..., 3] == 255).all() and (top[..., 0] == top[..., 1]).all() and (top[..., 1] == top[..., 2]).all()
    assert int(top[..., 0].min()) == 0 and int(top[..., 0].max()) == 255
    for mip in range(1, mask.mip_count):                          # only the right layout makes each mip the box of
        above = mask.texels(mip - 1).astype(float)                # the one before it
        box = above.reshape(above.shape[0] // 2, 2, above.shape[1] // 2, 2, 4).mean((1, 3))
        assert np.abs(box - mask.texels(mip)).max() < 1.0
    raster = np.frombuffer(mask.data, np.uint8, 128 * 128 * 4, mask.start).reshape(128, 128, 4).astype(float)
    wrong = raster.reshape(64, 2, 64, 2, 4).mean((1, 3))
    assert np.abs(wrong - mask.texels(1)).mean() > 20.0           # the unswizzled reading does not
    rebuilt = X.parse(X.rgba8_tex(top))
    assert rebuilt.mips == mask.mips and rebuilt.linear_blocks(0) == mask.linear_blocks(0)
    assert all(np.abs(rebuilt.texels(mip).astype(int) - mask.texels(mip).astype(int)).max() <= 2
               for mip in range(mask.mip_count))                  # the writer's own chain: within 2/255 of native
    white = X.parse(X.replace_texels(mask.data, np.full((128, 128, 4), 255, np.uint8)))
    assert white.mips == mask.mips and len(white.data) == len(mask.data)


@pytest.mark.skipif(not (ARC.is_file() and PACKAGE.is_file()), reason="the RomFS shader package is not present")
def test_the_shader_package_names_every_binding():
    objects = X.shader_objects(PACKAGE.read_bytes())
    assert len(objects) > 2000 and objects[0xCD06F364] == "tAlbedoMap" and objects[0x4934A384] == "tVtxDisplacement"
    arc = mt_arc.parse(ARC.read_bytes())
    short = X.texture_set_materials(arc)
    full = X.texture_set_materials(arc, objects=objects)
    for a, b in zip(short, full):
        for mine, theirs in zip(a["materials"], b["materials"]):
            assert mine["slots"] == theirs["slots"]                # the embedded names miss no texture slot here
            assert mine["constants"] == theirs["constants"]
    with pytest.raises(X.TexError):
        X.shader_objects(b"nope")
