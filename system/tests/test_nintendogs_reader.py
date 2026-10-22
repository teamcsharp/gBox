import glob
import struct

import pytest

from gbox.formats.nintendogs import Nintendogs, parse_bmd0

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
