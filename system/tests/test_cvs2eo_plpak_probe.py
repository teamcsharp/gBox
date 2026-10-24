import struct, pytest
from gbox.cvs2eo_plpak_probe import parse_plpak

def synth():
    secA, n = 0x20, 4
    first = secA + 4 * n
    tbl = [first, first + 8, first + 16, first + 20]
    body = b"\0" * 24
    secB = first + len(body)
    tb = [0x10, 0x20, 0x30]
    d = struct.pack("<8I", 0, secA, 0, secB, 0, secB + 12 + 4, 0, 0)
    d += struct.pack("<4I", *tbl) + body + struct.pack("<3I", *tb) + b"\0" * 8
    return d

def test_synth():
    r = parse_plpak(synth())
    assert r["a_count"] == 4 and r["a_monotone"] and r["a_in_range"]

def test_bad():
    with pytest.raises(ValueError):
        parse_plpak(b"\1" * 64)
