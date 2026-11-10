"""The RE4 Switch donor fit and its gate on synthetic skeletons (no game data, no donor file).

One test per cause measured on the 2026-11-10 pools (re4_switch_models, the comment above `proportional_fit`):
absolute cross-section scales, an uncapped hip segment, off-role skin carried by the stretch, the floor taken from the
lowest vertex, the rotation (not a cause), non-humanoid donors; then the gate's thresholds, the reject list, and the
pools drawing only passing donors.
"""
import json

import numpy as np
import pytest

from gbox import re4_switch_assets as A
from gbox import re4_switch_enemies as E
from gbox import re4_switch_models as M
from gbox import re5_donor_pool
from tests.test_re4_switch_assets import gradient, make_bin, make_pack, material
from tests.test_re4_switch_enemies import PACK_ID as GANADO_ID, ganado_pack
from tests.test_re4_switch_models import PACK_ID, SKELETON, player_pack

ROLES = M.ROLES
NODE = {role: 10 + i for i, role in enumerate(ROLES)}
PARENT = {"chest": "hip", "head": "chest", "l_upper": "chest", "l_fore": "l_upper", "l_hand": "l_fore",
          "r_upper": "chest", "r_fore": "r_upper", "r_hand": "r_fore", "l_thigh": "hip", "l_shin": "l_thigh",
          "l_foot": "l_shin", "r_thigh": "hip", "r_shin": "r_thigh", "r_foot": "r_shin"}


def _ring(a, b, rx, rz, n=8, steps=(0.15, 0.5, 0.85)):
    """Points on elliptical rings around the segment a->b (x radius rx, z radius rz)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    out = []
    for t in steps:
        c = a + t * (b - a)
        axis = (b - a) / np.linalg.norm(b - a)
        side = np.cross(axis, [0, 0, 1.0])
        side = side / np.linalg.norm(side) if np.linalg.norm(side) > 1e-6 else np.array([1.0, 0, 0])
        front = np.cross(side, axis)
        for k in range(n):
            u = 2 * np.pi * k / n
            out.append(c + side * rx * np.cos(u) + front * rz * np.sin(u))
    return out


def humanoid(unit=1.0, *, chest=None, tail=None, head_scale=1.0, pose="a"):
    """A 1.8 m person in metres times `unit`, facing +z: rings round every limb, a head above the neck, feet boxes
    from the ankle forward, soles on y 0. `chest` moves the chest joint, `tail` adds skin on two joints that are no
    role (a tail from the hip, to `tail` = its tip), `head_scale` enlarges the head (a chibi), `pose` "a" = arms 45
    degrees down, "t" = arms level."""
    J = {"hip": (0, 1.0, 0), "chest": chest or (0, 1.3, 0), "head": (0, 1.55, 0), "r_thigh": (-0.1, 0.95, 0),
         "r_shin": (-0.1, 0.5, 0), "r_foot": (-0.1, 0.08, 0)}
    d = np.array([-0.707, -0.707, 0]) if pose == "a" else np.array([-1.0, 0, 0])
    J["r_upper"] = (-0.2, 1.45, 0)
    J["r_fore"] = tuple(np.add(J["r_upper"], 0.28 * d))
    J["r_hand"] = tuple(np.add(J["r_fore"], 0.26 * d))
    for part in ("upper", "fore", "hand", "thigh", "shin", "foot"):
        x, y, z = J[f"r_{part}"]
        J[f"l_{part}"] = (-x, y, z)
    J = {role: np.asarray(p, float) for role, p in J.items()}
    rows = []                                                       # (point, joint node)
    torso = [J["hip"] + [0, -0.05, 0], J["head"] + [0, -0.05, 0]]
    rows += [(p, NODE["hip"] if p[1] < J["chest"][1] else NODE["chest"]) for p in _ring(*torso, 0.17, 0.11)]
    centre = J["head"] + [0, 0.11 * head_scale, 0]
    for k in range(24):
        u, v = 2 * np.pi * (k % 8) / 8, np.pi * (k // 8 + 0.5) / 3
        rows.append((centre + 0.11 * head_scale * np.array([np.sin(v) * np.cos(u), np.cos(v), np.sin(v) * np.sin(u)]),
                     NODE["head"]))
    for s in "rl":
        rows += [(p, NODE[f"{s}_upper"]) for p in _ring(J[f"{s}_upper"], J[f"{s}_fore"], 0.05, 0.05)]
        rows += [(p, NODE[f"{s}_fore"]) for p in _ring(J[f"{s}_fore"], J[f"{s}_hand"], 0.04, 0.04)]
        tip = J[f"{s}_hand"] + 0.3 * (J[f"{s}_hand"] - J[f"{s}_fore"])
        rows += [(p, NODE[f"{s}_hand"]) for p in _ring(J[f"{s}_hand"], tip, 0.03, 0.015)]
        rows += [(p, NODE[f"{s}_thigh"]) for p in _ring(J[f"{s}_thigh"], J[f"{s}_shin"], 0.075, 0.075)]
        rows += [(p, NODE[f"{s}_shin"]) for p in _ring(J[f"{s}_shin"], J[f"{s}_foot"], 0.055, 0.055)]
        x = J[f"{s}_foot"][0]
        rows += [(np.array([x + dx, y, z]), NODE[f"{s}_foot"]) for dx in (-0.05, 0.05) for y in (0.0, 0.08)
                 for z in (-0.05, 0.2)]
    joints = {NODE[role]: J[role] * unit for role in ROLES} | {1: np.zeros(3)}
    parents = {NODE["hip"]: 1} | {NODE[c]: NODE[p] for c, p in PARENT.items()}
    if tail is not None:
        base, tip = J["hip"] + [0, -0.05, -0.12], np.asarray(tail, float)
        joints |= {60: base * unit, 61: (base + tip) / 2 * unit}
        parents |= {60: NODE["hip"], 61: 60}
        rows += [(p, 60 if i < 16 else 61) for i, p in enumerate(_ring(base, tip, 0.05, 0.05, steps=(0.1, 0.4, 0.7, 0.95)))]
    vertices = [{"position": tuple(map(float, p * unit)), "normal": (0.0, 0.0, 1.0), "uv": (0.5, 0.5),
                 "source_joints": (node,), "source_weights": (1.0,)} for p, node in rows]
    faces = [(i, i + 1, i + 2) for i in range(0, len(vertices) - 2, 3)]
    return {"name": "humanoid.glb", "vertices": vertices, "faces": faces, "atlas": gradient(32, 32),
            "joints": joints, "parents": parents, "role_nodes": dict(NODE), "report": {},
            "donor": {"slug": "humanoid", "name": "humanoid", "game": "test", "franchise": "test"}}


def native_body(skeleton=SKELETON):
    """A native-like figure on the synthetic skeleton: rings round its bones, a head to 1,740, feet on y 0."""
    model = A.HdBin.parse(make_bin(skeleton=skeleton))
    bones = model.bone_world()
    rows = []
    rows += [(p, 0 if p[1] < 1250 else 2) for p in _ring(bones[0] - [0, 60, 0], bones[4], 170, 120)]
    rows += [(p, 4) for p in _ring(bones[4], bones[4] + [0, 190, 0], 90, 100, steps=(0.1, 0.5, 1.0))]
    for upper, fore, hand, thigh, shin, foot in ((7, 8, 10, 18, 19, 20), (13, 14, 16, 22, 23, 24)):
        rows += [(p, upper) for p in _ring(bones[upper], bones[fore], 50, 50)]
        rows += [(p, fore) for p in _ring(bones[fore], bones[hand], 45, 45)]
        rows += [(p, thigh) for p in _ring(bones[thigh], bones[shin], 75, 75)]
        rows += [(p, shin) for p in _ring(bones[shin], bones[foot], 55, 55)]
        x = bones[foot][0]
        rows += [(np.array([x + dx, y, z]), foot) for dx in (-50, 50) for y in (0, 90) for z in (-50, 200)]
    count = len(rows) - len(rows) % 3
    rows = rows[:count]
    bone_ids = sorted({b for _p, b in rows})
    sets = [((b, 100),) for b in bone_ids]
    return model.with_geometry(positions=np.asarray([p for p, _b in rows]),
                               normals=np.tile([0.0, 0.0, 1.0], (count, 1)), uvs=np.zeros((count, 2)),
                               weight_sets=sets, weight_index=np.asarray([bone_ids.index(b) for _p, b in rows]),
                               materials=[material([(A.PRIM_LIST, count)])], texture_count=6)


BODY = native_body()
BONES = BODY.bone_world()
NATIVE = M.native_envelope([BODY])


def fitted(donor, method="proportional"):
    return M._fit(donor, BONES, role_bones=M.ROLE_BONES, method=method, native=NATIVE)


def report(donor, method="proportional", gate=M.FIT_GATE):
    return M.fit_report(donor, BODY, native=NATIVE, method=method, gate=gate)


def test_the_native_envelope_measures_the_synthetic_figure():
    assert NATIVE["top"] == pytest.approx(1740, abs=1) and abs(NATIVE["floor"]) < 1
    assert NATIVE["head_up"] == pytest.approx(190, abs=1) and NATIVE["far_share"] == 0.0
    assert 200 < NATIVE["depth_z"] < 330 and NATIVE["skeleton_span_x"] == pytest.approx(1650, abs=1)
    assert set(NATIVE["parts"]) == {"torso", "head", "arm", "leg"}
    headless = M.native_envelope([BODY.with_positions(np.minimum(BODY.positions(), 1500))])
    assert headless["head_assumed"] and headless["top"] == BONES[4][1] + M.NATIVE_HEAD_UP


# ----------------------------------------------------------------------------------- cause 1: the donor's unit

@pytest.mark.parametrize("unit", [1.0, 39.37, 100.0, 1000.0])
def test_the_proportional_fit_does_not_depend_on_the_donors_unit(unit):
    metres, _n, _i, _r = fitted(humanoid(1.0))
    other, _n, _i, rep = fitted(humanoid(unit))
    assert np.allclose(other, metres, atol=1e-6 * 2000)
    assert rep["unit_mm_per_donor_unit"] == pytest.approx(
        fitted(humanoid(1.0))[3]["unit_mm_per_donor_unit"] / unit, rel=1e-4)
    assert report(humanoid(unit))["pass"]


def test_the_legacy_scales_flatten_a_metre_donor_and_inflate_a_centimetre_one():
    """SCALES are model mm per donor unit: right for a ~10 cm unit only. A metre donor is cardboard, a cm one a giant."""
    flat = report(humanoid(1.0), "legacy")
    assert not flat["pass"] and flat["metrics"]["depth_z"] < 60
    assert any(r.startswith("flat") for r in flat["reasons"])
    giant = report(humanoid(100.0), "legacy")
    assert not giant["pass"] and giant["metrics"]["depth_z"] > 2000
    assert any(r.startswith("height") for r in giant["reasons"]) and any(r.startswith("wide") for r in giant["reasons"])
    fixed = report(humanoid(1.0))["metrics"]
    assert 200 < fixed["depth_z"] < 330 and 0.95 < fixed["top"] / NATIVE["top"] < 1.1


# ---------------------------------------------------------------------------- cause 2: an uncapped hip segment

@pytest.mark.parametrize("chest", [(0, 0.98, 0.0), (0, 1.02, 0.0), (0, 1.0, 0.04)])
def test_a_chest_joint_at_or_under_the_hip_no_longer_blows_the_torso_up(chest):
    """RE2 GC HUNK (chest 0.02 units under the hip), JGR Rival Ntank, SoulCalibur's waist-level spine."""
    legacy = report(humanoid(1.0, chest=chest), "legacy")
    assert not legacy["pass"] and any("segment hip" in r for r in legacy["reasons"])
    assert legacy["measured"]["max_stretch"] > 4
    fixed = report(humanoid(1.0, chest=chest))
    assert fixed["pass"], fixed["reasons"]
    assert fixed["measured"]["height_ratio"] < 1.1 and fixed["measured"]["max_stretch"] < 1.3
    assert fixed["fit"]["segments"]["spine"]["turn_deg"] < 5


def short_arms():
    """Forearms half as long as the body's proportion says: the native length draws them 2x."""
    donor = humanoid(1.0)
    for role in ("l_fore", "r_fore"):
        hand = NODE[role.replace("fore", "hand")]
        donor["joints"][hand] = (donor["joints"][NODE[role]] + donor["joints"][hand]) / 2
    return donor


def test_every_segment_is_drawn_at_most_the_stretch_limit_longer_than_wide():
    donor = short_arms()
    _p, _n, _i, rep = fitted(donor)
    rows = rep["segments"]
    assert all(1 / M.STRETCH_LIMIT - 1e-9 <= r["anisotropy"] <= M.STRETCH_LIMIT + 1e-9 for r in rows.values())
    assert rows["l_fore"]["stretch"] > 1.7 and rows["l_fore"]["cross_moved"]
    verdict = report(donor)
    assert not verdict["pass"] and any("segment l_fore drawn" in r for r in verdict["reasons"])


# ------------------------------------------------------------------- cause 3: off-role skin, and the floor

def test_off_role_skin_rides_its_role_at_the_donors_own_size():
    """A tail on joints that are no role: legacy stretches it with the hip segment, the new fit keeps its size."""
    donor = humanoid(1.0, chest=(0, 1.02, 0.0), tail=(0, 0.35, -0.5))
    tail = [i for i, v in enumerate(donor["vertices"]) if v["source_joints"][0] in (60, 61)]
    legacy, _n, _i, _r = fitted(donor, "legacy")
    assert legacy[tail, 1].min() < -1000                           # under the floor, as the Lizardman's tail
    positions, _n, _i, rep = fitted(donor)
    assert positions[tail, 1].min() > 200 and rep["off_role_weight_share"] > 0.05
    donor_tail = np.asarray([donor["vertices"][i]["position"] for i in tail])
    assert np.ptp(positions[tail], 0).max() == pytest.approx(rep["unit_mm_per_donor_unit"] * np.ptp(donor_tail, 0).max(),
                                                             rel=0.35)
    assert report(donor)["pass"]


def test_a_long_tail_is_refused_as_too_deep_and_far_from_the_bones():
    verdict = report(humanoid(1.0, tail=(0, 0.1, -1.6)))
    assert not verdict["pass"]
    assert any(r.startswith("deep") for r in verdict["reasons"]) and verdict["metrics"]["far_share"] > 0


def test_the_soles_not_the_lowest_vertex_land_on_the_floor():
    donor = humanoid(1.0, tail=(0, -0.2, -0.4))                    # a tail that drags under the soles
    positions, _n, _i, rep = fitted(donor)
    feet = [i for i, v in enumerate(donor["vertices"]) if v["source_joints"][0] in (NODE["r_foot"], NODE["l_foot"])]
    assert positions[feet, 1].min() == 0.0
    assert all(f["anchor_moved"] is False for f in rep["feet"].values())
    verdict = report(donor)
    assert any(r.startswith("under the floor") for r in verdict["reasons"])


# ------------------------------------------------------------------------- cause 4: the rotation is not one

def test_the_rotation_keeps_the_depth_axis():
    for pose in ("a", "t"):
        _p, _n, _i, rep = fitted(humanoid(1.0, pose=pose))
        assert all(row["depth_kept"] >= 0.94 for row in rep["segments"].values()), pose
    metres = report(humanoid(1.0))["metrics"]["parts"]["torso"]["depth"]
    assert metres == pytest.approx(2 * 0.11 * np.sin(3 * np.pi / 8) * fitted(humanoid(1.0))[3]["unit_mm_per_donor_unit"],
                                   rel=0.15)


# ------------------------------------------------------------------------------ the head, a chibi donor

def test_a_chibi_head_is_capped_to_the_native_head():
    donor = humanoid(1.0, head_scale=3.0)
    legacy_top = fitted(donor, "proportional")[0][:, 1].max()
    _p, _n, _i, rep = fitted(donor)
    assert rep["head"]["capped"] and legacy_top <= NATIVE["top"] * 1.2
    verdict = report(donor)
    assert verdict["pass"], verdict["reasons"]
    head = verdict["metrics"]["parts"]["head"]
    assert max(head["width"], head["depth"]) <= M.HEAD_SIZE_LIMIT * M._head_size(NATIVE) + 1


# -------------------------------------------------------------------------- cause 5: non-humanoid donors

def _prop(kind):
    """A rig with all fifteen roles that is not a person: a pistol lying along z, a car, a body on all fours."""
    donor = humanoid(1.0)
    J = donor["joints"]
    if kind == "pistol":                                           # every role along a barrel, legs a stub
        for i, role in enumerate(ROLES):
            J[NODE[role]] = np.array([0.02 * (role[0] == "l") - 0.02 * (role[0] == "r"), 0.1 + 0.01 * i, 0.03 * i])
        J[NODE["head"]] = np.array([0.0, 0.3, 0.45])
    elif kind == "all_fours":                                      # the spine lies along z
        J[NODE["hip"]], J[NODE["chest"]], J[NODE["head"]] = (np.array([0, 0.8, -0.5]), np.array([0, 0.85, 0.0]),
                                                             np.array([0, 0.9, 0.6]))
    for vertex in donor["vertices"]:
        if kind == "car":
            x, y, z = vertex["position"]
            vertex["position"] = (x, y * 0.25, z * 9.0 + 0.4 * np.sign(z or 1))
    return donor


@pytest.mark.parametrize("kind", ["pistol", "car", "all_fours"])
def test_props_vehicles_and_quadrupeds_are_not_humanoids(kind):
    reasons = M.humanoid_reasons(M.donor_shape(_prop(kind)))
    assert reasons and all(r.startswith("not a humanoid") for r in reasons)
    assert not report(_prop(kind))["pass"]


def test_a_fighting_stance_is_still_a_humanoid():
    """Dead or Alive ++ rigs stand one foot forward, one back (role joints 0.45-0.72 of the height apart in z)."""
    donor = humanoid(1.0)
    for part, dz in (("thigh", 0.05), ("shin", 0.18), ("foot", 0.3)):
        donor["joints"][NODE[f"r_{part}"]] = donor["joints"][NODE[f"r_{part}"]] + [0, 0, dz]
        donor["joints"][NODE[f"l_{part}"]] = donor["joints"][NODE[f"l_{part}"]] - [0, 0, dz]
    shape = M.donor_shape(donor)
    assert shape["joint_depth_share"] > 0.3 and M.humanoid_reasons(shape) == []


# ------------------------------------------------------------------------------------------- the gate

def test_judge_names_every_threshold():
    base = report(humanoid(1.0))
    assert base["pass"] and base["reasons"] == []
    metrics, fit = base["metrics"], base["fit"]

    def reasons(**change):
        m = json.loads(json.dumps(metrics))
        for key, value in change.items():
            if key == "torso":
                m["parts"]["torso"]["depth"] = value
            elif key == "head":
                m["parts"]["head"]["width"] = value
            else:
                m[key] = value
        return M.judge(m, NATIVE, fit)["reasons"]

    assert reasons(top=NATIVE["top"] * 1.25)[0].startswith("height")
    assert reasons(top=NATIVE["top"] * 0.8)[0].startswith("height")
    assert reasons(depth_z=120)[0].startswith("flat:")
    assert reasons(torso=80)[0].startswith("flat torso")
    assert reasons(floor=-60)[0].startswith("under the floor")
    assert reasons(soles={"r_foot": 9.0, "l_foot": 0.0})[0].startswith("r_foot sole")
    assert reasons(span_x=NATIVE["skeleton_span_x"] * 1.4)[0].startswith("wide")
    assert reasons(depth_z=NATIVE["depth_z"] * 3.2)[0].startswith("deep")
    assert reasons(head=M._head_size(NATIVE) * 1.9)[0].startswith("head")
    assert reasons(far_share=0.09)[0].endswith("weapons dominate")
    stretched = json.loads(json.dumps(fit))
    stretched["segments"]["r_shin"] |= {"stretch": 1.75, "anisotropy": 1.9}
    got = M.judge(metrics, NATIVE, stretched)["reasons"]
    assert any("r_shin drawn 1.75x" in r for r in got) and any("r_shin 1.90x longer than wide" in r for r in got)
    lo, hi = M.FIT_GATE["height_ratio"]
    assert (lo, hi) == (0.85, 1.2) and M.FIT_GATE["min_depth_mm"] == 150 and M.FIT_GATE["floor_mm"] == 50


def test_fit_report_returns_a_refusal_for_a_rig_the_fit_cannot_take():
    donor = humanoid(1.0)
    donor["joints"][NODE["l_fore"]] = donor["joints"][NODE["l_upper"]]
    verdict = report(donor)
    assert not verdict["pass"] and "zero length" in verdict["reasons"][0] and verdict["metrics"] == {}
    assert json.dumps(verdict, default=str)


def test_the_legacy_method_is_the_old_fit_byte_for_byte():
    donor = humanoid(1.0)
    old = M.fit(donor["vertices"], donor["joints"], donor["parents"], donor["role_nodes"], BONES)
    new = fitted(donor, "legacy")
    assert np.array_equal(old[0], new[0]) and old[2] == new[2]


def test_author_body_with_the_gate_refuses_a_failing_donor_and_records_a_passing_ones_report():
    target, archive = player_pack(seed=3), make_pack(PACK_ID).build()
    _out, _arch, receipt = M.author_body(target, archive, humanoid(1.0))
    gate = receipt["fit"]["gate"]
    assert receipt["fit"]["method"].startswith("proportional") and gate["enforced"] is False
    assert set(gate) >= {"pass", "reasons", "measured", "metrics", "native"}
    with pytest.raises(M.ModelError, match="fit gate: not a humanoid"):
        M.author_body(target, archive, _prop("pistol"), gate=M.FIT_GATE)


# ---------------------------------------------------------------------------------------- the reject list

def test_donor_rejects_reads_the_list_and_scopes_it(tmp_path):
    assert M.donor_rejects(tmp_path / "absent.json") == {}
    path = tmp_path / "donor_rejects.json"
    path.write_text(json.dumps({"rejects": {"giant": "oversized on RE5", "re6_only": {"reason": "x", "titles": ["re6"]},
                                            "ours": {"reason": "flat", "titles": [M.TITLE_ID]}, "_note": "comment"}}))
    assert M.donor_rejects(path) == {"giant": "donor reject list: oversized on RE5",
                                     "ours": "donor reject list: flat"}
    path.write_text(json.dumps({"rejects": ["a", {"slug": "b", "reason": "r", "games": ["re4"]}]}))
    assert set(M.donor_rejects(path)) == {"a", "b"}
    path.write_text(json.dumps(["c"]))
    assert set(M.donor_rejects(path)) == {"c"}
    path.write_text("{not json")
    with pytest.raises(M.ModelError, match="cannot be read"):
        M.donor_rejects(path)


# ------------------------------------------------------------------------------------- the pools use the gate

def _donor_row(slug, franchise):
    return re5_donor_pool.Donor(slug=slug, name=slug, game=franchise, franchise=franchise, platform="test",
                                model=f"{slug}.glb", sha256="0" * 64, roles=tuple((r, r) for r in ROLES),
                                roles_from="test", provenance="test")


def _library(monkeypatch, records):
    def fake(library, slug, *, roles=None, atlas_size=(1024, 1024), sha256_expected=None):
        record = dict(records[slug])
        record["donor"] = {"slug": slug, "name": slug, "game": "test", "franchise": slug, "model": f"{slug}.glb",
                           "sha256": "0" * 64, "roles": {}}
        return record
    monkeypatch.setattr(M, "library_donor", fake)


def test_cast_pool_writes_only_passing_donors_and_skips_the_reject_list(tmp_path, monkeypatch):
    em, img = tmp_path / "em", tmp_path / "img"
    em.mkdir(), img.mkdir()
    for pack in ("pl08", "pl06", "pl0a", "pl0d", "pl0b"):
        (em / f"{pack}.udas").write_bytes(player_pack(seed=3))
    (img / "01000008.pack.fen").write_bytes(make_pack(PACK_ID).build())
    good = {f"good{i}": humanoid([1.0, 100.0, 39.37, 1000.0, 2.5, 10.0][i]) for i in range(6)}
    bad = {"pistol": _prop("pistol"), "car": _prop("car"), "short_arms": short_arms()}
    _library(monkeypatch, good | bad)
    rejects = tmp_path / "donor_rejects.json"
    rejects.write_text(json.dumps({"rejects": {"good5": "seen broken on RE5"}}))
    rows = [_donor_row(slug, f"F{slug}") for slug in sorted(good | bad)]
    receipt = M.cast_pool(em, img, tmp_path / "lib", rows, "seed-1", tmp_path / "out", rejects=rejects)
    assert set(receipt["assignment"].values()) <= {f"good{i}" for i in range(5)}
    assert len(set(receipt["assignment"].values())) == 5
    aside = receipt["plan"]["set_aside"]
    assert aside["good5"].startswith("donor reject list")
    assert all(row["fit"]["gate"]["pass"] and row["fit"]["gate"]["enforced"] for row in receipt["slots"].values())
    assert receipt["plan"]["fit_method"] == "proportional" and receipt["plan"]["reject_list"]["entries"] == 1
    for slug in ("pistol", "car", "short_arms"):
        assert slug not in receipt["assignment"].values()
    gated = {slug: reason for slug, reason in aside.items() if slug in bad}
    assert gated and all("fit gate:" in reason for reason in gated.values())      # dealt, measured, set aside
    with pytest.raises(M.ModelError, match="reject list"):
        M.cast_pool(em, img, tmp_path / "lib", rows, "seed-1", tmp_path / "out2", rejects=rejects,
                    assignment={"leon": "good5"})


def test_enemy_pool_checks_every_donor_on_its_own_body(tmp_path, monkeypatch):
    em, img = tmp_path / "em", tmp_path / "img"
    em.mkdir(), img.mkdir()
    (em / "emzz.udas").write_bytes(ganado_pack())
    (img / "00000016.pack.fen").write_bytes(make_pack(GANADO_ID).build())
    records = {"good_a": humanoid(1.0), "good_b": humanoid(100.0), "pistol": _prop("pistol"),
               "flat_chest": humanoid(1.0, chest=(0, 0.98, 0.0))}
    _library(monkeypatch, records)
    rows = [_donor_row(slug, f"F{slug}") for slug in sorted(records)]
    receipt = E.enemy_pool(em, img, tmp_path / "lib", rows, "seed-2", tmp_path / "out", classes=("emzz",))
    assert "pistol" not in receipt["assignment"].values() and len(receipt["assignment"]) == 2
    groups = receipt["classes"]["emzz"]["groups"]
    assert all(g["fit"]["gate"]["pass"] and g["fit"]["gate"]["enforced"] for g in groups)
    out = tmp_path / "out2"
    pinned = {"emzz:1": "pistol", "emzz:4": "good_a"}
    with pytest.raises(E.EnemyError, match="emzz:1 <- pistol: fit gate"):
        E.enemy_pool(em, img, tmp_path / "lib", rows, "seed-2", out, classes=("emzz",), assignment=pinned)
