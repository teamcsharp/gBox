"""The RE4 .bss private-storage verifier (checkpoint E3): synthetic NSO images exercise every check.

No game file is needed: the builder writes the NSO0 header the verifier reads, so each test controls the section
layout and the one static reference it plants into `.bss`. The measured RE4 layout's candidates are a separate,
image-only run (scripts/verify_re4_bss.py on the operator's main.bin).
"""
import importlib.util
import struct
from pathlib import Path

import pytest

from gbox import nso_elf

SHIFT = 0x100


def _load_tool():
    path = Path(__file__).resolve().parents[1] / "scripts" / "verify_re4_bss.py"
    spec = importlib.util.spec_from_file_location("verify_re4_bss", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V = _load_tool()

TEXT_SIZE = 0x400
RODATA_MEMORY, RODATA_SIZE = 0x1000, 0x100
DATA_MEMORY, DATA_SIZE = 0x1100, 0xF00          # .bss starts exactly at 0x2000
BSS_SIZE = 0x8000                                # .bss 0x2000..0xA000


def nso_image(*, text=b"", rodata=b"", data=b"", text_size=TEXT_SIZE, rodata_memory=RODATA_MEMORY,
              rodata_size=RODATA_SIZE, data_memory=DATA_MEMORY, data_size=DATA_SIZE, bss_size=BSS_SIZE,
              truncate=0):
    end = max(rodata_memory + rodata_size, data_memory + data_size, len(text))
    image = bytearray(SHIFT + end - truncate)
    struct.pack_into("<4s", image, 0, b"NSO0")
    struct.pack_into("<I", image, 0x0C, 0)
    struct.pack_into("<I", image, 0x10, SHIFT)
    struct.pack_into("<I", image, 0x14, 0)
    struct.pack_into("<I", image, 0x18, text_size)
    struct.pack_into("<I", image, 0x1C, 0)
    struct.pack_into("<I", image, 0x20, SHIFT + rodata_memory)
    struct.pack_into("<I", image, 0x24, rodata_memory)
    struct.pack_into("<I", image, 0x28, rodata_size)
    struct.pack_into("<I", image, 0x30, SHIFT + data_memory)
    struct.pack_into("<I", image, 0x34, data_memory)
    struct.pack_into("<I", image, 0x38, data_size)
    struct.pack_into("<I", image, 0x3C, bss_size)
    image[SHIFT:SHIFT + len(text)] = text
    image[SHIFT + rodata_memory:SHIFT + rodata_memory + len(rodata)] = rodata
    image[SHIFT + data_memory:SHIFT + data_memory + len(data)] = data
    return bytes(image)


def put(image, vaddr, blob):
    image = bytearray(image)
    image[SHIFT + vaddr:SHIFT + vaddr + len(blob)] = blob
    return bytes(image)


def adrp(pc, rd, target):
    page = target & ~0xFFF
    imm = (page - (pc & ~0xFFF)) >> 12
    immlo, immhi = imm & 3, (imm >> 2) & 0x7FFFF
    return struct.pack("<I", 0x90000000 | (immlo << 29) | (immhi << 5) | rd)


def add_imm(rd, rn, imm):
    return struct.pack("<I", 0x91000000 | ((imm & 0xFFF) << 10) | (rn << 5) | rd)


def ldr_imm(rt, rn, disp):
    return struct.pack("<I", 0xF9400000 | (((disp // 8) & 0xFFF) << 10) | (rn << 5) | rt)


# ---- finding candidates ------------------------------------------------------------------------------------------------

def test_a_clean_image_offers_every_aligned_bss_page():
    report = V.evaluate(nso_image())
    assert report["usable"] is True
    assert report["bss"]["at"] == "0x2000" and report["bss"]["size"] == BSS_SIZE
    assert report["free_window_count"] == BSS_SIZE // 0x1000
    assert report["candidates"][0] == "0x2000" and report["last_candidates"][-1] == "0x9000"
    assert report["largest_gap"]["at"] == "0x2000" and report["largest_gap"]["size"] == BSS_SIZE


def test_an_adrp_add_reference_removes_its_page():
    image = put(nso_image(), 0x40, adrp(0x40, 8, 0x2000) + add_imm(8, 8, 0x100))   # 0x2000 + 0x100
    report = V.evaluate(image)
    assert report["free_window_count"] == BSS_SIZE // 0x1000 - 1
    assert "0x2000" not in report["candidates"]
    assert report["reference_rows"][0]["kind"] == "adrp+add"
    assert report["reference_rows"][0]["target"] == "0x2100"
    assert V.evaluate(image, at=0x2000)["usable"] is False


def test_an_adrp_load_reference_removes_its_page():
    image = put(nso_image(), 0x80, adrp(0x80, 9, 0x3000) + ldr_imm(0, 9, 0x40))    # 0x3000 + 0x40
    report = V.evaluate(image)
    assert report["reference_rows"][0]["kind"] == "adrp+mem"
    assert report["reference_rows"][0]["target"] == "0x3040"
    assert "0x3000" not in report["candidates"]


def test_a_64_bit_literal_removes_its_page():
    image = put(nso_image(), RODATA_MEMORY + 0x20, struct.pack("<Q", 0x4000))
    report = V.evaluate(image)
    assert report["reference_rows"][0] == {"at": hex(RODATA_MEMORY + 0x20), "target": "0x4000",
                                           "kind": "literal-64"}
    assert "0x4000" not in report["candidates"]


def test_a_reference_just_past_the_window_does_not_count():
    image = put(nso_image(), 0x40, adrp(0x40, 8, 0x3000) + add_imm(8, 8, 0x100))   # 0x3100, page 0x3000
    # a 0x100-byte window ending at the reference is free; the full page containing it is not
    assert V.evaluate(image, size=0x100, at=0x3000)["usable"] is True
    report = V.evaluate(image, size=0x1000, at=0x3000)
    assert report["usable"] is False and "1 static reference" in report["reason"]


def test_an_adr_into_bss_counts():
    # ADR reaches +/-1 MB; the synthetic text and .bss are close, so aim it at 0x2800 from pc 0x100.
    pc, target = 0x100, 0x2800
    imm = target - pc
    immlo, immhi = imm & 3, (imm >> 2) & 0x7FFFF
    image = put(nso_image(), pc, struct.pack("<I", 0x10000000 | (immlo << 29) | (immhi << 5) | 0))
    report = V.evaluate(image)
    assert report["reference_rows"][0]["kind"] == "adr" and report["reference_rows"][0]["target"] == "0x2800"
    assert "0x2000" not in report["candidates"]


# ---- vetting one chosen range and the CLI -----------------------------------------------------------------------------

def test_a_range_outside_bss_or_unaligned_is_refused():
    report = V.evaluate(nso_image(), at=0x1000)                                   # .rodata page
    assert report["usable"] is False and "inside .bss" in report["reason"]
    report = V.evaluate(nso_image(), at=0x2100)                                   # 64-aligned, not 4 KiB
    assert report["usable"] is False and "page" in report["reason"]


def test_a_size_larger_than_a_page_is_refused():
    with pytest.raises(ValueError):
        V.evaluate(nso_image(), size=0x2000)


def test_a_truncated_or_foreign_image_is_refused():
    with pytest.raises(nso_elf.NsoError):
        V.evaluate(b"\x00" * 0x200)
    with pytest.raises(nso_elf.NsoError):
        V.evaluate(nso_image(truncate=0x80))


def test_the_cli_reports_pass_and_fail(tmp_path, capsys):
    good = tmp_path / "main.bin"
    good.write_bytes(nso_image())
    assert V.main(["verify_re4_bss.py", str(good)]) == 0
    assert "PASS" in capsys.readouterr().out
    bad = tmp_path / "bad.bin"
    bad.write_bytes(put(nso_image(), 0x40, adrp(0x40, 8, 0x2000) + add_imm(8, 8, 0x100)))
    assert V.main(["verify_re4_bss.py", str(bad), "--at", "0x2000"]) == 1
    assert "FAIL" in capsys.readouterr().out
