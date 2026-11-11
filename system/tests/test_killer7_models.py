import os
import numpy as np
import pytest
from gbox.killer7_models import Killer7Model, export_gltf

DISC = os.path.expanduser("~/gBox_alt/gbox-cache/9c5fc8fc9dd35b0a/Killer7 (USA) (Disc 2).gcz")


@pytest.mark.skipif(not os.path.exists(DISC), reason="owned disc not present")
def test_aki_m00_geometry_and_export(tmp_path):
    from gbox.gcdisc import GCDisc
    data = GCDisc(DISC).read("3Ddata/Model/Chara/AKI/AKI_M00.dat")
    m = Killer7Model(data, 0)
    geo = m.geometry()
    assert len(geo) >= 20
    allp = np.concatenate([g["pos"] for _, g in geo])
    assert np.isfinite(allp).all()
    assert sum(len(g["tris"]) for _, g in geo) > 1000
    for _, g in geo:
        assert g["tris"].size == 0 or g["tris"].max() < len(g["pos"])
    out = export_gltf(m, tmp_path / "aki.gltf")
    assert out.exists() and out.stat().st_size > 10000
