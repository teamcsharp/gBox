import importlib.util
import os
import struct

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD_PATH = os.path.join(HERE, "gbox", "wrestlemania_xix_inventory.py")


def _load():
    spec = importlib.util.spec_from_file_location("wm19_inventory", MOD_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wm = _load()


def _synthetic():
    blob = struct.pack(">4I", 0x30, 0x40, 0x20, 0x48) + b"\x00" * 20
    blob += b"root" + struct.pack(">II", 1, 3)
    blob += b"dat0" + struct.pack(">II", 0x60, 0xFF000003)
    blob += b"end\x00" + struct.pack(">II", 0x70, 0)
    return blob


def test_header_and_record_layout():
    c = wm.parse_container(_synthetic())
    assert c["header"][0] == 0x30
    assert c["table_start"] == 0x24
    assert c["record_count"] == 2
    assert c["entries"][0] == {"name": "root", "kind": "dir", "w1": 1, "w2": 3}
    assert c["entries"][1] == {"name": "dat0", "kind": "file", "size": 3,
                               "offset": 0x60}


def test_categories_match_discovered_prefixes():
    assert wm.CATEGORIES == sorted(wm.CATEGORIES)
    assert "char" in wm.CATEGORIES
    assert "rule" in wm.CATEGORIES
    assert len(wm.CATEGORIES) == 25


def test_lock_surface_is_not_claimed_verified():
    assert wm.LOCK_SURFACE["located"] is False
    gate = wm.profile_gate()
    assert gate["verified"] is False
    assert gate["writer"] is None
    assert gate["next_step"]


def test_real_iso_container_structure():
    if not os.path.exists(wm.ISO_PATH):
        pytest.skip("owned ISO not present")
    inv = wm.inventory()
    ents = inv["com_dt_mpc"]["entries"]
    names = [e["name"] for e in ents]
    assert names[:5] == ["root", "com", "cmn", "tbl", "bg"]
    assert names[:5] == ["root", "com", "cmn", "tbl", "bg"]
    by = {e["name"]: e for e in ents}
    assert inv["com_dt_mpc"]["header"] == [0x57C, 0xB7C60, 0x20, 0x5A0]
    assert by["cmn0"] == {"name": "cmn0", "kind": "file", "size": 3, "offset": 0}
    assert by["char"]["kind"] == "file" and by["char"]["size"] == 0xA6
    assert by["rule"]["offset"] == 0xE40
    assert inv["iso_sha256"] == wm.ISO_SHA256
    assert sorted(inv["categories"]) == wm.CATEGORIES
    assert inv["game_code"] == wm.GAME_CODE
