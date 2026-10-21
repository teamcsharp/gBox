import json
from pathlib import Path

import pytest

from gbox import doa_saturn_unlock as D

SCRATCH = Path("/home/ehm_eckx/.hermes/cache/scratch/doa_saturn")
EXE = SCRATCH / "00DOA.BIN"
MANIFEST = SCRATCH / "iso_manifest.json"

needs_artifacts = pytest.mark.skipif(
    not (EXE.exists() and MANIFEST.exists()),
    reason="offline fingerprinted artifacts not present on this node")


@needs_artifacts
def test_executable_hash_pinned_to_owned_build():
    assert D.sha256_file(str(EXE)) == D.EXE_SHA256


@needs_artifacts
def test_load_table_parses_all_112_gfs_entries():
    table = D.parse_file_table(EXE.read_bytes())
    assert len(table) == 112
    names = {e["name"] for e in table}
    assert all(";" not in n for n in names)  # ';1' ISO suffix stripped
    assert any(n.endswith("_MDL.BIN") for n in names)
    assert any(n.endswith("_TEX.BIN") for n in names)


@needs_artifacts
def test_load_table_names_all_exist_in_iso_manifest():
    manifest = json.loads(MANIFEST.read_text())
    inv = D.character_inventory(EXE.read_bytes(), manifest)
    assert inv["load_table_entries"] == 112
    assert inv["load_table_names_in_manifest"] == "112/112"


@needs_artifacts
def test_roster_and_costume_variant_inventory():
    manifest = json.loads(MANIFEST.read_text())
    inv = D.character_inventory(EXE.read_bytes(), manifest)
    assert sorted(D.CHARACTER_PREFIXES) == inv["roster_prefixes"]
    assert inv["suspected_extra_prefixes"] == ["TR"]
    variants = inv["costume_variants"]
    # verified from the 354-file ISO manifest: FA has 5 MDL/TEX + 3 LAD + 5 TNK
    assert len(variants["FA"]) >= 3
    assert "MDL" in variants["FA"]["1"] and "TEX" in variants["FA"]["1"]
    # LU ships 5 numbered model/texture variants (costumes)
    assert len(variants["LU"]) >= 4
    # every roster family ships TNK voice data
    for prefix in D.CHARACTER_PREFIXES:
        assert any("TNK" in s for s in sum(variants[prefix].values(), [])), prefix


def test_unlock_profile_refuses_to_claim_verified_unlock():
    game = {"game_id": D.GAME_ID, "platform": "saturn"}
    profile = D.unlock_profile(game)
    assert profile["verified"] is False
    assert profile["status"] == "research_pending"
    assert profile["requires_runtime_verification"] is True
    assert profile["scope"] == []
    # wrong platform/id stays unsupported
    assert D.unlock_profile({"game_id": D.GAME_ID, "platform": "dreamcast"})["status"] == "unsupported"
    assert D.unlock_profile({"game_id": "0" * 16, "platform": "saturn"})["status"] == "unsupported"


def test_module_performs_no_writes(monkeypatch):
    # pure-parse operations must never open the owned ROM path
    calls = []
    real_open = open
    def guard(path, *a, **k):
        if str(path).startswith("/mnt/gbox"):
            calls.append(str(path))
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", guard)
    D.unlock_profile({"game_id": D.GAME_ID, "platform": "saturn"})
    assert calls == []
