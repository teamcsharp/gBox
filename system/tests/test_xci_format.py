import struct

from gbox.formats import xci


def _lz4_literals(data: bytes) -> bytes:
    assert len(data) < 15
    return bytes([len(data) << 4]) + data


def test_lz4_literal_and_match():
    assert xci.lz4_block(_lz4_literals(b"abc"), 3) == b"abc"
    # literal 'ab' then match offset 2 length 4 -> 'ababab'
    src = bytes([0x20 | 0]) + b"ab" + bytes([2, 0])
    assert xci.lz4_block(src, 6) == b"ababab"


def test_parse_pfs0_roundtrip():
    names = b"main\0sdk\0"
    body = b"AAAA" + b"BB"
    hdr = struct.pack("<4sIII", b"PFS0", 2, len(names), 0)
    ents = struct.pack("<QQII", 0, 4, 0, 0) + struct.pack("<QQII", 4, 2, 5, 0)
    out = xci.parse_pfs0(hdr + ents + names + body)
    assert out == {"main": b"AAAA", "sdk": b"BB"}


def test_classify_standard_xci(tmp_path):
    def hfs(entries):
        names = b"".join(n.encode() + b"\0" for n, _ in entries)
        data = b"".join(d for _, d in entries)
        ents, off, noff = b"", 0, 0
        for n, d in entries:
            ents += struct.pack("<QQII", off, len(d), noff, 0) + b"\0" * 40
            off += len(d); noff += len(n) + 1
        return struct.pack("<4sIII", b"HFS0", len(entries), len(names), 0) + ents + names + data
    secure = hfs([("a.nca", b"x" * 8)])
    root = hfs([("secure", secure)])
    img = bytearray(0xF000)
    img[0x100:0x104] = b"HEAD"
    img[0x130:0x138] = struct.pack("<Q", 0xF000)
    p = tmp_path / "t.xci"
    p.write_bytes(bytes(img) + root)
    info = xci.classify(p)
    assert info["layout"] == "standard"
    assert info["partitions"]["secure"][0]["name"] == "a.nca"
