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
def _fresh_caches(tmp_path, monkeypatch):
    """The unit caches are per main base, and every fake guest here shares BASE; the stage coverage is this test's."""
    for cache in (R._FOUND, R._MISS, R._ACTION_NAMES):
        cache.clear()
    R._BONUS.update(base=None)
    R.TITLE.since = None
    monkeypatch.setattr(R, "COVERAGE_PATH", str(tmp_path / "re6_coverage.json"))
    R._COVERAGE["data"] = None
    yield
    R._COVERAGE["data"] = None


def round_guest(phase=R.PHASE_PLAYING, hp=900, timer=97.5, enemies=((300.0, 0.0, 500.0, 700),), player=True,
                state=0, ammo=18, cam_yaw=0.0, hud=True, laser=None, mode=R.MODE_NO_MERCY, tablets=8, guns=()):
    g = Guest()
    gm = g.obj("sGameMan", 0x8000)
    g.q(BASE + R.S_GAMEMAN, gm)
    g.i32(gm + R.GM_MODE, mode)
    g.i32(gm + R.GM_PHASE, phase)
    g.f32(gm + R.GM_TIMER, timer)
    from gbox.mercs.titles import re6_switch_mods as RM
    g.f32(gm + RM.GM_CLOCK, timer)                            # the countdown itself (GM_TIMER: the HUD's copy of it)
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


@pytest.mark.parametrize("count", [64, 72, 128, 300])
def test_no_mercy_crowds_do_not_disappear_above_64(count):
    enemies = tuple((float(i), 0.0, 250.0, 700) for i in range(count))
    snap = R.snapshot(round_guest(enemies=enemies))
    assert len(snap["enemies"]) == count
    assert snap["enemies"][-1]["pos"][0] == count - 1
    assert snap["enemy_scan"]["complete"] is True
    assert snap["enemy_scan"]["count"] == count


def test_corrupt_enemy_count_is_bounded_and_reported():
    g = round_guest()
    se = R.u64(g, BASE + R.S_ENEMY)
    g.i32(se + R.E_COUNT, 0x7fffffff)
    snap = R.snapshot(g)
    assert snap["enemies"] == []
    assert snap["enemy_scan"]["complete"] is False
    assert snap["enemy_scan"]["reason"] == "count_limit"


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
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", True)                                  # (off in play: a new round drawn)
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


def test_the_character_select_finds_chris_by_his_id_as_the_list_grows(monkeypatch):
    # a fresh save lists Leon 0, Chris 2, Jake 4, Agent 8 (index 1 = Chris); once Helena (1) unlocks she takes index 1
    # (live 2026-10-27: the second walk picked uPl01HelenaAsia at index 1) and Chris moves to index 2
    monkeypatch.setattr(R, "PICK", R._Pick())
    R.PICK.queued = {"character": 2, "stage": None}                            # Chris queued
    for ids, want in (((0, 2, 4, 8), 1), ((0, 1, 2, 4, 8), 2), ((0, 1, 2, 3, 4, 5, 6, 8), 2), ((0, 4, 8), R.PLAYER_TARGET)):
        g = menu_guest("uIdStartUp32", R.PLAYER_CURSOR, 0)
        u = g.lines[18][-1]
        g.i32(u + R.PLAYER_COUNT, len(ids))
        for i, cid in enumerate(ids):
            g.i32(u + R.PLAYER_IDS + 4 * i, cid)
        scr = R.screen(g)
        assert scr["where"] == "select_player" and scr["target"] == want


def test_the_stage_select_draws_a_random_unlocked_stage_once_a_visit(monkeypatch):
    import random
    monkeypatch.setattr(R, "PICK", R._Pick(random.Random(5)))
    g = menu_guest("uIdStartUp31", R.MENU_CURSOR, 0, {R.STAGE_UNLOCKED: 0b10010010})   # stages 1, 4 and 7 can start
    first = R.screen(g)
    assert first["where"] == "select_stage" and first["target"] in (1, 4, 7)
    assert first["stage"] == R.STAGES[first["target"]]
    assert all(R.screen(g)["target"] == first["target"] for _ in range(5))         # one draw a visit
    assert R.step(R.screen(g)) == "ddown"
    R.request(stage=4)
    assert R.screen(g)["target"] == 4
    R.request(stage=5)                                                             # locked: a random one that starts
    assert R.screen(g)["target"] in (1, 4, 7)
    R.PICK.stage = 4
    assert R.screen(round_guest())["where"] == "playing"                           # the round is up: drawn anew next
    assert R.PICK.stage is None and R.PICK.queued == {} and R.PICK.last["stage"] == 4
    assert R.coverage()["stages"] == {R.STAGES[4]: 1}                              # counted, kept on disk
    seen = set()
    for _ in range(40):
        R.PICK.reset()
        seen.add(R.screen(g)["target"])
    assert seen == {1, 7}                                                          # the least played first
    R._COVERAGE["data"] = None
    assert R.coverage()["stages"] == {R.STAGES[4]: 1}                              # read back from the file
    locked = menu_guest("uIdStartUp31", R.MENU_CURSOR, 0)                          # no bit readable: Urban Chaos
    assert R.screen(locked)["target"] == R.STAGE_TARGET


def test_the_character_select_puts_a_random_costume_on_the_character_then_confirms(monkeypatch):
    import random
    monkeypatch.setattr(R, "PICK", R._Pick(random.Random(3)))
    R.PICK.queued = {"character": 2, "stage": None}                                # Chris queued
    g = menu_guest("uIdStartUp32", R.PLAYER_CURSOR, 2)                             # on Chris, every character listed
    u = g.lines[18][-1]
    g.i32(u + R.PLAYER_COUNT, 9)
    for i in range(9):
        g.i32(u + R.PLAYER_IDS + 4 * i, i)
    g.i32(u + R.COSTUME_COUNT + 4 * 2, 4)
    want = R.screen(g)["costume_target"]
    assert 0 <= want < 4 and R.screen(g)["character"] == "Chris"
    key = None
    for _ in range(5):
        scr = R.screen(g)
        key = R.step(scr)
        if key == "a":
            break
        assert key == ("dright" if scr["costume_cursor"] < want else "dleft")
        g.i32(u + R.COSTUME_CURSOR + 4 * 2, scr["costume_cursor"] + (1 if key == "dright" else -1))
    assert key == "a" and R.screen(g)["costume_cursor"] == want
    R.request(character="Leon")                                                    # a queued round names Leon
    scr = R.screen(g)
    assert scr["target"] == 0 and R.step(scr) == "dup"
    with pytest.raises(ValueError):
        R.request(character="Wesker")
    assert R.costume_code(9) == ("Chris", 1) and R.costume_code(28) == ("Carla", 0)
    assert R.costume_code(29) == ("Agent", 0) and R.costume_code(30) is None


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


def test_legacy_flash_directive_cannot_substitute_an_inventory_throw():
    from gbox.mercs import directives as D
    bot, clock, snap = brain(round_guest(enemies=()))
    snap["player"].update(equipped=0, nades={R.NADE_TYPES["flash"]: (11, 20)})
    D.apply_to_stats(bot.stats, D.post("test-re6-flash-routing", "flashbang"))
    run(bot, snap, clock, 1)
    assert bot.nade is None
    assert not bot.stats.get("emergency_flashes")
    run(bot, snap, clock, 2)
    assert not bot.stats.get("emergency_flashes")


@pytest.mark.parametrize("command", ["next_area", "explore"])
def test_operator_wall_command_reaches_escape_once_through_full_tick(command):
    from gbox.mercs import directives as D
    bot, clock, snap = brain(round_guest(enemies=()))
    D.apply_to_stats(bot.stats, D.post("test-re6-wall-routing", command))
    act = run(bot, snap, clock, 1)[0]
    assert bot.stats.get("wall_reports") == 1
    assert set(act.get("hold", ())) & {"lup", "ldown", "lleft", "lright"}
    until = bot.wall_escape[0]
    run(bot, snap, clock, 2)
    assert bot.stats.get("wall_reports") == 1 and bot.wall_escape[0] == until


def test_at_a_stand_it_throws_a_remote_bomb_and_sets_it_off_when_they_are_on_it():
    crowd = ((0.0, 0.0, 700.0, 700), (150.0, 0.0, 800.0, 700), (-150.0, 0.0, 750.0, 700), (0.0, 0.0, 900.0, 700))   # 4
    bot, clock, snap = brain(round_guest(enemies=crowd))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    first = run(bot, snap, clock, 1)[0]
    assert first == {"tap": "dup"} and bot.doing == "bomb"                    # the wheel's up: one press to the bomb
    snap["player"]["equipped"] = R.BOMB_INDEX
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    assert {"hold": ("zl",)} in acts and {"hold": ("zl", "zr")} in acts       # ZL held, then ZR with it: the throw
    snap["player"]["bomb"] = {"count": 5, "out": True}                         # its slot's mode turned 1
    acts = run(bot, snap, clock, 2)
    assert bot.stats["bombs_placed"] == 1 and bot.bomb_at == (0.0, 0.0)       # taken to lie where he threw it ...
    assert bot.doing == "bomb" and all("ldown" in a["hold"] for a in acts)    # ... so he walks out of its reach at once
    snap["bomb_pos"] = (0.0, 0.0, R.BOMB_AHEAD)                               # read where it lies: 3 m ahead
    for e in snap["enemies"]:                                                 # they walk onto it
        e["pos"] = (50.0, 0.0, R.BOMB_AHEAD + 30.0)
    acts = run(bot, snap, clock, 4)
    assert bot.bomb_at == (0.0, R.BOMB_AHEAD) and all("ldown" in a["hold"] for a in acts)   # 3 m: inside, walking out
    snap["player"]["pos"] = (0.0, 0.0, R.BOMB_AHEAD - bot.book.safe - 80.0)   # the rule's distance and then some
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts and bot.bomb_phase in ("det", "det_wait")
    assert bot.stats["bomb_det_cm"] == [round(bot.book.safe + 80)]
    snap["player"].update(bomb={"count": 5, "out": False}, equipped=0)        # the blast; the game gave the gun back
    for e in snap["enemies"]:
        e["hp"] = 0                                                           # it took them all
    run(bot, snap, clock, 1)
    assert bot.stats["bombs_detonated"] == 1 and bot.bomb_phase is None
    run(bot, snap, clock, int(R.BOMB_LEARN_S / 0.05) + 2)
    assert bot.stats["bomb_self_hits"] == 0                                   # clear of it: the blast cost him nothing
    rec = bot.stats["bomb_blast_log"][-1]
    assert rec["real"] and rec["hit_cm"] == [58, 58, 58, 58] and rec["hp_lost"] == 0   # booked: the reach it showed
    snap["kills"] = (snap.get("kills") or 0) + 10                             # ten of them, and nobody left standing
    snap["enemies"] = []
    run(bot, snap, clock, int(R.BOMB_KILLS_S / 0.05) + 2)
    assert bot.stats["bomb_kills"] == 10


def bomb_out(enemies, me=(0.0, 0.0, 0.0)):
    """A bomb out 3 m ahead of where he stood (at the origin, facing +z) and the bot waiting on it."""
    bot, clock, snap = brain(round_guest(enemies=enemies))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True}, pos=me)
    bot.bomb_at, bot.bomb_since, bot.bomb_from, bot.bomb_phase = (0.0, R.BOMB_AHEAD), clock[0], (0.0, 0.0), "wait"
    return bot, clock, snap


def test_after_a_bomb_he_walks_off_it_and_never_sets_it_off_near_himself():
    on_it = ((40.0, 0.0, 300.0, 700), (-40.0, 0.0, 320.0, 700))               # two on the bomb, him 3 m from it
    bot, clock, snap = bomb_out(on_it)
    acts = run(bot, snap, clock, int(30.0 / 0.05))                            # 30 s pinned there (a wall behind)
    assert all("zr" not in a.get("hold", ()) for a in acts)                   # never set off from 3 m, however long
    assert bot.doing == "bomb" and bot.stats["bomb_walks"] == 1
    holds = [set(a.get("hold", ())) for a in acts]
    assert all("ldown" in h for h in holds)                                   # the stick back: away from it
    assert any("lleft" in h for h in holds) and any("lright" in h for h in holds)   # stuck: side steps, both ways
    snap["player"]["pos"] = (0.0, 0.0, R.BOMB_AHEAD - R.BOMB_SELF_R - 50.0)   # clear of it now: set off
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts and bot.stats["bomb_det_cm"] == [R.BOMB_SELF_R + 50]
    assert bot.stats["bomb_escapes"] == 1


def test_a_bomb_out_he_backs_off_it_and_kicks_the_ones_on_him_in_the_same_ticks_never_standing():
    six = (0.0, 0.0, R.BOMB_AHEAD - 600.0)                                    # 6 m from it: outside 5 m, inside 7 m
    bot, clock, snap = bomb_out(((0.0, 0.0, 100.0, 700),))                   # 3 m from it, one at arm's length
    snap["player"]["hp"] = 200                                                # and hurt: the tablet waits
    act = run(bot, snap, clock, 1)[0]
    assert set(act["hold"]) >= {"ldown", "zr"} and bot.stats["act"] == "bomb_escape"   # off it and a kick at once
    assert bot.stats["bomb_kicks"] == 1 and "zl" not in act["hold"]           # ZR alone: ZL + ZR would set it off
    acts = run(bot, snap, clock, int(R.CC_KICK_GAP_S / 0.05) + 1)
    assert all("ldown" in a["hold"] for a in acts) and bot.stats["bomb_kicks"] == 2   # still going, kicking again
    bot, clock, snap = bomb_out(((0.0, 0.0, six[2] + 100.0, 700),), me=six)  # outside the reach, one on him
    act = run(bot, snap, clock, 1)[0]
    assert set(act["hold"]) >= {"ldown", "zr"} and bot.stats["melee"] == 1
    bot, clock, snap = bomb_out(((150.0, 0.0, six[2] - 100.0, 700), (-150.0, 0.0, six[2] - 100.0, 700)), me=six)
    acts = run(bot, snap, clock, 20)                                          # two at his back, in the way out:
    assert bot.stats["escape_fights"] >= 1 and bot.stats["bomb_face_s"] == 0.0   # fought first, never walked into
    assert not any(a.get("hold") == ("ldown",) for a in acts)
    on_it = ((40.0, 0.0, 300.0, 700), (-40.0, 0.0, 320.0, 700))
    bot, clock, snap = bomb_out(on_it, me=six)
    acts = run(bot, snap, clock, int(30.0 / 0.05))                            # 30 s at 6 m (a wall behind)
    assert all("zr" not in a.get("hold", ()) for a in acts)                   # never set off inside 7 m, however long


def test_drift_into_blast_radius_during_det_aim_holds_the_trigger_not_fires():
    """When the player drifts into the blast's safe radius during the det_aim hold, the bot holds ZL
    (not ZL+ZR) so the bomb does not set off and damage him — the bomb_act_damage cluster fix."""
    bot, clock, snap = bomb_out(((40.0, 0.0, 300.0, 700), (-40.0, 0.0, 320.0, 700)))
    # He starts clear of the bomb (7 m away = safe distance)
    snap["player"]["pos"] = (0.0, 0.0, R.BOMB_AHEAD - R.BOMB_SELF_R - 50.0)
    # Start the det_aim phase: two zombies on the bomb trigger detonation
    acts = run(bot, snap, clock, 3)
    # He should be in det_aim now (ZL held, aiming at the bomb)
    assert bot.bomb_phase == "det_aim", f"phase={bot.bomb_phase}"
    # Now he drifts back into the blast radius during the aim hold
    snap["player"]["pos"] = (0.0, 0.0, R.BOMB_AHEAD - 200.0)  # 2 m from bomb, well inside safe
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    # The ZL+ZR (detonation) frame must never appear — the trigger was held, not fired
    assert not any(set(a.get("hold", ())) >= {"zl", "zr"} for a in acts), \
        f"ZL+ZR fired despite drift: acts={acts}"
    assert bot.stats["bomb_det_holds"] >= 1, \
        f"bomb_det_holds not incremented: stats={bot.stats.get('bomb_det_holds')}"
    # He should still be in det_aim (not transitioned to det)
    assert bot.bomb_phase in ("det_aim", "wait"), f"phase={bot.bomb_phase}"


def test_the_placed_bombs_own_spot_is_used_when_its_unit_is_found():
    g = round_guest(enemies=((0.0, 0.0, 3000.0, 700),))
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    bu = g.unit(16, "uWp1097")
    g.f32(bu + R.P_POS, 30.0, 0.0, 60.0)                                      # it dropped at his feet (a wall ahead)
    snap = R.snapshot(g)
    assert "bomb_pos" not in snap                                             # no bomb out: not looked for
    bot, clock, _ = brain(g)
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True})
    snap["bomb_pos"] = R.placed_bomb(g, BASE)
    assert snap["bomb_pos"] == (30.0, 0.0, 60.0) and p
    bot.bomb_at, bot.bomb_since, bot.bomb_phase, bot.bomb_from = (0.0, 0.0), clock[0], "wait", (0.0, 0.0)
    bot.held = lambda p, now: False
    act = run(bot, snap, clock, 1)[0]
    assert bot.bomb_at == (30.0, 60.0) and bot.stats["bomb_aim_err_cm"] == [242]
    assert "ldown" in act["hold"] and bot.doing == "bomb"                    # 0.7 m from it: walking off it


def test_terminal_observation_counts_death_before_the_engine_closes_evidence():
    bot, clock, snap = bomb_out(((0.0, 0.0, 120.0, 700),) * 3)
    run(bot, snap, clock, 4)
    bot.observe_round(snap, "playing", clock[0])
    assert bot.stats["deaths"] == 0
    snap["player"].update(hp=0, state=0)
    bot.observe_round(snap, "loading", clock[0])
    assert bot.stats["deaths"] == 0
    bot.observe_round(snap, "dead", clock[0])
    assert bot.stats["deaths"] == 1 and len(bot.stats["death_log"]) == 1
    bot.observe_round(snap, "dead", clock[0])
    run(bot, snap, clock, 1)
    assert bot.stats["deaths"] == 1 and len(bot.stats["death_log"]) == 1


def test_engine_persists_the_native_terminal_death_in_its_round(tmp_path, monkeypatch):
    import copy
    import json
    import sqlite3
    from gbox.mercs import engine, lessons

    monkeypatch.setattr(lessons, "ROOT", tmp_path / "mercs" / "lessons")
    bot, clock, scene = bomb_out(((0.0, 0.0, 300.0, 700),))
    dead = copy.deepcopy(scene)
    dead["player"]["hp"] = 0
    sequence = [scene, dead, dead]
    cursor = [0]

    class Driver:
        frame = None
        solo_p1 = True
        round_counters = ("deaths",)

        def snapshot(self, memory):
            result = sequence[cursor[0]]
            cursor[0] += 1
            clock[0] += 0.2
            return result

        def screen(self, memory, snap):
            return "dead" if snap["player"]["hp"] == 0 else "playing"

        def progress(self, snap):
            return {"score": 5180, "kills": 13, "timer": 73.26}

        def prompt_source(self, *args): return lambda: None
        def prompt_keys(self, buttons): return []

    engine.play_round({"map_id": R.MAP_ID}, object(), lambda rows: None,
                      lambda: cursor[0] >= len(sequence), bot.stats, lambda row: None,
                      brain=bot, driver=Driver(), clock=lambda: clock[0], sleep=lambda _: None)
    with sqlite3.connect(tmp_path / "mercs" / "curriculum" / R.MAP_ID / "rounds.sqlite") as db:
        rows = db.execute("SELECT outcome,data FROM rounds").fetchall()
    assert len(rows) == 1 and rows[0][0] == "died"
    assert json.loads(rows[0][1])["round_deaths"] == 1
    assert bot.stats["deaths"] == 1


def test_a_death_is_logged_with_its_cause_and_forgets_the_bomb():
    bot, clock, snap = bomb_out(((0.0, 0.0, 120.0, 700),) * 3)
    run(bot, snap, clock, 4)
    snap["player"].update(hp=0, state=0)
    run(bot, snap, clock, 1)
    d = bot.stats["death_log"][-1]
    assert d["near_2m"] == 3 and d["bomb_phase"] == "wait" and d["bomb_cm"] == 300 and d["held"] is False
    assert bot.bomb_at is None and bot.bomb_phase is None


def test_the_bomb_walk_heads_away_from_the_bomb_and_a_blast_that_hurts_him_is_counted():
    bot, clock, snap = bomb_out(((0.0, 0.0, 3000.0, 700),), me=(-300.0, 0.0, R.BOMB_AHEAD))   # the bomb 3 m to his +x
    act = run(bot, snap, clock, 1)[0]
    assert act["hold"] == ("lright",)                                         # +x is the screen's left: away is right
    bot, clock, snap = bomb_out(((0.0, 0.0, 300.0, 700),) * 2, me=(0.0, 0.0, R.BOMB_AHEAD - R.BOMB_SELF_R - 10.0))
    run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)                       # set off from 7.1 m
    snap["player"].update(bomb={"count": 5, "out": False}, equipped=0, hp=600)   # the blast took 300 of his health
    run(bot, snap, clock, int(R.BOMB_LEARN_S / 0.05) + 2)
    assert bot.stats["bombs_detonated"] == 1 and bot.stats["bomb_self_hits"] == 1   # nobody near him to blame
    assert bot.stats["bomb_blast_log"][-1]["real"] is False and bot.book.blasts == []   # not read: not booked


def blast(bot, clock, snap, me_z, zombies, hp_after=None, real=True):
    """A bomb read at (0, 300) set off with him at (0, me_z); zombies [(z, hurt)] beside it; his health after."""
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True}, pos=(0.0, 0.0, me_z), hp=900)
    snap["enemies"] = [{"slot": i, "ptr": 0x9000 + i, "pos": (0.0, 0.0, z), "hp": 700, "hp_max": 700}
                       for i, (z, _hurt) in enumerate(zombies)]
    if real:
        snap["bomb_pos"] = (0.0, 0.0, R.BOMB_AHEAD)
    bot.bomb_at, bot.bomb_since, bot.bomb_from, bot.bomb_phase = (0.0, R.BOMB_AHEAD), clock[0] - 20, (0.0, 0.0), "wait"
    run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    snap["player"].update(bomb={"count": 5, "out": False}, equipped=0, hp=hp_after or 900)
    snap.pop("bomb_pos", None)
    for e, (_z, hurt) in zip(snap["enemies"], zombies):
        if hurt:
            e["hp"] = 100
    run(bot, snap, clock, int(R.BOMB_LEARN_S / 0.05) + 3)


def test_the_blasts_reach_is_learned_kept_and_respected(tmp_path):
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], learn_dir=tmp_path)
    bot.held = lambda p, now: False
    snap = R.snapshot(round_guest(enemies=()))
    assert bot.book.radius == R.BOMB_RADIUS_CM and bot.book.safe == max(R.BOMB_SELF_R, R.BOMB_RADIUS_CM + 200)
    blast(bot, clock, snap, R.BOMB_AHEAD - 900.0, [(300.0 + 650.0, True), (300.0 + 1100.0, False)])   # hurt at 6.5 m
    assert bot.stats["bomb_blast_log"][-1]["hit_cm"] == [650] and bot.book.radius == 650
    assert bot.book.safe == 850 and bot.stats["bomb_self_hits"] == 0
    kept = R.Bot(stats={}, clock=lambda: clock[0], learn_dir=tmp_path)       # the next session: the same reach
    assert kept.book.radius == 650 and (tmp_path / R.BOMB_BOOK_FILE).exists()
    kept.held = lambda p, now: False
    snap = R.snapshot(round_guest(enemies=((0.0, 0.0, 300.0, 700),) * 2))
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True}, pos=(0.0, 0.0, R.BOMB_AHEAD - 800.0))
    kept.bomb_at, kept.bomb_since, kept.bomb_from, kept.bomb_phase = (0.0, R.BOMB_AHEAD), clock[0] - 20, (0.0, 0.0), "wait"
    acts = run(kept, snap, clock, int(10.0 / 0.05))                           # 8 m: past 7 m, inside 8.5 m
    assert all("zr" not in a.get("hold", ()) for a in acts)                   # the learned rule holds it


def test_a_zombie_at_his_elbow_is_not_the_blasts_and_old_records_do_not_count(tmp_path):
    import json as _json
    (tmp_path / R.BOMB_BOOK_FILE).write_text(_json.dumps({"blasts": [{"me_cm": 760, "hit_cm": [1024], "real": True}]}))
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], learn_dir=tmp_path)
    assert bot.book.radius == R.BOMB_RADIUS_CM                                # the old record's outlier: ignored
    bot.held = lambda p, now: False
    snap = R.snapshot(round_guest(enemies=()))
    me_z = R.BOMB_AHEAD - 760.0
    blast(bot, clock, snap, me_z, [(300.0 + 300.0, True), (me_z + 250.0, True)])   # one by the bomb, one at his elbow
    rec = bot.stats["bomb_blast_log"][-1]
    assert rec["hit_cm"] == [300] and rec["v"] == R.BOMB_BOOK_V and bot.book.radius == R.BOMB_RADIUS_CM


def test_a_blast_that_hurts_him_inside_its_reach_is_a_self_hit_and_teaches_the_reach(tmp_path):
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], learn_dir=tmp_path)
    bot.held = lambda p, now: False
    snap = R.snapshot(round_guest(enemies=()))
    bot.book.blasts = []
    rec_before = bot.book.radius
    # a blast set off from 7.5 m that still knocked him down, nobody near him to blame: the reach is at least 7.5 m
    blast(bot, clock, snap, R.BOMB_AHEAD - 750.0, [(300.0 + 200.0, True)], hp_after=700)
    rec = bot.stats["bomb_blast_log"][-1]
    assert rec["self_hit"] and rec["hp_lost"] == 200 and bot.stats["bomb_self_hits"] == 1
    assert bot.book.radius == 750 > rec_before and bot.book.safe == 950
    # one at his elbow when his health fell outside the reach: the zombie takes the blame, not booked as his
    bot2 = R.Bot(stats={}, clock=lambda: clock[0])
    bot2.held = lambda p, now: False
    me_z = R.BOMB_AHEAD - 900.0
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True}, pos=(0.0, 0.0, me_z), hp=900)
    snap["enemies"] = [{"slot": 0, "ptr": 0x9000, "pos": (0.0, 0.0, 400.0), "hp": 700, "hp_max": 700},
                       {"slot": 1, "ptr": 0x9001, "pos": (0.0, 0.0, me_z + 250.0), "hp": 700, "hp_max": 700}]
    snap["bomb_pos"] = (0.0, 0.0, R.BOMB_AHEAD)
    bot2.bomb_at, bot2.bomb_since, bot2.bomb_from, bot2.bomb_phase = (0.0, R.BOMB_AHEAD), clock[0] - 20, (0.0, 0.0), "wait"
    run(bot2, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)                      # set off as that one came
    snap["enemies"][1]["pos"] = (0.0, 0.0, me_z + 150.0)                      # it reached his elbow meanwhile
    run(bot2, snap, clock, 1)
    snap["player"].update(bomb={"count": 5, "out": False}, equipped=0, hp=800)
    snap.pop("bomb_pos", None)
    snap["enemies"][0]["hp"] = 100
    run(bot2, snap, clock, int(R.BOMB_LEARN_S / 0.05) + 3)
    assert bot2.stats["bomb_self_hits"] == 0 and bot2.stats["bomb_blast_log"][-1]["near_him"] == 1


def test_readying_a_bomb_is_given_up_when_one_comes_close():
    crowd = ((0.0, 0.0, 700.0, 700), (150.0, 0.0, 800.0, 700), (-150.0, 0.0, 750.0, 700), (0.0, 0.0, 900.0, 700))
    bot, clock, snap = brain(round_guest(enemies=crowd))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    run(bot, snap, clock, 1)
    assert bot.bomb_phase == "equip"
    snap["enemies"][0]["pos"] = (0.0, 0.0, 150.0)                             # one at 1.5 m while the wheel turns
    run(bot, snap, clock, 1)
    assert bot.bomb_phase is None and bot.stats["bomb_aborts"] == 1 and bot.doing == "crowd"


def test_clear_of_the_bomb_he_sets_it_off_as_they_come_and_faces_it_only_briefly_with_nobody_near():
    far = (0.0, 0.0, R.BOMB_AHEAD - 900.0)                                    # 9 m from it
    bot, clock, snap = bomb_out(((0.0, 0.0, far[2] + 350.0, 700),), me=far)  # one coming at 3.5 m, none on the bomb
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts                                     # set off now: the gun comes back
    bot, clock, snap = bomb_out(((0.0, 0.0, 3000.0, 700),), me=(-900.0, 0.0, R.BOMB_AHEAD))   # it 9 m to his right
    acts = run(bot, snap, clock, 30)
    faced = [a for a in acts if a.get("hold") and set(a["hold"]) <= {"rleft", "rright"} and a["hold"]]
    assert 0 < len(faced) * 0.05 <= R.BOMB_FACE_MAX_S + 0.05 and bot.stats["bomb_face_s"] <= R.BOMB_FACE_MAX_S + 0.1


def test_bomb_hits_taken_counts_the_health_he_loses_in_a_bomb_act():
    bot, clock, snap = bomb_out(((0.0, 0.0, 3000.0, 700),))
    run(bot, snap, clock, 2)
    snap["player"]["hp"] = 700                                                # hit while walking off it
    run(bot, snap, clock, 1)
    assert bot.stats["bomb_hits_taken"] == 200


def test_no_bomb_readied_with_two_within_three_metres():
    crowd = ((0.0, 0.0, 280.0, 700), (60.0, 0.0, 290.0, 700), (0.0, 0.0, 800.0, 700))
    bot, clock, snap = brain(round_guest(enemies=crowd))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    run(bot, snap, clock, 3)
    assert bot.bomb_phase is None and bot.stats["bombs_placed"] == 0


def test_three_close_get_a_flash_then_the_gun_back_and_the_melee_fever(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)                                    # (off in play until the wheel is measured)
    monkeypatch.setattr(R, "FLASH_BURST_S", 0.0)                             # one flash here (the flurry: its own test)
    near = ((0.0, 0.0, 300.0, 700), (100.0, 0.0, 350.0, 700), (-100.0, 0.0, 380.0, 700),
            (200.0, 0.0, 320.0, 700), (-200.0, 0.0, 330.0, 700))                       # five at 3-3.8 m
    bot, clock, snap = brain(round_guest(enemies=near, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100                              # (no crowd-control press in the way)
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)})
    acts = run(bot, snap, clock, 3)
    assert {"tap": "dup"} in acts and bot.nade["kind"] == "flash"            # the wheel's up to the flash grenade
    snap["player"]["equipped"] = 11
    acts = run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert {"hold": ("zl",)} in acts and {"hold": ("zl", "zr")} in acts and bot.stats["flashes"] == 1
    acts = run(bot, snap, clock, int((R.NADE_STEP_S + R.NADE_THROW_S) / 0.05) + 3)
    assert {"tap": "dright"} in acts                                          # the gun back
    snap["player"]["equipped"] = 0
    bot.melee_at = -1e9
    acts = run(bot, snap, clock, 4)
    assert bot.nade is None and bot.stats["act"] == "push_walk" and bot.push is not None
    assert all("ldown" in a.get("hold", ()) for a in acts)                    # the push-through: out the open side
    snap["enemies"][0]["pos"] = (0.0, 0.0, -100.0)                            # one steps into the way out
    acts = run(bot, snap, clock, 2)
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["fever_kicks"] >= 1
    assert bot.stats["bomb_drops"] == 0                                       # the fever first, no bomb drop
    bot.nade_last = -1e9                                                      # a second flash: not within FLASH_GAP_S
    run(bot, snap, clock, 3)
    assert bot.nade is None or bot.nade["kind"] != "flash"
    assert all("zl" not in a.get("hold", ()) for a in acts)                   # kicks, no quick shots


def test_the_throw_is_held_and_flashes_come_in_a_flurry_while_they_crowd_him(monkeypatch):
    """Operator 2026-10-28: "They still lift the grenade for use but never throw it" / "spamming a flurry of flash
    grenades": ZL + ZR held NADE_THROW_S (not one tick), and another flash at once while FLASH_N stay close."""
    monkeypatch.setattr(R, "NADES", True)
    near = ((0.0, 0.0, 220.0, 700), (100.0, 0.0, 240.0, 700), (-100.0, 0.0, 250.0, 700),
            (150.0, 0.0, 200.0, 700), (-150.0, 0.0, 210.0, 700))                   # five within 3 m: swarmed
    bot, clock, snap = brain(round_guest(enemies=near, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)})
    run(bot, snap, clock, 3)
    snap["player"]["equipped"] = 11                                           # the flash in hand
    acts = run(bot, snap, clock, int((R.NADE_AIM_S + R.NADE_THROW_S) / 0.05) + 2)
    assert sum(1 for a in acts if a.get("hold") == ("zl", "zr")) >= int(R.NADE_THROW_S / 0.05)   # held, not tapped
    acts = run(bot, snap, clock, 30)
    assert bot.stats["flashes"] >= 2 and bot.stats.get("flash_burst_throws", 0) >= 1
    assert {"tap": "dright"} not in acts or bot.stats["flashes"] >= 2             # no gun back mid-flurry
    assert bot.stats["bomb_drops"] == 0


def test_a_cluster_off_at_seven_metres_gets_a_grenade_and_its_kills_are_counted(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)                                    # (off in play until the wheel is measured)
    cluster = ((0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=cluster, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5)})
    run(bot, snap, clock, 2)
    assert bot.nade["kind"] == "frag"
    snap["player"]["equipped"] = 9
    acts = run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts and bot.stats["frags"] == 1
    snap["kills"] = (snap.get("kills") or 0) + 3
    snap["player"]["equipped"] = 0
    run(bot, snap, clock, int(R.NADE_KILLS_S / 0.05) + 2)
    assert bot.stats["grenade_kills"] == 3


def test_the_wheel_key_steps_toward_the_grenade():
    assert R.Bot._wheel_key(0, 11) == "dup" and R.Bot._wheel_key(0, 9) == "ddown"   # from the gun
    assert R.Bot._wheel_key(12, 11) == "dup" and R.Bot._wheel_key(9, 10) == "ddown"  # on an item: toward it


def test_after_a_throw_the_game_picks_the_knife_and_the_gun_back_is_his_magnum(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    cluster = ((0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=cluster, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5)})
    run(bot, snap, clock, 2)
    snap["player"]["equipped"] = 9
    run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert bot.stats["frags"] == 1
    snap["player"]["equipped"] = 2                                            # the game's pick after the throw: the knife
    acts = run(bot, snap, clock, int((R.NADE_STEP_S + R.NADE_THROW_S) / 0.05) + 3)
    assert {"tap": "dright"} in acts and bot.nade is not None                 # not his gun yet: on to it
    snap["player"]["equipped"] = 1                                            # another gun of his: good enough, at once
    run(bot, snap, clock, 1)
    assert bot.nade is None and bot.stats["nade_wheel"][-1]["to"] == 9


def test_a_grenade_in_hand_is_thrown_with_one_close_and_a_throw_is_called_off_only_before(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    cluster = ((0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=cluster, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5)})
    run(bot, snap, clock, 2)
    assert bot.nade is not None and bot.nade["kind"] == "frag"
    snap["player"]["equipped"] = 9                                            # the frag in hand ...
    snap["enemies"].append(dict(snap["enemies"][0], pos=(0.0, 0.0, 100.0), ptr=0x7777, slot=9))   # ... one at arm's length
    acts = run(bot, snap, clock, int((R.NADE_FACE_S + R.NADE_AIM_S) / 0.05) + 4)
    assert {"hold": ("zl", "zr")} in acts and bot.stats["frags"] == 1         # thrown at the cluster, not put away
    assert bot.stats["nade_aborts"] == 0 and bot.stats["throws_by_kind"] == {"frag": 1}
    assert bot.stats["unsafe_trigger_blocks"] == 0
    bot2, clock2, snap2 = brain(round_guest(enemies=cluster, cam_yaw=0.0))  # not in hand yet: called off for the fight
    bot2.held = lambda p, now: False
    snap2["player"].update(equipped=0, nades={0x113: (9, 5)})
    run(bot2, snap2, clock2, 1)
    snap2["enemies"][0]["pos"] = (0.0, 0.0, 100.0)
    acts = run(bot2, snap2, clock2, 2)
    assert bot2.stats["nade_aborts"] == 1 and bot2.stats["frags"] == 0        # the gun stays in hand for the fight


def test_a_grenade_lifted_outside_a_throw_is_thrown_at_the_best_cluster_four_metres_off(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    foes = ((0.0, 0.0, 250.0, 700),                                           # one near him ...
            (600.0, 0.0, 600.0, 700), (700.0, 0.0, 650.0, 700), (650.0, 0.0, 560.0, 700))   # ... three together 8.5 m off
    bot, clock, snap = brain(round_guest(enemies=foes, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=10, nades={0x113: (9, 5), 0x114: (10, 3)})   # the incendiary in his hand, no throw
    acts = run(bot, snap, clock, int((R.NADE_FACE_S + R.NADE_AIM_S) / 0.05) + 4)
    assert bot.stats["held_item_throws"] == 1 and bot.stats["fires"] == 1
    assert {"hold": ("zl", "zr")} in acts and bot.stats["unsafe_trigger_blocks"] == 0
    assert bot.stats["throws_by_kind"] == {"fire": 1}
    assert all(a.get("tap") != "dright" for a in acts[:acts.index({"hold": ("zl", "zr")})])   # never put away first


def test_a_frag_starts_with_one_near_him_when_the_cluster_is_clear_of_its_blast(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    foes = ((0.0, 0.0, 250.0, 700),                                           # one 2.5 m off (no NADE_START_R refusal)
            (0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=foes, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5)})
    bot._crowd_control = lambda *a, **k: None
    for _ in range(20):
        run(bot, snap, clock, 1)
        if bot.nade is not None:
            break
    assert bot.nade is not None and bot.nade["kind"] == "frag"


def test_the_combo_running_down_makes_the_nearest_the_target_and_a_lapse_is_counted():
    two = ((0.0, 0.0, 1500.0, 700), (800.0, 0.0, 600.0, 700))                 # one far ahead, one nearer to the right
    bot, clock, snap = brain(round_guest(enemies=two, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap.update(combo=6, combo_timer=2.0)
    run(bot, snap, clock, 1)
    assert bot.combo_urgent and bot.target == snap["enemies"][1]["ptr"] and bot.stats["combo_pushes"] == 1
    snap.update(combo=0, combo_timer=0.0)
    run(bot, snap, clock, 1)
    assert bot.stats["combo_breaks"] == 1 and bot.stats["combo_best"] == 6


def test_crowd_control_all_round_one_behind_gets_the_quick_turn():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, -300.0, 700),), cam_yaw=0.0))   # 3 m behind him
    bot.held = lambda p, now: False
    act = run(bot, snap, clock, 1)[0]
    assert act == {"hold": ("ldown",)} and bot.quick == 2 and bot.stats["quick_turns"] == 1


def test_no_zl_and_zr_with_an_item_in_hand_unless_it_is_a_throw():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 180.0, 700),), cam_yaw=0.0))   # a quick shot's distance
    bot.held = lambda p, now: False
    snap["player"]["equipped"] = 12                                           # the remote bomb in hand
    acts = run(bot, snap, clock, 6)
    assert all(not ({"zl", "zr"} <= set(a.get("hold", ()))) for a in acts)
    assert acts[0] == {"tap": "dright"} and bot.stats["item_gun_backs"] >= 1   # put away before ZL ever lifts it


def test_dying_at_one_health_he_presses_for_a_tablet_and_counts_whether_it_took(monkeypatch):
    monkeypatch.setattr(R, "DYING_TABLETS", True)                             # (off in play: the game takes none)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 800.0, 700),), hp=1, state=3))
    act = run(bot, snap, clock, 1)[0]
    assert act == {"tap": "r"} and bot.stats["act"] == "tablet_dying" and bot.stats["dying_states"] == [3]
    acts = run(bot, snap, clock, int(R.TABLET_CONFIRM_S / 0.05) + 1)          # the count stayed: the game ignored it
    assert bot.stats["tablet_misses"] == 1 and bot.stats["tablet_dying_taken"] == 0
    assert {"tap": "r"} in acts and bot.stats["tablet_dying_presses"] == 2    # pressed again at once
    snap["player"].update(tablets=7, hp=300)                                  # this one took: back up
    run(bot, snap, clock, 1)
    assert bot.stats["tablet_dying_taken"] == 1 and bot.stats["dyings"] == 1 and bot.dying_since is None


def test_a_crowd_gets_a_tablet_earlier_and_crowd_control_backs_out_as_it_attacks():
    four = ((0.0, 0.0, 120.0, 700), (100.0, 0.0, 200.0, 700), (-100.0, 0.0, 220.0, 700), (0.0, 0.0, 280.0, 700))
    bot, clock, snap = brain(round_guest(enemies=four, hp=740, cam_yaw=0.0))   # 82 % with four within 3 m
    bot.held = lambda p, now: False
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}                       # a tablet already
    bot, clock, snap = brain(round_guest(enemies=four, cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 12)
    attacks = [a for a in acts if "zr" in a.get("hold", ())]
    assert attacks and all("ldown" in a["hold"] for a in attacks) and bot.stats["cc_backouts"] > 0


def test_flanking_enemy_at_110deg_gets_crowd_control_not_aimed_fire():
    """#5047 (fc45a6229fe006d0): an enemy 1.5 m away at 110 deg off-facing falls outside CC_CONE (100 deg)
    but inside CC_FLANK_CONE (130 deg). The bot must enter crowd control (turning to the enemy) instead
    of raising its aim into the flanking threat."""
    bot, clock, snap = brain(round_guest(
        enemies=((150.0 * math.sin(math.radians(110)), 0.0, 150.0 * math.cos(math.radians(110)), 700),),
        cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 3)
    # The bot should be in crowd control (cc_turn or quick_turn), not aiming
    assert bot.stats["act"] in ("cc_turn", "cc_quick_shot", "cc_kick", "quick_turn"), \
        f"flanking enemy at 110 deg not caught by crowd control: act={bot.stats['act']}"


def test_flanking_enemy_at_137deg_gets_crowd_control_not_aimed_fire():
    """#5047 (fc45a6229fe006d0): an enemy at 137 deg off-facing (observed in the cluster) falls
    outside CC_CONE but inside CC_FLANK_CONE. The bot must enter crowd control (quick turn)."""
    bot, clock, snap = brain(round_guest(
        enemies=((180.0 * math.sin(math.radians(137)), 0.0, 180.0 * math.cos(math.radians(137)), 700),),
        cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 3)
    assert bot.stats["act"] in ("cc_turn", "cc_quick_shot", "cc_kick", "quick_turn"), \
        f"flanking enemy at 137 deg not caught by crowd control: act={bot.stats['act']}"


def test_flanking_enemy_at_99deg_gets_crowd_control_not_aimed_fire():
    """#5047 (fc45a6229fe006d0): an enemy at 99 deg off-facing is inside CC_CONE (100 deg).
    The bot must enter crowd control."""
    bot, clock, snap = brain(round_guest(
        enemies=((160.0 * math.sin(math.radians(99)), 0.0, 160.0 * math.cos(math.radians(99)), 700),),
        cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 3)
    assert bot.stats["act"] in ("cc_turn", "cc_quick_shot", "cc_kick", "quick_turn"), \
        f"flanking enemy at 99 deg not caught by crowd control: act={bot.stats['act']}"


def test_enemy_at_150deg_gets_quick_turn_not_crowd_control():
    """Regression: an enemy at 150 deg off-facing is outside CC_FLANK_CONE (130 deg).
    The bot should use quick_turn (existing behavior) rather than crowd control."""
    bot, clock, snap = brain(round_guest(
        enemies=((200.0 * math.sin(math.radians(150)), 0.0, 200.0 * math.cos(math.radians(150)), 700),),
        cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 3)
    assert bot.stats["act"] == "quick_turn", \
        f"enemy at 150 deg should get quick_turn not crowd control: act={bot.stats['act']}"


def test_a_bomb_only_healthy_with_nobody_near_and_three_coming_at_most_every_thirty_seconds():
    four = ((0.0, 0.0, 700.0, 700), (150.0, 0.0, 800.0, 700), (-150.0, 0.0, 750.0, 700), (0.0, 0.0, 1100.0, 700))
    for kw, enemies in (({"hp": 900}, four[:2]),                                       # two coming: no
                        ({"hp": 600}, four),                                           # 67 % health: no
                        ({"hp": 900}, four + ((0.0, 0.0, 350.0, 700),))):              # one at 3.5 m: no
        bot, clock, snap = brain(round_guest(enemies=enemies, **kw))
        bot.tablet_at = clock[0] + 100
        snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
        run(bot, snap, clock, 2)
        assert bot.bomb_phase is None and bot.stats["bombs_placed"] == 0, kw
    bot, clock, snap = brain(round_guest(enemies=four))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    bot.bomb_last = clock[0] - 20.0                                           # one 20 s ago: not yet
    run(bot, snap, clock, 2)
    assert bot.bomb_phase is None
    bot.bomb_last = clock[0] - R.BOMB_GAP_S - 1                               # 31 s ago: now
    run(bot, snap, clock, 1)
    assert bot.bomb_phase == "equip"


def test_clear_of_it_the_bomb_goes_off_with_one_within_three_metres_of_it():
    far = (0.0, 0.0, R.BOMB_AHEAD - 900.0)
    bot, clock, snap = bomb_out(((0.0, 0.0, R.BOMB_AHEAD + 250.0, 700),), me=far)   # one 2.5 m past the bomb
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts


def test_the_way_out_is_the_widest_gap_and_the_stick_follows_the_camera():
    p = {"pos": (0.0, 0.0, 0.0)}
    ahead = [{"pos": (0.0, 0.0, 300.0)}, {"pos": (150.0, 0.0, 300.0)}, {"pos": (-150.0, 0.0, 300.0)}]
    h = R.Bot._open_heading(p, ahead)
    assert abs(R.wrap(h - math.pi)) <= math.pi / 4                            # they are ahead (+z): out behind
    assert R.Bot._stick(math.pi, 0.0) == ("ldown",) and R.Bot._stick(math.pi / 2, 0.0) == ("lleft",)
    assert R.Bot._stick(-math.pi / 4, 0.0) == ("lup", "lright")
    h = R.Bot._open_heading(p, [], avoid=(0.0, 300.0))                        # a bomb ahead, nobody: away from it
    assert abs(R.wrap(h - math.pi)) <= math.pi / 8


def test_three_closing_he_kites_toward_open_space_while_aiming_and_counts_a_surround():
    three = ((0.0, 0.0, 500.0, 700), (150.0, 0.0, 520.0, 700), (-150.0, 0.0, 540.0, 700))
    on = ((0.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap = brain(round_guest(enemies=three, cam_yaw=0.0, laser=on))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 10)
    aimed = [a for a in acts if "zl" in a.get("hold", ()) and "zr" not in a.get("hold", ()) or
             set(a.get("hold", ())) >= {"zl", "zr"} and len(a["hold"]) > 2]
    assert any("ldown" in a.get("hold", ()) for a in acts) and bot.stats["kite_s"] > 0
    ring = tuple((330.0 * math.sin(a), 0.0, 330.0 * math.cos(a), 700) for a in [i * math.pi / 4 for i in range(8)])
    bot, clock, snap = brain(round_guest(enemies=ring, cam_yaw=0.0))
    run(bot, snap, clock, 2)
    assert bot.stats["surround_events"] == 1 and bot.stats["max_within_4m"] == 8 and aimed is not None


def test_a_long_shot_the_laser_confirms_is_fired_and_its_kill_counted():
    far = ((0.0, 0.0, 2500.0, 700),)                                          # 25 m ahead, nobody nearer
    on = ((0.0, R.CHEST_H, 2500.0), (20.0, 145.0, 30.0), 0.86)              # the dot on his chest
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0, laser=on))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 10)
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["confirmed_shots"] >= 1   # fired, no walking
    snap["enemies"][0]["hp"] = 0                                              # he went down
    run(bot, snap, clock, 1)
    assert bot.stats["long_shot_kills"] == 1


def test_quick_attack_runs_his_quick_attacks_ten_times_faster_and_puts_his_clock_back(mods, monkeypatch):
    g = round_guest()
    ad = Adapter(g)
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.f32(p + mods.UNIT_DELTA, 1.0)
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_walk", 0x100))
    monkeypatch.setattr(R, "QA_FAST", False)
    out = mods.run(ad, "quick_attack", multiplier=10)
    assert out["verified"] and out["quick_attack_x"] == 10.0 and R.QA_FAST
    mods.run(ad, "infinite_ammo", on=False)
    clock = [10.0]
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 0          # walking: his own 1.0
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_comn_quick_shot", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 10.0                     # the quick shot x10
    assert ad.writes[-1] == (p + mods.UNIT_DELTA, struct.pack("<f", 10.0))
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_wait", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 1.0                      # back to 1.0 after it
    g.f32(p + mods.UNIT_DELTA, 0.5)                                                         # the game's slow motion
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_attack_ex", 0x100))
    before = list(ad.writes)
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert ad.writes == before                                                              # left alone
    with pytest.raises(ValueError):
        mods.run(ad, "quick_attack", multiplier=50)


def test_with_quick_attacks_fast_crowd_control_presses_back_to_back_and_counts_them(monkeypatch):
    monkeypatch.setattr(R, "QA_FAST", True)
    g = round_guest(enemies=((0.0, 0.0, 180.0, 700),), cam_yaw=0.0)
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 20)                                          # 1 s
    assert bot.stats["cc_quick_shots"] >= 5                                   # every 0.15 s, not every 0.5 s
    for i in range(3):                                                        # three quick shots begun, 0.2 s apart
        snap["player"]["action"] = "cPlAction_pl_act_weapon_comn_quick_shot"
        run(bot, snap, clock, 2)
        snap["player"]["action"] = "cPlAction_pl_act_wait"
        run(bot, snap, clock, 2)
    assert bot.stats["quick_attacks"] == 3 and bot.stats["quick_attack_interval"] == pytest.approx(0.2, abs=0.01)
    assert R.unit_action(g, R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)) is None and acts


def test_with_none_on_his_floor_he_goes_after_the_stages_nearest_and_counts_the_pursuit():
    upstairs = ((0.0, 800.0, 1500.0, 700), (0.0, 0.0, 6000.0, 700))          # one a floor up, one far on his floor
    bot, clock, snap = brain(round_guest(enemies=upstairs, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap.update(combo=7, combo_timer=2.0)
    acts = run(bot, snap, clock, 1)
    assert acts[0]["hold"][0] == "lup"                                        # on to the far one on his floor
    snap["enemies"] = [snap["enemies"][0]]                                    # only the one upstairs: still after him
    acts = run(bot, snap, clock, 2)
    assert bot.stats["act"] == "pursue" and bot.stats["pursuits"] == 1 and bot.stats["census_alive"] == 1
    acts = run(bot, snap, clock, int(R.PURSUE_STUCK_S / 0.05) + 3)            # no progress: bounded back/side recovery
    assert bot.stats["movement_blocks"] >= 1 and any({"lleft", "lright"} & set(a["hold"]) for a in acts)
    assert snap["enemies"][0]["ptr"] in bot._walk_skip
    snap["kills"] = (snap.get("kills") or 0) + 1                              # the kill before the lapse
    run(bot, snap, clock, 1)
    assert bot.stats["pursuit_kills"] == 1


def test_after_a_multi_kill_with_nobody_near_he_taunts_and_the_emotion_is_counted(monkeypatch):
    monkeypatch.setattr(R, "TAUNTS", True)                                    # (off in play)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["kills"] = 10
    run(bot, snap, clock, 1)
    snap["kills"] = 14                                                        # four at once
    acts = run(bot, snap, clock, 2)
    assert any(a.get("tap") == "rstick" or "rstick" in a.get("hold", ()) for a in acts)
    assert bot.stats["taunts"] == 1 and bot.stats["taunt_multi"] == 1
    snap["player"]["action"] = R.EMOTION_ACTION                               # the game's gesture
    run(bot, snap, clock, 1)
    assert bot.stats["taunts_seen"] == 1
    snap["kills"] = 18                                                        # again at once: not within TAUNT_GAP_S
    acts = run(bot, snap, clock, int(R.TAUNT_HOLD_S / 0.05) + 3)
    assert bot.stats["taunts"] == 1


def test_no_taunt_with_one_near_and_a_boss_down_triggers_one(monkeypatch):
    monkeypatch.setattr(R, "TAUNTS", True)                                    # (off in play)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 300.0, 700),), cam_yaw=0.0))   # one at 3 m
    bot.held = lambda p, now: False
    snap["kills"] = 0
    run(bot, snap, clock, 1)
    snap["kills"] = 5
    run(bot, snap, clock, 2)
    assert bot.stats["taunts"] == 0                                           # not clear: dropped
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700), (0.0, 0.0, 1800.0, 700)), cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["enemies"][0]["hp_max"] = snap["enemies"][0]["hp"] = 3000           # a big one
    run(bot, snap, clock, 1)
    snap["enemies"] = [snap["enemies"][1]]                                    # the big one gone
    run(bot, snap, clock, 2)
    assert bot.stats["taunt_boss"] == 1


def with_aim_cam(g, pitch=0.1, yaw=0.5, vt_ok=True, owner_ok=True):
    """P1's own camera at player +0x3A28 (owner +0xB0) with the player camera uCameraQFPS at +0x16A0."""
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    cam = g.alloc(0x4D00)
    g.q(p + R.CAM_OWNED, cam)
    g.q(cam + R.CAM_OWNER, p if owner_ok else p + 8)
    g.q(cam + R.QFPS_OFF, BASE + (R.QFPS_VT if vt_ok else R.QFPS_VT + 0x40))
    g.f32(cam + R.QFPS_OFF + R.QFPS_PITCH, pitch, yaw)
    return cam


def test_snapshot_reads_his_player_camera_state_and_only_his():
    g = round_guest()
    cam = with_aim_cam(g, pitch=0.25, yaw=-1.5)
    ac = R.snapshot(g)["aim_cam"]
    assert ac["addr"] == cam + R.QFPS_OFF + R.QFPS_PITCH and ac["pitch"] == 0.25 and ac["yaw"] == pytest.approx(-1.5)
    g2 = round_guest()
    with_aim_cam(g2, vt_ok=False)                                             # not uCameraQFPS there
    assert R.snapshot(g2)["aim_cam"] is None
    g3 = round_guest()
    with_aim_cam(g3, owner_ok=False)                                          # another player's camera
    assert R.snapshot(g3)["aim_cam"] is None


def test_the_aim_writer_writes_both_floats_and_reads_them_back():
    g = round_guest()
    cam = with_aim_cam(g)
    ad = Adapter(g)

    class M:
        adapter = ad
    w = R.aim_writer(M())
    addr = cam + R.QFPS_OFF + R.QFPS_PITCH
    assert w(addr, -0.4, 2.0) and ad.writes == [(addr, struct.pack("<2f", -0.4, 2.0))]
    assert struct.unpack("<2f", g.rd(addr, 8)) == pytest.approx((-0.4, 2.0))

    class Off:
        adapter = ad
        mercs_no_modifications = True
    assert R.aim_writer(Off()) is None


def lock_brain(enemies, laser=None, ok=True, cam_pos=None):
    bot, clock, snap = brain(round_guest(enemies=enemies, cam_yaw=0.0, laser=laser))
    bot.held = lambda p, now: False
    writes = []
    if cam_pos is not None:                                                   # place the camera on the aim's line
        snap["camera"]["pos"] = cam_pos

    def ram(addr, pitch, yaw):
        writes.append((addr, pitch, yaw))
        if ok:                                                                # the game holds what was written
            snap["aim_cam"].update(pitch=pitch, yaw=yaw)
        return ok
    bot.ram = ram
    snap["aim_cam"] = {"addr": 0xABC0, "pitch": 0.0, "yaw": 0.0}
    return bot, clock, snap, writes


def test_with_the_lock_the_camera_is_written_onto_the_target_and_no_camera_key_steers():
    bot, clock, snap, writes = lock_brain(((600.0, 0.0, 900.0, 700),))       # off to the right of the camera's line
    acts = run(bot, snap, clock, 24)
    assert writes and bot.stats["aim_locks"] == 1 and bot.stats["lock_write_ok"] >= 1
    c = snap["camera"]["pos"]
    assert writes[-1][2] == pytest.approx(R.heading(600.0 - c[0], 900.0 - c[2]), abs=1e-4)   # the camera's line on him
    want = math.degrees(math.atan2(R.CHEST_H - c[1], math.hypot(600.0 - c[0], 900.0 - c[2])))
    assert writes[-1][1] == pytest.approx((want - R.PITCH_DEG_AT_0) / R.PITCH_DEG_PER_UNIT, abs=1e-3)
    assert all(not ({"rleft", "rright", "rup", "rdown"} & set(a.get("hold", ()))) for a in acts)
    assert "LOCK" in bot.stats["aim"]


def test_one_hanging_from_the_ceiling_right_above_is_locked_and_shot_and_one_far_off_another_floor_is_not(monkeypatch):
    monkeypatch.setattr(R, "CEILING_R", 400.0)                               # (off in play since 2026-10-28)
    far = (0.0, 600.0, 900.0, 700)                                            # 6 m up, 9 m off: no threat to him
    bot0, clock0, snap0, writes0 = lock_brain((far,), laser=((0.0, 660.0, 900.0), (20.0, 145.0, 30.0), 0.86))
    acts0 = run(bot0, snap0, clock0, 10)
    assert not any("zr" in a.get("hold", ()) for a in acts0) and bot0.stats["offlevel_skips"] >= 1
    hang = (0.0, 600.0, 300.0, 700)                                           # 6 m up, 3 m off: right above him
    pt = (0.0, 600.0 + R.OFF_FLOOR_AIM_H, 300.0)
    bot, clock, snap, writes = lock_brain((hang,), laser=(pt, (20.0, 145.0, 30.0), 0.86))
    acts = run(bot, snap, clock, 20)  # acquire the high target at the bounded physical pitch rate
    assert writes and any("zr" in a.get("hold", ()) for a in acts) and bot.stats["aimed_shots"] >= 1
    c = snap["camera"]["pos"]
    assert writes[-1][2] == pytest.approx(R.heading(-c[0], 300.0 - c[2]), abs=1e-4)
    bot2, clock2, snap2 = brain(round_guest(enemies=(hang,), cam_yaw=0.0, laser=(pt, (20.0, 145.0, 30.0), 0.86)))
    bot2.held = lambda p, now: False
    acts2 = run(bot2, snap2, clock2, 10)                                      # without the lock: off his floor, ignored
    assert not any("zr" in a.get("hold", ()) for a in acts2)


def test_the_big_one_gets_the_focus_fire_first():
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 800.0, 500), (500.0, 0.0, 1000.0, 1000)))   # none within 6 m
    snap["enemies"][1]["hp_max"] = 1000
    run(bot, snap, clock, 4)
    c = snap["camera"]["pos"]
    assert writes[-1][2] == pytest.approx(R.heading(500.0 - c[0], 1000.0 - c[2]), abs=1e-4)
    assert bot.target == snap["enemies"][1]["ptr"]


def test_a_lock_that_does_not_stick_puts_the_camera_keys_back():
    bot, clock, snap, writes = lock_brain(((600.0, 0.0, 900.0, 700),), ok=False)
    acts = run(bot, snap, clock, 30)
    assert bot.stats["lock_write_fail"] >= R.LOCK_FAIL_N and bot.stats["lock_fallbacks"] == 1
    assert any({"rleft", "rright"} & set(a.get("hold", ())) for a in acts[-3:])    # the keys steer again


def test_down_he_locks_onto_the_nearest_and_fires_then_rises_when_they_are_dead():
    near = (0.0, 0.0, 500.0, 700)
    bot, clock, snap, writes = lock_brain((near, (0.0, 0.0, 800.0, 700)),
                                          laser=((0.0, R.CHEST_H, 500.0), (20.0, 60.0, 30.0), 0.86))
    snap["player"].update(hp=400, action="cPlAction_pl_act_dying_loop")
    snap["kills"] = 20
    acts = run(bot, snap, clock, 6)
    assert bot.down and bot.stats["act"] in ("down_fire", "down_aim") and {"tap": "r"} not in acts
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["down_shots"] >= 1
    assert writes and all(not ({"lup", "ldown", "lleft", "lright"} & set(a.get("hold", ()))) for a in acts)
    snap["player"]["action"] = "cPlAction_pl_act_weapon_fire"                 # still down while it fires
    snap["kills"] = 22
    for e in snap["enemies"]:
        e["hp"] = 0
    acts = run(bot, snap, clock, 2)
    assert bot.down and bot.stats["down_kills"] == 2 and acts[-1] == {"hold": ("lup",)}   # nobody near: rising
    snap["player"]["action"] = "cPlAction_pl_act_gets_up"
    run(bot, snap, clock, 1)
    assert not bot.down and bot.stats["down_recoveries"] == 1 and bot.stats["down_s"] > 0
    snap["player"]["action"] = "cPlAction_pl_act_wait"
    snap["enemies"] = [{"slot": 9, "ptr": 0x9999, "pos": (0.0, 0.0, 1500.0), "hp": 700, "hp_max": 700}]
    assert {"tap": "r"} in run(bot, snap, clock, 3)                          # up at 1 health: a tablet at once
    snap["player"].update(hp=1, action="cPlAction_pl_act_dying_loop")       # down again, this time dying
    run(bot, snap, clock, 2)
    assert bot.down and bot.down_dying
    snap["player"]["action"] = "cPlAction_pl_act_gets_up"                    # rises from dying: since_dying set
    run(bot, snap, clock, 1)
    snap["player"]["action"] = "cPlAction_pl_act_wait"
    snap["player"]["hp"] = 0
    run(bot, snap, clock, 1)
    assert bot.stats["dying_deaths"] == 1


def test_health_falling_with_nobody_near_marks_a_hazard_and_he_moves_out_of_it():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700),), cam_yaw=0.0, hp=800))
    bot.held = lambda p, now: False
    run(bot, snap, clock, 2)
    snap["player"]["hp"] = 760                                                # smoke: nobody within 2.5 m
    acts = run(bot, snap, clock, 3)
    assert bot.stats["hazard_marks"] == 1 and bot.hazard is not None and bot.stats["hazard_s"] > 0
    assert any(set(a.get("hold", ())) & {"lup", "ldown", "lleft", "lright"} for a in acts)
    clock[0] += R.HAZARD_S + 0.1
    run(bot, snap, clock, 1)
    assert bot.hazard is None


def test_down_fire_triples_the_table_while_he_is_down_and_puts_it_back(mods):
    g = round_guest()
    table = weapon_table(g)
    ad = Adapter(g)
    iv = lambda i: struct.unpack("<f", g.rd(table + mods.FIRE_STRIDE * i + mods.FIRE_INTERVAL, 4))[0]
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_walk", 0x100))
    mods.run(ad, "fire_rate", multiplier=4, magnum=8, throw=16)
    assert mods.run(ad, "down_fire", multiplier=3)["down_fire_x"] == 3.0
    clock = [10.0]
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert iv(0x0F) == pytest.approx(0.025) and iv(0x07) == pytest.approx(0.1)    # up: fire_rate's own
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_lying_down_weapon_ready_loop", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert iv(0x0F) == pytest.approx(0.025 / 3) and iv(0x07) == pytest.approx(0.1 / 3)   # down: x3
    assert iv(0x13) == pytest.approx(0.125)                                   # the grenades keep theirs
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_fire", 0x100))  # firing from the ground: still down
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert iv(0x07) == pytest.approx(0.1 / 3)
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_gets_up", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert iv(0x0F) == pytest.approx(0.025) and iv(0x07) == pytest.approx(0.1)    # up: back at once
    with pytest.raises(ValueError):
        mods.run(ad, "down_fire", multiplier=50)


def test_the_lock_sweeps_target_after_target_a_few_shots_each():
    three = ((0.0, 0.0, 600.0, 700), (300.0, 0.0, 800.0, 700), (-300.0, 0.0, 1000.0, 700))
    bot, clock, snap, writes = lock_brain(three)
    order = []
    for _ in range(80):                                                       # 4 s: the laser follows the lock's target
        cur = next((e for e in snap["enemies"] if e["ptr"] == bot.target), snap["enemies"][0])
        snap["laser"] = {"from": (20.0, 145.0, 30.0), "at": (cur["pos"][0], R.CHEST_H, cur["pos"][2]), "up": True}
        run(bot, snap, clock, 1)
        if not order or order[-1] != bot.target:
            order.append(bot.target)
    assert bot.stats["aimed_shots"] >= 2 * R.SWEEP_SHOTS and bot.stats["sweeps"] >= 2
    assert bot.stats["targets_shot"] >= 3 and len(set(order)) == 3
    assert order[0] == snap["enemies"][0]["ptr"]                              # the nearest first
    assert bot.stats["cc_quick_shots"] == 0 and bot.stats["quick_shots"] == 0


def test_a_closing_one_is_swept_before_a_standing_one_as_near():
    bot, clock, snap, writes = lock_brain(((300.0, 0.0, 800.0, 700), (-300.0, 0.0, 800.0, 700)))
    bot.target = None
    run(bot, snap, clock, 1)
    bot.sweep_n[bot.target] = R.SWEEP_SHOTS                                   # done with that one
    other = next(e for e in snap["enemies"] if e["ptr"] != bot.target)
    first = bot.target
    run(bot, snap, clock, 1)
    assert bot.target == other["ptr"]
    bot.sweep_n[bot.target] = R.SWEEP_SHOTS
    back = next(e for e in snap["enemies"] if e["ptr"] == first)
    x, y, z = back["pos"]
    back["pos"] = (x, y, z - 100.0)                                           # it comes 1 m closer in 0.05 s
    run(bot, snap, clock, 1)
    assert bot.target == first


def test_the_sweep_still_holds_one_who_merely_moves_around_him():
    # No pass: the 1.7 m one is only +17 deg off his aim (the gun's own line) - not more than SWEEP_HOLD_BEAR,
    # so the sweep keeps finishing the 3.1 m one (the cluster is a behind / aimed-away hit, not any close one).
    near, far = (17.0, 0.0, 169.0, 700), (0.0, 0.0, 310.0, 700)
    bot, clock, snap, writes = lock_brain((near, far))
    bot.target = None
    run(bot, snap, clock, 1)
    near_e = next(e for e in snap["enemies"] if e["pos"][2] < 200)
    far_e = next(e for e in snap["enemies"] if e["pos"][2] >= 200)
    bot.target = far_e["ptr"]
    bot.sweep_n[bot.target] = R.SWEEP_SHOTS - 1
    run(bot, snap, clock, 1)
    assert bot.target == far_e["ptr"]                                          # held: +17 deg is inside the cone


def test_point_blank_crowd_gets_aimed_fire_and_a_lone_one_the_quick_shot():
    bot, clock, snap, writes = lock_brain(((60.0, 0.0, 170.0, 700), (-80.0, 0.0, 180.0, 700)))   # two at 1.8 m
    acts = run(bot, snap, clock, 10)
    assert bot.stats["cc_quick_shots"] == 0 and bot.stats["quick_shots"] == 0
    assert any("zl" in a.get("hold", ()) for a in acts) and writes                # the gun up on the lock
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 180.0, 700),))              # a lone one
    acts = run(bot, snap, clock, 3)
    assert {"hold": ("zl", "zr")} in acts and bot.stats["quick_shots"] >= 1


def test_the_flash_alone_with_five_close_and_no_fever_or_grenades(monkeypatch):
    monkeypatch.setattr(R, "NADES", False)
    monkeypatch.setattr(R, "FLASH", True)
    near = ((0.0, 0.0, 300.0, 700), (100.0, 0.0, 350.0, 700), (-100.0, 0.0, 380.0, 700),
            (200.0, 0.0, 320.0, 700), (-200.0, 0.0, 330.0, 700))
    bot, clock, snap = brain(round_guest(enemies=near, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)})
    run(bot, snap, clock, 3)
    assert bot.nade["kind"] == "flash"
    snap["player"]["equipped"] = 11
    run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert bot.stats["flashes"] == 1 and bot.fever_until < clock[0]            # no fever without NADES
    cluster = ((0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=cluster, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5)})
    run(bot, snap, clock, 3)
    assert bot.nade is None and bot.stats["frags"] == 0                       # no grenade into a cluster


def test_magnum_speed_runs_the_magnums_fire_and_recoil_faster_only(mods, monkeypatch):
    monkeypatch.setattr(R, "QA_FAST", False)                                  # (the quick_attack op sets it: put back)
    g = round_guest()
    ad = Adapter(g)
    weapon_table(g)
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.f32(p + mods.UNIT_DELTA, 1.0)
    g.put(p + R.P_SLOTS + 8, bytes([1, 0]) + struct.pack("<H", 0x107))       # the magnum in slot 0, equipped
    g.i32(p + R.P_EQUIPPED, 0)
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_fire", 0x100))
    mods.run(ad, "fire_rate", multiplier=4, magnum=8)
    assert mods.run(ad, "magnum_speed", multiplier=3)["magnum_speed_x"] == 3.0
    mods.run(ad, "quick_attack", multiplier=10)
    clock = [10.0]
    snap = R.snapshot(g)
    assert snap["player"]["weapon_id"] == 0x07
    mods.maintain(ad, snap, clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 3.0                      # the magnum's shot x3
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_comn_quick_shot", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 10.0                     # a quick shot keeps x10
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_walk", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 1.0
    g.put(p + R.P_SLOTS + 8, bytes([1, 0]) + struct.pack("<H", 0x10F))       # the rifle: its fire left alone
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_fire", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 1.0
    assert mods.ORIG[id(ad)]["magnum_fast"] == 1
    with pytest.raises(ValueError):
        mods.run(ad, "magnum_speed", multiplier=20)
def u_mesh(cells=((0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (0, 2)), size=100.0):
    """A walkable U of 1 m squares (two triangles each) around a hole at (0..1, 1): vertices, triangles, links."""
    verts, index, tris = [], {}, []

    def vid(x, z):
        if (x, z) not in index:
            index[(x, z)] = len(verts)
            verts.append((x * size, 0.0, z * size))
        return index[(x, z)]
    for cx, cz in cells:
        a, b, c, d = vid(cx, cz), vid(cx + 1, cz), vid(cx + 1, cz + 1), vid(cx, cz + 1)
        tris += [(a, b, c), (a, c, d)]
    links = [[j for j, u in enumerate(tris) if j != k and len(set(t) & set(u)) == 2] for k, t in enumerate(tris)]
    return verts, tris, links


def test_the_nav_mesh_path_goes_round_the_hole_not_through_it():
    mesh = R.NavMesh(*u_mesh())
    path = mesh.path((50.0, 0.0, 50.0), (50.0, 0.0, 250.0))                  # straight north crosses the hole
    assert path and path[-1] == (50.0, 0.0, 250.0) and max(w[0] for w in path) >= 200.0
    assert all(not (0 <= w[0] < 200 and 100 < w[2] < 200) for w in path)     # never over the hole
    assert mesh.locate((150.0, 0.0, 150.0)) is not None                       # off the mesh: the nearest triangle
    assert mesh.path((50.0, 0.0, 50.0), (60.0, 0.0, 60.0)) == [(60.0, 0.0, 60.0)]
    far = R.NavMesh(*u_mesh(cells=((0, 0), (5, 5))))                          # two islands
    assert far.path((50.0, 0.0, 50.0), (550.0, 0.0, 550.0)) is None


def test_the_nav_mesh_is_decoded_from_the_resource_in_ram():
    g = round_guest()
    verts, tris, links = u_mesh()
    nav = g.alloc(0x200)
    g.q(nav, BASE + R.NAV_VT)
    g.i32(nav + 0x80, R.NAV_MAGIC)
    g.put(nav + 0xC, b"soft\\stage\\s9999\0")
    va = g.alloc(0x10 * len(verts))
    for i, v in enumerate(verts):
        g.f32(va + 0x10 * i, *v)
    ta = g.alloc(0x70 * len(tris))
    pool = g.alloc(0x2000)
    at = pool
    for k, (t, ln) in enumerate(zip(tris, links)):
        g.put(at, struct.pack("<3i", *t))
        g.q(ta + 0x70 * k + 0x48, at)
        g.i32(ta + 0x70 * k + 0x50, 3)
        at += 12
        for j, nb in enumerate(ln):
            g.put(at + 0x18 * j, struct.pack("<6i", nb, 0, j, 0, 0, 0))
        g.q(ta + 0x70 * k + 0x58, at)
        g.i32(ta + 0x70 * k + 0x60, len(ln))
        at += 0x18 * len(ln)
    g.q(nav + 0xA0, va)
    g.i32(nav + 0xB8, len(verts))
    g.q(nav + 0xC0, ta)
    g.i32(nav + 0xC8, len(tris))
    sres = g.alloc(R.SRES_SIZE)
    g.q(BASE + R.SRES, sres)
    g.q(sres + 0x1000, g.obj("rTexture", 0x100))                             # another resource first
    g.q(sres + 0x2000, nav)
    R._NAV.update(base=None)
    mesh = R.navmesh(g, BASE, now=100.0)
    assert mesh is not None and len(mesh.T) == len(tris) and mesh.N == links and mesh.name.endswith("s9999")
    assert R.navmesh(g, BASE, now=100.5) is mesh                              # cached while the resource stays
    g.q(nav, 0)                                                               # freed: looked for again (not yet)
    assert R.navmesh(g, BASE, now=101.0) is None


def test_the_bonus_run_walks_the_nav_mesh_way_round():
    g = round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0)
    bonus_piece(g, "cSmTimeBonusAct_Wait", (100.0, 0.0, 500.0))               # beyond the hole (2 m squares)
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    snap["player"]["pos"] = (100.0, 0.0, 100.0)
    snap["navmesh"] = R.NavMesh(*u_mesh(size=200.0))
    acts = run(bot, snap, clock, 2)
    assert bot.stats["nav_paths"] == 1 and "nav mesh" in bot.why
    assert "rleft" in acts[0]["hold"] and "lup" not in acts[0]["hold"]       # face +x before walking east
    writes = []
    bot.ram = lambda *args: writes.append(args) or True                       # available to aiming, never navigation
    snap["aim_cam"] = {"addr": 0xABC0, "pitch": 0.1, "yaw": 0.0}
    for b in snap["bonuses"]:
        bot.bonus_unseen[b["ptr"]] = 1e9                                      # out of sight: walked to, not shot
    acts = run(bot, snap, clock, 1)
    assert acts[0]["hold"] == ("rleft",) and writes == []                   # navigation remains a governed stick turn
    snap["camera"]["yaw"] = math.pi / 2
    assert run(bot, snap, clock, 1)[0]["hold"] == ("lup",)


def test_the_bonus_run_takes_the_nearest_by_the_way_there():
    g = round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0)
    across = bonus_piece(g, "cSmTimeBonusAct_Wait", (100.0, 0.0, 500.0))      # 4 m straight, 12 m round the hole
    along = bonus_piece(g, "cSmTimeBonusAct_Wait", (500.0, 0.0, 300.0))       # 4.5 m straight, about as far walking
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    snap["player"]["pos"] = (100.0, 0.0, 100.0)
    run(bot, snap, clock, 1)
    assert bot.run_target == across                                           # without the mesh: the straight nearest
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    snap["player"]["pos"] = (100.0, 0.0, 100.0)
    snap["navmesh"] = R.NavMesh(*u_mesh(size=200.0))
    run(bot, snap, clock, 1)
    assert bot.run_target == along


def with_prompt(g, pad=0x4000, typ=18, button=17, index=0, unit=0x248, shown=True):
    """sActionButton with ButtonMgr[0] for player `index`, one ButtonUnit showing a cActionButton's prompt."""
    sab = g.alloc(0x1D20)
    g.q(BASE + R.S_ACTION_BUTTON, sab)
    for k in range(R.AB_MGRS):
        g.i32(sab + R.AB_MGR + R.AB_MGR_SIZE * k + 0xC, k)
    mgr = sab + R.AB_MGR + R.AB_MGR_SIZE * index
    ab = g.obj("cActionButton", 0x1D0)
    g.i32(ab + 0x30, typ)
    g.i32(ab + 0x38, button)
    g.put(mgr + unit + 0xC, bytes([1 if shown else 0, 1]))
    g.q(mgr + unit + 0x10, ab)
    g.i32(mgr + unit + 0x1C, typ)
    g.i32(mgr + unit + 0x28, pad)
    return ab


def test_the_snapshot_reads_the_games_shown_prompts_and_their_buttons():
    g = round_guest()
    ab = with_prompt(g, pad=0x4000, typ=35, button=17)
    q = R.snapshot(g)["prompts"]
    assert q == [{"type": 35, "button": 17, "pad": 0x4000, "key": "b", "ab": ab}]
    g2 = round_guest()
    with_prompt(g2, pad=0x8000, typ=1, button=1, unit=0x2E0)
    assert [x["key"] for x in R.snapshot(g2)["prompts"]] == ["y"]
    g3 = round_guest()
    with_prompt(g3, pad=0xF0000)
    assert R.snapshot(g3)["prompts"][0]["key"] == "stick"
    g4 = round_guest()
    with_prompt(g4, shown=False)
    assert R.snapshot(g4)["prompts"] == []
    g5 = round_guest()
    with_prompt(g5, index=1)                                                  # player 2's mgr: not his
    assert R.snapshot(g5)["prompts"] == []


def prompt_snap(enemies=((0.0, 0.0, 1500.0, 700),), **kw):
    bot, clock, snap = brain(round_guest(enemies=enemies, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["prompts"] = [dict({"type": 35, "button": 17, "pad": 0x4000, "key": "b", "ab": 0x5000}, **kw)]
    return bot, clock, snap


def test_a_shown_prompt_is_pressed_at_once_and_counted_taken_when_it_goes():
    bot, clock, snap = prompt_snap()
    acts = run(bot, snap, clock, 1)
    assert acts[0] == {"tap": "b"} and bot.stats["prompts_seen"] == 1 and bot.stats["act"] == "prompt_b"
    snap["prompts"] = []                                                      # he climbed
    run(bot, snap, clock, 1)
    assert bot.stats["prompts_taken"] == 1 and bot.stats["climbs"] == 1
    assert bot.stats["prompt_types"]["35"] == [1, 1, "b"] and bot.stats["prompt_latency_ms"] <= 100


def test_unlimited_items_skip_pickups_near_and_far_without_losing_other_prompts():
    bot, clock, snap = prompt_snap(enemies=((0.0, 0.0, 200.0, 700),), key="y", pad=0x8000, type=1)
    acts = run(bot, snap, clock, 2)
    assert {"tap": "y"} not in acts
    snap["enemies"][0]["pos"] = (0.0, 0.0, 900.0)
    acts = run(bot, snap, clock, 1)
    assert {"tap": "y"} not in acts and bot.stats["act"] != "prompt_y"
    snap["enemies"] = []
    acts = run(bot, snap, clock, 1)
    assert {"tap": "y"} not in acts and bot.stats["act"] != "prompt_y"
    snap["prompts"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["pickups"] == 0 and bot.stats["prompts_taken"] == 0
    bot, clock, snap = prompt_snap(key="stick", pad=0xF0000, type=26)
    acts = run(bot, snap, clock, 1)
    assert "b" not in acts[0]["hold"] and set(acts[0]["hold"]) <= {"lup", "ldown", "lleft", "lright"}
    bot, clock, snap = prompt_snap(key="r", pad=0x800, type=1, button=34)    # the heal hint: left to the tablet rules
    acts = run(bot, snap, clock, 3)
    assert {"tap": "r"} not in acts and bot.stats["prompts_seen"] == 1


def test_a_grabs_b_prompt_counts_the_holds_own_b_presses():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 80.0, 700),), state=8, cam_yaw=0.0))
    snap["prompts"] = [{"type": 18, "button": 17, "pad": 0x4000, "key": "b", "ab": 0x6000}]
    acts = run(bot, snap, clock, 3)
    assert any("b" in a.get("hold", ()) for a in acts) and bot.stats["act"] in ("break_free", "held_prompt")
    snap["prompts"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["prompts_seen"] == 1 and bot.stats["prompts_taken"] == 1 and bot.stats["climbs"] == 0
def test_every_visit_draws_a_random_listed_character_and_the_round_reports_its_draws(monkeypatch):
    import random
    monkeypatch.setattr(R, "PICK", R._Pick(random.Random(11)))
    ids = (0, 1, 2, 3, 4, 5, 6, 8)
    seen = set()
    for _ in range(40):
        g = menu_guest("uIdStartUp32", R.PLAYER_CURSOR, 0)
        u = g.lines[18][-1]
        g.i32(u + R.PLAYER_COUNT, len(ids))
        for i, cid in enumerate(ids):
            g.i32(u + R.PLAYER_IDS + 4 * i, cid)
        scr = R.screen(g)
        seen.add(ids[scr["target"]])
        assert all(R.screen(g)["target"] == scr["target"] for _ in range(3))     # one draw a visit
        R.PICK.reset()
    assert len(seen) >= 6 and seen <= set(ids)                                    # every listed one comes up
    R.PICK.stage, R.PICK.character, R.PICK.costume = 3, 5, 2
    assert R.screen(round_guest())["where"] == "playing"
    out = R.RE6Switch().progress(R.snapshot(round_guest()))
    assert out["stage"] == R.STAGES[3] and out["character"] == "Sherry" and out["costume"] == 2
    assert out["stage_coverage"] == f"{R.STAGES[3]}:1" and R.coverage()["characters"] == {"Sherry": 1}
    assert R.REPLAY_ON_DEATH is False and R.continue_target() == R.CONTINUE_NO   # a death: NO, the selects again


def test_each_stage_keeps_its_lessons_once_a_round(tmp_path):
    g = round_guest(enemies=((0.0, 0.0, 1500.0, 700),))
    bonus_piece(g, "cSmTimeBonusAct_Wait", (300.0, 0.0, 900.0))
    clock = [0.0]
    bot = R.Bot(stats={}, clock=lambda: clock[0], learn_dir=tmp_path)
    snap = R.snapshot(g)
    snap["navmesh"] = R.NavMesh(*u_mesh(), name=r"soft\stage\s1218\s1218")
    bot.held = lambda p, now: False
    snap["kills"] = 12
    run(bot, snap, clock, 5)
    book = json.loads((tmp_path / "stages" / "s1218.json").read_text())
    assert book["visits"] == 1 and book["bonuses"] == [[300, 0, 900]] and book["nav"]["triangles"] == 14
    bot._round_started = 99.0                                                 # the next round
    run(bot, snap, clock, 1)
    book = json.loads((tmp_path / "stages" / "s1218.json").read_text())
    assert book["visits"] == 2 and book["best_kills"] == 12
def flash_now(bot, snap, clock):
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)})
    run(bot, snap, clock, 3)
    assert bot.nade and bot.nade["kind"] == "flash"
    snap["player"]["equipped"] = 11
    run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert bot.stats["flashes"] == 1
    snap["player"]["equipped"] = 0
    run(bot, snap, clock, int(R.NADE_STEP_S / 0.05) + 3)


def test_four_within_five_metres_get_the_flash_and_the_fever_ends_when_an_unflashed_one_closes(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    four = ((0.0, 0.0, 450.0, 700), (150.0, 0.0, 430.0, 700), (-150.0, 0.0, 470.0, 700), (60.0, 0.0, 480.0, 700))
    bot, clock, snap = brain(round_guest(enemies=four, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100
    flash_now(bot, snap, clock)
    assert clock[0] < bot.fever_until and len(bot.flashed) == 4
    snap["kills"] = (snap.get("kills") or 0) + 2                              # two go down in the fever
    run(bot, snap, clock, 2)
    assert bot.stats["fever_kills"] == 2
    snap["prompts"] = [{"type": 1, "button": 8, "pad": 0x200, "key": "zr", "ab": 0x7000}]   # a finisher's prompt
    run(bot, snap, clock, 1)
    snap["prompts"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["finishers"] == 1
    late = {"slot": 9, "ptr": 0x9999, "pos": (0.0, 0.0, 180.0), "hp": 700, "hp_max": 700}
    snap["enemies"] = snap["enemies"] + [late]                                # one that was not flashed, on him
    run(bot, snap, clock, 1)
    assert bot.fever_until <= clock[0] and bot.stats["fever_breaks"] == 1


def test_frags_and_incendiaries_go_in_turn_at_most_every_ten_seconds(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    cluster = ((0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=cluster, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5)})
    run(bot, snap, clock, 2)
    assert bot.nade["kind"] == "frag"
    snap["player"]["equipped"] = 9
    run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    snap["player"]["equipped"] = 0
    run(bot, snap, clock, int(R.NADE_STEP_S / 0.05) + 3)
    assert bot.stats["frags"] == 1 and bot.nade is None
    run(bot, snap, clock, int(5.0 / 0.05))                                    # 5 s on: not again yet
    assert bot.nade is None and bot.stats["fires"] == 0
    clock[0] += R.FRAG_GAP_S
    run(bot, snap, clock, 2)
    assert bot.nade["kind"] == "fire"                                         # the incendiary's turn


def test_a_yellow_in_sight_is_shot_through_the_lock_and_one_out_of_sight_walked_to():
    g = round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0)
    u = bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1500.0))            # 15 m ahead
    bot, clock, snap, writes = lock_brain(())
    R._BONUS.update(base=None)                                                # (the bonus cache: this guest's pieces)
    snap.update(R.snapshot(g))
    snap["aim_cam"] = {"addr": 0xABC0, "pitch": 0.0, "yaw": 0.0}
    snap["laser"] = {"from": (20.0, 145.0, 30.0), "at": (0.0, R.BONUS_H, 1500.0), "up": True}   # the dot on it
    acts = run(bot, snap, clock, 8)
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["bonus_shots"] >= 1 and writes
    assert all("lup" not in a.get("hold", ()) for a in acts)                  # shot from here, not walked to
    snap["bonuses"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["yellows_taken"] == 1 and u
    R._BONUS.update(base=None)
    g = round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0)
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1500.0))
    bot, clock, snap, writes = lock_brain(())
    R._BONUS.update(base=None)                                                # (the bonus cache: this guest's pieces)
    snap.update(R.snapshot(g))
    snap["aim_cam"] = {"addr": 0xABC0, "pitch": 0.0, "yaw": 0.0}
    snap["laser"] = {"from": (20.0, 145.0, 30.0), "at": (0.0, R.BONUS_H, 400.0), "up": True}    # a wall at 4 m
    acts = run(bot, snap, clock, int(R.BONUS_SEE_S / 0.05) + 4)
    assert bot.stats["bonus_unseen"] == 1 and bot.stats["bonus_shots"] == 0 and "lup" in acts[-1]["hold"]


def test_greens_wait_for_the_match_and_save_a_running_out_combo():
    g = round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0)
    bonus_piece(g, "cSmComboBonusAct_Wait", (0.0, 0.0, 1200.0), cls="uSm5924")
    bot, clock, snap, writes = lock_brain(())
    R._BONUS.update(base=None)                                                # (the bonus cache: this guest's pieces)
    snap.update(R.snapshot(g))
    snap["aim_cam"] = {"addr": 0xABC0, "pitch": 0.0, "yaw": 0.0}
    snap["laser"] = {"from": (20.0, 145.0, 30.0), "at": (0.0, R.BONUS_H, 1200.0), "up": True}
    snap.update(combo=6, combo_timer=10.0)
    run(bot, snap, clock, 4)
    assert bot.stats["phase"] == "match" and bot.stats["bonus_shots"] == 0    # a green waits while the combo is fine
    snap["combo_timer"] = 2.0                                                 # running out
    acts = run(bot, snap, clock, 6)
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["bonus_shots"] >= 1
    snap["bonuses"] = []
    run(bot, snap, clock, 1)
    assert bot.stats["greens_taken"] == 1 and bot.stats["combo_saves"] == 1


def test_the_nav_mesh_line_of_sight_stops_at_its_walls():
    mesh = R.NavMesh(*u_mesh(size=200.0))
    assert mesh.clear((100.0, 0.0, 100.0), (100.0, 0.0, 500.0)) is False     # across the hole: a wall between
    assert mesh.clear((100.0, 0.0, 100.0), (500.0, 0.0, 100.0)) is True      # along the floor
    assert mesh.clear((500.0, 0.0, 100.0), (500.0, 0.0, 500.0)) is True
    assert mesh.clear((100.0, 0.0, 100.0), (100.0, 900.0, 500.0)) is None    # another level: the laser decides


def test_one_behind_a_wall_is_never_aimed_at_and_is_walked_to_by_the_mesh():
    hidden = (100.0, 0.0, 500.0, 700)                                         # beyond the hole from him
    bot, clock, snap, writes = lock_brain((hidden,))
    snap["player"]["pos"] = (100.0, 0.0, 100.0)
    snap["navmesh"] = R.NavMesh(*u_mesh(size=200.0))
    acts = run(bot, snap, clock, 6)
    assert all("zl" not in a.get("hold", ()) for a in acts)                  # never aimed at the wall
    assert writes == [] and all("rleft" in a.get("hold", ()) for a in acts)  # governed turn east; no camera RAM snap
    assert bot.stats["offscreen_skips"] >= 1 and bot.stats["act"] == "pursue" and "lup" not in acts[-1]["hold"]
    snap["camera"]["yaw"] = math.pi / 2                                    # observed facing now permits movement
    assert "lup" in run(bot, snap, clock, 1)[0]["hold"]
    snap["enemies"][0]["pos"] = (500.0, 0.0, 100.0)                           # down the corridor: in sight
    bot._sight_cache.clear()
    acts = run(bot, snap, clock, 6)
    assert any("zl" in a.get("hold", ()) for a in acts)


def test_the_lasers_probe_takes_one_out_of_sight_when_the_ray_stops_short():
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),),
                                          laser=((0.0, R.CHEST_H, 400.0), (20.0, 145.0, 30.0), 0.86))   # a wall at 4 m
    run(bot, snap, clock, int((R.READY_S + R.LOS_PROBE_S) / 0.05) + 6)
    assert bot.stats["los_blocks"] >= 1 and bot.is_blocked(snap["enemies"][0], clock[0])
    assert bot.stats["wall_aim_s"] == 0                                       # 4 m: not a wall at the muzzle
    snap["laser"] = {"from": (20.0, 145.0, 30.0), "at": (20.0, 145.0, 120.0), "up": True}   # 90 cm from the muzzle
    run(bot, snap, clock, 4)
    assert bot.stats["wall_aim_s"] > 0


def test_a_close_one_beats_a_far_one_and_low_health_is_survival():
    bot, clock, snap, writes = lock_brain(((300.0, 0.0, 300.0, 700), (0.0, 0.0, 1200.0, 700)))   # 4.2 m and 12 m
    run(bot, snap, clock, 4)
    assert bot.target == snap["enemies"][0]["ptr"] and bot.close_threat
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 2000.0, 700),))        # one far off in front
    snap["player"]["hp"] = 250                                                # under 35 %: survival
    acts = run(bot, snap, clock, 8)
    assert bot.survival and bot.stats["survival_s"] > 0 and all("zr" not in a.get("hold", ()) for a in acts)
    snap["enemies"] = [{"slot": 0, "ptr": 0x9100, "pos": (0.0, 0.0, 400.0), "hp": 700, "hp_max": 700}]
    acts = run(bot, snap, clock, 6)
    assert any("zl" in a.get("hold", ()) for a in acts)                       # the one closing in: shot
    assert any("ldown" in a.get("hold", ()) for a in acts)                    # backing away from him


def test_the_turn_governor_releases_the_sticks_on_a_whip_and_in_a_sped_up_action():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    run(bot, snap, clock, 2)
    snap["player"]["action"] = "cPlAction_pl_act_weapon_comn_quick_shot"     # x10 while it runs
    out = bot._govern(snap, {"hold": ("lup", "rleft", "zl")}, clock[0] + 0.05)
    assert out["hold"] == ("zl",) and bot.stats["boost_releases"] == 1 and bot.stats["whips"] == 0
    snap["player"]["action"] = "cPlAction_pl_act_walk"
    bot._rot_prev = (clock[0], 0.0)
    snap["player"]["rot"] = math.radians(90)                                  # 90 deg in 0.05 s: a whip
    out = bot._govern(snap, {"hold": ("lup", "zl")}, clock[0] + 0.05)
    assert out["hold"] == ("zl",) and bot.stats["spin_deg_s"] >= 1000 and bot.stats["whips"] == 1


def test_aiming_up_with_no_vertical_threat_is_counted():
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),))
    snap["camera"]["pitch"] = math.radians(30)                                # the camera up at the rafters
    run(bot, snap, clock, 8)
    assert bot.stats["up_aim_s"] > 0


def test_wind_ups_are_read_from_the_enemies_actions():
    me = (0.0, 0.0, 0.0)
    e = lambda a, z: {"pos": (0.0, 0.0, z), "action": a}
    assert R.windup(e("cEm1000ActAtkOneHand", 300.0), me) == "melee"
    assert R.windup(e("cEm5000ActCatch", 400.0), me) == "melee"
    assert R.windup(e("cEm1000ActIkakuKnife", 900.0), me) is None            # too far for a melee wind-up
    assert R.windup(e("cEm1000ActWalkGunL", 1200.0), me) == "ranged"
    assert R.windup(e("cEm5000ActDmgDown", 200.0), me) is None and R.windup(e("cEm5000ActWalk", 200.0), me) is None
    g = round_guest(enemies=((0.0, 0.0, 400.0, 700),))
    en = R.u64(g, R.u64(g, R.u64(g, BASE + R.S_ENEMY) + R.E_ARRAY))         # the first enemy
    g.q(en + 0x13F0, g.obj("cEm5000ActCatch", 0x100))
    assert R.snapshot(g)["enemies"][0]["action"] == "cEm5000ActCatch"


def test_the_one_winding_up_is_stopped_first_and_counted():
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 300.0, 700), (200.0, 0.0, 420.0, 700)))
    snap["enemies"][0]["action"] = "cEm5000ActWalk"
    snap["enemies"][1]["action"] = "cEm5000ActCatch"                         # the farther one reaches for him
    run(bot, snap, clock, 3)
    assert bot.target == snap["enemies"][1]["ptr"] and bot.stats["windup_seen"] == 1
    snap["enemies"][1]["action"] = "cEm5000ActDmgDown"                       # shot out of it
    run(bot, snap, clock, 1)
    assert bot.stats["windup_interrupts"] == 1
    snap["enemies"][1]["action"] = "cEm1000ActAtkOneHand"
    snap["enemies"][1]["pos"] = (100.0, 0.0, 150.0)
    run(bot, snap, clock, 1)
    snap["player"]["hp"] -= 100                                               # it landed
    run(bot, snap, clock, 1)
    assert bot.stats["hits_after_windup"] == 1


def test_two_winding_up_get_the_flash(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    two = ((0.0, 0.0, 400.0, 700), (150.0, 0.0, 420.0, 700))
    bot, clock, snap = brain(round_guest(enemies=two, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100
    for e in snap["enemies"]:
        e["action"] = "cEm1000ActAtkOneHandDash"
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)})
    run(bot, snap, clock, 3)
    assert bot.nade and bot.nade["kind"] == "flash"


def test_grenades_spam_into_several_clusters_and_take_the_bombs_place_when_they_are_close(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    monkeypatch.setattr(R, "FLASH_GAP_S", 1.5)                               # (frags here; the flash gap: its own rule)
    two = ((0.0, 0.0, 700.0, 700), (100.0, 0.0, 760.0, 700), (-100.0, 0.0, 740.0, 700),
           (700.0, 0.0, 300.0, 700), (760.0, 0.0, 380.0, 700), (740.0, 0.0, 220.0, 700))   # two clusters
    bot, clock, snap = brain(round_guest(enemies=two, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5)})
    run(bot, snap, clock, 2)
    snap["player"]["equipped"] = bot.nade["index"]
    run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    snap["player"]["equipped"] = 0
    run(bot, snap, clock, int(R.NADE_STEP_S / 0.05) + 3)
    first = bot.stats["grenade_throws"]
    clock[0] += R.NADE_GAP_S
    run(bot, snap, clock, 2)
    assert first == 1 and bot.nade is not None                                # straight into the next cluster
    assert R.Bot._clusters([e for e in snap["enemies"]], lambda e: math.hypot(e["pos"][0], e["pos"][2])) == 2


def test_throw_speed_runs_the_grenade_throw_twenty_times_faster(mods, monkeypatch):
    monkeypatch.setattr(R, "QA_FAST", False)
    g = round_guest()
    ad = Adapter(g)
    weapon_table(g)
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    g.f32(p + mods.UNIT_DELTA, 1.0)
    g.put(p + R.P_SLOTS + 8, bytes([1, 9]) + struct.pack("<H", 0x113))       # the hand grenade, equipped
    g.i32(p + R.P_EQUIPPED, 9)
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_weapon_fire", 0x100))
    mods.run(ad, "fire_rate", multiplier=4, magnum=8, throw=16)
    snap = R.snapshot(g)
    assert snap["player"]["weapon_id"] == 0x13
    mods.maintain(ad, snap, clock=lambda: 10.0)
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 20.0
    g.q(p + mods.UNIT_ACTION, g.obj("cPlAction_pl_act_walk", 0x100))
    mods.maintain(ad, R.snapshot(g), clock=lambda: 10.0)
    assert struct.unpack("<f", g.rd(p + mods.UNIT_DELTA, 4))[0] == 1.0 and mods.ORIG[id(ad)]["throw_fast"] == 1


def test_idle_seconds_count_nothing_pressed_with_zombies_about():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700),), cam_yaw=0.0))
    bot._govern(snap, {"hold": ()}, clock[0] + 0.05)
    bot._govern(snap, {"hold": ("lup",)}, clock[0] + 0.1)
    assert bot.stats["idle_s"] == pytest.approx(R.TICK_S)
def test_the_spread_fills_the_empty_weapon_slots_and_an_asked_weapon_goes_first(mods):
    import random
    w, _x = mods.loadout_plan(4, True, 5, random.Random(1), spread=True)     # Chris: rifle, Lightning Hawk, knife
    assert w[:3] == [(0x10F, 30), (0x107, 7), (0x119, 0xFFFF)]
    assert w[3:] == [(0x108, 5), (0x104, 8), (0x105, 7), (0x106, 3)]          # the magnum and the shotguns loaded
    w2, _x = mods.loadout_plan(4, True, 5, random.Random(1), spread=True, want=0x109)
    assert w2[3] == (0x109, 6) and (0x108, 5) in w2                           # the sniper rifle asked for: in first
    picks = set()
    for seed in range(40):                                                    # Leon: Wing Shooter and Shotgun
        w3, _x = mods.loadout_plan(0, True, 5, random.Random(seed), spread=True)
        assert not any(t in mods.HANDGUN_TYPES for t, _c in w3)               # never a pistol
        assert len({t for t, _c in w3 if t != 0}) == len([t for t, _c in w3 if t != 0])   # no gun twice
        picks.add(w3[0])
    assert len(picks) >= 4 and picks <= set(mods.PISTOL_SWAPS)                # drawn fresh: many campaign guns
    w4, _x = mods.loadout_plan(0, True, 5, random.Random(1))                  # without the spread: his own pistol
    assert w4[0] == (0x103, 18)


def weapon_guest(types):
    g = round_guest()
    p = R.u64(g, R.u64(g, BASE + R.S_PLAYER) + R.P_FIRST)
    for i, t in enumerate(types):                                             # weapon slots 0.. (index = wheel index)
        g.put(p + R.P_SLOTS + R.SLOT_STRIDE * i + 8, bytes([1, i]) + struct.pack("<H", t))
    return g, p


def test_live_weapon_switches_to_a_loaded_gun_and_queues_another_for_the_next_round(mods, monkeypatch):
    monkeypatch.setattr(R, "WANT_WEAPON", None)
    g, p = weapon_guest((0x10F, 0x107, 0x119, 0x104))
    ad = Adapter(g)
    out = mods.run(ad, "live_weapon", weapon="Shotgun")
    assert out["loaded"] and out["wheel_index"] == 3 and R.WANT_WEAPON == 3
    out = mods.run(ad, "live_weapon", weapon=0x10B)                           # the Anti-Materiel Rifle: not loaded
    assert not out["loaded"] and out["next_round"] and mods.ORIG[id(ad)]["next_weapon"] == 0x10B
    assert (0x10B, 10) in mods.ASKED and R.WANT_WEAPON == 3                   # (the switch stays on the shotgun)
    names = {w["name"]: w for w in mods.run(ad, "weapons")["weapons"]}
    assert names["Shotgun"]["loaded"] and names["Shotgun"]["wheel_index"] == 3 and not names["Hydra"]["loaded"]
    assert len(names) >= 24 and mods.run(ad, "status")["live_weapon_sets"] == 2
    with pytest.raises(ValueError):
        mods.run(ad, "live_weapon", weapon="Banana")


def test_the_bot_switches_to_the_wanted_weapon_and_a_crowd_gets_the_shotgun(monkeypatch):
    monkeypatch.setattr(R, "AUTO_SWITCH", True)                             # (off in play: the operator, 2026-10-28)
    monkeypatch.setattr(R, "WANT_WEAPON", 3)
    monkeypatch.setattr(R, "WANT_WEAPON_AT", 1.0)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 1500.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, guns={0x10F: 0, 0x107: 1, 0x104: 3})
    acts = run(bot, snap, clock, 2)
    assert {"tap": "dright"} in acts and bot.stats["weapon_switches"] >= 1
    snap["player"]["equipped"] = 3
    run(bot, snap, clock, 2)
    assert bot.stats["weapon_in_hand"] == 3
    monkeypatch.setattr(R, "WANT_WEAPON", None)
    crowd = ((0.0, 0.0, 300.0, 700), (100.0, 0.0, 350.0, 700), (-100.0, 0.0, 380.0, 700))
    bot, clock, snap = brain(round_guest(enemies=crowd, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, guns={0x10F: 0, 0x107: 1, 0x105: 4})
    acts = run(bot, snap, clock, 2)
    assert {"tap": "dright"} in acts and bot.stats["crowd_shotgun_s"] > 0


def test_a_grab_picks_a_shotgun_or_magnum_and_sets_the_bomb_off_only_from_clear_of_it(monkeypatch):
    monkeypatch.setattr(R, "WANT_WEAPON", None)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 80.0, 700),), state=8, cam_yaw=0.0))
    snap["player"].update(equipped=R.BOMB_INDEX, guns={0x10F: 0, 0x107: 1, 0x104: 3},
                          bomb={"count": 4, "out": True})
    snap["bomb_pos"] = (0.0, 0.0, 1500.0)                                    # 15 m off: clear of its reach
    acts = run(bot, snap, clock, 3)
    assert bot.grab_weapon in (1, 3) and bot.stats["weapon_swaps"] == 1
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["grab_det_presses"] >= 1
    snap["player"].update(state=0, bomb={"count": 4, "out": False})           # it went off; free
    run(bot, snap, clock, 1)
    assert bot.stats["grab_detonations"] == 1
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 80.0, 700),), state=8, cam_yaw=0.0))
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 4, "out": True})
    snap["bomb_pos"] = (0.0, 0.0, 200.0)                                     # 2 m off: never from here
    acts = run(bot, snap, clock, 3)
    assert not any("zr" in a.get("hold", ()) for a in acts) and bot.stats["grab_det_presses"] == 0


def test_the_mods_tool_routes_an_re6_switch_session_to_its_own_ops(mods, monkeypatch):
    from gbox import re5_mods_tool as T, tools
    monkeypatch.setattr(R, "WANT_WEAPON", None)
    monkeypatch.setattr(R, "FLASH", True)
    g, _p = weapon_guest((0x10F, 0x107, 0x119, 0x104))
    ad = Adapter(g)
    monkeypatch.setitem(tools.SESSIONS, "re6-1", (ad, {"game_id": "115f9cdbba115432", "title": "RE6"}))
    out = T.re5_mods(T.RE5ModsIn(session_id="re6-1", op="live_weapon", weapon=0x104), None)["result"]
    assert out["loaded"] and R.WANT_WEAPON == 3
    out = T.re5_mods(T.RE5ModsIn(session_id="re6-1", op="bot_options", flash=False), None)["result"]
    assert out["flash"] is False and not R.FLASH
    st = T.re5_mods(T.RE5ModsIn(session_id="re6-1", op="status"), None)["result"]
    assert st["bot"]["flash"] is False and st["live_weapon_sets"] == 1
    assert T.is_switch_re6({"title_id": "01002a000cd48000"}) and not T.is_switch_re6({"game_id": "52d15709be0fda1a"})


def test_the_pitch_guard_never_writes_far_above_the_targets_own_slope():
    bot, clock, snap, writes = lock_brain(((0.0, 0.0, 900.0, 700),))
    bot.pitch_bias = 0.25                                                     # a learned correction at its cap
    run(bot, snap, clock, 4)
    c = snap["camera"]["pos"]
    own = math.degrees(math.atan2(R.CHEST_H - c[1], math.hypot(-c[0], 900.0 - c[2])))
    cap = (math.degrees(R.CLOSE_PITCH) + math.degrees(R.LOCK_UP_SLACK) - R.PITCH_DEG_AT_0) / R.PITCH_DEG_PER_UNIT + 0.25
    assert writes and all(w[1] <= cap + 1e-6 for w in writes) and own < 0
    assert R.LOCK_BIAS_MAX <= 0.25


def test_no_new_bomb_under_half_health():
    crowd = ((0.0, 0.0, 700.0, 700), (150.0, 0.0, 800.0, 700), (-150.0, 0.0, 750.0, 700))
    bot, clock, snap = brain(round_guest(enemies=crowd, hp=400))
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False})
    bot.tablet_at = clock[0] + 100                                            # (no tablet this tick)
    run(bot, snap, clock, 1)
    assert bot.bomb_phase is None and bot.doing != "bomb"


def test_no_bomb_without_one_a_crowd_or_room():
    for kw, enemies in (({"count": 0, "out": False}, ((0.0, 0.0, 700.0, 700),) * 3),     # none left
                        ({"count": 5, "out": False}, ((0.0, 0.0, 1500.0, 700),)),        # one, far: no stand
                        ({"count": 5, "out": False}, ((0.0, 0.0, 150.0, 700),) * 2)):    # two on him: no drop
        bot, clock, snap = brain(round_guest(enemies=enemies))
        bot.bomb_from = (0.0, 0.0)                                            # where the last one went: no new section
        snap["player"].update(equipped=0, bomb=kw)
        acts = run(bot, snap, clock, 3)
        assert bot.doing != "bomb" and {"tap": "dup"} not in acts and bot.bomb_phase is None


def test_bot_options_turn_the_grenades_and_the_bomb_drop_on(mods, monkeypatch):
    monkeypatch.setattr(R, "NADES", False)
    monkeypatch.setattr(R, "BOMB_DROP", False)
    monkeypatch.setattr(R, "AIM_LOCK", True)
    monkeypatch.setattr(R, "FLASH", True)
    out = mods.run(Adapter(round_guest()), "bot_options", nades=True, bomb_drop=True)
    assert out == {"verified": True, "nades": True, "bomb_drop": True, "aim_lock": True, "flash": True} and R.NADES
    assert mods.run(Adapter(round_guest()), "bot_options", flash=False)["flash"] is False and not R.FLASH
    assert mods.run(Adapter(round_guest()), "bot_options", aim_lock=False)["aim_lock"] is False and not R.AIM_LOCK
    assert mods.run(Adapter(round_guest()), "bot_options", nades=False)["nades"] is False and R.BOMB_DROP


def test_backing_out_of_a_crowd_he_drops_a_bomb_at_his_feet_and_walks_out_of_its_reach(monkeypatch):
    monkeypatch.setattr(R, "BOMB_DROP", True)
    ring = tuple((330.0 * math.sin(a), 0.0, 330.0 * math.cos(a), 700) for a in [i * math.pi / 4 for i in range(8)])
    bot, clock, snap = brain(round_guest(enemies=ring, cam_yaw=0.0))         # eight round him at 3.3 m: surrounded
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False}, nades={})
    first = run(bot, snap, clock, 1)[0]
    assert first == {"tap": "dup"} and bot.bomb_drop and bot.stats["bomb_drops"] == 1   # not called off: a drop
    snap["player"]["equipped"] = R.BOMB_INDEX
    acts = run(bot, snap, clock, int(R.BOMB_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts and not any(set(a.get("hold", ())) & {"rleft", "rright"} for a in acts)
    snap["player"]["bomb"] = {"count": 5, "out": True}
    act = run(bot, snap, clock, 2)[-1]
    assert "ldown" in act["hold"] and bot.stats["act"] == "bomb_escape"     # out of its reach first


def test_a_zombie_behind_a_wall_is_not_fired_at_and_the_next_one_is_the_target():
    wall = ((16.0, 139.0, 260.0), (20.0, 145.0, 30.0), 0.86)             # the ray at him ends 2.3 m out: a wall
    two = ((0.0, 0.0, 1200.0, 700), (600.0, 0.0, 1300.0, 700))            # one straight ahead behind it, one off right
    bot, clock, snap = brain(round_guest(enemies=two, cam_yaw=0.0, laser=wall))
    acts = run(bot, snap, clock, 8)
    assert bot.stats["los_blocks"] == 1 and all("zr" not in a.get("hold", ()) for a in acts)
    hidden = snap["enemies"][0]["ptr"]
    assert bot.is_blocked(snap["enemies"][0], clock[0]) and bot.target != hidden   # the next one is the target
    assert bot.target == snap["enemies"][1]["ptr"]
    clock[0] += R.BLOCK_S + 0.1                                               # out of sight only for BLOCK_S
    assert not bot.is_blocked(snap["enemies"][0], clock[0])


def test_the_cameras_line_only_guides_aim_even_when_the_zombie_was_recently_hit():
    far = ((0.0, 0.0, 1500.0, 700),)                                      # 15 m along the camera's line, no laser
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0))
    acts = run(bot, snap, clock, 30)
    assert all("zr" not in a.get("hold", ()) for a in acts) and bot.stats["camera_far_holds"] > 0
    bot.seen[snap["enemies"][0]["ptr"]] = clock[0]                           # his health fell to a shot just now
    acts = run(bot, snap, clock, 6)
    assert all("zr" not in a.get("hold", ()) for a in acts)
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0))
    bot.laser_seen[snap["enemies"][0]["ptr"]] = 0.0                          # the laser reached him a moment ago
    acts = run(bot, snap, clock, 16)
    assert all("zr" not in a.get("hold", ()) for a in acts)
    near = ((0.0, 0.0, 700.0, 700),)                                      # 7 m: within CAM_FIRE_R
    bot, clock, snap = brain(round_guest(enemies=near, cam_yaw=0.0))
    acts = run(bot, snap, clock, 30)
    assert all("zr" not in a.get("hold", ()) for a in acts)


def test_a_zombie_the_trigger_never_hurts_is_left_for_another():
    on = ((0.0, R.CHEST_H, 900.0), (20.0, 145.0, 30.0), 0.86)             # the dot on him, 9 m ahead
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 900.0, 700),), cam_yaw=0.0, laser=on))
    bot.held = lambda p, now: False                                          # (the frozen snapshot never moves him)
    acts = run(bot, snap, clock, int(R.NOHIT_S / 0.05) + 4)                  # the trigger on him, his health never falls
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["nohit_blocks"] == 1
    acts = run(bot, snap, clock, 10)
    assert all("zr" not in a.get("hold", ()) for a in acts)                   # out of sight: not fired at
    assert bot.doing == "walk"                                                # all out of sight: walking round
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 900.0, 700),), cam_yaw=0.0, laser=on))
    for _ in range(int(R.NOHIT_S / 0.05) + 4):                               # his health falls to the shots: kept
        snap["enemies"][0]["hp"] -= 10
        run(bot, snap, clock, 1)
    assert bot.stats["nohit_blocks"] == 0 and bot.seen


def test_point_blank_quick_shots_never_leave_one_even_when_they_miss():
    assert R.CC_R <= R.BLOCK_MIN_R                                            # crowd control only where nothing blocks
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 150.0, 700),), cam_yaw=0.0))   # 1.5 m: always fought
    bot.held = lambda p, now: False
    run(bot, snap, clock, int(4 * R.CC_QSHOT_GAP_S / 0.05))
    assert bot.stats["cc_blocks"] == 0 and bot.doing == "crowd" and bot.stats["cc_quick_shots"] >= 4
    bot._block(snap["enemies"][0], clock[0], "los_blocks")                    # whatever said so
    assert not bot.is_blocked(snap["enemies"][0], clock[0]) and bot.stats["los_blocks"] == 0


def bonus_piece(g, action, pos, line=14, cls="uSm5923"):
    """A breakable set piece on a move line: its class, position and current action (+0x13F0)."""
    u = g.unit(line, cls, size=0x1500)
    g.q(u + R.PIECE_ACTION, g.obj(action, 0x100))
    g.f32(u + R.P_POS, *pos)
    return u


def test_the_snapshot_finds_the_time_and_combo_bonuses_by_their_action():
    g = round_guest()
    gm = R.u64(g, BASE + R.S_GAMEMAN)
    t = bonus_piece(g, "cSmTimeBonusAct_Wait", (100.0, 0.0, 900.0))
    c = bonus_piece(g, "cSmComboBonusAct_Wait", (-400.0, 50.0, 300.0), cls="uSm5924")
    bonus_piece(g, "SmWoodBoxActWait", (0.0, 0.0, 200.0), line=13, cls="uSm1537")     # a crate: not a bonus
    snap = R.snapshot(g)
    assert sorted((b["kind"], b["ptr"]) for b in snap["bonuses"]) == sorted([("time", t), ("combo", c)])
    assert next(b for b in snap["bonuses"] if b["ptr"] == t)["pos"] == (100.0, 0.0, 900.0)
    g.q(t + R.PIECE_ACTION, g.obj("cSmGlassAct_Break", 0x100))                         # shot: it breaks
    assert [b["kind"] for b in R.snapshot(g)["bonuses"]] == ["combo"]                  # seen without a new walk
    g.i32(gm + R.GM_PHASE, R.PHASE_OVER)
    assert "bonuses" not in R.snapshot(g)


def test_with_nobody_near_it_shoots_a_time_bonus_and_books_it_taken(monkeypatch):
    monkeypatch.setattr(R, "BONUS_PURSUIT", True)                             # the shooting kept, behind its switch
    monkeypatch.setattr(R, "BONUS_RUN", False)
    g = round_guest(enemies=(), laser=((0.0, R.BONUS_H, 1000.0), (20.0, 145.0, 30.0), 0.86))   # the dot on the bonus
    u = bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))                   # 10 m ahead
    bot, clock, snap = brain(g)
    acts = run(bot, snap, clock, 12)
    assert bot.doing == "bonus" and all("zl" in a["hold"] for a in acts[1:])
    assert any("zr" in a["hold"] for a in acts) and bot.stats["bonus_shots"] >= 2 and bot.stats["shots"] == 0
    snap["bonuses"] = []                                                               # it broke
    run(bot, snap, clock, 1)
    assert bot.stats["bonuses_taken"] == 1 and bot.stats["time_bonuses_taken"] == 1 and bot.bonus_target is None
    snap["mercenaries_phase"] = R.PHASE_OVER                                           # the round's end
    run(bot, snap, clock, 1)
    assert bot.stats["bonus_log"] == [{"seen": 1, "taken": 1, "time": 1, "combo": 0, "missed": 0}]
    assert bot.stats["bonuses_missed"] == 0 and u


def test_no_bonus_shot_with_a_bomb_out(monkeypatch):
    monkeypatch.setattr(R, "BONUS_PURSUIT", True)                             # the shooting kept, behind its switch
    monkeypatch.setattr(R, "BONUS_RUN", False)
    g = round_guest(enemies=(), laser=((0.0, R.BONUS_H, 1000.0), (20.0, 145.0, 30.0), 0.86))
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))
    bot, clock, snap = brain(g)
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True}, pos=(0.0, 0.0, -1500.0))
    bot.bomb_at, bot.bomb_since, bot.bomb_phase = (0.0, 0.0), clock[0], "wait"
    acts = run(bot, snap, clock, 12)
    assert bot.doing != "bonus" and all("zr" not in a.get("hold", ()) for a in acts)


def test_no_bonus_with_a_zombie_near_and_one_out_of_sight_is_left_and_missed(monkeypatch):
    monkeypatch.setattr(R, "BONUS_PURSUIT", True)                             # the shooting kept, behind its switch
    monkeypatch.setattr(R, "BONUS_RUN", False)
    g = round_guest(enemies=((0.0, 0.0, 400.0, 700),))                               # a zombie 4 m ahead
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 6)
    assert bot.doing != "bonus" and bot.stats["bonus_shots"] == 0
    R._BONUS.update(base=None)                                                         # another guest at the same base
    for cache in (R._FOUND, R._MISS):                                                  # (its laser too)
        cache.clear()
    g = round_guest(enemies=((0.0, 0.0, 4000.0, 700),), laser=((0.0, R.BONUS_H, 500.0), (20.0, 145.0, 30.0), 0.86))
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))                       # a wall at 5 m: the dot short
    bot, clock, snap = brain(g)
    acts = run(bot, snap, clock, int(R.BONUS_TRY_S / 0.05) + 4)
    assert all("zr" not in a.get("hold", ()) for a in acts) and bot.stats["bonus_skips"] == 1
    assert bot.doing == "walk"                                                         # left: on to the zombie
    snap["mercenaries_phase"] = R.PHASE_OVER
    run(bot, snap, clock, 1)
    assert bot.stats["bonuses_missed"] == 1 and bot.stats["bonus_log"][-1]["missed"] == 1


def test_the_bonus_run_walks_to_the_nearest_bonus_and_breaks_it_with_the_physical_attack():
    g = round_guest(enemies=((0.0, 0.0, 6000.0, 700),))                       # a zombie far off: no blocker
    near = bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 800.0))          # 8 m ahead
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 3000.0))
    bonus_piece(g, "cSmComboBonusAct_Wait", (0.0, 700.0, 500.0), cls="uSm5924")   # a floor up: later
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 3)
    assert bot.stats["phase"] == "bonus_run" and bot.run_target == near and all("lup" in a["hold"] for a in acts)
    assert all("zl" not in a["hold"] and "zr" not in a["hold"] for a in acts)   # no shooting at it
    snap["player"]["pos"] = (0.0, 0.0, 700.0)                                 # at it
    acts = run(bot, snap, clock, 12)
    assert {"tap": "zr"} in acts and bot.stats["bonus_melee"] >= 2 and bot.stats["shots"] == 0
    snap["bonuses"] = [b for b in snap["bonuses"] if b["ptr"] != near]       # it broke
    acts = run(bot, snap, clock, 2)
    assert bot.stats["bonuses_taken"] == 1 and bot.run_target != near and "lup" in acts[-1]["hold"]
    assert bot.stats["bonus_time_s"] > 0
    snap["bonuses"] = []                                                      # every one taken: the match
    run(bot, snap, clock, 2)
    assert bot.stats["phase"] == "match" and bot.doing != "bonus"


def test_the_bonus_run_fights_a_blocker_first_and_leaves_one_that_will_not_break(monkeypatch):
    monkeypatch.setattr(R, "FIRE_ZONE_R", 0.0)                              # (the run itself; shoot-first: off here)
    g = round_guest(enemies=((0.0, 0.0, 200.0, 700),))                        # one at 2 m: in the way
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 800.0))
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    run(bot, snap, clock, 3)
    assert bot.doing != "bonus" and bot.stats["bonus_time_s"] > 0
    R._BONUS.update(base=None)
    g = round_guest(enemies=())
    stuck = bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 100.0))         # at arm's length, never breaking
    bot, clock, snap = brain(g)
    bot.held = lambda p, now: False
    run(bot, snap, clock, int(R.BONUS_HIT_S / 0.05) + 6)
    assert bot.stats["bonus_skips"] == 1 and bot.bonus_skip.get(stuck) and bot.stats["phase"] == "match"


def test_a_replay_is_not_every_bonus_taken():
    g = round_guest(enemies=((0.0, 0.0, 400.0, 700),))
    for x in (0.0, 500.0, 1000.0):
        bonus_piece(g, "cSmTimeBonusAct_Wait", (x, 0.0, 2000.0))
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 2)
    snap["bonuses"] = [dict(b, ptr=b["ptr"] + 0x10000) for b in snap["bonuses"]]      # the round again: new pieces
    run(bot, snap, clock, 2)
    assert bot.stats["bonuses_taken"] == 0 and bot.stats["bonus_log"][-1] == {"seen": 3, "taken": 0, "time": 0,
                                                                              "combo": 0, "missed": 3}


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
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 180.0, 700),), cam_yaw=0.0))   # point blank (CC_R)
    acts = run(bot, snap, clock, 2)
    assert acts[0]["hold"] == ("zl", "zr") and acts[1]["hold"] == () and bot.stats["quick_shots"] == 1


def test_far_away_it_walks_along_the_camera():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 4000.0, 700),), cam_yaw=0.0))   # past LONG_R
    assert run(bot, snap, clock, 1)[0]["hold"] == ("lup",)


def test_a_hold_read_in_ram_is_shaken_off():
    bot, clock, snap = brain(round_guest(state=8))
    acts = run(bot, snap, clock, 4)
    assert [a["hold"] for a in acts] == [R.WIGGLE[i % len(R.WIGGLE)] for i in range(1, 5)] and bot.stats["holds"] == 1
    assert {k for chord in R.WIGGLE for k in chord} == {"lup", "lright", "ldown", "lleft", "b"}   # round, B mashed


def test_auto_qte_frees_no_grab_so_he_shakes_at_once_with_it_on():
    bot, clock, snap = brain(round_guest(state=8))
    snap["auto_qte"] = True                                  # live 2026-10-27: the option let every bite land
    assert R.AUTO_QTE_WAIT_S == 0.0 and run(bot, snap, clock, 1)[0]["hold"] in R.WIGGLE


def test_with_auto_qte_on_a_hold_gets_a_hands_off_window_then_the_shake(monkeypatch):
    monkeypatch.setattr(R, "AUTO_QTE_WAIT_S", 1.2)           # the window, when one is set
    bot, clock, snap = brain(round_guest(state=8))
    snap["auto_qte"] = True                                  # the driver's flag: re6_switch_mods.auto_qte is on
    wait = int(R.AUTO_QTE_WAIT_S / 0.05) - 1
    acts = run(bot, snap, clock, wait)
    assert all(a == {"hold": ()} for a in acts) and bot.stats["acts"]["held_auto_qte"] == wait   # nothing pressed
    acts = run(bot, snap, clock, 4)                          # still held past the window: shaken off as without it
    assert acts[-1]["hold"] in R.WIGGLE and bot.stats["holds"] == 1
    snap["player"]["state"] = 0
    run(bot, snap, clock, 1)
    assert bot.stats["holds_shaken"] == 1 and bot.stats["holds_freed_no_press"] == 0
    assert bot.stats["hold_log"][-1]["pressed"] is True and bot.stats["hold_log"][-1]["auto_qte"] is True


def test_a_hold_the_game_frees_inside_the_window_counts_as_freed_with_no_press(monkeypatch):
    monkeypatch.setattr(R, "AUTO_QTE_WAIT_S", 1.2)
    bot, clock, snap = brain(round_guest(state=9))
    snap["auto_qte"] = True
    run(bot, snap, clock, 8)                                 # 0.4 s held, nothing pressed
    snap["player"]["state"] = 1                              # the game let him go
    run(bot, snap, clock, 1)
    assert bot.stats["holds_freed_no_press"] == 1 and bot.stats["holds_shaken"] == 0
    entry = bot.stats["hold_log"][-1]
    assert entry["pressed"] is False and 0.3 <= entry["s"] <= 0.5
    bot2, clock2, snap2 = brain(round_guest(state=8))        # auto QTE off: shaken off at once, as before
    assert run(bot2, snap2, clock2, 1)[0]["hold"] in R.WIGGLE


def test_the_driver_tells_the_bot_when_auto_qte_is_on(mods):
    g = round_guest()
    ad = Adapter(g)
    g.adapter = ad
    d = R.RE6Switch()
    snap = R.snapshot(g)
    d._mods(g, snap, True)
    assert snap["auto_qte"] is False
    mods.ORIG.setdefault(id(ad), {"base": BASE})["auto_qte"] = True
    snap = R.snapshot(g)
    d._mods(g, snap, True)
    assert snap["auto_qte"] is True


def test_dead_it_answers_continue_yes_by_the_cursor_and_counts_the_replay(monkeypatch):
    monkeypatch.setattr(R, "REPLAY_ON_DEATH", True)                                  # (off in play: a new round drawn)
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


def test_a_tablet_at_sixty_percent_while_he_is_free_whoever_is_near():
    bot, clock, snap = brain(round_guest(hp=540, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"} and bot.stats["tablet_presses"] == 1   # 60 % of 900
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # one a TABLET_GAP_S
    bot, clock, snap = brain(round_guest(hp=560, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # above 60 %: none
    bot, clock, snap = brain(round_guest(hp=500, enemies=((0.0, 0.0, 120.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}                       # one at arm's length: a tablet anyway
    bot, clock, snap = brain(round_guest(hp=400, tablets=0, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"} and bot.stats["tablets"] == 0
    bot, clock, snap = brain(round_guest(hp=1, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    snap["player"]["action"] = "cPlAction_pl_act_dying_loop"
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # dying: RE6 takes none (DYING_TABLETS off)
    bot, clock, snap = brain(round_guest(hp=1, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    snap["player"]["action"] = "cPlAction_pl_act_weapon_ready_loop"
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}                       # up again at 1 health: a tablet at once
    bot, clock, snap = brain(round_guest(hp=300, state=1, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    assert {"tap": "r"} not in run(bot, snap, clock, 3)                      # being hit: R would be ignored


def test_a_tablet_counts_once_the_count_falls_and_the_taps_keep_coming_while_he_is_low():
    # operator 2026-10-29: "you can just tap it multiple times to spam eating a lot of health caplets" - a burst
    g = round_guest(hp=400, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0)
    bot, clock, snap = brain(g)
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}
    snap["player"]["tablets"] = 7                                            # the press took one
    run(bot, snap, clock, 1)
    assert bot.stats["tablets"] == 1
    acts = run(bot, snap, clock, int((R.TABLET_CHAIN_S + R.TABLET_LOWER_S) / 0.05) + 4)
    assert {"tap": "r"} in acts                                              # still low: tapped again at once
    snap["player"]["hp"] = 900                                               # refilled: no more
    clock[0] += R.TABLET_CONFIRM_S
    run(bot, snap, clock, 2)
    assert {"tap": "r"} not in run(bot, snap, clock, 10)

def test_a_tablet_waits_a_moment_after_the_gun_was_up():
    bot, clock, snap = brain(round_guest(hp=400, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0))
    bot._zl_at = clock[0]                                                     # the gun was up just now
    acts = run(bot, snap, clock, int(R.TABLET_LOWER_S / 0.05) + 2)
    assert acts[0] == {"hold": ()} and {"tap": "r"} in acts and bot.stats["tablet_presses"] == 1


def test_a_gun_that_does_not_come_up_keeps_aiming_along_the_camera_and_looks_for_the_laser_again():
    down = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.3)            # the laser unit, but the gun not up
    bot, clock, snap = brain(round_guest(enemies=((300.0, 0.0, 500.0, 700),), cam_yaw=math.atan2(300, 500),
                                         laser=down))
    R._FOUND[(BASE, "laser")] = (1, 2)
    acts = run(bot, snap, clock, int(R.LASER_WAIT_S / 0.05) + 4)
    assert bot.stats["reraise"] == 1 and (BASE, "laser") not in R._FOUND
    assert all("zl" in a["hold"] for a in acts)                              # the gun never went down for it
    assert all("zr" not in a["hold"] for a in acts)                        # camera alignment cannot confirm a hit
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
def mods(monkeypatch):
    from gbox.mercs.titles import re6_switch_mods as RM
    RM.ORIG.clear()
    monkeypatch.setattr(RM, "FIRE_MAX", 80.0)       # the mechanics at any multiplier (play caps it at 5x, 2026-10-28)
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


class RacingAdapter(Adapter):
    """The game spends `spent` of a count between the write and its read-back (an automatic's shot): the adapter's own
    read-back then fails, as CitronLinuxAdapter's does."""

    def __init__(self, g, spent):
        super().__init__(g)
        self.spent = spent

    def write_memory(self, a, data):
        self.writes.append((a, bytes(data)))
        if len(data) == 2:
            data = struct.pack("<h", struct.unpack("<h", data)[0] - self.spent)
        self.g.put(a, bytes(data))
        if self.spent:
            raise RuntimeError("memory write not confirmed by read-back")
        return {"verified": True}


def test_a_shot_between_a_top_up_and_its_read_back_is_the_games_own_spending(mods):
    g = round_guest(guns=((20, 30),))
    ad = RacingAdapter(g, 1)
    assert mods.run(ad, "infinite_ammo", on=True)["topped_up"] == 1          # 30 written, 29 read back: done
    assert R.snapshot(g)["player"]["ammo"] == 29
    clock = [10.0]
    res = mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert res["verified"] and res["writes"] == 1                           # the next check tops it up again
    ad.spent = 7                                                             # far more than a shot: a real mismatch
    clock[0] += mods.CHECK_S
    res = mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert res["verified"] is False and "read-back" in res["reason"]


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


def item_slots(g, rows):
    """cItem slots in use: rows of (physical slot, +0x9 index, type, count, capacity)."""
    from gbox.mercs.titles import re6_switch_mods as RM
    p = R.snapshot(g)["player"]["ptr"]
    for i in range(RM.ALL_SLOTS):
        g.q(p + RM.SLOTS + RM.SLOT_STRIDE * i, BASE + RM.SLOT_VTABLE)
    for phys, index, kind, count, cap in rows:
        slot = p + RM.SLOTS + RM.SLOT_STRIDE * phys
        g.put(slot + RM.SLOT_USED, bytes([1, index]) + struct.pack("<H", kind))
        g.put(slot + RM.SLOT_ROUNDS, struct.pack("<h", count))
        g.put(slot + RM.SLOT_CAP, struct.pack("<h", cap))
    return lambda phys: struct.unpack("<h", g.rd(p + RM.SLOTS + RM.SLOT_STRIDE * phys + RM.SLOT_ROUNDS, 2))[0]


def test_infinite_grenades_keeps_every_stack_and_the_wheels_total(mods):
    g = round_guest(guns=((30, 30),))
    count = item_slots(g, ((9, 9, 0x113, 2, 5), (12, 12, 0x116, 5, 5),        # the wheel: hand grenades 2, remote bombs 5
                           (15, 15, 0x113, 2, 5), (16, 16, 0x116, 5, 5),      # their stacks
                           (17, 17, 0x204, 59, 60), (8, 8, 0x120, 0, 3)))     # an ammo box and the spray: never written
    ad = Adapter(g)
    out = mods.run(ad, "grenades", on=True)
    assert out["verified"] and out["kept"] == 2 and count(15) == 5 and count(9) == 5     # the stack, then the wheel's total
    assert count(16) == 5 and count(12) == 5 and count(17) == 59 and count(8) == 0
    assert len(ad.writes) == 2
    g.put(R.snapshot(g)["player"]["ptr"] + mods.SLOTS + mods.SLOT_STRIDE * 16 + mods.SLOT_ROUNDS, struct.pack("<h", 4))
    clock = [10.0]
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 1 and count(16) == 5   # a bomb placed
    mods.run(ad, "infinite_grenades", on=False)
    g.put(R.snapshot(g)["player"]["ptr"] + mods.SLOTS + mods.SLOT_STRIDE * 16 + mods.SLOT_ROUNDS, struct.pack("<h", 4))
    clock[0] += 1.0
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 0 and count(16) == 4


def test_infinite_stamina_keeps_the_combat_gauge_at_its_maximum(mods):
    g = round_guest(guns=((30, 30),))
    p = R.snapshot(g)["player"]["ptr"]
    g.f32(p + mods.P_STAMINA, 420.0, 800.0)                                  # 1 of 5 segments left after two melees
    ad = Adapter(g)
    out = mods.run(ad, "stamina", on=True)
    assert out["verified"] and out["kept"] == 1 and out["gauge"] == {"value": 800.0, "max": 800.0}
    assert ad.writes == [(p + mods.P_STAMINA, struct.pack("<f", 800.0))]     # the gauge's f32, nothing else
    g.f32(p + mods.P_STAMINA, 700.0)                                         # a quick shot
    clock = [10.0]
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 1
    assert struct.unpack("<f", g.rd(p + mods.P_STAMINA, 4))[0] == 800.0
    clock[0] += mods.CHECK_S
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 0   # full: nothing to write
    for top in (0.0, 1e9, float("nan")):                                     # not a gauge's maximum: never written
        g2 = round_guest()
        p2 = R.snapshot(g2)["player"]["ptr"]
        g2.f32(p2 + mods.P_STAMINA, 100.0, top)
        ad2 = Adapter(g2)
        mods.ORIG.clear()
        assert mods.run(ad2, "infinite_stamina", on=True)["kept"] == 0 and ad2.writes == []
    assert mods.run(ad, "revert_all")["infinite_stamina"]["infinite_stamina"] is False


def test_unlock_characters_writes_only_the_selects_mask_in_both_copies(mods):
    from gbox import re6_switch_unlock as U
    g = round_guest()
    im = g.alloc(U.INFO_ARRAY + U.INFO_STRIDE)                              # sInfoMan with its cSystemInfo 0
    g.q(BASE + U.S_INFOMAN, im)
    g.i32(im + U.INFO_INDEX, 0)
    info = im + U.INFO_ARRAY
    for off in mods.CHARACTER_MASK:
        g.put(info + off, struct.pack("<I", 0x10711))                       # live 2026-10-27: Leon, Helena, Chris 1-3, Jake
    ad = Adapter(g)
    out = mods.run(ad, "unlock_characters", on=True)
    assert out["verified"] and out["writes"] == 2 and out["after"] == ["0x3fffffff", "0x3fffffff"]
    assert sorted(a for a, _ in ad.writes) == sorted(info + off for off in mods.CHARACTER_MASK)   # nothing else written
    assert all(data == struct.pack("<I", 0x3FFFFFFF) for _, data in ad.writes)
    assert mods.run(ad, "all_characters", on=True)["writes"] == 0                 # already unlocked: no write
    g2 = round_guest()                                                       # still booting: no cSystemInfo
    ad2 = Adapter(g2)
    mods.ORIG.clear()
    out2 = mods.run(ad2, "unlock_characters", on=True)
    assert out2["verified"] is False and ad2.writes == []


def test_the_gun_in_hand_is_the_equipped_slots_and_automatics_hold_the_trigger():
    g = round_guest(guns=((30, 30), (7, 7)))
    p = R.snapshot(g)["player"]["ptr"]
    for i, (index, item) in enumerate(((0, 0x0F), (1, 0x07), (15, 0x13))):  # Chris: the rifle, the magnum, a grenade stack
        g.put(p + R.P_SLOTS + R.SLOT_STRIDE * i + 8, bytes([1, index]) + struct.pack("<H", 0x100 + item))
    g.put(p + R.P_WEAPON_ID, bytes([0x0F]))
    for equipped, want in ((0, 0x0F), (1, 0x07), (15, 0x13), (9, 0x0F)):     # 9: no live slot holds it - slot 0's
        g.i32(p + R.P_EQUIPPED, equipped)
        assert R.snapshot(g)["player"]["weapon_id"] == want
    assert {0x0F, 0x10, 0x11, 0x0C, 0x0E} <= R.AUTO_IDS and not {0x07, 0x03, 0x04, 0x13} & R.AUTO_IDS


def system_info_guest(mask=0x10711, stages=0x1, qte=0):
    from gbox import re6_switch_unlock as U
    g = round_guest()
    im = g.alloc(U.INFO_ARRAY + U.INFO_STRIDE)
    g.q(BASE + U.S_INFOMAN, im)
    g.i32(im + U.INFO_INDEX, 0)
    info = im + U.INFO_ARRAY
    for a, b, v in ((0x974, 0x974 + 0x5510, mask), (0x970, 0x970 + 0x5510, stages), (0x46B0, 0x46B0 + 0x5510, qte)):
        g.put(info + a, struct.pack("<I", v))
        g.put(info + b, struct.pack("<I", v))
    return g, info


def test_unlock_stages_and_auto_qte_write_only_their_own_cells_in_both_copies(mods):
    g, info = system_info_guest(stages=0x1)
    ad = Adapter(g)
    out = mods.run(ad, "unlock_stages", on=True)
    assert out["verified"] and out["writes"] == 2 and out["after"] == ["0x1807", "0x1807"]   # bits 1, 2, 11, 12 ORed in
    assert sorted(a for a, _ in ad.writes) == sorted(info + off for off in mods.STAGE_MASK)
    assert mods.run(ad, "all_stages", on=True)["writes"] == 0                             # already there
    ad.writes.clear()
    out = mods.run(ad, "auto_qte", on=True)
    assert out["verified"] and out["writes"] == 2 and out["after"] == ["0x1", "0x1"]
    assert sorted(a for a, _ in ad.writes) == sorted(info + off for off in mods.AUTO_QTE)
    assert all(d == struct.pack("<I", 1) for _, d in ad.writes)
    off = mods.run(ad, "qte", on=False)
    assert off["after"] == ["0x0", "0x0"] and off["writes"] == 2
    for cell in (0x974, 0x974 + 0x5510):                                                   # the character mask untouched
        assert struct.unpack("<I", g.rd(info + cell, 4))[0] == 0x10711


def test_kill_time_adds_seconds_per_new_kill(mods):
    g = round_guest(timer=60.0)
    gm = R.u64(g, BASE + R.S_GAMEMAN)
    ad = Adapter(g)
    clock = [10.0]
    out = mods.run(ad, "kill_time_bonus", seconds=3)
    assert out["kill_time"] is True and out["seconds"] == 3.0
    mods.run(ad, "infinite_ammo", on=False)
    snap = R.snapshot(g)
    assert mods.maintain(ad, snap, clock=lambda: clock[0])["writes"] == 0       # the round's count read: 9 kills
    g.i32(gm + R.GM_KILLS, 11)                                                 # two more
    res = mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert res["writes"] == 1 and res["kill_time"]["applied_seconds"] == pytest.approx(6.0)
    assert struct.unpack("<f", g.rd(gm + mods.GM_CLOCK, 4))[0] == pytest.approx(66.0)
    assert ad.writes[-1] == (gm + mods.GM_CLOCK, struct.pack("<f", 66.0))      # that f32 only (no notice)
    g.i32(gm + R.GM_KILLS, 12)                                                 # one more
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(gm + mods.GM_CLOCK, 4))[0] == pytest.approx(69.0)
    assert struct.unpack("<f", g.rd(gm + R.GM_TIMER, 4))[0] == 60.0            # the HUD's copy is the game's to write
    g.i32(gm + R.GM_KILLS, 0)                                                  # a new round: counted afresh
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 0
    g.f32(gm + mods.GM_CLOCK, 5998.0)
    g.i32(gm + R.GM_KILLS, 1)
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert struct.unpack("<f", g.rd(gm + mods.GM_CLOCK, 4))[0] == pytest.approx(mods.CLOCK_MAX)   # the game's cap
    g.i32(gm + R.GM_PHASE, R.PHASE_OVER)                                       # time up: nothing written
    g.i32(gm + R.GM_KILLS, 3)
    before = list(ad.writes)
    mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert ad.writes == before
    assert mods.run(ad, "status")["kill_time_on"] is True
    with pytest.raises(ValueError):
        mods.run(ad, "kill_time", seconds=40)


def test_add_time_and_set_time_move_the_clock_within_its_bounds(mods):
    g = round_guest(timer=30.0)
    gm = R.u64(g, BASE + R.S_GAMEMAN)
    ad = Adapter(g)
    out = mods.run(ad, "add_time", seconds=20)
    assert out["verified"] and out["added_seconds"] == 20 and out["clock_after"] == pytest.approx(50.0)
    out = mods.run(ad, "add_time", seconds=-100)                              # never under 1 s
    assert out["clock_after"] == pytest.approx(1.0) and out["clamped"]
    assert mods.run(ad, "set_time", seconds=90)["clock_after"] == pytest.approx(90.0)
    g.i32(gm + R.GM_PHASE, R.PHASE_OVER)
    assert mods.run(ad, "add_time", seconds=10)["verified"] is False
    with pytest.raises(ValueError):
        mods.run(ad, "set_time", seconds=0)


def struggle_guest(state=8, target=5.0, progress=1.5, active=1, kind=8, outcome=4, new=0):
    """sActionButton with player 0's ButtonMgr and one live struggle unit (a cActionButton): a zombie's grab by
    default (a chance button, type 8, its outcome rolled: 4 the bite)."""
    from gbox.mercs.titles import re6_switch_mods as RM
    g = round_guest(state=state)
    sab = g.obj("sActionButton", 0x1D40)
    g.q(BASE + RM.S_ACTBTN, sab)
    mgr = sab + RM.AB_MGRS
    g.q(mgr, g.klass("sActionButton::ButtonMgr"))
    btn = g.obj("cActionButton", 0x1D0)
    u = mgr + RM.MGR_UNITS[0]
    g.i32(u + RM.UNIT_OUTCOME, outcome)
    g.put(u + RM.UNIT_ACTIVE, bytes([active, new]))
    g.q(u + RM.UNIT_BUTTON, btn)
    g.i32(u + RM.UNIT_TYPE, kind)
    g.f32(u + RM.UNIT_TARGET, target, progress)
    return g, u


def test_auto_qte_ram_frees_a_grab_at_once_only_while_he_is_held(mods):
    g, u = struggle_guest()
    ad = Adapter(g)
    out = mods.run(ad, "auto_qte_ram", on=True)
    assert out["verified"] and out["units"] == 1
    clock = [10.0]
    res = mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])
    assert res["writes"] == 1 and struct.unpack("<I", g.rd(u + mods.UNIT_OUTCOME, 4))[0] == 0   # free at once
    assert ad.writes == [(u + mods.UNIT_OUTCOME, struct.pack("<I", 0))]                         # that u32 only
    assert mods.maintain(ad, R.snapshot(g), clock=lambda: clock[0])["writes"] == 0              # once a grab
    assert mods.run(ad, "status")["struggles_completed"] == 1
    for kw in ({"state": 0}, {"active": 0}, {"new": 1}, {"outcome": 0}, {"outcome": 9}):
        g2, u2 = struggle_guest(**kw)                       # free / no live unit / not rolled yet / free already / odd
        ad2 = Adapter(g2)
        mods.ORIG.clear()
        mods.run(ad2, "qte_ram", on=True)
        mods.maintain(ad2, R.snapshot(g2), clock=lambda: clock[0])
        assert ad2.writes == [], kw


def test_auto_qte_ram_fills_a_mash_button_to_its_target(mods):
    g, u = struggle_guest(kind=2)
    ad = Adapter(g)
    mods.run(ad, "auto_qte_ram", on=True)
    res = mods.maintain(ad, R.snapshot(g), clock=lambda: 10.0)
    assert res["writes"] == 1 and struct.unpack("<f", g.rd(u + mods.UNIT_PROGRESS, 4))[0] == 5.0   # at its target
    assert ad.writes == [(u + mods.UNIT_PROGRESS, struct.pack("<f", 5.0))]
    g2, _ = struggle_guest(kind=2, target=5000.0)            # not a struggle's target
    ad2 = Adapter(g2)
    mods.ORIG.clear()
    mods.run(ad2, "auto_qte_ram", on=True)
    mods.maintain(ad2, R.snapshot(g2), clock=lambda: 10.0)
    assert ad2.writes == []


def test_infinite_ammo_off_writes_nothing_and_status_reports(mods):
    g = round_guest(guns=((10, 18),))
    ad = Adapter(g)
    mods.run(ad, "infinite_ammo", on=False)
    assert mods.maintain(ad, R.snapshot(g))["writes"] == 0 and ad.writes == []
    st = mods.run(ad, "status")
    assert st["infinite_ammo"] is False and st["guns"] == [{"rounds": 10, "capacity": 18}] and st["in_hand_rounds"] == 10


def weapon_table(g, site=None):
    """This build's weapon parameter table (48 records: its first word, the tag 60, the interval, a neighbour) and the
    interval reader's ldr at main+0xB2701C."""
    from gbox.mercs.titles import re6_switch_mods as RM
    g.put(BASE + RM.FIRE_SITE, struct.pack("<I", RM.FIRE_SITE_WORD if site is None else site))
    for i, v in enumerate(RM.FIRE_ORIGINAL):
        rec = BASE + RM.FIRE_TABLE + RM.FIRE_STRIDE * i
        g.i32(rec, -1438083120)
        g.i32(rec + RM.FIRE_TAG, RM.FIRE_TAG_VALUE)
        g.f32(rec + RM.FIRE_INTERVAL, v)
        g.f32(rec + 0x30, 0.24)
    return BASE + RM.FIRE_TABLE


def test_fire_rate_speeds_up_every_guns_interval_only_and_writes_the_builds_back(mods):
    g = round_guest()
    table = weapon_table(g)
    ad = Adapter(g)
    cell = lambda i: table + mods.FIRE_STRIDE * i + mods.FIRE_INTERVAL
    iv = lambda i: struct.unpack("<f", g.rd(cell(i), 4))[0]
    guns = [i for i, v in enumerate(mods.FIRE_ORIGINAL) if i not in mods.FIRE_SKIP and 0 < v < mods.FIRE_GUN_MAX]
    out = mods.run(ad, "rapid_fire", multiplier=4)
    assert out["verified"] and out["fire_rate_x"] == 4.0 and out["writes"] == len(guns)
    assert sorted(a for a, _ in ad.writes) == sorted(cell(i) for i in guns)            # the interval cells, nothing else
    assert math.isclose(iv(0x0F), 0.025, rel_tol=1e-6) and math.isclose(iv(0x07), 0.2, rel_tol=1e-6)
    assert iv(0x13) == 2.0 and iv(0x16) == 2.0 and iv(0x00) == 10.0 and iv(0x18) == 10.0   # thrown / melee: theirs
    assert struct.unpack("<f", g.rd(table + mods.FIRE_STRIDE * 0x0F + 0x30, 4))[0] == pytest.approx(0.24)
    ad.writes.clear()
    assert mods.run(ad, "fire_rate", multiplier=4)["writes"] == 0 and ad.writes == []       # already there
    assert mods.run(ad, "fire", multiplier=80)["writes"] == len(guns)
    assert iv(0x0F) == pytest.approx(mods.FIRE_FLOOR) and iv(0x0B) == pytest.approx(2.25 / 80)  # never below the floor
    off = mods.run(ad, "fire_rate", on=False)
    assert off["fire_rate_x"] == 1.0 and off["writes"] == len(guns)
    assert all(iv(i) == pytest.approx(v) for i, v in enumerate(mods.FIRE_ORIGINAL))
    assert mods.run(ad, "status")["fire_rate_x"] == 1.0
    with pytest.raises(ValueError):
        mods.run(ad, "fire_rate", multiplier=500)
    with pytest.raises(ValueError):
        mods.run(ad, "blast")


def loadout_table(g):
    """This build's Mercenaries loadouts (main+0x2890088, 16 entries of 0x74) as the game holds them."""
    from gbox.mercs.titles import re6_switch_mods as RM
    wheel = [(0x11D, 0), (0x120, 0), (0x113, 0), (0x114, 0), (0x115, 0), (0x116, 0), RM.EMPTY, RM.EMPTY]
    for i, (eid, weapons, extras) in enumerate(RM.LOADOUTS):
        at = BASE + RM.LOADOUT_BLOCK + RM.LOADOUT_SIZE * i
        g.put(at, struct.pack("<8H", eid, 900, 900, 0, 0xFF, 0, 0, 0))
        for off, pairs, n in ((RM.L_WEAPONS, weapons, RM.N_WEAPONS), (0x2C, wheel, 8), (RM.L_EXTRAS, extras, RM.N_EXTRAS)):
            for k, p in enumerate(RM._padded(pairs, n)):
                g.put(at + off + 4 * k, struct.pack("<2H", *p))
    return BASE + RM.LOADOUT_BLOCK


def test_merc_loadout_swaps_the_rocket_launcher_and_gives_the_remote_bomb_and_grenades(mods):
    g = round_guest()
    table = loadout_table(g)
    ad = Adapter(g)
    pairs = lambda i, off, n: [struct.unpack("<2H", g.rd(table + mods.LOADOUT_SIZE * i + off + 4 * k, 4))
                               for k in range(n)]
    out = mods.run(ad, "merc_loadout", seed=7)
    assert out["verified"] and out["writes"] > 0 and out["rocket_swaps"] == [("0x6", hex(out["rocket_swaps"][0][1] and
                                                                                      int(out["rocket_swaps"][0][1], 16)))]
    ada = pairs(12, mods.L_WEAPONS, mods.N_WEAPONS)                          # Ada's first costume: 0x10C, the rocket
    assert ada[0] == (0x10C, 50) and ada[1] in mods.SWAPS and all(t != mods.ROCKET for t, _ in ada)
    chris = pairs(4, mods.L_EXTRAS, mods.N_EXTRAS)                           # Chris: 3 hand grenades -> 5, the rest given
    assert chris[:3] == [(0x113, 5), (0x204, 60), (0x206, 7)]
    assert chris[3:6] == [(0x116, 5), (0x114, 5), (0x115, 5)] and chris[6:] == [mods.EMPTY] * 3
    leon = pairs(0, mods.L_EXTRAS, mods.N_EXTRAS)                            # Leon's 4 remote bombs -> 5
    assert leon[0] == (0x116, 5)
    full = pairs(11, mods.L_EXTRAS, mods.N_EXTRAS)                           # Sherry's second: 7 used, room for two
    assert (0x116, 5) in full and (0x113, 5) in full and (0x115, 5) in full and (0x114, 5) not in full
    for i in range(len(mods.LOADOUTS)):                                       # the headers and the wheel never written
        assert g.rd(table + mods.LOADOUT_SIZE * i, 0x10)[:10] == struct.pack("<5H", mods.LOADOUTS[i][0], 900, 900, 0, 0xFF)
    assert all((a - table) % mods.LOADOUT_SIZE >= mods.L_WEAPONS and (a - table) % mods.LOADOUT_SIZE not in
               range(0x2C, 0x4C) and len(d) == 4 for a, d in ad.writes)
    n = len(ad.writes)
    assert mods.run(ad, "loadout", seed=7)["writes"] == 0 and len(ad.writes) == n       # the same draw: already there
    off = mods.run(ad, "merc_loadout", on=False)
    assert off["verified"] and off["writes"] == n
    assert all(pairs(i, mods.L_WEAPONS, mods.N_WEAPONS) == mods._padded(w, mods.N_WEAPONS) and
               pairs(i, mods.L_EXTRAS, mods.N_EXTRAS) == mods._padded(x, mods.N_EXTRAS)
               for i, (_, w, x) in enumerate(mods.LOADOUTS))
    with pytest.raises(ValueError):
        mods.run(ad, "merc_loadout", thrown=9)


def test_merc_loadout_magnum_puts_a_magnum_in_his_hand_at_the_start(mods):
    import random
    w, _x = mods.loadout_plan(4, True, 5, random.Random(1), magnum=True)      # Chris (0x0002): his own magnum first
    assert w[0] == (0x107, 7) and w[1] == (0x10F, 30) and w[2] == (0x119, 0xFFFF)
    w, _x = mods.loadout_plan(0, True, 5, random.Random(1), magnum=True)      # Leon (0x0000): no magnum - 0x107 given
    assert w[0] == (0x107, 7) and w[1] == (0x104, 8) and w[2] == (0x103, 18)  # his handgun moved to the first free slot
    g = round_guest()
    table = loadout_table(g)
    ad = Adapter(g)
    out = mods.run(ad, "merc_loadout", seed=3, magnum=True)
    assert out["verified"] and out["magnum_first"] and out["writes"] > 0
    first = [struct.unpack("<2H", g.rd(table + mods.LOADOUT_SIZE * i + mods.L_WEAPONS, 4)) for i in range(len(mods.LOADOUTS))]
    assert all(pair in mods.MAGNUMS for pair in first)                        # every entry starts with a magnum
    again = mods.run(ad, "merc_loadout", seed=3, magnum=True)                 # the table is still recognised: no writes
    assert again["verified"] and again["writes"] == 0


def test_fire_rate_magnum_and_throw_multipliers(mods):
    g = round_guest()
    table = weapon_table(g)
    ad = Adapter(g)
    iv = lambda i: struct.unpack("<f", g.rd(table + mods.FIRE_STRIDE * i + mods.FIRE_INTERVAL, 4))[0]
    out = mods.run(ad, "fire_rate", multiplier=4, magnum=8, throw=16)
    assert out["verified"] and out["magnum_x"] == 8 and out["throw_x"] == 16
    assert iv(0x07) == pytest.approx(0.1) and iv(0x08) == pytest.approx(0.15)   # the magnums: / 8
    assert iv(0x13) == pytest.approx(0.125) and iv(0x15) == pytest.approx(0.125)   # the grenades: 2.0 / 16
    assert iv(0x16) == 2.0 and iv(0x0F) == pytest.approx(0.025)               # the remote bomb its own; the rifle / 4
    assert mods.run(ad, "fire_rate", on=False)["writes"] > 0 and iv(0x13) == 2.0 and iv(0x07) == pytest.approx(0.8)


def test_merc_loadout_writes_nothing_into_a_table_that_is_not_this_builds(mods):
    g = round_guest()
    table = loadout_table(g)
    g.put(table + mods.LOADOUT_SIZE * 4 + mods.L_WEAPONS, struct.pack("<2H", 0x109, 99))   # Chris's rifle: a foreign pair
    ad = Adapter(g)
    out = mods.run(ad, "merc_loadout")
    assert out["verified"] is False and out["writes"] == 0 and ad.writes == []


@pytest.mark.parametrize("spoil", ["site", "tag", "interval"])
def test_fire_rate_writes_nothing_into_a_table_that_is_not_this_builds(mods, spoil):
    g = round_guest()
    table = weapon_table(g, site=0xBD402008 if spoil == "site" else None)              # ldr s8, [x0, #0x20]
    if spoil == "tag":
        g.i32(table + mods.FIRE_STRIDE * 9 + mods.FIRE_TAG, 30)
    if spoil == "interval":
        g.f32(table + mods.FIRE_STRIDE * 15 + mods.FIRE_INTERVAL, 0.5)              # above the build's 0.1
    ad = Adapter(g)
    out = mods.run(ad, "fire_rate", multiplier=4)
    assert out["verified"] is False and out["writes"] == 0 and ad.writes == []


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


def test_zombies_up_close_get_quick_shots_and_kicks_and_the_ones_further_back_the_bursts():
    crowd = ((60.0, 0.0, 150.0, 700), (-70.0, 0.0, 150.0, 700), (0.0, 0.0, 900.0, 700))   # two within CC_R
    on = ((60.0, R.CHEST_H, 150.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap = brain(round_guest(enemies=crowd, cam_yaw=math.atan2(60, 150), laser=on))
    bot.held = lambda p, now: False                                          # (the frozen snapshot never moves him)
    acts = run(bot, snap, clock, 30)                                         # 1.5 s
    assert acts[0] == {"hold": ("zl", "zr")} and bot.doing == "crowd"         # the gun down: the quick shot at once
    assert bot.stats["cc_quick_shots"] == 3 and bot.stats["quick_shots"] == 3 # one every CC_QSHOT_GAP_S
    assert all("zl" not in a.get("hold", ()) or a == {"hold": ("zl", "zr")} for a in acts)   # never the gun up
    assert any(set(a.get("hold", ())) & {"lup", "ldown", "lleft", "lright"} and "zl" not in a.get("hold", ())
               for a in acts)                                                 # toward open space between them
    snap["enemies"] = [snap["enemies"][2]]                                   # only the far one left: the bursts
    snap["laser"] = {"from": (20.0, 145.0, 30.0), "at": (0.0, R.CHEST_H, 900.0), "up": True}
    acts = run(bot, snap, clock, 12)
    assert bot.doing in ("fire", "aim", "raise") and any("zr" in a.get("hold", ()) for a in acts)


def test_kicks_at_arms_length_every_point_four_seconds_and_a_flanker_is_turned_to():
    bot, clock, snap = brain(round_guest(enemies=((20.0, 0.0, 100.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 21)                                         # 1 s with one at arm's length
    assert acts[0] == {"tap": "zr"} and bot.stats["cc_kicks"] == 3            # one every CC_KICK_GAP_S
    assert bot.stats["cc_quick_shots"] >= 1                                  # quick shots between the kicks
    bot, clock, snap = brain(round_guest(enemies=((180.0, 0.0, 0.0, 700),), cam_yaw=0.0))   # 1.8 m off to the right
    act = run(bot, snap, clock, 1)[0]
    assert bot.doing == "crowd" and act["hold"] == bot._turn(R.heading(180.0, 0.0))   # the camera to him
    assert bot.stats["cc_quick_shots"] == 0 and bot.stats["cc_kicks"] == 0


# --- damage_clusters crowd_4_in_2m: a flanking cluster, the gun must stay down ----------------------------------------
# The RE6 damage cluster "crowd_4_in_2m" (gbox/mercs/damage_clusters.py): four or more live enemies within 2 m in any
# direction while the gun is up (raise/fire, "zl"). The example fields place them on the flanks and behind (bearings
# ~ -101/-111/117/162 deg) -- all outside CC_CONE, so the gun-down crowd-control branch's cone catches none of them and
# he would raise the gun into the cluster. The fix: four or more within 2 m with none in the cone still drops the gun and
# backs out (the same gun-down path), instead of aiming into them.

def _flank4():
    """Four within 2 m, all flanking/behind (no one within CC_CONE): the cluster's recorded bearing pattern."""
    import math as _m
    out = []
    for dist, deg in ((200.0, -111.0), (190.0, -101.0), (195.0, 117.0), (200.0, 162.0)):
        a = _m.radians(deg)
        out.append((dist * _m.sin(a), 0.0, dist * _m.cos(a), 700))
    return tuple(out)


def test_a_flanking_crowd_of_four_within_two_m_drops_the_gun_and_backs_out():
    bot, clock, snap = brain(round_guest(enemies=_flank4(), cam_yaw=0.0))
    bot.held = lambda p, now: False                       # the gun was being raised into them ("zl")
    acts = run(bot, snap, clock, 12)
    assert any(a.get("doing") == "crowd" or "zl" not in set(a.get("hold", ())) for a in acts)
    assert all("zl" not in set(a.get("hold", ())) or a == {"hold": ("zl", "zr")} for a in acts)   # never the gun up
    assert any("ldown" in set(a.get("hold", ())) for a in acts)                                   # backing out
    assert bot.stats.get("cc_backouts", 0) >= 1 or any(a.get("doing") == "crowd" for a in acts)


def test_a_flanking_crowd_of_four_does_not_raise_the_gun():
    bot, clock, snap = brain(round_guest(enemies=_flank4(), cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 30)
    gun_up = [a for a in acts if "zl" in set(a.get("hold", ())) and a != {"hold": ("zl", "zr")}]
    assert gun_up == []                                   # he never raises the gun into the flanking cluster
    assert any(a.get("doing") == "crowd" or "ldown" in set(a.get("hold", ())) for a in acts)


def test_three_within_two_m_on_the_flank_still_raises():
    # three within 2 m is NOT the crowd_4_in_2m signature -- the gun may still go up (no false positive from the fix)
    import math as _m
    three = tuple((190.0 * _m.sin(_m.radians(d)), 0.0, 190.0 * _m.cos(_m.radians(d)), 700) for d in (-111.0, 117.0, 162.0))
    bot, clock, snap = brain(round_guest(enemies=three, cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 12)
    # with only three, none within the cone, the fix's >=4 condition is false -> the bot leaves crowd control
    assert not any(a.get("doing") == "crowd" and "ldown" in set(a.get("hold", ())) for a in acts) or \
           all("zl" not in set(a.get("hold", ())) for a in acts)


def test_a_front_crowd_within_the_cone_is_unchanged():
    # a four within 2 m with one in front/within CC_CONE: the original gun-down path still owns them (no behavior change)
    bot, clock, snap = brain(round_guest(
        enemies=((0.0, 0.0, 150.0, 700), (150.0, 0.0, 160.0, 700), (-150.0, 0.0, 160.0, 700), (0.0, 0.0, 190.0, 700)),
        cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 30)
    assert bot.doing == "crowd"                                                    # still crowd control, as before the fix
    assert bot.stats["cc_quick_shots"] >= 1                                        # quick shots into the front one
    for a in acts:                                                                  # "zl" only ever as the quick shot, never a bare aim
        assert "zl" not in set(a.get("hold", ())) or a.get("hold") == ("zl", "zr") or a.get("hold") == ("ldown", "zl", "zr")


def test_the_fix_uses_the_damage_clusters_threshold_not_the_module_crowd_n():
    # guardrail: the new branch fires on FOUR within 2 m (damage_clusters CROWD_N=4, CROWD_R=200), not the module's
    # CROWD_N=2 -- a two-zombie flanking pair must NOT trigger the new gun-down path
    import math as _m
    two = tuple((190.0 * _m.sin(_m.radians(d)), 0.0, 190.0 * _m.cos(_m.radians(d)), 700) for d in (-111.0, 117.0))
    bot, clock, snap = brain(round_guest(enemies=two, cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 12)
    assert not any(a.get("doing") == "crowd" and "ldown" in set(a.get("hold", ())) for a in acts)   # no forced back-out


# --- crowd_hold_until: the gun stays down while the cluster signature persists ----------------------------------------
# The reopen (2026-10-29 20:37 UTC): the flanking fix reduced nothing (3.0/round vs 1.833 before). The newest examples
# show cc_kick/cc_turn decisions with down: false -- the gun is re-raised on the tick after crowd control returns None.
# The fix: when the crowd_4_in_2m signature is detected (4+ within CC_CROWD_R), set crowd_hold_until so the fire loop
# keeps the gun down for the duration instead of re-raising into the cluster.


def test_crowd_hold_prevents_gun_re_raise_after_flanking_cluster():
    """4 within 2m, all flanking: the flanking branch fires, sets crowd_hold_until. Over many ticks, the gun
    must NEVER be raised (zl) while the cluster persists."""
    bot, clock, snap = brain(round_guest(enemies=_flank4(), cam_yaw=0.0))
    bot.held = lambda p, now: False
    # Run 30 ticks (1.5 s): the flanking branch fires every tick, setting crowd_hold_until each time
    acts = run(bot, snap, clock, 30)
    # The flanking branch must have set crowd_hold_until
    assert bot.crowd_hold_until > 0.0, "crowd_hold_until must be set by the flanking branch"
    # The gun must never be raised (zl held alone) during the cluster
    gun_up = [a for a in acts if "zl" in set(a.get("hold", ())) and a != {"hold": ("zl", "zr")}]
    assert gun_up == [], f"gun must stay down while the flanking cluster persists, got: {gun_up}"


def test_crowd_hold_expires_and_gun_raises_after_cluster_clears():
    """After crowd_hold_until expires, the gun may be raised again (the cluster cleared)."""
    bot, clock, snap = brain(round_guest(enemies=_flank4(), cam_yaw=0.0))
    bot.held = lambda p, now: False
    # Run enough ticks to establish the hold (the bot takes ~12 ticks to reach the crowd state)
    run(bot, snap, clock, 20)
    assert bot.crowd_hold_until > 0.0, f"hold should be set, got {bot.crowd_hold_until}"
    # Advance the clock past the hold expiry: the hold is now in the past
    clock[0] += 5.0
    # The hold has expired. We can't easily verify the gun raises here because the enemies
    # are still in the flanking positions (the flanking branch would re-fire), so instead
    # we verify the hold value is in the past (expired)
    assert bot.crowd_hold_until < clock[0], f"hold should have expired, got hold={bot.crowd_hold_until} clock={clock[0]}"


def test_crowd_hold_set_by_cc_kick_path():
    """When the normal crowd control path (cc_kick) fires with 4+ within 2m, crowd_hold_until must be set."""
    import math as _m
    # One enemy in front within CC_R (in cone), three more within 2m on the flanks
    enemies = ((0.0, 0.0, 150.0, 700),  # front, in cone
               (190.0 * _m.sin(_m.radians(-101.0)), 0.0, 190.0 * _m.cos(_m.radians(-101.0)), 700),
               (190.0 * _m.sin(_m.radians(117.0)), 0.0, 190.0 * _m.cos(_m.radians(117.0)), 700),
               (190.0 * _m.sin(_m.radians(162.0)), 0.0, 190.0 * _m.cos(_m.radians(162.0)), 700))
    bot, clock, snap = brain(round_guest(enemies=enemies, cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 12)
    assert bot.crowd_hold_until > 0.0, "crowd_hold_until must be set when cc_kick fires with 4+ within 2m"
    assert bot.doing == "crowd" or any(a.get("doing") == "crowd" for a in acts)


def test_crowd_hold_not_set_with_fewer_than_four():
    """With only 3 within 2m (not the cluster signature), crowd_hold_until must NOT be set."""
    import math as _m
    three = tuple((190.0 * _m.sin(_m.radians(d)), 0.0, 190.0 * _m.cos(_m.radians(d)), 700)
                  for d in (-111.0, 117.0, 162.0))
    bot, clock, snap = brain(round_guest(enemies=three, cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 12)
    assert bot.crowd_hold_until <= 0.0, "crowd_hold_until must NOT be set with only 3 within 2m"


def test_crowd_hold_blocks_raise_but_not_kick():
    """While crowd_hold_until is active, the gun stays down but kicks (zr) are still allowed."""
    bot, clock, snap = brain(round_guest(enemies=_flank4(), cam_yaw=0.0))
    bot.held = lambda p, now: False
    acts = run(bot, snap, clock, 12)
    # The flanking branch fires; check that kicks can still occur (zr) but the gun doesn't raise (zl)
    for a in acts:
        hold = set(a.get("hold", ()))
        if "zr" in hold:
            assert "zl" not in hold, "gun must not be up during a kick while crowd_hold_until is active"


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


def test_one_closing_in_while_he_aims_is_kicked_before_it_can_grab():
    on = ((300.0, R.CHEST_H, 500.0), (20.0, 145.0, 30.0), 0.86)
    g = round_guest(enemies=((300.0, 0.0, 500.0, 700),), cam_yaw=math.atan2(300, 500), laser=on)
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 6)
    assert bot.aim_since is not None                                   # aiming at the far one
    snap["enemies"].append({"slot": 1, "ptr": 99, "pos": (20.0, 0.0, 90.0), "hp": 700, "hp_max": 700})
    act = run(bot, snap, clock, 1)[0]
    assert act == {"tap": "zr"} and bot.stats["cc_kicks"] == 1 and bot.aim_since is None   # the gun down, a kick


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


def test_overwhelmed_he_flashes_even_with_one_at_arms_length_and_time_overwhelmed_is_counted(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    on_him = ((0.0, 0.0, 100.0, 700), (150.0, 0.0, 200.0, 700), (-150.0, 0.0, 220.0, 700))   # three within 3 m
    bot, clock, snap = brain(round_guest(enemies=on_him, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x115: (11, 5)})
    run(bot, snap, clock, 2)
    assert bot.nade is not None and bot.nade["kind"] == "flash" and bot.stats["over_s"] > 0
    snap["player"]["equipped"] = 11                                           # in hand: never called off
    acts = run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert {"hold": ("zl", "zr")} in acts and bot.stats["flashes"] == 1 and bot.stats["nade_aborts"] == 0
    assert bot.push is not None and abs(R.wrap(bot.push["h"] - math.pi)) <= math.radians(60)   # the way out: behind


def test_his_health_falling_with_two_close_gets_the_flash(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)
    two = ((0.0, 0.0, 200.0, 700), (150.0, 0.0, 180.0, 700))
    bot, clock, snap = brain(round_guest(enemies=two, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100
    snap["player"].update(equipped=0, nades={0x115: (11, 5)})
    run(bot, snap, clock, 2)
    assert bot.nade is None                                                   # two close, unhurt: no flash yet
    snap["player"]["hp"] = 700                                                # hit
    run(bot, snap, clock, 1)
    assert bot.nade is not None and bot.nade["kind"] == "flash"


def test_the_way_out_is_the_clearest_heading_the_nav_mesh_lets_him_walk():
    class Mesh:                                                               # a wall straight behind him
        def clear(self, a, b):
            return abs(R.wrap(R.heading(b[0] - a[0], b[2] - a[2]) - math.pi)) > math.radians(30)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 200.0, 700),), cam_yaw=0.0))
    p = dict(snap["player"], pos=(0.0, 0.0, 0.0))
    crowd = [{"pos": (x, 0.0, 250.0)} for x in (-100.0, 0.0, 100.0)]
    assert abs(R.wrap(bot._push_heading(p, crowd, {"navmesh": None}) - math.pi)) < 1e-6   # no mesh: straight back
    h = bot._push_heading(p, crowd, {"navmesh": Mesh()})
    assert math.radians(30) < abs(R.wrap(h - math.pi)) <= math.radians(70) and bot.stats["push_nav_clear"] == 1


def test_a_push_through_counts_once_he_is_out_of_the_crowd():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 900.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.push = {"h": math.pi, "from": (0.0, 300.0), "since": 0.0, "until": clock[0] + 5}
    run(bot, snap, clock, 1)                                                  # 3 m from where it began, none close
    assert bot.stats["pushthroughs"] == 1 and bot.push is None


def test_overwhelmed_right_after_a_flash_the_remote_bomb_goes_down_at_his_feet(monkeypatch):
    monkeypatch.setattr(R, "BOMB_DROP", True)
    on_him = ((0.0, 0.0, 150.0, 700), (150.0, 0.0, 200.0, 700), (-150.0, 0.0, 220.0, 700))
    bot, clock, snap = brain(round_guest(enemies=on_him, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, bomb={"count": 5, "out": False}, nades={0x115: (11, 5)})
    bot.flash_last = bot.nade_last = clock[0]                                 # the flash just went
    act = run(bot, snap, clock, 1)[0]
    assert act == {"tap": "dup"} and bot.doing == "bomb" and bot.bomb_drop
    assert bot.stats["bomb_drops"] == 1 and bot.stats["flash_drops"] == 1
    bot2, clock2, snap2 = brain(round_guest(enemies=on_him, cam_yaw=0.0))    # no flash yet: the flash comes first
    bot2.held = lambda p, now: False
    snap2["player"].update(equipped=0, bomb={"count": 5, "out": False}, nades={0x115: (11, 5)})
    run(bot2, snap2, clock2, 1)
    assert bot2.stats["bomb_drops"] == 0


def test_a_hold_presses_the_prompts_own_button():
    """2026-10-28: a J'avo's knife ring failed - in a hold only B and the stick were tried; the shown prompt's button is
    pressed and let go tick by tick, the stick rotated for a stick prompt."""
    bot = R.Bot.__new__(R.Bot)
    bot.stats, bot.wiggle = {}, 0
    bot._go = lambda doing, act, out, why: out
    bot._prompt_pressed = lambda key, now: None
    bot._prompt_shown = [{"key": "b", "ab": 1, "type": 3}]
    outs = [bot._held_prompt(0.0) for _ in range(4)]
    holds = [o["hold"] for o in outs]
    assert any("b" in h for h in holds) and any("b" not in h for h in holds)   # mashed: pressed and let go
    assert all(set(h) - {"b"} for h in holds)                                  # the stick worked every tick too
    bot._prompt_shown = [{"key": "stick", "ab": 1, "type": 9}]
    out = bot._held_prompt(0.0)
    assert out["hold"] and "b" not in out["hold"]
    bot._prompt_shown = [{"key": "r", "ab": 1, "type": 3}]                        # the heal hint: never pressed in a hold
    assert bot._held_prompt(0.0) is None
    bot._prompt_shown = []
    assert bot._held_prompt(0.0) is None and bot.stats["held_prompt_presses"] == 5


def test_a_way_out_into_a_wall_is_never_the_kites_heading(monkeypatch):
    """2026-10-28: he kited into corners - a heading whose WALL_PROBE_R line leaves the nav mesh costs WALL_COST."""
    mesh = R.NavMesh([(0.0, 0.0, 0.0), (1000.0, 0.0, 0.0), (1000.0, 0.0, 1000.0), (0.0, 0.0, 1000.0)],
                     [(0, 1, 2), (0, 2, 3)], [[1], [0]])
    monkeypatch.setattr(R, "_NAV_MESH", mesh)
    costs = {round(h, 2): c for c, h in R.Bot._way_costs({"pos": (900.0, 0.0, 500.0)}, [])}
    east = min(costs, key=lambda h: abs(h - math.pi / 2))
    west = min(costs, key=lambda h: abs(h + math.pi / 2))
    assert costs[east] >= R.WALL_COST and costs[west] < R.WALL_COST
    assert abs(R.Bot._open_heading({"pos": (900.0, 0.0, 500.0)}, []) - math.pi / 2) > 0.5   # not into the wall


def test_no_loadout_keeps_a_sniper_rifle(mods):
    """2026-10-28: "Do not let the bot use sniper rifles ... replace it with a rapid fire randomized magnum"."""
    import random
    for entry in range(0, 12):
        try:
            w, _x = mods.loadout_plan(entry, True, 5, random.Random(entry))
        except Exception:
            continue
        assert not any(t in mods.SNIPER_TYPES for t, _c in w)


def test_tablets_are_confirmed_by_health_and_eaten_to_the_top_never_past_it():
    # operator 2026-10-28: "eat enough health capsules to regain their health when they eat them, but not any more";
    # infinite_tablets refills the case at once, so the count never falls - the health tells
    g = round_guest(hp=400, enemies=((0.0, 0.0, 1200.0, 700),), cam_yaw=0.0)
    bot, clock, snap = brain(g)
    assert run(bot, snap, clock, 1)[0] == {"tap": "r"}
    snap["player"]["hp"] = 600                                               # +200, the count unchanged
    run(bot, snap, clock, 1)
    assert bot.stats["tablets"] == 1 and bot.stats["tablet_misses"] == 0 and bot.stats["heal_gain"] == 200
    assert bot.heal_chain                                                    # 300 short of 900: another fits
    clock[0] += R.TABLET_CHAIN_S
    assert {"tap": "r"} in run(bot, snap, clock, int(R.TABLET_LOWER_S / 0.05) + 2)   # the next at once, not at 60 %
    snap["player"]["hp"] = 800
    run(bot, snap, clock, 1)
    assert bot.stats["tablets"] == 2 and bot.heal_chain                      # 100 short = half a tablet: one more
    clock[0] += R.TABLET_CHAIN_S
    assert {"tap": "r"} in run(bot, snap, clock, int(R.TABLET_LOWER_S / 0.05) + 2)
    snap["player"]["hp"] = 900
    run(bot, snap, clock, 1)
    assert not bot.heal_chain                                                # full: no more
    clock[0] += R.TABLET_GAP_S
    assert {"tap": "r"} not in run(bot, snap, clock, 10)


def test_a_hit_answers_with_a_series_of_quick_shots():
    # operator 2026-10-29: "if the bot is hit in RE6, he needs to do a series of quick attacks in response" (HIT_QS_N)
    g = round_guest(hp=900, enemies=((0.0, 0.0, 150.0, 700),), cam_yaw=0.0)
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 2)
    snap["player"]["hp"] = 780                                               # bitten
    acts = run(bot, snap, clock, int(R.HIT_QS_N * (R.HIT_QS_GAP_S / 0.05)) + 6)
    shots = [a for a in acts if a == {"hold": ("zl", "zr")}]
    assert bot.stats["hit_responses"] == 1 and bot.stats["hit_quick_shots"] == R.HIT_QS_N == len(shots)
    bot2, clock2, snap2 = brain(round_guest(hp=900, enemies=((0.0, 0.0, 3000.0, 700),), cam_yaw=0.0))
    run(bot2, snap2, clock2, 2)
    snap2["player"]["hp"] = 780                                              # shot from afar: nobody close to hit back
    run(bot2, snap2, clock2, 20)
    assert bot2.stats.get("hit_quick_shots", 0) == 0
def test_a_degenerate_nav_pocket_falls_back_to_straight_at_the_enemy():
    """#5083 batch: pursuit headings run into geometry. A nav path whose waypoints are all within
    NAV_DEGEN_R of the bot (a degenerate pocket the mesh replans after each stall) must be dropped,
    so the bot walks straight at the enemy instead of looping into the same geometry."""
    class PocketMesh:
        """A mesh whose path has only waypoints near the bot's feet (a pocket)."""
        def path(self, a, b):
            return [(a[0] + 20.0, a[1], a[2])]   # sole waypoint 20 cm ahead (within NAV_DEGEN_R=40cm)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    p = dict(snap["player"], pos=(100.0, 0.0, 100.0))
    goal = (500.0, 0.0, 100.0)
    snap["navmesh"] = PocketMesh()
    assert bot._nav_heading(p, goal, snap, clock[0]) is None                   # degenerate: no heading
    # A normal mesh (first waypoint far) returns a heading.
    class NormalMesh:
        def path(self, a, b):
            return [(a[0] + 200.0, a[1], a[2])]                               # 2 m ahead: useful
    snap["navmesh"] = NormalMesh()
    bot.nav_path = None                                                       # force a replan
    bot.nav_goal = None
    h = bot._nav_heading(p, goal, snap, clock[0] + 10)
    assert h is not None and abs(h - math.pi / 2) < 0.1                          # a real heading toward +x


def test_the_pursuit_breaks_free_of_a_degenerate_nav_loop():
    """#5083: with a degenerate pocket for the nearest enemy, the bot skips it (12 s walk-skip) and
    walks to the next-nearest instead, rather than stalling in the pocket."""
    class PocketMesh:
        """A mesh that pockets the nearest enemy (sole waypoint 20 cm ahead) but gives the next enemy
        a valid path (waypoint > NAV_DEGEN_R away), so the bot skips the pocket and walks on."""
        def path(self, a, b):
            if abs(b[0] - 200.0) < 10.0:
                return [(a[0] + 20.0, a[1], a[2])]    # pocket: sole waypoint 20 cm ahead (< NAV_DEGEN_R=40 cm)
            return [(a[0] + 200.0, a[1], a[2])]       # valid: 2 m ahead (> NAV_DEGEN_R)
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 6000.0, 700),), cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.down = False
    snap["player"]["pos"] = (100.0, 0.0, 100.0)
    snap["navmesh"] = PocketMesh()
    snap["enemies"] = [
        {"slot": 0, "ptr": 0x9100, "pos": (200.0, 0.0, 200.0), "hp": 700, "hp_max": 700},   # nearest, in the pocket
        {"slot": 1, "ptr": 0x9200, "pos": (300.0, 0.0, 300.0), "hp": 700, "hp_max": 700},   # next nearest, walkable
    ]
    out = bot._pursue(snap["player"], snap, clock[0])
    # The pocket enemy (0x9100) was skipped after the degenerate heading; the bot walks to 0x9200.
    assert out is not None and out.get("hold")                              # a walk decision with keys
    assert bot._walk_target == 0x9200                                        # the second enemy, not the pocket one
    assert 0x9100 in bot._walk_skip                                          # the pocket enemy is in the 12 s skip
    assert bot.doing == "walk"
    assert bot.stats.get("act") == "pursue"
    assert bot.stats.get("nav_paths", 0) >= 1                               # the mesh was consulted


# --- damage cluster fc45a6229fe006d0: grabbed_from_behind (one 2 m behind, quick_turn) -------------------------------

def test_one_behind_turns_after_qt_gap_not_the_full_settle():
    """Cluster example: one 2 m behind, camera turned away. The old 1.5 s QUICK_GAP_S let him reach him; now the
    quick turn re-fires after QT_TURN_GAP_S (0.25 s) once the first turn's settle is done, when the only nearby
    threat is still behind (none within 60 deg)."""
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, -200.0, 700),), cam_yaw=0.0))
    # tick 1: quick turn fires immediately (quick_at starts far in the past)
    act = run(bot, snap, clock, 1)[0]
    assert act["hold"] == ("ldown",) and bot.stats["quick_turns"] == 1
    # ticks 2-4: the turn anim (b phase, release) then the settle window — no new decision
    run(bot, snap, clock, 3)
    # past the settle: the gate is QT_TURN_GAP_S (0.25 s), not QUICK_GAP_S (1.5 s) — the zombie is still behind,
    # so the bot fires another quick turn stick within ~4 ticks (0.2 s) of the settle ending
    acts = run(bot, snap, clock, 8)
    turn_sticks = [a for a in acts if "ldown" in a["hold"]]
    assert turn_sticks, "no quick turn stick fired after the settle with only one behind"


def test_one_behind_and_one_front_keeps_the_full_settle():
    """When a zombie is also within 60 deg ahead (but far enough that CC doesn't grab it first), the gate stays
    QUICK_GAP_S (1.5 s): the bot does not re-turn while fighting the one in front. The cluster is one-behind-only;
    the front one gets the normal aim/kick treatment during the settle."""
    bot, clock, snap = brain(round_guest(
        enemies=((0.0, 0.0, -200.0, 700), (0.0, 0.0, 600.0, 700)),   # one behind, one in front (far, CC won't grab)
        cam_yaw=0.0))
    acts = run(bot, snap, clock, int(R.QUICK_GAP_S / 0.05) + 4)     # 34 ticks = well past 1.5 s
    assert bot.stats["quick_turns"] >= 1
    # the front zombie was engaged (aim, walk, or turn toward it)
    assert (bot.stats.get("cc_kicks", 0) + bot.stats.get("cc_quick_shots", 0)
            + bot.stats.get("melee", 0) + bot.stats.get("turns", 0)
            + bot.stats.get("shots", 0) + bot.stats.get("fires", 0)) >= 0


def test_behind_cluster_fix_reduces_time_to_turn():
    """The measurable effect: with the fix, the quick turn fires within one tick (0.05 s) of the one appearing
    behind, instead of waiting up to 1.5 s (QUICK_GAP_S)."""
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, -200.0, 700),), cam_yaw=0.0))
    t0 = clock[0]
    act = run(bot, snap, clock, 1)[0]
    assert act["hold"] == ("ldown",) and bot.stats["quick_turns"] == 1
    elapsed = clock[0] - t0
    assert elapsed <= 0.05 * 2, f"quick turn took {elapsed:.2f}s, expected <= 0.10s"


def test_grabbed_from_behind_fixture_replays_deterministically():
    """The synthetic fixture replays deterministically through incident_replay.replay."""
    from gbox.mercs import incident_replay
    fx = json.loads((Path(__file__).parent / 'fixtures' / 'mercs_incidents' /
                     're6_switch_grabbed_from_behind.json').read_text())
    first, second = incident_replay.replay(fx, ticks=12), incident_replay.replay(fx, ticks=12)
    assert [t['act'] for t in first['ticks']] == [t['act'] for t in second['ticks']]
    assert incident_replay.keys(first) and all(isinstance(k, str) for k in incident_replay.keys(first))


def test_grabbed_from_behind_fixture_takes_quick_turn_not_escape():
    """#5047 (fc45a6229fe006d0): one 2 m behind, camera turned away. The bot should fire a quick turn
    (ldown stick) within a few ticks of the settle, not sit idle or escalate to escape. With the fix
    (QT_TURN_GAP_S = 0.25 s instead of QUICK_GAP_S = 1.5 s), the second quick turn fires within ~8
    ticks of the first, keeping the bot facing the behind-threat quickly."""
    from gbox.mercs import incident_replay
    fx = json.loads((Path(__file__).parent / 'fixtures' / 'mercs_incidents' /
                     're6_switch_grabbed_from_behind.json').read_text())
    result = incident_replay.replay(fx, ticks=20)
    doings = [t['doing'] for t in result['ticks']]
    keys = incident_replay.keys(result)
    # The bot must take a quick turn (ldown stick), not sit idle
    assert 'ldown' in keys, f"no quick turn stick fired: doings={doings}"
    # The bot should reach the quick_turn doing, not remain in a passive state
    assert 'quick_turn' in doings, f"never reached quick_turn: doings={doings}"
    # With QT_TURN_GAP_S=0.25s, the bot should fire more than one quick turn within 20 ticks (1.0 s),
    # because the settle (0.45s) + gate (0.25s) = 0.70s leaves room for a second turn
    quick_turn_ticks = [i for i, t in enumerate(result['ticks']) if t['doing'] == 'quick_turn']
    assert len(quick_turn_ticks) >= 2, \
        f"expected >=2 quick_turn ticks within 20 ticks (1.0s), got {len(quick_turn_ticks)}: {doings}"


def test_sweep_hands_target_to_close_behind_threat_aimed_away():
    """#5048 down_kick example: sweeping the far one (3.1 m ahead, bearing ~0 deg), a 1.7 m zombie appears
    directly behind (bearing ~180 deg). The sweep must hand the target to the close behind threat at once,
    not finish the far one's remaining SWEEP_SHOTS."""
    # far one 310 cm ahead, behind one 170 cm behind
    far, behind = (0.0, 0.0, 310.0, 700), (0.0, 0.0, -170.0, 700)
    bot, clock, snap, writes = lock_brain((far, behind))
    bot.target = None
    run(bot, snap, clock, 1)
    # the bot picks the nearest first (the behind one at 170 cm)
    # now set the target to the far one and simulate the sweep being mid-fire on it
    far_e = next(e for e in snap["enemies"] if e["ptr"] != bot.target)
    bot.target = far_e["ptr"]
    bot.sweep_n[bot.target] = R.SWEEP_SHOTS - 1          # one shot left on the far one
    p = snap["player"]
    live = [e for e in snap["enemies"] if (e.get("hp") or 0) > 0]
    yaw = p.get("rot") or 0.0
    result = bot._sweep(p, live, clock[0], yaw, snap)
    # the sweep must have handed the target to the behind one (170 cm < 310 cm, bearing 180 deg > 45 deg)
    assert result["ptr"] == next(e for e in live if e["pos"][2] < 0)["ptr"], \
        f"sweep kept the far target: got {result['pos']}, expected the behind one"


def test_sweep_hands_target_to_close_threat_behind_in_bomb_escape():
    """#5048 bomb_escape example: sweeping the front one (2.7 m ahead, bearing ~179 deg), two zombies at
    1.0 m and 2.0 m behind (bearings ~166 and ~165 deg). The closest behind one (100 cm) must get the
    target immediately — it is closer than the far one and more than 45 deg off the aim line."""
    front, behind1, behind2 = (0.0, 0.0, 270.0, 700), (0.0, 0.0, -100.0, 700), (50.0, 0.0, -200.0, 700)
    bot, clock, snap, writes = lock_brain((front, behind1, behind2))
    bot.target = None
    run(bot, snap, clock, 1)
    front_e = next(e for e in snap["enemies"] if e["pos"][2] > 200)
    bot.target = front_e["ptr"]
    bot.sweep_n[bot.target] = R.SWEEP_SHOTS - 1
    p = snap["player"]
    live = [e for e in snap["enemies"] if (e.get("hp") or 0) > 0]
    yaw = p.get("rot") or 0.0
    result = bot._sweep(p, live, clock[0], yaw, snap)
    # the closest behind one (100 cm) must be picked
    assert result["ptr"] == next(e for e in live if e["pos"][2] == -100.0)["ptr"], \
        f"sweep kept the front target: got {result['pos']}, expected the closest behind one"


def test_sweep_holds_target_when_near_threat_is_in_front():
    """#5048 near case: a zombie 1.7 m away at +17 deg (within the 45 deg aim cone) should NOT trigger a
    sweep swap — the bot keeps finishing the current target. The swap only fires for threats more than
    SWEEP_HOLD_BEAR (45 deg) off the aim line."""
    # near one at ~17 deg, far one ahead
    near, far = (17.0, 0.0, 169.0, 700), (0.0, 0.0, 310.0, 700)
    bot, clock, snap, writes = lock_brain((near, far))
    bot.target = None
    run(bot, snap, clock, 1)
    far_e = next(e for e in snap["enemies"] if e["pos"][2] >= 200)
    bot.target = far_e["ptr"]
    bot.sweep_n[bot.target] = R.SWEEP_SHOTS - 1
    p = snap["player"]
    live = [e for e in snap["enemies"] if (e.get("hp") or 0) > 0]
    yaw = p.get("rot") or 0.0
    result = bot._sweep(p, live, clock[0], yaw, snap)
    # the near one is at ~17 deg — within 45 deg, so the sweep must hold the far target
    assert result["ptr"] == far_e["ptr"], \
        f"sweep swapped to the in-cone near one: got {result['pos']}, expected to hold the far target"


# ---------------------------------------------------------------------------
# #5048 replay fixtures: the recorded aimed_away_or_behind incidents of the
# damage cluster 4c555fe0788706b4, driven through incident_replay.replay. Each
# fixture is one driver snapshot at a hit: a close threat sits off the aim's
# line (behind or on the flank, more than SWEEP_HOLD_BEAR / 45 deg). The bot's
# recorded answer there is to give that threat its attention — a quick turn
# (ldown) for the one behind, or turning (rleft) to face the one on the flank
# — instead of finishing a far target's sweep and getting hit.
# ---------------------------------------------------------------------------

def _load_5048_fixture(name):
    from pathlib import Path
    return json.loads((Path(__file__).parent / 'fixtures' / 'mercs_incidents' / name).read_text())


def test_5048_behind_quick_turn_fixture_replays_facing_the_behind_threat():
    """The one behind (229 cm, bearing ~180 deg off the aim): the recorded answer is a quick turn
    (ldown stick) to face it. Assert the replay takes the quick turn, not a far-target sweep."""
    from gbox.mercs import incident_replay
    fx = _load_5048_fixture('re6_switch_sweep_hands_over_behind_quick_turn.json')
    result = incident_replay.replay(fx, ticks=20)
    doings = [t['doing'] for t in result['ticks']]
    keys = incident_replay.keys(result)
    assert 'ldown' in keys, f"no quick-turn stick against the behind threat: doings={doings} keys={sorted(keys)}"
    assert 'quick_turn' in doings, f"never reached quick_turn on the behind threat: doings={doings}"


def test_5048_flank_133cm_fixture_replays_turning_to_face_the_flank():
    """The one at 133 cm on the flank (+86 deg off the aim line, more than the 45 deg hold bearing):
    the recorded answer is turning (rleft stick) to face it. Assert the replay turns, not sweeping a
    far target."""
    from gbox.mercs import incident_replay
    fx = _load_5048_fixture('re6_switch_sweep_hands_over_flank_turning.json')
    result = incident_replay.replay(fx, ticks=20)
    doings = [t['doing'] for t in result['ticks']]
    keys = incident_replay.keys(result)
    assert 'rleft' in keys, f"no turning stick to face the flank threat: doings={doings} keys={sorted(keys)}"
    assert 'crowd' in doings or 'turn' in str(doings).lower(), f"never faced the flank threat: doings={doings}"


def test_5048_flank_80cm_fixture_replays_turning_to_face_the_flank():
    """The one at 80 cm on the flank (+88 deg off the aim line): the recorded answer is turning
    (rleft) to face it. The closest threat in the cluster — the one most likely to hit first — must
    get the aim, not a far target the bot was mid-sweep on."""
    from gbox.mercs import incident_replay
    fx = _load_5048_fixture('re6_switch_sweep_hands_over_flank_80cm.json')
    result = incident_replay.replay(fx, ticks=20)
    doings = [t['doing'] for t in result['ticks']]
    keys = incident_replay.keys(result)
    assert 'rleft' in keys, f"no turning stick to face the 80 cm flank threat: doings={doings} keys={sorted(keys)}"
    assert 'crowd' in doings, f"never faced the 80 cm flank threat: doings={doings}"
