"""Super Smash Bros. Ultimate fighter models: read the game's SSBH model containers and emit skinned glTF.

The game stores a fighter's body in four files under ``fighter/<fighter>/model/body/c00/``:

* ``model.numdlb`` - SSBH ``MODL`` version 1.7: the model name and the join table (mesh-object name +
  subindex -> material label) plus the names of the three companion files.
* ``model.numshb`` - SSBH ``MESH`` version 1.10: bounding volumes, mesh objects (submeshes), their vertex
  attributes and index ranges, four shared vertex buffers, one shared index buffer and the per-object
  skinning buffers.
* ``model.nusktb`` - SSBH ``SKEL`` version 1.0: bones (name, index, parent, billboard flag) and four
  arrays of 4x4 matrices (world, inverse world, local, inverse local), stored little-endian float32.
* ``model.numatb`` - SSBH ``MATL`` version 1.6: materials with a shader label and typed parameters.

Every file starts with the 0x18-byte SSBH wrapper ``"HBSS" | u64 0x40 | u32 0 | <4-byte type tag> |
u16 major | u16 minor`` and the format payload begins at 0x18. Inside a payload all pointers are *offsets
relative to the pointer field itself*, arrays are ``u64 relative offset, u64 element count`` and strings
are ``u64 relative pointer, NUL-terminated bytes`` (``SsbhString`` 4-byte aligned, ``SsbhString8`` 8-byte
aligned). Those conventions are from the MIT-licensed `ssbh_lib` crate (ScanMountGoat / ultimate-research)
and every offset used here was re-measured on this cartridge image.

Measured on the operator's own ``data.arc`` (title 01006A800016E000, base game 1.0.0):

* Sonic's ``model.numshb`` is 978,536 decoded bytes with 77 mesh objects, 4 vertex buffers and a
  206,088-byte index buffer. ``polygon_index_size`` is a *byte* size (206,088 = 103,044 u16 indices),
  not an index count, and ``DrawElementType`` is 0 (u16) for every object of Sonic, Mario and Link.
* Sonic's object 0 uses a 28-byte vertex stride: position ``Float3`` at 0, normal ``HalfFloat4`` at
  0x0C and tangent ``HalfFloat4`` at 0x14; UVs are ``HalfFloat2`` in a second buffer with a 4-byte
  stride. Half floats decode to unit-length normals/tangents and UVs inside [0, 1].
* Skinning data on MESH 1.10 is a per-bone list of 6-byte ``(u16 vertex index, f32 weight)`` entries
  (4 influences maximum on Sonic, weights sum to 1.0). MESH 1.8/1.9 use 8-byte ``(u32, f32)`` entries.
* ``model.nusktb`` stores the world transform's translation in the *last row* (row-vector convention:
  ``world_point = local_point @ matrix``). Sonic's Hip is (0, 8.05, 0), Head (0, 10.35, 0), ToeL
  (0.66, 0.77, 2.38) - toes point +Z, so the model already faces +Z with +Y up, the orientation
  ``gbox.characters.render_preview`` expects. No axis conversion is applied anywhere in this module.
* Fighter materials are ``SFX_PBS_*``: ``Texture0`` (param id 92) is the albedo (``_col``),
  ``Texture4`` (96) the normal map (``_nor``), ``Texture6`` (98) the parameter map (``_prm``) and
  ``Texture7`` (99) a ``#replace_cubemap`` placeholder. ``SamplerN`` (108 + N) holds the sampler state
  for ``TextureN``. Verified on Sonic's ``def_sonic_001``, ``skin_sonic_001``, ``metal_sonic_001`` and
  ``EyeL``.
* Some referenced eye textures (``eyeW_sonic_001_col``/``_nor``/``_prm``, ``eyeL_sonic_001_col``,
  ``eyeR_sonic_001_col``, ``skin_sonic_mouthD/E_001_*``) have **no entry anywhere** in this archive:
  the multi-hash table contains no record whose file-name hash is that name (``def_sonic_001_col``
  has 16). The extractor therefore falls back to a material colour for them and says so in ``notes``.

``.nutexb`` textures are *footer-first*: the block-linear surface payload starts at offset 0, followed by
one 0x40-byte mip-size table per array layer and a 112-byte footer at the end of the file. The footer's
``unk3`` field is 0x1000 exactly when the payload is Tegra X1 block-linear swizzled. Fighter textures on
this image are BC7 sRGB (0x4E5) for colour and BC7 linear (0x4E0) for normal/parameter maps; other SSBU
textures use BC1/BC3/BC4/BC5/R8G8B8A8 as well. BC1/BC3/BC4/BC5 are decoded here in numpy; BC7 needs the
optional ``texture2ddecoder`` wheel (the ``textures`` extra of this project) and degrades to a flat
material colour with a warning when it is missing.

The block-linear untiling (GOB = 64x8 bytes) follows the Tegra X1 TRM algorithm as implemented by
`tegra_swizzle` (MIT): block height is inferred from the mip height with ``block_height_mip0`` and each
mip halves it while ``height <= (block_height / 2) * 8``.

One limitation of the shared archive reader is reported rather than worked around: a few table-3 index
records resolve to bytes that are not a Zstandard frame (measured on
``fighter/mario/model/body/c00/eye_mario_w_nor.nutexb``; all eight costume copies fail identically while
``eye_mario_w_col`` in the same folder reads fine). :func:`extract_fighter` catches a failed texture read,
records it in ``notes`` and uses the material colour, so one bad index entry cannot abort a model.
"""
from __future__ import annotations

import argparse
import io
import json
import struct
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import numpy as np

__all__ = [
    "SsbhError", "TextureError", "Numdlb", "Numshb", "Nusktb", "Numatb",
    "nutexb_image", "roles_from_bones", "extract_fighter", "main",
]

SSBH_WRAPPER_SIZE = 0x18
SKEL_VERSION = (1, 0)
MATL_VERSION = (1, 6)
MODL_VERSION = (1, 7)

#: SSBH ``Matl`` texture parameter ids: ``Texture0`` == 92, ``Texture15`` == 107, ``Texture16`` == 307.
TEXTURE_PARAM_IDS = {92 + n: n for n in range(16)} | {307 + n: 16 + n for n in range(4)}

#: Material parameter ids this module names (from the ``ParamId`` enum of ssbh_lib; only ids actually seen
#: in fighter materials are given a name).
PARAM_NAMES = {
    0: "Diffuse", 1: "Specular", 2: "Ambient", 4: "Transparency", 9: "Roughness",
    30: "DiffuseMap", 36: "NormalMap", 64: "DiffuseSampler", 66: "NormalSampler",
    152: "CustomVector0", 153: "CustomVector1", 160: "CustomVector8", 163: "CustomVector11",
    165: "CustomVector13", 166: "CustomVector14", 192: "CustomFloat0", 193: "CustomFloat1",
    200: "CustomFloat8", 232: "CustomBoolean0", 233: "CustomBoolean1", 235: "CustomBoolean3",
    236: "CustomBoolean4", 238: "CustomBoolean6", 243: "CustomBoolean11", 280: "BlendState0",
    291: "RasterizerState0", 315: "CustomVector20", 316: "CustomVector21", 317: "CustomVector22",
    324: "CustomVector29", 325: "CustomVector30", 326: "CustomVector31",
}

#: nutexb image formats (footer ``image_format`` u32) -> (name, block width, block height, bytes per block).
NUTEXB_FORMATS = {
    0x0100: ("R8_UNORM", 1, 1, 1),
    0x0400: ("R8G8B8A8_UNORM", 1, 1, 4),
    0x0405: ("R8G8B8A8_SRGB", 1, 1, 4),
    0x0434: ("R32G32B32A32_FLOAT", 1, 1, 16),
    0x0450: ("B8G8R8A8_UNORM", 1, 1, 4),
    0x0455: ("B8G8R8A8_SRGB", 1, 1, 4),
    0x0480: ("BC1_UNORM", 4, 4, 8),
    0x0485: ("BC1_SRGB", 4, 4, 8),
    0x0180: ("BC4_UNORM", 4, 4, 8),
    0x0185: ("BC4_SNORM", 4, 4, 8),
    0x0490: ("BC2_UNORM", 4, 4, 16),
    0x0495: ("BC2_SRGB", 4, 4, 16),
    0x04A0: ("BC3_UNORM", 4, 4, 16),
    0x04A5: ("BC3_SRGB", 4, 4, 16),
    0x0280: ("BC5_UNORM", 4, 4, 16),
    0x0285: ("BC5_SNORM", 4, 4, 16),
    0x04D7: ("BC6_UFLOAT", 4, 4, 16),
    0x04D8: ("BC6_SFLOAT", 4, 4, 16),
    0x04E0: ("BC7_UNORM", 4, 4, 16),
    0x04E5: ("BC7_SRGB", 4, 4, 16),
}

#: Extra bytes of fallback colour used when a texture cannot be decoded.
FALLBACK_RGBA = (128, 128, 128, 255)
#: Block-linear GOB geometry (Tegra X1: 64 bytes x 8 rows).
GOB_WIDTH = 64
GOB_HEIGHT = 8
GOB_SIZE = GOB_WIDTH * GOB_HEIGHT


class SsbhError(ValueError):
    """A file is not the SSBH container/layout this module measured."""


class TextureError(ValueError):
    """A NUTEXB file is malformed or uses a format this module cannot decode."""


# --------------------------------------------------------------------------------------- container


class _Ssbh:
    """Little-endian reader for one SSBH payload (the bytes after the 0x18-byte wrapper)."""

    def __init__(self, data: bytes, magic: str):
        if len(data) < SSBH_WRAPPER_SIZE:
            raise SsbhError(f"only {len(data)} bytes: shorter than the 0x18-byte SSBH wrapper")
        if data[:4] != b"HBSS":
            raise SsbhError(f"bad SSBH magic {data[:4]!r}")
        tag = data[0x10:0x14][::-1].decode("ascii", "replace")
        if tag != magic:
            raise SsbhError(f"expected a {magic} SSBH file, found {tag!r}")
        self.raw = bytes(data)
        self.magic = tag
        self.major, self.minor = struct.unpack_from("<HH", data, 0x14)
        self.data = self.raw[SSBH_WRAPPER_SIZE:]

    # -- primitives (all offsets are relative to ``self.data``) -------------------------------------

    def u8(self, offset: int) -> int:
        return self.data[offset]

    def u16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.data, offset)[0]

    def i16(self, offset: int) -> int:
        return struct.unpack_from("<h", self.data, offset)[0]

    def u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self.data, offset)[0]

    def i32(self, offset: int) -> int:
        return struct.unpack_from("<i", self.data, offset)[0]

    def u64(self, offset: int) -> int:
        return struct.unpack_from("<Q", self.data, offset)[0]

    def f32(self, offset: int) -> float:
        return struct.unpack_from("<f", self.data, offset)[0]

    def floats(self, offset: int, count: int) -> list[float]:
        return list(struct.unpack_from(f"<{count}f", self.data, offset))

    def pointer(self, offset: int) -> int | None:
        """A relative pointer: target = field position + stored offset (0 means null)."""
        relative = self.u64(offset)
        return offset + relative if relative else None

    def string(self, offset: int) -> str:
        target = self.pointer(offset)
        if target is None:
            return ""
        end = self.data.find(b"\0", target)
        if end < 0:
            raise SsbhError(f"unterminated string at 0x{target:x}")
        return self.data[target:end].decode("utf-8", "replace")

    def array(self, offset: int) -> tuple[int | None, int]:
        return self.pointer(offset), self.u64(offset + 8)

    def enum64(self, offset: int) -> tuple[int | None, int]:
        """SSBH enum: relative offset followed by a u64 data type."""
        return self.pointer(offset), self.u64(offset + 8)

    def check(self, offset: int, size: int) -> None:
        if offset < 0 or offset + size > len(self.data):
            raise SsbhError(f"read of {size} bytes at 0x{offset:x} is outside the {len(self.data)}-byte payload")


def _matrix_rows(reader: _Ssbh, offset: int) -> np.ndarray:
    """16 little-endian float32 -> a (4, 4) array in the file's row-vector convention."""
    return np.asarray(reader.floats(offset, 16), dtype=np.float32).reshape(4, 4)


# ------------------------------------------------------------------------------------------- MODL


class Numdlb(_Ssbh):
    """SSBH ``MODL`` (``.numdlb``): what files make up a model and which material each mesh object uses.

    The file has no geometry or skeleton data of its own; pass the companion payloads (or parsed objects)
    as ``mesh=``/``skel=``/``matl=`` so :meth:`vertices`, :meth:`indices`, :meth:`skeleton` and
    :meth:`decode` can reach them.
    """

    def __init__(self, data: bytes, *, mesh: "Numshb | bytes | None" = None,
                 skel: "Nusktb | bytes | None" = None, matl: "Numatb | bytes | None" = None):
        super().__init__(data, "MODL")
        if (self.major, self.minor) != MODL_VERSION:
            raise SsbhError(f"MODL version {self.major}.{self.minor}, expected {MODL_VERSION[0]}.{MODL_VERSION[1]}")
        self.model_name = self.string(0x00)
        self.skeleton_file_name = self.string(0x08)
        ptr, count = self.array(0x10)
        self.material_file_names = [self.string(ptr + 8 * i) for i in range(count)] if ptr else []
        animation = self.pointer(0x20)
        self.animation_file_name = self.string(animation) if animation is not None else ""
        self.mesh_file_name = self.string(0x28)
        self._entries_ptr, self._entry_count = self.array(0x30)
        self.mesh = Numshb(mesh) if isinstance(mesh, (bytes, bytearray)) else mesh
        self.skel = Nusktb(skel) if isinstance(skel, (bytes, bytearray)) else skel
        self.matl = Numatb(matl) if isinstance(matl, (bytes, bytearray)) else matl

    # -- join table -------------------------------------------------------------------------------

    @property
    def entry_count(self) -> int:
        """Number of (mesh object, material) assignments (77 for Sonic)."""
        return self._entry_count

    def materials(self) -> list[dict]:
        """The MODL entry table: ``[{"object", "subindex", "material"}]``.

        The join with a ``Numatb`` is by the exact material label string (the format stores no hash for
        it); the same (object, subindex) pair identifies the mesh object in the ``.numshb``.
        """
        out = []
        for i in range(self._entry_count):
            if self._entries_ptr is None:
                break
            at = self._entries_ptr + 24 * i
            out.append({"object": self.string(at), "subindex": self.u64(at + 8),
                        "material": self.string(at + 16)})
        return out

    def material_label(self, object_name: str, subindex: int) -> str:
        """The material label the MODL assigns to one mesh object ('' when it has no entry)."""
        for entry in self.materials():
            if entry["object"] == object_name and entry["subindex"] == subindex:
                return entry["material"]
        return ""

    # -- geometry / skeleton accessors -------------------------------------------------------------

    def vertices(self, objects: Iterable[int] | None = None) -> list[dict]:
        """Per-mesh-object vertex arrays (see :meth:`Numshb.vertices`); needs ``mesh=``."""
        if self.mesh is None:
            raise SsbhError("this Numdlb has no MESH payload (pass mesh=...)")
        return [self.mesh.vertices(i) for i in self.mesh.select(objects)]

    def indices(self, objects: Iterable[int] | None = None) -> list[np.ndarray]:
        """Per-mesh-object triangles ``(m, 3)``; needs ``mesh=``."""
        if self.mesh is None:
            raise SsbhError("this Numdlb has no MESH payload (pass mesh=...)")
        return [self.mesh.triangles(i) for i in self.mesh.select(objects)]

    def skeleton(self) -> dict:
        """Joint names, parents, world/local matrices and inverse bind matrices; needs ``skel=``."""
        if self.skel is None:
            raise SsbhError("this Numdlb has no SKEL payload (pass skel=...)")
        return self.skel.as_dict()

    def decode(self, *, textures: Mapping[str, np.ndarray] | None = None,
               objects: Iterable[int] | None = None) -> dict:
        """Decode the selected mesh objects into ``rig_from_gltf``-compatible primitives.

        Returns ``{"prims": [...], "joints": [{"parent", "world"}], "names": [...], "objects": [...]}``.
        Each prim has ``pos`` (n, 3 float32, +Y up, facing +Z in the game's own space), ``nrm``,
        ``uv``, ``tris`` (m, 3 int), ``tex`` (HxWx4 uint8 RGBA or None) and ``owner`` (per-vertex index
        into the joint list = largest skin weight, or the parent bone for unskinned objects).
        ``textures`` maps a texture name (``def_sonic_001_col``) to its decoded RGBA image; the albedo
        texture is chosen with :meth:`Numatb.albedo_candidates`.
        """
        if self.mesh is None or self.skel is None:
            raise SsbhError("decode() needs both the MESH and the SKEL payload")
        bone_index = {name: i for i, name in enumerate(self.skel.names)}
        entries = {(e["object"], e["subindex"]): e["material"] for e in self.materials()}
        textures = textures or {}
        prims = []
        for i in self.mesh.select(objects):
            obj = self.mesh.objects[i]
            verts = self.mesh.vertices(i)
            tris = self.mesh.triangles(i)
            material = entries.get((obj["name"], obj["subindex"]), "")
            tex = None
            if self.matl is not None and material:
                tex = self.matl.resolve_albedo(material, textures)
            owner = self.mesh.owners(i, bone_index)
            prims.append({
                "name": obj["name"], "subindex": obj["subindex"], "material": material,
                "pos": verts["pos"], "nrm": verts["nrm"], "uv": verts["uv"], "tris": tris,
                "tex": tex, "owner": owner,
                "tan": verts["tan"], "uv1": verts["uv1"], "color": verts["color"],
                "parent_bone": obj["parent_bone"], "skinned": bool(obj["use_vertex_skinning"]),
            })
        return {
            "prims": prims,
            "joints": [{"parent": p, "world": w} for p, w in zip(self.skel.parents, self.skel.world)],
            "names": list(self.skel.names),
            "objects": [i for i in self.mesh.select(objects)],
        }


# ------------------------------------------------------------------------------------------- MESH


class Numshb(_Ssbh):
    """SSBH ``MESH`` (``.numshb``): vertex buffers, mesh objects (submeshes), indices and skin weights.

    Supported versions: 1.8, 1.9 and 1.10 (the base game's fighter bodies are 1.10). All vertex
    attributes of a mesh object read from the shared vertex buffers at
    ``buffer_offset + object.vertex_bufferN_offset + vertex * strideN``.
    """

    _ATTR_STRIDE = {8: 20, 9: 48, 10: 48}
    _DATA_TYPES = {
        8: {820: "f3", 1076: "f4", 1077: "h4", 1079: "f2", 1024: "b4"},
        9: {820: "f3", 1076: "f4", 1077: "h4", 1079: "f2", 1024: "b4"},
        10: {0: "f3", 2: "b4", 4: "f4", 5: "h4", 7: "f2", 8: "h2"},
    }
    _USAGE = {0: "position", 1: "normal", 2: "binormal", 3: "tangent", 4: "uv", 5: "color"}
    OBJECT_SIZE = 0xD0
    RIGGING_SIZE = 40
    BONE_BUFFER_SIZE = 24

    def __init__(self, data: bytes):
        super().__init__(data, "MESH")
        version = int(self.minor)
        if self.major != 1 or version not in self._ATTR_STRIDE:
            raise SsbhError(f"MESH version {self.major}.{self.minor} is not supported (1.8-1.10)")
        self.model_name = self.string(0x00)
        self.bounding_info = self._bounding(0x08)
        self.unk1 = self.u32(0x6C)
        pointers = self.array(0x70)
        self._objects_ptr, self._object_count = pointers
        sizes_ptr, sizes_count = self.array(0x80)
        self.buffer_sizes = list(struct.unpack_from(f"<{sizes_count}I", self.data, sizes_ptr or 0))
        self.polygon_index_size = self.u64(0x90)
        vptr, self.vertex_buffer_count = self.array(0x98)
        self.vertex_buffers = [self._byte_buffer(vptr + 16 * i) for i in range(self.vertex_buffer_count)] if vptr else []
        self.index_buffer = self._byte_buffer(0xA8)
        self._rigging_ptr, self._rigging_count = self.array(0xB8)
        self.objects = self._read_objects()
        self.rigging = self._read_rigging()

    # -- helpers ----------------------------------------------------------------------------------

    def _bounding(self, at: int) -> dict:
        return {
            "sphere": {"center": self.floats(at, 3), "radius": self.f32(at + 12)},
            "volume": {"min": self.floats(at + 16, 3), "max": self.floats(at + 28, 3)},
            "obb": {"center": self.floats(at + 40, 3),
                    "transform": self.floats(at + 52, 9), "size": self.floats(at + 88, 3)},
        }

    def _byte_buffer(self, at: int) -> bytes:
        ptr, count = self.array(at)
        if ptr is None or count == 0:
            return b""
        self.check(ptr, count)
        return self.data[ptr:ptr + count]

    def _read_objects(self) -> list[dict]:
        objects = []
        attr_stride = self._ATTR_STRIDE[int(self.minor)]
        for i in range(self._object_count):
            at = (self._objects_ptr or 0) + self.OBJECT_SIZE * i
            attr_ptr, attr_count = self.array(at + 0xC0)
            attributes = []
            for j in range(attr_count):
                a = (attr_ptr or 0) + attr_stride * j
                usage, data_type, buffer_index, buffer_offset = struct.unpack_from("<4I", self.data, a)
                if attr_stride == 20:
                    subindex, name, names = self.u32(a + 16), "", []
                else:
                    subindex = self.u64(a + 16)
                    name = self.string(a + 24)
                    names_ptr, names_count = self.array(a + 32)
                    names = [self.string(names_ptr + 8 * k) for k in range(names_count)] if names_ptr else []
                attributes.append({"usage": usage, "usage_name": self._USAGE.get(usage, f"unk{usage}"),
                                   "data_type": data_type,
                                   "kind": self._DATA_TYPES[int(self.minor)].get(data_type, "?"),
                                   "buffer_index": buffer_index, "buffer_offset": buffer_offset,
                                   "subindex": subindex, "name": name, "attribute_names": names})
            objects.append({
                "name": self.string(at), "subindex": self.u64(at + 8), "parent_bone": self.string(at + 0x10),
                "vertex_count": self.u32(at + 0x18), "index_count": self.u32(at + 0x1C),
                "indices_per_face": self.u32(at + 0x20),
                "vertex_buffer_offsets": [self.u32(at + 0x24 + 4 * k) for k in range(4)],
                "strides": [self.u32(at + 0x34 + 4 * k) for k in range(4)],
                "index_buffer_offset": self.u32(at + 0x44), "unk8": self.u32(at + 0x48),
                "draw_element_type": self.u32(at + 0x4C), "use_vertex_skinning": self.u32(at + 0x50),
                "sort_bias": self.i32(at + 0x54), "depth_flags": [self.u8(at + 0x58), self.u8(at + 0x59)],
                "bounding_info": self._bounding(at + 0x5C), "attributes": attributes,
            })
        return objects

    def _read_rigging(self) -> dict:
        out = {}
        entry = np.dtype("<u2,<f4") if int(self.minor) >= 10 else np.dtype("<u4,<f4")
        for i in range(self._rigging_count):
            at = (self._rigging_ptr or 0) + self.RIGGING_SIZE * i
            name, subindex = self.string(at), self.u64(at + 8)
            max_influences, unk = self.u8(at + 16), self.u8(at + 17)
            buffers_ptr, buffers_count = self.array(at + 24)
            bones = []
            for j in range(buffers_count):
                e = (buffers_ptr or 0) + self.BONE_BUFFER_SIZE * j
                bone = self.string(e)
                if int(self.minor) >= 10:
                    raw = self._byte_buffer(e + 8)          # 1.10: a byte buffer, 6-byte entries
                else:                                       # 1.8/1.9: an array of 8-byte VertexWeightV8
                    data_ptr, data_count = self.array(e + 8)
                    raw = self.data[data_ptr:data_ptr + data_count * entry.itemsize] if data_ptr else b""
                count = len(raw) // entry.itemsize
                if count:
                    values = np.frombuffer(raw, dtype=entry, count=count)
                    bones.append({"bone": bone, "vertices": values["f0"].astype(np.int64),
                                  "weights": values["f1"].astype(np.float32)})
            out[(name, subindex)] = {"max_influences": max_influences, "unk": unk, "bones": bones}
        return out

    # -- public helpers ---------------------------------------------------------------------------

    def select(self, objects: Iterable[int] | None = None) -> list[int]:
        """Object indices to use (all of them when ``objects`` is None)."""
        return list(range(self._object_count)) if objects is None else [int(i) for i in objects]

    def _attribute(self, obj: dict, usage: int, subindex: int = 0) -> dict | None:
        for attr in obj["attributes"]:
            if attr["usage"] == usage and attr["subindex"] == subindex:
                return attr
        return None

    def _read_attribute(self, obj: dict, attr: dict) -> np.ndarray:
        buffer_index = attr["buffer_index"]
        stride = obj["strides"][buffer_index] if buffer_index < 4 else 0
        if not stride:
            raise SsbhError(f"{obj['name']}: attribute {attr['name'] or attr['usage_name']} uses buffer "
                            f"{buffer_index} with stride 0")
        buffer = self.vertex_buffers[buffer_index] if buffer_index < len(self.vertex_buffers) else b""
        start = obj["vertex_buffer_offsets"][buffer_index] + attr["buffer_offset"]
        count = obj["vertex_count"]
        kind = attr["kind"]
        widths = {"f3": (3, "<f4"), "f4": (4, "<f4"), "h4": (4, "<f2"), "h2": (2, "<f2"),
                  "f2": (2, "<f4"), "b4": (4, "u1")}
        if kind not in widths:
            raise SsbhError(f"{obj['name']}: unsupported attribute data type {attr['data_type']} "
                            f"(buffer {buffer_index})")
        width, dtype = widths[kind]
        needed = start + stride * (count - 1) + np.dtype(dtype).itemsize * width
        if needed > len(buffer):
            raise SsbhError(f"{obj['name']}: attribute {attr['name'] or attr['usage_name']} needs "
                            f"{needed} bytes but vertex buffer {buffer_index} has {len(buffer)}")
        raw = np.frombuffer(buffer, dtype=np.uint8, count=needed - start, offset=start)
        values = np.ndarray(shape=(count, width), dtype=dtype, buffer=raw, strides=(stride, np.dtype(dtype).itemsize))
        values = np.array(values, dtype=np.float32)
        if kind == "b4":
            values /= 255.0
        return values

    def vertices(self, index: int) -> dict:
        """Decoded vertex attributes of one mesh object.

        ``pos`` (n, 3), ``nrm`` (n, 3), ``tan`` (n, 3), ``uv`` (n, 2), ``uv1`` (n, 2) or None,
        ``color`` (n, 4) or None. Missing normals default to (0, 1, 0); missing UVs to 0.
        """
        obj = self.objects[index]
        position = self._attribute(obj, 0)
        if position is None:
            raise SsbhError(f"{obj['name']}: no position attribute (usage 0)")
        pos = self._read_attribute(obj, position)[:, :3]
        normal = self._attribute(obj, 1)
        tangent = self._attribute(obj, 3)
        uv, uv1, color = self._attribute(obj, 4, 0), self._attribute(obj, 4, 1), self._attribute(obj, 5)
        return {
            "pos": np.ascontiguousarray(pos, dtype=np.float32),
            "nrm": np.ascontiguousarray(self._read_attribute(obj, normal)[:, :3] if normal else
                                        np.tile([0.0, 1.0, 0.0], (obj["vertex_count"], 1)), dtype=np.float32),
            "tan": np.ascontiguousarray(self._read_attribute(obj, tangent)[:, :3] if tangent else
                                        np.zeros((obj["vertex_count"], 3)), dtype=np.float32),
            "uv": np.ascontiguousarray(self._read_attribute(obj, uv)[:, :2] if uv else
                                       np.zeros((obj["vertex_count"], 2)), dtype=np.float32),
            "uv1": (np.ascontiguousarray(self._read_attribute(obj, uv1)[:, :2], dtype=np.float32)
                    if uv1 else None),
            "color": (np.ascontiguousarray(self._read_attribute(obj, color)[:, :4], dtype=np.float32)
                      if color else None),
        }

    def triangles(self, index: int) -> np.ndarray:
        """``(m, 3)`` triangle list of one mesh object, decoded from the shared index buffer."""
        obj = self.objects[index]
        count = obj["index_count"]
        if not count:
            return np.zeros((0, 3), dtype=np.int64)
        offset = obj["index_buffer_offset"]
        dtype = "<u2" if obj["draw_element_type"] == 0 else "<u4"
        size = np.dtype(dtype).itemsize * count
        if offset + size > len(self.index_buffer):
            raise SsbhError(f"{obj['name']}: indices 0x{offset:x}+{size} run past the "
                            f"{len(self.index_buffer)}-byte index buffer")
        flat = np.frombuffer(self.index_buffer, dtype=dtype, count=count, offset=offset).astype(np.int64)
        if count % 3:
            raise SsbhError(f"{obj['name']}: {count} indices is not a whole number of triangles")
        return flat.reshape(-1, 3)

    def owners(self, index: int, bone_index: Mapping[str, int]) -> np.ndarray:
        """Per-vertex strongest bone (index into ``bone_index``), for skinning and for retargeting."""
        obj = self.objects[index]
        count = obj["vertex_count"]
        owner = np.full(count, -1, dtype=np.int64)
        best = np.zeros(count, dtype=np.float32)
        group = self.rigging.get((obj["name"], obj["subindex"]))
        if group:
            for bone in group["bones"]:
                joint = bone_index.get(bone["bone"])
                if joint is None:
                    continue
                vertices = bone["vertices"]
                weights = bone["weights"]
                valid = (vertices >= 0) & (vertices < count)
                vertices, weights = vertices[valid], weights[valid]
                better = weights > best[vertices]
                best[vertices[better]] = weights[better]
                owner[vertices[better]] = joint
        if not obj["use_vertex_skinning"] or (owner < 0).any():
            parent = bone_index.get(obj["parent_bone"])
            owner[owner < 0] = parent if parent is not None else 0
        return owner

    def influences(self, index: int, bone_index: Mapping[str, int], limit: int = 4) -> tuple[np.ndarray, np.ndarray]:
        """``(joints (n, limit) int, weights (n, limit) float)`` from the per-bone rigging buffers."""
        obj = self.objects[index]
        count = obj["vertex_count"]
        pairs: list[list[tuple[int, float]]] = [[] for _ in range(count)]
        group = self.rigging.get((obj["name"], obj["subindex"]))
        if group:
            for bone in group["bones"]:
                joint = bone_index.get(bone["bone"])
                if joint is None:
                    continue
                for vertex, weight in zip(bone["vertices"], bone["weights"]):
                    if 0 <= vertex < count:
                        pairs[vertex].append((joint, float(weight)))
        joints = np.zeros((count, limit), dtype=np.int64)
        weights = np.zeros((count, limit), dtype=np.float32)
        parent = bone_index.get(obj["parent_bone"], 0)
        for v, items in enumerate(pairs):
            items.sort(key=lambda item: -item[1])
            top = items[:limit]
            if not top:
                joints[v, 0], weights[v, 0] = parent, 1.0
                continue
            total = sum(w for _, w in top) or 1.0
            for k, (joint, weight) in enumerate(top):
                joints[v, k], weights[v, k] = joint, weight / total
        return joints, weights


# ------------------------------------------------------------------------------------------- SKEL


class Nusktb(_Ssbh):
    """SSBH ``SKEL`` (``.nusktb``): bone names, parents and the four transform-matrix arrays.

    Matrices are kept in the file's row-vector convention (``world_point = local_point @ world``); use
    :meth:`inverse_bind_matrices` for the column-vector matrices a glTF skin wants.
    """

    def __init__(self, data: bytes):
        super().__init__(data, "SKEL")
        if (self.major, self.minor) != SKEL_VERSION:
            raise SsbhError(f"SKEL version {self.major}.{self.minor}, expected 1.0")
        bone_ptr, self.bone_count = self.array(0x00)
        self.names: list[str] = []
        self.indices: list[int] = []
        self.parents: list[int] = []
        self.flags: list[dict] = []
        for i in range(self.bone_count):
            at = (bone_ptr or 0) + 16 * i
            self.names.append(self.string(at))
            self.indices.append(self.u16(at + 8))
            self.parents.append(self.i16(at + 10))
            self.flags.append({"unk1": self.u8(at + 12), "billboard": self.u8(at + 13)})
        self.world = self._matrices(0x10)
        self.inverse_world = self._matrices(0x20)
        self.local = self._matrices(0x30)
        self.inverse_local = self._matrices(0x40)

    def _matrices(self, at: int) -> np.ndarray:
        ptr, count = self.array(at)
        if ptr is None or count == 0:
            return np.zeros((0, 4, 4), dtype=np.float32)
        return np.stack([_matrix_rows(self, ptr + 64 * i) for i in range(count)])

    def inverse_bind_matrices(self) -> np.ndarray:
        """``(n, 4, 4)`` column-vector inverse bind matrices (glTF ``Matrix4x4`` order: transpose of the
        file's row-vector inverse-world matrix)."""
        return np.transpose(self.inverse_world, (0, 2, 1)) if len(self.inverse_world) else np.zeros((0, 4, 4))

    def as_dict(self) -> dict:
        return {"names": list(self.names), "parents": list(self.parents), "world": self.world,
                "local": self.local, "inverse_world": self.inverse_world,
                "inverse_bind": self.inverse_bind_matrices(), "flags": list(self.flags)}


# ------------------------------------------------------------------------------------------- MATL


class Numatb(_Ssbh):
    """SSBH ``MATL`` (``.numatb``): named materials with typed parameters and texture slots.

    Each material parameter is ``(u64 id, SSBH enum: relative offset + u64 data type)``; the value types
    this module decodes are float (1), boolean/u32 (2), vector4 (5), colour4 (7), string (11), sampler
    (14), UV transform (16), blend state (17) and rasterizer state (18). Texture names live in
    ``TextureN`` parameters (ids 92+N) and ``SamplerN`` (108+N) holds their sampler state.
    """

    def __init__(self, data: bytes):
        super().__init__(data, "MATL")
        if (self.major, self.minor) != MATL_VERSION:
            raise SsbhError(f"MATL version {self.major}.{self.minor}, expected 1.6")
        ptr, count = self.array(0x00)
        self.entry_count = count
        self.entries: list[dict] = []
        for i in range(count):
            at = (ptr or 0) + 32 * i
            label, shader = self.string(at), self.string(at + 24)
            attrs_ptr, attrs_count = self.array(at + 8)
            params, names = {}, {}
            for j in range(attrs_count):
                a = (attrs_ptr or 0) + 24 * j
                param_id = self.u64(a)
                value = self._param_value(a)
                params[param_id] = value
                names.setdefault(PARAM_NAMES.get(param_id, str(param_id)), value)
            self.entries.append({"label": label, "shader": shader, "params": params, "params_by_name": names})

    def _param_value(self, at: int):
        target, data_type = self.enum64(at + 8)
        if target is None:
            return None
        if data_type == 1:
            return self.f32(target)
        if data_type == 2:
            return self.u32(target)
        if data_type in (5, 7):
            return self.floats(target, 4)
        if data_type == 11:
            return self.string(target)
        if data_type == 14:
            return {"wrap_s": self.u32(target), "wrap_t": self.u32(target + 4),
                    "wrap_r": self.u32(target + 8), "min_filter": self.u32(target + 12),
                    "mag_filter": self.u32(target + 16), "filter": self.u32(target + 20),
                    "border": self.floats(target + 24, 4), "lod_bias": self.f32(target + 48),
                    "max_anisotropy": self.u32(target + 52)}
        if data_type == 16:
            return self.floats(target, 5)
        if data_type == 17:
            return {"source_color": self.u32(target), "color_op": self.u32(target + 4),
                    "destination_color": self.u32(target + 8), "source_alpha": self.u32(target + 12),
                    "alpha_op": self.u32(target + 16), "destination_alpha": self.u32(target + 20)}
        if data_type == 18:
            return {"fill_mode": self.u32(target), "cull_mode": self.u32(target + 4),
                    "depth_bias": self.f32(target + 8)}
        return {"data_type": data_type, "offset": target}

    # -- lookup -----------------------------------------------------------------------------------

    def labels(self) -> list[str]:
        """Material labels in file order (Sonic: 24, starting with ``EyeL``)."""
        return [entry["label"] for entry in self.entries]

    def entry(self, label: str) -> dict | None:
        return next((entry for entry in self.entries if entry["label"] == label), None)

    def texture_slots(self, label: str) -> dict[int, str]:
        """``{slot: texture name}`` for a material's ``TextureN`` parameters (measured: 0, 1, 4, 6, 7)."""
        entry = self.entry(label)
        if entry is None:
            return {}
        return {TEXTURE_PARAM_IDS[pid]: value for pid, value in entry["params"].items()
                if pid in TEXTURE_PARAM_IDS and isinstance(value, str)}

    def sampler_slots(self, label: str) -> dict[str, str]:
        """``{"SamplerN": texture name}``: the sampler a texture slot uses (measured: ``TextureN`` uses
        ``SamplerN``, so ``Sampler0``/``Sampler4``/``Sampler6``/``Sampler7`` on ``def_sonic_001``)."""
        return {f"Sampler{slot}": name for slot, name in sorted(self.texture_slots(label).items())}

    def albedo_candidates(self, label: str) -> list[str]:
        """Texture names to try for the albedo, most likely first.

        Measured: the albedo is ``Texture0`` (``_col``) on body materials; eye materials put the white
        base ``eyeW_*_col`` in ``Texture0`` and the per-eye ``_col`` map in ``Texture1``. Candidates are
        the first four texture slots in slot order, with ``_col`` names first, so a caller that only
        decodes textures which exist in the archive picks the right one.
        """
        slots = self.texture_slots(label)
        names = [slots[i] for i in sorted(slots) if i < 4 and slots[i]]
        colours = [name for name in names if name.lower().endswith("_col")]
        return colours + [name for name in names if name not in colours]

    def normal_name(self, label: str) -> str | None:
        """The ``_nor`` texture of a material (measured: slot 4, param id 96)."""
        slots = self.texture_slots(label)
        normals = [name for _, name in sorted(slots.items()) if name.lower().endswith("_nor")]
        return normals[0] if normals else slots.get(4)

    def resolve_albedo(self, label: str, textures: Mapping[str, np.ndarray]) -> np.ndarray | None:
        """The material's albedo as one RGBA image (see :meth:`composite_albedo`)."""
        return self.composite_albedo(label, textures)

    def composite_albedo(self, label: str, textures: Mapping[str, np.ndarray]) -> np.ndarray | None:
        """Pick the albedo image, compositing the eye shader's two colour maps when both exist.

        Measured: eye materials put a white/face base in ``Texture0`` and an alpha iris map in
        ``Texture1`` (``eye_mario_w_col`` + ``eye_mario_b_col``, ``eye_link_w_col`` + ``eye_link_b_col``).
        A glTF material has one base-colour texture, so the iris is alpha-composited over the base here;
        a caller that only wants the raw slot-0 image can use :meth:`texture_slots`.
        """
        names = [name for name in self.albedo_candidates(label) if name in textures]
        if not names:
            return None
        base = textures[names[0]]
        for name in names[1:]:
            overlay = textures[name]
            if overlay.shape != base.shape:
                continue
            coverage = float((overlay[..., 3] > 128).mean())
            if not 0.005 < coverage < 0.9:          # an opaque map is not an overlay
                continue
            alpha = overlay[..., 3:4].astype(np.float32) / 255.0
            rgb = (base[..., :3].astype(np.float32) * (1.0 - alpha)
                   + overlay[..., :3].astype(np.float32) * alpha)
            out = np.dstack([rgb, np.full(base.shape[:2], 255.0, np.float32)])
            return np.clip(out + 0.5, 0, 255).astype(np.uint8)
        return base

    def fallback_colour(self, label: str) -> tuple[float, float, float, float]:
        """A flat colour for a material whose albedo texture is unavailable.

        The PBS materials on this image carry no ``Diffuse`` parameter; ``CustomVector11`` (id 163) is
        their coloured term and is used when it is not black. ``eyeW*`` albedos are the eye's white base
        and get near-white. This is a presentation fallback, not a format fact.
        """
        entry = self.entry(label)
        if entry is None:
            return (0.6, 0.6, 0.6, 1.0)
        candidates = self.albedo_candidates(label)
        hint = (candidates[0] if candidates else "").lower()
        if "eyew" in hint or hint.startswith("eye"):
            return (0.92, 0.92, 0.92, 1.0)
        tint = entry["params"].get(163)
        if isinstance(tint, list) and len(tint) >= 3 and max(tint[:3]) > 0.03:
            return (float(tint[0]), float(tint[1]), float(tint[2]), 1.0)
        return (0.6, 0.6, 0.6, 1.0)


# ---------------------------------------------------------------------------------------- textures


def _block_height_mip0(height_in_blocks: int) -> int:
    """Infer the block height (in GOBs) from the mip height, as Ryujinx/tegra_swizzle do."""
    height = height_in_blocks + height_in_blocks // 2
    if height >= 128:
        return 16
    if height >= 64:
        return 8
    if height >= 32:
        return 4
    if height >= 16:
        return 2
    return 1


def _mip_block_height(height_in_blocks: int, block_height_mip0: int) -> int:
    height = block_height_mip0
    while height > 1 and height_in_blocks <= (height // 2) * 8:
        height //= 2
    return height


def _gob_offset(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Byte offset inside a GOB for byte coordinate (x, y) - Tegra TRM v1.3 page 1218."""
    return (((x % 64) // 32) * 256 + ((y % 8) // 2) * 64 + ((x % 32) // 16) * 32
            + (y % 2) * 16 + (x % 16))


def deswizzle_mip0(data: bytes, width: int, height: int, block_width: int, block_height: int,
                   bytes_per_block: int) -> np.ndarray:
    """Remove the Tegra X1 block-linear swizzle from the first mip; returns ``(height_blocks, row_bytes)``.

    ``width``/``height`` are in *pixels* (like a nutexb footer); ``block_width``/``block_height`` say how
    many pixels one block covers (4x4 for BC formats, 1x1 for uncompressed ones) and ``bytes_per_block``
    is the block's size in bytes. This is ``tegra_swizzle::surface::deswizzle_surface`` for mip 0.
    """
    width_blocks = max((width + block_width - 1) // block_width, 1)
    height_blocks = max((height + block_height - 1) // block_height, 1)
    row_bytes = width_blocks * bytes_per_block
    block_height_gobs = _mip_block_height(height_blocks, _block_height_mip0(height_blocks))
    gobs_x = (row_bytes + GOB_WIDTH - 1) // GOB_WIDTH
    x = np.arange(row_bytes, dtype=np.int64)
    y = np.arange(height_blocks, dtype=np.int64)
    block = y // (GOB_HEIGHT * block_height_gobs)
    inner = (y // GOB_HEIGHT) % block_height_gobs
    offsets = (block * (GOB_SIZE * block_height_gobs * gobs_x))[:, None] \
        + (inner * GOB_SIZE)[:, None] \
        + ((x // GOB_WIDTH) * (GOB_SIZE * block_height_gobs))[None, :] \
        + _gob_offset(x[None, :], (y % GOB_HEIGHT)[:, None])
    source = np.frombuffer(data, dtype=np.uint8)
    if int(offsets.max()) >= len(source):
        raise TextureError(f"swizzled surface needs {int(offsets.max()) + 1} bytes but only {len(source)} "
                           f"are present")
    return source[offsets]


def _rgb565(values: np.ndarray) -> np.ndarray:
    red = (values >> 11) & 0x1F
    green = (values >> 5) & 0x3F
    blue = values & 0x1F
    return np.stack([(red << 3) | (red >> 2), (green << 2) | (green >> 4), (blue << 3) | (blue >> 2)], -1)


def _bc1_rgba(blocks: np.ndarray) -> np.ndarray:
    """BC1 (DXT1): ``blocks`` (n, 8) uint8 -> (n, 16, 4) uint8."""
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    p0, p1 = _rgb565(c0).astype(np.float32), _rgb565(c1).astype(np.float32)
    four = c0 > c1
    p2 = np.where(four[:, None], (2 * p0 + p1) / 3.0, (p0 + p1) / 2.0)
    p3 = np.where(four[:, None], (p0 + 2 * p1) / 3.0, 0.0)
    palette = np.stack([p0, p1, p2, p3], 1)                     # (n, 4, 3)
    bits = (blocks[:, 4].astype(np.uint32) | (blocks[:, 5].astype(np.uint32) << 8)
            | (blocks[:, 6].astype(np.uint32) << 16) | (blocks[:, 7].astype(np.uint32) << 24))
    indices = np.stack([(bits >> (2 * k)) & 3 for k in range(16)], 1)
    rgba = np.concatenate([palette[np.arange(len(blocks))[:, None], indices],
                           np.full((len(blocks), 16, 1), 255, np.float32)], -1)
    if not four.all():
        transparent = (~four)[:, None] & (indices == 3)
        rgba[..., 3] = np.where(transparent, 0, 255)
    return np.clip(rgba + 0.5, 0, 255).astype(np.uint8)


def _bc4_values(blocks: np.ndarray, signed: bool) -> np.ndarray:
    """BC4: ``blocks`` (n, 8) uint8 -> (n, 16) float32 in 0..1 (or in -128..127 when signed)."""
    if signed:
        r0 = np.clip(blocks[:, 0].astype(np.int16) - 128, -127, 127).astype(np.float32)
        r1 = np.clip(blocks[:, 1].astype(np.int16) - 128, -127, 127).astype(np.float32)
    else:
        r0, r1 = blocks[:, 0].astype(np.float32), blocks[:, 1].astype(np.float32)
    bits = np.zeros(len(blocks), dtype=np.uint64)
    for k in range(6):
        bits |= blocks[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    indices = np.stack([(bits >> np.uint64(3 * k)) & np.uint64(7) for k in range(16)], 1)
    eight = (r0 > r1)[:, None]
    wide = np.empty((len(blocks), 8), dtype=np.float32)
    wide[:, 0], wide[:, 1] = r0, r1
    for k in range(2, 8):
        wide[:, k] = ((8 - k) * r0 + (k - 1) * r1) / 7.0
    narrow = np.empty((len(blocks), 8), dtype=np.float32)
    narrow[:, 0], narrow[:, 1] = r0, r1
    for k in range(2, 6):
        narrow[:, k] = ((6 - k) * r0 + (k - 1) * r1) / 5.0
    narrow[:, 6], narrow[:, 7] = (-127.0, 127.0) if signed else (0.0, 255.0)
    values = np.where(eight, wide, narrow)
    out = values[np.arange(len(blocks))[:, None], indices]
    return out / 127.0 if signed else out / 255.0


def _bc4_rgba(blocks: np.ndarray, signed: bool = False, channel: int = 0) -> np.ndarray:
    values = _bc4_values(blocks, signed)
    if signed:
        values = np.clip(values * 0.5 + 0.5, 0, 1)
    rgba = np.zeros((len(blocks), 16, 4), dtype=np.float32)
    rgba[..., channel] = values * 255.0
    rgba[..., 3] = 255.0
    return np.clip(rgba + 0.5, 0, 255).astype(np.uint8)


def _place_blocks(pixels: np.ndarray, width: int, height: int) -> np.ndarray:
    """(n_blocks, 16, 4) block order -> (height, width, 4)."""
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    image = pixels.reshape(blocks_y, blocks_x, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(blocks_y * 4,
                                                                                        blocks_x * 4, 4)
    return np.ascontiguousarray(image[:height, :width])


def _decode_bc7(raw: bytes, width: int, height: int) -> np.ndarray:
    try:
        import texture2ddecoder                    # type: ignore[import-not-found]
    except Exception as exc:                       # noqa: BLE001 - optional dependency
        raise TextureError("BC7 needs the optional 'texture2ddecoder' package "
                           "(pip install texture2ddecoder)") from exc
    try:
        bgra = texture2ddecoder.decode_bc7(raw, width, height)
    except Exception as exc:                       # noqa: BLE001 - the wheel rejects some payloads
        raise TextureError(f"texture2ddecoder failed on BC7: {exc}") from exc
    rgba = np.frombuffer(bgra, dtype=np.uint8).reshape(height, width, 4)[:, :, [2, 1, 0, 3]]
    return np.ascontiguousarray(rgba)


def _decode_blocks(raw: bytes, width: int, height: int, block_bytes: int) -> np.ndarray:
    """Split ``raw`` into 4x4 blocks, decoding BC1/BC2/BC3/BC4/BC5; returns block-order pixels."""
    count = ((width + 3) // 4) * ((height + 3) // 4)
    data = np.frombuffer(raw, dtype=np.uint8, count=count * block_bytes)
    blocks = data.reshape(count, block_bytes)
    return blocks


def _image_from_blocks(blocks: np.ndarray, width: int, height: int, mode: str) -> np.ndarray:
    if mode == "bc1":
        return _place_blocks(_bc1_rgba(blocks), width, height)
    if mode == "bc2":
        colour = _bc1_rgba(blocks[:, 8:]).astype(np.float32)
        packed = blocks[:, :8]
        alpha = np.empty((len(blocks), 16), dtype=np.float32)
        alpha[:, 0::2] = packed & 0x0F                # BC2 alpha: low nibble is the even pixel
        alpha[:, 1::2] = packed >> 4
        pixels = np.concatenate([colour[..., :3], (alpha * 17.0)[..., None]], -1)
        return _place_blocks(np.clip(pixels + 0.5, 0, 255).astype(np.uint8), width, height)
    if mode == "bc3":
        colour = _bc1_rgba(blocks[:, 8:]).astype(np.float32)
        alpha = _bc4_values(blocks[:, :8], False)[:, :, None] * 255.0
        pixels = np.concatenate([colour[..., :3], alpha], -1)
        return _place_blocks(np.clip(pixels + 0.5, 0, 255).astype(np.uint8), width, height)
    if mode in ("bc4", "bc4s"):
        return _place_blocks(_bc4_rgba(blocks, mode.endswith("s"), 0), width, height)
    if mode in ("bc5", "bc5s"):
        signed = mode.endswith("s")
        red = _bc4_values(blocks[:, :8], signed)
        green = _bc4_values(blocks[:, 8:], signed)
        if signed:
            red, green = np.clip(red * 0.5 + 0.5, 0, 1), np.clip(green * 0.5 + 0.5, 0, 1)
        pixels = np.zeros((len(blocks), 16, 4), dtype=np.float32)
        pixels[..., 0], pixels[..., 1] = red * 255.0, green * 255.0
        pixels[..., 3] = 255.0
        return _place_blocks(np.clip(pixels + 0.5, 0, 255).astype(np.uint8), width, height)
    raise TextureError(f"unsupported block mode {mode}")


def nutexb_image(data: bytes) -> tuple[np.ndarray, dict]:
    """Decode a NUTEXB texture's first mip into an ``(H, W, 4)`` uint8 RGBA array plus its header facts.

    The returned dict has ``name``, ``width``, ``height``, ``depth``, ``format`` (u32),
    ``format_name``, ``mip_count``, ``layers``, ``data_size``, ``data_offset`` (always 0: the surface
    starts at the beginning of the file), ``swizzled`` (footer ``unk3`` == 0x1000), ``mip_sizes`` (per
    layer) and, when decoding was not possible, ``warning`` and ``fallback`` - the image is then a flat
    :data:`FALLBACK_RGBA` and the caller should use a material colour instead. Only the first mip of the
    first array layer is decoded (fighter textures have one layer; ``layers``/``mip_sizes`` report the
    rest).
    """
    if len(data) < 112:
        raise TextureError(f"{len(data)} bytes is too short for the 112-byte nutexb footer")
    footer = len(data) - 112
    if data[footer:footer + 4] != b" XNT":
        raise TextureError(f"no nutexb footer at 0x{footer:x} (magic {data[footer:footer + 4]!r})")
    name = data[footer + 4:footer + 0x44].split(b"\0")[0].decode("ascii", "replace")
    width, height, depth, image_format, _unk2, mip_count, unk3, layers, data_size = struct.unpack_from(
        "<9I", data, footer + 0x44)
    version_major, version_minor = struct.unpack_from("<HH", data, footer + 0x6C)
    info = {"name": name, "width": width, "height": height, "depth": depth, "format": image_format,
            "format_name": NUTEXB_FORMATS.get(image_format, ("UNKNOWN", 1, 1, 0))[0],
            "mip_count": mip_count, "layers": layers, "data_size": data_size, "data_offset": 0,
            "swizzled": unk3 == 0x1000, "version": f"{version_major}.{version_minor}",
            "mip_sizes": []}
    if width == 0 or height == 0 or image_format not in NUTEXB_FORMATS:
        info["warning"] = f"unsupported nutexb format 0x{image_format:04x} or empty size"
        info["fallback"] = True
        return np.tile(np.array(FALLBACK_RGBA, dtype=np.uint8), (max(height, 1), max(width, 1), 1)), info
    _, block_w, block_h, block_bytes = NUTEXB_FORMATS[image_format]
    table = footer - 0x40 * max(layers, 1)
    for layer in range(layers):
        base = table + 0x40 * layer
        if base < 0:
            break
        info["mip_sizes"].append(list(struct.unpack_from(f"<{mip_count}I", data, base)))
    if data_size > footer:
        raise TextureError(f"data_size {data_size} runs into the footer at 0x{footer:x}")
    raw = data[:data_size]
    if info["swizzled"]:
        try:
            raw = deswizzle_mip0(data, width, height, block_w, block_h, block_bytes).reshape(-1).tobytes()
        except TextureError as exc:
            info["warning"] = str(exc)
            info["fallback"] = True
            return np.tile(np.array(FALLBACK_RGBA, dtype=np.uint8), (height, width, 1)), info
    mode = info["format_name"].split("_")[0].lower()
    if mode.startswith("bc"):
        block_suffix = info["format_name"].split("_")[1].lower()
        mode = mode if block_suffix != "snorm" else mode + "s"
    try:
        if mode == "bc7":
            rgba = _decode_bc7(raw, width, height)
        elif mode in ("bc1", "bc2", "bc3", "bc4", "bc4s", "bc5", "bc5s"):
            blocks = _decode_blocks(raw, width, height, block_bytes)
            rgba = _image_from_blocks(blocks, width, height, mode)
        elif mode in ("r8g8b8a8", "b8g8r8a8"):
            pixels = np.frombuffer(raw, dtype=np.uint8, count=width * height * 4).reshape(height, width, 4)
            rgba = np.ascontiguousarray(pixels[:, :, [2, 1, 0, 3]] if mode == "b8g8r8a8" else pixels)
        elif mode == "r32g32b32a32":
            floats = np.frombuffer(raw, dtype="<f4", count=width * height * 4).reshape(height, width, 4)
            rgba = np.clip(floats * 255.0 + 0.5, 0, 255).astype(np.uint8)
        elif mode == "r8":
            grey = np.frombuffer(raw, dtype=np.uint8, count=width * height).reshape(height, width)
            rgba = np.stack([grey, grey, grey, np.full_like(grey, 255)], -1)
        else:
            raise TextureError(f"format {info['format_name']} is not implemented")
    except (TextureError, ValueError) as exc:
        info["warning"] = str(exc)
        info["fallback"] = True
        return np.tile(np.array(FALLBACK_RGBA, dtype=np.uint8), (height, width, 1)), info
    return np.ascontiguousarray(rgba), info


# ------------------------------------------------------------------------------------- bone roles


#: SSBU fighter bone names -> retarget role. Measured on Sonic's real skeleton (115 bones): the arm chain
#: is ClavicleL -> ShoulderL -> ArmL -> HandL -> HaveL, so upper arm = ShoulderL, forearm = ArmL and hand =
#: HandL (HaveL is the weapon/attachment node); the leg chain is LegL -> KneeL -> FootL -> ToeL.
SSBU_ROLE_BONES = {
    "hip": ("Hip", "Hips", "hip"),
    "chest": ("Bust", "Chest", "Waist"),
    "neck": ("Neck", "neck"),
    "head": ("Head", "head"),
    "l_clav": ("ClavicleL", "ShoulderL_Clav"),
    "r_clav": ("ClavicleR",),
    "l_upper": ("ShoulderL", "UpperArmL", "ArmL"),
    "l_fore": ("ArmL", "ForeArmL", "LowerArmL"),
    "l_hand": ("HandL",),
    "r_upper": ("ShoulderR", "UpperArmR", "ArmR"),
    "r_fore": ("ArmR", "ForeArmR", "LowerArmR"),
    "r_hand": ("HandR",),
    "l_thigh": ("LegL", "ThighL", "UpperLegL"),
    "l_shin": ("KneeL", "ShinL", "LowerLegL"),
    "l_foot": ("FootL", "AnkleL"),
    "r_thigh": ("LegR", "ThighR", "UpperLegR"),
    "r_shin": ("KneeR", "ShinR", "LowerLegR"),
    "r_foot": ("FootR", "AnkleR"),
}


def roles_from_bones(names: Sequence[str]) -> dict[str, str]:
    """Map SSBU bone names onto :data:`gbox.retarget_profile.ROLES` (role -> bone name).

    Only roles whose bone actually exists are returned - a role is never invented. The mapping above is
    the standard SSBU fighter chain and is verified against the real sonic/mario/link skeletons; each
    joint is used for at most one role, and the more specific candidate wins (``Bust`` over ``Waist``
    for the chest, ``ShoulderL`` over ``ArmL`` for the upper arm).
    """
    from .retarget_profile import ROLES

    present = set(names)
    used: set[str] = set()
    roles: dict[str, str] = {}
    for role in ROLES:
        for candidate in SSBU_ROLE_BONES.get(role, ()):
            if candidate in present and candidate not in used:
                roles[role] = candidate
                used.add(candidate)
                break
    return roles


# ---------------------------------------------------------------------------------------------- glTF


def _png(rgba: np.ndarray) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba)).save(buffer, format="PNG")
    return buffer.getvalue()


class _GlbBuilder:
    """Accumulates glTF JSON + one binary blob (embedded PNG textures included)."""

    def __init__(self):
        self.blob = bytearray()
        self.gltf = {
            "asset": {"version": "2.0", "generator": "gbox ssbu_models"},
            "scene": 0, "scenes": [{"nodes": []}],
            "nodes": [], "meshes": [], "skins": [], "materials": [], "accessors": [],
            "bufferViews": [], "images": [], "textures": [], "samplers": [],
        }

    def _view(self, payload: bytes, target: int | None = None) -> int:
        while len(self.blob) % 4:
            self.blob.append(0)
        offset = len(self.blob)
        self.blob += payload
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        if target:
            view["target"] = target
        self.gltf["bufferViews"].append(view)
        return len(self.gltf["bufferViews"]) - 1

    def accessor(self, array: np.ndarray, component: int, kind: str, *, target: int = 34962,
                 normalized: bool = False, minmax: bool = False) -> int:
        data = np.ascontiguousarray(array)
        view = self._view(data.tobytes(), target)
        entry = {"bufferView": view, "componentType": component, "count": int(data.shape[0]) if data.ndim > 1
                 else int(data.size), "type": kind}
        if normalized:
            entry["normalized"] = True
        if minmax:
            flat = data.reshape(len(data), -1)
            if len(flat):
                entry["min"] = [float(v) for v in flat.min(0)]
                entry["max"] = [float(v) for v in flat.max(0)]
        self.gltf["accessors"].append(entry)
        return len(self.gltf["accessors"]) - 1

    def image(self, rgba: np.ndarray) -> int:
        view = self._view(_png(rgba))
        self.gltf["images"].append({"bufferView": view, "mimeType": "image/png"})
        return len(self.gltf["images"]) - 1

    def texture(self, rgba: np.ndarray) -> int:
        if not self.gltf["samplers"]:
            self.gltf["samplers"].append({"magFilter": 9729, "minFilter": 9987,
                                          "wrapS": 10497, "wrapT": 10497})
        self.gltf["textures"].append({"sampler": 0, "source": self.image(rgba)})
        return len(self.gltf["textures"]) - 1

    def write(self, path: Path) -> Path:
        self.gltf["buffers"] = [{"byteLength": len(self.blob)}]
        for key in ("meshes", "skins", "materials", "images", "textures", "samplers"):
            if not self.gltf[key]:
                del self.gltf[key]
        js = json.dumps(self.gltf, separators=(",", ":")).encode()
        js += b" " * (-len(js) % 4)
        blob = bytes(self.blob) + bytes(-len(self.blob) % 4)
        path.write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(blob))
                         + struct.pack("<II", len(js), 0x4E4F534A) + js
                         + struct.pack("<II", len(blob), 0x004E4942) + blob)
        return path


def _write_glb(model: Numdlb, textures: Mapping[str, np.ndarray], objects: Sequence[int],
               path: Path) -> dict:
    """Build the skinned glTF for ``objects``; returns counts used in the summary."""
    assert model.mesh is not None and model.skel is not None and model.matl is not None
    skel, mesh, matl = model.skel, model.mesh, model.matl
    builder = _GlbBuilder()
    bone_index = {name: i for i, name in enumerate(skel.names)}
    # Joint nodes carry the local transform; the hierarchy reproduces the file's world matrices.
    joint_nodes = []
    for i, name in enumerate(skel.names):
        # The file's row-vector matrix flattened row by row is the same list as the standard
        # (column-vector) matrix flattened column by column, which is what glTF stores.
        matrix = skel.local[i].reshape(-1).astype(np.float32) if len(skel.local) else np.eye(4).reshape(-1)
        joint_nodes.append({"name": name, "matrix": [float(v) for v in matrix]})
    for i, parent in enumerate(skel.parents):
        if 0 <= parent < len(joint_nodes):
            joint_nodes[parent].setdefault("children", []).append(i)
    builder.gltf["nodes"] = joint_nodes
    roots = [i for i, parent in enumerate(skel.parents) if parent < 0]
    ibm = skel.inverse_bind_matrices()
    if not len(ibm):
        ibm = np.tile(np.eye(4, dtype=np.float32), (len(skel.names), 1, 1))
    # glTF stores a matrix column-major; the file's row-vector inverse-world matrix already has that
    # element order, so write it row for row.
    ibm_accessor = builder.accessor(skel.inverse_world.reshape(len(skel.names), 16).astype(np.float32),
                                    5126, "MAT4", target=34962)
    skin_index = 0
    builder.gltf["skins"].append({"joints": list(range(len(skel.names))),
                                  "inverseBindMatrices": ibm_accessor,
                                  **({"skeleton": roots[0]} if roots else {})})
    material_index: dict[str, int] = {}
    entries = {(e["object"], e["subindex"]): e["material"] for e in model.materials()}
    textures_used: set[str] = set()
    triangles = vertices = 0
    for object_index in objects:
        obj = mesh.objects[object_index]
        verts = mesh.vertices(object_index)
        tris = mesh.triangles(object_index)
        material = entries.get((obj["name"], obj["subindex"]), "")
        label = material or f"{obj['name']}_{obj['subindex']}"
        prim: dict = {"attributes": {}, "mode": 4}
        attrs = prim["attributes"]
        attrs["POSITION"] = builder.accessor(verts["pos"], 5126, "VEC3", minmax=True)
        attrs["NORMAL"] = builder.accessor(verts["nrm"], 5126, "VEC3")
        attrs["TANGENT"] = builder.accessor(np.concatenate(
            [verts["tan"], np.ones((len(verts["tan"]), 1), np.float32)], 1), 5126, "VEC4")
        attrs["TEXCOORD_0"] = builder.accessor(verts["uv"], 5126, "VEC2")
        if obj["use_vertex_skinning"]:
            joints, weights = mesh.influences(object_index, bone_index)
            if len(skel.names) <= 255:
                attrs["JOINTS_0"] = builder.accessor(joints.astype(np.uint8), 5121, "VEC4")
            else:
                attrs["JOINTS_0"] = builder.accessor(joints.astype(np.uint16), 5123, "VEC4")
            attrs["WEIGHTS_0"] = builder.accessor(weights, 5126, "VEC4")
        if len(tris):
            flat = tris.reshape(-1).astype(np.uint32 if len(verts["pos"]) > 65535 else np.uint16)
            prim["indices"] = builder.accessor(flat, 5125 if flat.dtype == np.uint32 else 5123,
                                               "SCALAR", target=34963)
        if material and material not in material_index:
            albedo = matl.resolve_albedo(material, textures)
            normal = matl.normal_name(material)
            entry: dict = {"name": material, "doubleSided": True,
                           "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 0.75}}
            if albedo is not None:
                entry["pbrMetallicRoughness"]["baseColorTexture"] = {"index": builder.texture(albedo)}
                entry["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
                for name in matl.albedo_candidates(material):
                    if name in textures:
                        textures_used.add(name)
                        break
            else:
                entry["pbrMetallicRoughness"]["baseColorFactor"] = list(matl.fallback_colour(material))
            if normal and normal in textures:
                entry["normalTexture"] = {"index": builder.texture(textures[normal])}
                textures_used.add(normal)
            if albedo is not None and float((albedo[..., 3] < 250).mean()) > 0.01:
                entry["alphaMode"] = "BLEND"
            builder.gltf["materials"].append(entry)
            material_index[material] = len(builder.gltf["materials"]) - 1
        if material in material_index:
            prim["material"] = material_index[material]
        mesh_entry = {"name": f"{obj['name']}[{obj['subindex']}]", "primitives": [prim]}
        builder.gltf["meshes"].append(mesh_entry)
        node: dict = {"name": mesh_entry["name"], "mesh": len(builder.gltf["meshes"]) - 1}
        if obj["use_vertex_skinning"] or obj["parent_bone"] not in bone_index:
            builder.gltf["nodes"].append(node)           # model-space vertices with the skin's bind pose
            builder.gltf["nodes"][-1]["skin"] = skin_index
            roots.append(len(builder.gltf["nodes"]) - 1)
        else:
            builder.gltf["nodes"].append(node)           # bone-local vertices, rigidly under the bone
            builder.gltf["nodes"][bone_index[obj["parent_bone"]]].setdefault("children", []).append(
                len(builder.gltf["nodes"]) - 1)
        triangles += len(tris)
        vertices += len(verts["pos"])
    builder.gltf["scenes"][0]["nodes"] = roots
    builder.write(path)
    return {"triangles": int(triangles), "vertices": int(vertices), "materials": len(material_index),
            "textures_used": len(textures_used), "nodes": len(builder.gltf["nodes"])}


# ---------------------------------------------------------------------------------------- extraction


#: Base-name hints of the alternate face/expression meshes that the game toggles per animation. The first
#: mesh set of a fighter is its default appearance; these are extra overlays/variants in the same file.
_EXPRESSION_HINTS = ("blink", "brow", "talk", "ouch", "down", "pattern", "attack", "capture", "bound",
                     "cliff", "furafura", "ottotto", "catch", "hot", "result", "damage", "escape", "nohat")
#: Meshes of alternate forms / held props that are not part of the default body.
_FORM_HINTS = ("sphere", "ring", "item", "weapon")
#: Face-plate variants that are expression alternatives of the default ``FaceN`` plate.
_FACE_VARIANTS = ("flip", "center", "facenm", "faceo", "facet")


def default_object_indices(model: Numdlb) -> list[int]:
    """Choose the mesh objects that make up a fighter's default appearance.

    This is a *presentation heuristic*, not a format fact: a Smash model file packs every animation's
    face mesh and alternate form next to the default one, and the game hides them with animation tracks.
    The rule used here is measured on Sonic (77 objects), Mario (62) and Link (55):

    * drop expression meshes by base-name hint (Blink/Brow/Talk/Nohat...);
    * keep only the default ``FaceN`` face plate (Link's is ``FaceN_Mouth``; Mario's ``FaceNM*`` mouth
      shapes and every ``...FLIP``/``...center`` mirror are alternatives);
    * drop alternate forms and props by base-name hint (Sonic's spin-ball ``sphereM`` and ``RingM``);
    * keep everything else - a fighter's body is split into several mesh objects with the same name and
      increasing subindex (Sonic's object 0 is the blue body, object 1 the *same* object name at
      subindex 1 is the red shoes + white gloves, whose material happens to be called
      ``metal_sonic_001``; it is not an alternate body, so materials are not filtered).
    """
    assert model.mesh is not None
    mesh = model.mesh
    out = []
    for index, obj in enumerate(mesh.objects):
        base = obj["name"].lower()
        if any(hint in base for hint in _FORM_HINTS):
            continue
        if "eye" in base:                          # eye whites / irises are part of the default face
            out.append(index)
            continue
        if "face" in base:
            # Keep only the default FaceN plate (Link's is called FaceN_Mouth); drop mirrored/centred and
            # mouth-shape alternatives such as Mario's FaceNMClose / FaceNMHalf / FaceNMOpen.
            if "facen" in base and not any(variant in base for variant in _FACE_VARIANTS):
                out.append(index)
            continue
        if any(hint in base for hint in _EXPRESSION_HINTS):
            continue
        out.append(index)
    return out


def _texture_candidates(model: Numdlb, objects: Sequence[int]) -> list[str]:
    """Every albedo/normal texture name referenced by the materials of ``objects``, in use order."""
    assert model.mesh is not None and model.matl is not None
    entries = {(e["object"], e["subindex"]): e["material"] for e in model.materials()}
    names: list[str] = []
    for index in objects:
        obj = model.mesh.objects[index]
        label = entries.get((obj["name"], obj["subindex"]), "")
        if not label:
            continue
        for name in model.matl.albedo_candidates(label) + [model.matl.normal_name(label) or ""]:
            if name and name not in names and not name.startswith("#"):
                names.append(name)
    return names


def extract_fighter(fighter: str, arc, out_dir, *, name: str | None = None,
                    objects: Iterable[int] | None = None) -> dict:
    """Extract ``fighter``'s body model, textures and preview into ``out_dir``.

    Reads ``fighter/<fighter>/model/body/c00/{model.numdlb,model.numshb,model.nusktb,model.numatb}``
    from ``arc`` (a :class:`gbox.ssbu_arc.DataArc`), decodes every referenced texture that exists, writes
    ``<name>_ssbu.glb`` and ``<name>_ssbu.png`` and returns
    ``{fighter, joints, triangles, vertices, textures, materials, roles, glb, preview, notes}``.

    ``objects`` overrides the default object selection (:func:`default_object_indices`).
    """
    from . import characters

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = (name or fighter).lower()
    base = f"fighter/{fighter}/model/body/c00/"
    notes: list[str] = []
    model_paths = {}
    for filename in ("model.numdlb", "model.numshb", "model.nusktb", "model.numatb"):
        path = base + filename
        if not arc.exists(path):
            raise SsbhError(f"{path} is not in this archive")
        model_paths[filename] = arc.read(path)
    model = Numdlb(model_paths["model.numdlb"], mesh=Numshb(model_paths["model.numshb"]),
                   skel=Nusktb(model_paths["model.nusktb"]), matl=Numatb(model_paths["model.numatb"]))
    notes.append(f"read 4 SSBH files ({', '.join(f'{k}={len(v)}B' for k, v in model_paths.items())})")
    assert model.mesh is not None and model.skel is not None and model.matl is not None
    if model.mesh_file_name and model.mesh_file_name != "model.numshb":
        notes.append(f"MODL names the mesh file {model.mesh_file_name!r}")

    chosen = default_object_indices(model) if objects is None else [int(i) for i in objects]
    if objects is None:
        notes.append(f"default object selection: {len(chosen)} of {len(model.mesh.objects)} mesh objects "
                     f"(expression/alternate-form meshes excluded)")

    textures: dict[str, np.ndarray] = {}
    missing: list[str] = []
    unreadable: list[str] = []
    for tex_name in _texture_candidates(model, chosen):
        path = base + tex_name + ".nutexb"
        if not arc.exists(path):
            missing.append(tex_name)
            continue
        try:
            payload = arc.read(path)
        except Exception as exc:                   # noqa: BLE001 - a broken index entry must not abort a model
            unreadable.append(f"{tex_name} ({type(exc).__name__}: {exc})")
            continue
        try:
            rgba, info = nutexb_image(payload)
        except TextureError as exc:
            unreadable.append(f"{tex_name} ({exc})")
            continue
        textures[tex_name] = rgba
        if info.get("warning"):
            notes.append(f"texture {tex_name}: {info['warning']} (flat colour used)")
        elif info["format_name"] not in ("BC7_SRGB", "BC7_UNORM"):
            notes.append(f"texture {tex_name}: {info['format_name']} {info['width']}x{info['height']}")
    for tex_name in missing:
        notes.append(f"texture {tex_name}: no entry anywhere in this archive -> material colour fallback")
    for detail in unreadable:
        notes.append(f"texture {detail}: data.arc could not extract it -> material colour fallback")

    decoded = model.decode(textures=textures, objects=chosen)
    glb_path = out_dir / f"{slug}_ssbu.glb"
    counts = _write_glb(model, textures, chosen, glb_path)
    preview_path = out_dir / f"{slug}_ssbu.png"
    characters.render_preview(glb_path, preview_path, size=512, yaw=-30.0)

    roles = roles_from_bones(model.skel.names)
    from .retarget_profile import ROLES
    missing_roles = [role for role in ROLES if role not in roles]
    notes.append(f"bones={len(model.skel.names)} roles={len(roles)}/{len(ROLES)}"
                 + (f" missing={','.join(missing_roles)}" if missing_roles else " (all mapped)"))
    notes.append(f"textures embedded={len(textures)} of {len(textures) + len(missing) + len(unreadable)}"
                 f" referenced; materials used={counts['materials']}")
    if any("fallback" in note for note in notes):
        notes.append("textures without an archive entry are drawn with their material's flat colour")
    return {
        "fighter": fighter,
        "joints": len(model.skel.names),
        "triangles": counts["triangles"],
        "vertices": counts["vertices"],
        "textures": len(textures),
        "materials": counts["materials"],
        "roles": roles,
        "glb": str(glb_path),
        "preview": str(preview_path),
        "notes": notes,
    }


# ----------------------------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m gbox.ssbu_models --arc <data.arc> --fighter sonic --out <dir>``"""
    parser = argparse.ArgumentParser(description="Extract a Super Smash Bros. Ultimate fighter model")
    parser.add_argument("--arc", required=True, help="path to the extracted data.arc")
    parser.add_argument("--fighter", required=True, help="fighter folder name, e.g. sonic")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--name", default=None, help="output file stem (default: the fighter name)")
    parser.add_argument("--objects", default=None,
                        help="comma-separated mesh-object indices (default: the fighter's default set)")
    args = parser.parse_args(argv)
    from .ssbu_arc import DataArc

    with DataArc(args.arc) as arc:
        objects = [int(part) for part in args.objects.split(",")] if args.objects else None
        result = extract_fighter(args.fighter, arc, args.out, name=args.name, objects=objects)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
