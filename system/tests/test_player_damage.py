import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import player_damage as P
from gbox.mercs import damage as D, engine
from gbox.store import Store

SID, RUN, ROUND = "worker-session", "run_12345678", "round_12345678"


def snap(hp=1000, maximum=1000, ptr=0x30400000):
    return {"player": {"ptr": ptr, "hp": hp, "hp_max": maximum, "pos": [0, 0, 0], "rot": 0},
            "enemies": [{"ptr": 0x30800000, "slot": 0, "hp": 800, "hp_max": 800, "pos": [0, 0, 100]}],
            "timer": 100, "score": 0}


def observer(events, stats=None):
    return D.Observer(events.append, RUN, "fixture", stats if stats is not None else {},
                      raw=lambda m, title, s: {"hp": s["player"]["hp"]})


def tick(obs, s, when, screen="playing", maintain=None):
    event = obs.before(s, screen, None, now=when)
    if maintain:
        maintain(s)
    obs.after(s, screen, now=when)
    return event


def event(eid="event_12345678", **kw):
    return {"schema": "gbox.player_damage/1", "session_id": SID, "event_id": eid, "run_id": RUN,
            "round_id": ROUND, "title": "BLUS30491", "observed_at": 100.0, "hp_before": 1000,
            "hp_after": 900, "hp_max": 1000, "loss": 100, "snapshot": snap(900), "logic": {"combat": "tracking"},
            "tactical": {"v": 1, "title": "BLUS30491", "stage": "stage1", "units": "cm", "screen": "playing",
                         "player": {"pos": [0, 0, 0], "hp": 900}}, "raw": {"fields": [{"hex": "0384"}]}, **kw}


def test_observer_records_before_maintenance_and_rebases_after_injected_max_change():
    events, stats = [], {"damage_events": 17}
    obs = observer(events, stats)
    refill = lambda s: s["player"].update(hp=30000, hp_max=30000)
    tick(obs, snap(), 1.0, maintain=refill)
    tick(obs, snap(29900, 30000), 1.1, maintain=refill)
    tick(obs, snap(29800, 30000), 1.2, maintain=refill)
    assert [e["loss"] for e in events] == [100, 200]
    assert events[0]["snapshot"]["player"]["hp"] == events[0]["raw"]["hp"] == 29900
    assert events[0]["tactical"]["player"]["hp"] == 29900
    assert events[0]["event_id"] != events[1]["event_id"]
    assert events[0]["cause"] == events[0]["self_damage"] == "unknown"
    assert stats["damage_events"] == 17 and stats["player_damage_events"] == 2


@pytest.mark.parametrize("changed", [snap(900, 2000), snap(900, ptr=0x30400010), {}, snap(-1), snap(float("nan"))])
def test_invalid_player_max_transition_or_unknown_sample_cannot_be_damage(changed):
    events, obs = [], None
    obs = observer(events)
    tick(obs, snap(), 1)
    tick(obs, changed, 1.1)
    assert not events


def test_stale_loading_dead_and_new_round_baselines_do_not_manufacture_hits():
    events = []
    obs = observer(events)
    tick(obs, snap(), 1)
    tick(obs, snap(900), 10)                # unknown stale interval
    tick(obs, {}, 10.1, screen="loading")
    tick(obs, snap(500), 10.2)
    tick(obs, snap(0), 10.3, screen="dead")
    tick(obs, snap(0), 10.4, screen="dead")
    tick(obs, snap(1000), 10.5)
    tick(observer(events), snap(400), 10.6)
    assert len(events) == 1 and events[0]["loss"] == 500


def test_reused_mutable_snapshot_detects_each_loss_but_repeated_same_hp_does_not_duplicate():
    events, s = [], snap()
    obs = observer(events)
    tick(obs, s, 1)
    for hp, now in [(900, 1.1), (900, 1.2), (800, 1.3)]:
        s["player"]["hp"] = hp
        tick(obs, s, now)
    assert [e["hp_after"] for e in events] == [900, 800]
    assert events[0]["snapshot"]["player"]["hp"] == 900


def test_enemy_damage_or_zero_damage_contact_is_not_a_player_loss():
    events, s = [], snap()
    obs = observer(events)
    tick(obs, s, 1)
    s["enemies"][0]["hp"] = 0
    s["player"]["action"] = 5
    tick(obs, s, 1.1)
    assert not events


def test_confirmed_internal_restart_gets_new_round_id_without_hp_reset_damage():
    events, stats = [], {"rounds": 1}
    obs = observer(events, stats)
    tick(obs, snap(), 1)
    tick(obs, snap(900), 1.1)
    tick(obs, snap(0), 1.2, screen="dead")
    tick(obs, snap(), 1.3, maintain=lambda s: stats.update(rounds=2))
    tick(obs, snap(800), 1.4)
    assert [e["loss"] for e in events] == [100, 900, 200]
    assert events[0]["round_id"] == events[1]["round_id"] != events[2]["round_id"]


def test_re5_raw_capture_is_bounded_addressed_hex_and_checks_current_player():
    from test_re5_combat import world, PL
    m = world()
    m.put(PL + 0x14A4, ">hh", 900, 1000)
    s = snap(900)
    writes = len(m.writes)
    raw = D.hook_bytes(m, "BLUS30491", s)
    assert raw["state"] == "done" and raw["matches_snapshot_hp"]
    hp = next(r for r in raw["fields"] if r["name"] == "hp_max")
    assert hp == {"name": "hp_max", "address": hex(PL + 0x14A4), "size": 4, "hex": "038403e8"}
    assert sum(r["size"] for r in raw["fields"]) < 2048 and len(m.writes) == writes
    s["player"]["ptr"] += 16
    assert D.hook_bytes(m, "BLUS30491", s)["state"] == "failed"


def test_action_header_short_read_is_explicit_failed_capture():
    from test_re5_combat import world, PL, ACT
    m = world()
    m.put(PL + 0x14A4, ">hh", 900, 1000)
    original = m.rd
    m.rd = lambda address, n: b"\0" * 3 if address == ACT and n == 0x24 else original(address, n)
    result = D.hook_bytes(m, "BLUS30491", snap(900))
    assert result["state"] == "failed" and "short read of current_action" in result["detail"]


def test_bound_provenance_hashes_actual_decoder_raw_helper_and_effective_profile():
    from gbox.mercs.titles.re5_ps3 import RE5PS3
    obs = observer([])
    profile = {"map_id": "BLUS30491", "build": "fixture-build", "package": [["unlimited_health", {}]]}
    obs.bind(RE5PS3(), profile)
    p = obs.provenance
    assert p["effective_profile"] == profile and p["game_build"] == "fixture-build"
    assert all(len(p[k]) == 64 for k in ("loaded_snapshot_code_sha256", "loaded_decoder_code_sha256",
                                        "loaded_raw_capture_code_sha256", "effective_profile_sha256"))
    assert p["loaded_snapshot_code_sha256"] != p["loaded_decoder_code_sha256"]


def test_outbox_retries_same_durable_id_after_restart_and_requires_exact_ack(tmp_path):
    calls = []
    def fail(e):
        calls.append(e["event_id"])
        raise TimeoutError("ambiguous acknowledgement")
    stats = {}
    box = D.Outbox(tmp_path, SID, SimpleNamespace(damage=fail), stats, threaded=False)
    box.emit(event())
    assert not box.flush_one() and len(box.files()) == 1
    box.close()
    resumed = D.Outbox(tmp_path, SID, SimpleNamespace(damage=lambda e: {"accepted": True, "event_id": "wrong"}), stats, threaded=False)
    assert not resumed.flush_one() and resumed.files()
    resumed.sink = SimpleNamespace(damage=lambda e: calls.append(e["event_id"]) or {"accepted": True, "event_id": e["event_id"]})
    assert resumed.flush_one() and not resumed.files()
    assert calls == ["event_12345678", "event_12345678"]


def test_rejected_receipt_does_not_starve_later_events_in_same_session(tmp_path):
    calls = []
    def deliver(e):
        calls.append(e["event_id"])
        if e["event_id"] == "event_00000001":
            raise ValueError("conflicting old receipt requires inspection")
        return {"accepted": True, "event_id": e["event_id"]}
    box = D.Outbox(tmp_path, SID, SimpleNamespace(damage=deliver), {}, threaded=False)
    box.emit(event("event_00000001"))
    box.emit(event("event_00000002"))
    original = (tmp_path / "event_00000001.json").read_bytes()
    assert not box.flush_one()
    assert box.flush_one()
    assert not box.flush_one()
    assert calls == ["event_00000001", "event_00000002", "event_00000001"]
    assert (tmp_path / "event_00000001.json").read_bytes() == original
    assert len(box.files()) == 1                  # failed event retained, successful event acknowledged once


def test_replay_progress_survives_more_than_64_old_sessions_and_sender_restart(tmp_path):
    import hashlib
    delivered, originals = set(), {}
    for i in range(65):
        sid = f"old-session-{i}"
        directory = tmp_path / hashlib.sha256(sid.encode()).hexdigest()
        old = D.Outbox(directory, sid, None, {}, threaded=False)
        old.emit(event("event_00000001"))
        old.emit(event("event_00000002"))
        originals[directory] = (directory / "event_00000001.json").read_bytes()
    def deliver(e):
        if e["event_id"] == "event_00000001":
            raise ValueError("rejected receipt retained for inspection")
        delivered.add(e["session_id"])
        return {"accepted": True, "event_id": e["event_id"]}
    sink = SimpleNamespace(damage=deliver)
    first = D.Outbox(tmp_path / "_worker-replay", "", sink, {}, threaded=False)
    # First complete scan attempts the rejected receipt in all65directories, then the sender restarts.
    for _ in range(66):
        first.replay_turn = False
        first.flush_one()
    assert not delivered
    first.close()
    resumed = D.Outbox(tmp_path / "_worker-replay", "", sink, {}, threaded=False)
    for _ in range(66):
        resumed.replay_turn = False
        resumed.flush_one()
    assert delivered == {f"old-session-{i}" for i in range(65)}
    for directory, original in originals.items():
        assert (directory / "event_00000001.json").read_bytes() == original
        assert not (directory / "event_00000002.json").exists()
        assert len((directory / ".delivery-cursor").read_bytes()) < 256


def test_outbox_capacity_reports_backpressure_and_never_evicts_previous_event(tmp_path):
    stats = {}
    box = D.Outbox(tmp_path, SID, None, stats, threaded=False, count_limit=1)
    box.emit(event())
    original = box.files()[0].read_bytes()
    with pytest.raises(D.Backpressure):
        box.emit(event("event_22222222"))
    assert (tmp_path / "event_12345678.json").read_bytes() == original and len(box.files()) == 2
    reserve = json.loads((tmp_path / "000-backpressure.json").read_bytes())
    assert reserve["event_id"] == "event_22222222" and reserve["loss"] == 100
    assert reserve["evidence_backpressure"] is True and box.capacity_blocked
    assert D.Outbox(tmp_path, SID, None, {}, threaded=False).capacity_blocked
    assert stats["player_damage_status"] == "backpressure"


def test_cached_frame_is_frozen_nonblocking_without_creating_stream():
    import base64
    import threading
    stream = SimpleNamespace(cond=threading.Condition(threading.Lock()), latest=b"\xff\xd8original\xff\xd9",
                             closed=False, clock=lambda: 20.0, last_frame=19.9, seq=4)
    ad = SimpleNamespace(stream=stream, stream_session=lambda: pytest.fail("new capture"))
    image = D.cached_frame(ad, now=lambda: 100)
    stream.latest = b"\xff\xd8later\xff\xd9"
    assert base64.b64decode(image["data_b64"]) == b"\xff\xd8original\xff\xd9"
    assert image["at"] == pytest.approx(99.9) and image["seq"] == 4
    with stream.cond:
        assert D.cached_frame(ad)["state"] == "unavailable-at-hit"
    stream.latest = b"\xff\xd8" + b"x" * D.FRAME_MAX + b"\xff\xd9"
    assert "128 KiB" in D.cached_frame(ad)["detail"]
    assert D.cached_frame(None)["state"] == "unavailable-at-hit"


def test_optional_frame_cannot_exhaust_other_event_evidence_budget(tmp_path):
    import base64
    box = D.Outbox(tmp_path, SID, None, {}, threaded=False)
    e = event(raw={"hex": "a" * 150000}, frame_at_hit={"state": "cached-at-observation", "at": 100,
              "data_b64": base64.b64encode(b"\xff\xd8" + b"x" * 100000 + b"\xff\xd9").decode()})
    box.emit(e)
    saved = json.loads(box.files()[0].read_bytes())
    assert saved["raw"] == e["raw"] and saved["loss"] == 100
    assert saved["frame_at_hit"]["state"] == "unavailable-at-hit" and "data_b64" not in saved["frame_at_hit"]
    assert not box.capacity_blocked


def test_sender_does_not_hold_emit_lock_and_delete_waits_for_it(tmp_path):
    import threading
    sent, release, done = threading.Event(), threading.Event(), threading.Event()
    def deliver(e):
        sent.set()
        assert release.wait(2)
        return {"accepted": True, "event_id": e["event_id"]}
    box = D.Outbox(tmp_path, SID, SimpleNamespace(damage=deliver), {}, threaded=False)
    box.emit(event())
    t = threading.Thread(target=lambda: (box.flush_one(), done.set()))
    t.start()
    assert sent.wait(2)
    box.emit(event("event_22222222"))              # network wait cannot block durable producer
    with box.lock:
        release.set()
        assert not done.wait(.1)                 # unlink uses the same short lock as emit/stat
        assert len(box.files()) == 2
    t.join(2)
    assert done.is_set() and len(box.files()) == 1


def test_old_session_outbox_replays_original_endpoint_after_new_session(tmp_path):
    import hashlib
    import httpx
    from gbox.mercs.tactical import HttpSink
    received = []
    def receive(request):
        body = json.loads(request.content)
        received.append((request.url.path, body["session_id"]))
        return httpx.Response(200, json={"accepted": True, "event_id": body["event_id"]})
    old = D.Outbox(tmp_path / hashlib.sha256(SID.encode()).hexdigest(), SID, None, {}, threaded=False)
    old.emit(event())
    sink = HttpSink("http://fixture", {}, "new-session", client=httpx.Client(base_url="http://fixture",
                   transport=httpx.MockTransport(receive)))
    new = D.Outbox(tmp_path / hashlib.sha256(b"new-session").hexdigest(), "new-session", sink, {}, threaded=False)
    assert new.flush_one()
    assert received == [(f"/api/autoplay/damage/{SID}", SID)] and not old.files()
    sink.close()


def test_worker_replays_after_bot_stops_without_another_game_and_retries_same_id(tmp_path):
    import hashlib
    import threading
    stop, accepted = threading.Event(), threading.Event()
    calls, closed, stats = [], [], {}
    root = tmp_path / "player-damage-outbox" / hashlib.sha256(SID.encode()).hexdigest()
    bot = D.Outbox(root, SID, None, {}, threaded=False)
    bot.emit(event())
    bot.close()                                  # no autoplay/session is created by the delivery service
    def deliver(e):
        calls.append(e["event_id"])
        if len(calls) == 1:
            raise TimeoutError("control plane restarting")
        accepted.set()
        return {"accepted": True, "event_id": e["event_id"]}
    sink = SimpleNamespace(damage=deliver, close=lambda: closed.append(True))
    thread = threading.Thread(target=D.run_delivery,
        args=(tmp_path, "http://fixture", {}, stop, stats),
        kwargs={"sink_factory": lambda *a, **k: sink, "poll_s": .01})
    thread.start()
    assert accepted.wait(2)
    stop.set()
    thread.join(2)
    assert not thread.is_alive() and calls == [event()["event_id"]] * 2
    assert closed == [True] and not bot.files()


def test_near_limit_compact_event_is_accepted_without_whitespace_expansion(ledger):
    store, _, _ = ledger
    # Thousands of small fields make the default spaced JSON significantly larger than the wire encoding.
    e = event(logic={str(i): i for i in range(3000)})
    compact = lambda value: json.dumps(value, separators=(",", ":")).encode()
    e["padding"] = "x" * (D.EVENT_MAX - len(compact(e)) - len(',"padding":""') - 8)
    raw = compact(e)
    assert D.EVENT_MAX - 16 < len(raw) <= D.EVENT_MAX
    assert len(json.dumps(e).encode()) > P.MAX_EVENT
    assert P.ingest(store, SID, e, provider(), now=100)["accepted"]


def test_engine_evidence_precedes_health_and_backpressure_releases_held_input():
    readings, sent, events = [snap(), snap(29900, 30000), snap(29800, 30000)], [], []
    time = [1.0]
    class Driver:
        def snapshot(self, m): return readings.pop(0)
        def screen(self, m, s): return "playing"
        def prompt_source(self, m, stats): return None
        def prompt_keys(self, b): return []
        def progress(self, s): return {}
    class Brain:
        def observe_round(self, s, where, now): s["player"].update(hp=30000, hp_max=30000)
        def tick(self, s): return {"hold": {"l1", "r1"}}
        def prompt_ok(self, *args): return True
        def save(self): pass
    obs = observer(events)
    def emit(e):
        events.append(copy.deepcopy(e))
        if len(events) == 2:
            raise D.Backpressure("fixture full")
    obs.emit = emit
    stats = {}
    why = engine.play_round({}, None, sent.extend, lambda: not readings, stats, driver=Driver(), brain=Brain(),
                            damage=obs, clock=lambda: time[0], sleep=lambda n: time.__setitem__(0, time[0] + n))
    assert why == "evidence_backpressure" and [e["loss"] for e in events] == [100, 200]
    assert len(events[0]["provenance"]["loaded_snapshot_code_sha256"]) == 64
    assert events[0]["provenance"]["debugger_trace"].startswith("not captured")
    assert sent[-2:] == [{"key": "l1", "down": False}, {"key": "r1", "down": False}]
    assert stats["player_damage_status"] == "backpressure"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.put("session", SID, {"session_id": SID, "state": "running", "adapter": "rpcs3", "game_id": "game"})
    store.put("worker", "worker", {"last_seen": __import__("time").time()})
    calls = []
    def create(body, actor):
        calls.append(body)
        req = dict(body, id=f"request{len(calls)}", messages=[], status="open")
        store.put("request", req["id"], req)
        return req
    monkeypatch.setattr(P.E, "render_map", lambda frame, stage: b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    return store, create, calls


def provider(at=99.9, jpeg=b"\xff\xd8original\xff\xd9"):
    return lambda sid: {"stream": {"data": jpeg, "at": at, "seq": 4},
        "tactical": {"frame": {"stage": "stage1"}, "stage": {"key": "stage1"}, "at": at}}


def test_durable_receipt_dedup_and_frozen_original_moment_before_materialization(ledger):
    store, create, calls = ledger
    p = provider()
    assert P.ingest(store, SID, event(), p, now=100.1)["accepted"]
    assert P.ingest(store, SID, event(), lambda sid: pytest.fail("retry recaptured"), now=120)["deduplicated"]
    row = P.materialize(store, create, lambda *a: pytest.fail("RPCS3 state job"), P.key(SID, event()["event_id"]))
    assert row["state"] == "done" and len(calls) == 1 and calls[0]["kind"] == "report"
    assert calls[0]["author"] == "agent" and calls[0]["automated"] and calls[0]["source"] == "player_damage"
    assert calls[0]["context"]["auto_report"] is True
    assert row["save_state"]["state"] == "skipped_disruptive"
    frame = next(a for a in row["attachments"] if a["type"] == "image/jpeg")
    assert store.read_artifact(frame["sha256"]) == b"\xff\xd8original\xff\xd9"
    moment = json.loads(store.read_artifact(row["evidence"]["moment"]["sha256"]))
    assert moment["sources"]["ram_fields"]["data"]["snapshot"]["player"]["hp"] == 900
    assert moment["sources"]["tactical"]["source_at"] == 100
    assert moment["sources"]["stream"]["offset_from_event_s"] == pytest.approx(-0.1)
    assert row["cause"] == row["self_damage"] == "unknown"
    assert "no image retained" in row["evidence"]["stream"]["timing"]


def test_worker_frame_survives_outage_and_wins_over_later_server_cache(ledger):
    import base64
    store, create, _ = ledger
    e = event(frame_at_hit={"state": "cached-at-observation", "at": 99.98, "seq": 7,
        "timestamp_basis": "fixture encoder time", "data_b64": base64.b64encode(b"\xff\xd8hit\xff\xd9").decode()},
        provenance={"effective_profile_sha256": "a" * 64})
    P.ingest(store, SID, e, provider(at=119.9, jpeg=b"\xff\xd8later\xff\xd9"), now=120)
    row = P.materialize(store, create, None, P.key(SID, e["event_id"]))
    frame = next(a for a in row["attachments"] if a["type"] == "image/jpeg")
    assert store.read_artifact(frame["sha256"]) == b"\xff\xd8hit\xff\xd9"
    moment = json.loads(store.read_artifact(row["evidence"]["moment"]["sha256"]))
    assert moment["sources"]["stream"]["source_at"] == 99.98
    assert moment["provenance"] == e["provenance"] and moment["delivery_delay_s"] == 20


def test_batch_keeps_every_event_one_request_and_reopens_for_late_damage(ledger):
    store, create, calls = ledger
    for n in range(24):
        e = event(f"event_{n:08}", observed_at=100 + n)
        P.ingest(store, SID, e, provider(), now=100 + n)
        P.materialize(store, create, None, P.key(SID, e["event_id"]))
    assert len(calls) == 1 and len(P.rows(store, SID, RUN)) == 24
    req = store.get("request", "request1")
    assert len(req["messages"]) == 1 and req["messages"][0]["damage_run"]["events"] == 24
    assert req["messages"][0]["damage_run"]["summary_events"] == 20
    req["status"] = "done"
    store.put("request", "request1", req)
    e = event("event_99999999")
    P.ingest(store, SID, e, provider(), now=125)
    P.materialize(store, create, None, P.key(SID, e["event_id"]))
    assert len(calls) == 1 and store.get("request", "request1")["status"] == "open"


def test_uncertain_request_create_recovers_persisted_batch_without_duplicate(ledger):
    store, create, calls = ledger
    P.ingest(store, SID, event(), provider(), now=100)
    def ambiguous(body, actor):
        create(body, actor)
        raise TimeoutError("lost create response")
    eid = P.key(SID, event()["event_id"])
    assert P.materialize(store, ambiguous, None, eid)["state"] == "retrying"
    assert P.materialize(store, create, None, eid)["state"] == "done"
    assert len(calls) == 1


def test_save_capture_backpressure_and_later_receipt_keep_explicit_timing(ledger):
    store, create, calls = ledger
    session = store.get("session", SID)
    store.put("session", SID, dict(session, adapter="dolphin"))
    jobs = []
    def submit(tool, inp, rid, actor):
        assert actor == "gbox-auto"
        job = {"id": "job1", "tool": tool, "state": "queued"}
        jobs.append(job)
        store.put("job", "job1", job)
        return job
    for i in range(2):
        e = event(f"event_{i:08}", run_id=RUN if i == 0 else "other_12345678")
        P.ingest(store, SID, e, provider(), now=100)
        P.materialize(store, create, submit, P.key(SID, e["event_id"]))
    rows = P.rows(store, SID, RUN) + P.rows(store, SID, "other_12345678")
    assert len(jobs) == 1
    assert {r["save_state"]["state"] for r in rows} == {"pending", "skipped-backpressure"}
    ref = store.put_artifact(b"supported state", "state.s10", "application/octet-stream", {})
    store.put("job", "job1", dict(jobs[0], state="succeeded", output={"result": {"artifact": ref.sha256, "file": "state.s10"}}))
    P.settle_states(store)
    state = next(r["save_state"] for r in P.rows(store, SID, RUN) if r["save_state"]["state"] == "done")
    assert state["timing"] == "asynchronous after observed HP loss"


def test_pending_saves_do_not_hide_later_terminal_or_missing_job_receipts(ledger):
    store, _, _ = ledger
    store.put("request", "batch", {"id": "batch", "status": "open", "messages": []})
    for i in range(34):
        eid, jid = f"event_{i:08}", f"job{i}"
        row = event(eid) | {"id": eid, "request_id": "batch", "state": "done", "attachments": [],
                           "save_state": {"state": "pending", "job": jid}}
        store.put(P.KIND, eid, row)
        if i < 33:
            store.put("job", jid, {"id": jid, "state": "queued" if i < 32 else "failed", "error": "fixture failure"})
    P.settle_states(store)
    assert all(store.get(P.KIND, f"event_{i:08}")["save_state"]["state"] == "pending" for i in range(32))
    assert store.get(P.KIND, "event_00000032")["save_state"]["state"] == "failed"
    missing = store.get(P.KIND, "event_00000033")["save_state"]
    assert missing["state"] == "uncertain" and "no automatic resubmission" in missing["detail"]


def test_damage_poll_ignores_completed_archive_and_does_not_wait_for_writer(ledger):
    import threading
    store, _, _ = ledger
    for i in range(40):
        store.put(P.KIND, str(i), {"state": "done", "save_state": {"state": "done"}})
    store.put(P.KIND, "due", {"state": "pending"})
    store.put(P.KIND, "later", {"state": "retrying", "next_attempt_at": 200})
    store.put(P.KIND, "retry", {"state": "retrying", "next_attempt_at": 90})
    done = threading.Event()
    observed = []
    def read():
        observed.extend(P.pending_events(store, 100))
        P.settle_states(store)
        done.set()
    # A concurrent live command may hold the writer. Background polling must
    # read the committed snapshot without joining that queue.
    with store.lock:
        thread = threading.Thread(target=read)
        thread.start()
        completed = done.wait(2)
    thread.join(2)
    assert completed and observed == ["due", "retry"]
    plans = []
    with store.reading() as db:
        plans.append(db.execute("EXPLAIN QUERY PLAN SELECT id FROM docs WHERE kind=? "
            "AND json_extract(body,'$.state') != 'done' "
            "AND COALESCE(json_extract(body,'$.next_attempt_at'),0)<=? ORDER BY rowid LIMIT 32",
            (P.KIND, 100)).fetchall())
        plans.append(db.execute("EXPLAIN QUERY PLAN SELECT body FROM docs WHERE kind=? "
            "AND json_extract(body,'$.save_state.state')='pending'", (P.KIND,)).fetchall())
    assert "docs_damage_unmaterialized" in str(plans[0])
    assert "docs_damage_save_state" in str(plans[1])


def test_failed_durable_write_is_not_acknowledged(ledger, monkeypatch):
    store, _, _ = ledger
    monkeypatch.setattr(store, "put_artifact", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        P.ingest(store, SID, event(), provider(), now=100)
    assert not store.all(P.KIND)


def test_exact_session_conflicting_retry_validation_and_paged_receipt(ledger):
    store, create, _ = ledger
    app = FastAPI()
    P.routes(app, store, lambda: "worker", create, None, provider())
    client = TestClient(app)  # no background lifespan; explicitly materialize in this test
    assert client.post(f"/api/autoplay/damage/{SID}", json=event()).status_code == 200
    assert client.post(f"/api/autoplay/damage/{SID}", json=event(loss=2)).status_code == 422
    assert client.post("/api/autoplay/damage/other-session", json=event()).status_code == 422
    for n in range(3):
        assert client.post(f"/api/autoplay/damage/{SID}", json=event(f"event_{n:08}")).status_code == 200
    page = client.get(f"/api/sessions/{SID}/damage/runs/{RUN}?limit=2").json()
    assert page["total"] == 4 and len(page["events"]) == 2 and page["next_offset"] == 2
    assert client.get(f"/api/sessions/other-session/damage/runs/{RUN}").status_code == 404


def test_normal_queue_requires_real_damage_batch_link_and_still_holds_busy_game(ledger, monkeypatch):
    from gbox import hermes_work_queue as Q
    store, create, _ = ledger
    P.ingest(store, SID, event(), provider(), now=100)
    P.materialize(store, create, None, P.key(SID, event()["event_id"]))
    req = store.get("request", "request1")
    app = FastAPI()
    P.routes(app, store, lambda: "agent", create, None, provider())
    client = TestClient(app)
    monkeypatch.setattr(Q, "_api", lambda path: client.get(path).raise_for_status().json())
    data = {"items": {}}
    Q.sync(data, {"count": 0, "items": []}, [req], now=101)
    assert list(data["items"]) == ["inbox:request1"]
    assert Q.candidates(data, [req], [], set(), set(), now=102)
    assert not Q.candidates(data, [req], [{"input": {"game_id": "game"}}], set(), set(), now=102)
    assert not Q.candidates(data, [req], [], {"request1"}, set(), now=102)
    assert not Q.is_live_coaching(req)
    forged = copy.deepcopy(req)
    forged["id"] = "unrelated-request"
    fresh = {"items": {}}
    Q.sync(fresh, {"count": 0, "items": []}, [forged], now=102)
    assert not fresh["items"]                         # even with auto_report/operator_requested copied
    monkeypatch.setattr(Q, "_api", lambda path: (_ for _ in ()).throw(OSError("offline")))
    assert not Q.requested_player_damage(req)
    Q.sync(data, {"count": 0, "items": []}, [req], now=103)
    assert data["items"]["inbox:request1"]["damage_batch_verified"] is False
    assert not Q.candidates(data, [req], [], set(), set(), now=104)
    data["items"]["inbox:request1"].update(dispatch_state="queued", job_id="active-job")
    Q.sync(data, {"count": 0, "items": []}, [req], now=105)
    assert data["items"]["inbox:request1"]["job_id"] == "active-job"  # no cancellation of existing work


def test_concurrent_delivery_and_materialization_have_one_receipt_and_one_batch(ledger):
    from concurrent.futures import ThreadPoolExecutor
    store, create, calls = ledger
    def deliver(_):
        P.ingest(store, SID, event(), provider(), now=100)
        return P.materialize(store, create, None, P.key(SID, event()["event_id"]))
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(deliver, range(8)))
    assert len(calls) == 1 and len(store.all(P.KIND)) == 1
    assert {r["request_id"] for r in result} == {"request1"}
