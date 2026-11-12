"""Tetris (PSP, game 25da54968d78f816) 'LU' package + LUSIZES.TBL parser.

Byte-verified on the owned build (CISO sha256 b0afb70a682c11c56f7660d39ea1224950b0b3eb33f2686970da5870bfa61bf2):

GLOBAL.PSP (/PSP_GAME/USRDIR/TETRIS/GLOBAL/GLOBAL.PSP, lba 75616, 7312512 B):
  @0x00 magic u32 0x03033f23 ('#?..')
  @0x04 ver      u32 (=1 on owned build)
  @0x08 flags    u32 (=0)
  @0x0C f0c      u32 (=0x00010004)
  @0x10 name1    12B NUL-padded ('global')
  @0x1C name2    16B NUL-padded ('tetris')
  @0x28 pad      8B
  @0x30 section_count u32 (=1)
  @0x38 section_name  8B ('Build')
  @0x40 pair table: consecutive (u32, u32) entries; hole = (0, 0xFFFFFFFF).
       256 entries on the owned build; the section payload starts at the
       first live offset (0x840), which also bounds the table:
       table_end = min live offset, (table_end - 0x40) % 8 == 0.
       Live entries on the owned build (idx -> (a, b)):
         19:(1,0x840) 23:(47,0x850) 32:(184,0xB40) 34:(293,0x16C0)
         38:(1,0x2910) 39:(8,0x2920) 40:(10,0x29A0) 41:(9,0x2A40)
         42:(1,0x2AD0) 43:(6,0x2AE0) 67:(12,0x2B80) 89:(36,0x2C40)
         90:(48,0x2E40) 99:(15,0x3140)
       b is monotonic and all live b >= table_end. Pair field meanings are
       UNPROVED (hypothesis: (size, offset)); pending EBOOT/Ghidra loader
       trace — do not interpret a/b beyond the bounds checks below.

LUSIZES.TBL (/PSP_GAME/USRDIR/LUSIZES.TBL, 6858 B): CRLF lines of
  "tetris\\...\\name.psp"=<decimal-size>
187 lines on the owned build (186 .psp + 1 .sbk). Paths are relative to
/PSP_GAME/USRDIR/TETRIS/ (leading 'tetris\\' stripped, lowercased, '\\'->'/').
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from gbox.tetris_psp_inventory import CisoReader, TARGET_ASSET

LU_MAGIC = bytes.fromhex("03033f23")
HOLE = (0, 0xFFFFFFFF)
TABLE_START = 0x40
HEADER_SIZE = 0x40

_LUSIZES_LINE = re.compile(r'^"([^"]+)"=(\d+)\s*$')


class LuError(ValueError):
    pass


@dataclass
class LuHeader:
    ver: int
    flags: int
    f0c: int
    name1: str
    name2: str
    section_count: int
    section_name: str
    table_end: int
    table_entries: int
    live_pairs: list[tuple[int, int, int]] = field(default_factory=list)  # (idx, a, b)
    holes: int = 0

    @property
    def data_start(self) -> int:
        return self.table_end


def _cstr(buf, off, ln):
    end = buf.find(b"\0", off, off + ln)
    return buf[off : end if end != -1 else off + ln].decode("ascii", "replace")


DEFAULT_TABLE_ENTRIES = 256


def _default_table_end(data: bytes) -> int | None:
    """Accept the owned-build 256-entry table only if validated, else None."""
    avail = (len(data) - TABLE_START) // 8
    n = min(DEFAULT_TABLE_ENTRIES, avail)
    base = TABLE_START + n * 8
    live_b = []
    for i in range(n):
        a, b = struct.unpack_from("<II", data, TABLE_START + i * 8)
        if (a, b) != HOLE:
            live_b.append(int(b))
    if not live_b:
        return None
    if any(b < base or b > len(data) or (b - TABLE_START) % 8 for b in live_b):
        return None
    if live_b != sorted(live_b):
        return None
    return base


def _derive_table_end(data: bytes) -> int:
    """Pair-table end = smallest plausible live b (8-aligned, in payload)."""
    avail = (len(data) - TABLE_START) // 8
    cands = []
    for i in range(avail):
        a, b = struct.unpack_from("<II", data, TABLE_START + i * 8)
        if (a, b) == HOLE:
            continue
        if TABLE_START <= b <= len(data) and (b - TABLE_START) % 8 == 0:
            cands.append(int(b))
    if not cands:
        raise LuError("no live pair bounds the pair table")
    return int(min(cands))


def parse_lu_header(data: bytes, table_end: int | None = None) -> LuHeader:
    """Parse the LU package header + pair table.

    table_end: explicit end offset of the pair table. When None, it is
    derived as the smallest live b with TABLE_START <= b <= len(data) and
    (b - TABLE_START) % 8 == 0 — on the owned build this is the first
    section-payload offset (0x840), which the payload itself confirms
    (bytes at 0x800 are still holes, i.e. inside the table).
    """
    if len(data) < HEADER_SIZE:
        raise LuError("LU payload shorter than header")
    if data[:4] != LU_MAGIC:
        raise LuError("bad LU magic %s" % data[:4].hex())
    ver, flags, f0c = struct.unpack_from("<III", data, 4)
    name1 = _cstr(data, 0x10, 12)
    name2 = _cstr(data, 0x1C, 16)
    section_count = struct.unpack_from("<I", data, 0x30)[0]
    section_name = _cstr(data, 0x38, 8)

    if table_end is None:
        table_end = _default_table_end(data)
        if table_end is None:
            table_end = _derive_table_end(data)
    if table_end < TABLE_START or (table_end - TABLE_START) % 8:
        raise LuError("pair table end not 8-aligned within bounds")
    n = (table_end - TABLE_START) // 8
    if TABLE_START + n * 8 > len(data):
        raise LuError("pair table exceeds payload")

    live, holes = [], 0
    for i in range(n):
        a, b = struct.unpack_from("<II", data, TABLE_START + i * 8)
        if (a, b) == HOLE:
            holes += 1
        else:
            if b < table_end:
                raise LuError("live pair offset before table end: idx %d -> 0x%x" % (i, b))
            live.append((i, a, b))
    offs = [b for _, _, b in live]
    if offs != sorted(offs):
        raise LuError("live pair offsets not monotonic")
    return LuHeader(ver, flags, f0c, name1, name2, section_count, section_name,
                    table_end, n, live, holes)


def parse_lusizes_tbl(data: bytes) -> tuple[dict[str, int], int]:
    """Parse LUSIZES.TBL -> ({'global/en/global.psp': 2128, ...}, parsed_line_count).

    Keys are lowercase, backslashes to '/', leading 'tetris/' stripped.
    Raises LuError on a line that does not match the quoted form.
    """
    sizes: dict[str, int] = {}
    lines = data.split(b"\n")
    parsed = 0
    for raw in lines:
        line = raw.decode("ascii", "replace").rstrip("\r").strip()
        if not line:
            continue
        m = _LUSIZES_LINE.match(line)
        if not m:
            raise LuError("bad LUSIZES line: %r" % line[:80])
        path = m.group(1).replace("\\", "/").lower()
        if path.startswith("tetris/"):
            path = path[len("tetris/"):]
        sizes[path] = int(m.group(2))
        parsed += 1
    return sizes, parsed


def map_lusizes_path(path: str) -> str:
    """LUSIZES key -> ISO9660 path inside the PSP_GAME/USRDIR/TETRIS tree."""
    return "/PSP_GAME/USRDIR/TETRIS/" + path.upper()


def lu_report(ciso_path: str) -> dict:
    """Open the owned CISO, read GLOBAL.PSP + LUSIZES.TBL, stream-hash the
    target, and return a machine-readable report (no file copies)."""
    rd = CisoReader(ciso_path)
    try:
        import hashlib
        from gbox.tetris_psp_inventory import walk_iso

        ents = {e.path: e for e in walk_iso(rd) if not e.is_dir}
        if TARGET_ASSET not in ents:
            raise LuError("missing " + TARGET_ASSET)
        te = ents[TARGET_ASSET]
        off = te.lba * 2048
        h = hashlib.sha256()
        left = te.size
        while left:
            n = min(left, 1 << 20)
            h.update(rd.read(off + te.size - left, n))
            left -= n
        lu = rd.read(off, min(te.size, 1 << 20))  # header + table head
        header = parse_lu_header(lu)
        ls = ents.get("/PSP_GAME/USRDIR/LUSIZES.TBL")
        lusizes, lusizes_lines = ({}, 0)
        if ls:
            lusizes, lusizes_lines = parse_lusizes_tbl(rd.read(ls.lba * 2048, ls.size))
        return {
            "path": TARGET_ASSET,
            "lba": te.lba,
            "size": te.size,
            "sha256": h.hexdigest(),
            "lu": header,
            "lusizes": lusizes,
            "lusizes_lines": lusizes_lines,
            "lusizes_size": ls.size if ls else 0,
        }
    finally:
        rd.close()
