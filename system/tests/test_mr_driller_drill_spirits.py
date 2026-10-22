import hashlib, os, struct, glob, pytest
from gbox import mr_driller_drill_spirits as mod


def _pak(members):
    hs = 8 + 4 * (len(members) + 1)
    offs, o = [], hs
    for m in members:
        offs.append(o); o += len(m)
    offs.append(o)
    return b"PAK0" + struct.pack("<HH", hs, len(members)) + struct.pack("<%dI" % len(offs), *offs) + b"".join(members)


def test_pak_members_roundtrip():
    ms = [b"\xe0\x03" * 32, b"abcd" * 8]
    blob = _pak(ms)
    got = mod.pak_members(blob)
    assert [blob[o:o + n] for o, n in got] == ms


def test_pak_rejects_bad():
    with pytest.raises(ValueError):
        mod.pak_members(b"XXXX" + bytes(20))


ROM = os.environ.get("DRILLER_ROM") or next(iter(glob.glob(os.path.expanduser("~/.hermes/cache/scratch/drill/*.nds"))), None)
EXPECT = "47f60500db0f91cf6bbed1b0199494be00ac1b1771339a71601715466bb9f452"


@pytest.mark.skipif(not ROM or not os.path.exists(ROM), reason="owned ROM not available")
def test_owned_rom_inventory():
    rom = open(ROM, "rb").read()
    if hashlib.sha256(rom).hexdigest() != EXPECT:
        pytest.skip("different build")
    inv = mod.inventory(rom)
    assert inv["header"]["gamecode"] == "ADRE" and inv["file_count"] == 45
    t = inv["target"]
    assert len(t["members"]) == 8 and t["size"] == 303180
    assert all(m["pal0_key"] == 0x03E0 for m in t["members"])
