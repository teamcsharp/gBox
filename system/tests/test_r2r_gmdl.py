import hashlib, os, struct
import pytest
from gbox import r2r_gmdl as G


def _synth():
    nv, nt = 4, 2
    b = bytearray(struct.pack("<4I", nt, nv, 0, 1))
    for i in range(nv):
        b += struct.pack("<4I4f4f", 0, i, 0, 0, i, 0.5, -1, 1, 0, 0, 1, 1) + bytes(16)
    b += struct.pack("<4I", 0, 0, 0, 0)
    for t in ((0, 1, 2), (1, 2, 3)):
        b += struct.pack("<5I6f", *t, 10, 0, 0, 0, 1, 0, 0, 1)
    b += struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1) + b"\x01\x02"
    return bytes(b)


def test_roundtrip_synthetic():
    b = _synth(); g = G.parse_gmdl(b)
    assert (g.ntri, g.nvert, len(g.tris)) == (2, 4, 2)
    assert G.write_gmdl(g) == b
    assert G.to_obj(g).count("\nf ") == 2


def test_bad_index_and_truncation():
    b = bytearray(_synth())
    with pytest.raises(ValueError):
        G.parse_gmdl(bytes(b[:100]))
    tb = G.HDR + 4 * 64 + 16
    struct.pack_into("<I", b, tb, 99)
    with pytest.raises(ValueError):
        G.parse_gmdl(bytes(b))


REAL = os.path.expanduser("~/.hermes/cache/scratch/r2r/butcher2.gmdl")


@pytest.mark.skipif(not os.path.exists(REAL), reason="owned extract not present")
def test_real_butcher2_roundtrip():
    b = open(REAL, "rb").read()
    assert hashlib.sha256(b).hexdigest() == "f470d0ce4bccb170f6c8dc903b1bf90350877caf44c983611e0f7ad5c7c3c600"
    g = G.parse_gmdl(b)
    assert (g.ntri, g.nvert) == (3472, 1742)
    assert G.write_gmdl(g) == b
