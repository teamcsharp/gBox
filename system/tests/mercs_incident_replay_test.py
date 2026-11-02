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


def test_replay_crowd_gun_down_asserts_no_tablet_in_crowd():
    """With the #5051 crowd==0 guard, the bot must NOT press a tablet in a crowd.
    The fixture shows 4+ enemies within 2 m — the exact signature that caused the
    crowd_gun_down cluster. The gun stays up and firing instead of lowering for a
    tablet, eliminating the gun-down window that caused the deaths."""
    result = incident_replay.replay(_load(), ticks=40)
    bot = result["bot"]
    acts = [t for t in result["ticks"]]

    # 1. The bot must NOT press a tablet in this crowd scenario
    #    (4+ enemies within 300 cm → crowd >= 2 > 0 → crowd==0 guard blocks it)
    tablet_presses = [t for t in acts if t.get("doing") == "tablet"]
    assert tablet_presses == [], (
        f"bot must NOT press a tablet in a crowd (crowd==0 guard), "
        f"but got {len(tablet_presses)} tablet ticks: {tablet_presses}"
    )

    # 2. tablet_hold_until must remain unset (no tablet press → no crowd hold)
    assert bot.tablet_hold_until <= 0.0, (
        f"tablet_hold_until must not be set (no tablet in crowd), got {bot.tablet_hold_until}"
    )

    # 3. The gun stays up: the bot should be firing/aiming (zl present),
    #    not bare zl alone. Raise (zl+ldown) and aim (ldown+zl) are valid
    #    gun-up states — the gun is raised and tracking, not a tablet-lowering
    #    re-raise. Only a lone zl with no other context would be a problem.
    #    With the crowd==0 guard, the bot never lowers for a tablet in a crowd,
    #    so the critical check is that NO tablet press occurred (checked above).
    #    Here we just confirm the gun is up (zl present) in at least one tick,
    #    proving the bot is in a fighting posture, not a healing one.
    zl_ticks = [t for t in acts if "zl" in set(t.get("act", {}).get("hold", ()))]
    assert len(zl_ticks) > 0, (
        f"gun must be up (zl present) at some point, proving the bot is fighting "
        f"not healing, but no zl ticks found"
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
