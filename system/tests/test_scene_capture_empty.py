"""#971: a capture holding only the emulator's present blit(s) is retried once with the game running, and a frame
with no 3D draw is returned labelled 2D-only with the reason instead of as an empty 3D scene."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import scene_capture as sc


class Proc:
    pid = 4242

    def poll(self):
        return None


class Emu:
    def __init__(self, name):
        self.name, self.proc, self.calls = name, Proc(), []

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def get_frame(self):
        self.calls.append("frame")
        return b"\x89PNG %d" % len(self.calls)


class RetroArch(Emu):
    def __init__(self):
        super().__init__("retroarch")
        self.cmd, self.addr = object(), ("127.0.0.1", 55355)


class Dolphin(Emu):
    paused_tids = None

    def __init__(self):
        super().__init__("dolphin")


def S(tag, total, scene, hud=0):
    return {"tag": tag, "draws_total": total, "scene_draws": scene, "hud_draws": hud, "draws_exported": scene + hud,
            "textures": 0}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    ns = SimpleNamespace(caps=[], results=[], out=tmp_path / "out", fail_on=None)

    def capture_rdc(pid, frames=1, step="", wait=30, on_triggered=None):
        k = len(ns.caps)
        ns.caps.append({"frames": frames, "step": step})
        if ns.fail_on == k:
            raise RuntimeError("RenderDoc capture failed: no RenderDoc target")
        paths = []
        for i in range(frames):
            p = tmp_path / f"cap{k}_{i}.rdc"
            p.write_bytes(b"RDOC")
            paths.append(p)
        return paths

    def extract(rdcs, out_dir, fovy=0, aspect=0, mode="auto", timeout=600):
        s = dict(ns.results.pop(0))
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        s["capture"] = str(rdcs[-1])
        (out / "scene.glb").write_bytes(b"glTF" + s["tag"].encode())
        (out / "scene.json").write_text(json.dumps(s))
        (out / f"tex_{s['tag']}.png").write_bytes(b"png")
        return s

    monkeypatch.setattr(sc, "capture_rdc", capture_rdc)
    monkeypatch.setattr(sc, "extract", extract)
    monkeypatch.setattr(sc, "hooked", lambda proc: True)
    monkeypatch.setattr(sc, "RETRY_SETTLE_S", 0)
    return ns


def test_scene_empty_threshold():
    assert sc.scene_empty({"draws_total": 3, "scene_draws": 0})               # RetroArch's present blits
    assert sc.scene_empty({"draws_total": 1, "scene_draws": 0})               # Dolphin's XFB present
    assert not sc.scene_empty({"draws_total": 29, "scene_draws": 0, "hud_draws": 22})   # a real 2D screen
    assert not sc.scene_empty({"draws_total": 281, "scene_draws": 200})
    assert not sc.scene_empty({"draws_total": 4, "scene_draws": 2})


def test_retroarch_empty_frame_is_retried_with_the_game_running(rig):
    ad = RetroArch()
    rig.results[:] = [S("first", 3, 0), S("retry", 281, 200, 47)]
    s = sc._capture_session(ad, rig.out, frames=2)
    assert rig.caps == [{"frames": 2, "step": "udp:55355:FRAMEADVANCE"}, {"frames": sc.RETRY_FRAMES, "step": ""}]
    assert ad.calls == ["pause", "frame", "resume", "pause", "frame"]    # paused again; the new frame is grabbed
    assert s["scene_draws"] == 200 and "fallback" not in s and "note" not in s
    assert [a["how"] for a in s["capture_attempts"]] == ["paused, frame step", "game running"]
    assert [a["draws_total"] for a in s["capture_attempts"]] == [3, 281]
    assert (rig.out / "scene.glb").read_bytes() == b"glTFretry"
    assert (rig.out / "tex_retry.png").exists() and not (rig.out / "tex_first.png").exists()
    assert not (rig.out / "retry").exists()
    assert s["capture"] == str(rig.out / "frame.rdc") and (rig.out / "frame.rdc").exists()
    assert not list(rig.out.parent.glob("cap*.rdc"))                      # the other captured frames are removed
    assert "retry_s" in s["timings"] and s["frame_png"] is True


def test_dolphin_xfb_only_frames_are_labelled_2d_only(rig):
    ad = Dolphin()
    rig.results[:] = [S("a", 1, 0), S("b", 1, 0)]
    s = sc._capture_session(ad, rig.out, frames=2)
    assert [c["frames"] for c in rig.caps] == [2, sc.RETRY_FRAMES]
    assert ad.calls == ["pause", "frame", "resume", "pause"]
    assert s["fallback"] == "frame_2d" and s["scene_empty"] is True
    assert "held only 1 draw call(s)" in s["note"] and "2D-only" in s["note"] and "XFB" in s["note"]
    assert (rig.out / "scene.glb").read_bytes() == b"glTFa"               # the retry was no busier: first kept
    assert len(s["capture_attempts"]) == 2


def test_ps2_empty_capture_names_the_known_lrps2_gap(rig, monkeypatch):
    from gbox import scene_support
    monkeypatch.setattr(scene_support, "session_support",
                        lambda ad, host_os=None: {"adapter": "retroarch", "core": "pcsx2"})
    rig.results[:] = [S("a", 3, 0), S("b", 3, 0)]
    s = sc._capture_session(RetroArch(), rig.out, frames=2)
    assert s["scene_empty"] is True and "LRPS2" in s["note"]


def test_2d_screen_is_labelled_without_a_retry(rig):
    rig.results[:] = [S("menu", 29, 0, 22)]
    s = sc._capture_session(RetroArch(), rig.out, frames=2)
    assert len(rig.caps) == 1 and len(s["capture_attempts"]) == 1
    assert s["fallback"] == "frame_2d" and s["scene_empty"] is False and "2D screen" in s["note"]


def test_3d_frame_is_kept_without_a_retry(rig):
    ad = RetroArch()
    rig.results[:] = [S("pso", 281, 200, 47)]
    s = sc._capture_session(ad, rig.out, frames=2)
    assert len(rig.caps) == 1 and ad.calls == ["pause", "frame"]
    assert "fallback" not in s and s["capture_attempts"][0]["scene_draws"] == 200


def test_failed_retry_keeps_the_first_capture(rig):
    ad = RetroArch()
    rig.fail_on = 1
    rig.results[:] = [S("first", 3, 0)]
    s = sc._capture_session(ad, rig.out, frames=2)
    assert s["capture_attempts"][1]["error"].startswith("RenderDoc capture failed")
    assert ad.calls == ["pause", "frame", "resume", "pause"]              # left paused, as after any capture
    assert s["fallback"] == "frame_2d" and (rig.out / "scene.glb").read_bytes() == b"glTFfirst"
    assert "1 attempt" not in s["note"] and "over 2 attempt(s)" in s["note"]
