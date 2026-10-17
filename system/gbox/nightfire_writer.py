"""007 - Nightfire (USA) GameCube (GO7E69) -- writer: EDL method-1 encoder, level texture swap, ISO rebuild (#1377).

The inverse of `nightfire_edl` (decoder reconstructed from Nightfire.elf ef49ce2b...3367, method 1 at
0x800668e4).  Method 1 uses the deflate token alphabet unchanged (length = LEN_BASE+extra+3, distance =
DIST_BASE+extra+1, i.e. the deflate bases), so the encoder takes LZ77 tokens from zlib's raw deflate
stream (`deflate_tokens`, a token-level inflate) and re-emits them in the Eurocom block syntax:

  per block: bit 1 (Huffman block), litlen table, distance table (9-bit count; per symbol 1 flag bit and a
  4-bit length when the running length changes), symbols with canonical bit-reversed codes, EOB 256,
  then 1 bit (1 = last block).  Bits are packed LSB-first into big-endian u32 words from +0xC.

Codes are length-limited to the game's fast-table widths (litlen 10 bits at 0x8027fdf8, distance 8 bits at
0x802809f8) so the game never builds a sub-table (error -8/-9 paths), and every table is a complete code.
Blocks are cut every `BLOCK_INPUT` decoded bytes (originals average ~14 KB per block).

Hash-pack levels keep their table; `swap_texture` overwrites a texture's GX mip chain in place when the donor
has the same GX format, size and mip count (no pointer changes).  `build_mod_iso` copies the ISO, writes a
level EDL in place when it fits its extent, otherwise relocates it past the last FST file (aligned) and
patches that FST entry's offset/size; it never touches the source ISO.
"""
from __future__ import annotations

import hashlib
import heapq
import shutil
import struct
import zlib
from array import array
from pathlib import Path

from .nightfire_edl import DIST_BASE, DIST_EXTRA, LEN_BASE, LEN_EXTRA, decompress, header
from .nightfire_inventory import pack_index

LIT_LIMIT = 10      # game litlen fast table bits: no sub-tables
DIST_LIMIT = 8      # game distance fast table bits
BLOCK_INPUT = 16384
GC_DISC_SIZE = 1459978240
FILE_ALIGN = 0x8000

# deflate (RFC 1951) tables for the token-level inflate
_D_LBASE = [b + 3 for b in LEN_BASE]
_D_DBASE = [b + 1 for b in DIST_BASE]
_CL_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


# ----------------------------------------------------------------------------------------- deflate tokens
def _inflate_table(lengths):
    maxlen = max(lengths) if lengths else 0
    if maxlen == 0:
        return ((), 0)
    fast = [-1] * (1 << maxlen)
    code = 0
    for L in range(1, maxlen + 1):
        for sym, sl in enumerate(lengths):
            if sl == L:
                rev = int(f"{code:0{L}b}"[::-1], 2)
                for hi in range(0, 1 << maxlen, 1 << L):
                    fast[rev | hi] = sym << 4 | L
                code += 1
        code <<= 1
    return (fast, maxlen)


def deflate_tokens(raw: bytes) -> list:
    """Token-level inflate of a raw deflate stream: ints are literals, tuples are (length, distance)."""
    raw = bytes(raw) + b"\0" * 16
    buf = nb = bp = 0     # bit buffer, bits held, next byte to load
    out_len = 0
    toks = []
    app = toks.append

    def bits(k):
        nonlocal buf, nb, bp
        if nb < k:
            buf |= int.from_bytes(raw[bp:bp + 6], "little") << nb
            bp += 6
            nb += 48
        v = buf & ((1 << k) - 1)
        buf >>= k
        nb -= k
        return v

    def sym(tab):
        nonlocal buf, nb, bp
        fast, m = tab
        if nb < m:
            buf |= int.from_bytes(raw[bp:bp + 6], "little") << nb
            bp += 6
            nb += 48
        e = fast[buf & ((1 << m) - 1)]
        if e < 0:
            raise ValueError("bad deflate code")
        k = e & 0xF
        buf >>= k
        nb -= k
        return e >> 4

    def align_byte():
        nonlocal buf, nb, bp
        drop = nb & 7
        buf >>= drop
        nb -= drop
        # rewind whole buffered bytes so stored data is read straight from `raw`
        bp -= nb >> 3
        buf = nb = 0

    fixed = None
    while True:
        final, btype = bits(1), bits(2)
        if btype == 0:
            align_byte()
            n = raw[bp] | raw[bp + 1] << 8
            toks.extend(raw[bp + 4:bp + 4 + n])
            bp += 4 + n
            out_len += n
        else:
            if btype == 1:
                if fixed is None:
                    fixed = (_inflate_table([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8), _inflate_table([5] * 30))
                lit, dist = fixed
            elif btype == 2:
                hlit, hdist, hclen = bits(5) + 257, bits(5) + 1, bits(4) + 4
                cl = [0] * 19
                for i in range(hclen):
                    cl[_CL_ORDER[i]] = bits(3)
                clt = _inflate_table(cl)
                lens = []
                while len(lens) < hlit + hdist:
                    s = sym(clt)
                    if s < 16:
                        lens.append(s)
                    elif s == 16:
                        lens += [lens[-1]] * (3 + bits(2))
                    elif s == 17:
                        lens += [0] * (3 + bits(3))
                    else:
                        lens += [0] * (11 + bits(7))
                lit, dist = _inflate_table(lens[:hlit]), _inflate_table(lens[hlit:])
            else:
                raise ValueError("deflate block type 3")
            while True:
                s = sym(lit)
                if s < 256:
                    app(s)
                    out_len += 1
                    continue
                if s == 256:
                    break
                i = s - 257
                length = _D_LBASE[i] + (bits(LEN_EXTRA[i]) if LEN_EXTRA[i] else 0)
                d = sym(dist)
                back = _D_DBASE[d] + (bits(DIST_EXTRA[d]) if DIST_EXTRA[d] else 0)
                app((length, back))
                out_len += length
        if final:
            return toks


# ----------------------------------------------------------------------------------------- Huffman build
def huffman_lengths(freqs: list[int], limit: int) -> list[int]:
    """Code lengths (complete code, <= limit) for the used symbols; at least two symbols get a code."""
    f = list(freqs)
    used = [i for i, v in enumerate(f) if v]
    while len(used) < 2:
        extra = next(i for i in range(len(f)) if not f[i])
        f[extra] = 1
        used.append(extra)
    while True:
        heap = [(f[i], i, (i,)) for i in used]
        heapq.heapify(heap)
        depth = dict.fromkeys(used, 0)
        tie = len(f)
        while len(heap) > 1:
            a, _, sa = heapq.heappop(heap)
            b, _, sb = heapq.heappop(heap)
            for s in sa + sb:
                depth[s] += 1
            heapq.heappush(heap, (a + b, tie, sa + sb))
            tie += 1
        if max(depth.values()) <= limit:
            out = [0] * len(f)
            for s, d in depth.items():
                out[s] = d
            return out
        f = [(v >> 1) | 1 if v else 0 for v in f]


def canonical_codes(lengths: list[int]) -> list[tuple[int, int]]:
    """(bit-reversed code, length) per symbol, deflate canonical order (as `nightfire_edl._build`)."""
    codes = [(0, 0)] * len(lengths)
    code = 0
    for L in range(1, 16):
        for sym, sl in enumerate(lengths):
            if sl == L:
                codes[sym] = (int(f"{code:0{L}b}"[::-1], 2), L)
                code += 1
        code <<= 1
    return codes


def _len_code(n: int) -> int:
    for i in range(len(_D_LBASE) - 1, -1, -1):
        if n >= _D_LBASE[i] and (i != 27 or n < 258):
            return i
    raise ValueError(n)


def _dist_code(d: int) -> int:
    for i in range(len(_D_DBASE) - 1, -1, -1):
        if d >= _D_DBASE[i]:
            return i
    raise ValueError(d)


_LCODE = [0] * 3 + [_len_code(n) for n in range(3, 259)]


class _BitWriter:
    """LSB-first bits into big-endian u32 words (the inverse of `nightfire_edl._Bits`)."""

    def __init__(self):
        self.words = array("I")
        self.acc = 0
        self.n = 0

    def put(self, v: int, k: int):
        self.acc |= v << self.n
        self.n += k
        if self.n >= 32:
            self.words.append(self.acc & 0xFFFFFFFF)
            self.acc >>= 32
            self.n -= 32

    def bytes(self) -> bytes:
        w = array("I", self.words)
        if self.n:
            w.append(self.acc & 0xFFFFFFFF)
        if struct.pack("=I", 1) == struct.pack("<I", 1):
            w.byteswap()
        return w.tobytes()


# ----------------------------------------------------------------------------------------- EDL method 1
def compress_method1(data: bytes, level: int = 9, block_input: int = BLOCK_INPUT) -> bytes:
    """Encode `data` as an EDL method-1 file ('EDL' + 0x81, BE packed/unpacked sizes)."""
    co = zlib.compressobj(level, zlib.DEFLATED, -15, 9, zlib.Z_DEFAULT_STRATEGY)
    toks = deflate_tokens(co.compress(data) + co.flush())
    blocks, cur, size = [], [], 0
    for t in toks:
        cur.append(t)
        size += 1 if type(t) is int else t[0]
        if size >= block_input:
            blocks.append(cur)
            cur, size = [], 0
    if cur or not blocks:
        blocks.append(cur)
    bw = _BitWriter()
    put = bw.put
    run_len = 0
    for bi, blk in enumerate(blocks):
        lf, df = [0] * 286, [0] * 30
        lf[256] = 1
        for t in blk:
            if type(t) is int:
                lf[t] += 1
            else:
                lf[257 + _LCODE[t[0]]] += 1
                df[_dist_code(t[1])] += 1
        ll, dl = huffman_lengths(lf, LIT_LIMIT), huffman_lengths(df, DIST_LIMIT)
        put(1, 1)
        for lens in (ll, dl):
            n = max(i for i, L in enumerate(lens) if L) + 1
            put(n, 9)
            for L in lens[:n]:
                if L == run_len:
                    put(0, 1)
                else:
                    put(1, 1)
                    put(L, 4)
                    run_len = L
        lc, dc = canonical_codes(ll), canonical_codes(dl)
        for t in blk:
            if type(t) is int:
                put(*lc[t])
            else:
                length, back = t
                i = _LCODE[length]
                put(*lc[257 + i])
                if LEN_EXTRA[i]:
                    put(length - _D_LBASE[i], LEN_EXTRA[i])
                d = _dist_code(back)
                put(*dc[d])
                if DIST_EXTRA[d]:
                    put(back - _D_DBASE[d], DIST_EXTRA[d])
        put(*lc[256])
        put(1 if bi == len(blocks) - 1 else 0, 1)
    body = bw.bytes()
    return b"EDL\x81" + struct.pack(">II", 12 + len(body), len(data)) + body


def encode_level(data: bytes) -> bytes:
    """Method-1 EDL whose decode (by the reconstructed game decoder) is byte-identical to `data`."""
    edl = compress_method1(data)
    if decompress(edl) != data:
        raise ValueError("EDL re-encode does not decode back to the input")
    return edl


# ----------------------------------------------------------------------------------------- level edits
def entry(level: bytes, name: str) -> dict:
    for e in pack_index(level)["entries"]:
        if e["name"].lower() == name.lower():
            return e
    raise KeyError(name)


def object_texture(level: bytes, obj: str, tex: str) -> dict:
    from .nightfire_model import object_textures
    e = entry(level, obj)
    payload = level[e["offset"]:e["offset"] + e["size"]]
    for t in object_textures(payload):
        if t["name"] == tex:
            if t["data_offset"] is None:
                raise ValueError(f"{obj}/{tex} is a shared 'DT' reference without texels")
            return {**t, "abs": e["offset"] + t["data_offset"], "object": obj}
    raise KeyError(f"{obj}/{tex}")


def repack(level: bytes, replace: dict[str, bytes] | None = None) -> bytes:
    """Rebuild a hash pack from its table: header, table (u32 LE sizes rewritten), payloads in table order.

    With no replacements the result is byte-identical to the input (the no-op roundtrip); a replacement may
    change a payload's size, which only moves later payloads (entries carry no absolute offsets).
    """
    replace = {k.lower(): v for k, v in (replace or {}).items()}
    idx = pack_index(level)
    table = bytearray(level[0x20:0x20 + idx["table"]])
    p, payloads = 0, []
    for e in idx["entries"]:
        new = replace.pop(e["name"].lower(), None)
        body = level[e["offset"]:e["offset"] + e["size"]] if new is None else bytes(new)
        struct.pack_into("<I", table, p, len(body))
        p = table.index(b"\0", p + 5) + 1
        payloads.append(body)
    if replace:
        raise KeyError(f"not in pack: {sorted(replace)}")
    out = level[:0x20] + bytes(table) + b"".join(payloads)
    pack_index(out)
    return out


def swap_texture(level: bytes, dst: tuple[str, str], src: tuple[str, str] | bytes,
                 all_copies: bool = True) -> tuple[bytes, dict]:
    """Overwrite the GX mip chain of texture dst=(object, name) with src (object, name) or raw GX bytes.

    The donor must have the same byte size (same format/size/mips -> same layout); nothing else moves.
    With all_copies, every other identical copy of the original texels in the level is replaced too
    (variant objects of the same character share textures).
    """
    d = object_texture(level, *dst)
    old = level[d["abs"]:d["abs"] + d["size"]]
    if isinstance(src, (bytes, bytearray)):
        new, s = bytes(src), None
    else:
        s = object_texture(level, *src)
        if (s["gx_format"], s["width"], s["height"], s["mips"]) != (d["gx_format"], d["width"], d["height"], d["mips"]):
            raise ValueError("donor texture format/size/mips differ from the target")
        new = level[s["abs"]:s["abs"] + s["size"]]
    if len(new) != len(old):
        raise ValueError(f"donor texels {len(new)} B != target {len(old)} B")
    out = bytearray(level)
    hits = [d["abs"]]
    if all_copies:
        o = level.find(old)
        hits = []
        while o >= 0:
            hits.append(o)
            o = level.find(old, o + 1)
    for o in hits:
        out[o:o + len(old)] = new
    pack_index(bytes(out))  # table and tiling must still hold
    return bytes(out), {"target": f"{dst[0]}/{dst[1]}", "donor": src if s is None else f"{src[0]}/{src[1]}",
                        "size": len(old), "copies": hits, "old_sha256": hashlib.sha256(old).hexdigest(),
                        "new_sha256": hashlib.sha256(new).hexdigest()}


# ----------------------------------------------------------------------------------------- ISO rebuild
def fst_files(fh) -> list[dict]:
    """FST file entries of a GC disc image: index, path, offset, size, entry position in the image."""
    fh.seek(0x424)
    fo, fs = struct.unpack(">II", fh.read(8))
    fh.seek(fo)
    fst = fh.read(fs)
    n = struct.unpack_from(">I", fst, 8)[0]
    names = fst[n * 12:]
    out, stack = [], [(0, n, "")]
    for i in range(1, n):
        w, a, b = struct.unpack_from(">III", fst, i * 12)
        while i >= stack[-1][1]:
            stack.pop()
        nm = names[w & 0xFFFFFF:names.index(b"\0", w & 0xFFFFFF)].decode("latin-1")
        p = stack[-1][2] + nm
        if w >> 24:
            stack.append((i, b, p + "/"))
        else:
            out.append({"index": i, "path": p, "offset": a, "size": b, "entry_pos": fo + i * 12})
    return out


def build_mod_iso(src_iso: Path, out_iso: Path, path: str, data: bytes, align: int = FILE_ALIGN) -> dict:
    """Copy src_iso to out_iso and replace one FST file; relocates it to the free tail when it outgrows its extent."""
    src_iso, out_iso = Path(src_iso), Path(out_iso)
    if src_iso.resolve() == out_iso.resolve():
        raise ValueError("refusing to modify the source image in place")
    with open(src_iso, "rb") as fh:
        files = fst_files(fh)
    tgt = next(f for f in files if f["path"].lower() == path.lower())
    limit = os_size(src_iso)  # a full GC image is GC_DISC_SIZE; files may not grow the image
    starts = sorted(f["offset"] for f in files if f["offset"] > tgt["offset"])
    extent = (starts[0] if starts else limit) - tgt["offset"]
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_iso, out_iso)
    with open(out_iso, "r+b") as fh:
        if len(data) <= extent:
            off = tgt["offset"]
            fh.seek(off)
            fh.write(data + b"\0" * (tgt["size"] - len(data) if tgt["size"] > len(data) else 0))
            mode = "in_place"
        else:
            end = max(f["offset"] + f["size"] for f in files)
            off = -(-end // align) * align
            if off + len(data) > limit:
                raise ValueError(f"no room on the disc for {len(data)} B at {off:#x}")
            fh.seek(off)
            fh.write(data)
            mode = "relocated"
        fh.seek(tgt["entry_pos"] + 4)
        fh.write(struct.pack(">II", off, len(data)))
    with open(out_iso, "rb") as fh:
        after = fst_files(fh)
        new = next(f for f in after if f["index"] == tgt["index"])
        fh.seek(new["offset"])
        back = fh.read(new["size"])
    if back != data:
        raise ValueError("rebuilt image does not return the written file")
    spans = sorted((f["offset"], f["offset"] + f["size"], f["path"]) for f in after if f["size"])
    for (a0, a1, pa), (b0, b1, pb) in zip(spans, spans[1:]):
        if b0 < a1:
            raise ValueError(f"FST overlap {pa} / {pb}")
    if (len(after) != len(files) or os_size(out_iso) != os_size(src_iso)
            or any((x["offset"], x["size"]) != (y["offset"], y["size"]) for x, y in zip(files, after)
                   if x["index"] != tgt["index"])):
        raise ValueError("FST changed outside the replaced entry")
    return {"path": tgt["path"], "mode": mode, "old_offset": tgt["offset"], "old_size": tgt["size"],
            "extent": extent, "offset": off, "size": len(data), "fst_index": tgt["index"]}


def os_size(p: Path) -> int:
    return Path(p).stat().st_size


def read_disc_file(iso: Path, path: str) -> bytes:
    with open(iso, "rb") as fh:
        f = next(f for f in fst_files(fh) if f["path"].lower() == path.lower())
        fh.seek(f["offset"])
        return fh.read(f["size"])


def main(argv=None) -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Rebuild a Nightfire GC level EDL (optionally with a texture swap) into a mod ISO")
    ap.add_argument("iso", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--level", default="07000001")
    ap.add_argument("--swap", nargs=4, metavar=("DST_OBJ", "DST_TEX", "SRC_OBJ", "SRC_TEX"))
    a = ap.parse_args(argv)
    path = f"gc/{a.level}.bin"
    orig = read_disc_file(a.iso, path)
    level = decompress(orig)
    rep = {"level": path, "orig_edl_sha256": hashlib.sha256(orig).hexdigest(), "orig_edl_size": len(orig),
           "level_sha256": hashlib.sha256(level).hexdigest(), "level_size": len(level), "header": header(orig)}
    if a.swap:
        level, rep["swap"] = swap_texture(level, (a.swap[0], a.swap[1]), (a.swap[2], a.swap[3]))
        rep["mod_level_sha256"] = hashlib.sha256(level).hexdigest()
    edl = encode_level(level)
    rep["edl_sha256"], rep["edl_size"] = hashlib.sha256(edl).hexdigest(), len(edl)
    rep["iso"] = build_mod_iso(a.iso, a.out, path, edl)
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
