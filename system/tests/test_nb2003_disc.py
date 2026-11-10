import struct

import pytest

from gbox.gcdisc import GCDisc
from gbox.nb2003_disc import splice_file


def _tiny_iso(path, payload):
    fst_off = 0x1000
    data_off = 0x2000
    names = b"\0a.bin\0"
    fst = struct.pack(">BBHII", 1, 0, 0, 0, 2) + struct.pack(">BBHII", 0, 0, 0, 1, 0)[:0]
    root = struct.pack(">II", 0x01000000, 0) + struct.pack(">I", 2)
    ent = struct.pack(">III", 0x00000001, data_off, len(payload))
    fst = root + ent + names
    img = bytearray(0x3000)
    img[0:6] = b"TEST01"
    struct.pack_into(">II", img, 0x424, fst_off, len(fst))
    img[fst_off:fst_off + len(fst)] = fst
    img[data_off:data_off + len(payload)] = payload
    path.write_bytes(bytes(img))


def test_splice_same_size_only(tmp_path):
    iso = tmp_path / "t.iso"
    _tiny_iso(iso, b"AAAA")
    before = iso.read_bytes()
    with pytest.raises(ValueError):
        splice_file(str(iso), "a.bin", b"BBBBB")
    assert iso.read_bytes() == before
    off, size = splice_file(str(iso), "a.bin", b"BBBB")
    after = iso.read_bytes()
    assert (off, size) == (0x2000, 4)
    assert after[off:off + 4] == b"BBBB"
    assert after[:off] == before[:off] and after[off + 4:] == before[off + 4:]
    d = GCDisc(str(iso))
    assert d.read("a.bin") == b"BBBB"
