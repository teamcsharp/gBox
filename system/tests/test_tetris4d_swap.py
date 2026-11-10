"""Writer test for the Tetris 4D portrait mod (needs the cached split GDI)."""
import hashlib
import json
from pathlib import Path

import pytest

from gbox.gdrom import GDRom
from gbox.tetris4d_pvr import decode_pvr, parse_pvr
from gbox.tetris4d_swap import build_mod, slot_path

GDI = Path("/home/ehm_eckx/gBox_alt/gbox-cache/dc/864538c6473a986e/disc.gdi")
needs_disc = pytest.mark.skipif(not GDI.exists(), reason="cached split GDI not present")


def test_slot_path():
    assert slot_path("05aka") == "MENU/MENUMODEL/05AKA.PVR"
    assert slot_path("05AKA.pvr") == "MENU/MENUMODEL/05AKA.PVR"
    with pytest.raises(ValueError):
        slot_path("nope")


@needs_disc
def test_noop_roundtrip_and_changed_donor(tmp_path):
    disc = GDRom(GDI)
    orig = disc.read("MENU/MENUMODEL/05AKA.PVR")
    donor = disc.read("MENU/MENUMODEL/05PINK.PVR")
    # no-op: the slot's own image reproduces the file byte-exactly
    m0 = build_mod(GDI, tmp_path / "noop", "05AKA", orig)
    assert m0["new_sha256"] == m0["original_sha256"]
    # changed donor
    m = build_mod(GDI, tmp_path / "mod", "05AKA", donor)
    mod = GDRom(tmp_path / "mod" / "disc.gdi")
    new = mod.read("MENU/MENUMODEL/05AKA.PVR")
    assert len(new) == len(orig) and new != orig
    h_o, h_n = parse_pvr(orig), parse_pvr(new)
    assert (h_o.width, h_o.height, h_o.gbix, h_o.dfmt) == (h_n.width, h_n.height, h_n.gbix, h_n.dfmt)
    # other portraits and the boot executable are untouched; the owned disc is unchanged
    for n in ("MENU/MENUMODEL/05AO.PVR", "MENU/MENUMODEL/05PINK.PVR", "1ST_READ.BIN"):
        assert mod.read(n) == disc.read(n)
    # new image ~ donor image (VQ quantisation error only)
    _, _, a = decode_pvr(new)
    _, _, b = decode_pvr(donor)
    err = [abs(x - y) for x, y in zip(a, b)]
    assert sum(err) / len(err) <= 12      # mean; the max is higher at VQ codebook edges
    assert json.loads((tmp_path / "mod" / ".gbox-mod.json").read_text())["slot"] == "MENU/MENUMODEL/05AKA.PVR"
    assert m["new_sha256"] != m["original_sha256"]


@needs_disc
def test_refuses_owned_disc_dir():
    with pytest.raises(ValueError):
        build_mod(GDI, GDI.parent, "05AKA", GDRom(GDI).read("MENU/MENUMODEL/05PINK.PVR"))
