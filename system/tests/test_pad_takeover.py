"""Pick up the controller, take over from the bot for a moment, put it down: the bot resumes (gbox/pad_takeover.py).

Operator 2026-10-26: "pick up the controller and basically overwrite the gameplay by the bot for a brief moment ... then
just put down a controller and give the gameplay back to the bot ... on any system that's remoted in through G Box".
"""
import json
import threading
import time
from types import SimpleNamespace

import pytest

from gbox import operator_guard, pad_takeover, padstate
from gbox import screensaver as S
from gbox import tools
from gbox.mercs.round_map import RoundTrace

SID = "w1-s1"


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(pad_takeover, "LEASES", {})
    monkeypatch.setattr(pad_takeover, "SEGMENTS", {})
    monkeypatch.setattr(pad_takeover, "spawn", lambda fn, name: None)     # no watcher thread: the tests drive the clock
    operator_guard._VIEWING.clear()
    yield
    operator_guard._VIEWING.clear()


def press(key, **kw):
    return {"key": key, "down": True, "player": 1, "src": "player", "lease": True, "by": "operator", **kw}


def release(key, **kw):
    return {"key": key, "down": False, "player": 1, "src": "player", "lease": True, "by": "operator", **kw}


def rig(sid=SID, idle=3.0, applies=None, clock=None, data_dir=None):
    """A playing bot on `sid`: a live thread, its run bound to the session's lease, its send() behind a Gate."""
    done = threading.Event()
    th = threading.Thread(target=done.wait, daemon=True)
    th.start()
    run = {"sid": sid, "driver": SimpleNamespace(stopped=False, trace=[]), "thread": th, "live": {},
           "mission": "playbook: test_bot", "mode": "playbook"}
    lz = pad_takeover.bind(sid, run, idle_s=idle, applies=applies, data_dir=data_dir)
    lz.clock = clock or Clock()
    sent = []
    gate = pad_takeover.Gate(sid, lambda rows, **kw: sent.append(list(rows)))
    return SimpleNamespace(run=run, lease=lz, gate=gate, sent=sent, done=done, clock=lz.clock)


# --- the rule ---------------------------------------------------------------------------------------------------------

def test_the_bot_lets_go_at_the_first_press_before_the_operators_input_and_drops_its_own_meanwhile():
    r = rig()
    r.gate([{"key": "lup", "down": True}, {"key": "r", "down": True}])        # the bot runs forward, aiming
    batch = [press("b")]
    out = pad_takeover.inputs(SID, batch)
    # within the same call, before the pump applies the operator's press: every key the bot held goes up
    assert r.sent[-1] == [{"key": "lup", "down": False}, {"key": "r", "down": False}]
    assert out == batch and pad_takeover.active(SID)
    assert r.run["live"]["operator_control"] is True and r.run["live"]["operator_control_since"] == 1000.0
    assert r.run["live"]["operator_segment"] == f"{SID}:1" and r.run["live"]["operator_takeovers"] == 1
    n = len(r.sent)
    r.gate([{"key": "lleft", "down": True}])                                # its decisions go on: nothing reaches the game
    r.gate([{"key": "lleft", "down": False}])
    assert len(r.sent) == n and r.gate.dropped == 2 and r.gate.generation == 1


def test_every_input_renews_and_the_bot_takes_back_over_after_the_idle_time_from_a_clean_held_set():
    r = rig(idle=3.0)
    r.gate([{"key": "lup", "down": True}])
    pad_takeover.inputs(SID, [press("b")])
    r.clock.t += 2.0
    pad_takeover.inputs(SID, [release("b")])                                # a release renews (the operator plays)
    r.clock.t += 2.9
    assert pad_takeover.active(SID)                                         # 2.9 s after their last input
    r.gate([{"key": "lup", "down": True}])
    r.clock.t += 0.2
    assert not pad_takeover.active(SID)                                     # 3.1 s idle: the bot has the pad again
    live = r.run["live"]
    assert live["operator_control"] is False and "operator_control_since" not in live and "operator_segment" not in live
    assert live["operator_control_s"] == pytest.approx(5.1, abs=0.05)
    n = len(r.sent)
    r.gate([{"key": "x", "down": True}])
    assert r.sent[n:] == [[{"key": "x", "down": True}]]                     # nothing it held before is pressed again
    pad_takeover.inputs(SID, [release("b")])
    assert not pad_takeover.active(SID)                                     # a release never takes the pad


def test_a_key_still_held_keeps_the_pad_and_a_lost_release_gives_it_back_after_hold_max():
    r = rig()
    pad_takeover.inputs(SID, [press("lup")])
    r.clock.t += 20                                                         # holding the stick forward, no new event
    assert pad_takeover.active(SID)
    r.clock.t += pad_takeover.HOLD_MAX_S
    assert not pad_takeover.active(SID)                                     # the release must have been lost


def test_this_pcs_controller_takes_over_renews_while_held_and_gives_back_once_put_down():
    r = rig()
    r.gate([{"key": "a", "down": True}])
    assert pad_takeover.local(SID, {"b"})                                   # padstate.watch_xinput: a press
    assert r.sent[-1] == [{"key": "a", "down": False}]
    r.clock.t += 10
    assert not pad_takeover.local(SID, {"b"})                               # held steady: renewed, not a new takeover
    assert pad_takeover.active(SID)
    pad_takeover.local(SID, set())                                          # put down
    r.clock.t += 2.9
    assert pad_takeover.active(SID)
    r.clock.t += 0.2
    assert not pad_takeover.active(SID)
    assert not pad_takeover.local(SID, set())
    assert padstate.stick_keys((0.0, -0.9, 0.8, 0.0)) == {"lup", "rright"}  # watch_xinput reads y down
    assert pad_takeover.local(SID, padstate.stick_keys((0.0, -0.9, 0.0, 0.0)))   # a pushed stick is a press too


def test_the_worker_pcs_xinput_watch_claims_renews_while_held_and_never_on_the_autoplay_chord(monkeypatch):
    from gbox import xinput
    import httpx
    r = rig()
    # (packet, buttons) per poll, 2 s apart: Xbox A (RetroPad b) pressed and held over two unchanged polls, released,
    # two quiet polls, then View + A together (the autoplay chord) and let go
    script = iter([(1, 0x1000), (1, 0x1000), (1, 0x1000), (2, 0), (2, 0), (2, 0), (3, 0x0020 | 0x1000), (4, 0)])
    seen = []

    def read(fn, slot, st):
        st.packet, st.gamepad.buttons = next(script)
        return st
    monkeypatch.setattr(xinput, "load", lambda: object())
    monkeypatch.setattr(xinput, "read", read)
    monkeypatch.setattr(padstate, "PLAYER_TOUCH", {})

    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *exc): return False
        def post(self, url, json): pass
    monkeypatch.setattr(httpx, "Client", Client)
    ticks = iter(range(8))

    def alive():                                       # record the lease after each poll, then the next poll 2 s later
        if r.clock.t > 1000.0:
            seen.append(pad_takeover.active(SID))
        r.clock.t += 2.0
        return next(ticks, None) is not None
    padstate.watch_xinput("http://spark", {}, SID, alive)
    # pressed: theirs; held 4 s with no new packet: still theirs (renewed); released: theirs for the idle time, then the
    # bot's again; the chord itself never takes the pad
    assert seen == [True, True, True, True, True, False, False, False]
    assert r.lease.takeovers == 1 and padstate.PLAYER_TOUCH.get(SID)


def test_stop_still_stops_and_the_bots_input_path_lets_go_of_nothing_the_operator_holds(monkeypatch):
    r = rig()
    tools.AUTOPLAY[SID] = r.run
    released = []
    monkeypatch.setitem(tools.SESSIONS, SID, (SimpleNamespace(supported={"send_input"},
                                                              send_input=lambda rows: released.append(rows)), {}))
    try:
        pad_takeover.inputs(SID, [press("lup")])                            # the operator holds up
        tools._release_all(SID)                                             # the bot's cleanup: their key stays theirs
        assert released == []
        out = tools.autoplay(tools.AutoplayIn(session_id=SID, op="stop"), SimpleNamespace())
        assert out["result"]["stopped"] and r.run["driver"].stopped        # Stop still stops the bot
        r.done.set()
        r.run["thread"].join(2)
        assert not pad_takeover.active(SID)                                 # no bot: nothing to give the pad back to
        pad_takeover.inputs(SID, [press("b")])
        assert not pad_takeover.active(SID)
        status = tools.autoplay(tools.AutoplayIn(session_id=SID, op="status"), SimpleNamespace())["result"]
        assert status["operator_control"] is False and status["operator_takeovers"] == 1
    finally:
        tools.AUTOPLAY.pop(SID, None)


def test_a_human_coop_session_or_a_stopped_bot_never_hands_p1_over():
    r = rig(applies=lambda: False)                                          # tools: _mercs_human_controls
    r.gate([{"key": "a", "down": True}])
    pad_takeover.inputs(SID, [press("b")])
    assert not pad_takeover.active(SID) and r.sent == [[{"key": "a", "down": True}]]
    r2 = rig(sid="w1-s2")
    r2.run["driver"].stopped = True
    pad_takeover.inputs("w1-s2", [press("b")])
    assert not pad_takeover.active("w1-s2")


def test_a_refused_or_agent_event_never_takes_the_pad_and_relayed_bot_presses_wait_meanwhile():
    r = rig()
    applied = []
    r.gate([{"key": "a", "down": True}])
    for e in ({"key": "b", "down": True, "src": "agent"}, press("b", lease=False), {"key": "b", "rpc": 1, "src": "player"},
              {"key": "b", "down": True, "src": "autoplay"}):
        assert pad_takeover.inputs(SID, [e], send=applied.append) == [e]
        assert not pad_takeover.active(SID)
    # the mission / vision driver's presses come back through the pump (src autoplay): tracked, then released at the
    # takeover and dropped while the operator has the pad
    pad_takeover.inputs(SID, [{"key": "lup", "down": True, "src": "autoplay"}], send=applied.append)
    out = pad_takeover.inputs(SID, [press("x"), {"key": "lright", "down": True, "src": "autoplay"}], send=applied.append)
    assert out == [press("x")]
    assert {"key": "lup", "down": False} in applied[-1] and {"key": "b", "down": False} in applied[-1]


def test_a_second_takeover_lets_go_again_of_what_each_input_path_pressed_since():
    r = rig()
    applied = []
    pad_takeover.inputs(SID, [{"key": "lup", "down": True, "src": "autoplay"}], send=applied.append)   # relayed
    r.gate([{"key": "a", "down": True}])                                                                # direct
    pad_takeover.inputs(SID, [press("b"), release("b")], send=applied.append)                           # takeover 1
    assert applied[-1] == [{"key": "lup", "down": False}] and r.sent[-1] == [{"key": "a", "down": False}]
    r.clock.t += 3.5
    assert not pad_takeover.active(SID)
    pad_takeover.inputs(SID, [{"key": "ldown", "down": True, "src": "autoplay"}], send=applied.append)
    r.gate([{"key": "x", "down": True}])
    pad_takeover.inputs(SID, [press("b")], send=applied.append)                                         # takeover 2
    assert applied[-1] == [{"key": "ldown", "down": False}] and r.sent[-1] == [{"key": "x", "down": False}]
    assert r.lease.takeovers == 2 and r.gate.generation == 2


def test_a_restarted_bot_yields_to_a_takeover_already_running():
    r = rig()
    pad_takeover.inputs(SID, [press("b")])
    run2 = dict(r.run, live={})
    pad_takeover.bind(SID, run2, idle_s=3.0)                                # F5 / a hot reload restarted the bot
    assert run2["live"]["operator_control"] is True
    sent2 = []
    g2 = pad_takeover.Gate(SID, lambda rows: sent2.append(rows))
    g2([{"key": "lup", "down": True}])
    assert sent2 == [] and g2.dropped == 1


# --- the control plane --------------------------------------------------------------------------------------------------

def test_the_input_route_stamps_who_sent_it_and_never_trusts_a_clients_own_source():
    src = lambda actor: (lambda e: padstate._source(actor, e))
    forged = [{"key": "b", "down": True, "src": "player", "lease": True}, {"rpc": 7, "op": "state"}]
    agent = pad_takeover.stamp(forged, src("agent"), lease=True, actor="agent")
    assert agent[0] == {"key": "b", "down": True, "src": "agent"} and agent[1] == {"rpc": 7, "op": "state"}
    op = pad_takeover.stamp([{"key": "b", "down": True, "player": 1}, {"key": "start"}], src("operator"), lease=True,
                            actor="operator", via="desktop-webview@10.0.0.7")
    assert op[0] == {"key": "b", "down": True, "player": 1, "src": "player", "lease": True, "by": "operator",
                     "via": "desktop-webview@10.0.0.7"}
    assert op[1]["src"] == "ui" and op[1]["lease"] is True
    assert pad_takeover.stamp([{"key": "b"}], src("operator"), lease=False, actor="operator")[0]["lease"] is False
    assert pad_takeover.stamp([{"key": "b"}], src("autoplay"), lease=True, actor="autoplay")[0] == {"key": "b", "src": "autoplay"}


def test_viewing_is_per_machine_and_expires(tmp_path):
    from gbox.store import Store
    store = Store(tmp_path / "store")
    try:
        assert not operator_guard.viewing(store, SID, "10.0.0.7", now=100.0)
        operator_guard.report_watch(store, "mjpeg:x", SID, now=100.0, host="10.0.0.7")
        operator_guard._VIEWING.clear()
        assert operator_guard.viewing(store, SID, "10.0.0.7", now=101.0)
        assert not operator_guard.viewing(store, SID, "10.0.0.9", now=101.0)    # another machine is not viewing it
        operator_guard._VIEWING.clear()
        assert not operator_guard.viewing(store, SID, "10.0.0.7", now=100.0 + operator_guard.WATCH_TTL_S + 1)
    finally:
        store.db.close()


def _wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_input_forwarded_from_the_operators_app_takes_the_pad_end_to_end(plane, monkeypatch):
    """Control plane + worker pump over HTTP: the app's pad press for a session it views makes the session's bot let go
    before the press reaches the emulator; agents, automation and a machine not viewing it never take the pad."""
    monkeypatch.setattr(padstate, "watch_xinput", lambda *a, **kw: None)
    monkeypatch.setattr(pad_takeover, "spawn", lambda fn, name: threading.Thread(target=fn, daemon=True).start())
    sid = "w9-e2e"
    applied = []
    ad = SimpleNamespace(supported={"send_input"}, send_input=lambda rows, **kw: applied.append([dict(e) for e in rows]),
                         proc=SimpleNamespace(pid=None, poll=lambda: None))
    store = plane.app.state.store
    done = threading.Event()
    th = threading.Thread(target=done.wait, daemon=True)
    th.start()
    run = {"sid": sid, "driver": SimpleNamespace(stopped=False), "thread": th, "live": {}}
    tools.SESSIONS[sid] = (ad, {})
    tools.AUTOPLAY[sid] = run
    try:
        pad_takeover.bind(sid, run, idle_s=0.6)
        gate = pad_takeover.Gate(sid, ad.send_input)
        gate([{"key": "lup", "down": True}])                                # the bot holds up
        threading.Thread(target=tools._pump, args=(sid, ad, str(plane.base_url), dict(plane.headers)), daemon=True).start()
        keys = lambda: [(e["key"], e["down"]) for rows in applied for e in rows]

        # an agent's press and a machine that is not viewing the session: delivered, never a takeover
        plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "a", "down": True}]},
                   headers={"x-gbox-actor": "agent"}).raise_for_status()
        plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "y", "down": True, "player": 1}]}).raise_for_status()
        assert _wait(lambda: ("y", True) in keys())
        assert not pad_takeover.active(sid) and ("lup", False) not in keys()
        agent_row = next(e for rows in applied for e in rows if e["key"] == "a")
        assert agent_row["src"] == "agent" and "lease" not in agent_row
        unviewed = next(e for rows in applied for e in rows if e["key"] == "y")
        assert unviewed["src"] == "player" and unviewed["lease"] is False

        # automation acting as the operator (a worker tool inside an agent's job) is refused too
        store.put("session_watch", "app:127.0.0.1:test", {"session_id": sid, "until": time.time() + 60, "host": "127.0.0.1"})
        operator_guard._VIEWING.clear()
        store.put("job", "agentjob", {"id": "agentjob", "agent_use": True, "actor": "hermes", "state": "running"})
        plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "x", "down": True, "player": 1}]},
                   headers={"x-gbox-parent-job": "agentjob"}).raise_for_status()
        assert _wait(lambda: ("x", True) in keys()) and not pad_takeover.active(sid)

        # the operator's app viewing it: the bot lets go first, then the press lands
        plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "b", "down": True, "player": 1}]}).raise_for_status()
        assert _wait(lambda: ("b", True) in keys())
        k = keys()
        assert ("lup", False) in k and k.index(("lup", False)) < k.index(("b", True))
        assert pad_takeover.active(sid) and run["live"]["operator_control"] is True
        row = next(e for rows in applied for e in rows if e["key"] == "b")
        assert row["lease"] is True and row["by"] == "operator" and row["via"].endswith("@127.0.0.1")
        n = len(applied)
        gate([{"key": "lright", "down": True}])                             # dropped while the operator has the pad
        plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "l", "down": True}]},
                   headers={"x-gbox-actor": "autoplay"}).raise_for_status()   # a relayed bot press waits too
        time.sleep(0.3)
        assert not any(e["key"] in ("lright", "l") for rows in applied[n:] for e in rows)
        plane.post(f"/api/sessions/{sid}/input", json={"events": [{"key": "b", "down": False, "player": 1}]}).raise_for_status()
        assert _wait(lambda: not pad_takeover.active(sid), 5)               # put down: 0.6 s later the bot is back
        assert _wait(lambda: run["live"].get("operator_control") is False, 5)
        gate([{"key": "lright", "down": True}])
        assert applied[-1] == [{"key": "lright", "down": True}]
        seg = pad_takeover.segment(f"{sid}:1")
        assert seg["source"] == "remote" and seg["actor"] == "operator" and seg["keys"][0][1] == ["b"]
    finally:
        done.set()
        tools.SESSIONS.pop(sid, None)
        tools.AUTOPLAY.pop(sid, None)
        pad_takeover.forget(sid)


# --- training data ------------------------------------------------------------------------------------------------------

def test_segment_keys_are_held_or_pressed_per_quarter_second():
    events = [(10.0, "lup", True), (10.6, "b", True), (10.65, "b", False), (11.1, "lup", False)]
    assert pad_takeover.buckets(events, 10.0, 11.1) == [
        [10.0, ["lup"]], [10.25, ["lup"]], [10.5, ["b", "lup"]], [10.75, ["lup"]], [11.0, ["lup"]]]


def test_the_round_map_keeps_each_takeover_with_its_keys_and_route_and_its_time_is_the_operators(tmp_path, monkeypatch):
    r = rig(idle=3.0, data_dir=tmp_path)
    monkeypatch.setattr(pad_takeover, "spawn", lambda fn, name: fn() if name == "pad-takeover-log" else None)
    trace = RoundTrace(tmp_path / "maps", "G4BE08", "r100", "round0001", 100.0)
    stats = r.run["live"]
    for i in range(4):                                                      # the bot drives for a second
        trace.add(1000.0 + i * 0.25, i * 10.0, 0.0, 0.0, stats)
    r.clock.t = 1001.0
    pad_takeover.inputs(SID, [press("lup")])                                # the operator takes over and walks up
    for i in range(8):
        r.clock.t = 1001.0 + i * 0.25
        if i == 4:
            pad_takeover.inputs(SID, [press("b")])
        if i == 5:
            pad_takeover.inputs(SID, [release("b")])
        trace.add(r.clock.t, 40.0, i * 10.0, 0.0, stats)
    r.clock.t = 1003.0
    pad_takeover.inputs(SID, [release("lup")])
    r.clock.t = 1006.1
    assert not pad_takeover.active(SID)                                     # the bot has it back
    for i in range(4):
        trace.add(1006.25 + i * 0.25, 40.0 + i * 10, 70.0, 0.0, stats)
    s = trace.finish()
    seg = s["operator_segments"][0]
    assert seg["id"] == f"{SID}:1" and seg["t_from"] == 1001.0 and seg["source"] == "remote"
    assert seg["t_to"] == pytest.approx(1006.1, abs=0.01)                   # when the bot took the pad back
    assert seg["keys"][0] == [1001.0, ["lup"]] and [1002.0, ["b", "lup"]] in seg["keys"] and seg["keys"][-1][0] == 1003.0
    assert seg["route"][0] == [1001.0, 40.0, 0.0] and len(seg["route"]) == 8 and seg["to"] == [40.0, 70.0]
    # 7 quarter seconds of operator samples, then their last sample holds until the bot's next one (2 s cap); the
    # phase table rounds each step to 0.1 s
    assert s["time_by_phase"]["operator"] == pytest.approx(3.75, abs=0.2)
    assert s["operator_s"] == pytest.approx(5.1, abs=0.01)
    data = json.loads((tmp_path / "maps").glob("*.json").__next__().read_text())
    assert data["operator_segments"][0]["keys"] == seg["keys"]
    assert "#ff4fd8" in next((tmp_path / "maps").glob("*.svg")).read_text()   # drawn magenta on the map
    line = json.loads(next((tmp_path / "autoplay" / "operator_segments").glob("*.jsonl")).read_text().splitlines()[0])
    assert line["id"] == f"{SID}:1" and line["keys"][0] == [1001.0, ["lup"]]  # and logged for any bot


def test_a_bot_that_gives_up_while_the_operator_drove_never_gets_its_game_relaunched():
    r = rig()
    pad_takeover.inputs(SID, [press("start")])                              # they opened a menu the bot can't name
    pad_takeover.inputs(SID, [release("start")])
    assert pad_takeover.recent(SID)
    r.clock.t += 3.5
    assert not pad_takeover.active(SID) and pad_takeover.recent(SID)        # just after: still theirs to judge
    r.clock.t += pad_takeover.RECENT_S
    assert not pad_takeover.recent(SID)


def test_the_engines_bot_holds_nothing_while_the_operator_drives_and_presses_what_it_wants_after(tmp_path):
    from gbox.mercs import engine
    from tests.test_mercs_engine import Clock as EngineClock, re4
    m, clk, sent, stats, n = re4([]), EngineClock(), [], {}, [0]

    class Brain:
        def tick(self, snap):
            return {"hold": {"r"} if n[0] < 10 else {"lup"}}

        def prompt_ok(self, button, snap, now):
            return True

        def save(self):
            pass

    def stopped():
        n[0] += 1
        stats["operator_control"] = 5 <= n[0] < 15                           # the operator has the pad for a while
        return n[0] > 25
    engine.play_round({"driver": "gbox.mercs.titles.re4_gc"}, m, sent.append, stopped, stats, brain=Brain(),
                      sleep=clk.sleep, clock=clk, learn_dir=tmp_path)
    downs = [(e["key"], e["down"]) for rows in sent for e in rows]
    assert downs[0] == ("r", True) and ("r", False) not in downs             # the gate let go of r, not the engine
    assert downs[1] == ("lup", True) and downs.count(("r", True)) == 1       # its choice then, nothing from before


# --- the schedule -------------------------------------------------------------------------------------------------------

def test_a_screensaver_game_is_never_rotated_away_under_the_operators_pad():
    from tests.test_screensaver import rig as saver_rig
    S.TELEMETRY.clear()
    s, w, saver, calls, tick = saver_rig()
    t = 10_000.0
    tick()
    gid = calls[0]["input"]["game"]["game_id"]
    s.put("session", "w1-job0", {"session_id": "w1-job0", "game_id": gid, "state": "running"})
    tick(5)
    tick(S.START_GRACE)
    t += 5 + S.START_GRACE + 21 * 60
    S.telemetry_put("w1-job0", {"running": True, "stats": {"operator_control": True}}, now=t)
    assert S.operator_has_pad("w1-job0", now=t)
    tick(21 * 60)
    assert all(c["input"].get("op") != "stop_game" for c in calls)          # 21 minutes, but the operator plays it
    t += 60
    S.telemetry_put("w1-job0", {"running": True, "stats": {"operator_control": False}}, now=t)
    tick(60)
    assert calls[-1]["input"]["op"] == "stop_game"                          # pad down: the schedule goes on
    S.telemetry_put("w1-job0", {"running": True, "stats": {"operator_control": True}}, now=t - 60)
    assert not S.operator_has_pad("w1-job0", now=t)                         # a stale report never holds it
    S.TELEMETRY.clear()
