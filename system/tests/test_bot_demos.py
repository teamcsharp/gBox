"""Bot demos on any PC (operator 2026-10-20: "launch bot demos on computers that even I am on and be able to chat about
the gameplay"): the launch marks the session a bot demo, autoplay starts as the operator's demo (never an agent job
waiting for an idle PC), the worker's own calls say they are autoplay's, a frozen bot demo is relaunched (never the
operator's own game), the black watch trusts RAM, and on a PC someone uses the bot never takes their keyboard."""
import io
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from gbox import adapters as A
from gbox import screensaver as S
from gbox import tools as T
from tests.test_screensaver import Store, rig


# --- the control plane: the launch, the session row, a relaunch ---------------------------------------------------------
@pytest.fixture
def app(tmp_path):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    a = create_app(cfg)
    a.state.store.upsert_catalog([{"game_id": "re4", "title": "Resident Evil 4", "platform": "gamecube",
                                   "source_paths": ["re4.iso"], "format": "iso", "profile_id": "re4",
                                   "launch": {"kind": "standalone", "path": "re4.iso"}}])
    return a, TestClient(a, headers={"Authorization": f"Bearer {cfg.token()}"})


def test_bot_demo_on_a_named_pc_is_the_operators_launch_and_its_session_says_so(app):
    a, c = app
    r = c.post("/api/games/re4/launch?node=JAYBUILTFINALE&autoplay=true")
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["agent_use"] is False and job["require_worker"] == "JAYBUILTFINALE"   # no idle-PC admission
    assert job["input"]["jump"] is True                                              # into its menu moment if any
    store = a.state.store
    assert store.get(S.PENDING, job["id"])["agent"] is False
    store.put("session", f"w9-{job['id']}", {"session_id": f"w9-{job['id']}", "game_id": "re4", "state": "running"})
    store.put("session", "w9-other", {"session_id": "w9-other", "game_id": "re4", "state": "running"})
    rows = {s["session_id"]: s for s in c.get("/api/sessions").json()}
    assert rows[f"w9-{job['id']}"]["bot_demo"] is True and "bot_demo" not in rows["w9-other"]


def test_an_agents_bot_demo_stays_an_agent_job(app):
    a, c = app
    job = c.post("/api/games/re4/launch?node=i9-NUC&autoplay=true", headers={"x-gbox-actor": "agent"}).json()
    assert job["agent_use"] is True and a.state.store.get(S.PENDING, job["id"])["agent"] is True


def _reset(c, sid, actor):
    return c.post(f"/api/sessions/{sid}/reset", json={"mode": "restart"}, headers={"x-gbox-actor": actor})


def test_autoplay_relaunches_a_bot_demo_but_never_the_operators_own_game(app):
    a, c = app
    store = a.state.store
    for jid, demo in (("own", False), ("demo", True)):
        store.put("job", jid, {"id": jid, "tool": "launch_game", "actor": "operator", "agent_use": False,
                               "state": "succeeded"})
        store.put("session", f"w9-{jid}", {"session_id": f"w9-{jid}", "game_id": "re4", "state": "running"})
        if demo:
            S.autoplay_on_launch(store, jid, "re4")
    r = _reset(c, "w9-own", "autoplay")
    assert r.status_code == 409 and "operator's own" in r.text
    r = _reset(c, "w9-demo", "autoplay")
    assert r.status_code == 200, r.text
    j = r.json()
    store.put("job", j["id"], store.get("job", j["id"]) | {"cancel": True})   # the test stops the relaunch here
    assert j["actor"] == "autoplay"                                          # recorded as autoplay's, not the operator's


def test_a_relaunched_bot_demo_is_still_a_bot_demo():
    s = Store()
    S.autoplay_on_launch(s, "j1", "re4", actor="operator")
    assert S.bot_demo(s, "w1-j1")["game_id"] == "re4" and S.bot_demo(s, "w1-j2") is None
    assert S.carry_bot_demo(s, "w1-j1", "w1-j2") is True
    assert S.bot_demo(s, "w1-j2")["relaunched_from"] == "w1-j1"
    assert S.carry_bot_demo(s, "w1-zz", "w1-j3") is False                 # not a demo: nothing carried


@pytest.mark.parametrize("launched_by,agent", [("operator", False), ("agent", True)])
def test_a_bot_demo_starts_as_a_demo_by_autoplay(launched_by, agent):
    s, w, saver, calls, tick = rig()
    s.put("setting", S.SETTING, S.settings(s) | {"enabled": False})
    S.autoplay_on_launch(s, "L9", "sc", actor=launched_by, agent=agent)
    s.put("job", "L9", {"id": "L9", "state": "running"})
    s.put("session", "w1-L9", {"session_id": "w1-L9", "game_id": "sc", "state": "running"})
    tick(5)
    tick(S.START_GRACE)
    start = calls[-1]
    assert start["tool"] == "autoplay" and start["input"]["demo"] is True and "screensaver" not in start["input"]
    assert start["agent_use"] is agent                    # an operator's demo is never an agent job


# --- the worker: its calls say autoplay, a frozen demo comes back as a demo ----------------------------------------------
class Http:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, dict(headers or {})))
        if url.endswith("/autoplay-screensaver/result"):
            return SimpleNamespace(status_code=200, json=lambda: {"saved": False}, text="")
        return SimpleNamespace(status_code=200, json=lambda: {"id": "rj"}, text="")

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None, dict(headers or {})))
        return SimpleNamespace(json=lambda: {"state": "succeeded", "output": {"session_id": "w-2"}})


def test_bad_end_calls_are_autoplays_and_restart_the_demo_as_a_demo(monkeypatch):
    http = Http()
    monkeypatch.setattr(T.httpx, "post", http.post)
    monkeypatch.setattr(T.httpx, "get", http.get)
    run = {"sid": "w-1", "bad_end": "hung", "driver": SimpleNamespace(agent_use=False),
           "ctx": SimpleNamespace(server="http://cp", headers={"authorization": "Bearer t", "x-gbox-parent-job": "ap"}),
           "inp": SimpleNamespace(mode="auto", screensaver=False, style={}, demo=True)}
    T._bad_end(run, sleep=lambda s: None)
    assert all(h.get("x-gbox-actor") == "autoplay" and h.get("authorization") for _, _, _, h in http.calls)
    start = http.calls[-1][2]
    assert start["tool"] == "autoplay" and start["input"]["demo"] is True and start["agent_use"] is False
    assert run["recovery"].startswith("relaunched as w-2")


def png(grey):
    b = io.BytesIO()
    Image.new("RGB", (64, 48), (grey, grey, grey)).save(b, "PNG")
    return b.getvalue()


def _watch(run, frames, until=200):
    now = [0.0]
    d = SimpleNamespace(stopped=False)

    def sleep(s):
        now[0] += s
        run["live"]["ram_progress"] = run["live"].get("tick", lambda t: None)(now[0])
        if now[0] > until:
            d.stopped = True
    T._black_watch(run, d, SimpleNamespace(get_frame=lambda: frames), clock=lambda: now[0], sleep=sleep)
    for _ in range(400):
        if d.stopped:
            break
        time.sleep(0.005)
    return d


def test_black_frames_while_ram_moves_are_not_a_hang():
    run = {"sid": "w-1", "thread": None, "live": {"tick": lambda t: int(t // 10)}}    # the menus / clock move on
    _watch(run, png(1))
    assert "bad_end" not in run and run["black_but_running"] >= 3


def test_black_frames_with_nothing_moving_in_ram_still_end_the_run():
    run = {"sid": "w-1", "thread": None, "live": {"tick": lambda t: 7}}               # RAM still: a hang
    d = _watch(run, png(1))
    assert d.stopped and run["bad_end"] == "black"


# --- on a PC someone uses: the bot never takes the keyboard ----------------------------------------------------------------
@pytest.mark.parametrize("front,focus,idle,trusted,verdict", [
    (False, None, 99.0, True, "wait"),                   # another application in front: never type there
    (True, 42, 0.0, True, "send"),                       # the game window has the keyboard
    (True, 7, 1.0, True, "wait"),                        # gBox's coach box / a search field has it: wait
    (True, 7, A.POLITE_IDLE_S + 1, True, "take"),        # nobody touched mouse or keyboard for a while: give it back
    (True, None, 2.0, False, "take")])                   # the focus report can't be trusted here: as before
def test_polite_verdict(front, focus, idle, trusted, verdict):
    assert A.polite_verdict(front, focus, 42, idle, trusted) == verdict


class PoliteAd:
    def __init__(self, held_first=1):
        self.got, self.held_left = [], held_first

    def send_input(self, rows, polite=False):
        assert polite is True
        if self.held_left:
            self.held_left -= 1
            ups = [r for r in rows if not r["down"]]
            self.got.append(("held", ups))
            return {"sent": len(ups), "held": "the operator is typing"}
        self.got.append(("sent", list(rows)))
        return {"sent": len(rows)}


def test_demo_send_presses_again_what_waited_and_always_releases():
    ad = PoliteAd(held_first=1)
    send = T._demo_send(ad)
    send([{"key": "r", "down": True}, {"key": "up", "down": True}])     # the operator is typing: held back
    send([{"key": "a", "down": True}])                                   # now the game has the keyboard
    assert ad.got[0] == ("held", [])
    assert ad.got[1][0] == "sent" and {r["key"] for r in ad.got[1][1] if r["down"]} == {"a", "r", "up"}
    send([{"key": "r", "down": False}])
    assert ad.got[2] == ("sent", [{"key": "r", "down": False}])
    send([{"key": "b", "down": True}, {"key": "b", "down": False}])     # a tap inside one batch keeps its order
    assert ad.got[3] == ("sent", [{"key": "b", "down": True}, {"key": "b", "down": False}])


def test_autoplay_send_by_kind_of_run():
    plain = SimpleNamespace(send_input=lambda rows: rows)
    assert T._autoplay_send(plain, SimpleNamespace(screensaver=None, demo=False)) == plain.send_input
    assert T._autoplay_send(plain, SimpleNamespace(screensaver=None, demo=True)) == plain.send_input   # no polite mode
    polite = PoliteAd(held_first=0)
    assert T._autoplay_send(polite, SimpleNamespace(screensaver=None, demo=True)) != polite.send_input


def test_a_demo_brings_its_game_forward_only_on_an_idle_pc(monkeypatch):
    fronted = []
    monkeypatch.setattr(T, "_front", lambda ad: fronted.append(ad) or True)
    monkeypatch.setattr(T.sys, "platform", "win32")
    from gbox import worker
    monkeypatch.setattr(worker, "user_idle_seconds", lambda: 5.0)
    assert T._demo_front("ad") is False and not fronted                # someone is using this PC
    monkeypatch.setattr(worker, "user_idle_seconds", lambda: T.DEMO_FRONT_IDLE_S + 1)
    assert T._demo_front("ad") is True and fronted == ["ad"]
