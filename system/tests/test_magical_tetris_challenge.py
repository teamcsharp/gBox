import os
import struct
import pytest
from gbox import magical_tetris_challenge as m

BIN = os.environ.get("MTC_BIN")  # extracted MODE2/2352 bin of the owned CHD


def _pac(chunks):
    hdr = struct.pack("<II", len(chunks), 0) + b"".join(struct.pack("<II", t, len(p)) for t, p in chunks)
    body = b"".join(p + b"\0" * (-len(p) % 0x800) for _, p in chunks)
    out = bytearray(hdr.ljust(0x800, b"\0") + body)
    struct.pack_into("<I", out, 4, len(out))
    return bytes(out)


def test_synthetic_pac_roundtrip():
    data = _pac([(5, b"a" * 0x900), (6, b"b" * 4)])
    cs = m.parse_pac(data)
    assert [(c.type, c.size, c.offset) for c in cs] == [(5, 0x900, 0x800), (6, 4, 0x1800)]
    assert m.chunk_bytes(data, cs[1]) == b"bbbb"


def test_bad_pac_rejected():
    data = bytearray(_pac([(5, b"x" * 10)]))
    with pytest.raises(ValueError):
        m.parse_pac(bytes(data[:-0x800]))
    struct.pack_into("<I", data, 12, 0x5000)
    with pytest.raises(ValueError):
        m.parse_pac(bytes(data))


@pytest.mark.skipif(not BIN or not os.path.exists(BIN), reason="owned disc bin not provided (MTC_BIN)")
def test_owned_build_all_pacs_and_exe():
    from gbox.psxdisc import RawBin
    d = RawBin(BIN, False)
    assert len(d.files) == 98
    pacs = [f for f in d.files if f.endswith(".PAC")]
    assert len(pacs) == 59
    total = 0
    for f in pacs:
        total += len(m.parse_pac(d.read(f)))
    assert total == 160
    exe = m.parse_psx_exe(d.read("SCES_021.54"))
    assert exe["load"] == 0x80140000 and exe["size"] == 741376
