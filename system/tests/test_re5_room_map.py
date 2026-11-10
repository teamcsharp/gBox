"""The RE5 Switch stage map (#9360, checked: gbox.re5_switch_room_map; read by gbox.mercs.titles.re5_room_map through
gbox.mercs.core.room_map) and the bot's use of it (re5_switch.ROOM_MAP): the left stick's way probed on the
collision, refused toward a wall or off the floor (the route's way, else the nearest clear stick direction, never a
turn on the spot), the never-stand step along it, no shot through its walls.

Synthetic stages first (the game's cm; the tables in mm), then the real tables against #9360's JSON and the bot's own
live route samples (gbox-data/mercs/round_maps by navigation signature, 2026-11-10)."""
import json
import math
from pathlib import Path

import pytest

from gbox.mercs import ss_ledger
from gbox.mercs.core import room_map as RM
from gbox.mercs.titles import re5_room_map as R
from gbox.mercs.titles import re5_switch as B
from gbox.mercs.titles import re5_switch_wall as W

DOC = Path(__file__).resolve().parents[1] / "docs" / "research" / "re5-switch-mercs-collision.json"


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    monkeypatch.setattr(B, "PS3_BRAIN", False)
    monkeypatch.setattr(B, "HEAL_ENABLED", False)
    monkeypatch.setattr(B, "MINES", False)
    monkeypatch.setattr(B, "CALM", False)


def stage(walls_cm, void=()):
    """A 10 m x 10 m floor round the origin (mm table: 40 x 40 cells of 250 mm); walls given in cm."""
    rows = [[0 if (r, c) in void else 1 for c in range(40)] for r in range(40)]
    walls = [[w[0] * 10, w[1] * 10, w[2] * 10, w[3] * 10, w[4] * 10, w[5] * 10, 0] for w in walls_cm]
    return R.StageMap(RM.RoomMap.from_mask("s400", (-5000.0, -5000.0), 250.0, rows, walls))


ACROSS = (-300.0, 100.0, 300.0, 100.0, 0.0, 300.0)          # a 6 m wall 1 m in front (+z), 3 m tall (cm)


def player(pos=(0.0, 0.0, 30.0), rot=0.0):
    return {"ptr": 0x5D00001000, "pos": pos, "rot": rot, "hp": 1000, "hp_max": 1000, "motion": 4}


def bot(sm):
    b = B.Bot(stats={}, clock=lambda: 5.0)
    b._sm, b._now = sm, 5.0
    return b


def test_the_stick_into_a_wall_goes_along_it_instead_never_on_the_spot():
    sm = stage([ACROSS])
    b = bot(sm)
    s = {"player": player()}
    act = b._room_guard({"hold": ("lup", "b")}, s)
    keys = set(act["hold"])
    assert "lup" not in keys or keys & {"lleft", "lright"}, "not straight on into it"
    assert keys & {"lup", "ldown", "lleft", "lright"}, "a stick direction: never a turn on the spot"
    h = W._travel_heading(s["player"], act["hold"])
    end = (80 * math.sin(h), 0.0, 30 + 80 * math.cos(h))
    assert sm.walk_clear(s["player"]["pos"], end, end_r=0.0, body_r=B.ROOM_BRUSH_CM)
    assert b.stats["room_map_steps_refused"] == 1 and "a wall" in b.stats["room_map_refused_last"]
    assert b._room_guard({"hold": ("ldown",)}, s) == {"hold": ("ldown",)}, "away from it: untouched"


def test_the_routes_way_round_is_followed_and_a_boxed_in_stick_is_let_go(monkeypatch):
    sm = stage([ACROSS])
    b = bot(sm)
    s = {"player": player()}
    b._mesh_wp = (250.0, 30.0, 5.0)                                    # the route's point off to his left (+x), clear
    act = b._room_guard({"hold": ("lup",)}, s)
    assert b.stats["room_map_route_follows"] == 1 and {"lleft", "rleft"} <= set(act["hold"]) and "lup" not in act["hold"]
    b._mesh_wp = (0.0, 90.0, 5.0)                                      # the route's point short of the wall: on
    assert b._room_guard({"hold": ("lup",)}, s) == {"hold": ("lup",)}
    box = stage([(-300, 60, 300, 60, 0, 300), (-300, 0, 300, 0, 0, 300), (-30, -300, -30, 300, 0, 300),
                 (30, -300, 30, 300, 0, 300)])
    b2 = bot(box)
    act = b2._room_guard({"hold": ("lup", "rleft")}, {"player": player()})
    assert set(act["hold"]) == {"rleft"} and b2.stats["room_map_boxed_in"] == 1
    monkeypatch.setattr(B, "ROOM_MAP", False)
    assert b._room_guard({"hold": ("lup",)}, s) == {"hold": ("lup",)}, "the rollback"


def test_no_shot_through_a_wall_and_the_close_in_goes_round():
    sm = stage([ACROSS])
    b = bot(sm)
    p, e = player(pos=(0.0, 0.0, 0.0)), {"ptr": 11, "pos": (0.0, 0.0, 1200.0), "hp": 800}
    assert b._walled_off(p, e, 5.0) and b.stats["room_map_sight_blocks"] == 1
    low = bot(stage([(-300.0, 100.0, 300.0, 100.0, 0.0, 100.0)]))      # a 1 m wall: the shot (1.4 m) passes over
    assert not low._walled_off(p, e, 5.0)
    assert not bot(None)._walled_off(p, e, 5.0), "no geometry: no gate"


def test_the_never_stand_step_goes_along_the_collisions_floor():
    sm = stage([ACROSS, (-60.0, -300.0, -60.0, 300.0, 0.0, 300.0)])     # walled ahead and on his left: right is open
    b = bot(sm)
    s = {"player": player(pos=(0.0, 0.0, 30.0)), "mercenaries_phase": None}
    b._stand = {"pos": (0.0, 0.0, 30.0), "at": 0.0, "until": -1e9, "keys": ()}
    act = b._never_stand({"hold": ()}, s, 5.0)
    h = W._travel_heading(s["player"], act["hold"])
    end = (B.STAND_PROBE_CM * math.sin(h), 0.0, 30 + B.STAND_PROBE_CM * math.cos(h))
    assert b.stats["stand_breaks"] == 1 and sm.walk_clear(s["player"]["pos"], end)


def test_the_stage_is_named_by_its_navigation_signature():
    class Nav:
        def __init__(self, sig):
            self.learning_sig = sig
    sig = {v: k for k, v in ss_ledger.SIGNATURES.items()}
    assert R.for_snap({"nav": Nav(sig["Village"])}).room == "s402"
    assert R.for_snap({"nav": Nav(sig["Experimental Facility"])}) is None, "s404 is not its collision"
    assert R.for_snap({"nav": Nav("1-2-x-y")}) is None and R.for_snap({}) is None
    assert set(R.STAGE_ARCHIVE) == set(ss_ledger.STAGE_NAMES) - {"Experimental Facility"}


# --- the real tables ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def doc():
    return json.loads(DOC.read_text(encoding="utf-8"))["stages"]


@pytest.mark.parametrize("name", sorted(R.STAGE_ARCHIVE))
def test_each_table_carries_the_docs_walls_and_grid(doc, name):
    arch = R.STAGE_ARCHIVE[name]
    t = json.loads(R.path_of(arch).read_text(encoding="utf-8"))
    d = doc[arch]
    assert t["stage"] == name == d["stage"]
    assert [w[:4] for w in t["walls"]] == [[float(v) for v in s] for s in d["wall_segments_mm"]]
    assert t["grid"]["origin_mm"] == d["grid"]["origin_mm"] and t["grid"]["cols"] == d["grid"]["cols"]
    assert all(w[5] - w[4] >= 999 for w in t["walls"]), "taller than 1 m, the span kept"
    assert t["checks"]["parser_floor_cells"] == d["grid"]["floor_cells"]
    assert t["checks"]["parser_floor_cells_without_floor"] == 0
    assert not R.path_of("s404").exists()


# The bot's own live route (cm), 2026-11-10: per stage two positions on cells #9360's grid marks '#' (none in Ancient
# Ruins' sample) and two walked steps (0.2 s apart). Each stands on the collision's floor, outside the computed '#',
# and no walked step crosses a wall.
LIVE = {
    "Public Assembly": ([(-1110.1, -200.0, -3534.9), (-1146.2, -200.0, -3541.4)],
                        [((1627.0, 50.0, -95.7), (1658.1, 50.0, -177.0)), ((1654.1, 50.0, -170.6), (1708.5, 50.0, -117.2))]),
    "The Mines": ([(3677.2, 298.3, -19087.3), (3680.5, 298.2, -19087.8)],
                  [((3454.9, 305.3, -19159.2), (3505.1, 302.4, -19178.9)),
                   ((3545.6, 300.0, -19133.3), (3612.4, 300.0, -19116.4))]),
    "Village": ([(-7064.4, 420.0, 2360.8), (-7369.9, 420.0, 2076.0)],
                [((-4875.0, 30.0, 6410.5), (-4869.1, 27.5, 6385.8)), ((-4867.0, 28.7, 6375.6), (-4870.0, 24.1, 6341.6))]),
    "Ancient Ruins": ([(145.3, 1049.5, 16928.5)],
                      [((145.6, 1049.5, 16928.4), (122.2, 1049.5, 16929.5)),
                       ((122.2, 1049.5, 16929.5), (6.5, 1049.7, 16934.9))]),
    "Missile Area": ([(-4436.5, 1100.0, -13588.7), (-4442.1, 1100.0, -13604.9)],
                     [((-4425.8, 1100.0, -13597.4), (-4447.1, 1100.0, -13597.4)),
                      ((-4447.1, 1100.0, -13597.4), (-4447.1, 1100.0, -13556.9))]),
    "Prison": ([(-199.6, 0.0, 576.6), (-176.0, 0.0, 610.6)],
               [((1702.1, -20.8, 983.0), (1704.4, -21.7, 1010.3)), ((1704.5, -21.8, 1012.9), (1671.3, -19.2, 984.5))]),
}


def test_the_frame_live_positions_stand_on_the_floor_and_walked_steps_cross_no_wall(doc):
    from gbox.re5_switch_collision import unrle_row
    for name, (positions, steps) in LIVE.items():
        sm, g = R.load(R.STAGE_ARCHIVE[name]), doc[R.STAGE_ARCHIVE[name]]["grid"]
        for x, y, z in positions:
            assert sm.floor_at(x, z) and not sm.blocked_cell(x, z, y), (name, x, z)
            if name != "Ancient Ruins":
                r, c = int((z * 10 - g["origin_mm"][1]) // 250), int((x * 10 - g["origin_mm"][0]) // 250)
                assert unrle_row(g["rows_rle"][r])[c] == "#", "the doc's grid marks it a wall"
        for a, b in steps:
            assert sm.walk_clear(a, b, end_r=0.0, body_r=0.0), (name, a, b)


def test_a_wall_he_walks_through_is_learned_and_the_tables_carry_his_live_crossings():
    sm = stage([ACROSS])
    b = bot(sm)
    b._room_prev = (4.9, (0.0, 0.0, 60.0))                            # a tick ago, 40 cm short of the wall
    b._room_guard({"hold": ("lup",)}, {"player": player(pos=(0.0, 0.0, 130.0))})   # now 30 cm past it
    assert b.stats["room_map_walls_passed"] == 1 and sm.rm.walls[0][6] == RM.WALKED
    assert sm.walk_clear((0.0, 0.0, 30.0), (0.0, 0.0, 200.0)) and sm.sight_clear((0, 0, 0), (0, 0, 300), 140, 110)
    far = bot(stage([ACROSS]))
    far._room_prev = (4.0, (0.0, 0.0, 60.0))                          # a second ago: not one step
    far._room_guard({"hold": ("lup",)}, {"player": player(pos=(0.0, 0.0, 130.0))})
    assert "room_map_walls_passed" not in far.stats
    gate = R.load("s403").rm.walls[262]                               # Ancient Ruins: a 4 m x 4 m face at z 160 m his
    assert gate[:4] == (1969.0, 160000.0, -2031.0, 160000.0) and gate[6] == RM.WALKED      # routes crossed 6 times
    assert R.load("s403").walk_clear((15.6, 1112.0, 15990.0), (15.6, 1112.0, 16010.0), end_r=0.0)
