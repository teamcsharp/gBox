"""Pinned native builds never execute arbitrary ROM code or overwrite save storage."""
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import zipfile

import pytest

from gbox import doa3_native as native
from gbox.config import Config
from gbox.registry import ToolUnavailable


def config(tmp_path):
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")


def game():
    return {"game_id": native.GAME_ID, "platform": "xbox", "title": "Dead or Alive 3 (USA)"}


@pytest.fixture
def disc(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    original = bytearray(b"XBEH" + b"\0" * 1020)
    struct.pack_into("<I", original, 0x104, 0x10000)
    struct.pack_into("<I", original, 0x118, 0x10200)
    struct.pack_into("<II", original, 0x29C, 2, 1)
    monkeypatch.setattr(native, "XBE_SHA256", hashlib.sha256(original).hexdigest())
    patched = bytearray(original)
    struct.pack_into("<II", patched, 0x29C, 0x400001FF, 7)
    monkeypatch.setattr(native, "PATCHED_XBE_SHA256", hashlib.sha256(patched).hexdigest())
    xbe = root / "default.xbe"
    xbe.write_bytes(patched)
    (root / "data").mkdir()
    (root / "data" / "game.afs").write_bytes(b"game assets")
    return xbe, bytes(original), bytes(patched)


def test_title_recognition_is_id_and_console_not_display_name():
    assert native.supports_game(game())
    assert not native.supports_game({**game(), "game_id": "another-title"})
    assert not native.supports_game({**game(), "platform": "ps2"})
    assert not native.supports_game({"platform": "xbox", "title": "Dead or Alive 3 (USA)"})


@pytest.mark.parametrize('registered', [False, True])
def test_cancelled_launch_cleans_only_an_unregistered_native_game(tmp_path, monkeypatch, registered):
    from gbox import tools
    from gbox.registry import Cancelled
    ad = native.Doa3NativeAdapter(config(tmp_path), game())
    stopped = []
    monkeypatch.setattr(ad, 'stop_game', lambda: stopped.append(True) or {'stopped': True})
    monkeypatch.setattr(tools, 'SESSIONS', {})
    monkeypatch.setattr(tools, '_launch_failure_evidence', lambda *args: None)

    def boot_then_cancel(inp, ctx):
        tools._LAUNCH_DIAG.d['_adapter'] = ad
        if registered:
            tools.SESSIONS['owned-session'] = (ad, game())
        raise Cancelled('cancelled after boot')

    monkeypatch.setattr(tools, '_launch_game', boot_then_cancel)
    with pytest.raises(Cancelled, match='after boot'):
        tools.launch_game(None, SimpleNamespace())
    assert stopped == ([] if registered else [True])


def test_private_copy_restores_only_verified_certificate_and_keeps_source(disc, tmp_path):
    xbe, original, patched = disc
    cfg = config(tmp_path)
    private = native.prepare_play_disc(xbe, cfg, game())
    assert private.read_bytes() == original
    assert xbe.read_bytes() == patched
    assert private.stat().st_ino != xbe.stat().st_ino
    assert (private.parent / "data" / "game.afs").read_bytes() == b"game assets"
    assert private.is_relative_to(cfg.runtime)


def test_existing_save_and_cache_survive_relaunch(disc, tmp_path):
    xbe, _, _ = disc
    cfg = config(tmp_path)
    private = native.prepare_play_disc(xbe, cfg, game())
    save = private.parent / ".recomp-storage" / "partition1" / "UDATA" / "profile.dat"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"a real saved game")
    source_save = xbe.parent / ".recomp-storage" / "not-our-save"
    source_save.parent.mkdir()
    source_save.write_bytes(b"do not import")
    assert native.prepare_play_disc(xbe, cfg, game()) == private
    assert save.read_bytes() == b"a real saved game"
    assert not (private.parent / ".recomp-storage" / "not-our-save").exists()


def test_changed_source_asset_and_damaged_private_copy_fail_without_overwriting_saves(disc, tmp_path):
    xbe, _, _ = disc
    cfg = config(tmp_path)
    private = native.prepare_play_disc(xbe, cfg, game())
    storage = private.parent / ".recomp-storage"
    storage.mkdir()
    (storage / "save").write_bytes(b"keep")
    asset = xbe.parent / "data" / "game.afs"
    asset.write_bytes(b"evil assets")  # Same size: content, not a size-only check.
    with pytest.raises(ToolUnavailable, match="differs"):
        native.prepare_play_disc(xbe, cfg, game())
    assert (storage / "save").read_bytes() == b"keep"
    asset.write_bytes(b"game assets")
    (private.parent / "data" / "game.afs").write_bytes(b"evil assets")
    with pytest.raises(ToolUnavailable, match="content differs"):
        native.prepare_play_disc(xbe, cfg, game())
    assert (storage / "save").read_bytes() == b"keep"


def test_unknown_xbe_and_unreceipted_play_disc_are_not_replaced(disc, tmp_path):
    xbe, original, _ = disc
    cfg = config(tmp_path)
    xbe.write_bytes(original + b"unexpected")
    with pytest.raises(ToolUnavailable, match="XBE differs"):
        native.prepare_play_disc(xbe, cfg, game())
    xbe.write_bytes(original)
    private = cfg.runtime / "xbox" / "doa3-native-play" / native.GAME_ID / "disc"
    private.mkdir(parents=True)
    (private / "save").write_bytes(b"preserve")
    with pytest.raises(ToolUnavailable, match="left intact"):
        native.prepare_play_disc(xbe, cfg, game())
    assert (private / "save").read_bytes() == b"preserve"


def test_source_symlink_cannot_copy_outside_disc(disc, tmp_path):
    xbe, _, _ = disc
    outside = tmp_path / "private"
    outside.write_bytes(b"secret")
    try:
        (xbe.parent / "linked.afs").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable for this Windows account")
    with pytest.raises(ToolUnavailable, match="linked/reparse"):
        native.prepare_play_disc(xbe, config(tmp_path), game())


def test_windows_junction_attribute_is_rejected_before_resolving(tmp_path, monkeypatch):
    target = tmp_path / "junction"
    original = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda path: SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
                        if path == target else original(path))
    with pytest.raises(ToolUnavailable, match="linked/reparse"):
        native._plain_path(target / "payload")


def test_relative_runtime_and_source_become_absolute_without_following_links(disc, tmp_path, monkeypatch):
    xbe, _, _ = disc
    monkeypatch.chdir(tmp_path)
    cfg = Config(data_dir=Path("data"), cache_dir=Path("cache"))
    assert native.install_dir(cfg).is_absolute()
    result = native.prepare_play_disc(xbe.relative_to(tmp_path), cfg, game())
    assert result.is_absolute() and result.is_file()


def test_unreadable_source_subdirectory_is_not_silently_omitted(disc, tmp_path, monkeypatch):
    import os
    xbe, _, _ = disc
    scan = os.scandir
    def unreadable(path):
        if Path(path) == xbe.parent / "data":
            raise PermissionError("simulated unreadable disc folder")
        return scan(path)
    monkeypatch.setattr(os, "scandir", unreadable)
    with pytest.raises(ToolUnavailable, match="complete disc inventory"):
        native.prepare_play_disc(xbe, config(tmp_path), game())


def bundle(monkeypatch, extra=None, symlink=None):
    runner, sdl = b"MZrunner", b"MZsdl"
    crt = {name: b"MZ" + name.encode() for name in native.CRT_SHA256}
    monkeypatch.setattr(native, "RUNNER_SHA256", hashlib.sha256(runner).hexdigest())
    monkeypatch.setattr(native, "SDL_SHA256", hashlib.sha256(sdl).hexdigest())
    monkeypatch.setattr(native, "CRT_SHA256", {name: hashlib.sha256(data).hexdigest() for name, data in crt.items()})
    receipt = {"format": "gbox-doa3-native-build-v1", "upstream": "https://github.com/NoRain211/doa3-re",
               "release": "v0.2", "release_sha256": native.RELEASE_SHA256, "xbe_sha256": native.XBE_SHA256,
               "program_sha256": native.PROGRAM_SHA256, "runner_sha256": native.RUNNER_SHA256,
               "sdl_sha256": native.SDL_SHA256, "crt_sha256": native.CRT_SHA256}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in {"runner.exe": runner, "SDL3.dll": sdl, "LICENSE": b"GPL3", "NOTICE": b"Notice",
                           "build-receipt.json": json.dumps(receipt).encode(), **crt}.items():
            info = zipfile.ZipInfo(name)
            if name == symlink:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, data)
        if extra:
            archive.writestr(extra, b"arbitrary code")
    payload = output.getvalue()
    monkeypatch.setattr(native, "BUNDLE_SHA256", hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(native, "HOST_OS", "windows")
    monkeypatch.setattr(native, "_download", lambda *args: payload)
    return payload


def test_install_is_pinned_and_never_downloads_again_when_valid(tmp_path, monkeypatch):
    bundle(monkeypatch)
    cfg = config(tmp_path)
    exe = native.ensure_runtime(cfg, "https://configured-spark", {})
    assert exe.read_bytes() == b"MZrunner"
    monkeypatch.setattr(native, "_download", lambda *args: pytest.fail("Unexpected redownload"))
    assert native.ensure_runtime(cfg, "", {}) == exe
    (exe.parent / "SDL3.dll").write_bytes(b"MZtampered")
    with pytest.raises(ToolUnavailable, match="checksum mismatch"):
        native.ensure_runtime(cfg, "", {})


def test_tampered_crt_is_rejected_before_running(tmp_path, monkeypatch):
    bundle(monkeypatch)
    cfg = config(tmp_path)
    exe = native.ensure_runtime(cfg, "https://configured-spark", {})
    (exe.parent / "msvcp140.dll").write_bytes(b"MZtampered")
    with pytest.raises(ToolUnavailable, match="checksum mismatch: msvcp140.dll"):
        native.ensure_runtime(cfg, "", {})


@pytest.mark.parametrize("extra", ["../runner.exe", "folder/plugin.dll", "RUNNER.EXE"])
def test_bundle_paths_fail_closed(tmp_path, monkeypatch, extra):
    bundle(monkeypatch, extra=extra)
    cfg = config(tmp_path)
    with pytest.raises(ToolUnavailable, match="unexpected or duplicate"):
        native.ensure_runtime(cfg, "https://configured-spark", {})
    assert not native.install_dir(cfg).exists()


def test_symlink_bundle_and_wrong_download_are_rejected(tmp_path, monkeypatch):
    bundle(monkeypatch, symlink="SDL3.dll")
    with pytest.raises(ToolUnavailable, match="unsupported entry"):
        native.ensure_runtime(config(tmp_path), "https://configured-spark", {})
    monkeypatch.setattr(native, "_download", lambda *args: b"a changed bundle")
    with pytest.raises(ToolUnavailable, match="bundle checksum"):
        native.ensure_runtime(config(tmp_path), "https://configured-spark", {})


def test_unpublished_build_and_other_platform_never_execute(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "HOST_OS", "windows")
    monkeypatch.setattr(native, "BUNDLE_SHA256", "")
    with pytest.raises(ToolUnavailable, match="not available yet"):
        native.ensure_runtime(config(tmp_path), "", {})
    monkeypatch.setattr(native, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows"):
        native.ensure_runtime(config(tmp_path), "", {})


def test_normal_launch_has_only_fixed_arguments_and_removes_diagnostic_environment(disc, tmp_path, monkeypatch):
    from gbox import adapters
    import psutil
    xbe, _, _ = disc
    exe = tmp_path / "runner.exe"
    exe.write_bytes(b"MZrunner")
    monkeypatch.setattr(native, "ensure_runtime", lambda *args: exe)
    monkeypatch.setattr(native, "prepare_xbe", lambda *args: xbe)
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    monkeypatch.setattr(adapters, "keep_offscreen", lambda pid: None)
    monkeypatch.setenv("RECOMP_SAVE_SHORT_WRITE_AT", "1")
    monkeypatch.setenv("RECOMP_WATCHDOG_MS", "1")
    monkeypatch.setenv("recomp_unpaced", "1")
    monkeypatch.setenv("RECOMP_D3D_FRAME_DUMP", "somewhere-private.bmp")
    calls = []
    def start(args, **kwargs):
        from PIL import Image
        calls.append((args, kwargs))
        image = Image.new("RGB", (640, 480), (80, 40, 160))
        image.paste((230, 210, 180), (100, 100, 500, 300))
        image.save(kwargs["env"]["RECOMP_D3D_FRAME_DUMP"] + ".000.bmp")
        return SimpleNamespace(pid=56789, poll=lambda: None)
    monkeypatch.setattr(native.subprocess, "Popen", start)
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 123.0))
    clock = iter(range(50))
    monkeypatch.setattr(native.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(native.time, "sleep", lambda _: None)
    row = {"pid": 56789, "hwnd": 876, "class": native.Doa3NativeAdapter.render_class,
           "hung": False, "width": 640, "height": 480}
    monkeypatch.setattr(native, "owned_windows", lambda _: [row])
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    monkeypatch.setattr(adapter, "_live", lambda: {56789})
    result = adapter.launch_game(str(xbe))
    args, kwargs = calls[0]
    assert args == [str(exe), "--xbe", str(Path(result["rom"]).resolve())]
    assert {key for key in kwargs["env"] if key.upper().startswith("RECOMP_")} == {
        "RECOMP_D3D_SCALE", "RECOMP_D3D_WIDESCREEN", "RECOMP_AUDIO_GAIN", "RECOMP_D3D_FRAME_DUMP",
        "RECOMP_D3D_FRAME_DUMP_COUNT", "RECOMP_D3D_FRAME_DUMP_AT", "RECOMP_D3D_FRAME_DUMP_INTERVAL_MS"}
    assert Path(kwargs["env"]["RECOMP_D3D_FRAME_DUMP"]).is_relative_to(adapter.config.runtime)
    assert adapter._owned == {56789: 123.0}
    assert result["pid"] == 56789 and "gameplay not verified" in result["boot_validation"]
    adapter._output.close()


def test_black_or_incomplete_capture_does_not_prove_boot(tmp_path):
    from PIL import Image
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    path = tmp_path / "owned.bmp"
    adapter.boot_frame_paths = [path]
    path.write_bytes(b"BMpartial")
    assert adapter._boot_frame() is None
    Image.new("RGB", (640, 480), (0, 0, 0)).save(path)
    assert adapter._boot_frame() is None
    Image.new("RGB", (640, 480), (50, 80, 120)).save(path)
    assert adapter._boot_frame() is None  # A uniform colored clear buffer is not a rendered game image.
    image = Image.new("RGB", (640, 480), (50, 80, 120))
    image.paste((180, 200, 230), (100, 100, 500, 300))
    image.save(path)
    assert adapter._boot_frame()[0] == path
    import os
    os.utime(path, (1, 1))
    assert adapter._boot_frame(fresh=True) is None


def test_failed_start_closes_log_and_uses_owned_cleanup(disc, tmp_path, monkeypatch):
    from gbox import adapters
    xbe, _, _ = disc
    exe = tmp_path / "runner.exe"
    monkeypatch.setattr(native, "ensure_runtime", lambda *args: exe)
    monkeypatch.setattr(native, "prepare_xbe", lambda *args: xbe)
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("startup failed")))
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    with pytest.raises(OSError, match="startup failed"):
        adapter.launch_game(str(xbe))
    assert adapter._output.closed and not adapter.ready and adapter._owned == {}


def test_responsive_window_without_real_pixels_times_out_and_cleans_owned_process(disc, tmp_path, monkeypatch):
    from gbox import adapters
    import psutil
    xbe, _, _ = disc
    monkeypatch.setattr(native, "ensure_runtime", lambda *args: tmp_path / "runner.exe")
    monkeypatch.setattr(native, "prepare_xbe", lambda *args: xbe)
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *args, **kwargs: SimpleNamespace(pid=56789, poll=lambda: None))
    monkeypatch.setattr(psutil, "Process", lambda pid: SimpleNamespace(create_time=lambda: 123.0))
    clock = iter(range(50))
    monkeypatch.setattr(native.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(native.time, "sleep", lambda _: None)
    monkeypatch.setattr(native, "owned_windows", lambda _: [{"pid": 56789, "hwnd": 876,
        "class": native.Doa3NativeAdapter.render_class, "hung": False, "width": 640, "height": 480}])
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    adapter.boot_timeout_s = 8
    monkeypatch.setattr(adapter, "_live", lambda: {56789})
    cleaned = []
    def cleanup():
        cleaned.append(adapter._owned.copy())
        adapter._output.close()
    monkeypatch.setattr(adapter, "stop_game", cleanup)
    with pytest.raises(RuntimeError, match="visible back-buffer content"):
        adapter.launch_game(str(xbe))
    assert cleaned == [{56789: 123.0}] and adapter._output.closed and not adapter.ready


def test_live_capture_uses_shared_pid_capture_after_boot_snapshot_expires(tmp_path, monkeypatch):
    from gbox import adapters
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    adapter.render_pid = 56789
    monkeypatch.setattr(adapter, "_running", lambda: True)
    calls = []
    monkeypatch.setattr(adapters, "win_grab", lambda pid: calls.append(pid) or b"current GPU frame")
    assert adapter.get_frame() == b"current GPU frame"
    assert calls == [56789]


def test_failed_process_identity_terminates_only_retained_child_handle(disc, tmp_path, monkeypatch):
    from gbox import adapters
    import psutil
    xbe, _, _ = disc
    monkeypatch.setattr(native, "ensure_runtime", lambda *args: tmp_path / "runner.exe")
    monkeypatch.setattr(native, "prepare_xbe", lambda *args: xbe)
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    actions = []
    child = SimpleNamespace(pid=56789, poll=lambda: 0 if actions else None,
                            terminate=lambda: actions.append("terminate"), wait=lambda timeout: 0)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *args, **kwargs: child)
    monkeypatch.setattr(psutil, "Process", lambda pid: (_ for _ in ()).throw(psutil.AccessDenied(pid)))
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    with pytest.raises(psutil.AccessDenied):
        adapter.launch_game(str(xbe))
    assert actions == ["terminate"] and adapter._output.closed and adapter._owned == {}


def test_cancel_after_disc_verification_never_starts_a_process(disc, tmp_path, monkeypatch):
    from gbox.registry import Cancelled
    xbe, _, _ = disc
    monkeypatch.setattr(native, "ensure_runtime", lambda *args: tmp_path / "runner.exe")
    monkeypatch.setattr(native, "prepare_xbe", lambda *args: xbe)
    monkeypatch.setattr(native.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("Cancelled launch started a process"))
    adapter = native.Doa3NativeAdapter(config(tmp_path), game())
    def cancel(pct, text):
        if pct == 65:
            raise Cancelled("cancelled while preparing")
    adapter.progress = cancel
    with pytest.raises(Cancelled):
        adapter.launch_game(str(xbe))
    assert adapter.launcher is None
