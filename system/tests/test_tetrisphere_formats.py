"""Focused tests for the Tetrisphere (N64, USA) native asset inventory."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gbox.formats.tetrisphere import (  # noqa: E402
    CPU_CHARACTERS,
    DCM1_MAGIC,
    KSEG0,
    N64_ROM_MAGIC,
    SQSH_MAGIC,
    build_manifest,
    find_character_names,
    iter_blocks,
    read_rom_header,
    resolve_character_assets,
)


def _rom_path():
    candidates = [
        os.environ.get("TETRISPHERE_ROM"),
        "/home/ehm_eckx/.hermes/cache/scratch/tetrisphere-2479/Tetrisphere (USA).z64",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _synthetic():
    buf = bytearray(0x500)
    buf[0:4] = N64_ROM_MAGIC
    buf[4] = 0x14
    buf[0x20:0x2C] = b"TETRISPHERE"
    buf[0x3E] = ord("E")
    buf[0x100:0x104] = SQSH_MAGIC
    buf[0x200:0x204] = DCM1_MAGIC
    buf[0x300:0x308] = b"ROCKET\x00\x00"
    buf[0x400:0x404] = (0).to_bytes(4, "big")
    buf[0x404:0x408] = (KSEG0 | 0x300).to_bytes(4, "big")
    return bytes(buf)


def test_synthetic_blocks_and_roster():
    data = _synthetic()
    sqsh = iter_blocks(data, SQSH_MAGIC)
    assert len(sqsh) == 1 and sqsh[0].offset == 0x100
    dcm1 = iter_blocks(data, DCM1_MAGIC)
    assert len(dcm1) == 1 and dcm1[0].offset == 0x200
    names = find_character_names(data)
    assert names[0]["name"] == "ROCKET" and names[0]["name_offset"] == 0x300


def test_synthetic_pointer_binds_name_to_block():
    resolved = resolve_character_assets(_synthetic())
    rocket = [r for r in resolved if r["name"] == "ROCKET"][0]
    assert rocket["status"] == "resolved"
    assert rocket["blocks"][0]["offset"] == 0x100


def test_owned_build_header_and_counts():
    path = _rom_path()
    if not path:
        import pytest
        pytest.skip("owned Tetrisphere (USA) ROM unavailable in this environment")
    with open(path, "rb") as handle:
        data = handle.read()
    header = read_rom_header(data)
    assert header["country_code"] == "E"
    assert header["magic"] == N64_ROM_MAGIC.hex()
    assert len(iter_blocks(data, SQSH_MAGIC)) > 100
    assert len(iter_blocks(data, DCM1_MAGIC)) > 100


def test_owned_build_roster_is_complete():
    path = _rom_path()
    if not path:
        import pytest
        pytest.skip("owned Tetrisphere (USA) ROM unavailable in this environment")
    with open(path, "rb") as handle:
        data = handle.read()
    names = {entry["name"] for entry in find_character_names(data)}
    for name in CPU_CHARACTERS:
        assert name in names


def test_manifest_is_deterministic_and_serialisable():
    path = _rom_path()
    if not path:
        import pytest
        pytest.skip("owned Tetrisphere (USA) ROM unavailable in this environment")
    first = build_manifest(path, include_index_runs=False)
    second = build_manifest(path, include_index_runs=False)
    assert first["source_sha256"] == second["source_sha256"]
    assert len(first["source_sha256"]) == 64
    assert first["counts"] == second["counts"]
    assert first["byte_order"] == "big-endian"
    json.dumps(first)
