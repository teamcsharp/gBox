"""Verified string locators in the DOA5 Last Round PS3 EBOOT.elf.

Owned PS3 Japan disc 7z (sha256 85b2366710c82b8dc9da5ca2cfbcb818c95f8113078babe79c7731ca1de13ac7)
provides EBOOT.elf (ELF64-BE PPC64, 21,968,532 B, sha256 7747903e...533c) cached at
/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/eboot/EBOOT.elf.

Findings verified by direct byte scan on 2026-11-12 (lilspark2):

* 'chara_common.order' -- 0 hits in EBOOT.elf. The LFMO name-cipher key
  resource referenced by the LFMO grammar is NOT embedded under that
  plaintext name, so roster-character identity resolution requires the
  decoder function, not a plaintext key lookup (Ghidra xrefs on the
  name tables below).
* LFMO names[18] (target slot 0018) without its leading '/' appears at
  0x0108BF6C (cipher name table 0x01081000-0x010F0000) and again at
  0x010ED69C, where the full 55-char name ...DK1DBSH17O{TEAL71M is NUL-terminated at 0x010ED6D3.
  A same-family variant name (field-3 17KE1...DC8SG) sits at 0x010EC74C.
* Monitor name table head at 0x0106D84C ('kasumi_05_01_monitor_PP1').
* Roster base name table: 'ayane_01_base' at 0x010713B0 with 0x20
  stride; 'kasumi_01_base' at 0x010719B0.
* LFMO grammar magic at 0x011A77F4.

Roster tables (verified 2026-11-12 direct scan):

* Monitor name table: packed NUL-terminated strings from 0x0106D80C
  (jannlee_02_01_monitor_PP1 ... bayman_24_01_monitor_PP1), roster
  numbering with variant suffixes; NOT uniform stride.
* Base roster table: uniform 0x20 stride from 0x01071130 (leon_01_base
  ... 89 entries; per-character 01-04 variant slots).
* 'chara_common.order' absent; the 0x01079BA6 'order' hits sit next to a
  demangled C++ symbol, i.e. code text, not the resource name.
"""
from __future__ import annotations

import hashlib

EBOOT_SHA256 = "7747903ecdda5b686658654bcfbcd4590815f6416220e24ef458338ca446533c"
EBOOT_SIZE = 21_968_532
EBOOT_CACHE = "/home/ehm_eckx/gBox_alt/gbox-cache/research/doa5lr_samples_2450/eboot/EBOOT.elf"

# LFMO names[18] minus its leading '/' (first 40 bytes verified in ELF).
TARGET_NAME_PREFIX = "BR87Y@10T10000@DD1]T]D128K00RJ1M1J1G1DK1"
TARGET_VARIANT_PREFIX = "BR87Y@10T10000@DD1]T]17KE1RJ1M1J1G1DC8SG"

LOCATORS = {
    "target_name_table1": (0x0108BF6C, TARGET_NAME_PREFIX),
    "target_name_table2": (0x010ED69C, TARGET_NAME_PREFIX),
    "target_name_variant": (0x010EC74C, TARGET_VARIANT_PREFIX),
    "monitor_table_head": (0x0106D84C, "kasumi_05_01_monitor_PP1"),
    "monitor_table_start": (0x0106D80C, "jannlee_02_01_monitor_PP1"),
    "base_table_start": (0x01071130, "leon_01_base"),
    "base_table_end": (0x01071130 + 0x20 * 88, None),  # 89 uniform 0x20-stride entries
    "roster_base_ayane01": (0x010713B0, "ayane_01_base"),
    "roster_base_kasumi01": (0x010719B0, "kasumi_01_base"),
    "lfmo_magic": (0x011A77F4, "LFMO"),
}

# Verified absent from EBOOT.elf (0 hits, 2026-11-12 byte scan).
ABSENT_STRINGS = ("chara_common.order",)


def check_identity(data: bytes) -> None:
    """Raise ValueError unless data is the exact owned EBOOT.elf."""
    if len(data) != EBOOT_SIZE:
        raise ValueError(f"EBOOT size {len(data)} != {EBOOT_SIZE}")
    got = hashlib.sha256(data).hexdigest()
    if got != EBOOT_SHA256:
        raise ValueError(f"EBOOT sha256 {got} != {EBOOT_SHA256}")


def locate(data: bytes) -> dict:
    """Verify every locator/absence claim against the EBOOT bytes."""
    found = {}
    for name, (off, needle) in LOCATORS.items():
        raw = (needle or "").encode("latin-1")
        found[name] = {
            "expected_offset": off,
            "match_at_expected": data[off : off + len(raw)] == raw,
            "first_occurrence": data.find(raw),
        }
    for name in ABSENT_STRINGS:
        found[name] = {"absent": data.find(name.encode("latin-1")) == -1}
    return found


def verify(data: bytes) -> bool:
    """True iff identity holds and every locator/absence claim matches."""
    check_identity(data)
    r = locate(data)
    return all(
        v["match_at_expected"] if "match_at_expected" in v else v["absent"]
        for v in r.values()
    )
