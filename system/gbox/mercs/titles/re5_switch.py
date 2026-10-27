"""Title: Resident Evil 5 (Nintendo Switch: title 010018100CD46000, v1.0.0, main build EBFFDB223149A725A93CD9B60979F6AA)
- The Mercenaries United in No Mercy (operator 2026-10-26: "I need RE5 and 6 no mercy being the canonical mercenaries
mode we run for those two titles"), on Citron NEO (canonical, multi-core) or Eden (single-core): gbox.adapters'
SwitchLinuxAdapter / CitronLinuxAdapter, NCE, where a guest address is the host address.

The same MT Framework as the PS3 build (gbox/mercs/titles/re5_ps3.py), little-endian with 8-byte pointers. ASLR moves
main every boot, so every chain starts at module_base(m) + an offset. module_base finds main by 64 bytes of its
read-only data (unique in the module). Measured live 2026-10-26 on the Spark (docs/research/re5-switch-ram.md):

    sMain   [base+0x26A1BA8]  the sBioMain object; +0x584E0 -> cGameSys: +0x944 s32 phase (0 intro, 1 playing, 3 over),
                              +0x948 f32 seconds left (counts real time), +0x94C f32 round time (120), +0x96C s32 kills,
                              +0x970 combo on, +0x974 s32 combo, +0x978 s32 max combo, +0x97C f32 combo window,
                              +0x990 s32 score (the results screen agreed: Enemies Routed 9, Max combo 6x, 3,060)
    sPlayer [base+0x1CF1C98]  +0x30 -> the player (uPl00ChrisNormal ...): +0x60 pos (x, y up, z; cm), +0x70 rotation
                              quaternion (heading = 2 atan2(qy, qw), forward = (sin, 0, cos)), +0x8F8 u8 motion (held,
                              reloading, dying: P_MOTION), +0x1EB8 s16 health, +0x1EBA maximum (1000). 0 once the round
                              is over.
    sEnemy  [base+0x1CF04B8]  +0x38 u32 count (40-47 alive in No Mercy), +0x48 -> the enemies (uEm10 / uEm11 Majini,
                              uEm21, uEm62 ...): +0x60 pos, +0x1EB8 s16 health, +0x1EBA maximum (Majini 800 / 700)
    sUnit   [base+0x26A3270]  move lines at +0x18 + 0x30 * line (the line's first unit; each unit's +0x18 is the next).
                              The interface units name the screens: uIdStartUp00 main menu (cursor +0x74), 01 PLAY GAME
                              (cursor +0x74; +0x1C4 != 0 its EXTRA CONTENT list, cursor +0x1D8), 29 The Mercenaries
                              United (+0x1C4 = 1 its mode list, cursor +0x1C8: NO MERCY = 3), 21 STAGE SELECT (cursor
                              +0x74), 22 CHARACTER SELECT (cursor +0x1D0), uIdMerce00 the round's HUD, uIdMerceEd00
                              results, uIdGameover00 "You Are Dead - Continue?", uIdNowLoading00, uIdAlert00 (+0x68 the
                              dialog up: 0xC0 "Connect to the Leaderboards?", answered B). Line 19 (effects) holds the
                              uLaserSight: +0x280 the muzzle, +0x60 the dot, while the gun is up (zero when it is down).
An object's class: its vtable's slot 5 (getDTI) returns the MtDTI, whose +8 is the class name.

Controls (Type D, from the game's own Controller Settings): left stick moves, right stick turns (rleft = larger
heading, about 160 deg/s; while aiming it moves the aim, 36-42 deg/s, rup = up), ZL aims, ZL + ZR fires, L + ZR swings
the knife, ZL + B reloads, left stick back + B the quick turn (180 deg in 0.3 s), X inventory, R map.
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
P_MOTION = 0x8F8                         # u8 motion (also at +0x2550), live 2026-10-26 (rounds v2c / v2d): 0 standing,
                                         # 1 walking, 7 backing up, 9 / 10 turning, 22 the gun coming up, 26 aimed, 29 a
                                         # shot, 32 reloading, 107 grabbed then 106 held (a Majini holds him for another's
                                         # swing; his health does not fall), 113 / 100 / 114 strangled (it drains), 104 let
                                         # go, 40 / 47 / 51 dying (health 1), 8 dead
MOTION_HELD, MOTION_RELOAD = frozenset({100, 106, 107, 113, 114}), 32
HELD_R = 25.0                            # a Majini this near is on him: every hold measured 0-8 cm (bodies collide ~50 cm
                                         # apart otherwise), whatever the motion says
DYING_HP = 1                             # the solo dying state keeps exactly 1 HP (the PS3's, verified; seen live here)
E_COUNT, E_ARRAY, E_POS, E_HP = 0x38, 0x48, 0x60, 0x1EB8
MAX_ENEMIES = 64
GET_DTI_SLOT, DTI_NAME = 5, 0x8
UNIT_LINES, LINE_STRIDE, UNIT_NEXT, N_LINES, UI_MAX = 0x18, 0x30, 0x18, 32, 64
ALERT_UP, ALERT_ID = 0x68, 0x6C          # +0x68 != 0 while a dialog is up; +0x6C which one (the PS3's +0x3C ids)
ALERTS = {0x33: "alert_leaderboard",     # "Connect to the Leaderboards and submit your data?": B = No
          0x09: "alert_ok",              # "Save successful." (after Continue? No, and after the results): A = OK
          0x08: "alert_ok"}              # "Load successful.": A = OK
MENU_CURSOR, MENU_SUB, EXTRA_CURSOR, MODE_CURSOR, PLAYER_CURSOR = 0x74, 0x1C4, 0x1D8, 0x1C8, 0x1D0
CONTINUE_CURSOR, CONTINUE_YES, CONTINUE_NO = 0x1CC, 0, 1   # uIdGameover00 "Continue?": +0x1CC 0 Yes / 1 No: Yes
                                         # replays the round at once, No saves and goes to the selects (live 2026-10-26);
                                         # A goes in only with the cursor read on the answer the pace wants
# The pace between rounds (operator 2026-10-26: "match to match to match without these loading screens and waiting";
# re5_ps3.Pace on PS3): No Mercy here is always the same stage and character, so a death answers "Continue? Yes" - the
# same round again at once, with no save, no selects and no loading. The engine publishes MercMode's round boundary at
# the death (its terminal witness "dead") and closes the round's evidence; the bot counts the replay as the next round
# (stats rounds, deaths_continued, round_start_via "dead/retry") and marks its start (_round_started).
REPLAY_ON_DEATH = True
FRESH_ROUND_S = 3.0                      # a clock this close to the round's full time on the first tick alive: it began


def continue_target() -> int:
    """The "Continue?" answer the pace wants: Yes (replay) unless REPLAY_ON_DEATH is off."""
    return CONTINUE_YES if REPLAY_ON_DEATH else CONTINUE_NO
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, EXTRA_MERCENARIES, MODE_NO_MERCY = 0, 1, 0, 3
STAGE_TARGET, PLAYER_TARGET = 0, 0       # Public Assembly, Chris (BSAA): the selects' first entries

BOOT_KEY = "a"                           # a screen RAM can't name out of a round (PRESS ANY BUTTON, a notice)
STEPS = {"results": "plus", "alert_leaderboard": "b", "alert_ok": "a", "alert": "a", "mercs_title": "a"}
MENU_HANDOFF = ("results", "alert_ok", "alert_leaderboard", "alert", "select_stage", "select_player")
CURSORED = {"main_menu": ("dup", "ddown"), "play_game": ("dup", "ddown"), "extra_content": ("dup", "ddown"),
            "dead": ("dleft", "dright"),
            "mercs_mode": ("dup", "ddown"), "select_stage": ("dleft", "dright"), "select_player": ("dleft", "dright")}

# uLaserSight (sUnit move line 19, the effects line; PS3 line 18): while ZL is held, +0x60 is the laser dot, where the
# ray lands (a Majini, a wall, the ground), and +0x280 the laser's origin at the muzzle (PS3 +0x30 / +0x200). Measured
# live 2026-10-26: the stick moves the aim about 36-42 deg/s while aiming (rleft = larger yaw, rup = up).
LASER_LINE, LASER_DOT, LASER_FROM = 19, 0x60, 0x280
LASER_WALK_MAX, LASER_RESCAN_S = 1024, 0.25
_LASER: dict = {}                        # main base -> (the uLaserSight unit, its vtable), checked on every read
_LASER_MISS: dict = {}                   # main base -> when a walk last ended without it
_NOT_LASER: dict = {}                    # main base -> the effects line's other vtables (each named once)

# A Majini's body for the shot (the PS3 combat layer's measures, gbox/mercs/titles/re5_combat.py; the same models): a
# head sphere HEAD_H above his feet, HEAD_R wide; a body capsule from KNEE_H to SHOULDER_H, BODY_R wide; aimed at CHEST_H.
HEAD_H, HEAD_R, KNEE_H, SHOULDER_H, BODY_R, CHEST_H = 160.0, 22.0, 45.0, 145.0, 36.0, 110.0
FIRE_SLACK = 60.0                        # a ray ending this much short of him ends on something in front of him
STEER_RAY_CM = 50.0                      # a shorter ray (the dot at the muzzle) carries too little direction to steer by

# The round brain: face a Majini with the right stick (the body turns fast with the gun down), ready the gun (ZL), close
# the laser's ray onto his chest with the right stick (slow while aiming: it moves the aim, not the body), tap ZR while
# the dot is on a Majini or the ray runs through him; back off one that gets too close, walk to the next one when nobody
# is in range, wiggle free of a grab.
ENGAGE_R, TOO_CLOSE, MAX_DY = 2200.0, 150.0, 300.0
TURN_TOL, AIM_TOL = math.radians(14), math.radians(5)
BODY_AIM_TOL = math.radians(12)          # the body this close to him: the gun comes up (the aim then takes over)
TURN_FINE, FINE = math.radians(24), math.radians(5)   # inside these the stick goes in pulses (a tick on, a tick off)
YAW_DEAD, PITCH_DEAD = math.radians(0.6), math.radians(0.6)
UNAIM_ERR = math.radians(35)             # the ray this far off him: the gun goes down and the body turns (faster)
KEEP_TARGET = 1.5                        # the current Majini is kept unless another costs this much less ...
THREAT_R = 250.0                         # ... or another is this near (he grabs next): that one
READY_S = 0.15                           # ZL down this long before the laser is believed (the last aim's ray clears)
LASER_WAIT_S = 0.6                       # ZL down this long without the laser coming up (a stagger, a grab): ZL again
RAY_STALE_S = 1.0                        # the ray unchanged this long with the gun up: not aiming: ZL again
BACKOFF_S, BACKOFF_GAP_S = 0.5, 1.5      # one too close in front with the gun down: back off this long, then fight
BACKOFF_CONE = math.radians(60)          # ... only from one in front (backing up walks into one behind)
QUICK_ERR, QUICK_GAP_S, QUICK_SETTLE_S = math.radians(120), 1.5, 0.3   # him behind, the gun down: the quick turn
                                         # (left stick back, then B: 180 deg in 0.3 s, measured; the stick takes ~1.1 s)
HIT_S = 0.4                              # a Majini's health falls within this of the shot that hit him
GRAB_R, GRAB_S = 120.0, 0.6
STUCK_S, BREAK_S = 0.4, 1.2              # the sticks pressed this long and he neither turns nor moves: held (a Majini holds
                                         # him for another's swing; his health does not fall): break free this long
COMMIT_S = 1.0                           # a new target is kept this long (a crowd all round does not ping-pong the turn)
WIGGLE = (("lleft",), ("lright",))       # "Break free": the left stick shaken (the prompt's icon)
MASH = (("a",), ())                      # dying: "Resuscitate", A mashed (the prompt's icon)
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


def laser_unit(m, base: int, now: float | None = None) -> int | None:
    """The uLaserSight unit in sUnit's effects line: found once (by class, each other vtable named only once, since
    the line holds every muzzle flash, spark and blood unit), checked by its vtable on every read, looked for again
    when gone (at most every LASER_RESCAN_S)."""
    hit = _LASER.get(base)
    if hit is not None:
        try:
            if u64(m, hit[0]) == hit[1]:
                return hit[0]
        except (ValueError, OSError):
            pass
        _LASER.pop(base, None)
    now = time.monotonic() if now is None else now
    if now - _LASER_MISS.get(base, -1e9) < LASER_RESCAN_S:
        return None
    for cache in (_LASER, _LASER_MISS, _NOT_LASER):
        if len(cache) > 16:                                 # a base per boot: keep a few
            cache.clear()
    others = _NOT_LASER.setdefault(base, set())
    try:
        su = u64(m, base + S_UNIT)
        u, n = u64(m, su + UNIT_LINES + LINE_STRIDE * LASER_LINE), 0
        while ptr_ok(u) and n < LASER_WALK_MAX:
            vt = u64(m, u)
            if vt not in others:
                if class_name(m, u) == "uLaserSight":
                    _LASER[base] = (u, vt)
                    _LASER_MISS.pop(base, None)
                    return u
                others.add(vt)
            u, n = u64(m, u + UNIT_NEXT), n + 1
    except (ValueError, OSError):
        pass
    _LASER_MISS[base] = now
    return None


def laser(m, base: int) -> dict | None:
    """The laser sight: {from: the muzzle, at: the dot, up: the gun is up}, None without the unit. Measured live: both
    points read zero with the gun down, come alive ~0.2 s after ZL goes down and zero again ~50 ms after it is let go;
    a ray that hits nothing ends 5000 cm (its range) out."""
    u = laser_unit(m, base)
    if u is None:
        return None
    try:
        at = struct.unpack("<3f", m.rd(u + LASER_DOT, 12))
        frm = struct.unpack("<3f", m.rd(u + LASER_FROM, 12))
    except (ValueError, OSError):
        return None
    up = all(math.isfinite(v) for v in at + frm) and any(frm) and math.dist(at, frm) >= 1.0
    return {"from": frm, "at": at, "up": bool(up)}


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
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max,
                              "motion": m.rd(p + P_MOTION, 1)[0]}
        except (ValueError, OSError):
            snap["player"] = None
        if snap["player"]:
            snap["laser"] = laser(m, base)
            if snap["player"]["hp"] <= 0:                   # dead: "Continue?" and its cursor, once it is up
                over = ui_units(m, base).get("uIdGameover00")
                try:
                    snap["continue_cursor"] = _i32(m, over + CONTINUE_CURSOR) if over else None
                except (ValueError, OSError):
                    snap["continue_cursor"] = None
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
    if "uIdGameover00" in ui and (out["where"] == "dead" or not snap.get("player")):
        try:
            cursor = _i32(m, ui["uIdGameover00"] + CONTINUE_CURSOR)
        except (ValueError, OSError):
            cursor = None
        return out | {"where": "dead", "cursor": cursor, "target": continue_target()}
    if snap.get("player") and out["where"] == "loading" and snap.get("mercenaries_phase") == PHASE_INTRO \
            and "uIdNowLoading00" not in ui:
        return out | {"where": "playing", "intro": True}    # the round is up (its intro, the clock not yet running):
                                                            # the menus are done, and a MercMode prepare parks here
    if snap.get("player") and out["where"] in ("playing", "dead", "loading"):
        return out
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


WARM_SCREENS = {"uIdStartUp00": "main_menu", "uIdStartUp01": "play_game", "uIdStartUp29": "mercs_title",
                "uIdStartUp21": "select_stage", "uIdStartUp22": "select_player"}
WARM_ALERTS = {0x08: "alert_ok"}         # "Load successful.": the boot's first stop after PRESS ANY BUTTON
WARM_RESCAN_S = 2.0                      # main not found yet (still booting): look again this often (a full scan)
TITLE_READY = 0x18                       # uIdTitle00 +0x18: a pointer that appears ~6 s after the unit (live 2026-10-26,
                                         # Citron: the unit at 10.6 s of boot, black screen; the pointer at ~17 s): the
                                         # title's own state past its load, where the warm pool may pause it


def warm_probe(m) -> dict:
    """gbox.mercs.warm_boot's boot observer for RE5 Switch (title_probe): a stable native menu where the warm pool may
    pause the boot, read only (no input, no writes). Main's 64-byte signature pins this build (module_base); the
    screens are sUnit's interface units, each with its unit as the token (a menu that rebuilds is a new token)."""
    out = {"ready": False, "screen": "unknown", "title": MAP_ID}
    now = time.monotonic()
    if getattr(m, "_warm_miss", None) is not None and now - m._warm_miss < WARM_RESCAN_S:
        return out
    base = module_base(m)
    try:
        m._warm_miss = None if base is not None else now
    except AttributeError:
        pass
    if base is None:
        return out
    units = ui_units(m, base)
    if "uIdNowLoading00" in units:
        return out | {"screen": "loading"}
    for name, where in WARM_SCREENS.items():
        if name in units:
            return out | {"ready": True, "screen": where, "token": (name, units[name])}
    alert = units.get("uIdAlert00")
    if alert:
        try:
            up, aid = struct.unpack("<ii", m.rd(alert + ALERT_UP, 8))
        except (ValueError, OSError):
            up, aid = 0, 0
        if up and aid in WARM_ALERTS:
            return out | {"ready": True, "screen": WARM_ALERTS[aid], "token": ("alert", alert, aid)}
    title = units.get("uIdTitle00")
    if title:
        try:
            state = u64(m, title + TITLE_READY)
        except (ValueError, OSError):
            state = 0
        if ptr_ok(state):                                   # PRESS ANY BUTTON's state is up: pause here, press nothing
            return out | {"ready": True, "screen": "title", "token": ("uIdTitle00", title, state)}
        return out | {"screen": "title"}
    return out


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


def ray_error(origin, dot, target) -> tuple[float, float]:
    """(yaw, pitch) radians that turn the ray origin -> dot onto target (+ yaw = a larger heading = rleft, + pitch = up)."""
    ox, oy, oz = origin
    want_yaw, have_yaw = heading(target[0] - ox, target[2] - oz), heading(dot[0] - ox, dot[2] - oz)
    want_pitch = math.atan2(target[1] - oy, max(math.hypot(target[0] - ox, target[2] - oz), 1.0))
    have_pitch = math.atan2(dot[1] - oy, max(math.hypot(dot[0] - ox, dot[2] - oz), 1.0))
    return wrap(want_yaw - have_yaw), want_pitch - have_pitch


def dot_on(dot, foot) -> str | None:
    """Where the laser dot sits on a Majini standing at foot: "head", "body", else None (short of him, past, beside)."""
    dx, dy, dz = dot[0] - foot[0], dot[1] - foot[1], dot[2] - foot[2]
    if math.sqrt(dx * dx + (dy - HEAD_H) ** 2 + dz * dz) <= HEAD_R:
        return "head"
    if math.hypot(dx, dz) <= BODY_R and KNEE_H - 10 <= dy <= SHOULDER_H + 20:
        return "body"
    return None


def through(origin, dot, foot) -> bool:
    """Whether the ray origin -> dot runs to him: it reaches his chest's distance (less FIRE_SLACK) and passes inside his
    head or body on the way, or ends inside his body's angular width of his chest (close up the body is wide)."""
    chest = (foot[0], foot[1] + CHEST_H, foot[2])
    want, have = math.dist(origin, chest), math.dist(origin, dot)
    if want < 1.0 or have < 1.0 or have < want - FIRE_SLACK:
        return False
    d = tuple((dot[k] - origin[k]) / have for k in range(3))
    cos = sum((chest[k] - origin[k]) * d[k] for k in range(3)) / want
    if math.acos(max(-1.0, min(1.0, cos))) <= math.atan2(BODY_R, want):
        return True
    for h in (HEAD_H, CHEST_H, KNEE_H + 30):
        along = sum((foot[k] + (h if k == 1 else 0.0) - origin[k]) * d[k] for k in range(3))
        if 0.0 < along <= have and dot_on(tuple(origin[k] + along * d[k] for k in range(3)), foot) is not None:
            return True
    return False


class Bot:
    """One decision per tick from the snapshot.

    The Majini to fight: near and in front first; a new one is kept COMMIT_S, then while he lives unless another costs
    KEEP_TARGET times less or one comes within THREAT_R. Gun down: the body turns to him (the right stick turns it fast;
    the quick turn, stick back + B, for one behind), ZL once within BODY_AIM_TOL. Gun up: the laser sight's ray (muzzle
    -> dot, RAM) is closed onto his chest with the right stick (slow while aiming; pulsed inside FINE), and ZR is tapped
    while the dot sits on a Majini (that one becomes the target) or the ray runs through him. The body's heading is not
    the gun's aim: the upper body aims inside a cone, and the v1 bot, firing on the heading, hit few of its shots (live
    2026-10-26: 78 % of laser-guided presses hit, 20 % of the rest). The gun not up within LASER_WAIT_S: ZL again; a
    reload waits. One closer than TOO_CLOSE in front with the gun down: back off first.

    Held (the motion byte, a Majini on top of him, or the stick not moving him; the health need not fall) or dying
    (health 1): the left stick shaken with A / B mashed ("Break free", the left stick's prompt). Dead: "Continue?" is
    answered No (right, then A), like the PS3 bot, so the round ends on its results. Without a laser unit the v1 heading
    aim stands in."""

    def __init__(self, stats: dict | None = None, clock=time.monotonic, release=None):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        self.release = release                  # the driver's: the live mods' state put back when the bot stops
        for k in ("shots", "hits", "turns", "quick_turns", "backoffs", "wiggles", "holds", "laserless", "reraise",
                  "restale"):
            self.stats.setdefault(k, 0)
        self.target = None
        self.aim_since = None
        self.fire_down = False
        self.yaw_pulse = self.pitch_pulse = self.turn_pulse = 0
        self.ray_key, self.ray_since = None, 0.0
        self.backoff_until = self.backoff_ready = 0.0
        self.quick, self.quick_at = 0, -1e9      # the quick turn's step (1 stick back, 2 + B, 3 let go), its B press
        self.target_at = -1e9
        self.still, self.move_at, self.break_until, self.in_hold = None, -1e9, -1e9, False
        self.wiggle = 0
        self.hp_seen: list = []
        self.hp_prev: dict = {}
        self.fire_at = None                     # the last tick ZR was held on him
        self._threats: list = []
        self.dead_since, self.dead_taps = None, 0
        self.died, self.continued = False, None   # this round ended in a death / how "Continue?" was answered
        self._round_started = None                # the engine's round marker (a replay starts a new round in one call)

    # --- what to fight -----------------------------------------------------------------------------------------------
    @staticmethod
    def _cost(p, e) -> float:
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        return d * (1.0 + abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) / math.pi)

    def _choose(self, p, live, now):
        best = min(live, key=lambda e: self._cost(p, e))
        cur = next((e for e in live if self.target is not None and e.get("ptr", e.get("slot")) == self.target), None)
        px, _, pz = p["pos"]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        nearest = min(live, key=flat)
        if cur is not None and now - self.target_at < COMMIT_S:
            best = cur
        elif flat(nearest) < THREAT_R and (cur is None or flat(cur) > 1.5 * flat(nearest)):
            best = nearest
        elif cur is not None and self._cost(p, cur) <= KEEP_TARGET * self._cost(p, best):
            best = cur
        if best is not cur:
            self.target_at = now
        self.target = best.get("ptr", best.get("slot"))
        return best

    def held(self, p, now) -> bool:
        """The sticks pressed for STUCK_S while he neither turns nor moves: something holds him."""
        pos, rot = p["pos"], p["rot"]
        moved = self.still is None or math.dist(pos, self.still[1]) > 2.0 or abs(wrap(rot - self.still[2])) > math.radians(1)
        if moved or now - self.move_at > 0.2:               # moving, or not trying to: no hold
            self.still = (now, pos, rot)
            return False
        return now - self.still[0] > STUCK_S

    def grabbed(self, p, near: float, now) -> bool:
        self.hp_seen = [(t, hp) for t, hp in self.hp_seen if now - t <= GRAB_S] + [(now, p.get("hp") or 0)]
        falling = len(self.hp_seen) > 1 and self.hp_seen[-1][1] < self.hp_seen[0][1]
        return bool(falling and near <= GRAB_R)

    def _score_hits(self, snap, now) -> None:
        """A Majini's health falling while the trigger is held, or within HIT_S of letting it go, is a hit."""
        hp = {e.get("ptr", e.get("slot")): e.get("hp") or 0 for e in snap.get("enemies") or ()}
        drops = sum(1 for k, h in hp.items() if h < self.hp_prev.get(k, h))
        self.hp_prev = hp
        if drops and self.fire_at is not None and now - self.fire_at <= HIT_S:
            self.stats["hits"] += drops
        if self.stats.get("trigger_s"):
            self.stats["hits_per_trigger_s"] = round(self.stats["hits"] / self.stats["trigger_s"], 2)

    # --- the sticks and the trigger ------------------------------------------------------------------------------------
    def _turn(self, err: float, tol: float = 0.0) -> tuple:
        """The body (gun down): the right stick, pulsed inside TURN_FINE so it does not swing past him."""
        if abs(err) <= tol:
            return ()
        if abs(err) < TURN_FINE:
            self.turn_pulse ^= 1
            if not self.turn_pulse:
                return ()
        return ("rleft",) if err > 0 else ("rright",)

    def _yaw(self, err: float) -> set:
        if abs(err) <= YAW_DEAD:
            return set()
        if abs(err) < FINE:
            self.yaw_pulse ^= 1
            if not self.yaw_pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _pitch(self, err: float) -> set:
        if abs(err) <= PITCH_DEAD:
            return set()
        if abs(err) < FINE:
            self.pitch_pulse ^= 1
            if not self.pitch_pulse:
                return set()
        return {"rup"} if err > 0 else {"rdown"}

    def _trigger(self, on: bool, now) -> set:
        """ZR held while on him: the game repeats a held trigger at the gun's pace (live: 2.7 shots/s held or tapped
        with the M92F, 25 with the fire-rate mod, which a tapped trigger cannot reach). A pull counts as a shot."""
        if not on:
            self.fire_down = False
            return set()
        if not self.fire_down:
            self.stats["shots"] += 1
        elif self.fire_at is not None:
            self.stats["trigger_s"] = round(self.stats.get("trigger_s", 0.0) + min(now - self.fire_at, 0.2), 2)
            if self.stats["trigger_s"]:
                self.stats["hits_per_trigger_s"] = round(self.stats["hits"] / self.stats["trigger_s"], 2)
        self.fire_down, self.fire_at = True, now
        return {"zr"}

    def _round_start(self, snap, now) -> None:
        """The first tick alive of a round: its marker for the engine; after a death answered Yes, the replay counts as
        the next round (mercs_bot counts only rounds the menus reach)."""
        if self.died:
            self.died = False
            t, start = snap.get("timer"), snap.get("timer_start")
            fresh = isinstance(t, (int, float)) and isinstance(start, (int, float)) and start - t <= FRESH_ROUND_S
            if self.continued == "yes" and fresh:
                self.stats["rounds"] = self.stats.get("rounds", 0) + 1
                self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                self.stats["round_start_via"] = "dead/retry"
                self._round_started = now
                self.target, self.hp_prev, self.hp_seen = None, {}, []
            self.continued = None
        if self._round_started is None:
            self._round_started = now

    def _gun_down(self) -> None:
        self.aim_since, self.fire_down, self.ray_key = None, False, None

    # --- the decision ----------------------------------------------------------------------------------------------
    def tick(self, snap: dict) -> dict:
        now = self.clock()
        p = snap.get("player")
        if not p:
            self._gun_down()
            return {"hold": ()}
        if (p.get("hp") or 0) <= 0:
            self._gun_down()
            self.died = True
            if self.dead_since is None:
                self.dead_since = now
            if now - self.dead_since < DEAD_WAIT_S:
                return {"hold": ()}
            cursor = snap.get("continue_cursor", "unread")
            if cursor == "unread":                           # no cursor in this snapshot (another reader): v1's taps
                self.dead_taps += 1
                return {"tap": "dright" if self.dead_taps % 2 else "a"}
            if cursor is None:                               # "Continue?" not up yet
                return {"hold": ()}
            want = continue_target()
            if cursor == want:                               # A only on the answer the pace wants
                self.continued = "yes" if want == CONTINUE_YES else "no"
                return {"tap": "a"}
            return {"tap": "dleft" if cursor > want else "dright"}
        self.dead_since = None
        self._round_start(snap, now)
        self._score_hits(snap, now)
        if self.quick:                                       # the quick turn: the stick back, + B, let go
            step, self.quick = self.quick, (self.quick + 1) % 4
            if step == 2:
                self.quick_at = now
            return {"hold": ("ldown",) if step == 1 else ("ldown", "b") if step == 2 else ()}
        if now - self.quick_at < QUICK_SETTLE_S:             # it swings round by itself
            return {"hold": ()}
        px, py, pz = p["pos"]
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        near_e = min(live, key=flat, default=None)
        near = flat(near_e) if near_e is not None else math.inf
        motion = p.get("motion")                         # None: no motion byte (the health / stick heuristics)
        held = motion in MOTION_HELD or near < HELD_R or p.get("hp") == DYING_HP
        if held or now < self.break_until or (motion is None and self.grabbed(p, near, now)) or self.held(p, now):
            if held:                                         # held, or dying: break free / recover (RAM says so)
                if not self.in_hold:
                    kind = "dying" if p.get("hp") == DYING_HP else "holds"
                    self.stats[kind] = self.stats.get(kind, 0) + 1
                self.in_hold = True
            elif now >= self.break_until:
                self.stats["holds" if self.still and now - self.still[0] > STUCK_S else "wiggles"] += 1
                self.break_until = now + BREAK_S
            self._gun_down()
            self.still = None
            self.wiggle += 1
            dying = p.get("hp") == DYING_HP and motion not in MOTION_HELD
            pattern = MASH if dying else WIGGLE
            return {"hold": pattern[self.wiggle % len(pattern)]}
        self.in_hold = False
        if motion == MOTION_RELOAD and self.aim_since is not None:
            self.aim_since = now                             # reloading: the gun comes back up by itself
            return {"hold": ("zl",)}
        act = self._decide(p, live, flat, near_e, near, snap, now)
        if set(act.get("hold", ())) & {"rleft", "rright", "lup", "ldown"} and "zl" not in act.get("hold", ()):
            self.move_at = now
        return act

    def _decide(self, p, live, flat, near_e, near, snap, now) -> dict:
        px, py, pz = p["pos"]
        if not live:
            self._gun_down()
            return {"hold": ()}
        tgt = self._choose(p, live, now)
        foot = tgt["pos"]
        dist = flat(tgt)
        body_err = wrap(heading(foot[0] - px, foot[2] - pz) - p["rot"])
        self.stats["target_dist"] = round(dist)
        if dist > ENGAGE_R:                                  # nobody in range: walk to him
            self._gun_down()
            return {"hold": ("lup",) + self._turn(body_err, TURN_TOL)}
        if self.aim_since is None:
            near_err = wrap(heading(near_e["pos"][0] - px, near_e["pos"][2] - pz) - p["rot"])
            if near < TOO_CLOSE and abs(near_err) <= BACKOFF_CONE:   # one in his face: step back first
                if now >= self.backoff_ready:
                    self.backoff_until, self.backoff_ready = now + BACKOFF_S, now + BACKOFF_S + BACKOFF_GAP_S
                    self.stats["backoffs"] += 1
                if now < self.backoff_until:
                    return {"hold": ("ldown",) + self._turn(body_err)}
            if abs(body_err) > QUICK_ERR and now - self.quick_at > QUICK_GAP_S:
                self.stats["quick_turns"] += 1               # him behind: the quick turn
                self.quick = 2
                return {"hold": ("ldown",)}
            if abs(body_err) > BODY_AIM_TOL:                 # turn round first (fast, the gun down)
                self.stats["turns"] += 1
                return {"hold": self._turn(body_err)}
            self.aim_since = now
        lz = snap.get("laser")
        if lz is None:                                       # no laser unit at all: the body's heading stands in
            if now - self.aim_since < READY_S:
                return {"hold": ("zl",)}
            self.stats["laserless"] += 1
            keys = {"zl"} | (self._yaw(body_err) if abs(body_err) > AIM_TOL else self._trigger(True, now))
            return {"hold": tuple(sorted(keys))}
        if not lz.get("up") or now - self.aim_since < READY_S:   # the gun is coming up (or knocked down)
            if now - self.aim_since > LASER_WAIT_S:
                self.stats["reraise"] += 1                   # it did not come up: let ZL go a tick, press it again
                self._gun_down()
                return {"hold": ()}
            return {"hold": ("zl",)}
        ray = (tuple(lz["from"]), tuple(lz["at"]))
        if ray != self.ray_key:
            self.ray_key, self.ray_since = ray, now
        elif now - self.ray_since > RAY_STALE_S:
            self.stats["restale"] += 1                       # a frozen ray: not a live aim
            self._gun_down()
            return {"hold": ()}
        origin, dot = ray
        on_e = next((e for e in live if dot_on(dot, e["pos"])), None)
        if on_e is not None and on_e is not tgt:             # the dot is on another one: he is the target now
            tgt, foot = on_e, on_e["pos"]
            self.target = tgt.get("ptr", tgt.get("slot"))
            dist = flat(tgt)
        chest = (foot[0], foot[1] + CHEST_H, foot[2])
        yaw_err, pitch_err = ray_error(origin, dot, chest)
        if abs(yaw_err) > UNAIM_ERR:                         # the aim is far off him: gun down, turn the body
            self._gun_down()
            return {"hold": self._turn(body_err)}
        where = dot_on(dot, foot)
        on = where is not None or through(origin, dot, foot)
        keys = {"zl"} | self._trigger(on, now)
        if not on and math.dist(origin, dot) >= min(STEER_RAY_CM, 0.5 * math.dist(origin, chest)):
            keys |= self._yaw(yaw_err) | self._pitch(pitch_err)   # steer only off him: a raised fire rate paces the
                                                                  # aim with the shot (re5_switch_mods)
        self.stats["aim"] = (f"d {dist:.0f} yaw {math.degrees(yaw_err):+.1f} pitch {math.degrees(pitch_err):+.1f} "
                             f"dot_dy {dot[1] - foot[1]:+.0f} on {where or ('ray' if on else '-')} "
                             f"keys {','.join(sorted(keys))}")
        return {"hold": tuple(sorted(keys))}

    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self) -> None:
        if self.release is not None:
            try:
                self.release()
            except Exception:                               # noqa: BLE001 - the round is over either way
                pass


class RE5Switch(Driver):
    map_id = MAP_ID

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._timer = (None, 0.0)
        self.stats: dict | None = None

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
                where = "loading"                           # the clock stopped: frozen (the engine calls it lost)
        self._mods(m, snap, where == "playing")
        return where

    def _mods(self, m, snap, playing: bool, stats: dict | None = None) -> None:
        """The session's live mods (re5_switch_mods: fire_rate's time scale during shots, the no-ammo flags'
        read-back) on every snapshot, when the engine runs with the session's adapter and modifications are allowed."""
        ad = getattr(m, "adapter", None)
        if ad is None or getattr(m, "mercs_no_modifications", False):
            return
        from . import re5_switch_mods
        res = re5_switch_mods.maintain(ad, snap, enabled=playing)
        if self.stats is not None:
            self.stats["rapid_fire_active"] = bool(res.get("active"))
            self.stats["mod_writes"] = self.stats.get("mod_writes", 0) + res.get("writes", 0)
            if not res.get("verified", True):
                self.stats["mod_reason"] = res.get("reason", "")

    def menu_handoff(self, m, snap, where) -> bool:
        """The engine hands a finished round back to the menus only when RAM names a native screen. That means the
        results unit, a dialog (Save successful after Continue? No, the Leaderboards prompt) or the selects. Without
        this, a round that ended on "Save successful" read as a lost one (no player for 20 s), and mercs_bot stopped the
        run as hung (live in gBox on Citron, 2026-10-26)."""
        if where != "results":
            return False
        try:
            return screen(m).get("where") in MENU_HANDOFF
        except (ValueError, OSError, struct.error):
            return False

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        self.stats = stats

        def release():                                      # the round's end or the bot stopping: the game's pace back
            self._mods(m, snapshot(m), False)
        return Bot(stats=stats, clock=clock, release=release)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
                "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "no_mercy"}


DRIVER = RE5Switch
