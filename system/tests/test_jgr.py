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


def test_play_subobjects_record_table_sorted_by_address_and_contiguous():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    count, offsets, sizes = jgr.afs_entries(data)
    play_off = next(off for kind, off in jgr.chunks(data) if kind == "play")
    afs_size = sizes[offsets.index(play_off)]
    subs = jgr.play_subobjects(data, play_off, afs_size=afs_size)
    by_rel = sorted(subs, key=lambda s: s["relative"])
    for a, b in zip(by_rel, by_rel[1:]):
        assert a["offset"] + a["length"] == b["offset"]


def test_decode_submesh_produces_indexed_triangle_list_for_small_record():
    gdi = _gdi()
    if gdi is None:
        pytest.skip("JGR disc not present")
    data = _player_afs(gdi)
    count, offsets, sizes = jgr.afs_entries(data)
    play_off = next(off for kind, off in jgr.chunks(data) if kind == "play")
    afs_size = sizes[offsets.index(play_off)]
    subs = jgr.play_subobjects(data, play_off, afs_size=afs_size)
    # Pick the kind==1 record at relative offset 0x1b8d4 (observed to be self-contained).
    mesh = next(s for s in subs if s["kind"] == 1 and s["relative"] == 0x1B8D4)
    indices, verts = jgr.decode_submesh(mesh["bytes"])
    assert indices
    assert verts
    assert max(indices) < len(verts)
    assert len(indices) % 3 == 0
    xs, ys, zs = zip(*verts)
    assert max(xs) - min(xs) < 2.0
    assert max(ys) - min(ys) < 3.0
    assert max(zs) - min(zs) < 2.0


def test_container_header_rejects_unknown_magic():
    with pytest.raises(ValueError):
        jgr.container_header(b"XXXX" + struct.pack("<I", 3) + b"\x00" * 24, 0)
