"""Focused tests for the Return To Ragol (PSO GC) unlock research gate."""
import os
import re
import sys

# Allow running this file directly (python3 tests/test_pso_ragol_unlock.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gbox import pso_ragol_unlock as gate


def test_owned_identity_is_pinned():
    assert gate.GAME_ID == "5b5792e27be59f59"
    assert gate.SERIAL == "GPOE8P"
    assert re.fullmatch(r"[0-9a-f]{64}", gate.OWNED_EXECUTABLE_SHA256)
    assert gate.OWNED_EXECUTABLE_SIZE == 5236992
    assert gate.OWNED_DISC_FILE_COUNT == 3510


def test_profile_gate_is_not_verified():
    rec = gate.profile_gate()
    assert rec["verified"] is False
    assert rec["status"] == "pending_research"
    assert rec["game_id"] == gate.GAME_ID
    assert rec["owned_executable_sha256"] == gate.OWNED_EXECUTABLE_SHA256


def test_required_evidence_covers_the_full_chain():
    requires = gate.profile_gate()["requires"]
    for item in ("owned_executable_sha256", "save_backup_receipt", "rollback_receipt",
                 "live_boot_and_selection_acceptance", "second_launch_verification"):
        assert item in requires


def test_categories_cover_every_requested_family():
    cats = set(gate.CATEGORIES)
    for wanted in ("items", "modes", "stages", "costumes", "extras"):
        assert wanted in cats


def test_gate_exposes_no_write_targets():
    """A pending gate must never hand a writer an address or an offset."""
    rec = gate.profile_gate()
    assert "0x" not in repr(rec)
    assert rec["writable"] is False
    assert "write_target" not in rec


def test_hypothesis_layout_is_labelled_unverified():
    hyp = gate.HYPOTHESIS_SAVE_LAYOUT
    assert hyp["verified_for_owned_build"] is False
    assert hyp["source_build_sha256"] != gate.OWNED_EXECUTABLE_SHA256


def test_owned_disc_content_is_inventoried():
    content = gate.OWNED_DISC_CONTENT
    assert content["quest_stages"] == 29
    assert content["challenge_packs"] == 9
    assert content["challenge2_packs"] == 5
    assert content["level_table"] == 1


if __name__ == "__main__":
    import sys
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except Exception as exc:
                failures += 1
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
