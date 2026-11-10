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


COLORS = {"red": 6, "blue": 4, "green": 10, "yellow": 8, "purple": 5, "orange": 7}


def _sheet(rom):
    return (N.parse_ncgr(rom.raw("ncprj/blktimer.NCGR")),
            N.parse_nclr(rom.raw("ncprj/blktimer.NCLR"))["colors"])


def test_sball_binding_blktimer_palette_matches_colour_names(rom):
    # sball_<colour>.NCER frame 0 rendered from blktimer.NCGR/NCLR (2D tile map)
    # must be dominated by the colour in its name -> resolves the NCGR binding.
    g, cl = _sheet(rom)
    dom = {"red": 0, "blue": 2, "green": 1}
    for name, ch in dom.items():
        o = N.parse_ncer(rom.raw(f"ncprj/sball_{name}.NCER"))[0]["oams"][0]
        assert o["palette"] == COLORS[name]
        _, _, px = N.render_oam(g, cl, o)
        op = [p for r in px for p in r if p[3]]
        m = [sum(p[i] for p in op) / len(op) for i in range(3)]
        assert m.index(max(m)) == ch and len(op) == 69


def test_tile_writer_noop_and_donor_swap(rom):
    path = "ncprj/blktimer.NCGR"
    orig = rom.raw(path)
    g, cl = _sheet(rom)
    o = N.parse_ncer(rom.raw("ncprj/sball_red.NCER"))[0]["oams"][0]
    idx = N.oam_tile_indices(o, g["tiles_w"])
    assert idx == [724, 725, 756, 757]
    tb = g["tile_bytes"]
    px = g["pixel_data"]
    # no-op: rewriting identical tiles is byte-exact, also at ROM level
    same = N.replace_tiles(orig, {i: px[i * tb:(i + 1) * tb] for i in idx})
    assert same == orig
    info = rom._files[path]
    assert N.patch_rom_file(rom.data, info["start"], info["size"], same) == rom.data
    # donor: sball_chain frame 0 art (tile 664; colour balls share identical index art
    # and differ only by palette bank) written into the red ball frame-0 slot
    ob = N.parse_ncer(rom.raw("ncprj/sball_chain.NCER"))[0]["oams"][0]
    assert ob["tile"] == 664
    donor = {d: px[s * tb:(s + 1) * tb] for d, s in zip(idx, N.oam_tile_indices(ob, g["tiles_w"]))}
    new = N.replace_tiles(orig, donor)
    assert len(new) == len(orig) and new != orig
    changed = {i for i in range(len(orig)) if new[i] != orig[i]}
    assert changed <= set(range(len(orig)))
    mod = KonductraNDS(N.patch_rom_file(rom.data, info["start"], info["size"], new))
    assert mod.paths() == rom.paths()
    assert N.rebuild(mod.raw(path)) == mod.raw(path)
    g2 = N.parse_ncgr(mod.raw(path))
    assert [g2["pixel_data"][i * tb:(i + 1) * tb] for i in idx] == [donor[i] for i in idx]
    # everything outside the ROM file bytes is untouched
    a, b = rom.data, mod.data
    assert a[:info["start"]] == b[:info["start"]] and a[info["end"]:] == b[info["end"]:]
