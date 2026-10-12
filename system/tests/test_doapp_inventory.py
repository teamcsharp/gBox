"""Focused tests for gbox.doapp_inventory (Dead Or Alive ++ / Tecmo TPS).

Self-contained: synthetic zips only, no SMB/network access.
"""

import hashlib
import json
import os
import tempfile
import zipfile

import pytest

from gbox.doapp_inventory import (
    BANKED_ROMS,
    ROSTER,
    SCEI_LICENSE,
    find_roster,
    inventory,
    merge_banked,
    tim_count,
    verify_rom_sha1,
)


def _make_zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


@pytest.fixture
def src_dir(tmp_path):
    """Synthetic clone/parent/bios zips with the right member NAMES.

    Content is fake, so the dat-sha1 verification is expected to fail;
    that failure path is itself asserted.
    """
    d = tmp_path / "roms"
    d.mkdir()
    _make_zip(
        str(d / "doappk.zip"),
        {"doapp_u0119.119": b"\x11" * 0x100, "doapp_u0120.120": b"\x22" * 0x100},
    )
    parent = {"doapp-0.216": b"\x33" * 0x100}
    for name in ("doapp-1.217", "doapp-2.218", "doapp-3.219",
                 "doapp-4.220", "doapp-5.221"):
        parent[name] = b"\x00" * 0x40
    parent.update({"doapp119.bin": b"\x44" * 0x100,
                   "doapp120.bin": b"\x55" * 0x100, "mg05": b"\x00" * 8})
    _make_zip(str(d / "doapp.zip"), parent)
    _make_zip(
        str(d / "coh1002m.zip"),
        {"m534002c-61.ic353": b"\x66" * 0x100, "mg01.ic652": b"\x00" * 8},
    )
    return str(d)


def test_merge_banked_interleave(src_dir):
    merged = merge_banked(src_dir + "/doappk.zip", src_dir + "/doapp.zip")
    assert len(merged) == 0x2800000
    # 119 = odd bytes, 120 = even bytes (ROM_LOAD16_BYTE +1/+0)
    assert merged[0] == 0x22 and merged[1] == 0x11
    assert merged[0x400000] == 0x33  # doapp-0.216 at 0x400000
    assert SCEI_LICENSE not in merged  # synthetic data has no license string


def test_merge_banked_layout_offsets(src_dir):
    merged = merge_banked(src_dir + "/doappk.zip", src_dir + "/doapp.zip")
    for name, (off, size, _) in BANKED_ROMS.items():
        if name.startswith("doapp_u0"):
            continue  # interleaved pair, checked in test above
        blob = merged[off:off + 0x40]
        assert len(blob) == 0x40


def test_find_roster_finds_ordered_table():
    data = bytearray(0x1000)
    names = b"....".join(n.encode() for n in ROSTER)
    data[0x333:0x333 + len(names)] = names
    hits = find_roster(bytes(data))
    assert 0x333 in {o for o, _ in hits}
    assert 0x123 not in {o for o, _ in hits}


def test_find_roster_rejects_shuffled_order():
    data = b"".join(n.encode() + b".." for n in reversed(ROSTER))
    assert find_roster(data) == []


def test_verify_rom_sha1_reports_mismatch(tmp_path):
    p = _make_zip(str(tmp_path / "r.zip"), {"m": b"data"})
    problems = verify_rom_sha1(p, {"m": "00" * 40, "absent": "00" * 40})
    assert any("m: expected" in x for x in problems)
    assert any("absent: missing" in x for x in problems)


def test_verify_rom_sha1_passes_match(tmp_path):
    data = b"data"
    p = _make_zip(str(tmp_path / "r.zip"), {"m": data})
    assert verify_rom_sha1(p, {"m": hashlib.sha1(data).hexdigest()}) == []


def test_tim_count():
    assert tim_count(b"\x10\x00\x00\x00" * 3 + b"\x10\x01\x00\x00") == 3


def test_inventory_manifest_structure(src_dir, tmp_path):
    out = str(tmp_path / "manifest.json")
    m = inventory(src_dir, out)
    assert m["game_id"] == "59c55e95af61abbe"
    assert m["mame_set"] == "doappk" and m["clone_of"] == "doapp"
    assert m["bios_set"] == "coh1002m"
    assert m["platform"]["driver"] == "zn2p"
    assert m["characters"]["roster"] == ROSTER
    assert m["container"]["bankedroms_size"] == 0x2800000
    assert m["sources"]["clone_zip"]["sha256"]
    # synthetic ROM contents must fail the dat check loudly, not silently
    flat = " ".join(json.dumps(m["rom_verification"]).split())
    assert "expected" in flat
    assert json.load(open(out))["launch"]["mame_set"] == "doappk"


def test_inventory_requires_all_zips(tmp_path):
    with pytest.raises(FileNotFoundError):
        inventory(str(tmp_path))
