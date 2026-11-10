import hashlib
import os
import struct

import pytest

from gbox import unreal_le as u


def test_compact_index_roundtrip():
    for v in (0, 1, 63, 64, 0x466, 29497, 458537, -1, -18, -64, -5000):
        b = u.write_ci(v)
        assert u.read_ci(b + b"\xff", 0) == (v, len(b))
    assert u.read_ci(bytes([0x66, 0x11]), 0) == (0x466, 2)
    assert u.read_ci(bytes([0x79, 0xCC, 0x03]), 0) == (29497, 3)


def _build():
    names = ["None", "Core", "Package", "StaticMesh", "Class", "Grp", "Mesh"]
    nb = b"".join(bytes([len(n) + 1]) + n.encode() + b"\0" + b"\x00\x00\x07\x00" for n in names)
    name_off = 0x40
    imports = [(1, 4, 0, 3), (1, 4, 0, 2)]  # Core.Class StaticMesh, Core.Class Package
    ib = b"".join(struct.pack("<BBiB", *i) for i in imports)
    body = b"\x00" + b"M" * 100
    data_off = name_off + len(nb)
    imp_off = data_off + len(body)
    exp_off = imp_off + len(ib)
    e0 = u.write_ci(-2) + u.write_ci(0) + struct.pack("<i", 0) + u.write_ci(5) + struct.pack("<I", 0x70004) + u.write_ci(1) + u.write_ci(data_off)
    e1 = u.write_ci(-1) + u.write_ci(0) + struct.pack("<i", 1) + u.write_ci(6) + struct.pack("<I", 0xF0004) + u.write_ci(100) + u.write_ci(data_off + 1)
    head = u.TAG_LE + struct.pack("<II", 0x210066, 1) + struct.pack("<6I", len(names), name_off, 2, exp_off, 2, imp_off)
    head = head.ljust(name_off, b"\0")
    return head + nb + body + ib + e0 + e1


def test_synthetic_package():
    d = _build()
    pkg = u.parse_package(d)
    assert (pkg["version"], pkg["licensee"]) == (102, 33)
    assert [e["name"] for e in pkg["exports"]] == ["Grp", "Mesh"]
    assert pkg["exports"][1]["class"] == "StaticMesh"
    assert u.group_of(pkg, pkg["exports"][1]) == "Grp"
    assert u.export_data(pkg, d, 1) == b"M" * 100
    assert u.check_chain(pkg)
    assert pkg["export_table_end"] == len(d)


def test_rejects_non_package():
    with pytest.raises(ValueError):
        u.parse_package(b"\0" * 64)


REAL = os.path.expanduser("~/.hermes/cache/scratch/EMeshCharacter.usx")


@pytest.mark.skipif(not os.path.exists(REAL), reason="extracted EMeshCharacter.usx not present")
def test_real_emeshcharacter():
    d = open(REAL, "rb").read()
    pkg = u.parse_package(d)
    assert len(d) == 490085
    assert len(pkg["exports"]) == 44 and len(pkg["names"]) == 65 and len(pkg["imports"]) == 18
    assert u.check_chain(pkg) and pkg["export_table_end"] == len(d)
    meshes = [e for e in pkg["exports"] if e["class"] == "StaticMesh"]
    assert len(meshes) == 24
    assert sum(e["size"] for e in meshes) + 20 == 0x77728 - 0x466
    assert {(u.group_of(pkg, e), e["name"]) for e in meshes} >= {("Elite", "EliteHelmetGoggle"), ("Cook", "CookHat")}
