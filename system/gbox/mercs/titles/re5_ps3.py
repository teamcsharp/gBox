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
import uuid
from pathlib import Path

from ..driver import Driver
from .. import obstacle_map
from .. import stalemate as stalemate_rule       # no enemies for 15 s with time on the clock: the clock is cut
from . import re5_aim_geometry, re5_combat, re5_motion, re5_nav, re5_weapons

S_PLAYER, S_ENEMY, S_MAIN = 0x017FEB34, 0x017FDB60, 0x0191CEE4
S_ACTION, S_ITEM, S_UNIT = 0x017B7174, 0x017FE574, 0x0191D700
S_CAMERA, CAM_CTRL, CAM_EYE, CAM_AT = 0x0191CA6C, 0x104, 0x30, 0x50   # sBioCamera +0x104 -> uCameraCtrl: eye, look-at
MAIN_GAMESYS = 0x182D4
P_POS, P_ROT, P_PITCH, P_ACTION, P_HP = 0x30, 0x40, 0x1AA0, 0x845, 0x14A4
E_POS, E_HP = 0x30, 0x14A4
GS_TIMER, GS_START, GS_KILLS, GS_COMBO, GS_COMBO_T, GS_SCORE = 0x3E0, 0x3E4, 0x3F4, 0x3FC, 0x404, 0x418
GS_PHASE = 0x3DC                       # native Mercenaries state3 is terminal, including quota clear with time left
MAX_ENEMIES = 64
ACTIONS = {0: "stand", 1: "move", 2: "aim", 4: "grabbed", 5: "hit"}
P_GRABBED = 4                          # held by a Majini: "Break free" (wiggle the left stick)

HEAD_H, GUN_H = 160.0, 140.0           # above the feet: a Majini's head, the player's gun (cm)
# uLaserSight (sUnit's FxCore line 18): +0x200 the laser's origin (the muzzle), +0x30 the laser dot (where the ray
# lands: a Majini, a wall, the ground); the combat layer closes its aim on the dot (the camera's ray is ~5 deg off it,
# the body's yaw +-7: the upper body aims inside a cone)
FX_LINE, LASER_VT, LASER_FROM, LASER_AT = 18, 0x015BD958, 0x200, 0x30
SWITCH_EVERY_S, SWITCH_ACK_S, SWITCH_FAIL_S = 1.0, 1.5, 8.0
MINE_ENEMY_CM, MINE_ESCAPE_CM = 600.0, 600.0   # conservative policy margins, not measured native blast radii
STAGE_LOOP_R, STAGE_LOOP_N, STAGE_LOOP_S, STAGE_BAN_S = 400.0, 3, 40.0, 60.0   # the same ladder / ledge this near taken
                                              # this often in this long: left alone this long (operator 2026-10-24: "jumping
                                              # down the ladder, putting back up the ladder ... repeatedly")
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
HEAL_SAFE_R, HEAL_CRITICAL = 500.0, 0.15   # no heal started with a Majini this near unless health is this low: RE5's
                                       # inventory is real time, every heal in a crowd is eaten (operator 2026-10-26)
WEAPON_NAMES = {0x02: "M92F", 0x03: "VZ61", 0x0B: "M29", 0x12: "Barry's handgun", 0x15: "Gatling", 0x20: "Dragunov"}
ENGAGE, SHOOT_RANGE, TOO_CLOSE = re5_combat.ENGAGE_R, re5_combat.ENGAGE_R, 110.0   # long shots across the yard (operator 2026-10-24)
CLOSE_ESCAPE_S, CLOSE_ACQUIRE_S = 0.25, 1.0  # escape briefly, then give the gun time to become ready
BODY_R = 35.0                          # half a body: a shot inside atan(BODY_R / dist) hits
TURN_TOL = math.radians(12)            # turn with the stick (not aiming) until within this
AIM_TOL, PITCH_TOL = math.radians(2.5), math.radians(2.5)   # fire inside these
FINE = math.radians(6)                 # closer than this: pulse the stick (a tick on, a tick off)
MAX_DY = 450.0                         # targets this far above / below are out of reach (rooftops): not chosen
STUCK_S, STUCK_MOVE = 1.2, 80.0
# Pushed into the same wall again and again (operator 2026-10-22: "there is a wall there, find the window and door"):
# each repeat at that spot walks a wider angle off the heading, alternating sides, to slide along the wall to an
# opening (its door / window / vault prompt is then taken by the stage-prompt rule). Cleared after DETOUR_FREE of ground.
DETOUR_STEP, DETOUR_MAX, DETOUR_FREE = math.radians(40), math.radians(160), 250.0
STAGE_YIELD_S = 2.5                      # a stage prompt shown this long beside close foes is taken anyway (a fence / ledge between)
RUN_SPEED = 250.0                      # cm/s running (the route ETAs; measured live: walking 145)
# The time bonuses: hourglasses (uOm0100, model "sunadokei_360" = hourglass in uOm0100.arc; 9 in Public Assembly),
# units of sUnit's move line 12 ("OM"), told by their vtable.
OM_LINE, OM_MAX = 12, 600
HOURGLASS_VT = 0x015EF5E0              # uOm0100's vtable (BLUS30491 app 01.01; read live 2026-10-21)
HG_CENTRE_DY = 13.0                    # its middle, above its position (+0x30)
HG_CENTRE, HG_KIND = 0x250, 0x194      # bounding sphere; retained render word, never a bonus-type discriminator
HG_COLLECTED, HG_SECONDS = 0x13EC, 0x14A4  # native FUN_00723e34 adds signed seconds, then sets collected=1
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
IDLE_S = 6.0                           # standing on one spot this long, off the stand, no hits landing: a wall stare
IDLE_WALK_S = 2.0                      # the break-out walk (a turn off the wall, then running)
STAND_R = 250.0                        # the stand: the round's start position, held from this close
# The stand gone quiet (operator 2026-10-26: "long swaths of time where enemies are not spawning"; round maps
# Experimental_Facility 11:22 / 11:49: 491 s and 585 s at the stand with no Majini, 68 and 78 kills): the game spawns
# around the player, so he hunts the spawn points this stage has shown, the farthest unvisited first, until one shows
LULL_S, LULL_AGAIN_S = 8.0, 3.0        # no living Majini this long: hunt (sooner once a hunt has happened this round)
HUNT_REACH, HUNT_REVISIT_S, HUNT_GIVE_UP_S = 350.0, 90.0, 45.0   # a spawn point this near is visited, left alone this
                                       # long after; a walk taking longer is abandoned for the next one
SPAWN_CLUSTER_CM, SPAWNS_FILE = 400.0, "spawn_points.json"   # first-seen Majini positions per stage, this far apart
# A boss (re5_combat.BOSS_HP: the Executioner, the Chainsaw / Gatling Majini ...) is the target the moment he is in sight
# (operator 2026-10-26: "she is failing to recognize the threat of the boss and dispatch them. Bosses are threats that
# require the remove their HP and dispatch them without delay (preferably from a distance)") unless a Majini is at arm's
# length; inside BOSS_KEEP_R the gun comes down and a measured floor route takes him 6 m back before the next volley
BOSS_YIELD_R = 350.0                   # a Majini this near is shot before the boss (the combat layer's immediate radius)
BOSS_KEEP_R, BOSS_RETREAT_S, BOSS_RETREAT_GAP_S = 450.0, 2.5, 2.0   # back off from this close, this long, then fire
                                       # for at least this long before backing off again (never a run without shots)
BREAK_AT_S, BREAK_MARGIN_S = 60.0, 15.0   # leave the stand for time at this clock, or at the nearest one's ETA + this
# Sight and pursuit (operator 2026-10-21: "If the person stands still ... what is there to see?"; live the same day the
# bot spent 57 of 130 s aiming into walls at Majini behind them). A Majini is fought from where the player stands only
# with open floor between them (the navmesh: floor_segment, or a route that barely bends) or within PURSUE_NEAR;
# the rest are walked to along the navmesh. One fought while the laser dot stops short of him (a wall, a fence) for
# BLOCKED_VIEW_S, or without the dot ever reaching him for UNSIGHTED_S, is left out of sight for PURSUE_S and walked to.
SIGHT_R = 2200.0                       # open-floor Majini within this are fought (= SHOOT_RANGE)
IN_VIEW_CONE = math.radians(60)        # ...and any Majini within ENGAGE this close to his heading (Bot._in_view)
# round maps: which code runs each stats["phase"] (gbox.mercs.round_map.code_map resolves file:line)
PHASE_CODE = {"leave_proximity_bomb": "Bot._mine_retreat", "gather_time": "Bot._bonus", "break_for_time": "Bot._bonus",
              "pursue": "Bot._pursue", "fight": "Combat.tick", "clear_nearby": "Combat.tick", "keep_combo": "Bot._tick",
              "stand": "Bot._tick", "idle": "Bot._tick", "healing": "Bot._heal", "recover_navigation": "Bot._recover_nav",
              "obstacle_detour": "Bot._follow", "waiting_round_start": "Bot.tick", "egg_inventory": "Bot._egg_action",
              "hunt_spawns": "Bot._hunt_spawns", "boss_range": "Bot._boss_range"}
SIGHT_CACHE_S = 0.3                    # a floor_segment answer is kept this long per Majini
SIGHT_BEND, SIGHT_SLACK = 1.1, 50.0    # ...or a navmesh route at most this much longer than the straight line: open
PURSUE_NEAR = 200.0                    # this close he is fought whatever the floor says (a doorway, a corner)
BLOCKED_VIEW_S, UNSIGHTED_S, PURSUE_S = 0.5, 2.5, 2.0
COMBAT_STALL_S, COMBAT_STALL_R, COMBAT_STALL_BLOCK_S = 4.0, 120.0, 8.0   # the same Majini fought this long without a shot
COMBAT_STALL_TICKS = 20                # ...over at least this many ticks (a stall is seen tick after tick, never a clock jump)
                                       # leaving the gun, the player within this of where he stood: left alone this long
                                       # and the route goes on (operator 2026-10-26: "They cannot afford to sit still
                                       # ever"; round map Prison: 34 s in break_for_time, "no line: hold fire")
VIEW_SHORT = 150.0                     # the dot this much short of him, roughly toward him: something in between
WALL_R = 120.0                         # the dot this close to the muzzle: facing a wall
COMBO_LAPSE_S = 0.6                    # a combo that fell with this much window left or less ran out (was not kept)
PURSUE_PICK_S = 1.0                    # the Majini to walk to is chosen again this often (route lengths)
# Confirmed sight (operator 2026-10-22: "he is shooting at nonsense"; live the same day the bot spent a whole minute in
# Public Assembly's pit at y -200 aiming at Majini on the floor 4 m above, within PURSUE_NEAR on the map): the gun comes
# up only for a Majini confirmed in sight - the laser dot on him a moment ago, or on the player's own level with open
# floor between them (floor_segment within CONFIRM_R, a barely bending route within BEND_R) or right next to him.
LEVEL_DY = 150.0                       # this far above / below: another level (a roof, a pit), in sight only by the dot
CONFIRM_R = 1500.0                     # an open floor_segment confirms sight this far at most
BEND_R = 800.0                         # a barely bending navmesh route confirms sight this far at most
DOT_MEMORY_S = 1.0                     # the dot on him this recently: in sight, on any level
HARD_REFUSALS = ("dispatch nearby exposed threat first", "clock expires before pickup",
                 "inactive, unknown ETA, or unsafe route")   # the only strategy refusals a time bonus respects
RANK_SCORES = (("SS", 90000), ("S", 60000), ("A", 40000), ("B", 20000), ("C", 10000), ("D", 0))   # Reunion solo
                                       # (docs/mercenaries_re5_meta.md 1.1); the rank is score alone, same every stage


def ptr_ok(p) -> bool:
    return isinstance(p, int) and 0x30000000 <= p < 0x40000000


def u32(m, a) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


def player_index(m):
    """Zero-based memory-view scope; an invalid scope never selects Player 1."""
    index = getattr(m, "mercs_player_index", 0)
    return index if type(index) is int and index in (0, 1) else None


def modifications_allowed(m):
    """Solo modifier helpers have no authority over another player's actor."""
    return player_index(m) == 0 and not getattr(m, 'mercs_no_modifications', False)


def player_pointer(m) -> int:
    """Resolve the scoped actor without treating an adjacent pointer as Player 2.

    Existing solo readers retain their original chain. A second-player view
    requires the native manager, slot, actor-index and lifetime checks shared
    with the read-only participant recorder. This does not authorize controls.
    """
    index = player_index(m)
    if index is None:
        return 0
    if index == 0:
        manager = u32(m, S_PLAYER)
        return u32(m, manager + 0x28) if ptr_ok(manager) else 0
    from .re5_coop import participants
    return next((row['actor'] for row in participants(m) if row['slot'] == 2), 0)


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
    """Uncollected native time hourglasses from the OM line.

    FUN_00723e34 adds the signed +14A4 seconds to aGame, then marks +13EC=1
    before its removal animation. Combo chests are a different class; +194 is
    a render word and its 0x90 byte does not identify a combo bonus.
    """
    out: list = []
    for u in hourglass_units(m):
        if u32(m, u) != HOURGLASS_VT:                       # gone since the last walk
            continue
        collected = m.rd(u + HG_COLLECTED, 1)[0]
        if collected == 1:
            continue                                     # credited already; do not punch its shrinking actor again
        x, y, z = struct.unpack(">3f", m.rd(u + 0x30, 12))
        r = struct.unpack(">f", m.rd(u + HG_CENTRE + 12, 4))[0]
        r = r if 5.0 < r < 100.0 else 28.0
        kw = u32(m, u + HG_KIND)
        seconds = struct.unpack(">h", m.rd(u + HG_SECONDS, 2))[0]
        out.append({"ptr": u, "pos": (x, y + HG_CENTRE_DY, z), "r": r,
                    "kind": "time", "kind_word": kw,
                    "collected": False if collected == 0 else None,
                    "seconds": seconds if 0 < seconds <= 3600 else None})
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
    if player_index(m) != 0:
        return None                         # the first Fx laser has no verified second-player ownership
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
    index = player_index(m)
    snap['control_player'] = index+1 if index is not None else None
    p = player_pointer(m)
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
                enemy = {"slot": slot, "ptr": e, "pos": pos, "hp": hp, "hp_max": hp_max}
                geometry = re5_aim_geometry.read(m, enemy)
                if geometry is not None:
                    enemy["native_aim"] = geometry
                snap["enemies"].append(enemy)
    # +104 identifies a camera MODE, not a player slot. Never reuse P1's
    # camera for a P2 view while the per-player camera decoder is unverified.
    cm = u32(m, S_CAMERA) if player_index(m) == 0 else 0
    cc = u32(m, cm + CAM_CTRL) if ptr_ok(cm) else 0
    if ptr_ok(cc):
        snap["camera"] = {"eye": struct.unpack(">3f", m.rd(cc + CAM_EYE, 12)),
                          "at": struct.unpack(">3f", m.rd(cc + CAM_AT, 12))}
    if snap["player"]:
        snap["bonuses"] = bonuses(m)
        from . import re5_mines
        snap["ground_mines"] = re5_mines.ground_mines(m)
        from . import re5_health
        ground_health = getattr(re5_health,'ground_items',None)
        snap['health_items'] = ground_health(m) if callable(ground_health) else []
        snap["prompt"] = prompt(m)
        snap["stage_prompt"] = stage_prompt(m)
        snap["prompt_target"] = prompt_target(m)            # the Majini a finisher prompt is for (the combat layer)
        request = selected_prompt(m, include_item_pickups=True)
        snap['prompt_optional'] = bool(request and request['kind'] in (BTN_MELEE, BTN_STAGE)
            and request['owner'] == p and request['mode'] == 1 and request['token'] == 'mash:square'
            and action not in (4,5) and snap['player']['hp']>0 and not snap.get('recovery_active'))
        try:
            snap["nav"] = re5_nav.read(m, _NAV_CACHE)
        except (ValueError, OSError, struct.error):
            snap["nav"] = None
    main = u32(m, S_MAIN)
    gs = u32(m, main + MAIN_GAMESYS) if ptr_ok(main) else 0
    if ptr_ok(gs):
        t, t0 = struct.unpack(">2f", m.rd(gs + GS_TIMER, 8))
        snap.update(timer=round(t, 2), timer_start=t0, mercenaries_phase=u32(m, gs + GS_PHASE),
                    kills=struct.unpack(">i", m.rd(gs + GS_KILLS, 4))[0],
                    combo=struct.unpack(">i", m.rd(gs + GS_COMBO, 4))[0],
                    combo_timer=round(struct.unpack(">f", m.rd(gs + GS_COMBO_T, 4))[0], 2),
                    score=struct.unpack(">i", m.rd(gs + GS_SCORE, 4))[0])
        mode = u32(m, gs + 0x58)
        snap.update(mercenaries_mode={2: "mercenaries", 5: "reunion"}.get(mode),
                    stage_index=u32(m, gs + 0x348),
                    character_index=u32(m, gs + 0x364) if index == 0 else None)
        if mode in (2, 5) and u32(m, gs + 0x340) == 2:
            snap['scoring_players'] = 2     # native split-screen predicate FUN009C0B34
    if player_index(m) != index or index == 1 and player_pointer(m) != p:
        snap.update(player=None, inventory=[], laser=None, prompt=None,
                    stage_prompt=False, prompt_target=None, recovery_active=False)
        snap.pop('camera', None)
    return snap


MENU_KEYS = ("start", "cross")         # results: START (OK); stage / character select: cross


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
              0x015ABB20: "uIdMerceEd00",       # Mercs results, including native stage/character unlock notices
              0x015AB6E8: "uIdGameover00",     # Continue: state byte +0x17, Yes/No u32 +0x178
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
              0x015ACDB0: "uIdStartUp20",       # Original Mercenaries title / solo selector (Ghidra 0x613940)
              0x015ACCF0: "uIdStartUp22",       # CHARACTER SELECT (Reunion)
              0x015AD690: "uIdTopMenu00",       # the title's menus (around the selects, and the main menu)
              0x015AD638: "uIdTitle00",         # +0x1F8 = 0x48 on PRESS START
              0x015AD588: "uIdTitle02"}
UI_MAX = 64
ALERT_ID = 0x3C
ALERT_VT = 0x015AB350
ALERTS = {0x22: "alert_signin",                 # "... without signing in. Sign in?": circle = Continue
          0x09: "alert_ok",                     # Save successful after declining Continue: Cross = OK
          0x08: "alert_ok"}                     # "Load successful.": cross = OK (0x13: loading the save, wait)
MENU_CURSOR, MENU_SUB, EXTRA_CURSOR = 0x44, 0x174, 0x188
TITLE_STEP, TITLE_PRESS_START = 0x1F8, 0x48
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, EXTRA_REUNION = 0, 7, 3
# BLUS30491 app 01.01: 0x59299C dispatches state 2 to 0x592E5C. The input branch at 0x592F00 reads
# choice +0x178; Right selects 1, Left selects 0, and 0x592FA8 stores the result. Confirmation calls
# 0x591F9C: 0 retries (event 5,1), 1 exits (event 5,2). States 0/1 are the death/intro animation.
# ELF SHA256 d901458f13beeb3d5bb0523eaac9c60102863a67f69b20905d8fa0c74e8be293.
CONTINUE_VT, CONTINUE_STATE, CONTINUE_CHOICE = 0x015AB6E8, 0x17, 0x178
CONTINUE_READY, CONTINUE_NO, CONTINUE_BLOCKED = 2, 1, 0x1D4
CONTINUE_CODE = ((0x00592E5C, bytes.fromhex("7bbb00207f63db784bffe6295463063e")),
                 (0x00592F00, bytes.fromhex("809f01782f840001419e02e0")),
                 (0x00592F94, bytes.fromhex("801f01787f804800419e001c380000007f63db78913f0178901f018c")))
# Same pinned app01.01 ELF as CONTINUE_CODE. 0x5D0954 fills +290 from newly unlocked stage/character save bits;
# 0x5CFA58 displays them in outer state6. Inner3 at 0x5CFBEC accepts sBioPad's dynamic confirm mask.
MERCE_END_VT, MERCE_NOTICE_STATE, MERCE_FINAL_STATE = 0x015ABB20, 6, 10
S_BIOPAD, PAD_CONFIRM = 0x0191CF38, 0x1EA0
MERCE_NOTICE_CODE = ((0x005CFBEC, bytes.fromhex(
    "817e80c0812b000080091ea07f8900382c09000040820010546005ac2f800000419efefc")),
    (0x005CFC20, bytes.fromhex("817e80b4c1bf028cc19e800c812b0000c009002cedad002aff8d6000d1bf028c")),
    (0x005D2624, bytes.fromhex("7f63db784bffd4315463063e2f830000409eff10c1bf027c4bfffe58")))


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


def continue_screen(m, ui=None) -> dict:
    """Observe the native Continue choice; absent, unreadable or transitional dialogs never permit a press."""
    out = {"where": "dead", "cursor": None, "target": CONTINUE_NO, "continue_unit": None,
           "continue_state": None, "continue_ready": False}
    try:
        ui = ui_units(m, range(N_LINES)) if ui is None else ui
        unit = ui.get("uIdGameover00")
        if not ptr_ok(unit):
            return out
        raw = m.rd(unit, 0x1D8)
        if len(raw) != 0x1D8 or struct.unpack_from(">I", raw)[0] != CONTINUE_VT:
            return out
        state, choice = raw[CONTINUE_STATE], struct.unpack_from(">I", raw, CONTINUE_CHOICE)[0]
        out.update(continue_unit=unit, continue_state=state, cursor=choice if choice in (0, 1) else None)
        if state != CONTINUE_READY or choice not in (0, 1) or struct.unpack_from(">I", raw, CONTINUE_BLOCKED)[0]:
            return out
        main = u32(m, S_MAIN)
        # Other game-over modes bypass this state machine. +1D4 is the native readiness predicate's
        # blocking reason (0x59148C); it is reset before its network/system-dialog checks each update.
        if not ptr_ok(main) or u32(m, main + 0x182DC) & 0x503:
            return out
        if any(m.rd(address, len(code)) != code for address, code in CONTINUE_CODE):
            return out
        # A menu can be destroyed or begin confirming while these independent RAM reads are in flight.
        out["continue_ready"] = (u32(m, unit) == CONTINUE_VT
                                 and m.rd(unit + CONTINUE_STATE, 1) == bytes([CONTINUE_READY])
                                 and u32(m, unit + CONTINUE_CHOICE) == choice)
    except Exception:
        out["continue_ready"] = False
    return out


def alert_screen(m, ui=None) -> dict | None:
    """Read only the known native alert class, retaining unknown IDs without authorizing input."""
    if m is None:
        return None
    try:
        ui = ui_units(m) if ui is None else ui
        unit = ui.get("uIdAlert00")
        if not ptr_ok(unit):
            return None
        raw = m.rd(unit, ALERT_ID + 4)
        if len(raw) != ALERT_ID + 4 or struct.unpack_from(">I", raw)[0] != ALERT_VT:
            return None
        alert = struct.unpack_from(">I", raw, ALERT_ID)[0]
        if not alert:
            return None
        # The alert can finish or be recycled between independent RAM reads. The native state
        # bytes are compared for stability, not assigned an unverified generic ready-state meaning.
        if (u32(m, unit) != ALERT_VT or u32(m, unit + ALERT_ID) != alert
                or m.rd(unit + 0x16, 2) != raw[0x16:0x18]):
            return {"where": "alert", "cursor": None, "target": None}
        state = raw[0x16:0x18].hex()
        return {"where": ALERTS.get(alert, "alert"), "cursor": None, "target": None,
                "alert_unit": unit, "alert_id": alert, "alert_state": state,
                "confirmation": alert in (8, 9), "confirmation_token": ["alert", unit, alert, state]}
    except (OSError, ValueError, TypeError, struct.error):
        return None


def result_notice_screen(m, ui=None) -> dict | None:
    """The exact Mercs unlock-page state; a result class alone never authorizes Cross."""
    if m is None:
        return None
    out = None
    try:
        # This reader runs only at round boundaries; result/menu units are not restricted to HUD lines.
        ui = ui_units(m, range(N_LINES)) if ui is None else ui
        unit = ui.get("uIdMerceEd00")
        if not ptr_ok(unit):
            return None
        out = {"where": "results_wait", "cursor": None, "target": None,
               "result_unit": unit, "result_menu_verified": False, "unlock_ready": False}
        raw = m.rd(unit, 0x29C)
        if len(raw) != 0x29C or struct.unpack_from(">I", raw)[0] != MERCE_END_VT:
            return out
        inner, outer = raw[0x16:0x18]
        mask, index = struct.unpack_from(">II", raw, 0x290)
        out = {"where": "results_wait", "cursor": None, "target": None,
               "result_unit": unit, "result_outer": outer, "result_inner": inner,
               "unlock_mask": mask, "unlock_index": index, "unlock_ready": False,
               "result_menu_verified": False, "confirmation": False,
               "confirmation_token": ["merce_result", unit, outer, inner, mask, index]}
        if outer not in (MERCE_NOTICE_STATE, MERCE_FINAL_STATE) \
                or any(m.rd(address, len(code)) != code for address, code in MERCE_NOTICE_CODE):
            return out
        confirm_pad = u32(m, S_BIOPAD)
        cross_confirm = ptr_ok(confirm_pad) and u32(m, confirm_pad + PAD_CONFIRM) == 0x4000
        check = m.rd(unit, 0x29C)
        if (len(check) != len(raw) or check[:4] != raw[:4] or check[0x16:0x18] != raw[0x16:0x18]
                or check[0x28C:0x299] != raw[0x28C:0x299]):
            return out
        out["result_menu_verified"] = True
        if outer == MERCE_FINAL_STATE:
            out["where"] = "results"  # retain the existing final-result Start action
            return out
        out.update(where="unlock_wait", confirmation=True)
        ready = (inner == 3 and raw[0x298] == 1 and raw[0x28C:0x290] == bytes.fromhex("3dcccccd")
                 and 0 <= index < 24 and mask & ~0x00FFFFFF == 0 and mask & (1 << index) != 0
                 and cross_confirm and u32(m, S_BIOPAD) == confirm_pad
                 and u32(m, confirm_pad + PAD_CONFIRM) == 0x4000)
        if ready and (u32(m, unit) == MERCE_END_VT and m.rd(unit + 0x16, 2) == b"\x03\x06"
                      and m.rd(unit + 0x28C, 13) == raw[0x28C:0x299]):
            out.update(where="unlock_notice", unlock_ready=True)
        return out
    except (OSError, ValueError, TypeError, struct.error):
        return out


def screen(m, merc=None) -> dict:
    """The deployment's menus interface (gbox/mercs_bot.py): where RE5 is, read from RAM. In a round: playing / dead /
    results (the round's own fields). Out of one (no player), from the interface units: the title's dialogs
    (alert_signin, alert_ok), title (PRESS START), main_menu / play_game / extra_content (with cursor and target),
    reunion_title, reunion_solo, select_stage, select_player, loading, menu (the title's menus between those: wait),
    results (the clock at 0 and none of those up)."""
    snap = snapshot(m)
    out = {"where": own_screen(snap), "cursor": None, "target": None}
    ui = ui_units(m, range(N_LINES))
    alert = alert_screen(m, ui)
    if alert is not None:
        return alert | {"ui": sorted(ui)}
    notice = result_notice_screen(m, ui)
    if notice is not None:
        return notice | {"ui": sorted(ui)}
    if out["where"] == "dead":
        return continue_screen(m, ui)
    if snap.get("player"):
        if out["where"] == "playing" and (ROSTER.pick is not None or ROSTER.round is None):
            mode, index = snap.get("mercenaries_mode"), snap.get("character_index")
            if mode in MODE_ROSTERS and isinstance(index, int) and 0 <= index < len(MODE_ROSTERS[mode]):
                ROSTER.set_mode(mode)
                ROSTER.pick = index
                if getattr(m, "adapter", None) is not None and 0 <= snap.get("stage_index", 99) < 8:
                    coverage().started(mode, MODE_ROSTERS[mode][index], snap["stage_index"])
            out["character"] = ROSTER.started()
        return out
    if "uIdGameover00" in ui:
        return continue_screen(m, ui)
    plan = coverage().choose() if getattr(m, "adapter", None) is not None else None
    mode = snap.get("mercenaries_mode")
    if mode in MODE_ROSTERS:
        ROSTER.set_mode(mode)
    if plan is not None:
        out.update(next_mode=plan["mode"], mode_mismatch=mode in MODE_ROSTERS and mode != plan["mode"],
                   stage_target=STAGE_NAMES[plan["stage"]])
    where, cursor, target = "unknown", None, None
    if "uIdStartUp22" in ui:
        if plan is not None and plan["mode"] == ROSTER.mode:
            ROSTER.pick = ROSTER.characters.index(plan["character"])
        where, cursor, target = "select_player", u32(m, ui["uIdStartUp22"] + SELECT_CURSOR), ROSTER.want()
        out.update(mercenaries_mode=ROSTER.mode, character_target=ROSTER.characters[target],
                   character_cursor=ROSTER.characters[cursor] if 0 <= cursor < len(ROSTER.characters) else None,
                   character_roster=list(ROSTER.characters),
                   character_cursor_verified=ROSTER.confirmed == target)
    elif "uIdStartUp21" in ui:
        where = "select_stage"
        cursor = u32(m, ui["uIdStartUp21"] + MENU_CURSOR)
        if not 0 <= cursor < 8: cursor = None
        target = plan["stage"] if plan is not None else None
    elif "uIdStartUp29" in ui:
        where = "reunion_solo" if u32(m, ui["uIdStartUp29"] + MENU_SUB) == 1 else "reunion_title"
    elif "uIdStartUp20" in ui:
        where = "mercs_solo" if u32(m, ui["uIdStartUp20"] + MENU_SUB) == 1 else "mercs_title"
    elif "uIdStartUp01" in ui:
        u = ui["uIdStartUp01"]
        if u32(m, u + MENU_SUB) == 1:
            where, cursor, target = "extra_content", u32(m, u + EXTRA_CURSOR), EXTRA_REUNION
        else:
            where, cursor, target = "play_game", u32(m, u + MENU_CURSOR), PLAY_EXTRA_CONTENT
            if plan is not None and plan["mode"] == "mercenaries": target = 6
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
    out.update(where=where, cursor=cursor, target=target, ui=sorted(ui),
               confirmation_boundary=where in ("select_player", "mercs_title", "mercs_solo",
                                                "reunion_title", "reunion_solo", "extra_content"))
    return out


STEPS = {"results": "start", "select_stage": "cross", "title": "start",
         "alert_signin": "circle", "alert_ok": "cross", "reunion_title": "cross", "reunion_solo": "cross"}
BOOT_KEY = "cross"      # out of a round, a screen RAM can't name (the cold boot's HDD notice, logos): mercs_bot.Boot
CURSORED = ("main_menu", "play_game", "extra_content", "select_player")
CHARACTERS = ("Chris (Heavy Metal)", "Sheva (Fairy Tale)", "Josh", "Excella", "Chris (Warrior)", "Sheva (Business)",
              "Barry", "Rebecca")                   # CHARACTER SELECT's row, cursor 0..7 (uIdStartUp22 +0x180)
ORIGINAL_CHARACTERS = ("Chris (BSAA)", "Chris (Safari)", "Chris (STARS)", "Sheva (BSAA)",
                       "Sheva (Clubbin)", "Sheva (Tribal)", "Jill (BSAA)", "Jill (Battle Suit)",
                       "Wesker (Midnight)", "Wesker (STARS)")
MODE_ROSTERS = {"mercenaries": ORIGINAL_CHARACTERS, "reunion": CHARACTERS}
STAGE_NAMES = ("Public Assembly", "The Mines", "Village", "Ancient Ruins", "Experimental Facility",
               "Missile Area", "Ship Deck", "Prison")
_COVERAGE = None


def coverage():
    global _COVERAGE
    if _COVERAGE is None:
        from .. import lessons
        from ..curriculum import Coverage
        _COVERAGE = Coverage(lessons.ROOT.parent / "re5-coverage.json", MODE_ROSTERS, range(8))
    return _COVERAGE
SELECT_CURSOR = 0x180


class Roster:
    """A random character each round (operator 2026-10-21: "I want to see every character whooping ass"): the next
    pick is drawn among the characters played least so far, never the one just played; the per-character tallies
    (rounds, kills, points, best combo) go to stats. Module state: the menus are read through module functions."""

    def __init__(self, rng=None):
        import random
        self.rng = rng or random.Random()
        self.characters, self.mode = CHARACTERS, "reunion"
        self.pick = None                       # the cursor target for the coming round
        self.confirmed = None                  # matching RAM cursor when the confirmation press was sent
        self.last = None                       # the character of the last round started
        self.played: dict = {c: 0 for c in CHARACTERS}
        self.tally: dict = {}                  # name -> {"rounds", "kills", "points", "combo"}
        self.round = None                      # (name, best combo seen) while a round runs

    def set_mode(self, mode):
        if mode not in MODE_ROSTERS: return
        if mode != self.mode:
            self.characters, self.mode = MODE_ROSTERS[mode], mode
            self.pick, self.confirmed = None, None
            for name in self.characters: self.played.setdefault(name, 0)

    def want(self) -> int:
        if self.pick is None:
            self.confirmed = None
            least = min(self.played[c] for c in self.characters if c != self.last)
            pool = [i for i, c in enumerate(self.characters) if self.played[c] == least and c != self.last]
            self.pick = self.rng.choice(pool)
        return self.pick

    def started(self) -> str:
        """A round is up: the pick played (or the last one again when nothing was picked: a Continue)."""
        name = self.characters[self.pick] if self.pick is not None else (self.last or self.characters[0])
        if self.round is None or self.round[0] != name or self.pick is not None:
            self.played[name] += 1
            self.round = [name, 0]
        self.last, self.pick = name, None
        return name

    def confirm(self, cursor) -> bool:
        """Record a confirmation only at the requested RAM cursor, never from a guessed press count."""
        if self.pick is None or cursor != self.pick:
            return False
        self.confirmed = cursor
        return True

    def observe(self, snap: dict) -> dict:
        """The live round's counters into the character's tally; returns the stats fields."""
        if self.round is None:
            return {}
        name = self.round[0]
        self.round[1] = max(self.round[1], snap.get("combo") or 0)
        t = self.tally.setdefault(name, {"rounds": 0, "kills": 0, "points": 0, "combo": 0})
        t.update(rounds=self.played[name], kills=snap.get("kills") or t["kills"], points=snap.get("score") or t["points"],
                 combo=max(t["combo"], self.round[1]))
        return {"character": name, "mercenaries_mode": self.mode,
                "character_cursor_verified": self.confirmed is not None and self.confirmed < len(self.characters)
                    and self.characters[self.confirmed] == name,
                "character_roster_size": len(self.characters),
                "char_tally": "; ".join(f"{c}: {v['rounds']}r {v['kills']}k {v['points']}p c{v['combo']}"
                                                          for c, v in self.tally.items())}


ROSTER = Roster()


class StagePick:
    """A random stage each visit to STAGE SELECT (operator 2026-10-22: "have the bot go between the stages randomly
    during the select and have him play on different levels"). RAM doesn't name the stage cursor yet, and the row does
    not wrap (live: the bot stuck on the last stage, "unable to go back to any previous level because they're at the
    end of the list"): so every visit first walks left MAX_MOVES times, which parks the cursor on the first stage
    from anywhere, then right a random 0..MAX_MOVES before cross. mercs_bot's Navigator reports each press it sends
    (pressed()), so a press held back for a settle never counts."""
    MAX_MOVES = 7                              # Reunion's eight stages: the row's length - 1

    def __init__(self, rng=None):
        import random
        self.rng = rng or random.Random()
        self.plan = None                       # the presses still to make on this visit; None: not on STAGE SELECT
        self.last = self.target = None

    def key(self, scr: dict) -> str | None:
        if scr.get("target") is not None:
            # A requested stage must never fall through to a different random
            # stage merely because its native cursor is temporarily unreadable.
            if type(scr.get("cursor")) is not int or not 0 <= scr["cursor"] <= self.MAX_MOVES \
                    or type(scr["target"]) is not int or not 0 <= scr["target"] <= self.MAX_MOVES:
                return None
            self.target = scr["target"]
            return "cross" if scr["cursor"] == self.target else "dright" if scr["cursor"] < self.target else "dleft"
        if self.plan is None:
            self.target = self.rng.choice([i for i in range(self.MAX_MOVES + 1) if i != self.last])
            self.plan = ["dleft"] * self.MAX_MOVES + ["dright"] * self.target
        return self.plan[0] if self.plan else "cross"

    def pressed(self, scr: dict, key: str) -> None:
        if scr.get("where") == "select_stage" and scr.get("cursor") is not None and scr.get("target") is not None:
            if key == "cross" and scr.get("cursor") == scr.get("target"):
                self.last, self.target, self.plan = scr["cursor"], scr["target"], None
            return
        if scr.get("where") != "select_stage" or self.plan is None:
            return
        if self.plan and key == self.plan[0]:
            self.plan.pop(0)
        elif key == "cross":
            self.last = self.target
            self.plan = None                   # the stage is taken: the next visit draws again


STAGE_PICK = StagePick()


def pressed(scr: dict, key: str) -> None:
    """mercs_bot's Navigator: a key it sent on this screen."""
    STAGE_PICK.pressed(scr, key)
    if scr.get("where") == "select_player" and key == "cross":
        ROSTER.confirm(scr.get("cursor"))


def step(scr: dict) -> str | None:
    """The one press towards the next round. From the title: START, circle on the sign-in question, cross on "Load
    successful", then the cursor (read from RAM) moved to PLAY GAME, EXTRA CONTENT, THE MERCENARIES REUNION and taken,
    START and SOLO on Reunion's title. Between rounds: START leaves the results, cross takes the stage and the
    character the cursors are on (the last ones played). On the input-ready Continue dialog, Right selects No and
    Cross is allowed only after RAM confirms No, returning through save confirmation to stage/character selection."""
    where = scr.get("where")
    if where == "unlock_notice":
        return "cross" if scr.get("unlock_ready") is True else None
    if where == 'dead':
        if scr.get("continue_ready") is not True or type(scr.get("cursor")) is not int:
            return None
        return "cross" if scr["cursor"] == CONTINUE_NO else "dright" if scr["cursor"] == 0 else None
    if where == "extra_content" and scr.get("next_mode") == "mercenaries":
        return "circle"
    if scr.get("mode_mismatch") and where in ("select_stage", "select_player", "reunion_title", "reunion_solo", "mercs_title", "mercs_solo"):
        return "circle"
    if where in ("mercs_title", "mercs_solo"):
        return "cross"
    if where in CURSORED:
        cur, tgt = scr.get("cursor"), scr.get("target")
        if cur is None or tgt is None:
            return None
        if cur == tgt:
            return "cross"
        if where == "select_player":                     # the characters' row: left / right
            if not (isinstance(cur, int) and 0 <= cur < len(ROSTER.characters)):
                return None
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
MINE_VTABLES = frozenset({0x015B44B8, 0x0162E5F8, 0x01629DB0})  # live getDTI: uIt050A, uWp0a, uWpMine
LOOSE_ITEM_PICKUP = 0x3B
PLACE_LABEL = 0x64  # L1 Place belongs exclusively to the mine controller, never the prompt presser
PICKUP_LABEL = 1  # live Square Pick up; target is a small item handle (36/39), not an actor pointer
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
    if player_index(m) != 0:
        return False                        # the solo self-recovery callback is not co-op revival
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


def selected_prompt(m, *, include_item_pickups=False):
    """The scoped player's displayed input request, verified against the immutable mask table.

    sActionButton+0x34 is an array count, not HUD flags. Its two selected display units carry the actual input.
    The manager's player mask routes enemy-owned grab buttons too; button ownership is not a visibility test.
    FUN000B8BE0 selects player-local blocks with stride 0x2E8; +2C remains global.
    """
    try:
        index = player_index(m)
        if index is None:
            return None
        shift = index * 0x2E8
        sp, ab = u32(m, S_PLAYER), u32(m, S_ACTION)
        pl = player_pointer(m)
        if not (ptr_ok(pl) and ptr_ok(ab)) or not m.rd(ab + AB_ENABLED, 1)[0] \
                or not m.rd(ab + shift + AB_PLAYER_ENABLED, 1)[0] or u32(m, ab + shift + AB_PLAYER_INDEX) != index:
            return None
        if u32(m, ab + shift + AB_INPUT_MODE) != 0 or u32(m, ab + shift + AB_ALTERNATE_CONTROLLER) != 0xFFFFFFFF:
            return None                                # fixed physical keys: exclude remapped / Move controller input
        if struct.unpack(">h", m.rd(pl + P_HP, 2))[0] <= 0:
            return None                                # terminal corpse; real solo DYING retains exactly 1 HP
        if m.rd(QTE_INPUT_TABLE, len(QTE_INPUT_SIGNATURE)) != QTE_INPUT_SIGNATURE:
            return None
        if any(m.rd(address, len(expected)) != expected for address, expected in QTE_SIGNATURES.items()):
            return None
        requests = []
        for offset in QTE_UNITS:
            unit = ab + shift + offset
            raw = m.rd(unit, 0x1C)
            btn, mode, _, mask = struct.unpack_from(">4I", raw, 0x0C)
            if not raw[4] or not raw[5] or not ptr_ok(btn):
                continue
            button = m.rd(btn, 0x74)
            kind, button_mode, priority, key_index, label = struct.unpack_from(">5I", button, 0x14)
            players = struct.unpack_from(">I", button, 0x30)[0]
            if struct.unpack_from(">I", button)[0] != QTE_BUTTON_VT \
                    or struct.unpack_from(">I", button, 0x70)[0] & 1 \
                    or not button[0x0A] or button[0x0C] or not players & (1 << index) or mode != button_mode \
                    or (mode not in QTE_MODES and mode not in QTE_STICK_MODES) or not 0 < key_index < len(QTE_MASKS) \
                    or mask != QTE_MASKS[key_index] or label > 0xFF \
                    or (label in (LOOSE_ITEM_PICKUP, PLACE_LABEL) and not include_item_pickups):
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
            if not include_item_pickups and kind == BTN_STAGE and label == PICKUP_LABEL and token == 'mash:square':
                continue
            hp = struct.unpack(">h", m.rd(pl + P_HP, 2))[0]
            countdown = struct.unpack(">f", m.rd(pl + P_DYING_TIMER, 4))[0]
            if index == 0 and QTE_MODES.get(mode) == "mash" and chord == ("circle",) and hp == 1 \
                    and math.isfinite(countdown) and countdown > 0 \
                    and u32(m, pl + P_RECOVER_BUTTON) == btn:
                token = "mash"                         # the game's explicit SOLO_DYING_RECOVER button
            # Do not answer a selection that changed during the reads above.
            if m.rd(unit, 0x1C) != raw or m.rd(btn + 0x0A, 3) != button[0x0A:0x0D]:
                continue
            requests.append((priority, offset, {"token": token, "button": btn, "kind": kind, "mode": mode,
                                                "label": label,
                                                "owner": struct.unpack_from(">I", button, BTN_OWNER)[0],
                                                "target": struct.unpack_from(">I", button, BTN_TARGET)[0]}))
        if u32(m, S_ACTION) != ab or u32(m, S_PLAYER) != sp \
                or player_index(m) != index or player_pointer(m) != pl:
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


def egg_square_blocked(m, request=None):
    """Fresh carried-ID fence: ordinary Square can eat a rotten egg.

    Only a still-selected enemy-owned/targeted combat request may use Square
    while holding136. Traversal and item-use requests first require a gun.
    None means RAM could not establish a stable equipment identity.
    """
    try:
        sp=u32(m,S_PLAYER);pl=player_pointer(m)
        if not ptr_ok(pl):return None
        rows=inventory(m,pl)
        hand=tuple((row['slot'],row['id']) for row in rows if row.get('hand'))
        if u32(m,S_PLAYER)!=sp or player_pointer(m)!=pl \
                or hand!=tuple((row['slot'],row['id']) for row in inventory(m,pl) if row.get('hand')):
            return None
        if not any(item==0x136 for slot,item in hand):return False
        if request and request.get('kind')!=BTN_STAGE and 'square' in str(request.get('token')):
            enemies=enemy_ptrs(m)
            if request.get('owner') in enemies or request.get('target') in enemies:
                latest=selected_prompt(m,include_item_pickups=True)
                keys=('token','button','kind','mode','label','owner','target')
                if latest and all(latest.get(key)==request.get(key) for key in keys):return False
        return True
    except (ValueError,OSError,struct.error,AttributeError,TypeError):return None


def prompt(m) -> str | None:
    """An explicit displayed input request, otherwise the verified grabbed-action stick escape."""
    request = selected_prompt(m)
    if request is not None:
        if 'square' in request['token'] and egg_square_blocked(m,request) is not False:
            return None
        return None if mine_pickup(m, request) else request["token"]
    pl = player_pointer(m)
    if not ptr_ok(pl):
        return None
    if m.rd(pl + P_ACTION, 1)[0] == P_GRABBED:
        return "wiggle"
    return None


def stage_prompt(m) -> bool:
    """A prompt on the stage is up (the player's own cActionButton of kind 2: a ladder, a drop, Jump over)."""
    request = selected_prompt(m)
    return bool(request and request["kind"] == BTN_STAGE and request["token"] == "mash:square"
                and not mine_pickup(m, request))


def mine_pickup(m, request):
    """Decline loose-item recovery, including player-owned requests without a target pointer.

    Label 0x64 with L1 is Place, not pickup: only the scheduled controller may press it.
    """
    if request.get('token') != 'mash:square':
        return False
    if any(
        ptr_ok(actor) and u32(m, actor) in MINE_VTABLES
        for actor in (request.get("target", 0), request.get("owner", 0))):
        return True
    if request.get('kind') == BTN_STAGE and request.get('label') == PICKUP_LABEL \
            or request.get('label') in (LOOSE_ITEM_PICKUP,PLACE_LABEL):
        from . import re5_health
        ground_health,pickup = getattr(re5_health,'ground_items',None),getattr(re5_health,'pickup_request',None)
        # A fresh exact native health handle is the sole loose-pickup exception.
        return not (callable(ground_health) and callable(pickup) and pickup(m,request,ground_health(m)))
    return False


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
    if snap.get("mercenaries_phase") == 3 and (p.get("hp") or 0) > 0:
        return "results"                              # native quota clear keeps a positive countdown
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
        self.hold_heading = re5_motion.HeadingHold()
        self.meter = re5_motion.MotionMeter()
        self.aiming_since = None
        self.pulse = 0
        self.hist: list = []
        self.hp_seen: dict = {}
        self.nav_dynamic_mines = {}
        self.health_pickup = None
        self.unstick_until = 0.0
        self.unstick_dir = 1
        self.dead_tap = 0.0
        self.bonus_fired: dict = {}            # hourglass -> seconds fired at it
        self.bonus_skip: dict = {}             # hourglass -> left alone until
        self.bonus_seen: set = set()
        self.last_timer = None
        self.route, self.route_for, self.route_at, self.route_since = None, None, 0.0, 0.0
        self.route_midpoints, self.route_stall, self.route_walk_at = False, None, None
        self.route_effort, self.route_best, self.route_command_at = 0.0, math.inf, None
        self.traversal_started, self.traversal_pressed = None, None
        self.blocked_links, self.route_failures = set(), {}
        self.blocked_until, self.blocked_goal_retries = {}, set()
        self.round_input_ready = True
        self.round_intro_timer = None
        self.nav_last_good, self.nav_recovery = None, None
        self.nav_hazards, self.nav_trail = [], []
        self.nav_sample_at = self.nav_save_at = -math.inf
        self.route_rechecks, self._following_route = 0, False
        from .. import lessons as lesson_store
        nav_path = (Path(learn_dir) if learn_dir is not None else lesson_store.ROOT) / NAV_LEARNING_FILE
        self.nav_learning = re5_nav.Learning(nav_path)
        # every round's route + decision state on a map (gbox.mercs.round_map): where he stood still, doing what, which code
        self._trace_dir = (Path(learn_dir) if learn_dir is not None else lesson_store.ROOT).parent / "round_maps" / "BLUS30491"
        self._trace, self._trace_key = None, None
        self._learn_root = Path(learn_dir) if learn_dir is not None else lesson_store.ROOT
        self._spawn_seen: dict = {}            # this round: Majini ptr -> where he was first seen (a spawn point)
        self._spawn_seen_stage = None          # ...on this stage (the stats name can change before the round resets)
        self._spawn_points: dict = {}          # stage -> the spawn points learned (SPAWNS_FILE under the learn dir)
        self._last_live_at = None              # the last tick with a living Majini: the lull clock
        self._hunt, self._hunt_visited = None, {}
        self._boss_run = None                  # the back-off from a boss under way: {key, since}
        from ..route_guidance import Guidance
        self.operator_guidance = Guidance(lesson_store.ROOT.parent.parent,'BLUS30491')
        from ..map_goals import Goals
        self.map_goals = Goals()
        from ..tour import GoalCommitment
        self.bonus_commitment = GoalCommitment()
        self.checkpoint_clear_since = None
        self.checkpoint_walk_until = 0.
        self.laserless_reacquire_until = 0.
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
        from .re5_inventory_health import Controller as InventoryHealth
        self.inventory_heal = InventoryHealth(self.stats)
        self.inventory_live_weapon = InventoryHealth(self.stats, allowed_ids={0x10F}, prefix='inventory_live_weapon')
        self.live_weapon_pickup_at = -math.inf
        self.live_weapon_rows_at, self.live_weapon_rows = -math.inf, []
        self.inventory_egg = InventoryHealth(self.stats,allowed_ids={0x136}|{
            0x100|wid for wid,spec in re5_weapons.WEAPONS.items()
            if spec.family in re5_weapons.DIRECT or spec.family=='bow'},prefix='inventory_egg')
        self.egg_requested = False
        self.egg_return_weapon = None
        self.egg_ready_at = None
        self.egg_rows_at,self.egg_rows,self.egg_pickup_at = -math.inf,[], -math.inf
        self.switch_at = -math.inf
        self.switch_pending = None
        self.switch_blocked, self.switch_failures = {}, {}
        self._idle, self._idle_walk, self._idle_n = None, None, 0
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
        self._combo_prev = 0                    # last combo count seen (a fall to 0 is a lost combo)
        self._combo_prev_window = None
        self.combo_log: list = []               # per round: {"lengths": [...], "lost": n, "lapsed": n}
        self._sight: dict = {}                  # Majini ptr -> (when, open floor between him and the player)
        self.unsighted: dict = {}               # Majini ptr -> left out of sight until (walked to instead)
        self.engaged = None                     # [ptr, laser-up s off him, blocked since, last tick] while fought
        self.pursuit = None                     # (when chosen, ptr) of the Majini being walked to
        self.dot_seen: dict = {}                # Majini ptr -> when the laser dot was last on him
        self.stats.setdefault("pursuits", 0)
        self.stats.setdefault("unsighted", 0)
        # the operator's stalemate rule (gbox.mercs.stalemate): settings in stats (stalemate_cut_enabled / _s) from the
        # launch's MercMode block; the cut itself goes through re5_mods_tool.set_clock (the verified aGame owner write)
        self.stalemate = stalemate_rule.Rule(lambda: self.stats)

    def _can_hunt(self) -> bool:
        """The spawn hunt (LULL_S / _hunt_spawns: after a lull he walks to the spawn points this stage has shown) has
        somewhere to go: a hunt is under way, or spawn points are known for this stage. False on a tree without the
        hunt, or on a stage's first round (no spawn point known yet)."""
        if getattr(self, "_hunt", None) is not None:
            return True
        spawns = getattr(self, "_stage_spawns", None)
        if not callable(spawns):
            return False
        try:
            return bool(spawns())
        except Exception:                                   # noqa: BLE001 - a lost spawn memory is no stalemate call
            return False

    def _stalemate_watch(self, snap, p, now) -> None:
        """No living Majini (crows do not count, as in combat) for STALEMATE_S - HUNT_STALEMATE_S where the spawn hunt
        can look for them first - while the clock shows more than STALEMATE_CLOCK_S: the countdown is cut to the
        configured seconds once per round; stats["stalemate_cut"] and the round map keep the clock before / after."""
        living = sum(1 for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1)
        patience = stalemate_rule.HUNT_STALEMATE_S if self._can_hunt() else stalemate_rule.STALEMATE_S
        target = self.stalemate.observe(now, living, snap.get("timer"), patience=patience)
        if target is None:
            return
        from ...re5_mods_tool import set_clock
        result = set_clock(self.m.adapter, target)
        self.stalemate.record(now, result, trace=self._trace, pos=(p or {}).get("pos"))

    # --- the engine's brain interface ---
    def prompt_ok(self, button, snap, now) -> bool:
        if getattr(getattr(self,'mines',None),'escape',None) is not None \
                and not (self.stats.get('mine_departure_yielded')
                         and self._mine_hazard_removed(self.mines.escape,snap.get('ground_mines'))) \
                and not self._mine_escape_mandatory(snap) and 'square' in str(button):
            self.stats['mine_optional_prompts_deferred'] = self.stats.get('mine_optional_prompts_deferred',0)+1
            return False
        if 'square' in str(button) and self.m is not None \
                and egg_square_blocked(self.m,selected_prompt(self.m,include_item_pickups=True)) is not False:
            self.stats['egg_square_prompts_blocked']=self.stats.get('egg_square_prompts_blocked',0)+1
            return False
        if snap.get('stage_prompt') and 'square' in str(button):
            hazards = [(row['pos'],600.) for row in (snap.get('ground_mines') or {}).values()]
            player = snap.get('player') or {}
            crossing = next((w for w in (self.route or [])[:2] if isinstance(w,re5_nav.Traversal)),None)
            if crossing is not None and player.get('pos') and math.dist(player['pos'],crossing.approach)<250. \
                    and not re5_nav.NavMesh.hazard_segment_clear(crossing,crossing,hazards):
                self.stats['route'] = 'stage action deferred: observed bomb at its measured landing'
                return False
        return self.combat.prompt_ok(button, snap, now) if self.combat is not None else True

    @staticmethod
    def _mine_escape_mandatory(snap):
        p = snap.get('player') or {}
        optional = snap.get('prompt_optional')
        return bool(snap.get('recovery_active') or p.get('action') in (4,5) or (p.get('hp') or 0)<=0
                    or snap.get('prompt') and not optional)

    @staticmethod
    def _mine_hazard_removed(escape, ground):
        """Only one exact, witnessed detonation and a currently verified clear scan may yield departure priority."""
        if not escape or not escape.get('detonation_observed') or not escape.get('removal_recorded') \
                or ground is None or not getattr(ground,'verified',True) or ground:
            return False
        retained = escape.get('hazards') or {escape['actor']:escape['pos']}
        return len(retained)==1 and tuple(retained.get(escape['actor'],()))==tuple(escape['pos'])

    def recall(self, rows):
        self.round_lessons = rows
        self.stats["prior_stage_rounds"] = len(rows)
        self.stats["prior_best_bonus_count"] = max((r["observed"].get("bonuses_taken") or 0 for r in rows), default=0)
        # Notebook.recall already hard-filters title geometry and mode. Consume only
        # bounded, explicit policy fields; prose and ranks never manufacture routes.
        reviewed = [r.get("observed", {}) for r in rows
                    if (r.get("observed", {}).get("reflection") or {}).get("policy", {}).get("bonus_commitment") is True]
        self.stats['round_policy_source_ids'] = [r['id'] for r in rows[:5]
            if isinstance(r.get('id'),str) and len(r['id']) == 32 and all(c in '0123456789abcdef' for c in r['id'])
            and (r.get('observed',{}).get('reflection') or {}).get('policy',{}).get('bonus_commitment') is True]
        stalled = any((r.get("stuck") or 0) > 0 or (r.get("nav_oscillations") or 0) > 0
                      or (r.get("motion_idle_spin_s") or 0) > 3 for r in reviewed)
        self.bonus_commitment.patience_s = 16. if stalled else 12.
        self.stats["round_policy_applied"] = "held time checkpoint; measured crossing penalties; verified floor only"
        self.stats["bonus_commitment_patience_s"] = self.bonus_commitment.patience_s

    def save(self):
        if self._control_state is not None:
            from . import re5_controls, re5_live_weapon
            re5_controls.publish(self._control_state, id(self), {}, False)
            re5_live_weapon.stop(self._control_state, getattr(self.m, 'adapter', None), id(self))
        if getattr(self.m, "adapter", None) is not None and modifications_allowed(self.m):
            from ...re5_mods_tool import maintain_fire_animation,maintain_item_animation
            maintain_fire_animation(self.m.adapter, enabled=False)
            maintain_item_animation(self.m.adapter, enabled=False)
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
        pickup = self.health_pickup
        if pickup is not None and p and p.get('ptr')==pickup['player']:
            count = sum(w.get('rounds',0) for w in snap.get('inventory') or () if w.get('id')==pickup['id'])
            if count>pickup['before']:
                self.stats['health_pickups_verified'] = self.stats.get('health_pickups_verified',0)+1
                self.stats['health_seek_status'] = 'health item inventory increase observed after exact pickup request'
                self.health_pickup = None
            elif now-pickup['at']>5.:
                self.stats['health_seek_status'] = 'health pickup inventory increase unconfirmed'
                self.health_pickup = None
        if where == "playing" and p and not self.round_active:
            self.stats["round_used_health_protection"] = False
        if snap.get("stage_prompt"):
            self._remember_traversal_prompt(now)
        priority_prompt = snap.get("prompt") and not (self.combat is not None and self.combat.optional_prompt_blocked(snap))
        if priority_prompt or snap.get("recovery_active") or (p or {}).get("action") == P_GRABBED \
                or where != "playing" or not p:
            self._interrupt_route_walk()                   # engine-owned prompt frames may never call tick()
        if self.healing is not None and (priority_prompt or snap.get("recovery_active")
                                         or (p or {}).get("action") == P_GRABBED):
            self.healing["at"] = now           # observed mandatory interruptions pause only the bounded healing window
        if getattr(self.m, "adapter", None) is not None and modifications_allowed(self.m):
            from ...re5_mods_tool import ORIG
            from . import re5_controls
            self._control_state = ORIG.setdefault(id(self.m.adapter), {})
            re5_controls.bind_adapter(self._control_state,self.m.adapter)
            re5_controls.publish(self._control_state, id(self), snap, where == "playing" and bool(p))
            from . import re5_qte
            qte = re5_qte.maintain(self.m.adapter, snap, owner=id(self), enabled=where == 'playing' and bool(p))
            self.stats['qte_native'] = qte
            self.stats['qte_native_progress_writes'] = self.stats.get('qte_native_progress_writes', 0) + qte.get('writes', 0)
            from . import re5_live_weapon
            re5_live_weapon.observe(self.m, self._control_state, snap, where)
            live = self._control_state.get('live_weapon') or {}
            if not live.get('active') and live.get('donor'):
                re5_live_weapon.queue_supply(self.m.adapter)
        if where != "playing" or snap.get("prompt") not in ("stick:rotate", "stick:x", "stick:y"):
            self._stick_token = None
        self.stats["resuscitating"] = bool(snap.get("recovery_active") or snap.get("prompt") == "mash")
        if getattr(self.m, "adapter", None) is not None and modifications_allowed(self.m):
            from ...re5_mods_tool import maintain_fire_animation,maintain_item_animation
            firing = maintain_fire_animation(self.m.adapter, snap, enabled=(where == "playing"
                and not self.stats["resuscitating"] and not snap.get("prompt") and not snap.get("stage_prompt")))
            self.stats["fire_animation_active"] = bool(firing.get("active") and firing.get("verified"))
            self.stats["fire_animation_reason"] = firing.get("reason") or ""
            self.stats["fire_animation_writes"] = self.stats.get("fire_animation_writes", 0) + firing.get("writes", 0)
            item_rates=maintain_item_animation(self.m.adapter,snap,enabled=(where=='playing'
                and not self.stats['resuscitating'] and not snap.get('prompt') and not snap.get('stage_prompt')))
            for item in ('mine','egg'):
                result=item_rates.get(item) or {}
                self.stats[item+'_animation_active']=bool(result.get('active') and result.get('verified'))
                self.stats[item+'_animation_reason']=result.get('reason',item_rates.get('error',''))
                self.stats[item+'_animation_writes']=self.stats.get(item+'_animation_writes',0)+result.get('writes',0)
        if where == "playing" and p and not self.stats["resuscitating"] and getattr(self.m, "adapter", None) is not None \
                and modifications_allowed(self.m):
            from ...re5_mods_tool import maintain_health
            health = maintain_health(self.m.adapter, snap)
            self.stats["unlimited_health_enabled"] = health.get("unlimited_health", False)
            self.stats["health_maintained"] = bool(health.get("active") and health.get("verified"))
            self.stats["hit_immunity"] = bool(health.get("hit_immunity"))
            self.stats["immunity_verified"] = bool(health.get("immunity_verified"))
            self.stats["immunity_reason"] = health.get("immunity_reason") or ""
            self.stats["round_used_health_protection"] = bool(self.stats.get("round_used_health_protection")
                or health.get("unlimited_health") and health.get("verified")
                or health.get("hit_immunity") and health.get("immunity_verified"))
            if health.get("refilled"):
                self.stats["health_refills"] = self.stats.get("health_refills", 0) + 1
            from ...re5_mods_tool import maintain_spray
            spray = maintain_spray(self.m.adapter, snap)       # the infinite First Aid Spray (playing_ops infinite_spray)
            self.stats["infinite_spray"] = bool(spray.get("infinite_spray"))
            self.stats["spray_status"] = spray.get("reason") or ("restored" if spray.get("restored") else "")
            if spray.get("restored"):
                self.stats["sprays_restored"] = self.stats.get("sprays_restored", 0) + 1
            from ...re5_mods_tool import maintain_kill_time
            bonus = maintain_kill_time(self.m.adapter, snap)    # configured per-kill seconds from playing_ops
            if bonus.get("added"):
                self.stats["kill_time_added_s"] = round(self.stats.get("kill_time_added_s", 0.0) + bonus["added"], 1)
            elif bonus.get("kill_time") and not bonus.get("verified"):
                self.stats["kill_time_reason"] = bonus.get("reason") or "write not confirmed"
            if self.round_active and not snap.get("prompt"):
                self._stalemate_watch(snap, p, now)             # a stalemate's clock cut (gbox.mercs.stalemate)
        if where != "playing" or not p:
            self.healing = None
            self.inventory_heal.reset()
            self.inventory_egg.reset()
            self.inventory_live_weapon.reset()
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
                self.trace_finish()                         # the round's map (round_maps/BLUS30491/<stage>/)
            elif self.combat is not None:
                self.combat.suspend_observation(now)
            return
        if not self.round_active:
            self.map_goals.reset()
            self.stalemate.new_round()
            from ..research_profiles import profile
            self.stats['guide_profile'] = profile('BLUS30491',snap.get('mercenaries_mode'))
            guidance = getattr(self, 'operator_guidance', None)
            if guidance is not None:
                guidance.practice_state = None
            self.health_pickup = None
            self.inventory_heal.reset()
            self.inventory_egg.reset()
            self.egg_requested=False
            self.egg_return_weapon=None
            self.egg_ready_at=None
            self.egg_rows_at,self.egg_rows,self.egg_pickup_at=-math.inf,[],-math.inf
            self.stats.pop("completed_score_rank", None)
            self.stats.pop("completed_score_rank_source", None)
            self.bonus_commitment.reset()
            self.stats['round_policy_source_ids'] = []
            self.stats['round_semantic_round_ids'] = []
            self.checkpoint_clear_since, self.checkpoint_walk_until = None, 0.
            self.laserless_reacquire_until = 0.
            if callable(getattr(getattr(self,"mines",None),"reset_round",None)):
                self.mines.reset_round(now,p.get("ptr"))
            self._round_started = now
            timer,start = snap.get("timer"),snap.get("timer_start")
            self.round_intro_timer = timer if isinstance(timer,(int,float)) and isinstance(start,(int,float)) \
                and start>0 and abs(timer-start)<.02 else None
            self.round_input_ready = self.round_intro_timer is None
            self._round_ended_at = None
            self._round_baseline = {key: self.stats.get(key, 0) for key in (
                "deaths", "heals", "headshots", "finishers", "bonus_s", "bonuses_taken", "clock_jumps", "qte_presses")}
            self._round_combo = 0
            self._combo_prev, self._combo_prev_window = 0, None
            self.combo_log.append({"lengths": [], "lost": 0, "lapsed": 0})
            if self.round_end is not None:
                self.stats["rounds"] = self.stats.get("rounds", 0) + 1
                if self.round_end == "dead":
                    self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                self.bonus_fired.clear()
                self.blocked_links.clear()
                self.blocked_until.clear()
                self.blocked_goal_retries.clear()
                self.route_failures.clear()
                self.nav_last_good = self.nav_recovery = None
                self.bonus_skip.clear()
                self.route, self.route_for, self.route_len = None, None, None
                self.climb_at = self.take_at = None
                self.climb_pos = self.climb_tick = None
                self.spawn, self.at_stand, self.stood = None, False, False
                self._spawn_remember()                      # last round's spawn points: kept for this stage
                self._spawn_seen.clear()
                self._hunt, self._hunt_visited, self._last_live_at = None, {}, None
                self._boss_run = None
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
                self.dot_seen.clear()
                self.engaged = self.pursuit = None
            self.round_active, self.round_end = True, None
            if self.combat is not None:
                self.combat.start_round(now)
        if getattr(self,'_round_player',None) is not None and self._round_player != p.get('ptr'):
            self.map_goals.reset()
        self._round_player = p.get("ptr")
        if not self.round_input_ready:
            timer = snap.get("timer")
            if isinstance(timer,(int,float)) and timer < self.round_intro_timer-.02:
                self.round_input_ready = True
        self.stats["round_input_ready"] = self.round_input_ready
        self.stats["round_intro_wait_s"] = round(now-self._round_started,2) if not self.round_input_ready else 0.
        self._expire_navigation_blocks(now)
        self._round_combo = max(self._round_combo, snap.get("combo") or 0)
        self._track_combo(snap)
        if self.combat is not None:
            self.combat.observe(snap, now)
            self.combat.observe_awareness(snap, p, now)
        mesh = snap.get("nav")
        if mesh is not None and mesh.find(p["pos"], floor_only=True, height_slack=60.) is not None:
            self.nav_last_good = tuple(p["pos"])
        self._wall_mesh=mesh
        geometry = mesh.learning_sig if mesh is not None else None
        if geometry != self.nav_geometry:
            if self.nav_geometry is not None:
                self.map_goals.reset()
            self.bonus_commitment.reset()
            self.nav_trail, self.nav_hazards = [], []
            self._wall_motion=self._blocked_detour=None
            self.blocked_links.clear()
            self.blocked_until.clear()
            self.blocked_goal_retries.clear()
            self.route, self.route_for, self.route_len = None, None, None
            self.climb_at = self.climb_pos = self.climb_tick = None
            self.nav_geometry = geometry
        self.nav_learning.observe(mesh, p["pos"], now)
        if now - self.nav_sample_at >= .5:
            self.nav_trail = (self.nav_trail + [tuple(p["pos"])])[-240:]
            self.nav_sample_at = now
        if now - self.nav_save_at >= 20.:
            self.nav_learning.save()
            self.nav_save_at = now
        self.stats.update(self.nav_learning.summary())
        self._observe_weapon_switch(snap, now)
        self._score_hits(snap)
        t = snap.get("timer")
        if self.last_timer is not None and t is not None and self.last_timer > 0 and 2 < t - self.last_timer:
            # This clock includes configured kill credits and native time bonuses.
            # The route recorder owns confirmed hourglass counts/seconds after
            # matching nearby actor removal with an independent clock gain.
            self.stats["clock_gain_s"] = round(self.stats.get("clock_gain_s", 0.0) + t - self.last_timer, 1)
            self.stats["clock_jumps"] = self.stats.get("clock_jumps", 0) + 1
        self.last_timer = t
        standing = {b["ptr"] for b in snap.get("bonuses") or ()}
        taken = self.bonus_seen - standing
        if taken:
            self.stats["bonus_actor_removals"] = self.stats.get("bonus_actor_removals", 0) + len(taken)
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
            observed.update(round_shots=self.combat.round_counts["shots"],
                            round_hits=None if getattr(self.combat, 'damage_unattributed', False)
                            else self.combat.round_counts["hits"])
        self.stats["round_evaluation"] = re5_strategy.evaluate_round(observed)
        if snap.get('control_player') == 2 or snap.get('scoring_players') == 2:
            self.stats['round_evaluation']['score_scope'] = 'team'
            self.stats['round_evaluation']['damage_attribution'] = 'unattributed_multiple_players'

    def _observe_result(self, snap):
        """Retain terminal RAM totals while the results tally finishes; no UI rank is inferred."""
        p, timer = snap.get("player") or {}, snap.get("timer")
        if not (self.round_active or self.round_end == "results") or not self._round_player \
                or p.get("ptr") != self._round_player or not isinstance(timer, (int, float)) \
                or not math.isfinite(timer) or (timer > 0 and snap.get("mercenaries_phase") != 3):
            return
        # Result/menu teardown can clear counters before sPlayer disappears. Never replace a known total with that.
        for key in ("score", "kills"):
            value, prior = snap.get(key), self.stats.get(key)
            if type(value) is int and 0 <= value <= 0x7FFFFFFF \
                    and (not isinstance(prior, (int, float)) or value >= prior):
                self.stats[key] = value
        self.stats["timer"] = max(0., timer)
        self.stats["mercenaries_phase"] = snap.get("mercenaries_phase")
        self.stats["finished_naturally"] = bool(snap.get("mercenaries_phase") == 3 and (self.stats.get("kills") or 0) >= 150)
        combo = snap.get("combo")
        if type(combo) is int and 0 <= combo <= 0x7FFFFFFF:
            self.stats["max_combo"] = max(self.stats.get("max_combo", 0), combo)
        if snap.get('control_player') == 2 or snap.get('scoring_players') == 2:
            # Shared DUO totals do not use solo rank thresholds, and the global
            # menu roster cannot identify the controlled teammate's costume.
            for key in ('rank', 'completed_score_rank', 'completed_score_rank_source'):
                self.stats.pop(key, None)
            self.stats.update(scoring_scope='team', score_scope='team', kills_scope='team', combo_scope='team',
                              character='unknown', character_cursor_verified=False,
                              character_source='native_per_player_roster_unverified')
            return
        rank = rank_of(self.stats.get("score"))
        if rank:
            self.stats["rank"] = rank
            self.stats["completed_score_rank"] = rank
            self.stats["completed_score_rank_source"] = "terminal_ram_score_and_solo_thresholds"
        self.stats.update(ROSTER.observe({"score": self.stats.get("score"), "kills": self.stats.get("kills"),
                                          "combo": self.stats.get("max_combo")}))

    def plan(self) -> dict:
        """What the bot is doing, for the tactical map (gbox/mercs/tactical.py): no RAM reads, only state held."""
        walking = self.route if self.stats.get("phase") in ("gather_time", "break_for_time", "stand", "pursue", "leave_proximity_bomb", "practice_human_route", "operator_collect", "operator_collect_item") else None
        nb = None
        if self.route_len:
            ptr, d = min(((k, v) for k, v in self.route_len.items() if v is not None), key=lambda kv: kv[1],
                         default=(None, None))
            if ptr is not None:
                nb = {"id": ptr, "kind": "time", "dist": round(d), "eta_s": round(d / RUN_SPEED, 1)}
        recovery = getattr(self,'_blocked_detour',None)
        if recovery and self.clock() < recovery['until']:
            walking = recovery['route']
        observed = self.nav_learning.approach_obstacles(getattr(self,'_wall_mesh',None))
        return {"phase": self.stats.get("phase"), "target": self.plan_target,
                "goal_round": self.map_goals.round, "goal_capabilities": ['bonus', 'item'],
                "operator_goal": self.map_goals.public(),
                "trail": list(self.nav_trail), "hazards": (list(self.nav_hazards)+observed)[-64:],
                "enemy_awareness": getattr(self.combat, "awareness", []),
                "route": [tuple(w) for w in walking] if walking else None,
                "stand": {"pos": self.spawn, "r": STAND_R} if self.spawn else None,
                "nearest_bonus": nb, "enemy_flags": dict(self.flags),
                "note": str(self.stats.get("bonus_target") or self.stats.get("aim") or "")[:80]}

    def receive_map_goal(self, value):
        self.map_goals.receive(value, self.clock())

    def _idle_breakout(self, snap, act):
        """Stationary decisions invalidate the cached plan, never authorize blind movement."""
        p, now = snap.get("player"), self.clock()
        if not p or snap.get("prompt") or snap.get("stage_prompt") or (p.get("hp") or 1) <= 0:
            self._idle = self._idle_walk = None
            return act
        act = self._avoid_observed_blockage(snap,act,now)
        pos = tuple(p["pos"])
        activity = (self.stats.get("damage_events", 0), self.stats.get("kills_seen", 0), self.at_stand)
        self._idle_walk = None
        if self._idle is None or self._idle[2] != activity or math.dist(pos, self._idle[0]) >= STUCK_MOVE:
            self._idle = (pos, now, activity)
            return act
        if now - self._idle[1] >= IDLE_S and not self.at_stand:
            self._idle = (pos, now, activity)
            self.route_at, self.route_len = -math.inf, None
            self.stats["idle_route_replans"] = self.stats.get("idle_route_replans", 0) + 1
            self.stats["route"] = "stationary: discarding stale route; awaiting supported movement"
        return act

    def _avoid_observed_blockage(self,snap,act,now):
        """Remember failed movement across goal changes; probe only supported local floor."""
        p,mesh = snap.get('player'),snap.get('nav')
        if not p or mesh is None or not callable(getattr(mesh,'floor_segment',None)) \
                or p.get('action') not in (0,1) or snap.get('recovery_active'):
            self._wall_motion = self._blocked_detour = None
            return act
        self._wall_mesh = mesh
        pos = tuple(p['pos']);keys=set(act.get('hold',()))
        owner = (getattr(mesh,'learning_sig',None),p.get('ptr'))
        motion = getattr(self,'_wall_motion',None)
        if not motion or motion['owner']!=owner or not 0<=now-motion['at']<=.5 \
                or math.dist(pos,motion['origin'])>=STUCK_MOVE or now-motion['walking_at']>2.:
            motion={'owner':owner,'at':now,'origin':pos,'effort':0.,'forward':False,'walking_at':now}
        elif motion['forward']:
            motion['effort'] += now-motion['at']
        toward = (pos[0]+200.*math.sin(p['rot']),pos[1],pos[2]+200.*math.cos(p['rot']))
        target = self.route[0] if self.route and not isinstance(self.route[0],re5_nav.Traversal) \
            else (self.plan_target or {}).get('pos') or toward
        if abs(target[1]-pos[1])>60.:target=toward
        # #3451: when plan_target is None the fallback target equals `toward`,
        # so detour(pos, target, ...) is a zero-length search that returns
        # None, leaving the player holding position until the 16 s bonus_skip
        # re-tries the same walk — "pushed into the same wall again and again".
        # Guard the detour call: only run A* when the goal is meaningfully
        # different from the player position.
        eligible = 'lup' in keys and not keys.intersection({'l1','r1','l2'}) and not act.get('tap')
        if eligible and motion['effort']>=1.4:
            context=self.nav_learning.obstruction(mesh,pos,target,'stationary commanded movement across decisions',
                approach=toward,native_ray=snap.get('laser'))
            if context:
                self.stats['nav_obstruction_context']=context
                self.stats['nav_boundary_traces']=self.stats.get('nav_boundary_traces',0)+1
                self.stats['observed_blocked_approaches']=self.stats.get('observed_blocked_approaches',0)+1
                self.nav_learning.save()
            self.route=self.route_for=self.route_len=None
            self.route_at=-math.inf
            self._blocked_detour=None;motion['effort']=0.
            act={'hold':set()};eligible=False
        blocks=self.nav_learning.approach_obstacles(mesh)
        recovery=getattr(self,'_blocked_detour',None)
        goal=(self.plan_target or {}).get('kind'),(self.plan_target or {}).get('id')
        if recovery and (recovery['owner']!=owner or recovery['goal']!=goal or now>=recovery['until']):
            recovery=self._blocked_detour=None
        maneuver_allowed=not keys.intersection({'l1','r1','l2'}) and not act.get('tap')
        if (eligible or recovery and maneuver_allowed) and (recovery or not obstacle_map.clear_segment(pos,toward,blocks)):
            hazards=[(row['pos'],600.) for row in self.nav_dynamic_mines.values()]
            supported=lambda a,b:mesh.floor_segment(a,b,blocked_links=self.blocked_links)
            safe=lambda a,b:mesh.hazard_segment_clear(a,b,hazards,departing=True)
            if recovery is None:
                def project(point):
                    node=mesh.find(point,floor_only=True,height_slack=60.)
                    if node is None:return None
                    height=mesh._height(node,point[0],point[2])
                    return (point[0],height,point[2]) if height is not None else None
                # #3451: skip the degenerate zero-length case where target
                # fell back to `toward` (plan_target was None at this moment).
                if math.dist(pos, target) >= 10.:
                    route=obstacle_map.detour(pos,tuple(target),blocks,project=project,supported=supported,hazard_clear=safe)
                else:
                    route=None
                if route:
                    recovery=self._blocked_detour={'owner':owner,'goal':goal,'until':now+8.,'route':route}
                    self.stats['local_obstacle_detours']=self.stats.get('local_obstacle_detours',0)+1
            if recovery:
                while recovery['route'] and math.dist(pos,recovery['route'][0])<20.:
                    recovery['route'].pop(0)
                if recovery['route']:
                    waypoint=recovery['route'][0]
                    if supported(pos,waypoint) and safe(pos,waypoint) and obstacle_map.clear_segment(pos,waypoint,blocks):
                        error=wrap(heading(waypoint[0]-pos[0],waypoint[2]-pos[2])-p['rot'])
                        detour_keys=self._turn(error,aiming=False)
                        if abs(error)<=TURN_TOL:detour_keys|={'lup'}
                        act={'hold':detour_keys}
                        self.stats['phase']='obstacle_detour'
                        self.stats['route']='following supported local floor around an observed blocked approach'
                    else:
                        self._blocked_detour=None;act={'hold':set()}
                else:self._blocked_detour=None
            else:
                act={'hold':set()}
                self.stats['route']='observed approach blocked; no supported local detour, movement released'
                deferred = self.route_for
                if deferred is None and (self.plan_target or {}).get('kind') in ('time','combo'):
                    deferred=self.plan_target.get('id')
                if deferred is not None:self.bonus_skip[deferred]=now+16.
                self.route=self.route_for=self.route_len=None
                self.route_at=-math.inf
                self.map_goals.defer('Observed approach is blocked; waiting for a supported alternative')
        motion['at'],motion['forward']=now,'lup' in act.get('hold',())
        if motion['forward']:motion['walking_at']=now
        self._wall_motion=motion
        return act

    def _round_trace(self, snap) -> None:
        """One RoundTrace per round (a new combo_log entry = a new round): samples position, decision state and ground
        mines each tick; the finished round's map is written when the next one starts or the bot stops."""
        from ..round_map import RoundTrace, code_map
        key = len(self.combo_log)
        if key != self._trace_key:
            self.trace_finish()
            self._trace_key = key
            self._trace = RoundTrace(self._trace_dir / "stage", "BLUS30491", "stage", uuid.uuid4().hex, 400.0,
                                     code=code_map(PHASE_CODE, Bot, re5_combat.Combat))
        p = snap.get("player")
        if self._trace is not None and p:
            mines = [row["pos"] for row in (snap.get("ground_mines") or {}).values()
                     if isinstance(row, dict) and row.get("pos")]
            self._trace.add(self.clock(), p["pos"][0], p["pos"][2], p["pos"][1], self.stats, mines)

    def trace_finish(self) -> None:
        self._spawn_remember()                               # the round's spawn points outlive the bot (a stop, too)
        trace, self._trace = self._trace, None
        if trace is None:
            return
        stage = str(self.stats.get("stage") or "stage").replace("/", "-").replace(" ", "_")
        trace.room = stage
        if trace.out_dir is not None:
            trace.out_dir = trace.out_dir.parent / stage
        summary = trace.finish()
        if summary:
            self.stats["last_round_map"] = (summary.get("files") or [None])[-1]
            self.stats["last_round_verdict"] = summary.get("verdict")

    def tick(self, snap: dict) -> dict:
        self.stats['mine_departure_yielded'] = False
        try:
            self._round_trace(snap)
        except Exception as exc:                                  # noqa: BLE001 - the map never stops the bot
            self.stats["round_map_error"] = f"{type(exc).__name__}: {exc}"[:160]
        self.map_goals.defer('Waiting for mandatory action, healing, mine retreat or nearby threats to clear')
        self._following_route = False
        p = snap.get("player")
        if p:
            self.meter.observe(self.clock(), p["pos"], p["rot"])
            self.stats.update({"motion_" + k: v for k, v in self.meter.summary().items()})
        try:
            if self.m is not None and player_index(self.m) != 0:
                # A human may plant at the same time. Nearby new mine actors
                # currently carry no verified planter identity, so P2 must not
                # run the solo placement/credit controller or inherit P1 mods.
                self._control_state = None
                self.mines = None
                self.stats['mine_status'] = 'Player 2 automatic placement awaits native planter ownership'
                if player_index(self.m) != 1 or not p or player_pointer(self.m) != p.get('ptr'):
                    return {'hold': set()}
                self.nav_dynamic_mines = snap.get('ground_mines') or {}
                return self._leave_deployed_mines(self._idle_breakout(snap, self._tick(snap)))
            from . import re5_mines
            if getattr(self, "mines", None) is None:
                self.mines = re5_mines.Controller(self.m, self.stats, self._switch_weapon)
            self.mines.preferred_gun=self._preferred_gun
            if own_screen(snap) == "playing":
                self.observe_round(snap,"playing",self.clock())
                if not self.round_input_ready:
                    self.stats["phase"] = "waiting_round_start"
                    return {"hold":set()}
                self._observe_weapon_switch(snap, self.clock())
                snap["ground_mines"] = re5_mines.ground_mines(self.m)
                self.nav_dynamic_mines = snap["ground_mines"]
                placement_safe = self._mine_placement_preflight(snap,self.clock())
                egg_mode=bool((self._control_state or {}).get('rotten_eggs',{}).get('on'))
                snap['rotten_egg_only']=egg_mode
                if egg_mode:
                    placement_safe,snap['mine_placement_safe']=False,False
                hp,hp_max = p.get('hp') or 0,p.get('hp_max') or 0
                heal_needed = self.healing is not None or self.inventory_heal.active \
                    or hp_max>0 and 1<hp<=HEAL_AT*hp_max and self._heal_safe(p,snap,hp,hp_max)
                if heal_needed:
                    placement_safe,snap['mine_placement_safe'] = False,False
                mine_action = self.mines.tick(snap, self.clock())
                mandatory = self._mine_escape_mandatory(snap)
                if self.mines.escape is not None and not mandatory:
                    escape_action = self._mine_retreat(p,snap,self.clock())
                    if escape_action is not None:
                        # A gun restore can happen while leaving, but its neutral
                        # animation wait must not hold the player beside a bomb.
                        if mine_action and mine_action.get("tap") in QUICK.values():
                            escape_action = {"hold":set(escape_action.get("hold",())) | {mine_action["tap"]}}
                        return self._leave_deployed_mines(escape_action)
                if heal_needed and not mandatory:
                    heal_action = self._heal(p,snap,self.clock())
                    if heal_action is None:
                        heal_action = self._seek_health(p,snap,self.clock())
                    if heal_action is not None:
                        self.mines.prepare_at = None
                        self.bonus_commitment.pause(self.clock())
                        return self._leave_deployed_mines(heal_action)
                if mine_action is not None:
                    if not placement_safe and self.mines.pending is not None:
                        mine_action = {"hold":set(mine_action.get("hold",()))-{"l1","r1"}}
                    return self._leave_deployed_mines(mine_action)
                if not placement_safe and not mandatory and self.mines.pending is None and self.mines.escape is None:
                    hand = equipped(snap)
                    if hand is not None and hand.get("id")==0x10A:
                        gun = self._preferred_gun(snap) or next((w for w in snap.get("inventory",()) if re5_weapons.quick_key(w)
                                    and w.get("type")==1 and w.get("item") in re5_weapons.WEAPONS
                                    and re5_weapons.WEAPONS[w["item"]].family in re5_weapons.DIRECT),None)
                        if gun is not None:
                            self.mines.retry_at = self.clock()+2.
                            return self._switch_weapon(gun,self.clock(),"unsafe mine deployment; return to gun") or {"hold":set()}
            act = self._idle_breakout(snap, self._tick(snap))
            if self.mines.cadence.only and self.mines.cadence.enabled and not snap.get('rotten_egg_only'):
                if "r1" in act.get("hold", ()):
                    act = {"hold": set(act.get("hold", ())) - {"l1", "r1"}}
            return self._leave_deployed_mines(act)
        finally:
            if not self._following_route or not getattr(self, "_route_learn", True):
                self.bonus_commitment.pause(self.clock())
            if not self._following_route:
                self._interrupt_route_walk()

    def _interrupt_route_walk(self):
        """Combat, item selection and QTE input break continuous route-motion evidence, even for a single tick."""
        self.bonus_commitment.pause(self.clock())
        if self.route_walk_at is not None:
            self.hist, self.route_stall, self.route_walk_at = [], None, None
            self.route_command_at = None
            self.unstick_until, self.stuck_since = 0.0, None
            self.climb_at = self.climb_pos = self.climb_tick = None

    def _leave_deployed_mines(self, act):
        # Bonus punches and herb-use actions also use Square. Check their final input,
        # since a nearby mine can become the game's selected interaction after planning.
        if self.m is None or (act.get("tap") != "square" and "square" not in act.get("hold", ())):
            return act
        request = selected_prompt(self.m, include_item_pickups=True)
        if request and mine_pickup(self.m, request):
            self.stats["mine_pickups_avoided"] = self.stats.get("mine_pickups_avoided", 0) + 1
            return {"hold": set(act.get("hold", ())) - {"square"}}
        blocked=egg_square_blocked(self.m,request)
        snap=getattr(self,'_observed_snap',None) or {}
        if blocked is not False:
            self.stats['egg_square_uses_blocked']=self.stats.get('egg_square_uses_blocked',0)+1
            self.stats['egg_status']='Square deferred until an existing gun is confirmed; rotten eggs are thrown only'
            if blocked is True and hasattr(self,'inventory_egg'):
                try:
                    pl=player_pointer(self.m)
                    if not ptr_ok(pl):
                        return {'hold':set(act.get('hold',()))-{'square'}}
                    player=dict(snap.get('player') or {})
                    player.update(ptr=pl,pos=struct.unpack('>3f',self.m.rd(pl+P_POS,12)),
                        hp=struct.unpack('>h',self.m.rd(pl+P_HP,2))[0],
                        action=self.m.rd(pl+P_ACTION,1)[0])
                    fresh=dict(snap,player=player,inventory=inventory(self.m,pl))
                    return self._egg_action(player,fresh,self.clock(),for_square=True) or {'hold':set()}
                except (ValueError,OSError,struct.error,TypeError):pass
            return {'hold':set(act.get('hold',()))-{'square'}}
        return act

    def _tick(self, snap: dict) -> dict:
        now = self.clock()
        self.observe_round(snap, own_screen(snap), now)
        p = snap.get("player")
        self.nav_dynamic_mines = snap.get("ground_mines") or {}
        self.stats["max_combo"] = max(self.stats["max_combo"], snap.get("combo") or 0)
        if not p:
            return {"hold": set()}
        if not self.round_input_ready:
            self.stats["phase"] = "waiting_round_start"
            return {"hold":set()}
        self._see_dot(snap, now)
        close_foes = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0
                     and (e.get("hp_max") or 0) > 1 and math.dist(p["pos"], e["pos"]) <= FIGHT_R
                     and (self.combat is None or self.combat.blocked_until.get(e.get("ptr", e.get("slot")), 0) <= now)]
        if getattr(getattr(self, "mines", None), "cadence", None) is not None \
                and self.mines.cadence.only and self.mines.cadence.enabled and not snap.get('rotten_egg_only'):
            close_foes = []
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
        if p.get("hp") is not None and p["hp"] <= 0:
            if now - self.dead_tap > 1.5:
                scr = continue_screen(self.m)
                self.stats.update(continue_ready=scr["continue_ready"], continue_cursor=scr["cursor"],
                                  continue_state=scr["continue_state"])
                key = step(scr)
                if key:
                    self.dead_tap = now
                    counter = "continue_declined" if key == "cross" else "continue_select_presses"
                    self.stats[counter] = self.stats.get(counter, 0) + 1
                    return {"tap": key}
            return {"hold": set()}
        if getattr(getattr(self,'mines',None),'escape',None) is not None:
            if p.get('action') in (4,5):
                return {'hold':set()}  # grab/hit callbacks retain control until the native action finishes
            if not self._mine_escape_mandatory(snap):
                retreat = self._mine_retreat(p,snap,now)
                if retreat is not None:
                    return retreat
        if snap.get("prompt") and not (self.combat is not None and self.combat.optional_prompt_blocked(snap)):  # a finisher / a grab: the engine presses it; the gun
            self.aiming_since = None                        # stays down between its presses (L1 would cancel it)
            self.stats["prompt_holds"] = self.stats.get("prompt_holds", 0) + 1
            return {"hold": set()}
        retreat = self._mine_retreat(p, snap, now)
        if retreat is not None:
            return retreat
        heal = self._heal(p, snap, now)                     # heal after leaving an owned explosive, not beside it
        if heal:
            return heal
        health_route = self._seek_health(p,snap,now)
        if health_route is not None:
            return health_route
        held = equipped(snap)
        if held is not None and held.get("type") == 3 and self.healing is None \
                and not getattr(self.inventory_heal, "active", False):
            # A recovery item in hand outside a heal (the infinite spray's restored record, a pickup) is not a gun:
            # live 2026-10-24 rounds ended holding the First Aid Spray, "laserless gun: turning; hold fire" at a Majini
            # in front of him. Back to a gun before anything else.
            back = self._heal_return_weapon(snap.get("inventory") or (), {"return": None}, now)
            if back:
                self.stats["weapon_policy"] = "recovery item in hand outside a heal: back to a gun"
                return back
        if snap.get("stage_prompt") and close_foes:
            self.stage_wait_since = self.stage_wait_since or now
        else:
            self.stage_wait_since = None
        stage_yield = bool(snap.get("stage_prompt") and close_foes and self.stage_wait_since is not None
                           and now - self.stage_wait_since >= STAGE_YIELD_S)
        if snap.get("stage_prompt") and self._stage_loop(p, now):
            snap["stage_prompt"] = False                    # the same ladder / ledge again: left alone, the level goes on
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
        egg_action=self._egg_action(p,snap,now)
        if egg_action is not None:
            return egg_action
        live_weapon_action = self._live_weapon_action(p, snap, now)
        if live_weapon_action is not None:
            return live_weapon_action
        if self._control_state is not None and not snap.get('rotten_egg_only') \
                and not (getattr(getattr(self,'mines',None),'cadence',None)
                         and self.mines.cadence.enabled and self.mines.cadence.only):
            from . import re5_controls
            requested = re5_controls.consume(self._control_state, id(self), snap, self._switch_weapon, now,
                                             input_allowed=not close_foes)
            if requested:
                return requested
            if re5_controls.preferred(self._control_state,snap) is None:
                requested = re5_controls.leave_long_gun(snap, self._switch_weapon, now)
                if requested:return requested
        t = snap.get("timer")
        # Majini and the like: alive, more than 1 health (crows are "enemies" with 1), not far above or below
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1
                and (abs(e["pos"][1] - p["pos"][1]) < MAX_DY or self._laser_view(snap, e) == "on")]
        if getattr(getattr(self, "mines", None), "cadence", None) is not None \
                and self.mines.cadence.only and self.mines.cadence.enabled and not snap.get('rotten_egg_only'):
            live = []
        for e in live:                                   # where every Majini was first seen: this stage's spawn points
            key = e.get("ptr", e.get("slot"))
            if key not in self._spawn_seen:
                if not self._spawn_seen:
                    self._spawn_seen_stage = str(self.stats.get("stage") or "stage")
                self._spawn_seen[key] = tuple(e["pos"])
        self.stats["enemies"], self.stats["spawns"] = len(live), len(self._spawn_seen)
        if live or self._last_live_at is None:
            self._last_live_at = now
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
        if mesh is not None and not close_foes:
            if mesh.find(p["pos"], floor_only=True, height_slack=60.) is None:
                if self.traversal_pressed is not None and self.route and isinstance(self.route[0], re5_nav.Traversal):
                    return self._traverse(p, {"ptr": self.route_for, "pos": self.route[-1]}, mesh,
                                          self.route[0], snap.get("stage_prompt"), now)
                return self._recover_nav(p, mesh, now)
            if self.nav_recovery is not None:
                self.stats["nav_recoveries"] = self.stats.get("nav_recoveries", 0) + 1
                self.route, self.route_len, self.route_at = None, None, -math.inf
            self.nav_recovery = None
        if mesh is not None and self.avoid is not _AVOID.get(mesh_key(mesh)):
            self.avoid = crossings(mesh)
        if self.spawn is None and t is not None and t >= 110:
            self.spawn = tuple(p["pos"])                    # the round's start: a defensible spot by design
        px, py, pz = p["pos"]
        self.at_stand = self.spawn is not None and math.hypot(self.spawn[0] - px, self.spawn[2] - pz) < STAND_R \
            and abs(self.spawn[1] - py) < WP_CLIMB
        # only Majini in sight are fought from here (open floor between, or right on him); the rest are walked to
        sightable = [e for e in live if (self._laser_view(snap, e) == "on" or
                     (math.dist(p["pos"], e["pos"]) <= SIGHT_R and self._open(p, e, mesh, now)) or
                     self._in_view(p, e)) and getattr(self, "_stalled_until", {}).get(e.get("ptr", e.get("slot")), 0) <= now] \
            if self.combat is not None else live
        laserless = self.combat is not None and eq is not None and eq.get("type") == 1 \
            and (eq.get("item") in (0x0F,0x36) or (re5_weapons.WEAPONS.get(eq.get("item")) is not None
                 and re5_weapons.WEAPONS[eq["item"]].family in re5_weapons.DIRECT
                 and self.combat._ray(snap,now) is None))
        if laserless:
            # No laser: do not use the generic near-enemy / barely-bending-route visibility shortcuts.
            # This is only a known-wall veto. Actual projectile cover remains unconfirmed in combat telemetry.
            sightable = [e for e in sightable if self.combat.firing_corridor(snap,p,e,eq["item"])]
        checkpoint_lease = self._checkpoint_walk_allowed(snap,close_foes,now)
        candidate = self.combat.choose_target(snap, p, sightable, now) if self.combat is not None else None
        if candidate is None and self.combat is not None and sightable:
            candidate = min(sightable, key=lambda e: math.dist(p["pos"], e["pos"]))   # in sight, off the camera: turn
        if candidate is not None and self._combat_stalled(p, candidate, now):
            candidate = None                                 # fought in place too long: he is blocked, the route goes on
        boss = self._boss_first(p, live, sightable)
        if boss is not None and (candidate is None or not self._boss(candidate)):
            candidate = boss                                 # the boss first (operator 2026-10-26), whatever is nearer
            self.stats["target_evidence"] = (f"boss first: hp {boss.get('hp')}/{boss.get('hp_max')} "
                                             f"{math.dist(p['pos'], boss['pos']):.0f} away")
        order = self._operator_command(p, snap, live, now)          # the operator's instant command (chat dropdown / words)
        operator = self.map_goals.resolve(snap, now)
        if operator is not None and order in ("fight", "hunt", "score"):
            operator = None                                          # the Majini first: no collection detour right now
        if operator is not None:
            if close_foes:
                self.map_goals.defer('Dispatching a nearby exposed threat before collection')
            elif mesh is None:
                self.map_goals.defer('Waiting for measured native navigation geometry')
            else:
                goal = self.map_goals.goal
                key = operator['ptr'] if goal['kind'] == 'bonus' else ('health', operator['ptr'])
                if self.bonus_skip.get(key, 0) > now:
                    self.map_goals.defer('Prior approach was blocked; retaining goal while its retry cools down')
                elif goal['kind'] == 'item':
                    action = self._seek_health(p, snap, now, requested=operator)
                    if action is not None:
                        self.stats['phase'] = 'operator_collect_item'
                        return action
                    self.map_goals.defer('No supported route or exact recovery-item pickup prompt')
                else:
                    self.stats['phase'] = 'operator_collect'
                    self.plan_target = {'kind': 'bonus', 'id': operator['ptr'], 'pos': operator['pos']}
                    self.aiming_since = None
                    if math.dist(p['pos'], operator['pos']) > BONUS_TAKE or abs(p['pos'][1]-operator['pos'][1]) >= BONUS_LEVEL_DY:
                        return self._follow(p, operator, mesh, snap.get('stage_prompt'), now)
                    return self._take(p, operator, snap.get('stage_prompt'), now)
        selected_demo = self.stats.get('selected_route_id')
        if selected_demo and mesh is not None and not close_foes:
            mine_margins = [(row['pos'],600.) for row in self.nav_dynamic_mines.values()]
            nearby_bonus = next((bonus for bonus in snap.get('bonuses') or ()
                if bonus.get('kind') == 'time' and bonus.get('ptr') is not None
                and self.bonus_skip.get(bonus['ptr'],0) <= now
                and abs(bonus['pos'][1]-p['pos'][1]) < 60.
                and math.dist(bonus['pos'],p['pos']) <= BONUS_PUNCH_R
                and mesh.floor_segment(p['pos'],bonus['pos'])
                and mesh.hazard_segment_clear(p['pos'],bonus['pos'],mine_margins)), None)
            if nearby_bonus is not None:
                # A recorded path supplies positions, not button playback. Take
                # a currently observed, reachable hourglass through the normal
                # face-and-punch policy before continuing the demonstration.
                self.stats['phase'] = 'practice_take_time'
                self.plan_target = {'kind':'time','id':nearby_bonus['ptr'],'pos':nearby_bonus['pos']}
                return self._take(p,nearby_bonus,snap.get('stage_prompt'),now)
            practice = self.operator_guidance.practice(mesh, p['pos'], now,
                mode=self.stats.get('mercenaries_mode'), selected_route_id=selected_demo,
                hazards=mine_margins,
                blocked_links=self.blocked_links, avoid=self.avoid,
                penalties=self.nav_learning.link_penalties(mesh))
            if practice is not None:
                self.stats['demonstration_status'] = practice['status']
                self.stats['demonstration_progress'] = f"{practice['index']}/{practice['point_count']}"
                if practice['status'] in ('approach', 'practice'):
                    # Preserve the held hourglass goal across this explicit
                    # practice excursion. Live prompts, healing, mine escape and
                    # immediate exposed threats have already taken precedence.
                    target = {'ptr': practice['id'], 'pos': practice['pos']}
                    self.stats['phase'] = 'practice_human_route'
                    self.plan_target = {'kind':'waypoint', 'id':practice['id'], 'pos':practice['pos']}
                    return self._follow(p,target,mesh,snap.get('stage_prompt'),now,learn=False,
                                        approved_route=practice['route'])
        # Time bonuses first (operator 2026-10-22: "urgently seeking and acquiring time bonuses and pursuing the S rank
        # score"): only a Majini close and in sight (close_foes, or one in the way: _bonus) stops the gather; a fight
        # further off waits. A time bonus breaks the combo when it must; the strategy keeps only its safety refusals.
        tgt = self._bonus(p, sightable, snap.get("bonuses") or (), now, mesh, t, clearance_lease=checkpoint_lease)
        if tgt is not None:
            from . import re5_strategy
            distance = math.dist(p["pos"], tgt["pos"])
            routed = (self.route_len or {}).get(tgt["ptr"])
            eta = (routed if routed is not None else distance * 1.25) / RUN_SPEED
            decision = re5_strategy.detour_decision(snap, eta, distance < BONUS_REACH,
                kind=tgt.get("kind", "time"), immediate_threat=bool(close_foes))
            allowed = decision.allowed or (tgt.get("kind", "time") == "time" and decision.reason not in HARD_REFUSALS)
            if (decision.reason == "preserve combo or wait for a known window" and candidate is not None
                    and self._combo_running(snap) and t > eta + BREAK_MARGIN_S
                    and (self._laser_view(snap, candidate) == "on"
                         or (self._in_view(p, candidate) and self._open(p,candidate,mesh,now)))):
                # Keep a live chain with an exposed forward shot before a long trip.
                # The checkpoint commitment survives this brief combat interruption.
                allowed = False
            if checkpoint_lease and tgt.get("kind","time") == "time" \
                    and decision.reason == "dispatch nearby exposed threat first":
                allowed = True  # only this bounded dispatch refusal; clock and route refusals remain authoritative
            self.stats["strategy_decision"] = decision.reason if decision.allowed or not allowed \
                else f"time bonus first ({decision.reason})"
            if not allowed:
                tgt = None
        if order in ("fight", "hunt", "score") and live:
            tgt = None                                               # ahead of the time bonuses; not back to the stand
            self.at_stand = False
            self.stats["directive_status"] = "fighting: Majini first, bonuses after"
        if close_foes and not checkpoint_lease:
            tgt = None
            self.stats["phase"] = "clear_nearby"
        threats = [e for e in sightable if self._threat(p, e)]
        self.flags = {e["slot"]: ["blocking"] for e in threats}
        if tgt is None and candidate is None and live and self.combat is not None:
            chase = self._pursuit_target(p, live, mesh, now, snap)     # nobody in sight: go to them, never wait at a wall
            if chase is not None:
                return self._pursue(p, chase, mesh, snap.get("stage_prompt"), now)
        keep_combo = self.combat is not None and self._combo_running(snap) and bool(live)
        if tgt is None and not threats and candidate is None and keep_combo and mesh is None:
            # A combo is running and there is no mesh to route by: walk at the nearest one rather than back to the
            # stand, which would let the window lapse (a lost combo is a large score loss). With a mesh and no route
            # to anyone, a straight walk is a push into a wall (coaching note 14, #947): the stand rule below.
            near = min(live, key=lambda e: math.dist(p["pos"], e["pos"]))
            self.stats["phase"] = "keep_combo"
            self.stats["combo_chases"] = self.stats.get("combo_chases", 0) + 1
            self.aiming_since = None
            return {"hold": self._walk(p, heading(near["pos"][0] - px, near["pos"][2] - pz), now)}
        if tgt is None and not live and candidate is None \
                and now - self._last_live_at >= (LULL_AGAIN_S if self._hunt_visited or self._hunt else LULL_S):
            hunt = self._hunt_spawns(p, mesh, snap, now)        # the stand gone quiet: to where they spawn
            if hunt is not None:
                return hunt
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
        tgt = tgt or min(threats or live, key=lambda e: (0 if self._boss(e) else 1, self._cost(p, e)))
        self.plan_target = {"kind": tgt.get("kind", "enemy") if "ptr" in tgt else "enemy",
                            "id": tgt.get("ptr") if tgt.get("kind") in ("time", "combo") else tgt.get("slot"),
                            "pos": tgt["pos"]}
        aim_h = tgt.get("aim_h", HEAD_H)
        tx, ty, tz = tgt["pos"]
        dist = math.hypot(tx - px, tz - pz)
        want = heading(tx - px, tz - pz)
        if "ptr" in tgt and tgt.get("kind") not in ("time", "combo") and self._boss(tgt) and dist < BOSS_KEEP_R:
            backing = self._boss_range(p, tgt, mesh, snap, now, dist)
            if backing is not None:
                return backing
        if tgt.get("kind") in ("time", "combo"):            # a time bonus: walked to, taken with its prompt
            self.aiming_since, self.target = None, tgt["slot"]
            if tgt.get("walk"):
                return self._follow(p, tgt, snap.get("nav"), snap.get("stage_prompt"), now)
            return self._take(p, tgt, snap.get("stage_prompt"), now)
        if dist > ENGAGE and self._laser_view(snap, tgt) != "on":  # a current first hit confirms distant shots
            self.aiming_since = None
            if self.at_stand and not self._combo_running(snap):   # ...unless this is the stand: they come to him
                return {"hold": set()}                      # (not while a combo window is open: go and keep it)
            self.stats["phase"] = "keep_combo" if self.at_stand else self.stats.get("phase")
            if mesh is not None and tgt.get("ptr", tgt.get("slot")) is not None:
                # never a straight push at a far Majini: the way round the wall of the mesh, or nothing if there is none
                return self._pursue(p, tgt, mesh, snap.get("stage_prompt"), now)
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
            if laserless and mesh is not None:
                if self.combat.needs_firing_position:
                    self.laserless_reacquire_until = now+1.
                    self.combat.needs_firing_position = False
                if now < self.laserless_reacquire_until:
                    # Give the bounded, mine-aware router actual movement ticks, not a single-frame pause.
                    return self._pursue(p,tgt,mesh,snap.get("stage_prompt"),now)
            if self._lost_sight(snap, p, tgt, now):        # the dot stops short of him / never reaches him: go there
                chase = self._pursuit_target(p, live, mesh, now, snap)
                if chase is not None:
                    return self._pursue(p, chase, mesh, snap.get("stage_prompt"), now)
            from . import re5_controls
            if self.switch_pending is None and now - self.switch_at > SWITCH_EVERY_S \
                    and not snap.get('rotten_egg_only') \
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
    def _see_dot(self, snap, now):
        """Remember which Majini the laser dot is on (the one confirmation of sight that works across levels)."""
        lz = snap.get("laser")
        if not lz or not lz.get("from") or not lz.get("at") or not any(lz["from"]):
            return
        for e in snap.get("enemies") or ():
            if (e.get("hp") or 0) > 0 and re5_combat.dot_on(lz["at"], e["pos"]) is not None:
                self.dot_seen[e.get("ptr", e.get("slot"))] = now
        if len(self.dot_seen) > 256:
            self.dot_seen.clear()

    def _open(self, p, e, mesh, now) -> bool:
        """Whether a Majini is confirmed in sight, so the gun may come up for him: the laser dot on him a moment ago
        (DOT_MEMORY_S, any level), or on the player's level (LEVEL_DY) and right next to him (TOO_CLOSE; PURSUE_NEAR
        unless _lost_sight left him out of sight), or with open floor between them on the navmesh (floor_segment within
        CONFIRM_R, or a route that barely bends within BEND_R; no mesh: CONFIRM_R). Anyone else is walked to."""
        key = e.get("ptr", e.get("slot"))
        unsighted = self.unsighted.get(key, 0.0) > now
        if not unsighted and self.dot_seen.get(key, -math.inf) >= now - DOT_MEMORY_S:
            return True
        if abs(e["pos"][1] - p["pos"][1]) >= LEVEL_DY:     # a roof above, a pit below: the dot alone says he is seen
            return False
        flat = math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
        if flat < TOO_CLOSE:
            return True
        if unsighted:
            return False
        if flat < PURSUE_NEAR:
            return True
        if flat > CONFIRM_R:
            return False
        if mesh is None:
            return True
        hit = self._sight.get(key)
        if hit is not None and now - hit[0] < SIGHT_CACHE_S:
            return hit[1]
        try:
            ok = bool(mesh.floor_segment(p["pos"], e["pos"]))
            if not ok and flat <= BEND_R:                   # floor_segment is strict (unlinked faces, slopes: live, 4
                length = mesh.route_length(p["pos"], e["pos"], avoid=self.avoid)   # of 5 nearly straight routes were
                ok = length is not None and length <= SIGHT_BEND * flat + SIGHT_SLACK   # "closed"): barely bending
        except Exception:                                   # noqa: BLE001 - an odd triangle is no confirmation
            ok = False
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
        foot = tgt["pos"]
        if re5_combat.dot_on(dot, foot) is not None \
                or re5_combat.line_to((origin, dot), (foot[0], foot[1] + 110.0, foot[2]), foot):
            return "on"                                     # on him, or the ray runs through him to a dot beyond
        length = math.dist(origin, dot)
        if length < WALL_R:
            return "wall"
        centre = (tgt["pos"][0], tgt["pos"][1] + 110.0, tgt["pos"][2])
        err = abs(wrap(heading(dot[0] - origin[0], dot[2] - origin[2])
                       - heading(centre[0] - origin[0], centre[2] - origin[2])))
        if err < math.radians(20) and length < math.dist(origin, centre) - VIEW_SHORT:
            return "short"
        return None

    def _combat_stalled(self, p, tgt, now) -> bool:
        """Fought in place too long: the same Majini for COMBAT_STALL_S with no shot leaving the gun while the player
        stays within COMBAT_STALL_R of where he stood. He is left alone for COMBAT_STALL_BLOCK_S (combat.blocked_until:
        out of close_foes and sightable) and the bonus route goes on instead of holding fire at him."""
        if self.combat is None:
            return False
        key = tgt.get("ptr", tgt.get("slot"))
        shots = self.stats.get("shots", 0)
        st = getattr(self, "_combat_stall", None)
        moving = self.stats.get("phase") == "pursue" or self.switch_pending is not None   # walking to him, a switch
        if st is None or st["key"] != key or shots != st["shots"] or moving                 or math.dist(p["pos"], st["pos"]) > COMBAT_STALL_R:
            self._combat_stall = {"key": key, "shots": shots, "pos": tuple(p["pos"]), "since": now, "ticks": 0}
            return False
        st["ticks"] += 1
        if now - st["since"] < COMBAT_STALL_S or st["ticks"] < COMBAT_STALL_TICKS:
            return False
        self._combat_stall = None
        if not hasattr(self, "_stalled_until"):
            self._stalled_until = {}
        self._stalled_until[key] = now + COMBAT_STALL_BLOCK_S     # out of sightable (combat's own 0.8 s block is separate)
        self.combat.blocked_until[key] = now + COMBAT_STALL_BLOCK_S
        self.unsighted[key] = now + COMBAT_STALL_BLOCK_S
        self.stats["combat_stalls_broken"] = self.stats.get("combat_stalls_broken", 0) + 1
        self.stats["combat"] = f"fought in place {COMBAT_STALL_S:g} s without a shot: leaving him, the route goes on"
        return True

    def _lost_sight(self, snap, p, tgt, now) -> bool:
        """The Majini being fought is not in sight after all: the dot stopped short of him (or at a wall) for
        BLOCKED_VIEW_S, or the laser was up UNSIGHTED_S without the dot reaching him (time without a laser does not
        count: the gun coming up). He is then left out of sight for PURSUE_S (walked to)."""
        key = tgt.get("ptr", tgt.get("slot"))
        if key is None or (math.hypot(tgt["pos"][0] - p["pos"][0], tgt["pos"][2] - p["pos"][2]) < TOO_CLOSE
                           and abs(tgt["pos"][1] - p["pos"][1]) < LEVEL_DY):
            self.engaged = None                             # right on him: no wall between (a fence 2 m off is one)
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

    def _track_combo(self, snap) -> None:
        """Measure combo lengths per round: a combo that falls to 0 is closed with its length; one whose window had
        run out (<= COMBO_LAPSE_S left at the last read) counts as lapsed, i.e. the next Majini was not dispatched in time."""
        combo, window = snap.get("combo"), snap.get("combo_timer")
        if type(combo) is not int or combo < 0 or combo > 0x7FFFFFFF:
            return
        if not self.combo_log:
            self.combo_log.append({"lengths": [], "lost": 0, "lapsed": 0})
        cur = self.combo_log[-1]
        if self._combo_prev > 0 and combo == 0:
            cur["lengths"].append(self._combo_prev)
            cur["lost"] += 1
            if isinstance(self._combo_prev_window, (int, float)) and self._combo_prev_window <= COMBO_LAPSE_S:
                cur["lapsed"] += 1
            self.stats["combos_lost"] = self.stats.get("combos_lost", 0) + 1
        elif combo > 0 and combo < self._combo_prev:        # a new combo started straight after a loss
            cur["lengths"].append(self._combo_prev)
            cur["lost"] += 1
        self._combo_prev = combo
        self._combo_prev_window = window if combo > 0 else None
        self.stats["combo_rounds"] = [{"lengths": list(c["lengths"]), "lost": c["lost"], "lapsed": c["lapsed"]}
                                      for c in self.combo_log[-5:]]

    @staticmethod
    def _combo_running(snap) -> bool:
        """A combo with an open window: waiting for enemies to arrive would let it lapse."""
        combo, window = snap.get("combo"), snap.get("combo_timer")
        return (type(combo) is int and combo > 0 and isinstance(window, (int, float))
                and not isinstance(window, bool) and 0.0 < window < 60.0)

    def _pursuit_target(self, p, live, mesh, now, snap=None):
        """The Majini to walk to: the shortest navmesh route among the six nearest (chosen again every
        PURSUE_PICK_S); one whose route failed lately is skipped. None: nobody reachable."""
        combo = snap is not None and self._combo_running(snap)
        window = snap.get("combo_timer") if combo else None
        if self.pursuit is not None and now - self.pursuit[0] < PURSUE_PICK_S:
            e = next((e for e in live if e.get("ptr", e.get("slot")) == self.pursuit[1]), None)
            if e is not None and self.bonus_skip.get(("enemy", self.pursuit[1]), 0.0) <= now:
                # a running combo re-picks at once when the held one can no longer be reached inside the window
                left = getattr(self, "_pursuit_route", None)
                left = None if left is None else left - RUN_SPEED * (now - self.pursuit[0])
                if not (combo and left is not None and left / RUN_SPEED > window):
                    return e
        best, best_d = None, math.inf
        # with a combo running every Majini is a candidate (the nearest in a straight line can be the long way round)
        for e in sorted(live, key=lambda e: math.dist(p["pos"], e["pos"]))[:12 if combo else 6]:
            key = e.get("ptr", e.get("slot"))
            if self.bonus_skip.get(("enemy", key), 0.0) > now:
                continue
            if mesh is None:
                d = math.dist(p["pos"], e["pos"])
            else:
                try:
                    d = mesh.route_length(p["pos"], e["pos"], avoid=self.avoid,
                        blocked_links=self.blocked_links, link_penalties=self.nav_learning.link_penalties(mesh))
                except Exception:                           # noqa: BLE001
                    d = None
            if d is not None and d < best_d:
                best, best_d = e, d
        if combo and best is not None:
            self.stats["combo_pursuits"] = self.stats.get("combo_pursuits", 0) + 1
            self.stats["combo_pursuit_fits"] = self.stats.get("combo_pursuit_fits", 0) + \
                (1 if best_d / RUN_SPEED <= window else 0)
        self._pursuit_route = best_d if best is not None else None
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
            if current is not None and current.get("type") == 3:
                cooldown = SWITCH_EVERY_S * 2   # a recovery item in hand is no weapon: retry soon (live 2026-10-24: a
                                                # 60 s wait on one grid kept the First Aid Spray in hand through a fight)
            self.switch_blocked[wanted] = now + cooldown
            self.stats["weapon_switch_failures"] = self.stats.get("weapon_switch_failures", 0) + 1
            self.stats["weapon_switch_status"] = f"unconfirmed; grid {wanted[1]} waits {cooldown:g}s"
            self.switch_pending = None

    def _preferred_gun(self,snap):
        from . import re5_controls
        return re5_controls.preferred(getattr(self,'_control_state',None) or {},snap)

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

    def _bonus(self, p, live, standing, now, mesh=None, clock=None, *, clearance_lease=False):
        """The time bonus to go for now, or None (nothing standing, or a Majini within FIGHT_R: he is fought first).
        The nearest hourglass by the navmesh route (straight line without a mesh), on any level, walked to along the
        route and taken with its "□ Time bonus" prompt (Bot._take); one left alone for BONUS_SKIP_S when its prompt
        did not come or its route led nowhere."""
        px, py, pz = p["pos"]
        now_ptrs = {b["ptr"] for b in standing}
        self.stats["time_bonuses_remaining"] = sum(b.get("kind", "time") == "time" for b in standing)
        self.stats["combo_bonuses_remaining"] = sum(b.get("kind") == "combo" for b in standing)
        standing = [b for b in standing if self.bonus_skip.get(b["ptr"], 0.0) <= now]
        if not standing or not BONUS_HUNT:
            self.stats["bonus_target"] = None
            return None
        # about to take one (right on it, on its level): finish the square press even with a Majini near - it is quick
        near = min(standing, key=lambda b: math.hypot(b["pos"][0] - px, b["pos"][2] - pz))
        at_bonus = math.hypot(near["pos"][0] - px, near["pos"][2] - pz) < BONUS_REACH \
            and abs(near["pos"][1] - py) < BONUS_LEVEL_DY
        if not at_bonus and not clearance_lease and any(self._threat(p, e) for e in live):
            self.stats["phase"] = "fight"
            return None
        if mesh is not None and (self.route_len is None or now - self.route_len_at > ROUTE_LEN_S
                                 or set(self.route_len) != now_ptrs):
            self.route_len, self.route_len_at = {}, now
            for b in standing:
                self.route_len[b["ptr"]] = mesh.route_length(p["pos"], b["pos"], avoid=self.avoid,
                    blocked_links=self.blocked_links, link_penalties=self.nav_learning.link_penalties(mesh))

        def cost(b):
            d = self.route_len.get(b["ptr"]) if self.route_len else None
            if d is None:                                   # no route (yet): straight line, after the routed ones
                d = 2.0 * math.hypot(b["pos"][0] - px, b["pos"][2] - pz) + 5000.0
            return d
        self.stats["unreachable_bonuses"] = sum(1 for b in standing if mesh is not None
                                               and self.route_len.get(b["ptr"]) is None)
        if mesh is None:
            # No navmesh: a straight line is the only plan, and it cannot climb. A bonus on another level (a roof, a
            # ledge, a floor below) is not run at (operator 2026-10-22: "running face first at a wall"); the ones on
            # this level go first and the rest wait for a mesh.
            self.stats["unreachable_bonuses"] = sum(1 for b in standing if abs(b["pos"][1] - py) >= BONUS_LEVEL_DY)
            cands = [b for b in standing if abs(b["pos"][1] - py) < BONUS_LEVEL_DY and cost(b) < BONUS_RANGE]
        else:
            cands = [b for b in standing if cost(b) < BONUS_RANGE and self.route_len.get(b["ptr"]) is not None]
        if not cands:
            self.stats["bonus_target"] = None
            return None
        # Time checkpoints precede optional combo bonuses. All remaining time actors
        # are retained in the stage atlas even when this round has not found a route.
        time_cands = [candidate for candidate in cands if candidate.get("kind", "time") == "time"]
        cands = time_cands or cands
        if not time_cands:
            # Activate optional combo rewards where current exposed enemy flow
            # can use them; a map click is an explicit operator exception.
            cands = [b for b in cands if any(math.dist(e['pos'],b['pos'])<=1200. for e in live)]
            if not cands:
                self.stats['bonus_target']='Combo pickup deferred until an exposed combat opportunity'
                return None
        b = min(cands, key=lambda b: cost(b) +
                (self.nav_learning.route_penalty(mesh, p["pos"], b["pos"]) if mesh is not None else 0.0))
        if mesh is not None and clock is not None and len(cands) > 1:
            from ..tour import plan
            cache_key = (mesh_key(mesh), tuple(sorted(tuple(x) for x in self.avoid)), tuple(sorted(self.blocked_links)),
                         tuple(sorted(self.nav_learning.link_penalties(mesh).items())))
            if getattr(self, "_tour_key", None) != cache_key:
                self._tour_key, self._tour_distances = cache_key, {}
            def travel(a, other):
                key = (tuple(a["pos"]), tuple(other["pos"]))
                if key not in self._tour_distances:
                    self._tour_distances[key] = mesh.route_length(a["pos"], other["pos"], avoid=self.avoid,
                        blocked_links=self.blocked_links, link_penalties=self.nav_learning.link_penalties(mesh))
                return self._tour_distances[key]
            if now - getattr(self, "_tour_at", -math.inf) > 2 or getattr(self, "_tour_live", None) != now_ptrs:
                tour = plan(cands, travel, lambda a: cost(a) + self.nav_learning.route_penalty(mesh,p["pos"],a["pos"]),
                            clock, RUN_SPEED)
                self._tour_goal = tour[0]["ptr"] if tour else None
                self._tour_at, self._tour_live = now, now_ptrs
                self.stats["bonus_tour"] = [hex(x["ptr"]) for x in tour]
                self.stats["bonus_tour_planned"] = len(tour)
            b = next((x for x in cands if x["ptr"] == self._tour_goal), b)
        held = self.bonus_commitment.goal
        distance = (self.route_len or {}).get(held)
        chosen = self.bonus_commitment.choose(b["ptr"], [x["ptr"] for x in cands], now, distance)
        b = next((x for x in cands if x["ptr"] == chosen), b)
        self.stats["bonus_committed"] = hex(b["ptr"]) if isinstance(b["ptr"], int) else str(b["ptr"])
        d = math.hypot(b["pos"][0] - px, b["pos"][2] - pz)
        level = abs(b["pos"][1] - py) < BONUS_LEVEL_DY          # on its level, right at it: take it
        walk = d > BONUS_TAKE or not level
        dy = b["pos"][1] - py                                  # the vertical the walk must solve: up = a ledge / ladder
        self.stats["bonus_vertical"] = ("level" if level else "above" if dy > 0 else "below") + f" {dy:+.0f}"
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
    def _in_view(p, e) -> bool:
        """A Majini in front of him within ENGAGE (a walkway, a roof, a rocket launcher across the yard): taken on while
        navigating, the laser confirming the shot (operator 2026-10-24: "why is she afraid to take on these opponents that
        are long distance but shooting rocket launchers at her? ... if the enemy is open and in their sight. They need to
        take shots to dispatch them while navigating"). Open floor between them is not required; known walls still veto."""
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        off = abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
        return d <= ENGAGE and off <= IN_VIEW_CONE

    @staticmethod
    def _threat(p, e) -> bool:
        """A Majini worth stopping for: within FIGHT_R and in front (he blocks the way), or right on top of him."""
        px, py, pz = p["pos"]
        if abs(e["pos"][1] - py) >= LEVEL_DY:               # on another level: not in the way
            return False
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        if d < ON_TOP_R:
            return True
        off = abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
        return d < FIGHT_R and off < FIGHT_CONE

    def _heal_safe(self, p, snap, hp, hp_max) -> bool:
        """Start a heal (or a walk to a health item) now? Not with a Majini within HEAL_SAFE_R unless health is under
        HEAL_CRITICAL (operator 2026-10-26: "Im watching the bot sit idle and be attacked and fail to even dispatch these
        foes who are 1 foot away" - live 13:05, phase healing_inventory with 9 Majini on the field, 2 heals, 24 hits of
        86): the fight clears them first, the heal follows."""
        if hp_max <= 0 or hp <= HEAL_CRITICAL * hp_max:
            return True
        near = sum(1 for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and (e.get("hp_max") or 0) > 1
                   and math.dist(p["pos"], e["pos"]) < HEAL_SAFE_R)
        if not near:
            self.stats.pop("heal_deferred", None)
            return True
        self.stats["heal_deferred"] = f"{near} Majini within {HEAL_SAFE_R / 100:.0f} m at {hp / hp_max:.0%}: fight first"
        self.stats["heal_deferred_ticks"] = self.stats.get("heal_deferred_ticks", 0) + 1
        return False

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
            self.inventory_heal.reset()
            return None
        if self.inventory_heal.active:
            self.bonus_commitment.pause(now)
            action = self.inventory_heal.tick(self.m,snap,None,now)
            if action is not None or self.inventory_heal.active:
                self.stats['phase'] = 'healing_inventory'
                return action or {'hold':set()}
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
            if now<state.get('ready_at',-math.inf):
                self.stats['heal_status'] = 'lowering gun before recovery-item selection'
                return {'hold':set()}
            if state['equips']==0:
                state['equip_at'],state['equips'] = now,1
                self.stats['heal_equip_attempts'] = self.stats.get('heal_equip_attempts',0)+1
                return {'tap':re5_weapons.quick_key(item)}
            if now - state["equip_at"] >= SWITCH_ACK_S and state["equips"] < 2:
                key = re5_weapons.quick_key(item)
                if key:
                    state["equip_at"], state["equips"] = now, state["equips"] + 1
                    self.stats["heal_equip_attempts"] = self.stats.get("heal_equip_attempts", 0) + 1
                    return {"tap": key}
            self.stats["heal_status"] = "awaiting recovery item in hand"
            return {"hold": set()}
        if hp > HEAL_AT * hp_max or now - self.heal_at < HEAL_RETRY_S or not self._heal_safe(p, snap, hp, hp_max):
            return None
        heals = [s for s in items if s["id"] in HEAL_IDS and s.get("rounds", 0) > 0]
        if not heals:
            return None
        quick = next((s for s in heals if s.get("hand")), None) or next((s for s in heals if re5_weapons.quick_key(s)), None)
        if quick is None:
            self.switch_pending = None
            self.bonus_commitment.pause(now)
            action = self.inventory_heal.tick(self.m,snap,heals[0],now)
            if action is not None or self.inventory_heal.active:
                self.stats['phase'] = 'healing_inventory'
                self.stats.pop('heal_out_of_reach',None)
                return action or {'hold':set()}
            self.stats["heal_out_of_reach"] = heals[0]["slot"]
            self.stats['heal_status'] = self.stats.get('inventory_heal_status','recovery item selection unavailable')
            return None
        self.switch_pending = None                 # emergency healing owns selection until this bounded sequence ends
        settling = not quick.get('hand') and (p.get('action')==2 or self.aiming_since is not None)
        self.healing = {"key": re5_weapons.inventory_key(quick), "player": p.get("ptr"), "id": quick["id"],
                        "count": sum(s.get("rounds", 0) for s in items if s.get("id") == quick["id"]),
                        "hp": hp, "at": now, "last_use": -math.inf, "uses": 0,
                        "equip_at": now, "equips": 0 if quick.get("hand") or settling else 1,
                        'ready_at':now+1. if settling else now,
                        "return": re5_weapons.inventory_key(eq) if eq and eq.get("type") == 1 else None}
        self.stats["phase"] = "healing"
        if quick.get("hand"):
            return self._heal(p, snap, now)          # the screenshot's already-held spray needs Square, not another D-pad
        if settling:
            self.stats['heal_status'] = 'lowering gun before recovery-item selection'
            return {'hold':set()}
        self.stats["heal_equip_attempts"] = self.stats.get("heal_equip_attempts", 0) + 1
        self.stats["heal_status"] = "equipping recovery item"
        return {"tap": re5_weapons.quick_key(quick)}

    def _seek_health(self,p,snap,now,requested=None):
        """Pause the held checkpoint to reach a verified recovery item using existing safe floor paths."""
        hp,hp_max = p.get('hp') or 0,p.get('hp_max') or 0
        if hp_max<=0 or hp<=1 or requested is None and hp>HEAL_AT*hp_max or snap.get('recovery_active') \
                or requested is None and not self._heal_safe(p,snap,hp,hp_max):
            return None
        from . import re5_health
        rows = [row for row in snap.get('health_items') or [] if row.get('id') in HEAL_IDS and row.get('evidence')]
        if requested is not None:
            rows = [row for row in rows if row['ptr'] == requested['ptr'] and row.get('handle') == requested.get('handle')]
        if not rows:
            self.stats['health_seek_status'] = 'no verified ground recovery item observed'
            return None
        self.bonus_commitment.pause(now)
        pickup = getattr(re5_health,'pickup_request',None)
        request = selected_prompt(self.m,include_item_pickups=True) if self.m is not None else None
        matched = pickup(self.m,request,rows) if request and callable(pickup) else None
        if matched is not None and matched.get('id') in HEAL_IDS:
            prior = self.health_pickup
            if prior is not None and now-prior['at']<.7:
                return {'hold':set()}
            self.health_pickup = {'player':p.get('ptr'),'id':matched['id'],'actor':matched['ptr'],
                'at':now,'before':sum(w.get('rounds',0) for w in snap.get('inventory') or () if w.get('id')==matched['id'])}
            self.stats['phase'] = 'acquire_health'
            self.stats['health_pickup_presses'] = self.stats.get('health_pickup_presses',0)+1
            self.stats['health_seek_status'] = 'exact displayed recovery-item pickup; awaiting inventory increase'
            return {'tap':'square'}
        mesh = snap.get('nav')
        if mesh is None:
            self.stats['health_seek_status'] = 'verified recovery item observed; navigation unavailable'
            return None
        hazards = [(row['pos'],600.) for row in (snap.get('ground_mines') or {}).values()]
        candidates = []
        for item in rows:
            key = ('health',item['ptr'])
            if self.bonus_skip.get(key,0.)>now:
                continue
            route = mesh.route_avoiding_hazards(p['pos'],item['pos'],hazards,avoid=self.avoid,
                blocked_links=self.blocked_links,link_penalties=self.nav_learning.link_penalties(mesh))
            if route:
                candidates.append((sum(math.dist(a,b) for a,b in zip([p['pos']]+route,route)),item))
        if not candidates:
            self.stats['health_seek_status'] = 'no measured safe route to currently observed recovery items'
            return None
        distance,item = min(candidates,key=lambda pair:pair[0])
        self.stats['phase'] = 'seek_health'
        self.stats['health_seek_status'] = f"{item.get('name','recovery item')}: measured route {distance:.0f}cm"
        self.plan_target = {'kind':'health','id':item['ptr'],'pos':item['pos']}
        if math.dist(p['pos'],item['pos'])<100.:
            err = wrap(heading(item['pos'][0]-p['pos'][0],item['pos'][2]-p['pos'][2])-p['rot'])
            self.stats['health_seek_status'] = 'at verified recovery item; aligning for its actual pickup prompt'
            return {'hold':self._turn(err,aiming=False)}
        self.aiming_since = None
        return self._follow(p,{'ptr':('health',item['ptr']),'pos':item['pos']},mesh,snap.get('stage_prompt'),now,learn=False)

    def _heal_return_weapon(self, inv, state, now):
        guns = [s for s in inv if s.get("type") == 1 and s.get("rounds", 0) > 0 and re5_weapons.quick_key(s)
                and (re5_weapons.WEAPONS.get(s.get("item")) is not None)
                and re5_weapons.WEAPONS[s["item"]].family in re5_weapons.DIRECT]
        # a gun whose switch did not take waits its cooldown; any other loaded gun is tried meanwhile
        open_ = [s for s in guns if self.switch_blocked.get(re5_weapons.inventory_key(s), 0) <= now]
        preferred = self._preferred_gun({'inventory':inv})
        if preferred is not None and self.switch_blocked.get(re5_weapons.inventory_key(preferred), 0) > now and open_:
            preferred = None
        gun = preferred \
            or next((s for s in open_ if re5_weapons.inventory_key(s) == state["return"]), None) or next(iter(open_), None)
        if gun is not None and not gun.get("hand"):
            return self._switch_weapon(gun, now, "resume after healing")
        return None

    @staticmethod
    def _boss(e) -> bool:
        """A boss by his health (re5_combat.BOSS_HP: the one-finisher rule's own line): the Executioner, the Chainsaw /
        Gatling / Giant Majini, the Reaper. An ordinary Majini has 800-1000."""
        return (e.get("hp_max") or 0) >= re5_combat.BOSS_HP

    def _boss_first(self, p, live, sightable):
        """The boss to fight now: the nearest one in sight, unless an ordinary Majini is within BOSS_YIELD_R (he is
        shot first, then the boss); None when there is none in sight."""
        bosses = [e for e in sightable if self._boss(e)]
        if not bosses:
            return None
        if any(not self._boss(e) and math.dist(p["pos"], e["pos"]) <= BOSS_YIELD_R for e in live):
            return None
        return min(bosses, key=lambda e: math.dist(p["pos"], e["pos"]))

    def _boss_range(self, p, boss, mesh, snap, now, dist) -> dict | None:
        """A boss inside BOSS_KEEP_R: no stand-up fight at arm's length (operator 2026-10-26: "dispatch them without
        delay (preferably from a distance)"). The gun comes down and a measured floor route away from him (the mesh's
        retreat, 6 m) is walked for at most BOSS_RETREAT_S, then he turns and fires for BOSS_RETREAT_GAP_S at least
        before backing off again. None: the fight goes on here (no mesh to measure a way back by, or shots are due)."""
        key = boss.get("ptr", boss.get("slot"))
        run = self._boss_run
        if run is not None and run["key"] == key:
            if now - run["since"] <= BOSS_RETREAT_S:
                pass                                          # the back-off under way
            elif now - run["since"] <= BOSS_RETREAT_S + BOSS_RETREAT_GAP_S:
                self.stats["boss"] = f"{key:#x} hp {boss.get('hp')}/{boss.get('hp_max')} {dist:.0f} away: firing"
                return None                                   # his turn to take shots, from here
            else:
                run = None
        else:
            run = None
        if run is None:
            if mesh is None:
                return None                                   # no measured floor: never a blind run into a wall
            self._boss_run = run = {"key": key, "since": now}
            self.route, self.route_at = None, -math.inf       # a fresh retreat route, not the chase's
            self.stats["boss_retreats"] = self.stats.get("boss_retreats", 0) + 1
        px, py, pz = p["pos"]
        bx, _, bz = boss["pos"]
        d = max(dist, 1.0)
        away = (px + (px - bx) / d * 600.0, py, pz + (pz - bz) / d * 600.0)
        try:
            route = mesh.retreat(p["pos"], boss["pos"], 600.0, blocked_links=self.blocked_links,
                                 link_penalties=self.nav_learning.link_penalties(mesh))
            straight = not route and bool(mesh.floor_segment(p["pos"], away))   # open floor behind him: straight back
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
            route, straight = None, False
        if not route and not straight:
            self._boss_run = None
            self.stats["boss"] = f"{key:#x} hp {boss.get('hp')}/{boss.get('hp_max')} {dist:.0f} away: no way back, firing"
            return None                                       # walls behind: the fight here
        self.stats["phase"] = "boss_range"
        self.stats["boss"] = f"{key:#x} hp {boss.get('hp')}/{boss.get('hp_max')} {dist:.0f} away: backing off"
        self.plan_target = {"kind": "boss_range", "id": key, "pos": away}
        self.aiming_since = None
        if straight:
            return {"hold": self._walk(p, heading(px - bx, pz - bz), now)}
        return self._follow(p, {"ptr": "boss_range", "pos": away}, mesh, snap.get("stage_prompt"), now,
                            retreat_from=tuple(boss["pos"]))

    def _stage_spawns(self) -> list:
        """This stage's spawn points: every Majini's first-seen position, this round's and the rounds' before
        (SPAWNS_FILE under the learn dir), SPAWN_CLUSTER_CM apart."""
        stage = self._spawn_seen_stage or str(self.stats.get("stage") or "stage")
        if stage not in self._spawn_points:
            points = []
            try:
                data = json.loads((self._learn_root / SPAWNS_FILE).read_text(encoding="utf-8"))
                points = [tuple(float(v) for v in pt) for pt in data.get(stage, []) if len(pt) == 3]
            except (OSError, ValueError, TypeError):
                pass
            self._spawn_points[stage] = points
        points = self._spawn_points[stage]
        for pos in self._spawn_seen.values():
            if all(math.hypot(pos[0] - q[0], pos[2] - q[2]) >= SPAWN_CLUSTER_CM for q in points):
                points.append(tuple(pos))
        return points

    def _spawn_remember(self) -> None:
        """The round's spawn points into SPAWNS_FILE for the next round on this stage."""
        if not self._spawn_seen:
            return
        stage, points = self._spawn_seen_stage or "stage", self._stage_spawns()
        path = self._learn_root / SPAWNS_FILE
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            if not isinstance(data, dict):
                data = {}
            data[stage] = [[round(v, 1) for v in pt] for pt in points]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass                                             # a lost memory never stops the round

    def _hunt_spawns(self, p, mesh, snap, now) -> dict | None:
        """The stand gone quiet (LULL_S with no living Majini; operator 2026-10-26: "there is supposed to be a certain
        amount dispatched for level completion and they are getting 78 enemies by the end and having long swaths of
        time where enemies are not spawning"): the game spawns around the player, so he walks to the spawn points this
        stage has shown, the farthest one not visited within HUNT_REVISIT_S first, until a Majini shows (the fight
        takes over at once). None: no spawn point is known for this stage yet (the first round there)."""
        px, _, pz = p["pos"]
        hunt = self._hunt
        if hunt is not None and (math.hypot(hunt["pos"][0] - px, hunt["pos"][2] - pz) <= HUNT_REACH
                                 or now - hunt["since"] > HUNT_GIVE_UP_S):
            self._hunt_visited[hunt["key"]] = now
            hunt = self._hunt = None
        if hunt is None:
            points = self._stage_spawns()
            fresh = [(k, pt) for k, pt in enumerate(points) if now - self._hunt_visited.get(k, -math.inf) > HUNT_REVISIT_S]
            if not fresh and points:
                self._hunt_visited.clear()                   # the whole tour done: again
                fresh = list(enumerate(points))
            if not fresh:
                self.stats["hunt"] = "no spawn point known for this stage yet"
                return None
            key, pt = max(fresh, key=lambda kp: math.hypot(kp[1][0] - px, kp[1][2] - pz))
            hunt = self._hunt = {"key": key, "pos": tuple(pt), "since": now}
            self.stats["spawn_hunts"] = self.stats.get("spawn_hunts", 0) + 1
        self.stats["phase"] = "hunt_spawns"
        self.stats["hunt"] = f"spawn point {hunt['key']} {math.hypot(hunt['pos'][0] - px, hunt['pos'][2] - pz):.0f} away"
        self.plan_target = {"kind": "hunt", "id": hunt["key"], "pos": hunt["pos"]}
        self.aiming_since = None
        return self._follow(p, {"ptr": "hunt", "pos": hunt["pos"]}, mesh, snap.get("stage_prompt"), now)

    def _stage_loop(self, p, now) -> bool:
        """The same ladder / ledge (ground distance: a ladder's top and foot) taken STAGE_LOOP_N times in STAGE_LOOP_S:
        left alone there for STAGE_BAN_S, and the bonus / waypoint the route chased through it is skipped, so the
        level goes on instead of up-down-up-down (operator 2026-10-24)."""
        x, _, z = p["pos"]
        ban = getattr(self, "stage_ban", None)
        if ban and now < ban[2] and math.hypot(x - ban[0], z - ban[1]) < STAGE_LOOP_R:
            self.stats["stage_loops_refused"] = self.stats.get("stage_loops_refused", 0) + 1
            return True
        presses = [(t, px, pz) for t, px, pz in getattr(self, "stage_uses", []) if now - t < STAGE_LOOP_S]
        near = [u for u in presses if math.hypot(x - u[1], z - u[2]) < STAGE_LOOP_R]
        if not near or now - near[-1][0] > 2.0:                 # one use per prompt, not one per tick it is up
            presses.append((now, x, z))
            near.append((now, x, z))
        self.stage_uses = presses
        if len(near) < STAGE_LOOP_N:
            return False
        self.stage_ban, self.stage_uses = (x, z, now + STAGE_BAN_S), []
        self.stats["stage_loops_broken"] = self.stats.get("stage_loops_broken", 0) + 1
        target = self.plan_target or {}
        if target.get("kind") in ("bonus", "time") and target.get("id") is not None:
            self.bonus_skip[target["id"]] = now + STAGE_BAN_S
        self.route = None
        return True

    def _live_weapon_action(self, p, snap, now):
        """Use this bot's existing input owner, native pickup prompt and equip menu."""
        from . import re5_live_weapon as L
        state = self._control_state or {}
        cfg = state.get('live_weapon') or {}
        ad = getattr(self.m, 'adapter', None)
        def current():
            return cfg.get('controller_owner') == id(self) and L.current_request(state, cfg, ad)
        def emit(action):
            if current():
                return action
            self.inventory_live_weapon.reset()
            return {'hold': set()}
        self.stats['live_weapon_phase'] = cfg.get('phase', 'idle')
        self.stats['live_weapon_reason'] = cfg.get('reason', '')
        if not current():
            self.inventory_live_weapon.reset()
            return None
        if snap.get('rotten_egg_only'):
            cfg['reason'] = 'Waiting for the active egg-only controller to release weapon selection.'
            return None
        if p.get('ptr') != cfg.get('player') or snap.get('prompt') or snap.get('recovery_active') \
                or self.healing is not None or self.inventory_heal.active:
            return None
        if L.native_item(self.m, p['ptr'], snap.get('inventory'), held=True):
            return None
        target = L.inventory_item(self.m, p['ptr'], snap.get('inventory'))
        if target:
            if target.get('hand'):
                cfg['reason'] = 'Inventory selects the bow, but the native bow class/owner is unconfirmed.'
                return emit({'hold': set()})
            if any((e.get('hp') or 0) > 0 and math.dist(p['pos'], e['pos']) < 350.
                   for e in snap.get('enemies') or ()):
                cfg['reason'] = 'Bow inventory exists; waiting for a safe ordinary equip.'
                return None
            self.stats['phase'] = 'live_weapon_equip'
            self.bonus_commitment.pause(now)
            if re5_weapons.quick_key(target):
                return emit(self._switch_weapon(target, now, 'live native bow request') or {'hold': set()})
            return emit(self.inventory_live_weapon.tick(self.m, snap, target, now) or {'hold': set()})
        if ad is not None:
            L.queue_supply(ad)
        if now - self.live_weapon_rows_at >= .4:
            self.live_weapon_rows = L.rows(self.m, cfg.get('donor'))
            self.live_weapon_rows_at = now
        world = self.live_weapon_rows
        candidates = [row for row in world if row['id'] == L.ITEM]
        if not candidates:
            return None
        row = min(candidates, key=lambda v: math.dist(p['pos'], v['pos']))
        if now - self.live_weapon_pickup_at < .7:
            return emit({'hold': set()})
        request = selected_prompt(self.m, include_item_pickups=True)
        if L.pickup_request(self.m, request, row, cfg.get('donor')):
            self.live_weapon_pickup_at = now
            cfg['reason'] = 'Exact bow pickup pressed; waiting for game-created inventory and weapon.'
            return emit({'tap': 'square'})
        mesh = snap.get('nav')
        if mesh is None or any((e.get('hp') or 0) > 0 and math.dist(p['pos'], e['pos']) < 350.
                               for e in snap.get('enemies') or ()):
            return None
        hazards = [(v['pos'], 600.) for v in (snap.get('ground_mines') or {}).values()]
        route = mesh.route_avoiding_hazards(p['pos'], row['pos'], hazards)
        if not route or any((e.get('hp') or 0) > 0 and any(math.dist(e['pos'], point) < 350.
                           for point in [p['pos']] + route) for e in snap.get('enemies') or ()):
            return None
        if math.dist(p['pos'], row['pos']) < 100.:
            err = wrap(heading(row['pos'][0]-p['pos'][0], row['pos'][2]-p['pos'][2])-p['rot'])
            return emit({'hold': self._turn(err, aiming=False)})
        self.stats['phase'] = 'live_weapon_pickup'
        self.plan_target = {'kind': 'item', 'id': row['handle'], 'pos': row['pos']}
        return emit(self._follow(p, {'ptr': ('live_weapon', row['ptr']), 'pos': row['pos']}, mesh,
                                snap.get('stage_prompt'), now, learn=False))

    def _egg_action(self,p,snap,now,*,for_square=False):
        """One input owner for requested egg supply/equip and live-off gun restore."""
        from . import re5_eggs as E
        cfg=(self._control_state or {}).get('rotten_eggs') or {}
        on=bool(cfg.get('on'));snap['rotten_egg_only']=on
        self.stats['rotten_egg_only']=on
        self.stats['egg_native_equipped']=snap['rotten_egg_native_equipped']=False
        self.stats['egg_status']=cfg.get('status','disabled' if not on else 'native egg equip pending')
        inv=snap.get('inventory') or ();hand=equipped(snap)
        if on and not self.egg_requested:
            self.inventory_egg.reset();self.egg_ready_at=None
            self._egg_departure=None
            if hand and hand.get('id')!=E.EGG_ID:self.egg_return_weapon=re5_weapons.inventory_key(hand)
        if not on and self.egg_requested:
            self.inventory_egg.reset();self.egg_ready_at=None
            self._egg_departure=None
        self.egg_requested=on
        # Square while holding a rotten egg can eat it. Hold an existing gun
        # for a nearby time-bonus interaction, then return to eggs; never fire it.
        at_bonus=on and any(b.get('kind','time')=='time' and math.dist(p['pos'],b['pos'])<BONUS_REACH
                           for b in snap.get('bonuses') or ())
        restoring=not on or at_bonus or for_square
        if restoring:
            cfg['native_equipped']=False
            if at_bonus or for_square:cfg['status']='safe Square interaction; existing gun required'
            self.stats['egg_status']=cfg.get('status','returning to existing gun')
            if not hand or hand.get('id')!=E.EGG_ID:
                return None
            choices=[v for v in inv if v.get('id') in self.inventory_egg.allowed_ids
                     and v.get('id')!=E.EGG_ID and v.get('rounds',0)>0]
            target=self._preferred_gun(snap) \
                or next((v for v in choices if re5_weapons.inventory_key(v)==self.egg_return_weapon),None) \
                or next(iter(choices),None)
            cfg['status']='safe Square interaction; existing gun required' if at_bonus or for_square else 'returning to existing gun'
            self.stats['egg_status']=cfg['status']
        else:
            target=E.inventory_item(self.m,p['ptr'],inv) if self.m is not None else None
            held_native=E.carried(self.m,p['ptr'],inv) if target is not None else None
            cfg['native_equipped']=snap['rotten_egg_native_equipped']=bool(held_native)
            if held_native:
                self.inventory_egg.reset();self.egg_ready_at=None
                self._egg_departure=None
                cfg['status']='active: native rotten egg equipped; throw cadence and ballistic calibration unverified'
                self.stats['egg_native_equipped']=True
                self.stats['egg_status']=cfg['status']
                return None
            if target and target.get('hand'):
                cfg['status']='native egg selected; waiting for verified game-created uWp36 owner'
                self.stats['egg_status']=cfg['status']
                return {'hold':set()}
            if target:
                cfg['status']='native egg available; ordinary equip pending'
                self.stats['egg_status']=cfg['status']
        if target is not None:
            self.stats['phase']='egg_inventory' if on and not at_bonus else 'egg_restore_weapon'
            self.bonus_commitment.pause(now)
            self.switch_pending=None
            if re5_weapons.quick_key(target):
                if self.egg_ready_at is None:self.egg_ready_at=now+1.
                if now<self.egg_ready_at or p.get('action')==2:return {'hold':set()}
                self.egg_ready_at=None
                return self._switch_weapon(target,now,'egg mode selection') or {'hold':set()}
            return self.inventory_egg.tick(self.m,snap,target,now) or {'hold':set()}
        if restoring:return {'hold':set()} if hand and hand.get('id')==E.EGG_ID else None
        self.stats['egg_native_equipped']=False
        self.stats['egg_status']=cfg.get('status','waiting for native egg supply')
        ad=getattr(self.m,'adapter',None)
        if ad is not None:E.queue_supply(ad)
        if now-self.egg_rows_at>=.4:
            self.egg_rows=E.world_items(self.m,cfg.get('donor')) if self.m is not None else []
            self.egg_rows_at=now
        rows=[v for v in self.egg_rows if v['id']==E.EGG_ID]
        if not rows or at_bonus:
            return None if at_bonus else self._pending_egg_departure(p,snap,now)
        row=min(rows,key=lambda v:math.dist(p['pos'],v['pos']))
        if now-self.egg_pickup_at<.7:return {'hold':set()}
        request=selected_prompt(self.m,include_item_pickups=True)
        if E.pickup_request(self.m,request,row,cfg.get('donor')):
            self.egg_pickup_at=now
            self.stats['egg_pickup_presses']=self.stats.get('egg_pickup_presses',0)+1
            cfg['status']='exact egg pickup pressed; awaiting game-created inventory'
            self.stats['egg_status']=cfg['status']
            return {'tap':'square'}
        mesh=snap.get('nav')
        if mesh is None:return None
        if any((e.get('hp') or 0)>0 and math.dist(p['pos'],e['pos'])<350. for e in snap.get('enemies') or ()):
            return self._pending_egg_departure(p,snap,now)
        if math.dist(p['pos'],row['pos'])<100.:
            err=wrap(heading(row['pos'][0]-p['pos'][0],row['pos'][2]-p['pos'][2])-p['rot'])
            return {'hold':self._turn(err,aiming=False)}
        self.stats['phase']='acquire_rotten_eggs'
        self.plan_target={'kind':'item','id':row['handle'],'pos':row['pos']}
        return self._follow(p,{'ptr':('egg_supply',row['ptr']),'pos':row['pos']},mesh,
                            snap.get('stage_prompt'),now,learn=False)

    def _pending_egg_departure(self,p,snap,now):
        """Leave a crowd on measured floor while awaiting native eggs; never authorize a gun or unsafe conversion."""
        foes=[e for e in snap.get('enemies') or () if (e.get('hp') or 0)>0 and (e.get('hp_max') or 0)>1]
        close=[e for e in foes if math.dist(p['pos'],e['pos'])<350.]
        if not close:
            self._egg_departure=None
            self.stats['egg_supply_departure_status']='crowd clearance established; native supply may retry'
            return None
        if snap.get('prompt') or snap.get('stage_prompt') or snap.get('recovery_active') \
                or p.get('action') not in (0,1,2) or (p.get('hp') or 0)<=1 \
                or self.healing is not None or self.inventory_heal.active \
                or getattr(getattr(self,'mines',None),'escape',None) is not None:
            self.stats['egg_supply_departure_status']='mandatory action, healing or owned mine escape retains input'
            return None
        mesh=snap.get('nav')
        if mesh is None or any(math.dist(p['pos'],e['pos'])<=TOO_CLOSE for e in close):
            self.stats['egg_supply_departure_status']='no measured floor or actual contact prevents departure'
            return None
        hazards=[(v['pos'],600.) for v in (snap.get('ground_mines') or {}).values()]
        enemy_margins=[(e['pos'],350.) for e in foes]
        def safe(route):
            return bool(route) and all(not isinstance(w,re5_nav.Traversal) for w in route) \
                and all(mesh.floor_segment(a,b) and mesh.hazard_segment_clear(a,b,hazards)
                        and mesh.hazard_segment_clear(a,b,enemy_margins,departing=True)
                        for a,b in zip([p['pos']]+route,route)) \
                and all(math.dist(route[-1],e['pos'])>=450. for e in close)
        scope=p.get('ptr'),self.stats.get('rounds',0),mesh.learning_sig
        state=getattr(self,'_egg_departure',None)
        if state and (state['scope']!=scope or now<state['at'] or now-state['at']>3.):
            if state['scope']==scope and math.dist(p['pos'],state['start'])<40.:
                self.stats['egg_supply_departure_status']='bounded departure made no measured progress; movement released'
                self._egg_departure=None
                return {'hold':set()}
            state=None
        route=None
        if state:
            route=mesh.route(p['pos'],state['goal'],avoid=self.avoid,pull=False,blocked_links=self.blocked_links,
                             link_penalties=self.nav_learning.link_penalties(mesh))
            if not safe(route):state=None
        if state is None:
            centres=[e['pos'] for e in sorted(close,key=lambda e:math.dist(p['pos'],e['pos']))[:3]]
            centres.append(tuple(sum(e['pos'][i] for e in close)/len(close) for i in range(3)))
            options=[]
            for centre in centres:
                candidate=mesh.retreat(p['pos'],centre,500.,max_travel=800.,blocked_links=self.blocked_links,
                                       link_penalties=self.nav_learning.link_penalties(mesh))
                if safe(candidate):
                    verified=mesh.route(p['pos'],candidate[-1],avoid=self.avoid,pull=False,blocked_links=self.blocked_links,
                                        link_penalties=self.nav_learning.link_penalties(mesh))
                    if safe(verified):options.append(verified)
            if not options:
                self._egg_departure=None
                self.stats['egg_supply_departure_status']='no supported departure clears all enemies and observed mines'
                return {'hold':set()}
            route=min(options,key=lambda r:sum(math.dist(a,b) for a,b in zip([p['pos']]+r,r)))
            state={'scope':scope,'at':now,'start':tuple(p['pos']),'goal':tuple(route[-1])}
            self.stats['egg_supply_departure_routes']=self.stats.get('egg_supply_departure_routes',0)+1
        self._egg_departure=state
        self.bonus_commitment.pause(now)
        self.stats['phase']='egg_supply_departure'
        self.stats['egg_supply_departure_status']='supported departure away from crowd; native conversion guard unchanged'
        self.plan_target={'kind':'egg_supply_departure','id':'clear_crowd','pos':state['goal']}
        action=self._follow(p,{'ptr':('egg_supply_departure',scope,state['goal']),'pos':state['goal']},mesh,False,now,learn=False)
        # _follow may replan or consume a portal. Check the actual returned route again before sending input.
        if not safe(self.route):
            self.stats['egg_supply_departure_status']='replanned departure failed fresh enemy or floor verification'
            return {'hold':set()}
        return {'hold':set(action.get('hold',()))-{'l1','r1','l2','square'}}

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

    def _follow(self, p, tgt, mesh, stage_prompt, now, learn=True, retreat_from=None, approved_route=None) -> dict:
        """One step along the navmesh to a time bonus: the route drawn again every REPLAN_S; the next waypoint walked
        to (turn, then run); at a ladder or a drop (the next waypoint straight above / below) the stage's square
        prompt is taken; a bonus followed ROUTE_STALE_S without being reached is left for BONUS_SKIP_S."""
        self._following_route, self._route_learn = True, learn
        self._route_mesh = mesh
        self._route_pos = tuple(p["pos"])
        pos = p["pos"]
        hazards = [(row['pos'],600.) for row in self.nav_dynamic_mines.values()]
        if mesh is not None and hazards and retreat_from is None:
            inside = next((centre for centre,radius in hazards if math.dist(pos,centre)<radius),None)
            if inside is not None:
                retreat = mesh.retreat(pos,inside,650.,blocked_links=self.blocked_links)
                if retreat and all(mesh.hazard_segment_clear(a,b,hazards,departing=True)
                                   for a,b in zip([pos]+retreat,retreat)):
                    self.stats['route'] = 'leaving observed bomb margin on supported floor'
                    return self._follow(p,{'ptr':('observed_mine_escape',tuple(inside)),'pos':retreat[-1]},mesh,
                                        False,now,learn=False,retreat_from=inside)
                self.stats['route'] = 'blocked: no supported departure from observed bomb margin'
                return {'hold':set()}
        if self.route_for != tgt["ptr"]:
            self.nav_learning.begin_route(mesh if learn else None, pos, tgt["pos"])
            self.route, self.route_for, self.route_since = None, tgt["ptr"], now
            self.route_at = -math.inf
            self.climb_at = self.climb_pos = self.climb_tick = None
            self.route_midpoints, self.route_stall, self.route_walk_at = True, None, None
            self.route_rechecks = 0
            self.route_effort, self.route_best, self.route_command_at = 0.0, math.inf, None
            self.traversal_started = self.traversal_pressed = None
        if self.route_walk_at is None or now - self.route_walk_at > 1.0:
            self.hist, self.route_stall = [], None           # combat / a prompt is not stationary walking evidence
            self.unstick_until = 0.0
            if self.traversal_pressed is None:
                self.traversal_started = None
        if approved_route is not None:
            self.route = list(approved_route)
            self.route_at = now
        self.route_walk_at = now
        if self.route_stall is not None and math.dist(pos, self.route_stall) >= STUCK_MOVE:
            self.route_stall = None
        if now - self.route_since > ROUTE_STALE_S:
            self._nav_finish("timed_out")
            self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
            self.stats["routes_given_up"] = self.stats.get("routes_given_up", 0) + 1
            self.route_for = None
            return {"hold": set()}
        crossing = self.route and any(isinstance(w, re5_nav.Traversal) for w in self.route[:2])
        if mesh is not None and now - self.route_at > REPLAN_S and not crossing:
            if retreat_from is not None:
                self.route = mesh.retreat(pos, retreat_from, 600., blocked_links=self.blocked_links,
                                          link_penalties=self.nav_learning.link_penalties(mesh))
                self.route_at = now
            else:
                self.route = mesh.route_avoiding_hazards(pos,tgt['pos'],hazards,avoid=self.avoid,
                    blocked_links=self.blocked_links,link_penalties=self.nav_learning.link_penalties(mesh)) if hazards \
                    else mesh.route(pos,tgt['pos'],avoid=self.avoid,pull=not self.route_midpoints,
                        blocked_links=self.blocked_links,link_penalties=self.nav_learning.link_penalties(mesh))
                self.route_at = now
                if learn and self.route:
                    hint = self.operator_guidance.route(mesh,pos,tgt['pos'],self.route,now,hazards=hazards,
                        blocked_links=self.blocked_links,avoid=self.avoid,
                        penalties=self.nav_learning.link_penalties(mesh), mode=self.stats.get('mercenaries_mode'),
                        selected_route_id=self.stats.get('selected_route_id') or None)
                    if hint:
                        self.route = hint['route']
                        self.stats['operator_route_suggestion'] = hint['suggestion_id']
        if not self.route:
            if mesh is not None:                           # an explicit no-route result must never mean run through it
                self._nav_finish("unreachable")
                until = now+BONUS_SKIP_S
                if self.blocked_until:
                    until = min(until,min(self.blocked_until.values()))
                    self.blocked_goal_retries.add(tgt["ptr"])
                self.bonus_skip[tgt["ptr"]] = until
                self.stats["route"] = "unreachable on current mesh"
                return {"hold": set()}
            self.stats["route"] = "waiting for stage navigation; no blind straight-line pursuit"
            return {"hold": set()}
        while len(self.route) > 1 and not isinstance(self.route[0], re5_nav.Traversal) \
                and math.hypot(self.route[0][0] - pos[0], self.route[0][2] - pos[2]) < WP_REACHED \
                and abs(self.route[0][1] - pos[1]) < WP_CLIMB:
            following = self.route[1]
            if isinstance(following, re5_nav.Traversal):
                if mesh is None or not mesh.floor_segment(pos, following.approach):
                    break
                self.route.pop(0)
                continue
            if abs(following[1] - pos[1]) < WP_CLIMB:
                if mesh is not None and not mesh.floor_segment(pos, following):
                    break                                 # being near a corner does not permit cutting across its wall
            elif math.hypot(self.route[0][0] - pos[0], self.route[0][2] - pos[2]) > 20.0:
                break                                     # reach the action link's approach before advancing to its height
            self.route.pop(0)
        w = self.route[0]
        checked = w.approach if isinstance(w,re5_nav.Traversal) else w
        if mesh is not None and hazards and not mesh.hazard_segment_clear(pos,checked,hazards,departing=retreat_from is not None):
            self.route,self.route_at = None,-math.inf
            self.stats['route'] = 'current observed bomb blocks next segment; replanning verified floor detour'
            return {'hold':set()}
        if isinstance(w, re5_nav.Traversal):
            return self._traverse(p, tgt, mesh, w, stage_prompt, now)
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
            if approved_route is not None:
                self.stats['route'] = 'demonstrated segment no longer has supported floor; awaiting revalidation'
                return {'hold':set()}
            # A funnel path or stale position that cannot be justified by the current floor must not drive ahead.
            # Edge midpoints stay inside the original triangle corridor; the next tick checks those too.
            self.route_rechecks += 1
            if self.route_rechecks >= 3:
                return self._block_route(tgt, now, "no supported floor segment after three route checks")
            if not self.route_midpoints:
                self.route_best, self.route_effort = math.inf, 0.0
            self.route_midpoints = True
            self.route = mesh.retreat(pos, retreat_from, 600., blocked_links=self.blocked_links) if retreat_from is not None \
                else mesh.route(pos, tgt["pos"], avoid=self.avoid, pull=False, blocked_links=self.blocked_links)
            self.route_at, self.hist = now, []
            self.stats["route"] = "rechecking route through recorded portals"
            return {"hold": set()}
        self.route_rechecks = 0
        remaining = sum(math.dist(a, b) for a, b in zip([pos] + self.route, self.route))
        if remaining < self.route_best - 80.0:
            self.route_best, self.route_effort = remaining, 0.0
        if self.route_command_at is not None and 0 < now - self.route_command_at <= 0.5:
            self.route_effort += now - self.route_command_at
        if self.route_effort >= 6.0:
            return self._block_route(tgt, now, "no route progress after six seconds of commanded movement")
        stuck = self.stats["stuck"]
        keys = self._walk(p, heading(w[0] - pos[0], w[2] - pos[2]), now, precise=True, run=flat >= WP_REACHED)
        self.route_command_at = now  # repeated turns/unstick jitter without progress also consume the route budget
        if self.stats["stuck"] > stuck:
            # Do not send the generic blind back/side step beside walls or mines.
            return self._block_route(tgt, now, "stationary floor approach; recording nearby native boundaries and replanning")
        return {"hold": keys}

    def _mine_retreat(self, p, snap, now):
        """Leave a verified planted bomb using floor support; resume the held checkpoint afterwards."""
        self.stats['mine_departure_yielded'] = False
        controller = getattr(self, "mines", None)
        escape = getattr(controller, "escape", None)
        if escape is None or controller.clear_escape(now, p["pos"]):
            return None
        self.stats["phase"] = "leave_proximity_bomb"
        self.stats["mine_retreat_status"] = "seeking supported floor route away from planted bomb"
        self.bonus_commitment.pause(now)
        def yield_removed_hazard():
            if not self._mine_hazard_removed(escape,snap.get('ground_mines')):
                return False
            # Keep the controller's measured-separation/anti-repeat obligation.
            # A verified dead bomb must not make a blocked exit leave us defenseless.
            self.nav_dynamic_mines = dict(snap['ground_mines'])
            self.stats['mine_departure_yielded'] = True
            self.stats['mine_retreat_status'] = 'detonated mine verified gone; combat/navigation resumed, further planting deferred'
            return True
        mesh = snap.get("nav")
        if mesh is None:
            if yield_removed_hazard():
                return None
            self.stats["mine_retreat_status"] = "blocked: no escape mesh; departure retains priority over combat"
            return {"hold": set()}
        retained = escape.get('hazards') or {escape['actor']: escape['pos']}
        self.nav_dynamic_mines = dict(snap.get('ground_mines') or {})
        self.nav_dynamic_mines.update({('retained',actor): {'pos':pos} for actor,pos in retained.items()})
        hazards = [(row['pos'], MINE_ESCAPE_CM) for row in self.nav_dynamic_mines.values()]
        def supported(candidate, margins=hazards):
            return bool(candidate) and not any(isinstance(point,re5_nav.Traversal) for point in candidate) \
                and all(mesh.floor_segment(a,b,blocked_links=self.blocked_links)
                        and mesh.hazard_segment_clear(a,b,margins,departing=True)
                        for a,b in zip([p['pos']]+list(candidate),candidate))
        if mesh.find(p["pos"],floor_only=True,height_slack=60.) is None:
            self.stats["mine_retreat_status"] = "returning to observed floor before escaping planted bomb"
            recovery = self._recover_nav(p,mesh,now)
            if not recovery.get('hold') and not recovery.get('tap') and yield_removed_hazard():
                return None
            return recovery
        cached = self.route_for == "mine_escape:" + str(escape["actor"]) and self.route and now-self.route_at<=REPLAN_S \
            and math.dist(p['pos'],self.route[-1])>WP_REACHED and supported(self.route)
        route = self.route if cached else None
        if route is None and escape.get('geometry') == mesh.learning_sig:
            # The placement preflight already bought a departure toward the held
            # checkpoint. Keep that direction instead of picking an arbitrary retreat.
            # Passed waypoints may be dropped only when the remaining path still
            # passes fresh floor, blocked-link and actual planted-mine checks.
            planned = escape.get('route') or []
            route = next((planned[i:] for i in range(len(planned)) if supported(planned[i:])),None)
        if route is None:
            route = mesh.retreat(p["pos"], escape["pos"], MINE_ESCAPE_CM,
                blocked_links=self.blocked_links, link_penalties=self.nav_learning.link_penalties(mesh))
            if not supported(route):
                route = None
        checkpoint_exit = bool(cached and escape.get('checkpoint_exit'))
        if not route and escape.get('removal_recorded') and len(retained)==1 \
                and getattr(snap.get('ground_mines'), 'verified', True):
            # A vanished, previously detonating actor removes that hazard, not
            # the obligation to leave its site. A real checkpoint path can now
            # turn around a dead end instead of requiring monotonic separation.
            hazards = [(row['pos'],600.) for row in (snap.get('ground_mines') or {}).values()]
            for bonus in sorted((b for b in snap.get('bonuses') or () if b.get('kind')=='time'
                    and self.bonus_skip.get(b.get('ptr'),0)<=now),key=lambda b:math.dist(p['pos'],b['pos'])):
                if math.dist(bonus['pos'],escape['pos'])<600.:continue
                candidate = mesh.route_avoiding_hazards(p['pos'],bonus['pos'],hazards,avoid=self.avoid,
                    blocked_links=self.blocked_links,link_penalties=self.nav_learning.link_penalties(mesh))
                if candidate and not any(isinstance(point,re5_nav.Traversal) for point in candidate) \
                        and all(mesh.floor_segment(a,b) for a,b in zip([p['pos']]+candidate,candidate)):
                    route,checkpoint_exit = candidate,True
                    self.nav_dynamic_mines = dict(snap.get('ground_mines') or {})
                    break
        for distance in (450., 300.):                       # a shorter measured way off the bomb before none at all
            if route:
                break
            candidate = mesh.retreat(p["pos"], escape["pos"], distance, blocked_links=self.blocked_links,
                                     link_penalties=self.nav_learning.link_penalties(mesh))
            route = candidate if supported(candidate) else None
        if not route:
            if yield_removed_hazard():
                return None
            self.stats["mine_retreat_status"] = "blocked: no supported departure; combat and repeat planting withheld"
            self.stats["mine_retreats_blocked"] = self.stats.get("mine_retreats_blocked", 0) + 1
            self.aiming_since = None
            return {"hold": set()}
        escape['checkpoint_exit'] = checkpoint_exit
        target = {"ptr": "mine_escape:" + str(escape["actor"]), "pos": route[-1]}
        self.plan_target = {"kind": "waypoint", "id": target["ptr"], "pos": target["pos"]}
        self.stats["mine_retreat_status"] = "moving away on supported floor; departure has priority"
        self.aiming_since = None
        return self._follow(p, target, mesh, False, now, learn=False,
                            retreat_from=None if checkpoint_exit else escape["pos"], approved_route=route)

    def _mine_checkpoint_exit(self, p, mesh, goal, distance):
        """A bounded ordinary-floor prefix of the held checkpoint's real route."""
        route = mesh.route(p['pos'],goal['pos'],avoid=self.avoid,blocked_links=self.blocked_links,
                           link_penalties=self.nav_learning.link_penalties(mesh))
        prefix, start = [], tuple(p['pos'])
        for point in route or ():
            if isinstance(point,re5_nav.Traversal):
                return None  # an unperformed door/ledge action cannot buy a mine exit
            previous = prefix[-1] if prefix else start
            if math.dist(previous,point)<1.:
                continue
            if math.dist(start,point)>=distance:
                # Clip a long segment at the clearance circle; distant enemies
                # beyond the departure must not invalidate an otherwise safe exit.
                delta = tuple(point[k]-previous[k] for k in range(3))
                offset = tuple(previous[k]-start[k] for k in range(3))
                a = sum(v*v for v in delta)
                b = sum(offset[k]*delta[k] for k in range(3))
                c = sum(v*v for v in offset)-distance*distance
                fraction = min(1.,max(0.,(-b+math.sqrt(max(0.,b*b-a*c)))/a))
                point = tuple(previous[k]+fraction*delta[k] for k in range(3))
                prefix.append(point)
                return prefix
            prefix.append(tuple(point))
        return None  # collect the nearby checkpoint before scheduling a mine

    def _mine_placement_preflight(self, snap, now):
        """Require a supported exit and a conservative observed threat margin, without relying on immunity."""
        from . import re5_mines
        p,mesh = snap.get('player'),snap.get('nav')
        if getattr(self,'mines',None) is not None:
            bind=getattr(self.mines,'bind_learning',None)
            if callable(bind):bind(self.nav_learning,mesh)
        allowed = False
        reason = "navigation floor escape unavailable"
        enemies = [e for e in snap.get('enemies') or () if (e.get('hp') or 0)>0]
        def distance_to_segment(point,a,b):
            delta = tuple(b[k]-a[k] for k in range(3))
            length2 = sum(v*v for v in delta)
            t = max(0.,min(1.,sum((point[k]-a[k])*delta[k] for k in range(3))/max(length2,1e-9)))
            return math.dist(point,tuple(a[k]+t*delta[k] for k in range(3)))
        near_enemy = p and any(math.dist(p['pos'],e['pos'])<MINE_ENEMY_CM for e in enemies)
        if snap.get('ground_mines') is None or not getattr(snap.get('ground_mines'), 'verified', True):
            reason = "current ground-mine scan is incomplete"
        elif near_enemy:
            reason = f"living enemy within {MINE_ENEMY_CM:g}cm of deployment"
        elif p and mesh is not None:
            checkpoint = next((b for b in snap.get('bonuses') or ()
                if b.get('kind','time')=='time' and b.get('ptr')==self.bonus_commitment.goal
                and self.bonus_skip.get(b['ptr'],0)<=now),None)
            checkpoint_key = (checkpoint['ptr'],tuple(checkpoint['pos'])) if checkpoint else None
            previous = getattr(self,'_mine_preflight',None)
            if previous is not None and previous['geometry'] == mesh.learning_sig and now-previous['at']<2. \
                    and previous.get('blocked') == frozenset(self.blocked_links) \
                    and previous.get('checkpoint') == checkpoint_key and math.dist(previous['pos'],p['pos'])<25.:
                route = previous['route']
            else:
                exit_distance = MINE_ESCAPE_CM+re5_mines.SPAWN_MATCH_CM+50.
                route = self._mine_checkpoint_exit(p,mesh,checkpoint,exit_distance) if checkpoint else \
                    mesh.retreat(p['pos'],p['pos'],exit_distance,blocked_links=self.blocked_links,
                                 link_penalties=self.nav_learning.link_penalties(mesh))
                self._mine_preflight = {'geometry':mesh.learning_sig,'at':now,'pos':tuple(p['pos']),'route':route,
                                        'blocked':frozenset(self.blocked_links),'checkpoint':checkpoint_key}
            self.stats['mine_departure_policy'] = 'held time-checkpoint route' if checkpoint else 'measured floor retreat'
            if checkpoint and not route:
                reason = 'held checkpoint has no ordinary-floor mine departure; continue its route before planting'
            allowed = bool(route) and not any(isinstance(point,re5_nav.Traversal) for point in route) \
                and math.dist(p['pos'],route[-1])>=MINE_ESCAPE_CM+re5_mines.SPAWN_MATCH_CM \
                and all(mesh.floor_segment(a,b)
                        and mesh.hazard_segment_clear(a,b,[(p['pos'],MINE_ESCAPE_CM)],departing=True)
                        for a,b in zip([p['pos']]+list(route),route))
            if allowed:
                segments = list(zip([p['pos']]+route,route))
                if any(distance_to_segment(e['pos'],a,b)<MINE_ENEMY_CM for e in enemies for a,b in segments):
                    allowed,reason = False,f"living enemy within {MINE_ENEMY_CM:g}cm of escape corridor"
                elif any(distance_to_segment(mine['pos'],a,b)<600.
                         for mine in (snap.get('ground_mines') or {}).values() for a,b in segments):
                    allowed,reason = False,"observed ground bomb within 600cm of escape corridor"
                else:
                    reason = "supported escape; observed enemy and explosive margins clear"
        snap['mine_placement_safe'] = allowed
        snap['mine_escape_route'] = list(route) if allowed else None
        snap['mine_escape_geometry'] = mesh.learning_sig if allowed else None
        self.stats['mine_placement_route_verified'] = allowed
        self.stats['mine_placement_safety_reason'] = reason
        return allowed

    def _checkpoint_walk_allowed(self, snap, close_foes, now):
        """Give a supported departure a short movement window after measured safe crowd clearing.

        This uses ordinary HP and native kill observations. It never relies on immunity,
        authorizes walking into a nearby enemy, or substitutes a lease for floor support.
        """
        p = snap.get("player") or {}
        hp,maximum,kills = p.get('hp'),p.get('hp_max'),snap.get('kills')
        scope = p.get('ptr'),self.stats.get('rounds',0)
        observed = getattr(self,'_checkpoint_observed',None)
        if observed is None or observed['scope']!=scope or now<observed['at'] or now-observed['at']>2.:
            observed = {'scope':scope,'at':now,'hp':hp,'kills':kills,'stable_since':now,'kill_at':-math.inf}
            self.checkpoint_clear_since,self.checkpoint_walk_until = None,0.
        else:
            if isinstance(hp,(int,float)) and isinstance(observed['hp'],(int,float)) and hp<observed['hp']:
                observed['stable_since']=now
                self.checkpoint_clear_since,self.checkpoint_walk_until = None,0.
            if type(kills) is int and type(observed['kills']) is int:
                if kills>observed['kills']:
                    observed['kill_at']=now
                elif kills<observed['kills']:
                    observed['stable_since'],observed['kill_at']=now,-math.inf
                    self.checkpoint_clear_since,self.checkpoint_walk_until = None,0.
            observed.update(at=now,hp=hp,kills=kills)
        self._checkpoint_observed=observed
        mesh = snap.get('nav')
        goals = [b for b in snap.get('bonuses') or () if b.get('kind','time')=='time'
                 and self.bonus_skip.get(b['ptr'],0)<=now]
        reason = 'route normally' if not close_foes else 'waiting for stable HP and a measured clear departure'
        permitted = bool(close_foes and mesh is not None and goals and p.get('pos')
            and type(hp) in (int,float) and type(maximum) in (int,float) and maximum>0 and hp>maximum*.4
            and not snap.get('prompt') and not snap.get('stage_prompt') and not snap.get('recovery_active')
            and p.get('action') not in (4,5))
        if permitted:
            # Test the actual first floor segment, not the straight line to an hourglass through a wall.
            # Use the same held/tour-selected checkpoint that _tick will follow, not a different nearest bonus.
            goal = self._bonus(p,[],goals,now,mesh,snap.get('timer'),clearance_lease=True)
            if goal is None:
                self.checkpoint_clear_since,self.checkpoint_walk_until=None,0.
                self.stats['checkpoint_threat_policy']='no reachable held time checkpoint'
                return False
            route = self.route if self.route_for==goal['ptr'] and self.route else mesh.route(p['pos'],goal['pos'],
                avoid=self.avoid,blocked_links=self.blocked_links,link_penalties=self.nav_learning.link_penalties(mesh))
            waypoint = next((w for w in route or () if math.dist(p['pos'],w)>20.),None)
            permitted = waypoint is not None and not isinstance(waypoint,re5_nav.Traversal)
            if permitted:
                distance = math.dist(p['pos'],waypoint)
                step = tuple(p['pos'][i]+(waypoint[i]-p['pos'][i])*min(1.,200./distance) for i in range(3))
                enemies = [e for e in snap.get('enemies') or close_foes if (e.get('hp') or 0)>0 and (e.get('hp_max') or 0)>1]
                mines = [(m['pos'],600.) for m in (snap.get('ground_mines') or {}).values()]
                permitted = mesh.floor_segment(p['pos'],step) and mesh.hazard_segment_clear(p['pos'],step,mines) \
                    and mesh.hazard_segment_clear(p['pos'],step,[(e['pos'],220.) for e in enemies]) \
                    and all(math.dist(step,e['pos'])>=math.dist(p['pos'],e['pos'])-20. for e in close_foes)
                if not permitted:
                    reason = 'checkpoint departure blocked by floor, enemy clearance or observed mine'
                else:
                    recently_cleared = now-observed['kill_at']<=4.
                    separated = all(math.dist(p['pos'],e['pos'])>=280. for e in close_foes)
                    permitted = now-observed['stable_since']>=1. and (recently_cleared or separated)
            else:
                reason = 'no supported ordinary floor departure; traversal needs its actual prompt'
        if not permitted:
            self.checkpoint_clear_since,self.checkpoint_walk_until = None,0.
            self.stats['checkpoint_threat_policy']=reason
            return False
        if now < self.checkpoint_walk_until:
            self.stats['checkpoint_threat_policy']='normal-HP supported departure; movement window <=0.8s'
            return True
        if self.checkpoint_clear_since is None:
            self.checkpoint_clear_since = now
        if now-self.checkpoint_clear_since >= 1.2:
            self.checkpoint_walk_until,self.checkpoint_clear_since = now+.8,None
            self.stats['checkpoint_threat_policy']='normal-HP supported departure; movement window <=0.8s'
            self.stats["checkpoint_walk_leases"] = self.stats.get("checkpoint_walk_leases",0)+1
            return True
        self.stats['checkpoint_threat_policy']='bounded crowd clearing before supported departure'
        return False


    def _traverse(self, p, tgt, mesh, crossing, stage_prompt, now):
        pos, approach = p["pos"], crossing.approach
        hazards = [(row['pos'],600.) for row in self.nav_dynamic_mines.values()]
        if not mesh.hazard_segment_clear(crossing,crossing,hazards):
            self.route,self.route_at = None,-math.inf
            self.stats['route'] = 'stage action deferred: observed bomb at its measured landing'
            return {'hold':set()}
        landing_radius = 250. if abs(crossing[1] - approach[1]) >= BONUS_LEVEL_DY else WP_REACHED
        if math.dist(pos, crossing) < landing_radius and abs(pos[1] - crossing[1]) < BONUS_LEVEL_DY \
                and mesh.floor_segment(pos, crossing):
            self.route.pop(0)
            self.traversal_started = self.traversal_pressed = None
            self.stats["traversals_completed"] = self.stats.get("traversals_completed", 0) + 1
            if hasattr(self, "mines"):
                self.mines.cadence.entrance = True
            self.stats["route"] = "traversal landing reached on destination floor"
            return {"hold": set()}
        self.stats["route"] = f"traversal {'up' if crossing[1] > approach[1] else 'down/across'}; landing dy {crossing[1] - pos[1]:+.0f}"
        if self.traversal_started is None:
            if math.dist(pos, approach) > 35.:
                if not mesh.floor_segment(pos, approach):
                    return self._block_route(tgt, now, "traversal approach is not on reachable floor")
                return {"hold": self._walk(p, heading(approach[0] - pos[0], approach[2] - pos[2]),
                                             now, precise=True, run=False)}
        if self.traversal_started is not None and now - self.traversal_started > \
                (10.0 if self.traversal_pressed is not None else CLIMB_WAIT_S):
            self._nav_finish("blocked")
            self.avoid.append(crossing.portal)
            self.stats["crossings_avoided"] = self.stats.get("crossings_avoided", 0) + 1
            self.route = self.route_len = None
            self.route_at = -math.inf
            self.traversal_started = self.traversal_pressed = None
            self.stats["route"] = "action link did not complete; replanning through another entrance"
            return {"hold": set()}
        if stage_prompt:
            if self.traversal_started is None:
                self.traversal_started = now
            self.traversal_pressed = now
            self.stats["climbs"] = self.stats.get("climbs", 0) + 1
            return {"tap": "square"}
        if abs(pos[1] - approach[1]) >= BONUS_LEVEL_DY:
            return {"hold": set()}  # an in-flight climb is not evidence of a new walkable floor
        # The enemy mesh's landing is inset into the far floor. On Prison
        # this lies opposite the ladder's entrance, so facing the landing
        # turns away from the ladder. Face the measured entry portal.
        dx,dz = crossing.portal[0]-approach[0],crossing.portal[2]-approach[2]
        if math.hypot(dx,dz)<1.:
            dx,dz = crossing[0]-approach[0],crossing[2]-approach[2]
        way = heading(dx,dz)
        err = wrap(way - p["rot"])
        if abs(err) > math.radians(20):
            if self.traversal_pressed is None:
                self.traversal_started = None
            return {"hold": self._turn(err, aiming=False)}
        if self.traversal_started is None:
            self.traversal_started = now
        # Approach the action trigger slowly for a bounded interval; never run or fire into the face.
        return {"hold": {"lup"}}


    def _recover_nav(self, p, mesh, now):
        """Back toward recently observed or nearby same-level floor with bounded movement probes."""
        self.stats["phase"] = "recover_navigation"
        self._interrupt_route_walk()
        state = self.nav_recovery
        if state is None or math.dist(state["origin"], p["pos"]) > 100.:
            points = mesh.recovery_points(p["pos"])
            previous = self.nav_last_good
            if previous is not None and math.dist(previous, p["pos"]) < 250. \
                    and abs(previous[1] - p["pos"][1]) < 50.:
                points.insert(0, previous)
            state = self.nav_recovery = {"origin": tuple(p["pos"]), "points": points,
                                         "index": 0, "started": now, "walking": None}
        if state["index"] >= len(state["points"]) or now - state["started"] > 15.:
            self.stats["nav_recovery"] = "no safe floor recovery observed; movement stopped"
            return {"hold": set()}
        q = state["points"][state["index"]]
        hazards = [(row['pos'],600.) for row in self.nav_dynamic_mines.values()]
        if not mesh.hazard_segment_clear(p['pos'],q,hazards,departing=True):
            state['index'] += 1
            state['walking'] = None
            self.stats['nav_recovery'] = 'recovery probe rejected by current observed bomb margin'
            return {'hold':set()}
        if getattr(getattr(self,'mines',None),'escape',None) is not None \
                and not mesh.floor_segment(p['pos'],q,blocked_links=self.blocked_links):
            state['index'] += 1
            state['walking'] = None
            self.stats['nav_recovery'] = 'mine escape retains priority; recovery segment has no verified floor support'
            return {'hold':set()}
        err = wrap(heading(q[0] - p["pos"][0], q[2] - p["pos"][2]) - p["rot"])
        self.stats["nav_recovery"] = f"probe {state['index'] + 1}: returning to nearby same-level floor"
        if abs(err) > math.radians(20):
            return {"hold": self._turn(err, aiming=False)}
        if state["walking"] is None:
            state["walking"] = now
        if now - state["walking"] > 1.2:
            state["index"] += 1
            state["walking"] = None
            return {"hold": set()}
        return {"hold": {"lup"}}  # no sprint, aim or fire; actual floor membership must confirm recovery


    def _remember_traversal_prompt(self, now):
        # The engine can answer stage prompts without calling Bot.tick(). Retain the attempt across its animation.
        if not self.route:
            return
        index = next((i for i, w in enumerate(self.route[:2]) if isinstance(w, re5_nav.Traversal)), None)
        if index is not None:
            self.route = self.route[index:]
            if self.traversal_pressed is None:
                self.stats["traversal_attempts"] = self.stats.get("traversal_attempts", 0) + 1
            self.traversal_pressed = now
            if self.traversal_started is None:
                self.traversal_started = now


    def _nav_finish(self, outcome):
        if getattr(self, "_route_learn", True):          # a pursuit's route outcome is not the stage's route record
            self.nav_learning.finish_route(outcome)

    def _block_route(self, tgt, now, reason):
        self.nav_hazards = (self.nav_hazards + [{"pos": getattr(self, "_route_pos", tuple(tgt["pos"])),
                                                "reason": reason[:160], "at": now}])[-64:]
        self._nav_finish("blocked")
        link = getattr(self.route[0], "link", None) if self.route else None
        mesh = getattr(self, '_route_mesh', None)
        self.nav_learning.blocked(mesh, link)
        approach = self.route[0] if self.route and not isinstance(self.route[0],re5_nav.Traversal) \
            and ('stationary' in reason or 'six seconds' in reason) else None
        context = self.nav_learning.obstruction(mesh, getattr(self,'_route_pos',tgt['pos']),tgt['pos'],reason,approach=approach)
        if context:
            self.stats['nav_obstruction_context'] = context
            self.stats['nav_boundary_traces'] = self.stats.get('nav_boundary_traces',0)+1
        self.nav_learning.save()
        attempts = self.route_failures.get(tgt["ptr"], 0)
        if link is not None and link not in self.blocked_links and attempts < 2:
            self.blocked_links.add(link)
            self.blocked_until[link] = now+self.nav_learning.retry_delay(mesh,link)
            self.route_failures[tgt["ptr"]] = attempts + 1
            self.route = self.route_len = None
            self.route_at, self.route_best = -math.inf, math.inf
            self.route_effort = 0.
            self._interrupt_route_walk()
            self.stats["route_replans"] = self.stats.get("route_replans", 0) + 1
            self.stats["route"] = "no progress through recorded portal; trying an alternate route"
            return {"hold": set()}
        self.bonus_skip[tgt["ptr"]] = now + BONUS_SKIP_S
        self.stats["routes_blocked"] = self.stats.get("routes_blocked", 0) + 1
        self.stats["route"] = reason
        self.route = self.route_for = self.route_len = None
        self._interrupt_route_walk()
        return {"hold": set()}

    def _expire_navigation_blocks(self, now):
        """A stationary attempt proves a failed attempt, not a permanent wall.

        Temporary actors and round intro input locks can obstruct a valid portal.
        Retain measured soft costs, but periodically recheck the game's existing
        directed floor link with the normal bounded movement budget.
        """
        expired = [link for link,until in self.blocked_until.items() if now>=until]
        if not expired:
            return
        for link in expired:
            self.blocked_links.discard(link)
            del self.blocked_until[link]
        for goal in self.blocked_goal_retries:
            self.bonus_skip.pop(goal,None)
        self.blocked_goal_retries.clear()
        self.route_len,self.route_at = None,-math.inf
        self.stats["nav_portal_rechecks"] = self.stats.get("nav_portal_rechecks",0)+len(expired)


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

    def detour_angle(self) -> float:
        """Heading offset for the walk after repeated stalls at one spot: 0, then +40, -40, +80, -80 ... up to 160 deg."""
        n = getattr(self, "detour_n", 0)
        if n <= 0:
            return 0.0
        k = (n + 1) // 2
        return min(k * DETOUR_STEP, DETOUR_MAX) * (1 if n % 2 else -1)

    def _operator_command(self, p, snap, live, now):
        """The operator's instant commands (gbox.mercs.directives). One-shots act on the tick they arrive; the standing modes
        (fight / hunt / score) are returned for _tick to apply. A command never presses a key itself: the normal combat,
        navigation, heal and prompt logic still decides every press. None: no command applies."""
        from ..directives import Reader
        if getattr(self, "commands", None) is None:
            self.commands = Reader()
        cmd, fresh = self.commands.current(self.stats, time.time())
        if cmd is None:
            return None
        self.stats["directive_active"] = cmd
        if fresh:
            self.stats["directive_status"] = "acting: " + cmd
        target = self.plan_target or {}
        if cmd in ("next_area", "repetitive", "explore") and fresh:
            if target.get("kind") in ("time", "combo", "bonus", "waypoint", "stand") and target.get("id") is not None:
                self.bonus_skip[target["id"]] = now + (30.0 if cmd == "next_area" else 20.0)
            elif target.get("id") is not None and self.combat is not None:
                self.combat.blocked_until[target["id"]] = now + 15.0     # this enemy / spot: not for a while
            self.route, self.route_len, self.route_at = None, None, -math.inf
            self.stuck_since = None
            self.stats["directive_status"] = {"next_area": "skipped this goal: heading for the next one",
                "repetitive": "dropped the repeated action and its route; planning a new one",
                "explore": "route reset; planning through the rest of the level"}[cmd]
            return None
        if cmd == "mine" and fresh:
            cadence = getattr(getattr(self, "mines", None), "cadence", None)
            if cadence is not None and cadence.enabled:
                cadence.last, cadence.position = now - cadence.interval - 1.0, None     # due now; the escape follows it
                self.stats["directive_status"] = "mine due now: planting at the next safe moment, then leaving"
            else:
                self.stats["directive_status"] = "mine placement is switched off (the mines setting)"
            return None
        if cmd == "missing" and fresh:
            if self.combat is not None and hasattr(self.combat, "widen_aim"):
                self.stats["directive_status"] = self.combat.widen_aim(now)
            else:
                self.stats["directive_status"] = "aim learning reset: the next shots re-measure this weapon"
                for key in ("aim_bias_deg", "aim_offset_deg"):
                    self.stats.pop(key, None)
            return None
        return cmd if cmd in ("fight", "hunt", "score") else None

    def _walk(self, p, want: float, now: float, *, precise=False, run=True) -> set:
        """Run toward a heading: turn first (the body turns in place), run (up + cross) once within 60 deg. Stuck
        (pushing forward STUCK_S without STUCK_MOVE of ground): a step back and aside for 0.8 s. Turning in place
        is never "stuck" (live 2026-10-21: it was, and the walk thrashed)."""
        if not precise:
            self._interrupt_route_walk()                   # a non-route pursuit must not inherit route stall samples
        px, py, pz = p["pos"]
        if now < self.unstick_until:
            return {"ldown", "lleft" if self.unstick_dir > 0 else "lright"}
        spot = getattr(self, "detour_spot", None)
        if spot is not None and math.hypot(px - spot[0], pz - spot[1]) > DETOUR_FREE:
            self.detour_spot, self.detour_n = None, 0
        if not precise:                                   # a route walk has its own blocked-route handling
            want = wrap(self.hold_heading.pick(want, now) + self.detour_angle())   # hysteresis, then wall detour
            self.stats["heading_flips_held"] = self.hold_heading.flips_suppressed
        else:
            self.hold_heading.reset()
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
            if not precise:
                if getattr(self, "detour_spot", None) is None:
                    self.detour_spot, self.detour_n = (px, pz), 0
                self.detour_n = getattr(self, "detour_n", 0) + 1
                self.stats["wall_detours"] = self.stats.get("wall_detours", 0) + 1
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
        self._result_tally = None
        self._menu_observation = None

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def participants(self, m, snap=None):
        from .re5_coop import participants
        return participants(m,snap)

    def readiness(self, m):
        from .re5_coop import readiness
        return readiness(m)

    def for_player(self, m, player=2, stats=None):
        from .re5_coop import for_player
        return for_player(m,player,stats)

    def recovery_active(self, m) -> bool:
        return recovery_active(m)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        where = own_screen(snap)
        self._menu_observation = alert_screen(m)
        if self._menu_observation is None and where != "playing":
            self._menu_observation = result_notice_screen(m)
        if self._menu_observation is not None:
            # A successful-save dialog may remain after the dead actor has been destroyed.
            # Its stopped countdown is modal state, not evidence of an emulator hang.
            if "result_unit" not in self._menu_observation or where != "results" or not snap.get("player"):
                where = self._menu_observation["where"]
        if where != "results":
            self._result_tally = None
        if where == "playing" and (snap.get("prompt") == "mash" or snap.get("recovery_active")):
            self._timer = (snap.get("timer"), self.clock())
        elif where == "playing":
            now, t = self.clock(), snap.get("timer")
            if t != self._timer[0]:
                self._timer = (t, now)
            elif now - self._timer[1] > HANG_S:
                return "loading"                            # frozen: the engine calls it lost (its LOST_S later)
        return where

    def menu_handoff(self, m, snap, where) -> bool:
        """Let the engine return neutral to menu navigation only for the same verified native menu."""
        observed = self._menu_observation
        if observed is None or where != observed["where"]:
            return False
        if observed.get("result_menu_verified") is True:
            return result_notice_screen(m) == observed
        return observed.get("alert_id") in ALERTS and alert_screen(m) == observed

    def result_ready(self, snap, now):
        """Bounded neutral observation of the terminal score tally before closing evidence.

        The native terminal phase can precede its score count-up. Wait at least
        two seconds and one unchanged second; fifteen seconds is an explicit
        evidence bound, not proof that an endlessly changing score is final.
        """
        signature = (snap.get("player") or {}).get("ptr"), snap.get("score"), snap.get("kills")
        state = self._result_tally
        if state is None or state["player"] != signature[0]:
            state = self._result_tally = {"player":signature[0],"signature":signature,"started":now,"changed":now}
        elif state["signature"] != signature:
            state.update(signature=signature,changed=now)
        return now-state["started"]>=15. or (now-state["started"]>=2. and now-state["changed"]>=1.)

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        return Bot(m, clock=clock, stats=stats, learn_dir=learn_dir)

    def prompt_source(self, m, stats: dict):
        self._stats = stats
        def source():
            button = prompt(m)
            if self._stats.get('mine_escape_active') or self._stats.get('mine_placement_pending'):
                request = selected_prompt(m,include_item_pickups=True)
                if request and request['kind'] in (BTN_MELEE,BTN_STAGE) and request['mode']==1 \
                        and request['token']=='mash:square':
                    yielded = False
                    if self._stats.get('mine_departure_yielded') and not self._stats.get('mine_placement_pending'):
                        from . import re5_mines
                        ground = re5_mines.ground_mines(m)
                        yielded = ground is not None and getattr(ground,'verified',True) and not ground
                    player = player_pointer(m)
                    if not yielded and ptr_ok(player) and request['owner']==player and m.rd(player+P_ACTION,1) not in (b'\x04',b'\x05') \
                            and struct.unpack('>h',m.rd(player+P_HP,2))[0]>0 and not recovery_active(m,player):
                        return None  # optional pickup/traversal/finisher cannot delay leaving a planted mine
            if button and 'square' in str(button) \
                    and egg_square_blocked(m,selected_prompt(m,include_item_pickups=True)) is not False:
                return None  # mash requests bypass PromptPresser.ok; fence before that path
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
        out = {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
               "kills": snap.get("kills"), "mercenaries_phase": snap.get("mercenaries_phase")}
        index = snap.get("stage_index")
        if isinstance(index, int) and 0 <= index < len(STAGE_NAMES):
            out.update(stage_index=index, stage=STAGE_NAMES[index])
        if snap.get('control_player') == 2 or snap.get('scoring_players') == 2:
            out.update(scoring_scope='team', score_scope='team', kills_scope='team', combo_scope='team',
                       rank=None, completed_score_rank=None, completed_score_rank_source=None,
                       character='unknown', character_cursor_verified=False,
                       character_source='native_per_player_roster_unverified')
            return out
        if ROSTER.round is None and snap.get("player"):
            ROSTER.started()
        out.update(ROSTER.observe(snap))
        rank = rank_of(snap.get("score"))
        if rank:
            out["rank"] = rank
        return out


DRIVER = RE5PS3
