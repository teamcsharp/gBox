"""Examine 3D capture sessions (#971 stages 2-3): a GL RetroArch session is captured through a separate
vulkan/glcore capture session at the operator's moment, without pausing or reconfiguring the operator's game."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import capture_relaunch as cr
from gbox import scene_capture as scene
from gbox.registry import Unsupported


class RA:
    name = "retroarch"

    def __init__(self, tmp, core="flycast", driver="gl", save_ok=True):
        self.proc = SimpleNamespace(poll=lambda: None, pid=4242)          # no .renderdoc: RenderDoc isn't inside
        self.core_path = f"C:/RetroArch/cores/{core}_libretro.dll"
        self.video_driver = driver
        self.content_path = str(tmp / "roms" / "Phantasy Star Online Ver. 2 (USA).gdi")
        self.retroarch_exe = "C:/RetroArch/retroarch.exe"
        self.slot, self.slots, self.paused, self.save_ok = 3, [], False, save_ok
        self.state = tmp / "operator-states" / "Phantasy Star Online Ver. 2 (USA).state70"

    def save_state(self, slot=None):
        if not self.save_ok:
            raise RuntimeError("RetroArch did not produce a verified save file")
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_bytes(b"RASTATE-the-moment")
        self.slot = slot
        return {"slot": slot, "path": str(self.state), "verified": True}

    def _slot(self, slot):
        self.slots.append(slot)
        self.slot = slot
        return slot

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def query_runtime(self):
        return {"state": "PAUSED" if self.paused else "PLAYING"}


class Fakes:
    def __init__(self, fail_capture=False):
        self.launched, self.cmds, self.stopped, self.captured = None, [], [], None
        self.proc = SimpleNamespace(poll=lambda: None, pid=777)
        self.fail_capture = fail_capture

    def launch(self, content, work, **kw):
        self.launched = (content, Path(work), kw)
        return self.proc

    def ra(self, cmd, port, reply=False):
        self.cmds.append((cmd, port))
        return "GET_STATUS PLAYING flycast,pso" if cmd == "GET_STATUS" else None

    def capture(self, pid, frames, cap_dir, wait):
        if self.fail_capture:
            raise RuntimeError("capture failed: no RenderDoc target")
        self.captured = (pid, frames, Path(cap_dir))
        return [Path(cap_dir) / "frame_0.rdc"]

    def extract(self, rdcs, out_dir, fovy, aspect):
        return {"draws_exported": 3, "textures": 2, "capture": str(rdcs[0])}

    def run(self, ad, tmp):
        return cr.run(ad, tmp / "out", 2, runtime=tmp / "rt", launch=self.launch, capture=self.capture,
                      extract_fn=self.extract, ra_command=self.ra, stop=self.stopped.append, sleep=lambda s: None)


def test_plan_runs_vulkan_cores_under_vulkan(tmp_path):
    p = cr.plan(RA(tmp_path))
    assert p["driver"] == "vulkan" and p["core"] == "flycast"
    assert p["extra_cfg"]["video_driver"] == "vulkan" and p["extra_cfg"]["state_slot"] == "0"
    assert p["content"].endswith(".gdi") and p["core_path"].endswith("flycast_libretro.dll")
    assert p["retroarch"] == "C:/RetroArch/retroarch.exe"


def test_plan_runs_gl_only_cores_under_glcore(tmp_path):
    assert cr.plan(RA(tmp_path, core="kronos"))["extra_cfg"]["video_driver"] == "glcore"


@pytest.mark.parametrize("change", ["software_core", "no_content", "standalone", "d3d11_unhooked"])
def test_no_capture_session_when_the_matrix_or_session_rules_it_out(tmp_path, change):
    ad = RA(tmp_path, core="snes9x" if change == "software_core" else "flycast",
            driver="d3d11" if change == "d3d11_unhooked" else "gl")
    if change == "no_content":
        ad.content_path = None
    if change == "standalone":
        ad.name = "yuzu"
    assert cr.plan(ad) is None


def test_capture_session_keeps_the_moment_and_never_touches_the_operator_game(tmp_path):
    ad, f = RA(tmp_path), Fakes()
    s = f.run(ad, tmp_path)
    content, work, kw = f.launched
    assert content == ad.content_path and kw["core_path"] == ad.core_path and kw["retroarch"] == ad.retroarch_exe
    assert kw["extra_cfg"]["video_driver"] == "vulkan"
    assert work.parent == tmp_path / "rt" / "capture_sessions"                 # agent-owned config dir
    staged = work / "states" / "Phantasy Star Online Ver. 2 (USA).state"
    assert staged.read_bytes() == b"RASTATE-the-moment"
    assert f.cmds.index(("GET_STATUS", kw["cmd_port"])) < f.cmds.index(("LOAD_STATE", kw["cmd_port"]))
    assert f.captured == (0, 2, work / "cap")
    assert f.stopped == [f.proc]
    assert ad.slots == [3] and ad.paused is False                              # slot counter back, never paused
    assert s["capture_session"]["driver"] == "vulkan" and s["capture_session"]["moment"] == "save_state"
    assert s["capture_session"]["operator_paused"] is False and s["draws_exported"] == 3


def test_failed_save_boots_fresh_and_says_so(tmp_path):
    ad, f = RA(tmp_path, save_ok=False), Fakes()
    s = f.run(ad, tmp_path)
    assert s["capture_session"]["moment"] == "fresh_boot"
    assert "save state failed" in s["capture_session"]["note"]
    assert not any(c == "LOAD_STATE" for c, _ in f.cmds) and ad.slots == [3]


def test_capture_session_is_stopped_when_capture_fails(tmp_path):
    f = Fakes(fail_capture=True)
    with pytest.raises(RuntimeError, match="no RenderDoc target"):
        f.run(RA(tmp_path), tmp_path)
    assert f.stopped == [f.proc]


def test_wait_ready_reports_an_exited_or_silent_capture_session():
    dead = SimpleNamespace(poll=lambda: 1)
    with pytest.raises(RuntimeError, match="exited during start-up"):
        cr.wait_ready(dead, lambda *a, **k: None, 1, timeout=5, sleep=lambda s: None)
    t = [0.0]
    alive = SimpleNamespace(poll=lambda: None)
    with pytest.raises(RuntimeError, match="did not start within 3 s"):
        cr.wait_ready(alive, lambda *a, **k: None, 1, timeout=3, sleep=lambda s: t.__setitem__(0, t[0] + s),
                      clock=lambda: t[0])


def test_scene_capture_routes_a_gl_session_to_a_capture_session(monkeypatch, tmp_path):
    ad, seen = RA(tmp_path), {}
    monkeypatch.setattr(scene, "hooked", lambda proc: False)

    def fake_run(a, out_dir, frames, fovy, aspect, progress):
        seen["ad"] = a
        return {"draws_exported": 1, "capture_session": {"driver": "vulkan", "moment": "save_state"}}
    monkeypatch.setattr(cr, "run", fake_run)
    s = scene.capture_session(ad, tmp_path / "out")
    assert seen["ad"] is ad and s["resume_on_leave"] is False and ad.paused is False


def test_gl_session_without_a_capture_plan_keeps_its_reason(monkeypatch, tmp_path):
    ad = RA(tmp_path)
    ad.content_path = None
    ad.examine_unavailable_reason = "3D draw-call capture is unavailable for this OpenGL RetroArch session."
    monkeypatch.setattr(scene, "hooked", lambda proc: False)
    with pytest.raises(Unsupported, match="unavailable for this OpenGL"):
        scene.capture_session(ad, tmp_path / "out")


def test_frame_rip_launch_reuses_the_session_core_and_driver(monkeypatch, tmp_path):
    from gbox import frame_rip, provision
    monkeypatch.setattr(frame_rip, "_cfg", lambda: SimpleNamespace(runtime=tmp_path / "rt"))
    monkeypatch.setattr(provision, "ensure_core", lambda *a, **k: pytest.fail("must reuse the session's core"))
    monkeypatch.setattr(frame_rip, "renderdoc_dir", lambda *a: tmp_path / "rd")
    seen = {}

    def popen(args, env=None, cwd=None, stdout=None, stderr=None):
        seen.update(args=args, env=env)
        stdout.close()
        return SimpleNamespace(pid=1)
    monkeypatch.setattr(frame_rip.subprocess, "Popen", popen)
    frame_rip.launch("C:/roms/game.cue", tmp_path / "work", core="kronos", retroarch="C:/RA/retroarch.exe",
                     extra_cfg={"video_driver": "glcore"}, core_path="C:/RA/cores/kronos_libretro.dll")
    assert 'video_driver = "glcore"' in (tmp_path / "work" / "ra.cfg").read_text()
    assert seen["args"][seen["args"].index("-L") + 1] == "C:/RA/cores/kronos_libretro.dll"
    assert seen["env"]["VK_INSTANCE_LAYERS"] == "VK_LAYER_RENDERDOC_Capture"


def test_frame_rip_launch_yuzu_forces_vulkan_and_user_path(monkeypatch, tmp_path):
    from gbox import frame_rip
    monkeypatch.setattr(frame_rip, "renderdoc_dir", lambda *a: tmp_path / "rd")
    seen = {}

    def popen(args, env=None, cwd=None, stdout=None, stderr=None):
        seen.update(args=args, env=env)
        stdout.close()
        return SimpleNamespace(pid=2)
    monkeypatch.setattr(frame_rip.subprocess, "Popen", popen)
    (tmp_path / "rd").mkdir()
    (tmp_path / "rd" / "renderdoccmd.exe").write_text("")
    frame_rip.launch_yuzu("C:/roms/game.nsp", "C:/yuzu/yuzu.exe", tmp_path / "user", cap_dir=tmp_path / "cap")
    assert '[Renderer]\nbackend=Vulkan\n' in (tmp_path / "user" / "config" / "qt-config.ini").read_text()
    assert "--user-path" in seen["args"] and str(tmp_path / "user") in seen["args"]
    assert seen["args"][seen["args"].index("-g") + 1] == "C:/roms/game.nsp"
    assert seen["env"]["VK_INSTANCE_LAYERS"] == "VK_LAYER_RENDERDOC_Capture"


class Yuzu:
    name = "yuzu"

    def __init__(self, tmp):
        self.content_path = str(tmp / "roms" / "Animal Crossing NH.nsp")
        self.yuzu_exe = "C:/yuzu/yuzu.exe"
        self.proc = SimpleNamespace(poll=lambda: None, pid=4242)


class YuzuFakes:
    def __init__(self):
        self.launched, self.captured, self.stopped = None, None, []
        self.proc = SimpleNamespace(poll=lambda: None, pid=888)

    def launch_yuzu(self, content, yuzu_exe, user_dir, cap_dir=None):
        self.launched = (content, yuzu_exe, Path(user_dir), Path(cap_dir) if cap_dir else None)
        cfg_dir = Path(user_dir) / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "qt-config.ini").write_text("[Renderer]\nbackend=Vulkan\n")
        return self.proc

    def capture(self, pid, frames, cap_dir, wait):
        self.captured = (pid, frames, Path(cap_dir))
        return [Path(cap_dir) / "frame_0.rdc"]

    def extract(self, rdcs, out_dir, fovy, aspect):
        return {"draws_exported": 5, "textures": 3, "capture": str(rdcs[0])}

    def run(self, ad, tmp):
        return cr.run(ad, tmp / "out", 2, runtime=tmp / "rt", launch_yuzu=self.launch_yuzu,
                      capture=self.capture, extract_fn=self.extract,
                      wait_window=lambda *a, **k: None,
                      stop=lambda p, *_: self.stopped.append(p), sleep=lambda s: None)


def test_yuzu_plan_relaunches_under_vulkan(tmp_path):
    p = cr.plan(Yuzu(tmp_path))
    assert p["type"] == "yuzu" and p["driver"] == "vulkan"
    assert p["content"].endswith("Animal Crossing NH.nsp") and p["yuzu_exe"] == "C:/yuzu/yuzu.exe"


def test_yuzu_capture_session_boots_fresh_and_does_not_touch_operator_game(tmp_path):
    ad, f = Yuzu(tmp_path), YuzuFakes()
    s = f.run(ad, tmp_path)
    content, yuzu_exe, user_dir, cap_dir = f.launched
    assert content == ad.content_path and yuzu_exe == ad.yuzu_exe
    assert user_dir.parent.parent == tmp_path / "rt" / "capture_sessions"                 # agent-owned user dir
    assert (user_dir / "config" / "qt-config.ini").read_text() == "[Renderer]\nbackend=Vulkan\n"
    assert f.captured == (0, 2, cap_dir)
    assert cap_dir == user_dir.parent / "cap"                                              # captures land next to the user dir
    assert f.stopped == [f.proc]
    assert s["capture_session"]["driver"] == "vulkan" and s["capture_session"]["moment"] == "fresh_boot"
    assert s["capture_session"]["operator_paused"] is False and s["draws_exported"] == 5


def test_yuzu_without_content_or_exe_has_no_plan(tmp_path):
    ad = Yuzu(tmp_path)
    ad.content_path = ""
    assert cr.plan(ad) is None
    ad.content_path = str(tmp_path / "roms" / "game.nsp")
    ad.yuzu_exe = ""
    assert cr.plan(ad) is None
