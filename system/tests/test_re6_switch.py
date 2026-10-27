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
    R._BONUS.update(base=None)
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
    assert R.screen(round_guest())["where"] == "playing"                           # the round is up: drawn anew next
    assert R.PICK.stage is None and R.PICK.queued == {}
    seen = set()
    for _ in range(40):
        R.PICK.reset()
        seen.add(R.screen(g)["target"])
    assert seen == {1, 4, 7}
    locked = menu_guest("uIdStartUp31", R.MENU_CURSOR, 0)                          # no bit readable: Urban Chaos
    assert R.screen(locked)["target"] == R.STAGE_TARGET


def test_the_character_select_puts_a_random_costume_on_the_character_then_confirms(monkeypatch):
    import random
    monkeypatch.setattr(R, "PICK", R._Pick(random.Random(3)))
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
    acts = run(bot, snap, clock, 20)                                          # two at his back: never standing
    assert all("ldown" in a.get("hold", ()) for a in acts) and bot.stats["bomb_face_s"] == 0.0
    assert bot.stats["bomb_kicks"] >= 2
    on_it = ((40.0, 0.0, 300.0, 700), (-40.0, 0.0, 320.0, 700))
    bot, clock, snap = bomb_out(on_it, me=six)
    acts = run(bot, snap, clock, int(30.0 / 0.05))                            # 30 s at 6 m (a wall behind)
    assert all("zr" not in a.get("hold", ()) for a in acts)                   # never set off inside 7 m, however long


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


def test_a_death_is_logged_with_its_cause_and_forgets_the_bomb():
    bot, clock, snap = bomb_out(((0.0, 0.0, 120.0, 700),) * 3)
    run(bot, snap, clock, 4)
    snap["player"].update(hp=0, state=0)
    run(bot, snap, clock, 1)
    d = bot.stats["death_log"][-1]
    assert d["near_2m"] == 3 and d["bomb_phase"] == "wait" and d["bomb_cm"] == 300 and d["held"] is False
    assert bot.bomb_at is None and bot.bomb_phase is None


def test_the_bomb_walk_turns_the_camera_to_the_bomb_and_a_blast_that_hurts_him_is_counted():
    bot, clock, snap = bomb_out(((0.0, 0.0, 3000.0, 700),), me=(-300.0, 0.0, R.BOMB_AHEAD))   # the bomb 3 m to his right
    act = run(bot, snap, clock, 1)[0]
    assert act["hold"][0] == "ldown" and act["hold"][1:] == bot._turn(R.heading(300.0, 0.0))  # the camera to it
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
    near = ((0.0, 0.0, 300.0, 700), (100.0, 0.0, 350.0, 700), (-100.0, 0.0, 380.0, 700))   # three at 3-3.8 m
    bot, clock, snap = brain(round_guest(enemies=near, cam_yaw=0.0))
    bot.held = lambda p, now: False
    bot.melee_at = bot.qshot_at = clock[0] + 100                              # (no crowd-control press in the way)
    snap["player"].update(equipped=0, nades={0x113: (9, 5), 0x114: (10, 5), 0x115: (11, 5)})
    acts = run(bot, snap, clock, 3)
    assert {"tap": "dup"} in acts and bot.nade["kind"] == "flash"            # the wheel's up to the flash grenade
    snap["player"]["equipped"] = 11
    acts = run(bot, snap, clock, int(R.NADE_AIM_S / 0.05) + 3)
    assert {"hold": ("zl",)} in acts and {"hold": ("zl", "zr")} in acts and bot.stats["flashes"] == 1
    acts = run(bot, snap, clock, int(R.NADE_STEP_S / 0.05) + 3)
    assert {"tap": "dright"} in acts                                          # the gun back
    snap["player"]["equipped"] = 0
    bot.melee_at = -1e9
    acts = run(bot, snap, clock, 4)
    assert bot.nade is None and bot.stats["act"] in ("fever_close", "fever_kick")
    assert any("lup" in a.get("hold", ()) for a in acts)                      # in among them
    snap["enemies"][0]["pos"] = (0.0, 0.0, 100.0)
    acts = run(bot, snap, clock, 2)
    assert any("zr" in a.get("hold", ()) for a in acts) and bot.stats["fever_kicks"] >= 1
    assert bot.stats["bomb_drops"] == 0                                       # the fever first, no bomb drop
    assert all("zl" not in a.get("hold", ()) for a in acts)                   # kicks, no quick shots


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
    acts = run(bot, snap, clock, int(R.NADE_STEP_S / 0.05) + 3)
    assert {"tap": "dright"} in acts and bot.nade is not None                 # not his gun yet: on to it
    snap["player"]["equipped"] = 0
    run(bot, snap, clock, 1)
    assert bot.nade is None and bot.stats["nade_wheel"][-1]["to"] == 9


def test_a_throw_is_called_off_with_the_gun_back_first_when_one_comes_close(monkeypatch):
    monkeypatch.setattr(R, "NADES", True)                                    # (off in play until the wheel is measured)
    cluster = ((0.0, 0.0, 750.0, 700), (120.0, 0.0, 800.0, 700), (-120.0, 0.0, 780.0, 700))
    bot, clock, snap = brain(round_guest(enemies=cluster, cam_yaw=0.0))
    bot.held = lambda p, now: False
    snap["player"].update(equipped=0, nades={0x113: (9, 5)})
    run(bot, snap, clock, 2)
    snap["player"]["equipped"] = 9                                            # the frag in hand ...
    snap["enemies"][0]["pos"] = (0.0, 0.0, 100.0)                             # ... and one at arm's length
    acts = run(bot, snap, clock, 2)
    assert {"tap": "dright"} in acts and bot.stats["nade_aborts"] == 1        # the gun back before anything
    assert all(a.get("hold") != ("zl", "zr") for a in acts)                   # never ZL + ZR with it in hand


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
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 300.0, 700),), cam_yaw=0.0))   # a quick shot's distance
    bot.held = lambda p, now: False
    snap["player"]["equipped"] = 12                                           # the remote bomb in hand
    acts = run(bot, snap, clock, 6)
    assert all(not ({"zl", "zr"} <= set(a.get("hold", ()))) for a in acts)
    assert {"tap": "dright"} in acts and bot.stats["unsafe_trigger_blocks"] >= 1


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


def test_backing_out_of_a_crowd_he_drops_a_bomb_at_his_feet_and_walks_out_of_its_reach():
    three = ((0.0, 0.0, 200.0, 700), (120.0, 0.0, 250.0, 700), (-120.0, 0.0, 280.0, 700))
    bot, clock, snap = brain(round_guest(enemies=three, cam_yaw=0.0))
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


def test_the_cameras_line_fires_only_near_unless_the_zombie_was_hit():
    far = ((0.0, 0.0, 1500.0, 700),)                                      # 15 m along the camera's line, no laser
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0))
    acts = run(bot, snap, clock, 30)
    assert all("zr" not in a.get("hold", ()) for a in acts) and bot.stats["camera_far_holds"] > 0
    bot.seen[snap["enemies"][0]["ptr"]] = clock[0]                           # his health fell to a shot just now
    acts = run(bot, snap, clock, 6)
    assert any("zr" in a.get("hold", ()) for a in acts)
    bot, clock, snap = brain(round_guest(enemies=far, cam_yaw=0.0))
    bot.laser_seen[snap["enemies"][0]["ptr"]] = 0.0                          # the laser reached him a moment ago
    acts = run(bot, snap, clock, 16)
    assert any("zr" in a.get("hold", ()) for a in acts[:16])
    near = ((0.0, 0.0, 700.0, 700),)                                      # 7 m: within CAM_FIRE_R
    bot, clock, snap = brain(round_guest(enemies=near, cam_yaw=0.0))
    acts = run(bot, snap, clock, 30)
    assert any("zr" in a.get("hold", ()) for a in acts)


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


def test_quick_shots_that_never_hurt_a_close_one_leave_him_but_never_one_at_arms_length():
    bot, clock, snap = brain(round_guest(enemies=((0.0, 0.0, 300.0, 700),), cam_yaw=0.0))   # 3 m ahead (a wall between)
    bot.held = lambda p, now: False
    run(bot, snap, clock, int(R.CC_MISS_N * R.CC_QSHOT_GAP_S / 0.05) + 12)
    assert bot.stats["cc_quick_shots"] == R.CC_MISS_N and bot.stats["cc_blocks"] == 1
    assert bot.doing != "crowd"
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


def test_with_nobody_near_it_shoots_a_time_bonus_and_books_it_taken():
    g = round_guest(enemies=(), laser=((0.0, 40.0, 1000.0), (20.0, 145.0, 30.0), 0.86))   # the dot on the bonus
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


def test_no_bonus_shot_with_a_bomb_out():
    g = round_guest(enemies=(), laser=((0.0, 40.0, 1000.0), (20.0, 145.0, 30.0), 0.86))
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))
    bot, clock, snap = brain(g)
    snap["player"].update(equipped=R.BOMB_INDEX, bomb={"count": 5, "out": True}, pos=(0.0, 0.0, -1500.0))
    bot.bomb_at, bot.bomb_since, bot.bomb_phase = (0.0, 0.0), clock[0], "wait"
    acts = run(bot, snap, clock, 12)
    assert bot.doing != "bonus" and all("zr" not in a.get("hold", ()) for a in acts)


def test_no_bonus_with_a_zombie_near_and_one_out_of_sight_is_left_and_missed():
    g = round_guest(enemies=((0.0, 0.0, 400.0, 700),))                               # a zombie 4 m ahead
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))
    bot, clock, snap = brain(g)
    run(bot, snap, clock, 6)
    assert bot.doing != "bonus" and bot.stats["bonus_shots"] == 0
    R._BONUS.update(base=None)                                                         # another guest at the same base
    g = round_guest(enemies=((0.0, 0.0, 3000.0, 700),), laser=((0.0, 60.0, 500.0), (20.0, 145.0, 30.0), 0.86))
    bonus_piece(g, "cSmTimeBonusAct_Wait", (0.0, 0.0, 1000.0))                       # a wall at 5 m: the dot short
    bot, clock, snap = brain(g)
    acts = run(bot, snap, clock, int(R.BONUS_TRY_S / 0.05) + 4)
    assert all("zr" not in a.get("hold", ()) for a in acts) and bot.stats["bonus_skips"] == 1
    assert bot.doing == "walk"                                                         # left: on to the zombie
    snap["mercenaries_phase"] = R.PHASE_OVER
    run(bot, snap, clock, 1)
    assert bot.stats["bonuses_missed"] == 1 and bot.stats["bonus_log"][-1]["missed"] == 1


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
    assert run(bot, snap, clock, 1)[0] != {"tap": "r"}                       # dying: RE6 takes none (DYING_TABLETS off)
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
    acts = run(bot, snap, clock, int((R.TABLET_CONFIRM_S + R.TABLET_LOWER_S) / 0.05) + 3)   # the count stays: ignored
    assert bot.stats["tablet_misses"] == 1 and bot.stats["tablets"] == 1
    assert acts.count({"tap": "r"}) == 1 and acts[0] != {"tap": "r"}        # pressed again once the miss is known
    assert bot.stats["tablet_presses"] == 3


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
    g.put(table + mods.LOADOUT_SIZE * 4 + mods.L_WEAPONS, struct.pack("<2H", 0x10E, 30))   # Chris's rifle: another gun
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
    crowd = ((100.0, 0.0, 200.0, 700), (-120.0, 0.0, 200.0, 700), (0.0, 0.0, 900.0, 700))   # two within CC_R
    on = ((100.0, R.CHEST_H, 200.0), (20.0, 145.0, 30.0), 0.86)
    bot, clock, snap = brain(round_guest(enemies=crowd, cam_yaw=math.atan2(100, 200), laser=on))
    bot.held = lambda p, now: False                                          # (the frozen snapshot never moves him)
    acts = run(bot, snap, clock, 30)                                         # 1.5 s
    assert acts[0] == {"hold": ("zl", "zr")} and bot.doing == "crowd"         # the gun down: the quick shot at once
    assert bot.stats["cc_quick_shots"] == 3 and bot.stats["quick_shots"] == 3 # one every CC_QSHOT_GAP_S
    assert all("zl" not in a.get("hold", ()) or a == {"hold": ("zl", "zr")} for a in acts)   # never the gun up
    assert {"hold": ("ldown",)} in acts                                      # stepping back between them
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
    bot, clock, snap = brain(round_guest(enemies=((300.0, 0.0, 0.0, 700),), cam_yaw=0.0))   # 3 m off to the right
    act = run(bot, snap, clock, 1)[0]
    assert bot.doing == "crowd" and act["hold"] == bot._turn(R.heading(300.0, 0.0))   # the camera to him
    assert bot.stats["cc_quick_shots"] == 0 and bot.stats["cc_kicks"] == 0


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
