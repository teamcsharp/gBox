"""xemu runs the Xbox titles Cxbx cannot draw: pinned binary, private system copies, checked XISO images."""
import hashlib
from contextlib import contextmanager
import io
from pathlib import Path
import struct
import tomllib
import zipfile

import pytest

from gbox import adapters, xbox, xbox_disc, xemu
from gbox.config import Config, EmulatorConfig, Library
from gbox.registry import ToolUnavailable, Unsupported

JSRF = "collections/Microsoft XBOX/roms/Jet Set Radio Future (USA).7z"


def config(tmp_path, **extra):
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", **extra)


def entry(path, **extra):
    return {"platform": "xbox", "library": "hyperspin", "rel_path": path,
            "launch": {"kind": "attract", "rel_path": path, "emulator": "Microsoft XBOX"}} | extra


def xdvdfs(path, base=0):
    """A minimal image xbox_disc.layout accepts, with its XDVDFS volume at the given base."""
    header = bytearray(2048)
    header[:20] = header[-20:] = xbox_disc.MAGIC
    struct.pack_into("<II", header, 20, 34, 256)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as writer:
        writer.seek(base + 0x10000)
        writer.write(header)
        writer.seek(base + 0x20000 - 1)
        writer.write(b"\0")
    return path


def listing_text(files):
    lines = ["extract-xiso v2.7.1", "listing game.iso:"]
    lines += [f"/{name} ({size} bytes)" for name, size in files.items()]
    lines.append(f"{len(files)} files in game.iso total {sum(files.values())} bytes")
    return "\n".join(lines) + "\n"


def fake_extractor(monkeypatch, files):
    """Stands in for the pinned extract-xiso: records argv, writes an XISO for -c/-r, lists `files` for -l."""
    calls = []
    monkeypatch.setattr(xbox_disc, "ensure_extractor", lambda cfg: Path("extract-xiso.exe"))

    def run(argv, **kwargs):
        argv = [str(arg) for arg in argv]
        calls.append(argv)
        assert argv[1] == "-m", "media patching must stay disabled"
        if "-l" in argv:
            return listing_text(files).encode()
        if "-c" in argv:
            xdvdfs(Path(argv[argv.index("-c") + 2]))
        elif "-r" in argv:
            operand = Path(argv[-1])
            operand.rename(operand.with_name(operand.name + ".old"))      # what upstream does to its operand
            xdvdfs(Path(argv[argv.index("-d") + 1]) / operand.name)
        return b""
    monkeypatch.setattr(xbox_disc, "_run", run)
    return calls


def modes(calls):
    return [next(flag for flag in ("-c", "-r", "-l") if flag in argv) for argv in calls]


# --- routing ------------------------------------------------------------------------------------------------------

def test_jsrf_routes_to_xemu_and_other_xbox_games_keep_cxbx(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    cfg = config(tmp_path)
    by_id = adapters.for_game({"platform": "xbox", "game_id": "bb6edc3dfcf32822", "launch": {}}, cfg)
    assert isinstance(by_id, xemu.XemuAdapter) and by_id.name == "xemu"
    assert adapters.for_game(entry(JSRF), cfg).name == "xemu"                       # by normalized file title
    assert adapters.for_game({"platform": "xbox", "title": "Jet Set Radio Future", "launch": {}}, cfg).name == "xemu"
    legacy = entry(JSRF) | {"platform": "windows_native", "system": "Microsoft XBOX", "collections": ["Microsoft XBOX"]}
    assert adapters.for_game(legacy, cfg).name == "xemu"
    other = entry("collections/Microsoft XBOX/roms/Halo (USA).7z", game_id="c77a5418f4328722")
    assert type(adapters.for_game(other, cfg)) is xbox.XboxAdapter
    assert type(adapters.for_game({"platform": "xbox", "launch": {}}, cfg)) is xbox.XboxAdapter
    assert xemu.title_key("Jet Set Radio Future (USA) [!].7z") == "jet set radio future"
    assert not xemu.wants_xemu({"title": "Jet Set Radio"})


def test_config_override_selects_xemu_or_cxbx_but_doa3_native_is_untouched(tmp_path, monkeypatch):
    from gbox.doa3_native import Doa3NativeAdapter, GAME_ID
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    everything = config(tmp_path, emulators={"xbox": EmulatorConfig(adapter="xemu")})
    halo = entry("collections/Microsoft XBOX/roms/Halo (USA).7z")
    assert adapters.for_game(halo, everything).name == "xemu"
    assert isinstance(adapters.for_game(entry("x/Dead or Alive 3 (USA).7z", game_id=GAME_ID), everything), Doa3NativeAdapter)
    never = config(tmp_path, emulators={"xbox": EmulatorConfig(adapter="cxbx")})
    assert adapters.for_game(entry(JSRF), never).name == "cxbx"
    # A default [emulators.xbox] table (adapter "retroarch") expresses no Xbox preference.
    assert adapters.for_game(entry(JSRF), config(tmp_path, emulators={"xbox": EmulatorConfig()})).name == "xemu"
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows worker"):
        adapters.for_game(entry(JSRF), config(tmp_path))


def test_xemu_keeps_the_xbox_op_surface():
    ad = xemu.XemuAdapter(Config())
    caps = ad.get_capabilities()
    assert {op for op, state in caps.items() if state == "supported"} == {"launch_game", "stop_game", "query_runtime", "get_frame"}
    with pytest.raises(Unsupported, match="xemu does not support"):
        ad.send_input()


# --- install ------------------------------------------------------------------------------------------------------

def test_pinned_install_checks_archive_and_executable_and_keeps_existing_files(tmp_path, monkeypatch):
    import httpx
    binary = b"MZ" + b"\0" * 4096
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("xemu.exe", binary)
        archive.writestr("LICENSE.txt", b"GPL")
    content = payload.getvalue()
    monkeypatch.setattr(xemu, "HOST_OS", "windows")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    monkeypatch.setattr(xemu, "XEMU_SHA256", hashlib.sha256(content).hexdigest())
    monkeypatch.setattr(xemu, "XEMU_EXE_SHA256", hashlib.sha256(binary).hexdigest())

    @contextmanager
    def stream(*args, **kwargs):
        yield httpx.Response(200, content=content, request=httpx.Request("GET", xemu.XEMU_URL))
    monkeypatch.setattr(httpx, "stream", stream)
    cfg = config(tmp_path)
    home = xemu.install_dir(cfg)
    (home / "system").mkdir(parents=True)
    saves = home / "system" / "xbox_hdd.qcow2"
    saves.write_bytes(b"QFI\xfbsaves")
    exe = xemu.ensure_xemu(cfg)
    assert exe == home / "xemu.exe" and exe.read_bytes() == binary
    assert saves.read_bytes() == b"QFI\xfbsaves"
    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: pytest.fail("an installed runtime must not download"))
    assert xemu.ensure_xemu(cfg) == exe
    exe.write_bytes(b"MZ self-updated")
    with pytest.raises(ToolUnavailable, match="not the pinned"):
        xemu.ensure_xemu(cfg)


def test_bad_download_never_publishes_runtime(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(xemu, "HOST_OS", "windows")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)

    @contextmanager
    def stream(*args, **kwargs):
        yield httpx.Response(200, content=b"corrupt", request=httpx.Request("GET", xemu.XEMU_URL))
    monkeypatch.setattr(httpx, "stream", stream)
    cfg = config(tmp_path)
    with pytest.raises(ToolUnavailable, match="checksum"):
        xemu.ensure_xemu(cfg)
    assert not xemu.install_dir(cfg).exists()
    monkeypatch.setattr(xemu, "HOST_OS", "linux")
    with pytest.raises(ToolUnavailable, match="Windows worker"):
        xemu.ensure_xemu(cfg)


# --- system files -------------------------------------------------------------------------------------------------

def share(tmp_path, **sizes):
    """A library share with QuickSwap2's layout: Emulation/_emulation/XBOX(og) ISO beside the game folders."""
    folder = tmp_path / "share" / "Emulation" / "_emulation" / "XBOX(og) ISO"
    folder.mkdir(parents=True)
    defaults = {"mcpx_1.0.bin": b"\x01" * 512, "xbox-3944_256k.bin": b"\x02" * 256 * 1024,
                "xbox_hdd.qcow2": b"QFI\xfb" + b"\0" * 1000}
    for name, data in (defaults | sizes).items():
        if data is not None:
            (folder / name).write_bytes(data)
    library = Library(id="gc-iso", paths={"windows": str(tmp_path / "share" / "Emulation" / "_emulation" / "GC ISO"),
                                          "linux": str(tmp_path / "share" / "Emulation" / "_emulation" / "GC ISO")})
    return folder, config(tmp_path, libraries=[library])


def test_system_files_are_copied_from_the_share_once_and_never_written_back(tmp_path):
    folder, cfg = share(tmp_path)
    before = {item.name: item.read_bytes() for item in folder.iterdir()}
    home = tmp_path / "xemu"
    files = xemu.ensure_system(cfg, home)
    assert files["bootrom"].read_bytes() == before["mcpx_1.0.bin"]
    assert files["flashrom"].stat().st_size == 256 * 1024
    assert files["hdd"].parent == home / "system" and files["eeprom"] == home / "system" / "eeprom.bin"
    assert not files["eeprom"].exists()                     # xemu generates its EEPROM on first boot
    files["hdd"].write_bytes(b"QFI\xfb game saves")         # the worker's HDD copy is writable and private
    for item in folder.iterdir():
        item.unlink()                                        # the share is no longer needed once copied
    assert xemu.ensure_system(cfg, home)["hdd"].read_bytes() == b"QFI\xfb game saves"
    assert not list(home.rglob("*.gbox-part"))


@pytest.mark.parametrize("name, data, message", [
    ("mcpx_1.0.bin", b"\0" * 511, "must be 512 bytes"),
    ("xbox-3944_256k.bin", b"\0" * 100000, "256 KiB or 1 MiB"),
    ("xbox_hdd.qcow2", b"not a qcow2", "not a qcow2"),
    ("mcpx_1.0.bin", None, "mcpx_1.0.bin"),
    ("xbox-3944_256k.bin", None, "xbox-3944_256k.bin"),
    ("xbox_hdd.qcow2", None, "xbox_hdd.qcow2"),
], ids=["short-mcpx", "odd-flash", "raw-hdd", "no-mcpx", "no-flash", "no-hdd"])
def test_missing_or_wrong_system_files_name_the_file(tmp_path, name, data, message):
    _, cfg = share(tmp_path, **{name: data})
    with pytest.raises(ToolUnavailable, match=message.replace(".", r"\.")) as error:
        xemu.ensure_system(cfg, tmp_path / "xemu")
    assert name in str(error.value)
    assert not (tmp_path / "xemu" / "system" / name).exists()


def test_one_mib_flash_and_bad_existing_eeprom(tmp_path):
    _, cfg = share(tmp_path, **{"xbox-3944_256k.bin": b"\0" * 1024 * 1024})
    files = xemu.ensure_system(cfg, tmp_path / "xemu")
    files["eeprom"].write_bytes(b"\0" * 10)
    with pytest.raises(ToolUnavailable, match="256 bytes"):
        xemu.ensure_system(cfg, tmp_path / "xemu")
    assert files["eeprom"].read_bytes() == b"\0" * 10


def test_no_library_share_names_the_missing_file(tmp_path):
    with pytest.raises(ToolUnavailable, match="mcpx_1.0.bin.*no library roots"):
        xemu.ensure_system(config(tmp_path), tmp_path / "xemu")


# --- xemu.toml ----------------------------------------------------------------------------------------------------

def test_config_sets_system_paths_windowed_and_no_welcome(tmp_path):
    home = tmp_path / "xemu"
    home.mkdir()
    files = {role: home / "system" / name for role, name in
             (("bootrom", "mcpx_1.0.bin"), ("flashrom", "xbox-3944_256k.bin"), ("hdd", "xbox_hdd.qcow2"), ("eeprom", "eeprom.bin"))}
    disc = tmp_path / 'disc "quoted" \\ name.iso'
    path = xemu.write_config(home, files, disc)
    assert path == home / "xemu.toml"                        # beside xemu.exe: xemu's portable mode
    data = tomllib.loads(path.read_text(encoding="utf8"))
    assert data["sys"]["files"] == {"bootrom_path": str(files["bootrom"]), "flashrom_path": str(files["flashrom"]),
                                    "eeprom_path": str(files["eeprom"]), "hdd_path": str(files["hdd"]),
                                    "dvd_path": str(disc)}
    assert data["general"]["show_welcome"] is False and data["general"]["skip_boot_anim"] is True
    assert data["general"]["updates"]["check"] is False
    assert data["display"]["window"]["fullscreen_on_startup"] is False
    assert data["display"]["ui"]["show_menubar"] is False
    assert data["input"]["background_input_capture"] is True
    assert xemu.launch_args(home / "xemu.exe", path, disc) == [
        str(home / "xemu.exe"), "-config_path", str(path), "-dvd_path", str(disc)]


def test_config_keeps_operator_settings_and_refuses_broken_toml(tmp_path):
    home = tmp_path / "xemu"
    home.mkdir()
    (home / "xemu.toml").write_text(
        '[general]\nshow_welcome = true\nscreenshot_dir = "C:\\\\shots"\n'
        '[input.bindings]\nport1 = "030000005e040000"\n'
        '[[input.gamepad_mappings]]\ngamepad_id = "pad-1"\nenable_rumble = false\n'
        '[input.gamepad_mappings.controller_mapping]\na = 1\nb = 0\n'
        '[[net.nat.forward_ports]]\nhost = 9368\nguest = 9368\n'
        '[display.quality]\nsurface_scale = 2\n[audio]\nvolume_limit = 0.5\n', encoding="utf8")
    files = {role: home / role for role in ("bootrom", "flashrom", "hdd", "eeprom")}
    data = tomllib.loads(xemu.write_config(home, files, home / "game.iso").read_text(encoding="utf8"))
    assert data["general"]["show_welcome"] is False and data["general"]["screenshot_dir"] == "C:\\shots"
    assert data["input"]["bindings"]["port1"] == "030000005e040000"
    assert data["input"]["gamepad_mappings"] == [{"gamepad_id": "pad-1", "enable_rumble": False,
                                                  "controller_mapping": {"a": 1, "b": 0}}]
    assert data["net"]["nat"]["forward_ports"] == [{"host": 9368, "guest": 9368}]
    assert data["display"]["quality"]["surface_scale"] == 2 and data["audio"]["volume_limit"] == 0.5
    (home / "xemu.toml").write_text("[general\nbroken", encoding="utf8")
    with pytest.raises(ToolUnavailable, match="not valid TOML"):
        xemu.write_config(home, files, home / "game.iso")
    assert (home / "xemu.toml").read_text(encoding="utf8") == "[general\nbroken"


# --- disc images --------------------------------------------------------------------------------------------------

def dvd_folder(root):
    (root / "Media").mkdir(parents=True)
    (root / "default.xbe").write_bytes(b"XBEHboot")
    (root / "Media" / "Beat.bin").write_bytes(b"beat")
    return {"default.xbe": 8, "Media/Beat.bin": 4}


def test_dvd_folder_is_built_with_create_and_cached(tmp_path, monkeypatch):
    files = dvd_folder(tmp_path / "Jet Set Radio Future (USA)")
    calls = fake_extractor(monkeypatch, files)
    cfg = config(tmp_path)
    iso = xemu.prepare_xiso(tmp_path / "Jet Set Radio Future (USA)", cfg)
    assert modes(calls) == ["-c", "-l"]
    create = calls[0]
    assert create[create.index("-c") + 1] == str((tmp_path / "Jet Set Radio Future (USA)").absolute())
    assert iso.name == "game.iso" and iso.parent.parent == (cfg.runtime / "xbox" / "xiso").absolute()
    assert xbox_disc.layout(iso)["base"] == 0
    assert (tmp_path / "Jet Set Radio Future (USA)" / "default.xbe").read_bytes() == b"XBEHboot"
    # The cache is reused, and so is a default.xbe path to the same folder.
    assert xemu.prepare_xiso(tmp_path / "Jet Set Radio Future (USA)" / "default.xbe", cfg) == iso
    assert modes(calls) == ["-c", "-l"]


def test_archive_with_dvd_folder_is_unpacked_then_created(tmp_path, monkeypatch):
    archive = tmp_path / "Jet Set Radio Future (USA).zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("Jet Set Radio Future (USA)/default.xbe", b"XBEHboot")
        writer.writestr("Jet Set Radio Future (USA)/Media/Beat.bin", b"beat")
    calls = fake_extractor(monkeypatch, {"default.xbe": 8, "Media/Beat.bin": 4})
    iso = xemu.prepare_xiso(archive, config(tmp_path))
    assert modes(calls) == ["-c", "-l"] and iso.is_file()
    assert Path(calls[0][calls[0].index("-c") + 1]).name == "Jet Set Radio Future (USA)"


def test_archive_root_disc_is_created_without_gbox_marker(tmp_path, monkeypatch):
    archive = tmp_path / "Game.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("default.xbe", b"XBEHboot")
        writer.writestr("Media/Beat.bin", b"beat")
    staged = []
    calls = fake_extractor(monkeypatch, {"default.xbe": 8, "Media/Beat.bin": 4})
    run = xbox_disc._run

    def spy(argv, **kwargs):
        if "-c" in [str(a) for a in argv]:
            tree = Path(argv[list(argv).index("-c") + 1])
            staged.append(sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*")))
        return run(argv, **kwargs)
    monkeypatch.setattr(xbox_disc, "_run", spy)
    xemu.prepare_xiso(archive, config(tmp_path))
    assert staged == [["Media", "Media/Beat.bin", "default.xbe"]]
    assert modes(calls) == ["-c", "-l"]


def test_redump_image_is_rewritten_from_a_private_link_and_source_is_untouched(tmp_path, monkeypatch):
    source = xdvdfs(tmp_path / "redump.iso", base=xbox_disc.BASES[1])
    original = source.read_bytes()
    calls = fake_extractor(monkeypatch, {"default.xbe": 8})
    iso = xemu.prepare_xiso(source, config(tmp_path))
    assert modes(calls) == ["-l", "-r", "-l"]
    rewrite = calls[1]
    assert rewrite[-1] != str(source) and Path(rewrite[-1]).name == "source.iso"
    assert "-d" in rewrite and "-q" in rewrite
    assert source.read_bytes() == original and xbox_disc.layout(iso)["base"] == 0
    assert xemu.prepare_xiso(source, config(tmp_path)) == iso and len(calls) == 3


def test_xiso_is_used_as_is(tmp_path, monkeypatch):
    source = xdvdfs(tmp_path / "game.xiso.iso")
    calls = fake_extractor(monkeypatch, {"default.xbe": 8})
    assert xemu.prepare_xiso(source, config(tmp_path)) == source.absolute()
    assert calls == []


def test_build_that_lists_different_files_is_never_published(tmp_path, monkeypatch):
    dvd_folder(tmp_path / "disc")
    fake_extractor(monkeypatch, {"default.xbe": 8})                 # the built image lacks Media/Beat.bin
    cfg = config(tmp_path)
    with pytest.raises(ValueError, match="differs"):
        xemu.prepare_xiso(tmp_path / "disc", cfg)
    assert not list((cfg.runtime / "xbox" / "xiso").glob("xiso-*"))


def test_unsupported_inputs(tmp_path):
    chd = tmp_path / "game.chd"
    chd.write_bytes(b"MComprHD")
    with pytest.raises(Unsupported, match="CHD"):
        xemu.prepare_xiso(chd, config(tmp_path))
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "readme.txt").write_text("no game")
    with pytest.raises(ValueError, match="one default.xbe"):
        xemu.prepare_xiso(tmp_path / "empty", config(tmp_path))


# --- launch -------------------------------------------------------------------------------------------------------

class FakeProcess:
    pid = 303

    def poll(self):
        return None


def test_launch_waits_for_owned_sdl_window_and_reports_unverified_rendering(tmp_path, monkeypatch):
    import psutil
    cfg = config(tmp_path)
    home = xemu.install_dir(cfg)
    home.mkdir(parents=True)
    exe = home / "xemu.exe"
    files = {role: home / "system" / role for role in ("bootrom", "flashrom", "hdd", "eeprom")}
    disc = tmp_path / "game.iso"
    monkeypatch.setattr(xemu, "ensure_xemu", lambda *a: exe)
    monkeypatch.setattr(xemu, "ensure_system", lambda *a: files)
    monkeypatch.setattr(xemu, "prepare_xiso", lambda *a: disc)
    calls = []
    monkeypatch.setattr(xbox.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw["cwd"])) or FakeProcess())
    monkeypatch.setattr(psutil, "Process", lambda pid: type("Process", (), {"create_time": lambda _: 10.0})())
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    parked = []
    monkeypatch.setattr(adapters, "keep_offscreen", lambda pid: parked.append(pid))
    monkeypatch.setattr(xbox.XboxAdapter, "_live", lambda self: {303})
    menu = {"pid": 303, "hwnd": 5, "class": "IME", "title": "Default IME", "width": 0, "height": 0, "hung": False}
    window = {"pid": 303, "hwnd": 9, "class": "SDL_app", "title": "xemu | v0.8.136", "width": 1280, "height": 960, "hung": False}
    monkeypatch.setattr(xbox, "owned_windows", lambda pids, known_hwnd=None: [menu, window])
    tick = iter(range(10000))
    monkeypatch.setattr(xbox.time, "monotonic", lambda: float(next(tick)))
    monkeypatch.setattr(xbox.time, "sleep", lambda seconds: None)
    ad = xemu.XemuAdapter(cfg)
    out = ad.launch_game(JSRF)
    assert calls == [([str(exe), "-config_path", str(home / "xemu.toml"), "-dvd_path", str(disc)], home)]
    assert out["pid"] == 303 and out["rom"] == str(disc) and parked == [303, 303]
    assert "SDL_app window stable" in out["boot_validation"]
    assert out["window_ready"] and out["rendering_verified"] is False and out["gameplay_verified"] is False
    assert ad.log_path == home / "xemu.log"
    assert tomllib.loads((home / "xemu.toml").read_text(encoding="utf8"))["sys"]["files"]["dvd_path"] == str(disc)
    assert ad.query_runtime()["running"]
    ad._output.close()


def test_launch_reports_xemu_dialog(tmp_path, monkeypatch):
    import psutil
    cfg = config(tmp_path)
    home = xemu.install_dir(cfg)
    home.mkdir(parents=True)
    monkeypatch.setattr(xemu, "ensure_xemu", lambda *a: home / "xemu.exe")
    monkeypatch.setattr(xemu, "ensure_system", lambda *a: {r: home / r for r in ("bootrom", "flashrom", "hdd", "eeprom")})
    monkeypatch.setattr(xemu, "prepare_xiso", lambda *a: tmp_path / "game.iso")
    monkeypatch.setattr(xbox.subprocess, "Popen", lambda argv, **kw: FakeProcess())
    monkeypatch.setattr(psutil, "Process", lambda pid: type("Process", (), {"create_time": lambda _: 10.0})())
    monkeypatch.setattr(adapters, "capture_start", lambda: None)
    monkeypatch.setattr(adapters, "keep_offscreen", lambda pid: None)
    monkeypatch.setattr(xbox.XboxAdapter, "_live", lambda self: {303})
    dialog = {"pid": 303, "hwnd": 4, "class": "#32770", "title": "Unable to create OpenGL context",
              "text": "the graphics device on this system does not support OpenGL 4.0"}
    monkeypatch.setattr(xbox, "owned_windows", lambda pids, known_hwnd=None: [dialog])
    ad = xemu.XemuAdapter(cfg)
    monkeypatch.setattr(ad, "stop_game", lambda: None)
    with pytest.raises(RuntimeError, match="xemu displayed a startup dialog.*OpenGL 4.0"):
        ad.launch_game(JSRF)
    assert not ad.ready
    ad._output.close()
