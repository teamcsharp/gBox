import os, struct, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gbox import capcom_slots as cs
from gbox.psxdisc import RawBin

REAL = os.environ.get("CAPCOM_GEN_BIN", "/home/ehm_eckx/.bin")


def synth(paths):
    taddr = 0x80010000
    strs = b"".join(p.encode() + b"\0" for p in paths)
    offs, o = [], 0
    for p in paths:
        offs.append(taddr + o); o += len(p) + 1
    pad = (-len(strs)) % 4
    body = strs + b"\0" * pad + b"".join(struct.pack("<I", x) for x in offs) + b"\0" * 8
    hdr = bytearray(0x800); hdr[:8] = b"PS-X EXE"; struct.pack_into("<I", hdr, 0x18, taddr)
    return bytes(hdr) + body


def test_synthetic_table():
    paths = ["\\1943\\CHAR.DEE;1", "\\1943\\OBJ01.DEE;1"] + ["\\X\\F%d.DEE;1" % i for i in range(8)]
    t = cs.slot_table(synth(paths))
    assert t[0] == "1943/CHAR.DEE" and t[1] == "1943/OBJ01.DEE" and len(t) == 10


def test_not_exe():
    with pytest.raises(ValueError):
        cs.find_slot_tables(b"x" * 4096)


@pytest.mark.skipif(not os.path.exists(REAL), reason="owned disc not present")
def test_real_p1943():
    d = RawBin(REAL, writable=False)
    t = cs.slot_table(d.read("P1943.EXE"))
    assert len(t) == 27
    assert t[0] == "1943/CHAR.DEE" and t[1] == "1943/OBJ01.DEE" and t[26] == "1943/43CHAR7.DEE"
    assert all(p in d.files for p in t.values())
