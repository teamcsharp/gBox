"""Focused tests for the GTA Chinatown Wars owned-build inventory helpers.

The owned source is located from, in order:
  1. $GBX_CTW_ROM                       - explicit path to the owned .nds
  2. the extracted ROM in the run scratch directory
  3. the owned 7z on the hyperspin share, extracted into a temp directory

The tests assert container/bounds facts that are read back from the owned
bytes; no expected digest is copied from a reference build.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)

from gbox.formats import ctw_nds  # noqa: E402

SCRATCH = "/home/ehm_eckx/.hermes/cache/scratch/ctw"
SHARE_7Z = ("/mnt/gbox/hyperspin/Arcade/collections/Nintendo DS/roms/"
            "Grand Theft Auto - Chinatown Wars (USA).7z")


def _owned_rom():
    env = os.environ.get("GBX_CTW_ROM")
    if env and os.path.isfile(env):
        return env
    if os.path.isdir(SCRATCH):
        found = sorted(f for f in os.listdir(SCRATCH) if f.lower().endswith(".nds"))
        if found:
            return os.path.join(SCRATCH, found[0])
    if os.path.isfile(SHARE_7Z) and shutil.which("7z"):
        tmp = tempfile.mkdtemp(prefix="ctw-test-")
        subprocess.run(["7z", "x", "-y", "-o" + tmp, SHARE_7Z], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        found = [f for f in os.listdir(tmp) if f.lower().endswith(".nds")]
        if found:
            return os.path.join(tmp, found[0])
    return None


ROM = _owned_rom()


def _manifest():
    assert ROM is not None, "owned Chinatown Wars ROM not available"
    return ctw_nds.manifest(ROM)


def test_rom_header_identity():
    """Header fields come from the owned bytes: title 'GTA CTW', code YGXE."""
    manifest = _manifest()
    assert manifest["rom_title"] == "GTA CTW"
    assert manifest["rom_gamecode"] == "YGXE"
    assert manifest["arm9"]["size"] > 0
    assert manifest["arm9"]["offset"] >= ctw_nds.ROM_HEADER_SIZE


def test_container_members_are_named_and_in_range():
    """The four Rockstar members exist and their FAT ranges are inside the ROM."""
    manifest = _manifest()
    names = [m["name"] for m in manifest["members"]]
    assert names == ["ROM.TOC", "ROM.WAD", "game.pak", "dwc/utility.bin"]
    for member in manifest["members"]:
        assert member["size"] > 0
        assert 0 <= member["start"] < member["end"] <= manifest["source_size"]


def test_container_members_do_not_overlap():
    """The named Rockstar members occupy disjoint byte ranges."""
    manifest = _manifest()
    assert manifest["member_overlaps"] == []


def test_fat_table_is_in_bounds():
    """Every payload range of the owned build lies inside the file."""
    manifest = _manifest()
    assert manifest["out_of_bounds_fat_entries"] == []
    assert manifest["nitrofs"]["fat_entries"] == len(manifest["fat_manifest"])
    assert len(manifest["fat_manifest"]) > 100


def test_fat_overlap_detection_matches_brute_force():
    """The module's overlap finder agrees with an independent all-pairs scan."""
    manifest = _manifest()
    entries = manifest["fat_manifest"]
    brute = []
    for index, first in enumerate(entries):
        for second in entries[index + 1:]:
            if first["start"] < second["end"] and second["start"] < first["end"]:
                brute.append([first["file_id"], second["file_id"]])
    assert manifest["fat_overlaps"] == brute


def test_streamed_hash_matches_bytes():
    """sha256 is taken by streaming the owned file, and matches the raw bytes."""
    manifest = _manifest()
    with open(ROM, "rb") as handle:
        raw = hashlib.sha256(handle.read()).hexdigest()
    assert manifest["source_sha256"] == raw
    assert len(manifest["source_sha256"]) == 64
    assert ctw_nds.sha256_stream(ROM) == raw


def test_fat_manifest_digest_is_stable():
    """The manifest digest is a deterministic function of the FAT table."""
    manifest = _manifest()
    canonical = json.dumps(manifest["fat_manifest"], sort_keys=True,
                           separators=(",", ":"))
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert manifest["fat_manifest_sha256"] == expected


if __name__ == "__main__":
    failures = 0
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("FAIL", name, type(exc).__name__, exc)
    print("ROM:", ROM)
    sys.exit(1 if failures else 0)
