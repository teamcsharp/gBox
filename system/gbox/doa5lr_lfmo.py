"""DOA5 Last Round (PS3) LFMO ``NAME.bin`` + ``NAME.lnk`` container reader.

Layout (all big-endian), decoded from owned build BLJM61258 v04.65 and
cross-checked on message.* and chara_rtm.* (counts match, every extent lies
inside the .lnk, offsets 0x800-aligned, no nonzero reserved qwords):

NAME.bin  header 0x20: 'LFMO', u32 version(1), u32 count, u32 0x20, u32 index_off(0x28),
          u32 order_name_off, u32 first_name_off, u32 0.  Index = count x 12 bytes
          (u32 0, u32 index, u32 name_off) at index_off; names are NUL-terminated
          obfuscated strings (undecoded). The first plain name is NAME.order.
NAME.lnk  header 0x20: 4-char type tag, u32 0, u32 0, u32 count, u64 total_size,
          u64 align(0x800); then count x 32-byte entries (u64 offset, u64 size,
          u64 size_dup, u64 0) and data at the 0x800-aligned offsets.
"""
import struct

LFMO_MAGIC = b"LFMO"


class LfmoError(ValueError):
    pass


def parse_bin(data):
    if len(data) < 0x28 or data[:4] != LFMO_MAGIC:
        raise LfmoError("not an LFMO index")
    ver, count, hdr, idx_off, order_off, first_off = struct.unpack(">6I", data[4:28])
    if ver != 1 or hdr != 0x20:
        raise LfmoError("unsupported LFMO header")
    if idx_off + 12 * count > len(data) or count > 1 << 20:
        raise LfmoError("index exceeds file")
    recs = []
    for i in range(count):
        z, idx, noff = struct.unpack_from(">III", data, idx_off + 12 * i)
        if z or idx != i or not (0 < noff < len(data)):
            raise LfmoError("bad index record %d" % i)
        end = data.find(b"\0", noff)
        if end < 0:
            raise LfmoError("unterminated name %d" % i)
        recs.append({"index": i, "name_off": noff, "name": data[noff:end].decode("latin1")})
    oend = data.find(b"\0", order_off)
    if oend < 0:
        raise LfmoError("unterminated order name")
    return {"version": ver, "count": count, "index_off": idx_off,
            "order_name": data[order_off:oend].decode("latin1"), "entries": recs}


def parse_lnk(f, count, file_size):
    """Read the entry table from file object ``f`` (positioned anywhere)."""
    f.seek(0)
    h = f.read(0x20)
    if len(h) < 0x20:
        raise LfmoError("short lnk header")
    tag = h[:4]
    z1, z2, n = struct.unpack(">3I", h[4:16])
    total, align = struct.unpack(">QQ", h[16:32])
    if n != count or z1 or z2 or align != 0x800 or total != file_size:
        raise LfmoError("lnk header does not match index/file")
    t = f.read(32 * n)
    if len(t) != 32 * n:
        raise LfmoError("short lnk table")
    ents = []
    for i in range(n):
        off, size, size2, rsv = struct.unpack_from(">4Q", t, 32 * i)
        if rsv or size != size2 or off % align or off + size > file_size:
            raise LfmoError("bad lnk entry %d" % i)
        ents.append({"index": i, "offset": off, "size": size})
    return {"tag": tag.decode("latin1"), "count": n, "entries": ents}


def read_member(f, entry):
    f.seek(entry["offset"])
    return f.read(entry["size"])


def open_pair(bin_path, lnk_path):
    import os
    with open(bin_path, "rb") as b:
        idx = parse_bin(b.read())
    size = os.path.getsize(lnk_path)
    with open(lnk_path, "rb") as l:
        lnk = parse_lnk(l, idx["count"], size)
    for e, m in zip(idx["entries"], lnk["entries"]):
        e.update(offset=m["offset"], size=m["size"])
    return {"tag": lnk["tag"], "count": idx["count"], "order_name": idx["order_name"],
            "entries": idx["entries"]}
