import hashlib, os, struct
import pytest
from gbox.formats import rw_dff, bertha

ISO = "/mnt/gbox/quickswap2/Emulation/PS2/NFL Blitz 2003/NFL Blitz 2003.iso"


def ch(t, body, ver=0x310):
    return struct.pack("<III", t, len(body), ver) + body


def synth():
    geo = ch(0x0F, ch(1, struct.pack("<IIII", 28, 3, 6, 1)))
    gl = ch(0x1A, ch(1, struct.pack("<I", 1)) + geo)
    fl = ch(0x0E, ch(1, struct.pack("<I", 2) + b"\0" * 56))
    return ch(0x10, ch(1, struct.pack("<I", 1)) + fl + gl + ch(0x14, ch(1, b"\0" * 16)))


def test_synthetic_probe():
    r = rw_dff.probe(synth())
    assert r["frames"] == 2 and r["declared_atomics"] == 1 and r["atomic_chunks"] == 1
    assert r["geometries"] == [{"flags": 28, "triangles": 3, "vertices": 6, "morph_targets": 1}]


def test_rejects_non_clump():
    with pytest.raises(ValueError):
        rw_dff.probe(ch(0x03, b""))


@pytest.mark.skipif(not os.path.exists(ISO), reason="owned ISO not mounted")
def test_live_ac_cnmaf():
    zm = [m for m in bertha.iso_members(ISO) if m.name.upper().endswith("BERTHA.ZIP")][0]
    with open(ISO, "rb") as f:
        es = bertha.zip_entries(f, zm.offset, zm.size)
        e = [x for x in es if x.name.lower() == "ac_cnmaf.dff"][0]
        d = bertha.zip_member_bytes(f, zm, e)
    assert hashlib.sha256(d).hexdigest() == "b9ab0292dd6966069c7c8b728a13c7286e74e48eb2b699d7ede7f0d2d62ac845"
    r = rw_dff.probe(d)
    assert r["geometries"][0]["vertices"] == 404 and r["geometries"][0]["triangles"] == 202
    assert r["frames"] == 1 and r["declared_atomics"] == 1 and r["clump_size"] == 19120
