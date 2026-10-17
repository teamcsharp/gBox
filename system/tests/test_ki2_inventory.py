"""Tests for gbox.ki2_inventory — run against synthetic fixtures, not owned files."""

from __future__ import annotations

import json
import zipfile

from gbox import ki2_inventory as ki2


def test_roster_and_platform():
    assert len(ki2.ROSTER) == 11
    assert "Fulgore" in ki2.ROSTER
    assert ki2.PLATFORM["cpu"].startswith("MIPS R4600")
    assert ki2.PLATFORM["year"] == 1996
    assert ki2.MAME_CHD_SHA1 == "e7c9291b4648eae0012ea0cc230731ed4987d1d5"


def test_audit_zip_flags_missing_and_unknown(tmp_path):
    z = tmp_path / "set.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ki2-l14.u98", b"fake")
        zf.writestr("readme.txt", b"x")
    a = ki2.audit_zip(z)
    assert a.sha256
    assert "readme.txt" in a.unknown
    assert "ki2-l10.u98" in a.missing
    assert a.wrong_sha1, "fake boot ROM payload must be flagged"
    assert not a.complete


def test_audit_zip_accepts_known_subset(tmp_path):
    # A real torrentzip subset with one correct file is not flagged as wrong.
    z = tmp_path / "set.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ki2-l14.u98", bytes([0] * 16))
    a = ki2.audit_zip(z)
    assert "ki2-l14.u98" in a.bios
    assert not a.unknown


def test_disk_regions_on_synthetic_image(tmp_path):
    raw = tmp_path / "disk.raw"
    sector = 512
    blob = b"\x01" * (sector * 3)
    with open(raw, "wb") as f:
        f.write(bytes(sector))              # sector 0: zero
        f.write(blob)                       # sectors 1-3: data
        f.write(bytes(sector * 2))          # sectors 4-5: zero
        f.write(blob)                       # sectors 6-8: data
    runs = ki2.disk_regions(raw, min_run=2)
    assert runs == [
        {"sectors": [1, 3], "bytes": [512, 4 * 512 - 1]},
        {"sectors": [6, 8], "bytes": [6 * 512, 9 * 512 - 1]},
    ]


def test_inventory_manifest_fields(tmp_path):
    # chd_identity is the only external dependency; stub it via monkeypatch.
    import gbox.ki2_inventory as mod

    raw = tmp_path / "disk.raw"
    with open(raw, "wb") as f:
        f.write(b"\x69" + bytes(511))
    with zipfile.ZipFile(tmp_path / "set.zip", "w") as zf:
        zf.writestr("ki2-l14.u98", bytes(16))
    info = {"sha1": "e7c9291b4648eae0012ea0cc230731ed4987d1d5", "logical_size": 512,
            "bps": 512, "cyls": 1, "heads": 1, "secs": 1}
    mod.chd_identity = lambda p: dict(info)
    m = mod.inventory(tmp_path / "set.zip", tmp_path / "x.chd", raw=raw)
    assert m["source"]["chd_matches_mame"] is True
    assert m["disk"]["sectors"] == 1
    assert m["disk"]["nonzero_runs"] == []
    assert m["launch"]["requires_chd"] is True
    assert m["source"]["raw"].endswith("disk.raw")


def test_manifest_roundtrip_json(tmp_path):
    import gbox.ki2_inventory as mod

    raw = tmp_path / "disk.raw"
    raw.write_bytes(b"\x01" * 1024)
    with zipfile.ZipFile(tmp_path / "set.zip", "w") as zf:
        zf.writestr("ki2-l14.u98", bytes(16))
    mod.chd_identity = lambda p: {"sha1": "x", "logical_size": 1024, "bps": 512}
    out = tmp_path / "m.json"
    mod.inventory(tmp_path / "set.zip", tmp_path / "x.chd", out=out, raw=raw)
    data = json.loads(out.read_text())
    assert data["roster"] == ki2.ROSTER
