"""Focused tests for the THPS3 (GameCube) owned-build inventory reader.

These read the owned GameCube source read-only; they never write to it.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import thps3

SOURCE = thps3.SOURCE_PATH

requires_source = pytest.mark.skipif(
    not os.path.exists(SOURCE), reason="owned THPS3 GCZ source is not mounted")


@requires_source
def test_source_identity_is_streamed_hash():
    h = thps3.source_sha256()
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


@requires_source
def test_manifest_is_authoritative_and_in_range():
    m = thps3.manifest(with_hash=False)
    assert m["file_count"] >= 4000
    assert len(m["game_code"]) == 6
    assert m["extensions"][".skn"] == 323
    assert m["extensions"][".tex"] == 361
    assert m["extensions"][".ska"] == 281
    for f in m["files"]:
        assert f["size"] >= 0
        assert f["offset"] + f["size"] <= m["disc"]["data_size"]


@requires_source
def test_character_census_counts_from_fst():
    m = thps3.manifest(with_hash=False)
    parts = thps3.character_parts(m)
    assert len(parts["models/skater_m"]) == 170
    assert len(parts["models/skater_f"]) == 43
    assert "skater_m" in parts["models/skater_m"]
    assert "Head_Koston" in parts["models/skater_m"]


@requires_source
def test_skn_header_probe_on_base_mesh():
    m = thps3.manifest(with_hash=False)
    blob = thps3.read_member(SOURCE, thps3.PRIMARY_SLOT, m)
    h = thps3.skn_header(blob)
    assert h["version"] == 2
    assert h["chunk_magic"] == "NBCG"
    assert h["count"] > 0
    assert h["matrix"][5] == 1.0
    assert h["matrix"][11] == -1.0
    assert h["chunk_offset"] < h["size"]


@requires_source
def test_ska_and_tex_probes():
    m = thps3.manifest(with_hash=False)
    skn = thps3.read_member(SOURCE, thps3.NAMED_SLOT, m)
    tex = thps3.read_member(SOURCE, "models/skater_m/head_koston.tex", m)
    ska_paths = [f["path"] for f in m["files"] if f["path"].endswith(".ska")]
    assert ska_paths
    ska = thps3.read_member(SOURCE, ska_paths[0], m)
    assert thps3.ska_header(ska)["magic"] == "NACG"
    t = thps3.tex_header(tex)
    assert t["gctx_offset"] == 32
    assert t["name"].endswith(".png")
    assert thps3.skn_header(skn)["chunk_magic"] == "NBCG"


@requires_source
def test_native_target_slot_has_identity():
    m = thps3.manifest(with_hash=False)
    t = thps3.native_target(m, SOURCE)
    assert "primary" in t["slots"] and "named" in t["slots"]
    p = t["slots"]["primary"]
    assert p["size"] == 183152
    assert len(p["sha256"]) == 64
    n = t["slots"]["named"]
    assert n["size"] == 27876
    assert n["texture"].endswith(".tex")
    assert len(n["texture_sha256"]) == 64
