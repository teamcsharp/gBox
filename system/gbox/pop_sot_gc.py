"""Prince of Persia: The Sands of Time (GameCube, GPTE41) native probe.

Inventory-level only: the character/asset container is prince.bf (Ubisoft "BIG\\0" bigfile, 240 MB),
not the TPL files (those are just banner/icon). Header fields are little-endian. Entry-table layout
is NOT yet decoded -- this module claims only the header.
"""
import hashlib
import struct

GAME_ID = "GPTE41"
BIGFILE = "prince.bf"
BIG_MAGIC = b"BIG\x00"


def parse_big_header(buf: bytes) -> dict:
    if len(buf) < 16 or buf[:4] != BIG_MAGIC:
        raise ValueError("not a BIG bigfile")
    version, count_a, count_b = struct.unpack_from("<III", buf, 4)
    return {"magic": "BIG", "version": version, "field_8": count_a, "field_12": count_b}


def sha256_stream(chunks) -> str:
    h = hashlib.sha256()
    for c in chunks:
        h.update(c)
    return h.hexdigest()


def inventory(disc) -> dict:
    """disc: gbox.gcdisc.GCDisc. Returns manifest of counted files plus the bigfile header."""
    off, size = disc.files[BIGFILE]
    return {
        "game_id": disc.game_id,
        "file_count": len(disc.files),
        "files": {k: {"offset": v[0], "size": v[1]} for k, v in sorted(disc.files.items())},
        "bigfile": {"path": BIGFILE, "offset": off, "size": size,
                    **parse_big_header(disc._r(off, 16))},
        "dol_sha256": hashlib.sha256(disc.dol()).hexdigest(),
    }
