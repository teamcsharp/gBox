"""The run reviewer lists every captured Switch round with its run map (gbox.mercs.run_capture) and serves one run's map
with its stage's known extent: operator 2026-10-27 20:28, "a 2D map that is showing the path ... each run that we're
able to look at and review in the run reviewer for the Merc mode"."""
import json
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest

from gbox.mercs import run_capture as RC
from gbox.mercs.notebook import Notebook
from gbox.mercs.reviewer import Reviewer, routes

TITLE = "01002A000CD48000"


class Bot:
    doing, why = "walk", "to the capsule"


def capture(root, rid, stage="Rail Yard", steps=30):
    cap = RC.RunCapture(root / "mercs" / "round_maps", TITLE, rid, threaded=False,
                        provenance={"source_session_id": "worker-session"})
    for k in range(steps):
        cap.observe(1_793_000_000 + k * 0.2, "playing",
                    {"player": {"ptr": 1, "pos": (k * 60.0, 0.0, 0.0), "rot": 0.0, "hp": 900 - (k > 20) * 100,
                                "hp_max": 900},
                     "enemies": [{"slot": 0, "pos": (k * 60.0 + 200, 0.0, 0.0), "hp": 200, "hp_max": 200}],
                     "bonuses": [{"ptr": 5, "pos": (4000.0, 0.0, 3000.0), "kind": "time"}],
                     "timer": 120.0, "score": k, "combo": 1, "kills": 0},
                    Bot(), {"stage": stage, "shots": k})
    return cap.finish(1_793_000_100, "completed")


@pytest.fixture
def reviewer(tmp_path):
    notebook = Notebook(tmp_path / "mercs", TITLE)
    rows = {}
    for rid in ("a" * 32, "b" * 32):
        fields = capture(tmp_path, rid)
        notebook.finish("unknown", "mercenaries", "Chris", "completed", {"score": 1000, "stage": "Rail Yard", **fields},
                        round_id=rid)
        rows[rid] = fields
    notebook.finish("unknown", "mercenaries", "Chris", "died", {"score": 10}, round_id="c" * 32)      # before capture
    app = FastAPI()

    def auth(request: Request):
        if request.headers.get("authorization") != "Bearer fixture":
            raise HTTPException(401, "bad token")
        return "operator"
    routes(app, SimpleNamespace(data_dir=tmp_path), auth)
    client = TestClient(app, headers={"authorization": "Bearer fixture"})
    return SimpleNamespace(root=tmp_path, client=client, rows=rows, notebook=notebook, service=Reviewer(tmp_path))


def test_the_runs_list_says_which_rounds_have_a_run_map(reviewer):
    catalog = reviewer.client.get("/api/mercs/reviewer/catalog").json()
    game = catalog["games"][0]
    assert game["name"] == "Resident Evil 6 (Switch)" and game["visible_runs"] == 3 and game["mapped_runs"] == 2
    runs = {r["round_id"]: r for r in reviewer.client.get("/api/mercs/reviewer/runs",
                                                          params={"title": TITLE, "limit": 20}).json()["runs"]}
    mapped = runs["a" * 32]
    assert mapped["round_map"]["available"] and mapped["round_map"]["file"] == reviewer.rows["a" * 32]["round_map_file"]
    assert mapped["stage"] == "Rail Yard" and mapped["geometry"] == "unknown"   # the label, not the Notebook key
    assert mapped["exploration"]["distance_m"] == 17.4 and mapped["exploration"]["cells"] == 7
    assert runs["c" * 32]["round_map"] == {"available": False} and runs["c" * 32]["exploration"] is None


def test_one_runs_map_comes_with_its_stages_known_extent(reviewer):
    data = reviewer.client.get("/api/mercs/reviewer/round", params={"title": TITLE, "id": "notebook:" + "a" * 32}).json()
    rm = data["round_map"]
    assert rm["format"] == "gbox.run_map/1" and rm["round_id"] == "a" * 32 and rm["session_id"] == "worker-session"
    assert len(rm["route"]) == 30 and rm["doing"][0][1] == "walk" and rm["view"] == {"x": -1, "z": 1}
    assert rm["extent"]["runs"] == 2 and rm["extent"]["source"].startswith("observed")
    assert [16, 12] in rm["extent"]["known"]                                    # the capsule's cell
    assert rm["coverage_now"]["known_cells"] == len(rm["extent"]["known"]) and 0 < rm["coverage_now"]["value"] < 1
    assert data["notebook"]["observed"]["round_map_file"] == rm["file"] and data["samples"] == []
    one = reviewer.client.get("/api/mercs/reviewer/round-map", params={"title": TITLE, "id": "b" * 32}).json()
    assert one["round_map"]["round_id"] == "b" * 32 and one["run"]["id"] == "notebook:" + "b" * 32
    assert reviewer.client.get("/api/mercs/reviewer/round-map",
                               params={"title": TITLE, "id": "c" * 32}).status_code == 404


def test_a_run_map_path_never_leaves_the_round_maps_folder(reviewer, tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"round_id": "d" * 32, "route": []}))
    for rel in ("../secret.json", f"round_maps/{TITLE}/x/../../../secret.json",
                f"round_maps/OTHER/Rail_Yard/20261027-200000-dddddddd.json"):
        reviewer.notebook.finish("unknown", "mercenaries", "Chris", "ended", {"round_map_file": rel}, round_id="d" * 32)
        run = next(r for r in reviewer.service.summaries(TITLE) if r["round_id"] == "d" * 32)
        assert run["round_map"] == {"available": False}, rel
        with reviewer.notebook.connect() as db:
            db.execute("delete from rounds where id=?", ("d" * 32,))


def test_a_pruned_or_foreign_map_leaves_the_round_reviewable(reviewer):
    path = reviewer.root / "mercs" / reviewer.rows["a" * 32]["round_map_file"]
    d = json.loads(path.read_text())
    path.write_text(json.dumps({**d, "round_id": "e" * 32}))                  # someone else's map at this path
    data = reviewer.client.get("/api/mercs/reviewer/round", params={"title": TITLE, "id": "notebook:" + "a" * 32})
    assert data.status_code == 200 and data.json()["round_map"] is None and "does not belong" in data.json()["round_map_error"]
    path.unlink()
    runs = reviewer.client.get("/api/mercs/reviewer/runs", params={"title": TITLE}).json()["runs"]
    assert next(r for r in runs if r["round_id"] == "a" * 32)["round_map"]["available"] is False
