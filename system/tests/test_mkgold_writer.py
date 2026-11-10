"""MK Gold GEO writer: no-op roundtrip, block replacement, donor compatibility, owned-disc swap."""
import struct
from pathlib import Path

import pytest

from gbox import mkgold_geo as mg
from gbox import mkgold_writer as mw
from gbox.mkgold_inventory import geo_records
from tests.test_mkgold_geo import _geo, _strip, _v

GDI = Path.home() / "gbox-cache" / "dc" / "25cfe1a8f7ab69cd" / "disc.gdi"


def _strips(k=1):
    return [_strip(0, [_v((i, j, 0)) for j in range(4)]) for i in range(k)]


def test_noop_rebuild_is_identical():
    geo = _geo([_strips(2), _strips(1), _strips(3)])
    assert mw.rebuild_geo(geo) == geo


def test_encode_part_inverts_part_strips():
    geo = _geo([_strips(3)])
    rec = geo_records(geo)[0]
    assert mw.encode_part(mg.part_strips(geo, rec)) == geo[rec["offset"]:rec["offset"] + 3 * (32 + 4 * 32)]


def test_replace_block_relays_later_records_and_header():
    geo = _geo([_strips(1), _strips(1), _strips(1)])
    new = b"".join(_strips(3))
    out = mw.rebuild_geo(geo, {1: new}, {1: 3})
    assert struct.unpack_from("<I", out, 4)[0] == len(out) == len(geo) + 2 * (32 + 4 * 32)
    recs = geo_records(out)
    assert recs[1]["n"] == 3 and recs[1]["bytes"] == len(new)
    assert [r["bytes"] for r in recs] == [32 + 128, len(new), 32 + 128]
    assert out[recs[2]["offset"]:] == geo[geo_records(geo)[2]["offset"]:]


def test_replace_missing_record_refused():
    with pytest.raises(ValueError):
        mw.rebuild_geo(_geo([_strips(1)]), {5: b""})


def _img(w, h):
    return b"0.1v" + struct.pack("<II", 0x20 + 32 + w * h * 2, 1) + bytes(20) + struct.pack("<HH", w, h) + bytes(28) + bytes(w * h * 2)


def test_swap_check_flags_missing_parts_and_page_size():
    t = _geo([_strips(1), _strips(1)])
    assert mw.swap_check(t, _img(8, 4), t, _img(8, 4)) == []
    bad = mw.swap_check(t, _img(8, 4), _geo([_strips(1)]), _img(4, 4))
    assert len(bad) == 3


@pytest.mark.skipif(not GDI.exists(), reason="owned MK Gold disc unpack not present")
def test_owned_disc_roundtrip_and_donor_in_slot(tmp_path):
    from gbox.gdrom import GDRom
    g = GDRom(GDI)
    names = sorted(n for n in g.files if n.endswith(".GEO"))
    r = mw.roundtrip(g.read, names)
    assert r["files"] == 149 and r["identical"] == 149 and r["records_reencoded"] == 2549
    files = {"JA_GEO.GEO": g.read("KL_GEO.GEO"), "JA_GEO.IMG": g.read("KL_GEO.IMG")}
    gdi = mw.patch_disc(GDI, tmp_path, "t", files)
    m = GDRom(gdi)
    assert all(m.read(k) == v for k, v in files.items())
    assert m.files["JA_GEO.GEO"][1] == len(files["JA_GEO.GEO"])
    assert m.read("KL_GEO.GEO") == g.read("KL_GEO.GEO") and m.read("SZ_GEO.GEO") == g.read("SZ_GEO.GEO")
    with pytest.raises(ValueError):
        mw.patch_disc(GDI, tmp_path / "x", "t", {"KL_GEO.GEO": g.read("SZ_GEO.GEO")})
