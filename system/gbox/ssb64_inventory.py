"""Inventory the owned Super Smash Bros. (Europe) (En,Fr,De) N64 build.

Super Smash Bros. stores ~2.1k relocatable asset files in a table of
12-byte LBTableEntry records (src/lb/lbreloc.c in the US decompilation
https://github.com/VetriTheRetri/ssb-decomp-re). Layout of one entry,
all big-endian:

    u32  flags          bit31: is_compressed (VPK0); bits30..0: data_offset,
                       ROM offset of the file data relative to the end of
                       the table (rom_table_hi).
    u16  reloc_intern_offset   word offset of the internal relocation chain
                       inside the file data (0xFFFF = none).
    u16  compressed_size       file size in words (stored form).
    u16  reloc_extern_offset   word offset of the external relocation chain
                       inside the file data (0xFFFF = none).
    u16  decompressed_size     size in words after VPK0 decompression
                       (== compressed_size when not compressed).

File data begins immediately after the table: rom_table_hi =
table_addr + (file_count + 1) * 12. The decompressed_size stored in the
table counts only the *words* of the file body; for compressed files the
VPK0 stream starts with a 4-byte big-endian size that equals
decompressed_size * 4. Compressed files use the VPK0 codec
(src/sys/dma.c syDmaDecodeVpk0): u32 BE size, u8 sample method, two
Huffman trees (offsets, lengths), then the LZ bitstream (MSB first).

File IDs -> asset names are taken from the US decomp's
tools/relocFileDescriptions.us.txt (shipped as ssb64_names_us.txt); the
EUR build shares the same file set. Character files are IDs 202..250.

CLI:
    python -m gbox.ssb64_inventory ROM.z64 --out manifest.json

ROMs must be normalized big-endian .z64 (see gbox.n64_rom.normalize).
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ENTRY_SIZE = 12
TABLE_SCAN_LO = 0x150000
TABLE_SCAN_HI = 0xB00000
TABLE_MAX_FILES = 4096
EXPECTED_FILES_LO = 2000
EXPECTED_FILES_HI = 2400

_NAMES_FILE = Path(__file__).with_name("ssb64_names_us.txt")

# Fighter file IDs and their meaning (from the US decomp descriptions).
FIGHTERS = {
    "mario":   (202, 204), "mmario": (205, 206), "nmario":  (207, 207),
    "fox":     (208, 210), "nfox":   (211, 211),
    "donkey":  (212, 213), "ndonkey": (214, 214), "gdonkey": (215, 215),
    "samus":   (216, 218), "nsamus": (219, 219),
    "luigi":   (220, 222), "nluigi": (223, 223),
    "link":    (224, 226), "nlink":  (227, 227),
    "kirby":   (228, 230), "nkirby": (231, 231),
    "purin":   (232, 233), "npurin": (234, 234),
    "captain": (235, 236), "ncaptain": (237, 237),
    "ness":    (238, 240), "nness":  (241, 241),
    "pikachu": (242, 244), "npikachu": (245, 245),
    "yoshi":   (246, 247), "nyoshi": (248, 248),
    "boss":    (249, 250),  # Master Hand
}
FIGHTERS_COSTUMES = 4  # default + red/blue/green team palettes per fighter

# Fighting Polygon Team: low-poly variants, one per fighter.
POLYGON_TEAM = (
    "nmario", "nfox", "ndonkey", "nsamus", "nluigi", "nlink",
    "nkirby", "npurin", "ncaptain", "nness", "npikachu", "nyoshi",
)
ROSTER = tuple(
    name for name in FIGHTERS
    if name not in POLYGON_TEAM and name not in ("mmario", "gdonkey", "boss")
)


@dataclass
class TableEntry:
    file_id: int
    data_offset: int
    is_compressed: bool
    reloc_intern: int
    compressed_size: int
    reloc_extern: int
    decompressed_size: int

    @property
    def stored_bytes(self) -> int:
        return self.compressed_size * 4

    @property
    def decompressed_bytes(self) -> int:
        return self.decompressed_size * 4


def parse_entry(raw: bytes, file_id: int) -> TableEntry:
    if len(raw) != ENTRY_SIZE:
        raise ValueError(f"entry {file_id}: {len(raw)} bytes, want {ENTRY_SIZE}")
    flags, reloc_intern, compressed_size, reloc_extern, decompressed_size = struct.unpack(
        ">IHHHH", raw)
    return TableEntry(
        file_id=file_id,
        data_offset=flags & 0x7FFFFFFF,
        is_compressed=bool(flags & 0x80000000),
        reloc_intern=reloc_intern,
        compressed_size=compressed_size,
        reloc_extern=reloc_extern,
        decompressed_size=decompressed_size,
    )


def _entry_plausible(e: TableEntry, data_end: int, data_begin: int) -> bool:
    if e.compressed_size == 0:
        return False
    if e.decompressed_size == 0:
        return False
    if e.compressed_size > e.decompressed_size + 0x1000:
        # VPK0 can expand a little over the count rounding, but not wildly.
        return False
    if data_begin + e.data_offset + e.stored_bytes > data_end:
        return False
    # Relocation chains are walked in the DECOMPRESSED buffer
    # (ram_dst + reloc * 4 in lbRelocLoadAndRelocFile), so word offsets
    # are bounded by decompressed_size, not compressed_size.
    for reloc in (e.reloc_intern, e.reloc_extern):
        if reloc != 0xFFFF and reloc > e.decompressed_size:
            return False
    return True


def load_names() -> dict[int, str]:
    names: dict[int, str] = {}
    if not _NAMES_FILE.is_file():
        return names
    for line in _NAMES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        tag, _, name = line[1:].partition(":")
        try:
            names[int(tag)] = name.strip()
        except ValueError:
            continue
    return names


def locate_table(rom: bytes) -> tuple[int, int] | None:
    """Find (table_addr, file_count) of the LBTableEntry table.

    Scans for a run of plausible entries long enough to be the file table
    and validates that the first entry's data starts right at the table
    end (entry 0, MNCommon, always has data_offset 0). Returns None when
    no coherent table is found.
    """
    n = len(rom)
    best = None
    for cand in range(TABLE_SCAN_LO, min(TABLE_SCAN_HI, n - ENTRY_SIZE), 4):
        # Entry 0 of the real table has data_offset 0, so its flags word
        # is either 0x00000000 or 0x80000000. Strong prefilter.
        flags0 = int.from_bytes(rom[cand:cand + 4], "big")
        if flags0 not in (0x00000000, 0x80000000):
            continue
        count = 0
        for fid in range(TABLE_MAX_FILES):
            off = cand + fid * ENTRY_SIZE
            if off + ENTRY_SIZE > n:
                break
            e = parse_entry(rom[off:off + ENTRY_SIZE], fid)
            if not _entry_plausible(e, n, 0):
                break
            count += 1
        if count < EXPECTED_FILES_LO:
            continue
        # Data begins right after count+1 entries.
        data_begin = cand + (count + 1) * ENTRY_SIZE
        if data_begin > n:
            continue
        # Validate the first 64 and the last 8 entries against the real
        # data window, and require entry 0 to start at data_begin.
        first = parse_entry(rom[cand:cand + ENTRY_SIZE], 0)
        if first.data_offset != 0:
            continue
        ok = True
        for fid in list(range(min(64, count))) + list(range(max(0, count - 8), count)):
            off = cand + fid * ENTRY_SIZE
            e = parse_entry(rom[off:off + ENTRY_SIZE], fid)
            if not _entry_plausible(e, n, data_begin):
                ok = False
                break
        if not ok:
            continue
        if best is None or count > best[1]:
            best = (cand, count)
        if count > EXPECTED_FILES_HI:
            break
    return best


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
                        value = sample1
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


def inventory(rom_path: str | Path, out: str | Path | None = None) -> dict:
    rom = Path(rom_path).read_bytes()
    located = locate_table(rom)
    if located is None:
        raise ValueError("no LBTableEntry table found; is this a normalized SSB64 z64 ROM?")
    table_addr, file_count = located
    data_begin = table_addr + (file_count + 1) * ENTRY_SIZE
    names = load_names()

    files = []
    for fid in range(file_count):
        off = table_addr + fid * ENTRY_SIZE
        e = parse_entry(rom[off:off + ENTRY_SIZE], fid)
        files.append({
            "id": fid,
            "name": names.get(fid, "unknown"),
            "rom_offset": data_begin + e.data_offset,
            "stored_bytes": e.stored_bytes,
            "decompressed_bytes": e.decompressed_bytes,
            "compressed": e.is_compressed,
            "reloc_intern": None if e.reloc_intern == 0xFFFF else e.reloc_intern,
            "reloc_extern": None if e.reloc_extern == 0xFFFF else e.reloc_extern,
        })

    fighters = {}
    for name, (lo, hi) in FIGHTERS.items():
        fighters[name] = files[lo:hi + 1]

    manifest = {
        "game": "Super Smash Bros. (Europe) (En,Fr,De)",
        "platform": "n64",
        "rom_bytes": len(rom),
        "table_addr": table_addr,
        "file_count": file_count,
        "data_begin": data_begin,
        "compressed_files": sum(1 for f in files if f["compressed"]),
        "raw_files": sum(1 for f in files if not f["compressed"]),
        "characters": {
            "roster": sorted(
                k for k in FIGHTERS if not k.startswith(("n", "m", "g"))),
            "variants": ["mmario", "gdonkey"],
            "polygon_team": [k for k in FIGHTERS if k.startswith("n")],
            "bosses": ["boss"],
            "costumes_per_fighter": FIGHTERS_COSTUMES,
        },
        "fighters": fighters,
        "names_ref": "US decomp relocFileDescriptions (IDs shared with this build)",
        "files": files,
    }
    if out is not None:
        Path(out).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Inventory an SSB64 (Europe) z64 ROM")
    ap.add_argument("rom")
    ap.add_argument("--out", default="ssb64_manifest.json")
    args = ap.parse_args()
    m = inventory(args.rom, args.out)
    print(
        f"table=0x{m['table_addr']:X} files={m['file_count']} "
        f"data=0x{m['data_begin']:X} "
        f"compressed={m['compressed_files']} raw={m['raw_files']} -> {args.out}")


if __name__ == "__main__":
    main()
