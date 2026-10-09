import zipfile
from pathlib import Path

import pytest

from gbox import catalog, rom_archives


def make_disc(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Disc/game.cue", 'FILE "track.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        z.writestr("Disc/track.bin", bytes(300000))
        z.writestr("Disc/audio.bin", bytes(500))
        z.writestr("readme.txt", "Not bootable")


def test_disc_archive_catalog_and_complete_cache(tmp_path, cfg):
    src = tmp_path / "Game (USA).zip"
    make_disc(src)
    entries, errors = catalog.scan([tmp_path], {}, lib_id="ps1", do_hash=False, platform_hint="psx")
    assert not errors and len(entries) == 1
    entry = entries[0]
    assert entry.platform == "psx" and entry.core == "pcsx_rearmed"
    assert entry.launch["archive_member"] == "Disc/game.cue"
    boot = rom_archives.prepare(src, cfg, entry.launch["archive_member"])
    assert boot.name == "game.cue" and (boot.parent / "track.bin").stat().st_size == 300000
    assert (boot.parent / "audio.bin").stat().st_size == 500
    before = boot.stat().st_mtime_ns
    assert rom_archives.prepare(src, cfg, entry.launch["archive_member"]) == boot
    assert boot.stat().st_mtime_ns == before
    with zipfile.ZipFile(src, "a") as z:
        z.writestr("new.txt", "Changed archive")
    assert rom_archives.prepare(src, cfg, entry.launch["archive_member"]) != boot


def test_scan_excludes_bios_and_supports_flat_roots(tmp_path):
    (tmp_path / "Game.nes").write_bytes(b"NES\x1a")
    (tmp_path / "bios").mkdir()
    (tmp_path / "bios" / "bios.bin").write_bytes(bytes(300000))
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "Other.nes").write_bytes(b"NES\x1a")
    make_disc(tmp_path / "Console BIOS.zip")
    entries, errors = catalog.scan([tmp_path], {}, do_hash=False, platform_hint="nes",
                                  exclude_dirs=["bios"], exclude_files=["*bios*"])
    assert not errors and len(entries) == 2
    entries, errors = catalog.scan([tmp_path], {}, do_hash=False, recursive=False, exclude_files=["*bios*"])
    assert not errors and len(entries) == 1


def test_archive_rejects_escape_and_never_publishes_failure(tmp_path, cfg):
    src = tmp_path / "bad.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("../escape.nes", b"NES\x1a")
    with pytest.raises(ValueError, match="Unsafe"):
        rom_archives.prepare(src, cfg, "game.nes")
    assert not (cfg.runtime / "extract").exists()
    make_disc(src)
    with pytest.raises(ValueError, match="missing"):
        rom_archives.prepare(src, cfg, "missing.cue")
    assert not (cfg.runtime / "extract").exists()


def test_gdi_preferred_to_cue_and_large_track():
    assert rom_archives.boot_member([{"name": "Disc/g.cue", "size": 200},
        {"name": "Disc/track.bin", "size": 1000000}, {"name": "Disc/g.gdi", "size": 100}]) == "Disc/g.gdi"


def test_ps2_cd_header_overrides_small_size():
    data = bytearray(0x50000)
    data[0x8001:0x8006], data[0x8008:0x8013] = b"CD001", b"PLAYSTATION"
    data[0x9000:0x9011] = b"BOOT2=cdrom0:\\SLUS"
    platform, metadata = catalog.sniff_head(bytes(data), 600000000)
    assert platform == "ps2" and metadata["boot_platform"] == "ps2"


def test_renamed_track_repaired_only_in_extracted_copy(tmp_path, cfg):
    src = tmp_path / "game.zip"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("game.cue", 'FILE "game (USA).bin" BINARY\n')
        z.writestr("game.bin", bytes(1000))
    original = src.read_bytes()
    cue = rom_archives.prepare(src, cfg, "game.cue")
    assert '"game.bin"' in cue.read_text()
    assert src.read_bytes() == original
