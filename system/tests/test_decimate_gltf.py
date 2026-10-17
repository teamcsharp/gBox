"""#1292: Blender decimation of layered character meshes and the SM64 writer's fit loop."""
import subprocess
from pathlib import Path

import numpy as np
import pytest

from gbox import re4gc_enemies as R
from gbox import sm64_swap as S


def _blender() -> str | None:
    b = R.blender_exe()
    if not b or not Path(b).exists():
        return None
    try:
        return b if subprocess.run([b, "--version"], capture_output=True, timeout=60).returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _torus(rows: int, cols: int, flip: bool, color) -> dict:
    """A closed torus with the vertex copies glTF makes at a UV seam (last row/column repeat the first)."""
    u, v = np.meshgrid(np.linspace(0, 2 * np.pi, rows + 1), np.linspace(0, 2 * np.pi, cols + 1), indexing="ij")
    ring = 1.0 + 0.35 * np.cos(v)
    pos = np.stack([ring * np.cos(u), 0.35 * np.sin(v) + 1.0, ring * np.sin(u)], -1).reshape(-1, 3)
    cen = np.stack([np.cos(u), np.ones_like(u), np.sin(u)], -1).reshape(-1, 3)
    nrm = (pos - cen) / np.linalg.norm(pos - cen, axis=1, keepdims=True)
    uv = np.stack([u / (2 * np.pi), v / (2 * np.pi)], -1).reshape(-1, 2)
    idx = np.arange((rows + 1) * (cols + 1)).reshape(rows + 1, cols + 1)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    tris = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)])
    if flip:                                              # the inner face of double-sided cloth
        tris, nrm = tris[:, ::-1].copy(), -nrm
    n = len(pos)
    return {"pos": pos, "nrm": nrm, "uv": uv, "tris": tris, "J": np.tile([1, 0, 0, 0], (n, 1)),
            "W": np.tile([1.0, 0, 0, 0], (n, 1)), "tex": None, "color": color, "wrap": (10497, 10497)}


def test_decimate_reaches_target_when_primitives_share_positions(tmp_path):
    """Two coincident shells in two primitives (a layered part): welding across them made every edge 4-faced and
    the collapse never moved (RE6 Leon stopped at 4449 of 17162 triangles whatever the target)."""
    blender = _blender()
    if not blender:
        pytest.skip("no runnable Blender on this node")
    from gbox.melee_models import write_gltf
    joints = [{"parent": -1, "world": np.eye(4)}, {"parent": 0, "world": np.eye(4)}]
    prims = [_torus(24, 32, False, (200, 40, 40, 255)), _torus(24, 32, True, (40, 40, 200, 255))]
    src = write_gltf(tmp_path / "layered.gltf", joints, prims, 1.0, "layered", ["j00", "j01"])
    before = sum(len(p["tris"]) for p in prims)
    out = R.decimate(src, tmp_path / "dec.glb", 400.0, blender)
    got = S.read_rigged(out)                              # skin kept: every vertex still names its Mario joint
    after = sum(len(p["tris"]) for p in got)
    assert before == 3072
    assert 0 < after <= 400 * 1.15, after
    assert {int(j) for p in got for j in p["jid"]} == {1}


def test_sm64_build_reports_a_stalled_decimation(monkeypatch, tmp_path):
    """A decimation that ignores lower targets used to run every target and end on '4427 triangles need 207072
    bytes even untextured'; the loop now stops at the second identical result and says why."""
    monkeypatch.setattr(S, "check_rom", lambda rom: None)
    monkeypatch.setattr(S, "mario_target", lambda rom: {})
    monkeypatch.setattr(S, "load_rig", lambda *a, **k: {})
    monkeypatch.setattr(S, "retarget", lambda rig, tgt, scale=None: ([{"tris": np.zeros((17162, 3), int)}], {}))
    monkeypatch.setattr(S, "write_rigged", lambda prims, tgt, path, name: Path(path))
    asked = []
    monkeypatch.setattr(R, "decimate", lambda src, dst, amount, blender=None: asked.append(amount) or Path(dst))
    monkeypatch.setattr(S, "read_rigged", lambda p: [{"tris": np.zeros((4427, 3), int)}])
    monkeypatch.setattr(S, "to_writer", lambda prims, tgt: ({0: [None] * 4427}, [], []))

    def nofit(parts, mats, uses):
        raise ValueError("4427 triangles need 207072 bytes even untextured (budget 118048)")
    monkeypatch.setattr(S, "fit_budget", nofit)
    with pytest.raises(ValueError, match="decimation stopped at 4427 triangles"):
        S.build(b"", tmp_path / "m.gltf", {}, tmp_path / "w", "Leon", blender="/usr/bin/blender")
    assert asked == [1600.0, 1200.0]


def test_sm64_build_keeps_trying_lower_targets_while_they_help(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "check_rom", lambda rom: None)
    monkeypatch.setattr(S, "mario_target", lambda rom: {})
    monkeypatch.setattr(S, "load_rig", lambda *a, **k: {})
    monkeypatch.setattr(S, "retarget", lambda rig, tgt, scale=None: ([{"tris": np.zeros((17162, 3), int)}], {}))
    monkeypatch.setattr(S, "write_rigged", lambda prims, tgt, path, name: Path(path))
    monkeypatch.setattr(R, "decimate", lambda src, dst, amount, blender=None: Path(f"{int(amount)}"))
    monkeypatch.setattr(S, "read_rigged", lambda p: [{"tris": np.zeros((int(p.name), 3), int)}])
    monkeypatch.setattr(S, "to_writer", lambda prims, tgt: ({0: [None] * len(prims[0]["tris"])}, [], []))

    def fit(parts, mats, uses):
        if len(parts[0]) > 900:
            raise ValueError("too big")
        return [], {"bytes": 1, "budget": 2}
    monkeypatch.setattr(S, "fit_budget", fit)
    monkeypatch.setattr(S.W, "inject", lambda rom, parts, fitted: b"rom")
    b = S.build(b"", tmp_path / "m.gltf", {}, tmp_path / "w", "Leon", blender="/usr/bin/blender")
    assert b["report"]["triangles"] == 880
