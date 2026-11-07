"""Handing abandoned work back: `inbox.stale_in_progress` and `inbox.hand_back`.

Measured 2026-11-07: 1,694 of 8,894 requests were `in_progress` against 1,109 `open`. The analysis cap bounds how many
tickets a title may *leave open*; nothing released a ticket a worker claimed and abandoned. These tests pin the decision
- which requests are quiet enough to hand back - and the shape of the handed-back document.
"""
import pytest

from gbox import inbox as I

NOW = 10_000_000.0
HOUR = 3600.0


def row(rid, status="in_progress", *, created_hours=12.0, started_hours=None, messages=()):
    return {"id": rid, "status": status, "created": NOW - created_hours * HOUR,
            "started": None if started_hours is None else NOW - started_hours * HOUR,
            "messages": list(messages)}


def test_only_quiet_in_progress_work_is_handed_back():
    rows = [row("quiet"),
            row("recent", started_hours=1.0),                       # claimed an hour ago: still being worked
            row("open", status="open", created_hours=96.0),         # waiting on purpose
            row("done", status="done", created_hours=96.0),         # settled
            row("undated", created_hours=0.0)]                      # no timestamp at all
    rows[-1]["created"] = 0
    got = [r["id"] for r in I.stale_in_progress(rows, now=NOW)]
    assert got == ["quiet"]


def test_a_move_on_the_ticket_restarts_the_clock():
    """A message or a task step is activity, so a long-running ticket that is still reporting is left alone."""
    rows = [row("busy", created_hours=20.0, messages=[{"ts": NOW - 60.0}]),
            row("stepped", created_hours=20.0, messages=[{"ts": NOW - 9 * HOUR, "task_step": {"at": NOW - 120.0}}]),
            row("silent", created_hours=20.0, messages=[{"ts": NOW - 9 * HOUR}])]
    got = [r["id"] for r in I.stale_in_progress(rows, now=NOW)]
    assert got == ["silent"]


def test_the_limit_takes_the_quietest_first():
    rows = [row("a", created_hours=7.0), row("b", created_hours=40.0), row("c", created_hours=20.0)]
    got = [r["id"] for r in I.stale_in_progress(rows, now=NOW, limit=2)]
    assert got == ["b", "c"], "the longest-quiet requests are the ones to release first"


def test_the_threshold_is_configurable_and_excludes_recent_work():
    rows = [row("three_hours", created_hours=3.0), row("seven_hours", created_hours=7.0)]
    # quietest first: seven hours without a move comes before three
    assert [r["id"] for r in I.stale_in_progress(rows, now=NOW, after_s=2 * HOUR)] == ["seven_hours", "three_hours"]
    assert [r["id"] for r in I.stale_in_progress(rows, now=NOW, after_s=6 * HOUR)] == ["seven_hours"]


def test_handing_back_reopens_the_ticket_and_says_why():
    original = row("quiet", created_hours=12.0, messages=[{"author": "agent", "text": "started", "ts": NOW - 9 * HOUR}])
    out = I.hand_back(original, now=NOW)
    assert out["status"] == "open" and out["started"] is None
    assert out["handed_back_at"] == NOW
    assert len(out["messages"]) == len(original["messages"]) + 1     # nothing is lost
    note = out["messages"][-1]
    assert note["author"] == "system" and "Returned to the queue" in note["text"]
    assert "9.0 h" in note["text"] and "6 h" in note["text"]
    # the original document is untouched, so a caller can log both
    assert original["status"] == "in_progress" and len(original["messages"]) == 1


def test_activity_uses_the_newest_of_creation_claim_and_messages():
    assert I.activity({"created": 10.0, "started": 20.0, "messages": [{"ts": 30.0}]}) == 30.0
    assert I.activity({"created": 10.0}) == 10.0
    assert I.activity({}) == 0.0
