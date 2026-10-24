"""Metal Gear Solid (USA) disc 2 (PS1): owned-disc manifest and character-figure census.

Runs against the owned CHD.  Checks that need the full disc are opt-in (the disc is on a slow
network share): set ``GBOX_MGS_DISC2_FULL=1`` for the full source hash and the full member
re-hash, ``GBOX_MGS_DISC2_STAGE_DIR`` to point at an already extracted ``MGS/STAGE.DIR``.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from gbox import mgs_disc2_inventory as inv
from gbox import mgs_vr_swap as vr

CHD = Path(inv.CHD_PATH)
STAGE_CACHE = Path(os.environ.get(
    "GBOX_MGS_DISC2_STAGE_DIR", "/home/ehm_eckx/.hermes/cache/scratch/mgs_disc2/STAGE.DIR"))
FULL = os.environ.get("GBOX_MGS_DISC2_FULL") == "1"
MANIFEST_DOC = Path(__file__).resolve().parents[1] / "docs" / "mgs_disc2_manifest.json"


def _sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


@pytest.fixture(scope="module")
def stage():
    if STAGE_CACHE.is_file():
        return STAGE_CACHE.read_bytes()
    if not CHD.is_file():
        pytest.skip("owned MGS disc 2 CHD is not reachable")
    disc = inv.open_disc()
    try:
        return inv.stage_bytes(disc)
    finally:
        inv._close(disc)


# ------------------------------------------------------------------ source identity

def test_source_identity_constants():
    assert inv.SOURCE_BYTES == 474878219
    assert inv.SOURCE_SHA256 == "8837b20ddff61e5527fe95cbd186169e724f40409dd873cd549e489398b1d9ef"


def test_source_size_matches_owned_chd():
    if not CHD.is_file():
        pytest.skip("owned MGS disc 2 CHD is not reachable")
    assert CHD.stat().st_size == inv.SOURCE_BYTES


@pytest.mark.skipif(not FULL, reason="GBOX_MGS_DISC2_FULL not set (full 474 MB source hash)")
def test_source_sha256_streams_from_owned_chd():
    if not CHD.is_file():
        pytest.skip("owned MGS disc 2 CHD is not reachable")
    assert _sha256_file(CHD) == inv.SOURCE_SHA256


# ------------------------------------------------------------------ manifest

def test_manifest_document_is_complete():
    doc = json.loads(MANIFEST_DOC.read_text())
    assert doc["source_sha256"] == inv.SOURCE_SHA256
    assert doc["source_bytes"] == inv.SOURCE_BYTES
    assert doc["member_count"] == len(doc["members"]) == 11
    names = {m["path"] for m in doc["members"]}
    assert "MGS/STAGE.DIR" in names and "SYSTEM.CNF" in names and "DUMMY3M.DAT" in names
    for m in doc["members"]:
        assert m["size"] > 0 and m["lba"] >= 0
        assert len(m["sha256"]) == 64 and all(c in "0123456789abcdef" for c in m["sha256"])
    stage = next(m for m in doc["members"] if m["path"] == "MGS/STAGE.DIR")
    assert stage["size"] == inv.STAGE_BYTES


def test_small_members_rehash_to_manifest_values():
    if not CHD.is_file():
        pytest.skip("owned MGS disc 2 CHD is not reachable")
    doc = json.loads(MANIFEST_DOC.read_text())
    small = [m for m in doc["members"] if m["size"] <= 1 << 20]
    assert small, "expected at least one small member to re-hash"
    disc = inv.open_disc()
    try:
        for m in small:
            assert inv.member_manifest(disc, m["path"]) == m
    finally:
        inv._close(disc)


# ------------------------------------------------------------------ stage container

def test_stage_container_shape(stage):
    stages = vr.stage_dir(stage)
    assert len(stages) == inv.STAGE_COUNT == 96
    assert "init" in stages
    assert inv.kmd_sites(stage)


def test_census_finds_47_character_figures(stage):
    out = inv.figures(stage)
    assert out["kmd_sites"] == inv.KMD_SITES == 1876
    assert out["figure_count"] == inv.FIGURE_COUNT == 47
    for row in out["figures"].values():
        assert row["faces"] > 0 and row["verts"] > 0
        assert len(row["sha256"]) == 64


def test_player_model_is_the_identified_native_target(stage):
    row = inv.player_slot(stage)
    assert row is not None, "player model (member hash 39213) not found"
    assert row["hash"] == inv.PLAYER_MODEL_HASH
    assert row["bytes"] == 13608
    assert row["faces"] == 341 and row["verts"] == 369
    assert any(s["stage"] == "init" for s in row["sites"])
    assert any(s["offset"] == 5760508 for s in row["sites"])


def test_player_model_bytes_match_the_vr_missions_player_kmd(stage):
    """Disc 2's player KMD is byte-identical to the one gbox.mgs_vr_swap already targets."""
    row = inv.player_slot(stage)
    assert row is not None
    constants = {v for v in vars(vr).values()
                 if isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v)}
    assert row["sha256"] in constants, "player KMD is not the known VR Missions player model"
