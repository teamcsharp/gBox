"""Sonic & Knuckles (World): native player-sprite frame renderer and writer-room survey (#1365).

Builds on :mod:`gbox.sk_sprites` (PR #113), which derives each player's DPLC,
mapping, art and palette tables from the 68k code itself.  This module decodes
one player frame end-to-end -- uncompressed 4bpp art tiles + the frame's DPLC
stream + its mapping pieces + the 16-colour palette line -- into an RGBA sprite
(optionally a PNG), and measures the room a native writer has for each player
slot (128 KiB DMA art banks, the packed Map/PLC block, the free ROM tail).

The tile/mapping formats are pinned byte-for-byte against the skdisasm sources
for this build (``Map - Sonic.asm``, ``DPLC - Sonic.asm``): a mapping piece is
``s8 y, u8 ((w-1)<<2 | (h-1)), u16 (pri<<15 | pal<<13 | vf<<12 | hf<<11 | tile),
s16 x`` and a DPLC entry is ``u16 ((tiles-1)<<12 | first_tile)``.  A piece's
``tile`` indexes the *frame's* DPLC stream (contiguous ``w*h`` tiles in column
major order), not the art bank directly.

CLI: ``python -m gbox.sk_render SRC [--char sonic|knuckles] [--frame N] [--png out.png] [--sheet out.png]``
"""
from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

from gbox.sk_sprites import SkError, inventory, parse_dplc, parse_mappings, read_rom

BANK = 0x20000  # 128 KiB: the DMA-queue granularity an art run must not cross


def crgb(word: int) -> tuple[int, int, int]:
    """Genesis CRAM word (0000BBB0GGG0RRR0) -> 24-bit (r, g, b)."""
    r = (word >> 1) & 7
    g = (word >> 5) & 7
    b = (word >> 9) & 7
    return ((r << 5) | (r << 2) | (r >> 1),
            (g << 5) | (g << 2) | (g >> 1),
            (b << 5) | (b << 2) | (b >> 1))


def decode_palette(d: bytes, off: int, n: int = 16) -> list[tuple[int, int, int]]:
    words = struct.unpack_from(f">{n}H", d, off)
    return [crgb(w) for w in words]


def decode_tile(blob: bytes) -> bytes:
    """One 32-byte 4bpp tile -> 64 palette indices, row-major (nibble hi = left pixel)."""
    if len(blob) < 32:
        raise SkError(f"tile is {len(blob)} bytes, need 32")
    out = bytearray(64)
    for row in range(8):
        base = row * 4
        for px in range(4):
            b = blob[base + px]
            out[row * 8 + px * 2] = b >> 4
            out[row * 8 + px * 2 + 1] = b & 0xF
    return bytes(out)


def dplc_stream(ents: list[tuple[int, int]]) -> list[int]:
    """Expand ``[(first_tile, count), ...]`` into the ordered art-tile indices."""
    out: list[int] = []
    for first, n in ents:
        out.extend(range(first, first + n))
    return out


def render_frame(d: bytes, art: int, dplc_ents: list[tuple[int, int]],
                 pieces: list[dict], palette: list[tuple[int, int, int]]) -> dict:
    """Composite one frame into a tightly bounded RGBA sprite.  Colour 0 is transparent."""
    stream = dplc_stream(dplc_ents)
    placed = []
    for pc in pieces:
        for ty in range(pc["h"]):
            for tx in range(pc["w"]):
                sx = pc["w"] - 1 - tx if pc["hf"] else tx
                sy = pc["h"] - 1 - ty if pc["vf"] else ty
                k = pc["tile"] + sx * pc["h"] + sy
                placed.append((pc["x"] + tx * 8, pc["y"] + ty * 8, k, pc["hf"], pc["vf"]))
    if not placed:
        return {"rgba": b"", "w": 0, "h": 0, "bounds": None, "tiles": 0, "opaque": 0}
    minx = min(p[0] for p in placed)
    maxx = max(p[0] for p in placed) + 8
    miny = min(p[1] for p in placed)
    maxy = max(p[1] for p in placed) + 8
    w = maxx - minx
    h = maxy - miny
    canvas = bytearray(w * h * 4)
    opaque = 0
    for px, py, k, hf, vf in placed:
        if not 0 <= k < len(stream):
            raise SkError(f"mapping tile {k} beyond a {len(stream)}-tile DPLC stream")
        idx = stream[k]
        px8 = decode_tile(d[art + 32 * idx: art + 32 * idx + 32])
        for row in range(8):
            src_row = (7 - row) if vf else row
            for col in range(8):
                ci = px8[src_row * 8 + ((7 - col) if hf else col)]
                if ci == 0:
                    continue
                r, g, b = palette[ci]
                ox = px - minx + col
                oy = py - miny + row
                o = (oy * w + ox) * 4
                canvas[o:o + 3] = bytes((r, g, b))
                canvas[o + 3] = 255
                opaque += 1
    return {"rgba": bytes(canvas), "w": w, "h": h, "bounds": [minx, miny, maxx, maxy],
            "tiles": len(placed), "opaque": opaque}


def _char_dplc(d: bytes, c: dict, n: int) -> list[list[tuple[int, int]]]:
    alts = c.get("alt_plc", [])
    stop = min((a["offset"] for a in alts if a["offset"] > c["plc"]["offset"]), default=None)
    return parse_dplc(d, c["plc"]["offset"], stop, n)


def render_character(d: bytes, inv: dict, name: str = "sonic", frame: int = 1) -> dict:
    c = inv["characters"][name]
    if c.get("status") != "in_cart":
        raise SkError(f"{name} is not in-cart (status {c.get('status')})")
    n = c["plc"]["frames"]
    dplc = _char_dplc(d, c, n)
    maps = parse_mappings(d, c["mappings"]["offset"], n)
    if not (0 <= frame < n):
        raise SkError(f"frame {frame} out of range 0..{n - 1}")
    x = c.get("extra_art")
    split = x["from_frame"] if x else n
    art = x["offset"] if x and frame >= split else c["art"]["offset"]
    palette = decode_palette(d, c["palette"]["offset"])
    r = render_frame(d, art, dplc[frame], maps[frame], palette)
    r.update({"char": name, "frame": frame, "art_base": art})
    return r


def png_bytes(rgba: bytes, w: int, h: int) -> bytes:
    """Minimal lossless RGBA PNG (stdlib zlib; no PIL dependency)."""

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    if w <= 0 or h <= 0 or len(rgba) != w * h * 4:
        raise SkError("PNG dimensions must be positive and match the RGBA buffer")
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter None
        raw += rgba[y * w * 4:(y + 1) * w * 4]
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def _last_used(d: bytes) -> dict:
    """Highest non-0xFF offset: Genesis ROMs pad unused space with 0xFF."""
    end = len(d)
    last = 0
    for i in range(end - 1, -1, -1):
        if d[i] != 0xFF:
            last = i
            break
    return {"last_data": last, "free_tail": end - last - 1, "rom_size": end}


def writer_room(d: bytes, inv: dict) -> dict:
    """Measure the room a native re-import has for each in-cart player slot."""
    chars = inv["characters"]
    banks = {}
    for name, c in chars.items():
        if c.get("status") != "in_cart":
            continue
        art = c["art"]
        base, tiles, size = art["offset"], art["tiles"], art["size"]
        bank = (base >> 17) << 17
        bank_end = bank + BANK
        rec = {"base": base, "dplc_tiles": tiles, "dplc_bytes": size,
               "bank": bank, "bank_end": bank_end,
               "room_to_bank_end": bank_end - base - size,
               "room_tiles_to_bank_end": (bank_end - base - size) // 32,
               "max_tiles_in_bank": (bank_end - base) // 32}
        x = c.get("extra_art")
        if x:
            xb = (x["offset"] >> 17) << 17
            rec["extra_art"] = {"base": x["offset"], "tiles": x["tiles"], "size": x["size"],
                                "from_frame": x["from_frame"], "bank": xb, "bank_end": xb + BANK}
        banks[name] = rec
    tbls = []
    for name, c in chars.items():
        for k in ("mappings", "plc"):
            if k in c and "offset" in c[k]:
                tbls.append((name, k, c[k]["offset"], c[k]["offset"] + c[k]["size"]))
        for a in c.get("alt_plc", []):
            if "offset" in a and "size" in a:
                tbls.append((name, "alt_plc", a["offset"], a["offset"] + a["size"]))
    tbls.sort(key=lambda t: t[2])
    return {"art_banks": banks,
            "tables": {"block": [tbls[0][2], max(t[3] for t in tbls)],
                       "entries": [{"char": a, "table": b, "start": c, "end": d_} for a, b, c, d_ in tbls]},
            "tail": _last_used(d)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="S&K (World) player-sprite render + writer-room survey")
    ap.add_argument("src")
    ap.add_argument("--char", default="sonic")
    ap.add_argument("--frame", type=int, default=1)
    ap.add_argument("--png", help="write the single rendered frame to this PNG")
    ap.add_argument("--sheet", help="write a contact sheet of frames 1..N (N=--frame)")
    ap.add_argument("--room", action="store_true", help="print the writer-room survey")
    a = ap.parse_args(argv)
    p = Path(a.src)
    d, _ = read_rom(p)
    inv = inventory(a.src)
    if a.room:
        import json
        print(json.dumps(writer_room(d, inv), indent=1, default=lambda v: hex(v) if isinstance(v, int) else v))
        return 0
    if a.sheet:
        from collections import defaultdict
        n = a.frame
        frames = [render_character(d, inv, a.char, f) for f in range(1, n + 1)]
        col = max(f["w"] for f in frames)
        row = max(f["h"] for f in frames)
        pad = 4
        cols = 8
        rows = (len(frames) + cols - 1) // cols
        W = cols * (col + pad) + pad
        H = rows * (row + pad) + pad
        sheet = bytearray(W * H * 4)
        for i, f in enumerate(frames):
            ox = pad + (i % cols) * (col + pad) + (col - f["w"]) // 2
            oy = pad + (i // cols) * (row + pad) + (row - f["h"]) // 2
            for y in range(f["h"]):
                src = y * f["w"] * 4
                dst = (oy + y) * W * 4 + ox * 4
                sheet[dst:dst + f["w"] * 4] = f["rgba"][src:src + f["w"] * 4]
        Path(a.sheet).write_bytes(png_bytes(bytes(sheet), W, H))
        print(f"wrote {a.sheet} ({len(frames)} frames)")
        return 0
    r = render_character(d, inv, a.char, a.frame)
    print(f"{a.char} frame {a.frame}: {r['w']}x{r['h']} bounds={r['bounds']} "
          f"tiles={r['tiles']} opaque={r['opaque']} art=0x{r['art_base']:x}")
    if a.png:
        Path(a.png).write_bytes(png_bytes(r["rgba"], r["w"], r["h"]))
        print(f"wrote {a.png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
