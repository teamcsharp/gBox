import os
import struct
from pathlib import Path

import pytest

from gbox import nightfire_model as nm

LEVEL = Path(os.environ.get("GBOX_NIGHTFIRE_LEVEL",
                            Path.home() / "gbox-cache/744ba3bc797403bf/unpacked/07000001.unpacked"))


def _skin(n=3, att=1):
    head = struct.pack("<I3f", 0x05000099, 1, 1, 1) + bytes([1, 0, 0, att, 0])
    par = bytes([0xFF] + [0x80 | (i - 1) for i in range(1, n)])
    body = head + par
    body += b"\0" * (((len(body) + 3) & ~3) - len(body))
    body += struct.pack("<7f", 0, 0, 0, 0, 0, 0, -1.0)
    for _ in range(1, n):
        body += struct.pack("<7f", 0, 0.5, 0, 0, 0, 0, 1.0)
    for k in range(att):
        body += struct.pack("<2I7f", 0x34 + k, n - 1, 0.1, 0, 0, 0, 0, 0, 1.0)
    return body + b"\0" * ((-len(body)) % 16)


def test_synthetic_skin():
    sk = nm.skin_skeleton(_skin())
    assert sk["bones"] == 3 and sk["parents"] == [-1, 0, 1] and len(sk["attachments"]) == 1
    assert sk["attachments"][0]["bone"] == 2


def test_synthetic_object_and_blocks():
    node = nm.NODE_TAG + b"\0\0\0\x0f" + b"polySurface1".ljust(20, b"\0") + struct.pack(">40I", 9, 30, 2, *([0] * 37))
    obj = b"\0\0\0\0\x14\0\0\x0e\x01\0\0\x75" + b"\0" * 20 + node
    nodes = nm.object_nodes(obj)
    assert nodes[0]["name"] == "polySurface1" and nodes[0]["n_verts"] == 2
    static = b"\xfa" * 32 + struct.pack(">6h", 1, 2, 3, 16384, 0, 0) * 2 + b"\xfa" * 32 + b"\1" * 36
    off = nm.vertex_block(static, 2)
    assert off == 32
    v = nm.vertices(static, off, 2)
    assert v[0][:3] == (1, 2, 3) and nm.normal_stats(v)["mean"] == 1.0


@pytest.fixture(scope="module")
def level():
    if not LEVEL.exists():
        pytest.skip("decompressed Nightfire level 07000001 not cached")
    from gbox.nightfire_inventory import pack_index
    data = LEVEL.read_bytes()
    return data, {e["name"].lower(): e for e in pack_index(data)["entries"]}, pack_index(data)["entries"]


def _payload(data, e):
    return data[e["offset"]:e["offset"] + e["size"]]


def test_owned_bondcombat_skeleton(level):
    data, by, _ = level
    sk = nm.skin_skeleton(_payload(data, by["05000007"]))
    assert sk["hash"] == "0x05000007" and sk["bones"] == 73 and sk["bind_offset"] == 0x64
    assert len(sk["attachments"]) == 60 == sk["head"][3]
    assert all(p < i for i, p in enumerate(sk["parents"]) if i)


def test_owned_bond_model_vertices(level):
    data, by, entries = level
    e = by["01000075"]
    assert e["type"] == 2
    nodes = nm.object_nodes(_payload(data, e))
    assert [n["name"] for n in nodes] == ["bond_generic_head_g"]
    n = nodes[0]
    assert (n["n_verts"], n["n_index"], n["groups"]) == (1278, 0xD40, 22)
    # vertex pointer -> next pointer spans exactly the 12-byte vertex array plus a 0x20 pad run
    assert n["pointers"][5] - n["pointers"][3] == 1278 * 12 + 0x20
    static = _payload(data, next(x for x in entries if x["type"] == 13))
    off = nm.vertex_block(static, n["n_verts"])
    assert off == 0x4ACC0
    st = nm.normal_stats(nm.vertices(static, off, n["n_verts"]))
    assert 0.98 < st["mean"] < 1.02
