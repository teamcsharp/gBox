#!/usr/bin/env python3
"""AES-XTS plaintext probe for encrypted Switch XCI/NCSD card images.

Usage:
  python3 scripts/nsw_xts_probe.py <card_image> <prod_keys_file> [--sectors N]

Reads header_key from a prod.keys file (operator-provisioned; path given on
the CLI, never hard-coded), decrypts candidate 0x200-aligned regions with
AES-128-XTS under three IV schemes, and reports which region yields known
container magics (NCSD/XCI0/HEAD/HFS0/PFS0/NCA3).  When a header is found it
is parsed and hex-dumped so the partition table / file table can be walked.

Read-only: never writes to the card image.  Exit code 0 when at least one
plausible plaintext region was identified, 1 when nothing matched.
"""
from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.formats.nsw_xts import SECTOR_SIZE, decrypt_sectors, find_magic

CANDIDATE_REGIONS = [
    0x0000, 0x1000, 0x2000, 0x4000, 0x7000, 0x8000,
    0x10000, 0x14000, 0x18000, 0x20000, 0x30000, 0x40000,
]
IV_MODES = ("sector", "offset", "zero")


def read_header_key(keys_path: str) -> bytes:
    text = Path(keys_path).read_text(errors="replace")
    m = re.search(r"header_key\s*=\s*([0-9a-fA-F]{64})", text)
    if not m:
        sys.exit("header_key not found in %s" % keys_path)
    return bytes.fromhex(m.group(1))


def hexdump(data: bytes, label: str, width: int = 32) -> None:
    print("---- %s (first 0x%x bytes) ----" % (label, len(data)))
    for i in range(0, len(data), width):
        chunk = data[i:i + width]
        hexs = " ".join("%02x" % b for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print("0x%05x  %-78s  %s" % (i, hexs, asc))


def parse_ncsd_header(bl: bytes) -> None:
    _, size, revision, pcount = struct.unpack_from("<IQHH", bl, 0)
    print("NCSD: size=0x%x revision=%d partition_count=%d" % (size, revision, pcount))
    hexdump(bl[0x100:0x300], "NCSD partition-table area @0x100")


def parse_xci_header(bl: bytes) -> None:
    size, sector, hsize = struct.unpack_from("<QHH", bl, 8)
    print("XCI0: image_size=0x%x sector_size=0x%x header_size=0x%x" % (size, sector, hsize))
    hexdump(bl[0x100:0x300], "XCI0 header tail @0x100")


def parse_hfs0_header(bl: bytes) -> None:
    fcount, stsize = struct.unpack_from("<II", bl, 8)
    print("HFS0: file_count=%d string_table_size=0x%x" % (fcount, stsize))
    hexdump(bl[0x100:0x280], "HFS0 file-table area @0x100")
    hexdump(bl[0x1000:0x1100], "HFS0 alt table area @0x1000")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("card")
    ap.add_argument("prod_keys")
    ap.add_argument("--sectors", type=int, default=4, help="sectors to decrypt per region")
    args = ap.parse_args()

    key = read_header_key(args.prod_keys)
    card = Path(args.card)
    print("card: %s (%d bytes)" % (card, card.stat().st_size))

    best = None
    for region in CANDIDATE_REGIONS:
        for mode in IV_MODES:
            with open(card, "rb") as f:
                f.seek(region)
                raw = f.read(args.sectors * SECTOR_SIZE)
            if len(raw) < SECTOR_SIZE:
                continue
            bl = decrypt_sectors(raw, key, region, args.sectors, mode=mode)
            hits = find_magic(bl)
            for off, magic, label in hits:
                abs_off = region + off
                print("HIT  region=0x%x mode=%-6s magic=%s @abs 0x%x  (%s)"
                      % (region, mode, magic, abs_off, label))
                rank = 0 if (magic in ("NCSD", "XCI0", "HEAD", "HFS0", "PFS0") and off < 0x100) else 1
                cand = (rank, abs_off, region, mode, magic, off, bl)
                if best is None or (rank, abs_off) < (best[0], best[1]):
                    best = cand

    if best is None:
        print("NO plaintext magic found in candidate regions; scanning first 0x40000 at sector stride...")
        with open(card, "rb") as f:
            for base in range(0, 0x40000, SECTOR_SIZE):
                f.seek(base)
                raw = f.read(SECTOR_SIZE)
                for mode in IV_MODES:
                    bl = decrypt_sectors(raw, key, base, 1, mode=mode)
                    for off, magic, label in find_magic(bl):
                        print("SCAN HIT base=0x%x mode=%-6s magic=%s @abs 0x%x (%s)"
                              % (base, mode, magic, base + off, label))
                        if magic in ("NCSD", "XCI0", "HFS0") and off < 0x100 and best is None:
                            best = (0, base + off, base, mode, magic, off, bl)
        if best is None:
            print("RESULT: no plausible plaintext region identified")
            return 1

    rank, abs_off, region, mode, magic, off, bl = best
    print("\nBEST: region=0x%x mode=%s magic=%s @abs 0x%x" % (region, mode, magic, abs_off))
    hexdump(bl, "best decrypted block (region 0x%x, %s IV)" % (region, mode))
    if magic == "NCSD" and off == 0:
        parse_ncsd_header(bl)
    elif magic == "XCI0" and off == 0:
        parse_xci_header(bl)
    elif magic == "HFS0":
        parse_hfs0_header(bl[off:])
    elif magic == "PFS0":
        hexdump(bl[off:off + 0x200], "PFS0 block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
