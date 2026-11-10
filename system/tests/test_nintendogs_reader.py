import glob
import struct

import pytest

from gbox.formats.nintendogs import Nintendogs, analyze_nsbmd, parse_bmd0, parse_dict

ROM = glob.glob("/home/ehm_eckx/gBox_alt/gbox-hermes-tasks/e738c6c507d448d2/work/source/*.nds")


def _bmd0():
    body = b"MDL0" + struct.pack("<I", 8)
    hdr = b"BMD0" + struct.pack("<HHIHH", 0xFEFF, 2, 16 + 4 + len(body), 16, 1) + struct.pack("<I", 20)
    return hdr + body


def test_parse_bmd0_synthetic():
    b = parse_bmd0(_bmd0())
    assert b["blocks"] == {"MDL0": (20, 8)}


def test_parse_bmd0_rejects_bad():
    with pytest.raises(ValueError):
        parse_bmd0(b"XXXX" + bytes(40))


@pytest.mark.skipif(not ROM, reason="owned ROM not extracted")
def test_real_rom_slots_and_model():
    g = Nintendogs(open(ROM[0], "rb").read())
    s = g.slots()
    assert len(s) == 70 and "Bgl_a" in s
    name, data, info = g.export_model("Bgl_a")
    assert name == "Bgl_a.nsbmd" and len(data) == 63932
    assert "MDL0" in info["blocks"]
    assert len(g.shared_animations()) == 597


def test_parse_dict_rejects_overrun():
    with pytest.raises(ValueError):
        parse_dict(bytes([0, 1, 0xFF, 0x7F]) + bytes(16), 0)


@pytest.mark.skipif(not ROM, reason="owned ROM not extracted")
def test_bgl_a_analysis():
    g = Nintendogs(open(ROM[0], "rb").read())
    a = analyze_nsbmd(g.export_model("Bgl_a")[1])
    m = a["models"][0]
    assert (m["n_bones"], m["n_materials"], m["n_shapes"], m["n_vertices"]) == (30, 3, 3, 1132)
    assert m["bones"][0] == "skl_root" and m["bones"][-1] == "tail3" and len(m["bones"]) == 30
    t = {x["name"]: x for x in a["textures"]}
    assert t["Bgl_a_all"]["format"] == "tex4x4" and (t["Bgl_a_all"]["width"], t["Bgl_a_all"]["height"]) == (256, 256)
    assert len(t) == 7
    sk = analyze_nsbmd(g.rom.raw("Dog/Model/Tan_model.nsbmd"))["models"][0]
    assert sk["bones"] == ["jnt_root", "jnt1", "jnt2"]


@pytest.mark.skipif(not ROM, reason="owned ROM not extracted")
def test_all_slots_parse():
    g = Nintendogs(open(ROM[0], "rb").read())
    bones = set()
    for s in g.slots():
        a = analyze_nsbmd(g.export_model(s)[1])
        assert a["models"] and a["textures"]
        bones.add(a["models"][0]["n_bones"])
    assert bones  # bone-count variety recorded by the printed -s output
    print(sorted(bones))
