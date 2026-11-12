"""Checkpoint G4: the RE4 barrage's title knobs, its PiP rows, and the shared rule's step (offline)."""
from gbox.mercs import bot_logic as BL
from gbox.mercs import grenade_ring as RULE
from gbox.mercs.titles import re4_switch as R4


def test_the_re4_barrage_is_built_but_off_until_live_receipts():
    assert R4.SCATTER is False and R4.SCATTER_EVERY_S == 12.0 and R4.SCATTER_N == 8
    assert R4.SCATTER_FLASH_ONLY is False                 # flash and hand are both built: the cap narrows, not refuses
    assert R4.scatter_kinds() == ("flash", "hand")
    assert R4.RING is True and R4.RING_KIND == "launcher"   # the 360 launcher ring is live (operator 2026-11-11)


def test_the_shared_rule_offers_re4_its_step():
    assert "010099A00BC1E000" in RULE.SCATTER_TITLES
    step = RULE.control(None, {"map_id": "010099A00BC1E000", "menus": "gbox.mercs.titles.re4_switch"})
    assert callable(step)
    assert RULE.control(None, {"map_id": "BLUS30491"}) is None       # no PS3 barrage: the rule is Switch work


def test_scatter_policy_reads_re4s_knobs_and_kinds():
    policy = RULE.scatter_policy(R4)
    assert policy["enabled"] is False and policy["cooldown_s"] == 12.0 and policy["count"] == 8
    assert policy["kinds"] == ("flash", "hand")
    assert "flash_only" not in policy


def test_the_pip_rows_carry_the_three_scatter_knobs(tmp_path):
    view = BL.status("re4", path=tmp_path / "bot-logic.json")
    names = {row["name"] for row in view["knobs"]}
    assert {"SCATTER", "SCATTER_EVERY_S", "SCATTER_N"} <= names
