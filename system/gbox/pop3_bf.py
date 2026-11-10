"""Prince of Persia: The Two Thrones (GameCube, GKME41) pop3.bf index reader.

Layout verified on the owned GCZ build (little-endian, offsets relative to the
start of pop3.bf, 0x800-aligned):
  0x00 'BIG\\0', u32 version (0x26), u32 entry_count (6672), u32 aux (5)
  0x40 entry_count x (u32 key, u32 data_offset); offsets strictly ascending.
Entry size = next offset - offset (last entry runs to file end); the real
payload length lives inside each entry header (hypothesis: word0 flags,
word1/2 sizes).  Entry contents are NOT yet decoded.
"""
import struct

MAGIC = b"BIG\x00"
TABLE_OFF = 0x40
ALIGN = 0x800


class BFError(Exception):
    pass


def parse_index(head: bytes, file_size: int):
    if len(head) < TABLE_OFF or head[:4] != MAGIC:
        raise BFError("bad BIG magic")
    version, count, aux = struct.unpack_from("<III", head, 4)
    if version != 0x26:
        raise BFError(f"unsupported version {version:#x}")
    if count == 0 or TABLE_OFF + 8 * count > len(head):
        raise BFError("entry table outside supplied header bytes")
    ents, prev = [], -1
    for i in range(count):
        key, off = struct.unpack_from("<II", head, TABLE_OFF + 8 * i)
        if off % ALIGN or off <= prev or off >= file_size:
            raise BFError(f"entry {i}: bad offset {off:#x}")
        ents.append((key, off))
        prev = off
    out = []
    for i, (key, off) in enumerate(ents):
        end = ents[i + 1][1] if i + 1 < count else file_size
        out.append({"index": i, "key": key, "offset": off, "span": end - off})
    return {"version": version, "count": count, "aux": aux, "entries": out}
