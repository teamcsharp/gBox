"""Request #2062: Bloody Roar (USA) unlock-on-load probe harness tests.

Fixtures are independent synthetic bytes (explicit expected values), not parser output.
"""
import hashlib
import json

import pytest

from gbox import bloody_roar_unlock as br


def test_census_finds_gate_strings_with_independent_offsets():
    payload = bytearray(b"\x00" * 1000)
    for off, text in ((16, b"Hidden StAgE"), (500, b"CONCEPT ART"), (900, b"nothing special")):
        # NUL-delimit each string so the greedy [\x20-\x7e]{4,64} run stops at it.
        payload[off:off + len(text)] = text
    out = br.census_bytes(bytes(payload))
    hits = {h["text"]: h["offset"] for h in out["candidate_strings"]}
    assert hits["Hidden StAgE"] == 16
    assert hits["CONCEPT ART"] == 500
    assert "nothing special" not in hits


def test_census_is_bounded():
    payload = b"UNLOCK " * 5000
    out = br.census_bytes(payload)
    assert len(out["candidate_strings"]) <= 256


def test_sha256_stream_matches_hashlib(tmp_path):
    data = bytes(range(256)) * (br.BLOCK // 256 + 3)
    p = tmp_path / "img.bin"
    p.write_bytes(data)
    assert br.sha256_stream(p) == hashlib.sha256(data).hexdigest()


def test_find_owned_image_missing_records_next_step(tmp_path):
    rec = br.find_owned_image(tmp_path)
    assert rec["found"] is False
    assert "provision" in rec["next_step"]


def test_find_owned_image_finds_cache_hit(tmp_path):
    d = tmp_path / br.GAME_ID
    d.mkdir()
    img = d / "SLUS_007.02.bin"
    img.write_bytes(b"MComprHD" + b"\x00" * 100)
    rec = br.find_owned_image(tmp_path)
    assert rec["found"] and rec["path"] == str(img)
    assert rec["sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()


def test_save_manifest_roundtrip(tmp_path):
    manifest = {"game_id": br.GAME_ID, "verified": False}
    p = br.save_manifest(manifest, tmp_path / "out")
    assert json.loads(p.read_text()) == manifest
    assert p.name == f"{br.GAME_ID}-inventory.json"


def test_no_runtime_write_surface():
    # The harness must stay offline: no live session memory writes.
    src = (br.__file__ and open(br.__file__, encoding="utf-8").read())
    for forbidden in ("write_memory(", "freeze_memory(", "SESSIONS["):
        assert forbidden not in src
