import struct
import zlib

import pytest

from gbox import sfb_fuc as f


def make(entries):
    """Build a synthetic .FUC01 container from [(path, bytes)]."""
    d = bytearray(b".FUC01\x04\x07" + struct.pack("<II", len(entries), 0))
    for p, _ in entries:
        d += b"\0" * 8 + p.encode() + b"\0"
        while len(d) % 4:
            d += b"\0"
    pos, ptr = len(d), 16
    blobs = [zlib.compress(b) for _, b in entries]
    for (p, b), z in zip(entries, blobs):
        struct.pack_into("<II", d, ptr, pos, len(b))
        ptr = (ptr + 8 + len(p) + 1 + 3) & ~3
        pos += len(z)
    struct.pack_into("<I", d, 12, pos)
    return bytes(d) + b"".join(blobs)


E = [("Q:\\PS2BOWL\\A.DFF", b"\x10\0\0\0" * 50), ("Q:\\PS2BOWL\\LONGNAME.ANM", b"xyz" * 99)]


def test_parse_and_payload():
    d = make(E)
    i = f.parse(d)
    assert [e["path"] for e in i["entries"]] == [p for p, _ in E]
    assert [f.payload(d, e) for e in i["entries"]] == [b for _, b in E]


def test_noop_rebuild_identical():
    d = make(E)
    assert f.rebuild(d) == d


def test_replace_changes_only_target():
    d = make(E)
    new = b"\x10\0\0\0abcd" * 300
    d2 = f.rebuild(d, {E[0][0]: new})
    a, b = f.parse(d2)["entries"]
    assert f.payload(d2, a) == new and a["usize"] == len(new)
    assert f.payload(d2, b) == E[1][1]
    assert f.raw(d2, b) == f.raw(d, f.parse(d)["entries"][1])
    assert f.parse(d2)["total"] == len(d2)


def test_errors():
    with pytest.raises(f.FucError):
        f.parse(b"nope" * 8)
    with pytest.raises(f.FucError):
        f.rebuild(make(E), {"missing": b""})
    d = bytearray(make(E))
    d[12] ^= 1
    with pytest.raises(f.FucError):
        f.parse(bytes(d))


def test_owned_disc_all_fuc_roundtrip():
    from gbox import sfb_inventory as s
    from gbox.gcz import GCZ
    rom = s.find_owned_rom()
    if not rom:
        pytest.skip("owned disc not present")
    m = s.build_manifest(rom)
    g = GCZ(rom)
    n = 0
    for x in m["members"]:
        if x["ext"].lower() != ".fuc":
            continue
        d = g.read(x["offset"], x["size"])
        for e in f.parse(d)["entries"]:
            f.payload(d, e)  # inflate + usize check
        assert f.rebuild(d) == d
        n += 1
    assert n == 30
