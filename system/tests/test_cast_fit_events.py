"""The Fitting pop-up on the whole-cast builders (gbox.cast_swap BUILDERS): every model planned up front, then per
slot scale (the donor as loaded, its original height) -> retarget (on the slot's skeleton, posed) -> proportion ->
weights (per-limb / per-node vertices) -> decimate -> encode -> write, with mesh snapshots. Synthetic data only (no
disc, Blender or emulator); the OoT cast build's own sequence is in tests/test_oot_cast.py."""
import importlib
from types import SimpleNamespace

import pytest

from gbox import characters as C, fit_events as FE

FULL = ["scale", "retarget", "proportion", "weights", "decimate", "encode", "write"]


def collect():
    lines = []
    return lines, (lambda pct, msg: lines.append((pct, msg)))


def events(lines):
    return [FE.split(m)[1] for _p, m in lines if FE.split(m)[1] is not None]


def order(evs, key):
    seen = []
    for e in evs:
        if e.get("model") == key and e.get("stage") and e["stage"] not in seen:
            seen.append(e["stage"])
    return seen


def last(evs, key, stage):
    return [e for e in evs if e.get("model") == key and e.get("stage") == stage][-1]


def glb_vertices(path):
    from tests.test_fit_events import read_glb
    return read_glb(path)["accessors"][0]["count"]


def assert_snapshots(evs, key, stages=("scale", "retarget")):
    for st in stages:
        e = last(evs, key, st)
        assert e.get("snapshot") and glb_vertices(e["snapshot"]) > 0, (key, st, e)


# ---------------------------------------------------------------- PSO Ver.2 enemies (pso_enemy.build_cast)

def test_pso_build_cast_reports_every_enemy_slot(tmp_path, monkeypatch):
    from gbox import pso_enemy as PE
    from tests.test_cast_swap import PSO
    T = importlib.import_module("test_pso_enemy")
    bml = T.enemy_pack()
    gdi = T.make_gdi(tmp_path / "src", {"BM_ENE_LAPPY_AP.BML": bml, "BM_ENE_OTHER_A.BML": b"other" * 500})
    lib = tmp_path / "library"
    metas = {}
    for slug, pos in (("briggs", T.DONOR_POS), ("kane", T.DONOR_POS * [1, 1.3, 1])):
        (lib / slug).mkdir(parents=True)
        T.donor_gltf(lib / slug / "model.gltf", pos=pos)
        metas[slug] = {"slug": slug, "name": slug.title(), "model": "model.gltf",
                       "rig": {"roles": {n: n for n in T.DONOR_NAMES}}}
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    pairs = [("player", metas["briggs"]), ("enemy:lappy_base", metas["briggs"]), ("enemy:lappy_two", metas["kane"])]
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        r = PE.build_cast(SimpleNamespace(cache=tmp_path / "cache"), PSO, gdi, pairs, "cast_pso_fit", root=lib)
    assert r["mod"] == "cast_pso_fit"
    evs = events(lines)
    assert [x["model"] for x in evs[0]["plan"]] == ["player", "enemy:lappy_base", "enemy:lappy_two"]
    for slot, donor in (("enemy:lappy_base", "Briggs"), ("enemy:lappy_two", "Kane")):
        assert order(evs, slot) == FULL, (slot, order(evs, slot))
        assert_snapshots(evs, slot)
        sc = last(evs, slot, "scale")["data"]
        assert sc["donor_height"] > 0 and sc["fitted_height"] > 0 and sc["scale"] > 0
        w = last(evs, slot, "weights")["data"]
        assert w["vertices"] == sum(w["per_limb"].values()) > 0 and w["nodes"] >= 2
        assert last(evs, slot, "decimate")["state"] == "skipped"
        enc = last(evs, slot, "encode")["data"]
        assert enc["bytes"] == enc["body_bytes"] + enc["pvm_bytes"] and enc["pack_bytes"] <= enc["room"]
        wr = last(evs, slot, "write")
        assert wr["state"] == "done" and wr["data"]["mod"] == "cast_pso_fit" and wr["data"]["enemies"] == 1
    assert order(evs, "player") == ["write"] and last(evs, "player", "write")["state"] == "failed"
    # Kane is 1.3x taller than Briggs as loaded; both are fitted to the same Rappy
    assert last(evs, "enemy:lappy_two", "scale")["data"]["donor_height"] > \
        last(evs, "enemy:lappy_base", "scale")["data"]["donor_height"]


# ---------------------------------------------------------------- DOA2 roster (doa2_swap.build_roster)

def test_doa2_weighted_fit_reports_the_donor_its_limbs_and_the_two_influence_reduction(tmp_path):
    from gbox import doa2_swap
    from gbox.doa2_weighted_retarget import retarget
    from tests.test_doa2_weighted_retarget import rig, target
    r, t = rig(), target()
    r["source"] = str(tmp_path / "amy" / "amy.glb")
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        FE.model("fighter:KAS", "Amy -> Kasumi")
        prims, fit = retarget(r, t, None, t["jmap"])
        fit["max_influences"] = 3                       # as if the donor had three: the SUP reduction runs
        prims, fit["influence_reduction"] = doa2_swap.limit_influences(prims, 2)
        doa2_swap.weights_stage(prims, fit, t["jmap"])
    evs = events(lines)
    assert order(evs, "fighter:KAS") == ["scale", "retarget", "proportion", "weights"]
    assert_snapshots(evs, "fighter:KAS")
    sc = last(evs, "fighter:KAS", "scale")["data"]
    assert sc["donor_height"] == 2.1 and sc["fitted_height"] > 0 and sc["donor_joints"] == 10
    w = last(evs, "fighter:KAS", "weights")["data"]
    assert w["max_influences_before"] == 3 and w["vertices_reduced"] == 0 and w["vertices"] == 15
    assert w["per_limb"]["hip (bone 0)"] == 6 and sum(w["per_limb"].values()) == 15


def test_doa2_roster_plans_every_fighter_and_writes_each_one(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from gbox import doa2_swap as S
    from tests.test_doa2_roster import FakeDisc
    monkeypatch.setattr("gbox.gdrom.GDRom", lambda gdi: FakeDisc())
    monkeypatch.setattr("gbox.doa2_rig.collect_axes", lambda disc: {})

    def edits(disc, audit, gdi, character_dir, out_dir, family, costume="all", *, allow_downscale=False,
              progress=None):
        FE.model(f"fighter:{family}")
        FE.stage("encode", data={"chr_bytes": 4096})
        files = {f"DOA2/{family}00.CHR": b"c" * 10, f"DOA2/{family}00.BIN": b"b" * 5}
        return files, [{"fighter": family, "costume": "00"}], []
    monkeypatch.setattr(S, "fighter_edits", edits)

    def write_mod(gdi, out_dir, name, slug, changes, reports, progress):
        Path(out_dir, ".gbox-mod.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        return {"mod": name, "image": str(Path(out_dir) / "doa2.gdi")}
    monkeypatch.setattr(S, "write_mod", write_mod)
    donors = {}
    for slug in ("sonic", "sa2_tails"):
        (tmp_path / slug).mkdir()
        donors[slug] = tmp_path / slug
    plan = S.plan_roster([("Kasumi", "sonic"), ("", "sa2_tails")], seed="t")
    (tmp_path / "mod").mkdir()
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        S.build_roster("disc.gdi", donors, tmp_path / "mod", plan)
    evs = events(lines)
    assert [x["model"] for x in evs[0]["plan"]] == [f"fighter:{f}" for f in S.ROSTER]
    assert evs[0]["plan"][0]["label"] == "sonic -> Kasumi"
    for family in S.ROSTER:
        wr = last(evs, f"fighter:{family}", "write")
        assert wr["state"] == "done" and wr["data"]["files"] == 2 and wr["data"]["bytes"] == 15
        assert wr["data"]["image"] == "doa2.gdi" and wr["data"]["costumes"] == 1
