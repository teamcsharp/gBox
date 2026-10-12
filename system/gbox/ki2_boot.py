"""Killer Instinct 2 (Midway V-Unit / kinst2) boot-ROM program decompressor.

The game program does not live on the CHD.  It is stored compressed inside the
u98 boot EPROM (ki2-l14.u98 and its sibling BIOS revisions) and unpacked to
RAM by a small loader in the uncompressed head of that ROM.  The loader is
*instruction-aware*: it rebuilds every 32-bit MIPS word field by field
(opcode / rs / rt / rd / shamt / funct / imm16 / target26) from 24 static
prefix-code trees, with two move-to-back register caches.

Reverse-engineered from ki2-l14.u98 (all addresses KSEG1, base 0xbfc00000):

  0xbfc006a8  loader entry: src = align16(0xbfc01034), state @0x887fff00
  0xbfc00d7c  bit reader init (LSB-first, refilled 7 bytes at a time)
  0xbfc00dc4  getbits(n)          0xbfc00e08  skip(n) (used to byte-align)
  0xbfc00e44  byte position       0xbfc00e30  reseat reader at a byte
  0xbfc00e54  prefix-tree symbol decode (node byte: 0 = leaf, >0 = 7-bit
              skip, <0 = 15-bit skip; bit 1 -> next node, bit 0 -> skip)
  0xbfc00d18  register-cache init (32 entries, value 31..0)
  0xbfc00d3c  move-to-back update (hit value moves to index 31)
  0xbfc00eb0  SPECIAL funct flag table (64 x u16)
  0xbfc00f30  REGIMM rt flag table     (32 x u16)
  0xbfc00f70  COPz rs flag table       (32 x u16)
  0xbfc00fb0  primary opcode table     (64 x u16; 0xffff = COPz,
              0x4000 = 'jr ra', 0x2000 = 'nop', 0 = raw 26-bit word)

Stream layout: u16 magic 0x7262, u8 segment count, then per segment: u8 0,
u32 byte count, u32 load address (the first one is the entry point), byte
align, 24 x (u16 length + tree bytes), then the instruction bit stream.

This module only reads owned ROM bytes; it never patches or rewrites them.
"""
from __future__ import annotations

import hashlib
import struct
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROM_BASE = 0xBFC00000
MAGIC = 0x7262
TREE_COUNT = 24
JR_RA = 0x03E00008

# Tree slot indices, as fetched by the loader from state+0x40+4*k.
T_OPCODE, T_FUNCT, T_REGIMM_RT, T_RS, T_RT, T_RD, T_SHAMT, T_RS2, T_BYTE = range(9)
T_IMM_HI, T_IMM_LO = 9, 10
T_J0, T_J1, T_J2, T_J3 = 11, 12, 13, 14
T_IMM1_HI, T_IMM1_LO, T_IMM2_HI, T_IMM2_LO, T_IMM3_HI, T_IMM3_LO = 15, 16, 17, 18, 19, 20
T_FIELD, T_COP_RS, T_COP_RT = 21, 22, 23


class BootFormatError(ValueError):
    pass


def _u32(rom: bytes, addr: int) -> int:
    return struct.unpack_from("<I", rom, addr - ROM_BASE)[0]


def _imm(word: int) -> int:
    v = word & 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


@dataclass
class LoaderLayout:
    """Addresses recovered from the loader instructions of one u98 revision."""

    src: int
    opcode_table: int
    special_table: int
    regimm_table: int
    cop_table: int


def find_layout(rom: bytes) -> LoaderLayout:
    """Recover the stream start and flag-table addresses from loader code.

    The source pointer is built by ``lui a1,0xbfc0 / addiu a1,a1,X`` +
    ``addiu a1,a1,0xf / srl 4 / sll 4``; the four tables are each loaded with
    ``lui s4,0xbfc0`` followed by ``addiu s4,s4,X`` in the order opcode,
    SPECIAL, REGIMM, COPz.
    """
    words = struct.unpack_from("<%dI" % (min(len(rom), 0x2000) // 4), rom)
    src = None
    for i in range(len(words) - 1):
        if words[i] == 0x3C05BFC0 and words[i + 1] >> 16 == 0x24A5:
            src = (0xBFC00000 + _imm(words[i + 1]) + 0xF) & ~0xF
            break
    tables = []
    for i in range(len(words) - 3):
        if words[i] == 0x3C14BFC0:
            for j in range(i + 1, i + 4):
                if words[j] >> 16 == 0x2694:
                    tables.append(0xBFC00000 + _imm(words[j]))
                    break
    if src is None or len(tables) < 4:
        raise BootFormatError("loader signature not found (src=%r, tables=%d)" % (src, len(tables)))
    return LoaderLayout(src, tables[0], tables[1], tables[2], tables[3])


class BitReader:
    """LSB-first bit reader equivalent to the loader's s0/s1/s2 registers."""

    def __init__(self, data: bytes, byte_pos: int):
        self.data = data
        self.bit = byte_pos * 8

    def get(self, n: int) -> int:
        if n == 0:
            return 0
        byte, sh = self.bit >> 3, self.bit & 7
        chunk = int.from_bytes(self.data[byte:byte + 8], "little")
        self.bit += n
        return (chunk >> sh) & ((1 << n) - 1)

    def align(self) -> None:
        self.bit = (self.bit + 7) & ~7

    @property
    def byte_pos(self) -> int:
        return self.bit >> 3

    def seat(self, byte_pos: int) -> None:
        self.bit = byte_pos * 8

    def symbol(self, tree: int) -> int:
        """Walk a prefix tree stored at byte offset ``tree`` (loader 0xbfc00e54)."""
        d = self.data
        p = tree
        while True:
            b = d[p]
            p += 1
            if b == 0:
                return d[p]
            if b & 0x80:
                off = ((b & 0x7F) << 8) | d[p]
                p += 1
            else:
                off = b
            if not self.get(1):
                p += off


def _table(rom: bytes, addr: int, count: int) -> list[int]:
    return list(struct.unpack_from("<%dH" % count, rom, addr - ROM_BASE))


@dataclass
class Segment:
    load_addr: int
    size: int
    stream_offset: int
    tree_offsets: list[int]
    data: bytes = b""

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass
class Program:
    entry: int
    segments: list[Segment] = field(default_factory=list)
    end_offset: int = 0

    def image(self) -> tuple[int, bytes]:
        """Flat image from the lowest load address (gaps zero-filled)."""
        lo = min(s.load_addr for s in self.segments)
        hi = max(s.load_addr + s.size for s in self.segments)
        buf = bytearray(hi - lo)
        for s in self.segments:
            buf[s.load_addr - lo:s.load_addr - lo + s.size] = s.data
        return lo, bytes(buf)


class _RegCache:
    """Register cache from 0xbfc00d18/0xbfc00d3c (move-to-back, 32 slots)."""

    def __init__(self):
        self.t = [31 - i for i in range(32)]

    def take(self, index: int) -> int:
        v = self.t[index]
        del self.t[index]
        self.t.append(v)
        return v


def decompress(rom: bytes, layout: LoaderLayout | None = None, limit_words: int | None = None) -> Program:
    """Unpack the game program exactly as the boot loader does."""
    layout = layout or find_layout(rom)
    # 66 entries: the opcode tree also emits pseudo-opcodes 64 (0x2000, nop)
    # and 65 (0x4000, 'jr ra'); the loader reads them from the two u16 that
    # follow the 64-entry table (the 0x40002000 word at 0xbfc01030).
    op_t = _table(rom, layout.opcode_table, 66)
    sp_t = _table(rom, layout.special_table, 64)
    ri_t = _table(rom, layout.regimm_table, 32)
    cp_t = _table(rom, layout.cop_table, 32)
    br = BitReader(rom, layout.src - ROM_BASE)
    if br.get(16) != MAGIC:
        raise BootFormatError("bad program magic")
    nseg = br.get(8)
    prog = Program(entry=0)
    for _ in range(nseg):
        if br.get(8) != 0:
            raise BootFormatError("segment marker is not zero")
        size = br.get(32)
        addr = br.get(32)
        if not prog.entry:
            prog.entry = addr
        seg = Segment(addr, size, br.byte_pos, [])
        prog.segments.append(seg)
        if size == 0:
            continue
        cache1, cache2 = _RegCache(), _RegCache()
        trees = []
        for _k in range(TREE_COUNT):
            br.align()
            n = br.get(16)
            trees.append(br.byte_pos)
            br.seat(br.byte_pos + n)
        seg.tree_offsets = trees
        sym = br.symbol
        out = bytearray()
        count = size // 4 if limit_words is None else min(size // 4, limit_words)
        for _w in range(count):
            t0 = t4 = t5 = t6 = t7 = s3 = 0
            t1 = sym(trees[T_OPCODE])
            s4 = op_t[t1]
            if t1 == 0:  # SPECIAL
                t4 = sym(trees[T_FUNCT])
                s4 = sp_t[t4]
                if s4 == 0:
                    t0 |= br.get(20) << 6
            elif t1 == 1:  # REGIMM
                t6 = sym(trees[T_REGIMM_RT])
                s4 = ri_t[t6]
                if s4 == 0:
                    t5 |= sym(trees[T_FIELD])
                    t4 |= sym(trees[T_IMM_HI]) << 8
                    t4 |= sym(trees[T_IMM_LO])
            elif s4 == 0xFFFF:  # COPz
                v = sym(trees[T_COP_RS])
                s4 = cp_t[v]
                t5 |= v
                if s4 == 0:
                    t6 |= sym(trees[T_FIELD])
                    t4 |= sym(trees[T_IMM_HI]) << 8
                    t4 |= sym(trees[T_IMM_LO])
                if s4 == 0xC00:
                    t6 |= sym(trees[T_COP_RT])
                    if t6 >= 4:
                        t4 |= sym(trees[T_IMM_HI]) << 8
                        t4 |= sym(trees[T_IMM_LO])
                        s4 = 0
                if s4 == 0xFFFF:
                    t0 |= br.get(21)
                    s4 = 0
            elif s4 == 0:
                t0 |= br.get(26)
            elif s4 == 0x4000:
                t0, t1, s4 = JR_RA, 0, 0
            elif s4 == 0x2000:
                t0, t1, s4 = 0, 0, 0
            # field flags (0xbfc009dc..0xbfc00c40)
            if s4 & 0x4:
                t6 |= cache1.take(sym(trees[T_RT]))
            elif s4 & 0x8:
                t6 |= sym(trees[T_BYTE])
            if s4 & 0x1:
                if s4 & 0x200:
                    t5 |= cache2.take(sym(trees[T_RS2]))
                else:
                    t5 |= cache1.take(sym(trees[T_RS]))
            elif s4 & 0x2:
                t5 |= sym(trees[T_BYTE])
            if s4 & 0x10:
                t7 |= cache1.take(sym(trees[T_RD]))
            elif s4 & 0x20:
                t7 |= sym(trees[T_BYTE])
            if s4 & 0x40:
                s3 = sym(trees[T_SHAMT])
            elif s4 & 0x80:
                s3 = sym(trees[T_BYTE])
            if s4 & 0x100:
                t0 |= sym(trees[T_J0]) << 20
                t0 |= sym(trees[T_J1]) << 14
                t0 |= sym(trees[T_J2]) << 7
                t0 |= sym(trees[T_J3])
            sel = s4 & 0xC00
            if sel == 0x400:
                t4 |= (sym(trees[T_IMM1_HI]) << 8) | sym(trees[T_IMM1_LO])
            elif sel == 0x800:
                t4 |= (sym(trees[T_IMM2_HI]) << 8) | sym(trees[T_IMM2_LO])
            elif sel == 0xC00:
                t4 |= (sym(trees[T_IMM3_HI]) << 8) | sym(trees[T_IMM3_LO])
            if s4 & 0x1000:
                t4 |= sym(trees[T_BYTE])
            word = (t0 | (t1 << 26) | t4 | (t5 << 21) | (t6 << 16) | (t7 << 11) | (s3 << 6)) & 0xFFFFFFFF
            out += struct.pack("<I", word)
        seg.data = bytes(out)
    prog.end_offset = (br.bit + 7) >> 3
    return prog


def code_stats(data: bytes) -> dict:
    """Cheap sanity metrics for decoded MIPS code."""
    n = len(data) // 4
    words = struct.unpack_from("<%dI" % n, data)
    return {
        "words": n,
        "jr_ra": sum(1 for w in words if w == JR_RA),
        "addiu_sp_neg": sum(1 for w in words if w >> 16 == 0x27BD and w & 0x8000),
        "nop": sum(1 for w in words if w == 0),
    }


def load_u98(zip_path: str | Path, member: str = "ki2-l14.u98") -> bytes:
    with zipfile.ZipFile(zip_path) as z:
        return z.read(member)


# ---------------------------------------------------------------------------
# Disk access, from the unpacked l14 program (KSEG0 addresses):
#   0x8801ba60  ide_init: device control 8, then INITIALIZE DEVICE PARAMETERS
#               (0x91) with sector count 0x28 and head reg 0xd -> the game
#               addresses the drive as 14 heads x 40 sectors, independent of
#               the CHD's native 1463/13/47 geometry.
#   0x8801bd1c  set_chs(a1 = linear sector, a3 = count): sector = a1%40 + 1,
#               head = (a1/40)%14, cylinder = (a1/40)/14.
#   0x8801bad0  disk_read(t0 = RAM dest, a1 = linear sector, a2 = count),
#               READ SECTORS (0x20) in chunks of <= 255 sectors; 25 callers.
#   0x8801bb88  disk_write (0x30); 0x8801bbfc write+verify; 0x8801bd84 IDENTIFY.
#   0x880003fc  boot: ide_init, then disk_read(0x88090100, 0x190, 0x1e5).
#   0x880161c8  table loader: disk_read(t6, [t1] + 0x1504, 4).
# With the drive translated to 14x40, the game's linear sector equals the raw
# LBA of the chdman-extracted image (MAME ata_hle lba_address()).
GAME_HEADS = 14
GAME_SECTORS = 40
SECTOR = 512
BOOT_DISK_READ = {"dest": 0x88090100, "lba": 0x190, "count": 0x1E5}
TABLE_LOADER_BASE_LBA = 0x1504

# Verified unpack results for every owned u98 revision in kinst2.zip
# (image = all segments flattened from 0x88000000).
REVISION_IMAGES = {
    "ki2-l10.u98": "1bc5883c52016b01164a5ef7db280fb5e0746ede6e83b22ef76e4481405c7aa9",
    "ki2-l11.u98": "536c1c4734f8f75d0517342788419460d89291a839c8cf6e0885ec31c4bfc972",
    "ki2-l13.u98": "43046378e13388fa4d9dc4eaecbdee7ea074153a6713414b7faf10492d7ea70a",
    "ki2-l14.u98": "e17b457306ea9c0c92f0ec369b01b573bd53ba24244e9442fb3ebf379737c330",
    "ki2_l14p.u98": "e17b457306ea9c0c92f0ec369b01b573bd53ba24244e9442fb3ebf379737c330",
}


def chs_registers(lba: int) -> dict:
    """Task-file values the game writes for a linear sector (0x8801bd1c)."""
    track, sector = divmod(lba, GAME_SECTORS)
    cyl, head = divmod(track, GAME_HEADS)
    return {"sector": sector + 1, "head": head, "cyl_lo": cyl & 0xFF, "cyl_hi": cyl >> 8}


def chs_to_lba(cyl: int, head: int, sector: int) -> int:
    return (cyl * GAME_HEADS + head) * GAME_SECTORS + sector - 1


def read_sectors(raw_path: str | Path, lba: int, count: int) -> bytes:
    with open(raw_path, "rb") as f:
        f.seek(lba * SECTOR)
        return f.read(count * SECTOR)


def roster_strings(image: bytes, base: int = 0x88000000) -> list[tuple[int, str]]:
    """'<NAME> STATS' strings (the in-game roster) with their RAM addresses.

    The audit menu also has a 'GENERAL STATS' page, which is not a fighter.
    """
    import re

    return [(base + m.start(), m.group(1).decode())
            for m in re.finditer(rb"([A-Z][A-Z ]{2,9}) STATS\x00", image)
            if m.group(1) != b"GENERAL"]


def main() -> None:  # pragma: no cover - CLI helper
    import argparse
    import json

    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("zip")
    ap.add_argument("--member", default="ki2-l14.u98")
    ap.add_argument("--out")
    a = ap.parse_args()
    rom = load_u98(a.zip, a.member)
    prog = decompress(rom)
    report = {
        "member": a.member,
        "rom_sha256": hashlib.sha256(rom).hexdigest(),
        "entry": "0x%08x" % prog.entry,
        "compressed_end": "0x%x" % prog.end_offset,
        "segments": [
            {"load": "0x%08x" % s.load_addr, "size": s.size, "sha256": s.sha256, **code_stats(s.data)}
            for s in prog.segments
        ],
    }
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for s in prog.segments:
            (out / ("seg_%08x.bin" % s.load_addr)).write_bytes(s.data)
        lo, img = prog.image()
        (out / ("image_%08x.bin" % lo)).write_bytes(img)
        report["image"] = {"base": "0x%08x" % lo, "size": len(img), "sha256": hashlib.sha256(img).hexdigest()}
        (out / "program.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":  # pragma: no cover
    main()
