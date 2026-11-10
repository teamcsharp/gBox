import json
import os
import struct

import pytest

from gbox import re5_switch_collision as C

ARCH = os.path.expanduser("~/gBox_alt/switch/romfs/010018100CD46000/nativeNXx64/ImgNX/Archive")
REPORT = os.path.join(os.path.dirname(__file__), "..", "docs", "research", "re5-switch-mercs-collision.json")


def test_rle_roundtrip():
    row = "  ..##.  ...#"
    assert C.unrle_row(C.rle_row(row)) == row


def test_grid_floor_and_wall():
    # 4 m x 4 m floor (two triangles, normal +y) and a 2 m wall at x = 2 m across it
    v = [(0, 0, 0), (0, 0, 4), (4, 0, 0), (4, 0, 4), (2, 0, 0), (2, 2, 0), (2, 0, 4), (2, 2, 4)]
    t = [(0, 1, 2), (2, 1, 3), (4, 5, 6), (6, 5, 7)]
    assert C.classify(v, t)[0][3][1] > 0.99
    g = C.walk_grid(v, t)
    assert g["floor_cells"] > 0 and g["blocked_cells"] > 0
    mid = g["rows_chars"][g["rows"] // 2]
    assert "#" in mid and "." in mid


def test_bad_magic():
    with pytest.raises(ValueError):
        C.parse_packfile(b"\0" * 128)


@pytest.mark.skipif(not os.path.isdir(ARCH), reason="Switch romfs not present")
def test_s403_real_stage():
    (verts, tris), = C.simple_meshes(C.load_stage(ARCH, 403))
    assert (len(verts), len(tris)) == (901, 1352)


def test_report_matches_counts():
    r = json.load(open(REPORT))
    assert sorted(r["stages"]) == ["s%d" % n for n in range(400, 408)]
    s = r["stages"]["s400"]
    assert (s["vertices"], s["triangles"]) == (3939, 5587)
    rows = [C.unrle_row(x) for x in s["grid"]["rows_rle"]]
    assert len(rows) == s["grid"]["rows"] and all(len(x) == s["grid"]["cols"] for x in rows)
    assert sum(x.count(".") for x in rows) == s["grid"]["floor_cells"]
