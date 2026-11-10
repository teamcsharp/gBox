"""Project Justice (USA) Dreamcast: analysis-stage format identification.

Build: T-1219N V1.001 USA 2001-01-26 (1ST_READ.BIN sha256 93cbcb3c...ad4,
load base 0x8C010000). Inventory (gbox.pj_inventory) mapped the container;
this module identifies the character/asset binary formats and the roster.

Findings (all reproduced from the owned bytes in
``~/gbox-cache/dc/6334be1925fbe016``):

1. Character definition table
   A 0x50-byte-record array at vaddr 0x8c19c620 (file offset 0x18c620). Each
   record: 4-byte header ``[u8 idx, u8 idx, u8 idx, u8 group]`` (the index byte
   is written three times) followed by a NUL-terminated display name and
   padding. Records run idx 0x01..0x1c (28 records). The 4th byte groups
   characters (school/team).

2. Roster (the "RAIZO" question)
   There is NO ASCII or Shift-JIS spelling of ``RAIZO`` anywhere in
   1ST_READ.BIN. The 22 playable characters on this US build are, in table
   order: BATSU HINATA KYOSUKE SHOMA NATSU ROBERTO ROY TIFFANY BOMAN EDGE
   AKIRA GAN KUROW HYO IINCYO DAIGO HAYATO RAN NAGARE ZAKI MOMO YURIKA.
   The character the inventory called "RAIZO" is the Imawano boss ``HYO``
   (idx 0x10); the 22nd playable is ``IINCYO`` (student-council president,
   idx 0x12). Alternate forms: POWERED AKIRA, BURNING BATSU, DEMON HYO,
   WILD DAIGO. Non-playable: HIDEO, KYOKO (Batsu's parents).

3. Asset archive formats
   - UPLMDL.AFS  (42 entries): headerless model data, NO NJCM/NJTL/NJMD magic.
     Header is a u16 table alternating a flag word (0x0000 for the first
     section, 0x0001 after) with a 16-bit offset; offsets point at
     float/fixed-point vertex data (exact record grammar TBD in reader stage).
   - XPLTEX.AFS (336 entries, 8/model): headerless texture data (no GBIX/PVRT).
   - WPLMOT.AFS  (92 entries): ``u32 count`` then ``count`` x ``u32`` offsets
     into the entry (motion clip table).
   - YPLPACK.AFS  (32 entries): magic ``DTPK`` (Capcom pack).
   - UGMEDMDL.AFS (320 entries): small medal/select models (u32 + float data).
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

FIRST_READ_BASE = 0x8C010000
FIRST_READ_SHA256 = "93cbcb3c88135ae1175837f919bed21655cf7d33d37bebe5c551beb81b4faad4"

# character definition table (see module docstring)
CHARACTER_TABLE_VA = 0x8C19C620
CHARACTER_TABLE_FILE_OFF = CHARACTER_TABLE_VA - FIRST_READ_BASE
CHARACTER_RECORD_SIZE = 0x50
FIRST_CHAR_IDX = 0x01
LAST_CHAR_IDX = 0x1C

# 22 playable characters in table order
PLAYABLE_ROSTER = [
    "BATSU", "HINATA", "KYOSUKE", "SHOMA", "NATSU", "ROBERTO", "ROY",
    "TIFFANY", "BOMAN", "EDGE", "AKIRA", "GAN", "KUROW", "HYO", "IINCYO",
    "DAIGO", "HAYATO", "RAN", "NAGARE", "ZAKI", "MOMO", "YURIKA",
]
ALT_FORMS = ["POWERED AKIRA", "BURNING BATSU", "DEMON HYO", "WILD DAIGO"]
NPC_NAMES = ["HIDEO", "KYOKO"]


def _cstr(data: bytes, off: int, limit: int) -> str:
    end = data.find(b"\x00", off, off + limit)
    if end < 0:
        end = off + limit
    return data[off:end].decode("latin-1", "replace")


def character_table(exe: bytes) -> list[dict]:
    """Parse the 0x50-byte character table from 1ST_READ.BIN.

    Returns one dict per record: ``{"idx", "group", "name", "va"}``.
    Raises ValueError if the table's index pattern is not found.
    """
    off = CHARACTER_TABLE_FILE_OFF
    records: list[dict] = []
    while off + CHARACTER_RECORD_SIZE <= len(exe):
        a, b, c, group = exe[off], exe[off + 1], exe[off + 2], exe[off + 3]
        if not (a == b == c and FIRST_CHAR_IDX <= a <= LAST_CHAR_IDX):
            break
        name = _cstr(exe, off + 4, CHARACTER_RECORD_SIZE - 4)
        records.append({
            "idx": a,
            "group": group,
            "name": name,
            "va": off + FIRST_READ_BASE,
        })
        off += CHARACTER_RECORD_SIZE
    if not records:
        raise ValueError("character table not found at 0x%08x" % CHARACTER_TABLE_VA)
    return records


def playable_roster(exe: bytes) -> list[str]:
    """The 22 playable names (alternate forms and NPCs filtered out)."""
    return [r["name"] for r in character_table(exe)
            if r["name"] not in ALT_FORMS and r["name"] not in NPC_NAMES]


def wplmot_offsets(blob: bytes) -> list[int]:
    """Parse a WPLMOT motion entry: ``u32 count`` then ``count`` u32 offsets.

    Offsets are relative to the start of the entry and must be monotonic and
    in-bounds. Raises ValueError on a malformed table.
    """
    if len(blob) < 4:
        raise ValueError("WPLMOT entry too small")
    count = struct.unpack_from("<I", blob, 0)[0]
    if not 0 < count <= 512 or 4 + count * 4 > len(blob):
        raise ValueError("WPLMOT count %d out of range" % count)
    offsets = list(struct.unpack_from("<%dI" % count, blob, 4))
    if any(o >= len(blob) for o in offsets):
        raise ValueError("WPLMOT offset out of range")
    if offsets != sorted(offsets):
        raise ValueError("WPLMOT offsets not monotonic")
    return offsets


def uplmdl_pointers(blob: bytes) -> tuple[list[int], list[int]]:
    """Extract the (flag, offset) u16 table at the head of a UPLMDL entry.

    The header interleaves a flag word (0x0000 for the first section, 0x0001
    thereafter) with a 16-bit offset into the entry; offsets point at
    float/fixed-point vertex data. Parsing stops at the first word pair that
    no longer matches the flag grammar. Returns ``(flags, offsets)``.
    """
    n = min(len(blob) // 2, 512)
    words = struct.unpack_from("<%dH" % n, blob, 0)
    flags: list[int] = []
    offsets: list[int] = []
    for i in range(0, len(words) - 1, 2):
        fl, off = words[i], words[i + 1]
        if fl not in (0, 1):
            break
        if off >= 0x10000:
            break
        flags.append(fl)
        offsets.append(off)
    return flags, offsets

# --- AFS descriptor table + character pointer table (loader-side evidence) ---
# The boot code (init loop at 0x8c126584, 14 iterations, r14 += 12) walks a
# 12-byte-record array at vaddr 0x8c2b9e44: {u32 name_ptr, u32 toc_buf_ptr,
# u32 entry_count}. toc_buf_ptr lies in BSS (past the file image), i.e. the AFS
# TOC is read into RAM at boot; entry_count equals the AFS entry count on disc.
AFS_DESC_VA = 0x8C2B9E44
AFS_DESC_COUNT = 14
AFS_DESC_SIZE = 12
# 29 u32 pointers (P0 form 0x0c19c620 + 0x50*n) at 0x8c19d340: slot 0 and 1
# both reference record 0x01 (BATSU), then records 0x02..0x1c.
CHAR_PTR_TABLE_VA = 0x8C19D340
CHAR_PTR_TABLE_LEN = 29


def _va_to_off(va: int) -> int:
    return (va & 0x1FFFFFFF) - (FIRST_READ_BASE & 0x1FFFFFFF)


def afs_descriptors(exe: bytes) -> list[dict]:
    """Boot-time AFS descriptor table: name, TOC RAM buffer, entry count.

    The slot number (list index) is the archive id used by the loaders:
    ... 5=yplpack 6=xpltex 7=uplmdl 8=wplmot ... 13=ugmedmdl.
    """
    out = []
    base = _va_to_off(AFS_DESC_VA)
    for i in range(AFS_DESC_COUNT):
        name_p, buf_p, count = struct.unpack_from(
            "<III", exe, base + i * AFS_DESC_SIZE)
        out.append({
            "slot": i,
            "name": _cstr(exe, _va_to_off(name_p), 32),
            "toc_va": 0x80000000 | (buf_p & 0x1FFFFFFF),
            "count": count,
        })
    return out


def character_pointer_table(exe: bytes) -> list[int]:
    """Pointers (as 0x8c-form VAs) from the table at 0x8c19d340 to records."""
    base = _va_to_off(CHAR_PTR_TABLE_VA)
    ptrs = struct.unpack_from("<%dI" % CHAR_PTR_TABLE_LEN, exe, base)
    return [0x80000000 | (p & 0x1FFFFFFF) for p in ptrs]


# --- Loader evidence round 3 (SH-4 disassembly of 1ST_READ.BIN) ---------------
# Pointers inside the executable are stored in P0 (physical-mirror) form,
# 0x0cXXXXXX, not 0x8cXXXXXX.  A literal search for the 0x8c form finds
# nothing; search the low 29 bits instead.  Loader code found this way:
#   * 0x8c0281fe, 0x8c09dda4 and ~20 other sites load 0x0c19d340 and do
#     rec = table[slot]; stat = STAT_TABLE[rec[0]]; (rec[1] bounds 1..45
#     selects a per-costume block via 0x0c1931fc).
#   * slot range checked by the game is 0..39 (cmp/gt #39), i.e. 40 slots,
#     not 29: slots 29..39 are Vatsu, Taiyo-M/F, Gorin-M/F, Paci-M/F, Gedo,
#     Seijun, Jus-M/F (partner / extra characters).
#   * 0x8c175bec is NOT a model/motion table.  The routine at 0x8c126662
#     (r4=file slot, r5=index) reads {u16 group,u16 entry,u8[4] flags} and
#     forwards (handle=[0x0c305e08+4*r4], group, entry) to 0x0c2bdb34, i.e. a
#     stream/sound table (51 consecutive entries in group 0).
CHAR_SLOT_COUNT = 40
CHAR_STAT_TABLE_VA = 0x8C19E5C0
CHAR_STAT_RECORD_SIZE = 0x6C
STREAM_TABLE_VA = 0x8C175BEC


def p0_to_va(ptr: int) -> int:
    """Convert a stored 0x0cXXXXXX / 0xacXXXXXX pointer to its 0x8c VA."""
    return 0x80000000 | (ptr & 0x1FFFFFFF)


def character_slots(exe: bytes) -> list[dict]:
    """All 40 slots reachable via the 0x8c19d340 pointer table.

    ``ids`` are the first four record bytes (b0 = stat-record index into
    0x8c19e5c0, b1 = costume-block index 1..45, b2/b3 = unresolved).
    """
    base = _va_to_off(CHAR_PTR_TABLE_VA)
    out = []
    for slot in range(CHAR_SLOT_COUNT):
        (ptr,) = struct.unpack_from("<I", exe, base + 4 * slot)
        va = p0_to_va(ptr)
        off = _va_to_off(va)
        out.append({"slot": slot, "va": va,
                    "ids": tuple(exe[off:off + 4]),
                    "name": _cstr(exe, off + 4, 16)})
    return out


def character_stat_records(exe: bytes) -> list[dict]:
    """Per-slot stat records via 0x8c19e5c0[rec.b0] (0x6c bytes each).

    Only fields observed in the loader are decoded: s32 +0x08 (171..182,
    health-like), f32 +0x0c/+0x10 (scale-like, ~0.9..1.1) and two pointers
    at +0x14/+0x18 whose targets are in the executable image.
    """
    tbl = _va_to_off(CHAR_STAT_TABLE_VA)
    out = []
    for cs in character_slots(exe):
        (ptr,) = struct.unpack_from("<I", exe, tbl + 4 * cs["ids"][0])
        va = p0_to_va(ptr)
        off = _va_to_off(va)
        v8, f0, f1, p14, p18 = struct.unpack_from("<i f f I I", exe, off + 8)
        out.append({"slot": cs["slot"], "name": cs["name"], "stat_va": va,
                    "value_0x08": v8, "scale_a": f0, "scale_b": f1,
                    "ptr_0x14": p0_to_va(p14), "ptr_0x18": p0_to_va(p18)})
    return out


COSTUME_TABLE_VA = 0x8C1931FC
COSTUME_BLOCK_HEADER_PTRS = 13


def costume_block_table(exe: bytes) -> list[int]:
    """Pointer table at 0x8c1931fc, one P0 pointer per costume block.

    Entries run until the first non-pointer word (the 0 terminator at
    0x8c1933a8); b1 of a slot record (1..45) selects into it. Returns VAs.
    """
    base = _va_to_off(COSTUME_TABLE_VA)
    out = []
    for i in range(256):
        (ptr,) = struct.unpack_from("<I", exe, base + 4 * i)
        if (ptr >> 24) != 0x0C:
            break
        out.append(p0_to_va(ptr))
    return out


def costume_block_header(exe: bytes, va: int) -> list[int]:
    """The 13 leading P0 pointers of a costume block, as VAs.

    EVIDENCE: hdr[0] is a shared ``rts; nop`` stub (0x8c0e4af8) and other
    entries target SH-4 code/state tables in the executable image, i.e. these
    blocks (and stat-record ptr_0x14/0x18) are per-character fight-script /
    callback data, NOT UPLMDL/WPLMOT indices. The model/motion mapping lives
    in the AFS loader callers (HYPOTHESIS: indexed by slot/costume id).
    """
    off = _va_to_off(va)
    return [p0_to_va(x) for x in
            struct.unpack_from("<%dI" % COSTUME_BLOCK_HEADER_PTRS, exe, off)]


def stream_table(exe: bytes, count: int = 80) -> list[dict]:
    """8-byte {u16 group, u16 entry, u8 flags[4]} stream/sound table."""
    base = _va_to_off(STREAM_TABLE_VA)
    out = []
    for i in range(count):
        grp, ent, f = struct.unpack_from("<HH4s", exe, base + 8 * i)
        out.append({"idx": i, "group": grp, "entry": ent, "flags": f.hex()})
    return out


def classify_entry(blob: bytes) -> str:
    """Coarse classification of a positional AFS entry payload."""
    if blob[:4] == b"AFS\x00":
        return "afs"
    if blob[:4] == b"DTPK":
        return "dtpk"
    if blob[:4] in (b"NJCM", b"NJTL", b"NJMD"):
        return "ninja-chunk"
    if blob[:4] in (b"GBIX", b"PVRT"):
        return "pvr-texture"
    if len(blob) >= 4 and 0 < struct.unpack_from("<I", blob, 0)[0] <= 512:
        # candidate count-prefixed table (e.g. WPLMOT, UGMEDMDL)
        return "count-table"
    return "headerless"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Project Justice (USA) DC analysis")
    ap.add_argument("first_read", help="path to 1ST_READ.BIN")
    ap.add_argument("--uplmdl-entry", help="path to one UPLMDL entry (.bin)")
    ap.add_argument("--wplmot-entry", help="path to one WPLMOT entry (.bin)")
    args = ap.parse_args(argv)

    exe = Path(args.first_read).read_bytes()
    recs = character_table(exe)
    print("character table: %d records" % len(recs))
    for r in recs:
        print("  [%02x] grp=%02x %-14s va=0x%08x" % (r["idx"], r["group"], r["name"], r["va"]))
    roster = playable_roster(exe)
    print("playable roster (%d): %s" % (len(roster), " ".join(roster)))

    if args.uplmdl_entry:
        blob = Path(args.uplmdl_entry).read_bytes()
        flags, offsets = uplmdl_pointers(blob)
        print("UPLMDL header: %d (flag,offset) records" % len(offsets))
        print("  flags  :", " ".join("%04x" % f for f in flags))
        print("  offsets:", " ".join("%04x" % o for o in offsets))

    if args.wplmot_entry:
        blob = Path(args.wplmot_entry).read_bytes()
        offs = wplmot_offsets(blob)
        print("WPLMOT: %d offsets, first=%04x last=%04x" % (len(offs), offs[0], offs[-1]))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
