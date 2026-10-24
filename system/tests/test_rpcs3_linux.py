"""PS3 sessions on a Linux node (the Spark): RPCS3's AppImage on the session's Xvfb display (gbox.adapters.RPCS3LinuxAdapter,
gbox.provision.ensure_rpcs3_linux). Verified live with RE5 Gold (BLUS30491) on the Spark's aarch64 RPCS3 0.0.43."""
from types import SimpleNamespace

import pytest

from gbox import adapters, provision
from gbox.config import Config
from gbox.models import CatalogEntry

RPCS3_WRITTEN = """Core:
  PPU Decoder: Recompiler (LLVM)
  Accurate RSX reservation access: false
  RSX FIFO Fetch Accuracy: Atomic
Video:
  Renderer: Vulkan
  Resolution: 1280x720
Audio:
  Renderer: Cubeb
Miscellaneous:
  Automatically start games after boot: true
  GDB Server: 127.0.0.1:2345
Log:
  {}
"""


def cfg(tmp_path, **kw) -> Config:
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", **kw)


def re5_entry() -> CatalogEntry:
    member = "Resident Evil 5 - Gold Edition (USA) (v02.00)/PS3_GAME/USRDIR/EBOOT.BIN"
    return CatalogEntry(game_id="e7ca89bbeb67360d", title="Resident Evil 5 - Gold Edition", platform="ps3",
                        platform_confidence="ext", source_paths=[], core=None, hashes={}, size=0, format="7z",
                        launch={"kind": "emulator", "platform": "ps3", "path": "/mnt/x/RE5.7z", "archive_member": member},
                        profile_id="e7ca89bbeb67360d")


def test_service_audio_discovers_only_an_owned_existing_socket(tmp_path, monkeypatch):
    import os
    import socket
    if not hasattr(os, "getuid"):
        pytest.skip("Linux user-owned Pulse socket")
    native = tmp_path / "pulse" / "native"
    native.parent.mkdir()
    assert provision.linux_audio_env({}, runtime_dir=tmp_path) == {}
    native.write_text("not a socket")
    assert provision.linux_audio_env({}, runtime_dir=tmp_path) == {}
    native.unlink()
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(native))
        expected = {"XDG_RUNTIME_DIR": str(tmp_path), "PULSE_SERVER": "unix:" + str(native)}
        assert provision.linux_audio_env({}, runtime_dir=tmp_path) == expected
        assert provision.linux_audio_env({"PULSE_SERVER": "tcp:operator"}, runtime_dir=tmp_path)["PULSE_SERVER"] == "tcp:operator"
        monkeypatch.setattr(os, "getuid", lambda: native.stat().st_uid + 1)
        assert provision.linux_audio_env({}, runtime_dir=tmp_path) == {}


def test_linux_routes_ps3_to_rpcs3_appimage(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    ad = adapters.for_game(re5_entry().model_dump(), cfg(tmp_path))
    assert isinstance(ad, adapters.RPCS3LinuxAdapter)
    assert {"send_input", "stream_session", "get_frame", "read_memory", "write_memory", "save_state",
            "load_state"} <= ad.supported
    assert ad.checkpoint_state is False                        # no in-place rewind: RPCS3 reloads on a save state
    assert ad.screen == (1280, 720)
    env = ad.env                                               # RPCS3's XDG folders are gBox's own, never ~/.config
    assert env["XDG_CONFIG_HOME"].startswith(str(tmp_path)) and env["XDG_CACHE_HOME"].startswith(str(tmp_path))
    assert ad.home == provision.rpcs3_linux_dir(ad.config)


def test_yaml_set_replaces_inserts_and_adds_sections():
    t = adapters.yaml_set(RPCS3_WRITTEN, "Core", "Accurate RSX reservation access", "true")
    assert "  Accurate RSX reservation access: true" in t and "reservation access: false" not in t
    assert "  RSX FIFO Fetch Accuracy: Atomic" in t                       # neighbours untouched
    t = adapters.yaml_set(t, "Audio", "Audio Provider", "CellAudio")      # a key the section lacks: inserted in it
    lines = t.splitlines()
    assert lines[lines.index("Audio:") + 1] == "  Audio Provider: CellAudio"
    t = adapters.yaml_set(t, "Net", "PSN status", "Disconnected")         # a missing section: appended
    assert t.rstrip().endswith("Net:\n  PSN status: Disconnected")


def test_write_settings_on_rpcs3s_own_config(tmp_path):
    ad = adapters.RPCS3LinuxAdapter(cfg(tmp_path))
    ad.home.mkdir(parents=True)
    (ad.home / "config.yml").write_text(RPCS3_WRITTEN)
    ad.write_settings()
    text = (ad.home / "config.yml").read_text()
    assert "  Accurate RSX reservation access: true" in text                # RE5 hung on a black screen without it (ARM)
    assert '  GDB Server: ""' in text and "2345" not in text               # a port probe crashed the emulator
    assert '  Renderer: FAudio' in text and '  Microphone type: "Null"' in text
    assert '  Renderer: Cubeb' not in text
    assert "  Renderer: Vulkan" in text and "  PPU Decoder: Recompiler (LLVM)" in text
    pad = (ad.home / "input_configs" / "global" / "Default.yml").read_text()
    assert pad.startswith("Player 1 Input:\n  Handler: Keyboard\n  Device: Keyboard\n")
    for line in ("    Cross: X", "    Circle: C", "    Square: Z", "    Triangle: V", "    Left Stick Up: W",
                 "    Right Stick Left: J", "    Up: Up", "    Start: Return", "    Select: Space", "    L1: Q", "    R1: E"):
        assert line in pad
    ini = (ad.home / "GuiConfigs" / "CurrentSettings.ini").read_text()
    assert "game_window_savestate=F2" in ini and "game_window_restart=Ctrl+Alt+Shift+F11" in ini
    # RPCS3's welcome dialog covered RE5's boot in the Spark session and took the pad's keys: off, info boxes too
    assert "[main_window]\n" in ini and "infoBoxEnabledWelcome=false" in ini and "infoBoxEnabledInstallPKG=false" in ini
    ad.write_settings()                                                     # idempotent
    assert (ad.home / "config.yml").read_text() == text
    assert (ad.home / "GuiConfigs" / "CurrentSettings.ini").read_text() == ini


def test_rpcs3_faudio_uses_real_sdl_pulse_driver_and_preserves_explicit_override(tmp_path, monkeypatch):
    monkeypatch.delenv('SDL_AUDIO_DRIVER',raising=False)
    monkeypatch.setattr(provision,'linux_audio_env',lambda:{'PULSE_SERVER':'unix:/run/user/1000/pulse/native'})
    env = provision.rpcs3_linux_env(cfg(tmp_path))
    assert env['SDL_AUDIO_DRIVER'] == 'pulseaudio'
    assert env['PULSE_SERVER'] == 'unix:/run/user/1000/pulse/native'
    monkeypatch.setenv('SDL_AUDIO_DRIVER','pipewire')
    assert provision.rpcs3_linux_env(cfg(tmp_path))['SDL_AUDIO_DRIVER'] == 'pipewire'


def test_re5_framebuffer_writeback_is_title_scoped_and_retains_custom_graphics(tmp_path):
    ad = adapters.RPCS3LinuxAdapter(cfg(tmp_path))
    custom = ad.home / 'custom_configs'
    custom.mkdir(parents=True)
    re5 = custom / 'config_BLUS30491.yml'
    re5.write_text('Video:\n  Write Color Buffers: false\n  Anisotropic Filter Override: 16\n'
                   'Audio:\n  Renderer: Cubeb\n')
    other = custom / 'config_BLUS30855.yml'
    other.write_text('Video:\n  Write Color Buffers: false\n')
    ad.write_settings()
    text = re5.read_text()
    assert '  Write Color Buffers: true' in text
    assert '  Anisotropic Filter Override: 16' in text
    assert '  Renderer: FAudio' in text and '  Renderer: Cubeb' not in text
    assert '  Accurate RSX reservation access: true' in text
    assert 'Write Color Buffers: true' not in (ad.home / 'config.yml').read_text()
    assert other.read_text() == 'Video:\n  Write Color Buffers: false\n'
    ad.write_settings()
    assert re5.read_text() == text


def test_ini_set_keeps_rpcs3s_own_lines():
    rpcs3 = ("[Meta]\nattachCommandLine=false\n\n[main_window]\ninfoBoxEnabledWelcome=true\n"
             "lastExplorePathPUP=/home/x\n\n[Shortcuts]\ngame_window_restart=F4\n")
    t = adapters.ini_set(rpcs3, "main_window", "infoBoxEnabledWelcome", "false")      # replaced in place
    assert "infoBoxEnabledWelcome=false\nlastExplorePathPUP=/home/x\n" in t and "=true" not in t
    t = adapters.ini_set(t, "main_window", "restartHint", "false")                     # appended to its own section
    assert "lastExplorePathPUP=/home/x\nrestartHint=false\n\n[Shortcuts]" in t
    t = adapters.ini_set(t, "Shortcuts", "game_window_restart", "Ctrl+Alt+Shift+F11")  # off F4 (gBox's load key)
    assert t.endswith("[Shortcuts]\ngame_window_restart=Ctrl+Alt+Shift+F11\n") and "=F4" not in t
    assert adapters.ini_set("", "Meta", "a", "1") == "[Meta]\na=1\n"
    assert adapters.ini_set("[A]\nx=1\n\n", "B", "y", "2") == "[A]\nx=1\n\n[B]\ny=2\n"   # a new section after the rest


def test_send_input_presses_the_bound_keys(tmp_path, monkeypatch):
    ad = adapters.RPCS3LinuxAdapter(cfg(tmp_path))
    sent = []
    monkeypatch.setattr(ad, "_xdo", lambda *a: sent.append(a))
    out = ad.send_input([{"key": "cross", "down": True}, {"key": "lup", "down": True}, {"key": "r1", "down": True},
                         {"key": "b", "down": False}, {"key": "up", "down": True}, {"key": "start", "down": True},
                         {"key": "select", "down": True}, {"key": "home", "down": True},
                         {"key": "x", "down": True, "player": 2}])
    args = list(sent[0])
    assert args[:6] == ["keydown", "x", "keydown", "w", "keydown", "e"]   # Cross = X, left stick up = W, R1 = E
    assert args[6:9] == ["sleep", "0.06", "keyup"] and args[9] == "x"       # b = the bottom button = Cross
    assert args[10:] == ["keydown", "Up", "keydown", "Return", "keydown", "space"]   # D-pad up, Start, Select
    assert out["skipped"] == ["home"]                                       # not a PS3 button: left out


def test_guest_base_probe():
    mem = {0x300010000: b"\x7c\x08\x02\xa6" * 4}
    read = lambda a, n: mem.get(a, b"\0" * n)                                  # noqa: E731
    assert adapters.rpcs3_guest_base(1, read=read, maps=[]) == 0x300000000
    mem = {0x7F2000010000: b"\x01" * 16}                                     # an unusual reservation: from the maps
    read = lambda a, n: mem.get(a, b"\0" * n)                                  # noqa: E731
    maps = ["7f2000000000-7f2000010000 ---p 00000000 00:00 0",
            "7f2000010000-7f2001bc0000 rw-s 00000000 00:01 5 /memfd:rpcs3 (deleted)",
            "7f2001bc0000-7f2100000000 ---p 00000000 00:00 0"]
    assert adapters.rpcs3_guest_base(1, read=read, maps=maps) == 0x7F2000000000
    with pytest.raises(RuntimeError, match="guest memory not found"):
        adapters.rpcs3_guest_base(1, read=lambda a, n: b"\0" * n, maps=[])


def test_read_and_write_guest_memory(tmp_path, monkeypatch):
    ad = adapters.RPCS3LinuxAdapter(cfg(tmp_path))
    mem = tmp_path / "mem"
    mem.write_bytes(bytes(0x3000))
    ad.MEM, ad._mem = str(tmp_path / "mem"), (1234, 0x1000)                 # base 0x1000 in the stand-in file
    monkeypatch.setattr(ad, '_guest', lambda: (1234, 0x1000))             # I/O fixture is not a live RPCS3 reservation
    ad.proc = SimpleNamespace(pid=1234, poll=lambda: None)
    assert ad.write_memory(0x10, b"\x00\x00\x03\xe8") == {"address": 0x10, "written": 4, "verified": True}
    assert mem.read_bytes()[0x1010:0x1014] == b"\x00\x00\x03\xe8"
    assert ad.read_memory(0x10, 4) == b"\x00\x00\x03\xe8"
    with pytest.raises(ValueError, match="not mapped"):
        ad.read_memory(0x1FF0, 0x20)                                      # past the end of the stand-in


def test_rpcs3_linux_exe_from_config(tmp_path):
    c = cfg(tmp_path)
    assert provision.rpcs3_linux_exe(c) == provision.rpcs3_linux_home(c) / "squashfs-root" / "AppRun"
    appdir = tmp_path / "rpcs3-appdir"
    (appdir / "squashfs-root").mkdir(parents=True)
    (appdir / "squashfs-root" / "AppRun").write_text("#!/bin/sh\n")
    assert provision.rpcs3_linux_exe(cfg(tmp_path, rpcs3_appimage=str(appdir))) == appdir / "squashfs-root" / "AppRun"
    binary = tmp_path / "rpcs3"
    binary.write_text("")
    assert provision.rpcs3_linux_exe(cfg(tmp_path, rpcs3_appimage=str(binary))) == binary
    img = tmp_path / "rpcs3-v0.0.43_linux_aarch64.AppImage"
    img.write_text("")                                                      # an AppImage is extracted into gBox's home
    assert provision.rpcs3_linux_exe(cfg(tmp_path, rpcs3_appimage=str(img))) == \
        provision.rpcs3_linux_home(c) / "squashfs-root" / "AppRun"


def test_ensure_refuses_an_unchecked_download(tmp_path, monkeypatch):
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ARCH", "aarch64")
    rel = {"assets": [{"name": "rpcs3-v0.0.43-20355_linux_aarch64.AppImage", "browser_download_url": "https://x/a"}]}
    monkeypatch.setattr(provision.httpx, "get", lambda *a, **k: SimpleNamespace(json=lambda: rel))
    with pytest.raises(RuntimeError, match="no sha256 digest"):
        provision.ensure_rpcs3_linux(cfg(tmp_path))
    monkeypatch.setattr(provision, "HOST_OS", "windows")
    with pytest.raises(provision.ToolUnavailable):
        provision.ensure_rpcs3_linux(cfg(tmp_path))


def test_ensure_checks_the_digest_and_installs_firmware(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(provision, "HOST_OS", "linux")
    monkeypatch.setattr(provision, "ARCH", "aarch64")
    body = b"\x7fELF fake appimage"
    rel = {"assets": [{"name": "rpcs3_linux_aarch64.AppImage", "browser_download_url": "https://x/a",
                       "digest": "sha256:" + hashlib.sha256(body).hexdigest()}]}
    lst = "Dest=84;ImageVersion=1;CDN=http://dus01.example/PS3UPDAT.PUP;CDN_Timeout=30;"

    class Stream:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self, n):
            yield self.data
    monkeypatch.setattr(provision.httpx, "get", lambda url, **k: SimpleNamespace(
        json=lambda: rel, text=lst))
    monkeypatch.setattr(provision.httpx, "stream", lambda m, url, **k: Stream(b"PUP" if url.endswith(".PUP") else body))
    c = cfg(tmp_path)

    def extract(appimage, home):
        assert appimage.read_bytes() == body
        (home / "squashfs-root").mkdir()
        (home / "squashfs-root" / "AppRun").write_text("")
    monkeypatch.setattr(provision, "_rpcs3_appimage_extract", extract)
    fw = {}

    def installfw(exe, pup, env, done, timeout_s=900.0):
        fw.update(exe=exe, pup=pup.read_bytes(), env=env)
        done.parent.mkdir(parents=True)
        done.write_bytes(b"vsh")
        return True
    monkeypatch.setattr(provision, "rpcs3_installfw_linux", installfw)
    r = provision.ensure_rpcs3_linux(c)
    assert r["status"] == "ok" and fw["pup"] == b"PUP" and fw["exe"] == provision.rpcs3_linux_exe(c)
    assert fw["env"]["XDG_CONFIG_HOME"] == str(provision.rpcs3_linux_home(c) / "config")
    assert not list(provision.rpcs3_linux_home(c).glob("*.AppImage"))      # the download is removed once extracted
    body = b"tampered"                                                      # a second run downloads nothing
    assert provision.ensure_rpcs3_linux(c)["status"] == "ok"


def test_windows_guest_base_is_the_reservation_with_the_games_elf():
    # JAYBUILTFINALE 2026-10-22: RE5's guest memory sat at 0x500000000, beside non-zero regions that are not guest memory
    ad = object.__new__(adapters.RPCS3Adapter)
    ad.base = None
    mem = {0x900000000 + 0x10000: b"\x08\x00\x08\x00", 0x500000000 + 0x10000: b"\x7fELF"}
    ad._rpm = lambda a, n: mem.get(a, b"\x00" * n)[:n].ljust(n, b"\x00") if a in mem else None
    assert ad._base() == 0x500000000
    ad.base, mem = None, {0x300000000 + 0x10000: b"\x01\x02\x03\x04"}   # no ELF anywhere: the usual non-zero one
    assert ad._base() == 0x300000000
    ad.base, mem = None, {}
    with pytest.raises(RuntimeError, match="guest memory not found"):
        ad._base()
