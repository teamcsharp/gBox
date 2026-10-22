import struct
import pytest
from gbox import r2r_inventory as r


def _make_rat(entries):
    hdr = r.RAT_MAGIC + struct.pack("<I", len(entries)) + b"\0" * 20
    body = b""
    off = r.RAT_HEADER + len(entries) * r.RAT_ENTRY
    payload = b""
    for name, data in entries:
        body += name.encode().ljust(16, b"\0") + struct.pack("<IIII", len(data), 0, 0, off + len(payload))
        payload += data
    return hdr + body + payload


def test_rat_roundtrip_and_tiling():
    blob = _make_rat([("BUTCHER2GMDLRII", b"A" * 10), ("BUTCHER2WTEXNUL", b"B" * 7)])
    ents = r.parse_rat_table(lambda o, n: blob[o:o + n], len(blob))
    assert [e.name for e in ents] == ["BUTCHER2GMDLRII", "BUTCHER2WTEXNUL"]
    assert ents[-1].offset + ents[-1].size == len(blob)
    assert blob[ents[0].offset:ents[0].offset + ents[0].size] == b"A" * 10
    assert [e.name for e in r.character_models(ents)] == ["BUTCHER2GMDLRII"]


def test_rat_rejects_bad_magic_and_overrun():
    with pytest.raises(ValueError):
        r.parse_rat_table(lambda o, n: b"X" * n, 100)
    blob = _make_rat([("A", b"1234")])
    with pytest.raises(ValueError):
        r.parse_rat_table(lambda o, n: blob[o:o + n], len(blob) - 2)


def test_classify():
    assert r.classify("BUTCHER2GMDLRII") == ("BUTCHER2", "GMDL", "RII")
    assert r.classify("AFRO3DTEXNUL") == ("AFRO3", "DTEX", "NUL")
    assert r.classify("CHARLISTCHLTRII")[1] == ""


def _sector(user):
    return b"\0" * 16 + user.ljust(2048, b"\0") + b"\0" * (2352 - 16 - 2048)


def _rec(name, lba, size, d=False):
    n = name.encode()
    l = 33 + len(n)
    l += l % 2
    e = bytearray(l)
    e[0] = l
    e[2:6] = struct.pack("<I", lba)
    e[10:14] = struct.pack("<I", size)
    e[25] = 2 if d else 0
    e[32] = len(n)
    e[33:33 + len(n)] = n
    return bytes(e)


def test_walk_iso_synthetic():
    base = r.PVD_LBA
    pvd = bytearray(2048)
    pvd[0:6] = b"\x01CD001"
    pvd[156:190] = _rec("\x00", base + 4, 2048, True)[:34]
    root = _rec("\x00", base + 4, 2048, True) + _rec("\x01", base + 4, 2048, True) \
        + _rec("BOXING.RAT;1", 73017, 123) + _rec("SUB", base + 5, 2048, True)
    sub = _rec("\x00", base + 5, 2048, True) + _rec("\x01", base + 4, 2048, True) + _rec("A.SFD;1", 9, 5)
    img = bytearray(b"\0" * (r.RAW_SECTOR * (base + 6)))
    for lba, u in [(base, bytes(pvd)), (base + 4, root), (base + 5, sub)]:
        img[lba * r.RAW_SECTOR:(lba + 1) * r.RAW_SECTOR] = _sector(u)
    files = r.walk_iso(r.RawDisc(bytes(img)))
    assert ("BOXING.RAT", 73017, 123) in files and ("SUB/A.SFD", 9, 5) in files
