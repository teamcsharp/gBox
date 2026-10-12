"""Exact-build inventory checks for Dead or Alive 2 (USA) Dreamcast (5f08ad9a86ebcc9a).

Needs the owned CHD unpacked to a .gdi; set GBOX_DOA2_USA_GDI to the disc.gdi path
(the cached copy at ~/gbox-cache/dc/5f08ad9a86ebcc9a/disc.gdi on the Spark).
Skipped when the disc is absent. Never modifies the disc or the CHD.
"""
from pathlib import Path

import pytest

from gbox.doa2usa_inventory import (FIRST_READ_SHA256, GAME_ID, build, families)

import os

GDI = os.environ.get("GBOX_DOA2_USA_GDI",
                     "/home/ehm_eckx/gbox-cache/dc/5f08ad9a86ebcc9a/disc.gdi")

pytestmark = pytest.mark.skipif(
    not Path(GDI).exists(),
    reason="DOA2 USA unpacked disc not present (GBOX_DOA2_USA_GDI)",
)

USA_FIGHTERS = {"KAS", "AYA", "LEI", "TIN", "BAS", "JAN", "GEN", "BAY", "RYU", "ZAC",
                "HIK", "TNG", "KTE"}
USA_VARIANTS = {"LOR", "MAM", "WBA", "YTI"}


@pytest.fixture(scope="module")
def manifest():
    return build(GDI, hash_tracks=False, deep=True)


def test_build_identity(manifest):
    assert manifest["build_matches"] is True
    assert manifest["ip"]["product"] == "T3601N"
    assert manifest["ip"]["version"] == "V1.100"
    assert manifest["ip"]["area"] == "U"
    assert manifest["executable"]["sha256"] == FIRST_READ_SHA256


def test_disc_families_match_usa_roster(manifest):
    from gbox.gdrom import GDRom
    fam = families(GDRom(GDI).files)
    fighters = {k for k in fam if k not in USA_VARIANTS and k not in ("STAGE",)}
    assert fighters == USA_FIGHTERS
    assert set(fam) & USA_VARIANTS == USA_VARIANTS
    # LE-only families must not appear
    assert "SAM" not in fam and "PDG" not in fam


def test_roster_on_disc_flags(manifest):
    by_key = {r["key"]: r for r in manifest["characters"]}
    assert all(by_key[k]["on_disc"] for k in USA_FIGHTERS | USA_VARIANTS)
    assert by_key["KTE"]["motion"] and "KARATE" in by_key["KTE"]["motion"][0]["file"]


def test_every_fighter_chr_decodes(manifest):
    bad = []
    for r in manifest["characters"]:
        for c in r["costumes"]:
            chr_ = c.get("chr") or {}
            if chr_.get("decoded") is not True:
                bad.append(f"{r['key']}{c['costume']}: {chr_.get('error')}")
    assert not bad, f"{len(bad)} undecoded fighter CHRs: {bad[:5]}"


def test_stage_and_layout_counts(manifest):
    assert len(manifest["stages"]) == 82  # 41x STAGE..CHR + 41x STAGE..BIN
    assert sum(1 for s in manifest["stages"] if s.endswith(".CHR")) == 41
    layout = manifest["layout"]
    assert layout["files"] >= 530
    ext = layout["by_extension"]
    assert ext["DOA2/*.CHR"]["files"] == 86
    assert ext["DOA2/*.SUP"]["files"] == 42
    assert ext["DOA2/*.MOT"]["files"] == 76


def test_kasumi_costume_counts(manifest):
    kas = next(r for r in manifest["characters"] if r["key"] == "KAS")
    assert [c["costume"] for c in kas["costumes"]] == ["00", "01", "02", "03", "04", "05"]
    # KAS04 carries the loose MDL duplicate
    k04 = {k: v for k, v in kas["costumes"][4].items() if v is not None}
    assert "mdl" in k04
