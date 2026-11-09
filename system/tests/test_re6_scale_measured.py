"""Measured scale regression: the real RE6 Xbox 360 disc copy and the measured SA2 Sonic donor.

Skips where the operator's extracted disc or the mirrored donor is absent. This is the check behind the numbers in
docs/re6-model-replacement.md: the segment fit stretches the donor (arm/height 0.25) while the source-proportion fit
keeps it (0.1615) and lands the requested 180 cm inside the native quantisation box.
"""
from pathlib import Path

import numpy as np
import pytest

from gbox import characters as C, re6, re6_models as M

BASE = Path(r"D:\gBox\runtime\re6\base")
SONIC = Path(r"D:\gBox\cache\characters_mirror\sonic\sa2_sonic_0.glb")
ROLES = {"hip": "node002", "chest": "node033", "head": "node044",
         "l_upper": "node037", "l_fore": "node038", "l_hand": "node039",
         "r_upper": "node056", "r_fore": "node057", "r_hand": "node058",
         "l_thigh": "node017", "l_shin": "node019", "l_foot": "node023",
         "r_thigh": "node007", "r_shin": "node009", "r_foot": "node013"}

pytestmark = pytest.mark.skipif(not (BASE.is_dir() and SONIC.is_file()),
                                reason="needs the operator's extracted RE6 disc and the mirrored Sonic GLB")


def written_body(files: dict) -> M.Mod:
    path = next(k for k in files if k.endswith("uPl00LeonUsa.arc"))
    arc = re6.Arc(data=files[path])
    return M.Mod(arc.get(arc.find(sorted({e["name"] for e in arc.entries if e["ext"] == "mod"})[0], "mod")))


def decoded(mod: M.Mod) -> np.ndarray:
    return np.concatenate([g["pos"] for g in (mod.decode(p) for p in mod.prims) if g is not None and len(g["pos"])])


def arm_ratio(rig: dict) -> float:
    joints = np.asarray(rig["joints"], float)
    height = float(np.ptp(np.concatenate([p["pos"][:, 1] for p in rig["prims"]])))
    return float(np.linalg.norm(joints[rig["roles"]["l_hand"]] - joints[rig["roles"]["l_upper"]]) / height)


def test_the_measured_donor_and_slot_round_trip_through_both_fits():
    rig = C.rig_from_gltf(SONIC, ROLES)
    source_ratio = arm_ratio(rig)
    assert source_ratio == pytest.approx(0.1615, abs=5e-4)

    segment = M.build_swap(BASE, SONIC, ROLES, "leon", "Usa", "scale-test", pose_mode="segment")
    exact = M.build_swap(BASE, SONIC, ROLES, "leon", "Usa", "scale-test",
                         scale={"pose": "source_proportions", "height": 180.0})
    fit = exact["fit"]
    assert fit["pose_mode"] == "source_proportions"
    assert fit["fitted_height"] == pytest.approx(180.0, abs=0.01)
    assert fit["uniform_scale"] > 0 and not fit["height_clamped"]
    assert fit["proportion_error"] < 1e-4
    assert fit["unmapped_vertices"] == 0

    exact_mod = written_body(exact["files"])
    P = decoded(exact_mod)
    lo, hi = P.min(0), P.max(0)
    assert hi[1] - lo[1] == pytest.approx(180.0, abs=0.05)
    q = (np.c_[P, np.ones(len(P))] @ np.linalg.inv(exact_mod.dequant()))[:, :3]
    assert q.min() >= 0 and q.max() <= 1

    roles_t = M.role_indices(exact_mod)
    W = exact_mod.world()
    target_ratio = float(np.linalg.norm(W[roles_t["l_hand"]][3, :3] - W[roles_t["l_upper"]][3, :3])
                         / (hi[1] - lo[1]))
    assert target_ratio == pytest.approx(source_ratio, rel=2e-3)

    segment_mod = written_body(segment["files"])
    S = decoded(segment_mod)
    segment_height = float(np.ptp(S[:, 1]))
    assert segment_height > 195.0                       # the stretched fit the source-proportion path replaces
