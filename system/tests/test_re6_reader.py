"""Focused tests for gbox.re6_reader (synthetic arc extraction; owned-ISO GLB export when present)."""

import os
import struct
import tempfile
from pathlib import Path

import pytest

from gbox.re6_models import CHARACTERS
from gbox.re6_reader import extract_character_arcs, reader_probe

ISO = Path(os.environ.get("RE6_ISO", "/mnt/gbox/hyperspin/Arcade/collections/Microsoft XBOX 360/roms/Resident Evil 6.iso"))


def test_character_roster():
    """The 7 playable heroes are registered with their arc stems."""
    assert set(CHARACTERS) == {"leon", "helena", "chris", "piers", "jake", "sherry", "ada"}
    leon = CHARACTERS["leon"]
    assert leon["pl"] == "pl0000"
    assert leon["arc"].format(part="", costume="Usa") == "uPl00LeonUsa"
    assert leon["arc"].format(part="Head", costume="Usa") == "uPl00HeadLeonUsa"
    assert "Usa" in leon["costumes"]


def test_roster_and_collection_routing():
    """The reader is wired into the normal collection path: roster + characters.DEDICATED + char_coverage."""
    from gbox import char_coverage
    from gbox.characters import DEDICATED
    from gbox.re6_reader import roster

    entries = roster()
    assert {e["key"] for e in entries} == set(CHARACTERS)
    assert all(e["slug"].startswith("re6_") and e["kind"] == "character" for e in entries)

    hit = [d for d in DEDICATED if d[1]("resident evil 6", "xbox360")]
    assert len(hit) == 1 and hit[0][0] == "re6"
    assert [e["name"] for e in hit[0][2]()][:1] == ["Leon S. Kennedy"]
    # char_coverage reports the extractor for the favorite's catalog game
    ex, ros = char_coverage.extractor_for({"title": "Resident Evil 6", "platform": "xbox360"})
    assert ex == "re6" and len(ros) == 7


@pytest.mark.skipif(not ISO.exists(), reason="owned RE6 ISO not mounted")
def test_leon_usa_glb_export():
    """Export Leon Usa (body+head+hands, LOD0) to GLB from the owned ISO."""
    r = reader_probe(str(ISO), "leon", "Usa")
    assert r["character"] == "leon" and r["costume"] == "Usa"
    # at least the body arc was extracted
    stems = [e["stem"] for e in r["extracted_arcs"]]
    assert "uPl00LeonUsa" in stems
    # GLB was produced and is non-trivial
    glb = r["glb"]
    assert glb["bytes"] > 100000, f"GLB too small: {glb['bytes']}"
    assert glb["sha256"] and len(glb["sha256"]) == 64
    # stats: body+head+hands exported, triangles counted
    assert r["stats"]["triangles"] > 10000
    assert len(r["stats"]["parts"]) >= 1
