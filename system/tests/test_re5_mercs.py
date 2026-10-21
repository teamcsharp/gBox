"""Title #2 of the Mercenaries engine: Resident Evil 5 Gold (PS3 BLUS30491) - the RAM map and the driver, on a small RAM
fixture laid out the way the live game keeps it (found on the Spark's RPCS3, 2026-10-20)."""
import math

import pytest
import struct

from gbox import ram_map
from gbox.mercs import engine, vocab
from gbox.mercs.titles import re5_ps3 as R

SPLAYER, SENEMY, MAIN = 0x3883_69C0, 0x3883_6FE0, 0x3000_0020
PLAYER, GAMESYS, ARRAY = 0x303F_8A00, 0x31EE_C3F0, 0x31F0_2C20
ENEMIES = [0x3070_E630 + 0x21B0 * i for i in range(4)]


class Mem:
    """Sparse big-endian guest memory: rd(addr, n) like the bots' readers."""

    def __init__(self):
        self.b: dict[int, int] = {}

    def put(self, a, data: bytes):
        for i, x in enumerate(data):
            self.b[a + i] = x

    def u32(self, a, v):
        self.put(a, struct.pack(">I", v))

    def rd(self, a, n):
        return bytes(self.b.get(a + i, 0) for i in range(n))

    read = rd


def quat(yaw):
    return struct.pack(">4f", 0.0, math.sin(yaw / 2), 0.0, math.cos(yaw / 2))


def world(player_pos=(0.0, 0.0, 0.0), yaw=0.0, action=0, pitch_raw=0.0, hp=1000, enemies=(), timer=100.0,
          score=900, kills=3, combo=2, combo_t=8.9):
    m = Mem()
    m.u32(R.S_PLAYER, SPLAYER)
    m.u32(SPLAYER + 0x28, PLAYER)
    m.put(PLAYER + 0x30, struct.pack(">3f", *player_pos))
    m.put(PLAYER + 0x40, quat(yaw))
    m.put(PLAYER + 0x845, bytes([action]))
    m.put(PLAYER + 0x1AA0, struct.pack(">f", pitch_raw))
    m.put(PLAYER + 0x14A4, struct.pack(">hh", hp, 1000))
    m.u32(R.S_ENEMY, SENEMY)
    m.u32(SENEMY + 0x28, len(enemies))
    m.u32(SENEMY + 0x34, ARRAY)
    for i, (pos, hp_e, hp_max) in enumerate(enemies):
        m.u32(ARRAY + 4 * i, ENEMIES[i])
        m.put(ENEMIES[i] + 0x30, struct.pack(">3f", *pos))
        m.put(ENEMIES[i] + 0x14A4, struct.pack(">hh", hp_e, hp_max))
    m.u32(R.S_MAIN, MAIN)
    m.u32(MAIN + R.MAIN_GAMESYS, GAMESYS)
    m.put(GAMESYS + 0x3E0, struct.pack(">2f", timer, 120.0))
    m.put(GAMESYS + 0x3F4, struct.pack(">i", kills))
    m.put(GAMESYS + 0x3FC, struct.pack(">i", combo))
    m.put(GAMESYS + 0x404, struct.pack(">f", combo_t))
    m.put(GAMESYS + 0x418, struct.pack(">i", score))
    return m


def test_the_map_follows_the_format_and_fills_the_vocabulary():
    m = ram_map.load("BLUS30491")
    assert m.platform == "ps3" and m.id == "BLUS30491"
    assert ram_map.resolve({"game_id": "e7ca89bbeb67360d"}) == "BLUS30491"
    prof = vocab.profile("BLUS30491")
    assert vocab.check(prof) == []
    assert prof.mercs["driver"] == "gbox.mercs.titles.re5_ps3" and prof.units_per_m == 100
    for name in ("merc.timer", "merc.score", "merc.kills", "merc.combo", "merc.combo_timer", "player.pos",
                 "player.hp", "player.action", "player.aim_pitch", "enemy.ptrs"):
        f = m.fields[name]
        assert f.spec.get("source") == "scan" and "live 2026-10-20" in f.spec.get("evidence", ""), name


def test_the_map_reads_the_fixture_like_the_live_game():
    mem = world(player_pos=(10.0, 550.0, -20.0), action=2, pitch_raw=-0.05, hp=608,
                enemies=[((100.0, 550.0, 300.0), 800, 800)], score=900, kills=3, combo=2)
    v = ram_map.load("BLUS30491").read(mem.rd)
    assert v["merc.timer"] == 100.0 and v["merc.score"] == 900 and v["merc.kills"] == 3 and v["merc.combo"] == 2
    assert v["player.pos"] == [10.0, 550.0, -20.0] and v["player.hp"] == 608 and v["player.hp_max"] == 1000
    assert v.label("player.action") == "aim" and abs(v["player.aim_pitch"] - 0.05) < 1e-6   # + = up after the scale
    assert v["enemy.count"] == 1 and v["enemy.ptrs"] == [ENEMIES[0]]


def test_snapshot_reads_the_singletons():
    mem = world(player_pos=(1.0, 2.0, 3.0), yaw=math.radians(90), enemies=[((5.0, 0.0, 6.0), 700, 700)])
    s = R.snapshot(mem)
    p = s["player"]
    assert p["ptr"] == PLAYER and p["pos"] == (1.0, 2.0, 3.0) and abs(p["rot"] - math.radians(90)) < 1e-6
    assert p["hp"] == 1000 and p["state"] == "stand" and s["enemies"][0]["hp"] == 700
    assert s["timer"] == 100.0 and s["score"] == 900 and s["combo"] == 2 and abs(s["combo_timer"] - 8.9) < 1e-3
    assert R.own_screen(s) == "playing"


def test_screens_from_ram():
    assert R.own_screen(R.snapshot(world(hp=0))) == "dead"
    assert R.own_screen(R.snapshot(world(timer=0.0))) == "results"
    mem = world()
    mem.u32(SPLAYER + 0x28, 0)                      # results / menus: sPlayer holds no player
    assert R.own_screen(R.snapshot(mem)) == "loading"
    assert R.RE5PS3().screen(mem, None) == "loading"


def tick(mem, bot=None):
    bot = bot or R.Bot(clock=lambda: 100.0)
    return bot.tick(R.snapshot(mem)), bot


def test_turns_toward_the_majini_then_aims():
    # heading convention atan2(dx, dz): a Majini at +x is at +90 deg; facing +z (0): turn left (larger heading)
    act, bot = tick(world(enemies=[((1000.0, 0.0, 0.0), 800, 800)]))
    assert act == {"hold": {"rleft"}}
    act, _ = tick(world(yaw=math.radians(-90), enemies=[((-1.0, 0.0, -1000.0), 800, 800)]))   # behind-left
    assert act["hold"] == {"rleft"} or act["hold"] == {"rright"}
    act, _ = tick(world(yaw=math.radians(90), enemies=[((1000.0, 0.0, 0.0), 800, 800)]))
    assert act == {"hold": {"l1"}}                   # facing him: ready the gun


def test_aims_the_pitch_onto_the_head_and_fires():
    e = [((0.0, 0.0, 1000.0), 800, 800)]            # straight ahead; head 160 above his feet, gun 140 above ours
    want = math.atan2(R.HEAD_H - R.GUN_H, 1000.0)
    act, _ = tick(world(action=2, pitch_raw=-(want - 0.3), enemies=e))   # aimed 0.3 rad low: raise it, no fire
    assert "rup" in act["hold"] and "r1" not in act["hold"] and "l1" in act["hold"]
    act, _ = tick(world(action=2, pitch_raw=-(want + 0.3), enemies=e))   # high: lower it
    assert "rdown" in act["hold"] and "r1" not in act["hold"]
    act, bot = tick(world(action=2, pitch_raw=-want, enemies=e))         # on him: fire
    assert act["hold"] >= {"l1", "r1"} and bot.target == 0


def test_skips_crows_rooftops_and_the_dead_and_backs_off_when_on_top():
    e = [((0.0, 0.0, 300.0), 1, 1),                 # a crow: 1 health
         ((0.0, 900.0, 400.0), 800, 800),           # up on a roof
         ((0.0, 0.0, 500.0), 0, 800),               # dead
         ((900.0, 0.0, 0.0), 800, 800)]             # the one to fight: at +x
    act, bot = tick(world(enemies=e))
    assert act == {"hold": {"rleft"}}                # turning toward the live Majini at +x, not the crow ahead
    act, _ = tick(world(enemies=[((0.0, 0.0, 60.0), 800, 800)]))
    assert "ldown" in act["hold"]                    # on top of us: a step back
    act, _ = tick(world(enemies=[((0.0, 0.0, 6000.0), 800, 800)]))
    assert {"lup", "cross"} <= act["hold"]           # far: run to him


def test_hits_and_kills_are_counted_from_health():
    bot = R.Bot(clock=lambda: 1.0)
    bot.tick(R.snapshot(world(action=2, enemies=[((0.0, 0.0, 800.0), 800, 800)])))
    bot.tick(R.snapshot(world(action=2, enemies=[((0.0, 0.0, 800.0), 500, 800)])))
    bot.tick(R.snapshot(world(action=2, enemies=[((0.0, 0.0, 800.0), 0, 800)])))
    assert bot.stats["hits"] == 2 and bot.stats["kills_seen"] == 1


def test_play_round_runs_the_driver_until_the_round_ends():
    mem = world(action=2, enemies=[((0.0, 0.0, 1000.0), 800, 800)])
    sent, n = [], [0]

    def stopped():
        n[0] += 1
        if n[0] == 5:                                 # the clock runs out: the results screen
            mem.put(GAMESYS + 0x3E0, struct.pack(">f", 0.0))
        return n[0] > 50
    stats: dict = {}
    why = engine.play_round({"driver": "gbox.mercs.titles.re5_ps3"}, mem, sent.extend, stopped, stats,
                            sleep=lambda s: None, clock=lambda: n[0] * 0.5, tick_s=0.0)
    assert why == "round" and stats["timer"] == 100.0 and stats["score"] == 900
    assert {"key": "l1", "down": True} in sent        # pad names, pressed as a diff


def with_camera(mem, eye, at):
    """sBioCamera (static 0x0191CA6C) +0x104 -> uCameraCtrl: eye +0x30, look-at +0x50."""
    cam_mgr, cam = 0x3827_8170, 0x304F_C760
    mem.u32(R.S_CAMERA, cam_mgr)
    mem.u32(cam_mgr + R.CAM_CTRL, cam)
    mem.put(cam + R.CAM_EYE, struct.pack(">3f", *eye))
    mem.put(cam + R.CAM_AT, struct.pack(">3f", *at))
    return mem


def test_aims_on_the_cameras_look_ray_when_there_is_one():
    e = [((0.0, 0.0, 1000.0), 800, 800)]            # head at (0, 160, 1000)
    eye = (0.0, 200.0, -150.0)                       # over the shoulder, behind the player
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (0.0, 600.0, 400.0)))    # well above his head
    assert "rdown" in act["hold"] and "r1" not in act["hold"]
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (0.0, -300.0, 400.0)))   # at the ground
    assert "rup" in act["hold"] and "r1" not in act["hold"]
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (0.0, 160.0, 1000.0)))   # the crosshair on his head
    assert act["hold"] >= {"l1", "r1"}
    # facing +z, +x is on the left (the stick's left turns toward larger headings): a look at -x is right of him
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (-400.0, 160.0, 1000.0)))
    assert "rleft" in act["hold"] and "r1" not in act["hold"]
    act, _ = tick(with_camera(world(action=2, enemies=e), eye, (400.0, 160.0, 1000.0)))   # left of him: turn right
    assert "rright" in act["hold"] and "r1" not in act["hold"]


def test_continues_after_you_are_dead_and_walks_the_menus():
    bot = R.Bot(clock=lambda: 10.0)
    assert bot.tick(R.snapshot(world(hp=0))) == {"tap": "cross"}
    assert bot.tick(R.snapshot(world(hp=0))) == {"hold": set()}      # not again within 1.5 s
    assert [R.menu_key(n) for n in range(4)] == ["start", "cross", "start", "cross"]


def with_ui(mem, names, line=27):
    """sUnit (static 0x0191D700) with the interface units `names` in one move line (+0x24 + 0x20 * line: +0xC the first
    unit; a unit's +8 the next); a unit is its vtable (UI_VTABLES)."""
    sunit, first = 0x3882_5B20, 0x3009_8D00
    vt = {v: k for k, v in R.UI_VTABLES.items()}
    mem.u32(R.S_UNIT, sunit)
    mem.u32(sunit + R.UNIT_LINES + R.LINE_STRIDE * line + R.LINE_FIRST, first if names else 0)
    for i, n in enumerate(names):
        u = first + 0x100 * i
        mem.u32(u, vt[n])
        mem.u32(u + R.UNIT_NEXT, u + 0x100 if i + 1 < len(names) else 0)
    return mem


def between_rounds(names):
    mem = world(timer=0.0)
    mem.u32(SPLAYER + 0x28, 0)                       # out of a round: sPlayer holds no player
    return with_ui(mem, names)


def test_the_screens_between_rounds_come_from_the_interface_units():
    assert R.screen(between_rounds(["uIdStartUp21", "uIdTitle00", "uIdTopMenu00"]))["where"] == "select_stage"
    assert R.screen(between_rounds(["uIdStartUp22", "uIdTitle02", "uIdTopMenu00"]))["where"] == "select_player"
    assert R.screen(between_rounds(["uIdNowLoading00"]))["where"] == "loading"
    assert R.screen(between_rounds(["uIdSaving00"]))["where"] == "loading"       # the results, saving the records
    assert R.screen(between_rounds(["uIdTitle00", "uIdTopMenu00"]))["where"] == "menu"   # between the selects / main menu
    assert R.screen(between_rounds([]))["where"] == "results"                     # the clock at 0, nothing else up
    mem = world(enemies=[((0.0, 0.0, 900.0), 800, 800)])
    assert R.screen(with_ui(mem, ["uIdMerce00", "uIdPause00"]))["where"] == "playing"
    assert R.screen(world(hp=0))["where"] == "dead"


def test_it_presses_only_on_the_reunion_screens():
    assert R.step({"where": "results"}) == "start"
    assert R.step({"where": "select_stage"}) == "cross" and R.step({"where": "select_player"}) == "cross"
    assert R.step({"where": "dead"}) == "cross"
    for where in ("menu", "loading", "unknown", "playing"):
        assert R.step({"where": where}) is None, where                       # never a press on the title's menus
    assert R.wandered({"where": "menu"}) is None


def test_a_grab_is_answered_with_a_wiggle():
    held = world(action=R.P_GRABBED, enemies=[((0.0, 0.0, 60.0), 800, 800)])
    assert R.prompt(held) == "wiggle"
    assert R.prompt(world(action=2)) is None
    drv = R.RE5PS3()
    assert drv.prompt_source(held, {})() == "wiggle"
    assert drv.prompt_keys("wiggle") == [("lleft",), ("lright",), ("lleft",), ("lright",)]
    assert drv.prompt_keys("square") == [("square",)]
    from gbox.mercs import reactions
    assert "wiggle" in reactions.MASH                                             # the engine mashes it, never rests
    assert R.snapshot(held)["player"]["state"] == "grabbed"


def with_prompt(mem, kind, owner, target, hud=0x4B):
    """sActionButton (static 0x017B7174) with a prompt up (+0x34 bit 1) and +0x2A4 -> a cActionButton: +0x04 owner,
    +0x14 kind, +0x40 the Majini it acts on."""
    ab, btn = 0x3883_8370, 0x328E_1FE0
    mem.u32(R.S_ACTION, ab)
    mem.u32(ab + R.AB_HUD, hud)
    mem.u32(ab + R.AB_BUTTON, btn)
    mem.u32(btn + R.BTN_OWNER, owner)
    mem.u32(btn + R.BTN_KIND, kind)
    mem.u32(btn + R.BTN_TARGET, target)
    return mem


def test_a_melee_finisher_on_a_majini_is_pressed_with_square():
    e = [((0.0, 0.0, 150.0), 450, 800)]
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_MELEE, PLAYER, ENEMIES[0])) == "square"     # "Hook"
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_MELEE, PLAYER, ENEMIES[0], hud=0x49)) is None   # not up
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_STAGE, PLAYER, 0)) is None                  # "Jump over"
    assert R.prompt(with_prompt(world(enemies=e), R.BTN_MELEE, PLAYER, 0x3099_0000)) is None        # not a Majini
    assert R.prompt(with_prompt(world(enemies=e), 0, ENEMIES[0], 0)) is None                       # his grab button
    held = with_prompt(world(action=R.P_GRABBED, enemies=e), 0, ENEMIES[0], 0, hud=0x4A)
    assert R.prompt(held) == "wiggle"                                                             # the grab itself
    act, _ = tick(with_prompt(world(action=2, enemies=e), R.BTN_MELEE, PLAYER, ENEMIES[0]))
    assert act == {"hold": set()}                     # the gun down while the engine presses the finisher (no L1)


HOURGLASS_VT = 0x0159_0000


def with_bonuses(mem, centres, kind=0x00A00C01):
    """sUnit's OM line with a barrel and hourglasses (uOm0100 = HOURGLASS_VT) whose bounding spheres (+0x250: centre,
    28 cm radius) sit at `centres`; +0x194 their kind word."""
    sunit, first = 0x3882_5B20, 0x3040_0000
    mem.u32(R.S_UNIT, sunit)
    mem.u32(sunit + R.UNIT_LINES + R.LINE_STRIDE * R.OM_LINE + R.LINE_FIRST, first)
    units = [(0x0158_8888, (500.0, 0.0, 500.0))] + [(HOURGLASS_VT, q) for q in centres]   # a barrel first
    for i, (vt, q) in enumerate(units):
        u = first + 0x1000 * i
        mem.u32(u, vt)
        mem.put(u + 0x30, struct.pack(">3f", q[0], q[1] - 13.0, q[2]))           # the origin: 13 cm below the centre
        mem.put(u + R.HG_CENTRE, struct.pack(">4f", *q, 28.4))
        mem.u32(u + R.HG_KIND, kind)
        mem.u32(u + R.UNIT_NEXT, u + 0x1000 if i + 1 < len(units) else 0)
    return mem


def test_time_bonuses_are_read_from_the_om_line(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    snap = R.snapshot(with_bonuses(world(), [(0.0, 140.0, 1000.0), (-800.0, 50.0, 0.0)]))
    assert [b["pos"] for b in snap["bonuses"]] == [(0.0, 140.0, 1000.0), (-800.0, 50.0, 0.0)]
    assert snap["bonuses"][0]["r"] == pytest.approx(28.4) and snap["bonuses"][0]["kind_word"] == 0x00A00C01
    monkeypatch.setattr(R, "HOURGLASS_VT", 0)                                     # not known: none read
    assert R.snapshot(with_bonuses(world(), [(0.0, 0.0, 1000.0)]))["bonuses"] == []


def test_it_shoots_a_time_bonus_when_no_majini_is_close(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    far_majini = [((3000.0, 0.0, 0.0), 800, 800)]                                # 30 m away at +x
    want = math.atan2(20.0 - R.GUN_H, 1000.0)                                     # an hourglass 10 m ahead, 20 cm up
    act, bot = tick(with_bonuses(world(action=2, pitch_raw=-want, enemies=far_majini), [(0.0, 20.0, 1000.0)]))
    assert act["hold"] >= {"l1", "r1"} and str(bot.target).startswith("bonus")
    assert "bonus_target" in bot.stats
    act, _ = tick(with_bonuses(world(action=2, pitch_raw=-(want + 0.05), enemies=far_majini), [(0.0, 20.0, 1000.0)]))
    assert "r1" not in act["hold"]                                                # 3 deg off a 28 cm sphere: no shot
    close = [((0.0, 0.0, 500.0), 800, 800)]                                       # a Majini 5 m away: him first
    act, bot = tick(with_bonuses(world(action=2, enemies=close), [(0.0, 20.0, 1000.0)]))
    assert bot.target == 0


def test_a_bonus_shots_cannot_take_is_left_alone_for_a_while(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    want = math.atan2(20.0 - R.GUN_H, 1000.0)
    clock = [100.0]
    bot = R.Bot(clock=lambda: clock[0])
    mem = with_bonuses(world(action=2, pitch_raw=-want), [(0.0, 20.0, 1000.0)])
    for _ in range(int(R.BONUS_GIVE_UP_S / 0.05) + 2):                           # firing at it, it stays
        act = bot.tick(R.snapshot(mem))
    assert "r1" not in act["hold"]                                                # left alone now
    clock[0] += R.BONUS_SKIP_S + 1
    assert "r1" in bot.tick(R.snapshot(mem))["hold"]                              # tried again later


def test_far_bonuses_wait_and_the_clock_jumps_are_counted(monkeypatch):
    monkeypatch.setattr(R, "HOURGLASS_VT", HOURGLASS_VT)
    act, bot = tick(with_bonuses(world(), [(0.0, 0.0, 2500.0)]))                  # 25 m ahead, nobody near
    assert act == {"hold": set()}                                                 # no walking to bonuses yet
    monkeypatch.setattr(R, "BONUS_WALK", True)
    act, bot = tick(with_bonuses(world(), [(0.0, 0.0, 2500.0)]))
    assert {"lup", "cross"} <= act["hold"]                                        # with routes: runs to it
    bot.tick(R.snapshot(with_bonuses(world(timer=60.0), [])))                     # gone from the line: taken
    assert bot.stats["bonuses_taken"] == 1
    bot.tick(R.snapshot(with_bonuses(world(timer=89.5), [])))                     # the clock +29.5 s: a time bonus
    assert bot.stats["clock_jumps"] == 1 and bot.stats["bonus_s"] == 29.5
