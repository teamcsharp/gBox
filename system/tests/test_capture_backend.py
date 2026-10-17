"""#971 stage 2: capture-session backends per emulator, RenderDoc's Vulkan layer environment, and that every override
lands in the agent-owned capture session's own files (never the operator's). Fake RenderDoc folder, no emulator."""
import hashlib
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters
from gbox import capture_backend as cb
from gbox import scene_capture as scene
from gbox.config import EmulatorConfig

MANIFEST = {"file_format_version": "1.1.2", "layer": {
    "name": "VK_LAYER_RENDERDOC_Capture", "type": "GLOBAL", "library_path": ".\\renderdoc.dll",
    "implementation_version": "46", "enable_environment": {"ENABLE_VULKAN_RENDERDOC_CAPTURE": "1"},
    "disable_environment": {"DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46": "1"}}}


@pytest.fixture
def fake_rd(tmp_path):
    rd = tmp_path / "runtime" / "tools" / "RenderDoc_1.46_64"
    rd.mkdir(parents=True)
    (rd / "renderdoc.json").write_text(json.dumps(MANIFEST))
    for f in ("renderdoc.dll", "qrenderdoc.exe", "renderdoccmd.exe"):
        (rd / f).write_bytes(b"")
    return rd


# ------------------------------------------------------------------------------------------- backend per emulator

@pytest.mark.parametrize("adapter,core,driver,attach,options", [
    ("retroarch", "flycast_libretro.dll", "vulkan", "layer", {}),
    ("retroarch", "mednafen_psx_hw", "vulkan", "layer", {"beetle_psx_hw_renderer": "hardware_vk"}),
    ("retroarch", "pcsx2", "d3d11", "inject", {}),
    ("retroarch", "lrps2", "d3d11", "inject", {}),
    ("retroarch", "dolphin", "vulkan", "layer", {"dolphin_renderer": "Hardware"}),
    ("retroarch", "citra", "vulkan", "layer", {"citra_graphics_api": "Vulkan"}),
    ("retroarch", "swanstation", "vulkan", "layer", {"swanstation_GPU_Renderer": "Vulkan"}),
    ("retroarch", "ppsspp", "vulkan", "layer", {"ppsspp_backend": "vulkan"}),
    ("retroarch", "mupen64plus_next", "glcore", "inject", {"mupen64plus-rdp-plugin": "gliden64",
                                                          "mupen64plus-rsp-plugin": "hle"}),
    ("retroarch", "kronos", "glcore", "inject", {}),
    ("retroarch", "some_new_core", "vulkan", "layer", {}),
    ("dolphin", None, "vulkan", "layer", {}),
    ("rpcs3", None, "vulkan", "layer", {}),
    ("yuzu", None, "vulkan", "layer", {}),
])
def test_backend_per_emulator(adapter, core, driver, attach, options):
    p = cb.plan(adapter, core)
    assert (p["driver"], p["attach"], p["core_options"]) == (driver, attach, options)
    if adapter == "retroarch":
        assert p["ra_cfg"] == {"video_driver": driver}


@pytest.mark.parametrize("adapter,core", [("retroarch", "snes9x"), ("retroarch", "genesis_plus_gx"),
                                          ("retroarch", "parallel_n64"), ("xenia", None),
                                          ("steam", None), ("mame", None)])
def test_no_capture_backend_without_a_3d_path(adapter, core):
    assert cb.plan(adapter, core) is None


# ------------------------------------------------------------------------------------------- RenderDoc's Vulkan layer

def test_layer_env_loads_renderdoc_by_environment_only(fake_rd, tmp_path):
    base = {"PATH": "x", "VK_ADD_LAYER_PATH": "C:/other", "DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46": "1",
            "VK_INSTANCE_LAYERS": "VK_LAYER_KHRONOS_validation"}
    env = cb.layer_env(fake_rd, tmp_path / "cap" / "frame", base=base)
    assert env["ENABLE_VULKAN_RENDERDOC_CAPTURE"] == "1"
    assert "DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46" not in env
    assert env["VK_ADD_IMPLICIT_LAYER_PATH"] == str(fake_rd)
    assert env["VK_ADD_LAYER_PATH"].startswith(str(fake_rd)) and env["VK_ADD_LAYER_PATH"].endswith("C:/other")
    assert env["VK_INSTANCE_LAYERS"].startswith("VK_LAYER_RENDERDOC_Capture")
    assert "VK_LAYER_KHRONOS_validation" in env["VK_INSTANCE_LAYERS"]
    assert env["RENDERDOC_CAPFILE"] == str(tmp_path / "cap" / "frame") and (tmp_path / "cap").is_dir()
    assert base["DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46"] == "1" and "ENABLE_VULKAN_RENDERDOC_CAPTURE" not in base


def test_layer_env_needs_renderdocs_manifest(tmp_path):
    with pytest.raises(FileNotFoundError, match="renderdoc.json"):
        cb.layer_env(tmp_path)
    (tmp_path / "renderdoc.json").write_text(json.dumps({"layer": {"name": "VK_LAYER_other"}}))
    with pytest.raises(ValueError, match="capture layer"):
        cb.layer_env(tmp_path)


def test_popen_layer_starts_without_injection(monkeypatch, fake_rd, tmp_path):
    started = []

    class FakePopen:
        def __init__(self, argv, **kw):
            started.append((argv, kw))
            self.pid = 42

        def poll(self):
            return None
    monkeypatch.setattr(scene, "renderdoc_dir", lambda provision=False: fake_rd)
    monkeypatch.setattr(scene.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(scene, "inject", lambda *a, **k: pytest.fail("a Vulkan capture session must not inject"))
    p = scene.popen_layer(["retroarch.exe", "--config", "x.cfg"], tmp_path / "rdc", cwd=str(tmp_path))
    argv, kw = started[0]
    assert argv[0] == "retroarch.exe" and kw["env"]["ENABLE_VULKAN_RENDERDOC_CAPTURE"] == "1"
    assert p.renderdoc["attach"] == "layer" and "error" not in p.renderdoc
    loaded = {"yes": False}
    monkeypatch.setattr(scene, "_modules", lambda pid: {"renderdoc.dll": 1} if loaded["yes"] else {})
    monkeypatch.setattr(scene, "_kill_children", lambda pid, name="renderdoccmd.exe": 0)
    assert scene.hooked(p) is False and p.renderdoc["loaded"] is False        # no Vulkan device yet
    loaded["yes"] = True
    assert scene.hooked(p) is True and p.renderdoc["loaded"] is True


def test_popen_layer_without_renderdoc_still_launches(monkeypatch, tmp_path):
    def missing(provision=False):
        raise FileNotFoundError("RenderDoc not found")
    monkeypatch.setattr(scene, "renderdoc_dir", missing)
    monkeypatch.setattr(scene.subprocess, "Popen", lambda argv, **kw: SimpleNamespace(pid=1, poll=lambda: None))
    p = scene.popen_layer(["yuzu.exe"], None)
    assert "RenderDoc not found" in p.renderdoc["error"]


def _zip(files: dict) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        for k, v in files.items():
            z.writestr(k, v)
    return b.getvalue()


def test_ensure_renderdoc_installs_the_pinned_portable_build(tmp_path):
    data = _zip({"RenderDoc_9.9_64/qrenderdoc.exe": b"q", "RenderDoc_9.9_64/renderdoc.json": json.dumps(MANIFEST),
                 "RenderDoc_9.9_64/renderdoc.dll": b"d"})
    urls = []
    with pytest.raises(RuntimeError, match="sha256"):
        scene.ensure_renderdoc(tmp_path, "9.9", "0" * 64, fetch=lambda u: data)
    rd = scene.ensure_renderdoc(tmp_path, "9.9", hashlib.sha256(data).hexdigest(), fetch=lambda u: urls.append(u) or data)
    assert rd == tmp_path / "tools" / "RenderDoc_9.9_64" and (rd / "renderdoc.json").is_file()
    assert urls == ["https://renderdoc.org/stable/9.9/RenderDoc_9.9_64.zip"]
    assert scene.ensure_renderdoc(tmp_path, "9.9", "unused", fetch=lambda u: pytest.fail("already installed")) == rd


def test_ensure_renderdoc_rejects_paths_outside_its_folder(tmp_path):
    data = _zip({"RenderDoc_9.9_64/../../evil.dll": b"x"})
    with pytest.raises(RuntimeError, match="unsafe path"):
        scene.ensure_renderdoc(tmp_path, "9.9", hashlib.sha256(data).hexdigest(), fetch=lambda u: data)
    assert not (tmp_path / "evil.dll").exists()


# ------------------------------------------------------------------------------------------- overrides stay agent-owned

def _retroarch(tmp_path, monkeypatch, core="flycast", platform="dreamcast"):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")          # the capture branch is OS-independent; skip pad probing
    cfg = SimpleNamespace(runtime=tmp_path / "rt", data_dir=tmp_path)
    ad = adapters.RetroArchAdapter(EmulatorConfig(core=core, executable=str(tmp_path / "retroarch.exe")), config=cfg,
                                   platform=platform, port=55555)
    shared = cfg.runtime / "retroarch" / "core-options.cfg"
    shared.parent.mkdir(parents=True)
    shared.write_text('reicast_internal_resolution = "1280x960"\nbeetle_psx_hw_renderer = "hardware_gl"\n')
    return ad, shared


def test_retroarch_capture_session_writes_only_its_own_files(tmp_path, monkeypatch):
    ad, shared = _retroarch(tmp_path, monkeypatch, "mednafen_psx_hw", "psx")
    before = shared.read_text()
    normal = ad._write_cfg()
    ad.capture_backend = cb.plan("retroarch", "mednafen_psx_hw")
    own = ad._write_cfg()
    work = tmp_path / "rt" / "capture_sessions" / "ra-55555"
    assert own == work / "retroarch.cfg" and own != normal
    text = own.read_text()
    assert 'video_driver = "vulkan"' in text and 'audio_enable = "false"' in text
    assert f'savestate_directory = "{work / "states"}"' in text
    assert f'core_options_path = "{work / "core-options.cfg"}"' in text
    assert 'input_player1_joypad_index = "15"' in text and 'config_save_on_exit = "false"' in text
    opts = (work / "core-options.cfg").read_text()
    assert 'beetle_psx_hw_renderer = "hardware_vk"' in opts and 'reicast_internal_resolution = "1280x960"' in opts
    assert shared.read_text() == before                         # the operator's core options are untouched
    assert 'video_driver = "gl"' in normal.read_text()          # and so is the operator's session config
    assert ad.state_dir() == work / "states"


def test_flycast_capture_session_keeps_the_operators_state_options(tmp_path, monkeypatch):
    ad, shared = _retroarch(tmp_path, monkeypatch)
    ad.capture_backend = cb.plan("retroarch", "flycast")
    ad._write_cfg()
    opts = (tmp_path / "rt" / "capture_sessions" / "ra-55555" / "core-options.cfg").read_text()
    assert 'reicast_threaded_rendering = "disabled"' in opts     # same state layout as the operator's session
    assert "reicast_threaded_rendering" not in shared.read_text()


def test_popen_picks_layer_or_injection_by_plan(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    monkeypatch.setattr(adapters, "keep_offscreen", lambda pid, **kw: calls.append(("offscreen", kw)))
    monkeypatch.setattr(adapters, "capture_start", lambda: "capture-start")
    monkeypatch.setattr(adapters, "hidden_start", lambda: "hidden-start")
    import gbox.graphics
    monkeypatch.setattr(gbox.graphics, "prefer_gpu", lambda exe: None)
    monkeypatch.setattr(scene, "popen_layer", lambda argv, cap_dir, **kw: calls.append(("layer", kw)) or
                        SimpleNamespace(pid=7))
    monkeypatch.setattr(scene, "popen_hooked", lambda argv, cap_dir=None, **kw: calls.append(("inject", kw)) or
                        SimpleNamespace(pid=8))
    cfg = tmp_path / "ra.cfg"
    cfg.write_text('video_driver = "glcore"\n')
    ad = SimpleNamespace(examine=True, config=SimpleNamespace(runtime=tmp_path), capture_backend=cb.plan("retroarch", "flycast"))
    adapters._popen(ad, ["ra.exe", "--config", str(cfg)])
    assert calls[0][0] == "layer" and calls[0][1]["startupinfo"] == "capture-start"
    assert calls[1] == ("offscreen", {"limit_s": 1800.0, "give_up_s": float("inf")})   # never pops onto the desktop
    calls.clear()
    ad.capture_backend = cb.plan("retroarch", "kronos")
    adapters._popen(ad, ["ra.exe", "--config", str(cfg)])
    assert calls[0][0] == "inject"                              # glcore is injectable in a capture session only
    calls.clear()
    operator = SimpleNamespace(examine=True, config=SimpleNamespace(runtime=tmp_path))
    monkeypatch.setattr(adapters.subprocess, "Popen", lambda argv, **kw: calls.append(("plain", kw)) or SimpleNamespace(pid=9))
    adapters._popen(operator, ["ra.exe", "--config", str(cfg)])
    assert calls[0][0] == "plain" and calls[0][1]["startupinfo"] == "hidden-start"
    assert calls[1] == ("offscreen", {})


def test_dolphin_capture_session_switches_backend_on_the_command_line_only(tmp_path, monkeypatch):
    exe = tmp_path / "Dolphin-x64" / "gBox Dolphin.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    ad = adapters.DolphinWinAdapter.__new__(adapters.DolphinWinAdapter)
    ad.port = 2345
    monkeypatch.setattr(ad, "_exe", lambda: exe, raising=False)
    monkeypatch.setattr(ad, "_gecko_setup", lambda user, rom: None, raising=False)
    argv = ad._argv("game.iso")
    assert "Dolphin.Core.GFXBackend=Vulkan" in argv          # normal play defaults to Vulkan (D3D12 renderer hung: #1806/#1933)
    ad.capture_backend = cb.plan("dolphin")
    argv = ad._argv("game.iso")
    assert "Dolphin.Core.GFXBackend=Vulkan" in argv and "Dolphin.Core.GFXBackend=D3D12" not in argv
    assert not (exe.parent / "User" / "Config" / "Dolphin.ini").exists()      # nothing written into Dolphin's config


@pytest.mark.parametrize("text,expect", [
    ("", "Video:\n  Renderer: Vulkan\n"),
    ("Video:\n  Resolution Scale: 300\n", "Video:\n  Resolution Scale: 300\n  Renderer: Vulkan\n"),
    ("Video:\n  Renderer: OpenGL\n  MSAA: Auto\nCore:\n  PPU Decoder: LLVM\n",
     "Video:\n  Renderer: Vulkan\n  MSAA: Auto\nCore:\n  PPU Decoder: LLVM\n"),
    ("Core:\n  PPU Decoder: LLVM\nVideo:\n  MSAA: Auto\nAudio:\n  Renderer: XAudio2\n",
     "Core:\n  PPU Decoder: LLVM\nVideo:\n  MSAA: Auto\n  Renderer: Vulkan\nAudio:\n  Renderer: XAudio2\n"),
])
def test_rpcs3_capture_config_sets_vulkan(text, expect):
    assert cb.rpcs3_renderer_yaml(text) == expect


def test_yuzu_backend_from_qt_config(tmp_path):
    ini = tmp_path / "qt-config.ini"
    assert cb.yuzu_backend(ini) is None
    ini.write_text("[Renderer]\nbackend\\default=false\nbackend=0\n[UI]\nbackend=1\n")
    assert cb.yuzu_backend(ini) == "opengl"
    ini.write_text("[Renderer]\nbackend\\default=true\nbackend=1\n")
    assert cb.yuzu_backend(ini) == "vulkan"
    ini.write_text("[UI]\nx=1\n")
    assert cb.yuzu_backend(ini) == "vulkan"                    # unset: Yuzu's default


def test_launch_capture_plan_provisions_renderdoc_and_honours_explicit_driver(monkeypatch, tmp_path):
    from gbox import tools
    monkeypatch.setattr(tools, "HOST_OS", "windows")
    monkeypatch.setattr(scene, "renderdoc_dir", lambda provision=False: provision and tmp_path)
    ctx = SimpleNamespace(progress=lambda pct, msg: None)
    ad = SimpleNamespace(name="retroarch", cfg=SimpleNamespace(core="flycast"))
    g = SimpleNamespace(core=None)
    p = tools._capture_plan(ad, g, "auto", ctx)
    assert (p["driver"], p["attach"], p["renderdoc"]) == ("vulkan", "layer", str(tmp_path))
    p = tools._capture_plan(ad, g, "glcore", ctx)
    assert (p["driver"], p["attach"], p["ra_cfg"]) == ("glcore", "inject", {"video_driver": "glcore"})
    with pytest.raises(tools.Unsupported, match="2D frame only"):
        tools._capture_plan(SimpleNamespace(name="retroarch", cfg=SimpleNamespace(core="snes9x")), g, "auto", ctx)


def test_capture_launch_input_fields():
    from gbox import tools
    fields = tools.LaunchIn.model_fields
    assert fields["capture_backend"].default == "" and fields["capture_for"].default == ""
    assert "relay" in scene.SceneIn.model_fields
