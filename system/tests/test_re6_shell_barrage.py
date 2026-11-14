"""The research shell barrage behind the ring chooser's launcher kinds (the operator's 360 nitrogen ring)."""
import math

import pytest

from gbox.mercs.titles import re6_switch_shell_probe as P
from gbox.mercs.native.re6_061d2a06 import shell_probe as S
from test_re6_shell_probe_receipts import Memory


@pytest.fixture
def ring(monkeypatch):
    m = Memory()
    monkeypatch.setattr(P, "_install_images", lambda _: None)
    monkeypatch.setattr(P.R, "inventory_guns", lambda *_: {0x112: 0})
    monkeypatch.setattr(P.R, "owned_throwables", lambda *_: [])
    clock = iter(i * .02 for i in range(10000))
    monkeypatch.setattr(P.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(P.time, "sleep", lambda _: None)
    return m


def test_a_shell_barrage_spawns_and_arms_a_ring_around_the_player(ring):
    ring.put(ring.action + 0x28, 'B', 1)
    out = P.barrage(ring, count=8, radius_cm=700., timeout_s=.05)
    assert out["op"] == "shell_barrage" and out["requested"] == 8
    assert out["spawned"] == 8 and out["armed"] == 8
    assert out["verified"] is False and out["state"] == "uncertain"
    assert out["detonated"] == 0                      # arming is never emission evidence
    spawns = [c for c in ring.calls if c[0] == S.SPAWN[0]]
    arms = [c for c in ring.calls if c[0] == S.ARM[0]]
    assert len(spawns) == 8 and len(arms) == 8
    for row in out["ring"]:
        x, y, z = row["point"]
        assert abs(math.hypot(x, z) - 700.) < 1.0 and y == 0.
    angles = {round(math.atan2(row["point"][2], row["point"][0]) % (2 * math.pi), 3) for row in out["ring"]}
    assert len(angles) == 8                            # evenly spaced, one shell per direction
    assert "unverified" in out["reason"]


def test_a_shell_barrage_is_never_replayed_this_life(ring):
    P.barrage(ring, count=2, radius_cm=700., timeout_s=.05)
    with pytest.raises(P.Unavailable, match="not replayed"):
        P.barrage(ring, count=2, radius_cm=700., timeout_s=.05)


def test_the_shell_barrage_needs_the_launcher(ring, monkeypatch):
    monkeypatch.setattr(P.R, "inventory_guns", lambda *_: {})
    with pytest.raises(P.Unavailable, match="launcher"):
        P.barrage(ring, count=2, radius_cm=700.)
    assert not ring.calls and not ring.writes


@pytest.mark.parametrize("radius", [600., 0., 3000., float("nan")])
def test_an_unsafe_ring_radius_refuses_before_any_native_call(ring, radius):
    with pytest.raises(P.Unavailable):
        P.barrage(ring, count=2, radius_cm=radius)
    assert not ring.calls and not ring.writes


def test_a_cancelled_barrage_never_spawns(ring):
    with pytest.raises(P.Unavailable, match="cancelled"):
        P.barrage(ring, count=8, radius_cm=700., cancelled=lambda: True)
    assert not ring.calls and not ring.writes


def test_the_barrage_waits_for_each_arm_return_and_reports_zero_when_refused(ring):
    ring.put(ring.action + 0x28, 'B', 1)
    def call(off, *args, **kwargs):
        ring.calls.append((off, args))
        if off == S.SPAWN[0]:
            ring.put(ring.heap + P.PACKET_OFFSET + 16, "QI", ring.unit, 2)
            return ring.unit
        return 0                                       # the arm refuses every shell
    ring.call = call
    out = P.barrage(ring, count=3, radius_cm=700., timeout_s=.05)
    assert out["spawned"] == 3 and out["armed"] == 0 and out["detonated"] == 0
    assert out["state"] == "uncertain" and "unverified" in out["reason"]


def test_a_barrage_reports_the_nearby_ice_reactions_it_observed(ring, monkeypatch):
    # The ring's evidence rule is the probe's: a NEW DmgIce/DeadIce transition with stable identity after the shells
    # are spawned and armed. The baseline is read before the spawn so an already-iced enemy never counts.
    ring.put(ring.action + 0x28, "B", 1)
    baseline = [{"unit": 7, "generation": 1, "vtable": 2, "action": "cEm1000ActWait", "hp": 500}]
    monkeypatch.setattr(P, "nearby_targets", lambda ctl, point, **kw: list(baseline))
    monkeypatch.setattr(P, "ice_changes", lambda ctl, before: [
        {"unit": 7, "generation": 1, "before": "cEm1000ActWait", "after": "cEm1000ActDmgIce",
         "hp_before": 500, "hp_after": 125}])
    out = P.barrage(ring, count=2, radius_cm=700., timeout_s=.05)
    assert out["spawned"] == out["armed"] == 2
    assert out["ice_observed"] == 1
    assert out["ice_observations"][0]["after"] == "cEm1000ActDmgIce"
    assert out["targets_before"][0]["unit"] == 7
