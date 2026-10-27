"""Tests for the Super Bust-A-Move (PS2) mode-select lock inventory."""
from __future__ import annotations

import hashlib
import os
import struct

import pytest

from gbox import sbam_modeselect as mod

ELF = os.path.expanduser(
    "~/gBox_alt/gbox-cache/ps2/6cd93f2e36885f31/inventory/SLUS_201.15")


def _elf():
    if not os.path.exists(ELF):
        pytest.skip("owned Super Bust-A-Move executable is not on this host")
    with open(ELF, "rb") as handle:
        return handle.read()


def _word(elf, vaddr):
    return struct.unpack_from("<I", elf, mod.vaddr_to_offset(vaddr))[0]


def _cstr(elf, vaddr):
    off = mod.vaddr_to_offset(vaddr)
    return elf[off:elf.index(b"\x00", off)].decode("latin1")


def test_profile_is_not_verified():
    prof = mod.profile()
    assert prof["verified"] is False
    assert prof["complete_unlock_profile"] is False
    assert prof["game_id"] == mod.GAME_ID
    assert prof["findings"]
    assert prof["unverified_note"]


def test_module_has_no_write_or_launch_api():
    with open(mod.__file__, "r", encoding="utf-8") as handle:
        src = handle.read()
    for token in ("write_memory", "freeze_memory", "launch_game", "mcp__gbox",
                  "poke(", "read_memory"):
        assert token not in src, token


def test_executable_digest_matches():
    assert hashlib.sha256(_elf()).hexdigest() == mod.EXECUTABLE_SHA256


def test_instruction_words_match_executable():
    elf = _elf()
    for row in mod.INSTRUCTIONS:
        assert _word(elf, row["vaddr"]) == row["word"], row


def test_panel_global_load_targets_the_documented_global():
    word = _word(_elf(), 0x001191C4)
    assert (word >> 26) & 0x3F == 0x23          # lw
    assert (word & 0xFFFF) == 0x1640
    assert (0x570000 + (word & 0xFFFF)) == mod.PANEL_GLOBAL_VADDR


def test_branch_target_is_the_narrow_panel():
    pc = 0x001191CC
    word = _word(_elf(), pc)
    assert (word >> 26) & 0x3F == 5             # bne
    offset = word & 0xFFFF
    if offset & 0x8000:
        offset -= 0x10000
    assert pc + 4 + offset * 4 == 0x00119248


def test_round_lock_gate_branches_to_only_one():
    pc = 0x00119658
    word = _word(_elf(), pc)
    assert (word >> 26) == 0x04                # BEQ
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    assert rs == 2, f"beq should test $v0 (rs=2), got rs={rs}"
    assert rt == 0, f"beq should compare against $zero (rt=0), got rt={rt}"
    offset = word & 0xFFFF
    if offset & 0x8000:
        offset -= 0x10000
    assert pc + 4 + offset * 4 == 0x001196A8, \
        "beq target should be the only-1 branch"


def test_bubble_lock_gate_branches_to_only_one():
    pc = 0x001199E8
    word = _word(_elf(), pc)
    assert (word >> 26) == 0x04                # BEQ
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    assert rs == 2, f"beq should test $v0 (rs=2), got rs={rs}"
    assert rt == 0, f"beq should compare against $zero (rt=0), got rt={rt}"
    offset = word & 0xFFFF
    if offset & 0x8000:
        offset -= 0x10000
    assert pc + 4 + offset * 4 == 0x00119A38, \
        "beq target should be the only-1 branch"


def test_round_and_bubble_lock_site_words():
    elf = _elf()
    # Round lock site
    assert _word(elf, 0x00119678) == 0x3C050056  # lui $a1, 0x56
    assert _word(elf, 0x001196A0) == 0x1000000E  # beqz $v0, ...
    assert _word(elf, 0x001196B8) == 0x3C050056  # lui $a1, 0x56
    assert _word(elf, 0x001196C4) == 0x0C077504  # jal 0x001dd410
    # Bubble lock site
    assert _word(elf, 0x00119A08) == 0x3C050056  # lui $a1, 0x56
    assert _word(elf, 0x00119A30) == 0x1000000E  # beqz $v0, ...
    assert _word(elf, 0x00119A48) == 0x3C050056  # lui $a1, 0x56
    assert _word(elf, 0x00119A54) == 0x0C077504  # jal 0x001dd410


def test_format_strings_match_executable():
    elf = _elf()
    assert _cstr(elf, mod.LOCK_SITE["format_selectable_vaddr"]) == \
        "ZONE %c (A-%c selectable)"
    assert _cstr(elf, mod.LOCK_SITE["format_only_a_vaddr"]) == \
        "ZONE %c (only A selectable)"
    assert _cstr(elf, mod.ROUND_LOCK_SITE["format_selectable_vaddr"]) == \
        "ROUND %d (1-%d selectable)"
    assert _cstr(elf, mod.ROUND_LOCK_SITE["format_only_one_vaddr"]) == \
        "ROUND %d (only 1 selectable)"
    assert _cstr(elf, mod.BUBBLE_LOCK_SITE["format_selectable_vaddr"]) == \
        "BUBBLE %d (1-%d selectable)"
    assert _cstr(elf, mod.BUBBLE_LOCK_SITE["format_only_one_vaddr"]) == \
        "BUBBLE %d (only 1 selectable)"


def test_panel_global_is_zero_on_disk():
    assert _word(_elf(), mod.PANEL_GLOBAL_VADDR) == mod.PANEL_GLOBAL_ON_DISK
    assert mod.PANEL_GLOBAL_ON_DISK == 0


def test_ev_names_present_in_executable():
    elf = _elf()
    for row in mod.EV_NAMES:
        assert _cstr(elf, row["vaddr"]) == row["name"]


# ---- unlock-registry registration (request #2250, next milestone) ----

def test_owned_revision_is_recorded_in_proven_revisions():
    assert mod.EXECUTABLE_SHA256 in mod.PROVEN_REVISIONS
    record = mod.PROVEN_REVISIONS[mod.EXECUTABLE_SHA256]
    assert record["artifact"]
    assert "modes" in record["categories"]


def test_inventory_is_honest_and_complete():
    inv = mod.inventory()
    assert set(inv) == set(mod.CATEGORIES)
    # 21 character cstrings, all pinned and all still unknown
    assert len(inv["characters"]) == len(mod.EV_NAMES)
    for row in inv["characters"]:
        assert row["status"] == "unknown"
        assert "vaddr" in row["evidence"] or "0x" in row["evidence"]
    # the three mode locks are listed, none proven
    modes = {row["name"]: row for row in inv["modes"]}
    for name in ("zone_select", "round_select", "bubble_select"):
        assert name in modes and modes[name]["status"] == "unknown"


def test_profile_carries_evidence_chain_and_patch_plan():
    prof = mod.profile()
    assert prof["verified"] is False
    assert prof["proven_revisions"] == [mod.EXECUTABLE_SHA256]
    assert prof["unknown_counts"]["characters"] == len(mod.EV_NAMES)
    assert prof["unknown_counts"]["modes"] == 3
    plan = prof["patch_plan"]
    assert plan["revision"] == mod.EXECUTABLE_SHA256
    (op, addr, data), = plan["writes"]
    assert op == "w" and addr == mod.PANEL_GLOBAL_VADDR and data == b"\x01\x00\x00\x00"


def test_staged_patch_plan_passes_the_revision_guard():
    errors = mod.validate_write(mod.PATCH_PLAN["writes"], mod.PATCH_PLAN["revision"])
    assert errors == []


def test_write_plan_refused_without_proven_revision():
    errors = mod.validate_write([("w", mod.PANEL_GLOBAL_VADDR, b"\x01")], "0" * 64)
    assert any("binary_session" in e for e in errors)


def test_write_plan_bounds():
    rev = mod.EXECUTABLE_SHA256
    assert mod.validate_write([("w", mod.PANEL_GLOBAL_VADDR, b"\x01\x00\x00\x00")], rev) == []
    assert mod.validate_write([("r", mod.PANEL_GLOBAL_VADDR, b"\x01")], rev)   # unsupported op
    assert mod.validate_write([("w", mod.PANEL_GLOBAL_VADDR, b"")], rev)      # empty write
    assert mod.validate_write([("w", mod.PANEL_GLOBAL_VADDR, b"\x01" * 5)], rev)  # too wide
    assert mod.validate_write([("w", 0x000F_0000, b"\x01")], rev)             # below .text
    assert mod.validate_write([("w", 0x0080_0000, b"\x01")], rev)             # above window


def test_accept_revision_rejects_bad_input():
    import pytest as _p
    with _p.raises(ValueError):
        mod.accept_revision("nope", "art", {})
    with _p.raises(ValueError):
        mod.accept_revision("f" * 64, " ", {})
    with _p.raises(ValueError):
        mod.accept_revision("f" * 64, "art", {"bogus_category": []})
    with _p.raises(ValueError):  # claims need evidence
        mod.accept_revision("f" * 64, "art",
                            {"characters": [{"name": "EV1_KATZE", "status": "unlocked"}]})
    with _p.raises(ValueError):
        mod.accept_revision("f" * 64, "art",
                            {"characters": [{"name": "EV1_KATZE", "status": "maybe"}]})


def test_accept_revision_records_and_dedupes_names():
    out = mod.accept_revision("f" * 64, "art-42", {
        "characters": [{"name": "EV1_KATZE", "status": "not_present",
                        "evidence": "rea:roster_scan"}]})
    assert out["verified"] is False and out["recorded"] == "f" * 64
    inv = mod.inventory()
    assert len([r for r in inv["characters"] if r["name"] == "EV1_KATZE"]) == 1
    assert [r for r in inv["characters"] if r["name"] == "EV1_KATZE"][0]["status"] == "not_present"
    # restore
    mod.PROVEN_REVISIONS.pop("f" * 64, None)
    mod.INVENTORY["characters"] = [
        {"name": r["name"], "status": "unknown",
         "evidence": r["evidence"]} for r in
        [mod.inventory()["characters"][i] for i in range(21)]]


def test_game_unlocks_registration_for_sbam():
    from types import SimpleNamespace
    from gbox import game_unlocks as G
    game = {"game_id": mod.GAME_ID, "platform": "ps2"}
    result = G.pre_launch(game, SimpleNamespace())
    assert result["applied"] is False
    assert result["state"] == "research_pending"
    assert result["proven_revisions"] == [mod.EXECUTABLE_SHA256]
    assert result["patch_plan"]["revision"] == mod.EXECUTABLE_SHA256
    # launch plan must not produce any job for an unverified profile
    worker = {"id": "w" * 16, "name": "JAYBUILTFINALE"}
    plan = G.launch_plan(game, worker, enable_unlock=True, allow_save_upgrade=True)
    assert plan["status"] == "unsupported_unlock" and plan["jobs"] == [] and plan["executed"] is False
    # profile_for stays honest: never verified, no writer scope
    prof = G.profile_for(game)
    assert prof["verified"] is False and prof["status"] == "pending_research"


def test_sbam_gate_cannot_be_bypassed_by_other_platform():
    from gbox import game_unlocks as G
    assert G.profile_for({"game_id": mod.GAME_ID, "platform": "psp"})["verified"] is False
    assert G.profile_for({"game_id": "6" * 16, "platform": "ps2"})["verified"] is False
