"""RE6 cast roster: assign a collection character to every native player slot and let the round rotation show them.

The roster build is exercised with a stub writer (no game disc); the round mapping is checked against RE6's own select
ids, which is what `gbox.mercs.round_controls.Controls.choose_character` walks each round.
"""
import json
from types import SimpleNamespace

import pytest

from gbox import re6_cast as R, re6_tool as T


def entry(slug, roles=None):
    return {"slug": slug, "name": slug.title(),
            "rig": {"roles": {r: f"b{i}" for i, r in enumerate(roles or
                              ("hip", "chest", "neck", "head", "l_upper", "l_fore", "l_hand", "r_upper",
                               "r_fore", "r_hand", "l_thigh", "l_shin", "l_foot", "r_thigh", "r_shin", "r_foot"))}}}


CAST = [entry(s) for s in ("mario", "sonic", "link", "kirby", "samus", "snake", "pikachu", "ness", "captain_falcon")]


def ctx(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(cache=tmp_path), progress=lambda *a: None,
                           artifact=lambda *a, **kw: None)


def test_the_roster_assigns_one_distinct_character_per_native_slot():
    assignment = R.plan(CAST, seed=7)
    assert set(assignment) == set(R.TARGETS)
    assert len({m["slug"] for m in assignment.values()}) == len(R.TARGETS)


def test_the_plan_is_deterministic_for_a_seed_and_varies_between_seeds():
    first = {t: m["slug"] for t, m in R.plan(CAST, seed=1).items()}
    assert first == {t: m["slug"] for t, m in R.plan(CAST, seed=1).items()}
    assert first != {t: m["slug"] for t, m in R.plan(CAST, seed=2).items()}


def test_a_short_cast_is_reused_in_order():
    assignment = R.plan([entry("sonic"), entry("mario")], seed=0)
    assert len({m["slug"] for m in assignment.values()}) == 2


def test_entries_without_body_roles_are_not_cast():
    weak = {"slug": "statue", "name": "Statue", "rig": {"roles": {"hip": "a"}}}
    with pytest.raises(R.CastError):
        R.plan([weak])


def test_the_rotation_maps_re6_select_ids_to_the_cast():
    assignment = R.plan(CAST, seed=3)
    rows = R.rotation(assignment)
    assert [r["select_id"] for r in rows] == list(range(7))
    assert [r["native"] for r in rows] == list(R.TARGETS)
    assert rows[0]["cast"] == assignment["leon"]["slug"]
    assert R.current(assignment, 2)["native"] == "chris"
    assert R.current(assignment, 9) is None


def test_an_explicit_cast_list_keeps_its_slots_and_fills_the_rest():
    assignment = R.plan_from_slugs(CAST, ["sonic", "mario"], seed=5)
    assert assignment["leon"]["slug"] == "sonic" and assignment["helena"]["slug"] == "mario"
    assert len({m["slug"] for m in assignment.values()}) == 7
    with pytest.raises(R.CastError, match="not in the collection"):
        R.plan_from_slugs(CAST, ["goku"])


def test_a_per_costume_plan_covers_every_costume_with_a_different_character():
    from gbox import re6_models as M
    assignment = R.plan_per_costume(CAST, seed=2)
    rows = R.costume_rotation(assignment)
    pairs = {(target, c) for target in R.TARGETS for c in M.CHARACTERS[target]["costumes"]}
    assert len(rows) == len(pairs) >= 40
    assert {(r["native"], r["costume"]) for r in rows} == pairs
    by_target = R.rotation(assignment)
    assert all("costumes" in row for row in by_target)


def test_build_accepts_per_costume_assignments_and_records_every_character(tmp_path, monkeypatch):
    assignment = R.plan_per_costume(CAST, seed=4)
    calls, written = [], []
    monkeypatch.setattr(T, "fetch_model", lambda ctx, meta: tmp_path / f"{meta['slug']}.glb")

    def swap(base, model, roles, target, costume, slug, preview=None, scale=None):
        calls.append((target, costume, slug))
        return {"files": {f"{target}-{costume}.arc": b"x"}, "triangles": 1, "vertices": 1,
                "pose_mode": (scale or {}).get("pose"), "fit": {"fitted_height": 180.0}, "notes": []}

    monkeypatch.setattr("gbox.re6_models.build_swap", swap)
    monkeypatch.setattr(T, "build_mod_folder", lambda cfg, name, files, meta: written.append(meta) or {"mod": name})
    out = R.build(ctx(tmp_path), tmp_path, assignment)
    assert len(calls) == len(out["costume_rotation"])
    assert len({c[2] for c in calls}) == len({r["cast"] for r in out["costume_rotation"]})
    meta = written[0]
    assert set(meta["assignment"]["leon"]) == set(__import__("gbox.re6_models", fromlist=["x"])
                                                  .CHARACTERS["leon"]["costumes"])
    assert meta["characters"]["leon"] == {c: m["slug"] for c, m in assignment["leon"].items()}
    assert out["characters"] >= 7


def test_build_merges_every_slot_into_one_mod_and_records_the_rotation(tmp_path, monkeypatch):
    assignment = R.plan(CAST, seed=11)
    calls, written = [], []
    monkeypatch.setattr(T, "fetch_model", lambda ctx, meta: tmp_path / f"{meta['slug']}.glb")

    def swap(base, model, roles, target, costume, slug, preview=None, scale=None):
        calls.append((target, costume, slug, dict(scale or {})))
        return {"files": {f"{target}-{costume}.arc": b"x"}, "triangles": 2, "vertices": 3,
                "pose_mode": (scale or {}).get("pose"), "fit": {"fitted_height": 180.0, "proportion_error": 0.0},
                "notes": []}

    monkeypatch.setattr("gbox.re6_models.build_swap", swap)
    monkeypatch.setattr(T, "build_mod_folder", lambda cfg, name, files, meta: written.append((name, files, meta))
                        or {"mod": name})
    out = R.build(ctx(tmp_path), tmp_path, assignment, progress=lambda *a: None)
    assert out["mod"] == R.DEFAULT_NAME and out["files"] == len(calls)
    assert len({c[0] for c in calls}) == 7
    assert all(c[3] == {"pose": "source_proportions", "height": 180.0} for c in calls)
    name, files, meta = written[0]
    assert name == R.DEFAULT_NAME and len(files) == len(calls)
    assert meta["kind"] == "cast_roster"
    assert {row["native"] for row in meta["rotation"]} == set(R.TARGETS)
    assert [row["select_id"] for row in meta["rotation"]] == list(range(7))


def test_cast_plan_reports_the_rotation_without_building(tmp_path, monkeypatch):
    monkeypatch.setattr("gbox.characters._api", lambda *a, **kw: CAST)
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast_plan", cast=["sonic"], seed=1, name="", pose="",
                                                    height=180.0, launch=False))
    assert res["mod"] == R.DEFAULT_NAME
    assert res["rotation"][0]["cast"] == "sonic"
    assert "as leon" in res["description"]


def test_cast_plan_can_cover_every_costume(tmp_path, monkeypatch):
    monkeypatch.setattr("gbox.characters._api", lambda *a, **kw: CAST)
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast_plan", cast=[], seed=3, name="", pose="", height=180.0,
                                                   launch=False, per_costume=True))
    assert res["per_costume"] is True
    assert len(res["costume_rotation"]) >= 40
    assert res["characters"] == len({row["cast"] for row in res["costume_rotation"]})
    assert set(res["assignment"]) == set(R.TARGETS) and isinstance(res["assignment"]["leon"], dict)


def test_cast_status_reports_a_missing_roster(tmp_path):
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast_status", name="nope"))
    assert res["installed"] is False and "build it" in res["message"]


def test_cast_status_reads_an_installed_roster(tmp_path):
    d = tmp_path / "mods" / "0871eee3b68cdea3" / "re6_smash_roster"
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text(json.dumps({"assignment": {"leon": {"slug": "sonic"}},
                                                  "rotation": [{"select_id": 0, "native": "leon", "cast": "sonic"}]}))
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast_status", name=""))
    assert res["installed"] is True and res["assignment"]["leon"]["slug"] == "sonic"


def test_cast_launches_the_roster_when_asked(tmp_path, monkeypatch):
    monkeypatch.setattr("gbox.characters._api", lambda *a, **kw: CAST)
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    monkeypatch.setattr(R, "build", lambda *a, **kw: {"mod": R.DEFAULT_NAME, "slots": [], "files": 0,
                                                      "rotation": [], "build": {}})
    launched = []
    monkeypatch.setattr(T, "_launch_mod", lambda ctx, gid, name, inp: launched.append((gid, name))
                        or {"launched": True})
    monkeypatch.setattr("gbox.characters.HOST_OS", "windows")
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast", cast=[], seed=0, name="", pose="", height=180.0,
                                                   launch=True))
    assert launched and launched[0][1] == R.DEFAULT_NAME and res["launched"] is True


def test_cast_can_set_the_pcs_mercmode_default_build(tmp_path, monkeypatch):
    calls = []

    def api(ctx, method, path, **kw):
        calls.append((method, path, kw.get("json")))
        return CAST if (method, path) == ("GET", "/api/characters") else {"ok": True}

    monkeypatch.setattr("gbox.characters._api", api)
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    monkeypatch.setattr(R, "build", lambda *a, **kw: {"mod": R.DEFAULT_NAME, "slots": [], "files": 0,
                                                      "rotation": [], "build": {}})
    monkeypatch.setattr("gbox.characters.HOST_OS", "windows")
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast", cast=[], seed=0, name="", pose="", height=180.0,
                                                   launch=False, host="lilspark", mercmode_default=True))
    assert res["mercmode"]["applied_to"] == "lilspark"
    post = next(c for c in calls if c[0] == "POST" and c[1] == "/api/mercmode")
    assert post[2] == {"host": "lilspark", "default_mods": {"re6": R.DEFAULT_NAME}}


def test_cast_reports_the_setting_without_a_host(tmp_path, monkeypatch):
    monkeypatch.setattr("gbox.characters._api", lambda *a, **kw: CAST)
    monkeypatch.setattr(T, "base", lambda *a: tmp_path)
    monkeypatch.setattr(R, "build", lambda *a, **kw: {"mod": R.DEFAULT_NAME, "slots": [], "files": 0,
                                                      "rotation": [], "build": {}})
    monkeypatch.setattr("gbox.characters.HOST_OS", "windows")
    res = T.cast_op(ctx(tmp_path), SimpleNamespace(op="cast", cast=[], seed=0, name="", pose="", height=180.0,
                                                   launch=False))
    assert res["mercmode"]["default_mods"] == {"re6": R.DEFAULT_NAME} and "applied_to" not in res["mercmode"]
