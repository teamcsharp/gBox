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

from ..driver import Driver
from . import re5_nav

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
SWITCH_EVERY_S = 3.0                   # a weapon switch (a D-pad quick slot) at most this often
# The inventory: embedded in the player at +0x22E0 (live 2026-10-21, with the RE5 mods agent): INV_SLOTS slots of 0x30,
# a slot: +0x08 u32 id word 0x0TII (T 1 = weapon, uWpII; 2 = ammo / items), +0x0C rounds loaded, +0x10 capacity,
# +0x20 u32 1 = in hand, +0x2D u8 != 0 = in use. The 3 x 3 grid is slots 0..8, row by row; the D-pad quick-uses
# the edge slots (up 1, left 3, right 5, down 7).
P_INV, INV_SLOT, INV_SLOTS, INV_ALL = 0x22E0, 0x30, 9, 24   # the grid; all the slots (the one in hand may sit past 9)
INV_ID, INV_ROUNDS, INV_CAP, INV_HAND, INV_USED = 0x08, 0x0C, 0x10, 0x20, 0x2D
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
HOLD_FIRE = {0x15, 0x03, 0x09}         # automatic weapons fired by holding R1 (the Gatling, the VZ61, Chris HM's
HOLD_CAP = 50                          # uWp09); or any with a big magazine (autos): the rest fire once a press
TAP_ON, TAP_OFF = 1, 2                 # ticks of R1 down / up when tapping (a magnum's own recovery is longer)
HEAL_IDS = {0x301, 0x302, 0x303, 0x304, 0x307, 0x309}   # Green / Red / Yellow Herb, First Aid Spray, mixes GG / GR
                                       # (the item tables, from the RE5 mods agent 2026-10-21)
HEAL_AT = 0.4                          # use one below this share of health
WEAPON_NAMES = {0x02: "M92F", 0x03: "VZ61", 0x0B: "M29", 0x12: "Barry's handgun", 0x15: "Gatling", 0x20: "Dragunov"}
ENGAGE, SHOOT_RANGE, TOO_CLOSE = 3000.0, 2200.0, 110.0
BODY_R = 35.0                          # half a body: a shot inside atan(BODY_R / dist) hits
TURN_TOL = math.radians(12)            # turn with the stick (not aiming) until within this
AIM_TOL, PITCH_TOL = math.radians(2.5), math.radians(2.5)   # fire inside these
FINE = math.radians(6)                 # closer than this: pulse the stick (a tick on, a tick off)
MAX_DY = 450.0                         # targets this far above / below are out of reach (rooftops): not chosen
STUCK_S, STUCK_MOVE = 1.2, 80.0
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
STAND_R = 250.0                        # the stand: the round's start position, held from this close
BREAK_AT_S, BREAK_MARGIN_S = 60.0, 15.0   # leave the stand for time at this clock, or at the nearest one's ETA + this
RANK_SCORES: tuple = ()                # (("S", points), ("A", points), ...) once the thresholds are known (the meta
                                       # research is extracting them); until then no rank is logged


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
    """The player's 3 x 3 grid from RAM: [{"slot", "id", "type", "item", "rounds", "cap", "hand", "used"}] for the slots
    in use (type 1 = a weapon uWp<item>, 2 = ammo / items)."""
    raw = m.rd(player + P_INV, INV_SLOT * INV_ALL)
    out = []
    for k in range(INV_ALL):
        rec = raw[INV_SLOT * k:INV_SLOT * (k + 1)]
        if not rec[INV_USED]:
            continue
        word = struct.unpack(">I", rec[INV_ID:INV_ID + 4])[0]
        rounds = struct.unpack(">I", rec[INV_ROUNDS:INV_ROUNDS + 4])[0]
        cap = struct.unpack(">I", rec[INV_CAP:INV_CAP + 4])[0]
        hand = struct.unpack(">I", rec[INV_HAND:INV_HAND + 4])[0]   # +0x20, not next to the counts
        if k >= INV_SLOTS and hand != 1:
            continue                                        # past the grid: only the one in hand matters
        out.append({"slot": k, "id": word, "type": word >> 8, "item": word & 0xFF, "rounds": rounds, "cap": cap,
                    "hand": hand == 1})
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
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    """Never: the bot presses only on the screens above, so it never starts a story game."""
    return None


WIGGLE = (("lleft",), ("lright",), ("lleft",), ("lright",))
# sActionButton (static 0x017B7174): +0x34 u32 the HUD's prompt bits (bit 1: a prompt is up; bit 0: the weapon is up),
# +0x2A4 -> the cActionButton on screen: +0x04 its owner, +0x14 its kind, +0x40 the Majini it acts on (live 2026-10-21, frames
# of each): kind 3 owned by the player and aimed at a Majini = a melee finisher ("Hook", "Uppercut", "Straight": square);
# kind 2 owned by the player = the stage ("Jump over", a ladder: not taken); a button owned by a Majini = his grab.
AB_HUD, AB_BUTTON, HUD_PROMPT = 0x34, 0x2A4, 0x02
BTN_OWNER, BTN_KIND, BTN_TARGET = 0x04, 0x14, 0x40
BTN_MELEE, BTN_STAGE = 3, 2


def enemy_ptrs(m) -> set:
    se = u32(m, S_ENEMY)
    if not ptr_ok(se):
        return set()
    n, arr = u32(m, se + 0x28), u32(m, se + 0x34)
    if not ptr_ok(arr) or not 0 < n <= MAX_ENEMIES:
        return set()
    return {e for e in struct.unpack(f">{n}I", m.rd(arr, 4 * n)) if ptr_ok(e)}


def prompt(m) -> str | None:
    """The prompt the game asks the player to answer, from RAM: "wiggle" while a Majini holds him (action 4, the
    "Break free" prompt: the left stick wiggled), "square" for a melee finisher on a Majini (the player's own
    cActionButton of kind 3 aimed at one of sEnemy's), else None (no prompt, or one on the stage: never taken)."""
    sp = u32(m, S_PLAYER)
    pl = u32(m, sp + 0x28) if ptr_ok(sp) else 0
    if not ptr_ok(pl):
        return None
    if m.rd(pl + P_ACTION, 1)[0] == P_GRABBED:
        return "wiggle"
    ab = u32(m, S_ACTION)
    if not ptr_ok(ab) or not u32(m, ab + AB_HUD) & HUD_PROMPT:
        return None
    btn = u32(m, ab + AB_BUTTON)
    if not ptr_ok(btn) or u32(m, btn + BTN_OWNER) != pl or u32(m, btn + BTN_KIND) != BTN_MELEE:
        return None
    return "square" if u32(m, btn + BTN_TARGET) in enemy_ptrs(m) else None


def stage_prompt(m) -> bool:
    """A prompt on the stage is up (the player's own cActionButton of kind 2: a ladder, a drop, Jump over)."""
    sp = u32(m, S_PLAYER)
    pl = u32(m, sp + 0x28) if ptr_ok(sp) else 0
    ab = u32(m, S_ACTION)
    if not (ptr_ok(pl) and ptr_ok(ab)) or not u32(m, ab + AB_HUD) & HUD_PROMPT:
        return False
    btn = u32(m, ab + AB_BUTTON)
    return ptr_ok(btn) and u32(m, btn + BTN_OWNER) == pl and u32(m, btn + BTN_KIND) == BTN_STAGE


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
    playing; health 0 = dead ("You Are Dead - Continue?"); time 0 = results; no player = loading or menus."""
    p = snap.get("player")
    if not p:
        return "loading"
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

    def __init__(self, m=None, clock=time.time, stats: dict | None = None):
        self.m, self.clock = m, clock
        self.stats = stats if stats is not None else {}
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
        self.avoid: list = []                  # crossings the player could not take this round (no prompt there)
        self.climb_at = None                   # (the crossing, since when) while waiting at one for its prompt
        self.take_at = None                    # (the bonus, since when) while standing at one for its prompt
        self.route_len, self.route_len_at = None, 0.0   # hourglass -> its route's length (cm), when worked out
        self.nearest_eta = None
        self.tap = 0                           # the R1 tap cycle (TAP_ON down, TAP_OFF up)
        self.spawn = None                      # where the round started: the stand
        self.at_stand = False
        self.stood = False                     # the stand has begun (every reachable bonus gathered once)
        self.plan_target = None
        self.flags: dict = {}
        self.reload_until = 0.0
        self.heal_at = 0.0
        self.switch_at = 0.0

    # --- the engine's brain interface ---
    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self):
        save_crossings()

    def plan(self) -> dict:
        """What the bot is doing, for the tactical map (gbox/mercs/tactical.py): no RAM reads, only state held."""
        walking = self.route if self.stats.get("phase") in ("gather_time", "break_for_time", "stand") else None
        nb = None
        if self.route_len:
            ptr, d = min(((k, v) for k, v in self.route_len.items() if v is not None), key=lambda kv: kv[1],
                         default=(None, None))
            if ptr is not None:
                nb = {"id": ptr, "kind": "time", "dist": round(d), "eta_s": round(d / RUN_SPEED, 1)}
        return {"phase": self.stats.get("phase"), "target": self.plan_target,
                "route": [tuple(w) for w in walking] if walking else None,
                "stand": {"pos": self.spawn, "r": STAND_R} if self.spawn else None,
                "nearest_bonus": nb, "enemy_flags": dict(self.flags),
                "note": str(self.stats.get("bonus_target") or self.stats.get("aim") or "")[:80]}

    def tick(self, snap: dict) -> dict:
        now = self.clock()
        p = snap.get("player")
        self.stats["max_combo"] = max(self.stats["max_combo"], snap.get("combo") or 0)
        if not p:
            return {"hold": set()}
        if p.get("hp") is not None and p["hp"] <= 0:        # "You Are Dead - Continue? Yes / No": Yes (cross)
            if now - self.dead_tap > 1.5:
                self.dead_tap = now
                self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                return {"tap": "cross"}
            return {"hold": set()}
        self._score_hits(snap)
        if snap.get("prompt"):                              # a finisher / a grab: the engine presses it; the gun
            self.aiming_since = None                        # stays down between its presses (L1 would cancel it)
            self.stats["prompt_holds"] = self.stats.get("prompt_holds", 0) + 1
            return {"hold": set()}
        heal = self._heal(p, snap, now)                     # low: a herb / a spray from a quick slot
        if heal:
            return heal
        t = snap.get("timer")
        if self.last_timer is not None and t is not None and self.last_timer > 0 and 2 < t - self.last_timer < 95:
            # (+30 / +60 / +90 of a bonus, +5 of a finisher; a Continue's new clock is not one)
            self.stats["bonus_s"] = round(self.stats.get("bonus_s", 0.0) + t - self.last_timer, 1)
            self.stats["clock_jumps"] = self.stats.get("clock_jumps", 0) + 1
        self.last_timer = t
        # Majini and the like: alive, more than 1 health (crows are "enemies" with 1), not far above or below
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1
                and abs(e["pos"][1] - p["pos"][1]) < MAX_DY]
        eq = equipped(snap)
        if eq is not None:
            self.stats["weapon"] = f"{WEAPON_NAMES.get(eq['item'], 'uWp%02x' % eq['item'])} {eq['rounds']}/{eq['cap']}" \
                if eq["type"] == 1 else f"item {eq['id']:#x}"
            if eq["type"] == 1 and eq["rounds"] == 0 and eq["cap"] == 0 and p.get("action") != P_GRABBED \
                    and now - self.switch_at > SWITCH_EVERY_S:
                # EMPTY 0 / 0 (Excella, live 2026-10-21: the trigger did nothing): another weapon with rounds from
                # a quick slot (the D-pad equips the edge slots)
                other = next((w for w in snap.get("inventory") or () if w["type"] == 1 and not w["hand"]
                              and w["rounds"] > 0 and w["slot"] in QUICK), None)
                if other is not None:
                    self.switch_at = now
                    self.stats["weapon_switches"] = self.stats.get("weapon_switches", 0) + 1
                    return {"tap": QUICK[other["slot"]]}
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
        tgt = self._bonus(p, live, snap.get("bonuses") or (), now, mesh, t)
        threats = [e for e in live if self._threat(p, e)]
        self.flags = {e["slot"]: ["blocking"] for e in threats}
        if tgt is None and not threats and self.spawn is not None and not self.at_stand:
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
            self.stats["phase"] = "fight" if threats or not self.at_stand else "stand"
        tgt = tgt or min(threats or live, key=lambda e: self._cost(p, e))
        self.plan_target = {"kind": tgt.get("kind", "enemy") if "ptr" in tgt else "enemy",
                            "id": tgt.get("ptr", tgt.get("slot")), "pos": tgt["pos"]}
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
        if dist < TOO_CLOSE and not aiming:                 # on top of him: a step back while facing him
            self.aiming_since = None
            self.stats["backoffs"] += 1
            return {"hold": {"ldown"} | self._turn(wrap(want - p["rot"]), aiming=False)}
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

    # --- helpers ---
    def _bonus(self, p, live, standing, now, mesh=None, clock=None):
        """The time bonus to go for now, or None (nothing standing, or a Majini within FIGHT_R: he is fought first).
        The nearest hourglass by the navmesh route (straight line without a mesh), on any level, walked to along the
        route and taken with its "□ Time bonus" prompt (Bot._take); one left alone for BONUS_SKIP_S when its prompt
        did not come or its route led nowhere."""
        px, py, pz = p["pos"]
        now_ptrs = {b["ptr"] for b in standing}
        taken = self.bonus_seen - now_ptrs
        if taken:
            self.stats["bonuses_taken"] = self.stats.get("bonuses_taken", 0) + len(taken)
        self.bonus_seen = now_ptrs
        standing = [b for b in standing if self.bonus_skip.get(b["ptr"], 0.0) <= now]
        if not standing or not BONUS_HUNT:
            self.stats["bonus_target"] = None
            return None
        if any(self._threat(p, e) for e in live):
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
        cands = [b for b in standing if cost(b) < BONUS_RANGE]
        if not cands:
            self.stats["bonus_target"] = None
            return None
        b = min(cands, key=cost)
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
        """Below HEAL_AT of his health, with a healing item (HEAL_IDS) in a quick slot: the D-pad uses it (once a
        4 s); one in a corner slot can't be quick-used (logged). Unknown item ids are logged for the table."""
        inv = snap.get("inventory") or ()
        items = [s for s in inv if s["type"] != 1]
        if items:
            self.stats["items"] = ", ".join(f"{s['id']:#x}x{s['rounds']}@{s['slot']}" for s in items)
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        if hp_max <= 0 or hp > HEAL_AT * hp_max or now - self.heal_at < 4.0 or p.get("action") == P_GRABBED:
            return None
        heals = [s for s in items if s["id"] in HEAL_IDS]
        if not heals:
            return None
        quick = next((s for s in heals if s["slot"] in QUICK), None)
        if quick is None:
            self.stats["heal_out_of_reach"] = heals[0]["slot"]
            return None
        self.heal_at = now
        self.stats["heals"] = self.stats.get("heals", 0) + 1
        return {"tap": QUICK[quick["slot"]]}

    def _take(self, p, tgt, stage_prompt, now) -> dict:
        """At a time bonus: square when its prompt ("□ Time bonus") is up, else face it and edge up to it; a bonus
        stood at BONUS_GIVE_UP_S without its prompt is left for BONUS_SKIP_S."""
        pos = p["pos"]
        if stage_prompt:
            self.stats["bonus_presses"] = self.stats.get("bonus_presses", 0) + 1
            return {"tap": "square"}
        if self.take_at is None or self.take_at[0] != tgt["ptr"]:
            self.take_at = (tgt["ptr"], now)
        elif now - self.take_at[1] > BONUS_GIVE_UP_S:
            self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
            self.take_at = None
            return {"hold": set()}
        err = wrap(heading(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]) - p["rot"])
        keys = self._turn(err, aiming=False)
        if math.hypot(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]) > 60.0 and abs(err) < math.radians(30):
            keys = keys | {"lup"}                           # a step closer (walking, not running)
        return {"hold": keys}

    def _follow(self, p, tgt, mesh, stage_prompt, now) -> dict:
        """One step along the navmesh to a time bonus: the route drawn again every REPLAN_S; the next waypoint walked
        to (turn, then run); at a ladder or a drop (the next waypoint straight above / below) the stage's square
        prompt is taken; a bonus followed ROUTE_STALE_S without being reached is left for BONUS_SKIP_S."""
        pos = p["pos"]
        if self.route_for != tgt["ptr"]:
            self.route, self.route_for, self.route_since = None, tgt["ptr"], now
        if now - self.route_since > ROUTE_STALE_S:
            self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
            self.stats["routes_given_up"] = self.stats.get("routes_given_up", 0) + 1
            self.route_for = None
            return {"hold": set()}
        if mesh is not None and (self.route is None or now - self.route_at > REPLAN_S):
            self.route, self.route_at = mesh.route(pos, tgt["pos"], avoid=self.avoid), now
        if not self.route:                                  # no mesh, or no way there: straight at it
            return {"hold": self._walk(p, heading(tgt["pos"][0] - pos[0], tgt["pos"][2] - pos[2]), now)}
        while len(self.route) > 1 and math.hypot(self.route[0][0] - pos[0], self.route[0][2] - pos[2]) < WP_REACHED \
                and abs(self.route[0][1] - pos[1]) < WP_CLIMB:
            self.route.pop(0)
        w = self.route[0]
        flat = math.hypot(w[0] - pos[0], w[2] - pos[2])
        self.stats["route"] = f"{len(self.route)} wp, next d {flat:.0f} dy {w[1] - pos[1]:+.0f}"
        if flat < WP_CLIMB and abs(w[1] - pos[1]) >= WP_CLIMB:  # a ladder / a drop: the game's own action
            if stage_prompt:
                self.stats["climbs"] = self.stats.get("climbs", 0) + 1
                return {"tap": "square"}
            if self.climb_at is None or math.dist(self.climb_at[0], w) > 60.0:
                self.climb_at = (w, now)
            elif now - self.climb_at[1] > CLIMB_WAIT_S:        # no prompt here: a crossing only the Majini take
                self.avoid.append(w)
                self.stats["crossings_avoided"] = self.stats.get("crossings_avoided", 0) + 1
                self.climb_at, self.route = None, None
                return {"hold": set()}
            beyond = next((v for v in self.route[1:] if math.hypot(v[0] - w[0], v[2] - w[2]) > 50.0), None)
            way = heading(beyond[0] - pos[0], beyond[2] - pos[2]) if beyond else heading(w[0] - pos[0], w[2] - pos[2])
            err = wrap(way - p["rot"])
            if abs(err) > math.radians(25):                 # face the way down first: the prompt wants it
                return {"hold": self._turn(err, aiming=False)}
            return {"hold": {"lup"}}                        # on to the edge until the prompt shows
        return {"hold": self._walk(p, heading(w[0] - pos[0], w[2] - pos[2]), now)}

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

    def _walk(self, p, want: float, now: float) -> set:
        """Run toward a heading: turn first (the body turns in place), run (up + cross) once within 60 deg. Stuck
        (pushing forward STUCK_S without STUCK_MOVE of ground): a step back and aside for 0.8 s. Turning in place
        is never "stuck" (live 2026-10-21: it was, and the walk thrashed)."""
        px, py, pz = p["pos"]
        if now < self.unstick_until:
            return {"ldown", "lleft" if self.unstick_dir > 0 else "lright"}
        err = wrap(want - p["rot"])
        keys = self._turn(err, aiming=False)
        if abs(err) >= math.radians(60):
            self.hist = []
            return keys
        keys |= {"lup", "cross"}                            # run (up + cross)
        self.hist = [h for h in self.hist if now - h[0] < STUCK_S + 0.3] + [(now, px, pz)]
        if now - self.hist[0][0] >= STUCK_S and math.hypot(px - self.hist[0][1], pz - self.hist[0][2]) < STUCK_MOVE:
            self.hist, self.unstick_dir = [], -self.unstick_dir
            self.unstick_until = now + 0.8
            self.stats["stuck"] += 1
        return keys

    def _score_hits(self, snap):
        for e in snap.get("enemies") or ():
            prev = self.hp_seen.get(e["ptr"])
            if prev is not None and e["hp"] < prev:
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
                return "loading"                            # frozen: the engine calls it lost (its LOST_S later)
        return where

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(m, clock=clock, stats=stats)

    def prompt_source(self, m, stats: dict):
        self._stats = stats
        return lambda: prompt(m)

    def prompt_keys(self, button) -> list:
        stats = getattr(self, "_stats", None)
        if stats is not None:                               # what was answered: presses_square / presses_wiggle
            stats[f"presses_{button}"] = stats.get(f"presses_{button}", 0) + 1
        if button == "wiggle":
            return list(WIGGLE)
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
