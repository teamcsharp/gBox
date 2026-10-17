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
from .formats.rarc import parse as _rarc_parse, walk as _rarc_walk

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


def _identity(d):
    if d.game_id!=GAME_ID:
        raise ValueError(f"Expected {GAME_ID}, got {d.game_id}")
    dol=d.dol()
    return {'game_id':d.game_id,'title':d.title,'file_count':len(d.files),
            'main_dol_size':len(dol),'main_dol_sha256':hashlib.sha256(dol).hexdigest()}

def disc_identity(disc_path: str) -> dict:
    d=GCDisc(disc_path)
    try:
        return _identity(d)
    finally:
        d.f.close()


def fst_layout(disc: GCDisc) -> dict:
    cats = Counter()
    exts = Counter()
    top = defaultdict(lambda: [0, 0])
    for path, (_off, size) in disc.files.items():
        cats[_cat(path)] += 1
        exts[Path(path).suffix.lower()] += 1
        parts = Path(path).parts
        t = parts[0] if len(parts) > 1 else "(root)"
        top[t][0] += 1
        top[t][1] += size
    return {
        "categories": dict(cats.most_common()),
        "extensions": dict(exts.most_common()),
        "top_dirs": {k: {"files": v[0], "bytes": v[1]} for k, v in sorted(top.items(), key=lambda kv: -kv[1][1])},
    }


def rarc_parse(raw: bytes) -> dict:
    """Validate RARC table/member bounds and directory links; summarize named files."""
    table=_rarc_parse(raw)
    members=_rarc_walk(raw)
    names=[name for name,_,_ in members]
    kinds=Counter(Path(name).suffix.lower() for name in names if Path(name).suffix.lower() in _J3D_EXT)
    return {'size':table['size'],'data_off':table['data_off'],'data_size':table['data_size'],
            'node_count':len(table['nodes']),'entry_count':len(table['files']),
            'str_size':table['str_size'],'dirs':[n['name'] for n in table['nodes']],
            'name_count':len(names),'j3d_assets':dict(kinds),
            'sample_names':[n for n in names if Path(n).suffix.lower() in _J3D_EXT][:24],
            'valid':True}


def inventory(disc_path: str = GCZ) -> dict:
    """Full read-only inventory of the owned disc."""
    d = GCDisc(disc_path)
    try:
        ident = _identity(d)
        layout = fst_layout(d)

        arcs = []
        for path, (_o, size) in d.files.items():
            if path.lower().endswith((".arc", ".szs", ".szp")):
                arcs.append((path, size))

        yaz0_wrapped = raw_rarc = 0
        for path, _s in arcs:
            off,size=d.files[path]
            h4 = d._r(off,min(4,size))
            if len(h4)!=min(4,size):
                raise ValueError("Truncated archive prefix")
            if h4 == b"Yaz0":
                yaz0_wrapped += 1
            elif h4 == b"RARC":
                raw_rarc += 1

        # decompress + validate a sample of the largest archives (bounded)
        sample = sorted(arcs, key=lambda t: -t[1])[:6]
        parsed = {}
        for path, _s in sample:
            if _s>64*1024*1024:
                raise ValueError("Archive exceeds inventory size limit")
            blob = d.read(path)
            if blob[:4] == b"Yaz0":
                blob = yaz0_decompress(blob,max_output=64*1024*1024)
            if blob[:4] == b"RARC":
                parsed[path] = rarc_parse(blob)

        return {
            "source": {"path":str(disc_path),"sha256":sha256_file(disc_path), **ident},
            "hashes": {"main_dol": ident["main_dol_sha256"]},
            "reference_hashes": {"main_dol": MAIN_DOL_SHA256, "disc_iso": DISC_SHA256},
            "layout": layout,
            "archives": {"total": len(arcs), "yaz0_wrapped": yaz0_wrapped, "raw_rarc": raw_rarc},
            "sample_archives": parsed,
        }
    finally:
        d.f.close()


if __name__ == "__main__":
    import json
    print(json.dumps(inventory(), indent=2, default=str))
