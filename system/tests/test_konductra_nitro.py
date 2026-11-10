import struct
from pathlib import Path
import pytest
from gbox import konductra_nitro as N
from gbox.konductra import KonductraNDS

ROM = next(Path.home().glob(".hermes/cache/scratch/kondu/*.nds"), None)
pytestmark = pytest.mark.skipif(ROM is None, reason="owned ROM not extracted")


@pytest.fixture(scope="module")
def rom():
    return KonductraNDS(ROM.read_bytes())


def test_all_nitro_files_noop_roundtrip(rom):
    n = 0
    for p in rom.paths():
        b = rom.raw(p)
        if b[:4] in N.NITRO_MAGICS:
            assert N.rebuild(b) == b, p
            n += 1
    assert n == 168


def test_sball_red_slot(rom):
    cells = N.parse_ncer(rom.raw("ncprj/sball_red.NCER"))
    assert len(cells) == 4
    o = cells[0]["oams"][0]
    assert (o["tile"], o["palette"], o["dims"], o["colors256"]) == (724, 6, (16, 16), False)
    assert N.tiles_used(cells)[:4] == [724, 725, 726, 727]
    pal = N.parse_nclr(rom.raw("ncprj/mainmenusprites.NCLR"))
    assert pal["banks"] == 16 and len(pal["colors"]) == 256
    g = N.parse_ncgr(rom.raw("ncprj/blktimer.NCGR"))
    assert g["bpp"] == 4 and g["tile_count"] == 1024
    assert not N.tile_is_blank(g, 724)
    assert N.parse_nanr(rom.raw("ncprj/sball_red.NANR"))["sequences"] == 1


def test_bad_header_rejected():
    with pytest.raises(ValueError):
        N.blocks(b"RGCN" + b"\0" * 12)
