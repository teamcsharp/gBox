# Turok: Dinosaur Hunter (N64, NTUE Rev B) — cart inventory + RNC decoders.
#
# Acclaim London engine ("tengine"). The cartridge holds ONE tree of
# CIndexedSet collections rooted at ROM offset 0x1F00 (NTUE Rev B):
#
#   CIndexedSet = { u32 BE block_count, u32 BE offsets[count+1] }
#   block i spans base + offsets[i] .. base + offsets[i+1]
#   (offsets relative to the indexed set's own base; tengine/cart.c).
#
# Root has 11 collections (tengine/cartdir.h):
#   0 GraphicObjects   674 objects, each an indexed set of 4
#                        (ObjectInfo=2, Geometry=2, Anims=7, StaticEvents)
#   1 ObjectAttributes RNC-packed
#   2 ObjectTypes      raw {u32 sub=2, u32 nObjects, u16 animTypes[]}
#   3 TextureSets      1033 sets, each an RNC-packed 3-block indexed set
#                        (format, bitmaps, palettes)
#   4 ParticleEffects  RNC-packed
#   5 SoundEffects     RNC-packed
#   6 Levels           51 levels x 6
#   7 PersistantCounts 3
#   8 WarpDests        2
#   9 Binaries         30
#  10 BinaryTypes      raw {u32 sub=4, u32 n, u32 types[]}
#
# Collection payloads and per-object/per-level blocks are compressed with
# Rob Northen Compression (Propack) methods 1 and 2.  Decoders follow the
# RNC format spec; every decode is verified against the header CRC-16
# (poly 0xA001 reflected, seed 0), so a wrong stream cannot slip through.
#
# Method 1: 16-bit LE bit words, low bit first.  Body = 2 flag bits, then
# chunks: 3 Huffman tables (u5 symbol count <= 16, u4 code length per
# symbol), u16 subchunk count, then per subchunk a literal-run value from
# table 1 (0 = none) and — except the chunk's last — a distance (table 2,
# +1) and length (table 3, +2).  Symbol s < 2 is the value s; s >= 2 takes
# s-1 extra bits: value = 2^(s-1) | extra.  Literal bytes come straight
# from the byte stream; the bit look-ahead is re-synced after each run.
#
# Method 2: fixed codes, one byte at a time, high bit first:
#   0            literal byte
#   10 ab        match len 4+a (b=0) / len 6+2a+c (b=1); len 9 = raw run:
#                u4 n, then n*4+12 raw bytes
#   110          match len 2, distance = byte + 1
#   1110         match len 3
#   1111 byte    byte != 0: match len byte+8; byte == 0: end of chunk,
#                then one bit (1 = more chunks follow)
#   distances for len >= 3: prefix-coded high nibble, then low byte, + 1
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

CART_ROOT_OFFSET = 0x1F00  # NTUE Rev B (GoodN64 V1.2)
CART_ROOT_NAMES = [
    "GraphicObjects", "ObjectAttributes", "ObjectTypes", "TextureSets",
    "ParticleEffects", "SoundEffects", "Levels", "PersistantCounts",
    "WarpDests", "Binaries", "BinaryTypes",
]
GRAPHOBJ_NAMES = ["ObjectInfo", "Geometry", "Anims", "StaticEvents"]
TEXSET_NAMES = ["format", "bitmaps", "palettes"]
LEVEL_NAMES = ["level", "collision", "instances", "gridBounds",
               "gridSections", "skyTextureSet"]
TEXTURE_FORMATS = {0: "CI8_RGBA", 1: "CI4_RGBA", 2: "32_RGBA", 3: "CI4_IA",
                   4: "MM16RGBA"}


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc & 0xFFFF


class _Source:
    """Shared byte position for bit words and literal copies."""

    __slots__ = ("d", "pos", "end")

    def __init__(self, data: bytes, end: int | None = None):
        self.d = data
        self.pos = 0
        self.end = len(data) if end is None else min(end, len(data))

    def peek(self, off: int) -> int:
        at = self.pos + off
        return self.d[at] if at < self.end else 0

    def take(self, n: int) -> bytes:
        if self.pos + n > self.end:
            raise ValueError("raw bytes run past the packed size")
        b = self.d[self.pos: self.pos + n]
        self.pos += n
        return b


# ---------------------------------------------------------------------------
# Method 1
# ---------------------------------------------------------------------------
class _Bits1:
    __slots__ = ("s", "buf", "cnt")

    def __init__(self, src: _Source):
        self.s = src
        self.buf = 0
        self.cnt = 0

    def refill(self):
        low = self.s.peek(0)
        high = self.s.peek(1)
        self.s.pos += 2
        self.buf = low | (high << 8) | (self.s.peek(0) << 16) | (self.s.peek(1) << 24)
        self.cnt = 16

    def bits(self, n: int) -> int:
        v = 0
        sh = 0
        while n:
            if not self.cnt:
                self.refill()
            t = min(n, self.cnt)
            v |= (self.buf & ((1 << t) - 1)) << sh
            self.buf >>= t
            self.cnt -= t
            sh += t
            n -= t
        return v

    def peek(self, n: int) -> int:
        return self.buf & ((1 << n) - 1)

    def resync(self):
        ahead = self.s.peek(0) | (self.s.peek(1) << 8) | (self.s.peek(2) << 16)
        kept = self.buf & ((1 << self.cnt) - 1)
        self.buf = ((ahead << self.cnt) | kept) & 0xFFFFFFFF


def _canonical_codes(depths: list[int]) -> list[tuple[int, int]]:
    codes = [(0, 0)] * len(depths)
    nxt = 0
    for d in range(1, 16):
        for s, sd in enumerate(depths):
            if sd == d:
                codes[s] = (d, int(f"{nxt:0{d}b}"[::-1], 2))
                nxt += 1
        nxt <<= 1
    return codes


class _Table1:
    __slots__ = ("lookup", "ds")

    def __init__(self, b: _Bits1):
        n = b.bits(5)
        if n > 16:
            raise ValueError(f"table declares {n} symbols")
        depths = [b.bits(4) for _ in range(n)]
        if sum(1 << (15 - d) for d in depths if d) > 1 << 15:
            raise ValueError("code lengths over-subscribe the code space")
        self.lookup = {c: s for s, c in enumerate(_canonical_codes(depths)) if c[0]}
        self.ds = sorted({d for d in depths if d})

    def value(self, b: _Bits1) -> int:
        for d in self.ds:
            s = self.lookup.get((d, b.peek(d)))
            if s is not None:
                b.bits(d)
                if s < 2:
                    return s
                return b.bits(s - 1) | (1 << (s - 1))
        raise ValueError("no table code matches the bit stream")


def _unpack_1(src: _Source, target: int) -> bytes:
    b = _Bits1(src)
    out = bytearray()
    b.bits(1)
    b.bits(1)  # locked / keyed flags (keyed refuses, but stock carts never use it)
    while len(out) < target:
        runs = _Table1(b)
        dists = _Table1(b)
        lens = _Table1(b)
        subchunks = b.bits(16)
        if not subchunks:
            raise ValueError("a chunk declares no subchunks")
        for left in range(subchunks - 1, -1, -1):
            run = runs.value(b)
            if run:
                out += src.take(run)
                b.resync()
            if left:
                dist = dists.value(b) + 1
                length = lens.value(b) + 2
                for _ in range(length):
                    out.append(out[len(out) - dist])
    if len(out) != target:
        raise ValueError(f"size mismatch: {len(out)} != {target}")
    return bytes(out)


# ---------------------------------------------------------------------------
# Method 2
# ---------------------------------------------------------------------------
class _Bits2:
    __slots__ = ("s", "buf", "cnt")

    def __init__(self, src: _Source):
        self.s = src
        self.buf = 0
        self.cnt = 0

    def bit(self) -> int:
        if not self.cnt:
            self.buf = self.s.take(1)[0]
            self.cnt = 8
        self.cnt -= 1
        return (self.buf >> self.cnt) & 1

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            v = (v << 1) | self.bit()
        return v


def _distance_2(b: _Bits2, src: _Source) -> int:
    high = 0
    if b.bit():
        high = b.bit()
        if b.bit():
            high = ((high << 1) | b.bit()) | 4
            if not b.bit():
                high = (high << 1) | b.bit()
        elif not high:
            high = b.bit() + 2
    return ((high << 8) | src.take(1)[0]) + 1


def _unpack_2(src: _Source, target: int) -> bytes:
    b = _Bits2(src)
    out = bytearray()
    b.bit()
    b.bit()  # flags
    while len(out) < target:
        while True:
            if not b.bit():
                out += src.take(1)
                continue
            if b.bit():
                if b.bit():
                    if b.bit():
                        length = src.take(1)[0] + 8
                        if length == 8:
                            b.bit()  # more chunks follow; the size decides
                            break
                    else:
                        length = 3
                    dist = _distance_2(b, src)
                else:
                    length = 2
                    dist = src.take(1)[0] + 1
            else:
                length = b.bit() + 4
                if b.bit():
                    length = ((length - 1) << 1) + b.bit()
                if length == 9:
                    run = (b.bits(4) << 2) + 12
                    out += src.take(run)
                    continue
                dist = _distance_2(b, src)
            for _ in range(length):
                out.append(out[len(out) - dist])
    if len(out) != target:
        raise ValueError(f"size mismatch: {len(out)} != {target}")
    return bytes(out)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def decode_rnc(blob: bytes) -> bytes:
    if len(blob) < 18 or blob[:3] != b"RNC":
        raise ValueError("no RNC magic")
    method = blob[3]
    if method not in (1, 2):
        raise ValueError(f"unknown method {method}")
    target = struct.unpack_from(">I", blob, 4)[0]
    packed = struct.unpack_from(">I", blob, 8)[0]
    crc_want = struct.unpack_from(">H", blob, 12)[0]
    src = _Source(blob[18: 18 + packed])
    out = _unpack_1(src, target) if method == 1 else _unpack_2(src, target)
    if crc16(out) != crc_want:
        raise ValueError("unpacked CRC mismatch")
    return out


def rnc_info(blob: bytes) -> dict:
    return {
        "method": blob[3],
        "unpacked": struct.unpack_from(">I", blob, 4)[0],
        "packed": struct.unpack_from(">I", blob, 8)[0],
        "crc_unpacked": struct.unpack_from(">H", blob, 12)[0],
        "crc_packed": struct.unpack_from(">H", blob, 14)[0],
    }


# ---------------------------------------------------------------------------
# CIndexedSet tree
# ---------------------------------------------------------------------------
def parse_indexed(data: bytes, base: int) -> list[tuple[int, int]] | None:
    """Return [(rel_off, size)] for each block, or None if not an indexed set."""
    if base + 4 > len(data):
        return None
    n = struct.unpack_from(">I", data, base)[0]
    if not (0 < n < 65536) or base + 4 + 4 * (n + 1) > len(data):
        return None
    offs = struct.unpack_from(f">{n + 1}I", data, base + 4)
    if offs[0] < 8 or any(offs[i] >= offs[i + 1] for i in range(n)):
        return None
    if base + offs[-1] > len(data):
        return None
    return [(offs[i], offs[i + 1] - offs[i]) for i in range(n)]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------
def inventory(rom: bytes) -> dict:
    root = parse_indexed(rom, CART_ROOT_OFFSET)
    if root is None:
        raise ValueError("no cart root at 0x1F00")
    if len(root) != 11:
        raise ValueError(f"root has {len(root)} blocks, want 11")

    colls = {}
    for name, (rel, size) in zip(CART_ROOT_NAMES, root):
        base = CART_ROOT_OFFSET + rel
        head = rom[base: base + 8]
        is_rnc = head[:4] in (b"RNC\x01", b"RNC\x02")
        entry = {"rom": base, "size": size, "head": head[:4].hex(), "rnc": is_rnc}
        if is_rnc:
            blob = rom[base: base + size]
            entry.update(rnc_info(blob))
            try:
                out = decode_rnc(blob)
                entry["crc_ok"] = True
                child = parse_indexed(out, 0)
                entry["child_blocks"] = len(child) if child else None
            except Exception as e:
                entry["crc_ok"] = False
                entry["error"] = str(e)
        else:
            parsed = parse_indexed(rom, base)
            entry["blocks"] = len(parsed) if parsed else None
        colls[name] = entry

    # ObjectTypes: raw {u32 sub=2, u32 nObjects, u16 animTypes[nObjects]}
    ot_base = CART_ROOT_OFFSET + root[2][0]
    ot_n = struct.unpack_from(">I", rom, ot_base + 4)[0]
    colls["ObjectTypes"]["raw_table"] = {"nObjects": ot_n, "u16 animTypes": ot_n}

    # BinaryTypes: raw {u32 sub=4, u32 n=30, u32 types[n]}
    bt_base = CART_ROOT_OFFSET + root[10][0]
    bt_n = struct.unpack_from(">I", rom, bt_base + 4)[0]
    bt_vals = struct.unpack_from(f">{bt_n}I", rom, bt_base + 8)
    colls["BinaryTypes"]["raw_table"] = {"n": bt_n, "types": list(bt_vals)}

    # GraphicObjects: 674 objects each an indexed set of 4
    go_base = CART_ROOT_OFFSET + root[0][0]
    go_blocks = parse_indexed(rom, go_base) or []
    objs = []
    for i, (rel, size) in enumerate(go_blocks):
        ob = parse_indexed(rom, go_base + rel)
        if ob is None or len(ob) < 4:
            objs.append({"i": i, "bad": True})
            continue
        blocks = {GRAPHOBJ_NAMES[j]: {"rel": r, "size": s}
                  for j, (r, s) in enumerate(ob)}
        objs.append({"i": i, "rom": go_base + rel, **blocks})
    n_geom_ok = sum(1 for o in objs if "bad" not in o)

    # TextureSets: each set is RNC-packed and holds a 3-block indexed set
    ts_base = CART_ROOT_OFFSET + root[3][0]
    ts_blocks = parse_indexed(rom, ts_base) or []
    texsets = []
    fmt_counts = {}
    crc_fail = 0
    for i, (rel, size) in enumerate(ts_blocks):
        blob = rom[ts_base + rel: ts_base + rel + size]
        ob = None
        if blob[:4] in (b"RNC\x01", b"RNC\x02"):
            try:
                ob = parse_indexed(decode_rnc(blob), 0)
            except Exception:
                crc_fail += 1
        if ob is None or len(ob) < 3:
            texsets.append({"i": i, "bad": True})
            continue
        dec = decode_rnc(blob)
        fmt_blob = dec[ob[0][0]: ob[0][0] + ob[0][1]]
        fmt = fmt_blob[0] if len(fmt_blob) >= 1 else None
        name = TEXTURE_FORMATS.get(fmt, f"?{fmt}") if fmt is not None else "unknown"
        fmt_counts[name] = fmt_counts.get(name, 0) + 1
        texsets.append({"i": i, "size": size, "format": name,
                        "bitmaps": ob[1][1], "palettes": ob[2][1]})
    n_ts_ok = sum(1 for t in texsets if "bad" not in t)

    # Levels: 51 x 6
    lv_base = CART_ROOT_OFFSET + root[6][0]
    lv_blocks = parse_indexed(rom, lv_base) or []
    levels = []
    for i, (rel, size) in enumerate(lv_blocks):
        ob = parse_indexed(rom, lv_base + rel)
        if ob is None or len(ob) < 6:
            levels.append({"i": i, "bad": True})
            continue
        levels.append({"i": i, "rom": lv_base + rel, "size": size,
                       **{LEVEL_NAMES[j]: {"rel": r, "size": s}
                          for j, (r, s) in enumerate(ob)}})
    n_lv_ok = sum(1 for l in levels if "bad" not in l)

    # RNC census across whole ROM (magic-anchored)
    census = {}
    for i in range(len(rom) - 4):
        if rom[i: i + 3] == b"RNC":
            census.setdefault(rom[i + 3], []).append(i)
    rnc_stats = {str(m): len(v) for m, v in census.items()}

    # decompress-verify a sample of per-object blocks (first 24 objects)
    sample = []
    for o in objs[:24]:
        if "bad" in o:
            continue
        obase = o["rom"]
        rec = {"i": o["i"]}
        for j, key in enumerate(GRAPHOBJ_NAMES):
            b = o[key]
            blob = rom[obase + b["rel"]: obase + b["rel"] + b["size"]]
            if blob[:4] in (b"RNC\x01", b"RNC\x02"):
                try:
                    dec = decode_rnc(blob)
                    rec[key] = f"RNC{blob[3]} ok {b['size']}->{len(dec)}"
                except Exception as e:
                    rec[key] = f"RNC{blob[3]} FAIL {e}"
            else:
                rec[key] = f"raw {b['size']}"
        sample.append(rec)

    return {
        "cart_root": CART_ROOT_OFFSET,
        "collections": colls,
        "graphic_objects": {"total": len(objs), "valid": n_geom_ok,
                            "objects": objs},
        "texture_sets": {"total": len(texsets), "valid": n_ts_ok,
                         "crc_failures": crc_fail,
                         "format_counts": fmt_counts,
                         "sets": texsets[:8]},
        "levels": {"total": len(levels), "valid": n_lv_ok,
                   "levels": levels[:8]},
        "rnc_census": rnc_stats,
        "decompress_sample_objects": sample,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src", help="ROM path (.z64/.n64/.v64 or the owned .zip)")
    ap.add_argument("--out", default=None, help="write manifest JSON here")
    args = ap.parse_args(argv)

    from gbox import n64_rom  # handles .zip members and byte order
    raw = n64_rom.read(args.src)
    manifest = {
        "game": "Turok: Dinosaur Hunter",
        "region": "USA", "revision": "Rev B (GoodN64 V1.2)",
        "serial": raw[0x3B: 0x3F].decode("ascii", "replace"),
        "cic": "6102", "save": "cpak",
        "rom_size": len(raw),
        "rom_md5": hashlib.md5(raw).hexdigest(),
        "rom_sha1": hashlib.sha1(raw).hexdigest(),
        "rom_sha256": hashlib.sha256(raw).hexdigest(),
        "boot": {"ipl3": raw[0x40: 0x48].hex(), "entry": "0x80000400",
                 "code_start": 0x1000},
        "container": "CIndexedSet tree, blocks RNC(Propack)-compressed",
        "inventory": inventory(raw),
    }
    if args.out:
        with open(args.out, "w") as f:
            json.dump(manifest, f, indent=1)
        print(f"wrote {args.out}")
    else:
        print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
