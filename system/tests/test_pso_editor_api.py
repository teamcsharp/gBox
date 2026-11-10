"""P6b's page: the editor's web layer, the class labels it shows and the server-rendered preview."""
import struct

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import pso_editor_api as API

REAL_EDIT_ERROR = API.pso_editor.EditError


def client(monkeypatch, rows=None, world=None, ops_ok=True):
    """An app with a fake disc: two placements, one door and one sensor."""
    rows = rows if rows is not None else [
        {"index": 0, "kind": 0x47, "class": "TObjCityDoor_Guild", "family": "door", "x": 10.0, "y": 1.0, "z": -3.0,
         "angle": 0.0},
        {"index": 1, "kind": 0x02, "class": "TOSensor", "family": "sensor", "x": -20.0, "y": 1.0, "z": 40.0,
         "angle": 0.0}]
    monkeypatch.setattr(API, "disc_for", None) if False else None
    monkeypatch.setattr(API, "rom_for", lambda config: __import__("pathlib").Path("disc.iso"))
    monkeypatch.setattr(API.pso_gc, "open_disc", lambda path: object())

    class Editor:
        EditError = REAL_EDIT_ERROR

        @staticmethod
        def sets(disc):
            return [{"name": "map_city00_00o.dat", "kind": "object", "where": "loose"}]

        @staticmethod
        def placements(disc, name):
            if name != "map_city00_00o.dat":
                raise KeyError(name)
            return {"set": name, "where": "loose", "count": len(rows), "records": [dict(r) for r in rows]}

        @staticmethod
        def world_position(row, name):
            return world

        @staticmethod
        def edits(*ops):
            if not ops_ok or not ops:
                raise REAL_EDIT_ERROR("no edits given")
            return list(ops)

        @staticmethod
        def preview(disc, ops):
            return {"ok": True, "files": ["map_city00_00o.dat"], "edits": len(ops), "changes": {}, "expect": {}}

        @staticmethod
        def build(cfg, game_id, rom, name, ops):
            if name == "boom":
                raise RuntimeError("the writer refused this image")
            return {"image": f"/cache/mods/{game_id}/{name}/disc.iso", "edits": list(ops),
                    "verification": {"ok": True, "checked": len(ops)}}

    monkeypatch.setattr(API, "pso_editor", Editor)
    app = FastAPI()
    API.routes(app, type("Cfg", (), {"cache": "."})(), lambda: "agent")
    return TestClient(app)


def test_the_page_is_served(monkeypatch):
    res = client(monkeypatch).get("/pso/editor")
    assert res.status_code == 200 and "PSO placement editor" in res.text
    assert "api/pso/editor/sets" in res.text                    # the page talks to the API


def test_the_sets_and_a_sets_placements_are_labelled(monkeypatch):
    c = client(monkeypatch)
    sets = c.get("/api/pso/editor/sets").json()
    assert sets["count"] == 1 and sets["sets"][0]["name"] == "map_city00_00o.dat"
    data = c.get("/api/pso/editor/set/map_city00_00o.dat").json()
    assert data["count"] == 2
    assert data["records"][0]["class"] == "TObjCityDoor_Guild" and data["records"][0]["family"] == "door"
    assert data["families"] == {"door": 1, "sensor": 1}


def test_the_preview_is_a_real_svg_with_the_markers_and_a_legend(monkeypatch):
    res = client(monkeypatch).get("/api/pso/editor/set/map_city00_00o.dat/svg?width=600")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/html")
    svg = res.text
    assert svg.startswith("<svg") and 'data-set="map_city00_00o.dat"' in svg and 'data-count="2"' in svg
    assert svg.count("<circle") == 2
    assert "TObjCityDoor_Guild" in svg                            # doors are named on the map
    assert "door:1 sensor:1" in svg                               # and the legend counts families


def test_a_family_filter_draws_only_that_family(monkeypatch):
    svg = client(monkeypatch).get("/api/pso/editor/set/map_city00_00o.dat/svg?families=door").text
    assert svg.count("<circle") == 1 and "sensor:1" not in svg


def test_world_positions_show_where_the_offset_is_known(monkeypatch):
    data = client(monkeypatch, world=(238.0, 288.0)).get("/api/pso/editor/set/map_city00_00o.dat").json()
    assert data["records"][0]["world"] == [238.0, 288.0]
    # without an offset the local position is all there is
    data = client(monkeypatch, world=None).get("/api/pso/editor/set/map_city00_00o.dat").json()
    assert data["records"][0]["world"] is None


def test_an_unknown_set_is_a_404_not_a_crash(monkeypatch):
    assert client(monkeypatch).get("/api/pso/editor/set/nope.dat").status_code == 404


def test_preview_refuses_an_empty_edit_set(monkeypatch):
    res = client(monkeypatch, ops_ok=False).post("/api/pso/editor/preview", json={"ops": []})
    assert res.status_code == 400 and "no edits" in res.text


def test_preview_reports_what_would_change(monkeypatch):
    res = client(monkeypatch).post("/api/pso/editor/preview",
                                   json={"ops": [{"op": "move", "set": "map_city00_00o.dat", "index": 1,
                                                  "x": 1.0, "y": 2.0, "z": 3.0}]})
    assert res.status_code == 200 and res.json()["edits"] == 1


# ---- the svg renderer on its own --------------------------------------------------------------------------------------------

def test_the_svg_scales_and_flips_z_so_up_is_up():
    data = {"set": "s", "count": 2, "records": [
        {"index": 0, "kind": 0x47, "class": "TObjCityDoor_Guild", "family": "door", "x": 0.0, "z": 0.0},
        {"index": 1, "kind": 0x02, "class": "TOSensor", "family": "sensor", "x": 100.0, "z": 100.0}]}
    svg = API.svg_of(data, width=400)
    ys = [float(part.split('cy="')[1].split('"')[0]) for part in svg.split("<circle")[1:]]
    assert ys[0] > ys[1]                                          # the higher z draws higher on the page


def test_a_set_with_no_placements_says_so():
    svg = API.svg_of({"set": "empty", "count": 0, "records": []})
    assert "no placements" in svg


def test_build_applies_the_edits_and_reports_the_verification(monkeypatch):
    res = client(monkeypatch).post("/api/pso/editor/build",
                                   json={"name": "pso_t1", "ops": [{"op": "move", "set": "map_city00_00o.dat",
                                                                    "index": 1, "x": 1.0, "y": 2.0, "z": 3.0}]})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["ok"] is True and data["name"] == "pso_t1" and data["image"].endswith("pso_t1/disc.iso")
    assert data["verification"]["ok"] is True and len(data["edits"]) == 1


def test_build_refuses_a_bad_mod_name(monkeypatch):
    res = client(monkeypatch).post("/api/pso/editor/build", json={"name": "Bad Name!", "ops": []})
    assert res.status_code == 400 and "mod name" in res.text


def test_build_refuses_an_empty_edit_set(monkeypatch):
    res = client(monkeypatch).post("/api/pso/editor/build", json={"name": "pso_t1", "ops": []})
    assert res.status_code == 400 and "no edits" in res.text


def test_a_failed_build_is_a_400_with_the_reason(monkeypatch):
    res = client(monkeypatch).post("/api/pso/editor/build",
                                   json={"name": "boom", "ops": [{"op": "move", "set": "map_city00_00o.dat",
                                                                  "index": 1, "x": 1.0, "y": 2.0, "z": 3.0}]})
    assert res.status_code == 400 and "the writer refused" in res.text
