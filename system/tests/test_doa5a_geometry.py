import os
from pathlib import Path

import pytest

from gbox.doa5a_geometry import geometry_summary, load_tmc, read_geometry

ROOT = Path(os.environ.get("GBOX_DOA5A_ROOT",
            "/mnt/gbox/hyperspin/Arcade/collections/Teknoparrot/roms/DOA5"))
TMC = ROOT / "character/HELENA/costume/COS_001/HELENA_COS_001.tmc"
pytestmark = pytest.mark.skipif(not TMC.exists(), reason="owned DOA5A assets not mounted")

EXPECT = [  # name, layer, vertices, indices, stride
    ("*T_acs_earringl", 0, 591, 902, 56), ("*T_acs_earringr", 1, 591, 908, 56),
    ("WGT_acs_obil", 2, 295, 636, 60), ("WGT_acs_obir", 3, 286, 707, 60),
    ("*cs_ribbonloopl", 4, 43, 49, 64), ("*cs_ribbonloopr", 5, 44, 51, 64),
    ("*cs_ribbontarel", 6, 28, 29, 64), ("*cs_ribbontarer", 7, 28, 29, 64),
    ("WGT_cos_hel000", 8, 4411, 7281, 56), ("WGT_sweat_chest", 12, 51, 112, 60)]


@pytest.fixture(scope="module")
def raw():
    return load_tmc(str(TMC))


def test_geometry_counts_pinned(raw):
    got = [(g["name"], g["layer"], g["vertex_count"], g["index_count"], g["stride"])
           for g in read_geometry(raw)]
    assert got == EXPECT


def test_indices_in_range_and_body_symmetric(raw):
    s = geometry_summary(raw)
    assert all(g["max_index"] == g["vertex_count"] - 1 for g in s)
    body = s[8]
    assert body["bbox_min"][0] == pytest.approx(-body["bbox_max"][0])
    assert body["bbox_max"][0] == pytest.approx(0.3344783, abs=1e-6)
