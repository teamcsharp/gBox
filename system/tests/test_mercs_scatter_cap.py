"""Checkpoint D: RE5's scatter barrage on the one flash clock (FLASH_MIN_GAP_S), and back on.

Synthetic rule tests plus the native controllers' narrowed draw. No game: a fake title module carries the constants,
a fake controller records the barrage, and `stats["native_flash_confirmed_at"]` is the shared clock the bot's own
rules read (`re5_switch._flashed_lately`).
"""
import math
import random
import time

import pytest

from gbox.mercs import grenade_ring as GR
from gbox.mercs.titles import re5_switch as R5
from gbox.mercs.titles import re5_switch_native as N5
from gbox.mercs.titles import re6_switch_native as N6


class RE5Title:
    SCATTER, SCATTER_EVERY_S, SCATTER_N = True, 12.0, 8
    FLASH_MIN_GAP_S = 60.0
    SCATTER_FLASH_ONLY = True

    @staticmethod
    def scatter_kinds():
        return ("flash",)


class MixedTitle(RE5Title):
    SCATTER_FLASH_ONLY = False

    @staticmethod
    def scatter_kinds():
        return ("flash", "hand")


def ring(n=4, r=300.0):
    return [{"ptr": 0x1000 + i, "pos": [r * math.sin(i * 1.5), 0.0, r * math.cos(i * 1.5)],
             "hp": 500, "hp_max": 500, "class": f"uEm{1000 + i}"} for i in range(n)]


def snap(enemies, kills=0):
    return {"player": {"ptr": 0x2000, "pos": [0.0, 0.0, 0.0], "hp": 900, "generation": 1},
            "enemies": list(enemies), "kills": kills, "screen": "playing"}


def stats(**kw):
    out = {"round_evidence_id": "round-d", "screen": "playing"}
    out.update(kw)
    return out


NOW = 10_000.0


# ---- the rule ---------------------------------------------------------------------------------------------------------

def test_re5_is_on_and_flash_only_under_its_own_clock():
    assert R5.SCATTER is True
    policy = GR.scatter_policy(R5)
    assert policy["enabled"] is True
    assert policy["flash_only"] is True
    assert policy["flash_gap_s"] == R5.FLASH_MIN_GAP_S == 60.0
    assert policy["kinds"] == ("flash",) == R5.scatter_kinds()
    # The gate flag is only honest while the flash is the sole verified kind: C must revisit both together.
    assert R5.SCATTER_FLASH_ONLY == (R5.scatter_kinds() == ("flash",))


def test_a_closed_flash_clock_refuses_the_all_flash_barrage():
    st = stats(native_flash_confirmed_at=time.time() - 10.0)
    out = GR.decide_scatter(snap(ring()), st, NOW, GR.scatter_policy(RE5Title()), title="010018100CD46000")
    assert out["fire"] is False
    assert "FLASH_MIN_GAP_S" in out["reason"] and "one every 60 s" in out["reason"]
    assert st["flash_gap_skips"] == 1


def test_an_open_clock_fires_and_stamps_the_shared_clock():
    st = stats(native_flash_confirmed_at=time.time() - 120.0)
    title = RE5Title()
    policy = GR.scatter_policy(title)
    out = GR.decide_scatter(snap(ring()), st, NOW, policy, title="010018100CD46000")
    assert out["fire"] is True and out["flash"] is True
    before = st["native_flash_confirmed_at"]

    class Ctl:
        def grenade_scatter(self, kind, **kw):
            return {"state": "confirmed", "detonated": kw.get("count"), "kinds": ["flash"]}
    receipt = GR.fire_scatter(None, out, st, NOW, ring=Ctl())
    assert receipt["state"] == "confirmed"
    assert st["native_flash_confirmed_at"] > before
    assert st["scatters_fired"] == 1 and st["flash_paths"] == {"scatter": 1}
    # the title's own flash rule reads that clock: one flash a minute from any source
    drv = R5.Bot.__new__(R5.Bot)
    drv.stats = st
    assert drv._flashed_lately(NOW) is True


def test_a_mixed_barrage_leaves_the_flash_out_inside_the_gap():
    st = stats(native_flash_confirmed_at=time.time() - 5.0)
    title = MixedTitle()
    out = GR.decide_scatter(snap(ring()), st, NOW, GR.scatter_policy(title), title="010018100CD46000")
    assert out["fire"] is True and out["narrowed"] is True
    assert out["kinds"] == ["hand"] and "flash" not in out["kinds"]
    assert "FLASH_MIN_GAP_S" in out["flash_held"]
    assert out.get("flash") is not True
    seen = {}

    class Ctl:
        def grenade_scatter(self, kind, **kw):
            seen.update(kind=kind, **kw)
            return {"state": "confirmed", "detonated": kw.get("count"), "kinds": ["hand"]}
    before = st.get("native_flash_confirmed_at")
    GR.fire_scatter(None, out, st, NOW, ring=Ctl())
    assert seen["kind"] == "random" and seen["kinds"] == ("hand",)
    assert st.get("native_flash_confirmed_at") == before          # no flash round, so no new stamp
    assert st["scatters_fired"] == 1


def test_an_open_clock_keeps_the_full_mixed_draw():
    st = stats(native_flash_confirmed_at=time.time() - 300.0)
    out = GR.decide_scatter(snap(ring()), st, NOW, GR.scatter_policy(MixedTitle()), title="010018100CD46000")
    assert out["fire"] is True and out["kinds"] == ["flash", "hand"] and not out.get("narrowed")


# ---- the native controllers' narrowed draw ----------------------------------------------------------------------------

def test_the_re5_controller_draws_only_the_narrowed_kinds():
    from test_re5_class_pair import ring_controller
    ctl = ring_controller()
    result = ctl.grenade_scatter("random", count=3, toward=[(2000.0, -2000.0)], kinds=("flash",),
                                 rng=random.Random(4))
    assert result["state"] == "confirmed" and result["kinds"] == ["flash"] and result["detonated"] == 3


@pytest.mark.parametrize("kinds,match", [(("nuke",), "cannot draw"), ((), "cannot draw")])
def test_the_re5_controller_refuses_a_draw_it_cannot_make(kinds, match):
    from test_re5_class_pair import ring_controller
    ctl = ring_controller()
    with pytest.raises(N5.Unavailable, match=match):
        ctl.grenade_scatter("random", kinds=kinds)
    assert ctl.calls == []


def test_narrowing_an_explicit_kind_is_refused():
    from test_re5_class_pair import ring_controller
    ctl = ring_controller()
    with pytest.raises(N5.Unavailable, match="cannot also narrow"):
        ctl.grenade_scatter("flash", kinds=("flash",))
    assert ctl.calls == []


def test_the_re6_controller_draws_only_the_narrowed_kinds(monkeypatch):
    from tests.test_re6_class_images import class_controller
    monkeypatch.setattr(N6.R, "inventory_items", lambda m, p: {0x115})
    monkeypatch.setattr(N6.R, "unit_action", lambda m, unit: "cWpAction_wp_act_throw")
    ctl = class_controller()
    out = ctl.grenade_scatter("random", count=2, toward=[(1500.0, -2000.0)], kinds=("flash",))
    assert out["state"] == "confirmed" and out["kinds"] == ["flash"] and out["detonated"] == 2
