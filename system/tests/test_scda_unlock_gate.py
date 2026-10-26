"""Focused tests for the SCDA (GameCube, gwye41) unlock-gate discovery and binding helpers."""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gbox.scda_unlock_gate import (  # noqa: E402
    ARTIFACT_DIR,
    BUILD,
    DISC_ID,
    EXPECTED_DIGESTS,
    GATE_TOKENS,
    bind_gate_vaddrs,
    gate_report,
    scan_gate_tokens,
    sha256_file,
    verify_artifacts,
)

HAVE_ARTIFACTS = (ARTIFACT_DIR / "main.dol").is_file()


def test_gate_vocabulary_is_pinned():
    assert GATE_TOKENS == ("UnlockCondition", "UnLocked", "BashUnLocked")
    assert BUILD == "gwye41"
    assert DISC_ID == "GCEX41"


def test_scan_reports_all_tokens_even_when_absent():
    found = scan_gate_tokens(b"nothing to see here")
    assert set(found) == set(GATE_TOKENS)
    assert all(offsets == [] for offsets in found.values())


def test_scan_finds_each_token_at_its_true_offset():
    # "UnLocked" is a suffix of "BashUnLocked", so both hits must be reported.
    blob = b"\x00" + b"UnlockCondition" + b"\x00" + b"UnLocked" + b"\x00" + b"BashUnLocked"
    found = scan_gate_tokens(blob)
    assert found["UnlockCondition"] == [1]
    assert found["UnLocked"] == [17, 30]
    assert found["BashUnLocked"] == [26]


def test_scan_ignores_condition_text_that_is_not_a_gate():
    found = scan_gate_tokens(b" CONDITION `%s`")
    assert all(offsets == [] for offsets in found.values())


def test_verify_flags_a_digest_mismatch(tmp_path):
    (tmp_path / "main.dol").write_bytes(b"payload")
    report = verify_artifacts(tmp_path, expected={"main.dol": "0" * 64})
    entry = report["main.dol"]
    assert entry["present"] is True
    assert entry["matches"] is False
    assert entry["sha256"] == hashlib.sha256(b"payload").hexdigest()


def test_verify_accepts_a_correct_digest(tmp_path):
    (tmp_path / "main.dol").write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    report = verify_artifacts(tmp_path, expected={"main.dol": digest})
    assert report["main.dol"]["matches"] is True


def test_sha256_file_matches_hashlib(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abc" * 5000)
    assert sha256_file(path) == hashlib.sha256(b"abc" * 5000).hexdigest()


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_owned_artifacts_match_the_pinned_digests():
    report = verify_artifacts()
    for name, entry in report.items():
        assert entry["present"], name
        assert entry["matches"], name
    assert set(report) == set(EXPECTED_DIGESTS)


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_owned_dol_carries_every_gate_token():
    blob = (ARTIFACT_DIR / "main.dol").read_bytes()
    found = scan_gate_tokens(blob)
    for token in GATE_TOKENS:
        assert found[token], token
    assert found["UnlockCondition"] == sorted(found["UnlockCondition"])


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_gate_report_is_internally_consistent():
    report = gate_report()
    assert report["game_id"] == "3ee1e44d0f1ebf5e"
    assert report["all_artifacts_match"] is True
    assert all(report["gate_tokens_present"].values())


def _make_elf(vaddr: int, foff: int, size: int, data: bytes) -> bytes:
    """Build a minimal big-endian MIPS32 ELF with one PT_LOAD segment."""
    # ELF header (52 bytes)
    e_ident = b"\x7fELF\x01\x01\x01\x00" + b"\x00" * 9  # 64-bit, big-endian
    e_type = 2  # ET_EXEC
    e_machine = 0x0014  # MIPS
    e_version = 1
    e_entry = vaddr
    e_phoff = 52
    e_shoff = 0
    e_flags = 0
    e_ehsize = 52
    e_phentsize = 32
    e_phnum = 1
    e_shentsize = 0
    e_shnum = 0
    e_shstrndx = 0
    ehdr = e_ident + struct.pack(
        ">HHIIIIIHHHHHH",
        e_type, e_machine, e_version, e_entry, e_phoff, e_shoff, e_flags,
        e_ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum, e_shstrndx,
    )
    # Program header
    p_type = 1  # PT_LOAD
    p_offset = foff
    p_vaddr = vaddr
    p_paddr = vaddr
    p_filesz = size
    p_memsz = size
    p_flags = 5  # PF_R | PF_X
    p_align = 0x1000
    phdr = struct.pack(">8I", p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align)
    return ehdr + phdr + data


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_bind_gate_vaddrs_finds_unlockcondition():
    """The bind_gate_vaddrs function must find the correct ELF vaddr for UnlockCondition."""
    dol = (ARTIFACT_DIR / "main.dol").read_bytes()
    elf = (ARTIFACT_DIR / "main.elf").read_bytes()
    bindings = bind_gate_vaddrs(dol, elf)
    assert "UnlockCondition" in bindings
    assert len(bindings["UnlockCondition"]) == 1
    # The known correct vaddr from the Ghidra analysis
    assert bindings["UnlockCondition"][0] == 0x805FF55A


@pytest.mark.skipif(not HAVE_ARTIFACTS, reason="owned build artifacts not present")
def test_bind_gate_vaddrs_finds_all_tokens():
    """All three gate tokens must be found and bound to their ELF vaddrs."""
    dol = (ARTIFACT_DIR / "main.dol").read_bytes()
    elf = (ARTIFACT_DIR / "main.elf").read_bytes()
    bindings = bind_gate_vaddrs(dol, elf)
    assert len(bindings["UnLocked"]) == 2
    assert len(bindings["BashUnLocked"]) == 1
    # Verify the vaddrs contain the expected strings
    for vaddr in bindings["UnLocked"]:
        foff = None
        # Find the file offset for this vaddr
        e_phoff = struct.unpack_from(">I", elf, 28)[0]
        e_phnum = struct.unpack_from(">H", elf, 44)[0]
        for i in range(e_phnum):
            off = e_phoff + i * 32
            p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = (
                struct.unpack(">8I", elf[off : off + 32])
            )
            if p_type == 1 and p_vaddr <= vaddr < p_vaddr + p_filesz:
                foff = p_offset + (vaddr - p_vaddr)
                break
        assert foff is not None
        assert elf[foff : foff + 8] == b"UnLocked"
