"""The RE6 remote-mine ring (operator 2026-11-11): four bombs ejected in a ring, no throw; the flag detonation.

No live game: a fake native controller (the ring) and a fake helpers module (the rule's decision).
"""
import math
import struct
import threading
import types

import pytest

from gbox.mercs import remote_mines as RM
from gbox.mercs.titles import re6_switch as R
from gbox.mercs.titles import re6_switch_native as N

TITLE = "01002A000CD48000"


# ---- the native ring -------------------------------------------------------------------------------------------------

def ring_controller(fails_at=None, position=(100.0, 50.0, -20.0)):
    ctl = N.Controller.__new__(N.Controller)
    ctl.lock = threading.RLock()
    ctl.player = 0x200000000
    ctl.mem, ctl.dropped = {}, []
    put = lambda at, data: ctl.mem.update({at + i: b for i, b in enumerate(data)})   # noqa: E731
    put(ctl.player + R.P_POS, struct.pack("<3f", *position))
    ctl.rd = lambda at, n: bytes(ctl.mem.get(at + i, 0) for i in range(n))
    ctl.ready = lambda: (ctl.player, 7)

    def drop(at, wait_s=0.5):
        if fails_at is not None and len(ctl.dropped) == fails_at:
            raise N.Uncertain("native remote bomb allocation refused")
        ctl.dropped.append(tuple(at))
        return {"state": "confirmed", "op": "bomb_drop", "unit": 0x300000000 + len(ctl.dropped), "pos": list(at)}

    ctl.drop_bomb = drop
    return ctl


def test_drop_bomb_ring_ejects_four_bombs_on_a_ring_around_him():
    ctl = ring_controller()
    receipt = ctl.drop_bomb_ring(4, 200.0)
    assert receipt["state"] == "confirmed" and receipt["placed"] == 4 and receipt["requested"] == 4
    assert len(ctl.dropped) == 4
    for x, y, z in ctl.dropped:
        assert y == pytest.approx(50.0)                       # his floor
        assert math.hypot(x - 100.0, z + 20.0) == pytest.approx(200.0)   # the radius
    # four points evenly spaced: the diagonals, not four on one line
    angles = sorted(round(math.degrees(math.atan2(z + 20.0, x - 100.0))) % 360 for x, _y, z in ctl.dropped)
    assert angles == [45, 135, 225, 315]


def test_a_partial_ring_is_uncertain_and_never_reported_confirmed():
    ctl = ring_controller(fails_at=2)
    receipt = ctl.drop_bomb_ring(4, 200.0)
    assert receipt["state"] == "uncertain" and receipt["placed"] == 2 and len(receipt["failures"]) == 1
    assert len(ctl.dropped) == 2


def test_the_ring_count_and_radius_are_bounded():
    ctl = ring_controller()
    receipt = ctl.drop_bomb_ring(99, 9999)
    assert receipt["requested"] == 16 and receipt["radius_cm"] == 600.0
    assert all(abs(math.hypot(x - 100.0, z + 20.0) - 600.0) < 1e-6 for x, _y, z in ctl.dropped)


# ---- the rule ------------------------------------------------------------------------------------------------------

def stats(**kw):
    out = {"round_evidence_id": "round-1", "screen": "playing"}
    out.update(kw)
    return out


def snap(pos=(0.0, 0.0, 0.0)):
    return {"player": {"ptr": 0x2000, "pos": list(pos), "hp": 900, "generation": 1}, "enemies": []}


def test_the_rule_drops_a_ring_then_detonates_the_set_through_the_flag(monkeypatch):
    calls = []

    def ring_now(ad, count=4, radius_cm=200.0):
        calls.append(("ring", count, radius_cm))
        return {"op": "bomb_ring", "state": "confirmed", "placed": count, "requested": count}

    def detonate_now(ad, snap=None):
        calls.append(("detonate",))
        return {"op": "bomb_detonate", "verified": True, "count": 12}

    monkeypatch.setattr(N, "bomb_ring_now", ring_now)
    monkeypatch.setattr(N, "bomb_detonate_now", detonate_now)
    step = RM.control(None, {"map_id": TITLE})
    live = stats(remote_mines={"drop_jitter_s": 0, "rings_before_detonate": 3})
    first = step(snap(), live, 100.0, lambda keys: True)
    assert first["fired"] is True and calls[0] == ("ring", 4, 200.0)
    assert live["mine_rings_dropped"] == 1 and live["mine_rings_since_detonate"] == 1
    # the next two rings are forced by moving the clock past the stored next-drop
    for at in (130.0, 160.0):
        live["mine_next_drop_at"] = at - 1
        assert step(snap(), live, at, lambda keys: True)["fire"] is True
    assert live["mine_rings_since_detonate"] == 3 and live["mine_bombs_since_detonate"] == 12
    # the player is still on the centre: the flag waits for the distance (operator 2026-11-11 17:50)
    held = step(snap(), live, 160.5, lambda keys: True)
    assert held["fire"] is False and "nearest lying ring" in held["reason"]
    # 400 cm clear of the ring: the third ring makes the set due and the next tick detonates by the flag
    done = step(snap((0.0, 0.0, 400.0)), live, 161.0, lambda keys: True)
    assert done["op"] == "bomb_detonate" and done["fired"] is True
    assert calls[-1] == ("detonate",)
    assert live["mine_rings_since_detonate"] == 0 and live["mine_flag_detonations"] == 1
    assert live["mine_ring_centres"] == []


def test_the_rule_never_fires_while_the_drivers_bomb_action_runs(monkeypatch):
    monkeypatch.setattr(N, "bomb_ring_now", lambda *a, **k: pytest.fail("must not drop"))
    monkeypatch.setattr(N, "bomb_detonate_now", lambda *a, **k: pytest.fail("must not detonate"))
    bot = types.SimpleNamespace(bomb_phase="mind", nade=None)
    step = RM.control(None, {"map_id": TITLE}, bot_getter=lambda: bot)
    out = step(snap(), stats(), 100.0, lambda keys: True)
    assert out["fire"] is False and "driver's own bomb" in out["reason"]


def test_the_rule_is_switch_re6_only_and_honours_a_held_input(monkeypatch):
    assert RM.control(None, {"map_id": "010018100CD46000"}) is None
    monkeypatch.setattr(N, "bomb_ring_now", lambda *a, **k: pytest.fail("must not drop"))
    step = RM.control(None, {"map_id": TITLE})
    out = step(snap(), stats(), 100.0, lambda keys: False)
    assert out["fire"] is False and "keys did not release" in out["reason"]
