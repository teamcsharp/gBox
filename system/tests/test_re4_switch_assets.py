"""RE4 Switch asset files: every fixture here is built byte by byte in the test (no game data)."""
import io
import struct
import zlib

import numpy as np
import pytest

from gbox import re4_switch_assets as A


def pad(data, phase=0):
    return data + bytes((phase - len(data)) % 32)


def material(prims, diffuse=0, flag=0):
    header = bytearray(24)
    header[11], header[12] = flag, diffuse
    header[13] = header[14] = header[15] = header[23] = 0xFF
    return A.Material(bytes(header), prims)


def make_bin(*, bonepair=True, adjacent=True, morph=False, version=0x20030818, tail=b"", skeleton=None):
    """A 14-vertex model: a 3-triangle list+strip material and a quad material, on a 3-bone chain (or `skeleton`,
    a list of (id, parent id, (x, y, z)))."""
    skeleton = skeleton or [(i, 0xFF if i == 0 else i - 1, (0.0, 10.0 * (i + 1), float(i))) for i in range(3)]
    bones = b"".join(struct.pack("<BBH3f", ident, parent, 0, *place) for ident, parent, place in skeleton)
    weights = bytes([0, 0, 0, 1, 100, 0, 0, 0]) + bytes([1, 2, 0, 2, 80, 20, 0, 0])
    count = 14
    positions = (np.arange(count * 3, dtype="<f4").reshape(count, 3) * 0.5).tobytes()
    normals = (np.tile(np.array([[0, 0, 1]], "<f4"), (count, 1)) * A.NORMAL_SCALE).astype("<f4").tobytes()
    index = np.array([0, 1] * 7, "<u2").tobytes()
    colors = b"\xff" * (4 * count)
    uvs = (np.arange(count * 2, dtype="<f4").reshape(count, 2) / 32).tobytes()
    mats = [material([(A.PRIM_LIST, 6), (A.PRIM_STRIP, 4)], diffuse=1), material([(A.PRIM_QUADS, 4)], flag=3)]
    parts = [("bones", pad(bones)), ("weights", pad(weights))]
    if morph:
        parts.append(("morph", pad(b"\x01\x02\x03\x04" * 5)))
    if bonepair:
        parts.append(("bonepair", pad(struct.pack("<I4H", 1, 1, 0, 2, 50))))
    if adjacent:
        parts.append(("adjacent", pad(struct.pack(">HH3H", 0, 3, 0xFFFF, 2, 1))))
    parts += [("positions", pad(positions)), ("weight_index", pad(index)), ("normals", pad(normals)),
              ("weight_index2", pad(index)), ("colors", pad(colors)), ("uvs", pad(uvs)),
              ("materials", b"".join(m.encode() for m in mats) + bytes(8) + tail)]
    header = bytearray(A.BIN_HEAD)
    header[0x0C] = 0x50
    header[0x28], header[0x29] = 2, len(skeleton)
    struct.pack_into("<H", header, 0x2A, len(mats))
    struct.pack_into("<II", header, 0x38, 0xA0000300, 2)
    header[0x40] = 4
    struct.pack_into("<H", header, 0x42, 2)
    struct.pack_into("<HHI", header, 0x58, count, count, version)
    offset = A.BIN_HEAD
    for name, payload in parts:
        at, size = A.BIN_POINTERS[name]
        struct.pack_into("<Q" if size == 8 else "<I", header, at, offset)
        if name in A.BIN_LEGACY:
            struct.pack_into("<I", header, A.BIN_LEGACY[name], offset - 0x38)
        offset += len(payload)
    return bytes(header) + b"".join(payload for _name, payload in parts)


def make_tpl(count=3, pack_id=0x01000008, first=0):
    return A.Tpl([A.TplImage(64 << i, 32 << i, 0x0E if i != 1 else 3, pack_id, first + i) for i in range(count)])


def make_dat(slots):
    return A.Dat([(ext, payload) for ext, payload in slots], gap=bytes(-(16 + 8 * len(slots)) % 32)).build()


def make_udas(dat, *, sound=b"SND!" * 24, slack=b"\x01\x02" * 16, lead=bytes(0x20)):
    """The measured shape: header, 0x20 lead, DAT, residue, then a sound block with its own header."""
    block = bytearray(0x400)
    block[:0x20] = bytes.fromhex("20beb6ca") * 8
    struct.pack_into("<4I", block, 0x20, 1, len(sound), 0, 0x400)
    struct.pack_into("<I", block, 0x40, 0xFFFFFFFF)
    head = bytearray(0x400)
    head[:0x20] = A.UDAS_FILL
    start = 0x400 + len(lead)
    struct.pack_into("<4I", head, 0x20, 0, len(dat), 0, start)
    struct.pack_into("<4I", head, 0x40, 4, 0, 0, start + len(dat) + len(slack))
    struct.pack_into("<I", head, 0x60, 0xFFFFFFFF)
    return bytes(head) + lead + dat + slack + bytes(block) + sound


def gradient(width, height):
    y, x = np.mgrid[0:height, 0:width]
    return np.stack([x * 255 // max(1, width - 1), y * 255 // max(1, height - 1), (x + y) % 256,
                     np.full_like(x, 255)], 2).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------- containers

def test_udas_roundtrip_and_resize_moves_only_what_follows_the_dat():
    dat = make_dat([("BIN", make_bin()), ("TPL", make_tpl().slot()), ("", b""), ("FCV", bytes(64))])
    data = make_udas(dat)
    pack = A.Udas.parse(data)
    assert pack.build() == data and pack.entries == [(0, len(dat), 0x420), (4, 0, 0x420 + len(dat) + 32)]
    pack.dat = dat + bytes(64)
    grown = A.Udas.parse(pack.build())
    assert grown.entries[0] == (0, len(dat) + 64, 0x420) and grown.entries[1][2] == pack.entries[1][2] + 64
    assert (grown.slack, grown.rest, grown.lead) == (pack.slack, pack.rest, pack.lead)


def test_udas_single_section_pack():
    dat = make_dat([("BIN", make_bin())])
    head = bytearray(0x400)
    head[:0x20] = A.UDAS_FILL
    struct.pack_into("<4I", head, 0x20, 0, len(dat), 0, 0x400)
    struct.pack_into("<I", head, 0x40, 0xFFFFFFFF)
    data = bytes(head) + dat
    assert A.Udas.parse(data).build() == data


@pytest.mark.parametrize("damage, message", [
    (lambda d: b"\0" * 4 + d[4:], "fill"),
    (lambda d: d[:0x60] + b"\0" * 4 + d[0x64:0x400].replace(b"\xff\xff\xff\xff", b"\0" * 4) + d[0x400:], "terminator"),
    (lambda d: d[:0x20] + struct.pack("<I", 4) + d[0x24:], "not a DAT"),
    (lambda d: d[:0x24] + struct.pack("<I", 1 << 30) + d[0x28:], "outside"),
])
def test_udas_refuses_what_it_did_not_measure(damage, message):
    data = make_udas(make_dat([("BIN", make_bin())]))
    with pytest.raises(A.AssetError, match=message):
        A.Udas.parse(damage(data))


def test_dat_roundtrip_empty_slots_and_replace():
    slots = [("BIN", make_bin()), ("TPL", make_tpl().slot()), ("", b""), ("FCV", b"\xcd" * 96)]
    data = make_dat(slots)
    dat = A.Dat.parse(data)
    assert dat.build() == data and [(e, len(p)) for e, p in dat.slots] == [(e, len(p)) for e, p in slots]
    dat.replace(0, bytes(64))
    dat.replace(3, None)
    again = A.Dat.parse(dat.build())
    assert [(e, len(p)) for e, p in again.slots] == [("BIN", 64), ("TPL", len(slots[1][1])), ("", 0), ("", 0)]
    assert again.slots[1][1] == slots[1][1]
    with pytest.raises(A.AssetError, match="multiple of 32"):
        dat.replace(0, bytes(33))
    with pytest.raises(A.AssetError, match="out of range"):
        dat.replace(9, bytes(32))


def test_dat_refuses_descending_offsets():
    data = bytearray(make_dat([("BIN", bytes(32)), ("BIN", bytes(32))]))
    struct.pack_into("<I", data, 20, 8)
    with pytest.raises(A.AssetError, match="ascending"):
        A.Dat.parse(bytes(data))


# ----------------------------------------------------------------------------------------------------------- BIN

@pytest.mark.parametrize("kwargs", [{}, {"bonepair": False}, {"bonepair": False, "adjacent": False, "version": 0x20010801},
                                    {"morph": True}, {"tail": b"\x07" * 24}])
def test_bin_roundtrip_every_section_layout(kwargs):
    data = make_bin(**kwargs)
    model = A.HdBin.parse(data)
    assert model.build() == data and len(data) % 32 == (len(kwargs.get("tail", b"")) % 32)
    assert (model.vertex_count, model.bone_count, model.weight_count, model.material_count, model.texture_count) == (14, 3, 2, 2, 2)
    assert ("morph" in model.sections) == bool(kwargs.get("morph"))


def test_bin_decodes_arrays_bones_weights_and_triangles():
    model = A.HdBin.parse(make_bin())
    assert model.positions()[3].tolist() == [4.5, 5.0, 5.5] and model.uvs().shape == (14, 2)
    assert np.allclose(np.linalg.norm(model.normals(), axis=1), A.NORMAL_SCALE, rtol=1e-6)
    assert model.bones()[2][:2] == (2, 1) and model.bone_world()[2].tolist() == [0.0, 60.0, 3.0]
    part = bytearray(make_bin())                      # a part lists skeleton ids, not 0..n-1: ids 4, 26, 27
    for row, (ident, parent) in enumerate(((4, 0xFF), (26, 4), (27, 4))):
        part[A.BIN_HEAD + 16 * row:A.BIN_HEAD + 16 * row + 2] = bytes((ident, parent))
    world = A.HdBin.parse(bytes(part), verify=False).bone_world()
    assert sorted(world) == [4, 26, 27] and world[27].tolist() == [0.0, 40.0, 2.0]
    assert model.weights() == [((0, 100),), ((1, 80), (2, 20))]
    assert model.weight_index().tolist() == [0, 1] * 7 and model.colors().min() == 255
    first, second = A.triangles(model.materials())
    # list 0-5, then a strip of 4 (second triangle flipped), then one quad split into two
    assert first.tolist() == [[0, 1, 2], [3, 4, 5], [6, 7, 8], [8, 7, 9]]
    assert second.tolist() == [[10, 11, 12], [10, 12, 13]]
    assert [m.triangle_count for m in model.materials()] == [4, 2] and model.materials()[0].textures() == [1]


def test_bin_refuses_a_gamecube_header_and_broken_counts():
    data = make_bin()
    with pytest.raises(A.AssetError, match="not an HD BIN"):
        A.HdBin.parse(struct.pack("<Q", 0x60) + data[8:])
    short = bytearray(data)
    struct.pack_into("<HH", short, 0x58, 13, 13)
    with pytest.raises(A.AssetError, match="consume the vertex array"):
        A.HdBin.parse(bytes(short))
    stray = bytearray(data)
    stray[0x28] = 1                                   # one weight set, but vertices name set 1
    with pytest.raises(A.AssetError, match="weight set past the table"):
        A.HdBin.parse(bytes(stray))
    lost = bytearray(data)
    struct.pack_into("<Q", lost, 0x48, len(data) + 64)
    with pytest.raises(A.AssetError, match="outside the file"):
        A.HdBin.parse(bytes(lost))


def test_bin_material_remap_keeps_geometry_bytes():
    model = A.HdBin.parse(make_bin())
    moved = model.with_materials([m.remapped({0: 5, 1: 7}) for m in model.materials()], texture_count=9)
    assert [m.diffuse for m in moved.materials()] == [7, 5] and moved.texture_count == 9
    assert all(moved.sections[name] == model.sections[name] for name in model.sections if name != "materials")
    assert len(moved.build()) == len(model.build())
    with pytest.raises(A.AssetError, match="no remap"):
        model.materials()[0].remapped({0: 1})


def test_bin_position_edit_keeps_everything_else():
    model = A.HdBin.parse(make_bin())
    moved = model.with_positions(model.positions() * 0.1)
    assert np.allclose(moved.positions(), model.positions() * 0.1)
    assert moved.build()[:A.BIN_HEAD] == model.build()[:A.BIN_HEAD]
    assert all(moved.sections[n] == model.sections[n] for n in model.sections if n != "positions")
    with pytest.raises(A.AssetError):
        model.with_positions(np.zeros((3, 3)))


def test_bin_new_geometry_rewrites_counts_offsets_and_keeps_the_skeleton():
    template = A.HdBin.parse(make_bin())
    faces = [np.array([[0, 1, 2], [2, 1, 3]]), np.array([[4, 5, 6]])]
    order, runs = A.soup(faces)
    source = np.arange(7 * 3, dtype=np.float32).reshape(7, 3)
    sets, index, step = A.weight_table([[(0, 1.0)], [(1, 0.5), (2, 0.5)], [(1, 0.5), (2, 0.5)], [(2, 1.0)],
                                        [(0, 0.2), (1, 0.8)], [(0, 1.0)], [(0, 1.0)]])
    assert step == 1 and len(sets) == 4 and sets[1] == ((1, 50), (2, 50))
    mats = [material(runs[0], diffuse=1), material(runs[1], diffuse=0)]
    built = template.with_geometry(positions=source[order], normals=np.tile([0.0, 2.0, 0.0], (9, 1)),
                                   uvs=np.zeros((9, 2)), weight_sets=sets, weight_index=index[order],
                                   materials=mats, texture_count=2)
    data = built.build()
    again = A.HdBin.parse(data)
    assert again.build() == data and len(data) % 32 == 0
    assert (again.vertex_count, again.weight_count, again.material_count, again.bone_count) == (9, 4, 2, 3)
    assert struct.unpack_from("<H", data, 0x42)[0] == 4 and struct.unpack_from("<H", data, 0x5A)[0] == 9
    assert all(struct.unpack_from("<I", data, at)[0] == struct.unpack_from("<Q", data, A.BIN_POINTERS[n][0])[0] - 0x38
               for n, at in A.BIN_LEGACY.items())
    assert np.array_equal(again.positions(), source[order]) and again.weights() == sets
    assert np.allclose(again.normals(), np.tile([0.0, A.NORMAL_SCALE, 0.0], (9, 1)), rtol=1e-6)
    assert [t.tolist() for t in A.triangles(again.materials())] == [[[0, 1, 2], [3, 4, 5]], [[6, 7, 8]]]
    for kept in ("bones", "bonepair", "adjacent"):
        assert again.sections[kept] == template.sections[kept]
    assert data[0x38:0x3C] == make_bin()[0x38:0x3C] and data[0x0C] == 0x50      # header constants untouched


def test_bin_new_geometry_refuses_what_the_format_cannot_hold():
    template = A.HdBin.parse(make_bin())
    args = dict(positions=np.zeros((3, 3)), normals=np.tile([0, 0, 1.0], (3, 1)), uvs=np.zeros((3, 2)),
                weight_sets=[((0, 100),)], weight_index=[0, 0, 0], materials=[material([(A.PRIM_LIST, 3)])])
    template.with_geometry(**args)
    for change, message in (({"weight_sets": [((0, 160),)]}, "100%"), ({"weight_sets": [((0, 25),) * 4]}, "100%"),
                            ({"weight_index": [0, 0, 1]}, "weight sets"), ({"normals": np.zeros((3, 3))}, "normal"),
                            ({"materials": [material([(A.PRIM_LIST, 6)])]}, "consume the vertex array")):
        with pytest.raises(A.AssetError, match=message):
            template.with_geometry(**(args | change))
    with pytest.raises(A.AssetError, match="morph"):
        A.HdBin.parse(make_bin(morph=True)).with_geometry(**args)


def test_weight_table_coarsens_until_one_byte_can_count_the_sets():
    rng = np.random.default_rng(7)
    influences = [[(0, w), (1, 1 - w)] for w in rng.uniform(0.01, 0.99, 600)]
    sets, index, step = A.weight_table(influences, limit=20)
    assert len(sets) <= 20 and step > 1 and len(index) == 600
    assert all(sum(w for _b, w in s) == 100 and all(w % step == 0 for _b, w in s) for s in sets)
    four = A.weight_table([[(0, 0.4), (1, 0.3), (2, 0.2), (3, 0.1)]])[0][0]
    assert [b for b, _w in four] == [0, 1, 2] and sum(w for _b, w in four) == 100     # the weakest of four is dropped
    with pytest.raises(A.AssetError):
        A.weight_table([[(0, 0.0)]])


# ------------------------------------------------------------------------------------------------- TPL and packs

def test_tpl_roundtrip_loose_and_in_a_slot():
    table = make_tpl()
    loose = table.build()
    assert len(loose) == 16 + 64 * 3 and A.Tpl.parse(loose).build() == loose
    slot = table.slot()
    parsed = A.Tpl.parse(slot)
    assert len(slot) % 32 == 0 and parsed.build() == slot and parsed.tail == bytes(len(slot) - len(loose))
    image = parsed.images[2]
    assert (image.width, image.height, image.format, image.index, image.archive()) == (256, 128, 0x0E, 2, "01000008.pack.fen")
    assert struct.unpack_from("<HH", loose, 16 + 48)[0] == 32            # height is stored before width
    parsed.images.append(A.TplImage(8, 8, 0x0E, 0x01000006, 30))
    assert A.Tpl.parse(parsed.slot()).images[3].archive() == "01000006.pack.fen"


def test_tpl_refuses_gamecube_and_names_the_palette_variant():
    with pytest.raises(A.AssetError, match="0x0020AF30"):
        A.Tpl.parse(struct.pack(">I", 0x0020AF30) + bytes(60))
    paletted = bytearray(make_tpl(1).build())
    struct.pack_into("<Q", paletted, 24, 0x20)
    assert A.tpl_has_palette(bytes(paletted)) and not A.tpl_has_palette(make_tpl(1).build())
    with pytest.raises(A.AssetError, match="palette"):
        A.Tpl.parse(bytes(paletted))


def make_pack(pack_id=0x01000008, sizes=((16, 8), (8, 8))):
    pack = A.ImagePack(pack_id, [])
    for width, height in sizes:
        pack.append(A.encode_dds(gradient(width, height)))
    return pack


def test_image_pack_roundtrip_and_append():
    pack = make_pack()
    data = pack.build()
    again = A.ImagePack.parse(data)
    assert again.build() == data and again.pack_id == 0x01000008
    assert [(t["width"], t["height"], t["fourcc"]) for t in again.textures()] == [(16, 8, "DXT5"), (8, 8, "DXT5")]
    body = again.body()
    assert [struct.unpack_from("<Q", body, 8 + 8 * i)[0] % 128 for i in range(2)] == [112, 112]   # DDS on a 128 boundary
    assert again.append(A.encode_dds(gradient(4, 4), mipmaps=False)) == 2
    grown = A.ImagePack.parse(again.build())
    assert [e[:2] for e in grown.entries[:2]] == [e[:2] for e in pack.entries] and grown.textures()[2]["mipmaps"] == 1
    assert [struct.unpack_from("<Q", grown.body(), 8 + 8 * i)[0] % 128 for i in range(3)] == [112] * 3
    many = make_pack(sizes=((4, 4),) * 14)                                      # the table outgrows its first 128 bytes
    assert struct.unpack_from("<Q", many.body(), 8)[0] == 240 and A.ImagePack.parse(many.build()).build() == many.build()


def test_image_pack_refuses_a_lying_size_and_a_foreign_entry():
    data = make_pack().build()
    with pytest.raises(A.AssetError, match="declares a size"):
        A.ImagePack.parse(struct.pack("<I", 7) + data[4:])
    with pytest.raises(A.AssetError, match="zlib"):
        A.ImagePack.parse(data[:4] + b"not zlib at all")
    body = bytearray(zlib.decompress(data[4:]))
    first = struct.unpack_from("<Q", body, 8)[0]
    struct.pack_into("<I", body, first + 8, 0x02000000)                         # wrapper names another pack
    with pytest.raises(A.AssetError, match="wrapper"):
        A.ImagePack.parse_body(bytes(body))


def test_encode_dds_is_a_dds_other_tools_decode():
    from PIL import Image

    image = gradient(64, 32)
    image[:, :32, 3] = 64                                                       # a translucent half
    dds = A.encode_dds(image)
    info = A.dds_info(dds)
    assert (info["width"], info["height"], info["fourcc"], info["mipmaps"]) == (64, 32, "DXT5", 7)
    assert len(dds) == 128 + 16 * sum(max(1, (64 >> m) + 3 >> 2) * max(1, (32 >> m) + 3 >> 2) for m in range(7))
    decoded = np.asarray(Image.open(io.BytesIO(dds)).convert("RGBA"), np.int32)
    assert decoded.shape == (32, 64, 4)
    assert np.abs(decoded[:, :, :3] - image[:, :, :3]).mean() < 6 and np.abs(decoded[:, :, 3] - image[:, :, 3]).max() <= 1
    flat = np.zeros((8, 8, 4), np.uint8)
    flat[:] = (10, 200, 30, 255)
    solid = np.asarray(Image.open(io.BytesIO(A.encode_dds(flat, mipmaps=False))).convert("RGBA"), np.int32)
    assert np.abs(solid - flat).max() <= 8
    with pytest.raises(A.AssetError):
        A.encode_dds(np.zeros((5, 8, 4), np.uint8))


# ------------------------------------------------------------------------------------------------------- reports

def test_slot_summary_and_roundtrip_report():
    other = struct.pack("<8I", 11, 48, 55, 102, 155, 269, 372, 477)             # a "BIN" slot that is not a model
    dat = make_dat([("BIN", make_bin()), ("TPL", make_tpl().slot()), ("", b""), ("BIN", other)])
    data = make_udas(dat)
    report = A.roundtrip("pl99.udas", data)
    assert report["identical"] and (report["bin"], report["tpl"], report["other_bin"]) == (1, 1, 1)
    with pytest.raises(A.AssetError):
        A.slot_summary(data)                                                    # a summary does not guess either
    rows = A.slot_summary(make_udas(make_dat([("BIN", make_bin()), ("TPL", make_tpl().slot()), ("", b"")])))
    assert rows[0] | {"bytes": 0} == {"slot": 0, "ext": "BIN", "bytes": 0, "vertices": 14, "bones": 3, "weight_sets": 2,
                                      "materials": 2, "textures": 2, "triangles": 6, "version": "0x20030818",
                                      "morph": False}
    assert rows[1]["images"][1] == {"width": 128, "height": 64, "format": 3, "archive": "01000008.pack.fen", "index": 1}
    assert rows[2] == {"slot": 2, "ext": "", "bytes": 0}
    assert A.roundtrip("x.pack.fen", make_pack().build())["identical"]
    assert A.roundtrip("x.bin", make_bin())["identical"] and A.roundtrip("x.tpl", make_tpl().build())["identical"]
    with pytest.raises(A.AssetError, match="no reader"):
        A.roundtrip("x.fcv", b"")
