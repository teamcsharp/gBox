"""Title: Resident Evil 6 (Nintendo Switch: title 01002A000CD48000 with its update v131072 = 1.0.2, main build
061D2A06CD700785E987C42CE2D72231) - The Mercenaries No Mercy (operator 2026-10-26: "I need RE5 and 6 no mercy being the
canonical mercenaries mode we run for those two titles"), on Citron NEO (gbox.adapters.CitronLinuxAdapter, the
canonical Switch emulator for RE5 / RE6; NCE, so a guest address is the host address).

A fresh save never reaches the main menu until the Prologue is cleared; gbox.re6_switch_unlock sets the save's own
"Prologue cleared" bit in RAM at the title screen (game_unlocks.session_start on every gBox launch). This module only
presses A at the title once the title's own byte says the main menu is what it opens (uIdTitle00 +0x20A = 1).

Measured live on the Spark (docs/research/re6-switch-ram.md; this driver's own measurements in the same file):

    sGameMan [base+0x28E9B10]  +0x54 extra mode (1 THE MERCENARIES, 2 NO MERCY), +0x3DEC phase (1 playing, 3 time up),
                               +0x3DF0 f32 seconds left (a per-frame copy), +0x3DF8 the last time bonus, +0x408C kills,
                               +0x4090 combo on, +0x4094 combo, +0x4098 max combo, +0x409C f32 combo window, +0x40AC
                               the running combo's bonus, +0x40B0 score, +0x40BC base points (300 a kill)
    sPlayer  [base+0x28EAC10]  +0x30 -> the player (uPl00LeonAsia ...): +0x60 pos (x, y up, z; cm), +0x70 rotation
                               quaternion (heading = 2 atan2(qy, qw)), +0x1368 s16 health, +0x136A maximum
    sEnemy   [base+0x28E9AA8]  +0x40 u32 count, +0x50 -> the enemies (uEm5200 ...): +0x60 pos, +0x1368 / +0x136A health
    sUnit    [base+0x2A60780]  an sBioUnit: move line N at +0x268 + 0x30 * N (its first unit), each unit's +0x20 the
                               next. The interface units (by vtable, below) name the screens; the effects line holds
                               the uLaserSight while the gun is up.
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver

TITLE_ID = "01002A000CD48000"
MAP_ID = TITLE_ID                       # profiles/gamedata/01002A000CD48000-ram.json
BUILD_ID = "061D2A06CD700785E987C42CE2D72231"
SIG_OFF = 0x2151000                     # 64 read-only bytes of main, unique in main (gbox.re6_switch_unlock's signature)
SIGNATURE = bytes.fromhex("f304353f08208038386c3bbd286b6ece8716993eb743ba51a0d80b3e00401c46"
                          "008097436666863facc5273700c0284520bcbe4b017ba13ddb0fc93f48e17a3f")
S_GAMEMAN, S_PLAYER, S_ENEMY, S_UNIT = 0x28E9B10, 0x28EAC10, 0x28E9AA8, 0x2A60780
GM_MODE, GM_PHASE, GM_TIMER, GM_BONUS_S = 0x54, 0x3DEC, 0x3DF0, 0x3DF8
GM_KILLS, GM_COMBO_ON, GM_COMBO, GM_MAX_COMBO, GM_COMBO_T = 0x408C, 0x4090, 0x4094, 0x4098, 0x409C
GM_COMBO_BONUS, GM_SCORE, GM_BASE = 0x40AC, 0x40B0, 0x40BC
MODE_MERCENARIES, MODE_NO_MERCY = 1, 2
PHASE_PLAYING, PHASE_OVER = 1, 3
P_FIRST, P_POS, P_ROT, P_HP = 0x30, 0x60, 0x70, 0x1368
E_COUNT, E_ARRAY, E_POS, E_HP = 0x40, 0x50, 0x60, 0x1368
MAX_ENEMIES = 64
GET_DTI_SLOT, DTI_NAME = 5, 0x8

UNIT_LINES, LINE_STRIDE, UNIT_NEXT, N_LINES = 0x268, 0x30, 0x20, 32
UI_LINES = (0, 1, 18, 19)               # the interface units' lines (title / dialogs, the extras' backdrop, menus / HUD)
UI_MAX = 64
UNITS = {                               # interface units by vtable (main + offset), from their getDTI (slot 5)
    0x269B390: "uIdTitle00", 0x2698958: "uIdStartUp00", 0x26988B0: "uIdStartUp01", 0x2698808: "uIdStartUp02",
    0x269A080: "uIdStartUp30", 0x2699F30: "uIdStartUp31", 0x2699E88: "uIdStartUp32", 0x2685650: "uIdMerceUI",
    0x2683608: "uIdGameover00", 0x2683530: "uIdCountDown", 0x2686750: "uIdResult30", 0x2686898: "uIdResultBg",
    0x2681440: "uIdAlert00", 0x2685A68: "uIdNowLoading00", 0x2685990: "uIdNowLoading01", 0x2686968: "uIdSave00",
    0x2686A38: "uIdSaving00", 0x2686EF8: "uIdSignIn00", 0x2682AB0: "uIdExtra",
}
TITLE_MENU_OPEN = 0x20A                 # uIdTitle00: 1 = A opens the main menu (0 = the Prologue: never pressed then)
ALERT_ID, ALERT_UP = 0x1C8, 0x1CC       # uIdAlert00: +0x1CC = 1 while a dialog is up, +0x1C8 which one
ALERTS = {0x41: "alert_leaderboard",    # "Connect to the Leaderboards and submit your data?": B = No
          0x09: "alert_ok",             # "Save successful."
          0x08: "alert_ok",             # "Load successful."
          0x0F: "alert_ok",             # "This game has an autosave feature ..."
          0x0D: "alert_wait",           # on the load path it clears itself within a second (live 2026-10-27)
          0x02: "alert_ok",             # the first dialog after PRESS ANY BUTTON with no save (gBox's own Citron home,
                                        # live 2026-10-27: the warm prepare stopped there 120 s): A creates the save
          0x0C: "alert_wait"}           # "Now saving." (no button)
# Any other dialog is declined (B): on a fresh save the game asks to open its privacy policy web page, and A there opens a
# browser on the session display (RE5 Switch on Eden ran xdg-open); B never confirms anything.
MENU_CURSOR, PLAYER_CURSOR = 0x50, 0x1CC
EXTRA_COUNT, EXTRA_MODES = 0x54, 0x1C4  # uIdStartUp02: how many modes, their ids (0 Agent Hunt, 1 Mercenaries, 2 No Mercy)
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, MERCS_SOLO = 0, 3, 0
STAGES = ("Urban Chaos", "Steel Beast", "Mining the Depths", "Rail Yard", "High Seas Fortress", "The Catacombs",
          "Requiem for War", "Liquid Fire", "Rooftop Mission", "Creature Workshop")
CHARACTERS = ("Leon", "Chris", "Jake", "Agent")
STAGE_TARGET, PLAYER_TARGET = 0, 1      # Urban Chaos, Chris: his assault rifle is automatic (ZR held fires 9.6 rounds
                                        # a second; with infinite ammo it never stops: "rain fire", operator 2026-10-27)

CONTINUE_CURSOR, CONTINUE_YES, CONTINUE_NO, CONTINUE_MENU = 0x50, 0, 1, 0x248   # uIdGameover00 "YOU ARE DEAD -
                                        # CONTINUE? YES / NO": +0x50 the cursor (0 YES, 1 NO), +0x248 -> its YES / NO
                                        # menu once it takes input (~4 s after the death). YES replays the same round at
                                        # once (~13 s to the next round's first frame); NO goes through "Now saving",
                                        # "Save successful", the stage and character selects (live 2026-10-26)
# The pace between rounds (operator 2026-10-26: rounds back to back; gbox.mercs.titles.re5_switch does the same): No Mercy
# here is always the same stage and character, so a death answers YES - the same round again at once. The engine
# publishes MercMode's round boundary at the death (its terminal witness "dead") and closes that round's evidence; the
# bot counts the replay as the next round (stats rounds, deaths_continued, round_start_via "dead/retry") and marks its
# start (_round_started) on its first tick alive with a full clock. REPLAY_ON_DEATH False answers NO instead.
REPLAY_ON_DEATH = True
ROUND_TIME_S, FRESH_ROUND_S = 120.0, 3.0   # No Mercy's clock; within this of it on the first tick alive: a new round


def continue_target() -> int:
    """The "Continue?" answer the pace wants: YES (the replay) unless REPLAY_ON_DEATH is off."""
    return CONTINUE_YES if REPLAY_ON_DEATH else CONTINUE_NO

BOOT_KEY = "a"                          # a screen RAM can't name out of a round (PRESS ANY BUTTON)
STEPS = {"results": "plus", "alert_leaderboard": "b", "alert_ok": "a", "mercs_wrong_mode": "b", "press_any_button": "a",
         "alert": "b"}
MENU_HANDOFF = ("results", "alert_ok", "alert_leaderboard", "alert_wait", "alert", "select_stage", "select_player",
                "dead")
CURSORED = {"main_menu": ("dup", "ddown"), "play_game": ("dup", "ddown"), "extra_content": ("dup", "ddown"),
            "mercs_mode": ("dup", "ddown"), "select_stage": ("dup", "ddown"), "select_player": ("dup", "ddown"),
            "dead": ("dleft", "dright")}
TITLE_STUCK_S = 45.0                    # the title up this long without its main-menu byte: the unlock is off

# The camera (any uCamera: mCameraPos +0x60, mTargetPos +0x80, registered by main+0x124DE70) and the laser sight
# (uLaserSight on the effects line: +0x60 the dot where the aim's ray lands, +0x12C how far the gun is up).
CAM_POS, CAM_TARGET = 0x60, 0x80
CAMERA_CLASSES, CAMERA_LINES, CAM_NEAR = ("uCameraCtrl",), (14, 8), 600.0   # the live one rides ~2 m from him
LASER_LINES, LASER_DOT, LASER_FROM, LASER_UP, LASER_UP_MIN = (22,), 0x60, 0x440, 0x12C, 0.6
MUZZLE_NEAR = 400.0                     # the muzzle rides ~190 cm from his feet while the gun is up
RESCAN_S, WALK_MAX = 0.5, 4096
P_AMMO = 0x507E                         # s16: the gun in hand's rounds (18 -> 15 over three shots of the Wing Shooter)
P_STATE, P_MOTION = 0x6E2, 0x598        # u8 the action's kind, u16 its motion (live 2026-10-26, 20 samples a second): kind
                                        # 0 free, 1 hit (a moment), 2 / 64 / 66 a shot (64 -> 66 -> 2 a quick shot), 3
                                        # knocked down, 8 -> 9 / 25 held by a zombie (its bite: 450 -> 300 health), the
                                        # motion 4012 / 4018 only then
HELD_STATES = frozenset({8, 9, 25})
P_TABLETS = 0x5196                      # s16: the health tablets (8 at the round start; R takes one, live 2026-10-27)
P_WEAPON_ID = 0x507A                    # u8: slot 0's item id, the gun in hand at the start (Leon 0x03, Chris 0x0F)


def _rows(m):
    """The guest's readable rows [(start, end, perms)] in guest addresses (the Citron / Eden adapter's HostMemory arena;
    direct addressing under NCE), or what m says itself."""
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


def _i32(m, a) -> int:
    return struct.unpack("<i", m.rd(a, 4))[0]


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x1000000 <= p < (1 << 40)


def class_name(m, obj) -> str | None:
    """An MtObject's class from its vtable's getDTI (slot 5: adrp x0 / add x0 / ret)."""
    try:
        vt = u64(m, obj)
        if not ptr_ok(vt):
            return None
        f = u64(m, vt + 8 * GET_DTI_SLOT)
        if not ptr_ok(f):
            return None
        w0, w1, w2 = struct.unpack("<III", m.rd(f, 12))
        if (w0 & 0x9F00001F) != 0x90000000 or w2 != 0xD65F03C0 or (w1 & 0xFFC003FF) != 0x91000000:
            return None
        imm = ((w0 >> 29) & 3) | (((w0 >> 5) & 0x7FFFF) << 2)
        if imm & (1 << 20):
            imm -= 1 << 21
        dti = (f & ~0xFFF) + (imm << 12) + ((w1 >> 10) & 0xFFF)
        raw = bytes(m.rd(u64(m, dti + DTI_NAME), 48)).split(b"\0")[0]
        name = raw.decode("ascii")
        return name if name.replace(":", "_").isidentifier() else None
    except (ValueError, OSError, OverflowError, struct.error, UnicodeDecodeError):
        return None


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading_of(q) -> float:
    return wrap(2.0 * math.atan2(q[1], q[3]))


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def ui_units(m, base: int | None = None) -> dict:
    """The interface units up now: class name -> the first unit of that class (the interface lines only, by vtable)."""
    base = module_base(m) if base is None else base
    out: dict = {}
    if base is None:
        return out
    su = u64(m, base + S_UNIT)
    if not ptr_ok(su):
        return out
    for line in UI_LINES:
        try:
            u = u64(m, su + UNIT_LINES + LINE_STRIDE * line)
        except (ValueError, OSError):
            continue
        n = 0
        while ptr_ok(u) and n < UI_MAX:
            try:
                name = UNITS.get(u64(m, u) - base)
                if name and name not in out:
                    out[name] = u
                u = u64(m, u + UNIT_NEXT)
            except (ValueError, OSError):
                break
            n += 1
    return out


def game_man(m, base: int) -> int:
    gm = u64(m, base + S_GAMEMAN)
    return gm if ptr_ok(gm) else 0


def snapshot(m) -> dict:
    """The round from RAM: the player, the live enemies and the Mercenaries counters (None where a pointer is not)."""
    snap: dict = {"player": None, "enemies": [], "timer": None, "score": None, "kills": None, "combo": None,
                  "combo_timer": None, "max_combo": None, "mercenaries_phase": None, "mercenaries_mode": None}
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
            ammo = struct.unpack("<h", m.rd(p + P_AMMO, 2))[0]
            state = m.rd(p + P_STATE, 1)[0]
            motion = struct.unpack("<H", m.rd(p + P_MOTION, 2))[0]
            tablets = struct.unpack("<h", m.rd(p + P_TABLETS, 2))[0]
            weapon_id = m.rd(p + P_WEAPON_ID, 1)[0]
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max, "ammo": ammo,
                              "state": state, "motion": motion, "tablets": tablets, "weapon_id": weapon_id}
            if hp <= 0:                                     # dead: CONTINUE? and its cursor, once it takes input
                over = ui_units(m, base).get("uIdGameover00")
                snap["continue_cursor"] = continue_prompt(m, over)["cursor"] if over else None
        except (ValueError, OSError):
            snap["player"] = None
        if snap["player"]:
            snap["camera"] = camera(m, base, snap["player"]["pos"])
            snap["laser"] = laser(m, base, snap["player"]["pos"])
    se = u64(m, base + S_ENEMY)
    if ptr_ok(se):
        try:
            n, arr = struct.unpack("<I", m.rd(se + E_COUNT, 4))[0], u64(m, se + E_ARRAY)
        except (ValueError, OSError):
            n, arr = 0, 0
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
    gm = game_man(m, base)
    if gm:
        raw = m.rd(gm + GM_PHASE, 0x10)
        tail = m.rd(gm + GM_KILLS, GM_BASE + 4 - GM_KILLS)
        at = lambda off, fmt: struct.unpack_from(fmt, tail, off - GM_KILLS)[0]
        mode = _i32(m, gm + GM_MODE)
        snap.update(mercenaries_phase=struct.unpack_from("<i", raw, 0)[0],
                    timer=round(struct.unpack_from("<f", raw, GM_TIMER - GM_PHASE)[0], 2),
                    bonus_s=struct.unpack_from("<i", raw, GM_BONUS_S - GM_PHASE)[0],
                    kills=at(GM_KILLS, "<i"), combo=at(GM_COMBO, "<i"), max_combo=at(GM_MAX_COMBO, "<i"),
                    combo_timer=round(at(GM_COMBO_T, "<f"), 2), combo_bonus=at(GM_COMBO_BONUS, "<i"),
                    score=at(GM_SCORE, "<i"), base_points=at(GM_BASE, "<i"),
                    mercenaries_mode={MODE_MERCENARIES: "mercenaries", MODE_NO_MERCY: "no_mercy"}.get(mode))
    return snap


class _Title:
    """When the title came up without its main-menu byte (the unlock-on-load is off: the run must say so)."""
    since = None


TITLE = _Title()


def screen(m, merc=None, now: float | None = None) -> dict:
    """The deployment's menus interface (gbox/mercs_bot.py): where RE6 is, from RAM. A dialog first (its id names the
    button), then the round (playing / dead / results from the player, the HUD and the result units), then the menus
    with their cursors and targets: title / main_menu / play_game / extra_content / mercs_mode / select_stage /
    select_player; loading between them."""
    now = time.monotonic() if now is None else now
    out = {"where": "unknown", "cursor": None, "target": None}
    base = module_base(m)
    if base is None:
        return out
    ui = ui_units(m, base)
    out["ui"] = sorted(ui)
    alert = ui.get("uIdAlert00")
    if alert:
        try:
            aid, up = struct.unpack("<ii", m.rd(alert + ALERT_ID, 8))
        except (ValueError, OSError):
            aid, up = 0, 0
        if up and aid:
            return out | {"where": ALERTS.get(aid, "alert"), "alert_id": aid,
                          "confirmation_token": ["alert", alert, aid], "confirmation": aid in (0x08, 0x09, 0x0F)}
    snap = snapshot(m)
    p, phase = snap.get("player"), snap.get("mercenaries_phase")
    if "uIdGameover00" in ui:
        return out | continue_prompt(m, ui["uIdGameover00"])
    if "uIdResult30" in ui:
        return out | {"where": "results"}
    if p and "uIdMerceUI" in ui:
        if (p.get("hp") or 0) <= 0:
            return out | {"where": "dead"}
        return out | {"where": "playing" if phase == PHASE_PLAYING else "loading"}
    if p:
        return out | {"where": "loading"}                   # the stage is up, its HUD not yet
    if {"uIdNowLoading00", "uIdNowLoading01", "uIdSave00", "uIdSaving00"} & ui.keys():
        return out | {"where": "loading"}
    where, cursor, target = "unknown", None, None
    try:
        if "uIdStartUp32" in ui:
            where, cursor, target = "select_player", _i32(m, ui["uIdStartUp32"] + PLAYER_CURSOR), PLAYER_TARGET
        elif "uIdStartUp31" in ui:
            where, cursor, target = "select_stage", _i32(m, ui["uIdStartUp31"] + MENU_CURSOR), STAGE_TARGET
        elif "uIdStartUp30" in ui:
            if snap.get("mercenaries_mode") == "no_mercy":
                where, cursor, target = "mercs_mode", _i32(m, ui["uIdStartUp30"] + MENU_CURSOR), MERCS_SOLO
            else:
                where = "mercs_wrong_mode"                  # THE MERCENARIES (not No Mercy): back to EXTRA CONTENT
        elif "uIdStartUp02" in ui:
            u = ui["uIdStartUp02"]
            n = max(0, min(_i32(m, u + EXTRA_COUNT), 8))
            modes = struct.unpack(f"<{n}i", m.rd(u + EXTRA_MODES, 4 * n)) if n else ()
            target = modes.index(MODE_NO_MERCY) if MODE_NO_MERCY in modes else None
            where, cursor = "extra_content", _i32(m, u + MENU_CURSOR)
        elif "uIdStartUp01" in ui:
            where, cursor, target = "play_game", _i32(m, ui["uIdStartUp01"] + MENU_CURSOR), PLAY_EXTRA_CONTENT
        elif "uIdStartUp00" in ui:
            where, cursor, target = "main_menu", _i32(m, ui["uIdStartUp00"] + MENU_CURSOR), MAIN_PLAY_GAME
        elif "uIdTitle00" in ui:
            ready = m.rd(ui["uIdTitle00"] + TITLE_MENU_OPEN, 1)[0] == 1
            if ready:
                TITLE.since = None
            elif TITLE.since is None:
                TITLE.since = now
            where = "title" if ready else "title_locked"
            out["title_wait_s"] = 0.0 if ready else round(now - TITLE.since, 1)
        elif "uIdSignIn00" in ui:
            where = "press_any_button"                      # the boot's sign-in: PRESS ANY BUTTON (no title unit yet)
        elif phase == PHASE_OVER and not ui.keys() - {"uIdAlert00", "uIdExtra"}:
            where = "loading"                               # between the results and the selects
    except (ValueError, OSError, struct.error):
        where = "unknown"
    if where not in ("title", "title_locked"):
        TITLE.since = None
    return out | {"where": where, "cursor": cursor, "target": target,
                  "confirmation_boundary": where in ("select_player", "mercs_mode", "extra_content")}


def continue_prompt(m, over: int) -> dict:
    """YOU ARE DEAD - CONTINUE?: where "dead", its cursor once the YES / NO menu takes input (None before: no key),
    and the pace's answer as the target (the menus walk and the bot both press A only with the cursor on it)."""
    try:
        ready = ptr_ok(u64(m, over + CONTINUE_MENU))
        cursor = _i32(m, over + CONTINUE_CURSOR) if ready else None
    except (ValueError, OSError):
        cursor = None
    return {"where": "dead", "cursor": cursor if cursor in (0, 1) else None, "target": continue_target()}


def step(scr: dict) -> str | None:
    """One key toward the next round: a cursor walks to its target first (the D-pad), then A confirms. The title takes
    A only when its main-menu byte is set; "Now saving" and loading take nothing."""
    where = scr.get("where")
    if where in CURSORED:
        cursor, target = scr.get("cursor"), scr.get("target")
        if not isinstance(cursor, int) or not isinstance(target, int):
            return None
        if cursor == target:
            return "a"
        back, fwd = CURSORED[where]
        return fwd if cursor < target else back
    if where == "title":
        return "a"
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """The title held without its main-menu byte: A would start the Prologue, so the run stops and says why."""
    if scr.get("where") == "title_locked" and (scr.get("title_wait_s") or 0) > TITLE_STUCK_S:
        return ("the title would start the Prologue (mUnlockFlag bit 0 clear): the RE6 Switch unlock-on-load did not "
                "run (gbox.re6_switch_unlock: the memory_write permission, or the RE6 everything_unlocked switch)")
    return None


def pressed(scr: dict, key: str) -> None:
    return None


STAGE_NAMES = STAGES                    # mercs_bot's prepare receipt names the stage by these
WARM_SCREENS = {"uIdStartUp00": "main_menu", "uIdStartUp01": "play_game", "uIdStartUp02": "extra_content",
                "uIdStartUp30": "mercs_mode", "uIdStartUp31": "select_stage", "uIdStartUp32": "select_player"}
WARM_ALERTS = {0x08: "alert_ok"}        # "Load successful.": the boot's first stop after PRESS ANY BUTTON
WARM_RESCAN_S = 2.0                     # main not found yet (still booting): look again this often (a full scan)


def warm_probe(m) -> dict:
    """gbox.mercs.warm_boot's boot observer for RE6 Switch (title_probe): a stable native menu where the warm pool may
    pause the boot, read only (no input, no writes): the menus, "Load successful", the title once its main-menu byte is
    set (the unlock-on-load ran: A opens the main menu, not the Prologue), or the boot's PRESS ANY BUTTON (uIdSignIn00),
    where a boot without input stays. Each screen's unit is its token."""
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
    if {"uIdNowLoading00", "uIdNowLoading01"} & units.keys():
        return out | {"screen": "loading"}
    for name, where in WARM_SCREENS.items():
        if name in units:
            return out | {"ready": True, "screen": where, "token": (name, units[name])}
    alert = units.get("uIdAlert00")
    if alert:
        try:
            aid, up = struct.unpack("<ii", m.rd(alert + ALERT_ID, 8))
        except (ValueError, OSError):
            aid, up = 0, 0
        if up and aid in WARM_ALERTS:
            return out | {"ready": True, "screen": WARM_ALERTS[aid], "token": ("alert", alert, aid)}
    title = units.get("uIdTitle00")
    if title:
        try:
            open_ = m.rd(title + TITLE_MENU_OPEN, 1)[0] == 1
        except (ValueError, OSError):
            open_ = False
        return out | ({"ready": True, "screen": "title", "token": ("uIdTitle00", title)} if open_
                      else {"screen": "title_locked"})
    if "uIdSignIn00" in units:
        # where a boot without input waits (live 2026-10-27, lilspark's warm prelaunch: uIdSignIn00 with uIdAlert00 down
        # on line 0, nothing else; the first two RE6 prelaunches timed out there after 600 s): the round preparation
        # presses A from here, the save loads ("Load successful") and the unlock-on-load opens the title's main menu
        return out | {"ready": True, "screen": "press_any_button", "token": ("uIdSignIn00", units["uIdSignIn00"])}
    return out


# --- the camera and the laser sight -------------------------------------------------------------------------------------
_FOUND: dict = {}                       # (main base, what) -> (unit, its vtable), checked by the vtable on every read
_MISS: dict = {}                        # (main base, what) -> when a walk last ended without it


def _find_unit(m, base: int, what: str, classes: tuple, lines, pick=None, now: float | None = None) -> int | None:
    """A unit by class on sUnit's lines: found once (each vtable named only once), checked by its vtable afterwards,
    looked for again when gone (at most every RESCAN_S). pick(unit) may refuse a candidate (the wrong camera)."""
    key = (base, what)
    hit = _FOUND.get(key)
    if hit is not None:
        try:
            if u64(m, hit[0]) == hit[1]:
                return hit[0]
        except (ValueError, OSError, OverflowError):
            pass
        _FOUND.pop(key, None)
    now = time.monotonic() if now is None else now
    if now - _MISS.get(key, -1e9) < RESCAN_S:
        return None
    for cache in (_FOUND, _MISS):
        if len(cache) > 32:
            cache.clear()
    try:
        su = u64(m, base + S_UNIT)
        names: dict = {}
        for line in lines:
            u, n = u64(m, su + UNIT_LINES + LINE_STRIDE * line), 0
            while ptr_ok(u) and n < WALK_MAX:
                vt = u64(m, u)
                if vt not in names:
                    names[vt] = class_name(m, u)
                if names[vt] in classes and (pick is None or pick(u)):
                    _FOUND[key] = (u, vt)
                    _MISS.pop(key, None)
                    return u
                u, n = u64(m, u + UNIT_NEXT), n + 1
    except (ValueError, OSError, OverflowError):
        pass
    _MISS[key] = now
    return None


def forget(what: str) -> None:
    """Drop a cached unit ("camera", "laser") for every main base: the next read looks for it again."""
    for key in [k for k in _FOUND if k[1] == what]:
        _FOUND.pop(key, None)


def camera(m, base: int, near=None) -> dict | None:
    """The game camera: {pos, target, yaw, pitch} from uCamera's own properties (mCameraPos +0x60, mTargetPos +0x80,
    registered by main+0x124DE70 for every camera class), on the camera unit nearest the player."""
    def pick(u):
        try:
            c = struct.unpack("<3f", m.rd(u + CAM_POS, 12))
        except (ValueError, OSError):
            return False
        return all(math.isfinite(v) for v in c) and (near is None or math.dist(c, near) < CAM_NEAR)
    u = _find_unit(m, base, "camera", CAMERA_CLASSES, CAMERA_LINES, pick)
    if u is None:
        return None
    try:
        c = struct.unpack("<3f", m.rd(u + CAM_POS, 12))
        t = struct.unpack("<3f", m.rd(u + CAM_TARGET, 12))
    except (ValueError, OSError):
        return None
    if near is not None and not pick(u):                    # the cached unit no longer rides with him (a replay
        _FOUND.pop((base, "camera"), None)                  # freed the round's camera): look again
        u = _find_unit(m, base, "camera", CAMERA_CLASSES, CAMERA_LINES, pick)
        if u is None:
            return None
        try:
            c = struct.unpack("<3f", m.rd(u + CAM_POS, 12))
            t = struct.unpack("<3f", m.rd(u + CAM_TARGET, 12))
        except (ValueError, OSError):
            return None
    if not all(math.isfinite(v) for v in c + t) or math.dist(c, t) < 1.0:
        return None
    flat = max(math.hypot(t[0] - c[0], t[2] - c[2]), 1e-3)
    return {"pos": c, "target": t, "yaw": heading(t[0] - c[0], t[2] - c[2]),
            "pitch": math.atan2(t[1] - c[1], flat), "unit": u}


def laser(m, base: int, near=None) -> dict | None:
    """The laser sight's dot (uLaserSight +0x60: where the aim's ray lands), the muzzle (+0x440) and how far up the
    gun is (+0x12C). With the gun up, a muzzle far from him means another unit sits at the cached address: up = False."""
    u = _find_unit(m, base, "laser", ("uLaserSight",), LASER_LINES)
    if u is None:
        return None
    try:
        at = struct.unpack("<3f", m.rd(u + LASER_DOT, 12))
        frm = struct.unpack("<3f", m.rd(u + LASER_FROM, 12))
        up = struct.unpack("<f", m.rd(u + LASER_UP, 4))[0]
    except (ValueError, OSError):
        return None
    if not all(math.isfinite(v) for v in at + frm):
        return None
    up_now = bool(math.isfinite(up) and up >= LASER_UP_MIN)
    if up_now and near is not None and math.dist(frm, near) > MUZZLE_NEAR:
        _FOUND.pop((base, "laser"), None)                   # not his laser: look again next time
        up_now = False
    return {"at": at, "from": frm, "up": up_now, "alpha": round(up, 3)}


# --- the shot's geometry (a zombie's body; RE6's are human-sized like RE5's Majini) ---------------------------------------
HEAD_H, HEAD_R, KNEE_H, SHOULDER_H, BODY_R, CHEST_H = 160.0, 22.0, 45.0, 145.0, 36.0, 115.0
FIRE_SLACK = 60.0                       # a ray ending this much short of him ends on something in front of him


def ray_error(origin, toward, target) -> tuple[float, float]:
    """(yaw, pitch) radians that turn the ray origin -> toward onto target (+ yaw = a larger heading, + pitch = up)."""
    ox, oy, oz = origin
    want_yaw, have_yaw = heading(target[0] - ox, target[2] - oz), heading(toward[0] - ox, toward[2] - oz)
    want_pitch = math.atan2(target[1] - oy, max(math.hypot(target[0] - ox, target[2] - oz), 1.0))
    have_pitch = math.atan2(toward[1] - oy, max(math.hypot(toward[0] - ox, toward[2] - oz), 1.0))
    return wrap(want_yaw - have_yaw), want_pitch - have_pitch


def dot_on(dot, foot) -> str | None:
    """Where the laser dot sits on a zombie standing at foot: "head", "body", else None."""
    dx, dy, dz = dot[0] - foot[0], dot[1] - foot[1], dot[2] - foot[2]
    if math.sqrt(dx * dx + (dy - HEAD_H) ** 2 + dz * dz) <= HEAD_R:
        return "head"
    if math.hypot(dx, dz) <= BODY_R and KNEE_H - 10 <= dy <= SHOULDER_H + 20:
        return "body"
    return None


def through(origin, dot, foot) -> bool:
    """Whether the ray origin -> dot runs to him: it reaches his chest's distance (less FIRE_SLACK) and passes inside
    his head or body on the way, or ends inside his body's angular width of his chest."""
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


def line_hits(origin, toward, foot, reach: float) -> bool:
    """Whether the line from origin through toward, out to reach, passes inside a zombie standing at foot (his head or
    his body between the knees and the shoulders). The camera's forward line is the aim's when the laser is not read:
    RE6 aims at the middle of the screen."""
    have = math.dist(origin, toward)
    if have < 1.0:
        return False
    d = tuple((toward[k] - origin[k]) / have for k in range(3))
    for h in (HEAD_H, CHEST_H, KNEE_H + 30):
        along = sum((foot[k] + (h if k == 1 else 0.0) - origin[k]) * d[k] for k in range(3))
        if 0.0 < along <= reach and dot_on(tuple(origin[k] + along * d[k] for k in range(3)), foot) is not None:
            return True
    return False


# --- the round brain ----------------------------------------------------------------------------------------------------
# RE6's controls (the game's own Controls screen; measured live 2026-10-26): the right stick turns the camera (rleft = a
# larger yaw, ~174 deg/s with the gun down), the left stick walks along the camera (lup = the camera's yaw), ZL raises
# the gun along the camera (the body turns to it; the right stick then moves the aim, ~70 deg/s yaw, ~95 deg/s pitch;
# the left stick still walks him, RE6 moves while aiming), ZR fires while ZL is held, ZR alone is a physical attack
# (melee), ZL and ZR together a quick shot (the game's own auto-aimed shot), L-stick back + B the quick turn (180 deg,
# the camera follows), Y reloads.
#
# "Raise their weapon and rain fire" (operator 2026-10-27): the gun comes up as soon as a zombie stands in front within
# reach (FRONT_CONE, ENGAGE_R) and stays up while any does; the trigger is down whenever the aim's line runs through any
# zombie, not only the one being steered to; with one close he steps back while he fires instead of lowering the gun;
# the laser not read yet (raising, a replay, a stale unit) hands the aim to the camera's line instead of lowering the
# gun. The gun goes down only to turn to a zombie outside the front with none in it, for a kick at arm's length, a
# tablet, and a hold.
ENGAGE_R, MAX_DY = 1800.0, 300.0
FRONT_CONE = math.radians(60)           # a zombie this close to the aim within ENGAGE_R: the gun comes up and stays up
AIM_CONE = FRONT_CONE                   # (the camera turning with the gun down raises it once he is this close)
UNAIM_ERR = math.radians(100)           # aiming, the target this far off the line with none in front: gun down, turn
TURN_TOL, TURN_FINE = math.radians(8), math.radians(30)   # the camera's turn (gun down): pulsed inside TURN_FINE
YAW_DEAD, PITCH_DEAD = math.radians(0.8), math.radians(1.0)
FINE_YAW, FINE_PITCH = math.radians(6), math.radians(12)  # the aim's stick in pulses inside these (pitch is fast)
QUICK_ERR, QUICK_GAP_S, QUICK_SETTLE_S = math.radians(130), 1.5, 0.45
MELEE_R, MELEE_CONE, MELEE_GAP_S = 140.0, math.radians(40), 0.7
CROWD_R, CROWD_N = 260.0, 2             # this many this near, or one within KEEP_R: he steps back while he fires
KEEP_R = 200.0
QSHOT_R, QSHOT_CONE, QSHOT_GAP_S = 450.0, math.radians(35), 1.5
READY_S, LASER_WAIT_S, RAY_STALE_S = 0.12, 0.7, 1.0
KEEP_TARGET, THREAT_R, COMMIT_S = 1.5, 250.0, 1.0
HIT_S = 0.45                            # a zombie's health falls within this of the shot that hit him
GRAB_R, GRAB_S, STUCK_S, BREAK_S = 120.0, 0.6, 0.5, 1.2
WIGGLE = (("b", "lup"), ("lright", "lup"), ("b", "lright"), ("ldown", "lright"),   # break free: the prompt shows B
          ("b", "ldown"), ("ldown", "lleft"), ("b", "lleft"), ("lleft", "lup"))      # (live), mashed, the stick round
DEAD_WAIT_S = 2.5                       # "YOU ARE DEAD - CONTINUE?" takes input ~4 s after the death
RELOAD_GAP_S = 1.5
TABLET_HP, TABLET_CLEAR_R, TABLET_GAP_S = 0.5, 150.0, 3.0   # a tablet (R) at half health or less, nobody this near
TABLET_LOW_HP = 0.34                    # ... and at a third or less whoever is near (a tablet beats dying)
TABLET_CONFIRM_S, TABLET_RETRY_S = 1.5, 1.0   # a press that took one drops the count within this; one the game ignored
                                        # (live 2026-10-27: 5 of 6 presses in a crowd left the HUD's count at 7) is
                                        # pressed again this soon, and only while he is free (action 0)
AUTO_IDS = frozenset({0x0F})            # automatic guns: ZR held, not tapped (Chris's assault rifle: held 2.5 s, 24 rounds)
REPLAY_LOAD_S = 60.0                    # a death's YES replay loads this long at most before it counts as lost
HANG_S = 6.0
# "Look at the bot" (gbox.mercs.bot_look, as RE5 Switch): stats look (the last trigger pulls and what they did, the
# decisions and why, the idle streak among zombies) and the round counters below, whose per-round amounts the engine
# records (Driver.round_counters: round_<key>):
#   t_<doing>      seconds spent on each decision (DOINGS): fire (the trigger working on a zombie on the line), aim (the
#                  gun up, steering, nobody on the line), raise (the gun coming up), turn / unaim / quick_turn (the body
#                  turning, the gun down), melee, quick_shot, held (breaking a hold), tablet, reload, walk, no_foes, dead
#   trigger_s      seconds with the trigger working (t_fire), the number to raise
#   pulls_hit / pulls_miss  trigger pulls (a streak on one zombie) that took health within HIT_S / that did not
#   first_pull_s/_n  seconds from the gun's raise to its first pull, summed / how many raises fired
#   t_turn_foe_front seconds turning with the gun down while a zombie stood in front within reach (none, by design)
LOOK_FOE_R, LOOK_MOVE_CM_S, LOOK_PUBLISH_S, LOOK_STEP_MAX_S = 400.0, 40.0, 0.25, 0.25
DOINGS = ("fire", "aim", "raise", "turn", "unaim", "quick_turn", "quick_shot", "melee", "held", "tablet", "reload",
          "walk", "no_foes", "dead")
AIM_COUNTERS = ("trigger_s", "pulls_hit", "pulls_miss", "first_pull_n", "first_pull_s", "t_turn_foe_front")
SURVIVAL = ("held", "tablet", "reload")


class Bot:
    """One decision per tick from the snapshot.

    The zombie to fight: near and in front of the camera first (those in front within reach before any other); a new
    one is kept COMMIT_S, then while he lives unless another costs KEEP_TARGET times less or one comes within THREAT_R.
    A zombie in front within reach: the gun up (a kick first for one at arm's length, the game's quick shot for one
    close), the laser's ray (muzzle +0x440 -> dot +0x60, RAM) - or the camera's line while the laser is not read - closed
    onto his chest with the right stick, and the trigger down whenever the line runs through any zombie (tapped for a
    handgun, held for an automatic); one close or a crowd: he steps back while he fires. Nobody in front: the gun down,
    the camera turns to him (the quick turn for one behind), or he walks to him. Held (RAM's action byte, or the stick
    moving nothing): B mashed with the left stick turned round. Hurt: a tablet (R) while he is free, counted once the
    tablet count falls (an ignored press is tried again). Dead: "Continue?" YES by the cursor read in RAM (the same round
    again at once; NO when REPLAY_ON_DEATH is off), the replay counted as the next round."""

    def __init__(self, stats: dict | None = None, clock=time.monotonic):
        from ..bot_look import BotLook
        self.stats = stats if stats is not None else {}
        self.clock = clock
        for k in ("shots", "hits", "quick_shots", "melee", "turns", "quick_turns", "wiggles", "holds", "reloads",
                  "reraise", "restale", "deaths", "tablets", "tablet_presses", "tablet_misses", "backoffs",
                  "pulls_hit", "pulls_miss", "first_pull_n"):
            self.stats.setdefault(k, 0)
        for k in ("trigger_s", "first_pull_s"):
            self.stats.setdefault(k, 0.0)
        self.target, self.target_at = None, -1e9
        self.aim_since = None
        self.reraised = False                     # this raise already looked for the laser unit again
        self.fire_down = False
        self.yaw_pulse = self.pitch_pulse = self.turn_pulse = 0
        self.ray_key, self.ray_since = None, 0.0
        self.quick, self.quick_at = 0, -1e9
        self.melee_at = self.qshot_at = self.reload_at = self.tablet_at = -1e9
        self.tablet_wait, self.tablet_missed = None, False   # (the count, when) after an R press, until it falls
        self.keeping_off = False
        self.qshot_release = False
        self.still, self.move_at, self.break_until, self.in_hold = None, -1e9, -1e9, False
        self.wiggle = 0
        self.hp_seen: list = []
        self.hp_prev: dict = {}
        self.pending: list = []
        self._threats: list = []
        self.dead_since, self.dead_taps = None, 0
        self.died, self.continued = False, None   # this round ended in a death / how "Continue?" was answered
        self._round_started = None                # the engine's round marker (a replay starts a new round in one call)
        # the look
        self.look = BotLook()
        self.doing, self.why = "none", ""
        self._ran = ("none", False)               # the last decision and whether a zombie stood in front while it ran
        self._acc = {k: float(self.stats.get(k) or 0) for k in tuple("t_" + d for d in DOINGS) + ("t_turn_foe_front",
                                                                                                   "trigger_s")}
        self._tick_t = None
        self._look_at = None
        self._look_pub = (-1, -1e9)
        self._pull = None                         # the trigger pull under way: {target, start, entry}
        self._pulls: list = []                    # pulls ended, waiting out HIT_S: [{target, end, hit, entry}]
        self._dropped: set = set()                # the zombies whose health fell this tick
        self._raise_t = None                      # when the gun went up for the pull to come (first_pull_s)
        self._aimctx: dict = {}

    def _round_start(self, snap, now) -> None:
        """The first tick alive of a round: its marker for the engine; after a death answered YES, the replay counts as
        the next round (mercs_bot counts only the rounds its menus reach)."""
        if self.died:
            self.died = False
            t = snap.get("timer")
            fresh = isinstance(t, (int, float)) and ROUND_TIME_S - t <= FRESH_ROUND_S
            if self.continued == "yes" and fresh:
                self.stats["rounds"] = self.stats.get("rounds", 0) + 1
                self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                self.stats["round_start_via"] = "dead/retry"
                self._round_started = now
                self.target, self.hp_prev, self.hp_seen = None, {}, []
                self.tablet_wait, self.tablet_missed = None, False
                self.look.new_round()
            self.continued = None
        if self._round_started is None:
            self._round_started = now

    # --- what to fight -----------------------------------------------------------------------------------------------
    @staticmethod
    def _cost(p, yaw, e) -> float:
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        return d * (1.0 + abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - yaw)) / math.pi)

    def _choose(self, p, yaw, live, now):
        best = min(live, key=lambda e: self._cost(p, yaw, e))
        cur = next((e for e in live if self.target is not None and e.get("ptr", e.get("slot")) == self.target), None)
        px, _, pz = p["pos"]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        nearest = min(live, key=flat)
        if cur is not None and now - self.target_at < COMMIT_S:
            best = cur
        elif flat(nearest) < THREAT_R and (cur is None or flat(cur) > 1.5 * flat(nearest)):
            best = nearest
        elif cur is not None and self._cost(p, yaw, cur) <= KEEP_TARGET * self._cost(p, yaw, best):
            best = cur
        if best is not cur:
            self.target_at = now
        self.target = best.get("ptr", best.get("slot"))
        return best

    def held(self, p, now) -> bool:
        """The left stick pressed for STUCK_S while he neither turns nor moves: something holds him."""
        pos, rot = p["pos"], p["rot"]
        moved = self.still is None or math.dist(pos, self.still[1]) > 2.0 or abs(wrap(rot - self.still[2])) > math.radians(1)
        if moved or now - self.move_at > 0.2:
            self.still = (now, pos, rot)
            return False
        return now - self.still[0] > STUCK_S

    def grabbed(self, p, near: float, now) -> bool:
        self.hp_seen = [(t, hp) for t, hp in self.hp_seen if now - t <= GRAB_S] + [(now, p.get("hp") or 0)]
        falling = len(self.hp_seen) > 1 and self.hp_seen[-1][1] < self.hp_seen[0][1]
        return bool(falling and near <= GRAB_R)

    def _tablet_check(self, p, now) -> None:
        """An R press counts as a tablet once the count falls (stats tablets); none within TABLET_CONFIRM_S is a press
        the game ignored (stats tablet_misses), tried again after TABLET_RETRY_S."""
        if self.tablet_wait is None:
            return
        before, at = self.tablet_wait
        n = p.get("tablets")
        if isinstance(n, int) and isinstance(before, int) and n < before:
            self.stats["tablets"] += 1
            self.tablet_wait, self.tablet_missed = None, False
        elif now - at >= TABLET_CONFIRM_S:
            self.stats["tablet_misses"] += 1
            self.tablet_wait, self.tablet_missed = None, True

    def _score_hits(self, snap, now) -> None:
        """A zombie's health falling within HIT_S of a shot is that shot's hit (accuracy = hits / shots)."""
        hp = {e.get("ptr", e.get("slot")): e.get("hp") or 0 for e in snap.get("enemies") or ()}
        self._dropped = {k for k, h in hp.items() if h < self.hp_prev.get(k, h)}
        drops = len(self._dropped)
        self.hp_prev = hp
        self.pending = [t for t in self.pending if now - t <= HIT_S]
        while drops and self.pending:
            self.pending.pop(0)
            drops -= 1
            self.stats["hits"] += 1
        if self.stats["shots"]:
            self.stats["accuracy"] = round(self.stats["hits"] / self.stats["shots"], 3)

    # --- the sticks and the trigger ------------------------------------------------------------------------------------
    def _turn(self, err: float, tol: float = 0.0) -> tuple:
        """The camera (gun down): the right stick, pulsed inside TURN_FINE so it does not swing past him."""
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
        if abs(err) < FINE_YAW:
            self.yaw_pulse ^= 1
            if not self.yaw_pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _pitch(self, err: float) -> set:
        if abs(err) <= PITCH_DEAD:
            return set()
        if abs(err) < FINE_PITCH:
            self.pitch_pulse = (self.pitch_pulse + 1) % 3      # one tick in three: pitch moves fast
            if self.pitch_pulse:
                return set()
        return {"rup"} if err > 0 else {"rdown"}

    def _trigger(self, on: bool, now, auto: bool = False) -> set:
        """The trigger while a zombie is on the line: held for an automatic gun, tapped (a tick down, a tick up: the
        handgun fires once a press) for any other."""
        if not on:
            self.fire_down = False
            return set()
        self.fire_down = True if auto else not self.fire_down
        if not self.fire_down:
            return set()
        self.stats["shots"] += 1
        self.pending.append(now)
        return {"zr"}

    def _gun_down(self) -> None:
        self.aim_since, self.fire_down, self.ray_key, self.reraised = None, False, None, False

    def _act(self, name: str) -> None:
        """What this tick decided, for the watch panel and the round's audit: stats act and acts (counts)."""
        self.stats["act"] = name
        acts = self.stats.setdefault("acts", {})
        acts[name] = acts.get(name, 0) + 1

    def _go(self, doing: str, act: str, out: dict, why: str = "") -> dict:
        """One decision: its doing (the look's time budget), its act (stats act / acts) and why."""
        self.doing, self.why = doing, why
        self._act(act)
        return out

    # --- the decision ----------------------------------------------------------------------------------------------
    def tick(self, snap: dict) -> dict:
        now = self.clock()
        out = self._tick(snap, now)
        try:
            self._look_tick(snap, now)
        except Exception as exc:                             # noqa: BLE001 - the look never costs the round a tick
            self.stats["look_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return out

    def _tick(self, snap: dict, now: float) -> dict:
        p = snap.get("player")
        if not p:
            self._gun_down()
            return self._go("none", "no_player", {"hold": ()}, "no player (between rounds)")
        if (p.get("hp") or 0) <= 0:
            self._gun_down()
            self.died = True
            if self.dead_since is None:
                self.dead_since = now
                self.stats["deaths"] += 1
            if now - self.dead_since < DEAD_WAIT_S:
                return self._go("dead", "dead_wait", {"hold": ()}, "dead: the Continue? screen comes up")
            cursor = snap.get("continue_cursor")
            if cursor is None:                                   # CONTINUE? not taking input yet
                return self._go("dead", "dead_wait", {"hold": ()}, "dead: Continue? not taking input yet")
            self.dead_taps += 1
            want = continue_target()
            if cursor == want:                                   # A only on the answer the pace wants
                self.continued = "yes" if want == CONTINUE_YES else "no"
                return self._go("dead", "continue", {"tap": "a"}, f"Continue? {self.continued}")
            return self._go("dead", "continue", {"tap": "dleft" if cursor > want else "dright"}, "Continue? cursor")
        self.dead_since = None
        self._round_start(snap, now)
        self._score_hits(snap, now)
        self._tablet_check(p, now)
        if self.qshot_release:                                   # a quick shot: both triggers went down last tick
            self.qshot_release = False
            return self._go("quick_shot", "quick_shot_release", {"hold": ()}, "the quick shot's triggers let go")
        if self.quick:                                           # the quick turn: the stick back, + B, let go
            step, self.quick = self.quick, (self.quick + 1) % 4
            if step == 2:
                self.quick_at = now
            return self._go("quick_turn", "quick_turn",
                            {"hold": ("ldown",) if step == 1 else ("ldown", "b") if step == 2 else ()}, "the quick turn")
        if now - self.quick_at < QUICK_SETTLE_S:
            return self._go("quick_turn", "quick_turn_settle", {"hold": ()}, "the quick turn settles")
        px, py, pz = p["pos"]
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        near_e = min(live, key=flat, default=None)
        near = flat(near_e) if near_e is not None else math.inf
        state = p.get("state")                               # None: no state byte (the health / stick heuristics)
        held = state in HELD_STATES
        if held or now < self.break_until or (state is None and self.grabbed(p, near, now)) or self.held(p, now):
            if held:                                         # RAM says a zombie holds him: shake him off
                if not self.in_hold:
                    self.stats["holds"] += 1
                self.in_hold = True
            elif now >= self.break_until:
                self.stats["holds" if self.still and now - self.still[0] > STUCK_S else "wiggles"] += 1
                self.break_until = now + BREAK_S
            self._gun_down()
            self.still = None
            self.wiggle += 1
            return self._go("held", "break_free", {"hold": WIGGLE[self.wiggle % len(WIGGLE)]},
                            f"held (action {state}): B mashed, the stick round")
        self.in_hold = False
        act = self._decide(p, live, flat, near_e, near, snap, now)
        if set(act.get("hold", ())) & {"lup", "ldown", "lleft", "lright"}:
            self.move_at = now
        return act

    def _decide(self, p, live, flat, near_e, near, snap, now) -> dict:
        px, py, pz = p["pos"]
        if not live:
            self._gun_down()
            return self._go("no_foes", "idle", {"hold": ()}, "no zombie alive within reach")
        cam = snap.get("camera")
        yaw = cam["yaw"] if cam else p["rot"]                    # without the camera: the body's heading stands in
        bearing = lambda e: wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - yaw)
        front = [e for e in live if flat(e) <= ENGAGE_R and abs(bearing(e)) <= FRONT_CONE]
        tgt = self._choose(p, yaw, front or live, now)
        foot, dist, err = tgt["pos"], flat(tgt), bearing(tgt)
        self.stats["target_dist"] = round(dist)
        crowd = sum(1 for e in live if flat(e) < CROWD_R)
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        gap = TABLET_RETRY_S if self.tablet_missed else TABLET_GAP_S
        if (hp_max and hp > 1 and (p.get("tablets") or 0) > 0 and p.get("state") in (0, None)
                and self.tablet_wait is None and now - self.tablet_at >= gap
                and (hp <= TABLET_LOW_HP * hp_max or (hp <= TABLET_HP * hp_max and near > TABLET_CLEAR_R))):
            self._gun_down()                                     # half health, nobody close, free: a tablet (R),
            self.tablet_at = now                                 # the gun down for it (the tap lets ZL go first)
            self.tablet_wait = (p.get("tablets"), now)
            self.stats["tablet_presses"] += 1
            return self._go("tablet", "tablet", {"tap": "r"}, f"health {hp}/{hp_max}: a tablet")
        if self.aim_since is None:
            near_err = bearing(near_e)
            if near < MELEE_R and abs(near_err) <= MELEE_CONE and now - self.melee_at >= MELEE_GAP_S:
                self.melee_at = now                              # one at arm's length in front: a kick
                self.stats["melee"] += 1
                return self._go("melee", "melee", {"tap": "zr"}, f"one at {near:.0f} cm in front: a kick")
            if not front:
                if dist > ENGAGE_R:                              # nobody in reach: walk to him along the camera
                    return self._go("walk", "walk", {"hold": ("lup",) + self._turn(err, TURN_TOL)},
                                    f"the nearest at {dist:.0f} cm: walking")
                if abs(err) > QUICK_ERR and now - self.quick_at > QUICK_GAP_S:
                    self.stats["quick_turns"] += 1               # him behind: the quick turn
                    self.quick = 2
                    return self._go("quick_turn", "quick_turn", {"hold": ("ldown",)},
                                    f"him behind ({math.degrees(err):+.0f} deg): the quick turn")
                self.stats["turns"] += 1                         # the camera turns to him (fast, the gun down)
                return self._go("turn", "turn", {"hold": self._turn(err)},
                                f"nobody in front: turning {math.degrees(err):+.0f} deg to him")
            if dist < QSHOT_R and abs(err) <= QSHOT_CONE and now - self.qshot_at >= QSHOT_GAP_S:
                self.qshot_at = now                              # close in front: the game's own quick shot
                self.stats["quick_shots"] += 1
                self.qshot_release = True
                return self._go("quick_shot", "quick_shot", {"hold": ("zl", "zr")}, f"one at {dist:.0f} cm: quick shot")
            self.aim_since, self._raise_t, self.reraised = now, now, False   # a zombie in front: the gun comes up
        keep_off = crowd >= CROWD_N or near < KEEP_R             # he steps back while he fires
        if keep_off and not self.keeping_off:
            self.stats["backoffs"] += 1
        self.keeping_off = keep_off
        back = ("ldown",) if keep_off else ()
        if p.get("ammo") == 0 and now - self.reload_at > RELOAD_GAP_S:
            self.reload_at = now                                 # empty: reload (Y)
            self.stats["reloads"] += 1
            return self._go("reload", "reload", {"hold": ("zl", "y")}, "the gun is empty: reload")
        if now - self.aim_since < READY_S:
            return self._go("raise", "raise", {"hold": ("zl",) + back}, "the gun comes up")
        origin = dot = None
        lz = snap.get("laser")
        if lz is not None and lz.get("up"):
            ray = (tuple(lz["from"]), tuple(lz["at"]))
            if ray != self.ray_key:
                self.ray_key, self.ray_since = ray, now
                origin, dot = ray
            elif now - self.ray_since > RAY_STALE_S:             # a frozen ray is another unit's: look again
                self.stats["restale"] += 1
                forget("laser")
                self.ray_key = None
            else:
                origin, dot = ray
        if origin is None and now - self.aim_since >= LASER_WAIT_S and not self.reraised:
            self.reraised = True                                 # still no laser: the unit may be another one's
            self.stats["reraise"] += 1
            forget("laser")
        source = "laser"
        if origin is None:
            if cam is None or now - self.aim_since < LASER_WAIT_S:
                return self._go("raise", "raise", {"hold": ("zl",) + back}, "the gun comes up (no laser yet)")
            origin, dot, source = cam["pos"], cam["target"], "camera"
        on_e = self._on_line(origin, dot, source, front or live)
        if on_e is not None and on_e is not tgt:                 # the line is on another one: he is the target now
            tgt, foot = on_e, on_e["pos"]
            self.target, self.target_at = tgt.get("ptr", tgt.get("slot")), now
            dist = flat(tgt)
        return self._aim(p, tgt, foot, dist, origin, dot, source, on_e, front, back, now)

    def _on_line(self, origin, dot, source, cands):
        """The zombie the aim's line runs into first: the laser's dot on him or its ray through him, or the camera's line
        through him within ENGAGE_R. None: nobody on the line."""
        best, best_d = None, math.inf
        for e in cands:
            foot = e["pos"]
            if source == "laser":
                hit = dot_on(dot, foot) is not None or through(origin, dot, foot)
            else:
                hit = line_hits(origin, dot, foot, ENGAGE_R + 300.0)
            if hit:
                d = math.dist(origin, foot)
                if d < best_d:
                    best, best_d = e, d
        return best

    def _aim(self, p, tgt, foot, dist, origin, dot, source, on_e, front, back, now) -> dict:
        chest = (foot[0], foot[1] + CHEST_H, foot[2])
        yaw_err, pitch_err = ray_error(origin, dot, chest)
        if abs(yaw_err) > UNAIM_ERR and on_e is None:
            line_yaw = heading(dot[0] - origin[0], dot[2] - origin[2])
            px, _, pz = p["pos"]
            alt = [e for e in front if abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - line_yaw)) <= FRONT_CONE]
            if not alt:                                          # far off him and nobody in front: gun down, turn
                self._gun_down()
                return self._go("unaim", "unaim", {"hold": ()}, f"aim {math.degrees(yaw_err):+.0f} deg off him: gun down")
            tgt = min(alt, key=lambda e: math.dist(origin, e["pos"]))
            foot = tgt["pos"]
            self.target, self.target_at = tgt.get("ptr", tgt.get("slot")), now
            yaw_err, pitch_err = ray_error(origin, dot, (foot[0], foot[1] + CHEST_H, foot[2]))
        on = on_e is not None
        auto = p.get("weapon_id") in AUTO_IDS
        trig = self._trigger(on, now, auto)
        keys = {"zl"} | self._yaw(yaw_err) | self._pitch(pitch_err) | trig | set(back)
        self._aimctx = {"target": (on_e or tgt).get("ptr", (on_e or tgt).get("slot")), "dist": dist,
                        "yaw_err": yaw_err, "source": source, "where": dot_on(dot, foot) if source == "laser" else None}
        where = self._aimctx["where"]
        self.stats["aim"] = (f"d {dist:.0f} yaw {math.degrees(yaw_err):+.1f} pitch {math.degrees(pitch_err):+.1f} "
                             f"on {where or ('line' if on else '-')} via {source} keys {','.join(sorted(keys))}")
        return self._go("fire" if on else "aim", "aim", {"hold": tuple(sorted(keys))},
                        (f"on a zombie at {dist:.0f} cm ({source})" if on else
                         f"steering {math.degrees(yaw_err):+.0f} deg to him ({source})") + (", stepping back" if back else ""))

    # --- the look (stats look, gbox.mercs.bot_look: "look at the bot") ----------------------------------------------
    def _front_foe(self, p, snap) -> bool:
        """A living zombie in front of him within reach (inside FRONT_CONE of his facing)."""
        px, py, pz = p["pos"]
        for e in snap.get("enemies") or ():
            if (e.get("hp") or 0) <= 0 or abs(e["pos"][1] - py) > MAX_DY:
                continue
            dx, dz = e["pos"][0] - px, e["pos"][2] - pz
            if math.hypot(dx, dz) <= ENGAGE_R and abs(wrap(heading(dx, dz) - p["rot"])) <= FRONT_CONE:
                return True
        return False

    def _pulls_tick(self, now) -> None:
        """Trigger pulls: one starts when the trigger starts working on a zombie (its look entry, the raise's first pull
        timed), ends when it stops or moves to another; an ended pull resolves after HIT_S: hit when its zombie's health
        fell while it ran or within HIT_S after."""
        firing = self.doing == "fire"
        target = self._aimctx.get("target") if firing else None
        if self._pull is not None and (not firing or target != self._pull["target"]):
            self._pull["end"] = now
            self._pulls.append(self._pull)
            self._pull = None
        if firing and self._pull is None:
            from ..bot_look import make_target
            if self._raise_t is not None:                        # the first pull since the gun went up
                self.stats["first_pull_n"] += 1
                self.stats["first_pull_s"] = round(self.stats["first_pull_s"] + max(0.0, now - self._raise_t), 2)
                self._raise_t = None
            ctx = self._aimctx
            entry = self.look.record_shot("auto" if self.fire_down and self.doing == "fire" else "gun",
                                          f"the line on him ({ctx.get('source')})",
                                          make_target(id=str(target), kind="zombie", dist_m=(ctx.get("dist") or 0) / 100.0),
                                          aim_err_deg=-math.degrees(ctx.get("yaw_err") or 0.0),
                                          dot_on="target" if ctx.get("source") == "laser" else "off")
            self._pull = {"target": target, "start": now, "end": None, "hit": False, "entry": entry}
        for pull in ([self._pull] if self._pull else []) + self._pulls:
            if pull["target"] in self._dropped:
                pull["hit"] = True
        for pull in [x for x in self._pulls if now - x["end"] > HIT_S]:
            self._pulls.remove(pull)
            self.stats["pulls_hit" if pull["hit"] else "pulls_miss"] += 1
            self.look.resolve(pull["entry"], "hit:zombie" if pull["hit"] else "miss:off_target")

    def _look_tick(self, snap, now) -> None:
        """After each decision: the time since the last tick in the budget of the decision that ran (t_<doing>,
        trigger_s, the turning with a zombie in front), the pulls, the idle streak among zombies, the decision itself,
        and stats look (at most every LOOK_PUBLISH_S)."""
        dt = 0.0 if self._tick_t is None else max(0.0, min(now - self._tick_t, LOOK_STEP_MAX_S))
        self._tick_t = now
        ran, front = self._ran
        keys = (("t_" + ran,) if ran in DOINGS and dt else ()) + (("trigger_s",) if ran == "fire" and dt else ()) \
            + (("t_turn_foe_front",) if front and dt else ())
        for key in keys:
            self._acc[key] += dt
            self.stats[key] = round(self._acc[key], 2)
        p = snap.get("player")
        doing = self.doing
        self._ran = (doing, bool(doing in ("turn", "unaim") and p and self._front_foe(p, snap)))
        self._pulls_tick(now)
        if p and doing not in ("none",):
            pos = p["pos"]
            moving = bool(self._look_at is not None and dt and
                          math.hypot(pos[0] - self._look_at[0], pos[2] - self._look_at[2]) / dt >= LOOK_MOVE_CM_S)
            self._look_at = pos
            foes = any((e.get("hp") or 0) > 0 and abs(e["pos"][1] - pos[1]) <= MAX_DY
                       and math.hypot(e["pos"][0] - pos[0], e["pos"][2] - pos[2]) <= LOOK_FOE_R
                       for e in snap.get("enemies") or ())
            busy = moving or doing not in ("aim", "raise", "no_foes", "walk")
            self.look.tick_idle(foes, busy, t=now)
            phase = "dead" if doing == "dead" else "survive" if doing in SURVIVAL else "fight"
            self.look.record_decision(phase, doing, self.why, t=now)
        self.stats["look_idle_among_foes_s"] = round(self.look.idle_s, 1)
        if "look" not in self.stats or (self.look.version != self._look_pub[0]
                                        and now - self._look_pub[1] >= LOOK_PUBLISH_S):
            self.stats["look"] = self.look.snapshot()
            self._look_pub = (self.look.version, now)

    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self) -> None:
        return None


class RE6Switch(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # No Mercy on Switch is played solo here: one pad, no partner control
    round_counters = ("shots", "hits", "quick_shots", "melee", "holds", "reloads", "deaths", "tablets",
                      "tablet_presses", "tablet_misses", "turns", "quick_turns", "backoffs", "reraise", "restale")         + AIM_COUNTERS + tuple("t_" + d for d in DOINGS)

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._timer = (None, 0.0)
        self._dead_at = None                    # the last moment RAM showed him dead (a replay's load follows a YES)
        self._tally, self._results_up = None, False
        self.stats: dict | None = None

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        """playing / dead / results / loading for the engine. The HUD unit and the player name the round; the clock
        standing still for HANG_S while playing reads as frozen."""
        where = self._where(m, snap)
        if where == "playing":
            self._mods(m, self.snapshot(m) if snap is None else snap, True)
        return where

    def _where(self, m, snap) -> str:
        where = screen(m).get("where")
        self._results_up = where == "results"
        now = self.clock()
        if where == "dead":
            self._dead_at = now
        elif where in ("loading", "unknown") and self._dead_at is not None and now - self._dead_at < REPLAY_LOAD_S:
            return "dead"                       # CONTINUE? YES: the replay's load stays inside the round (NO shows
                                                # "Now saving", a dialog, and is handed to the menus as before)
        elif where == "playing":
            self._dead_at = None
        if where == "loading":
            snap = self.snapshot(m) if snap is None else snap
            if snap.get("mercenaries_phase") == PHASE_OVER:
                return "results"                # time up: the round is over (its HUD fades before the results unit)
        if where == "playing":
            snap = self.snapshot(m) if snap is None else snap
            now, t = self.clock(), snap.get("timer")
            if t != self._timer[0]:
                self._timer = (t, now)
            elif now - self._timer[1] > HANG_S:
                return "loading"
            return "playing"
        if where in ("dead", "results", "loading"):
            return where
        return "results" if where in MENU_HANDOFF else "loading"

    def _mods(self, m, snap, playing: bool) -> None:
        """The session's live mods (re6_switch_mods: infinite_ammo's magazines topped up) on every snapshot, when the
        engine runs with the session's adapter and modifications are allowed."""
        ad = getattr(m, "adapter", None)
        if ad is None or getattr(m, "mercs_no_modifications", False):
            return
        from . import re6_switch_mods
        res = re6_switch_mods.maintain(ad, snap, enabled=playing)
        if self.stats is not None:
            self.stats["mod_writes"] = self.stats.get("mod_writes", 0) + res.get("writes", 0)
            if not res.get("verified", True):
                self.stats["mod_reason"] = res.get("reason", "")

    def result_ready(self, snap, now) -> bool:
        """The terminal tally is final (the engine closes the round's evidence then): the RESULTS unit is up, or the
        score and kills held still for 1 s after 2 s of the time-up (15 s at most)."""
        sig = (snap.get("score"), snap.get("kills"))
        st = self._tally
        if st is None or st["phase"] != snap.get("mercenaries_phase"):
            st = self._tally = {"phase": snap.get("mercenaries_phase"), "sig": sig, "started": now, "changed": now}
        elif st["sig"] != sig:
            st.update(sig=sig, changed=now)
        if self._results_up:
            return True
        return now - st["started"] >= 15.0 or (now - st["started"] >= 2.0 and now - st["changed"] >= 1.0)

    def menu_handoff(self, m, snap, where) -> bool:
        """The engine hands a finished round back to the menus only when RAM names a native screen: the results, a
        dialog (Save successful, the Leaderboards prompt), the Continue? screen or the selects."""
        if where != "results":
            return False
        try:
            return screen(m).get("where") in MENU_HANDOFF
        except (ValueError, OSError, struct.error):
            return False

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        self.stats = stats
        return Bot(stats=stats, clock=clock)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
                "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "no_mercy"}


DRIVER = RE6Switch
