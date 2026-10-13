"""Pick whip backend glue (gbox/pickwhip.py): the pause hold + watchdog, and pick_name's local-LLM tool loop."""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import pickwhip as PW
from gbox.config import LLMEndpoint

SID = "w1-s1"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Store:
    def __init__(self, state="running"):
        self.sessions = {SID: {"session_id": SID, "state": state}}
        self.audits = []

    def get(self, kind, key):
        return self.sessions.get(key) if kind == "session" else None

    def audit(self, *a):
        self.audits.append(a)


def app_with(rpc_paused=False, live=True, state="running"):
    clock, store, calls = Clock(), Store(state), []

    def rpc(sid, op):
        calls.append(("rpc", op))
        if not live:
            raise TimeoutError("no live channel")
        return {"runtime": {"state": "PAUSED" if rpc_paused else "PLAYING"}} if op == "info" else {"ok": True}

    def submit_op(sid, op):
        calls.append(("job", op))

    app = FastAPI()
    H = PW.register(app, lambda: "operator", store, rpc=rpc, submit_op=submit_op, holds=PW.Holds(clock), watchdog=False)
    return TestClient(app), app, clock, calls, H


def test_hold_pauses_once_and_resumes_on_last_release():
    c, app, clock, calls, H = app_with()
    r = c.post(f"/api/pickwhip/{SID}/hold", json={"op": "pause", "holder": "desktop"}).json()
    assert r["paused"] and r["owned"] and r["via"] == "rpc"
    c.post(f"/api/pickwhip/{SID}/hold", json={"op": "pause", "holder": "web"})
    assert calls.count(("rpc", "pause")) == 1                 # the second holder doesn't pause again
    assert c.post(f"/api/pickwhip/{SID}/hold", json={"op": "release", "holder": "desktop"}).json()["resumed"] is False
    r = c.post(f"/api/pickwhip/{SID}/hold", json={"op": "release", "holder": "web"}).json()
    assert r["resumed"] is True and ("rpc", "resume") in calls


def test_operator_paused_game_stays_paused():
    c, app, clock, calls, H = app_with(rpc_paused=True)
    r = c.post(f"/api/pickwhip/{SID}/hold", json={"op": "pause", "holder": "desktop"}).json()
    assert r["owned"] is False and ("rpc", "pause") not in calls
    assert c.post(f"/api/pickwhip/{SID}/hold", json={"op": "release", "holder": "desktop"}).json()["resumed"] is False
    assert ("rpc", "resume") not in calls


def test_watchdog_resumes_when_the_client_goes_away():
    c, app, clock, calls, H = app_with()
    c.post(f"/api/pickwhip/{SID}/hold", json={"op": "pause", "holder": "desktop", "ttl_s": 10})
    clock.t += 5
    assert c.post(f"/api/pickwhip/{SID}/hold", json={"op": "renew", "holder": "desktop", "ttl_s": 10}).json()["ok"]
    clock.t += 9
    app.state.pickwhip_tick()
    assert ("rpc", "resume") not in calls                    # renewed: still held
    clock.t += 2
    app.state.pickwhip_tick()
    assert ("rpc", "resume") in calls
    assert c.get("/api/pickwhip/holds").json() == {}


def test_no_live_channel_uses_the_job_queue_and_ended_session_refuses():
    c, app, clock, calls, H = app_with(live=False)
    r = c.post(f"/api/pickwhip/{SID}/hold", json={"op": "pause", "holder": "desktop"}).json()
    assert r["via"] == "job" and ("job", "pause") in calls and ("rpc", "pause") not in calls
    c2 = app_with(state="ended")[0]
    assert c2.post(f"/api/pickwhip/{SID}/hold", json={"op": "pause"}).status_code == 409


def test_runtime_paused_reads_like_the_web_control():
    assert PW.runtime_paused({"runtime": {"paused": True}}) is True
    assert PW.runtime_paused({"state": "RUNNING"}) is False
    assert PW.runtime_paused({"runtime": {}}) is None


# ---------------------------------------------------------------------------------------------------------- pick_name

def cfg(cloud_key=None):
    eps = [LLMEndpoint(name="spark-ollama", url="http://spark:11434/v1", model="gemma-e2b")]
    if cloud_key:
        eps.append(LLMEndpoint(name="cloud", url="https://cloud/v1", model="big", api_key_env=cloud_key))
    return SimpleNamespace(agent={"llm_url": "http://127.0.0.1:11434/v1", "model": "qwen3.6:35b", "vision_model": "qwen2.5vl:7b"},
                           llm_endpoints=eps)


def test_routes_are_local_first_and_cloud_only_when_allowed(monkeypatch):
    monkeypatch.setenv("PW_KEY", "x")
    r = PW.llm_routes(cfg("PW_KEY"), "gemma4:e4b")
    assert [x.model for x in r][:2] == ["gemma4:e4b", "gemma4:e4b"] and all(x.local for x in r)
    assert not any(x.name == "cloud" for x in r)
    r = PW.llm_routes(cfg("PW_KEY"), "auto", allow_cloud=True)
    assert r[0].model == "gemma-e2b" and r[-1].name == "cloud" and r[-1].local is False
    monkeypatch.delenv("PW_KEY")
    assert not any(x.name == "cloud" for x in PW.llm_routes(cfg("PW_KEY"), "", allow_cloud=True))


def call(fn, **args):
    return {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "function": {"name": fn, "arguments": json.dumps(args)}}]}}]}


def test_tool_loop_calls_pick_identify_then_reports():
    replies = [call("pick_identify", x=0.4, y=0.6), call("report_pick", name="Leon", kind="player", slot="player", confidence=0.9)]
    sent, ran, lines = [], [], []

    def post(route, body):
        sent.append((route.model, body))
        return replies.pop(0)

    def run_tool(name, args):
        ran.append((name, args))
        return {"entity": {"name": "pl0000", "kind": "player"}, "model": "pl00.mdl"}

    inp = PW.PickNameIn(target_session=SID, x=0.4, y=0.6, evidence={"picked": {"class": "pl0000", "kind": "player"}}, model="gemma4:e4b")
    out = PW.name_pick(inp, PW.llm_routes(cfg(), inp.model), post, run_tool, lambda p, m: lines.append(m))
    assert out["name"] == "Leon" and out["route"] == "local" and out["llm_model"] == "gemma4:e4b"
    assert out["model"] == "pl00.mdl"                          # filled from the tool's evidence when the model omits it
    assert ran == [("pick_identify", {"x": 0.4, "y": 0.6})]
    assert sent[0][1]["tools"][0]["function"]["name"] == "pick_preview"
    assert any(m["role"] == "tool" and m["name"] == "pick_identify" for m in sent[1][1]["messages"])
    assert any("calls pick_identify" in m for m in lines)


def test_unavailable_models_fall_back_to_evidence():
    def post(route, body):
        raise ConnectionError("refused")
    inp = PW.PickNameIn(evidence={"picked": {"class": "TObjEneBeast", "kind": "enemy"}, "model": ["enemy", "beast.nj"]})
    out = PW.name_pick(inp, PW.llm_routes(cfg(), ""), post, lambda n, a: {})
    assert out["route"] == "evidence" and out["name"] == "TObjEneBeast" and out["kind"] == "enemy"
    assert out["model"] == "enemy / beast.nj" and len(out["tried"]) == 2


def test_json_content_answer_is_accepted():
    post = lambda r, b: {"choices": [{"message": {"content": 'Sure: {"name": "yellow taxi", "kind": "vehicle"}'}}]}
    out = PW.name_pick(PW.PickNameIn(), PW.llm_routes(cfg(), ""), post, lambda n, a: {})
    assert out["name"] == "yellow taxi" and out["kind"] == "vehicle" and out["route"] == "local"
