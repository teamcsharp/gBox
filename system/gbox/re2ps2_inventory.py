"""Resident Evil Outbreak (PS2, USA) archive inventory.

The disc keeps its data in three CRI-AFS containers (NETBIO00/01/02.DAT) whose entries are themselves
AFS archives (romdata_usa.afs, rNNN.afs, adxsnd.afs, movieNNN.afs ...). Each AFS ends with a name
directory (48-byte records: 32-byte name + ... ) pointed to by the (offset, size) pair that follows the
entry table. This module reads those headers in place (no extraction) and censuses the contents.

Verified on the USA disc: NETBIO00 = 13 entries (romdata_usa.afs 1342 entries, r001/r002/r028/r035/r041/
rfff.afs + *_h.bin); romdata_usa.afs holds 510 TEX-prefixed .nbd entries, 168 pl00..pl07_pc_NNN.bin,
8 plNN_tbl.bin, 16 wpNN.wmd, 12 .tm2, 28 .snp.
"""
from __future__ import annotations

import re
import struct
from collections import Counter

AFS_MAGIC = b"AFS\x00"
NAME_REC = 48
CONTAINERS = ("NETBIO00.DAT", "NETBIO01.DAT", "NETBIO02.DAT")
ROMDATA = "romdata_usa.afs"


class AfsError(ValueError):
    pass


def _read(f, off: int, n: int) -> bytes:
    f.seek(off)
    return f.read(n)


def read_afs(f, base: int = 0) -> list[dict]:
    """Entries of the AFS at absolute byte ``base``: index, name (None if no directory), offset
    (relative to ``base``), size, magic (first four bytes)."""
    head = _read(f, base, 8)
    if head[:4] != AFS_MAGIC:
        raise AfsError(f"not an AFS at {base}: {head[:4]!r}")
    n = struct.unpack_from("<I", head, 4)[0]
    tbl = _read(f, base + 8, 8 * n + 8)
    if len(tbl) < 8 * n + 8:
        raise AfsError("truncated entry table")
    ents = [struct.unpack_from("<II", tbl, 8 * i) for i in range(n)]
    doff, dsz = struct.unpack_from("<II", tbl, 8 * n)
    names: list[str | None] = [None] * n
    if doff and dsz >= NAME_REC * n and dsz < (1 << 24):
        nd = _read(f, base + doff, dsz)
        if len(nd) >= NAME_REC * n:
            names = [nd[NAME_REC * i:NAME_REC * i + 32].split(b"\0", 1)[0].decode("latin-1") for i in range(n)]
    return [{"index": i, "name": names[i], "offset": o, "size": s,
             "magic": _read(f, base + o, 4) if s >= 4 else b""} for i, (o, s) in enumerate(ents)]


def player_slug(name: str) -> str | None:
    m = re.match(r"pl(\d\d)_", name, re.I)
    return f"re2ps2_pl{m.group(1)}" if m else None


def classify(name: str | None) -> str:
    """Coarse role of a romdata entry from its name."""
    if not name:
        return "unnamed"
    low = name.lower()
    ext = low.rsplit(".", 1)[-1] if "." in low else ""
    if re.match(r"pl\d\d_tbl\.bin$", low):
        return "player_table"
    if re.match(r"pl\d\d_pc_\d+\.bin$", low):
        return "player_chunk"
    if ext == "nbd":
        return "texture_bank"       # TEX\0-prefixed
    if ext in ("tm2", "tex", "img"):
        return "texture"
    if ext in ("snp", "wmd", "sdt", "mat", "amo", "dat"):
        return ext
    return "other_" + ext if ext else "other"


def census(entries: list[dict]) -> dict:
    kinds = Counter(classify(e["name"]) for e in entries)
    magics = Counter(e["magic"].hex() for e in entries if e["magic"])
    return {"entries": len(entries), "kinds": dict(kinds), "magics": dict(magics.most_common(12)),
            "bytes": sum(e["size"] for e in entries)}


def players(entries: list[dict]) -> dict[str, dict]:
    """Per-player table + chunk list, keyed by ``re2ps2_plNN``."""
    out: dict[str, dict] = {}
    for e in entries:
        k = classify(e["name"])
        if k not in ("player_table", "player_chunk"):
            continue
        d = out.setdefault(player_slug(e["name"]), {"table": None, "chunks": 0, "chunk_bytes": 0})
        if k == "player_table":
            d["table"] = {"name": e["name"], "offset": e["offset"], "size": e["size"]}
        else:
            d["chunks"] += 1
            d["chunk_bytes"] += e["size"]
    return dict(sorted(out.items()))


def inventory(iso_path: str) -> dict:
    """Full disc inventory: nested AFS census per container plus romdata player/texture breakdown."""
    from gbox.romexport import iso_files
    res: dict = {"iso": iso_path, "containers": {}}
    with open(iso_path, "rb") as f:
        files = iso_files(f)
        for cname in CONTAINERS:
            if cname not in files:
                continue
            base = files[cname][1] * 2048
            outer = read_afs(f, base)
            sub = {}
            for e in outer:
                if e["magic"] == AFS_MAGIC:
                    inner = read_afs(f, base + e["offset"])
                    sub[e["name"]] = {"size": e["size"], **census(inner)}
                    if e["name"] == ROMDATA:
                        res["players"] = players(inner)
                else:
                    sub[e["name"]] = {"size": e["size"], "raw": True}
            res["containers"][cname] = {"entries": len(outer), "archives": sub}
    return res
