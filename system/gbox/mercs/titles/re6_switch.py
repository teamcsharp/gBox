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

import heapq
import json
import math
import random
import struct
import time
from pathlib import Path

from .. import tuning                      # learned per-stage constants (gbox/mercs/tuning.py)
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
PLAYER_COUNT, PLAYER_IDS = 0x1D0, 0x1D4 # uIdStartUp32: how many characters it lists, their ids (a fresh save: 4 - Leon
                                        # 0, Chris 2, Jake 4, Agent 8; the partners join the list as they unlock: after
                                        # a 147,040 round Helena (1) sat at the cursor's index 1, live 2026-10-27)
EXTRA_COUNT, EXTRA_MODES = 0x54, 0x1C4  # uIdStartUp02: how many modes, their ids (0 Agent Hunt, 1 Mercenaries, 2 No Mercy)
MAIN_PLAY_GAME, PLAY_EXTRA_CONTENT, MERCS_SOLO = 0, 3, 0
STAGES = ("Urban Chaos", "Steel Beast", "Mining the Depths", "Rail Yard", "High Seas Fortress", "The Catacombs",
          "Requiem for War", "Liquid Fire", "Rooftop Mission", "Creature Workshop")
CHARACTERS = ("Leon", "Helena", "Chris", "Piers", "Jake", "Sherry", "Ada", "Carla", "Agent")   # by their select ids 0-8
STAGE_TARGET, PLAYER_TARGET = 0, 1      # Urban Chaos, Chris (the cursor's index on a fresh save's list, the fallback)
PLAYER_ID = 2                           # Chris by his id in the select's list: his assault rifle is automatic (ZR held
                                        # fires 9.6 rounds a second; with infinite ammo it never stops: "rain fire",
                                        # operator 2026-10-27), the character when no queued round names one
# A random stage and costume each round (operator 2026-10-27: "the characters using random costumes and playing random
# levels"), from the selects' own state (Ghidra, this build: the stage select's update main+0xAAFB20, the character
# select's main+0xAAD830). The stage select lists all ten (+0x54 = 10), its cursor +0x50 walks them with up / down, and
# A starts only a stage whose bit is set in +0x58. The character select keeps, per select id, the costume it shows
# (+0x1F8 + 4 * id, left / right step it) and how many it lists (+0x21C + 4 * id: the unlocked ones); its confirm writes
# the costume code (0-29, the unlock mask's bit) to sGameMan +0x3CA4, and the round's loadout follows the costume
# (gbox.mercs.titles.re6_switch_mods.LOADOUTS: costume 0 has its own, 1-3 share the second).
STAGE_COUNT, STAGE_UNLOCKED = 0x54, 0x58
COSTUME_CURSOR, COSTUME_COUNT = 0x1F8, 0x21C
GM_GAME_MODE, GM_STAGE, GM_COSTUME = 0xCC, 0x3C78, 0x3CA4   # sGameMan: the round set-up's mode, stage index, costume code


class _Pick:
    """This menu visit's draws, kept until the round is up (screen() says playing), then drawn afresh at the next
    selects (operator 2026-10-27 18:03: "a random character / costume each and every round ... and level ... cycling
    through all of the levels"): the stage the least played among the unlocked ones (coverage, ties at random), a
    random character among the select's listed ones, a random costume among his; a queued round (request) names the
    character and / or the stage (None = drawn). last: the round that went up (stage, character, costume)."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.queued: dict = {}
        self.stage = self.costume = self.character = None
        self.costume_of = None
        self.last: dict = {}

    def reset(self) -> None:
        self.stage = self.costume = self.costume_of = self.character = None

    consumed: dict = {}                                     # the last queued pick a round started with (not again)


PICK = _Pick()
RELOAD_KEEP = ("PICK",)                 # a bot hot reload keeps this visit's draws and a queued pick (gbox.hot_reload)


def request(character=None, stage=None) -> dict:
    """The next selects' character and stage (MercMode's DJ queue): a character by name or select id, a stage index
    (0-9); None leaves it random (the stage among the unlocked ones; the character: Chris)."""
    cid = None
    if character is not None:
        cid = character if isinstance(character, int) else next(
            (i for i, n in enumerate(CHARACTERS) if n.casefold() == str(character).casefold()), None)
        if cid is None or not 0 <= cid < len(CHARACTERS):
            raise ValueError(f"RE6 has no character {character!r} (one of {', '.join(CHARACTERS)})")
    if stage is not None and (type(stage) is not int or not 0 <= stage < len(STAGES)):
        raise ValueError(f"RE6 has no stage {stage!r} (0-{len(STAGES) - 1})")
    pick = {"character": cid, "stage": stage}
    if pick == PICK.consumed:                               # the pick a round already started with (a prepared round's
        return {}                                           # own turn hands it over again): the next selects draw anew
    PICK.queued = pick
    PICK.reset()
    return dict(pick)


# Coverage (the same message: "learning and studying and cycling through all of the levels"): the rounds each stage and
# character went up, kept in learn dir / COVERAGE_FILE (gbox-data/mercs/learned/<title>/): the stage select draws the
# least played; the driver's progress reports the round's stage, character, costume and the coverage.
COVERAGE_FILE = "re6_coverage.json"
COVERAGE_PATH = None                    # (tests point it elsewhere; None: the deployment's learn dir)
_COVERAGE: dict = {"data": None}


def _coverage_path():
    if COVERAGE_PATH is not None:
        return Path(COVERAGE_PATH)
    try:
        from .. import lessons as L
        return L.ROOT.parent / "learned" / MAP_ID / COVERAGE_FILE
    except Exception:                                        # noqa: BLE001 - no learn dir: this run only
        return None


def coverage() -> dict:
    """{"stages": {name: rounds}, "characters": {name: rounds}} (read once, then kept)."""
    if _COVERAGE["data"] is None:
        data = {"stages": {}, "characters": {}}
        path = _coverage_path()
        if path is not None and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                data["stages"].update({str(k): int(v) for k, v in (raw.get("stages") or {}).items()})
                data["characters"].update({str(k): int(v) for k, v in (raw.get("characters") or {}).items()})
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        _COVERAGE["data"] = data
    return _COVERAGE["data"]


def _count_round(stage, character) -> None:
    data = coverage()
    if isinstance(stage, int) and 0 <= stage < len(STAGES):
        data["stages"][STAGES[stage]] = data["stages"].get(STAGES[stage], 0) + 1
    if isinstance(character, int) and 0 <= character < len(CHARACTERS):
        data["characters"][CHARACTERS[character]] = data["characters"].get(CHARACTERS[character], 0) + 1
    path = _coverage_path()
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
        except OSError:
            pass


def stage_target(m, unit: int) -> int:
    """The stage select's target: the queued stage when it can start, else this visit's random draw among the stages
    whose bit is set (+0x58); STAGE_TARGET when the mask can't be read."""
    try:
        mask = struct.unpack("<I", m.rd(unit + STAGE_UNLOCKED, 4))[0]
    except (ValueError, OSError, struct.error):
        return STAGE_TARGET
    open_ = [i for i in range(len(STAGES)) if mask >> i & 1]
    if not open_:
        return STAGE_TARGET
    if PICK.stage not in open_:
        q = PICK.queued.get("stage")
        if q in open_:
            PICK.stage = q
        else:                                                # the least played, ties at random
            played = coverage()["stages"]
            low = min(played.get(STAGES[i], 0) for i in open_)
            PICK.stage = PICK.rng.choice([i for i in open_ if played.get(STAGES[i], 0) == low])
    return PICK.stage


def wanted_character(ids=None) -> int:
    """The queued character, else this visit's random draw among the select's listed ids (PLAYER_ID without them)."""
    q = PICK.queued.get("character")
    if isinstance(q, int):
        return q
    listed = [i for i in ids or () if 0 <= i < len(CHARACTERS)]
    if PICK.character is None or (listed and PICK.character not in listed):
        PICK.character = PICK.rng.choice(listed) if listed else None
    return PICK.character if PICK.character is not None else PLAYER_ID


def costume_target(m, unit: int, cid: int) -> tuple[int | None, int | None]:
    """(the costume the select shows for select id cid, this visit's random target among the ones it lists)."""
    try:
        cur, n = (struct.unpack("<i", m.rd(unit + off + 4 * cid, 4))[0] for off in (COSTUME_CURSOR, COSTUME_COUNT))
    except (ValueError, OSError, struct.error):
        return None, None
    if not 0 < n <= 4 or not 0 <= cur < n:
        return None, None
    if PICK.costume is None or PICK.costume_of != cid or not 0 <= PICK.costume < n:
        PICK.costume, PICK.costume_of = PICK.rng.randrange(n), cid
    return cur, PICK.costume


def costume_code(code: int) -> tuple[str, int] | None:
    """(character, costume index) of a costume code (the unlock mask's bit): 4 a character for the first seven, then
    Carla and Agent with one each."""
    if 0 <= code < 28:
        return CHARACTERS[code // 4], code % 4
    if code in (28, 29):
        return CHARACTERS[code - 21], 0
    return None

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
REPLAY_ON_DEATH = False                 # (operator 18:03: a new stage and character every round - a death answers NO and
                                        # the selects draw again; True replays the same round at once)
ROUND_TIME_S, FRESH_ROUND_S = 120.0, 3.0   # No Mercy's clock; within this of it on the first tick alive: a new round


def player_target(m, unit: int) -> int:
    """The character select's cursor index for the wanted character (a queued one, else PLAYER_ID): its place in the
    select's own list of ids, which grows as characters unlock; PLAYER_TARGET when the list can't be read or lacks
    him."""
    try:
        n = _i32(m, unit + PLAYER_COUNT)
        if 0 < n <= 16:
            ids = struct.unpack(f"<{n}i", m.rd(unit + PLAYER_IDS, 4 * n))
            want = wanted_character(ids)
            if want in ids:
                return ids.index(want)
            if PLAYER_ID in ids:
                return ids.index(PLAYER_ID)
    except (ValueError, OSError, struct.error):
        pass
    return PLAYER_TARGET


def continue_target() -> int:
    """The "Continue?" answer the pace wants: YES (the replay) unless REPLAY_ON_DEATH is off."""
    return CONTINUE_YES if REPLAY_ON_DEATH else CONTINUE_NO

BOOT_KEY = "a"                          # a screen RAM can't name out of a round (PRESS ANY BUTTON)
STEPS = {"results": "plus", "alert_leaderboard": "b", "alert_ok": "a", "mercs_wrong_mode": "b", "press_any_button": "a",
         "alert": "b", "split_lobby": "a"}     # split_lobby: A starts the game (only once Player 2 has joined on its pad)
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
BOMB_INDEX, BOMB_TYPE, SLOT_MODE = 12, 0x116, 0xC          # the item wheel's remote bomb slot; its mode byte (1 = out)
P_EQUIPPED, P_SLOTS, SLOT_STRIDE, N_SLOTS = 0x5064, 0x5070, 0x28, 24   # the equipped slot's index (the HUD's: uIdLife's
                                        # update reads it and finds the slot whose +0x9 holds it, main+0xB22BB0); the 24
                                        # cItem slots: +0x8 in use, +0x9 the slot's index, +0xA u16 the type (0x100 + the
                                        # item id), +0xE s16 rounds / count


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


def inventory_state(m, p: int) -> tuple[int | None, int, dict | None]:
    """(the equipped slot's index, the item id in hand, the remote bomb): +0x5064 names the equipped slot by its +0x9
    index (slot 0's id when no live slot holds it); the bomb is the item wheel's remote bomb slot (index BOMB_INDEX,
    type 0x116) - {"count", "out"}: out while its +0xC mode is 1 (a bomb thrown, the remote in his hand)."""
    try:
        idx = struct.unpack("<i", m.rd(p + P_EQUIPPED, 4))[0]
        raw = m.rd(p + P_SLOTS, SLOT_STRIDE * N_SLOTS)
    except (ValueError, OSError, struct.error):
        return None, 0, None
    item, bomb = None, None
    for o in range(0, SLOT_STRIDE * N_SLOTS, SLOT_STRIDE):
        if not raw[o + 8]:
            continue
        if raw[o + 9] == idx and item is None:
            item = raw[o + 0xA]
        if raw[o + 9] == BOMB_INDEX and struct.unpack_from("<H", raw, o + 0xA)[0] == BOMB_TYPE:
            bomb = {"count": struct.unpack_from("<h", raw, o + 0xE)[0], "out": raw[o + SLOT_MODE] == 1}
    if item is None:
        try:
            item = m.rd(p + P_WEAPON_ID, 1)[0]
        except (ValueError, OSError):
            item = 0
    return idx, item, bomb


NADE_TYPES = {"frag": 0x113, "fire": 0x114, "flash": 0x115}   # the hand, incendiary and flash grenades' item types
WEAPON_INDEXES = 7                      # wheel indexes 0-6 the weapons, 7-12 the items (the remote bomb 12)


def inventory_items(m, p: int) -> dict:
    """The grenades on his item wheel: {type: (wheel index +0x9, count +0xE)} for the live slots holding one."""
    try:
        raw = m.rd(p + P_SLOTS, SLOT_STRIDE * N_SLOTS)
    except (ValueError, OSError):
        return {}
    out = {}
    for o in range(0, SLOT_STRIDE * N_SLOTS, SLOT_STRIDE):
        t = struct.unpack_from("<H", raw, o + 0xA)[0]
        if raw[o + 8] and t in NADE_TYPES.values() and t not in out:
            out[t] = (raw[o + 9], struct.unpack_from("<h", raw, o + 0xE)[0])
    return out


def inventory_guns(m, p: int) -> dict:
    """His weapons now: {type: wheel index} for the live weapon slots (+0x9 index below WEAPON_INDEXES)."""
    try:
        raw = m.rd(p + P_SLOTS, SLOT_STRIDE * N_SLOTS)
    except (ValueError, OSError):
        return {}
    out = {}
    for o in range(0, SLOT_STRIDE * N_SLOTS, SLOT_STRIDE):
        t, idx = struct.unpack_from("<H", raw, o + 0xA)[0], raw[o + 9]
        if raw[o + 8] and idx < WEAPON_INDEXES and 0x100 <= t < 0x130 and t not in out:
            out[t] = idx
    return out


_ACTION_NAMES: dict = {}


def unit_action(m, u: int) -> str | None:
    """A unit's current action's class (+0x13F0: the player's cPlAction_pl_act_..., a set piece's cSm...Act_...)."""
    try:
        act = u64(m, u + 0x13F0)
        if not ptr_ok(act):
            return None
        vt = u64(m, act)
    except (ValueError, OSError):
        return None
    if vt not in _ACTION_NAMES:
        if len(_ACTION_NAMES) > 512:
            _ACTION_NAMES.clear()
        _ACTION_NAMES[vt] = class_name(m, act)
    return _ACTION_NAMES[vt]


def equipped_id(m, p: int) -> int:
    """The item id of the gun in hand (inventory_state)."""
    return inventory_state(m, p)[1]


# Split screen (docs/research/switch-coop-bot.md, static from this main): sPlayer holds eight players at +0x30 + 8 * index
# (count +0x70); the add-player routine (main+0x3E6E24) stores each one's index byte at +0x5A2C. main+0xB2E180 makes the
# player's own uCameraCtrl (owner at the camera's +0xB0) and keeps it at +0x3A28; main+0xBCC014 its own uLaserSight
# (owner's index at the laser's +0x590) at +0x54E8. THE MERCENARIES NO MERCY lists SPLIT at uIdStartUp30's index 3, and
# SPLIT goes on only with two controllers (main+0xAB2AE8). A snapshot is player 0's, read exactly as before, unless the
# memory names a player (mercs_player_index) or split screen (mercs_coop): gbox.mercs.titles.switch_team.View. The menus
# walk takes SPLIT for a session whose memory asks for split screen (mercs_split_screen: switch_team.Session).
P_INDEX, S_PLAYER_COUNT, MAX_PLAYERS = 0x5A2C, 0x70, 8
P_CAMERA, CAM_OWNER = 0x3A28, 0xB0
P_LASER, LASER_OWNER = 0x54E8, 0x590
MERCS_SPLIT = 3


def mercs_target(m=None) -> int:
    """uIdStartUp30's entry the menus walk takes: SPLIT for a split-screen session, SOLO otherwise."""
    return MERCS_SPLIT if getattr(m, "mercs_split_screen", False) is True else MERCS_SOLO


def player_index(m) -> int | None:
    """The player a snapshot of m is for (0 = Player 1, the solo default); None for a value that names no slot."""
    index = getattr(m, "mercs_player_index", 0)
    return index if type(index) is int and 0 <= index < MAX_PLAYERS else None


def player_pointer(m, sp: int, index: int) -> int:
    """Player `index` from sPlayer's slots, only when its own index byte agrees (never a neighbouring slot's)."""
    try:
        p = u64(m, sp + P_FIRST + 8 * index)
        return p if ptr_ok(p) and m.rd(p + P_INDEX, 1)[0] == index else 0
    except (ValueError, OSError, struct.error, OverflowError):
        return 0


def own_camera(m, p: int) -> dict | None:
    """Player p's own camera (its +0x3A28, owned when the camera's +0xB0 points back at p): the reading camera() makes."""
    try:
        u = u64(m, p + P_CAMERA)
        if not ptr_ok(u) or u64(m, u + CAM_OWNER) != p:
            return None
        c = struct.unpack("<3f", m.rd(u + CAM_POS, 12))
        t = struct.unpack("<3f", m.rd(u + CAM_TARGET, 12))
    except (ValueError, OSError, struct.error, OverflowError):
        return None
    if not all(math.isfinite(v) for v in c + t) or math.dist(c, t) < 1.0:
        return None
    flat = max(math.hypot(t[0] - c[0], t[2] - c[2]), 1e-3)
    return {"pos": c, "target": t, "yaw": heading(t[0] - c[0], t[2] - c[2]),
            "pitch": math.atan2(t[1] - c[1], flat), "unit": u}


def own_laser(m, p: int, index: int) -> dict | None:
    """Player p's own laser sight (its +0x54E8, owned when the laser's +0x590 holds p's index): the reading laser()
    makes; None without one."""
    try:
        u = u64(m, p + P_LASER)
        if not ptr_ok(u) or struct.unpack("<I", m.rd(u + LASER_OWNER, 4))[0] != index:
            return None
        at = struct.unpack("<3f", m.rd(u + LASER_DOT, 12))
        frm = struct.unpack("<3f", m.rd(u + LASER_FROM, 12))
        up = struct.unpack("<f", m.rd(u + LASER_UP, 4))[0]
    except (ValueError, OSError, struct.error, OverflowError):
        return None
    if not all(math.isfinite(v) for v in at + frm):
        return None
    return {"at": at, "from": frm, "up": bool(math.isfinite(up) and up >= LASER_UP_MIN), "alpha": round(up, 3)}


# --- the stage's nav mesh -----------------------------------------------------------------------------------------------
# The coordinator, 17:20: "the zombies path around the stage, so RE6 has navigation data in RAM ... run A* from him to
# each bonus." The stage's rNavigationMesh (vtable main+0x28B8F48, magic 'NAV' v0x22 at +0x80) sits among sResource's
# resources (main+0x2A5FF98, 0x6A6F0 bytes holding their pointers). Ghidra's writer main+0x15AED40 gives its layout:
# the vertices at +0xA0 (0x10 each: x, y, z), their count +0xB8; the triangles at +0xC0 (0x70 each), their count +0xC8:
# a triangle's +0x48 / +0x50 its vertex indices, +0x58 / +0x60 its links (0x18 each, +0 the neighbouring triangle); the
# lists live in one pool. Live (s1218 / Mining the Depths, MercMode 17:20): 2005 vertices, 3434 triangles, 9722 links,
# every one symmetric and sharing an edge. navmesh() decodes it once per stage (a rescan at most every NAV_SCAN_S while
# none is found); NavMesh.path() is A* over the triangles, its waypoints the shared edges' midpoints and the goal.
SRES, SRES_SIZE, NAV_VT, NAV_MAGIC = 0x2A5FF98, 0x6A6F0, 0x28B8F48, 0x56414E
NAV_SCAN_S, NAV_CELL, NAV_DY, NAV_MAX_TRIS = 10.0, 400.0, 250.0, 20000
_NAV: dict = {"base": None, "ptr": None, "mesh": None, "at": -1e9}


class NavMesh:
    """A stage's walkable triangles: V vertices, T (a, b, c) indices, N neighbour lists; locate() / path()."""

    def __init__(self, verts, tris, links, name=""):
        self.V, self.T, self.N, self.name = verts, tris, links, name
        self.C = [tuple(sum(verts[v][i] for v in t) / 3.0 for i in range(3)) for t in tris]
        self.edge_nb: list = []                              # per triangle: {edge (u, v sorted): the neighbour across}
        for k, t in enumerate(tris):
            nbs = {}
            for nb in links[k]:
                shared = sorted(v for v in t if v in tris[nb])
                if len(shared) == 2:
                    nbs[tuple(shared)] = nb
            self.edge_nb.append(nbs)
        self.grid: dict = {}
        for k, t in enumerate(tris):
            xs, zs = [verts[v][0] for v in t], [verts[v][2] for v in t]
            for gx in range(int(min(xs) // NAV_CELL), int(max(xs) // NAV_CELL) + 1):
                for gz in range(int(min(zs) // NAV_CELL), int(max(zs) // NAV_CELL) + 1):
                    self.grid.setdefault((gx, gz), []).append(k)

    def _inside(self, k, x, z) -> bool:
        (ax, _, az), (bx, _, bz), (cx, _, cz) = (self.V[v] for v in self.T[k])
        d1 = (x - bx) * (az - bz) - (ax - bx) * (z - bz)
        d2 = (x - cx) * (bz - cz) - (bx - cx) * (z - cz)
        d3 = (x - ax) * (cz - az) - (cx - ax) * (z - az)
        return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))

    def locate(self, pt) -> int | None:
        """The triangle under pt (within NAV_DY of its height), else the nearest centre within two cells."""
        x, y, z = pt
        gx, gz = int(x // NAV_CELL), int(z // NAV_CELL)
        cand = self.grid.get((gx, gz), [])
        inside = [k for k in cand if abs(self.C[k][1] - y) <= NAV_DY and self._inside(k, x, z)]
        if inside:
            return min(inside, key=lambda k: abs(self.C[k][1] - y))
        near = [k for dx in (-2, -1, 0, 1, 2) for dz in (-2, -1, 0, 1, 2) for k in self.grid.get((gx + dx, gz + dz), ())]
        if not near:
            return None
        return min(near, key=lambda k: (abs(self.C[k][1] - y) > NAV_DY, math.hypot(self.C[k][0] - x, self.C[k][2] - z)))

    def clear(self, a, b, steps: int = 600) -> bool | None:
        """Whether the straight line a -> b stays on the walkable floor (on a's level): walked triangle to triangle
        across the edges it crosses; an edge with no neighbour (a wall, a drop, a crate) - False. None: off the mesh or
        another level (unknown)."""
        k, g = self.locate(a), self.locate(b)
        if k is None or g is None or abs(a[1] - b[1]) > 2 * NAV_DY:
            return None
        ax, az, bx, bz = a[0], a[2], b[0], b[2]
        length = math.hypot(bx - ax, bz - az)
        if length < 1.0:
            return True
        ax, az = ax + (bx - ax) * 0.5 / length, az + (bz - az) * 0.5 / length   # off an edge it may start on
        k = self.locate((ax, a[1], az))
        if k is None:
            return None

        def cross(o, p_, q):
            return (p_[0] - o[0]) * (q[1] - o[1]) - (p_[1] - o[1]) * (q[0] - o[0])
        prev = None
        for _ in range(steps):
            if k == g:
                return True
            t, nxt, wall = self.T[k], None, False
            for i in range(3):
                u, v = t[i], t[(i + 1) % 3]
                pu, pv = (self.V[u][0], self.V[u][2]), (self.V[v][0], self.V[v][2])
                d1, d2 = cross(pu, pv, (ax, az)), cross(pu, pv, (bx, bz))
                d3, d4 = cross((ax, az), (bx, bz), pu), cross((ax, az), (bx, bz), pv)
                if not ((d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)):
                    continue                                 # the line does not cross this edge
                nb = self.edge_nb[k].get(tuple(sorted((u, v))))
                if nb is None:
                    wall = True
                    continue
                if nb == prev:
                    continue
                nxt = nb
                break
            if nxt is None:                                  # it ends in this triangle, or runs into a wall
                if self._inside(k, bx, bz):
                    return True
                return False if wall else None
            prev, k = k, nxt
        return None

    def path(self, a, b) -> list | None:
        """A* from a's triangle to b's: the shared edges' midpoints, then b. None: off the mesh or no way there."""
        s0, g0 = self.locate(a), self.locate(b)
        if s0 is None or g0 is None:
            return None
        if s0 == g0:
            return [tuple(b)]
        openq, came, cost = [(0.0, s0)], {s0: None}, {s0: 0.0}
        while openq:
            _f, k = heapq.heappop(openq)
            if k == g0:
                break
            for nb in self.N[k]:
                c = cost[k] + math.dist(self.C[k], self.C[nb])
                if c < cost.get(nb, 1e18):
                    cost[nb], came[nb] = c, k
                    heapq.heappush(openq, (c + math.dist(self.C[nb], self.C[g0]), nb))
        if g0 not in came:
            return None
        chain, k = [], g0
        while k is not None:
            chain.append(k)
            k = came[k]
        chain.reverse()
        out = []
        for u, w in zip(chain, chain[1:]):
            shared = [v for v in self.T[u] if v in self.T[w]]
            if len(shared) == 2:
                out.append(tuple((self.V[shared[0]][i] + self.V[shared[1]][i]) / 2.0 for i in range(3)))
            else:
                out.append(self.C[w])
        out.append(tuple(b))
        return out


def navmesh(m, base: int, now: float | None = None) -> NavMesh | None:
    """The stage's NavMesh (cached while its resource stays; None when none is loaded or it does not decode)."""
    now = time.monotonic() if now is None else now
    c = _NAV
    if c["base"] != base:
        c.update(base=base, ptr=None, mesh=None, at=-1e9)
    try:
        if c["ptr"] is not None and u64(m, c["ptr"]) == base + NAV_VT:
            return c["mesh"]
    except (ValueError, OSError):
        pass
    c.update(ptr=None, mesh=None)
    if now - c["at"] < NAV_SCAN_S:
        return None
    c["at"] = now
    try:
        blk = m.rd(u64(m, base + SRES), SRES_SIZE)
        seen = set()
        for o in range(0, len(blk), 8):
            v = struct.unpack_from("<Q", blk, o)[0]
            if v in seen or not ptr_ok(v) or base <= v < base + 0x3000000:
                continue
            seen.add(v)
            try:
                if u64(m, v) == base + NAV_VT and _i32(m, v + 0x80) == NAV_MAGIC:
                    mesh = _decode_nav(m, v)
                    if mesh is not None:
                        c.update(ptr=v, mesh=mesh)
                        return mesh
            except (ValueError, OSError):
                continue
    except (ValueError, OSError, struct.error):
        return None
    return None


def _decode_nav(m, nav: int) -> NavMesh | None:
    hdr = m.rd(nav, 0xE8)
    nv, nt = struct.unpack_from("<I", hdr, 0xB8)[0], struct.unpack_from("<I", hdr, 0xC8)[0]
    va, ta = struct.unpack_from("<Q", hdr, 0xA0)[0], struct.unpack_from("<Q", hdr, 0xC0)[0]
    if not (0 < nv <= 3 * NAV_MAX_TRIS and 0 < nt <= NAV_MAX_TRIS and ptr_ok(va) and ptr_ok(ta)):
        return None
    vraw = m.rd(va, 0x10 * nv)
    verts = [struct.unpack_from("<3f", vraw, 0x10 * i) for i in range(nv)]
    traw = m.rd(ta, 0x70 * nt)
    heads = [struct.unpack_from("<QI4xQI", traw, 0x70 * k + 0x48) for k in range(nt)]
    lo = min(min(h[0] for h in heads), min(h[2] for h in heads))
    hi = max(max(h[0] + 4 * h[1] for h in heads), max(h[2] + 0x18 * h[3] for h in heads))
    if not (ptr_ok(lo) and 0 < hi - lo <= 0x200000):
        return None
    pool = m.rd(lo, hi - lo)
    tris, links = [], []
    for vp, vc, lp, lc in heads:
        if vc != 3:
            return None
        t = struct.unpack_from("<3i", pool, vp - lo)
        if not all(0 <= v < nv for v in t):
            return None
        tris.append(t)
        links.append([n for n in (struct.unpack_from("<i", pool, lp - lo + 0x18 * j)[0] for j in range(lc))
                      if 0 <= n < nt])
    name = hdr[0xC:0x48].split(b"\0")[0].decode("ascii", "replace")
    return NavMesh(verts, tris, links, name)


# --- the game's own button prompts ----------------------------------------------------------------------------------------
# The operator, 17:39-17:52: "seeing them miss QTE events"; "failing to notice the on screen prompts for telling it to
# climb ledges"; a frame with a "(B)" climb prompt beside Chris and "(Y) 9mm Ammo" at the bottom left. Ghidra:
# sActionButton (singleton main+0x28E7AF0, 0x1D20 bytes) holds one ButtonMgr per player (0x398 each from +0x50; its +0xC
# the player index, its cPad at +0x10); a mgr shows up to two ButtonUnits (+0x248, +0x2E0; 0x98 each): +0xC shown,
# +0x10 the cActionButton asking (its +0x30 the action type, +0x38 the logical button), +0x1C that type again. The
# press check main+0x31F0C0 writes the button's pad mask into the unit's +0x28 every frame (main+0x2218870 maps the
# logical button to it) and main+0x31D4F0 runs the action once that mask is pressed. The pad mask is the PS3 layout
# the port kept, shown with the Switch's buttons in the same places: 0x4000 cross = B (climb, the frame's "(B)"),
# 0x8000 square = Y (pick up, "(Y) 9mm Ammo"), 0x2000 circle = A, 0x1000 triangle = X, L1 0x400, R1 0x800, L2 0x100,
# R2 0x200, the D-pad 0x10-0x80; 0x10000-0x80000 the stick (a mash). prompts() lists the shown ones.
S_ACTION_BUTTON, AB_MGR, AB_MGR_SIZE, AB_MGRS, AB_UNITS = 0x28E7AF0, 0x50, 0x398, 8, (0x248, 0x2E0)
PAD_KEYS = ((0x4000, "b"), (0x8000, "y"), (0x2000, "a"), (0x1000, "x"), (0x0800, "r"), (0x0400, "l"),
            (0x0200, "zr"), (0x0100, "zl"), (0x0010, "dup"), (0x0020, "dright"), (0x0040, "ddown"), (0x0080, "dleft"))
PAD_STICK = 0xF0000


def prompts(m, base: int, index: int = 0) -> list | None:
    """The game's shown button prompts for this player: [{type, button, pad, key, ab}] (key: the Switch button to press,
    "stick" for a mash of the stick, None for a mask with no known button); None when the reads fail."""
    try:
        sab = u64(m, base + S_ACTION_BUTTON)
        if not ptr_ok(sab):
            return None
        raw = m.rd(sab + AB_MGR, AB_MGR_SIZE * AB_MGRS)
        out = []
        for k in range(AB_MGRS):
            mgr = AB_MGR_SIZE * k
            if struct.unpack_from("<i", raw, mgr + 0xC)[0] != index:
                continue
            for u in AB_UNITS:
                if not raw[mgr + u + 0xC]:
                    continue
                ab = struct.unpack_from("<Q", raw, mgr + u + 0x10)[0]
                pad = struct.unpack_from("<I", raw, mgr + u + 0x28)[0]
                typ = struct.unpack_from("<i", raw, mgr + u + 0x1C)[0]
                button = _i32(m, ab + 0x38) if ptr_ok(ab) else None
                key = next((name for bit, name in PAD_KEYS if pad & bit), None)
                if key is None and pad & PAD_STICK:
                    key = "stick"
                out.append({"type": typ, "button": button, "pad": pad, "key": key, "ab": ab})
            break
        return out
    except (ValueError, OSError, struct.error):
        return None


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
            ammo = struct.unpack("<h", m.rd(p + P_AMMO, 2))[0]
            state = m.rd(p + P_STATE, 1)[0]
            motion = struct.unpack("<H", m.rd(p + P_MOTION, 2))[0]
            tablets = struct.unpack("<h", m.rd(p + P_TABLETS, 2))[0]
            equipped, weapon_id, bomb = inventory_state(m, p)
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max, "ammo": ammo,
                              "state": state, "motion": motion, "tablets": tablets, "weapon_id": weapon_id,
                              "equipped": equipped, "bomb": bomb, "nades": inventory_items(m, p),
                              "guns": inventory_guns(m, p),
                              "action": unit_action(m, p)}
            if hp <= 0:                                     # dead: CONTINUE? and its cursor, once it takes input
                over = ui_units(m, base).get("uIdGameover00")
                snap["continue_cursor"] = continue_prompt(m, over)["cursor"] if over else None
        except (ValueError, OSError):
            snap["player"] = None
        if snap["player"]:
            snap["camera"] = own_camera(m, p) if coop else camera(m, base, snap["player"]["pos"])
            snap["laser"] = own_laser(m, p, index) if coop else laser(m, base, snap["player"]["pos"])
            snap["aim_cam"] = aim_cam(m, base, p)
            snap["navmesh"] = navmesh(m, base)
            snap["prompts"] = prompts(m, base, index or 0)                # this player's own camera state (the aim lock)
            if (snap["player"].get("bomb") or {}).get("out"):
                snap["bomb_pos"] = placed_bomb(m, base)
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
        me = (snap.get("player") or {}).get("pos")
        if me is not None:                                  # what the near ones are doing (their wind-ups)
            for en in snap["enemies"]:
                if en["hp"] > 0 and math.hypot(en["pos"][0] - me[0], en["pos"][2] - me[2]) <= ACTION_READ_R:
                    en["action"] = unit_action(m, en["ptr"])
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
        if snap["mercenaries_phase"] == PHASE_PLAYING and snap["player"]:
            snap["bonuses"] = bonuses(m, base)
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
        if phase == PHASE_PLAYING and (PICK.stage is not None or PICK.costume is not None or PICK.queued):
            PICK.last = {"stage": PICK.stage, "character": PICK.character if PICK.character is not None
                         else PICK.queued.get("character", PLAYER_ID), "costume": PICK.costume}
            _count_round(PICK.last["stage"], PICK.last["character"])
            PICK.consumed, PICK.queued = PICK.queued or PICK.consumed, {}    # the round is up: the next selects draw anew
            PICK.reset()
        return out | {"where": "playing" if phase == PHASE_PLAYING else "loading"}
    if p:
        return out | {"where": "loading"}                   # the stage is up, its HUD not yet
    if {"uIdNowLoading00", "uIdNowLoading01", "uIdSave00", "uIdSaving00"} & ui.keys():
        return out | {"where": "loading"}
    where, cursor, target = "unknown", None, None
    try:
        if "uIdStartUp32" in ui:
            u = ui["uIdStartUp32"]
            where, cursor, target = "select_player", _i32(m, u + PLAYER_CURSOR), player_target(m, u)
            if cursor == target and 0 <= cursor < 16:            # on the character: the costume next (left / right)
                cid = _i32(m, u + PLAYER_IDS + 4 * cursor)
                if 0 <= cid < len(CHARACTERS):
                    out["costume_cursor"], out["costume_target"] = costume_target(m, u, cid)
                    out["character"] = CHARACTERS[cid]
        elif "uIdStartUp31" in ui:
            u = ui["uIdStartUp31"]
            where, cursor, target = "select_stage", _i32(m, u + MENU_CURSOR), stage_target(m, u)
            if isinstance(target, int) and 0 <= target < len(STAGES):
                out["stage"] = STAGES[target]
        elif "uIdStartUp30" in ui:
            if snap.get("mercenaries_mode") == "no_mercy":
                where, cursor, target = "mercs_mode", _i32(m, ui["uIdStartUp30"] + MENU_CURSOR), mercs_target(m)
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
        elif "uIdTitle00" in ui and getattr(m, "mercs_split_screen", False) is True                 and snap.get("mercenaries_mode") == "no_mercy":
            # split screen's lobby (a live run 2026-10-27, real frames): after the stage select, "THE MERCENARIES NO
            # MERCY · <stage>", Player 1 joined, Player 2's slot "Press -/+ to join", A starts the game. Its own unit is
            # not named yet; the title unit stays listed under it, and a real title never has the No Mercy mode set
            where = "split_lobby"
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
            cc, ct = scr.get("costume_cursor"), scr.get("costume_target")
            if isinstance(cc, int) and isinstance(ct, int) and cc != ct:
                return "dright" if cc < ct else "dleft"         # the character select's costume, then A
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


BOMB_UNITS = ("uWp1097",)               # the remote bomb lying placed, its position +0x60 like every unit's (MercMode's
                                        # RE6 turn 2026-10-27 12:17:23: a uWp1097 unit came up as the slot went out, 34 cm
                                        # from him - the throw had dropped it at his feet - and went at the blast 12:17:38)


def placed_bomb(m, base: int):
    """Where the placed remote bomb lies (x, y, z), or None: its unit found on sUnit's lines (looked for again at most
    every RESCAN_S while it is not there)."""
    u = _find_unit(m, base, "bomb", BOMB_UNITS, range(N_LINES))
    if u is None:
        return None
    try:
        pos = struct.unpack("<3f", m.rd(u + P_POS, 12))
    except (ValueError, OSError):
        return None
    return pos if all(math.isfinite(v) and abs(v) < 1e6 for v in pos) else None


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


def aim_cam(m, base: int, player: int) -> dict | None:
    """P1's player camera state: {addr (the uCameraQFPS inside his own uCameraCtrl), pitch (-1..1), yaw}; None when the
    camera is not his (owner +0xB0) or the object there is not uCameraQFPS (its vtable)."""
    try:
        cam = u64(m, player + CAM_OWNED)
        if not ptr_ok(cam) or u64(m, cam + CAM_OWNER) != player or u64(m, cam + QFPS_OFF) != base + QFPS_VT:
            return None
        pitch, yaw = struct.unpack("<2f", m.rd(cam + QFPS_OFF + QFPS_PITCH, 8))
    except (ValueError, OSError):
        return None
    if not (math.isfinite(pitch) and math.isfinite(yaw) and -1.001 <= pitch <= 1.001 and abs(yaw) <= 3.1417):
        return None
    return {"addr": cam + QFPS_OFF + QFPS_PITCH, "pitch": pitch, "yaw": yaw}


def aim_writer(m):
    """The aim lock's writer for this session: write(addr, pitch, yaw) -> True once both floats are written and read
    back (within LOCK_TOL: the game's frame may ease them). None without the session's adapter or with modifications
    off (the keys aim)."""
    ad = getattr(m, "adapter", None)
    if ad is None or getattr(m, "mercs_no_modifications", False):
        return None

    def write(addr: int, pitch: float, yaw: float) -> bool:
        try:
            ad.write_memory(addr, struct.pack("<2f", pitch, yaw))
            back = struct.unpack("<2f", ad.read_memory(addr, 8))
        except (RuntimeError, ValueError, OSError):
            return False
        return abs(back[0] - pitch) <= LOCK_TOL and abs(wrap(back[1] - yaw)) <= LOCK_TOL
    return write


def aim_point(e, ppos) -> tuple:
    """Where to aim at e: his chest on (or near) his floor; one off it (a ceiling's, a hanging one) at its own position
    OFF_FLOOR_AIM_H up."""
    x, y, z = e["pos"]
    return (x, y + (CHEST_H if abs(y - ppos[1]) <= MAX_DY else OFF_FLOOR_AIM_H), z)


def near_line(origin, toward, pt, r: float, reach: float = 1e9) -> bool:
    """Whether the line origin -> toward passes within r of pt, ahead of origin and within reach."""
    have = math.dist(origin, toward)
    if have < 1.0:
        return False
    d = tuple((toward[k] - origin[k]) / have for k in range(3))
    along = sum((pt[k] - origin[k]) * d[k] for k in range(3))
    if not 0.0 < along <= reach:
        return False
    return math.dist(pt, tuple(origin[k] + along * d[k] for k in range(3))) <= r


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


class BlastBook:
    """The remote bomb's reach in this title, learned from its blasts: each booked blast {me_cm, hp_lost, hit_cm,
    spared_cm, real, self_hit, at}; radius = the farthest reach of the blasts read where the bomb lay (the zombies it hurt,
    his own distance when it hurt him with nobody near), BOMB_RADIUS_CM before any, never past BOMB_RADIUS_MAX. Kept in
    learn_dir / BOMB_BOOK_FILE (none: this run only)."""

    def __init__(self, learn_dir=None):
        self.path = Path(learn_dir) / BOMB_BOOK_FILE if learn_dir else None
        self.blasts: list = []
        if self.path is not None and self.path.exists():
            try:
                self.blasts = list(json.loads(self.path.read_text(encoding="utf-8")).get("blasts") or [])[-BOMB_BOOK_N:]
            except (OSError, ValueError, AttributeError):
                self.blasts = []

    @property
    def radius(self) -> float:
        reach = [BOMB_RADIUS_CM]
        for b in self.blasts:
            if b.get("real") and b.get("v", 1) >= BOMB_BOOK_V:  # (older records counted the zombies he hurt himself)
                reach += [max(b.get("hit_cm") or [0])]
                if b.get("self_hit"):
                    reach.append(b.get("me_cm") or 0)
        return min(BOMB_RADIUS_MAX, max(reach))

    @property
    def safe(self) -> float:
        return max(BOMB_SELF_R, self.radius + BOMB_MARGIN_CM)

    def add(self, blast: dict) -> None:
        self.blasts = (self.blasts + [blast])[-BOMB_BOOK_N:]
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"radius_cm": round(self.radius), "safe_cm": round(self.safe),
                                       "blasts": self.blasts}, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass


# --- time bonuses -------------------------------------------------------------------------------------------------------
# The stage's time and combo bonuses are breakable set pieces on sUnit's lines (live census 2026-10-27, Mining the Depths:
# uSm5923 x5 the time bonuses, uSm5924 x2 the combo bonuses, on line 14 among the barrels and crates of line 13). A
# piece's current action sits at +0x13F0: cSmTimeBonusAct_Wait / cSmComboBonusAct_Wait while it waits to be broken (a
# shot or a kick); broken, it leaves that action. The class numbers differ by stage, the actions do not, so a bonus is
# found by its action. bonuses() walks every line at most every BONUS_RESCAN_S (each vtable named once) and between
# walks re-reads only the found pieces' actions.
PIECE_ACTION = 0x13F0
BONUS_ACTIONS = {"cSmTimeBonusAct_Wait": "time", "cSmComboBonusAct_Wait": "combo"}
BONUS_RESCAN_S = 3.0
_BONUS: dict = {"base": None, "at": -1e9, "units": (), "names": {}}


def bonuses(m, base: int, now: float | None = None) -> list[dict] | None:
    """The bonuses still waiting to be broken: [{ptr, pos, kind ("time" / "combo")}]; None when a read failed."""
    now = time.monotonic() if now is None else now
    cache = _BONUS
    if cache["base"] != base:
        cache.update(base=base, at=-1e9, units=(), names={})
    names = cache["names"]
    if len(names) > 4096:
        names.clear()

    def name_of(obj, vt):
        if vt not in names:
            names[vt] = class_name(m, obj)
        return names[vt]

    def kind_of(u):
        act = u64(m, u + PIECE_ACTION)
        if not ptr_ok(act):
            return None
        return BONUS_ACTIONS.get(name_of(act, u64(m, act)) or "")

    try:
        if now - cache["at"] >= BONUS_RESCAN_S:
            cache["at"] = now
            found = []
            su = u64(m, base + S_UNIT)
            for line in range(N_LINES):
                u, n = u64(m, su + UNIT_LINES + LINE_STRIDE * line), 0
                while ptr_ok(u) and n < WALK_MAX:
                    vt = u64(m, u)
                    if (name_of(u, vt) or "").startswith("uSm"):
                        found.append((u, vt))
                    u, n = u64(m, u + UNIT_NEXT), n + 1
            cache["units"] = tuple(found)
        out = []
        for u, vt in cache["units"]:
            if u64(m, u) != vt:                             # freed since the walk
                continue
            kind = kind_of(u)
            if kind is None:
                continue
            pos = struct.unpack("<3f", m.rd(u + P_POS, 12))
            if all(math.isfinite(v) for v in pos):
                out.append({"ptr": u, "pos": pos, "kind": kind})
        return out
    except (ValueError, OSError, OverflowError):
        cache["at"] = -1e9
        return None


def near_ray(origin, dot, point, radius: float, slack: float = FIRE_SLACK) -> bool:
    """Whether the ray origin -> dot reaches point (it does not end more than slack short of it) and passes within
    radius of it."""
    have, want = math.dist(origin, dot), math.dist(origin, point)
    if have < 1.0 or want < 1.0 or have < want - slack:
        return False
    d = tuple((dot[k] - origin[k]) / have for k in range(3))
    along = sum((point[k] - origin[k]) * d[k] for k in range(3))
    if along <= 0.0:
        return False
    return math.dist(point, tuple(origin[k] + along * d[k] for k in range(3))) <= radius


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
QSHOT_R, QSHOT_CONE, QSHOT_GAP_S = 200.0, math.radians(35), 1.5   # point blank only (450 until 16:30)
READY_S, LASER_WAIT_S, RAY_STALE_S = 0.12, 0.7, 1.0
KEEP_TARGET, THREAT_R, COMMIT_S = 1.5, 250.0, 1.0
HIT_S = 0.45                            # a zombie's health falls within this of the shot that hit him
GRAB_R, GRAB_S, STUCK_S, BREAK_S = 120.0, 0.6, 0.5, 1.2
AUTO_QTE_WAIT_S = 0.0                   # with the game's own auto QTE on (re6_switch_mods.auto_qte), a hold read in RAM
                                        # gets this long with nothing pressed before he shakes free as without it. 0:
                                        # MercMode's RE6 turn of 2026-10-27 09:29 with 1.2 s showed the option frees no
                                        # grab by itself - every hold ended in a bite (450 -> 387 in 1.05 s, 359 -> 244
                                        # in 1.76 s, 244 -> 150 in 4.2 s) and he died in round 1 - so he shakes at once
HOLD_LOG_N = 12                         # the last holds kept in stats hold_log
WIGGLE = (("b", "lup"), ("lright", "lup"), ("b", "lright"), ("ldown", "lright"),   # break free: the prompt shows B
          ("b", "ldown"), ("ldown", "lleft"), ("b", "lleft"), ("lleft", "lup"))      # (live), mashed, the stick round
DEAD_WAIT_S = 2.5                       # "YOU ARE DEAD - CONTINUE?" takes input ~4 s after the death
RELOAD_GAP_S = 1.5
TABLET_HP, TABLET_CLEAR_R, TABLET_GAP_S = 0.6, 150.0, 3.0   # a tablet (R) at 60 % health or less while he is free,
TABLET_LOW_HP = 0.6                     # whoever is near: the case never runs out (re6_switch_mods.infinite_tablets);
                                        # MercMode's RE6 turn of 2026-10-27 09:29-09:43 took 1 tablet in 8.5 min under
                                        # the old 50 % / nobody-within-1.5 m rule and died 4 times after runs of bites
# Crowd control (operator 2026-10-27: "when zombies are up close in re6, do a series of quick attacks to deal with them
# ... unlimited stamina so they can use quick attacks when they have enemies near as form of crowd control"; the combat
# gauge is kept full by re6_switch_mods.infinite_stamina): a zombie within CC_R in front or flanking (CC_CONE) puts the
# gun down for the game's quick shot every CC_QSHOT_GAP_S and a kick at arm's length every CC_KICK_GAP_S, before it can
# grab (that turn: 30 grabs, 21 of them bites of ~110); the ones further back get the gun's bursts as before.
CC_R, CC_CONE = 200.0, math.radians(100)   # point blank only (operator 16:30; 350 until then; 5 m all round was tried live
                                        # 2026-10-27 13:43 / 13:53: more holds, fewer kills)
CC_QSHOT_GAP_S, CC_KICK_GAP_S, CC_ATTACK_CONE = 0.5, 0.4, math.radians(60)
QA_FAST, CC_FAST_GAP_S = False, 0.15    # with quick_attack on (re6_switch_mods: his quick attacks x10) they go out back to
                                        # back: this often, the gauge kept full by infinite_stamina
CC_BACK_N, CC_BACK_R = 3, 400.0         # this many within this: he steps back while he fires (the earlier back-off)
# Dying (RE6's 1-health state: he crawls; every death in the 2026-10-27 runs came through it, at 1 health for 3 s and
# more): R pressed for a tablet every DYING_GAP_S while the case holds one; stats tablet_dying_presses / _taken (the
# count fell) say whether the game takes it there, dying_states the action bytes seen while dying.
DYING_TABLETS, DYING_HP, DYING_GAP_S = False, 1, 1.0   # off: RE6 takes no tablet while dying (live 13:55: 4 presses
                                        # at 1 health, the count never fell); dyings / dying_states still counted
# Not reaching 1 health in a crowd: with CROWD_TABLET_N within CROWD_TABLET_R a tablet already at CROWD_TABLET_HP; in
# crowd control with CC_BACK_N within CC_BACK_R the kicks and quick shots carry the stick back (stats cc_backouts).
CROWD_TABLET_N, CROWD_TABLET_R, CROWD_TABLET_HP = 4, 300.0, 0.85
TABLET_LOWER_S = 0.3                    # R only this long after ZL was last held
TABLET_CONFIRM_S, TABLET_RETRY_S = 1.5, 1.0   # a press that took one drops the count within this; one the game ignored
                                        # (live 2026-10-27: 5 of 6 presses in a crowd left the HUD's count at 7) is
                                        # pressed again this soon, and only while he is free (action 0)
AUTO_IDS = frozenset({0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x28})   # ZR held, not tapped: the guns the fire action's
                                        # own loop fires again while the trigger stays down (Ghidra: main+0x1098470, the
                                        # weapon class 0x20 / 0x40 of main+0xF42980 or the types 0x10D / 0x128; Chris's
                                        # assault rifle 0x0F: held 2.5 s, 24 rounds); any other gun fires once a press
# Line of sight (operator 2026-10-27 11:12: "right now they are shooting at a wall"; MercMode's RE6 turn of 10:50-11:20:
# of the last 30 pulls, 25 aimed along the camera's line - the laser not read - and the 12 of those at a zombie 13-20 m
# off all missed; the laser, when read, ended 1.6 m out on a wall in front of the one at 15.9 m. The camera's line runs
# through walls.) A zombie the laser's ray ends short of (FIRE_SLACK, the ray on him within LOS_YAW / LOS_PITCH) is out
# of sight for BLOCK_S; so is one the trigger worked on for NOHIT_S without his health falling, and one CC_MISS_N quick
# shots in a row left whole. Those are never fired at, never the target while another is open, and crowd control leaves
# them; the camera's line fires only within CAM_FIRE_R, or on one whose health fell to a shot within SEEN_S. All in reach
# out of sight: he walks at the nearest with a side step swapped every DETOUR_S (a way round). A still laser is stale
# only once the camera turned RAY_STALE_TURN under it (standing still behind a wall freezes it too).
BLOCK_S, NOHIT_S, SEEN_S, NOHIT_GAP_S = 2.5, 1.0, 3.0, 0.5
BLOCK_MIN_R = 200.0                     # never out of sight this near: crowd control always works on him (live 11:37:
                                        # quick shots that took no health marked ones at 87-92 cm, and he died twice)
LASER_SEEN_S = 1.0                      # the laser's ray on him this recently: the camera's line may fire at him too
CAM_FIRE_R = 1000.0
LOS_YAW, LOS_PITCH = math.radians(3), math.radians(3)
RAY_STALE_TURN = math.radians(5)
CC_MISS_N = 2
DETOUR_S = 1.5
# Remote bombs (operator 2026-10-27: "they should put remote mines down and detonate them as they make a stand going
# from section to section"), the flow measured live 2026-10-27 (Chris, Liquid Fire): the D-pad's down steps the item
# wheel (+0x5064 then names slot 12, the remote bomb; a press or two), ZL + ZR throws one about 3 m ahead along the aim
# and that slot's mode turns 1 (the remote stays in his hand), ZL + ZR again sets it off (mode 0) and the game puts the
# gun back in his hand by itself; one blast took 11 J'avo (000 -> 011 kills, an 11 combo, in 3 s). With the loadouts'
# bombs (re6_switch_mods.merc_loadout) and infinite_grenades every character carries five that never run out.
BOMBS = True
# Rare and safe (operator's mine anxiety in numbers, live 2026-10-27 14:02: 48.5 s of 150 in bomb acts, 1573 health
# lost there): one goes out only with him above BOMB_MIN_HP, nobody within BOMB_ROOM_R and BOMB_STAND_N coming within
# BOMB_COMING_MIN_R..BOMB_STAND_R (it lands at his feet: he walks off it as they come over it), at most every BOMB_GAP_S;
# clear of it, it goes off with BOMB_BLAST_N within BOMB_BLAST_R of it or anyone within BOMB_ON_R of it.
BOMB_STAND_N, BOMB_STAND_R, BOMB_ROOM_R = 3, 1200.0, 400.0   # (4 at 6-12 m placed none in 150 s live 14:18: the
BOMB_COMING_MIN_R = 500.0                                   # operator wants the mines; 3 at 5-12 m)
BOMB_ON_R = 300.0
BOMB_GAP_S = 30.0                       # a bomb at most this often
BOMB_AHEAD = 300.0                      # where it lands (live: 2.9 m ahead along the aim)
BOMB_BLAST_R, BOMB_BLAST_N = 400.0, 2   # set off with this many zombies this near it ...
BOMB_SELF_R = 700.0                     # ... and him at least this far from it, never nearer: the floor of the rule
                                        # below (live 2026-10-27: set off from about 3 m, both blasts knocked Chris down)
# The blast's reach, learned (operator 2026-10-27 12:10: "is still standing on top of mines. The bot needs to learn the
# proper distance needing to be had and respect that"): every blast whose bomb was read where it lay (snapshot
# bomb_pos) books the farthest zombie it hurt and, when it cost him health with nobody at arm's length to blame, his
# own distance (BlastBook, learn_dir / BOMB_BOOK_FILE, per title). The rule: the learned radius + BOMB_MARGIN_CM, never
# under BOMB_SELF_R; he never sets it off inside it, whatever the wait, and inside the radius itself he walks out
# before anything else but breaking a hold. Until the bomb is read it is taken to lie where he stood throwing it.
BOMB_RADIUS_CM, BOMB_RADIUS_MAX = 500.0, 900.0   # before any blast is booked (live 11:35-11:38: zombies hurt to 4.9 m,
                                        # spared from 4.85 m); a booked reach is capped here (a barrel's chain blast)
BOMB_MARGIN_CM = 200.0
BOMB_BOOK_FILE, BOMB_BOOK_N = "re6_bomb_blasts.json", 40
BOMB_BOOK_V, BOMB_ME_R = 2, 300.0       # the book's record version; zombies this near him at a blast are left out of
                                        # it (his own kicks and shots hurt them: MercMode 12:58 booked one hurt 10.2 m
                                        # from the bomb at his elbow, and the reach went to the 9 m cap)
BOMB_LEARN_S, BOMB_SPARE_R, BOMB_BLAME_R = 0.7, 1500.0, 200.0   # a blast's toll read this long after it; the zombies
                                        # within SPARE_R left whole are the spared; one within BLAME_R of him takes the
                                        # blame for his health instead
BOMB_HOLD_S = 8.0                       # out this long: off once he is clear
# A bomb out never means standing still among them (operator 2026-10-27 13:06: two J'avo at arm's length hitting him
# while he stood turned to his bomb, the gun down): with one within BOMB_FIGHT_R he backs off the bomb and kicks the
# nearest in the same ticks (ZR alone; ZL + ZR would set the bomb off); clear of it he sets it off as soon as one comes
# within BOMB_DET_NEAR_R (the gun comes back with the blast); the camera turns to the bomb standing only with nobody
# within BOMB_FACE_CLEAR_R and for BOMB_FACE_MAX_S a bomb at most. No bomb is readied with BOMB_CROWD_N within
# BOMB_CROWD_R (it lands at his feet). stats bomb_face_s, bomb_kicks, bomb_hits_taken (health lost in a bomb act).
# Aggression (operator 2026-10-27 13:10: "proactive with a rapid fire magnum absolutely removing all nearby enemies ...
# throwing grenades at 16x speed and flashbanging the enemies and going on a melee fever ... It is essential to be
# proactive with combo time"):
#   flash: FLASH_N within FLASH_R and none within NADE_CLEAR_R - the flash grenade (the item wheel stepped with the D-pad's
#          down, ZL then ZR at them), the gun back (the D-pad's right), then the melee fever for FEVER_S: at the stunned
#          ones within FEVER_R, walking in and kicking (the finishers) every CC_KICK_GAP_S, no quick shots;
#   grenade: a cluster of NADE_N (within NADE_CLUSTER_R of one another) NADE_MIN_R..NADE_MAX_R off - the hand grenade
#          (else the incendiary), never nearer than its blast;
#   combo: with the combo window under COMBO_LOW_S the nearest open zombie is the target (kicked at arm's length), a bomb
#          out goes off with one on it; stats combo_breaks (it lapsed with one in reach), combo_best.
# The whole kit (operator 17:42: "over the course of the match the bot is also using all of their grenades. Basically
# the bot should be flashbanging these guys and then going up and doing melee attacks on them and hitting them with QTE
# events"): on - the flash at FLASH_N within FLASH_R, then the fever (in among the stunned ones, kicks; FEVER_S, left the
# moment one that was not flashed comes within FEVER_BREAK_R); the hand and incendiary grenades turn about into clusters
# NADE_MIN_R..NADE_MAX_R off, at most every FRAG_GAP_S. stats flashes, fever_kicks, fever_kills, fever_breaks, frags,
# fires (the incendiaries), grenade_kills. The switch-off: bot_options nades=false.
NADES = True                            # (on per profile, re6_switch_mods bot_options nades=); the wheel measured live 14:17 (_wheel_key; the D-pad's right from an item lands
                                        # on wheel index 0, between the guns it steps 0 -> 1 -> 2 -> 0; a throw leaves the
                                        # game's own pick of a gun in hand - the knife, index 2 - so the gun back is to his)
NADE_UP_FROM = 11                       # from a gun, the wheel's up reaches the flash (11) and the bomb (12) first
FLASH_N, FLASH_R, NADE_CLEAR_R = 4, 500.0, 200.0   # (3 flashed on every horde: MercMode 15:38-15:51, 30 flashes and
FLASH_GAP_S = 12.0                      # 115 fever kicks in 12 min, kills a minute down a fifth; 17:42: 4+ within 5 m)
FRAG_GAP_S, FEVER_BREAK_R = 10.0, 250.0
SPAM_CLUSTERS, SPAM_S = 2, 3.0          # (operator 19:01: "able to spam them if needed") two clusters about: no gap
BOMB_NADE_R = 800.0                     # the crowd for a bomb this near already: a grenade into it instead (no time to
                                        # walk off a bomb); stats bomb_choices / nade_choices
# The flash when they are on him, within FLASH_R (live 14:31: with "nobody within 3 m" none was ever thrown), no call-off
# but a hold, no facing.
# The bomb dropped while backing out of a crowd (BOMB_DROP_N within CC_BACK_R, him above BOMB_MIN_HP, BOMB_GAP_S since
# the last): the wheel's up (one press from a gun) to it, ZL then ZR at his feet, then out of its reach first and set
# off from the rule's distance as they come (stats bomb_drops).
BOMB_DROP = False                       # off by default: on per profile (re6_switch_mods bot_options bomb_drop=)
BOMB_DROP_N = 8                         # surrounded (operator 15:18: "surrounded by eight or more enemies ... drop a
                                        # remote mine and run away from that location"): this many within CC_BACK_R
# Not being surrounded (operator 15:18: "avoiding letting yourself be surrounded ... using the weapons at your disposal
# to avoid that"): with KITE_N within KITE_R he keeps moving toward open space - the heading of KITE_DIRS whose zombies
# within KITE_SCAN_R stand least in its way (and away from a bomb out) - while he aims and fires, in crowd control and
# walking off a bomb too, kicking one in the way. The left stick by the camera: up its heading, left +90 deg (a larger
# yaw is to the screen's left: rleft turns it up). stats kite_s, surround_events (SURROUND_N within CC_BACK_R),
# max_within_4m.
KITE_N, KITE_R, KITE_SCAN_R, KITE_DIRS = 3, 600.0, 700.0, 16
# Confirmed-hit fire (operator 15:27: "if the ghidra hook is able to tell them if the shot they are lining up will hit
# then have them take the shot. I love seeing the long shots"): the laser's ray ending on (or running through) any
# living zombie fires at once, at any distance; with nobody within ENGAGE_R the gun comes up for one in front out to
# LONG_R (the laser shows whether he is in sight). stats confirmed_shots, moving_shots (the stick on as it fires),
# long_shot_kills (one over LONG_KILL_R dying within LONG_KILL_S of the trigger on him).
LONG_R, LONG_KILL_R, LONG_KILL_S = 3500.0, 1500.0, 1.5
QUICK_ACTION_NAMES = frozenset({"cPlAction_pl_act_attack_ex", "cPlAction_pl_act_weapon_comn_quick_shot",
                                "cPlAction_pl_act_jake_hand_quick_attack"})   # his quick attacks (re6_switch_mods)
SURROUND_N = 8
NADE_N, NADE_MIN_R, NADE_MAX_R, NADE_CLUSTER_R = 3, 500.0, 1000.0, 300.0
NADE_GAP_S, NADE_STEP_S, NADE_STEPS, NADE_AIM_S, NADE_FACE_S = 3.0, 0.45, 8, 0.3, 0.8   # the wheel's step pace is
                                        # the bomb's (live 13:43: at 0.2 s a step the wheel ran past the grenades to the
                                        # remote bomb)
NADE_START_R, NADE_FACE_ERR = 300.0, math.radians(60)   # a throw starts with nobody this near; the camera turned to
                                        # them only when they are this far off the aim
NADE_WHEEL_N = 6                        # stats nade_wheel: the last throws' wheel steps (the item in hand after each)
# The trigger's safety (live 13:43: a crowd-control quick shot with the remote bomb in hand threw it and set it off at
# his feet): ZL + ZR goes out only with a gun in hand (wheel index < WEAPON_INDEXES) or in a throw of the bomb's or a
# grenade's own; otherwise the D-pad's right brings the gun back first (stats unsafe_trigger_blocks).
THROW_ACTS = ("bomb_place", "bomb_det", "nade_frag", "nade_fire", "nade_flash")
NADE_KILLS_S = 3.0
FEVER_S, FEVER_R = 2.5, 500.0           # the fever: kicks at arm's length, quick shots at the rest, at crowd control's pace
COMBO_LOW_S = 3.0
# The whole stage's zombies (operator 15:25: "make him aware of the locations of any and all enemies in the level, so
# that in the event that he's unable to locate enemies to defeat, in order to maintain the combo, he knows where enemies
# are and is able to go and pursue them"): the snapshot's enemies are sEnemy's whole list, every floor. With nobody on
# his floor in reach he goes after the best of them - his floor first, then the nearest - walking along the camera
# turned to him; not PURSUE_STUCK_CM further in PURSUE_STUCK_S, a side step for PURSUE_SIDE_S (the side swapped each
# time). With the combo running (COMBO_LOW_S) a pursuit is counted: pursuit_kills when the kill count rises, pursuit_
# lapses when the combo lapses first; census_alive / census_floor the stage's living zombies and those on his floor.
PURSUE_STUCK_CM, PURSUE_STUCK_S, PURSUE_SIDE_S = 30.0, 1.0, 0.8
# Taunts (operator 15:33: "taunts and random dances when they do damage to a large group or kill a boss"): RE6's partner
# call on the right stick's click puts him in his emotion action (cPlAction_pl_act_emotion, the game's own gesture and
# line; the HUD's uIdEmotion). After TAUNT_KILLS kills within TAUNT_KILLS_S, a blast (bomb / grenade) that took
# TAUNT_BLAST, or a boss down (one of at least BOSS_HP gone), with nobody within TAUNT_CLEAR_R and not more often than
# TAUNT_GAP_S: one click (a tap, or held TAUNT_HOLD_S for the other call, picked at random). stats taunts (by trigger:
# taunt_multi / taunt_blast / taunt_boss), taunts_seen (his action turned emotion within TAUNT_SEEN_S of the click).
TAUNTS = False                          # (off: in solo Mercenaries R3 never put him in the emotion action - 0 of 5
                                        # live 16:13-16:25; a RAM emotion request is the follow-up)
TAUNT_KILLS, TAUNT_KILLS_S, TAUNT_BLAST, BOSS_HP = 4, 2.0, 3, 1500
TAUNT_CLEAR_R, TAUNT_GAP_S, TAUNT_HOLD_S, TAUNT_SEEN_S = 400.0, 8.0, 0.6, 1.5
EMOTION_ACTION = "cPlAction_pl_act_emotion"
# RAM aim lock (operator 16:30, a frame with a boss hanging top right, the laser pointing away from it and Chris in boss
# smoke: "surely the ghidra hook can inform the bot as to where the enemy is on screen so that they can aim at them and
# deal with them ... These are life or death situations."). Ghidra: P1's camera [player + 0x3A28] (its owner [camera +
# 0xB0] == player) embeds the player camera uCameraQFPS at +0x16A0 (vtable main+0x25C4080). Its +0x2C4 yaw (radians,
# wrapped, the heading convention atan2(x, z)) and +0x2C0 pitch (-1..1) are the state the right stick turns:
# main+0x48A3F0 eases them toward a look request, clamps the pitch and wraps the yaw every frame (+0x2C8 / +0x2CC keep
# the last frame's). Read-only in MercMode's RE6 (16:15-16:40, 495 + 288 samples): the view's yaw equals +0x2C4 at rest
# (36.2 deg / 0.631 rad, -2.1 / -0.036, 168.2 / 2.936); the view's pitch runs about PITCH_DEG_PER_UNIT a unit of +0x2C0
# (PITCH_DEG_AT_0 at 0). Each tick the bot has a target it writes both - the yaw onto the camera's line through the
# target's aim point, the pitch from that line's slope plus a correction learned once the view settles - and reads them
# back: no camera keys for the aim. A write that fails or does not stick (LOCK_FAIL_N within LOCK_FAIL_S) puts the keys
# back for LOCK_OFF_S. stats aim_locks (a new target locked), lock_write_ok / lock_write_fail / lock_overwritten,
# lock_fallbacks, aimed_shots / aimed_hits (a locked shot, and its target's health falling within LOCK_HIT_S),
# boss_damage (health the big ones lost while locked), cc_vs_aimed (crowd-control quick shots per aimed shot).
AIM_LOCK = True
CAM_OWNED, QFPS_OFF, QFPS_VT, QFPS_PITCH = P_CAMERA, 0x16A0, 0x25C4080, 0x2C0   # (P_CAMERA / CAM_OWNER: the co-op readers')
PITCH_DEG_PER_UNIT, PITCH_DEG_AT_0 = 23.0, -1.5
LOCK_BIAS_GAIN, LOCK_BIAS_MAX, LOCK_SETTLE, LOCK_STILL = 0.35, 0.25, math.radians(1.5), math.radians(0.4)
# The pitch guard (live 20:00-20:22: up_aim_s 28.6 s over five rounds, most on High Seas Fortress / Requiem for War):
# the written pitch never runs more than LOCK_UP_SLACK above the target's own slope, nor above CLOSE_PITCH for one that
# is not up there itself; the learned correction is held to LOCK_BIAS_MAX (about 6 deg).
LOCK_UP_SLACK = math.radians(5)
LOCK_FAIL_N, LOCK_FAIL_S, LOCK_OFF_S, LOCK_HIT_S, LOCK_TOL = 5, 2.0, 3.0, 0.6, 0.02
# Aimed fire (the same message: "any enemy on screen or within ~15 m in line of sight, including ceiling or hanging
# enemies and bosses ... gets locked and shot at the magnum's rapid rate until dead; crowd-control quick shots only at
# point blank; bosses and large enemies get priority focus fire"): with the lock, every one alive within AIM_LOCK_R
# (3D - a ceiling's, a hanging one: no floor filter) or on his floor within ENGAGE_R is a target at any bearing (the
# lock turns the camera); the big ones (BIG_HP max health and more: uEm2100 / 2210 / 2300 hold 1000 in MercMode's
# census, the hordes 100-500) first. One off his floor is aimed at its own position (OFF_FLOOR_AIM_H up) and counted
# on the line within OFF_FLOOR_HIT_R of it.
AIM_LOCK_R, BIG_HP, OFF_FLOOR_AIM_H, OFF_FLOOR_HIT_R = 1500.0, 900, 60.0, 90.0
# Aimed fire is the default (operator 17:24-17:28: "the bot is relying too much on quick attack ... blasting the Magnum
# in rapid succession ... The quick shot is kind of a singular shot, so it basically locks him into just one enemy while
# other enemies continue to close in ... use quick shot sparingly and in the right situations ... aiming and actually
# hitting these targets generally in rapid succession"): with the lock he sweeps - the nearest first (one closing in
# before one standing), SWEEP_SHOTS aimed shots each (fewer once his health is gone), then the next; the quick shot
# only for a lone one at point blank (nobody else within CC_CROWD_R), a kick for one at arm's length (a grab threat);
# into a crowd the lock sweeps while he backs out. stats sweeps (targets left after SWEEP_SHOTS), targets_shot,
# targets_per_min (targets shot at a minute since the first aimed shot).
SWEEP_SHOTS, CC_CROWD_R, CLOSING_W = 3, 400.0, 0.5
FLASH = True                            # the flash alone at FLASH_N within FLASH_R (NADES adds the hand / incendiary
                                        # grenades and the melee fever after a flash)
# Down (operator 16:22: "when the character is down, They need to raise their weapon and blast like mad, nailing each
# and every target nearby to clear the area ... fire rate tripled ... so they can rise again"). MercMode 16:30, read
# only (player +0x13F0): knocked to 1 health he went buttobi_damage_common -> dying_loop, and from there RE6 fires -
# motion_ex -> lying_down_weapon_ready_loop -> weapon_fire (a kill at 16:30:13), kicks (attack_ex) and crawls
# (creeping_move) - until gets_up 15 s later, at 1 health; he died 2 s after it with no tablet (the tablet rule wanted
# more than 1 health). Down (DOWN_ACTIONS, held through DOWN_KEEP's while down): no tablet, no stick; the nearest within
# DOWN_FIGHT_R locked and fired at (a kick for one within MELEE_R); nobody near: the stick up to rise. Up at 1 health:
# a tablet at once. re6_switch_mods.down_fire triples the fire table while he is down. stats down_s, down_shots,
# down_kills, down_recoveries (gets_up after a down), dying_deaths (died at 1 health after dying, never above it since).
DOWN_ACTIONS = frozenset("cPlAction_pl_act_" + n for n in (
    "dying_loop", "creeping_move", "stand_to_creeping", "lying_down_weapon_ready_loop", "lying_down_weapon_ready_move",
    "lying_down_weapon_ready_turn", "damage_lying_loop", "go_lying_down", "buttobi_damage_to_lying", "go_any_down",
    "down"))
DOWN_KEEP = frozenset("cPlAction_pl_act_" + n for n in ("motion_ex", "weapon_fire", "attack_ex", "weapon_reload",
                                                        "weapon_comn_quick_shot"))
GETUP_ACTIONS = frozenset("cPlAction_pl_act_" + n for n in ("gets_up", "damage_gets_up"))
DOWN_FIGHT_R = 900.0
# Hazards (the same frame: "standing in boss smoke"): his health falling with nobody within HAZARD_CONTACT_R, not held,
# not his own blast - smoke, gas, fire, acid - marks his spot (HAZARD_R, for HAZARD_S); inside a mark he moves out
# toward open space while he keeps firing. stats hazard_marks, hazard_s.
HAZARD_CONTACT_R, HAZARD_R, HAZARD_S = 250.0, 400.0, 6.0
AIM_WALK_R, AIM_WALK_S = 800.0, 0.8     # aiming this long without the line on one this near: he walks at him
TICK_S = 0.05                           # the engine's tick (gbox.mercs.engine tick_s)
BOMB_FIGHT_R, BOMB_DET_NEAR_R, BOMB_FACE_CLEAR_R, BOMB_FACE_MAX_S = 200.0, 400.0, 400.0, 0.4
BOMB_CROWD_N, BOMB_CROWD_R = 2, 300.0
DEATH_LOG_N, HP_HIST_S = 8, 3.0         # stats death_log: the last deaths, each with his last HP_HIST_S
BOMB_STUCK_S, BOMB_SIDE_S = 0.6, 0.8    # walking off it: not 30 cm further in this long, a side step this long
BOMB_HURT_HP = 50                       # a blast that takes this much of his health (BOMB_LEARN_S): stats bomb_self_hits
BOMB_LOG_N = 12
BOMB_REAL_R = 3000.0                    # the placed bomb's unit (snapshot bomb_pos) within this of him: its spot is used
                                        # (stats bomb_aim_err_cm: how far it lay from 3 m ahead of the throw)
BOMB_MIN_HP = 0.7                       # no new bomb under this much health (live 12:29: a throw at low health dropped it
                                        # at his feet and he crawled out of its reach at 1 health, too slow)
BOMB_RETRY_S = 4.0                      # readying one given up (one came within BOMB_ROOM_R): tried again this soon
                                        # (live 11:21: 900 -> 1 health in 5 s readying one with two at 76 cm)
BOMB_STEP_S, BOMB_STEPS, BOMB_AIM_S = 0.45, 8, 0.45   # the wheel's step pace and presses, ZL held before ZR
BOMB_FACE, BOMB_FACE_S = math.radians(25), 1.5        # the throw waits (this long at most) for the crowd in the aim
BOMB_TAKE_S, BOMB_KILLS_S = 2.0, 3.0    # a throw / a blast shows in its slot within this; its kills counted this long
REPLAY_LOAD_S = 60.0                    # a death's YES replay loads this long at most before it counts as lost
# Time bonuses (operator 2026-10-27: "I am not seeing them go after the time bonuses"; snapshot bonuses): with nobody
# within BONUS_SAFE_R, a bonus within BONUS_R (flat) and BONUS_DY (height) is shot - the camera turned to it with the
# gun down, then the gun up and the laser's ray (or the camera's line) closed onto it, the trigger down while the ray
# passes within BONUS_HIT_R of it and does not end short of it. Aimed at BONUS_TRY_S without breaking (out of sight):
# left for BONUS_SKIP_S. Every break (his shot, a bomb, a kick) counts as taken, a bonus still waiting when the round
# ends as missed: stats bonuses_taken / bonuses_missed (per round: round_*, bonus_log).
BONUS_PURSUIT = False                   # (shooting them: off - operator 16:52, they break only to a physical attack)
BONUS_R, BONUS_DY, BONUS_SAFE_R = 2500.0, 600.0, 600.0
BONUS_H, BONUS_HIT_R = 130.0, 45.0     # the capsule's middle (a frame of one, 2026-10-27: a column ~2.6 m tall
                                        # with its glowing part around 1.3 m up; 40 cm aimed at its foot - live,
                                        # 12 bonus shots on High Seas Fortress broke none)
BONUS_TRY_S, BONUS_SKIP_S = 2.5, 30.0   # (5 s a try wasted 20 s on 4 out of sight live 14:41)
BONUS_RESET_N = 3                       # this many gone in one tick: the round started again (a replay), not breaks
BONUS_LOG_N = 12
# Sight (operator 18:58: "Every time the bot points a gun at a wall, I cry"): a zombie the nav mesh says is behind a
# wall from him (NavMesh.clear: the line between them crosses a floor edge with no neighbour) counts as out of sight -
# never a target, the camera never turned to him (stats offscreen_skips); one off his level, or the mesh unknown: the
# laser decides - locked on him LOS_PROBE_S and the ray ending short of him (within LOS_PROBE_ERR of his line): out of
# sight for BLOCK_S (stats los_blocks). None in sight: walked toward by the nav mesh. stats wall_aim_s: the laser's dot
# within WALL_AIM_R of the muzzle while zombies are about (the aim on a wall; target 0).
SIGHT_S, LOS_PROBE_S, LOS_PROBE_ERR, WALL_AIM_R = 0.25, 0.3, math.radians(8), 150.0
# Wind-ups (operator 19:25: "The bot should be able to tell who is transitioning into an attack animation and be able to
# prioritize deactivating them with an attack"): each enemy within ACTION_READ_R has its action (+0x13F0) in the
# snapshot. Live, MercMode 19:30 (Mining the Depths, 416 samples): the J'avo (uEm1000) threaten with a knife
# (cEm1000ActIkakuKnife), attack one-handed (ActAtkOneHand / ...Dash) and walk with a gun raised (ActWalkGunL / R / B);
# the zombies (uEm5000) start a grab with ActCatch (then ActNeckHangCS); hits put them in ActDmg*. A melee wind-up
# within WINDUP_R, or a raised gun within RANGED_R, is the top target: the nearest of them before anyone else (the lock's
# aimed magnum stops it; the kick and the prompts follow); two winding up within FLASH_R get the flash. stats
# windup_seen (wind-ups begun), windup_interrupts (one in a wind-up hit into ActDmg*), hits_after_windup (his health
# falling with one winding up within WINDUP_HIT_R).
ACTION_READ_R, WINDUP_R, RANGED_R, WINDUP_HIT_R = 2000.0, 500.0, 1500.0, 250.0
WINDUP_KEYS = ("Atk", "Attack", "Catch", "Ikaku", "Grab", "Bite", "Lunge", "Throw")
RANGED_KEYS = ("WalkGun", "GunAim", "Shoot", "Shot", "Bow", "Rocket")


def windup(e, me=None) -> str | None:
    """'melee' / 'ranged' for one winding up an attack on him (by its action), else None."""
    a = e.get("action") or ""
    if not a or "Dmg" in a:
        return None
    d = math.hypot(e["pos"][0] - me[0], e["pos"][2] - me[2]) if me is not None else 0.0
    if any(k in a for k in WINDUP_KEYS) and d <= WINDUP_R:
        return "melee"
    if any(k in a for k in RANGED_KEYS) and d <= RANGED_R:
        return "ranged"
    return None
# Threats only (operator 19:09, a frame at low health aiming up at the ceiling with nothing there: "Aiming up for no reason
# is how you get killed in this game ... if it's not in the vicinity, then she's basically risking her life"): an aim
# target is one on his level (within AIM_DY) in sight, or a real vertical threat - one above him within CEILING_R, or a
# big one (BIG_HP) - never one on another floor that can't reach him (stats offlevel_skips; still in the census for the
# walks). One on his level within CLOSE_R: only those, the lock's pitch never above CLOSE_PITCH. Low health (under
# SURVIVAL_HP): survival - only the ones within CLOSE_R, backing away from the nearest, no long shots, no upward aim
# (stats survival_s). stats up_aim_s: the camera's pitch over UP_AIM with no vertical threat (target 0).
AIM_DY, CEILING_R, CLOSE_R, CLOSE_PITCH, SURVIVAL_HP, UP_AIM = 180.0, 400.0, 600.0, math.radians(15), 0.35, math.radians(20)
# The turn governor (the RE5 lesson, 19:05: a time scale raised while the shot plays turns any stick held then many
# times too fast): his body's heading turning faster than SPIN_DEG_S, or his action one the mods speed up (a quick
# attack, the magnum's shot), releases the sticks for that tick (a grab's escape exempt). stats spin_deg_s (the
# fastest seen), whips (ticks released).
SPIN_DEG_S = 150.0
STICK_KEYS = frozenset({"lup", "ldown", "lleft", "lright", "rup", "rdown", "rleft", "rright"})
BOOSTED_ACTIONS = frozenset({"cPlAction_pl_act_weapon_comn_quick_shot", "cPlAction_pl_act_attack_ex",
                             "cPlAction_pl_act_jake_hand_quick_attack"})   # (+ weapon_fire with a magnum: x3)
MAGNUM_IDS = frozenset({0x07, 0x08})
# Walking by the nav mesh (snapshot navmesh): the bonus run and the combo pursuit walk its path - toward the next
# waypoint, the ones within NAV_REACH_R dropped, replanned every NAV_REPLAN_S, on a new goal or after a stall; with the
# aim lock's writer the camera's yaw is written onto the way (no turning keys). stats nav_paths, nav_fails (no path:
# straight at it as before).
NAV_WALK, NAV_REACH_R, NAV_REPLAN_S = True, 90.0, 1.5
# Taking the game's prompts (snapshot prompts; operator 16:54: "if they hit an enemy and they get an opportunity to do a
# QTE event, they must activate that QTE event immediately"; 17:50-17:52 the climb prompts, "it should be aware that
# there's a button press that's required for it to relocate to the next area"; take pickups "when they're free and
# safe"): a shown prompt's button is pressed at once (a stick mask: the stick round), again every PROMPT_REPEAT_S while
# it stays (a mash); a pickup (Y) only with nobody within PROMPT_SAFE_R; none while a bomb or an item is in his hand
# (the remote's ZR, a grenade's throw). A prompt gone within PROMPT_TAKEN_S of a press counts as taken. stats
# prompts_seen / prompts_taken, prompt_types {type: [seen, taken, key]}, prompt_latency_ms (the mean from shown to
# pressed), climbs (B taken while not held), pickups (Y taken); the B spots are logged per stage for the nav
# (learn_dir / PROMPT_SPOTS_FILE: {stage: [[x, y, z, type], ...]}).
PROMPTS, PROMPT_REPEAT_S, PROMPT_TAKEN_S, PROMPT_SAFE_R = True, 0.15, 1.5, 300.0
PROMPT_SKIP_KEYS = frozenset({"r"})     # R: the heal hint shown whenever he is hurt (live 17:55: types 1 / 26 with
                                        # button 34 at 780 / 900 health) - tablets stay with the tablet rules
PROMPT_SPOTS_FILE, PROMPT_SPOTS_N, PROMPT_SAVE_S = "re6_prompt_spots.json", 200, 30.0
# The weapon in hand (operator 18:00: "if the bot is grabbed ... change their equipped weapon to a rapid fire shotgun
# randomly or a magnum at random ... I want to be able to change what weapon is being used by the bot actively ...
# instantly"): WANT_WEAPON (re6_switch_mods live_weapon, the app's dropdown) or, after a grab, a random loaded shotgun or
# magnum (GRAB_SWAP) is the wheel index he switches to - the game's own weapon switch, the D-pad's right every
# WEAPON_TAP_S (the guns cycle 0 -> 1 -> ... -> 0; from an item it lands on 0) until it is in hand, not while held, a
# throw or a bomb is under way; WEAPON_TRIES presses without it: left for WEAPON_REST_S. stats weapon_switches (taps),
# weapon_swaps (a grab's pick), weapon_in_hand. A grab with a bomb out and him outside the learned reach (+ margin): ZR
# in the mash with the remote in hand (stats grab_det_presses; grab_detonations when it went off during the hold).
WANT_WEAPON, WANT_WEAPON_AT = None, -1e9
GRAB_SWAP, GRAB_DETONATE = True, True
WEAPON_TAP_S, WEAPON_TRIES, WEAPON_REST_S = 0.35, 9, 5.0
SHOTGUN_MAGNUM_TYPES = frozenset({0x104, 0x105, 0x106, 0x107, 0x108})
# The shotgun clears the circle (operator 19:25, the RE5 rule): CROWD_GUN_N within CROWD_GUN_R on his level and no
# weapon asked for in the app - a loaded shotgun (the Assault Shotgun first) is the weapon until the circle thins.
# stats crowd_shotgun_s.
CROWD_GUN_N, CROWD_GUN_R = 3, 500.0
SHOTGUN_ORDER = (0x105, 0x104, 0x106)
# The round plan, phase 1: the bonus run (operator 16:52: "You can't shoot it from a distance. You have to walk up to it
# and dispatch the time bonus physically" ... "running from Checkpoint to Checkpoint, grabbing the time bonuses ... after
# grabbing all the time bonuses, that's when the match truly begins and they can begin to make a stand"; 16:55: a round
# ended almost at once with them untaken). While any bonus waits: the nearest next (his floor first, then the nearest),
# walked to along the camera turned to it (a side step when the walk stalls: PURSUE_STUCK_*), and within BONUS_MELEE_R
# the gun down and the physical attack (ZR alone) every BONUS_MELEE_GAP_S until it breaks. Only a zombie within
# BONUS_BLOCK_R is fought on the way (a grab's escape comes first as always). One walked to for BONUS_WALK_S or attacked
# for BONUS_HIT_S without breaking is left for BONUS_SKIP_S. Phase 2, the match: everything else as before. stats phase
# ("bonus_run" / "match"), bonus_time_s (the seconds of bonus runs), bonus_melee (the attacks on bonuses), bonus_skips.
BONUS_RUN = True
BONUS_MELEE_R, BONUS_MELEE_CONE, BONUS_MELEE_GAP_S, BONUS_BLOCK_R = 150.0, math.radians(30), 0.45, 300.0
BONUS_WALK_S, BONUS_HIT_S = 25.0, 4.0
# Shooting them (operator 18:31, a frame of Ada by a green capsule: "these objects are able to be shot. These green ones
# turn on combo time. The yellow ones are for time bonuses ... You can melee them or you can shoot them from afar"):
# with the aim lock the bonus run's yellow (time) bonus is locked onto (its centre BONUS_H up) from up to BONUS_SHOOT_R
# and shot while the laser's ray runs through it (not ending short of it); one the ray never reaches within BONUS_SEE_S
# is out of sight for BONUS_UNSEEN_S - walked to by the nav mesh, broken by the attack at arm's length. The yellows are
# phase 1's; a green (combo) bonus is kept for the match: shot (or kicked) when the combo window runs under
# COMBO_LOW_S with one in sight, nobody within BONUS_BLOCK_R (stats combo_saves). stats yellows_taken, greens_taken,
# bonus_shots, bonus_melee, bonus_unseen.
BONUS_SHOOT_R, BONUS_SEE_S, BONUS_UNSEEN_S = 2500.0, 1.5, 8.0
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
          "walk", "no_foes", "dead", "bomb", "crowd", "nade", "bonus", "prompt")
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

    def __init__(self, stats: dict | None = None, clock=time.monotonic, learn_dir=None, ram=None):
        from ..bot_look import BotLook
        self.stats = stats if stats is not None else {}
        self.clock = clock
        for k in ("shots", "hits", "quick_shots", "melee", "turns", "quick_turns", "wiggles", "holds", "reloads",
                  "reraise", "restale", "deaths", "tablets", "tablet_presses", "tablet_misses", "backoffs",
                  "pulls_hit", "pulls_miss", "first_pull_n", "bombs_placed", "bombs_detonated", "bomb_kills",
                  "bomb_misses", "holds_freed_no_press", "holds_shaken", "cc_quick_shots", "cc_kicks",
                  "los_blocks", "nohit_blocks", "cc_blocks", "camera_far_holds", "detours", "bomb_walks",
                  "bomb_self_hits", "bomb_aborts", "bomb_escapes", "bomb_det_holds", "bomb_kicks",
                  "bomb_hits_taken", "flashes", "frags", "fires", "nade_aborts", "nade_back_fails", "fever_kicks",
                  "grenade_kills", "combo_breaks", "combo_best", "combo_pushes", "unsafe_trigger_blocks", "dyings",
                  "tablet_dying_presses", "tablet_dying_taken", "cc_backouts",
                  "bonuses_taken", "time_bonuses_taken", "combo_bonuses_taken", "bonuses_missed", "bonus_skips",
                  "bonus_shots", "bomb_drops", "surround_events", "max_within_4m", "confirmed_shots",
                  "moving_shots", "long_shot_kills", "quick_attacks", "quick_attack_kills", "fever_quick_shots",
                  "pursuits", "pursuit_kills", "pursuit_lapses", "pursuit_stuck", "census_alive", "census_floor",
                  "taunts", "taunts_seen", "taunt_multi", "taunt_blast", "taunt_boss", "bonus_melee",
                  "yellows_taken", "greens_taken", "combo_saves", "bonus_unseen",
                  "aim_locks", "lock_write_ok", "lock_write_fail", "lock_overwritten", "lock_fallbacks", "aimed_shots",
                  "aimed_hits", "boss_damage", "down_shots", "down_kills", "down_recoveries", "dying_deaths",
                  "hazard_marks", "sweeps", "targets_shot"):
            self.stats.setdefault(k, 0)
        for k in ("trigger_s", "first_pull_s", "bomb_face_s", "kite_s", "bonus_time_s", "down_s", "hazard_s",
                  "cc_vs_aimed"):
            self.stats.setdefault(k, 0.0)
        self.run_target, self.run_since, self.run_hit_since = None, -1e9, None   # the bonus run's bonus; since when
        self.stats.setdefault("offscreen_skips", 0)
        self.stats.setdefault("wall_aim_s", 0.0)
        for k in ("windup_seen", "windup_interrupts", "hits_after_windup", "grenade_throws", "spam_bursts",
                  "flash_qtes", "bomb_choices", "nade_choices"):
            self.stats.setdefault(k, 0)
        for k in ("idle_s", "backtrack_m"):
            self.stats.setdefault(k, 0.0)
        self.windups: dict = {}                              # enemy -> when its wind-up began
        self._wu_hp, self._run_d = None, None                # his health last tick; the bonus run's distance last tick
        for k in ("offlevel_skips", "whips"):
            self.stats.setdefault(k, 0)
        for k in ("up_aim_s", "survival_s", "spin_deg_s"):
            self.stats.setdefault(k, 0.0)
        self.survival, self.close_threat = False, False
        self._rot_prev = None                                # (when, his body heading) for the turn governor
        self._sight_cache: dict = {}
        self.lock_at = -1e9                                  # when the lock took its current target
        for k in ("weapon_switches", "weapon_swaps", "grab_det_presses", "grab_detonations"):
            self.stats.setdefault(k, 0)
        self.grab_weapon, self.grab_weapon_at = None, -1e9   # a grab's pick (wheel index) and when
        self.weapon_tap_at, self.weapon_taps, self.weapon_rest = -1e9, 0, -1e9
        self.hold_bomb_out = False                           # a bomb was out when this hold began
        self.bonus_unseen: dict = {}                         # bonus -> until when it counts as out of sight
        self.bshot = None                                    # the bonus being shot: (ptr, since)
        for k in ("prompts_seen", "prompts_taken", "climbs", "pickups"):
            self.stats.setdefault(k, 0)
        self.prompt_live: dict = {}                          # shown prompts: {(ab, type): {since, pressed, at}}
        self.prompt_spots_path = Path(learn_dir) / PROMPT_SPOTS_FILE if learn_dir else None
        self.prompt_spots: dict = {}
        self.prompt_saved = -1e9
        if self.prompt_spots_path is not None and self.prompt_spots_path.exists():
            try:
                self.prompt_spots = dict(json.loads(self.prompt_spots_path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                self.prompt_spots = {}
        for k in ("nav_paths", "nav_fails"):
            self.stats.setdefault(k, 0)
        self.nav_path, self.nav_goal, self.nav_at = None, None, -1e9   # the walk's waypoints; toward what; planned when
        self.ram = ram                                       # the aim lock's writer (aim_writer); None: the keys aim
        self.lock_tid, self.lock_w, self.lock_fails, self.lock_off_until = None, None, [], -1e9
        self.pitch_bias, self.lock_view = 0.0, None          # the pitch's learned correction; the last view (yaw, pitch)
        self.lock_shots: list = []                           # aimed shots waiting for their target's health to fall
        self.down, self.down_dying, self.down_kills_k = False, False, None   # down now; a dying one; kills when it began
        self.since_dying = False                             # rose from dying and never above 1 health since
        self.hazards: list = []                              # [(x, z, until)]
        self.hazard = None                                   # the mark he stands in (x, z), or None
        self._hz_hp, self._big_hp = None, {}
        self.sweep_n: dict = {}                              # aimed shots at each target this sweep
        self.sweep_seen: set = set()                         # the targets shot at (targets_per_min)
        self.sweep_t0, self._edist = None, {}                # the first aimed shot; each one's last distance (closing)
        self.target, self.target_at = None, -1e9
        self.aim_since = None
        self.reraised = False                     # this raise already looked for the laser unit again
        self.fire_down = False
        self.yaw_pulse = self.pitch_pulse = self.turn_pulse = 0
        self.ray_key, self.ray_since = None, 0.0
        self.quick, self.quick_at = 0, -1e9
        self.melee_at = self.qshot_at = self.reload_at = self.tablet_at = -1e9
        self.tablet_wait, self.tablet_missed = None, False   # (the count, when) after an R press, until it falls
        self._zl_at = -1e9                                   # when ZL was last held
        self.tablet_dying, self.dying_since = False, None    # that press made while dying; dying since when
        self.keeping_off = False
        self.qshot_release = False
        self.still, self.move_at, self.break_until, self.in_hold = None, -1e9, -1e9, False
        self.hold_since, self.hold_pressed = None, False     # the RAM hold under way: since when, anything pressed
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
        # remote bombs: the step under way (equip / face / aim / throw / thrown / wait / det_aim / det / det_wait)
        self.bomb_phase, self.bomb_phase_at, self.bomb_steps = None, -1e9, 0
        self.bomb_at = self.bomb_from = None                 # where it went (x, z), his spot then
        self.bomb_since, self.bomb_last, self.bomb_why = None, -1e9, ""
        self.bomb_kills = None                               # (the kill count at a blast, when)
        self.bomb_drop = False                               # this bomb dropped while backing out of a crowd
        self.bomb_walk, self.bomb_side_until = None, -1e9    # walking off it: (since when, from where); a side step
        self.bomb_walk_since = None                          # when this bomb's walk began
        self.bomb_real = False                               # this bomb's spot read from its unit
        self.bomb_face_t, self._tick_hp, self._tick_at = 0.0, None, None   # this bomb's facing; last tick's health
        self.nade, self.nade_last, self.nade_kills = None, -1e9, None   # the throw under way; its kills (count, when)
        self.fever_until = -1e9                              # the melee fever after a flash
        self.flashed, self.fever_k, self.frag_last = set(), None, -1e9   # the flashed ones; kills then; the last grenade
        for k in ("fever_kills", "fever_breaks"):
            self.stats.setdefault(k, 0)
        self.flash_last = -1e9                               # the last flash thrown
        self.combo_prev, self.combo_urgent = 0, False
        self.surrounded = False                              # 8+ within 4 m last tick
        self._p, self._cam_yaw = None, 0.0
        self.long_shot = {}                                  # zombie -> when the trigger was last on him past LONG_KILL_R
        self.qa_in, self.qa_at, self.qa_kills_k = False, None, None   # in a quick attack; when the last began; kills then
        self.pursuit = None                                  # the combo's pursuit under way: {since, kills}
        self.kill_times: list = []                           # when each recent kill came (the kill count's rises)
        self.taunt_due, self.taunt_at, self.taunt_hold_until = None, -1e9, -1e9   # the trigger waiting; the last click
        self._kills_prev, self._bosses = None, {}             # the kill count; the big ones alive {id: max health}
        self._blast_kills_seen = (0, 0)                      # bomb_kills, grenade_kills already looked at
        self._taunt_seen = False
        self.pursue_spot, self.pursue_side_until = None, -1e9   # (since when, where) for the stuck check; a side step                       # this tick's player and camera yaw (crowd control's way out)
        self.hp_hist: list = []                              # (when, his health, doing) for the last HP_HIST_S
        self.book = BlastBook(learn_dir)                     # the blast's learned reach (this title)
        self.stage_dir = Path(learn_dir) / "stages" if learn_dir else None   # what each stage taught (stage_book)
        self.stage_seen = None                               # the stage this round's book was written for
        self.blast = None                                    # the blast under way: its toll, read for BOMB_LEARN_S
        self._prev_z, self._prev_hp = {}, None               # the last tick's zombies {id: (health, pos)}, his health
                                                             # (a blast seen this tick is read against them)
        # line of sight
        self.blocked: dict = {}                              # zombie -> until when he is out of sight (never fired at)
        self.seen: dict = {}                                 # zombie -> when his health last fell to a shot
        self.laser_seen: dict = {}                           # zombie -> when the laser's ray last reached him
        self.fire_track = None                               # [zombie, since, his health then, last on the line]
        self.ray_yaw = None                                  # the camera's yaw when the laser's ray last moved
        self.cc_shot = None                                  # (zombie, when, {zombie: health} within CC_R)
        self.cc_miss: dict = {}
        self.detour, self.detour_at = "lleft", -1e9
        self._ppos, self._pos_of = None, {}                  # his position this tick, the zombies' by id
        # time bonuses: the one being shot (since when), those left for a while, this round's book
        self.bonus_target, self.bonus_since, self.bonus_skip = None, -1e9, {}
        self.bonus_prev: dict = {}                           # ptr -> kind, waiting at the last tick
        self.bonus_round = None                              # {"seen": {ptr: kind}, "taken": {ptr: kind}}

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
                tuning.apply(MAP_ID, tuning.stage_name(STAGES, PICK.last.get("stage")), self.stats)
                self.target, self.hp_prev, self.hp_seen = None, {}, []
                self.tablet_wait, self.tablet_missed = None, False
                self.look.new_round()
            self.continued = None
        if self._round_started is None:
            self._round_started = now
            tuning.apply(MAP_ID, tuning.stage_name(STAGES, PICK.last.get("stage")), self.stats)
        self._stage_book(snap)

    def _stage_book(self, snap) -> None:
        """Each stage's lessons (operator 18:03: "learning and studying and cycling through all of the levels"): once a
        round, at its first tick with the stage's nav mesh and bonuses, learn_dir / stages / <stage>.json - the nav mesh
        (name, size), the bonuses' spots, visits, the best kills of the rounds before; the next visit starts from them."""
        k = snap.get("kills")
        if isinstance(k, int):
            self.stage_best = max(getattr(self, "stage_best", 0), k)
        mesh = snap.get("navmesh")
        name = getattr(mesh, "name", "") if mesh is not None else ""
        if self.stage_dir is None or not name or not snap.get("bonuses"):
            return
        stage = name.replace("\\", "/").rsplit("/", 1)[-1]
        key = (stage, self._round_started)
        if self.stage_seen == key:
            return
        prev, self.stage_seen = self.stage_seen, key
        if prev is not None and getattr(self, "stage_best", 0):
            self._stage_write(prev[0], lambda b: b.update(best_kills=max(int(b.get("best_kills") or 0),
                                                                         self.stage_best)))
        self.stage_best = 0

        def visit(book):
            book["visits"] = int(book.get("visits") or 0) + 1
            book["nav"] = {"name": name, "vertices": len(mesh.V), "triangles": len(mesh.T)}
            spots = {tuple(b[:3]) for b in book.get("bonuses") or ()}
            spots |= {(round(b["pos"][0]), round(b["pos"][1]), round(b["pos"][2])) for b in snap["bonuses"]}
            book["bonuses"] = [list(b) for b in sorted(spots)][:32]
        self._stage_write(stage, visit)

    def _stage_write(self, stage: str, change) -> None:
        path = self.stage_dir / f"{stage}.json"
        try:
            book = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            book = {}
        change(book)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(book, sort_keys=True), encoding="utf-8")
        except OSError:
            pass

    # --- what to fight -----------------------------------------------------------------------------------------------
    @staticmethod
    def _cost(p, yaw, e) -> float:
        px, _, pz = p["pos"]
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        return d * (1.0 + abs(wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - yaw)) / math.pi)

    def _choose(self, p, yaw, live, now):
        wound = [e for e in live if windup(e, p["pos"])]
        if wound:                                                # about to attack him: stopped first
            best = min(wound, key=lambda e: math.dist(p["pos"], e["pos"]))
            if self.target != best.get("ptr", best.get("slot")):
                self.target_at = now
            self.target = best.get("ptr", best.get("slot"))
            return best
        big = [e for e in live if (e.get("hp_max") or 0) >= BIG_HP and math.dist(p["pos"], e["pos"]) <= AIM_LOCK_R]
        locking = self._lock_ready(getattr(self, "_snap", {}) or {}, now)
        if big and locking:                                      # priority focus fire on the big ones
            best = min(big, key=lambda e: math.dist(p["pos"], e["pos"]))
            if self.target != best.get("ptr", best.get("slot")):
                self.target_at = now
            self.target = best.get("ptr", best.get("slot"))
            return best
        if locking:                                              # the sweep: target after target
            return self._sweep(p, live, now)
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
            if self.tablet_dying:
                self.stats["tablet_dying_taken"] += 1
            self.tablet_wait, self.tablet_missed, self.tablet_dying = None, False, False
        elif now - at >= TABLET_CONFIRM_S:
            self.stats["tablet_misses"] += 1
            self.tablet_wait, self.tablet_missed, self.tablet_dying = None, True, False

    def _dying(self, p, now) -> dict | None:
        """At 1 health (RE6's dying crawl): R for a tablet every DYING_GAP_S while the case holds one. None: no press
        this tick (the rest of the decision goes on)."""
        if self.dying_since is None:
            self.dying_since = now
            self.stats["dyings"] += 1
        st = p.get("state")
        seen = self.stats.setdefault("dying_states", [])
        if st is not None and st not in seen and len(seen) < 8:
            seen.append(st)
        if (p.get("tablets") or 0) <= 0 or self.tablet_wait is not None or now - self.tablet_at < DYING_GAP_S:
            return None
        self._gun_down()
        self.tablet_at, self.tablet_wait, self.tablet_dying = now, (p.get("tablets"), now), True
        self.stats["tablet_presses"] += 1
        self.stats["tablet_dying_presses"] += 1
        return self._go("tablet", "tablet_dying", {"tap": "r"}, "dying at 1 health: a tablet")

    def _score_hits(self, snap, now) -> None:
        """A zombie's health falling within HIT_S of a shot is that shot's hit (accuracy = hits / shots)."""
        hp = {e.get("ptr", e.get("slot")): e.get("hp") or 0 for e in snap.get("enemies") or ()}
        for k, at in list(self.long_shot.items()):               # a long shot's kill: he dies soon after the trigger
            if hp.get(k, 0) <= 0 and self.hp_prev.get(k, 0) > 0 or (k not in hp and k in self.hp_prev):
                if now - at <= LONG_KILL_S:
                    self.stats["long_shot_kills"] += 1
                del self.long_shot[k]
            elif now - at > LONG_KILL_S:
                del self.long_shot[k]
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
        out = self._govern(snap, out, now)
        if "zl" in (out.get("hold") or ()):
            self._zl_at = now
        hold = set(out.get("hold") or ())
        eq = (snap.get("player") or {}).get("equipped")
        if ({"zl", "zr"} <= hold and isinstance(eq, int) and eq >= WEAPON_INDEXES
                and self.stats.get("act") not in THROW_ACTS):     # an item in hand: ZL + ZR would throw it or set it off
            self.stats["unsafe_trigger_blocks"] += 1
            self.qshot_release, self.fire_down = False, False
            out = self._go("nade", "gun_back", {"tap": "dright"}, f"an item in hand (wheel {eq}): the gun back first")
        try:
            self._look_tick(snap, now)
        except Exception as exc:                             # noqa: BLE001 - the look never costs the round a tick
            self.stats["look_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return out

    def _govern(self, snap, out, now) -> dict:
        """The turn governor: his heading turning faster than SPIN_DEG_S, or a sped-up action running, releases the
        sticks this tick (held: exempt); up_aim_s: the camera aimed up past UP_AIM with no vertical threat targeted."""
        p = snap.get("player") or {}
        cam = snap.get("camera")
        bonus_aim = str(self.stats.get("act") or "").startswith("bonus") or isinstance(self.lock_tid, tuple)
        if cam and cam.get("pitch", 0.0) > UP_AIM and "zl" in (out.get("hold") or ()) and not bonus_aim:
            tgt = next((e for e in snap.get("enemies") or () if e.get("ptr", e.get("slot")) == self.target), None)
            up_to = None
            if tgt is not None and p.get("pos"):                 # the target's own elevation from the camera
                pt, c = aim_point(tgt, p["pos"]), cam["pos"]
                up_to = math.atan2(pt[1] - c[1], max(math.hypot(pt[0] - c[0], pt[2] - c[2]), 1.0))
            if tgt is None or not (self._vertical_threat(p, tgt) or (up_to is not None and up_to >= UP_AIM - 0.1)):
                self.stats["up_aim_s"] = round(self.stats["up_aim_s"] + TICK_S, 2)
        rot = p.get("rot")
        spin = 0.0
        if isinstance(rot, (int, float)) and self._rot_prev is not None and now > self._rot_prev[0]:
            spin = math.degrees(abs(wrap(rot - self._rot_prev[1]))) / (now - self._rot_prev[0])
            self.stats["spin_deg_s"] = round(max(self.stats["spin_deg_s"], spin), 1)
        self._rot_prev = (now, rot) if isinstance(rot, (int, float)) else None
        hold = out.get("hold")
        if (snap.get("mercenaries_phase") == PHASE_PLAYING and (p.get("hp") or 0) > 0 and not hold and "tap" not in out
                and any((e.get("hp") or 0) > 0 for e in snap.get("enemies") or ())):
            self.stats["idle_s"] = round(self.stats["idle_s"] + TICK_S, 2)   # nothing pressed with zombies about
        bs = {b["ptr"]: b for b in snap.get("bonuses") or ()}
        tb = bs.get(self.run_target) if self.stats.get("phase") == "bonus_run" else None
        if tb is not None and p.get("pos"):
            d = math.dist(p["pos"], tb["pos"])
            if self._run_d is not None and self._run_d[0] == self.run_target and d > self._run_d[1] + 5.0:
                self.stats["backtrack_m"] = round(self.stats["backtrack_m"] + (d - self._run_d[1]) / 100.0, 2)
            self._run_d = (self.run_target, d)
        if not hold or self.in_hold or self.stats.get("act") in ("break_free", "held_auto_qte", "grab_detonate",
                                                                "quick_turn", "quick_turn_settle"):
            return out                                           # (a grab's escape and the quick turn: exempt)
        boosted = p.get("action") in BOOSTED_ACTIONS or (p.get("action") == "cPlAction_pl_act_weapon_fire"
                                                          and p.get("weapon_id") in MAGNUM_IDS)
        if (spin > SPIN_DEG_S or boosted) and set(hold) & STICK_KEYS:
            self.stats["whips" if spin > SPIN_DEG_S else "boost_releases"] =                 self.stats.get("whips" if spin > SPIN_DEG_S else "boost_releases", 0) + 1
            out = dict(out, hold=tuple(k for k in hold if k not in STICK_KEYS))
        return out

    def _tick(self, snap: dict, now: float) -> dict:
        p = snap.get("player")
        self._snap = snap
        if snap.get("mercenaries_phase") != PHASE_PLAYING:
            self._bonus_close()
        if not p:
            self._gun_down()
            return self._go("none", "no_player", {"hold": ()}, "no player (between rounds)")
        if (p.get("hp") or 0) <= 0:
            self._gun_down()
            self.died = True
            if self.dead_since is None:
                self.dead_since = now
                self.stats["deaths"] += 1
                if self.down_dying or self.since_dying:
                    self.stats["dying_deaths"] += 1
                self.down = self.down_dying = self.since_dying = False
                self._death(p, snap, now)
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
        hp_now = p.get("hp")
        if self.doing == "bomb" and isinstance(hp_now, int) and isinstance(self._tick_hp, int) and hp_now < self._tick_hp:
            self.stats["bomb_hits_taken"] += self._tick_hp - hp_now
        if self.stats.get("act") == "bomb_face" and self._tick_at is not None:
            self.stats["bomb_face_s"] = round(self.stats["bomb_face_s"] + min(now - self._tick_at, LOOK_STEP_MAX_S), 2)
        self._tick_hp, self._tick_at = hp_now if isinstance(hp_now, int) else self._tick_hp, now
        self.hp_hist = [h for h in self.hp_hist if now - h[0] <= HP_HIST_S] + [(now, p.get("hp"), self.doing)]
        self._round_start(snap, now)
        self._score_hits(snap, now)
        self._ppos = p["pos"]
        self._mesh = snap.get("navmesh")
        lz = snap.get("laser")
        alive = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0]
        if lz is not None and lz.get("up") and math.dist(lz["from"], lz["at"]) < WALL_AIM_R and alive and not any(
                math.hypot(e["pos"][0] - lz["at"][0], e["pos"][2] - lz["at"][2]) <= WALL_AIM_R for e in alive):
            self.stats["wall_aim_s"] = round(self.stats["wall_aim_s"] + TICK_S, 2)   # the aim on a wall (not on one)
        self._pos_of = {e.get("ptr", e.get("slot")): e["pos"] for e in snap.get("enemies") or ()}
        self._los_tick(snap, now)
        self._tablet_check(p, now)
        self._bomb_kills_tick(snap, now)
        self._bomb_track(p, snap, now)
        self._blast_tick(p, snap, now)
        self._bonus_book(snap)
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
        self._combo_tick(snap, live, flat, now)
        self._quick_tick(p, snap, now)
        self._census_tick(p, snap, live)
        self._taunt_watch(snap, now)
        self._windup_tick(p, snap, now)
        self._down_tick(p, snap, now)
        self._hazard_tick(p, live, flat, now)
        self._prompt_shown = self._prompt_book(p, snap, now)
        self._lock_tick(snap, now)
        within = sum(1 for e in live if flat(e) <= CC_BACK_R)
        self.stats["max_within_4m"] = max(self.stats["max_within_4m"], within)
        if within >= SURROUND_N and not self.surrounded:
            self.stats["surround_events"] += 1
        self.surrounded = within >= SURROUND_N
        state = p.get("state")                               # None: no state byte (the health / stick heuristics)
        held = state in HELD_STATES
        if self.in_hold and not held:                        # a hold read in RAM just ended: how it was freed
            self._hold_ended(now, snap)
        if p.get("hp") != DYING_HP:
            self.dying_since = None
        elif not DYING_TABLETS:
            if self.dying_since is None:                     # counted only (no tablet while dying)
                self.dying_since = now
                self.stats["dyings"] += 1
                st = p.get("state")
                seen = self.stats.setdefault("dying_states", [])
                if st is not None and st not in seen and len(seen) < 8:
                    seen.append(st)
        elif not held and self.nade is None:                 # dying: a tablet before anything else
            dying = self._dying(p, now)
            if dying is not None:
                return dying
        if held or now < self.break_until or (state is None and self.grabbed(p, near, now)) or self.held(p, now):
            if held:                                         # RAM says a zombie holds him: shake him off
                if not self.in_hold:
                    self.stats["holds"] += 1
                    self.hold_since, self.hold_pressed = now, False
                    self._grab_swap(p, now)
                    self.hold_bomb_out = bool((p.get("bomb") or {}).get("out"))
                self.in_hold = True
                if snap.get("auto_qte") and now - self.hold_since < AUTO_QTE_WAIT_S:
                    self._gun_down()                         # the game's auto QTE: nothing pressed for a while
                    self.still = None
                    return self._go("held", "held_auto_qte", {"hold": ()},
                                    f"held (action {state}): the game's auto QTE, nothing pressed")
                self.hold_pressed = True
            elif now >= self.break_until:
                self.stats["holds" if self.still and now - self.still[0] > STUCK_S else "wiggles"] += 1
                self.break_until = now + BREAK_S
            self._gun_down()
            self.still = None
            self.wiggle += 1
            if "b" in WIGGLE[self.wiggle % len(WIGGLE)]:
                self._prompt_pressed("b", now)
            if held and self._grab_detonate(p, snap):            # the bomb set off from the mash
                return self._go("held", "grab_detonate", {"hold": WIGGLE[self.wiggle % len(WIGGLE)] + ("zr",)},
                                f"held (action {state}), the bomb out and him clear of it: set off (ZR)")
            return self._go("held", "break_free", {"hold": WIGGLE[self.wiggle % len(WIGGLE)]},
                            f"held (action {state}): B mashed, the stick round")
        self.in_hold = False
        took = self._prompt(p, snap, now)                        # the game's own prompt: pressed at once
        if took is not None:
            return took
        switched = self._weapon_switch(p, now)                   # the weapon asked for (the app, a grab's pick)
        if switched is not None:
            return switched
        escape = self._bomb_escape(p, snap, now)
        if escape is not None:
            return escape
        act = self._decide(p, live, flat, near_e, near, snap, now)
        if set(act.get("hold", ())) & {"lup", "ldown", "lleft", "lright"}:
            self.move_at = now
        return act

    def _grab_swap(self, p, now) -> None:
        """A grab: a random loaded shotgun or magnum other than the gun in hand, switched to once he is free."""
        if not GRAB_SWAP:
            return
        guns = p.get("guns") or {}
        eq = p.get("equipped")
        picks = [i for t, i in guns.items() if t in SHOTGUN_MAGNUM_TYPES and i != eq]
        if picks:
            self.grab_weapon, self.grab_weapon_at = random.choice(picks), now
            self.stats["weapon_swaps"] += 1

    def _grab_detonate(self, p, snap) -> bool:
        """Held with the bomb out and the remote in hand, him outside the learned reach + margin: ZR in the mash."""
        bomb = p.get("bomb") or {}
        if not (GRAB_DETONATE and bomb.get("out") and p.get("equipped") == BOMB_INDEX):
            return False
        at = snap.get("bomb_pos")
        if at is None:
            return False
        if math.hypot(at[0] - p["pos"][0], at[2] - p["pos"][2]) < self.book.safe:
            return False
        self.stats["grab_det_presses"] += 1
        return True

    def _weapon_switch(self, p, now) -> dict | None:
        """The wanted weapon into his hands - the app's (WANT_WEAPON), else a shotgun for a crowd on him, else a grab's
        pick: the D-pad's right until the equipped index is it. None: in hand already, not loaded, or resting."""
        want = WANT_WEAPON if WANT_WEAPON is not None and WANT_WEAPON_AT >= self.grab_weapon_at else None
        held = p.get("guns") or {}
        if want is None:
            px, py, pz = p["pos"]
            crowd = sum(1 for e in (self._snap or {}).get("enemies") or () if (e.get("hp") or 0) > 0
                        and abs(e["pos"][1] - py) <= MAX_DY and math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= CROWD_GUN_R)
            gun = next((held[t] for t in SHOTGUN_ORDER if t in held), None)
            if crowd >= CROWD_GUN_N and gun is not None:     # a crowd on him: the shotgun clears the circle
                want = gun
                self.stats["crowd_shotgun_s"] = round(self.stats.get("crowd_shotgun_s", 0.0) + TICK_S, 2)
            else:
                want = self.grab_weapon
        guns = held.values()
        eq = p.get("equipped")
        if want is None or want not in guns or eq == want:
            self.weapon_taps = 0
            if want is not None and eq == want:
                self.stats["weapon_in_hand"] = want
            return None
        if now < self.weapon_rest or (p.get("bomb") or {}).get("out") or self.nade is not None \
                or self.bomb_phase is not None:
            return None
        if now - self.weapon_tap_at < WEAPON_TAP_S:
            return None
        if self.weapon_taps >= WEAPON_TRIES:
            self.weapon_rest, self.weapon_taps = now + WEAPON_REST_S, 0
            return None
        self.weapon_tap_at = now
        self.weapon_taps += 1
        self.stats["weapon_switches"] += 1
        self._gun_down()
        return self._go("reload", "weapon_switch", {"tap": "dright"}, f"to the weapon at wheel {want} (now {eq})")

    def _hold_ended(self, now, snap) -> None:
        """A RAM hold's end: stats holds_freed_no_press (it ended before he pressed anything: the game's auto QTE) or
        holds_shaken, and hold_log - its length, whether he pressed, whether auto QTE was on - for the last HOLD_LOG_N."""
        self.in_hold = False
        if self.hold_bomb_out and not (((snap.get("player") or {}).get("bomb")) or {}).get("out"):
            self.stats["grab_detonations"] += 1                  # it went off while he was held
        self.hold_bomb_out = False
        pressed = bool(self.hold_pressed)
        self.stats["holds_shaken" if pressed else "holds_freed_no_press"] += 1
        log = self.stats.setdefault("hold_log", [])
        log.append({"s": round(now - (self.hold_since or now), 2), "pressed": pressed,
                    "auto_qte": bool(snap.get("auto_qte"))})
        del log[:-HOLD_LOG_N]

    def _decide(self, p, live, flat, near_e, near, snap, now) -> dict:
        px, py, pz = p["pos"]
        if self.down:
            return self._down_fight(p, snap, now)
        ran = self._bonus_run(p, live, flat, snap, now)          # phase 1: the bonuses first
        if ran is not None:
            return ran
        saved = self._green_save(p, live, flat, snap, now)       # the match: a green bonus for a running-out combo
        if saved is not None:
            return saved
        high = self._off_floor(p, snap, now) if not live else []   # nobody on his floor: one above or below him
        if self.hazard is not None and not live:                 # nobody to fight and in smoke: out of it
            cam = snap.get("camera")
            return self._go("walk", "hazard_out", {"hold": self._stick(self._open_heading(p, live, self.hazard),
                                                                       cam["yaw"] if cam else p["rot"])},
                            "in a hazard: moving out")
        if not live and not high:
            taunt = self._taunt(p, live, flat, now)
            if taunt is not None:
                return taunt
            took = self._bonus(p, live, flat, snap, now)
            if took is not None:
                return took
            self._gun_down()
            chase = self._pursue(p, snap, now)                   # none on his floor: after the stage's best one
            if chase is not None:
                return chase
            return self._go("no_foes", "idle", {"hold": ()}, "no zombie alive within reach")
        cam = snap.get("camera")
        yaw = cam["yaw"] if cam else p["rot"]                    # without the camera: the body's heading stands in
        self._p, self._cam_yaw = p, yaw
        bearing = lambda e: wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - yaw)
        vis = [e for e in live if not self.is_blocked(e, now)]              # out of sight: never the target
        front = [e for e in vis if flat(e) <= ENGAGE_R and abs(bearing(e)) <= FRONT_CONE]
        if not front:                                            # nobody near: one in front far off - a long shot
            front = [e for e in vis if flat(e) <= LONG_R and abs(bearing(e)) <= FRONT_CONE]
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        self.survival = bool(hp_max and hp <= SURVIVAL_HP * hp_max)
        if self.survival:
            self.stats["survival_s"] = round(self.stats["survival_s"] + TICK_S, 2)
        level = [e for e in vis if abs(e["pos"][1] - py) <= AIM_DY]
        close = [e for e in level if flat(e) <= CLOSE_R]
        self.close_threat = bool(close)
        if close or self.survival:                               # the near ones beat everything; low health: only them
            if self._lock_ready(snap, now):
                front = [e for e in (close or level) if flat(e) <= (CLOSE_R if self.survival else ENGAGE_R)] or front
            self._aimable = close or [e for e in level if flat(e) <= CLOSE_R]
        else:
            self._aimable = level + [e for e in vis if abs(e["pos"][1] - py) > AIM_DY and self._vertical_threat(p, e)] \
                + self._off_floor(p, snap, now)
        if self._lock_ready(snap, now) and self._aimable:        # the lock turns the camera: any bearing
            near_all = [e for e in self._aimable if math.dist(p["pos"], e["pos"]) <= AIM_LOCK_R or flat(e) <= ENGAGE_R]
            if near_all:
                front = near_all
        tgt = self._choose(p, yaw, front or vis or live, now)
        foot, dist, err = tgt["pos"], flat(tgt), bearing(tgt)
        self.stats["target_dist"] = round(dist)
        crowd = sum(1 for e in live if flat(e) < CROWD_R)
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        gap = TABLET_RETRY_S if self.tablet_missed else TABLET_GAP_S
        if (hp_max and (hp > 1 or (hp == DYING_HP and not self.down)) and (p.get("tablets") or 0) > 0
                and p.get("state") in (0, None)
                and self.tablet_wait is None and now - self.tablet_at >= gap
                and (hp <= TABLET_LOW_HP * hp_max or (hp <= TABLET_HP * hp_max and near > TABLET_CLEAR_R)
                     or (hp <= CROWD_TABLET_HP * hp_max
                         and sum(1 for e in live if flat(e) <= CROWD_TABLET_R) >= CROWD_TABLET_N))):
            self._gun_down()                                     # 60 % health or less, free: a tablet (R),
            if now - self._zl_at < TABLET_LOWER_S:               # the gun down a moment first (live 14:41: 24 of 25
                return self._go("tablet", "tablet_lower", {"hold": ()}, "the gun down for a tablet")   # R right after ZL ignored)
            self.tablet_at = now                                 # the gun down for it (the tap lets ZL go first)
            self.tablet_wait = (p.get("tablets"), now)
            self.stats["tablet_presses"] += 1
            return self._go("tablet", "tablet", {"tap": "r"}, f"health {hp}/{hp_max}: a tablet")
        taunt = self._taunt(p, live, flat, now)
        if taunt is not None:
            return taunt
        bombed = self._bomb(p, live, flat, yaw, snap, now)
        if bombed is not None:
            return bombed
        thrown = self._nade(p, vis, live, flat, yaw, snap, now)
        if thrown is not None:
            return thrown
        if self.combo_urgent and vis:                        # the combo running out: the nearest open one
            tgt = min(vis, key=flat)
            self.target, self.target_at = tgt.get("ptr", tgt.get("slot")), now
            foot, dist, err = tgt["pos"], flat(tgt), bearing(tgt)
        crowded = self._crowd_control(vis, flat, bearing, now)
        if crowded is not None:
            return crowded
        took = self._bonus(p, live, flat, snap, now)
        if took is not None:
            return took
        if not self._aimable:                                    # every one in reach out of sight: a way round
            self._gun_down()
            want = self._nav_heading(p, tgt["pos"], snap, now)
            if want is not None:                                 # by the nav mesh's way to him
                return self._go("walk", "walk_nav", {"hold": self._walk_keys(p, want, snap)},
                                f"the nearest at {dist:.0f} cm is out of sight: walking the nav mesh to him")
            if now - self.detour_at >= DETOUR_S:
                self.detour_at, self.detour = now, "lright" if self.detour == "lleft" else "lleft"
                self.stats["detours"] += 1
            return self._go("walk", "walk_detour", {"hold": ("lup", self.detour) + self._turn(err, TURN_TOL)},
                            f"the nearest at {dist:.0f} cm is out of sight: walking round ({self.detour})")
        if self.aim_since is None:
            near_err = bearing(near_e) if near_e is not None else math.pi
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
            lone = not self._lock_ready(snap, now) or sum(1 for e in live if flat(e) <= CC_CROWD_R) < 2
            if lone and dist < QSHOT_R and abs(err) <= QSHOT_CONE and now - self.qshot_at >= QSHOT_GAP_S:
                self.qshot_at = now                              # close in front: the game's own quick shot
                self.stats["quick_shots"] += 1
                self.qshot_release = True
                return self._go("quick_shot", "quick_shot", {"hold": ("zl", "zr")}, f"one at {dist:.0f} cm: quick shot")
            self.aim_since, self._raise_t, self.reraised = now, now, False   # a zombie in front: the gun comes up
        keep_off = (crowd >= CROWD_N or near < KEEP_R             # he steps back while he fires
                    or sum(1 for e in live if flat(e) < CC_BACK_R) >= CC_BACK_N)
        if keep_off and not self.keeping_off:
            self.stats["backoffs"] += 1
        self.keeping_off = keep_off
        back = ("ldown",) if keep_off else ()
        if sum(1 for e in live if flat(e) < KITE_R) >= KITE_N:  # 3+ closing: toward open space as he fires
            back = self._stick(self._open_heading(p, live), yaw)
            self.stats["kite_s"] = round(self.stats["kite_s"] + TICK_S, 2)
        if self.hazard is not None:                              # in smoke: out of it as he fires
            back = self._stick(self._open_heading(p, live, self.hazard), yaw)
        elif self.survival and near_e is not None:              # low health: away from the nearest as he fires
            back = self._stick(self._open_heading(p, live, (near_e["pos"][0], near_e["pos"][2])), yaw)
        self._locked = (self._lock(p, tgt, snap, now), tgt.get("ptr", tgt.get("slot")))   # the lock from the raise on
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
                self.ray_key, self.ray_since, self.ray_yaw = ray, now, cam["yaw"] if cam else None
                origin, dot = ray
            elif (now - self.ray_since > RAY_STALE_S              # frozen while the camera turned: another unit's
                  and (cam is None or self.ray_yaw is None or abs(wrap(cam["yaw"] - self.ray_yaw)) > RAY_STALE_TURN)):
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
        cands = self._aimable if source == "laser" else (front or self._aimable)
        on_e = self._on_line(origin, dot, source, cands, now)
        if source == "laser" and on_e is None and (self._ray_short(origin, dot, tgt) or self._probe_short(origin, dot, tgt, now)):
            self._block(tgt, now, "los_blocks")                  # the ray ends on something in front of him: a wall
        if on_e is not None and on_e is not tgt:                 # the line is on another one: he is the target now
            tgt, foot = on_e, on_e["pos"]
            self.target, self.target_at = tgt.get("ptr", tgt.get("slot")), now
            dist = flat(tgt)
        return self._aim(p, tgt, foot, dist, origin, dot, source, on_e, front, back, now)

    def _on_line(self, origin, dot, source, cands, now=None):
        """The zombie the aim's line runs into first: the laser's dot on him or its ray through him, or the camera's line
        through him within CAM_FIRE_R (further only on one hit within SEEN_S: the camera's line runs through walls).
        None: nobody on the line."""
        now = self.clock() if now is None else now
        best, best_d = None, math.inf
        for e in cands:
            foot = e["pos"]
            if self.is_blocked(e, now):
                continue
            ppos = self._ppos or origin
            if abs(foot[1] - ppos[1]) > MAX_DY:                  # off his floor: near its aim point
                hit = near_line(origin, dot, aim_point(e, ppos), OFF_FLOOR_HIT_R, AIM_LOCK_R + 600.0)
                if hit and source == "laser":
                    self.laser_seen[e.get("ptr", e.get("slot"))] = now
            elif source == "laser":
                hit = dot_on(dot, foot) is not None or through(origin, dot, foot)
                if hit:                                          # the laser reaches him: in sight (LASER_SEEN_S)
                    self.laser_seen[e.get("ptr", e.get("slot"))] = now
            else:
                hit = line_hits(origin, dot, foot, ENGAGE_R + 300.0)
                tid = e.get("ptr", e.get("slot"))
                me = self._ppos or origin                        # from him (the camera rides ~2.5 m behind)
                far = math.hypot(foot[0] - me[0], foot[2] - me[2]) > CAM_FIRE_R
                if hit and far and now - self.seen.get(tid, -1e9) > SEEN_S \
                        and now - self.laser_seen.get(tid, -1e9) > LASER_SEEN_S:
                    self.stats["camera_far_holds"] += 1          # far along the camera's line, never hit: not fired at
                    hit = False
            if hit:
                d = math.dist(origin, foot)
                if d < best_d:
                    best, best_d = e, d
        return best

    def _aim(self, p, tgt, foot, dist, origin, dot, source, on_e, front, back, now) -> dict:
        chest = aim_point(tgt, p["pos"])
        yaw_err, pitch_err = ray_error(origin, dot, chest)
        aim_at = on_e or tgt
        done, done_id = getattr(self, "_locked", (False, None))
        locked = done if done_id == aim_at.get("ptr", aim_at.get("slot")) else self._lock(p, aim_at, self._snap, now)
        if abs(yaw_err) > UNAIM_ERR and on_e is None and not locked:
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
        if trig:
            if source == "laser":
                self.stats["confirmed_shots"] += 1               # the ray itself on him: the hit confirmed
            if set(back) & {"lup", "ldown", "lleft", "lright"}:
                self.stats["moving_shots"] += 1
            if on_e is not None and dist > LONG_KILL_R:
                self.long_shot[on_e.get("ptr", on_e.get("slot"))] = now
        if not on and not back and dist <= AIM_WALK_R and self.aim_since is not None and now - self.aim_since > AIM_WALK_S:
            back = ("lup",)                                      # never standing among them: in at him while aiming
        if on:                                                   # the trigger on him: his health must fall (NOHIT_S)
            tid = on_e.get("ptr", on_e.get("slot"))
            if self.fire_track is None or self.fire_track[0] != tid:
                self.fire_track = [tid, now, on_e.get("hp") or 0, now]
            self.fire_track[3] = now
        if trig and locked:
            self._aimed_shot(on_e or tgt, now)
        steer = set() if locked else self._yaw(yaw_err) | self._pitch(pitch_err)
        keys = {"zl"} | steer | trig | set(back)
        self._aimctx = {"target": (on_e or tgt).get("ptr", (on_e or tgt).get("slot")), "dist": dist,
                        "yaw_err": yaw_err, "source": source, "where": dot_on(dot, foot) if source == "laser" else None,
                        "locked": locked}
        where = self._aimctx["where"]
        self.stats["aim"] = (f"d {dist:.0f} yaw {math.degrees(yaw_err):+.1f} pitch {math.degrees(pitch_err):+.1f} "
                             f"on {where or ('line' if on else '-')} via {source}{' LOCK' if locked else ''} "
                             f"keys {','.join(sorted(keys))}")
        return self._go("fire" if on else "aim", "aim", {"hold": tuple(sorted(keys))},
                        (f"on a zombie at {dist:.0f} cm ({source})" if on else
                         f"steering {math.degrees(yaw_err):+.0f} deg to him ({source})") + (", stepping back" if back else ""))

    def _quick_tick(self, p, snap, now) -> None:
        """Quick attacks from his action (snapshot action): stats quick_attacks (each one begun), quick_attack_interval
        (the mean seconds between two begun within 1 s of each other: the pace the game accepts), quick_attack_kills (the
        kill count rising while one runs)."""
        quick = p.get("action") in QUICK_ACTION_NAMES
        k = snap.get("kills")
        if quick and not self.qa_in:
            self.stats["quick_attacks"] += 1
            if self.qa_at is not None and now - self.qa_at <= 1.0:
                n = self.stats.get("quick_attack_pairs", 0) + 1
                mean = self.stats.get("quick_attack_interval", 0.0)
                self.stats["quick_attack_interval"] = round(mean + (now - self.qa_at - mean) / n, 3)
                self.stats["quick_attack_pairs"] = n
            self.qa_at = now
        if quick and isinstance(k, int) and isinstance(self.qa_kills_k, int) and k > self.qa_kills_k:
            self.stats["quick_attack_kills"] += k - self.qa_kills_k
        self.qa_in, self.qa_kills_k = quick, k

    # --- the RAM aim lock --------------------------------------------------------------------------------------------
    def _lock_ready(self, snap, now) -> bool:
        return bool(AIM_LOCK and self.ram is not None and snap.get("aim_cam") and snap.get("camera")
                    and now >= self.lock_off_until)

    def _off_floor(self, p, snap, now) -> list:
        """The living ones off his floor within AIM_LOCK_R (3D) and in sight: a ceiling's, a hanging one, a boss."""
        if not self._lock_ready(snap, now):
            return []
        py = p["pos"][1]
        out = []
        for e in snap.get("enemies") or ():
            if (e.get("hp") or 0) <= 0 or abs(e["pos"][1] - py) <= MAX_DY or math.dist(p["pos"], e["pos"]) > AIM_LOCK_R:
                continue
            if not self._vertical_threat(p, e):
                self.stats["offlevel_skips"] += 1                # another floor, no threat to him: not aimed at
                continue
            if not self.is_blocked(e, now):
                out.append(e)
        return out

    def _vertical_threat(self, p, e) -> bool:
        """One off his level worth aiming at: above him within CEILING_R, or a big one."""
        dy = e["pos"][1] - p["pos"][1]
        h = math.hypot(e["pos"][0] - p["pos"][0], e["pos"][2] - p["pos"][2])
        return (dy > 0 and h <= CEILING_R) or (e.get("hp_max") or 0) >= BIG_HP

    def _lock_fail(self, now, why: str) -> None:
        self.stats[why] += 1
        self.lock_fails = [t for t in self.lock_fails if now - t <= LOCK_FAIL_S] + [now]
        if len(self.lock_fails) >= LOCK_FAIL_N:                  # it does not stick: the keys for a while
            self.lock_off_until, self.lock_fails = now + LOCK_OFF_S, []
            self.lock_w = None
            self.stats["lock_fallbacks"] += 1

    def _lock(self, p, tgt, snap, now, point=None) -> bool:
        """The player camera's yaw onto the camera's line through tgt's aim point (or point), its pitch from that line's
        slope plus the learned correction; written and read back. True: written this tick (no camera keys)."""
        if tgt is None or not self._lock_ready(snap, now):
            self.lock_w = None
            return False
        ac, cam = snap["aim_cam"], snap["camera"]
        pt, c = (point if point is not None else aim_point(tgt, p["pos"])), cam["pos"]
        want_yaw = heading(pt[0] - c[0], pt[2] - c[2])
        want_pitch = math.atan2(pt[1] - c[1], max(math.hypot(pt[0] - c[0], pt[2] - c[2]), 1.0))
        if (self.close_threat or self.survival) and point is None:
            want_pitch = min(want_pitch, CLOSE_PITCH)            # one close by: never aimed up past this
        tid = tgt.get("ptr", tgt.get("slot"))
        if tid != self.lock_tid:
            self.lock_tid, self.lock_at = tid, now
            self.stats["aim_locks"] += 1
        view, w = (cam["yaw"], cam["pitch"]), self.lock_w
        if w is not None:
            if abs(wrap(ac["yaw"] - w[1])) > 0.05:               # not what was written: the game set it since
                self._lock_fail(now, "lock_overwritten")
                if now < self.lock_off_until:                    # one too many: the keys for a while
                    return False
            settled = abs(wrap(view[0] - ac["yaw"])) <= LOCK_SETTLE and self.lock_view is not None \
                and abs(view[1] - self.lock_view[1]) <= LOCK_STILL
            if settled:                                          # the view at rest: learn the pitch's correction
                err_units = math.degrees(w[2] - view[1]) / PITCH_DEG_PER_UNIT
                self.pitch_bias = max(-LOCK_BIAS_MAX, min(LOCK_BIAS_MAX, self.pitch_bias + LOCK_BIAS_GAIN * err_units))
        self.lock_view = view
        pitch = (math.degrees(want_pitch) - PITCH_DEG_AT_0) / PITCH_DEG_PER_UNIT + self.pitch_bias
        if point is None:                                    # the pitch guard: never far above his own slope
            cap_deg = math.degrees(max(want_pitch, CLOSE_PITCH) + LOCK_UP_SLACK)
            pitch = min(pitch, (cap_deg - PITCH_DEG_AT_0) / PITCH_DEG_PER_UNIT + max(0.0, self.pitch_bias))
        pitch = max(-1.0, min(1.0, pitch))
        if not self.ram(ac["addr"], pitch, want_yaw):
            self._lock_fail(now, "lock_write_fail")
            self.lock_w = None
            return False
        self.stats["lock_write_ok"] += 1
        self.lock_w = (pitch, want_yaw, want_pitch)
        return True

    def _sweep(self, p, live, now):
        """The lock's sweep: the current target until SWEEP_SHOTS aimed shots (or his health is gone), then the nearest
        other one, one closing in first (CLOSING_W of its approach in cm/s off its distance)."""
        me = p["pos"]
        dist = {e.get("ptr", e.get("slot")): math.dist(me, e["pos"]) for e in live}
        closing = {}
        for tid, d in dist.items():
            last = self._edist.get(tid)
            closing[tid] = (last[0] - d) / max(now - last[1], 1e-3) if last and now - last[1] < 1.0 else 0.0
        self._edist = {tid: (d, now) for tid, d in dist.items()}
        cur = next((e for e in live if e.get("ptr", e.get("slot")) == self.target), None)
        if cur is not None and (self.sweep_n.get(self.target, 0) < SWEEP_SHOTS or len(live) == 1):
            return cur
        rest = [e for e in live if e is not cur] or live
        best = min(rest, key=lambda e: dist[e.get("ptr", e.get("slot"))]
                   - CLOSING_W * max(0.0, closing[e.get("ptr", e.get("slot"))]))
        if cur is not None and best is not cur:
            self.stats["sweeps"] += 1
        tid = best.get("ptr", best.get("slot"))
        if tid != self.target:
            self.target_at = now
            self.sweep_n[tid] = 0
        self.target = tid
        return best

    def _aimed_shot(self, tgt, now) -> None:
        tid = tgt.get("ptr", tgt.get("slot"))
        self.sweep_n[tid] = self.sweep_n.get(tid, 0) + 1
        if tid not in self.sweep_seen:
            self.sweep_seen.add(tid)
            self.stats["targets_shot"] += 1
        if self.sweep_t0 is None:
            self.sweep_t0 = now
        if now - self.sweep_t0 >= 10.0:
            self.stats["targets_per_min"] = round(self.stats["targets_shot"] * 60.0 / (now - self.sweep_t0), 1)
        self.stats["aimed_shots"] += 1
        self.lock_shots.append((tgt.get("ptr", tgt.get("slot")), now, tgt.get("hp") or 0))
        self.stats["cc_vs_aimed"] = round(self.stats.get("cc_quick_shots", 0) / max(1, self.stats["aimed_shots"]), 2)

    def _lock_tick(self, snap, now) -> None:
        """aimed_hits: an aimed shot's target's health fell within LOCK_HIT_S; boss_damage: the big ones' health lost
        while locked on."""
        hp = {e.get("ptr", e.get("slot")): e.get("hp") or 0 for e in snap.get("enemies") or ()}
        keep = []
        for tid, t, h in self.lock_shots:
            if tid in hp and hp[tid] < h:
                self.stats["aimed_hits"] += 1
            elif now - t <= LOCK_HIT_S and tid in hp:
                keep.append((tid, t, h))
        self.lock_shots = keep
        big = {e.get("ptr", e.get("slot")): e.get("hp") or 0 for e in snap.get("enemies") or ()
               if (e.get("hp_max") or 0) >= BIG_HP}
        if self.lock_tid in big and self.lock_tid in self._big_hp and big[self.lock_tid] < self._big_hp[self.lock_tid]:
            self.stats["boss_damage"] += self._big_hp[self.lock_tid] - big[self.lock_tid]
        self._big_hp = big

    # --- down ---------------------------------------------------------------------------------------------------------
    def _down_tick(self, p, snap, now) -> None:
        """Down (DOWN_ACTIONS, kept through DOWN_KEEP's) or up; down_s, down_kills, down_recoveries, since_dying."""
        act, hp, k = p.get("action"), p.get("hp"), snap.get("kills")
        was = self.down
        if act in DOWN_ACTIONS:
            self.down = True
        elif act not in DOWN_KEEP:
            self.down = False
        if self.down and not was:
            self.down_dying, self.down_kills_k = hp == DYING_HP, k
            self._gun_down()
        if self.down:
            self.down_dying = self.down_dying or hp == DYING_HP
            self.stats["down_s"] = round(self.stats["down_s"] + TICK_S, 2)
            if isinstance(k, int) and isinstance(self.down_kills_k, int) and k > self.down_kills_k:
                self.stats["down_kills"] += k - self.down_kills_k
            self.down_kills_k = k
        if was and not self.down:
            if act in GETUP_ACTIONS or (hp or 0) > 0:
                self.stats["down_recoveries"] += 1
            self.since_dying = self.down_dying
        if isinstance(hp, int) and hp > DYING_HP:
            self.since_dying = False

    def _down_fight(self, p, snap, now) -> dict:
        """Down: the nearest within DOWN_FIGHT_R locked and fired at (a kick for one within MELEE_R), no tablet, no
        stick; nobody near: the stick up to rise."""
        me = p["pos"]
        near = sorted((e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0
                       and math.dist(me, e["pos"]) <= DOWN_FIGHT_R and not self.is_blocked(e, now)),
                      key=lambda e: math.dist(me, e["pos"]))
        if not near:
            self._gun_down()
            return self._go("down", "down_rise", {"hold": ("lup",)}, "down, nobody near: rising")
        e = near[0]
        d = math.dist(me, e["pos"])
        if d < MELEE_R and now - self.melee_at >= MELEE_GAP_S:
            self.melee_at = now
            self.stats["melee"] += 1
            return self._go("down", "down_kick", {"tap": "zr"}, f"down: a kick at the one at {d:.0f} cm")
        if self.aim_since is None:
            self.aim_since = now
        locked = self._lock(p, e, snap, now)
        origin = dot = None
        source = "laser"
        lz, cam = snap.get("laser"), snap.get("camera")
        if lz is not None and lz.get("up"):
            origin, dot = tuple(lz["from"]), tuple(lz["at"])
        elif cam is not None:
            origin, dot, source = cam["pos"], cam["target"], "camera"
        on_e = self._on_line(origin, dot, source, near, now) if origin is not None else None
        trig = self._trigger(on_e is not None, now, p.get("weapon_id") in AUTO_IDS)
        steer = set()
        if not locked and origin is not None:
            yaw_err, pitch_err = ray_error(origin, dot, aim_point(e, me))
            steer = self._yaw(yaw_err) | self._pitch(pitch_err)
        if trig:
            self.stats["down_shots"] += 1
            if locked:
                self._aimed_shot(on_e, now)
        keys = {"zl"} | trig | steer
        return self._go("down", "down_fire" if on_e is not None else "down_aim", {"hold": tuple(sorted(keys))},
                        f"down: {'firing at' if on_e is not None else 'aiming at'} the one at {d:.0f} cm"
                        + (" (lock)" if locked else ""))

    # --- hazards ------------------------------------------------------------------------------------------------------
    def _hazard_tick(self, p, live, flat, now) -> None:
        """His health falling with nobody within HAZARD_CONTACT_R, not held and not his blast: a hazard marked at his
        spot (HAZARD_R, HAZARD_S); hazard the mark he stands in; hazard_s the time in one."""
        hp, px, pz = p.get("hp"), p["pos"][0], p["pos"][2]
        if (isinstance(hp, int) and isinstance(self._hz_hp, int) and hp < self._hz_hp and not self.in_hold
                and p.get("state") not in HELD_STATES and self.doing != "bomb"
                and not any(flat(e) <= HAZARD_CONTACT_R for e in live)):
            if not any(math.hypot(px - x, pz - z) <= HAZARD_R * 0.5 for x, z, _u in self.hazards):
                self.stats["hazard_marks"] += 1
            self.hazards.append((px, pz, now + HAZARD_S))
        self._hz_hp = hp if isinstance(hp, int) else self._hz_hp
        self.hazards = [h for h in self.hazards if h[2] > now][-12:]
        inside = [(x, z) for x, z, _u in self.hazards if math.hypot(px - x, pz - z) <= HAZARD_R]
        self.hazard = min(inside, key=lambda h: math.hypot(px - h[0], pz - h[1])) if inside else None
        if self.hazard is not None:
            self.stats["hazard_s"] = round(self.stats["hazard_s"] + TICK_S, 2)

    # --- taunts -----------------------------------------------------------------------------------------------------
    def _windup_tick(self, p, snap, now) -> None:
        """Wind-ups begun (windup_seen), stopped by a hit (windup_interrupts), and his health falling with one winding up
        close by (hits_after_windup)."""
        me = p["pos"]
        cur = {}
        for e in snap.get("enemies") or ():
            if (e.get("hp") or 0) <= 0:
                continue
            tid = e.get("ptr", e.get("slot"))
            if windup(e, me):
                cur[tid] = self.windups.get(tid, now)
                if tid not in self.windups:
                    self.stats["windup_seen"] += 1
            elif tid in self.windups and "Dmg" in (e.get("action") or ""):
                self.stats["windup_interrupts"] += 1         # hit out of it
        hp = p.get("hp")
        if isinstance(hp, int) and isinstance(self._wu_hp, int) and hp < self._wu_hp and any(
                math.hypot(e["pos"][0] - me[0], e["pos"][2] - me[2]) <= WINDUP_HIT_R
                for e in snap.get("enemies") or () if e.get("ptr", e.get("slot")) in self.windups):
            self.stats["hits_after_windup"] += 1
        self._wu_hp = hp if isinstance(hp, int) else self._wu_hp
        self.windups = cur

    def _taunt_watch(self, snap, now) -> None:
        """The triggers: TAUNT_KILLS kills within TAUNT_KILLS_S, a blast's TAUNT_BLAST kills (bomb_kills / grenade_kills
        rising that much at once), a boss gone (one of BOSS_HP max health dead or freed); and a click's emotion seen."""
        k = snap.get("kills")
        if isinstance(k, int):
            if isinstance(self._kills_prev, int) and k > self._kills_prev:
                self.kill_times += [now] * min(10, k - self._kills_prev)
            self._kills_prev = k
        self.kill_times = [t for t in self.kill_times if now - t <= TAUNT_KILLS_S]
        if len(self.kill_times) >= TAUNT_KILLS and self.taunt_due is None:
            self.taunt_due = "taunt_multi"
            self.kill_times = []
        bk, gk = self.stats.get("bomb_kills", 0), self.stats.get("grenade_kills", 0)
        if (bk - self._blast_kills_seen[0] >= TAUNT_BLAST or gk - self._blast_kills_seen[1] >= TAUNT_BLAST) \
                and self.taunt_due is None:
            self.taunt_due = "taunt_blast"
        self._blast_kills_seen = (bk, gk)
        alive = {e.get("ptr", e.get("slot")): e.get("hp_max") or 0 for e in snap.get("enemies") or ()
                 if (e.get("hp") or 0) > 0}
        for b in [b for b in self._bosses if b not in alive]:    # a big one gone: down
            del self._bosses[b]
            if self.taunt_due is None:
                self.taunt_due = "taunt_boss"
        self._bosses.update({b: h for b, h in alive.items() if h >= BOSS_HP})
        if now - self.taunt_at <= TAUNT_SEEN_S and (snap.get("player") or {}).get("action") == EMOTION_ACTION \
                and not self._taunt_seen:
            self._taunt_seen = True
            self.stats["taunts_seen"] += 1

    def _taunt(self, p, live, flat, now) -> dict | None:
        """A trigger waiting, nobody within TAUNT_CLEAR_R, TAUNT_GAP_S since the last: the right stick's click (a tap,
        or held for the other call). None: no taunt now (a trigger is dropped when he is not clear)."""
        clear = not any(flat(e) <= TAUNT_CLEAR_R for e in live)
        if now < self.taunt_hold_until:                          # the held call (cut short when one comes close)
            if clear:
                return self._go("melee", "taunt", {"hold": ("rstick",)}, "the partner call, held")
            self.taunt_hold_until = -1e9
        due = self.taunt_due
        if not TAUNTS or due is None:
            return None
        self.taunt_due = None
        eq = p.get("equipped")
        if (now - self.taunt_at < TAUNT_GAP_S or not clear or p.get("state") not in (0, None)
                or (p.get("bomb") or {}).get("out") or self.bomb_phase is not None or self.nade is not None
                or (isinstance(eq, int) and eq >= WEAPON_INDEXES) or (self.combo_urgent and live)):
            return None                                          # not now: the trigger is dropped
        self._gun_down()
        self.taunt_at, self._taunt_seen = now, False
        self.stats["taunts"] += 1
        self.stats[due] += 1
        if random.random() < 0.5:
            self.taunt_hold_until = now + TAUNT_HOLD_S
            return self._go("melee", "taunt", {"hold": ("rstick",)}, f"a taunt ({due[6:]}): the partner call, held")
        return self._go("melee", "taunt", {"tap": "rstick"}, f"a taunt ({due[6:]}): the partner call")

    # --- the whole stage --------------------------------------------------------------------------------------------
    def _census_tick(self, p, snap, live) -> None:
        """The stage's living zombies (census_alive) and those on his floor (census_floor); a pursuit's end: the kill
        count rising (pursuit_kills) or the combo lapsing first (pursuit_lapses)."""
        alive = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0]
        self.stats["census_alive"], self.stats["census_floor"] = len(alive), len(live)
        self.stats["census_list"] = len(snap.get("enemies") or ())   # sEnemy's own list (its count +0x40), the dead too
        pu = self.pursuit
        if pu is not None:
            k, combo = snap.get("kills"), snap.get("combo")
            if isinstance(k, int) and isinstance(pu["kills"], int) and k > pu["kills"]:
                self.stats["pursuit_kills"] += 1
                self.pursuit = None
            elif combo == 0:
                self.stats["pursuit_lapses"] += 1
                self.pursuit = None

    def _prompt_book(self, p, snap, now) -> list:
        """The shown prompts against the last tick's: new ones counted seen (prompt_types), gone ones after a press
        within PROMPT_TAKEN_S counted taken (a B one a climb, a Y one a pickup). The shown ones, newest first."""
        shown = snap.get("prompts")
        if shown is None:
            return []
        cur = {(q["ab"], q["type"]): q for q in shown}
        types = self.stats.setdefault("prompt_types", {})
        for key, q in cur.items():
            if key not in self.prompt_live:
                self.prompt_live[key] = {"since": now, "pressed": None, "at": -1e9, "q": q}
                self.stats["prompts_seen"] += 1
                row = types.setdefault(str(q["type"]), [0, 0, q.get("key")])
                row[0] += 1
                if q.get("key") == "b":
                    self._prompt_spot(p, snap, q)
        for key in [k for k in self.prompt_live if k not in cur]:
            live = self.prompt_live.pop(key)
            if live["pressed"] is not None and now - live["at"] <= PROMPT_TAKEN_S:
                q = live["q"]
                self.stats["prompts_taken"] += 1
                types.setdefault(str(q["type"]), [0, 0, q.get("key")])[1] += 1
                if now - self.fever_until < 1.0 and not self.in_hold:
                    self.stats["finishers"] = self.stats.get("finishers", 0) + 1   # taken among the flashed ones
                    self.stats["flash_qtes"] += 1
                elif q.get("key") == "b" and not self.in_hold:
                    self.stats["climbs"] += 1
                elif q.get("key") == "y":
                    self.stats["pickups"] += 1
        return sorted(cur.values(), key=lambda q: -self.prompt_live[(q["ab"], q["type"])]["since"])

    def _prompt_spot(self, p, snap, q) -> None:
        """A B prompt's spot, logged per stage (the nav's climb links to be)."""
        mesh = snap.get("navmesh")
        stage = getattr(mesh, "name", "") or "unknown"
        spots = self.prompt_spots.setdefault(stage, [])
        x, y, z = p["pos"]
        if any(math.dist((x, y, z), s_[:3]) < 150.0 for s_ in spots):
            return
        spots.append([round(x), round(y), round(z), q["type"]])
        del spots[:-PROMPT_SPOTS_N]
        now = self.clock()
        if self.prompt_spots_path is not None and now - self.prompt_saved >= PROMPT_SAVE_S:
            self.prompt_saved = now
            try:
                self.prompt_spots_path.parent.mkdir(parents=True, exist_ok=True)
                self.prompt_spots_path.write_text(json.dumps(self.prompt_spots), encoding="utf-8")
            except OSError:
                pass

    def _prompt_pressed(self, key: str, now) -> None:
        """Every shown prompt asking for key counts as pressed now (its latency the first time)."""
        for live in self.prompt_live.values():
            if live["q"].get("key") != key:
                continue
            if live["pressed"] is None:
                live["pressed"] = now
                n = self.stats.get("prompt_presses", 0) + 1
                mean = self.stats.get("prompt_latency_ms", 0.0)
                self.stats["prompt_latency_ms"] = round(mean + ((now - live["since"]) * 1000.0 - mean) / n, 1)
                self.stats["prompt_presses"] = n
            live["at"] = now

    def _prompt(self, p, snap, now) -> dict | None:
        """A shown prompt's button, pressed at once and again every PROMPT_REPEAT_S while it stays. None: no prompt to
        take this tick."""
        shown = getattr(self, "_prompt_shown", None) or []
        if not PROMPTS or not shown:
            return None
        eq = p.get("equipped")
        if (p.get("bomb") or {}).get("out") or (isinstance(eq, int) and eq >= WEAPON_INDEXES) or self.nade is not None:
            return None
        px, py, pz = p["pos"]
        near = min((math.hypot(e["pos"][0] - px, e["pos"][2] - pz) for e in snap.get("enemies") or ()
                    if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY), default=math.inf)
        for q in shown:
            key, live = q.get("key"), self.prompt_live[(q["ab"], q["type"])]
            if (key is None or key in PROMPT_SKIP_KEYS or (key == "y" and near < PROMPT_SAFE_R)
                    or now - live["at"] < PROMPT_REPEAT_S):
                continue
            self._prompt_pressed(key, now)
            self._gun_down()
            if key == "stick":
                self.wiggle += 1
                return self._go("prompt", "prompt_stick", {"hold": tuple(k for k in WIGGLE[self.wiggle % len(WIGGLE)] if k != "b")},
                                f"a prompt (type {q['type']}): the stick round")
            return self._go("prompt", "prompt_" + key, {"tap": key}, f"a prompt (type {q['type']}): {key.upper()}")
        return None

    def _nav_heading(self, p, goal, snap, now) -> float | None:
        """The heading of the next nav-mesh waypoint toward goal (None: no mesh, or no path - straight at it)."""
        mesh = snap.get("navmesh")
        if not NAV_WALK or mesh is None:
            return None
        key = (round(goal[0] / 50.0), round(goal[1] / 50.0), round(goal[2] / 50.0))
        if key != self.nav_goal or now - self.nav_at >= NAV_REPLAN_S or not self.nav_path:
            self.nav_goal, self.nav_at = key, now
            self.nav_path = mesh.path(p["pos"], goal)
            self.stats["nav_paths" if self.nav_path else "nav_fails"] += 1
        px, _, pz = p["pos"]
        while self.nav_path and len(self.nav_path) > 1 and math.hypot(self.nav_path[0][0] - px,
                                                                      self.nav_path[0][2] - pz) <= NAV_REACH_R:
            self.nav_path.pop(0)
        if not self.nav_path:
            return None
        w = self.nav_path[0]
        return heading(w[0] - px, w[2] - pz)

    def _walk_keys(self, p, want: float, snap, side=()) -> tuple:
        """Walking toward heading want: the camera's yaw written onto it when the lock's writer can (the stick up), else
        the camera turned with the right stick as he walks."""
        cam, ac = snap.get("camera"), snap.get("aim_cam")
        if self.ram is not None and AIM_LOCK and ac and cam and self.ram(ac["addr"], ac["pitch"], want):
            return ("lup",) + tuple(side)
        err = wrap(want - (cam["yaw"] if cam else p["rot"]))
        return ("lup",) + tuple(side) + self._turn(err, TURN_TOL)

    def _pursue(self, p, snap, now) -> dict | None:
        """After the best zombie of the whole stage (his floor first, then the nearest): along the camera turned to him,
        a side step when the walk stalls. None: no zombie alive anywhere."""
        alive = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0]
        if not alive:
            return None
        px, py, pz = p["pos"]
        e = min(alive, key=lambda z: (abs(z["pos"][1] - py) > MAX_DY,
                                      math.hypot(z["pos"][0] - px, z["pos"][2] - pz)))
        d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
        if self.combo_urgent and self.pursuit is None:
            self.stats["pursuits"] += 1
            self.pursuit = {"since": now, "kills": snap.get("kills")}
        if self.pursue_spot is None or math.hypot(px - self.pursue_spot[1][0], pz - self.pursue_spot[1][1]) > PURSUE_STUCK_CM:
            self.pursue_spot = (now, (px, pz))
        elif now - self.pursue_spot[0] > PURSUE_STUCK_S and now >= self.pursue_side_until:
            self.stats["pursuit_stuck"] += 1                     # against something: a side step
            self.pursue_side_until = now + PURSUE_SIDE_S
            self.detour = "lright" if self.detour == "lleft" else "lleft"
            self.pursue_spot = (now, (px, pz))
        side = (self.detour,) if now < self.pursue_side_until else ()
        if side:
            self.nav_path = None                                 # a stall: plan again after the side step
        want = self._nav_heading(p, e["pos"], snap, now)
        keys = self._walk_keys(p, heading(e["pos"][0] - px, e["pos"][2] - pz) if want is None else want, snap, side)
        floor = "his floor" if abs(e["pos"][1] - py) <= MAX_DY else "another floor"
        return self._go("walk", "pursue", {"hold": keys}, f"after the nearest of {len(alive)} ({floor}, {d:.0f} cm)")

    # --- the way out -------------------------------------------------------------------------------------------------
    @staticmethod
    def _open_heading(p, live, avoid=None) -> float:
        """The clearest way out: of KITE_DIRS headings, the one the zombies within KITE_SCAN_R stand least in the way of
        (each counts by how squarely it is ahead and how near), steering clear of `avoid` (x, z) - a bomb - too."""
        px, _, pz = p["pos"]
        near = []
        for e in live:
            d = math.hypot(e["pos"][0] - px, e["pos"][2] - pz)
            if d <= KITE_SCAN_R:
                near.append((heading(e["pos"][0] - px, e["pos"][2] - pz), 1.2 - d / KITE_SCAN_R))
        away = heading(avoid[0] - px, avoid[1] - pz) if avoid is not None else None
        best, best_cost = 0.0, math.inf
        for i in range(KITE_DIRS):
            h = -math.pi + 2 * math.pi * i / KITE_DIRS
            cost = sum(w * ((1.0 + math.cos(h - b)) / 2.0) ** 2 for b, w in near)
            if away is not None:
                cost += 3.0 * (1.0 + math.cos(h - away)) / 2.0
            if cost < best_cost:
                best, best_cost = h, cost
        return best

    @staticmethod
    def _stick(h: float, yaw: float) -> tuple:
        """The left stick toward heading h with the camera at yaw: up along it, left at +90 deg, the diagonals between."""
        rel = wrap(h - yaw)
        keys = []
        if abs(rel) <= 3 * math.pi / 8:
            keys.append("lup")
        elif abs(rel) >= 5 * math.pi / 8:
            keys.append("ldown")
        if math.pi / 8 < rel < 7 * math.pi / 8:
            keys.append("lleft")
        elif -7 * math.pi / 8 < rel < -math.pi / 8:
            keys.append("lright")
        return tuple(keys)

    # --- grenades and the combo -------------------------------------------------------------------------------------
    def _combo_tick(self, snap, live, flat, now) -> None:
        """The combo's count and window (sGameMan): stats combo_best, combo_breaks (it lapsed with a zombie in reach),
        combo_urgent while it runs under COMBO_LOW_S; a grenade's kills (grenade_kills) NADE_KILLS_S after its throw."""
        combo, ct = snap.get("combo"), snap.get("combo_timer")
        if isinstance(combo, int):
            self.stats["combo_best"] = max(self.stats["combo_best"], combo)
            if self.combo_prev > 0 and combo == 0 and any(flat(e) <= ENGAGE_R for e in live):
                self.stats["combo_breaks"] += 1
            urgent = combo > 0 and isinstance(ct, (int, float)) and 0 < ct < COMBO_LOW_S
            if urgent and not self.combo_urgent:
                self.stats["combo_pushes"] += 1
            self.combo_urgent = urgent
            self.combo_prev = combo
        if self.nade_kills is not None and now - self.nade_kills[1] >= NADE_KILLS_S:
            k = snap.get("kills")
            if isinstance(k, int) and isinstance(self.nade_kills[0], int):
                self.stats["grenade_kills"] += max(0, k - self.nade_kills[0])
            self.nade_kills = None

    def _nade(self, p, vis, live, flat, yaw, snap, now) -> dict | None:
        """A flash at FLASH_N within FLASH_R (none within NADE_CLEAR_R), or a hand / incendiary grenade into a cluster
        NADE_MIN_R..NADE_MAX_R off: the item wheel stepped (D-pad down) to it, the camera to them, ZL then ZR, the gun
        back (D-pad right); one coming within NADE_CLEAR_R calls it off (the gun back first: ZL + ZR with a grenade in
        hand would throw it at his feet). None: no throw this tick."""
        n = self.nade
        eq = p.get("equipped")
        px, _, pz = p["pos"]
        if n is None:
            if not (NADES or FLASH) or now - self.nade_last < NADE_GAP_S or not vis or (p.get("bomb") or {}).get("out"):
                return None
            nades = p.get("nades") or {}
            group, kind = None, None
            near = [e for e in vis if flat(e) <= FLASH_R]
            winding = sum(1 for e in near if windup(e, p["pos"]) == "melee")
            if ((len(near) >= FLASH_N or winding >= 2) and (nades.get(NADE_TYPES["flash"]) or (0, 0))[1] > 0
                    and now - self.flash_last >= FLASH_GAP_S):
                group, kind = near, "flash"
            elif (not NADES or any(flat(e) < NADE_START_R for e in live)   # (FLASH alone: no grenades)
                  or (now - self.frag_last < FRAG_GAP_S and self._clusters(vis, flat) < SPAM_CLUSTERS)):
                return None
            else:
                for e in vis:
                    if not NADE_MIN_R <= flat(e) <= NADE_MAX_R:
                        continue
                    c = [z for z in vis if math.hypot(z["pos"][0] - e["pos"][0], z["pos"][2] - e["pos"][2]) <= NADE_CLUSTER_R]
                    if len(c) >= NADE_N and all(flat(z) >= NADE_MIN_R * 0.8 for z in c):
                        turn = ("fire", "frag") if self.stats["fires"] < self.stats["frags"] else ("frag", "fire")
                        for k in turn:                               # the hand and incendiary grenades in turn
                            if (nades.get(NADE_TYPES[k]) or (0, 0))[1] > 0:
                                group, kind = c, k
                                break
                        if group:
                            break
            if group is None:
                return None
            cx = sum(e["pos"][0] for e in group) / len(group)
            cz = sum(e["pos"][2] for e in group) / len(group)
            self.nade = n = {"kind": kind, "index": nades[NADE_TYPES[kind]][0], "phase": "equip", "at": now - NADE_STEP_S,
                             "steps": 0, "to": (cx, cz), "since": now, "seen": [eq], "back_key": "dright",
                             "gun": eq if isinstance(eq, int) and eq < WEAPON_INDEXES else None}
        self._gun_down()
        if n["seen"][-1] != eq:
            n["seen"].append(eq)
        if n["kind"] != "flash" and n["phase"] in ("equip", "face", "aim") and any(flat(e) < MELEE_R for e in live):
            self.stats["nade_aborts"] += 1                       # one on him: the gun back first, then the fight
            n.update(phase="back", at=now - NADE_STEP_S, steps=0)
        if n["phase"] == "equip":
            if eq == n["index"]:
                n.update(phase="face", at=now)
            elif n["steps"] >= NADE_STEPS:
                n.update(phase="back", at=now - NADE_STEP_S, steps=0)
                self.stats["nade_aborts"] += 1
            elif now - n["at"] >= NADE_STEP_S:
                n["steps"] += 1
                n["at"] = now
                key = self._wheel_key(eq, n["index"])
                return self._go("nade", "nade_" + n["kind"], {"tap": key}, f"the item wheel to the {n['kind']} grenade")
            else:
                return self._go("nade", "nade_" + n["kind"], {"hold": ()}, "the item wheel steps")
        if n["phase"] == "face":
            err = wrap(heading(n["to"][0] - px, n["to"][1] - pz) - yaw)
            if n["kind"] != "flash" and abs(err) > NADE_FACE_ERR and now - n["at"] < NADE_FACE_S:
                return self._go("nade", "nade_" + n["kind"], {"hold": self._turn(err)}, f"facing them for the {n['kind']}")
            n.update(phase="aim", at=now)
        if n["phase"] == "aim":
            if eq != n["index"]:                                 # not that grenade in hand (the wheel moved): no throw
                self.stats["nade_aborts"] += 1
                n.update(phase="back", at=now - NADE_STEP_S, steps=0)
                return self._go("nade", "nade_back", {"hold": ()}, "the wheel moved off the grenade: the gun back")
            if now - n["at"] < NADE_AIM_S:
                return self._go("nade", "nade_" + n["kind"], {"hold": ("zl",)}, f"the {n['kind']} grenade readied")
            n.update(phase="thrown", at=now)
            self.stats[{"flash": "flashes", "frag": "frags", "fire": "fires"}[n["kind"]]] += 1
            if n["kind"] == "flash":
                if NADES:                                        # the fever only with the full grenade set
                    self.fever_until = now + FEVER_S + 0.6
                    me = p["pos"]                                # the flashed ones: in among them; another closing ends it
                    self.flashed = {e.get("ptr", e.get("slot")) for e in snap.get("enemies") or ()
                                    if (e.get("hp") or 0) > 0 and math.dist(me, e["pos"]) <= FLASH_R + 200.0}
                    self.fever_k = snap.get("kills")
                self.flash_last = now
            else:
                if now - self.frag_last < SPAM_S:
                    self.stats["spam_bursts"] += 1               # one straight after another
                self.frag_last = now
                self.nade_kills = (snap.get("kills"), now)
            self.stats["grenade_throws"] += 1
            return self._go("nade", "nade_" + n["kind"], {"hold": ("zl", "zr")}, f"the {n['kind']} grenade thrown")
        if n["phase"] == "thrown":
            n.update(phase="back", at=now, steps=0)
            return self._go("nade", "nade_" + n["kind"], {"hold": ()}, "the triggers let go")
        if n["phase"] == "back":
            if eq is not None and (eq == n["gun"] if n["gun"] is not None else eq < WEAPON_INDEXES):   # his own gun
                self._nade_done(n, now)
                return None
            if n["steps"] >= NADE_STEPS:
                if n["back_key"] == "dright":                    # the other way round the wheel
                    n.update(back_key="dleft", steps=0)
                else:
                    self.stats["nade_back_fails"] += 1
                    self._nade_done(n, now)
                    return None
            if now - n["at"] >= NADE_STEP_S:
                n["steps"] += 1
                n["at"] = now
                return self._go("nade", "nade_back", {"tap": n["back_key"]}, "the gun back in hand")
            return self._go("nade", "nade_back", {"hold": ()}, "the gun coming back")
        return None

    @staticmethod
    def _wheel_key(eq, index: int) -> str:
        """The D-pad press that steps the item wheel toward wheel index `index` (live 2026-10-27 14:17: from a gun the
        first down only opens the wheel, then down steps 9 -> 10 -> 11 -> 12 and stops; up goes straight to 12, then
        11, 10; on an item, down steps up the indexes and up steps down them)."""
        if isinstance(eq, int) and eq >= WEAPON_INDEXES:
            return "ddown" if eq < index else "dup"
        return "dup" if index >= NADE_UP_FROM else "ddown"

    @staticmethod
    def _clusters(vis, flat) -> int:
        """Clusters of NADE_N within NADE_CLUSTER_R of one another NADE_MIN_R..NADE_MAX_R off (each zombie once)."""
        left = [e for e in vis if NADE_MIN_R <= flat(e) <= NADE_MAX_R]
        n = 0
        while left:
            e = left.pop(0)
            group = [z for z in left if math.hypot(z["pos"][0] - e["pos"][0], z["pos"][2] - e["pos"][2]) <= NADE_CLUSTER_R]
            if len(group) + 1 >= NADE_N:
                n += 1
                left = [z for z in left if z not in group]
        return n

    def _nade_done(self, n, now) -> None:
        log = self.stats.setdefault("nade_wheel", [])
        log.append({"kind": n["kind"], "to": n["index"], "seen": n["seen"][-12:]})
        del log[:-NADE_WHEEL_N]
        self.nade, self.nade_last = None, now

    # --- line of sight ---------------------------------------------------------------------------------------------
    def is_blocked(self, e, now) -> bool:
        """Out of sight: blocked within BLOCK_S, or behind a wall by the nav mesh (_sight), and not within BLOCK_MIN_R of
        him (one that close is always fought)."""
        me = self._ppos
        if me is not None and math.hypot(e["pos"][0] - me[0], e["pos"][2] - me[2]) < BLOCK_MIN_R:
            return False
        if self.blocked.get(e.get("ptr", e.get("slot")), -1e9) > now:
            return True
        return not self._sight(e, now)

    def _sight(self, e, now) -> bool:
        """The nav mesh's line from him to e (cached SIGHT_S): False only when it crosses a wall; off his level or off
        the mesh: True (the laser's probe decides)."""
        mesh, me = getattr(self, "_mesh", None), self._ppos
        if mesh is None or me is None:
            return True
        tid = e.get("ptr", e.get("slot"))
        hit = self._sight_cache.get(tid)
        if hit is not None and now - hit[0] < SIGHT_S:
            return hit[1]
        ok = True
        if abs(e["pos"][1] - me[1]) <= MAX_DY:
            eye = (me[0], me[1], me[2])
            ok = mesh.clear(eye, e["pos"]) is not False
        if not ok and (hit is None or hit[1]):
            self.stats["offscreen_skips"] += 1
        if len(self._sight_cache) > 256:
            self._sight_cache.clear()
        self._sight_cache[tid] = (now, ok)
        return ok

    def _block(self, e, now, why: str) -> None:
        """A zombie out of sight for BLOCK_S (stats <why>): never fired at, never the target while another is open."""
        tid = e if not isinstance(e, dict) else e.get("ptr", e.get("slot"))
        pos = e.get("pos") if isinstance(e, dict) else self._pos_of.get(tid)
        me = self._ppos
        if pos is not None and me is not None and math.hypot(pos[0] - me[0], pos[2] - me[2]) < BLOCK_MIN_R:
            return                                               # that close: never out of sight
        if self.blocked.get(tid, -1e9) <= now:
            self.stats[why] += 1
        self.blocked[tid] = now + BLOCK_S
        if self.target == tid:
            self.target = None
        if self.fire_track is not None and self.fire_track[0] == tid:
            self.fire_track = None

    @staticmethod
    def _ray_short(origin, dot, tgt) -> bool:
        """The laser's ray pointed at him (within LOS_YAW / LOS_PITCH of his chest) ends short of him: a wall between."""
        foot = tgt["pos"]
        chest = (foot[0], foot[1] + CHEST_H, foot[2])
        yaw_err, pitch_err = ray_error(origin, dot, chest)
        if abs(yaw_err) > LOS_YAW or abs(pitch_err) > LOS_PITCH:
            return False
        have, want = math.dist(origin, dot), math.dist(origin, chest)
        return 1.0 <= have < want - FIRE_SLACK and dot_on(dot, foot) is None

    def _probe_short(self, origin, dot, tgt, now) -> bool:
        """The lock on him LOS_PROBE_S and the laser's ray, within LOS_PROBE_ERR of his line, ends short of him."""
        if self.lock_tid != tgt.get("ptr", tgt.get("slot")) or now - self.lock_at < LOS_PROBE_S:
            return False
        pt = aim_point(tgt, self._ppos or origin)
        yaw_err, pitch_err = ray_error(origin, dot, pt)
        if abs(yaw_err) > LOS_PROBE_ERR or abs(pitch_err) > LOS_PROBE_ERR:
            return False
        have, want = math.dist(origin, dot), math.dist(origin, pt)
        return 1.0 <= have < want - FIRE_SLACK

    def _los_tick(self, snap, now) -> None:
        """Out of sight by what the shots did: the trigger on one zombie NOHIT_S without his health falling, or
        CC_MISS_N quick shots in a row that took nobody's health within CC_R; a hit marks him seen (SEEN_S)."""
        hp = {e.get("ptr", e.get("slot")): e.get("hp") or 0 for e in snap.get("enemies") or ()}
        for k in [k for k, t in self.blocked.items() if t <= now]:
            del self.blocked[k]
        ft = self.fire_track
        if ft is not None:
            tid, since, h0, last = ft
            if hp.get(tid, h0) < h0:                             # it took his health: in sight
                self.seen[tid] = now
                self.fire_track = [tid, now, hp[tid], last]
            elif now - last > NOHIT_GAP_S:                       # the trigger left him
                self.fire_track = None
            elif now - since >= NOHIT_S:
                self._block(tid, now, "nohit_blocks")
        cs = self.cc_shot
        if cs is not None:
            tid, at, before = cs
            fell = [z for z, h in before.items() if hp.get(z, h) < h]
            if fell:
                for z in fell:
                    self.seen[z] = now
                self.cc_miss.pop(tid, None)
                self.cc_shot = None
            elif now - at > HIT_S:
                self.cc_shot = None
                self.cc_miss[tid] = self.cc_miss.get(tid, 0) + 1
                if self.cc_miss[tid] >= CC_MISS_N:
                    self.cc_miss.pop(tid, None)
                    self._block(tid, now, "cc_blocks")
        if len(self.seen) > 256:
            self.seen = {k: t for k, t in self.seen.items() if now - t <= SEEN_S}
        if len(self.laser_seen) > 256:
            self.laser_seen = {k: t for k, t in self.laser_seen.items() if now - t <= LASER_SEEN_S}

    # --- crowd control ---------------------------------------------------------------------------------------------
    def _crowd_control(self, live, flat, bearing, now) -> dict | None:
        """A zombie up close (CC_R, in front or flanking): the gun down, the game's quick shot every CC_QSHOT_GAP_S and a
        kick at arm's length every CC_KICK_GAP_S (the gauge is kept full), the camera turned to one on the flank; between
        them he steps back. None: nobody that close (the gun's bursts go on)."""
        fever = now < self.fever_until
        if fever and any(flat(e) <= FEVER_BREAK_R and e.get("ptr", e.get("slot")) not in self.flashed for e in live):
            self.fever_until, fever = now, False                 # one not flashed on him: back to aimed fire
            self.stats["fever_breaks"] += 1
        k_now = (getattr(self, "_snap", None) or {}).get("kills")
        if isinstance(k_now, int) and isinstance(self.fever_k, int) and k_now > self.fever_k:
            if fever or now - self.fever_until < 0.6:
                self.stats["fever_kills"] += k_now - self.fever_k
            self.fever_k = k_now if fever else None
        close = [e for e in live if flat(e) <= (FEVER_R if fever else CC_R) and abs(bearing(e)) <= CC_CONE]
        if not close:
            return None
        e = min(close, key=flat)
        d, err = flat(e), bearing(e)
        crowd = (not fever and self._lock_ready(getattr(self, "_snap", {}) or {}, now)
                 and sum(1 for z in live if flat(z) <= CC_CROWD_R) >= 2)
        if crowd and d >= MELEE_R:                               # a crowd: the lock's aimed fire sweeps them
            return None
        self._gun_down()
        if fever:                                                # after a flash: in among the stunned ones
            kick_gap = CC_FAST_GAP_S if QA_FAST else CC_KICK_GAP_S
            if d < MELEE_R and now - self.melee_at >= kick_gap:
                self.melee_at = now
                self.stats["melee"] += 1
                self.stats["fever_kicks"] += 1
                return self._go("crowd", "fever_kick", {"hold": ("zr",) + self._turn(err, CC_ATTACK_CONE)},
                                f"melee fever: a kick at the one at {d:.0f} cm")
            qgap = CC_FAST_GAP_S if QA_FAST else CC_QSHOT_GAP_S
            if d >= MELEE_R and abs(err) <= CC_ATTACK_CONE and now - self.qshot_at >= qgap:
                self.qshot_at = now                              # the stunned ones further off: quick shots
                self.stats["quick_shots"] += 1
                self.stats["fever_quick_shots"] += 1
                self.qshot_release = True
                return self._go("crowd", "fever_quick_shot", {"hold": ("zl", "zr")},
                                f"melee fever: a quick shot at the one at {d:.0f} cm")
            walk = ("lup",) if d >= MELEE_R * 0.8 else ()
            return self._go("crowd", "fever_close", {"hold": walk + self._turn(err, TURN_TOL)},
                            f"melee fever: in to the one at {d:.0f} cm")
        if abs(err) > QUICK_ERR and now - self.quick_at > QUICK_GAP_S and d > MELEE_R:
            self.stats["quick_turns"] += 1                       # one behind: the quick turn
            self.quick = 2
            return self._go("quick_turn", "quick_turn", {"hold": ("ldown",)}, f"one {d:.0f} cm behind: the quick turn")
        backing = sum(1 for z in live if flat(z) < CC_BACK_R) >= CC_BACK_N   # a crowd: every attack backs out too
        out = self._stick(self._open_heading(self._p, live), self._cam_yaw) if backing else ()   # toward open space
        if backing:
            self.stats["cc_backouts"] += 1
        kick_gap, qshot_gap = (CC_FAST_GAP_S, CC_FAST_GAP_S) if QA_FAST else (CC_KICK_GAP_S, CC_QSHOT_GAP_S)
        if d < MELEE_R and abs(err) <= CC_ATTACK_CONE and now - self.melee_at >= kick_gap:
            self.melee_at = now
            self.stats["melee"] += 1
            self.stats["cc_kicks"] += 1
            return self._go("crowd", "cc_kick", {"hold": out + ("zr",)} if backing else {"tap": "zr"},
                            f"one at {d:.0f} cm: a kick (crowd control)" + (", backing out" if backing else ""))
        if not crowd and abs(err) <= CC_ATTACK_CONE and now - self.qshot_at >= qshot_gap:
            self.qshot_at = now                                  # a lone one at point blank: the quick shot
            self.stats["quick_shots"] += 1
            self.stats["cc_quick_shots"] += 1
            self.qshot_release = True
            self.cc_shot = (e.get("ptr", e.get("slot")), now,
                            {z.get("ptr", z.get("slot")): z.get("hp") or 0 for z in live if flat(z) <= CC_R})
            return self._go("crowd", "cc_quick_shot", {"hold": out + ("zl", "zr") if backing else ("zl", "zr")},
                            f"one at {d:.0f} cm: quick shot (crowd control)" + (", backing out" if backing else ""))
        if abs(err) > CC_ATTACK_CONE:                            # on the flank: the camera to him
            return self._go("crowd", "cc_turn", {"hold": self._turn(err)},
                            f"one at {d:.0f} cm on the flank ({math.degrees(err):+.0f} deg): turning")
        step = self._stick(self._open_heading(self._p, live), self._cam_yaw) if self._p else ("ldown",)
        return self._go("crowd", "cc_space", {"hold": step}, f"one at {d:.0f} cm: toward open space between attacks")

    # --- time bonuses ----------------------------------------------------------------------------------------------
    def _bonus_book(self, snap) -> None:
        """This round's bonuses: one waiting at the last tick and gone now was broken (taken: stats bonuses_taken,
        <kind>_bonuses_taken); BONUS_RESET_N or more gone at once is the round starting again (the book closes)."""
        bs = snap.get("bonuses")
        if bs is None or snap.get("mercenaries_phase") != PHASE_PLAYING:
            return
        cur = {b["ptr"]: b["kind"] for b in bs}
        gone = {ptr: kind for ptr, kind in self.bonus_prev.items() if ptr not in cur}
        if len(gone) >= BONUS_RESET_N:
            self._bonus_close()
            gone = {}
        if self.bonus_round is None:
            self.bonus_round = {"seen": {}, "taken": {}}
        r = self.bonus_round
        for ptr, kind in gone.items():
            if ptr in r["taken"]:
                continue
            r["taken"][ptr] = kind
            self.stats["bonuses_taken"] += 1
            self.stats[kind + "_bonuses_taken"] += 1
            self.stats["yellows_taken" if kind == "time" else "greens_taken"] += 1
            if kind == "combo" and isinstance(snap.get("combo"), int) and snap["combo"] > 0 \
                    and (snap.get("combo_timer") or 0) < COMBO_LOW_S + 1.0:
                self.stats["combo_saves"] += 1
            if ptr == self.bonus_target:
                self.bonus_target = None
        r["seen"].update(cur)
        self.bonus_prev = cur

    def _bonus_close(self) -> None:
        """The round's end (or a replay): the bonuses still waiting count as missed; bonus_log keeps the last rounds."""
        r, self.bonus_round, self.bonus_prev = self.bonus_round, None, {}
        self.bonus_target, self.bonus_skip = None, {}
        if not r or not r["seen"]:
            return
        missed = [ptr for ptr in r["seen"] if ptr not in r["taken"]]
        self.stats["bonuses_missed"] += len(missed)
        kinds = list(r["taken"].values())
        log = self.stats.setdefault("bonus_log", [])
        log.append({"seen": len(r["seen"]), "taken": len(kinds), "time": kinds.count("time"),
                    "combo": kinds.count("combo"), "missed": len(missed)})
        del log[:-BONUS_LOG_N]

    def _bonus_run(self, p, live, flat, snap, now) -> dict | None:
        """Phase 1 (BONUS_RUN): while a bonus waits, the nearest one next (his floor first), walked to and attacked
        physically within BONUS_MELEE_R; only a zombie within BONUS_BLOCK_R is fought. None: phase 2 this tick (no bonus
        waiting, every waiting one left for now, a zombie in the way, or the bomb / an item in hand)."""
        bs = snap.get("bonuses")
        px, py, pz = p["pos"]
        cands = [b for b in bs or () if self.bonus_skip.get(b["ptr"], -1e9) <= now and b.get("kind") != "combo"]
        self.stats["phase"] = "bonus_run" if cands else "match"
        eq = p.get("equipped")
        if (not BONUS_RUN or not cands or (p.get("bomb") or {}).get("out") or self.nade is not None
                or (isinstance(eq, int) and eq >= WEAPON_INDEXES) or self.bomb_phase is not None):
            self.run_target = None
            return None
        self.stats["bonus_time_s"] = round(self.stats["bonus_time_s"] + TICK_S, 2)
        if any(flat(e) <= BONUS_BLOCK_R for e in live):          # one in the way: fought first
            self.run_hit_since = None
            return None
        reach = lambda b: math.hypot(b["pos"][0] - px, b["pos"][2] - pz)
        b = next((c for c in cands if c["ptr"] == self.run_target), None)
        if b is not None and (now - self.run_since > BONUS_WALK_S
                              or (self.run_hit_since is not None and now - self.run_hit_since > BONUS_HIT_S)):
            self.bonus_skip[b["ptr"]] = now + BONUS_SKIP_S       # not reached / not breaking: left for now
            self.stats["bonus_skips"] += 1
            cands.remove(b)
            b = None
            if not cands:
                self.run_target = None
                return None
        seen = [c for c in cands if self.bonus_unseen.get(c["ptr"], -1e9) <= now
                and math.dist(p["pos"], c["pos"]) <= BONUS_SHOOT_R]
        if self._lock_ready(snap, now) and (b is None or b not in seen) and seen:
            b = min(seen, key=lambda c: math.dist(p["pos"], c["pos"]))   # one to shoot from here first
            if b["ptr"] != self.run_target:
                self.run_target, self.run_since, self.run_hit_since = b["ptr"], now, None
        if b is not None and b in seen and reach(b) > BONUS_MELEE_R and self._lock_ready(snap, now):
            shot = self._bonus_shoot(p, b, snap, now)
            if shot is not None:
                return shot
        if b is None:
            mesh = snap.get("navmesh") if NAV_WALK else None
            walk = {}
            if mesh is not None:                                 # the nearest by the way there (stairs, ramps)
                for c in cands:
                    way = mesh.path(p["pos"], c["pos"])
                    if way:
                        walk[c["ptr"]] = sum(math.dist(u, w) for u, w in zip([p["pos"]] + way[:-1], way))
            if walk:
                b = min(cands, key=lambda c: walk.get(c["ptr"], 1e9 + reach(c)))
            else:
                b = min(cands, key=lambda c: (abs(c["pos"][1] - py) > BONUS_DY, reach(c)))
            self.run_target, self.run_since, self.run_hit_since = b["ptr"], now, None
            self.pursue_spot = None
        self._gun_down()
        d, kind = reach(b), b["kind"]
        cam = snap.get("camera")
        err = wrap(heading(b["pos"][0] - px, b["pos"][2] - pz) - (cam["yaw"] if cam else p["rot"]))
        if d <= BONUS_MELEE_R:                                   # at it: face it, the physical attack
            if abs(err) > BONUS_MELEE_CONE:
                return self._go("bonus", "bonus_face", {"hold": self._turn(err)},
                                f"a {kind} bonus at {d:.0f} cm: facing it")
            if self.run_hit_since is None:
                self.run_hit_since = now
            if now - self.melee_at >= BONUS_MELEE_GAP_S:
                self.melee_at = now
                self.stats["bonus_melee"] += 1
                return self._go("bonus", "bonus_melee", {"tap": "zr"}, f"a {kind} bonus at {d:.0f} cm: the attack")
            return self._go("bonus", "bonus_wait", {"hold": ()}, f"a {kind} bonus at {d:.0f} cm: the next attack")
        self.run_hit_since = None
        if self.pursue_spot is None or math.hypot(px - self.pursue_spot[1][0], pz - self.pursue_spot[1][1]) > PURSUE_STUCK_CM:
            self.pursue_spot = (now, (px, pz))
        elif now - self.pursue_spot[0] > PURSUE_STUCK_S and now >= self.pursue_side_until:
            self.stats["pursuit_stuck"] += 1                     # against something: a side step
            self.pursue_side_until = now + PURSUE_SIDE_S
            self.detour = "lright" if self.detour == "lleft" else "lleft"
            self.pursue_spot = (now, (px, pz))
        side = (self.detour,) if now < self.pursue_side_until else ()
        if side:
            self.nav_path = None                                 # a stall: plan again after the side step
        want = self._nav_heading(p, b["pos"], snap, now) if d > 2 * BONUS_MELEE_R else None
        if want is not None:                                     # along the nav mesh's way to it
            return self._go("bonus", "bonus_run", {"hold": self._walk_keys(p, want, snap, side)},
                            f"the bonus run: a {kind} bonus at {d:.0f} cm by the nav mesh ({len(cands)} waiting)")
        walk = ("lup",) if abs(err) < math.radians(60) or d > 3 * BONUS_MELEE_R else ()
        return self._go("bonus", "bonus_run", {"hold": walk + side + self._turn(err, TURN_TOL)},
                        f"the bonus run: a {kind} bonus at {d:.0f} cm ({len(cands)} waiting)")

    def _bonus_shoot(self, p, b, snap, now) -> dict | None:
        """A bonus shot through the lock: its centre locked onto, the gun up, the trigger down while the laser's ray runs
        through it (not ending short); the ray short of it BONUS_SEE_S on: out of sight for BONUS_UNSEEN_S (None: walk)."""
        pt = (b["pos"][0], b["pos"][1] + BONUS_H, b["pos"][2])
        if self.bshot is None or self.bshot[0] != b["ptr"]:
            self.bshot = (b["ptr"], now)
        if self.aim_since is None:
            self.aim_since, self._raise_t, self.reraised = now, None, False
        locked = self._lock(p, {"ptr": ("bonus", b["ptr"]), "pos": b["pos"]}, snap, now, point=pt)
        if not locked:
            return None
        lz = snap.get("laser")
        on = short = False
        if lz is not None and lz.get("up") and now - self.aim_since >= READY_S:
            origin, dot = tuple(lz["from"]), tuple(lz["at"])
            on = near_ray(origin, dot, pt, BONUS_HIT_R)
            short = math.dist(origin, dot) < math.dist(origin, pt) - FIRE_SLACK
        if not on and now - self.bshot[1] > BONUS_SEE_S and (short or lz is None or not lz.get("up")):
            self.bonus_unseen[b["ptr"]] = now + BONUS_UNSEEN_S   # the ray never reached it: walk there
            self.stats["bonus_unseen"] += 1
            self.bshot = None
            self._gun_down()
            return None
        fire = set()
        if on:
            self.fire_down = True if p.get("weapon_id") in AUTO_IDS else not self.fire_down
            if self.fire_down:
                fire = {"zr"}
                self.stats["bonus_shots"] += 1
        else:
            self.fire_down = False
        kind = b["kind"]
        return self._go("bonus", "bonus_fire" if fire else "bonus_aim", {"hold": tuple(sorted({"zl"} | fire))},
                        f"a {kind} bonus at {math.dist(p['pos'], b['pos']):.0f} cm: "
                        + ("shooting it (lock)" if on else "the lock on it"))

    def _green_save(self, p, live, flat, snap, now) -> dict | None:
        """The match: the combo window under COMBO_LOW_S, a green (combo) bonus in sight within BONUS_SHOOT_R and nobody
        within BONUS_BLOCK_R - shot through the lock (kicked when it is right there)."""
        combo, ct = snap.get("combo"), snap.get("combo_timer")
        if not (isinstance(combo, int) and combo > 0 and isinstance(ct, (int, float)) and ct < COMBO_LOW_S):
            return None
        eq = p.get("equipped")
        if ((p.get("bomb") or {}).get("out") or self.nade is not None or (isinstance(eq, int) and eq >= WEAPON_INDEXES)
                or any(flat(e) <= BONUS_BLOCK_R for e in live) or not self._lock_ready(snap, now)):
            return None
        greens = [b for b in snap.get("bonuses") or () if b.get("kind") == "combo"
                  and self.bonus_unseen.get(b["ptr"], -1e9) <= now and math.dist(p["pos"], b["pos"]) <= BONUS_SHOOT_R]
        if not greens:
            return None
        b = min(greens, key=lambda c: math.dist(p["pos"], c["pos"]))
        px, _, pz = p["pos"]
        if math.hypot(b["pos"][0] - px, b["pos"][2] - pz) <= BONUS_MELEE_R and now - self.melee_at >= BONUS_MELEE_GAP_S:
            self.melee_at = now
            self.stats["bonus_melee"] += 1
            return self._go("bonus", "bonus_melee", {"tap": "zr"}, "a green bonus for the combo: the attack")
        return self._bonus_shoot(p, b, snap, now)

    def _bonus(self, p, live, flat, snap, now) -> dict | None:
        """A time / combo bonus in reach with nobody near (BONUS_SAFE_R): turned to, the gun up, the aim's ray closed
        onto it and the trigger down while the ray runs through it. None: no bonus to shoot (the fight goes on)."""
        bs = snap.get("bonuses")
        eq = p.get("equipped")
        if (not BONUS_PURSUIT or not bs or (p.get("bomb") or {}).get("out")   # the remote in hand: ZR would set it off
                or (isinstance(eq, int) and eq >= WEAPON_INDEXES) or self.nade is not None
                or any(flat(e) < BONUS_SAFE_R for e in live)):
            self.bonus_target = None
            return None
        px, py, pz = p["pos"]
        reach = lambda b: math.hypot(b["pos"][0] - px, b["pos"][2] - pz)
        cands = [b for b in bs if self.bonus_skip.get(b["ptr"], -1e9) <= now
                 and abs(b["pos"][1] - py) <= BONUS_DY and reach(b) <= BONUS_R]
        b = next((c for c in cands if c["ptr"] == self.bonus_target), None)
        if b is not None and now - self.bonus_since > BONUS_TRY_S:   # aimed at this long, still there: out of sight
            self.bonus_skip[b["ptr"]] = now + BONUS_SKIP_S
            self.stats["bonus_skips"] += 1
            self._gun_down()
            cands.remove(b)
            b = None
        if b is None:
            if not cands:
                self.bonus_target = None
                return None
            b = min(cands, key=reach)
            self.bonus_target, self.bonus_since = b["ptr"], now
        pt = (b["pos"][0], b["pos"][1] + BONUS_H, b["pos"][2])
        d, kind = reach(b), b["kind"]
        cam = snap.get("camera")
        err = wrap(heading(pt[0] - px, pt[2] - pz) - (cam["yaw"] if cam else p["rot"]))
        if self.aim_since is None and abs(err) > AIM_CONE:           # the gun down: the camera turns to it
            return self._go("bonus", "bonus_turn", {"hold": self._turn(err)},
                            f"a {kind} bonus at {d:.0f} cm, {math.degrees(err):+.0f} deg: turning to it")
        if self.aim_since is None:
            self.aim_since, self._raise_t, self.reraised = now, None, False
        lz = snap.get("laser")
        if lz is not None and lz.get("up") and now - self.aim_since >= READY_S:
            origin, dot, source = tuple(lz["from"]), tuple(lz["at"]), "laser"
        elif cam is not None and now - self.aim_since >= LASER_WAIT_S:
            origin, source = cam["pos"], "camera"
            far = math.dist(origin, pt) + 100.0
            have = max(math.dist(origin, cam["target"]), 1.0)
            dot = tuple(origin[k] + (cam["target"][k] - origin[k]) * far / have for k in range(3))
        else:
            return self._go("bonus", "bonus_raise", {"hold": ("zl",)}, f"a {kind} bonus at {d:.0f} cm: the gun comes up")
        on = near_ray(origin, dot, pt, BONUS_HIT_R)
        yaw_err, pitch_err = ray_error(origin, dot, pt)
        fire = set()
        if on:
            self.fire_down = True if p.get("weapon_id") in AUTO_IDS else not self.fire_down
            if self.fire_down:
                fire = {"zr"}
                self.stats["bonus_shots"] += 1
        else:
            self.fire_down = False
        keys = {"zl"} | self._yaw(yaw_err) | self._pitch(pitch_err) | fire
        return self._go("bonus", "bonus_fire" if fire else "bonus_aim", {"hold": tuple(sorted(keys))},
                        f"a {kind} bonus at {d:.0f} cm ({source}): " + ("shooting it" if on else
                        f"steering {math.degrees(yaw_err):+.0f} / {math.degrees(pitch_err):+.0f} deg onto it"))

    # --- remote bombs ----------------------------------------------------------------------------------------------
    def _bomb(self, p, live, flat, yaw, snap, now) -> dict | None:
        """Remote bombs (BOMBS): healthy (BOMB_MIN_HP), nobody within BOMB_ROOM_R and BOMB_STAND_N coming 6-12 m off, at
        most every BOMB_GAP_S, one goes out toward them; with him clear of it, it goes off once BOMB_BLAST_N stand on it,
        one is within BOMB_ON_R of it, one comes within BOMB_DET_NEAR_R of him, or after BOMB_HOLD_S. None: nothing to
        do with bombs this tick (the fight goes on)."""
        bomb = p.get("bomb")
        if not BOMBS or not isinstance(bomb, dict):
            self.bomb_phase = None
            return None
        px, _, pz = p["pos"]
        eq = p.get("equipped")
        if bomb.get("out"):
            if self.bomb_phase in ("thrown", "throw"):
                self.bomb_phase = "wait"
                self.stats["bombs_placed"] += 1
            if self.bomb_phase in ("det_aim", "det", "det_wait"):
                return self._bomb_press(eq, now, detonate=True)
            bx, bz = self.bomb_at
            on = sum(1 for e in live if math.hypot(e["pos"][0] - bx, e["pos"][2] - bz) <= BOMB_BLAST_R)
            me = math.hypot(px - bx, pz - bz)
            out_s = now - (self.bomb_since or now)
            on_him = [e for e in live if flat(e) <= BOMB_FIGHT_R]
            coming = any(flat(e) <= BOMB_DET_NEAR_R for e in live)
            on_close = any(math.hypot(e["pos"][0] - bx, e["pos"][2] - bz) <= BOMB_ON_R for e in live)
            if not on_him and me >= self.book.safe and (on >= BOMB_BLAST_N or on_close or out_s >= BOMB_HOLD_S
                                                        or coming or (self.combo_urgent and on >= 1)):
                self.bomb_phase, self.bomb_phase_at, self.bomb_steps = "det_aim", now, 0
                self.bomb_kills = (snap.get("kills"), now)
                log = self.stats.setdefault("bomb_det_cm", [])
                log.append(round(me))
                del log[:-BOMB_LOG_N]
                return self._bomb_press(eq, now, detonate=True)
            self.bomb_phase = "wait"
            self._gun_down()
            if on_him or me < self.book.safe + 150.0:           # off it, kicking the ones on him as he goes
                return self._bomb_walk(p, (bx, bz), yaw, me, on, now, live=live)
            self.bomb_walk = None
            err = wrap(heading(bx - px, bz - pz) - yaw)
            if (abs(err) > TURN_TOL and self.bomb_face_t < BOMB_FACE_MAX_S
                    and not any(flat(e) <= BOMB_FACE_CLEAR_R for e in live)):   # nobody within 4 m: a look at it
                self.bomb_face_t += TICK_S
                return self._go("bomb", "bomb_face", {"hold": self._turn(err)}, "a bomb out, nobody near: a look at it")
            return self._go("bomb", "bomb_wait", {"hold": ()}, f"a bomb out: {on} on it, {me:.0f} cm from him")
        if self.bomb_phase in ("equip", "face", "aim") and live and not self.bomb_drop and (
                min(flat(e) for e in live) < BOMB_ROOM_R or sum(1 for e in live if flat(e) < BOMB_CROWD_R) >= BOMB_CROWD_N):
            self.stats["bomb_aborts"] += 1                       # one came close while it was readied: fight first
            self.bomb_phase, self.bomb_last = None, now - BOMB_GAP_S + BOMB_RETRY_S
            return None
        if self.bomb_phase in ("equip", "face", "aim", "throw", "thrown"):
            if self.bomb_phase == "thrown" and now - self.bomb_phase_at > BOMB_TAKE_S:   # the throw never showed
                self.stats["bomb_misses"] += 1
                self.bomb_phase, self.bomb_last = None, now
                return None
            return self._bomb_press(eq, now, live=live, p=p, yaw=yaw)
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        if hp_max and hp < BOMB_MIN_HP * hp_max:                 # hurt: no bomb (a throw can drop it at his feet,
            return None                                          # and he must walk out of its reach first)
        if (bomb.get("count") or 0) <= 0 or now - self.bomb_last < BOMB_GAP_S or not live:
            return None
        near = min(flat(e) for e in live)
        crowd = sum(1 for e in live if flat(e) < CC_BACK_R)
        flash_ready = (NADES and now - self.nade_last >= NADE_GAP_S
                       and ((p.get("nades") or {}).get(NADE_TYPES["flash"]) or (0, 0))[1] > 0)
        self.bomb_drop = (BOMB_DROP and crowd >= BOMB_DROP_N      # backing out of a crowd: dropped at his feet
                          and not flash_ready and now >= self.fever_until)   # (the flash and its fever first)
        if near < BOMB_ROOM_R and not self.bomb_drop:
            return None                                          # it lands at his feet: never with one near
        coming = sum(1 for e in live if BOMB_COMING_MIN_R <= flat(e) <= BOMB_STAND_R)
        if coming < BOMB_STAND_N and not self.bomb_drop:
            return None
        nades = p.get("nades") or {}
        if (not self.bomb_drop and NADES and min((flat(e) for e in live), default=1e9) < BOMB_NADE_R
                and any((nades.get(NADE_TYPES[k]) or (0, 0))[1] > 0 for k in ("frag", "fire"))):
            self.stats["nade_choices"] += 1                      # they are already close: a grenade, not a bomb
            self.frag_last = -1e9
            return None
        self.stats["bomb_choices"] += 1
        if self.bomb_drop:
            self.stats["bomb_drops"] += 1
        self.bomb_why = f"{crowd} on him: dropped as he backs out" if self.bomb_drop else f"{coming} coming at 5-12 m"
        self.bomb_phase, self.bomb_phase_at, self.bomb_steps = "equip", now - BOMB_STEP_S, 0
        return self._bomb_press(eq, now, live=live, p=p, yaw=yaw)

    def _bomb_went_off(self, p, now) -> None:
        """The bomb out is gone after a set-off (the game put the gun back): counted, its toll read for BOMB_LEARN_S
        (_blast_tick), its kills counted BOMB_KILLS_S from now."""
        px, _, pz = p["pos"]
        self.stats["bombs_detonated"] += 1
        if self.bomb_at is not None:                         # its toll on him and on them, read BOMB_LEARN_S
            bx, bz = self.bomb_at
            self.blast = {"t": now, "at": (bx, bz), "real": bool(self.bomb_real),
                          "me_cm": round(math.hypot(px - bx, pz - bz)), "hp0": self._prev_hp, "me": (px, pz),
                          "z0": dict(self._prev_z), "low": {}, "my_low": self._prev_hp,
                          "near": sum(1 for h, zp in self._prev_z.values()
                                      if h > 0 and math.hypot(zp[0] - px, zp[2] - pz) <= BOMB_BLAME_R),
                          "held": bool(self.in_hold)}
        self.bomb_walk = self.bomb_walk_since = None
        self.bomb_real = False
        self.bomb_phase, self.bomb_last, self.bomb_at = None, now, None
        if self.bomb_kills is not None:                      # its kills counted BOMB_KILLS_S from the blast
            self.bomb_kills = (self.bomb_kills[0], now)

    def _bomb_track(self, p, snap, now) -> None:
        """Where the bomb out lies: read from its unit (snapshot bomb_pos, within BOMB_REAL_R of him), else where he stood
        throwing it (out but untracked: where he stands). stats bomb_aim_err_cm: how far it lay from 3 m ahead of the
        throw; bomb_radius_cm / bomb_safe_cm: the learned reach and the rule."""
        self.stats["bomb_radius_cm"], self.stats["bomb_safe_cm"] = round(self.book.radius), round(self.book.safe)
        if not (p.get("bomb") or {}).get("out"):
            if self.bomb_phase in ("det_aim", "det", "det_wait"):
                self._bomb_went_off(p, now)
            return
        px, _, pz = p["pos"]
        if self.bomb_phase in ("thrown", "throw"):              # the throw showed in its slot: placed
            self.bomb_phase = "wait"
            self.stats["bombs_placed"] += 1
            self.bomb_face_t = 0.0
        if self.bomb_at is None:
            self.bomb_at = (px, pz)
            self.bomb_since, self.bomb_from = now, (px, pz)
        real = snap.get("bomb_pos")
        if real is not None and math.hypot(real[0] - px, real[2] - pz) <= BOMB_REAL_R:
            if not self.bomb_real:
                self.bomb_real = True
                if self.bomb_from is not None:
                    fx, fz = self.bomb_from
                    yaw = (snap.get("camera") or {}).get("yaw", p.get("rot") or 0.0)
                    ax, az = fx + BOMB_AHEAD * math.sin(yaw), fz + BOMB_AHEAD * math.cos(yaw)
                    log = self.stats.setdefault("bomb_aim_err_cm", [])
                    log.append(round(math.hypot(real[0] - ax, real[2] - az)))
                    del log[:-BOMB_LOG_N]
            self.bomb_at = (real[0], real[2])

    def _bomb_escape(self, p, snap, now) -> dict | None:
        """Inside the bomb's learned reach while it is out: he walks out before anything else (only a hold comes first);
        a set-off under way with him inside the rule's distance is called off. None: clear of it."""
        if not BOMBS or not (p.get("bomb") or {}).get("out") or self.bomb_at is None:
            return None
        px, _, pz = p["pos"]
        bx, bz = self.bomb_at
        me = math.hypot(px - bx, pz - bz)
        py = p["pos"][1]
        live = [e for e in snap.get("enemies") or () if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY]
        on_him = any(math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= BOMB_FIGHT_R for e in live)
        if self.bomb_phase in ("det_aim", "det") and (me < self.book.safe or (on_him and self.bomb_phase == "det_aim")):
            self.stats["bomb_det_holds"] += 1                    # too near it for the blast, or one on him: not now
            self.bomb_phase = "wait"
        if me >= self.book.radius:
            return None
        self._gun_down()
        if self.bomb_phase not in ("wait", None):
            self.bomb_phase = "wait"
        if self.bomb_walk_since is None:
            self.stats["bomb_escapes"] += 1
        cam = snap.get("camera")
        return self._bomb_walk(p, (bx, bz), cam["yaw"] if cam else p["rot"], me, 0, now, act="bomb_escape",
                               why=f"inside the bomb's reach ({me:.0f} of {self.book.radius:.0f} cm): out first",
                               live=live)

    def _blast_tick(self, p, snap, now) -> None:
        """A blast's toll, BOMB_LEARN_S after it showed: the zombies it hurt and spared by their distance from it, his
        health lost (stats bomb_self_hits when it was the blast: him inside its reach, or nobody within BOMB_BLAME_R and
        no hold to blame), booked for the learned reach when the bomb was read where it lay; stats bomb_blast_log."""
        zs = {e.get("ptr", e.get("slot")): (e.get("hp") or 0, e["pos"]) for e in snap.get("enemies") or ()}
        b = self.blast
        if b is not None:
            for k, (h, _pos) in zs.items():
                if k in b["z0"]:
                    b["low"][k] = min(b["low"].get(k, h), h)
            if isinstance(p.get("hp"), int):
                b["my_low"] = p["hp"] if b["my_low"] is None else min(b["my_low"], p["hp"])
            b["held"] = b["held"] or bool(self.in_hold)
            if now - b["t"] >= BOMB_LEARN_S:
                self.blast = None
                bx, bz = b["at"]
                hit, spared = [], []
                for k, (h0, zp) in b["z0"].items():
                    if h0 <= 0:
                        continue
                    d = round(math.hypot(zp[0] - bx, zp[2] - bz))
                    if math.hypot(zp[0] - b["me"][0], zp[2] - b["me"][1]) <= BOMB_ME_R:
                        continue                                 # at his elbow: his own blows, not the blast
                    if b["low"].get(k, 0) < h0:                  # hurt, or gone (killed and freed)
                        hit.append(d)
                    elif d <= BOMB_SPARE_R:
                        spared.append(d)
                lost = (b["hp0"] - b["my_low"]) if isinstance(b["hp0"], int) and isinstance(b["my_low"], int) else 0
                inside = b["me_cm"] < self.book.radius + 100.0
                self_hit = lost >= BOMB_HURT_HP and (inside or (not b["near"] and not b["held"]))
                if self_hit:
                    self.stats["bomb_self_hits"] += 1
                rec = {"me_cm": b["me_cm"], "hp_lost": lost, "hit_cm": sorted(hit), "spared_cm": sorted(spared)[:12],
                       "real": b["real"], "self_hit": self_hit, "near_him": b["near"], "held": b["held"],
                       "at": round(time.time()), "v": BOMB_BOOK_V}
                log = self.stats.setdefault("bomb_blast_log", [])
                log.append(rec)
                del log[:-BOMB_LOG_N]
                if b["real"]:
                    self.book.add(rec)
        self._prev_z = zs
        self._prev_hp = p.get("hp") if isinstance(p.get("hp"), int) else self._prev_hp

    def _death(self, p, snap, now) -> None:
        """stats death_log: what he was doing over his last HP_HIST_S (the decisions while his health fell), whether a
        zombie held him, how many stood near, a bomb out and how far, so a death names its cause."""
        px, py, pz = p["pos"]
        near = sorted(math.hypot(e["pos"][0] - px, e["pos"][2] - pz) for e in snap.get("enemies") or ()
                      if (e.get("hp") or 0) > 0 and abs(e["pos"][1] - py) <= MAX_DY)
        falls, doing_fall = [], {}
        for (t0, h0, d0), (t1, h1, _d1) in zip(self.hp_hist, self.hp_hist[1:]):
            if isinstance(h0, int) and isinstance(h1, int) and h1 < h0:
                falls.append(h0 - h1)
                doing_fall[d0] = doing_fall.get(d0, 0) + (h0 - h1)
        bomb = None
        if self.bomb_at is not None:
            bomb = round(math.hypot(px - self.bomb_at[0], pz - self.bomb_at[1]))
        log = self.stats.setdefault("death_log", [])
        log.append({"held": bool(self.in_hold), "doing": self.doing, "why": self.why[:80],
                    "lost_by_doing": doing_fall, "hp_3s": [h for _t, h, _d in self.hp_hist[::5]],
                    "near_2m": sum(1 for d in near if d <= 200), "near_4m": sum(1 for d in near if d <= 400),
                    "bomb_phase": self.bomb_phase, "bomb_cm": bomb})
        del log[:-DEATH_LOG_N]
        self.hp_hist = []
        self.bomb_phase, self.bomb_at, self.bomb_walk, self.bomb_walk_since = None, None, None, None

    def _bomb_walk(self, p, at, yaw, me, on, now, act="bomb_walk", why=None, live=()) -> dict:
        """Off the bomb: the camera turned to it and the stick back (he runs away from it); not 30 cm further in
        BOMB_STUCK_S (a wall behind), a side step for BOMB_SIDE_S, the side swapped each time."""
        px, _, pz = p["pos"]
        if self.bomb_walk_since is None:
            self.stats["bomb_walks"] += 1
            self.bomb_walk_since = now
        if self.bomb_walk is None:
            self.bomb_walk = (now, (px, pz))
        elif math.hypot(px - self.bomb_walk[1][0], pz - self.bomb_walk[1][1]) > 30.0:
            self.bomb_walk = (now, (px, pz))
        elif now - self.bomb_walk[0] > BOMB_STUCK_S and now >= self.bomb_side_until:
            self.bomb_side_until = now + BOMB_SIDE_S
            self.detour = "lright" if self.detour == "lleft" else "lleft"
            self.bomb_walk = (now, (px, pz))
        keys = self._stick(self._open_heading(p, live, avoid=at), yaw)
        if now < self.bomb_side_until and self.detour not in keys:
            keys = keys + (self.detour,)
        why = why or f"walking off the bomb: {me:.0f} cm from it, {on} on it"
        d_near = min((math.hypot(e["pos"][0] - px, e["pos"][2] - pz) for e in live), default=math.inf)
        if d_near <= BOMB_FIGHT_R and now - self.melee_at >= CC_KICK_GAP_S:   # one on him: a kick as he goes
            self.melee_at = now
            self.stats["melee"] += 1
            self.stats["bomb_kicks"] += 1
            keys += ("zr",)
            why += f", a kick at the one at {d_near:.0f} cm"
        return self._go("bomb", act, {"hold": keys}, why)

    def _bomb_kills_tick(self, snap, now) -> None:
        """A blast's kills (stats bomb_kills): the kill count BOMB_KILLS_S after it less the count when it was set off;
        every tick, foes or none (a blast that clears the area leaves nobody for the decision)."""
        if self.bomb_kills is None or self.bomb_phase in ("det_aim", "det", "det_wait"):
            return
        if now - self.bomb_kills[1] >= BOMB_KILLS_S:
            k = snap.get("kills")
            if isinstance(k, int) and isinstance(self.bomb_kills[0], int):
                self.stats["bomb_kills"] += max(0, k - self.bomb_kills[0])
            self.bomb_kills = None

    def _bomb_press(self, eq, now, detonate: bool = False, live=None, p=None, yaw=0.0) -> dict | None:
        """One step of a bomb's keys: the wheel stepped (D-pad down) until the remote bomb is in hand, the crowd brought
        into the aim (placing), ZL held BOMB_AIM_S, then ZR with it: a throw, or with the bomb out, its blast."""
        self._gun_down()
        tag = "bomb_det" if detonate else "bomb_place"
        if self.bomb_phase in ("equip", "det_aim") and eq != BOMB_INDEX:   # the remote bomb to hand first
            if self.bomb_steps >= BOMB_STEPS:
                self.stats["bomb_misses"] += 1
                self.bomb_phase, self.bomb_last = None, now
                return None
            if now - self.bomb_phase_at >= BOMB_STEP_S:
                self.bomb_steps += 1
                self.bomb_phase_at = now
                return self._go("bomb", tag, {"tap": self._wheel_key(eq, BOMB_INDEX)}, "the item wheel to the remote bomb")
            return self._go("bomb", tag, {"hold": ()}, "the item wheel steps")
        if self.bomb_phase == "equip":
            self.bomb_phase, self.bomb_phase_at = "face", now
        if self.bomb_phase == "face":
            px, _, pz = p["pos"]
            group = [e for e in live if math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= BOMB_STAND_R] or live
            cx = sum(e["pos"][0] for e in group) / len(group)
            cz = sum(e["pos"][2] for e in group) / len(group)
            err = wrap(heading(cx - px, cz - pz) - yaw)
            if not self.bomb_drop and abs(err) > BOMB_FACE and now - self.bomb_phase_at < BOMB_FACE_S:
                return self._go("bomb", tag, {"hold": self._turn(err)}, f"facing them for the bomb ({self.bomb_why})")
            self.bomb_phase, self.bomb_phase_at = "aim", now
            self.bomb_at = (px, pz)                              # taken to lie where he stands until it is read
            self.bomb_from = (px, pz)
        if self.bomb_phase in ("aim", "det_aim"):
            if now - self.bomb_phase_at < BOMB_AIM_S:
                return self._go("bomb", tag, {"hold": ("zl",)}, "the remote readied" if detonate else "the bomb readied")
            self.bomb_phase, self.bomb_phase_at = ("det" if detonate else "throw"), now
            return self._go("bomb", tag, {"hold": ("zl", "zr")}, "the bomb set off" if detonate else "the bomb thrown")
        if self.bomb_phase in ("throw", "det"):
            self.bomb_phase, self.bomb_phase_at = ("det_wait" if detonate else "thrown"), now
            if not detonate:
                self.bomb_since = now
            return self._go("bomb", tag, {"hold": ()}, "the triggers let go")
        if self.bomb_phase == "det_wait" and now - self.bomb_phase_at > BOMB_TAKE_S:   # no blast yet: once more
            self.bomb_phase, self.bomb_phase_at, self.bomb_steps = "det_aim", now, 0
        return self._go("bomb", tag, {"hold": ()}, "waiting on the bomb")

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
                      "tablet_presses", "tablet_misses", "turns", "quick_turns", "backoffs", "reraise", "restale",
                      "bombs_placed", "bombs_detonated", "bomb_kills", "bomb_misses", "holds_freed_no_press",
                      "holds_shaken", "cc_quick_shots", "cc_kicks", "los_blocks", "nohit_blocks", "cc_blocks",
                      "camera_far_holds", "detours", "bomb_walks", "bomb_self_hits", "bomb_aborts", "bomb_escapes",
                      "bomb_det_holds", "bomb_kicks", "bomb_hits_taken", "flashes", "frags", "fires", "fever_kicks",
                      "surround_events", "confirmed_shots", "moving_shots", "long_shot_kills", "bomb_drops",
                      "quick_attacks", "quick_attack_kills", "pursuits", "pursuit_kills", "pursuit_lapses", "taunts",
                      "aim_locks", "lock_write_ok", "lock_write_fail", "lock_fallbacks", "aimed_shots", "aimed_hits",
                      "boss_damage", "down_shots", "down_kills", "down_recoveries", "dying_deaths", "hazard_marks",
                      "taunts_seen",
                      "pursuit_stuck",
                      "grenade_kills", "combo_breaks", "combo_pushes", "unsafe_trigger_blocks", "tablet_dying_presses",
                      "tablet_dying_taken", "bonuses_taken", "bonuses_missed", "bonus_skips", "bonus_shots")         + AIM_COUNTERS + tuple("t_" + d for d in DOINGS)

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
        snap["auto_qte"] = bool((re6_switch_mods.ORIG.get(id(ad)) or {}).get("auto_qte"))   # the bot leaves holds to it
        if self.stats is not None:
            self.stats["mod_writes"] = self.stats.get("mod_writes", 0) + res.get("writes", 0)
            st = re6_switch_mods.ORIG.get(id(ad)) or {}
            self.stats["recoil_x"] = st.get("magnum_speed", re6_switch_mods.MAGNUM_SPEED_X) if st.get("fire_rate") else 1.0
            self.stats["throw_x"] = st.get("throw_speed", re6_switch_mods.THROW_SPEED_X) if st.get("fire_rate") else 1.0
            self.stats["throw_fast"] = st.get("throw_fast", 0)
            self.stats["magnum_fast"] = st.get("magnum_fast", 0)
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
        if learn_dir is None:                                    # the deployment: gbox-data/mercs/learned/<title>
            from .. import lessons as L
            learn_dir = L.ROOT.parent / "learned" / MAP_ID
        return Bot(stats=stats, clock=clock, learn_dir=learn_dir, ram=aim_writer(m))

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        out = {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
               "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
               "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "no_mercy"}
        last = PICK.last
        if last:                                             # the round's own draws (per round, for the report)
            st, ch = last.get("stage"), last.get("character")
            out.update(stage=STAGES[st] if isinstance(st, int) and 0 <= st < len(STAGES) else None,
                       character=CHARACTERS[ch] if isinstance(ch, int) and 0 <= ch < len(CHARACTERS) else None,
                       costume=last.get("costume"),
                       stage_coverage=" ".join(f"{k}:{v}" for k, v in sorted(coverage()["stages"].items())))
        return out


DRIVER = RE6Switch
