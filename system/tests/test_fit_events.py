"""Fitting events (gbox/fit_events.py): the wire format, the server's fold, and emission by the DOA2 and RE4 (char
swap) fits and the shared sm64_swap retarget."""
import json
import struct

import numpy as np
import pytest

from gbox import fit_events as FE


def collect():
    lines = []
    return lines, (lambda pct, msg: lines.append((pct, msg)))


def events(lines):
    return [FE.split(m)[1] for _p, m in lines if FE.split(m)[1] is not None]


def read_glb(path):
    d = open(path, "rb").read()
    magic, version, total = struct.unpack_from("<III", d, 0)
    assert (magic, version, total) == (0x46546C67, 2, len(d))
    jl = struct.unpack_from("<I", d, 12)[0]
    return json.loads(d[20:20 + jl])


# ---------------------------------------------------------------- wire format + fold

def test_an_event_rides_on_a_progress_line_and_splits_back_out():
    msg = "Amy -> Kasumi: retarget" + FE.encode({"model": "fighter:KAS", "stage": "retarget", "data": {"k": 1.5}})
    text, ev = FE.split(msg)
    assert text == "Amy -> Kasumi: retarget" and ev["stage"] == "retarget" and ev["data"] == {"k": 1.5}
    assert FE.split("plain progress") == ("plain progress", None)
    assert FE.split("broken #fit{not json") == ("broken #fit{not json", None)
    wrapped = "KAS: " + msg                               # writers' progress wrappers prefix the message
    assert FE.split(wrapped)[1]["model"] == "fighter:KAS"


def test_fold_builds_per_model_stages_from_a_plan():
    st = FE.fold(None, {"plan": [{"model": "fighter:KAS", "label": "Amy → Kasumi"},
                                 {"model": "fighter:RYU", "label": "Sonic → Ryu"}]}, now=1)
    assert st["order"] == ["fighter:KAS", "fighter:RYU"] and st["models"]["fighter:RYU"]["state"] == "pending"
    st = FE.fold(st, {"model": "fighter:KAS", "stage": "scale", "state": "done", "data": {"scale": 1.23456789}}, now=2)
    st = FE.fold(st, {"model": "fighter:KAS", "stage": "retarget", "snapshot": "/api/jobs/j/fitting/files/a.glb"}, now=3)
    st = FE.fold(st, {"model": "fighter:KAS", "stage": "decimate", "snapshot": "C:/worker/local.glb"}, now=4)
    m = st["models"]["fighter:KAS"]
    assert m["stages"]["scale"]["data"]["scale"] == 1.2346 and m["stages"]["retarget"]["state"] == "running"
    assert m["snapshot"] == "/api/jobs/j/fitting/files/a.glb" and m["snapshot_stage"] == "retarget"
    assert m["current"] == "decimate" and st["current"] == "fighter:KAS"   # a local path never reaches the client
    st = FE.fold(st, {"model": "fighter:KAS", "stage": "write", "state": "done"}, now=5)
    assert st["models"]["fighter:KAS"]["state"] == "done"
    st = FE.fold(st, {"model": "fighter:RYU", "stage": "encode", "state": "failed"}, now=6)
    assert st["models"]["fighter:RYU"]["state"] == "failed"


def test_fold_bounds_models_and_data():
    st = {}
    for i in range(FE.MAX_MODELS + 10):
        st = FE.fold(st, {"model": f"m{i}", "stage": "scale", "data": {"x": list(range(100)), "s": "y" * 999}})
    assert len(st["order"]) == FE.MAX_MODELS
    d = st["models"]["m0"]["stages"]["scale"]["data"]
    assert len(d["x"]) == 24 and len(d["s"]) == 160


def test_without_a_sink_every_call_is_a_no_op():
    assert not FE.active()
    FE.model("x")
    FE.stage("scale", data={"a": 1}, prims=[{"pos": np.zeros((3, 3)), "tris": np.array([[0, 1, 2]])}])
    assert FE.current() is None


def test_snapshot_glb_is_a_valid_bounded_mesh(tmp_path):
    rng = np.random.default_rng(0)
    prims = [{"pos": rng.normal(size=(900, 3)), "tris": rng.integers(0, 900, size=(5000, 3))},
             {"pos": rng.normal(size=(30, 3)), "tris": rng.integers(0, 30, size=(10, 3))}]
    gl = read_glb(FE.snapshot_glb(prims, tmp_path / "s.glb", max_tris=1000))
    assert gl["accessors"][2]["count"] == 3000 and gl["accessors"][0]["count"] <= 930
    assert gl["meshes"][0]["primitives"][0]["attributes"] == {"POSITION": 0, "COLOR_0": 1}


def test_plan_and_auto_model_assign_fits_to_planned_slots(tmp_path):
    lines, sink = collect()
    with FE.job(sink, tmp_path):
        FE.plan([("enemy:booma", "amy", "Amy → Booma"), ("enemy:gobooma", "amy", "Amy → Gobooma"),
                 ("enemy:rappy", "sonic", "Sonic → Rappy")])
        assert FE.auto_model(tmp_path / "sonic" / "sonic.glb") == "enemy:rappy"
        FE.stage("retarget")
        assert FE.auto_model(tmp_path / "amy" / "amy.glb") == "enemy:booma"
        FE.stage("retarget")
        assert FE.auto_model(tmp_path / "amy" / "amy.glb") == "enemy:gobooma"   # same donor, next planned slot
        FE.stage("retarget")
        assert FE.auto_model(tmp_path / "amy" / "amy.glb") == "enemy:gobooma"   # a refit: nothing left planned
        FE.model("player", "Amy → player")
        assert FE.auto_model(tmp_path / "other" / "x.glb") == "player"           # an explicit model keeps its fits
    assert not FE.active()
    evs = events(lines)
    assert evs[0]["plan"][1] == {"model": "enemy:gobooma", "label": "Amy → Gobooma"}
    assert [e["model"] for e in evs if e.get("stage") == "retarget"] == ["enemy:rappy", "enemy:booma", "enemy:gobooma"]


# ---------------------------------------------------------------- emission by the fits

def _fixture():
    from tests.test_doa2_weighted_retarget import rig, target
    return rig(), target()


def test_doa2_weighted_fit_emits_scale_retarget_and_proportion_with_snapshots(tmp_path):
    from gbox.doa2_weighted_retarget import retarget
    rig, tgt = _fixture()
    rig["source"] = str(tmp_path / "amy_rose" / "amy.glb")
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        FE.model("fighter:KAS", "Amy → Kasumi (costume 00)", "amy_rose")
        retarget(rig, tgt, {"profile": {"head": 1.3}}, tgt["jmap"])
    evs = events(lines)
    stages = [(e["stage"], e["state"]) for e in evs if "stage" in e]
    assert stages == [("scale", "done"), ("retarget", "done"), ("proportion", "done")]
    assert all(e["model"] == "fighter:KAS" for e in evs)
    scale = next(e for e in evs if e.get("stage") == "scale")["data"]
    assert scale["scale"] > 0 and "head_scale" in scale
    prop = next(e for e in evs if e.get("stage") == "proportion")
    assert prop["data"]["applied"] is True and prop["data"]["head"] == 1.3
    for e in evs:
        if e.get("stage") in ("retarget", "proportion"):
            assert read_glb(e["snapshot"])["accessors"][0]["count"] > 0
    texts = [FE.split(m)[0] for _p, m in lines]
    assert "Amy → Kasumi (costume 00): proportion" in texts


def test_doa2_limit_influences_and_write_are_stages_of_the_current_model(tmp_path):
    from gbox import doa2_swap
    lines, sink = collect()
    prims = [{"J": np.array([[1, 2, 3]]), "W": np.array([[.5, .3, .2]]), "pos": np.zeros((1, 3))}]
    with FE.job(sink, tmp_path):
        FE.model("fighter:KAS", "Amy → Kasumi")
        out, rep = doa2_swap.limit_influences(prims, 2)
        FE.stage("weights", data=rep)
        FE.stage("write", data={"image": "x.gdi"})
        assert FE.auto_model(tmp_path / "amy" / "a.glb") != "fighter:KAS"       # written: a new fit is a new model
    evs = events(lines)
    assert [e.get("stage") for e in evs if "stage" in e] == ["weights", "write"]
    assert evs[1]["data"]["vertices_reduced"] == 1


def test_sm64_fit_without_a_profile_reports_proportion_skipped(tmp_path):
    from gbox import sm64_swap as S
    rig, tgt = _fixture()
    lines, sink = collect()
    with FE.job(sink, tmp_path):
        S.retarget(rig, tgt, None, tgt["jmap"])
    evs = events(lines)
    assert evs[0]["label"] == "model 1"                   # no source path, no writer model: still one entry
    assert [(e["stage"], e["state"]) for e in evs if "stage" in e][-1] == ("proportion", "skipped")


class _Template:
    """re4gc_models.Bin stand-in: bones (id, parent, _, x, y, z) in world space."""
    def __init__(self, roles, pos):
        self.bones = [(b, 0xFF, 0, *pos[r]) for r, b in roles.items()]

    def bone_world(self):
        return {b[0]: np.array(b[3:], float) for b in self.bones}


def test_re4_char_swap_fit_emits_stages_and_applies_the_profile(tmp_path):
    from gbox import re4gc_enemies as E
    rig, _tgt = _fixture()
    rig["roles"] = {k: v for k, v in rig["roles"].items() if k != "l_clav"}
    pos = {"pelvis": [0, 950, 0], "hip": [0, 1000, 0], "chest": [0, 1300, 0], "neck": [0, 1500, 0],
           "head": [0, 1600, 0], "r_clav": [-80, 1450, 0], "r_upper": [-200, 1450, 0], "r_fore": [-500, 1450, 0],
           "r_hand": [-750, 1450, 0], "r_hand_end": [-850, 1450, 0], "l_clav": [80, 1450, 0],
           "l_upper": [200, 1450, 0], "l_fore": [500, 1450, 0], "l_hand": [750, 1450, 0],
           "l_hand_end": [850, 1450, 0], "r_thigh": [-100, 950, 0], "r_shin": [-100, 500, 0], "r_foot": [-100, 80, 0],
           "r_toe": [-100, 0, 100], "l_thigh": [100, 950, 0], "l_shin": [100, 500, 0], "l_foot": [100, 80, 0],
           "l_toe": [100, 0, 100]}
    tmpl = _Template(E.GANADO_ROLES, pos)
    base = E.retarget(rig, tmpl)
    lines, sink = collect()
    with FE.job(sink, tmp_path):
        FE.model("player", "Amy → Leon")
        tall = E.retarget(rig, tmpl, scale={"profile": {"height": 1.1}})
    evs = events(lines)
    assert [(e["stage"], e["state"]) for e in evs if "stage" in e] == [("scale", "done"), ("retarget", "done"),
                                                                      ("proportion", "done")]
    assert next(e for e in evs if e.get("stage") == "proportion")["data"]["height"] == 1.1
    ground = np.array([0, 80.0, 0])                     # the feet
    np.testing.assert_allclose(tall[0]["pos"], ground + (base[0]["pos"] - ground) * 1.1, atol=1e-6)


def test_a_cancelled_progress_still_stops_the_writer(tmp_path):
    class Cancelled(Exception):
        pass

    def sink(pct, msg):
        raise Cancelled("operator")
    with FE.job(sink, tmp_path):
        with pytest.raises(Cancelled):
            FE.model("x")
