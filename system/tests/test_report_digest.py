"""The incident-report digest: what the evidence says, and that it says nothing it cannot support."""
import json

from gbox.mercs import report_digest


class Store:
    """The smallest store the digest needs: one table of documents, returned the way sqlite returns them."""

    def __init__(self, rows):
        self.rows = rows

        class Cursor:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return [(json.dumps(row),) for row in self.rows]

        class DB:
            def __init__(self, rows):
                self.rows = rows

            def execute(self, sql, args=()):
                return Cursor(self.rows)

        self.db = DB(rows)


def report(state, outcome="died", title="010018100CD46000", timer=120.0, shots=100, hits=90, kills=10, **extra):
    metrics = {"survival": {"timer": timer}, "aim": {"shots": shots, "hits": hits}, "engagement": {"kills": kills}}
    metrics.update(extra)
    return {"state": state, "title": title,
            "report": {"outcome": outcome, "category": "rank_not_verified", "metrics": metrics}}


def test_rates_are_per_minute_not_raw_counts():
    """A 4-minute death and a 1-minute completion must compare by rate, or the longer round always 'wins'."""
    rows = [report("analysed", outcome="died", timer=240.0, shots=240),
            report("analysed", outcome="completed", timer=60.0, shots=240)]
    out = report_digest.digest(Store(rows))
    assert out["per_minute"]["died"]["shots"] == 60.0
    assert out["per_minute"]["completed"]["shots"] == 240.0


def test_the_digest_counts_each_state_and_only_mines_analysed_reports():
    rows = [report("analysed"), report("queued_for_hermes"), {"state": "recorded_no_dispatch",
                                                              "reason": "no incident: the player was not killed"}]
    out = report_digest.digest(Store(rows))
    assert out["reports"] == 3 and out["analysed"] == 1
    assert out["outcomes"] == {"died": 1}
    assert "no incident" in next(iter(out["why_no_report"]))


def test_a_title_is_split_by_outcome():
    rows = [report("analysed", outcome="died", title="A"), report("analysed", outcome="completed", title="A"),
            report("analysed", outcome="died", title="B")]
    out = report_digest.digest(Store(rows))
    assert out["titles"]["A"] == {"died": 1, "completed": 1}
    assert out["titles"]["B"] == {"died": 1}


def test_missing_metrics_do_not_invent_a_rate():
    """A report with no survival timer must leave the per-minute figures alone rather than divide by zero."""
    rows = [{"state": "analysed", "title": "A", "report": {"outcome": "died", "metrics": {}}}]
    out = report_digest.digest(Store(rows))
    assert out["per_minute"]["died"]["shots"] is None
    assert out["minutes_analysed"]["died"] == 0.0
