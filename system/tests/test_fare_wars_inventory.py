"""gbox.fare_wars_inventory: owned-build inventory for Crazy Taxi: Fare Wars (PSP) (request #2453).

The owned-build tests read the operator's own CSO image and are skipped when it is not
mounted; the parsing tests use synthetic bytes and always run.
"""
import os
import struct
from pathlib import Path

import pytest

from gbox import fare_wars_inventory as inv

CSO = os.environ.get("GBOX_FAREWARS_CSO", "/mnt/gbox/hyperspin/Arcade/collections/"
                     "Sony PlayStation Portable/roms/Crazy Taxi - Fare Wars (USA).cso")


def _synthetic_sfo():
    """Minimal PARAM.SFO in the layout verified against the owned file (index at 0x14)."""
    keys = b"DISC_ID\x00TITLE\x00"
    key_start = 20 + 2 * 16
    data_start = key_start + len(keys)
    disc, title = b"ULUS10273\x00\x00\x00", b"Crazy Taxi: Fare Wars\x00"
    header = struct.pack("<IIIII", 0x46535000, 0x101, key_start, data_start, 2)
    idx = struct.pack("<HHIII", 0, 0x0204, 10, 16, 0)
    idx += struct.pack("<HHIII", 8, 0x0204, len(title), 32, 16)
    return header + idx + keys + disc.ljust(16, b"\0") + title.ljust(32, b"\0")


def test_sfo_entries_reads_verified_layout():
    entries = inv.sfo_entries(_synthetic_sfo())
    assert entries["TITLE"] == "Crazy Taxi: Fare Wars"
    assert entries["DISC_ID"] == "ULUS10273"
    assert entries["_header"]["index_count"] == 2


def test_sfo_entries_rejects_truncated_header():
    with pytest.raises(ValueError):
        inv.sfo_header(b"\x00" * 8)


def test_container_probe_reports_bytes_without_guessing_layout():
    probe = inv.container_probe(b"AFS\x00" + b"\x11" * 28)
    assert probe["size"] == 32
    assert probe["magic_ascii"].startswith("AFS")
    assert "head_hex" in probe


def test_stream_sha256_matches_hashlib():
    import hashlib
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False) as fh:
        fh.write(b"crazy taxi" * 1000)
        path = fh.name
    try:
        assert inv.stream_sha256(path) == hashlib.sha256(b"crazy taxi" * 1000).hexdigest()
    finally:
        os.unlink(path)


@pytest.mark.skipif(not os.path.exists(CSO), reason="owned PSP CSO image is not mounted here")
def test_owned_build_manifest():
    data = inv.inventory(CSO)
    assert data["source_sha256"] == inv.OWNED_CSO_SHA256
    assert data["source_size"] == inv.OWNED_CSO_SIZE
    assert data["iso_member_count"] == inv.ISO_MEMBER_COUNT
    assert data["required_members_missing"] == []
    assert data["revision"].get("TITLE", "").startswith("Crazy Taxi")
    assert data["revision"]["DISC_ID"] == "ULUS10273"
    assert data["revision"]["TITLE"] == "Crazy Taxi: Fare Wars"
    assert data["revision"]["DISC_VERSION"] == "1.01"
    # every member is inside the uncompressed image and has a 64-hex digest
    for m in data["members"]:
        assert m["offset"] >= 0 and m["size"] >= 0
        assert len(m["sha256"]) == 64 and all(c in "0123456789abcdef" for c in m["sha256"])
    # the identified native target asset
    t = data["target_asset"]
    assert t["member"] == inv.PRIMARY_TARGET
    assert t["size"] > 0 and len(t["sha256"]) == 64
