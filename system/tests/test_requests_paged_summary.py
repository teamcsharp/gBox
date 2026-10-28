"""GET /api/requests?limit=N&offset=M and ?summary=1, the paged and summary inbox routes (#4485).
2026-10-27: the desktop inbox pulled the whole history (46 MB) once a minute; over the operator's Wi-Fi it took 26 s
and the 8 s timeout aborted it every time, so the inbox never loaded."""
from fastapi.testclient import TestClient

from gbox import inbox
from gbox.server import create_app


def _client(cfg):
    app = create_app(cfg)
    return app, TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})


def _seed(client, n=5):
    ids = []
    for i in range(n):
        r = client.post("/api/requests", json={"title": f"Request {i+1}", "body": f"body {i+1}"})
        ids.append(r.json()["id"])
    return ids


def test_limit_returns_newest_n_full_rows(cfg):
    _, client = _client(cfg)
    ids = _seed(client, 5)
    rows = client.get("/api/requests?limit=3").json()
    assert len(rows) == 3
    # newest first: the last-created ids come first
    assert [r["id"] for r in rows] == [ids[4], ids[3], ids[2]]
    # full rows keep messages and metrics keys (they may be empty lists/dicts)
    for r in rows:
        assert "messages" in r and "metrics" in r


def test_limit_and_offset_page_through_the_history(cfg):
    _, client = _client(cfg)
    ids = _seed(client, 6)
    page1 = client.get("/api/requests?limit=2&offset=0").json()
    page2 = client.get("/api/requests?limit=2&offset=2").json()
    page3 = client.get("/api/requests?limit=2&offset=4").json()
    assert [r["id"] for r in page1] == [ids[5], ids[4]]
    assert [r["id"] for r in page2] == [ids[3], ids[2]]
    assert [r["id"] for r in page3] == [ids[1], ids[0]]
    assert client.get("/api/requests?limit=2&offset=6").json() == []


def test_summary_returns_counts_by_status_and_source_plus_newest_lite_rows(cfg):
    _, client = _client(cfg)
    open_id = client.post("/api/requests", json={"title": "Open", "body": "o" * 3000, "source": "app"}).json()["id"]
    done_id = client.post("/api/requests", json={"title": "Done", "body": "d" * 500, "source": "api"}).json()["id"]
    client.post(f"/api/requests/{done_id}/status", json={"status": "done", "note": "Verified"})
    child = client.post("/api/requests", json={"title": "Sub", "body": "s" * 100, "source": "automation",
                                               "parent_request_id": open_id}).json()["id"]
    summary = client.get("/api/requests?summary=1").json()
    # the child request defaults to open too
    assert summary["counts"]["by_status"]["open"] == 2
    assert summary["counts"]["by_status"]["done"] == 1
    assert summary["counts"]["by_source"]["app"] == 1
    assert summary["counts"]["by_source"]["api"] == 1
    assert summary["counts"]["by_source"]["automation"] == 1
    assert summary["total"] == 3
    newest = summary["newest"]
    assert len(newest) == 3
    # lite rows: no messages or metrics, long bodies cut
    by_id = {r["id"]: r for r in newest}
    assert "messages" not in by_id[open_id] and "metrics" not in by_id[open_id]
    assert by_id[open_id]["body"] == "o" * inbox.LITE_OPEN_BODY
    assert by_id[open_id]["body_chars"] == 3000
    assert by_id[done_id]["body"] == "d" * inbox.LITE_CLOSED_BODY
    assert by_id[done_id]["body_chars"] == 500


def test_summary_limit_controls_newest_count(cfg):
    _, client = _client(cfg)
    _seed(client, 5)
    summary = client.get("/api/requests?summary=1&limit=2").json()
    assert len(summary["newest"]) == 2
    assert summary["total"] == 5


def test_paged_and_summary_routes_have_distinct_etags_and_answer_304(cfg):
    _, client = _client(cfg)
    _seed(client, 3)
    paged = client.get("/api/requests?limit=2")
    paged_tag = paged.headers["etag"]
    summary = client.get("/api/requests?summary=1")
    summary_tag = summary.headers["etag"]
    assert paged_tag != summary_tag
    assert client.get("/api/requests?limit=2", headers={"if-none-match": paged_tag}).status_code == 304
    assert client.get("/api/requests?summary=1", headers={"if-none-match": summary_tag}).status_code == 304
    # a different page is a different answer
    assert client.get("/api/requests?limit=2&offset=2").headers["etag"] != paged_tag


def test_summary_respects_status_filter(cfg):
    _, client = _client(cfg)
    open_id = client.post("/api/requests", json={"title": "Open", "body": "o"}).json()["id"]
    done_id = client.post("/api/requests", json={"title": "Done", "body": "d"}).json()["id"]
    client.post(f"/api/requests/{done_id}/status", json={"status": "done", "note": "Verified"})
    summary = client.get("/api/requests?summary=1&status=open").json()
    assert summary["total"] == 1
    assert summary["counts"]["by_status"] == {"open": 1}
    assert [r["id"] for r in summary["newest"]] == [open_id]
