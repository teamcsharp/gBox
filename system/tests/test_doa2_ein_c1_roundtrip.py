"""Request #1138: DOA2 LE "character in the middle of the screen" = Ein C1 (KTE, costume 1).

Locks the validated native extraction into the collection: the owned disc's
KTE01 native asset set must decode byte-identically to the registered
collection entry `doa2_ein_c1` (preserved CHR/BIN/SUP/APV/ACS/KARATE hashes)
and produce the same model statistics. The pick that filed #1138 was
slot=player at x=0.5/y=0.55 in the same session whose #1139 pick-whip frame
(47%/57%, target "the game's player model") shows black-outfit Ein C1.

Source of truth for the preserved hashes: the registered collection entry
`gbox-cache/characters/doa2_ein_c1/meta.json` `native_source_hashes` plus the
files on disk next to it (APV, KARATE.BIN). The disc build is the owned
DOA2 Limited Edition (Japan) T3601M V1.002, 1ST_READ.BIN sha256
27a014ae…c97e1 (see the inventory manifest, #1326).
"""
import hashlib
import os
from pathlib import Path

import pytest

from gbox import characters, doa2_chars

GAME_ID = "1de2e7634f3161ff"
DISC_CANDIDATES = [
    Path(os.environ.get("GBOX_DOA2_LE_GDI", "") or "."),
    Path.home() / "gBox_alt/gbox-cache" / "dc" / GAME_ID / "disc.gdi",
]
# Preserved native source hashes of the registered entry doa2_ein_c1.
PRESERVED = {
    "KTE01.CHR": "e5242c1451fd752d6256293c482ceb012215ec8790ca74b29e97642253510c7a",
    "KTE01.BIN": "5a8aba1d30058c8833ca25cbe7ac509ed9fd7daec0587aecb98fc95e486687a7",
    "KTE01.SUP": "64c19d3bf107db0bc12fc4ef6a19910f048c83fe52189245d24af209ca3721dd",
    "KTE01.APV": "3d2b8c344ecaa24939ff8872bce7d9f7f6988de94257ad83ddb8a041e7cc27c3",
    "KTE_A01.ACS": "8ff363ece21e2346a169a45d28e96fd25cd49a8cfe243faa2450fe7a9bb821f5",
    "KARATE.BIN": "87da842f85eb17af006ef06e6cb92ac5d88ba40636d6310fb9ba79e272b8ca18",
}
TRIANGLES, VERTICES = 8269, 6141


def test_kte_roster_is_ein():
    roster = {r["key"]: r for r in doa2_chars.roster()}
    assert "KTE" in roster
    assert roster["KTE"]["name"] == "Ein"
    assert GAME_ID in doa2_chars.GAME_IDS


def test_doa2_dedicated_extractor_routed():
    names = [name for name, *_ in characters.DEDICATED]
    assert "doa2" in names


def _disc():
    for cand in DISC_CANDIDATES:
        if cand and cand.is_file():
            return cand
    return None


def test_ein_c1_native_roundtrip(tmp_path):
    disc = _disc()
    if disc is None:
        pytest.skip("DOA2 LE disc cache not available (set GBOX_DOA2_LE_GDI)")
    r = doa2_chars.export(str(disc), str(tmp_path), "KTE", "1")
    # doa2_chars.export reports file names relative to out_dir (characters
    # joins them onto the work dir the same way).
    files = {Path(f).name: tmp_path / Path(f).name for f in r["files"]}
    for name, want in PRESERVED.items():
        p = files.get(name)
        assert p is not None and p.is_file(), f"missing native file {name}"
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        assert got == want, f"{name}: {got} != {want}"
    rep = r.get("core_report") or {}
    assert rep.get("triangles") == TRIANGLES, rep.get("triangles")
    assert rep.get("vertices") == VERTICES, rep.get("vertices")
