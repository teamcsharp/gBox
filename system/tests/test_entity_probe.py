"""gbox/entity_probe on synthetic big-endian RAM laid out from the 007 Agent Under Fire profile (#1438 stage 1):
entity table, C++ objects with vtables, FAKK-style str model names, a gclient_t camera; projection, picking and
garbage-memory behaviour. Nothing here touches a running game."""
import json
import math
import struct
from pathlib import Path

import pytest

from gbox import entity_probe, semantic

PROFILE = Path(__file__).resolve().parent.parent / "profiles" / "auf-gcn-us.json"
TABLE, OBJECTS, STRINGS, STRDATA, CLIENTS = 0x80400000, 0x80500000, 0x80600000, 0x80610000, 0x80700000


def prof():
    return json.loads(PROFILE.read_text(encoding="utf-8"))


def hx(v):
    return int(v, 16)


class Mem:
    """Sparse big-endian RAM: unknown bytes read as zero (like freshly cleared GameCube memory)."""

    def __init__(self):
        self.m = {}
        self.reads = 0

    def put(self, a, data):
        for i, b in enumerate(data):
            self.m[a + i] = b

    def u32(self, a, v):
        self.put(a, struct.pack(">I", v & 0xFFFFFFFF))

    def f3(self, a, v):
        self.put(a, struct.pack(">3f", *v))

    def read_memory(self, a, n):
        self.reads += 1
        return bytes(self.m.get(a + i, 0) for i in range(n))


def vtable(p, name):
    return next(hx(k) for k, v in p["entities"]["classes"].items() if v["name"] == name)


def build(p, entities, camera, count=None, pm_flags=0, scripted=None):
    """entities: [(class, pos, model, absmin, absmax, extra)] -> Mem with the profile's real addresses."""
    ent, cam = p["entities"], p["camera"]
    mem = Mem()
    mem.put(0x80000000, b"GW7E69")
    mem.u32(hx(ent["base_pointer"]), TABLE)
    mem.u32(hx(ent["base_pointer_alt"]), TABLE)
    mem.u32(hx(ent["count"]), len(entities) if count is None else count)
    stride = hx(ent["stride"])
    f = ent["fields"]
    for i, (cls, pos, model, lo, hi, extra) in enumerate(entities):
        rec = TABLE + i * stride
        obj = OBJECTS + i * 0x1000
        if cls is None:                                   # free slot
            continue
        mem.u32(rec + hx(ent["inuse"][1]), 1)
        mem.u32(rec + hx(f["number"][1]), i)
        if cls == "garbage":
            mem.u32(rec + hx(ent["object"][1]), 0x12345678)
            continue
        mem.u32(rec + hx(ent["object"][1]), obj)
        mem.u32(rec + hx(f["modelindex"][1]), extra.get("modelindex", 10 + i))
        mem.u32(rec + hx(f["svflags"][1]), extra.get("svflags", 0x20))
        mem.f3(rec + hx(f["record_absmin"][1]), lo)
        mem.f3(rec + hx(f["record_absmax"][1]), hi)
        mem.f3(rec + hx(f["record_origin"][1]), pos)
        mem.u32(obj + hx(f["class"][1]), vtable(p, cls) if cls in ("Player", "Bot", "Actor", "World", "Deadbody") else cls)
        name = STRINGS + i * 0x40
        mem.put(name, cls.encode() + b"\0" if isinstance(cls, str) else b"\0")
        mem.u32(obj + hx(f["classname"][1]), name)
        mem.u32(obj + hx(f["entnum"][1]), i)
        mem.u32(obj + hx(f["client"][1]), extra.get("client", 0))
        sd = STRDATA + i * 0x40
        chars = STRINGS + 0x2000 + i * 0x40
        mem.put(chars, model.encode() + b"\0")
        mem.put(sd, struct.pack(">IIII", chars, 1, 32, len(model)))
        mem.u32(obj + hx(f["model"][1]), sd)
        mem.f3(obj + hx(f["mins"][1]), [lo[k] - pos[k] for k in range(3)])
        mem.f3(obj + hx(f["maxs"][1]), [hi[k] - pos[k] for k in range(3)])
        mem.f3(obj + hx(f["position"][1]), pos)
        mem.f3(obj + hx(f["angles"][1]), extra.get("angles", (0, 0, 0)))
    mem.u32(hx(cam["clients_pointer"]), CLIENTS)
    mem.u32(hx(cam["client_stride"]), hx(cam["client_stride_expected"]))
    mem.u32(hx(cam["client_index"]), 0)
    mem.u32(hx(cam["client_count"]), 1)
    eye, angles, fov = camera
    mem.f3(CLIENTS + hx(cam["eye"][1]), eye)
    mem.f3(CLIENTS + hx(cam["angles"][1]), angles)
    mem.put(CLIENTS + hx(cam["fov"][1]), struct.pack(">f", fov))
    mem.u32(CLIENTS + hx(cam["override"]["flags"][1]), pm_flags)
    if scripted:
        e2, a2, f2 = scripted
        mem.f3(CLIENTS + hx(cam["override"]["eye"][1]), e2)
        mem.f3(CLIENTS + hx(cam["override"]["angles"][1]), a2)
        mem.put(CLIENTS + hx(cam["override"]["fov"][1]), struct.pack(">f", f2))
    return mem


# camera at the origin, 64 up, looking along +y (Quake yaw 90), 90 degree vertical fov, 4:3
CAMERA = ((0.0, 0.0, 64.0), (0.0, 90.0, 0.0), 90.0)
SCENE = [
    ("Player", (0.0, 0.0, 0.0), "models/bond.tik", (-16, -16, -24), (16, 16, 48), {"client": CLIENTS}),
    ("Bot", (0.0, 300.0, 40.0), "models/mp_guard.tik", (-16, 284, 16), (16, 316, 88), {}),
    ("Actor", (100.0, 300.0, 40.0), "models/guard_a.tik", (84, 284, 16), (116, 316, 88), {"svflags": 0x40000020}),
    (None, None, None, None, None, {}),                                       # free slot
    ("garbage", (0, 0, 0), "", (0, 0, 0), (0, 0, 0), {}),                    # inuse but a wild object pointer
    ("World", (0.0, 0.0, 0.0), "*1", (-4096, -4096, -4096), (4096, 4096, 4096), {}),
    ("Actor", (0.0, -300.0, 40.0), "models/guard_b.tik", (-16, -316, 16), (16, -284, 88), {"svflags": 0xA0}),
]


def test_profile_is_understood_and_matches_the_game():
    p = prof()
    assert entity_probe.validate_profile(p) == []
    assert p["id"] == "auf-gcn-us" and p["game_id"] == "65b7187589166b26"
    assert next(x for x in semantic.load_profiles() if x["id"] == "auf-gcn-us")
    mem = build(p, SCENE, CAMERA)
    game = {"platform": "gamecube", "title": "007 - Agent Under Fire (USA)"}
    assert semantic.match(game, mem.read_memory)["id"] == "auf-gcn-us"
    assert semantic.match({"platform": "gamecube", "title": "Soul Calibur II"}, mem.read_memory) is None
    classes = p["entities"]["classes"]
    for name, vt in (("Player", 0x80254E70), ("Bot", 0x80287BB4), ("Actor", 0x802612C0), ("Entity", 0x80249C70)):
        assert classes[f"0x{vt:08X}"]["name"] == name
    assert classes["0x80287BB4"]["super"] == "DeathmatchPlayer" and classes["0x80287BB4"]["size"] == 3216
    assert p["provenance"]["executable"]["sha256"].startswith("1a9c0d19")


def test_entities_parse_with_class_kind_model_and_position():
    p = prof()
    mem = build(p, SCENE, CAMERA)
    pr = entity_probe.Probe(p, mem.read_memory)
    ents = pr.entities()
    by = {e["index"]: e for e in ents}
    assert sorted(by) == [0, 1, 2, 5, 6]                            # free slot and wild pointer skipped
    assert [by[i]["class"] for i in (0, 1, 2, 5)] == ["Player", "Bot", "Actor", "World"]
    assert [by[i]["kind"] for i in (0, 1, 2, 5)] == ["player", "bot", "npc", "world"]
    assert by[1]["model"] == "models/mp_guard.tik" and by[0]["model"] == "models/bond.tik"
    assert (by[1]["x"], by[1]["y"], by[1]["z"]) == (0.0, 300.0, 40.0)
    assert by[1]["modelindex"] == 11 and by[1]["classname"] == "Bot" and by[1]["entnum"] == 1
    assert by[1]["box"] == [[-16.0, 284.0, 16.0], [16.0, 316.0, 88.0]]
    assert by[1]["mins"] == [-16.0, -16.0, -24.0] and by[1]["class_size"] == 3216
    assert by[2]["rendered"] is True and by[2]["hidden"] is False
    assert by[6]["hidden"] is True and by[6]["rendered"] is False
    assert any("0x12345678" in d for d in pr.diagnostics)


def test_camera_projection_conventions():
    cam = entity_probe.Camera((0, 0, 64), (0, 90, 0), 90, "vertical", 4 / 3)
    assert [round(v, 6) for v in cam.forward] == [0, 1, 0]
    sx, sy, depth = cam.project((0, 300, 64))                        # straight ahead: picture centre
    assert (round(sx, 6), round(sy, 6), depth) == (0.5, 0.5, 300.0)
    sx, sy, _ = cam.project((100, 300, 64))                           # to the right of the view: right of centre
    assert sx == pytest.approx(0.625) and sy == pytest.approx(0.5)
    sx, sy, _ = cam.project((0, 300, 164))                            # above: up the picture
    assert sx == pytest.approx(0.5) and sy == pytest.approx(0.5 - 0.5 / 3)
    assert cam.project((0, -300, 64)) is None                         # behind the camera
    down = entity_probe.Camera((0, 0, 64), (90, 90, 0), 90)           # Quake pitch 90 = looking straight down
    assert [round(v, 6) for v in down.forward] == [0, 0, -1]
    horizontal = entity_probe.Camera((0, 0, 64), (0, 90, 0), 90, "horizontal", 4 / 3)
    sx, sy, _ = horizontal.project((100, 300, 64))
    assert sx == pytest.approx(0.5 + 0.5 / 3)


def test_scan_projects_boxes_and_under_point_names_the_bot():
    p = prof()
    mem = build(p, SCENE, CAMERA)
    pr = entity_probe.Probe(p, mem.read_memory)
    scan = pr.scan(640, 480)
    assert scan["camera"]["source"] == "view" and scan["camera"]["fov"] == 90.0
    by = {e["index"]: e for e in scan["entities"]}
    assert by[0]["is_viewer"] is True and by[1]["is_viewer"] is False
    assert by[1]["screen"] == [320.0, 259.2]                        # 24 units below eye height, 300 away: below centre
    x0, y0, x1, y1 = by[1]["screen_box"]
    assert x0 < 320 < x1 and y0 < 259 < y1 and by[1]["depth"] == 284.0
    assert by[2]["screen"][0] > 380 and by[6].get("behind_camera") is True
    hit = entity_probe.Probe.under_point(320, 230, scan)
    assert hit["entity"]["class"] == "Bot" and hit["contained"] is True
    hit = entity_probe.Probe.under_point(by[2]["screen"][0], by[2]["screen"][1], scan)
    assert hit["entity"]["class"] == "Actor" and hit["entity"]["index"] == 2
    assert entity_probe.Probe.under_point(5, 5, scan)["entity"] is None          # sky: nothing (world excluded)
    near = entity_probe.Probe.under_point(x1 + 10, 230, scan)                     # just outside the box
    assert near["entity"]["class"] == "Bot" and near["contained"] is False and 0 < near["miss"] <= 12
    assert entity_probe.under_point(p, mem.read_memory, 320, 230)["entity"]["kind"] == "bot"
    assert entity_probe.summary(by[1])["model"] == "models/mp_guard.tik"


def test_scripted_camera_override_and_viewer_inclusion():
    p = prof()
    # cutscene camera 300 units east of the player looking west (yaw 180), 60 degree fov: only the player is on screen
    mem = build(p, SCENE, CAMERA, pm_flags=0x100, scripted=((300, 0, 64), (0, 180, 0), 60))
    scan = entity_probe.Probe(p, mem.read_memory).scan()
    assert scan["camera"]["source"] == "scripted" and scan["camera"]["fov"] == 60.0
    by = {e["index"]: e for e in scan["entities"]}
    assert by[0]["screen"] == [320.0, pytest.approx(328.7, abs=0.1)] and by[0]["depth"] == pytest.approx(284.0)
    assert by[1]["screen"][0] > 640 and by[6]["screen"][0] < 0                     # bot right of, guard left of the picture
    assert entity_probe.Probe.under_point(*by[0]["screen"], scan)["entity"] is None   # the viewer is never picked...
    assert entity_probe.Probe.under_point(*by[0]["screen"], scan, include_viewer=True)["entity"]["class"] == "Player"
    mem = build(p, SCENE, CAMERA, pm_flags=0x200, scripted=((300, 0, 64), (0, 180, 0), 60))   # other pm_flags bit: no
    assert entity_probe.Probe(p, mem.read_memory).scan()["camera"]["source"] == "view"


def test_garbage_memory_never_raises():
    p = prof()
    empty = Mem()                                                     # all zeros: no table pointer
    pr = entity_probe.Probe(p, empty.read_memory)
    assert pr.scan() == {"entities": [], "camera": None, "frame": [640, 480], "diagnostics": pr.diagnostics}
    assert any("outside pointer_range" in d for d in pr.diagnostics)
    mem = build(p, SCENE, CAMERA, count=10 ** 6)                      # absurd count: capped, no exception
    pr = entity_probe.Probe(p, mem.read_memory, max_entities=8)
    assert len(pr.entities()) == 5 and any("capped" in d for d in pr.diagnostics)
    assert mem.reads < 200

    def flaky(a, n):                                                  # reads that fail or come back short
        if a == OBJECTS + 0x1000:
            raise OSError("emulator went away")
        if a == OBJECTS + 0x2000:
            return b"\0" * 3
        return mem.read_memory(a, n)
    pr = entity_probe.Probe(p, flaky)
    idx = sorted(e["index"] for e in pr.entities())
    assert idx == [0, 5, 6] and any("OSError" in d for d in pr.diagnostics) and any("short read" in d for d in pr.diagnostics)
    nan = build(p, SCENE, CAMERA)
    nan.put(OBJECTS + 0x1000 + hx(p["entities"]["fields"]["position"][1]), b"\x7f\xc0\x00\x00" * 3)
    pr = entity_probe.Probe(p, nan.read_memory)
    assert 1 not in [e["index"] for e in pr.entities()] and any("no finite position" in d for d in pr.diagnostics)
    bad_cam = build(p, SCENE, CAMERA)
    bad_cam.put(CLIENTS + hx(p["camera"]["fov"][1]), struct.pack(">f", 0.0))
    pr = entity_probe.Probe(p, bad_cam.read_memory)
    assert pr.camera() is None and pr.scan()["camera"] is None
    bad_str = build(p, SCENE, CAMERA)
    bad_str.put(STRINGS + 0x2000 + 0x40, bytes(range(1, 40)))         # binary where the bot's model name was
    assert {e["index"]: e["model"] for e in entity_probe.Probe(p, bad_str.read_memory).entities()}[1] is None


def test_semantic_extractor_and_pick_helpers_use_the_probe():
    p = prof()
    mem = build(p, SCENE, CAMERA)
    st = semantic.Extractor(p, mem.read_memory).state()
    assert st["profile"] == "auf-gcn-us" and st["player"]["class"] == "Player" and st["verified"], st["checks"]
    assert [e["kind"] for e in st["entities"]] == ["player", "bot", "npc", "world", "npc"]
    assert st["globals"]["num_entities"] == len(SCENE) and st["globals"]["current_player"] == 0
    assert "diagnostics" in st                                          # the wild pointer is reported, not raised
    from gbox import tools
    reads = mem.reads
    scan = entity_probe.Probe(p, mem.read_memory).scan(*tools.PICK_FRAME, entities=st["entities"])
    assert mem.reads - reads < 10                                        # pick reuses what the Extractor read
    out = tools._pick_from_probe(scan, 0.5, 230 / 480)
    assert out["picked"]["class"] == "Bot" and out["picked"]["kind"] == "bot" and out["contained"]
    assert out["click_px"] == [320.0, 230.0] and out["entities"] == 5 and "mp_guard" in out["asset_note"]
    assert tools._picture_xy(tools.PickIn(session_id="s", x=0.5, y=0.5, window_aspect=16 / 9)) == (0.5, 0.5)
    cx, _ = tools._picture_xy(tools.PickIn(session_id="s", x=0.125, y=0.5, window_aspect=16 / 9))
    assert cx == pytest.approx(0.0)                                      # left edge of the centred 4:3 picture


def test_validate_profile_reports_unknown_fields():
    p = prof()
    p["entities"]["fields"]["weird"] = ["q64", "0x10"]
    p["entities"]["flags"].append({"name": "x", "field": "nope", "mask": "0x1"})
    p["camera"]["fov_axis"] = "diagonal"
    problems = entity_probe.validate_profile(p)
    assert any("unknown type q64" in x for x in problems)
    assert any("flags: bad rule" in x for x in problems)
    assert any("fov_axis" in x for x in problems)



def test_under_point_collapses_cloneplayer_twin_onto_its_bot():
    from gbox.entity_probe import Probe
    bot = {"index": 2, "class": "Bot", "kind": "bot", "model": "models/mp_player_bloch.men",
           "x": 332.858, "y": -683.912, "z": 0.125, "screen_box": [300, 100, 380, 300], "depth": 400.0}
    clone = dict(bot, index=114, **{"class": "ClonePlayer", "kind": "player", "screen_box": [310, 110, 370, 290], "depth": 399.0})
    viewer = {"index": 0, "class": "DeathmatchPlayer", "kind": "player", "model": "models/mp_player_bondtux.men",
              "x": 40.0, "y": -340.0, "z": 0.125, "is_viewer": True, "screen_box": None}
    viewer_clone = dict(viewer, index=108, is_viewer=False, **{"class": "ClonePlayer", "screen_box": [0, 0, 640, 480], "depth": 1.0})
    scan = {"frame": [640, 480], "entities": [viewer, bot, viewer_clone, clone]}
    hit = Probe.under_point(340, 200, scan)
    assert hit["entity"]["index"] == 2 and hit["contained"]
    assert all(o["class"] != "ClonePlayer" for o in hit["others"])
    lone = dict(clone, index=200, x=999.0)          # a ClonePlayer with no owner stays pickable
    assert Probe.under_point(340, 200, {"frame": [640, 480], "entities": [lone]})["entity"]["index"] == 200
