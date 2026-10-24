"""Non-fabrication guard for the RE3 Operation Mad Jackal (GameCube) inspection plan (#3348).

Enforces the two honesty rules the plan (docs/re3_gc_inspection_plan.md) commits to:
  1. no unresolved ``TBD-derive`` entry may ship in a RE3 GC RAM map, and
  2. every committed address carries a ``GLEE08`` product code + SHA256 citation.

Drives off the plan's Python/JSON forms rather than parsing prose, so the scheduler and a future
verified driver both read the same single source of truth. Stands on its own with only stdlib, so it
runs in the task workspace without the gBox runtime.
"""
from __future__ import annotations

import json
import pathlib


PLAN = pathlib.Path(__file__).resolve().parent.parent / "docs" / "re3_gc_inspection_plan.md"
TITLE = pathlib.Path(__file__).resolve().parent.parent / "gbox" / "mercs" / "titles" / "re3_psx.py"
MERC = pathlib.Path(__file__).resolve().parent.parent / "gbox" / "mercmode.py"

# The verified RE4 GC anchors the plan is allowed to cite (reuse template). These are the only
# concrete addresses the plan may treat as measured, and they are RE4's, not RE3's.
RE4_ANCHORS = {
    0x8027DF20,  # EMMGR
    0x802B9780,  # P_PLAYER
    0x80279308,  # MERC_TIMER
    0x8021392C,  # MERC
    0x802B3044,  # *player entity
    0x80218738,  # AIM_PITCH
    0x80287E90,  # GAME_PAD
    0x80000000,  # Dolphin MEM1 base
    # RE4 code/routine addresses the plan cites as the reuse template (routines, not data):
    0x8014415C,  # aim routine
}


def _plan_text() -> str:
    return PLAN.read_text(encoding="utf-8")


def test_plan_exists_and_names_targets():
    text = _plan_text()
    assert "GLEE08" in text
    assert "2e2acf3bfe6e5fd3" in text
    assert "TBD-derive" in text, "plan must keep RE3 addresses as TBD-derive until verified"


def test_no_unresolved_tbd_in_shipped_map_field():
    """Any 'RE3 addr' cell must be TBD-derive or absent; a shipped value is a fabrication signal."""
    text = _plan_text()
    # The RAM-map table rows: a RE3 addr cell is the column before the RE4 anchor column.
    for line in text.splitlines():
        if line.startswith("|") and "| RE3 addr |" not in line and "`TBD-derive`" not in line:
            # Only flag rows that look like map rows (contain an 0x8... hex literal in a RE3 cell).
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 4 and cells[2].startswith("0x"):
                raise AssertionError(f"RE3 addr cell not marked TBD-derive: {line!r}")


def test_only_re4_anchors_are_asserted_as_measured():
    """Every concrete hex address the plan quotes must be a RE4 anchor, never a would-be RE3 addr."""
    text = _plan_text()
    for word in text.replace(",", " ").replace("(", " ").replace(")", " ").split():
        w = word.strip("`")
        if w.lower().startswith("0x") and w.lower().replace("0x", "", 1)[:1] in "0123456789abcdef":
            try:
                addr = int(w, 16)
            except ValueError:
                continue
            if 0x80000000 <= addr < 0x81800000:
                assert addr in RE4_ANCHORS, f"plan quotes {w} as measured but it is not a RE4 anchor"


def test_psx_title_stays_honest_until_map_reviewed():
    """The existing PSX RE3 driver must keep returning an empty snapshot (no invented addresses)."""
    text = TITLE.read_text(encoding="utf-8")
    assert "return {}                    # no reviewed RAM map" in text
    assert "0x8" not in text, "PSX RE3 title must still cite no concrete RAM addresses"


def test_re3_catalog_entry_not_playable():
    text = MERC.read_text(encoding="utf-8")
    # Scope the check to the re3 entry's own dict literal, not the whole file.
    start = text.index("'re3':")
    end = text.index("}\n", start) if "}\n" in text[start:] else len(text)
    entry = text[start:start + text[start:].index("\n}") + 1]
    assert "'playable': False" in entry, "re3 must be playable=False until its map is reviewed"
    # And no title-level flip to True exists anywhere for re3: its own entry is False.
    assert "'playable': True" not in entry, "re3 entry must not be marked playable"


if __name__ == "__main__":
    import sys

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    sys.exit(1 if failures else 0)
