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
