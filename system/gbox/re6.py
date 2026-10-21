"""Resident Evil 6 (Xbox 360, title 43430819, BH6MasterRelease) in Xenia: disc extraction, MT Framework files, mods.

Live memory work (items, Mercenaries loadouts) is in gbox/re6_tool.py; this module is the offline side:
  - XDVDFS reader: the catalogue's ISO -> a local extracted copy (runtime/re6/base). Xenia boots an extracted folder
    (default.xex + nativeXenon/...), so mods are hard-link copies of that folder with only the changed .arc files real
    (cache/mods/<game_id>/<mod>, the same layout as gbox/filemods.py; launch_game(mod=...) runs them). The ISO is never
    written; revert = launch without a mod (or op=revert_all, which also removes the mod folders).
  - ARC (MT Framework archive, Xbox 360 = big-endian, version 7): read, and write back with replaced/added entries.
  - TEX (version 0x9D, Xbox 360): GPU-tiled, 16-bit endian-swapped DXT/ARGB -> PNG (Pillow).
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import time
import zlib
from pathlib import Path

TITLE_ID = 0x43430819
GAME_ID = "0871eee3b68cdea3"          # catalogue id of "Resident Evil 6" (xbox360, hyperspin library)


def runtime(cfg) -> Path:
    d = Path(cfg.runtime) / "re6"
    d.mkdir(parents=True, exist_ok=True)
    return d


def base_dir(cfg) -> Path:
    return runtime(cfg) / "base"


# ------------------------------------------------------------------ XDVDFS (Xbox / Xbox 360 game discs)

class XDVD:
    """Read-only XDVDFS image. files: {"/nativeXenon/arc/X360/Merce.arc": (byte offset, size)}."""
    PARTITIONS = (0, 0x2080000, 0xFD90000, 0x18300000)       # plain / XGD3 / XGD2 / XGD1 game partition

    def __init__(self, path):
        self.path, self.f = str(path), open(path, "rb")
        for part in self.PARTITIONS:
            self.f.seek(part + 32 * 2048)
            h = self.f.read(28)
            if h[:20] == b"MICROSOFT*XBOX*MEDIA":
                self.part = part
                root, size = struct.unpack("<II", h[20:28])
                break
        else:
            raise ValueError(f"{path}: not an Xbox disc image (no XDVDFS volume)")
        self.files: dict[str, tuple[int, int]] = {}
        self._walk(root, size, "")

    def _walk(self, sec: int, size: int, path: str):
        self.f.seek(self.part + sec * 2048)
        d = self.f.read(size)
        stack = [0]
        while stack:
            off = stack.pop() * 4
            if off + 14 > len(d):
                continue
            left, right, s, n, attr, nl = struct.unpack("<HHIIBB", d[off:off + 14])
            if left == 0xFFFF:
                continue
            name = d[off + 14:off + 14 + nl].decode("latin-1")
            if left:
                stack.append(left)
            if right:
                stack.append(right)
            p = f"{path}/{name}"
            if attr & 0x10:
                if n:
                    self._walk(s, n, p)
            else:
                self.files[p] = (self.part + s * 2048, n)

    def read(self, p: str) -> bytes:
        # Keys are absolute disc paths ("/default.xex"); accept a bare name too so
        # callers that guess "default.xex" get the file instead of a KeyError.
        key = p if p.startswith("/") else "/" + p
        off, n = self.files[key]
        self.f.seek(off)
        return self.f.read(n)

    def close(self):
        self.f.close()


def extract(iso, dst: Path, progress=None, only=None) -> dict:
    """Copy every file of the disc (or those whose path contains one of `only`) into dst. Resumable: files already
    there with the right size are kept. The marker .gbox-base-complete is written when the whole disc is out."""
    dst = Path(dst)
    disc = XDVD(iso)
    todo = {p: v for p, v in disc.files.items() if not only or any(o.lower() in p.lower() for o in only)}
    total, done, t0 = sum(n for _, n in todo.values()) or 1, 0, time.time()
    try:
        for p, (off, n) in sorted(todo.items(), key=lambda kv: kv[1][0]):      # disc order: sequential reads
            out = dst / p.lstrip("/")
            if not (out.exists() and out.stat().st_size == n):
                out.parent.mkdir(parents=True, exist_ok=True)
                tmp = out.with_name(out.name + ".part")
                with open(tmp, "wb") as fo:
                    disc.f.seek(off)
                    left = n
                    while left:
                        b = disc.f.read(min(left, 8 << 20))
                        if not b:
                            raise IOError(f"short read in {p}")
                        fo.write(b)
                        left -= len(b)
                tmp.replace(out)
            done += n
            if progress:
                progress(done, total, p)
    finally:
        disc.close()
    if not only:
        (dst / ".gbox-base-complete").write_text(json.dumps({"iso": str(iso), "files": len(todo), "at": time.time()}))
    return {"dir": str(dst), "files": len(todo), "bytes": total, "seconds": round(time.time() - t0, 1)}


def ensure_base(cfg, iso, progress=None) -> Path:
    b = base_dir(cfg)
    if not (b / ".gbox-base-complete").exists():
        extract(iso, b, progress)
    return b


# ------------------------------------------------------------------ LZX (XMemCompress "native" stream, as in the arcs)
# Decoder: the LZX format as described by libmspack's lzxd.c, implemented independently in Python.
# Encoder: only LZX "uncompressed" blocks, which every LZX decoder (the game's XMemDecompress included) accepts.

_EXTRA = [min(max(i // 2 - 1, 0), 17) for i in range(51)]
_PBASE = [0]
for _e in _EXTRA:
    _PBASE.append(_PBASE[-1] + (1 << _e))


class _Bits:
    __slots__ = ("d", "p", "buf", "n")

    def __init__(self, d: bytes):
        self.d, self.p, self.buf, self.n = d, 0, 0, 0

    def ensure(self, k):
        while self.n < k:
            w = self.d[self.p] | self.d[self.p + 1] << 8 if self.p + 1 < len(self.d) else 0
            self.p += 2
            self.buf = ((self.buf << 16) | w) & 0xFFFFFFFFFFFF
            self.n += 16

    def peek(self, k):
        if self.n < k:
            self.ensure(k)
        return (self.buf >> (self.n - k)) & ((1 << k) - 1)

    def drop(self, k):
        self.n -= k

    def read(self, k):
        if not k:
            return 0
        v = self.peek(k)
        self.n -= k
        return v


class _Huff:
    """Canonical Huffman table: one lookup per symbol (table indexed by the next `bits` bits)."""
    __slots__ = ("bits", "sym", "ln")

    def __init__(self, lens):
        m = max(lens) if lens else 0
        self.bits = m
        self.sym = self.ln = None
        if not m:
            return
        size = 1 << m
        sym, ln = [0] * size, [0] * size
        code = 0
        for L in range(1, m + 1):
            for s, l in enumerate(lens):
                if l == L:
                    lo = code << (m - L)
                    hi = lo + (1 << (m - L))
                    if hi > size:
                        raise ValueError("LZX: over-subscribed Huffman table")
                    sym[lo:hi] = [s] * (hi - lo)
                    ln[lo:hi] = [L] * (hi - lo)
                    code += 1
            code <<= 1
        self.sym, self.ln = sym, ln

    def decode(self, b: _Bits):
        i = b.peek(self.bits)
        L = self.ln[i]
        if not L:
            raise ValueError("LZX: bad Huffman code")
        b.n -= L
        return self.sym[i]


class LZXDecoder:
    def __init__(self, window_bits: int = 17):
        self.wsize = 1 << window_bits
        self.win = bytearray(self.wsize)
        self.wpos = 0
        self.slots = {15: 30, 16: 32, 17: 34, 18: 36, 19: 38, 20: 42, 21: 50}[window_bits]
        self.main_lens = [0] * (256 + self.slots * 8)
        self.len_lens = [0] * 249
        self.R = [1, 1, 1]
        self.header_read = False
        self.btype = self.blen = self.remaining = 0

    @staticmethod
    def _read_lens(b, lens, first, last):
        pre = _Huff([b.read(4) for _ in range(20)])
        x = first
        while x < last:
            z = pre.decode(b)
            if z == 17:
                run = 4 + b.read(4)
                lens[x:x + run] = [0] * run
                x += run
            elif z == 18:
                run = 20 + b.read(5)
                lens[x:x + run] = [0] * run
                x += run
            elif z == 19:
                run = 4 + b.read(1)
                z = (lens[x] - pre.decode(b)) % 17
                lens[x:x + run] = [z] * run
                x += run
            else:
                lens[x] = (lens[x] - z) % 17
                x += 1

    def frame(self, data: bytes, out_len: int) -> bytes:
        b = _Bits(data)
        if not self.header_read:
            if b.read(1):
                raise ValueError("LZX: Intel E8 translation is not supported")
            self.header_read = True
        win, wmask, R = self.win, self.wsize - 1, self.R
        start, togo = self.wpos, out_len
        while togo > 0:
            if self.remaining == 0:
                if self.btype == 3 and self.blen & 1:
                    b.p += 1                                          # uncompressed block of odd length: pad byte
                self.btype = b.read(3)
                self.blen = self.remaining = (b.read(16) << 8) | b.read(8)
                if self.btype == 2:
                    self.aligned = _Huff([b.read(3) for _ in range(8)])
                if self.btype in (1, 2):
                    self._read_lens(b, self.main_lens, 0, 256)
                    self._read_lens(b, self.main_lens, 256, len(self.main_lens))
                    self.main = _Huff(self.main_lens)
                    self._read_lens(b, self.len_lens, 0, 249)
                    self.lent = _Huff(self.len_lens)
                elif self.btype == 3:
                    b.ensure(16)
                    if b.n > 16:
                        b.p -= 2
                    b.buf = b.n = 0
                    R[0], R[1], R[2] = struct.unpack_from("<III", data, b.p)
                    b.p += 12
                else:
                    raise ValueError(f"LZX: bad block type {self.btype}")
            n = min(self.remaining, togo)
            pos = self.wpos
            end = pos + n
            if self.btype == 3:
                win[pos:end] = data[b.p:b.p + n]
                b.p += n
                self.remaining -= n
                togo -= n
                self.wpos = end & wmask
                continue
            aligned = self.btype == 2
            main, lent, al = self.main, self.lent, getattr(self, "aligned", None)
            msym, mln, mbits = main.sym, main.ln, main.bits
            while pos < end:
                # inline main-tree decode (hot loop)
                if b.n < mbits:
                    b.ensure(mbits)
                i = (b.buf >> (b.n - mbits)) & ((1 << mbits) - 1)
                L = mln[i]
                if not L:
                    raise ValueError("LZX: bad Huffman code")
                b.n -= L
                sym = msym[i]
                if sym < 256:
                    win[pos] = sym
                    pos += 1
                    continue
                sym -= 256
                ml = sym & 7
                if ml == 7:
                    ml += lent.decode(b)
                ml += 2
                slot = sym >> 3
                if slot > 2:
                    extra = _EXTRA[slot]
                    off = _PBASE[slot] - 2
                    if aligned and extra >= 3:
                        if extra > 3:
                            off += b.read(extra - 3) << 3
                        off += al.decode(b)
                    elif extra:
                        off += b.read(extra)
                    else:
                        off = 1
                    R[2], R[1], R[0] = R[1], R[0], off
                elif slot == 0:
                    off = R[0]
                elif slot == 1:
                    off = R[1]
                    R[1], R[0] = R[0], off
                else:
                    off = R[2]
                    R[2], R[0] = R[0], off
                src = pos - off
                if src >= 0 and ml <= off and pos + ml <= self.wsize:
                    win[pos:pos + ml] = win[src:src + ml]
                else:
                    for k in range(ml):
                        win[(pos + k) & wmask] = win[(src + k) & wmask]
                pos += ml
            used = pos - self.wpos
            self.remaining -= used
            togo -= used
            self.wpos = pos & wmask
        if start + out_len <= self.wsize:
            return bytes(win[start:start + out_len])
        return bytes(win[start:]) + bytes(win[:start + out_len - self.wsize])


def xmem_decompress(data: bytes, out_size: int, window_bits: int = 15) -> bytes:
    """XMemCompress native stream: chunks of [FF hi lo]{frame size} [hi lo]{chunk size} or [hi lo] (frame = 32 KiB).
    RE6's arcs use a 32 KiB window (15 bits); other window sizes are tried if that one doesn't decode."""
    try:
        return _xmem(data, out_size, window_bits)
    except (ValueError, IndexError, struct.error):
        for w in (16, 17, 18, 19, 20, 21):
            if w != window_bits:
                try:
                    return _xmem(data, out_size, w)
                except (ValueError, IndexError, struct.error):
                    pass
        raise


def _xmem(data: bytes, out_size: int, window_bits: int) -> bytes:
    dec, out, p = LZXDecoder(window_bits), bytearray(), 0
    while len(out) < out_size and p + 2 <= len(data):
        if data[p] == 0xFF:
            frame = data[p + 1] << 8 | data[p + 2]
            blk = data[p + 3] << 8 | data[p + 4]
            p += 5
        else:
            frame, blk = 0x8000, data[p] << 8 | data[p + 1]
            p += 2
        if not blk or not frame:
            break
        out += dec.frame(data[p:p + blk], min(frame, out_size - len(out)))
        p += blk
    if len(out) != out_size:
        raise ValueError(f"LZX stream ended at {len(out)} of {out_size} bytes")
    return bytes(out)


def xmem_store(raw: bytes) -> bytes:
    """A valid XMem/LZX stream holding `raw` in LZX uncompressed blocks (one 32 KiB frame per block)."""
    out = bytearray()
    for i in range(0, len(raw), 0x8000):
        chunk = raw[i:i + 0x8000]
        n = len(chunk)
        # header bits: [E8 flag = 0, first frame only] [block type 3: 3 bits] [size: 24 bits], padded to 16-bit words
        k = (1 if i == 0 else 0) + 3 + 24
        v = (3 << 24) | n
        pad = (-k) % 16
        v <<= pad
        k += pad
        words = b"".join(struct.pack("<H", (v >> (k - 16 * (j + 1))) & 0xFFFF) for j in range(k // 16))
        blk = words + struct.pack("<III", 1, 1, 1) + chunk + (b"\0" if n & 1 else b"")
        out += (struct.pack(">H", len(blk)) if n == 0x8000 else b"\xff" + struct.pack(">HH", n, len(blk))) + blk
    out += bytes(5)                                   # end of stream: 5 zero bytes, exactly as the game's own arcs
    return bytes(out)


# ------------------------------------------------------------------ LZX encoder (verbatim blocks)
# The game's XMemDecompress does not take LZX "uncompressed" blocks from us (checked in game: the arc never finished
# loading), so entries are written as real LZX: one verbatim block per 32 KiB frame, literals + LZ77 matches
# (explicit offsets only, no repeat-offset slots), complete length-limited Huffman trees, lengths delta-coded against
# the previous block exactly as the decoder keeps them. Window 15 bits, as the game's own arcs use.

class _BitW:
    def __init__(self):
        self.words, self.acc, self.n = bytearray(), 0, 0

    def put(self, v: int, k: int):
        if not k:
            return
        self.acc = (self.acc << k) | (v & ((1 << k) - 1))
        self.n += k
        while self.n >= 16:
            self.n -= 16
            w = (self.acc >> self.n) & 0xFFFF
            self.words += bytes((w & 0xFF, w >> 8))
        self.acc &= (1 << self.n) - 1

    def flush(self) -> bytes:
        if self.n:
            self.put(0, 16 - self.n)
        return bytes(self.words)


def _huff_lengths(freq: list[int], maxlen: int) -> list[int]:
    """Huffman code lengths (<= maxlen) for freq; at least two symbols get a code (complete tree)."""
    import heapq
    f = list(freq)
    used = [i for i, x in enumerate(f) if x]
    for i in (0, 1):                                   # complete trees need >= 2 symbols
        if len(used) < 2 and i not in used:
            f[i] = 1
            used.append(i)
    while True:
        heap = [(x, i, None) for i, x in enumerate(f) if x]
        heapq.heapify(heap)
        nodes = {}
        uid = len(f)
        while len(heap) > 1:
            a = heapq.heappop(heap)
            b = heapq.heappop(heap)
            nodes[uid] = (a[1], b[1])
            heapq.heappush(heap, (a[0] + b[0], uid, None))
            uid += 1
        lens = [0] * len(f)
        stack = [(heap[0][1], 0)]
        while stack:
            k, d = stack.pop()
            if k in nodes:
                stack += [(nodes[k][0], d + 1), (nodes[k][1], d + 1)]
            else:
                lens[k] = max(d, 1)
        if max(lens) <= maxlen:
            return lens
        f = [(x + 1) // 2 if x else 0 for x in f]    # flatten and retry


def _codes(lens: list[int]) -> list[int]:
    """Canonical codes (as the decoder assigns them: by length, then symbol)."""
    codes, code = [0] * len(lens), 0
    for L in range(1, 17):
        for s, l in enumerate(lens):
            if l == L:
                codes[s] = code
                code += 1
        code <<= 1
    return codes


def _pos_slot(fo: int) -> int:
    lo, hi = 0, len(_PBASE) - 2
    while lo < hi:                                     # largest slot with PBASE[slot] <= fo
        mid = (lo + hi + 1) // 2
        if _PBASE[mid] <= fo:
            lo = mid
        else:
            hi = mid - 1
    return lo


def _lz77(data: bytes, start: int, end: int) -> list:
    """Greedy matches inside data[start:end] (offsets within the frame): [lit] or (length, offset)."""
    out, table, i = [], {}, start
    mv = data
    while i < end:
        best_len = 0
        if i + 3 <= end:
            key = mv[i:i + 3]
            j = table.get(key)
            table[key] = i
            if j is not None and i - j <= 32765:
                L, mx = 0, min(257, end - i)
                while L < mx and mv[j + L] == mv[i + L]:
                    L += 1
                if L >= 3:
                    best_len, off = L, i - j
        if best_len:
            out.append((best_len, off))
            for k in range(i + 1, min(i + best_len, end - 2)):
                table[mv[k:k + 3]] = k
            i += best_len
        else:
            out.append(mv[i])
            i += 1
    return out


def _write_lens(w: _BitW, new: list[int], prev: list[int]):
    """Pretree-coded tree lengths (delta vs prev, mod 17), no run codes."""
    zs = [(p - n) % 17 for p, n in zip(prev, new)]
    pf = [0] * 20
    for z in zs:
        pf[z] += 1
    plens = _huff_lengths(pf, 15)
    for l in plens:
        w.put(l, 4)
    pc = _codes(plens)
    for z in zs:
        w.put(pc[z], plens[z])


def xmem_compress(raw: bytes, window_bits: int = 15) -> bytes:
    nslots = {15: 30, 16: 32, 17: 34}[window_bits]
    main_prev, len_prev = [0] * (256 + nslots * 8), [0] * 249
    out = bytearray()
    for fstart in range(0, len(raw), 0x8000):
        fend = min(len(raw), fstart + 0x8000)
        toks = _lz77(raw, fstart, fend)
        mf, lf = [0] * len(main_prev), [0] * 249
        enc = []
        for t in toks:
            if isinstance(t, int):
                mf[t] += 1
                enc.append((t, None, None))
            else:
                L, off = t
                slot = _pos_slot(off + 2)
                if slot >= nslots:
                    raise ValueError("LZX offset beyond the window")
                lh = min(L - 2, 7)
                sym = 256 + slot * 8 + lh
                mf[sym] += 1
                ls = L - 2 - 7 if lh == 7 else None
                if ls is not None:
                    lf[ls] += 1
                enc.append((sym, ls, (off + 2 - _PBASE[slot], _EXTRA[slot])))
        mlens, llens = _huff_lengths(mf, 16), _huff_lengths(lf, 16)
        mcodes, lcodes = _codes(mlens), _codes(llens)
        w = _BitW()
        if fstart == 0:
            w.put(0, 1)                                # no Intel E8 translation
        w.put(1, 3)                                    # verbatim block
        n = fend - fstart
        w.put(n >> 8, 16)
        w.put(n & 0xFF, 8)
        _write_lens(w, mlens[:256], main_prev[:256])
        _write_lens(w, mlens[256:], main_prev[256:])
        _write_lens(w, llens, len_prev)
        for sym, ls, ex in enc:
            w.put(mcodes[sym], mlens[sym])
            if sym >= 256:
                if ls is not None:
                    w.put(lcodes[ls], llens[ls])
                v, k = ex
                w.put(v, k)
        blk = w.flush()
        main_prev, len_prev = mlens, llens
        if len(blk) >= 0x8000:
            raise ValueError("LZX frame did not compress below 32 KiB")
        out += (struct.pack(">H", len(blk)) if n == 0x8000 else b"\xff" + struct.pack(">HH", n, len(blk))) + blk
    out += bytes(5)                                   # end of stream: 5 zero bytes, exactly as the game's own arcs
    return bytes(out)


# ------------------------------------------------------------------ ARC (MT Framework archive, Xbox 360)
# header ">4sHH": b"\0CRA", version 17, count; entries of 80 bytes: name[64] (backslash path, no extension),
# type hash u32, compressed size u32, (size << 3 | flags) u32, offset u32. Data is XMem-compressed, 32 KiB aligned.

# type hash -> extension (MT Framework class-name CRC; the ones RE6 uses for what gBox reads/writes)
EXT = {0x241F5DEB: "tex", 0x58A15856: "mod", 0x2749C8A8: "mrl", 0x3B5C7FD3: "gui", 0x7808EA10: "rtex"}


class Arc:
    def __init__(self, data: bytes | None = None, path=None):
        if data is None:
            data = Path(path).read_bytes()
        self.path = path
        magic, self.version, n = struct.unpack_from(">4sHH", data)
        if magic != b"\0CRA":
            raise ValueError(f"{path or 'data'}: not an Xbox 360 MT Framework arc ({magic!r})")
        self.entries = []
        for i in range(n):
            o = 8 + i * 80
            name = data[o:o + 64].split(b"\0")[0].decode("latin-1")
            t, csize, usize, off = struct.unpack_from(">IIII", data, o + 64)
            self.entries.append({"name": name, "type": t, "ext": EXT.get(t, f"{t:08x}"), "csize": csize,
                                 "size": usize >> 3, "flags": usize & 7, "offset": off, "_raw": data[off:off + csize]})

    def get(self, e) -> bytes:
        if isinstance(e, str):
            e = self.find(e)
        if "_data" in e:
            return e["_data"]
        raw = e["_raw"]
        if e["csize"] == e["size"] and raw[:1] != b"\xff":
            return raw
        return xmem_decompress(raw, e["size"])

    def find(self, name: str, ext: str | None = None):
        k = name.lower().replace("/", "\\")
        for e in self.entries:
            if e["name"].lower() == k and (ext is None or e["ext"] == ext):
                return e
        raise KeyError(f"{name}.{ext or '*'} not in {self.path or 'arc'}")

    def put(self, name: str, ext_or_type, data: bytes):
        """Replace (or add) an entry, LZX-compressed (xmem_compress: real verbatim blocks; the game refuses stored ones)."""
        t = ext_or_type if isinstance(ext_or_type, int) else {v: k for k, v in EXT.items()}[ext_or_type]
        try:
            e = self.find(name, EXT.get(t, f"{t:08x}"))
        except KeyError:
            e = {"name": name.replace("/", "\\"), "type": t, "ext": EXT.get(t, f"{t:08x}"), "flags": 2}
            self.entries.append(e)
        e["_data"] = data
        e["_raw"] = xmem_compress(data)
        e["csize"], e["size"] = len(e["_raw"]), len(data)

    def build(self) -> bytes:
        n = len(self.entries)
        off = (8 + 80 * n + 0x7FFF) & ~0x7FFF
        head, body = bytearray(struct.pack(">4sHH", b"\0CRA", self.version, n)), bytearray()
        for e in self.entries:
            raw = e["_raw"]
            name = e["name"].encode("latin-1")[:63]
            head += name + bytes(64 - len(name)) + struct.pack(">IIII", e["type"], len(raw), (e["size"] << 3) | e.get("flags", 2),
                                                               off + len(body))
            body += raw
        head += bytes(((8 + 80 * n + 0x7FFF) & ~0x7FFF) - len(head))
        return bytes(head + body)


# ------------------------------------------------------------------ TEX (MT Framework texture, Xbox 360)
# b"\0XET", u32 (version 0x9b | flags), u32 (mips:6 | width:13 | height:13), u32 (faces:8 | format:8 | depth...),
# then mips*faces u32 data offsets, then the data: Xenos GPU-tiled, 16-bit big-endian words.
# format -> (Pillow "bcn" decoder number or "argb", bytes per 4x4 block / per pixel)
TEX_FMT = {0x13: (1, 8), 0x14: (1, 8), 0x15: (2, 16), 0x17: (3, 16), 0x18: (3, 16), 0x19: (1, 8), 0x1E: (1, 8),
           0x1F: (3, 16), 0x23: (3, 16), 0x27: ("argb", 4), 0x28: ("argb", 4), 0x0E: ("argb", 4)}


def _xg_tiled(x, y, width: int, log_bpp: int):
    """XGAddress2DTiledOffset: element (x, y) of a tiled surface `width` elements wide -> element index.
    Works on ints or numpy integer arrays."""
    aw = (width + 31) & ~31
    macro = ((x >> 5) + (y >> 5) * (aw >> 5)) << (log_bpp + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << log_bpp
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + log_bpp)) + ((y & 1) << 4)
    return (((off & ~511) << 3) + ((off & 448) << 2) + (off & 63) + ((y & 16) << 7)
            + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)) >> log_bpp


def _tile_index(w: int, h: int, bpe: int):
    import numpy as np
    log_bpp = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}[bpe]
    aw, ah = (w + 31) & ~31, (h + 31) & ~31
    ys, xs = np.mgrid[0:h, 0:w].astype(np.int64)
    return _xg_tiled(xs, ys, aw, log_bpp).ravel(), aw * ah


def _untile(data: bytes, w: int, h: int, bpe: int) -> bytes:
    """w, h in elements (blocks or pixels); bpe bytes per element. Tiled -> linear rows."""
    import numpy as np
    idx, total = _tile_index(w, h, bpe)
    need = max(total, int(idx.max()) + 1) * bpe
    src = np.frombuffer(data.ljust(need, b"\0"), dtype=np.uint8)[:need].reshape(-1, bpe)
    return src[idx].tobytes()


def _tile(lin: bytes, w: int, h: int, bpe: int) -> bytes:
    """Linear rows -> Xenos tiled layout (inverse of _untile)."""
    import numpy as np
    idx, total = _tile_index(w, h, bpe)
    out = np.zeros((max(total, int(idx.max()) + 1), bpe), dtype=np.uint8)
    out[idx] = np.frombuffer(lin, dtype=np.uint8).reshape(-1, bpe)
    return out.tobytes()


def _swap16(b: bytes) -> bytes:
    import numpy as np
    return np.frombuffer(b[:len(b) & ~1], dtype=">u2").astype("<u2").tobytes()


def tex_info(d: bytes) -> dict:
    if d[:4] != b"\0XET":
        raise ValueError("not an Xbox 360 MT texture")
    w1, w2, w3 = struct.unpack_from(">III", d, 4)
    mips, faces = w2 & 63, w3 & 0xFF
    offs = struct.unpack_from(f">{mips * faces}I", d, 16)
    return {"version": w1 & 0xFFF, "flags": w1 >> 12, "mips": mips, "width": (w2 >> 6) & 0x1FFF,
            "height": (w2 >> 19) & 0x1FFF, "faces": faces, "format": (w3 >> 8) & 0xFF, "w3": w3, "offsets": offs}


def tex_to_image(d: bytes):
    """Top mip of an Xbox 360 MT texture -> PIL.Image (RGBA)."""
    from PIL import Image
    import numpy as np
    t = tex_info(d)
    fmt = TEX_FMT.get(t["format"])
    if not fmt:
        raise ValueError(f"texture format 0x{t['format']:02x} not supported")
    kind, bpe = fmt
    W, H = t["width"], t["height"]
    start = t["offsets"][0]
    end = t["offsets"][1] if t["mips"] * t["faces"] > 1 else len(d)
    raw = d[start:end]
    if kind == "argb":
        a = np.frombuffer(_untile(raw, W, H, 4), dtype=np.uint8).reshape(H, W, 4)[:, :, [1, 2, 3, 0]]   # ARGB -> RGBA
        return Image.fromarray(np.ascontiguousarray(a), "RGBA")
    bw, bh = (W + 3) // 4, (H + 3) // 4
    lin = _swap16(_untile(raw, bw, bh, bpe))
    return Image.frombytes("RGBA", (bw * 4, bh * 4), lin, "bcn", kind).crop((0, 0, W, H))


def _dxt1_encode(img) -> bytes:
    """RGB image (sides multiples of 4) -> DXT1 blocks (little-endian, linear rows of blocks). Endpoints: the darkest and
    brightest texel of each block; good enough for low-poly character textures."""
    import numpy as np
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    h, w = a.shape[:2]
    blocks = a.reshape(h // 4, 4, w // 4, 4, 3).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 3)
    lum = blocks @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    n = np.arange(len(blocks))
    lo, hi = blocks[n, lum.argmin(1)], blocks[n, lum.argmax(1)]

    def p565(c):
        c = np.clip(np.rint(c), 0, 255).astype(np.uint32)
        return ((c[:, 0] >> 3) << 11) | ((c[:, 1] >> 2) << 5) | (c[:, 2] >> 3)

    def u565(v):
        return np.stack([((v >> 11) & 31) * 255 / 31, ((v >> 5) & 63) * 255 / 63, (v & 31) * 255 / 31], 1).astype(np.float32)
    c0, c1 = p565(hi), p565(lo)
    c0, c1 = np.maximum(c0, c1), np.minimum(c0, c1)
    c0 = np.where((c0 == c1) & (c0 < 0xFFFF), c0 + 1, c0)    # keep the 4-colour mode (c0 > c1)
    c1 = np.where(c0 == c1, c1 - 1, c1)
    e0, e1 = u565(c0), u565(c1)
    pal = np.stack([e0, e1, (2 * e0 + e1) / 3, (e0 + 2 * e1) / 3], 1)              # (n, 4, 3)
    sel = ((blocks[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1).argmin(-1).astype(np.uint32)
    bits = (sel << (2 * np.arange(16, dtype=np.uint32))).sum(1).astype(np.uint32)
    out = np.zeros((len(blocks), 4), dtype="<u2")
    out[:, 0], out[:, 1], out[:, 2], out[:, 3] = c0, c1, bits & 0xFFFF, bits >> 16
    return out.tobytes()


def image_to_tex(img, size: int | None = None, mips: int = 1, w1: int = 0x2000209B) -> bytes:
    """PIL image -> Xbox 360 MT DXT1 texture (format 0x14), square power of two, `mips` levels (stops above the
    packed mip tail, < 128 px)."""
    from PIL import Image
    size = size or max(128, min(1024, 1 << (max(img.size) - 1).bit_length()))
    cur = img.convert("RGB").resize((size, size), Image.LANCZOS)
    levels = []
    for _ in range(mips):
        s = cur.size[0]
        levels.append(_tile(_swap16(_dxt1_encode(cur)), s // 4, s // 4, 8))
        if s // 2 < 128:
            break
        cur = cur.resize((s // 2, s // 2), Image.LANCZOS)
    n = len(levels)
    head = struct.pack(">4sIII", b"\0XET", w1, n | (size << 6) | (size << 19), (1 << 16) | (0x14 << 8) | 1)
    off = len(head) + 4 * n
    table, body = b"", b""
    for lv in levels:
        table += struct.pack(">I", off + len(body))
        body += lv
    return head + table + body


# ------------------------------------------------------------------ XEX2 -> loaded image (for Ghidra)
# The executable's own platform encryption/compression, undone exactly as an emulator does to run it (layout as
# documented by Xenia, xenia/kernel/util/xex2_info.h). Output = the PE image as it sits at its base address.
_XEX_KEYS = (bytes.fromhex("20B185A59D28FDC340583FBB0896BF91"), bytes(16))      # retail, devkit


def xex_image(data: bytes) -> dict:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    magic, mflags, pe_off, _, sec_off, nopt = struct.unpack_from(">4sIIIII", data)
    if magic != b"XEX2":
        raise ValueError("not an XEX2 executable")
    opt = {}
    for i in range(nopt):
        k, v = struct.unpack_from(">II", data, 24 + 8 * i)
        opt[k] = v
    image_size = struct.unpack_from(">I", data, sec_off + 4)[0]
    load = struct.unpack_from(">I", data, sec_off + 0x110)[0]
    file_key = data[sec_off + 0x150:sec_off + 0x160]
    ffi = opt[0x3FF]
    info_size, enc, comp = struct.unpack_from(">IHH", data, ffi)
    payload = data[pe_off:]

    def decrypt(key):
        d = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
        sess = d.update(file_key) + d.finalize()
        c = Cipher(algorithms.AES(sess), modes.CBC(bytes(16))).decryptor()
        n = len(payload) & ~15
        return c.update(payload[:n]) + c.finalize() + payload[n:]
    tries = [decrypt(k) for k in _XEX_KEYS] if enc else [payload]
    last = None
    for raw in tries:
        try:
            if comp == 1:                                  # basic: (data size, zero size) blocks
                out, p = bytearray(), 0
                for k in range((info_size - 8) // 8):
                    ds, zs = struct.unpack_from(">II", data, ffi + 8 + 8 * k)
                    out += raw[p:p + ds] + bytes(zs)
                    p += ds
                img = bytes(out)
            elif comp == 2:                                # normal: hashed block chain of LZX chunks
                window = struct.unpack_from(">I", data, ffi + 8)[0]
                bsize = struct.unpack_from(">I", data, ffi + 12)[0]
                chunks, p = [], 0
                while bsize:
                    blk = raw[p:p + bsize]
                    nxt = struct.unpack_from(">I", blk, 0)[0]
                    q = 24
                    while q + 2 <= len(blk):
                        n = struct.unpack_from(">H", blk, q)[0]
                        q += 2
                        if not n:
                            break
                        chunks.append(blk[q:q + n])
                        q += n
                    p += bsize
                    bsize = nxt
                dec, out = LZXDecoder(window.bit_length() - 1), bytearray()
                for ch in chunks:
                    out += dec.frame(ch, min(0x8000, image_size - len(out)))
                    if len(out) >= image_size:
                        break
                img = bytes(out)
            elif comp == 0:
                img = raw[:image_size]
            else:
                raise ValueError(f"XEX compression {comp} (delta patch) not supported")
            if img[:2] != b"MZ":
                raise ValueError("decoded image is not a PE file")
            return {"image": img, "base": opt.get(0x10201, load), "entry": opt.get(0x10100), "size": image_size}
        except (ValueError, IndexError, struct.error) as e:
            last = e
    raise ValueError(f"could not decode the XEX: {last}")


def pe_sections(img: bytes) -> list[dict]:
    pe = struct.unpack_from("<I", img, 0x3C)[0]
    nsec = struct.unpack_from("<H", img, pe + 6)[0]
    opt_size = struct.unpack_from("<H", img, pe + 20)[0]
    out = []
    for i in range(nsec):
        o = pe + 24 + opt_size + 40 * i
        name = img[o:o + 8].split(b"\0")[0].decode("latin-1")
        vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", img, o + 8)
        flags = struct.unpack_from("<I", img, o + 36)[0]
        out.append({"name": name, "vaddr": vaddr, "vsize": vsize, "exec": bool(flags & 0x20000000), "flags": flags})
    return out
