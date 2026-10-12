"""Focused tests for the archived-GDI Dreamcast source path and the USA-build inventory.

The .7z branch of characters._dc_gdi extracts an owned archived GDI set once
(flattening tracks beside disc.gdi, the layout GDRom reads), so the DOA2 US
catalog entry (a .7z, game 3dd7e33362597f85) can be read by the shared doa2
pipeline instead of failing with "needs a GDI, or a CHD plus chdman".

The inventory smoke test is skipped unless the operator's extracted disc set
is present (never committed; the .7z itself is the owned source).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox import characters as C  # noqa: E402

GAME = {"game_id": "3dd7e33362597f85", "title": "Dead or Alive 2"}
US_FIRST_READ_SHA256 = "105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85"


class _Ctx:
    def __init__(self, cache: str):
        self.config = SimpleNamespace(cache=cache)

    def progress(self, p: int, m: str) -> None:  # noqa: ARG002
        pass


def _make_7z(tmp: Path) -> tuple[Path, Path]:
    """A synthetic archived GDI set: one .gdi descriptor inside a .7z."""
    raw = tmp / "raw"
    raw.mkdir()
    (raw / "Game (US)[!].gdi").write_text(
        "3\n1 0 4 2352 track01.bin 0\n2 45000 0 2352 track02.raw 0\n3 45001 4 2352 track03.bin 0\n")
    archive = tmp / "disc.7z"
    subprocess.run(["7z", "a", "-bd", str(archive), str(raw / "Game (US)[!].gdi")],
                   check=True, capture_output=True)
    return archive, raw / "Game (US)[!].gdi"


def test_dc_gdi_extracts_7z_archive_once(tmp_path: Path, monkeypatch) -> None:
    archive, _ = _make_7z(tmp_path)
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


@pytest.mark.skipif(not (Path("/home/ehm_eckx/gbox-hermes-tasks/d9f7808c88c94ef5-data/doa2_us/fresh-cache/dc/3dd7e33362597f85/disc.gdi").exists()
                         or Path("/home/ehm_eckx/gbox-hermes-tasks/d9f7808c88c94ef5-data/doa2_us/track03.bin").exists()),
                    reason="owned disc extraction not present on this node")
def test_doa2usa_inventory_build_identity() -> None:
    from gbox.doa2usa_inventory import build
    data = Path("/home/ehm_eckx/gbox-hermes-tasks/d9f7808c88c94ef5-data/doa2_us")
    fresh = data / "fresh-cache" / "dc" / GAME["game_id"] / "disc.gdi"
    gdi = fresh if fresh.exists() else next(data.glob("*.gdi"))
    m = build(gdi, game_id=GAME["game_id"], title=GAME["title"],
              hash_tracks=False, deep=False)
    assert m["build_matches"] is True
    assert m["ip"]["product"] == "T3601N" and m["ip"]["version"] == "V1.100"
    assert m["executable"]["sha256"] == US_FIRST_READ_SHA256
    fam = {r["key"] for r in m["characters"] if r["costumes"]}
    assert fam == {"KAS", "AYA", "LEI", "TIN", "BAS", "JAN", "GEN", "BAY", "RYU", "ZAC",
                   "HIK", "TNG", "KTE", "LOR", "MAM", "WBA", "YTI"}
    assert "SAM" not in fam and "PDG" not in fam                  # LE-only families absent here
