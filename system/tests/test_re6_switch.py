"""RE6 Switch Mercenaries driver (gbox.mercs.titles.re6_switch) on a fake 64-bit little-endian guest laid out like the
live measurements of 2026-10-26 (Citron NEO on the Spark): main found by its read-only signature, the round from
sGameMan / sPlayer / sEnemy, the camera (uCamera +0x60 / +0x80) and the laser sight (+0x60 dot, +0x440 muzzle), the
native menus from sUnit's interface units by vtable, and the brain's decisions."""
import json
import math
import struct
from pathlib import Path

import pytest

from gbox.mercs.titles import re6_switch as R

BASE = 0x3CA7C04000                      # the live runs' main base
HEAP = 0x5D00000000


class Guest:
    """Guest memory as two rows like the HostMemory ones (main's image, a heap): rd(a, n) inside them only."""
    MAIN_SIZE, HEAP_SIZE = 0x2B00000, 0x600000

    def __init__(self):
        self.regions = {BASE: bytearray(self.MAIN_SIZE), HEAP: bytearray(self.HEAP_SIZE)}
        self.next_heap = HEAP + 0x1000
        self.dtis: dict[str, int] = {}
        self.code = BASE + 0x100000      # getDTI functions
        self.names = BASE + 0x1800000    # class name strings
        self.dti_at = BASE + 0x1D00000   # the DTIs
        self.put(BASE + R.SIG_OFF, R.SIGNATURE)
        self.lines: dict[int, list[int]] = {}
        self.su = self.alloc(R.UNIT_LINES + R.LINE_STRIDE * R.N_LINES + 0x100)
        self.q(BASE + R.S_UNIT, self.su)

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

    def f32(self, a, *v):
        self.put(a, struct.pack(f"<{len(v)}f", *v))

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
        self.q(o, self.klass(name))
        return o

    def unit(self, line, name=None, vtable_off=None, size=0x800):
        """A unit appended to a move line: an interface unit by its real vtable offset, others by class."""
        u = self.alloc(size)
        self.q(u, BASE + vtable_off if vtable_off is not None else self.klass(name))
        chain = self.lines.setdefault(line, [])
        if chain:
            self.q(chain[-1] + R.UNIT_NEXT, u)
        else:
            self.q(self.su + R.UNIT_LINES + R.LINE_STRIDE * line, u)
        chain.append(u)
        return u


VT = {name: off for off, name in R.UNITS.items()}


def ui(g, line, name):
    return g.unit(line, vtable_off=VT[name])


@pytest.fixture(autouse=True)
def _fresh_caches():
    """The unit caches are per main base, and every fake guest here shares BASE."""
    for cache in (R._FOUND, R._MISS):
        cache.clear()
    R.TITLE.since = None
    yield


def round_guest(phase=R.PHASE_PLAYING, hp=900, timer=97.5, enemies=((300.0, 0.0, 500.0, 700),), player=True,
                state=0, ammo=18, cam_yaw=0.0, hud=True, laser=None, mode=R.MODE_NO_MERCY, tablets=8, guns=()):
    g = Guest()
    gm = g.obj("sGameMan", 0x8000)
    g.q(BASE + R.S_GAMEMAN, gm)
    g.i32(gm + R.GM_MODE, mode)
    g.i32(gm + R.GM_PHASE, phase)
    g.f32(gm + R.GM_TIMER, timer)
    g.i32(gm + R.GM_BONUS_S, 5)
    for off, v in ((R.GM_KILLS, 9), (R.GM_COMBO_ON, 1), (R.GM_COMBO, 2), (R.GM_MAX_COMBO, 7),
                   (R.GM_COMBO_BONUS, 40), (R.GM_SCORE, 4540), (R.GM_BASE, 2700)):
        g.i32(gm + off, v)
    g.f32(gm + R.GM_COMBO_T, 14.75)
    sp = g.obj("sPlayer", 0x5220)
    g.q(BASE + R.S_PLAYER, sp)
    if player:
        p = g.obj("uPl00LeonAsia", 0x8000)
        g.q(sp + R.P_FIRST, p)
        g.f32(p + R.P_POS, 0.0, 0.0, 0.0)
        g.f32(p + R.P_ROT, 0.0, 0.0, 0.0, 1.0)                 # heading 0: facing +z
        g.put(p + R.P_HP, struct.pack("<hh", hp, 900))
        g.put(p + R.P_AMMO, struct.pack("<h", ammo))
        g.put(p + R.P_STATE, bytes([state]))
        g.put(p + R.P_MOTION, struct.pack("<H", 4012 if state in R.HELD_STATES else 342))
        g.put(p + R.P_TABLETS, struct.pack("<h", tablets))
        from gbox.mercs.titles import re6_switch_mods as RM
        for i, (rounds, cap) in enumerate(guns):              # the inventory's cItem slots
            slot = p + RM.SLOTS + RM.SLOT_STRIDE * i
            g.q(slot, BASE + RM.SLOT_VTABLE)
            g.put(slot + RM.SLOT_ROUNDS, struct.pack("<h", rounds))
            g.put(slot + RM.SLOT_CAP, struct.pack("<h", cap))
        g.put(p + R.P_AMMO, struct.pack("<h", guns[0][0] if guns else ammo))
        cam = g.unit(14, "uCameraCtrl")                        # ~2 m behind him, looking along cam_yaw
        c = (-200 * math.sin(cam_yaw), 140.0, -200 * math.cos(cam_yaw))
        g.f32(cam + R.CAM_POS, *c)
        g.f32(cam + R.CAM_TARGET, c[0] + 300 * math.sin(cam_yaw), 140.0, c[2] + 300 * math.cos(cam_yaw))
        g.unit(8, "uCameraCtrl")                               # the idle one (0, 200, -700) far from him
        if laser is not None:
            lu = g.unit(22, "uLaserSight", size=0x600)
            g.f32(lu + R.LASER_DOT, *laser[0])
            g.f32(lu + R.LASER_FROM, *laser[1])
            g.f32(lu + R.LASER_UP, laser[2])
    se = g.obj("sEnemy", 0x870)
    g.q(BASE + R.S_ENEMY, se)
    arr = g.alloc(8 * max(1, len(enemies)))
    g.put(se + R.E_COUNT, struct.pack("<I", len(enemies)))
    g.q(se + R.E_ARRAY, arr)
    for i, (x, y, z, ehp) in enumerate(enemies):
        e = g.obj("uEm5200", 0x2000)
        g.q(arr + 8 * i, e)
        g.f32(e + R.E_POS, x, y, z)
        g.put(e + R.E_HP, struct.pack("<hh", ehp, 700))
    ui(g, 0, "uIdAlert00")
    if hud and player:
        ui(g, 18, "uIdMerceUI")
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


def test_class_name_refuses_garbage_vtables():
    g = round_guest()
    assert R.class_name(g, R.u64(g, BASE + R.S_PLAYER)) == "sPlayer"
    o = g.alloc(0x100)
    g.q(o, 0xFFFF_FFFF_FFFF_0000)                       # a vtable no pointer can be: no read past the guest
    assert R.class_name(g, o) is None


def test_snapshot_reads_the_measured_fields():
    g = round_guest(laser=((10.0, 150.0, 900.0), (25.0, 145.0, 40.0), 0.86))
    snap = R.snapshot(g)
    p = snap["player"]
    assert p["hp"] == 900 and p["hp_max"] == 900 and p["ammo"] == 18 and p["state"] == 0 and p["rot"] == 0.0
    assert snap["timer"] == 97.5 and snap["kills"] == 9 and snap["score"] == 4540 and snap["combo"] == 2
    assert snap["max_combo"] == 7 and snap["combo_timer"] == 14.75 and snap["base_points"] == 2700
    assert snap["mercenaries_phase"] == R.PHASE_PLAYING and snap["mercenaries_mode"] == "no_mercy"
    assert [(e["hp"], e["hp_max"], e["pos"]) for e in snap["enemies"]] == [(700, 700, (300.0, 0.0, 500.0))]
    cam = snap["camera"]
    assert math.isclose(cam["yaw"], 0.0, abs_tol=1e-6) and math.dist(cam["pos"], (0.0, 140.0, -200.0)) < 1e-3
    lz = snap["laser"]
    assert lz["up"] and lz["at"] == (10.0, 150.0, 900.0) and lz["from"] == (25.0, 145.0, 40.0)
    down = R.snapshot(round_guest(laser=((10.0, 150.0, 900.0), (25.0, 145.0, 40.0), 0.3)))["laser"]
    assert down["up"] is False                                           # the gun down: the dot is not the aim


def test_the_camera_is_the_live_one_near_him_and_yaw_follows_its_target():
    g = round_guest(cam_yaw=math.radians(-124.6))
    cam = R.snapshot(g)["camera"]
    assert math.isclose(math.degrees(cam["yaw"]), -124.6, abs_tol=0.01)
    assert math.dist(cam["pos"], (0.0, 0.0, 0.0)) < R.CAM_NEAR                # not the idle (0, 200, -700) one


@pytest.mark.parametrize("phase,hp,hud,want", [
    (R.PHASE_PLAYING, 900, True, "playing"), (R.PHASE_PLAYING, 0, True, "dead"),
    (R.PHASE_OVER, 900, True, "loading"), (R.PHASE_PLAYING, 900, False, "loading")])
def test_round_screens(phase, hp, hud, want):
    assert R.screen(round_guest(phase=phase, hp=hp, hud=hud))["where"] == want


def test_dead_and_results_units_name_their_screens(monkeypatch):
    g = round_guest()
    over = ui(g, 18, "uIdGameover00")
    scr = R.screen(g)
    assert scr["where"] == "dead" and scr["cursor"] is None and R.step(scr) is None   # not taking input yet
    g.q(over + R.CONTINUE_MENU, g.alloc(0x100))                                      # its YES / NO menu is up
    scr = R.screen(g)
    assert scr["cursor"] == 0 and scr["target"] == R.CONTINUE_YES and R.step(scr) == "a"   # the pace: YES at once
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", False)                                 # switched off: NO
    assert R.step(R.screen(g)) == "dright"
    g.i32(over + R.CONTINUE_CURSOR, R.CONTINUE_NO)
    scr = R.screen(g)
    assert scr["cursor"] == 1 and scr["target"] == 1 and R.step(scr) == "a"
    g = round_guest(player=False, phase=R.PHASE_OVER)
    ui(g, 18, "uIdResult30")
    assert R.screen(g)["where"] == "results" and R.step(R.screen(g)) == "plus"     # (+) End game


@pytest.mark.parametrize("aid,where,key", [(0x41, "alert_leaderboard", "b"), (0x09, "alert_ok", "a"),
                                           (0x08, "alert_ok", "a"), (0x0F, "alert_ok", "a"),
                                           (0x0C, "alert_wait", None), (0x0D, "alert_wait", None),
                                           (0x02, "alert_ok", "a"),     # no save yet (gBox's Citron home): create it
                                           (0x2A, "alert", "b")])       # any other dialog: declined, never confirmed
def test_dialogs_by_their_id(aid, where, key):
    g = round_guest(player=False)
    alert = g.lines[0][0]
    g.i32(alert + R.ALERT_ID, aid)
    g.i32(alert + R.ALERT_UP, 1)
    scr = R.screen(g)
    assert scr["where"] == where and scr["alert_id"] == aid and R.step(scr) == key


def menu_guest(name, offset=None, value=0, extra=None, mode=R.MODE_NO_MERCY):
    g = round_guest(player=False, mode=mode)
    u = ui(g, 18, name)
    if offset is not None:
        g.i32(u + offset, value)
    for off, v in (extra or {}).items():
        g.i32(u + off, v)
    return g


@pytest.mark.parametrize("name,offset,value,where,target,key", [
    ("uIdStartUp00", R.MENU_CURSOR, 3, "main_menu", 0, "dup"),
    ("uIdStartUp01", R.MENU_CURSOR, 0, "play_game", 3, "ddown"),
    ("uIdStartUp30", R.MENU_CURSOR, 0, "mercs_mode", 0, "a"),
    ("uIdStartUp31", R.MENU_CURSOR, 2, "select_stage", 0, "dup"),
    ("uIdStartUp32", R.PLAYER_CURSOR, 0, "select_player", 1, "ddown"),     # Chris: the automatic rifle
    ("uIdStartUp32", R.PLAYER_CURSOR, 1, "select_player", 1, "a")])
def test_menus_walk_to_no_mercy(name, offset, value, where, target, key):
    scr = R.screen(menu_guest(name, offset, value))
    assert (scr["where"], scr["cursor"], scr["target"]) == (where, value, target) and R.step(scr) == key


def test_the_character_select_finds_chris_by_his_id_as_the_list_grows():
    # a fresh save lists Leon 0, Chris 2, Jake 4, Agent 8 (index 1 = Chris); once Helena (1) unlocks she takes index 1
    # (live 2026-10-27: the second walk picked uPl01HelenaAsia at index 1) and Chris moves to index 2
    for ids, want in (((0, 2, 4, 8), 1), ((0, 1, 2, 4, 8), 2), ((0, 1, 2, 3, 4, 5, 6, 8), 2), ((0, 4, 8), R.PLAYER_TARGET)):
        g = menu_guest("uIdStartUp32", R.PLAYER_CURSOR, 0)
        u = g.lines[18][-1]
        g.i32(u + R.PLAYER_COUNT, len(ids))
        for i, cid in enumerate(ids):
            g.i32(u + R.PLAYER_IDS + 4 * i, cid)
        scr = R.screen(g)
        assert scr["where"] == "select_player" and scr["target"] == want


def test_extra_content_targets_no_mercy_by_its_mode_id():
    modes = {R.EXTRA_COUNT: 7, **{R.EXTRA_MODES + 4 * i: m for i, m in enumerate((0, 1, 2, 3, 4, 5, 6))}}
    scr = R.screen(menu_guest("uIdStartUp02", R.MENU_CURSOR, 0, modes))
    assert scr["where"] == "extra_content" and scr["target"] == 2 and R.step(scr) == "ddown"
    shuffled = {R.EXTRA_COUNT: 3, R.EXTRA_MODES: 1, R.EXTRA_MODES + 4: 2, R.EXTRA_MODES + 8: 0}
    scr = R.screen(menu_guest("uIdStartUp02", R.MENU_CURSOR, 1, shuffled))
    assert scr["target"] == 1 and R.step(scr) == "a"


def test_the_mercenaries_menu_of_the_wrong_mode_backs_out():
    scr = R.screen(menu_guest("uIdStartUp30", R.MENU_CURSOR, 0, mode=R.MODE_MERCENARIES))
    assert scr["where"] == "mercs_wrong_mode" and R.step(scr) == "b"


def test_the_title_waits_for_its_main_menu_byte_then_gives_up_with_a_reason():
    g = round_guest(player=False)
    title = ui(g, 0, "uIdTitle00")
    scr = R.screen(g, now=0.0)
    assert scr["where"] == "title_locked" and R.step(scr) is None and R.wandered(scr) is None
    late = R.screen(g, now=R.TITLE_STUCK_S + 1)
    assert "Prologue" in R.wandered(late)
    g.put(title + R.TITLE_MENU_OPEN, b"\x01")
    scr = R.screen(g, now=R.TITLE_STUCK_S + 2)
    assert scr["where"] == "title" and R.step(scr) == "a" and R.wandered(scr) is None


def test_driver_screen_calls_a_stopped_clock_loading_and_hands_menus_back():
    clock = [0.0]
    d = R.RE6Switch(clock=lambda: clock[0])
    g = round_guest()
    assert d.screen(g, None) == "playing"
    clock[0] = R.HANG_S + 1
    assert d.screen(g, None) == "loading"
    menus = menu_guest("uIdStartUp31", R.MENU_CURSOR, 0)
    assert d.screen(menus, None) == "results" and d.menu_handoff(menus, {}, "results") is True
    assert d.menu_handoff(g, {}, "playing") is False


# --- the brain -------------------------------------------------------------------------------------------------------

def run(bot, snap, clock, ticks, dt=0.05):
    out = []
    for _ in range(ticks):
        clock[0] += dt
        out.append(bot.tick(snap))
    return out


def brain(snap_guest):
    clock = [0.0]
    return R.Bot(stats={}, clock=lambda: clock[0]), clock, R.snapshot(snap_guest)


def test_it_aims_along_the_laser_and_fires_when_the_dot_is_on_him():
    on = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.86)          # the dot on his chest
    bot, clock, snap = brain(round_guest(enemies=((300.0, 0.0, 500.0, 700),), cam_yaw=math.atan2(300, 500), laser=on))
    acts = run(bot, snap, clock, 12)
    assert all("zl" in a["hold"] for a in acts)
    assert any("zr" in a["hold"] for a in acts) and bot.stats["shots"] >= 2


def test_it_steers_the_aim_toward_him_with_the_right_stick():
    short_of_him = ((150.0, R.CHEST_H, 520.0), (20.0, 145.0, 30.0), 0.86)  # he stands at a larger heading
    bot, clock, snap = brain(round_guest(enemies=((300.0, 0.0, 500.0, 700),), cam_yaw=math.atan2(300, 500),
                                         laser=short_of_him))
    acts = run(bot, snap, clock, 10)
    keys = set().union(*(set(a["hold"]) for a in acts))
    assert "rleft" in keys and "rright" not in keys and "zr" not in keys


def test_the_camera_turns_to_one_off_to_the_side_with_the_gun_down():
    bot, clock, snap = brain(round_guest(enemies=((-900.0, 0.0, 300.0, 700),), cam_yaw=0.0))
    act = run(bot, snap, clock, 1)[0]
    assert act["hold"] == ("rright",) and bot.stats["turns"] == 1          # a smaller yaw: the right stick right


def test_the_quick_turn_for_one_behind():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, -900.0, 700),), cam_yaw=0.0))
    acts = run(bot, snap, clock, 4)
    assert acts[0]["hold"] == ("ldown",) and set(acts[1]["hold"]) == {"b", "ldown"} and bot.stats["quick_turns"] == 1


def test_melee_for_one_at_arms_length_and_the_quick_shot_for_one_close():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 100.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] == {"tap": "zr"} and bot.stats["melee"] == 1
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 380.0, 700),), cam_yaw=0.0))
    acts = run(bot, snap, clock, 2)
    assert acts[0]["hold"] == ("zl", "zr") and acts[1]["hold"] == () and bot.stats["quick_shots"] == 1


def test_far_away_it_walks_along_the_camera():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 3000.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0]["hold"] == ("lup",)


def test_a_hold_read_in_ram_is_shaken_off():
    bot, clock, snap = brain(round_guest(state=8))
    acts = run(bot, snap, clock, 4)
    assert [a["hold"] for a in acts] == [R.WIGGLE[i % len(R.WIGGLE)] for i in range(1, 5)] and bot.stats["holds"] == 1
    assert {k for chord in R.WIGGLE for k in chord} == {"lup", "lright", "ldown", "lleft", "b"}   # round, B mashed


def test_dead_it_answers_continue_yes_by_the_cursor_and_counts_the_replay(monkeypatch):
    g = round_guest(hp=0)
    over = ui(g, 18, "uIdGameover00")
    bot, clock, snap = brain(g)
    assert snap["continue_cursor"] is None                       # the dialog is not taking input yet
    acts = run(bot, snap, clock, int(R.DEAD_WAIT_S / 0.05) + 2)
    assert all(a == {"hold": ()} for a in acts) and bot.stats["deaths"] == 1
    g.q(over + R.CONTINUE_MENU, g.alloc(0x100))
    g.i32(over + R.CONTINUE_CURSOR, R.CONTINUE_NO)
    snap = R.snapshot(g)
    assert snap["continue_cursor"] == 1 and run(bot, snap, clock, 1)[0] == {"tap": "dleft"}   # to YES first
    g.i32(over + R.CONTINUE_CURSOR, R.CONTINUE_YES)
    assert run(bot, R.snapshot(g), clock, 1)[0] == {"tap": "a"} and bot.continued == "yes"
    alive = R.snapshot(round_guest(timer=119.4))                 # the replay's first tick alive: a full clock
    run(bot, alive, clock, 1)
    assert bot.stats["rounds"] == 1 and bot.stats["deaths_continued"] == 1
    assert bot.stats["round_start_via"] == "dead/retry" and bot._round_started == clock[0]


def test_a_continue_no_or_a_far_clock_is_not_counted_as_a_replay(monkeypatch):
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", False)
    g = round_guest(hp=0)
    over = ui(g, 18, "uIdGameover00")
    g.q(over + R.CONTINUE_MENU, g.alloc(0x100))
    g.i32(over + R.CONTINUE_CURSOR, R.CONTINUE_NO)
    bot, clock, snap = brain(g)
    run(bot, snap, clock, int(R.DEAD_WAIT_S / 0.05) + 2)
    assert bot.continued == "no"
    run(bot, R.snapshot(round_guest(timer=119.4)), clock, 1)
    assert bot.stats.get("rounds", 0) == 0                       # the menus count a round reached through them
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", True)
    bot, clock, _ = brain(g)
    bot.died, bot.continued = True, "yes"
    run(bot, R.snapshot(round_guest(timer=90.0)), clock, 1)     # alive with a clock far from full: not a new round
    assert bot.stats.get("rounds", 0) == 0


def test_an_empty_gun_reloads():
    on = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap = brain(round_guest(ammo=0, cam_yaw=math.atan2(300, 500), laser=on))
    acts = run(bot, snap, clock, 6)
    assert any("y" in a["hold"] for a in acts) and bot.stats["reloads"] == 1


def test_hits_count_when_his_health_falls_after_a_shot():
    on = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.86)
    g = round_guest(cam_yaw=math.atan2(300, 500), laser=on)
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 6)
    assert bot.stats["shots"] >= 1
    snap["enemies"][0]["hp"] = 550
    run(bot, snap, clock, 1)
    assert bot.stats["hits"] == 1 and 0 < bot.stats["accuracy"] <= 1


# --- the map ---------------------------------------------------------------------------------------------------------

def test_the_ram_map_names_this_driver_for_the_catalog_game():
    spec = json.loads((Path(__file__).resolve().parents[1] / "profiles/gamedata/01002A000CD48000-ram.json")
                      .read_text(encoding="utf-8"))
    assert spec["id"] == R.TITLE_ID and spec["platform"] == "switch"
    assert spec["match"]["game_ids"] == ["115f9cdbba115432"]
    merc = spec["mercs"]
    assert merc["driver"] == merc["menus"] == "gbox.mercs.titles.re6_switch" and merc["ready"] is True
    assert merc["rules"]["mode"] == "no_mercy"
    from gbox.mercs import driver as D
    assert isinstance(D.load(merc), R.RE6Switch)


def test_a_tablet_at_half_health_with_nobody_close_and_at_a_third_regardless():
    bot, clock, snap = brain(round_guest(hp=400, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"} and bot.stats["tablet_presses"] == 1
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # one a TABLET_GAP_S
    bot, clock, snap = brain(round_guest(hp=400, enemies=((0.0, 0.0, 120.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # one at arm's length: fight first
    bot, clock, snap = brain(round_guest(hp=300, enemies=((0.0, 0.0, 120.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}                       # a third left: a tablet anyway
    bot, clock, snap = brain(round_guest(hp=400, tablets=0, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"} and bot.stats["tablets"] == 0
    bot, clock, snap = brain(round_guest(hp=1, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # dying: no tablet (not measured)
    bot, clock, snap = brain(round_guest(hp=300, state=1, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert {"tap": "r"} not in run(bot, snap, clock, 3)                      # being hit: R would be ignored


def test_a_tablet_counts_once_the_count_falls_and_an_ignored_press_is_pressed_again():
    g = round_guest(hp=400, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0)
    bot, clock, snap = brain(g)
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}
    snap["player"]["tablets"] = 7                                            # the press took one
    run(bot, snap, clock, 1)
    assert bot.stats["tablets"] == 1 and bot.stats["tablet_misses"] == 0
    clock[0] += R.TABLET_GAP_S
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"} and bot.stats["tablet_presses"] == 2
    acts = run(bot, snap, clock, int(R.TABLET_CONFIRM_S / 0.05) + 2)       # the count stays at 7: ignored
    assert bot.stats["tablet_misses"] == 1 and bot.stats["tablets"] == 1
    assert acts.count({"tap": "r"}) == 1 and acts[0] != {"tap": "r"}        # pressed again once the miss is known
    assert bot.stats["tablet_presses"] == 3


def test_a_gun_that_does_not_come_up_keeps_aiming_along_the_camera_and_looks_for_the_laser_again():
    down = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.3)            # the laser unit, but the gun not up
    bot, clock, snap = brain(round_guest(enemies=((300.0, 0.0, 500.0, 700),), cam_yaw=math.atan2(300, 500),
                                         laser=down))
    R._FOUND[(BASE, "laser")] = (1, 2)
    acts = run(bot, snap, clock, int(R.LASER_WAIT_S / 0.05) + 4)
    assert bot.stats["reraise"] == 1 and (BASE, "laser") not in R._FOUND
    assert all("zl" in a["hold"] for a in acts)                              # the gun never went down for it
    assert "zr" in acts[-1]["hold"] or "zr" in acts[-2]["hold"]             # the camera's line runs through him: fire
    assert bot.stats["aim"].endswith(("keys rleft,zl,zr", "keys zl,zr")) or "via camera" in bot.stats["aim"]


# --- the live mods ---------------------------------------------------------------------------------------------------

class Adapter:
    """A Citron adapter over the fake guest: read_memory / write_memory (read back) and its HostMemory rows."""

    def __init__(self, g):
        self.g, self.writes, self.address_mode = g, [], "direct"

    def read_memory(self, a, n):
        return self.g.rd(a, n)

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        self.g.put(a, bytes(data))
        return {"verified": True}

    def _guest(self):
        return 1, {"base": 0, "mapped": self.g.rows()}


@pytest.fixture
def mods():
    from gbox.mercs.titles import re6_switch_mods as RM
    RM.ORIG.clear()
    yield RM
    RM.ORIG.clear()


def test_infinite_ammo_tops_every_gun_up_to_its_capacity(mods):
    g = round_guest(guns=((15, 18), (3, 8), (0, 0)))                         # the Wing Shooter, a shotgun, a knife
    ad = Adapter(g)
    out = mods.run(ad, "infinite_ammo", on=True)
    assert out["verified"] and out["topped_up"] == 2
    p = R.snapshot(g)["player"]
    assert [(r, c) for _, r, c in mods.RE6Switch(ad).slots(p["ptr"])] == [(18, 18), (8, 8)]
    assert p["ammo"] == 18
    slot = p["ptr"] + mods.SLOTS
    g.put(slot + mods.SLOT_ROUNDS, struct.pack("<h", 12))                    # three shots later
    clock = [10.0]
    res = mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert res["active"] and res["writes"] == 1 and R.snapshot(g)["player"]["ammo"] == 18
    g.put(slot + mods.SLOT_ROUNDS, struct.pack("<h", 12))
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 0   # at most every CHECK_S
    clock[0] += mods.CHECK_S
    assert mods.maintain(ad, R.snapshot(g), enabled=False, clock=lambda: clock[0])["writes"] == 0   # out of a round
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 1


def test_infinite_ammo_leaves_the_item_slots_alone(mods):
    g = round_guest(guns=((20, 30), (7, 7)), tablets=3)                    # Chris: the rifle and a 7-round gun
    p = R.snapshot(g)["player"]["ptr"]
    for i in range(2, mods.N_SLOTS):                                        # the rest of the 12 cItem slots
        g.q(p + mods.SLOTS + mods.SLOT_STRIDE * i, BASE + mods.SLOT_VTABLE)
    item = lambda i: p + mods.SLOTS + mods.SLOT_STRIDE * i
    g.put(item(7) + mods.SLOT_CAP, struct.pack("<h", 12))                  # the tablets: 3 of 12 (P_TABLETS)
    g.put(item(9) + mods.SLOT_ROUNDS, struct.pack("<hhhh", 3, 0, 0, 5))    # an item at 3 of 5
    ad = Adapter(g)
    assert mods.run(ad, "infinite_ammo", on=True)["topped_up"] == 1
    assert [(r, c) for _, r, c in mods.RE6Switch(ad).slots(p)] == [(30, 30), (7, 7)]
    assert R.snapshot(g)["player"]["tablets"] == 3 and struct.unpack("<h", g.rd(item(9) + mods.SLOT_ROUNDS, 2))[0] == 3


def tablet_case(g, count, obj=0x5D612FC0F0, cid=0x1D, used=1, index=7):
    """The tablet case's cItem slot (Chris: slot 7, id 0x1D, 0 / 12, its item object set)."""
    from gbox.mercs.titles import re6_switch_mods as RM
    p = R.snapshot(g)["player"]["ptr"]
    for i in range(RM.N_SLOTS):                                             # every slot a cItem, as in the game
        g.q(p + RM.SLOTS + RM.SLOT_STRIDE * i, BASE + RM.SLOT_VTABLE)
    slot = p + RM.SLOTS + RM.SLOT_STRIDE * index
    g.put(slot + RM.SLOT_USED, bytes([used, index, cid]))
    g.put(slot + RM.SLOT_ROUNDS, struct.pack("<h", count))
    g.put(slot + RM.SLOT_CAP, struct.pack("<h", 12))
    g.q(slot + RM.SLOT_OBJ, obj)
    return slot


def test_infinite_tablets_keeps_the_case_counted_only_in_its_live_slot(mods):
    g = round_guest(guns=((30, 30),))
    slot = tablet_case(g, 0)                                                # Chris starts with none
    ad = Adapter(g)
    out = mods.run(ad, "infinite_tablets", on=True)
    assert out["verified"] and out["kept"] == 1 and R.snapshot(g)["player"]["tablets"] == mods.TABLET_KEEP
    assert ad.writes == [(slot + mods.SLOT_ROUNDS, struct.pack("<h", mods.TABLET_KEEP))]   # the count's s16, nothing else
    g.put(slot + mods.SLOT_ROUNDS, struct.pack("<h", mods.TABLET_KEEP - 1))            # a tablet taken
    clock = [10.0]
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 1
    assert R.snapshot(g)["player"]["tablets"] == mods.TABLET_KEEP
    assert mods.run(ad, "status")["tablets"] == {"count": mods.TABLET_KEEP, "capacity": 12}
    for kw in ({"obj": 0}, {"cid": 0x20}, {"used": 0}):                      # no live tablet slot: nothing written
        g2 = round_guest()
        tablet_case(g2, 2, **kw)
        ad2 = Adapter(g2)
        mods.ORIG.clear()
        assert mods.run(ad2, "infinite_tablets", on=True)["kept"] == 0 and ad2.writes == []
    g3 = round_guest()
    tablet_case(g3, 8)                                                      # Leon's 8: above the keep, left alone
    ad3 = Adapter(g3)
    mods.ORIG.clear()
    assert mods.run(ad3, "tablets", on=True)["kept"] == 0 and ad3.writes == []


def test_infinite_ammo_off_writes_nothing_and_status_reports(mods):
    g = round_guest(guns=((10, 18),))
    ad = Adapter(g)
    mods.run(ad, "infinite_ammo", on=False)
    assert mods.maintain(ad, R.snapshot(g))["writes"] == 0 and ad.writes == []
    st = mods.run(ad, "status")
    assert st["infinite_ammo"] is False and st["guns"] == [{"rounds": 10, "capacity": 18}] and st["in_hand_rounds"] == 10


def test_fire_rate_is_honest_about_no_game_side_multiplier(mods):
    ad = Adapter(round_guest())
    assert mods.run(ad, "fire_rate", multiplier=80)["verified"] is False
    assert mods.run(ad, "rapid_fire", on=False)["fire_rate_x"] == 1.0
    with pytest.raises(ValueError):
        mods.run(ad, "fire_rate", multiplier=500)
    with pytest.raises(ValueError):
        mods.run(ad, "blast")


def test_the_driver_keeps_the_magazines_full_while_playing(mods):
    g = round_guest(guns=((10, 18),))
    ad = Adapter(g)
    g.adapter = ad
    mods.run(ad, "infinite_ammo", on=True)
    g.put(R.snapshot(g)["player"]["ptr"] + mods.SLOTS + mods.SLOT_ROUNDS, struct.pack("<h", 4))
    mods.ORIG[id(ad)]["ammo_at"] = -1e9
    d = R.RE6Switch()
    d.brain(g, {}, lambda: 0.0)
    assert d.screen(g, None) == "playing" and R.snapshot(g)["player"]["ammo"] == 18 and d.stats["mod_writes"] == 1


def test_apply_ops_dispatches_the_re6_switch_profile(mods, monkeypatch):
    from gbox import mercs_bot
    g = round_guest(guns=((10, 18),))
    ad = Adapter(g)
    failed = mercs_bot.apply_ops(ad, [("infinite_ammo", {"on": True})], {"map_id": R.MAP_ID, "platform": "switch"})
    assert failed == [] and mods.ORIG[id(ad)]["infinite_ammo"] is True


def test_a_yes_replays_load_stays_inside_the_round_and_no_goes_to_the_menus():
    clock = [0.0]
    d = R.RE6Switch(clock=lambda: clock[0])
    dead = round_guest(hp=0)
    ui(dead, 18, "uIdGameover00")
    assert d.screen(dead, None) == "dead"
    loading = round_guest(player=False)                         # the replay's load: no player, no dialog
    clock[0] = 8.0
    assert d.screen(loading, None) == "dead"                    # the engine keeps the round (no "lost" clock)
    clock[0] = 8.0 + R.REPLAY_LOAD_S
    assert d.screen(loading, None) == "loading"                 # too long: the engine's own lost rule again
    d = R.RE6Switch(clock=lambda: clock[0])
    assert d.screen(dead, None) == "dead"
    saving = round_guest(player=False)
    alert = saving.lines[0][0]
    saving.i32(alert + R.ALERT_ID, 0x0C)
    saving.i32(alert + R.ALERT_UP, 1)
    assert d.screen(saving, None) == "results" and d.menu_handoff(saving, {}, "results")   # NO: "Now saving"


def test_a_stale_camera_or_laser_after_a_replay_is_looked_up_again():
    g = round_guest(cam_yaw=math.radians(30), laser=((10.0, 150.0, 900.0), (25.0, 145.0, 40.0), 0.86))
    first = R.snapshot(g)["camera"]["unit"]
    g.f32(first + R.CAM_POS, 0.0, 200.0, -700.0)               # the round's camera freed, another one at its address
    fresh = g.unit(14, "uCameraCtrl")
    g.f32(fresh + R.CAM_POS, 0.0, 140.0, -200.0)
    g.f32(fresh + R.CAM_TARGET, 0.0, 140.0, 100.0)
    R._MISS.clear()
    cam = R.snapshot(g)["camera"]
    assert cam["unit"] == fresh and math.isclose(cam["yaw"], 0.0, abs_tol=1e-6)
    lu = g.lines[22][0]
    g.f32(lu + R.LASER_FROM, 5000.0, 145.0, 5000.0)             # a muzzle nowhere near him: not his laser
    assert R.snapshot(g)["laser"]["up"] is False and (BASE, "laser") not in R._FOUND


def test_a_crowd_close_by_is_fired_on_while_he_steps_back():
    crowd = ((100.0, 0.0, 200.0, 700), (-120.0, 0.0, 200.0, 700), (0.0, 0.0, 900.0, 700))   # two within CROWD_R
    on = ((100.0, R.CHEST_H, 200.0), (20.0, 145.0, 30.0), 0.86)              # the dot on the near one's chest
    bot, clock, snap = brain(round_guest(enemies=crowd, cam_yaw=math.atan2(100, 200), laser=on))
    acts = run(bot, snap, clock, 10)
    assert acts[0] == {"hold": ("zl", "zr")} and bot.stats["quick_shots"] == 1   # the close one: the quick shot first
    assert all("ldown" in a.get("hold", ()) for a in acts[2:]) and bot.stats["backoffs"] == 1   # stepping back ...
    assert all("zl" in a.get("hold", ()) for a in acts[2:])                  # ... with the gun up
    assert sum("zr" in a.get("hold", ()) for a in acts[2:]) >= 2 and bot.stats["t_fire"] > 0    # ... and firing


def test_time_up_closes_the_round_and_the_tally_is_read_before_the_boundary():
    clock = [0.0]
    d = R.RE6Switch(clock=lambda: clock[0])
    over = round_guest(phase=R.PHASE_OVER, timer=0.0)
    assert R.screen(over)["where"] == "loading" and R.step(R.screen(over)) is None   # the menus press nothing yet
    assert d.screen(over, None) == "results"                                        # the engine: the round is over
    snap = R.snapshot(over)
    assert d.result_ready(snap, 0.0) is False
    assert d.result_ready(snap, 1.5) is False
    assert d.result_ready(snap, 2.1) is True                                         # held still past 2 s
    d2 = R.RE6Switch(clock=lambda: clock[0])
    res = round_guest(player=False, phase=R.PHASE_OVER, timer=0.0)
    ui(res, 18, "uIdResult30")
    assert d2.screen(res, None) == "results" and d2.result_ready(R.snapshot(res), 0.0) is True


def test_one_closing_in_while_he_aims_is_backed_away_from_with_the_gun_up():
    on = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.86)
    g = round_guest(enemies=((300.0, 0.0, 500.0, 700),), cam_yaw=math.atan2(300, 500), laser=on)
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 6)
    assert bot.aim_since is not None                                   # aiming at the far one
    snap["enemies"].append({"slot": 1, "ptr": 99, "pos": (20.0, 0.0, 90.0), "hp": 700, "hp_max": 700})
    act = run(bot, snap, clock, 1)[0]
    assert "zl" in act["hold"] and "ldown" in act["hold"] and bot.stats["melee"] == 0   # gun up, a step back


def test_warm_probe_names_stable_native_menus_and_waits_for_an_open_title():
    g = round_guest(player=False)
    assert R.warm_probe(g) == {"ready": False, "screen": "unknown", "title": R.MAP_ID}
    title = ui(g, 0, "uIdTitle00")
    assert R.warm_probe(g)["screen"] == "title_locked" and not R.warm_probe(g)["ready"]
    g.put(title + R.TITLE_MENU_OPEN, b"\x01")
    probe = R.warm_probe(g)
    assert probe["ready"] and probe["screen"] == "title" and probe["token"] == ("uIdTitle00", title)
    menu = ui(g, 18, "uIdStartUp31")
    probe = R.warm_probe(g)
    assert probe["ready"] and probe["screen"] == "select_stage" and probe["token"] == ("uIdStartUp31", menu)
    g = round_guest(player=False)
    alert = g.lines[0][0]
    g.i32(alert + R.ALERT_ID, 0x08)
    g.i32(alert + R.ALERT_UP, 1)
    assert R.warm_probe(g)["screen"] == "alert_ok" and R.warm_probe(g)["ready"]


def test_the_boots_press_any_button_is_a_warm_stop_and_a_press_of_a_for_the_menus():
    # live 2026-10-27 on lilspark: a warm prelaunch (no input) waits on the sign-in's PRESS ANY BUTTON - line 0 held
    # uIdScreen, uIdAlert00 (down), uIdNetMsg00 and uIdSignIn00 - which neither the probe nor the menus named, so the
    # first two RE6 prelaunches timed out after 600 s and were closed
    g = round_guest(player=False)
    signin = ui(g, 0, "uIdSignIn00")
    probe = R.warm_probe(g)
    assert probe["ready"] and probe["screen"] == "press_any_button" and probe["token"] == ("uIdSignIn00", signin)
    scr = R.screen(g)
    assert scr["where"] == "press_any_button" and R.step(scr) == "a" and R.wandered(scr) is None
    title = ui(g, 0, "uIdTitle00")                                           # the title after the load comes first
    assert R.warm_probe(g)["screen"] == "title_locked" and not R.warm_probe(g)["ready"]
    assert R.screen(g)["where"] == "title_locked" and R.step(R.screen(g)) is None   # never A on a locked title
    g.put(title + R.TITLE_MENU_OPEN, b"")
    assert R.warm_probe(g)["screen"] == "title" and R.screen(g)["where"] == "title"


def test_the_warm_pool_finds_the_re6_reader_from_the_catalog_game():
    from gbox.mercs import warm_boot
    reader = warm_boot.title_probe(None, {"game_id": "115f9cdbba115432", "platform": "switch"})
    assert reader is R.warm_probe
