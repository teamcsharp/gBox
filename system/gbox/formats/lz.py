"""LZ-family codecs shared by every title reader (one implementation per codec; title modules import from here).

  Sega PRS (LSB-first control bits)      prs_decompress / prs_compress        Ninja titles: PSO, SA1/SA2, JGR, ...
  Eighting PRS (MSB-first control bits)  prs_msb_decompress                   Bleach GC/Wii fpack (con2, cnr2)
  MIO0 (Nintendo)                        mio0_decompress / mio0_compress      SM64, SF64, MK64, Warzone
  Yaz0 (Nintendo)                        yaz0_decompress / yaz0_compress      OoT, MM
  LZSS (Okumura, 4 KiB ring at 0xFEE)    lzss_decompress / lzss_compress      Mega Man 64, FF7 LZS, AKI wrestling
  LZ10 (Nintendo DS/GBA type 0x10)       lz10_decompress                      Tetris DS
  VPK0 (Nintendo, Huffman LZ)            vpk0_decode                          Smash Bros 64
  RNC ProPack 1/2                        gbox.formats.rnc.decode_rnc          Turok 1/2
  RefPack / QFS (EA)                     refpack_decompress (gbox.refpack)    WCW Mayhem (EA titles)
  zlib / raw deflate / gzip              inflate                              RE2 N64, UE3 packages, GCZ blocks

Each moved function is the title module's original code, unchanged; the title modules re-import it under the same
name, so callers and tests see no difference. New encoders exist so tests can round-trip synthetic data.
"""
from __future__ import annotations

import struct
import zlib
from typing import Any


# ---------------------------------------------------------------- facades over codecs that live in their own module


def refpack_decompress(b: bytes) -> bytes:
    from .. import refpack
    return refpack.decompress(b)


def is_refpack(b: bytes) -> bool:
    from .. import refpack
    return refpack.is_refpack(b)


def decode_rnc(blob: bytes) -> bytes:
    from .rnc import decode_rnc as dec
    return dec(blob)


def inflate(data: bytes, limit: int | None = None) -> bytes:
    """zlib, gzip or raw deflate, detected from the first bytes (zlib header 0x78, gzip 1F 8B, else raw)."""
    if data[:2] == b"\x1f\x8b":
        wbits = 31
    elif len(data) >= 2 and data[0] & 0x0F == 8 and (data[0] << 8 | data[1]) % 31 == 0:
        wbits = 15
    else:
        wbits = -15
    d = zlib.decompressobj(wbits)
    out = d.decompress(data, limit or 0)
    return out if limit else out + d.flush()


# ---------------------------------------------------------------- Eighting PRS (MSB-first; Bleach GC/Wii fpack)


def prs_msb_decompress(data: bytes, size: int, *, strict: bool = True, zero_window: bool = True) -> bytes:
    """Decode an Eighting PRS stream to exactly `size` bytes (MSB-first flag bits: 1 = literal; 00 = short copy, 2
    length bits + 8-bit back-offset; 01 = long copy, 13-bit back-offset with the length in the low 3 bits or a following
    byte). The encoder's window starts zero-filled: references before the start read 0. Port of GNTool
    PRSUncompressor (tpu / Luigi Auriemma QuickBMS spec). strict: the stream must produce exactly `size` bytes.
    zero_window=False keeps gbox.cnr2's original reading of such references (Python negative indexing into the
    output buffer); valid streams decode identically either way."""
    out = bytearray(size)
    i = bits = o = flag = 0
    n = len(data)

    def bit() -> int:
        nonlocal i, bits, flag
        if bits == 0:
            if i >= n:
                raise ValueError("truncated PRS stream")
            flag = data[i]
            i += 1
            bits = 8
        b = (flag >> 7) & 1
        flag = (flag << 1) & 0xFF
        bits -= 1
        return b

    def byte() -> int:
        nonlocal i
        if i >= n:
            raise ValueError("truncated PRS stream")
        i += 1
        return data[i - 1]

    while i < n:
        if bit():
            v = byte()
            if o < size:
                out[o] = v
                o += 1
            continue
        if bit() == 0:
            length = ((bit() << 1) | bit()) + 2
            pos = byte() - 0x100
        else:
            w = (byte() << 8) | byte()
            length = w & 7
            pos = (w >> 3) - 0x2000
            length = byte() + 1 if length == 0 else length + 2
        pos += o
        for _ in range(length):
            if o < size:
                out[o] = out[pos] if pos >= 0 or not zero_window else 0
                o += 1
                pos += 1
    if strict and o != size:
        raise ValueError(f"PRS stream produced {o} of {size} bytes")
    return bytes(out)


def prs_msb_compress(data: bytes) -> bytes:
    """Greedy Eighting PRS encoder (literals + short/long copies); prs_msb_decompress inverts it."""
    out = bytearray()
    st = {"pos": None, "n": 8}

    def bit(b):
        if st["n"] == 8:
            st["pos"], st["n"] = len(out), 0
            out.append(0)
        out[st["pos"]] |= (b & 1) << (7 - st["n"])
        st["n"] += 1
    i, n = 0, len(data)
    while i < n:
        best_len = best_d = 0
        for d in range(1, min(i, 0x1FFF) + 1):
            k = 0
            while k < 256 and i + k < n and data[i - d + k] == data[i + k]:
                k += 1
            if k > best_len or (k == best_len and k and d < best_d):
                best_len, best_d = k, d
            if best_len == 256:
                break
        if best_len >= 2 and best_d <= 0xFF and best_len <= 5:
            bit(0), bit(0)
            c = best_len - 2
            bit(c >> 1), bit(c & 1)
            out.append(0x100 - best_d)
        elif best_len >= 3:
            bit(0), bit(1)
            w = ((0x2000 - best_d) << 3) & 0xFFFF
            if best_len <= 9:
                w |= best_len - 2
                out += bytes((w >> 8, w & 0xFF))
            else:
                out += bytes((w >> 8, w & 0xFF, best_len - 1))
        else:
            best_len = 1
            bit(1)
            out.append(data[i])
        i += best_len
    return bytes(out)


# ---------------------------------------------------------------- MIO0 (SM64 / SF64 / MK64)


def mio0_header(d: bytes, o: int = 0) -> tuple[int, int, int] | None:
    """(decompressed size, comp offset, raw offset) of a MIO0 header at `o`, or None when it isn't plausible."""
    if d[o:o + 4] != b"MIO0" or o + 16 > len(d):
        return None
    size, comp, raw = struct.unpack_from(">III", d, o + 4)
    if not (0 < size <= 0x1000000 and 16 <= comp <= raw and comp % 4 == 0):
        return None
    return size, comp, raw


def mio0_decompress(d: bytes, o: int = 0, *, strict: bool = True) -> bytes:
    """MIO0 at offset `o`: header "MIO0", u32 size, u32 comp offset, u32 raw offset (relative to the header); control
    bits MSB first from +16 (1 = a raw byte, 0 = a 2-byte back-reference: length (v >> 12) + 3, distance
    (v & 0xFFF) + 1). One codec for SM64 and SF64 (the SF64 decomp's libmio0 reads the same bits byte by byte).
    strict: raise ValueError on overruns / a size mismatch instead of IndexError."""
    if d[o:o + 4] != b"MIO0":
        raise ValueError("not a MIO0 blob")
    size, comp, raw = struct.unpack_from(">III", d, o + 4)
    out = bytearray()
    bits_p, comp_p, raw_p = o + 16, o + comp, o + raw
    word, nbits = 0, 0
    while len(out) < size:
        if nbits == 0:
            if strict and bits_p + 4 > o + comp:
                raise ValueError("MIO0 control bits overrun")
            word = struct.unpack_from(">I", d, bits_p)[0]
            bits_p += 4
            nbits = 32
        bit = word & 0x80000000
        word = (word << 1) & 0xFFFFFFFF
        nbits -= 1
        if bit:
            if strict and raw_p >= len(d):
                raise ValueError("MIO0 uncompressed section overrun")
            out.append(d[raw_p])
            raw_p += 1
        else:
            if strict and comp_p + 2 > o + raw:
                raise ValueError("MIO0 compressed section overrun")
            v = struct.unpack_from(">H", d, comp_p)[0]
            comp_p += 2
            ln, back = (v >> 12) + 3, (v & 0xFFF) + 1
            if strict and back > len(out):
                raise ValueError("MIO0 back-reference before output start")
            for _ in range(ln):
                out.append(out[-back])
    if strict and len(out) != size:
        raise ValueError("MIO0 size mismatch: decoded %d, header says %d" % (len(out), size))
    return bytes(out[:size]) if strict else bytes(out)


def _lz_matches(data: bytes, window: int, min_len: int, max_len: int, depth: int = 64):
    """Greedy longest-match finder: yields (position, length, distance) with length 0 for a literal."""
    heads: dict[bytes, list[int]] = {}
    i, n = 0, len(data)
    while i < n:
        best_len = best_d = 0
        key = data[i:i + min_len]
        if len(key) == min_len:
            for j in reversed(heads.get(key, [])[-depth:]):
                if i - j > window:
                    break
                k = min_len
                while k < max_len and i + k < n and data[j + k] == data[i + k]:
                    k += 1
                if k > best_len:
                    best_len, best_d = k, i - j
                    if k == max_len:
                        break
        step = best_len if best_len >= min_len else 1
        yield i, (best_len if best_len >= min_len else 0), best_d
        for k in range(i, i + step):
            if k + min_len <= n:
                heads.setdefault(data[k:k + min_len], []).append(k)
        i += step


def mio0_compress(data: bytes) -> bytes:
    """Greedy MIO0 encoder (lengths 3..18, distances 1..4096); mio0_decompress inverts it."""
    flags, comp, raw = [], bytearray(), bytearray()
    for i, ln, d in _lz_matches(data, 4096, 3, 18):
        if ln:
            flags.append(0)
            comp += struct.pack(">H", (ln - 3) << 12 | (d - 1))
        else:
            flags.append(1)
            raw.append(data[i])
    flags += [0] * (-len(flags) % 32)
    bits = bytearray()
    for k in range(0, len(flags), 32):
        w = 0
        for b in flags[k:k + 32]:
            w = (w << 1) | b
        bits += struct.pack(">I", w)
    comp_off = 16 + len(bits)
    raw_off = comp_off + len(comp)
    return b"MIO0" + struct.pack(">III", len(data), comp_off, raw_off) + bytes(bits) + bytes(comp) + bytes(raw)


# ---------------------------------------------------------------- Yaz0 encoder (decoder moved from gbox.oot_writer below)


def yaz0_compress(data: bytes) -> bytes:
    """Greedy Yaz0 encoder (lengths 3..273, distances 1..4096); yaz0_decompress inverts it."""
    out = bytearray(b"Yaz0" + struct.pack(">I", len(data)) + bytes(8))
    group, code, nbits = bytearray(), 0, 0
    for i, ln, d in _lz_matches(data, 4096, 3, 0x111):
        code <<= 1
        if ln:
            if ln >= 0x12:
                group += bytes(((d - 1) >> 8, (d - 1) & 0xFF, ln - 0x12))
            else:
                group += bytes((((ln - 2) << 4) | ((d - 1) >> 8), (d - 1) & 0xFF))
        else:
            code |= 1
            group.append(data[i])
        nbits += 1
        if nbits == 8:
            out.append(code)
            out += group
            group, code, nbits = bytearray(), 0, 0
    if nbits:
        out.append(code << (8 - nbits))
        out += group
    return bytes(out)


# ---------------------------------------------------------------- LZSS encoder (decoder moved from gbox.mm64_inventory)


def lzss_compress(data: bytes) -> bytes:
    """Greedy Okumura LZSS (flag bytes LSB first, 1 = literal; references into a 4 KiB ring that starts at 0xFEE,
    3..18 bytes): the stream lzss_decompress reads (FF7 LZS without its u32 size, Mega Man 64, AKI after its
    4-byte header)."""
    out = bytearray()
    flags_pos, nbit = None, 8
    for i, ln, d in _lz_matches(data, 4078, 3, 18):
        if nbit == 8:
            flags_pos, nbit = len(out), 0
            out.append(0)
        if ln:
            o = (i - d + 0xFEE) & 0xFFF
            out += bytes((o & 0xFF, ((o >> 4) & 0xF0) | (ln - 3)))
        else:
            out[flags_pos] |= 1 << nbit
            out.append(data[i])
        nbit += 1
    return bytes(out)


def prs_decompress(data: bytes) -> bytes:
    out, pos, ctrl, bits = bytearray(), 0, 0, 0

    def bit():
        nonlocal ctrl, bits, pos
        if bits == 0:
            ctrl, bits = data[pos], 8
            pos += 1
        b = ctrl & 1
        ctrl >>= 1
        bits -= 1
        return b

    while pos < len(data):
        if bit():
            out.append(data[pos])
            pos += 1
            continue
        if bit():                                            # long backreference
            if pos + 1 >= len(data):
                break
            a = data[pos] | (data[pos + 1] << 8)
            pos += 2
            offset = (a >> 3) | ~0x1FFF
            if offset == ~0x1FFF:
                break
            count = (a & 7) + 2 if a & 7 else data[pos] + 1
            if not a & 7:
                pos += 1
        else:                                                # short backreference
            count = ((bit() << 1) | bit()) + 2
            offset = data[pos] | ~0xFF
            pos += 1
        start = len(out) + offset
        for z in range(count):
            out.append(out[start + z])
    return bytes(out)


def prs_compress(data: bytes, depth: int = 256) -> bytes:
    """PRS encoder (the exact inverse of prs_decompress): literals (9 bits), short refs (2..5 bytes, 256 back, 12
    bits), long refs (3..9 bytes inline, 18 bits; 10..256 with a count byte, 26 bits; 8191 back). Hash-chain match
    finder + an optimal parse (shortest bit cost, dynamic programming from the end): about SEGA's own ratio."""
    n = len(data)
    head, prev = {}, [-1] * n
    longm = [(0, 0)] * n                                     # (length, distance) longest match, distance <= 8191
    shortm = [(0, 0)] * n                                    # longest match with distance <= 255 (short refs)
    for i in range(n):
        if i + 2 < n:
            key = data[i:i + 3]
            j, tries = head.get(key, -1), 0
            lim = min(256, n - i)
            bl = bo = sl = so = 0
            while j >= 0 and i - j <= 8191 and tries < depth:
                if data[j + bl:j + bl + 1] == data[i + bl:i + bl + 1] or (i - j <= 255 and sl < 5):
                    k = 0
                    while k < lim and data[j + k] == data[i + k]:
                        k += 1
                    if k > bl:
                        bl, bo = k, i - j
                    if i - j <= 255 and k > sl:
                        sl, so = min(k, 5), i - j
                    if bl == lim:
                        break
                j, tries = prev[j], tries + 1
            longm[i] = (bl, bo)
            if sl < 2 and i + 1 < n and i >= 1 and data[i - 1:i + 1] == data[i:i + 2]:
                sl, so = 2, 1
            shortm[i] = (sl, so)
            prev[i] = head.get(key, -1)
            head[key] = i
        elif i + 1 < n:                                      # the last two bytes: a 2-byte short ref is possible
            for d in range(1, min(255, i) + 1):
                if data[i - d:i - d + 2] == data[i:i + 2]:
                    shortm[i] = (2, d)
                    break
    INF = float("inf")
    cost = [INF] * (n + 1)
    choice = [None] * (n + 1)
    cost[n] = 0
    for i in range(n - 1, -1, -1):
        best, ch = 9 + cost[i + 1], (1, 0)
        sl, so = shortm[i]
        for L in range(2, sl + 1):
            c = 12 + cost[i + L]
            if c < best:
                best, ch = c, (L, -so)
        ll, lo = longm[i]
        if ll >= 3:
            for L in range(3, min(9, ll) + 1):
                c = 18 + cost[i + L]
                if c < best:
                    best, ch = c, (L, lo)
            if ll >= 10:
                Ls = range(10, ll + 1) if ll < 48 else list(range(10, 48)) + [ll]
                for L in Ls:
                    c = 26 + cost[i + L]
                    if c < best:
                        best, ch = c, (L, lo)
        cost[i], choice[i] = best, ch
    out = bytearray()
    st = {"pos": None, "n": 8}

    def bit(b):
        if st["n"] == 8:                                     # the decoder fetches a control byte when it needs a bit
            st["pos"], st["n"] = len(out), 0
            out.append(0)
        out[st["pos"]] |= (b & 1) << st["n"]
        st["n"] += 1
    i = 0
    while i < n:
        L, off = choice[i]
        if L == 1:
            bit(1)
            out.append(data[i])
        elif off < 0:                                        # short reference
            bit(0), bit(0)
            c = L - 2
            bit(c >> 1), bit(c & 1)
            out.append((off) & 0xFF)
        else:
            bit(0), bit(1)
            o = (-off) & 0x1FFF
            if L <= 9:
                a = (o << 3) | (L - 2)
                out += bytes((a & 0xFF, a >> 8))
            else:
                a = o << 3
                out += bytes((a & 0xFF, a >> 8, L - 1))
        i += L
    bit(0), bit(1)
    out += b"\0\0"
    return bytes(out)


def yaz0_decompress(src: bytes) -> bytes:
    assert src[:4] == b"Yaz0", "not Yaz0"
    size = struct.unpack_from(">I", src, 4)[0]
    dst = bytearray(size)
    s, d = 16, 0
    while d < size:
        code = src[s]
        s += 1
        for bit in range(8):
            if d >= size:
                break
            if code & (0x80 >> bit):
                dst[d] = src[s]
                d += 1
                s += 1
            else:
                b1, b2 = src[s], src[s + 1]
                s += 2
                dist = ((b1 & 0x0F) << 8 | b2) + 1
                n = b1 >> 4
                if n == 0:
                    n = src[s] + 0x12
                    s += 1
                else:
                    n += 2
                c = d - dist
                if dist >= n:
                    dst[d:d + n] = dst[c:c + n]
                else:
                    for i in range(n):
                        dst[d + i] = dst[c + i]
                d += n
    return bytes(dst)


def lzss_decompress(src: bytes, pos: int = 0, out_size: int | None = None,
                    end: int | None = None) -> tuple[bytes, int]:
    """Decode one LZSS stream starting at ``src[pos]``.

    Returns ``(data, consumed)``.  Decoding stops at ``out_size`` bytes or at
    ``end`` (exclusive input bound), whichever comes first.
    """
    ring = bytearray(0x1000)
    r = 0xFEE
    out = bytearray()
    i = pos
    n = len(src) if end is None else min(end, len(src))
    while i < n and (out_size is None or len(out) < out_size):
        flags = src[i]
        i += 1
        for bit in range(8):
            if (out_size is not None and len(out) >= out_size) or i >= n:
                break
            if flags >> bit & 1:
                c = src[i]
                i += 1
                out.append(c)
                ring[r] = c
                r = (r + 1) & 0xFFF
            else:
                if i + 1 >= n:
                    i = n
                    break
                b0, b1 = src[i], src[i + 1]
                i += 2
                o = b0 | ((b1 & 0xF0) << 4)
                for k in range((b1 & 0x0F) + 3):
                    c = ring[(o + k) & 0xFFF]
                    out.append(c)
                    ring[r] = c
                    r = (r + 1) & 0xFFF
    if out_size is not None:
        del out[out_size:]
    return bytes(out), i - pos


def vpk0_decode(src: bytes, out_size: int) -> bytes | None:
    """Decode a VPK0 stream; None when the stream is malformed.

    Ported from the US decomp src/sys/dma.c (syDmaDecodeVpk0). Bit order
    is MSB-first within a big-endian word; the first 4 bytes of the
    stream carry the decompressed size.
    """
    if len(src) < 5:
        return None
    bits = src
    pos = 0

    def get_bits(count: int) -> int:
        nonlocal pos
        if count == 0:
            return 0
        if pos + count > len(bits) * 8:
            raise ValueError("vpk0: bitstream overrun")
        value = 0
        for _ in range(count):
            value = (value << 1) | ((bits[pos >> 3] >> (7 - (pos & 7))) & 1)
            pos += 1
        return value

    # Stream layout (dma.c syDmaDecodeVpk0): 4-byte "vpk0" magic, u32 BE
    # decompressed size, u8 sample method, two Huffman trees, LZ bitstream.
    magic = get_bits(32)
    if magic != 0x76706B30:  # b"vpk0"
        return None
    header_size = get_bits(32)
    sample_method = get_bits(8)

    def read_tree() -> Any:  # noqa: ANN401 - recursive tree, ints/tuples mix
        stack: list = []
        try:
            while True:
                node = get_bits(1)
                if node and len(stack) < 2:
                    return stack[0] if stack else None
                if node:
                    right = stack.pop()
                    left = stack.pop()
                    stack.append((left, right))
                else:
                    stack.append(get_bits(8))
        except ValueError:
            return None

    offsets_tree = read_tree()
    lengths_tree = read_tree()
    if offsets_tree is None or lengths_tree is None:
        return None

    out = bytearray()
    try:
        while len(out) < out_size:
            flag = get_bits(1)
            if not flag:
                out.append(get_bits(8))
            else:
                # Offsets first, then lengths (bit order matters).
                if sample_method:
                    sp64 = 0
                    s1 = offsets_tree
                    while isinstance(s1, tuple):
                        s1 = s1[0 if get_bits(1) == 0 else 1]
                    sample1 = get_bits(s1)
                    if sample1 <= 2:
                        sp64 = sample1 + 1
                        off = offsets_tree
                        while isinstance(off, tuple):
                            off = off[0 if get_bits(1) == 0 else 1]
                        sample2 = get_bits(off)
                        value = sample2 * 4 + sp64 - 8
                    else:
                        # dma.c: copy_src = out_ptr - value * 4 - sp64 + 8
                        # with sp64 == 0, i.e. distance = value * 4 - 8.
                        value = sample1 * 4 - 8
                    copy_src = len(out) - value
                else:
                    node = offsets_tree
                    while isinstance(node, tuple):
                        node = node[0 if get_bits(1) == 0 else 1]
                    value = get_bits(node)
                    copy_src = len(out) - value

                node = lengths_tree
                while isinstance(node, tuple):
                    node = node[0 if get_bits(1) == 0 else 1]
                length = get_bits(node)

                if copy_src < 0 or copy_src >= len(out):
                    return None
                for _ in range(length):
                    out.append(out[copy_src])
                    copy_src += 1
            if len(out) > out_size:
                return None
    except (ValueError, IndexError):
        return None
    if header_size != len(out):
        return None
    return bytes(out[:out_size])


class LZ10Error(ValueError):
    pass


def lz10_decompress(data: bytes) -> bytes:
    """Nitro LZ10 (type 0x10) decompressor with the backward zero-window.

    Matches ndspy.lz10.decompress byte-for-byte on every compressed file of
    the owned Tetris DS (USA) ROM.
    """
    if not data or data[0] != 0x10:
        raise LZ10Error("not an LZ10 stream (missing 0x10 type byte)")
    out_len = data[1] | (data[2] << 8) | (data[3] << 16)
    out = bytearray(out_len)  # zero-filled: backward reads beyond out_pos see 0x00
    in_pos, out_pos = 4, 0
    while out_len > 0 and in_pos < len(data):
        d = data[in_pos]
        in_pos += 1
        if d:
            for _ in range(8):
                if d & 0x80:
                    if in_pos + 2 > len(data):
                        raise LZ10Error("truncated copy token")
                    w = (data[in_pos] << 8) | data[in_pos + 1]
                    in_pos += 2
                    length = (w >> 12) + 3
                    window = out_pos - (w & 0xFFF) - 1
                    for _ in range(length):
                        out[out_pos] = out[window]  # may read backward/zeroed cells
                        out_pos += 1
                        window += 1
                        out_len -= 1
                        if out_len == 0:
                            return bytes(out)
                else:
                    if in_pos >= len(data):
                        raise LZ10Error("truncated literal")
                    out[out_pos] = data[in_pos]
                    out_pos += 1
                    in_pos += 1
                    out_len -= 1
                    if out_len == 0:
                        return bytes(out)
                d = (d << 1) & 0xFF
        else:
            for _ in range(8):
                if in_pos >= len(data):
                    raise LZ10Error("truncated literal run")
                out[out_pos] = data[in_pos]
                out_pos += 1
                in_pos += 1
                out_len -= 1
                if out_len == 0:
                    return bytes(out)
    if out_len:
        raise LZ10Error(f"stream exhausted with {out_len} bytes missing")
    return bytes(out)
