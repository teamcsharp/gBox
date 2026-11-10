"""Capcom Generations (Europe) (Disc 1) (PS1) - .DEE container format parser.

The .DEE files are custom sprite/texture containers found in the 1942, 1943,
1943K, and MENU directories on the owned disc.  They are NOT PS1 TIM1/TIM2.

Header layout (12 bytes, little-endian u16 pairs):
  +0x00  type_tag     -- varies by asset type (0x2220 char sprites, 0x1d20 cards,
                         0x0220 scroll/obj, 0x6a20 menu, 0x5040 font, etc.)
  +0x02  sub_type     -- 0x0000 or 0x0001/0x0002
  +0x04  payload_len  -- == file_size - 12 (verified for all 12 dumped files)
  +0x06  reserved     -- always 0x0000
  +0x08  flag         -- 0x0001 in all observed files
  +0x0A  block_token  -- 0x0040 (most), 0x0090 (CARD/menu), 0x0200 (43LDG)

Body starts at 0x0C:
  +0x0C  body_marker  -- 0x106b (9 files) or 0x102b (42CHAR7, FONT16, GENR)
  +0x0E  pad          -- 0x0000
  +0x10  block_count  -- 0x0800 (most), 0x0900 (CARD/menu), 0x0200 (43LDG)
  +0x12  field_count  -- 0x0031 (49) in all observed files

The body after the 16-byte header block contains sprite geometry descriptors
and/or 4bpp pixel data with a palette.  The exact sub-layout requires Ghidra
analysis of the loader in SLES_018.81 to confirm.
"""

from __future__ import annotations

import hashlib
import struct

DEE_HEADER_SIZE = 12
DEE_BODY_HEADER_SIZE = 16  # body_marker, pad, block_count, field_count (4 x u16)
DEE_MIN_SIZE = DEE_HEADER_SIZE + DEE_BODY_HEADER_SIZE  # 28

KNOWN_TYPE_TAGS = {
    0x2220: "char_sprites",
    0x2040: "char_sprites_1942",
    0x1d20: "cards",
    0x0220: "scroll_obj",
    0x6a20: "menu",
    0x5040: "font",
    0x1840: "menu_genr",
    0x5814: "loading",
}

KNOWN_BODY_MARKERS = {
    0x106b: "standard",
    0x102b: "compact",
}


def parse_dee(data: bytes) -> dict:
    """Parse a .DEE container header.

    Returns a dict with header fields and body summary.  Does not interpret
    the pixel/geometry payload (that requires Ghidra loader analysis).
    """
    if len(data) < DEE_MIN_SIZE:
        raise ValueError(
            "DEE file too small: %d bytes < %d" % (len(data), DEE_MIN_SIZE)
        )

    type_tag, sub_type, payload_len, reserved, flag, block_token = (
        struct.unpack_from("<6H", data, 0)
    )

    # Verify payload_len == file_size - 12
    expected_payload = len(data) - DEE_HEADER_SIZE
    if payload_len != expected_payload:
        raise ValueError(
            "DEE payload_len mismatch: header says 0x%x (%d), file says 0x%x (%d)"
            % (payload_len, payload_len, expected_payload, expected_payload)
        )

    if reserved != 0:
        raise ValueError("DEE reserved field @0x06 is nonzero: 0x%04x" % reserved)

    body_marker, pad, block_count, field_count = struct.unpack_from(
        "<4H", data, DEE_HEADER_SIZE
    )

    if pad != 0:
        raise ValueError("DEE body pad @0x0E is nonzero: 0x%04x" % pad)

    body_size = len(data) - DEE_HEADER_SIZE - DEE_BODY_HEADER_SIZE
    if body_size < 0:
        raise ValueError("DEE body size negative: %d" % body_size)

    type_name = KNOWN_TYPE_TAGS.get(type_tag, "unknown")
    body_variant = KNOWN_BODY_MARKERS.get(body_marker, "unknown")

    return {
        "type_tag": type_tag,
        "type_name": type_name,
        "sub_type": sub_type,
        "payload_len": payload_len,
        "flag": flag,
        "block_token": block_token,
        "body_marker": body_marker,
        "body_variant": body_variant,
        "block_count": block_count,
        "field_count": field_count,
        "body_size": body_size,
        "total_size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def parse_dee_file(path: str) -> dict:
    """Parse a .DEE file from disk."""
    with open(path, "rb") as f:
        data = f.read()
    result = parse_dee(data)
    result["path"] = path
    return result


def list_dee_files(paths: list) -> list:
    """Parse multiple .DEE files and return a list of header dicts."""
    out = []
    for p in paths:
        out.append(parse_dee_file(p))
    return out


# ---------------------------------------------------------------------------
# Body codec (verified 51/51 against the owned CHD's compressed .DEE files):
# the body at 0x0C is a byte-flag LZ77 stream whose output is a standard PSX
# TIM. (The "body marker" u16 at 0x0C is really flag byte 0 + first literal.)
#   flag byte, consumed LSB first: 1 = literal byte, 0 = 2-byte match
#   match word w = b1 | b2 << 8 : length = (w & 0xF) + 2, distance = (w >> 4) + 1
#   (distance is relative to the output tail; overlapping copies allowed)
# ---------------------------------------------------------------------------


def dee_decompress(data: bytes, start: int = DEE_HEADER_SIZE, max_out: int = 1 << 24) -> bytes:
    out = bytearray()
    p, n = start, len(data)
    while p < n and len(out) < max_out:
        flags = data[p]
        p += 1
        for _ in range(8):
            if p >= n:
                break
            if flags & 1:
                out.append(data[p])
                p += 1
            else:
                if p + 1 >= n:
                    break
                w = data[p] | (data[p + 1] << 8)
                p += 2
                length, dist = (w & 0xF) + 2, (w >> 4) + 1
                if dist > len(out):
                    raise ValueError("DEE match distance %d beyond output (%d)" % (dist, len(out)))
                for _ in range(length):
                    out.append(out[-dist])
            flags >>= 1
    return bytes(out)


def parse_tim(tim: bytes) -> dict:
    """Parse a PSX TIM header; raises ValueError unless blocks tile the buffer exactly."""
    if len(tim) < 20 or tim[:4] != b"\x10\x00\x00\x00":
        raise ValueError("not a TIM")
    flag = struct.unpack_from("<I", tim, 4)[0]
    off, info = 8, {"flag": flag, "bpp": {0: 4, 1: 8, 2: 16, 3: 24}[flag & 3]}
    if flag & 8:
        size, x, y, w, h = struct.unpack_from("<I4H", tim, off)
        info["clut"] = {"size": size, "x": x, "y": y, "w": w, "h": h}
        off += size
    size, x, y, w, h = struct.unpack_from("<I4H", tim, off)
    info["image"] = {"size": size, "x": x, "y": y, "w": w, "h": h}
    off += size
    if off != len(tim):
        raise ValueError("TIM blocks end at %d, buffer is %d" % (off, len(tim)))
    return info


def decode_dee_tim(data: bytes) -> tuple:
    """Return (tim_bytes, tim_info) for a compressed DEE file."""
    tim = dee_decompress(data)
    return tim, parse_tim(tim)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    import zlib
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def _clut_color(value: int) -> tuple:
    """Decode a PSX 16-bit CLUT entry to RGBA.

    The entry is 5:5:5 STP/X:B:G:R (bit 15 = semi-transparency / transparent
    select bit, bit 0 is the LSB of red).  We keep the STP bit as an opaque
    channel only when clear; STP=1 marks the pixel transparent (alpha 0).
    """
    stp = (value >> 15) & 1
    r = (value & 0x1F) << 3
    g = ((value >> 5) & 0x1F) << 3
    b = ((value >> 10) & 0x1F) << 3
    return (r, g, b, 0 if stp else 255)


def tim_to_png(tim: bytes) -> tuple:
    """Decode a PSX TIM to an RGBA PNG, honoring CLUT STP transparency.

    Supports 4bpp (CLUT-indexed, 2 pixels/byte, low nibble = left pixel) and
    8bpp (CLUT-indexed).  16/24bpp direct-color TIMs are not produced by any
    observed Capcom Generations .DEE asset, so they raise ValueError.

    Returns (png_bytes, meta) where meta carries the image/clut dimensions and
    the decoded CLUT entry count.  This is the editable-artefact export path
    (DEE -> LZ77 -> TIM -> PNG) for character replacement.
    """
    if len(tim) < 8 or tim[:4] != b"\x10\x00\x00\x00":
        raise ValueError("not a TIM")
    flag = struct.unpack_from("<I", tim, 4)[0]
    bpp = flag & 3
    off = 8
    clut: list = []
    clut_meta = None
    if flag & 8:
        csize, cx, cy, cw, ch = struct.unpack_from("<I4H", tim, off)
        ncolors = (csize - 12) // 2
        clut = [_clut_color(v) for v in struct.unpack_from("<%dH" % ncolors, tim, off + 12)]
        clut_meta = {"x": cx, "y": cy, "w": cw, "h": ch, "count": ncolors}
        off += csize
    isize, ix, iy, iw, ih = struct.unpack_from("<I4H", tim, off)
    pix = tim[off + 12: off + isize]

    if bpp == 0:  # 4bpp: two pixels per byte, low nibble first (left)
        indices = []
        for y in range(ih):
            row_start = y * (iw // 2)
            for x in range(iw):
                byte = pix[row_start + x // 2]
                indices.append(byte & 0xF if x % 2 == 0 else (byte >> 4) & 0xF)
    elif bpp == 1:  # 8bpp
        indices = list(pix[:iw * ih])
    else:
        raise ValueError("TIM bpp %d (16/24-bit direct color) is unsupported" % bpp)

    raw = bytearray(iw * ih * 4)
    for i, idx in enumerate(indices):
        r, g, b, a = clut[idx] if idx < len(clut) else (0, 0, 0, 0)
        raw[i * 4:i * 4 + 4] = bytes((r, g, b, a))

    idat = bytearray()
    stride = iw * 4
    for y in range(ih):
        idat += b"\x00" + bytes(raw[y * stride:(y + 1) * stride])
    import zlib
    png = (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", iw, ih, 8, 6, 0, 0, 0))
           + _png_chunk(b"IDAT", zlib.compress(bytes(idat), 9))
           + _png_chunk(b"IEND", b""))
    meta = {"image": {"x": ix, "y": iy, "w": iw, "h": ih},
            "bpp": {0: 4, 1: 8, 2: 16, 3: 24}[bpp],
            "clut": clut_meta}
    return png, meta


def dee_to_png(data: bytes) -> tuple:
    """Full path: decompress a .DEE body and render the TIM to a PNG.

    Returns (png_bytes, meta) where meta also carries the DEE header summary
    so the exporter can record source identity end-to-end.
    """
    hdr = parse_dee(data)
    tim = dee_decompress(data)
    png, meta = tim_to_png(tim)
    meta["tim"] = parse_tim(tim)
    meta["dee"] = {k: hdr[k] for k in ("type_tag", "type_name", "body_marker", "block_token")}
    return png, meta


# ---------------------------------------------------------------------------
# Writer side: recompressor + container packer (no-op roundtrip foundation)
#
# Corrected 12-byte header (little-endian u32 x3), verified on 50 owned files:
#   +0x00 u32  decompressed (TIM) length
#   +0x04 u32  compressed payload length (== file_size - 12)
#   +0x08 u32  0x00400001 (u16 version=1, u16 token=0x40)
# ---------------------------------------------------------------------------

DEE_TRAILER_WORD = 0x00400001
_MAX_MATCH, _MIN_MATCH, _MAX_DIST = 17, 3, 4096


def dee_header(data: bytes) -> dict:
    """Decode the u32 header of a compressed DEE file."""
    if len(data) < DEE_HEADER_SIZE:
        raise ValueError("DEE too small")
    raw_len, comp_len, word = struct.unpack_from("<3I", data, 0)
    return {"raw_len": raw_len, "comp_len": comp_len, "word": word}


def dee_compress(raw: bytes, max_chain: int = 64) -> bytes:
    """Greedy LZ77 encoder for the DEE stream (inverse of dee_decompress)."""
    out = bytearray()
    n = len(raw)
    heads: dict = {}
    i = 0
    group = []  # up to 8 items: ("L", byte) / ("M", word)

    def flush():
        flags = 0
        body = bytearray()
        for k, (kind, v) in enumerate(group):
            if kind == "L":
                flags |= 1 << k
                body.append(v)
            else:
                body += struct.pack("<H", v)
        out.append(flags)
        out.extend(body)
        group.clear()

    def index(pos):
        if pos + 3 <= n:
            heads.setdefault(raw[pos:pos + 3], []).append(pos)

    while i < n:
        best_len = best_dist = 0
        if i + _MIN_MATCH <= n:
            cands = heads.get(raw[i:i + 3], ())
            for c in reversed(cands[-max_chain:]):
                dist = i - c
                if dist > _MAX_DIST:
                    break
                length = 0
                lim = min(_MAX_MATCH, n - i)
                while length < lim and raw[c + length] == raw[i + length]:
                    length += 1
                if length > best_len:
                    best_len, best_dist = length, dist
                    if length == lim:
                        break
        if best_len >= _MIN_MATCH:
            group.append(("M", (best_dist - 1) << 4 | (best_len - 2)))
            for k in range(best_len):
                index(i + k)
            i += best_len
        else:
            group.append(("L", raw[i]))
            index(i)
            i += 1
        if len(group) == 8:
            flush()
    if group:
        flush()
    return bytes(out)


def dee_pack(raw: bytes) -> bytes:
    """Compress raw (TIM) bytes into a complete .DEE file."""
    comp = dee_compress(raw)
    return struct.pack("<3I", len(raw), len(comp), DEE_TRAILER_WORD) + comp


def tim_replace_image(tim: bytes, pixels: bytes) -> bytes:
    """Return a TIM with the image-block pixel bytes replaced (same size)."""
    info = parse_tim(tim)
    off = 8 + (info["clut"]["size"] if "clut" in info else 0)
    size = info["image"]["size"]
    if len(pixels) != size - 12:
        raise ValueError("pixel data %d != image block %d" % (len(pixels), size - 12))
    return tim[:off + 12] + bytes(pixels) + tim[off + size:]
