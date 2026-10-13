"""#712: the request history (polled by the desktop inbox) and artifacts are cheap to re-ask for."""
from fastapi.testclient import TestClient

from gbox.server import create_app


def test_unchanged_inbox_answers_304_and_any_change_or_filter_gets_a_new_tag(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    rid = client.post("/api/requests", json={"title": "Slow app", "body": "menus lag"}).json()["id"]
    first = client.get("/api/requests")
    tag = first.headers["etag"]
    assert first.status_code == 200 and first.json()[0]["id"] == rid
    again = client.get("/api/requests", headers={"if-none-match": tag})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == tag
    filtered = client.get("/api/requests?status=open", headers={"if-none-match": tag})
    assert filtered.status_code == 200 and filtered.headers["etag"] != tag, "a filtered list is a different answer"
    client.post(f"/api/requests/{rid}/messages", json={"author": "agent", "text": "found it"})
    changed = client.get("/api/requests", headers={"if-none-match": tag})
    assert changed.status_code == 200 and changed.headers["etag"] != tag
    assert changed.json()[0]["messages"][-1]["text"] == "found it"
    stored = app.state.store.get("request", rid)                  # a writer outside the API (a script) is seen too
    stored["title"] = "Slow app (edited)"
    app.state.store.put("request", rid, stored)
    assert client.get("/api/requests", headers={"if-none-match": changed.headers["etag"]}).status_code == 200


def test_artifacts_are_immutable_in_client_caches(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    ref = client.post("/api/artifacts?name=shot.png&media_type=image/png", content=b"\x89PNG fake").json()
    r = client.get(f"/api/artifacts/{ref['sha256']}")
    assert r.status_code == 200 and r.content == b"\x89PNG fake"
    assert "immutable" in r.headers["cache-control"] and "max-age=31536000" in r.headers["cache-control"]
