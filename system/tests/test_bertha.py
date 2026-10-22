"""Focused tests for the NFL Blitz 2003 container reader."""

from __future__ import annotations

import hashlib
import os
import struct
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox.formats import bertha  # noqa: E402

OWNED_ISO = os.environ.get(
    "BLITZ2003_ISO",
    "/mnt/gbox/quickswap2/Emulation/PS2/NFL Blitz 2003/NFL Blitz 2003.iso",
)
OWNED_ISO_SHA256 = "7927f812724eb7c30d672903c5c277b5358d25d20b61b1590d376a796270d513"


def _synthetic_zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("ac.rsc", b"RYWM" + b"\x00" * 60)
        zf.writestr("zombie.dff", b"\x89DFF" + b"\x01" * 100)
    return path


def test_zip_entries_reads_central_directory(tmp_path):
    zp = _synthetic_zip(tmp_path / "bertha.zip")
    size = os.path.getsize(zp)
    with open(zp, "rb") as fh:
        entries = bertha.zip_entries(fh, 0, size)
    names = [e.name for e in entries]
    assert names == ["ac.rsc", "zombie.dff"]
    assert all(e.method == 0 for e in entries)
    assert entries[1].size == 104


def test_zip_member_bytes_round_trip(tmp_path):
    zp = _synthetic_zip(tmp_path / "bertha.zip")
    size = os.path.getsize(zp)
    with open(zp, "rb") as fh:
        entries = bertha.zip_entries(fh, 0, size)
        member = bertha.IsoMember("DATA/BERTHA.ZIP", 0, size, 0)
        blob = bertha.zip_member_bytes(fh, member, entries[0])
    assert blob.startswith(b"RYWM")
    assert hashlib.sha256(blob).hexdigest() == hashlib.sha256(b"RYWM" + b"\x00" * 60).hexdigest()


def test_roster_names_reads_nul_separated_table():
    blob = b"\x00zombie.dff\x00xx_jumbo.rtd\x00wrihfnta.wip\x00\x00"
    assert bertha.roster_names(blob) == ["zombie.dff", "xx_jumbo.rtd", "wrihfnta.wip"]


def test_extension_histogram_counts_named_assets():
    hist = bertha.extension_histogram(["a.dff", "b.dff", "c.rtd"])
    assert hist == {"dff": 2, "rtd": 1}


@pytest.mark.skipif(not os.path.exists(OWNED_ISO), reason="owned PS2 ISO not mounted")
def test_manifest_against_owned_build():
    manifest = bertha.build_manifest(OWNED_ISO, OWNED_ISO_SHA256)
    names = [m["name"] for m in manifest["members"]]
    assert "SLUS_204.74" in names
    assert "DATA/BERTHA.ZIP" in names
    assert "DATA/BERTHA.ZIH" in names

    exe = next(m for m in manifest["members"] if m["name"] == "SLUS_204.74")
    assert exe["size"] == 2417112

    zih = manifest["bertha_zih"]
    assert zih["roster_count"] > 100
    assert zih["extensions"].get("dff", 0) > 0
    assert "zombie.dff" in zih["roster"]

    container = manifest["bertha_zip"]
    assert container["entry_count"] > 0
    assert all(e["method"] == 0 for e in container["entries"])

    target = manifest["target_asset"]
    assert target["size"] > 0
    assert len(target["sha256"]) == 64
