"""Inventory for Dead or Alive (USA) PSX (Tecmo, 1998, SLUS-00606).

The owned source is a HyperSpin CHD (v5) whose data track holds a plain ISO9660
disc. Boot chain (SYSTEM.CNF): SLUS_006.06 (544 KB boot EXE) -> PS_DOA.BIN
(46.4 MB, the entire game: code, textures, models, motions, VAG ADPCM samples)
plus MOVIE.EXE (STR movie player), OPENING.STR / ENDING.STR and 30 CD-DA audio
tracks.

PS_DOA.BIN layout (best-effort, confirmed at inventory time):
  0x000000  338-entry load table of (u32 size, u32 ref) pairs. Entries 1..8
            refs are RAM load addresses (0x80000000 | ref) and tile the loaded
            image without overlap; entries 9..85 use 0x100-aligned RAM refs
            with code at the matching file offsets. Entries 86..337 carry a
            packed (u8 index, u8 count) ref whose semantics (per-character
            motion/asset index) are decoded in the analysis stage.
  0x0017d0  12-slot character name table (12-byte slots), slot 8 empty:
            AYANE, LEI-FANG, RAIDOU, BASS, BAYMAN, GEN-FU, KASUMI, HAYABUSA,
            (empty), JANN-LEE, TINA, ZACK.
  0x00192a  TIM texture (UI), another at 0x1940; further TIMs at 0x802bf+.
  0x0070804 OMAKE gallery table: per-entry (title, "OMAKE", BMP filename)
            mapping to the OMAKE/*.BMP bonus pictures.
  0x027300+ MIPS code region (matches RAM refs of table entries 1..8).
  ~0x23CEA1B / 0x2684A1B: embedded VAG ADPCM banks.

No 'TMD', 'HELENA' or BIP markers exist; character geometry/texture data is
packed in the opaque high-entropy regions between the code area and the VAG
banks (compression analysis is the next stage's job).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from . import psxdisc

EXE_FILES = ("SLUS_006.06", "PS_DOA.BIN", "MOVIE.EXE")
ROSTER_SLOTS = 12
ROSTER_OFFSET = 0x17D0
GALLERY_OFFSET = 0x70804


def exe_header(b: bytes) -> dict:
    """Parse a PS-X EXE. This build's Sony variant puts pc0/gp/t_addr/t_size at
    0x10/0x14/0x18/0x1c (standard layout would start t_size at 0x10)."""
    if len(b) < 0x28 or b[:8] != b"PS-X EXE":
        return {"magic": None, "size": len(b)}
    pc0, gp, t_addr, t_size = struct.unpack_from("<4I", b, 0x10)
    return {
        "magic": "PS-X EXE",
        "size": len(b),
        "pc0": pc0,
        "gp": gp,
        "t_addr": t_addr,
        "t_size": t_size,
        "loaded_span": (t_addr, t_addr + t_size),
    }


def block_table(b: bytes, max_entries: int = 338) -> list[tuple[int, int]]:
    """(u32 size, u32 ref) pairs until a zero pair. Entry count is bounded by
    the table area that precedes the name table at 0x17d0."""
    out: list[tuple[int, int]] = []
    for i in range(max_entries):
        size, ref = struct.unpack_from("<II", b, 8 * i)
        if size == 0 and ref == 0:
            break
        out.append((size, ref))
    return out


def _cstr(b: bytes, off: int) -> str:
    end = b.find(b"\x00", off)
    if end < 0 or end - off > 15:
        raise ValueError("no C string")
    return b[off:end].decode("latin-1")


def roster_names(b: bytes) -> list[str | None]:
    """Character name table: align4-walked NUL-terminated names, at most 12
    slots, starting at ROSTER_OFFSET."""
    out: list[str | None] = []
    off = ROSTER_OFFSET
    for _ in range(ROSTER_SLOTS):
        if b[off] == 0:
            out.append(None)
            off = (off + 4 + 3) & ~3
            continue
        name = _cstr(b, off)
        out.append(name)
        off = (off + len(name) + 1 + 3) & ~3
    return out


def _quoted(b: bytes, off: int) -> tuple[str, int]:
    """Read a \\-quoted field: b'\\' + text + b'\\'; returns (text, end_of_closing_bs)."""
    if b[off] != 0x5C:
        raise ValueError("not a quoted field")
    end = b.find(b"\x5C", off + 1)
    if end < 0 or end - off > 17:
        raise ValueError("no closing quote")
    return b[off + 1:end].decode("latin-1"), end


def gallery(b: bytes) -> list[tuple[str, str]]:
    """OMAKE gallery records: (title, BMP filename). Record layout:
    title (NUL-term), then a \\-quoted b"OMAKE" label at align4(title_end),
    then a NUL-terminated filename, next record at align4(filename_end)."""
    out: list[tuple[str, str]] = []
    off = GALLERY_OFFSET
    while off + 8 <= len(b):
        if b[off] == 0:
            break
        try:
            title = _cstr(b, off)
            lab = (off + len(title) + 1 + 3) & ~3
            label, _ = _quoted(b, lab)
            if label != "OMAKE":
                break
            name = _cstr(b, lab + 7)
        except ValueError:
            break
        out.append((title, name))
        off = (lab + 7 + len(name) + 1 + 3) & ~3
    return out


def _magic_hits(b: bytes, magic: bytes, cap: int = 16) -> list[int]:
    hits: list[int] = []
    start = 0
    while len(hits) < cap:
        i = b.find(magic, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    return hits


def _classify(b: bytes, page: int = 0x1000) -> dict[str, int]:
    from collections import Counter
    counts = Counter()
    for off in range(0, len(b), page):
        seg = b[off:off + page]
        if seg.count(0) > int(page * 0.9):
            counts["zero"] += 1
            continue
        asc = sum(1 for x in seg if 32 <= x < 127)
        counts["entropy" if asc > int(page * 0.12) and seg.count(0) < int(page * 0.12) else "data"] += 1
    return dict(counts)


def inventory(bin_path: str | Path, chd_path: str | None = None,
              chd_sha256: str | None = None) -> dict:
    d = psxdisc.RawBin(str(bin_path), writable=False)
    files = []
    for name, (lba, size) in sorted(d.files.items()):
        data = None
        if name in EXE_FILES or name == "SYSTEM.CNF":
            data = d.read(name)
        files.append({
            "name": name,
            "lba": lba,
            "size": size,
            "sha256": hashlib.sha256(data).hexdigest() if data is not None else None,
            **({"exe": exe_header(data)} if data is not None and name in EXE_FILES else {}),
        })
    doa = d.read("PS_DOA.BIN")
    tbl = block_table(doa)
    ram_entries = [i for i, (s, r) in enumerate(tbl) if r and (r & 0xFF) == 0]
    asset_entries = [i for i, (s, r) in enumerate(tbl) if r and (r & 0xFF)]
    manifest = {
        "title": "Dead or Alive (USA)",
        "platform": "psx",
        "library": "hyperspin",
        "boot": "SLUS_006.06",
        "chd_sha256": chd_sha256,
        "bin_sha256": hashlib.sha256(Path(bin_path).read_bytes()).hexdigest(),
        "files": files,
        "ps_doa_bin": {
            "size": len(doa),
            "sha256": hashlib.sha256(doa).hexdigest(),
            "block_table_entries": len(tbl),
            "ram_load_entries": ram_entries,
            "asset_index_entries": asset_entries,
            "roster": roster_names(doa),
            "omake_gallery": gallery(doa),
            "tim_offsets": _magic_hits(doa, b"TIM"),
            "vag_offsets": _magic_hits(doa, b"VAG", cap=8),
            "anm_offsets": _magic_hits(doa, b"ANM", cap=8),
            "regions": _classify(doa),
        },
    }
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("bin", help="raw MODE2/2352 disc image or track-1 .bin")
    ap.add_argument("--chd", help="optional owned CHD path (for source identity)")
    ap.add_argument("--chd-sha256", help="precomputed owned CHD sha256")
    ap.add_argument("--out", default="doa_psx_manifest.json")
    args = ap.parse_args(argv)
    chd_sha = args.chd_sha256
    if args.chd and not chd_sha:
        chd_sha = hashlib.sha256(Path(args.chd).read_bytes()).hexdigest()
    m = inventory(args.bin, args.chd, chd_sha)
    Path(args.out).write_text(json.dumps(m, indent=2))
    print(f"manifest -> {args.out} (roster: {m['ps_doa_bin']['roster']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
