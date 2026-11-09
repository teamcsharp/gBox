"""Character writer planning cannot write an overlay, restart a title, or implicitly launch a cast."""
from types import SimpleNamespace

import pytest

from gbox import characters as C, switch_mods as S
from gbox.config import Config

TID = "010018100CD46000"
GAME = {"game_id": "52d15709be0fda1a", "platform": "switch", "title": "Resident Evil 5", "serial": TID}


@pytest.fixture
def writer(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    calls = []
    def api(ctx, method, path, **kw):
        calls.append((method, path, kw))
        return [{"session_id": "sid", "game_id": GAME["game_id"], "state": "running", "mod": "existing"}] if path == "/api/sessions" else {"id": "job"}
    monkeypatch.setitem(S.WRITERS, TID, lambda *a: {"changes": {"body.arc": {"bytes": b"character"}},
                                                 "slots": [{"slot": "player", "donor": "sonic"}]})
    monkeypatch.setattr(S, "running_users", lambda *a: [])
    return SimpleNamespace(config=cfg, job_id="plan-test"), api, calls


def test_a_plan_with_a_live_session_never_writes_or_restarts(writer):
    ctx, api, calls = writer
    inp = C.CharIn(op="cast_swap", source="sonic", session_id="sid", plan_only=True)
    result = S.character_use(ctx, api, None, GAME, inp, op="cast_swap")
    assert result["status"] == "planned" and result["files"] == ["romfs/body.arc"]
    assert not ctx.config.cache.exists()
    assert not any(method == "POST" for method, _, _ in calls)


def test_cast_launch_requires_an_explicit_launch_setting(writer):
    ctx, api, calls = writer
    default = C.CharIn(op="cast_swap", source="sonic", mod_name="cast-plan")
    assert default.launch
    S.character_use(ctx, api, None, GAME, default, op="cast_swap")
    assert not any(path == "/api/jobs" for _, path, _ in calls)
    explicit = C.CharIn(op="cast_swap", source="sonic", mod_name="cast-launch", launch=True)
    S.character_use(ctx, api, None, GAME, explicit, op="cast_swap")
    assert sum(path == "/api/jobs" for _, path, _ in calls) == 1


@pytest.mark.parametrize("session_id", ["", "other"])
def test_live_use_requires_the_requested_current_session(writer, session_id):
    ctx, api, calls = writer
    inp = C.CharIn(op="live_use", character="sonic", session_id=session_id)
    result = S.character_use(ctx, api, {"slug": "sonic"}, GAME, inp, op="live_use")
    assert result["status"] == "failed" and not ctx.config.cache.exists()
    assert not any(method == "POST" for method, _, _ in calls)


def test_historical_same_game_session_cannot_write_or_fall_back_to_launch(writer):
    ctx, _, calls = writer
    def ended_api(ctx, method, path, **kw):
        calls.append((method, path, kw))
        assert method == "GET" and path == "/api/sessions"
        return [{"session_id": "ended", "state": "ended", "game_id": GAME["game_id"], "mod": "old-build"}]
    inp = C.CharIn(op="live_use", character="sonic", session_id="ended")
    result = S.character_use(ctx, ended_api, {"slug": "sonic"}, GAME, inp, op="live_use")
    assert result["status"] == "failed" and not ctx.config.cache.exists()
