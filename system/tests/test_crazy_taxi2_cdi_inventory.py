"""Focused tests for gbox.crazy_taxi2_cdi_inventory (request #2454, owned-build manifest)."""
import hashlib
import json

from gbox import crazy_taxi2 as c2
from gbox import crazy_taxi2_cdi_inventory as inv


class FakeDisc:
    """Minimal stand-in for gbox.gdrom.CDIRom: a member table plus byte payloads."""

    def __init__(self, members):
        self._m = dict(members)
        self.files = sorted(self._m)

    def read(self, name):
        return self._m[name]


def test_file_sha256_streams_real_bytes(tmp_path):
    data = b"crazy taxi 2" * 5000
    p = tmp_path / "blob.bin"
    p.write_bytes(data)
    assert inv.file_sha256(p) == hashlib.sha256(data).hexdigest()


def test_member_hash_matches_the_bytes_read_back():
    d = FakeDisc({"1ST_READ.BIN": b"abc"})
    assert inv.sha256_bytes(d.read("1ST_READ.BIN")) == hashlib.sha256(b"abc").hexdigest()


def test_build_maps_high_banks_onto_driver_slots():
    d = FakeDisc({"POLPP1AH.BIN": b"x" * 64, "TEXPP1AH.BIN": b"y" * 32, "1ST_READ.BIN": b"z" * 16})
    man = inv.build(d)
    row = man["banks"]["PP1A"]
    assert row["high_model"] == "POLPP1AH.BIN"
    assert row["high_texture"] == "TEXPP1AH.BIN"
    assert row["slot"] == "driver:axel"
    assert row["high_model_sha256"] == hashlib.sha256(b"x" * 64).hexdigest()
    assert man["members"] == 3


def test_build_separates_different_and_missing_pinned_files():
    d = FakeDisc({"1ST_READ.BIN": b"not the real 1ST_READ", "POLPP1A.BIN": b"nope"})
    man = inv.build(d)
    pc = man["pinned_comparison"]
    assert pc["same_build"] is False
    assert "1ST_READ.BIN" in pc["different"]
    assert "POLPP1A.BIN" in pc["different"]
    assert pc["missing"], "pinned files absent from the image must be reported as missing"
    assert pc["pinned_count"] == len(c2.FILES_SHA256)


def test_walk_section_covers_every_pol_bank_only():
    d = FakeDisc({"POLPP1A.BIN": b"nope", "TEXPP1A.BIN": b"t"})
    man = inv.build(d)
    assert "POLPP1A.BIN" in man["walk"]
    assert "ok" in man["walk"]["POLPP1A.BIN"]
    assert "TEXPP1A.BIN" not in man["walk"]


def test_target_records_slot_banks_and_table_outcome():
    d = FakeDisc({"POLPP1AH.BIN": b"x" * 64, "TEXPP1AH.BIN": b"y" * 32, "1ST_READ.BIN": b"z" * 16})
    t = inv.build(d)["target"]
    assert t["key"] == "PP1A" and t["slot"] == "driver:axel" and t["driver"] == "Axel"
    assert t["model"] == "POLPP1AH.BIN" and t["texture"] == "TEXPP1AH.BIN"
    assert t["tables"] is not None or t["error"]


def test_manifest_is_json_serialisable():
    d = FakeDisc({"POLPP1AH.BIN": b"x" * 64, "1ST_READ.BIN": b"z" * 16})
    json.dumps(inv.build(d))


def test_target_key_is_a_known_driver_of_the_owned_build():
    assert inv.TARGET["key"] in c2.DRIVERS
    assert c2.SLUGS[inv.TARGET["key"]] == inv.TARGET["slot"].split(":", 1)[1]
