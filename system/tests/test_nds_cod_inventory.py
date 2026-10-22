import os
import struct
import pytest
from gbox import nds_cod_inventory as m

ROM = "/home/ehm_eckx/gBox_alt/gbox-cache/d9467f457f53f2c7/2905 - Call of Duty - World at War (U)(Venom).nds"


def _rom():
    d = bytearray(0x1000)
    d[:12] = b"TEST"; d[12:16] = b"CALE"
    fnt = 0x200
    # root dir entry: sub offset 8, first file id 0, parent count
    struct.pack_into("<IHH", d, fnt, 8, 0, 1)
    name = b"a.bin"
    d[fnt + 8] = len(name); d[fnt + 9:fnt + 9 + 5] = name
    fat = 0x300
    struct.pack_into("<2I", d, fat, 0x400, 0x404)
    d[0x400:0x404] = b"wxyz"
    struct.pack_into("<4I", d, 0x20, 0x100, 0x2000800, 0x2000000, 0x10)
    struct.pack_into("<4I", d, 0x30, 0x120, 0x2380000, 0x2380000, 0x10)
    struct.pack_into("<4I", d, 0x40, fnt, 0x20, fat, 8)
    return bytes(d)


def test_synthetic_fs():
    d = _rom()
    assert m.nds_files(d) == [{"path": "a.bin", "off": 0x400, "size": 4}]
    assert m.nds_header(d)["arm9"]["size"] == 0x10


def test_bad_extent():
    d = bytearray(_rom()); struct.pack_into("<2I", d, 0x300, 0x400, 0x9999)
    with pytest.raises(ValueError):
        m.nds_files(bytes(d))


def test_bmd0_bounds():
    b = b"BMD0" + struct.pack("<HHIHH", 0xFEFF, 2, 24, 16, 1) + struct.pack("<I", 20) + b"MDL0" + struct.pack("<I", 100)
    with pytest.raises(ValueError):
        m.bmd0_probe(b)
    with pytest.raises(ValueError):
        m.bmd0_probe(b"XXXX" + b"\0" * 20)


@pytest.mark.skipif(not os.path.exists(ROM), reason="owned ROM absent")
def test_owned_rom():
    d = open(ROM, "rb").read()
    h = m.nds_header(d)
    assert h["gamecode"] == "CALE" and h["arm9"]["size"] == 1726040
    assert h["arm9"]["sha256"] == "653cbaa4b02ee3c5a48f434b72276cb1080cb98f02deb6de3de4c02454f2548f"
    fs = {f["path"]: f for f in m.nds_files(d)}
    assert len(fs) == 3039
    f = fs["Models/american.nsbmd"]
    p = m.bmd0_probe(d[f["off"]:f["off"] + f["size"]])
    assert set(p["sections"]) == {"MDL0", "TEX0"}
