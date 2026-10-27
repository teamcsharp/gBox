"""Title: Resident Evil 5 (Nintendo Switch: title 010018100CD46000, v1.0.0, main build EBFFDB223149A725A93CD9B60979F6AA)
- The Mercenaries United in No Mercy (operator 2026-10-26: "I need RE5 and 6 no mercy being the canonical mercenaries
mode we run for those two titles"), on Eden (gbox.adapters.SwitchLinuxAdapter: single-core, NCE, where a guest address
is the host address).

The same MT Framework as the PS3 build (gbox/mercs/titles/re5_ps3.py), little-endian with 8-byte pointers. ASLR moves
main every boot, so every chain starts at module_base(m) + an offset. module_base finds main by 64 bytes of its
read-only data (unique in the module). Measured live 2026-10-26 on the Spark (docs/research/re5-switch-ram.md):

    sMain   [base+0x26A1BA8]  the sBioMain object; +0x584E0 -> cGameSys: +0x944 s32 phase (0 intro, 1 playing, 3 over),
                              +0x948 f32 seconds left (counts real time), +0x94C f32 round time (120), +0x96C s32 kills,
                              +0x970 combo on, +0x974 s32 combo, +0x978 s32 max combo, +0x97C f32 combo window,
                              +0x990 s32 score (the results screen agreed: Enemies Routed 9, Max combo 6x, 3,060)
    sPlayer [base+0x1CF1C98]  +0x30 -> the player (uPl00ChrisNormal ...): +0x60 pos (x, y up, z; cm), +0x70 rotation
                              quaternion (heading = 2 atan2(qy, qw), forward = (sin, 0, cos)), +0x1EB8 s16 health,
                              +0x1EBA maximum (1000). 0 once the round is over.
    sEnemy  [base+0x1CF04B8]  +0x38 u32 count (40-47 alive in No Mercy), +0x48 -> the enemies (uEm10 / uEm11 Majini,
                              uEm21, uEm62 ...): +0x60 pos, +0x1EB8 s16 health, +0x1EBA maximum (Majini 800 / 700)
    sUnit   [base+0x26A3270]  move lines at +0x18 + 0x30 * line (the line's first unit; each unit's +0x18 is the next).
                              The interface units name the screens: uIdStartUp00 main menu (cursor +0x74), 01 PLAY GAME
                              (cursor +0x74; +0x1C4 != 0 its EXTRA CONTENT list, cursor +0x1D8), 29 The Mercenaries
                              United (+0x1C4 = 1 its mode list, cursor +0x1C8: NO MERCY = 3), 21 STAGE SELECT (cursor
                              +0x74), 22 CHARACTER SELECT (cursor +0x1D0), uIdMerce00 the round's HUD, uIdMerceEd00
                              results, uIdGameover00 "You Are Dead - Continue?", uIdNowLoading00, uIdAlert00 (+0x68 the
                              dialog up: 0xC0 "Connect to the Leaderboards?", answered B).
An object's class: its vtable's slot 5 (getDTI) returns the MtDTI, whose +8 is the class name.

Controls (Type D, from the game's own Controller Settings): left stick moves, right stick turns (rleft = larger
heading, about 160 deg/s), ZL aims, ZL + ZR fires, L + ZR swings the knife, ZL + B reloads, X inventory, R map.
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver

TITLE_ID = "010018100CD46000"
MAP_ID = TITLE_ID                       # profiles/gamedata/010018100CD46000-ram.json
BUILD_ID = "EBFFDB223149A725A93CD9B60979F6AA"
SIG_OFF = 0x1191000                     # 64 read-only bytes of main (part of its RELA table), unique in the module
SIGNATURE = bytes.fromhex("03040000000000003052000000000000e821ce010000000003040000000000001053000000000000"
                          "f021ce010000000003040000000000005054000000000000")
S_MAIN, S_PLAYER, S_ENEMY, S_UNIT = 0x26A1BA8, 0x1CF1C98, 0x1CF04B8, 0x26A3270
MAIN_GAMESYS = 0x584E0
GS_PHASE, GS_TIMER, GS_START, GS_KILLS = 0x944, 0x948, 0x94C, 0x96C
GS_COMBO_ON, GS_COMBO, GS_MAX_COMBO, GS_COMBO_T, GS_SCORE = 0x970, 0x974, 0x978, 0x97C, 0x990
PHASE_INTRO, PHASE_PLAYING, PHASE_OVER = 0, 1, 3
P_FIRST, P_POS, P_ROT, P_HP = 0x30, 0x60, 0x70, 0x1EB8
E_COUNT, E_ARRAY, E_POS, E_HP = 0x38, 0x48, 0x60, 0x1EB8
MAX_ENEMIES = 64
GET_DTI_SLOT, DTI_NAME = 5, 0x8
UNIT_LINES, LINE_STRIDE, UNIT_NEXT, N_LINES, UI_MAX = 0x18, 0x30, 0x18, 32, 64
ALERT_UP, ALERT_ID = 0x68, 0x6C          # +0x68 != 0 while a dialog is up; +0x6C which one (the PS3's +0x3C ids)
ALERTS = {0x33: "alert_leaderboard",     # "Connect to the Leaderboards and submit your data?": B = No
          0x09: "alert_ok",              # "Save successful." (after Continue? No, and after the results): A = OK
          0x08: "alert_ok"}              # "Load successful.": A = OK
MENU_CURSOR, MENU_SUB, EXTRA_CURSOR, MODE_CURSOR, PLAYER_CURSOR = 0x74, 0x1C4, 0x1D8, 0x1C8, 0x1D0
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, EXTRA_MERCENARIES, MODE_NO_MERCY = 0, 1, 0, 3
STAGE_TARGET, PLAYER_TARGET = 0, 0       # Public Assembly, Chris (BSAA): the selects' first entries

BOOT_KEY = "a"                           # a screen RAM can't name out of a round (PRESS ANY BUTTON, a notice)
STEPS = {"results": "plus", "alert_leaderboard": "b", "alert_ok": "a", "alert": "a", "dead": "a", "mercs_title": "a"}
CURSORED = {"main_menu": ("dup", "ddown"), "play_game": ("dup", "ddown"), "extra_content": ("dup", "ddown"),
            "mercs_mode": ("dup", "ddown"), "select_stage": ("dleft", "dright"), "select_player": ("dleft", "dright")}

# The round brain (first cut, 2026-10-26): face the nearest Majini, aim, fire; walk to the next one when nobody is
# in range; wiggle the left stick when one holds the player.
ENGAGE_R, TOO_CLOSE, MAX_DY = 1600.0, 90.0, 300.0
TURN_TOL, AIM_TOL = math.radians(14), math.radians(5)
GRAB_R, GRAB_S = 120.0, 0.6
DEAD_WAIT_S = 2.5                        # "You Are Dead - Continue?" comes up after the death animation
HANG_S = 6.0


def _rows(m):
    """The guest's readable rows [(start, end, perms)] in guest addresses, when the session can say (Eden: the
    adapter's HostMemory arena; direct addressing under NCE)."""
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
    """main's load address this boot: cached on m and checked again (one 64-byte read) on every call."""
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


def u64(m, a) -> int:
    return struct.unpack("<Q", m.rd(a, 8))[0]


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x1000000 <= p < (1 << 40)


def class_name(m, obj) -> str | None:
    """An MtObject's class from its vtable's getDTI (adrp x0 / add x0 or ldr x0 through the GOT / ret)."""
    try:
        f = u64(m, u64(m, obj) + 8 * GET_DTI_SLOT)
        w0, w1, w2 = struct.unpack("<III", m.rd(f, 12))
        if (w0 & 0x9F00001F) != 0x90000000 or w2 != 0xD65F03C0:
            return None
        imm = ((w0 >> 29) & 3) | (((w0 >> 5) & 0x7FFFF) << 2)
        if imm & (1 << 20):
            imm -= 1 << 21
        page = (f & ~0xFFF) + (imm << 12)
        if (w1 & 0xFFC003FF) == 0x91000000:
            dti = page + ((w1 >> 10) & 0xFFF)
        elif (w1 & 0xFFC003FF) == 0xF9400000:
            dti = u64(m, page + (((w1 >> 10) & 0xFFF) << 3))
        else:
            return None
        raw = bytes(m.rd(u64(m, dti + DTI_NAME), 40)).split(b"\0")[0]
        name = raw.decode("ascii")
        return name if name.isidentifier() else None
    except (ValueError, OSError, struct.error, UnicodeDecodeError):
        return None


def heading_of(q) -> float:
    return wrap(2.0 * math.atan2(q[1], q[3]))


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def game_sys(m, base: int) -> int:
    main = u64(m, base + S_MAIN)
    return u64(m, main + MAIN_GAMESYS) if ptr_ok(main) else 0


def snapshot(m) -> dict:
    """The round from RAM: the player, the live enemies and the Mercenaries counters (None where a pointer is not)."""
    snap: dict = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, "kills": None,
                  "combo": None, "combo_timer": None, "max_combo": None, "mercenaries_phase": None}
    base = module_base(m)
    if base is None:
        return snap
    snap["module_base"] = base
    sp = u64(m, base + S_PLAYER)
    p = u64(m, sp + P_FIRST) if ptr_ok(sp) else 0
    if ptr_ok(p):
        try:
            pos = struct.unpack("<3f", m.rd(p + P_POS, 12))
            rot = struct.unpack("<4f", m.rd(p + P_ROT, 16))
            hp, hp_max = struct.unpack("<hh", m.rd(p + P_HP, 4))
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max}
        except (ValueError, OSError):
            snap["player"] = None
    se = u64(m, base + S_ENEMY)
    if ptr_ok(se):
        n, arr = struct.unpack("<I", m.rd(se + E_COUNT, 4))[0], u64(m, se + E_ARRAY)
        if ptr_ok(arr) and 0 < n <= MAX_ENEMIES:
            for slot, e in enumerate(struct.unpack(f"<{n}Q", m.rd(arr, 8 * n))):
                if not ptr_ok(e):
                    continue
                try:
                    pos = struct.unpack("<3f", m.rd(e + E_POS, 12))
                    hp, hp_max = struct.unpack("<hh", m.rd(e + E_HP, 4))
                except (ValueError, OSError):
                    continue
                snap["enemies"].append({"slot": slot, "ptr": e, "pos": pos, "hp": hp, "hp_max": hp_max})
    gs = game_sys(m, base)
    if ptr_ok(gs):
        raw = m.rd(gs + GS_PHASE, GS_SCORE + 4 - GS_PHASE)
        at = lambda off, fmt: struct.unpack_from(fmt, raw, off - GS_PHASE)[0]
        snap.update(mercenaries_phase=at(GS_PHASE, "<i"), timer=round(at(GS_TIMER, "<f"), 2),
                    timer_start=at(GS_START, "<f"), kills=at(GS_KILLS, "<i"), combo=at(GS_COMBO, "<i"),
                    combo_timer=round(at(GS_COMBO_T, "<f"), 2), max_combo=at(GS_MAX_COMBO, "<i"),
                    score=at(GS_SCORE, "<i"))
    return snap


def own_screen(snap: dict) -> str:
    """playing / dead / results / loading from the round's fields alone. The player object exists only inside a round
    (from its intro, phase 0, to the results): gone with the phase past the intro, the round is over (the results, or
    "Save successful" after Continue? No)."""
    p, phase = snap.get("player"), snap.get("mercenaries_phase")
    if not p:
        return "results" if phase in (PHASE_PLAYING, PHASE_OVER) else "loading"
    if phase == PHASE_OVER:
        return "results"
    if p.get("hp") is not None and p["hp"] <= 0:
        return "dead"
    return "playing" if phase == PHASE_PLAYING else "loading"


def ui_units(m, base: int | None = None) -> dict:
    """The interface units up now (uId* classes): class name -> the first unit of that class."""
    base = module_base(m) if base is None else base
    out: dict = {}
    if base is None:
        return out
    su = u64(m, base + S_UNIT)
    if not ptr_ok(su):
        return out
    for line in range(N_LINES):
        try:
            u = u64(m, su + UNIT_LINES + LINE_STRIDE * line)
        except (ValueError, OSError):
            continue
        n = 0
        while ptr_ok(u) and n < UI_MAX:
            name = class_name(m, u)
            if name and name.startswith("uId") and name not in out:
                out[name] = u
            try:
                u = u64(m, u + UNIT_NEXT)
            except (ValueError, OSError):
                break
            n += 1
    return out


def _i32(m, a):
    return struct.unpack("<i", m.rd(a, 4))[0]


def screen(m, merc=None) -> dict:
    """The deployment's menus interface (gbox/mercs_bot.py): where RE5 is, from RAM. The round's own fields first
    (playing / dead / results), then the interface units: a dialog (alert_leaderboard, alert), title / main_menu /
    play_game / extra_content / mercs_title / mercs_mode / select_stage / select_player (cursor and target), loading."""
    snap = snapshot(m)
    out = {"where": own_screen(snap), "cursor": None, "target": None}
    base = snap.get("module_base")
    if base is None:
        return out | {"where": "unknown"}
    ui = ui_units(m, base)
    out["ui"] = sorted(ui)
    alert = ui.get("uIdAlert00")
    if alert:
        try:
            up, aid = struct.unpack("<ii", m.rd(alert + ALERT_UP, 8))
        except (ValueError, OSError):
            up, aid = 0, 0
        if up and aid:
            return out | {"where": ALERTS.get(aid, "alert"), "alert_id": aid,
                          "confirmation_token": ["alert", alert, aid]}
    if snap.get("player") and out["where"] in ("playing", "dead", "loading"):
        return out
    if "uIdGameover00" in ui:
        return out | {"where": "dead"}
    if "uIdMerceEd00" in ui:
        return out | {"where": "results"}
    if "uIdNowLoading00" in ui:
        return out | {"where": "loading"}
    where, cursor, target = "unknown", None, None
    try:
        if "uIdStartUp22" in ui:
            where, cursor, target = "select_player", _i32(m, ui["uIdStartUp22"] + PLAYER_CURSOR), PLAYER_TARGET
        elif "uIdStartUp21" in ui:
            where, cursor, target = "select_stage", _i32(m, ui["uIdStartUp21"] + MENU_CURSOR), STAGE_TARGET
        elif "uIdStartUp29" in ui:
            u = ui["uIdStartUp29"]
            if _i32(m, u + MENU_SUB) == 1:
                where, cursor, target = "mercs_mode", _i32(m, u + MODE_CURSOR), MODE_NO_MERCY
            else:
                where = "mercs_title"                       # START is the first entry and is where it opens
        elif "uIdStartUp01" in ui:
            u = ui["uIdStartUp01"]
            if _i32(m, u + MENU_SUB):
                where, cursor, target = "extra_content", _i32(m, u + EXTRA_CURSOR), EXTRA_MERCENARIES
            else:
                where, cursor, target = "play_game", _i32(m, u + MENU_CURSOR), PLAY_EXTRA_CONTENT
        elif "uIdStartUp00" in ui:
            where, cursor, target = "main_menu", _i32(m, ui["uIdStartUp00"] + MENU_CURSOR), MAIN_PLAY_GAME
        elif snap.get("mercenaries_phase") == PHASE_OVER and not snap.get("player") and not ui.keys() - {"uIdAlert00"}:
            where = "loading"                               # between the results and the selects
    except (ValueError, OSError):
        where = "unknown"
    return out | {"where": where, "cursor": cursor, "target": target,
                  "confirmation_boundary": where in ("select_player", "mercs_mode", "extra_content")}


def step(scr: dict) -> str | None:
    """One key toward the next round: a cursor walks to its target first (D-pad), then A confirms."""
    where = scr.get("where")
    if where in CURSORED:
        cursor, target = scr.get("cursor"), scr.get("target")
        if not isinstance(cursor, int) or not isinstance(target, int):
            return None
        if cursor == target:
            return "a"
        back, fwd = CURSORED[where]
        return fwd if cursor < target else back
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    return None


def pressed(scr: dict, key: str) -> None:
    return None


class Bot:
    """One decision per tick (first cut): turn to the nearest living Majini with the right stick, aim (ZL) when facing
    him inside ENGAGE_R, fire (ZR, pressed every other tick while aimed and on target), walk toward the nearest one when
    nobody is in range, wiggle the left stick while one holds the player (health falling with one at arm's length).
    Dead: "Continue?" is answered No (right, then A), like the PS3 bot, so the round ends on its results."""

    def __init__(self, stats: dict | None = None, clock=time.monotonic):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        self.fire_phase = False
        self.wiggle = 0
        self.hp_seen: list = []
        self._threats: list = []
        self.dead_since, self.dead_taps = None, 0

    def _target(self, snap):
        p = snap["player"]
        px, py, pz = p["pos"]
        best = None
        for e in snap.get("enemies") or []:
            if (e.get("hp") or 0) <= 0:
                continue
            ex, ey, ez = e["pos"]
            if abs(ey - py) > MAX_DY:
                continue
            d = math.hypot(ex - px, ez - pz)
            if best is None or d < best[0]:
                best = (d, e, heading(ex - px, ez - pz))
        return best

    def grabbed(self, snap, now) -> bool:
        p = snap["player"]
        self.hp_seen = [(t, hp) for t, hp in self.hp_seen if now - t <= GRAB_S] + [(now, p.get("hp") or 0)]
        falling = len(self.hp_seen) > 1 and self.hp_seen[-1][1] < self.hp_seen[0][1]
        tgt = self._target(snap)
        return bool(falling and tgt is not None and tgt[0] <= GRAB_R)

    def tick(self, snap: dict) -> dict:
        now = self.clock()
        p = snap.get("player")
        if not p:
            return {"hold": ()}
        if (p.get("hp") or 0) <= 0:
            if self.dead_since is None:
                self.dead_since = now
            if now - self.dead_since < DEAD_WAIT_S:
                return {"hold": ()}
            self.dead_taps += 1
            return {"tap": "dright" if self.dead_taps % 2 else "a"}
        self.dead_since = None
        if self.grabbed(snap, now):
            self.wiggle += 1
            self.stats["wiggles"] = self.stats.get("wiggles", 0) + 1
            return {"hold": ("lleft",) if self.wiggle % 2 else ("lright",)}
        tgt = self._target(snap)
        if tgt is None:
            self.fire_phase = False
            return {"hold": ()}
        dist, enemy, want = tgt
        err = wrap(want - p["rot"])
        turn = ("rleft",) if err > 0 else ("rright",)
        self.stats["target_dist"] = round(dist)
        if dist > ENGAGE_R:
            self.fire_phase = False
            return {"hold": ("lup",) + (turn if abs(err) > TURN_TOL else ())}
        if abs(err) > TURN_TOL:
            self.fire_phase = False
            return {"hold": turn + (("ldown",) if dist < TOO_CLOSE else ())}
        keys = ["zl"]
        if abs(err) > AIM_TOL:
            keys.append(turn[0])
        else:
            self.fire_phase = not self.fire_phase
            if self.fire_phase:
                keys.append("zr")
                self.stats["shots"] = self.stats.get("shots", 0) + 1
        return {"hold": tuple(keys)}

    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self) -> None:
        return None


class RE5Switch(Driver):
    map_id = MAP_ID

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._timer = (None, 0.0)

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        where = own_screen(snap)
        if where == "playing":
            now, t = self.clock(), snap.get("timer")
            if t != self._timer[0]:
                self._timer = (t, now)
            elif now - self._timer[1] > HANG_S:
                return "loading"                            # the clock stopped: frozen (the engine calls it lost)
        return where

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(stats=stats, clock=clock)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
                "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "no_mercy"}


DRIVER = RE5Switch
