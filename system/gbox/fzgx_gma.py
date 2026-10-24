"""F-Zero GX (GFZE01) Amusement Vision GMA model container and AV texture pack (.tpl) parsers.

Layouts worked out on the owned disc (big-endian), e.g. chara/arrow_500.gma + .tpl:

GMA container
  0x00 u32 model_count, 0x04 u32 base (offset of first GCMF; 0x20 for 1 model)
  0x08 model_count * (u32 gcmf_offset_rel_base, u32 name_offset_rel_names)
  names block follows the entry table (NUL padded) and ends at `base`.
GCMF model (at base + gcmf_offset)
  +0x00 'GCMF'  +0x04 u32 attributes  +0x08 f32 x3 bounding-sphere origin  +0x14 f32 radius
  +0x18 u16 texture_ref_count  +0x1A u16 material_count  +0x1C u16 translucent_count
  +0x1E u8 transform_matrix_count  +0x1F pad  +0x20 u32 header_size (end of header, from GCMF)
  +0x24 u32 pad  +0x28 u8[8] default matrix indices  ...  header is 0x40 bytes, followed by
  `texture_ref_count` 0x20-byte texture records: +0x06 u16 TPL texture index, +0x0C u8 ...
AV TPL texture pack
  0x00 u32 texture_count, then texture_count * 0x10 entries
  (u32 gx_format, u32 data_offset, u16 width, u16 height, u32 mip/flags 0x00011234),
  data starts at the 0x20-aligned end of the table; each texture's data is contiguous,
  size = GX format size of width x height (no mip chain in the owned samples).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

GCMF_MAGIC = b"GCMF"
# gx_format -> (block_w, block_h, bytes_per_block)
GX_FORMATS = {
    0x0: (8, 8, 32),    # I4
    0x1: (8, 4, 32),    # I8
    0x2: (8, 4, 32),    # IA4
    0x3: (4, 4, 32),    # IA8
    0x4: (4, 4, 32),    # RGB565
    0x5: (4, 4, 32),    # RGB5A3
    0x6: (4, 4, 64),    # RGBA8
    0xE: (8, 8, 32),    # CMPR (DXT1)
}


class FzgxFormatError(ValueError):
    pass


def gx_size(fmt: int, w: int, h: int) -> int:
    if fmt not in GX_FORMATS:
        raise FzgxFormatError(f"unsupported GX texture format 0x{fmt:x}")
    bw, bh, bpb = GX_FORMATS[fmt]
    return ((w + bw - 1) // bw) * ((h + bh - 1) // bh) * bpb


@dataclass
class TplTexture:
    fmt: int
    offset: int
    width: int
    height: int
    flags: int
    size: int


@dataclass
class Gcmf:
    offset: int
    attributes: int
    origin: tuple
    radius: float
    texture_refs: int
    material_count: int
    translucent_count: int
    matrix_count: int
    header_size: int
    default_matrices: bytes
    tex_indices: list = field(default_factory=list)


@dataclass
class GmaModel:
    name: str
    gcmf: Gcmf


def parse_tpl(blob: bytes) -> list[TplTexture]:
    if len(blob) < 4:
        raise FzgxFormatError("tpl too short")
    n = struct.unpack_from(">I", blob, 0)[0]
    if n == 0 or n > 4096 or 4 + n * 0x10 > len(blob):
        raise FzgxFormatError(f"implausible texture count {n}")
    out = []
    for i in range(n):
        fmt, off, w, h, fl = struct.unpack_from(">IIHHI", blob, 4 + i * 0x10)
        size = gx_size(fmt, w, h)
        if off % 0x20 or off < 4 + n * 0x10 or off + size > len(blob):
            raise FzgxFormatError(f"texture {i}: bad data range off=0x{off:x} size=0x{size:x}")
        out.append(TplTexture(fmt, off, w, h, fl, size))
    return out


def parse_gma(blob: bytes) -> list[GmaModel]:
    if len(blob) < 8:
        raise FzgxFormatError("gma too short")
    count, base = struct.unpack_from(">II", blob, 0)
    if count == 0 or count > 4096 or base > len(blob) or 8 + count * 8 > base:
        raise FzgxFormatError(f"bad gma header count={count} base=0x{base:x}")
    names_off = 8 + count * 8
    models = []
    for i in range(count):
        goff, noff = struct.unpack_from(">II", blob, 8 + i * 8)
        ns = names_off + noff
        if ns >= base:
            raise FzgxFormatError(f"model {i}: name offset out of range")
        end = blob.find(b"\0", ns, base)
        name = blob[ns:end if end >= 0 else base].decode("latin-1")
        pos = base + goff
        if blob[pos:pos + 4] != GCMF_MAGIC:
            raise FzgxFormatError(f"model {i} ({name}): no GCMF magic at 0x{pos:x}")
        attrs, ox, oy, oz, rad = struct.unpack_from(">I4f", blob, pos + 4)
        tex, mat, trans = struct.unpack_from(">HHH", blob, pos + 0x18)
        mtx = blob[pos + 0x1E]
        hdr = struct.unpack_from(">I", blob, pos + 0x20)[0]
        defaults = blob[pos + 0x28:pos + 0x30]
        if pos + hdr > len(blob) or hdr < 0x40 + tex * 0x20:
            raise FzgxFormatError(f"model {i} ({name}): header_size 0x{hdr:x} inconsistent")
        idx = [struct.unpack_from(">H", blob, pos + 0x40 + k * 0x20 + 6)[0] for k in range(tex)]
        models.append(GmaModel(name, Gcmf(pos, attrs, (ox, oy, oz), rad, tex, mat, trans, mtx, hdr, defaults, idx)))
    return models


def check_pair(gma: bytes, tpl: bytes) -> dict:
    """Every texture index referenced by the models must exist in the TPL pack."""
    models, texs = parse_gma(gma), parse_tpl(tpl)
    mx = max((i for m in models for i in m.gcmf.tex_indices), default=-1)
    if mx >= len(texs):
        raise FzgxFormatError(f"texture index {mx} >= tpl count {len(texs)}")
    return {"models": [m.name for m in models], "textures": len(texs), "max_tex_index": mx}
