"""Autoplay telemetry for the watch panel (gbox.screensaver TELEMETRY): live while posted, stale after, then gone."""
from gbox import screensaver as S


def test_telemetry_is_live_then_stale_then_gone():
    S.TELEMETRY.clear()
    S.telemetry_put("w-1", {"running": True, "mode": "playbook", "mission": "playbook: doa2_bot", "title": "DOA2",
                            "stats": {"jumps": 3}}, now=100.0)
    t = S.telemetry_get("w-1", now=104.0)
    assert t["running"] is True and t["stats"] == {"jumps": 3} and t["age_s"] == 4.0
    assert S.telemetry_get("w-1", now=140.0)["running"] is False          # the worker stopped posting
    assert S.telemetry_get("w-1", now=100.0 + S.TELEMETRY_TTL + 1) == {}
    assert S.telemetry_get("nope") == {}


def test_a_stopped_run_reads_stopped():
    S.TELEMETRY.clear()
    S.telemetry_put("w-2", {"running": False, "stats": {}}, now=10.0)
    assert S.telemetry_get("w-2", now=11.0)["running"] is False


def test_old_entries_are_dropped_on_put():
    S.TELEMETRY.clear()
    S.telemetry_put("old", {"stats": {}}, now=0.0)
    S.telemetry_put("new", {"stats": {}}, now=S.TELEMETRY_TTL + 5)
    assert "old" not in S.TELEMETRY
