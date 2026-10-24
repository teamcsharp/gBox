import os
from pathlib import Path
import hashlib
import pytest
from gbox import sshuffle_analysis as A

GDI = Path(os.environ.get("SSHUFFLE_GDI", Path.home() / "gbox-cache/dc/79ade87c3c2fad3e/disc.gdi"))
needs_disc = pytest.mark.skipif(not GDI.exists(), reason="owned Sonic Shuffle GDI not unpacked")


def test_constants_consistent():
    assert len(A.MOTION_MAP) == 27 and max(A.MOTION_MAP) == 93
    assert A.TYPE_MASK == {"pvm": 1, "njcm": 2, "nmdm": 4}
    assert A.NAME_TABLE_VA + 32 <= A.MODEL_SEL_VA


def test_synthetic_literal_scan():
    # mov.l @(1,PC),r2 at BASE: literal at ((BASE+4)&~3)+4
    exe = bytearray(32)
    exe[0:2] = (0xD201).to_bytes(2, "little")
    exe[8:12] = (0x8C0FA624).to_bytes(4, "little")
    assert A.literal_loads(bytes(exe), {A.BASE + 8}) == {A.BASE + 8: [A.BASE]}


@needs_disc
def test_pinned_loader_tables():
    from gbox.gdrom import GDRom
    exe = GDRom(GDI).read("1ST_READ.BIN")
    assert hashlib.sha256(exe).hexdigest() == A.FIRST_READ_SHA256
    p = A.probe(exe)
    assert p["names"] == [f"C0{i}.MDL" for i in range(8)]
    assert p["literal_pools"] == {hex(v): hex(A.NAME_TABLE_VA) for v in A.NAME_TABLE_XREF_LITERALS}
    assert p["users"] == sorted(hex(a) for a in A.NAME_TABLE_USERS)
    assert p["model_sel"] == [0] * 8 and p["texlist_sel"] == [0] * 8
    assert tuple(p["motion_map"]) == A.MOTION_MAP
    assert p["player_names"][0] == "SONIC" and p["player_names"][7] == "SUPER SONIC"


@needs_disc
def test_type_local_resolution_all_board_chars():
    from gbox.gdrom import GDRom
    from gbox.sshuffle_inventory import mdl_table
    g = GDRom(GDI)
    for i in range(8):
        t = mdl_table(g.read(f"CHRDATA/C0{i}.MDL"))["entries"]
        body = A.type_local(t, "model", 0)
        assert body["magic"] == "NJCM"
        assert A.type_local(t, "pvm", 0)["magic"] == "PVMH"
        assert A.type_local(t, "motion", max(A.MOTION_MAP))["magic"] == "NMDM"
    sonic = mdl_table(g.read("CHRDATA/C00.MDL"))["entries"]
    assert A.type_local(sonic, "model", 0)["index"] == 8   # body entry from the inventory
    assert A.type_local(sonic, "motion", 93)["index"] == 110
