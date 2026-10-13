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


# ---------------------------------------------------------------- the wrestling match writers (op=match)

def _pso_donor(tmp_path, slug="donor"):
    T = importlib.import_module("test_pso_enemy")
    (tmp_path / "lib" / slug).mkdir(parents=True, exist_ok=True)
    model = T.donor_gltf(tmp_path / "lib" / slug / "m.gltf")
    meta = {"slug": slug, "name": slug.title(), "model": "m.gltf", "rig": {"roles": {n: n for n in T.DONOR_NAMES}}}
    return T, model, meta


def _skeleton(jmap, names, pos, units=30.0):
    """A synthetic target skeleton: the donor's own joint layout (scaled) on the writer's bone numbers."""
    import numpy as np
    n = max(jmap.values()) + 1
    T = np.zeros((n, 3))
    for i, r in enumerate(names):
        if r in jmap:
            T[jmap[r]] = pos[i] * units
    for k in range(n):
        if not T[k].any():
            T[k] = T[jmap["hip"]]
    W = [np.eye(4) for _ in range(n)]
    for k in range(n):
        W[k][:3, 3] = T[k]
    return {"T": T, "W": W, "parent": [-1] * n, "ground": 0.0, "head_h": 8.0, "joints": n}


def test_defjam_fit_reports_every_stage_and_refits_until_the_entry_fits(tmp_path, monkeypatch):
    from gbox import defjam_writer as DJ
    T, model, meta = _pso_donor(tmp_path)
    monkeypatch.setattr(DJ, "target", lambda base: _skeleton(DJ.JMAP, T.DONOR_NAMES, T.DONOR_POS))
    sizes = iter([5000, 900])                             # the first budget overflows the entry, the second fits
    monkeypatch.setattr(DJ, "encode_container", lambda base, fit: (b"x" * next(sizes), {}))
    monkeypatch.setattr(DJ, "verify_container", lambda new, fit: {"ok": True})
    jb = {"model": model, "roles": meta["rig"]["roles"], "name": "Donor"}
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        FE.model("Briggs", "Donor -> Briggs")
        r = DJ.fit_fitting({198: b"base"}, {198: 1000}, jb, tmp_path / "work")
    evs = events(lines)
    assert order(evs, "Briggs") == FULL[:-1], order(evs, "Briggs")
    assert_snapshots(evs, "Briggs")
    w = last(evs, "Briggs", "weights")["data"]
    assert w["per_limb"]["head (bone 7)"] > 0 and w["skeleton_limbs"] == 40 and w["vertices"] == 45
    encs = [e for e in evs if e.get("stage") == "encode"]
    assert [e["state"] for e in encs] == ["running", "done"] and encs[0]["data"]["bytes"] == 5000
    assert encs[1]["data"] == {"bytes": 900, "budget": 1000, "containers": 1, "max_tris": DJ.BUDGETS[1],
                               "triangles": r["fit"]["triangles"], "relocated": False}
    assert last(evs, "Briggs", "scale")["data"]["donor_height"] == 1.75


def test_defjam_match_plans_every_wrestler_and_build_mod_writes_each(tmp_path, monkeypatch):
    from gbox import defjam_writer as DJ, defjam_inventory as inv, defjam_models as M
    _T, _model, a = _pso_donor(tmp_path, "amy")
    _T, _model, b = _pso_donor(tmp_path, "kane")
    monkeypatch.setattr(C, "best_match", lambda chars, q: next(m for m in chars if m["slug"] == q))
    monkeypatch.setattr(DJ, "find_wrestler", lambda q: [{"Briggs": 198, "DMX": 12}[q]])
    seen = {}
    monkeypatch.setattr(DJ, "use", lambda ctx, meta, game, inp, pairs, title: seen.setdefault("pairs", pairs))
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        DJ.match(None, [a, b], {}, None, [("amy", "Briggs"), ("kane", "DMX")])
    assert events(lines)[0]["plan"] == [{"model": "Briggs", "label": "Amy -> Briggs"},
                                        {"model": "DMX", "label": "Kane -> DMX"}]
    monkeypatch.setattr(M, "_source_iso", lambda ctx, game: tmp_path / "djv.iso")
    jobs = {}

    def build_disc(iso, out, js, work, blender=None, progress=None):
        jobs["keys"] = [j["fit_key"] for j in js]
        out.parent.mkdir(parents=True, exist_ok=True)
        return {"image": str(out), "reports": [{"entries": [{"wrestler": "BRIGGS", "index": 198, "bytes": 700}],
                                                "preview_from": b""},
                                               {"entries": [{"wrestler": "DMX", "index": 12, "bytes": 650}],
                                                "preview_from": b""}]}
    monkeypatch.setattr(DJ, "build_disc", build_disc)
    monkeypatch.setattr(M, "assemble", lambda new: {})
    monkeypatch.setattr(inv, "parse_wrs", lambda new: {"slots": {18: {"start": 0}}})
    monkeypatch.setattr(M, "parse_texture", lambda d: {"rgba": None})
    monkeypatch.setattr(M, "write_glb", lambda path, a, name, page: path)
    monkeypatch.setattr("gbox.sm64_swap._blender", lambda cfg: None)
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        r = DJ.build_mod(SimpleNamespace(cache=tmp_path / "cache"), {"game_id": "deabd11481aa5a0c"}, seen["pairs"],
                         root=tmp_path / "lib")
    assert jobs["keys"] == ["Briggs", "DMX"]
    evs = events(lines)
    for slot, n in (("Briggs", 700), ("DMX", 650)):
        wr = last(evs, slot, "write")
        assert wr["data"]["mod"] == r["mod"] and wr["data"]["bytes"] == n and wr["data"]["entries"] == 1


class _NMWriter:
    def __init__(self, rom):
        self.files = []

    def add_file(self, data):
        self.files.append(data)
        return 0x2000 + len(self.files)

    def add_template(self, keys, entries):
        self.template = entries

    def build(self, **kw):
        return b"rom" * 10


def test_no_mercy_rom_build_names_each_wrestler_and_reports_its_encode(tmp_path, monkeypatch):
    from gbox import aki_wrestling as A
    monkeypatch.setattr(A, "NMWriter", _NMWriter)
    monkeypatch.setattr(A, "roster", lambda rom: [{"number": 1, "name": "The Rock", "body": [0], "face_tex": [1]},
                                                  {"number": 2, "name": "Kane", "body": [0], "face_tex": [2]}])
    monkeypatch.setattr(A, "set_ring_names", lambda wr, names: {})

    def fit_character(rom, model, roles, body, work, name, *a, **k):
        FE.stage("retarget", data={"vertices": 9})
        return {"parts": {0x08: (b"m" * 40, "g", None), 0x20: (b"n" * 24, "g", None)}, "textures": {"g": b"t" * 64},
                "palette": b"p" * 512, "rigged": tmp_path / "r.gltf", "report": {"triangles": 30}}
    monkeypatch.setattr(A, "fit_character", fit_character)
    jobs = [{"wrestler": 1, "model": "a", "roles": {}, "name": "Amy", "fit_key": "The Rock"},
            {"wrestler": 2, "model": "b", "roles": {}, "name": "Sonic", "fit_key": "Kane"}]
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        A.build_rom(b"", jobs, tmp_path / "work")
    evs = events(lines)
    for slot in ("The Rock", "Kane"):
        assert order(evs, slot) == ["retarget", "encode"]
        enc = last(evs, slot, "encode")["data"]
        assert enc["bytes"] == 40 + 24 + 64 + 512 and enc["parts"] == 2 and enc["files_added"] == 4
        assert enc["relocated"] is True


def test_no_mercy_and_smackdown_matches_plan_the_cast_and_key_each_wrestler(tmp_path, monkeypatch):
    from gbox import aki_wrestling as A, yukes_sd as Y
    _T, _model, a = _pso_donor(tmp_path, "amy")
    monkeypatch.setattr(C, "best_match", lambda chars, q: a)
    for mod, ros in ((A, [{"number": 1, "name": "The Rock"}, {"number": 2, "name": "Kane"}]),
                     (Y, [{"id": 0, "name": "The Rock"}, {"id": 8, "name": "Kane"}])):
        seen = {}
        monkeypatch.setattr(mod, "use", lambda ctx, meta, game, inp, pairs, title, seen=seen: seen.update(p=pairs))
        if mod is A:
            monkeypatch.setattr(A, "rom_bytes", lambda p: b"")
            monkeypatch.setattr("gbox.tools.rom_path", lambda e, c: "rom.z64")
            monkeypatch.setattr("gbox.models.CatalogEntry", SimpleNamespace(model_validate=lambda g: g))
            monkeypatch.setattr(A, "roster", lambda rom, ros=ros: ros)
            monkeypatch.setattr(A, "find_wrestler", lambda rom, q, ros=ros: next(w for w in ros if w["name"] == q))
        else:
            monkeypatch.setattr(Y, "_roster_for", lambda ctx, game, ros=ros: ros)
            monkeypatch.setattr(Y, "find_wrestler", lambda ros_, q: next(w for w in ros_ if w["name"] == q))
        lines, sink = collect()
        with FE.job(sink, tmp_path / "snaps"):
            mod.match(SimpleNamespace(config=None), [a], {"game_id": "23a346e48b6368a6"}, None,
                      [("amy", "Kane"), ("amy", "")])
        assert events(lines)[0]["plan"] == [{"model": "Kane", "label": "Amy -> Kane"},
                                            {"model": "The Rock", "label": "Amy -> The Rock"}], mod
        assert [w["fit_key"] for _m, w in seen["p"]] == ["Kane", "The Rock"]


# ---------------------------------------------------------------- the chained builders (JGR, Crazy Taxi)

def _cast_ctx(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda *a: None, job_id="j")


def test_crazy_taxi_chain_reports_each_driver_from_the_donor_to_the_written_disc(tmp_path, monkeypatch):
    import gbox.gcdisc as gcdisc
    from gbox import cast_swap as CS, crazy_taxi as ct, crazy_taxi_swap as CTS
    TC = importlib.import_module("test_crazy_taxi_swap")
    bank, _ = TC._bank()

    class Disc:
        def __init__(self, path):
            self.f = SimpleNamespace(close=lambda: None)

        def read(self, name):
            return bank

    def fake_build(cfg, game, iso, new_bank, name, image_name, progress=None):
        return {"mod": name, "dir": str(tmp_path), "image": str(tmp_path / image_name), "files": [ct.BANK]}
    monkeypatch.setattr(gcdisc, "GCDisc", Disc)
    monkeypatch.setattr(ct, "build_mod", fake_build)
    monkeypatch.setattr(CTS, "donor_segments", lambda glb, roles: TC._segs())
    monkeypatch.setattr(C, "_gc_iso", lambda ctx, game: tmp_path / "ct.iso")
    monkeypatch.setattr(C, "_local_or_fetch", lambda ctx, meta, rel: tmp_path / "donor" / rel)
    meta = {"slug": "donor", "name": "Donor", "model": "donor.glb", "rig": {"roles": {"hip": "j_hip"}}}
    pairs = [("driver:axel", meta), ("driver:bd_joe", meta), ("driver:nobody", meta)]
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        FE.plan([(s, "donor", f"Donor -> {s}") for s, _m in pairs])
        r = CS._crazy_taxi(_cast_ctx(tmp_path), {"game_id": "x"}, pairs, "cast_ct", SimpleNamespace())
    assert r["mod"] == "cast_ct" and r["slots"]["driver:nobody"]["status"] == "failed"
    evs = events(lines)
    for slot in ("driver:axel", "driver:bd_joe"):
        assert order(evs, slot) == FULL, (slot, order(evs, slot))
        assert_snapshots(evs, slot)
        assert last(evs, slot, "scale")["data"]["donor_height"] > 0
        w = last(evs, slot, "weights")["data"]
        assert w["limbs"] == len(ct.PARTS) and sum(w["per_limb"].values()) == w["vertices"]
        dec = last(evs, slot, "decimate")["data"]
        assert dec["from"] > dec["triangles"] > 0                   # dense spheres clustered into the stock parts
        enc = last(evs, slot, "encode")["data"]
        assert enc["bytes"] > 0 and enc["relocated"] is False
        wr = last(evs, slot, "write")["data"]
        assert wr["mod"] == "cast_ct" and wr["image"] == "Crazy Taxi cast_ct.iso" and wr["bytes"] == len(bank)
    assert last(evs, "driver:nobody", "write")["state"] == "failed"


def test_jgr_chain_names_each_step_and_writes_every_built_slot(tmp_path, monkeypatch):
    from gbox import cast_swap as CS, gdrom, jgr
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, g: tmp_path / "disc.gdi")
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "lib")
    monkeypatch.setattr(gdrom, "GDRom", lambda p: SimpleNamespace(read=lambda path: b"AFS"))
    monkeypatch.setattr(__import__("gbox.jgr_swap", fromlist=["x"]), "resolve_slot",
                        lambda slot, data: {"archive": {"character:beat": 4, "character:gum": 6}[slot]})

    def build_swap(gdi, model, roles, work, name, index, *a, data=None):
        if index == 6:
            raise ValueError("does not fit")
        FE.stage("encode", data={"bytes": 10})
        return {"files": {jgr.PLAYER_AFS: data + b"#4"}}
    monkeypatch.setattr(jgr, "build_swap", build_swap)
    monkeypatch.setattr(gdrom, "patch_gdi", lambda gdi, d, name, files, progress=None:
                        d.mkdir(parents=True) or d / f"{name}.gdi")
    meta = {"slug": "beat", "name": "Beat", "model": "m.glb", "rig": {"roles": {}}}
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        r = CS._jgr(_cast_ctx(tmp_path), {"game_id": "4187aeab4d67638c"},
                    [("character:beat", meta), ("character:gum", meta)], "cast_jgr", SimpleNamespace())
    assert r["mod"] == "cast_jgr"
    evs = events(lines)
    assert order(evs, "character:beat") == ["encode", "write"]
    wr = last(evs, "character:beat", "write")["data"]
    assert wr == {"mod": "cast_jgr", "image": "cast_jgr.gdi", "files": 1, "bytes": 5}
    gum = last(evs, "character:gum", "write")
    assert gum["state"] == "failed" and gum["data"]["reason"] == "does not fit"


# ---------------------------------------------------------------- Vice City peds (gta_vc_swap.build_cast)

def test_vice_city_build_cast_fits_each_ped_onto_its_skeleton(tmp_path, monkeypatch):
    from pathlib import Path
    from gbox import gta_vc_swap as S
    Y = importlib.import_module("gta_vc_synth")
    inst = Y.install(tmp_path / "vc")
    (tmp_path / "lib" / "donor").mkdir(parents=True)
    Y.donor_glb(tmp_path / "lib" / "donor" / "donor.glb")
    meta = {"slug": "donor", "name": "Donor", "model": "donor.glb", "rig": {"roles": Y.DONOR_ROLES}}
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    game = {"game_id": "1fd42f50b10252e6", "title": "Grand Theft Auto Vice City", "platform": "windows_native"}
    pairs = [("ped:cop", meta), ("ped:male01", meta), ("ped:nosuch", meta)]
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        r = S.build_cast(SimpleNamespace(cache=str(tmp_path / "cache")), game, Path(inst["exe"]), pairs, "cast_vc",
                         root=tmp_path / "lib")
    assert r["mod"] == "cast_vc" and r["slots"]["ped:nosuch"]["status"] == "failed"
    evs = events(lines)
    assert [x["model"] for x in evs[0]["plan"]] == ["ped:cop", "ped:male01", "ped:nosuch"]
    for slot in ("ped:cop", "ped:male01"):
        assert order(evs, slot) == FULL, (slot, order(evs, slot))
        assert_snapshots(evs, slot)
        assert last(evs, slot, "scale")["data"]["donor_height"] > 0
        w = last(evs, slot, "weights")["data"]
        assert w["vertices"] == sum(w["per_limb"].values()) > 0 and any("Head" in k for k in w["per_limb"])
        assert last(evs, slot, "decimate")["state"] == "skipped"
        enc = last(evs, slot, "encode")["data"]
        assert enc["bytes"] == enc["dff_bytes"] + enc["txd_bytes"] and enc["triangles"] == 16 * 12
        wr = last(evs, slot, "write")
        assert wr["state"] == "done" and wr["data"]["mod"] == "cast_vc" and wr["data"]["entries"] == 2
    assert last(evs, "ped:nosuch", "write")["state"] == "failed"
    assert "entries" not in r["slots"]["ped:cop"]


# ---------------------------------------------------------------- 007 Agent Under Fire (auf_swap.build_mod)

@pytest.mark.parametrize("workers", [1, 2])
def test_auf_cast_reports_each_body_even_from_level_worker_processes(tmp_path, workers, monkeypatch):
    import json
    from pathlib import Path
    import gbox
    from gbox import auf_gcm as G, auf_ngc as N, auf_swap as S
    system = str(Path(gbox.__file__).resolve().parents[1])   # spawned level workers import THIS checkout's gbox
    monkeypatch.syspath_prepend(system)
    monkeypatch.chdir(system)
    TA = importlib.import_module("test_auf_swap")
    m = N.mesh(TA._model(("body_mat",)))
    N.to_glb(m, tmp_path / "donor.glb", "donor")
    roles = {r: "bone%02d_%08x" % (i, 0x1000 + i) for r, i in G.auto_roles(N.skeleton(TA.template())).items()}
    donor = S.load_donor("synthetic_wrestler", tmp_path / "donor.glb", roles, "Synthetic Wrestler")
    level = TA.level_package()
    src = TA.gc_image(tmp_path / "auf.iso", {"maps/dm1.ngc": level, "maps/dm2.ngc": level, "opening.bnr": b"x" * 64})
    plan = {("dm1", "body"): "synthetic_wrestler", ("dm2", "body"): "synthetic_wrestler"}
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        r = S.build_mod(tmp_path / "cache", src, "auf_fit", plan, {"synthetic_wrestler": donor}, workers=workers)
    evs = events(lines)
    assert evs[0]["plan"] == [{"model": "body", "label": "Synthetic Wrestler -> body"}]
    assert order(evs, "body") == FULL, order(evs, "body")
    assert_snapshots(evs, "body", ("scale", "retarget", "decimate"))
    sc = last(evs, "body", "scale")["data"]
    assert sc["donor_height"] > 0 and sc["donor_triangles"] > 0 and sc["scale"] > 0
    w = last(evs, "body", "weights")["data"]
    assert w["vertices"] > 0 and sum(w["per_limb"].values()) == w["vertices"] and w["skeleton_limbs"] > 10
    dec = last(evs, "body", "decimate")["data"]
    assert dec["lods"] == 2 and dec["to"] > 0 and dec["triangles"] <= dec["to"]
    enc = last(evs, "body", "encode")["data"]
    assert enc["models"] == 2 and enc["bytes"] > 0
    wr = last(evs, "body", "write")["data"]
    assert wr["mod"] == "auf_fit" and wr["levels"] == 2 and wr["vrom"].startswith("maps/dm1.ngc @ 0x")
    assert all("_snap" not in e for lv in r["levels"] for e in lv["replaced"])      # never in the result
    json.dumps(r["levels"])
    assert Path(r["dir"]).is_dir()


# ---------------------------------------------------------------- Dead Or Alive ++ (doapp_swap.build)

def test_doapp_build_reports_each_costume_from_the_donor_to_the_encoded_file(tmp_path, monkeypatch):
    from gbox import doapp_motion as DM, doapp_swap as W
    TD = importlib.import_module("test_doapp_swap")
    roles = TD.humanoid(tmp_path / "tube.gltf")
    model = TD.synthetic_original()
    monkeypatch.setattr(DM, "Rig", lambda *a: None)
    monkeypatch.setattr(W, "target", lambda ram, banked, f, c, rig=None: TD.synthetic_target(model, f["models"][c]))
    monkeypatch.setattr(W, "SLOT_VERTEX_CAP", {0: 60, 2: 10, 4: 10, 7: 66})    # tight caps: the fit decimates
    monkeypatch.setattr(W, "budget", lambda i: 0x1BAB4)
    jobs = [({"name": "KASUMI", "id": 1, "models": [49, 50]}, 0), ({"name": "KASUMI", "id": 1, "models": [49, 50]}, 1)]
    keys = ["kasumi:kasumi:1", "kasumi:kasumi:2"]
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        FE.plan([(k, "tube", f"Tube -> {k}") for k in keys])
        r = W.build(None, None, tmp_path / "tube.gltf", roles, jobs, tmp_path / "work", "Tube", verify=False,
                    fit_keys=keys)
    evs = events(lines)
    for k, idx in zip(keys, (49, 50)):
        assert order(evs, k) == FULL[:-1], (k, order(evs, k))
        assert_snapshots(evs, k, ("scale", "retarget", "decimate"))
        w = last(evs, k, "weights")["data"]
        assert w["skeleton_limbs"] == 15 and "head (bone 1)" in w["per_limb"]
        dec = last(evs, k, "decimate")["data"]
        assert dec["from"] > dec["triangles"] > 0 and int(dec["caps"]["0"]) <= 60
        enc = last(evs, k, "encode")["data"]
        assert enc["bytes"] == r["reports"][idx]["bytes"] <= enc["budget"] and enc["relocated"] is False


# ---------------------------------------------------------------- Clay Fighter: Sculptor's Cut (sprites)

def test_clayfighter_sprites_show_the_donor_frames_then_the_fitted_ones(tmp_path):
    import numpy as np
    from PIL import Image
    from gbox import clayfighter_swap as S
    TC = importlib.import_module("test_clayfighter_swap")
    rom = TC.synthetic_rom()
    rng = np.random.default_rng(3)
    donor = [np.dstack([rng.integers(0, 256, (90, 60, 3)), np.full((90, 60), 255)]).astype(np.uint8)]
    lines, sink = collect()
    with FE.job(sink, tmp_path / "snaps"):
        FE.model("fighter:taffy", "Donor -> Taffy")
        _new, rep = S.write_fighters(rom, [{"index": 2, "frames": donor}])
    evs = events(lines)
    assert order(evs, "fighter:taffy") == FULL[:-1]
    sc = last(evs, "fighter:taffy", "scale")
    assert sc["data"]["donor_height"] == 90 and sc["data"]["donor_frames"] == 1 and sc["data"]["scale"] > 0
    for st in ("scale", "retarget"):                      # sprites: preview images instead of mesh snapshots
        assert Image.open(last(evs, "fighter:taffy", st)["preview"]).size[0] > 0
    assert [last(evs, "fighter:taffy", s)["state"] for s in ("proportion", "weights", "decimate")] == ["skipped"] * 3
    enc = last(evs, "fighter:taffy", "encode")["data"]
    assert enc["relocated"] is True and rep[0]["relocated"] and enc["bitmap_bytes"] == rep[0]["bitmap_bytes"]
    assert "was 0x" in enc["where"]


# ---------------------------------------------------------------- characters op=collect (any DEDICATED reader)

def _textured_gltf(path):
    """A small skinned glTF with a red 2x2 texture (as a reader writes one): two triangles on two joints."""
    import numpy as np
    from gbox.melee_models import write_gltf
    joints = []
    for parent, y in ((-1, 0.0), (0, 1.0)):
        w = np.eye(4)
        w[1, 3] = y
        joints.append({"parent": parent, "world": w})
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 2, 0], [1, 2, 0]], float)
    J, W = np.zeros((6, 4), int), np.zeros((6, 4))
    J[3:, 0], W[:, 0] = 1, 1
    tex = np.zeros((2, 2, 4), np.uint8)
    tex[..., 0], tex[..., 3] = 255, 255
    prim = {"pos": P, "nrm": np.tile([0, 0, 1.0], (6, 1)), "uv": np.full((6, 2), 0.25), "tris": np.array([[0, 1, 2], [3, 4, 5]]),
            "J": J, "W": W, "tex": tex, "color": (255, 255, 255, 255), "wrap": (10497, 10497)}
    return write_gltf(path, joints, [prim], joint_names=["hip", "head"])


def test_collect_shows_each_character_as_it_comes_out_of_the_game(tmp_path, monkeypatch):
    import numpy as np
    from PIL import Image
    game = {"game_id": "fixture", "title": "Sonic Adventure (fixture)", "platform": "test"}
    entries = [{"slug": "fx_sonic", "name": "Sonic", "aliases": []}, {"slug": "fx_tikal", "name": "Tikal", "aliases": []},
               {"slug": "fx_sheet", "name": "Sheet", "aliases": []}, {"slug": "fx_broken", "name": "Broken", "aliases": []}]

    def run(ctx, game, e, work):
        if e["slug"] == "fx_broken":
            raise ValueError("corrupt native model")
        if e["slug"] == "fx_sheet":                       # a sprite reader hands over its sheet
            Image.fromarray(np.full((16, 32, 4), 200, np.uint8)).save(work / "sheet.png")
            return {"files": [work / "sheet.png"], "source_files": [], "tool": "fixture"}
        return {"files": [_textured_gltf(work / f"{e['slug']}.gltf")], "source_files": [], "tool": "fixture",
                "roles": {"hip": "hip", "head": "head"}}
    monkeypatch.setattr(C, "DEDICATED", [("fixture", lambda t, p: True, lambda: entries, run)])
    monkeypatch.setattr(C, "_game", lambda ctx, inp: game)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "lib")
    monkeypatch.setattr(C, "render_preview", lambda model, out, **kw: Image.fromarray(
        np.random.default_rng(0).integers(0, 255, (64, 64, 3), np.uint8)).save(out) or out)
    monkeypatch.setattr(C, "verify_entry", lambda root, meta: {"ok": True})
    ctx = SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda *a: None)
    lines, sink = collect()
    ctx.progress = sink
    with FE.job(sink, tmp_path / "snaps"):
        r = C.collect(ctx, C.CharIn(op="collect"))
        again = []                                        # a second collect: entries already in the collection
        ctx.progress = lambda p, m: again.append((p, m))
        with FE.job(ctx.progress, tmp_path / "snaps2"):
            C.collect(ctx, C.CharIn(op="collect"))
    assert r["collected"] == 3
    evs = events(lines)
    assert evs[0]["kind"] == "collect" and [x["model"] for x in evs[0]["plan"]] == [e["slug"] for e in entries]
    assert FE.split(lines[0][1])[0] == "Collecting 4 models"
    for slug in ("fx_sonic", "fx_tikal"):
        assert order(evs, slug) == ["extract", "preview"]
        ex = last(evs, slug, "extract")
        assert ex["data"]["triangles"] == 2 and ex["data"]["roles"] == 2 and ex["data"]["height"] == 2.0
        gl = __import__("tests.test_fit_events", fromlist=["x"]).read_glb(ex["snapshot"])
        assert gl["accessors"][0]["count"] == 6                         # the decoded model, in its own pose
        blob = open(ex["snapshot"], "rb").read()
        js = 20 + __import__("struct").unpack_from("<I", blob, 12)[0]
        col = np.frombuffer(blob[js + 8:], np.float32, 6 * 4, 6 * 12).reshape(6, 4)
        assert np.allclose(col[:, :3], [1, 0, 0])                       # coloured from its texture
        assert last(evs, slug, "preview")["preview"].endswith("preview.png")
    sheet = last(evs, "fx_sheet", "extract")
    assert sheet["data"]["kind"] == "sprites" and sheet["preview"].endswith("sheet.png") and "snapshot" not in sheet
    assert last(evs, "fx_broken", "preview")["state"] == "failed"
    st = None
    for e in evs:
        st = FE.fold(st, e)
    assert st["kind"] == "collect" and [st["models"][e["slug"]]["state"] for e in entries] == \
        ["done", "done", "done", "failed"]
    ev2 = events(again)
    assert last(ev2, "fx_sonic", "extract")["state"] == "skipped" and last(ev2, "fx_sonic", "extract").get("snapshot")
