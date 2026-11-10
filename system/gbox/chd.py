"""Read-only CHD v5 (CD type) access in pure Python: the HyperSpin PS2 / PSX sets are chdman ``createcd`` images with
the ``cdlz`` / ``cdzl`` / ``cdfl`` codecs, which ``gbox.psxdisc.CHD`` (v4 only) cannot open and no node had chdman for.

Layout (MAME src/lib/util/chd.cpp, chdcodec.cpp, huffman.cpp; verified on the owned Enter the Matrix / Path of Neo
PS2 images, which read back byte-identical ISO9660 trees):

* header (124 bytes, big endian): ``MComprHD``, u32 length, u32 version 5, 4 x codec tag, u64 logical bytes, u64 map
  offset, u64 metadata offset, u32 hunk bytes, u32 unit bytes (2448 = one CD frame: 2352 sector + 96 subcode), 3 SHA-1.
* map: 16-byte header ``u32 compressed bytes, u48 first data offset, u16 crc, u8 length bits, u8 self bits, u8 parent
  bits, u8 0`` then an MSB-first bit stream: a 16-symbol RLE-coded Huffman tree (max 8 bits), one compression type per
  hunk (7 / 8 = run of the previous type), then per hunk its length (+16-bit CRC) or self / parent reference.
* CD codecs: ``ecc bitmap ((frames + 7) / 8 bytes), compressed base length (2 bytes, 3 when the hunk is >= 64 KiB),
  base stream (all frames' 2352 sector bytes), subcode stream (zlib)``. cdlz = raw LZMA1 (lc 3, lp 0, pb 2, no end
  marker), cdzl = raw deflate. cdfl = headerless FLAC frames (44.1 kHz stereo, samples big endian) then the zlib
  subcode, no ECC bitmap; chdman picks it for a few all-zero system-area hunks (decoded by ``flac_cd``).
* a MODE1 (cooked) track stores the 2048 user bytes at the start of each 2448-byte frame.

``ChdDisc(path).read(name)`` / ``.files`` give the ISO9660 tree, ``.sector(lba)`` 2048-byte user data.
"""
from __future__ import annotations

import lzma
import re
import struct
import zlib
from functools import lru_cache
from pathlib import Path

FRAME, SECTOR, SUBCODE = 2448, 2352, 96
T_NONE, T_SELF, T_PARENT, RLE_SMALL, RLE_LARGE = 4, 5, 6, 7, 8
SELF_0, SELF_1, PARENT_SELF, PARENT_0, PARENT_1 = 9, 10, 11, 12, 13


class ChdError(ValueError):
    pass


class _Bits:
    """MSB-first bit reader (chd bitstream_in)."""

    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def read(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.pos >> 3
            if byte >= len(self.data):
                raise ChdError("map bit stream overrun")
            v = (v << 1) | ((self.data[byte] >> (7 - (self.pos & 7))) & 1)
            self.pos += 1
        return v


class _Huffman:
    """huffman_decoder<16, 8>::import_tree_rle + canonical codes (huffman.cpp)."""

    def __init__(self, bits: _Bits, numcodes: int = 16, maxbits: int = 8):
        nb = 5 if maxbits >= 16 else 4 if maxbits >= 8 else 3
        lens: list[int] = []
        while len(lens) < numcodes:
            v = bits.read(nb)
            if v != 1:
                lens.append(v)
                continue
            v = bits.read(nb)
            if v == 1:
                lens.append(1)
            else:
                lens.extend([v] * (bits.read(nb) + 3))
        if len(lens) != numcodes:
            raise ChdError("map huffman tree: wrong code count")
        histo = [0] * 33
        for n in lens:
            if n > maxbits:
                raise ChdError("map huffman tree: code too long")
            histo[n] += 1
        start = 0
        for ln in range(32, 0, -1):
            nxt = (start + histo[ln]) >> 1
            if ln != 1 and nxt * 2 != start + histo[ln]:
                raise ChdError("map huffman tree: inconsistent lengths")
            histo[ln], start = start, nxt
        self.codes: dict[tuple[int, int], int] = {}
        for sym, n in enumerate(lens):
            if n:
                self.codes[(n, histo[n])] = sym
                histo[n] += 1
        self.maxbits = maxbits

    def decode(self, bits: _Bits) -> int:
        v = 0
        for n in range(1, self.maxbits + 1):
            v = (v << 1) | bits.read(1)
            sym = self.codes.get((n, v))
            if sym is not None:
                return sym
        raise ChdError("map huffman: bad code")


def _signed(v: int, n: int) -> int:
    return v - (1 << n) if n and v >> (n - 1) else v


def _rice(bits: _Bits, n: int, param: int) -> list[int]:
    out = []
    for _ in range(n):
        q = 0
        while not bits.read(1):
            q += 1
        u = (q << param) | bits.read(param)
        out.append((u >> 1) ^ -(u & 1))
    return out


def _residual(bits: _Bits, block: int, order: int) -> list[int]:
    method = bits.read(2)
    if method > 1:
        raise ChdError("FLAC: reserved residual coding method")
    pbits, esc = (4, 15) if method == 0 else (5, 31)
    porder = bits.read(4)
    out: list[int] = []
    for p in range(1 << porder):
        n = (block >> porder) - (order if p == 0 else 0)
        if n < 0:
            raise ChdError("FLAC: bad partition order")
        param = bits.read(pbits)
        if param == esc:
            w = bits.read(5)
            out += [_signed(bits.read(w), w) for _ in range(n)]
        else:
            out += _rice(bits, n, param)
    return out


_FIXED = [[], [1], [2, -1], [3, -3, 1], [4, -6, 4, -1]]


def _subframe(bits: _Bits, block: int, bps: int) -> list[int]:
    if bits.read(1):
        raise ChdError("FLAC: subframe padding bit set")
    t = bits.read(6)
    wasted = 0
    if bits.read(1):
        wasted = 1
        while not bits.read(1):
            wasted += 1
    bps -= wasted
    if t == 0:
        s = [_signed(bits.read(bps), bps)] * block
    elif t == 1:
        s = [_signed(bits.read(bps), bps) for _ in range(block)]
    elif 8 <= t <= 12 or t >= 32:
        order = t - 8 if t < 32 else t - 31
        s = [_signed(bits.read(bps), bps) for _ in range(order)]
        if t < 32:
            coefs, shift = _FIXED[order], 0
        else:
            prec = bits.read(4) + 1
            if prec == 16:
                raise ChdError("FLAC: invalid LPC precision")
            shift = _signed(bits.read(5), 5)
            coefs = [_signed(bits.read(prec), prec) for _ in range(order)]
        res = _residual(bits, block, order)
        for r in res:
            acc = sum(c * s[-1 - j] for j, c in enumerate(coefs))
            s.append((acc >> shift if shift >= 0 else acc << -shift) + r)
    else:
        raise ChdError(f"FLAC: reserved subframe type {t}")
    return [v << wasted for v in s] if wasted else s


def flac_cd(src: bytes, samples: int) -> tuple[bytes, int]:
    """Decode the headerless FLAC frames of a CHD ``cdfl`` hunk (44.1 kHz stereo 16-bit) into big-endian interleaved
    samples; returns (bytes, bytes consumed). Small: these hunks are rare (all-zero system-area runs here)."""
    bits = _Bits(src)
    out = bytearray()
    got = 0
    while got < samples:
        if bits.read(15) != 0x7FFC:
            raise ChdError("FLAC: lost frame sync")
        bits.read(1)
        bsc, _src = bits.read(4), bits.read(4)
        chan, ssc = bits.read(4), bits.read(3)
        bits.read(1)
        b0 = bits.read(8)
        extra = 0
        while b0 & (0x80 >> extra) and extra < 7:
            extra += 1
        for _ in range(max(0, extra - 1)):
            bits.read(8)
        block = {1: 192, 6: None, 7: None}.get(bsc)
        if 2 <= bsc <= 5:
            block = 576 << (bsc - 2)
        elif bsc >= 8:
            block = 256 << (bsc - 8)
        elif bsc == 6:
            block = bits.read(8) + 1
        elif bsc == 7:
            block = bits.read(16) + 1
        if not block:
            raise ChdError("FLAC: reserved block size")
        if _src == 12:
            bits.read(8)
        elif _src in (13, 14):
            bits.read(16)
        bits.read(8)                                       # CRC-8
        bps = {0: 16, 1: 8, 2: 12, 4: 16, 5: 20, 6: 24}.get(ssc, 16)
        if chan < 8:
            ch = [_subframe(bits, block, bps) for _ in range(chan + 1)]
        elif chan in (8, 9, 10):
            a = _subframe(bits, block, bps + (1 if chan == 9 else 0))
            b = _subframe(bits, block, bps + (1 if chan != 9 else 0))
            if chan == 8:
                ch = [a, [x - y for x, y in zip(a, b)]]
            elif chan == 9:
                ch = [[x + y for x, y in zip(a, b)], b]
            else:
                ch = [[((m << 1) | (s & 1)) + s >> 1 for m, s in zip(a, b)],
                      [((m << 1) | (s & 1)) - s >> 1 for m, s in zip(a, b)]]
        else:
            raise ChdError("FLAC: reserved channel assignment")
        if len(ch) != 2:
            raise ChdError("FLAC: cdfl hunks are stereo")
        bits.pos = (bits.pos + 7) & ~7
        bits.read(16)                                      # CRC-16
        for l, r in zip(*ch):
            out += struct.pack(">hh", l, r)
        got += block
    return bytes(out), bits.pos >> 3


def header(b: bytes) -> dict:
    if b[:8] != b"MComprHD":
        raise ChdError("not a CHD")
    hlen, ver = struct.unpack_from(">II", b, 8)
    if ver != 5:
        raise ChdError(f"CHD v{ver}: this reader handles v5 (gbox.psxdisc.CHD reads v4)")
    out = {"version": ver, "header_bytes": hlen,
           "codecs": [b[16 + 4 * i:20 + 4 * i].decode("latin-1") for i in range(4)]}
    out["logical_bytes"], out["map_offset"], out["meta_offset"] = struct.unpack_from(">QQQ", b, 32)
    out["hunk_bytes"], out["unit_bytes"] = struct.unpack_from(">II", b, 56)
    out["raw_sha1"], out["sha1"], out["parent_sha1"] = b[64:84].hex(), b[84:104].hex(), b[104:124].hex()
    return out


class Chd:
    """A CD-type CHD v5 opened read-only; hunks decoded on demand (LRU cached)."""

    def __init__(self, path):
        self.path = Path(path)
        self.f = open(self.path, "rb")
        try:
            self.size = self.path.stat().st_size
            self.h = header(self.f.read(124))
            if self.h["unit_bytes"] != FRAME:
                raise ChdError(f"unit bytes {self.h['unit_bytes']}: not a CD CHD")
            if int(self.h["parent_sha1"], 16):
                raise ChdError("CHD with a parent (delta image) is not supported")
            self.hunkbytes = self.h["hunk_bytes"]
            if self.hunkbytes % FRAME or not 0 < self.hunkbytes <= 1 << 20:
                raise ChdError(f"hunk bytes {self.hunkbytes}")
            self.frames_per_hunk = self.hunkbytes // FRAME
            self.nhunks = -(-self.h["logical_bytes"] // self.hunkbytes)
            self.tracks = self._tracks()
            self._map()
            self._hunk = lru_cache(256)(self._read_hunk)
        except BaseException:
            self.f.close()
            raise

    def close(self):
        self.f.close()

    def _tracks(self) -> list[dict]:
        out, o, seen = [], self.h["meta_offset"], 0
        while o and seen < 512:
            self.f.seek(o)
            m = self.f.read(16)
            if len(m) < 16:
                break
            tag, ln, nxt = m[:4], int.from_bytes(m[5:8], "big"), struct.unpack_from(">Q", m, 8)[0]
            data = self.f.read(ln)
            if tag in (b"CHT2", b"CHTR"):
                out.append(dict(re.findall(r"(\w+):(\S+)", data.rstrip(b"\0").decode("ascii", "replace"))))
            o, seen = nxt, seen + 1
        return out

    def _map(self):
        self.f.seek(self.h["map_offset"])
        mh = self.f.read(16)
        mapbytes = struct.unpack_from(">I", mh, 0)[0]
        first = int.from_bytes(mh[4:10], "big")
        lbits, sbits = mh[12], mh[13]                     # mh[14]: parent bits (no parents here)
        if not 0 < mapbytes <= 64 << 20:
            raise ChdError(f"map size {mapbytes}")
        bits = _Bits(self.f.read(mapbytes))
        huff = _Huffman(bits)
        types = bytearray(self.nhunks)
        last, rep = 0, 0
        for i in range(self.nhunks):
            if rep:
                types[i], rep = last, rep - 1
                continue
            v = huff.decode(bits)
            if v == RLE_SMALL:
                types[i], rep = last, 2 + huff.decode(bits)
            elif v == RLE_LARGE:
                types[i], rep = last, 2 + 16 + (huff.decode(bits) << 4)
                rep += huff.decode(bits)
            else:
                types[i] = last = v
        self.map: list[tuple[int, int, int]] = []          # (type, offset, length)
        cur, last_self = first, 0
        for i in range(self.nhunks):
            t, off, ln = types[i], cur, 0
            if t <= 3:
                ln = bits.read(lbits)
                cur += ln
                bits.read(16)
            elif t == T_NONE:
                ln = self.hunkbytes
                cur += ln
                bits.read(16)
            elif t == T_SELF:
                last_self = off = bits.read(sbits)
            elif t in (SELF_0, SELF_1):
                if t == SELF_1:
                    last_self += 1
                t, off = T_SELF, last_self
            elif t in (T_PARENT, PARENT_SELF, PARENT_0, PARENT_1):
                raise ChdError("parent hunk references in a CHD without a parent")
            else:
                raise ChdError(f"hunk {i}: map type {t}")
            if t != T_SELF and off + ln > self.size:
                raise ChdError(f"hunk {i}: data 0x{off:x}+0x{ln:x} past end of file")
            if t == T_SELF and off >= i:
                raise ChdError(f"hunk {i}: self reference {off} is not earlier")
            self.map.append((t, off, ln))

    def codec_counts(self) -> dict[str, int]:
        names = self.h["codecs"] + ["none", "self"]
        out: dict[str, int] = {}
        for t, _o, _l in self.map:
            k = names[t] if t < 6 else str(t)
            out[k] = out.get(k, 0) + 1
        return out

    def _read_hunk(self, i: int) -> bytes:
        if not 0 <= i < self.nhunks:
            raise ChdError(f"hunk {i} out of range")
        t, off, ln = self.map[i]
        if t == T_SELF:
            return self._hunk(off)
        self.f.seek(off)
        src = self.f.read(ln)
        if len(src) != ln:
            raise ChdError(f"hunk {i}: short read")
        if t == T_NONE:
            return src
        return self._cd_decode(self.h["codecs"][t], src, i)

    def _cd_decode(self, codec: str, src: bytes, i: int) -> bytes:
        frames = self.frames_per_hunk
        if codec == "cdfl":
            sec, used = flac_cd(src, frames * SECTOR // 4)
            sub = zlib.decompressobj(-15).decompress(src[used:], frames * SUBCODE) if used < len(src) else b""
            sub = sub.ljust(frames * SUBCODE, b"\0")
            return b"".join(sec[k * SECTOR:(k + 1) * SECTOR] + sub[k * SUBCODE:(k + 1) * SUBCODE] for k in range(frames))
        eccb = (frames + 7) // 8
        clb = 2 if self.hunkbytes < 65536 else 3
        if len(src) < eccb + clb:
            raise ChdError(f"hunk {i}: truncated CD header")
        base_len = int.from_bytes(src[eccb:eccb + clb], "big")
        hb = eccb + clb
        if hb + base_len > len(src):
            raise ChdError(f"hunk {i}: base stream past hunk end")
        want = frames * SECTOR
        base = src[hb:hb + base_len]
        if codec == "cdlz":
            d = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 1 << 20,
                                                                  "lc": 3, "lp": 0, "pb": 2}])
            sec = d.decompress(base, max_length=want)
        elif codec == "cdzl":
            sec = zlib.decompressobj(-15).decompress(base, want)
        else:
            raise ChdError(f"hunk {i}: codec {codec!r} not supported")
        if len(sec) < want:
            raise ChdError(f"hunk {i}: {codec} gave {len(sec)} of {want} bytes")
        sub = zlib.decompressobj(-15).decompress(src[hb + base_len:], frames * SUBCODE) if len(src) > hb + base_len else b""
        sub = sub.ljust(frames * SUBCODE, b"\0")
        out = bytearray()
        for k in range(frames):
            out += sec[k * SECTOR:(k + 1) * SECTOR] + sub[k * SUBCODE:(k + 1) * SUBCODE]
        # ECC-stripped frames (bitmap bit set) only lose sync/ECC bytes; user data is intact, so not regenerated
        return bytes(out)

    def frame(self, n: int) -> bytes:
        h, k = divmod(n, self.frames_per_hunk)
        return self._hunk(h)[k * FRAME:(k + 1) * FRAME]


class ChdDisc:
    """ISO9660 over the first data track of a CD-type CHD v5 (MODE1 cooked or MODE1_RAW / MODE2_RAW)."""

    def __init__(self, path):
        self.chd = Chd(path)
        try:
            t = (self.chd.tracks or [{"TYPE": "MODE1"}])[0]
            self.track_type = t.get("TYPE", "MODE1")
            self.frames = int(t.get("FRAMES", 0) or 0)
            self.files: dict[str, tuple[int, int]] = {}
            pvd = self.sector(16)
            if pvd[1:6] != b"CD001":
                raise ChdError("no ISO9660 primary volume descriptor at sector 16")
            self.pvd = pvd
            root = pvd[156:190]
            self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "", 0)
        except BaseException:
            self.chd.close()
            raise

    def close(self):
        self.chd.close()

    def sector(self, lba: int) -> bytes:
        if self.frames and not 0 <= lba < self.frames:
            raise ChdError(f"sector {lba} outside the track ({self.frames})")
        f = self.chd.frame(lba)
        if self.track_type == "MODE1":
            return f[:2048]
        if self.track_type == "MODE2_RAW" and f[15] == 2:
            return f[24:24 + 2048]
        return f[16:16 + 2048]

    def _walk(self, lba: int, size: int, prefix: str, depth: int):
        if depth > 12 or size > 1 << 22:
            return
        buf = b"".join(self.sector(lba + i) for i in range((size + 2047) // 2048))
        o = 0
        while o < len(buf):
            n = buf[o]
            if n == 0:
                o = (o // 2048 + 1) * 2048
                continue
            rec, o = buf[o:o + n], o + n
            if len(rec) < 34:
                break
            name = rec[33:33 + rec[32]]
            if name in (b"\0", b"\1"):
                continue
            path = prefix + name.decode("latin-1").split(";")[0]
            elba, esize = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0]
            if rec[25] & 2:
                self._walk(elba, esize, path + "/", depth + 1)
            else:
                self.files[path.upper()] = (elba, esize)

    def size(self, name: str) -> int:
        return self.files[name.upper()][1]

    def read(self, name: str, offset: int = 0, size: int | None = None) -> bytes:
        lba, n = self.files[name.upper()]
        size = n - offset if size is None else size
        if offset < 0 or size < 0 or offset + size > n:
            raise ChdError(f"{name}: read 0x{offset:x}+0x{size:x} outside 0x{n:x} bytes")
        first, last = (offset // 2048), (offset + size + 2047) // 2048
        buf = b"".join(self.sector(lba + i) for i in range(first, last))
        s = offset - first * 2048
        return buf[s:s + size]

    def write_iso(self, out: Path, progress=None) -> Path:
        """The whole data track as a plain 2048-byte-sector ISO (what PCSX2 and the patch writers take). Written to
        ``out.part`` and renamed, so a half-written image is never mistaken for a finished one."""
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_name(out.name + ".part")
        frames = self.frames or self.chd.nhunks * self.chd.frames_per_hunk
        with open(part, "wb") as f:
            for h in range(-(-frames // self.chd.frames_per_hunk)):
                hunk = self.chd._read_hunk(h)
                for k in range(self.chd.frames_per_hunk):
                    n = h * self.chd.frames_per_hunk + k
                    if n >= frames:
                        break
                    fr = hunk[k * FRAME:(k + 1) * FRAME]
                    f.write(fr[:2048] if self.track_type == "MODE1" else
                            fr[24:24 + 2048] if self.track_type == "MODE2_RAW" and fr[15] == 2 else fr[16:16 + 2048])
                if progress and h % 2048 == 0:
                    progress(h * self.chd.frames_per_hunk, frames)
        part.replace(out)
        return out

    def extract(self, name: str, out: Path, progress=None) -> Path:
        """Stream one file to disk (big archives: 2048-byte sectors, never the whole file in memory)."""
        lba, n = self.files[name.upper()]
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            done = 0
            for i in range((n + 2047) // 2048):
                chunk = self.sector(lba + i)[:n - done]
                f.write(chunk)
                done += len(chunk)
                if progress and i % 4096 == 0:
                    progress(done, n)
        return out


# ---------------------------------------------------------------- GD-ROM / multi-track CHD -> GDI (no chdman needed)

def _meta_tracks(f, meta_offset: int) -> list[dict]:
    """CHT2 / CHTR / CHGD track records (v4 and v5 share the metadata entry layout)."""
    out, o, seen = [], meta_offset, 0
    while o and seen < 512:
        f.seek(o)
        m = f.read(16)
        if len(m) < 16:
            break
        tag, ln, nxt = m[:4], int.from_bytes(m[5:8], "big"), struct.unpack_from(">Q", m, 8)[0]
        data = f.read(ln)
        if tag in (b"CHT2", b"CHTR", b"CHGD"):
            rec = dict(re.findall(r"(\w+):(\S+)", data.rstrip(b"\0").decode("ascii", "replace")))
            rec["_tag"] = tag.decode("ascii")
            out.append(rec)
        o, seen = nxt, seen + 1
    return sorted(out, key=lambda r: int(r.get("TRACK", 0)))


def track_layout(path) -> list[dict]:
    """[{track, type, frames, first_frame}] of a CD / GD-ROM CHD (v4 or v5). chdman pads every track to a multiple of
    4 frames (CD_TRACK_PADDING; CHGD records name it as PAD), so track N starts after the padded tracks before it."""
    with open(path, "rb") as f:
        b = f.read(124)
        if b[:8] != b"MComprHD":
            raise ChdError("not a CHD")
        ver = struct.unpack_from(">I", b, 12)[0]
        meta = struct.unpack_from(">Q", b, 36 if ver == 4 else 48)[0]
        records = _meta_tracks(f, meta)
        total = None                                       # frames the CHD stores (v5: logical bytes / unit bytes)
        if ver == 5:
            logical, unit = struct.unpack_from(">Q", b, 32)[0], struct.unpack_from(">I", b, 60)[0]
            total = logical // unit if unit else None

    def layout(stored_pad: bool) -> tuple[list[dict], int]:
        out, first = [], 0
        for r in records:
            frames = int(r.get("FRAMES", 0))
            pad = int(r["PAD"]) if stored_pad and "PAD" in r else (-frames) % 4
            out.append({"track": int(r.get("TRACK", len(out) + 1)), "type": r.get("TYPE", "MODE1_RAW"),
                        "frames": frames, "first_frame": first})
            first += frames + pad
        return out, first

    out, end = layout(True)
    if total is not None and end != total:
        # Some chdman builds write the GD-ROM gap before the high-density area as PAD (Crazy Taxi 2 USA: PAD 150 and
        # 44024 frames) without storing it; the stored layout is then the 4-frame CD_TRACK_PADDING alone.
        alt, alt_end = layout(False)
        if alt_end == total:
            out = alt
    if not out:
        raise ChdError("CHD has no CD track metadata")
    return out


class _FrameSource:
    """Raw 2352-byte frames of a CD CHD whatever its version: v5 through Chd, v4 through gbox.psxdisc.CHD."""

    def __init__(self, path):
        with open(path, "rb") as f:
            ver = struct.unpack_from(">I", f.read(16), 12)[0]
        if ver == 5:
            self._c = Chd(path)
            self.read = lambda n: self._c.frame(n)[:SECTOR]
        elif ver == 4:
            from .psxdisc import CHD as V4
            self._c = V4(path)
            self.read = self._c.sector
        else:
            raise ChdError(f"CHD v{ver}: no reader")
        self.version = ver


def _msf_lba(head: bytes) -> int | None:
    """LBA a raw Mode 1/2 sector header addresses (BCD minute/second/frame), None without a sync pattern."""
    if head[:12] != b"\x00" + b"\xff" * 10 + b"\x00":
        return None
    m, s, f = ((x >> 4) * 10 + (x & 15) for x in head[12:15])
    return (m * 60 + s) * 75 + f - 150


def write_gdi(path, out_dir, *, gdi_name: str = "disc.gdi", progress=None) -> Path:
    """Unpack a GD-ROM CHD to a GDI set (what chdman extractcd writes), in pure Python.

    Track 1 sits at LBA 0, the high-density data track at LBA 45000 (checked: the Mode 1 header of its first sector
    must address 45000), and an audio track between them at the LBA after the first track. Audio frames are stored big
    endian in a CHD and written little endian, as chdman does. Files go to ``*.part`` names first and are renamed once
    complete, so an interrupted run never leaves a set that looks finished."""
    layout = track_layout(path)
    src = _FrameSource(path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines, lba, done, total = [str(len(layout))], 0, 0, sum(t["frames"] for t in layout)
    names = []
    for i, t in enumerate(layout):
        audio = t["type"].upper() == "AUDIO"
        if i == len(layout) - 1 and len(layout) >= 3 and not audio:
            lba = 45000                                   # the GD-ROM high-density area
        name = f"disc{t['track']:02d}.{'raw' if audio else 'bin'}"
        part = out_dir / (name + ".part")
        with open(part, "wb") as f:
            for k in range(t["frames"]):
                fr = src.read(t["first_frame"] + k)
                if audio:
                    a = bytearray(fr)
                    a[0::2], a[1::2] = fr[1::2], fr[0::2]
                    fr = bytes(a)
                f.write(fr)
                done += 1
                if progress and done % 20000 == 0:
                    progress(done, total)
        if not audio:
            with open(part, "rb") as f:
                got = _msf_lba(f.read(16))
            if got is not None and got != lba:
                part.unlink()
                raise ChdError(f"track {t['track']}: first sector addresses LBA {got}, expected {lba}")
        names.append((part, out_dir / name))
        lines.append(f"{t['track']} {lba} {0 if audio else 4} 2352 {name} 0")
        lba += t["frames"]
    for part, final in names:
        part.replace(final)
    gdi = out_dir / gdi_name
    gdi.write_text("\n".join(lines) + "\n")
    return gdi
