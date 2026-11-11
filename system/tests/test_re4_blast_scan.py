"""The RE4 blast-entry scanner (checkpoint G3's tooling): area-attack sites and the blast-cluster descriptor slots.

The unit tests use a synthetic tiny image; the operator-image test is skipped when the extracted main is absent.
"""
import importlib.util
import struct
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "re4_blast_scan.py"
IMAGE = Path(r"D:\gBox\cache\re4-base\main.bin")


def load():
    spec = importlib.util.spec_from_file_location("re4_blast_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bl_word(target: int, at: int) -> int:
    off = (target - at) // 4
    return 0b100101 << 26 | (off & 0x3FFFFFF)


def test_bl_target_decodes_an_area_attack_call():
    scan = load()
    text = bytearray(0x200)
    struct.pack_into("<I", text, 0x100, bl_word(scan.AREA_ATTACK, 0x100))
    assert scan.bl_target(text, 0x100) == scan.AREA_ATTACK
    assert scan.bl_target(text, 0x104) is None


def test_a_synthetic_site_is_found_with_its_ids():
    scan = load()
    image = bytearray(0x100 + 0x400)
    base = 0x100
    # mov w3, #0x13 ; mov w1, #0x14 ; bl AREA_ATTACK  (at 0x100, 0x104, 0x108)
    struct.pack_into("<I", image, 0x100 + base, 0x52800000 | (0x13 << 5) | 3)       # mov w3, #0x13
    struct.pack_into("<I", image, 0x100 + base + 4, 0x52800000 | (0x14 << 5) | 1)   # mov w1, #0x14
    struct.pack_into("<I", image, 0x100 + base + 8, bl_word(scan.AREA_ATTACK, base + 8))
    data = scan.scan(bytes(image))
    assert len(data["sites"]) == 1
    site = data["sites"][0]
    assert site["site"] == base + 8 and site["class"] == 0x13 and site["sounds"][-1] == 0x14


@pytest.mark.skipif(not IMAGE.is_file(), reason="the extracted RE4 main is not on this machine")
def test_the_operator_image_has_the_three_known_blasts():
    scan = load()
    lines = scan.report(IMAGE.read_bytes())
    text = "\n".join(lines)
    assert "known blasts: 0x2e48b0 (hand), 0x2e4aa0 (simple), 0x2e4e50 (flash)" in text
    assert "area-attack sites:" in text
