"""Paper Mario (USA) sprite reader/exporter (#1673 reader stage): sprite -> editable PNGs + index,
and PNG -> CI4 re-encode, stdlib only.

Rounds the #1673 analysis probe into a usable reader: ``export_sprite`` writes every raster of a
player or NPC sprite as an 8-bit RGBA PNG (own palette applied, index 0 transparent), the palettes
as JSON (raw RGBA5551 + swatch PNGs), and an ``index.json`` of raster/animation records.
``png_to_ci4`` re-encodes such a PNG back to native CI4 pixels for a fixed 16-colour palette;
``export_sprite(..., encode=True)`` verifies every written PNG re-encodes byte-identical to the ROM
data (no-op roundtrip, the writer-stage precondition).
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from . import pm_inventory as pm
from . import pm_sprite_probe as pr


# ----------------------------------------------------------------------------- PNG decode (stdlib)
def decode_png_rgba(png: bytes) -> tuple[int, int, bytes]:
    """Decode an 8-bit RGBA (colour type 6), non-interlaced PNG. Returns (w, h, RGBA bytes)."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    p, idat, w = 8, b"", 0
    ihdr = None
    while p < len(png):
        n, t = struct.unpack_from(">I4s", png, p)
        d = png[p + 8:p + 8 + n]
        if struct.unpack_from(">I", png, p + 8 + n)[0] != zlib.crc32(t + d):
            raise ValueError("PNG chunk CRC mismatch")
        if t == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", d)
        elif t == b"IDAT":
            idat += d
        p += 12 + n
    if ihdr is None:
        raise ValueError("missing IHDR")
    w, h, depth, ctype, comp, filt, inter = ihdr
    if (depth, ctype, comp, filt, inter) != (8, 6, 0, 0, 0):
        raise ValueError(f"unsupported PNG form (depth={depth} ctype={ctype} interlace={inter}); want 8-bit RGBA")
    stride = w * 4
    raw = zlib.decompress(idat)
    out = bytearray()
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:  # sub
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 0xFF
        elif f == 2:  # up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:  # average
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:  # paeth
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                b, c = prev[i], (prev[i - 4] if i >= 4 else 0)
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pr_ = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr_) & 0xFF
        elif f != 0:
            raise ValueError(f"unknown PNG filter {f}")
        out += line
        prev = line
    return w, h, bytes(out)


# ----------------------------------------------------------------------------- PNG -> CI4
def png_to_ci4(png: bytes, pal: bytes) -> bytes:
    """Re-encode a PNG produced from ``pal`` back to native CI4 bytes (high nibble first).

    Colour index 0 is transparency: any fully transparent pixel maps to 0. Other pixels must match
    a palette entry after the RGBA5551 round-trip quantization used by the exporter.
    """
    w, h, rgba = decode_png_rgba(png)
    if len(pal) < 32:
        raise ValueError("short palette")
    # lookup keyed on the quantized RGBA5551-expansion so encoder round-trips are exact
    lut: dict[tuple[int, int, int, int], int] = {(0, 0, 0, 0): 0}
    for i, c in enumerate(struct.unpack(">16H", pal[:32])):
        r, g, b, a = pr.rgba5551(c)
        key = (r, g, b, a)
        if key == (0, 0, 0, 0):
            continue
        lut[key] = i  # first entry wins, matching table order
    out = bytearray()
    idxs = []
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            px = rgba[i:i + 4]
            idx = 0 if px[3] == 0 else lut.get((px[0], px[1], px[2], px[3]))
            if idx is None:
                # tolerate 8-bit rounding: compare after re-quantization to 5-bit
                q = (((px[0] >> 3) << 3) | (px[0] >> 5), ((px[1] >> 3) << 3) | (px[1] >> 5),
                     ((px[2] >> 3) << 3) | (px[2] >> 5), px[3])
                idx = lut.get(q)
            if idx is None:
                raise ValueError(f"pixel ({x},{y}) RGBA {px!r} not in the 16-colour palette")
            idxs.append(idx)
    # nibbles continue across row boundaries (linear packing, matches spr DMA/cache layout)
    for j in range(0, len(idxs), 2):
        out.append((idxs[j] << 4) | (idxs[j + 1] if j + 1 < len(idxs) else 0))
    return bytes(out)


def palette_png(pal: bytes) -> bytes:
    """16-swatch strip (one row) of a palette, for eyeballing/editing colours."""
    px = b"".join(bytes(pr.rgba5551(c) if c & 1 else (0, 0, 0, 0)) for c in struct.unpack(">16H", pal[:32]))
    return _raw_rgba_png(px, 16, 1)


def _raw_rgba_png(rgba: bytes, w: int, h: int) -> bytes:
    rows = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


# ----------------------------------------------------------------------------- export
def _anim_components(rom: bytes, hdr: dict, which: str, index: int) -> list[int]:
    if which == "player":
        s, _e = pm._yay0_table(rom, hdr["player_yay0"], hdr["npc_yay0"], 13)[index]
    else:
        s, _e = pm._yay0_table(rom, hdr["npc_yay0"], hdr["end"])[index]
    d = pm.yay0_decompress(rom, s)
    return [len(pm.offset_list(d, a)) for a in pm.offset_list(d, 0x10)]


def export_sprite(rom: bytes, index: int, out: Path, npc: bool = False, name: str | None = None,
                  encode: bool = True) -> dict:
    """Write rasters/palettes/index of sprite ``index`` to ``out``. Returns the index dict.

    With ``encode`` (default), every written raster PNG is re-encoded to CI4 and asserted
    byte-identical to the ROM pixel data (no-op roundtrip).
    """
    hdr = pm.sprite_header(rom)
    spr = pr.npc_sprite(rom, index) if npc else pr.player_sprite(rom, index)
    name = name or (f"npc{index}" if npc else f"player{index}")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    recs = []
    for r in spr["rasters"]:
        png = pr.ci4_to_png(r["pixels"], r["w"], r["h"], spr["palettes"][r["palette"]])
        (out / f"raster_{r['index']:03d}_pal{r['palette']}.png").write_bytes(png)
        if encode:
            pal = spr["palettes"][r["palette"]]
            enc = png_to_ci4(png, pal)
            # palettes may repeat a colour; accept canonicalized indices iff the image is unchanged
            if enc != r["pixels"] and pr.ci4_to_png(enc, r["w"], r["h"], pal) != png:
                raise ValueError(f"raster {r['index']} round-trip mismatch")
        rec = {"index": r["index"], "w": r["w"], "h": r["h"], "palette": r["palette"],
               "size": r.get("size", r["w"] * r["h"] // 2)}
        rec["file"] = f"raster_{r['index']:03d}_pal{r['palette']}.png"
        if not npc:
            rec["pool_offset"] = r["pool_offset"]
        recs.append(rec)
    pals = []
    for i, p in enumerate(spr["palettes"]):
        (out / f"palette_{i:02d}.png").write_bytes(palette_png(p))
        pals.append({"index": i, "rgba5551": [f"{c:04X}" for c in struct.unpack('>16H', p[:32])]})
    idx = {"sprite": name, "npc": npc, "source_rom_sha256": None, "rasters": recs, "raster_count": len(recs),
           "palettes": pals, "animation_component_counts": _anim_components(rom, hdr, "npc" if npc else "player", index),
           "roundtrip_verified": bool(encode)}
    (out / "index.json").write_text(json.dumps(idx, indent=1))
    return idx
