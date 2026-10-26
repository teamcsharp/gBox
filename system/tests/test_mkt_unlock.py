"""Focused tests for MKT N64 unlock profile generation and verification.

Run: python3 -m pytest system/tests/test_mkt_unlock.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gbox"))

from mkt_unlock import (
    ROM_CRC32,
    ROM_GAME,
    ROM_PLATFORM,
    ROM_SHA1,
    ROM_SIZE,
    UNLOCK_FLAGS,
    build_profile,
    get_cheat_lines,
    verify_profile,
    write_profile,
)


@pytest.fixture()
def system_root(tmp_path: Path) -> Path:
    """Create a temporary system root with the profile written."""
    root = tmp_path / "system"
    root.mkdir()
    write_profile(root)
    return root


class TestROMIdentity:
    def test_sha1(self):
        assert ROM_SHA1 == "63d68c330558c63527f6c36f77b0b8f8dcc377f6"

    def test_crc32(self):
        assert ROM_CRC32 == "4601fe86"

    def test_size(self):
        assert ROM_SIZE == 10877773

    def test_game(self):
        assert ROM_GAME == "Mortal Kombat Trilogy (USA)"
        assert ROM_PLATFORM == "Nintendo 64"


class TestUnlockFlags:
    def test_count(self):
        assert len(UNLOCK_FLAGS) == 11

    def test_hidden_characters(self):
        hidden = [f for f in UNLOCK_FLAGS if f[3] == "hidden_character"]
        assert len(hidden) == 3
        descs = [f[2] for f in hidden]
        assert any("Human Smoke" in d for d in descs)
        assert any("Khameleon" in d for d in descs)

    def test_game_modes(self):
        modes = [f for f in UNLOCK_FLAGS if f[3] == "game_mode"]
        assert len(modes) == 8

    def test_addresses_in_rdram(self):
        for addr, _, desc, _ in UNLOCK_FLAGS:
            assert 0x80000000 <= addr <= 0x803FFFFF, (
                f"{desc} address 0x{addr:08X} outside RDRAM"
            )

    def test_values_are_small(self):
        for _, val, desc, _ in UNLOCK_FLAGS:
            assert 0 <= val <= 255, f"{desc} value {val} not uint8"


class TestProfileBuild:
    def test_structure(self):
        profile = build_profile()
        assert "title" in profile
        assert "rom" in profile
        assert "cheats" in profile
        assert "verification" in profile
        assert len(profile["cheats"]) == 11

    def test_rom_section(self):
        profile = build_profile()
        rom = profile["rom"]
        assert rom["sha1"] == ROM_SHA1
        assert rom["crc32"] == ROM_CRC32
        assert rom["size"] == ROM_SIZE

    def test_cheat_format(self):
        profile = build_profile()
        for cheat in profile["cheats"]:
            assert "desc" in cheat
            assert "address" in cheat
            assert "value" in cheat
            assert cheat["type"] == "uint8"
            assert cheat["address"].startswith("0x")
            addr_int = int(cheat["address"], 16)
            assert 0x80000000 <= addr_int <= 0x803FFFFF


class TestProfileWrite:
    def test_write_and_verify(self, system_root: Path):
        result = verify_profile(system_root)
        assert result["ok"], f"Verification failed: {result}"
        assert result["cheat_count"] == 11

    def test_profile_file_exists(self, system_root: Path):
        profile_file = system_root / "profiles" / "gamedata" / "cb47d622c26b67f8-unlock.json"
        assert profile_file.exists()
        data = json.loads(profile_file.read_text())
        assert data["rom"]["sha1"] == ROM_SHA1
        assert len(data["cheats"]) == 11


class TestGameSharkCodes:
    def test_code_count(self):
        lines = get_cheat_lines()
        assert len(lines) == 11

    def test_code_format(self):
        for line in get_cheat_lines():
            # Format: "description: TTVVAAAA VVVV"
            assert ": " in line
            code_part = line.split(": ", 1)[1]
            parts = code_part.split(" ")
            assert len(parts) == 2
            assert len(parts[0]) == 12  # TTVVAAAA (12 hex chars)
            assert len(parts[1]) == 4   # VVVV (4 hex chars)

    def test_all_addresses_unique(self):
        lines = get_cheat_lines()
        addresses = set()
        for line in lines:
            code = line.split(": ", 1)[1].split(" ")[0]
            addr = code[4:]  # Last 8 hex chars = address
            addresses.add(addr)
        assert len(addresses) == len(lines), "Duplicate addresses found"
