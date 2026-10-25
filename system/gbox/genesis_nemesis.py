"""Nemesis (Sega Genesis) art codec in pure Python.

Format (verified against Clownacy's clownnemesis output on the owned
Sonic 1 and 2 ROM):

* Header word (big-endian): bit 15 = XOR mode, bits 0-14 = tile count.
* Code table: bytes until 0xFF. A byte with bit 7 set selects the current
  palette nybble (low 4 bits). Any other byte is ``0RRR CCCC``: run length
  RRR+1 and code length CCCC; the next byte is the code value (right-aligned).
* Bit stream (MSB first): a code maps to (nybble, run). The 6-bit code
  ``111111`` is the *inline* escape: the next 7 bits are ``RRR NNNN``
  (run-1, nybble).
* Decoded nybbles fill 32-bit rows, 8 rows per tile. In XOR mode each row is
  XORed with the previous output row (initially 0).
"""
from __future__ import annotations

import io
import struct

__all__ = ["NemesisError", "decode", "decode_with_size", "encode",
           "tiles_to_png_bytes"]


class NemesisError(Exception):
    pass


def _parse_table(data: bytes, pos: int) -> tuple[dict, int]:
    table: dict[tuple[int, int], tuple[int, int]] = {}
    nyb = None
    while True:
        if pos >= len(data):
            raise NemesisError("truncated code table")
        b = data[pos]
        pos += 1
        if b == 0xFF:
            return table, pos
        if b & 0x80:
            nyb = b & 0x0F
            if pos >= len(data):
                raise NemesisError("truncated code table")
            b = data[pos]
            pos += 1
        if nyb is None:
            raise NemesisError("code entry before palette index")
        run = ((b >> 4) & 7) + 1
        length = b & 0x0F
        if pos >= len(data):
            raise NemesisError("truncated code table")
        code = data[pos]
        pos += 1
        if length == 0 or length > 8 or code >> length:
            raise NemesisError("bad code entry")
        table[(length, code)] = (nyb, run)


def decode_with_size(data: bytes) -> tuple[bytes, int]:
    """Decode a stream; returns (tile bytes, bytes consumed)."""
    if len(data) < 3:
        raise NemesisError("stream too short")
    header = struct.unpack_from(">H", data, 0)[0]
    xor_mode = bool(header & 0x8000)
    tiles = header & 0x7FFF
    if tiles == 0:
        raise NemesisError("zero tile count")
    table, pos = _parse_table(data, 2)
    total = tiles * 64  # nybbles
    nybbles = bytearray()
    bitpos = pos * 8
    limit = len(data) * 8

    def getbit() -> int:
        nonlocal bitpos
        if bitpos >= limit:
            raise NemesisError("bitstream exhausted")
        bit = (data[bitpos >> 3] >> (7 - (bitpos & 7))) & 1
        bitpos += 1
        return bit

    while len(nybbles) < total:
        acc = 0
        nbits = 0
        while True:
            acc = (acc << 1) | getbit()
            nbits += 1
            if nbits == 6 and acc == 0x3F:
                v = 0
                for _ in range(7):
                    v = (v << 1) | getbit()
                nyb, run = v & 0x0F, ((v >> 4) & 7) + 1
                break
            hit = table.get((nbits, acc))
            if hit:
                nyb, run = hit
                break
            if nbits >= 8:
                raise NemesisError("invalid code in bitstream")
        nybbles.extend([nyb] * run)
    if len(nybbles) != total:
        raise NemesisError("run overflows tile data")
    rows = []
    prev = 0
    for i in range(0, total, 8):
        row = 0
        for n in nybbles[i:i + 8]:
            row = (row << 4) | n
        if xor_mode:
            row ^= prev
            prev = row
        rows.append(row)
    return b"".join(r.to_bytes(4, "big") for r in rows), (bitpos + 7) // 8


def decode(data: bytes) -> bytes:
    return decode_with_size(data)[0]


def encode(tiles: bytes, xor_mode: bool = True) -> bytes:
    """Encode 4bpp tiles using inline-only codes (valid, not size-optimal).

    Empty code table; every run is a ``111111`` escape + 7 bits.
    """
    if not tiles or len(tiles) % 32:
        raise NemesisError("tile data must be a positive multiple of 32 bytes")
    count = len(tiles) // 32
    if count > 0x7FFF:
        raise NemesisError("too many tiles")
    rows = [int.from_bytes(tiles[i:i + 4], "big") for i in range(0, len(tiles), 4)]
    if xor_mode:
        rows = [rows[0]] + [rows[i] ^ rows[i - 1] for i in range(1, len(rows))]
    nyb = [(r >> (28 - 4 * k)) & 0xF for r in rows for k in range(8)]
    bits = []
    i = 0
    while i < len(nyb):
        run = 1
        while run < 8 and i + run < len(nyb) and nyb[i + run] == nyb[i]:
            run += 1
        bits.append(format((0x3F << 7) | ((run - 1) << 4) | nyb[i], "013b"))
        i += run
    s = "".join(bits)
    s += "0" * (-len(s) % 8)
    payload = int(s, 2).to_bytes(len(s) // 8, "big")
    return struct.pack(">H", (0x8000 if xor_mode else 0) | count) + b"\xff" + payload


def tiles_to_png_bytes(tiles: bytes, cols: int = 8, palette: list | None = None) -> bytes:
    """Render 4bpp tiles to a PNG tile sheet (greyscale default, index 0 transparent)."""
    from PIL import Image
    n = len(tiles) // 32
    rows = (n + cols - 1) // cols
    pal = palette or [(0, 0, 0, 0)] + [(i * 17, i * 17, i * 17, 255) for i in range(1, 16)]
    img = Image.new("RGBA", (cols * 8, rows * 8), (0, 0, 0, 0))
    px = img.load()
    for t in range(n):
        for y in range(8):
            for x in range(8):
                b = tiles[t * 32 + y * 4 + x // 2]
                px[(t % cols) * 8 + x, (t // cols) * 8 + y] = pal[(b >> 4) if x % 2 == 0 else (b & 15)]
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()
