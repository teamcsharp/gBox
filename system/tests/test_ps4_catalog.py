"""Extracted PS4 applications are identified by metadata, never by a .bin/.pkg suffix."""
import struct

import pytest
from fastapi.testclient import TestClient

from gbox import catalog, systems
from gbox.config import Config, TEMPLATE
from gbox.server import create_app


def sfo_bytes(**values):
    keys, data, indices = bytearray(), bytearray(), bytearray()
    for key, value in values.items():
        encoded = value.encode() + b"\0"
        indices += struct.pack("<HHIII", len(keys), 0x0204, len(encoded), len(encoded), len(data))
        keys += key.encode() + b"\0"
        data += encoded
    key_offset = 20 + len(indices)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, key_offset, key_offset + len(keys), len(values)) + indices + keys + data


def game_folder(path, **overrides):
    (path / "sce_sys").mkdir(parents=True)
    (path / "eboot.bin").write_bytes(b"\x7fELF" + bytes(100))
    values = {"TITLE_ID": "CUSA04437", "TITLE": "Resident Evil 5", "APP_VER": "01.00", "CATEGORY": "gd"}
    values.update(overrides)
    (path / "sce_sys" / "param.sfo").write_bytes(sfo_bytes(**values))
    return path / "eboot.bin"


def test_ps4_folder_scan_uses_sfo_and_does_not_index_assets(tmp_path):
    eboot = game_folder(tmp_path / "CUSA04437 (USA)")
    (eboot.parent / "asset.bin").write_bytes(b"asset")
    (eboot.parent / "bonus.nes").write_bytes(b"not a separate game")
    (eboot.parent / "sce_sys" / "icon0.png").write_bytes(b"image")
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    entries, problems = catalog.scan([tmp_path], {}, lib_id="owned-ps4")
    assert not problems
    assert len(entries) == 1
    entry = entries[0]
    assert entry.title == "Resident Evil 5"
    assert entry.platform == "ps4" and entry.serial == "CUSA04437"
    assert entry.region == "US" and entry.format == "ps4_folder"
    assert entry.launch == {"kind": "emulator", "platform": "ps4", "path": str(eboot),
                            "title_id": "CUSA04437", "app_ver": "01.00"}
    assert entry.runtimes == {"ps4": "shadps4"} and entry.core is None
    assert entry.source_paths == [str(eboot)] and entry.rel_path.endswith("/eboot.bin")
    assert before == {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}
    rescanned, _ = catalog.scan([tmp_path], {"ps4": "configured"}, lib_id="owned-ps4", do_hash=False)
    assert rescanned[0].game_id == entry.game_id
    assert rescanned[0].runtimes == {"ps4": "configured"}


def test_ps4_scan_accepts_uppercase_dump_paths(tmp_path):
    folder = tmp_path / "GAME"
    (folder / "SCE_SYS").mkdir(parents=True)
    (folder / "EBOOT.BIN").write_bytes(b"\x7fELF")
    (folder / "SCE_SYS" / "PARAM.SFO").write_bytes(sfo_bytes(TITLE_ID="CUSA03856", TITLE="Resident Evil 6"))
    entries, problems = catalog.scan([tmp_path], {})
    assert not problems and len(entries) == 1
    assert entries[0].serial == "CUSA03856"


@pytest.mark.parametrize("overrides, message", [
    ({"TITLE_ID": "BLUS30491"}, "CUSA title ID"),
    ({"TITLE_ID": "PPSA00001"}, "CUSA title ID"),
    ({"CATEGORY": "gp"}, "not standalone games"),
    ({"CATEGORY": "ac"}, "not standalone games"),
])
def test_ps4_metadata_rejects_other_platforms_updates_and_dlc(tmp_path, overrides, message):
    eboot = game_folder(tmp_path / "game", **overrides)
    (eboot.parent / "asset.bin").write_bytes(b"not a game")
    entries, problems = catalog.scan([tmp_path], {})
    assert not entries and len(problems) == 1
    assert message in problems[0]


@pytest.mark.parametrize("data", [b"", b"\0PSF", b"not SFO", b"\0PSF" + b"\xff" * 80,
                                  sfo_bytes(TITLE_ID="CUSA04437")[:-3]])
def test_malformed_sfo_becomes_scan_problem(tmp_path, data):
    eboot = game_folder(tmp_path / "bad")
    (eboot.parent / "sce_sys" / "param.sfo").write_bytes(data)
    entries, problems = catalog.scan([tmp_path], {})
    assert not entries and len(problems) == 1 and "invalid PS4" in problems[0]


def test_ps4_hint_does_not_turn_unrelated_bins_or_pkgs_into_games(tmp_path):
    (tmp_path / "eboot.bin").write_bytes(b"unidentified executable")
    (tmp_path / "unidentified.pkg").write_bytes(b"package")
    entries, problems = catalog.scan([tmp_path], {}, platform_hint="ps4")
    assert not entries and len(problems) == 2
    assert all("sce_sys/param.sfo" in p for p in problems)
    entries, _ = catalog.scan([tmp_path], {})
    assert all(e.platform != "ps4" for e in entries)


def package_bytes(expected_size=0x1000, **kwargs):
    head = bytearray(0x1000)
    head[:4] = kwargs.get("magic", b"\x7fCNT")
    head[0x40:0x64] = b"UP0102-CUSA04437_00-0123456789ABCDEF"
    struct.pack_into(">Q", head, 0x430, expected_size)
    return bytes(head)


@pytest.mark.parametrize("expected,status", [(0x1000, "installation_required"), (0x8000, "copy_incomplete")])
def test_ps4_package_header_discovery_is_pending_and_bounded(tmp_path, monkeypatch, expected, status):
    package = tmp_path / "Resident Evil 5 (USA).pkg"
    package.write_bytes(package_bytes(expected))
    monkeypatch.setattr(catalog, "file_hashes", lambda *a: pytest.fail("must not hash a copying package"))
    entries, problems = catalog.scan([tmp_path], {}, do_hash=True)
    assert not problems and len(entries) == 1
    entry = entries[0]
    assert entry.serial == "CUSA04437" and entry.format == "ps4_pkg"
    assert entry.playable == status and entry.hashes == {}
    assert entry.launch["kind"] == "ps4_package"
    assert entry.launch["integrity"] == "not_verified"
    assert entry.launch["expected_size"] == expected
    assert entry.launch["observed_size"] == 0x1000


@pytest.mark.parametrize("data", [package_bytes()[:0x100], package_bytes(0x800),
                                  package_bytes() + b"extra"])
def test_partial_or_invalid_package_header_is_not_bootable(tmp_path, data):
    (tmp_path / "game.pkg").write_bytes(data)
    entries, problems = catalog.scan([tmp_path], {})
    assert entries == [] and len(problems) == 1


def test_ps3_pkg_is_not_ps4(tmp_path):
    (tmp_path / "PS3.pkg").write_bytes(package_bytes(magic=b"\x7fPKG"))
    entries, _ = catalog.scan([tmp_path], {})
    assert entries == []


def test_package_rescan_refreshes_pending_status_without_losing_gameplay_status(tmp_path):
    from gbox.store import Store
    package = tmp_path / "Resident Evil 5.pkg"
    package.write_bytes(package_bytes(0x2000))
    entries, _ = catalog.scan([tmp_path], {})
    store = Store(tmp_path / "database")
    gid = entries[0].game_id
    store.upsert_catalog([e.model_dump() for e in entries])
    assert store.catalog_get(gid)["playable"] == "copy_incomplete"
    with package.open("ab") as stream:
        stream.write(bytes(0x1000))
    entries, _ = catalog.scan([tmp_path], {})
    store.upsert_catalog([e.model_dump() for e in entries])
    assert store.catalog_get(gid)["playable"] == "installation_required"
    game = {"game_id": "real-game", "title": "Game", "platform": "ps4", "format": "ps4_folder", "playable": "launches (shadps4)"}
    store.upsert_catalog([game])
    store.upsert_catalog([game | {"playable": "untested"}])
    assert store.catalog_get("real-game")["playable"] == "launches (shadps4)"


def test_ps3_and_ps4_in_same_library_remain_distinct(tmp_path):
    game_folder(tmp_path / "PS4 game")
    ps3 = tmp_path / "PS3 game" / "PS3_GAME"
    (ps3 / "USRDIR").mkdir(parents=True)
    (ps3 / "USRDIR" / "EBOOT.BIN").write_bytes(b"SCE\0")
    (ps3 / "PARAM.SFO").write_bytes(sfo_bytes(TITLE_ID="BLUS30491", TITLE="Resident Evil 5 Gold"))
    entries, problems = catalog.scan([tmp_path], {})
    assert not problems and {e.platform for e in entries} == {"ps3", "ps4"}
    assert {e.serial for e in entries} == {"BLUS30491", "CUSA04437"}


def test_ps4_aliases_keep_ps5_separate():
    for name in ("Sony PlayStation 4", "PS4", "shadPS4"):
        assert systems.classify(name) == ("ps4", None, [])
    assert systems.classify("Sony PlayStation 5")[0] == "ps_modern"
    assert systems.classify("Sony PlayStation 3")[0] == "ps3"


def test_ps4_spoken_search_selects_ps4_release(cfg):
    app = create_app(cfg)
    app.state.store.upsert_catalog([
        {"game_id": "ps3-re5", "title": "Resident Evil 5", "platform": "ps3"},
        {"game_id": "ps4-re5", "title": "Resident Evil 5", "platform": "ps4"},
    ])
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    response = client.get("/api/catalog/best", params={"q": "Resident Evil 5 PS4"})
    assert response.status_code == 200
    assert response.json()[0]["game_id"] == "ps4-re5"


def test_ps4_config_example_parses():
    import tomllib
    Config(**tomllib.loads(TEMPLATE))
    cfg = Config(emulators={"ps4": {"adapter": "shadps4", "executable": "shadPS4", "stage_local": False}})
    assert cfg.emulators["ps4"].adapter == "shadps4"
