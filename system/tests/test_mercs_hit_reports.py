"""The player-hurt follow reports (gbox.mercs.hit_reports): one request per hit, with the attackers, capped, never fatal."""
import pytest

from gbox.mercs import hit_reports as HR

TITLE = "01002A000CD48000"


@pytest.fixture(autouse=True)
def _configured():
    HR._CFG.update(url="http://x", token="tok", title=TITLE, session_id="sess-1")


def snap(hp=900):
    return {"player": {"ptr": 1, "pos": [10.0, 0.0, 20.0], "hp": hp}, "enemies": []}


def test_a_hit_files_one_report_with_the_attackers(monkeypatch):
    calls = []
    monkeypatch.setattr(HR, "post", lambda url, token, payload: calls.append(payload) or {"id": "hit-1"})
    live = {"round_evidence_id": "round-3", "hits_taken": 0, "timer": "01:00.00"}
    HR.observe(live, snap(900), 100.0, doing="aim", why="the steady aim")
    live["hits_taken"] = 1
    reply = HR.observe(live, snap(750), 101.0,
                       attackers=[{"kind": "uEm10", "dist": 120, "state": ["wind"], "eta": 0.4, "act": "attack"}],
                       doing="aim", why="the steady aim")
    assert reply and reply["request"] == "hit-1" and len(calls) == 1
    payload = calls[0]
    assert payload["automated"] is True and "round-3" in payload["title"]
    assert "hp 900 -> 750" in payload["body"] and "uEm10 at 120 cm" in payload["body"]
    assert "the steady aim" in payload["body"] and live["hit_reports"] == 1
    # the same hit counted again (no new hit) is not a second report
    assert HR.observe(live, snap(750), 102.0) is None and len(calls) == 1


def test_the_reports_are_capped_per_round_and_a_failed_post_is_a_stat(monkeypatch):
    calls = []
    monkeypatch.setattr(HR, "post", lambda url, token, payload: calls.append(payload) or {"id": f"h-{len(calls)}"})
    live = {"round_evidence_id": "round-4", "hits_taken": 0}
    HR.observe(live, snap(900), 100.0)
    for hit in range(1, HR.MAX_PER_ROUND + 3):
        live["hits_taken"] = hit
        HR.observe(live, snap(900 - hit * 10), 100.0 + hit)
    assert len(calls) == HR.MAX_PER_ROUND
    assert live["hit_reports_suppressed"] == 2

    def boom(url, token, payload):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(HR, "post", boom)
    live2 = {"round_evidence_id": "round-5", "hits_taken": 0}
    HR.observe(live2, snap(900), 200.0)
    live2["hits_taken"] = 1
    assert HR.observe(live2, snap(800), 201.0) is None
    assert live2["hit_report_failures"] == 1 and "connection refused" in live2["hit_report_error"]
    assert "hit_reports" not in live2


def test_the_damage_observers_count_is_the_primary_hurt_signal(monkeypatch):
    """RE6's driver keeps the hurt counter as player_damage_events (the damage Observer), not hits_taken - the report
    must follow the title's own counter."""
    calls = []
    monkeypatch.setattr(HR, "post", lambda url, token, payload: calls.append(payload) or {"id": "d1"})
    live = {"round_evidence_id": "round-6", "player_damage_run": "run-1", "player_damage_events": 0}
    HR.observe(live, snap(900), 100.0)
    live["player_damage_events"] = 1
    reply = HR.observe(live, snap(800), 101.0)
    assert reply and len(calls) == 1 and "hp 900 -> 800" in calls[0]["body"]
    assert live["hit_reports"] == 1


def test_a_new_rounds_first_hit_still_files(monkeypatch):
    """A new round's damage count starts over: its first hit must file, not be swallowed by the old round's baseline."""
    calls = []
    monkeypatch.setattr(HR, "post", lambda url, token, payload: calls.append(payload) or {"id": f"r-{len(calls)}"})
    live = {"round_evidence_id": "r1", "player_damage_events": 0}
    HR.observe(live, snap(900), 100.0)
    live["player_damage_events"] = 1
    HR.observe(live, snap(800), 101.0)
    assert len(calls) == 1 and live["hit_reports"] == 1
    live["round_evidence_id"] = "r2"
    live["player_damage_events"] = 1
    HR.observe(live, snap(700), 200.0)
    assert len(calls) == 2 and "r2" in calls[1]["title"] and "hp 800 -> 700" in calls[1]["body"]
