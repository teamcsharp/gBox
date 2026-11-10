"""RE4 Switch's camera in RAM (#9386: pG + 0xA8, the per-frame render copy of the camera; re4_switch.camera_state /
decode_camera) and the camera-collapse wall signal (combat.CameraCollapse, re4_switch.CAMERA_COLLAPSE): the camera
pulled in against a wall while the stick walks him is a wall press - the operator's screenshot of Krauser and Leon
pinned with the camera inside a wall."""
import math
import struct

from gbox.mercs.core import combat as C
from gbox.mercs.titles import re4_switch as D


def block(pos=(100.0, 1800.0, -3000.0), target=(0.0, 1500.0, 0.0), fovy=45.0, look=(0.0, 0.0, 1.0), dist=3000.0):
    raw = bytearray(D.CAM_SIZE)

    def put(off, vals):
        struct.pack_into(f"<{len(vals)}f", raw, off - D.CAM_BLOCK, *vals)
    put(D.CAM_POS, pos)
    put(D.CAM_TARGET, target)
    put(D.CAM_FOVY, (fovy,))
    put(D.CAM_LOOK, look)
    put(D.CAM_DIST, (dist,))
    return bytes(raw)


def test_the_camera_block_decodes_at_the_docs_offsets():
    cam = D.decode_camera(block())
    assert cam["pos"] == (100.0, 1800.0, -3000.0) and cam["target"] == (0.0, 1500.0, 0.0) and cam["fovy"] == 45.0
    assert cam["target_dist"] == math.dist((100.0, 1800.0, -3000.0), (0.0, 1500.0, 0.0))
    assert D.CAM_BLOCK == 0xA8 and D.CAM_POS - D.CAM_BLOCK == 0xA4 and D.CAM_FOVY == 0x168
    assert D.decode_camera(block(fovy=0.0)) is None and D.decode_camera(block(pos=(float("nan"), 0, 0))) is None
    assert D.decode_camera(block()[:100]) is None


class Mem:
    """A session: the pG pointer at module + PG_PTR_VAR, the camera block at pG + CAM_BLOCK."""
    BASE, PG = 0x3CA7C04000, 0x3CA8E78338

    def __init__(self, raw):
        self.raw = raw

    def rd(self, a, n):
        if a == self.BASE + D.PG_PTR_VAR:
            return struct.pack("<Q", self.PG)[:n]
        if a == self.PG + D.CAM_BLOCK:
            return self.raw[:n]
        raise OSError("unmapped")


def test_camera_state_follows_the_pg_chain():
    assert D.camera_state(Mem(block()), Mem.BASE)["fovy"] == 45.0
    assert D.camera_state(Mem(block(fovy=500.0)), Mem.BASE) is None, "not a camera there: nothing"


def test_a_collapse_is_the_distance_well_under_its_median_while_he_pushes():
    cc = C.CameraCollapse({}, 0.6, 0.15)
    t = 0.0
    for _ in range(30):                                              # the free camera: 3 m off
        assert not cc.observe(t, 3000.0, True)
        t += 0.05
    assert not cc.observe(t, 1200.0, False), "not walking: no collapse"
    found = [cc.observe(t + 0.05 * k, 1200.0, True) for k in range(1, 8)]
    assert found.count(True) == 1 and cc.stats["camera_collapses"] == 1, "one per spell, after hold_s"
    assert not cc.observe(t + 1.0, 3000.0, True) and cc.median() == 3000.0, "the spell does not drag the median"
    assert [cc.observe(t + 1.0 + 0.05 * k, 1000.0, True) for k in range(1, 6)].count(True) == 1, "a new spell"


def mm(p):
    return tuple(v * D.MM_PER_CM for v in p)


def snap(dist, pos=(0.0, 0.0, 0.0)):
    return {"player": {"pos": mm(pos), "rot": 0.0, "hp": 1000, "ptr": 1}, "enemies": [], "camera_dist_mm": dist}


def test_the_bot_takes_a_collapse_as_a_wall_press_and_turns_away(monkeypatch):
    b = D.Bot(stats={}, director=False)
    t, x = 0.0, 0.0
    for _ in range(40):                                              # walking on (the sweep), the camera 3 m off
        b._wall_core({"pos": mm((0.0, 0.0, x))}, {"hold": {"lup"}}, snap(3000.0, (0.0, 0.0, x)), t)
        b._uc_control_at = t
        t, x = t + 0.05, x + 100.0
    acts = []
    for _ in range(6):                                               # the camera pulled in to 0.9 m
        acts.append(b._wall_core({"pos": mm((0.0, 0.0, x)), "rot": 0.0}, {"hold": {"lup"}}, snap(900.0, (0, 0, x)), t))
        b._uc_control_at = t
        t, x = t + 0.05, x + 100.0
    assert b.stats["camera_collapses"] == 1 and b.stats["camera_dist_mm"] == 900.0 and b.stats["walls_pressed"] == 1
    assert b.doing == "unwall" and acts[-1]["hold"] != {"lup"}, "turned away, not on into it"


def test_the_aims_own_zoom_and_the_rollback_are_no_collapse(monkeypatch):
    b = D.Bot(stats={}, director=False)
    t = 0.0
    for _ in range(40):
        b._wall_core({"pos": mm((0.0, 0.0, t * 2000))}, {"hold": {"lup"}}, snap(3000.0), t)
        b._uc_control_at = t
        t += 0.05
    b._wall_core({"pos": (0.0, 0.0, 0.0)}, {"hold": {D.AIM_BTN}}, snap(900.0), t)      # the gun up: zoomed in
    for k in range(1, 6):                                            # gun down, still zoomed for a moment
        b._wall_core({"pos": mm((0.0, 0.0, 9000.0 + 100 * k)), "rot": 0.0}, {"hold": {"lup"}}, snap(900.0),
                     t + 0.05 * k)
    assert b.stats["camera_collapses"] == 0
    monkeypatch.setattr(D, "CAMERA_COLLAPSE", False)
    r = D.Bot(stats={}, director=False)
    for k in range(60):
        r._wall_core({"pos": mm((0.0, 0.0, k * 100.0))}, {"hold": {"lup"}}, snap(3000.0 if k < 40 else 900.0), k * 0.05)
    assert r.stats.get("camera_collapses", 0) == 0


def test_a_change_of_distance_source_starts_a_median_of_its_own():
    """camera_dist_source: "player" (|Campos - his position|, while it is a camera's) or "target" (the camera's own
    |Campos - Target|, when Campos is not in his frame): a collapse is judged against the same source's median."""
    b = D.Bot(stats={}, director=False)
    for k in range(40):
        s = dict(snap(3000.0, (0.0, 0.0, k * 100.0)), camera_dist_source="target")
        b._wall_core({"pos": mm((0.0, 0.0, k * 100.0))}, {"hold": {"lup"}}, s, k * 0.05)
        b._uc_control_at = k * 0.05
    assert b.stats["camera_dist_source"] == "target"
    for k in range(40, 46):                                          # a player distance, 0.9 m: not a collapse yet
        s = dict(snap(900.0, (0.0, 0.0, k * 100.0)), camera_dist_source="player")
        b._wall_core({"pos": mm((0.0, 0.0, k * 100.0)), "rot": 0.0}, {"hold": {"lup"}}, s, k * 0.05)
        b._uc_control_at = k * 0.05
    assert b.stats["camera_dist_source"] == "player" and b.stats["camera_collapses"] == 0
