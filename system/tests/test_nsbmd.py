import struct
import pytest
from gbox.formats import nsbmd


def _dict(names, ptrs):
    n = len(names)
    tree = b"\0" * (4 * (n + 1))
    body = struct.pack("<HH", 4 + 4 * n + 4 * 0, 4 + 4 * n) + struct.pack("<HH", 4, 4)  # unit hdr
    body = struct.pack("<HH", 4, 4) + b"".join(struct.pack("<I", p) for p in ptrs)
    names_b = b"".join(x.encode().ljust(16, b"\0") for x in names)
    head_len = 8 + len(tree) + len(body) + len(names_b)
    return struct.pack("<BBHHH", 0, n, head_len, 8, 0) + tree + body + names_b


def make(name="p_test"):
    d = _dict([name], [0x40])
    mdl = b"MDL0" + struct.pack("<I", 8 + len(d)) + d
    off = 0x14
    hdr = b"BMD0" + struct.pack("<HHIHH", 0xFEFF, 2, 0x14 + len(mdl), 0x10, 1) + struct.pack("<I", off)
    return hdr + mdl


def test_parse_names():
    r = nsbmd.parse(make("p_hero"))
    assert r["models"] == ["p_hero"] and "MDL0" in r["blocks"]


def test_rejects_bad():
    with pytest.raises(ValueError):
        nsbmd.parse(b"NOPE" + b"\0" * 32)
