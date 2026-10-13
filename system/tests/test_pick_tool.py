"""pick_identify / pick_replace / pick_ghidra with fake sessions and synthetic RAM (no game files, no emulator)."""
import gzip
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import char_coverage, fit_events as FE, live_inject as LI, pick_tool as PT, semantic, tools

DC = 0x8C000000
ENT = 0x8C400000
ROOT = 0x8C500000
GAME = {"game_id": "daba7a3b195dcf6b", "title": "Phantasy Star Online Ver. 2", "platform": "dreamcast"}
PROFILE = {"id": "pso_test", "title": "PSO test", "endian": "little",
           "camera": {"eye": "0x8C001000", "target": "0x8C00100C", "fov": 45},
           "entities": {"table": "0x8C477D40", "struct_size": "0x340"},
           "models": {"TObjEneBm5Wolf": ["PSO/BM_ENE_BM5_WOLF_A.BML", "bm5_s_kem_body.nj"]}, "evidence": {}}
SLOTS = [{"slot": "enemy:boomas", "name": "Booma, Gobooma and Gigobooma", "aggregate": True},
         {"slot": "enemy:wolf", "name": "Savage Wolf", "file": "PSO/BM_ENE_BM5_WOLF_A.BML", "entry": "bm5_s_kem_body.nj"}]


class Emu:
    name = "fake"

    def __init__(self, data, base=DC, state="RUNNING"):
        self.mem, self.base, self.state = bytearray(data), base, state

    def read_memory(self, a, n):
        return bytes(self.mem[a - self.base:a - self.base + n])

    def write_memory(self, a, d):
        self.mem[a - self.base:a - self.base + len(d)] = d
        return {"written": len(d)}

    def query_runtime(self):
        return {"state": self.state}

    def pause(self):
        self.state = "PAUSED"
        return {"state": "PAUSED"}

    def resume(self):
        self.state = "RUNNING"
        return {"state": "RUNNING"}


def ninja_root(buf, at, n=3):
    nodes = [at + 0x34 * i for i in range(n)]
    for i, a in enumerate(nodes):
        m = at + 0x34 * n + 0x40 * i
        struct.pack_into("<II3f3i3fII", buf, a - DC, 0x0C, m, 0, 5.0 * i, 0, 0, 0, 0, 1, 1, 1,
                         nodes[i + 1] if i + 1 < n else 0, 0)
        struct.pack_into("<II4f", buf, m - DC, m + 0x18, 0, 0, 1, 0, 3)
        struct.pack_into("<I", buf, m + 0x18 - DC, (6 << 16) | 0x29)


def pattern(n, seed=1):
    return bytes((i * 7 + seed * 13 + (i >> 5)) & 0xFF for i in range(n))


@pytest.fixture
def world(monkeypatch, tmp_path):
    buf = bytearray(0x1000000)
    struct.pack_into("<3f3f", buf, 0x1000, 0, 0, 0, 0, 0, 1)
    ninja_root(buf, ROOT)
    struct.pack_into("<I", buf, ENT - DC, 0x8C2F3014)       # class name pointer
    struct.pack_into("<I", buf, ENT - DC + 0x34, ROOT)       # the model pointer
    asset_at = DC + 0x600000                                 # a loaded model file image (live injection target)
    orig = pattern(0x800)
    buf[asset_at - DC:asset_at - DC + len(orig)] = orig
    emu = Emu(buf)
    tools.SESSIONS["s1"] = (emu, dict(GAME))
    monkeypatch.setattr(tools, "_semantic_state", lambda ad, g, player_only=False: {
        "profile": "pso_test", "entities": [{"class": "TObjEneBm5Wolf", "kind": "enemy", "entity_id": 3,
                                              "ptr": hex(ENT), "x": 0.0, "y": 0.0, "z": 30.0, "room": 1}]})
    monkeypatch.setattr(semantic, "load_profiles", lambda: [PROFILE])
    monkeypatch.setattr(tools, "project_point", lambda eye, tgt, p, fov: (0.5, 0.5))
    monkeypatch.setattr(char_coverage, "cast_slots", lambda game: SLOTS)
    monkeypatch.setattr(char_coverage, "writer_for", lambda game: {"writer": "gbox.pso_player", "routed": True,
                                                                  "slots": [], "replaces": "PSO enemies"})
    monkeypatch.setattr(PT, "JOB_POLL_S", 0)
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path / "data", runtime=tmp_path / "rt", cache=tmp_path),
                          server=None, headers={}, job_id="job1", log=[], progress=lambda p, m: None)
    yield SimpleNamespace(emu=emu, ctx=ctx, orig=orig, asset_at=asset_at, tmp=tmp_path)
    tools.SESSIONS.pop("s1", None)
    tools.SESSIONS.pop("s2", None)


def test_identify_maps_the_point_to_entity_slot_and_model_in_ram_then_learns_it(world):
    inp = PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5)
    out = PT.pick_identify(inp, world.ctx)
    assert out["entity"]["class"] == "TObjEneBm5Wolf" and out["game_id"] == GAME["game_id"]
    assert out["slot"] == "enemy:wolf"
    assert out["ram"]["entity_struct"] == "0x8C400000" and out["ram"]["model"] == "0x8C500000"
    assert out["ram"]["model_detail"]["nodes"] == 3
    assert out["replaceable"]["live"] and out["replaceable"]["build"]
    assert {"entity", "pointer walk", "slot"} <= {e["step"] for e in out["evidence"] if e["ok"]}
    assert out["confidence"] >= 0.75
    assert world.emu.state == "RUNNING"                      # paused for the snapshot, resumed
    learned = json.loads((world.tmp / "data" / "pick_learned" / f"{GAME['game_id']}.json").read_text())
    rule = learned["classes"]["TObjEneBm5Wolf"]
    assert rule["slot"] == "enemy:wolf" and rule["model_ptr"] == {"path": ["0x00000034"], "kind": "ninja_object"}
    again = PT.pick_identify(inp, world.ctx)                # the next pick takes the learned path
    assert any(e["step"] == "learned model" and e["ok"] for e in again["evidence"])
    assert again["ram"]["model"] == "0x8C500000"
    assert any(e["step"] == "ghidra" for e in again["evidence"])   # roots known, no control plane here


def test_identify_oot_actor_is_live_replaceable_on_ntsc_1_2(monkeypatch, world):
    from gbox import oot, oot_live
    game = {"game_id": "ootid", "title": "Legend of Zelda, The - Ocarina of Time (USA) (Rev 2)", "platform": "n64"}
    tools.SESSIONS["s2"] = (world.emu, game)
    actor = {"addr": 0x801E0000, "id": 0x146, "name": "En_Sa", "category": "npc", "pos": np.array([1.0, 2.0, 3.0]),
             "focus": np.array([1.0, 40.0, 3.0]), "object": 0xB6, "object_name": "object_sa", "object_segment": 0x80300000,
             "drawn": True, "distance": 0.01, "screen": [0.5, 0.6, 0.5, 0.4]}
    monkeypatch.setattr(oot_live, "pick", lambda ad, x, y: actor)
    monkeypatch.setattr(oot_live, "skel_anime", lambda ad, a: {"at": 0x801E0140, "limbs": 16, "skeleton": 0x06001234,
                                                                "joint_table": 0x801E0400, "frame": [], "dlcount": 16})
    monkeypatch.setattr(oot, "layout", lambda ad: {"version": "ntsc-1.2"})
    out = PT.pick_identify(PT.PickIdentifyIn(session_id="s2", x=0.5, y=0.5, deep=False), world.ctx)
    assert out["backend"] == "oot" and out["slot"] == "En_Sa"
    assert out["ram"]["skeleton"] == "0x80301234" and out["ram"]["model"] == "0x80300000"
    assert out["replaceable"]["live"] and "oot_hot_swap" in out["replaceable"]["live_reason"]


def glb_with_texture(path, rgba, w, h, extras):
    import io
    from PIL import Image
    png = io.BytesIO()
    Image.frombytes("RGBA", (w, h), bytes(rgba)).save(png, "PNG")
    png = png.getvalue()
    gl = {"asset": {"version": "2.0"}, "nodes": [{"mesh": 0, "extras": extras}],
          "meshes": [{"primitives": [{"attributes": {}, "material": 0}]}],
          "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
          "textures": [{"source": 0}], "images": [{"bufferView": 0, "mimeType": "image/png", "name": "tex0"}],
          "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
          "buffers": [{"byteLength": len(png)}]}
    js = json.dumps(gl).encode()
    js += b" " * ((-len(js)) % 4)
    binc = png + bytes((-len(png)) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binc), b"BIN\0") + binc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)


def test_capture_draw_layer_finds_the_texture_in_ram_and_matches_the_draw(monkeypatch, world):
    from gbox import characters, pick_ram, scene_capture
    w = h = 8
    rgba = bytearray()
    for y in range(h):
        for x in range(w):
            rgba += bytes((x * 32, y * 32, (x ^ y) * 16 & 0xF8, 255))
    enc = dict(pick_ram.tex_encodings(bytes(rgba), w, h))["gx_rgb5a3"]
    world.emu.mem[0x900000:0x900000 + len(enc)] = enc        # the texture as the console stores it
    va = DC + 0x910000
    for i in range(8):
        struct.pack_into("<3f", world.emu.mem, va - DC + 12 * i, i * 1.0, (i % 3) * 2.0, 1.0 + i)
    struct.pack_into("<I", world.emu.mem, va - DC + 96, 0x7FC00000)   # NaN ends the run
    struct.pack_into("<I", world.emu.mem, ENT - DC + 0x40, va)
    out_dir = world.tmp / "rt" / "pick_capture" / "s1"
    glb_with_texture(out_dir / "scene.glb", rgba, w, h, {"draw": 7, "eid": 70, "vertices": 8, "triangles": 6})
    monkeypatch.setattr(PT, "HOST_OS", "windows")
    monkeypatch.setattr(scene_capture, "capture_session", lambda ad, out, *a: ad.pause() and {"resume_on_leave": True})
    monkeypatch.setattr(characters, "cut_scene", lambda p, x, y: {"nodes": [0], "seed": 0, "depth": 3.0, "size": [1, 2, 1],
                                                                   "hits": [{"draw": 0}]})
    out = PT.pick_identify(PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5, capture=True), world.ctx)
    assert out["draws"][0]["draw"] == 7
    assert out["ram"]["textures"][0] == {"texture": "tex0", "addr": "0x8C900000", "format": "gx_rgb5a3"}
    assert out["ram"]["draw_matches"] == [{"draw": 7, "ram": "0x8C910000", "by": "8 vertices"}]
    assert world.emu.state == "RUNNING"                      # the capture's pause was released after the snapshot


def run_with_fitting(fn):
    events = []

    def progress(p, m):
        text, ev = FE.split(m)
        if ev:
            events.append(ev)
    with FE.job(progress):
        res = fn(progress)
    return res, events


def test_replace_live_writes_the_writers_image_into_ram_with_fit_events(monkeypatch, world):
    new = bytearray(world.orig)
    new[0x200:0x240] = b"\x5A" * 0x40
    blob = LI.pack([LI.asset("PSO/BM_ENE_BM5_WOLF_A.BML:bm5_s_kem_body.nj", world.orig, bytes(new))], {"mod": "pso_x"})
    monkeypatch.setattr(PT, "_character", lambda ctx, q: {"slug": "hucast", "name": "HUcast"})
    monkeypatch.setattr(PT, "get_prepared", lambda *a, **k: {"mod": "pso_x", "patch_blob": blob,
                                                            "signatures": LI.signatures(LI.unpack(blob)[0])})
    pick = PT.pick_identify(PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5), world.ctx)

    def go(progress):
        world.ctx.progress = progress
        return PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick=pick, character="hucast"), world.ctx)["result"]
    res, events = run_with_fitting(go)
    assert res["status"] == "live" and res["mode_used"] == "live"
    assert bytes(world.emu.mem[world.asset_at - DC + 0x200:world.asset_at - DC + 0x240]) == b"\x5A" * 0x40
    assert res["live"]["apply"]["verified"] and world.emu.state == "RUNNING"
    assert any(e.get("plan") for e in events)
    writes = [e for e in events if e.get("stage") == "write"]
    assert writes[-1]["state"] == "done" and writes[-1]["model"] == "enemy:wolf"
    learned = json.loads((world.tmp / "data" / "pick_learned" / f"{GAME['game_id']}.json").read_text())
    assert learned["replace"]["enemy:wolf"]["live_ok"] is True and learned["assets"]["enemy:wolf"]["signatures"]
    again = PT.pick_identify(PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5), world.ctx)
    assert any(e["step"] == "model image" for e in again["evidence"])   # learned signatures are searched


def test_replace_live_falls_back_to_build_swap_and_refreshes_the_new_sessions_ram(monkeypatch, world):
    other = pattern(0x800, 9)                               # not in RAM: live can't place it
    new = bytearray(other)
    new[0x10:0x20] = b"\x33" * 16
    blob = LI.pack([LI.asset("X.BIN", other, bytes(new))], {"mod": "pso_x"})
    monkeypatch.setattr(PT, "_character", lambda ctx, q: {"slug": "hucast", "name": "HUcast"})
    monkeypatch.setattr(PT, "get_prepared", lambda *a, **k: {"mod": "pso_x", "patch_blob": blob})
    buf2 = bytearray(0x1000000)
    buf2[0x700000:0x700000 + len(other)] = other            # the swapped session (state restored) holds the old model
    emu2 = Emu(buf2)
    tools.SESSIONS["s2"] = (emu2, dict(GAME))
    calls = []

    def api(ctx, method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions/s1/swap":
            return {"id": "sw1", "state": "running"}
        if path == "/api/jobs/sw1":
            return {"id": "sw1", "state": "succeeded", "output": {"session_id": "s2", "state_loaded": True}}
        raise AssertionError(path)
    monkeypatch.setattr(PT, "_api", api)
    monkeypatch.setattr(PT.time, "sleep", lambda s: None)
    pick = {"game_id": GAME["game_id"], "slot": "enemy:wolf", "backend": "profile",
            "replaceable": {"live": True, "build": True}, "ram": {}}
    res = PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick=pick, character="hucast"), world.ctx)["result"]
    assert res["status"] == "swapped" and res["fell_back"] and "not in RAM" in res["fallback_reason"]
    assert ("POST", "/api/sessions/s1/swap", {"mod": "pso_x", "keep_state": True}) in calls
    assert res["session_id"] == "s2" and res["build"]["ram_refresh"]["ok"]
    assert bytes(emu2.mem[0x700010:0x700020]) == b"\x33" * 16
    learned = json.loads((world.tmp / "data" / "pick_learned" / f"{GAME['game_id']}.json").read_text())
    assert learned["replace"]["enemy:wolf"]["live_ok"] is False


def test_a_frozen_picture_after_the_write_restores_ram(monkeypatch, world):
    from gbox import live_link
    new = bytearray(world.orig)
    new[0x40:0x50] = b"\xEE" * 16
    world.emu.get_frame = lambda: b"png"
    monkeypatch.setattr(live_link, "_frames", lambda ad, ctx: {"ok": False, "animating": False, "luma": 0})
    monkeypatch.setattr(PT.time, "sleep", lambda s: None)
    r = PT.inject(world.emu, GAME, [LI.asset("M", world.orig, bytes(new))], None, [], world.ctx)
    assert not r["ok"] and r["apply"]["reverted"]["restored"] and "frame check" in r["reason"]
    assert bytes(world.emu.mem[world.asset_at - DC:world.asset_at - DC + 0x800]) == world.orig
    assert world.emu.state == "RUNNING"
    world.emu.state = "PAUSED"                              # the operator paused: no frame check, stays paused
    r = PT.inject(world.emu, GAME, [LI.asset("M", world.orig, bytes(new))], None, [], world.ctx)
    assert r["ok"] and world.emu.state == "PAUSED" and "frame_check" not in r["apply"]


def test_replace_without_a_slot_or_with_live_and_no_fallback(monkeypatch, world):
    out = PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick={"game_id": GAME["game_id"], "slot": None},
                                           character="hucast"), world.ctx)["result"]
    assert out["status"] == "not_replaceable"
    monkeypatch.setattr(PT, "_character", lambda ctx, q: {"slug": "hucast", "name": "HUcast"})
    pick = {"game_id": GAME["game_id"], "slot": "fighter:KAS:01", "backend": "doa2",
            "replaceable": {"live": False, "build": True, "reason": "DOA2 deforms the CHR"}}
    out = PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick=pick, character="hucast", fallback=False),
                          world.ctx)["result"]
    assert out["status"] == "live_failed" and "DOA2" in out["message"]
    with pytest.raises(ValueError, match="another game"):
        PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick={"game_id": "other", "slot": "player"},
                                         character="hucast"), world.ctx)


def test_relay_reemits_a_subjobs_fitting_stages_once(monkeypatch):
    fit = {"order": ["player"], "models": {"player": {"label": "A -> B", "stages": {
        "retarget": {"state": "done", "data": {"joints": 20}, "ts": 1.0}},
        "snapshot": "/api/jobs/sub/fitting/files/a.glb", "snapshot_stage": "retarget"}}}
    seq = [{"id": "sub", "state": "running", "fitting": fit, "progress": {"pct": 50, "msg": "fitting"}},
           {"id": "sub", "state": "succeeded", "fitting": json.loads(json.dumps(fit)) | {}, "output": {"result": {}}}]
    seq[1]["fitting"]["models"]["player"]["stages"]["write"] = {"state": "done", "ts": 2.0}
    monkeypatch.setattr(PT, "_api", lambda ctx, m, p, **k: seq.pop(0))
    monkeypatch.setattr(PT, "JOB_POLL_S", 0)
    got = []
    ctx = SimpleNamespace(progress=lambda p, m: got.append(FE.split(m)[1]))
    job = PT.relay(ctx, {"id": "sub", "state": "queued"}, 60)
    evs = [e for e in got if e]
    assert job["state"] == "succeeded"
    assert [(e["model"], e["stage"]) for e in evs] == [("player", "retarget"), ("player", "write")]
    assert evs[0]["snapshot"] == "/api/jobs/sub/fitting/files/a.glb" and evs[0]["data"] == {"joints": 20}


def test_pick_ghidra_parses_findrefs_and_explain_and_learns(monkeypatch, tmp_path):
    import subprocess
    from gbox import re_lab_tool
    ram = bytes(0x10000)

    def fake_run(cmd, **kw):
        out = Path(cmd[cmd.index("-postScript") + 2])
        if "FindRefs.java" in cmd:
            out.write_text(json.dumps({"targets": [{"addr": "8c477d40", "end": "8c477d40", "refs": [
                {"from": "8c0a0010", "to": "8c477d40", "function": "FUN_8c0a0000", "entry": "8c0a0000", "type": "READ"}]}]}))
        else:
            out.write_text(json.dumps({"addresses": [{"function": "FUN_8c0a0000", "entry": "8c0a0000",
                                                      "decompiled": "void FUN_8c0a0000(void) { draw(); }", "callers": []}]}))
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(PT, "_api", lambda ctx, m, p, **k: gzip.compress(ram))
    monkeypatch.setattr(re_lab_tool, "analysis_root", lambda cfg: tmp_path / "analysis")
    monkeypatch.setattr(tools, "_ghidra_exe", lambda cfg: Path("analyzeHeadless"))
    monkeypatch.setattr(tools, "_ghidra_env", lambda cfg=None: {})
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path / "data"), server=None, headers={}, job_id="g1",
                          progress=lambda p, m: None, artifact=lambda *a, **k: None)
    res = PT.run_ghidra(ctx, PT.PickGhidraIn(game_id="g", platform="dreamcast", ram="sha", base=DC,
                                             roots=["0x8C477D40"], labels={"0x8C477D40": "profile entities.table"}))
    root = res["roots"]["0x8C477D40"]
    assert root["functions"] == [{"name": "FUN_8c0a0000", "entry": "8c0a0000"}] and root["why"] == "profile entities.table"
    assert res["explained"][0]["decompiled"].startswith("void FUN_8c0a0000")
    learned = json.loads((tmp_path / "data" / "pick_learned" / "g.json").read_text())
    assert learned["ghidra"]["0x8C477D40"]["functions"][0]["entry"] == "8c0a0000"


def test_picture_and_region_mapping():
    assert PT.picture_xy(0.5, 0.5, 16 / 9) == (0.5, 0.5)
    x, _ = PT.picture_xy(0.125, 0.5, 16 / 9)
    assert abs(x) < 1e-9                                   # the left pillarbox edge is the picture's left edge
    assert PT.region_box({"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}, 4 / 3) == pytest.approx((0.4, 0.4, 0.6, 0.6))
    assert PT.region_box([0.6, 0.6, 0.4, 0.4], 4 / 3) == pytest.approx((0.4, 0.4, 0.6, 0.6))
    assert PT.region_box(None, 4 / 3) is None


def test_learned_pick_data_endpoints(cfg):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.get("/api/profiles/g1/pick").json() == {}
    assert client.post("/api/profiles/g1/pick", json={"classes": {}}).status_code == 404   # unknown game
    app.state.store.put("profile", "g1", {"game_id": "g1", "title": "T", "platform": "dreamcast"})
    client.post("/api/profiles/g1/pick", json={"classes": {"A": {"slot": "player", "seen": 1}}})
    r = client.post("/api/profiles/g1/pick", json={"classes": {"A": {"seen": 2}, "B": {"slot": "enemy:x"}}}).json()
    assert r["classes"] == {"A": {"slot": "player", "seen": 2}, "B": {"slot": "enemy:x"}}
    assert client.get("/api/profiles/g1/pick").json()["classes"]["A"]["seen"] == 2


def learned_of(world):
    return json.loads((world.tmp / "data" / "pick_learned" / f"{GAME['game_id']}.json").read_text())


def test_a_successful_identify_is_saved_compact_to_the_profile_and_the_session(monkeypatch, world):
    import httpx
    posts = []
    monkeypatch.setattr(httpx, "get", lambda *a, **k: SimpleNamespace(status_code=404, json=lambda: {}))
    monkeypatch.setattr(httpx, "post", lambda url, **k: posts.append((url, k.get("json"))))
    monkeypatch.setattr(PT, "_api", lambda ctx, m, p, **k: posts.append((p, k.get("json"))) or {})
    world.ctx.server = "http://cp"
    out = PT.pick_identify(PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5), world.ctx)
    saved = learned_of(world)
    pick = saved["picks"]["enemy:wolf"]
    assert saved["last_pick"] == pick and pick["status"] == "identified" and pick["session_id"] == "s1"
    assert pick["ram"]["model"] == out["ram"]["model"] and pick["ram"]["entity_struct"] == "0x8C400000"
    assert "structures" not in pick["ram"] and "draws" not in pick and "seconds" not in pick
    assert all("data" not in e for e in pick["evidence"]) and pick["replaceable"]["live"]
    session = [j for p, j in posts if p == "/api/sessions/s1/live-pick"]
    assert session and session[-1]["slot"] == "enemy:wolf" and session[-1]["game_id"] == GAME["game_id"]
    assert any(u.endswith("/api/profiles/daba7a3b195dcf6b/pick") and (j.get("picks") or {}).get("enemy:wolf")
               for u, j in posts if isinstance(j, dict))
    hover = PT.pick_identify(PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5, deep=False), world.ctx)
    assert hover["slot"] and learned_of(world)["picks"]["enemy:wolf"]["saved"] == pick["saved"]   # hovers aren't kept


def test_compact_pick_drops_bytes_images_and_walk_listings():
    pick = {"game_id": "g", "slot": "player", "backend": "profile", "ram": {"model": "0x1", "structures": [{"at": 1}],
            "_best": {}, "textures": [{"addr": "0x2", "rgba": b"\0" * 64}]}, "draws": [{"draw": 1}], "seconds": 3,
            "evidence": [{"step": "x", "ok": True, "detail": "d" * 900, "source": "s", "data": {"big": [1] * 999}}],
            "entity": {"class": "A", "pos": np.array([1.0, 2.0])}}
    c = PT.compact_pick(pick, signatures=[{"name": "n", "size": 4, "pieces": [{"offset": 0, "hex": "00ff"}]}])
    assert c["ram"] == {"model": "0x1", "textures": [{"addr": "0x2"}]} and "draws" not in c and "seconds" not in c
    assert len(c["evidence"][0]["detail"]) == 200 and "data" not in c["evidence"][0]
    assert c["entity"]["pos"] == [1.0, 2.0]
    assert c["signatures"][0]["pieces"][0] == {"offset": 0, "hex": "00ff"}     # a live write needs the signatures
    json.dumps(c)


def test_replace_live_and_swapped_save_the_pick_with_what_was_written(monkeypatch, world):
    new = bytearray(world.orig)
    new[0x200:0x240] = b"\x5A" * 0x40
    blob = LI.pack([LI.asset("WOLF.NJ", world.orig, bytes(new))], {"mod": "pso_x"})
    sigs = LI.signatures(LI.unpack(blob)[0])
    monkeypatch.setattr(PT, "_character", lambda ctx, q: {"slug": "hucast", "name": "HUcast"})
    monkeypatch.setattr(PT, "get_prepared", lambda *a, **k: {"mod": "pso_x", "patch_blob": blob, "signatures": sigs})
    pick = PT.pick_identify(PT.PickIdentifyIn(session_id="s1", x=0.5, y=0.5), world.ctx)
    res = PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick=pick, character="hucast"), world.ctx)["result"]
    assert res["status"] == "live"
    saved = learned_of(world)["picks"]["enemy:wolf"]
    assert saved["status"] == "live" and saved["replaced"]["slug"] == "hucast" and saved["replaced"]["mod"] == "pso_x"
    assert saved["ram"]["model_images"] == [{"name": "WOLF.NJ", "base": hex(world.asset_at), "bytes": 0x800}]
    assert saved["signatures"][0]["name"] == "WOLF.NJ" and learned_of(world)["last_pick"] == saved
    assert "class" in saved["entity"] and saved["ram"]["entity_struct"] == "0x8C400000"
    # the Blender round trip hands the saved pick back unchanged: pick_replace takes it as is
    blob2 = LI.pack([LI.asset("WOLF.NJ", bytes(new), bytes(world.orig))], {"mod": "pso_y"})
    monkeypatch.setattr(PT, "get_prepared", lambda *a, **k: {"mod": "pso_y", "patch_blob": blob2})
    again = PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick=saved, character="hucast"), world.ctx)["result"]
    assert again["status"] == "live"
    assert learned_of(world)["picks"]["enemy:wolf"]["replaced"]["mod"] == "pso_y"   # replaced whole, not merged
    # build: saved for the NEW session
    tools.SESSIONS["s2"] = (Emu(bytearray(0x1000000)), dict(GAME))
    calls = []

    def api(ctx, method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/sessions/s1/swap":
            return {"id": "sw1", "state": "running"}
        if path == "/api/jobs/sw1":
            return {"id": "sw1", "state": "succeeded", "output": {"session_id": "s2"}}
        return {}
    monkeypatch.setattr(PT, "_api", api)
    monkeypatch.setattr(PT.time, "sleep", lambda s: None)
    world.ctx.server = "http://cp"
    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **k: SimpleNamespace(status_code=404, json=lambda: {}))
    monkeypatch.setattr(httpx, "post", lambda *a, **k: None)
    res = PT.pick_replace(PT.PickReplaceIn(session_id="s1", pick=saved, character="hucast", mode="build"),
                          world.ctx)["result"]
    assert res["status"] == "swapped"
    kept = learned_of(world)["picks"]["enemy:wolf"]
    assert kept["status"] == "swapped" and kept["session_id"] == "s2" and kept["replaced"]["mode_used"] == "build"
    assert any(p == "/api/sessions/s2/live-pick" and j["slot"] == "enemy:wolf" for _m, p, j in calls)


def test_session_live_pick_endpoint(cfg):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    assert client.post("/api/sessions/nope/live-pick", json={"slot": "player"}).status_code == 404
    app.state.store.put("session", "s1", {"session_id": "s1", "state": "running", "game_id": "g"})
    assert client.post("/api/sessions/s1/live-pick", json={"slot": "player", "game_id": "g"}).status_code == 200
    s = next(x for x in client.get("/api/sessions").json() if x["session_id"] == "s1")
    assert s["live_pick"]["slot"] == "player" and s["live_pick"]["saved"]
    assert client.post("/api/sessions/s1/live-pick", json={"slot": "p", "blob": "x" * (300 << 10)}).status_code == 413
