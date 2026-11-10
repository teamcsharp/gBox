"""Donor fit audit, the persistent reject list, every writer honouring it, and the operator's model swap
(gbox.donor_fit_audit, gbox.donor_rejects, gbox.donor_swap): synthetic receipts, no assets, no emulator."""
import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import donor_fit_audit as A, donor_rejects as R, donor_swap as D, mercmode as M, screensaver as S
from gbox import merc_live_controls as LC
from tests.test_mercmode import boundary, playing, rig


@pytest.fixture
def rejects(tmp_path, monkeypatch):
    path = tmp_path / "donor_rejects.json"
    monkeypatch.setenv(R.ENV, str(path))
    return path


# --- synthetic receipts ------------------------------------------------------------------------------------------

def re4_cast(tmp_path, build="recovery-re4-cast-pool-01-20261110"):
    """The RE4 cast receipt shape (re4_switch_models.cast_pool) with the boxes measured on lilspark (mm)."""
    slots = {"leon": ("pl08", "auf_thug_alpine_inside", [[-1702.98, 0.0, -1177.32], [1585.33, 2479.38, 1913.51]]),
             "hunk": ("pl06", "jgr_char05", [[-960.0, 0.0, -386.0], [960.0, 1860.0, 387.0]]),
             "wesker": ("pl0d", "ff7_vincent_field", [[-39900.0, -20490.0, -29800.0], [39900.0, 26560.0, 29790.0]]),
             "ada": ("pl0b", "djv_ps2_razor_1", [[-650.0, -10.0, -38.0], [650.0, 1610.0, 38.0]]),
             "krauser": ("pl0a", "sc_lizardman", [[-745.0, -800.0, -107.0], [745.0, 1790.0, 107.0]])}
    doc = {"recipe": "re4_switch_models.cast_pool", "name": build, "game_id": "270a15eb98dab4d7",
           "slots": {k: {"pack": pack, "archive": f"010000{pack[2:]}.pack.fen", "donor": {"slug": slug, "name": slug},
                         "fit": {"bbox": box}} for k, (pack, slug, box) in slots.items()},
           "files": [{"path": f"romfs/bio4/em/{pack}.udas", "bytes": 1000 + i} for i, (pack, _s, _b)
                     in enumerate(slots.values())]}
    folder = tmp_path / "re4-cast"
    folder.mkdir()
    (folder / "receipt.json").write_text(json.dumps(doc))
    return folder


def re4_enemies(tmp_path):
    groups = {"em16": [(453, "melee_mewtwo", [[-733, 0, -323], [733, 1746, 63]]),
                       (472, "ff7_cloud_field", [[-16800, -5490, -14000], [16800, 32850, 14134]])],
              "em1c": [(541, "djv_ps2_proof_1", [[-730, 0, -34], [730, 1670, 34]])],
              "em20": [(579, "auf_zero_body", [[-1740, 0, -1200], [1740, 2460, 1202]])]}
    doc = {"recipe": "re4_switch_enemies.enemy_pool", "name": "recovery-re4-enemy-pool-01-20261110",
           "classes": {cls: {"pack": cls, "groups": [{"body": b, "donor": {"slug": s}, "fit": {"bbox": box}}
                                                     for b, s, box in rows]} for cls, rows in groups.items()},
           "files": [{"path": f"romfs/bio4/em/{cls}.udas", "bytes": 5000} for cls in groups]}
    folder = tmp_path / "re4-enemy"
    folder.mkdir()
    (folder / "receipt.json").write_text(json.dumps(doc))
    return folder


def _bounds(w, h, d, floor=0.0):
    return {"min": {"x": -w / 2, "y": floor, "z": -d / 2}, "max": {"x": w / 2, "y": floor + h, "z": d / 2}}


def re5_players(tmp_path, build="build-01"):
    native = _bounds(182.7, 187.6, 49.9)
    slots = {"chris_bsaa": ("Chris (BSAA)", "sm64ds_mario", _bounds(158.2, 186.6, 26.2)),
             "chris_stars": ("Chris (STARS)", "sc_yoshimitsu", _bounds(331.0, 187.0, 70.8)),
             "sheva_bsaa": ("Sheva (BSAA)", "ff7_ballet_field", _bounds(160.0, 186.0, 30.0))}
    doc = {"recipe": "re5_cast_writer", "slots": {
        key: {"slot": {"key": key, "label": label}, "donor": slug, "source": {"slug": slug, "name": slug},
              "fit": {"bounds": box, "native_bounds": native, "native_height": 187.6,
                      "scale": {"body_scale": 2.9, "feet_vertical_scale": {"l_foot": 9.8}}},
              "output": {"path": f"romfs/nativeNXx64/ImgNX/Archive/{key}.arc", "bytes": 40_000_000 + i}}
        for i, (key, (label, slug, box)) in enumerate(slots.items())}}
    folder = tmp_path / build
    folder.mkdir()
    (folder / "receipt-players.json").write_text(json.dumps(doc))
    return folder


def re6_shuffle(tmp_path, build="recovery-re6-roster-shuffle-01-20261110"):
    doc = {"build": build, "title_id": "01002A000CD48000",
           "slots": [{"slot": "leon/c0 (variant 0)", "slot_arc": "uPl00LeonUsa", "wearer": "chris/Omake00",
                      "texsets": [{"arc": "uPlTex0000_0"}]},
                     {"slot": "chris/c1 (Omake00)", "slot_arc": "uPl02ChrisOmake00", "wearer": "jake/Omake00",
                      "texsets": []}],
           "files": {"romfs/nativeNXx64/arc/NX/uPl00LeonUsa.arc": {"bytes": 4934233},
                     "romfs/nativeNXx64/arc/NX/uPlTex0000_0.arc": {"bytes": 8124550},
                     "romfs/nativeNXx64/arc/NX/uPl02ChrisOmake00.arc": {"bytes": 3000000}}}
    folder = tmp_path / build
    folder.mkdir()
    (folder / "receipt.json").write_text(json.dumps(doc))
    return folder


# --- the audit ---------------------------------------------------------------------------------------------------

def test_the_audit_flags_the_measured_re4_misfits_and_passes_a_person(tmp_path):
    rows = A.audit_paths([re4_cast(tmp_path), re4_enemies(tmp_path)])
    verdict = {r["donor"]: (r["verdict"], sorted(f["code"] for f in r["flags"])) for r in rows}
    assert verdict["jgr_char05"] == ("pass", [])
    assert verdict["melee_mewtwo"] == ("pass", [])
    assert {"wide", "deep", "box"} <= set(verdict["auf_thug_alpine_inside"][1])     # 3.3 x 2.5 x 3.1 m
    assert "tall" in verdict["ff7_vincent_field"][1]                                  # ~47 m
    assert verdict["djv_ps2_razor_1"][1] == ["flat"]                                  # 7.6 cm deep
    assert "sinks" in verdict["sc_lizardman"][1]                                      # 0.8 m under the floor
    assert "tall" in verdict["ff7_cloud_field"][1] and verdict["djv_ps2_proof_1"][1] == ["flat"]
    assert {"wide", "deep"} <= set(verdict["auf_zero_body"][1])
    found = A.rejects(rows, now=5)
    assert set(found["re4"]) == {"auf_thug_alpine_inside", "ff7_vincent_field", "djv_ps2_razor_1", "sc_lizardman",
                                 "ff7_cloud_field", "djv_ps2_proof_1", "auf_zero_body"}
    leon = found["re4"]["auf_thug_alpine_inside"]
    assert leon["source"]["by"] == "audit" and leon["source"]["slot"] == "leon"
    assert leon["measurement"]["fitted_m"]["width"] == pytest.approx(3.288, abs=0.01)
    assert "#slots.leon.fit.bbox" in leon["source"]["receipt"]
    table = A.table(rows)
    assert "### RE4" in table and "auf_thug_alpine_inside" in table


def test_re5_native_heights_pass_and_an_extreme_width_is_refused(tmp_path):
    rows = A.audit_paths([re5_players(tmp_path)])
    by = {r["donor"]: r for r in rows}
    assert by["sm64ds_mario"]["verdict"] == "pass" and by["sm64ds_mario"]["label"] == "Chris (BSAA)"
    assert by["sc_yoshimitsu"]["verdict"] == "reject" and [f["code"] for f in by["sc_yoshimitsu"]["flags"]] == ["wide"]
    assert by["sm64ds_mario"]["files"] == [{"path": "romfs/nativeNXx64/ImgNX/Archive/chris_bsaa.arc", "size": 40_000_000}]


def test_watch_flags_are_reported_but_never_rejected():
    row = {"title": "re5", "role": "enemy", "fitted": {"height": 1.85, "width": 1.7, "depth": 0.4, "floor": 0.0},
           "native": {"height": 1.87, "width": 1.82}, "part_spread": 4.9}
    flags = A.judge(row)
    assert [f["code"] for f in flags] == ["parts"] and A.rejecting(flags) == []
    assert A.judge_all([row | {"build": "b", "slot": "uEm14:5", "donor": "melee_luigi", "source": "x"}])[0][
        "verdict"] == "watch"


def test_the_index_follows_live_companions_by_path_and_size_only(tmp_path):
    rows = A.audit_paths([re5_players(tmp_path, "build-01")], names={"build-01": "recovery-series-01-20261110"})
    files = [{"path": f"romfs/nativeNXx64/ImgNX/Archive/{k}.arc", "size": 40_000_000 + i}
             for i, k in enumerate(("chris_bsaa", "chris_stars", "sheva_bsaa"))]
    live = {"recovery-series-01-20261110": {"game_id": "52d15709be0fda1a", "files": files},
            "recovery-series-01-20261110-blueprint": {"game_id": "52d15709be0fda1a",
                                                      "files": files + [{"path": "romfs/stage.arc", "size": 9}]},
            # another series build: the same archive paths, other sizes - not this receipt's donors
            "recovery-series-03-20261110": {"game_id": "52d15709be0fda1a",
                                            "files": [dict(f, size=f["size"] + 7) for f in files]}}
    index = A.index(rows, live)
    assert index["recovery-series-01-20261110"]["players"]["chris_bsaa"]["donor"] == "sm64ds_mario"
    assert index["recovery-series-01-20261110-blueprint"]["players"]["chris_bsaa"]["from"] == \
        "recovery-series-01-20261110"
    assert "recovery-series-03-20261110" not in index


def test_re6_shuffle_slots_are_native_costumes_keyed_without_the_variant_label(tmp_path):
    rows = A.audit_paths([re6_shuffle(tmp_path)])
    assert {r["slot"]: r["donor"] for r in rows} == {"leon/c0": "chris/Omake00", "chris/c1": "jake/Omake00"}
    assert all(r["verdict"] == "pass" and r["native_costume"] for r in rows)
    leon = next(r for r in rows if r["slot"] == "leon/c0")
    assert [f["path"] for f in leon["files"]] == ["romfs/nativeNXx64/arc/NX/uPl00LeonUsa.arc",
                                                  "romfs/nativeNXx64/arc/NX/uPlTex0000_0.arc"]


# --- the reject list ---------------------------------------------------------------------------------------------

def test_reject_list_round_trip_operator_entries_survive_an_audit(rejects):
    assert R.rejected("re4") == {}                                   # no file: an empty list, never an error
    R.add("re4", "ff7_cloud_field", reason="38 m tall", source={"by": "audit"}, codes=["tall"], now=1)
    R.add("re5", "sm64ds_mario", reason="operator: broken", source={"by": "operator", "slot": "chris_bsaa"}, now=2)
    R.add("all", "prop_crate", reason="a crate", source={"by": "audit"}, now=3)
    assert set(R.rejected("re5")) == {"sm64ds_mario", "prop_crate"}
    assert R.is_rejected("52d15709be0fda1a", "sm64ds_mario")        # a game id names its title
    # an audit that no longer flags Mario must not drop the operator's reject
    R.merge({"re5": {"other": {"reason": "x", "source": {"by": "audit"}}}}, None, replace_audit=True)
    doc = R.load()
    assert "sm64ds_mario" in doc["titles"]["re5"] and doc["titles"]["re5"]["sm64ds_mario"]["source"]["by"] == "operator"
    R.add("re5", "sm64ds_mario", reason="again", source={"by": "operator"}, now=4)
    assert R.entry("re5", "sm64ds_mario")["history"][0]["reason"] == "operator: broken"
    assert R.remove("re5", "sm64ds_mario") and not R.is_rejected("re5", "sm64ds_mario")
    with pytest.raises(ValueError):
        R.add("re9", "x", reason="?", source={})


def test_build_index_reads_through_blueprints_and_variants(rejects):
    R.merge({}, {"X": {"title": "re5", "players": {"chris_bsaa": {"donor": "d"}}, "enemies": {}}})
    for name in ("X", "X-blueprint", "X-fix1", "X-fix3-blueprint"):
        assert R.build_index(name)["players"]["chris_bsaa"]["donor"] == "d"
    assert R.build_index("Y") is None


# --- every writer honours it -------------------------------------------------------------------------------------

class Dealt(Exception):
    pass


def _donor(slug, franchise="F"):
    from gbox.re5_donor_pool import Donor
    return Donor(slug=slug, name=slug, game="G", franchise=franchise, platform="p", model=f"{slug}.glb", sha256="0",
                 roles=(("hip", "h"),), roles_from="t", provenance="p")


def test_re4_and_re5_pool_writers_deal_without_the_rejected_donors(monkeypatch, tmp_path, rejects):
    from gbox import re4_switch_enemies, re4_switch_models, re5_cast_writer, re5_donor_pool
    R.add("re4", "bad4", reason="flat", source={"by": "audit"})
    R.add("re5", "bad5", reason="operator", source={"by": "operator"})
    seen = []

    def plan(seed, slots, donors, *, exclude=frozenset(), **kw):
        seen.append(set(exclude))
        raise Dealt
    monkeypatch.setattr(re5_donor_pool, "plan", plan)
    donors = [_donor(s) for s in ("bad4", "bad5", "good")]
    with pytest.raises(Dealt):
        re4_switch_models.cast_pool(tmp_path, tmp_path, tmp_path, donors, 1, tmp_path / "o1")
    with pytest.raises(Dealt):
        re4_switch_enemies.enemy_pool(tmp_path, tmp_path, tmp_path, donors, 1, tmp_path / "o2", classes=())
    with pytest.raises(Dealt):
        re5_cast_writer.pool_cast(tmp_path, tmp_path, donors, 1, tmp_path / "o3")
    assert "bad4" in seen[0] and "bad4" in seen[1] and "bad5" not in seen[0]
    assert "bad5" in seen[2] and "bad4" not in seen[2]
    # a pinned rebuild (a fit fix verified on the same donors) is not refused by the list
    with pytest.raises(Exception) as pinned:
        re4_switch_models.cast_pool(tmp_path, tmp_path, tmp_path, donors, 1, tmp_path / "o4",
                                    assignment={"leon": "bad4"})
    assert not isinstance(pinned.value, Dealt) or "bad4" not in seen[-1]


def test_re5_series_plan_never_deals_a_rejected_donor(tmp_path, rejects, capsys):
    from gbox import re5_cast_series as series
    R.add("re5", "d007", reason="operator", source={"by": "operator"})
    entries = {}
    for i in range(160):
        slug = f"d{i:03d}"
        entries[slug] = {"usable": True, "rig": {"winding": "ccw"},
                         "donor": {"slug": slug, "name": slug, "game": f"G{i % 9}", "franchise": f"F{i % 9}",
                                   "platform": "p", "model": f"{slug}.glb", "sha256": "0", "roles": {"hip": "h"},
                                   "roles_from": "t", "provenance": "p"}}
    survey = tmp_path / "survey.json"
    survey.write_text(json.dumps({"entries": entries}))
    assert series.main(["--romfs", ".", "--archives", ".", "--library", ".", "--survey", str(survey), "--seed", "s",
                        "--out", str(tmp_path / "o"), "--plan-only"]) == 0
    plan = json.loads(capsys.readouterr().out)
    dealt = {slug for build in plan for slug in list(build["players"].values())
             + [s for v in build["enemies"].values() for s in v]}
    assert "d007" not in dealt and len(dealt) == 159


def test_re6_donor_pool_leaves_rejected_library_donors_out(monkeypatch, rejects):
    from gbox import re6_switch_cast
    R.add("re6", "keep_bad", reason="stretched", source={"by": "audit"})
    rig = {"skinned": True, "roles": {role: f"j{i}" for i, role in enumerate(re6_switch_cast.FULL_ROLES)}}
    metas = [{"slug": s, "model": f"{s}.glb", "rig": rig} for s in ("keep_bad", "keep_good")]
    monkeypatch.setattr(re6_switch_cast.C, "list_all", lambda library: metas)
    assert [m["slug"] for m in re6_switch_cast.donor_pool(Path("lib"))] == ["keep_good"]
    assert [m["slug"] for m in re6_switch_cast.donor_pool(Path("lib"), rejects={})] == ["keep_bad", "keep_good"]


# --- mercmode: purpose rounds and superseded builds -----------------------------------------------------------

def test_purpose_entries_validate_play_once_and_do_not_count_toward_the_playlist_limit():
    store, w, *_ = rig()
    with pytest.raises(ValueError, match="purpose"):
        M.normalize({"queue": [{"title": "re5", "purpose": "because"}]})
    playlist = [{"title": "re5", "mod": f"b{i}"} for i in range(M.QUEUE_MAX)]
    swap = {"title": "re5", "mod": "b0-fix1", "purpose": "donor_swap"}
    cfg = M.configure(store, w["name"], {"queue": [swap] + playlist, "repeat_queue": True})
    assert cfg["queue"][0]["purpose"] == "donor_swap" and len(cfg["queue"]) == M.QUEUE_MAX + 1
    M.pop_queue(store, w["name"])                                  # the purpose round played: it is not recycled
    after = M.settings(store, w["name"])["queue"]
    assert after == cfg["queue"][1:] and not any(e.get("purpose") for e in after)
    M.pop_queue(store, w["name"])                                  # a playlist entry is
    assert M.settings(store, w["name"])["queue"][-1] == cfg["queue"][1]


def test_default_mod_follows_the_variant_that_superseded_a_build():
    store, *_ = rig()
    store.put(D.SUPERSEDE, "g", {"X": "X-fix1", "X-fix1": "X-fix2"})
    resolve = M.build_resolver(store, "g")
    assert resolve("X") == "X-fix2" and resolve("Y") == "Y"
    row = {"title": "re5", "game_id": "g", "selection": {"mod": "X"}}
    assert M.default_mod({"blueprint_look": True}, row, resolve)["selection"]["mod"] == "X-fix2-blueprint"
    assert M.default_mod({}, {"title": "re5", "selection": {"mod": "X"}})["selection"]["mod"] == "X"


def _swap_round(store, w, run, title, rounds=5):
    run["mod"] = "series-01"
    store.put(S.STATE, w["name"], run)
    M.configure(store, w["name"], {"titles": [title], "rounds_per_title": rounds,
                                   "queue": [{"title": title, "mod": "series-02"}]})


def test_a_different_build_waits_but_a_purpose_round_plays_at_the_next_boundary():
    store, w, saver, calls, now, tick, run, job = playing()
    title = run["mercmode"]["title"]
    _swap_round(store, w, run, title)
    receipt = boundary(run, now[0]) | {"round_id": "b" * 32}
    assert saver.round_boundary(receipt, job, now[0])["rotate_requested"] is False      # 1 of 5 rounds: it waits
    assert not store.get(S.STATE, w["name"]).get("mercmode_mod_rotate")
    cfg = M.settings(store, w["name"])
    M.configure(store, w["name"], {"queue": [{"title": title, "mod": "series-01-fix1", "purpose": "donor_swap"}]
                                   + cfg["queue"]})
    now[0] += 30
    S.telemetry_put(run["session_id"], {"running": True, "stats": {}}, now=now[0])
    receipt = boundary(run, now[0]) | {"round_id": "c" * 32}
    assert saver.round_boundary(receipt, job, now[0])["rotate_requested"] is True
    state = store.get(S.STATE, w["name"])
    assert state["mercmode_mod_rotate"] and state["mercmode_purpose"] == "donor_swap"
    tick(1)
    assert calls[-1]["input"]["op"] == "stop_game"
    store.put("session", run["session_id"], store.get("session", run["session_id"]) | {"state": "ended"})
    tick(1)
    launch = calls[-1]
    assert launch["tool"] == "launch_game" and launch["input"]["mod"] == "series-01-fix1"
    assert [e["mod"] for e in M.settings(store, w["name"])["queue"]] == ["series-02"]


def test_a_quick_death_does_not_hold_back_a_purpose_round():
    store, w, saver, calls, now, tick, run, job = playing()
    title = run["mercmode"]["title"]
    _swap_round(store, w, run, title)
    M.configure(store, w["name"], {"queue": [{"title": title, "mod": "series-01-fix1", "purpose": "donor_swap"}]})
    receipt = boundary(run, now[0], screen="dead", hp=0, tally_ready=False, timer=60) | {"round_id": "d" * 32}
    assert saver.round_boundary(receipt, job, now[0])["rotate_requested"] is True


def test_the_running_variant_is_the_superseded_build_so_a_playlist_does_not_restart_it():
    store, w, saver, calls, now, tick, run, job = playing()
    title = run["mercmode"]["title"]
    run["mod"] = "series-01-fix1"
    store.put(S.STATE, w["name"], run)
    store.put(D.SUPERSEDE, run["game_id"], {"series-01": "series-01-fix1"})
    M.configure(store, w["name"], {"titles": [title], "repeat_queue": True, "queue": [{"title": title, "mod": "series-01"}]})
    receipt = boundary(run, now[0]) | {"round_id": "e" * 32}
    assert saver.round_boundary(receipt, job, now[0])["rotate_requested"] is False
    assert not store.get(S.STATE, w["name"]).get("mercmode_mod_rotate")


# --- the swap itself ----------------------------------------------------------------------------------------------

INDEX = {"recovery-series-01-20261110": {
    "title": "re5", "game_id": "52d15709be0fda1a",
    "players": {"chris_bsaa": {"donor": "sm64ds_mario", "label": "Chris (BSAA)",
                               "files": [{"path": "romfs/nativeNXx64/ImgNX/Archive/uPl00ChrisNormal.arc", "size": 9}]},
                "sheva_bsaa": {"donor": "ff7_ballet_field", "label": "Sheva (BSAA)",
                               "files": [{"path": "romfs/nativeNXx64/ImgNX/Archive/uPl01ShebaNormal.arc", "size": 9}]}},
    "enemies": {"uEm10": {"donors": ["sc_astaroth", "melee_fox"],
                          "files": [{"path": "romfs/nativeNXx64/ImgNX/Archive/uEm10.arc", "size": 9}]}}}}


def test_plan_finds_the_playing_characters_slot_per_title():
    assert D.player_slots("re5", INDEX["recovery-series-01-20261110"], "Chris (BSAA)") == ["chris_bsaa"]
    assert D.player_slots("re4", {"players": {"leon": {}, "hunk": {}}}, "HUNK") == ["hunk"]
    six = {"players": {"leon/c0": {}, "leon/c2": {}, "ada/c0": {}}}
    assert D.player_slots("re6", six, "Leon", costume=2) == ["leon/c2"]
    assert D.player_slots("re6", six, "Leon") == ["leon/c0", "leon/c2"]
    doc = {"titles": {}, "audited_builds": INDEX}
    swap = D.plan("re5", "recovery-series-01-20261110-blueprint", character="Chris (BSAA)", enemy="melee_fox", doc=doc)
    assert swap["build"] == "recovery-series-01-20261110" and swap["players"][0]["donor"] == "sm64ds_mario"
    assert swap["enemies"] == [{"class": "uEm10", "donors": ["melee_fox"],
                                "files": INDEX["recovery-series-01-20261110"]["enemies"]["uEm10"]["files"]}]
    with pytest.raises(D.SwapError, match="not a donor build"):
        D.plan("re5", "stock-build", character="Chris (BSAA)", doc=doc)
    with pytest.raises(D.SwapError, match="no library donor"):
        D.plan("re5", "recovery-series-01-20261110", character="Josh (BSAA)", doc=doc)


def test_variant_names_continue_the_chain():
    assert D.variant_name("X") == "X-fix1"
    assert D.variant_name("X-blueprint", ["X-fix1", "X-fix2"]) == "X-fix3"
    assert D.variant_name("X-fix3") == "X-fix4" and D.root_of("X-fix3-blueprint") == "X"


def test_the_click_rejects_the_donor_queues_the_job_and_lands_as_the_next_round(rejects):
    store, w, saver, calls, now, tick, run, job = playing()
    R.merge({}, INDEX)
    run = run | {"game_id": "52d15709be0fda1a", "mod": "recovery-series-01-20261110"}
    jobs = []

    def submit(spec):
        jobs.append(spec)
        store.put("job", "j1", {"id": "j1", "state": "queued"})
        return {"id": "j1"}
    record = D.request(store, host=w["name"], worker_id=w["id"], run=run, submit=submit,
                       telemetry={"stats": {"character": "Chris (BSAA)"}}, request_id="r1", now=now[0])
    assert record["state"] == "queued" and record["variant"] == "recovery-series-01-20261110-fix1"
    entry = R.entry("re5", "sm64ds_mario")
    assert entry["source"]["by"] == "operator" and entry["source"]["slot"] == "chris_bsaa"
    spec = jobs[0]
    assert spec["tool"] == "switch_mods" and spec["require_worker"] == w["id"]
    assert spec["input"]["op"] == "donor_variant" and spec["input"]["new_name"] == record["variant"]
    assert "sm64ds_mario" in spec["input"]["changes"]["exclude"]
    assert D.request(store, host=w["name"], worker_id=w["id"], run=run, submit=submit, telemetry={},
                     request_id="r1")["id"] == record["id"]           # the same click again: the same record
    with pytest.raises(D.SwapError, match="already queued"):
        D.request(store, host=w["name"], worker_id=w["id"], run=run, submit=submit, telemetry={}, request_id="r2")
    store.put("job", "j1", {"id": "j1", "state": "running"})
    assert D.status(store, w["name"])["state"] == "building"
    landed = D.accept(store, {"op": "donor_variant", "swap_id": record["id"], "variant": record["variant"],
                              "slots": [{"slot": "chris_bsaa", "old": "sm64ds_mario", "new": "melee_marth"}]})
    assert landed["state"] == "ready" and "plays next round" in landed["message"]
    head = M.settings(store, w["name"])["queue"][0]
    assert head["purpose"] == "donor_swap" and head["mod"] == record["variant"] and head["character"] == "Chris (BSAA)"
    assert D.resolve(store, run["game_id"], "recovery-series-01-20261110") == record["variant"]
    assert D.status(store, w["name"], running_mod=record["variant"] + "-blueprint")["state"] == "playing"
    # the variant has its own index entry: the swapped slot carries the redrawn donor, nothing rejected is left on it
    assert R.build_index(record["variant"])["players"]["chris_bsaa"]["donor"] == "melee_marth"
    assert D.build_rejects(record["variant"]) == []
    assert [r["donor"] for r in D.build_rejects("recovery-series-01-20261110")] == ["sm64ds_mario"]


def test_a_failed_job_is_reported_with_its_reason(rejects):
    store, w, *_ = rig()
    store.put(D.STATE, w["name"], {"id": "s", "state": "queued", "job": "j", "variant": "X-fix1", "host": w["name"]})
    store.put("job", "j", {"id": "j", "state": "failed", "error": "X-fix1 already exists"})
    out = D.status(store, w["name"])
    assert out["state"] == "failed" and "already exists" in out["message"]


def test_the_api_refuses_a_round_that_is_not_a_donor_build(rejects):
    store, w, saver, calls, now, tick, run, job = playing()
    with pytest.raises(ValueError, match="donor build"):                # the rig plays the PS3 / GC editions
        saver.donor_swap(run["session_id"], request_id="r", now=now[0])
    with pytest.raises(ValueError, match="not a MercMode round"):
        saver.donor_swap("nobody", now=now[0])


def test_the_variant_reverts_the_slot_and_copies_the_blueprint_companion(tmp_path):
    from gbox import switch_mods as SM
    cfg = SimpleNamespace(cache=tmp_path)
    gid, tid = "115f9cdbba115432", "01002A000CD48000"
    leon = "romfs/nativeNXx64/arc/NX/uPl00LeonUsa.arc"
    other = "romfs/nativeNXx64/arc/NX/uPl02ChrisAsia.arc"
    for name, extra in (("shuffle", {}), ("shuffle-blueprint", {"romfs/stage.arc": b"grey"})):
        SM.write_files(cfg, gid, name, {leon: {"bytes": b"chris"}, other: {"bytes": b"jake"},
                                        **{k: {"bytes": v} for k, v in extra.items()}},
                       create={"title_id": tid})
    spec = {"title": "re6", "swap_id": "s1", "players": [{"slot": "leon/c0", "donor": "chris/Omake00",
                                                          "files": [{"path": leon, "size": 5}]}]}
    out = D.build_variant(cfg, gid, "shuffle", "shuffle-fix1", spec, log=lambda *_: None)
    assert out["variant"] == "shuffle-fix1" and out["blueprint"] == "shuffle-fix1-blueprint"
    assert out["slots"][0]["how"] == "native" and "native" in out["slots"][0]["why"]
    fix = {f["path"] for f in SM.overlay_files(SM.build_dir(cfg, gid, "shuffle-fix1"))}
    assert fix == {other}
    blue = {f["path"] for f in SM.overlay_files(SM.build_dir(cfg, gid, "shuffle-fix1-blueprint"))}
    assert blue == {other, "romfs/stage.arc"}
    source = {f["path"] for f in SM.overlay_files(SM.build_dir(cfg, gid, "shuffle"))}
    assert source == {leon, other}                                      # the source build is never written
    with pytest.raises(ValueError, match="never overwritten"):
        D.build_variant(cfg, gid, "shuffle", "shuffle-fix1", spec, log=lambda *_: None)


def test_the_redraw_takes_the_next_donor_that_passes_and_records_the_misfits(tmp_path, monkeypatch, rejects):
    from gbox import re5_cast_writer as P, skin_swap, switch_mods as SM
    cfg = SimpleNamespace(cache=tmp_path)
    gid, tid = "52d15709be0fda1a", "010018100CD46000"
    path = "romfs/" + P.SLOTS["chris_bsaa"].archive
    SM.write_files(cfg, gid, "series", {path: {"bytes": b"mario"}}, create={"title_id": tid})
    romfs = tmp_path / "romfs-original"
    (romfs / P.SLOTS["chris_bsaa"].archive).parent.mkdir(parents=True)
    (romfs / P.SLOTS["chris_bsaa"].archive).write_bytes(b"native")
    monkeypatch.setattr(skin_swap, "romfs_root", lambda title_id: romfs)
    (tmp_path / "characters").mkdir()
    order = ["rejected_one", "taken_one", "wide_one", "good_one"]
    monkeypatch.setattr(D, "_candidates", lambda library, exclude, seed: [s for s in order if s not in exclude])
    monkeypatch.setattr(P, "donor_from", lambda library, slug: SimpleNamespace(slug=slug, model="m.glb"))

    def build(original, source, donor):
        assert original == b"native"
        width = 400.0 if donor.slug == "wide_one" else 160.0
        return b"built-" + donor.slug.encode(), {"slot": {"label": "Chris (BSAA)"}, "fit": {
            "bounds": _bounds(width, 187.0, 30.0), "native_bounds": _bounds(182.7, 187.6, 49.9), "native_height": 187.6}}
    monkeypatch.setattr(P, "build", build)
    spec = {"title": "re5", "swap_id": "s", "exclude": {"rejected_one": "x"}, "taken": ["taken_one"],
            "players": [{"slot": "chris_bsaa", "donor": "sm64ds_mario", "label": "Chris (BSAA)",
                         "files": [{"path": path, "size": 5}]}]}
    out = D.build_variant(cfg, gid, "series", "series-fix1", spec, log=lambda *_: None)
    assert out["slots"][0] | {"tried": None} == {"slot": "chris_bsaa", "old": "sm64ds_mario", "new": "good_one",
                                                 "how": "redrawn", "tried": None}
    assert [r["donor"] for r in out["rejected_during"]] == ["wide_one"]
    assert (SM.build_dir(cfg, gid, "series-fix1") / path).read_bytes() == b"built-good_one"
    assert (SM.build_dir(cfg, gid, "series") / path).read_bytes() == b"mario"
    D.record_redraw_rejects(out | {"game_id": gid})
    assert R.entry("re5", "wide_one")["codes"] == ["wide"] and R.entry("re5", "wide_one")["source"]["by"] == "audit"


def test_switch_mods_accept_routes_the_variant_result(monkeypatch):
    from gbox import switch_mods as SM
    got = []
    monkeypatch.setattr(D, "accept", lambda store, r: got.append(r))
    monkeypatch.setattr(D, "record_redraw_rejects", lambda r: None)
    SM._accept(object(), SM.SwitchModsOut(result={"op": "donor_variant", "swap_id": "s", "variant": "v"}), "a")
    assert got and got[0]["variant"] == "v"


# --- the live-controls facade ------------------------------------------------------------------------------------

class Plane:
    def __init__(self):
        self.posts = []
        self.swap = {"id": "s", "state": "queued", "message": "queued"}

    async def get(self, path, **kw):
        if path == "/api/sessions":
            return [{"session_id": "pc-1", "state": "running", "game_id": "52d15709be0fda1a", "adapter": "rpcs3",
                     "title": "RE5"}]
        if path == "/api/mercmode":
            return {"hosts": [{"id": "pc", "online": True, "donor_swap": self.swap,
                               "current_run": {"session_id": "pc-1", "game_id": "52d15709be0fda1a",
                                               "phase": "playing"}}]}
        if path.endswith("/interventions"):
            return {"available": False, "capabilities": []}
        raise AssertionError(path)

    async def post(self, path, body):
        self.posts.append((path, body))
        return {"swap": self.swap | {"request_id": body["request_id"]}}


def test_live_controls_model_swap_posts_one_request_and_reports_its_state():
    async def check():
        plane = Plane()
        controls = LC.Controls(plane.get, plane.post)
        with pytest.raises(ValueError, match="UUID"):
            await controls.call({"session_id": "pc-1", "op": "model_swap", "request_id": "x"})
        rid = str(uuid.uuid4())
        out = await controls.call({"session_id": "pc-1", "op": "model_swap", "request_id": rid, "enemy": "uEm10"})
        assert plane.posts == [("/api/sessions/pc-1/donor-swap", {"request_id": rid, "enemy": "uEm10"})]
        assert out["action"]["state"] == "queued" and out["model_swap"]["request_id"] == rid
        status = await controls.call({"session_id": "pc-1"})
        assert status["model_swap"]["state"] == "queued"
    asyncio.run(check())


# --- frames (report only) ----------------------------------------------------------------------------------------

def test_camera_filled_spots_one_surface_over_the_view_not_a_scene_or_a_black_frame():
    rng = np.random.default_rng(1)
    scene = rng.integers(0, 255, (180, 320, 3), dtype=np.uint8)
    wall = np.full((180, 320, 3), (140, 90, 60), dtype=np.uint8)
    wall[:20] = scene[:20]                                      # the HUD strip stays the game's
    black = np.zeros((180, 320, 3), dtype=np.uint8)
    assert D.camera_filled(wall)["filled"] is True
    assert D.camera_filled(scene)["filled"] is False
    assert D.camera_filled(black)["filled"] is False and D.camera_filled(black)["dark"] is True
