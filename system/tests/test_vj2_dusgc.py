import os, pytest
from gbox.vj2_dusgc import rle_chunk, decode_dusgc, toc, MAGIC
import struct

ISO = "/mnt/gbox/quickswap2/Emulation/_emulation/GC ISO/Viewtiful Joe 2 (USA).nkit.iso"


def test_rle_synthetic():
    hdr = MAGIC + b"\0" + struct.pack(">I", 7) + b"\0" * 8 + struct.pack(">I", 1)
    buf = hdr + bytes([3, 0, 0x82, 0xAA, 0xBB, 2, 9, 0x80])
    out, tot, flag, end = rle_chunk(buf, 0)
    assert out == b"\0\0\0\xaa\xbb\x09\x09" and tot == 7 and flag == 1 and end == len(buf)


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned ISO not mounted")
def test_pl00_decodes_and_toc_tiles():
    from gbox.gcdisc import GCDisc
    d = GCDisc(ISO)
    data, n = decode_dusgc(d.read("etc/pl00.dusgc"))
    assert n == 3 and len(data) == 0x155d00
    t = toc(data)
    assert len(t) == 0x1d and t[0][0] == 0x120
    pos = t[0][0]
    for off, size in t:
        assert off == pos
        pos += size
    assert pos == len(data)
