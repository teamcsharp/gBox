"""RE Outbreak File #2 (PS2, SLUS_209.84) BIN/0x.DAT container probes.

Verified against the owned disc: BIN/0-3.DAT are 'MWo3' overlay headers carrying MIPS-LE
code (submain/demo/game/netwk .bin); BIN/01-05.DAT are AFS archives ('AFS\\0').
An AFS header is magic, u32 count, count * (u32 offset, u32 size), little-endian.
"""
import struct

MWO3 = b"MWo3"
AFS = b"AFS\x00"


def parse_afs(head: bytes, total: int | None = None) -> list[tuple[int, int]]:
    if head[:4] != AFS:
        raise ValueError("not an AFS archive")
    count = struct.unpack_from("<I", head, 4)[0]
    if not 0 < count <= 65536 or len(head) < 8 + 8 * count:
        raise ValueError(f"bad AFS count/short header: {count}")
    ents = [struct.unpack_from("<II", head, 8 + 8 * i) for i in range(count)]
    prev = 8 + 8 * count
    for off, size in ents:
        if off < prev or (total is not None and off + size > total):
            raise ValueError("AFS entry out of order or beyond archive")
        prev = off + size
    return ents


def parse_mwo3(head: bytes) -> dict:
    if head[:4] != MWO3:
        raise ValueError("not an MWo3 overlay")
    idx, a, b, c, d, e, f = struct.unpack_from("<7I", head, 4)
    name = head[0x20:0x40].split(b"\0")[0].decode("ascii", "replace")
    return {"index": idx, "fields": [a, b, c, d, e, f], "name": name}
