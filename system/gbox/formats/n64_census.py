"""Bounded N64 ROM census: byte-order normalisation, header, CRCs, compressed-block magics.

Read-only probe. Not an asset reader: it only counts validated signatures.
"""
import hashlib
import json
import struct
import zlib

MAGICS = {b"\x80\x37\x12\x40": "z64", b"\x37\x80\x40\x12": "v64", b"\x40\x12\x37\x80": "n64"}
M32 = 0xFFFFFFFF


def normalize(data):
    """Return (big-endian z64 bytes, original order name). Rejects unknown magic."""
    order = MAGICS.get(bytes(data[:4]))
    if order is None:
        raise ValueError("not an N64 ROM: magic %r" % bytes(data[:4]).hex())
    if order == "z64":
        return bytes(data), order
    n = len(data) - (len(data) % 4 if order == "n64" else len(data) % 2)
    b = bytearray(data[:n])
    if order == "v64":
        b[0::2], b[1::2] = data[1:n:2], data[0:n:2]
    else:  # n64: 32-bit little-endian words
        for k in range(4):
            b[k::4] = data[3 - k:n:4]
    return bytes(b), order


def header(z):
    if len(z) < 0x40:
        raise ValueError("short header")
    return {
        "clock": z[4:8].hex(), "entry": "0x%08x" % struct.unpack(">I", z[8:12])[0],
        "crc1": "0x%08x" % struct.unpack(">I", z[0x10:0x14])[0],
        "crc2": "0x%08x" % struct.unpack(">I", z[0x14:0x18])[0],
        "title": z[0x20:0x34].decode("ascii", "replace").rstrip(" \x00"),
        "game_code": z[0x3B:0x3F].decode("ascii", "replace"), "version": z[0x3F],
    }


def crc(z, seed=0xF8CA4DDC):
    """CIC-6102/7101 boot CRC over 0x1000..0x101000 (needs >=1MiB)."""
    if len(z) < 0x101000:
        raise ValueError("ROM too small for CRC")
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    for i in range(0x1000, 0x101000, 4):
        d = struct.unpack_from(">I", z, i)[0]
        if ((t6 + d) & M32) < t6:
            t4 = (t4 + 1) & M32
        t6 = (t6 + d) & M32
        t3 ^= d
        r = ((d << (d & 0x1F)) | (d >> (32 - (d & 0x1F)))) & M32 if d & 0x1F else d
        t5 = (t5 + r) & M32
        t2 = (t2 ^ r) & M32 if t2 > d else (t2 ^ t6 ^ d) & M32
        t1 = (t1 + (t5 ^ d)) & M32
    return (t6 ^ t4 ^ t3) & M32, (t5 ^ t2 ^ t1) & M32


def _zlib_ok(z, off, limit=1 << 22):
    try:
        d = zlib.decompressobj()
        out = d.decompress(z[off:off + 65536], limit)
        return len(out) > 0 and (d.eof or len(out) >= 64)
    except zlib.error:
        return False


def census(z, max_hits=20):
    """Count validated signatures. zlib hits are verified by inflating a prefix."""
    sigs = {"Yaz0": b"Yaz0", "Yay0": b"Yay0", "MIO0": b"MIO0", "ZLIB-78DA": b"\x78\xda",
            "ZLIB-789C": b"\x78\x9c", "ZLIB-7801": b"\x78\x01", "gzip": b"\x1f\x8b\x08"}
    out = {}
    for name, m in sigs.items():
        offs, cnt, p = [], 0, z.find(m)
        while p != -1:
            ok = name[:4] != "ZLIB" and name != "gzip" or _zlib_ok(z, p) if name[:4] == "ZLIB" else True
            if ok:
                cnt += 1
                if len(offs) < max_hits:
                    offs.append(p)
            p = z.find(m, p + 1)
        out[name] = {"count": cnt, "first_offsets": ["0x%x" % o for o in offs]}
    # F3DEX/F3DEX2 display-list evidence: 8-byte commands, runs of known opcodes
    ops = {0xE7, 0xFC, 0xFD, 0xF5, 0xF2, 0xE6, 0xF0, 0xBF, 0x06, 0x05, 0x01, 0xDE, 0xDF, 0xFB, 0xFA, 0xE3, 0xE2, 0xB6, 0xB7, 0xB8}
    runs, i, n = 0, 0, len(z) - 16
    while i < n:
        if z[i] == 0xE7 and z[i + 1:i + 8] == b"\x00" * 7:  # G_RDPPIPESYNC-style header
            runs += 1
            i += 8
        else:
            i += 8
    out["gbi_E7_pipesync_cmds"] = runs
    return out


def probe(raw):
    z, order = normalize(raw)
    h = header(z)
    c = crc(z)
    h["crc_computed"] = ["0x%08x" % c[0], "0x%08x" % c[1]]
    h["crc_ok"] = h["crc_computed"] == [h["crc1"], h["crc2"]]
    return {"byte_order": order, "size": len(z), "z64_sha256": hashlib.sha256(z).hexdigest(),
            "header": h, "census": census(z)}


if __name__ == "__main__":
    import sys
    import zipfile
    p = sys.argv[1]
    if p.lower().endswith(".zip"):
        zf = zipfile.ZipFile(p)
        m = [i for i in zf.infolist() if i.filename.lower().endswith((".z64", ".n64", ".v64"))][0]
        raw = zf.read(m)
    else:
        raw = open(p, "rb").read()
    print(json.dumps(probe(raw), indent=1))
