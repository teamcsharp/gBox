"""Switch sessions on a Linux node (the Spark): Eden on the session's Xvfb display (gbox.adapters.SwitchLinuxAdapter,
gbox.provision.ensure_switch_linux, gbox.eden_memory, gbox.switch_nsp). Built from Eden's sources, no live run yet:
docs/research/switch-emulator-spark.md."""
import struct
from types import SimpleNamespace

import pytest

from gbox import adapters, eden_memory, provision, switch_nsp
from gbox.config import Config, EmulatorConfig, Library
from gbox.registry import ToolUnavailable

# Eden's HostMemory arena as /proc/<pid>/maps shows it on an ARM64 host (NCE: direct addressing): the reservation is
# anonymous rw-p between 2^36 and 2^39, the guest's pages are memfd rows carved into it; unrelated rows around it.
ARM64_MAPS = [
    "aaaad0000000-aaaad0010000 r-xp 00000000 fe:01 1 /opt/eden/usr/bin/eden",
    "1200000000-1208000000 rw-p 00000000 00:00 0 ",
    "1208000000-1210000000 r-xp 00000000 00:01 123 /memfd:HostMemory (deleted)",
    "1210000000-1214000000 rw-p 08000000 00:01 123 /memfd:HostMemory (deleted)",
    "1214000000-5200000000 rw-p 00000000 00:00 0 ",
    "5200000000-5200001000 r--p 00000000 fe:01 2 /usr/lib/aarch64-linux-gnu/libc.so.6",
    "ffff80000000-ffff80021000 rw-p 00000000 00:00 0 ",
]
# A Dynarmic (JIT) host: the arena holds the guest's 39-bit space at an offset, the game's code at guest 0x8000000.
X86_MAPS = [
    "7f0000000000-7f0008000000 rw-p 00000000 00:00 0 ",
    "7f0008000000-7f000c000000 r-xp 00000000 00:01 9 /memfd:HostMemory (deleted)",
    "7f000c000000-7f8000000000 rw-p 00000000 00:00 0 ",
]


def cfg(tmp_path, **kw) -> Config:
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", **kw)


def switch_game() -> dict:
    return {"game_id": "52d15709be0fda1a", "platform": "switch", "title": "Resident Evil 5",
            "launch": {"kind": "emulator", "platform": "switch", "path": "/x/Resident Evil 5.nsp"}}


def build_nsp(path, names: list[str], payload: bytes = b"nca") -> str:
    """A tiny PFS0 container with these file names (the NCAs themselves are irrelevant here)."""
    table = b"".join(n.encode() + b"\0" for n in names)
    entries, offset, name_at = b"", 0, 0
    for n in names:
        entries += struct.pack("<QQII", offset, len(payload), name_at, 0)
        offset += len(payload)
        name_at += len(n) + 1
    path.write_bytes(struct.pack("<4sIII", b"PFS0", len(names), len(table), 0) + entries + table + payload * len(names))
    return str(path)


# --- routing and shape ------------------------------------------------------------------------------------------------

def test_linux_routes_switch_to_eden_and_windows_keeps_yuzu(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    ad = adapters.for_game(switch_game(), cfg(tmp_path), debug=True)
    assert isinstance(ad, adapters.SwitchLinuxAdapter) and ad.debug is True and ad.name == "eden"
    assert {"read_memory", "write_memory", "send_input", "stream_session", "get_frame", "pause"} <= ad.supported
    assert "save_state" not in ad.supported and ad.checkpoint_state is False      # Eden has no save states
    assert ad.screen == (1280, 720)
    env = ad.env                                                 # Eden's XDG folders are gBox's own, never ~/.local
    assert env["XDG_DATA_HOME"].startswith(str(tmp_path)) and env["XDG_CONFIG_HOME"].startswith(str(tmp_path))
    assert env["QT_QPA_PLATFORM"] == "xcb"                       # Eden documents Wayland as problematic
    assert ad.home == provision.switch_linux_dir(ad.config) and ad.home.name == "eden"
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    assert isinstance(adapters.for_game(switch_game(), cfg(tmp_path)), adapters.YuzuAdapter)


def test_keys_are_edens_default_keyboard_layout():
    from gbox.yuzu_runtime import SWITCH_KEYS
    assert adapters.SwitchLinuxAdapter.keys == SWITCH_KEYS
    assert adapters.SwitchLinuxAdapter.keys["a"] == "c" and adapters.SwitchLinuxAdapter.keys["lup"] == "w"


# --- the emulator and keys on this host -----------------------------------------------------------------------------------

def test_switch_exe_prefers_configured_apprun_then_binary_never_the_raw_appimage(tmp_path):
    folder = tmp_path / "eden-extracted"
    (folder / "squashfs-root").mkdir(parents=True)
    apprun = folder / "squashfs-root" / "AppRun"
    apprun.write_text("#!/bin/sh\n")
    c = cfg(tmp_path, emulators={"switch": EmulatorConfig(adapter="eden", executable=str(folder))})
    assert provision.switch_linux_exe(c) == apprun
    binary = tmp_path / "eden"
    binary.write_text("bin")
    assert provision.switch_linux_exe(cfg(tmp_path, switch_appimage=str(binary))) == binary
    img = tmp_path / "Eden-Linux-v0.2.1-aarch64-gcc-standard.AppImage"
    img.write_bytes(b"AI")
    c = cfg(tmp_path, switch_appimage=str(img))                 # an AppImage is extracted once, never run through FUSE
    assert provision.switch_linux_exe(c) == provision.switch_linux_home(c) / "squashfs-root" / "AppRun"
    assert provision.switch_appimage_source(c) == img
    assert provision.switch_linux_exe(cfg(tmp_path)) == provision.switch_linux_home(cfg(tmp_path)) / "squashfs-root" / "AppRun"


def test_ensure_extracts_the_appimage_once_and_copies_the_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    img = tmp_path / "Eden-Linux-v0.2.1-aarch64-gcc-standard.AppImage"
    img.write_bytes(b"AI")
    share = tmp_path / "share" / "_switch"
    share.mkdir(parents=True)
    (share / "prod.keys").write_text("header_key = 00\n")
    (share / "title.keys").write_text("x = y\n")
    c = cfg(tmp_path, switch_appimage=str(img), switch_keys=str(share / "prod.keys"))
    calls = []

    def extract(appimage, home):
        calls.append(appimage)
        (home / "squashfs-root").mkdir(parents=True, exist_ok=True)
        (home / "squashfs-root" / "AppRun").write_text("#!/bin/sh\n")
    monkeypatch.setattr(provision, "_rpcs3_appimage_extract", extract)
    r = provision.ensure_switch_linux(c)
    assert r["step"] == "eden" and r["status"] == "ok" and calls == [img]
    keys = provision.switch_linux_dir(c) / "keys"
    assert (keys / "prod.keys").read_text() == "header_key = 00\n" and (keys / "title.keys").read_text() == "x = y\n"
    assert "prod.keys, title.keys copied" in r["detail"]
    r2 = provision.ensure_switch_linux(c)                       # unchanged AppImage and keys: nothing redone
    assert calls == [img] and "copied" not in r2["detail"]
    (share / "prod.keys").write_text("header_key = 01\n")       # new keys on the share: copied again
    provision.ensure_switch_linux(c)
    assert (keys / "prod.keys").read_text() == "header_key = 01\n"


def test_ensure_names_what_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match=r"Eden-Linux-v0\.2\.1-\w+-gcc-standard\.AppImage .*switch_appimage"):
        provision.ensure_switch_linux(cfg(tmp_path))
    binary = tmp_path / "eden"
    binary.write_text("bin")
    with pytest.raises(ToolUnavailable, match="prod.keys"):
        provision.ensure_switch_linux(cfg(tmp_path, switch_appimage=str(binary)))
    monkeypatch.setattr(provision, "HOST_OS", "windows")
    with pytest.raises(ToolUnavailable, match="Linux nodes only"):
        provision.ensure_switch_linux(cfg(tmp_path))


def test_keys_default_to_the_switch_librarys_root(tmp_path):
    root = tmp_path / "_switch"
    root.mkdir()
    lib = Library(id="quickswap-switch", platform="switch", paths={provision.HOST_OS: str(root)})
    assert provision.switch_keys_source(cfg(tmp_path, libraries=[lib])) is None
    (root / "prod.keys").write_text("k")
    assert provision.switch_keys_source(cfg(tmp_path, libraries=[lib])) == root / "prod.keys"
    other = Library(id="gc", platform="gamecube", paths={provision.HOST_OS: str(root)})
    assert provision.switch_keys_source(cfg(tmp_path, libraries=[other])) is None   # only Switch libraries count
    assert provision.switch_keys_source(cfg(tmp_path, switch_keys=str(tmp_path / "none.keys"))) is None


# --- Eden's settings and command line -------------------------------------------------------------------------------------

def test_write_settings_owns_only_its_keys_and_marks_them_non_default(tmp_path):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.nce, ad.debug, ad.port = True, False, 43210
    path = provision.switch_linux_config(ad.config)
    path.parent.mkdir(parents=True)
    path.write_text("[Renderer]\nbackend=0\nbackend\\default=true\nresolution_setup=2\n\n[UI]\ntheme=dark\n")
    assert ad.write_settings() == path
    t = path.read_text()
    assert "backend=1\n" in t and "backend\\default=false\n" in t and "backend=0" not in t and "backend\\default=true" not in t
    assert "resolution_setup=2" in t and "theme=dark" in t      # the operator's other settings stay
    assert "[Cpu]\ncpu_backend=1\ncpu_backend\\default=false" in t and ad.address_mode == "direct"   # NCE for play
    assert "[Debugging]\nuse_gdbstub=false\nuse_gdbstub\\default=false\ngdbstub_port=43210\ngdbstub_port\\default=false" in t
    for line in ("firstStart=false", "confirmStop=2", "check_for_updates=false", "pauseWhenInBackground=false",
                 "use_multi_core=true"):
        assert f"{line}\n" in t and f"{line.split('=')[0]}\\default=false\n" in t
    # a debug launch: the GDB stub, and Dynarmic, because Eden's NCE backend has no breakpoints (offset addressing)
    ad.debug = True
    ad.write_settings()
    t = path.read_text()
    assert "use_gdbstub=true" in t and "use_gdbstub=false" not in t
    assert "cpu_backend=0" in t and "cpu_backend=1" not in t and ad.address_mode == "offset" and not ad.use_nce
    ad.debug, ad.nce = False, False                              # a host that cannot run NCE (x86_64, 64 KiB pages)
    ad.write_settings()
    assert "cpu_backend=0" in path.read_text() and ad.address_mode == "offset"
    before = path.read_text()
    ad.write_settings()                                          # idempotent
    assert path.read_text() == before


def test_re5_and_re6_get_single_core_in_edens_per_game_file(tmp_path):
    """Eden v0.2.1 loses the npad thread that moves itself to cores 1-2 at boot (svcBreak 0xE401 / SIGSEGV): RE5 and
    RE6 run single-core through Eden's per-game file; the global file keeps multi-core for every other game."""
    folder = tmp_path / "Resident Evil 5"
    folder.mkdir()
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.rom = build_nsp(folder / "Resident Evil 5.nsp", ["a.nca", "010018100cd460000000000000000003.tik"])
    ad.write_settings()
    custom = provision.switch_linux_config(ad.config).parent / "custom" / "010018100CD46000.ini"
    t = custom.read_text()
    assert "[Core]\n" in t and "use_multi_core\\use_global=false\n" in t and "use_multi_core\\default=false\n" in t
    assert adapters.ini_get(t, "Core", "use_multi_core") == "false"
    # single-core's cost, measured in a live No Mercy round: no stalls on first-time shader compiles
    assert adapters.ini_get(t, "Renderer", "use_asynchronous_shaders") == "true"
    assert adapters.ini_get(t, "Renderer", "async_presentation") == "true"
    assert adapters.ini_get(t, "Renderer", "async_presentation\\use_global") == "false"
    assert adapters.ini_get(t, "Renderer", "gpu_accuracy") is None          # Eden's default: Low inverted a frame
    assert ad.title_settings == {"Core": {"use_multi_core": "false"},
                                 "Renderer": {"use_asynchronous_shaders": "true", "async_presentation": "true"}}
    assert adapters.ini_get(provision.switch_linux_config(ad.config).read_text(), "Core", "use_multi_core") == "true"
    assert set(adapters.EDEN_TITLE_SETTINGS) >= {"010018100CD46000", "01002A000CD48000"}
    # Eden rewrites the file on every boot with its own lines; gBox keeps them and stays idempotent
    custom.write_text(t + "\n[Cpu]\ncpu_accuracy\\use_global=true\n")
    ad.write_settings()
    before = custom.read_text()
    assert "cpu_accuracy\\use_global=true" in before
    ad.write_settings()
    assert custom.read_text() == before
    # a game without overrides gets no per-game file
    other = tmp_path / "Zelda"
    other.mkdir()
    ad.rom = build_nsp(other / "Zelda.nsp", ["a.nca", "0100f2c0115b60000000000000000003.tik"])
    ad.write_settings()
    assert ad.title_settings == {} and not (custom.parent / "0100F2C0115B6000.ini").exists()


def test_a_dropped_title_override_goes_back_to_the_global_value(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    assert ad.write_title_settings("010018100cd46000") == adapters.EDEN_TITLE_SETTINGS["010018100CD46000"]
    monkeypatch.setattr(adapters, "EDEN_TITLE_SETTINGS", {"01002A000CD48000": {"Core": {"use_multi_core": "false"}}})
    assert ad.write_title_settings("010018100CD46000") == {}
    t = (provision.switch_linux_config(ad.config).parent / "custom" / "010018100CD46000.ini").read_text()
    assert adapters.ini_get(t, "Core", "use_multi_core\\use_global") == "true"
    assert ad.write_title_settings(None) == {} and ad.write_title_settings("") == {}


def test_an_update_beside_the_game_becomes_an_eden_content_folder(tmp_path):
    """RE6 boots with its v131072 update through Eden's external content folders (no NAND install); a game whose
    folder holds no update or DLC clears them."""
    re6 = tmp_path / "Resident Evil 6"
    re6.mkdir()
    base = build_nsp(re6 / "Resident Evil 6 [01002A000CD48000].nsp", ["a.nca", "01002a000cd480000000000000000003.tik"])
    build_nsp(re6 / "Resident Evil 6 [01002A000CD48800][v131072].nsp", ["b.nca"])
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.rom = base
    ini = ad.write_settings()
    t = ini.read_text()
    assert ad.content_dirs == [str(re6)]
    assert adapters.ini_get(t, "UI", "Paths\\external_content_dirs\\size") == "1"
    assert adapters.ini_get(t, "UI", "Paths\\external_content_dirs\\1\\path") == str(re6)
    assert ad.title_settings["Core"] == {"use_multi_core": "false"}
    re5 = tmp_path / "Resident Evil 5"
    re5.mkdir()
    ad.rom = build_nsp(re5 / "Resident Evil 5.nsp", ["a.nca", "010018100cd460000000000000000003.tik"])
    t = ad.write_settings().read_text()
    assert ad.content_dirs == [] and adapters.ini_get(t, "UI", "Paths\\external_content_dirs\\size") == "0"
    assert adapters.ini_get(t, "UI", "Paths\\external_content_dirs\\1\\path") is None
    assert t.count("[UI]") == 1


def test_eden_never_opens_a_host_browser_or_self_updates(tmp_path, monkeypatch):
    """RE5's first boot asks to open Capcom's privacy page: Eden's openUrl ran xdg-open, which opened the Spark user's
    Firefox on the session display. A no-op xdg-open goes first on Eden's PATH."""
    import os
    c = cfg(tmp_path)
    env = provision.switch_linux_env(c)
    stub = provision.switch_linux_stub_dir(c)
    assert env["PATH"].split(os.pathsep)[0] == str(stub)
    assert env["BROWSER"] == env["DEFAULT_BROWSER"] == str(stub / "xdg-open") and env["DISABLE_AUTO_UPDATES"] == "1"
    path = provision.switch_linux_url_stub(c)
    assert path == stub / "xdg-open" and path.read_text() == provision.SWITCH_URL_STUB
    assert path.read_text().startswith("#!/bin/sh\n") and "exit 0" in path.read_text()
    path.write_text("#!/bin/sh\nexec firefox \"$@\"\n")        # replaced when it changed
    provision.switch_linux_url_stub(c)
    assert path.read_text() == provision.SWITCH_URL_STUB
    ad = adapters.SwitchLinuxAdapter(c)
    assert ad.env["PATH"] == env["PATH"]


def test_argv_is_fullscreen_plus_game(tmp_path):
    binary = tmp_path / "eden"
    binary.write_text("bin")
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path, switch_appimage=str(binary)))
    assert ad._argv("/x/Resident Evil 5.nsp") == [str(binary), "-f", "-g", "/x/Resident Evil 5.nsp"]
    assert ad.rom == "/x/Resident Evil 5.nsp"


def test_nce_only_on_arm64_hosts_with_4k_pages():
    assert eden_memory.nce_capable("aarch64", 4096) and eden_memory.nce_capable("arm64", 4096)
    assert not eden_memory.nce_capable("x86_64", 4096) and not eden_memory.nce_capable("aarch64", 65536)
    assert eden_memory.mode_for(True) == "direct" and eden_memory.mode_for(False) == "offset"


# --- guest memory ------------------------------------------------------------------------------------------------------

def test_arena_is_the_reservation_around_the_hostmemory_rows():
    arena = eden_memory.guest_arena(ARM64_MAPS)
    assert (arena["lo"], arena["hi"], arena["base"]) == (0x1200000000, 0x5200000000, 0x1200000000)
    assert arena["mapped"] == [(0x1208000000, 0x1210000000, "r-xp"), (0x1210000000, 0x1214000000, "rw-p")]
    assert eden_memory.guest_arena(["5500000000-5500010000 r-xp 00000000 fe:01 1 /usr/bin/eden"]) is None
    x86 = eden_memory.guest_arena(X86_MAPS)
    assert (x86["lo"], x86["hi"]) == (0x7f0000000000, 0x7f8000000000)
    assert eden_memory.parse_maps(["garbage", "zz-yy r--p 0 0 0"]) == []


def test_host_addresses_direct_and_offset_and_refusals():
    arena = eden_memory.guest_arena(ARM64_MAPS)
    assert eden_memory.host_address(arena, 0x1208000010, "direct") == 0x1208000010
    assert eden_memory.mapped(arena, 0x1208000010, 16) and not eden_memory.mapped(arena, 0x1208000010, 16, "w")
    assert eden_memory.mapped(arena, 0x1208000010, 16, None)
    assert not eden_memory.mapped(arena, 0x1214000000, 4)        # inside the arena, no guest page there
    assert not eden_memory.mapped(arena, 0x120fffffff, 4)        # straddling a row's end
    with pytest.raises(ValueError, match="outside the guest arena"):
        eden_memory.host_address(arena, 0x8000000, "direct")
    with pytest.raises(ValueError, match="unknown address mode"):
        eden_memory.host_address(arena, 0x8000000, "jit")
    x86 = eden_memory.guest_arena(X86_MAPS)
    assert eden_memory.host_address(x86, 0x8000000, "offset") == 0x7f0008000000
    assert eden_memory.regions(x86, "offset") == [(0x8000000, 0x4000000)]
    assert eden_memory.regions(arena, "direct") == [(0x1208000000, 0xC000000)]   # adjacent rows merged


def test_read_and_write_memory_use_the_arena_and_refuse_unmapped(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.nce, ad.address_mode = True, "direct"
    ad.proc = SimpleNamespace(pid=77, poll=lambda: None)
    monkeypatch.setattr(adapters, "_proc_tree", lambda pid: [pid, 78])
    maps = {77: ["5500000000-5500010000 r-xp 00000000 fe:01 1 /opt/eden/AppRun"], 78: ARM64_MAPS}
    monkeypatch.setattr(ad, "_maps", lambda pid: maps[pid])
    store = bytearray(0x40)

    def rd(pid, host, n):
        assert pid == 78
        off = host - 0x1210000000
        return bytes(store[off:off + n])

    def wr(pid, host, data):
        off = host - 0x1210000000
        store[off:off + len(data)] = data
    monkeypatch.setattr(ad, "_read_host", rd)
    monkeypatch.setattr(ad, "_write_host", wr)
    assert ad.read_memory(0x1210000000, 4) == b"\0\0\0\0"
    out = ad.write_memory(0x1210000004, b"\x01\x02")
    assert out["verified"] and out["address_mode"] == "direct" and store[4:6] == b"\x01\x02"
    with pytest.raises(ValueError, match="not mapped"):
        ad.read_memory(0x1214000000, 4)                           # arena, but no guest page there
    with pytest.raises(ValueError, match="outside"):
        ad.read_memory(0x8000000, 4)
    assert ad.regions() == [(0x1208000000, 0xC000000)]
    rt = ad.query_runtime()
    assert rt["guest_arena"] == ["0x1200000000", "0x5200000000"] and rt["cpu_backend"] == "nce" and rt["running"]
    ad.proc = SimpleNamespace(pid=77, poll=lambda: 0)
    ad._mem, ad._mem_checked_at = None, -1e9
    with pytest.raises(RuntimeError, match="not running"):
        ad.read_memory(0x1210000000, 4)


# --- launch ------------------------------------------------------------------------------------------------------------

def _fake_launch(ad, monkeypatch, maps_stages, popen):
    from gbox import memory_card_sessions
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(ad, "_ensure", lambda: None)
    monkeypatch.setattr(adapters, "Display", lambda *a: SimpleNamespace(name=":99", w=1280, h=720, close=lambda: None))
    proc = SimpleNamespace(pid=501, poll=lambda: None)
    monkeypatch.setattr(adapters.subprocess, "Popen", lambda argv, **kw: popen.append((argv, kw)) or proc)
    monkeypatch.setattr(adapters, "_proc_tree", lambda pid: [pid])
    stages = iter(maps_stages)
    last = maps_stages[-1]
    monkeypatch.setattr(ad, "_maps", lambda pid: next(stages, last))
    monkeypatch.setattr(adapters.time, "sleep", lambda s: None)
    monkeypatch.setattr(memory_card_sessions, "launched", lambda ad: None)
    return proc


def test_launch_waits_for_guest_memory_then_parks_the_pointer(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.nce, ad.address_mode = True, "direct"
    popen, xdo = [], []
    _fake_launch(ad, monkeypatch, [["aaaad0000000-aaaad0010000 r-xp 00000000 fe:01 1 /opt/eden/usr/bin/eden"], ARM64_MAPS], popen)
    monkeypatch.setattr(ad, "_xdo", lambda *a: xdo.append(a))
    monkeypatch.setattr(ad, "_boot_watch", lambda: {"watched": True, "frames": 3, "after_s": 9.0})
    rom = build_nsp(tmp_path / "Resident Evil 5.nsp", ["010018100cd460000000000000000003.tik", "a.nca"])
    out = ad.launch_game(rom)
    assert out["boot_watch"]["watched"] and out["boot_attempts"] == 1 and out["boot_failures"] == []
    argv, kw = popen[0]
    assert argv[1:] == ["-f", "-g", rom]
    assert kw["env"]["DISPLAY"] == ":99" and kw["env"]["QT_QPA_PLATFORM"] == "xcb"
    assert kw["env"]["XDG_DATA_HOME"] == str(provision.switch_linux_home(ad.config) / "data")
    assert out["emulator"] == "eden (linux)" and out["ready"] == "guest_memory" and out["address_mode"] == "direct"
    assert out["guest_arena"] == ["0x1200000000", "0x5200000000"] and out["title_id"] == "010018100CD46000"
    assert out["debugger"] is False and out["display"] == ":99" and out["eden_log"].endswith("eden_log.txt")
    assert ("mousemove", "640", "360") in xdo                    # keys go to the window under the pointer
    assert ad.query_runtime()["running"] is True and "set_breakpoint" not in ad.supported


def test_launch_fails_with_the_log_when_no_guest_memory_appears(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.boot_timeout_s = 0.01
    popen, killed = [], []
    proc = _fake_launch(ad, monkeypatch, [["aaaad0000000-aaaad0010000 r-xp 00000000 fe:01 1 /opt/eden/usr/bin/eden"]], popen)
    monkeypatch.setattr(adapters, "_kill_tree", lambda p: killed.append(p))
    monkeypatch.setattr(ad, "_signal", lambda sig: 0)
    monkeypatch.setattr(ad, "_xdo", lambda *a: None)
    ad.eden_log().parent.mkdir(parents=True)
    ad.eden_log().write_text("[   0.123] Core <Error> Missing production keys: derivation failed\n")
    with pytest.raises(RuntimeError, match="did not map guest memory.*Missing production keys"):
        ad.launch_game(str(tmp_path / "Resident Evil 5.nsp"))
    assert killed == [proc]                                       # only this session's process is stopped


def test_launch_refuses_a_title_update_nsp(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    with pytest.raises(ToolUnavailable, match="title update.*01002A000CD48000"):
        ad.launch_game(str(tmp_path / "Resident Evil 6 [01002A000CD48800][v131072].nsp"))
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    with pytest.raises(ToolUnavailable, match="linux node"):
        ad.launch_game("/x/Resident Evil 5.nsp")


def test_send_input_types_only_switch_pad_names(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    sent = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: sent.append(list(a)))
    events = [{"key": "A", "down": True}, {"key": "lup", "down": True}, {"key": "cross", "down": True},
              {"key": "a", "down": False}]
    out = ad.send_input(events)
    assert out == {"sent": 3, "skipped": ["cross"]}
    assert sent == [["keydown", "c", "keydown", "w", "sleep", "0.06", "keyup", "c"]]
    assert events[0] == {"key": "A", "down": True}               # the caller's events are not rewritten


def test_pause_and_resume_signal_the_process_tree(tmp_path, monkeypatch):
    import signal
    monkeypatch.setattr(signal, "SIGSTOP", 19, raising=False)   # Linux numbers; a Windows test host has neither
    monkeypatch.setattr(signal, "SIGCONT", 18, raising=False)
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.proc = SimpleNamespace(pid=9, poll=lambda: None)
    monkeypatch.setattr(adapters, "_proc_tree", lambda pid: [9, 10])
    sent = []
    monkeypatch.setattr(adapters.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert ad.pause() == {"paused": True, "via": "SIGSTOP"} and ad.paused
    assert ad.resume() == {"paused": False} and not ad.paused
    assert sent == [(9, 19), (10, 19), (9, 18), (10, 18)]
    # Stop on a paused game continues it first (a stopped process would not act on SIGTERM), then ends only its tree
    monkeypatch.setattr(signal, "SIGTERM", 15, raising=False)
    killed = []
    monkeypatch.setattr(adapters, "_kill_tree", lambda p: killed.append(p))
    ad.pause()
    sent.clear()
    ad.stop_game()
    assert sent == [(9, 18), (10, 18), (9, 15), (10, 15)] and killed == [ad.proc] and not ad.paused


# --- NSP containers --------------------------------------------------------------------------------------------------------

def test_nsp_title_id_from_the_ticket_then_from_the_file_name(tmp_path):
    p = build_nsp(tmp_path / "Resident Evil 5.nsp",
                  ["0100aabbccdd0000.nca", "010018100cd460000000000000000003.tik", "010018100cd460000000000000000003.cert"])
    assert switch_nsp.title_id(p) == "010018100CD46000"
    names = switch_nsp.pfs0_names(p)
    assert names == ["0100aabbccdd0000.nca", "010018100cd460000000000000000003.tik", "010018100cd460000000000000000003.cert"]
    d = switch_nsp.describe(p)
    assert d["has_ticket"] and not d["is_update"] and d["base_title_id"] == "010018100CD46000" and d["ncas"] == ["0100aabbccdd0000.nca"]
    assert switch_nsp.launchable(p) == (True, "")
    assert switch_nsp.catalog_fields(p) == ("010018100CD46000", {"title_id": "010018100CD46000"})
    q = build_nsp(tmp_path / "Resident Evil 6 [01002A000CD48800][v131072].nsp", ["abc.nca"])
    assert switch_nsp.title_id(q) == "01002A000CD48800"          # no ticket: the file name's tag
    d = switch_nsp.describe(q)
    assert d["is_update"] and d["base_title_id"] == "01002A000CD48000" and d["version"] == 131072 and d["files"] == 1
    ok, why = switch_nsp.launchable(q)
    assert not ok and "title update (v131072)" in why and "01002A000CD48000" in why
    assert switch_nsp.catalog_fields(q) == ("01002A000CD48800", {"title_id": "01002A000CD48800", "title_update": True,
                                                                "base_title_id": "01002A000CD48000", "version": 131072})
    assert switch_nsp.title_id(tmp_path / "missing.nsp") is None and switch_nsp.catalog_fields(tmp_path / "x.nsp") == (None, {})
    (tmp_path / "junk.nsp").write_bytes(b"not a container at all")
    with pytest.raises(ValueError, match="not a PFS0"):
        switch_nsp.pfs0_names(tmp_path / "junk.nsp")
    assert switch_nsp.describe(tmp_path / "junk.nsp")["error"]
    # a dump with a cnmt.xml member and no ticket: the title id comes from the metadata, not the file name
    xml = b'<ContentMeta><Type>Application</Type><Id>0x010018100cd46000</Id><Version>0</Version></ContentMeta>'
    r = build_nsp(tmp_path / "RE5 dump.nsp", ["x.cnmt.xml"], payload=xml)
    assert switch_nsp.title_id(r) == "010018100CD46000"
    assert switch_nsp.is_update("01002A000CD48800") and not switch_nsp.is_update("01002A000CD48000")
    assert switch_nsp.base_title_id("01002A000CD48000") == "01002A000CD48000"


def test_companions_are_the_games_own_updates_and_dlc_beside_it(tmp_path):
    re6 = tmp_path / "Resident Evil 6"
    re6.mkdir()
    base = build_nsp(re6 / "Resident Evil 6 [01002A000CD48000].nsp", ["a.nca", "01002a000cd480000000000000000003.tik"])
    upd = build_nsp(re6 / "Resident Evil 6 [01002A000CD48800][v131072].nsp", ["b.nca"])
    dlc = build_nsp(re6 / "RE6 costume [01002A000CD49001].nsp", ["c.nca"])
    build_nsp(re6 / "Other game update [0100AAAA00000800][v65536].nsp", ["d.nca"])
    (re6 / "notes.txt").write_text("x")
    assert [str(p) for p in switch_nsp.companions(base)] == sorted([upd, dlc])
    assert switch_nsp.companions(upd) == []                     # an update has no companions of its own
    assert switch_nsp.is_addon_of("01002A000CD49001", "01002A000CD48000")
    assert not switch_nsp.is_addon_of("01002A000CD48800", "01002A000CD48000")
    alone = tmp_path / "Resident Evil 5"
    alone.mkdir()
    assert switch_nsp.companions(build_nsp(alone / "Resident Evil 5.nsp", ["010018100cd460000000000000000003.tik"])) == []
    assert switch_nsp.companions(tmp_path / "missing" / "x.nsp") == []


# --- Citron NEO: the canonical Switch emulator for RE5 / RE6 (multi-core; live 2026-10-26) ---------------------------------

def citron_cfg(tmp_path, **kw):
    img = tmp_path / "citron_nightly-56dad8119-linux-aarch64-use-nopgo.AppImage"
    img.write_bytes(b"AI")
    return cfg(tmp_path, switch_citron_appimage=str(img), **kw)


def re5_game(**kw):
    return dict(switch_game(), serial="010018100CD46000", **kw)


def test_re5_and_re6_start_in_citron_once_it_is_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    plain = adapters.for_game(re5_game(), cfg(tmp_path))
    assert type(plain) is adapters.SwitchLinuxAdapter                            # no Citron placed: Eden
    c = citron_cfg(tmp_path)
    ad = adapters.for_game(re5_game(), c)
    assert isinstance(ad, adapters.CitronLinuxAdapter) and ad.name == "citron"
    re6 = dict(switch_game(), serial="0x01002a000cd48000", title="Resident Evil 6")
    assert isinstance(adapters.for_game(re6, c), adapters.CitronLinuxAdapter)
    zelda = dict(switch_game(), serial="0100F2C0115B6000", title="Zelda")
    assert type(adapters.for_game(zelda, c)) is adapters.SwitchLinuxAdapter      # other titles stay in Eden
    forced = citron_cfg(tmp_path, switch_linux_emulator="eden")
    assert type(adapters.for_game(re5_game(), forced)) is adapters.SwitchLinuxAdapter
    forced = cfg(tmp_path, switch_linux_emulator="citron")
    assert isinstance(adapters.for_game(zelda, forced), adapters.CitronLinuxAdapter)


def test_citron_settings_are_its_own_and_multi_core(tmp_path):
    folder = tmp_path / "Resident Evil 5"
    folder.mkdir()
    ad = adapters.CitronLinuxAdapter(citron_cfg(tmp_path))
    ad.nce, ad.debug, ad.port = True, False, 43210
    ad.rom = build_nsp(folder / "Resident Evil 5.nsp", ["a.nca", "010018100cd460000000000000000003.tik"])
    path = ad.write_settings()
    assert path == provision.citron_linux_config(ad.config) and path.parent.name == "citron"
    t = path.read_text()
    assert adapters.ini_get(t, "Renderer", "backend") == "0"                    # Citron: Vulkan 0, Null 1
    assert adapters.ini_get(t, "Core", "use_multi_core") == "true"
    assert adapters.ini_get(t, "Cpu", "cpu_backend") == "1" and adapters.ini_get(t, "UI", "confirmStop") == "2"
    custom = path.parent / "custom" / "010018100CD46000.ini"
    c = custom.read_text()
    assert adapters.ini_get(c, "Renderer", "use_asynchronous_shaders") == "true"
    assert adapters.ini_get(c, "Core", "use_multi_core") is None                # no single-core in Citron
    assert ad.title_settings == adapters.CITRON_TITLE_SETTINGS["010018100CD46000"]
    assert not provision.switch_linux_config(ad.config).exists()                 # Eden's files are not touched
    assert ad.eden_log() == provision.citron_linux_dir(ad.config) / "log" / "citron_log.txt"


def test_citron_env_lets_the_usb_shim_through_sharun(tmp_path):
    import os
    c = citron_cfg(tmp_path)
    env = provision.citron_linux_env(c)
    home = provision.citron_linux_home(c)
    assert env["XDG_DATA_HOME"] == str(home / "data") and env["QT_QPA_PLATFORM"] == "xcb"
    assert env["SHARUN_ALLOW_LD_PRELOAD"] == "1"
    assert env["LD_PRELOAD"].startswith(str(c.runtime / "switch-usb-shim")) and env["LD_PRELOAD"].endswith(".so")
    assert env["PATH"].split(os.pathsep)[0] == str(home / "bin") and env["DISABLE_AUTO_UPDATES"] == "1"
    assert adapters.CitronLinuxAdapter(c).env == env


def test_usb_shim_is_built_from_the_repos_source_once(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        out = argv[argv.index("-o") + 1]
        with open(out, "wb") as f:
            f.write(b"\x7fELF")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(provision.shutil, "which", lambda n: "/usr/bin/cc" if n == "cc" else None)
    monkeypatch.setattr(provision.subprocess, "run", fake_run)
    shim = provision.switch_usb_shim(c)
    assert shim.is_file() and shim.name == "libgbox_usb_noinit.so"
    assert calls[0][0] == "/usr/bin/cc" and "-nostdlib" in calls[0] and str(provision.USB_SHIM_SOURCE) in calls[0]
    assert provision.USB_SHIM_SOURCE.read_text().count("libusb_init") >= 2
    assert provision.switch_usb_shim(c) == shim and len(calls) == 1               # cached by the source's digest
    assert str(shim) == provision.citron_linux_env(c)["LD_PRELOAD"]
    monkeypatch.setattr(provision.shutil, "which", lambda n: None)
    with pytest.raises(ToolUnavailable, match="no C compiler"):
        provision.switch_usb_shim(cfg(tmp_path / "other"))


def test_ensure_citron_extracts_once_installs_keys_stub_and_shim(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    share = tmp_path / "share" / "_switch"
    share.mkdir(parents=True)
    (share / "prod.keys").write_text("header_key = 00\n")
    c = citron_cfg(tmp_path, switch_keys=str(share / "prod.keys"))
    calls = []

    def extract(appimage, home):
        calls.append(appimage)
        (home / "squashfs-root").mkdir(parents=True, exist_ok=True)
        (home / "squashfs-root" / "AppRun").write_text("#!/bin/sh\n")
    monkeypatch.setattr(provision, "_rpcs3_appimage_extract", extract)
    monkeypatch.setattr(provision, "switch_usb_shim", lambda cfg_: tmp_path / "shim.so")
    r = provision.ensure_citron_linux(c)
    assert r["step"] == "citron" and r["status"] == "ok" and len(calls) == 1 and "shim.so" in r["detail"]
    assert (provision.citron_linux_dir(c) / "keys" / "prod.keys").read_text() == "header_key = 00\n"
    assert (provision.citron_linux_home(c) / "bin" / "xdg-open").read_text() == provision.SWITCH_URL_STUB
    provision.ensure_citron_linux(c)
    assert len(calls) == 1                                                       # unchanged AppImage: not again
    assert provision.citron_linux_available(c)
    with pytest.raises(ToolUnavailable, match="switch_citron_appimage"):
        provision.ensure_citron_linux(cfg(tmp_path / "bare"))


def test_layeredfs_uses_citrons_own_load_folder(tmp_path, monkeypatch):
    from gbox import switch_mods
    c = citron_cfg(tmp_path)
    emu = switch_mods.citron(c)
    assert emu.kind == "citron" and emu.load == provision.citron_linux_dir(c) / "load"
    assert emu.config == provision.citron_linux_config(c)
    assert adapters.CitronLinuxAdapter(c)._emu() == emu
    monkeypatch.setattr(switch_mods, "HOST_OS", "linux")
    assert switch_mods._emu_here(c, re5_game()).kind == "citron"
    assert switch_mods._emu_here(cfg(tmp_path / "e"), re5_game()).kind == "eden"
    assert [e.kind for e in switch_mods.local_emulators(c)] == ["eden", "citron"]


# --- the boot watch: one more start for a boot that never draws -------------------------------------------------------

def test_boot_watch_needs_changing_frames_after_the_loading_overlay(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.proc = SimpleNamespace(pid=5, poll=lambda: None)
    clock = [0.0]
    monkeypatch.setattr(adapters.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(adapters.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    frames = iter([b"a", b"b", b"c"])
    monkeypatch.setattr(ad, "get_frame", lambda: next(frames))
    out = ad._boot_watch()
    assert out["watched"] and out["frames"] == 3 and out["after_s"] >= adapters.BOOT_WATCH_SETTLE_S
    clock[0] = 0.0
    monkeypatch.setattr(ad, "get_frame", lambda: b"black")
    with pytest.raises(adapters.BootHung, match="no changing frame"):
        ad._boot_watch()
    clock[0] = 0.0
    ad.proc = SimpleNamespace(pid=5, poll=lambda: -11)
    with pytest.raises(adapters.BootHung, match="exited during boot"):
        ad._boot_watch()


def test_a_hung_boot_is_started_once_more(tmp_path, monkeypatch):
    ad = adapters.SwitchLinuxAdapter(cfg(tmp_path))
    ad.nce, ad.address_mode = True, "direct"
    popen, stops = [], []
    _fake_launch(ad, monkeypatch, [ARM64_MAPS], popen)
    monkeypatch.setattr(ad, "_xdo", lambda *a: None)
    monkeypatch.setattr(ad, "stop_game", lambda: stops.append(1) or {})
    outcomes = [adapters.BootHung("drew no changing frame"), {"watched": True, "frames": 3}]

    def watch():
        r = outcomes.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(ad, "_boot_watch", watch)
    rom = build_nsp(tmp_path / "Resident Evil 5.nsp", ["010018100cd460000000000000000003.tik", "a.nca"])
    out = ad.launch_game(rom)
    assert out["boot_attempts"] == 2 and "drew no changing frame" in out["boot_failures"][0]
    assert len(popen) == 2 and len(stops) == 1                                   # the hung one stopped, one restart
    outcomes[:] = [adapters.BootHung("hung"), adapters.BootHung("hung again")]
    with pytest.raises(adapters.BootHung, match="hung again"):
        ad.launch_game(rom)
    other = build_nsp(tmp_path / "Zelda.nsp", ["0100f2c0115b60000000000000000003.tik", "a.nca"])

    def never():
        raise AssertionError("not watched")
    monkeypatch.setattr(ad, "_boot_watch", never)
    assert ad.launch_game(other)["boot_watch"] == {"watched": False}             # only the listed titles
