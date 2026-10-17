"""Frame-record decoder and sprite renderer for Yoshi's Story (N64, USA).

Analysis stage of #1323.  The game draws its pre-rendered 2D characters as a
set of textured quads: every animation frame is a 0x400-byte record that holds
a GBI1 (F3DEX) display list plus 24 vertices, and the CI8 tiles + 256-colour
TLUT it references live in a separate per-sprite texture buffer addressed
through segment 3.

Established on the owned ROM (z64 sha256
e8a63388c38f8f0bea37e9b13a97f0898ac5496e08ca2028afb8db9a866e0ce9):

* a frame record is 0x400 bytes.  Its display list runs from ``+0x000`` and
  always ends with the *prologue* ``04 00 61 7F 03 00 02 00`` at ``+0x3F8``:
  a GBI1 ``G_VTX`` that loads 24 vertices from ``seg3 + 0x200`` (0x180 bytes),
  which sit at ``+0x200`` inside the record itself.  The last 4 vertices of a
  short frame are zero-filled (only the quads the frame needs are populated).
* the DL body is, in order: ``G_SETTIMG`` for the TLUT at ``seg3 + 0x400``
  (fmt RGBA/16bpp), ``G_LOADTLUT`` (256 colours), then one
  ``G_SETTIMG``(CI/8bpp) / ``G_LOADBLOCK`` / ``G_SETTILESIZE`` / ``G_TRI2``
  group per texture tile.  Each ``G_TRI2`` emits two triangles that share an
  edge, i.e. one quad (vertex indices are 6-bit).
* ``OBJ_DRAW`` (0x8007BEE8, single caller 0x80076708) patches the display list
  with a ``G_MOVEWORD`` (0xBC000006 | seg<<10) whose word1 is
  ``dl_ram - (seg_addr & 0xFFFFFF)``, so segment-3 offsets are resolved
  relative to the buffer the frame DL was copied into, not the record's ROM
  address.  The TLUT/tiles are therefore filled by the texture-slot loader
  (see ``yoshi_story_analysis``) from a per-sprite texture atlas whose ROM
  base is still being pinned.

The CI8 tile/TLUT atlas for the frame bank is not yet resolved to a ROM
offset, so ``render_frame_png`` rasterises the decoded quads flat-shaded: it
proves the geometry (silhouette, vertex and UV decode) but not the texture
colours.  The tile seg3 offsets + texel counts needed to finish the decode are
returned by ``parse_frame``.
"""
from __future__ import annotations

import struct

FRAME_ALIGN = 0x400
FRAME_SIZE = 0x400
VTX_OFFSET = 0x200
PROLOGUE_OFFSET = 0x3F8
NV = 24
VTX_SIZE = 0x10  # 3x s16 pos, s16 flag, 2x s16 uv, 4x u8 rgba

# GBI1/F3DEX opcodes as used by this title (matches yoshi_story_inventory).
G_SETTIMG = 0xFD
G_SETTILE = 0xF5
G_LOADBLOCK = 0xF3
G_LOADTLUT = 0xF0
G_SETTILESIZE = 0xF2
G_TRI1 = 0xBF
G_TRI2 = 0xB1
G_VTX = 0x04
G_ENDDL = 0xB8  # F3DEX/GBI1; 0xDF belongs to GBI2

FMT = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}
SIZ = {0: 4, 1: 8, 2: 16, 3: 32}


def _w(rom: bytes, off: int) -> int:
    if off<0 or off+4>len(rom):
        raise ValueError("Word outside input")
    return struct.unpack_from(">I", rom, off)[0]


def prologue(rom: bytes, rec: int) -> bool:
    """True when ``rec`` looks like a frame record (G_VTX prologue at +0x3F8)."""
    if rec<0 or rec + FRAME_SIZE > len(rom):
        return False
    return _w(rom, rec + PROLOGUE_OFFSET) == 0x0400617F and _w(rom, rec + PROLOGUE_OFFSET + 4) == 0x03000200


def frame_records(rom: bytes, start: int = 0xB58B0) -> list[int]:
    """Return every 0x400-aligned frame-record offset in ``[start, len(rom))``.

    A record must *start* with ``G_SETTIMG`` (0xFD) and end with the G_VTX
    prologue at ``+0x3F8``.  The prologue alone is not sufficient: the CI8 tile
    atlas that precedes the frame bank (e.g. 0x9E6800) contains the 8-byte
    prologue pattern by coincidence and must not be counted as a record.
    """
    if start<0:
        raise ValueError("Frame scan start must be nonnegative")
    first = (start + FRAME_ALIGN - 1) // FRAME_ALIGN * FRAME_ALIGN
    return [off for off in range(first, len(rom) - FRAME_SIZE + 1, FRAME_ALIGN)
            if rom[off] == G_SETTIMG and prologue(rom, off)]


def decode_vertex(rom: bytes, off: int) -> dict:
    if off<0 or off+VTX_SIZE>len(rom):
        raise ValueError("Vertex outside input")
    x, y, z, flag, s, t = struct.unpack_from(">hhhHhh", rom, off)
    r, g, b, a = rom[off + 12:off + 16]
    return {"x": x, "y": y, "z": z, "flag": flag, "s": s, "t": t,
            "rgba": (r, g, b, a)}


def decode_vertices(rom: bytes, rec: int) -> list[dict]:
    """Decode the 24 vertices stored at ``rec + 0x200``."""
    if rec<0 or rec+FRAME_SIZE>len(rom):
        raise ValueError("Frame outside input")
    return [decode_vertex(rom, rec + VTX_OFFSET + i * VTX_SIZE) for i in range(NV)]


def _tri_indices(w0: int, w1: int) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    # GBI1 gsSP2Triangles: v00/v01/v02 in w0, v10/v11/v12 in w1 (indices multiplied by two).
    return ((w0 >> 17) & 0x7F, (w0 >> 9) & 0x7F, (w0 >> 1) & 0x7F), \
           ((w1 >> 17) & 0x7F, (w1 >> 9) & 0x7F, (w1 >> 1) & 0x7F)


def parse_frame(rom: bytes, rec: int) -> dict:
    """Parse one record: TLUT ref, tile refs (seg3 offset + texel count) and quads.

    The DL body before the vertices (``rec .. rec+0x200``) is walked in 8-byte
    command steps.  A tile is a ``G_SETTIMG`` (CI) followed by a ``G_LOADBLOCK``
    (texel count) and the ``G_TRI1``/``G_TRI2`` that draw it.
    """
    if not prologue(rom, rec):
        raise ValueError(f"0x{rec:X} is not a frame record (no G_VTX prologue)")
    tlut, tiles, tris, cur, tlut_seg3 = None, [], [], None, None
    for i in range(0, VTX_OFFSET, 8):
        op = rom[rec + i]
        w0, w1 = _w(rom, rec + i), _w(rom, rec + i + 4)
        if op == G_ENDDL:
            break
        if op == G_SETTIMG:
            if w1>>24!=3:
                raise ValueError("Unsupported frame texture segment")
            fmt, siz = (w0 >> 21) & 7, (w0 >> 19) & 3
            seg3 = w1 & 0xFFFFFF
            if fmt == 0:  # RGBA -> TLUT image
                tlut_seg3, cur = seg3, None
            else:
                cur = {"fmt": FMT.get(fmt, str(fmt)), "bpp": SIZ[siz], "seg3": seg3,
                       "texels": 0, "load_units": 0, "load_bpp":SIZ[siz], "tris": []}
                tiles.append(cur)
        elif op == G_LOADTLUT:
            tlut = {"seg3": tlut_seg3, "colors": ((w1 >> 14) & 0x3FF) + 1}
        elif op == G_SETTILE and cur is not None:
            # The render descriptor (last G_SETTILE before G_SETTILESIZE) carries
            # the sampled format: CI8 tiles are loaded 16bpp into TMEM but drawn
            # 8bpp, so the load G_SETTIMG's siz (16) must not be reported.
            fmt, siz = (w0 >> 21) & 7, (w0 >> 19) & 3
            cur["fmt"] = FMT.get(fmt, str(fmt))
            cur["bpp"] = SIZ[siz]
        elif op == G_LOADBLOCK and cur is not None:
            cur["load_units"] = ((w1 >> 12) & 0xFFF) + 1
        elif op == G_SETTILESIZE and cur is not None:
            uls,ult=(w0>>12)&0xfff,w0&0xfff
            lrs,lrt=(w1>>12)&0xfff,w1&0xfff
            if lrs<uls or lrt<ult:
                raise ValueError("Reversed frame tile bounds")
            cur["width"]=(lrs-uls)//4+1
            cur["height"]=(lrt-ult)//4+1
        elif op == G_TRI2 and cur is not None:
            a, b = _tri_indices(w0, w1)
            cur["tris"].extend([a, b])
            tris.extend([a, b])
        elif op == G_TRI1 and cur is not None:
            a = ((w1 >> 17) & 0x7F, (w1 >> 9) & 0x7F, (w1 >> 1) & 0x7F)
            cur["tris"].append(a)
            tris.append(a)
    if any(i>=NV for tri in tris for i in tri):
        raise ValueError("Triangle references vertex outside frame block")
    for tile in tiles:
        bits=tile["load_units"]*tile["load_bpp"]
        tile["load_bytes"]=(bits+7)//8
        tile["texels"]=bits//tile["bpp"]
    return {"rom": rec, "textured":False, "tlut": tlut, "tiles": tiles, "triangles": tris,
            "vertices": decode_vertices(rom, rec)}


def _tile_palette(i: int) -> tuple[int, int, int]:
    # distinct, stable colours for flat-shaded geometry previews
    return [(0xD8, 0x4A, 0x4A), (0x4A, 0x7B, 0xD8), (0x4A, 0xB8, 0x6A),
            (0xD8, 0xC0, 0x4A), (0xA8, 0x4A, 0xD8), (0x4A, 0xD8, 0xD4)][i % 6]


def render_frame_png(rom: bytes, rec: int, path, scale: int = 10, pad: int = 4):
    """Rasterise a frame's quads to a PNG (flat-shaded; texture atlas pending)."""
    from PIL import Image, ImageDraw

    if not isinstance(scale,int) or not isinstance(pad,int) or scale<=0 or pad<0:
        raise ValueError("Preview scale must be positive and padding nonnegative")
    f = parse_frame(rom, rec)
    verts = f["vertices"]
    tris = f["triangles"]
    if not tris:
        raise ValueError(f"frame at 0x{rec:X} has no triangles")
    used={i for tri in tris for i in tri}
    xs = [verts[i]["x"] for i in used]
    ys = [verts[i]["y"] for i in used]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w = (maxx - minx + 1) * scale + 2 * pad
    h = (maxy - miny + 1) * scale + 2 * pad
    if w>8192 or h>8192 or w*h>16*1024*1024:
        raise ValueError("Frame preview exceeds pixel limit")
    img = Image.new("RGB", (w, h), (24, 24, 24))
    d = ImageDraw.Draw(img)

    def px(v):
        return ((v["x"] - minx) * scale + pad, (maxy - v["y"]) * scale + pad)

    # colour each triangle by the tile it belongs to
    tri_colour = []
    for i,tile in enumerate(f["tiles"]):
        tri_colour.extend([_tile_palette(i)] * len(tile["tris"]))
    for k, (i0, i1, i2) in enumerate(tris):
        d.polygon([px(verts[i0]), px(verts[i1]), px(verts[i2])],
                  fill=tri_colour[k] if k < len(tri_colour) else (255, 255, 255))
    img.save(path)
    return {"path": str(path), "textured":False, "size": (w, h), "bbox": (minx, miny, maxx, maxy),
            "triangles": len(tris), "tiles": len(f["tiles"])}
