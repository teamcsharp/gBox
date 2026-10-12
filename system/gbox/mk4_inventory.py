"""Exact-build inventory for Mortal Kombat 4 (USA), N64 (Midway/Eurocom, NM4E rev 0).

The owned HyperSpin zip holds one ``.n64``-named member that is really
byte-swapped v64 data, so the ROM is always read through
:func:`gbox.n64_rom.read` (normalised big-endian z64).  The build is NM4E
rev 0 (internal name ``MORTAL KOMBAT 4``), CIC-NUS-6102, 16 MiB.

Layout recovered from the ROM itself (nothing written back to the share):

* IPL3 loads ROM 0x1000.. to 0x80000400.  The entry stub clears BSS
  0x80050180 (+0xD6770) and jumps to 0x800004D0, so the resident
  boot/code/text segment is ROM 0x1000-0x12FDB8 (RAM = ROM + 0x7FFFF400).
* A boot-time patch table at ROM 0x12FDB8-0x132800 lists 1353
  ``{slot, value}`` pairs.  Slots are ROM cells (0x1FFC48-0x20241C) or RAM
  cells (0x8004xxxx); values are ROM or RAM addresses.  The ROM slot
  arrays themselves hold high-entropy (encrypted/undecoded) words, so the
  table is the game's authoritative pointer data.  Its consumer is the
  analysis stage (Ghidra); this module only maps and counts it.
* The 15 story fighters' bios are plaintext at ROM 0x4B4C8-0x4CB40 (name +
  bio text, one NUL-terminated block per fighter).  Goro's bio is at
  0x4CB40 and Noob Saibot is referenced by the "KODE 13: NOOB SAIBOT MODE"
  string at 0x121349; neither is story-playable.
* Audio banks are ``N64 WaveTables`` blobs (41 found, 0x249884-0x5E1F64).
* The asset region 0x132800-0xEB0000 holds mid-entropy data (vertex/
  texture-like) up to ~0xB40000 and near-uniform entropy (encrypted or
  dense-packed) at 0xB40000-0xEB0000.  ROM 0x0000EB00 onward is 0xFF
  padding.  No plaintext file-name table exists anywhere in the ROM; data
  is addressed through the patch table and hard-coded offsets in code.

``python -m gbox.mk4_inventory SOURCE.zip --out manifest.json`` writes the
manifest.  It refuses any other ROM (gBox mods included) unless
``strict=False``.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile
import zlib

from . import n64_rom
from .mkmyth_inventory import decode_entry, parse_header  # shared N64 header/entry helpers

GAME_ID = "3e52c76354e8c5bb"
TITLE = "Mortal Kombat 4 (USA)"

# Exact build identity (normalised z64), pinned from the owned source.
KNOWN = {
    "z64_sha1": "f47d05bbd1bcadddff2ec7a21bc2e795cbef9f9b",
    "z64_md5": "c70b91430866300ce38b49098019ef9d",
    "z64_size": 0x1000000,
    "game_code": "NM4E",
    "version": 0,
}
OWNED_ZIP_SHA256 = "7b0b8006ad247a4da88e3968b9569f90477fe4b6f6e7d405e11f55125f456ebf"

RAM_DELTA = 0x7FFFF400          # resident segment: RAM = ROM + RAM_DELTA
PATCH_ANCHOR = 0x12FDD8         # interior entry of the boot patch table
BIO_NAMES = {                   # ROM offset -> fighter name (story bios, in order)
    0x4B4C8: "SCORPION", 0x4B5DC: "RAIDEN", 0x4B740: "SONYA BLADE",
    0x4B8AC: "LIU KANG", 0x4BA68: "SUB ZERO", 0x4BC00: "FUJIN",
    0x4BD50: "SHINNOK", 0x4BEC0: "QUAN CHI", 0x4BFF0: "REPTILE",
    0x4C11C: "KAI", 0x4C22C: "TANYA", 0x4C3E0: "JAX", 0x4C520: "REIKO",
    0x4C608: "JOHNNY CAGE", 0x4C7A8: "JAREK",
}
GORO_BIO = 0x4CB40
NOOB_KODE = 0x121349
WAVETABLES = b"N64 WaveTables"

# crc32 of IPL3 (ROM 0x40-0x1000) -> CIC chip (same table as MK Mythologies).
IPL3_CIC = {
    0x6170A4A1: "6101", 0x90BB6CB5: "6102", 0x0B050EE0: "6103",
    0x98BC2C86: "6105", 0xACC8580A: "6106", 0x009E9EA3: "7102",
}
_M = 0xFFFFFFFF


class WrongBuild(ValueError):
    """Raised when the ROM is not the pinned NM4E rev 0 build."""


def rom_to_ram(off: int) -> int:
    return (off + RAM_DELTA) & _M


def ipl3_cic(rom: bytes) -> tuple[str | None, int]:
    crc = zlib.crc32(rom[0x40:0x1000]) & _M
    return IPL3_CIC.get(crc), crc


def _ok_pair(a: int, b: int) -> bool:
    if a == b == 0:
        return False
    return (0x1000 <= a < 0x210000 or 0x80000000 <= a < 0x80800000) and \
           (0x1000 <= b < 0x210000 or 0x80000000 <= b < 0x80800000)


def patch_table(rom: bytes) -> dict:
    """Map the boot patch table around PATCH_ANCHOR: consecutive
    {slot, value} u32 pairs whose slot and value are ROM or RAM addresses."""
    words = struct.unpack_from(">%dI" % (len(rom) // 4), rom, 0)
    n = len(words)

    def ok_at(i: int) -> bool:
        return i + 1 < n and _ok_pair(words[i], words[i + 1])

    i = PATCH_ANCHOR // 4
    while i - 2 >= 0 and ok_at(i - 2):
        i -= 2
    j = PATCH_ANCHOR // 4 + 2
    while ok_at(j) and j - i < 20000:
        j += 2
    pairs = [(words[k], words[k + 1]) for k in range(i, j, 2)]
    slots = [a for a, _ in pairs]
    values = [b for _, b in pairs]
    return {
        "start": i * 4,
        "end": j * 4,
        "entries": len(pairs),
        "first": pairs[0],
        "last": pairs[-1],
        "rom_slots": sum(a < 0x210000 for a in slots),
        "ram_slots": sum(a >= 0x80000000 for a in slots),
        "rom_values": sum(b < 0x210000 for b in values),
        "ram_values": sum(b >= 0x80000000 for b in values),
    }


def audio_banks(rom: bytes) -> list[int]:
    out, pos = [], 0
    while True:
        p = rom.find(WAVETABLES, pos)
        if p < 0:
            return out
        out.append(p)
        pos = p + 1


def bios(rom: bytes) -> list[dict]:
    """The 15 story fighters: pinned name offsets + following bio text."""
    out = []
    for off, name in sorted(BIO_NAMES.items()):
        end = rom.find(b"\x00", off + len(name))
        text = rom[off:end].decode("ascii", "replace")
        out.append({"name": name, "offset": off, "text": text})
    return out


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = collections.Counter(data)
    n = len(data)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def layout(rom: bytes) -> dict:
    pt = patch_table(rom)
    buckets = []
    for off in range(pt["end"], 0xEB0000, 0x10000):
        e = entropy(rom[off:off + 0x10000])
        kind = "low" if e < 6.6 else ("mid" if e < 7.4 else "high")
        buckets.append({"start": off, "end": min(off + 0x10000, 0xEB0000),
                        "entropy": round(e, 3), "kind": kind})
    return {
        "boot": {"start": 0x1000, "end": pt["start"]},
        "patch_table": pt,
        "bios": {"start": min(BIO_NAMES), "end": GORO_BIO + 0x40},
        "kode_text": {"start": 0x1212F0, "end": 0x1214A0},
        "assets": {"start": pt["end"], "end": 0xEB0000, "buckets": buckets},
        "audio_banks": audio_banks(rom),
        "padding": [0xEB0000, 0x1000000],
    }


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
        raise WrongBuild("not the owned NM4E rev 0 build (%s)" % ", ".join(bad))


def inventory(path: str | Path, strict: bool = True) -> dict:
    src, rom = load(path)
    header = parse_header(rom)
    if strict:
        check_build(src, header)
    cic, ipl3_crc = ipl3_cic(rom)
    entry = decode_entry(rom)
    fighters = bios(rom)
    assert [f["name"] for f in fighters] == list(
        name for _, name in sorted(BIO_NAMES.items()))
    return {
        "game_id": GAME_ID,
        "title": TITLE,
        "platform": "n64",
        "source": src,
        "build": KNOWN,
        "header": header,
        "boot": {"cic": cic, "ipl3_crc32": "%08x" % ipl3_crc},
        "entry": entry,
        "layout": layout(rom),
        "characters": {
            "story_fighters": [f["name"] for f in fighters],
            "bios": fighters,
            "goro_bio_offset": GORO_BIO,
            "noob_saibot_kode_offset": NOOB_KODE,
            "full_roster": [f["name"] for f in fighters] + ["GORO", "NOOB SAIBOT"],
        },
        "launch": {
            "platform": "n64",
            "cic": cic or "unknown",
            "core_windows": "parallel_n64 (angrylion gfx needs LLE cxd4 RSP)",
            "core_linux": "mupen64plus",
            "agent_audio_rule": "agent runs set active playback to 2%",
        },
        "next_step": (
            "analysis: build the correct-architecture Ghidra project for NM4E rev 0; "
            "locate the boot code that consumes the 0x%X patch table and the character "
            "asset loader/offset tables." % PATCH_ANCHOR),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exact-build inventory for MK4 (USA), N64")
    ap.add_argument("source", help="owned zip (or ROM)")
    ap.add_argument("--out", help="write manifest JSON here")
    ap.add_argument("--no-strict", action="store_true", help="allow non-owned builds")
    args = ap.parse_args(argv)
    m = inventory(args.source, strict=not args.no_strict)
    text = json.dumps(m, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
