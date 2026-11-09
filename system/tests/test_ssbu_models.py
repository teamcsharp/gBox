"""Tests for :mod:`gbox.ssbu_models`: synthetic SSBH/NUTEXB fixtures plus the operator's real data.arc.

The synthetic fixtures exercise the container layout (relative pointers, arrays, vertex attributes,
index buffers), the bone hierarchy and the BC1/BC3/BC4/BC5/BC7 decoders without needing the game. The
real-data tests are skipped when ``.tmp/ssbu_romfs/data.arc`` is absent.
"""
from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from gbox import ssbu_models as S
from gbox.ssbu_arc import DataArc

REPO = Path(__file__).resolve().parents[2]
ARC = REPO / ".tmp" / "ssbu_romfs" / "data.arc"
HAS_BC7 = importlib.util.find_spec("texture2ddecoder") is not None
needs_arc = pytest.mark.skipif(not ARC.is_file(), reason="the operator's data.arc is not present")


# ---------------------------------------------------------------------------------- fixture builders


def ssbh(magic: bytes, minor: int, payload: bytes) -> bytes:
    """The 0x18-byte SSBH wrapper around a format payload (``HBSS | 64 | 0 | tag | major | minor``)."""
    return (b"HBSS" + struct.pack("<Q", 64) + struct.pack("<I", 0) + magic
            + struct.pack("<HH", 1, minor) + payload)


class Blob:
    """A byte buffer with SSBH relative-pointer helpers."""

    def __init__(self, size: int = 0x800):
        self.data = bytearray(size)

    def u16(self, offset: int, value: int) -> None:
        struct.pack_into("<H", self.data, offset, value)

    def i16(self, offset: int, value: int) -> None:
        struct.pack_into("<h", self.data, offset, value)

    def u32(self, offset: int, value: int) -> None:
        struct.pack_into("<I", self.data, offset, value)

    def u64(self, offset: int, value: int) -> None:
        struct.pack_into("<Q", self.data, offset, value)

    def f32(self, offset: int, value: float) -> None:
        struct.pack_into("<f", self.data, offset, value)

    def rel(self, offset: int, target: int | None) -> None:
        self.u64(offset, 0 if target is None else target - offset)

    def array(self, offset: int, target: int | None, count: int) -> None:
        self.rel(offset, target)
        self.u64(offset + 8, count)

    def string(self, offset: int, text: str, target: int) -> None:
        raw = text.encode()
        self.data[target:target + len(raw) + 1] = raw + b"\0"
        self.rel(offset, target)


def half(value: float) -> int:
    return struct.unpack("<H", struct.pack("<e", value))[0]


def build_mesh() -> bytes:
    """A MESH 1.10 with one triangle: position/float3, normal/half4, tangent/half4, uv/half2, u16 indices."""
    b = Blob(0x800)
    b.array(0x70, 0xC8, 1)                      # objects
    b.array(0x80, 0x290, 4)                     # buffer_sizes (bytes)
    b.u64(0x90, 6)                              # polygon_index_size: 6 bytes = 3 u16 indices
    b.array(0x98, 0x260, 2)                     # vertex_buffers
    b.array(0xA8, 0x300, 6)                     # index_buffer
    b.array(0xB8, None, 0)                      # rigging (empty)
    for k, size in enumerate((3 * 28, 3 * 4, 0, 0)):
        b.u32(0x290 + 4 * k, size)
    # mesh object
    o = 0xC8
    b.string(o, "tri", 0x310)
    b.u64(o + 8, 0)
    b.u32(o + 0x18, 3)                          # vertex_count
    b.u32(o + 0x1C, 3)                          # index_count
    b.u32(o + 0x20, 3)                          # indices per face
    b.u32(o + 0x34, 28)                         # stride0
    b.u32(o + 0x38, 4)                          # stride1
    b.u32(o + 0x48, 4)                          # unk8
    b.u32(o + 0x4C, 0)                          # DrawElementType: u16
    b.array(o + 0xC0, 0x198, 4)                 # attributes
    for k, (usage, dtype, buffer_index, buffer_offset) in enumerate(
            ((0, 0, 0, 0), (1, 5, 0, 12), (3, 5, 0, 20), (4, 8, 1, 0))):
        a = 0x198 + 48 * k
        b.u32(a, usage)
        b.u32(a + 4, dtype)
        b.u32(a + 8, buffer_index)
        b.u32(a + 12, buffer_offset)
        b.u64(a + 16, 0)                        # subindex
        b.array(a + 32, None, 0)                # attribute_names
    b.array(0x260, 0x2A0, 3 * 28)               # vertex buffer 0
    b.array(0x270, 0x2F4, 3 * 4)                # vertex buffer 1
    positions = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0))
    uvs = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))
    for i, (position, uv) in enumerate(zip(positions, uvs)):
        at = 0x2A0 + 28 * i
        for k, value in enumerate(position):
            b.f32(at + 4 * k, value)
        for k, value in enumerate((0.0, 0.0, 1.0, 0.0)):       # normal +Z, half floats
            b.u16(at + 12 + 2 * k, half(value))
        for k, value in enumerate((1.0, 0.0, 0.0, 1.0)):       # tangent
            b.u16(at + 20 + 2 * k, half(value))
        for k, value in enumerate(uv):
            b.u16(0x2F4 + 4 * i + 2 * k, half(value))
    for k, index in enumerate((0, 1, 2)):
        b.u16(0x300 + 2 * k, index)
    return ssbh(b"HSEM", 10, bytes(b.data))


def build_skel() -> bytes:
    """A SKEL 1.0 with three bones (Hip -> Head -> HandL) and identity-with-translation matrices."""
    b = Blob(0x700)
    bones = (("Hip", -1), ("Head", 0), ("HandL", 1))
    b.array(0x00, 0x50, 3)
    b.array(0x10, 0x80, 3)                      # world
    b.array(0x20, 0x140, 3)                     # inverse world
    b.array(0x30, 0x200, 3)                     # local
    b.array(0x40, 0x2C0, 3)                     # inverse local
    for i, (name, parent) in enumerate(bones):
        at = 0x50 + 16 * i
        b.string(at, name, 0x500 + 32 * i)
        b.u16(at + 8, i)
        b.i16(at + 10, parent)
    for array_at, sign in ((0x80, 1), (0x140, -1), (0x200, 1), (0x2C0, -1)):
        for i in range(3):
            at = array_at + 64 * i
            for k in range(4):
                b.f32(at + 4 * (4 * k + k), 1.0)                 # diagonal
            b.f32(at + 48, 0.0)
            b.f32(at + 52, sign * i)
            b.f32(at + 56, 0.0)
    return ssbh(b"LEKS", 0, bytes(b.data))


def build_matl() -> bytes:
    """A MATL 1.6 with two materials: one textured (Texture0/4) and one with only CustomVector11."""
    b = Blob(0x500)
    b.array(0x00, 0x10, 2)
    for i, (label, attrs, count) in enumerate((("mat", 0x50, 3), ("plain", 0x98, 1))):
        entry = 0x10 + 32 * i
        b.string(entry, label, 0x100 + 16 * i)
        b.array(entry + 8, attrs, count)
        b.string(entry + 24, "SFX_PBS_" + label, 0x120 if i == 0 else 0x140)
    # mat: Texture0 = tex_col, Texture4 = tex_nor, CustomVector11 = [0.2, 0.4, 0.6, 1]
    for k, (param_id, dtype, value_at) in enumerate(((92, 11, 0xC0), (96, 11, 0xC8), (163, 5, 0xD0))):
        a = 0x50 + 24 * k
        b.u64(a, param_id)
        b.rel(a + 8, value_at)
        b.u64(a + 16, dtype)
    # plain: CustomVector11 = [0.1, 0.2, 0.3, 1]
    b.u64(0x98, 163)
    b.rel(0xA0, 0xB0)
    b.u64(0xA8, 5)
    for k, value in enumerate((0.1, 0.2, 0.3, 1.0)):
        b.f32(0xB0 + 4 * k, value)
    b.rel(0xC0, 0x160)                          # SsbhString -> "tex_col"
    b.rel(0xC8, 0x170)                          # SsbhString -> "tex_nor"
    for k, value in enumerate((0.2, 0.4, 0.6, 1.0)):
        b.f32(0xD0 + 4 * k, value)
    b.data[0x100:0x104] = b"mat\0"
    b.data[0x110:0x116] = b"plain\0"
    b.data[0x120:0x12D] = b"SFX_PBS_test\0"
    b.data[0x140:0x14E] = b"SFX_PBS_plain\0"
    b.data[0x160:0x168] = b"tex_col\0"
    b.data[0x170:0x178] = b"tex_nor\0"
    return ssbh(b"LTAM", 6, bytes(b.data))


def build_nutexb(width: int, height: int, fmt: int, payload: bytes, *, swizzled: bool = False,
                 name: str = "tex") -> bytes:
    """A data-first NUTEXB: surface, one 0x40-byte mip table, 112-byte footer."""
    table = struct.pack("<I", len(payload)) + b"\0" * (0x40 - 4)
    footer = bytearray(112)
    footer[0:4] = b" XNT"
    footer[4:4 + len(name)] = name.encode()
    struct.pack_into("<9I", footer, 0x44, width, height, 1, fmt, 4, 1, 0x1000 if swizzled else 0, 1,
                     len(payload))
    footer[0x68:0x6C] = b" XET"
    struct.pack_into("<HH", footer, 0x6C, 1, 2)
    return payload + table + bytes(footer)


def bc1_solid(rgb565: int) -> bytes:
    return struct.pack("<HHI", rgb565, rgb565, 0)          # 4x4 block, all indices 0


def bc4_solid(value: int) -> bytes:
    return bytes([value, value, 0, 0, 0, 0, 0, 0])         # r0 == r1, all indices 0


# ------------------------------------------------------------------------------------ synthetic tests


def test_mesh_parses_header_attributes_and_indices():
    mesh = S.Numshb(build_mesh())
    assert (mesh.major, mesh.minor) == (1, 10)
    assert mesh._object_count == 1
    assert mesh.polygon_index_size == 6
    assert mesh.buffer_sizes == [84, 12, 0, 0]
    obj = mesh.objects[0]
    assert (obj["name"], obj["subindex"], obj["vertex_count"], obj["index_count"]) == ("tri", 0, 3, 3)
    assert [a["kind"] for a in obj["attributes"]] == ["f3", "h4", "h4", "h2"]
    verts = mesh.vertices(0)
    np.testing.assert_allclose(verts["pos"], [[0, 0, 0], [1, 0, 0], [0, 2, 0]])
    np.testing.assert_allclose(verts["uv"], [[0, 0], [1, 0], [0, 1]])
    np.testing.assert_allclose(verts["nrm"], [[0, 0, 1], [0, 0, 1], [0, 0, 1]])
    np.testing.assert_allclose(verts["tan"], [[1, 0, 0], [1, 0, 0], [1, 0, 0]])
    tris = mesh.triangles(0)
    np.testing.assert_array_equal(tris, [[0, 1, 2]])
    assert tris.max() < obj["vertex_count"]
    assert np.isfinite(verts["uv"]).all()


def test_mesh_rejects_wrong_container():
    with pytest.raises(S.SsbhError, match="MODL"):
        S.Numdlb(build_mesh())
    with pytest.raises(S.SsbhError, match="bad SSBH magic"):
        S.Numshb(b"nope" + bytes(32))
    with pytest.raises(S.SsbhError, match="version"):
        S.Numshb(ssbh(b"HSEM", 7, bytes(0x100)))


def test_skeleton_parents_and_matrices():
    skel = S.Nusktb(build_skel())
    assert skel.names == ["Hip", "Head", "HandL"]
    assert skel.parents == [-1, 0, 1]
    assert skel.world.shape == (3, 4, 4)
    np.testing.assert_allclose(skel.world[:, 3, :3], [[0, 0, 0], [0, 1, 0], [0, 2, 0]], atol=1e-6)
    np.testing.assert_allclose(skel.inverse_bind_matrices()[:, :3, 3], [[0, 0, 0], [0, -1, 0], [0, -2, 0]],
                               atol=1e-6)
    for i, parent in enumerate(skel.parents):
        assert -1 <= parent < len(skel.names)
        assert parent != i


def test_material_slots_and_fallbacks():
    matl = S.Numatb(build_matl())
    assert matl.labels() == ["mat", "plain"]
    assert matl.texture_slots("mat") == {0: "tex_col", 4: "tex_nor"}
    assert matl.sampler_slots("mat") == {"Sampler0": "tex_col", "Sampler4": "tex_nor"}
    assert matl.albedo_candidates("mat") == ["tex_col"]
    assert matl.normal_name("mat") == "tex_nor"
    assert matl.texture_slots("plain") == {}
    assert matl.fallback_colour("plain") == pytest.approx((0.1, 0.2, 0.3, 1.0))
    # A composited iris overlay: base + alpha overlay of the same size become one image.
    base = np.full((4, 4, 4), 200, np.uint8)
    iris = np.zeros((4, 4, 4), np.uint8)
    iris[..., :3] = (0, 0, 255)
    iris[1:3, 1:3, 3] = 255                                # a small opaque iris on a transparent map
    matl.entries[0]["params"][93] = "iris"
    out = matl.composite_albedo("mat", {"tex_col": base, "iris": iris})
    assert out is not None and out.shape == (4, 4, 4)
    assert out[1, 1, 2] > out[1, 1, 0]                     # blue iris wins where alpha is 255
    assert out[0, 0, 0] == 200                             # base shows through alpha 0


def test_nutexb_bc1_bc3_bc4_bc5():
    # BC1: 8x8 pixels = 4 solid blocks, 16-bit 565 red.
    rgba, info = S.nutexb_image(build_nutexb(8, 8, 0x0480, bc1_solid(0xF800) * 4))
    assert info["format_name"] == "BC1_UNORM" and info["swizzled"] is False
    assert rgba.shape == (8, 8, 4)
    np.testing.assert_array_equal(rgba[..., :3].reshape(-1, 3)[0], [255, 0, 0])
    # BC3: alpha block 255 + green colour block.
    bc3 = bc4_solid(255) + bc1_solid(0x07E0)
    rgba, _ = S.nutexb_image(build_nutexb(4, 4, 0x04A0, bc3 * 1))
    np.testing.assert_array_equal(rgba[0, 0], [0, 255, 0, 255])
    # BC4: a single channel, r0 == r1 == 128.
    rgba, info = S.nutexb_image(build_nutexb(4, 4, 0x0180, bc4_solid(128)))
    assert info["format_name"] == "BC4_UNORM"
    np.testing.assert_array_equal(rgba[0, 0], [128, 0, 0, 255])
    # BC5: red = 64, green = 192.
    rgba, _ = S.nutexb_image(build_nutexb(4, 4, 0x0280, bc4_solid(64) + bc4_solid(192)))
    np.testing.assert_array_equal(rgba[0, 0], [64, 192, 0, 255])


def test_nutexb_bc7_or_graceful_fallback():
    # One "block" is not a valid BC7 block; either the decoder rejects it (fallback) or it is all zeros.
    payload = bytes(16)
    rgba, info = S.nutexb_image(build_nutexb(4, 4, 0x04E5, payload))
    assert rgba.shape == (4, 4, 4)
    if not HAS_BC7:
        assert info["fallback"] is True and "texture2ddecoder" in info["warning"]


def test_nutexb_unswizzles_a_single_gob():
    # 16x16 BC1 is a 4x4 block surface: exactly one GOB (64x8 bytes) with a partial height.
    linear = np.arange(4 * 32, dtype=np.uint8)
    swizzled = np.zeros(512, dtype=np.uint8)
    for y in range(4):
        for x in range(32):
            offset = (((x % 64) // 32) * 256 + ((y % 8) // 2) * 64 + ((x % 32) // 16) * 32
                      + (y % 2) * 16 + (x % 16))
            swizzled[offset] = linear[y * 32 + x]
    out = S.deswizzle_mip0(swizzled.tobytes(), 16, 16, 4, 4, 8)
    assert out.shape == (4, 32)
    np.testing.assert_array_equal(out.reshape(-1), linear)


def test_nutexb_rejects_short_and_bad_files():
    with pytest.raises(S.TextureError, match="too short"):
        S.nutexb_image(b"x" * 20)
    with pytest.raises(S.TextureError, match="footer"):
        S.nutexb_image(bytes(200))


def test_roles_from_bones_never_invents():
    names = ["Trans", "Hip", "Bust", "Neck", "Head", "ClavicleL", "ShoulderL", "ArmL", "HandL",
             "ClavicleR", "ShoulderR", "ArmR", "HandR", "LegL", "KneeL", "FootL", "LegR", "KneeR", "FootR"]
    roles = S.roles_from_bones(names)
    assert roles["hip"] == "Hip" and roles["chest"] == "Bust" and roles["head"] == "Head"
    assert roles["l_upper"] == "ShoulderL" and roles["l_fore"] == "ArmL" and roles["l_hand"] == "HandL"
    assert roles["r_thigh"] == "LegR" and roles["r_shin"] == "KneeR" and roles["r_foot"] == "FootR"
    assert len(roles) == 18
    assert S.roles_from_bones(["Hip", "Head", "Spine", "tail"]) == {"hip": "Hip", "head": "Head"}
    assert S.roles_from_bones([]) == {}


# --------------------------------------------------------------------------------------- real data


@pytest.fixture(scope="module")
def arc():
    if not ARC.is_file():
        pytest.skip("the operator's data.arc is not present")
    with DataArc(ARC) as opened:
        yield opened


def load_model(arc: DataArc, fighter: str) -> S.Numdlb:
    base = f"fighter/{fighter}/model/body/c00/"
    return S.Numdlb(arc.read(base + "model.numdlb"),
                    mesh=S.Numshb(arc.read(base + "model.numshb")),
                    skel=S.Nusktb(arc.read(base + "model.nusktb")),
                    matl=S.Numatb(arc.read(base + "model.numatb")))


@needs_arc
def test_real_sonic_mesh_geometry(arc):
    model = load_model(arc, "sonic")
    mesh = model.mesh
    assert model.model_name == "model"
    assert model.mesh_file_name == "model.numshb"
    assert model.skeleton_file_name == "model.nusktb"
    assert model.material_file_names == ["model.numatb"]
    assert mesh is not None and len(mesh.objects) == 77
    assert len(mesh.vertex_buffers) == 4 and mesh.buffer_sizes[:2] == [568988, 82324]
    triangles = 0
    for i, obj in enumerate(mesh.objects):
        verts = mesh.vertices(i)
        tris = mesh.triangles(i)
        assert verts["pos"].shape == (obj["vertex_count"], 3)
        assert np.isfinite(verts["pos"]).all() and np.isfinite(verts["uv"]).all()
        assert tris.shape[1] == 3
        assert int(tris.max()) < obj["vertex_count"]
        triangles += len(tris)
    assert triangles == mesh.polygon_index_size // 2 // 3 == 34348


@needs_arc
def test_real_sonic_skeleton_and_roles(arc):
    model = load_model(arc, "sonic")
    skel = model.skel
    assert skel is not None and len(skel.names) == 115
    assert skel.names[skel.names.index("Hip")] == "Hip"
    assert all(-1 <= parent < len(skel.names) for parent in skel.parents)
    assert skel.parents[skel.names.index("Trans")] == -1
    assert skel.world.shape == (115, 4, 4)
    np.testing.assert_allclose(skel.world[skel.names.index("Hip"), 3, :3], [0, 8.04976, 0], atol=1e-3)
    roles = S.roles_from_bones(skel.names)
    from gbox.retarget_profile import ROLES
    assert set(roles) == set(ROLES)
    assert roles["chest"] == "Bust" and roles["l_clav"] == "ClavicleL"
    assert len([role for role in roles if role not in ("head", "neck")]) >= 10


@needs_arc
def test_real_sonic_materials_and_textures(arc):
    model = load_model(arc, "sonic")
    matl = model.matl
    assert matl is not None
    assert matl.texture_slots("def_sonic_001") == {
        0: "def_sonic_001_col", 4: "def_sonic_001_nor", 6: "def_sonic_001_prm", 7: "#replace_cubemap"}
    assert matl.albedo_candidates("def_sonic_001")[0] == "def_sonic_001_col"
    assert matl.normal_name("def_sonic_001") == "def_sonic_001_nor"
    payload = arc.read("fighter/sonic/model/body/c00/def_sonic_001_col.nutexb")
    rgba, info = S.nutexb_image(payload)
    assert (info["width"], info["height"], info["format_name"], info["swizzled"]) == (1024, 1024, "BC7_SRGB", True)
    assert rgba.shape == (1024, 1024, 4)
    red, green, blue = rgba[..., 0].mean(), rgba[..., 1].mean(), rgba[..., 2].mean()
    assert blue > red and blue > green                      # Sonic's body texture is blue


@needs_arc
def test_real_sonic_decode_prims(arc):
    model = load_model(arc, "sonic")
    chosen = S.default_object_indices(model)
    assert 0 in chosen and 1 in chosen                      # body + shoes/gloves
    names = [model.mesh.objects[i]["name"].lower() for i in chosen]
    assert not any("sphere" in name or "blink" in name or "brow" in name for name in names)
    decoded = model.decode(textures={}, objects=chosen)
    assert [prim["name"] for prim in decoded["prims"]] == [model.mesh.objects[i]["name"] for i in chosen]
    for prim in decoded["prims"]:
        assert np.isfinite(prim["pos"]).all() and np.isfinite(prim["uv"]).all()
        assert int(prim["tris"].max()) < len(prim["pos"])
        assert prim["owner"].min() >= 0 and prim["owner"].max() < len(decoded["names"])
        assert prim["tex"] is None
    assert len(decoded["joints"]) == 115
    assert decoded["joints"][2]["parent"] == 1


@needs_arc
def test_extract_sonic_round_trips_through_rig_from_gltf(arc, tmp_path):
    from gbox.characters import rig_from_gltf

    result = S.extract_fighter("sonic", arc, tmp_path, name="sonic")
    assert result["fighter"] == "sonic"
    assert result["triangles"] >= 1000
    assert result["joints"] == 115
    assert len(result["roles"]) >= 10
    assert result["textures"] >= (7 if HAS_BC7 else 0)
    assert result["materials"] >= 6
    glb, preview = Path(result["glb"]), Path(result["preview"])
    assert glb.is_file() and preview.is_file()
    assert glb.read_bytes()[:4] == b"glTF"
    assert any("eyeW_sonic_001_col" in note and "fallback" in note for note in result["notes"])

    rig = rig_from_gltf(glb, result["roles"])
    assert rig["joints"].shape == (115, 3)
    assert len(rig["parent"]) == 115
    assert rig["parent"][0] == -1
    assert len(rig["prims"]) == len(S.default_object_indices(load_model(arc, "sonic")))
    assert len(rig["roles"]) >= 10
    for prim in rig["prims"]:
        assert np.isfinite(prim["pos"]).all() and np.isfinite(prim["uv"]).all()
        assert prim["tris"].max() < len(prim["pos"])
        assert prim["owner"].max() < 115
    assert any(prim["tex"] is not None for prim in rig["prims"])


@needs_arc
def test_extract_mario_is_general(arc, tmp_path):
    result = S.extract_fighter("mario", arc, tmp_path, name="mario")
    assert result["triangles"] >= 1000
    assert result["joints"] > 50
    assert result["materials"] >= 4
    assert Path(result["glb"]).is_file() and Path(result["preview"]).is_file()
    assert len(result["roles"]) >= 10
    summary = json.loads(json.dumps(result, default=str))   # the result must be serialisable for the summary
    assert summary["fighter"] == "mario"
