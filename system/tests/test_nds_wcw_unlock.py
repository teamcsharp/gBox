"""Focused tests for the NDS World at War candidate unlock profile (#2070).

These validate encoding, ROM binding and honesty flags only. They are not
gameplay verification: the read-back probe in verification_plan owns that.
"""
from pathlib import Path

import pytest

from gbox import nds_wcw_unlock as W

NDS = Path("/home/ehm_eckx/gBox_alt/gbox-cache/d9467f457f53f2c7/2905 - Call of Duty - World at War (U)(Venom).nds")
CHT = Path("/home/ehm_eckx/gBox/system/gbox-data/cheatdb/libretro-database/cht/Nintendo - Nintendo DS/Call of Duty - World at War (USA).cht")


def test_unlock_ops_match_cht_16bit_little_endian_prefix():
    ops = {o["field"]: o for o in W.unlock_ops()}
    assert set(ops) == {"all_countries_quickplay", "challenge_mode_complete"}
    for o in ops.values():
        assert o["width"] == 2
        assert o["hex_bytes"] == "1e00"  # value 0x001E little-endian; neighbours preserved by 2-byte write
        assert not o["gameplay_verified"] and not o["database_verified"]
    assert ops["all_countries_quickplay"]["address"] == 0x021B77A9
    assert ops["challenge_mode_complete"]["address"] == 0x021B77C1


def test_addresses_inside_nds_main_ram_window():
    for _name, (_p, address, _v, width, _d) in W.UNLOCK_FIELDS.items():
        assert W.in_main_ram(address, width)
    assert not W.in_main_ram(0x08000000, 2)
    assert not W.in_main_ram(0x023FFFFF, 4)  # straddles the window end


def test_expected_bytes_roundtrip():
    import struct
    assert W.expected_bytes("challenge_mode_complete") == struct.pack("<H", 0x1E)


def test_profile_is_honest_about_unverified_state():
    p = W.profile()
    assert p["verified"] == [] and not p["gameplay_verified"] and not p["complete_unlock_profile"]
    assert p["requires_live_readback"]
    assert "known_gap" in p and p["known_gap"]
    assert p["rom_sha256"] == W.ROM_SHA256


def test_rom_guard_pins_owned_revision():
    if not NDS.is_file():
        pytest.skip("owned ROM not in cache on this host")
    assert W.rom_guard(NDS)["ok"]
    assert not W.rom_guard(CHT)["ok"]  # any other bytes must be refused


def test_database_binding_and_ops_agree_with_installed_cht():
    if not CHT.is_file():
        pytest.skip("installed cheat database not available")
    assert W.DATABASE_SHA256 == __import__("hashlib").sha256(CHT.read_bytes()).hexdigest()
    from gbox import cheats
    entries = {e["desc"]: e for e in cheats.parse_cht(CHT.read_text(encoding="utf-8"))}
    for field, desc in (("all_countries_quickplay", "All Countries Unlocked (Quickplay)"),
                        ("challenge_mode_complete", "Complete Challenge Mode")):
        code = entries[desc]["code"].replace(" ", "").replace("-", "")
        assert code == W.cht_token(field), (code, W.cht_token(field))


def test_verification_plan_requires_readback():
    plan = W.verification_plan("sess-abc")
    assert plan["read_back_required"] and "rollback" in plan
    assert plan["steps"][-1].startswith("5.")
