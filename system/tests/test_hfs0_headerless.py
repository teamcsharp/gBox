import hashlib
import struct

import pytest

from gbox.formats import hfs0


def _hfs0(files, hashed=0x200):
    pool = b"".join(n.encode() + b"\0" for n, _ in files)
    ents, off, no = b"", 0, 0
    for n, d in files:
        ents += struct.pack("<QQIIQ", off, len(d), no, min(hashed, len(d)), 0) + hashlib.sha256(d[:hashed]).digest()
        off += len(d)
        no += len(n) + 1
    return b"HFS0" + struct.pack("<III", len(files), len(pool), 0) + ents + pool + b"".join(d for _, d in files)


def _card(root_at=0xF000):
    secure = _hfs0([("a.nca", b"A" * 700), ("b.tik", b"B" * 40)])
    root = _hfs0([("update", _hfs0([])), ("secure", secure)])
    img = bytearray(root_at + len(root))
    img[0x100:0x104] = b"HEAD"
    struct.pack_into("<Q", img, 0x130, root_at)
    img[root_at:] = root
    return bytes(img)


def _ra(img):
    return lambda o, n: img[o:o + n]


def test_lists_partitions_and_hashes():
    img = _card()
    parts = hfs0.list_card(_ra(img), len(img))
    assert set(parts) == {"update", "secure"}
    names = [(e.name, e.size) for e in parts["secure"]]
    assert names == [("a.nca", 700), ("b.tik", 40)]
    e = parts["secure"][0]
    assert img[e.offset:e.offset + 700] == b"A" * 700
    assert e.sha256 == hashlib.sha256(b"A" * 512).hexdigest()


def test_default_root_when_header_field_zero():
    img = bytearray(_card())
    struct.pack_into("<Q", img, 0x130, 0)
    assert "secure" in hfs0.list_card(_ra(bytes(img)))


def test_rejects_non_card_and_truncated():
    with pytest.raises(ValueError):
        hfs0.list_card(_ra(b"\0" * 0x20000))
    img = _card()
    with pytest.raises(ValueError):
        hfs0.list_card(_ra(img[:-100]), len(img) - 100)
    with pytest.raises(ValueError):
        hfs0.parse_hfs0(_ra(b"XXXX" + b"\0" * 64), 0)


def test_disc_lists_xci(tmp_path):
    from gbox.formats import disc
    p = tmp_path / "g.xci"
    p.write_bytes(_card())
    fn = disc.listing
    L = fn(str(p))
    assert L.kind == "switch_xci"
    assert {f["path"] for f in L.files} == {"secure/a.nca", "secure/b.tik"}
