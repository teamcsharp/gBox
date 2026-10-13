"""Clay Fighter: Sculptor's Cut (USA, N64) — fighter sprite reader + writer (request #588).

characters op=use character=<sprites entry> game=<Clay Fighter SC> slot=fighter:<name>[:flip] re-draws every frame of
one fighter with a collection sprite donor (a `sprites` entry: sheet + JSON index — a sprite_capture clip, an MVC2 /
Tetris DS set, or another Clay Fighter fighter collected by op=collect) and writes a patched ROM copy (header CRC
recomputed) as a file mod. op=collect lists the 16 fighters as slots and rips each fighter's frames into the
collection as a sprites entry.

Format (reversed from the owned build, sha1 28697FBA...; all verified by decoding every frame of all 16 fighters with
byte-exact consumption of each frame's stored size and alpha-record length):

  CHAR_ROM_START  ROM 0x0AB260 (RAM 0x800AA660): 17 u32 ROM offsets of the fighter blobs, roster index order
                  (gbox.clayfighter_sc.ROSTER: 0 = Bad Mr. Frosty ... 16 = Zappa Boys).
  CHAR_ROM_END    ROM 0x0AB2A4: 17 u32 blob ends. Index 7 (CHAR_HOBO) is a 16-byte "nullchar" stub: at boot
                  (RAM 0x80004780) every "nullchar" slot is pointed at the first real fighter and flagged absent.
  Fighter blob    (loader RAM 0x80003F40):
     +0x00 header, 16 u32 (big-endian):
           h0  = 0x0446 << 16 | frame count (CharDef version 4.70)     h1 = 0x40
           h2  = frame table offset (RAM image)       h3 = palette count (64 colours each)
           h4  = palette offset (RAM image)          h5 = palette end = alpha-record area (+0x68 effect palettes)
           h6  = sound bank ctl ("B1", alBnkfNew) offset (RAM image), 0 = none
           h7  = sound sample table, blob offset       h8 = compressed CharDef, blob offset
           h9  = compressed CharDef size               h10 = chunk count (1)   h11 = palettes the costume hook skips
     +0x40 .. h7   frame bitmaps, contiguous, frame order (ROM; DMA'd per frame into one of 32 frame slots)
     h7 .. h8      sound sample table (ROM)
     h8 .. +h9     MPF compressed CharDef: header {u8 type=0x10 (RLE8), u8 0, u16 12, u32 total, u32 unpacked} + RLE8
  RAM image = the 0x40 header + the unpacked CharDef. Frame table at h2: per frame {u32 bitmap blob offset, u32 bitmap
  size (even), u32 alpha record} where the record is a *file* offset: RAM = rec + 0x40 - h8 (fixed up at load).
  Palettes at h4: h3 x 64 RGBA5551 colours. Alpha records: contiguous, frame order, from h5 + 0x68 up to h6.

  Frame bitmap (decoder RAM 0x80005870, CHARFRAM.C): u8 W, u8 H, u8 X, u8 Y (hotspot: X ~ W/2, Y ~ H-1 = the feet),
  then an LSB-first bit stream of runs over the W*H pixels:
     8 bits c: c&1 -> (c>>1)+1 transparent pixels; else (c>>1)+1 opaque pixels. The first opaque run starting in a
     new row (the decoder's row changes whenever a run ends at or past the row end) is preceded by 8 bits palette
     number P and 3 bits mode m (m >= 5: one more bit, +3). Per pixel, colour = palette P[index]:
       m 0: 6 bits index        m 1/2: 5 bits v, index 2v / 2v+1     m 3/4: 5 bits v, index v / 32+v
       m 5-8: 4 bits v, index 4v+(m-5)                              m 9/10: 4 bits v, index 2v / 32+2v
  Alpha record (same decoder): 4-bit nibbles; nibbles with bit 3 set accumulate a base-8 skip (MSB first), the next
  nibble n sets pixel (t += skip + 1) alpha to 25*(n+1); ends when t >= H * (W rounded up to even).

Writer strategy (write_fighters):
  * every target frame keeps its W, H, hotspot X/Y and table position, so the game's sequences, hit/attack rects,
    move tables and sounds (all in the CharDef, untouched) still line up. Donor frames are dealt over the target
    frames (in order when the donor has at least as many, else cycled), cropped to their opaque box, scaled by one
    common factor (90th-percentile donor height -> target height) and letterboxed into each W x H with the donor's
    bottom-centre on the hotspot; a frame the common scale overflows is shrunk to fit.
  * colours: the palettes the original frames used are re-filled — one 64-colour palette per frame (median cut,
    luminance-ordered so rows land in the 4/5-bit modes), frames grouped onto shared palettes when a fighter has
    more frames than palettes. Palettes no frame used are kept. Partial donor alpha (64..229) becomes alpha records.
  * bitmaps are re-encoded (cheapest mode per row) and the CharDef re-packed (RLE8). When both fit the fighter's own
    ROM space they are written in place; otherwise the whole fighter blob is relocated to space appended to the ROM
    (header, sample table and blob-relative offsets unchanged; new bitmaps after the CharDef) and CHAR_ROM_START /
    CHAR_ROM_END are re-pointed. The ROM grows to the next 4 MiB (16 -> 20 MiB for one fighter).
  * the header CRC pair is recomputed (gbox.romexport.n64_crc; the cart is CIC-6102 and the stored pair FA5A3DFF /
    B4C9CDB9 reproduces with it).
"""
from __future__ import annotations

import json
import math
import re
import shutil
import struct
import time
from pathlib import Path

import numpy as np

from . import clayfighter_sc as SC

GAME_ID = "f87ec3e2f6b266a1"
GAME_IDS = {GAME_ID: "Clay Fighter: Sculptor's Cut (USA)"}
TITLE = "Clay Fighter - Sculptor's Cut (USA)"
CIC = "6102"

CHAR_ROM_START = 0x0AB260
CHAR_ROM_END = 0x0AB2A4
COUNT = SC.CHARACTER_COUNT
HEADER = 0x40
VERSION = 0x0446
COMP_RLE8 = 0x10
EFFECT_PALETTES = 0x68                      # h5 .. first alpha record: 0x2F marker + small 16-colour palettes (kept)
GROW = 0x400000                             # the ROM grows in 4 MiB steps when a blob is relocated
MODES = {1: (1, 0), 2: (1, 1), 3: (0, 0), 4: (0, 0x20), 5: (2, 0), 6: (2, 1), 7: (2, 2), 8: (2, 3),
         9: (1, 0), 10: (1, 0x20)}           # mode -> (shift, base): index = base + (v << shift)
BITS = {0: 6, 1: 5, 2: 5, 3: 5, 4: 5, 5: 4, 6: 4, 7: 4, 8: 4, 9: 4, 10: 4}


# ------------------------------------------------------------------------------------------------ roster / slots

def fighters() -> list[dict]:
    """The 17 roster entries; index 7 (Hobo Cop) has no data in this build (a "nullchar" stub)."""
    out = []
    for i, (code, disp) in enumerate(SC.ROSTER):
        key = code[5:].lower()
        name = "Bad Mr. Frosty" if key == "bmf" else disp
        out.append({"index": i, "code": code, "key": key, "name": name, "slot": f"fighter:{key}",
                    "slug": f"clayfighter_{key}", "present": code != "CHAR_HOBO"})
    return out


def cast_slots() -> list[dict]:
    """characters op=collect "slots": one fighter:<name> per playable fighter."""
    return [{"slot": f["slot"], "name": f["name"], "kind": "fighter", "writer": "gbox.clayfighter_swap"}
            for f in fighters() if f["present"]]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def find_fighter(slot: str) -> tuple[dict, bool]:
    """slot "fighter:<code | name>[:flip]" (or "player" = Bad Mr. Frosty, the default player-1 cursor) -> (fighter,
    mirror the donor?)."""
    s = (slot or "player").strip()
    flip = s.lower().endswith(":flip")
    if flip:
        s = s[:-5]
    if s.lower() in ("player", "fighter", ""):
        return fighters()[0], flip
    q = _norm(s.split(":", 1)[1] if s.lower().startswith("fighter:") else s)
    for f in fighters():
        if q in (_norm(f["key"]), _norm(f["name"]), _norm(f["code"]), _norm(f["slug"]), str(f["index"])):
            if not f["present"]:
                raise ValueError(f"{f['name']} has no sprite data in this build (CHAR_HOBO is a nullchar stub)")
            return f, flip
    for f in fighters():
        if f["present"] and q and (q in _norm(f["name"]) or _norm(f["name"]).startswith(q)):
            return f, flip
    raise ValueError(f"no Clay Fighter fighter matches {slot!r}; slots: "
                     + ", ".join(s["slot"] for s in cast_slots()))


# ------------------------------------------------------------------------------------------------ RLE8 (MPF type 0x10)

def rle8_decode(src: bytes, size: int | None = None) -> tuple[bytes, int]:
    """MPF RLE8 (RAM 0x80092434): c = 0xFF end; c & 0x80: next byte x (c & 0x7F) + 1; else c + 1 literal bytes.
    Returns (data, bytes consumed)."""
    out, i = bytearray(), 0
    while True:
        c = src[i]
        i += 1
        if c == 0xFF:
            break
        if c & 0x80:
            out += bytes([src[i]]) * ((c & 0x7F) + 1)
            i += 1
        else:
            out += src[i:i + c + 1]
            i += c + 1
    if size is not None and len(out) != size:
        raise ValueError(f"RLE8 unpacked {len(out)} bytes, header says {size}")
    return bytes(out), i


def rle8_encode(data: bytes) -> bytes:
    """Inverse of rle8_decode: runs of 3+ equal bytes (max 127: 0xFF is the end code), literals up to 128."""
    out, lit, i, n = bytearray(), bytearray(), 0, len(data)

    def flush():
        for k in range(0, len(lit), 128):
            part = lit[k:k + 128]
            out.append(len(part) - 1)
            out.extend(part)
        lit.clear()
    while i < n:
        j = i + 1
        while j < n and data[j] == data[i] and j - i < 127:
            j += 1
        if j - i >= 3:
            flush()
            out += bytes([0x80 | (j - i - 1), data[i]])
            i = j
        else:
            lit.append(data[i])
            i += 1
    flush()
    out.append(0xFF)
    return bytes(out)


def pack_chardef(body: bytes) -> bytes:
    """The MPF_CompressedDataHeader + RLE8 stream as it sits at blob offset h8."""
    s = rle8_encode(body)
    return struct.pack(">BBHII", COMP_RLE8, 0, 12, 12 + len(s), len(body)) + s


def unpack_chardef(comp: bytes) -> bytes:
    t, _z, hs, _total, size = struct.unpack_from(">BBHII", comp)
    if t != COMP_RLE8:
        raise ValueError(f"CharDef compression type 0x{t:02X} (only RLE8 0x10 is used by this build)")
    return rle8_decode(comp[hs:], size)[0]


# ------------------------------------------------------------------------------------------------ bit streams

class BitReader:
    """LSB-first bit reader (the game's mpReadBits order: bit k of a field = bit (pos + k) of the stream)."""

    def __init__(self, b, pos: int = 0):
        self.b, self.pos = b, 8 * pos

    def read(self, n: int) -> int:
        i = self.pos >> 3
        v = (int.from_bytes(self.b[i:i + 3], "little") >> (self.pos & 7)) & ((1 << n) - 1)
        self.pos += n
        return v

    def used(self) -> int:
        return (self.pos + 7) >> 3


class BitWriter:
    def __init__(self):
        self.out, self.acc, self.n = bytearray(), 0, 0

    def write(self, v: int, n: int):
        self.acc |= (v & ((1 << n) - 1)) << self.n
        self.n += n
        while self.n >= 8:
            self.out.append(self.acc & 0xFF)
            self.acc >>= 8
            self.n -= 8

    def bytes(self) -> bytes:
        return bytes(self.out) + (bytes([self.acc]) if self.n else b"")


# ------------------------------------------------------------------------------------------------ frames

def decode_bitmap(bm: bytes) -> dict:
    """A frame bitmap -> {W, H, X, Y, pal: HxW palette numbers (-1 = transparent), idx: HxW colour index, used}."""
    W, H, X, Y = bm[0], bm[1], bm[2], bm[3]
    pal = np.full(W * H, -1, np.int16)
    idx = np.zeros(W * H, np.uint8)
    br = BitReader(bm, 4)
    p, row, left, sel, mode, P = 0, -1, 0, False, 0, 0
    while True:
        while left <= 0:
            row += 1
            if row >= H:
                break
            left += W
            sel = False
        if row >= H:
            break
        c = br.read(8)
        n = (c >> 1) + 1
        left -= n
        if c & 1:
            p += n
            continue
        if not sel:
            P, mode = br.read(8), br.read(3)
            if mode >= 5 and br.read(1):
                mode += 3
            sel = True
        bits = BITS[mode]
        sh, base = MODES.get(mode, (0, 0))
        for _ in range(n):
            v = br.read(bits)
            if p < W * H:
                pal[p], idx[p] = P, (v if mode == 0 else base + (v << sh))
            p += 1
    return {"W": W, "H": H, "X": X, "Y": Y, "pal": pal.reshape(H, W), "idx": idx.reshape(H, W), "used": br.used()}


def decode_alpha(rec: bytes, W: int, H: int) -> tuple[dict[int, int], int]:
    """An alpha record -> ({linear pixel: alpha byte}, bytes consumed)."""
    ar, out = BitReader(rec, 0), {}
    t1, t0 = H * (W + (W & 1)), -1
    while True:
        a = 0
        while True:
            nib = ar.read(4)
            if not nib & 8:
                break
            a = (a << 3) | (nib & 7)
        t0 += 1 + a
        if t0 >= t1:
            break
        out[t0] = 25 * (nib + 1)
    return out, ar.used()


def _row_mode(vals: np.ndarray) -> int:
    """The cheapest mode that can express every colour index of a row (4 bits < 5 bits < 6 bits)."""
    if not len(vals):
        return 0
    lo, hi = int(vals.min()), int(vals.max())
    for m in (5, 6, 7, 8):
        if np.all(vals % 4 == m - 5):
            return m
    if np.all(vals % 2 == 0) and hi < 32:
        return 9
    if np.all(vals % 2 == 0) and lo >= 32:
        return 10
    if hi < 32:
        return 3
    if lo >= 32:
        return 4
    if np.all(vals % 2 == 0):
        return 1
    if np.all(vals % 2 == 1):
        return 2
    return 0


def encode_bitmap(W: int, H: int, X: int, Y: int, idx: np.ndarray, P: int | np.ndarray) -> bytes:
    """Inverse of decode_bitmap. idx: HxW colour indices 0..63, -1 = transparent. P: one palette number, or one per row.
    Opaque runs stay inside their row; transparent runs may cross rows."""
    if not (0 < W < 256 and 0 < H < 256 and 0 <= X < 256 and 0 <= Y < 256):
        raise ValueError(f"frame geometry out of range: {W}x{H} hotspot {X},{Y}")
    idx = np.asarray(idx).reshape(H, W).astype(np.int16)
    if idx.max(initial=-1) > 63:
        raise ValueError("colour index above 63 (palettes hold 64 colours)")
    Ps = np.broadcast_to(np.asarray(P, np.int16), (H,))
    flat = idx.reshape(-1)
    bw = BitWriter()
    for b in (W, H, X, Y):
        bw.write(b, 8)
    modes = [_row_mode(r[r >= 0]) for r in idx]
    p, total, head_row = 0, W * H, -1
    while p < total:
        row = p // W
        if flat[p] < 0:
            q = p
            while q < total and flat[q] < 0 and q - p < 128:
                q += 1
            bw.write(((q - p - 1) << 1) | 1, 8)
            p = q
            continue
        end = min((row + 1) * W, p + 128)
        q = p
        while q < end and flat[q] >= 0:
            q += 1
        bw.write((q - p - 1) << 1, 8)
        m = modes[row]
        if head_row != row:
            bw.write(int(Ps[row]), 8)
            bw.write(m if m < 5 else (m if m < 8 else m - 3), 3)
            if m >= 5:
                bw.write(1 if m >= 8 else 0, 1)
            head_row = row
        sh, base = MODES.get(m, (0, 0))
        for v in flat[p:q]:
            bw.write(int(v) if m == 0 else (int(v) - base) >> sh, BITS[m])
        p = q
    out = bw.bytes()
    return out + (b"\0" if len(out) & 1 else b"")


def encode_alpha(W: int, H: int, alpha: dict[int, int]) -> bytes:
    """Inverse of decode_alpha: {linear pixel: level 0..7 (alpha 25*(level+1))}."""
    bw, prev = BitWriter(), -1

    def skip(s):
        digits = []
        while s:
            digits.append(s & 7)
            s >>= 3
        for d in reversed(digits):
            bw.write(8 | d, 4)
    t1 = H * (W + (W & 1))
    for t in sorted(alpha):
        if not 0 <= t < W * H:
            continue
        skip(t - prev - 1)
        bw.write(int(alpha[t]) & 7, 4)
        prev = t
    skip(t1 - prev - 1)
    bw.write(0, 4)
    return bw.bytes()


def rgba5551(v: int) -> tuple[int, int, int]:
    return (((v >> 11) & 31) * 255 + 15) // 31, (((v >> 6) & 31) * 255 + 15) // 31, (((v >> 1) & 31) * 255 + 15) // 31


def to5551(rgb) -> int:
    r, g, b = (int(round(c * 31 / 255)) for c in rgb[:3])
    return (r << 11) | (g << 6) | (b << 1) | 1


# ------------------------------------------------------------------------------------------------ ROM structure

def blob_table(rom: bytes) -> tuple[list[int], list[int]]:
    return (list(struct.unpack_from(f">{COUNT}I", rom, CHAR_ROM_START)),
            list(struct.unpack_from(f">{COUNT}I", rom, CHAR_ROM_END)))


class Fighter:
    """One fighter blob parsed from a ROM image (read-only view; write_fighters builds new bytes)."""

    def __init__(self, rom: bytes, index: int):
        starts, ends = blob_table(rom)
        self.index, self.base, self.end = index, starts[index], ends[index]
        if rom[self.base:self.base + 8] == b"nullchar":
            raise ValueError(f"fighter {index} ({SC.ROSTER[index][0]}) is a nullchar stub in this ROM")
        self.h = list(struct.unpack_from(">16I", rom, self.base))
        if self.h[0] >> 16 != VERSION or self.h[1] != HEADER:
            raise ValueError(f"fighter {index}: CharDef header 0x{self.h[0]:08X} is not version 4.70")
        self.count = self.h[0] & 0xFFFF
        comp = rom[self.base + self.h[8]:self.base + self.h[8] + self.h[9]]
        self.image = bytearray(rom[self.base:self.base + HEADER] + unpack_chardef(comp))
        self.table = [struct.unpack_from(">III", self.image, self.h[2] + 12 * i) for i in range(self.count)]
        self.rom = rom

    def rec_ram(self, i: int) -> int:
        return self.table[i][2] + HEADER - self.h[8]

    def palettes(self) -> np.ndarray:
        """h3 x 64 RGBA5551 words."""
        n = self.h[3] * 64
        return np.frombuffer(bytes(self.image[self.h[4]:self.h[4] + 2 * n]), ">u2").reshape(self.h[3], 64)

    def bitmap(self, i: int) -> bytes:
        o, sz, _r = self.table[i]
        return self.rom[self.base + o:self.base + o + sz]

    def frame(self, i: int) -> dict:
        d = decode_bitmap(self.bitmap(i))
        d["alpha"], d["rec_used"] = decode_alpha(memoryview(self.image)[self.rec_ram(i):], d["W"], d["H"])
        d["size"] = self.table[i][1]
        return d

    def frames(self) -> list[dict]:
        return [self.frame(i) for i in range(self.count)]

    def rgba(self, d: dict, pals: np.ndarray | None = None) -> np.ndarray:
        """A decoded frame -> HxWx4 uint8 (what the game draws, before its own tinting)."""
        pals = self.palettes() if pals is None else pals
        H, W = d["H"], d["W"]
        out = np.zeros((H, W, 4), np.uint8)
        m = d["pal"] >= 0
        words = pals[np.clip(d["pal"], 0, len(pals) - 1), d["idx"]]
        out[..., 0] = ((words >> 11) & 31) * 255 // 31
        out[..., 1] = ((words >> 6) & 31) * 255 // 31
        out[..., 2] = ((words >> 1) & 31) * 255 // 31
        out[~m] = 0
        a = np.where(m, 255, 0).astype(np.uint8).reshape(-1)
        for t, v in d["alpha"].items():
            if t < a.size and a[t]:
                a[t] = v
        out[..., 3] = a.reshape(H, W)
        return out

    def used_palettes(self, frames: list[dict] | None = None) -> list[int]:
        s = set()
        for d in frames or self.frames():
            s.update(int(v) for v in np.unique(d["pal"]) if v >= 0)
        return sorted(s)


def read_fighter(rom: bytes, index: int) -> dict:
    f = Fighter(rom, index)
    frames = f.frames()
    return {"index": index, "code": SC.ROSTER[index][0], "base": f.base, "header": f.h, "frames": frames,
            "palettes": f.palettes(), "fighter": f}


def validate(rom: bytes) -> dict:
    """Decode every frame of every fighter; a frame passes when its bit stream ends inside its stored (even) size and
    its alpha record ends at the next record."""
    problems, counts = [], {}
    for i in range(COUNT):
        try:
            f = Fighter(rom, i)
        except ValueError as e:
            if "nullchar" in str(e):
                counts[SC.ROSTER[i][0]] = 0
                continue
            problems.append(str(e))
            continue
        recs = [f.rec_ram(k) for k in range(f.count)]
        for k in range(f.count):
            d = f.frame(k)
            if not (d["size"] - 1 <= d["used"] <= d["size"]):
                problems.append(f"{SC.ROSTER[i][0]} frame {k}: bitmap used {d['used']} of {d['size']}")
            nxt = recs[k + 1] if k + 1 < f.count else f.h[6] or len(f.image)
            if recs[k] + d["rec_used"] > nxt:
                problems.append(f"{SC.ROSTER[i][0]} frame {k}: alpha record overruns")
        counts[SC.ROSTER[i][0]] = f.count
    return {"ok": not problems, "problems": problems[:20], "frames": counts}


# ------------------------------------------------------------------------------------------------ donor fitting

def _crop(img: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(img[..., 3] >= 64)
    if not len(ys):
        return img[:1, :1] * 0
    return img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _resize(img: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image
    w, h = max(1, w), max(1, h)
    if img.shape[1] == w and img.shape[0] == h:
        return img
    # premultiplied resampling so transparent pixels' colour never bleeds into edges
    a = img[..., 3:4].astype(np.float32) / 255
    pm = np.concatenate([img[..., :3] * a, img[..., 3:4].astype(np.float32)], 2).astype(np.uint8)
    up = w > img.shape[1] or h > img.shape[0]
    r = np.asarray(Image.fromarray(pm, "RGBA").resize((w, h), Image.Resampling.NEAREST if up else Image.Resampling.BOX))
    r = r.astype(np.float32)
    al = r[..., 3:4] / 255
    rgb = np.where(al > 0, r[..., :3] / np.maximum(al, 1e-6), 0)
    return np.concatenate([np.clip(rgb, 0, 255), r[..., 3:4]], 2).astype(np.uint8)


def deal(n_target: int, n_donor: int) -> list[int]:
    """Which donor frame each target frame gets: in order when the donor has enough, else cycled."""
    if n_donor <= 0:
        raise ValueError("the donor has no frames")
    if n_donor >= n_target:
        return [i * n_donor // n_target for i in range(n_target)]
    return [i % n_donor for i in range(n_target)]


def fit_frames(targets: list[dict], donor: list[np.ndarray], flip: bool = False) -> list[np.ndarray]:
    """Donor RGBA frames -> one RGBA canvas per target frame (W x H, donor bottom-centre on the hotspot)."""
    crops = [_crop(np.asarray(d, np.uint8)) for d in donor]
    if flip:
        crops = [c[:, ::-1] for c in crops]
    th = np.percentile([t["H"] for t in targets], 90)
    dh = np.percentile([c.shape[0] for c in crops], 90)
    scale = float(th) / max(1.0, float(dh))
    out = []
    for t, k in zip(targets, deal(len(targets), len(crops))):
        c = crops[k]
        W, H, X, Y = t["W"], t["H"], t["X"], t["Y"]
        s = min(scale, W / c.shape[1], H / c.shape[0])
        w, h = max(1, min(W, int(round(c.shape[1] * s)))), max(1, min(H, int(round(c.shape[0] * s))))
        r = _resize(c, w, h)
        x0 = int(round(min(max(X, 0), W - 1) - w / 2))
        y0 = min(max(Y, 0), H - 1) + 1 - h
        x0, y0 = min(max(0, x0), W - w), min(max(0, y0), H - h)
        canvas = np.zeros((H, W, 4), np.uint8)
        canvas[y0:y0 + h, x0:x0 + w] = r
        out.append(canvas)
    return out


def quantize(pixels: np.ndarray, n: int = 64) -> np.ndarray:
    """RGB rows (N x 3) -> a luminance-ordered palette of <= n colours (N' x 3 uint8, 5-bit exact)."""
    from PIL import Image
    px = (np.asarray(pixels, np.uint8).reshape(-1, 3) >> 3).astype(np.uint8)
    uniq = np.unique(px, axis=0)
    if len(uniq) <= n:
        pal = uniq
    else:
        side = int(math.ceil(math.sqrt(len(px))))
        buf = np.zeros((side * side, 3), np.uint8)
        buf[:len(px)] = px << 3
        buf[len(px):] = px[0] << 3
        q = Image.fromarray(buf.reshape(side, side, 3), "RGB").quantize(colors=n, method=Image.Quantize.MEDIANCUT,
                                                                          dither=Image.Dither.NONE)
        pal = np.unique(np.asarray(q.getpalette()[:3 * n], np.uint8).reshape(-1, 3) >> 3, axis=0)
    pal = (pal.astype(np.int32) * 255 + 15) // 31
    lum = pal @ np.array([299, 587, 114])
    return pal[np.argsort(lum, kind="stable")].astype(np.uint8)


def nearest(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
    rgb = rgb.reshape(-1, 3).astype(np.int32)
    out = np.empty(len(rgb), np.int16)
    for s in range(0, len(rgb), 4096):
        d = ((rgb[s:s + 4096, None, :] - pal[None].astype(np.int32)) ** 2).sum(2)
        out[s:s + 4096] = d.argmin(1)
    return out


def encode_frames(targets: list[dict], canvases: list[np.ndarray], palette_ids: list[int]) -> dict:
    """Canvases (one per target frame) -> {bitmaps, records, palettes {id: 64 words}, assign}."""
    n, slots = len(canvases), len(palette_ids)
    if slots == 0:
        raise ValueError("no palettes available")
    groups = [list(range(g * n // slots, (g + 1) * n // slots)) for g in range(min(n, slots))] if n > slots \
        else [[i] for i in range(n)]
    bitmaps, records, palettes, assign = [None] * n, [None] * n, {}, [0] * n
    for g, members in enumerate(groups):
        pid = palette_ids[g]
        opaque = [c[..., :3][c[..., 3] >= 64] for c in (canvases[i] for i in members)]
        allpx = np.concatenate(opaque) if any(len(o) for o in opaque) else np.zeros((1, 3), np.uint8)
        pal = quantize(allpx, 64)
        words = [to5551(c) for c in pal] + [to5551(pal[-1])] * (64 - len(pal))
        palettes[pid] = words
        for i in members:
            c, t = canvases[i], targets[i]
            idx = np.full(c.shape[:2], -1, np.int16)
            m = c[..., 3] >= 64
            if m.any():
                idx[m] = nearest(c[..., :3][m], pal)
            bitmaps[i] = encode_bitmap(t["W"], t["H"], t["X"], t["Y"], idx, pid)
            a = c[..., 3].reshape(-1)
            part = np.nonzero((a >= 64) & (a < 230))[0]
            records[i] = encode_alpha(t["W"], t["H"], {int(p): max(0, min(7, int(round(a[p] / 25)) - 1)) for p in part})
            assign[i] = pid
    return {"bitmaps": bitmaps, "records": records, "palettes": palettes, "assign": assign}


# ------------------------------------------------------------------------------------------------ writer

def fix_crc(rom: bytearray, cic: str | None = None) -> tuple[int, int]:
    """Recompute the header CRC pair in place (gbox.romexport.n64_crc); returns it."""
    from .romexport import n64_cic, n64_crc
    try:
        cic = cic or n64_cic(bytes(rom))
    except ValueError:
        cic = CIC                                           # synthetic images carry no boot code; the cart is 6102
    crc = n64_crc(bytes(rom), cic)
    struct.pack_into(">II", rom, 0x10, *crc)
    return crc


def _pack_records(f: Fighter, records: list[bytes], image: bytearray, targets: list[dict]) -> list[int]:
    """Lay the alpha records out in the fighter's record area; returns each record's RAM offset. Records that don't
    fit (partial alpha costs bits) fall back to an empty record (binary alpha)."""
    start = min(f.rec_ram(i) for i in range(f.count))
    limit = f.h[6] if f.h[6] else len(image)
    total = sum(len(r) for r in records)
    if start + total > limit:
        records = [encode_alpha(t["W"], t["H"], {}) for t in targets]
        total = sum(len(r) for r in records)
        if start + total > limit:
            raise ValueError("alpha records do not fit the fighter's record area")
    offs, p = [], start
    image[start:limit] = bytes(limit - start)
    for r in records:
        image[p:p + len(r)] = r
        offs.append(p)
        p += len(r)
    return offs


def write_fighters(rom: bytes, jobs: list[dict], cic: str | None = None) -> tuple[bytes, list[dict]]:
    """jobs: [{"index": fighter index, "frames": [RGBA ndarray per donor frame], "flip": bool}] -> (patched ROM with
    the header CRC recomputed, per-fighter reports). Every target frame keeps its size, hotspot and table slot."""
    out = bytearray(rom)
    reports = []
    for job in jobs:
        f = Fighter(bytes(out), job["index"])
        targets = [{k: d[k] for k in ("W", "H", "X", "Y")} for d in (f.frame(i) for i in range(f.count))]
        frames0 = [f.frame(i) for i in range(f.count)]
        used = f.used_palettes(frames0)
        keep_last = f.h[11]                                # the costume hook skips the last h11 palettes
        order = [p for p in used if p < f.h[3] - keep_last] + [p for p in used if p >= f.h[3] - keep_last]
        canvases = job.get("canvases") or fit_frames(targets, job["frames"], job.get("flip", False))
        enc = encode_frames(targets, canvases, order[:max(1, min(len(order), f.count))])
        image = bytearray(f.image)
        for pid, words in enc["palettes"].items():
            struct.pack_into(">64H", image, f.h[4] + 128 * pid, *words)
        partial = sum(len(r) for r in enc["records"])
        rec_offs = _pack_records(f, enc["records"], image, targets)
        bms = enc["bitmaps"]
        bm_total = sum(len(b) for b in bms)
        starts, ends = blob_table(bytes(out))
        later = sorted(s for s in starts if s > f.base)
        room = (later[0] if later else len(rom)) - f.base - f.h[8]
        # offsets: in place when the bitmaps fit [0x40, h7); else after the CharDef (relocated blob)
        in_bitmaps = bm_total <= f.h[7] - HEADER

        def build_image(bm_offs):
            img = bytearray(image)
            for i in range(f.count):
                struct.pack_into(">III", img, f.h[2] + 12 * i, bm_offs[i], len(bms[i]),
                                 rec_offs[i] - HEADER + f.h[8])
            return img
        if in_bitmaps:
            offs, p = [], HEADER
            for b in bms:
                offs.append(p)
                p += len(b)
            img = build_image(offs)
            comp = pack_chardef(bytes(img[HEADER:]))
            hdr = list(f.h)
            hdr[9] = len(comp)
            if len(comp) <= room:                          # everything fits: write in place
                blob_base = f.base
                out[blob_base:blob_base + HEADER] = struct.pack(">16I", *hdr)
                p = blob_base + HEADER
                for b in bms:
                    out[p:p + len(b)] = b
                    p += len(b)
                out[p:blob_base + f.h[7]] = bytes(blob_base + f.h[7] - p)
                out[blob_base + f.h[8]:blob_base + f.h[8] + len(comp)] = comp
                out[blob_base + f.h[8] + len(comp):blob_base + f.h[8] + room] = bytes(room - len(comp))
                relocated = False
            else:
                relocated = True
        else:
            relocated = True
        if relocated:
            # the whole blob moves to appended space: header + original bitmaps/sample table keep their offsets
            if in_bitmaps:
                bm_offs = offs
            else:
                comp0 = pack_chardef(bytes(build_image([0] * f.count)[HEADER:]))
                p = (f.h[8] + len(comp0) + 12 * f.count + 0x40 + 15) & ~15   # slack: real offsets pack worse than 0s
                bm_offs = []
                for b in bms:
                    bm_offs.append(p)
                    p += len(b)
            img = build_image(bm_offs)
            comp = pack_chardef(bytes(img[HEADER:]))
            if not in_bitmaps and f.h[8] + len(comp) > bm_offs[0]:
                raise ValueError("re-packed CharDef overruns the relocated bitmaps")
            hdr = list(f.h)
            hdr[9] = len(comp)
            size = max(f.h[8] + len(comp), (bm_offs[-1] + len(bms[-1])) if not in_bitmaps else 0)
            blob = bytearray(f.rom[f.base:f.base + f.h[8]]) + comp
            blob += bytes(max(0, size - len(blob)))
            blob[:HEADER] = struct.pack(">16I", *hdr)
            for o, b in zip(bm_offs, bms):
                blob[o:o + len(b)] = b
            blob_base = (len(out) + 15) & ~15
            out += bytes(blob_base - len(out)) + blob
            struct.pack_into(">I", out, CHAR_ROM_START + 4 * job["index"], blob_base)
            struct.pack_into(">I", out, CHAR_ROM_END + 4 * job["index"], blob_base + len(blob))
        reports.append({"fighter": SC.ROSTER[job["index"]][0], "frames": f.count, "palettes": len(enc["palettes"]),
                        "bitmap_bytes": bm_total, "original_bitmap_bytes": f.h[7] - HEADER,
                        "chardef_packed": len(comp), "original_packed": f.h[9], "alpha_record_bytes": partial,
                        "relocated": relocated, "blob": f"0x{(blob_base if relocated else f.base):X}"})
    if len(out) > len(rom):
        out += bytes((-len(out)) % GROW)
    crc = fix_crc(out, cic)
    for r in reports:
        r["crc"] = f"{crc[0]:08X} {crc[1]:08X}"
    return bytes(out), reports


# ------------------------------------------------------------------------------------------------ sprite sheets

def sheet_of(frames: list[np.ndarray], cols: int = 0) -> tuple[np.ndarray, list[list[int]]]:
    """Pack RGBA frames into one sheet; returns (sheet, [x, y, w, h] per frame)."""
    cols = cols or max(1, int(math.ceil(math.sqrt(len(frames)))))
    cw = max(f.shape[1] for f in frames)
    ch = max(f.shape[0] for f in frames)
    rows = int(math.ceil(len(frames) / cols))
    sheet = np.zeros((rows * ch, cols * cw, 4), np.uint8)
    cells = []
    for k, fr in enumerate(frames):
        x, y = (k % cols) * cw, (k // cols) * ch
        sheet[y:y + fr.shape[0], x:x + fr.shape[1]] = fr
        cells.append([x, y, int(fr.shape[1]), int(fr.shape[0])])
    return sheet, cells


def export_fighter(rom: bytes, index: int, out: Path) -> dict:
    """A fighter's frames -> <out>/<slug>_sheet.png + <slug>_sheet.json (index: frames[].sheet [x,y,w,h] + hotspot).
    The sheet is a collection `sprites` entry (and so a donor for any sprite writer)."""
    from PIL import Image
    f = Fighter(rom, index)
    frames = f.frames()
    pals = f.palettes()
    imgs = [f.rgba(d, pals) for d in frames]
    sheet, cells = sheet_of(imgs)
    fi = fighters()[index]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    png, js = out / f"{fi['slug']}_sheet.png", out / f"{fi['slug']}_sheet.json"
    Image.fromarray(sheet, "RGBA").save(png)
    js.write_text(json.dumps({"tool": "gbox.clayfighter_swap", "game_id": GAME_ID, "fighter": fi["code"],
                              "name": fi["name"], "sheet": png.name,
                              "frames": [{"index": k, "sheet": c, "hotspot": [d["X"], d["Y"]]}
                                         for k, (c, d) in enumerate(zip(cells, frames))]}, indent=1))
    return {"files": [png, js], "frames": len(frames), "sheet": list(sheet.shape[:2])}


def _components(img: np.ndarray, max_parts: int = 512) -> list[np.ndarray]:
    """A sheet without an index: its opaque connected regions (8-connected), reading order. One frame when the sheet
    is one blob or shatters into more than max_parts pieces."""
    m = img[..., 3] >= 64
    H, W = m.shape
    lab = np.zeros((H, W), np.int32)
    boxes, n = [], 0
    for y0, x0 in zip(*np.nonzero(m)):
        if lab[y0, x0]:
            continue
        n += 1
        stack, lab[y0, x0] = [(y0, x0)], n
        y1 = y2 = y0
        x1 = x2 = x0
        while stack:
            y, x = stack.pop()
            y1, y2, x1, x2 = min(y1, y), max(y2, y), min(x1, x), max(x2, x)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < H and 0 <= xx < W and m[yy, xx] and not lab[yy, xx]:
                        lab[yy, xx] = n
                        stack.append((yy, xx))
        boxes.append((y1, x1, y2, x2))
        if n > max_parts:
            return [img]
    big = [b for b in boxes if (b[2] - b[0] + 1) * (b[3] - b[1] + 1) >= 16] or boxes
    if len(big) <= 1:
        return [img]
    big.sort(key=lambda b: (b[0] // 16, b[1]))
    return [img[y1:y2 + 1, x1:x2 + 1] for y1, x1, y2, x2 in big]


def _index_frames(sheet: np.ndarray, index: dict) -> list[np.ndarray]:
    """Frame rectangles from a sheet index: frames[].sheet [x,y,w,h] (sprite_capture, this module), sprites[] with
    atlas_x/atlas_y/w/h (MVC2), or frames[] with x/y/w/h."""
    rects = []
    for fr in index.get("frames") or []:
        if isinstance(fr, dict) and isinstance(fr.get("sheet"), list):
            rects.append(fr["sheet"])
        elif isinstance(fr, dict) and all(k in fr for k in ("x", "y", "w", "h")):
            rects.append([fr["x"], fr["y"], fr["w"], fr["h"]])
        elif isinstance(fr, (list, tuple)) and len(fr) == 4:
            rects.append(list(fr))
    if not rects:
        for s in index.get("sprites") or []:
            if isinstance(s, dict) and "atlas_x" in s and s.get("w") and s.get("h"):
                rects.append([s["atlas_x"], s["atlas_y"], s["w"], s["h"]])
    return [sheet[int(y):int(y) + int(h), int(x):int(x) + int(w)] for x, y, w, h in rects
            if w > 0 and h > 0 and sheet[int(y):int(y) + int(h), int(x):int(x) + int(w)].size]


def _rgba(path: Path) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGBA"))


def _key_background(img: np.ndarray) -> np.ndarray:
    """A rendered preview (opaque background) -> RGBA with the corner colour keyed out."""
    img = img.copy()
    corners = np.array([img[0, 0, :3], img[0, -1, :3], img[-1, 0, :3], img[-1, -1, :3]], np.int32)
    bg = np.median(corners, 0)
    d = np.abs(img[..., :3].astype(np.int32) - bg).sum(2)
    img[..., 3] = np.where(d <= 24, 0, img[..., 3])
    return img


def donor_frames(entry_dir: Path, meta: dict) -> tuple[list[np.ndarray], str]:
    """A collection entry -> (RGBA frames, how they were found). sprites entries: sprite_capture clips
    (meta.animations), a JSON index next to the sheet, or the sheet's connected regions. Any other entry (a 3D model):
    its rendered preview as one static pose."""
    d = Path(entry_dir)
    if meta.get("kind") != "sprites":
        prev = d / meta.get("preview", "preview.png")
        if not prev.is_file():
            raise ValueError(f"{meta.get('name')} is not a sprites entry and has no preview to use as a pose")
        return [_key_background(_rgba(prev))], "static pose from the 3D model's preview render"
    frames: list[np.ndarray] = []
    for a in meta.get("animations") or []:
        try:
            idx = json.loads((d / a["index"]).read_text())
            frames += _index_frames(_rgba(d / a["sheet"]), idx)
        except (OSError, KeyError, ValueError):
            continue
    if frames:
        return frames, f"{len(meta['animations'])} captured clip(s)"
    model = d / meta["model"]
    sheet = _rgba(model)
    for j in sorted(d.glob("*.json")):
        if j.name in ("meta.json",):
            continue
        try:
            idx = json.loads(j.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(idx, dict):
            continue
        ref = (idx.get("atlas") or {}).get("sprites", {}).get("file") or idx.get("sheet")
        if ref and isinstance(ref, str) and ref != model.name:
            continue
        fr = _index_frames(sheet, idx)
        if fr:
            return fr, f"sheet index {j.name}"
    return _components(sheet), "sheet regions (no frame index)"


# ------------------------------------------------------------------------------------------------ gBox integration

def load_rom(path) -> bytes:
    from . import n64_rom
    data = n64_rom.read(Path(path))
    if data[:4] != b"\x80\x37\x12\x40":
        raise ValueError("not a big-endian N64 image")
    return data


def roster_entries() -> list[dict]:
    """characters op=collect roster (gbox.characters.DEDICATED): the 16 fighters, ripped as sprites entries."""
    return [{"key": f["key"], "slug": f["slug"], "name": f"{f['name']} (Clay Fighter SC)",
             "aliases": [f["name"], f["code"], f["slot"]], "kind": "character"} for f in fighters() if f["present"]]


def extract_run(ctx, game, entry, work) -> dict:
    from .models import CatalogEntry
    from .tools import rom_path
    rom = load_rom(rom_path(CatalogEntry.model_validate(game), ctx.config))
    f, _flip = find_fighter(f"fighter:{entry['key']}")
    r = export_fighter(rom, f["index"], Path(work))
    return {"files": r["files"], "roles": {}, "kind": "sprites", "tool": "gbox.clayfighter_swap (export_fighter)",
            "source_files": [f"{TITLE}.z64: fighter blob {f['code']}"],
            "notes": f"{r['frames']} frames of {f['name']} (decoded with the game's own CHARFRAM run format); "
                     f"slot {f['slot']} for characters op=use",
            "extra": {"picture": "2d", "clayfighter": {"fighter": f["code"], "slot": f["slot"]}}}


def mod_name(meta: dict, fighter: dict) -> str:
    return f"cfsc_{meta['slug']}_as_{fighter['key']}"[:64]


def build_mod(cfg, game: dict, meta: dict, fighter: dict, flip: bool, progress=lambda p, m: None,
              root: Path | None = None) -> dict:
    from . import characters as C, filemods
    from .models import CatalogEntry
    from .tools import rom_path
    root = root or C.library_root(cfg)
    rom_file = rom_path(CatalogEntry.model_validate(game), cfg)
    progress(5, f"Reading {Path(rom_file).name}")
    rom = load_rom(rom_file)
    frames, how = donor_frames(root / meta["slug"], meta)
    progress(30, f"Re-drawing {fighter['name']}'s frames with {meta['name']} ({len(frames)} donor frames: {how})")
    new, reports = write_fighters(rom, [{"index": fighter["index"], "frames": frames, "flip": flip}])
    check, orig = Fighter(new, fighter["index"]), Fighter(rom, fighter["index"])
    geo = ("W", "H", "X", "Y")
    bad = [i for i in range(check.count) if [check.frame(i)[k] for k in geo] != [orig.frame(i)[k] for k in geo]]
    if bad:
        raise RuntimeError(f"read-back changed frame geometry: {bad[:5]}")
    name = mod_name(meta, fighter)
    d = filemods.mod_dir(cfg, game["game_id"], name)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    donor = re.sub(r"[^\w .()-]+", "", meta["name"]).strip()
    img = f"{TITLE} - {donor} as {fighter['name']}.z64".replace("'", "")
    (d / img).write_bytes(new)
    # a contact sheet of what the game will draw, for the operator and the collection entry's targets/
    from PIL import Image
    pals = check.palettes()
    sheet, _cells = sheet_of([check.rgba(check.frame(i), pals) for i in range(min(check.count, 36))], 9)
    Image.fromarray(sheet, "RGBA").save(d / "frames_preview.png")
    tdir = root / meta["slug"] / "targets"
    try:
        tdir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d / "frames_preview.png", tdir / f"clayfighter_{fighter['key']}_preview.png")
    except OSError:
        pass
    mj = {"name": name, "game_id": game["game_id"], "image": img, "title": f"{meta['name']} as {fighter['name']}",
          "files": ["@image: fighter sprites (gbox.clayfighter_swap)"], "built": time.time(),
          "characters": [meta["slug"]], "replaces": [fighter["name"]], "donor": how, "report": reports[0]}
    (d / ".gbox-mod.json").write_text(json.dumps(mj))
    return {"mod": name, "image": img, "report": reports[0], "donor": how}


def needs(game: dict) -> dict:
    return {"target": "a fighter's sprite frames", "format": "CF3 CharDef 4.70 + CHARFRAM run-coded frames",
            "steps": [], "have": "gbox/clayfighter_swap.py: characters op=use slot=fighter:<name>[:flip]"}


def use(ctx, meta: dict, game: dict, inp) -> dict:
    """characters op=use for Clay Fighter SC: slot fighter:<name>[:flip] (player = Bad Mr. Frosty). Builds the ROM mod
    on the control plane (where the collection lives), registers the target, launches it when asked."""
    from . import characters as C
    gid = game["game_id"]
    if gid not in GAME_IDS:
        return {"status": "missing", "missing": needs(game), "message": "not Clay Fighter: Sculptor's Cut (USA)"}
    fighter, flip = find_fighter(inp.slot)
    sess = C._session(ctx, inp.session_id) if inp.session_id else None
    node = sess["session_id"].split("-")[0] if sess else C.HOST_OS
    name, built = mod_name(meta, fighter), None
    if not C.library_root(ctx.config).is_dir():               # not the control plane: build there, launch here
        cp = next((w["id"] for w in C._api(ctx, "GET", "/api/workers") if w.get("os") == "linux"), None)
        j = C._job(ctx, "characters", {"op": "use", "character": inp.character, "game_id": gid, "slot": inp.slot,
                                       "rebuild": inp.rebuild, "launch": False}, cp, 1800)
        r = (j.get("output") or {}).get("result") or {}
        if j.get("state") != "succeeded" or r.get("status") not in ("built", "ready"):
            return {"status": "failed", "error": r.get("error") or j.get("error") or r}
        name, built = r["mod"], r.get("build")
    else:
        from . import filemods
        have = (filemods.mod_dir(ctx.config, gid, name) / ".gbox-mod.json").exists()
        if inp.rebuild or not have:
            built = build_mod(ctx.config, game, meta, fighter, flip, ctx.progress)
            C._api(ctx, "POST", f"/api/characters/{meta['slug']}/targets",
                   json={"game_id": gid, "slot": fighter["slot"], "mod": name, "nodes": [C.HOST_OS],
                         "notes": f"re-draws all {built['report']['frames']} frames of {fighter['name']} "
                                  f"({built['donor']}); moves, hit boxes and sounds are the fighter's own"})
    res = {"mod": name, "build": built, "replaces": f"{fighter['name']} -> {meta['name']}", "slot": fighter["slot"]}
    if not inp.launch:
        return res | {"status": "built" if built else "ready"}
    ctx.progress(92, f"Launching Clay Fighter: Sculptor's Cut (mod {name})")
    lj = C._api(ctx, "POST", "/api/jobs", json={"tool": "@launch", "input": {"game_id": gid, "mod": name, "node": node}})
    from .sm64_swap import _wait
    lj = _wait(ctx, lj, 600)
    ok = lj.get("state") == "succeeded"
    msg = (f"Clay Fighter: Sculptor's Cut is running with {fighter['name']} re-drawn as {meta['name']} (mod {name}). "
           f"Pick {fighter['name']} on the character select screen." if ok else
           f"Mod {name} built but the launch {lj.get('state')}: {lj.get('error')}")
    return res | {"status": ("built+launched" if built else "launched") if ok else "built, launch failed",
                  "launch": {"job": lj.get("id"), "state": lj.get("state"), "node": node,
                             "session_id": (lj.get("output") or {}).get("session_id"), "error": lj.get("error")},
                  "message": msg}
