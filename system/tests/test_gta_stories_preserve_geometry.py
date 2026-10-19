from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import gta_stories_models as M


def test_preserve_geometry_resolves_from_profile():
    assert M._preserve_geometry(None) is False
    assert M._preserve_geometry({}) is False
    assert M._preserve_geometry({"profile": {}}) is False
    assert M._preserve_geometry({"profile": {"preserve_geometry": True}}) is True
    assert M._preserve_geometry({"profile": {"preserve_geometry": False}}) is False


def test_swap_files_preserve_geometry_reports_oversized_without_decimating(tmp_path, monkeypatch):
    """An operator-edited donor with preserve_geometry must not be silently collapsed to fit the native .mdl budget:
    the writer reports the exact shortfall instead of calling the Blender decimator."""
    from gbox import re4gc_enemies as RE

    disc = SimpleNamespace(special=lambda e: {"sector": 0, "sectors": 1, "name": e},
                           file_at=lambda s: b"")
    prim = {"pos": np.zeros((3, 3)), "nrm": np.zeros((3, 3)), "uv": np.zeros((3, 2)),
            "J": np.zeros((3, 1), int), "tris": np.array([[0, 1, 2]]), "color": (255, 255, 255, 255)}
    monkeypatch.setattr(M, "read_ped", lambda b: SimpleNamespace(bone_names=lambda: ["bone"]))
    monkeypatch.setattr(M, "txd_for", lambda d, e: (0, 1))
    monkeypatch.setattr(M, "read_chk", lambda b: [])
    monkeypatch.setattr(M, "texture_slots",
                        lambda m, t: [{"texture": "x", "material": 0, "size": (64, 64), "depth": 8}])
    monkeypatch.setattr(M, "retarget_onto", lambda *a, **k: [prim])
    monkeypatch.setattr(M, "pack_atlases",
                        lambda prims, sizes: ([np.zeros((64, 64, 4), np.uint8)], [(0, np.zeros((1, 3, 2)))]))
    monkeypatch.setattr(M, "build_geometry", lambda m, groups: (b"", {"triangles": 1000}))
    # one IMG sector = 2048 bytes; return a 4096-byte .mdl so the fit is oversized
    monkeypatch.setattr(M, "replace_geometry", lambda orig, block: b"x" * 4096)
    monkeypatch.setattr(RE, "decimate", lambda *a, **k: pytest.fail("preserve_geometry must not decimate"))

    with pytest.raises(ValueError, match="automatic geometry reduction disabled"):
        M.swap_files(disc, Path("donor.glb"), {}, "player", tmp_path, None, preserve_geometry=True)
