"""Inventory-stage checks for the GameCube multi-title Zelda owned build.

The unit checks run on synthetic bytes; the integration check runs against the
owned .gcz when it is mounted and is skipped otherwise.
"""
import json
import os
import re
import struct
from pathlib import Path

import pytest

from gbox import zelda_gc_multipack_inventory as I

OWNED = Path(os.environ.get(
    "GBOX_ZELDA_GCZ",
    "/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/"
    "Legend of Zelda, The - Ocarina of Time - Master Quest (USA).gcz"))
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def manifest():
    if not OWNED.exists():
        pytest.skip("owned Zelda multi-pack source not mounted")
    m = I.inventory(OWNED)
    out = os.environ.get("GBOX_ZELDA_MANIFEST_OUT")
    if out:
        Path(out).write_text(json.dumps(m, indent=2, sort_keys=True))
    return m


def test_j3d_probe_sees_embedded_chunk_tags():
    raw = b"J3D " + b"\0" * 12 + b"MSH1" + struct.pack(">I", 16) + b"POS1" + b"\0" * 8
    probe = I.j3d_probe(raw, I.J3D_MODEL_TAGS)
    assert probe["magic"] == "J3D "
    assert probe["size"] == len(raw)
    assert {"MSH1", "POS1"} <= set(probe["j3d_tags"])
    assert probe["j3d_tags"]["MSH1"]["aligned_hits"] == 1


def test_j3d_probe_reports_empty_candidate():
    probe = I.j3d_probe(b"\0" * 32, I.J3D_MODEL_TAGS)
    assert probe["j3d_tag_count"] == 0


def test_sha256_file_streams_real_bytes(tmp_path):
    p = tmp_path / "blob"
    p.write_bytes(b"zelda" * 1000)
    import hashlib
    assert I.sha256_file(p) == hashlib.sha256(b"zelda" * 1000).hexdigest()


def test_owned_source_hash_is_pinned(manifest):
    assert manifest["source"]["sha256"] == I.EXPECTED_SOURCE_SHA256
    assert HEX64.match(manifest["source"]["sha256"])
    assert manifest["source"]["size"] == 1394879917


def test_owned_disc_header_and_file_table(manifest):
    disc = manifest["disc"]
    assert disc["game_id"] == I.EXPECTED_GAME_ID == "D43E01"
    assert disc["title"] == I.EXPECTED_TITLE
    assert disc["file_count"] == 28
    names = {f["name"] for f in disc["files"]}
    assert I.ARCHIVE_NAME in names
    assert "zlj_f.tgc" in names


def test_every_nested_sub_image_carries_gc_magic(manifest):
    subs = manifest["sub_images"]
    assert len(subs) == 8
    assert all(s["gc_magic_ok"] for s in subs)
    assert sum(1 for s in subs if s.get("fst_status") == "decoded") == 7


def test_retail_payload_file_table_is_not_decoded(manifest):
    retail = [s for s in manifest["sub_images"] if s["name"] == "zlj_f.tgc"][0]
    assert retail["inner_game_id"] == "D43J01"
    assert retail["size"] == 543975896
    assert retail["fst_status"] == "undecoded"
    assert manifest["unresolved"]


def test_retail_payload_resolves_to_two_n64_roms(manifest):
    retail = manifest["retail_roms"]
    assert set(retail) == {"zlj_f.tgc"}
    roms = retail["zlj_f.tgc"]
    assert len(roms) == 2
    by_crc = {r["crc_stored"].split("/")[0] for r in roms}
    assert by_crc == {"f034001a", "f3dd35ba"}  # Master Quest + original OoT v1.2
    for r in roms:
        assert HEX64.match(r["sha256"])
        assert r["size"] == 0x2000000
        assert r["title"] == "THE LEGEND OF ZELDA"
    # the Master Quest ROM is the named target of this build
    mq = [r for r in roms if r["crc_stored"].startswith("f034001a")][0]
    assert mq["sha256"] == "2a8d9dff460757a0f506a43db9b929510777ef690df620fb4364069a653372a8"


def test_character_archive_counts_and_native_target(manifest):
    zg = manifest["zelda_graph"]
    assert zg["member_count"] >= 200
    assert zg["asset_counts"]["bmd"] >= 2
    assert zg["asset_counts"]["bck"] >= 2
    model = zg["native_target"]["model"]
    anim = zg["native_target"]["animation"]
    assert model["path"] == I.NATIVE_TARGET_MODEL
    assert model["size"] == 1888
    assert HEX64.match(model["sha256"])
    assert anim["path"] == I.NATIVE_TARGET_ANIM
    assert anim["size"] == 736
    assert HEX64.match(zg["sha256"])


def test_outer_tpl_texture_archives_are_counted(manifest):
    tpl = [t for t in manifest["outer_tpl"] if "name" in t]
    assert len(tpl) == 9
    parsed = [t for t in tpl if t.get("image_count")]
    assert parsed
    assert all("error" in t or t.get("image_count", 0) >= 1 for t in tpl)
