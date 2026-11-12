"""gbox.switch_import: card scan, copy into the switch2 library, NUP extraction and the card watcher."""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import switch_import, tools
from gbox.config import Config

FIXTURE = Path(__file__).parent / "fixtures" / "sample_game.nup"


def card(tmp_path: Path) -> Path:
    folder = tmp_path / "card"
    folder.mkdir()
    shutil.copy2(FIXTURE, folder / "Sample Game.nup")
    (folder / "partial.nup.part").write_bytes(b"x")
    (folder / "tiny.nsp").write_bytes(b"x")
    return folder


def test_scan_finds_titles_and_ignores_partials_and_small_files(tmp_path):
    folder = card(tmp_path)
    rows = switch_import.find_titles(folder, min_mb=0)
    assert [p.name for p in rows] == ["Sample Game.nup"]
    assert switch_import.find_titles(folder, min_mb=4) == []          # the fixture is 3.5 KB
    assert switch_import.find_titles(tmp_path / "missing") == []


def test_import_copies_hashes_dedupes_and_extracts(tmp_path):
    folder = card(tmp_path)
    out = switch_import.import_titles([folder], tmp_path / "library", extract=True,
                                      games_dir=tmp_path / "games", min_mb=0)
    assert out["found"] == 1 and out["copied"] == 1
    row = out["titles"][0]
    assert row["copied"] and len(row["sha256"]) == 64
    assert (tmp_path / "library" / "Sample Game.nup").is_file()
    extracted = Path(row["extracted"]["folder"])
    assert (extracted / "exefs" / "main").is_file() and (extracted / "romfs").is_dir()
    assert (extracted / ".gbox-nup.json").is_file()
    again = switch_import.import_titles([folder], tmp_path / "library", min_mb=0)
    assert again["copied"] == 0


def test_watch_imports_the_card_that_is_already_inserted(tmp_path):
    folder = card(tmp_path)
    out = switch_import.watch_titles(tmp_path / "library", sources=[folder], min_mb=0, timeout_s=5,
                                     interval_s=1, extract=True, games_dir=tmp_path / "games")
    assert out["copied"] == 1 and out["root"] == str(folder)
    assert (tmp_path / "games").is_dir()


def test_watch_without_media_times_out(tmp_path):
    with pytest.raises(TimeoutError, match="no Switch title"):
        switch_import.watch_titles(tmp_path / "library", sources=[], all_drives=False, timeout_s=0.2,
                                   interval_s=1, min_mb=0)


def test_tool_scan_import_watch_and_extract(tmp_path):
    folder = card(tmp_path)
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", switch2_root=str(tmp_path / "switch2"))
    ctx = SimpleNamespace(config=cfg, server=None, headers={}, progress=lambda *a: None)
    scanned = tools.switch_import_tool(tools.SwitchImportIn(op="scan", source=str(folder), min_mb=0), ctx)
    assert scanned["result"]["titles"][0]["bytes"] == FIXTURE.stat().st_size
    imported = tools.switch_import_tool(tools.SwitchImportIn(op="import", source=str(folder),
                                                             dest=str(tmp_path / "lib"), min_mb=0, scan=False), ctx)
    assert imported["result"]["copied"] == 1 and imported["result"]["scan_job"] is None
    watched = tools.switch_import_tool(tools.SwitchImportIn(op="watch", source=str(folder), dest=str(tmp_path / "lib2"),
                                                            min_mb=0, timeout_s=5, scan=False), ctx)
    assert watched["result"]["op"] == "watch" and watched["result"]["copied"] == 1
    extracted = tools.switch_import_tool(tools.SwitchImportIn(op="extract", source=str(FIXTURE),
                                                              games=str(tmp_path / "games")), ctx)
    assert extracted["result"]["has_exefs"] and extracted["result"]["has_romfs"]


def test_installed_content_detects_a_switch_sd_layout(tmp_path):
    concat = tmp_path / "Nintendo" / "Contents" / "registered" / "00000000" / "abc.nca.CONCAT"
    concat.mkdir(parents=True)
    (concat / "00").write_bytes(b"NAX1")
    info = switch_import.installed_content(tmp_path)
    assert info["content_groups"] == 1 and info["nca_concat"] == 1 and info["tickets"] == 0
    assert "not a NUP/NSP" in info["note"]
