"""GoldenEye 007 PC port bots: the bridge block (gbox/ge007_bridge.py, adapters/ge007_port/gbox_bridge.c) and the
driver that turns a bot brain's intent into an N64 pad (gbox/ge007_bots.py)."""
import re
import struct
from pathlib import Path

from gbox import bot_brain
from gbox import ge007_bots as bots
from gbox import ge007_bridge as gb

C_SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "ge007_port" / "gbox_bridge.c"


def block(players=(), items=(), nodes=(), adj=(), in_match=True, stage=38, nav_serial=1, frame=100):
    """A bridge block as the port writes it."""
    mm = bytearray(gb.SIZE)
    edges = [j for a in adj for j in a]
    gb.HEADER.pack_into(mm, 0, gb.MAGIC, gb.VERSION, gb.SIZE, frame, stage, len(players), int(in_match), nav_serial,
                        len(nodes), len(edges), len(items), 0, 4242, 0, 0, 0)
    for i, p in enumerate(players):
        row = {"pos": (0.0, 0.0, 0.0), "theta": 0.0, "verta": 0.0, "health": 1.0, "armour": 0.0, "dead": 0,
               "weapon": 8, "room": 1, "near": -1, "visible": 0, "kills": 0, "deaths": 0, "points": 0, "flags": 3,
               "ammo": 30, "mag": 30} | p
        gb.PLAYER.pack_into(mm, gb.OFF_PLAYERS + i * gb.PLAYER.size, *row["pos"], row["theta"], row["verta"],
                            row["health"], row["armour"], row["dead"], row["weapon"], row["room"], row["near"],
                            row["visible"], row["kills"], row["deaths"], row["points"], row["flags"], row["ammo"],
                            row["mag"], 0, 0)
    for k, (pos, item) in enumerate(items):
        gb.ITEM.pack_into(mm, gb.OFF_ITEMS + k * gb.ITEM.size, *pos, item)
    first = 0
    for i, pos in enumerate(nodes):
        gb.NODE.pack_into(mm, gb.OFF_NODES + i * gb.NODE.size, *pos, first, len(adj[i]), 2)
        first += len(adj[i])
    if edges:
        struct.pack_into(f"<{len(edges)}i", mm, gb.OFF_EDGES, *edges)
    return mm


def bridge_on(mm) -> gb.Bridge:
    br = gb.Bridge("unused")
    br.mm = mm
    return br


def test_python_layout_matches_the_c_bridge():
    """The C file's _Static_assert offsets and sizes are the Python mirror's."""
    src = C_SOURCE.read_text()
    asserted = {m.group(1): int(m.group(2)) for m in re.finditer(r"offsetof\(GbxBridge, (\w+)\) == (\d+)", src)}
    assert asserted == {"players": gb.OFF_PLAYERS, "seats": gb.OFF_SEATS, "items": gb.OFF_ITEMS,
                        "chrs": gb.OFF_CHRS, "nodes": gb.OFF_NODES, "edges": gb.OFF_EDGES}
    sizes = {m.group(1): int(m.group(2)) for m in re.finditer(r"sizeof\((\w+)\) == (\d+)", src)}
    assert sizes == {"GbxPlayer": gb.PLAYER.size, "GbxSeat": gb.SEAT.size, "GbxNode": gb.NODE.size,
                     "GbxChr": gb.CHR.size, "GbxBridge": gb.SIZE}
    assert f"#define GBX_VERSION      {gb.VERSION}" in src and "0x31584247u" in src
    for fn in ("void gboxBridgeTick(void)", "int gboxBridgeSeat(int idx, unsigned *button, int *sx, int *sy)"):
        assert fn in src


def test_snapshot_and_nav_parse():
    mm = block(players=[{"pos": (1.0, 2.0, 3.0), "theta": 90.0, "visible": 0b100, "weapon": 13, "kills": 2},
                        {"dead": 1, "ammo": 0}],
               items=[((5.0, 0.0, 5.0), 14)], nodes=[(0, 0, 0), (100, 0, 0)], adj=[[1], [0]])
    s = gb.parse_snapshot(mm)
    assert s.in_match and s.stage == 38 and s.nplayers == 2 and s.pid == 4242
    p0, p1 = s.players[:2]
    assert p0.pos == (1.0, 2.0, 3.0) and p0.theta == 90.0 and p0.sees(2) and not p0.sees(1) and p0.kills == 2
    assert p0.weapon == 13 and p0.on_floor and p0.present and p1.dead and p1.ammo == 0
    assert not s.players[2].present
    assert s.items[0].item == 14
    nav = gb.parse_nav(mm)
    assert nav.serial == 1 and nav.nodes == [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)] and nav.adj == [[1], [0]]


def test_parse_refuses_a_foreign_block():
    mm = block()
    struct.pack_into("<I", mm, 4, 99)
    try:
        gb.parse_snapshot(mm)
    except ValueError as e:
        assert "version" in str(e)
    else:
        raise AssertionError("a version 99 block parsed")


def test_heading_and_bearing_conventions():
    # the AI's bearing is atan2(dx, dz); the player's yaw is 360 - vv_theta (measured on the port: walking with
    # theta 53.46 moved along bearing ~306.5)
    assert gb.heading_deg(53.46) == 306.54
    assert round(gb.bearing_deg((0, 0, 0), (0, 0, 10))) == 0
    assert round(gb.bearing_deg((0, 0, 0), (10, 0, 0))) == 90


def test_drive_and_release_write_the_seat_and_bump_seq():
    mm = block()
    br = bridge_on(mm)
    br.drive(2, gb.Z | gb.CR, 120, -30)
    seq, enabled, buttons, sx, sy, live = gb.SEAT.unpack_from(mm, gb.OFF_SEATS + 2 * gb.SEAT.size)
    assert (seq, enabled, buttons, sx, sy, live) == (1, 1, gb.Z | gb.CR, 80, -30, 0)   # stick clamped to +-80
    br.release(2)
    seq, enabled, buttons, *_ = gb.SEAT.unpack_from(mm, gb.OFF_SEATS + 2 * gb.SEAT.size)
    assert (seq, enabled, buttons) == (2, 0, 0)
    br.mm = None                                     # closed: writes are no-ops, reads say so
    br.drive(1, gb.A)
    br.release(1)
    assert br.nav() is None


def test_seat_measures_turn_sign_and_control_style():
    seat = bots.Seat(1, "00", rng=None)
    p = gb.Player(1, True, (0.0, 0.0, 0.0), theta=10.0, verta=0.0)
    assert seat.calibrate(p, 0.0) == (50, 0)                     # turn test: stick X held
    p.theta = 25.0                                                # theta up -> heading (360 - theta) down
    assert seat.calibrate(p, 0.5) == (0, 0)
    assert seat.turn_sign == -1 and not seat.ready
    assert seat.calibrate(p, 0.6) == (0, 50)                     # style test: stick Y held
    p.verta = -6.0                                                # the view tilted: 1.2 Solitare (stick looks)
    seat.calibrate(p, 1.0)
    assert seat.style == "solitare" and seat.pitch_sign == -1 and seat.ready
    honey = bots.Seat(2, "00", rng=None)
    honey.turn_sign = 1
    q = gb.Player(2, True, (0.0, 0.0, 0.0))
    honey.calibrate(q, 0.0)
    q.pos = (0.0, 0.0, 40.0)                                      # walked instead: 1.1 Honey
    honey.calibrate(q, 0.5)
    assert honey.style == "honey"


def test_pad_mapping_per_style_and_fire_modes():
    seat = bots.Seat(1, "00", rng=None)
    seat.turn_sign, seat.style = -1, "honey"
    i = bot_brain.Intent(forward=1.0, strafe=-1.0, turn=0.5, fire=True)
    buttons, sx, sy = seat.pad(i, weapon=13)                      # AR33: automatic, Z held
    assert buttons & gb.Z and buttons & gb.CL and sx == -40 and sy == 80
    assert seat.pad(i, weapon=13)[0] & gb.Z
    semi = [bool(seat.pad(i, weapon=4)[0] & gb.Z) for _ in range(4)]   # PP7: one press per shot
    assert semi in ([True, False, True, False], [False, True, False, True])
    seat.style, seat.pitch_sign = "solitare", -1
    buttons, sx, sy = seat.pad(bot_brain.Intent(forward=1.0), weapon=13, verta=10.0)
    assert buttons & gb.CU and sy > 0                             # walk on C-up; stick Y levels a raised view
    assert seat.pad(bot_brain.Intent(forward=-1.0), weapon=13, verta=0.0)[0] & gb.CD
    seat.pad(bot_brain.Intent(respawn=True), weapon=0)
    assert seat.pad(bot_brain.Intent(), weapon=0)[0] & gb.A       # A is held two ticks


def test_weapon_scores_and_picker():
    assert bots.weapon_score(14) > bots.weapon_score(4) > bots.weapon_score(0) == 0.0
    assert bots.weapon_score(25, enemy_close=True) < 0.1           # no rockets at arm's length
    assert bots.weapon_score(13, ammo=0) == 0.0
    pick = bots.WeaponPicker()
    assert pick.want_cycle(0, 0.0, False)                          # fists: next weapon
    assert not pick.want_cycle(0, 0.3, False)                      # not before 0.7 s
    assert not pick.want_cycle(4, 1.0, False)                      # a PP7, the best seen so far: keep it
    pick.reset()
    assert not pick.want_cycle(14, 2.0, False)                     # RC-P90: keep it
    for t in range(13):
        pick.want_cycle(0, 10.0 + t, False)
    assert pick.pause_until > 0                                    # went round 12 times: stop for a while


def test_step_drives_bot_seats_and_idles_outside_a_match():
    nodes = [(0.0, 0.0, 0.0), (500.0, 0.0, 0.0), (1000.0, 0.0, 0.0)]
    players = [{"pos": (5000.0, 0.0, 5000.0)}, {"pos": (0.0, 0.0, 0.0), "near": 0, "theta": 270.0},
               {"pos": (1000.0, 0.0, 0.0), "near": 2}]
    mm = block(players=players, nodes=nodes, adj=[[1], [0, 2], [1]])
    br = bridge_on(mm)
    b = bots.GoldenEyeBots(br, seats=(1, 2, 3), difficulty="00")
    for s in b.seats.values():
        s.turn_sign, s.style = -1, "honey"
    b.step(0.0)
    seq1, en1, _btn, sx1, sy1, _ = gb.SEAT.unpack_from(mm, gb.OFF_SEATS + 1 * gb.SEAT.size)
    assert en1 == 1 and seq1 == 1 and sy1 == 80                  # heading 90 (theta 270): straight at node 1
    seq3, en3, *_ = gb.SEAT.unpack_from(mm, gb.OFF_SEATS + 3 * gb.SEAT.size)
    assert seq3 == 1 and en3 == 1                                  # seat 3 has no player: held idle
    assert b.stats["seats"][1]["goal"] in ("hunt", "pickup", "roam")
    gb.HEADER.pack_into(mm, 0, gb.MAGIC, gb.VERSION, gb.SIZE, 200, 90, 1, 0, 1, 3, 4, 0, 0, 4242, 0, 0, 0)
    b.step(1.0)                                                    # title screen: every seat idle
    assert gb.SEAT.unpack_from(mm, gb.OFF_SEATS + 1 * gb.SEAT.size)[2:5] == (0, 0, 0)


def test_player_one_autoplay_presses_start_through_menus():
    mm = block(players=[{}], in_match=False, stage=90)
    b = bots.GoldenEyeBots(bridge_on(mm), seats=(0,), menus=True)
    seat0 = lambda: gb.SEAT.unpack_from(mm, gb.OFF_SEATS)[2]               # noqa: E731
    b.step(10.0)
    assert seat0() == gb.START
    b.step(10.5)
    assert seat0() == 0                                                      # a press, not a hold
    b.step(11.6)
    assert seat0() == gb.START
    quiet = bots.GoldenEyeBots(bridge_on(block(players=[{}], in_match=False)), seats=(1,))
    quiet.step(10.0)
    assert gb.SEAT.unpack_from(quiet.bridge.mm, gb.OFF_SEATS + gb.SEAT.size)[2] == 0   # bot seats never press


def test_playbook_matches_only_a_port_session_with_a_bridge():
    class Ad:
        port_id = "ge007"
        bridge = object()
    assert bots.matches(Ad(), {})
    Ad.bridge = None
    assert not bots.matches(Ad(), {})
    assert not bots.matches(object(), {})
