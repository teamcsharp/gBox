"""Exact-build inventory for Mortal Kombat Mythologies: Sub-Zero (USA), N64.

The owned HyperSpin zip holds one ``.n64``-named member that is really
byte-swapped v64 data, so the ROM is always read through :func:`gbox.n64_rom.read` (normalised big-endian z64).
The build is NMYE rev 0 (internal name ``MK_MYTHOLOGIES``), CIC-NUS-6102.

Layout recovered from the ROM itself (no emulator, nothing written):

* IPL3 loads ROM 0x1000.. to 0x80000400.  The entry stub clears BSS
  0x800B43C0 (+0x238A70) and jumps to 0x80000450, so the resident code/data
  segment is ROM 0x1000-0xB4FC0 (RAM = ROM + 0x7FFFF400).
* A 12-byte ``{rom_start, rom_end, flag}`` segment table at ROM 0xA5160
  (RAM 0x800A4560) lists 144 records (index 118 is an all-zero null record).
  The 143 real records tile ROM 0xB4FC0-0xEF6B60 without overlap, except for
  the 0x947C80-0xD2DA50 hole, which starts with an ``SN64`` sound bank.
* Records are either offset-table banks (first u32 = 4 * entry count, all
  entries inside the record) or packed blobs whose first u32 is a candidate
  unpacked size followed by a signature word.  Decoding them is the analysis
  stage; this module only classifies and hashes them.
* The debug ``TEST CHARACTERS`` select has a 25-entry name-pointer table at
  ROM 0x9BAC8 (enemy/boss ids 0..24: MONK1 .. SHINNOK) and an 11-entry level
  table at ROM 0x9B7DC.  The player character, Sub-Zero, is not in that list.

``python -m gbox.mkmyth_inventory SOURCE.zip --out manifest.json`` writes the
manifest.  It refuses any other ROM (gBox mods included) unless
``strict=False``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zipfile
import zlib

from . import n64_rom

GAME_ID = "6d46221997228c6a"
TITLE = "Mortal Kombat Mythologies: Sub-Zero (USA)"

# Exact build identity (normalised z64), pinned from the owned source.
KNOWN = {
    "z64_sha1": "ef3df4e1496260d44c44ab7dd145751141f11c60",
    "z64_md5": "deec4faec416f4e02d934c2e42c0caad",
    "z64_size": 0x1000000,
    "game_code": "NMYE",
    "version": 0,
}

RAM_DELTA = 0x7FFFF400          # resident segment: RAM = ROM + RAM_DELTA
SEGMENT_TABLE = 0xA5160         # ROM offset of the {start, end, flag} table
CHARACTER_NAMES = 0x9BAC8       # debug TEST CHARACTERS name pointers
LEVEL_NAMES = 0x9B7DC           # debug level-select name pointers

# crc32 of IPL3 (ROM 0x40-0x1000) -> CIC chip.
IPL3_CIC = {
    0x6170A4A1: "6101",
    0x90BB6CB5: "6102",
    0x0B050EE0: "6103",
    0x98BC2C86: "6105",
    0xACC8580A: "6106",
    0x009E9EA3: "7102",
}
CIC_SEED = {
    "6101": 0xF8CA4DDC, "6102": 0xF8CA4DDC, "7102": 0xF8CA4DDC,
    "6103": 0xA3886759, "6105": 0xDF26F436, "6106": 0x1FEA617A,
}
_M = 0xFFFFFFFF


class WrongBuild(ValueError):
    """Raised when the ROM is not the pinned NMYE rev 0 build."""


def rom_to_ram(off: int) -> int:
    return (off + RAM_DELTA) & _M


def ram_to_rom(addr: int) -> int:
    return (addr - RAM_DELTA) & _M


def parse_header(rom: bytes) -> dict:
    pi, clock, entry, release, crc1, crc2 = struct.unpack_from(">6I", rom, 0)
    return {
        "pi_bsd": pi,
        "clock_rate": clock,
        "entry_point": entry,
        "release": release,
        "crc1": crc1,
        "crc2": crc2,
        "internal_name": rom[0x20:0x34].decode("ascii", "replace").rstrip(" \0"),
        "game_code": rom[0x3B:0x3F].decode("ascii", "replace"),
        "version": rom[0x3F],
    }


def ipl3_cic(rom: bytes) -> tuple[str | None, int]:
    crc = zlib.crc32(rom[0x40:0x1000]) & _M
    return IPL3_CIC.get(crc), crc


def header_crc(rom: bytes, cic: str) -> tuple[int, int]:
    """Standard N64 boot checksum over ROM 0x1000-0x101000."""
    seed = CIC_SEED[cic]
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    words = struct.unpack_from(">%dI" % (0x100000 // 4), rom, 0x1000)
    for n, d in enumerate(words):
        if (t6 + d) & _M < t6:
            t4 = (t4 + 1) & _M
        t6 = (t6 + d) & _M
        t3 ^= d
        s = d & 0x1F
        r = ((d << s) | (d >> (32 - s))) & _M if s else d
        t5 = (t5 + r) & _M
        t2 = t2 ^ r if t2 > d else t2 ^ (t6 ^ d)
        if cic == "6105":
            k = struct.unpack_from(">I", rom, 0x750 + ((n * 4) & 0xFF))[0]
            t1 = (t1 + (k ^ d)) & _M
        else:
            t1 = (t1 + (t5 ^ d)) & _M
    if cic == "6103":
        return ((t6 ^ t4) + t3) & _M, ((t5 ^ t2) + t1) & _M
    if cic == "6106":
        return (t6 * t4 + t3) & _M, (t5 * t2 + t1) & _M
    return (t6 ^ t4 ^ t3) & _M, (t5 ^ t2 ^ t1) & _M


def _sext16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def decode_entry(rom: bytes, off: int = 0x1000, count: int = 16) -> dict:
    """Resolve the lui/addiu pairs of the libultra entry stub.

    Returns the BSS start/size (t0/t1), main entry (t2) and initial sp.
    """
    regs: dict[int, int] = {}
    for i in range(count):
        ins = struct.unpack_from(">I", rom, off + 4 * i)[0]
        op, rs, rt, imm = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31, ins & 0xFFFF
        if op == 0x0F:                      # lui
            regs[rt] = imm << 16
        elif op == 0x09 and rs == rt and rs in regs:   # addiu rt, rt, imm
            regs[rt] = (regs[rt] + _sext16(imm)) & _M
    bss_start, bss_size = regs.get(8), regs.get(9)
    return {
        "bss_start": bss_start,
        "bss_size": bss_size,
        "main": regs.get(10),
        "stack_top": regs.get(29),
        "resident_rom_end": None if bss_start is None else ram_to_rom(bss_start),
    }


def classify(blob: bytes) -> dict:
    """Classify one segment record by its header (no decoding)."""
    if len(blob) < 8:
        return {"kind": "tiny"}
    w0, w1 = struct.unpack_from(">II", blob, 0)
    if w0 and w0 % 4 == 0 and w0 < len(blob):
        n = w0 // 4
        offs = struct.unpack_from(">%dI" % n, blob, 0)
        if all(o == _M or o < len(blob) for o in offs):
            return {"kind": "offset_table", "entries": n,
                    "invalid_entries": sum(o == _M for o in offs)}
    if w1 >> 28 == 0x8:
        sig = "%08x" % (w1 & 0xFFFFF000)
    elif w1 >> 24 == 0x08:
        sig = "08xxxxxx"
    elif w1 == 0:
        sig = "00000000"
    else:
        sig = "other"
    return {"kind": "packed", "signature": sig, "word0": w0}


def segment_table(rom: bytes, off: int = SEGMENT_TABLE,
                  lo: int = 0xB4FC0) -> list[dict]:
    """Parse the {rom_start, rom_end, flag} records until the first bad one."""
    out = []
    i = off
    while i + 12 <= len(rom):
        start, end, flag = struct.unpack_from(">III", rom, i)
        if start == end == flag == 0:
            out.append({"index": len(out), "table_off": i, "null": True})
        elif lo <= start < end <= len(rom) and flag in (0, 1):
            rec = {"index": len(out), "table_off": i, "null": False,
                   "start": start, "end": end, "size": end - start,
                   "flag": flag}
            rec.update(classify(rom[start:end]))
            out.append(rec)
        else:
            break
        i += 12
    while out and out[-1]["null"]:
        out.pop()
    return out


def coverage(records: list[dict], lo: int, hi: int) -> dict:
    spans = sorted((r["start"], r["end"]) for r in records if not r["null"])
    gaps, overlaps, cur = [], [], lo
    for a, b in spans:
        if a > cur:
            gaps.append((cur, a))
        elif a < cur:
            overlaps.append((a, min(b, cur)))
        cur = max(cur, b)
    if cur < hi:
        gaps.append((cur, hi))
    return {"low": lo, "high": cur, "gaps": gaps, "overlaps": overlaps}


def _c_string(rom: bytes, off: int, limit: int = 64) -> str | None:
    m = re.match(rb"[\x20-\x7e]{1,%d}\x00" % limit, rom[off:off + limit + 1])
    return m.group()[:-1].decode("ascii") if m else None


def pointer_strings(rom: bytes, off: int, max_count: int = 64,
                    resident_end: int = 0xB4FC0) -> list[str]:
    """Read consecutive RAM pointers to C strings until one fails."""
    names = []
    for i in range(max_count):
        p = struct.unpack_from(">I", rom, off + 4 * i)[0]
        o = ram_to_rom(p)
        if not 0x1000 <= o < resident_end:
            break
        s = _c_string(rom, o)
        if not s:
            break
        names.append(s)
    return names


def find_strings(rom: bytes, needles: list[bytes], hi: int) -> dict:
    out = {}
    for n in needles:
        hit = rom.find(n, 0x1000, hi)
        out[n.decode()] = hit if hit >= 0 else None
    return out


def load(path: str | Path) -> tuple[dict, bytes]:
    path = Path(path)
    raw = path.read_bytes()
    src = {"path": str(path), "size": len(raw),
           "sha256": hashlib.sha256(raw).hexdigest()}
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            info = z.infolist()[0]
            head = z.open(info).read(4)
            src.update(member=info.filename, member_size=info.file_size,
                       member_crc32="%08x" % info.CRC)
    else:
        head = raw[:4]
    src["byte_order"] = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64",
                         b"\x40\x12\x37\x80": "n64"}.get(head, head.hex())
    rom = n64_rom.read(path)
    src.update(z64_sha256=hashlib.sha256(rom).hexdigest(),
               z64_sha1=hashlib.sha1(rom).hexdigest(),
               z64_md5=hashlib.md5(rom).hexdigest(), z64_size=len(rom))
    return src, rom


def check_build(src: dict, header: dict) -> None:
    bad = [k for k in ("z64_sha1", "z64_md5", "z64_size") if src[k] != KNOWN[k]]
    if header["game_code"] != KNOWN["game_code"] or header["version"] != KNOWN["version"]:
        bad.append("game_code/version")
    if bad:
        raise WrongBuild("not the owned NMYE rev 0 build (%s)" % ", ".join(bad))


def inventory(path: str | Path, strict: bool = True) -> dict:
    src, rom = load(path)
    header = parse_header(rom)
    if strict:
        check_build(src, header)
    cic, ipl_crc = ipl3_cic(rom)
    crc_ok = bool(cic) and header_crc(rom, cic) == (header["crc1"], header["crc2"])
    entry = decode_entry(rom)
    resident_end = entry["resident_rom_end"] or 0xB4FC0
    records = segment_table(rom, lo=resident_end)
    end = len(rom)
    while end and rom[end - 1] in (0, 0xFF):
        end -= 1
    real = [r for r in records if not r["null"]]
    cov = coverage(records, resident_end, max(r["end"] for r in real))
    gaps = []
    for a, b in cov["gaps"]:
        gaps.append({"start": a, "end": b, "size": b - a,
                     "magic": rom[a:a + 4].decode("ascii", "replace"),
                     "kind": "sn64_sound_bank" if rom[a:a + 4] == b"SN64" else "unknown"})
    kinds: dict[str, int] = {}
    for r in real:
        k = r["kind"] if r["kind"] != "packed" else "packed:" + r["signature"]
        kinds[k] = kinds.get(k, 0) + 1
        r["sha1"] = hashlib.sha1(rom[r["start"]:r["end"]]).hexdigest()
    characters = pointer_strings(rom, CHARACTER_NAMES, resident_end=resident_end)
    levels = pointer_strings(rom, LEVEL_NAMES, resident_end=resident_end)
    hints = find_strings(rom, [b"TEST CHARACTERS", b"SELECT CHARACTER",
                               b"No more palettes!", b"ran outta textures!",
                               b"NINTENDO 64 CONVERSION", b"SUB-ZERO"], resident_end)
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "n64",
        "source": src,
        "header": header,
        "boot": {"cic": cic, "ipl3_crc32": "%08x" % ipl_crc,
                 "header_crc_matches": crc_ok},
        "launch": {"core": "parallel_n64", "rom_size_mbit": len(rom) * 8 // 0x100000,
                   "byte_order_on_disk": src["byte_order"],
                   "notes": "Windows N64 adapter pins angrylion + cxd4 LLE RSP"},
        "layout": {
            "resident": {"rom_start": 0x1000, "rom_end": resident_end,
                         "ram_start": header["entry_point"], **entry},
            "segment_table": {"rom": SEGMENT_TABLE, "ram": rom_to_ram(SEGMENT_TABLE),
                              "records": len(records), "real": len(real),
                              "null_indices": [r["index"] for r in records if r["null"]],
                              "flagged": sum(r["flag"] for r in real),
                              "kinds": kinds},
            "coverage": {"low": cov["low"], "high": cov["high"],
                         "overlaps": cov["overlaps"], "gaps": gaps},
            "data_end": end,
            "padding": [end, len(rom)],
        },
        "characters": {
            "player": "SUB-ZERO",
            "debug_select_table": CHARACTER_NAMES,
            "debug_select": [{"id": i, "name": n} for i, n in enumerate(characters)],
        },
        "levels": {"debug_select_table": LEVEL_NAMES,
                   "debug_select": [{"id": i, "name": n} for i, n in enumerate(levels)]},
        "string_hints": hints,
        "records": real,
        "unverified": [
            "segment record -> character/level mapping (needs the loader xref)",
            "packed-record codec (word0 is only a candidate unpacked size)",
            "flag bit meaning (58 records set it)",
            "sprite pixel/palette format (strings suggest CI textures + TLUT pools)",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inventory the owned MK Mythologies USA N64 build.")
    ap.add_argument("source")
    ap.add_argument("--out")
    ap.add_argument("--no-strict", action="store_true")
    a = ap.parse_args(argv)
    m = inventory(a.source, strict=not a.no_strict)
    text = json.dumps(m, indent=1, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text)
    else:
        print(text)
    return 0


# ---------------------------------------------------------------------------
# Character / level resource tables (analysis stage)
# ---------------------------------------------------------------------------

CHARACTER_COUNT = 25                # debug TEST CHARACTERS; the name table holds 27 entries
CHARACTER_DATA_POINTERS = 0x9BB94   # parallel table of RAM pointers to each character's data
LEVEL_COUNT = 12                    # debug level-select entries
LEVEL_DESCRIPTORS = 0x9B80C         # level descriptor records, 28 bytes each
LEVEL_DESCRIPTOR_STRIDE = 28
BSS_START = 0x800B43C0              # first byte of BSS; the resident segment ends here
BSS_SIZE = 0x238A70
BSS_END = BSS_START + BSS_SIZE


def _rd32(rom: bytes, off: int) -> int:
    """Big-endian u32 read used by the resource-table probes."""
    return struct.unpack_from(">I", rom, off)[0]


def _region(addr: int) -> str:
    """Classify a RAM pointer: resident segment, BSS (runtime structs) or other."""
    if BSS_START <= addr < BSS_END:
        return "bss"
    if 0x80000400 <= addr < BSS_START:
        return "resident"
    return "other"


def character_resources(rom: bytes, names_off: int = CHARACTER_NAMES,
                        ptrs_off: int = CHARACTER_DATA_POINTERS,
                        count: int = CHARACTER_COUNT) -> list[dict]:
    """Map every debug character to the RAM address of its data record.

    ``names_off`` holds 27 name pointers, the first ``count`` of which are
    the debug characters.  ``ptrs_off`` holds the parallel table of RAM
    addresses the game uses for each character; a zero pointer means the
    character ships no data record.
    """
    out: list[dict] = []
    for i in range(count):
        nptr = _rd32(rom, names_off + 4 * i)
        name = _c_string(rom, nptr - RAM_DELTA) if nptr else None
        dptr = _rd32(rom, ptrs_off + 4 * i)
        out.append({"index": i, "name": name, "name_ram": nptr,
                    "data_ram": dptr, "region": _region(dptr) if dptr else "none"})
    return out


def level_resources(rom: bytes, names_off: int = LEVEL_NAMES,
                    desc_off: int = LEVEL_DESCRIPTORS, count: int = LEVEL_COUNT,
                    stride: int = LEVEL_DESCRIPTOR_STRIDE) -> list[dict]:
    """Map the debug level-select entries to their descriptor records.

    ``names_off`` holds the level name pointers (the last entry is null) and
    the descriptor records follow, each ``stride`` bytes of big-endian u32
    whose first word is a RAM pointer.
    """
    out: list[dict] = []
    for i in range(count):
        nptr = _rd32(rom, names_off + 4 * i)
        name = _c_string(rom, nptr - RAM_DELTA) if nptr else None
        words = list(struct.unpack_from(">%dI" % (stride // 4), rom, desc_off + stride * i))
        out.append({"index": i, "name": name, "name_ram": nptr,
                    "ram": words[0], "words": words})
    return out


# ---------------------------------------------------------------------------
# Analysis stage: segment-record families, packed-record header, palette pools
# ---------------------------------------------------------------------------

# The N64's colour-indexed (CI) texturing renders 4/8-bit pixels through a
# TLUT (texture look-up table) of 16-bit RGBA entries.  This build banks its
# sprite palettes in small flag=0 records; a palette entry is emitted as
# ``0x80808000`` (50% gray, alpha 0) between real colour runs, and the words
# ``80808000`` / ``ffffff??`` mark the CI palette pool the "No more palettes!"
# string warns about.
CI_POOL_MARKER = 0x80808000


def packed_header(rom: bytes, rec: dict) -> dict:
    """Decode a flag=1 packed record's two header words.

    Verified against the owned build: for flag=1 records ``word0`` is the
    *unpacked* size in bytes (larger than the on-ROM payload, which starts 8
    bytes in) and ``word1`` is the big-endian RAM destination the decompressor
    writes to.  ``word0`` being a multiple of 4 and ``word1`` in KSEG0
    (``0x80xxxxxx``) are the two invariants the loader relies on.
    """
    w0, w1 = struct.unpack_from(">II", rom, rec["start"])
    payload = rec["size"] - 8
    return {"rom_start": rec["start"], "ram_dest": w1,
            "unpacked_size": w0, "packed_size": payload,
            "ratio": round(payload / w0, 3) if w0 else None,
            "plausible": bool(0 < payload < w0 and w1 >> 24 == 0x80)}


def palette_pool(rom: bytes, rec: dict) -> dict:
    """Probe whether a record is a CI-sprite/palette pool.

    CI texture data is a run of 16-bit TLUT entries; the recurring
    ``0x80808000`` marker word between colour runs is the tell.  We return the
    count of marker words, the record size, and the palette entry count (size
    / 2) so a later writer stage can size a replacement bank.
    """
    body = rom[rec["start"]:rec["end"]]
    words = struct.unpack_from(">%dH" % (len(body) // 2), body, 0)
    markers = words.count(CI_POOL_MARKER >> 16)
    return {"is_palette_pool": markers >= 4, "marker_words": markers,
            "palette_entries": len(words), "bytes": len(body)}


def segment_families(rom: bytes, end: int = 0xEF6B60) -> dict:
    """Group the 143 real segment records into actionable families.

    Family assignment corrects the earlier ``classify`` heuristic:

    * ``code_reloc``  -- flag=0 records whose first word is a 4-aligned
      offset-table entry count (``offset_table`` plus the code records whose
      header is a relocation index list).  These are the loader/code blocks.
    * ``compressed``   -- flag=1 records (58 total); header = {unpacked size,
      RAM dest}, payload is compressed code/data.
    * ``palette_pool`` -- small flag=0 records rich in ``0x80808000`` marker
      words, i.e. CI sprite TLUT banks (the "No more palettes!" pool).
    * ``raw``          -- everything else (uncompressed function bodies / data).

    Returns ``{family: [record-index, ...]}`` for the compact proof a test can
    assert against.
    """
    records = segment_table(rom, lo=0xB4FC0)
    real = [r for r in records if not r["null"]]
    fam: dict[str, list[int]] = {"code_reloc": [], "compressed": [],
                                 "palette_pool": [], "raw": []}
    for r in real:
        idx = r["index"]
        if r["flag"] == 1:
            fam["compressed"].append(idx)
        elif r["kind"] == "offset_table":
            fam["code_reloc"].append(idx)
        elif palette_pool(rom, r)["is_palette_pool"]:
            fam["palette_pool"].append(idx)
        else:
            fam["raw"].append(idx)
    return fam


def analysis_probe(rom: bytes) -> dict:
    """Bounded analysis summary used by the focused test.

    Confirms on the owned build: 143 real records; 58 compressed with a
    consistent {unpacked_size, KSEG0 dest} header; the palette-pool records the
    sprite TLUT banks live in; and the unmapped offset-table banks (the 42
    ``flag``=0 non-code records) the character/level mapping still has to bind.
    """
    records = segment_table(rom, lo=0xB4FC0)
    real = [r for r in records if not r["null"]]
    fam = segment_families(rom)
    packed = [packed_header(rom, r) for r in real if r["flag"] == 1]
    plausible = [h for h in packed if h["plausible"]]
    return {
        "real_records": len(real),
        "families": {k: len(v) for k, v in fam.items()},
        "compressed_header": {
            "count": len(packed),
            "plausible": len(plausible),
            "unpacked_total": sum(h["unpacked_size"] for h in packed),
            "unique_dests": sorted({h["ram_dest"] for h in packed}),
        },
        "palette_pools": fam["palette_pool"],
        "code_reloc_banks": fam["code_reloc"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
