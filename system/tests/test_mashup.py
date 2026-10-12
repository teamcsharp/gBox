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
    {"slug": "peach-64", "name": "Peach", "aliases": [],
     "rig": {}, "source": {"game_id": "g1", "game_title": "Super Mario 64"}},          # collected but not yet mapped
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

OOT_WRITER = {"writer": "gbox.oot_swap", "routed": True, "slots": ["player"], "replaces": "Link"}


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


def _job_api(posted, state="succeeded"):
    """A fake control plane that records every POST /api/jobs payload and answers job polls."""
    def api(ctx, method, path, **kw):
        if method == "POST" and path == "/api/jobs":
            posted.append(kw["json"])
            return {"id": f"job-{len(posted)}", "state": state, "output": {"result": {"ok": True}}}
        if method == "GET" and path.startswith("/api/jobs/"):
            return {"id": path.rsplit("/", 1)[-1], "state": state, "output": {"result": {"ok": True}}}
        return _fake_api(ctx, method, path, **kw)
    return api


def test_parse_request_phrasings():
    assert M._parse_request("Mario 64 sprite in Ocarina of Time") == ("mario 64 sprite", "ocarina of time")
    assert M._parse_request("replace Link with Ganondorf") == ("ganondorf", "link")
    assert M._parse_request("replace Link with Ganondorf in Ocarina of Time") == ("ganondorf", "ocarina of time")
    assert M._parse_request("swap Link and Ganondorf") == ("ganondorf", "link")
    assert M._parse_request("metal gear solid 2 snake in metal gear solid 1") == ("metal gear solid 2 snake", "metal gear solid 1")


def test_api_needs_the_control_plane():
    with pytest.raises(RuntimeError, match="ctx.server"):
        M._api(SimpleNamespace(server=None, headers={}), "GET", "/api/characters")


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


def test_no_writer_is_needs_writer_and_submits_nothing(monkeypatch):
    monkeypatch.setattr(M, "_api", _fake_api)                       # raises on any POST
    monkeypatch.setattr(M.CC, "writer_for", lambda game: None)
    monkeypatch.setattr(M.CC, "extractor_for", lambda game: ("some_extractor", []))
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="Mario in Metal Arms", auto_dispatch=True), ctx)
    r = out["result"]
    assert r["status"] == "needs_writer"
    feas = next(s for s in r["plan"] if s["action"] == "check_feasibility")
    assert feas["status"] == "blocked" and "overlay" in feas["fallback"]
    assert any(s["action"] == "file_gap_report" for s in r["plan"])
    assert r["jobs"] == [] and r["job_details"] == []
    assert "overlay" in r["next_action"]


def test_routed_writer_dry_run_is_ready_to_dispatch(monkeypatch):
    monkeypatch.setattr(M, "_api", _fake_api)                       # raises on any POST
    monkeypatch.setattr(M.CC, "writer_for", lambda game: OOT_WRITER)
    monkeypatch.setattr(M.CC, "extractor_for", lambda game: (None, []))
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="Mario in Ocarina of Time", dry_run=True, auto_dispatch=True), ctx)
    r = out["result"]
    assert r["status"] == "ready_to_dispatch" and r["dry_run"] is True
    swap = next(s for s in r["plan"] if s["action"] == "build_and_launch_swap")
    assert swap["status"] == "needed" and "slot=player" in swap["detail"]
    assert r["jobs"] == []


def test_auto_dispatch_submits_use_job(monkeypatch):
    posted = []
    monkeypatch.setattr(M, "_api", _job_api(posted))
    monkeypatch.setattr(M.CC, "writer_for", lambda game: OOT_WRITER)
    monkeypatch.setattr(M.CC, "extractor_for", lambda game: (None, []))
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(request="Mario in Ocarina of Time", auto_dispatch=True), ctx)
    r = out["result"]
    assert posted == [{"tool": "characters", "parent_request_id": None,
                       "input": {"op": "use", "character": "mario-64", "game_id": "g2", "slot": "player"}}]
    assert r["status"] == "dispatched_succeeded" and r["dry_run"] is False
    assert r["jobs"] == [{"tool": "characters", "op": "use", "character": "mario-64", "game_id": "g2", "slot": "player"}]
    assert r["job_details"][0]["id"] == "job-1"
    swap = next(s for s in r["plan"] if s["action"] == "build_and_launch_swap")
    assert swap["status"] == "dispatched"


def test_auto_dispatch_collects_unmapped_source_first(monkeypatch):
    posted = []
    monkeypatch.setattr(M, "_api", _job_api(posted))
    monkeypatch.setattr(M.CC, "writer_for", lambda game: OOT_WRITER)
    monkeypatch.setattr(M.CC, "extractor_for", lambda game: (None, []))
    ctx = _Ctx()
    out = M.mashup(M.MashupIn(source="Peach", target="Ocarina of Time", auto_dispatch=True), ctx)
    r = out["result"]
    assert [(p["tool"], p["input"]["op"]) for p in posted] == [("characters", "collect"), ("characters", "use")]
    assert posted[0]["input"] == {"op": "collect", "game_id": "g1"}
    assert posted[1]["input"]["character"] == "peach-64"
    assert r["status"] == "dispatched_succeeded"
    assert [j["op"] for j in r["jobs"]] == ["collect", "use"]


def test_auto_dispatch_failed_job(monkeypatch):
    posted = []
    monkeypatch.setattr(M, "_api", _job_api(posted, state="failed"))
    monkeypatch.setattr(M.CC, "writer_for", lambda game: OOT_WRITER)
    monkeypatch.setattr(M.CC, "extractor_for", lambda game: (None, []))
    out = M.mashup(M.MashupIn(request="Mario in Ocarina of Time", auto_dispatch=True), _Ctx())
    assert len(posted) == 1
    assert out["result"]["status"] == "dispatched_failed"


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
