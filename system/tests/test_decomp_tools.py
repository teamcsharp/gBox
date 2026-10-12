"""Focused tests for the decomp.me / IDA Pro / N64Recomp integration tools.

No network, no IDA install and no cargo run: request building, token gating,
install discovery, MCP config writing, toolchain detection and the command
builders are tested directly.
"""
import json
import os
import subprocess

import pytest

from gbox import decomp_tools as dt
from gbox.config import Config
from gbox.registry import REGISTRY


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path / "data")


class FakeCtx:
    def __init__(self, config):
        self.config = config
        self.log = []


def test_config_defaults_and_env_token(monkeypatch, cfg):
    assert cfg.ida_home is None
    assert cfg.decompme_token is None
    assert dt._decompme_token(cfg) is None
    monkeypatch.setenv("DECOMPME_TOKEN", "tok")
    assert dt._decompme_token(cfg) == "tok"
    cfg.decompme_token = "cfg-tok"
    monkeypatch.delenv("DECOMPME_TOKEN")
    assert dt._decompme_token(cfg) == "cfg-tok"


def test_decompme_request_builds_url_and_auth(monkeypatch, cfg):
    captured = {}

    def fake_request(method, url, params=None, json=None, headers=None, timeout=None):
        captured.update(method=method, url=url, params=params, body=json, headers=headers)

        class Response:
            status_code = 200
            content = b'{"ok": true}'
            text = '{"ok": true}'

        return Response()

    monkeypatch.setattr(dt.httpx, "request", fake_request)
    out = dt._dm_request(FakeCtx(cfg), "GET", "scratch/foo", params={"platform": "n64"}, token="secret")
    assert out == {"ok": True}
    assert captured["url"] == "https://api.decomp.dev/scratch/foo"
    assert captured["headers"]["authorization"] == "Bearer secret"
    assert captured["params"] == {"platform": "n64"}


def test_decompme_empty_response_requires_token(monkeypatch, cfg):
    def fake_request(*args, **kwargs):
        class Response:
            status_code = 200
            content = b""
            text = ""

        return Response()

    monkeypatch.setattr(dt.httpx, "request", fake_request)
    with pytest.raises(RuntimeError, match="requires a token"):
        dt._dm_request(FakeCtx(cfg), "GET", "scratch/foo")
    # With a token the same shape fails for a different, explicit reason.
    with pytest.raises(RuntimeError, match="empty response"):
        dt._dm_request(FakeCtx(cfg), "GET", "scratch/foo", token="secret")


def test_decompme_http_error_surfaced(monkeypatch, cfg):
    def fake_request(*args, **kwargs):
        class Response:
            status_code = 401
            content = b"unauthorized"
            text = "unauthorized"

        return Response()

    monkeypatch.setattr(dt.httpx, "request", fake_request)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        dt._dm_request(FakeCtx(cfg), "GET", "scratch/foo", token="bad")


def test_decompme_mutation_requires_token(monkeypatch, cfg):
    calls = []

    def fake_execute(name, raw_input, ctx):
        calls.append(name)
        return {"op": "create", "status": "ok", "data": {}, "token_used": False}

    monkeypatch.setattr("gbox.registry.execute", fake_execute)
    # Without a token the tool itself refuses, before any HTTP round trip.
    with pytest.raises(RuntimeError, match="publishes code publicly"):
        dt.decompme(dt.DecompMeIn(op="create", payload={"platform": "n64"}), FakeCtx(cfg))


def test_ida_locate_via_config(cfg, tmp_path):
    home = tmp_path / "ida"
    home.mkdir()
    (home / "ida64").write_text("fake")
    cfg.ida_home = str(home)
    info = dt._ida_home(cfg)
    assert info == home
    assert dt._ida_binary(cfg) == home / "ida64"


def test_ida_analyze_command_shape(cfg, tmp_path):
    binary = tmp_path / "ida64"
    binary.write_text("fake")
    idc = tmp_path / "gbox_export.idc"
    out = tmp_path / "analysis.json"
    cmd = dt._analyze_command(binary, "game.z64", out, idc)
    assert cmd[0] == str(binary)
    assert "-A" in cmd and "-B" in cmd
    script_arg = next(a for a in cmd if a.startswith("-S"))
    assert str(idc) in script_arg and str(out) in script_arg
    assert cmd[-1] == "game.z64"


def test_ida_mcp_config_written(tmp_path):
    user = tmp_path / "idauser"
    user.mkdir()
    cfg_path = dt._write_mcp_config(user, 13337)
    text = cfg_path.read_text(encoding="utf-8")
    assert cfg_path.parent.name == "ida_mcp"
    assert 'port = 13337' in text and 'check_port = false' in text


def test_ida_rea_hint(monkeypatch):
    hint = dt._rea_hint(13337)
    assert json.loads(hint["REA_IDA_MCP_CONFIG"]) == {"type": "http", "url": "http://127.0.0.1:13337/mcp"}


def test_n64recomp_toolchain_detection(monkeypatch):
    real_which = dt.shutil.which
    monkeypatch.setattr(dt.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("git", "cargo") else real_which(name))
    tc = dt._toolchain()
    assert tc["git"] == "/usr/bin/git"
    assert tc["cargo"] == "/usr/bin/cargo"


def test_n64recomp_generate_command(cfg, tmp_path):
    repo = tmp_path / "N64Recomp"
    toml = tmp_path / "RecompModInfo.toml"
    cmd = dt._generate_command(repo, "game.z64", toml)
    assert cmd[0].endswith("cargo") or cmd[0] == "cargo"
    assert "--manifest-path" in cmd and "--rom" in cmd and "game.z64" in cmd
    assert str(toml) in cmd


def test_registry_registers_the_three_tools():
    for name in ("decompme", "ida_pro", "n64recomp"):
        assert name in REGISTRY, f"{name} missing from REGISTRY"
    assert REGISTRY["decompme"].capabilities == ["reverse-engineering", "decompilation", "network"]
    assert REGISTRY["ida_pro"].capabilities == ["reverse-engineering", "analysis", "ida"]
    assert "recompilation" in REGISTRY["n64recomp"].capabilities
    # Mutating decomp.me ops must declare the public publication side effect.
    assert any("publicly" in s for s in REGISTRY["decompme"].side_effects)
