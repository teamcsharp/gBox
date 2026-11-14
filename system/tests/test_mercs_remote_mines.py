"""The RE6 remote-mine ring (operator 2026-11-11): four bombs ejected in a ring, no throw; the flag detonation.

No live game: a fake native controller (the ring) and a fake helpers module (the rule's decision).
"""
import math
import struct
import threading
import time
import types

import pytest

from gbox.mercs import remote_mines as RM
from gbox.mercs.titles import re6_switch as R
from gbox.mercs.titles import re6_switch_native as N
from gbox.mercs import re6_remote_control as C

TITLE = "01002A000CD48000"


@pytest.fixture(autouse=True)
def receipts(monkeypatch, tmp_path):
    monkeypatch.setattr(C, 'ROOT', tmp_path)


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

    def drop(at, wait_s=0.5, **kw):
        if fails_at is not None and len(ctl.dropped) == fails_at:
            raise N.Uncertain("native remote bomb allocation refused")
        ctl.dropped.append(tuple(at))
        return {"state": "confirmed", "op": "bomb_drop", "unit": 0x300000000 + len(ctl.dropped), "pos": list(at),
                "generation": len(ctl.dropped), "armed": True, "placed_at": 100.0 + len(ctl.dropped) * .01,
                "detonate_deadline_at": 105.0 + len(ctl.dropped) * .01}

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
    assert all(u['armed'] and u['generation'] and u['detonate_deadline_at'] == u['placed_at'] + 5
               for u in receipt['units'])


def test_slow_ring_stops_allocating_to_leave_time_for_escape_and_flag(monkeypatch):
    ctl = ring_controller()
    clock = [0.0]
    original = ctl.drop_bomb
    def slow_drop(*a, **kw):
        out = original(*a, **kw)
        clock[0] += 1.1
        return out
    ctl.drop_bomb = slow_drop
    monkeypatch.setattr(N.time, 'monotonic', lambda: clock[0])
    out = ctl.drop_bomb_ring(15)
    assert out['state'] == 'uncertain' and out['placed'] == 2 and out['requested'] == 15
    assert 'budget' in out['failures'][0]


def test_cancelled_or_different_life_ring_never_allocates():
    ctl = ring_controller()
    out = ctl.drop_bomb_ring(cancelled=lambda: True)
    assert not out['placed'] and not ctl.dropped
    with pytest.raises(N.Unavailable, match='ended player life'):
        ctl.drop_bomb_ring(expected_generation=8)


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
    return {"player": {"ptr": 0x2000, "pos": list(pos), "hp": 900, "generation": 1}, "enemies": [], 'throwables': []}


def settled(step, snapshot, live, now):
    until = time.monotonic() + 2
    while time.monotonic() < until:
        step.observe(snapshot, live, now)
        if not live.get('mine_ring_pending'):
            return
        time.sleep(.001)
    pytest.fail('native ring test worker did not finish')


def test_the_rule_drops_a_ring_then_detonates_the_set_through_the_flag(monkeypatch):
    calls = []

    def ring_now(ad, owner, cancelled, count, radius_cm, allow_existing=None, **kwargs):
        calls.append(("ring", count, radius_cm))
        return {"op": "bomb_ring", "state": "confirmed", "placed": count, "requested": count}

    def detonate_now(ad, snap=None):
        calls.append(("detonate",))
        return {"op": "bomb_detonate", "verified": True, "count": 1, 'detonated': [10]}

    monkeypatch.setattr(C, "emergency_ring_now", ring_now)
    monkeypatch.setattr(N, "bomb_detonate_now", detonate_now)
    step = RM.control(None, {"map_id": TITLE})
    live = stats(remote_mines={"drop_jitter_s": 0, "rings_before_detonate": 4, "detonate_after_s": 75}, ring_flash_at=100.)
    first = step(snap(), live, 100.0, lambda keys: True)
    settled(step, snap(), live, 100.1)
    assert first['pending'] and not first['fired'] and calls[0] == ("ring", 15, 200.0)
    assert live["mine_rings_dropped"] == 1
    # A complete native census, not a request counter, starts the fuse.
    def lying(at):
        s = snap((0, 0, at))
        s['throwables'] = [{'unit': 10, 'generation': 1, 'kind': 'remote', 'pos': [0, 0, 0],
                            'action': 'cWpAction_wp_act_setting'}]
        return s
    held = step(lying(0), live, 101, lambda keys: True)
    assert held['fired'] is False and 'escape first' in held['reason']
    assert not step(lying(400), live, 102, lambda keys: True)['fired']
    done = step(lying(1200), live, 104, lambda keys: pytest.fail('native flag needs no pad release'))
    assert done["op"] == "bomb_detonate" and done["fired"] is True
    assert calls[-1] == ("detonate",)
    assert live["mine_flag_detonations"] == 1
    assert live['mine_deadline_at'] == 106  # old 75-second override cannot delay this bomb


def test_the_rule_never_fires_while_the_drivers_bomb_action_runs(monkeypatch):
    monkeypatch.setattr(N, "bomb_ring_now", lambda *a, **k: pytest.fail("must not drop"))
    monkeypatch.setattr(N, "bomb_detonate_now", lambda *a, **k: pytest.fail("must not detonate"))
    bot = types.SimpleNamespace(bomb_phase="mind", nade=None)
    step = RM.control(None, {"map_id": TITLE}, bot_getter=lambda: bot)
    out = step(snap(), stats(), 100.0, lambda keys: True)
    assert out["fire"] is False and "driver's own bomb" in out["reason"]


def test_the_rule_is_switch_re6_only_and_requires_a_complete_bomb_census(monkeypatch):
    assert RM.control(None, {"map_id": "010018100CD46000"}) is None
    monkeypatch.setattr(N, "bomb_ring_now", lambda *a, **k: pytest.fail("must not drop"))
    step = RM.control(None, {"map_id": TITLE})
    s = snap()
    s['throwables'] = None
    out = step(s, stats(), 100.0, lambda keys: False)
    assert out["fire"] is False and "complete native bomb census" in out["reason"]


def test_a_flashbang_earns_the_fifteen_mine_ring_combo(monkeypatch):
    """Operator 2026-11-11 18:02: a flashbang deployed -> a ring of up to 15 remote mines right away, then detonated."""
    calls = []

    def ring_now(ad, owner, cancelled, count, radius_cm, allow_existing=None, **kwargs):
        calls.append(("ring", count, radius_cm))
        return {"op": "bomb_ring", "state": "confirmed", "placed": count, "requested": count}

    def detonate_now(ad, snap=None):
        calls.append(("detonate",))
        return {"op": "bomb_detonate", "verified": True, "count": 15}

    monkeypatch.setattr(C, "emergency_ring_now", ring_now)
    monkeypatch.setattr(N, "bomb_detonate_now", detonate_now)
    step = RM.control(None, {"map_id": TITLE})
    live = stats(remote_mines={"drop_jitter_s": 0}, ring_flash_at=100.0)
    out = step(snap(), live, 100.3, lambda keys: True)
    settled(step, snap(), live, 100.3)
    assert out['pending'] and not out['fired'] and calls[0] == ("ring", 15, 200.0)
    assert live["mine_flash_combos"] == 1 and live["mine_ring_requests"] == 1
    # the same flash never drops a second combo ring
    assert step(snap(), live, 100.5, lambda keys: True)["fire"] is False
    # and a stale flash earns nothing
    stale = stats(remote_mines={"drop_jitter_s": 0}, ring_flash_at=50.0)
    assert step(snap(), stale, 100.3, lambda keys: True)["op"] != "bomb_ring" or "flash combo" not in str(
        step(snap(), stale, 100.3, lambda keys: True))


def test_the_mine_lane_reports_every_editions_availability():
    """Operator 2026-11-11 18:30: the same features across titles, honestly. The RE6 lane is verified; the RE5/RE4
    editions name why they have none yet (the uWp0a DTI / the RE4 mine system)."""
    rows = {r["game_id"]: r for r in RM.status()}
    assert rows["01002A000CD48000"]["available"] is True and not rows["01002A000CD48000"]["reason"]
    assert rows["010018100CD46000"]["available"] is False and "uWp0a" in rows["010018100CD46000"]["reason"]
    assert rows["010099A00BC1E000"]["available"] is False and "mine system" in rows["010099A00BC1E000"]["reason"]
    assert [r["game_id"] for r in RM.status("01002A000CD48000")] == ["01002A000CD48000"]


def enemy(x, z=0.0):
    return {"ptr": 0x1000 + int(x), "pos": [float(x), 0.0, float(z)], "hp": 500, "hp_max": 500}


def crowd_snap(enemies, pos=(0.0, 0.0, 0.0)):
    s = snap(pos)
    s["enemies"] = list(enemies)
    return s


def test_a_surround_earns_the_massive_mine_ring(monkeypatch):
    """Operator 2026-11-11 18:44: surrounded -> drop massive amounts of remote mines. Four within 400 cm earns the
    15-mine ring on its own 10 s cadence, no flash needed."""
    calls = []

    def ring_now(ad, owner, cancelled, count, radius_cm, allow_existing=None, **kwargs):
        calls.append(("ring", count))
        return {"op": "bomb_ring", "state": "confirmed", "placed": count, "requested": count}

    monkeypatch.setattr(C, "emergency_ring_now", ring_now)
    step = RM.control(None, {"map_id": TITLE})
    crowd = [enemy(100 + i * 50) for i in range(4)]
    live = stats(remote_mines={"drop_jitter_s": 0})
    out = step(crowd_snap(crowd), live, 100.0, lambda keys: True)
    settled(step, crowd_snap(crowd), live, 100.0)
    assert out['pending'] and not out['fired'] and calls[0] == ("ring", 15)
    assert live["mine_surround_rings"] == 1 and live["mine_rings_dropped"] == 1
    # the same surround inside its 10 s cadence does not ring again
    out2 = step(crowd_snap(crowd), live, 105.0, lambda keys: True)
    assert "surrounded" not in (out2.get("reason") or "")
    # a lone enemy is not a surround
    lone = stats(remote_mines={"drop_jitter_s": 0})
    step(crowd_snap([enemy(100)]), lone, 100.0, lambda keys: True)
    assert not lone.get("mine_surround_rings")
