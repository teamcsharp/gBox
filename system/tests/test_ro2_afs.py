import struct
from pathlib import Path
import pytest
from gbox import ro2_afs as a
from gbox import ro2_inventory as inv

CHD = Path("/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation 2/roms/USA/"
           "Resident Evil Outbreak File #2 (USA).chd")


def test_synthetic_afs():
    h = b"AFS\0" + struct.pack("<I", 2) + struct.pack("<IIII", 2048, 16, 2064, 8)
    assert a.parse_afs(h, 3000) == [(2048, 16), (2064, 8)]
    with pytest.raises(ValueError):
        a.parse_afs(h, 2060)
    with pytest.raises(ValueError):
        a.parse_afs(b"XXXX" + h[4:])


def test_mwo3():
    h = b"MWo3" + struct.pack("<7I", 3, 1, 2, 3, 4, 5, 6)
    h = h.ljust(0x20, b"\0") + b"game.bin\0"
    assert a.parse_mwo3(h)["name"] == "game.bin"


@pytest.mark.skipif(not CHD.exists(), reason="owned CHD not mounted")
def test_owned_disc_afs_counts():
    d = inv.ChdDisc(CHD)
    try:
        got = {}
        for n in ("01", "02", "03", "04", "05"):
            p = f"BIN/{n}.DAT"
            c = struct.unpack("<I", d.read(p, 4, 4))[0]
            got[n] = len(a.parse_afs(d.read(p, 0, 8 + 8 * c), d.files[p][1]))
        assert got == {"01": 26, "02": 23, "03": 37, "04": 19, "05": 56}
        assert [a.parse_mwo3(d.read(f"BIN/{i}.DAT", 0, 64))["name"] for i in range(4)] == \
            ["submain.bin", "demo.bin", "game.bin", "netwk.bin"]
    finally:
        d.close()
