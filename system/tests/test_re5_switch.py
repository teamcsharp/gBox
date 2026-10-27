"""RE5 Switch Mercenaries driver (gbox.mercs.titles.re5_switch) on a fake 64-bit little-endian guest laid out like the
live measurements of 2026-10-26: module base found by its read-only signature, MtDTI classes through getDTI, the round
from cGameSys / sPlayer / sEnemy, the native menus from sUnit's interface units."""
import math
import struct
from types import SimpleNamespace

import pytest

from gbox import mercs_bot, ram_map
from gbox.mercs.titles import re5_switch as R

BASE = 0x3CA89C3000                      # the live run's main base (ASLR moves it every boot)
HEAP = 0x5D00000000


class Guest:
    """Guest memory as two rows like Eden's HostMemory ones (main's image, a heap): rd(a, n) inside them only."""
    MAIN_SIZE, HEAP_SIZE = 0x2800000, 0x400000

    def __init__(self):
        self.regions = {BASE: bytearray(self.MAIN_SIZE), HEAP: bytearray(self.HEAP_SIZE)}
        self.next_heap = HEAP
        self.dtis: dict[str, int] = {}
        self.code = BASE + 0x100000      # getDTI functions
        self.names = BASE + 0x1800000    # class name strings
        self.dti_at = BASE + 0x1D00000   # the DTIs
        self.put(BASE + R.SIG_OFF, R.SIGNATURE)

    def _region(self, a, n):
        for s, buf in self.regions.items():
            if s <= a and a + n <= s + len(buf):
                return s, buf
        raise ValueError(f"unmapped {a:#x}")

    def put(self, a, data: bytes):
        s, buf = self._region(a, len(data))
        buf[a - s:a - s + len(data)] = data

    def q(self, a, v):
        self.put(a, struct.pack("<Q", v))

    def i32(self, a, v):
        self.put(a, struct.pack("<i", v))

    def rd(self, a, n):
        s, buf = self._region(a, n)
        return bytes(buf[a - s:a - s + n])

    def rows(self):
        return [(s, s + len(buf), "r--p" if s == BASE else "rw-p") for s, buf in self.regions.items()]

    def alloc(self, n):
        a = self.next_heap
        self.next_heap += (n + 0xFFF) & ~0xFFF
        return a

    def klass(self, name: str) -> int:
        """A vtable whose slot 5 is `adrp x0 / add x0 / ret` returning a DTI named `name`."""
        if name not in self.dtis:
            dti = self.dti_at + 0x40 * len(self.dtis)
            s = self.names + 0x40 * len(self.dtis)
            self.put(s, name.encode() + b"\0")
            self.q(dti + R.DTI_NAME, s)
            f = self.code + 0x20 * len(self.dtis)
            imm = ((dti & ~0xFFF) - (f & ~0xFFF)) >> 12
            adrp = 0x90000000 | ((imm & 3) << 29) | (((imm >> 2) & 0x7FFFF) << 5)
            add = 0x91000000 | ((dti & 0xFFF) << 10)
            self.put(f, struct.pack("<III", adrp, add, 0xD65F03C0))
            vt = self.code + 0x80000 + 0x100 * len(self.dtis)
            self.q(vt + 8 * R.GET_DTI_SLOT, f)
            self.dtis[name] = vt
        return self.dtis[name]

    def obj(self, name, size=0x2000):
        o = self.alloc(size)
        self.put(o, bytes(size))
        self.q(o, self.klass(name))
        return o


@pytest.fixture(autouse=True)
def _fresh_laser_caches():
    """The laser caches are per main base, and every fake guest here shares BASE."""
    for cache in (R._LASER, R._LASER_MISS, R._NOT_LASER):
        cache.clear()
    yield


def round_guest(phase=R.PHASE_PLAYING, hp=1000, timer=97.5, enemies=((300.0, 0.0, 500.0, 800),), player=True,
                units=(), cursors=None, motion=0):
    g = Guest()
    main = g.obj("sBioMain", 0x60000)
    g.q(BASE + R.S_MAIN, main)
    gs = g.obj("cGameSys", 0xA88)
    g.q(main + R.MAIN_GAMESYS, gs)
    g.i32(gs + R.GS_PHASE, phase)
    g.put(gs + R.GS_TIMER, struct.pack("<ff", timer, 120.0))
    g.i32(gs + R.GS_KILLS, 9)
    g.i32(gs + R.GS_COMBO, 4)
    g.i32(gs + R.GS_MAX_COMBO, 6)
    g.put(gs + R.GS_COMBO_T, struct.pack("<f", 8.5))
    g.i32(gs + R.GS_SCORE, 3060)
    sp = g.obj("sPlayer", 0x610)
    g.q(BASE + R.S_PLAYER, sp)
    if player:
        p = g.obj("uPl00ChrisNormal", 0x3000)
        g.q(sp + R.P_FIRST, p)
        g.put(p + R.P_POS, struct.pack("<3f", 0.0, 0.0, 0.0))
        g.put(p + R.P_ROT, struct.pack("<4f", 0.0, 0.0, 0.0, 1.0))      # heading 0: facing +z
        g.put(p + R.P_HP, struct.pack("<hh", hp, 1000))
        g.put(p + R.P_MOTION, bytes([motion]))
    se = g.obj("sEnemy", 0x1B0)
    g.q(BASE + R.S_ENEMY, se)
    arr = g.alloc(8 * max(1, len(enemies)))
    g.put(se + R.E_COUNT, struct.pack("<I", len(enemies)))
    g.q(se + R.E_ARRAY, arr)
    for i, (x, y, z, ehp) in enumerate(enemies):
        e = g.obj("uEm10", 0x3000)
        g.q(arr + 8 * i, e)
        g.put(e + R.E_POS, struct.pack("<3f", x, y, z))
        g.put(e + R.E_HP, struct.pack("<hh", ehp, 800))
    su = g.obj("sUnit", 0x800)
    g.q(BASE + R.S_UNIT, su)
    prev = {}
    for line, name in units:
        u = g.obj(name, 0x400)
        if line in prev:
            g.q(prev[line] + R.UNIT_NEXT, u)
        else:
            g.q(su + R.UNIT_LINES + R.LINE_STRIDE * line, u)
        prev[line] = u
        for off, v in (cursors or {}).get(name, {}).items():
            g.i32(u + off, v)
    return g


# --- RAM -----------------------------------------------------------------------------------------------------------

def test_module_base_is_found_by_signature_and_rechecked():
    g = round_guest()
    assert R.module_base(g) == BASE and g.module_base == BASE
    g.module_base = BASE + 0x1000                      # a stale cache from an earlier boot: searched again
    assert R.module_base(g) == BASE
    empty = Guest()
    empty.put(BASE + R.SIG_OFF, bytes(len(R.SIGNATURE)))
    assert R.module_base(empty) is None


def test_classes_come_from_getdti():
    g = round_guest()
    assert R.class_name(g, R.u64(g, BASE + R.S_PLAYER)) == "sPlayer"
    assert R.class_name(g, HEAP + 0x7FFFFF00) is None                  # unmapped: no class


def test_each_enemy_carries_his_class_named_once_per_vtable(monkeypatch):
    R._CLASSES.clear()
    g = round_guest(enemies=((300.0, 0.0, 500.0, 800), (-200.0, 0.0, 900.0, 700)))
    calls = []
    real = R.class_name
    monkeypatch.setattr(R, "class_name", lambda m, o: calls.append(o) or real(m, o))
    assert [e["class"] for e in R.snapshot(g)["enemies"]] == ["uEm10", "uEm10"]
    R.snapshot(g)
    assert len(calls) == 1                                               # one vtable, named once


def test_snapshot_reads_the_measured_fields():
    snap = R.snapshot(round_guest())
    p = snap["player"]
    assert p["hp"] == 1000 and p["hp_max"] == 1000 and p["pos"] == (0.0, 0.0, 0.0) and p["rot"] == 0.0
    assert p["motion"] == 0 and R.snapshot(round_guest(motion=106))["player"]["motion"] == 106
    assert snap["laser"] is None                                          # no laser sight unit in this guest
    assert snap["timer"] == 97.5 and snap["timer_start"] == 120.0 and snap["kills"] == 9 and snap["score"] == 3060
    assert snap["combo"] == 4 and snap["max_combo"] == 6 and snap["combo_timer"] == 8.5
    assert snap["mercenaries_phase"] == R.PHASE_PLAYING and snap["module_base"] == BASE
    assert [(e["hp"], e["hp_max"], e["pos"]) for e in snap["enemies"]] == [(800, 800, (300.0, 0.0, 500.0))]


def test_heading_follows_the_quaternion_and_the_atan2_dx_dz_convention():
    q = (0.0, math.sin(math.radians(45) / 2), 0.0, math.cos(math.radians(45) / 2))
    assert math.isclose(math.degrees(R.heading_of(q)), 45.0, abs_tol=1e-6)
    assert math.isclose(R.heading(1.0, 1.0), math.radians(45))


@pytest.mark.parametrize("phase,hp,player,want", [
    (R.PHASE_PLAYING, 1000, True, "playing"), (R.PHASE_PLAYING, 0, True, "dead"),
    (R.PHASE_INTRO, 1000, True, "loading"), (R.PHASE_OVER, 1000, True, "results"),
    (R.PHASE_OVER, 0, False, "results"), (R.PHASE_PLAYING, 0, False, "results"),   # Continue? No: the player is gone
    (R.PHASE_INTRO, 0, False, "loading")])
def test_round_screens(phase, hp, player, want):
    assert R.own_screen(R.snapshot(round_guest(phase=phase, hp=hp, player=player))) == want


def test_driver_screen_calls_a_stopped_clock_loading():
    clock = [0.0]
    d = R.RE5Switch(clock=lambda: clock[0])
    g = round_guest()
    assert d.screen(g, None) == "playing"
    clock[0] = R.HANG_S + 1
    assert d.screen(g, None) == "loading"


# --- menus -----------------------------------------------------------------------------------------------------------

MENU = {"uIdStartUp00": {R.MENU_CURSOR: 2}, "uIdStartUp01": {R.MENU_CURSOR: 0, R.MENU_SUB: 0},
        "uIdStartUp29": {R.MENU_SUB: 1, R.MODE_CURSOR: 0}, "uIdStartUp21": {R.MENU_CURSOR: 0},
        "uIdStartUp22": {R.PLAYER_CURSOR: 3}}


@pytest.mark.parametrize("unit,where,cursor,target,key", [
    ("uIdStartUp00", "main_menu", 2, 0, "dup"), ("uIdStartUp01", "play_game", 0, 1, "ddown"),
    ("uIdStartUp29", "mercs_mode", 0, 3, "ddown"), ("uIdStartUp21", "select_stage", 0, 0, "a"),
    ("uIdStartUp22", "select_player", 3, 0, "dleft")])
def test_native_menus_walk_to_no_mercy(unit, where, cursor, target, key):
    g = round_guest(phase=R.PHASE_OVER, player=False, units=((27, "uIdAlert00"), (28, unit)), cursors=MENU)
    scr = R.screen(g)
    assert (scr["where"], scr["cursor"], scr["target"]) == (where, cursor, target)
    assert R.step(scr) == key


def test_extra_content_and_the_mercenaries_title():
    cur = {"uIdStartUp01": {R.MENU_SUB: 2, R.EXTRA_CURSOR: 0}, "uIdStartUp29": {R.MENU_SUB: 0}}
    g = round_guest(phase=R.PHASE_OVER, player=False, units=((7, "uIdStartUp01"),), cursors=cur)
    scr = R.screen(g)
    assert (scr["where"], scr["cursor"], scr["target"]) == ("extra_content", 0, R.EXTRA_MERCENARIES) and R.step(scr) == "a"
    g = round_guest(phase=R.PHASE_OVER, player=False, units=((7, "uIdStartUp29"),), cursors=cur)
    assert R.screen(g)["where"] == "mercs_title" and R.step(R.screen(g)) == "a"


@pytest.mark.parametrize("aid,where,key", [(0x33, "alert_leaderboard", "b"), (0x09, "alert_ok", "a"),
                                           (0x08, "alert_ok", "a"), (0x77, "alert", "a")])
def test_dialogs(aid, where, key):
    g = round_guest(phase=R.PHASE_OVER, player=False, units=((1, "uIdAlert00"), (2, "uIdMerceEd00")),
                    cursors={"uIdAlert00": {R.ALERT_UP: 0xC0, R.ALERT_ID: aid}})
    scr = R.screen(g)
    assert scr["where"] == where and scr["alert_id"] == aid and R.step(scr) == key


def test_results_loading_dead_and_unknown():
    g = round_guest(phase=R.PHASE_OVER, player=False, units=((1, "uIdAlert00"), (2, "uIdMerceEd00")))
    assert R.screen(g)["where"] == "results" and R.step(R.screen(g)) == "plus"
    g = round_guest(phase=R.PHASE_INTRO, player=False, units=((29, "uIdNowLoading00"),))
    assert R.screen(g)["where"] == "loading" and R.step(R.screen(g)) is None
    g = round_guest(phase=R.PHASE_PLAYING, hp=0, units=((28, "uIdGameover00"),))
    assert R.screen(g)["where"] == "dead"
    g = round_guest(phase=R.PHASE_INTRO, player=False, units=((1, "uIdTitle00"),))
    assert R.screen(g)["where"] == "unknown" and R.BOOT_KEY == "a"
    g = round_guest()
    assert R.screen(g)["where"] == "playing"
    assert R.wandered({"where": "playing"}) is None


# --- the laser sight ---------------------------------------------------------------------------------------------------

def test_the_laser_sight_is_read_from_the_effects_line():
    g = round_guest(units=((R.LASER_LINE, "uEfCamDying"), (R.LASER_LINE, "uLaserSight")))
    u = R.laser_unit(g, BASE)
    assert R.class_name(g, u) == "uLaserSight"
    assert R.snapshot(g)["laser"] == {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0), "up": False}   # the gun down
    g.put(u + R.LASER_FROM, struct.pack("<3f", 10.0, 140.0, 40.0))
    g.put(u + R.LASER_DOT, struct.pack("<3f", 10.0, 120.0, 600.0))
    assert R.snapshot(g)["laser"] == {"from": (10.0, 140.0, 40.0), "at": (10.0, 120.0, 600.0), "up": True}
    su = R.u64(g, BASE + R.S_UNIT)
    g.q(su + R.UNIT_LINES + R.LINE_STRIDE * R.LASER_LINE, 0)
    assert R.laser_unit(g, BASE) == u                                     # cached: checked by its vtable, no walk
    g.q(u, g.klass("uEfBlood"))                                           # gone: looked for again ...
    assert R.laser_unit(g, BASE, now=100.0) is None
    g.q(su + R.UNIT_LINES + R.LINE_STRIDE * R.LASER_LINE, u)
    g.q(u, g.klass("uLaserSight"))
    assert R.laser_unit(g, BASE, now=100.1) is None                       # ... at most every LASER_RESCAN_S
    assert R.laser_unit(g, BASE, now=100.0 + R.LASER_RESCAN_S + 0.01) == u


def test_ray_geometry():
    o = (0.0, 140.0, 0.0)
    yaw, pitch = R.ray_error(o, (100.0, 140.0, 1000.0), (0.0, 110.0, 1000.0))
    assert yaw < 0 and pitch < 0                     # the dot is at a larger heading and level: rright, rdown
    foot = (0.0, 0.0, 1000.0)
    assert R.dot_on((10.0, 120.0, 990.0), foot) == "body" and R.dot_on((0.0, 160.0, 1000.0), foot) == "head"
    assert R.dot_on((0.0, 120.0, 1100.0), foot) is None and R.dot_on((60.0, 120.0, 1000.0), foot) is None
    assert R.through(o, (0.0, 100.0, 2000.0), foot)                       # the dot past him, the ray through him
    assert not R.through(o, (0.0, 120.0, 500.0), foot)                    # it ends short of him (a wall)
    assert not R.through(o, (400.0, 120.0, 2000.0), foot)                 # beside him


# --- the brain -------------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _switch_fight(monkeypatch):
    """These tests drive the Switch's own fight (re5_switch.Bot._decide), kept behind PS3_BRAIN = False until the RE5
    PS3 combat core (tests/test_re5_switch_brain.py) has proven itself live."""
    monkeypatch.setattr(R, "PS3_BRAIN", False)

OFF = {"from": (0.0, 0.0, 0.0), "at": (0.0, 0.0, 0.0), "up": False}


def ray(at, frm=(0.0, 140.0, 40.0)):
    return {"from": frm, "at": at, "up": True}


def bot_snap(enemy=(0.0, 0.0, 600.0), rot=0.0, laser=OFF, hp=1000, motion=0, ehp=800, more=()):
    enemies = ([{"ptr": 1, "pos": enemy, "hp": ehp, "hp_max": 800}] if enemy else []) + \
        [{"ptr": 2 + i, "pos": pos, "hp": 800, "hp_max": 800} for i, pos in enumerate(more)]
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": rot, "hp": hp, "hp_max": 1000, "motion": motion},
            "enemies": enemies, "laser": laser}


def snap_with(enemy, hp=1000, rot=0.0):
    """No motion byte and no laser unit: the bot's fallbacks (the health heuristic, the heading aim)."""
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": rot, "hp": hp, "hp_max": 1000},
            "enemies": [{"pos": enemy, "hp": 800, "hp_max": 800}] if enemy else []}


def brain():
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock


def test_bot_turns_raises_the_gun_and_closes_the_laser_on_his_chest():
    b, clock = brain()
    assert b.tick(bot_snap((600.0, 0.0, 0.0)))["hold"] == ("rleft",)      # +x is heading +90: rleft raises it
    clock[0] = 0.05
    assert b.tick(bot_snap())["hold"] == ("zl",)                         # faced: the gun comes up
    clock[0] = 0.3
    assert b.tick(bot_snap(laser=ray((-100.0, 110.0, 600.0))))["hold"] == ("rleft", "zl")   # off him: steer, no shot
    assert b.stats["shots"] == 0
    clock[0] = 0.35
    on = bot_snap(laser=ray((5.0, 110.0, 590.0)))                        # the dot on his body
    first, second = b.tick(on)["hold"], b.tick(dict(on, laser=ray((5.0, 111.0, 590.0))))["hold"]
    assert first == second == ("zl", "zr")                              # ZR held on him (the game repeats it), no stick
    assert b.stats["shots"] == 1 and "on body" in b.stats["aim"]         # one pull
    assert b.tick(bot_snap(laser=ray((-100.0, 110.0, 600.0))))["hold"] == ("rleft", "zl")   # off him: let go, steer


def test_bot_fires_through_him_but_not_into_a_wall_short_of_him():
    b, clock = brain()
    b.tick(bot_snap())
    clock[0] = 0.3
    assert "zr" in b.tick(bot_snap(laser=ray((0.0, 90.0, 1200.0))))["hold"]   # the dot past him: the ray runs through
    b, clock = brain()
    b.tick(bot_snap())
    clock[0] = 0.3
    assert "zr" not in b.tick(bot_snap(laser=ray((0.0, 120.0, 300.0))))["hold"]   # it ends on something in front


def test_bot_takes_the_majini_the_dot_is_on(monkeypatch):
    monkeypatch.setattr(R, "SMOOTH", True)                      # (with SMOOTH off the switch is immediate, as before)
    b, clock = brain()
    b.tick(bot_snap(more=((150.0, 0.0, 700.0),)))
    clock[0] = 0.3
    act = b.tick(bot_snap(more=((150.0, 0.0, 700.0),), laser=ray((140.0, 100.0, 690.0))))
    assert b.target != 2                                             # one tick under the dot: not yet (smoothness)
    clock[0] = 0.35
    act = b.tick(bot_snap(more=((150.0, 0.0, 700.0),), laser=ray((140.0, 100.0, 691.0))))
    assert "zr" in act["hold"] and b.target == 2 and b.stats["target_switches"] == 1


def test_bot_raises_the_gun_again_and_waits_out_a_reload():
    b, clock = brain()
    b.tick(bot_snap())
    clock[0] = R.LASER_WAIT_S + 0.1
    assert b.tick(bot_snap())["hold"] == () and b.stats["reraise"] == 1  # the laser never came up: ZL again
    b, clock = brain()
    b.tick(bot_snap())
    clock[0] = 5.0
    assert b.tick(bot_snap(motion=R.MOTION_RELOAD))["hold"] == ("zl",)  # reloading: no re-raise
    assert b.stats["reraise"] == 0


def test_bot_quick_turns_for_one_behind():
    b, clock = brain()
    assert b.tick(bot_snap((0.0, 0.0, -600.0)))["hold"] == ("ldown",)
    clock[0] = 0.05
    assert b.tick(bot_snap((0.0, 0.0, -600.0)))["hold"] == ("ldown", "b")
    clock[0] = 0.1
    assert b.tick(bot_snap((0.0, 0.0, -600.0)))["hold"] == ()
    clock[0] = 0.2
    assert b.tick(bot_snap((0.0, 0.0, -600.0)))["hold"] == ()            # it swings round by itself
    assert b.stats["quick_turns"] == 1


def test_bot_backs_off_one_in_front_only(monkeypatch):
    monkeypatch.setattr(R, "CLOSE_BACKOFF", True)                         # (off since rain fire: the gun goes up)
    b, clock = brain()
    assert b.tick(bot_snap((0.0, 0.0, 100.0)))["hold"][0] == "ldown" and b.stats["backoffs"] == 1
    b, clock = brain()
    assert b.tick(bot_snap((0.0, 0.0, -100.0)))["hold"] == ("ldown",)    # behind: the quick turn, not a back-off
    assert b.stats["backoffs"] == 0 and b.stats["quick_turns"] == 1


@pytest.mark.parametrize("snap,kind,pattern", [(bot_snap(motion=106), "holds", R.WIGGLE),
                                               (bot_snap(motion=113), "holds", R.WIGGLE),
                                               (bot_snap((0.0, 0.0, 8.0)), "holds", R.WIGGLE),
                                               (bot_snap(hp=1), "dying", R.MASH),
                                               (bot_snap(hp=1, motion=106), "dying", R.WIGGLE)])
def test_bot_breaks_free_when_held_and_resuscitates_when_dying(snap, kind, pattern):
    b, clock = brain()
    keys = {b.tick(snap)["hold"], b.tick(snap)["hold"]}
    assert keys == set(pattern) and b.stats[kind] == 1    # "Break free": the stick shaken; "Resuscitate": A mashed


def test_bot_breaks_free_when_the_stick_does_not_move_him():
    b, clock = brain()
    far = bot_snap((600.0, 0.0, 0.0))                                     # a turn he cannot make
    for k in range(12):
        clock[0] = 0.05 * k
        act = b.tick(far)
    assert act["hold"] in R.WIGGLE and b.stats["holds"] == 1


def test_bot_scores_its_hits():
    b, clock = brain()
    b.tick(bot_snap())
    clock[0] = 0.3
    b.tick(bot_snap(laser=ray((5.0, 110.0, 590.0))))
    clock[0] = 0.4
    b.tick(bot_snap(laser=ray((5.0, 111.0, 590.0)), ehp=640))            # his health fell while the trigger is held
    assert b.stats["shots"] == 1 and b.stats["hits"] == 1 and b.stats["trigger_s"] == 0.1
    assert b.stats["hits_per_trigger_s"] == 10.0
    clock[0] = 0.4 + R.HIT_S + 0.1
    b.tick(bot_snap((0.0, 0.0, 600.0), laser=ray((-100.0, 110.0, 600.0)), ehp=500))   # long after the trigger: not his
    assert b.stats["hits"] == 1


def test_bot_without_a_laser_unit_aims_by_heading():
    b, clock = brain()
    b.tick(snap_with((0.0, 0.0, 600.0)))
    clock[0] = 0.3
    first, second = b.tick(snap_with((0.0, 0.0, 600.0)))["hold"], b.tick(snap_with((0.0, 0.0, 600.0)))["hold"]
    assert first == second == ("zl", "zr") and b.stats["laserless"] == 2
    assert b.tick(snap_with((0.0, 0.0, 5000.0)))["hold"] == ("lup",)     # nobody in range: walk to him
    assert b.tick(snap_with(None))["hold"] == ()


def test_bot_answers_continue_by_the_cursor_in_ram_yes_for_the_pace():
    b, clock = brain()
    dead = lambda cursor: dict(bot_snap(hp=0), continue_cursor=cursor)
    assert b.tick(dead(None)) == {"hold": ()}                                 # the death animation
    clock[0] = R.DEAD_WAIT_S
    assert b.tick(dead(None)) == {"hold": ()}                                 # "Continue?" not up yet: no press
    assert b.tick(dead(R.CONTINUE_NO)) == {"tap": "dleft"}                    # on No: to Yes first, never A
    assert b.tick(dead(R.CONTINUE_YES)) == {"tap": "a"} and b.continued == "yes"   # Yes: the same round again


def test_bot_answers_continue_no_when_replays_are_off(monkeypatch):
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", False)
    b, clock = brain()
    dead = lambda cursor: dict(bot_snap(hp=0), continue_cursor=cursor)
    b.tick(dead(None))
    clock[0] = R.DEAD_WAIT_S
    assert b.tick(dead(R.CONTINUE_YES)) == {"tap": "dright"} and b.tick(dead(R.CONTINUE_NO)) == {"tap": "a"}
    assert b.continued == "no"


def test_a_replay_after_continue_yes_counts_as_the_next_round():
    b, clock = brain()
    alive = lambda timer: dict(bot_snap(), timer=timer, timer_start=120.0)
    b.tick(alive(80.0))
    first = b._round_started
    assert first == 0.0 and "deaths_continued" not in b.stats
    clock[0] = 1.0
    b.tick(dict(bot_snap(hp=0), continue_cursor=None))                       # he dies
    clock[0] = 1.0 + R.DEAD_WAIT_S
    b.tick(dict(bot_snap(hp=0), continue_cursor=R.CONTINUE_YES))              # Yes
    clock[0] = 20.0
    b.tick(alive(119.6))                                                      # the replay's first tick: a full clock
    assert b.stats["rounds"] == 1 and b.stats["deaths_continued"] == 1 and b.stats["round_start_via"] == "dead/retry"
    assert b._round_started == first        # set once: the death closed the round, the engine opens the replay's own
    clock[0] = 30.0
    b.tick(dict(bot_snap(hp=0), continue_cursor=None))                       # a death whose answer is not seen ...
    clock[0] = 40.0
    b.tick(alive(60.0))                                                       # ... and a clock far from full: no count
    assert b.stats["rounds"] == 1 and b._round_started == first


def test_the_continue_dialog_has_a_cursor_for_the_menus_walk():
    g = round_guest(phase=R.PHASE_PLAYING, hp=0, units=((28, "uIdGameover00"),))
    scr = R.screen(g)
    assert (scr["where"], scr["cursor"], scr["target"]) == ("dead", 0, R.CONTINUE_YES) and R.step(scr) == "a"
    u = R.ui_units(g)["uIdGameover00"]
    g.i32(u + R.CONTINUE_CURSOR, R.CONTINUE_NO)
    assert R.step(R.screen(g)) == "dleft" and R.snapshot(g)["continue_cursor"] == R.CONTINUE_NO
    assert "continue_cursor" not in R.snapshot(round_guest())                 # alive: no dialog read


def test_bot_breaks_free_and_answers_continue_no():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b.tick(snap_with((0.0, 0.0, 60.0), hp=900))
    clock[0] = 0.2
    act = b.tick(snap_with((0.0, 0.0, 60.0), hp=800))                         # health falling, one at arm's length
    assert act["hold"] in R.WIGGLE and b.stats["wiggles"] == 1
    clock[0] = 1.0 + R.BREAK_S
    assert b.tick(snap_with((0.0, 0.0, 60.0), hp=0)) == {"hold": ()}          # the death animation
    clock[0] = 1.0 + R.BREAK_S + R.DEAD_WAIT_S
    assert b.tick(snap_with(None, hp=0)) == {"tap": "dright"}                 # Continue? -> No ...
    assert b.tick(snap_with(None, hp=0)) == {"tap": "a"}                      # ... and confirm


# --- deployment ------------------------------------------------------------------------------------------------------

def test_the_ram_map_names_the_switch_driver_for_the_catalog_game():
    rm = ram_map.find({"game_id": "52d15709be0fda1a", "platform": "switch"})
    assert rm is not None and rm.id == R.MAP_ID == "010018100CD46000" and rm.platform == "switch"
    block = rm.spec["mercs"]
    assert block["driver"] == block["menus"] == "gbox.mercs.titles.re5_switch" and block["ready"] is True
    from gbox.mercs.driver import load
    assert isinstance(load(block), R.RE5Switch)


def test_mercs_bot_reads_an_eden_session_through_proc_mem_at_the_guest_address(monkeypatch, tmp_path):
    opened = []

    class FakeProcMem:
        def __init__(self, pid, base):
            opened.append((pid, base))
    monkeypatch.setattr(mercs_bot, "ProcMem", FakeProcMem)
    arena = {"lo": 0x1200000000, "hi": 0x5200000000, "base": 0x1200000000, "mapped": []}
    ad = SimpleNamespace(MEM="/proc/{pid}/mem", address_mode="direct", _guest=lambda: (77, arena))
    m = mercs_bot._memory(ad)
    assert opened == [(77, 0)] and m.adapter is ad                          # NCE: a guest address is the host one
    ad.address_mode = "offset"
    mercs_bot._memory(ad)
    assert opened[-1] == (77, 0x1200000000)                                  # Dynarmic: arena base + guest address


def test_menu_handoff_only_for_a_native_screen_in_ram():
    """A round that ended on "Save successful" (Continue? No) has no player: the engine must hand it to the menus,
    not call it lost (live in gBox on Citron 2026-10-26: mercs_bot stopped the run as hung)."""
    d = R.RE5Switch()
    save = round_guest(phase=R.PHASE_PLAYING, player=False, units=((1, "uIdAlert00"),),
                       cursors={"uIdAlert00": {R.ALERT_UP: 0xC0, R.ALERT_ID: 0x09}})
    assert d.screen(save, None) == "results" and d.menu_handoff(save, R.snapshot(save), "results") is True
    tally = round_guest(phase=R.PHASE_OVER, player=False, units=((2, "uIdMerceEd00"),))
    assert d.menu_handoff(tally, R.snapshot(tally), "results") is True
    blank = round_guest(phase=R.PHASE_OVER, player=False, units=())
    assert d.menu_handoff(blank, R.snapshot(blank), "results") is False        # nothing named: the lost watch runs
    assert d.menu_handoff(save, R.snapshot(save), "loading") is False


def test_result_ready_waits_for_a_still_tally_so_mercmode_can_count_a_completed_round():
    d = R.RE5Switch()
    snap = lambda score, kills=15: {"player": None, "score": score, "kills": kills, "timer": 0.0}
    assert callable(d.result_ready)                       # the engine's terminal witness: tally_ready = callable(...)
    assert d.result_ready(snap(5000), 0.0) is False       # the results just came up
    assert d.result_ready(snap(5100), 1.5) is False       # the score still counting up
    assert d.result_ready(snap(5100), 2.0) is False       # two seconds in, but changed half a second ago
    assert d.result_ready(snap(5100), 2.6) is True        # still for a second after two: final
    assert d.result_ready(snap(9000), 30.0) is False      # a later round's results (a gap): watched afresh
    for k in range(1, 32):                                 # a score that never settles ...
        last = d.result_ready(snap(9000 + k), 30.0 + 0.5 * k)
    assert last is True                                   # ... is final after fifteen seconds
