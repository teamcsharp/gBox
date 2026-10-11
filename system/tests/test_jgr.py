"""Focused checks for the JGR Dreamcast reader foundation (gbox/jgr.py).

These gate on the owned disc, like the DOA2 suite: they run only when the extracted GD-ROM is
present (env JGR_GDI or the default cache path), otherwise they skip. They verify the archive and
container-header plumbing against the real PLAYER.AFS, not a synthetic stand-in.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import jgr
from gbox.gdrom import GDRom

_DEFAULT_GDI = "/home/ehm_eckx/gbox-cache/dc/4187aeab4d67638c/disc.gdi"


def _gdi():
    p = Path(os.environ.get("JGR_GDI", _DEFAULT_GDI))
    return p if p.is_file() else None


def _player_afs(gdi):
    return GDRom(str(gdi)).read("JETRADIO/PLAYER.AFS")


def test_afs_header_parses_owned_player_archive():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    count, offsets, sizes = jgr.afs_entries(data)
    assert count == 34
    assert len(offsets) == 34 and len(sizes) == 34
    # First offset points at the first PLAY chunk; its magic is intact.
    assert data[offsets[0]:offsets[0] + 4] == b"PLAY"


def test_chunks_finds_play_ptex_and_main():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    found = jgr.chunks(data)
    kinds = [k for k, _ in found]
    assert kinds.count("play") == 8
    assert kinds.count("ptex") == 8
    assert kinds.count("main") == 1
    assert len(found) == 17


def test_play_container_header_decodes_record_table():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    off = next(off for kind, off in jgr.chunks(data) if kind == "play")
    magic, recs = jgr.container_header(data, off)
    assert magic == b"PLAY"
    assert len(recs) == 12
    assert recs[0] == (108, 1)
    assert recs[-1] == (812880, 0)


def test_ptex_container_header_decodes():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    off = next(off for kind, off in jgr.chunks(data) if kind == "ptex")
    magic, recs = jgr.container_header(data, off)
    assert magic == b"PTEX"
    assert len(recs) > 0


def test_inventory_lists_player_and_enemy_archives():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    inv = jgr.inventory(str(gdi))
    assert "JETRADIO/PLAYER.AFS" in inv
    assert "JETRADIO/ENEMY.AFS" in inv
    assert len(inv["JETRADIO/PLAYER.AFS"]) == 17


def test_afs_entries_rejects_non_archive():
    with pytest.raises(ValueError):
        jgr.afs_entries(b"\x00" * 64)


def test_container_header_rejects_unknown_magic():
    with pytest.raises(ValueError):
        jgr.container_header(b"XXXX" + struct.pack("<I", 3) + b"\x00" * 24, 0)
