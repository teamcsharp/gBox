"""Adapter contract tests. RetroArch is exercised against a local fake of its UDP command protocol."""
import shutil
import socket
import threading

import pytest

from gbox import adapters
from gbox.config import Config, EmulatorConfig
from gbox.registry import Ctx, ToolUnavailable, Unsupported, execute


class FakeRetroArch(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", 0))
        self.port, self.mem, self.paused, self.log = self.s.getsockname()[1], bytearray(range(256)) * 4, False, []
        self.no_map = False                      # Flycast-like: no libretro memory map, only the achievements RAM view

    def run(self):
        while True:
            data, addr = self.s.recvfrom(65536)
            cmd = data.decode().split()
            self.log.append(cmd[0])
            if cmd[0] == "GET_STATUS":
                self.s.sendto(f"GET_STATUS {'PAUSED' if self.paused else 'PLAYING'} dreamcast,PSO,crc32=0".encode(), addr)
            elif cmd[0] == "PAUSE_TOGGLE":
                self.paused = not self.paused
            elif cmd[0] in ("READ_CORE_MEMORY", "WRITE_CORE_MEMORY") and self.no_map:
                self.s.sendto(f"{cmd[0]} {cmd[1]} -1 no memory map defined".encode(), addr)
            elif cmd[0] == "READ_CORE_RAM":
                a, n = int(cmd[1], 16), int(cmd[2])
                self.s.sendto((f"READ_CORE_RAM {cmd[1]} " + " ".join(f"{b:02X}" for b in self.mem[a:a + n])).encode(), addr)
            elif cmd[0] == "WRITE_CORE_RAM":
                a, bs = int(cmd[1], 16), bytes(int(x, 16) for x in cmd[2:])
                self.mem[a:a + len(bs)] = bs
            elif cmd[0] == "READ_CORE_MEMORY":
                a, n = int(cmd[1], 16), int(cmd[2])
                if a + n > len(self.mem):
                    self.s.sendto(f"READ_CORE_MEMORY {cmd[1]} -1 no memory map".encode(), addr)
                else:
                    self.s.sendto((f"READ_CORE_MEMORY {cmd[1]} " + " ".join(f"{b:02x}" for b in self.mem[a:a + n])).encode(), addr)
            elif cmd[0] == "WRITE_CORE_MEMORY":
                a, bs = int(cmd[1], 16), bytes(int(x, 16) for x in cmd[2:])
                self.mem[a:a + len(bs)] = bs
                self.s.sendto(f"WRITE_CORE_MEMORY {cmd[1]} {len(bs)}".encode(), addr)


class DeferredToggleRetroArch(FakeRetroArch):
    """Like RetroArch itself: PAUSE_TOGGLE is a virtual hotkey press applied after the command poll that received it,
    so a status read in that same poll still reports the previous state (#1123)."""

    def run(self):
        pending = False
        while True:
            data, addr = self.s.recvfrom(65536)
            cmd = data.decode().split()[0]
            self.log.append(cmd)
            if cmd == "GET_STATUS":
                shown = self.paused
                if pending:
                    self.paused, pending = not self.paused, False
                self.s.sendto(f"GET_STATUS {'PAUSED' if shown else 'PLAYING'} dreamcast,PSO,crc32=0".encode(), addr)
            elif cmd == "PAUSE_TOGGLE":
                pending = True


@pytest.fixture
def ra():
    fake = FakeRetroArch()
    fake.start()
    return fake, adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"), port=fake.port)


def test_retroarch_protocol(ra):
    fake, ad = ra
    assert ad.read_memory(0x10, 600) == bytes(fake.mem[0x10:0x10 + 600])     # chunked over several datagrams
    assert ad.write_memory(4, b"\xde\xad") == {"written": 2, "via": "core_memory_map"} and fake.mem[4:6] == b"\xde\xad"
    assert ad.pause()["state"] == "PAUSED" and fake.paused
    assert ad.pause()["state"] == "PAUSED" and fake.paused  # actual state, not just returned labels
    assert ad.resume()["state"] == "PLAYING" and not fake.paused
    assert fake.log.count("PAUSE_TOGGLE") == 2
    with pytest.raises(RuntimeError, match="no memory map"):
        ad.read_memory(2000, 100)


def test_retroarch_pause_resume_keeps_native_state_idempotent(ra):
    """An existing pause/resume state must survive repeated calls and resetting a playing game."""
    fake, ad = ra
    fake.log.clear()
    ad.pause()
    assert fake.paused
    ad.pause()
    assert fake.paused
    ad.resume()
    assert not fake.paused
    ad.resume()
    assert not fake.paused
    assert fake.log.count("PAUSE_TOGGLE") == 2
    ad.reset()
    assert not fake.paused
    assert fake.log.count("PAUSE_TOGGLE") == 2


def test_ram_fallback_and_address_translation(ra):
    fake, ad = ra
    fake.no_map, ad.platform = True, "dreamcast"
    assert ad.read_memory(0x8C000010, 8) == bytes(fake.mem[0x10:0x18])       # P1 mirror -> RAM offset
    assert ad.read_memory(0x0C000020, 4) == bytes(fake.mem[0x20:0x24])       # physical address
    assert ad.read_memory(0x30, 4) == bytes(fake.mem[0x30:0x34])             # plain offset passes through
    r = ad.write_memory(0xAC000040, b"4")                             # P2 mirror, verified by read-back
    assert r == {"written": 2, "via": "core_ram", "verified": True} and fake.mem[0x40:0x42] == b"4"
    ad.platform = "gamecube"
    assert ad._ram_offset(0x80001234) == 0x1234 and ad._ram_offset(0xC0001234) == 0x1234


def test_capability_discovery():
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"))
    caps = ad.get_capabilities()
    assert set(caps) == set(adapters.OPS) and caps["read_memory"] == "supported" and caps["get_audio"] == "unsupported"
    with pytest.raises(Unsupported):
        ad.get_audio()
    assert adapters.SteamAdapter().get_capabilities()["stop_game"] == "unsupported"


def test_unconfigured_platform_explicit():
    with pytest.raises(ToolUnavailable, match="no emulator configured"):
        adapters.for_platform("dreamcast", Config())


def test_switch_uses_native_yuzu_on_windows():
    if adapters.HOST_OS != "windows":
        pytest.skip("Yuzu is a Windows adapter")
    ad = adapters.for_game({"platform": "switch", "launch": {"kind": "attract"}}, Config())
    assert isinstance(ad, adapters.YuzuAdapter)
    assert ad.get_capabilities()["pause"] == "supported"


def test_windows_dolphin_can_scroll_with_c_stick(monkeypatch):
    ad = adapters.DolphinWinAdapter(Config(), "gamecube")
    ad.proc = type("Proc", (), {"pid": 123})()
    sent = []
    monkeypatch.setattr(adapters, "win_send_keys", lambda pid, events: sent.extend(events) or {"sent": len(events)})
    assert "Keyboard Mouse:I" in ad.PAD_INI_WIN
    assert ad.send_input([{"key": "cdown", "down": True}, {"key": "cdown", "down": False},
                          {"key": "a", "down": True}]) == {"sent": 3}
    assert sent == [{"key": "i", "down": True}, {"key": "i", "down": False},
                    {"key": "a", "down": True}]


def test_windows_dolphin_launches_vulkan_not_d3d12(tmp_path, monkeypatch):
    from gbox import game_audio
    ad = adapters.DolphinWinAdapter(Config(), "gamecube")
    exe = tmp_path / "Dolphin.exe"
    exe.write_bytes(b"x")
    monkeypatch.setattr(ad, "_exe", lambda: exe)
    monkeypatch.setattr(ad, "_claim_lane", lambda: "F13")
    monkeypatch.setattr(ad, "_gecko_setup", lambda user, rom: None)
    monkeypatch.setattr(adapters, "_audio_selection", lambda ad, wait_s=1.0: {})
    monkeypatch.setattr(game_audio, "dolphin_backend", lambda sel: "Cubeb")
    argv = ad._argv("rom.iso")
    assert "Dolphin.Core.GFXBackend=Vulkan" in argv
    assert not any("D3D12" in a for a in argv)
    # an agent-owned capture session keeps Vulkan and mutes audio (RenderDoc's layer captures it off-screen)
    ad.capture_backend = {"driver": "vulkan", "attach": "layer"}
    argv2 = ad._argv("rom.iso")
    assert "Dolphin.Core.GFXBackend=Vulkan" in argv2
    assert "Dolphin.DSP.Backend=No Audio Output" in argv2


def test_graphics_panel_uses_active_emulator(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from gbox import graphics, tools
    from gbox.registry import REGISTRY

    monkeypatch.setattr(graphics, "gpu", lambda: {"name": "Test GPU", "vram_mb": 8192})
    sid = "worker-session"
    monkeypatch.setitem(tools.SESSIONS, sid, (SimpleNamespace(name="yuzu"), {"game_id": "switch-game"}))
    ctx = Ctx(Config(data_dir=tmp_path))
    run = REGISTRY["graphics"].fn
    result = run(tools.GraphicsIn(game_id="switch-game", session_id=sid), ctx)["result"]
    assert result["emulator"] == "yuzu" and result["choices"] == {} and result["prefs"] == {}
    assert "RPCS3" not in result["notes"]
    with pytest.raises(Unsupported, match="does not yet control yuzu"):
        run(tools.GraphicsIn(game_id="switch-game", session_id=sid, op="set", prefs={"res_scale": 200}), ctx)

    monkeypatch.setitem(tools.SESSIONS, sid, (SimpleNamespace(name="rpcs3"), {"game_id": "ps3-game"}))
    result = run(tools.GraphicsIn(game_id="ps3-game", session_id=sid), ctx)["result"]
    assert set(result["choices"]) == {"res_scale", "msaa", "aniso", "upscaler", "sharpen"}
    assert "post_aa" not in result["choices"] and "vsync" not in result["choices"]


def test_command_adapter_missing_exe():
    with pytest.raises(ToolUnavailable):
        adapters.CommandAdapter(EmulatorConfig(adapter="command", executable="definitely-not-here.exe")).launch_game("r")


def test_command_adapter_lifecycle(tmp_path):
    import sys
    ad = adapters.CommandAdapter(EmulatorConfig(adapter="command", executable=sys.executable,
                                                args=["-c", "import time,sys; time.sleep(30)", "{rom}"]))
    ad.launch_game("rom.bin")
    assert ad.query_runtime()["running"]
    ad.stop_game()
    assert not ad.query_runtime()["running"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.skipif(adapters.HOST_OS != "windows", reason="x11grab display not available in headless cron")
def test_get_frame_real_capture(tmp_path):
    from gbox.registry import REGISTRY
    ctx = Ctx(Config(data_dir=tmp_path))
    out = execute("get_frame", {"region": [0, 0, 32, 24]}, ctx)
    arts = {n: d for n, d, _, _ in ctx.artifacts}
    t = REGISTRY["get_frame"]
    assert (out["width"], out["height"]) == (32, 24)
    assert t.validate(t.Out.model_validate(out), arts) == []


def test_retroarch_pause_reports_the_state_its_toggle_produces():
    """#1123: a status read sent straight behind PAUSE_TOGGLE is stale; pause/resume wait for an observed new state,
    stay idempotent and never send a blind toggle."""
    fake = DeferredToggleRetroArch()
    fake.start()
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"), port=fake.port)
    assert ad.pause()["state"] == "PAUSED" and fake.paused
    assert fake.log == ["GET_STATUS", "PAUSE_TOGGLE", "GET_STATUS", "GET_STATUS"]
    assert ad.pause()["state"] == "PAUSED" and fake.paused and fake.log.count("PAUSE_TOGGLE") == 1
    assert ad.resume()["state"] == "PLAYING" and not fake.paused and fake.log.count("PAUSE_TOGGLE") == 2
    assert ad.resume()["content"] == "dreamcast,PSO,crc32=0" and not fake.paused and fake.log.count("PAUSE_TOGGLE") == 2


def test_retroarch_pause_never_claims_an_unconfirmed_transition(monkeypatch):
    ad = adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"))
    sent = []
    monkeypatch.setattr(ad, "query_runtime", lambda: {"state": "PLAYING"})
    monkeypatch.setattr(ad, "cmd", lambda *args, **kwargs: sent.append(args))
    monkeypatch.setattr(adapters.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="did not confirm pause"):
        ad.pause()
    assert len(sent) == 1


@pytest.mark.parametrize("reference", ["../escape.bin", "sub/escape.bin", r"sub\escape.bin", "C:escape.bin"])
def test_gd_list_links_cannot_escape_staging(tmp_path, reference):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "data.bin").write_bytes(b"original")
    lst = stage / "game.lst"
    lst.write_text('1 0 4 2352 "' + reference + '" 0\n')
    with pytest.raises(ValueError, match="sibling filename"):
        adapters._link_lst_names(lst)
    assert sorted(p.name for p in stage.iterdir()) == ["data.bin", "game.lst"]
    assert not (tmp_path / "escape.bin").exists()


def test_gd_list_repairs_a_missing_sibling_name(tmp_path):
    (tmp_path / "data.bin").write_bytes(b"original")
    lst = tmp_path / "game.lst"
    lst.write_text('1 0 4 2352 "expected.bin" 0\n')
    assert adapters._link_lst_names(lst) == ["expected.bin"]
    assert (tmp_path / "expected.bin").read_bytes() == b"original"
    assert adapters._link_lst_names(lst) == []


def test_windows_dolphin_dpad_reaches_the_game(monkeypatch):
    # RE4's menus read the D-pad: on Windows it had no key, every menu press was dropped and the i9-NUC bot sat on the
    # main menu (2026-10-22)
    ad = adapters.DolphinWinAdapter(Config(), "gamecube")
    ad.proc = type("Proc", (), {"pid": 123})()
    sent = []
    monkeypatch.setattr(adapters, "win_send_keys", lambda pid, events: sent.extend(events) or {"sent": len(events)})
    for key in ("T", "G", "F", "H"):
        assert f"Keyboard Mouse:{key}`" in ad.PAD_INI_WIN
    ad.send_input([{"key": k, "down": True} for k in ("dup", "ddown", "dleft", "dright")])
    assert [e["key"] for e in sent] == ["t", "g", "f", "h"]
    assert all(adapters._SCAN.get(e["key"]) for e in sent)        # each one has a scan code: nothing is skipped
