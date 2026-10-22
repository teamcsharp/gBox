"""Tetris (PSP Minis) unlock gate: revision guard, owned-disc inventory, honest dispatch surface.

The inventory tests read the owned disc read-only from the shared library; they
skip when that library is not mounted on this node.
"""
from pathlib import Path

try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

from gbox import tetris_psp_unlock as T

OWNED_DISC = Path("/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Minis/roms/Tetris (USA).cso")


def _skip(reason):
    if pytest is not None:
        pytest.skip(reason)
    raise RuntimeError("SKIP: " + reason)


def _disc():
    if not OWNED_DISC.is_file():
        _skip(f"owned disc not mounted at {OWNED_DISC}")
    return OWNED_DISC


def test_guard_accepts_the_owned_revision():
    guard = T.disc_guard(_disc())
    assert guard["ok"] is True
    assert guard["actual"] == T.DISC_SHA256
    assert guard["expected"] == T.DISC_SHA256


def test_guard_rejects_any_other_bytes(tmp_path=None):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        fake = Path(d) / "not-tetris.cso"
        fake.write_bytes(b"not the owned revision")
        guard = T.disc_guard(fake)
    assert guard["ok"] is False
    assert guard["actual"] != T.DISC_SHA256


def test_param_sfo_matches_the_owned_revision():
    sfo = T.read_param_sfo(_disc())
    assert sfo["TITLE"] == "Tetris"
    assert sfo["DISC_ID"] == T.DISC_ID
    assert sfo["DISC_VERSION"] == T.DISC_VERSION
    assert sfo["BOOTABLE"] == 1


def test_inventory_lists_the_shipped_modes():
    inv = T.inventory(_disc())
    names = [m["name"] for m in inv["modes"]]
    assert len(names) == 12, names
    for expected in ("CHILL", "FLASH", "FLOOD", "GRAVITY", "LASER", "LEDGES",
                     "MAGNETIC", "ORIGIN", "RADICAL", "SCANNER", "SPLIT", "TREAD"):
        assert expected in names, (expected, names)
    for mode in inv["modes"]:
        assert len(mode["level_sha256"]) == 64
        assert mode["level_bytes"] > 0
        assert mode["background_sha256"] is not None
        assert "EN" in mode["languages"]
        assert mode["lock_state"] == "unknown"


def test_inventory_categories_are_honest():
    inv = T.inventory(_disc())
    for category in T.CATEGORIES:
        row = inv["categories"][category]
        assert row["status"] in ("unlocked", "not_present", "unknown")
        assert "reason" in row
    assert inv["categories"]["modes"]["status"] == "unknown"
    assert not any(r["status"] == "unlocked" for r in inv["categories"].values())


def test_profile_gate_blocks_every_writer():
    gate = T.profile_gate()
    assert gate["verified"] is False
    assert gate["status"] == "pending_research"
    assert gate["owned_executable"]["sha256"] == T.EBOOT_SHA256
    assert "lock_flag_evidence" in gate["requires"]
    assert "live_boot_and_selection_acceptance" in gate["requires"]


def test_dispatch_surface_reports_pending_for_this_exact_game():
    from gbox import game_unlocks
    row = game_unlocks.profile_for({"game_id": T.GAME_ID, "platform": T.PLATFORM})
    assert row["status"] == "pending_research"
    assert row["verified"] is False
    assert row["profile"] is None
    assert set(T.CATEGORIES) <= set(row["scope"])


def test_other_titles_stay_unsupported():
    from gbox import game_unlocks
    row = game_unlocks.profile_for({"game_id": "0" * 16, "platform": T.PLATFORM})
    assert row["status"] == "unsupported"


def test_re_lab_psp_branch_reports_encrypted_eboot(tmp_path):
    import io, struct, pytest
    from gbox import re_lab_tool as rl
    assert rl.PLATFORM_CPU["psp"][1] == "MIPS:LE:32:default"
    from pathlib import Path
    disc = Path("/mnt/gbox/hyperspin/Arcade/collections/Sony PlayStation Minis/roms/Tetris (USA).cso")
    if not disc.exists():
        pytest.skip("owned disc not mounted")
    with pytest.raises(ValueError, match="encrypted ~PSP"):
        rl.extract_from_disc(None, {"platform": "psp"}, disc)
