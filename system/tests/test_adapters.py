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


@pytest.fixture
def ra():
    fake = FakeRetroArch()
    fake.start()
    return fake, adapters.RetroArchAdapter(EmulatorConfig(adapter="retroarch", executable="x", core="y"), port=fake.port)


def test_retroarch_protocol(ra):
    fake, ad = ra
    assert ad.read_memory(0x10, 600) == bytes(fake.mem[0x10:0x10 + 600])     # chunked over several datagrams
    assert ad.write_memory(4, b"\xde\xad") == {"written": 2, "via": "core_memory_map"} and fake.mem[4:6] == b"\xde\xad"
    assert ad.pause()["state"] == "PAUSED" and ad.pause()["state"] == "PAUSED"   # idempotent
    assert ad.resume()["state"] == "PLAYING"
    with pytest.raises(RuntimeError, match="no memory map"):
        ad.read_memory(2000, 100)


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
def test_get_frame_real_capture(tmp_path):
    from gbox.registry import REGISTRY
    ctx = Ctx(Config(data_dir=tmp_path))
    out = execute("get_frame", {"region": [0, 0, 32, 24]}, ctx)
    arts = {n: d for n, d, _, _ in ctx.artifacts}
    t = REGISTRY["get_frame"]
    assert (out["width"], out["height"]) == (32, 24)
    assert t.validate(t.Out.model_validate(out), arts) == []
