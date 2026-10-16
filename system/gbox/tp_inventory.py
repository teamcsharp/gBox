"""Twilight Princess (USA, GameCube) — source inventory.

Read-only. Identifies the owned disc (GZ2E01), hashes the source executable, and enumerates the
container layout: 3656 FST files, 1843 RARC archives (Yaz0-wrapped or raw), with a validated RARC
header + string-table scan for character archives. This is stage 1 (inventory) of the
character-replacement pipeline; the J3D model/texture/animation readers are stage 3 (reader).

Authoritative source identity (reuse across stages):
    game_id      GZ2E01
    main.dol     sha256 e7f197436815e66c4a11df3d7bd557d66083b641ff8a8e76439f3caba7ae60e8   (4,020,672 B)
    disc (ISO)   sha256 490ef919f413e00daedb4711777c3be05ef9afc12c7acca7675c721c9393c814   (1,459,978,240 B)
The GCZ (catalog source) and the sibling ISO carry the same game_id and byte-identical main.dol.
"""
from __future__ import annotations

import hashlib
import struct
from collections import Counter, defaultdict
from pathlib import Path

from .formats.lz import yaz0_decompress
from .gcdisc import GCDisc

GCZ = "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Legend of Zelda, The - Twilight Princess (USA).gcz"
ISO = "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Legend of Zelda, The - Twilight Princess (USA).iso"

GAME_ID = "GZ2E01"
MAIN_DOL_SHA256 = "e7f197436815e66c4a11df3d7bd557d66083b641ff8a8e76439f3caba7ae60e8"
DISC_SHA256 = "490ef919f413e00daedb4711777c3be05ef9afc12c7acca7675c721c9393c814"

_EXT_CAT = {
    ".arc": "archive", ".szs": "archive", ".szp": "archive",
    ".bmd": "model", ".bdl": "model",
    ".bti": "texture", ".btk": "texture", ".jpc": "texture",
    ".bck": "anim", ".bca": "anim", ".btp": "anim", ".bla": "anim", ".brk": "anim", ".bls": "anim",
    ".blo": "layout",
    ".rel": "code", ".dol": "code",
    ".thp": "video",
    ".aw": "audio", ".ast": "audio", ".bms": "audio", ".bmg": "audio",
}

# J3D asset kinds found inside RARC archives (Twilight Princess actors).
_J3D_EXT = {".bmd", ".bdl", ".bmt", ".bti", ".btk", ".bck", ".bca", ".btp", ".bla", ".bls", ".brk", ".blo"}


def _cat(path: str) -> str:
    ext = Path(path).suffix.lower()
    return _EXT_CAT.get(ext, f"other{ext}")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def disc_identity(disc_path: str) -> dict:
    d = GCDisc(disc_path)
    dol = d.dol()
    return {
        "game_id": d.game_id,
        "title": d.title,
        "file_count": len(d.files),
        "main_dol_size": len(dol),
        "main_dol_sha256": hashlib.sha256(dol).hexdigest(),
    }


def fst_layout(disc: GCDisc) -> dict:
    cats = Counter()
    exts = Counter()
    top = defaultdict(lambda: [0, 0])
    for path, (_off, size) in disc.files.items():
        cats[_cat(path)] += 1
        exts[Path(path).suffix.lower()] += 1
        parts = Path(path).parts
        t = parts[1] if len(parts) > 1 else "(root)"
        top[t][0] += 1
        top[t][1] += size
    return {
        "categories": dict(cats.most_common()),
        "extensions": dict(exts.most_common()),
        "top_dirs": {k: {"files": v[0], "bytes": v[1]} for k, v in sorted(top.items(), key=lambda kv: -kv[1][1])},
    }


def rarc_parse(raw: bytes) -> dict:
    """Parse a (Yaz0-decoded) RARC archive header and scan its string table for filenames.

    Header layout (the node/entry/string metadata header sits at `data_header`, its offsets are
    RELATIVE to `data_header`):
        0x00 "RARC"; 0x04 size; 0x08 data_header (0x20); 0x0C file-data offset; 0x10 file-data size.
        @data_header: node_count, node_off, entry_count, entry_off, str_size, str_off (relative).

    We validate the header counts/offsets and enumerate the string table (NUL-terminated names of
    directories and files). Full node/entry record decoding (data offsets + sizes) is reader-stage
    work and is deliberately not claimed here.
    """
    if raw[:4] != b"RARC":
        raise ValueError(f"not a RARC: {raw[:4]!r}")
    size = struct.unpack_from(">I", raw, 0x04)[0]
    dh = struct.unpack_from(">I", raw, 0x08)[0]
    data_off = struct.unpack_from(">I", raw, 0x0C)[0]
    data_size = struct.unpack_from(">I", raw, 0x10)[0]
    node_count = struct.unpack_from(">I", raw, dh)[0]
    node_off = dh + struct.unpack_from(">I", raw, dh + 4)[0]
    entry_count = struct.unpack_from(">I", raw, dh + 8)[0]
    entry_off = dh + struct.unpack_from(">I", raw, dh + 12)[0]
    str_size = struct.unpack_from(">I", raw, dh + 16)[0]
    str_off = dh + struct.unpack_from(">I", raw, dh + 20)[0]

    # sanity: header counts must not overflow the file
    valid = (dh + 0x20 <= len(raw) and str_off + str_size <= len(raw)
             and data_off + data_size <= size and node_count < 0x10000 and entry_count < 0x10000)

    # node inlined names (4 bytes each; directory names are short)
    dirs = []
    for i in range(min(node_count, 512)):
        o = node_off + 0x10 * i
        if o + 4 > len(raw):
            break
        nm4 = raw[o:o + 4].rstrip(b"\0")
        dirs.append(nm4.decode("latin-1", "replace") if all(32 <= c < 127 for c in nm4) else "")

    # string table -> NUL-terminated filenames
    strtab = raw[str_off:str_off + str_size]
    names = [s.decode("latin-1", "replace") for s in strtab.split(b"\0") if s]
    j3d = Counter(Path(n).suffix.lower() for n in names if Path(n).suffix.lower() in _J3D_EXT)

    return {
        "size": size, "data_off": data_off, "data_size": data_size,
        "node_count": node_count, "entry_count": entry_count, "str_size": str_size,
        "dirs": dirs, "name_count": len(names), "j3d_assets": dict(j3d),
        "sample_names": [n for n in names if Path(n).suffix.lower() in _J3D_EXT][:24],
        "valid": valid,
    }


def inventory(disc_path: str = GCZ) -> dict:
    """Full read-only inventory of the owned disc."""
    d = GCDisc(disc_path)
    ident = disc_identity(disc_path)
    layout = fst_layout(d)

    arcs = []
    for path, (_o, size) in d.files.items():
        if path.lower().endswith((".arc", ".szs", ".szp")):
            arcs.append((path, size))

    yaz0_wrapped = raw_rarc = 0
    for path, _s in arcs:
        h4 = d.read(path)[:4]
        if h4 == b"Yaz0":
            yaz0_wrapped += 1
        elif h4 == b"RARC":
            raw_rarc += 1

    # decompress + validate a sample of the largest archives (bounded)
    sample = sorted(arcs, key=lambda t: -t[1])[:6]
    parsed = {}
    for path, _s in sample:
        blob = d.read(path)
        if blob[:4] == b"Yaz0":
            blob = yaz0_decompress(blob)
        if blob[:4] == b"RARC":
            parsed[path] = rarc_parse(blob)

    return {
        "source": {"gcz": GCZ, "iso": ISO, **ident},
        "hashes": {"main_dol": MAIN_DOL_SHA256, "disc_iso": DISC_SHA256},
        "layout": layout,
        "archives": {"total": len(arcs), "yaz0_wrapped": yaz0_wrapped, "raw_rarc": raw_rarc},
        "sample_archives": parsed,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(inventory(), indent=2, default=str))
