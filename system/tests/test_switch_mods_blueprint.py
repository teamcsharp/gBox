"""switch_mods op=blueprint: `<build>-blueprint` = a copy of the build with the greybox archives written over it,
idempotent, the source build never written (operator 2026-11-09, the UE-blueprint look). Temp dirs only."""
import hashlib
import json
from pathlib import Path

import pytest

from gbox import switch_mods as SM
from test_switch_mods import GID, CREATE, cfg, overlay

STAGE = "romfs/nativeNXx64/ImgNX/Archive/s400.arc"
CRATE = "romfs/nativeNXx64/ImgNX/Archive/uOm0889.arc"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def files_of(folder: Path) -> dict[str, bytes]:
    return {f["path"]: (folder / f["path"]).read_bytes() for f in SM.overlay_files(folder)}


def test_blueprint_creates_the_companion_from_the_build_plus_the_manifest_and_leaves_the_source_alone(tmp_path):
    c = cfg(tmp_path)
    src = overlay(c, "recovery-pool", {"nativeNXx64/ImgNX/Archive/uEm10.arc": b"E" * 32, STAGE: b"photo-stage"})
    before = files_of(src), (src / SM.MARKER).read_bytes()
    grid = tmp_path / "s400.arc"
    grid.write_bytes(b"grid-stage" * 4)
    r = SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"from": str(grid)}, CRATE: {"bytes": b"grid-crate"}},
                           by="job 1")
    assert r["mod"] == "recovery-pool-blueprint" and r["of"] == "recovery-pool" and r["created"] is True
    assert r["written"] == [STAGE, CRATE] and r["removed"] == [] and r["unchanged"] == [] and r["pending"] is False
    dst = Path(r["dir"])
    assert files_of(dst) == {"romfs/nativeNXx64/ImgNX/Archive/uEm10.arc": b"E" * 32, STAGE: grid.read_bytes(),
                             CRATE: b"grid-crate"}
    meta = SM.read_meta(dst)
    assert meta["blueprint_of"] == "recovery-pool" and SM.is_overlay(meta) and meta["name"] == "recovery-pool-blueprint"
    assert meta["blueprint_manifest"] == {STAGE: str(grid), CRATE: "bytes"}
    assert meta["layeredfs"]["load"].endswith("/recovery-pool-blueprint")
    # the source build is byte for byte what it was
    assert (files_of(src), (src / SM.MARKER).read_bytes()) == before
    assert SM.overlay_of(c, GID, "recovery-pool-blueprint") == "recovery-pool-blueprint"


def test_blueprint_is_idempotent_and_refreshes_from_a_changed_source(tmp_path):
    c = cfg(tmp_path)
    src = overlay(c, "recovery-pool", {"nativeNXx64/ImgNX/Archive/uEm10.arc": b"E" * 32})
    manifest = {STAGE: {"bytes": b"grid-stage"}}
    first = SM.blueprint_build(c, GID, "recovery-pool", manifest)
    dst = Path(first["dir"])
    edits = len(SM.read_meta(dst)["history"])
    again = SM.blueprint_build(c, GID, "recovery-pool", manifest)
    assert again["created"] is False and again["edit"] is None and again["written"] == [] and again["unchanged"] == [STAGE]
    assert len(SM.read_meta(dst)["history"]) == edits                       # nothing staged, nothing landed
    # an artifact reference whose SHA-256 matches the companion's file is not fetched
    calls = []
    r = SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"artifact": sha(b"grid-stage")}},
                           resolve=lambda need: calls.append(need) or {k: {"bytes": b"fetched"} for k in need})
    assert r["unchanged"] == [STAGE] and calls == []
    # a different artifact is fetched through resolve and written
    r = SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"artifact": "ab" * 32}},
                           resolve=lambda need: calls.append(need) or {k: {"bytes": b"fetched"} for k in need})
    assert r["written"] == [STAGE] and calls == [{STAGE: {"artifact": "ab" * 32}}]
    assert (dst / STAGE).read_bytes() == b"fetched"
    # the source gains a file and changes one: the next refresh copies both; a stale companion file goes
    SM.write_files(c, GID, "recovery-pool", {"nativeNXx64/ImgNX/Archive/uEm10.arc": {"bytes": b"F" * 32},
                                             "nativeNXx64/ImgNX/Archive/uEm11.arc": {"bytes": b"G" * 8}})
    (dst / "romfs/nativeNXx64/ImgNX/Archive").joinpath("stale.arc").write_bytes(b"old")
    r = SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"bytes": b"fetched"}})
    assert sorted(r["copied_from_source"]) == ["romfs/nativeNXx64/ImgNX/Archive/uEm10.arc",
                                               "romfs/nativeNXx64/ImgNX/Archive/uEm11.arc"]
    assert r["removed"] == ["romfs/nativeNXx64/ImgNX/Archive/stale.arc"] and r["unchanged"] == [STAGE]
    assert files_of(dst) == {"romfs/nativeNXx64/ImgNX/Archive/uEm10.arc": b"F" * 32,
                             "romfs/nativeNXx64/ImgNX/Archive/uEm11.arc": b"G" * 8, STAGE: b"fetched"}
    assert files_of(src) == {"romfs/nativeNXx64/ImgNX/Archive/uEm10.arc": b"F" * 32,
                             "romfs/nativeNXx64/ImgNX/Archive/uEm11.arc": b"G" * 8}


def test_blueprint_waits_for_a_restart_while_the_companion_runs_and_refuses_bad_inputs(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    overlay(c, "recovery-pool")
    monkeypatch.setattr(SM, "running_users", lambda gid, name: ["sid-1"] if name == "recovery-pool-blueprint" else [])
    r = SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"bytes": b"grid"}})
    dst = Path(r["dir"])
    assert r["pending"] is True and not (dst / STAGE).exists() and SM.pending_edits(dst)
    assert SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"bytes": b"grid"}})["unchanged"] == [STAGE]
    monkeypatch.setattr(SM, "running_users", lambda gid, name: [])
    SM.apply_pending(dst)
    assert (dst / STAGE).read_bytes() == b"grid"
    with pytest.raises(ValueError, match="no greybox files"):
        SM.blueprint_build(c, GID, "recovery-pool", {})
    with pytest.raises(ValueError, match="already a blueprint companion"):
        SM.blueprint_build(c, GID, "recovery-pool-blueprint", {STAGE: {"bytes": b"x"}})
    with pytest.raises(ValueError, match="not a Switch LayeredFS build"):
        SM.blueprint_build(c, GID, "nobody", {STAGE: {"bytes": b"x"}})
    with pytest.raises(ValueError, match="one of artifact, from, bytes or b64"):
        SM.blueprint_build(c, GID, "recovery-pool", {STAGE: {"remove": True}})
    with pytest.raises(ValueError, match="resolve"):
        SM.blueprint_build(c, GID, "recovery-pool", {CRATE: {"artifact": "cd" * 32}})
    assert SM.blueprint_name("x") == "x-blueprint" and SM.blueprint_name("x-blueprint") == "x-blueprint"


def test_the_tool_op_names_the_source_build_and_fetches_artifacts(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    overlay(c, "recovery-pool")
    fetched = []
    monkeypatch.setattr(SM, "_catalog", lambda ctx, gid: {"game_id": GID, "platform": "switch", "title": "Resident Evil 5",
                                                            "serial": CREATE["title_id"], "rel_path": CREATE["base"]})
    monkeypatch.setattr(SM, "_facts", lambda ctx, game: (CREATE["title_id"], CREATE["base"]))
    monkeypatch.setattr(SM, "_collection_elsewhere", lambda ctx, gid, name: False)
    monkeypatch.setattr(SM, "_resolve", lambda ctx, ch: fetched.append(ch) or {k: {"bytes": b"grid-" + k[-8:].encode()} for k in ch})
    ctx = type("Ctx", (), {"config": c, "server": "http://spark", "headers": {}, "job_id": "j1",
                           "progress": staticmethod(lambda *a, **k: None)})()
    out = SM.switch_mods_tool(SM.SwitchModsIn(op="blueprint", game_id=GID, build="recovery-pool",
                                              changes={STAGE: {"artifact": "aa" * 32}}), ctx)
    assert out["result"]["op"] == "blueprint" and out["result"]["mod"] == "recovery-pool-blueprint"
    assert fetched == [{STAGE: {"artifact": "aa" * 32}}] and out["result"]["written"] == [STAGE]
    assert "blueprint_look" in out["result"]["note"]
    with pytest.raises(ValueError, match="name the source build"):
        SM.switch_mods_tool(SM.SwitchModsIn(op="blueprint", game_id=GID, build="", changes={STAGE: {"bytes": b"x"}}), ctx)
