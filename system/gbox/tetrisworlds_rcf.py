"""Tetris Worlds (GameCube, GTRE78) container readers.

Verified against the owned build (ISO sha256 8c3625ab...5c5a5c): the game is
Radical Entertainment's RCF ("RADCORE CEMENT LIBRARY") + Pure3D (.p3d), not AKI.
Byte order: RCF index big-endian, P3D chunks little-endian.
RCF layout (observed): 0x00 magic[32]; 0x20 version; toc at 0x800:
  u32 count, u32 name_off, u32 name_size, u32 ?; entries at 0x810 of
  (u32 name_hash, u32 offset, u32 size) big-endian, sorted by hash.
Name->entry pairing is NOT yet verified (hash algorithm unidentified).
"""
import gzip, re, struct, zlib

RCF_MAGIC = b"RADCORE CEMENT LIBRARY"
P3D_MAGIC = b"P3D\xff"


def gcz_blocks(f):
    """Yield decompressed blocks of a GCZ file (bit63 of offset = stored raw)."""
    m, _st, comp, _data, _bs, n = struct.unpack("<IIQQII", f.read(32))
    if m != 0xB10BC001:
        raise ValueError("not a GCZ")
    offs = struct.unpack("<%dQ" % n, f.read(8 * n)); f.read(4 * n)
    base = f.tell(); mask = (1 << 63) - 1
    for i in range(n):
        o = offs[i]; raw = bool(o >> 63); o &= mask
        e = (offs[i + 1] & mask) if i + 1 < n else comp
        f.seek(base + o); b = f.read(e - o)
        yield b if raw else zlib.decompress(b)


def parse_fst(iso):
    """Return [(path, offset, size)] from a GameCube disc image (bytes-like with seek/read)."""
    iso.seek(0x424); fstoff, fstsz = struct.unpack(">II", iso.read(8))
    iso.seek(fstoff); fst = iso.read(fstsz)
    n = struct.unpack(">I", fst[8:12])[0]; names = fst[n * 12:]
    def nm(o): return names[o:names.index(b"\0", o)].decode("latin1")
    out = []; path = [("", n)]
    for i in range(1, n):
        no = int.from_bytes(fst[i*12+1:i*12+4], "big")
        a, b = struct.unpack(">II", fst[i*12+4:i*12+12])
        while len(path) > 1 and i >= path[-1][1]: path.pop()
        p = "/".join([x[0] for x in path[1:]] + [nm(no)])
        if fst[i*12]: path.append((nm(no), b))
        else: out.append((p, a, b))
    return out


def parse_rcf(data):
    """Return (entries[(hash, off, size)], names[str]) of an RCF blob."""
    if not data.startswith(RCF_MAGIC): raise ValueError("not RCF")
    n, name_off, name_sz = struct.unpack(">III", data[0x800:0x80c])
    ents = [struct.unpack(">III", data[0x810+12*i:0x81c+12*i]) for i in range(n)]
    for _h, o, s in ents:
        if o + s > len(data): raise ValueError("entry out of range")
    names = [x.decode("latin1") for x in re.findall(rb"[\x21-\x7e]+\.[a-z0-9]{2,4}", data[name_off:name_off+name_sz])]
    return ents, names


def p3d_chunk_counts(blob):
    """Count Pure3D chunk ids (depth<=1) in one .p3d blob."""
    if not blob.startswith(P3D_MAGIC): raise ValueError("not P3D")
    acc = {}
    def walk(o, e, d):
        while o + 12 <= e:
            cid, hs, sz = struct.unpack("<III", blob[o:o+12])
            if sz < 12 or o + sz > e: break
            acc[cid] = acc.get(cid, 0) + 1
            if d < 1: walk(o + hs, o + sz, d + 1)
            o += sz
    walk(12, len(blob), 0)
    return acc
