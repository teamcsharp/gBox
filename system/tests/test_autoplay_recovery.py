"""Autoplay never leaves a frozen or black game on screen (gbox.tools _black / _black_watch / _bad_end, screensaver
report): a screensaver demo moves on to its next game, any other autoplay game is relaunched and played again."""
import io
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from gbox import screensaver as S
from gbox import tools as T
from tests.test_screensaver import Archive, Store, worker


def png(grey: int) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (64, 48), (grey, grey, grey)).save(b, "PNG")
    return b.getvalue()


def test_black_tells_black_from_a_picture():
    assert T._black(SimpleNamespace(get_frame=lambda: png(2))) is True
    assert T._black(SimpleNamespace(get_frame=lambda: png(90))) is False

    def broken():
        raise RuntimeError("no frame")
    assert T._black(SimpleNamespace(get_frame=broken)) is None


def test_black_watch_ends_the_run_after_black_for_long_enough():
    now = [0.0]
    d, run = SimpleNamespace(stopped=False), {"sid": "w-1", "thread": None}
    T._black_watch(run, d, SimpleNamespace(get_frame=lambda: png(1)), clock=lambda: now[0],
                   sleep=lambda s: now.__setitem__(0, now[0] + s))
    for _ in range(200):
        if d.stopped:
            break
        time.sleep(0.01)
    assert d.stopped and run["bad_end"] == "black" and now[0] >= T.BLACK_FOR


def test_a_picture_resets_the_black_clock():
    now, frames = [0.0], iter([png(1)] * 6 + [png(80)] + [png(1)] * 4 + [png(80)] * 1000)
    d, run = SimpleNamespace(stopped=False), {"sid": "w-1", "thread": None}

    def sleep(s):
        now[0] += s
        if now[0] > 200:
            d.stopped = True                                     # end the test's watch
    T._black_watch(run, d, SimpleNamespace(get_frame=lambda: next(frames)), clock=lambda: now[0], sleep=sleep)
    for _ in range(300):
        if d.stopped:
            break
        time.sleep(0.01)
    assert "bad_end" not in run                                  # 30 s black, a picture, 20 s black: never 45 s


class Http:
    def __init__(self, saved=False, job_states=("running", "succeeded"), new="w-2"):
        self.calls, self.saved, self.states, self.new = [], saved, list(job_states), new

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json))
        if url.endswith("/autoplay-screensaver/result"):
            return SimpleNamespace(status_code=200, json=lambda: {"saved": self.saved}, text="")
        if url.endswith("/reset"):
            return SimpleNamespace(status_code=200, json=lambda: {"id": "rj"}, text="")
        return SimpleNamespace(status_code=200, json=lambda: {"id": "aj"}, text="")

    def get(self, url, headers=None, timeout=None):
        self.calls.append(("GET", url, None))
        st = self.states.pop(0) if self.states else "succeeded"
        return SimpleNamespace(json=lambda: {"state": st, "output": {"session_id": self.new} if st == "succeeded" else {}})


def run_for(monkeypatch, http, bad="black"):
    monkeypatch.setattr(T.httpx, "post", http.post)
    monkeypatch.setattr(T.httpx, "get", http.get)
    run = {"sid": "w-1", "bad_end": bad, "ctx": SimpleNamespace(server="http://cp", headers={}),
           "inp": SimpleNamespace(mode="auto", screensaver=True, style={"pace": 1.0})}
    T._bad_end(run, sleep=lambda s: None)
    return run


def test_a_screensaver_run_moves_on_without_a_relaunch(monkeypatch):
    http = Http(saved=True)
    run_for(monkeypatch, http)
    assert [c[1] for c in http.calls] == ["http://cp/api/autoplay-screensaver/result"]


def test_any_other_run_is_relaunched_and_played_again(monkeypatch):
    http = Http(saved=False)
    run = run_for(monkeypatch, http, bad="hung")
    posts = [c for c in http.calls if c[0] == "POST"]
    assert posts[1][1] == "http://cp/api/sessions/w-1/reset" and posts[1][2] == {"mode": "restart"}
    start = posts[2][2]
    assert start["tool"] == "autoplay" and start["require_worker"] == "w"
    assert start["input"] == {"session_id": "w-2", "op": "start", "mode": "auto", "screensaver": True, "style": {"pace": 1.0}}
    assert run["recovery"].startswith("relaunched as w-2")


def test_a_refused_relaunch_is_noted_not_retried(monkeypatch):
    http = Http(saved=False)

    def post(url, json=None, headers=None, timeout=None):
        if url.endswith("/reset"):
            return SimpleNamespace(status_code=409, json=lambda: {}, text="the operator's live session")
        return http.post(url, json, headers, timeout)
    monkeypatch.setattr(T.httpx, "post", post)
    monkeypatch.setattr(T.httpx, "get", http.get)
    run = {"sid": "w-1", "bad_end": "black", "ctx": SimpleNamespace(server="http://cp", headers={}), "inp": None}
    T._bad_end(run, sleep=lambda s: None)
    assert run["recovery"].startswith("relaunch refused")


@pytest.mark.parametrize('resumed', [False, True])
def test_replacement_resume_decision_never_falls_back_to_another_start(monkeypatch, resumed):
    http = Http(saved=False)
    http.get = lambda *a, **kw: SimpleNamespace(json=lambda: {
        'state': 'succeeded', 'output': {'session_id': 'w-2', 'autoplay_resumed': resumed}})
    run = run_for(monkeypatch, http, bad='hung')
    assert not any(url.endswith('/api/jobs') for _, url, _ in http.calls)
    assert ('autoplay resumed by replacement' if resumed else 'autoplay was not resumed') in run['recovery']


@pytest.mark.parametrize('status,body', [(409, {'detail': 'stopped'}), (200, {'id': 'aj', 'state': 'rejected'}),
                                         (200, {})])
def test_legacy_autoplay_restart_rejection_is_not_reported_as_started(monkeypatch, status, body):
    http = Http(saved=False)
    post = http.post
    def respond(url, **kw):
        if url.endswith('/api/jobs'):
            return SimpleNamespace(status_code=status, json=lambda: body, text='stopped')
        return post(url, **kw)
    http.post = respond
    run = run_for(monkeypatch, http, bad='hung')
    assert 'autoplay restart refused' in run['recovery'] or 'autoplay restart was not accepted' in run['recovery']


def test_the_screensaver_moves_on_from_a_black_game():
    s, now = Store(), 10_000.0
    w = worker(now)
    calls = []

    def submit(req, actor, origin):
        calls.append(req.tool)
        return SimpleNamespace(id=f"j{len(calls)}", state="queued")
    saver = S.Screensaver(s, Archive(), submit, lambda: [w])
    s.put(S.STATE, w["name"], {"worker": w["name"], "worker_id": w["id"], "phase": "playing", "job": "j0",
                               "game_id": "sc", "title": "SoulCalibur", "started": now, "session_id": "w1-j0"})
    s.put("session", "w1-j0", {"session_id": "w1-j0", "state": "running"})
    assert saver.report("w1-j0", {"bad_end": "black"}) is True
    out = saver.tick(now + 1)
    assert "only black" in out[w["name"]] and "session_op" in calls                  # stopped, next game later
