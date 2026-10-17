"""Focused tests for gbox.toohuman_inventory: classification and XEX identity.

The disc walk itself is exercised in production via gbox.re6.XDVD (already covered
by the RE6 suite); these tests pin the Too Human-specific asset classification and
the XEX2 title-id read without needing the 6.6 GB owned ISO. An integration test is
included but skips unless GBOX_TOOHUMAN_ISO is set.
"""

from __future__ import annotations

import os
import struct

import pytest

from gbox import toohuman_inventory as th


def _xex(with_execution=True):
    header = bytearray(0x60)
    header[:4] = b"XEX2"
    struct.pack_into(">II", header, 4, 1, len(header))
    if with_execution:
        struct.pack_into(">I", header, 20, 1)
        struct.pack_into(">II", header, 24, 0x00040006, 0x40)
        struct.pack_into(">I", header, 0x4c, 0x4D5307D1)
    return header


def test_xex_info_reads_title_id_from_optional_header():
    info = th.xex_info(bytes(_xex()))
    assert info["module_flags"] == "0x1"
    assert info["header_size"] == "0x60"
    assert info["title_id"] == "0x4d5307d1"
    assert info["title_id_offset"] == 0x4c


def test_xex_info_ignores_execution_signature_outside_optional_table():
    header = _xex(False)
    struct.pack_into(">II", header, 0x30, 0x00040006, 0x40)
    assert th.xex_info(bytes(header))["title_id"] is None


@pytest.mark.parametrize("kind", ["short", "count", "offset"])
def test_xex_info_rejects_truncated_or_out_of_range_records(kind):
    header = _xex()
    if kind == "short":
        header = header[:12]
    elif kind == "count":
        struct.pack_into(">I", header, 20, 100)
    else:
        struct.pack_into(">I", header, 28, len(header) - 8)
    with pytest.raises(ValueError):
        th.xex_info(bytes(header))


def test_classify_groups_character_families():
    files = {
        "/pla001.zzz.gz": (0, 1),
        "/pla001_aug_assault1_torso.zzz.gz": (0, 1),
        "/pla001_aug_g42_torso.zzz.gz": (0, 1),
        "/god003_r.zzz.gz": (0, 1),
        "/god014.zzz.gz": (0, 1),
        "/enm001.zzz.gz": (0, 1),
        "/npc001.zzz.gz": (0, 1),
        "/mon002.zzz.gz": (0, 1),
        "/wep001_aug_001.zzz.gz": (0, 1),
        "/world00.zzz.gz": (0, 1),
        "/world00_Tex.g00.gz": (0, 1),   # has a subdir-like name, stays out of root families
    }
    fam = th.classify(files)
    assert fam["player_pla001"] == ["pla001.zzz.gz"]
    assert len(fam["player_armor"]) == 2
    assert fam["gods"] == ["god003_r.zzz.gz", "god014.zzz.gz"]
    assert fam["enemies"] == ["enm001.zzz.gz"]
    assert fam["npcs"] == ["npc001.zzz.gz"]
    assert fam["monsters"] == ["mon002.zzz.gz"]
    assert fam["weapons"] == ["wep001_aug_001.zzz.gz"]
    assert "world00.zzz.gz" in fam["other_root_zzz"]
    assert "world00_Tex.g00.gz" not in fam["other_root_zzz"]  # not a root-level .zzz.gz asset


def test_classify_ignores_non_root_and_non_zzz():
    files = {
        "/Cinematics/w00_scene01.stm.gz": (0, 1),
        "/Italian/8/849066430.xma": (0, 1),
        "/Baldur.bnk": (0, 1),
        "/god003_r.zzz.gz": (0, 1),
    }
    fam = th.classify(files)
    assert fam["gods"] == ["god003_r.zzz.gz"]
    assert all(v == [] for k, v in fam.items() if k != "gods")


@pytest.mark.skipif(not os.environ.get("GBOX_TOOHUMAN_ISO"), reason="owned ISO not set")
def test_inventory_against_owned_disc():
    iso = os.environ["GBOX_TOOHUMAN_ISO"]
    man = th.inventory(iso)
    assert man["executable"]["magic"] == "XEX2"
    assert man["disc"]["files"] > 20000
    assert man["assets"]["character_roster"]["player_pla001"]
