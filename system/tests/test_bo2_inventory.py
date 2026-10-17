"""Tests for gbox.bo2_inventory.

Runs against the owned HyperSpin Dolphin GCZ "collections/Nintendo GameCube/roms/Legacy of Kain,
The - Blood Omen 2 (USA).gcz".  Verifies the module identifies the GO2E4F build, hashes the
executables, detects the Crystal Dynamics GOE engine, and parses the character roster.  The pure
unit tests (goefile_names / character_etypes) run without the disc.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gbox import bo2_inventory

GCZ = Path("/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/Legacy of Kain, The - Blood Omen 2 (USA).gcz")


def _skip_if_no_source():
    if not GCZ.is_file():
        pytest.skip(f"owned source not reachable: {GCZ}")


# --- pure unit tests (no disc needed) ---


def test_goefile_names_extracts_section_vocabulary():
    blob = (b"\xffgoefile\x00\xffsymlist\x00\xffdefault\x00\xff\x08\x01\x02\x03"
            b"\xffnative\x00\xffset\x00")
    names = bo2_inventory.goefile_names(blob)
    assert names == ["goefile", "symlist", "default", "native", "set"]


def test_goefile_magic_detection():
    assert (b"\xffgoefile\x00rest").startswith(bo2_inventory.GOEFILE_MAGIC)
    assert not b"\x00goefile\x00".startswith(bo2_inventory.GOEFILE_MAGIC)


def test_character_etypes_filters_wrappers_and_anims():
    txt = "\n".join([
        "d:/gogames/bo2/assets/etypes/characters/vm/voradvm/voradvm.etp",
        "d:/gogames/bo2/assets/etypes/characters/vm/voradvm/voradvmactor.etp",
        "d:/gogames/bo2/assets/etypes/characters/vm/+talk_anims.etp",
        "d:/gogames/bo2/assets/etypes/characters/sarafan_common.etp",
        "d:/gogames/bo2/assets/etypes/characters/cactor_proto.etp",
        "d:/gogames/bo2/assets/etypes/characters/dem/beast/beast.etp",
        "d:/gogames/bo2/assets/etypes/camera/camera.etp",  # not characters/
    ])
    roster = bo2_inventory.character_etypes(txt.encode())
    assert roster["actor_count"] == 2                       # voradvm, beast
    assert "voradvm" in roster["categories"]["vm"]
    assert "beast" in roster["categories"]["dem"]
    assert "sarafan_common" in roster["categories"]["root"]  # still listed, not counted


# --- disc-backed tests ---


@pytest.fixture(scope="module")
def disc():
    _skip_if_no_source()
    from gbox.gcdisc import GCDisc
    return GCDisc(GCZ)


def test_source_gcz_unchanged():
    _skip_if_no_source()
    assert GCZ.stat().st_size == 1_376_028_634


def test_disc_identity(disc):
    assert disc.game_id == "GO2E4F"
    assert disc.title == "Blood Omen 2"
    assert len(disc.files) == 213


def test_inventory_identifies_build_and_engine():
    _skip_if_no_source()
    m = bo2_inventory.inventory(GCZ, source_sha256=bo2_inventory.SOURCE_SHA256)
    assert m["disc_id"] == "GO2E4F"
    assert m["platform"] == "gamecube"
    assert m["region"] == "USA"
    assert m["source"]["sha256"] == bo2_inventory.SOURCE_SHA256
    assert m["engine"]["name"].startswith("Crystal Dynamics GOE")
    assert m["totals_by_kind"]["goefile"] == 179
    assert m["totals_by_kind"]["vault"] == 1


def test_executables_hashed():
    _skip_if_no_source()
    m = bo2_inventory.inventory(GCZ)
    by_name = {e["name"]: e for e in m["executables"]}
    assert by_name["main.dol (boot, not in FST)"]["sha256"] == \
        "f89ee2f72401916a8136a34e240dc7851e9ac48858db8eece1f8e40fde3163e9"
    assert by_name["main.dol (boot, not in FST)"]["entry"] == "0x80003140"
    assert by_name["gogames/bo2/code.bgg"]["sha256"] == \
        "d21e86d812ac0cd363a08fd89b8d9a15af8c6fb6666526d7248f413ea3c0481a"
    assert by_name["gogames/bo2/code.bgg"]["goefile"] is True


def test_kain_packs_are_goefile():
    _skip_if_no_source()
    m = bo2_inventory.inventory(GCZ)
    packs = m["characters"]["player"]["kain"]["packs"]
    assert [p["name"].rsplit("/", 1)[-1] for p in packs] == \
        ["kain.bgg", "kainc.bgg", "kaind.bgg", "kaine.bgg", "kainf.bgg"]
    assert all(p["goefile"] for p in packs)
    assert any("goefile" in p["sections"] for p in packs)


def test_manifest_roundtrip_json(tmp_path):
    _skip_if_no_source()
    out = tmp_path / "manifest.json"
    m = bo2_inventory.inventory(GCZ)
    out.write_text(json.dumps(m, indent=2))
    loaded = json.loads(out.read_text())
    assert loaded["game_id"] == "af354bb8263e7b32"
    assert loaded["disc_id"] == "GO2E4F"


def test_duplicate_actor_paths_are_counted_once():
    line = b"assets/etypes/characters/vm/voradvm.etp\n"
    assert bo2_inventory.character_etypes(line * 2)["actor_count"] == 1


def test_section_names_respect_byte_limit_and_ascii():
    assert bo2_inventory.goefile_names(b"\xffvalid\x00", limit=4) == []
    assert bo2_inventory.goefile_names(b"\xffa\x01bc\x00") == []
