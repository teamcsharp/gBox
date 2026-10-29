"""The RE6 Switch tablet cluster (#5082, cluster 54090060da6cd49c, signature ``round:tablet_misses``): a health tablet
(R) pressed in a crowd right after the gun went down is swallowed by the game -- the tablet count does not fall. The bot
recorded it as a miss, but the retry's gap was measured from the swallowed press, not from the confirmed miss, so the
re-press landed back inside the game's input-dead window and was swallowed too: the bot spun in a loop of misses and took
the crowd hits that followed (14.836 / round, flat, 122 marked rounds).

The one change: in ``Bot._tablet_check``, when a press is confirmed missed, ``tablet_at`` is reset to ``now`` so the
retry's ``TABLET_RETRY_S`` gap is measured from the confirmed miss -- the gun gets a full beat down before the retry the
game will accept.

The live replay endpoint (``GET /api/mercs/damage-clusters/<cluster>/replay``) returns no per-hit fixtures for this
cluster (its ``hits`` is 0, so the example rounds carry no recorded damage situation). The fixture below reconstructs the
documented incident counters from the cluster record: hp 41 / 78 (52.6 %), a five-enemy crowd within ``CROWD_TABLET_R``,
the tablet case at 7, in a ``state 0`` fight -- the exact shape the cluster's example rounds describe.
"""
import json
from pathlib import Path

import pytest

import gbox.mercs.incident_replay as IR
from gbox.mercs.titles import re6_switch as R

FIXTURES = Path(__file__).parent / "fixtures" / "mercs_incidents"
CLUSTER = "54090060da6cd49c"


def fixture(name):
    fx = json.loads((FIXTURES / name).read_text())
    assert fx["event"]["cluster_id"] == CLUSTER
    return fx


@pytest.fixture(autouse=True)
def _fresh_caches():
    for cache in (R._FOUND, R._MISS, R._ACTION_NAMES):
        cache.clear()
    R.TITLE.since = None
    yield


def test_a_swallowed_tablet_press_is_recorded_as_a_miss():
    """The incident: a tablet pressed at 52.6 % health in a five-strong crowd. The game swallows the R -- the count does
    not fall -- so the press must count as an ignored miss, not as a confirmed tablet."""
    fx = fixture("re6_switch_tablet_after_zl.json")
    result = IR.replay(fx, ticks=40)
    bot = result["bot"]
    assert bot.stats["tablet_presses"] >= 1
    assert bot.stats["tablet_misses"] >= 1, "the swallowed press must count as an ignored miss, not a confirmed tablet"
    assert bot.stats["tablets"] == 0, "the count never fell, so no tablet is counted"


def test_the_retry_after_a_miss_waits_from_the_confirmed_miss():
    """The fix: the retry's ``TABLET_RETRY_S`` gap is measured from the confirmed miss (when the count is known not to
    have fallen), not from the swallowed press. With the old code the retry re-pressed on ``TABLET_RETRY_S`` from the
    press -- inside the game's input-dead window -- and was swallowed again. Now the second R lands at least
    ``TABLET_RETRY_S`` after the miss was confirmed, with the gun a full beat down."""
    assert R.TABLET_CONFIRM_S > R.TABLET_RETRY_S, (
        "the miss is confirmed on TABLET_CONFIRM_S, which must outlast the old retry gap or the fix is a no-op")
    fx = fixture("re6_switch_tablet_after_zl.json")
    result = IR.replay(fx, ticks=80)
    bot = result["bot"]
    acts = [t["t"] for t in result["ticks"] if isinstance(t["act"], dict) and t["act"].get("tap") == "r"]
    assert len(acts) >= 2, "the bot must retry the swallowed tablet"
    miss_at = acts[0] + R.TABLET_CONFIRM_S        # when _tablet_check confirms the count did not fall
    gap = acts[1] - miss_at
    assert gap >= R.TABLET_RETRY_S - 1e-6, (
        f"the retry came {gap:.2f} s after the confirmed miss; it must wait the full TABLET_RETRY_S beat, "
        f"not re-press inside the game's input-dead window")
