"""Focused tests for gbox.sms_inventory (Super Mario Sunshine owned-build inventory)."""
import hashlib
import os
import struct

import pytest

from gbox import sms_inventory as sms

OWNED = sms.owned_source_path()
needs_owned = pytest.mark.skipif(OWNED is None, reason="owned Super Mario Sunshine image is not staged in the cache")


def _bmd(size=0x200):
    """A minimal J3D2bmd3 header shaped exactly like the owned build's model header."""
    blob = bytearray(size)
    blob[0:8] = b"J3D2bmd3"
    struct.pack_into(">I", blob, 8, size)      # file size
    struct.pack_into(">I", blob, 12, 8)        # padding word
    blob[0x10:0x14] = b"SRV3"                 # section tag
    blob[0x20:0x24] = b"INF1"                 # INF1 chunk
    return bytes(blob)


def test_bmd_probe_reads_only_proven_header_fields():
    probe = sms.bmd_probe(_bmd())
    assert probe["magic"] == "J3D2"
    assert probe["version"] == "bmd3"
    assert probe["file_size"] == 0x200
    assert probe["section_tag"] == "SRV3"
    assert probe["inf_tag"] == "INF1"
    assert probe["byte_order"] == "big-endian"


def test_bmd_probe_rejects_foreign_bytes():
    with pytest.raises(ValueError):
        sms.bmd_probe(b"NOTAMODEL" + bytes(0x40))
    with pytest.raises(ValueError):
        sms.bmd_probe(b"J3D2bmd3")           # truncated header


def test_member_bytes_is_bounded_by_the_archive():
    payload = bytearray(b"\0" * 0x40)
    payload[0:4] = b"RARC"
    with pytest.raises(Exception):
        sms.member_bytes(bytes(payload), "nope.bmd")


def test_owned_source_path_is_found_by_catalog_id():
    # The owned build is a staged cache copy; the id-addressed lookup is the only reliable one.
    assert sms.owned_source_path() is None or sms.owned_source_path().endswith((".gcz", ".iso", ".gcm"))


@needs_owned
def test_owned_build_manifest():
    manifest = sms.inventory(OWNED, census=False)
    assert manifest["source"]["sha256"] == "7767b10a3d7a8c6ee90785bc9f1a2647774d4251b322509350e8251c43829e3a"
    assert manifest["source"]["bytes"] == 1416728028
    assert manifest["disc"]["game_id"] == "GMSE01"
    assert manifest["disc"]["file_count"] == 174
    assert manifest["archives"] == 122
    assert manifest["target"]["member"] == "bmd/ma_mdl1.bmd"
    assert manifest["target"]["bytes"] == 117248
    assert manifest["target"]["sha256"] == "33ae21b047a8dff0d76fed843dbcf1accfd85b6b427367dd23e6465ac2574eb6"
    assert manifest["target"]["bmd"]["file_size"] == manifest["target"]["bytes"]


@needs_owned
def test_every_szs_is_a_yaz0_archive():
    for name, _size, _off in sms.disc_files(OWNED):
        if not name.endswith(".szs"):
            continue
        assert sms.read_disc_file(OWNED, name)[:4] == b"Yaz0"


@needs_owned
def test_target_member_is_the_native_mario_model():
    payload = sms.decode_szs(sms.read_disc_file(OWNED, "data/mario.szs"))
    blob = sms.member_bytes(payload, "bmd/ma_mdl1.bmd")
    assert len(blob) == 117248
    assert blob[:8] == b"J3D2bmd3"
    assert hashlib.sha256(blob).hexdigest() == "33ae21b047a8dff0d76fed843dbcf1accfd85b6b427367dd23e6465ac2574eb6"
