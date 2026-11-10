"""Capcom Generations (Europe) (Disc 1) (PS1) - .DEE container format parser.

The .DEE files are custom LZ77-compressed sprite/texture containers found in
the 1942, 1943, 1943K, and MENU directories on the owned disc.  The LZ77
payload decompresses to a standard PSX TIM image (CLUT-indexed 4bpp/8bpp).

Header layout (12 bytes, little-endian u32 x3), verified on 53 owned files:
  +0x00 u32  raw_len    -- decompressed (TIM) length in bytes
  +0x04 u32  comp_len   -- compressed payload length (== file_size - 12)
  +0x08 u32  word       -- 0x00400001 (u16 version = 1, u16 token = 0x40)

The body (payload) at +0x0C is a byte-flag LZ77 stream; the first byte is a
flag byte (bit set = literal, clear = 2-byte match), NOT a "body marker".

Two files are not TIM payloads and are handled specially:
  * MENU_WARN2.DEE -- u32 header absent (raw_len=0x10, comp_len=9, word=0x20c)
      is an uncompressed/raw TIM (0x10 magic at offset 0).
  * MENU_S14.DEE / MENU_S14K.DEE -- non-TIM payloads (not standard containers).
"""

from __future__ import annotations

import hashlib
import struct

DEE_HEADER_SIZE = 12
DEE_MIN_SIZE = DEE_HEADER_SIZE

DEE_TRAILER_WORD = 0x00400001


def parse_dee(data: bytes) -> dict:
    """Parse a compressed .DEE container header (3 x u32).

    Returns the raw_len/comp_len/word fields plus a body summary: the
    compressed payload size and the source SHA-256.  Does not interpret the
    pixel payload; use dee_unpack + parse_tim for that.
    """
    if len(data) < DEE_MIN_SIZE:
        raise ValueError(
            "DEE file too small: %d bytes < %d" % (len(data), DEE_MIN_SIZE)
        )

    raw_len, comp_len, word = struct.unpack_from("<3I", data, 0)
    expected_payload = len(data) - DEE_HEADER_SIZE
    if comp_len != expected_payload:
        raise ValueError(
            "DEE comp_len mismatch: header says 0x%x (%d), file says 0x%x (%d)"
            % (comp_len, comp_len, expected_payload, expected_payload)
        )

    body_size = expected_payload
    return {
        "raw_len": raw_len,
        "comp_len": comp_len,
        "word": word,
        "version": word & 0xFFFF,
        "token": (word >> 16) & 0xFFFF,
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


def dee_unpack(data: bytes) -> bytes:
    """Decompress a DEE honoring its header (ignores sector padding after comp_len)."""
    h = dee_header(data)
    end = DEE_HEADER_SIZE + h["comp_len"]
    if end > len(data):
        raise ValueError("DEE truncated: header comp_len %d > data" % h["comp_len"])
    out = dee_decompress(data[:end], max_out=h["raw_len"])
    if len(out) != h["raw_len"]:
        raise ValueError("DEE raw_len mismatch: %d != %d" % (len(out), h["raw_len"]))
    return out


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
    meta["dee"] = {k: hdr[k] for k in ("raw_len", "comp_len", "word", "version", "token")}
    return png, meta


# ---------------------------------------------------------------------------
# Writer side: recompressor + container packer (no-op roundtrip foundation)
#
# Corrected 12-byte header (little-endian u32 x3), verified on 50 owned files:
#   +0x00 u32  decompressed (TIM) length
#   +0x04 u32  compressed payload length (== file_size - 12)
#   +0x08 u32  0x00400001 (u16 version=1, u16 token=0x40)
# ---------------------------------------------------------------------------

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
