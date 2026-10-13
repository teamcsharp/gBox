"""Examine 3D (#971): Yuzu / RPCS3 Vulkan-layer rows that settle after the game boots, and replays that run out of GPU
memory while the paused emulator holds it (live check on JAYBUILTFINALE, Animal Crossing NH on Yuzu)."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import scene_capture as scene
from gbox import scene_support as ss
from gbox.registry import Unsupported


class Proc:
    """A live (or ended) emulator process started with RenderDoc's Vulkan layer."""
    def __init__(self, info, alive=True):
        self.pid, self.renderdoc, self.alive = 999999, info, alive

    def poll(self):
        return None if self.alive else 0


def layer(age_s=0.0, loaded=False):
    return {"attach": "layer", "loaded": loaded, "started": time.time() - age_s}


def yuzu(info, **kw):
    calls = []
    ad = SimpleNamespace(name="yuzu", cfg=None, video_driver="vulkan", paused_tids=[], proc=Proc(info), calls=calls,
                         query_runtime=lambda: {"running": True, "paused": False}, get_frame=lambda: b"\x89PNG",
                         pause=lambda: calls.append("pause"), resume=lambda: calls.append("resume"))
    for k, v in kw.items():
        setattr(ad, k, v)
    return ad


@pytest.fixture
def no_kill(monkeypatch):
    monkeypatch.setattr(scene, "_kill_children", lambda pid: 0)


def test_layer_started_yuzu_is_pending_not_examine_off(monkeypatch, no_kill):
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: False)
    row = ss.session_support(yuzu(layer(age_s=12)), "windows")      # the 10 s launch check already gave up
    assert (row["status"], row["layer"], row["attach"]) == (ss.SUPPORTED, "pending", "layer")
    assert "Examine 3D on" in row["reason"] and "off at launch" not in row["reason"]


def test_row_is_supported_once_yuzu_makes_its_vulkan_device(monkeypatch, no_kill):
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: True)
    ad = yuzu(layer(age_s=40))
    row = ss.session_support(ad, "windows")
    assert row["status"] == ss.SUPPORTED and row.get("layer") is None and ad.proc.renderdoc["loaded"] is True


def test_layer_that_never_loads_is_missed_not_examine_off(monkeypatch, no_kill):
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: False)
    row = ss.session_support(yuzu(layer(age_s=ss.LAYER_PENDING_MAX_S + 5), name="rpcs3"), "windows")
    assert (row["status"], row["layer"]) == (ss.RELAUNCH, "missed")
    assert "never loaded" in row["reason"] and "RPCS3" in row["reason"] and "off at launch" not in row["reason"]


def test_ended_or_unlayered_sessions_keep_their_rows(monkeypatch, no_kill):
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: False)
    ad = yuzu(layer(age_s=5))
    ad.proc.alive = False
    assert ss.session_support(ad, "windows")["status"] == ss.RELAUNCH
    plain = ss.session_support(yuzu(None), "windows")              # started without the layer: Examine 3D was off
    assert plain["status"] == ss.RELAUNCH and "off at launch" in plain["reason"] and plain.get("layer") is None


def test_capture_on_a_pending_layer_waits_then_explains(monkeypatch, tmp_path, no_kill):
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: False)
    monkeypatch.setattr(scene, "LAYER_WAIT_S", 0)
    ad = yuzu(layer(age_s=3))
    with pytest.raises(Unsupported, match="has not loaded yet"):
        scene.capture_session(ad, tmp_path)
    assert ad.calls == ["resume"]                       # the game was running: it keeps running


def test_capture_goes_ahead_when_the_layer_loads_during_the_wait(monkeypatch, tmp_path, no_kill):
    seen = iter([False, False])                         # hooked() and the matrix probe miss it; the wait sees it
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: next(seen, True))
    rdc = tmp_path / "f.rdc"
    rdc.write_bytes(b"RDOC")
    monkeypatch.setattr(scene, "capture_rdc", lambda pid, frames, **k: [rdc])

    def fake_extract(rdcs, out_dir, fovy=0, aspect=0, **k):
        (Path(out_dir) / "scene.glb").write_bytes(b"glTF")
        return {"draws_total": 40, "scene_draws": 30, "draws_exported": 30, "textures": 2, "capture": str(rdcs[0])}
    monkeypatch.setattr(scene, "extract", fake_extract)
    s = scene.capture_session(yuzu(layer(age_s=3)), tmp_path / "out")
    assert s["scene_draws"] == 30 and s["resume_on_leave"] is True and (tmp_path / "out" / "frame.rdc").is_file()


def test_extract_names_a_gpu_out_of_memory_replay(monkeypatch, tmp_path):
    def oom_log(script, env, timeout):
        (Path(env["RD_OUT"]) / "extract.log").write_text(
            "Traceback (most recent call last):\nAssertionError: ResultCode.OutOfMemory VK_ERROR_OUT_OF_DEVICE_MEMORY\n")
    monkeypatch.setattr(scene, "_qrd", oom_log)
    with pytest.raises(scene.ReplayOutOfMemory):
        scene.extract([tmp_path / "a.rdc"], tmp_path / "out")
    monkeypatch.setattr(scene, "_qrd", lambda script, env, timeout: (Path(env["RD_OUT"]) / "extract.log").write_text("boom"))
    with pytest.raises(RuntimeError) as e:
        scene.extract([tmp_path / "a.rdc"], tmp_path / "out")
    assert not isinstance(e.value, scene.ReplayOutOfMemory)

    def crash(script, env, timeout):
        raise RuntimeError("qrenderdoc exited 3: vkAllocateMemory returned VK_ERROR_OUT_OF_DEVICE_MEMORY")
    monkeypatch.setattr(scene, "_qrd", crash)
    with pytest.raises(scene.ReplayOutOfMemory):
        scene.extract([tmp_path / "a.rdc"], tmp_path / "out")


def test_out_of_memory_replay_keeps_the_capture_and_the_game_running(monkeypatch, tmp_path):
    monkeypatch.setattr(scene, "hooked", lambda proc: True)
    cap = tmp_path / "rdc"
    cap.mkdir()
    rdcs = [cap / f"frame_{i}.rdc" for i in range(2)]
    for r in rdcs:
        r.write_bytes(b"RDOC")
    monkeypatch.setattr(scene, "capture_rdc", lambda pid, frames, **k: list(rdcs))

    def oom(*a, **k):
        raise scene.ReplayOutOfMemory("scene extract failed: VK_ERROR_OUT_OF_DEVICE_MEMORY")
    monkeypatch.setattr(scene, "extract", oom)
    ad = yuzu(layer(loaded=True))
    out = tmp_path / "out"
    with pytest.raises(Unsupported, match="video memory Yuzu holds"):
        scene.capture_session(ad, out)
    info = json.loads((out / "rebuild.json").read_text())
    assert [Path(r).parent for r in info["rdcs"]] == [out / "rebuild"] * 2 and all(Path(r).is_file() for r in info["rdcs"])
    assert info["emulator"] == "yuzu" and (out / "frame.png").is_file()
    assert ad.calls[-1] == "resume"                     # pause state restored: the operator's game keeps running


def kept(out, title="Animal Crossing: New Horizons"):
    (out / "rebuild").mkdir(parents=True)
    rdc = out / "rebuild" / "frame_0.rdc"
    rdc.write_bytes(b"RDOC")
    (out / "rebuild.json").write_text(json.dumps({"rdcs": [str(rdc)], "fovy": 0, "aspect": 0, "emulator": "yuzu",
                                                  "meta": {"game": "0c77e1500e467772", "title": title}}))
    return rdc


def fake_scene(monkeypatch, draws=200):
    def fake_extract(rdcs, out_dir, fovy=0, aspect=0, **k):
        (Path(out_dir) / "scene.glb").write_bytes(b"glTF-rebuilt")
        return {"draws_total": draws + 20, "scene_draws": draws, "draws_exported": draws, "textures": 15,
                "capture": str(rdcs[0])}
    monkeypatch.setattr(scene, "extract", fake_extract)


def test_rebuild_replays_the_kept_capture_after_the_game_closed(monkeypatch, tmp_path):
    out = tmp_path / "out"
    kept(out)
    fake_scene(monkeypatch)
    s = scene.rebuild_kept(out)
    assert s["rebuilt_from_kept"] and s["kept_meta"]["game"] == "0c77e1500e467772" and s["resume_on_leave"] is False
    assert s["capture_attempts"][0]["scene_draws"] == 200
    assert (out / "frame.rdc").is_file() and not (out / "rebuild.json").exists() and not (out / "rebuild").exists()
    with pytest.raises(Unsupported, match="No kept capture"):
        scene.rebuild_kept(out)


def test_rebuild_still_out_of_memory_says_close_the_game(monkeypatch, tmp_path):
    out = tmp_path / "out"
    kept(out)

    def oom(*a, **k):
        raise scene.ReplayOutOfMemory("oom")
    monkeypatch.setattr(scene, "extract", oom)
    with pytest.raises(Unsupported, match="close the game"):
        scene.rebuild_kept(out)
    assert (out / "rebuild.json").exists()               # still kept for the next try


def test_scene_capture_rebuild_job_needs_no_live_session(monkeypatch, tmp_path):
    from gbox import tools
    monkeypatch.setattr(tools, "SESSIONS", {})
    sid = "786c6f7687d441f3-f275300b8f6840be"
    kept(tmp_path / "scene_capture" / sid)
    fake_scene(monkeypatch)
    arts = {}
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda p, m: None,
                          artifact=lambda name, data, mime, **meta: arts.__setitem__(name, (data, meta)))
    res = scene.scene_capture(scene.SceneIn(session_id=sid, rebuild=True), ctx)
    assert res["glb"] == scene.sha256(b"glTF-rebuilt") and res["paused"] is False
    assert arts["scene.glb"][1]["title"] == "Animal Crossing: New Horizons"
    assert scene.SceneOut.model_validate(res)
    with pytest.raises(Unsupported, match="no longer available"):   # without rebuild an ended session is refused
        scene.scene_capture(scene.SceneIn(session_id=sid), ctx)


def test_scene_capture_names_the_game_on_a_kept_capture(monkeypatch, tmp_path):
    from gbox import tools
    sid = "786c6f7687d441f3-aaaa"
    monkeypatch.setattr(tools, "SESSIONS", {sid: (yuzu(layer(loaded=True)), {"game_id": "0c77e1500e467772",
                                                                            "title": "ACNH"})})

    def keep_then_fail(ad_, out, *a, **k):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / "rebuild.json").write_text(json.dumps({"rdcs": []}))
        raise Unsupported("kept")
    monkeypatch.setattr(scene, "capture_session", keep_then_fail)
    ctx = SimpleNamespace(config=SimpleNamespace(runtime=tmp_path), progress=lambda p, m: None,
                          artifact=lambda *a, **k: None)
    with pytest.raises(Unsupported):
        scene.scene_capture(scene.SceneIn(session_id=sid), ctx)
    assert json.loads((tmp_path / "scene_capture" / sid / "rebuild.json").read_text())["meta"]["title"] == "ACNH"


def test_session_watch_posts_the_settled_row_to_the_server(monkeypatch, no_kill):
    from gbox import tools
    monkeypatch.setattr(tools, "HOST_OS", "windows")
    state = {"loaded": False}
    monkeypatch.setattr(scene, "renderdoc_loaded", lambda pid: state["loaded"])
    ad = yuzu(layer(age_s=2))
    posts = []
    c = SimpleNamespace(post=lambda url, json: posts.append((url, json)))
    assert tools._scene_row_watch(ad)
    assert tools._refresh_scene_row(c, "w-s", ad) is True and posts == []
    state["loaded"] = True
    assert tools._refresh_scene_row(c, "w-s", ad) is False
    (url, body), = posts
    assert url == "/api/sessions/w-s/detail" and body["examine"] is True
    assert body["scene_capture"]["status"] == ss.SUPPORTED and body["scene_capture"].get("layer") is None
    assert not tools._scene_row_watch(ad)
    assert "scene_watch = _refresh_scene_row(c, sid, ad)" in open(tools.__file__).read()


def test_server_lets_a_rebuild_through_for_an_ended_session():
    from gbox import server
    src = open(server.__file__).read()
    i = src.index('if inp.get("rebuild"):')
    j = src.index('raise HTTPException(409, "This game session has ended.', i)
    assert i < j and "wants_relay" in src[j:j + 600]
