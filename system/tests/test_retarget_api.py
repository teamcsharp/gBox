"""Server side of the Retarget editor and the Fitting pop-up: profile GET/PUT, the stock reference, and fitting
events folded into a job's progress (with uploaded snapshots)."""
import json

import pytest

from gbox import fit_events as FE

GID = "0123456789abcdef"
GAME = {"game_id": GID, "title": "Dead or Alive 2", "platform": "dreamcast", "source_paths": ["doa2.gdi"],
        "format": "gdi", "profile_id": "dc"}
AMY = {"slug": "amy", "name": "Amy Rose", "model": "amy.glb", "kind": "character",
       "source": {"game_id": "fedcba9876543210", "game_title": "Sonic Adventure 2"},
       "rig": {"roles": {"hip": "pelvis", "head": "head"}},
       "targets": {GID: [{"slot": "fighter:KAS:all", "mod": "doa2_kas_amy"}, {"slot": "fighter:RYU:all", "mod": "m2"}]}}
KASUMI = {"slug": "doa2_kasumi", "name": "Kasumi", "model": "kasumi.glb", "kind": "character",
          "source": {"game_id": GID, "game_title": "Dead or Alive 2"}, "rig": {"roles": {"hip": "j00", "head": "j05"}}}
TINA = {"slug": "doa2_tina", "name": "Tina", "model": "tina.glb", "kind": "character",
        "source": {"game_id": GID, "game_title": "Dead or Alive 2"}, "rig": {"roles": {"hip": "j00"}}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    lib = tmp_path / "characters"
    for m in (AMY, KASUMI, TINA):
        (lib / m["slug"]).mkdir(parents=True)
        (lib / m["slug"] / "meta.json").write_text(json.dumps(m))
    monkeypatch.setenv("GBOX_CHARACTERS", str(lib))
    cfg = Config(data_dir=tmp_path / "data")
    app = create_app(cfg)
    app.state.store.upsert_catalog([GAME])
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {cfg.token()}"
        c.lib, c.store = lib, app.state.store
        yield c


def test_profile_put_get_reset_and_rebuild_marking(client):
    r = client.get(f"/api/characters/amy/retarget_profile?game_id={GID}&slot=fighter:KAS").json()
    assert r["profile"] is None and r["resolved"] is None and r["rig_roles"]["hip"] == "pelvis"
    assert "l_fore" in r["roles"] and r["model_url"] == "/api/characters/amy/file/amy.glb"
    put = client.put("/api/characters/amy/retarget_profile",
                     json={"game_id": GID, "slot": "fighter:KAS", "profile": {"head": 1.4, "roles": {"chest": "spine"}}})
    assert put.status_code == 200
    body = put.json()
    assert body["profile"]["head"] == 1.4 and body["resolved"]["roles"] == {"chest": "spine"}
    meta = json.loads((client.lib / "amy" / "meta.json").read_text())
    assert meta["retarget_profiles"][GID]["fighter:kas"]["head"] == 1.4
    flags = {t["slot"]: t.get("needs_rebuild") for t in meta["targets"][GID]}
    assert flags == {"fighter:KAS:all": True, "fighter:RYU:all": None}        # only that slot's mod
    client.post("/api/characters/amy/retarget_profile", json={"game_id": GID, "profile": {"height": 1.1}})
    r = client.get(f"/api/characters/amy/retarget_profile?game_id={GID}&slot=fighter:KAS").json()
    assert r["resolved"]["height"] == 1.0 and r["resolved"]["head"] == 1.4 and r["saved_slots"] == ["*", "fighter:kas"]
    r = client.get(f"/api/characters/amy/retarget_profile?game_id={GID}&slot=fighter:RYU").json()
    assert r["profile"] is None and r["game_wide"]["height"] == 1.1 and r["resolved"]["height"] == 1.1
    meta = json.loads((client.lib / "amy" / "meta.json").read_text())
    assert all(t["needs_rebuild"] for t in meta["targets"][GID])              # game-wide: every slot
    client.post("/api/characters/amy/retarget_profile", json={"game_id": GID, "slot": "fighter:KAS", "reset": True})
    client.post("/api/characters/amy/retarget_profile", json={"game_id": GID, "reset": True})
    assert "retarget_profiles" not in json.loads((client.lib / "amy" / "meta.json").read_text())


def test_profile_put_refuses_bad_input(client):
    bad = client.put("/api/characters/amy/retarget_profile", json={"game_id": GID, "profile": {"roles": {"tail": "x"}}})
    assert bad.status_code == 422 and "tail" in bad.json()["detail"]
    assert client.put("/api/characters/amy/retarget_profile", json={"game_id": "nope", "profile": {}}).status_code == 422
    assert client.put("/api/characters/nobody/retarget_profile", json={"game_id": GID, "profile": {}}).status_code == 404


def test_reference_finds_the_slots_stock_character(client):
    r = client.get(f"/api/retarget/reference?game_id={GID}&slot=fighter:Kasumi").json()
    assert r["reference"]["slug"] == "doa2_kasumi" and r["exact"] is True
    assert r["reference"]["model_url"] == "/api/characters/doa2_kasumi/file/kasumi.glb"
    other = client.get(f"/api/retarget/reference?game_id={GID}&slot=fighter:Zack").json()
    assert other["reference"] and other["exact"] is False                      # some stock model of that game
    none = client.get("/api/retarget/reference?game_id=1111111111111111&slot=x").json()
    assert none["reference"] is None


def test_fitting_events_fold_into_the_job_and_snapshots_upload(client, tmp_path):
    client.store.put("job", "j1", {"id": "j1", "tool": "characters", "state": "running", "input": {"op": "cast_swap"}})
    plan = "Fitting 1 models" + FE.encode({"plan": [{"model": "fighter:KAS", "label": "Amy → Kasumi"}]})
    assert client.post("/api/jobs/j1/progress", json={"pct": 5, "msg": plan}).json()["ok"]
    up = client.post("/api/jobs/j1/fitting/files/fighter_KAS-retarget-0.glb", content=b"glTF-bytes")
    assert up.status_code == 200
    url = up.json()["url"]
    msg = "KAS: Amy → Kasumi: retarget" + FE.encode({"model": "fighter:KAS", "stage": "retarget", "state": "done",
                                                      "data": {"scale": 1.2}, "snapshot": url})
    client.post("/api/jobs/j1/progress", json={"pct": 20, "msg": msg})
    j = client.get("/api/jobs/j1").json()
    assert j["progress"]["msg"] == "KAS: Amy → Kasumi: retarget" and "#fit" not in "".join(j["progress_log"])
    m = j["fitting"]["models"]["fighter:KAS"]
    assert m["label"] == "Amy → Kasumi" and m["stages"]["retarget"]["data"] == {"scale": 1.2}
    assert m["snapshot"] == url and client.get(url).content == b"glTF-bytes"
    assert client.post("/api/jobs/j1/fitting/files/..%2Fx.glb", content=b"x").status_code in (400, 404)
    assert client.post("/api/jobs/j1/fitting/files/a.exe", content=b"x").status_code == 400
    client.store.put("job", "j1", client.store.get("job", "j1") | {"state": "succeeded"})
    assert client.post("/api/jobs/j1/fitting/files/late.glb", content=b"x").status_code == 409


def test_worker_ctx_uploads_a_snapshot_and_rewrites_the_event(tmp_path, monkeypatch):
    from gbox.config import Config
    from gbox.registry import Ctx
    sent = []

    class R:
        status_code = 200

        def __init__(self, url):
            self.url = url

        def json(self):
            return {"url": "/api/jobs/j9/fitting/files/s.glb", "ok": True, "cancel": False}
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.append((url, kw)) or R(url))
    snap = tmp_path / "s.glb"
    snap.write_bytes(b"glb")
    ctx = Ctx(Config(data_dir=tmp_path / "d"), job_id="j9")
    ctx.server = "http://cp"
    ctx.progress(10, "Amy: retarget" + FE.encode({"model": "m", "stage": "retarget", "snapshot": str(snap)}))
    assert sent[0][0] == "http://cp/api/jobs/j9/fitting/files/s.glb" and sent[0][1]["content"] == b"glb"
    _text, ev = FE.split(sent[1][1]["json"]["msg"])
    assert ev["snapshot"] == "/api/jobs/j9/fitting/files/s.glb"


def test_fit_rows_name_their_donor_game_slot_and_the_slots_goals_are_kept(client):
    """The Fitting pop-up's R buttons open the editor on a row's donor / game / slot; the retarget stage's goals (the
    slot's own skeleton as the writer loaded it) are kept per (game, slot) for the editor's Goals view."""
    client.store.put("job", "j2", {"id": "j2", "tool": "characters", "state": "running", "input": {"op": "cast_swap"}})
    plan = "Fitting 1 models" + FE.encode({"plan": [{"model": "fighter:KAS", "label": "Amy → Kasumi", "donor": "amy",
                                                     "slot": "fighter:KAS", "game": GID}]})
    client.post("/api/jobs/j2/progress", json={"pct": 5, "msg": plan})
    goals = {"donor": {"hip": [0, 1, 0], "l_fore": [0.5, 1.45, 0]},
             "target": {"hip": [0, 0.9, 0], "head": [0, 1.6, 0], "l_fore": [0.45, 1.4, 0]}, "target_ground": 0}
    client.post("/api/jobs/j2/progress", json={"pct": 20, "msg": "KAS: retarget" + FE.encode(
        {"model": "fighter:KAS", "stage": "retarget", "state": "done", "goals": goals})})
    m = client.get("/api/jobs/j2").json()["fitting"]["models"]["fighter:KAS"]
    assert (m["donor"], m["game"], m["slot"]) == ("amy", GID, "fighter:KAS")
    assert m["goals"]["target"]["l_fore"] == [0.45, 1.4, 0.0]
    r = client.get(f"/api/retarget/goals?game_id={GID}&slot=fighter:KAS:all").json()
    assert r["goals"]["target"]["head"] == [0.0, 1.6, 0.0] and r["goals"]["donor"]["l_fore"] == [0.5, 1.45, 0.0]
    assert r["goals"]["job"] == "j2" and r["goals"]["donor_slug"] == "amy" and r["goals"]["slot"] == "fighter:KAS"
    assert client.get(f"/api/retarget/goals?game_id={GID}&slot=fighter:RYU").json()["goals"] is None
    assert client.get("/api/retarget/goals?game_id=nope&slot=x").status_code == 422


def test_a_profile_with_joint_moves_saves_clamped(client):
    put = client.put("/api/characters/amy/retarget_profile", json={"game_id": GID, "slot": "fighter:KAS",
                                                                    "profile": {"joints": {"l_fore": [0, -0.9, 0.01]}}})
    assert put.status_code == 200 and put.json()["resolved"]["joints"] == {"l_fore": [0.0, -0.25, 0.01]}
    bad = client.put("/api/characters/amy/retarget_profile", json={"game_id": GID, "profile": {"joints": {"tail": [0, 1, 0]}}})
    assert bad.status_code == 422


def test_the_editors_rebuild_this_slot_recipe_queues_one_slot_and_never_launches(client):
    """retarget-editor.js "Save and rebuild this slot": the job's cast call narrowed to the slot, queued through the
    special-builds rebuild route (gbox/special_builds.py sanitize + queue) as a Spark job."""
    recipe = {"tool": "characters", "input": {"op": "cast_swap", "target_game": GID, "source": "SA2", "mapping": "by_role",
                                              "seed": "s1", "slots": "fighter:KAS",
                                              "assignments": [{"slot": "fighter:KAS", "character": "amy"}],
                                              "launch": False, "rebuild": True}}
    r = client.post(f"/api/games/{GID}/special_builds/rebuild", json={"recipes": [recipe]}).json()
    assert r["queued"] == 1 and r["skipped"] == []
    j = client.store.get("job", r["job_ids"][0])
    assert j["tool"] == "characters" and j["require_os"] == "linux"
    assert {k: j["input"][k] for k in recipe["input"]} == recipe["input"]      # (+ the CharIn defaults)
