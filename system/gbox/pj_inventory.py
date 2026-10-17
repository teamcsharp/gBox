"""Project Justice (USA) Dreamcast inventory.

Owned source: the Hyperspin CHD ``Project Justice (USA).chd``
(sha256 723e033f1fc5dd7bf53d6b68723ae9d96f08c214c5291d90280f2fc9196ed5f8).
``chdman extractcd`` unpacks it to a Redump-style GDI next to the CHD
(``disc.gdi`` + ``disc01.bin``/``disc02.raw``/``disc03.bin``).

Disc: T-1219N V1.001, USA, 2001-01-26, Capcom (maker 1EAC), boots 1ST_READ.BIN.
Root holds 20 files: 15 CRI AFS archives + 4 BIN + 1 PVR. The AFS archives use the
standard CRI layout (``AFS\\0``, u32 entry count, interleaved u32 (offset, size) pairs,
data from 0x80000) and carry NO filename directory, so entries are positional.

Character chain (positional entries):
- UPLMDL.AFS   42 entries: per-player model files (float-heavy payload, no magic)
- XPLTEX.AFS  336 entries: per-player texture packs (8 per model slot)
- WPLMOT.AFS   92 entries: player motion files (u16 offset-table headers)
- YPLPACK.AFS  32 entries: player pack files
- UGMEDMDL.AFS 320 entries: small (~4-9 KB) medal/select models
- UDCSDM.AFS   471,859,200 B: NOT an AFS despite the extension (u32 0x4CB8 + dense
  s16 tables); large speech/sound data, outside the character model chain.

The model/motion/texture binary formats are unidentified at this stage; decoding
them is the analysis stage's first task. Roster names (BATSU, HINATA, KYOSUKE, ROY,
TIFFANY, BOMAN, DAIGO, RAN, ROBERTO, MOMO, YURIKA, NAGARE, EDGE, GAN, AKIRA, ZAKI,
KUROW, HAYATO, VATSU, ...) all appear in 1ST_READ.BIN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from gbox.gdrom import GDRom
from gbox.jgr import afs_entries

# owned-source identity, pinned to this exact build
SOURCE_CHD_SHA256 = "723e033f1fc5dd7bf53d6b68723ae9d96f08c214c5291d90280f2fc9196ed5f8"
FIRST_READ_SHA256 = "93cbcb3c88135ae1175837f919bed21655cf7d33d37bebe5c551beb81b4faad4"
FIRST_READ_LOAD_BASE = 0x8C010000  # standard SH-4 DC user-program base

# AFS archive name -> expected entry count on this exact build
CHAR_ARCHIVES = {
    "UPLMDL.AFS": 42,     # player model files
    "XPLTEX.AFS": 336,    # player texture packs (8 per model slot)
    "WPLMOT.AFS": 92,     # player motion files
    "YPLPACK.AFS": 32,    # player packs
    "UGMEDMDL.AFS": 320,  # medal/select models
}
OTHER_AFS = [
    "ODEMO.AFS", "SDEMO.AFS", "VSDEMO.AFS", "WGAME.AFS", "WISOUND.AFS",
    "WMENU.AFS", "ZADX0.AFS", "ZADX1.AFS", "ZADX2.AFS",
]
# UDCSDM.AFS is not an AFS (see module docstring)

ROSTER_NAMES = [
    "BATSU", "HINATA", "KYOSUKE", "ROY", "TIFFANY", "BOMAN", "DAIGO", "RAN",
    "ROBERTO", "MOMO", "YURIKA", "NAGARE", "EDGE", "GAN", "AKIRA", "ZAKI",
    "KUROW", "HAYATO", "RAIZO", "VATSU", "NATSU", "SHOMA",
]


def read_disc_file(gdi: str | Path, name: str) -> bytes:
    """Read one file from a Redump-style GDI via the on-main GDRom reader."""
    g = GDRom(Path(gdi))
    try:
        return g.read(name)
    finally:
        for f in g._fh.values():
            f.close()


def ip_bin(gdi: str | Path) -> bytes:
    """IP.BIN = the first 16 high-density sectors (LBA 45000..45015)."""
    g = GDRom(Path(gdi))
    try:
        return b"".join(g.sector(45000 + i) for i in range(16))[:0x8000]
    finally:
        for f in g._fh.values():
            f.close()


def ip_fields(ip: bytes) -> dict:
    """Parse the fields this build actually uses (offsets differ from the
    textbook layout: maker+device at 0x20, area+periph at 0x30)."""
    def text(off: int, n: int) -> str:
        return ip[off:off + n].decode("latin-1", "replace").strip("\x00 ").strip()
    return {
        "maker_device": text(0x20, 16),
        "area_periph": text(0x30, 16),
        "product_version": text(0x40, 16),
        "date": text(0x50, 16),
        "boot_file": text(0x60, 16),
        "periph2": text(0x70, 16),
        "title": text(0x80, 16),
    }


def sniff_afs(data: bytes) -> dict:
    """Header facts for one CRI AFS archive."""
    count, offsets, sizes = afs_entries(data)
    entries = []
    for i, (off, size) in enumerate(zip(offsets, sizes)):
        entries.append({
            "index": i,
            "offset": off,
            "size": size,
            "magic16": data[off:off + 16].hex(),
        })
    return {
        "count": count,
        "first_data_offset": offsets[0] if offsets else None,
        "entries": entries,
    }


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(gdi: str | Path, chd: str | Path | None = None,
              chd_sha256: str | None = None) -> dict:
    """Walk the owned disc and return the build manifest. Only reads; never writes."""
    gdi = Path(gdi)
    if chd is not None and chd_sha256 is None:
        chd_sha256 = _sha256_file(chd)
    g = GDRom(gdi)
    try:
        files = dict(sorted(g.files.items()))
        ip = ip_bin(gdi)
        first_read = g.read("1ST_READ.BIN")
        # count roster-name hits in the executable
        exe_names = {
            n: first_read.count(n.encode("latin-1"))
            for n in ROSTER_NAMES
        }
        archives = {}
        for name in list(CHAR_ARCHIVES) + OTHER_AFS:
            data = g.read(name)
            archives[name] = sniff_afs(data)
        udcsdm = g.read("UDCSDM.AFS")
        udcsdm_hdr = {
            "size": len(udcsdm),
            "u32_at_0": struct.unpack_from("<I", udcsdm, 0)[0],
            "magic16": udcsdm[:16].hex(),
            "is_afs": udcsdm[:4] == b"AFS\x00",
        }
    finally:
        for f in g._fh.values():
            f.close()

    manifest = {
        "game": "Project Justice (USA)",
        "platform": "dreamcast",
        "source": {
            "chd": str(chd) if chd else None,
            "sha256": chd_sha256,
        },
        "disc": {
            "ip": ip_fields(ip),
            "ip_bin_sha256": hashlib.sha256(ip).hexdigest(),
            "tracks": [
                {"start_lba": s, "sector_size": sz, "path": str(p)}
                for s, sz, p in g.tracks
            ],
        },
        "executable": {
            "name": "1ST_READ.BIN",
            "size": len(first_read),
            "sha256": hashlib.sha256(first_read).hexdigest(),
            "load_base": FIRST_READ_LOAD_BASE,
        },
        "launch": {
            "core": "flycast",
            "boot": "IP.BIN -> 1ST_READ.BIN",
            "prerequisites": [
                "Redump GDI from chdman extractcd (track 1 data + track 2 audio + track 3 high-density data)",
                "no BIOS needed beyond IP.BIN; SH-4 user program at 0x8C010000",
            ],
        },
        "files": {n: {"lba": l, "size": s} for n, (l, s) in files.items()},
        "archives": archives,
        "udcsdm": udcsdm_hdr,
        "characters": {
            "model_entries": len(archives["UPLMDL.AFS"]["entries"]),
            "texture_entries": len(archives["XPLTEX.AFS"]["entries"]),
            "textures_per_model": len(archives["XPLTEX.AFS"]["entries"]) // len(archives["UPLMDL.AFS"]["entries"]),
            "motion_entries": len(archives["WPLMOT.AFS"]["entries"]),
            "pack_entries": len(archives["YPLPACK.AFS"]["entries"]),
            "medal_model_entries": len(archives["UGMEDMDL.AFS"]["entries"]),
            "roster_names_in_exe": exe_names,
            "entry_name_directory": "none (positional AFS entries)",
        },
        "format_notes": [
            "AFS archives: 'AFS\\0', u32 count, (offset,size) u32 pairs, data from 0x80000",
            "UPLMDL entries: float-heavy payloads, no magic; format unidentified (analysis stage)",
            "WPLMOT entries: several start with u16 offset tables; format unidentified",
            "XPLTEX entries: ~70-105 KB each; format unidentified",
            "UDCSDM.AFS is not an AFS archive (see udcsdm header)",
        ],
    }
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Project Justice (USA) DC inventory")
    ap.add_argument("gdi", help="path to the unpacked disc.gdi")
    ap.add_argument("--chd", help="path to the owned source CHD (identity only)")
    ap.add_argument("--chd-sha256", default=SOURCE_CHD_SHA256)
    ap.add_argument("--out", help="write the manifest JSON here")
    args = ap.parse_args(argv)
    man = inventory(args.gdi, chd=args.chd, chd_sha256=args.chd_sha256)
    if args.out:
        Path(args.out).write_text(json.dumps(man, indent=2))
    else:
        print(json.dumps(man, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
