"""Live executable extraction is bound to one verified game session and RAM layout."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from gbox import re_lab_tool as lab
from gbox.config import Config
from gbox.registry import Ctx

SID = "worker123-job123"
GID = "game123"
BASE = 0x80000000


@pytest.fixture
def live(tmp_path, monkeypatch):
    game = {"game_id": GID, "title": "Owned game", "platform": "gamecube", "format": "iso",
            "source_paths": [str(tmp_path / "missing.iso")], "profile_id": "gc",
            "launch": {"path": str(tmp_path / "missing.iso")},
            "hashes": {"sha256": "a" * 64}}
    row = {"session_id": SID, "game_id": GID, "title": "Owned game", "state": "running",
           "adapter": "dolphin", "mod": "face-build", "staged_mod": "face-build~7",
           "collection_mod": "face-build", "started": 123.0, "detail": {"pid": 4321}}
    info = {"game_id": GID, "platform": "gamecube", "core": "dolphin", "emulator": "dolphin",
            "rom": "modded.iso", "runtime": {"running": True, "pid": 4321},
            "capabilities": {"read_memory": "supported"}}
    state = {"game": game, "rows": [row], "info": info, "reads": [], "session_checks": 0}
    def api(ctx, method, path, **kwargs):
        if method == "GET" and path == f"/api/catalog/{GID}":
            return deepcopy(state["game"])
        if method == "GET" and path == "/api/sessions":
            state["session_checks"] += 1
            return deepcopy(state["rows"])
        if method == "POST" and path == f"/api/sessions/{SID}/rpc":
            payload = kwargs["json"]
            if payload["op"] == "info":
                return deepcopy(state["info"])
            assert payload["op"] == "read_memory"
            state["reads"].append(payload["args"])
            if state.get("on_read"):
                state["on_read"]()
            return state.get("payload", bytes([23]) * payload["args"]["length"]).hex()
        pytest.fail(f"Unexpected API call: {method} {path}")
    monkeypatch.setattr(lab, "_api", api)
    ctx = Ctx(Config(data_dir=tmp_path / "data"), worker="analysis-linux")
    return state, ctx


def request(**kwargs):
    return lab.ExeIn(game_id=GID, source="ram", session_id=SID, ram_base=BASE + 0x20, ram_size=32, **kwargs)


def test_ram_snapshot_keeps_actual_session_build_worker_and_raw_revision(live):
    state, ctx = live
    result = lab.re_executable(request(), ctx)
    raw_hash = hashlib.sha256(bytes([23]) * 32).hexdigest()
    assert state["reads"] == [{"address": BASE + 0x20, "length": 32}]
    assert state["session_checks"] == 2
    assert result["source_sha256"] == raw_hash != state["game"]["hashes"]["sha256"]
    assert result["session_id"] == SID and result["worker_id"] == "worker123"
    assert result["mod"] == "face-build" and result["revision"]["actual_mod"] == "face-build~7"
    assert result["revision"]["kind"] == "ram_snapshot" and result["revision"]["sha256"] == raw_hash
    assert result["revision"]["atomic"] is False
    assert result["snapshot_finished_at"] >= result["snapshot_started_at"]
    assert "non-atomic" in " ".join(result["notes"])
    data = Path(result["elf_path"]).read_bytes()
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    name, artifact, media, provenance = ctx.artifacts[0]
    assert name == "exe_info.json" and media == "application/json"
    assert json.loads(artifact)["revision"] == result["revision"]
    assert provenance["worker"] == "analysis-linux" and provenance["worker_id"] == "worker123"
    assert not lab._validate(lab.ExeOut.model_validate(result), {name: artifact})


@pytest.mark.parametrize("change", ["missing", "ended", "stopping", "wrong_game", "wrong_worker", "duplicate"])
def test_invalid_ledger_identity_never_reads_ram(live, change):
    state, ctx = live
    row = state["rows"][0]
    if change == "missing":
        state["rows"] = [row | {"session_id": "worker123-othergame"}]
    elif change == "duplicate":
        state["rows"].append(row.copy())
    else:
        row.update({"ended": {"state": "ended"}, "stopping": {"stopping": True},
                    "wrong_game": {"game_id": "different"}, "wrong_worker": {"worker_id": "another-worker"}}[change])
    with pytest.raises(ValueError):
        lab.re_executable(request(), ctx)
    assert state["reads"] == [] and ctx.artifacts == []


@pytest.mark.parametrize("change", ["wrong_game", "wrong_platform", "dead", "unsupported", "wrong_emulator"])
def test_worker_runtime_must_confirm_identity_and_memory_support_before_read(live, change):
    state, ctx = live
    state["info"].update({"wrong_game": {"game_id": "different"}, "wrong_platform": {"platform": "ps2"},
                          "dead": {"runtime": {"running": False}}, "unsupported": {"capabilities": {"read_memory": "unsupported"}},
                          "wrong_emulator": {"emulator": "another-emulator"}}[change])
    with pytest.raises(ValueError):
        lab.re_executable(request(), ctx)
    assert state["reads"] == [] and ctx.artifacts == []


def test_auto_disc_failure_uses_the_same_strict_live_binding(live):
    state, ctx = live
    state["rows"][0]["game_id"] = "other-game-on-the-same-worker"
    inp = request().model_copy(update={"source": "auto"})
    with pytest.raises(ValueError, match="game_id changed"):
        lab.re_executable(inp, ctx)
    assert not state["reads"] and not ctx.artifacts


def test_auto_disc_failure_retains_successful_ram_provenance(live):
    state, ctx = live
    result = lab.re_executable(request().model_copy(update={"source": "auto"}), ctx)
    assert result["source"] == "ram" and result["session_id"] == SID
    assert result["worker_id"] == "worker123" and result["revision"]["kind"] == "ram_snapshot"
    assert "disc route failed" in " ".join(result["notes"])


def test_default_layout_reads_exact_psx_ram_in_bounded_chunks(live):
    state, ctx = live
    state["game"]["platform"] = state["info"]["platform"] = "psx"
    state["rows"][0]["adapter"] = state["info"]["emulator"] = "retroarch"
    state["info"]["core"] = "mednafen_psx_hw"
    result = lab.re_executable(lab.ExeIn(game_id=GID, source="ram", session_id=SID), ctx)
    assert state["reads"] == [{"address": BASE, "length": 0x100000},
                              {"address": BASE + 0x100000, "length": 0x100000}]
    assert result["revision"]["size"] == 0x200000 and result["processor"] == "MIPS:LE:32:default"


@pytest.mark.parametrize("overrides", [{"ram_base": BASE - 1}, {"ram_size": -1}, {"ram_size": 0},
                                        {"ram_base": None}, {"ram_size": None}, {"ram_size": 0x1800000}])
def test_unverified_or_incomplete_range_is_rejected_before_memory_read(live, overrides):
    state, ctx = live
    with pytest.raises(ValueError, match="RAM range|ram_base and ram_size"):
        lab.re_executable(request().model_copy(update=overrides), ctx)
    assert not state["reads"]


def test_unknown_platform_mapping_cannot_interpret_arbitrary_ram(live):
    state, ctx = live
    state["game"]["platform"] = state["info"]["platform"] = "nes"
    with pytest.raises(ValueError, match="CPU mapping"):
        lab.re_executable(request(), ctx)
    assert not state["reads"]


def test_platform_without_verified_ram_layout_does_not_accept_manual_addresses(live):
    state, ctx = live
    state["game"]["platform"] = state["info"]["platform"] = "xbox360"
    with pytest.raises(ValueError, match="main-RAM layout"):
        lab.re_executable(request(), ctx)
    assert not state["reads"]


@pytest.mark.parametrize("change", ["mod", "pid", "end"])
def test_session_revision_change_during_read_discards_snapshot(live, change):
    state, ctx = live
    def changed():
        if change == "mod":
            state["rows"][0]["mod"] = "different-build"
        elif change == "pid":
            state["info"]["runtime"]["pid"] = 9999
        else:
            state["rows"][0]["state"] = "ended"
    state["on_read"] = changed
    with pytest.raises(ValueError):
        lab.re_executable(request(), ctx)
    assert len(state["reads"]) == 1 and not ctx.artifacts
    assert not (ctx.config.data_dir / "analysis").exists()


def test_short_memory_payload_cannot_be_accepted_as_a_valid_snapshot(live):
    state, ctx = live
    state["payload"] = b"short"
    with pytest.raises(ValueError, match="Incomplete RAM snapshot"):
        lab.re_executable(request(), ctx)
    assert not ctx.artifacts


def test_same_second_different_snapshots_never_overwrite_analysis_input(live):
    state, ctx = live
    a = lab.re_executable(request(), ctx)
    old = Path(a["elf_path"]).read_bytes()
    state["payload"] = b"\x44" * 32
    b = lab.re_executable(request(), ctx)
    assert a["elf_path"] != b["elf_path"]
    assert Path(a["elf_path"]).read_bytes() == old


def test_artifact_validation_checks_live_provenance_not_only_elf_hash(live):
    _, ctx = live
    result = lab.re_executable(request(), ctx)
    changed = result | {"session_id": "worker123-another-game"}
    assert lab._validate(lab.ExeOut.model_validate(result), {"exe_info.json": json.dumps(changed).encode()})


def test_disc_executable_output_remains_usable_without_a_live_session(live, tmp_path):
    state, ctx = live
    rom = tmp_path / "owned.gba"
    rom.write_bytes(b"owned game data")
    state["game"].update(platform="gba", format="gba", source_paths=[str(rom)], launch={"path": str(rom)})
    result = lab.re_executable(lab.ExeIn(game_id=GID, source="disc"), ctx)
    assert result["source"] == "disc" and result["session_id"] == result["worker_id"] == ""
    assert result["revision"] == {} and state["session_checks"] == 0 and not state["reads"]
