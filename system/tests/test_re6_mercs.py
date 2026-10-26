import struct

from gbox.mercs.titles import re6_x360 as re6


class Mem:
    def __init__(self):
        self.b = {}

    def put(self, a, data):
        for i, v in enumerate(data):
            self.b[a + i] = v

    def rd(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))


class Mesh:
    def __init__(self, open_floor=True):
        self.open = open_floor

    def floor_segment(self, a, b):
        return self.open

    def route(self, a, b, **kw):
        return [b]


def mem_with_player(pos=(0.0, 0.0, 0.0), hp=500):
    m = Mem()
    sp, pl = 0x40001000, 0x40002000
    m.put(re6.S_PLAYER, struct.pack(">I", sp))
    m.put(sp + re6.PL_FIRST, struct.pack(">I", pl))
    m.put(pl + re6.PL_POS, struct.pack(">3f", *pos))
    m.put(pl + re6.PL_LIFE, struct.pack(">2h", hp, 1000))
    return m


def snap(enemies=(), bonuses=(), hp=500):
    return {"player": {"pos": (0.0, 0.0, 0.0), "hp": hp, "hp_max": 1000, "rot": 0.0},
            "enemies": list(enemies), "bonuses": list(bonuses)}


def test_snapshot_reads_verified_fields_and_flags_unknown():
    s = re6.snapshot(mem_with_player((1.0, 2.0, 3.0), 321))
    assert s["player"]["pos"] == (1.0, 2.0, 3.0) and s["player"]["hp"] == 321
    assert "timer" not in s and s["enemies"] == []
    assert re6.snapshot(Mem()) == {}


def test_screen():
    d = re6.RE6X360()
    assert d.screen(None, {}) == "loading"
    assert d.screen(None, snap()) == "playing"
    assert d.screen(None, snap(hp=0)) == "dead"
    assert re6.DRIVER is re6.RE6X360


def test_fires_only_with_proven_sight():
    foe = {"pos": (0.0, 0.0, 800.0), "hp": 100}
    blind = re6.Bot(mesh=None)
    assert "r2" not in blind.tick(snap([foe]))["hold"] and blind.stats["withheld"] == 1
    walled = re6.Bot(mesh=Mesh(open_floor=False))
    assert "r2" not in walled.tick(snap([foe]))["hold"]
    seen = re6.Bot(mesh=Mesh())
    assert {"l2", "r2"} <= seen.tick(snap([foe]))["hold"]
    flagged = re6.Bot(mesh=None)
    assert "r2" in flagged.tick(snap([dict(foe, visible=True)]))["hold"]
    assert "r2" not in flagged.tick(snap([dict(foe, visible=False)]))["hold"]


def test_turns_before_firing_and_ignores_other_floors():
    b = re6.Bot(mesh=Mesh())
    k = b.tick(snap([{"pos": (800.0, 0.0, 0.0), "hp": 5}]))["hold"]
    assert "r2" not in k and "rleft" in k
    up = {"pos": (0.0, 900.0, 300.0), "hp": 5}
    assert "r2" not in re6.Bot(mesh=Mesh()).tick(snap([up]))["hold"]


def test_walks_to_bonus_when_nobody_in_sight():
    b = re6.Bot(mesh=Mesh())
    k = b.tick(snap(bonuses=[{"pos": (0.0, 0.0, 1500.0)}]))["hold"]
    assert "lup" in k and "r2" not in k
    assert re6.Bot(mesh=None).tick(snap(bonuses=[{"pos": (0.0, 0.0, 1500.0)}]))["hold"] == set()


def test_dead_taps_confirm_and_configure_rejects_unknown():
    assert re6.Bot().tick(snap(hp=0)) == {"tap": "a"}
    try:
        re6.configure(bogus=1)
    except KeyError:
        pass
    else:
        raise AssertionError
