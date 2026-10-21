"""Native PC ports (gbox/native_ports.py): the GoldenEye 007 PC port's build recipe, ROM preparation, catalog entry,
launch routing and session input. Nothing here downloads, compiles or needs the real ROM."""
import dataclasses
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import run_job
from gbox import adapters, native_ports as np_
from gbox.config import Config, Library

PORT = np_.GE007


def fake_tree(root: Path) -> Path:
    """Just the upstream lines the gBox patches anchor on."""
    files = {
        "src/boss.c": "x\n                            joyConsumeSamplesWrapper();\n                            permit_stderr(0);\ny\n",
        "port/src/input.c": "a\n    if (sx > STICK_MAX)  sx = STICK_MAX;\nb\n",
        "assets/animationtable_data.h": "#if defined(__x86_64__) || (defined(__aarch64__) && defined(__APPLE__))\n",
        "src/game/bg.c": "    ptr = (u8 *)specialportalarray;\n    end = (u8 *)&g_BgCurrentRoom;\n",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return root


def test_patch_text_inserts_once_and_refuses_a_moved_anchor():
    text, did = np_.patch_text("a\nB\nc\n", "B\n", "B\nhook\n", "f")
    assert did and text == "a\nB\nhook\nc\n"
    assert np_.patch_text(text, "B\n", "B\nhook\n", "f") == (text, False)          # already there
    with pytest.raises(RuntimeError, match="found 0"):
        np_.patch_text("nothing", "B\n", "B\nhook\n", "f")
    with pytest.raises(RuntimeError, match="found 2"):
        np_.patch_text("B\nB\n", "B\n", "B\nX\n", "f")


def test_patch_tree_adds_the_bridge_hooks_and_cpu_fixes(tmp_path):
    src = fake_tree(tmp_path / "src")
    changed = np_.patch_tree(src, PORT, arch="aarch64")
    assert set(changed) == {"port/src/gbox_bridge.c", "src/boss.c", "port/src/input.c",
                            "assets/animationtable_data.h", "src/game/bg.c"}
    assert "gboxBridgeTick();" in (src / "src/boss.c").read_text()
    assert "gboxBridgeSeat(idx, &button, &sx, &sy);" in (src / "port/src/input.c").read_text()
    assert "specialportalarray + sizeof(specialportalarray)" in (src / "src/game/bg.c").read_text()
    assert (src / "port/src/gbox_bridge.c").read_bytes() == (np_.GBOX_ROOT / PORT.bridge).read_bytes()
    assert np_.patch_tree(src, PORT, arch="aarch64") == []                         # idempotent
    x86 = fake_tree(tmp_path / "x86")
    assert "src/game/bg.c" not in np_.patch_tree(x86, PORT, arch="x86_64")         # fixes are per CPU


def test_hook_anchors_name_the_bridge_entry_points():
    c = (np_.GBOX_ROOT / PORT.bridge).read_text()
    for _rel, _old, new in PORT.hooks:
        name = "gboxBridgeTick" if "Tick" in new else "gboxBridgeSeat"
        assert name in new and name in c


def test_pin_ini_sets_keys_keeps_the_rest(tmp_path):
    ini = tmp_path / "ge007.ini"
    ini.write_text("[Input]\nMPMode = 0\nNaturalPitch = 1\n[Video]\nMSAA = 2\n")
    assert np_.pin_ini(ini, PORT.ini)
    text = ini.read_text()
    assert "NaturalPitch = 0" in text and "MouseEnabled = 0" in text and "MPMode = 0" in text and "MSAA = 2" in text
    assert "VSync = 0" in text and "[Window]\nWidth = 960\nHeight = 720" in text
    assert not np_.pin_ini(ini, PORT.ini)                                          # nothing left to change
    fresh = tmp_path / "new" / "ge007.ini"
    assert np_.pin_ini(fresh, {"Input": {"NaturalPitch": "0"}}) and fresh.read_text() == "[Input]\nNaturalPitch = 0\n"


def rom_entry(gid, title="GoldenEye 007", region="US", kind="emulator", library="quickswap-n64"):
    launch = {"kind": kind, "platform": "n64", "path": f"/roms/{title}.zip"}
    if kind == "emulator":
        launch["archive_member"] = f"{title} (USA).z64"
    return {"game_id": gid, "title": title, "platform": "n64", "region": region, "source_paths": [f"/roms/{title}.zip"],
            "library": library, "rel_path": f"{title}.zip", "format": "zip", "profile_id": gid, "launch": launch}


def test_catalog_gets_one_port_entry_for_an_owned_us_rom():
    rows = [rom_entry("hs1", "007: GoldenEye (USA)", kind="attract", library="hyperspin"),
            rom_entry("qs1"), rom_entry("eu1", "007 - GoldenEye (Europe)", region="EU"),
            rom_entry("mk1", "Mario Kart 64")]
    out = np_.catalog_entries(rows)
    assert len(out) == 1
    e = out[0]
    assert e.title == PORT.title and e.platform == "n64" and e.system == "Native PC ports"
    assert e.launch["kind"] == "native_port" and e.launch["port"] == "ge007"
    assert e.launch["base_game_id"] == "qs1"                                       # the ROM file beats the attract row
    assert e.launch["archive_member"] == "GoldenEye 007 (USA).z64"
    assert e.library == "quickswap-n64" and e.rel_path == "GoldenEye 007.zip"
    assert e.game_id == np_.entry_id(PORT) == e.profile_id and len(e.game_id) == 16
    hs_only = np_.catalog_entries([rom_entry("hs1", "007: GoldenEye (USA)", kind="attract", library="hyperspin")])
    assert hs_only[0].game_id == e.game_id and hs_only[0].library == "hyperspin"   # same entry from a partial scan
    assert np_.catalog_entries([e.model_dump()]) == []                             # never a port of a port
    assert np_.catalog_entries([rom_entry("eu1", "007 - GoldenEye (Europe)", region="EU")]) == []


def test_for_game_hands_port_entries_to_the_port_adapter(tmp_path):
    cfg = Config(data_dir=tmp_path)
    e = np_.catalog_entries([rom_entry("qs1")])[0].model_dump()
    ad = adapters.for_game(e, cfg)
    assert isinstance(ad, np_.PortAdapter) and ad.port is PORT and ad.port_id == "ge007"
    assert {"launch_game", "stop_game", "get_frame", "send_input"} <= ad.supported
    assert ("stream_session" in ad.supported) == (np_.HOST_OS == "linux")   # Windows: a docked local window


def test_rom_must_be_one_the_port_builds_for(tmp_path):
    rom = tmp_path / "fake.z64"
    rom.write_bytes(b"\x80\x37\x12\x40" + bytes(4092))
    with pytest.raises(ValueError, match="SHA-1"):
        np_.rom_bytes(rom, PORT)


class Recorder:
    """subprocess.run stand-in: records argv; 'clone' makes a source tree, '--build' makes the binary."""

    def __init__(self, cfg, port):
        self.cfg, self.port, self.calls = cfg, port, []

    def __call__(self, argv, cwd=None, capture_output=True, text=True, timeout=None):
        argv = [str(a) for a in argv]
        self.calls.append((argv, cwd))
        if "clone" in argv:
            fake_tree(Path(argv[-1]))
            (Path(argv[-1]) / ".git").mkdir()
        if "--build" in argv:
            exe = np_.exe_path(self.cfg, self.port)
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"\x7fELF")
        for a in argv:
            if a.endswith("_emit.py"):
                for s in self.port.sidecars:
                    (Path(cwd) / s).parent.mkdir(parents=True, exist_ok=True)
                    (Path(cwd) / s).write_bytes(b"x")
        return subprocess.CompletedProcess(argv, 0, "", "")


def test_build_clones_the_pinned_commit_patches_and_compiles_politely(tmp_path, monkeypatch):
    monkeypatch.setattr(np_, "HOST_OS", "linux")
    monkeypatch.setattr(np_.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(np_, "machine", lambda: "aarch64")
    cfg = Config(data_dir=tmp_path)
    rec = Recorder(cfg, PORT)
    st = np_.build(cfg, PORT, jobs=4, run=rec)
    argvs = [a for a, _cwd in rec.calls]
    assert argvs[0][:3] == ["git", "clone", "--filter=blob:none"] and argvs[0][3] == PORT.repo
    assert any(a[-3:] == ["checkout", "--force", "--detach"] or a[-1] == PORT.commit for a in argvs)
    assert ["git", "-C", str(np_.source_dir(cfg, PORT)), "checkout", "--force", "--detach", PORT.commit] in argvs
    compile_ = next(a for a in argvs if "--build" in a)
    assert compile_[:5] == ["nice", "-n", "19", "ionice", "-c3"] and compile_[-2:] == ["-j", "4"]
    configure = next(a for a in argvs if "-S" in a)
    assert f"-DROMID={PORT.romid}" in configure
    assert st["built"] and set(st["patched"]) >= {"src/boss.c", "port/src/input.c", "src/game/bg.c"}


def test_build_is_not_automated_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(np_, "HOST_OS", "windows")
    with pytest.raises(np_.ToolUnavailable, match="MSYS2"):
        np_.build(Config(data_dir=tmp_path), PORT, run=Recorder(None, PORT))


def test_prepare_copies_the_rom_runs_the_converters_once_and_pins_the_ini(tmp_path, monkeypatch):
    monkeypatch.setattr(np_, "HOST_OS", "linux")
    monkeypatch.setattr(np_.shutil, "which", lambda name: f"/usr/bin/{name}")
    data = b"\x80\x37\x12\x40" + bytes(4092)
    port = dataclasses.replace(PORT, rom_sha1=(hashlib.sha1(data).hexdigest(),))
    rom = tmp_path / "GoldenEye 007 (USA).zip"
    with zipfile.ZipFile(rom, "w") as z:
        z.writestr("GoldenEye 007 (USA).z64", data)
    cfg = Config(data_dir=tmp_path / "d")
    rec = Recorder(cfg, port)
    out = np_.prepare(cfg, port, rom, run=rec)
    src = np_.source_dir(cfg, port)
    assert (src / "data" / port.rom_name).read_bytes() == data and out["converted"] and out["ini_pinned"]
    conv = [a for a, _ in rec.calls]
    assert len(conv) == 3 and all(a[:5] == ["nice", "-n", "19", "ionice", "-c3"] and a[5] == sys.executable for a in conv)
    assert "NaturalPitch = 0" in (src / "data" / "ge007.ini").read_text()
    rec.calls.clear()
    assert not np_.prepare(cfg, port, rom, run=rec)["converted"] and rec.calls == []   # done once


class FakeBridge:
    def __init__(self):
        self.mm, self.calls = bytearray(8), []

    def drive(self, seat, buttons=0, sx=0, sy=0):
        self.calls.append(("drive", seat, buttons, sx, sy))

    def release(self, seat):
        self.calls.append(("release", seat))


def test_streamed_pad_reaches_player_one_through_the_bridge(tmp_path):
    ad = np_.PortAdapter(Config(data_dir=tmp_path), {"launch": {"port": "ge007"}})
    ad.bridge = FakeBridge()
    ad.send_input([{"key": "b", "down": True}, {"key": "lup", "down": True}, {"key": "rleft", "down": True},
                   {"key": "l2", "down": True, "player": 2}])          # player 2 is a bot seat: ignored
    assert ad.bridge.calls[-1] == ("drive", 0, 0x8000 | 0x0002, 0, 80)
    ad.send_input([{"key": "b", "down": False}, {"key": "lup", "down": False}, {"key": "rleft", "down": False}])
    assert ad.bridge.calls[-1] == ("drive", 0, 0, 0, 0) and not ad.held


def test_bridge_names_are_per_session():
    a, b = np_.bridge_name(PORT, "1-2"), np_.bridge_name(PORT, "1-3")
    assert a != b and "gbox-ge007-1-2" in a


def test_native_port_tool_is_registered_with_status():
    from gbox.registry import REGISTRY
    t = REGISTRY["native_port"]
    assert t.platforms == ["linux", "windows"] and "native-port" in t.capabilities

    class Ctx:
        config = Config(data_dir=Path("unused-data"))
        progress = staticmethod(lambda pct, msg: None)
    out = native_ports_status = t.fn(t.In(op="status"), Ctx())
    assert out["op"] == "status" and out["result"]["port"] == "ge007" and native_ports_status["result"]["built"] is False
    with pytest.raises(ValueError):
        t.fn(t.In(op="status", port="nope"), Ctx())


def test_scan_lists_the_port_and_a_play_goes_to_the_linux_worker(plane, cfg, tmp_path):
    lib = tmp_path / "n64"
    lib.mkdir()
    with zipfile.ZipFile(lib / "GoldenEye 007 (USA).zip", "w") as z:
        z.writestr("GoldenEye 007 (USA).z64", b"\x80\x37\x12\x40" + bytes(4092))
    cfg.libraries.append(Library(id="n64", kind="files", paths={"windows": str(lib), "linux": str(lib)}))
    job = run_job(plane, "scan_library", {"include_steam": False})
    assert job["state"] == "succeeded", job
    hits = plane.get("/api/catalog", params={"q": "PC port"}).json()["items"]
    assert len(hits) == 1 and hits[0]["launch"]["kind"] == "native_port" and hits[0]["platform"] == "n64"
    launch = plane.post(f"/api/games/{hits[0]['game_id']}/launch").json()
    assert launch["require_os"] == "linux" and launch["tool"] == "launch_game"
