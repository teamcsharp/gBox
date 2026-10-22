"""Focused tests for the CNR2 DOL header parser and PowerPC xref probe."""

import importlib.util
import os
import struct
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "gbox" / "cnr2_dol.py"

spec = importlib.util.spec_from_file_location("cnr2_dol", MODULE_PATH)
cnr2_dol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cnr2_dol)


def _build_dol(text: bytes, data: bytes, text_addr=0x80004000, data_addr=0x80010000):
    """Build a minimal two-section DOL around the given payloads."""
    text_file_offset = cnr2_dol.DOL_HEADER_SIZE
    data_file_offset = text_file_offset + len(text)
    words = [0] * 64
    words[cnr2_dol.W_TEXT_FILE_OFFSET] = text_file_offset
    words[cnr2_dol.W_DATA_FILE_OFFSET] = data_file_offset
    words[cnr2_dol.W_TEXT_LOAD_ADDRESS] = text_addr
    words[cnr2_dol.W_DATA_LOAD_ADDRESS] = data_addr
    words[cnr2_dol.W_TEXT_SIZE] = len(text)
    words[cnr2_dol.W_DATA_SIZE] = len(data)
    words[cnr2_dol.W_ENTRY_POINT] = text_addr
    return struct.pack(">64I", *words) + text + data


def _lis_addi(reg, target):
    """Encode lis rD,hi(target); addi rD,rD,lo(target) for reg."""
    hi = (target >> 16) & 0xFFFF
    lo = target & 0xFFFF
    if lo & 0x8000:
        hi = (hi + 1) & 0xFFFF
    lis = 0x3C000000 | (reg << 21) | hi
    addi = 0x38000000 | (reg << 21) | (reg << 16) | lo
    return struct.pack(">II", lis, addi)


def test_parse_dol_header_reads_sections_and_entry():
    text = b"\x60\x00\x00\x00" * 4
    data = b"fpack/chr/%s\x00"
    blob = _build_dol(text, data)
    header = cnr2_dol.parse_dol_header(blob)
    assert header["entry_point"] == 0x80004000
    present = cnr2_dol.present_sections(header)
    assert [s["kind"] for s in present] == ["text", "data"]
    assert present[0]["load_address"] == 0x80004000
    assert present[0]["size"] == len(text)
    assert present[1]["load_address"] == 0x80010000
    assert present[1]["size"] == len(data)


def test_parse_dol_header_rejects_short_buffer():
    with pytest.raises(ValueError):
        cnr2_dol.parse_dol_header(b"\x00" * 16)


def test_header_consistency_rejects_random_words():
    assert not cnr2_dol.dol_header_is_consistent(bytes(range(256)))


def test_flatten_dol_places_sections_at_runtime_addresses():
    text = b"\xAA" * 8
    data = b"fpack/chr/%s\x00"
    blob = _build_dol(text, data)
    image, base, header = cnr2_dol.flatten_dol(blob)
    assert base == 0x80004000
    assert image[0:8] == text
    assert image[0x80010000 - base : 0x80010000 - base + len(data)] == data
    assert header["entry_point"] == 0x80004000


def test_find_strings_reports_runtime_addresses():
    data = b"fpack/chr/%s\x00"
    blob = _build_dol(b"\x00" * 4, data)
    image, base, _ = cnr2_dol.flatten_dol(blob)
    found = cnr2_dol.find_strings(image, base, ["fpack/chr/%s"])
    assert found["fpack/chr/%s"] == [0x80010000]


def test_find_ppc_xrefs_finds_lis_addi_reference():
    target = 0x80010000
    text = b"\x60\x00\x00\x00" + _lis_addi(3, target) + b"\x4E\x80\x00\x20"
    data = b"fpack/chr/%s\x00"
    blob = _build_dol(text, data)
    image, base, header = cnr2_dol.flatten_dol(blob)
    hits = cnr2_dol.find_ppc_xrefs(image, base, header, [target])
    assert len(hits) == 1
    assert hits[0]["kind"] == "lis+addi"
    assert hits[0]["target"] == target
    assert hits[0]["site"] == 0x80004004
    assert hits[0]["ref"] == 0x80004008


def test_find_ppc_xrefs_ignores_unrelated_targets():
    text = b"\x60\x00\x00\x00" + _lis_addi(3, 0x80010000) + b"\x4E\x80\x00\x20"
    blob = _build_dol(text, b"fpack\x00")
    image, base, header = cnr2_dol.flatten_dol(blob)
    assert cnr2_dol.find_ppc_xrefs(image, base, header, [0x81234567]) == []


def test_cross_reference_dol_links_string_to_code_site():
    target = 0x80010000
    text = b"\x60\x00\x00\x00" + _lis_addi(3, target)
    blob = _build_dol(text, b"fpack/chr/%s\x00")
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / "cnr2_dol_probe_test.dol"
    tmp.write_bytes(blob)
    try:
        report = cnr2_dol.cross_reference_dol(str(tmp), ["fpack/chr/%s"])
    finally:
        tmp.unlink()
    assert report["base_address"] == 0x80004000
    assert report["strings"]["fpack/chr/%s"] == [target]
    assert report["xrefs"] and report["xrefs"][0]["needle"] == "fpack/chr/%s"
    assert report["sha256"] == cnr2_dol.hashlib.sha256(blob).hexdigest()


def test_real_main_dol_header_is_consistent():
    """The owned main.dol must parse; disc copies are encrypted and skipped."""
    candidates = [os.environ["CNR2_MAIN_DOL"]] if "CNR2_MAIN_DOL" in os.environ else None
    path = cnr2_dol.find_plaintext_dol(candidates)
    if path is None:
        pytest.skip("no plaintext main.dol available (disc copy is encrypted)")
    blob = path.read_bytes()
    image, base, header = cnr2_dol.flatten_dol(blob)
    assert base == 0x80004000
    assert header["entry_point"] & 0xFFFF0000 == 0x80000000
    present = cnr2_dol.present_sections(header)
    assert present and present[0]["kind"] == "text"
    assert sum(s["size"] for s in present) <= len(blob)
    found = cnr2_dol.find_strings(image, base, ["fpack"])
    for needle, addresses in found.items():
        for address in addresses:
            offset = address - base
            assert image[offset : offset + len(needle)] == needle.encode()
