"""RE6 Switch cast-roster planner/build tests (library- and RomFS-dependent ones skip when the assets are absent)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from gbox import re6_switch_cast as R
from gbox import re6_switch_models as S

ROMFS = Path(os.environ.get("GBOX_RE6_SWITCH_ROMFS", r"C:\_tools\gBox\.tmp\re6sw_romfs"))
LIB = Path(os.environ.get("GBOX_CHARACTER_LIBRARY", r"D:\gBox\cache\characters"))
needs_romfs = pytest.mark.skipif(not (ROMFS / "nativeNXx64" / "arc" / "NX").is_dir(),
                                 reason="the extracted RE6 Switch RomFS is not present")


def test_plan_puts_a_distinct_donor_on_every_slot():
    pool = [{"slug": f"donor{i:02d}", "name": f"Donor {i}", "rig": {"skinned": True, "roles": {}}} for i in range(30)]
    slots = [("leon", "Usa"), ("leon", "Asia"), ("chris", "Europe")]
    assignment = R.plan(ROMFS, pool, seed=3, slots=slots)
    assert set(assignment) == set(slots)
    assert len({meta["slug"] for meta in assignment.values()}) == len(slots)


def test_per_character_plan_reuses_one_donor_per_character():
    """A textured build needs one donor per character (its albedo set is shared by its costumes)."""
    pool = [{"slug": f"donor{i:02d}", "name": f"Donor {i}"} for i in range(9)]
    slots = [("leon", "Usa"), ("leon", "Asia"), ("ada", "A")]
    assignment = R.plan(ROMFS, pool, seed=1, slots=slots, per_character=True)
    assert assignment[("leon", "Usa")]["slug"] == assignment[("leon", "Asia")]["slug"]
    assert assignment[("leon", "Usa")]["slug"] != assignment[("ada", "A")]["slug"]


def test_plan_refuses_a_pool_smaller_than_the_slots():
    pool = [{"slug": "one", "name": "One"}]
    with pytest.raises(R.CastError):
        R.plan(ROMFS, pool, slots=[("leon", "Usa"), ("leon", "Asia")])


@pytest.mark.skipif(not LIB.is_dir(), reason="the character library is not present")
def test_donor_pool_only_returns_complete_rigs():
    pool = R.donor_pool(LIB)
    assert len(pool) >= 40
    assert all(len(meta["rig"]["roles"]) >= 18 for meta in pool)
    # two roles cannot share one joint (R.O.B.'s single leg): map_weights needs distinct anchors
    assert all(len(set(meta["rig"]["roles"].values())) == len(meta["rig"]["roles"]) for meta in pool)
    assert any(meta["slug"].endswith("_ssbu") for meta in pool)
    assert any(meta["slug"].endswith("_ssbb") for meta in pool)


@pytest.mark.skipif(not LIB.is_dir(), reason="the character library is not present")
def test_status_reports_an_absent_build(tmp_path):
    class Cfg:
        cache = tmp_path

    out = R.status(Cfg(), "no_such_mod")
    assert out["built"] is False and out["mod"] == "no_such_mod"


@needs_romfs
@pytest.mark.skipif(not LIB.is_dir(), reason="the character library is not present")
def test_the_tool_plans_the_switch_roster():
    from types import SimpleNamespace

    from gbox import re6_tool as T

    ctx = SimpleNamespace(config=SimpleNamespace(cache=Path(r"D:\gBox\cache"),
                                                 data_dir=Path(r"C:\_tools\gBox\system\gbox-data")),
                          server=None, headers={}, progress=lambda _s: None)
    out = T.switch_cast_op(ctx, T.Re6In(op="switch_cast_plan", romfs=str(ROMFS), seed=7))
    assert out["slots"] == len(S.body_arcs(ROMFS))
    assert len({row["donor"] for row in out["assignment"]}) == out["slots"]
    assert out["mercmode"]["default_mods"] == {"re6": R.DEFAULT_NAME}
    subset = T.switch_cast_op(ctx, T.Re6In(op="switch_cast_plan", romfs=str(ROMFS),
                                           slots=["leon/Usa", "ada/A"]))
    assert [row["slot"] for row in subset["assignment"]] == ["ada/A", "leon/Usa"]
