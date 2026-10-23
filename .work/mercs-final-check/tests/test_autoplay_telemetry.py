"""Autoplay telemetry for the watch panel (gbox.screensaver TELEMETRY): live while posted, stale after, then gone."""
import json

import pytest

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


@pytest.fixture
def telemetry_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    # No lifespan context: the tests exercise HTTP telemetry without starting
    # the background screensaver scheduler or creating any native job.
    S.install(app, None, None, lambda: "worker", lambda *a, **k: None, lambda: [], None)
    S.TELEMETRY.clear()
    return TestClient(app)


def test_rich_re5_telemetry_over_the_old_limit_stays_live(telemetry_client):
    stats = {
        "profile": "BLUS30491", "screen": "playing", "phase": "gather_time",
        "curriculum": {"mode": "mercenaries", "character": "Wesker (Midnight)", "stage": 0},
        "navigation": {"goal": "time", "position": [556.97, 158.48, 1409.1],
                       "checkpoints": [{"position": [i * 120, 0, i * 80], "acquired": i < 2} for i in range(12)]},
        "mines": {"armed": 1, "detonated": 0, "recovered": 0},
        "diagnostics": [{"tick": i, "action": "follow route", "wall": False,
                         "position": [i * 3.0, 0, i * 2.0]} for i in range(100)],
    }
    assert 8000 < len(json.dumps(stats).encode()) < S.TELEMETRY_STATS_MAX_BYTES
    response = telemetry_client.post("/api/autoplay/telemetry/spark-re5", json={"stats": stats, "running": True})
    assert response.status_code == 200
    live = telemetry_client.get("/api/autoplay/telemetry/spark-re5").json()
    assert live["running"] is True and live["age_s"] < 2 and live["stats"] == stats


def test_stats_limit_counts_encoded_utf8_bytes_and_keeps_last_valid_packet(telemetry_client):
    url = "/api/autoplay/telemetry/spark-re5"
    # {"x":"..."} contributes eight bytes; multibyte text must count as UTF-8.
    exact = {"x": "é" * ((S.TELEMETRY_STATS_MAX_BYTES - 8) // 2)}
    assert len(json.dumps(exact, ensure_ascii=False, separators=(",", ":")).encode()) == S.TELEMETRY_STATS_MAX_BYTES
    assert telemetry_client.post(url, json={"stats": exact}).status_code == 200
    oversized = {"x": exact["x"] + "é"}
    assert telemetry_client.post(url, json={"stats": oversized}).status_code == 413
    assert telemetry_client.get(url).json()["stats"] == exact


@pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_stats_are_rejected_without_poisoning_live_view(telemetry_client, invalid):
    url = "/api/autoplay/telemetry/spark-re5"
    assert telemetry_client.post(url, json={"stats": {"kills": 4}}).status_code == 200
    raw = '{"stats":{"navigation":{"distance":' + invalid + '}}}'
    response = telemetry_client.post(url, content=raw, headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert telemetry_client.get(url).json()["stats"] == {"kills": 4}
