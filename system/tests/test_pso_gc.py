import tempfile
from pathlib import Path

import pytest

from gbox import gcdisc, pso_gc

ISO = Path.home() / "gbox-cache" / "gc" / "436e0bb84d5337d1" / "disc.iso"


@pytest.mark.skipif(not ISO.exists(), reason="owned ISO not present")
def test_player_body_decode():
    disc = gcdisc.GCDisc(ISO)
    for cls in ("A", "C", "X"):
        nj = pso_gc.read_body(disc, cls)
        assert len(nj.bones) == 64
        assert nj.tris


@pytest.mark.skipif(not ISO.exists(), reason="owned ISO not present")
def test_export_hucast_body_glb():
    disc = gcdisc.GCDisc(ISO)
    with tempfile.TemporaryDirectory() as td:
        glb = pso_gc.export_body(ISO, "HUcast", Path(td) / "out")
        assert glb.exists() and glb.stat().st_size > 0


@pytest.mark.skipif(not ISO.exists(), reason="owned ISO not present")
def test_gvm_header_probe():
    disc = gcdisc.GCDisc(ISO)
    info = pso_gc.gvm_list(disc.read("player00.gvm"))
    assert info["count"] == 1
    assert info["names"][0] == "hcs_test01"
    info2 = pso_gc.gvm_list(disc.read("player01.GVM"))
    assert info2["count"] == 9
    assert info2["names"][0] == "a_core"
