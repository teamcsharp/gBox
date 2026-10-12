"""Tests for the generic Unreal Engine Steam analysis module.

These tests run on the Linux build host using synthetic Steam installs; they never
need a real Windows Steam client because every path can be passed through a Config.
"""
import json
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


def test_default_steam_root_is_none_on_linux():
    assert catalog.default_steam_root() is None


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
    out = REGISTRY["ue_steam"].fn({"op": "status", "appid": "12345"}, ctx)
    assert out["result"]["installed"] is False
