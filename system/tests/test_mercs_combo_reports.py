"""The combo-loss follow reports (gbox.mercs.combo_reports): one request per loss, deduped, rate-capped, never fatal."""
import pytest

from gbox.mercs import combo_reports as CR

TITLE = "01002A000CD48000"


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    CR._CFG.update(url="http://x", token="tok", title=TITLE, session_id="sess-1")


def snap(combo, enemies=()):
    return {"player": {"ptr": 1, "pos": [0.0, 0.0, 0.0], "hp": 900}, "enemies": list(enemies), "combo": combo}


def test_one_report_per_loss_with_the_evidence(monkeypatch):
    calls = []
    monkeypatch.setattr(CR, "post", lambda url, token, payload: calls.append((url, token, payload)) or {"id": "req-1"})
    live = {"round_evidence_id": "round-7", "kills": 4, "score": 700, "timer": "01:12.00"}
    threats = [{"ptr": 2, "class": "uEm10", "pos": [250.0, 0.0, 0.0], "hp": 300},
               {"ptr": 3, "class": "uEm20", "pos": [900.0, 0.0, 0.0], "hp": 500}]
    CR.observe(live, snap(5, threats), 100.0, doing="fire", why="the nearest Ganado")
    reply = CR.observe(live, snap(0, threats), 101.0, doing="fire", why="the nearest Ganado")
    assert reply and reply["request"] == "req-1" and len(calls) == 1
    url, token, payload = calls[0]
    assert url == "http://x" and token == "tok" and payload["automated"] is True
    assert "round-7" in payload["title"] and "COMBO LOST" in payload["body"]
    assert "Combo: 5 -> 0" in payload["body"] and "uEm10 at 250 cm" in payload["body"]
    assert "uEm20" not in payload["body"]                      # farther than the 6 m window
    assert "fire" in payload["body"] and live["combo_reports"] == 1
    # the next tick at 0 is not a second loss
    assert CR.observe(live, snap(0, threats), 102.0) is None and len(calls) == 1


def test_a_second_loss_reports_again_and_the_round_caps_at_three(monkeypatch):
    calls = []
    monkeypatch.setattr(CR, "post", lambda url, token, payload: calls.append(payload) or {"id": f"req-{len(calls)}"})
    live = {"round_evidence_id": "round-8"}
    for combo in (5, 0, 3, 0, 2, 0, 4, 0):
        CR.observe(live, snap(combo), 100.0 + len(calls))
    assert len(calls) == 3                                     # four losses, three reports
    assert live["combo_reports_suppressed"] == 1
    # a new round starts the count over
    live["round_evidence_id"] = "round-9"
    CR.observe(live, snap(9), 200.0)
    CR.observe(live, snap(0), 201.0)
    assert len(calls) == 4 and live["combo_reports"] == 4


def test_a_failed_post_is_a_stat_and_never_raises(monkeypatch):
    def boom(url, token, payload):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(CR, "post", boom)
    live = {"round_evidence_id": "round-9"}
    CR.observe(live, snap(2), 100.0)
    assert CR.observe(live, snap(0), 101.0) is None
    assert live["combo_report_failures"] == 1 and "connection refused" in live["combo_report_error"]
    assert "combo_reports" not in live
