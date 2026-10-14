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


def test_mesh_foot_placement_uses_weighted_foot_vertices_and_keeps_ground_offset():
    points=[[.1,-.15,0],[-.1,-.1,0],[0,1.6,0]]
    out,report=fit(points,['l_foot','r_foot','head'],{'plant_feet':True,'ground':.02})
    expected=.02*RP.frame(POS,0)['H']
    assert out['pos'][:2,1].min()==pytest.approx(expected)
    assert report['feet']['applied'] and np.allclose(np.diff(out['pos'],axis=0),np.diff(points,axis=0))


@pytest.mark.parametrize('lying',[False,True])
def test_explicit_shoe_planes_split_overassigned_feet_and_recover_shoe_vertices(lying):
    rig=donor_rig(weighted=True)
    p=rig['prims'][0]
    # Height remains two units; an overassigned foot extends up the leg, while a shoe point was called shin.
    p['pos'][:3]=[[.1,.1,0],[.1,.6,0],[.1,.2,0]]
    p['owner'][:3]=[JMAP['l_foot'],JMAP['l_foot'],JMAP['l_shin']]
    p['J'][:3,0]=p['owner'][:3]
    if lying:
        rotation=np.array([[-1.,0,0],[0,0,-1],[0,-1,0]])
        rig['joints']=rig['joints']@rotation.T
        p['pos']=p['pos']@rotation.T;p['nrm']=p['nrm']@rotation.T
    old=p['owner'].copy()
    result,report=RP.move_joints(rig,{'shoe_tops':{'l':.15}})
    assert result['prims'][0]['owner'][:3].tolist()==[JMAP['l_foot'],JMAP['l_shin'],JMAP['l_foot']]
    assert result['prims'][0]['J'][:3,0].tolist()==result['prims'][0]['owner'][:3].tolist()
    assert report['vertices_reassigned']==2
    np.testing.assert_array_equal(p['owner'],old)
    np.testing.assert_allclose(result['joints'],rig['joints'])
    assert RP.digest({'shoe_tops':{'l':.15}})!=RP.digest({'shoe_tops':{'l':.2}})
    assert RP.profile_of({'profile':{'preserve_geometry':True}})['preserve_geometry']


def test_shoe_planes_require_distinct_shin_and_foot_roles():
    rig=donor_rig();del rig['roles']['l_foot']
    with pytest.raises(ValueError,match='distinct l shin and foot'):
        RP.move_joints(rig,{'shoe_tops':{'l':.15}})


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


# ---------------------------------------------------------------- joint moves (the Goals view's circles)

PARENT = {"hip": None, "chest": "hip", "neck": "chest", "head": "neck", "l_upper": "chest", "l_fore": "l_upper",
          "l_hand": "l_fore", "r_upper": "chest", "r_fore": "r_upper", "r_hand": "r_fore", "l_thigh": "hip",
          "l_shin": "l_thigh", "l_foot": "l_shin", "r_thigh": "hip", "r_shin": "r_thigh", "r_foot": "r_shin"}
ARM_X = [0.25, 0.3, 0.35, 0.4, 0.45, 0.52, 0.55, 0.58, 0.6, 0.65, 0.7, 0.72, 0.8, 0.85, 0.9]


def _arm_owner(x):
    return "l_upper" if x < 0.5 else "l_fore" if x < 0.75 else "l_hand"


def donor_rig(weighted=False):
    """A T-posed donor (the POS skeleton) whose left arm is a row of vertices owned by upper arm / forearm / hand by
    where its rig put the elbow (x 0.5) and the wrist (x 0.75); the body spans y 0..2 (donor height 2)."""
    pts = [[x, 1.45, 0.0] for x in ARM_X] + [[0, 1.0, 0], [0, 0.0, 0.05], [0, 2.0, 0]]
    own = [_arm_owner(x) for x in ARM_X] + ["hip", "hip", "head"]
    P = np.asarray(pts, float)
    prim_ = {"pos": P, "nrm": np.tile([0, 0, 1.0], (len(P), 1)), "uv": np.zeros((len(P), 2)),
             "tris": np.arange(len(P)).reshape(-1, 3), "owner": np.array([JMAP[r] for r in own]),
             "tex": None, "color": (255, 255, 255, 255)}
    if weighted:
        J, W = np.zeros((len(P), 4), int), np.zeros((len(P), 4))
        J[:, 0], W[:, 0] = prim_["owner"], 0.7
        J[:, 1], W[:, 1] = JMAP["chest"], 0.3
        prim_ |= {"J": J, "W": W}
    return {"joints": T.copy(), "parent": [-1 if PARENT[r] is None else JMAP[PARENT[r]] for r in ORDER],
            "roles": dict(JMAP), "names": list(ORDER), "prims": [prim_], "source": "/lib/amy/amy.glb"}


def bent_target():
    """The same skeleton with the left forearm hanging down from the elbow (the wrist under it)."""
    Tb = T.copy()
    Tb[JMAP["l_hand"]] = [0.5, 1.2, 0]
    return {"T": Tb, "ground": 0.0, "head_h": 0.4}


def test_normalize_keeps_joint_moves_clamped_and_drops_zero_ones():
    p = RP.normalize({"joints": {"l_fore": [0.01, -2, "x"], "r_shin": [0, 0, 0], "head": [0, 0.05, 0]}})
    assert p["joints"] == {"l_fore": [0.01, -0.25, 0.0], "head": [0.0, 0.05, 0.0]}
    assert not RP.is_identity({"joints": {"l_fore": [0, -0.02, 0]}})
    assert RP.is_identity({"joints": {"l_fore": [0, 0, 0]}})
    assert RP.digest({"joints": {"l_fore": [0, -0.02, 0]}}) != RP.digest({"joints": {"l_fore": [0, -0.03, 0]}})
    with pytest.raises(ValueError):
        RP.normalize({"joints": {"tail": [0, 0.1, 0]}})
    with pytest.raises(ValueError):
        RP.normalize({"joints": [0, 0.1, 0]})
    out = RP.apply_to_meta({"rig": {"roles": {"hip": "b"}}, "retarget_profiles": {"g": {"*": {
        "joints": {"l_fore": [0, -0.02, 0]}}}}}, "g", "player")
    assert out["rig"]["scale"]["profile"]["joints"] == {"l_fore": [0.0, -0.02, 0.0]}  # joint moves reach the writers


def test_move_joints_moves_the_pivot_and_reowns_the_vertices_it_swept():
    rig = donor_rig()
    same, rep = RP.move_joints(rig, {"head": 1.2})
    assert same is rig and rep == {"moved": []}                # no joint moves: the very same rig
    moved, rep = RP.move_joints(rig, {"joints": {"l_fore": [0.05, 0, 0]}})       # 0.05 x donor height 2 = 0.1
    assert rep["moved"] == ["l_fore"] and rep["donor_height"] == 2.0
    np.testing.assert_allclose(moved["joints"][JMAP["l_fore"]], [0.6, 1.45, 0])
    np.testing.assert_allclose(moved["joints"][JMAP["l_hand"]], T[JMAP["l_hand"]])   # descendants stay
    names = {v: k for k, v in JMAP.items()}
    owners = [names[j] for j in moved["prims"][0]["owner"][:len(ARM_X)]]
    expect = ["l_upper" if x <= 0.6 else "l_fore" if x < 0.75 else "l_hand" for x in ARM_X]
    assert owners == expect                                    # on the new elbow plane: the parent keeps it
    assert rep["vertices_reassigned"] == 4                     # 0.52, 0.55, 0.58, 0.6 crossed the elbow
    assert rig["joints"][JMAP["l_fore"]][0] == 0.5 and rig["prims"][0]["owner"][5] == JMAP["l_fore"]  # not mutated
    back, rep = RP.move_joints(rig, {"joints": {"l_hand": [-0.05, 0, 0]}})       # the wrist moves up the arm
    owners = [names[j] for j in back["prims"][0]["owner"][:len(ARM_X)]]
    assert owners == [_arm_owner(x) if x <= 0.65 or x >= 0.75 else "l_hand" for x in ARM_X]


def test_move_joints_follows_the_donors_own_axes():
    rig = donor_rig()                                          # the same donor lying on its back: up = -Z
    R = np.array([[1.0, 0, 0], [0, 0, 1], [0, -1, 0]])         # editor (x, y, z) -> rig (x, z, -y)
    rig = {**rig, "joints": rig["joints"] @ R.T, "prims": [{**rig["prims"][0], "pos": rig["prims"][0]["pos"] @ R.T}]}
    moved, rep = RP.move_joints(rig, {"joints": {"head": [0, 0.05, 0]}})          # up in the editor frame
    np.testing.assert_allclose(moved["joints"][JMAP["head"]] - rig["joints"][JMAP["head"]], R @ [0, 0.1, 0],
                               atol=1e-12)


def test_weighted_prims_move_the_swept_influences_to_the_new_segment():
    rig = donor_rig(weighted=True)
    moved, _ = RP.move_joints(rig, {"joints": {"l_fore": [0.05, 0, 0]}})
    J = moved["prims"][0]["J"]
    i = ARM_X.index(0.55)
    assert J[i, 0] == JMAP["l_upper"] and J[i, 1] == JMAP["chest"]                # the chest share stays
    assert J[ARM_X.index(0.7), 0] == JMAP["l_fore"]
    np.testing.assert_array_equal(moved["prims"][0]["W"], rig["prims"][0]["W"])   # weights untouched


def test_a_moved_elbow_moves_where_the_shared_retarget_bends_the_arm():
    rig, tgt = donor_rig(), bent_target()
    i = ARM_X.index(0.55)                                      # between the rig's elbow (0.5) and the operator's (0.6)
    base, _ = S.retarget(rig, tgt, None, JMAP)
    np.testing.assert_allclose(base[0]["pos"][i], [0.5, 1.40, 0], atol=1e-9)      # bent down with the forearm
    prof = {"joints": {"l_fore": [0.05, 0, 0]}}
    out, rep = S.retarget(rig, tgt, {"profile": prof}, JMAP)
    assert rep["joints_moved"]["moved"] == ["l_fore"]
    np.testing.assert_allclose(out[0]["pos"][i][1], 1.45, atol=1e-9)              # now on the straight upper arm
    np.testing.assert_allclose(out[0]["pos"][ARM_X.index(0.6)], [0.5, 1.45, 0], atol=1e-9)   # new elbow -> target's
    assert out[0]["J"][i, 0] == JMAP["l_upper"] and base[0]["J"][i, 0] == JMAP["l_fore"]      # the weights follow
    np.testing.assert_allclose(out[0]["pos"][len(ARM_X):], base[0]["pos"][len(ARM_X):], atol=1e-9)  # body as it was


def test_the_weighted_and_re4_retargets_honour_joint_moves_too():
    from gbox.doa2_weighted_retarget import retarget
    rig, tgt = donor_rig(weighted=True), bent_target()
    i = ARM_X.index(0.55)
    base, _ = retarget(rig, tgt, None, JMAP)
    out, rep = retarget(rig, tgt, {"profile": {"joints": {"l_fore": [0.05, 0, 0]}}}, JMAP)
    assert rep["joints_moved"]["moved"] == ["l_fore"]
    assert out[0]["pos"][i][1] > base[0]["pos"][i][1] + 0.02   # the upper-arm share no longer hangs with the forearm
    from gbox import re4gc_enemies as E
    assert "move_joints" in E.retarget.__code__.co_names        # RE4's fit (and its duck-typed users) start from it


def test_the_retarget_stage_carries_the_goals_the_fit_aimed_at(tmp_path):
    from gbox import fit_events as FE
    rig, tgt = donor_rig(), bent_target()
    lines = []
    with FE.job(lambda pct, msg: lines.append(msg), tmp_path):
        FE.target("0123456789abcdef")
        FE.model("fighter:KAS", "Amy → Kasumi", "amy")
        S.retarget(rig, tgt, {"profile": {"joints": {"l_fore": [0.05, 0, 0]}}}, JMAP)
    ev = next(e for e in (FE.split(m)[1] for m in lines) if e and e.get("stage") == "retarget")
    g = ev["goals"]
    assert g["target"]["l_hand"] == [0.5, 1.2, 0.0] and g["target_ground"] == 0.0
    assert g["donor"]["l_fore"] == [0.6, 1.45, 0.0]           # the donor's moved elbow, upright
    assert ev["data"]["joints_moved"] == 1
    assert RP.goals({"hip": [0, 1, 0], "tail": [0, 0, 0]}, {"hip": np.array([0, 2.0, 0])}) == {
        "donor": {"hip": [0.0, 1.0, 0.0]}, "target": {"hip": [0.0, 2.0, 0.0]}}
