import ctypes
import io
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import adapters, shadps4
from gbox.config import Config, EmulatorConfig
from gbox.registry import ToolUnavailable, Unsupported


@pytest.fixture
def ad(tmp_path, monkeypatch):
    monkeypatch.setattr(shadps4, "HOST_OS", "windows")
    monkeypatch.setattr(shadps4.platform, "machine", lambda: "AMD64")
    return shadps4.ShadPS4Adapter(Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache"))


class FakeMemory:
    def __init__(self):
        self.base = 0x100000020
        self.data = bytearray(b"abcdefgh")
        self.writable = True
        self.writes = []

    def query(self, address):
        if address < self.base:
            return dict(start=0, size=self.base, readable=False, writable=False)
        if address < self.base + 8:
            return dict(start=self.base, size=8, readable=True, writable=self.writable)
        return None

    def read(self, address, length):
        offset = address - self.base
        return bytes(self.data[offset:offset + length])

    def write(self, address, data):
        self.writes.append((address, data))
        offset = address - self.base
        self.data[offset:offset + len(data)] = data


def running(ad):
    ad.proc = SimpleNamespace(pid=123, poll=lambda: None)
    ad._memory = FakeMemory()
    return ad._memory


def test_factory_separate_from_ps3_and_rejects_other_adapter(ad, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    assert isinstance(adapters.for_game({"platform": "ps4"}, ad.config), shadps4.ShadPS4Adapter)
    ad.config.emulators["ps4"] = EmulatorConfig(adapter="command", executable="wrong")
    with pytest.raises(ToolUnavailable, match="adapter='shadps4'"):
        adapters.for_game({"platform": "ps4"}, ad.config)


def test_non_windows_worker_is_not_claimed(ad, monkeypatch):
    monkeypatch.setattr(shadps4, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows x64"):
        shadps4.ShadPS4Adapter(ad.config)


def test_command_preserves_spaces_without_shell(ad):
    ad.cfg.args = ["--show-fps"]
    assert ad.argv(Path("C:/emulator tools/shadPS4.exe"), Path("C:/my games/RE5/eboot.bin")) == [
        str(Path("C:/emulator tools/shadPS4.exe")), "--show-fps", "--fullscreen", "false", "-g",
        str(Path("C:/my games/RE5/eboot.bin"))]
    ad.cfg.args = ["--game", "other.bin"]
    with pytest.raises(ValueError):
        ad.argv(Path("core.exe"), Path("eboot.bin"))


def test_package_and_non_ps4_rejected_before_process_spawn(tmp_path):
    pkg = tmp_path / "RE5.pkg"
    pkg.write_bytes(b"incomplete")
    with pytest.raises(ToolUnavailable, match="installation/extraction"):
        shadps4.boot_path(str(pkg))
    exe = tmp_path / "EBOOT.BIN"
    exe.write_bytes(b"PS3")
    with pytest.raises(ToolUnavailable, match="valid"):
        shadps4.boot_path(str(exe))


def test_explicit_executable_is_not_silently_replaced(ad, tmp_path):
    exe = tmp_path / "shadPS4.exe"
    exe.write_bytes(b"test")
    ad.config.emulators["ps4"] = EmulatorConfig(adapter="shadps4", executable=str(exe))
    assert shadps4.executable(ad.config) == exe
    exe.unlink()
    with pytest.raises(ToolUnavailable, match="not installed"):
        shadps4.executable(ad.config)


def test_ipc_handshake_and_controls(ad, tmp_path):
    pipe = io.StringIO()
    ad.proc = SimpleNamespace(stdin=pipe, poll=lambda: None)
    ad.log_path = tmp_path / "ipc.log"
    assert ad.get_capabilities()["pause"] == "unsupported"
    ad._consume_output(io.StringIO("boot log\n;#IPC_ENABLED\n;ENABLE_EMU_CONTROL\n;#IPC_END\n"), ipc=True)
    assert pipe.getvalue() == "RUN\nSTART\n"
    assert ad._ipc_ready.is_set()
    assert ad.get_capabilities()["pause"] == "supported"
    assert ad.pause()["status"] == "requested"
    assert ad.resume()["paused"] is False
    assert pipe.getvalue().endswith("PAUSE\nRESUME\n")


def test_missing_ipc_never_claims_pause_or_save_states(ad):
    with pytest.raises(Unsupported, match="did not advertise"):
        ad.pause()
    caps = ad.get_capabilities()
    for op in ("pause", "resume", "save_state", "load_state", "step_frames", "set_breakpoint", "rewind"):
        assert caps[op] == "unsupported"


def test_old_output_cannot_start_or_change_new_process(ad, tmp_path):
    old = SimpleNamespace(stdin=io.StringIO(), poll=lambda: 0)
    current = SimpleNamespace(stdin=io.StringIO(), poll=lambda: None)
    ad.proc = current
    log = tmp_path / "old.log"
    ad._consume_output(io.StringIO(";#IPC_ENABLED\n;ENABLE_EMU_CONTROL\n;#IPC_END\n"),
                       ipc=True, proc=old, log_path=log)
    assert current.stdin.getvalue() == ""
    assert not ad.ipc and not ad._ipc_ready.is_set()


def test_broken_stop_pipe_still_cleans_up_process(ad, monkeypatch):
    class BrokenPipe:
        def write(self, _):
            raise BrokenPipeError("already closed")
        def close(self):
            raise BrokenPipeError("already closed")
    ad.proc = SimpleNamespace(stdin=BrokenPipe(), poll=lambda: None, returncode=None)
    ad.ipc = True
    def kill(proc):
        proc.poll = lambda: 0
    monkeypatch.setattr(adapters, "_kill_tree", kill)
    assert ad.stop_game()["returncode"] == 0


def test_memory_64_bit_read_write_and_map_scope(ad):
    mem = running(ad)
    assert ad.read_memory(mem.base, 4) == b"abcd"
    result = ad.write_memory(mem.base + 1, b"XY")
    assert result["before_hex"] == b"bc".hex()
    assert result["verified"] is True
    assert mem.data == b"aXYdefgh"
    info = ad.query_memory_map()
    assert info["scope"] == "process_virtual"
    assert info["pointer_size"] == 8
    assert info["regions"][0]["start"] == hex(mem.base)
    assert ad.regions() == [(mem.base, 8)]


@pytest.mark.parametrize("address,length", [(-1, 4), (True, 4), (0, 0), (0, -1),
                                            (0, shadps4.MAX_TRANSFER + 1), (shadps4.MAX_ADDRESS - 1, 2)])
def test_bad_memory_requests_fail_before_access(ad, address, length):
    running(ad)
    with pytest.raises(ValueError):
        ad.read_memory(address, length)


def test_memory_boundaries_and_read_only_pages(ad):
    mem = running(ad)
    with pytest.raises(ValueError):
        ad.read_memory(mem.base + 6, 4)
    mem.writable = False
    with pytest.raises(ValueError, match="not writable"):
        ad.write_memory(mem.base, b"x")
    assert mem.writes == []


def test_changed_readback_is_not_success(ad, monkeypatch):
    mem = running(ad)
    monkeypatch.setattr(mem, "write", lambda *args: None)
    with pytest.raises(RuntimeError, match="could not be verified"):
        ad.write_memory(mem.base, b"x")


def test_stopped_session_cannot_reuse_handle(ad):
    running(ad)
    ad.proc.poll = lambda: 1
    with pytest.raises(RuntimeError, match="not running"):
        ad.read_memory(0x100000020, 4)


def test_input_is_named_validated_and_window_targeted(ad, monkeypatch):
    calls = []
    monkeypatch.setattr(ad, "_window", lambda: 456)
    monkeypatch.setattr(adapters.RPCS3Adapter, "_post_key", lambda *args: calls.append(args))
    monkeypatch.setattr(shadps4.time, "sleep", lambda _: None)
    assert ad.send_input([{"key": "b"}, {"key": "b", "down": False}])["sent"] == 2
    assert calls == [(456, ord("N"), True, False), (456, ord("N"), False, False)]
    with pytest.raises(Unsupported):
        ad.send_input([{"key": "cross"}, {"key": "cross", "player": 2}])
    assert len(calls) == 2  # whole batch validated before sending


def test_launch_failure_closes_process(ad, tmp_path, monkeypatch):
    eboot = tmp_path / "eboot.bin"
    eboot.write_bytes(b"fixture")
    monkeypatch.setattr(shadps4, "boot_path", lambda _: eboot)
    monkeypatch.setattr(shadps4, "executable", lambda _: Path(sys.executable))
    monkeypatch.setattr(ad, "argv", lambda *_: [sys.executable, "-c", "print('boot failed'); raise SystemExit(7)"])
    monkeypatch.setattr(adapters, "_pid_window", lambda _: None)
    ad.boot_timeout_s = 5
    with pytest.raises(RuntimeError, match="exited 7"):
        ad.launch_game(str(eboot))
    assert ad.proc.poll() == 7
    assert ad.proc.stdin.closed


def test_startup_accepts_owned_minimized_window_without_accepting_hidden_or_foreign(ad):
    running(ad)
    # The normal capture selector intentionally rejects iconic/minimized windows.
    # Startup must still publish the PID so the desktop can restore and dock it.
    owners, visible = {11: 123, 22: 456, 33: 123}, {11: False, 22: True, 33: True}
    class User32:
        def EnumWindows(self, callback, value):
            for window in owners:
                callback(window, value)

        def GetWindowThreadProcessId(self, window, owner):
            owner._obj.value = owners[window]

        def IsWindowVisible(self, window):
            return visible[window]

        def IsIconic(self, window):
            raise AssertionError("startup must not reject an owned minimized window")

    assert ad._startup_window(User32()) == 33
    visible[33] = False
    assert ad._startup_window(User32()) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 ABI and real process memory")
def test_real_win64_process_memory_reads_and_writes_own_buffer():
    # Exercise actual ctypes signatures using only a buffer owned by this test.
    buffer = ctypes.create_string_buffer(b"original")
    mem = shadps4.ProcessMemory(os.getpid())
    try:
        address = ctypes.addressof(buffer)
        assert mem.query(address)["writable"]
        assert mem.read(address, 8) == b"original"
        mem.write(address, b"modified")
        assert buffer.raw[:8] == b"modified"
    finally:
        mem.close()
    assert mem.handle is None


def test_ps4_map_rpc_and_reader_use_process_memory(ad, monkeypatch):
    from gbox import tools, ram_reader
    mem = running(ad)
    monkeypatch.setitem(tools.SESSIONS, "ps4-test", (ad, {"platform": "ps4"}))
    assert tools.session_rpc("ps4-test", "query_memory_map", {})["scope"] == "process_virtual"
    reader = ram_reader.AdapterReader(ad)
    assert reader.kind == "procmem"
    assert reader.read(mem.base, 4) == b"abcd"


def test_ps4_search_requires_bounded_explicit_range(ad, monkeypatch):
    from gbox import tools
    mem = running(ad)
    monkeypatch.setitem(tools.SESSIONS, "ps4-test", (ad, {"platform": "ps4"}))
    monkeypatch.setattr(tools, "MSEARCH", {})
    for ranges in ([], [[mem.base, 17 << 20]], [[mem.base, 0]], [[-1, 10]], [[0]]):
        with pytest.raises(ValueError):
            tools.memory_search(tools.MemSearchIn(session_id="ps4-test", ranges=ranges), None)
    result = tools.memory_search(tools.MemSearchIn(session_id="ps4-test", type="u8", value=ord("c"),
                                                  ranges=[[mem.base, 8]]), None)
    assert result["result"]["candidates"] == 1


def test_ps4_package_launch_refused_without_touching_context():
    from gbox import tools
    from gbox.models import CatalogEntry
    game = CatalogEntry(game_id="pkg", title="RE5", platform="ps4", launch={"kind": "ps4_package"},
                        source_paths=["RE5.pkg"], format="ps4_pkg", profile_id="pkg")
    with pytest.raises(ToolUnavailable, match="not installed"):
        tools._launch_game(tools.LaunchIn(game=game), None)


@pytest.mark.parametrize("node,debug,kind,status", [
    ("auto", False, "emulator", 200),
    ("linux", False, "emulator", 409),
    ("auto", True, "emulator", 409),
    ("auto", False, "ps4_package", 409),
])
def test_ps4_launch_api_routes_and_refuses_packages(tmp_path, node, debug, kind, status):
    from fastapi.testclient import TestClient
    from gbox.server import create_app
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    app.state.store.upsert_catalog([{"game_id": "ps4", "title": "Resident Evil 5", "platform": "ps4",
                                    "source_paths": ["test/eboot.bin"], "core": None,
                                    "format": "ps4_folder", "profile_id": "ps4",
                                    "launch": {"kind": kind, "path": "test/eboot.bin"}}])
    with TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"}) as client:
        response = client.post("/api/games/ps4/launch", params={"node": node, "debug": debug})
    assert response.status_code == status, response.text
    if status == 200:
        assert response.json()["require_os"] == "windows"
    else:
        assert not app.state.store.all("job")
