from pathlib import Path

from gbox.config import Config, HOST_OS, Library
from gbox.offline import cache_entries, local_config, index_local
from gbox.store import Store


def test_local_config_isolates_server_and_preserves_emulators(tmp_path):
    source = Config(data_dir=tmp_path / "original", api_host="0.0.0.0", public_url="http://spark:8765")
    source.showcase.enabled = True
    cfg = local_config(source, tmp_path / "offline", 18766)
    assert cfg.data_dir != source.data_dir
    assert cfg.api_host == "127.0.0.1"
    assert cfg.public_url == "http://127.0.0.1:18766"
    assert cfg.runtime == source.runtime
    assert cfg.cache == source.cache
    assert not cfg.showcase.enabled and not cfg.hermes.grunt.enabled
    assert source.showcase.enabled
    assert source.libraries == []


def test_cache_keeps_game_identity_and_uses_local_launch_path(tmp_path):
    cfg = local_config(Config(data_dir=tmp_path), tmp_path / "offline", 18766)
    gid = "0123456789abcdef"
    folder = cfg.cache / gid
    folder.mkdir(parents=True)
    game = folder / "Example (USA).nes"
    game.write_bytes(b"NES\x1a" + bytes(64))
    (folder / "unfinished.nes.part").write_bytes(b"partial")
    mods = cfg.cache / "mods" / gid
    mods.mkdir(parents=True)
    (mods / "unfinished.nes").write_bytes(b"NES\x1a" + bytes(64))
    rows = list(cache_entries(cfg))
    assert len(rows) == 1
    row = rows[0]
    assert row["game_id"] == row["profile_id"] == gid
    assert row["source_paths"] == [str(game)]
    assert row["launch"]["path"] == str(game)
    assert cfg.library(row["library"]).root() / row["rel_path"] == game


def test_chd_platform_maps_to_playstation_core(tmp_path, monkeypatch):
    cfg = local_config(Config(data_dir=tmp_path), tmp_path / "offline", 18766)
    folder = cfg.cache / "0123456789abcdef"
    folder.mkdir(parents=True)
    (folder / "Game.chd").write_bytes(b"MComprHD" + bytes(128))
    monkeypatch.setattr("gbox.offline.chd_platform", lambda _: "ps1")
    row, = list(cache_entries(cfg))
    assert row["platform"] == row["system"] == "psx"
    assert row["core"] == row["launch"]["core"] == "pcsx_rearmed"


def test_rescan_keeps_cached_ids_and_excludes_mod_workspaces(tmp_path):
    import gzip
    import json
    from gbox.registry import Ctx
    from gbox.tools import scan_library, ScanIn
    cfg = local_config(Config(data_dir=tmp_path), tmp_path / "offline", 18766)
    folder = cfg.cache / "0123456789abcdef"
    folder.mkdir(parents=True)
    (folder / "Game.nes").write_bytes(b"NES\x1a" + bytes(64))
    mods = cfg.cache / "mods"
    mods.mkdir()
    (mods / "Unfinished.nes").write_bytes(b"NES\x1a" + bytes(64))
    ctx = Ctx(cfg)
    result = scan_library(ScanIn(include_steam=False), ctx)
    artifact = next(blob for name, blob, *_ in ctx.artifacts if name == "catalog.jsonl.gz")
    rows = [json.loads(line) for line in gzip.decompress(artifact).splitlines()]
    assert result["count"] == 1
    assert rows[0]["game_id"] == folder.name


def test_cached_library_is_ready_before_unreachable_library(tmp_path, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    original = Path.is_dir
    unavailable = tmp_path / "unavailable"
    def is_dir(path):
        if path == unavailable:
            entered.set()
            release.wait(5)
            return False
        return original(path)
    monkeypatch.setattr(Path, "is_dir", is_dir)
    cfg = local_config(Config(data_dir=tmp_path, libraries=[
        Library(id="nas", paths={HOST_OS: str(unavailable)})]), tmp_path / "offline", 18766)
    folder = cfg.cache / "0123456789abcdef"
    folder.mkdir(parents=True)
    (folder / "Game.nes").write_bytes(b"NES\x1a" + bytes(64))
    store = Store(cfg.data_dir)
    try:
        index_local(cfg, store)
        assert entered.wait(1)
        assert store.catalog_get(folder.name)["platform"] == "nes"
    finally:
        release.set()
