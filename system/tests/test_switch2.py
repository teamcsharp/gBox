"""gbox.switch2: engine choice, key installation, game-argument resolution and a launch plan without starting anything."""
import json
import struct
from pathlib import Path

import pytest

from gbox import catalog, switch2, switch_nup
from gbox.config import Config

FIXTURE = Path(__file__).parent / "fixtures" / "sample_game.nup"
OOT = "0400486024DEC000"


def fake_engine(root: Path, name: str) -> Path:
    folder = root / name / "Fritchii-v0"
    folder.mkdir(parents=True)
    (folder / "lichii.exe").write_bytes(b"MZ")
    (folder / "user").mkdir()
    return folder


def cfg_for(tmp_path: Path, **overrides) -> Config:
    engine = fake_engine(tmp_path / "switch2", "fritchii")
    keys = tmp_path / "prod.keys"
    keys.write_text("master_key_00 = 00000000000000000000000000000000\n")
    (tmp_path / "title.keys").write_text("0400486024DEC000 = 00000000000000000000000000000000\n")
    values = dict(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", switch2_root=str(tmp_path / "switch2"),
                  switch2_fritchii=str(engine), switch2_keys=str(keys))
    values.update(overrides)
    return Config(**values)


def game(**extra) -> dict:
    return {"game_id": "g1", "platform": "switch", "format": "nup", "serial": OOT,
            "launch": {"switch_generation": 2, "title_id": OOT}, **extra}


def test_is_game_only_says_yes_to_switch2_rows():
    assert switch2.is_game(game())
    assert switch2.is_game({"platform": "switch", "format": "nup", "serial": "0400E88025B1A000"})
    assert switch2.is_game({"platform": "switch", "format": "switch_dump"})
    assert switch2.is_game({"platform": "switch", "launch": {"switch_generation": 2}})
    assert switch2.is_game({"platform": "switch", "serial": "0400C3F00006E000"})
    assert not switch2.is_game({"platform": "switch", "serial": "01002A000CD48000",
                                "launch": {"switch_generation": 1}})
    # a Switch 1 NUP is still a Switch 1 game: the explicit generation wins over the container format
    assert not switch2.is_game({"platform": "switch", "format": "nup", "serial": "0100123456789ABC",
                                "launch": {"switch_generation": 1}})
    assert not switch2.is_game({"platform": "switch", "format": "nsp", "serial": "01002A000CD48000"})
    assert not switch2.is_game({"platform": "ps4", "serial": OOT})


def test_engine_for_prefers_hookshot_only_when_built(tmp_path):
    cfg = cfg_for(tmp_path)
    assert switch2.engine_for(cfg, game()) == "fritchii"
    game_dir = switch2.hookshot_game(cfg)
    game_dir.mkdir(parents=True)
    (game_dir / "Hookshot.exe").write_bytes(b"MZ")
    assert switch2.engine_for(cfg, game()) == "hookshot"
    assert switch2.engine_for(cfg_for(tmp_path / "b", switch2_engine="lichii"), game()) == "lichii"


def test_keys_are_copied_into_the_portable_user_folder(tmp_path):
    cfg = cfg_for(tmp_path)
    copied = switch2.install_keys(cfg, "fritchii")
    assert copied == ["prod.keys", "title.keys"]
    keys_dir = switch2.engine_home(cfg, "fritchii") / "user" / "keys"
    assert (keys_dir / "prod.keys").is_file() and (keys_dir / "title.keys").is_file()
    assert switch2.install_keys(cfg, "fritchii") == []          # unchanged: nothing copied twice


def test_game_arg_for_nup_nsp_and_extracted_dumps(tmp_path):
    cfg = cfg_for(tmp_path)
    assert switch2.game_arg(cfg, game(), FIXTURE) == str(FIXTURE)
    nsp = tmp_path / "Mario Kart World [0400C3F00006E000].nsp"
    nsp.write_bytes(b"PFS0")
    assert switch2.game_arg(cfg, game(), nsp) == str(nsp)
    dump = tmp_path / "DonkeyKongBananza"
    (dump / "base" / "exefs").mkdir(parents=True)
    (dump / "base" / "exefs" / "main").write_bytes(b"NSO0")
    (dump / "base" / "romfs").mkdir()
    assert switch2.game_arg(cfg, game(), dump) == str(dump / "base" / "exefs" / "main")
    flat = tmp_path / "Flat"
    (flat / "exefs").mkdir(parents=True)
    (flat / "exefs" / "main").write_bytes(b"NSO0")
    assert switch2.game_arg(cfg, game(), flat) == str(flat / "exefs" / "main")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no base/exefs/main"):
        switch2.game_arg(cfg, game(), empty)


def test_materialize_nup_option_extracts_a_loose_exefs(tmp_path):
    cfg = cfg_for(tmp_path, switch2_materialize_nup=True)
    arg = Path(switch2.game_arg(cfg, game(), FIXTURE))
    assert arg.name == "main" and arg.parent.name == "exefs"
    assert (arg.parent.parent / ".gbox-nup.json").is_file()
    assert switch2.game_arg(cfg, game(), FIXTURE) == str(arg)      # marker makes the second call free


def test_plan_launch_for_fritchii_uses_dash_g_and_the_portable_folder(tmp_path):
    cfg = cfg_for(tmp_path)
    plan = switch2.plan_launch(cfg, game(), FIXTURE)
    assert plan["engine"] == "fritchii"
    assert plan["argv"][1:] == ["-g", str(FIXTURE)]
    assert Path(plan["cwd"]).is_dir() and plan["argv"][0].lower().endswith("lichii.exe")
    assert (Path(plan["cwd"]) / "user" / "keys" / "prod.keys").is_file()
    assert set(plan["keys"]) == {"prod.keys", "title.keys"}


def test_plan_launch_for_hookshot_sets_the_control_bridge(tmp_path):
    home = tmp_path / "hookhome"
    (home / "Games" / "Hookshot").mkdir(parents=True)
    (home / "Games" / "Hookshot" / "Hookshot.exe").write_bytes(b"MZ")
    (home / "HookshotBuilder.exe").write_bytes(b"MZ")
    cfg = cfg_for(tmp_path, switch2_hookshot=str(home / "HookshotBuilder.exe"), switch2_engine="hookshot")
    plan = switch2.plan_launch(cfg, game(), FIXTURE)
    assert plan["engine"] == "hookshot"
    assert plan["argv"][1:3] == ["--play", str(home / "Games" / "Hookshot")]
    assert plan["env"]["HOS_CONTROL_MEM"] == "rw"
    assert "gbox-hookshot" in plan["env"]["HOS_CONTROL"]
    builder = tmp_path / "builder" / "HookshotBuilder.exe"
    builder.parent.mkdir()
    builder.write_bytes(b"MZ")
    with pytest.raises(FileNotFoundError, match="not built"):
        switch2.plan_launch(cfg_for(tmp_path / "b", switch2_hookshot=str(builder), switch2_engine="hookshot"),
                            game(), FIXTURE)


def test_npdm_program_id_is_read_at_the_aci0_offset(tmp_path):
    data = bytearray(b"META" + b"\x00" * 0x10 + b"ACI0" + b"\x00" * 12)
    data += (0x040074A01BF12000).to_bytes(8, "little")
    p = tmp_path / "main.npdm"
    p.write_bytes(data)
    assert switch_nup.npdm_title_id(p) == "040074A01BF12000"
    p.write_bytes(b"not an npdm")
    assert switch_nup.npdm_title_id(p) is None


def test_catalog_lists_an_extracted_switch2_dump_once(tmp_path):
    lib = tmp_path / "switch2"
    base = lib / "DonkeyKongBananza" / "base"
    (base / "exefs").mkdir(parents=True)
    (base / "exefs" / "main").write_bytes(b"NSO0")
    npdm = bytearray(b"META" + b"\x00" * 0x10 + b"ACI0" + b"\x00" * 12)
    npdm += (0x040074A01BF12000).to_bytes(8, "little")
    (base / "exefs" / "main.npdm").write_bytes(npdm)
    (base / "romfs").mkdir()
    (base / "romfs" / "data.bin").write_bytes(b"x")
    upd = lib / "DonkeyKongBananza" / "updates" / "65536"
    (upd / "exefs").mkdir(parents=True)
    (upd / "exefs" / "main").write_bytes(b"NSO0")
    entries, problems = catalog.scan([lib], {"switch": "configured"}, lib_id="switch2", do_hash=False,
                                     platform_hint="switch")
    assert problems == []
    assert len(entries) == 1, [e.title for e in entries]
    entry = entries[0]
    assert entry.format == "switch_dump" and entry.serial == "040074A01BF12000"
    assert entry.launch["switch_generation"] == 2 and entry.rel_path == "DonkeyKongBananza"
    assert switch2.is_game(entry.model_dump())


def test_switch_nsp_marks_a_04_title_as_generation_two(tmp_path):
    from gbox import switch_nsp

    def container(name, title_id):
        names = (name, f"{title_id}0000000000000000.tik")
        table = b"".join(n.encode() + b"\x00" for n in names)
        offsets = (0, len(names[0]) + 1)
        entries = b"".join(struct.pack("<QQII", i * 4, 4, off, 0) for i, off in enumerate(offsets))
        path = tmp_path / f"{title_id}.nsp"
        path.write_bytes(struct.pack("<4sIII", b"PFS0", 2, len(table), 0) + entries + table + b"AAAA" * 2)
        return path

    serial, extra = switch_nsp.catalog_fields(container("a.nca", "0400C3F00006E000"))
    assert serial == "0400C3F00006E000" and extra["switch_generation"] == 2
    serial, extra = switch_nsp.catalog_fields(container("a.nca", "01002A000CD48000"))
    assert serial == "01002A000CD48000" and extra["switch_generation"] == 1


def test_for_game_routes_switch2_and_leaves_switch1_on_yuzu(tmp_path):
    from gbox import adapters
    cfg = cfg_for(tmp_path)
    ad = adapters.for_game({"platform": "switch", "format": "nup", "serial": OOT, "game_id": "g1",
                            "launch": {"switch_generation": 2}}, cfg)
    assert isinstance(ad, adapters.Switch2Adapter)
    s1 = adapters.for_game({"platform": "switch", "format": "nsp", "serial": "01002A000CD48000", "game_id": "g2",
                            "launch": {"switch_generation": 1}}, cfg)
    assert isinstance(s1, adapters.YuzuAdapter) and not isinstance(s1, adapters.Switch2Adapter)


@pytest.fixture(autouse=True)
def _isolated_hookshot_home(monkeypatch, tmp_path):
    """Tests never read the machine's real %LOCALAPPDATA%\\HookshotBuilder (builder-settings.json, installed versions)."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
