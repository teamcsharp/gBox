"""Owned-build inventory tests for Strike Force Bowling (GameCube, G5BE4Z)."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gbox.gcz import GCZ  # noqa: E402
from gbox.formats.gcfst import parse_fst  # noqa: E402
from gbox.sfb_inventory import (  # noqa: E402
    build_manifest, classify_member, find_owned_rom, read_disc_header,
)

ROM = find_owned_rom()
needs_rom = pytest.mark.skipif(
    ROM is None, reason="owned Strike Force Bowling ROM is not mounted")


def test_classify_member_uses_extension_and_directory_evidence():
    assert classify_member("GCNFUCs/BOB.FUC") == (".fuc", "fuc_container", "gcnfucs")
    assert classify_member("abanner.tpl") == (".tpl", "texture_container", "root")
    assert classify_member("GCNSND1/alley.spd") == (".spd", "audio_stream", "gcnsnd1")
    assert classify_member("GCNSND1/alley.spt") == (".spt", "audio_table", "gcnsnd1")
    assert classify_member("main.elf")[1] == "executable"


@needs_rom
def test_disc_header_matches_owned_build():
    gz = GCZ(ROM)
    try:
        disc = read_disc_header(gz)
    finally:
        gz.close()
    assert disc["game_code"] == "G5BE4Z"
    assert disc["title"] == "Strike Force Bowling"
    assert disc["endianness"] == "big"
    assert disc["fst_size"] > 0
    assert disc["main_dol_offset"] > 0


@pytest.fixture(scope="module")
def manifest():
    if ROM is None:
        pytest.skip("owned ROM not mounted")
    return build_manifest(ROM)


@needs_rom
def test_manifest_counts_match_owned_disc(manifest):
    m = manifest
    assert len(m["members"]) == 60
    assert m["counts"]["by_ext"] == {
        ".fuc": 30, ".spd": 12, ".spt": 12, ".tpl": 3, ".ddf": 1, ".elf": 1, ".bnr": 1}
    assert m["counts"]["by_kind"]["fuc_container"] == 30
    assert m["counts"]["by_kind"]["texture_container"] == 3
    assert m["counts"]["by_kind"]["audio_stream"] == 12


@needs_rom
def test_every_member_lies_inside_the_image(manifest):
    m = manifest
    limit = m["source"]["data_size"]
    for rec in m["members"]:
        assert rec["offset"] >= 0
        assert rec["size"] >= 0
        assert rec["offset"] + rec["size"] <= limit, rec["path"]


@needs_rom
def test_candidate_containers_are_grouped_and_unverified(manifest):
    m = manifest
    fucs = m["candidates"]["fuc_containers"]
    assert len(fucs) == 30
    for rec in fucs:
        assert rec["group"] == "gcnfucs"
        assert rec["role"] == "unverified"
        assert rec["size"] > 0
    assert any(r["path"].endswith("CHARSEL.FUC") for r in fucs)
    assert len(m["candidates"]["textures"]) == 3


@needs_rom
def test_member_hash_matches_direct_range_read():
    m = build_manifest(ROM, hash_paths=["AIA.tpl"])
    rec = [r for r in m["members"] if r["path"] == "AIA.tpl"][0]
    assert len(rec["sha256"]) == 64
    gz = GCZ(ROM)
    try:
        assert rec["sha256"] == gz.sha256_range(rec["offset"], rec["size"])
    finally:
        gz.close()


@needs_rom
def test_manifest_is_deterministic(manifest):
    """A second independent FST walk reproduces the same member table."""
    gz = GCZ(ROM)
    try:
        disc = read_disc_header(gz)
        fst = gz.read(disc["fst_offset"], disc["fst_size"])
        again = sorted((p, a, b) for p, a, b, _ in parse_fst(fst, disc["fst_offset"]))
    finally:
        gz.close()
    first = sorted((r["path"], r["offset"], r["size"]) for r in manifest["members"])
    assert first == again
    assert manifest["disc"]["fst_offset"] == disc["fst_offset"]
