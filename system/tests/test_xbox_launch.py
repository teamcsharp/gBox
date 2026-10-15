"""Original Xbox archives boot a real Cxbx renderer, never RocketLauncher's GUI wrapper."""
import hashlib
import io
from pathlib import Path
import zipfile

import pytest

from gbox import adapters, catalog, rom_archives, systems, xbox
from gbox.config import Config
from gbox.registry import ToolUnavailable, Unsupported


def config(tmp_path):
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")


def legacy_entry(path="collections/Microsoft XBOX/roms/Dead or Alive 3 (USA).7z"):
    return {"platform": "windows_native", "system": "Microsoft XBOX", "core": None,
            "library": "hs", "rel_path": path, "collections": ["Microsoft XBOX"],
            "launch": {"kind": "attract", "rel_path": path, "emulator": "Microsoft XBOX"}}


def test_original_xbox_routes_directly_without_catalog_rescan(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    cfg = config(tmp_path)
    assert isinstance(adapters.for_game(legacy_entry(), cfg), xbox.XboxAdapter)
    assert isinstance(adapters.for_game({"platform": "xbox", "launch": {}}, cfg), xbox.XboxAdapter)
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows worker"):
        adapters.for_game(legacy_entry(), cfg)


def test_console_identity_uses_actual_disc_collection():
    assert systems.classify("Microsoft XBOX")[:2] == ("xbox", None)
    assert systems.classify("Microsoft XBOX 360")[:2] == ("xbox360", None)
    assert systems.classify("Microsoft XBOX", "Microsoft XBOX", "collections/Sony Playstation 2/roms/USA")[:2] == ("ps2", "pcsx2")
    assert not xbox.is_xbox_game(legacy_entry("collections/Sony Playstation 2/roms/USA/Black (USA).chd"))
    assert not xbox.is_xbox_game(legacy_entry("collections/Microsoft XBOX 360/roms/Some Game.iso"))
    assert not xbox.is_xbox_game({"platform": "xbox360", "system": "Microsoft XBOX 360"})
    assert not xbox.is_xbox_game({"platform": "windows_native", "system": "PC Games", "launch": {"path": "game.exe"}})


def test_default_xbe_beats_larger_asset_files_and_archive_extracts_whole_dvd(tmp_path):
    archive = tmp_path / "DOA3.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("DOA3/default.XBE", b"XBEH" + b"\0" * 100)
        writer.writestr("DOA3/loadfile.afs", b"DATA" * 1000)
        writer.writestr("DOA3/movies/intro.sfd", b"MOVIE")
    assert catalog.EXT_PLATFORM[".xbe"] == "xbox"
    assert rom_archives.boot_member(rom_archives.members(archive)) == "DOA3/default.XBE"
    cfg = config(tmp_path)
    result = xbox.prepare_xbe(archive, cfg)
    assert result.name == "default.XBE" and result.read_bytes().startswith(b"XBEH")
    assert (result.parent / "loadfile.afs").read_bytes() == b"DATA" * 1000
    assert (result.parent / "movies" / "intro.sfd").read_bytes() == b"MOVIE"
    assert xbox.prepare_xbe(archive, cfg) == result
    assert archive.is_file()


def test_bad_and_ambiguous_inputs_never_boot(tmp_path):
    cfg = config(tmp_path)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("a/default.xbe", b"XBEH")
        writer.writestr("b/default.xbe", b"XBEH")
    with pytest.raises(ValueError, match="exactly one"):
        xbox.prepare_xbe(archive, cfg)
    bogus = tmp_path / "default.xbe"
    bogus.write_bytes(b"MZxx")
    with pytest.raises(ValueError, match="Not an Xbox XBE"):
        xbox.prepare_xbe(bogus, cfg)
    iso = tmp_path / "game.iso"
    iso.write_bytes(b"disc")
    with pytest.raises(Unsupported, match="conversion"):
        xbox.prepare_xbe(iso, cfg)


def test_ini_changes_preserve_controller_profiles_repeated_keys_and_saves(tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text('[gui]\nRecentXbeFiles = a\nRecentXbeFiles = b\nDataStorageToggle = 0x0\n'
                    '[input-profile-0]\nDeviceName = Custom controller\n'
                    '[core]\nLoggedModules = 0x1\nLoggedModules = 0x2\nKrnlDebugMode = 0x0\n')
    xbox._set_ini(path, {"gui": {"DataStorageToggle": "0x1"}, "core": {"KrnlDebugMode": "0x2"}})
    text = path.read_text()
    assert "RecentXbeFiles = a\nRecentXbeFiles = b" in text
    assert "DeviceName = Custom controller" in text
    assert "LoggedModules = 0x1\nLoggedModules = 0x2" in text
    assert "DataStorageToggle = 0x1" in text and "KrnlDebugMode = 0x2" in text


def release_zip():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as writer:
        for name in ("cxbx.exe", "cxbxr-ldr.exe", "cxbxr-emu.dll", "SDL2.dll"):
            writer.writestr(name, b"MZ" + b"\0" * 2048)
        writer.writestr("hlsl/xbox.hlsl", b"shader")
    return content.getvalue()


def test_pinned_install_checksum_and_preserve_settings(tmp_path, monkeypatch):
    import httpx
    payload = release_zip()
    monkeypatch.setattr(xbox, "HOST_OS", "windows")
    monkeypatch.setattr(xbox, "CXBX_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, content=payload, request=httpx.Request("GET", xbox.CXBX_URL)))
    cfg = config(tmp_path)
    home = xbox.install_dir(cfg)
    home.mkdir(parents=True)
    settings = home / "settings.ini"
    settings.write_text("operator settings")
    save = home / "EmuDisk" / "E" / "TDATA" / "save.dat"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"do not overwrite")
    exe = xbox.ensure_cxbx(cfg)
    assert exe.name == "cxbxr-ldr.exe" and (home / "cxbxr-emu.dll").is_file()
    assert settings.read_text() == "operator settings"
    assert save.read_bytes() == b"do not overwrite"
    assert (home / ".gbox-installed.json").is_file()
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: pytest.fail("existing runtime must not download"))
    assert xbox.ensure_cxbx(cfg) == exe


def test_bad_download_never_publishes_runtime(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(xbox, "HOST_OS", "windows")
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, content=b"corrupt archive", request=httpx.Request("GET", xbox.CXBX_URL)))
    cfg = config(tmp_path)
    with pytest.raises(ToolUnavailable, match="checksum"):
        xbox.ensure_cxbx(cfg)
    assert not xbox.install_dir(cfg).exists()


class FakeProcess:
    pid = 101

    def poll(self):
        return None


def setup_launch(tmp_path, monkeypatch, windows):
    import psutil
    cfg = config(tmp_path)
    exe = tmp_path / "cxbx.exe"
    exe.write_bytes(b"MZ" + b"\0" * 1024)
    xbe = tmp_path / "default.xbe"
    xbe.write_bytes(b"XBEH")
    monkeypatch.setattr(xbox, "ensure_cxbx", lambda *args: exe)
    monkeypatch.setattr(xbox.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())
    monkeypatch.setattr(psutil, "Process", lambda pid: type("Process", (), {"create_time": lambda _: 10.0})())
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    monkeypatch.setattr(adapters, "keep_offscreen", lambda pid: None)
    monkeypatch.setattr(xbox.XboxAdapter, "_live", lambda self: {101, 202})
    monkeypatch.setattr(xbox, "owned_windows", lambda pids, known_hwnd=None: windows())
    tick = iter(range(10000))
    monkeypatch.setattr(xbox.time, "monotonic", lambda: float(next(tick)))
    monkeypatch.setattr(xbox.time, "sleep", lambda seconds: None)
    return xbox.XboxAdapter(cfg), xbe


def test_launch_requires_renderer_and_reports_owned_child_pid(tmp_path, monkeypatch):
    renderer = {"pid": 202, "hwnd": 77, "class": "CxbxRender", "title": "Cxbx-Reloaded",
                "width": 640, "height": 480, "hung": False}
    calls = []
    ad, xbe = setup_launch(tmp_path, monkeypatch, lambda: [renderer])
    monkeypatch.setattr(xbox.subprocess, "Popen", lambda argv, **kwargs: calls.append(argv) or FakeProcess())
    out = ad.launch_game(str(xbe))
    assert calls == [[str(tmp_path / "cxbx.exe"), str(xbe.resolve())]]
    assert out["pid"] == ad.proc.pid == 202 and out["launch_pid"] == 101
    assert out["owned_pids"] == [101, 202] and out["local_window"]
    assert "stable" in out["boot_validation"]
    assert ad.query_runtime()["running"]
    ad._output.close()


def test_standalone_loader_has_required_load_and_explicit_kernel_logging(tmp_path, monkeypatch):
    renderer = {"pid": 101, "hwnd": 77, "class": "CxbxRender", "title": "Cxbx-Reloaded",
                "width": 640, "height": 480, "hung": False}
    ad, xbe = setup_launch(tmp_path, monkeypatch, lambda: [renderer])
    loader = tmp_path / "cxbxr-ldr.exe"
    loader.write_bytes(b"MZ" + b"\0" * 2048)
    assert xbox._executable(tmp_path) == loader
    monkeypatch.setattr(xbox, "ensure_cxbx", lambda *args: loader)
    calls = []
    startup = object()
    monkeypatch.setattr(adapters, "capture_start", lambda: startup)
    park = []
    monkeypatch.setattr(adapters, "keep_offscreen", lambda pid: park.append(pid))
    def popen(argv, **kwargs):
        assert kwargs["startupinfo"] is startup
        calls.append(argv)
        return FakeProcess()
    monkeypatch.setattr(xbox.subprocess, "Popen", popen)
    out = ad.launch_game(str(xbe))
    assert calls == [[str(loader), "/load", str(xbe.resolve()), "/dm", "2", "/df", str(ad.log_path.resolve())]]
    assert out["pid"] == 101 and "stable" in out["boot_validation"]
    assert park[0] == 101
    settings = (tmp_path / "settings.ini").read_text()
    assert "IgnoreInvalidXbeSig" not in settings and "IgnoreInvalidXbeSec" not in settings
    assert "AllowAdminPrivilege = true" not in settings
    ad._output.close()


def test_gui_alone_times_out_instead_of_reporting_a_playable_game(tmp_path, monkeypatch):
    gui = {"pid": 101, "hwnd": 1, "class": "Cxbx", "title": "Dead or Alive 3",
           "width": 640, "height": 480, "hung": False}
    ad, xbe = setup_launch(tmp_path, monkeypatch, lambda: [gui])
    ad.boot_timeout_s = 5
    stopped = []
    monkeypatch.setattr(ad, "stop_game", lambda: stopped.append(True))
    with pytest.raises(RuntimeError, match="render window"):
        ad.launch_game(str(xbe))
    assert stopped == [True] and not ad.ready
    ad._output.close()


def test_owned_startup_error_is_a_failed_launch(tmp_path, monkeypatch):
    ad, xbe = setup_launch(tmp_path, monkeypatch, lambda: [{"class": "#32770", "title": "Missing DirectX runtime"}])
    monkeypatch.setattr(ad, "stop_game", lambda: None)
    with pytest.raises(RuntimeError, match="Missing DirectX runtime"):
        ad.launch_game(str(xbe))
    assert not ad.ready
    ad._output.close()


def test_startup_dialog_reports_explanation_and_buttons_without_accepting(tmp_path, monkeypatch):
    dialog = {"class": "#32770", "title": "Cxbx-Reloaded", "controls": [
        {"class": "Static", "text": "The emulator was launched with Administrator rights. Continue?"},
        {"class": "Button", "text": "&Yes"}, {"class": "Button", "text": "&No"}]}
    ad, xbe = setup_launch(tmp_path, monkeypatch, lambda: [dialog])
    monkeypatch.setattr(ad, "stop_game", lambda: None)
    with pytest.raises(RuntimeError, match="Administrator rights") as error:
        ad.launch_game(str(xbe))
    assert "&Yes" in str(error.value) and "&No" in str(error.value)
    assert not ad.ready
    assert "AllowAdminPrivilege = true" not in (tmp_path / "settings.ini").read_text()
    ad._output.close()


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="Windows dialog API")
def test_native_dialog_static_edit_and_button_text_is_collected():
    import ctypes
    from ctypes import wintypes as w
    user = ctypes.windll.user32
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
    user.CreateWindowExW.restype = w.HWND
    user.DestroyWindow.argtypes = [w.HWND]
    # Hidden owned fixture windows cannot interrupt the operator's desktop.
    dialog = user.CreateWindowExW(0, "#32770", "Cxbx diagnostic fixture", 0, 0, 0, 400, 300, None, None, None, None)
    assert dialog
    try:
        for klass, text in (("Static", "The required emulation DLL could not be loaded."),
                            ("Edit", "C:\\runtime\\cxbxr-emu.dll"), ("Button", "OK")):
            assert user.CreateWindowExW(0, klass, text, 0x40000000, 0, 0, 200, 40, dialog, None, None, None)
        controls = xbox.dialog_controls(dialog)
        assert {row["class"] for row in controls} == {"Static", "Edit", "Button"}
        assert any("emulation DLL" in row["text"] for row in controls)
        assert any(row["text"] == "C:\\runtime\\cxbxr-emu.dll" for row in controls)
    finally:
        user.DestroyWindow(dialog)


def test_docked_renderer_keeps_its_verified_handle(tmp_path, monkeypatch):
    renderer = {"pid": 202, "hwnd": 77, "class": "CxbxRender", "title": "Cxbx-Reloaded",
                "width": 640, "height": 480, "hung": False}
    ad, xbe = setup_launch(tmp_path, monkeypatch, lambda: [renderer])
    ad.launch_game(str(xbe))
    calls = []
    def after_dock(pids, known_hwnd=None):
        calls.append(known_hwnd)
        return [renderer] if known_hwnd == 77 else []
    monkeypatch.setattr(xbox, "owned_windows", after_dock)
    assert ad.query_runtime()["running"] and calls == [77]
    ad._output.close()


def test_partial_install_never_mixes_binary_versions(tmp_path, monkeypatch):
    monkeypatch.setattr(xbox, "HOST_OS", "windows")
    cfg = config(tmp_path)
    home = xbox.install_dir(cfg)
    home.mkdir(parents=True)
    old = home / "cxbxr-emu.dll"
    old.write_bytes(b"old build")
    monkeypatch.setattr(xbox, "_download_cxbx", lambda *args: pytest.fail("do not mix binary versions"))
    with pytest.raises(ToolUnavailable, match="DLLs but no executable"):
        xbox.ensure_cxbx(cfg)
    assert old.read_bytes() == b"old build"
