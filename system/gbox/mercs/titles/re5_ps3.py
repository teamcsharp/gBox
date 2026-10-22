"""Title #2: Resident Evil 5 Gold Edition, PS3 (BLUS30491, app 01.01) - the Mercenaries driver (The Mercenaries Reunion).

RE5 is MT Framework: the game's managers are singletons whose instance pointers sit next to their class descriptors
(MtDTI) in .bss, so every chain starts at a static address (found live 2026-10-20 on the Spark's RPCS3; the class of
any object comes from its vtable's getDTI: slot 5 returns the MtDTI, whose +4 is the class name):

    sPlayer   [0x017FEB34]   +0x28  -> the player (uPl00ChrisCos4 ...): +0x30 pos (x, y up, z), +0x40 rotation
                                     quaternion (yaw = 2 atan2(qy, qw), the atan2(dx, dz) convention: forward =
                                     (sin, 0, cos)), +0x845 u8 action (0 stand, 1 move / run, 2 aim), +0x1AA0 f32
                                     aim pitch while aiming (radians, + = down), +0x14A4 s16 health, +0x14A6 maximum
    sEnemy    [0x017FDB60]   +0x28 count, +0x34 -> array of enemy pointers (uEm10 / uEm11 Majini ...): +0x30 pos,
                                     +0x40 rotation, +0x14A4 s16 health, +0x14A6 maximum (Majini 800, 700)
    sBioMain  [0x0191CEE4]   +0x182D4 -> cGameSys: +0x3E0 f32 seconds left, +0x3E4 f32 the round's start time,
                                     +0x3F4 s32 kills, +0x3FC s32 combo, +0x404 f32 combo window left, +0x418 s32 score
    sActionButton [0x017B7174], sItem [0x017FE574], sUnit [0x0191D700], sBioPad [0x0191CF38]

Controls (Type D, the game's default here; gBox pad names = PS3 buttons, gbox.adapters.RPCS3_KEYPAD): left stick
moves / strafes (lup ...), right stick turns (rleft = larger heading, rright = smaller; while aiming it turns ~30 deg/s
and raises / lowers the aim: rup = up), L1 = ready the weapon, L1 + R1 = fire, L2 + R1 = knife, up + cross = run,
L1 + cross = reload. Measured live: the stick turns ~150 deg/s, walking ~145 units/s (world units are cm).
"""
from __future__ import annotations

import json
import math
import struct
import time
from pathlib import Path

from ..driver import Driver
from . import re5_combat, re5_nav, re5_weapons

S_PLAYER, S_ENEMY, S_MAIN = 0x017FEB34, 0x017FDB60, 0x0191CEE4
S_ACTION, S_ITEM, S_UNIT = 0x017B7174, 0x017FE574, 0x0191D700
S_CAMERA, CAM_CTRL, CAM_EYE, CAM_AT = 0x0191CA6C, 0x104, 0x30, 0x50   # sBioCamera +0x104 -> uCameraCtrl: eye, look-at
MAIN_GAMESYS = 0x182D4
P_POS, P_ROT, P_PITCH, P_ACTION, P_HP = 0x30, 0x40, 0x1AA0, 0x845, 0x14A4
E_POS, E_HP = 0x30, 0x14A4
GS_TIMER, GS_START, GS_KILLS, GS_COMBO, GS_COMBO_T, GS_SCORE = 0x3E0, 0x3E4, 0x3F4, 0x3FC, 0x404, 0x418
MAX_ENEMIES = 64
ACTIONS = {0: "stand", 1: "move", 2: "aim", 4: "grabbed", 5: "hit"}
P_GRABBED = 4                          # held by a Majini: "Break free" (wiggle the left stick)

HEAD_H, GUN_H = 160.0, 140.0           # above the feet: a Majini's head, the player's gun (cm)
# uLaserSight (sUnit's FxCore line 18): +0x200 the laser's origin (the muzzle), +0x30 the laser dot (where the ray
# lands: a Majini, a wall, the ground); the combat layer closes its aim on the dot (the camera's ray is ~5 deg off it,
# the body's yaw +-7: the upper body aims inside a cone)
FX_LINE, LASER_VT, LASER_FROM, LASER_AT = 18, 0x015BD958, 0x200, 0x30
SWITCH_EVERY_S, SWITCH_ACK_S, SWITCH_FAIL_S = 1.0, 1.5, 8.0
# The inventory: embedded in the player at +0x22E0 (live 2026-10-21, with the RE5 mods agent): INV_SLOTS slots of 0x30,
# a slot: +0x08 u32 id word 0x0TII (T 1 = weapon, uWpII; 2 = ammo / items), +0x0C rounds loaded, +0x10 capacity,
# +0x1C u32 UI grid position, +0x20 u32 1 = in hand, +0x2D u8 != 0 = in use. Storage order differs from
# UI grid order: live rocket record0 -> grid3, Hydra record1 -> grid5. Only grid1/3/5/7 are D-pad positions.
P_INV, INV_SLOT, INV_SLOTS, INV_ALL = 0x22E0, 0x30, 9, 24
INV_ID, INV_ROUNDS, INV_CAP, INV_GRID, INV_HAND, INV_USED = 0x08, 0x0C, 0x10, 0x1C, 0x20, 0x2D
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
HOLD_FIRE = {0x15, 0x03, 0x09}         # automatic weapons fired by holding R1 (the Gatling, the VZ61, Chris HM's
HOLD_CAP = 50                          # uWp09); or any with a big magazine (autos): the rest fire once a press
TAP_ON, TAP_OFF = 1, 2                 # ticks of R1 down / up when tapping (a magnum's own recovery is longer)
# PS3 item table: spray, green herb, GG and GR; uncombined red (0x306) cannot heal.
# https://astralshade.wordpress.com/2013/12/19/resident-evil-5-ps3-mod-weapons-hack/
HEAL_IDS = {0x304, 0x305, 0x307, 0x309}
HEAL_AT = 0.4                          # use one below this share of health
HEAL_USE_EVERY_S, HEAL_ATTEMPT_S, HEAL_RETRY_S = 0.35, 4.0, 1.0
WEAPON_NAMES = {0x02: "M92F", 0x03: "VZ61", 0x0B: "M29", 0x12: "Barry's handgun", 0x15: "Gatling", 0x20: "Dragunov"}
ENGAGE, SHOOT_RANGE, TOO_CLOSE = re5_combat.ENGAGE_R, 2200.0, 110.0
CLOSE_ESCAPE_S, CLOSE_ACQUIRE_S = 0.25, 1.0  # escape briefly, then give the gun time to become ready
BODY_R = 35.0                          # half a body: a shot inside atan(BODY_R / dist) hits
TURN_TOL = math.radians(12)            # turn with the stick (not aiming) until within this
AIM_TOL, PITCH_TOL = math.radians(2.5), math.radians(2.5)   # fire inside these
FINE = math.radians(6)                 # closer than this: pulse the stick (a tick on, a tick off)
MAX_DY = 450.0                         # targets this far above / below are out of reach (rooftops): not chosen
STUCK_S, STUCK_MOVE = 1.2, 80.0
STAGE_YIELD_S = 2.5                      # a stage prompt shown this long beside close foes is taken anyway (a fence / ledge between)
RUN_SPEED = 250.0                      # cm/s running (the route ETAs; measured live: walking 145)
# The time bonuses: hourglasses (uOm0100, model "sunadokei_360" = hourglass in uOm0100.arc; 9 in Public Assembly),
# units of sUnit's move line 12 ("OM"), told by their vtable.
OM_LINE, OM_MAX = 12, 600
HOURGLASS_VT = 0x015EF5E0              # uOm0100's vtable (BLUS30491 app 01.01; read live 2026-10-21)
HG_CENTRE_DY = 13.0                    # its middle, above its position (+0x30)
HG_CENTRE, HG_KIND = 0x250, 0x194      # +0x250 f32 x4 bounding sphere (centre, radius: 28 cm, 13 cm above the origin);
HG_COMBO = 0x90                        # the kind byte of the 2 combo bonuses (their clock is the combo's; unconfirmed)
                                       # +0x194 u32 0x00KK..01: 0x90 on 2 of Public Assembly's 9, 0xA0 on the other 7
BONUS_RANGE = 12000.0                  # go for a time bonus whose route is this long at most (cm)
FIGHT_R, FIGHT_CONE = 350.0, math.radians(40)   # a Majini this near and this far off the heading blocks the way:
ON_TOP_R = 160.0                       # fought from where the player stands, as is one this close from any side;
                                       # the rest chase him and are ignored (grabs are wiggled off): the tour goes on
ROUTE_LEN_S = 3.0                      # the bonuses' route lengths are worked out again this often
BONUS_GIVE_UP_S, BONUS_SKIP_S = 4.0, 30.0   # fired at one this long and it is still there: leave it this long
BONUS_WALK = True                      # walk to the far ones along the game's navmesh (re5_nav)
BONUS_HUNT = True                      # go for them (taken with the "□ Time bonus" prompt at the hourglass:
                                       # the Gatling's fire, knife slashes and walking over it do not take one)
BONUS_TAKE = 140.0                     # this close (and on its level): face it, square on its prompt
BONUS_REACH = 400.0                    # this close: finish taking it even with a Majini near (the press is quick)
BONUS_PUNCH_R, BONUS_PUNCH_S = 170.0, 0.45   # within this, facing it: tap square blindly to punch it, this often
BONUS_NEAR = 650.0                     # walked to within this, then shot from where he stands...
BONUS_STEEP = math.radians(-18)        # ...no steeper than this (the aim stops near -20 deg: step back)
BONUS_LEVEL_DY = 150.0                 # ...and from its own level (not from a roof above it)
WP_REACHED, WP_CLIMB = 70.0, 110.0     # a waypoint is passed this close; the next one this far above / below and
                                       # (almost) straight up / down = a ladder or a drop: the stage's square prompt
REPLAN_S, ROUTE_STALE_S = 2.0, 60.0    # the route is drawn again this often; a bonus followed this long is left
CLIMB_WAIT_S = 3.0                     # at a crossing this long without its prompt: the player can't take it
_AVOID: dict = {}                      # navmesh signature -> the crossings the player could not take (kept across
                                       # rounds and runs: gbox-data/mercs/lessons/BLUS30491-crossings.json)
CROSSINGS_FILE = "BLUS30491-crossings.json"
NAV_LEARNING_FILE = "BLUS30491-navigation.json"
STAND_R = 250.0                        # the stand: the round's start position, held from this close
BREAK_AT_S, BREAK_MARGIN_S = 60.0, 15.0   # leave the stand for time at this clock, or at the nearest one's ETA + this
# Sight and pursuit (operator 2026-10-21: "If the person stands still ... what is there to see?"; live the same day the
# bot spent 57 of 130 s aiming into walls at Majini behind them). A Majini is fought from where the player stands only
# with open floor between them (the navmesh: floor_segment, or a route that barely bends) or within PURSUE_NEAR;
# the rest are walked to along the navmesh. One fought while the laser dot stops short of him (a wall, a fence) for
# BLOCKED_VIEW_S, or without the dot ever reaching him for UNSIGHTED_S, is left out of sight for PURSUE_S and walked to.
SIGHT_R = 2200.0                       # open-floor Majini within this are fought (= SHOOT_RANGE)
SIGHT_CACHE_S = 0.3                    # a floor_segment answer is kept this long per Majini
SIGHT_BEND, SIGHT_SLACK = 1.1, 50.0    # ...or a navmesh route at most this much longer than the straight line: open
PURSUE_NEAR = 200.0                    # this close he is fought whatever the floor says (a doorway, a corner)
BLOCKED_VIEW_S, UNSIGHTED_S, PURSUE_S = 0.5, 2.5, 2.0
VIEW_SHORT = 150.0                     # the dot this much short of him, roughly toward him: something in between
WALL_R = 120.0                         # the dot this close to the muzzle: facing a wall
PURSUE_PICK_S = 1.0                    # the Majini to walk to is chosen again this often (route lengths)
RANK_SCORES = (("SS", 90000), ("S", 60000), ("A", 40000), ("B", 20000), ("C", 10000), ("D", 0))   # Reunion solo
                                       # (docs/mercenaries_re5_meta.md 1.1); the rank is score alone, same every stage


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000


def u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def yaw_of(q) -> float:
    """The quaternion (x, y, z, w) about +y -> heading (atan2(dx, dz) convention)."""
    return wrap(2.0 * math.atan2(q[1], q[3]))


_HOURGLASSES: dict = {}                 # id(memory) -> (monotonic time, [units], memory): the OM line walked once a second
HOURGLASS_WALK_S = 1.0


def hourglass_units(m) -> list:
    """The hourglass units in sUnit's OM line (walked at most once a HOURGLASS_WALK_S per memory view)."""
    if not HOURGLASS_VT:
        return []
    now = time.monotonic()
    hit = _HOURGLASSES.get(id(m))
    if hit and hit[2] is m and now - hit[0] < HOURGLASS_WALK_S:
        return hit[1]
    su = u32(m, S_UNIT)
    units: list = []
    if ptr_ok(su):
        u, n = u32(m, su + UNIT_LINES + LINE_STRIDE * OM_LINE + LINE_FIRST), 0
        while ptr_ok(u) and n < OM_MAX:
            if u32(m, u) == HOURGLASS_VT:
                units.append(u)
            u, n = u32(m, u + UNIT_NEXT), n + 1
    if len(_HOURGLASSES) > 16:
        _HOURGLASSES.clear()
    _HOURGLASSES[id(m)] = (now, units, m)
    return units


def bonuses(m) -> list:
    """The time bonuses still standing: [{"ptr", "pos", "r", "kind": "time", "kind_word"}] from the OM line
    (HOURGLASS_VT): each one's bounding sphere read every call, the line itself once a second."""
    out: list = []
    for u in hourglass_units(m):
        if u32(m, u) != HOURGLASS_VT:                       # gone since the last walk
            continue
        x, y, z = struct.unpack(">3f", m.rd(u + 0x30, 12))
        r = struct.unpack(">f", m.rd(u + HG_CENTRE + 12, 4))[0]
        r = r if 5.0 < r < 100.0 else 28.0
        kw = u32(m, u + HG_KIND)
        out.append({"ptr": u, "pos": (x, y + HG_CENTRE_DY, z), "r": r,
                    "kind": "combo" if (kw >> 16) & 0xFF == HG_COMBO else "time", "kind_word": kw})
    return out


def inventory(m, player: int) -> list:
    """Every used storage record; slot is its index, grid is its independent valid UI position (or None)."""
    raw = m.rd(player + P_INV, INV_SLOT * INV_ALL)
    out = []
    for k in range(INV_ALL):
        rec = raw[INV_SLOT * k:INV_SLOT * (k + 1)]
        if not rec[INV_USED]:
            continue
        word = struct.unpack(">I", rec[INV_ID:INV_ID + 4])[0]
        rounds = struct.unpack(">I", rec[INV_ROUNDS:INV_ROUNDS + 4])[0]
        cap = struct.unpack(">I", rec[INV_CAP:INV_CAP + 4])[0]
        grid = struct.unpack_from(">I", rec, INV_GRID)[0]
        hand = struct.unpack(">I", rec[INV_HAND:INV_HAND + 4])[0]   # +0x20, not next to the counts
        out.append({"slot": k, "id": word, "type": word >> 8, "item": word & 0xFF, "rounds": rounds, "cap": cap,
                    "grid": grid if grid < INV_SLOTS else None, "grid_raw": grid, "hand": hand == 1})
    return out


_LASER: dict = {}                      # id(memory) -> (the uLaserSight unit, memory): found once a round


def laser(m) -> dict | None:
    """The laser sight's ray from RAM: {"from": the muzzle, "at": the dot}, None without the unit."""
    hit = _LASER.get(id(m))
    u = hit[0] if hit and hit[1] is m else 0
    if not (ptr_ok(u) and u32(m, u) == LASER_VT):
        su = u32(m, S_UNIT)
        u, n = (u32(m, su + UNIT_LINES + LINE_STRIDE * FX_LINE + LINE_FIRST) if ptr_ok(su) else 0), 0
        while ptr_ok(u) and n < UI_MAX and u32(m, u) != LASER_VT:
            u, n = u32(m, u + UNIT_NEXT), n + 1
        if not ptr_ok(u):
            return None
        if len(_LASER) > 16:
            _LASER.clear()
        _LASER[id(m)] = (u, m)
    return {"from": struct.unpack(">3f", m.rd(u + LASER_FROM, 12)), "at": struct.unpack(">3f", m.rd(u + LASER_AT, 12))}


def equipped(snap: dict) -> dict | None:
    """The slot in hand, or None."""
    return next((s for s in snap.get("inventory") or () if s.get("hand")), None)


def snapshot(m) -> dict:
    """The round from RAM: the player, the enemies, the Mercenaries counters (None where a pointer is not there)."""
    snap: dict = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, "kills": None,
                  "combo": None, "combo_timer": None}
    sp = u32(m, S_PLAYER)
    p = u32(m, sp + 0x28) if ptr_ok(sp) else 0
    if ptr_ok(p):
        pos = struct.unpack(">3f", m.rd(p + P_POS, 12))
        rot = struct.unpack(">4f", m.rd(p + P_ROT, 16))
        pitch = -struct.unpack(">f", m.rd(p + P_PITCH, 4))[0]        # + = up
        hp, hp_max = struct.unpack(">hh", m.rd(p + P_HP, 4))
        action = m.rd(p + P_ACTION, 1)[0]
        snap["player"] = {"ptr": p, "pos": pos, "rot": wrap(yaw_of(rot)), "pitch": pitch, "action": action,
                          "state": ACTIONS.get(action, action), "hp": hp, "hp_max": hp_max}
        try:
            snap["recovery_active"] = hp == 1 and recovery_active(m, p)
        except (ValueError, OSError, struct.error, IndexError):
            snap["recovery_active"] = False          # health maintenance independently rereads and refuses read errors
        try:
            snap["inventory"] = inventory(m, p)
        except (ValueError, OSError, struct.error):
            snap["inventory"] = []
        try:
            snap["laser"] = laser(m)
        except (ValueError, OSError, struct.error):
            snap["laser"] = None
    se = u32(m, S_ENEMY)
    if ptr_ok(se):
        n, arr = u32(m, se + 0x28), u32(m, se + 0x34)
        if ptr_ok(arr) and 0 < n <= MAX_ENEMIES:
            ptrs = struct.unpack(f">{n}I", m.rd(arr, 4 * n))
            for slot, e in enumerate(ptrs):
                if not ptr_ok(e):
                    continue
                pos = struct.unpack(">3f", m.rd(e + E_POS, 12))
                hp, hp_max = struct.unpack(">hh", m.rd(e + E_HP, 4))
                snap["enemies"].append({"slot": slot, "ptr": e, "pos": pos, "hp": hp, "hp_max": hp_max})
    cm = u32(m, S_CAMERA)
    cc = u32(m, cm + CAM_CTRL) if ptr_ok(cm) else 0
    if ptr_ok(cc):
        snap["camera"] = {"eye": struct.unpack(">3f", m.rd(cc + CAM_EYE, 12)),
                          "at": struct.unpack(">3f", m.rd(cc + CAM_AT, 12))}
    if snap["player"]:
        snap["bonuses"] = bonuses(m)
        snap["prompt"] = prompt(m)
        snap["stage_prompt"] = stage_prompt(m)
        snap["prompt_target"] = prompt_target(m)            # the Majini a finisher prompt is for (the combat layer)
        try:
            snap["nav"] = re5_nav.read(m, _NAV_CACHE)
        except (ValueError, OSError, struct.error):
            snap["nav"] = None
    main = u32(m, S_MAIN)
    gs = u32(m, main + MAIN_GAMESYS) if ptr_ok(main) else 0
    if ptr_ok(gs):
        t, t0 = struct.unpack(">2f", m.rd(gs + GS_TIMER, 8))
        snap.update(timer=round(t, 2), timer_start=t0, kills=struct.unpack(">i", m.rd(gs + GS_KILLS, 4))[0],
                    combo=struct.unpack(">i", m.rd(gs + GS_COMBO, 4))[0],
                    combo_timer=round(struct.unpack(">f", m.rd(gs + GS_COMBO_T, 4))[0], 2),
                    score=struct.unpack(">i", m.rd(gs + GS_SCORE, 4))[0])
    return snap


MENU_KEYS = ("start", "cross")         # results: START (OK); stage / character select: cross; "Continue?": cross = Yes


def menu_key(n: int) -> str:
    """The n-th press that walks Reunion's screens back into a round when RAM says no round is up: START and cross in
    turn (live 2026-10-20: START leaves the results screen and does nothing on the selects; cross picks the stage and
    the character - the last ones played - and does nothing on the results), so a press never wanders off."""
    return MENU_KEYS[n % len(MENU_KEYS)]


# The screens between rounds and on the way from the title, from the interface's own units (live 2026-10-21, one
# press at a time on a gBox session): sUnit keeps its units in move lines, +0x24 + 0x20 * line: +0xC the line's first
# unit, and each unit's +8 is the next; a unit's class is told by its vtable (each named by its getDTI). The title's
# menus are uIdStartUpNN units, not all in the interface lines (Reunion's title is in line 1), so out of a round every
# line is walked.
UNIT_LINES, LINE_STRIDE, LINE_FIRST, UNIT_NEXT = 0x24, 0x20, 0xC, 0x8
UI_LINES = (0, 26, 27, 28)
N_LINES = 32
UI_VTABLES = {0x015ABAC8: "uIdMerce00",         # the round's Mercenaries HUD (clock, score, combo)
              0x015ABE28: "uIdPause00",         # the in-round pause menu (there while a round runs)
              0x015ABB80: "uIdNowLoading00",    # NOW LOADING
              0x015ABEE0: "uIdSaving00",        # saving the records on the results screen
              0x015AB350: "uIdAlert00",         # the title's dialogs: +0x3C names the one up (ALERTS)
              0x015AB690: "uIdCursor",          # the menus' cursors (the results screen, the title; not the boot)
              0x015AC608: "uIdStartUp00",       # the main menu (PLAY GAME, RECORDS ...): cursor +0x44
              0x015AC5A8: "uIdStartUp01",       # PLAY GAME (cursor +0x44, EXTRA CONTENT = 7); with +0x174 = 1 its
                                                # EXTRA CONTENT list (cursor +0x188, THE MERCENARIES REUNION = 3)
              0x015ACA50: "uIdStartUp29",       # Reunion's title (START first); with +0x174 = 1 SOLO / DUO (SOLO first)
              0x015ACD50: "uIdStartUp21",       # STAGE SELECT (Reunion)
              0x015ACCF0: "uIdStartUp22",       # CHARACTER SELECT (Reunion)
              0x015AD690: "uIdTopMenu00",       # the title's menus (around the selects, and the main menu)
              0x015AD638: "uIdTitle00",         # +0x1F8 = 0x48 on PRESS START
              0x015AD588: "uIdTitle02"}
UI_MAX = 64
ALERT_ID = 0x3C
ALERTS = {0x22: "alert_signin",                 # "... without signing in. Sign in?": circle = Continue
          0x08: "alert_ok"}                     # "Load successful.": cross = OK (0x13: loading the save, wait)
MENU_CURSOR, MENU_SUB, EXTRA_CURSOR = 0x44, 0x174, 0x188
TITLE_STEP, TITLE_PRESS_START = 0x1F8, 0x48
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, EXTRA_REUNION = 0, 7, 3


def ui_units(m, lines=UI_LINES) -> dict:
    """The interface units up now that UI_VTABLES knows: class name -> the first unit of that class."""
    su = u32(m, S_UNIT)
    out: dict = {}
    if not ptr_ok(su):
        return out
    for line in lines:
        u, n = u32(m, su + UNIT_LINES + LINE_STRIDE * line + LINE_FIRST), 0
        while ptr_ok(u) and n < UI_MAX:
            name = UI_VTABLES.get(u32(m, u))
            if name and name not in out:
                out[name] = u
            u, n = u32(m, u + UNIT_NEXT), n + 1
    return out


def screen(m, merc=None) -> dict:
    """The deployment's menus interface (gbox/mercs_bot.py): where RE5 is, read from RAM. In a round: playing / dead /
    results (the round's own fields). Out of one (no player), from the interface units: the title's dialogs
    (alert_signin, alert_ok), title (PRESS START), main_menu / play_game / extra_content (with cursor and target),
    reunion_title, reunion_solo, select_stage, select_player, loading, menu (the title's menus between those: wait),
    results (the clock at 0 and none of those up)."""
    snap = snapshot(m)
    out = {"where": own_screen(snap), "cursor": None, "target": None}
    if snap.get("player"):
        if out["where"] == "playing" and (ROSTER.pick is not None or ROSTER.round is None):
            out["character"] = ROSTER.started()
        return out
    ui = ui_units(m, range(N_LINES))
    alert = u32(m, ui["uIdAlert00"] + ALERT_ID) if "uIdAlert00" in ui else 0
    where, cursor, target = "unknown", None, None
    if alert:
        where = ALERTS.get(alert, "alert")
    elif "uIdStartUp22" in ui:
        where, cursor, target = "select_player", u32(m, ui["uIdStartUp22"] + SELECT_CURSOR), ROSTER.want()
    elif "uIdStartUp21" in ui:
        where = "select_stage"
    elif "uIdStartUp29" in ui:
        where = "reunion_solo" if u32(m, ui["uIdStartUp29"] + MENU_SUB) == 1 else "reunion_title"
    elif "uIdStartUp01" in ui:
        u = ui["uIdStartUp01"]
        if u32(m, u + MENU_SUB) == 1:
            where, cursor, target = "extra_content", u32(m, u + EXTRA_CURSOR), EXTRA_REUNION
        else:
            where, cursor, target = "play_game", u32(m, u + MENU_CURSOR), PLAY_EXTRA_CONTENT
    elif "uIdStartUp00" in ui:
        where, cursor, target = "main_menu", u32(m, ui["uIdStartUp00"] + MENU_CURSOR), MAIN_PLAY_GAME
    elif ui.keys() & {"uIdNowLoading00", "uIdSaving00"}:
        where = "loading"
    elif "uIdTitle00" in ui and "uIdTopMenu00" not in ui and u32(m, ui["uIdTitle00"] + TITLE_STEP) == TITLE_PRESS_START:
        where = "title"
    elif ui.keys() & {"uIdTopMenu00", "uIdTitle00", "uIdTitle02"}:
        where = "menu"
    elif "uIdCursor" in ui and snap.get("timer") is not None and snap["timer"] <= 0:
        where = "results"                               # (the boot's logos have no cursor units: never pressed on)
    out.update(where=where, cursor=cursor, target=target, ui=sorted(ui))
    return out


STEPS = {"results": "start", "select_stage": "cross", "dead": "cross", "title": "start",
         "alert_signin": "circle", "alert_ok": "cross", "reunion_title": "cross", "reunion_solo": "cross"}
BOOT_KEY = "cross"      # out of a round, a screen RAM can't name (the cold boot's HDD notice, logos): mercs_bot.Boot
CURSORED = ("main_menu", "play_game", "extra_content", "select_player")
CHARACTERS = ("Chris (Heavy Metal)", "Sheva (Fairy Tale)", "Josh", "Excella", "Chris (Warrior)", "Sheva (Business)",
              "Barry", "Rebecca")                   # CHARACTER SELECT's row, cursor 0..7 (uIdStartUp22 +0x180)
SELECT_CURSOR = 0x180


class Roster:
    """A random character each round (operator 2026-10-21: "I want to see every character whooping ass"): the next
    pick is drawn among the characters played least so far, never the one just played; the per-character tallies
    (rounds, kills, points, best combo) go to stats. Module state: the menus are read through module functions."""

    def __init__(self, rng=None):
        import random
        self.rng = rng or random.Random()
        self.pick = None                       # the cursor target for the coming round
        self.last = None                       # the character of the last round started
        self.played: dict = {c: 0 for c in CHARACTERS}
        self.tally: dict = {}                  # name -> {"rounds", "kills", "points", "combo"}
        self.round = None                      # (name, best combo seen) while a round runs

    def want(self) -> int:
        if self.pick is None:
            least = min(self.played[c] for c in CHARACTERS if c != self.last)
            pool = [i for i, c in enumerate(CHARACTERS) if self.played[c] == least and c != self.last]
            self.pick = self.rng.choice(pool)
        return self.pick

    def started(self) -> str:
        """A round is up: the pick played (or the last one again when nothing was picked: a Continue)."""
        name = CHARACTERS[self.pick] if self.pick is not None else (self.last or CHARACTERS[0])
        if self.round is None or self.round[0] != name or self.pick is not None:
            self.played[name] += 1
            self.round = [name, 0]
        self.last, self.pick = name, None
        return name

    def observe(self, snap: dict) -> dict:
        """The live round's counters into the character's tally; returns the stats fields."""
        if self.round is None:
            return {}
        name = self.round[0]
        self.round[1] = max(self.round[1], snap.get("combo") or 0)
        t = self.tally.setdefault(name, {"rounds": 0, "kills": 0, "points": 0, "combo": 0})
        t.update(rounds=self.played[name], kills=snap.get("kills") or t["kills"], points=snap.get("score") or t["points"],
                 combo=max(t["combo"], self.round[1]))
        return {"character": name, "char_tally": "; ".join(f"{c}: {v['rounds']}r {v['kills']}k {v['points']}p c{v['combo']}"
                                                          for c, v in self.tally.items())}


ROSTER = Roster()


class StagePick:
    """A random stage each visit to STAGE SELECT (operator 2026-10-22: "have the bot go between the stages randomly
    during the select and have him play on different levels"). RAM doesn't name the stage cursor yet, so the pick is
    a random number of D-pad rights (the row of stages, 0..MAX_MOVES) before cross; mercs_bot's Navigator reports each
    press it sends (pressed()), so a press held back for a settle never counts."""
    MAX_MOVES = 7                              # Reunion's eight stages: any of them from wherever the cursor is

    def __init__(self, rng=None):
        import random
        self.rng = rng or random.Random()
        self.left = None                       # moves still to make on this visit; None: not on STAGE SELECT

    def key(self, scr: dict) -> str:
        if self.left is None:
            self.left = self.rng.randint(0, self.MAX_MOVES)
        return "dright" if self.left > 0 else "cross"

    def pressed(self, scr: dict, key: str) -> None:
        if scr.get("where") != "select_stage":
            return
        if key == "dright" and self.left:
            self.left -= 1
        elif key == "cross":
            self.left = None                   # the stage is taken: the next visit draws again


STAGE_PICK = StagePick()


def pressed(scr: dict, key: str) -> None:
    """mercs_bot's Navigator: a key it sent on this screen."""
    STAGE_PICK.pressed(scr, key)


def step(scr: dict) -> str | None:
    """The one press towards the next round. From the title: START, circle on the sign-in question, cross on "Load
    successful", then the cursor (read from RAM) moved to PLAY GAME, EXTRA CONTENT, THE MERCENARIES REUNION and taken,
    START and SOLO on Reunion's title. Between rounds: START leaves the results, cross takes the stage and the
    character the cursors are on (the last ones played), cross answers "Continue? Yes". Nothing anywhere else."""
    where = scr.get("where")
    if where in CURSORED:
        cur, tgt = scr.get("cursor"), scr.get("target")
        if cur is None or tgt is None:
            return None
        if cur == tgt:
            return "cross"
        if where == "select_player":                     # the characters' row: left / right
            return "dright" if cur < tgt else "dleft"
        if where == "play_game" and cur == 0:
            return "dup"                                 # up from the top wraps to EXTRA CONTENT, the last entry
        return "ddown" if cur < tgt else "dup"
    if where == "select_stage":
        return STAGE_PICK.key(scr)
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """Never: the bot presses only on the screens above, so it never starts a story game."""
    return None


WIGGLE = (("lleft",), ("lright",), ("lleft",), ("lright",))
# sActionButton+0x34 is its active-array COUNT, not HUD bits. The selected first-player display units below carry
# visibility and actual requested keys. cActionButton+4 owner/+14 kind/+40 target describe the action, not the input.
BTN_OWNER, BTN_KIND, BTN_TARGET = 0x04, 0x14, 0x40
BTN_MELEE, BTN_STAGE = 3, 2
AB_ENABLED, AB_PLAYER_ENABLED, AB_PLAYER_INDEX = 0x2C, 0x4C, 0x50
AB_INPUT_MODE, AB_ALTERNATE_CONTROLLER = 0x60, 0x24C
QTE_UNITS = (0x298, 0x2DC)
QTE_INPUT_TABLE = 0x0139E2C0
QTE_MASKS = (0, 0x8000, 0x1000, 0x4000, 0x2000, 0x0400, 0x0800, 0x0100,
             0x0200, 0x8000, 0x1000, 0x4000, 0x2000, 0x9000, 0x6000, 0xC000,
             0x3000, 0x0300, 0x0C00, 0x0300, 0, 0, 0x8000, 0x1000,
             0x4000, 0x2000, 0, 0, 0, 0x8001, 0, 0)
QTE_INPUT_SIGNATURE = struct.pack(">32I", *QTE_MASKS)
QTE_SIGNATURES = {0x000B7EC4: bytes.fromhex("816a000c812b001890ca0014912a0010800b002090ca001c"),
                  0x000B7100: bytes.fromhex("8159000c2f0a0000419a029c79490020800900242f80003b"),
                  0x000AD9CC: bytes.fromhex("817f000c38000001981f0005812b00242f890100419e0128"),
                  0x00C2F0B4: bytes.fromhex("a17d000a5560077a2f800000419e000861290100556007382f800000419e000861290200")}
QTE_KEYS = ((0x8000, "square"), (0x1000, "triangle"), (0x4000, "cross"), (0x2000, "circle"),
            (0x0400, "l2"), (0x0800, "r2"), (0x0100, "l1"), (0x0200, "r1"))
QTE_ALLOWED_MASK = sum(bit for bit, _ in QTE_KEYS)
QTE_MODES = {1: "mash", 2: "release", 3: "mash", 4: "mash", 5: "mash"}
QTE_STICK_MODES = {6: "mash:wiggle", 7: "stick:rotate", 8: "stick:y", 9: "stick:x"}
QTE_STICK_SIGNATURES = {
    0x00C2F118: bytes.fromhex("a01d00122b80003f419d028c65290001a01d00102b80003f419d026c65290008"),
    0x000ABEF4: bytes.fromhex("801b0034540a031e2f8a0000419e00d4801a00142f800000"),
    0x000ADAE8: bytes.fromhex("809900345489031e2f890000409e00b438000000913f00145403063e4bfffec8"),
    0x000AD98C: bytes.fromhex("0000003c00000090000000a8000000c0000000dc000000fc0000011c0000013c0000015c0000015c")}
QTE_ROTATION = (("lup",), ("lup", "lleft"), ("lleft",), ("lleft", "ldown"),
                ("ldown",), ("ldown", "lright"), ("lright",), ("lright", "lup"))
QTE_STICK_STEP_S = 0.08
QTE_BUTTON_VT = 0x016332A8
P_DYING_TIMER, P_RECOVER_BUTTON = 0x1CEC, 0x22DC


def recovery_active(m, player=None) -> bool:
    """Verified solo DYING state, including frames when its button is hidden; this never authorizes input.

    The recovery callback reads HP1, the positive countdown and this owned button independently of display flags.
    Read failures propagate so a health writer cannot interpret an unreadable state as permission to refill.
    """
    sp = u32(m, S_PLAYER)
    if not ptr_ok(sp) or sp % 4 or sp > 0x40000000 - 0x2C:
        return False
    pl = u32(m, sp + 0x28)
    if not ptr_ok(pl) or pl % 4 or pl > 0x40000000 - P_RECOVER_BUTTON - 4 \
            or player is not None and player != pl or struct.unpack(">h", m.rd(pl + P_HP, 2))[0] != 1:
        return False
    countdown = struct.unpack(">f", m.rd(pl + P_DYING_TIMER, 4))[0]
    btn = u32(m, pl + P_RECOVER_BUTTON)
    if not math.isfinite(countdown) or countdown <= 0 or not ptr_ok(btn) or btn % 4 or btn > 0x40000000 - 8:
        return False
    identity = m.rd(btn, 8)
    if struct.unpack(">2I", identity) != (QTE_BUTTON_VT, pl):
        return False
    # Countdown may legitimately decrease between reads, but the living player and owned button must stay current.
    countdown = struct.unpack(">f", m.rd(pl + P_DYING_TIMER, 4))[0]
    return math.isfinite(countdown) and countdown > 0 and u32(m, S_PLAYER) == sp \
        and u32(m, sp + 0x28) == pl and u32(m, pl + P_RECOVER_BUTTON) == btn \
        and m.rd(btn, 8) == identity and struct.unpack(">h", m.rd(pl + P_HP, 2))[0] == 1


def prompt_chord(token, prefix):
    """Resolve only known pad chords; a malformed token never becomes an input event."""
    if not isinstance(token, str) or not token.startswith(prefix + ":"):
        return None
    keys = token[len(prefix) + 1:].split("+")
    known = {key for _, key in QTE_KEYS}
    return tuple(keys) if keys and len(keys) == len(set(keys)) and all(k in known for k in keys) else None


def selected_prompt(m):
    """The first player's active displayed input request, verified against BLUS30491's immutable mask table.

    sActionButton+0x34 is an array count, not HUD flags. Its two selected display units carry the actual input.
    The manager's player mask routes enemy-owned grab buttons too; button ownership is not a visibility test.
    """
    try:
        sp, ab = u32(m, S_PLAYER), u32(m, S_ACTION)
        pl = u32(m, sp + 0x28) if ptr_ok(sp) else 0
        if not (ptr_ok(pl) and ptr_ok(ab)) or not m.rd(ab + AB_ENABLED, 1)[0] \
                or not m.rd(ab + AB_PLAYER_ENABLED, 1)[0] or u32(m, ab + AB_PLAYER_INDEX) != 0:
            return None
        if u32(m, ab + AB_INPUT_MODE) != 0 or u32(m, ab + AB_ALTERNATE_CONTROLLER) != 0xFFFFFFFF:
            return None                                # fixed physical keys: exclude remapped / Move controller input
        if struct.unpack(">h", m.rd(pl + P_HP, 2))[0] <= 0:
            return None                                # terminal corpse; real solo DYING retains exactly 1 HP
        if m.rd(QTE_INPUT_TABLE, len(QTE_INPUT_SIGNATURE)) != QTE_INPUT_SIGNATURE:
            return None
        if any(m.rd(address, len(expected)) != expected for address, expected in QTE_SIGNATURES.items()):
            return None
        requests = []
        for offset in QTE_UNITS:
            unit = ab + offset
            raw = m.rd(unit, 0x1C)
            btn, mode, _, mask = struct.unpack_from(">4I", raw, 0x0C)
            if not raw[4] or not raw[5] or not ptr_ok(btn):
                continue
            button = m.rd(btn, 0x74)
            kind, button_mode, priority, index, label = struct.unpack_from(">5I", button, 0x14)
            players = struct.unpack_from(">I", button, 0x30)[0]
            if struct.unpack_from(">I", button)[0] != QTE_BUTTON_VT \
                    or struct.unpack_from(">I", button, 0x70)[0] & 1 \
                    or not button[0x0A] or button[0x0C] or not players & 1 or mode != button_mode \
                    or (mode not in QTE_MODES and mode not in QTE_STICK_MODES) or not 0 < index < len(QTE_MASKS) \
                    or mask != QTE_MASKS[index] or label > 0xFF or label == 0x3B:
                continue
            chord = ()
            if mode in QTE_STICK_MODES:
                if any(m.rd(a, len(expected)) != expected for a, expected in QTE_STICK_SIGNATURES.items()):
                    continue
                token = QTE_STICK_MODES[mode]          # these handlers read stick directions, not the digital mask
            else:
                if not mask or mask & ~QTE_ALLOWED_MASK:
                    continue
                chord = tuple(key for bit, key in QTE_KEYS if mask & bit)
                token = QTE_MODES[mode] + ":" + "+".join(chord)
            hp = struct.unpack(">h", m.rd(pl + P_HP, 2))[0]
            countdown = struct.unpack(">f", m.rd(pl + P_DYING_TIMER, 4))[0]
            if QTE_MODES.get(mode) == "mash" and chord == ("circle",) and hp == 1 \
                    and math.isfinite(countdown) and countdown > 0 \
                    and u32(m, pl + P_RECOVER_BUTTON) == btn:
                token = "mash"                         # the game's explicit SOLO_DYING_RECOVER button
            # Do not answer a selection that changed during the reads above.
            if m.rd(unit, 0x1C) != raw or m.rd(btn + 0x0A, 3) != button[0x0A:0x0D]:
                continue
            requests.append((priority, offset, {"token": token, "button": btn, "kind": kind, "mode": mode,
                                                "target": struct.unpack_from(">I", button, BTN_TARGET)[0]}))
        if u32(m, S_ACTION) != ab or u32(m, sp + 0x28) != pl:
            return None
        return min(requests, key=lambda row: (row[2]["token"] != "mash", *row[:2]))[2] if requests else None
    except (ValueError, OSError, struct.error, IndexError):
        return None


def enemy_ptrs(m) -> set:
    se = u32(m, S_ENEMY)
    if not ptr_ok(se):
        return set()
    n, arr = u32(m, se + 0x28), u32(m, se + 0x34)
    if not ptr_ok(arr) or not 0 < n <= MAX_ENEMIES:
        return set()
    return {e for e in struct.unpack(f">{n}I", m.rd(arr, 4 * n)) if ptr_ok(e)}


def prompt(m) -> str | None:
    """An explicit displayed input request, otherwise the verified grabbed-action stick escape."""
    request = selected_prompt(m)
    if request is not None:
        return request["token"]
    sp = u32(m, S_PLAYER)
    pl = u32(m, sp + 0x28) if ptr_ok(sp) else 0
    if not ptr_ok(pl):
        return None
    if m.rd(pl + P_ACTION, 1)[0] == P_GRABBED:
        return "wiggle"
    return None


def stage_prompt(m) -> bool:
    """A prompt on the stage is up (the player's own cActionButton of kind 2: a ladder, a drop, Jump over)."""
    request = selected_prompt(m)
    return bool(request and request["kind"] == BTN_STAGE and request["token"] == "mash:square")


def prompt_target(m):
    """The Majini the on-screen cActionButton acts on (+0x40), or None: who a finisher prompt is for (the combat
    layer refuses a second melee on a boss)."""
    request = selected_prompt(m)
    tgt = request["target"] if request else 0
    return tgt if ptr_ok(tgt) else None


_NAV_CACHE: dict = {}


def mesh_key(mesh) -> str:
    return getattr(mesh, "sig", None) or f"ptr-{getattr(mesh, 'ptr', 0):#x}"


def _crossings_path():
    try:
        from .. import lessons
        return lessons.ROOT / CROSSINGS_FILE
    except Exception:                                       # noqa: BLE001
        return None


def crossings(mesh) -> list:
    """The crossings the player could not take on this stage's mesh (learned live; kept per mesh signature across
    rounds and, through the lessons dir, across runs). The list is shared: Bot appends to it."""
    key = mesh_key(mesh)
    if key not in _AVOID:
        path = _crossings_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path and path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        _AVOID[key] = [tuple(q) for q in data.get(key) or []]
    return _AVOID[key]


def save_crossings() -> None:
    path = _crossings_path()
    if path is None or not _AVOID:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        data.update({k: [list(q) for q in v] for k, v in _AVOID.items()})
        path.write_text(json.dumps(data), encoding="utf-8")
    except (OSError, ValueError):
        pass


def rank_of(score) -> str | None:
    """The round's rank by RANK_SCORES, None until the thresholds are known."""
    if score is None or not RANK_SCORES:
        return None
    return next((r for r, at in RANK_SCORES if score >= at), RANK_SCORES[-1][0] if RANK_SCORES else None)


def own_screen(snap: dict) -> str:
    """playing / dead / results / loading from the round's fields: the player present with health and time left =
    playing; health 0 without RESUSCITATE = dead ("You Are Dead - Continue?"); time 0 = results; no player = loading."""
    p = snap.get("player")
    if not p:
        return "loading"
    if snap.get("prompt") == "mash" and (snap.get("timer") or 0) > 0:
        return "playing"                              # explicit RESUSCITATE prompt: HP0 is still recoverable
    if p.get("hp") is not None and p["hp"] <= 0:
        return "dead"
    if (snap.get("timer") or 0) <= 0:
        return "results"
    return "playing"


class Bot:
    """One decision per tick from the snapshot: turn to the nearest Majini with the right stick, ready the gun (L1),
    raise / lower the laser onto his head with the right stick (closed loop on the game's own aim point), fire (R1)
    inside AIM_TOL / PITCH_TOL; back off one that is too close; walk to the next one when nobody is in range.
    Reads only; presses only (gBox pad names)."""

    def __init__(self, m=None, clock=time.time, stats: dict | None = None, learn_dir=None, lessons=None):
        self.m, self.clock = m, clock
        self.stats = stats if stats is not None else {}
        self.combat = re5_combat.Combat(m, self.stats, clock=clock, learn_dir=learn_dir, lessons=lessons) \
            if m is not None and re5_combat.ENABLED else None
        for k in ("shots_s", "hits", "kills_seen", "max_combo", "turns", "backoffs", "stuck"):
            self.stats.setdefault(k, 0)
        self.target = None
        self.aiming_since = None
        self.pulse = 0
        self.hist: list = []
        self.hp_seen: dict = {}
        self.unstick_until = 0.0
        self.unstick_dir = 1
        self.dead_tap = 0.0
        self.bonus_fired: dict = {}            # hourglass -> seconds fired at it
        self.bonus_skip: dict = {}             # hourglass -> left alone until
        self.bonus_seen: set = set()
        self.last_timer = None
        self.route, self.route_for, self.route_at, self.route_since = None, None, 0.0, 0.0
        self.route_midpoints, self.route_stall, self.route_walk_at = False, None, None
        self.route_rechecks, self._following_route = 0, False
        from .. import lessons as lesson_store
        nav_path = (Path(learn_dir) if learn_dir is not None else lesson_store.ROOT) / NAV_LEARNING_FILE
        self.nav_learning = re5_nav.Learning(nav_path)
        self.nav_geometry = None
        self.avoid: list = []                  # crossings the player could not take this round (no prompt there)
        self.climb_at = None                   # (the crossing, since when) while waiting at one for its prompt
        self.climb_pos = self.climb_tick = None
        self.take_at = None                    # (the bonus, since when) while standing at one for its prompt
        self.last_punch = 0.0                  # when square was last tapped at a hourglass
        self.route_len, self.route_len_at = None, 0.0   # hourglass -> its route's length (cm), when worked out
        self.nearest_eta = None
        self.tap = 0                           # the R1 tap cycle (TAP_ON down, TAP_OFF up)
        self.spawn = None                      # where the round started: the stand
        self.at_stand = False
        self.stood = False                     # the stand has begun (every reachable bonus gathered once)
        self.plan_target = None
        self.flags: dict = {}
        self.reload_until = 0.0
        self.heal_at = -math.inf
        self.healing = None
        self.switch_at = -math.inf
        self.switch_pending = None
        self.switch_blocked, self.switch_failures = {}, {}
        self.stage_wait_since = None            # first tick a stage prompt was shown while close foes held it back
        self.stuck_since = None                 # set while the walk is pushing forward without ground (a wall, a door)
        self.close_escape_until = self.close_acquire_until = 0.0
        self.round_active = False
        self.round_end = None
        self._round_player = None
        self._observed_snap = None
        self._stick_token, self._stick_at, self._stick_step = None, 0.0, 0
        self._control_state = None
        self._round_started = None
        self._round_ended_at = None
        self._round_baseline = {}
        self._round_combo = 0
        self._sight: dict = {}                  # Majini ptr -> (when, open floor between him and the player)
        self.unsighted: dict = {}               # Majini ptr -> left out of sight until (walked to instead)
        self.engaged = None                     # [ptr, laser-up s off him, blocked since, last tick] while fought
        self.pursuit = None                     # (when chosen, ptr) of the Majini being walked to
        self.stats.setdefault("pursuits", 0)
        self.stats.setdefault("unsighted", 0)

    # --- the engine's brain interface ---
    def prompt_ok(self, button, snap, now) -> bool:
        return self.combat.prompt_ok(button, snap, now) if self.combat is not None else True

    def save(self):
        if self._control_state is not None:
            from . import re5_controls
            re5_controls.publish(self._control_state, id(self), {}, False)
        if getattr(self.m, "adapter", None) is not None:
            from ...re5_mods_tool import maintain_fire_animation
            maintain_fire_animation(self.m.adapter, enabled=False)
        save_crossings()
        self.nav_learning.save()
        if self.combat is not None:
            self.combat.save()

    def observe_round(self, snap, where, now):
        """Observe real round boundaries even when the engine handles a prompt instead of calling tick."""
        if self._observed_snap is snap:
            return
        self._observed_snap = snap
        p = snap.get("player")
        priority_prompt = snap.get("prompt") and not (self.combat is not None and self.combat.optional_prompt_blocked(snap))
        if priority_prompt or snap.get("recovery_active") or (p or {}).get("action") == P_GRABBED \
                or where != "playing" or not p:
            self._interrupt_route_walk()                   # engine-owned prompt frames may never call tick()
        if self.healing is not None and (priority_prompt or snap.get("recovery_active")
                                         or (p or {}).get("action") == P_GRABBED):
            self.healing["at"] = now           # observed mandatory interruptions pause only the bounded healing window
        if getattr(self.m, "adapter", None) is not None:
            from ...re5_mods_tool import ORIG
            from . import re5_controls
            self._control_state = ORIG.setdefault(id(self.m.adapter), {})
            re5_controls.publish(self._control_state, id(self), snap, where == "playing" and bool(p))
        if where != "playing" or snap.get("prompt") not in ("stick:rotate", "stick:x", "stick:y"):
            self._stick_token = None
        self.stats["resuscitating"] = bool(snap.get("recovery_active") or snap.get("prompt") == "mash")
        if getattr(self.m, "adapter", None) is not None:
            from ...re5_mods_tool import maintain_fire_animation
            firing = maintain_fire_animation(self.m.adapter, snap, enabled=(where == "playing"
                and not self.stats["resuscitating"] and not snap.get("prompt") and not snap.get("stage_prompt")))
            self.stats["fire_animation_active"] = bool(firing.get("active") and firing.get("verified"))
            self.stats["fire_animation_reason"] = firing.get("reason") or ""
            self.stats["fire_animation_writes"] = self.stats.get("fire_animation_writes", 0) + firing.get("writes", 0)
        if where == "playing" and p and not self.stats["resuscitating"] and getattr(self.m, "adapter", None) is not None:
            from ...re5_mods_tool import maintain_health
            health = maintain_health(self.m.adapter, snap)
            self.stats["unlimited_health_enabled"] = health.get("unlimited_health", False)
            self.stats["health_maintained"] = bool(health.get("active") and health.get("verified"))
            self.stats["hit_immunity"] = bool(health.get("hit_immunity"))
            self.stats["immunity_verified"] = bool(health.get("immunity_verified"))
            self.stats["immunity_reason"] = health.get("immunity_reason") or ""
            if health.get("refilled"):
                self.stats["health_refills"] = self.stats.get("health_refills", 0) + 1
        if where != "playing" or not p:
            self.healing = None
            if self.combat is not None:
                self.combat.awareness = []
            if where == "results":
                self._observe_result(snap)
            self.nav_learning.suspend()
            self.last_timer = None
            self.bonus_seen.clear()
            self.hp_seen.clear()
            if where in ("dead", "results"):
                if where == "dead" and self.round_end is None:
                    self.stats["deaths"] = self.stats.get("deaths", 0) + 1
                if self.round_active and self.combat is not None:
                    self.combat.observe(snap, now, active=False)
                    self.combat.end_round(now)
                self.round_active = False
                self.round_end = self.round_end or where
                self._evaluate_round(snap, now, self.round_end)
            elif self.combat is not None:
                self.combat.suspend_observation(now)
            return
        if not self.round_active:
            self._round_started = now
            self._round_ended_at = None
            self._round_baseline = {key: self.stats.get(key, 0) for key in (
                "deaths", "heals", "headshots", "finishers", "bonus_s", "bonuses_taken", "clock_jumps", "qte_presses")}
            self._round_combo = 0
            if self.round_end is not None:
                self.stats["rounds"] = self.stats.get("rounds", 0) + 1
                if self.round_end == "dead":
                    self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                self.bonus_fired.clear()
                self.bonus_skip.clear()
                self.route, self.route_for, self.route_len = None, None, None
                self.climb_at = self.take_at = None
                self.climb_pos = self.climb_tick = None
                self.spawn, self.at_stand, self.stood = None, False, False
                self.hist.clear()
                self.target = self.plan_target = self.aiming_since = None
                self.reload_until = self.unstick_until = 0.0
                self.close_escape_until = self.close_acquire_until = 0.0
                self.switch_pending = None
                self.switch_blocked.clear()
                self.switch_failures.clear()
                self.switch_at = -math.inf
                self.healing = None
                self.heal_at = -math.inf
                self._sight.clear()
                self.unsighted.clear()
                self.engaged = self.pursuit = None
            self.round_active, self.round_end = True, None
            if self.combat is not None:
                self.combat.start_round(now)
        self._round_player = p.get("ptr")
        self._round_combo = max(self._round_combo, snap.get("combo") or 0)
        if self.combat is not None:
            self.combat.observe(snap, now)
            self.combat.observe_awareness(snap, p, now)
        mesh = snap.get("nav")
        geometry = mesh.learning_sig if mesh is not None else None
        if geometry != self.nav_geometry:
            self.route, self.route_for, self.route_len = None, None, None
            self.climb_at = self.climb_pos = self.climb_tick = None
            self.nav_geometry = geometry
        self.nav_learning.observe(mesh, p["pos"], now)
        self.stats.update(self.nav_learning.summary())
        self._observe_weapon_switch(snap, now)
        self._score_hits(snap)
        t = snap.get("timer")
        if self.last_timer is not None and t is not None and self.last_timer > 0 and 2 < t - self.last_timer:
            self.stats["bonus_s"] = round(self.stats.get("bonus_s", 0.0) + t - self.last_timer, 1)
            self.stats["clock_jumps"] = self.stats.get("clock_jumps", 0) + 1
        self.last_timer = t
        standing = {b["ptr"] for b in snap.get("bonuses") or ()}
        taken = self.bonus_seen - standing
        if taken:
            self.stats["bonuses_taken"] = self.stats.get("bonuses_taken", 0) + len(taken)
        self.bonus_seen = standing
        self._evaluate_round(snap, now)

    def _evaluate_round(self, snap, now, end_reason=None):
        from . import re5_strategy
        if self._round_started is None:
            return
        observed = {key: snap.get(key) for key in ("score", "kills", "timer")}
        if end_reason:
            if self._round_ended_at is None:
                self._round_ended_at = now
            now = self._round_ended_at
            for key in ("score", "kills"):
                observed[key] = self.stats.get(key, observed[key])
        observed.update(max_combo=self._round_combo, end_reason=end_reason,
                        elapsed_s=max(0, now - self._round_started) if self._round_started is not None else None)
        for key, initial in self._round_baseline.items():
            observed[key] = max(0, self.stats.get(key, 0) - initial)
        if self.combat is not None:
            observed.update(round_shots=self.combat.round_counts["shots"], round_hits=self.combat.round_counts["hits"])
        self.stats["round_evaluation"] = re5_strategy.evaluate_round(observed)

    def _observe_result(self, snap):
        """The score can finish counting after timer0; retain only valid totals from this round's player."""
        p, timer = snap.get("player") or {}, snap.get("timer")
        if not (self.round_active or self.round_end == "results") or not self._round_player \
                or p.get("ptr") != self._round_player or not isinstance(timer, (int, float)) \
                or not math.isfinite(timer) or timer > 0:
            return
        # Result/menu teardown can clear counters before sPlayer disappears. Never replace a known total with that.
        for key in ("score", "kills"):
            value, prior = snap.get(key), self.stats.get(key)
            if type(value) is int and 0 <= value <= 0x7FFFFFFF \
                    and (not isinstance(prior, (int, float)) or value >= prior):
                self.stats[key] = value
        self.stats["timer"] = 0.0
        combo = snap.get("combo")
        if type(combo) is int and 0 <= combo <= 0x7FFFFFFF:
            self.stats["max_combo"] = max(self.stats.get("max_combo", 0), combo)
        rank = rank_of(self.stats.get("score"))
        if rank:
            self.stats["rank"] = rank
        self.stats.update(ROSTER.observe({"score": self.stats.get("score"), "kills": self.stats.get("kills"),
                                          "combo": self.stats.get("max_combo")}))

    def plan(self) -> dict:
        """What the bot is doing, for the tactical map (gbox/mercs/tactical.py): no RAM reads, only state held."""
        walking = self.route if self.stats.get("phase") in ("gather_time", "break_for_time", "stand", "pursue") else None
        nb = None
        if self.route_len:
            ptr, d = min(((k, v) for k, v in self.route_len.items() if v is not None), key=lambda kv: kv[1],
                         default=(None, None))
            if ptr is not None:
                nb = {"id": ptr, "kind": "time", "dist": round(d), "eta_s": round(d / RUN_SPEED, 1)}
        return {"phase": self.stats.get("phase"), "target": self.plan_target,
                "enemy_awareness": getattr(self.combat, "awareness", []),
                "route": [tuple(w) for w in walking] if walking else None,
                "stand": {"pos": self.spawn, "r": STAND_R} if self.spawn else None,
                "nearest_bonus": nb, "enemy_flags": dict(self.flags),
                "note": str(self.stats.get("bonus_target") or self.stats.get("aim") or "")[:80]}

    def tick(self, snap: dict) -> dict:
        self._following_route = False
        try:
            return self._tick(snap)
        finally:
            if not self._following_route:
                self._interrupt_route_walk()

    def _interrupt_route_walk(self):
        """Combat, item selection and QTE input break continuous route-motion evidence, even for a single tick."""
        if self.route_walk_at is not None:
            self.hist, self.route_stall, self.route_walk_at = [], None, None
            self.unstick_until, self.stuck_since = 0.0, None
            self.climb_at = self.climb_pos = self.climb_tick = None

    def _tick(self, snap: dict) -> dict:
        now = self.clock()
        self.observe_round(snap, own_screen(snap), now)
        p = snap.get("player")
        self.stats["max_combo"] = max(self.stats["max_combo"], snap.get("combo") or 0)
        if not p:
            return {"hold": set()}
        close_foes = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0
                     and (e.get("hp_max") or 0) > 1 and math.dist(p["pos"], e["pos"]) <= FIGHT_R
                     and (self.combat is None or self.combat.blocked_until.get(e.get("ptr", e.get("slot")), 0) <= now)]
        if self.combat is not None:                    # a Majini behind a wall of the mesh is no immediate threat
            close_foes = [e for e in close_foes if self._open(p, e, snap.get("nav"), now)]
        if snap.get("recovery_active") and not snap.get("prompt"):
            self.aiming_since = None
            return {"hold": set()}                     # wait through hidden recovery frames; no unseen circle presses
        stick_token = snap.get("prompt")
        if stick_token in ("stick:rotate", "stick:x", "stick:y"):
            self.aiming_since = None
            if self._stick_token != stick_token:
                self._stick_token, self._stick_at, self._stick_step = stick_token, now, 0
            elif stick_token == "stick:rotate" and now - self._stick_at >= QTE_STICK_STEP_S:
                # A delayed tick still moves only to the adjacent direction; neutral or skipped turns reset progress.
                self._stick_step = (self._stick_step + 1) % len(QTE_ROTATION)
                self._stick_at = now
            keys = QTE_ROTATION[self._stick_step] if stick_token == "stick:rotate" else \
                   (("lup",) if stick_token == "stick:y" else ("lleft",))
            self.stats["qte_stick"] = stick_token
            return {"hold": set(keys)}
        if prompt_chord(snap.get("prompt"), "release"):
            self.aiming_since = None
            return {"hold": set()}                     # mode2 succeeds when its requested held bits are absent
        held_prompt = prompt_chord(snap.get("prompt"), "hold")
        if held_prompt:
            self.aiming_since = None
            return {"hold": set(held_prompt)}
        if snap.get("prompt") == "mash":
            self.aiming_since = None
            return {"hold": set()}                     # the prompt presser owns rapid circle, never cross/aim/fire
        if p.get("hp") is not None and p["hp"] <= 0:        # "You Are Dead - Continue? Yes / No": Yes (cross)
            if now - self.dead_tap > 1.5:
                self.dead_tap = now
                self.stats["continue_presses"] = self.stats.get("continue_presses", 0) + 1
                return {"tap": "cross"}
            return {"hold": set()}
        if snap.get("prompt") and not (self.combat is not None and self.combat.optional_prompt_blocked(snap)):  # a finisher / a grab: the engine presses it; the gun
            self.aiming_since = None                        # stays down between its presses (L1 would cancel it)
            self.stats["prompt_holds"] = self.stats.get("prompt_holds", 0) + 1
            return {"hold": set()}
        heal = self._heal(p, snap, now)                     # equip, confirm in hand, then Square to actually use it
        if heal:
            return heal
        if snap.get("stage_prompt") and close_foes:
            self.stage_wait_since = self.stage_wait_since or now
        else:
            self.stage_wait_since = None
        stage_yield = bool(snap.get("stage_prompt") and close_foes and self.stage_wait_since is not None
                           and now - self.stage_wait_since >= STAGE_YIELD_S)
        if snap.get("stage_prompt") and (not close_foes or stage_yield):     # a ladder / jump-down / vault / door / "□ Time bonus" /
            self.aiming_since = None                        # pick up: take it at once, before anything else (operator
            self.stats["stage_presses"] = self.stats.get("stage_presses", 0) + 1   # 2026-10-21: he ignored a ledge
            self.climb_at = self.climb_pos = self.climb_tick = None
            if stage_yield:
                self.stage_wait_since = None
                self.stats["stage_yielded_to_foes"] = self.stats.get("stage_yielded_to_foes", 0) + 1
            if self.stuck_since is not None:                # and a door). A prompt while stuck = it was blocking him.
                self.stats["stuck_prompts_cleared"] = self.stats.get("stuck_prompts_cleared", 0) + 1
            return {"tap": "square"}
        if self._control_state is not None:
            from . import re5_controls
            requested = re5_controls.consume(self._control_state, id(self), snap, self._switch_weapon, now,
                                             input_allowed=not close_foes)
            if requested:
                return requested
        t = snap.get("timer")
        # Majini and the like: alive, more than 1 health (crows are "enemies" with 1), not far above or below
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1
                and abs(e["pos"][1] - p["pos"][1]) < MAX_DY]
        eq = equipped(snap)
        if eq is not None:
            self.stats["weapon"] = f"{WEAPON_NAMES.get(eq['item'], 'uWp%02x' % eq['item'])} {eq['rounds']}/{eq['cap']}" \
                if eq["type"] == 1 else f"item {eq['id']:#x}"
            if eq["type"] == 1 and eq["rounds"] == 0 and eq["cap"] == 0 and p.get("action") != P_GRABBED:
                # EMPTY 0 / 0 (Excella, live 2026-10-21: the trigger did nothing): another weapon with rounds from
                # a quick slot (the D-pad equips the edge slots)
                other = next((w for w in snap.get("inventory") or () if w["type"] == 1 and not w["hand"]
                              and w["rounds"] > 0 and re5_weapons.quick_key(w)
                              and self.switch_blocked.get(re5_weapons.inventory_key(w), 0) <= now), None)
                if other is not None:
                    change = self._switch_weapon(other, now, "empty weapon")
                    if change:
                        return change
            if eq["type"] == 1 and eq["rounds"] == 0 and eq["cap"] > 0 and p.get("action") != P_GRABBED:
                if now > self.reload_until + 2.5:           # empty: L1 + cross reloads (once, then let it play)
                    self.reload_until = now + 0.3
                    self.stats["reloads"] = self.stats.get("reloads", 0) + 1
                if now < self.reload_until:
                    return {"hold": {"l1", "cross"}}
        mesh = snap.get("nav")
        if mesh is not None and self.avoid is not _AVOID.get(mesh_key(mesh)):
            self.avoid = crossings(mesh)
        if self.spawn is None and t is not None and t >= 110:
            self.spawn = tuple(p["pos"])                    # the round's start: a defensible spot by design
        px, py, pz = p["pos"]
        self.at_stand = self.spawn is not None and math.hypot(self.spawn[0] - px, self.spawn[2] - pz) < STAND_R \
            and abs(self.spawn[1] - py) < WP_CLIMB
        # only Majini in sight are fought from here (open floor between, or right on him); the rest are walked to
        sightable = [e for e in live if math.dist(p["pos"], e["pos"]) <= SIGHT_R and self._open(p, e, mesh, now)] \
            if self.combat is not None else live
        candidate = self.combat.choose_target(snap, p, sightable, now) if self.combat is not None else None
        if candidate is None and self.combat is not None and sightable:
            candidate = min(sightable, key=lambda e: math.dist(p["pos"], e["pos"]))   # in sight, off the camera: turn
        tgt = self._bonus(p, sightable, snap.get("bonuses") or (), now, mesh, t)
        if tgt is not None:
            from . import re5_strategy
            distance = math.dist(p["pos"], tgt["pos"])
            routed = (self.route_len or {}).get(tgt["ptr"])
            eta = (routed if routed is not None else distance * 1.25) / RUN_SPEED
            decision = re5_strategy.detour_decision(snap, eta, distance < BONUS_REACH,
                kind=tgt.get("kind", "time"), immediate_threat=bool(close_foes))
            self.stats["strategy_decision"] = decision.reason
            if not decision.allowed:
                tgt = None
        if close_foes:
            tgt = None
            self.stats["phase"] = "clear_nearby"
        if tgt is not None and candidate is not None:
            at_bonus = math.hypot(tgt["pos"][0] - px, tgt["pos"][2] - pz) < BONUS_REACH \
                and abs(tgt["pos"][1] - py) < BONUS_LEVEL_DY
            if not at_bonus and math.dist(p["pos"], candidate["pos"]) <= SHOOT_RANGE \
                    and (self._threat(p, candidate) or self.combat.target_exposed):
                tgt = None                                # exposed shots / path blockers may interrupt; distant guesses may not
        threats = [e for e in sightable if self._threat(p, e)]
        self.flags = {e["slot"]: ["blocking"] for e in threats}
        if tgt is None and candidate is None and live and self.combat is not None:
            chase = self._pursuit_target(p, live, mesh, now)     # nobody in sight: go to them, never wait at a wall
            if chase is not None:
                return self._pursue(p, chase, mesh, snap.get("stage_prompt"), now)
        if tgt is None and not threats and candidate is None and self.spawn is not None and not self.at_stand:
            self.stats["phase"] = "stand"                   # the bonuses gathered: back to the stand
            self.stood = True
            self.plan_target = {"kind": "stand", "id": "spawn", "pos": self.spawn}
            self.aiming_since = None
            return self._follow(p, {"ptr": "stand", "pos": self.spawn}, mesh, snap.get("stage_prompt"), now)
        if tgt is None and not live:
            self.aiming_since = None
            self.stats["phase"] = "stand" if self.at_stand else "idle"
            self.stood = self.stood or self.at_stand
            self.plan_target = None
            return {"hold": set()}
        if tgt is None:
            self.stats["phase"] = "clear_nearby" if close_foes else "fight" if threats or not self.at_stand else "stand"
        if tgt is None and self.combat is not None:
            if candidate is None:
                return self.combat.seek_target(snap, p, live, now)
            tgt = candidate                               # existing finisher prompts still win before this decision
        tgt = tgt or min(threats or live, key=lambda e: self._cost(p, e))
        self.plan_target = {"kind": tgt.get("kind", "enemy") if "ptr" in tgt else "enemy",
                            "id": tgt.get("ptr") if tgt.get("kind") in ("time", "combo") else tgt.get("slot"),
                            "pos": tgt["pos"]}
        aim_h = tgt.get("aim_h", HEAD_H)
        tx, ty, tz = tgt["pos"]
        dist = math.hypot(tx - px, tz - pz)
        want = heading(tx - px, tz - pz)
        if tgt.get("kind") in ("time", "combo"):            # a time bonus: walked to, taken with its prompt
            self.aiming_since, self.target = None, tgt["slot"]
            if tgt.get("walk"):
                return self._follow(p, tgt, snap.get("nav"), snap.get("stage_prompt"), now)
            return self._take(p, tgt, snap.get("stage_prompt"), now)
        if dist > ENGAGE:                                   # nobody near: walk toward the nearest...
            self.aiming_since = None
            if self.at_stand:                               # ...unless this is the stand: they come to him
                return {"hold": set()}
            return {"hold": self._walk(p, want, now)}
        aiming = p.get("action") == 2
        if dist < TOO_CLOSE and not aiming and self.combat is None:
            if now >= self.close_acquire_until:
                self.close_escape_until = now + CLOSE_ESCAPE_S
                self.close_acquire_until = self.close_escape_until + CLOSE_ACQUIRE_S
                self.stats["backoffs"] += 1
            if now < self.close_escape_until:
                self.aiming_since = None
                return {"hold": {"ldown"} | self._turn(wrap(want - p["rot"]), aiming=False)}
            # A stationary nearby attacker must not keep the gun down indefinitely.
        else:
            self.close_escape_until = self.close_acquire_until = 0.0
        if self.combat is not None and tgt.get("kind") not in ("time", "combo"):   # the combat layer owns the fight
            if self._lost_sight(snap, p, tgt, now):        # the dot stops short of him / never reaches him: go there
                chase = self._pursuit_target(p, live, mesh, now)
                if chase is not None:
                    return self._pursue(p, chase, mesh, snap.get("stage_prompt"), now)
            from . import re5_controls
            if self.switch_pending is None and now - self.switch_at > SWITCH_EVERY_S \
                    and (not close_foes or eq is None or not re5_controls.eligible(eq)) \
                    and not re5_controls.pinned(self._control_state or {}, snap, now):
                blocked = {key for key, until in self.switch_blocked.items() if until > now}
                other = re5_weapons.best_quick_slot(snap, tgt, blocked)
                if other is not None:
                    change = self._switch_weapon(other, now, "range/crowd/boss fit")
                    if change:
                        return change
            self.target = tgt["slot"]
            return self.combat.tick(snap, p, tgt, now, observed=True)
        if not aiming:
            err = wrap(want - p["rot"])
            if abs(err) > TURN_TOL:                         # turn round first (fast, not aiming)
                self.aiming_since = None
                self.stats["turns"] += 1
                return {"hold": self._turn(err, aiming=False)}
            self.aiming_since = self.aiming_since or now
            return {"hold": {"l1"}}                         # ready the gun; the aim pose comes up
        # aiming: close the loop on the crosshair - the camera's look ray (over the shoulder, along the aim) - onto
        # his head; without a camera, on the body's heading and the player's own pitch value
        cam = snap.get("camera")
        if cam:
            (ex, ey, ez), (cx, cy, cz) = cam["eye"], cam["at"]
            look_yaw = heading(cx - ex, cz - ez)
            look_pitch = math.atan2(cy - ey, max(math.hypot(cx - ex, cz - ez), 1e-3))
            tgt_pitch = math.atan2(ty + aim_h - ey, max(math.hypot(tx - ex, tz - ez), 1.0))
            yaw_err = wrap(heading(tx - ex, tz - ez) - look_yaw)
            pitch_err = tgt_pitch - look_pitch
            sight = math.dist((ex, ey, ez), (tx, ty + aim_h, tz))       # the crosshair's distance to it
        else:
            tgt_pitch = math.atan2(ty + aim_h - (py + GUN_H), max(dist, 1.0))
            yaw_err = wrap(want - p["rot"])
            pitch_err = tgt_pitch - (p.get("pitch") or 0.0)
            sight = dist
        if tgt.get("kind") == "time" and tgt_pitch < BONUS_STEEP:   # right on top of it: out of the aim's reach
            self.aiming_since = None
            return {"hold": {"ldown"} | self._turn(wrap(want - p["rot"]), aiming=False)}
        tol = max(AIM_TOL, math.atan2(BODY_R, max(dist, 1.0)))   # close up the body is wide
        ptol = max(PITCH_TOL * 2, tol)                      # a body is tall
        if tgt.get("kind") == "time":                       # an hourglass (25 cm on the ground): the crosshair
            tol = ptol = max(math.radians(0.4),             # inside half its radius, seen from the camera
                             math.atan2(0.5 * (tgt.get("r") or 25.0), max(sight, 1.0)))
        keys = {"l1"} | self._turn(yaw_err, aiming=True, tol=min(AIM_TOL, 0.7 * tol))
        if abs(pitch_err) > min(PITCH_TOL, 0.7 * ptol):    # corrected inside the shot's own tolerance
            close = abs(pitch_err) < FINE
            self.pulse ^= 1
            if not close or self.pulse:
                keys.add("rup" if pitch_err > 0 else "rdown")
        if abs(yaw_err) <= tol and abs(pitch_err) <= ptol and dist <= SHOOT_RANGE:
            tap, self.tap = self.tap, (self.tap + 1) % (TAP_ON + TAP_OFF)
            auto = eq is not None and eq.get("type") == 1 and (eq.get("item") in HOLD_FIRE or (eq.get("cap") or 0) >= HOLD_CAP)
            if auto or tap < TAP_ON:
                keys.add("r1")                              # on him: fire (held for the Gatling, a press for the rest:
            self.stats["shots_s"] = round(self.stats["shots_s"] + 0.05, 2)   # a held R1 fires a handgun once)
            if tgt.get("kind") == "time":
                fired = self.bonus_fired[tgt["ptr"]] = self.bonus_fired.get(tgt["ptr"], 0.0) + 0.05
                if fired > BONUS_GIVE_UP_S:                 # shots don't take it from here (a wall, its kind)
                    self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
                    self.bonus_fired[tgt["ptr"]] = 0.0
        self.target = tgt["slot"]
        self.stats["aim"] = (f"slot {tgt['slot']} d {dist:.0f} dy {ty - py:+.0f} yaw_err {math.degrees(yaw_err):+.1f} "
                             f"pitch {math.degrees(p.get('pitch') or 0):+.1f} want {math.degrees(tgt_pitch):+.1f} "
                             f"keys {','.join(sorted(keys))}")
        return {"hold": keys}

    # --- sight and pursuit ---
    def _open(self, p, e, mesh, now) -> bool:
        """Whether a Majini may be fought from where the player stands: right on him (PURSUE_NEAR), or open floor
        between them on the navmesh (no wall of the mesh in between; no mesh: assumed open), and not left out of sight
        by _lost_sight a moment ago."""
        key = e.get("ptr", e.get("slot"))
        if math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2]) < PURSUE_NEAR:
            return True
        if self.unsighted.get(key, 0.0) > now:
            return False
        if mesh is None:
            return True
        hit = self._sight.get(key)
        if hit is not None and now - hit[0] < SIGHT_CACHE_S:
            return hit[1]
        try:
            ok = bool(mesh.floor_segment(p["pos"], e["pos"]))
            if not ok:                                      # floor_segment is strict (unlinked faces, slopes: live, 4 of
                flat = math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])   # 5 nearly straight routes
                length = mesh.route_length(p["pos"], e["pos"], avoid=self.avoid)        # were "closed"): a route
                ok = length is not None and length <= SIGHT_BEND * flat + SIGHT_SLACK   # that barely bends is open
        except Exception:                                   # noqa: BLE001 - an odd triangle never blinds the fight
            ok = True
        if len(self._sight) > 256:
            self._sight.clear()
        self._sight[key] = (now, ok)
        return ok

    @staticmethod
    def _laser_view(snap, tgt) -> str | None:
        """What the laser says about him: "on" (the dot on him), "wall" (the dot at the muzzle), "short" (the dot well
        short of him, roughly toward him: something in between), "none" (no laser: the gun is not up), None (no
        evidence either way)."""
        lz = snap.get("laser")
        if not lz or not lz.get("from") or not lz.get("at") or not any(lz["from"]):
            return "none"
        origin, dot = lz["from"], lz["at"]
        if re5_combat.dot_on(dot, tgt["pos"]) is not None:
            return "on"
        length = math.dist(origin, dot)
        if length < WALL_R:
            return "wall"
        centre = (tgt["pos"][0], tgt["pos"][1] + 110.0, tgt["pos"][2])
        err = abs(wrap(heading(dot[0] - origin[0], dot[2] - origin[2])
                       - heading(centre[0] - origin[0], centre[2] - origin[2])))
        if err < math.radians(20) and length < math.dist(origin, centre) - VIEW_SHORT:
            return "short"
        return None

    def _lost_sight(self, snap, p, tgt, now) -> bool:
        """The Majini being fought is not in sight after all: the dot stopped short of him (or at a wall) for
        BLOCKED_VIEW_S, or the laser was up UNSIGHTED_S without the dot reaching him (time without a laser does not
        count: the gun coming up). He is then left out of sight for PURSUE_S (walked to)."""
        key = tgt.get("ptr", tgt.get("slot"))
        if key is None or math.hypot(tgt["pos"][0] - p["pos"][0], tgt["pos"][2] - p["pos"][2]) < PURSUE_NEAR:
            self.engaged = None
            return False
        if self.engaged is None or self.engaged[0] != key:
            self.engaged = [key, 0.0, None, now]           # him, laser-up seconds off him, blocked since, last tick
        dt = max(0.0, min(0.5, now - self.engaged[3]))
        self.engaged[3] = now
        view = self._laser_view(snap, tgt)
        if view == "on":
            self.engaged[1], self.engaged[2] = 0.0, None
            return False
        if view != "none":
            self.engaged[1] += dt
        if view in ("wall", "short"):
            self.engaged[2] = self.engaged[2] if self.engaged[2] is not None else now
        else:
            self.engaged[2] = None
        blocked = self.engaged[2] is not None and now - self.engaged[2] >= BLOCKED_VIEW_S
        if not blocked and self.engaged[1] < UNSIGHTED_S:
            return False
        self.unsighted[key] = now + PURSUE_S
        self._sight.pop(key, None)
        self.engaged = None
        self.stats["unsighted"] += 1
        self.stats["sight"] = f"dot {view} of him {BLOCKED_VIEW_S:g}s" if blocked else \
            f"dot never on him in {UNSIGHTED_S:g}s"
        return True

    def _pursuit_target(self, p, live, mesh, now):
        """The Majini to walk to: the shortest navmesh route among the six nearest (chosen again every
        PURSUE_PICK_S); one whose route failed lately is skipped. None: nobody reachable."""
        if self.pursuit is not None and now - self.pursuit[0] < PURSUE_PICK_S:
            e = next((e for e in live if e.get("ptr", e.get("slot")) == self.pursuit[1]), None)
            if e is not None and self.bonus_skip.get(("enemy", self.pursuit[1]), 0.0) <= now:
                return e
        best, best_d = None, math.inf
        for e in sorted(live, key=lambda e: math.dist(p["pos"], e["pos"]))[:6]:
            key = e.get("ptr", e.get("slot"))
            if self.bonus_skip.get(("enemy", key), 0.0) > now:
                continue
            if mesh is None:
                d = math.dist(p["pos"], e["pos"])
            else:
                try:
                    d = mesh.route_length(p["pos"], e["pos"], avoid=self.avoid)
                except Exception:                           # noqa: BLE001
                    d = None
            if d is not None and d < best_d:
                best, best_d = e, d
        self.pursuit = (now, best.get("ptr", best.get("slot"))) if best is not None else None
        return best

    def _pursue(self, p, e, mesh, stage_prompt, now) -> dict:
        """Walk to a Majini out of sight along the navmesh (the gun down, running), the way time bonuses are walked
        to: around walls, up ladders and down drops; he is fought once in sight."""
        self.stats["phase"] = "pursue"
        self.aiming_since = None
        self.target = e.get("slot")
        self.plan_target = {"kind": "enemy", "id": e.get("slot"), "pos": e["pos"]}
        key = ("enemy", e.get("ptr", e.get("slot")))
        if self.route_for != key:
            self.stats["pursuits"] += 1
        if mesh is None:
            return {"hold": self._walk(p, heading(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2]), now)}
        return self._follow(p, {"ptr": key, "pos": e["pos"]}, mesh, stage_prompt, now, learn=False)

    # --- helpers ---
    def _observe_weapon_switch(self, snap, now):
        pending = self.switch_pending
        if pending is None or not snap.get("inventory"):
            return
        wanted, started = pending
        current = equipped(snap)
        if current is not None and re5_weapons.inventory_key(current) == wanted:
            self.stats["weapon_switches"] = self.stats.get("weapon_switches", 0) + 1
            self.stats["weapon_switch_status"] = "confirmed in hand"
            self.switch_pending = None
            self.switch_failures.pop(wanted, None)
            self.switch_blocked.pop(wanted, None)
        elif now - started >= SWITCH_ACK_S:
            count = self.switch_failures[wanted] = self.switch_failures.get(wanted, 0) + 1
            cooldown = min(60.0, SWITCH_FAIL_S * 2 ** min(count - 1, 3))
            self.switch_blocked[wanted] = now + cooldown
            self.stats["weapon_switch_failures"] = self.stats.get("weapon_switch_failures", 0) + 1
            self.stats["weapon_switch_status"] = f"unconfirmed; grid {wanted[1]} waits {cooldown:g}s"
            self.switch_pending = None

    def _switch_weapon(self, item, now, why):
        key, identity = re5_weapons.quick_key(item), re5_weapons.inventory_key(item)
        if not key or self.switch_pending is not None or now - self.switch_at <= SWITCH_EVERY_S \
                or self.switch_blocked.get(identity, 0) > now:
            return None
        self.switch_at, self.switch_pending = now, (identity, now)
        self.stats["weapon_switch_attempts"] = self.stats.get("weapon_switch_attempts", 0) + 1
        self.stats["weapon_switch_status"] = f"waiting for grid {item['grid']} in hand"
        weapon = re5_weapons.WEAPONS.get(item.get("item"))
        self.stats["weapon_policy"] = f"switch to {weapon.name if weapon else 'loaded weapon'}: {why}"
        return {"tap": key}

    def _bonus(self, p, live, standing, now, mesh=None, clock=None):
        """The time bonus to go for now, or None (nothing standing, or a Majini within FIGHT_R: he is fought first).
        The nearest hourglass by the navmesh route (straight line without a mesh), on any level, walked to along the
        route and taken with its "□ Time bonus" prompt (Bot._take); one left alone for BONUS_SKIP_S when its prompt
        did not come or its route led nowhere."""
        px, py, pz = p["pos"]
        now_ptrs = {b["ptr"] for b in standing}
        standing = [b for b in standing if self.bonus_skip.get(b["ptr"], 0.0) <= now]
        if not standing or not BONUS_HUNT:
            self.stats["bonus_target"] = None
            return None
        # about to take one (right on it, on its level): finish the square press even with a Majini near - it is quick
        near = min(standing, key=lambda b: math.hypot(b["pos"][0] - px, b["pos"][2] - pz))
        at_bonus = math.hypot(near["pos"][0] - px, near["pos"][2] - pz) < BONUS_REACH \
            and abs(near["pos"][1] - py) < BONUS_LEVEL_DY
        if not at_bonus and any(self._threat(p, e) for e in live):
            self.stats["phase"] = "fight"
            return None
        if mesh is not None and (self.route_len is None or now - self.route_len_at > ROUTE_LEN_S
                                 or set(self.route_len) != now_ptrs):
            self.route_len, self.route_len_at = {}, now
            for b in standing:
                self.route_len[b["ptr"]] = mesh.route_length(p["pos"], b["pos"], avoid=self.avoid)

        def cost(b):
            d = self.route_len.get(b["ptr"]) if self.route_len else None
            if d is None:                                   # no route (yet): straight line, after the routed ones
                d = 2.0 * math.hypot(b["pos"][0] - px, b["pos"][2] - pz) + 5000.0
            return d
        self.stats["unreachable_bonuses"] = sum(1 for b in standing if mesh is not None
                                               and self.route_len.get(b["ptr"]) is None)
        cands = [b for b in standing if cost(b) < BONUS_RANGE
                 and (mesh is None or self.route_len.get(b["ptr"]) is not None)]
        if not cands:
            self.stats["bonus_target"] = None
            return None
        b = min(cands, key=lambda b: cost(b) +
                (self.nav_learning.route_penalty(mesh, p["pos"], b["pos"]) if mesh is not None else 0.0))
        d = math.hypot(b["pos"][0] - px, b["pos"][2] - pz)
        level = abs(b["pos"][1] - py) < BONUS_LEVEL_DY          # on its level, right at it: take it
        walk = d > BONUS_TAKE or not level
        if walk and not BONUS_WALK:
            return None
        self.nearest_eta = cost(b) / RUN_SPEED
        self.stats["nearest_eta_s"] = round(self.nearest_eta, 1)
        # Gather first, always: every reachable bonus is taken before the stand (operator 2026-10-21: movement first,
        # "navigate around the level completing time bonuses"). break_for_time = a bonus grabbed after the stand began.
        self.stats["phase"] = "break_for_time" if self.stood else "gather_time"
        self.stats["bonus_target"] = f"{b['ptr']:#x} d {d:.0f} route {cost(b):.0f}" + (" walk" if walk else " take")
        return {"slot": f"bonus {b['ptr']:#x}", "ptr": b["ptr"], "pos": b["pos"], "aim_h": 0.0, "r": b.get("r"),
                "kind": b.get("kind", "time"), "walk": walk}

    @staticmethod
    def _threat(p, e) -> bool:
        """A Majini worth stopping for: within FIGHT_R and in front (he blocks the way), or right on top of him."""
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        if d < ON_TOP_R:
            return True
        off = abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
        return d < FIGHT_R and off < FIGHT_CONE

    def _heal(self, p, snap, now):
        """D-pad equips; Square uses the confirmed recovery item (Capcom PS3 manual, Actions pp16–17).

        https://static.capcom.com/manuals/re5/RE5_PS3_DMNL_EN.pdf
        Keep combat from switching it away between these two actions. Attempts are bounded and are not heals.
        """
        inv = snap.get("inventory") or ()
        items = [s for s in inv if s["type"] != 1]
        if items:
            self.stats["items"] = ", ".join(f"{s['id']:#x}x{s['rounds']}@{s['slot']}" for s in items)
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        if hp_max <= 0 or hp <= 1 or snap.get("recovery_active") or p.get("action") == P_GRABBED:
            return None
        state, eq = self.healing, equipped(snap)
        if state is not None:
            if state["player"] != p.get("ptr"):
                self.healing = None
                return None
            item = next((s for s in items if re5_weapons.inventory_key(s) == state["key"]), None)
            # Grid/storage relocation is not consumption. Compare all records of the same item ID.
            count = sum(s.get("rounds", 0) for s in items if s.get("id") == state["id"])
            consumed = bool(inv) and count < state["count"]
            if state["uses"] and consumed:
                self.stats["heal_items_used"] = self.stats.get("heal_items_used", 0) + 1
                if hp > state["hp"]:
                    self.stats["heals"] = self.stats.get("heals", 0) + 1
                self.stats["heal_status"] = "item consumption observed" + ("; HP increased" if hp > state["hp"] else "; HP gain unconfirmed")
                self.healing, self.heal_at = None, now
                return self._heal_return_weapon(inv, state, now)
            if hp > HEAL_AT * hp_max:
                self.stats["heal_status"] = "health recovered; item use not confirmed"
                self.healing, self.heal_at = None, now
                return self._heal_return_weapon(inv, state, now)
            if now - state["at"] >= HEAL_ATTEMPT_S or state["uses"] >= 12:
                self.stats["heal_failures"] = self.stats.get("heal_failures", 0) + 1
                self.stats["heal_status"] = "use unconfirmed; bounded retry"
                self.healing, self.heal_at = None, now
                return self._heal_return_weapon(inv, state, now)
            if item is None or not item.get("rounds"):
                self.healing, self.heal_at = None, now
                self.stats["heal_status"] = "selected item unavailable"
                return self._heal_return_weapon(inv, state, now)
            self.stats["phase"] = "healing"
            if item.get("hand"):
                if now - state["last_use"] >= HEAL_USE_EVERY_S:
                    state["last_use"], state["uses"] = now, state["uses"] + 1
                    self.stats["heal_use_presses"] = self.stats.get("heal_use_presses", 0) + 1
                    self.stats["heal_status"] = "Square use; awaiting consumption and HP"
                    return {"tap": "square"}
                return {"hold": set()}             # do not raise the gun or switch away while use is pending
            if now - state["equip_at"] >= SWITCH_ACK_S and state["equips"] < 2:
                key = re5_weapons.quick_key(item)
                if key:
                    state["equip_at"], state["equips"] = now, state["equips"] + 1
                    self.stats["heal_equip_attempts"] = self.stats.get("heal_equip_attempts", 0) + 1
                    return {"tap": key}
            self.stats["heal_status"] = "awaiting recovery item in hand"
            return {"hold": set()}
        if hp > HEAL_AT * hp_max or now - self.heal_at < HEAL_RETRY_S:
            return None
        heals = [s for s in items if s["id"] in HEAL_IDS and s.get("rounds", 0) > 0]
        if not heals:
            return None
        quick = next((s for s in heals if s.get("hand")), None) or next((s for s in heals if re5_weapons.quick_key(s)), None)
        if quick is None:
            self.stats["heal_out_of_reach"] = heals[0]["slot"]
            return None
        self.switch_pending = None                 # emergency healing owns selection until this bounded sequence ends
        self.healing = {"key": re5_weapons.inventory_key(quick), "player": p.get("ptr"), "id": quick["id"],
                        "count": sum(s.get("rounds", 0) for s in items if s.get("id") == quick["id"]),
                        "hp": hp, "at": now, "last_use": -math.inf, "uses": 0,
                        "equip_at": now, "equips": 0 if quick.get("hand") else 1,
                        "return": re5_weapons.inventory_key(eq) if eq and eq.get("type") == 1 else None}
        self.stats["phase"] = "healing"
        if quick.get("hand"):
            return self._heal(p, snap, now)          # the screenshot's already-held spray needs Square, not another D-pad
        self.stats["heal_equip_attempts"] = self.stats.get("heal_equip_attempts", 0) + 1
        self.stats["heal_status"] = "equipping recovery item"
        return {"tap": re5_weapons.quick_key(quick)}

    def _heal_return_weapon(self, inv, state, now):
        guns = [s for s in inv if s.get("type") == 1 and s.get("rounds", 0) > 0 and re5_weapons.quick_key(s)
                and (re5_weapons.WEAPONS.get(s.get("item")) is not None)
                and re5_weapons.WEAPONS[s["item"]].family in re5_weapons.DIRECT]
        gun = next((s for s in guns if re5_weapons.inventory_key(s) == state["return"]), None) or next(iter(guns), None)
        if gun is not None and not gun.get("hand"):
            return self._switch_weapon(gun, now, "resume after healing")
        return None

    def _take(self, p, tgt, stage_prompt, now) -> dict:
        """At a time bonus: walk onto it, then tap square to punch it. The "□ Time bonus" prompt is not the kind-2
        cActionButton the ladders use (the bot stood on a hourglass with stage_prompt False, live 2026-10-21), so the
        press is blind: within BONUS_PUNCH_R, facing it, release every direction and tap square on a cadence; the
        unit leaving the OM line is observed by observe_round. Given up after BONUS_GIVE_UP_S of tapping."""
        pos = p["pos"]
        flat = math.hypot(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2])
        err = wrap(heading(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]) - p["rot"])
        if stage_prompt or (flat < BONUS_PUNCH_R and abs(err) < math.radians(45)):
            if self.take_at is None or self.take_at[0] != tgt["ptr"]:
                self.take_at = (tgt["ptr"], now)
            elif now - self.take_at[1] > BONUS_GIVE_UP_S:   # tapped a while, still here: leave it, try later
                self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
                self.take_at = None
                return {"hold": set()}
            if now - self.last_punch < BONUS_PUNCH_S:       # let the last tap land (the engine spaces a tap itself)
                return {"hold": set()}
            self.last_punch = now
            self.stats["bonus_presses"] = self.stats.get("bonus_presses", 0) + 1
            return {"tap": "square"}                        # release all, punch
        keys = self._turn(err, aiming=False)
        if flat > 50.0 and abs(err) < math.radians(40):
            keys = keys | {"lup"}                           # walk onto it (not running: it would overshoot)
        return {"hold": keys}

    def _follow(self, p, tgt, mesh, stage_prompt, now, learn=True) -> dict:
        """One step along the navmesh to a time bonus: the route drawn again every REPLAN_S; the next waypoint walked
        to (turn, then run); at a ladder or a drop (the next waypoint straight above / below) the stage's square
        prompt is taken; a bonus followed ROUTE_STALE_S without being reached is left for BONUS_SKIP_S."""
        self._following_route, self._route_learn = True, learn
        pos = p["pos"]
        if self.route_for != tgt["ptr"]:
            if learn:                                      # enemy pursuits are not route learning
                self.nav_learning.begin_route(mesh, pos, tgt["pos"])
            else:
                self.nav_learning.finish_route("interrupted")
            self.route, self.route_for, self.route_since = None, tgt["ptr"], now
            self.route_at = -math.inf
            self.climb_at = self.climb_pos = self.climb_tick = None
            self.route_midpoints, self.route_stall, self.route_walk_at = False, None, None
            self.route_rechecks = 0
        if self.route_walk_at is None or now - self.route_walk_at > 1.0:
            self.hist, self.route_stall = [], None           # combat / a prompt is not stationary walking evidence
            self.unstick_until = 0.0
        self.route_walk_at = now
        if self.route_stall is not None and math.dist(pos, self.route_stall) >= STUCK_MOVE:
            self.route_stall = None
        if now - self.route_since > ROUTE_STALE_S:
            self._nav_finish("timed_out")
            self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
            self.stats["routes_given_up"] = self.stats.get("routes_given_up", 0) + 1
            self.route_for = None
            return {"hold": set()}
        if mesh is not None and now - self.route_at > REPLAN_S:
            self.route, self.route_at = mesh.route(pos, tgt["pos"], avoid=self.avoid,
                                                   pull=not self.route_midpoints), now
        if not self.route:
            if mesh is not None:                           # an explicit no-route result must never mean run through it
                self._nav_finish("unreachable")
                self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
                self.stats["route"] = "unreachable on current mesh"
                return {"hold": set()}
            return {"hold": self._walk(p, heading(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]), now)}
        while len(self.route) > 1 and math.hypot(self.route[0][0] - pos[0], self.route[0][2] - pos[2]) < WP_REACHED \
                and abs(self.route[0][1] - pos[1]) < WP_CLIMB:
            following = self.route[1]
            if abs(following[1] - pos[1]) < WP_CLIMB:
                if mesh is not None and not mesh.floor_segment(pos, following):
                    break                                 # being near a corner does not permit cutting across its wall
            elif math.hypot(self.route[0][0] - pos[0], self.route[0][2] - pos[2]) > 20.0:
                break                                     # reach the action link's approach before advancing to its height
            self.route.pop(0)
        w = self.route[0]
        flat = math.hypot(w[0] - pos[0], w[2] - pos[2])
        self.stats["route"] = f"{len(self.route)} wp, next d {flat:.0f} dy {w[1] - pos[1]:+.0f}"
        if flat < WP_CLIMB and abs(w[1] - pos[1]) >= WP_CLIMB:  # a ladder / a drop: the game's own action
            if stage_prompt:
                self.stats["climbs"] = self.stats.get("climbs", 0) + 1
                self.climb_at = self.climb_pos = self.climb_tick = None
                return {"tap": "square"}
            beyond = next((v for v in self.route[1:] if math.hypot(v[0] - w[0], v[2] - w[2]) > 50.0), None)
            way = heading(beyond[0] - pos[0], beyond[2] - pos[2]) if beyond else heading(w[0] - pos[0], w[2] - pos[2])
            err = wrap(way - p["rot"])
            if abs(err) > math.radians(25):                 # face the way down first: the prompt wants it
                self.climb_at = self.climb_pos = self.climb_tick = None
                return {"hold": self._turn(err, aiming=False)}
            if self.climb_at is None or math.dist(self.climb_at[0], w) > 60.0 \
                    or self.climb_tick is None or now - self.climb_tick > 1.0 \
                    or self.climb_pos is None or math.dist(pos, self.climb_pos) > 20.0:
                self.climb_at, self.climb_pos = (w, now), tuple(pos)
            elif now - self.climb_at[1] > CLIMB_WAIT_S:        # continuous aligned approach, without motion or prompt
                self._nav_finish("blocked")
                self.avoid.append(w)
                self.stats["crossings_avoided"] = self.stats.get("crossings_avoided", 0) + 1
                self.climb_at, self.route, self.route_len = None, None, None
                self.climb_pos = self.climb_tick = None
                return {"hold": set()}
            self.climb_tick = now
            return {"hold": {"lup"}}                        # on to the edge until the prompt shows
        self.climb_at = self.climb_pos = self.climb_tick = None
        if mesh is not None and not mesh.floor_segment(pos, w):
            # A funnel path or stale position that cannot be justified by the current floor must not drive ahead.
            # Edge midpoints stay inside the original triangle corridor; the next tick checks those too.
            self.route_rechecks += 1
            if self.route_rechecks >= 3:
                return self._block_route(tgt, now, "no supported floor segment after three route checks")
            self.route_midpoints = True
            self.route = mesh.route(pos, tgt["pos"], avoid=self.avoid, pull=False)
            self.route_at, self.hist = now, []
            self.stats["route"] = "rechecking route through recorded portals"
            return {"hold": set()}
        self.route_rechecks = 0
        stuck = self.stats["stuck"]
        keys = self._walk(p, heading(w[0] - pos[0], w[2] - pos[2]), now, precise=True, run=flat >= WP_REACHED)
        if self.stats["stuck"] > stuck:
            if self.route_stall is not None:
                return self._block_route(tgt, now, "repeated stationary approach; trying another target")
            self.route_stall = tuple(pos)
            self.route_midpoints, self.route_at = True, -math.inf
        return {"hold": keys}

    def _nav_finish(self, outcome):
        if getattr(self, "_route_learn", True):          # a pursuit's route outcome is not the stage's route record
            self.nav_learning.finish_route(outcome)

    def _block_route(self, tgt, now, reason):
        self._nav_finish("blocked")
        self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
        self.stats["routes_blocked"] = self.stats.get("routes_blocked", 0) + 1
        self.stats["route"] = reason
        self.route = self.route_for = self.route_len = None
        self._interrupt_route_walk()
        return {"hold": set()}

    @staticmethod
    def _cost(p, e) -> float:
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        off = abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
        return d * (1.0 + off / math.pi)                    # near and in front first

    def _turn(self, err: float, aiming: bool, tol: float | None = None) -> set:
        tol = tol if tol is not None else (AIM_TOL if aiming else TURN_TOL)
        if abs(err) <= tol:
            return set()
        if abs(err) < FINE:                                 # close: pulse, no overshoot
            self.pulse ^= 1
            if not self.pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}         # left = larger heading (measured)

    def _walk(self, p, want: float, now: float, *, precise=False, run=True) -> set:
        """Run toward a heading: turn first (the body turns in place), run (up + cross) once within 60 deg. Stuck
        (pushing forward STUCK_S without STUCK_MOVE of ground): a step back and aside for 0.8 s. Turning in place
        is never "stuck" (live 2026-10-21: it was, and the walk thrashed)."""
        if not precise:
            self._interrupt_route_walk()                   # a non-route pursuit must not inherit route stall samples
        px, py, pz = p["pos"]
        if now < self.unstick_until:
            return {"ldown", "lleft" if self.unstick_dir > 0 else "lright"}
        err = wrap(want - p["rot"])
        keys = self._turn(err, aiming=False)
        if abs(err) > (TURN_TOL if precise else math.radians(60)):
            self.hist = []
            return keys
        keys |= {"lup", "cross"} if run else {"lup"}         # walk into a nearby corner instead of overshooting it
        self.hist = [h for h in self.hist if now - h[0] < STUCK_S + 0.3] + [(now, px, pz)]
        if now - self.hist[0][0] >= STUCK_S and math.hypot(px - self.hist[0][1], pz - self.hist[0][2]) < STUCK_MOVE:
            self.stuck_since = self.stuck_since or now       # pushing forward against something (a wall, a door)
            self.hist, self.unstick_dir = [], -self.unstick_dir
            self.unstick_until = now + 0.8
            self.stats["stuck"] += 1
            return {"ldown", "lleft" if self.unstick_dir > 0 else "lright"}
        else:
            self.stuck_since = None
        return keys

    def _score_hits(self, snap):
        for e in snap.get("enemies") or ():
            prev = self.hp_seen.get(e["ptr"])
            if prev is not None and e["hp"] < prev:
                self.stats["damage_events"] = self.stats.get("damage_events", 0) + 1
                if self.combat is None:
                    self.stats["hits"] += 1
                if e["hp"] <= 0 < prev:
                    self.stats["kills_seen"] += 1
            self.hp_seen[e["ptr"]] = e["hp"]


HANG_S = 60.0                          # a round's clock standing still this long: the emulator hung (RPCS3 on
                                       # arm64 froze mid-round, live 2026-10-21) - the round is given up as lost


class RE5PS3(Driver):
    map_id = "BLUS30491"

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._timer = (None, 0.0)              # the round's clock and when it last moved
        self._wiggle_step = 0

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def recovery_active(self, m) -> bool:
        return recovery_active(m)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        where = own_screen(snap)
        if where == "playing" and (snap.get("prompt") == "mash" or snap.get("recovery_active")):
            self._timer = (snap.get("timer"), self.clock())
        elif where == "playing":
            now, t = self.clock(), snap.get("timer")
            if t != self._timer[0]:
                self._timer = (t, now)
            elif now - self._timer[1] > HANG_S:
                return "loading"                            # frozen: the engine calls it lost (its LOST_S later)
        return where

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(m, clock=clock, stats=stats, learn_dir=learn_dir)

    def prompt_source(self, m, stats: dict):
        self._stats = stats
        def source():
            button = prompt(m)
            if button == "mash:square":
                request = selected_prompt(m)
                if request and request["token"] == button and request["kind"] == BTN_MELEE and request["mode"] == 1:
                    return "square"                    # ordinary finisher: preserve attack timing and boss limit
            return None if prompt_chord(button, "hold") or prompt_chord(button, "release") \
                or button in ("stick:rotate", "stick:x", "stick:y") else button
        return source

    def prompt_keys(self, button) -> list:
        if isinstance(button, str) and button.startswith(("hold:", "release:", "stick:")):
            return []                                  # continuous / neutral inputs belong to Bot.tick
        if isinstance(button, str) and button.startswith("mash:"):
            if button == "mash:wiggle":
                chord = WIGGLE[self._wiggle_step % 2]
                self._wiggle_step += 1
            else:
                chord = prompt_chord(button, "mash")
            if chord is None:
                return []
            stats = getattr(self, "_stats", None)
            if stats is not None:
                stats["qte_presses"] = stats.get("qte_presses", 0) + 1
                stats["qte_keys"] = "+".join(chord)
            return [chord]
        stats = getattr(self, "_stats", None)
        if stats is not None:                               # what was answered: presses_square / presses_wiggle
            stats[f"presses_{button}"] = stats.get(f"presses_{button}", 0) + 1
        if button == "wiggle":
            return list(WIGGLE)
        if button == "mash":
            if stats is not None:
                stats["resuscitate_presses"] = stats.get("resuscitate_presses", 0) + 1
            return [("circle",)]                       # RESUSCITATE: engine's 45ms down / 35ms up mash cadence
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        if ROSTER.round is None and snap.get("player"):
            ROSTER.started()
        out = {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
               "kills": snap.get("kills"), **ROSTER.observe(snap)}
        rank = rank_of(snap.get("score"))
        if rank:
            out["rank"] = rank
        return out


DRIVER = RE5PS3
