"""scripts/patch_atlas.py: the patch atlas generator (docs/patch-atlas/README.md). Fixtures only, no network."""
import json
import sqlite3

import pytest

from scripts import patch_atlas as pa


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return path


@pytest.fixture
def library(tmp_path):
    """A patch library: one tree build with payload, one cold cast build, one hash sidecar of a deleted build and one
    sidecar of a build that still exists."""
    lib = tmp_path / "patch-library"
    write(lib / "aaaa000000000001" / "re6_aya" / ".gbox-mod.json", {
        "name": "re6_aya", "game_id": "aaaa000000000001", "image": "default.xex", "built": 1791000000.0,
        "files": ["nativeXenon/arc/X360/uPl00LeonUsa.arc", "nativeXenon/arc/X360/uPl00LeonAsia.arc"],
        "character": "aya", "target": "leon", "kind": "character",
        "recipe": {"tool": "characters", "input": {"op": "use", "character": "aya", "slot": "leon", "launch": False,
                                                   "assignments": [{"slot": "x", "character": "y"}]}}})
    write(lib / "aaaa000000000001" / "re6_aya" / "archive.json", {
        "game_id": "aaaa000000000001", "title": "Resident Evil 6", "platform": "xbox360", "build": "re6_aya",
        "tier": "hot", "payload": ["payload/nativeXenon/arc/X360/uPl00LeonUsa.arc"], "meta": [], "not_kept": [],
        "notes": [], "size": 1234, "kept_bytes": 99})
    write(lib / "aaaa000000000001" / "cast_v1.cold" / ".gbox-mod.json", {
        "name": "cast_v1", "built": "2026-10-15T12:00:00", "writer": "gbox.x_cast", "kind": "cast",
        "gameplay_verified": True, "file_changes": [{"path": "disc/loadfile.afs", "change": "patched"}],
        "slots": [{"slot": "fighter:zack", "donor": "sa1_tikal"}, {"slot": "fighter:tina", "donor": "wario_hd"}],
        "note": "69 costume entries rebuilt"})
    write(lib / "aaaa000000000001" / "cast_v1.cold" / "archive.json", {"tier": "cold", "title": "Resident Evil 6",
                                                                       "platform": "xbox360", "not_kept": ["loadfile.afs"]})
    write(lib / "aaaa000000000001" / ".old_build.sha256.json" / "archive.json", {
        "title": "Resident Evil 6", "platform": "xbox360", "notes": ["a lone file, not a build folder: recorded, not kept"]})
    write(lib / "aaaa000000000001" / ".re6_aya.sha256.json.cold" / "archive.json", {
        "notes": ["a lone file, not a build folder: recorded, not kept"]})
    return lib


@pytest.fixture
def switch(tmp_path):
    sw = tmp_path / "mods"
    write(sw / "010099A00BC1E000" / "re4-noclothes" / ".gbox-mod.json", {
        "name": "re4-noclothes", "writer": "gbox.switch_mods", "kind": "file", "platform": "switch",
        "game_title": "010099A00BC1E000", "built": 1794129579.7,
        "layeredfs": {"format": 1, "title_id": "010099A00BC1E000", "load": "load/010099A00BC1E000/re4-noclothes"},
        "files": ["romfs/bio4/em/pl00.udas"],
        "file_changes": [{"path": "romfs/bio4/em/pl00.udas", "change": "replaced", "size": 1448576}],
        "history": [{"id": "e1", "note": "replace pl00.udas with hide-only", "files": []}], "hot_swaps": 2})
    write(sw / "bbbb000000000002" / "empty" / ".gbox-mod.json", {"name": "empty", "game_title": "Mystery Game",
                                                                "layeredfs": {"title_id": "0100AAAA00000000"}})
    (sw / "bbbb000000000002" / "no-manifest").mkdir(parents=True)
    return sw


@pytest.fixture
def catalog(tmp_path):
    db = tmp_path / "gbox.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE catalog (game_id TEXT PRIMARY KEY, library TEXT, title TEXT, platform TEXT, system TEXT, "
                "year TEXT, body TEXT)")
    con.execute("INSERT INTO catalog VALUES (?,?,?,?,?,?,?)", (
        "aaaa000000000001", "hyperspin", "Resident Evil 6", "xbox360", "Microsoft XBOX 360", None,
        json.dumps({"serial": None, "region": "US", "format": "iso", "size": 8091336704, "hashes": {},
                    "rel_path": "collections/Microsoft XBOX 360/roms/Resident Evil 6.iso", "library": "hyperspin"})))
    con.commit()
    con.close()
    return db


@pytest.fixture
def repo(tmp_path):
    """A fake system/ tree: a RAM map, a codes file, a picker profile, two writer modules."""
    r = tmp_path / "system"
    write(r / "profiles" / "gamedata" / "X360RE6-ram.json", {
        "format": "gbox-ram-map/1", "id": "X360RE6", "title": "RE6 X360", "platform": "xbox360", "endian": "big",
        "match": {"game_ids": ["aaaa000000000001"]}, "groups": {"player": "the player"},
        "fields": {"player.ptr": {"address": "0x83CA52FC", "type": "ptr", "description": "sPlayer", "source": "scan"},
                   "player.hp": {"pointer": ["0x83CA52FC", "0x28", "0xF20"], "type": "s16",
                                 "description": "Life", "source": "live"}}})
    write(r / "profiles" / "gamedata" / "0100AAAA00000000-ram.json", {
        "format": "gbox-ram-map/1", "id": "0100AAAA00000000", "platform": "switch", "match": {"title_id": "0100AAAA00000000"},
        "fields": {}, "notes": ["ASLR: base + offset"]})
    write(r / "profiles" / "gamedata" / "aaaa000000000001-codes.json", {
        "codes": [{"desc": "a"}, {"desc": "b"}], "verified": True, "scope": ["unlocks"]})
    write(r / "profiles" / "re6-pick.json", {"id": "re6-pick", "match": {"platform": "xbox360",
                                                                         "title_contains": "Resident Evil 6"},
                                             "camera": {"eye": "0x0"}, "entities": {}})
    write(r / "gbox" / "x_cast.py", "# cited\n")
    write(r / "gbox" / "lonely_swap.py", "# not cited by any page\n")
    return r


def curated(**kw):
    g = {"title": "Resident Evil 6", "platform": "xbox360", "game_ids": ["aaaa000000000001"], "emulator": "xenia",
         "identification": {"title_id": None, "disc_id": None, "serial": None, "hashes": {}, "notes": ""},
         "layout": [{"container": "nativeXenon/arc/X360/*.arc", "format": "MT ARC", "reader": "gbox/mt_arc.py",
                     "notes": ""}],
         "assets": [{"class": "character", "where": "uPl00*.arc", "how_found": "arc listing",
                     "writer": "gbox/x_cast.py (characters op=use)", "method": "replace MOD", "verified_in_game": "yes",
                     "evidence": "docs/missing-receipt.md", "notes": ""}],
         "live": {"file_swap": {"status": "static_only", "how": "relaunch"},
                  "ram_hooks": [{"name": "hp", "address": "0x1", "what": "", "source": "", "status": "proven_write"},
                                {"name": "ptr", "address": "0x2", "what": "", "source": "", "status": "proven_read"}],
                  "live_controls": "job_re6", "pickwhip": {"status": "none", "how": ""}},
         "gaps": ["no live body swap", "no save state", "no pick backend", "fourth gap"],
         "sources": ["system/gbox/x_cast.py", "system/docs/gone.md"]}
    g.update(kw)
    return g


# ----------------------------------------------------------------------------------------------------- helpers ----

def test_names_and_slugs():
    assert pa.sidecar_name(".sm64_ryo.sha256.json") == "sm64_ryo"
    assert pa.sidecar_name(".pe_mario.sha256.json.cold") == "pe_mario"
    assert pa.build_name("pe_mario.cold") == "pe_mario"
    assert pa.slugify("Metal Gear Solid 2: Substance (USA)", "ps2") == "metal-gear-solid-2-substance-usa-ps2"
    assert pa.platform_dir("psx") == "ps1" and pa.platform_dir("switch") == "switch"
    assert pa.day(1794129579.7) == "2026-11-08" and pa.day("2026-10-15T12:00:00") == "2026-10-15" and pa.day(None) is None


@pytest.mark.parametrize("man, want", [
    ({"verified_in_game": True}, True),
    ({"verified_in_game": False, "gameplay_verified": True}, False),   # the first explicit flag wins
    ({"gameplay_verified": True}, True),
    ({"verified": False}, False),
    ({"verification": {"in_game": True}}, True),
    ({"verification": "pending"}, None),
    ({}, None),
])
def test_verified_flags(man, want):
    assert pa.verified(man) is want


def test_recipe_keeps_tool_op_and_short_args():
    r = pa.recipe({"build_call": {"tool": "characters", "input": {"op": "cast_swap", "seed": "c8118b", "slots": "all",
                                                                  "assignments": [1, 2], "launch": False}}})
    assert r == {"tool": "characters", "op": "cast_swap", "args": {"seed": "c8118b"}}
    assert pa.recipe({"recipe": {"tool": "gbox.doa2_mixed.build", "plan": {"AYA": [], "LEI": []}}}) == \
        {"tool": "gbox.doa2_mixed.build", "plan_keys": 2}
    assert pa.recipe({}) is None


# -------------------------------------------------------------------------------------------------------- scan ----

def test_scan_library_builds_and_sidecars(library):
    f = pa.scan_library(library)["aaaa000000000001"]
    assert f["title"] == "Resident Evil 6" and f["platform"] == "xbox360"
    rows = {r["name"]: r for r in f["builds"]}
    assert set(rows) == {"re6_aya", "cast_v1"}
    aya = rows["re6_aya"]
    assert aya["files_count"] == 2 and aya["payload_files"] == 1 and aya["tier"] == "hot"
    assert aya["donors"] == ["aya"] and aya["recipe"] == {"tool": "characters", "op": "use",
                                                          "args": {"character": "aya", "slot": "leon"}}
    assert aya["built"] == "2026-10-03" and "verified" not in aya
    cast = rows["cast_v1"]
    assert cast["tier"] == "cold" and cast["verified"] is True and cast["files"] == ["disc/loadfile.afs"]
    assert cast["donors"] == ["sa1_tikal", "wario_hd"] and cast["slots_count"] == 2 and cast["not_kept"] == 1
    assert cast["note"] == "69 costume entries rebuilt" and cast["writer"] == "gbox.x_cast"
    assert f["sidecars"] == ["old_build"]                 # re6_aya's own sidecar is not a lost build


def test_scan_switch_overlays(switch):
    folders = pa.scan_switch(switch)
    re4 = folders["010099A00BC1E000"]["builds"][0]
    assert re4["title_id"] == "010099A00BC1E000" and re4["edits"] == 1 and re4["hot_swaps"] == 2
    assert re4["files"] == ["romfs/bio4/em/pl00.udas"] and re4["note"] == "replace pl00.udas with hide-only"
    assert re4["tier"] == "live" and re4["source"] == "switch"
    other = folders["bbbb000000000002"]
    assert [b["name"] for b in other["builds"]] == ["empty"] and other["title_id"] == "0100AAAA00000000"


def test_scan_reads_the_catalog_read_only(library, switch, catalog, tmp_path):
    before = catalog.read_bytes()
    atlas = write(tmp_path / "atlas.json", {"games": {"x": {"game_ids": ["aaaa000000000001", "ffff000000000009"]}}})
    doc = pa.scan(library, switch, catalog, atlas, now=1794345421.7)
    assert doc["format"] == pa.SCAN_FORMAT and doc["scanned_at"] == "2026-11-10"
    assert set(doc["folders"]) == {"aaaa000000000001", "010099A00BC1E000", "bbbb000000000002"}
    assert doc["catalog"] == {"aaaa000000000001": {"title": "Resident Evil 6", "platform": "xbox360", "region": "US",
                                                   "file": "Resident Evil 6.iso", "format": "iso", "size": 8091336704,
                                                   "library": "hyperspin"}}
    assert any("index.json" in n for n in doc["notes"])
    assert catalog.read_bytes() == before


def test_cli_scan_writes_json(library, tmp_path, capsys):
    out = tmp_path / "scan.json"
    assert pa.main(["scan", "--library", str(library), "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["folders"]["aaaa000000000001"]["builds"]
    with pytest.raises(SystemExit):
        pa.main(["scan"])                                 # needs a root


# ------------------------------------------------------------------------------------------------------- build ----

def scanned(library, switch):
    return pa.scan(library, switch, None, None, now=1794345421.7)


def test_build_assigns_folders_by_id_title_id_and_stub(library, switch, repo):
    atlas = pa.skeleton()
    pa.curate(atlas, {"games": {"re6-xbox360": curated(),
                                "re4-switch": curated(title="Resident Evil 4", platform="switch", game_ids=["270a"],
                                                      identification={"title_id": "010099a00bc1e000"})}})
    out = pa.build(atlas, scanned(library, switch), repo)
    assert out["games"]["re6-xbox360"]["generated"]["library"]["folders"] == ["aaaa000000000001"]
    assert out["games"]["re4-switch"]["generated"]["library"]["folders"] == ["010099A00BC1E000"]
    stub = out["games"]["mystery-game-switch"]
    assert stub["curated"]["stub"] is True and stub["curated"]["game_ids"] == ["bbbb000000000002"]
    assert stub["page"] == "switch/mystery-game-switch.md"
    assert list(out["games"])[:2] == ["mystery-game-switch", "re4-switch"]     # platform order, then slug
    lib = out["games"]["re6-xbox360"]["generated"]["library"]
    assert lib["builds"] == 2 and lib["verified"] == {"unknown": 1, "yes": 1}
    assert lib["sidecar_only"] == ["old_build"] and ["disc/loadfile.afs", 1] in lib["files_touched"]
    assert [r["name"] for r in lib["rows"]] == ["re6_aya", "cast_v1"]     # by build date


def test_build_repo_facts_and_status(library, repo):
    atlas = pa.skeleton()
    pa.curate(atlas, {"games": {"re6-xbox360": curated()}})
    g = pa.build(atlas, scanned(library, None), repo)["games"]["re6-xbox360"]
    facts = g["generated"]["repo"]
    m = facts["ram_maps"][0]
    assert m["file"] == "profiles/gamedata/X360RE6-ram.json" and m["groups"] == {"player": "the player"}
    assert {f["name"]: f["at"] for f in m["fields"]} == {"player.ptr": "0x83CA52FC",
                                                         "player.hp": "0x83CA52FC -> 0x28 -> 0xF20"}
    assert facts["codes"] == [{"file": "profiles/gamedata/aaaa000000000001-codes.json", "codes": 2, "verified": True,
                               "scope": ["unlocks"]}]
    assert facts["pick_profiles"][0]["id"] == "re6-pick" and facts["pick_profiles"][0]["camera"] is True
    assert facts["missing_sources"] == ["docs/gone.md", "docs/missing-receipt.md"]
    assert g["status"] == {"replace": "proven", "live_file_swap": "static_only", "ram_writes_proven": 1,
                           "ram_reads_proven": 1, "pickwhip": "none", "assets_verified": 1, "assets": 1,
                           "builds": 2, "builds_verified": 1}


def test_build_switch_map_by_title_id(switch, repo):
    atlas = pa.skeleton()
    pa.curate(atlas, {"games": {"mystery-switch": curated(title="Mystery", platform="switch", game_ids=["bbbb000000000002"],
                                                          identification={"title_id": "0100AAAA00000000"})}})
    g = pa.build(atlas, scanned(None, switch), repo)["games"]["mystery-switch"]
    assert [m["id"] for m in g["generated"]["repo"]["ram_maps"]] == ["0100AAAA00000000"]


def test_build_without_scan_keeps_the_library(library, repo):
    atlas = pa.skeleton()
    pa.curate(atlas, {"games": {"re6-xbox360": curated()}})
    first = pa.build(atlas, scanned(library, None), repo)
    again = pa.build(first, None, repo)
    assert again["games"]["re6-xbox360"]["generated"]["library"] == first["games"]["re6-xbox360"]["generated"]["library"]
    assert again["scan"] == first["scan"] and again["scan"]["builds"] == 2
    assert again["unpaged_writers"] == ["gbox/lonely_swap.py"]


def test_build_rejects_other_formats(repo):
    with pytest.raises(ValueError):
        pa.build(pa.skeleton(), {"format": "nope"}, repo)


def test_curate_requires_the_schema_and_takes_platforms():
    atlas = pa.skeleton()
    with pytest.raises(ValueError, match="missing"):
        pa.curate(atlas, {"games": {"half": {"title": "x"}}})
    done = pa.curate(atlas, {"games": {"re6-xbox360": curated()}, "platforms": {"xbox360": {"name": "Xbox 360"}}})
    assert done == ["re6-xbox360", "platform:xbox360"] and atlas["platforms"]["xbox360"]["name"] == "Xbox 360"


# ------------------------------------------------------------------------------------------------------ render ----

def test_render_pages_readme_and_check(library, switch, repo, tmp_path):
    docs = tmp_path / "docs" / "patch-atlas"
    write(docs / "README.md", "# Atlas\n\nHand-written intro.\n\n<!-- atlas:games:begin -->\nold\n<!-- atlas:games:end -->\n")
    atlas_path = tmp_path / "patch_atlas.json"
    atlas = pa.skeleton()
    pa.curate(atlas, {"games": {"re6-xbox360": curated()},
                      "platforms": {"xbox360": {"name": "Xbox 360 (Xenia)", "ram": "WriteProcessMemory",
                                                "mechanisms": [{"verb": "insert", "name": "stub", "status": "proven live",
                                                                "how": "a | pipe", "code": "gbox/re6.py"}],
                                                "rules": ["patch right after boot"]}}})
    atlas = pa.build(atlas, scanned(library, switch), repo)
    changed = pa.write_outputs(atlas, atlas_path, docs)
    assert atlas_path in changed and docs / "xbox360" / "re6-xbox360.md" in changed
    page = (docs / "xbox360" / "re6-xbox360.md").read_text(encoding="utf-8")
    for want in ("# Resident Evil 6 (Xbox 360)", "## Replaceable assets", "## Builds in the patch library",
                 "`re6_aya`", "`player.hp`", "`0x83CA52FC -> 0x28 -> 0xF20`", "## Gaps before a live swap",
                 "Cited but not in this checkout", "Earlier builds known only by their hash sidecar", "`old_build`",
                 "picker profile `profiles/re6-pick.json`", "cheat codes"):
        assert want in page, want
    readme = (docs / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# Atlas\n\nHand-written intro.") and "\nold\n" not in readme
    assert "[Resident Evil 6](xbox360/re6-xbox360.md)" in readme
    assert "a \\| pipe" in readme and "> **Rule:** patch right after boot" in readme
    assert "fourth gap" not in readme and "1 more on the page" in readme       # top three gaps per game
    assert "`gbox/lonely_swap.py`" in readme
    assert (docs / "switch" / "mystery-game-switch.md").exists()                 # the stub gets a page too
    # idempotent, and check() sees a hand edit
    assert pa.write_outputs(atlas, atlas_path, docs) == []
    assert pa.stale(atlas_path, docs, repo) == []
    (docs / "xbox360" / "re6-xbox360.md").write_text("edited by hand\n", encoding="utf-8")
    assert pa.stale(atlas_path, docs, repo) == [docs / "xbox360" / "re6-xbox360.md"]


def test_replace_block_appends_when_missing():
    text = pa.replace_block("# T\n", "games", "rows")
    assert text.endswith("<!-- atlas:games:begin -->\nrows\n<!-- atlas:games:end -->\n")
    assert pa.replace_block(text, "games", "new").count("atlas:games:begin") == 1


def test_cell_escapes_pipes_and_newlines():
    assert pa.cell("a|b\nc") == "a\\|b c" and pa.cell(["x", "y"]) == "x, y" and pa.cell(None) == ""


# --------------------------------------------------------------------------------------------- committed atlas ----

def test_committed_atlas_is_valid_and_its_pages_match():
    """The atlas in the repo: every game has the curated keys, a status and a page that renders from the JSON as it
    is on disk (repo facts may move between rescans; `patch_atlas.py check` covers those)."""
    atlas = pa.load_json(pa.ATLAS)
    assert atlas and atlas["format"] == pa.FORMAT and atlas["games"]
    for slug, g in atlas["games"].items():
        cur = g["curated"]
        if not cur.get("stub"):
            assert not [k for k in pa.CURATED_KEYS if k not in cur], slug
        assert set(g["status"]) >= {"replace", "live_file_swap", "pickwhip"}
    rendered = pa.render_all(atlas, pa.DOCS)
    for path, text in rendered.items():
        assert path.exists(), path
        assert path.read_text(encoding="utf-8") == text, f"{path} is stale: run scripts/patch_atlas.py build"
