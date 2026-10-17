import os
import zipfile
from pathlib import Path

import pytest

from gbox import catalog, rom_archives


def make_disc(path, track_byte=0):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Disc/game.cue", 'FILE "track.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        z.writestr("Disc/track.bin", bytes([track_byte]) * 300000)
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


def test_staged_archive_reuses_extraction_after_lru_mtime_touch(tmp_path, cfg, monkeypatch):
    src = tmp_path / "Game.zip"
    make_disc(src)
    staged = Path(catalog.stage(src, "disc", cfg)["dst"])
    # Use an old access timestamp so the real staging reuse must change mtime,
    # independently of the filesystem clock resolution.
    os.utime(staged, ns=(1_000_000_000, 1_000_000_000))
    record = catalog._db_load(cfg.cache)[str(staged)]
    catalog._db_set(cfg.cache, str(staged), record | {"ident": catalog._ident(staged.stat())})
    before = staged.stat().st_mtime_ns
    boot = rom_archives.prepare(staged, cfg, "Disc/game.cue")
    extracted_mtime = boot.stat().st_mtime_ns

    reused = catalog.stage(src, "disc", cfg)
    assert not reused["copied"] and not reused["hashed"]
    assert staged.stat().st_mtime_ns != before
    monkeypatch.setattr(rom_archives, "members", lambda *_: pytest.fail("unchanged staged content must not unpack again"))
    assert rom_archives.prepare(staged, cfg, "Disc/game.cue") == boot
    assert boot.stat().st_mtime_ns == extracted_mtime


def test_restaged_same_size_content_gets_a_new_extraction(tmp_path, cfg):
    src = tmp_path / "Game.zip"
    make_disc(src)
    first = catalog.stage(src, "disc", cfg)
    staged = Path(first["dst"])
    old_boot = rom_archives.prepare(staged, cfg, "Disc/game.cue")
    previous = src.stat()
    make_disc(src, track_byte=1)
    os.utime(src, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    assert src.stat().st_size == previous.st_size

    changed = catalog.stage(src, "disc", cfg)
    assert changed["copied"] and changed["sha1"] != first["sha1"]
    boot = rom_archives.prepare(staged, cfg, "Disc/game.cue")
    assert boot != old_boot
    assert (boot.parent / "track.bin").read_bytes() == bytes([1]) * 300000
    assert (old_boot.parent / "track.bin").read_bytes() == bytes(300000)


def test_stale_stage_hash_cannot_reuse_changed_archive(tmp_path, cfg):
    src = tmp_path / "Game.zip"
    make_disc(src)
    staged = Path(catalog.stage(src, "disc", cfg)["dst"])
    boot = rom_archives.prepare(staged, cfg, "Disc/game.cue")
    previous = staged.stat()
    make_disc(staged, track_byte=2)
    os.utime(staged, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    assert staged.stat().st_size == previous.st_size
    assert catalog._db_load(cfg.cache)[str(staged)]["ident"] != catalog._ident(staged.stat())

    changed = rom_archives.prepare(staged, cfg, "Disc/game.cue")
    assert changed != boot
    assert (changed.parent / "track.bin").read_bytes() == bytes([2]) * 300000


def test_ordinary_archive_keeps_mtime_identity(tmp_path, cfg):
    src = tmp_path / "Game.zip"
    make_disc(src)
    boot = rom_archives.prepare(src, cfg, "Disc/game.cue")
    previous = src.stat()
    os.utime(src, ns=(previous.st_atime_ns, previous.st_mtime_ns + 1_000_000_000))
    assert rom_archives.prepare(src, cfg, "Disc/game.cue") != boot


def test_staged_content_identity_keeps_boot_member_distinct(tmp_path, cfg):
    src = tmp_path / "Game.zip"
    with zipfile.ZipFile(src, "w") as archive:
        archive.writestr("first.nes", b"NES\x1aFIRST")
        archive.writestr("second.nes", b"NES\x1aSECOND")
    staged = Path(catalog.stage(src, "disc", cfg)["dst"])
    first = rom_archives.prepare(staged, cfg, "first.nes")
    second = rom_archives.prepare(staged, cfg, "second.nes")
    assert first.parent != second.parent
    assert first.read_bytes() == b"NES\x1aFIRST" and second.read_bytes() == b"NES\x1aSECOND"


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
