"""Enemy types on the live map, the run maps and the reviewer, with portraits captured from the game (operator
2026-10-29: "be able to associate the foes and show them in the merc live map and run reviewer with profile pictures
as a legend representing what enemies are being represented on the map")."""
import io
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from gbox import tactical_map as TM
from gbox.mercs import enemy_kinds as K
from gbox.mercs import run_capture as RC
from gbox.mercs import tactical as T

RE5, RE6 = "010018100CD46000", "01002A000CD48000"


def jpeg(w=960, h=540, color=(200, 40, 40)):
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, "JPEG")
    return out.getvalue()


def test_names_are_only_the_verified_ones_and_threat_follows_health():
    assert K.name(RE5, "uEm10") == "Majini" and K.name(RE6, "uEm1000") == "J'avo"
    assert K.name(RE5, "uEm99") == "uEm99"                         # not confirmed: its class name
    assert K.name(RE5, None) == "unknown"
    assert [K.threat(h) for h in (1, 800, 1500, 4000, None)] == ["none", "low", "medium", "high", None]
    assert K.valid_class("uEm5200") and not K.valid_class("../x") and not K.valid_class("")


def snap(enemies):
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": 0.0, "hp": 1000, "hp_max": 1000}, "enemies": enemies}


def test_frames_carry_each_enemys_type_threat_and_the_legend_counts():
    tr = T.Tracker(RE5)
    f = tr.frame(snap([{"slot": 0, "ptr": 0x10, "pos": (100.0, 0.0, 0.0), "hp": 700, "hp_max": 700, "class": "uEm10"},
                       {"slot": 1, "ptr": 0x20, "pos": (300.0, 0.0, 0.0), "hp": 700, "hp_max": 700, "class": "uEm10"},
                       {"slot": 2, "ptr": 0x30, "pos": (900.0, 0.0, 0.0), "hp": 4000, "hp_max": 4000, "class": "uEm23"}]),
                 {}, "playing", now=1.0)
    rows = {r["id"]: r for r in f["enemies"]}
    assert rows[0]["cls"] == "uEm10" and rows[0]["kind"] == "Majini" and rows[0]["threat"] == "low"
    assert rows[2]["kind"] == "uEm23" and rows[2]["threat"] == "high"
    assert f["kinds"] == {"uEm10": {"name": "Majini", "count": 2, "threat": "low"},
                          "uEm23": {"name": "uEm23", "count": 1, "threat": "high"}}
    assert "portrait" not in f                                      # no aim: no portrait moment


def test_the_laser_on_one_nearby_is_a_portrait_moment():
    tr = T.Tracker(RE6)
    bot = SimpleNamespace(_aimctx={"target": 0x20, "where": "chest", "dist": 420.0}, plan=lambda: {})
    f = tr.frame(snap([{"slot": 1, "ptr": 0x20, "pos": (420.0, 0.0, 0.0), "hp": 500, "hp_max": 500,
                        "class": "uEm5200"}]), T.take_plan(bot), "playing", now=1.0)
    assert f["portrait"] == {"class": "uEm5200", "dist": 420}
    for ctx in ({"target": 0x20, "where": None, "dist": 420.0},       # the dot not on him
                {"target": 0x20, "where": "head", "dist": 2000.0}):   # a speck
        bot._aimctx = ctx
        f = tr.frame(snap([{"slot": 1, "ptr": 0x20, "pos": (420.0, 0.0, 0.0), "hp": 500, "hp_max": 500,
                            "class": "uEm5200"}]), T.take_plan(bot), "playing", now=2.0)
        assert "portrait" not in f


def test_a_portrait_is_cropped_kept_and_replaced_only_by_a_better_one(tmp_path):
    clock = [100.0]
    P = TM.Portraits(tmp_path, clock=lambda: clock[0])
    assert P.offer(RE5, {"class": "uEm10", "dist": 800}, jpeg())
    with Image.open(tmp_path / RE5 / "uEm10.jpg") as pic:
        assert pic.size == (TM.PORTRAIT_PX, TM.PORTRAIT_PX)
    assert P.index(RE5)["uEm10"]["name"] == "Majini"
    clock[0] += 1
    assert not P.offer(RE5, {"class": "uEm10", "dist": 350}, jpeg())   # too soon
    clock[0] += TM.PORTRAIT_EVERY_S
    assert not P.offer(RE5, {"class": "uEm10", "dist": 900}, jpeg())   # no nearer the best distance
    assert P.offer(RE5, {"class": "uEm10", "dist": 360}, jpeg())       # nearer: replaces it
    assert P.index(RE5)["uEm10"]["dist"] == 360
    assert not P.offer("../x", {"class": "uEm10", "dist": 360}, jpeg()) and not P.offer(RE5, {"class": "../e", "dist": 360}, jpeg())


def test_the_frame_route_crops_the_sessions_picture_and_serves_it(tmp_path):
    app = FastAPI()
    pictures = {"s1": jpeg()}
    TM.install(app, lambda: "agent", frame_of=pictures.get, portraits_root=tmp_path)
    c = TestClient(app)
    frame = {"v": TM.FORMAT, "title": RE6, "portrait": {"class": "uEm1000", "dist": 400}}
    assert c.post("/api/autoplay/tactical/s1", json=frame).status_code == 200
    import time
    for _ in range(50):                                             # the crop runs on its own thread
        if (tmp_path / RE6 / "uEm1000.jpg").is_file():
            break
        time.sleep(0.05)
    assert c.get(f"/api/mercs/portraits/{RE6}").json()["portraits"]["uEm1000"]["name"] == "J'avo"
    r = c.get(f"/api/mercs/portraits/{RE6}/uEm1000.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert c.get(f"/api/mercs/portraits/{RE6}/uEm5200.jpg").status_code == 404


def test_run_maps_keep_each_enemys_type_as_an_index(tmp_path):
    cap = RC.RunCapture(tmp_path, RE5, "r1")
    a = {"class": "uEm10"}
    assert cap._kind(a) == [0] and cap._kind({"class": "uEm23"}) == [1] and cap._kind(a) == [0]
    assert cap._kind({"class": None}) == [] and cap.kinds == ["uEm10", "uEm23"]
