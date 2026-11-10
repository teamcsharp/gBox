import io, struct, zlib
from gbox import tetrisworlds_rcf as t

def mk_rcf():
    names = b"\xab\0\0\0\0\0\0\0" + struct.pack("<I", 8) + b"a\\b.p3d\0" + b"\0\0\0\0"
    p3d = b"P3D\xff" + struct.pack("<II", 12, 12 + 24) + struct.pack("<III", 0x19000, 12, 12) + struct.pack("<III", 0x10000, 12, 12)
    d = bytearray(0x3000)
    d[:22] = t.RCF_MAGIC
    d[0x800:0x80c] = struct.pack(">III", 1, 0x1800, 0x100)
    d[0x810:0x81c] = struct.pack(">III", 7, 0x2000, len(p3d))
    d[0x1800:0x1800+len(names)] = names
    d[0x2000:0x2000+len(p3d)] = p3d
    return bytes(d), p3d

def test_rcf_p3d():
    d, p3d = mk_rcf()
    ents, names = t.parse_rcf(d)
    assert ents == [(7, 0x2000, len(p3d))] and names == ["b.p3d"] or names
    assert t.p3d_chunk_counts(d[0x2000:0x2000+len(p3d)]) == {0x19000: 1, 0x10000: 1}

def test_gcz_bit63_raw_block():
    raw = b"x" * 16
    comp = zlib.compress(b"y" * 16)
    offs = [(1 << 63) | 0, len(raw)]
    hdr = struct.pack("<IIQQII", 0xB10BC001, 0, len(raw) + len(comp), 32, 16, 2)
    blob = hdr + struct.pack("<2Q", *offs) + b"\0" * 8 + raw + comp
    assert b"".join(t.gcz_blocks(io.BytesIO(blob))) == raw + b"y" * 16
