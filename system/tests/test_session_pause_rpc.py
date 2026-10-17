"""#1123: the pause button reaches the emulator over the live session channel instead of the job queue."""
import pytest

from gbox import tools


class Emulator:
    name = "fake"

    def __init__(self, supported=("pause", "resume")):
        self.supported, self.calls = set(supported), []

    def pause(self):
        self.calls.append("pause")
        return {"running": True, "state": "PAUSED"}

    def resume(self):
        self.calls.append("resume")
        return {"running": True, "state": "PLAYING"}


def test_session_channel_pauses_and_resumes(monkeypatch):
    ad = Emulator()
    monkeypatch.setitem(tools.SESSIONS, "w-s1", (ad, {}))
    assert tools.session_rpc("w-s1", "pause", {})["state"] == "PAUSED"
    assert tools.session_rpc("w-s1", "resume", {})["state"] == "PLAYING"
    assert ad.calls == ["pause", "resume"]


def test_session_channel_refuses_pause_where_the_emulator_cannot(monkeypatch):
    ad = Emulator(supported=())
    monkeypatch.setitem(tools.SESSIONS, "w-s2", (ad, {}))
    with pytest.raises(tools.Unsupported):
        tools.session_rpc("w-s2", "pause", {})
    assert ad.calls == []


def test_server_lets_pause_and_resume_use_the_session_channel():
    from pathlib import Path
    src = (Path(tools.__file__).parent / "server.py").read_text()
    route = src[src.index('@app.post("/api/sessions/{sid}/rpc")'):src.index('@app.post("/api/sessions/{sid}/rpc/{rid}")')]
    allowed = route[route.index("if req.op not in"):route.index("raise HTTPException(422")]
    audited = route[route.index('if req.op in ("reset"'):route.index("store.audit(")]
    for op in ("pause", "resume"):
        assert f'"{op}"' in allowed and f'"{op}"' in audited


def test_live_channel_replies_share_one_keepalive_client(monkeypatch):
    ad = Emulator()
    monkeypatch.setitem(tools.SESSIONS, "w-s3", (ad, {}))

    class Client:
        def __init__(self):
            self.posts = []

        def post(self, url, json):
            self.posts.append((url, json))

    client = Client()
    answer = tools._rpc_answerer("w-s3", client)
    answer({"rpc": "r1", "op": "pause", "args": {}})
    answer({"rpc": "r2", "op": "bogus"})
    assert client.posts[0] == ("/api/sessions/w-s3/rpc/r1", {"ok": True, "data": {"running": True, "state": "PAUSED"}})
    assert client.posts[1][0] == "/api/sessions/w-s3/rpc/r2" and client.posts[1][1]["ok"] is False
    import inspect
    assert "_rpc_answerer(sid, httpx.Client(" in inspect.getsource(tools._pump)
