"""Focused tests for the revision-guarded S&K RAM map and unlock plan."""
from __future__ import annotations

import hashlib
import pathlib
import sys
import zipfile

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from gbox import sk_ram_map as M

CACHE = pathlib.Path("/home/ehm_eckx/gBox_alt/gbox-cache/668e74c15d61a9a7")
ROM_ZIP = CACHE / "source.zip"
ASM = CACHE / "disasm" / "sonic3k.asm"


@pytest.fixture(scope="module")
def rom():
    if not ROM_ZIP.exists():
        pytest.skip("owned ROM not present in this environment")
    with zipfile.ZipFile(ROM_ZIP) as zf:
        return zf.read(zf.namelist()[0])


def test_verified_table_is_in_work_ram():
    for sym, hexaddr in M.VERIFIED_RAM.items():
        a = int(hexaddr, 16)
        assert M.RAM_START <= a <= M.RAM_END, (sym, hexaddr)


def test_revision_guard_accepts_owned_rom(rom):
    assert M.revision_ok(rom)
    assert hashlib.sha256(rom).hexdigest() == M.ROM_SHA256


def test_revision_guard_rejects_other_rom(rom):
    assert not M.revision_ok(rom[:-1] + bytes([rom[-1] ^ 0xFF]))


def test_resolver_rejects_ambiguous_symbols(rom):
    if not ASM.exists():
        pytest.skip("disassembly not present in this environment")
    res = M.resolve_ram_symbols(rom, ASM.read_text(errors="replace"))
    assert res
    # documented negative result: no symbol is both unique and non-colliding
    import collections
    cnt = collections.Counter(r["addr"] for r in res.values() if r["distinct"] == 1)
    strict = [k for k, r in res.items()
              if r["distinct"] == 1 and r["votes"] >= 2 and cnt[r["addr"]] == 1]
    assert strict == []


def test_resolver_reproduces_verified_table(rom):
    if not ASM.exists():
        pytest.skip("disassembly not present in this environment")
    res = M.resolve_ram_symbols(rom, ASM.read_text(errors="replace"))
    for sym, hexaddr in M.VERIFIED_RAM.items():
        assert sym in res, sym
        assert res[sym]["hex"] == hexaddr, (sym, res[sym]["hex"], hexaddr)
        assert res[sym]["distinct"] == 1, (sym, res[sym]["alts"])


def test_no_writes_without_verified_addresses():
    assert M.VERIFIED_RAM == {}
    assert M.plan_writes() == []


def test_unlock_plan_targets_known_symbols():
    # exercised with an explicit (hypothetical) map; real map is empty until verified
    smap = {"Level_select_flag": "0xFF1000", "Debug_cheat_flag": "0xFF1002",
            "Debug_mode_flag": "0xFF1004", "Chaos_emerald_count": "0xFF1006",
            "Super_emerald_count": "0xFF1007"}
    writes = M.plan_writes(smap)
    assert writes, "unlock plan must produce writes"
    names = {w["name"] for w in writes}
    assert {"level_select", "debug_cheat", "chaos_emeralds", "super_emeralds"} <= names
    for w in writes:
        assert M.RAM_START <= w["address"] <= M.RAM_END
        assert 0 <= w["value"] <= 0xFFFF
    # the level-select value must be the exact constant the game itself writes
    ls = [w for w in writes if w["name"] == "level_select"][0]
    assert ls["value"] == 0x0101
    # emerald counts must reach 7 (the value sub_85B0 compares against)
    for w in writes:
        if w["name"].endswith("emeralds"):
            assert w["value"] == 7


def test_category_inventory_covers_request_scope():
    for cat in ("characters", "hidden_characters", "modes", "levels", "stages",
                "costumes", "items", "extras"):
        assert cat in M.CATEGORY_EVIDENCE
        entry = M.CATEGORY_EVIDENCE[cat]
        assert "present" in entry and "not_present" in entry
        assert entry["evidence"], cat
    # Tails must be recorded as not_present for the standalone revision
    assert "Tails" in M.CATEGORY_EVIDENCE["characters"]["not_present"]
