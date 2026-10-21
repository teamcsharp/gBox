"""A build rebuilt under the same name in the central collection is fetched again: launch_game only reuses the local
copy whose build marker matches the collection's current one (DOA3 cast tests kept relaunching a stale copy)."""
import hashlib
from types import SimpleNamespace

import httpx

from gbox import filemods


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _mod(root, name, marker: bytes):
    d = root / "mods" / "g1" / name
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_bytes(marker)
    return d


def _collection(monkeypatch, marker: bytes | None, status=200):
    def get(url, headers=None, timeout=None):
        if marker is None:
            return _Resp(status, {})
        return _Resp(status, {"files": [{"path": "disc/x.bin", "size": 1, "sha256": "0" * 64},
                                        {"path": ".gbox-mod.json", "size": len(marker),
                                         "sha256": hashlib.sha256(marker).hexdigest()}]})
    monkeypatch.setattr(httpx, "get", get)


def test_current_copy_is_kept(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path)
    _mod(tmp_path, "cast_x", b'{"built": 1}')
    _collection(monkeypatch, b'{"built": 1}')
    assert filemods.current_local_copy(cfg, "http://spark", {}, "g1", "cast_x") == "cast_x"


def test_rebuilt_build_makes_the_local_copy_stale(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path)
    _mod(tmp_path, "cast_x", b'{"built": 1}')
    _collection(monkeypatch, b'{"built": 2}')
    assert filemods.current_local_copy(cfg, "http://spark", {}, "g1", "cast_x") is None


def test_a_staged_copy_of_the_rebuild_is_used(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path)
    _mod(tmp_path, "cast_x", b'{"built": 1}')
    _mod(tmp_path, "cast_x~abc123", b'{"built": 2}')
    _collection(monkeypatch, b'{"built": 2}')
    assert filemods.current_local_copy(cfg, "http://spark", {}, "g1", "cast_x") == "cast_x~abc123"


def test_unreachable_or_local_only_collection_keeps_the_local_copy(tmp_path, monkeypatch):
    cfg = SimpleNamespace(cache=tmp_path)
    _mod(tmp_path, "cast_x", b'{"built": 1}')
    _collection(monkeypatch, None, status=404)                     # a local-only build
    assert filemods.current_local_copy(cfg, "http://spark", {}, "g1", "cast_x") == "cast_x"

    def down(url, headers=None, timeout=None):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "get", down)
    assert filemods.current_local_copy(cfg, "http://spark", {}, "g1", "cast_x") == "cast_x"
    assert filemods.current_local_copy(cfg, "", {}, "g1", "cast_x") == "cast_x"


def test_launch_game_stages_a_rebuilt_build_instead_of_the_stale_copy():
    import inspect
    from gbox import tools
    src = inspect.getsource(tools._launch_game)
    assert "current_local_copy" in src
    assert "if local_mod is None and ctx.server:" in src          # stale or missing: stage the collection's build
