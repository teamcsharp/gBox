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

from .. import tuning                      # learned per-stage constants and dead ends (gbox/mercs/tuning.py)
from ..bot_look import BotLook, make_target
from ..driver import Driver
from . import re5_switch_aim, re5_switch_nades, re5_switch_prompt

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
P_AIM_PITCH = 0x3F5C                     # f32 the aim's pitch while the gun is up (rad, + = down): the game's own, from
                                         # the camera, not the laser's muzzle -> dot line (which misreads up close);
                                         # computed every frame (a write does not hold: aim_write_probe, 2026-10-27)
HELD_R = 25.0                            # a Majini this near is on him: every hold measured 0-8 cm (bodies collide ~50 cm
                                         # apart otherwise), whatever the motion says
DYING_HP = 1                             # the solo dying state keeps exactly 1 HP (the PS3's, verified; seen live here)
# The inventory, in the player (live 2026-10-26): slots of 0x38 from +0x30F0; a slot's +0x08 u32 id word 0x0TII (T 1 a
# weapon uWpII, 2 ammo, 3 a recovery item), +0x0C rounds (an item's count), +0x10 capacity, +0x1C the grid position,
# +0x20 1 = in hand. Chris (BSAA) starts No Mercy with a First Aid Spray at grid 7 (the D-pad's down).
P_INV, INV_SLOT, INV_SLOTS = 0x30F0, 0x38, 9
INV_ID, INV_ROUNDS, INV_CAP, INV_GRID, INV_HAND = 0x08, 0x0C, 0x10, 0x1C, 0x20
INV_OBJ = 0x30                           # -> the item's own object (heap); the game zeroes it when the slot empties (live
                                         # 2026-10-27, the spray's slot two seconds after its last use)
EMPTY_IDS = frozenset({0x0, 0x100})      # no item / WP00 NONE
E_COUNT, E_ARRAY, E_POS, E_HP = 0x38, 0x48, 0x60, 0x1EB8
# A Majini's own motion (the player's +0x8F8, the same base class) and its action flags (+0xA23: 0x40 while an attack is
# under way), read for the ones within WINDUP_READ_R (one read each). Found read-only on the live MercMode game
# (2026-10-27 20:20-20:30, 4495 samples of the nearest Majini within 3 m, 32 of his hits and grabs): motion 80 is the
# grab's lunge (from ~1.6 m, the grab ~0.6 s later: 26 % of its ticks end in an attack within 1 s, 54 grabs and 40 hits),
# 81 another grab's, 60 and 91 swings (31 / 32 %), 7 the grab itself, 47 / 13 holding him; 4 standing, 40 walking (11 %:
# the walk in), 85-87 / 30 / 12 / 2 none. The flag: 45 % (64 of 209 ticks set) against 4 % clear.
E_MOTION, E_ACT, E_ATTACKING = 0x8F8, 0xA23, 0x40
WINDUP_MOTIONS = frozenset({80, 81, 60, 91})
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
REPLAY_ON_DEATH = False                  # (operator 18:03: "a random character / costume each and every round ... and
                                         # level": a death answers No and walks the selects too - never the same round)
FRESH_ROUND_S = 3.0                      # a clock this close to the round's full time on the first tick alive: it began


def continue_target() -> int:
    """The "Continue?" answer the pace wants: Yes (replay) unless REPLAY_ON_DEATH is off."""
    return CONTINUE_YES if REPLAY_ON_DEATH else CONTINUE_NO
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, EXTRA_MERCENARIES, MODE_NO_MERCY = 0, 1, 0, 3
STAGE_TARGET, PLAYER_TARGET = 0, 0       # Public Assembly, Chris (BSAA): the selects' first entries
# The operator's next-round choice (the PS3 tool's mercs_select, re5_switch_mods.mercs_select): the stage and character
# selects walk to these instead (STAGE_NAMES / CHARACTERS index); kept across a bot reload
SELECTION: dict = {}
STAGE_NAMES = ("Public Assembly", "The Mines", "Village", "Ancient Ruins", "Experimental Facility", "Missile Area",
               "Ship Deck", "Prison")
CHARACTERS = ("Chris (BSAA)", "Chris (Safari)", "Chris (STARS)", "Sheva (BSAA)", "Sheva (Clubbin)", "Sheva (Tribal)",
              "Jill (BSAA)", "Jill (Battle Suit)", "Wesker (Midnight)", "Wesker (STARS)")
RELOAD_KEEP = ("SELECTION", "_CYCLE")


# The stage cycle (operator 18:03: "i am not seeing the bots cycle through random levels and characters ... I want a
# random character / costume each and every round ... and level. I want them learning and studying and cycling through
# all of the levels"): with no operator choice (SELECTION, mercs_select), each visit to the selects takes the stage
# played least so far (random among the ties, never the last one) and a random character / costume (CHARACTERS: the
# costumes are the select's own entries; never the last one), held until a round starts on them. The counts persist
# (CYCLE_FILE). A target the cursor does not reach in CYCLE_MAX_PRESSES presses (a locked entry) is given up: the entry
# the cursor rests on is taken. The round's stats name the stage and character; stage_coverage the counts.
CYCLE, CYCLE_MAX_PRESSES = True, 14


class StageCycle:
    def __init__(self, path=None, rng=None):
        import random
        self.path, self.rng = path, rng or random.Random()
        self.stages, self.chars, self.last, self.held = {}, {}, None, None
        self.confirmed = {}                                 # what the selects confirmed this visit: stage / character
        self.presses, self.where = 0, None
        if path is not None:
            try:
                import json
                d = json.loads(open(path, encoding="utf-8").read())
                self.stages = {int(k): int(v) for k, v in (d.get("stages") or {}).items()}
                self.chars = {int(k): int(v) for k, v in (d.get("characters") or {}).items()}
                self.last = tuple(d["last"]) if isinstance(d.get("last"), list) and len(d["last"]) == 2 else None
            except (OSError, ValueError, TypeError, KeyError):
                pass

    def pick(self) -> tuple:
        """(stage, character) for the coming round, held until a round starts on it."""
        if self.held is None:
            last_s, last_c = self.last if self.last else (None, None)
            stages = [i for i in range(len(STAGE_NAMES)) if i != last_s] or list(range(len(STAGE_NAMES)))
            low = min(self.stages.get(i, 0) for i in stages)
            stage = self.rng.choice([i for i in stages if self.stages.get(i, 0) == low])
            chars = [i for i in range(len(CHARACTERS)) if i != last_c] or list(range(len(CHARACTERS)))
            self.held = (stage, self.rng.choice(chars))
        return self.held

    def started(self, stage: int, char: int) -> None:
        self.stages[stage] = self.stages.get(stage, 0) + 1
        self.chars[char] = self.chars.get(char, 0) + 1
        self.last, self.held, self.confirmed = (stage, char), None, {}
        if self.path is not None:
            try:
                import json
                import os
                tmp = str(self.path) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump({"stages": self.stages, "characters": self.chars, "last": list(self.last)}, f)
                os.replace(tmp, self.path)
            except OSError:
                pass

    def coverage_text(self) -> str:
        return ", ".join(f"{STAGE_NAMES[i]} {self.stages.get(i, 0)}" for i in range(len(STAGE_NAMES)))


_CYCLE: dict = {}                        # the one StageCycle (made when first used); kept across a bot reload


def cycle() -> StageCycle:
    if "c" not in _CYCLE:
        try:
            from .. import lessons
            path = lessons.ROOT.parent / "re5-switch-cycle.json"
        except Exception:                                    # noqa: BLE001 - no data folder: in memory only
            path = None
        _CYCLE["c"] = StageCycle(path)
    return _CYCLE["c"]


def stage_target() -> int:
    if "stage" in SELECTION or not CYCLE:
        return int(SELECTION.get("stage", STAGE_TARGET))
    return cycle().pick()[0]


# Split screen (docs/research/switch-coop-bot.md, static from this main): sPlayer holds four players at +0x30 + 8 * index
# (count +0x50); the add-player routine (main+0x1EC6F4) stores each one's index byte at +0x3F2C, and the player's init
# (main+0x7974C4) its own uLaserSight at +0x3728 with the owner's index in the laser's +0x374. uIdStartUp29's confirm
# (main+0x59E2FC) writes the mode list's choice to cGameSys +0x898 (SPLIT-SCREEN 2; NO MERCY is 0 plus the flag +0xA76).
# A snapshot is player 0's, read exactly as before, unless the memory names a player (mercs_player_index) or split screen
# (mercs_coop): gbox.mercs.titles.switch_team.View, one per player. The menus walk takes SPLIT-SCREEN for a session whose
# memory asks for split screen (mercs_split_screen, set by switch_team.Session on its own session's memory only).
P_INDEX, S_PLAYER_COUNT, MAX_PLAYERS = 0x3F2C, 0x50, 4
P_LASER, LASER_OWNER = 0x3728, 0x374
GS_PLAYERS, PLAYERS_SPLIT, MODE_SPLIT_SCREEN = 0x898, 2, 2


def mode_target(m=None) -> int:
    """The mode list's entry the menus walk takes: SPLIT-SCREEN for a split-screen session, NO MERCY otherwise."""
    return MODE_SPLIT_SCREEN if getattr(m, "mercs_split_screen", False) is True else MODE_NO_MERCY


def player_index(m) -> int | None:
    """The player a snapshot of m is for (0 = Player 1, the solo default); None for a value that names no slot."""
    index = getattr(m, "mercs_player_index", 0)
    return index if type(index) is int and 0 <= index < MAX_PLAYERS else None


def player_pointer(m, sp: int, index: int) -> int:
    """Player `index` from sPlayer's slots, only when its own index byte agrees (never a neighbouring slot's)."""
    try:
        p = u64(m, sp + P_FIRST + 8 * index)
        return p if ptr_ok(p) and m.rd(p + P_INDEX, 1)[0] == index else 0
    except (ValueError, OSError, struct.error):
        return 0


def own_laser(m, p: int, index: int) -> dict | None:
    """Player p's own laser sight (its +0x3728, owned when the laser's +0x374 holds p's index): the same reading as
    laser(); None without one (the bot aims by heading then, never by the other player's laser)."""
    try:
        u = u64(m, p + P_LASER)
        if not ptr_ok(u) or struct.unpack("<I", m.rd(u + LASER_OWNER, 4))[0] != index:
            return None
        at = struct.unpack("<3f", m.rd(u + LASER_DOT, 12))
        frm = struct.unpack("<3f", m.rd(u + LASER_FROM, 12))
    except (ValueError, OSError, struct.error):
        return None
    up = all(math.isfinite(v) for v in at + frm) and any(frm) and math.dist(at, frm) >= 1.0
    return {"from": frm, "at": at, "up": bool(up)}


def player_target() -> int:
    if "character" in SELECTION or not CYCLE:
        return int(SELECTION.get("character", PLAYER_TARGET))
    return cycle().pick()[1]

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
_CLASSES: dict = {}                      # an enemy's vtable -> its class name (uEm10 ...), named once a boot
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
# Smoothness (operator 2026-10-27 10:55: "the bot in RE5 is aiming spasticly"). Live 10:36-10:48: hit rates fine, but 90
# decision changes a minute: the gun raised 22 times and lowered 16 times a minute (each a camera zoom in / out on
# stream), 9 body turns and 5 quick turns a minute. Now: the target is not flipped back to the one he just left within
# FLIP_S (a grab threat still wins), the dot on another Majini makes him the target only after DOT_SWITCH_TICKS ticks,
# the gun goes down for a far-off aim only after UNAIM_HOLD_S of it (or past UNAIM_HARD), never within MIN_UP_S of
# coming up, and once turning with the gun down it comes up again inside RERAISE_FRAC of the raise tolerance. The dot
# resting on another Majini before he becomes the target still pulls the trigger on him (as before: opportunistic fire
# in a crowd; live 11:42-11:54 without it: 13.8 kills a round, 5 deaths in 6), the aim held where it is. Both
# holds only with nobody within THREAT_R (live 11:42, the first turn: ringed at arm's length, two deaths in two
# rounds): up close he turns at once, as before.
# Off since 2026-10-27 13:00: with it on, deaths rose in every RE5 turn (#1322: 5 in 6; with #1323 and #1325: 3 in 6;
# with #1327: 4 in 5, against 1-3 in 5 before), while kills came back (19.6-19.8). K_PLAN stays on. The pieces return one
# at a time, each with its own turn of numbers.
SMOOTH = False
# The pieces, back one RE5 turn at a time, each with its own numbers (a piece that raises deaths is dropped); each is on
# when its flag is True or SMOOTH is:
SMOOTH_FAR = True        # the far-aim unaim hold and the re-raise hysteresis, only with nobody within THREAT_R (13:25)
SMOOTH_FLIP = True       # no flip back to the Majini he just left within FLIP_S (back 14:10)
SMOOTH_DOT = False       # the dot takes another Majini after DOT_SWITCH_TICKS (and fires on him at once meanwhile)
SMOOTH_LEVEL = True      # his own level first, no pitch swings to roofs while ground Majini come (back 14:40)
SMOOTH_CLOSE = True      # up close the target is kept until it dies or leaves THREAT_R (back 14:40)


def piece(flag: bool) -> bool:
    return bool(flag or SMOOTH)
FLIP_S, DOT_SWITCH_TICKS = 1.5, 2
UNAIM_HOLD_S, UNAIM_HARD, MIN_UP_S, RERAISE_FRAC = 0.25, math.radians(75), 0.5, 0.75
MOTION_COUNTERS = ("target_switches", "target_flips", "aim_reversals", "stick_onsets", "raises", "unaims")
# His own level first (live 12:06: the camera pointed at the sky for 2 s, the aim pitched up at a Majini on a roof inside
# the MAX_DY window, while ground Majini closed in and grabbed him): a Majini off his level costs LEVEL_COST x its
# height / MAX_DY more, and the "in front" pick takes one on his level (within LEVEL_DY) whenever there is one.
LEVEL_COST, LEVEL_DY = 1.5, 120.0
# No pitch swing past PITCH_SWING (to a Majini that far above or below the muzzle) while one on his level is within
# PITCH_GUARD_R; a grab threat (GRAB_THREAT_R) always first. Up close (THREAT_R) he keeps his target until it dies or
# leaves THREAT_R unless another gets within GRAB_THREAT_R and nearer (no re-pick every tick among equal threats).
PITCH_SWING, PITCH_GUARD_R, MUZZLE_H = math.radians(25), 600.0, 140.0
LEVEL_COUNTERS = ("pitch_swings", "off_level_picks", "close_keeps")
# Combo time (operator 2026-10-27 13:10: "There should never be him chilling surrounded by enemies ... It is essential to
# be proactive with combo time"): the Mercenaries combo (cGameSys +0x974 count, +0x97C the window's seconds left). Each
# combo that falls is counted (combo_breaks), and one whose window had run out (COMBO_LAPSE_S or less left at the last
# read: the next Majini not dispatched in time) is a combo_lapse, as the PS3 bot counts them. COMBO_PUSH: with a combo
# running and its window under COMBO_URGENT_S, the target is the quickest kill (the cheapest in reach, his level first,
# no stickiness), and with nobody within COMBO_REACH he walks to the nearest (combo_pushes counts the ticks).
COMBO_PUSH, COMBO_URGENT_S, COMBO_LAPSE_S, COMBO_REACH = True, 3.0, 0.6, 900.0
# Threat first (operator 2026-10-27 14:30, watching RE5: "the bot aim sporadically where they're pointing at enemies
# that are way farther away despite them being crowded in the same area by enemies that are a much more immediate
# threat ... jumping his view around way too much"): with a Majini on his level within THREAT_NEAR_R, no target beyond
# THREAT_CAP_R - not the choice, not the dot's switch, not the nearest to the ray, not the combo's quickest kill. Among
# those his own level first, then the lowest threat distance: the distance less APPROACH_LEAD_S of the Majini's closing
# speed, x (1 + TURN_W x the turn to him / pi). The current one is kept while his threat distance is within THREAT_KEEP
# of the best (+ THREAT_KEEP_CM); one within GRAB_THREAT_R wins unless the current one is that near too.
THREAT_FIRST, THREAT_NEAR_R, THREAT_CAP_R = True, 400.0, 800.0
APPROACH_LEAD_S, APPROACH_EMA, TURN_W, THREAT_KEEP, THREAT_KEEP_CM = 0.6, 0.5, 0.5, 1.25, 25.0
# Pitch up (the same watch: "I will randomly see them point just up in the air"): every aimed tick with the laser more
# than PITCH_UP_LOG above level is counted with its cause - the target itself that high (pitch_up_target_high), the gun
# just raised (pitch_up_raise: the camera's old pitch), the target just changed (pitch_up_retarget), else
# pitch_up_other; stats pitch_up_last holds the last one's numbers.
# Only a ray at least PITCH_UP_RAY long counts (a dot on something at the muzzle reads steep at any height). The first
# ray after each raise is read too: raise_up_first counts those over PITCH_UP_LOG, with the last aim's pitch before the
# gun came down (does the raise keep the old pitch?) in stats raise_up_last; pitch_up_last is a string (the notebook
# keeps strings, not dicts).
PITCH_UP_LOG, PITCH_UP_RECENT_S, PITCH_UP_RAY = math.radians(20), 0.6, 300.0
# The sky guard (operator 2026-10-27 15:15, a frame of Chris aiming at the sky with a combo of 13 and 10 s left: "its a
# major malfunction of the aimbot. It shouldnt be doing that"): every aimed tick, a laser more than SKY_MARGIN above
# the target's own elevation (from the muzzle to his chest) is pushed down at once - the pitch-up stick never pressed in
# that state - so only a Majini actually high takes the aim up. Aimed (motion 26) with no laser at all past SKY_BLIND_S
# (the ray on nothing: the sky), the aim goes down too unless the last ray was already below level. sky_ticks: aimed
# ticks with the laser over PITCH_UP_LOG while the target is under SKY_LOW (the target is 0); sky_corrections: each
# time the guard took over; sky_blind_ticks: the no-laser pushes.
SKY_MARGIN, SKY_LOW, SKY_RAY_CM, SKY_BLIND_S, MOTION_AIMED = math.radians(12), math.radians(10), 100.0, 0.3, 26
# Off at 15:45 (the operator at 15:38, the guard and the settle on: "look at the current aim. it is dizzying"; the live
# round had sky_guard_ticks 377, sky_ticks 271, target_switches 707): the 14:58 turn's aim (threat first, no guard, no
# settle: 27.2 kills, 0 deaths) is back while the guard is fixed. The counters stay on either way.
SKY_GUARD = False
SKY_COUNTERS = ("sky_ticks", "sky_corrections", "sky_guard_ticks", "sky_blind_ticks")
# The pitch without overshoot (operator 15:15, the coordinator's list: after a retarget pitch to the new chest from where
# the aim is, no overshoot; after a raise let the game's own aim pitch settle first). The aim's pitch rate is measured
# from ray to ray (rays of PITCH_RATE_RAY or more whose dot did not jump: the distance within PITCH_RATE_JUMP x);
# pressing toward the target, the stick coasts once that rate would close the error within PITCH_LEAD_S (pitch_brakes).
# For RAISE_SETTLE_S after a raise's first ray the pitch stick waits (raise_settle_ticks; the sky guard still pushes
# down). pitch_reversals: the pitch stick the other way within 0.4 s (an overshoot corrected).
PITCH_LEAD_S, PITCH_RATE_RAY, PITCH_RATE_JUMP, RAISE_SETTLE_S = 0.15, 150.0, 1.5, 0.2
PITCH_SETTLE = False                     # off at 15:45 with SKY_GUARD (the 14:58 aim back)
# Aim faults (operator 15:33-15:38, watching RE5: "aiming into the distance while all of the enemies congregate behind
# him ... he'll randomly point the aim somewhere up in the sky or away from the enemies"; a frame of a shot into a wall:
# "take a moment to point a gun at a wall and just shoot at a wall and waste time"):
#  * the trigger only on a confirmed ray: the dot on a living Majini (any one, any distance: CONFIRMED_FIRE - threat
#    first turns him, never holds a shot the ray confirms; only another within GRAB_THREAT_R does), the ray running on
#    through the target to a dot at or past his chest (WALL_SLACK), or point blank. A ray the old gate fired on that
#    ends short of him on geometry is a wall shot (wall_shots, not fired); the dot short of him WALL_DROP_S: the target
#    left for WALL_BLOCK_S (wall_blocks);
#  * a dot frozen FROZEN_TICKS aimed ticks while the stick or his heading moved is no live aim (the sky, or a stale
#    laser): no shot, the gun down to raise it again (frozen_dots);
#  * a Majini within BEHIND_R costs no turn in the threat pick (one 3 m behind beats one 4 m ahead); behind_threat_s:
#    the seconds one within BEHIND_R stands over 90 deg off his facing while he aims at another;
#  * an aim over AWAY_ERR off the nearest threat within THREAT_NEAR_R for AWAY_S (no confirmed shot): a fault,
#    corrected at once - that one the target, the gun down to turn (aim_away_s, aim_away_fixes);
#  * crowd_max: the most within 4 m at once in the round; ex_<fault>: the first EXAMPLES of each in the round, readable.
# long_shot_kills: a Majini fired on past LONG_KILL_R found dead within LONG_KILL_S.
CONFIRMED_FIRE, LONG_KILL_R, LONG_KILL_S = True, 1500.0, 3.0
WALL_SLACK, WALL_DROP_S, WALL_BLOCK_S, FROZEN_TICKS = 10.0, 0.3, 3.0, 3   # (operator 18:58: "Every time the bot points
                                         # a gun at a wall, I cry": dropped after 0.3 s for 3 s; wall_aim_s the seconds
                                         # the gun's ray ended on geometry short of the target, target 0)
BEHIND_R, AWAY_ERR, AWAY_S, EXAMPLES = 300.0, math.radians(45), 0.3, 3
FAULT_KINDS = ("wall_shot", "wall_block", "frozen_dot", "behind_threat", "aim_away", "sky")
# The close-range pitch (the 15:26 turn's pitch_up_last: targets 0.8-2.2 m wanting -23 to -38 deg with the laser at
# +21 to +28 deg - "ray 50.0 m", the laser's limit: the sky - and the aim +56 / +57 deg just before raises, the guard's
# rdown held: up close the pitch stick ran the aim up, not down). Within CLOSE_PITCH_R no pitch stick at all (the yaw
# only; point blank and the ray through him fire) - close_pitch_skips; there the laser over CLOSE_SKY up for
# CLOSE_SKY_S without a shot: the gun down and up again, never the stick (close_sky_reraises). The first ray after a
# raise over REROLL_ERR above the wanted angle: the gun down and up again, once (raise_rerolls).
CLOSE_PITCH_R, CLOSE_SKY, CLOSE_SKY_S, REROLL_ERR = 250.0, math.radians(15), 0.3, math.radians(15)
CLOSE_COUNTERS = ("close_pitch_skips", "close_sky_reraises", "raise_rerolls")
# The 5 m rampage (operator 16:05: "if the bot is surrounded by enemies. They need to be blasting continuously until the
# threat is resolved. I dont want them raising the gun and putting it down ... until the threats within 5 meters of
# their circle are gone ... i dont care about inaccuracy"; 16:12: "whipping their view around unreasonably while
# they're getting attacked from behind pointing the gun at threats that aren't even on screen"). With a living Majini
# on his level within RAMPAGE_R, every other path waits (no dot switch, ray pick, pursuit, combo push, crowd move, wall
# gate, unaim): the target is the nearest inside the circle, held until it dies or leaves it (one within GRAB_THREAT_R
# takes over; at most one change every RAMPAGE_RETARGET_S); one within BEHIND_R and over RAMPAGE_BEHIND off his facing
# gets one decisive quick turn (the gun down for it, behind_turns), the gun comes up at once (no body turn first) and
# the trigger stays down from the first tick, the aim turning by yaw (pitch only past CLOSE_PITCH_R). The gun: a
# shotgun, else a magnum, on a D-pad slot (one press while the gun is down; the main gun back after: rampage_swaps).
# Counters: rampage_s, rampage_shots (pulls), rampage_kills, idle_in_5m_s (no trigger with one inside: target 0),
# unaims_in_5m (target 0), behind_turns, offscreen_aim_s (the aim over OFFSCREEN_ERR off the nearest inside, target 0),
# whips (a turn of WHIP_DEG or more reversed by WHIP_BACK_DEG within WHIP_S: target near 0); rampage_weapon: the gun.
RAMPAGE, RAMPAGE_R, RAMPAGE_RETARGET_S, RAMPAGE_BEHIND = False, 500.0, 0.6, math.radians(100)
RAMPAGE_FAMILIES = ("shotgun", "automatic", "magnum")   # the crowd's gun: a shotgun, else the Gatling / AK-74 / an
                                         # SMG (re5_weapons "automatic", #1395's loadouts), else a magnum
# Near focus (operator 20:2x: "Stop having the bot worry about enemies that are far away whenever they're surrounded by
# people that are nearby"): with a Majini on his level within RAMPAGE_R, no target, dot switch, confirmed shot, aim line
# pick or combo kill beyond NEAR_FOCUS_R - the fight's pool is the near ones. far_picks_while_crowded: ticks aimed at
# one beyond it anyway (target 0).
NEAR_FOCUS, NEAR_FOCUS_R = True, 600.0
# Crowd fire (operator 19:25: "completely surrounded with threats that they were unable to dispatch. They should have
# pulled out their shotgun and did crowd control"; 19:5x: "give the bot rapid fire shotguns for crowd control ... this
# bot is swarmed and is barely shooting"; live 19:50 / 19:53: unaims_in_5m 32 / 53, behind_threat_s 39 / 64, no
# shotgun): the rampage's path, front-facing and calm. CROWD_FIRE_N or more on his level within RAMPAGE_R, or one
# within CROWD_FIRE_CLOSE_R: the shotgun (else the magnum) comes up by its D-pad slot, the gun stays up while anyone is
# within RAMPAGE_R (never an unaim there), the target the nearest in front (within CROWD_FRONT of his facing), else the
# nearest, held until it dies or leaves; the trigger only with the aim on a Majini (the dot, the ray through one, point
# blank, or the target inside CROWD_CONE: the shotgun's spread), the aim turned to the target by the stick between shots
# only (never in the shot motion: fire_rate's time scale) and its pitch held on a chest (P_AIM_PITCH,
# SWEEP_PITCH_BAND); no quick turn (QUICK_TURN off), the heading governor over all. Counters: crowd_fire_s,
# shotgun_swaps (the shotgun / magnum put up), rampage_kills, unaims_in_5m (target 0).
CROWD_FIRE, CROWD_FIRE_N, CROWD_FIRE_CLOSE_R = True, 3, 200.0
CROWD_FRONT, CROWD_CONE = math.radians(60), math.radians(10)
OFFSCREEN_ERR, WHIP_DEG, WHIP_BACK_DEG, WHIP_S, SWAP_GAP_S = math.radians(60), 90.0, 45.0, 1.0, 1.0
RAMPAGE_COUNTERS = ("rampage_s", "rampage_shots", "rampage_kills", "idle_in_5m_s", "unaims_in_5m", "behind_turns",
                    "offscreen_aim_s", "whips", "rampage_swaps", "crowd_fire_s", "shotgun_swaps")
# The calm camera (operator 16:47: "smoothly looking around so it's like organic and it doesn't cause any sort of
# motion sickness because there's motion blur on the game"), shaped on the right stick every tick, whatever decided it
# (the RAM aim lock waits: +0x3F5C is computed, a write does not stick - 16:55): a stick direction is never reversed
# within CALM_REVERSE_S of the last press the other way (it coasts a moment first: calm_coasts); the body's turn with
# the gun down (about TURN_SPEED_DEG_S held) is held to CALM_TURN_DEG_S on average by a turn budget (calm_caps); the
# quick turn only for one within CALM_QUICK_R behind. spin_deg_s / spin_max_deg_s: his heading's mean and peak speed.
CALM, CALM_REVERSE_S, CALM_TURN_DEG_S, TURN_SPEED_DEG_S, CALM_QUICK_R = True, 0.25, 110.0, 160.0, 300.0
CALM_COUNTERS = ("calm_coasts", "calm_caps")
# The heading governor (operator 18:52: "i need the gameplay to look logical. It makes no sense for him to turn too fast
# and just rotate in place"; live with #1381's sweep: spin_deg_s 1325 mean, 1998 peak, whips 224 - the sweep held the
# aim stick while the trigger was down, and re5_switch_mods.fire_rate runs his time scale up to x80 in the shot motion,
# the stick's turn with it). The pad's last stage, whatever decided the tick (a grab's escape aside): his heading's speed
# read from RAM since the last tick over HEADING_GOV_DEG_S releases the turn stick this tick (gov_drops); no aim stick in
# the shot motion (shot_stick_drops); the quick turn (180 deg in 0.3 s) is not used (QUICK_TURN off: the body turns by
# the stick, the way out behind him backed toward). Target: spin_deg_s under 90, spin_max_deg_s under 200, whips ~0.
HEADING_GOV, HEADING_GOV_DEG_S, QUICK_TURN = True, 150.0, True
# The quick turn back (operator 20:25: "you can do a quick turn by holding down and pressing B. Thats how you turn around
# and deal with people behind you"): a Majini on his level within BEHIND_R more than QUICK_ERR off his heading, nobody
# nearer in front: the trigger let go first (never in the boosted shot motion), the gun down, then the stick back, + B,
# let go (behind_turns); the fight raises at the one now in front after the settle. At most one each QUICK_GAP_S, and
# none within QUICK_BACK_S of the last unless the one behind is within GRAB_THREAT_R (no back and forth). The quick turn
# is exempt from the heading governor (its 180 deg in 0.3 s is the game's own move).
QUICK_BACK_S = 3.0
# Wind-ups first (operator 19:25: "The bot should be able to tell who is transitioning into an attack animation and be
# able to prioritize deactivating them with an attack"): a Majini on his level within WINDUP_R whose own motion is a
# wind-up (WINDUP_MOTIONS: the grab's lunge, the swings) or whose attack flag is up is the target before any other (the
# threat pick, the crowd fire, the dot's switch), the nearest such first; behind him, the quick turn's rule applies.
# Counters: windup_seen (each one starting within WINDUP_R), windup_interrupts (one his shots hurt while it wound up and
# no attack landed within WINDUP_HIT_S), hits_after_windup (his health falling, or a grab, within WINDUP_HIT_S of one).
WINDUP, WINDUP_R, WINDUP_READ_R, WINDUP_HIT_S = True, 300.0, 600.0, 1.2
WINDUP_COUNTERS = ("windup_seen", "windup_interrupts", "hits_after_windup", "windup_picks")
# The RAM aim lock (re5_switch_aim, the RE6 way of #1367; the coordinator 19:06: "even better aim"): with the gun up,
# the aim moved by RAM toward the target instead of the right stick - the player's heading by the yaw error, the camera
# pitch (uCameraQFPS +0x1B0) by the pitch error, each at most AIM_LOCK_YAW_DEG_S / AIM_LOCK_PITCH_DEG_S (all of it within
# AIM_LOCK_SNAP_DEG: no overshoot, no snap), every write read back; the errors from the laser's ray when it is long
# enough to steer by, else from his heading and the chest's elevation. While the gun comes up the camera pitch goes to
# the target's elevation first (no raise from an old +57 deg). A failed read-back: the stick as before (aim_lock_fails).
# OFF until one live round shows the writes hold (no private slot for the write test). Counters: aim_lock_ticks,
# aim_lock_fails, aim_lock_prepitch.
AIM_LOCK, AIM_LOCK_YAW_DEG_S, AIM_LOCK_PITCH_DEG_S, AIM_LOCK_SNAP_DEG = True, 140.0, 90.0, 1.5
AIM_LOCK_HELD = 0.03                     # rad: the next frame's state this near the write: it held (else, 6 times and
                                         # more often than held, the lock stands down for the round: aim_lock_unheld)
AIM_LOCK_COUNTERS = ("aim_lock_ticks", "aim_lock_fails", "aim_lock_prepitch", "aim_lock_unheld")
GOV_COUNTERS = ("gov_drops",)
# The game's own prompts (operator 17:39: "seeing them miss QTE events"; 17:36: the ledge's "Jump down" by Y; the
# hourglass: re5_switch_prompt's live finding, label 112 press:y on the statue - up 23 samples in six minutes, never
# pressed, bonuses_taken 0). snap prompt (sActionButton's shown button) is taken the moment it shows, ahead of the
# fight, by its type:
#   enemy   one a Majini owns or names (Break free, a dodge, a finisher) or a stick QTE: always (not kind 0 alone: the
#           start's box, uOm088a, is a kind 0 press:y too)
#   dying   Resuscitate (label 55): always            bonus   the hourglass (label 112): always
#   pickup  Pick up (label 1): with nobody within PICKUP_CLEAR_R and none of his bombs within MINE_CLEAR_R
#   traverse  a stage spot's action (TRAVERSE_LABELS, or another of his own press:y): only on the way to a statue or a
#           pursued Majini off his level (no blind Y: #1370's presses wait for the prompt now); each spot logged
#   (never the bomb's Place, label 100: the mines module's; never kind 3's area pickups: ammo is infinite)
# The press by the prompt's mode: press / release / mash - the keys one tick, let go the next (a fresh press each
# time); wiggle - the left stick left / right by turns; rotate - the left stick round; the axes - back and forth.
# Counters: prompts_seen and prompts_seen_<type>, prompts_taken (gone within PROMPT_TAKE_S of the first press),
# prompt_presses, prompt_latency_s (the mean seconds from shown to the first press), ledge_jumps (traverse prompts
# taken), level_changes (his height changing by LEVEL_DY within LEVEL_CHANGE_S of one); stats traverse_spots: the
# last spots (label @ x, y, z).
PROMPTS, PICKUP_CLEAR_R, MINE_CLEAR_R, PROMPT_TAKE_S, LEVEL_CHANGE_S = True, 250.0, 250.0, 3.0, 3.0
PROMPT_TYPES = ("enemy", "dying", "bonus", "pickup", "traverse", "other")
PROMPT_COUNTERS = ("prompts_seen", "prompts_taken", "prompt_presses", "ledge_jumps", "level_changes")     + tuple("prompts_seen_" + t for t in PROMPT_TYPES)
ROTATE = (("lup",), ("lup", "lleft"), ("lleft",), ("lleft", "ldown"), ("ldown",), ("ldown", "lright"), ("lright",),
          ("lright", "lup"))
# The turret sweep (operator 17:38: "with as many threats that they have around them within a five meter circle, they
# should be holding down the trigger and just spinning around getting all of these people that are ganging up on them";
# kept from 16:12 / 16:47: no whipping, nothing dizzying). It replaces the rampage (RAMPAGE stays off): SWEEP_N or more
# Majini on his level within SWEEP_R, or one within BEHIND_R behind him while another stands in front inside SWEEP_R:
# the gun up, the aim panned ONE way - toward the side with more of them, the nearer weighing more - by the right stick
# held (while aiming the stick turns the aim, and him with it, at the game's own steady ~40 deg/s: a slow pan, never a
# snap); the trigger held while the dot or the ray is on a Majini (or one is at point blank in front), the pan stopped
# meanwhile, until nobody is inside SWEEP_R for SWEEP_EXIT_S. A sweep that starts within SWEEP_SAME_S of the last keeps
# its direction. No aim stick while the shot motion plays (MOTION_SHOT): re5_switch_mods.fire_rate runs his own time
# scale up to x80 in it, the stick's turn with it (live 18:47, the first sweep turn: the trigger and the stick held
# together, 44 kills in a round but his heading at 970 deg/s on average, 200 whips). The aim's pitch (P_AIM_PITCH) is
# held inside SWEEP_PITCH_BAND: a Majini's chest 1-5 m away, never the sky.
# A grab, a heal, the hurt escape and the bombs still come first (they run before the fight). Counters: sweeps, sweep_s,
# sweep_kills, sweep_reversals (the yaw stick reversed during a sweep: target 0), sweep_clears / sweep_clear_s (sweeps
# that cleared the circle and their seconds); stats crowd_cleared_s: the round's mean seconds to clear it.
SWEEP, SWEEP_R, SWEEP_N, SWEEP_EXIT_S, SWEEP_SAME_S = False, 500.0, 3, 0.4, 2.0   # off since 18:52 (#1383): back
                                         # only after the heading governor (HEADING_GOV) has its numbers
MOTION_SHOT = 29                         # the shot motion (re5_switch_mods.MOTION_SHOT: the raised time scale)
SWEEP_PITCH_BAND = (-0.05, 0.30)         # P_AIM_PITCH (+ = down): from 3 deg up to 17 deg down
SWEEP_COUNTERS = ("sweeps", "sweep_s", "sweep_kills", "sweep_reversals", "sweep_clears", "sweep_clear_s",
                  "sweep_shot_waits", "shot_stick_drops")
# Keep moving (operator 17:42: "If the RE5 bot doesn't get away from the enemies and tries maneuvering around the level
# quickly, he will be overwhelmed ... It is important to continue moving around the level"): his dwell is the time he
# stays within DWELL_R of one spot. Past DWELL_MAX_S with Majini about, after a sweep clears the circle, or with
# RELOC_CROWD_N or more within RELOC_CROWD_R, he relocates (at most every RELOC_GAP_S): a run (B) away from the census -
# every live Majini within RELOC_SENSE_R pushing by 1/d - turned KITE_DEG to one side (a loop through the level, the side
# kept until a run sticks), toward a standing statue within RELOC_STATUE_DEG of that heading when there is one; the
# quick turn once when the way out is behind him; the run ends after RELOC_DIST, RELOC_MAX_S, a Majini within
# RELOC_BLOCK_R in front, or no RELOC_PROGRESS_CM in RELOC_STUCK_S (the kite's side flips). Then he turns and fights. A
# bomb is due as he leaves (the mines' own checks still apply). Counters: relocations, reloc_stuck, avg_dwell_s,
# max_dwell_s, hits_taken (his health falling).
RELOCATE, DWELL_R, DWELL_MAX_S, RELOC_CROWD_N, RELOC_CROWD_R, RELOC_GAP_S = True, 250.0, 7.0, 6, 800.0, 4.0
RELOC_SENSE_R, KITE_DEG, RELOC_STATUE_DEG, RELOC_DIST, RELOC_MAX_S = 1500.0, 35.0, 60.0, 800.0, 3.0
RELOC_BLOCK_R, RELOC_PROGRESS_CM, RELOC_STUCK_S = 150.0, 40.0, 0.8
# (operator 19:5x: "run face forward at a corner and away from the enemies while the enemies gather behind them"; live
# 19:50 / 19:53: 48 / 68 relocations a round, 12 / 16 stuck): a relocation only with nobody within 5 m (boxed in: stand
# and shotgun), to a point he knows is open - his own trail, a point every TRAIL_EVERY_S kept TRAIL_KEPT, TRAIL_AGE_S old
# or more, RELOC_GOAL_MIN away - or a standing statue, the clearest of Majini, never through them, never within
# DEAD_END_R of a run that stuck (the last DEAD_ENDS_KEPT: reloc_dead_ends). None known: he stays and fights.
TRAIL_EVERY_S, TRAIL_KEPT, TRAIL_AGE_S, RELOC_GOAL_MIN, DEAD_END_R, DEAD_ENDS_KEPT = 1.5, 60, 4.0, 500.0, 300.0, 16
RELOC_COUNTERS = ("relocations", "reloc_stuck", "reloc_dead_ends", "unaim_holds")     # hits_taken: the engine's own per-round delta field
# The aim's own pitch up close (live 17:27: "Why is he looking up?" - pitch_up_last "the laser +62 deg, wanted -24 deg,
# 2.3 m ... ray 50.0 m"; raise_up_last "first ray +28 deg, the last aim before +62 deg"): the laser's muzzle -> dot line
# misreads up close, the pitch stick followed it up, and the next raise kept the pitch. Now, aimed at a Majini on his
# level within THREAT_CAP_R, the game's own aim pitch (P_AIM_PITCH) more than CAM_UP_MAX above his chest's elevation
# (or above level for one below): the pitch stick down (never up),
# whatever the laser says, and no shot unless the dot is on a Majini (cam_up_ticks, cam_up_fixes: the times it took
# over). With the aim pitch read the gun is no longer lowered and raised again for a high first ray or a high laser up
# close (raise_rerolls / close_sky_reraises: each a camera zoom out and in). Pressed down CAM_CHECK_S and the pitch went
# up instead (cam_pitch_inverted): the guard stands down for the round.
CAM_GUARD, CAM_UP_MAX, CAM_CHECK_S = True, 0.21, 0.35   # 0.21 rad: 12 deg up
CAM_COUNTERS = ("cam_up_ticks", "cam_up_fixes", "cam_pitch_inverted")
# Time bonuses first (operator 16:45: "the most important thing is capturing every time bonus and then maintaining the
# combo"; 16:52: "running from Checkpoint to Checkpoint, grabbing the time bonuses ... In Resident Evil Five, the only way
# to grab a time bonus is to walk up to it and melee it ... after grabbing all the time bonuses, that's when the match
# truly begins"). Phase 1 of a round: the hourglass statues (uOm0100 units, vtable main+0x1BD6D58, #1350; the snapshot
# reads them every BONUS_SCAN_S: snap bonuses ptr / pos / s16 seconds), the next one by the flat distance + 3 x the
# height: he runs there (B; walking the last BONUS_WALK_R), faces it and swings the knife (L held, ZR every
# KNIFE_SWING_S) within KNIFE_R until it breaks (a step closer after KNIFE_TRY_S, KNIFE_RETRIES times, then another one
# for BONUS_BLOCK_S); a detour when no closer for 1.5 s. Only a Majini within BONUS_FIGHT_R (in his way, about to grab)
# is fought first. Phase 2, the match, once none is left or reachable. Counters: bonuses_seen, bonuses_taken (a statue
# gone from the scan), bonuses_left, bonus_time_s (the round's time when the last went), time_gained (the clock's jumps
# of BONUS_JUMP_S or more), bonus_runs, knife_swings, bonus_detours.
BONUS, BONUS_VT, BONUS_SCAN_S, BONUS_FIGHT_R, BONUS_WALK_R, BONUS_BLOCK_S, BONUS_JUMP_S = \
    True, 0x1BD6D58, 1.0, 300.0, 250.0, 12.0, 20.0       # (a Majini within 3 m: the fight takes over the run - 21:0x)
KNIFE_R, KNIFE_FACE, KNIFE_SWING_S, KNIFE_TRY_S, KNIFE_RETRIES = 90.0, math.radians(12), 0.35, 3.0, 2
# Live 16:59-17:04: 8 statues seen, none taken - he spawned on the roof (y 550) and walked at one 1.6 m below for a
# minute: stuck BONUS_JUMP_TRY_S with the statue off his level, the context action (Y, the "Jump down" prompt) first.
BONUS_JUMP_TRY_S = 0.8
BONUS_COUNTERS = ("bonuses_seen", "bonuses_taken", "time_gained", "bonus_runs", "knife_swings", "bonus_detours",
                  "bonus_jumps")
# The wall governor (operator 21:0x: "the bot running with his face in the wall as if he doesn't actually see ... that's
# how you end up surrounded by zombies"; live 20:59-21:01: bonus_detours 4-7 a round, the run straight at a statue
# through walls, then a side step for a fixed time). Over all movement, whatever decided it (the bonus run, the pursuit,
# a relocation, the hunt, a walk), before the calm camera and the heading governor: the left stick forward (not aiming)
# with under WALL_MIN_CM of progress in WALL_WINDOW_S is a wall - the push stops at once (wall_hits; wall_push_s the
# seconds pushed without progress, target ~0), the spot and heading remembered for the round (a push there again on that
# heading stops before it starts: wall_preempts), and a recovery: WALL_BACK_S stepping back, then WALL_GO_S along the most
# open known way - toward a point of his own trail (where he has walked is open) the nearest to the way he was going
# but at least WALL_TURN_DEG off it and off every wall remembered near, else back the way he came (wall_recoveries).
# The routing (worktree re5-guided-runs) feeds it its own blocked spots through wall_memory().
WALL_GOV, WALL_WINDOW_S, WALL_MIN_CM, WALL_BACK_S, WALL_GO_S = True, 0.35, 15.0, 0.25, 0.8
WALL_MEM_R, WALL_MEM_DEG, WALL_TURN_DEG, WALL_MEM_KEPT = 120.0, 35.0, 50.0, 48
WALL_COUNTERS = ("wall_hits", "wall_recoveries", "wall_push_s", "wall_preempts")
# through_shots: pulls started on the "ray through him" gate alone (the dot on geometry just past him: 64 hits, 26
# misses in the 15:26 turn), counted to decide whether that gate stays.
AIMFAULT_COUNTERS = ("wall_shots", "wall_blocks", "wall_aim_s", "frozen_dots", "behind_threat_s", "aim_away_s", "aim_away_fixes",
                     "confirmed_shots", "long_shot_kills", "through_shots") + CLOSE_COUNTERS + RAMPAGE_COUNTERS \
    + BONUS_COUNTERS + WALL_COUNTERS + CALM_COUNTERS + SWEEP_COUNTERS + RELOC_COUNTERS + CAM_COUNTERS + GOV_COUNTERS + PROMPT_COUNTERS \
    + AIM_LOCK_COUNTERS + WINDUP_COUNTERS
# Combo pursuit (operator 15:25: "the Ghidra hook make him aware of the locations of any and all enemies in the level ...
# so that in the event that he's unable to locate enemies to defeat, in order to maintain the combo, he knows where
# enemies are and is able to go and pursue them"). The census is sEnemy's whole array (snap enemies: every Majini in
# the stage, wherever he is), checked against sUnit's enemy line (ENEMY_LINE, the uEm units alive, every CENSUS_S:
# census_units against census_count). With a combo running, its window under PURSUE_S and nobody on his level within
# COMBO_REACH, he runs (B) to the census's best - the flat distance + PURSUE_DY_W x the height (his level preferred);
# no PURSUE_PROGRESS_CM closer in PURSUE_STUCK_S: a detour (PURSUE_DETOUR_DEG off the heading for PURSUE_DETOUR_S, the
# side alternating); PURSUE_MAX_DETOURS on one Majini: another for PURSUE_BLOCK_S. pursuit_kills: a kill during a
# pursuit or within PURSUE_CREDIT_S after it (once a pursuit); pursuit_lapses: a combo lapse during one.
PURSUIT, PURSUE_S, PURSUE_DY_W, PURSUE_CREDIT_S = True, 6.0, 3.0, 4.0
PURSUE_PROGRESS_CM, PURSUE_STUCK_S, PURSUE_DETOUR_DEG, PURSUE_DETOUR_S = 50.0, 1.5, 70.0, 0.9
PURSUE_MAX_DETOURS, PURSUE_BLOCK_S = 3, 8.0
ENEMY_LINE, CENSUS_S = 10, 2.0
PURSUIT_COUNTERS = ("pursuits", "pursuit_kills", "pursuit_lapses", "pursuit_stuck")
# Crowd moves (operator 15:27: "they need to always keep the crowd control and be on the move to avoid being
# overcrowded"): CROWD_N or more within CROWD_R and the gun up CROWD_BURST_S: the gun down and CROWD_MOVE_S moving away
# from them (the left stick back, sideways or between, whichever points most away; still turning to the target), at
# most once every CROWD_GAP_S; not while a confirmed long shot is on.
CROWD_MOVES, CROWD_N, CROWD_R, CROWD_BURST_S, CROWD_MOVE_S, CROWD_GAP_S = True, 3, 600.0, 1.2, 0.5, 2.5
CROWD_COUNTERS = ("crowd_moves",)
SETTLE_COUNTERS = ("pitch_brakes", "raise_settle_ticks", "pitch_reversals")
THREAT_COUNTERS = ("threat_ticks", "threat_caps", "threat_switches", "far_aim_ticks", "far_picks_while_crowded",
                   "pitch_up_ticks",
                   "pitch_up_target_high", "pitch_up_raise", "pitch_up_retarget", "pitch_up_other", "raise_up_first",
                   "raise_first_rays") + SKY_COUNTERS + SETTLE_COUNTERS + AIMFAULT_COUNTERS + PURSUIT_COUNTERS \
    + CROWD_COUNTERS
# Each lapse's cause, counted at the lapse (counters only, no behavior): no Majini alive (combo_lapse_empty), the
# nearest beyond COMBO_REACH (combo_lapse_far), one in reach but not dispatched in time (combo_lapse_near), and of
# those, how many with his gun up (combo_lapse_aimed). combo_window_full: the longest window read (the game's own).
COMBO_COUNTERS = ("combo_breaks", "combo_lapses", "combo_pushes", "combo_lapse_empty", "combo_lapse_far",
                  "combo_lapse_near", "combo_lapse_aimed")
# The enemy knowledge database at work (brain step 4, operator 2026-10-27: "not utilizing any of the lessons learned";
# Hermes #4484): the fight asks gbox.mercs.brain.knowledge.dispatch_plan (K's learned fields over the defaults) for its
# target's class, distance and weapon, and uses a learned field only at K_MIN_CONF and K_MIN_SAMPLES: the aim height
# (in place of CHEST_H), and the range where that class's shots do the most (such a Majini costs K_RANGE_PREF less as a
# target). Fire mode: the database has not learned one here (the default, held). Plans are cached per class, 2 m band
# and weapon for K_CACHE_S. Round counters k_aim_ticks / k_range_picks; stats k_plan says what the last plan carried.
K_PLAN, K_MIN_CONF, K_MIN_SAMPLES, K_CACHE_S, K_RANGE_PREF = True, 0.6, 30, 1.0, 0.85
K_COUNTERS = ("k_aim_ticks", "k_range_picks")
WIGGLE = (("lleft",), ("lright",))       # "Break free": the left stick shaken (the prompt's icon)
MASH = (("a",), ())                      # dying: "Resuscitate", A mashed (the prompt's icon)
# Survival (operator 2026-10-26, the first MercMode turn: 5 deaths in 6 rounds, usually swarmed).
# Healing, the PS3 bot's rules (re5_ps3._heal / _heal_safe): under HEAL_AT of his health, with no Majini within
# HEAL_SAFE_R, or anyway under HEAL_CRITICAL; the item comes up from its D-pad quick slot and HEAL_USE_KEY uses it (the
# PS3's Square by position), confirmed by its count falling or his health rising, then the gun goes back up.
HEAL_IDS = frozenset({0x304, 0x305, 0x307, 0x309})   # First Aid Spray, green herb, the mixed herbs (red alone: no)
HEAL_AT, HEAL_CRITICAL, HEAL_SAFE_R, HEAL_GAIN = 0.4, 0.25, 400.0, 50
HEAL_USE_KEY = "y"                       # the game's own Type D screen leaves Y unassigned, and by position it is the PS3
                                         # manual's Square, "use recovery item" (X = Triangle inventory, A = Circle partner
                                         # action, B = Cross run: docs/evidence/switch-citron/re5-switch-controls-type-d.jpg)
HEAL_ENABLED = True                      # on (2026-10-27): watch heal_failures against heals in the live telemetry
HEAL_USE_EVERY_S, HEAL_ATTEMPT_S, HEAL_RETRY_S, EQUIP_ACK_S = 0.35, 4.0, 1.0, 1.0
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}   # the inventory grid's D-pad positions (the PS3's)
KNIVES = frozenset({0x01, 0x0E, 0x14, 0x23, 0x24})        # WP01 / WP0E / WP14 / WP23 / WP24 KNIFE_*: never the gun
# Thrown or placed, never the gun: WP06 GRENADE_NORMAL, WP07 GRENADE_FIRE, WP08 GRENADE_FLASH, WP0A MINE_B (the
# proximity bomb). With one in hand ZL alone places or throws it (live 2026-10-27: ZL with the bomb in hand set one down
# at his feet, and held, another every 1.25 s; its blast took 700 of his 1000 at 3.8 m), so the fight never raises one:
# the gun comes back first (Bot._gun_back)
THROWN = frozenset({0x06, 0x07, 0x08, 0x0A})
GUN_BACK_GAP_S = 0.6                     # between D-pad taps for the gun (a neutral pad before each)
# The proximity bombs on the ground (live 2026-10-27, private Citron): each placed bomb is a unit of class uWp0a on
# sUnit's move line 11, its position at +0x60 (E_POS), ~57 cm ahead of his feet; it leaves the line when it goes off.
# Two more uWp0a units (the stack's own) sit elsewhere all round: a placed bomb is a NEW one near him.
MINE_LINE, MINE_CLASS, MINE_ITEM, GROUND_MAX = 11, "uWp0a", 0x10A, 64
# A ring: Majini whose bearings leave no gap of RING_GAP, either tight (TIGHT: n within r) or, hurt (under HURT of his
# health), RING_N within RING_R: run out through the widest gap (the left stick + B, Type D's own "Run") for ESCAPE_S,
# at most every ESCAPE_GAP_S and ESCAPES_MAX times a round. Live 2026-10-27: 3 within 3 m at any health escaped up to 13
# times a round (a completed round of 9 kills): the rapid fire clears a loose crowd better than running from it. Then
# (4+ within 2.5 m or 3+ within 1.8 m, 6 a round): 0.11 deaths a round, but escapes near the cap and kills sliding late
# in the turn (8-15): now only 4+ within 2.5 m, or hurt, and 4 a round.
RING_R, RING_N, RING_GAP = 300.0, 3, math.radians(150)
TIGHT = ((4, 250.0),)
HURT = 0.6
ESCAPE_S, ESCAPE_GAP_S, ESCAPES_MAX = 1.2, 4.0, 4
RUN = ("b", "lup")
HUNT_R = 1200.0                          # the "hunt" directive: closer than this the fight takes over, farther he walks
# A front crowd (FRONT_N within FRONT_R, inside FRONT_CONE of his facing): a burst of BURST_S, then the gun down and
# BACKOFF_S of backing up (he cannot move while aiming), then the next burst (the rapid fire makes the burst count).
FRONT_N, FRONT_R, FRONT_CONE, BURST_S = 2, 220.0, math.radians(60), 0.8
# Rain fire (operator 2026-10-27: "the bot needs to raise their weapon and rain fire. I need them unloading with the
# gidra hooks"): the gun stays up and the trigger down whenever a Majini is in front. The live look (03:13-03:16, stats
# look, 350 decisions) had the trigger down 4 % of the round. After almost every pull the laser read down for a tick in
# the shot's motion (29), and the bot stopped firing to wait for it (25 times) or let the gun go (17 of 24 reraises at
# motion 29). 49 body turns and 46 unaims were for Majini 0.8 m away (median; turns of 19 deg, inside his body's width
# that close), half the unaims on a ray of 0.2-0.6 m (the dot on the Majini at the muzzle), and back-offs took 15 %.
MOTION_AIM = frozenset({22, 26, 29})     # the gun coming up, aimed, a shot: the gun is up even when the laser reads down
FLICKER_S = 0.6                          # the last ray stands in this long while the motion byte says the gun is up ...
LASER_STUCK_S = 2.0                      # ... and the gun is raised again after this long without a laser, whatever it says
RAISE_WIDTH = 1.25                       # the gun comes up once he is inside this many body half-widths (close up: wide)
POINT_BLANK_RAY, POINT_BLANK_R = 60.0, 150.0   # a ray this short with him this near in front: the dot is on him
SWITCH_ERR = math.radians(20)            # the aim far off the target: a Majini this near the ray is taken instead
GRAB_THREAT_R = 120.0                    # one this near, not in front, is turned to before the ones in front
CLOSE_BACKOFF, BURST_BACKOFF, HEALTHY_ESCAPES = False, False, False   # no back-offs, no bursts cut short; escapes hurt only
# Long shots with care (operator 2026-10-27: "raining fire ... with the aimbot improving allowing them to fire with great
# distance and precision if the opportunity allows"). Live 04:00-04:13 (rain fire): 27 pulls at Majini 8-22 m hit 16; the
# misses' yaw was under 1.3 deg, most of them pulls that ended within 0.1-0.4 s, the dot swept across him; and aiming
# began 15+ deg off in pitch for 88 of 149 s, the stick pulsed a tick on, a tick off inside FINE (about 2 deg a pulse,
# wider than a far Majini: he is 1-2 deg across at 15-20 m). Now, with nobody within LONG_CLEAR_R and him past LONG_R:
#   * the stick inside FINE pulses one tick in PULSE_N (2 when the error is over twice his window, 3 over it, 4 inside),
#     so the dot creeps onto him instead of jumping across;
#   * the first pull waits for SETTLE_TICKS ticks on him in a row (a dot that sweeps across never pulls);
#   * once firing, the trigger stays down while the dot stays on him (the rapid fire does the rest).
LONG_R, LONG_CLEAR_R, SETTLE_TICKS = 800.0, 400.0, 2
PULSE_N = (2, 3, 4)
DEAD_WAIT_S = 2.5                        # "You Are Dead - Continue?" comes up after the death animation
HANG_S = 6.0
TALLY_MIN_S, TALLY_STILL_S, TALLY_MAX_S, TALLY_GAP_S = 2.0, 1.0, 15.0, 5.0   # result_ready (the PS3 driver's rule)
# "Look at the bot" (gbox.mercs.bot_look; operator 2026-10-27: "From the diagnostics data per match, you should be able to
# see shots, misfires, aimbot commands ... where the aimbot is going wrong and be able to fix it"): stats look (the last
# trigger pulls and what they did, the decisions and why, the idle streak among foes, the walls shot) and the aim's
# round counters below, whose per-round amounts the engine records (Driver.round_counters: round_<key>).
#   t_<doing>        seconds spent on each decision (DOINGS): fire (ZR held on him), aim (the gun up, steering), raise
#                    (the gun coming up), turn / unaim / quick_turn (the body turning, the gun down), the survival ones
#   pulls_hit        trigger pulls that took a Majini's health within HIT_S
#   pulls_dot_miss   pulls with the dot on a Majini (head / body) that took no health: "misses with the dot on"
#   pulls_ray_miss   pulls on a ray running through him (the dot behind him) that took no health
#   pulls_blind      pulls without a target in the line (the laserless heading aim)
#   pulls_short      pulls shorter than PULL_SHORT_S (the aim flickering on and off him)
#   pulls_slipped    pulls that ended with the aim sliding off a living target (not the gun going down)
#   drops_mid_burst  living targets left for another while the trigger was held (a new pull starts on the new one)
#   first_pull_s/_n  seconds from the gun's raise to its first pull, summed / how many raises fired
#   t_turn_foe_front seconds spent turning the body while another Majini stood in front within reach
LOOK_FOE_R, LOOK_MOVE_CM_S, LOOK_PUBLISH_S, LOOK_STEP_MAX_S = 400.0, 40.0, 0.25, 0.25
RAY_RANGE_CM, FLOOR_DY, PULL_SHORT_S = 4900.0, 25.0, 0.2
DOINGS = ("fire", "aim", "raise", "reraise", "restale", "turn", "unaim", "quick_turn", "backoff", "burst_backoff",
          "escape", "heal", "held", "reload", "walk", "no_foes", "dead", "reposition", "mine", "rearm", "sweep",
          "relocate", "prompt", "flash")
# Proximity bombs left behind (re5_switch_mines: one every MINE_EVERY_S, operator 2026-10-27); only with the bomb in the
# inventory (re5_switch_mods.mine_loadout gives Chris (BSAA) the stack). gun_backs: the gun back with a throwable in hand
MINES, MINE_EVERY_S = True, 9.0
MINE_COUNTERS = ("mines_placed", "mine_attempts", "mine_unconfirmed", "mine_retreats_completed", "mine_equip_failures",
                 "mines_gone", "mine_clear_runs", "mine_blasts", "mine_kills", "mine_blast_hp_loss", "gun_backs")
# Flash grenades when overwhelmed (re5_switch_nades; operator 2026-10-27 21:0x / 21:1x: "throw flash grenades and then
# drop mines and leave the area"): the flash, a bomb at his heels once clear of them, out toward open ground or the next
# statue, the gun back; re5_switch_mods.flash_loadout gives every loadout the flash on a D-pad grid
NADES = True
# The fight is the RE5 PS3 combat core's (re5_switch_brain.Fighter, operator 2026-10-27: "I assume the bot will get the
# same mind that we trained on the ps5"); False: the Switch's own fight below (_decide), kept until the PS3 core has
# proven itself in MercMode turns
PS3_BRAIN = False
BRAIN_COUNTERS = ("misses", "headshots", "miss_short", "miss_past", "miss_beside", "miss_moved", "threat_blasts",
                  "laser_rejected", "front_first", "blocked_switches")
AIM_COUNTERS = ("pulls_hit", "pulls_dot_miss", "pulls_ray_miss", "pulls_blind", "pulls_short", "pulls_slipped",
                "drops_mid_burst", "first_pull_n", "first_pull_s", "t_turn_foe_front")
SURVIVAL = ("heal", "escape", "held", "backoff", "burst_backoff", "reload")
# The enemy knowledge database (gbox.mercs.enemy_db, through gbox.mercs.brain.knowledge): every resolved pull is a
# record_shot (his class, distance, the weapon, where the dot sat on him, hit / kill / miss and the health it took), every
# health loss a record_damage (the nearest Majini, or the one holding him, and how: "grab" / "hold" / "melee"), and the
# live Majini within K_OBSERVE_M go to observe about K_OBSERVE_HZ times a second (his exposure: the danger it learns)
K_OBSERVE_HZ, K_OBSERVE_M = 10.0, 15.0


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
    except (ValueError, OSError, OverflowError, struct.error, UnicodeDecodeError):
        return None


def enemy_class(m, e) -> str | None:
    """His class name (uEm10 / uEm11 Majini, uEm21 ... : the enemy knowledge's class key), one vtable read a tick; each
    vtable named once (class_name) and remembered."""
    try:
        vt = u64(m, e)
    except (ValueError, OSError, struct.error):
        return None
    if vt not in _CLASSES:
        if len(_CLASSES) > 256:
            _CLASSES.clear()
        _CLASSES[vt] = class_name(m, e)
    return _CLASSES[vt]


def ground_mines(m, base: int) -> list:
    """The uWp0a units on sUnit's move line MINE_LINE: [{"ptr", "pos"}] (each vtable named once: enemy_class)."""
    out: list = []
    try:
        su = u64(m, base + S_UNIT)
        u = u64(m, su + UNIT_LINES + LINE_STRIDE * MINE_LINE) if ptr_ok(su) else 0
    except (ValueError, OSError, struct.error):
        return out
    n = 0
    while ptr_ok(u) and n < GROUND_MAX:
        if enemy_class(m, u) == MINE_CLASS:
            try:
                pos = struct.unpack("<3f", m.rd(u + E_POS, 12))
                if all(math.isfinite(v) for v in pos):
                    out.append({"ptr": u, "pos": pos})
            except (ValueError, OSError, struct.error):
                pass
        try:
            u, n = u64(m, u + UNIT_NEXT), n + 1
        except (ValueError, OSError, struct.error):
            break
    return out


def heading_of(q) -> float:
    return wrap(2.0 * math.atan2(q[1], q[3]))


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


_UNIT_CENSUS = {"at": -1e9, "n": None}
_BONUS_SCAN = {"at": -1e9, "list": None, "line": None, "full_at": -1e9}


def time_bonuses(m, base: int, now: float | None = None):
    """The hourglass statues standing (uOm0100, vtable main+BONUS_VT): [{"ptr", "pos", "secs"}], read at most every
    BONUS_SCAN_S - their own line only, every line every 10 s (where they live is learned)."""
    now = time.monotonic() if now is None else now
    if now - _BONUS_SCAN["at"] < BONUS_SCAN_S:
        return _BONUS_SCAN["list"]
    _BONUS_SCAN["at"] = now
    out, found_line = [], None
    try:
        su = u64(m, base + S_UNIT)
        if not ptr_ok(su):
            return None
        vt = base + BONUS_VT
        for line in range(N_LINES):                      # every line each time (a one-line scan lost some: 16:59)
            u, k = u64(m, su + UNIT_LINES + LINE_STRIDE * line), 0
            while ptr_ok(u) and k < 1024:
                if u64(m, u) == vt:
                    pos = struct.unpack("<3f", m.rd(u + E_POS, 12))
                    secs = struct.unpack("<h", m.rd(u + E_HP, 2))[0]
                    if all(math.isfinite(v) for v in pos):
                        out.append({"ptr": u, "pos": pos, "secs": secs})
                        found_line = line
                u, k = u64(m, u + UNIT_NEXT), k + 1
    except (ValueError, OSError, struct.error):
        return _BONUS_SCAN["list"]
    if found_line is not None:
        _BONUS_SCAN["line"] = found_line
    _BONUS_SCAN["list"] = out
    return out


def unit_enemies_alive(m, base: int, now: float | None = None):
    """The game's own count: uEm units alive on sUnit's enemy line (ENEMY_LINE), read at most every CENSUS_S."""
    now = time.monotonic() if now is None else now
    if now - _UNIT_CENSUS["at"] < CENSUS_S:
        return _UNIT_CENSUS["n"]
    _UNIT_CENSUS["at"] = now
    n = None
    try:
        su = u64(m, base + S_UNIT)
        if ptr_ok(su):
            u, k, n = u64(m, su + UNIT_LINES + LINE_STRIDE * ENEMY_LINE), 0, 0
            while ptr_ok(u) and k < 256:
                if (enemy_class(m, u) or "").startswith("uEm") and struct.unpack("<h", m.rd(u + E_HP, 2))[0] > 0:
                    n += 1
                u, k = u64(m, u + UNIT_NEXT), k + 1
    except (ValueError, OSError, struct.error):
        n = None
    _UNIT_CENSUS["n"] = n
    return n


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


def inventory(m, player: int) -> list:
    """The player's inventory slots holding something: [{slot, addr, id, type, item, rounds, cap, grid, hand}]."""
    try:
        raw = m.rd(player + P_INV, INV_SLOT * INV_SLOTS)
    except (ValueError, OSError):
        return []
    out = []
    for k in range(INV_SLOTS):
        o = INV_SLOT * k
        idw = struct.unpack_from("<I", raw, o + INV_ID)[0]
        if idw in EMPTY_IDS or idw > 0xFFFF:
            continue
        rounds, cap = struct.unpack_from("<ii", raw, o + INV_ROUNDS)
        grid, hand = struct.unpack_from("<ii", raw, o + INV_GRID)
        out.append({"slot": k, "addr": player + P_INV + o, "id": idw, "type": (idw >> 8) & 0xF, "item": idw & 0xFF,
                    "rounds": rounds, "cap": cap, "grid": grid, "hand": hand == 1})
    return out


def snapshot(m) -> dict:
    """The round from RAM: the player, the live enemies and the Mercenaries counters (None where a pointer is not)."""
    snap: dict = {"player": None, "enemies": [], "timer": None, "timer_start": None, "score": None, "kills": None,
                  "combo": None, "combo_timer": None, "max_combo": None, "mercenaries_phase": None}
    base = module_base(m)
    if base is None:
        return snap
    snap["module_base"] = base
    sp = u64(m, base + S_PLAYER)
    index = player_index(m)
    coop = index != 0 or bool(getattr(m, "mercs_coop", False))    # split screen: this player's own pointers
    if not coop:
        p = u64(m, sp + P_FIRST) if ptr_ok(sp) else 0
    else:
        p = player_pointer(m, sp, index) if ptr_ok(sp) and index is not None else 0
        snap["player_index"] = index
    if ptr_ok(p):
        try:
            pos = struct.unpack("<3f", m.rd(p + P_POS, 12))
            rot = struct.unpack("<4f", m.rd(p + P_ROT, 16))
            hp, hp_max = struct.unpack("<hh", m.rd(p + P_HP, 4))
            aim_pitch = struct.unpack("<f", m.rd(p + P_AIM_PITCH, 4))[0]
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max,
                              "motion": m.rd(p + P_MOTION, 1)[0],
                              "aim_pitch": aim_pitch if math.isfinite(aim_pitch) and abs(aim_pitch) < 2.0 else None}
        except (ValueError, OSError):
            snap["player"] = None
        if snap["player"]:
            snap["laser"] = own_laser(m, p, index) if coop else laser(m, base)
            snap["inventory"] = inventory(m, p)
            if AIM_LOCK:                                 # the camera pitch and heading the aim lock writes
                snap["aim_cam"] = re5_switch_aim.aim_state(m, base, p)
            if PROMPTS and prompt_table_ok(m, base):     # the game's own prompt (re5_switch_prompt): None when none
                snap["prompt"] = re5_switch_prompt.selected_prompt(m, base, p, index or 0)
                snap["prompt_read"] = True
            if any(s["id"] == MINE_ITEM for s in snap["inventory"]):   # the bombs on the ground (re5_switch_mines)
                snap["ground_mines"] = ground_mines(m, base)
            if snap["player"]["hp"] <= 0:                   # dead: "Continue?" and its cursor, once it is up
                over = ui_units(m, base).get("uIdGameover00")
                try:
                    snap["continue_cursor"] = _i32(m, over + CONTINUE_CURSOR) if over else None
                except (ValueError, OSError):
                    snap["continue_cursor"] = None
    snap["unit_enemies_alive"] = unit_enemies_alive(m, base)
    snap["bonuses"] = time_bonuses(m, base)
    se = u64(m, base + S_ENEMY)
    ppos = (snap.get("player") or {}).get("pos")
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
                act = None                               # his motion and action flags, near him only
                if ppos is not None and hp > 0 and math.hypot(pos[0] - ppos[0], pos[2] - ppos[2]) <= WINDUP_READ_R:
                    try:
                        raw = m.rd(e + E_MOTION, E_ACT - E_MOTION + 1)
                        act = (raw[0], raw[E_ACT - E_MOTION])
                    except (ValueError, OSError):
                        act = None
                snap["enemies"].append({"slot": slot, "ptr": e, "pos": pos, "hp": hp, "hp_max": hp_max,
                                        "class": enemy_class(m, e), "motion": act[0] if act else None,
                                        "act": act[1] if act else None})
    gs = game_sys(m, base)
    if ptr_ok(gs):
        raw = m.rd(gs + GS_PHASE, GS_SCORE + 4 - GS_PHASE)
        at = lambda off, fmt: struct.unpack_from(fmt, raw, off - GS_PHASE)[0]
        snap.update(mercenaries_phase=at(GS_PHASE, "<i"), timer=round(at(GS_TIMER, "<f"), 2),
                    timer_start=at(GS_START, "<f"), kills=at(GS_KILLS, "<i"), combo=at(GS_COMBO, "<i"),
                    combo_timer=round(at(GS_COMBO_T, "<f"), 2), max_combo=at(GS_MAX_COMBO, "<i"),
                    score=at(GS_SCORE, "<i"))
        if coop and _i32(m, gs + GS_PLAYERS) == PLAYERS_SPLIT:
            snap["scoring_players"] = 2                     # a team round: the score is both players'
    return snap


_PROMPT_TABLE: dict = {}                 # main base -> its key table is this reader's (re5_switch_prompt.table_ok)


def prompt_table_ok(m, base: int) -> bool:
    """re5_switch_prompt's key table check, once a boot (main's base)."""
    if base not in _PROMPT_TABLE:
        if len(_PROMPT_TABLE) > 16:
            _PROMPT_TABLE.clear()
        _PROMPT_TABLE[base] = re5_switch_prompt.table_ok(m, base)
    return _PROMPT_TABLE[base]


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
            where, cursor, target = "select_player", _i32(m, ui["uIdStartUp22"] + PLAYER_CURSOR), player_target()
        elif "uIdStartUp21" in ui:
            where, cursor, target = "select_stage", _i32(m, ui["uIdStartUp21"] + MENU_CURSOR), stage_target()
        elif "uIdStartUp29" in ui:
            u = ui["uIdStartUp29"]
            if _i32(m, u + MENU_SUB) == 1:
                where, cursor, target = "mercs_mode", _i32(m, u + MODE_CURSOR), mode_target(m)
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
    if CYCLE and where in ("select_stage", "select_player") and isinstance(scr.get("cursor"), int):
        c = cycle()
        if c.where != where:
            c.where, c.presses = where, 0
        if c.presses >= CYCLE_MAX_PRESSES:
            return "a"                                      # the target not reached (a locked entry): this one
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
    """The menus' press went in: the stage cycle counts the presses on a select and keeps what A confirmed there."""
    where = scr.get("where")
    if not CYCLE or where not in ("select_stage", "select_player") or not isinstance(scr.get("cursor"), int):
        return None
    c = cycle()
    if c.where != where:
        c.where, c.presses = where, 0
    c.presses += 1
    if key == "a":
        c.confirmed["stage" if where == "select_stage" else "character"] = scr["cursor"]
        c.where, c.presses = None, 0
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

    def __init__(self, stats: dict | None = None, clock=time.monotonic, release=None, m=None, learn_dir=None,
                 lessons=None):
        self.stats = stats if stats is not None else {}
        self.clock = clock
        self.release = release                  # the driver's: the live mods' state put back when the bot stops
        for k in ("shots", "hits", "turns", "quick_turns", "backoffs", "wiggles", "holds", "laserless", "reraise",
                  "restale", "heal_starts", "heals", "heal_failures", "escapes", "burst_backoffs"):
            self.stats.setdefault(k, 0)
        self.target = None
        self.aim_since = None
        self.fire_down = False
        self.yaw_pulse = self.pitch_pulse = self.turn_pulse = 0
        self.on_key, self.on_ticks = None, 0      # the target the dot has sat on, for how many ticks in a row
        self.ray_key, self.ray_since = None, 0.0
        self.backoff_until = self.backoff_ready = 0.0
        self.quick, self.quick_at = 0, -1e9      # the quick turn's step (1 stick back, 2 + B, 3 let go), its B press
        self.target_at = -1e9
        self.prev_target, self.switch_at = None, -1e9   # the one he left and when (FLIP_S)
        self.dot_other = (None, 0)                # another Majini under the dot, for how many ticks (DOT_SWITCH_TICKS)
        self.unaim_since = None                   # the aim far off him since (UNAIM_HOLD_S)
        self.turning = False                      # turning with the gun down (RERAISE_FRAC)
        self._yaw_dir, self._yaw_dir_at = 0, -1e9   # the yaw stick's last direction (aim_reversals)
        self._sticks: set = set()                 # the right stick's keys held last tick (stick_onsets)
        for k in MOTION_COUNTERS + K_COUNTERS + LEVEL_COUNTERS + COMBO_COUNTERS + THREAT_COUNTERS:
            self.stats.setdefault(k, 0)
        self._appr, self._threat_now = {}, False         # each Majini's (distance, when, closing cm/s); a threat near
        self._ray_pitch, self._lower_pitch, self._first_ray = None, None, False   # the aim's pitch: now, before the raise
        self._ap_now = None                              # this tick's P_AIM_PITCH (the pitch-up details)
        self._crowded = False                            # a Majini on his level within RAMPAGE_R this tick (NEAR_FOCUS)
        self._m, self._ram, self._lock_t = m, None, None  # the session (the aim lock's writer, made when first used)
        self._lock_last, self._lock_score, self._lock_off = None, [0, 0], False   # did the writes hold (next frame)
        self._wu, self._windup_e, self._grab_at, self._was_held = {}, None, -1e9, False   # the wind-ups (WINDUP)
        self._sky, self._pu_detail = False, None         # the sky guard on last tick; this tick's pitch-up details
        self._prate, self._pray, self._first_ray_at = None, None, None   # pitch rate (rad/s); last (pitch, len, t)
        self._pitch_dir, self._pitch_dir_at = 0, -1e9
        self._dot_prev, self._dot_same, self._rot_prev = None, 0, None   # the frozen-dot watch
        self._wall_since, self._away_since, self._behind_on, self._fault_t = None, None, False, None
        self._wall_t = None                              # the last aimed tick (wall_aim_s)
        self._long_marks = {}                            # far Majini fired on: key -> when (long_shot_kills)
        self._first_check, self._raise_is_reroll, self._reroll_next, self._close_sky_since = False, False, False, None
        self._ramp = None                                # the rampage: {"since", "main", "kills0", "retarget_at"}
        self._calm = {"h": (0, -1e9), "v": (0, -1e9), "budget": 0.0, "t": None, "rot": None, "spin": [0.0, 0.0]}
        self._bonus_known, self._bonus_block, self._bonus = {}, {}, None   # statues seen; given up; the run under way
        self._bonus_seen_round, self._round_t0 = False, None
        self._timer_prev = None
        self._ramp_t, self._swap_at, self._restore = None, -1e9, None
        self._whip = {"dir": 0, "amount": 0.0, "end": -1e9, "last_big": None, "rot": None}
        self._pur, self._pur_block, self._pur_end_at, self._pur_credit = None, {}, -1e9, True   # the pursuit
        self._kills_prev = None
        self._sweep_st, self._sweep_last, self._sweep_t = None, None, None   # the turret sweep
        self._gov = (None, None)                         # (heading, when) at the last tick: the heading governor
        self._pr = None                                  # the prompt being answered (PROMPTS): its button, since, presses
        self._pr_lat: list = []                          # seconds from shown to the first press
        self._goal_dy = None                             # the statue / pursued Majini's height off his level (traverse)
        self._level_watch = None                         # (his height, until) after a traverse prompt: level_changes
        self.stats.setdefault("traverse_spots", "")
        self.stats.setdefault("prompt_latency_s", 0)
        self._clears: list = []                          # this round's sweep seconds to clear the circle
        self._dwell = None                               # {"anchor", "since"}: the spot he stands at (keep moving)
        self._dwells: list = []                          # this round's finished dwells (seconds)
        self._reloc, self._reloc_ready, self._reloc_due, self._kite_side = None, -1e9, False, 1
        self._trail, self._dead_ends = [], []           # his own trail (open, reachable); runs that stuck
        self._hp_track, self._hit_at = None, -1e9       # (player, health) last tick, the last fall: hits_taken
        self._cam = {"off": False, "down_since": None, "ap0": None, "on": False}   # the aim pitch guard
        for k in ("avg_dwell_s", "max_dwell_s", "crowd_cleared_s", "hits_taken"):
            self.stats.setdefault(k, 0)
        self._crowd_until, self._crowd_ready, self._crowd_keys = -1e9, 0.0, ()
        self._walls: list = []                           # the round's walls: (x, z, heading) (WALL_GOV)
        self._wall_hist: list = []                       # (when, position) while the stick pushes forward
        self._wall_push, self._wall_rec, self._wgov_t = None, None, None
        self.stats.setdefault("crowd_max", 0)
        for kind in FAULT_KINDS:
            self.stats.setdefault("ex_" + kind, "")
        self._combo_prev, self._combo_window = 0, None   # the last combo count and its window (combo_breaks / lapses)
        self._plans: dict = {}                    # (class, 2 m band, weapon) -> (at, plan): K's plans, cached
        self._item = None                         # the weapon in hand this tick (K's plans are per weapon)
        self.still, self.move_at, self.break_until, self.in_hold = None, -1e9, -1e9, False
        self.wiggle = 0
        self.hp_seen: list = []
        self.hp_prev: dict = {}
        self.fire_at = None                     # the last tick ZR was held on him
        self._threats: list = []
        self.dead_since, self.dead_taps = None, 0
        self.died, self.continued = False, None   # this round ended in a death / how "Continue?" was answered
        self._round_started = None                # the engine's round marker: set once (a replay's new round is the
                                                  # engine's own: the death closed the last one's evidence)
        self.healing, self.heal_at = None, -1e9   # a heal under way / when the last one ended
        self.escape, self.escape_at = None, -1e9  # (the bearing out, until) / when the last escape began
        self.round_escapes = 0                    # escapes this round (ESCAPES_MAX)
        self.trigger_since = None                 # the burst's first pull since the gun came up (kept across the
                                                  # targets it drops; the gun going down ends the burst)
        for k in AIM_COUNTERS + tuple("t_" + d for d in DOINGS):
            self.stats.setdefault(k, 0)
        self.look = BotLook(epoch=clock)          # stats look: the last pulls and decisions ("look at the bot")
        self.doing, self.why, self._now = "none", "", None   # this tick's decision (DOINGS) and why
        self._tick_t = self._look_at = None
        self._ran = ("none", False)               # (the last decision, turning with a foe in front): charged next tick
        self._acc = {k: float(self.stats.get(k) or 0) for k in tuple("t_" + d for d in DOINGS) + ("t_turn_foe_front",)}
        self._look_pub = (-1, -math.inf)          # (look version, when) last published
        self._aimctx = None                       # the aim as the trigger was pulled (_decide)
        self._pulls: list = []                    # pulls whose hit window is still open
        self._raise_t = None                      # when the gun went up for the pulls to come (first_pull_s)
        self._k_obs_at = None                     # the last observe() to the enemy knowledge database
        self._hp_last = None                      # (player, health) at the last tick: a fall is a record_damage
        self.ray_seen, self.last_ray = None, None # the last live laser ray and when (FLICKER_S)
        self.stats.setdefault("flicker_s", 0)
        self.fighter = None                       # the PS3 combat core (PS3_BRAIN): its accounting and its fight
        self.commands = None                      # the operator's instant commands (gbox.mercs.directives.Reader)
        self.blocked: dict = {}                   # target -> until: "repetitive" drops the one he kept at
        self.mode = None                          # a standing directive: "fight" / "hunt" / "score"
        from .re5_switch_mines import Mines
        self.mines = Mines(self.stats, every_s=MINE_EVERY_S) if MINES else None
        self.nades = re5_switch_nades.Nades(self.stats) if NADES else None
        self._gun_back_at = -1e9                  # the last D-pad tap for the gun with a throwable in hand
        self.stats.setdefault("gun_backs", 0)
        self._fire_t = None                       # the last tick the fighter held the trigger (trigger_s)
        if PS3_BRAIN:
            from .re5_switch_brain import Fighter
            self.fighter = Fighter(m, self.stats, clock, look=self.look, learn_dir=learn_dir, lessons=lessons)
            for k in BRAIN_COUNTERS:
                self.stats.setdefault(k, 0)

    # --- what to fight -----------------------------------------------------------------------------------------------
    @staticmethod
    def _cost(p, e) -> float:
        px, py, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        level = 1.0 + (LEVEL_COST * min(abs(e["pos"][1] - py), MAX_DY) / MAX_DY if piece(SMOOTH_LEVEL) else 0.0)
        return d * (1.0 + abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) / math.pi) * level

    @staticmethod
    def raise_tol(dist: float) -> float:
        """How far off his bearing the gun comes up: BODY_AIM_TOL, or close up his body's angle (RAISE_WIDTH half-widths:
        0.8 m away that is 29 deg, where the body turn used to wait for 12)."""
        return max(BODY_AIM_TOL, math.atan2(BODY_R * RAISE_WIDTH, max(dist, 1.0)))

    def _aim_h(self, tgt, dist, now) -> float:
        """The height on him to aim at: K's learned aim for his class at this distance and weapon (sure), else CHEST_H;
        kept inside his body (KNEE_H .. HEAD_H). Within GRAB_THREAT_R (a grab or a lunge: the Switch reads no enemy
        state) always CHEST_H, the bot's own rule."""
        if dist < GRAB_THREAT_R:
            return CHEST_H                                   # at grabbing / lunging range: the old rule, whatever K says
        plan = self._plan(tgt, dist, self._item, now)
        if self._sure(plan, "aim_offset"):
            self.stats["k_aim_ticks"] += 1
            self.stats["k_plan"] = {"class": tgt.get("class"), "dist_m": round(dist / 100, 1),
                                    "aim_h_cm": round(plan.aim_offset[1]), "zone": plan.zone,
                                    "fields": [f for f, _ in plan.field_confidence],
                                    "confidence": dict(plan.field_confidence)}
            return max(KNEE_H, min(HEAD_H, float(plan.aim_offset[1])))
        return CHEST_H

    def _kcost(self, p, e, now) -> float:
        """_cost, K_RANGE_PREF less for a Majini standing where K says his class's shots do the most (learned, sure)."""
        c = self._cost(p, e)
        if not K_PLAN or not e.get("class"):
            return c
        d = math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
        plan = self._plan(e, d, self._item, now)
        if self._sure(plan, "range_cm") and plan.range_cm and plan.range_cm[0] <= d <= plan.range_cm[1]:
            return c * K_RANGE_PREF
        return c

    def _example(self, kind, p, now, detail) -> None:
        """The first EXAMPLES of a fault in the round, readable: round time, his position and heading, the detail, the
        decision."""
        key = "ex_" + kind
        cur = self.stats.get(key) or ""
        if cur and cur.count(" | ") + 1 >= EXAMPLES:
            return
        t = now - self._round_t0 if self._round_t0 is not None else now
        x, y, z = p["pos"]
        line = (f"{t:.1f} s: Chris ({x:.0f},{y:.0f},{z:.0f}) heading {math.degrees(p.get('rot') or 0.0):.0f}; {detail}; "
                f"{self.doing}: {self.why}")
        self.stats[key] = f"{cur} | {line}" if cur else line

    def _fault_tick(self, p, live, flat, snap, now) -> None:
        """Every tick: crowd_max, the seconds a Majini stands close behind him while he aims at another, the far
        Majini fired on that died (long_shot_kills)."""
        dt = 0.0 if self._fault_t is None else max(0.0, min(now - self._fault_t, LOOK_STEP_MAX_S))
        self._fault_t = now
        px, py, pz = p["pos"]
        self.stats["crowd_max"] = max(self.stats.get("crowd_max") or 0, sum(1 for e in live if flat(e) <= 400))
        self._bonus_tick(snap, now)
        self._trail_tick(p, now)
        self._keep_moving(p, live, flat, now)
        self._watch_whips(p, now)
        self.stats["census_count"] = sum(1 for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0)
        if snap.get("unit_enemies_alive") is not None:
            self.stats["census_units"] = snap["unit_enemies_alive"]
        k = snap.get("kills")
        if type(k) is int and type(self._kills_prev) is int and k > self._kills_prev and not self._pur_credit \
                and (self._pur is not None or now - self._pur_end_at <= PURSUE_CREDIT_S):
            self.stats["pursuit_kills"] += 1
            self._pur_credit = True
        if type(k) is int:
            self._kills_prev = k
        behind = [e for e in live if flat(e) <= BEHIND_R and e.get("ptr", e.get("slot")) != self.target
                  and abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) > math.pi / 2]
        on = bool(behind) and self.aim_since is not None
        if on:
            self.stats["behind_threat_s"] = round(self.stats["behind_threat_s"] + dt, 2)
            if not self._behind_on:
                e = min(behind, key=flat)
                self._example("behind_threat", p, now, f"one {flat(e) / 100:.1f} m behind "
                                                       f"({math.degrees(wrap(heading(e['pos'][0] - px, e['pos'][2] - pz) - p['rot'])):+.0f} deg) "
                                                       f"while aiming at another")
        self._behind_on = on
        if self._long_marks:
            by = {e.get("ptr", e.get("slot")): e for e in snap.get("enemies") or ()}
            for key, t in list(self._long_marks.items()):
                e = by.get(key)
                if e is not None and (e.get("hp") or 0) <= 0:
                    self.stats["long_shot_kills"] += 1
                    del self._long_marks[key]
                elif e is None or now - t > LONG_KILL_S:
                    del self._long_marks[key]

    def _pursue(self, p, live, flat, snap, now):
        """The combo running down with nobody on his level in reach: run to the census's best (stuck: a detour)."""
        combo, window = snap.get("combo"), snap.get("combo_timer")
        running = PURSUIT and type(combo) is int and combo > 0 and isinstance(window, (int, float)) \
            and not isinstance(window, bool) and 0.0 < window <= PURSUE_S
        if not running or any(flat(e) <= COMBO_REACH for e in live) or self.aim_since is not None:
            if self._pur is not None:
                self._pur, self._pur_end_at = None, now
            return None
        px, py, pz = p["pos"]
        self._pur_block = {k: t for k, t in self._pur_block.items() if t > now}
        census = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos")
                  and e.get("ptr", e.get("slot")) not in self._pur_block]
        if not census:
            return None
        cost = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz) + PURSUE_DY_W * abs(e["pos"][1] - py)
        tgt = min(census, key=cost)
        key = tgt.get("ptr", tgt.get("slot"))
        d = math.hypot(tgt["pos"][0] - px, tgt["pos"][2] - pz)
        self._goal_dy = tgt["pos"][1] - py
        if self._pur is None or self._pur["target"] != key:
            if self._pur is None:
                self.stats["pursuits"] += 1
                self._pur_credit = False
            self._pur = {"target": key, "best": d, "best_at": now, "detours": 0, "detour_until": -1e9, "side": 1}
        pur = self._pur
        if d < pur["best"] - PURSUE_PROGRESS_CM:
            pur["best"], pur["best_at"] = d, now
        elif now - pur["best_at"] > PURSUE_STUCK_S and now >= pur["detour_until"]:
            self.stats["pursuit_stuck"] += 1             # no closer: a detour, the other side each time
            pur["detours"] += 1
            pur["side"] = -pur["side"]
            pur["detour_until"], pur["best_at"] = now + PURSUE_DETOUR_S, now + PURSUE_DETOUR_S
            if pur["detours"] > PURSUE_MAX_DETOURS:
                self._pur_block[key] = now + PURSUE_BLOCK_S
                pur["target"] = None
        off = math.radians(PURSUE_DETOUR_DEG) * pur["side"] if now < pur["detour_until"] else 0.0
        err = wrap(heading(tgt["pos"][0] - px, tgt["pos"][2] - pz) + off - p["rot"])
        self.target = key
        self.doing = "walk"
        self.why = (f"pursuit: combo {combo}, {window:.1f} s left, the best of {len(census)} at {d / 100:.1f} m "
                    f"(dy {tgt['pos'][1] - py:+.0f})" + (" - a detour" if off else ""))
        self._gun_down()
        return {"hold": ("lup", "b") + self._turn(err, TURN_TOL)}

    @staticmethod
    def _escape_keys(p, crowd) -> tuple:
        """The left stick away from the crowd (each Majini pushing by 1/d^2), in his frame: back, sideways or between."""
        px, _, pz = p["pos"]
        vx = vz = 0.0
        for e in crowd:
            dx, dz = px - e["pos"][0], pz - e["pos"][2]
            d = max(math.hypot(dx, dz), 50.0)
            vx, vz = vx + dx / (d * d), vz + dz / (d * d)
        if not (vx or vz):
            return ("ldown",)
        a = math.degrees(wrap(heading(vx, vz) - p["rot"]))   # 0 ahead, +90 his left (a larger heading), 180 behind
        options = ((0, ("lup",)), (45, ("lleft", "lup")), (90, ("lleft",)), (135, ("ldown", "lleft")),
                   (180, ("ldown",)), (-180, ("ldown",)), (-135, ("ldown", "lright")), (-90, ("lright",)),
                   (-45, ("lright", "lup")))
        return min(options, key=lambda o: abs(o[0] - a))[1]

    def _bonus_tick(self, snap, now) -> None:
        """The round's statues: each new one seen, one gone taken; the clock's jumps (time_gained); bonuses_left."""
        bonuses = snap.get("bonuses")
        t = snap.get("timer")
        if isinstance(t, (int, float)) and isinstance(self._timer_prev, (int, float)) \
                and t - self._timer_prev >= BONUS_JUMP_S:
            self.stats["time_gained"] = round(self.stats["time_gained"] + (t - self._timer_prev), 1)
        if isinstance(t, (int, float)):
            self._timer_prev = t
        if bonuses is None:
            return
        now_keys = {b["ptr"] for b in bonuses}
        for b in bonuses:
            if b["ptr"] not in self._bonus_known:
                self._bonus_known[b["ptr"]] = b
                self._bonus_seen_round = True
                self.stats["bonuses_seen"] += 1
        for key in [k for k in self._bonus_known if k not in now_keys]:
            del self._bonus_known[key]
            self.stats["bonuses_taken"] += 1
            if self._bonus is not None and self._bonus.get("ptr") == key:
                self._bonus = None
        self.stats["bonuses_left"] = len(now_keys)
        t0 = getattr(self, "_round_t0", None)
        if not now_keys and self._bonus_seen_round and t0 is not None and self.stats.get("_bonus_done_round") != t0:
            self.stats["_bonus_done_round"] = t0
            self.stats["bonus_time_s"] = round(now - t0, 1)

    def _go_bonus(self, p, live, flat, snap, now):
        """Phase 1 (operator 16:52: "running from Checkpoint to Checkpoint, grabbing the time bonuses ... the only way to
        grab a time bonus is to walk up to it and melee it"): the next statue - run to it, face it, the knife (L + ZR)
        until it breaks; only a Majini within BONUS_FIGHT_R (in the way, about to grab) is fought first."""
        bonuses = snap.get("bonuses") or ()
        px, py, pz = p["pos"]
        blocking = any(flat(e) <= BONUS_FIGHT_R and abs(e["pos"][1] - py) <= LEVEL_DY for e in live)
        if not BONUS or not bonuses or blocking:
            return None
        self._bonus_block = {k: t for k, t in self._bonus_block.items() if t > now}
        open_ = [b for b in bonuses if b["ptr"] not in self._bonus_block]
        if not open_:
            return None
        cost = lambda b: math.hypot(b["pos"][0] - px, b["pos"][2] - pz) + 3.0 * abs(b["pos"][1] - py)
        run = self._bonus
        b = next((x for x in open_ if run is not None and x["ptr"] == run["ptr"]), None) or min(open_, key=cost)
        if run is None or run["ptr"] != b["ptr"]:
            self.stats["bonus_runs"] += 1
            run = self._bonus = {"ptr": b["ptr"], "since": now, "knife_since": None, "retries": 0,
                                 "best": 1e9, "best_at": now, "side": 1, "detour_until": -1e9, "detours": 0}
        if self.aim_since is not None:
            self._gun_down()
        bx, by, bz = b["pos"]
        d = math.hypot(bx - px, bz - pz)
        err = wrap(heading(bx - px, bz - pz) - p["rot"])
        self._goal_dy = by - py                          # a ledge's prompt on the way is taken (PROMPTS: traverse)
        if d <= KNIFE_R and snap.get("prompt_read"):     # at it: its own prompt takes it (Y, PROMPTS); walk into it
            run["knife_since"] = run["knife_since"] or now
            if now - run["knife_since"] > KNIFE_TRY_S * (KNIFE_RETRIES + 1):
                self._bonus_block[b["ptr"]] = now + BONUS_BLOCK_S   # no prompt here: another one first
                self._bonus = None
            self.doing, self.why = "walk", f"time bonus {b.get('secs')} s at {d / 100:.1f} m: into it for its prompt"
            return {"hold": ("lup",) + self._turn(err, KNIFE_FACE)}
        if d <= KNIFE_R:                                 # at it: face it, then the knife until it breaks
            if abs(err) > KNIFE_FACE:
                self.doing, self.why = "turn", f"time bonus {b.get('secs')} s at {d / 100:.1f} m: facing it"
                run["knife_since"] = None
                return {"hold": self._turn(err)}
            run["knife_since"] = run["knife_since"] or now
            if now - run["knife_since"] > KNIFE_TRY_S:   # not broken yet: a step in, again (then another one)
                run["knife_since"], run["retries"] = None, run["retries"] + 1
                if run["retries"] > KNIFE_RETRIES:
                    self._bonus_block[b["ptr"]] = now + BONUS_BLOCK_S
                    self._bonus = None
                self.doing, self.why = "walk", "time bonus: a step closer for the knife"
                return {"hold": ("lup",)}
            swing = int((now - run["knife_since"]) / KNIFE_SWING_S) % 2 == 1
            if swing and not run.get("swung"):
                self.stats["knife_swings"] += 1
            run["swung"] = swing
            self.doing, self.why = "melee", f"time bonus {b.get('secs')} s: the knife"
            return {"hold": ("l", "zr") if swing else ("l",)}
        if d < run["best"] - 50.0:                       # on the way: run (walk the last metres), a detour when stuck
            run["best"], run["best_at"] = d, now
        elif now - run["best_at"] > BONUS_JUMP_TRY_S and not run.get("jumped") and abs(by - py) > LEVEL_DY                 and not snap.get("prompt_read"):         # (with the prompt read, Y waits for the ledge's own prompt)
            run["jumped"] = True                         # stuck at a ledge above (or below) it: the context action
            run["best_at"] = now                         # (Y: "Jump down" - the 16:24 frame on the roof - or a ladder)
            self.stats["bonus_jumps"] += 1
            self.doing, self.why = "walk", f"time bonus {d / 100:.1f} m, {by - py:+.0f} cm off his level: Y"
            return {"hold": ("y", "lup")}
        elif now - run["best_at"] > 1.5 and now >= run["detour_until"]:
            run["detours"] += 1
            run["side"] = -run["side"]
            run["detour_until"], run["best_at"] = now + 0.9, now + 0.9
            run["jumped"] = False
            self.stats["bonus_detours"] += 1
            if run["detours"] > 3:
                self._bonus_block[b["ptr"]] = now + BONUS_BLOCK_S
                self._bonus = None
        off = math.radians(70) * run["side"] if now < run["detour_until"] else 0.0
        err = wrap(heading(bx - px, bz - pz) + off - p["rot"])
        self.doing = "walk"
        self.why = (f"time bonus {b.get('secs')} s at {d / 100:.1f} m (dy {by - py:+.0f}), "
                    f"{len(open_)} left" + (" - a detour" if off else ""))
        return {"hold": (("lup", "b") if d > BONUS_WALK_R else ("lup",)) + self._turn(err, TURN_TOL)}

    def _watch_whips(self, p, now) -> None:
        """A turn of WHIP_DEG or more one way, then WHIP_BACK_DEG back within WHIP_S of its end: a whip."""
        w, rot = self._whip, p.get("rot")
        if rot is None:
            return
        if w["rot"] is None:
            w["rot"] = rot
            return
        d = math.degrees(wrap(rot - w["rot"]))
        w["rot"] = rot
        if abs(d) < 0.5:
            return
        sign = 1 if d > 0 else -1
        if sign != w["dir"]:
            if w["amount"] >= WHIP_DEG:
                w["last_big"] = (w["dir"], w["end"])     # a big turn ended at its last tick
            w["dir"], w["amount"] = sign, 0.0
        w["amount"] += abs(d)
        w["end"] = now
        big = w["last_big"]
        if big is not None and sign != big[0] and w["amount"] >= WHIP_BACK_DEG:
            if now - big[1] <= WHIP_S:
                self.stats["whips"] += 1
            w["last_big"] = None

    def _rampage_gun(self, inv):
        """The shotgun, else the magnum, on a D-pad slot: (its inventory slot, family) or (None, None)."""
        from . import re5_weapons
        best = (None, None)
        for fam in RAMPAGE_FAMILIES:
            for s_ in inv or ():
                spec = re5_weapons.WEAPONS.get(s_.get("item"))
                if s_.get("type") == 1 and s_.get("grid") in QUICK and spec is not None and spec.family == fam:
                    return s_, fam
        return best

    def _rampage(self, p, live, flat, snap, now):
        """Anyone on his level within RAMPAGE_R: the gun up, the trigger down, the nearest inside held (above)."""
        px, py, pz = p["pos"]
        dt = 0.0 if self._ramp_t is None else max(0.0, min(now - self._ramp_t, LOOK_STEP_MAX_S))
        self._ramp_t = now
        crowd = CROWD_FIRE and not RAMPAGE               # the calm crowd fire (CROWD_FIRE above); RAMPAGE: the old one
        ring = [e for e in live if flat(e) <= RAMPAGE_R and abs(e["pos"][1] - py) <= LEVEL_DY] \
            if (RAMPAGE or crowd) else []
        if crowd and self._ramp is None and len(ring) < CROWD_FIRE_N \
                and not any(flat(e) <= CROWD_FIRE_CLOSE_R for e in ring):
            ring = []                                    # not crowded yet (once on, on while anyone is within 5 m)
        inv = snap.get("inventory") or ()
        held = next((s_ for s_ in inv if s_.get("hand")), None)
        if not ring:
            if self._ramp is not None:                   # the circle is clear: the main gun back when the gun is down
                self._restore, self._ramp = self._ramp.get("main"), None
            if self._restore is not None and self.aim_since is None and held is not None \
                    and held.get("item") != self._restore and now - self._swap_at >= SWAP_GAP_S:
                back = next((s_ for s_ in inv if s_.get("item") == self._restore and s_.get("grid") in QUICK), None)
                self._swap_at = now
                if back is None:
                    self._restore = None
                    return None
                self.stats["rampage_swaps"] += 1
                self.doing, self.why = "raise", "the circle clear: the main gun back"
                return {"hold": (QUICK[back["grid"]],)}
            if held is not None and held.get("item") == self._restore:
                self._restore = None
            return None
        kills = snap.get("kills")
        if self._ramp is None:
            self._ramp = {"since": now, "main": held.get("item") if held and held.get("type") == 1 else None,
                          "kills0": kills if type(kills) is int else None, "retarget_at": -1e9}
            self._restore = None
        r = self._ramp
        self.stats["rampage_s"] = round(self.stats["rampage_s"] + dt, 2)
        if type(kills) is int and type(r["kills0"]) is int and kills > r["kills0"]:
            self.stats["rampage_kills"] += kills - r["kills0"]
            r["kills0"] = kills
        elif type(kills) is int and r["kills0"] is None:
            r["kills0"] = kills
        # the target: the one held while inside and alive; a grab-range one takes over; one change per RAMPAGE_RETARGET_S
        cur = next((e for e in ring if self.target is not None and e.get("ptr", e.get("slot")) == self.target), None)
        nearest = min(ring, key=flat)
        if crowd:                                        # the nearest in front first: one direction at a time
            front = [e for e in ring if abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) <= CROWD_FRONT]
            near_front = min(front, key=flat) if front else None
            if near_front is not None and flat(near_front) < 2.0 * flat(nearest) + 100.0:
                nearest = near_front
        tgt = cur
        wu = self._windup_e if self._windup_e is not None and any(e is self._windup_e for e in ring) else None
        if wu is not None and wu is not cur:             # winding up: him first, at once
            tgt, r["retarget_at"] = wu, now
            self.stats["windup_picks"] += 1
        elif cur is None or (flat(nearest) < GRAB_THREAT_R and flat(cur) >= GRAB_THREAT_R and nearest is not cur):
            if cur is None or now - r["retarget_at"] >= RAMPAGE_RETARGET_S:
                tgt = nearest
                r["retarget_at"] = now
        key = tgt.get("ptr", tgt.get("slot"))
        if key != self.target:
            self._set_target(key, now)
            self.target_at = now
        dist = flat(tgt)
        body_err = wrap(heading(tgt["pos"][0] - px, tgt["pos"][2] - pz) - p["rot"])
        gun, fam = self._rampage_gun(inv)
        self.stats["rampage_weapon"] = fam or (f"0x{held['item']:03x}" if held else "-")
        # attacked from behind: one decisive quick turn (the gun down for it), then up and blasting
        if QUICK_TURN and dist <= BEHIND_R and abs(body_err) > RAMPAGE_BEHIND and now - self.quick_at > QUICK_GAP_S                 and (now - self.quick_at >= QUICK_BACK_S or dist <= GRAB_THREAT_R):
            if self.aim_since is not None:
                self._gun_down()
            self.stats["behind_turns"] += 1
            self.stats["quick_turns"] += 1
            self.quick = 2
            self.doing, self.why = "quick_turn", (f"rampage: one {dist / 100:.1f} m behind "
                                                  f"({math.degrees(body_err):+.0f} deg): the quick turn")
            self.stats["idle_in_5m_s"] = round(self.stats["idle_in_5m_s"] + dt, 2)
            return {"hold": ("ldown",)}
        if self.aim_since is None:
            if gun is not None and not gun.get("hand") and now - self._swap_at >= SWAP_GAP_S:
                self._swap_at = now                      # the shotgun / magnum first (one press, the gun down)
                self.stats["rampage_swaps"] += 1
                self.stats["shotgun_swaps"] += 1
                self.doing, self.why = "raise", f"rampage: the {fam} up first"
                self.stats["idle_in_5m_s"] = round(self.stats["idle_in_5m_s"] + dt, 2)
                return {"hold": (QUICK[gun["grid"]],)}
            self.aim_since = self._raise_t = now         # up at once, no body turn first
            self.stats["raises"] += 1
            self.ray_seen = self.last_ray = None
            self._lower_pitch, self._first_ray = self._ray_pitch, True
            self._first_check, self._raise_is_reroll, self._reroll_next = False, True, False
        lz = snap.get("laser") or {}
        keys = {"zl"}
        aim_off = abs(body_err)
        weapon = f"0x{held['item']:03x}" if held else "gun"
        if lz.get("up") and lz.get("from") and lz.get("at"):
            origin, dot = tuple(lz["from"]), tuple(lz["at"])
            chest = (tgt["pos"][0], tgt["pos"][1] + CHEST_H, tgt["pos"][2])
            yaw_err, pitch_err = ray_error(origin, dot, chest)
            aim_off = abs(yaw_err)
            where = dot_on(dot, tgt["pos"])
            self._aimctx = {"target": key, "dist": dist, "bearing": body_err, "yaw_err": yaw_err, "where": where,
                            "laserless": False, "weapon": weapon, "origin": origin, "dot": dot, "py": py,
                            "class": tgt.get("class"), "foot": tuple(tgt["pos"]), "hp_max": tgt.get("hp_max"),
                            "item": held.get("item") if held else None, "shooter": tuple(p["pos"]),
                            "gate": "rampage" + (f": dot on {where}" if where else "")}
            keys |= self._yaw(yaw_err)
            if not crowd and dist >= CLOSE_PITCH_R and math.dist(origin, dot) >= STEER_RAY_CM:
                keys |= self._pitch(pitch_err)
            on = bool(where) or abs(yaw_err) <= CROWD_CONE or any(
                dot_on(dot, e["pos"]) or through(origin, dot, e["pos"]) for e in ring)
        else:
            self._aimctx = {"target": key, "dist": dist, "bearing": body_err, "yaw_err": body_err, "where": None,
                            "laserless": True, "weapon": weapon, "gate": "rampage: the gun coming up"}
            keys |= self._yaw(body_err)
            on = abs(body_err) <= CROWD_CONE and p.get("motion") in MOTION_AIM
        if dist <= POINT_BLANK_R and abs(body_err) <= self.raise_tol(dist):
            on = True                                    # point blank in front: on him
        if crowd:
            self.stats["crowd_fire_s"] = round(self.stats["crowd_fire_s"] + dt, 2)
            ap = p.get("aim_pitch")
            if ap is not None and now - self.aim_since >= READY_S:   # the aim's own pitch on a chest, never the sky
                if ap < SWEEP_PITCH_BAND[0]:
                    keys.add("rdown")
                elif ap > SWEEP_PITCH_BAND[1]:
                    keys.add("rup")
            if p.get("motion") == MOTION_SHOT:           # the shot plays at fire_rate's time scale: no stick in it
                if keys & {"rleft", "rright", "rup", "rdown"}:
                    self.stats["shot_stick_drops"] += 1
                keys -= {"rleft", "rright", "rup", "rdown"}
            if AIM_LOCK and snap.get("aim_cam"):         # the RAM aim lock (the stick only as a fallback)
                lzo = (tuple(lz["from"]), tuple(lz["at"])) if lz.get("up") and lz.get("from") and lz.get("at") \
                    else (None, None)
                keys = self._lock_aim(snap, keys, *self._lock_errors(p, snap, tgt["pos"], CHEST_H, dist, *lzo), now)
            if not on:                                   # the aim off them: turn, the trigger let go (the turn's pace)
                if self.fire_down:
                    self._trigger(False, now)
                self.stats["idle_in_5m_s"] = round(self.stats["idle_in_5m_s"] + dt, 2)
                self.doing = "aim"
                self.why = ("crowd fire: %d within %.0f m; turning to the one %.1f m away (%+.0f deg)"
                            % (len(ring), RAMPAGE_R / 100, dist / 100, math.degrees(body_err)))
                return {"hold": tuple(sorted(keys))}
        if not self.fire_down:
            self.stats["rampage_shots"] += 1
        keys |= self._trigger(True, now)                 # blasting (crowd fire: with the aim on them)
        if aim_off > OFFSCREEN_ERR:
            self.stats["offscreen_aim_s"] = round(self.stats["offscreen_aim_s"] + dt, 2)
        self.doing = "fire"
        self.why = ("%s: %d within %.0f m, the nearest %.1f m; on the one %.1f m away (%+.0f deg)"
                    % ("crowd fire" if crowd else "rampage", len(ring), RAMPAGE_R / 100, flat(nearest) / 100,
                       dist / 100, math.degrees(body_err)))
        self.stats["aim"] = f"rampage d {dist:.0f} off {math.degrees(aim_off):+.1f} keys {','.join(sorted(keys))}"
        return {"hold": tuple(sorted(keys))}

    @staticmethod
    def _winding(e) -> bool:
        """His own motion is a wind-up (WINDUP_MOTIONS) or his attack flag is up."""
        return bool(WINDUP and (e.get("motion") in WINDUP_MOTIONS or (e.get("act") or 0) & E_ATTACKING))

    def _windup_tick(self, p, live, flat, now):
        """The wind-ups within WINDUP_R on his level: counted as they start, resolved WINDUP_HIT_S later (an attack landed
        on him: hits_after_windup; else hurt by him meanwhile: windup_interrupts); the nearest one now, or None."""
        py = p["pos"][1]
        winding = [e for e in live if flat(e) <= WINDUP_R and abs(e["pos"][1] - py) <= LEVEL_DY and self._winding(e)]
        by = {e.get("ptr", e.get("slot")): e for e in live}
        for e in winding:
            k = e.get("ptr", e.get("slot"))
            if k not in self._wu:
                self._wu[k] = {"t": now, "hp0": e.get("hp") or 0, "hurt": False}
                self.stats["windup_seen"] += 1
        for k, w in list(self._wu.items()):
            e = by.get(k)
            if e is not None and (e.get("hp") or 0) < w["hp0"]:
                w["hurt"] = True
            if e is None and not w["hurt"]:
                w["hurt"] = True                         # gone from the living: killed
            if now - w["t"] >= WINDUP_HIT_S:
                if self._hit_at >= w["t"] or self._grab_at >= w["t"]:
                    self.stats["hits_after_windup"] += 1
                elif w["hurt"]:
                    self.stats["windup_interrupts"] += 1
                del self._wu[k]
        self._windup_e = min(winding, key=flat) if winding else None
        return self._windup_e

    def _quick_behind(self, p, live, flat, now):
        """A Majini close behind him (the quick turn above): the turn's first step, or the trigger let go first."""
        if not QUICK_TURN or now - self.quick_at <= QUICK_GAP_S:
            return None
        px, py, pz = p["pos"]
        bear = lambda e: abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
        behind = [e for e in live if flat(e) <= BEHIND_R and abs(e["pos"][1] - py) <= LEVEL_DY and bear(e) > QUICK_ERR]
        if not behind:
            return None
        e = min(behind, key=lambda x: (not self._winding(x), flat(x)))   # a wind-up first
        if any(flat(f) < flat(e) and bear(f) <= math.radians(60) and (self._winding(f) or not self._winding(e))
               for f in live):
            return None                                  # one nearer in front (as dangerous): him first
        if now - self.quick_at < QUICK_BACK_S and flat(e) > GRAB_THREAT_R:
            return None                                  # just turned: no back and forth
        if p.get("motion") == MOTION_SHOT or self.fire_down:
            if self.fire_down:
                self._trigger(False, now)                # the trigger let go first: the shot motion ends
            self.doing, self.why = "quick_turn", "one behind: the trigger let go before the quick turn"
            return {"hold": ("zl",) if self.aim_since is not None else ()}
        self._gun_down()
        key = e.get("ptr", e.get("slot"))
        self._set_target(key, now)
        self.target_at = now
        self.stats["quick_turns"] += 1
        self.stats["behind_turns"] += 1
        self.quick = 2
        self.doing, self.why = "quick_turn", (f"one {flat(e) / 100:.1f} m behind "
                                              f"({math.degrees(bear(e)):.0f} deg): the quick turn")
        return {"hold": ("ldown",)}

    def _sweep(self, p, live, flat, snap, now):
        """The turret sweep (SWEEP above): this tick's keys while it runs, None when the circle is not crowded."""
        px, py, pz = p["pos"]
        dt = 0.0 if self._sweep_t is None else max(0.0, min(now - self._sweep_t, LOOK_STEP_MAX_S))
        self._sweep_t = now
        ring = [e for e in live if flat(e) <= SWEEP_R and abs(e["pos"][1] - py) <= LEVEL_DY] if SWEEP else []
        bear = lambda e: wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])
        sw, kills = self._sweep_st, snap.get("kills")
        if sw is None:
            if not ring:
                return None
            behind = any(flat(e) <= BEHIND_R and abs(bear(e)) > math.pi / 2 for e in ring)
            front = any(abs(bear(e)) <= math.pi / 2 for e in ring)
            if len(ring) < SWEEP_N and not (behind and front):
                return None
            last = self._sweep_last
            if last is not None and now - last[1] < SWEEP_SAME_S:
                d = last[0]                              # straight after the last one: the same way (no reversal)
            else:                                        # toward the side with more of them, the nearer weighing more
                d = 1 if sum((1.0 if bear(e) > 0 else -1.0) / max(flat(e), 50.0) for e in ring) >= 0 else -1
            sw = self._sweep_st = {"since": now, "dir": d, "kills": kills if type(kills) is int else None,
                                   "clear_since": None, "yaw": 0}
            self.stats["sweeps"] += 1
            self._reloc = None
        if type(kills) is int:
            if type(sw["kills"]) is int and kills > sw["kills"]:
                self.stats["sweep_kills"] += kills - sw["kills"]
            sw["kills"] = kills
        if ring:
            sw["clear_since"] = None
        else:
            sw["clear_since"] = sw["clear_since"] or now
            if now - sw["clear_since"] >= SWEEP_EXIT_S:  # the circle clear: back to the round, moving on first
                took = sw["clear_since"] - sw["since"]
                self._clears.append(took)
                self.stats["sweep_clears"] += 1
                self.stats["sweep_clear_s"] = round(self.stats["sweep_clear_s"] + took, 2)
                self.stats["crowd_cleared_s"] = round(sum(self._clears) / len(self._clears), 2)
                self._sweep_st, self._sweep_last, self._reloc_due = None, (sw["dir"], now), True
                if self.fire_down:
                    self._trigger(False, now)
                return None
        self.stats["sweep_s"] = round(self.stats["sweep_s"] + dt, 2)
        if self.aim_since is None:                       # up at once, no body turn first
            self.aim_since = self._raise_t = now
            self.stats["raises"] += 1
            self.ray_seen = self.last_ray = None
            self._lower_pitch, self._first_ray = self._ray_pitch, True
        nearest = min(ring, key=flat) if ring else None
        held = next((s_ for s_ in snap.get("inventory") or () if s_.get("hand")), None)
        weapon = f"0x{held['id']:03x}" if held else "gun"
        lz = snap.get("laser") or {}
        hit = None
        if lz.get("up") and lz.get("from") and lz.get("at"):
            origin, dot = tuple(lz["from"]), tuple(lz["at"])
            hit = next((e for e in ring if dot_on(dot, e["pos"]) or through(origin, dot, e["pos"])), None)
        if hit is None and (lz.get("up") or p.get("motion") in MOTION_AIM):   # point blank in front: on him
            hit = next((e for e in sorted(ring, key=flat) if flat(e) <= POINT_BLANK_R
                        and abs(bear(e)) <= self.raise_tol(flat(e))), None)
        tgt = hit or nearest
        if tgt is not None:
            key = tgt.get("ptr", tgt.get("slot"))
            if key != self.target:
                self._set_target(key, now)
                self.target_at = now
            self._aimctx = {"target": key, "dist": flat(tgt), "bearing": bear(tgt), "yaw_err": bear(tgt),
                            "where": dot_on(tuple(lz["at"]), tgt["pos"]) if hit is not None else None,
                            "laserless": not lz.get("up"), "weapon": weapon, "class": tgt.get("class"),
                            "foot": tuple(tgt["pos"]), "hp_max": tgt.get("hp_max"), "shooter": tuple(p["pos"]),
                            "item": held.get("item") if held else None, "py": py,
                            "origin": tuple(lz["from"]) if lz.get("up") else None,
                            "dot": tuple(lz["at"]) if lz.get("up") else None, "gate": "sweep"}
        keys = {"zl"}
        shot = p.get("motion") == MOTION_SHOT            # the shot plays at the raised time scale: no stick in it
        if hit is None and not shot:                     # nobody under the aim: pan on
            keys.add("rleft" if sw["dir"] > 0 else "rright")
        ap = p.get("aim_pitch")
        if ap is not None and now - self.aim_since >= READY_S and not shot:   # the aim's own pitch: a chest 1-5 m
            if ap < SWEEP_PITCH_BAND[0]:
                keys.add("rdown")
            elif ap > SWEEP_PITCH_BAND[1]:
                keys.add("rup")
        if shot and hit is None:
            self.stats["sweep_shot_waits"] += 1          # the trigger let go, the shot motion still playing
        if hit is not None:
            keys |= self._trigger(True, now)             # on one: the trigger, the pan stopped
        elif self.fire_down:
            self._trigger(False, now)
        yaw = 1 if "rleft" in keys else -1 if "rright" in keys else 0
        if yaw and sw["yaw"] and yaw != sw["yaw"]:
            self.stats["sweep_reversals"] += 1
        sw["yaw"] = yaw or sw["yaw"]
        self.doing = "sweep"
        self.why = (f"sweep {'left' if sw['dir'] > 0 else 'right'} {now - sw['since']:.1f} s: {len(ring)} within "
                    f"{SWEEP_R / 100:.0f} m" + (f", the nearest {flat(nearest) / 100:.1f} m" if nearest else ", clearing")
                    + (" - firing on one" if hit is not None else " - the shot playing" if shot else " - panning"))
        return {"hold": tuple(sorted(keys))}

    def _keep_moving(self, p, live, flat, now) -> None:
        """His dwell at one spot (DWELL_R): avg_dwell_s / max_dwell_s, and a relocation due past DWELL_MAX_S with
        Majini about, or with RELOC_CROWD_N within RELOC_CROWD_R after 3 s at one spot."""
        pos, dw = p["pos"], self._dwell
        if dw is None or math.hypot(pos[0] - dw["anchor"][0], pos[2] - dw["anchor"][2]) > DWELL_R:
            if dw is not None:
                self._dwells.append(now - dw["since"])
                self.stats["avg_dwell_s"] = round(sum(self._dwells) / len(self._dwells), 1)
            dw = self._dwell = {"anchor": pos, "since": now}
        cur = now - dw["since"]
        if cur > (self.stats.get("max_dwell_s") or 0):
            self.stats["max_dwell_s"] = round(cur, 1)
        if not RELOCATE or self._reloc is not None or self._sweep_st is not None or now < self._reloc_ready:
            return
        about = any(flat(e) <= RELOC_SENSE_R for e in live)
        boxed = any(flat(e) <= RAMPAGE_R for e in live)  # anyone within 5 m: stand and shotgun (CROWD_FIRE)
        if cur > DWELL_MAX_S and about and not boxed:
            self._reloc_due = True

    def _trail_tick(self, p, now) -> None:
        """His own trail: a point every TRAIL_EVERY_S (where he has been is open and reachable), the last TRAIL_KEPT."""
        if not self._trail or now - self._trail[-1][0] >= TRAIL_EVERY_S:
            self._trail = (self._trail + [(now, tuple(p["pos"]))])[-TRAIL_KEPT:]

    def _reloc_goal(self, p, live, snap, now):
        """Where to relocate: a point he knows is open - his own trail (TRAIL_AGE_S old or more, RELOC_GOAL_MIN away)
        or a standing statue on his level - farthest from the Majini (each within RELOC_SENSE_R pushing by 1/d), never
        within DEAD_END_R of a run that stuck, nor one whose way runs through the crowd. (heading, statue?, goal) or
        None."""
        px, py, pz = p["pos"]
        cands = [(pos, False) for t, pos in self._trail if now - t >= TRAIL_AGE_S]
        cands += [(tuple(b["pos"]), True) for b in snap.get("bonuses") or ()]
        near = [e for e in live if math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= RELOC_SENSE_R]
        best = None
        for pos, statue in cands:
            d = math.hypot(pos[0] - px, pos[2] - pz)
            if d < RELOC_GOAL_MIN or abs(pos[1] - py) > LEVEL_DY:
                continue
            if any(math.hypot(pos[0] - q[0], pos[2] - q[2]) <= DEAD_END_R for q in self._dead_ends):
                continue                                 # a run stuck there before: a dead end
            head = heading(pos[0] - px, pos[2] - pz)
            through = any(abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - head)) <= math.radians(30)
                          and math.hypot(e["pos"][0] - px, e["pos"][2] - pz) < d for e in near)
            if through:
                continue                                 # its way runs through them
            crowd = sum(1.0 / max(math.hypot(e["pos"][0] - pos[0], e["pos"][2] - pos[2]), 100.0) for e in near)
            score = crowd * 1000.0 - (0.3 if statue else 0.0)   # the clearest; a statue (phase 1) by a little
            if best is None or score < best[0]:
                best = (score, head, statue, pos)
        return None if best is None else best[1:]

    def _relocate(self, p, live, flat, snap, now):
        """A relocation (RELOCATE above): the run's keys while it lasts, None otherwise."""
        px, py, pz = p["pos"]
        r = self._reloc
        if r is None:
            if not (RELOCATE and self._reloc_due):
                return None
            self._reloc_due = False
            if now < self._reloc_ready:
                return None
            goal = self._reloc_goal(p, live, snap, now)
            if goal is None:
                return None                              # nowhere known open and clear: stand and fight here
            head, statue, gpos = goal
            r = self._reloc = {"since": now, "head": head, "from": (px, pz), "best": 0.0, "best_at": now,
                               "quick": False, "statue": statue, "goal": gpos}
            self.stats["relocations"] += 1
            self._reloc_ready = now + RELOC_GAP_S
            self._gun_down()
            if self.mines is not None:
                self._mine_now("")                       # a bomb as he leaves (the mines' own checks still apply)
        moved = math.hypot(px - r["from"][0], pz - r["from"][1])
        if moved > r["best"] + RELOC_PROGRESS_CM:
            r["best"], r["best_at"] = moved, now
        blocked = any(flat(e) <= RELOC_BLOCK_R and abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"]))
                      <= math.radians(45) for e in live)
        stuck = now - r["best_at"] > RELOC_STUCK_S
        if moved >= RELOC_DIST or now - r["since"] >= RELOC_MAX_S or blocked or stuck:
            if stuck and not blocked and moved < RELOC_DIST:
                self.stats["reloc_stuck"] += 1
                self.stats["reloc_dead_ends"] += 1
                self._dead_ends = (self._dead_ends + [(px, py, pz), tuple(r["goal"])])[-DEAD_ENDS_KEPT:]
                tuning.note_dead_end(MAP_ID, (px, pz), r["goal"])
                self._kite_side = -self._kite_side       # a wall that way: loop the other way next time
            self._reloc, self._dwell = None, None
            return None
        if r.get("goal") is not None:                    # on toward the goal (a point he knows is open)
            r["head"] = heading(r["goal"][0] - px, r["goal"][2] - pz)
        err = wrap(r["head"] - p["rot"])
        can_quick = QUICK_TURN and not r["quick"] and now - self.quick_at > QUICK_BACK_S
        if abs(err) > QUICK_ERR and not can_quick:       # the way out behind him: back toward it while turning
            r["best_at"] = max(r["best_at"], now)
            self.doing, self.why = "relocate", f"relocating: turning to the way out {math.degrees(err):+.0f} deg"
            return {"hold": ("ldown",) + self._turn(err)}
        if abs(err) > QUICK_ERR:
            r["quick"], r["best_at"] = True, now + 0.6   # the way out behind him: one quick turn, then the run
            self.stats["quick_turns"] += 1
            self.quick = 2
            self.doing, self.why = "quick_turn", f"relocating: the way out {math.degrees(err):+.0f} deg"
            return {"hold": ("ldown",)}
        self.doing = "relocate"
        self.why = (f"relocating {moved / 100:.1f} m" + (" to a statue" if r["statue"] else "")
                    + f", heading {math.degrees(err):+.0f} deg off")
        return {"hold": ("lup", "b") + self._turn(err, TURN_TOL)}

    def _frozen_dot(self, p, dot, fresh) -> bool:
        """The live dot unchanged FROZEN_TICKS aimed ticks while the right stick was held or his heading changed."""
        moved = bool(self._sticks & {"rleft", "rright", "rup", "rdown"}) or (
            self._rot_prev is not None and abs(wrap(p["rot"] - self._rot_prev)) > 0.01)
        self._rot_prev = p["rot"]
        if not fresh:
            return False
        same = self._dot_prev is not None and math.dist(dot, self._dot_prev) < 0.01   # the very same floats: stale
        self._dot_same = self._dot_same + 1 if same and moved else (self._dot_same if same else 0)
        self._dot_prev = dot
        if self._dot_same >= FROZEN_TICKS:
            self._dot_same, self._dot_prev = 0, None
            return True
        return False

    def _aim_away(self, p, live, flat, origin, dot, confirmed, now):
        """The aim over AWAY_ERR off the nearest threat within THREAT_NEAR_R for AWAY_S: that one, at once."""
        px, py, pz = p["pos"]
        near = [e for e in live if flat(e) <= THREAT_NEAR_R and abs(e["pos"][1] - py) <= LEVEL_DY]
        if not near or math.hypot(dot[0] - origin[0], dot[2] - origin[2]) < 1.0:
            self._away_since = None
            return None
        e = min(near, key=flat)
        aim = heading(dot[0] - origin[0], dot[2] - origin[2])
        off = abs(wrap(heading(e["pos"][0] - origin[0], e["pos"][2] - origin[2]) - aim))
        if off <= AWAY_ERR or confirmed:
            self._away_since = None
            return None
        dt = min(now - self._away_since, LOOK_STEP_MAX_S) if self._away_since is not None else 0.0
        self.stats["aim_away_s"] = round(self.stats["aim_away_s"] + dt, 2)
        self._away_since = self._away_since or now
        if now - self._away_since < AWAY_S:
            self._away_t = now
            return None
        self.stats["aim_away_fixes"] += 1
        key = e.get("ptr", e.get("slot"))
        self._set_target(key, now)
        self.target_at = now
        err = wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])
        self.doing, self.why = "unaim", (f"aim {math.degrees(off):.0f} deg off the nearest ({flat(e) / 100:.1f} m) "
                                         f"for {now - self._away_since:.1f} s: to him")
        self._example("aim_away", p, now, f"aim {math.degrees(off):.0f} deg off the one {flat(e) / 100:.1f} m away")
        self._away_since = None
        if CROWD_FIRE and flat(e) <= RAMPAGE_R:
            return {"hold": ("zl",)}                     # (the caller turns the aim: the gun stays up within 5 m)
        self._gun_down()
        return {"hold": self._turn(err)}

    def _track_approach(self, p, live, now) -> None:
        """Each Majini's closing speed on him (cm/s, + = coming), smoothed (APPROACH_EMA), from tick to tick."""
        px, _, pz = p["pos"]
        seen = {}
        for e in live:
            k = e.get("ptr", e.get("slot"))
            d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
            prev = self._appr.get(k)
            v = 0.0
            if prev is not None:
                dt = now - prev[1]
                v = APPROACH_EMA * (prev[0] - d) / dt + (1.0 - APPROACH_EMA) * prev[2] if 0.0 < dt <= 0.5 else prev[2]
            seen[k] = (d, now, max(-1000.0, min(1000.0, v)))
        self._appr = seen

    def _threat_d(self, p, e) -> float:
        """How soon this Majini is on him: the distance less APPROACH_LEAD_S of his closing speed, x the turn to him."""
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        v = (self._appr.get(e.get("ptr", e.get("slot"))) or (0.0, 0.0, 0.0))[2]
        turn = abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) if d > BEHIND_R else 0.0
        return max(0.0, d - APPROACH_LEAD_S * max(0.0, v)) * (1.0 + TURN_W * turn / math.pi)

    @staticmethod
    def _threat_near(p, live) -> bool:
        """A Majini on his level within THREAT_NEAR_R (THREAT_FIRST)."""
        px, py, pz = p["pos"]
        return bool(THREAT_FIRST and any(math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= THREAT_NEAR_R
                                         and abs(e["pos"][1] - py) <= LEVEL_DY for e in live))

    def _threat_pick(self, p, live, cur, now):
        """Threat first: within THREAT_CAP_R, his level first, the lowest threat distance; the current one kept within
        THREAT_KEEP; one within GRAB_THREAT_R wins (unless the current one is that near)."""
        px, py, pz = p["pos"]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        pool = [e for e in live if flat(e) <= THREAT_CAP_R]
        pool = [e for e in pool if abs(e["pos"][1] - py) <= LEVEL_DY] or pool
        self.stats["threat_ticks"] += 1
        if len(pool) < len(live):
            self.stats["threat_caps"] += 1                   # one or more beyond the cap (or off his level) left out
        td = lambda e: self._threat_d(p, e)
        best = min(pool, key=td)
        grab = min((e for e in pool if flat(e) < GRAB_THREAT_R), key=flat, default=None)
        in_pool = cur is not None and any(e is cur for e in pool)
        if grab is not None and not (in_pool and flat(cur) < GRAB_THREAT_R):
            best = grab
        elif in_pool and td(cur) <= THREAT_KEEP * td(best) + THREAT_KEEP_CM:
            best = cur
        if best is not cur:
            self.stats["threat_switches"] += 1
        return best

    def _choose(self, p, live, now):
        """The Majini to fight. One he can shoot without turning (inside raise_tol, in reach) comes first: the current
        one if he is in front, else the nearest in front, unless one not in front is about to grab him (GRAB_THREAT_R).
        Nobody in front: the cost (near and in front; K's learned range preferred), a new one kept COMMIT_S, one within
        THREAT_R first."""
        px, py, pz = p["pos"]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        if piece(SMOOTH_LEVEL):                              # no pitching up at a roof while ground Majini come
            ground_near = any(flat(e) <= PITCH_GUARD_R and abs(e["pos"][1] - py) <= LEVEL_DY for e in live)
            calm = [e for e in live
                    if not (ground_near and flat(e) >= GRAB_THREAT_R and self._pitch_to(p, e) > PITCH_SWING)]
            live = calm or live
        best = min(live, key=lambda e: self._kcost(p, e, now))
        if K_PLAN and best is not min(live, key=lambda e: self._cost(p, e)):
            self.stats["k_range_picks"] += 1                 # a choice the learned range changed
        cur = next((e for e in live if self.target is not None and e.get("ptr", e.get("slot")) == self.target), None)
        wu = self._windup_e
        if wu is not None and any(e is wu for e in live):   # winding up: the target before any other
            if wu is not cur:
                self.stats["windup_picks"] += 1
                self.target_at = now
            self._set_target(wu.get("ptr", wu.get("slot")), now)
            return wu
        nearest = min(live, key=flat)
        front = [e for e in live if flat(e) <= ENGAGE_R
                 and abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) <= self.raise_tol(flat(e))]
        if piece(SMOOTH_LEVEL):
            level = [e for e in front if abs(e["pos"][1] - py) <= LEVEL_DY]
            front = level or front                           # his own level first
        if piece(SMOOTH_CLOSE):
            if cur is not None and flat(cur) < THREAT_R and (cur.get("hp") or 0) > 0:
                grab = min((e for e in live if e is not cur and flat(e) < GRAB_THREAT_R), key=flat, default=None)
                if grab is None or flat(grab) > 0.7 * flat(cur):
                    self.stats["close_keeps"] += 1           # up close: kept until it dies or leaves THREAT_R
                    self._set_target(cur.get("ptr", cur.get("slot")), now)
                    return cur
        if self._threat_near(p, live):                       # one on his level within reach of him: threat first
            best = self._threat_pick(p, live, cur, now)
            if best is not cur:
                self.target_at = now
                if cur is not None and abs(self._pitch_to(p, best) - self._pitch_to(p, cur)) > PITCH_SWING:
                    self.stats["pitch_swings"] += 1
            self._set_target(best.get("ptr", best.get("slot")), now)
            return best
        if front:
            best = cur if cur is not None and any(e is cur for e in front) else min(front, key=flat)
            if flat(nearest) < GRAB_THREAT_R and not any(e is nearest for e in front) and flat(best) > 2 * flat(nearest):
                best = nearest
        elif cur is not None and now - self.target_at < COMMIT_S:
            best = cur
        elif flat(nearest) < THREAT_R and (cur is None or flat(cur) > 1.5 * flat(nearest)):
            best = nearest
        elif cur is not None and self._kcost(p, cur, now) <= KEEP_TARGET * self._kcost(p, best, now):
            best = cur
        if piece(SMOOTH_FLIP) and cur is not None and best is not cur \
                and best.get("ptr", best.get("slot")) == self.prev_target \
                and now - self.switch_at < FLIP_S and flat(best) >= GRAB_THREAT_R:
            best = cur                                       # not back to the one he just left (a flip-flop)
        if best is not cur:
            self.target_at = now
            if abs(best["pos"][1] - p["pos"][1]) > LEVEL_DY:
                self.stats["off_level_picks"] += 1
            if cur is not None and abs(self._pitch_to(p, best) - self._pitch_to(p, cur)) > PITCH_SWING:
                self.stats["pitch_swings"] += 1
        self._set_target(best.get("ptr", best.get("slot")), now)
        return best

    @staticmethod
    def _pitch_to(p, e) -> float:
        """The aim's pitch (absolute, radians) from his muzzle to this Majini's chest."""
        d = math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
        return abs(math.atan2(e["pos"][1] + CHEST_H - (p["pos"][1] + MUZZLE_H), max(d, 1.0)))

    def _calm_sticks(self, act, snap, now) -> dict:
        """The right stick shaped (CALM): no reversal within CALM_REVERSE_S, the gun-down turn held to CALM_TURN_DEG_S
        on average; his heading's speed measured (spin_deg_s, spin_max_deg_s). A grab's mashing is left alone."""
        c = self._calm
        dt = 0.0 if c["t"] is None else max(0.0, min(now - c["t"], LOOK_STEP_MAX_S))
        c["t"] = now
        p = snap.get("player") or {}
        rot = p.get("rot")
        if rot is not None and c["rot"] is not None and dt > 0:
            speed = abs(math.degrees(wrap(rot - c["rot"]))) / dt
            c["spin"][0] += speed * dt
            c["spin"][1] += dt
            self.stats["spin_deg_s"] = round(c["spin"][0] / c["spin"][1], 1) if c["spin"][1] else 0.0
            if speed < 2000:
                self.stats["spin_max_deg_s"] = round(max(self.stats.get("spin_max_deg_s") or 0.0, speed), 1)
        c["rot"] = rot
        hold = act.get("hold")
        if not CALM or hold is None or self.doing in ("held", "escape", "quick_turn"):
            return act
        keys = list(hold)
        for axis, pair in (("h", ("rleft", "rright")), ("v", ("rup", "rdown"))):
            d = 1 if pair[0] in keys else -1 if pair[1] in keys else 0
            last_d, last_t = c[axis]
            if d and last_d and d != last_d and now - last_t < CALM_REVERSE_S:
                keys = [k for k in keys if k not in pair]    # a reversal: coast first
                self.stats["calm_coasts"] += 1
                continue
            if d:
                c[axis] = (d, now)
        c["budget"] = min(c["budget"] + CALM_TURN_DEG_S * dt, 0.15 * TURN_SPEED_DEG_S)
        if "zl" not in keys and any(k in keys for k in ("rleft", "rright")):
            cost = TURN_SPEED_DEG_S * dt
            if c["budget"] >= cost:
                c["budget"] -= cost
            else:
                keys = [k for k in keys if k not in ("rleft", "rright")]   # over the turn rate: this tick coasts
                self.stats["calm_caps"] += 1
        return {**act, "hold": tuple(keys)}

    def _prompt_type(self, pr, snap) -> str:
        enemies = {e.get("ptr") for e in snap.get("enemies") or () if e.get("ptr")}
        label, kind = pr.get("label"), pr.get("kind")
        if pr.get("owner") in enemies or pr.get("target") in enemies or pr.get("mode") in (6, 7, 8, 9):
            return "enemy"                               # a Majini's (a grab, a dodge, a finisher) or a stick QTE
        if kind == re5_switch_prompt.KIND_ENEMY and not pr.get("owner"):
            return "enemy"                               # (a grab whose owner was not read)
        if label == re5_switch_prompt.LABEL_RESUSCITATE:
            return "dying"
        if label == re5_switch_prompt.LABEL_TIME_BONUS:
            return "bonus"
        if label == re5_switch_prompt.LABEL_PICKUP and kind == re5_switch_prompt.KIND_PLAYER:
            return "pickup"
        if kind == re5_switch_prompt.KIND_PLAYER and label != re5_switch_prompt.LABEL_PLACE                 and (label in re5_switch_prompt.TRAVERSE_LABELS or pr.get("token") == "press:y"):
            return "traverse"
        return "other"

    def _prompt_wanted(self, kind, p, snap) -> bool:
        if kind in ("enemy", "dying", "bonus"):
            return True
        px, py, pz = p["pos"]
        if kind == "pickup":
            near = any((e.get("hp") or 0) > 0 and math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= PICKUP_CLEAR_R
                       and abs(e["pos"][1] - py) <= MAX_DY for e in snap.get("enemies") or ())
            mine = any(math.hypot(g["pos"][0] - px, g["pos"][2] - pz) <= MINE_CLEAR_R
                       for g in snap.get("ground_mines") or ())
            busy = self.healing is not None or self.escape is not None                 or (self.mines is not None and self.mines.state != "idle")
            return not (near or mine or busy)
        if kind == "traverse":
            return self._goal_dy is not None and abs(self._goal_dy) > LEVEL_DY
        return False

    def _prompt(self, p, snap, now):
        """The game's shown prompt (snap prompt) answered by its type and mode (PROMPTS above); None when there is none
        or it is not one to take."""
        pr = snap.get("prompt") if PROMPTS else None
        st = self._pr
        lw = self._level_watch
        if lw is not None:
            if abs(p["pos"][1] - lw[0]) > LEVEL_DY:
                self.stats["level_changes"] += 1
                self._level_watch = None
            elif now > lw[1]:
                self._level_watch = None
        if st is not None and (pr is None or pr.get("button") != st["button"] or pr.get("label") != st["label"]):
            if st["presses"] and now - st["first"] <= PROMPT_TAKE_S:
                self.stats["prompts_taken"] += 1         # pressed, and gone (or another in its place)
                if st["type"] == "traverse":
                    self.stats["ledge_jumps"] += 1
            self._pr = st = None
        if pr is None:
            return None
        if st is None:
            kind = self._prompt_type(pr, snap)
            st = self._pr = {"button": pr.get("button"), "label": pr.get("label"), "type": kind, "since": now,
                             "first": None, "presses": 0, "phase": 0}
            self.stats["prompts_seen"] += 1
            self.stats["prompts_seen_" + kind] += 1
            if kind == "traverse":                       # the stage's spot: logged (the ledges learned later)
                x, y, z = p["pos"]
                spots = [s_ for s_ in (self.stats.get("traverse_spots") or "").split(" | ") if s_]
                spots = (spots + [f"{pr.get('label')}@{x:.0f},{y:.0f},{z:.0f}"])[-8:]
                self.stats["traverse_spots"] = " | ".join(spots)
        if not self._prompt_wanted(st["type"], p, snap):
            return None
        if st["first"] is None:
            st["first"] = now
            self._pr_lat.append(now - st["since"])
            del self._pr_lat[:-50]
            self.stats["prompt_latency_s"] = round(sum(self._pr_lat) / len(self._pr_lat), 3)
            if st["type"] == "traverse":
                self._level_watch = (p["pos"][1], now + LEVEL_CHANGE_S)
        st["presses"] += 1
        st["phase"] += 1
        self.stats["prompt_presses"] += 1
        token = pr.get("token") or ""
        if st["presses"] == 1 and not self.in_hold and (st["type"] == "dying" or token == "mash:wiggle"):
            k = "dying" if st["type"] == "dying" else "holds"   # (the round's holds / dying, as the held rule counts)
            self.stats[k] = self.stats.get(k, 0) + 1
            self.in_hold = True
        self.doing = "held" if st["type"] in ("enemy", "dying") else "prompt"
        self.why = f"prompt {st['type']}: {token} (label {pr.get('label')})"
        if token == "mash:wiggle":
            return {"hold": WIGGLE[st["phase"] % len(WIGGLE)]}
        if token == "stick:rotate":
            return {"hold": ROTATE[st["phase"] % len(ROTATE)]}
        if token in ("stick:y", "stick:x"):
            pair = (("lup",), ("ldown",)) if token == "stick:y" else (("lleft",), ("lright",))
            return {"hold": pair[st["phase"] % 2]}
        keys = tuple(pr.get("keys") or ())
        if not keys:
            return None
        return {"hold": keys if st["phase"] % 2 else ()}  # one tick down, one up: a fresh press each time

    def _writer(self):
        if self._ram is None and self._m is not None:
            self._ram = re5_switch_aim.aim_writer(self._m) or False
        return self._ram or None

    def _lock_aim(self, snap, keys, yaw_err, pitch_err, now):
        """AIM_LOCK: the aim moved by RAM - the heading by yaw_err, the camera pitch by pitch_err (radians: + = a larger
        heading / up), each at most its rate this tick (all of it within AIM_LOCK_SNAP_DEG), read back: the right-stick
        keys dropped. Off, no camera, no writer or a failed read-back: the keys as they were."""
        st = snap.get("aim_cam")
        if not AIM_LOCK or not st or (yaw_err is None and pitch_err is None) or self._lock_off:
            return keys
        w = self._writer()
        if w is None:
            return keys
        last = self._lock_last                           # did the game keep the last write? (the next frame's state)
        if last is not None and now - last[2] <= 0.25:
            held = (last[0] is None or abs(st["pitch"] - last[0]) <= AIM_LOCK_HELD) and                 (last[1] is None or abs(wrap(st["heading"] - last[1])) <= AIM_LOCK_HELD)
            self._lock_score[0 if held else 1] += 1
            if self._lock_score[1] >= 6 and self._lock_score[1] > self._lock_score[0]:
                self._lock_off = True                    # written, read back, then overwritten: the stick again
                self.stats["aim_lock_unheld"] += 1
                return keys
        dt = max(1.0 / 30.0, min(now - self._lock_t, LOOK_STEP_MAX_S)) if self._lock_t is not None else 1.0 / 30.0
        self._lock_t = now

        def step(err, rate):
            lim = math.radians(rate) * dt
            return err if abs(err) <= math.radians(AIM_LOCK_SNAP_DEG) else max(-lim, min(lim, err))
        h = wrap(st["heading"] + step(yaw_err, AIM_LOCK_YAW_DEG_S)) if yaw_err is not None else None
        pt = st["pitch"] + step(pitch_err, AIM_LOCK_PITCH_DEG_S) if pitch_err is not None else None
        if w(st, pt, h):
            self.stats["aim_lock_ticks"] += 1
            self._lock_last = (pt, h, now)
            return set(keys) - {"rleft", "rright", "rup", "rdown"}
        self.stats["aim_lock_fails"] += 1
        return keys

    def _lock_errors(self, p, snap, foot, aim_h, dist, origin=None, dot=None):
        """(yaw, pitch) errors for the lock: from the laser's ray when it is long enough to steer by, else his heading
        to the target and the chest's elevation against the camera's pitch."""
        chest = (foot[0], foot[1] + aim_h, foot[2])
        if origin is not None and dot is not None and math.dist(origin, dot) >= STEER_RAY_CM:
            return ray_error(origin, dot, chest)
        px, py, pz = p["pos"]
        st = snap.get("aim_cam") or {}
        yaw = wrap(heading(chest[0] - px, chest[2] - pz) - p["rot"])
        want = math.atan2(chest[1] - (py + MUZZLE_H), max(dist, 1.0))
        return yaw, (want - st["pitch"]) if st.get("pitch") is not None else None

    def wall_memory(self, x: float, z: float, heading_rad: float) -> None:
        """A blocked spot and the heading into it (the routing's own, or the governor's): no push there again."""
        self._walls = (self._walls + [(float(x), float(z), float(heading_rad))])[-WALL_MEM_KEPT:]

    def _open_heading(self, p, push_head: float) -> float:
        """The most open known way from here: toward a point of his trail (open: he walked it) nearest to the way he was
        going yet at least WALL_TURN_DEG off it and off every wall remembered near; else back the way he came."""
        px, _, pz = p["pos"]
        near_walls = [w[2] for w in self._walls if math.hypot(w[0] - px, w[1] - pz) <= 2 * WALL_MEM_R] + [push_head]
        best = None
        for _t, pos in getattr(self, "_trail", []) or []:
            d = math.hypot(pos[0] - px, pos[2] - pz)
            if not 150.0 <= d <= 1500.0:
                continue
            h = heading(pos[0] - px, pos[2] - pz)
            if any(abs(wrap(h - w)) < math.radians(WALL_TURN_DEG) for w in near_walls):
                continue
            off = abs(wrap(h - push_head))
            if best is None or off < best[0]:
                best = (off, h)
        return best[1] if best is not None else wrap(push_head + math.pi)

    def _wall_start(self, p, now, preempt: bool) -> None:
        head = p["rot"]
        if not preempt:
            self.wall_memory(p["pos"][0], p["pos"][2], head)
        self._wall_rec = {"back_until": now + WALL_BACK_S, "until": now + WALL_BACK_S + WALL_GO_S,
                          "head": self._open_heading(p, head)}
        self._wall_push, self._wall_hist = None, []

    def _wall_gov(self, act, snap, now) -> dict:
        """WALL_GOV: no push into a wall - this tick's movement keys, a recovery's while one runs."""
        p, hold = snap.get("player"), act.get("hold")
        dt = 0.0 if self._wgov_t is None else max(0.0, min(now - self._wgov_t, LOOK_STEP_MAX_S))
        self._wgov_t = now
        if not WALL_GOV or not p or hold is None or self.doing in ("held", "dead", "quick_turn") or "zl" in hold:
            self._wall_push, self._wall_hist = None, []
            return act
        rec = self._wall_rec
        if rec is not None:
            if now < rec["until"]:                       # the recovery: a step back, then the open way
                keys = [k for k in hold if k not in ("lup", "ldown", "lleft", "lright", "b", "rleft", "rright")]
                if now < rec["back_until"]:
                    keys.append("ldown")
                else:
                    keys += ["lup"] + list(self._turn(wrap(rec["head"] - p["rot"]), TURN_TOL))
                self.doing = "walk"
                self.why = f"wall: the open way {math.degrees(wrap(rec['head'] - p['rot'])):+.0f} deg"
                return {**act, "hold": tuple(keys)}
            self._wall_rec = None
            self.stats["wall_recoveries"] += 1
        if "lup" not in hold:
            self._wall_push, self._wall_hist = None, []
            return act
        px, _, pz = p["pos"]
        if any(math.hypot(w[0] - px, w[1] - pz) <= WALL_MEM_R and abs(wrap(p["rot"] - w[2])) <= math.radians(WALL_MEM_DEG)
               for w in self._walls):
            self.stats["wall_preempts"] += 1             # a wall met here on this heading: not again
            self._wall_start(p, now, preempt=True)
            return self._wall_gov(act, snap, now)
        self._wall_push = self._wall_push or now
        self._wall_hist = [x for x in self._wall_hist if now - x[0] <= 1.0] + [(now, p["pos"])]
        old = next((x for x in self._wall_hist if now - x[0] >= WALL_WINDOW_S), None)
        if old is not None:
            moved = math.hypot(px - old[1][0], pz - old[1][2])
            if moved < WALL_MIN_CM:
                self.stats["wall_push_s"] = round(self.stats["wall_push_s"] + dt, 2)
                self.stats["wall_hits"] += 1
                self._example("wall_shot", p, now, f"pushing into a wall: {moved:.0f} cm in {WALL_WINDOW_S:.2f} s")
                self._wall_start(p, now, preempt=False)
                return self._wall_gov(act, snap, now)
        return act

    def _governor(self, act, snap, now) -> dict:
        """HEADING_GOV: his heading turned faster than HEADING_GOV_DEG_S since the last tick: no turn stick this tick
        (a grab's escape left alone)."""
        rot, g = (snap.get("player") or {}).get("rot"), self._gov
        speed = None
        if rot is not None and g[0] is not None and now > g[1]:
            speed = abs(math.degrees(wrap(rot - g[0]))) / (now - g[1])
        self._gov = (rot, now) if rot is not None else (None, now)
        hold = act.get("hold")
        if not HEADING_GOV or speed is None or speed <= HEADING_GOV_DEG_S or not hold or self.doing == "held" \
                or not {"rleft", "rright"} & set(hold) or self.quick or now - self.quick_at < QUICK_SETTLE_S + 0.3:
            return act                                   # (the quick turn: the game's own 180, exempt)
        self.stats["gov_drops"] += 1
        return {**act, "hold": tuple(k for k in hold if k not in ("rleft", "rright"))}

    def _count_sticks(self, act, now) -> None:
        """The right stick's motion this tick: a key newly down (stick_onsets: the pulses), and the yaw turned the other
        way within 0.4 s of the last (aim_reversals: the camera swinging back)."""
        sticks = {k for k in act.get("hold") or () if k in ("rleft", "rright", "rup", "rdown")}
        self.stats["stick_onsets"] += len(sticks - self._sticks)
        self._sticks = sticks
        d = 1 if "rleft" in sticks else -1 if "rright" in sticks else 0
        if d:
            if self._yaw_dir and d != self._yaw_dir and now - self._yaw_dir_at <= 0.4:
                self.stats["aim_reversals"] += 1
            self._yaw_dir, self._yaw_dir_at = d, now
        d = 1 if "rup" in sticks else -1 if "rdown" in sticks else 0
        if d:
            if self._pitch_dir and d != self._pitch_dir and now - self._pitch_dir_at <= 0.4:
                self.stats["pitch_reversals"] += 1
            self._pitch_dir, self._pitch_dir_at = d, now

    def _plan(self, e, dist, item, now):
        """K's dispatch plan for this Majini (class, distance, weapon), or None (no class, K off, or no learned field)."""
        cls = e.get("class")
        if not K_PLAN or not cls:
            return None
        key = (cls, int(dist // 200), item)
        hit = self._plans.get(key)
        if hit is not None and now - hit[0] < K_CACHE_S:
            return hit[1]
        from ..brain import knowledge
        try:
            plan = knowledge.dispatch_plan(MAP_ID, cls, None, dist, item)
        except Exception:                                    # noqa: BLE001 - no knowledge: today's constants
            plan = None
        plan = plan if plan is not None and plan.source != "default" else None
        if len(self._plans) > 256:
            self._plans.clear()
        self._plans[key] = (now, plan)
        return plan

    @staticmethod
    def _sure(plan, field) -> bool:
        return plan is not None and plan.conf(field) >= K_MIN_CONF \
            and dict(plan.field_samples).get(field, 0) >= K_MIN_SAMPLES

    def _track_combo(self, snap) -> None:
        """A combo that falls to 0 is a break; one whose window had run out at the last read is a lapse."""
        combo, window = snap.get("combo"), snap.get("combo_timer")
        if type(combo) is not int or not 0 <= combo < 100000:
            return
        if self._combo_prev > 0 and (combo == 0 or combo < self._combo_prev):
            self.stats["combo_breaks"] += 1
            if isinstance(self._combo_window, (int, float)) and self._combo_window <= COMBO_LAPSE_S:
                self.stats["combo_lapses"] += 1
                self._lapse_cause(snap)
                if self._pur is not None or (self._now is not None and self._now - self._pur_end_at < 1.0):
                    self.stats["pursuit_lapses"] += 1
        if combo > 0 and isinstance(window, (int, float)) and not isinstance(window, bool) and 0 < window < 600:
            self.stats["combo_window_full"] = round(max(window, self.stats.get("combo_window_full") or 0.0), 1)
        self._combo_prev = combo
        self._combo_window = window if combo > 0 else None

    def _lapse_cause(self, snap) -> None:
        p = snap.get("player") or {}
        px, _, pz = p.get("pos") or (0.0, 0.0, 0.0)
        alive = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos")]
        if not alive:
            self.stats["combo_lapse_empty"] += 1
            return
        near = min(math.hypot(e["pos"][0] - px, e["pos"][2] - pz) for e in alive)
        self.stats["combo_lapse_far" if near > COMBO_REACH else "combo_lapse_near"] += 1
        if self.aim_since is not None:
            self.stats["combo_lapse_aimed"] += 1

    def _combo_urgent(self, snap) -> bool:
        combo, window = snap.get("combo"), snap.get("combo_timer")
        return bool(COMBO_PUSH and type(combo) is int and combo > 0 and isinstance(window, (int, float))
                    and not isinstance(window, bool) and 0.0 < window <= COMBO_URGENT_S)

    def _set_target(self, key, now) -> None:
        """The target from here on: a change is counted (target_switches), and a change back to the one he left within
        FLIP_S too (target_flips)."""
        if key != self.target:
            if self.target is not None and key is not None:
                self.stats["target_switches"] += 1
                if key == self.prev_target and now - self.switch_at < FLIP_S:
                    self.stats["target_flips"] += 1
            self.prev_target, self.switch_at = self.target, now
        self.target = key

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
        fell = {k: self.hp_prev[k] - h for k, h in hp.items() if h < self.hp_prev.get(k, h)}
        drops = len(fell)
        self.hp_prev = hp
        for pull in self._pulls:                             # the look: which pull took the health
            if fell and (pull["end"] is None or now - pull["end"] <= HIT_S):
                pull["drops"] += drops
                pull["hp_delta"] -= fell.get(pull["target"], 0)
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

    def _yaw(self, err: float, window: float | None = None) -> set:
        if abs(err) <= YAW_DEAD:
            return set()
        if abs(err) < FINE:
            n = self._pulse_n(err, window)
            self.yaw_pulse = (self.yaw_pulse + 1) % n
            if self.yaw_pulse:
                return set()
        return {"rleft"} if err > 0 else {"rright"}

    def _pitch_settled(self, err: float, window: float | None, now: float) -> set:
        """The pitch stick, after the raise's own pitch settles (RAISE_SETTLE_S) and coasting once the measured rate
        closes the error within PITCH_LEAD_S (no overshoot after a retarget)."""
        if not PITCH_SETTLE:
            return self._pitch(err, window)
        if self._first_ray_at is not None and now - self._first_ray_at < RAISE_SETTLE_S:
            self.stats["raise_settle_ticks"] += 1
            return set()
        r = self._prate
        if r is not None and abs(err) > PITCH_DEAD and r * err > 0 and abs(r) * PITCH_LEAD_S >= abs(err):
            self.stats["pitch_brakes"] += 1              # moving toward him fast enough: let it coast
            return set()
        return self._pitch(err, window)

    def _pitch(self, err: float, window: float | None = None) -> set:
        if abs(err) <= PITCH_DEAD:
            return set()
        if abs(err) < FINE:
            n = self._pulse_n(err, window)
            self.pitch_pulse = (self.pitch_pulse + 1) % n
            if self.pitch_pulse:
                return set()
        return {"rup"} if err > 0 else {"rdown"}

    @staticmethod
    def _pulse_n(err: float, window: float | None) -> int:
        """Inside FINE: a pulse every n ticks - 2 (a tick on, a tick off) without a window (close up), else from how the
        error compares with his window (a long shot: PULSE_N)."""
        if not window:
            return 2
        a = abs(err)
        return PULSE_N[0] if a > 2 * window else PULSE_N[1] if a > window else PULSE_N[2]

    def _trigger(self, on: bool, now) -> set:
        """ZR held while on him: the game repeats a held trigger at the gun's pace (live: 2.7 shots/s held or tapped
        with the M92F, 25 with the fire-rate mod, which a tapped trigger cannot reach). A pull counts as a shot."""
        if not on:
            if self.fire_down:                               # the aim slid off him: the pull ends
                self._pull_end(now, slipped=True)
            self.fire_down = False
            return set()
        if not self.fire_down:
            self.stats["shots"] += 1
            if self.trigger_since is None:
                self.trigger_since = now
            self._pull_start(now)
        elif self.fire_at is not None:
            self.stats["trigger_s"] = round(self.stats.get("trigger_s", 0.0) + min(now - self.fire_at, 0.2), 2)
            if self.stats["trigger_s"]:
                self.stats["hits_per_trigger_s"] = round(self.stats["hits"] / self.stats["trigger_s"], 2)
        self.fire_down, self.fire_at = True, now
        return {"zr"}

    def _round_start(self, snap, now) -> None:
        """The first tick alive of a round: the engine's marker, once (a marker changed again on a replay made the
        engine close the replay's fresh evidence at once: "ended" rows at 119.9 s in the first MercMode turn); after a
        death answered Yes, the replay counts as the next round (mercs_bot counts only rounds the menus reach)."""
        if self.died:
            self.died = False
            t, start = snap.get("timer"), snap.get("timer_start")
            fresh = isinstance(t, (int, float)) and isinstance(start, (int, float)) and start - t <= FRESH_ROUND_S
            if self.continued == "yes" and fresh:
                self.stats["rounds"] = self.stats.get("rounds", 0) + 1
                self.stats["deaths_continued"] = self.stats.get("deaths_continued", 0) + 1
                self.stats["round_start_via"] = "dead/retry"
                self.target, self.hp_prev, self.hp_seen, self.round_escapes = None, {}, [], 0
                self.look.new_round()
                self._new_round(now)                     # the replay's statues are new units: none counted taken
            self.continued = None
        if self._round_started is None:
            self._round_started = now
            self.look.new_round()
            self._new_round(now)

    def _new_round(self, now) -> None:
        """A round's own state and gauges, at the first round's start and at each replay's (dead/retry: the engine's
        marker stays, the round's statues, clock and gauges start again)."""
        self._round_t0 = now
        self.stats["crowd_max"] = 0
        for kind in FAULT_KINDS:
            self.stats["ex_" + kind] = ""
        self._bonus_known, self._bonus_block, self._bonus, self._timer_prev = {}, {}, None, None
        self._bonus_seen_round = False
        self._walls, self._wall_hist, self._wall_push, self._wall_rec = [], [], None, None
        self._sweep_st, self._reloc, self._dwell, self._clears, self._dwells = None, None, None, [], []
        self._trail, self._dead_ends = [], []
        for k in ("avg_dwell_s", "max_dwell_s", "crowd_cleared_s"):
            self.stats[k] = 0
        self._cam["off"] = False
        self._lock_last, self._lock_score, self._lock_off = None, [0, 0], False
        self._wu, self._windup_e = {}, None
        if self.mines is not None:
            self.mines.new_round(now)
        if self.nades is not None:
            self.nades.new_round(now)
        tuning.apply(MAP_ID, tuning.stage_name(STAGE_NAMES, stage_target()), self.stats)
        self._dead_ends = tuning.dead_ends(MAP_ID)       # the stage's learned dead ends, before this round's own

    def _gun_down(self) -> None:
        if self.fire_down and self._now is not None:
            self._pull_end(self._now)
        self.aim_since, self.fire_down, self.ray_key, self.trigger_since = None, False, None, None
        self._raise_t = None

    # --- survival ----------------------------------------------------------------------------------------------------
    def _heal(self, p, snap, live, flat, now) -> dict | None:
        """The heal (HEAL_* above): its next press, or None (no heal now)."""
        inv = snap.get("inventory")
        if inv is None or not HEAL_ENABLED:
            return None                                     # off, or a snapshot without the inventory reader
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        st = self.healing
        if st is not None:
            if st["player"] != p.get("ptr"):
                self.healing = None
                return None
            count = sum(s["rounds"] for s in inv if s["id"] == st["id"])
            item = next((s for s in inv if s["id"] == st["id"] and s["rounds"] > 0), None)
            done = None
            if count < st["count"] or hp >= st["hp"] + HEAL_GAIN:
                done = "heals"
            elif now - st["at"] >= HEAL_ATTEMPT_S or st["uses"] >= 12 or item is None or item["grid"] not in QUICK:
                done = "heal_failures"
            if done:
                self.stats[done] += 1
                self.stats["heal_status"] = "healed" if done == "heals" else "use unconfirmed"
                self.healing, self.heal_at = None, now
                return self._rearm(inv, st.get("gun"))
            self._gun_down()
            if item["hand"]:
                if now - st["last_use"] >= HEAL_USE_EVERY_S:
                    st["last_use"], st["uses"] = now, st["uses"] + 1
                    return {"tap": HEAL_USE_KEY}
                return {"hold": ()}
            if now - st["equip_at"] >= EQUIP_ACK_S and st["equips"] < 3:
                st["equip_at"], st["equips"] = now, st["equips"] + 1
                return {"tap": QUICK[item["grid"]]}
            return {"hold": ()}
        if hp_max <= 0 or hp <= 1 or hp > HEAL_AT * hp_max or now - self.heal_at < HEAL_RETRY_S:
            return None
        near = sum(1 for e in live if flat(e) < HEAL_SAFE_R)
        if near and hp > HEAL_CRITICAL * hp_max:
            self.stats["heal_deferred"] = f"{near} Majini within {HEAL_SAFE_R / 100:.0f} m at {hp / hp_max:.0%}"
            return None
        item = next((s for s in inv if s["id"] in HEAL_IDS and s["rounds"] > 0 and s["grid"] in QUICK), None)
        if item is None:
            return None
        gun = next((s for s in inv if s["hand"] and s["type"] == 1 and s["item"] not in THROWN), None)
        self._gun_down()
        self.healing = {"player": p.get("ptr"), "id": item["id"], "hp": hp, "at": now, "uses": 0, "last_use": -1e9,
                        "count": sum(s["rounds"] for s in inv if s["id"] == item["id"]), "equips": 1, "equip_at": now,
                        "gun": gun["grid"] if gun else None}
        self.stats["heal_starts"] += 1
        self.stats["heal_status"] = f"healing at {hp / hp_max:.0%} ({near} near)"
        return {"hold": ()} if item["hand"] else {"tap": QUICK[item["grid"]]}

    def _gun_back(self, snap, now) -> dict | None:
        """A grenade or the bomb in hand (THROWN) with nothing else using it: the gun's D-pad slot, a tap every
        GUN_BACK_GAP_S with the pad neutral between, until a gun is in hand. The fight raises with ZL, and ZL with the
        bomb in hand sets one down at his feet."""
        inv = snap.get("inventory") or ()
        held = next((s for s in inv if s.get("hand")), None)
        want = (snap.get("preferred_weapon") or {}).get("item")      # the operator's gun (re5_switch_mods.select_weapon)
        choice = next((s for s in inv if s.get("type") == 1 and s.get("item") == want and s.get("grid") in QUICK
                       and s.get("item") not in KNIVES and s.get("item") not in THROWN), None) if want else None
        if choice is not None and not choice.get("hand") and self.aim_since is None:
            if now - self._gun_back_at < GUN_BACK_GAP_S:
                return {"hold": ()}
            self._gun_back_at = now
            self.stats["gun_choices"] = self.stats.get("gun_choices", 0) + 1
            return {"tap": QUICK[choice["grid"]]}
        if held is None or held.get("type") != 1 or held.get("item") not in THROWN:
            return None
        if self._rearm(inv, None) is None:
            return None                                      # no gun on a D-pad slot: nothing to go back to
        if now - self._gun_back_at < GUN_BACK_GAP_S:
            return {"hold": ()}
        self._gun_back_at = now
        self.stats["gun_backs"] += 1
        return self._rearm(inv, choice["grid"] if choice else None)

    def _rearm(self, inv, grid) -> dict | None:
        """The gun back in his hands after a heal: the one he held (its D-pad slot), else the first gun on one."""
        guns = [s for s in inv if s["type"] == 1 and s["grid"] in QUICK and s["item"] not in KNIVES
                and s["item"] not in THROWN]
        gun = next((s for s in guns if s["grid"] == grid), None) or next(iter(guns), None)
        if gun is None or gun["hand"]:
            return None
        return {"tap": QUICK[gun["grid"]]}

    def _escape(self, p, live, flat, now) -> dict | None:
        """A ring (RING_*): run out through the widest gap between their bearings; None when not ringed."""
        if self.escape is not None:
            out, until = self.escape
            if now < until:
                err = wrap(out - p["rot"])
                if not QUICK_TURN and abs(err) > QUICK_ERR:   # the gap behind him: back toward it while turning
                    return {"hold": ("ldown",) + self._turn(err)}
                return {"hold": RUN + self._turn(err, TURN_TOL)}
            self.escape = None
        if now - self.escape_at < ESCAPE_GAP_S or self.round_escapes >= ESCAPES_MAX:
            return None
        px, _, pz = p["pos"]
        hurt = (p.get("hp") or 0) < HURT * (p.get("hp_max") or 0)
        limits = (TIGHT if hurt or HEALTHY_ESCAPES else ()) + (((RING_N, RING_R),) if hurt else ())
        ring = None
        for n, r in limits:
            near = sorted(heading(e["pos"][0] - px, e["pos"][2] - pz) for e in live if flat(e) < r)
            if len(near) >= n:
                ring = near
                break
        if ring is None:
            return None
        gaps = [((ring[(i + 1) % len(ring)] - a) % (2 * math.pi) or 2 * math.pi, a) for i, a in enumerate(ring)]
        gap, start = max(gaps)
        if gap >= RING_GAP:
            return None                                     # an open side: fight on
        out = wrap(start + gap / 2)
        self._gun_down()
        self.escape, self.escape_at = (out, now + ESCAPE_S), now
        self.round_escapes += 1
        self.stats["escapes"] += 1
        err = wrap(out - p["rot"])
        if QUICK_TURN and abs(err) > QUICK_ERR and now - self.quick_at > QUICK_GAP_S:
            self.stats["quick_turns"] += 1                   # the gap behind him: the quick turn first, then the run
            self.quick = 2
            self.escape = (out, now + ESCAPE_S + 0.6)
            return {"hold": ("ldown",)}
        if not QUICK_TURN and abs(err) > QUICK_ERR:
            return {"hold": ("ldown",) + self._turn(err)}
        return {"hold": RUN + self._turn(err, TURN_TOL)}

    # --- the decision ----------------------------------------------------------------------------------------------
    def tick(self, snap: dict) -> dict:
        now = self.clock()
        self.doing, self.why, self._now = "none", "", now
        held = next((s for s in snap.get("inventory") or () if s.get("hand")), None)
        self._item = held.get("item") if held else None       # the weapon in hand (K's plans are per weapon)
        act = self._tick(snap, now)
        act = self._wall_gov(act, snap, now)
        act = self._calm_sticks(act, snap, now)
        act = self._governor(act, snap, now)
        self._count_sticks(act, now)
        try:
            self._look_tick(snap, now)
        except Exception as exc:                             # noqa: BLE001 - the look never stops the bot
            self.stats["look_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return act

    def _tick(self, snap: dict, now: float) -> dict:
        p = snap.get("player")
        if not p:
            self._gun_down()
            return {"hold": ()}
        if self.fighter is not None:
            try:
                self.fighter.observe(snap, now)              # its shot / hit / kill accounting, every tick
            except Exception as exc:                         # noqa: BLE001 - accounting never stops the bot
                self.stats["brain_error"] = f"observe {type(exc).__name__}: {exc}"[:160]
        if (p.get("hp") or 0) <= 0:
            self.doing, self.why = "dead", "Continue?"
            self._gun_down()
            if not self.died and self.fighter is not None:
                self.fighter.end_round(now)                  # the round's shots resolved, its calibration learned
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
        last, self._hp_track = self._hp_track, (p.get("ptr"), p.get("hp"))
        if last is not None and last[0] == p.get("ptr") and type(p.get("hp")) is int and type(last[1]) is int                 and p["hp"] < last[1]:
            if now - self._hit_at > 0.5:                 # his health fell (a hit, a blast; a squeeze counts once)
                self.stats["hits_taken"] += 1
            self._hit_at = now
        act = self._prompt(p, snap, now)                 # the game's own prompt: taken the moment it shows
        if act is not None:
            self._gun_down()
            return act
        if self.quick:                                       # the quick turn: the stick back, + B, let go
            self.doing, self.why = "quick_turn", f"step {self.quick}"
            step, self.quick = self.quick, (self.quick + 1) % 4
            if step == 2:
                self.quick_at = now
            return {"hold": ("ldown",) if step == 1 else ("ldown", "b") if step == 2 else ()}
        if now - self.quick_at < QUICK_SETTLE_S:             # it swings round by itself
            self.doing, self.why = "quick_turn", "settling"
            return {"hold": ()}
        px, py, pz = p["pos"]
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        near_e = min(live, key=flat, default=None)
        near = flat(near_e) if near_e is not None else math.inf
        motion = p.get("motion")                         # None: no motion byte (the health / stick heuristics)
        # Held means the game's own grab (his motion, or its Break free prompt), never a Majini merely close: the
        # learning loop's replay (#1403) found him shaking the stick with one within HELD_R that held nothing while
        # swarmed ("RE5 swarmed with the gun LOWERED = 20 deaths" in 24 h). HELD_R stands in only without a motion byte;
        # the stuck rule (the sticks pressed, no move) only with nobody within RAMPAGE_R (geometry, not a crowd).
        grab_prompt = ((snap.get("prompt") or {}).get("label") == re5_switch_prompt.LABEL_BREAK_FREE)
        held = motion in MOTION_HELD or grab_prompt or (motion is None and near < HELD_R) or p.get("hp") == DYING_HP
        if motion in MOTION_HELD and not self._was_held:
            self._grab_at = now                          # a grab began (hits_after_windup)
        self._was_held = motion in MOTION_HELD
        stuck = self.held(p, now) and (motion is None or near > RAMPAGE_R)
        if held or now < self.break_until or (motion is None and self.grabbed(p, near, now)) or stuck:
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
            self.doing, self.why = "held", ("dying" if dying else f"motion {motion}" if held else "stuck, breaking free")
            pattern = MASH if dying else WIGGLE
            return {"hold": pattern[self.wiggle % len(pattern)]}
        self.in_hold = False
        if motion == MOTION_RELOAD and self.aim_since is not None:
            self.doing, self.why = "reload", "the gun reloads"
            self.aim_since = now                             # reloading: the gun comes back up by itself
            return {"hold": ("zl",)}
        if self.mines is not None and snap.get("mine_settings"):
            self.mines.configure(snap["mine_settings"])          # the operator's `mines` op (re5_switch_mods.mines)
        self.mode = self._operator_command(p, snap, live, now)
        act = self._heal(p, snap, live, flat, now)
        if act is not None:
            self.doing, self.why = "heal", str(self.stats.get("heal_status") or "")
        elif self.nades is not None and (act := self.nades.tick(p, snap, live, now, busy=self.escape is not None,
                                                                  winding=self._winding, mines=self.mines)) is not None:
            self._gun_down()                                 # (its own ZL / ZR: the fight raises afresh after it)
            self.doing, self.why = "flash", str(self.stats.get("flash_status") or "")
        elif self.mines is not None and (act := self.mines.tick(p, snap, live, now,
                                                                  busy=self.escape is not None)) is not None:
            self._gun_down()
            self.doing, self.why = "mine", str(self.stats.get("mine_status") or "")
        else:
            act = self._escape(p, live, flat, now)
            if act is not None:
                self.doing, self.why = "escape", f"{self.round_escapes} this round"
            elif (act := self._gun_back(snap, now)) is not None:
                self._gun_down()
                self.doing, self.why = "rearm", "the gun back first (a grenade or bomb in hand, or the operator's gun)"
            elif self.fighter is not None:
                act = self._fight(live, snap, now)
            else:
                act = self._decide(p, live, flat, near_e, near, snap, now)
        if set(act.get("hold", ())) & {"rleft", "rright", "lup", "ldown"} and "zl" not in act.get("hold", ()):
            self.move_at = now
        return act

    def _operator_command(self, p, snap, live, now) -> str | None:
        """The operator's instant commands (gbox.mercs.directives, the PS3 bot's set): one-shots act on the tick they
        arrive, the standing modes (fight / hunt / score) are returned for the fight to apply. A command never presses
        a key itself: the fight, the heal, the escape and the bombs' rules still decide every press."""
        from ..directives import Reader
        if self.commands is None:
            self.commands = Reader()
        cmd, fresh = self.commands.current(self.stats, time.time())
        if cmd is None:
            return None
        self.stats["directive_active"] = cmd
        if fresh:
            self.stats["directive_status"] = "acting: " + cmd
        if cmd == "mine" and fresh:
            self.stats["directive_status"] = self._mine_now("mine due now: placed at the next safe moment, then out of "
                                                            "its blast")
        elif cmd == "mine_trail":
            busy = self.mines is not None and self.mines.state != "idle"
            self.stats["directive_status"] = "mine trail: placing or leaving the last bomb" if busy else                 self._mine_now("mine trail: due now, placed at the next safe spot, then moving on")
        elif cmd == "repetitive" and fresh:
            if self.target is not None:
                self.blocked[self.target] = now + 15.0
            self.target, self.aim_since = None, None
            self.stats["directive_status"] = "dropped the target he kept at; choosing another for 15 s"
        elif cmd in ("next_area", "explore") and fresh:
            self.stats["directive_status"] = "not yet on Switch: no level map to route by; fighting on where he stands"
        elif cmd == "missing" and fresh:
            self.stats["directive_status"] = ("the Switch fight closes the laser dot on him before every shot: no learned "
                                              "aim offset to reset")
        return cmd if cmd in ("fight", "hunt", "score") else None

    def _mine_now(self, ok: str) -> str:
        m = self.mines
        if m is None or not m.enabled:
            return "mine placement is switched off (the mines setting)"
        if m.state == "idle":
            m.last_at = self._now - m.every_s - 1.0 if self._now is not None else None   # due now: its checks still apply
        return ok

    def _decide(self, p, live, flat, near_e, near, snap, now) -> dict:
        px, py, pz = p["pos"]
        self._goal_dy = None                             # (set again by the bonus run / the pursuit this tick)
        if self.blocked:
            self.blocked = {k: t for k, t in self.blocked.items() if t > now}
            rest = [e for e in live if e.get("ptr", e.get("slot")) not in self.blocked]
            live = rest or live
        self._fault_tick(p, live, flat, snap, now)
        if not live:
            act = self._go_bonus(p, live, flat, snap, now)
            if act is not None:
                return act
            act = self._rampage(p, live, flat, snap, now)   # (the circle clear: the main gun back)
            if act is not None:
                return act
            act = self._pursue(p, live, flat, snap, now)
            if act is not None:
                return act
            others = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0]
            if self.mode in ("fight", "hunt") and others:     # nobody on his level: go to the nearest one anywhere
                tgt = min(others, key=lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz))
                err = wrap(heading(tgt["pos"][0] - px, tgt["pos"][2] - pz) - p["rot"])
                self.doing, self.why = "walk", f"{self.mode}: the nearest Majini off his level"
                self._gun_down()
                return {"hold": ("lup",) + self._turn(err, TURN_TOL)}
            self.doing, self.why = "no_foes", "no Majini alive on his level"
            self._gun_down()
            return {"hold": ()}
        if self.mode == "hunt" and near > HUNT_R and self.aim_since is None:   # hunt: close in on the nearest
            err = wrap(heading(near_e["pos"][0] - px, near_e["pos"][2] - pz) - p["rot"])
            self.doing, self.why = "walk", f"hunt: the nearest {near / 100:.1f} m"
            self._gun_down()
            return {"hold": ("lup",) + self._turn(err, TURN_TOL)}
        self._track_approach(p, live, now)
        self._threat_now = self._threat_near(p, live)
        crowded = NEAR_FOCUS and any(flat(e) <= RAMPAGE_R and abs(e["pos"][1] - py) <= LEVEL_DY for e in live)
        if crowded:                                      # someone near: the far ones are no concern now
            live = [e for e in live if flat(e) <= NEAR_FOCUS_R] or live
        self._crowded = crowded
        self._windup_tick(p, live, flat, now)
        act = self._quick_behind(p, live, flat, now)    # one close behind: the quick turn (stick back + B)
        if act is not None:
            return act
        act = self._sweep(p, live, flat, snap, now)     # crowded within 5 m: the turret sweep first (off)
        if act is not None:
            return act
        act = self._rampage(p, live, flat, snap, now)   # crowded: the shotgun, front-facing (CROWD_FIRE)
        if act is not None:
            return act
        act = self._relocate(p, live, flat, snap, now)  # then keep moving: no spot held long
        if act is not None:
            return act
        act = self._go_bonus(p, live, flat, snap, now)
        if act is not None:
            return act
        act = self._pursue(p, live, flat, snap, now)
        if act is not None:
            return act
        urgent = self._combo_urgent(snap)
        if urgent:                                           # the combo window runs down: the quickest kill
            self.stats["combo_pushes"] += 1
            reach = [e for e in live if flat(e) <= COMBO_REACH]
            if not reach and self.aim_since is None:         # nobody in reach: run to the nearest, the gun down
                err = wrap(heading(near_e["pos"][0] - px, near_e["pos"][2] - pz) - p["rot"])
                self.doing, self.why = "walk", f"combo {snap.get('combo')}: the nearest {near / 100:.1f} m"
                self._gun_down()
                return {"hold": ("lup", "b") + self._turn(err, TURN_TOL)}
        if urgent and reach and not self._threat_now:        # (a threat near: the threat pick is the quickest kill)
            tgt = min(reach, key=lambda e: self._cost(p, e))
            self._set_target(tgt.get("ptr", tgt.get("slot")), now)
        else:
            tgt = self._choose(p, live, now) if self.mode != "score" else min(live, key=flat)   # score: the nearest
        if self.mode == "score":
            self.target = tgt.get("ptr", tgt.get("slot"))
        foot = tgt["pos"]
        dist = flat(tgt)
        body_err = wrap(heading(foot[0] - px, foot[2] - pz) - p["rot"])
        self.stats["target_dist"] = round(dist)
        if dist > ENGAGE_R:                                  # nobody in range: walk to him
            self.doing, self.why = "walk", f"nearest target {dist / 100:.1f} m"
            self._gun_down()
            return {"hold": ("lup",) + self._turn(body_err, TURN_TOL)}
        motion = p.get("motion")
        if self.aim_since is None:
            if now < self.backoff_until:                     # a back-off under way (a crowd's burst ended it): finish it
                self.doing, self.why = "backoff", "finishing a back-off"
                return {"hold": ("ldown",) + self._turn(body_err)}
            if now < self._crowd_until:                      # a crowd move under way: on, still turning to him
                self.doing, self.why = "backoff", f"moving out of the crowd ({','.join(self._crowd_keys)})"
                return {"hold": self._crowd_keys + self._turn(body_err)}
            near_err = wrap(heading(near_e["pos"][0] - px, near_e["pos"][2] - pz) - p["rot"])
            if CLOSE_BACKOFF and near < TOO_CLOSE and abs(near_err) <= BACKOFF_CONE:   # one in his face: step back
                if now >= self.backoff_ready:
                    self.backoff_until, self.backoff_ready = now + BACKOFF_S, now + BACKOFF_S + BACKOFF_GAP_S
                    self.stats["backoffs"] += 1
                if now < self.backoff_until:
                    self.doing, self.why = "backoff", f"one {near / 100:.1f} m in front"
                    return {"hold": ("ldown",) + self._turn(body_err)}
            if QUICK_TURN and abs(body_err) > QUICK_ERR and now - self.quick_at > QUICK_GAP_S                     and (not CALM or dist <= CALM_QUICK_R) and (now - self.quick_at >= QUICK_BACK_S or dist <= GRAB_THREAT_R):
                self.doing, self.why = "quick_turn", f"target behind ({math.degrees(body_err):+.0f} deg)"
                self.stats["quick_turns"] += 1               # him behind: the quick turn
                self.quick = 2
                return {"hold": ("ldown",)}
            tol = self.raise_tol(dist) * (RERAISE_FRAC if piece(SMOOTH_FAR) and self.turning and near > THREAT_R else 1.0)
            if abs(body_err) > tol:                          # turn round first (fast, the gun down)
                self.doing, self.why = "turn", f"target {math.degrees(body_err):+.0f} deg at {dist / 100:.1f} m"
                self.stats["turns"] += 1
                self.turning = True
                return {"hold": self._turn(body_err)}
            self.turning = False
            self.aim_since = self._raise_t = now
            self._lower_pitch, self._first_ray = self._ray_pitch, True
            self._first_check, self._raise_is_reroll, self._reroll_next = True, self._reroll_next, False
            self.stats["raises"] += 1
            self.ray_seen = self.last_ray = None
        lz = snap.get("laser")
        gun = next((s for s in snap.get("inventory") or () if s.get("hand")), None)
        weapon = f"0x{gun['id']:03x}" if gun else "gun"
        if lz is None:                                       # no laser unit at all: the body's heading stands in
            self.doing, self.why = "raise", "no laser unit"
            if now - self.aim_since < READY_S:
                return {"hold": ("zl",)}
            self.stats["laserless"] += 1
            self._aimctx = {"target": tgt.get("ptr", tgt.get("slot")), "dist": dist, "bearing": body_err,
                            "yaw_err": body_err, "where": None, "laserless": True, "weapon": weapon,
                            "gate": "laserless: the body's heading"}
            fire = abs(body_err) <= AIM_TOL
            self.doing, self.why = ("fire", "laserless heading") if fire else ("aim", "laserless heading")
            keys = {"zl"} | (self._trigger(True, now) if fire else self._yaw(body_err))
            return {"hold": tuple(sorted(keys))}
        fresh_ray = False
        if lz.get("up") and now - self.aim_since >= READY_S:
            fresh_ray = True
            ray = (tuple(lz["from"]), tuple(lz["at"]))
            self._track_pitch_rate(ray, now)
            self._note_ray_pitch(ray, tgt, dist)
            self.ray_seen, self.last_ray = now, ray
            if ray != self.ray_key:
                self.ray_key, self.ray_since = ray, now
            elif now - self.ray_since > RAY_STALE_S and not (CROWD_FIRE and near <= RAMPAGE_R):
                self.doing, self.why = "restale", f"the ray unchanged {RAY_STALE_S:.0f} s"
                self.stats["restale"] += 1                   # a frozen ray: not a live aim
                self._gun_down()
                return {"hold": ()}
        elif self.last_ray is not None and motion in MOTION_AIM and now - self.ray_seen <= FLICKER_S:
            ray = self.last_ray                              # the laser read down in the shot: the gun is up, aim on
            self.stats["flicker_s"] = round(self.stats["flicker_s"] + min(now - (self._tick_t or now), LOOK_STEP_MAX_S), 2)
        else:                                                # the gun is coming up (or knocked down)
            waited = now - max(self.aim_since, self.ray_seen if self.ray_seen is not None else -math.inf)
            if (waited > LASER_WAIT_S and motion not in MOTION_AIM and motion != MOTION_RELOAD) or waited > LASER_STUCK_S:
                self.doing, self.why = "reraise", f"no laser after {waited:.2f} s (motion {motion})"
                self.stats["reraise"] += 1                   # it did not come up: let ZL go a tick, press it again
                self._gun_down()
                return {"hold": ()}
            self.doing, self.why = "raise", f"the gun coming up (motion {motion})"
            if self.fire_down:
                self._trigger(False, now)
            if AIM_LOCK and snap.get("aim_cam"):         # no raise from an old pitch: the target's elevation first
                _yaw, perr = self._lock_errors(p, snap, foot, CHEST_H, dist)
                if perr is not None and abs(perr) > math.radians(AIM_LOCK_SNAP_DEG) \
                        and self._lock_aim(snap, {"zl"}, None, perr, now) == {"zl"}:
                    self.stats["aim_lock_prepitch"] += 1
            if SKY_GUARD and motion == MOTION_AIMED and waited > SKY_BLIND_S \
                    and (self._ray_pitch is None or self._ray_pitch > -math.radians(5)):
                self.stats["sky_blind_ticks"] += 1           # aimed, no dot anywhere: the ray on the sky; down
                self.why = f"aimed with no laser {waited:.2f} s: the aim down (the sky)"
                return {"hold": ("rdown", "zl")}
            return {"hold": ("zl",)}
        origin, dot = ray
        frozen = self._frozen_dot(p, dot, fresh_ray)
        if frozen and CROWD_FIRE and near <= RAMPAGE_R:
            frozen = False                               # one within 5 m: no re-raise (the gun stays up)
        if frozen:                                       # the dot stood still while the aim moved: no live aim
            self.stats["frozen_dots"] += 1
            self.doing, self.why = "restale", f"the dot frozen {FROZEN_TICKS} ticks while the aim moved"
            self._example("frozen_dot", p, now, f"dot ({dot[0]:.0f},{dot[1]:.0f},{dot[2]:.0f}) "
                                                f"ray {math.dist(origin, dot) / 100:.1f} m")
            self._gun_down()
            return {"hold": ()}
        on_e = next((e for e in live if dot_on(dot, e["pos"])
                     and not (self._threat_now and flat(e) > THREAT_CAP_R)), None)   # threat first: none far off
        other = on_e.get("ptr", on_e.get("slot")) if on_e is not None and on_e is not tgt else None
        self.dot_other = (other, self.dot_other[1] + 1 if other is not None and other == self.dot_other[0] else
                          (1 if other is not None else 0))
        if other is not None and (not piece(SMOOTH_DOT) or self.dot_other[1] >= DOT_SWITCH_TICKS
                                  or flat(on_e) < GRAB_THREAT_R):
            tgt, foot = on_e, on_e["pos"]                    # the dot stays on another one: he is the target now
            self._set_target(other, now)
            dist = flat(tgt)
            body_err = wrap(heading(foot[0] - px, foot[2] - pz) - p["rot"])
        aim_h = self._aim_h(tgt, dist, now)
        chest = (foot[0], foot[1] + aim_h, foot[2])
        yaw_err, pitch_err = ray_error(origin, dot, chest)
        ray_len = math.dist(origin, dot)
        have_p = math.atan2(dot[1] - origin[1], max(math.hypot(dot[0] - origin[0], dot[2] - origin[2]), 1.0))
        want_p = math.atan2(chest[1] - origin[1], max(math.hypot(chest[0] - origin[0], chest[2] - origin[2]), 1.0))
        cam_read = CAM_GUARD and not self._cam["off"] and p.get("aim_pitch") is not None
        if fresh_ray and self._first_check and ray_len >= STEER_RAY_CM and not cam_read:
            self._first_check = False
            if not self._raise_is_reroll and have_p > want_p + REROLL_ERR:
                self._reroll_next = True                 # the raise came up high: down and up again, once
                self.stats["raise_rerolls"] += 1
                self.doing, self.why = "reraise", (f"the first ray {math.degrees(have_p):+.0f} deg, wanted "
                                                   f"{math.degrees(want_p):+.0f} deg: raised again")
                self._gun_down()
                return {"hold": ()}
        point_blank = ray_len < POINT_BLANK_RAY and dist <= POINT_BLANK_R and abs(body_err) <= self.raise_tol(dist)
        far_off = abs(yaw_err) > UNAIM_ERR and not point_blank
        self.unaim_since = (self.unaim_since or now) if far_off else None
        if far_off:                                          # the aim is far off him
            pool = [e for e in live if flat(e) <= THREAT_CAP_R] if self._threat_now else live
            alt = self._near_aim(origin, dot, pool, flat) if ray_len >= STEER_RAY_CM else None
            hold = piece(SMOOTH_FAR) and near > THREAT_R and abs(yaw_err) <= UNAIM_HARD \
                and (now - self.unaim_since < UNAIM_HOLD_S or now - self.aim_since < MIN_UP_S)
            if alt is None and hold:                         # a moment off him, or just raised: the aim turns, gun up
                far_off = False
        if far_off and alt is None and CROWD_FIRE and near <= RAMPAGE_R:
            self.stats["unaim_holds"] += 1               # one within 5 m: the gun stays up, the aim turns to him
            self.doing, self.why = "aim", (f"aim {math.degrees(yaw_err):+.0f} deg off at {dist / 100:.1f} m: turning "
                                           f"the aim (one within {RAMPAGE_R / 100:.0f} m: the gun stays up)")
            keys = {"zl"} | (self._yaw(yaw_err) if motion != MOTION_SHOT else set())
            if self.fire_down:
                self._trigger(False, now)
            return {"hold": tuple(sorted(keys))}
        if far_off:
            if alt is None:                                  # nobody near the aim: gun down, turn the body
                self.stats["unaims"] += 1
                if near <= RAMPAGE_R:
                    self.stats["unaims_in_5m"] += 1
                self.doing, self.why = "unaim", (f"aim {math.degrees(yaw_err):+.0f} deg off at {dist / 100:.1f} m "
                                                 f"(ray {ray_len / 100:.1f} m)")
                self._gun_down()
                return {"hold": self._turn(body_err)}
            tgt, foot = alt, alt["pos"]                      # another one near the aim: him, the gun stays up
            self._set_target(tgt.get("ptr", tgt.get("slot")), now)
            self.target_at = now
            dist = flat(tgt)
            body_err = wrap(heading(foot[0] - px, foot[2] - pz) - p["rot"])
            aim_h = self._aim_h(tgt, dist, now)
            chest = (foot[0], foot[1] + aim_h, foot[2])
            yaw_err, pitch_err = ray_error(origin, dot, chest)
        where = dot_on(dot, foot)
        on = where is not None or point_blank or through(origin, dot, foot)
        self._ap_now = p.get("aim_pitch")
        self._pitch_up(origin, dot, chest, tgt, dist, now)
        if self._threat_now and dist > THREAT_CAP_R:
            self.stats["far_aim_ticks"] += 1                 # (none expected: every path above is capped)
        if self._crowded and dist > NEAR_FOCUS_R:
            self.stats["far_picks_while_crowded"] += 1       # (target 0: the pool above is the near ones)
        ray_len, chest_len = math.dist(origin, dot), math.dist(origin, chest)
        dot_e = next((e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and e.get("pos")
                      and dot_on(dot, e["pos"]) and not (self._crowded and flat(e) > NEAR_FOCUS_R)), None)
        if on and where is None and not point_blank and ray_len < chest_len - WALL_SLACK and dot_e is None:
            on = False                                   # the ray ends on something short of him: no shot
            if self._wall_since is None:
                self.stats["wall_shots"] += 1
                self._example("wall_shot", p, now, f"target {dist / 100:.1f} m, the ray {ray_len / 100:.1f} m, "
                                                   f"dot ({dot[0]:.0f},{dot[1]:.0f},{dot[2]:.0f})")
        wall_dt = 0.0 if self._wall_t is None else max(0.0, min(now - self._wall_t, LOOK_STEP_MAX_S))
        self._wall_t = now
        if not on and dot_e is None and ray_len > POINT_BLANK_R and ray_len < chest_len - FIRE_SLACK:
            self.stats["wall_aim_s"] = round(self.stats["wall_aim_s"] + wall_dt, 2)   # the gun on a wall (target 0)
            self._wall_since = self._wall_since or now   # the dot short of him on geometry
            if now - self._wall_since >= WALL_DROP_S:
                key0 = tgt.get("ptr", tgt.get("slot"))
                self.blocked[key0] = now + WALL_BLOCK_S  # leave him a moment: another one
                self.stats["wall_blocks"] += 1
                self._example("wall_block", p, now, f"target {dist / 100:.1f} m behind geometry at "
                                                    f"{ray_len / 100:.1f} m")
                self._wall_since = None
                self.target = None
        elif on or dot_e is not None:
            self._wall_since = None
        confirmed = False
        if CONFIRMED_FIRE and not on and dot_e is not None and dot_e is not tgt \
                and not any(flat(e) < GRAB_THREAT_R and e is not dot_e for e in live):
            tgt, foot = dot_e, dot_e["pos"]              # the dot on a living Majini: the shot, whoever he is
            where, on, confirmed = dot_on(dot, foot), True, True
            dist = flat(tgt)
            body_err = wrap(heading(foot[0] - px, foot[2] - pz) - p["rot"])
            self.stats["confirmed_shots"] += 1
        if dist < CLOSE_PITCH_R and not on and have_p > CLOSE_SKY and not cam_read:
            self._close_sky_since = self._close_sky_since or now
            if now - self._close_sky_since >= CLOSE_SKY_S:     # up close and pointing up: down and up again
                self.stats["close_sky_reraises"] += 1
                self.doing, self.why = "reraise", (f"the laser {math.degrees(have_p):+.0f} deg up with him "
                                                   f"{dist / 100:.1f} m away: raised again")
                self._example("sky", p, now, f"close: the laser {math.degrees(have_p):+.0f} deg, wanted "
                                             f"{math.degrees(want_p):+.0f} deg at {dist / 100:.1f} m")
                self._close_sky_since = None
                self._gun_down()
                return {"hold": ()}
        else:
            self._close_sky_since = None
        fix = self._aim_away(p, live, flat, origin, dot, confirmed, now)
        if fix is not None:
            if CROWD_FIRE and near <= RAMPAGE_R:         # one within 5 m: the aim turns to him, the gun stays up
                e = next((x for x in live if x.get("ptr", x.get("slot")) == self.target), None)
                if e is not None:
                    err = ray_error(origin, dot, (e["pos"][0], e["pos"][1] + CHEST_H, e["pos"][2]))[0]
                    self.aim_since = self.aim_since or now
                    self.doing = "aim"
                    return {"hold": tuple(sorted({"zl"} | (self._yaw(err) if motion != MOTION_SHOT else set())))}
            return fix
        if piece(SMOOTH_DOT) and not on and other is not None and self.target != other:
            other_where = dot_on(dot, on_e["pos"])           # the dot on another Majini, not yet the target: shoot him
            if other_where is not None:                      # now (the trigger), the aim kept where it is (no swing)
                tgt, foot, where, on = on_e, on_e["pos"], other_where, True
                dist = flat(tgt)
                body_err = wrap(heading(foot[0] - px, foot[2] - pz) - p["rot"])
                self.stats["dot_shots"] = self.stats.get("dot_shots", 0) + 1
        key = tgt.get("ptr", tgt.get("slot"))
        self.on_ticks = self.on_ticks + 1 if on and key == self.on_key else (1 if on else 0)
        self.on_key = key if on else None
        long_shot = dist > LONG_R and near > LONG_CLEAR_R    # a far Majini, nobody close: with care
        settling = long_shot and on and not confirmed and not self.fire_down and self.on_ticks < SETTLE_TICKS
        if settling:
            on = False                                       # the dot on him a tick: wait for it to stay
        windows = (math.atan2(BODY_R, max(dist, 1.0)), math.atan2((SHOULDER_H - KNEE_H) / 2, max(dist, 1.0))) \
            if long_shot else (None, None)
        front = sum(1 for e in live if flat(e) < FRONT_R
                    and abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - p["rot"])) <= FRONT_CONE)
        if on and dist > LONG_KILL_R:
            self._long_marks[tgt.get("ptr", tgt.get("slot"))] = now
        if on and where is None and not point_blank and not confirmed and not self.fire_down:
            self.stats["through_shots"] += 1
        crowd = [e for e in live if flat(e) <= CROWD_R]
        if CROWD_MOVES and len(crowd) >= CROWD_N and now - self.aim_since >= CROWD_BURST_S and now >= self._crowd_ready \
                and not (confirmed and dist > LONG_R) and not (CROWD_FIRE and near <= RAMPAGE_R):
            self._crowd_keys = self._escape_keys(p, crowd)
            self._crowd_until, self._crowd_ready = now + CROWD_MOVE_S, now + CROWD_MOVE_S + CROWD_GAP_S
            self.stats["crowd_moves"] += 1
            self.doing, self.why = "backoff", f"{len(crowd)} within {CROWD_R / 100:.0f} m: the gun down, moving out"
            self._gun_down()
            return {"hold": self._crowd_keys + self._turn(body_err)}
        if BURST_BACKOFF and front >= FRONT_N and self.trigger_since is not None and now - self.trigger_since >= BURST_S:
            self.doing, self.why = "burst_backoff", f"{front} in front after a {now - self.trigger_since:.1f} s burst"
            self.stats["burst_backoffs"] += 1                # a crowd in front: the burst is done, step back, burst again
            self._gun_down()
            self.backoff_until = now + BACKOFF_S
            return {"hold": ("ldown",)}
        self._aimctx = {"target": tgt.get("ptr", tgt.get("slot")), "dist": dist, "bearing": body_err,
                        "yaw_err": yaw_err, "where": where, "laserless": False, "weapon": weapon, "origin": origin,
                        "dot": dot, "py": py, "class": tgt.get("class"), "foot": tuple(foot), "hp_max": tgt.get("hp_max"),
                        "item": gun.get("item") if gun else None, "shooter": tuple(p["pos"]),
                        "gate": f"dot on {where}" if where else "point blank" if point_blank else "ray through him"}
        self.doing = "fire" if on else "aim"
        self.why = (f"{where or ('point blank' if point_blank else 'ray')} at {dist / 100:.1f} m"
                    + (" (long shot)" if long_shot else "") if on else
                    f"settling on him at {dist / 100:.1f} m" if settling else
                    f"yaw {math.degrees(yaw_err):+.1f} pitch {math.degrees(pitch_err):+.1f} at {dist / 100:.1f} m"
                    + (" (long shot)" if long_shot else ""))
        if long_shot:
            self.stats["long_shot_ticks"] = self.stats.get("long_shot_ticks", 0) + 1
        held = next((x for x in reversed(self._pulls) if x["end"] is None), None) if self.fire_down else None
        if held is not None and held["target"] != self._aimctx["target"] \
                and (self.hp_prev.get(held["target"]) or 0) > 0:     # a living target left with the trigger held
            self.stats["drops_mid_burst"] += 1
            self._pull_end(now)
            self.fire_down = False                           # (ZR stays down: the next pull is on the new one)
        cam_up = self._cam_up(p, foot, dist, now)       # the aim's own pitch up at one on his level: down, no sky shot
        if cam_up and on and where is None and not confirmed:
            on = False
            self.doing = "aim"
        keys = {"zl"} | self._trigger(on, now)
        if not on and not settling and math.dist(origin, dot) >= min(STEER_RAY_CM, 0.5 * math.dist(origin, chest)):
            keys |= self._yaw(yaw_err, windows[0]) | self._pitch_settled(pitch_err, windows[1], now)   # steer only off him: a raised fire rate paces the
                                                                  # aim with the shot (re5_switch_mods)
        if dist < CLOSE_PITCH_R and keys & {"rup", "rdown"}:
            keys -= {"rup", "rdown"}                     # up close: the yaw only (by the laser) ...
            self.stats["close_pitch_skips"] += 1
        if cam_up:                                       # ... but the aim's own pitch up: down, at any range
            keys = (keys - {"rup"}) | {"rdown"}
            self.why = f"aim pitch {math.degrees(-p['aim_pitch']):+.0f} deg up: down; {self.why}"
        if motion == MOTION_SHOT and keys & {"rleft", "rright", "rup", "rdown"}:
            keys -= {"rleft", "rright", "rup", "rdown"}  # the shot plays at fire_rate's time scale: the stick waits
            self.stats["shot_stick_drops"] += 1
        if AIM_LOCK and snap.get("aim_cam"):             # the RAM aim lock: the aim by RAM, the stick only as a fallback
            keys = self._lock_aim(snap, keys, *self._lock_errors(p, snap, foot, aim_h, dist, origin, dot), now)
        keys = self._sky_guard(origin, dot, chest, on, point_blank, keys)
        if self._pu_detail is not None:
            self.stats["pitch_up_last"] = (f"{self._pu_detail}; {self.doing}: {self.why}; "
                                           f"keys {','.join(sorted(keys))}")
            self._pu_detail = None
        self.stats["aim"] = (f"d {dist:.0f} yaw {math.degrees(yaw_err):+.1f} pitch {math.degrees(pitch_err):+.1f} "
                             + (f"own {-math.degrees(p['aim_pitch']):+.0f} " if p.get("aim_pitch") is not None else "")
                             + f"laser {math.degrees(have_p):+.0f} "
                             f"dot_dy {dot[1] - foot[1]:+.0f} on {where or ('ray' if on else '-')} "
                             f"keys {','.join(sorted(keys))}")
        return {"hold": tuple(sorted(keys))}

    def _cam_up(self, p, foot, dist, now) -> bool:
        """The aim's own pitch (P_AIM_PITCH) more than CAM_UP_MAX up while aimed at a Majini on his level within
        THREAT_CAP_R (CAM_GUARD above). Pressed down CAM_CHECK_S and it went up instead: off for the round."""
        c, ap = self._cam, p.get("aim_pitch")
        want_up = math.atan2(foot[1] + CHEST_H - p["pos"][1] - MUZZLE_H, max(dist, 1.0))   # his chest's elevation
        if not CAM_GUARD or c["off"] or ap is None or -ap <= max(want_up, 0.0) + CAM_UP_MAX or dist > THREAT_CAP_R                 or abs(foot[1] - p["pos"][1]) > LEVEL_DY:
            c["down_since"], c["on"] = None, False
            return False
        self.stats["cam_up_ticks"] += 1
        if not c["on"]:
            self.stats["cam_up_fixes"] += 1
            self._example("sky", p, now, f"the aim {math.degrees(-ap):+.0f} deg up at one {dist / 100:.1f} m away")
        c["on"] = True
        if c["down_since"] is None:
            c["down_since"], c["ap0"] = now, ap
        elif now - c["down_since"] >= CAM_CHECK_S:
            if ap < c["ap0"] - 0.05:                     # pressed down and it went further up: not this stick
                self.stats["cam_pitch_inverted"] += 1
                c["off"], c["on"], c["down_since"] = True, False, None
                return False
            c["down_since"], c["ap0"] = now, ap
        return True

    def _sky_guard(self, origin, dot, chest, on, point_blank, keys) -> set:
        """The laser more than SKY_MARGIN above the target's elevation: the pitch-up stick out, the pitch-down in."""
        if point_blank or math.dist(origin, dot) < SKY_RAY_CM:
            self._sky = False
            return keys
        have = math.atan2(dot[1] - origin[1], max(math.hypot(dot[0] - origin[0], dot[2] - origin[2]), 1.0))
        elev = math.atan2(chest[1] - origin[1], max(math.hypot(chest[0] - origin[0], chest[2] - origin[2]), 1.0))
        if have > PITCH_UP_LOG and elev < SKY_LOW:
            self.stats["sky_ticks"] += 1
            if self._now is not None and self.stats.get("_sky_ex_at", -1e9) < self._now - 1.0:
                self.stats["_sky_ex_at"] = self._now
                self._example("sky", {"pos": (origin[0], origin[1] - MUZZLE_H, origin[2]), "rot": 0.0}, self._now,
                              f"the laser {math.degrees(have):+.0f} deg, the target {math.degrees(elev):+.0f} deg, "
                              f"ray {math.dist(origin, dot) / 100:.1f} m, keys {','.join(sorted(keys))}")
        sky = SKY_GUARD and have > elev + SKY_MARGIN and not on
        if sky:
            if not self._sky:
                self.stats["sky_corrections"] += 1
            self.stats["sky_guard_ticks"] += 1
            keys = (set(keys) - {"rup"}) | {"rdown"}
            self.why = (f"sky guard: the laser {math.degrees(have):+.0f} deg, the target {math.degrees(elev):+.0f} deg; "
                        + self.why)
        self._sky = sky
        return keys

    def _track_pitch_rate(self, ray, now) -> None:
        """The aim's pitch rate from this ray and the last (None across a dot that jumped, or a short ray)."""
        origin, dot = ray
        ln = math.dist(origin, dot)
        if ln < PITCH_RATE_RAY:
            self._pray, self._prate = None, None
            return
        pitch = math.atan2(dot[1] - origin[1], max(math.hypot(dot[0] - origin[0], dot[2] - origin[2]), 1.0))
        last = self._pray
        if last is not None and 0.0 < now - last[2] <= 0.3 and 1.0 / PITCH_RATE_JUMP <= ln / last[1] <= PITCH_RATE_JUMP:
            self._prate = (pitch - last[0]) / (now - last[2])
        elif last is None or now - last[2] > 0.3:
            self._prate = None
        self._pray = (pitch, ln, now)

    def _note_ray_pitch(self, ray, tgt, dist) -> None:
        """The aim's pitch from each live ray; the first after a raise compared with the last before it."""
        origin, dot = ray
        if self._first_ray:
            self._first_ray_at = self._now
        if math.dist(origin, dot) < PITCH_UP_RAY:
            return
        pitch = math.atan2(dot[1] - origin[1], max(math.hypot(dot[0] - origin[0], dot[2] - origin[2]), 1.0))
        if self._first_ray:
            self._first_ray = False
            self.stats["raise_first_rays"] += 1
            if pitch > PITCH_UP_LOG:
                self.stats["raise_up_first"] += 1
                want = math.atan2(tgt["pos"][1] + CHEST_H - origin[1], max(dist, 1.0))
                low = self._lower_pitch
                self.stats["raise_up_last"] = (f"first ray {math.degrees(pitch):+.0f} deg, the last aim before "
                                               + (f"{math.degrees(low):+.0f}" if low is not None else "none")
                                               + f" deg, wanted {math.degrees(want):+.0f} deg at {dist / 100:.1f} m")
        self._ray_pitch = pitch

    def _pitch_up(self, origin, dot, chest, tgt, dist, now) -> None:
        """An aimed tick with the laser over PITCH_UP_LOG above level (a ray PITCH_UP_RAY or longer): counted, with
        its cause."""
        if math.dist(origin, dot) < PITCH_UP_RAY:
            return
        have = math.atan2(dot[1] - origin[1], max(math.hypot(dot[0] - origin[0], dot[2] - origin[2]), 1.0))
        if have <= PITCH_UP_LOG:
            return
        want = math.atan2(chest[1] - origin[1], max(math.hypot(chest[0] - origin[0], chest[2] - origin[2]), 1.0))
        cause = ("target_high" if want > PITCH_UP_LOG else
                 "raise" if self.aim_since is not None and now - self.aim_since < PITCH_UP_RECENT_S else
                 "retarget" if now - self.target_at < PITCH_UP_RECENT_S else "other")
        self.stats["pitch_up_ticks"] += 1
        self.stats["pitch_up_" + cause] += 1
        self._pu_detail = (
            f"{cause}: the laser {math.degrees(have):+.0f} deg, wanted {math.degrees(want):+.0f} deg, {dist / 100:.1f} m, "
            f"dy {tgt['pos'][1] - origin[1] + MUZZLE_H:+.0f} cm, ray {math.dist(origin, dot) / 100:.1f} m, up "
            + (f"{now - self.aim_since:.2f}" if self.aim_since is not None else "-")
            + f" s, the target {now - self.target_at:.2f} s, {tgt.get('class') or '?'}"
            + (f", the aim's own pitch {-math.degrees(self._ap_now):+.0f} deg" if self._ap_now is not None else ""))

    @staticmethod
    def _near_aim(origin, dot, live, flat):
        """The Majini nearest the aim line (by the ray's yaw to his chest), within SWITCH_ERR and in reach; None."""
        best, best_err = None, SWITCH_ERR
        for e in live:
            if flat(e) > ENGAGE_R:
                continue
            err = abs(ray_error(origin, dot, (e["pos"][0], e["pos"][1] + CHEST_H, e["pos"][2]))[0])
            if err < best_err:
                best, best_err = e, err
        return best

    # --- the look (stats look, gbox.mercs.bot_look: "look at the bot") ----------------------------------------------
    def _pull_start(self, now) -> None:
        """A trigger pull: its entry in the look, with the aim as it was pulled (_decide's _aimctx). dot_on is "target"
        for the laser's pulls (the dot on him, or the ray running through him first) and "off" for the laserless aim."""
        ctx = self._aimctx or {}
        if self._raise_t is not None:                        # the first pull since the gun went up
            self.stats["first_pull_n"] += 1
            self.stats["first_pull_s"] = round(self.stats["first_pull_s"] + max(0.0, now - self._raise_t), 2)
            self._raise_t = None
        target = make_target(id=ctx.get("target"), kind="majini" if ctx.get("target") is not None else None,
                             dist_m=(ctx.get("dist") or 0.0) / 100.0, bearing_deg=-math.degrees(ctx.get("bearing") or 0.0))
        entry = self.look.record_shot(ctx.get("weapon"), ctx.get("gate"), target,
                                      aim_err_deg=-math.degrees(ctx.get("yaw_err") or 0.0),
                                      dot_on="off" if ctx.get("laserless") else "target")
        self._pulls.append({"entry": entry, "start": now, "end": None, "drops": 0, "hp_delta": 0,
                            "target": ctx.get("target"), "where": ctx.get("where"),
                            "laserless": bool(ctx.get("laserless")), "behind": self._behind(ctx),
                            "k": {k: ctx.get(k) for k in ("class", "dist", "item", "dot", "foot", "shooter", "hp_max")}})
        del self._pulls[:-4]                                 # (a pull resolves within HIT_S of its end)

    @staticmethod
    def _behind(ctx) -> str:
        """What the dot met behind him on a ray-through pull: "wall", "floor" or "none" (nothing in range)."""
        origin, dot = ctx.get("origin"), ctx.get("dot")
        if ctx.get("where") is not None or origin is None or dot is None:
            return ""
        if math.dist(origin, dot) >= RAY_RANGE_CM:
            return "none"
        return "floor" if abs(dot[1] - (ctx.get("py") or 0.0)) <= FLOOR_DY else "wall"

    def _pull_end(self, now, slipped: bool = False) -> None:
        pull = next((x for x in reversed(self._pulls) if x["end"] is None), None)
        if pull is None:
            return
        pull["end"] = now
        if now - pull["start"] < PULL_SHORT_S:
            self.stats["pulls_short"] += 1
        if slipped and pull["target"] is not None and (self.hp_prev.get(pull["target"]) or 0) > 0:
            self.stats["pulls_slipped"] += 1

    def _resolve_pulls(self, now) -> None:
        """Pulls whose hit window has passed: hit (a Majini's health fell), or why not."""
        for pull in [x for x in self._pulls if x["end"] is not None and now - x["end"] > HIT_S]:
            self._pulls.remove(pull)
            if pull["drops"]:
                out, key = "hit:majini", "pulls_hit"
            elif pull["laserless"]:
                out, key = "miss:off_target", "pulls_blind"
            elif pull["where"] is not None:
                out, key = "miss:no_damage", "pulls_dot_miss"
            else:
                out, key = "miss:off_target", "pulls_ray_miss"
            self.stats[key] += 1
            gate = pull["entry"].get("gate") or ""
            if pull["behind"]:
                pull["entry"]["gate"] = f"{gate} (the dot on the {pull['behind']} behind him)"[:160]
            self.look.resolve(pull["entry"], out, pull["hp_delta"] or None)
            self._k_shot(pull, out, now)

    def _k_shot(self, pull, out, now) -> None:
        """The pull for the enemy knowledge database: his class, the distance, the weapon, the dot's point on him (a world
        point beside his feet and the shooter: the database takes up / across), kill / hit / miss, the health taken."""
        from ..brain import knowledge
        k = pull.get("k") or {}
        dead = pull["drops"] and pull["target"] is not None and (self.hp_prev.get(pull["target"]) or 0) <= 0
        outcome = "kill" if dead else "hit" if pull["drops"] else "miss"
        point = k.get("dot") if pull["where"] is not None else None   # the dot on him: where the shots went on him
        knowledge.record_shot(MAP_ID, k.get("class"), None, (k.get("dist") or 0.0) / 100.0, k.get("item"),
                              point, outcome, pull["hp_delta"] or None, enemy_id=pull["target"],
                              zone=pull["where"], fire_mode="hold", enemy_pos=k.get("foot"),
                              shooter_pos=k.get("shooter"), units_per_m=100.0, hp_max=k.get("hp_max"),
                              round_id=self.stats.get("round_evidence_id"), t=now)

    def _k_tick(self, snap, now) -> None:
        """Each tick: a health fall -> record_damage (the Majini holding him, else the nearest, and how); the live
        Majini within K_OBSERVE_M -> observe, about K_OBSERVE_HZ times a second."""
        from ..brain import knowledge
        p = snap.get("player")
        if not p:
            self._hp_last = None
            return
        px, py, pz = p["pos"]
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY]
        flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        hp, last = p.get("hp"), self._hp_last
        self._hp_last = (p.get("ptr"), hp)
        if last is not None and last[0] == p.get("ptr") and isinstance(hp, int) and isinstance(last[1], int) \
                and hp < last[1]:
            near = min(live, key=flat, default=None)
            motion = p.get("motion")
            how = "grab" if motion in (106, 107) else "hold" if motion in MOTION_HELD else \
                "melee" if near is not None and flat(near) <= THREAT_R else "unknown"
            knowledge.record_damage(MAP_ID, near.get("class") if near else None, None,
                                    flat(near) / 100.0 if near else None, how, last[1] - hp,
                                    enemy_id=near.get("ptr") if near else None, hp_max=p.get("hp_max"),
                                    player_state=motion, round_id=self.stats.get("round_evidence_id"), t=now)
        if self._k_obs_at is None or now - self._k_obs_at >= 1.0 / K_OBSERVE_HZ:
            self._k_obs_at = now
            knowledge.observe(MAP_ID, [{"id": e.get("ptr"), "cls": e.get("class"), "state": None,
                                        "dist_m": round(flat(e) / 100.0, 2)}
                                       for e in live if flat(e) <= K_OBSERVE_M * 100.0], t=now)

    def _front_foe(self, p, snap) -> bool:
        """Another living Majini in front of him (inside BODY_AIM_TOL) within reach: one he could shoot without turning."""
        px, py, pz = p["pos"]
        for e in snap.get("enemies") or ():
            if (e.get("hp") or 0) <= 0 or abs(e["pos"][1] - py) > MAX_DY or e.get("ptr", e.get("slot")) == self.target:
                continue
            dx, dz = e["pos"][0] - px, e["pos"][2] - pz
            if math.hypot(dx, dz) <= ENGAGE_R and abs(wrap(heading(dx, dz) - p["rot"])) <= BODY_AIM_TOL:
                return True
        return False

    def _look_tick(self, snap, now) -> None:
        """After each decision: its time in the budget (t_<doing>), the turning with a foe in front, the pulls' outcomes,
        the idle streak among foes, the decision itself, and stats look (at most every LOOK_PUBLISH_S)."""
        dt = 0.0 if self._tick_t is None else max(0.0, min(now - self._tick_t, LOOK_STEP_MAX_S))
        self._tick_t = now
        doing, p = self.doing, snap.get("player")
        ran, front = self._ran                               # the time since the last tick ran the last decision
        for key in (("t_" + ran,) if ran in DOINGS and dt else ()) + (("t_turn_foe_front",) if front and dt else ()):
            self._acc[key] += dt                             # (summed unrounded: 2,400 ticks a round)
            self.stats[key] = round(self._acc[key], 2)
        self._ran = (doing, bool(doing in ("turn", "unaim", "quick_turn") and p and self._front_foe(p, snap)))
        self._resolve_pulls(now)
        self._k_tick(snap, now)
        if snap.get("player"):
            self._track_combo(snap)
        if self.mines is not None and p:
            self.mines.watch(p, snap, now)                   # the bombs and their blasts, whatever ran this tick
        if self.nades is not None and p:
            self.nades.watch(p, snap, now)                   # his health falling, the melees on the flashed ones
        if p and doing != "none":
            pos = p["pos"]
            moving = bool(self._look_at is not None and dt and
                          math.hypot(pos[0] - self._look_at[0], pos[2] - self._look_at[2]) / dt >= LOOK_MOVE_CM_S)
            self._look_at = pos
            foes = any((e.get("hp") or 0) > 0 and abs(e["pos"][1] - pos[1]) <= MAX_DY
                       and math.hypot(e["pos"][0] - pos[0], e["pos"][2] - pos[2]) <= LOOK_FOE_R
                       for e in snap.get("enemies") or ())
            busy = moving or doing not in ("aim", "raise", "reraise", "restale", "no_foes", "walk")
            self.look.tick_idle(foes, busy, t=now)
            phase = "dead" if doing == "dead" else "survive" if doing in SURVIVAL else "fight"
            self.look.record_decision(phase, doing, self.why, t=now)
        self.stats["look_idle_among_foes_s"] = round(self.look.idle_s, 1)
        self.stats["look_walls_shot"] = self.look.walls_shot
        if "look" not in self.stats or (self.look.version != self._look_pub[0]
                                        and now - self._look_pub[1] >= LOOK_PUBLISH_S):
            self.stats["look"] = self.look.snapshot()
            self._look_pub = (self.look.version, now)

    def _fight(self, live, snap, now) -> dict:
        """The PS3 combat core's decision on the Switch pad (re5_switch_brain.Fighter), with the Switch's trigger time
        and the dropouts fired through counted here."""
        try:
            act, self.doing, self.why = self.fighter.fight(snap, live, now)
        except Exception as exc:                             # noqa: BLE001 - a brain error falls back to the Switch's
            self.stats["brain_error"] = f"fight {type(exc).__name__}: {exc}"[:160]
            p = snap["player"]
            px, _, pz = p["pos"]
            flat = lambda e: math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
            near_e = min(live, key=flat, default=None)
            return self._decide(p, live, flat, near_e, flat(near_e) if near_e is not None else math.inf, snap, now)
        held = act.get("hold") or ()
        if "zr" in held:
            if self._fire_t is not None:
                self.stats["trigger_s"] = round(self.stats.get("trigger_s", 0.0) + min(now - self._fire_t, 0.2), 2)
            self._fire_t = now
            if self.fighter.flickering and self._tick_t is not None:
                self.stats["flicker_s"] = round(self.stats["flicker_s"] + min(now - self._tick_t, LOOK_STEP_MAX_S), 2)
        else:
            self._fire_t = None
        self.aim_since = (self.aim_since or now) if "zl" in held else None   # (the reload wait keeps the gun up)
        return act

    def prompt_ok(self, button, snap, now) -> bool:
        return True

    def save(self) -> None:
        if self.fighter is not None:
            self.fighter.end_round(self.clock())
        if self.release is not None:
            try:
                self.release()
            except Exception:                               # noqa: BLE001 - the round is over either way
                pass


class RE5Switch(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # No Mercy on Switch is played solo here: one pad, no partner control
    round_counters = ("shots", "hits", "trigger_s", "holds", "dying", "escapes", "burst_backoffs", "heals",
                      "heal_starts", "heal_failures", "turns", "quick_turns", "backoffs", "reraise", "restale",
                      "flicker_s") + BRAIN_COUNTERS + MINE_COUNTERS + re5_switch_nades.COUNTERS + MOTION_COUNTERS + K_COUNTERS + LEVEL_COUNTERS + COMBO_COUNTERS \
        + THREAT_COUNTERS \
        + AIM_COUNTERS + tuple("t_" + d for d in DOINGS)

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._timer = (None, 0.0)
        self.stats: dict | None = None
        self._tally = None                      # the results tally being watched (result_ready)

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        snap = self.snapshot(m) if snap is None else snap
        where = own_screen(snap)
        if where == "playing":
            self._cycle_started()
            now, t = self.clock(), snap.get("timer")
            if t != self._timer[0]:
                self._timer = (t, now)
            elif now - self._timer[1] > HANG_S:
                where = "loading"                           # the clock stopped: frozen (the engine calls it lost)
        self._mods(m, snap, where == "playing")
        return where

    def _cycle_started(self) -> None:
        """A round is up on what the selects confirmed: the stage cycle counts it; the round's stats name it."""
        if not CYCLE or "c" not in _CYCLE:
            return
        c = _CYCLE["c"]
        stage, char = c.confirmed.get("stage"), c.confirmed.get("character")
        if not (isinstance(stage, int) and isinstance(char, int)
                and 0 <= stage < len(STAGE_NAMES) and 0 <= char < len(CHARACTERS)):
            return
        c.started(stage, char)
        if self.stats is not None:
            self.stats.update(stage=STAGE_NAMES[stage], character=CHARACTERS[char], stage_coverage=c.coverage_text())

    def _mods(self, m, snap, playing: bool, stats: dict | None = None) -> None:
        """The session's live mods (re5_switch_mods: fire_rate's time scale during shots, the no-ammo flags'
        read-back) on every snapshot, when the engine runs with the session's adapter and modifications are allowed."""
        ad = getattr(m, "adapter", None)
        if ad is None or getattr(m, "mercs_no_modifications", False):
            return
        from . import re5_switch_mods
        res = re5_switch_mods.maintain(ad, snap, enabled=playing)
        if snap is not None:
            snap["mine_settings"] = re5_switch_mods.mine_settings(ad)   # the `mines` op's cadence for the bot
            snap["preferred_weapon"] = re5_switch_mods.preferred_weapon(ad)   # select_weapon / random_weapon
        if self.stats is not None:
            self.stats["rapid_fire_active"] = bool(res.get("active"))
            self.stats["mod_writes"] = self.stats.get("mod_writes", 0) + res.get("writes", 0)
            if not res.get("verified", True):
                self.stats["mod_reason"] = res.get("reason", "")

    def result_ready(self, snap, now) -> bool:
        """The round's results tally is over: its score and kills unchanged for a second after at least two on the
        results, or fifteen at most (the PS3 driver's rule). The engine then closes the round with a terminal witness
        whose tally_ready MercMode requires to count a completed round. Without this method every completed RE5
        Switch round was refused ("The native result tally is not complete"), and only deaths counted: once the bot
        survived most rounds, a turn played 10 rounds in 24 minutes and MercMode had counted 2 (live 2026-10-27)."""
        sig = ((snap.get("player") or {}).get("ptr"), snap.get("score"), snap.get("kills"))
        st = self._tally
        if st is None or now - st["seen"] > TALLY_GAP_S:            # a new results screen
            st = self._tally = {"sig": sig, "started": now, "changed": now, "seen": now}
        else:
            if st["sig"] != sig:
                st.update(sig=sig, changed=now)
            st["seen"] = now
        return now - st["started"] >= TALLY_MAX_S or (now - st["started"] >= TALLY_MIN_S
                                                       and now - st["changed"] >= TALLY_STILL_S)

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
        return Bot(stats=stats, clock=clock, release=release, m=m, learn_dir=learn_dir)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
                "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "no_mercy"}


DRIVER = RE5Switch
