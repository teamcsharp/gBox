"""#1671: characters op=use died on a bare HTTP 404 for hucast/pso_hucast_h0_c0.glb while the entry was re-collected."""
import json
from types import SimpleNamespace

import httpx
import pytest

from gbox import characters as C


def _ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_CHARACTERS", str(tmp_path / "lib"))
    (tmp_path / "lib").mkdir()
    return SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), server="http://x", headers={})


def _404(path):
    req = httpx.Request("GET", f"http://x{path}")
    return httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))


def test_local_library_file_wins(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    d = tmp_path / "lib" / "hucast"
    d.mkdir()
    (d / "m.glb").write_bytes(b"glTF")
    monkeypatch.setattr(C, "_api", lambda *a, **k: pytest.fail("no API call for a local file"))
    assert C._local_or_fetch(ctx, {"slug": "hucast", "model": "m.glb"}, "m.glb") == d / "m.glb"


def test_transient_404_waits_for_recollect_then_mirrors_atomically(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    calls = []

    def api(_ctx, method, path, **kw):
        if path.endswith("/file/pso_hucast_h0_c0.glb"):
            calls.append(path)
            if len(calls) < 3:                             # absent for two polls, then the re-collect lands
                raise _404(path)
        if path == "/api/characters/hucast":
            return {"slug": "hucast", "model": "pso_hucast_h0_c0.glb"}
        return b"glTF-bytes"

    monkeypatch.setattr(C, "_api", api)
    sleeps = []
    p = C._local_or_fetch(ctx, {"slug": "hucast", "model": "pso_hucast_h0_c0.glb"}, "pso_hucast_h0_c0.glb",
                          sleep=sleeps.append)
    assert p.read_bytes() == b"glTF-bytes" and p.name == "pso_hucast_h0_c0.glb"
    assert not list(p.parent.glob("*.part"))
    assert len(sleeps) == 2 and len(calls) == 3


def test_renamed_model_is_followed(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)
    d = tmp_path / "lib" / "hucast"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"slug": "hucast", "model": "pso_hucast_h1_c0.glb"}))

    def api(_ctx, method, path, **kw):
        if path.endswith("/file/pso_hucast_h0_c0.glb"):
            raise _404(path)
        assert path.endswith("/file/pso_hucast_h1_c0.glb")
        return b"new"

    monkeypatch.setattr(C, "_api", api)
    p = C._local_or_fetch(ctx, {"slug": "hucast", "model": "pso_hucast_h0_c0.glb"}, "pso_hucast_h0_c0.glb",
                          sleep=lambda s: pytest.fail("a rename needs no wait"))
    assert p.name == "pso_hucast_h1_c0.glb" and p.read_bytes() == b"new"


def test_persistent_404_is_actionable(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)

    def api(_ctx, method, path, **kw):
        if "/file/" in path:
            raise _404(path)
        return {"slug": "hucast", "model": "pso_hucast_h0_c0.glb"}

    monkeypatch.setattr(C, "_api", api)
    with pytest.raises(FileNotFoundError, match="op=collect"):
        C._local_or_fetch(ctx, {"slug": "hucast", "model": "pso_hucast_h0_c0.glb"}, "pso_hucast_h0_c0.glb",
                          retries=2, sleep=lambda s: None)


def test_other_http_errors_are_not_swallowed(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path, monkeypatch)

    def api(_ctx, method, path, **kw):
        req = httpx.Request("GET", "http://x")
        raise httpx.HTTPStatusError("401", request=req, response=httpx.Response(401, request=req))

    monkeypatch.setattr(C, "_api", api)
    with pytest.raises(httpx.HTTPStatusError):
        C._local_or_fetch(ctx, {"slug": "hucast", "model": "m.glb"}, "m.glb", sleep=lambda s: None)
