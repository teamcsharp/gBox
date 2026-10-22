"""Focused tests for the Prince of Persia: Warrior Within (GameCube) unlock gate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gbox import popww_unlock
from gbox.game_unlocks import profile_for


def test_pins_the_exact_owned_revision():
    assert popww_unlock.GAME_ID == "9fc973656e2fd05d"
    assert popww_unlock.PLATFORM == "gamecube"
    assert popww_unlock.DISC_ID == "G2OE41"
    assert popww_unlock.OWNED_SOURCE_SIZE == 1303782157
    for digest in (popww_unlock.OWNED_SOURCE_SHA256, popww_unlock.MAIN_DOL_SHA256,
                   popww_unlock.PRINCE_BF_SHA256):
        assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_revision_guard_accepts_only_the_pinned_build():
    good = popww_unlock.verify_revision({
        "source_sha256": popww_unlock.OWNED_SOURCE_SHA256,
        "main_dol_sha256": popww_unlock.MAIN_DOL_SHA256,
        "prince_bf_sha256": popww_unlock.PRINCE_BF_SHA256})
    assert good["ok"] is True
    bad = popww_unlock.verify_revision({"source_sha256": "0" * 64})
    assert bad["ok"] is False
    assert bad["checks"]["source_sha256"]["match"] is False


def test_inventory_covers_every_requested_category_with_evidence():
    inv = popww_unlock.inventory()
    assert set(inv) == set(popww_unlock.CATEGORIES)
    for category, entries in inv.items():
        assert entries, category
        for entry in entries:
            assert entry["state"] in ("unlocked", "not_present", "unknown"), entry
            assert entry["evidence"], entry


def test_gate_exposes_no_write_target():
    source = Path(popww_unlock.__file__).read_text(encoding="utf-8")
    for forbidden in ("write_memory", "memset", "patch_bytes", "0x8000"):
        assert forbidden not in source
    assert popww_unlock.profile_gate()["verified"] is False


def test_profile_for_reports_pending_research_for_this_title():
    profile = profile_for({"game_id": popww_unlock.GAME_ID, "platform": "gamecube"})
    assert profile["verified"] is False
    assert profile["status"] == "pending_research"
    assert profile["scope"] == list(popww_unlock.CATEGORIES)
    assert profile["disc_id"] == "G2OE41"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS " + name)
            except AssertionError as exc:
                failures += 1
                print("FAIL " + name + ": " + str(exc))
    print(("FAILED" if failures else "OK") + " failures=" + str(failures))
    raise SystemExit(1 if failures else 0)
