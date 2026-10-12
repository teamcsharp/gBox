"""Unit tests for the gbox mashup planner."""
import json
from types import SimpleNamespace

import pytest

from gbox import mashup as M


class _Ctx(SimpleNamespace):
    def __init__(self):
        super().__init__(server="http://test", headers={})
        self._artifacts = []

    def artifact(self, name, content, media_type, **meta):
        self._artifacts.append((name, content, media_type, meta))
        return "sha256:test"


CHARS = [
    {"slug": "mario-64", "name": "Mario", "aliases": ["Super Mario"],
     "rig": {"roles": ["player"]}, "source": {"game_id": "g1", "game_title": "Super Mario 64"}},
    {"slug": "link-oot", "name": "Link", "aliases": [],
     "rig": {"roles": ["player"]}, "source": {"game_id": "g2", "game_title": "Zelda: Ocarina of Time"}},
    {"slug": "ganondorf-oot", "name": "Ganondorf", "aliases": [],
     "rig": {"roles": ["boss"]}, "source": {"game_id": "g2", "game_title": "Zelda: Ocarina of Time"}},
]

GAMES = {
    "g1": {"game_id": "g1", "title": "Super Mario 64", "platform": "n64"},
    "g2": {"game_id": "g2", "title": "Zelda: Ocarina of Time", "platform": "n64"},
    "g3": {"game_id": "g3", "title": "Metal Arms: Glitch in the System", "platform": "gc"},
}


def _fake_api(ctx, method, path, **kw):
    if method == "GET" and path == "/api/characters":
        return CHARS
    if method == "GET" and path == "/api/catalog/best":
        q = kw.get("params", {}).get("q", "").lower()
        for g in GAMES.values():
            if q in g["title"].lower():
                return [g]
        return []
    if method == "GET" and path.startswith("/api/catalog/"):
        gid = path.rsplit("/", 1)[-1]
        return GAMES.get(gid, {"game_id": gid, "title": "Unknown", "platform": "?"})
    raise RuntimeError(f"unexpected {method} {path}")


def test_parse_request_in(monkeypatch):
    monkeypatch.setattr(M, "_api", _fake_api)
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="Mario in Ocarina of Time"), ctx)
    r = out["result"]
    assert r["understood"]["source_slug"] == "mario-64"
    assert r["understood"]["target_game_id"] == "g2"
    assert any(s["action"] == "check_feasibility" for s in r["plan"])


def test_explicit_source_target(monkeypatch):
    monkeypatch.setattr(M, "_api", _fake_api)
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(source="Ganondorf", target="Zelda: Ocarina of Time"), ctx)
    r = out["result"]
    assert r["understood"]["source_slug"] == "ganondorf-oot"
    assert r["understood"]["target_game_id"] == "g2"


def test_dry_run_ready_no_writer(monkeypatch):
    # metal arms has no routed writer in our fake coverage, but it has extractor fallback
    monkeypatch.setattr(M, "_api", _fake_api)
    monkeypatch.setattr(M.CC, "writer_for", lambda game: None)
    monkeypatch.setattr(M.CC, "extractor_for", lambda game: ("some_extractor", []))
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="Mario in Metal Arms"), ctx)
    r = out["result"]
    assert r["status"] in ("needs_writer", "ready_to_dispatch")


def test_unresolvable_request(monkeypatch):
    monkeypatch.setattr(M, "_api", _fake_api)
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="abcdefg in zzzzzzz"), ctx)
    r = out["result"]
    assert r["status"] == "unresolvable"


def test_artifact_saved(monkeypatch):
    monkeypatch.setattr(M, "_api", _fake_api)
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="Mario in Ocarina of Time"), ctx)
    assert ctx._artifacts
    assert ctx._artifacts[0][0] == "mashup-plan.json"
    payload = json.loads(ctx._artifacts[0][1])
    assert payload["understood"]["source_slug"] == "mario-64"
