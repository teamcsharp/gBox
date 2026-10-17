"""Tests for the generic Unreal Engine Steam analysis module.

These tests run on the Linux build host using synthetic Steam installs; they never
need a real Windows Steam client because every path can be passed through a Config.
"""
import json
import struct
import sys
from pathlib import Path

import pytest

from gbox import catalog, config, ue_steam
from gbox.registry import Ctx


def _make_steam_root(tmp_path: Path, appid: str, name: str) -> Path:
    root = tmp_path / "steam"
    steamapps = root / "steamapps"
    steamapps.mkdir(parents=True)
    root_str = str(root).replace("\\", "\\")
    (steamapps / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root_str}"\n\t}}\n}}\n'
    )
    common = steamapps / "common"
    common.mkdir()
    gd = common / name
    gd.mkdir()
    (steamapps / f"appmanifest_{appid}.acf").write_text(
        f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{name}"\n\t"buildid"\t\t"123"\n\t"SizeOnDisk"\t\t"999"\n}}\n'
    )
    return gd


@pytest.fixture
def fake_ue_game(tmp_path: Path):
    gd = _make_steam_root(tmp_path, "12345", "FakeUEGame")
    # Main executable
    (gd / "FakeUEGame-Win64-Shipping.exe").write_bytes(b"UE4 4.27\x00UCharacterMovementComponent\x00MaxWalkSpeed")
    # Build.version
    (gd / "Engine" / "Build").mkdir(parents=True)
    (gd / "Engine" / "Build" / "Build.version").write_text(json.dumps({"MajorVersion": 4, "MinorVersion": 27, "PatchVersion": 2}))
    # Pak files
    (gd / "Content" / "Paks").mkdir(parents=True)
    (gd / "Content" / "Paks" / "fake-WindowsNoEditor.pak").write_bytes(b"PAK0")
    (gd / "Content" / "Paks" / "fake-WindowsNoEditor_P.pak").write_bytes(b"PAK1")
    # Binaries
    (gd / "FakeUEGame" / "Binaries" / "Win64").mkdir(parents=True)
    (gd / "FakeUEGame" / "Binaries" / "Win64" / "FakeUEGame-Win64-Shipping.dll").write_bytes(b"UAnimInstance\x00PlayAnim")
    cfg = config.Config(steam_root=tmp_path / "steam")
    return gd, cfg


def test_default_steam_root_is_none_off_windows(monkeypatch):
    monkeypatch.setattr(catalog.sys, "platform", "linux")
    assert catalog.default_steam_root() is None


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Steam registry key of this PC")
def test_default_steam_root_on_windows_is_a_path_or_none():
    root = catalog.default_steam_root()
    assert root is None or isinstance(root, Path)


def test_steam_root_prefers_config_then_registry(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(ue_steam, "default_steam_root", lambda: tmp_path / "registry-steam")
    assert ue_steam.steam_root(config.Config(steam_root=tmp_path / "cfg-steam")) == tmp_path / "cfg-steam"
    assert ue_steam.steam_root(config.Config()) == tmp_path / "registry-steam"
    monkeypatch.setattr(ue_steam, "default_steam_root", lambda: None)
    assert ue_steam.steam_root(config.Config()) is None


def test_scan_steam_finds_ue_game(fake_ue_game):
    gd, cfg = fake_ue_game
    entries, problems = catalog.scan_steam(cfg.steam_root)
    assert not problems
    assert any(e.game_id == "steam-12345" and e.platform == "pc_steam" for e in entries)


def test_game_dir_resolves(fake_ue_game):
    gd, cfg = fake_ue_game
    assert ue_steam.game_dir("12345", cfg) == gd


def test_game_dir_raises_when_not_installed(tmp_path: Path):
    cfg = config.Config(steam_root=_make_steam_root(tmp_path, "99999", "OtherGame"))
    with pytest.raises(FileNotFoundError):
        ue_steam.game_dir("12345", cfg)


def test_safety_ok(fake_ue_game):
    gd, _ = fake_ue_game
    s = ue_steam.safety(gd)
    assert s["ok"] is True
    assert not s["anticheat_files"]


def test_safety_flags_anticheat(fake_ue_game):
    gd, _ = fake_ue_game
    (gd / "BattlEye").mkdir()
    (gd / "BattlEye" / "BEService.exe").write_text("svc")
    s = ue_steam.safety(gd)
    assert s["ok"] is False
    assert any("BattlEye" in p for p in s["anticheat_files"])


def test_engine_version_from_build_version(fake_ue_game):
    gd, _ = fake_ue_game
    v = ue_steam.engine_version(gd)
    assert v["source"] == "Engine/Build/Build.version"
    assert v["major"] == 4
    assert v["minor"] == 27


def test_pak_index(fake_ue_game):
    gd, _ = fake_ue_game
    paks = ue_steam.run_pak_index(gd)
    names = {p["path"] for p in paks}
    assert "Content/Paks/fake-WindowsNoEditor.pak" in names
    assert "Content/Paks/fake-WindowsNoEditor_P.pak" in names
    for p in paks:
        assert p["sha256"] is not None


def test_status_counts_paks_without_hashing(fake_ue_game, monkeypatch):
    gd, cfg = fake_ue_game

    def _no_hash(p):
        raise AssertionError(f"status must not hash {p}")

    monkeypatch.setattr(ue_steam, "_sha256", _no_hash)
    out = ue_steam.ue_steam_tool(ue_steam.UESteamIn(op="status", appid="12345"), Ctx(cfg))
    assert out["result"]["installed"] is True
    assert out["result"]["paks"] == 2
    assert out["result"]["engine"]["version"] == "4.27.2"


def test_locomotion_classifier():
    analysis = {
        "functions": [
            {"name": "UCharacterMovementComponent::PhysWalking", "entryPoint": "0x1000"},
            {"name": "AFakeCharacter::UpdateLocomotionState", "entryPoint": "0x2000"},
            {"name": "SomeUnrelatedFunction", "entryPoint": "0x3000"},
        ],
        "strings": [
            {"string": "MaxWalkSpeed", "address": "0xa000"},
            {"string": "UAnimInstance::NativeUpdateAnimation", "address": "0xb000"},
            {"string": "random unrelated string", "address": "0xc000"},
        ],
        "program": {"name": "fake.exe"},
    }
    hits = ue_steam._analyze_artifact(json.dumps(analysis).encode())
    symbols = {h["symbol"] for h in hits}
    assert "UCharacterMovementComponent" in symbols
    assert "MaxWalkSpeed" in symbols
    assert "UAnimInstance" in symbols
    assert "SomeUnrelatedFunction" not in symbols
    assert "random unrelated string" not in symbols


def test_static_analysis_blocks_anticheat(fake_ue_game):
    gd, _ = fake_ue_game
    (gd / "EasyAntiCheat").mkdir()
    (gd / "EasyAntiCheat" / "EasyAntiCheat_Setup.exe").write_text("x")
    r = ue_steam.run_static_analysis(gd, None)
    assert r["safe"] is False


def test_static_analysis_no_executable(fake_ue_game):
    gd, _ = fake_ue_game
    (gd / "FakeUEGame-Win64-Shipping.exe").unlink()
    r = ue_steam.run_static_analysis(gd, None)
    assert r["safe"] is True
    assert "error" in r


def test_static_analysis_uses_artifact(fake_ue_game, monkeypatch):
    gd, _ = fake_ue_game
    analysis = {"functions": [{"name": "UCharacterMovementComponent::PhysWalking", "entryPoint": "0x1000"}],
                "strings": [], "program": {"name": "fake.exe"}}
    artifact = json.dumps(analysis).encode()

    def _fake_ghidra(binary_path, ctx):
        return {"functions": 1, "strings": 0, "program": {"name": binary_path.name},
                "artifact": artifact, "sha256": "00" * 32}

    monkeypatch.setattr(ue_steam, "_ghidra_analysis", _fake_ghidra)
    ctx = Ctx(config.Config())
    (gd / "FakeUEGame-Win64-Shipping.exe").write_bytes(b"dummy")
    r = ue_steam.run_static_analysis(gd, ctx)
    assert r["safe"] is True
    assert any(h["symbol"] == "UCharacterMovementComponent" for h in r["candidates"])
    assert ctx._pct > 0


@pytest.mark.skipif(sys.platform != "win32", reason="tool registration is Windows-only")
def test_ue_steam_tool_status_not_installed(tmp_path: Path):
    cfg = config.Config(steam_root=_make_steam_root(tmp_path, "99999", "OtherGame"))
    ctx = Ctx(cfg)
    from gbox.registry import REGISTRY
    out = REGISTRY["ue_steam"].fn(ue_steam.UESteamIn(op="status", appid="12345"), ctx)
    assert out["result"]["installed"] is False


# ---------------------------------------------------------------------- pak ops (synthetic paks, no game data)

@pytest.fixture
def pak_game(tmp_path: Path):
    import ue_synth as S
    gd = _make_steam_root(tmp_path, "4242", "SynthGame")
    paks = gd / "Game" / "Content" / "Paks"
    paks.mkdir(parents=True)
    (paks / "Game-WindowsNoEditor.pak").write_bytes(S.build_pak(S.game_files(), 11, "Zlib", block_size=0x800))
    # A patch pak overriding the ini, and a non-Unreal Chromium resources.pak that must be skipped.
    (paks / "Game-WindowsNoEditor_P.pak").write_bytes(S.build_pak({"Game/Config/DefaultGame.ini": b"patched"}, 11))
    (gd / "resources.pak").write_bytes(b"\x05\x00\x00\x00" + b"\0" * 200)
    (gd / "Engine" / "Build").mkdir(parents=True)
    (gd / "Engine" / "Build" / "Build.version").write_text(json.dumps({"MajorVersion": 4, "MinorVersion": 27, "PatchVersion": 2}))
    cfg = config.Config(steam_root=tmp_path / "steam", data_dir=tmp_path / "data")
    return gd, cfg


def _op(cfg, **kw):
    ctx = Ctx(cfg)
    return ue_steam.ue_steam_tool(ue_steam.UESteamIn(appid="4242", title="Synth", **kw), ctx)["result"], ctx


def test_inventory_manifest(pak_game):
    gd, cfg = pak_game
    r, ctx = _op(cfg, op="inventory")
    assert r["safe"] and r["engine"]["minor"] == 27
    assert {p["status"] for p in r["paks"]} == {"ok"}                   # resources.pak dropped as not_unreal
    assert r["counts"]["skeletal_mesh"] == 1 and r["counts"]["skeleton"] == 1 and r["counts"]["animation"] == 1
    assert r["counts"]["pawn_actors"] == 2                                # BP_Hero (Character) and BP_Villain (BP_Hero)
    hero = next(a for a in r["actors"] if a["class"] == "BP_Hero_C")
    assert hero["pawn_base"] == "Character" and hero["skeletal_meshes"] == ["/Game/Char/SK_Test.SK_Test"]
    man = json.loads(Path(r["manifest"]).read_text())
    assert man["schema"] == "gbox.ue_inventory/1" and man["assets"]["animation"][0]["export"] == "Run_Fwd"
    assert Path(r["manifest"]).is_relative_to(cfg.data_dir)
    assert [a[0] for a in ctx.artifacts] == ["ue_inventory.json"]


def test_list_files_and_patch_override(pak_game):
    gd, cfg = pak_game
    r, _ = _op(cfg, op="list_files", paths=["*.ini"])
    assert r["matched"] == 1 and r["entries"][0]["size"] == len(b"patched")


def test_extract_writes_outside_the_install_only(pak_game):
    gd, cfg = pak_game
    before = sorted(p.relative_to(gd).as_posix() for p in gd.rglob("*"))
    r, _ = _op(cfg, op="extract", paths=["SK_Test"])
    got = sorted(Path(x["path"]).name for x in r["extracted"])
    assert got == ["SK_Test.uasset", "SK_Test.uexp"]
    for x in r["extracted"]:
        assert Path(x["file"]).is_file() and not Path(x["file"]).resolve().is_relative_to(gd.resolve())
    assert sorted(p.relative_to(gd).as_posix() for p in gd.rglob("*")) == before     # install untouched
    r, _ = _op(cfg, op="extract")
    assert "paths" in r["error"]
    with pytest.raises(ValueError, match="game install"):
        _op(cfg, op="extract", paths=["SK_Test"], out_dir=str(gd / "out"))


def test_export_glb_and_skeleton(pak_game):
    gd, cfg = pak_game
    r, ctx = _op(cfg, op="export", paths=["Char/SK_Test"])
    assert r["glb_count"] == 1 and r["skeleton_count"] == 1
    mesh = next(x for x in r["results"] if x.get("glb"))
    assert mesh["vertices"] == 4 and mesh["bones"] == 3 and Path(mesh["glb"]).read_bytes()[:4] == b"glTF"
    assert [a[0] for a in ctx.artifacts] == ["SK_Test.glb"]
    r, _ = _op(cfg, op="export", paths=["Char/SK_Test"], engine="4.21")
    assert any("SerializeRenderItem_Legacy" in b for b in r["blockers"])


def test_pak_ops_refuse_anticheat_before_opening_archives(pak_game, monkeypatch):
    gd, cfg = pak_game
    be = gd / "Game" / "Binaries" / "Win64" / "BattlEye"
    be.mkdir(parents=True)
    (be / "BEClient_x64.dll").write_bytes(b"MZ")

    def _boom(*a, **k):
        raise AssertionError("archives must not be opened for an anti-cheat game")

    monkeypatch.setattr(ue_steam, "GameArchive", _boom)
    for op in ("list_files", "inventory", "extract", "export"):
        r, _ = _op(cfg, op=op, paths=["x"])
        assert r["safe"] is False and any("BattlEye" in p for p in r["anticheat_files"])


def test_encrypted_game_reports_key_needed(tmp_path):
    import ue_synth as S
    gd = _make_steam_root(tmp_path, "4242", "Locked")
    (gd / "Locked.pak").write_bytes(S.build_pak(S.game_files(), 11, encrypt_index=True))
    cfg = config.Config(steam_root=tmp_path / "steam", data_dir=tmp_path / "data")
    r, _ = _op(cfg, op="inventory")
    assert r["paks"][0]["status"] == "encrypted" and "AES" in r["paks"][0]["error"]
    assert "no readable" in r["error"]


def test_engine_version_from_launcher_release_string(tmp_path):
    gd = tmp_path / "G"
    gd.mkdir()
    blob = b"MZ" + b"\0" * 64 + "++UE4+Release-4.26".encode("utf-16-le") + b"\0" * 8
    blob += "VS_VERSION_INFO".encode("utf-16-le") + b"\0" * 4 + b"\xbd\x04\xef\xfe" + struct.pack("<IIII", 0x10000, (4 << 16) | 26, 2 << 16, 0)
    (gd / "G.exe").write_bytes(blob)
    v = ue_steam.engine_version(gd)
    assert (v["major"], v["minor"], v["patch"]) == (4, 26, 2) and "release string" in v["source"]


def test_resolve_engine_falls_back_to_pak_version(tmp_path):
    e = ue_steam.resolve_engine(tmp_path, "", [{"status": "ok", "version": 4}])
    assert (e["major"], e["minor"]) == (4, 19) and "guessed" in e["source"]
    assert ue_steam.resolve_engine(tmp_path, "4.25")["minor"] == 25
