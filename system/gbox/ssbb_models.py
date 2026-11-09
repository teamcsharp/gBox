"""Nintendo Wii / Super Smash Bros. Brawl (RSBE01) fighter model extraction: PAC -> BRRES -> MDL0/TEX0/PLT0.

Every offset below was measured on the operator's extracted disc (``.tmp/brawl/files/DATA/files/fighter/
fighter/<char>/Fit<Name>00.pac``); the parser was cross-checked against BrawlLib/BrawlCrate's structures
(``MDL0.cs``, ``MDL0ObjectNode.cs``, ``ElementCodec.cs``, ``VertexCodec.cs``) and against the data itself
(index ranges, face counts and texture sizes all agree).

PAC container (``.pac``/``.pcs``)
    0x00 "ARC\\0"; 0x04 u16 version (0x0101); 0x06 u16 child count; 0x08 u32 0; 0x0C u32 0;
    0x10 char[0x30] archive name (e.g. "FitSonic00"); children start at 0x40.
    Each child header (0x20 bytes): 0x00 i16 type (1 = Sakurai animation data, 2 = model BRRES, 3 = texture/
    palette/animation BRRES, 4 = extra animation BRRES, 8 = nested ARC), 0x02 i16 sub-index, 0x04 u32 payload
    size, 0x08 u8 group index, 0x09 i16 redirect (0x00FF = payload follows inline, otherwise the index of the
    child whose payload is reused). The payload follows the header and the next header is 0x20-aligned after it.
    Measured: FitSonic00.pac children @0x40/0x61EE0/0xDA680 (sizes 0x61E80/0x78780/0x5A00), 3D model in the
    first (type 2, sub 0) and TEX0/PLT0 in the second (type 3).

BRRES archive (NW4R)
    "bres" FEFF, u16 pad, u32 size, u16 root offset, u16 section count. Root: "root", u32 size, then an index
    group: u32 size, u32 count, (count+1) 16-byte entries (u16 id, u16 flag, u16 left, u16 right, u32 name,
    u32 data); pointers are relative to the group start and entry 0 is the group's own root node. Folder entries
    ("3DModels(NW4R)", "Textures(NW4R)", "Palettes(NW4R)", ...) point at further index groups whose entries are
    the resources (MDL0, TEX0, PLT0, CHR0, SRT0, SHP0, PAT0, VIS0, ...). Sub-file header: magic, u32 size,
    u32 version, s32 offset to the BRRES start, then version-specific fields.

MDL0 model (fighters: version 9, sections 11; versions 10/11 add FurVectors/FurLayerCoords = 13 sections)
    0x00 "MDL0"; 0x04 u32 size; 0x08 u32 version; 0x0C s32 brres offset (-(offset of the MDL0 from the BRRES));
    0x10 s32 section offset[n] (relative to the MDL0); name offset at 0x3C (v9) / 0x44 (v10) / 0x48 (v11).
    v9 section order: Definitions, Bones, Vertices, Normals, Colors, UVs, Materials, Shaders, Objects,
    Textures, Palettes. All sections except Definitions are BRRES index groups (name + data relative to group).
    Following the header at 0x40 is MDL0Props: u32 0x40, s32 mdl0 offset (=-0x40), s32 scaling rule, s32 tex
    matrix mode, s32 vertex count, s32 triangle count, s32 original path, s32 node count, u8 need normal matrix
    array, u8 need texture matrix array, u8 enable extents, u8 envelope matrix mode, u32 node-table offset
    (relative to the props), then a 0x18-byte bounding box.
    The node table (props + u32 at props+0x24) is u32 count followed by `count` s32 bone indices (-1 = none):
    node id -> bone index, measured 368 nodes / 83 bones for Sonic.
    Definitions group entries are node-definition streams: byte type 2 {u16 index, u16 parent node id},
    3 {u16 node id, u8 count, count x {u16 bone node id, f32 weight}}, 4 {u16 material, u16 object/polygon,
    u16 bone, u8 z} (a draw call), 5 {u16 node id, u16 env-matrix index}, 6 {u32}; any other byte ends the
    stream. Sonic ships 3 streams named "NodeTree", "NodeMix" and "DrawOpa"; "NodeMix" holds the 285 weighted
    bone mixes and the DrawOpa stream one draw call per object.

MDL0 bone (0xD0 bytes, version 9)
    0x00 s32 header length (0xD0); 0x04 s32 mdl0 offset; 0x08 s32 name offset; 0x0C s32 index;
    0x10 s32 node id; 0x14 u32 flags; 0x18 u32 billboard flags; 0x1C u32 billboard index;
    0x20 f32 scale[3]; 0x2C f32 rotation[3] (radians); 0x38 f32 translation[3];
    0x44 f32 bbox min[3]; 0x50 f32 bbox max[3]; 0x5C s32 parent offset; 0x60 s32 first child;
    0x64 s32 next sibling; 0x68 s32 previous sibling; 0x6C s32 user data;
    0x70 f32 world matrix (3x4 row-major, translation in column 3); 0xA0 f32 inverse bind matrix (3x4).
    Verified on all 46 fighter files: world @0x70 times inverse @0xA0 is the identity.

MDL0 vertex/normal/color/UV data nodes (all arrays are big-endian, GX quantised)
    Vertices (0x40 header): s32 data length, s32 mdl0 offset, s32 data offset (0x40), s32 name offset, s32
    index, s32 isXYZ, s32 component type (0 u8, 1 i8, 2 u16, 3 i16, 4 f32), u8 divisor, u8 stride, u16 count,
    f32 min[3], f32 max[3], 8 pad bytes; elements start at +0x40. Fighter positions are f32 XYZ (type 4).
    Normals (0x20 header): same but s32 isNBT at 0x14 (count triples for NBT), elements at +data offset (0x20),
    3 components always; component type/divisor as above.
    Colors (0x1C header): s32 isRGBA, s32 format (0 RGB565, 1 RGB5A3, 2 RGBA8), u8 stride, u8 pad, u16 count.
    UVs (0x40 header): s32 isST, s32 component type, u8 divisor, u8 stride, u16 count, f32 min[2], f32 max[2];
    elements at +data offset (0x40).
    A float element is divided by VQuant divisor: scale = 1/(1<<d) for d<32, 1<<(64-d) otherwise.

MDL0 object (0x64 header; version 9 layout, measured)
    0x00 s32 total length; 0x04 s32 mdl0 offset; 0x08 s32 single-bind bone node id (-1 = skinned);
    0x0C u32 vertex format low (CP VtxFmtLo); 0x10 u32 vertex format high (VtxFmtHi); 0x14 u32 vertex specs;
    0x18 {u32 buffer size, u32 used size, u32 offset} definitions group (offset from 0x18); 0x24 same triple
    for the primitive group (offset from 0x24); 0x30 u32 array flags; 0x34 s32 flag; 0x38 u32 name offset;
    0x3C s32 index; 0x40 s32 vertex count; 0x44 s32 face count; 0x48 i16 vertex data id; 0x4A i16 normal data
    id; 0x4C i16 color ids[2]; 0x50 i16 UV ids[8]; 0x60 s32 weight-table offset (always 0x64 in v9);
    0x64 s32 weight count + u16 weight node ids[count] (v10+ at 0x68).
    The definitions buffer starts with a MDL0PolygonDefs: 0x0A u16 0x0850, 0x0C u32 VtxFmtLo, 0x10 u16 0x0860,
    0x12 u32 VtxFmtHi, ... (CP/XF register writes). VtxFmtLo bits: 0 weighted, 1..8 texture-matrix present,
    9..10 position format-1, 11..12 normal, 13..14 color0, 15..16 color1; VtxFmtHi 2 bits per UV set
    (format-1, 0 = absent, 1 = u8 index, 2 = u16 index).

MDL0 primitive stream
    Repeated records: 0x20/0x28/0x30/0x38 = LoadIndexA/B/C/D (u16 node id, u16 matrix cache entry: low 12 bits
    / 12 is the cache slot); the other opcodes are GX draw commands, each followed by a u16 facepoint count:
    0x80 quads, 0x90 triangles, 0x98 triangle strip, 0xA0 triangle fan, 0xA8 lines, 0xB0 line strip,
    0xB8 points. Each facepoint is: [u8 weight index if weighted, = cache slot*3] [one u8 per texture matrix]
    then one index per attribute in position, normal, color0, color1, UV0..UV7 order (u8 for format 1, u16
    for format 2). The stream ends at the first byte that is not a known command. Facepoint vertex indices
    index the vertex/normal/color/UV arrays; the weight index selects the weighted bone mix node.

TEX0 / PLT0
    TEX0: magic, u32 size, u32 version, s32 brres offset, u32 data offset, u32 name offset, u32 flags,
    u16 width, u16 height, u32 GX format, u32 mipmap count; pixel data at +data offset, mip levels follow.
    GX formats seen in fighter files: 0x0 I4, 0x1 I8, 0x2 IA4, 0x3 IA8, 0x4 RGB565, 0x5 RGB5A3, 0x6 RGBA8,
    0x8 CI4, 0x9 CI8, 0xE CMPR (DXT1). Size: I4/CI4/CMPR w*h/2, I8/CI8/IA4 w*h, IA8/RGB565/RGB5A3 2*w*h,
    RGBA8 4*w*h. Textures are tiled: 8x8 texels per tile for the 4/8-bit formats (32/64 bytes) and CMPR
    (32 bytes = four 4x4 DXT blocks, order TL/TR/BL/BR), 4x4 texels per tile for IA8/RGB565/RGB5A3 (32 bytes)
    and RGBA8 (64 bytes); tiles run left to right, top to bottom.
    PLT0 (0x40 header): magic, u32 size, u32 version, s32 brres offset, s32 header length (0x40), u32 name
    offset, u32 palette format (0 IA8, 1 RGB565, 2 RGB5A3), i16 entry count, u16 pad, s32 original path
    offset, padding; entries are u16 big-endian colours at +header length.

Vertex spaces, skin weights and hidden meshes (confirmed against the data, all 46 fighter files)
    The node table (props + 0x24) has one s32 per node id: the bone index that node belongs to, or -1 for the
    285 weighted bone-mix nodes of Sonic (368 nodes / 83 bones). An object's weight table (object + 0x64) lists
    the node ids its primitive stream can use; its LoadIndexA (0x20) records fill a per-primitive-group matrix
    cache (slot = low 12 bits of the record's second u16 / 12) that maps the per-facepoint weight byte // 3 to a
    node id. A facepoint whose influence is a single bone stores its position in that bone's local space (its
    rest world position is bone_world * position); a facepoint with two or more bone weights is already in
    model space (its rest envelope matrix is the identity). Reading all vertices as model space leaves hundreds
    of stretched triangles per fighter (Sonic polygon2: ~450 of 1686 triangles longer than 3 model units);
    applying the single-bone rule leaves none on Sonic's body meshes, which is how BrawlLib's
    Vertex3.Weight()/Influence.CalcMatrix() treat bone-local vertex data.
    Meshes hung off the root transform chain instead of the pelvis subtree (Sonic's SphereM spin ball, Samus's
    two morph-ball spheres, Yoshi's egg, Meta Knight's mantle, Game & Watch's sleep bubbles) are animation-only
    props kept at full size in the file; they are skipped so the rest pose is the character (see
    ``Mdl0._is_effect_object``).
    Draw calls live in the Definitions streams named "DrawOpa"/"DrawXlu": byte type 4 then {u16 material index,
    u16 object index, u16 bone index, u8 z}. They give each object its material (and through the material's
    texture refs its base texture); Sonic ships 3 such streams, Mario adds a 1-call "DrawXlu" stream.
    CMPR (DXT1) blocks are 4x4 texels inside the 8x8 GX tile, in TL/TR/BL/BR order, and the four 2-bit index
    words of a block start at the least significant bits of the big-endian u32 index field.

Measured example (sonic/FitSonic00.pac, MDL0 v9 in the first BRRES at PAC 0x60, MDL0 at BRRES 0x80)
    PAC header 0x40, three children at 0x40/0x61EE0/0xDA680 (BRRES sizes 0x61E80/0x78780/0x5A00); model MDL0
    name "FitSonic00", 83 bones, 26 objects, 16806 primitive facepoints and 12310 triangles; 13 TEX0 resources
    (CMPR, CI4, CI8, I4, IA4 and RGB5A3) in the second BRRES. ``python -m gbox.ssbb_models --fighter-dir <dir>
    --out <dir> --all`` writes one skinned GLB + preview per fighter, summary.json and contact_sheet.png.
"""
from __future__ import annotations

import base64
import json
import struct
import sys
import unicodedata
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------- container constants

ARC_HEADER = 0x40
ARC_CHILD_HEADER = 0x20
ARC_INLINE = 0xFF
TEX0_FORMATS = {0x00: "I4", 0x01: "I8", 0x02: "IA4", 0x03: "IA8", 0x04: "RGB565", 0x05: "RGB5A3",
                0x06: "RGBA8", 0x08: "CI4", 0x09: "CI8", 0x0A: "CI14X2", 0x0E: "CMPR"}
_CI_FORMATS = {0x08, 0x09, 0x0A}
_SECTION_NAMES = {
    "v9": ["Definitions", "Bones", "Vertices", "Normals", "Colors", "UVs", "Materials", "Shaders", "Objects",
           "Textures", "Palettes"],
    "v11": ["Definitions", "Bones", "Vertices", "Normals", "Colors", "UVs", "FurVectors", "FurLayerCoords",
            "Materials", "Shaders", "Objects", "Textures", "Palettes"],
}
_DRAW_COMMANDS = {0x80: "quads", 0x90: "triangles", 0x98: "strip", 0xA0: "fan", 0xA8: "lines",
                  0xB0: "line_strip", 0xB8: "points"}
_LOAD_INDEX = {0x20: "A", 0x28: "B", 0x30: "C", 0x38: "D"}


# ---------------------------------------------------------------------------- small helpers

def _u8(d: bytes, o: int) -> int:
    return d[o]


def _u16(d: bytes, o: int) -> int:
    return struct.unpack_from(">H", d, o)[0]


def _i16(d: bytes, o: int) -> int:
    return struct.unpack_from(">h", d, o)[0]


def _u32(d: bytes, o: int) -> int:
    return struct.unpack_from(">I", d, o)[0]


def _i32(d: bytes, o: int) -> int:
    return struct.unpack_from(">i", d, o)[0]


def _f32(d: bytes, o: int) -> float:
    return struct.unpack_from(">f", d, o)[0]


def _cstr(d: bytes, o: int) -> str:
    """NUL-terminated ASCII string at offset ``o`` (empty for a zero/out-of-range pointer)."""
    if o <= 0 or o >= len(d):
        return ""
    end = d.find(b"\0", o)
    return d[o:end if end >= 0 else len(d)].decode("ascii", "replace")


def _f32s(d: bytes, o: int, n: int) -> np.ndarray:
    return np.array(struct.unpack_from(f">{n}f", d, o), np.float32)


def _mat34(d: bytes, o: int) -> np.ndarray:
    """A 3x4 row-major matrix (translation in column 3) as a 4x4 float32 matrix."""
    m = np.eye(4, dtype=np.float32)
    m[:3, :] = np.array(struct.unpack_from(">12f", d, o), np.float32).reshape(3, 4)
    return m


def _align(n: int, a: int = 0x20) -> int:
    return (n + a - 1) & ~(a - 1)


# ---------------------------------------------------------------------------- PAC container

def pac_files(data: bytes) -> list[dict]:
    """The children of a Brawl PAC/ARC container.

    Each entry: name, type (2 = model BRRES, 3 = textures/palettes, 4 = animation, 8 = nested ARC, 1 = Sakurai
    data), index, size, offset (absolute payload offset), magic (first four payload bytes), redirect (0xFF when
    the payload is inline), and resources (the names of the BRRES resources inside it, when it is a BRRES).
    """
    if data[:4] != b"ARC\0":
        raise ValueError("not a Brawl PAC (expected 'ARC\\0')")
    arc = _cstr(data, 0x10)
    version, count = _u16(data, 4), _u16(data, 6)
    out: list[dict] = []
    off = ARC_HEADER
    for i in range(count):
        if off + ARC_CHILD_HEADER > len(data):
            break
        ty, sub = _i16(data, off), _i16(data, off + 2)
        size = _u32(data, off + 4)
        redirect = _i16(data, off + 9) & 0xFFFF
        payload_at = off + ARC_CHILD_HEADER
        inline = redirect == ARC_INLINE and payload_at + size <= len(data)
        payload = data[payload_at:payload_at + size] if inline else b""
        magic = payload[:4].decode("latin1")
        entry = {"name": f"{arc}#{i}", "archive": arc, "type": ty, "index": sub, "size": size,
                 "offset": payload_at if inline else -1, "magic": magic, "redirect": redirect,
                 "inline": inline, "version": version, "resources": []}
        if magic in ("bres",) or payload[:3] == b"bres":
            try:
                entry["resources"] = [r["name"] for r in brres_models(payload)["resources"]]
                if entry["resources"]:
                    entry["name"] = entry["resources"][0]
            except (ValueError, struct.error, IndexError):
                pass
        out.append(entry)
        off = payload_at + _align(size, ARC_CHILD_HEADER)
    return out


def _pac_brres(data: bytes) -> list[tuple[str, bytes]]:
    """(label, BRRES bytes) for every BRRES payload of a PAC, descending into nested ARC children."""
    found: list[tuple[str, bytes]] = []
    for e in pac_files(data):
        payload = data[e["offset"]:e["offset"] + e["size"]] if e["inline"] else b""
        if not payload:
            continue
        if payload[:4] == b"bres":
            found.append((e["name"], payload))
        elif payload[:4] == b"ARC\0":
            try:
                found.extend((f"{e['name']}/{n}", b) for n, b in _pac_brres(payload))
            except (ValueError, struct.error):
                continue
    return found


# ---------------------------------------------------------------------------- BRRES groups

def _brres_group(data: bytes, at: int) -> list[tuple[str, int]]:
    """(name, absolute data offset) of each entry of the index group at ``at`` (entry 0 is skipped)."""
    count = _u32(data, at + 4)
    out = []
    for i in range(1, count + 1):
        e = at + 8 + i * 16
        name, ptr = _u32(data, e + 8), _u32(data, e + 12)
        out.append((_cstr(data, at + name), at + ptr))
    return out


def _tex0_info(data: bytes, at: int) -> dict:
    size, ver = _u32(data, at + 4), _u32(data, at + 8)
    data_off, name_off = _u32(data, at + 0x10), _u32(data, at + 0x14)
    w, h = _u16(data, at + 0x1C), _u16(data, at + 0x1E)
    fmt, mips = _u32(data, at + 0x20), _u32(data, at + 0x24)
    return {"name": _cstr(data, at + name_off), "offset": at, "size": size, "version": ver,
            "width": w, "height": h, "format": fmt, "format_name": TEX0_FORMATS.get(fmt, f"0x{fmt:X}"),
            "mipmaps": mips, "data_offset": data_off, "data_size": _tex0_pixel_size(fmt, w, h)}


def _tex0_pixel_size(fmt: int, w: int, h: int) -> int:
    """Stored size of the top mip level of a GX texture (bytes), padded to whole tiles."""
    if fmt in (0x00, 0x08, 0x0E):                            # I4, CI4, CMPR: 8x8 tiles, 32 bytes
        return max(1, (w + 7) // 8) * max(1, (h + 7) // 8) * 32
    if fmt in (0x01, 0x09):                                  # I8, CI8: 8x8 tiles, 64 bytes
        return max(1, (w + 7) // 8) * max(1, (h + 7) // 8) * 64
    if fmt == 0x02:                                          # IA4: 8x8 tiles, 32 bytes
        return max(1, (w + 7) // 8) * max(1, (h + 7) // 8) * 32
    if fmt in (0x03, 0x04, 0x05):                            # IA8, RGB565, RGB5A3: 4x4 tiles, 32 bytes
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 32
    if fmt == 0x06:                                          # RGBA8: 4x4 tiles, 64 bytes
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 64
    raise ValueError(f"unsupported GX texture format {fmt:#x}")


def _plt0_info(data: bytes, at: int) -> dict:
    size, ver = _u32(data, at + 4), _u32(data, at + 8)
    header_len = _i32(data, at + 0x10)
    name_off = _u32(data, at + 0x14)
    fmt = _u32(data, at + 0x18)
    count = _i16(data, at + 0x1C)
    return {"name": _cstr(data, at + name_off), "offset": at, "size": size, "version": ver,
            "format": fmt, "count": count, "header_len": header_len}


def brres_models(data: bytes) -> dict:
    """Parse one BRRES file: folders, contained resource names, MDL0 models, TEX0 textures, PLT0 palettes.

    Returns {"name", "size", "folders": {folder: [resource names]}, "resources": [{name, magic, offset,
    folder, version/size or width/height/format}], "models", "textures", "palettes"}.
    """
    if data[:4] != b"bres":
        raise ValueError("not a BRRES (expected 'bres')")
    if data[4:6] != b"\xfe\xff":
        raise ValueError("BRRES is not big-endian (BOM is not FEFF)")
    size, root = _u32(data, 8), _u16(data, 0xC)
    if data[root:root + 4] != b"root":
        raise ValueError("BRRES root block missing")
    out: dict = {"name": "", "size": size, "folders": {}, "resources": [], "models": [], "textures": [],
                 "palettes": []}
    for folder, fat in _brres_group(data, root + 8):
        names = []
        for name, at in _brres_group(data, fat):
            magic = data[at:at + 4].decode("latin1")
            info = {"name": name, "magic": magic, "offset": at, "folder": folder}
            try:
                if magic == "MDL0":
                    info.update(size=_u32(data, at + 4), version=_u32(data, at + 8))
                    out["models"].append(info)
                elif magic == "TEX0":
                    info.update(_tex0_info(data, at))
                    out["textures"].append(info)
                elif magic == "PLT0":
                    info.update(_plt0_info(data, at))
                    out["palettes"].append(info)
                elif magic in ("CHR0", "SRT0", "SHP0", "PAT0", "VIS0", "CLR0", "MAT0", "SCN0", "SND0"):
                    info.update(size=_u32(data, at + 4), version=_u32(data, at + 8))
            except (struct.error, IndexError):
                info["error"] = "truncated"
            names.append(name)
            out["resources"].append(info)
        out["folders"][folder] = names
        if out["name"] == "" and folder.startswith("3DModels") and names:
            out["name"] = names[0]
    return out


# ---------------------------------------------------------------------------- TEX0 / PLT0 decoding

def plt0_entries(data: bytes, at: int = 0) -> np.ndarray:
    """Palette colours of a PLT0 resource as an (n, 4) uint8 RGBA array (format 0 IA8, 1 RGB565, 2 RGB5A3)."""
    info = _plt0_info(data, at)
    start = at + (info["header_len"] or 0x40)
    n = max(0, info["count"])
    raw = np.frombuffer(data, np.uint8, n * 2, start).reshape(n, 2).astype(np.uint32)
    v = (raw[:, 0] << 8) | raw[:, 1]
    out = np.zeros((n, 4), np.uint8)
    if info["format"] == 1:                                  # RGB565
        out[:, 0] = ((v >> 11) & 0x1F) * 255 // 31
        out[:, 1] = ((v >> 5) & 0x3F) * 255 // 63
        out[:, 2] = (v & 0x1F) * 255 // 31
        out[:, 3] = 255
    elif info["format"] == 2:                                # RGB5A3
        rgb555 = (v & 0x8000) != 0
        out[rgb555, 0] = ((v[rgb555] >> 10) & 0x1F) * 255 // 31
        out[rgb555, 1] = ((v[rgb555] >> 5) & 0x1F) * 255 // 31
        out[rgb555, 2] = (v[rgb555] & 0x1F) * 255 // 31
        out[rgb555, 3] = 255
        a = ~rgb555
        out[a, 0] = ((v[a] >> 8) & 0xF) * 17
        out[a, 1] = ((v[a] >> 4) & 0xF) * 17
        out[a, 2] = (v[a] & 0xF) * 17
        out[a, 3] = ((v[a] >> 12) & 0x7) * 255 // 7
    else:                                                    # IA8 (alpha high byte, intensity low byte)
        out[:, 0] = out[:, 1] = out[:, 2] = v & 0xFF
        out[:, 3] = (v >> 8) & 0xFF
    return out


def _tiles(raw: bytes, w: int, h: int, tw: int, th: int, tile_bytes: int):
    """Yield ((x, y), bytes) for every tile in left-to-right, top-to-bottom order."""
    n = 0
    for ty in range(0, h, th):
        for tx in range(0, w, tw):
            yield (tx, ty), raw[n * tile_bytes:(n + 1) * tile_bytes]
            n += 1


def _decode_i4(tile: bytes) -> np.ndarray:
    a = np.frombuffer(tile, np.uint8, 32).reshape(8, 4)
    out = np.empty((8, 8), np.uint8)
    out[:, 0::2] = (a >> 4) & 0xF
    out[:, 1::2] = a & 0xF
    return out


def _decode_i8(tile: bytes) -> np.ndarray:
    return np.frombuffer(tile, np.uint8, 64).reshape(8, 8)


def _decode_ia4(tile: bytes) -> np.ndarray:
    a = np.frombuffer(tile, np.uint8, 32).reshape(8, 4)
    i = np.empty((8, 8), np.uint8)
    al = np.empty((8, 8), np.uint8)
    i[:, 0::2] = (a >> 4) & 0xF
    i[:, 1::2] = a & 0xF
    al[:, 0::2] = a & 0xF
    al[:, 1::2] = (a >> 4) & 0xF
    return np.stack([i * 17, i * 17, i * 17, al * 17], -1)


def _rgb565(v: np.ndarray) -> np.ndarray:
    out = np.zeros((len(v), 4), np.uint8)
    out[:, 0] = ((v >> 11) & 0x1F) * 255 // 31
    out[:, 1] = ((v >> 5) & 0x3F) * 255 // 63
    out[:, 2] = (v & 0x1F) * 255 // 31
    out[:, 3] = 255
    return out


def _rgb5a3(v: np.ndarray) -> np.ndarray:
    out = np.zeros((len(v), 4), np.uint8)
    rgb555 = (v & 0x8000) != 0
    out[rgb555, 0] = ((v[rgb555] >> 10) & 0x1F) * 255 // 31
    out[rgb555, 1] = ((v[rgb555] >> 5) & 0x1F) * 255 // 31
    out[rgb555, 2] = (v[rgb555] & 0x1F) * 255 // 31
    out[rgb555, 3] = 255
    a = ~rgb555
    out[a, 0] = ((v[a] >> 8) & 0xF) * 17
    out[a, 1] = ((v[a] >> 4) & 0xF) * 17
    out[a, 2] = (v[a] & 0xF) * 17
    out[a, 3] = ((v[a] >> 12) & 0x7) * 255 // 7
    return out


def _decode_cmpr(tile: bytes) -> np.ndarray:
    """A GX CMPR 8x8 tile = four DXT1 4x4 blocks in TL, TR, BL, BR order."""
    out = np.zeros((8, 8, 4), np.uint8)
    for blk in range(4):
        c = struct.unpack_from(">HHI", tile, blk * 8)
        c0, c1, bits = c[0], c[1], c[2]
        p = np.zeros((4, 4), np.uint8)
        for k in range(16):                                  # 2-bit indices, pixel 0 in the low bits (DXT order)
            p[k // 4, k % 4] = (bits >> (2 * k)) & 3
        a = _rgb565(np.array([c0], np.uint32))[0]
        b = _rgb565(np.array([c1], np.uint32))[0]
        if c0 > c1:
            pal = np.stack([a, b, (2 * a.astype(int) + b) // 3, (a.astype(int) + 2 * b) // 3]).astype(np.uint8)
        else:
            pal = np.stack([a, b, ((a.astype(int) + b) // 2), np.zeros(4, np.uint8)]).astype(np.uint8)
        blk_img = pal[p]
        ox, oy = (blk % 2) * 4, (blk // 2) * 4
        out[oy:oy + 4, ox:ox + 4] = blk_img
    return out


def _gx_image(fmt: int, w: int, h: int, raw: bytes, palette: np.ndarray | None) -> np.ndarray:
    """Decode one GX texture level to an (h, w, 4) uint8 RGBA array (tiled as in the module docstring)."""
    if fmt in (0x00, 0x08, 0x0E):                            # 8x8 tiles, 32 bytes
        tw = th = 8
    elif fmt in (0x01, 0x09, 0x02):                          # 8x8 tiles, 64 or 32 bytes
        tw = th = 8
    else:                                                    # IA8 / RGB565 / RGB5A3 / RGBA8: 4x4 tiles
        tw = th = 4
    pw, ph = max(tw, (w + tw - 1) // tw * tw), max(th, (h + th - 1) // th * th)
    canvas = np.zeros((ph, pw, 4), np.uint8)
    tile_bytes = {0x00: 32, 0x08: 32, 0x0E: 32, 0x01: 64, 0x09: 64, 0x02: 32,
                  0x03: 32, 0x04: 32, 0x05: 32, 0x06: 64}[fmt]
    pal = None if palette is None else np.asarray(palette, np.uint8)
    for (tx, ty), tile in _tiles(raw, pw, ph, tw, th, tile_bytes):
        if fmt == 0x0E:
            img = _decode_cmpr(tile)
        elif fmt == 0x00:
            v = _decode_i4(tile) * 17
            img = np.stack([v, v, v, np.full_like(v, 255)], -1)
        elif fmt == 0x08:
            idx = _decode_i4(tile).astype(np.int64)
            img = pal[idx % len(pal)] if pal is not None else \
                np.stack([idx * 17, idx * 17, idx * 17, np.full_like(idx, 255)], -1).astype(np.uint8)
        elif fmt == 0x01:
            v = _decode_i8(tile)
            img = np.stack([v, v, v, np.full_like(v, 255)], -1)
        elif fmt == 0x09:
            idx = _decode_i8(tile).astype(np.int64)
            img = pal[idx % len(pal)] if pal is not None else \
                np.stack([idx, idx, idx, np.full_like(idx, 255)], -1).astype(np.uint8)
        elif fmt == 0x02:
            img = _decode_ia4(tile)
        elif fmt == 0x03:
            v = np.frombuffer(tile, np.uint8, 32).reshape(16, 2)
            i, a = v[:, 1], v[:, 0]
            img = np.stack([i, i, i, a], -1).reshape(4, 4, 4)
        elif fmt in (0x04, 0x05):
            v = np.frombuffer(tile, np.uint8, 32).reshape(16, 2).astype(np.uint32)
            c = (v[:, 0] << 8) | v[:, 1]
            img = (_rgb565(c) if fmt == 0x04 else _rgb5a3(c)).reshape(4, 4, 4)
        else:                                                # 0x06 RGBA8: 4x4 tiles, ARGB bytes
            v = np.frombuffer(tile, np.uint8, 64).reshape(16, 4)
            img = v[:, [1, 2, 3, 0]].reshape(4, 4, 4)
        canvas[ty:ty + th, tx:tx + tw] = np.asarray(img, np.uint8)[:th, :tw]
    return canvas[:h, :w]


def tex0_image(data: bytes, offset: int = 0, palettes: dict[str, np.ndarray] | None = None) -> np.ndarray:
    """Decode a Brawl TEX0 texture (at ``offset`` in ``data``) to an (h, w, 4) uint8 RGBA array.

    ``palettes`` maps palette names to RGBA arrays (see ``plt0_entries``); CI4/CI8 need the palette whose name
    matches the texture's, falling back to the first one given.
    """
    info = _tex0_info(data, offset)
    w, h, fmt = info["width"], info["height"], info["format"]
    start = offset + info["data_offset"]
    raw = data[start:start + info["data_size"]]
    if len(raw) < info["data_size"]:
        raise ValueError(f"TEX0 {info['name']!r} is truncated")
    raw = raw.ljust(_tex0_pixel_size(fmt, max(w, 8), max(h, 8)), b"\0")
    palette = None
    if fmt in _CI_FORMATS:
        if palettes:
            palette = palettes.get(info["name"])
            if palette is None:
                palette = next(iter(palettes.values()))
            palette = np.asarray(palette, np.uint8)
        else:
            raise ValueError(f"TEX0 {info['name']!r} is paletted but no PLT0 palette was given")
    return _gx_image(fmt, w, h, raw, palette)


# ---------------------------------------------------------------------------- MDL0

class Mdl0:
    """A decoded Brawl MDL0 model: bones (world + inverse bind), vertex assets, objects and materials.

    After ``decode()`` the model exposes ``primitives`` (glTF-ready dicts) and ``joints`` (``{parent, world}``
    rest-pose bones), so ``gbox.characters.rig_from_gltf`` can read the written GLB back.
    """

    def __init__(self, data: bytes, offset: int = 0):
        if data[offset:offset + 4] != b"MDL0":
            raise ValueError("not a MDL0 resource")
        self.data = data
        self.offset = offset
        self.size = _u32(data, offset + 4)
        self.version = _u32(data, offset + 8)
        self.sections: dict[str, int] = {}
        names = _SECTION_NAMES["v11" if self.version >= 10 else "v9"]
        for name, off in zip(names, struct.unpack_from(f">{len(names)}i", data, offset + 0x10)):
            if off > 0:
                self.sections[name] = offset + off
        str_off = {10: 0x44, 11: 0x48}.get(self.version, 0x3C)
        self.name = _cstr(data, offset + _i32(data, offset + str_off))
        props_at = offset + {10: 0x48, 11: 0x4C}.get(self.version, 0x40)
        self.props = {
            "vertex_count": _i32(data, props_at + 0x10), "triangle_count": _i32(data, props_at + 0x14),
            "node_count": _i32(data, props_at + 0x1C),
            "node_table": props_at + _i32(data, props_at + 0x24),
        }
        self.bones = self._read_bones()
        self.bone_names = [b["name"] for b in self.bones]
        self.node_table = self._read_node_table()
        self.vertex_sets = self._read_group("Vertices")
        self.normal_sets = self._read_group("Normals")
        self.color_sets = self._read_group("Colors")
        self.uv_sets = self._read_group("UVs")
        self.materials = self._read_materials()
        self.textures = self._read_group("Textures")
        self.palettes = self._read_group("Palettes")
        self.objects = self._read_objects()
        self.draw_calls, self.mixes = self._read_defs()
        self.primitives: list[dict] = []

    # ---- groups / nodes -------------------------------------------------------------------------

    def _read_group(self, name: str) -> list[tuple[str, int]]:
        at = self.sections.get(name)
        return _brres_group(self.data, at) if at else []

    def _read_node_table(self) -> list[int]:
        at = self.props.get("node_table", 0)
        if not at or at + 4 > len(self.data):
            return []
        n = _i32(self.data, at)
        if n < 0 or at + 4 + n * 4 > len(self.data):
            return []
        return list(struct.unpack_from(f">{n}i", self.data, at + 4))

    def _read_bones(self) -> list[dict]:
        d = self.data
        out = []
        raw = []
        for name, at in self._read_group("Bones"):
            raw.append({"name": name, "at": at, "index": _i32(d, at + 0xC), "node": _i32(d, at + 0x10),
                        "flags": _u32(d, at + 0x14), "scale": _f32s(d, at + 0x20, 3),
                        "rotation": _f32s(d, at + 0x2C, 3), "translation": _f32s(d, at + 0x38, 3),
                        "parent_at": at + _i32(d, at + 0x5C), "world": _mat34(d, at + 0x70),
                        "inverse": _mat34(d, at + 0xA0)})
        by_at = {b["at"]: i for i, b in enumerate(raw)}
        for b in raw:
            parent_at = b.pop("parent_at")
            b["parent"] = -1 if parent_at == b["at"] else by_at.get(parent_at, -1)
        return raw

    def _read_materials(self) -> list[dict]:
        d = self.data
        out = []
        for name, at in self._read_group("Materials"):
            mat = {"name": name, "at": at, "index": _i32(d, at + 0xC), "textures": []}
            try:
                n = _i32(d, at + 0x2C)
                ref_off = _i32(d, at + 0x30)
            except struct.error:
                n, ref_off = 0, 0
            if 0 < n < 64 and ref_off:
                for k in range(n):
                    ref = at + ref_off + k * 0x34
                    try:
                        tex = _cstr(d, ref + _i32(d, ref))
                        plt = _cstr(d, ref + _i32(d, ref + 4))
                        mat["textures"].append({"texture": tex, "palette": plt or None,
                                                "wrap": (_i32(d, ref + 0x18), _i32(d, ref + 0x1C)),
                                                "ref": ref})
                    except (struct.error, IndexError):
                        break
            out.append(mat)
        return out

    def _read_objects(self) -> list[dict]:
        d = self.data
        wtab = self.data
        out = []
        for gi, (name, at) in enumerate(self._read_group("Objects")):
            try:
                obj = {
                    "name": name, "at": at, "group_index": gi, "length": _i32(d, at),
                    "node_id": _i32(d, at + 8), "fmt_lo": _u32(d, at + 0xC), "fmt_hi": _u32(d, at + 0x10),
                    "index": _i32(d, at + 0x3C), "num_vertices": _i32(d, at + 0x40),
                    "num_faces": _i32(d, at + 0x44), "vertex_id": _i16(d, at + 0x48),
                    "normal_id": _i16(d, at + 0x4A),
                    "color_ids": [_i16(d, at + 0x4C), _i16(d, at + 0x4E)],
                    "uv_ids": [_i16(d, at + 0x50 + 2 * k) for k in range(8)],
                }
                obj["defs_at"] = at + 0x18 + _i32(d, at + 0x20)
                obj["prims_at"] = at + 0x24 + _i32(d, at + 0x2C)
                obj["prims_size"] = _i32(d, at + 0x24)
                wcount_at = at + (0x68 if self.version >= 10 else 0x64)
            except (struct.error, IndexError):
                continue
            if _u16(d, obj["defs_at"] + 0x0A) == 0x0850:
                obj["vtx_fmt_lo"] = _u32(d, obj["defs_at"] + 0x0C)
                obj["vtx_fmt_hi"] = _u32(d, obj["defs_at"] + 0x12)
            else:                                            # header layout without the definitions copy
                obj["vtx_fmt_lo"], obj["vtx_fmt_hi"] = obj["fmt_lo"], obj["fmt_hi"]
            try:
                n = _i32(wtab, wcount_at)
                obj["weight_nodes"] = list(struct.unpack_from(f">{n}H", wtab, wcount_at + 4)) if 0 < n < 4096 \
                    else []
            except struct.error:
                obj["weight_nodes"] = []
            if 0 <= obj["num_vertices"] < 1 << 20 and 0 <= obj["prims_size"] < 1 << 26:
                out.append(obj)
        return out

    def _read_defs(self) -> tuple[dict[int, int], dict[int, list[tuple[int, float]]]]:
        """Draw calls (object index -> material index) and weighted bone mixes (node id -> [(bone node, w)])."""
        draw: dict[int, int] = {}
        mixes: dict[int, list[tuple[int, float]]] = {}
        at = self.sections.get("Definitions")
        if not at:
            return draw, mixes
        for name, start in _brres_group(self.data, at):
            p = end = start
            while end + 1 < len(self.data) and self.data[end] in (2, 3, 4, 5, 6):
                end = self._def_entry_end(end)
            if name.startswith("Draw"):
                for kind, vals in self._def_entries(start, end):
                    if kind == 4:
                        draw.setdefault(vals[1], vals[0])    # first draw call of a polygon wins
            elif name == "NodeMix":
                for kind, vals in self._def_entries(start, end):
                    if kind == 3:
                        mixes[vals[0]] = vals[1]
        return draw, mixes

    def _def_entry_end(self, p: int) -> int:
        d = self.data
        kind = d[p]
        if kind == 2:
            return p + 5
        if kind == 3:
            n = d[p + 3]
            return p + 4 + n * 6
        if kind == 4:
            return p + 8
        if kind == 5:
            return p + 5
        return p + 5                                        # kind 6: u32 skipped

    def _def_entries(self, start: int, end: int):
        d = self.data
        p = start
        while p < end:
            kind = d[p]
            if kind == 2:
                yield 2, (_u16(d, p + 1), _u16(d, p + 3))
                p += 5
            elif kind == 3:
                n = d[p + 3]
                ents = [(_u16(d, p + 4 + k * 6), _f32(d, p + 6 + k * 6)) for k in range(n)]
                yield 3, (_u16(d, p + 1), ents)
                p += 4 + n * 6
            elif kind == 4:
                yield 4, (_u16(d, p + 1), _u16(d, p + 3), _u16(d, p + 5), d[p + 7])
                p += 8
            elif kind == 5:
                yield 5, (_u16(d, p + 1), _u16(d, p + 3))
                p += 5
            elif kind == 6:
                p += 5
            else:
                break

    # ---- vertex assets --------------------------------------------------------------------------

    def _element_array(self, at: int, count: int, ctype: int, ncomp: int, divisor: int, data_at: int):
        """Decode ``count`` interleaved GX elements to a float32 (count, ncomp) array."""
        d = self.data
        size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4}[ctype]
        raw = d[data_at:data_at + count * ncomp * size]
        if len(raw) < count * ncomp * size:
            raise ValueError("vertex array is truncated")
        dt = {0: ">u1", 1: ">i1", 2: ">u2", 3: ">i2", 4: ">f4"}[ctype]
        arr = np.frombuffer(raw, dtype=dt, count=count * ncomp).reshape(count, ncomp).astype(np.float32)
        scale = 1.0 / (1 << divisor) if divisor < 32 else float(1 << (64 - divisor))
        return arr * scale if divisor else arr

    def _positions(self, set_index: int) -> np.ndarray:
        name, at = self.vertex_sets[set_index]
        d = self.data
        is_xyz, ctype = _i32(d, at + 0x14), _i32(d, at + 0x18)
        divisor, count = _u8(d, at + 0x1C), _u16(d, at + 0x1E)
        arr = self._element_array(at, count, ctype, 3 if is_xyz else 2, divisor, at + 0x40)
        if not is_xyz:
            arr = np.c_[arr, np.zeros(len(arr), np.float32)]
        return arr.astype(np.float32)

    def _normals(self, set_index: int) -> np.ndarray:
        name, at = self.normal_sets[set_index]
        d = self.data
        nbt, ctype = _i32(d, at + 0x14), _i32(d, at + 0x18)
        divisor, count = _u8(d, at + 0x1C), _u16(d, at + 0x1E)
        count *= 3 if nbt else 1
        data_at = at + _i32(d, at + 8)
        return self._element_array(at, count, ctype, 3, divisor, data_at).astype(np.float32)

    def _uvs(self, set_index: int) -> np.ndarray:
        name, at = self.uv_sets[set_index]
        d = self.data
        is_st, ctype = _i32(d, at + 0x14), _i32(d, at + 0x18)
        divisor, count = _u8(d, at + 0x1C), _u16(d, at + 0x1E)
        data_at = at + _i32(d, at + 8)
        arr = self._element_array(at, count, ctype, 2 if is_st else 1, divisor, data_at)
        if not is_st:
            arr = np.c_[arr, np.zeros(len(arr), np.float32)]
        return arr.astype(np.float32)

    def _colors(self, set_index: int) -> np.ndarray:
        name, at = self.color_sets[set_index]
        d = self.data
        fmt, stride, count = _i32(d, at + 0x18), _u8(d, at + 0x1C), _u16(d, at + 0x1E)
        data_at = at + _i32(d, at + 8)
        raw = d[data_at:data_at + count * max(stride, 1)]
        out = np.zeros((count, 4), np.float32)
        if fmt == 2:                                        # RGBA8
            v = np.frombuffer(raw, np.uint8, count * 4).reshape(count, 4).astype(np.float32)
            out[:] = v[:, :4]
        elif fmt == 0:                                      # RGB565
            v = np.frombuffer(raw, np.uint8, count * 2).reshape(count, 2).astype(np.uint16)
            c = (v[:, 0] << 8) | v[:, 1]
            out[:, 0] = ((c >> 11) & 0x1F) * 255 // 31
            out[:, 1] = ((c >> 5) & 0x3F) * 255 // 63
            out[:, 2] = (c & 0x1F) * 255 // 31
            out[:, 3] = 255
        elif fmt == 1:                                      # RGB5A3
            v = np.frombuffer(raw, np.uint8, count * 2).reshape(count, 2).astype(np.uint16)
            c = ((v[:, 0].astype(np.int32) << 8) | v[:, 1]).astype(np.uint32)
            out[:] = _rgb5a3(c)
        else:
            out[:] = 255
        return out / 255.0

    # ---- primitives -----------------------------------------------------------------------------

    @staticmethod
    def _attr_formats(obj: dict) -> list[tuple[str, int, int]]:
        """[(kind, slot, byte width)] for every attribute a facepoint stores, in stream order."""
        lo, hi = obj["vtx_fmt_lo"], obj["vtx_fmt_hi"]
        out = []
        for slot, shift, kind in ((0, 9, "pos"), (0, 11, "nrm"), (0, 13, "col"), (1, 15, "col")):
            fmt = (lo >> shift) & 3
            if fmt:
                if fmt == 1:                                 # GX direct: inline attribute, never used by fighters
                    raise ValueError("GX direct vertex attribute is not supported")
                out.append((kind, slot, 1 if fmt == 2 else 2))
        for i in range(8):
            fmt = (hi >> (2 * i)) & 3
            if fmt:
                if fmt == 1:
                    raise ValueError("GX direct UV attribute is not supported")
                out.append(("uv", i, 1 if fmt == 2 else 2))
        return out

    def _decode_object(self, obj: dict) -> dict:
        """Decode one object's primitive stream into facepoint arrays and triangles."""
        d = self.data
        lo = obj["vtx_fmt_lo"]
        weighted = bool(lo & 1)
        tex_mtx = [(lo >> (i + 1)) & 1 for i in range(8)]
        attrs = self._attr_formats(obj)
        stride = (1 if weighted else 0) + sum(tex_mtx) + sum(w for _k, _s, w in attrs)
        p, end = obj["prims_at"], obj["prims_at"] + obj["prims_size"]
        if not (0 < obj["prims_size"] and end <= len(d)):
            raise ValueError(f"object {obj['name']} has no primitive stream")
        cache: dict[int, int] = {}
        verts: list[dict] = []
        tris: list[tuple[int, int, int]] = []
        pos_cache: dict[int, np.ndarray] = {}

        def positions(sid):
            if sid not in pos_cache:
                pos_cache[sid] = self._positions(sid)
            return pos_cache[sid]

        def facepoint(start: int) -> dict:
            q = start
            fp = {"node": None}
            if weighted:
                fp["weight_byte"] = d[q]
                fp["slot"] = d[q] // 3
                fp["node"] = cache.get(fp["slot"])
                q += 1
            for i in range(8):
                if tex_mtx[i]:
                    fp[f"texmtx{i}"] = d[q]
                    q += 1
            for kind, slot, width in attrs:
                fp[f"{kind}{slot}"] = _u16(d, q) if width == 2 else d[q]
                q += width
            return fp

        base = len(verts)
        while p < end:
            cmd = d[p]
            p += 1
            if cmd in _LOAD_INDEX:
                node, extra = _u16(d, p), _u16(d, p + 2)
                p += 4
                if cmd == 0x20:
                    cache[(extra & 0xFFF) // 12] = node
                continue
            if cmd not in _DRAW_COMMANDS:
                break
            count = _u16(d, p)
            p += 2
            if p + count * stride > end:
                break
            start = len(verts)
            for k in range(count):
                fp = facepoint(p + k * stride)
                fp["index"] = len(verts)
                verts.append(fp)
            p += count * stride
            if cmd == 0x80:                                  # quads
                for k in range(0, count - 3, 4):
                    i = start + k
                    tris += [(i, i + 2, i + 1), (i, i + 3, i + 2)]
            elif cmd == 0x90:                                # triangles
                for k in range(0, count - 2, 3):
                    i = start + k
                    tris.append((i + 2, i + 1, i))
            elif cmd == 0x98:                                # triangle strip
                for k in range(count - 2):
                    a, b, c = start + k, start + k + 1, start + k + 2
                    tris.append((c, b, a) if k % 2 == 0 else (b, c, a))
            elif cmd == 0xA0:                                # triangle fan
                for k in range(2, count):
                    tris.append((start, start + k, start + k - 1))
            # lines / line strips / points carry no triangles
        return {"obj": obj, "verts": verts, "tris": tris, "cache": cache,
                "weighted": weighted, "attrs": attrs}

    def _vertex_weights(self, obj: dict, fp: dict, cache: dict[int, int]) -> list[tuple[int, float]]:
        """[(bone index, weight)] for a facepoint (single bind, bone node or weighted bone mix)."""
        if obj["node_id"] >= 0:
            node = obj["node_id"]
            return [(self._bone_of_node(node), 1.0)]
        node = fp.get("node")
        if node is None:
            node = cache.get(fp.get("slot", -1))
        if node is None:
            nodes = obj.get("weight_nodes") or []
            k = fp.get("slot", -1)
            node = nodes[k] if 0 <= k < len(nodes) else None
        if node is None:
            return [(0, 1.0)]
        mix = self.mixes.get(node)
        if mix:
            return [(self._bone_of_node(b), w) for b, w in mix]
        return [(self._bone_of_node(node), 1.0)]

    def _bone_of_node(self, node: int) -> int:
        if 0 <= node < len(self.node_table) and self.node_table[node] >= 0:
            return self.node_table[node]
        by_node = {b["node"]: i for i, b in enumerate(self.bones)}
        return by_node.get(node, 0)

    def _pelvis(self) -> int:
        for i, n in enumerate(self.bone_names):
            if _norm_bone(n) in ("hipn", "hip", "hips", "pelvis", "pelvisn", "hipj"):
                return i
        return -1

    def _body_bones(self) -> set[int]:
        """Bone indices in the pelvis subtree: everything animated with the body (not root-chain effect bones)."""
        hip = self._pelvis()
        if hip < 0:
            return set(range(len(self.bones)))
        out = set()
        for i in range(len(self.bones)):
            j = i
            while j >= 0:
                if j == hip:
                    out.add(i)
                    break
                j = self.bones[j]["parent"]
        return out

    def _is_effect_object(self, obj: dict) -> bool:
        """A rigid mesh hung off the root transform chain rather than the body (spin ball, egg, sleep bubbles,
        thrown/hammer props). Brawl keeps these at full size in the rest pose; only CHR0 animations scale them
        in, so rendering them would bury the character (Sonic's ``SphereM`` ball is centred on his whole body)."""
        if obj["node_id"] < 0:
            return False
        bi = {b["node"]: i for i, b in enumerate(self.bones)}.get(obj["node_id"])
        return bi is not None and bi not in self._body_bones()

    def _material_of(self, obj: dict) -> dict | None:
        """The object's material: its draw call's material, else the material whose name is the vertex-data name
        suffix (Brawl names a vertex set ``<mesh>__<material>``), else the material at the object's group index."""
        mi = self.draw_calls.get(obj["group_index"])
        if mi is not None and 0 <= mi < len(self.materials):
            return self.materials[mi]
        if obj["vertex_id"] < len(self.vertex_sets):
            stem = self.vertex_sets[obj["vertex_id"]][0]
            suffix = stem.split("__")[-1] if "__" in stem else ""
            if suffix:
                for mat in self.materials:
                    if suffix.endswith(mat["name"]) or suffix.lower().endswith(mat["name"].lower()):
                        return mat
        return self.materials[min(obj["group_index"], len(self.materials) - 1)] if self.materials else None

    def decode(self, textures: dict[str, np.ndarray] | None = None) -> list[dict]:
        """Decode every object with faces into a primitive compatible with gbox.characters.rig_from_gltf.

        Each primitive: pos (n,3) float32 in model space, nrm (n,3), uv (n,2), col (n,4) or None, tris (m,3)
        int32, tex (h,w,4) uint8 or None, owner (n,) int32 bone index, J (n,4) int64, W (n,4) float32,
        material/texture/palette names, wrap and name.
        """
        textures = textures or {}
        prims: list[dict] = []
        self.skipped: list[str] = []
        by_node = {b["node"]: i for i, b in enumerate(self.bones)}
        for obj in self.objects:
            if obj["num_vertices"] <= 0:
                continue
            if self._is_effect_object(obj):
                self.skipped.append(obj["name"])
                continue
            try:
                g = self._decode_object(obj)
            except (ValueError, IndexError, struct.error):
                continue
            if not g["tris"] or not g["verts"]:
                continue
            pos = self._positions(obj["vertex_id"]) if obj["vertex_id"] >= 0 else None
            nrm = self._normals(obj["normal_id"]) if obj["normal_id"] >= 0 else None
            # Brawl stores a vertex in the local space of its (single) bone when its influence is exactly one
            # bone - rigid single-bind objects and vertices of a weighted mesh that belong entirely to one bone.
            # Vertices with two or more weights are already in model space (their rest envelope matrix is the
            # identity). Verified on every fighter object: applying this per-facepoint rule removes all the
            # stretched triangles a plain model-space read produces (Sonic polygon2/4, Mario polygon0/2/9, ...).
            worlds = [np.asarray(b["world"], np.float64) for b in self.bones]
            uv = self._uvs(obj["uv_ids"][0]) if obj["uv_ids"] and obj["uv_ids"][0] >= 0 else None
            col = None
            for cid in obj["color_ids"]:
                if cid >= 0:
                    try:
                        col = self._colors(cid)
                    except (ValueError, IndexError, struct.error):
                        col = None
                    break
            if pos is None:
                continue
            n = len(g["verts"])
            p_out = np.zeros((n, 3), np.float32)
            n_out = np.zeros((n, 3), np.float32)
            uv_out = np.zeros((n, 2), np.float32)
            col_out = np.ones((n, 4), np.float32)
            owner = np.zeros(n, np.int32)
            J = np.zeros((n, 4), np.int64)
            W = np.zeros((n, 4), np.float32)
            for fp in g["verts"]:
                i = fp["index"]
                vid, nid = fp.get("pos0"), fp.get("nrm0")
                if vid is None or vid >= len(pos):
                    continue
                p = pos[vid]
                n = nrm[nid] if nrm is not None and nid is not None and nid < len(nrm) else None
                ws = sorted(self._vertex_weights(obj, fp, g["cache"]), key=lambda t: -t[1])[:4]
                if len(ws) == 1:                             # single-bone influence: stored in bone-local space
                    xf = worlds[ws[0][0]]
                    p = np.asarray(xf[:3, :3]) @ p + np.asarray(xf[:3, 3])
                    if n is not None:
                        n = np.asarray(xf[:3, :3]) @ n
                p_out[i] = p
                if n is not None:
                    n_out[i] = n
                uid = fp.get("uv0")
                if uv is not None and uid is not None and uid < len(uv):
                    uv_out[i] = uv[uid]
                if col is not None:
                    cid = fp.get("col0")
                    if cid is not None and cid < len(col):
                        col_out[i] = col[cid]
                tot = sum(w for _b, w in ws) or 1.0
                owner[i] = ws[0][0] if ws else 0
                for k, (b, w) in enumerate(ws):
                    J[i, k], W[i, k] = b, w / tot
            mat = self._material_of(obj)
            texture_name = palette_name = None
            image = None
            wrap = (10497, 10497)
            if mat is not None and mat["textures"]:
                ref = self._pick_texture(mat)
                if ref is not None:
                    texture_name, palette_name = ref["texture"], ref["palette"]
                    image = textures.get(texture_name)
                    wrap = {0: 33071, 1: 10497, 2: 33648}.get(ref["wrap"][0] & 0xFF, 10497), \
                        {0: 33071, 1: 10497, 2: 33648}.get(ref["wrap"][1] & 0xFF, 10497)
            prims.append({"name": f"{self.name}_{obj['name']}", "pos": p_out, "nrm": n_out, "uv": uv_out,
                          "col": None if col_out is None else col_out, "tris": np.array(g["tris"], np.int32),
                          "tex": image, "owner": owner, "J": J, "W": W,
                          "material": None if mat is None else mat["name"],
                          "texture": texture_name, "palette": palette_name, "wrap": wrap,
                          "double_sided": True})
        self.primitives = prims
        return prims

    @staticmethod
    def _pick_texture(mat: dict) -> dict | None:
        """Choose the base-colour texture of a material: the ref matching the material name, otherwise the first
        non-mask/env/base/highlight ref (Brawl lists masks and environment maps first, the colour map later)."""
        refs = [r for r in mat["textures"] if r.get("texture")]
        if not refs:
            return None
        stem = mat["name"]
        for suffix in ("_ExtMtl", "EnvBlend", "Env", "Normal", "Mask", "Ring", "Blend", "J", "N"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
        stem = stem.rstrip("LRlr")
        secondary = ("mask", "env", "highlight", "metal", "spec", "spc", "ref", "shadow", "kage", "damage",
                     "dmg", "spa")

        def score(ref: dict) -> tuple:
            name = ref["texture"].lower()
            base = stem.lower()
            exact = name.endswith(base) if base else False
            return (1 if exact else 0, -sum(s in name for s in secondary), len(ref["texture"]))

        best = max(refs, key=score)
        if not score(best)[0] and all(any(s in r["texture"].lower() for s in secondary) for r in refs):
            return refs[0]
        return best

    # ---- joints ---------------------------------------------------------------------------------

    def joints(self) -> list[dict]:
        """[{parent, world (4x4)}] rest-pose joints in group order (index = bone index)."""
        return [{"parent": b["parent"], "world": np.array(b["world"], np.float64)} for b in self.bones]


# ---------------------------------------------------------------------------- body roles

_ROLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hip", ("hipn", "hipj", "hip", "hips", "pelvis", "pelvisn")),
    ("chest", ("waistn", "chestn", "chest", "spine2", "spinen", "spine1", "spine", "bustn", "bodyn")),
    ("neck", ("neckn", "neck", "neckj")),
    ("head", ("headn", "headj", "head")),
    ("l_clav", ("lshouldern", "lshoulder", "lclaviclen", "lclavicle", "lclavn", "lclav")),
    ("l_upper", ("lshoulderj", "lupperarm", "larmj", "larmn", "larm")),
    ("l_fore", ("lelbown", "lelbowj", "leblow", "lforearm", "larmj", "lfore")),
    ("l_hand", ("lhandn", "lhande", "lhandj", "lhandb", "lhand", "lwrist")),
    ("r_clav", ("rshouldern", "rshoulder", "rclaviclen", "rclavicle", "rclavn", "rclav")),
    ("r_upper", ("rshoulderj", "rupperarm", "rarmj", "rarmn", "rarm")),
    ("r_fore", ("relbown", "relbowj", "relbow", "rforearm", "rarmj", "rfore")),
    ("r_hand", ("rhandn", "rhande", "rhandj", "rhandb", "rhand", "rwrist")),
    ("l_thigh", ("lthighj", "lthighn", "lthigh", "llegj", "llegn", "lleg", "lupperleg")),
    ("l_shin", ("lshinj", "lshinn", "lshin", "lkneej", "lknee", "llowerleg")),
    ("l_foot", ("lfootj", "lfootn", "lfoot", "lanklej", "lankle")),
    ("r_thigh", ("rthighj", "rthighn", "rthigh", "rlegj", "rlegn", "rleg", "rupperleg")),
    ("r_shin", ("rshinj", "rshinn", "rshin", "rkneej", "rknee", "rlowerleg")),
    ("r_foot", ("rfootj", "rfootn", "rfoot", "ranklej", "rankle")),
)
_ROLE_ORDER = [r for r, _c in _ROLE_RULES]
_ROLE_INDEX = {r: i for i, r in enumerate(_ROLE_ORDER)}


def _norm_bone(name: str) -> str:
    """Lower-case bone name without separators, so ``LShoulder_J`` and ``lshoulderj`` compare equal."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", name).lower() if ch.isalnum())


def roles_from_bones(names: list[str]) -> dict:
    """Map Brawl bone names onto ``gbox.retarget_profile.ROLES``.

    Brawl fighters share a naming scheme (``HipN``, ``WaistN``/``BustN``, ``NeckN``, ``HeadN``, ``LShoulderN``
    (clavicle), ``LShoulderJ`` (shoulder), ``LArmJ`` (elbow), ``LHandN``/``LHandE`` (wrist), ``LLegJ`` (hip),
    ``LKneeJ`` (knee), ``LFootJ`` (ankle) and R variants), but helper bones end in M/C/E and the roster
    variants differ (``LThighJ``/``LShinJ`` in some exports). Roles a skeleton does not have are simply absent
    from the result (Kirby has no neck/head bone, Sonic has no head bone, ...), never invented.
    Unmatched names are handed to :func:`gbox.rig_detect.from_names`, whose preset mappings fill leftovers.
    """
    norm = {}
    for n in names:
        key = _norm_bone(n)
        norm.setdefault(key, n)
    roles: dict[str, str] = {}
    used: set[str] = set()
    for role, candidates in _ROLE_RULES:
        for cand in candidates:
            hit = norm.get(cand)
            if hit and hit not in used:
                roles[role] = hit
                used.add(hit)
                break
    if len(roles) < 12:                                     # unusual names: try the generic presets
        try:
            from . import rig_detect
            for cand in rig_detect.from_names(names):
                for role, name in cand["roles"].items():
                    if role in _ROLE_INDEX and role not in roles and name not in used:
                        roles[role] = name
                        used.add(name)
                if len(roles) >= 14:
                    break
        except Exception:                                   # noqa: BLE001 - role detection is best effort
            pass
    return {r: roles[r] for r in _ROLE_ORDER if r in roles}


# ---------------------------------------------------------------------------- GLB packing

def _write_glb(gltf_text: str, out: Path) -> Path:
    """Pack a self-contained .gltf (base64 data URI buffer) into a binary .glb."""
    gl = json.loads(gltf_text)
    blob = b""
    buf = (gl.get("buffers") or [{}])[0]
    uri = buf.get("uri", "")
    if uri.startswith("data:"):
        blob = base64.b64decode(uri.split(",", 1)[1])
        buf.pop("uri", None)
    buf["byteLength"] = len(blob)
    js = json.dumps(gl, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += bytes(-len(blob) % 4)
    total = 12 + 8 + len(js) + (8 + len(blob) if blob else 0)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(js), 0x4E4F534A) + js)
        if blob:
            f.write(struct.pack("<II", len(blob), 0x004E4942) + blob)
    return out


# ---------------------------------------------------------------------------- character extraction

def _fighter_pac(fighter_dir: Path) -> Path | None:
    """The canonical ``Fit<Name>00.pac`` of a fighter directory (skips hats/spy/final/dark variants)."""
    best = None
    for p in sorted(Path(fighter_dir).glob("Fit*00.pac")):
        if any(s in p.name for s in ("Spy", "Final", "Entry", "Dark", "MotionEtc", "Result")):
            continue
        best = p if best is None or len(p.stem) < len(best.stem) else best
    return best


def _collect_textures(brres_blobs: list[bytes]) -> tuple[dict[str, np.ndarray], dict[str, dict]]:
    """Decode every TEX0 of every BRRES blob -> ({name: RGBA}, {name: info}). PLT0s are decoded per BRRES."""
    images: dict[str, np.ndarray] = {}
    infos: dict[str, dict] = {}
    for blob in brres_blobs:
        try:
            parsed = brres_models(blob)
        except (ValueError, struct.error):
            continue
        if not parsed["textures"]:
            continue
        palettes = {}
        for pi in parsed["palettes"]:
            try:
                palettes[pi["name"]] = plt0_entries(blob, pi["offset"])
            except (ValueError, struct.error):
                continue
        for ti in parsed["textures"]:
            if ti["name"] in images:
                continue
            try:
                images[ti["name"]] = tex0_image(blob, ti["offset"], palettes)
                infos[ti["name"]] = ti
            except (ValueError, struct.error):
                continue
    return images, infos


def extract_character(pac_path: Path, out_glb: Path, *, name: str | None = None) -> dict:
    """Decode the fighter model in ``pac_path`` and write a skinned GLB that ``gbox.characters.rig_from_gltf`` loads.

    Picks the MDL0 with the most vertices (the fighter body, not its shadow), textures it from every BRRES of the
    PAC (the model BRRES holds no TEX0) and returns a report: name, joints, triangles, vertices, textures, bones,
    roles, plus the texture/palette/material names it used.
    """
    from .melee_models import write_gltf

    pac_path = Path(pac_path)
    data = pac_path.read_bytes()
    blobs = _pac_brres(data)
    if not blobs:
        raise ValueError(f"{pac_path.name}: no BRRES resources inside the PAC")
    best = None
    for label, blob in blobs:
        try:
            parsed = brres_models(blob)
        except (ValueError, struct.error):
            continue
        for mi in parsed["models"]:
            try:
                cand = Mdl0(blob, mi["offset"])
            except (ValueError, struct.error):
                continue
            score = cand.props.get("vertex_count", 0)
            if best is None or score > best[0]:
                best = (score, label, blob, cand)
    if best is None:
        raise ValueError(f"{pac_path.name}: no decodable MDL0")
    _score, label, blob, model = best
    textures, tex_infos = _collect_textures([b for _l, b in blobs])
    palettes = {}
    try:
        parsed = brres_models(blob)
        for pi in parsed["palettes"]:
            palettes[pi["name"]] = plt0_entries(blob, pi["offset"])
    except (ValueError, struct.error):
        pass
    # decode with the palettes of every BRRES, so CI textures from the texture archive get their colours
    for other in blobs:
        if other is blob:
            continue
        try:
            parsed = brres_models(other)
        except (ValueError, struct.error):
            continue
        for pi in parsed["palettes"]:
            if pi["name"] not in palettes:
                try:
                    palettes[pi["name"]] = plt0_entries(other, pi["offset"])
                except (ValueError, struct.error):
                    continue
    prims = model.decode(textures=textures)
    if not prims:
        raise ValueError(f"{pac_path.name}: model {model.name!r} decoded no triangles")
    joints = model.joints()
    names = model.bone_names
    roles = roles_from_bones(names)
    out_glb = Path(out_glb)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_glb.with_suffix(".tmp.gltf")
    try:
        write_gltf(tmp, joints, prims, 1.0, name or model.name, names,
                   extras={"game": "ssbb", "char": name or model.name, "source": pac_path.name,
                           "mdl0_version": model.version})
        _write_glb(tmp.read_text(), out_glb)
    finally:
        tmp.unlink(missing_ok=True)
    all_roles = _ROLE_ORDER
    report = {
        "name": name or model.name, "model": model.name, "source": pac_path.name, "mdl0_version": model.version,
        "joints": len(joints), "bones": len(names), "triangles": int(sum(len(p["tris"]) for p in prims)),
        "vertices": int(sum(len(p["pos"]) for p in prims)), "primitives": len(prims),
        "textures": len({p["texture"] for p in prims if p["texture"]}),
        "textured_primitives": int(sum(1 for p in prims if p["tex"] is not None)),
        "texture_names": sorted({p["texture"] for p in prims if p["texture"]}),
        "materials": sorted({p["material"] for p in prims if p["material"]}),
        "roles": roles, "roles_missing": [r for r in all_roles if r not in roles],
        "skipped_effect_meshes": list(getattr(model, "skipped", [])),
        "glb_bytes": out_glb.stat().st_size, "container": [f["magic"] for f in pac_files(data)],
        "resources": len(blobs),
    }
    return report


# ---------------------------------------------------------------------------- previews / CLI

def _contact_sheet(previews: list[Path], out: Path, cell: int = 192, cols: int = 8) -> Path:
    """A grid of preview PNGs with the character name under each cell."""
    from PIL import Image, ImageDraw
    rows = (len(previews) + cols - 1) // cols
    pad, label = 4, 14
    sheet = Image.new("RGB", (cols * (cell + pad) + pad, rows * (cell + pad + label) + pad), (24, 25, 30))
    dr = ImageDraw.Draw(sheet)
    for i, p in enumerate(previews):
        try:
            im = Image.open(p).convert("RGB")
        except OSError:
            continue
        im.thumbnail((cell, cell))
        x = pad + (i % cols) * (cell + pad)
        y = pad + (i // cols) * (cell + pad + label)
        sheet.paste(im, (x + (cell - im.width) // 2, y + (cell - im.height) // 2))
        dr.text((x + 2, y + cell + 1), p.parent.name, fill=(210, 214, 222))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def main(argv: list[str] | None = None) -> int:
    """python -m gbox.ssbb_models --fighter-dir <dir> --out <dir> [--char sonic ...] [--all] [--no-preview]"""
    import argparse
    import time

    from .characters import check_preview, render_preview

    ap = argparse.ArgumentParser(description="Extract Super Smash Bros. Brawl fighter models (PAC/MDL0) to GLB.")
    ap.add_argument("--fighter-dir", required=True, help="...\\DATA\\files\\fighter\\fighter")
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--char", action="append", default=[], help="character directory name (repeatable)")
    ap.add_argument("--all", action="store_true", help="every character directory with a Fit<Name>00.pac")
    ap.add_argument("--size", type=int, default=384, help="preview size")
    ap.add_argument("--no-preview", action="store_true", help="skip preview rendering")
    args = ap.parse_args(argv)
    root = Path(args.fighter_dir)
    out = Path(args.out)
    dirs = [root / c for c in args.char] if args.char else []
    if args.all or not dirs:
        dirs = sorted(d for d in root.iterdir() if d.is_dir() and _fighter_pac(d))
    rows, previews = [], []
    for d in dirs:
        pac = _fighter_pac(d)
        if pac is None:
            rows.append({"char": d.name, "error": "no Fit<Name>00.pac"})
            continue
        dest = out / "models" / d.name / f"{d.name}_brawl.glb"
        try:
            rep = extract_character(pac, dest, name=d.name)
        except (ValueError, OSError, struct.error, IndexError) as e:
            rows.append({"char": d.name, "error": str(e)})
            continue
        row = {"char": d.name, "name": rep["name"], "source": rep["source"],
               "mdl0_version": rep["mdl0_version"], "triangles": rep["triangles"],
               "vertices": rep["vertices"], "textures": rep["textures"],
               "textured_primitives": rep["textured_primitives"], "joints": rep["joints"],
               "roles_mapped": len(rep["roles"]), "roles": rep["roles"],
               "roles_missing": rep["roles_missing"], "glb": str(dest.relative_to(out)),
               "glb_bytes": rep["glb_bytes"], "preview": "", "preview_bytes": 0,
               "skipped_effect_meshes": rep.get("skipped_effect_meshes", [])}
        if not args.no_preview:
            prev = dest.with_suffix(".png")
            prev.parent.mkdir(parents=True, exist_ok=True)
            try:
                render_preview(dest, prev, size=args.size)
                row["preview"] = str(prev.relative_to(out))
                row["preview_bytes"] = prev.stat().st_size
                row["preview_check"] = check_preview(prev)
                previews.append(prev)
            except (ValueError, OSError) as e:
                row["preview_error"] = str(e)
        rows.append(row)
    out.mkdir(parents=True, exist_ok=True)
    if previews:
        _contact_sheet(previews, out / "contact_sheet.png")
    summary = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "fighter_dir": str(root),
               "characters": len(rows), "extracted": sum(1 for r in rows if "error" not in r), "rows": rows}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({"characters": summary["characters"], "extracted": summary["extracted"],
                      "out": str(out)}, indent=1))
    return 0


__all__ = ["Mdl0", "brres_models", "extract_character", "main", "pac_files", "plt0_entries", "roles_from_bones",
           "tex0_image"]


if __name__ == "__main__":
    sys.exit(main())
