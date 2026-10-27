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


def round_guest(phase=R.PHASE_PLAYING, hp=1000, timer=97.5, enemies=((300.0, 0.0, 500.0, 800),), player=True,
                units=(), cursors=None):
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


def test_snapshot_reads_the_measured_fields():
    snap = R.snapshot(round_guest())
    p = snap["player"]
    assert p["hp"] == 1000 and p["hp_max"] == 1000 and p["pos"] == (0.0, 0.0, 0.0) and p["rot"] == 0.0
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


# --- the brain -------------------------------------------------------------------------------------------------------

def snap_with(enemy, hp=1000, rot=0.0):
    return {"player": {"pos": (0.0, 0.0, 0.0), "rot": rot, "hp": hp, "hp_max": 1000},
            "enemies": [{"pos": enemy, "hp": 800, "hp_max": 800}] if enemy else []}


def test_bot_faces_aims_and_fires_at_the_nearest():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    assert b.tick(snap_with((500.0, 0.0, 0.0)))["hold"] == ("rleft",)       # +x is heading +90: rleft raises it
    assert b.tick(snap_with((-500.0, 0.0, 0.0)))["hold"] == ("rright",)
    first = b.tick(snap_with((0.0, 0.0, 600.0)))["hold"]
    second = b.tick(snap_with((0.0, 0.0, 600.0)))["hold"]
    assert {first, second} == {("zl", "zr"), ("zl",)}                        # ZR goes down every other tick
    assert b.stats["shots"] == 1
    assert b.tick(snap_with((0.0, 0.0, 5000.0)))["hold"] == ("lup",)        # nobody in range: walk to him
    assert b.tick(snap_with(None))["hold"] == ()


def test_bot_breaks_free_and_answers_continue_no():
    clock = [0.0]
    b = R.Bot(stats={}, clock=lambda: clock[0])
    b.tick(snap_with((0.0, 0.0, 60.0), hp=900))
    clock[0] = 0.2
    act = b.tick(snap_with((0.0, 0.0, 60.0), hp=800))                         # health falling, one at arm's length
    assert act["hold"] in (("lleft",), ("lright",)) and b.stats["wiggles"] == 1
    clock[0] = 1.0
    assert b.tick(snap_with((0.0, 0.0, 60.0), hp=0)) == {"hold": ()}          # the death animation
    clock[0] = 1.0 + R.DEAD_WAIT_S
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
