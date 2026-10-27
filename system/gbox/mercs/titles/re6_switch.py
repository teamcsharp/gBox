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

import json
import math
import struct
import time
from pathlib import Path

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
    selects: the stage among the unlocked ones, the costume among the listed ones; a queued round (request) names the
    character and / or the stage (None = random, MercMode's convention); no queue: PLAYER_ID, a random stage."""

    def __init__(self, rng=None):
        import random
        self.rng = rng or random.Random()
        self.queued: dict = {}
        self.stage = self.costume = None
        self.costume_of = None

    def reset(self) -> None:
        self.stage = self.costume = self.costume_of = None

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
        PICK.stage = q if q in open_ else PICK.rng.choice(open_)
    return PICK.stage


def wanted_character() -> int:
    q = PICK.queued.get("character")
    return q if isinstance(q, int) else PLAYER_ID


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
REPLAY_ON_DEATH = True
ROUND_TIME_S, FRESH_ROUND_S = 120.0, 3.0   # No Mercy's clock; within this of it on the first tick alive: a new round


def player_target(m, unit: int) -> int:
    """The character select's cursor index for the wanted character (a queued one, else PLAYER_ID): its place in the
    select's own list of ids, which grows as characters unlock; PLAYER_TARGET when the list can't be read or lacks
    him."""
    want = wanted_character()
    try:
        n = _i32(m, unit + PLAYER_COUNT)
        if 0 < n <= 16:
            ids = struct.unpack(f"<{n}i", m.rd(unit + PLAYER_IDS, 4 * n))
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


def equipped_id(m, p: int) -> int:
    """The item id of the gun in hand (inventory_state)."""
    return inventory_state(m, p)[1]


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
            equipped, weapon_id, bomb = inventory_state(m, p)
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max, "ammo": ammo,
                              "state": state, "motion": motion, "tablets": tablets, "weapon_id": weapon_id,
                              "equipped": equipped, "bomb": bomb}
            if hp <= 0:                                     # dead: CONTINUE? and its cursor, once it takes input
                over = ui_units(m, base).get("uIdGameover00")
                snap["continue_cursor"] = continue_prompt(m, over)["cursor"] if over else None
        except (ValueError, OSError):
            snap["player"] = None
        if snap["player"]:
            snap["camera"] = camera(m, base, snap["player"]["pos"])
            snap["laser"] = laser(m, base, snap["player"]["pos"])
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
        if phase == PHASE_PLAYING and (PICK.stage is not None or PICK.costume is not None or PICK.queued):
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
CC_R, CC_CONE = 350.0, math.radians(100)
CC_QSHOT_GAP_S, CC_KICK_GAP_S, CC_ATTACK_CONE = 0.5, 0.4, math.radians(60)
CC_BACK_N, CC_BACK_R = 3, 400.0         # this many within this: he steps back while he fires (the earlier back-off)
# Dying (RE6's 1-health state: he crawls; every death in the 2026-10-27 runs came through it, at 1 health for 3 s and
# more): R pressed for a tablet every DYING_GAP_S while the case holds one; stats tablet_dying_presses / _taken (the
# count fell) say whether the game takes it there, dying_states the action bytes seen while dying.
DYING_TABLETS, DYING_HP, DYING_GAP_S = True, 1, 1.0
# The trigger's safety (live 2026-10-27 13:43: a crowd-control quick shot with the remote bomb in hand threw it and set it
# off at his feet): ZL + ZR goes out only with a gun in hand (wheel index < WEAPON_INDEXES) or in the bomb's own throw and
# set-off; otherwise the D-pad's right brings the gun back first (stats unsafe_trigger_blocks).
WEAPON_INDEXES = 7                      # wheel indexes 0-6 the weapons, 7-12 the items (the remote bomb 12)
THROW_ACTS = ("bomb_place", "bomb_det")
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
BOMB_STAND_N, BOMB_STAND_R, BOMB_ROOM_R = 3, 1000.0, 250.0   # a stand: this many within this, the nearest beyond ROOM
BOMB_SECTION_CM = 1500.0                # a new section: this far from where the last bomb went, a zombie within reach
BOMB_GAP_S = 12.0                       # a bomb at most this often
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
TICK_S = 0.05                           # the engine's tick (gbox.mercs.engine tick_s)
BOMB_FIGHT_R, BOMB_DET_NEAR_R, BOMB_FACE_CLEAR_R, BOMB_FACE_MAX_S = 200.0, 400.0, 400.0, 0.4
BOMB_CROWD_N, BOMB_CROWD_R = 2, 300.0
DEATH_LOG_N, HP_HIST_S = 8, 3.0         # stats death_log: the last deaths, each with his last HP_HIST_S
BOMB_STUCK_S, BOMB_SIDE_S = 0.6, 0.8    # walking off it: not 30 cm further in this long, a side step this long
BOMB_HURT_HP = 50                       # a blast that takes this much of his health (BOMB_LEARN_S): stats bomb_self_hits
BOMB_LOG_N = 12
BOMB_REAL_R = 3000.0                    # the placed bomb's unit (snapshot bomb_pos) within this of him: its spot is used
                                        # (stats bomb_aim_err_cm: how far it lay from 3 m ahead of the throw)
BOMB_MIN_HP = 0.5                       # no new bomb under half health (live 12:29: a throw at low health dropped it at
                                        # his feet and he crawled out of its reach at 1 health, too slow)
BOMB_RETRY_S = 4.0                      # readying one given up (one came within BOMB_ROOM_R): tried again this soon
                                        # (live 11:21: 900 -> 1 health in 5 s readying one with two at 76 cm)
BOMB_STEP_S, BOMB_STEPS, BOMB_AIM_S = 0.45, 8, 0.45   # the wheel's step pace and presses, ZL held before ZR
BOMB_FACE, BOMB_FACE_S = math.radians(25), 1.5        # the throw waits (this long at most) for the crowd in the aim
BOMB_TAKE_S, BOMB_KILLS_S = 2.0, 3.0    # a throw / a blast shows in its slot within this; its kills counted this long
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
          "walk", "no_foes", "dead", "bomb", "crowd")
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

    def __init__(self, stats: dict | None = None, clock=time.monotonic, learn_dir=None):
        from ..bot_look import BotLook
        self.stats = stats if stats is not None else {}
        self.clock = clock
        for k in ("shots", "hits", "quick_shots", "melee", "turns", "quick_turns", "wiggles", "holds", "reloads",
                  "reraise", "restale", "deaths", "tablets", "tablet_presses", "tablet_misses", "backoffs",
                  "pulls_hit", "pulls_miss", "first_pull_n", "bombs_placed", "bombs_detonated", "bomb_kills",
                  "bomb_misses", "holds_freed_no_press", "holds_shaken", "cc_quick_shots", "cc_kicks",
                  "los_blocks", "nohit_blocks", "cc_blocks", "camera_far_holds", "detours", "bomb_walks",
                  "bomb_self_hits", "bomb_aborts", "bomb_escapes", "bomb_det_holds", "bomb_kicks",
                  "bomb_hits_taken", "unsafe_trigger_blocks", "dyings", "tablet_dying_presses", "tablet_dying_taken"):
            self.stats.setdefault(k, 0)
        for k in ("trigger_s", "first_pull_s", "bomb_face_s"):
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
        self.bomb_walk, self.bomb_side_until = None, -1e9    # walking off it: (since when, from where); a side step
        self.bomb_walk_since = None                          # when this bomb's walk began
        self.bomb_real = False                               # this bomb's spot read from its unit
        self.bomb_face_t, self._tick_hp, self._tick_at = 0.0, None, None   # this bomb's facing; last tick's health
        self.hp_hist: list = []                              # (when, his health, doing) for the last HP_HIST_S
        self.book = BlastBook(learn_dir)                     # the blast's learned reach (this title)
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
        hold = set(out.get("hold") or ())
        eq = (snap.get("player") or {}).get("equipped")
        if ({"zl", "zr"} <= hold and isinstance(eq, int) and eq >= WEAPON_INDEXES
                and self.stats.get("act") not in THROW_ACTS):     # an item in hand: ZL + ZR would throw it or set it off
            self.stats["unsafe_trigger_blocks"] += 1
            self.qshot_release, self.fire_down = False, False
            out = self._go("bomb", "gun_back", {"tap": "dright"}, f"an item in hand (wheel {eq}): the gun back first")
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
        self._pos_of = {e.get("ptr", e.get("slot")): e["pos"] for e in snap.get("enemies") or ()}
        self._los_tick(snap, now)
        self._tablet_check(p, now)
        self._bomb_kills_tick(snap, now)
        self._bomb_track(p, snap, now)
        self._blast_tick(p, snap, now)
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
        if self.in_hold and not held:                        # a hold read in RAM just ended: how it was freed
            self._hold_ended(now, snap)
        if p.get("hp") != DYING_HP:
            self.dying_since = None
        elif DYING_TABLETS and not held:                     # dying: a tablet before anything else
            dying = self._dying(p, now)
            if dying is not None:
                return dying
        if held or now < self.break_until or (state is None and self.grabbed(p, near, now)) or self.held(p, now):
            if held:                                         # RAM says a zombie holds him: shake him off
                if not self.in_hold:
                    self.stats["holds"] += 1
                    self.hold_since, self.hold_pressed = now, False
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
            return self._go("held", "break_free", {"hold": WIGGLE[self.wiggle % len(WIGGLE)]},
                            f"held (action {state}): B mashed, the stick round")
        self.in_hold = False
        escape = self._bomb_escape(p, snap, now)
        if escape is not None:
            return escape
        act = self._decide(p, live, flat, near_e, near, snap, now)
        if set(act.get("hold", ())) & {"lup", "ldown", "lleft", "lright"}:
            self.move_at = now
        return act

    def _hold_ended(self, now, snap) -> None:
        """A RAM hold's end: stats holds_freed_no_press (it ended before he pressed anything: the game's auto QTE) or
        holds_shaken, and hold_log - its length, whether he pressed, whether auto QTE was on - for the last HOLD_LOG_N."""
        self.in_hold = False
        pressed = bool(self.hold_pressed)
        self.stats["holds_shaken" if pressed else "holds_freed_no_press"] += 1
        log = self.stats.setdefault("hold_log", [])
        log.append({"s": round(now - (self.hold_since or now), 2), "pressed": pressed,
                    "auto_qte": bool(snap.get("auto_qte"))})
        del log[:-HOLD_LOG_N]

    def _decide(self, p, live, flat, near_e, near, snap, now) -> dict:
        px, py, pz = p["pos"]
        if not live:
            self._gun_down()
            return self._go("no_foes", "idle", {"hold": ()}, "no zombie alive within reach")
        cam = snap.get("camera")
        yaw = cam["yaw"] if cam else p["rot"]                    # without the camera: the body's heading stands in
        bearing = lambda e: wrap(heading(e["pos"][0] - px, e["pos"][2] - pz) - yaw)
        vis = [e for e in live if not self.is_blocked(e, now)]              # out of sight: never the target
        front = [e for e in vis if flat(e) <= ENGAGE_R and abs(bearing(e)) <= FRONT_CONE]
        tgt = self._choose(p, yaw, front or vis or live, now)
        foot, dist, err = tgt["pos"], flat(tgt), bearing(tgt)
        self.stats["target_dist"] = round(dist)
        crowd = sum(1 for e in live if flat(e) < CROWD_R)
        hp, hp_max = p.get("hp") or 0, p.get("hp_max") or 0
        gap = TABLET_RETRY_S if self.tablet_missed else TABLET_GAP_S
        if (hp_max and hp > 1 and (p.get("tablets") or 0) > 0 and p.get("state") in (0, None)
                and self.tablet_wait is None and now - self.tablet_at >= gap
                and (hp <= TABLET_LOW_HP * hp_max or (hp <= TABLET_HP * hp_max and near > TABLET_CLEAR_R))):
            self._gun_down()                                     # 60 % health or less, free: a tablet (R),
            self.tablet_at = now                                 # the gun down for it (the tap lets ZL go first)
            self.tablet_wait = (p.get("tablets"), now)
            self.stats["tablet_presses"] += 1
            return self._go("tablet", "tablet", {"tap": "r"}, f"health {hp}/{hp_max}: a tablet")
        bombed = self._bomb(p, live, flat, yaw, snap, now)
        if bombed is not None:
            return bombed
        crowded = self._crowd_control(vis, flat, bearing, now)
        if crowded is not None:
            return crowded
        if not vis:                                              # every one in reach out of sight: a way round
            self._gun_down()
            if now - self.detour_at >= DETOUR_S:
                self.detour_at, self.detour = now, "lright" if self.detour == "lleft" else "lleft"
                self.stats["detours"] += 1
            return self._go("walk", "walk_detour", {"hold": ("lup", self.detour) + self._turn(err, TURN_TOL)},
                            f"the nearest at {dist:.0f} cm is out of sight: walking round ({self.detour})")
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
        keep_off = (crowd >= CROWD_N or near < KEEP_R             # he steps back while he fires
                    or sum(1 for e in live if flat(e) < CC_BACK_R) >= CC_BACK_N)
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
        on_e = self._on_line(origin, dot, source, front or vis, now)
        if source == "laser" and on_e is None and self._ray_short(origin, dot, tgt):
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
            if source == "laser":
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
        if on:                                                   # the trigger on him: his health must fall (NOHIT_S)
            tid = on_e.get("ptr", on_e.get("slot"))
            if self.fire_track is None or self.fire_track[0] != tid:
                self.fire_track = [tid, now, on_e.get("hp") or 0, now]
            self.fire_track[3] = now
        keys = {"zl"} | self._yaw(yaw_err) | self._pitch(pitch_err) | trig | set(back)
        self._aimctx = {"target": (on_e or tgt).get("ptr", (on_e or tgt).get("slot")), "dist": dist,
                        "yaw_err": yaw_err, "source": source, "where": dot_on(dot, foot) if source == "laser" else None}
        where = self._aimctx["where"]
        self.stats["aim"] = (f"d {dist:.0f} yaw {math.degrees(yaw_err):+.1f} pitch {math.degrees(pitch_err):+.1f} "
                             f"on {where or ('line' if on else '-')} via {source} keys {','.join(sorted(keys))}")
        return self._go("fire" if on else "aim", "aim", {"hold": tuple(sorted(keys))},
                        (f"on a zombie at {dist:.0f} cm ({source})" if on else
                         f"steering {math.degrees(yaw_err):+.0f} deg to him ({source})") + (", stepping back" if back else ""))

    # --- line of sight ---------------------------------------------------------------------------------------------
    def is_blocked(self, e, now) -> bool:
        """Out of sight: blocked within BLOCK_S and not within BLOCK_MIN_R of him (one that close is always fought)."""
        if self.blocked.get(e.get("ptr", e.get("slot")), -1e9) <= now:
            return False
        me = self._ppos
        return me is None or math.hypot(e["pos"][0] - me[0], e["pos"][2] - me[2]) >= BLOCK_MIN_R

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
        close = [e for e in live if flat(e) <= CC_R and abs(bearing(e)) <= CC_CONE]
        if not close:
            return None
        e = min(close, key=flat)
        d, err = flat(e), bearing(e)
        self._gun_down()
        if d < MELEE_R and abs(err) <= CC_ATTACK_CONE and now - self.melee_at >= CC_KICK_GAP_S:
            self.melee_at = now
            self.stats["melee"] += 1
            self.stats["cc_kicks"] += 1
            return self._go("crowd", "cc_kick", {"tap": "zr"}, f"one at {d:.0f} cm: a kick (crowd control)")
        if abs(err) <= CC_ATTACK_CONE and now - self.qshot_at >= CC_QSHOT_GAP_S:
            self.qshot_at = now
            self.stats["quick_shots"] += 1
            self.stats["cc_quick_shots"] += 1
            self.qshot_release = True
            self.cc_shot = (e.get("ptr", e.get("slot")), now,
                            {z.get("ptr", z.get("slot")): z.get("hp") or 0 for z in live if flat(z) <= CC_R})
            return self._go("crowd", "cc_quick_shot", {"hold": ("zl", "zr")},
                            f"one at {d:.0f} cm: quick shot (crowd control)")
        if abs(err) > CC_ATTACK_CONE:                            # on the flank: the camera to him
            return self._go("crowd", "cc_turn", {"hold": self._turn(err)},
                            f"one at {d:.0f} cm on the flank ({math.degrees(err):+.0f} deg): turning")
        return self._go("crowd", "cc_space", {"hold": ("ldown",)}, f"one at {d:.0f} cm: stepping back between attacks")

    # --- remote bombs ----------------------------------------------------------------------------------------------
    def _bomb(self, p, live, flat, yaw, snap, now) -> dict | None:
        """Remote bombs (BOMBS): at a stand (BOMB_STAND_N within BOMB_STAND_R) or in a new section (BOMB_SECTION_CM from
        the last bomb), one goes out toward them; it goes off once BOMB_BLAST_N stand on it with him clear of it, or
        after BOMB_HOLD_S. None: nothing to do with bombs this tick (the fight goes on)."""
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
            if not on_him and me >= self.book.safe and (on >= BOMB_BLAST_N or out_s >= BOMB_HOLD_S or coming):
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
        if self.bomb_phase in ("equip", "face", "aim") and live and (
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
        if near < BOMB_ROOM_R or sum(1 for e in live if flat(e) < BOMB_CROWD_R) >= BOMB_CROWD_N:
            return None                                          # it lands at his feet: not among them
        stand = sum(1 for e in live if flat(e) <= BOMB_STAND_R) >= BOMB_STAND_N
        section = near <= BOMB_STAND_R and (self.bomb_from is None or
                                            math.hypot(px - self.bomb_from[0], pz - self.bomb_from[1]) >= BOMB_SECTION_CM)
        if not (stand or section):
            return None
        self.bomb_why = "a stand" if stand else "a new section"
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
        err = wrap(heading(at[0] - px, at[1] - pz) - yaw)
        keys = ("ldown",) + ((self.detour,) if now < self.bomb_side_until else ()) + self._turn(err, TURN_TOL)
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
                return self._go("bomb", tag, {"tap": "ddown"}, "the item wheel to the remote bomb")
            return self._go("bomb", tag, {"hold": ()}, "the item wheel steps")
        if self.bomb_phase == "equip":
            self.bomb_phase, self.bomb_phase_at = "face", now
        if self.bomb_phase == "face":
            px, _, pz = p["pos"]
            group = [e for e in live if math.hypot(e["pos"][0] - px, e["pos"][2] - pz) <= BOMB_STAND_R] or live
            cx = sum(e["pos"][0] for e in group) / len(group)
            cz = sum(e["pos"][2] for e in group) / len(group)
            err = wrap(heading(cx - px, cz - pz) - yaw)
            if abs(err) > BOMB_FACE and now - self.bomb_phase_at < BOMB_FACE_S:
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
                      "bomb_det_holds", "bomb_kicks", "bomb_hits_taken", "unsafe_trigger_blocks", "tablet_dying_presses",
                      "tablet_dying_taken")         + AIM_COUNTERS + tuple("t_" + d for d in DOINGS)

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
        return Bot(stats=stats, clock=clock, learn_dir=learn_dir)

    def prompt_keys(self, button) -> list:
        return [tuple(str(button).split("+"))]

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "max_combo": snap.get("max_combo"),
                "mercenaries_phase": snap.get("mercenaries_phase"), "mode": "no_mercy"}


DRIVER = RE6Switch
