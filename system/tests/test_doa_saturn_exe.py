import os
import struct
import pytest
from gbox import doa_saturn_exe as m

CHD = "/mnt/gbox/hyperspin/Arcade/collections/Sega Saturn/roms/Dead or Alive (Japan).chd"


def _synthetic():
    d = bytearray(0x80)
    d[0x40:0x4C] = b"FOO1_MDL.BIN"
    d[0x4C:0x58] = b"BAR_FIX1.BIN"
    struct.pack_into(">I", d, 0x20, m.LOAD_BASE + 0x4C)   # literal pool word
    struct.pack_into(">H", d, 0x10, 0xD103)               # mov.l @(3,PC),r1 -> 0x14+12=0x20
    return bytes(d)


def test_ip_header():
    s = bytearray(2048)
    s[:16] = b"SEGA SEGASATURN "
    s[0x20:0x2A] = b"T-3603G    "[:10]
    struct.pack_into(">I", s, 0xE0, 0x1800)
    struct.pack_into(">I", s, 0xF0, 0x06004000)
    h = m.ip_header(bytes(s))
    assert h["first_read_addr"] == m.LOAD_BASE and h["ip_size"] == 0x1800
    with pytest.raises(ValueError):
        m.ip_header(bytes(2048))


def test_synthetic_xrefs():
    d = _synthetic()
    assert m.name_table(d, 0x40) == ["FOO1_MDL.BIN", "BAR_FIX1.BIN"]
    x = m.string_xrefs(d, lo=0)
    assert [(r["name"], r["literal_off"], r["load_sites"]) for r in x] == [
        ("BAR_FIX1.BIN", 0x20, [m.LOAD_BASE + 0x10])]


@pytest.mark.skipif(not os.path.exists(CHD), reason="owned CHD not mounted")
def test_owned_build():
    d = m.read_exe(CHD)
    assert m.verify_exe(d)["ok"]
    assert d[:2] == bytes.fromhex("d408")
    x = {}
    for r in m.string_xrefs(d):
        x.setdefault(r["name"], r)
    assert x["NAME_MDL.BIN"]["literal_off"] == 0x7EE44
    assert x["NAME_MDL.BIN"]["load_sites"] == [m.LOAD_BASE + 0x7ED3C, m.LOAD_BASE + 0x7ED9C]
    assert x["FIX2.BIN"]["literal_off"] == 0x3C994
    assert m.name_table(d, 0x33A34)[:3] == ["KL1_OPT.BIN", "FA1_OPT.BIN", "TN2_OPT.BIN"]
