"""Original collection identities select owned Switch archives; arbitrary models cannot pass."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import characters as C, mt_arc, re5_character_writer as W, re5ps3_collection as PS3, skin_swap, switch_mods as S
from gbox.config import Config
from gbox.re5ps3_roles import CHRIS_MODEL, SHEVA_MODEL
from gbox.re_switch import RE5_TITLE_ID as TID

GAME = {"game_id": "52d15709be0fda1a", "title": "Resident Evil 5", "platform": "switch", "serial": TID}


def native_meta(character="sheva"):
    archive, model, digest = ((PS3.SHEVA, r"pawn\pl\pl01\model\pl0100", SHEVA_MODEL) if character == "sheva"
                              else (PS3.CHRIS, r"pawn\pl\pl00\model\pl0000", CHRIS_MODEL))
    hashes = {p: PS3.FILES[p][1] for p in (PS3.SFO, PS3.EBOOT, archive)}
    slug = f"re5ps3_{character}_normal"
    return {"slug": slug, "name": character.title(), "kind": "character", "model": slug + ".glb",
            "extraction_tool": "gbox.re5ps3_collection", "re5ps3_reader": PS3.READER_VERSION,
            "source": {"platform": "ps3", "game_id": PS3.GAME_ID,
                       "files": [f"{p} SHA256 {h}" for p, h in hashes.items()] + [model]},
            "native_evidence": {"game_id": PS3.GAME_ID, "title_id": PS3.TITLE_ID, "disc_version": "02.00",
                                "app_version": "01.00", "archive_member": archive, "archive_sha256": hashes[archive],
                                "model_member": model, "source_sha256": digest, "source_files_sha256": hashes}}


def archive(character):
    player_id = Path(skin_swap.CHARACTER_ARCS[TID][character]).name[3:5]
    data = ("owned Switch " + character).encode()
    return mt_arc.build(mt_arc.Arc(7, [mt_arc.Entry(f"pawn\\pl\\pl{player_id}\\model\\pl{player_id}00", 0, 0, len(data), 0, data)]))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    root = tmp_path / "romfs"
    for name, relative in skin_swap.CHARACTER_ARCS[TID].items():
        p = root / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(archive(name))
    monkeypatch.setattr(W, "_romfs", lambda config: root)
    monkeypatch.setattr(S, "running_users", lambda *a: [])
    monkeypatch.setattr(S, "WRITERS", {})
    # Structural/provenance exercises below are not runtime acceptance.
    monkeypatch.setattr(W, "VERIFIED_NATIVE_PAIRS", frozenset({("chris", "sheva"), ("sheva", "chris")}))
    return SimpleNamespace(config=cfg, job_id="native-test"), root


def test_failed_native_trial_is_gated_before_asset_reads_or_writes(setup, monkeypatch):
    ctx, _ = setup
    monkeypatch.setattr(W, "VERIFIED_NATIVE_PAIRS", frozenset())
    monkeypatch.setattr(W, "_romfs", lambda *a: pytest.fail("unaccepted pair read game assets"))
    result = W.plan(ctx, GAME, C.CharIn(op="live_use", character="re5ps3_sheva_normal", slot="chris"), native_meta())
    assert result == {"reason": W.UNVERIFIED_REASON}
    assert not ctx.config.cache.exists()


@pytest.mark.parametrize("donor,target", [("chris", "sheva"), ("sheva", "chris")])
def test_exact_original_identity_writes_its_switch_counterpart(setup, donor, target):
    ctx, root = setup
    plan = W.plan(ctx, GAME, C.CharIn(op="use", character=donor, slot=target, launch=False), native_meta(donor))
    relative = skin_swap.CHARACTER_ARCS[TID][target]
    assert plan["changes"] == {"romfs/" + relative: {"bytes": archive(donor)}}
    scope = plan["replacement_scope"]
    assert scope["source_platform"] == "ps3" and scope["written_platform"] == "switch"
    assert scope["collection_model_used"] is False and scope["gameplay_verified"] is False
    assert scope["written_sha256"] == hashlib.sha256(archive(donor)).hexdigest()
    assert (root / relative).read_bytes() == archive(target)
    assert not ctx.config.cache.exists()


def test_plan_only_uses_lazy_writer_without_writes_launches_or_swaps(setup, monkeypatch):
    ctx, _ = setup
    calls = []
    def api(ctx, method, path, **kw):
        calls.append((method, path))
        assert method == "GET" and path == "/api/sessions"
        return [{"session_id": "live", "state": "running", "game_id": GAME["game_id"], "mod": "active"}]
    monkeypatch.setattr(S, "write_files", lambda *a, **k: pytest.fail("plan_only wrote an overlay"))
    result = S.character_use(ctx, api, native_meta(), GAME,
                             C.CharIn(op="live_use", character="re5ps3_sheva_normal", slot="chris",
                                      session_id="live", plan_only=True), op="live_use")
    assert result["status"] == "planned" and result["replacement_scope"]["route"] == "native_archive_counterpart"
    assert result["switch_overlay"]["active_build"] == "active" and result["slots"][0]["slot"] == "chris"
    assert S.WRITERS[TID] is W.plan and not ctx.config.cache.exists()
    assert calls == [("GET", "/api/sessions")]


def test_live_use_stages_exact_active_build_and_restarts_only_its_session(setup, monkeypatch):
    ctx, root = setup
    path = "romfs/" + skin_swap.CHARACTER_ARCS[TID]["chris"]
    S.write_files(ctx.config, GAME["game_id"], "active", {path: {"bytes": b"prior edit"}}, create={"title_id": TID})
    monkeypatch.setattr(S, "running_users", lambda gid, name: ["live"] if name == "active" else [])
    calls = []
    def api(ctx, method, route, **kw):
        calls.append((method, route, kw))
        if method == "GET":
            return [{"session_id": "live", "state": "running", "game_id": GAME["game_id"], "mod": "active"}]
        assert route == "/api/sessions/live/swap"
        return {"id": "restart-job"}
    result = S.character_use(ctx, api, native_meta(), GAME,
                             C.CharIn(op="live_use", character="re5ps3_sheva_normal", slot="chris", session_id="live"),
                             op="live_use")
    folder = S.build_dir(ctx.config, GAME["game_id"], "active")
    assert result["status"] == "restarting" and result["mod"] == "active" and result["swap_job"] == "restart-job"
    assert result["replacement_scope"]["collection_model_used"] is False
    assert (folder / path).read_bytes() == b"prior edit"
    assert len(S.pending_edits(folder)) == 1
    S.apply_pending(folder)
    assert (folder / path).read_bytes() == archive("sheva")
    assert (root / skin_swap.CHARACTER_ARCS[TID]["chris"]).read_bytes() == archive("chris")
    assert [(m, p) for m, p, _ in calls] == [("GET", "/api/sessions"), ("POST", "/api/sessions/live/swap")]


@pytest.mark.parametrize("alter", [
    lambda m: m.update(slug="sonic"),
    lambda m: m.update(variant_of="re5ps3_sheva_normal"),
    lambda m: m["source"].update(variant_of="original"),
    lambda m: m.update(extraction_tool="Blender"),
    lambda m: m.update(model="edited.glb"),
    lambda m: m.update(props=[{"node": "hat"}]),
    lambda m: m.update(rig={"scale": {"head": 2}}),
    lambda m: m["source"].update(game_id="different-game"),
    lambda m: m["source"].update(platform="switch"),
    lambda m: m["source"].update(files=[]),
    lambda m: m["native_evidence"].update(archive_member=PS3.CHRIS),
    lambda m: m["native_evidence"].update(archive_sha256="0" * 64),
    lambda m: m["native_evidence"].update(source_sha256=CHRIS_MODEL),
    lambda m: m["native_evidence"]["source_files_sha256"].update({PS3.EBOOT: "0" * 64}),
])
def test_modified_wrong_source_and_unproven_donors_fail_before_reading_romfs(setup, monkeypatch, alter):
    ctx, _ = setup
    meta = copy.deepcopy(native_meta())
    alter(meta)
    monkeypatch.setattr(W, "_romfs", lambda *a: pytest.fail("unsupported donor read game assets"))
    result = W.plan(ctx, GAME, C.CharIn(op="use", character="requested", slot="chris"), meta)
    assert "reason" in result and "changes" not in result
    assert not ctx.config.cache.exists()


@pytest.mark.parametrize("slot,target", [("player", ""), ("enemies", ""), ("../chris", ""), ("sheva", "chris")])
def test_target_is_explicit_known_player_and_unambiguous(setup, slot, target):
    ctx, _ = setup
    result = W.plan(ctx, GAME, C.CharIn(op="live_use", character="sheva", slot=slot, target=target), native_meta())
    assert "reason" in result and "changes" not in result


@pytest.mark.parametrize("slot,target", [("character:chris", ""), ("player", "chris"), ("uPl00ChrisNormal.arc", "")])
def test_explicit_slot_aliases_resolve_to_the_named_native_archive(setup, slot, target):
    ctx, _ = setup
    result = W.plan(ctx, GAME, C.CharIn(op="live_use", character="sheva", slot=slot, target=target), native_meta())
    assert result["slots"][0]["slot"] == "chris"


def test_wrong_title_same_donor_cast_and_bad_archive_never_produce_changes(setup):
    ctx, root = setup
    inp = C.CharIn(op="use", character="sheva", slot="chris")
    assert "changes" not in W.plan(ctx, GAME | {"serial": "01002A000CD48000"}, inp, native_meta())
    assert "changes" not in W.plan(ctx, GAME, inp.model_copy(update={"slot": "sheva"}), native_meta())
    assert "changes" not in W.plan(ctx, GAME, C.CharIn(op="cast_swap", source="re5"), None)
    (root / skin_swap.CHARACTER_ARCS[TID]["sheva"]).write_bytes(archive("chris"))
    result = W.plan(ctx, GAME, inp, native_meta())
    assert "expected Switch player archive" in result["reason"] and "changes" not in result


def test_unrelated_title_does_not_register_re5_and_explicit_writer_wins(setup):
    assert S._writer_for("01002A000CD48000") is None and S.WRITERS == {}
    custom = lambda *a: {}
    S.register_writer(TID, custom)
    assert S._writer_for(TID) is custom
