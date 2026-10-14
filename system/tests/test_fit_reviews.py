from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import numpy as np
import pytest

from gbox import build_feedback, fit_events, fit_reviews
from gbox.store import Store

GID = "0123456789abcdef"


@pytest.fixture
def review(tmp_path):
    store = Store(tmp_path / "data")
    cfg = SimpleNamespace(cache=tmp_path / "cache")
    folder = cfg.cache / "fitting-jobs" / "fit-job"
    primitive = [{"pos": np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]]), "tris": [[0, 1, 2]]}]
    fit_events.snapshot_glb(primitive, folder / "before.glb", max_tris=None)
    fit_events.snapshot_glb(primitive, folder / "after.glb", max_tris=None)
    pair = {"before": "/api/jobs/fit-job/fitting/files/before.glb", "after": "/api/jobs/fit-job/fitting/files/after.glb",
            "data": {"sampled": False, "geometry_only": True, "source_triangles": 1, "result_triangles": 1}}
    model = {"game": GID, "donor": "amy", "slot": "fighter:KAS", "label": "Amy / Kasumi", "comparison": pair}
    job = {"id": "fit-job", "tool": "characters", "state": "succeeded", "input": {"op": "use", "game_id": GID},
           "fitting": {"order": ["m"], "models": {"m": model}}}
    store.put("job", "fit-job", job)
    filed = []
    def file_report(issue, details, actor):
        filed.append(issue)
        rid = "review-" + str(len(filed))
        doc = {"id": rid, "number": len(filed), "messages": [{"attachments": issue["attachments"]}]}
        store.put("request", rid, doc)
        return doc
    app = FastAPI(); fit_reviews.routes(app, store, cfg, lambda: "operator", file_report=file_report)
    with TestClient(app) as client:
        yield client, store, folder, job, filed


def test_report_retains_exact_meshes_and_blocks_future_builds_until_feedback_is_reviewed(review):
    client, store, folder, job, filed = review
    view = client.get("/api/jobs/fit-job/fitting/review").json()
    assert view["models"][0]["comparison"]["data"]["sampled"] is False
    result = client.post("/api/jobs/fit-job/fitting/review", json={"model": "m", "note": "The eyes have collapsed"})
    assert result.status_code == 200
    response = result.json()
    before = response["geometry_retained"]["before"]
    expected = (folder / "before.glb").read_bytes()
    for path in folder.iterdir():
        path.unlink()
    assert store.read_artifact(before) == expected
    feedback = build_feedback.rows(store, GID)
    assert feedback[0]["note"] == "The eyes have collapsed" and feedback[0]["mesh_review"]["prefer_original"] is True
    assert feedback[0]["attachments"] and filed[0]["save_state"] is False
    request = {"tool": "characters", "input": {"op": "use", "game_id": GID}}
    with pytest.raises(HTTPException) as caught:
        build_feedback.check(store, request)
    assert caught.value.status_code == 409
    request["input"]["feedback_ack"] = {response["id"]: 1}
    build_feedback.check(store, request)


@pytest.mark.parametrize("url", ["/api/jobs/other/fitting/files/before.glb", "/api/jobs/fit-job/fitting/files/../before.glb",
                                 "https://example.com/before.glb"])
def test_comparisons_cannot_read_other_jobs_or_unrelated_paths(review, url):
    client, store, folder, job, filed = review
    job["fitting"]["models"]["m"]["comparison"]["before"] = url
    store.put("job", "fit-job", job)
    assert client.get("/api/jobs/fit-job/fitting/review").json()["models"][0]["comparison"] is None


def test_older_or_expired_fits_accept_notes_without_claiming_an_exact_comparison(review):
    client, store, folder, job, filed = review
    (folder / "after.glb").unlink()
    assert client.get("/api/jobs/fit-job/fitting/review").json()["models"][0]["comparison"] is None
    result = client.post("/api/jobs/fit-job/fitting/review", json={"model": "m", "note": "Please retain the face"})
    assert result.status_code == 200 and result.json()["geometry_retained"] == {}
    assert "No exact saved pair remains" in filed[0]["detail"]


@pytest.mark.parametrize("body,expected", [({"model": "missing", "note": "Wrong face"}, 404),
                                         ({"model": "m", "note": "   "}, 422),
                                         ({"model": "m", "note": "Wrong face", "evidence": {"image_b64": "invalid"}}, 422)])
def test_invalid_reports_do_not_file_requests(review, body, expected):
    client, store, folder, job, filed = review
    assert client.post("/api/jobs/fit-job/fitting/review", json=body).status_code == expected
    assert not filed
