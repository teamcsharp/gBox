"""RE6-style `ARC` containers: the header, the entry table and a structural comparison against the game's own arc.

Measured on the i9 against the RE6 base RomFS (`nativeNXx64/arc/NX/uPl00HeadLeonUsa.arc` and the 45 roster-donor
artifacts): the container starts with `ARC\\0`, a u16 version (7), a u16 at +0x06, then the arc's own path in a fixed
0x40-byte field (0x08..0x48); the entry table starts at 0x48, each entry is 0x10 bytes of words plus a 0x40-byte path,
0x50 bytes in all. The donor artifacts keep the same entry paths as the game's arc but their resources are re-encoded
much smaller (ratios 0.07-0.48), which is what makes them worth comparing before an overlay is built.
"""
import struct

MAGIC = b"ARC\x00"
PATH_AT = 0x08
PATH_SIZE = 0x40
TABLE_AT = 0x48
ENTRY_SIZE = 0x50


def parse(blob: bytes) -> dict:
    """The container's version, its own path and its entries [{words, path}]."""
    if len(blob) < TABLE_AT or blob[:4] != MAGIC:
        raise ValueError("not an ARC container")
    version = struct.unpack_from("<H", blob, 4)[0]
    path = blob[PATH_AT:PATH_AT + PATH_SIZE].split(b"\x00")[0].decode("utf-8", "replace")
    entries = []
    at = TABLE_AT
    while at + ENTRY_SIZE <= len(blob):
        words = struct.unpack_from("<4I", blob, at)
        entry_path = blob[at + 0x10:at + ENTRY_SIZE].split(b"\x00")[0].decode("utf-8", "replace")
        if not entry_path:
            break
        entries.append({"words": words, "path": entry_path})
        at += ENTRY_SIZE
    return {"version": version, "path": path, "entries": entries}


def compare(game: bytes, donor: bytes) -> dict:
    """Whether the donor keeps the game's entry paths and how its entry sizes compare (word 2 is the size field)."""
    g, d = parse(game), parse(donor)
    gp = [e["path"] for e in g["entries"]]
    dp = [e["path"] for e in d["entries"]]
    ratios = []
    for ge, de in zip(g["entries"], d["entries"]):
        gsz, dsz = ge["words"][3], de["words"][3]
        if gsz:
            ratios.append({"path": ge["path"], "game": gsz, "donor": dsz, "ratio": round(dsz / gsz, 3)})
    return {"same_paths": gp == dp, "game_entries": len(gp), "donor_entries": len(dp),
            "sizes": ratios, "worst_ratio": min((r["ratio"] for r in ratios), default=1.0)}
