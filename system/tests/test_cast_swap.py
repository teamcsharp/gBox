"""Whole-cast swap (gbox.cast_swap): slot enumeration per writer, donor selection (groups, titles, costume dedupe,
the retarget check, stale readers re-extracted), deterministic mappings, the chained multi-slot path with fake
writers, one-mod builds with per-slot reports, the PSO pairs build on synthetic enemy packs (no disc, Blender or
emulator), and the agent / mashup routing of "replace everyone in PSO with wrestlers"."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import cast_swap as CS, characters as C, mashup, pso_enemy as PE

PSO = {"game_id": "daba7a3b195dcf6b", "title": "Phantasy Star Online Ver. 2 (USA)", "platform": "dreamcast"}
JGR = {"game_id": "4187aeab4d67638c", "title": "Jet Grind Radio (USA)", "platform": "dreamcast"}
CT = {"game_id": next(iter(__import__("gbox.crazy_taxi_swap", fromlist=["x"]).GAME_IDS)), "title": "Crazy Taxi (USA)",
      "platform": "gamecube"}
DJV = {"game_id": "deabd11481aa5a0c", "title": "Def Jam - Vendetta (USA)", "platform": "ps2"}
DOA2 = {"game_id": next(iter(__import__("gbox.doa2_swap", fromlist=["x"]).GAME_IDS)), "title": "Dead or Alive 2",
        "platform": "dreamcast"}
ROLES = {"hip": "j0", "chest": "j1", "head": "j2"}


def entry(slug, name, title, platform, roles=ROLES, **kw):
    return {"slug": slug, "name": name, "kind": "character", "model": f"{slug}.glb", "aliases": kw.pop("aliases", []),
            "rig": {"roles": roles} if roles is not None else {}, "stats": {"triangles": 100, "textures": 1},
            "source": {"game_title": title, "game_id": kw.pop("gid", slug[:3] + "0" * 13), "platform": platform}, **kw}


DJ = ("Def Jam - Vendetta (USA)", "ps2")
SD2 = ("WWF SmackDown! 2 - Know Your Role (USA)", "psx")
JG = ("Jet Grind Radio (USA)", "dreamcast")
CHARS = [
    entry("djv_ps2_briggs_1", "Briggs (costume 1) (Def Jam Vendetta PS2)", *DJ, gid="deabd11481aa5a0c"),
    entry("djv_ps2_briggs_2", "Briggs (costume 2) (Def Jam Vendetta PS2)", *DJ, gid="deabd11481aa5a0c"),
    entry("djv_ps2_dmx", "DMX (Def Jam Vendetta PS2)", *DJ, gid="deabd11481aa5a0c"),
    entry("djv_ps2_moses", "Moses (Def Jam Vendetta PS2)", *DJ, gid="deabd11481aa5a0c"),
    entry("djv_ps2_unmapped", "Deebo (Def Jam Vendetta PS2)", *DJ, gid="deabd11481aa5a0c", roles=None),
    entry("sd2_the_rock", "The Rock", *SD2, gid="276334ad218ffb46"),
    entry("sd2_kane", "Kane", *SD2, gid="276334ad218ffb46"),
    entry("jgr_char04", "Beat (JGR ereki, ID 0)", *JG, gid="4187aeab4d67638c", extraction_tool="gbox.jgr + gbox.ninja",
          jgr_reader=2),
    entry("jgr_char06", "Gum (JGR gum, ID 1)", *JG, gid="4187aeab4d67638c", extraction_tool="gbox.jgr + gbox.ninja"),
    entry("sonic", "Sonic", "Sonic Adventure 2 (USA)", "dreamcast", gid="5a20000000000000"),
    entry("sonic_bighead", "Sonic - big head", "Sonic Adventure 2 (USA)", "dreamcast", variant_of="sonic"),
]


# ---------------------------------------------------------------- slots

def test_pso_slots_drop_aggregates_and_keep_the_player_with_its_status():
    rows = CS.slot_rows(PSO)
    slots = [r["slot"] for r in rows]
    assert slots[0] == "player" and rows[0]["status"] == "not_working"
    assert {"enemy:booma", "enemy:gobooma", "enemy:gigobooma", "enemy:bm2_moja", "enemy:df2_bringer"} <= set(slots)
    assert "enemy:boomas" not in slots and "enemies" not in slots
    assert len(slots) == len(set(slots))
    big = {r["slot"]: r["size"] for r in rows if r.get("size")}
    assert big["enemy:gigobooma"] > big["enemy:booma"] > big["enemy:lappy"]
    assert [r["slot"] for r in CS.filter_slots(rows, "enemies")] == slots[1:]
    assert [r["slot"] for r in CS.filter_slots(rows, "main")] == ["player"]
    assert [r["slot"] for r in CS.filter_slots(rows, "enemy:booma, enemy:lappy")] == ["enemy:booma", "enemy:lappy"]
    with pytest.raises(ValueError, match="matches none"):
        CS.filter_slots(rows, "enemy:nope")


def test_jgr_crazy_taxi_defjam_doa2_slots_list_every_model_once():
    jgr = [r["slot"] for r in CS.slot_rows(JGR)]
    assert len(jgr) == 16 and "player" not in jgr and "character:beat" in jgr       # player is Beat's alias
    ct = CS.slot_rows(CT)
    assert {r["slot"] for r in ct} >= {"driver:axel", "driver:bd_joe", "driver:gena", "driver:gus"}
    assert not {"player", "drivers", "pedestrians", "passengers"} & {r["slot"] for r in ct}
    assert {r["kind"] for r in ct} == {"driver", "pedestrian", "passenger"}
    dj = CS.slot_rows(DJV)
    names = [r["slot"] for r in dj]
    assert "player" not in names and len(names) == len(set(names)) and {"Briggs", "DMX", "Method Man"} <= set(names)
    assert next(r for r in dj if r["slot"] == "Briggs")["costumes"] == 3
    doa = CS.slot_rows(DOA2)
    assert len(doa) == 14 and all(r["slot"].startswith("fighter:") and r["kind"] == "fighter" for r in doa)


# ---------------------------------------------------------------- donors

def test_source_groups_titles_ids_and_extractors():
    w = CS.resolve_source("wrestlers", CHARS)
    assert {m["slug"] for m in w["entries"]} == {"djv_ps2_briggs_1", "djv_ps2_briggs_2", "djv_ps2_dmx", "djv_ps2_moses",
                                                  "djv_ps2_unmapped", "sd2_the_rock", "sd2_kane"}
    assert "Wrestlers" in w["label"]
    assert {m["slug"] for m in CS.resolve_source("JGR", CHARS)["entries"]} == {"jgr_char04", "jgr_char06"}
    assert {m["slug"] for m in CS.resolve_source("Jet Grind Radio", CHARS)["entries"]} == {"jgr_char04", "jgr_char06"}
    assert {m["slug"] for m in CS.resolve_source("276334ad218ffb46", CHARS)["entries"]} == {"sd2_the_rock", "sd2_kane"}
    assert {m["slug"] for m in CS.resolve_source("smackdown2", CHARS)["entries"]} == {"sd2_the_rock", "sd2_kane"}
    both = CS.resolve_source("SA2, JGR", CHARS)["entries"]
    assert {m["slug"] for m in both} == {"sonic", "jgr_char04", "jgr_char06"}               # the big-head variant is out
    with pytest.raises(ValueError, match="sources: Wrestlers"):
        CS.resolve_source("Final Fantasy XII", CHARS)
    menu = CS.source_groups(CHARS)
    assert menu[0]["key"] == "wrestlers" and menu[0]["count"] == 6                         # Briggs' costumes count once
    assert any(g["label"] == "Jet Grind Radio (USA)" and g["count"] == 2 for g in menu)


def test_costumes_dedupe_onto_one_donor():
    keep, dropped = CS.dedupe(CS.resolve_source("wrestlers", CHARS)["entries"])
    assert "djv_ps2_briggs_1" in {m["slug"] for m in keep} and "djv_ps2_briggs_2" not in {m["slug"] for m in keep}
    assert dropped == [{"slug": "djv_ps2_briggs_2", "name": "Briggs (costume 2) (Def Jam Vendetta PS2)",
                        "costume_of": "djv_ps2_briggs_1"}]


def test_gate_refuses_unmapped_donors_with_the_reason():
    donors, refused, refreshed = CS.gate([m for m in CHARS if m["slug"].startswith("djv")])
    assert "djv_ps2_unmapped" not in {d["slug"] for d in donors}
    why = next(r for r in refused if r["slug"] == "djv_ps2_unmapped")["reason"]
    assert "no body roles" in why and refreshed == []


def test_gate_runs_the_collection_check_when_the_library_is_here(tmp_path):
    m = entry("broken", "Broken", *SD2)
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "meta.json").write_text(json.dumps(m))
    assert "no model file" in CS.retarget_check(m, tmp_path)


def test_stale_jgr_donor_is_re_extracted_before_building():
    v1, v2 = CHARS[8], CHARS[7]
    assert C.reader_status(v1) == {"extractor": "jgr", "entry": 1, "current": 2, "stale": True}
    assert C.reader_status(v2)["stale"] is False and C.reader_status(CHARS[0]) is None
    calls = []

    def refresh(meta):
        calls.append(meta["slug"])
        return meta | {"jgr_reader": 2}
    donors, refused, refreshed = CS.gate([v1, v2], refresh=refresh)
    assert calls == ["jgr_char06"] and [d["slug"] for d in donors] == ["jgr_char06", "jgr_char04"]
    assert refreshed[0]["slug"] == "jgr_char06" and "v2" in refreshed[0]["status"] and not refused
    donors, refused, _ = CS.gate([v1], refresh=lambda m: (_ for _ in ()).throw(RuntimeError("disc unreadable")))
    assert not donors and "re-extraction (reader v1 -> v2) failed: disc unreadable" in refused[0]["reason"]
    donors, refused, _ = CS.gate([v1])                                # planning: no refresh -> flagged as stale
    assert not donors and refused[0]["stale"] and "re-extract" in refused[0]["reason"]


def test_refresher_reruns_the_source_games_dedicated_reader(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: seen.setdefault("api", p) and JGR)
    monkeypatch.setattr(C, "extract_dedicated", lambda ctx, g, what, root: seen.update(game=g, what=what) or
                        {"status": "extracted", "entry": {"slug": what}})
    monkeypatch.setattr(C, "get", lambda root, slug: CHARS[8] | {"jgr_reader": 2})
    new = CS._refresher(SimpleNamespace(), tmp_path)(CHARS[8])
    assert seen == {"api": "/api/catalog/4187aeab4d67638c", "game": JGR, "what": "jgr_char06"}
    assert new["jgr_reader"] == 2 and new["preview_url"] == "/api/characters/jgr_char06/preview"


def test_extract_dedicated_flags_a_v1_jgr_entry_for_refresh():
    assert C.reader_status(CHARS[8], "jgr")["stale"] and not C.reader_status(CHARS[7], "jgr")["stale"]
    not_jgr = CHARS[8] | {"extraction_tool": "scene_capture"}                       # a frame cut is never re-read
    assert C.reader_status(not_jgr, "jgr")["stale"] is False


# ---------------------------------------------------------------- mapping

def donors(n, sizes=None, lead=()):
    return [{"slug": f"d{i}", "name": f"D{i}", "size": (sizes or {}).get(i), "lead": i in lead} for i in range(n)]


def slots(n, sizes=None, player=False):
    out = [{"slot": "player", "name": "player", "kind": "player"}] if player else []
    return out + [{"slot": f"s{i}", "name": f"S{i}", "kind": "enemy", "size": (sizes or {}).get(i)} for i in range(n)]


def test_mapping_is_deterministic_per_seed_and_uses_every_donor_before_repeating():
    a = CS.assign(slots(10), donors(4), "random", "x")
    assert a == CS.assign(slots(10), donors(4), "random", "x")
    assert [r["character"] for r in a] != [r["character"] for r in CS.assign(slots(10), donors(4), "random", "y")]
    first = [r["character"] for r in a[:4]]
    assert sorted(first) == ["d0", "d1", "d2", "d3"]                     # one full round before any repeat
    assert sorted(r["character"] for r in a[4:8]) == ["d0", "d1", "d2", "d3"]
    b = CS.assign(slots(3), donors(8), "by_role", "x")
    assert len({r["character"] for r in b}) == 3 and b == CS.assign(slots(3), donors(8), "by_role", "x")
    with pytest.raises(ValueError, match="mapping"):
        CS.assign(slots(1), donors(1), "alphabetical")


def test_by_role_puts_the_lead_on_the_player_and_big_donors_on_big_slots():
    s = slots(3, {0: 0.6, 1: 1.7, 2: 1.0}, player=True)
    d = donors(4, {0: 0.8, 1: 1.3, 2: 1.0, 3: 1.1}, lead=(2,))
    got = {r["slot"]: r["character"] for r in CS.assign(s, d, "auto", "")}
    assert got == {"player": "d2", "s1": "d1", "s2": "d3", "s0": "d0"}
    rows = CS.assign(s, d, "by_role", "")
    assert [r["slot"] for r in rows] == ["player", "s0", "s1", "s2"]                 # the target's own slot order
    assert rows[0]["why"] == "lead character on the player slot" and "body size" in rows[2]["why"]


def test_skipped_slots_get_no_donor_and_edits_override_the_plan():
    s = slots(2, player=True)
    s[0]["skip"] = "not drawn"
    plan = CS.assign(s, donors(3), "random", "1")
    assert [r["slot"] for r in plan] == ["s0", "s1"]
    d = donors(3)
    edited = CS.apply_edits(plan, [{"slot": "s0", "character": "d2"}, {"slot": "s1", "character": ""}], d, s[1:])
    assert [(r["slot"], r["character"], r["why"]) for r in edited] == [("s0", "d2", "edited")]
    with pytest.raises(ValueError, match="not an eligible donor"):
        CS.apply_edits(plan, [{"slot": "s0", "character": "zz"}], d, s[1:])


def test_plan_pso_cast_as_wrestlers_without_the_library():
    p = CS.plan(PSO, CHARS, "wrestlers", "by_role", "7")
    assert p["status"] == "planned" and p["writer"] == "gbox.pso_player" and p["strategy"] == "pairs"
    assert p["skipped"][0]["slot"] == "player" and "not_working" in p["skipped"][0]["reason"]
    assert {r["slot"] for r in p["assignments"]} == {s["slot"] for s in p["slots"] if not s.get("skip")}
    used = {r["character"] for r in p["assignments"]}
    assert used == {"djv_ps2_briggs_1", "djv_ps2_dmx", "djv_ps2_moses", "sd2_the_rock", "sd2_kane"}
    assert [r["slug"] for r in p["refused"]] == ["djv_ps2_unmapped"] and p["costumes_merged"][0]["slug"] == "djv_ps2_briggs_2"
    assert p["mod"].startswith("cast_phantasy_star_onli_wrestlers_no_mercy_")
    assert p == CS.plan(PSO, CHARS, "wrestlers", "by_role", "7")
    enemies = CS.plan(PSO, CHARS, "JGR", slots="enemy:booma,enemy:gigobooma")
    assert [r["slot"] for r in enemies["assignments"]] == ["enemy:booma", "enemy:gigobooma"]
    stale = next(d for d in enemies["donors"] if d["slug"] == "jgr_char06")         # planned, re-extracted at build
    assert stale["stale"] and "will be re-extracted" in enemies["refreshed"][0]["status"]


def test_the_reviewed_plan_is_what_builds_even_after_re_extraction():
    shown = CS.plan(JGR, CHARS, "JGR", "random", "s")                       # plan_only: Gum flagged as stale
    built = CS.plan(JGR, CHARS, "JGR", "random", "s", refresh=lambda m: m | {"jgr_reader": 2})
    assert [r["slug"] for r in shown["donors"]] == [r["slug"] for r in built["donors"]]
    assert shown["assignments"] == built["assignments"]
    rows = [{"slot": r["slot"], "character": r["character"]} for r in shown["assignments"]]
    pinned = CS.plan(JGR, CHARS, "JGR", "random", "other seed", assignments=rows,
                     refresh=lambda m: m | {"jgr_reader": 2})
    assert [(r["slot"], r["character"]) for r in pinned["assignments"]] == [(r["slot"], r["character"]) for r in rows]
    gum = next(r for r in rows if r["character"] == "jgr_char06")
    failed = CS.plan(JGR, CHARS, "JGR", "random", "s", assignments=rows,
                     refresh=lambda m: (_ for _ in ()).throw(RuntimeError("disc unreadable")))
    assert gum["slot"] not in {r["slot"] for r in failed["assignments"]}
    assert any(s["slot"] == gum["slot"] and "disc unreadable" in s["reason"] for s in failed["skipped"])


def test_plan_for_a_game_without_a_writer_is_unsupported():
    p = CS.plan({"game_id": "f" * 16, "title": "Shenmue", "platform": "dreamcast"}, CHARS, "wrestlers")
    assert p["status"] == "unsupported" and "no routed character writer" in p["message"]


# ---------------------------------------------------------------- the chained path and one-mod builds

def test_chain_feeds_each_step_the_previous_output_and_isolates_failures():
    original = {"AFS": b"0000"}
    seen = []

    def writer(i, fail=False):
        def step(files):
            seen.append(files["AFS"])
            if fail:
                raise ValueError("does not fit its AFS room")
            b = bytearray(files["AFS"])
            b[i] = ord("x")
            return {"AFS": bytes(b)}
        return step
    files, rep = CS.chain(original, [("a", writer(0)), ("b", writer(1, fail=True)), ("c", writer(2))])
    assert files == {"AFS": b"x0x0"} and original == {"AFS": b"0000"}
    assert seen == [b"0000", b"x000", b"x000"]                     # c builds on a's output, b left no trace
    assert rep["a"] == {"status": "built", "files": ["AFS"]} and rep["c"]["status"] == "built"
    assert rep["b"] == {"status": "failed", "reason": "does not fit its AFS room"}
    _f, rep = CS.chain({"AFS": b"0"}, [("d", lambda f: {"OTHER": b"1"})])
    assert rep["d"]["status"] == "failed" and "outside the staged copy" in rep["d"]["reason"]


def test_staged_disc_answers_the_previous_steps_bytes():
    disc = SimpleNamespace(files={"A": (10, 4), "B": (20, 4)}, read=lambda p: b"orig")
    st = CS.StagedDisc(disc, {"A": b"newer!"})
    assert st.read("A") == b"newer!" and st.read("B") == b"orig" and st.files["A"] == (10, 6)


def _ctx(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(cache=tmp_path / "cache"), progress=lambda *a: None, job_id="j")


def test_build_runs_one_multi_slot_builder_and_reports_every_slot(tmp_path, monkeypatch):
    from gbox import filemods
    posted, calls = [], []
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: posted.append((m, p, kw.get("json"))))
    monkeypatch.setattr(C, "get", lambda root, slug: next(m for m in CHARS if m["slug"] == slug))

    def fake(ctx, game, pairs, name, inp):
        calls.append([(s, m["slug"]) for s, m in pairs])
        d = filemods.mod_dir(ctx.config, game["game_id"], name)
        d.mkdir(parents=True)
        (d / ".gbox-mod.json").write_text(json.dumps({"name": name, "game_id": game["game_id"]}))
        return {"mod": name, "slots": {s: ({"status": "failed", "reason": "pack full"} if i == 1 else {"status": "built"})
                                       for i, (s, _m) in enumerate(pairs)}}
    monkeypatch.setitem(CS.BUILDERS, "gbox.pso_player", fake)
    p = CS.plan(PSO, CHARS, "wrestlers", "random", "3", "enemy:booma,enemy:gobooma,enemy:gigobooma")
    inp = SimpleNamespace(rebuild=False, seed="3")
    r = CS.build(_ctx(tmp_path), PSO, p, CHARS, tmp_path, inp)
    assert len(calls) == 1 and [s for s, _ in calls[0]] == ["enemy:booma", "enemy:gobooma", "enemy:gigobooma"]
    assert r["status"] == "partial" and r["mod"] == p["mod"]
    assert [(x["slot"], x["status"]) for x in r["report"]][:3] == [("enemy:booma", "built"), ("enemy:gobooma", "failed"),
                                                                   ("enemy:gigobooma", "built")]
    assert r["report"][1]["reason"] == "pack full" and r["report"][1]["donor"]
    rec = json.loads((filemods.mod_dir(_ctx(tmp_path).config, PSO["game_id"], p["mod"]) / ".gbox-mod.json").read_text())
    assert [c["slot"] for c in rec["cast"]] == ["enemy:booma", "enemy:gobooma", "enemy:gigobooma"]
    assert rec["cast_source"] == p["source"] and rec["verified_in_game"] is False
    assert [x[1] for x in posted] == [f"/api/characters/{r['report'][0]['character']}/targets",
                                      f"/api/characters/{r['report'][2]['character']}/targets"]
    again = CS.build(_ctx(tmp_path), PSO, p, CHARS, tmp_path, inp)                 # the same plan reuses the mod
    assert again["status"] == "ready" and len(calls) == 1 and again["report"][1]["status"] == "failed"


def test_build_without_a_multi_slot_path_reports_why(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "get", lambda root, slug: next(m for m in CHARS if m["slug"] == slug))
    p = {"mod": "cast_x", "strategy": "single", "writer": "gbox.re6_tool", "source": "x", "mapping": "auto", "seed": "",
         "assignments": [{"slot": "player", "slot_name": "Leon", "character": "sonic", "donor": "Sonic"},
                         {"slot": "enemies", "slot_name": "enemies", "character": "sd2_kane", "donor": "Kane"}]}
    r = CS.build(_ctx(tmp_path), PSO, p, CHARS, tmp_path, SimpleNamespace(rebuild=False))
    assert r["status"] == "failed" and r["mod"] is None and "no multi-slot path" in r["report"][0]["reason"]


def test_jgr_chain_builder_stages_player_afs_and_writes_one_image(tmp_path, monkeypatch):
    from gbox import gdrom, jgr
    afs = b"AFS-ORIGINAL"
    steps = []
    monkeypatch.setattr(C, "_dc_gdi", lambda ctx, g: tmp_path / "disc.gdi")
    monkeypatch.setattr(C, "_blender", lambda cfg: None)
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "lib")
    monkeypatch.setattr(gdrom, "GDRom", lambda p: SimpleNamespace(read=lambda path: afs))
    monkeypatch.setattr(__import__("gbox.jgr_swap", fromlist=["x"]), "resolve_slot",
                        lambda slot, data: {"archive": {"character:beat": 4, "character:gum": 6}[slot]})

    def build_swap(gdi, model, roles, work, name, index, *a, data=None):
        steps.append((index, data))
        if index == 6 and b"#4" not in data:
            raise AssertionError("Gum's step must see Beat's output")
        return {"files": {jgr.PLAYER_AFS: data + f"#{index}".encode()}}
    monkeypatch.setattr(jgr, "build_swap", build_swap)
    written = {}
    monkeypatch.setattr(gdrom, "patch_gdi", lambda gdi, d, name, files, progress=None:
                        written.update(files) or (d.mkdir(parents=True) or d / f"{name}.gdi"))
    pairs = [("character:beat", CHARS[5]), ("character:gum", CHARS[6])]
    r = CS._jgr(_ctx(tmp_path), JGR, pairs, "cast_jgr_x", SimpleNamespace())
    assert r["mod"] == "cast_jgr_x" and {s: x["status"] for s, x in r["slots"].items()} == \
        {"character:beat": "built", "character:gum": "built"}
    assert steps == [(4, b"AFS-ORIGINAL"), (6, b"AFS-ORIGINAL#4")]
    assert written == {jgr.PLAYER_AFS: b"AFS-ORIGINAL#4#6"} and afs == b"AFS-ORIGINAL"


# ---------------------------------------------------------------- PSO pairs build on synthetic data

def _pso_fixtures():
    import importlib
    return importlib.import_module("test_pso_enemy")


def test_pso_build_swap_pairs_give_every_enemy_its_own_donor(tmp_path):
    T = _pso_fixtures()
    bml = T.enemy_pack()
    disc = T.fake_disc(bml, spare_sectors=8)
    tall = T.DONOR_POS * [1, 1.3, 1]
    a, b = T.donor_gltf(tmp_path / "a.gltf"), T.donor_gltf(tmp_path / "b.gltf", pos=tall)
    roles = {n: n for n in T.DONOR_NAMES}
    ens = [T.enemy(bml) | {"donor": {"model": a, "roles": roles, "name": "Briggs"}},
           T.enemy(bml, "lappy_two", "lappy_two.nj", roles=None) | {"donor": {"model": b, "roles": roles, "name": "Kane"}}]
    r = PE.build_swap(disc, None, None, tmp_path / "work", "cast", ens)
    assert list(r["files"]) == [T.PACK] and len(r["files"][T.PACK]) <= PE.room_bytes(disc, T.PACK)
    assert r["report"]["lappy_base"]["donor"] == "Briggs" and r["report"]["lappy_two"]["donor"] == "Kane"
    errors = {}
    ens[1]["donor"] = {"model": b, "roles": {}, "name": "Nobody"}
    r = PE.build_swap(disc, None, None, tmp_path / "work2", "cast", ens, on_error=lambda k, e: errors.update({k: str(e)}))
    assert set(r["report"]) == {"lappy_base"} and "no donor model / body roles" in errors["lappy_two"]


def test_pso_build_cast_writes_one_gdi_with_every_assignment(tmp_path, monkeypatch):
    from gbox.gdrom import GDRom
    T = _pso_fixtures()
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
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    pairs = [("player", metas["briggs"]), ("enemy:lappy_base", metas["briggs"]), ("enemy:lappy_two", metas["kane"]),
             ("enemy:nosuch", metas["kane"])]
    before = (tmp_path / "src" / "disc03.bin").read_bytes()
    r = PE.build_cast(cfg, PSO, gdi, pairs, "cast_pso_test", root=lib)
    assert r["mod"] == "cast_pso_test"
    st = {s: x["status"] for s, x in r["slots"].items()}
    assert st == {"player": "failed", "enemy:lappy_base": "built", "enemy:lappy_two": "built", "enemy:nosuch": "failed"}
    assert "not_working" in r["slots"]["player"]["reason"] and "nosuch" in r["slots"]["enemy:nosuch"]["reason"]
    d = tmp_path / "cache" / "mods" / PSO["game_id"] / "cast_pso_test"
    man = json.loads((d / ".gbox-mod.json").read_text())
    assert man["files"] == [T.PACK] and man["enemies"] == {"lappy_base": "enemy:lappy_base", "lappy_two": "enemy:lappy_two"}
    mod = GDRom(d / man["image"])
    assert mod.read(T.PACK) != bml and mod.read("PSO/BM_ENE_OTHER_A.BML") == b"other" * 500
    assert (tmp_path / "src" / "disc03.bin").read_bytes() == before                         # never the original
    assert r["detail"]["lappy_base"]["donor"] == "Briggs" and r["detail"]["lappy_two"]["donor"] == "Kane"
    assert (lib / "kane" / "targets" / "pso_lappy_two.gltf").is_file()


# ---------------------------------------------------------------- the menu's API

def test_cast_swap_api_lists_sources_and_plans(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    import numpy as np
    from PIL import Image
    lib = tmp_path / "characters"
    rng = np.random.default_rng(0)
    for m in CHARS:
        (lib / m["slug"]).mkdir(parents=True)
        (lib / m["slug"] / "meta.json").write_text(json.dumps(m))
        if m["slug"] in ("djv_ps2_dmx", "sd2_kane"):                    # two donors pass the collection check
            (lib / m["slug"] / m["model"]).write_bytes(b"glTF" + bytes(64))
            Image.fromarray(rng.integers(0, 255, (64, 64, 3), np.uint8)).save(lib / m["slug"] / "preview.png")
    monkeypatch.setenv("GBOX_CHARACTERS", str(lib))
    cfg = Config(data_dir=tmp_path / "data")
    app = create_app(cfg)
    app.state.store.upsert_catalog([PSO | {"source_paths": ["pso.gdi"], "format": "gdi", "profile_id": "dc"}])
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {cfg.token()}"
        r = client.get(f"/api/cast_swap/sources?game_id={PSO['game_id']}").json()
        assert r["sources"][0]["key"] == "wrestlers" and "enemy:booma" in [s["slot"] for s in r["slots"]]
        p = client.post("/api/cast_swap/plan", json={"game_id": PSO["game_id"], "source": "wrestlers", "seed": "1"}).json()
        assert p["status"] == "planned" and p["assignments"][0]["preview_url"].startswith("/api/characters/")
        assert {r["character"] for r in p["assignments"]} == {"djv_ps2_dmx", "sd2_kane"}
        assert any("no model file" in x["reason"] for x in p["refused"])          # the library check runs server-side
        bad = client.post("/api/cast_swap/plan", json={"game_id": PSO["game_id"], "source": "nothing like it"})
        assert bad.status_code == 422 and "sources:" in bad.json()["detail"]
        assert client.post("/api/cast_swap/plan", json={"game_id": "0" * 16, "source": "x"}).status_code == 404


# ---------------------------------------------------------------- the tool, the agent, the mashup planner

def test_characters_tool_routes_cast_swap_without_a_character(monkeypatch):
    got = {}
    monkeypatch.setattr(CS, "run", lambda ctx, inp: got.setdefault("inp", inp) and {"status": "planned"})
    inp = C.CharIn(op="cast_swap", target_game="PSO", source="wrestlers", plan_only=True)
    assert C.characters_tool(inp, SimpleNamespace()) == {"result": {"status": "planned"}}
    assert got["inp"].source == "wrestlers" and "launch" not in inp.model_fields_set


def test_run_plans_through_the_api_and_names_sources_when_none_given(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "library_root", lambda cfg: tmp_path / "absent")
    monkeypatch.setattr(C, "_game", lambda ctx, q: PSO if "phantasy" in (q.game or "") else pytest.fail(q))
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: CHARS if p == "/api/characters" else pytest.fail(p))
    ctx = _ctx(tmp_path)
    r = CS.run(ctx, C.CharIn(op="cast_swap", target_game="PSO"))
    assert r["status"] == "needs_source" and r["sources"][0]["key"] == "wrestlers"
    p = CS.run(ctx, C.CharIn(op="cast_swap", target_game="PSO", source="wrestlers", plan_only=True, seed="1"))
    assert p["status"] == "planned" and p["assignments"] and all(d["height"] is None for d in p["donors"])


@pytest.mark.parametrize("text,want", [
    ("replace everyone in PSO with wrestlers", ("pso", "wrestlers")),
    ("Replace the entire cast of Phantasy Star Online with the entire cast of Jet Grind Radio",
     ("phantasy star online", "jet grind radio")),
    ("replace all the characters in Crazy Taxi with Def Jam wrestlers", ("crazy taxi", "def jam wrestlers")),
    ("everyone in DOA2 as Sonic Adventure 2 characters", ("doa2", "sonic adventure 2")),
    ("make PSO's cast the wrestlers", None),
])
def test_mashup_recognises_whole_cast_requests(text, want):
    assert mashup.parse_cast_request(text) == want
    assert mashup.parse_cast_request("put Mario in Ocarina of Time") is None


def test_mashup_routes_a_whole_cast_request_to_cast_swap(monkeypatch):
    posted = []
    monkeypatch.setattr(mashup, "_resolve_game", lambda name, ctx: PSO if "phantasy" in name else None)
    monkeypatch.setattr(mashup, "_dispatch_job", lambda ctx, tool, inp, limit=0: posted.append((tool, inp)) or
                        {"id": "j1", "state": "succeeded"})
    ctx = SimpleNamespace(artifact=lambda *a, **k: None)
    r = mashup.mashup(mashup.MashupIn(request="replace everyone in PSO with wrestlers"), ctx)["result"]
    assert r["kind"] == "cast_swap" and r["status"] == "ready_to_dispatch" and not posted
    assert r["call"]["input"] == {"op": "cast_swap", "target_game": PSO["game_id"], "source": "wrestlers",
                                  "mapping": "auto", "launch": False}
    r = mashup.mashup(mashup.MashupIn(request="replace everyone in PSO with wrestlers", auto_dispatch=True), ctx)["result"]
    assert r["status"] == "dispatched_succeeded" and posted[0][0] == "characters" and posted[0][1]["op"] == "cast_swap"


def test_agent_prompt_and_schema_route_whole_cast_requests_to_cast_swap():
    src = Path(__file__).resolve().parents[1].joinpath("gbox", "agent.py").read_text("utf-8")
    assert "everyone in PSO with wrestlers" in src
    assert "characters op=cast_swap target_game=<game>" in src
    assert '"target_game": s, "source": s, "mapping": s' in src
