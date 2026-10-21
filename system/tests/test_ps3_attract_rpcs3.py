"""#1093: HyperSpin PS3 ".txt" stubs boot their disc folder's EBOOT.BIN in gBox's RPCS3 (save states), not RocketLauncher.

On the test PCs every RocketLauncher run threw "RLDLL.Start - Exception thrown: -2" and exited 0 within ~15 s, and the
one direct RPCS3 attempt was handed the empty .txt stub itself and exited 1.
"""
import struct

import pytest

from gbox import adapters, catalog, tools
from gbox.config import Config, Library
from gbox.models import CatalogEntry
from gbox.registry import Ctx

STUB = "collections/Sony PlayStation 3/roms/Soul Calibur V (BLUS30736).txt"


def sfo(title_id: str) -> bytes:
    """Minimal PARAM.SFO with one utf8 TITLE_ID key (layout read by catalog.param_sfo)."""
    key, val = b"TITLE_ID\x00", title_id.encode() + b"\x00"
    kt = 20 + 16
    return (b"\x00PSF" + b"\x01\x01\x00\x00" + struct.pack("<III", kt, kt + len(key), 1)
            + struct.pack("<HHIII", 0, 0x0204, len(val), 16, 0) + key + val)


def make_disc(root, folder="Soul Calibur V (BLUS30736)", psn=False, stub_text=""):
    roms = root / "collections" / "Sony PlayStation 3" / "roms"
    game = roms / folder / ("" if psn else "PS3_GAME")
    (game / "USRDIR").mkdir(parents=True)
    (game / "USRDIR" / "EBOOT.BIN").write_bytes(b"SCE\x00")
    (game / "PARAM.SFO").write_bytes(sfo("BLUS30736"))
    stub = roms / "Soul Calibur V (BLUS30736).txt"
    stub.write_text(stub_text)
    return stub, game / "USRDIR" / "EBOOT.BIN"


def entry(rel=STUB) -> CatalogEntry:
    return CatalogEntry(
        game_id="bef7d283d27accc2", title="SoulCalibur V (USA)", platform="ps3", platform_confidence="collection",
        source_paths=[rel], library="hs", rel_path=rel, system="Sony PlayStation 3", collections=["Sony PlayStation 3"],
        core=None, hashes={}, size=0, format=rel.rsplit(".", 1)[-1], runtimes={"rocketlauncher": "windows-node"},
        launch={"kind": "attract", "library": "hs", "rel_path": rel, "emulator": "Sony PlayStation 3",
                "name": "Soul Calibur V (BLUS30736)"}, profile_id="bef7d283d27accc2")


def config(tmp_path) -> Config:
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    cfg.libraries.append(Library(id="hs", kind="attract", paths={"windows": str(tmp_path / "hs"), "linux": str(tmp_path / "hs")}))
    return cfg


def test_stub_resolves_disc_psn_and_named_folders(tmp_path):
    stub, eboot = make_disc(tmp_path / "a")                                   # empty stub: folder named like the stub
    assert catalog.ps3_stub_eboot(stub) == eboot
    assert catalog.ps3_title_id(eboot) == "BLUS30736"
    stub, eboot = make_disc(tmp_path / "b", psn=True)                         # PSN layout: <folder>/USRDIR/EBOOT.BIN
    assert catalog.ps3_stub_eboot(stub) == eboot and catalog.ps3_title_id(eboot) == "BLUS30736"
    stub, eboot = make_disc(tmp_path / "c", folder="BLUS30736", stub_text="BLUS30736\r\n")   # first line names the folder
    assert catalog.ps3_stub_eboot(stub) == eboot
    stub = tmp_path / "d" / "Missing (BLUS00000).txt"
    stub.parent.mkdir()
    stub.write_text("")
    assert catalog.ps3_stub_eboot(stub) is None and catalog.ps3_stub_eboot(tmp_path / "nope.txt") is None
    assert catalog.ps3_title_id(tmp_path / "x" / "USRDIR" / "EBOOT.BIN") is None


def test_ps3_txt_stub_routes_to_rpcs3_not_rocketlauncher(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    ad = adapters.for_game(entry().model_dump(), cfg)
    assert isinstance(ad, adapters.RPCS3Adapter) and {"save_state", "load_state"} <= ad.supported
    other = entry("collections/Sony PlayStation 3/roms/Some Game.7z")          # RocketLauncher's archive layout stays
    assert isinstance(adapters.for_game(other.model_dump(), cfg), adapters.RocketLauncherAdapter)
    monkeypatch.setattr(adapters, "HOST_OS", "linux")                          # the Spark: RPCS3's AppImage on Xvfb
    ad = adapters.for_game(entry().model_dump(), cfg)
    assert isinstance(ad, adapters.RPCS3LinuxAdapter) and {"send_input", "stream_session", "read_memory"} <= ad.supported
    monkeypatch.setattr(adapters, "HOST_OS", "darwin")
    with pytest.raises(adapters.ToolUnavailable, match="RPCS3 on a Windows or Linux node"):
        adapters.for_game(entry().model_dump(), cfg)


def test_launch_hands_rpcs3_the_eboot_not_the_stub(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    _, eboot = make_disc(tmp_path / "hs")
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    seen = {}

    class Booted(Exception):
        pass

    def fake_launch(self, rom):
        seen["rom"], seen["serial"] = rom, self.serial
        raise Booted

    monkeypatch.setattr(adapters.RPCS3Adapter, "launch_game", fake_launch)
    monkeypatch.setattr(tools, "SESSIONS", {})
    with pytest.raises(Booted):
        tools._launch_game(tools.LaunchIn(game=entry()), Ctx(cfg, job_id="j1", worker="w1"))
    assert seen == {"rom": str(eboot), "serial": "BLUS30736"}


def test_launch_reports_a_missing_disc_folder(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    stub = tmp_path / "hs" / STUB
    stub.parent.mkdir(parents=True)
    stub.write_text("")
    monkeypatch.setattr(adapters, "HOST_OS", "windows")
    monkeypatch.setattr(tools, "SESSIONS", {})
    with pytest.raises(FileNotFoundError, match="EBOOT.BIN"):
        tools._launch_game(tools.LaunchIn(game=entry()), Ctx(cfg, job_id="j2", worker="w1"))
