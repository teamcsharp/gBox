"""Focused tests for the Splinter Cell Pandora Tomorrow (GC) inventory manifest."""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.spt_gc_inventory import (build_manifest, census, classify,  # noqa: E402
                                   disc_header, select_target, sha256_file)

LE = bytes.fromhex("c1832a9e")


class StubDisc:
    def __init__(self, files, blobs):
        self.files = files
        self._blobs = blobs

    def _r(self, off, n):
        return self._blobs.get(off, b"")[:n]


def test_classify_ue3_endianness():
    assert classify(LE + b"\x11\x22") == "unreal_package_le"
    assert classify(bytes.fromhex("9e2a83c1")) == "unreal_package_be"
    assert classify(b"") == "empty"
    assert classify(b"\x7fELF\x01") == "elf"
    assert classify(b"RIFFxxxx") == "riff"


def test_census_counts_and_bounds():
    files = {"/a.upk": (100, 8), "/b.bin": (200, 8), "/c.upk": (300, 8)}
    blobs = {100: LE + b"\x00" * 4, 200: b"otherdata", 300: LE + b"\x11" * 4}
    rows, stats = census(StubDisc(files, blobs))
    assert stats["total"] == 3 and stats["scanned"] == 3 and stats["truncated"] is False
    assert [r["label"] for r in rows] == ["unreal_package_le", "other", "unreal_package_le"]
    rows2, stats2 = census(StubDisc(files, blobs), limit=2)
    assert stats2["truncated"] is True and len(rows2) == 2


def test_select_target_prefers_character_named_package():
    files = {"/generic.upk": (100, 8), "/sam_fisher_char.upk": (200, 8)}
    blobs = {100: LE, 200: LE}
    rows, _ = census(StubDisc(files, blobs))
    assert select_target(rows)["path"] == "/sam_fisher_char.upk"
    assert select_target([{"path": "/x", "size": 1, "label": "other"}]) is None


def test_manifest_records_identity_and_source_hash():
    files = {"/sam_char.upk": (100, 8)}
    blobs = {100: LE}
    disc = StubDisc(files, blobs)
    rows, stats = census(disc)
    man = build_manifest(disc, rows, stats, "/owned/source.gcz", "a" * 64, 1075497093)
    assert man["game_id"] == "d11d44eeacdd5e31"
    assert man["source"]["sha256"] == "a" * 64
    assert man["source"]["bytes"] == 1075497093
    assert man["census"]["unreal_package_le"] == 1
    assert man["offset_base"].startswith("absolute byte offset")
    assert man["target_asset"]["path"] == "/sam_char.upk"
    json.dumps(man)                                    # manifest must stay serialisable


def test_disc_header_is_defensive_on_short_reads():
    assert disc_header(StubDisc({}, {}))["game_code"] == ""


def test_sha256_file_streams_bytes(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc" * 1000)
    assert sha256_file(p) == hashlib.sha256(b"abc" * 1000).hexdigest()
