from gbox.mercs.navcommon import PortalMemory, StuckDetector, bonus_priority, height_cost, sight_gate


def test_stuck_when_moving_without_ground():
    s = StuckDetector(window_s=1.0, min_move=80)
    hits = [s.update(t * 0.25, 10.0, 10.0) for t in range(8)]
    assert True in hits and s.count >= 1


def test_not_stuck_when_progressing_or_turning():
    s = StuckDetector(window_s=1.0, min_move=80)
    assert not any(s.update(t * 0.25, t * 50.0, 0.0) for t in range(12))
    assert not any(s.update(t * 0.25, 0.0, 0.0, moving=False) for t in range(12))


def test_portals_remembered_per_stage_and_merged():
    m = PortalMemory()
    assert m.remember("a", "door", (0, 0, 0))
    assert not m.remember("a", "door", (10, 0, 5))
    assert m.remember("a", "ladder", (0, 0, 0))
    assert m.remember("b", "door", (500, 0, 0))
    assert len(m.portals("a")) == 2 and len(m.portals("b")) == 1
    assert m.nearest("a", (1, 0, 1), "ladder")[0] == "ladder"
    m.forget("a")
    assert m.portals("a") == []


def test_height_aware_cost_and_priority():
    assert height_cost((0, 0, 0), (100, 0, 0)) == 100
    assert height_cost((0, 0, 0), (100, 400, 0)) > 100 + 400
    near_up = {"kind": "score", "pos": (50, 0, 0)}
    far_time = {"kind": "time", "pos": (300, 0, 0)}
    assert bonus_priority([near_up, far_time], (0, 0, 0))[0] is far_time
    assert bonus_priority([near_up, far_time], (0, 0, 0), s_rank=False, time_left_s=300)[0] is near_up
    up = {"kind": "score", "pos": (60, 600, 0)}
    assert bonus_priority([up, {"kind": "score", "pos": (200, 0, 0)}], (0, 0, 0), s_rank=False)[0]["pos"][1] == 0


def test_sight_gate():
    assert sight_gate("on", 0) == "fire"
    assert sight_gate("wall", 0.1) == "wait"
    assert sight_gate("short", 0.5) == "pursue"
    assert sight_gate("none", 0) == "wait"
