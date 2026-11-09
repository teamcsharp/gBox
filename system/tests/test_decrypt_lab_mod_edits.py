"""Panel mod actions publish tracked overlays and leave running builds unchanged until restart."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from gbox import decrypt_lab as L, switch_mods as S
from gbox.config import Config

TID = "010018100CD46000"
GID = "52d15709be0fda1a"
PREFIX = "nativeNXx64/ImgNX/Archive/"


@pytest.fixture
def panel(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(S, "running_users", lambda *a: [])
    romfs = tmp_path / "gBox_alt" / "switch" / "romfs" / TID
    (romfs / PREFIX).mkdir(parents=True)
    for name in ("uPl00ChrisNormal.arc", "uPl02JillCos1.arc", "uEm10.arc", "uEm11.arc"):
        (romfs / PREFIX / name).write_bytes(name.encode())
    rows = [(GID, json.dumps({"serial": TID}))]
    store = SimpleNamespace(db=SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchall=lambda: rows)))
    app = FastAPI()
    L.install(app, store, cfg, lambda: None)
    routes = {r.path: r.endpoint for r in app.routes}
    monkeypatch.setattr(L, "_swap_arc_bytes", lambda *a, **kw: (b"replacement", {
        "slot": "chris", "donor": "jill", "mesh": [], "maps": ["BM"], "textures_added": []}))
    return cfg, romfs, routes


def skin_input():
    return L.ModelSwapIn(title="re5_switch", build="panel-test", arc_path=PREFIX + "uPl00ChrisNormal.arc",
                         donor_arc=PREFIX + "uPl02JillCos1.arc")


def test_skin_edit_has_manifest_history_and_can_be_reverted(panel):
    cfg, _, routes = panel
    result = routes["/api/decrypt-lab/model-swap"](skin_input())
    folder = S.build_dir(cfg, GID, "panel-test")
    rel = "romfs/" + skin_input().arc_path
    marker = S.read_meta(folder)
    assert result["ok"] and not result["pending"]
    assert marker["history"][-1]["id"] == result["edit"]
    assert rel in marker["files"]
    assert (folder / rel).read_bytes() == b"replacement"
    S.revert(cfg, GID, "panel-test", result["edit"])
    assert not (folder / rel).exists()


def test_live_overlay_edit_waits_for_restart_and_preserves_backup(panel, monkeypatch):
    cfg, _, routes = panel
    rel = "romfs/" + skin_input().arc_path
    S.write_files(cfg, GID, "panel-test", {rel: {"bytes": b"prior"}}, create={"title_id": TID})
    folder = S.build_dir(cfg, GID, "panel-test")
    monkeypatch.setattr(S, "running_users", lambda *a: ["session"])
    result = routes["/api/decrypt-lab/model-swap"](skin_input())
    assert result["pending"] and (folder / rel).read_bytes() == b"prior"
    assert len(S.pending_edits(folder)) == 1
    S.apply_pending(folder)
    assert (folder / rel).read_bytes() == b"replacement"
    S.revert(cfg, GID, "panel-test", result["edit"])
    assert (folder / rel).read_bytes() == b"prior"


def test_native_character_plan_writes_nothing_and_build_keeps_donor_bytes(panel):
    cfg, romfs, routes = panel
    endpoint = routes["/api/decrypt-lab/character-swap"]
    inp = L.CharacterSwapIn(**skin_input().model_dump(), plan_only=True)
    plan = endpoint(inp)
    assert plan["plan_only"] and not cfg.cache.exists()
    result = endpoint(inp.model_copy(update={"plan_only": False}))
    assert result["ok"] and not result["replacement_scope"]["complete"]
    assert not result["replacement_scope"]["gameplay_verified"]
    target = S.build_dir(cfg, GID, "panel-test") / "romfs" / inp.arc_path
    assert target.read_bytes() == (romfs / inp.donor_arc).read_bytes()


def test_native_archive_paths_cannot_escape_the_romfs(panel):
    cfg, _, routes = panel
    with pytest.raises(HTTPException):
        routes["/api/decrypt-lab/character-swap"](L.CharacterSwapIn(
            title="re5_switch", arc_path="../outside.arc", donor_arc="uPl00ChrisNormal.arc"))
    assert not cfg.cache.exists()


def test_native_class_rebind_requires_existing_matching_main_before_writing(panel):
    from gbox import mt_arc, re5_ips
    from tests.test_re5_ips_class_rebind import supported_main
    cfg, romfs, routes = panel
    donor = mt_arc.build(mt_arc.Arc(7, [mt_arc.Entry("em1000", 0, 0, 3, 0, b"arc")]))
    (romfs / PREFIX / "uEm10.arc").write_bytes(donor)
    inp = L.CharacterSwapIn(title="re5_switch", build="rebind", arc_path=PREFIX + "uEm11.arc",
                            donor_arc=PREFIX + "uEm10.arc")
    endpoint = routes["/api/decrypt-lab/character-swap"]
    with pytest.raises(HTTPException, match="existing verified"):
        endpoint(inp)
    assert not cfg.cache.exists()
    main = cfg.cache / "exefs" / TID / "main.bin"
    main.parent.mkdir(parents=True)
    main.write_bytes(supported_main())
    result = endpoint(inp)
    assert result["ok"] and "exefs/main.ips" in result["files"]
    folder = S.build_dir(cfg, GID, "rebind")
    assert (folder / "exefs/main.ips").read_bytes() == re5_ips.make_ips()
    assert (folder / re5_ips.ARCHIVE_PATH).read_bytes() == donor


def test_enemy_set_is_one_reversible_edit_and_failed_set_writes_nothing(panel, monkeypatch):
    from gbox import model_swap
    cfg, _, routes = panel
    monkeypatch.setattr(model_swap, "swap_models", lambda *a, **kw: {
        "data": b"cast texture", "meshes": [], "textures": []})
    body = L.ZombieCastIn(title="re5_switch", build="cast-test", donors=["chris"], max_growth=0)
    result = routes["/api/decrypt-lab/zombie-cast"](body)
    assert result["ok"] and result["swapped"] == 2
    folder = S.build_dir(cfg, GID, "cast-test")
    assert len(S.read_meta(folder)["history"]) == 1
    assert len(S.read_meta(folder)["files"]) == 2
    def refuse(*a, **kw):
        raise model_swap.SwapError("no compatible material")
    monkeypatch.setattr(model_swap, "swap_models", refuse)
    failed = routes["/api/decrypt-lab/zombie-cast"](body.model_copy(update={"build": "failed-test"}))
    assert not failed["ok"] and not S.build_dir(cfg, GID, "failed-test").exists()
