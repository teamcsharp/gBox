"""Resident Evil 4 (GameCube G4BE08) Mercenaries autoplay playbook: an "any means necessary" run, played like a game.

setup() applies the hack package through re_mods (Mercenaries unlocked, Leon's loadout = the Hand Cannon at its own
fire rate with x99.9 damage (no explosive rounds: they kept him from firing close), infinite ammo (Leon mortal), time pickups x3, combo window x3 and
frozen, every Ganado cloned twice more, the aim's stick speed x3 (a game constant: the aim routine's scale); not full
auto: that restarted the magnum's recoil every 3 frames and bent Leon's arm back over his head). play() then drives
Leon from RAM at ~20 Hz with the pad only, the way a player would
(operator 2026-10-20: "I want the game to be played like a normal game"; "it is unnatural and nightmare fuel"): it
reads Leon and never writes him - no facing, aim pitch or position writes:
  * reads Leon (player em: *0x802B3044, +0x94 position, +0xA4 facing) and every live Ganado (EmMgr 0x8027DF20 slots:
    flags & 0x601 and +0x398 != 0xFF, +0x94 position);
  * steering is closed loop on his real facing: the stick turns him (left = +heading, ~140-230 deg/s measured on the
    Spark; a target behind him: the quick turn, back + B), R aims (the stick then fine-turns, pulsed when close: the
    package sets the game's aim sensitivity x AIM_SPEED_X, ~30 -> ~90 deg/s), A is pressed once per shot once the aim
    is within FIRE_TOL (2 degrees) - the Hand Cannon fires on a press, so A held down fired once and then nothing.
    Where the gun points is the game's own aim (the aim routine 0x8014415C): his facing plus the aim's horizontal
    offset (Leon +0x400: the stick moves it first, inside the weapon's small cone, then turns him; 0 as the aim comes
    up), and the aim's vertical blend (the global 0x80218738, -1 down .. +1 up, kept between aims); the aim height the
    same way: while R is held the stick moves that pitch towards the target, pulsed when close, and A fires within
    PITCH_TOL; which stick direction raises it is learned from what a push does (an inverted aim setting flips it);
  * fights any Ganado within ENGAGE;
  * with the disc's level map (gbox.re4_navmap: collision, the stage's item hourglasses, line of sight) it takes the
    reachable Time Bonus hourglasses in the planner's order (exact tour from where the round starts): runs its path
    (Up+B, ~3,300 units/s), pressing A at the fence / window waypoints, and takes each hourglass with A at its stand
    point (they are items: "TAKE"); a Combo Bonus when COMBO_CROWD Ganados are near (every kill in its 30 s scores
    more); then makes its stand: goes after the nearest Ganados; it fires only with a clear line of sight from the gun
    to the head. Without the map: the hourglass events in HOURGLASS, shot from range;
  * a learned map per stage (LearnedMap, saved after every round and every WALLS_PER_SAVE new walls): every cell Leon
    walks is floor, the cell ahead of him when he runs into something is wall (never the cell he stands on); the
    learned walls are authoritative over the disc's map: a path leg, or a straight run at a Ganado, that crosses one
    goes round it on the learned map (A*), navmap or not, and a stuck re-plans the goal's path, so a crate or cart
    the disc's collision does not know is hit once, not every round (operator 2026-10-24: "map the world like a
    Roomba: anytime they run into a wall it adds to the database"; 2026-10-20: "with every round that is played,
    the navigation map needs to improve"); every stuck is explained (stats stuck_reason: the cell, room, heading
    and what he did) and kept (Bot.stuck_log -> <learn_dir>/r<room>-stuck.jsonl at save());
  * presses what the screen asks for (operator 2026-10-20: "the characters ignore QTE opportunities ... detect that a
    press A dialogue is being required of them and press it"): prompt() (gbox.screen_prompt.Watcher on the session's
    picture: the button icon RE4 draws for JUMP OVER / JUMP THROUGH / TAKE / KICK / CLIMB / a grab) -> R let go,
    the button pressed, every PROMPT_EVERY s while it shows; a prompt still up after PROMPT_BURST presses in 3 s is
    left alone for PROMPT_REST s;
  * sees his shots (gbox.re4_threats.Shots): a press the gun could fire (35 frames since the last) is a shot; any
    Ganado's health falling, or one starting to die, within HIT_S of it is a hit (the Hand Cannon goes through
    bodies), else a miss (stats shots / hits / misses / kills / accuracy); MISSES_TO_ADJUST misses in a row at a raised
    or lowered target move the aim height to the next PITCH_STEPS offset, a hit keeps it (operator 2026-10-20: "every
    shot ... setting up the zombies to be stunned or eliminating them");
  * shoots only what he can hit (operator 2026-10-20: "shooting into walls near him and blowing himself up"): fires
    inside SHOOT_RANGE, not steeper down than STEEP_DOWN (that is the roof edge in front of him), at any range (no
    explosive rounds, so a point-blank shot is safe); further out he closes in; up on the start roof (HIGH_GROUND
    above the Ganados) he first runs to the edge towards them and jumps down;
  * threats first, from RAM (gbox.re4_threats; operator 2026-10-20: "too often I see Leon just sitting there just
    accepting an attack ... he should be proactive and shoot any attacking enemy", "shoot it out the air", "walking
    out of their attacks"): every tick ranks the Ganados by what their own code is doing - an attack (routine
    r_no_1 in the attack table) by the seconds until its hit frames (read ahead in the motion's event words), a
    weapon thrown at him (em 0x42) by its time to reach him, then the others by distance (dying ones are never
    shot at, knocked-down ones last); the most urgent is shot (lead for its speed; a level shot at the chest), or,
    when it lands before a shot can leave the gun (turn + aim pose + the gun's rate), run out of its reach (the
    quick turn when the way out is behind him; away from walls and other Ganados on the level map) or across a
    thrown weapon's line; two or more on top of him, or one there as he gets up from a hit: out first, then one by
    one. While he is hit or held (his routine 1) the game has him: play() presses SHAKE OFF / the QTE from RAM;
  * the stage bosses first (operator 2026-10-26, watching Leon die: "so i just watched leon just eat a chainsaw ...
    Does he not see these bosses? because they are high level threats that have to be dispatched. I see leon not
    taking them seriously ... letting them gang up near him is detrimental"): gbox.re4_threats.boss names them from
    RAM by their full health (BOSS_HP; the Village's Dr. Salvador 6500, the Waterworld's sisters 3500 / 5000 against
    400-1800 for the crowd - the ESLs, see re4_threats) - a boss in sight is the target before any ordinary Ganado
    unless an ordinary attack lands sooner than a shot at him can leave; the chainsaw man (one hit kills) is never
    allowed inside CHAINSAW_KEEP without an answer: in there and not in front of Leon he gets the run-out (_way_out:
    away from walls and the other Ganados; the quick turn first when the way out is behind), once per
    CHAINSAW_REEVADE_S, and the quick turn + fire after it; in front, or outside the keep-out, he is shot continuously
    (RE4 roots Leon while he aims: there is no firing while running or backing off - the shots come after the turn).
    The gun is whatever the round's loadout gave (one gun a round: random_loadout guns=1, so there is nothing stronger
    in the case to switch to; re_mods equip_item could swap through the dispatcher but the bot plays with the pad);
    the stats "combat" / "boss" lines name every boss target ("boss chainsaw 0x16 hp 6500/6500 dist 1840") and
    "bosses" lists every boss seen as {id, type, hp_max, room} so the next round proves the classifier;
  * crowd control (operator 2026-10-26: "he carries a shotgun for crowd control so he cant just be letting these guys
    crowd. Thats a combo wasting"): CROWD_N Ganados inside CROWD_R get the run-out as before - but with a shotgun in
    his hands (SHOTGUNS; the weapon in hand is read from the item manager) and two or more of them inside its cone
    (SHOTGUN_CONE) within SHOTGUN_R, one blast goes into the group first (it knocks them down together) and the run-out
    follows the moment the gun has fired (or BLAST_S later), at most once per BLAST_EVERY - the evades stay EVADE_S
    short, so the combo's kill cadence keeps up (the package freezes the combo window anyway);
  * when Leon dies the stats say why: "last_hit_by" is the threat that was landing when his routine went to 1 (the
    Tracker's hit record: kind, slot, em id / type, health, distance), "death_cause" repeats it on the death screen and
    the round map gets a death event - the next "why did he die" is traceable from round_maps/G4BE08/r<room>/;
  * blocked while running (moved < STUCK_MOVE in STUCK_S, up and down included: a ladder moves him up, not along):
    taps A ("JUMP OVER" / "CLIMB" prompts), then detours; still blocked after that, backs off for BACK_S and tries the
    other side (no teleports: a position write mid-climb crashed the game with "Invalid read" in its area-event code,
    2026-10-20);
  * a target that soaks 6 s of fire without the combo moving (on a roof, behind a wall) is skipped for 10 s;
  * the Mercenaries clock stops while a prompt is up ("Take the Handgun Ammo?", a time pillar): answer Yes (A);
  * between rounds (results, the Mercenaries title, character / stage select, the briefing) it presses A until the
    next round starts: GAME START, Leon, the first stage, go - the hack package stays in RAM, so every round is
    played the same way and no menu stays on screen.
v1 (2026-10-20, facing writes + teleports): 19 in a row, 24,500 points on the Village; the operator saw Leon stuck at a
fence and aiming with his arm behind him.

Memory comes from Dolphin's shared RAM view (/proc/<pid>/mem on Linux, a whole EmMgr table per read) when available,
else the adapter's read_memory/write_memory. Input goes through the adapter's send_input with gBox pad names.
"""
from __future__ import annotations

import heapq
import json
import math
import os
import struct
import time
from pathlib import Path

import numpy as np

try:
    from . import re4_ram_prompts                 # the game's own action-button state: prompts from RAM, vision after
except ImportError:                              # a tree without it: vision only
    re4_ram_prompts = None
from . import re4_threats as threats_ram         # who is attacking right now, what is thrown at him (RAM)
from .mercs import directives as operator_commands   # the chat's instant commands (fight, next area, explore ...)
from .mercs import stalemate as stalemate_rule   # no Ganados for 15 s with time on the clock: the clock is cut
try:
    from . import re4_menus                       # the title and the menus from RAM: boot -> a Mercenaries round
except ImportError:                              # a tree without it: no presses out of a round
    re4_menus = None

GAME_IDS = {"G4BE08"}
EMMGR, P_PLAYER, P_GLOBAL = 0x8027DF20, 0x802B9780 - 0x673C, 0x802B2280
G_ROOM, MERC_TIMER, MERC = 0x4FA8, 0x80279308, 0x8021392C
G_HP = 0x4FB0                                    # pG+0x4FB0 s16: Leon's health (0 on "You Are Dead")
ENGAGE = 3800.0                                  # Ganados this close are fought, else Leon goes for the time bonuses
TURN_TOL, FIRE_TOL = 0.35, 0.035                 # radians: turn with the stick until within TURN_TOL, aim-turn to FIRE_TOL
AIM_PITCH = 0x80218738                           # the aim's vertical blend, f32 -1 (down) .. +1 (up) with the default
                                                 # controls: the aim routine (0x8014415C) adds the stick's y to it every
                                                 # frame, clamps it, and the aim pose blends level -> full up / down by it
                                                 # (0x8013FA6C); a global (the aim struct 0x80218650 +0xE8), kept between
                                                 # aims. Read only. (Leon +0x258, read before: a motion value, not the aim
                                                 # - it never follows the stick; run1.rec 2026-10-20)
PITCH_SCALE = 1.0                                # radians at a full blend (assumed: the aim-up pose's angle)
AIM_YAW_OFF = 0x400                              # Leon +0x400 f32: the aim's horizontal offset from his facing while he
                                                 # aims (radians, + left like the facing): the stick moves it first,
                                                 # inside the weapon's cone (Hand Cannon +0.063 / -0.050), then turns him;
                                                 # 0 as the aim comes up (0x8092AD98; run1.rec 2026-10-20)
GAME_PAD = 0x80287E90                            # the game's pad as the aim routine reads it: stick x, y (s8) at +0, +1
HEAD_H, GUN_H, HOURGLASS_H = 1550.0, 1400.0, 900.0   # above the feet: a Ganado's head, Leon's gun, an hourglass
PITCH_MAX, PITCH_AFTER = 0.5, 0.25              # aim no further up / down (radians); read it once R is held this long
PITCH_TOL, PITCH_FINE, PITCH_LIMIT_S = 0.05, 0.15, 0.5   # fire within PITCH_TOL of the head; closer than PITCH_FINE the
                                                         # stick is pulsed; a push that moves nothing this long: the limit
SHOOT_RANGE = 2400.0                             # fire inside this
BONUS_FIGHT_R = 2400.0                           # bonuses left: only a Ganado in view this close is fought first
THREAT_R = 1600.0                                # a Ganado this close is about to strike: him first, before bonuses
PRESS_HOLD, PRESS_GAP = 0.04, 0.09               # the trigger: one 50 ms tick down, one up - ~10 presses a second, the loop's
                                                 # limit (operator 2026-10-26: "leon needs to fire about 20x faster"; the gun's
                                                 # own interval is already /20, so presses were the cap at 0.30/0.40 = 1.4 a second)
QUICK_TURN_ERR, QUICK_TURN_S = 2.3, 0.9          # a target this far round (radians): the quick turn (back + B), at
                                                 # most once in QUICK_TURN_S
TURN_RATE = 3.0                                  # radians a second, the stick turning him (not aiming): the start;
                                                 # Bot.turn_rate is what the turns he makes measure
URGENT_S = 2.5                                   # an attack landing within this is fought (or dodged) before anything
EVADE_S, EVADE_MARGIN = 0.8, 0.15                # run out of a swing this long; dodge when it lands this much sooner
                                                 # than he can shoot
CROWD_R, CROWD_N = 750.0, 2                      # this many Ganados this close: get out, then fight them one by one
AIM_SPEED_X = 1.0                                # the game's own aim speed (re_mods aim_turn_speed: the constant pi at
                                                 # 0x801ED930 the aim routine scales the stick by): ~30 deg/s. Was x3
                                                 # (~90 deg/s) until operator 2026-10-22: the camera spun "so spastically",
                                                 # the bot overshot and circled - back to regular
AIM_FINE = 0.12                                  # aiming, this close to the target (radians): the stick in pulses
AIM_KEEP_ERR = 0.8                               # aiming already: the gun stays up and aim-turns within this (radians)
EVADE_LOOK = 1500.0                              # a way out is clear this far ahead (the level map, other Ganados)
TURN_COST = 350.0                                # choosing among near ones: a radian to turn costs this many units
FACING_ERR = 0.6                                 # an attacker this close to his facing (radians) is shot, not run from
PROMPT_GUARD_S = 0.8                             # an action prompt (A) waits while an attack lands within this
RECOVER_S = 1.2                                  # just up from a hit, a Ganado within CROWD_R: out of reach first
                                                 # (operator: "getting slapped on by these people over and over")
CHAINSAW_KEEP = 2000.0                           # the chainsaw man is never allowed this close unanswered (operator
                                                 # 2026-10-26): inside it, not in front of Leon, the run-out; in front,
                                                 # or outside it, he is shot continuously (SHOOT_RANGE > CHAINSAW_KEEP)
CHAINSAW_PAD = 300.0                             # inside his reach + this his saw is about to land: out of its arc, unless
                                                 # he is in front (the quick turn away is slower than the shot)
CHAINSAW_REEVADE_S = 2.5                         # one run-out per this long: he runs as fast as Leon, so running never
                                                 # ends it - after the run-out he is turned to and shot (a hit staggers him)
SHOTGUNS = frozenset({0x2C, 0x2D, 0x94})         # Shotgun, Striker, Riot Gun (re_games.ITEMS): the crowd-control guns
MAGNUMS, HANDCANNON = frozenset({0x29, 0x2A, 0x2B}), 0x37   # Broken Butterfly, Killer7 (x2); the Hand Cannon
SHOTGUN_CONE, SHOTGUN_R = 0.3, 900.0             # a shotgun blast knocks down what is inside this half-angle (radians,
                                                 # ~17 degrees of the aim) and this close: two or more there = one blast
BLAST_S, BLAST_EVERY = 0.7, 2.0                  # the blast is one trigger press: the run-out follows when the gun has
                                                 # fired or this long has passed; at most one blast per BLAST_EVERY
ITEM_MGR = 0x802138E0                            # re_games.ITEM_MGR; +0x10 u16: the weapon in the player's hands (what
                                                 # re_mods_tool.equip_item reads back to verify an equip; 0 = none)
ELEV_DY = 600.0                                  # a target this far above / below: raise or lower the aim; else level
BODY_LO, CHEST_H, BODY_HI = 700.0, 1150.0, 1650.0   # a Ganado's body above his feet: a shot anywhere in it lands
HEAD_LO, HEAD_AIM_H = 1300.0, 1520.0             # operator 2026-10-22: "never shooting at the ground ... aiming at heads": a shot
                                                 # leaves only with the aim inside the head band (HEAD_LO .. BODY_HI above
                                                 # his feet, never below the gun), and the stick settles on HEAD_AIM_H
LOW_BODY = (0.0, 400.0, 200.0)                   # a hurt Ganado (knocked down, fallen; staggering: his legs): lo, hi, aim
                                                 # (was 0-700 / 300: shots 500-700 above the feet passed over one lying
                                                 # flat - operator 2026-10-26: "Leon shoots directly in front of him when
                                                 # the enemy is on the ground so he basically misses")
LOW_AIM_BACK_S = 1.0                             # a low target the aim cannot get down to for this long: step back
SMALL_BODY = (0.0, 450.0, 150.0)                 # a small animal (a chicken), health SMALL_HP or less: just off the ground
SMALL_HP = 20                                    # (operator 2026-10-24: Leon missed "people he knocked down, people who
                                                 # fell down, chickens" - every shot went at head height over them)
BODY_HALF_W = 180.0                              # ... and to either side of his middle
PITCH_RATE = 1.0                                 # radians a second the stick moves the aim pitch (learned as he plays;
                                                 # the routine ramps the stick over 7 frames: ~2.4 a second held)
AIM_R1, AIM_READY_R2 = 6, (1, 2)                 # Leon's routine 00 06 01 .. = aiming, 00 06 02 .. = firing: the pose
                                                 # is up (00 06 00 / 00 06 01 04 while it rises; live 2026-10-20)
STEEP_DOWN = -0.5                                # a shot this far down (radians) hits the ledge in front: move instead
HIGH_GROUND = 1500.0                             # Leon this far above the Ganados (the start roof): get down first
ITEM_R, TAKE_TRIES = 250.0, 2                      # an hourglass without an action zone is taken this close to it; tries per round
TAKE_R, VAULT_R = 450.0, 900.0                   # take an item hourglass this close to its stand point; vault from here
COMBO_CROWD, COMBO_NEAR = 5, 3500.0              # this many Ganados this close: take a combo bonus first (TAS route)
EM_HP = 0x320                                    # Ganado (EmMgr slot) +0x320 s16 health, +0x322 s16 max (found
                                                 # 2026-10-20: 1000 / 1800 at full, falls with hits, 0 at death)
MISSES_TO_ADJUST = 3                             # misses in a row at a raised / lowered target: the next aim height
BLOCKED_MISSES, BLOCKED_SKIP_S = 3, 5.0          # misses in a row at one Ganado: something is in the way, leave him
BLOCKED_R = 2500.0                               # ... when he is this close and on Leon's level (a level shot)
PITCH_STEPS = (0.0, -0.05, 0.05, -0.1, 0.1, -0.15, 0.15)   # aim-height offsets tried in turn after misses (radians)
CELL = 400.0                                     # the learned map's grid (world units)
RAY_FAN_N = 5                                    # lookahead rays cast ahead every tick (request #3299)
RAY_FAN_SPREAD = math.pi / 3                     # the fan's total spread (radians, 60 deg)
RAY_FAN_LEN = 2000.0                             # each ray's reach ahead (world units)
EXPLORE_R = 2400.0                               # "navigate more of the level": the distance of each exploring leg
WALLS_PER_SAVE, STUCK_LOG_MAX = 5, 200           # save the learned map after this many new walls; stuck events kept
DETOUR_S = 1.0                                   # a learned detour round a wall is planned again this often at most
STUCK_S, STUCK_MOVE = 0.9, 250.0                 # running but moved less than this in that long (any way): blocked
BACK_S = 0.6                                     # still blocked after a vault and a detour: back off this long
ORBIT_R, ORBIT_ERR = 2500.0, 0.6                 # a goal this near and this far off his heading is inside his turning
                                                 # circle (run ~4 m/s, turn ~2 rad/s): turn on the spot, don't orbit it
CIRCLE_TURN, CIRCLE_BOX, CIRCLE_S = 2 * math.pi, 3000.0, 8.0   # a whole turn inside this box in this long: circling
                                                 # (operator 2026-10-24: "Leon is running into a circle")
BONUS_MAX = 400.0                                # the clock jumps up to this much for one bonus (time pickups x3: 270 s)
ARRIVE = 650.0                                   # a waypoint this close is reached
# Ladders: never climbed (operator 2026-10-26: "Leon has climbed the clock tower and is unable to turn around and go back
# down the ladder. Make sure he is mapping this level so he knows not to climb the ladder"): routes avoid them, the CLIMB
# UP prompt is not pressed, a goal only a ladder reaches is left; up one anyway (the start, an old route), he walks back
# to its top and faces the way down - the prompt logic presses CLIMB DOWN. The disc's ladder links run foot -> top only,
# so the planner had no way back down and he ran into the tower's walls
LADDER_AVOID = 1e9                               # the planner's cost of a ladder: only when nothing else reaches a goal
LADDER_RISE, LADDER_TOP_DY, LADDER_TOP_R = 1000.0, 600.0, 3500.0   # a ladder this tall; Leon this near its top's height
LADDER_EDGE_R = 350.0                            # and within LADDER_TOP_R of it is up there; this near the top: the edge
COLLECT_R, COLLECT_TRY_S = 1500.0, 4.0           # shoot an hourglass from this close; give up on it after this long
# Village (r400) time bonuses: the room's four small AEV events (live RAM 2026-10-20), (x, z) in world units
HOURGLASS = {0x400: [(19401.0, -6857.0), (-20476.0, -5294.0), (-8452.0, -20283.0), (5592.0, 16384.0)]}
MENU_AFTER, MENU_EVERY = 2.0, 1.5                 # out of a stage this long: press A this often (next round)
TRANSIENT_MAX = 20.0                             # a gap in a live Mercenaries room (grabbed, a pickup) waits this long
PROMPT_EVERY, PROMPT_BURST, PROMPT_REST = 0.6, 3, 5.0   # press a prompt this often; still up after this many presses
                                                       # within 3 s (a TAKE he can't carry): leave it alone this long
MENU_KEYS = ("up", "a")                          # each menu step: up (GAME START, the top stage row), then confirm; no
                                                 # left: Select Player wraps from Leon to Wesker (live 2026-10-20)
PACKAGE = [("mercenaries_unlock", {"on": True}),
           ("merc_loadout", {"character": "leon", "items": ["handcannon", "handcannon ammo:200"], "on": True}),
           ("weapon_mod", {"item": "handcannon", "reset": True, "damage": "99.9"}),   # its own fire rate (see above)
           ("infinite_ammo", {"on": True}), ("unlimited_health", {"on": False}),   # Leon can die now (operator 2026-10-22)
           ("auto_first_aid", {"on": True}),     # ... but carries an infinite First Aid Spray (operator 2026-10-24): hp back
                                                 # to full under 35% once per 2.5 s, from play() every tick (first_aid)
           ("merc_time_bonus", {"multiplier": 3}), ("combo_time", {"multiplier": 3}),
           ("combo_freeze", {"on": True}), ("spawn_multiplier", {"count": 3, "on": True}),
           ("aim_turn_speed", {"multiplier": AIM_SPEED_X})]   # the game's aim sensitivity (a constant, not Leon)

# every round's own loadout (operator 2026-10-22: "autoplaying mercenary levels with random weapons"): a fresh random gun
# from the game's weapon table at each Select Player, with its firepower scaled so a weak pick still kills; the
# PACKAGE's fixed handcannon + weapon_mod are the fallback and are skipped when this runs
ROUND_OP = ("random_loadout", {"character": "all", "damage": "99.9", "fire_x": 20, "on": True,    # 20x fire rate, every character
                               "weapon": "handcannon", "weapon_chance": 0.5})   # the Hand Cannon half the time (operator
                                                   # 2026-10-24), else a random campaign gun (operator 2026-10-26), both x20
LOADOUT_OPS = ("merc_loadout", "weapon_mod")


def ptr_ok(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


class ShmMem:
    """Dolphin's 32 MiB MEM1 view in /dev/shm, read through /proc/<pid>/mem (Linux, same user): whole tables per read.
    Read-only. It takes the first Dolphin on this host running the game, so it is for standalone runs with no session;
    a session's playbook reads its own Dolphin (memory(ad))."""

    def __init__(self, game_id: bytes = b"G4BE08"):
        for pid in (p for p in os.listdir("/proc") if p.isdigit()):
            try:
                maps = open(f"/proc/{pid}/maps").read()
            except OSError:
                continue
            for line in maps.splitlines():
                if "/dev/shm/dolphin-emu" not in line:
                    continue
                a, b = (int(x, 16) for x in line.split()[0].split("-"))
                if b - a != 0x2000000:
                    continue
                try:
                    f = open(f"/proc/{pid}/mem", "rb", 0)
                    f.seek(a)
                    if f.read(6) == game_id:
                        self.f, self.base = f, a
                        return
                except OSError:
                    continue
        raise OSError("no Dolphin MEM1 view for this game")

    def rd(self, addr: int, n: int) -> bytes:
        self.f.seek(self.base + (addr & 0x1FFFFFF))
        return self.f.read(n)


class OwnShm:
    """The session's own Dolphin MEM1 (gbox.ram_dump.ShmRam: found only under the session's process, read-only), so two
    RE4 sessions on one host never read each other's game."""

    def __init__(self, ram):
        self.ram = ram

    def rd(self, addr: int, n: int) -> bytes:
        return self.ram.read(0x80000000 | (addr & 0x1FFFFFF), n)


class AdMem:
    def __init__(self, ad):
        self.ad = ad

    def rd(self, addr: int, n: int) -> bytes:
        return bytes(self.ad.read_memory(addr, n))

    def wr(self, addr: int, data: bytes) -> None:
        self.ad.write_memory(addr, data)


def memory(ad):
    """The session's RAM, read-only: its own Dolphin's shared view when it runs on this host, else the adapter's
    read_memory. Without a session (a standalone run), the one Dolphin on this host running the game."""
    if ad is None:
        return ShmMem()
    try:
        from .ram_dump import ShmRam
        ram = ShmRam.find(ad)
        if ram is not None:
            return OwnShm(ram)
    except Exception:                                  # noqa: BLE001 - the adapter's reads still work
        pass
    return AdMem(ad)


def u32(m, a):
    return struct.unpack(">I", m.rd(a, 4))[0]


def cut_clock(m, seconds: float) -> dict:
    """The stalemate rule's write: the Mercenaries clock (MERC_TIMER, frames at 30 a second) set to `seconds`, never
    under one second, through the bot's memory writer (m.wr: AdMem, a test's memory) or, behind a read-only view
    (OwnShm / ShmMem), the owning session adapter (m.adapter.write_memory, as mercs_bot binds it). Read back: verified
    when the clock is within a second of the target. Never raises; a failure is the reason in the result."""
    target = max(1.0, float(seconds))
    frames = int(round(target * 30))
    try:
        before = u32(m, MERC_TIMER) / 30.0
        wr = getattr(m, "wr", None)
        ad = getattr(m, "adapter", None)
        if wr is None and ad is not None and callable(getattr(ad, "write_memory", None)):
            wr = ad.write_memory
        if wr is None:
            return {"verified": False, "clock_before": round(before, 1), "clock_after": round(before, 1),
                    "reason": "read-only memory view and no session adapter: no clock writer"}
        wr(MERC_TIMER, struct.pack(">I", frames))
        after = u32(m, MERC_TIMER)
        return {"verified": frames - 30 <= after <= frames, "clock_before": round(before, 1),
                "clock_after": round(after / 30.0, 1), "target_s": target,
                **({} if frames - 30 <= after <= frames else {"reason": "MERC_TIMER readback does not match"})}
    except Exception as error:                        # noqa: BLE001 - a lost adapter must not stop the tick
        return {"verified": False, "reason": f"clock write unavailable: {type(error).__name__}: {str(error)[:120]}"}


def aim_of(m, pl: int, rot: float, r: tuple) -> tuple:
    """Where the gun points (the game's own aim): (aim facing, horizontal offset, pitch in radians or None). The
    offset counts only while he aims (00 06 ..; it keeps its last value after); a value out of its range is unknown."""
    off = 0.0
    if len(r) > 1 and r[0] == 0 and r[1] == AIM_R1:
        off = struct.unpack(">f", m.rd(pl + AIM_YAW_OFF, 4))[0]
        if not math.isfinite(off) or abs(off) > 0.5:
            off = 0.0
    n = struct.unpack(">f", m.rd(AIM_PITCH, 4))[0]
    pitch = n * PITCH_SCALE if math.isfinite(n) and abs(n) <= 1.0001 else None
    return wrap(rot + off), off, pitch


def snapshot(m) -> dict:
    """room, Merc clock (s), combo, Leon's health, Leon {ptr, pos, rot (his facing), aim_rot (where the gun points:
    facing + the aim's offset), aim_off, pitch (the aim's, radians), r (his routine bytes), stick (the game's pad x,
    y)}, weapon (the item id in his hands, ITEM_MGR +0x10), live Ganados [{slot, pos, hp, hp_max} +
    gbox.re4_threats.em_fields: r (routine bytes), id, type, motion events, frame, ...], the thrown weapons in the
    air [{slot, pos}]."""
    pg = u32(m, P_GLOBAL)
    room = struct.unpack(">H", m.rd(pg + G_ROOM, 2))[0] if ptr_ok(pg) else None
    hp = struct.unpack(">h", m.rd(pg + G_HP, 2))[0] if ptr_ok(pg) else None
    weapon = struct.unpack(">H", m.rd(ITEM_MGR + 0x10, 2))[0]
    pl = u32(m, P_PLAYER)
    player = None
    if ptr_ok(pl):
        rot = struct.unpack(">f", m.rd(pl + 0xA4, 4))[0]
        r = tuple(m.rd(pl + threats_ram.EM_ROUTINE, 4))
        aim_rot, aim_off, pitch = aim_of(m, pl, rot, r)
        player = {"ptr": pl, "pos": struct.unpack(">3f", m.rd(pl + 0x94, 12)), "rot": rot, "aim_rot": aim_rot,
                  "aim_off": aim_off, "pitch": pitch, "r": r, "stick": struct.unpack(">bb", m.rd(GAME_PAD, 2))}
    base, n, stride = u32(m, EMMGR), u32(m, EMMGR + 4), u32(m, EMMGR + 8)
    enemies, thrown = [], []
    # Spawn multipliers expand the native table beyond 128 (150 live slots on
    # r404). Validate the whole MEM1 span rather than hiding every enemy.
    if ptr_ok(base) and 0 < n <= 512 and 0x100 < stride < 0x2000 and base + n * stride <= 0x81800000:
        d = m.rd(base, n * stride)
        for k in range(1, n):
            o = k * stride
            if (not (struct.unpack_from(">I", d, o)[0] & 0x601) or d[o + 0x398] == 0xFF
                    or d[o + threats_ram.EM_ID] == threats_ram.THROWN_ID):
                continue
            enemy_hp, enemy_hp_max = struct.unpack_from(">hh", d, o + EM_HP)
            enemies.append({"slot": k, "pos": struct.unpack_from(">3f", d, o + 0x94), "hp": enemy_hp, "hp_max": enemy_hp_max,
                            **threats_ram.em_fields(d, o)})
        thrown = threats_ram.thrown(d, n, stride)
    return {"room": room, "hp": hp, "timer": round(u32(m, MERC_TIMER) / 30.0, 1), "combo": u32(m, MERC + 0x28),
            "player": player, "weapon": weapon, "enemies": enemies, "thrown": thrown}


def in_mercenaries(snap: dict) -> bool:
    return snap["room"] is not None and (snap["room"] >> 8) == 4 and snap["player"] is not None


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


BODY_BAND = (HEAD_LO, BODY_HI, HEAD_AIM_H)        # a standing Ganado: the head band (lo, hi, aim) above his feet


def body_band(tgt: dict) -> tuple:
    """Where shots land on this target, above its feet: a standing Ganado's head band; LOW_BODY for one that is hurt
    (knocked down, fallen - r_no_0 2; a staggering one is still hit in the legs); SMALL_BODY for a small animal."""
    if 0 < (tgt.get("hp_max") or 0) <= SMALL_HP:
        return SMALL_BODY
    r = tgt.get("r") or ()
    if r and r[0] == threats_ram.R_HURT:
        return LOW_BODY
    return BODY_BAND


def fire_tol(dist: float) -> float:
    """How far off his facing a Ganado at dist can be and still take the shot: his body's half width (live
    2026-10-20: the 2-degree tolerance kept Leon aiming, not firing, at a Ganado 4 degrees off at 2000)."""
    return max(FIRE_TOL, math.atan2(BODY_HALF_W, max(dist, 1.0)))


def weapon_name(iid: int | None) -> str:
    """'Shotgun (0x2c)' for the stats / round map; re_games names it (the RE4 item table), 'none' for 0."""
    if not iid:
        return "none"
    try:
        from . import re_games
        name = re_games.item_name(iid)
    except Exception:                                # noqa: BLE001 - a tree without the table
        name = f"item {iid:#x}"
    return f"{name} ({iid:#x})"


def shotgun(iid: int | None) -> bool:
    """A shotgun family gun in his hands: the crowd-control blast is on."""
    return iid in SHOTGUNS


def boss_tag(e: dict, dist: float) -> str:
    """'boss chainsaw 0x16 hp 6500/6500 dist 1840': the stats line for a boss target (the round map keeps it)."""
    eid = e.get("id")
    return (f"boss {e.get('boss') or 'boss'} {eid:#x} hp {e.get('hp')}/{e.get('hp_max')} dist {dist:.0f}"
            if isinstance(eid, int) else f"boss {e.get('boss') or 'boss'} hp {e.get('hp')}/{e.get('hp_max')} dist {dist:.0f}")


def hit_tag(h: dict | None) -> str:
    """The Tracker's hit record in words: 'swing slot 12 id 0x16 type 0x3 hp 1800/1800 at 640 (eta 0.0)' - with
    'boss chainsaw' in front when it was one ('boss chainsaw swing slot ..' mid-swing, 'boss chainsaw slot ..' when
    the saw itself was what the Tracker saw coming)."""
    if not h:
        return ""
    eid, et = h.get("id"), h.get("type")
    ids = (f" id {eid:#x}" if isinstance(eid, int) else "") + (f" type {et:#x}" if isinstance(et, int) else "")
    eta = f" (eta {h['eta']})" if h.get("eta") is not None else ""
    kind = h.get("kind")
    head = f"boss {h['boss']} " + (f"{kind} " if kind != h["boss"] else "") if h.get("boss") else f"{kind} "
    return f"{head}slot {h.get('slot')}{ids} hp {h.get('hp')}/{h.get('hp_max')} at {h.get('dist')}{eta}"


def _navmap():
    """gbox.re4_navmap (the level from the disc: walls, vault edges, hourglasses, paths) when it is installed."""
    try:
        from . import re4_navmap
        return re4_navmap
    except Exception:                                # noqa: BLE001 - straight lines and stuck handling without it
        return None


class LearnedMap:
    """What Leon has learned about one stage, round after round: cells he walked (floor) and cells he ran into (walls).
    path() plans on it with A*: walked cells are cheapest, unknown ones a little dearer, walls are avoided (a cell
    walked far more often than it blocked him is floor again: a Ganado was in the way, not a wall)."""

    def __init__(self, path: Path | None = None):
        self.path_file = path
        self.walked: dict[tuple, int] = {}
        self.blocked: dict[tuple, int] = {}
        if path is not None and path.is_file():
            try:
                d = json.loads(path.read_text())
                self.walked = {(i, j): n for i, j, n in d.get("walked", [])}
                self.blocked = {(i, j): n for i, j, n in d.get("blocked", [])}
            except (OSError, ValueError, TypeError):
                pass

    @staticmethod
    def cell(x: float, z: float) -> tuple:
        return int(math.floor(x / CELL)), int(math.floor(z / CELL))

    def walk(self, x: float, z: float) -> None:
        k = self.cell(x, z)
        self.walked[k] = min(self.walked.get(k, 0) + 1, 10000)

    def block(self, x: float, z: float) -> bool:
        return self.block_cell(self.cell(x, z))

    def block_cell(self, k: tuple) -> bool:
        """One more run into cell k; True when it is a new wall (never blocked before)."""
        new = k not in self.blocked
        self.blocked[k] = self.blocked.get(k, 0) + 1
        return new

    def wall(self, k: tuple) -> bool:
        b = self.blocked.get(k, 0)
        return b > 0 and b * 40 > self.walked.get(k, 0)

    @classmethod
    def cells_between(cls, a: tuple, b: tuple) -> list:
        """The cells a straight run from a to b ((x, z)) passes, sampled every half cell, a's own cell first."""
        n = max(1, int(math.ceil(math.hypot(b[0] - a[0], b[1] - a[1]) / (CELL * 0.5))))
        out = []
        for i in range(n + 1):
            k = cls.cell(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            if not out or out[-1] != k:
                out.append(k)
        return out

    def crosses(self, a: tuple, b: tuple) -> tuple | None:
        """The first learned wall a straight run from a to b would hit, else None. Neither end's own cell counts: he
        stands on a's, and b is where he wants to be (a stand point against a wall is in the wall's cell)."""
        if not self.blocked:
            return None
        for k in self.cells_between(a, b)[1:-1]:
            if self.wall(k):
                return k
        return None

    def path(self, start: tuple, goal: tuple) -> list:
        """[(x, z)] waypoints from start to goal round the learned walls; [goal] when nothing is known."""
        a, b = self.cell(*start), self.cell(*goal)
        if not self.blocked or a == b:
            return [goal]
        known = list(self.walked) + list(self.blocked) + [a, b]
        lo_i, hi_i = min(k[0] for k in known) - 6, max(k[0] for k in known) + 6
        lo_j, hi_j = min(k[1] for k in known) - 6, max(k[1] for k in known) + 6
        h = lambda k: math.hypot(k[0] - b[0], k[1] - b[1])        # noqa: E731
        best, came, todo = {a: 0.0}, {}, [(h(a), a)]
        while todo:
            _, k = heapq.heappop(todo)
            if k == b:
                break
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (k[0] + di, k[1] + dj)
                    if n == k or not (lo_i <= n[0] <= hi_i and lo_j <= n[1] <= hi_j) or (self.wall(n) and n != b):
                        continue
                    if di and dj and (self.wall((k[0] + di, k[1])) or self.wall((k[0], k[1] + dj))):
                        continue                                      # no squeezing past a wall corner
                    cost = best[k] + math.hypot(di, dj) * (1.0 if n in self.walked else 1.3)
                    if cost < best.get(n, float("inf")):
                        best[n], came[n] = cost, k
                        heapq.heappush(todo, (cost + h(n), n))
        if b not in came:
            return [goal]
        cells = [b]
        while cells[-1] != a:
            cells.append(came[cells[-1]])
        cells.reverse()
        way, last_dir = [], None                                      # keep only the corners
        for c0, c1 in zip(cells, cells[1:]):
            d = (c1[0] - c0[0], c1[1] - c0[1])
            if d != last_dir and c0 != a:
                way.append(((c0[0] + 0.5) * CELL, (c0[1] + 0.5) * CELL))
            last_dir = d
        return way + [goal]

    def save(self) -> None:
        if self.path_file is None:
            return
        try:
            self.path_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"cell": CELL, "walked": [[i, j, n] for (i, j), n in self.walked.items()],
                                       "blocked": [[i, j, n] for (i, j), n in self.blocked.items()]}))
            tmp.replace(self.path_file)
        except OSError:
            pass


class Bot:
    """One decision per tick; the caller sends what it returns ({'hold': keys} / {'tap': key}) and sleeps. Pad only:
    the stick turns Leon, R aims, A fires / vaults, B runs."""

    def __init__(self, m, clock=time.time, nav=None, learn_dir: Path | None = None, round_maps_dir: Path | None = None):
        self.m, self.clock = m, clock
        self.nav = nav if nav is not None else _navmap()
        self.learn_dir = learn_dir
        # every round's route map lands here (<dir>/r<room>/; round_maps_dir_for: gbox-data/mercs/round_maps/G4BE08 in
        # a deployment, RE5's layout) - with no learn_dir the maps were dropped before (2026-10-26)
        self.round_maps_dir = round_maps_dir if round_maps_dir is not None else round_maps_dir_for(None, learn_dir)
        self.learned: LearnedMap | None = None
        self.r_since = None                           # since when the bot has held R (the aim pose is up after a moment)
        self.miss_run, self.pitch_i = 0, 0
        self.pitch_up, self.pitch_key = "up", None    # the stick direction that raises the aim (learned); held last tick
        self.pitch_seen, self.pitch_wrong, self.pitch_push = None, 0, None
        self.st, self.items, self.combos, self.ordered = None, [], [], False
        self.hist: list = []
        self.last_timer, self.timer_since = None, clock()
        self.skip: dict[int, float] = {}
        self.aim = {"slot": None, "since": 0.0, "combo": 0}
        self.room = None
        self.bonus: list = []                         # time bonuses left this round [(x, z)]
        self.goal = None                              # {"pos", "since", "path"} the time bonus Leon is going for
        self.unstick = None                           # {"stage": "detour" | "back", "until", "dir"}
        self.turns, self.circles, self.turn_first = [], {}, False   # circle detection (heading history, per goal)
        self.detour_dir = 1
        self.stuck_n = 0
        self.commands = operator_commands.Reader()    # the operator's instant commands (stats directive*)
        self.explore = None                           # {"goal": (x, z), "at"}: where "navigate more of the level" is heading
        self.stuck_log: list = []                     # every stuck this run (the last STUCK_LOG_MAX): where, why, what he did
        self._stuck_pending: list = []                # ... not yet written to r<room>-stuck.jsonl (save())
        self._new_walls = 0                           # learned walls since the map was last saved
        self._detour = None                           # {"goal", "at", "way"}: a straight run's way round a learned wall
        self.dead = False                              # on the death screen (counted once per death)
        self.tracker = threats_ram.Tracker(m)         # who is attacking, what is thrown (RAM)
        self.shots = threats_ram.Shots()              # every shot scored by the Ganados' health
        self.trigger = {"down": False, "at": float("-inf")}   # A: pressed once per shot (the Hand Cannon is not auto)
        self.evade = None                             # {"slot", "since", "until", "turned"}: getting out of a swing
        self.leon_r0 = 0                              # his routine byte last tick (1: hit / held)
        self.target_slot = None
        self.qturn_at = float("-inf")
        self.recovered_at = float("-inf")              # when he last got up from a hit / a hold
        self.shot_ram, self._was_firing, self.target_thrown = False, False, False
        self.pitch_rate = PITCH_RATE
        self._last_enemies: list = []
        self._threats: list = []
        self.blast = None                             # {"since", "shots"}: a shotgun blast into a crowd under way
        self.blast_at = float("-inf")                 # when the last one was fired (BLAST_EVERY)
        self.boss_evaded_at = float("-inf")           # the last run-out from the chainsaw man (CHAINSAW_REEVADE_S)
        self._keepout = None                          # (slot, at): the chainsaw man inside CHAINSAW_KEEP, counted once
        self._death_logged = False                    # this death's cause is in the stats already
        self.stats = {"prompts": 0, "max_combo": 0, "vaults": 0, "detours": 0, "backoffs": 0, "time_bonus": 0,
                      "shots_s": 0.0, "learned_walls": 0, "replans": 0, "hits": 0, "misses": 0, "accuracy": 0.0,
                      "pitch_offset": 0.0, "shots": 0, "kills": 0, "hits_taken": 0, "evades": 0,
                      "attacks_seen": 0, "attacks_prevented": 0, "attacks_avoided": 0, "attacks_landed": 0,
                      "thrown_seen": 0, "thrown_shot": 0, "quick_turns": 0,
                      "stuck_events": 0, "stuck_reason": "", "wall_detours": 0,   # the obstruction database at work
                      "learned_map": None, "learned_floor_cells": 0,
                      "rays_cast": 0, "ray_hits": 0,
                      # the bosses (operator 2026-10-26): every one seen, the one targeted, the chainsaw's keep-out
                      # answers, the shotgun blasts into crowds, and what hit / killed Leon
                      "bosses": [], "bosses_seen": 0, "boss": "", "boss_shots": 0, "chainsaw_keepouts": 0,
                      "chainsaw_evades": 0, "crowd_blasts": 0, "weapon": "", "last_hit_by": "", "death_cause": ""}
        # the operator's stalemate rule (gbox.mercs.stalemate): settings in stats (stalemate_cut_enabled / _s) from the
        # launch's MercMode block (play() / mercs_bot.play put them there); the write is cut_clock on this memory
        self.stalemate = stalemate_rule.Rule(lambda: self.stats)     # play() / the engine rebind bot.stats

    def _stalemate_watch(self, s: dict, p: dict, now: float) -> None:
        """No living Ganado for STALEMATE_S while the clock shows more than STALEMATE_CLOCK_S: the clock is cut to the
        configured seconds once per round (stats["stalemate_cut"]: before / after; a 'stalemate_cut' event on the map)."""
        living = sum(1 for e in s.get("enemies") or () if not threats_ram.dying(e))
        target = self.stalemate.observe(now, living, s.get("timer"))
        if target is None:
            return
        result = cut_clock(self.m, target)
        self.stalemate.record(now, result, trace=getattr(self, "trace", None), pos=p["pos"])

    # -- the round's time bonuses --
    def _round(self, room):
        if room != self.room:
            self.save()                               # the last room's map and stuck log
            self.room = room
            self.stalemate.new_round()
            self.learned = LearnedMap(self.learn_dir / f"r{room:03x}.json" if self.learn_dir else None)
            self.stats["learned_walls"] = len(self.learned.blocked)
            self.stats["learned_floor_cells"] = len(self.learned.walked)
            self.stats["learned_map"] = str(self.learned.path_file) if self.learned.path_file else None
            self._detour = None
            self.st, self.items, self.combos = None, [], []
            if self.nav is not None:
                try:
                    st = self.nav.stage(f"r{room:03x}")
                    hg = [h for h in st["hourglasses"] if h.get("reachable")]
                    self.st = st
                    self.items = [h for h in hg if h.get("kind") == "time_bonus"]
                    self.combos = [h for h in hg if h.get("kind") == "combo_bonus"]
                except Exception:                     # noqa: BLE001 - no map for this stage: the old way
                    self.st = None
            self.ordered = False
            self.bonus = [] if self.st is not None else list(HOURGLASS.get(room, []))
            self.goal = None

    def _path(self, start, goal):
        """The way to goal: the disc's map, with every leg that crosses a learned wall taken round it (_round_walls);
        without the map, the learned map alone."""
        if self.st is not None:
            try:
                way = self.nav.path(self.st, start, goal, ladder_cost=LADDER_AVOID)
                if way:
                    return self._round_walls(start, [(w.x, w.z, w.action) if hasattr(w, "action") else tuple(w) for w in way])
            except Exception:                         # noqa: BLE001
                pass
        elif self.nav is not None and self.room is not None:
            try:
                way = self.nav.path(self.nav.stage(f"r{self.room:03x}"), start, goal)
                if way:
                    return self._round_walls(start, [tuple(w) for w in way])
            except Exception:                         # noqa: BLE001
                pass
        if self.learned is not None:
            return self.learned.path(start[0::2] if len(start) == 3 else start, goal[0::2] if len(goal) == 3 else goal)
        return [goal]

    def _round_walls(self, start, way: list) -> list:
        """The planned path with the learned walls honoured: a leg that crosses a cell Leon has run into (the disc's
        collision does not know every crate and cart; a round's worth of them is the obstruction database) gets the
        learned map's corners round it spliced in before its waypoint (which keeps its action: a vault, a ladder)."""
        if self.learned is None or not self.learned.blocked:
            return way
        a = (start[0], start[2]) if len(start) == 3 else tuple(start)
        out = []
        for w in way:
            b = (w[0], w[1])
            corners = self.learned.path(a, b)[:-1] if self.learned.crosses(a, b) is not None else []
            if corners:
                out += corners
                self.stats["wall_detours"] += 1
            out.append(w)
            a = b
        return out

    def _sight(self, p, target_xyz) -> bool:
        """A clear line from Leon's gun to target_xyz on the level map (True without a map)."""
        if self.st is None:
            return True
        try:
            gun = [p["pos"][0], p["pos"][1] + GUN_H, p["pos"][2]]
            return bool(self.nav.sight(self.st, gun, list(target_xyz)))
        except Exception:                             # noqa: BLE001
            return True

    # -- lookahead raycast fan (request #3299) --
    def _raycast_fan(self, p, now) -> None:
        """Cast a fan of lookahead rays ahead of Leon every tick and mark hits into the learned map.

        Uses the disc's collision walls via gbox.re4_collision.raycast (a Python reimplementation
        of the native BVH line-test documented in that module).  Each hit marks a wall cell into
        LearnedMap so the bot steers before contact, not after a stuck.  Stats report rays_cast
        and ray_hits per round.
        """
        if self.st is None or self.learned is None:
            return
        try:
            from . import re4_collision as rc
            walls = self.st.get("_walls")
            if walls is None:
                w = np.asarray(self.st["walls"], np.float64).reshape(-1, 7)
                self.st["_walls"] = w
                walls = w
            origin = [p["pos"][0], p["pos"][1] + GUN_H, p["pos"][2]]
            heading = p.get("aim_rot", p["rot"])
            hits = rc.fan(walls, origin, heading, n=RAY_FAN_N, spread=RAY_FAN_SPREAD,
                          length=RAY_FAN_LEN, height=0.0, see_through=True)
            self.stats["rays_cast"] += len(hits)
            for h in hits:
                if h.blocked and h.point is not None:
                    self.stats["ray_hits"] += 1
                    # Mark the hit cell as a wall in the learned map (obstruction database)
                    self.learned.block(h.point[0], h.point[2])
                    self._new_walls += 1
        except Exception:                             # noqa: BLE001
            pass

    def save(self):
        """Keep what this round taught (the caller calls it between rounds and at the end; _go every WALLS_PER_SAVE
        new walls): the learned map, and the stuck events appended to <learn_dir>/r<room>-stuck.jsonl, one JSON object
        a line (at, pos, rot, heading_deg, cell(s) learned, room, action, replanned), for the round's report."""
        if self.learned is not None:
            self.learned.save()
            self._new_walls = 0
        if not self._stuck_pending:
            return
        if self.learn_dir is None or self.room is None:
            self._stuck_pending = []
            return
        try:
            self.learn_dir.mkdir(parents=True, exist_ok=True)
            with open(self.learn_dir / f"r{self.room:03x}-stuck.jsonl", "a", encoding="utf-8") as f:
                f.writelines(json.dumps(e) + "\n" for e in self._stuck_pending)
            self._stuck_pending = []
        except OSError:
            pass

    # -- steering --
    def _turn(self, err: float, aiming: bool, tol: float | None = None) -> set:
        keys = {"r"} if aiming else set()
        tol = tol if tol is not None else (FIRE_TOL if aiming else TURN_TOL)
        if abs(err) <= tol:
            self.fine_pulse = False
            return keys
        if aiming and abs(err) < AIM_FINE:            # close: a tick on, a tick off (no overshoot at the faster aim)
            self.fine_pulse = not getattr(self, "fine_pulse", False)
            if not self.fine_pulse:
                return keys
        keys.add("left" if err > 0 else "right")
        return keys

    def _fight(self, p, tgt, now, s) -> dict:
        self.stats["phase"] = "fight"
        px, _, pz = p["pos"]
        tx, _, tz = tgt["pos"]
        err = wrap(heading(tx - px, tz - pz) - p.get("aim_rot", p["rot"]))   # from where the gun points
        if tgt["slot"] != self.aim["slot"] or s["combo"] != self.aim["combo"]:
            self.aim = {"slot": tgt["slot"], "since": now, "combo": s["combo"], "hp": tgt.get("hp")}
        elif tgt.get("hp") is not None and self.aim.get("hp") is not None and tgt["hp"] < self.aim["hp"]:
            self.aim["since"], self.aim["hp"] = now, tgt["hp"]      # his health is falling: the shots reach him (a boss
        elif now - self.aim["since"] > 6:                              # takes many) - soaked 6 s of fire with nothing
            self.skip[tgt["slot"]] = now + 10                          # moving: out of reach
            self.aim = {"slot": None, "since": now, "combo": s["combo"]}
            return {"hold": set()}
        dist = math.hypot(tx - px, tz - pz)
        tag = (boss_tag(tgt, dist) + " ") if tgt.get("boss") else ""
        if tag:
            self.stats["boss"] = tag.strip()
        band = body_band(tgt)
        if band is not BODY_BAND:
            self.stats["low_target_shots"] = self.stats.get("low_target_shots", 0) + (self.r_since is None)
        down = math.atan2(tgt["pos"][1] + HEAD_H - (p["pos"][1] + GUN_H), max(dist, 1.0))
        if band is not BODY_BAND and not tgt.get("thrown"):
            # one on the ground at Leon's feet is below the lowest aim: a step back brings him into it
            reach = (p["pos"][1] + GUN_H - (tgt["pos"][1] + band[1])) / math.tan(PITCH_MAX)
            if dist < reach and abs(err) < QUICK_TURN_ERR:
                self.stats["low_target_backsteps"] = self.stats.get("low_target_backsteps", 0) + 1
                self.r_since = None
                return {"hold": {"down"}}
        if not tgt.get("thrown"):                                      # (a weapon in the air: shoot it from here)
            if p["pos"][1] - tgt["pos"][1] > HIGH_GROUND or down < STEEP_DOWN:   # up on a roof: get down to them
                self.r_since = None
                return self._go(p, (tx, tz), now)
            if not self._sight(p, (tx, tgt["pos"][1] + max(band[2], 300.0), tz)):   # a wall between: navigate, never fire
                self.r_since = None
                return self._go(p, (tx, tz), now)
            if dist > SHOOT_RANGE:                                     # in view but too far: close in
                self.r_since = None
                return self._run_to(p, (tx, tgt["pos"][1], tz), now)
        aiming = self.r_since is not None                               # the gun is up (or coming up) already
        if abs(err) > (AIM_KEEP_ERR if aiming else TURN_TOL):          # (up: it stays up and aim-turns unless he is
            self.r_since = None                                         # far round - lowering it to turn and raising
            self.stats["combat"] = f"{tag}turning to slot {tgt['slot']} d {dist:.0f} yaw {math.degrees(err):+.0f} (gun down)"
            self.stats["fire_gate"] = "turning: hold"
            if abs(err) > QUICK_TURN_ERR and now - self.qturn_at > QUICK_TURN_S:   # it again cost 0.6 s and a swing
                self.qturn_at = now                                             # landed meanwhile, live 2026-10-21)
                self.stats["quick_turns"] += 1                                  # behind him: the quick turn (back + B)
                return {"hold": {"down", "b"}}
            return {"hold": self._turn(err, aiming=False)}               # turn round first (fast)
        self.r_since = now if self.r_since is None else self.r_since
        if tgt.get("thrown"):                                           # a weapon in the air: at its own height
            height, level = self._aim_height(p, tgt["pos"][1], dist, now)
        else:                                                           # a body: any pitch that lands on it
            height, level = self._aim_body(p, tgt["pos"][1], dist, now, band)
            if band is not BODY_BAND and not level and now - self.r_since > LOW_AIM_BACK_S:
                # one on the ground the aim cannot get down to from here (the game's own pitch limit is short of
                # PITCH_MAX): a step back brings him into it, never shots into the ground in front of him
                self.stats["low_target_backsteps"] = self.stats.get("low_target_backsteps", 0) + 1
                self.stats["combat"] = f"{tag}low target slot {tgt['slot']} d {dist:.0f}: stepping back to aim down at him"
                self.r_since = None
                return {"hold": {"down"}}
        deg = math.degrees(err)
        if abs(err) > fire_tol(dist) or not level:
            self.trigger["down"] = False
            self.stats["combat"] = f"{tag}aiming slot {tgt['slot']} d {dist:.0f} yaw {deg:+.1f} {'level' if level else 'pitch'}"
            self.stats["fire_gate"] = "off target: hold" if abs(err) > fire_tol(dist) else "aim height: hold"
            return {"hold": self._turn(err, aiming=True, tol=fire_tol(dist)) | height}   # aim, turn, raise onto him
        self.stats["shots_s"] = round(self.stats["shots_s"] + 0.05, 2)
        self.stats["combat"] = f"{tag}on slot {tgt['slot']} d {dist:.0f} yaw {deg:+.1f} FIRE"
        self.stats["fire_gate"] = "on him"
        was_down = self.trigger["down"]
        keys = self._pull(now, tgt)
        if tag and "a" in keys and not was_down:                         # a fresh trigger press at a boss
            self.stats["boss_shots"] += 1
        return {"hold": {"r"} | keys}                                    # on target: fire

    def _pull(self, now, tgt) -> set:
        """The trigger: pressed for a moment, then let go, every PRESS_GAP while on target (a press while the gun is
        busy is just ignored; held down, the Hand Cannon also repeats at its own rate - live 2026-10-20 - but a fresh
        press fires the moment it can). The shots themselves are counted from RAM (his routine going to 00 06 02,
        _shot_seen); without that, a press the gun could fire counts."""
        tr = self.trigger
        self.target_slot = tgt["slot"]
        self.target_thrown = bool(tgt.get("thrown"))
        if tr["down"]:
            if now - tr["at"] < PRESS_HOLD:
                return {"a"}
            tr["down"] = False
            return set()
        if now - tr["at"] < PRESS_GAP:
            return set()
        tr["down"], tr["at"] = True, now
        if not self.shot_ram and self.shots.press(now) and tgt.get("thrown"):
            self.stats["thrown_shot"] += 1
        return {"a"}

    def _shot_seen(self, p, now):
        """A shot as the game fires it: his routine entering 00 06 02 (the fire motion; live 2026-10-20)."""
        r = p.get("r")
        if not r or len(r) < 3:
            return
        if r[0] == 0 and r[1] == AIM_R1:
            self.shot_ram = True                            # this RAM shows the aim states: count shots from it
        firing = r[0] == 0 and r[1] == AIM_R1 and r[2] == 2
        if firing and not self._was_firing:
            self.shots.fired(now)
            if getattr(self, "target_thrown", False):
                self.stats["thrown_shot"] += 1
        self._was_firing = firing

    # -- combat: the threats first --
    def _ready_in(self, p, t, now) -> float:
        """Seconds until a shot at threat t can leave the gun: the turn (the quick turn for anything behind), the aim
        pose, bringing the aim pitch into his body (at the pitch rate the stick has shown), the gun's own rate."""
        px, py, pz = p["pos"]
        dist = math.hypot(t.pos[0] - px, t.pos[2] - pz)
        err = abs(wrap(heading(t.pos[0] - px, t.pos[2] - pz) - p.get("aim_rot", p["rot"])))
        tol = fire_tol(dist)
        turn = 0.0 if err <= tol else (0.55 if err > QUICK_TURN_ERR else err / getattr(self, "turn_rate", TURN_RATE))
        pose = 0.0 if self._pose_up(p, now) else PITCH_AFTER
        if not pose and self.r_since is not None and err <= TURN_TOL:
            pose = max(0.0, PITCH_AFTER - (now - self.r_since))
        pitch = 0.0
        cur = p.get("pitch")                                 # the game keeps it between aims: known before R
        if cur is not None and t.kind != "thrown":
            lo = math.atan2(t.pos[1] + HEAD_LO - (py + GUN_H), max(dist, 1.0))
            hi = math.atan2(t.pos[1] + BODY_HI - (py + GUN_H), max(dist, 1.0))
            off = max(lo - cur, cur - hi, 0.0)
            pitch = off / max(self.pitch_rate, 0.05)
        gun = max(0.0, self.shots.last_shot + self.shots.GUN_GAP - now)
        return max(turn + pose + pitch, gun) + 0.1

    @staticmethod
    def _facing(p, t, within: float = FACING_ERR) -> bool:
        """He is in front of Leon: the way out of his reach is behind (a quick turn), the shot is the faster answer."""
        px, _, pz = p["pos"]
        return abs(wrap(heading(t.pos[0] - px, t.pos[2] - pz) - p["rot"])) <= within

    def prompt_ok(self, button, s, now=None) -> bool:
        """Press the prompt the game shows now? Not an action button (a KICK, a TAKE: a second of Leon busy) while
        another Ganado's attack lands within PROMPT_GUARD_S (live 2026-10-20: a KICK mid-swing got Leon hit); a
        QTE (two buttons), a SHAKE OFF are always pressed."""
        if button not in ("a",):
            return True
        if self.stats.get("ram_action") == "CLIMB UP":             # a ladder: never climbed (LADDER_AVOID)
            self.stats["ladders_refused"] = self.stats.get("ladders_refused", 0) + 1
            return False
        if self.stats.get("ram_action") == "TAKE" and not (self.goal or {}).get("item"):
            # ammo / grenades a Ganado dropped: infinite ammo, never worth Leon's second (operator 2026-10-24: "dont
            # have the bot pick up ammo in any mode ... Just fight"); hourglasses are taken by _take's own goal
            self.stats["pickups_skipped"] = self.stats.get("pickups_skipped", 0) + 1
            return False
        for t in self._threats:                                    # as of the last tick
            if t.kind not in ("near", "down") and t.eta < PROMPT_GUARD_S and t.dist < 2500:
                self.stats["prompts_held"] = self.stats.get("prompts_held", 0) + 1
                return False
        return True

    @staticmethod
    def _as_target(t, lead_s: float = 0.0) -> dict:
        """A threat as _fight's target: a Ganado's slot and health, or a thrown weapon (negative slot), at the position
        it will have lead_s from now (on top of the tracker's own lead)."""
        e = dict(t.enemy) if t.kind != "thrown" else {"thrown": True}
        pos = tuple(t.pos[i] + t.vel[i] * lead_s for i in range(3))
        e.update(slot=t.slot if t.kind != "thrown" else -t.slot, pos=pos)
        if t.boss:
            e["boss"] = t.boss                                       # _fight names him in the stats (boss_tag)
        return e

    def _watch(self, p, s, threats, now):
        """Combat stats from RAM: hits taken (his routine going to 1: hit or held), attacks seen and how they ended:
        prevented (the attacker died in it), avoided (over without a hit), landed (Leon hit while it ran)."""
        r0 = (p.get("r") or (0,))[0]
        if r0 == 1 and self.leon_r0 != 1:
            self.stats["hits_taken"] += 1
            self.stats["last_hit_by"] = hit_tag(self.tracker.last_hit) or "unknown: no attack seen landing"
            if getattr(self, "trace", None) is not None:
                self.trace.event(now, "hit", p["pos"][0], p["pos"][2], by=self.stats["last_hit_by"][:120])
        if r0 != 1 and self.leon_r0 == 1:
            self.recovered_at = now                                 # on his feet again: out before the next one
        self.leon_r0 = r0
        for k in ("attacks_seen", "thrown_seen", "bosses_seen"):
            self.stats[k] = self.tracker.stats[k]
        for k in ("prevented", "avoided", "landed"):                # how each attack ended (re4_threats.Tracker)
            self.stats[f"attacks_{k}"] = self.tracker.stats.get(k, 0)
        if len(self.tracker.bosses) != getattr(self, "_bosses_n", 0):   # every boss seen, once per id / type / health
            self._bosses_n = len(self.tracker.bosses)                   # / room (the slots change; the table is the proof)
            seen, rows = set(), []
            for b in self.tracker.bosses.values():
                key = (b["id"], b["type"], b["hp_max"], b["room"])
                if key not in seen:
                    seen.add(key)
                    rows.append({"id": f"{b['id']:#x}" if isinstance(b["id"], int) else b["id"],
                                 "type": f"{b['type']:#x}" if isinstance(b["type"], int) else b["type"],
                                 "hp_max": b["hp_max"], "kind": b["kind"],
                                 "room": f"r{b['room']:03x}" if isinstance(b["room"], int) else b["room"]})
            self.stats["bosses"] = rows[:12]

    def _way_out(self, p, t) -> float:
        """The heading to run: away from the attacker, turned up to 60 degrees towards open ground - no wall in the
        next EVADE_LOOK (the level map's line of sight), no other Ganado near where it leads."""
        px, py, pz = p["pos"]
        away = heading(px - t.pos[0], pz - t.pos[2])
        others = [e["pos"] for e in self._last_enemies if e["slot"] != t.slot and not threats_ram.dying(e)]
        best, best_cost = away, float("inf")
        for turn in (0.0, 0.5, -0.5, 1.0, -1.0):
            h = away + turn
            ex, ez = px + math.sin(h) * EVADE_LOOK, pz + math.cos(h) * EVADE_LOOK
            cost = abs(turn) * 300.0
            if not self._sight(p, (ex, py + GUN_H, ez)):
                cost += 5000.0
            for ox, _, oz in others:
                d = math.hypot(ox - ex, oz - ez)
                if d < 1200.0:
                    cost += 1200.0 - d
            if cost < best_cost:
                best, best_cost = h, cost
        return best

    def _evade(self, p, t, now, side: bool = False) -> dict:
        self.stats["phase"] = "evade"
        tag = (boss_tag(dict(t.enemy, boss=t.boss), t.dist) + ": ") if t.boss else ""
        if tag:
            self.stats["boss"] = tag.rstrip(": ")
        self.stats["combat"] = f"{tag}evade {t.kind} {t.dist:.0f} away (eta {t.eta:.1f} s)"
        """Out of the way of an attack he can't stop in time: away from the attacker at a run (the quick turn first
        when the way out is behind him), for EVADE_S; side: across a thrown weapon's line (the side it passes on)."""
        px, _, pz = p["pos"]
        self.r_since = None
        self.trigger["down"] = False
        if self.evade is None or self.evade["slot"] != t.slot or now > self.evade["until"]:
            if side:
                vx, vz = t.vel[0], t.vel[2]
                cross = vx * (pz - t.pos[2]) - vz * (px - t.pos[0])     # which side of its line Leon is on
                away = heading(vz, -vx) if cross < 0 else heading(-vz, vx)
            else:
                away = self._way_out(p, t)
            self.evade = {"slot": t.slot, "since": now, "until": now + EVADE_S, "turned": False, "away": away,
                          "side": side}
            self.stats["evades"] += 1
        return self._run_out(p, now)

    def _run_out(self, p, now) -> dict:
        self.stats["phase"] = "run_out"
        """The evade under way: the quick turn when the way out is behind him (once), then a run along it."""
        err = wrap(self.evade["away"] - p["rot"])
        if abs(err) > QUICK_TURN_ERR and not self.evade["turned"] and now - self.qturn_at > QUICK_TURN_S:
            self.evade["turned"] = True
            self.qturn_at = now
            self.stats["quick_turns"] += 1
            return {"hold": {"down", "b"}}
        keys = {"up", "b"}
        if err > TURN_TOL / 2:
            keys.add("left")
        elif err < -TURN_TOL / 2:
            keys.add("right")
        return {"hold": keys}

    def _combat(self, p, s, now) -> dict | None:
        """The fight, threats first (operator 2026-10-20: "shoot any attacking enemy to prevent them from attacking
        him", "shoot it out the air", "walking out of their attacks"): a Ganado in an attack (gbox.re4_threats: his
        routine in the attack table, the hit frames by its motion) is shot - the one closest to landing first - or,
        when it lands before a shot can leave the gun, dodged; a thrown weapon coming at him is shot; two or more on
        top of him: get out first. None: no fight here (the route goes on)."""
        threats = self.tracker.update(s, now)
        self._threats = threats
        self._last_enemies = s["enemies"]
        self._shot_seen(p, now)
        self._watch(p, s, threats, now)
        self._score(s, now)
        if s.get("hp") is not None and s["hp"] <= 0:                 # dead: say what did it, once per death (after the
            if not self._death_logged:                               # tracker saw this tick: the killing blow puts his
                self._death_logged = True                            # routine at 1 and his health at 0 together)
                self._death(p, now)
        else:
            self._death_logged = False
        self.stats["boss"] = ""                                     # set again below when a boss is the target
        if self.stats.get("weapon") != weapon_name(s.get("weapon")):
            self.stats["weapon"] = weapon_name(s.get("weapon"))
        if (p.get("r") or (0,))[0] == 1:                             # hit or held: the game has him (play() presses
            self.r_since, self.trigger["down"] = None, False       # SHAKE OFF / the QTE from RAM)
            self.blast = None
            return {"hold": set()}
        if self.evade and now < self.evade["until"]:                # an evade under way: through, unless the attacker
            t = next((x for x in threats if x.slot == self.evade["slot"] and x.kind != "thrown"), None)   # is gone
            if self.evade["side"] or (t is not None and t.dist < threats_ram.REACH.get(t.kind, 900.0) + 500.0):
                self.r_since, self.trigger["down"] = None, False
                return self._run_out(p, now)
        live = [t for t in threats if self.skip.get(t.slot, float("-inf")) < now or t.kind not in ("near", "down")]
        urgent = [t for t in live if t.kind not in ("near", "down") and t.eta < URGENT_S]
        # a stage boss in sight is the target before any ordinary Ganado (operator 2026-10-26: "high level threats
        # that have to be dispatched") - unless an ordinary attack lands sooner than a shot at him can leave
        boss_t = self._boss_target(p, live)
        if boss_t is not None:
            ready = self._ready_in(p, boss_t, now)
            if not any(not u.boss and u.eta + EVADE_MARGIN < ready for u in urgent):
                return self._boss_act(p, s, boss_t, now)
        for t in urgent:
            if t.boss:                                             # the boss's own swing / hold / closing in: his rules
                if t.dist < ENGAGE and self._sight(p, (t.pos[0], t.pos[1] + HEAD_H, t.pos[2])):   # (out of view or
                    return self._boss_act(p, s, t, now)            # far: the next threat; the route finds him like
                continue                                           # any Ganado)
            ready = self._ready_in(p, t, now)
            late = t.eta + EVADE_MARGIN < ready
            if t.kind == "thrown" and late:                       # can't shoot it in time: out of its line
                return self._evade(p, t, now, side=True)
            if t.kind in threats_ram.MELEE and t.dist < threats_ram.REACH.get(t.kind, 900.0) + 300.0 and late \
                    and not self._facing(p, t):                    # it lands first: out of its way - but one in
                return self._evade(p, t, now)                      # front is still shot (running from him takes the
            lead = min(ready, t.eta) if t.kind == "thrown" else 0.0   # quick turn: slower than the shot; a hit
            return self._fight(p, self._as_target(t, lead), now, s)   # staggers him)
        close = [t for t in live if t.kind == "near" and t.dist < CROWD_R]
        if len(close) >= CROWD_N or (close and now - self.recovered_at < RECOVER_S):
            blast = self._crowd_blast(p, s, close, now)            # the shotgun into the group first (operator
            if blast is not None:                                   # 2026-10-26: "he carries a shotgun for crowd
                return blast                                        # control"), then out
            return self._evade(p, close[0], now)                    # on top of him / just hit: out, then one by one
        self.blast = None
        px, _, pz = p["pos"]

        def cost(t):                                           # near, and little to turn: a radian ~ TURN_COST units
            return t.dist + TURN_COST * abs(wrap(heading(t.pos[0] - px, t.pos[2] - pz) - p["rot"]))
        small = lambda t: 0 < (t.enemy.get("hp_max") or 0) <= SMALL_HP           # a chicken: after every Ganado
        near = sorted((t for t in live if t.kind == "near" and t.dist < THREAT_R), key=lambda t: (small(t), cost(t)))
        near += sorted((t for t in live if t.kind == "down" and t.dist < THREAT_R),   # knocked down: last - a downed
                       key=lambda t: (not t.boss, cost(t)))                            # boss before a downed Ganado
        if near:
            return self._fight(p, self._as_target(near[0]), now, s)
        return None

    def _boss_target(self, p, live):
        """The boss to fight now: the nearest one on his feet (kind chainsaw / boss, or in a known attack / hold) in
        view within ENGAGE; None when none is. A knocked-down boss waits his turn in the near list (he is hit low)."""
        px, _, pz = p["pos"]
        bosses = [t for t in live if t.boss and t.kind not in ("down", "thrown") and t.dist < ENGAGE
                  and self._sight(p, (t.pos[0], t.pos[1] + HEAD_H, t.pos[2]))]
        return min(bosses, key=lambda t: t.dist) if bosses else None

    def _boss_act(self, p, s, t, now) -> dict:
        """A boss as the target. The chainsaw man inside CHAINSAW_KEEP and not in front of Leon: the run-out first
        (his saw is one hit; the quick turn into him is slower than it), once per CHAINSAW_REEVADE_S - running from a
        chaser as fast as Leon never ends, so after it he is turned to (the quick turn) and shot. In front of Leon, or
        outside the keep-out, or any other boss (a Garrador, J.J.): shot continuously (_fight closes in past
        SHOOT_RANGE, fires with a line of sight)."""
        tag = boss_tag(dict(t.enemy, boss=t.boss), t.dist)
        self.stats["boss"] = tag
        if t.boss == "chainsaw" and t.dist < CHAINSAW_KEEP:
            if self._keepout is None or self._keepout[0] != t.slot or now - self._keepout[1] > 5.0:
                self.stats["chainsaw_keepouts"] += 1                # he came inside: counted once per approach
            self._keepout = (t.slot, now)
            late = t.eta + EVADE_MARGIN < self._ready_in(p, t, now)
            if not self._facing(p, t) and (late or t.dist < threats_ram.CHAINSAW_REACH + CHAINSAW_PAD) \
                    and now - self.boss_evaded_at > CHAINSAW_REEVADE_S:
                self.boss_evaded_at = now
                self.stats["chainsaw_evades"] += 1
                return self._evade(p, t, now)
        return self._fight(p, self._as_target(t), now, s)

    def _crowd_blast(self, p, s, close, now):
        """Shotgun crowd control: with a shotgun in his hands and CROWD_N of the close Ganados inside its cone
        (SHOTGUN_CONE of where the gun points) within SHOTGUN_R, aim at the nearest of them and fire once - the blast
        knocks the group down - then the caller's run-out. None: no blast (no shotgun, the group not in the cone, one
        fired within BLAST_EVERY, or this one is done: the gun fired / BLAST_S passed)."""
        if not shotgun(s.get("weapon")) or now - self.blast_at < BLAST_EVERY:
            return None
        b = self.blast
        if b is not None and (self.shots.stats["shots"] > b["shots"] or now - b["since"] > BLAST_S):
            self.blast, self.blast_at = None, now               # fired (or the moment passed): out now
            key = "crowd_blasts" if self.shots.stats["shots"] > b["shots"] else "crowd_blast_timeouts"
            self.stats[key] = self.stats.get(key, 0) + 1
            return None
        px, _, pz = p["pos"]
        aim = p.get("aim_rot", p["rot"])
        cone = [t for t in close if t.dist < SHOTGUN_R and abs(wrap(heading(t.pos[0] - px, t.pos[2] - pz) - aim)) < SHOTGUN_CONE]
        if len(cone) < CROWD_N:
            self.blast = None                                   # the group is not in the cone (any more): the run-out
            return None
        if b is None:
            self.blast = {"since": now, "shots": self.shots.stats["shots"]}
        tgt = self._as_target(min(cone, key=lambda t: t.dist))
        act = self._fight(p, tgt, now, s)
        self.stats["combat"] = f"shotgun blast at {len(cone)} in the cone: " + str(self.stats.get("combat"))
        return act

    def _score(self, s, now):
        """What the shots did (gbox.re4_threats.Shots: a shot hit when a Ganado's health fell or one started dying
        within HIT_S of it). MISSES_TO_ADJUST misses in a row at a raised / lowered target try the next aim-height
        offset (kept while it lands); a level shot at the chest keeps no offset. BLOCKED_MISSES misses in a row at one
        Ganado that is not attacking: something stands between (live 2026-10-21: a water tank the level map's line of
        sight let through took a clip) - he is left for BLOCKED_SKIP_S, the next one taken."""
        before = self.shots.stats["misses"], self.shots.stats["hits"]
        self.shots.update(s["enemies"], now)
        misses = self.shots.stats["misses"] - before[0]
        if self.shots.stats["hits"] > before[1]:
            self.miss_run = 0
            self.miss_by = {}
        self.miss_run += misses
        tgt = self.target_slot
        e = next((x for x in s["enemies"] if x["slot"] == tgt), None) if misses and tgt is not None and tgt >= 0 else None
        p = s.get("player")
        if e is not None and p and abs(e["pos"][1] - p["pos"][1]) < ELEV_DY \
                and math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2]) < BLOCKED_R:
            self.miss_by = getattr(self, "miss_by", {})      # (a level shot this close misses for a wall, not the aim)
            self.miss_by[tgt] = self.miss_by.get(tgt, 0) + misses
            if self.miss_by[tgt] >= BLOCKED_MISSES:
                self.skip[tgt] = now + BLOCKED_SKIP_S
                self.miss_by.pop(tgt)
                self.stats["blocked_skips"] = self.stats.get("blocked_skips", 0) + 1
        if self.miss_run >= MISSES_TO_ADJUST:
            self.pitch_i = (self.pitch_i + 1) % len(PITCH_STEPS)
            self.stats["pitch_offset"] = PITCH_STEPS[self.pitch_i]
            self.miss_run = 0
        for k in ("shots", "hits", "misses", "kills", "accuracy"):
            self.stats[k] = self.shots.stats[k]

    def _pose_up(self, p, now) -> bool:
        """The aim pose is up: his routine says so (00 06 01 .. aiming, 00 06 02 .. firing; live 2026-10-20), else
        PITCH_AFTER since R went down."""
        r = p.get("r")
        if r and len(r) >= 3 and r[0] == 0 and r[1] == AIM_R1:
            return r[2] in AIM_READY_R2
        return self.r_since is not None and now - self.r_since >= PITCH_AFTER

    def _aim_body(self, p, target_y: float, dist: float, now: float, band=None) -> tuple[set, bool]:
        """A Ganado's head: the aim must sit between HEAD_LO and BODY_HI above his feet to fire (never at the ground or
        his legs: a level aim at the gun's own height already is that band on flat ground); outside it the stick
        brings the aim to HEAD_AIM_H and holds it there, steady. band: (lo, hi, aim) above his feet for a target that is
        not standing head-high (body_band: on the ground, a chicken)."""
        band_lo, band_hi, band_aim = band or BODY_BAND
        cur = p.get("pitch")
        if cur is None or self.r_since is None or not self._pose_up(p, now):
            self.pitch_key, self.pitch_seen, self.pitch_push = None, None, None
            return set(), False
        gun = p["pos"][1] + GUN_H
        off = PITCH_STEPS[self.pitch_i]                      # learned from misses at raised / lowered targets
        lo = math.atan2(target_y + band_lo - gun, max(dist, 1.0)) + off
        hi = math.atan2(target_y + band_hi - gun, max(dist, 1.0)) + off
        margin = min(0.02, (hi - lo) * 0.2)
        if lo + margin <= cur <= hi - margin:
            self.pitch_key, self.pitch_seen, self.pitch_push = None, (now, cur, None), None
            return set(), True
        keys, level = self._aim_height(p, target_y + band_aim, dist, now)
        if level and band is not None and band is not BODY_BAND and not lo <= cur <= hi:
            return keys, False                        # at the game's pitch limit and still above him: no shot over him
        return keys, level

    def _aim_height(self, p, target_y: float, dist: float, now: float, offset: bool = True) -> tuple[set, bool]:
        """The stick key that moves the aim towards target_y while R is held, and whether the aim is there. Reads the
        game's own pitch (AIM_PITCH) and never writes it: the game keeps the pose and its limits. Which direction raises
        it is learned from what the last push did (two contradicting pushes in a row flip it). offset: add the aim
        height learned from misses (not for a level shot at the chest)."""
        cur = p.get("pitch")
        if cur is None or self.r_since is None or now - self.r_since < PITCH_AFTER:
            self.pitch_key, self.pitch_seen, self.pitch_push = None, None, None
            return set(), False                       # the aim pose is not up yet
        want = math.atan2(target_y - (p["pos"][1] + GUN_H), max(dist, 1.0)) + (PITCH_STEPS[self.pitch_i] if offset else 0.0)
        want = max(-PITCH_MAX, min(PITCH_MAX, want))
        seen = self.pitch_seen
        if seen is not None and seen[2] is not None and abs(cur - seen[1]) > 0.004:   # what the last push did
            dt = now - seen[0]
            if 0.02 < dt < 0.3 and abs(cur - seen[1]) < 1.0:   # how fast the stick moves the aim (the hack's x3 or not)
                self.pitch_rate = 0.8 * self.pitch_rate + 0.2 * abs(cur - seen[1]) / dt
            if (cur > seen[1]) == (seen[2] == self.pitch_up):
                self.pitch_wrong = 0
            else:
                self.pitch_wrong += 1
                if self.pitch_wrong >= 2:             # inverted aim: this stick direction lowers it
                    self.pitch_up, self.pitch_wrong = ("down" if self.pitch_up == "up" else "up"), 0
        err = want - cur
        if abs(err) <= PITCH_TOL:
            self.pitch_key, self.pitch_seen, self.pitch_push = None, (now, cur, None), None
            return set(), True
        key = self.pitch_up if err > 0 else ("down" if self.pitch_up == "up" else "up")
        if self.pitch_push is None or self.pitch_push[2] != key:
            self.pitch_push = (now, cur, key)
        elif now - self.pitch_push[0] > PITCH_LIMIT_S and abs(cur - self.pitch_push[1]) < 0.01:
            self.pitch_key, self.pitch_seen = None, (now, cur, None)
            return set(), True                        # pushing moves nothing: the game's limit, as close as it gets
        if abs(err) < PITCH_FINE and self.pitch_key is not None:
            key = None                                # close: pulse the stick (a tick on, a tick off), no overshoot
        self.pitch_key, self.pitch_seen = key, (now, cur, key)
        return ({key} if key else set()), False

    def _ladder_route(self, way) -> bool:
        """The planned way still climbs a ladder (nothing else reaches the goal): counted, and the caller leaves it."""
        if any(len(w) > 2 and w[2] == "ladder" for w in way or ()):
            self.stats["ladder_goals_left"] = self.stats.get("ladder_goals_left", 0) + 1
            return True
        return False

    def _ladder_descent(self, p, now):
        """Up where a ladder leads (the disc's ladder events: foot "pos", "top", "facing"): walk to its top, face the way
        down - towards the foot, or away from the climbing facing when the two are one above the other - and step to
        the edge; the CLIMB DOWN prompt it brings up is pressed by the prompt logic (prompt_ok). None: not up one."""
        events = (self.st or {}).get("events") if isinstance(self.st, dict) else None
        if not events:
            return None
        px, py, pz = p["pos"]
        for e in events:
            top, foot = e.get("top"), e.get("pos")
            if e.get("kind") != "ladder" or not top or not foot or top[1] - foot[1] < LADDER_RISE:
                continue
            d = math.hypot(px - top[0], pz - top[2])
            if abs(py - top[1]) > LADDER_TOP_DY or d > LADDER_TOP_R:
                continue
            self.stats["phase"] = "ladder_down"
            self.r_since = None
            if d > LADDER_EDGE_R:
                self.stats["combat"] = f"up a ladder: back to its top ({d:.0f} away)"
                return self._go(p, (top[0], top[2]), now)
            run = math.hypot(foot[0] - top[0], foot[2] - top[2])
            want = heading(foot[0] - top[0], foot[2] - top[2]) if run >= 150.0 else wrap((e.get("facing") or 0.0) + math.pi)
            err = wrap(want - p["rot"])
            if abs(err) > TURN_TOL:
                self.stats["combat"] = f"up a ladder: facing the way down ({math.degrees(err):+.0f} deg)"
                return {"hold": self._turn(err, aiming=False)}
            if not getattr(self, "ladder_edge", False):
                self.stats["ladder_descents"] = self.stats.get("ladder_descents", 0) + 1
            self.ladder_edge = True
            self.stats["combat"] = "up a ladder: at its top, CLIMB DOWN"
            return {"hold": {"up"}}
        self.ladder_edge = False
        return None

    def _take(self, p, h: dict, now, pool: list) -> dict:
        self.stats["phase"] = "take_bonus"
        """Run to an item hourglass's stand point on the map's path and take it with A."""
        px, py, pz = p["pos"]
        sx, sy, sz = h["stand"]
        if not self.goal or self.goal.get("item") is not h:
            self.goal = {"item": h, "pos": (sx, sz), "since": now, "path": self._path((px, py, pz), (sx, sy, sz))}
            if self._ladder_route(self.goal["path"]):                 # only up a ladder: left for this round
                pool.remove(h)
                self.goal = None
                return {"hold": set()}
        if math.hypot(sx - px, sz - pz) < TAKE_R:
            if now - self.goal.setdefault("take_since", now) > COLLECT_TRY_S:  # not taking it: retry once at the back, then leave it
                pool.remove(h)
                h["tries"] = h.get("tries", 0) + 1
                if h["tries"] < TAKE_TRIES:
                    pool.append(h)
                self.goal = None
                return {"hold": set()}
            ix, iz = h["pos"][0], h["pos"][2]
            d = math.hypot(ix - px, iz - pz)
            if d > 1.0:                                                   # A takes what he faces and stands against:
                err = wrap(heading(ix - px, iz - pz) - p["rot"])          # turn to the hourglass, close in on it, then A
                if abs(err) > TURN_TOL:
                    self.r_since = None
                    return {"hold": self._turn(err, aiming=False)}
                if d > ITEM_R and not h.get("zone"):
                    self.r_since = None
                    return {"hold": {"up"}}
            self.r_since = None
            return {"tap": "a"}                                           # TAKE
        return self._follow(p, now)

    def _run_to(self, p, target_xyz, now) -> dict:
        self.stats["phase"] = "run_to_target"
        """Close in on a Ganado round the walls (map path, refreshed as he moves) or straight without a map."""
        if self.st is None:
            return self._go(p, (target_xyz[0], target_xyz[2]), now)
        g = self.goal or {}
        if g.get("chase") is None or now - g.get("since", 0) > 1.5:
            self.goal = {"chase": True, "pos": (target_xyz[0], target_xyz[2]), "since": now,
                         "path": self._path(tuple(p["pos"]), tuple(target_xyz))}
        return self._follow(p, now)

    def _follow(self, p, now) -> dict:
        """Run the goal's path: drop waypoints as they are reached, A at a fence / window waypoint."""
        px, _, pz = p["pos"]
        way = self.goal["path"]
        while way:
            w = way[0]
            d = math.hypot(w[0] - px, w[1] - pz)
            if len(w) > 2 and w[2] == "vault" and d < VAULT_R:           # a fence / window: JUMP OVER it first
                way[0] = (w[0], w[1], "vaulted")
                self.stats["vaults"] += 1
                return {"tap": "a"}
            if len(way) > 1 and d < ARRIVE:
                way.pop(0)
                continue
            break
        w = way[0]
        self.r_since = None
        return self._go(p, (w[0], w[1]), now)

    def _go(self, p, goal_xz, now) -> dict:
        px, py, pz = p["pos"]
        if self.unstick and now < self.unstick["until"]:
            if self.unstick["stage"] == "detour":
                return {"hold": {"up", "b", "left" if self.unstick["dir"] > 0 else "right"}}
            if self.unstick["stage"] == "back":
                return {"hold": {"down"}}
        self.unstick = None
        self.hist = [h for h in self.hist if now - h[0] < STUCK_S + 0.3] + [(now, px, py, pz)]
        span = now - self.hist[0][0]
        moved = math.dist((px, py, pz), self.hist[0][1:])                # up a ladder counts: not blocked
        if span >= STUCK_S and moved < STUCK_MOVE:                       # running into something
            self.hist = []
            self.stuck_n += 1
            cells, replanned = [], None
            if self.learned is not None:                                 # learn the wall ahead of him (never his own
                cells = self._learn_wall(p)                              # cell); plan the goal's path round it, the
                self.stats["learned_walls"] = len(self.learned.blocked)  # disc's map or not (it does not know this wall)
                self._detour = None
                if self.goal and self.goal.get("pos"):
                    self.goal["path"] = self._path((px, py, pz), self.goal["pos"])
                    self.stats["replans"] += 1
                    replanned = len(self.goal["path"])
            if self.stuck_n == 1:
                self.stats["vaults"] += 1
                act, action = {"tap": "a"}, "vault"                       # a fence / window: JUMP OVER
            elif self.stuck_n % 3 == 0:                                   # a vault and a detour didn't do it: back
                self.unstick = {"stage": "back", "until": now + BACK_S}   # off, then the other side
                self.stats["backoffs"] += 1
                act, action = {"hold": {"down"}}, "back"
            else:
                self.detour_dir = -self.detour_dir
                self.unstick = {"stage": "detour", "until": now + 0.8, "dir": self.detour_dir}
                self.stats["detours"] += 1
                act, action = {"hold": {"up", "b", "left" if self.detour_dir > 0 else "right"}}, "detour"
            self._stuck_event(p, now, goal_xz, cells, action, replanned)
            if self.learned is not None and self._new_walls >= WALLS_PER_SAVE:   # a crash mid-round keeps what he learned
                self.save()
            return act
        if span >= STUCK_S and moved > 3 * STUCK_MOVE:
            self.stuck_n = 0                                              # running freely again
        if self.learned is not None:
            self.learned.walk(px, pz)
            self.stats["learned_floor_cells"] = len(self.learned.walked)
            goal_xz = self._around(p, goal_xz, now)                       # a learned wall on the straight line: round it
        final = getattr(self, "_detour", None) is None                   # the goal itself, not a corner on the way
        gx, gz = goal_xz
        err = wrap(heading(gx - px, gz - pz) - p["rot"])
        if self._circling(p, (gx, gz), now):
            if self.goal is None:                                        # twice round the same goal: it is dropped
                return {"hold": set()}
        keys = {"up", "b"}
        if err > TURN_TOL / 2:
            keys.add("left")
        elif err < -TURN_TOL / 2:
            keys.add("right")
        # inside his turning circle (radius ORBIT_R / 2): running while turning can never reach it, only orbit it
        inside = final and abs(err) > ORBIT_ERR and math.hypot(gx - px, gz - pz) < ORBIT_R * math.sin(min(abs(err), 1.57))
        if self.turn_first and abs(err) < TURN_TOL:
            self.turn_first = False
        if abs(err) > 1.6 or self.turn_first or inside:                  # behind him, circling, or inside his
            keys -= {"up", "b"}                                                     # turning circle: turn on the spot
        return {"hold": keys}

    def _circling(self, p, goal_xz, now) -> bool:
        """A whole turn (CIRCLE_TURN of heading change) inside CIRCLE_BOX within CIRCLE_S: he is running in a circle.
        The first time he turns on the spot towards the goal; the second time round the same goal it is dropped (the
        next hourglass / target), so the round goes on instead of orbiting."""
        px, _, pz = p["pos"]
        self.turns = [t for t in self.turns if now - t[0] < CIRCLE_S] + [(now, p["rot"], px, pz)]
        if len(self.turns) < 3:
            return False
        turned = sum(abs(wrap(b[1] - a[1])) for a, b in zip(self.turns, self.turns[1:]))
        xs, zs = [t[2] for t in self.turns], [t[3] for t in self.turns]
        if turned < CIRCLE_TURN or max(max(xs) - min(xs), max(zs) - min(zs)) > CIRCLE_BOX:
            return False
        self.turns = []
        key = (round(goal_xz[0], -2), round(goal_xz[1], -2))
        self.circles[key] = self.circles.get(key, 0) + 1
        self.stats["circles_broken"] = self.stats.get("circles_broken", 0) + 1
        if self.circles[key] >= 2:
            for pool_ in (self.items, self.bonus):
                if len(pool_) > 1:
                    pool_.append(pool_.pop(0))
            self.goal, self.circles[key] = None, 0
            self.stats["circle_goals_dropped"] = self.stats.get("circle_goals_dropped", 0) + 1
        else:
            self.turn_first = True
        return True

    def _operator(self, p, s, near, dist, now):
        """The operator's instant commands (gbox.mercs.directives; the chat's dropdown or typed words). One-shots change the
        plan on the tick they arrive; standing modes steer until they expire. None: no command applies, play as usual."""
        cmd, fresh = self.commands.current(self.stats, time.time())
        if cmd is None:
            if self.explore and now - self.explore["at"] > 20:
                self.explore = None
            return None
        self.stats["directive_active"] = cmd
        if fresh:
            self.stats["directive_status"] = "acting: " + cmd
        if cmd in ("mine", "mine_trail"):
            self.stats["directive_status"] = "RE4 Mercenaries has no mines to drop"
            return None
        if cmd == "missing":
            if fresh:                                                      # the next aim-height offset, misses forgotten
                self.pitch_i = (self.pitch_i + 1) % len(PITCH_STEPS)
                self.stats["pitch_offset"] = PITCH_STEPS[self.pitch_i]
                self.miss_by = {}
                self.stats["directive_status"] = f"aim height offset now {PITCH_STEPS[self.pitch_i]:+.2f} rad"
            return None
        if cmd == "next_area":
            if fresh:                                                      # drop this goal for the next one
                for pool_ in (self.items, self.bonus):
                    if len(pool_) > 1:
                        pool_.append(pool_.pop(0))
                self.goal, self.ordered = None, True
                self.stats["directive_status"] = "skipped to the next time bonus"
            return None
        if cmd == "repetitive":
            if fresh:                                                      # forget this target and route, back off, move on
                if near:
                    self.skip[near["slot"]] = now + 10.0
                for pool_ in (self.items, self.bonus):
                    if len(pool_) > 1:
                        pool_.append(pool_.pop(0))
                self.goal, self.hist, self.stuck_n = None, [], 0
                self.unstick = {"stage": "back", "until": now + BACK_S}
                self.explore = None
                self.stats["directive_status"] = "dropped the repeated action: backing off, then forward"
            if self.unstick and now < self.unstick["until"]:
                return {"hold": {"down"}}
            return self._explore(p, now, force=fresh)
        if cmd == "explore":
            if near and dist < ENGAGE and self._sight(p, (near["pos"][0], near["pos"][1] + HEAD_H, near["pos"][2])):
                return self._fight(p, near, now, s)
            return self._explore(p, now, force=fresh)
        # fight / hunt / score: the Ganados first, ahead of time bonuses and the route
        if near is None:
            self.stats["directive_status"] = "no enemy seen yet: exploring to find them"
            return self._explore(p, now, force=fresh)
        if dist < ENGAGE and self._sight(p, (near["pos"][0], near["pos"][1] + HEAD_H, near["pos"][2])):
            self.stats["directive_status"] = f"fighting at {dist:.0f}"
            return self._fight(p, near, now, s)
        self.stats["directive_status"] = f"going after the nearest enemy ({dist:.0f} away)"
        self.r_since = None
        return self._go(p, (near["pos"][0], near["pos"][2]), now)

    def _explore(self, p, now, force=False) -> dict:
        self.stats["phase"] = "explore"
        """Head for ground Leon has not walked: the open heading (of 16) whose ray ahead crosses the fewest walked cells and
        no learned wall, EXPLORE_R away; picked again on arrival or every few seconds."""
        px, _, pz = p["pos"]
        e = self.explore
        if force or e is None or now - e["at"] > 4.0 or math.hypot(e["goal"][0] - px, e["goal"][1] - pz) < ARRIVE:
            learned, best = self.learned, None
            for k in range(16):
                ang = 2 * math.pi * k / 16
                gx, gz = px + math.sin(ang) * EXPLORE_R, pz + math.cos(ang) * EXPLORE_R
                if learned is not None and learned.crosses((px, pz), (gx, gz)) is not None:
                    continue
                known = sum(1 for c in (learned.cells_between((px, pz), (gx, gz)) if learned else []) if c in learned.walked)
                score = known * 3 + abs(wrap(ang - p["rot"])) * 2 + (k * 0.6180339887 % 1.0) * 0.5   # stable tie-break
                if best is None or score < best[0]:
                    best = (score, (gx, gz))
            if best is None:                                               # boxed in by learned walls: back out
                self.stats["directive_status"] = "boxed in by learned walls: backing out"
                return {"hold": {"down"}}
            e = self.explore = {"goal": best[1], "at": now}
        self.r_since = None
        return self._go(p, e["goal"], now)

    def _learn_wall(self, p) -> list:
        """The wall he ran into, into the learned map: the cell half a cell ahead of him and the cell directly in front
        of his own (his heading snapped to the eight neighbours) - never his own cell: he stands on it, so it is floor
        (the old mark 0.8 cell ahead landed in his own cell when he stood at its near edge, and the wall was never
        learned). The cells marked; counts the new walls towards the next save."""
        px, _, pz = p["pos"]
        here = self.learned.cell(px, pz)
        sx, cz = math.sin(p["rot"]), math.cos(p["rot"])
        snap = lambda c: 1 if c > 0.3827 else -1 if c < -0.3827 else 0       # noqa: E731 - sin(22.5 deg): 8 ways
        ahead = self.learned.cell(px + sx * CELL * 0.5, pz + cz * CELL * 0.5)
        front = (here[0] + snap(sx), here[1] + snap(cz))
        marked = []
        for k in (ahead, front):
            if k != here and k not in marked:
                if self.learned.block_cell(k):
                    self._new_walls += 1
                marked.append(k)
        return marked

    def _death(self, p, now) -> None:
        """Leon's health hit 0: the cause for the round's report (operator 2026-10-26, "i just watched leon just eat
        a chainsaw"): the last threat that landed on him (stats last_hit_by), the bosses on the field, into the stats
        and the round map's events."""
        cause = self.stats.get("last_hit_by") or "unknown: no attack was seen landing"
        bosses = [t for t in self._threats if t.boss and not threats_ram.dying(t.enemy)]
        field = (f"; {len(bosses)} boss(es) on the field, nearest {boss_tag(dict(bosses[0].enemy, boss=bosses[0].boss), bosses[0].dist)}"
                 if bosses else "")
        self.stats["death_cause"] = f"killed by {cause}{field}; hits taken this run {self.stats.get('hits_taken', 0)}"
        if cause.startswith("boss"):
            self.stats["deaths_by_boss"] = self.stats.get("deaths_by_boss", 0) + 1
        if getattr(self, "trace", None) is not None:
            self.trace.event(now, "death", p["pos"][0], p["pos"][2], cause=self.stats["death_cause"][:200])

    def trace_start(self, round_id: str) -> None:
        """This round's route map (gbox.mercs.round_map) under round_maps_dir/r<room>/: finishes the last one first."""
        from .mercs.round_map import RoundTrace
        self.trace_finish()
        self.stalemate.new_round()                    # a new round: its own stalemate watch (one cut per round)
        room = f"r{self.room:03x}" if self.room is not None else "room"
        out = Path(self.round_maps_dir) / room if self.round_maps_dir is not None else None
        self.trace = RoundTrace(out, "G4BE08", room, round_id, CELL)

    def trace_finish(self) -> None:
        trace, self.trace = getattr(self, "trace", None), None
        if trace is None:
            return
        if trace.room == "room" and self.room is not None:          # the stage was read after the round began
            trace.room = f"r{self.room:03x}"
            if trace.out_dir is not None:
                trace.out_dir = trace.out_dir.parent / trace.room
        lm = self.learned
        summary = trace.finish(lm.walked if lm else (), lm.blocked if lm else ())
        if summary:
            self.stats["last_round_map"] = (summary.get("files") or [None])[-1]
            self.stats["last_round_verdict"] = summary.get("verdict")

    def _stuck_event(self, p, now, goal_xz, cells: list, action: str, replanned) -> None:
        """Why he stopped, in words for the watch panel (stats stuck_reason) and as a record (stuck_log, the last
        STUCK_LOG_MAX; save() appends them to r<room>-stuck.jsonl): where he stood, his heading, the cell(s) learned as
        wall, what he did about it (vault / detour / back) and how many waypoints the re-planned path has."""
        px, py, pz = p["pos"]
        deg = round(math.degrees(p["rot"])) % 360
        room = f"r{self.room:03x}" if self.room is not None else "?"
        ev = {"at": round(now, 2), "pos": [round(px), round(py), round(pz)], "rot": round(p["rot"], 3),
              "heading_deg": deg, "cell": list(cells[0]) if cells else None, "cells": [list(k) for k in cells],
              "room": room, "goal": [round(g) for g in goal_xz], "action": action, "replanned": replanned,
              "stuck_n": self.stuck_n}
        self.stuck_log.append(ev)
        del self.stuck_log[:-STUCK_LOG_MAX]
        if getattr(self, "trace", None) is not None:
            self.trace.event(now, "stuck", px, pz, action=action)
        self._stuck_pending.append(ev)
        self.stats["stuck_events"] += 1
        what = f"wall learned at cell {cells[0]}" if cells else "blocked, no learned map"
        plan = f", replanned {replanned} waypoints" if replanned is not None else ""
        self.stats["stuck_reason"] = f"{what} room {room} heading {deg}°: {action}{plan}"

    def _around(self, p, goal_xz, now):
        """Where to run for goal_xz: goal_xz itself when the straight line crosses no learned wall, else the first
        corner of the learned map's way round (planned again when he reaches it, the goal moves a cell, or after
        DETOUR_S) - so a straight run (at a Ganado, the next waypoint) honours the walls too."""
        px, _, pz = p["pos"]
        if self.learned.crosses((px, pz), goal_xz) is None:
            self._detour = None
            return goal_xz
        d = self._detour
        if d is None or math.dist(d["goal"], goal_xz) > CELL or now - d["at"] > DETOUR_S \
                or math.hypot(d["way"][0][0] - px, d["way"][0][1] - pz) < CELL * 0.5:
            if d is None:
                self.stats["wall_detours"] += 1
            d = self._detour = {"goal": goal_xz, "at": now, "way": self.learned.path((px, pz), goal_xz)}
        return d["way"][0]

    def _learn_turn(self, p, now):
        """How fast the stick turns him (radians a second, not aiming), from what the last tick's turn did: the pad's
        stick is not always full (gBox's keys give 72 of 127 - live 2026-10-21), so the rate is measured, not assumed."""
        last = getattr(self, "_turn_obs", None)
        if last is not None and p is not None:
            t0, rot0, key = last
            dt = now - t0
            if key and 0.02 < dt < 0.25:
                rate = abs(wrap(p["rot"] - rot0)) / dt
                if 0.2 < rate < 12.0:
                    self.turn_rate = 0.85 * self.turn_rate + 0.15 * rate
                    self.stats["turn_rate"] = round(self.turn_rate, 2)

    def tick(self, s: dict) -> dict:
        p = s["player"]
        now = self.clock()
        if not hasattr(self, "turn_rate"):
            self.turn_rate = TURN_RATE
        self._learn_turn(p, now)
        act = self._tick(s)
        keys = act.get("hold", set()) if isinstance(act, dict) else set()
        turning = (keys & {"left", "right"}) and not (keys & {"r", "up", "down", "b"}) and len(keys & {"left", "right"}) == 1
        self._turn_obs = (now, p["rot"], bool(turning)) if p else None
        return act

    def _tick(self, s: dict) -> dict:
        now, p = self.clock(), s["player"]
        self.stats["max_combo"] = max(self.stats["max_combo"], s["combo"])
        if not p:
            return {"hold": set()}
        self._round(s["room"])
        self._raycast_fan(p, now)
        if s["timer"] != self.last_timer:
            if self.last_timer is not None and self.last_timer > 1 and 5 < s["timer"] - self.last_timer < BONUS_MAX and self.bonus:   # a time bonus (not the next round's clock)
                px, _, pz = p["pos"]
                got = min(self.bonus, key=lambda b: (b[0] - px) ** 2 + (b[1] - pz) ** 2)
                self.bonus.remove(got)
                self.stats["time_bonus"] += 1
                self.goal = None
            elif self.last_timer is not None and self.last_timer > 1 and 5 < s["timer"] - self.last_timer < BONUS_MAX \
                    and (self.items or self.combos):
                px, _, pz = p["pos"]
                pool = self.items + self.combos
                got = min(pool, key=lambda h: (h["stand"][0] - px) ** 2 + (h["stand"][2] - pz) ** 2)
                (self.items if got in self.items else self.combos).remove(got)
                self.stats["time_bonus"] += 1
                self.goal = None
            self.last_timer, self.timer_since = s["timer"], now
            self.dead = False
        elif now - self.timer_since > 1.2 and s["timer"] > 0:           # the clock stopped: a prompt is up
            self.stats["prompts"] += 1
            if s.get("hp") is not None and s["hp"] <= 0:                 # "You Are Dead - Continue Yes / No": Yes
                if not self.dead:
                    self.dead = True
                    self.stats["deaths"] = self.stats.get("deaths", 0) + 1
                return {"tap": "a"}
            return {"tap": "b" if now - self.timer_since > 6 else "a"}
        self._stalemate_watch(s, p, now)                                  # no Ganados for a while: the clock is cut
        px, _, pz = p["pos"]
        act = self._combat(p, s, now)                                     # attacks, thrown weapons, a Ganado on him:
        if act is not None:                                               # before any bonus or route
            return act
        act = self._ladder_descent(p, now)                                # up a ladder (the clock tower): down it first
        if act is not None:
            return act
        pool = [e for e in s["enemies"] if self.skip.get(e["slot"], float("-inf")) < now and not threats_ram.dying(e)]
        near = min(pool, key=lambda e: (e["pos"][0] - px) ** 2 + (e["pos"][2] - pz) ** 2) if pool else None
        dist = math.hypot(near["pos"][0] - px, near["pos"][2] - pz) if near else None
        order = self._operator(p, s, near, dist, now)                     # the operator's instant command, if any
        if order is not None:
            return order
        crowd = sum(1 for e in pool if math.hypot(e["pos"][0] - px, e["pos"][2] - pz) < COMBO_NEAR)
        if self.st is not None and self.combos and crowd >= COMBO_CROWD:     # a combo window while they crowd in
            c = min(self.combos, key=lambda h: math.hypot(h["stand"][0] - px, h["stand"][2] - pz))
            if math.hypot(c["stand"][0] - px, c["stand"][2] - pz) < 2 * COMBO_NEAR:
                return self._take(p, c, now, self.combos)
        pending = bool(self.items or self.bonus)                          # time bonuses still on the field
        seen = bool(near) and self._sight(p, (near["pos"][0], near["pos"][1] + HEAD_H, near["pos"][2]))
        if near and dist < ENGAGE and (seen if not pending else seen and dist < BONUS_FIGHT_R):
            return self._fight(p, near, now, s)                           # in view (and, with bonuses left, close)
        if self.st is not None:
            if self.items and not self.ordered:                            # the round's route: best order from here
                try:
                    order = self.nav.tour(self.st, tuple(p["pos"]), targets=self.items)
                    self.items = [self.items[i] for i in order]
                except Exception:                     # noqa: BLE001
                    pass
                self.ordered = True
            if self.items:
                return self._take(p, self.items[0], now, self.items)
        if self.bonus:                                                    # the time bonuses, nearest first
            if not self.goal or self.goal["pos"] not in self.bonus:
                pos = min(self.bonus, key=lambda b: (b[0] - px) ** 2 + (b[1] - pz) ** 2)
                self.goal = {"pos": pos, "since": now, "path": self._path((px, pz), pos)}
                if self._ladder_route(self.goal["path"]):             # only up a ladder: left for this round
                    self.bonus.remove(pos)
                    self.goal = None
                    return {"hold": set()}
            gx, gz = self.goal["pos"]
            d = math.hypot(gx - px, gz - pz)
            if d < COLLECT_R:                                             # break it: aim at it and fire
                if now - self.goal.setdefault("shoot_since", now) > COLLECT_TRY_S:
                    self.bonus.remove(self.goal["pos"])                  # not breaking: leave it for this round
                    self.goal = None
                    return {"hold": set()}
                err = wrap(heading(gx - px, gz - pz) - p["rot"])
                if abs(err) > TURN_TOL:
                    self.r_since = None
                    return {"hold": self._turn(err, aiming=False)}
                self.r_since = now if self.r_since is None else self.r_since
                height, _ = self._aim_height(p, p["pos"][1] + HOURGLASS_H, d, now)
                return {"hold": {"r", "a"} | (self._turn(err, aiming=True) - {"r"}) | height}
            way = self.goal["path"]
            while len(way) > 1 and math.hypot(way[0][0] - px, way[0][1] - pz) < ARRIVE:
                way.pop(0)
            self.r_since = None
            return self._go(p, way[0], now)
        if near:                                                          # nothing in view: navigate to them, no shots
            self.r_since = None
            return self._go(p, (near["pos"][0], near["pos"][2]), now)
        return {"hold": set()}


EARLY_OPS = ("mercenaries_unlock",)              # RAM only (pSys+4 unlock bits): in at once, menus included; the rest
                                                 # are code hooks, applied at Select Player (play(): after the menu moment)


def setup(ad) -> list[str]:
    """Apply the hack package (re_mods); returns the ops that failed. In a round: all of it. Anywhere else (the title,
    the menus) only the unlock bits go in now, so the main menu lists THE MERCENARIES; the code hooks wait for Select
    Player, where play() applies them after it saved the menu moment (a save state taken after the hooks restores into
    a hang, 2026-10-20)."""
    try:
        in_round = in_mercenaries(snapshot(memory(ad)))
    except Exception:                                # noqa: BLE001 - can't tell: the unlock bits only
        in_round = False
    return apply_package(ad, None if in_round else EARLY_OPS)


def apply_round(ad, equip_now: bool = False) -> list[str]:
    """The per-round random loadout (re_mods random_loadout); the failure as a list, empty when it went in."""
    from . import re_mods_tool as RM
    try:
        r = RM.run(ad, ROUND_OP[0], **ROUND_OP[1], **({"equip_now": True} if equip_now else {}))
        return [] if r.get("verified") else [f"{ROUND_OP[0]}: not verified ({r.get('picked')})"]
    except Exception as e:                           # noqa: BLE001 - a failed draw keeps the last loadout
        return [f"{ROUND_OP[0]}: {e}"]


def apply_package(ad, only=None, skip=()) -> list[str]:
    """Run the package's re_mods ops (only those named in `only` when given, none in `skip`); the ones that failed."""
    from . import re_mods_tool as RM
    g = RM.RE4(ad)
    failed = []
    for op, kw in PACKAGE:
        if (only is not None and op not in only) or op in skip:
            continue
        try:
            RM.run(ad, op, g=g, **kw)
        except Exception as e:                       # noqa: BLE001 - one failed mod never stops the run
            failed.append(f"{op}: {e}")
    return failed


def first_aid(ad, s: dict, stats: dict, now: float | None = None, round_id=None) -> dict:
    """The package's auto_first_aid, one tick (re_mods_tool.maintain_first_aid): with Leon in a round and under 35% of
    his full health, one verified write puts it back to full (what using a First Aid Spray does), once per 2.5 s. Nothing
    happens unless the op is on for this adapter (PACKAGE turns it on at Select Player); never raises."""
    from . import re_mods_tool as RM
    try:
        return RM.maintain_first_aid(ad, s, stats, now=now, round_id=round_id)
    except Exception as e:                           # noqa: BLE001 - the loop goes on without the spray
        stats["first_aid_status"] = f"first aid unavailable: {type(e).__name__}"
        return {"auto_first_aid": False, "active": False, "verified": False}


def arm_round(ad, stats: dict) -> None:
    """Every round is armed, whichever way it started (2026-10-24: MercMode launches booted past Select Player, where
    the package and the random gun are applied, so nine rounds ran with no mods and not one shot fired). The package
    goes in once per run if Select Player never applied it; the round's random gun (x20 fire rate) is equipped now
    unless Select Player drew one for this round."""
    if not str(stats.get('hooks') or '').startswith('applied'):
        failed = apply_package(ad, skip=EARLY_OPS + LOADOUT_OPS)
        stats['hooks'] = 'applied in round' + (f' ({len(failed)} failed)' if failed else '')
        if failed:
            stats['hooks_failed'] = '; '.join(failed)[:300]
    if stats.get('rounds_hooked_seen') != stats.get('rounds_hooked'):
        stats['rounds_hooked_seen'] = stats.get('rounds_hooked')         # Select Player drew this round's gun
        return
    failed = apply_round(ad, equip_now=True)
    stats['round_armed_in_round'] = stats.get('round_armed_in_round', 0) + 1
    if failed:
        stats['round_hooks_failed'] = '; '.join(failed)[:300]


def _room_on(m) -> bool:
    """The game runs a room (gbox.re4_menus.in_room); True when that can't be read (the clock decides, as before)."""
    if re4_menus is None:
        return True
    try:
        return re4_menus.in_room(m)
    except Exception:                                # noqa: BLE001
        return True


class _Menus:
    """Out of a round: RE4's menus (gbox.re4_menus) through the shared boot layer (gbox.mercs_bot.Boot): the menu
    moment and the hooks at Select Player, one press at a time, and the run's end when the game wandered off (a story
    game) or RAM can't name the menus."""

    def __init__(self, ad, m, send, sleep, clock, stats, game=None, hooks=None):
        from .mercs_bot import Boot
        rounds = None
        if hooks is None and ad is not None:         # the default: the package, and a random loadout at every Select Player
            hooks = lambda: apply_package(ad, skip=EARLY_OPS + LOADOUT_OPS)          # noqa: E731
            rounds = lambda: apply_round(ad)                                         # noqa: E731
        # a random character and stage every round (operator 2026-10-24: "it keeps picking the same character"),
        # unless a launch explicitly asks for the game's own default; a MercMode launch can carry the DJ's pick
        merc = ((game or {}).get('launch') or {}).get('mercmode')
        selected = re4_menus.RandomSelections(key=id(ad)) if re4_menus is not None and merc is not False else re4_menus
        pick = merc.get('selection') if isinstance(merc, dict) else None
        if re4_menus is not None and isinstance(pick, dict) and pick.get('title') == 're4':
            try:
                re4_menus.request(id(ad), pick.get('character'), pick.get('stage'))
            except ValueError:
                pass
        self.boot = Boot(selected, m, send, sleep=sleep, clock=clock, stats=stats, ad=ad, game=game, hooks=hooks,
                         jump_at="select_player", round_hooks=rounds) if re4_menus is not None else None

    def tick(self, s: dict, now: float) -> str | None:
        """One look at the screen; returns why the run must end (stats["hung"] is set), else None."""
        if self.boot is None:return None
        scr=self.boot.menus.screen(self.boot.m,merc=s)
        if scr.get('where')=='select_player' and scr.get('cursor')==scr.get('target') \
                and type(scr.get('cursor')) is int and 0<=scr['cursor']<len(re4_menus.PLAYERS):
            self.boot.stats['character']=re4_menus.PLAYERS[scr['cursor']]
            self.boot.stats['character_source']='native_menu_cursor'
        elif scr.get('where')=='select_stage' and scr.get('cursor')==scr.get('target') \
                and type(scr.get('cursor')) is int and 0<=scr['cursor']<len(re4_menus.STAGES):
            self.boot.stats['stage']=re4_menus.STAGES[scr['cursor']]      # the round's stage (MercMode's prepare receipt)
            self.boot.stats['stage_index']=scr['cursor']
        return self.boot.tick(now, scr=scr)


def learn_dir_for(ad) -> Path:
    """Where the learned stage maps live: the worker's runtime folder (or ~/.gbox for a standalone run)."""
    rt = getattr(getattr(ad, "config", None), "runtime", None)
    return (Path(rt) if rt else Path.home() / ".gbox") / "re4_learned"


def round_maps_dir_for(ad=None, learn_dir: Path | None = None) -> Path:
    """Where every round's route map lands, RE5's layout (gbox-data/mercs/round_maps/BLUS30491 beside it): the
    adapter's <data_dir>/mercs/round_maps/G4BE08; with no adapter but a learn_dir of one's own (tests, a private
    run) its neighbour <learn_dir>/../round_maps/G4BE08; else the lessons' gbox-data (gbox.mercs.lessons.ROOT, the
    configured data dir). 2026-10-26: the Spark's RE4 maps had been going to <runtime>/round_maps/r4xx/ (the learned
    map's folder), where nobody looked for them, and a Bot without a learn_dir wrote none at all."""
    data = getattr(getattr(ad, "config", None), "data_dir", None)
    if data:
        return Path(data) / "mercs" / "round_maps" / "G4BE08"
    if learn_dir is not None:
        return Path(learn_dir).parent / "round_maps" / "G4BE08"
    from .mercs import lessons
    return Path(lessons.ROOT).parent / "round_maps" / "G4BE08"


def play(ad, send, stopped, sleep=time.sleep, m=None, tick_s: float = 0.05, stats: dict | None = None,
         clock=time.time, learn_dir: Path | None = None, rerun=None, prompt=None, ram_prompt=None, game=None,
         hooks=None, round_boundary=None, record_dir=None, session_id=None, source_job_id=None,
         prepare: bool = False) -> dict:
    """Drive Leon until stopped(); send(rows) presses keys. Returns the run's stats (stats, when given, is filled live:
    the watch panel shows it): backoffs, prompts, max_combo, combo, timer, rounds, menu_presses, screen.

    prepare (MercMode's seamless swap, gbox.tools._prepare_round): only the menus - the walk ends on the round's first
    in-round frame (Select Stage taken, the stage loaded, Leon in the room with the clock running) with nothing pressed
    in it and stats["prepared"] True; the caller pauses the game at that exact point and the switch resumes it there.

    From boot, and between rounds, it gets to the next round from RAM (gbox.re4_menus: the title, the main menu's THE
    MERCENARIES, GAME START, Leon, the Village, the results, "You Are Dead": Continue Yes), one press at a time and only
    on a screen RAM names: never New Game, Load, Options, Assignment Ada or EXIT (blind up + A presses had walked to the
    main title and started a story game with the hooks in, which crashed Dolphin, 2026-10-20). At Select Player it
    saves the menu moment (gbox.mercs_bot.save_menu_moment: game = the session's game and build) and applies the package's
    code hooks (hooks(), default apply_package). A story game, or menus RAM can't name (mercs_bot.MENU_LOST_S), end the run
    with stats["hung"] (the caller relaunches a bot demo, into its menu moment).

    The button prompts come from RAM first (ram_prompt: () -> button | None, raising re4_ram_prompts.Unknown when
    RAM can't tell; default: gbox.re4_ram_prompts on m, False = none) and from prompt (vision, gbox.screen_prompt)
    only when RAM fails or can't tell (operator 2026-10-20: "Vision analysis to me should be the last level that we
    have to fall back to"). stats["prompt_source"] says which one answered last."""
    m = m or memory(ad)
    if ad is not None and getattr(m, "adapter", None) is None:
        m.adapter = ad                                 # verified writes (the stalemate clock cut) use the owning adapter
    bot, held = Bot(m, clock=clock, learn_dir=learn_dir or learn_dir_for(ad),
                    round_maps_dir=round_maps_dir_for(ad, learn_dir)), set()
    if stats is not None:
        stats.update(bot.stats)
        bot.stats = stats
    stalemate_rule.configure(bot.stats, game)          # the launch's MercMode stalemate_cut / stalemate_cut_s (default on, 5 s)
    try:
        started_in = in_mercenaries(snapshot(m)) and _room_on(m)
    except Exception:                              # noqa: BLE001 - a read during a load: from the menus
        started_in = False
    bot.stats.update(rounds=1 if started_in else 0, menu_presses=0,
                     **({"screen": "playing"} if started_in else {}))   # a prepared swap starts in the round: say so at once
    menus = _Menus(ad, m, send, sleep, clock, bot.stats, game=game, hooks=hooks)
    out_since, last_press, was_in, left_at = None, 0.0, started_in, None
    bot.stats["prompt_presses"] = 0
    prompt_taps: list = []                         # times the current prompt was pressed
    prompt_rest = 0.0
    if ram_prompt is None and re4_ram_prompts is not None:
        ram_prompt = re4_ram_prompts.source(m, bot.stats)
    unknown = re4_ram_prompts.Unknown if re4_ram_prompts is not None else LookupError
    import uuid
    boundary_id=uuid.uuid4().hex
    boundary_sent=False
    armed_round=None
    playing_observed=started_in
    recorder=None
    record_dir=record_dir or getattr(getattr(ad,'config',None),'data_dir',None)
    if record_dir is not None and not prepare:           # a prepare plays no round: nothing to record
        from .mercs.legacy_trace import LegacyRecorder
        provenance={key:value for key,value in {'source_session_id':session_id,
            'source_autoplay_job_id':source_job_id}.items() if isinstance(value,str) and 0<len(value)<=160}
        recorder=LegacyRecorder(record_dir,bot.stats,getattr(ad,'config',None),provenance=provenance)

    def ask():
        """The button the game asks for: RAM (the game's own action state), else vision."""
        if ram_prompt:
            try:
                button = ram_prompt()
                bot.stats["prompt_source"] = "ram"
                return button
            except unknown:
                pass                               # not a state RAM can name: the screen decides
        if prompt is not None:
            bot.stats["prompt_source"] = "vision"
            return prompt()
        return None

    def hold(keys):
        nonlocal held
        rows = [{"key": k, "down": False} for k in sorted(held - keys)] + [{"key": k, "down": True} for k in sorted(keys - held)]
        if rows:
            send(rows)
        held = set(keys)
    while not stopped():
        s = snapshot(m)
        now = clock()
        room_on = _room_on(m)                         # a stage still loading shows the last round's clock
        if (round_boundary is not None or recorder is not None) and playing_observed and not boundary_sent and re4_menus is not None \
                and (s.get('timer')==0 or isinstance(s.get('hp'),(int,float)) and s['hp']<=0):
            terminal=re4_menus.screen(m,merc=s)
            if terminal.get('where') in ('results','dead') and s.get('player'):
                hold(set())
                witness={'screen':terminal['where'],'playing_observed':True,'player_verified':True,
                    'tally_ready':terminal['where']=='results','timer':s.get('timer'),'hp':s.get('hp'),
                    'game_routine':terminal.get('game_routine'),'room':s.get('room')}
                if recorder is not None:recorder.finish(now,'completed' if terminal['where']=='results' else 'died',bot.stats)
                boundary_sent=True
                if round_boundary is not None:
                    round_boundary({'round_id':boundary_id,'at':now,'map_id':'G4BE08',
                        'role':'solo_p1','source':'native_terminal_reader','mode':'mercenaries',
                        'stage':str(s.get('room')),'character':bot.stats.get('character'),'witness':witness},bot.stats)
                if bot.stats.get('mercmode_rotate_requested'):
                    break
        if not in_mercenaries(s) or s["timer"] <= 0 or not room_on:   # results (clock at 0), the title, menus, a load
            hold(set())
            out_since = out_since or now
            # Leon grabbed / a pickup animation: still the Mercenaries room with time on the clock - not the round's
            # end (a 2 s gap there reran a 49,370 round with 21 s left, 2026-10-20); wait it out
            transient = room_on and s["room"] is not None and (s["room"] >> 8) == 4 and s["timer"] > 0.5
            if transient and now - out_since < TRANSIENT_MAX:
                sleep(0.25)
                continue
            if rerun is not None and now - out_since > MENU_AFTER:
                # the menu save state (Select Player, taken before the hooks): load it, hooks back in, character,
                # stage, go - blind A presses walked from the Result screen to the main title and started a story
                # game with the Mercenaries hooks in, which crashed the game (2026-10-20)
                try:
                    rerun()
                    bot.stats["reruns"] = bot.stats.get("reruns", 0) + 1
                except Exception as e:             # noqa: BLE001 - the next pass tries again
                    bot.stats["rerun_error"] = f"{type(e).__name__}: {e}"[:200]
                out_since, last_press = None, clock()
                sleep(1.0)
                continue
            if was_in:
                left_at = now                          # a round just ended: its results come up first
                bot.trace_finish()                     # its route map (round_maps/r<room>/)
            if rerun is None and (left_at is None or now - left_at > MENU_AFTER):
                # the screen from RAM and the one press towards the next round (gbox.re4_menus), never a blind one:
                # up + A had walked from the Result screen to the main title's START, a story game with the hooks in
                # that crashed Dolphin (2026-10-20)
                why = menus.tick(s, now)
                if why:
                    bot.stats.update(hung=True, wandered=why)
                    break
            was_in = False
            sleep(0.25)
            continue
        if prepare:
            # MercMode prepare: the round is up (Leon in a Mercenaries room, the clock running): stop on this first
            # in-round frame with nothing pressed; the caller pauses the game here (gbox.tools._prepare_round)
            bot.stats.update(screen="playing", prepared=True, timer=s["timer"], room=s["room"])
            break
        if not was_in:
            boundary_id,boundary_sent=uuid.uuid4().hex,False
            bot.stats["rounds"] += 1
            bot.trace_start(boundary_id)
            bot.stats["screen"] = "playing"            # the menus' last screen no longer shows on the watch panel
            bot.save()                                 # what the last round taught
            was_in = True
        elif boundary_sent and room_on and s.get('player') and s.get('hp',0)>0:
            # A retry can recreate the player without a sampled menu gap: an attempt of its own, with its own route map
            # (2026-10-26: one map spanned a whole RE4 turn of deaths and retries, so no single death could be traced)
            boundary_id,boundary_sent=uuid.uuid4().hex,False
            bot.stats['rounds']+=1
            bot.trace_start(boundary_id)
        if room_on and s.get('player') and s.get('hp',0)>0:
            playing_observed=True
            if getattr(bot, "trace", None) is not None:
                px_, py_, pz_ = s['player']['pos']
                bot.trace.add(now, px_, pz_, py_, bot.stats)
            if ad is not None and armed_round != bot.stats['rounds']:
                arm_round(ad, bot.stats)
                armed_round = bot.stats['rounds']
        out_since = None
        bot.stats.update(combo=s["combo"], timer=s["timer"])
        if ad is not None:                             # the infinite First Aid Spray: hp -> full when low (auto_first_aid)
            first_aid(ad, s, bot.stats, now=now, round_id=bot.stats["rounds"])
        if recorder is not None and s.get('hp',0)>0:
            recorder.observe(s,bot,held,now,boundary_id,bot.stats.get('character','Unknown'))
        resting = now < prompt_rest
        button = ask() if not resting or ram_prompt else None
        mash = button == "wiggle"                      # SHAKE OFF (a grab): every pass, resting or not
        if button and not mash and (resting or not bot.prompt_ok(button, s, now)):
            button = None                              # resting, or an attack lands first: fight / dodge, prompt later
        if button:                                     # the game asks for a button: press it (not aiming: A acts)
            prompt_taps = [t for t in prompt_taps if now - t < 3.0]
            if len(prompt_taps) >= PROMPT_BURST and not mash:
                prompt_rest, prompt_taps = now + PROMPT_REST, []
            elif mash or not prompt_taps or now - prompt_taps[-1] >= PROMPT_EVERY:
                hold(set())
                # one button, a QTE's pair pressed together (A+B, L+R), or SHAKE OFF's run of stick flicks and A / B
                chords = re4_ram_prompts.KEYS.get(button, [(button,)]) if re4_ram_prompts is not None else [(button,)]
                for chord in chords:
                    send([{"key": k, "down": True} for k in chord])
                    sleep(0.045 if mash else (0.12 if len(chords) == 1 else 0.06))
                    send([{"key": k, "down": False} for k in chord])
                    if mash or len(chords) > 1:
                        sleep(0.035 if mash else 0.04)
                prompt_taps.append(clock())
                bot.stats["prompt_presses"] += 1
                if not mash:
                    sleep(0.15)
                continue
        else:
            prompt_taps = []
        act = bot.tick(s)
        if "tap" in act:
            hold(set())
            sleep(0.15)
            send([{"key": act["tap"], "down": True}])
            sleep(0.25)
            send([{"key": act["tap"], "down": False}])
            sleep(0.4)
            continue
        hold(act["hold"])
        sleep(tick_s)
    hold(set())
    if recorder is not None:recorder.finish(clock(),'interrupted',bot.stats)
    bot.trace_finish()                                 # a stopped / frozen round still leaves its route map
    bot.save()
    return bot.stats


def matches(ad, g: dict) -> bool:
    """This playbook plays this session: RE4 GameCube NTSC-U in any state. From boot (the title, the menus) play()
    gets itself to a Mercenaries round from RAM (gbox.re4_menus); in a round it plays."""
    if g.get("platform") != "gamecube":
        return False
    try:
        return memory(ad).rd(0x80000000, 6).decode("ascii", "replace") in GAME_IDS
    except Exception:                                # noqa: BLE001
        return False
