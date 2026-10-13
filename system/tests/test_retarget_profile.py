"""Retarget profiles (gbox/retarget_profile.py): storage rules and the adjustment maths on synthetic skeletons."""
import math

import numpy as np
import pytest

from gbox import retarget_profile as RP
from gbox import sm64_swap as S

# A T-pose in target space (+Y up, left = +X): hip at 1.0, head joint at 1.6, ground 0 -> H = 1.6
POS = {"hip": [0, 1.0, 0], "chest": [0, 1.3, 0], "neck": [0, 1.5, 0], "head": [0, 1.6, 0],
       "l_upper": [0.2, 1.45, 0], "l_fore": [0.5, 1.45, 0], "l_hand": [0.75, 1.45, 0],
       "r_upper": [-0.2, 1.45, 0], "r_fore": [-0.5, 1.45, 0], "r_hand": [-0.75, 1.45, 0],
       "l_thigh": [0.1, 0.95, 0], "l_shin": [0.1, 0.5, 0], "l_foot": [0.1, 0.08, 0],
       "r_thigh": [-0.1, 0.95, 0], "r_shin": [-0.1, 0.5, 0], "r_foot": [-0.1, 0.08, 0]}
ORDER = list(POS)
JMAP = {r: i for i, r in enumerate(ORDER)}
T = np.array([POS[r] for r in ORDER], float)


def prim(points, joints, weights=None, normals=None):
    P = np.asarray(points, float)
    J = np.zeros((len(P), 4), int)
    W = np.zeros((len(P), 4))
    for i, js in enumerate(joints):
        js = js if isinstance(js, (list, tuple)) else [js]
        ws = weights[i] if weights is not None else [1.0]
        J[i, :len(js)] = [JMAP[j] for j in js]
        W[i, :len(ws)] = ws
    N = np.asarray(normals, float) if normals is not None else np.tile([0, 0, 1.0], (len(P), 1))
    return {"pos": P, "nrm": N, "J": J, "W": W, "tris": np.arange(len(P) // 3 * 3).reshape(-1, 3)}


def fit(points, joints, profile, **kw):
    out, rep = RP.apply_jmap([prim(points, joints, **kw)], T, JMAP, profile, 0.0)
    return out[0], rep


# ---------------------------------------------------------------- profile rules

def test_roles_match_the_retarget_role_order():
    assert RP.ROLES == S.ORDER


def test_normalize_clamps_numbers_and_drops_default_adjustments():
    p = RP.normalize({"height": 99, "ground": -3, "head": "1.5", "torso_width": float("nan"),
                      "adjust": {"l_fore": {"length": 0.01, "offset": [5, 0, 0]}, "r_fore": {}},
                      "roles": {"head": " Bip01 Head ", "l_hand": None}})
    assert p["height"] == 4.0 and p["ground"] == -0.5 and p["head"] == 1.5 and p["torso_width"] == 1.0
    assert p["adjust"]["l_fore"]["length"] == 0.25 and p["adjust"]["l_fore"]["offset"] == [1.0, 0.0, 0.0]
    assert "r_fore" not in p["adjust"]                   # an all-default adjustment is not stored
    assert p["roles"] == {"head": "Bip01 Head", "l_hand": ""}


def test_normalize_refuses_unknown_roles_and_non_objects():
    with pytest.raises(ValueError):
        RP.normalize({"roles": {"tail": "bone"}})
    with pytest.raises(ValueError):
        RP.normalize({"adjust": {"wing": {"length": 2}}})
    with pytest.raises(ValueError):
        RP.normalize([1, 2])


def test_a_slots_own_profile_replaces_the_game_wide_one():
    meta = {"retarget_profiles": {"g1": {"*": {"height": 1.2, "head": 1.1},
                                         "fighter:kasumi": {"head": 1.4, "adjust": {"l_fore": {"length": 1.5}}}}}}
    p = RP.resolve(meta, "g1", "fighter:Kasumi:all")
    assert p["height"] == 1.0 and p["head"] == 1.4 and p["adjust"]["l_fore"]["length"] == 1.5
    assert RP.resolve(meta, "g1", "fighter:Ryu")["head"] == 1.1          # game-wide only
    assert RP.resolve(meta, ["other", "g1"], "")["height"] == 1.2         # several regional ids
    assert RP.resolve(meta, "g2", "x") is None
    assert RP.resolve({"retarget_profiles": {"g1": {"kasumi": {"head": 2}}}}, "g1", "fighter:kasumi")["head"] == 2


def test_apply_to_meta_overrides_roles_and_passes_the_profile_through_rig_scale():
    meta = {"name": "Amy", "slug": "amy", "rig": {"roles": {"hip": "pelvis", "head": "neck_bone", "l_hand": "hand_L"},
                                                  "scale": {"head": 1.2}},
            "retarget_profiles": {"g": {"*": {"roles": {"head": "head_bone", "chest": "pelvis", "l_hand": ""},
                                              "head": 1.3}}}}
    out = RP.apply_to_meta(meta, "g", "player")
    roles = out["rig"]["roles"]
    assert roles["head"] == "head_bone" and roles["chest"] == "pelvis"
    assert "hip" not in roles                            # pelvis now is the chest: a bone keeps one role
    assert "l_hand" not in roles                         # "" removes a wrongly guessed role
    assert out["rig"]["scale"]["head"] == 1.2 and out["rig"]["scale"]["profile"]["head"] == 1.3
    assert out["retarget_profile_digest"] and meta["rig"]["roles"]["hip"] == "pelvis"   # the input is not mutated
    assert RP.apply_to_meta({"name": "x", "rig": {}}, "g", "player") == {"name": "x", "rig": {}}
    roles_only = RP.apply_to_meta({"rig": {"roles": {}}, "retarget_profiles": {"g": {"*": {"roles": {"hip": "b"}}}}},
                                  "g", "")
    assert "scale" not in roles_only["rig"] and roles_only["rig"]["roles"] == {"hip": "b"}


def test_digest_tracks_what_changes_the_fit():
    assert RP.digest(None) == "" and RP.digest({}) == ""
    a, b = RP.digest({"head": 1.2}), RP.digest({"head": 1.3})
    assert a and b and a != b
    assert RP.digest({"head": 1.2, "updated": 5, "by": "x"}) == a


# ---------------------------------------------------------------- the maths

def test_no_profile_returns_the_prims_untouched():
    prims = [prim([[0, 1.0, 0]], ["hip"])]
    out, rep = RP.apply_jmap(prims, T, JMAP, None)
    assert out is prims and rep == {"applied": False}
    out, rep = RP.apply_jmap(prims, T, JMAP, {"height": 1.0, "roles": {"hip": "b"}})
    assert out is prims and rep["applied"] is False


def test_head_size_scales_about_the_head_joint_only():
    p, rep = fit([[0, 1.8, 0.1], [0, 1.0, 0.05]], ["head", "hip"], {"head": 1.5})
    np.testing.assert_allclose(p["pos"][0], [0, 1.6 + 0.3, 0.15])
    np.testing.assert_allclose(p["pos"][1], [0, 1.0, 0.05])
    assert rep["applied"] and rep["head"] == 1.5 and rep["max_shift"] == pytest.approx(0.1 / 1.6, abs=1e-4)


def test_limb_length_stretches_along_the_bone_and_girth_across_it():
    # forearm: elbow (0.5,1.45) -> wrist (0.75,1.45), bone axis +X
    p, _ = fit([[0.6, 1.5, 0.02]], ["l_fore"], {"adjust": {"l_fore": {"length": 2.0, "girth": 0.5}}})
    np.testing.assert_allclose(p["pos"][0], [0.5 + 0.1 * 2, 1.45 + 0.05 * 0.5, 0.02 * 0.5])
    p, _ = fit([[0.1, 0.7, 0]], ["l_shin"], {"leg_length": 1.5})      # shin axis -Y from knee (0.1,0.5)
    np.testing.assert_allclose(p["pos"][0], [0.1, 0.5 + 0.2 * 1.5, 0])
    p, _ = fit([[0.3, 1.45, 0]], ["l_upper"], {"arm_length": 1.5, "adjust": {"l_upper": {"length": 2}}})
    np.testing.assert_allclose(p["pos"][0], [0.2 + 0.1 * 3, 1.45, 0])  # global arm length x the role's own


def test_height_and_ground_move_the_figure_about_the_ground_under_the_hip():
    p, _ = fit([[0.3, 1.2, 0.1]], ["chest"], {"height": 1.5})
    np.testing.assert_allclose(p["pos"][0], [0.45, 1.8, 0.15])
    p, _ = fit([[0.3, 1.2, 0.1]], ["chest"], {"ground": 0.1})
    np.testing.assert_allclose(p["pos"][0], [0.3, 1.2 + 0.16, 0.1])  # 0.1 of H = 1.6


def test_torso_width_widens_the_torso_and_carries_the_limbs_rigidly():
    p, _ = fit([[0.15, 1.3, 0], [0.6, 1.5, 0], [0.7, 1.45, 0]], ["chest", "l_fore", "l_hand"], {"torso_width": 1.5})
    np.testing.assert_allclose(p["pos"][0], [0.225, 1.3, 0])
    np.testing.assert_allclose(p["pos"][1], [0.6 + 0.5 * 0.2, 1.5, 0])  # the shoulder's x shift, no scaling
    np.testing.assert_allclose(p["pos"][2], [0.7 + 0.5 * 0.2, 1.45, 0])


def test_offset_and_rotation_are_about_the_roles_own_joint():
    p, _ = fit([[0, 1.8, 0]], ["head"], {"adjust": {"head": {"offset": [0, 0.1, 0]}}})
    np.testing.assert_allclose(p["pos"][0], [0, 1.8 + 0.16, 0])
    p, _ = fit([[0, 1.8, 0]], ["head"], {"adjust": {"head": {"rotate": [0, 0, 90]}}})
    np.testing.assert_allclose(p["pos"][0], [-0.2, 1.6, 0], atol=1e-12)


def test_weighted_vertices_blend_their_roles_transforms():
    p, _ = fit([[0, 1.55, 0]], [["head", "neck"]], {"head": 2.0}, weights=[[0.5, 0.5]])
    head_only = [0, 1.6 + (1.55 - 1.6) * 2, 0]
    np.testing.assert_allclose(p["pos"][0], (np.array(head_only) + [0, 1.55, 0]) / 2)


def test_normals_follow_the_inverse_transpose_and_stay_unit():
    # a forearm "tube" normal pointing up stays perpendicular to the bone after a non-uniform girth/length change
    p, _ = fit([[0.6, 1.5, 0]], ["l_fore"], {"adjust": {"l_fore": {"length": 3.0, "girth": 0.4}}},
               normals=[[0.6, 0.8, 0]])
    n = p["nrm"][0]
    assert math.isclose(float(np.linalg.norm(n)), 1.0, rel_tol=1e-9)
    tangent = np.array([0.8, -0.6, 0])                    # a surface tangent of the original normal...
    A = np.diag([3.0, 0.4, 0.4])                          # ...stays perpendicular to the new normal once transformed
    assert abs(float(n @ (A @ tangent))) < 1e-9
    np.testing.assert_allclose(n, np.array([0.6 / 3, 0.8 / 0.4, 0]) / np.linalg.norm([0.2, 2.0, 0]))


def test_unmapped_joints_take_the_torso_and_global_transform():
    prims = [{"pos": np.array([[0.2, 1.1, 0.0]]), "nrm": np.array([[0, 0, 1.0]]),
              "J": np.array([[40, 0, 0, 0]]), "W": np.array([[1.0, 0, 0, 0]])}]
    out, _ = RP.apply_jmap(prims, T, JMAP, {"torso_width": 2.0, "height": 1.0, "head": 1.0})
    np.testing.assert_allclose(out[0]["pos"][0], [0.4, 1.1, 0])


def test_single_influence_prims_without_weights_use_their_joint():
    prims = [{"pos": np.array([[0, 1.8, 0.0]]), "nrm": np.array([[0, 1.0, 0]]), "J": np.array([JMAP["head"]])}]
    out, _ = RP.apply_jmap(prims, T, JMAP, {"head": 2})
    np.testing.assert_allclose(out[0]["pos"][0], [0, 2.0, 0])


# ---------------------------------------------------------------- the writers' retargets honour it

def _rig_and_target():
    from tests.test_doa2_weighted_retarget import rig, target
    return rig(), target()


def test_sm64_retarget_applies_the_profile_from_rig_scale():
    rig, tgt = _rig_and_target()
    base, _ = S.retarget(rig, tgt, None, tgt["jmap"])
    big, rep = S.retarget(rig, tgt, {"profile": {"head": 1.5}}, tgt["jmap"])
    head = tgt["T"][tgt["jmap"]["head"]]
    sel = base[0]["J"][:, 0] == tgt["jmap"]["head"]
    assert sel.any() and rep["profile"]["applied"]
    np.testing.assert_allclose(big[0]["pos"][sel], head + (base[0]["pos"][sel] - head) * 1.5, atol=1e-9)
    np.testing.assert_allclose(big[0]["pos"][~sel], base[0]["pos"][~sel], atol=1e-9)


def test_doa2_weighted_retarget_applies_the_profile_per_influence():
    from gbox.doa2_weighted_retarget import retarget
    rig, tgt = _rig_and_target()
    base, _ = retarget(rig, tgt, None, tgt["jmap"])
    tall, rep = retarget(rig, tgt, {"profile": {"height": 1.25}}, tgt["jmap"])
    assert rep["profile"]["applied"] and rep["profile"]["height"] == 1.25
    hip = tgt["T"][tgt["jmap"]["hip"]]
    ground = np.array([hip[0], tgt["ground"], hip[2]])
    np.testing.assert_allclose(tall[0]["pos"], ground + (base[0]["pos"] - ground) * 1.25, atol=1e-9)
    np.testing.assert_array_equal(tall[0]["J"], base[0]["J"])            # the weights are untouched
    np.testing.assert_array_equal(tall[0]["W"], base[0]["W"])


def test_crazy_taxi_part_profile_matrix_scales_the_head_part_only():
    from gbox import crazy_taxi_swap as CTS
    cloud = np.random.default_rng(1).normal(size=(50, 3)) * [1, 3, 1]
    np.testing.assert_allclose(CTS.profile_matrix("atama", cloud, {"head": 1.4}), np.eye(3) * 1.4)
    np.testing.assert_allclose(CTS.profile_matrix("mune", cloud, {"head": 1.4}), np.eye(3))
    np.testing.assert_allclose(CTS.profile_matrix("atama", cloud, None), np.eye(3))
    M = CTS.profile_matrix("ude_l", cloud, {"arm_length": 2})
    d = np.linalg.svd(cloud - cloud.mean(0))[2][0]
    np.testing.assert_allclose(M @ d, 2 * d, atol=1e-9)                  # the part's long axis
