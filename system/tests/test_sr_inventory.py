"""Focused tests for :mod:`gbox.sr_inventory` (Sonic Riders USA GameCube inventory)."""
import json
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gbox.sr_inventory import (  # noqa: E402
    CHARACTER_SLOT_RE,
    OWNED_SOURCE,
    OWNED_SOURCE_SHA256,
    OWNED_SOURCE_SIZE,
    build_manifest,
    character_slots,
    gcax_sections,
    parse_gcax_header,
    sha256_file,
    verify_fingerprint,
)

LIVE = pytest.mark.skipif(not os.path.exists(OWNED_SOURCE),
                          reason="owned Sonic Riders disc is not mounted")


def _fake_char_dat(size=0x2000):
    """Synthesise the gcax/DTPK layout observed in 10SONIC.DAT."""
    buf = bytearray(size)
    buf[0:4] = b"gcax"
    buf[4:8] = b"DTPK"
    struct.pack_into(">I", buf, 0x0C, size)
    buf[0x60:0x64] = b"gcax"
    buf[0x64:0x68] = b"TBLD"
    buf[0x800:0x804] = b"gcax"
    buf[0x804:0x808] = b"PCMD"
    return bytes(buf)


def test_parse_gcax_header_reads_big_endian_size():
    head = parse_gcax_header(_fake_char_dat(0x2000), 0)
    assert head["arch"] == "DTPK"
    assert head["declared_size"] == 0x2000
    assert head["offset"] == 0


def test_parse_gcax_header_rejects_foreign_magic():
    with pytest.raises(ValueError):
        parse_gcax_header(b"NOPE" + b"\x00" * 0x40, 0)


def test_gcax_sections_lists_dtpk_tbld_pcmd():
    secs = gcax_sections(_fake_char_dat(0x2000))
    assert [(s["offset"], s["arch"]) for s in secs] == [
        (0x000, "DTPK"), (0x060, "TBLD"), (0x800, "PCMD")]


def test_character_slot_regex_selects_only_10_dat():
    paths = ["10SONIC.DAT", "10AMY.DAT", "10ER1.DAT", "11SONIC.DAT",
             "10SONIC.BIN", "SONIC.DAT", "0501.DAT"]
    assert character_slots(paths) == ["10AMY.DAT", "10ER1.DAT", "10SONIC.DAT"]
    assert CHARACTER_SLOT_RE.match("10SONIC.DAT")


def test_sha256_file_streams_bytes(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"gbox" * 1000)
    digest, size = sha256_file(str(p))
    import hashlib
    assert digest == hashlib.sha256(b"gbox" * 1000).hexdigest()
    assert size == 4000


@LIVE
def test_manifest_maps_owned_build():
    m = build_manifest(OWNED_SOURCE, source_sha256=OWNED_SOURCE_SHA256,
                       source_size=OWNED_SOURCE_SIZE)
    assert m["disc"]["file_count"] == 1669
    assert m["disc"]["fst_offset"] == 0x144000
    assert m["disc"]["fst_size"] == 0x72B1
    assert sorted(m["cri_afs"]) == ["VOICE_E.AFS", "V_CHAO_E.AFS"]
    assert m["character_slot_count"] == 16
    assert m["target_slot"] == "10SONIC.DAT"
    sonic = [s for s in m["character_slots"] if s["name"] == "10SONIC.DAT"][0]
    assert sonic["size"] == 0x22000
    assert sonic["declared_size_matches_file"] is True
    assert [(s["offset"], s["arch"]) for s in sonic["sections"]] == [
        (0x000, "DTPK"), (0x060, "TBLD"), (0x800, "PCMD")]
    assert len(m["files"]) == 1669


@LIVE
def test_fingerprint_claims_are_checked_against_owned_files():
    m = build_manifest(OWNED_SOURCE, source_sha256=OWNED_SOURCE_SHA256,
                       source_size=OWNED_SOURCE_SIZE)
    checks = {c["claim"]: c for c in verify_fingerprint(m)}
    assert checks["CRI AFS archive x1"]["verdict"] == "mismatch"
    assert checks["CRI AFS archive x1"]["observed"] == 2
    assert checks["engine CRI Middleware (ADX present)"]["observed"] == 62
    assert checks["character assets are containers (not AFS)"]["observed"] == 16


@LIVE
def test_owned_source_sha256_matches_streamed_digest():
    digest, size = sha256_file(OWNED_SOURCE)
    assert digest == OWNED_SOURCE_SHA256
    assert size == OWNED_SOURCE_SIZE
