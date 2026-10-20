import os
import struct
import tempfile
from pathlib import Path

import pytest

from gbox import gcdisc, pso_gc

ISO = Path(os.environ.get("GBOX_PSO_GC_ISO", Path.home() / "gBox_alt/gbox-cache" / "gc" / "436e0bb84d5337d1" / "disc.iso"))


def _gvm(names, flags=0x000F):
    stride = 2 + (28 if flags & 8 else 0) + (2 if flags & 4 else 0) + (2 if flags & 2 else 0) + (4 if flags & 1 else 0)
    body = b""
    for i, n in enumerate(names):
        e = struct.pack(">H", i)
        if flags & 8:
            e += n.encode().ljust(28, b"\0")
        e += b"\0" * (stride - len(e))
        body += e
    hsize = 4 + len(body)
    return b"GVMH" + struct.pack("<I", hsize) + struct.pack(">HH", flags, len(names)) + body + b"GVRT"


def test_gvm_list_uses_flag_driven_entry_stride():
    info = pso_gc.gvm_list(_gvm(["a_core", "b_arm", "c_leg"]))
    assert info["count"] == 3 and info["flags"] == 0xF
    assert info["names"] == ["a_core", "b_arm", "c_leg"]          # 38-byte entries, not 0x20
    assert pso_gc.gvm_list(_gvm(["x", "y"], flags=0x0008))["names"] == ["x", "y"]
    assert pso_gc.gvm_list(_gvm(["x", "y"], flags=0x0001))["names"] == ["tex0", "tex1"]


def test_gvm_list_rejects_bad_input():
    with pytest.raises(ValueError):
        pso_gc.gvm_list(b"PVMH" + bytes(12))
    with pytest.raises(ValueError):
        pso_gc.gvm_list(b"GVMH" + struct.pack("<I", 4) + struct.pack(">HH", 0xF, 500))


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
