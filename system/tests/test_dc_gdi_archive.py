"""Archived-GDI Dreamcast source path (characters._dc_gdi) and the DOA2 US .7z entry.

The .7z branch of characters._dc_gdi extracts an owned archived GDI set once
(flattening tracks beside disc.gdi, the layout GDRom reads), so the DOA2 US
catalog entry (a .7z, game 3dd7e33362597f85) can be read by the shared doa2
pipeline instead of failing with "needs a GDI, or a CHD plus chdman".

The archive tests need the 7z CLI and are skipped without it; the inventory
smoke test is skipped unless the extracted disc set is present
(GBOX_DOA2_US_7Z_GDI, default: the _dc_gdi cache copy).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import characters as C

GAME = {"game_id": "3dd7e33362597f85", "title": "Dead or Alive 2"}
US_FIRST_READ_SHA256 = "105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85"
OWNED_GDI = Path(os.environ.get("GBOX_DOA2_US_7Z_GDI",
                                Path.home() / "gbox-cache" / "dc" / GAME["game_id"] / "disc.gdi"))
needs_7z = pytest.mark.skipif(shutil.which("7z") is None, reason="7z CLI not installed on this node")


class _Ctx:
    def __init__(self, cache: str):
        self.config = SimpleNamespace(cache=cache)

    def progress(self, p: int, m: str) -> None:  # noqa: ARG002
        pass


def _make_7z(tmp: Path) -> Path:
    """A synthetic archived GDI set: one .gdi descriptor inside a .7z."""
    raw = tmp / "raw"
    raw.mkdir()
    (raw / "Game (US)[!].gdi").write_text(
        "3\n1 0 4 2352 track01.bin 0\n2 45000 0 2352 track02.raw 0\n3 45001 4 2352 track03.bin 0\n")
    archive = tmp / "disc.7z"
    subprocess.run(["7z", "a", "-bd", str(archive), str(raw / "Game (US)[!].gdi")],
                   check=True, capture_output=True)
    return archive


@needs_7z
def test_dc_gdi_extracts_7z_archive_once(tmp_path: Path, monkeypatch) -> None:
    archive = _make_7z(tmp_path)
    cache = tmp_path / "cache"
    monkeypatch.setattr(C, "_rom", lambda ctx, game: archive)

    out = C._dc_gdi(_Ctx(str(cache)), GAME)
    assert out == cache / "dc" / GAME["game_id"] / "disc.gdi"
    assert out.exists()
    assert "3\n1 0 4 2352 track01.bin 0" in out.read_text()
    assert (out.parent / "Game (US)[!].gdi").exists()          # tracks stay beside disc.gdi

    # Second call reuses the extracted copy instead of re-extracting.
    archive.unlink()                                            # prove the cache is the source now
    out2 = C._dc_gdi(_Ctx(str(cache)), GAME)
    assert out2 == out and out2.exists()


def test_dc_gdi_accepts_extracted_directory(tmp_path: Path, monkeypatch) -> None:
    d = tmp_path / "set"
    d.mkdir()
    gdi = d / "Disc.gdi"
    gdi.write_text("3\n1 0 4 2352 track01.bin 0\n")
    monkeypatch.setattr(C, "_rom", lambda ctx, game: d)
    assert C._dc_gdi(_Ctx(str(tmp_path / "cache")), GAME) == gdi


def test_dc_gdi_directory_without_descriptor_raises(tmp_path: Path, monkeypatch) -> None:
    d = tmp_path / "set"
    d.mkdir()
    monkeypatch.setattr(C, "_rom", lambda ctx, game: d)
    with pytest.raises(ValueError, match="no .gdi descriptor"):
        C._dc_gdi(_Ctx(str(tmp_path / "cache")), GAME)


@needs_7z
def test_dc_gdi_7z_without_descriptor_raises(tmp_path: Path, monkeypatch) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "track01.bin").write_bytes(b"nope")
    archive = tmp_path / "disc.7z"
    subprocess.run(["7z", "a", "-bd", str(archive), str(raw / "track01.bin")],
                   check=True, capture_output=True)
    monkeypatch.setattr(C, "_rom", lambda ctx, game: archive)
    with pytest.raises(ValueError, match="no .gdi descriptor"):
        C._dc_gdi(_Ctx(str(tmp_path / "cache")), GAME)
    assert not (tmp_path / "cache" / "dc" / (GAME["game_id"] + ".part")).exists()


@pytest.mark.skipif(not OWNED_GDI.exists(), reason="owned DOA2 US .7z disc set not extracted on this node")
def test_doa2usa_inventory_build_identity_for_7z_entry() -> None:
    from gbox.doa2usa_inventory import build
    m = build(OWNED_GDI, game_id=GAME["game_id"], title=GAME["title"], hash_tracks=False, deep=False)
    assert m["game_id"] == GAME["game_id"] and m["title"] == GAME["title"]
    assert m["build_matches"] is True
    assert m["ip"]["product"] == "T3601N" and m["ip"]["version"] == "V1.100"
    assert m["executable"]["sha256"] == US_FIRST_READ_SHA256
    fam = {r["key"] for r in m["characters"] if r["costumes"]}
    assert fam == {"KAS", "AYA", "LEI", "TIN", "BAS", "JAN", "GEN", "BAY", "RYU", "ZAC",
                   "HIK", "TNG", "KTE", "LOR", "MAM", "WBA", "YTI"}
    assert "SAM" not in fam and "PDG" not in fam                  # LE-only families absent here
