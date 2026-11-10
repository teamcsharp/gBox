"""Viewtiful Joe 2 (GameCube, USA) .dusgc "runlength comp." reader (analysis stage).

Derived from main.dol function 0x801de668 (xref to string "runlength comp." @0x802c6adc):
  chunk  = 0x20-byte header (16B name "runlength comp.", BE u32 total size @+0x10, u32 flag @+0x1c; flag!=0
           resets the running output counter) followed by a control stream at +0x20:
           c==0x80 end; c&0x80 -> literal (c&0x7f) bytes; else run of c copies of the next byte.
  Chunks sit on 0x80000 strides starting at file offset 0x800; concatenated output of the chunks equals the
  BE u32 total size (pl00: 3 chunks -> 0x155d00).  The output begins with a table: u32 count, 3 words, then
  (offset,size) pairs that tile the output contiguously.
"""
import struct

MAGIC = b"runlength comp."
STRIDE = 0x80000


def rle_chunk(buf, off):
    """Decode one chunk. Returns (decoded bytes, declared_total, flag, end_offset)."""
    if buf[off:off + len(MAGIC)] != MAGIC:
        raise ValueError("no runlength chunk at 0x%x" % off)
    total, = struct.unpack_from(">I", buf, off + 0x10)
    flag, = struct.unpack_from(">I", buf, off + 0x1c)
    p = off + 0x20
    out = bytearray()
    while True:
        c = buf[p]
        p += 1
        if c == 0x80:
            break
        n = c & 0x7f
        if c & 0x80:
            out += buf[p:p + n]
            p += n
        else:
            out += bytes([buf[p]]) * n
            p += 1
    return bytes(out), total, flag, p


def decode_dusgc(buf, start=0x800):
    """Decode all leading chunks (stride 0x80000) until the declared total is reached."""
    off, parts, got, total = start, [], 0, None
    while off + len(MAGIC) <= len(buf) and buf[off:off + len(MAGIC)] == MAGIC:
        o, total, _f, _e = rle_chunk(buf, off)
        parts.append(o)
        got += len(o)
        off += STRIDE
        if got >= total:
            break
    data = b"".join(parts)
    if total is None or len(data) != total:
        raise ValueError("decoded %d != declared %s" % (len(data), total))
    return data, len(parts)


def toc(data):
    """Parse the (offset,size) table at the start of decoded data."""
    count, = struct.unpack_from(">I", data, 0)
    words = struct.unpack_from(">%dI" % (2 * count), data, 16)
    return [(words[2 * i], words[2 * i + 1]) for i in range(count)]
