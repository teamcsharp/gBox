"""Replay test for the crowd_gun_down incident (cluster b294c62b554c77fd).

Drives the RE6 switch bot through the recorded incident fixture
tests/fixtures/mercs_incidents/re6_switch_crowd_gun_down.json via
gbox.mercs.incident_replay.replay() and asserts that the bot's decision
after the tablet press is crowd_hold (gun down, backing out) — not a
re-raise into the flanking cluster.
"""
import json
from pathlib import Path

import pytest

from gbox.mercs import incident_replay

FIXTURE = Path(__file__).parent / "fixtures" / "mercs_incidents" / "re6_switch_crowd_gun_down.json"


def _load():
    return json.loads(FIXTURE.read_text())


def test_replay_crowd_gun_down_asserts_crowd_hold():
    """After the tablet press the bot must hold the gun down (crowd_hold / cc_backouts),
    not re-raise into the flanking cluster. The fixture shows 4+ enemies within 2 m
    with the camera pointing away — the exact signature that caused the cluster."""
    result = incident_replay.replay(_load(), ticks=40)
    bot = result["bot"]
    acts = [t for t in result["ticks"]]

    # 1. The tablet was pressed (health 488/900, 4+ within 300 cm)
    assert any(t.get("doing") == "tablet" for t in acts), "bot must press a tablet"

    # 2. tablet_hold_until must be set: the gun-down hold fires when
    #    sum(1 for e in live if flat(e) <= CC_CROWD_R) >= CC_BACK_N
    #    CC_CROWD_R = 400.0, CC_BACK_N = 3; the fixture has 6 enemies at
    #    72-228 cm, so the hold must fire.
    assert bot.tablet_hold_until > 0.0, (
        f"tablet_hold_until must be set by the crowd-tablet guard, got {bot.tablet_hold_until}"
    )

    # 3. cc_backouts must have incremented: the crowd_hold decision path
    #    (line ~2814) fires when now < tablet_hold_until.
    assert bot.stats.get("cc_backouts", 0) > 0, (
        f"cc_backouts must be > 0 (gun held down during crowd), got {bot.stats.get('cc_backouts')}"
    )

    # 4. No tick after the tablet press may show a bare zl (gun raised alone).
    #    Quick-shot holds are (zl, zr) — allowed; bare zl is a re-raise.
    tablet_ticks = [i for i, t in enumerate(acts) if t.get("doing") == "tablet"]
    after_tablet = acts[tablet_ticks[0] + 1:] if tablet_ticks else []
    bare_zl = [
        t for t in after_tablet
        if "zl" in set(t.get("act", {}).get("hold", ()))
        and set(t.get("act", {}).get("hold", ())) != {"zl", "zr"}
        and set(t.get("act", {}).get("hold", ())) != {"ldown", "zl", "zr"}
    ]
    assert bare_zl == [], (
        f"gun must stay down after tablet in crowd, got bare zl: {bare_zl}"
    )


def test_replay_fixture_matches_cluster_fields():
    """Sanity: the fixture is the correct incident (crowd_gun_down, 4+ within 2 m)."""
    fx = _load()
    cluster = fx["cluster"]
    assert cluster["id"] == "b294c62b554c77fd"
    assert cluster["signature"] == "crowd_gun_down"
    assert fx["hp_max"] == 900
    assert fx["hp_before"] >= 1
    # At least 4 enemies in the snapshot within 200 cm (2 m) of the player
    import math
    enemies = (fx.get("snapshot") or {}).get("enemies") or []
    ppos = (fx.get("snapshot") or {}).get("player", {}).get("pos") or [0.0, 0.0, 0.0]
    within_2m = [
        e for e in enemies
        if (e.get("hp") or 0) > 0
        and math.hypot(
            (e.get("pos") or [0, 0, 0])[0] - ppos[0],
            (e.get("pos") or [0, 0, 0])[2] - ppos[2],
        ) <= 200.0
    ]
    assert len(within_2m) >= 4, (
        f"fixture must show 4+ enemies within 2 m of the player, got {len(within_2m)}: "
        f"{[round(math.hypot((e.get('pos') or [0,0,0])[0]-ppos[0], (e.get('pos') or [0,0,0])[2]-ppos[2])) for e in within_2m]}"
    )
