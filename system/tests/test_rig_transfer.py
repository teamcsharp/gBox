from gbox import rig_transfer as rt

CUBE_V = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
# outward CCW faces for the cube, built from indices
def _faces(flip=False):
    idx = {v: i for i, v in enumerate(CUBE_V)}
    quads = [((1,-1,-1),(1,1,-1),(1,1,1),(1,-1,1)), ((-1,-1,-1),(-1,-1,1),(-1,1,1),(-1,1,-1)),
             ((-1,1,-1),(-1,1,1),(1,1,1),(1,1,-1)), ((-1,-1,-1),(1,-1,-1),(1,-1,1),(-1,-1,1)),
             ((-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)), ((-1,-1,-1),(-1,1,-1),(1,1,-1),(1,-1,-1))]
    out = []
    for q in quads:
        i = [idx[p] for p in q]
        t = [(i[0], i[1], i[2]), (i[0], i[2], i[3])]
        out += [tuple(reversed(f)) if flip else f for f in t]
    return out

CUBE_F = _faces()

def test_joint_mapping_across_naming_schemes():
    donor = ["Hips", "Spine", "Neck", "Head", "LeftUpperArm", "LeftForeArm", "LeftHand", "RightHand", "LeftFoot"]
    target = ["b000_pelvis", "b001_spine", "b002_neck", "b003_head", "l_upperarm", "l_forearm", "l_hand", "r_hand", "l_foot"]
    m = rt.map_donor_to_target(donor, target)
    assert m["Head"] == "b003_head" and m["LeftHand"] == "l_hand" and m["RightHand"] == "r_hand"
    assert m["Hips"] == "b000_pelvis"

def test_normals_check():
    assert not rt.check_normals(CUBE_V, _faces())["flag"]
    assert rt.check_normals(CUBE_V, _faces(flip=True))["flag"]

def test_head_seat_and_stretch():
    ok = {"neck": (0, 0, 150), "head": (0, 0, 175), "l_foot": (0, 0, 0), "l_shoulder": (10, 0, 145)}
    assert not rt.check_head_seat(ok)["flag"]
    sunk = dict(ok, head=(0, 0, 140))
    assert rt.check_head_seat(sunk)["flag"]
    assert rt.check_head_seat({})["flag"] is None
    assert rt.check_stretch({"height": 1.0, "l_arm": 1.6})["flag"]
    assert not rt.check_stretch({"height": 1.0, "l_arm": 1.1})["flag"]

def test_proportional_fit():
    d = {"neck": (0, 0, 100), "head": (0, 0, 120), "l_foot": (0, 0, 0), "pelvis": (0, 0, 50)}
    t = {k: tuple(c * 2 for c in v) for k, v in d.items()}
    assert abs(rt.proportional_fit(d, t)["height"] - 2.0) < 1e-9

def test_critique_parse():
    assert [r["action"] for r in rt.parse_critique("these normals look inverted")] == ["flip_normals"]
    assert rt.parse_critique("this model has its head shoved down its shoulders")[0]["action"] == "raise_head"
    r = rt.parse_critique("the legs look stretched and he's floating")
    assert {x["action"] for x in r} == {"shrink_limb", "lower_model"}
    assert [x for x in r if x["action"] == "shrink_limb"][0]["part"] == ["l_leg", "r_leg"]
    assert rt.parse_critique("nice run animation") == []

def test_fixes_persist_and_reuse(tmp_path):
    res = rt.critique_to_fixes(tmp_path, "re4_leon", "re5_chris", "head shoved down and normals inverted")
    assert res["rebuild"] and (tmp_path / "mercs/rig_fixes/re4_leon__re5_chris.json").exists()
    f = rt.load_fixes(tmp_path, "re4_leon", "re5_chris")
    assert f["part_flips"] == ["*"] and f["joint_offsets"]["head"][2] == rt.HEAD_STEP
    rt.critique_to_fixes(tmp_path, "re4_leon", "re5_chris", "normals inverted")
    assert rt.load_fixes(tmp_path, "re4_leon", "re5_chris")["part_flips"] == []
    pos = rt.apply_fixes({"head": (0, 0, 1.7)}, f)
    assert abs(pos["head"][2] - 1.7 - rt.HEAD_STEP) < 1e-9
    assert rt.critique_to_fixes(tmp_path, "a", "b", "good")["rebuild"] is False

def test_limb_scale_applies():
    f = rt.empty_fixes("d", "t")
    rt.apply_correction(f, {"action": "shrink_limb", "part": ["l_arm"]})
    p = rt.apply_fixes({"l_upper_arm": (0, 0, 0), "l_hand": (10, 0, 0)}, f)
    assert abs(p["l_hand"][0] - 9.0) < 1e-9


def test_coach_reply_uses_session_donor(tmp_path):
    sess = {"game_id": "re4", "build_manifest": {"donor": "re5_chris", "slot": "leon"}}
    r = rt.coach_reply(tmp_path, sess, "his head is shoved down and the arms are stretched")
    assert (r["donor"], r["target"]) == ("re5_chris", "leon") and r["rebuild"]
    fx = rt.load_fixes(tmp_path, "re5_chris", "leon")
    assert fx["joint_offsets"]["head"][2] > 0 and fx["scales"]["l_arm"] < 1
    assert "re5_chris -> leon" in r["reply"]
    assert rt.coach_reply(tmp_path, sess, "nice dodge") is None
    assert rt.coach_reply(tmp_path, {"game_id": "re4"}, "normals inverted") is None


def test_all_scale_is_applied():
    f = rt.empty_fixes("d", "t")
    rt.apply_correction(f, {"action": "scale_down"})
    p = rt.apply_fixes({"pelvis": (0, 0, 10), "head": (0, 0, 20)}, f)
    assert abs(p["head"][2] - 19.0) < 1e-9 and p["pelvis"][2] == 10


def test_retarget_entry_point_applies_stored_fixes(tmp_path):
    donor = {"Hips": (0, 0, 50), "Neck": (0, 0, 100), "Head": (0, 0, 105), "LeftFoot": (0, 0, 0)}
    target = {"pelvis": (0, 0, 100), "neck": (0, 0, 200), "head": (0, 0, 230), "l_foot": (0, 0, 0)}
    before = rt.retarget(tmp_path, "dn", "tg", donor, target, faces=CUBE_F, verts=CUBE_V)
    assert abs(before["fit"]["height"] - 230 / 105) < 1e-9
    assert "head_seat" in before["flags"] or before["checks"]["head_seat"]["flag"] is not None
    rt.critique_to_fixes(tmp_path, "dn", "tg", "normals inverted and head shoved down")
    after = rt.retarget(tmp_path, "dn", "tg", donor, target, faces=CUBE_F, verts=CUBE_V)
    assert after["fixes_applied"]
    assert after["positions"]["head"][2] > before["positions"]["head"][2]
    assert after["faces"][0] == tuple(reversed(before["faces"][0]))
