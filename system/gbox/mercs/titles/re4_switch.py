"""Title: Resident Evil 4 (Nintendo Switch: title 010099A00BC1E000, update 1.0.2) - The Mercenaries mode.

"RE4" here is ALWAYS this Switch edition (never the GameCube G4BE08 one). RE4 Switch is a port of the 2007 HD /
PS2 / PC build (biohazard 4), NOT MT Framework, so its RAM layout is the RE4 engine's (pG global work area, the
cEm / EmMgr enemy table, the title.cpp task with its TW work area), closer to gbox.re4_merc_bot / gbox.re4_menus
(GameCube) than to re5_switch / re6_switch (MT Framework). What is shared with those Switch drivers is only the
*mechanism*: ARM64, little-endian, ASLR, so every address is main's load base (module_base, pinned by a 64-byte
read-only signature) plus a fixed offset, and reads go through the gbox.adapters SwitchLinuxAdapter (Eden,
single-core, NCE: a guest address is the host address) / CitronLinuxAdapter.

Renders on Eden only on the GB10 (switch_linux_emulator="eden"; Citron is broken there - memory
gbox-switch-render-fix-2026-11-03). The guest RAM layout is the GAME's, so addresses measured on ANY Eden host
apply to the lilspark MercMode rotation.

STATUS 2026-11-04: SCAFFOLD. Every live-measured constant below is None. The plumbing (signature guard, snapshot
shape, menu walk, screen classifier, first-cut combat brain) mirrors re5_switch / re6_switch and re4_gc so that the
live RAM scan only has to fill the constants. Until the signature and the struct anchors are measured, snapshot()
returns the empty round shape, screen() returns "loading"/"unknown", and step() returns None, so the menu loop is
inert and the map's mercs.ready stays false (RE4 is kept out of the rotation).

Known from RE4 itself (gbox.re4_menus / gbox.re4_merc_bot, GameCube), shared with the Switch port:
- 5 characters: Leon, Ada, Krauser, HUNK, Wesker (Select Player, portraits left to right)
- 4 stages: Village, Castle, Base, Waterworld (Select Stage, a 2x2 grid)
- The Mercenaries is a separate mode (title main menu -> THE MERCENARIES -> GAME START -> player -> stage -> round)
- The round is a countdown clock with a combo / score; a character starts with a fixed loadout

LIVE RAM-SCAN PLAN: docs/research/re4-switch-ram.md. The map file (filled by the scan):
profiles/gamedata/010099A00BC1E000-ram.json.
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver

TITLE_ID = "010099A00BC1E000"
MAP_ID = TITLE_ID                       # profiles/gamedata/010099A00BC1E000-ram.json

# ---------------------------------------------------------------------------
# Live-measured constants - ALL PENDING the Eden RAM scan (docs/research/re4-switch-ram.md).
# Fill these, flip the map's mercs.ready to true, and the driver plays. Until then the guards below keep it inert.
# ---------------------------------------------------------------------------
BUILD_ID = None                         # pending: main build id (Eden log / NSO), for the map's title string
SIG_OFF = None                          # pending: offset into main of 64 read-only bytes unique in the module
SIGNATURE = None                        # pending: those 64 bytes (bytes.fromhex(...)); module_base pins the boot by them

# Static manager anchors (offsets from module_base). On the RE4 engine these are the global work area (pG), the
# player pointer, the enemy manager (EmMgr: base / count / stride) and the Mercenaries game struct (clock / combo /
# score / kills). The GameCube build's absolute addresses (gbox.re4_merc_bot: P_GLOBAL, P_PLAYER, EMMGR, MERC) and
# field offsets are the starting hypotheses for the scan; the Switch port's are measured fresh.
S_PGLOBAL = None                        # pending -> pG work area (room, Leon's health)
S_PLAYER = None                         # pending -> Leon's object pointer (slot, or a pG field)
S_EMMGR = None                          # pending -> EmMgr (+0 base, +4 count, +8 stride) of the cEm enemy table
S_MERC = None                           # pending -> the Mercenaries game struct (clock, combo, score, kills, phase)
S_TITLE_TASK = None                     # pending -> the scheduler's title.cpp task (its TW work area holds the menu cursors)

# Field offsets inside pG / player / enemy / merc (pending; GameCube values in the comments as the scan's hypotheses).
PG_ROOM = None                          # pending (GC pG+0x4FA8 u16 room: 0x04RR = a Mercenaries stage)
PG_HP = None                            # pending (GC pG+0x4FB0 s16 Leon's health)
P_POS = None                            # pending (GC player+0x94 3*f32 x,y,z)
P_ROT = None                            # pending (GC player+0xA4 f32 facing)
P_HP = None                             # pending (may live in pG rather than the object)
E_POS = None                            # pending (GC enemy+0x94 3*f32)
E_HP = None                             # pending (GC enemy+0x320 s16 health, +0x322 s16 max)
E_FLAGS = None                          # pending (GC enemy+0x00 alive/active bitfield; a dead slot is skipped)
MERC_TIMER = None                       # pending (GC a dword of frames; seconds = frames / fps)
MERC_FPS = 60.0                         # Switch runs at 60; the clock decrements once a game frame (verify on the scan)
MERC_COMBO = None                       # pending (GC merc+0x28)
MERC_KILLS = None                       # pending
MERC_SCORE = None                       # pending
MERC_PHASE = None                       # pending (0 intro / 1 playing / 3 over, if the port keeps RE5's scheme; else derive)

# Menu work-area (TW) offsets, from gbox.re4_menus (GameCube). The Switch port is expected to keep the title.cpp
# routine state machine; the live scan confirms the offsets and the routine / cursor codes.
TW_ROUTINE = None                       # pending (GC TW+0x00: 5 main menu, 6 extra games, 7 game starting)
TW_SUB = None                           # pending (GC TW+0x01 step: 8 Select Player, 0xC Select Stage)
TW_MENU_CURSOR = None                   # pending (GC TW+0x28 main-menu cursor)
TW_MERC_CURSOR = None                   # pending (GC TW+0x54 The Mercenaries: 0 GAME START / 1 EXIT)
TW_PLAYER_CURSOR = None                 # pending (GC TW+0x55 Select Player: 0..4)
TW_STAGE_CURSOR = None                  # pending (GC TW+0x56 Select Stage: 0..3, a 2x2 grid)

CLOCK_MAX_S = 1200.0                    # the Mercenaries clock never reads more than this (sanity bound, from re4_merc_bot)

MAX_ENEMIES = 512                       # read budget for the EmMgr table (spawn multipliers expand it; re4_merc_bot)
PTR_LO, PTR_HI = 0x1000000, 1 << 40     # a plausible ARM64 guest pointer (as re5_switch.ptr_ok)

# The round shape the engine needs (driver.Driver.snapshot): keep this identical to re5_switch / re6_switch so the
# engine and round_reports read RE4 the same way.
PHASE_INTRO, PHASE_PLAYING, PHASE_OVER = 0, 1, 3

# ---------------------------------------------------------------------------
# Characters, stages, and the per-round targets (the randomizer mirrors re5_switch.StageCycle; wired on the scan).
# ---------------------------------------------------------------------------
CHARACTERS = ("Leon", "Ada", "Krauser", "HUNK", "Wesker")       # Select Player portraits, left to right
STAGES = ("Village", "Castle", "Base", "Waterworld")            # Select Stage, a 2x2 grid
PLAYER_TARGET, STAGE_TARGET = 0, 0                              # Leon, Village: the selects' first entries

# Default controls hypothesis for the first cut (RE4 remaster, Switch pad). The scan confirms them live before the
# brain fires; until then the brain only turns (CONTROLS_READY False), so a scan session never wastes ammo blind.
CONTROLS_READY = False
AIM_BTN, FIRE_BTN, RELOAD_BTN = "zr", "a", "r"   # pending live confirmation (RE4 UHD default: aim held, fire, reload)

DPAD = {"up": "dup", "down": "ddown", "left": "dleft", "right": "dright"}


# ---------------------------------------------------------------------------
# Memory helpers (little-endian ARM64, as re5_switch).
# ---------------------------------------------------------------------------
def _rows(m):
    """The guest's readable rows [(start, end, perms)] in guest addresses (re5_switch._rows)."""
    ad = getattr(m, "adapter", None)
    guest = getattr(ad, "_guest", None)
    if callable(guest):
        try:
            _pid, arena = guest()
        except Exception:                                   # noqa: BLE001 - not booted yet
            return []
        shift = 0 if getattr(ad, "address_mode", "direct") == "direct" else arena.get("base", 0)
        return [(s - shift, e - shift, p) for s, e, p in arena.get("mapped", [])]
    rows = getattr(m, "rows", None)
    return list(rows() if callable(rows) else rows or [])


def module_base(m) -> int | None:
    """main's load address this boot: cached on m, re-checked by one signature read. None until SIGNATURE is measured."""
    if SIGNATURE is None or SIG_OFF is None:
        return None
    base = getattr(m, "module_base", None)
    if isinstance(base, int):
        try:
            if bytes(m.rd(base + SIG_OFF, len(SIGNATURE))) == SIGNATURE:
                return base
        except (ValueError, OSError):
            pass
    for s, e, p in _rows(m):
        if not p.startswith("r") or "w" in p:
            continue
        step = 1 << 24
        for off in range(s, e, step):
            n = min(step + len(SIGNATURE), e - off)
            try:
                chunk = bytes(m.rd(off, n))
            except (ValueError, OSError):
                break
            i = chunk.find(SIGNATURE)
            if i >= 0:
                found = off + i - SIG_OFF
                try:
                    m.module_base = found
                except AttributeError:
                    pass
                return found
    return None


def ptr_ok(p) -> bool:
    return isinstance(p, int) and PTR_LO <= p < PTR_HI


def u32(m, a) -> int:
    return struct.unpack("<I", m.rd(a, 4))[0]


def u64(m, a) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def _anchor(m, base, off) -> int:
    """The pointer a static anchor holds (module_base + off -> a manager pointer). 0 when the anchor is None/unset."""
    if off is None or base is None:
        return 0
    try:
        return u64(m, base + off)
    except (ValueError, OSError, struct.error):
        return 0


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


_EMPTY = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, "kills": None,
          "combo": None, "combo_timer": None, "max_combo": None, "mercenaries_phase": None}


def snapshot(m) -> dict:
    """The round from RAM. SCAFFOLD: returns the empty shape until the anchors below are measured (every read guarded).

    When the constants are filled this reads, like re5_switch.snapshot:
      player  : {ptr, pos (x,y,z cm), rot (facing rad), hp, hp_max}
      enemies : [{slot, ptr, pos, hp, hp_max}]  (the EmMgr cEm table, live slots only)
      merc    : timer (s), combo, kills, score, mercenaries_phase
    """
    snap: dict = dict(_EMPTY)
    base = module_base(m)
    if base is None:
        return snap
    snap["module_base"] = base

    # --- player ---
    if S_PLAYER is not None and None not in (P_POS, P_ROT):
        p = _anchor(m, base, S_PLAYER)
        if ptr_ok(p):
            try:
                pos = struct.unpack("<3f", m.rd(p + P_POS, 12))
                rot = struct.unpack("<f", m.rd(p + P_ROT, 4))[0]
                hp = hp_max = None
                if P_HP is not None:
                    hp, hp_max = struct.unpack("<hh", m.rd(p + P_HP, 4))
                elif None not in (S_PGLOBAL, PG_HP):
                    pg = _anchor(m, base, S_PGLOBAL)
                    hp = struct.unpack("<h", m.rd(pg + PG_HP, 2))[0] if ptr_ok(pg) else None
                if all(math.isfinite(v) for v in pos) and math.isfinite(rot):
                    snap["player"] = {"ptr": p, "pos": pos, "rot": wrap(rot), "hp": hp, "hp_max": hp_max}
            except (ValueError, OSError, struct.error):
                snap["player"] = None

    # --- room (pG), for the screen classifier ---
    if None not in (S_PGLOBAL, PG_ROOM):
        pg = _anchor(m, base, S_PGLOBAL)
        if ptr_ok(pg):
            try:
                snap["room"] = struct.unpack("<H", m.rd(pg + PG_ROOM, 2))[0]
            except (ValueError, OSError, struct.error):
                pass

    # --- enemies (EmMgr table) ---
    if S_EMMGR is not None and None not in (E_POS, E_HP):
        em = _anchor(m, base, S_EMMGR)
        if ptr_ok(em):
            try:
                tbl, n, stride = struct.unpack("<QII", m.rd(em, 16))
            except (ValueError, OSError, struct.error):
                tbl = n = stride = 0
            if ptr_ok(tbl) and 0 < n <= MAX_ENEMIES and 0x100 <= stride < 0x4000:
                try:
                    d = m.rd(tbl, n * stride)
                except (ValueError, OSError):
                    d = b""
                need = max(E_POS + 12, E_HP + 4, (E_FLAGS + 4) if E_FLAGS is not None else 0)
                for k in range(n):
                    o = k * stride
                    if o + need > len(d):
                        break
                    if E_FLAGS is not None:
                        try:
                            if not (struct.unpack_from("<I", d, o + E_FLAGS)[0] & 0x1):
                                continue
                        except struct.error:
                            continue
                    try:
                        pos = struct.unpack_from("<3f", d, o + E_POS)
                        hp, hp_max = struct.unpack_from("<hh", d, o + E_HP)
                    except struct.error:
                        continue
                    if not all(math.isfinite(v) for v in pos):
                        continue
                    snap["enemies"].append({"slot": k, "ptr": tbl + o, "pos": pos, "hp": hp, "hp_max": hp_max})

    # --- Mercenaries counters ---
    if S_MERC is not None:
        mg = _anchor(m, base, S_MERC)
        if ptr_ok(mg):
            try:
                if MERC_TIMER is not None:
                    snap["timer"] = round(u32(m, mg + MERC_TIMER) / MERC_FPS, 2)
                if MERC_COMBO is not None:
                    snap["combo"] = u32(m, mg + MERC_COMBO)
                if MERC_KILLS is not None:
                    snap["kills"] = u32(m, mg + MERC_KILLS)
                if MERC_SCORE is not None:
                    snap["score"] = u32(m, mg + MERC_SCORE)
                if MERC_PHASE is not None:
                    snap["mercenaries_phase"] = struct.unpack("<i", m.rd(mg + MERC_PHASE, 4))[0]
            except (ValueError, OSError, struct.error):
                pass
    return snap


def own_screen(snap: dict) -> str:
    """playing / dead / results / story / loading from the round's own fields (mirrors re4_gc.own_screen, with the
    merc phase when the port exposes one). Conservative: unknown stays "loading" so the walk waits, never blind."""
    p = snap.get("player")
    room, phase = snap.get("room"), snap.get("mercenaries_phase")
    if phase == PHASE_OVER:
        return "results"
    if not p:
        return "loading"
    # A room outside the Mercenaries stage range (0x04RR on the GC build) is the story, which the bot never plays.
    if room is not None and (room >> 8) != 0x04:
        return "story"
    timer = snap.get("timer")
    if timer is not None and not 0 < timer <= CLOCK_MAX_S:
        return "results"
    if p.get("hp") is not None and p["hp"] <= 0:
        return "dead"
    if phase in (None, PHASE_PLAYING):
        return "playing"
    return "loading"


# ---------------------------------------------------------------------------
# Menu walk (title -> main menu -> THE MERCENARIES -> GAME START -> Select Player -> Select Stage -> round).
# SCAFFOLD: title_work() reads the TW cursors once S_TITLE_TASK and the TW_* offsets are measured; until then screen()
# falls back to the round's own fields and step() returns None (the walk is inert).
# ---------------------------------------------------------------------------
BOOT_KEY = "a"                          # at the title / PRESS START, before any menu is readable, nudge forward
STEPS = {"title": "a", "results": "a", "story_starting": None}


def title_work(m, base) -> int | None:
    """-> the title.cpp task's TW work area (its menu cursors). Pending: the scheduler/stack scan (gbox.re4_menus.tw
    does it on the GameCube build by finding the routine table beside TW on the task's saved stack). Returns None
    until S_TITLE_TASK and the scan are ported to the Switch task layout."""
    if S_TITLE_TASK is None or base is None:
        return None
    # TODO(live scan): port gbox.re4_menus.tw's task/stack walk to the Switch task layout, or anchor TW directly if
    # the scan finds a static pointer to it. Leave None until then: the walk stays inert, never pressing blind.
    return None


def screen(m, merc=None) -> dict:
    """Where RE4 is, for the menus loop (gbox.mercs_bot). The round's own fields first (playing/dead/results/story),
    then the TW menu cursors (main_menu / mercs_title / select_player / select_stage) once they are measured."""
    snap = merc if isinstance(merc, dict) else snapshot(m)
    where = own_screen(snap)
    out = {"where": where, "cursor": None, "target": None}
    if where in ("playing", "dead", "results", "story"):
        return out
    base = snap.get("module_base")
    tw = title_work(m, base)
    if tw is None:
        return out  # inert until the TW scan lands; "loading" keeps the walk waiting, never pressing blind
    # --- the measured path (reached once title_work and the TW_* offsets are filled) ---
    try:
        routine = m.rd(tw + TW_ROUTINE, 1)[0] if TW_ROUTINE is not None else None
        sub = m.rd(tw + TW_SUB, 1)[0] if TW_SUB is not None else None
        if routine == 7:                                    # a game is starting
            return out | {"where": "loading"}
        if routine == 6:                                    # extra games: The Mercenaries menu / player / stage selects
            if sub == 0x0C and TW_STAGE_CURSOR is not None:
                return out | {"where": "select_stage", "cursor": m.rd(tw + TW_STAGE_CURSOR, 1)[0],
                              "target": STAGE_TARGET}
            if sub == 0x08 and TW_PLAYER_CURSOR is not None:
                return out | {"where": "select_player", "cursor": m.rd(tw + TW_PLAYER_CURSOR, 1)[0],
                              "target": PLAYER_TARGET}
            if TW_MERC_CURSOR is not None:
                return out | {"where": "mercs_title", "cursor": m.rd(tw + TW_MERC_CURSOR, 1)[0], "target": 0}
        if routine == 5 and TW_MENU_CURSOR is not None:     # main menu (walk to THE MERCENARIES)
            return out | {"where": "main_menu", "cursor": m.rd(tw + TW_MENU_CURSOR, 1)[0], "target": None}
    except (ValueError, OSError, struct.error):
        return out | {"where": "unknown"}
    return out


def step(scr: dict) -> str | None:
    """One pad press toward the next round: a cursor walks to its target (D-pad), then A confirms. Never blind."""
    where = scr.get("where")
    if where == "select_player":
        cur, tgt = scr.get("cursor"), scr.get("target")
        if not isinstance(cur, int):
            return None
        tgt = PLAYER_TARGET if not isinstance(tgt, int) else tgt
        if cur == tgt:
            return "a"
        return DPAD["right"] if (tgt - cur) % len(CHARACTERS) <= len(CHARACTERS) // 2 else DPAD["left"]
    if where == "select_stage":
        cur, tgt = scr.get("cursor"), scr.get("target")
        if not isinstance(cur, int):
            return None
        tgt = STAGE_TARGET if not isinstance(tgt, int) else tgt
        if cur == tgt:
            return "a"
        if (cur ^ tgt) & 2:                                 # different row: up / down
            return DPAD["down"] if tgt & 2 else DPAD["up"]
        return DPAD["right"] if tgt & 1 else DPAD["left"]   # same row, different column
    if where in ("main_menu", "mercs_title"):
        cur, tgt = scr.get("cursor"), scr.get("target")
        if not isinstance(cur, int):
            return None
        if not isinstance(tgt, int):
            return "a"                                      # mercs_title GAME START is entry 0: confirm
        if cur == tgt:
            return "a"
        return DPAD["down"] if cur < tgt else DPAD["up"]
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """The run must end: a story game (the bot never plays RE4's story)."""
    return "story game" if scr.get("where") == "story" else None


def pressed(scr: dict, key: str) -> None:
    """A menu press went in (hook for the per-round randomizer, like re5_switch.pressed). SCAFFOLD: no-op; the live
    cycle is wired once the selects' cursors read."""
    return None


def warm_probe(m) -> dict:
    """gbox.mercs.warm_boot boot observer: a stable screen where the warm pool may pause the boot, read-only. SCAFFOLD:
    not ready until the signature pins the build and the menus read."""
    out = {"ready": False, "screen": "unknown", "title": MAP_ID}
    base = module_base(m)
    if base is None:
        return out
    where = screen(m).get("where", "unknown")
    if where in ("title", "main_menu", "select_player", "select_stage", "mercs_title"):
        return out | {"ready": True, "screen": where, "token": ("re4sw", base, where)}
    return out | {"screen": where}


# ---------------------------------------------------------------------------
# Driver + first-cut combat brain.
# ---------------------------------------------------------------------------
class RE4Switch(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # The Mercenaries on Switch is played solo on P1 here
    round_counters = ("shots", "hits", "turns", "backoffs", "holds", "dying", "escapes")

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.stats: dict | None = None

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        return own_screen(snap)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        self.stats = stats
        return Bot(stats=stats, clock=clock)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "mode": "mercenaries"}


class Bot:
    """One decision per tick from the snapshot. FIRST CUT (mirrors re5 / re6 at a high level): face the nearest living
    Ganado, raise the gun and fire. Deliberately simple - the real re5 / re6 behaviour (line-of-sight gating, no wall
    shots, mines, combo routing) is refined after the first driveable round. Fires only once the controls are
    confirmed live (CONTROLS_READY); until then it only turns, so a scan session never wastes ammo blind."""

    TURN_TOL = 0.12                                      # rad: close enough to fire

    def __init__(self, stats: dict | None = None, clock=time.monotonic):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        for k in ("shots", "hits", "turns", "backoffs", "holds", "dying", "escapes"):
            self.stats.setdefault(k, 0)
        self.target = None

    @staticmethod
    def _nearest(p, enemies):
        px, _, pz = p["pos"]
        live = [(math.hypot(e["pos"][0] - px, e["pos"][2] - pz), e)
                for e in enemies if (e.get("hp") or 0) > 0]
        return min(live, key=lambda t: t[0])[1] if live else None

    def tick(self, snap: dict):
        p = snap.get("player")
        if not p or p.get("pos") is None:
            return {}
        e = self._nearest(p, snap.get("enemies") or [])
        if e is None:
            return {}
        px, _, pz = p["pos"]
        ex, _, ez = e["pos"]
        err = wrap(heading(ex - px, ez - pz) - p.get("rot", 0.0))
        self.target = e.get("ptr")
        if abs(err) > self.TURN_TOL:
            self.stats["turns"] = self.stats.get("turns", 0) + 1
            return {"hold": {DPAD["right"] if err > 0 else DPAD["left"]}}
        if not CONTROLS_READY:
            return {"hold": set()}                           # aligned but controls unconfirmed: hold fire
        self.stats["shots"] = self.stats.get("shots", 0) + 1
        return {"hold": {AIM_BTN, FIRE_BTN}}

    def prompt_ok(self, button, snap, now):
        return False

    def save(self):
        pass


DRIVER = RE4Switch
