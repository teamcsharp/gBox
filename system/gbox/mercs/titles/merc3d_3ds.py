"""Title: Resident Evil: The Mercenaries 3D (3DS; the catalog's game 0ed22ae742e1b56b, the EUR image CTR-P-ABMP, title
0004000000038B00, .code sha256 85a34c86...821be) in RetroArch's citra_libretro core. Guest virtual addresses, read through
Citra's own page table in the RetroArch process (gbox.citra_memory, hooked into RetroArchAdapter.read_memory).

Measured live on the Spark 2026-10-27 (docs/research/merc3d-ram.md), names from the game's own MT DTIs and properties:

    sArea    [0x8BE7A4]  the area stack: +0x3818 depth, +0x3820 the areas (aGame, aMerceArea, then the screen's: aMerceTitle,
                         aMerceMain, a stage aS####, aMerceResult). An area's +0x1C is its cFlowStateManager (vtable
                         0x87FBCC): +0x18 the states, +0x1C how many, +0x20 the current one, +0x24 the previous one. The
                         state object's class names the screen (cMerceTitlePressStartState, cMerceMainMissionSelectState,
                         cMerceStageMainState, cMerceStageYouAreDeadState ...).
    sPlayer  [0x8D5898]  +0x20 the first node of its unit list; a node's +0x10 is the unit (uPl< Chris > ...): +0x40 pos (x,
                         y up, z; cm), +0x50 rotation quaternion (heading = 2 atan2(qy, qw), 0 = +z, positive toward +x),
                         +0xCC4 f32 vitality, +0xCCC f32 its maximum (uCharaBase mVitality / mMaxVitality: 1000 / 1000)
    sMission [0x8D58D0]  +0x18 mMissionID, +0x1C mCharaID, +0x64 f32 mElaps (seconds played), +0x68 f32 mLimitSec (seconds
                         left: 150 - elapsed in mission 1-1), +0x7C mScore, +0x80 mComboScore, +0x88 mComboCount, +0x94
                         f32 mComboSec (the combo window)

The class of any object: its vtable's slot 5 is getDTI (`ldr r0, [pc]; bx lr; .word DTI`), and the MtDTI's +4 is the name.

The way to a round, measured: the gore warning takes A, the Capcom logo passes by itself, PRESS START takes START (not A:
A there is ignored and the attract demo follows), and START opens the Mercenaries menus (aMerceMain) on the mission
select. A there starts the mission under the cursor (mission 1-1, the tutorial, plays Chris only and skips the
character select). Time up ends a mission in cMerceStageFailedState when its objective is not met.
"""
from __future__ import annotations

import math
import struct
import time

from ..driver import Driver

TITLE_ID = "0004000000038B00"
MAP_ID = TITLE_ID                       # profiles/gamedata/0004000000038B00-ram.json
CODE_SIGNATURE = bytes.fromhex(        # the .code's first 64 bytes: what the loader puts at guest 0x100000
    "080000eb71041ceb4a041cebb3041ceb5b041ceb29401ceb39041ceb6e041ceb1e041ceb1b041cea14009fe514109fe50020a0e3"
    "010050e104208034fcffff3a")
S_AREA, S_PLAYER, S_ENEMY, S_MISSION, S_SAVE = 0x8BE7A4, 0x8D5898, 0x8D5948, 0x8D58D0, 0x8D5888
AREA_DEPTH, AREA_STACK, AREA_MAX = 0x3818, 0x3820, 8
AREA_FLOW, FLOW_VT = 0x1C, 0x87FBCC
FLOW_STATES, FLOW_COUNT, FLOW_CUR, FLOW_PREV = 0x18, 0x1C, 0x20, 0x24
# a unit-list node: {vtable 0x899630, +0x4 prev, +0x8 next, +0xC vtable, +0x10 the unit} (live 2026-10-27 on the i9: the
# player's node 0x8567154 held uPl< Chris > at +0x10; +0x14 is 0, so 0x14 left the bot with "no player")
SP_FIRST, NODE_NEXT, NODE_OWNER = 0x20, 0x8, 0x10
# sEnemy +0x1C: a unit list (first node +0x24, the sentinel +0x20 that the last node's link points back to); a node is
# {vtable 0x8995B8, +0x4 prev, +0x8 next, +0xC vtable, +0x10 the unit} (live 2026-10-27, mission 1-3)
SE_SENTINEL, SE_FIRST, EN_NODE_VT, EN_NODE_UNIT, MAX_ENEMIES = 0x20, 0x24, 0x8995B8, 0x10, 64
P_POS, P_ROT, P_VIT, P_VIT_MAX = 0x40, 0x50, 0xCC4, 0xCCC
M_MISSION, M_CHARA, M_ELAPSED, M_LEFT = 0x18, 0x1C, 0x64, 0x68
M_SCORE, M_COMBO_SCORE, M_COMBO, M_COMBO_T = 0x7C, 0x80, 0x88, 0x94
GETDTI_SLOT, GETDTI_STUB, DTI_NAME = 0x14, 0xE59F0000, 0x4
HEAP = (0x08000000, 0x20000000)         # heap + linear heap: where the game's objects live

# the screens by flow state (the class of the current state of the top area)
TITLE_STATES = {"cMerceTitleGoreWarningState": "gore_warning", "cMerceTitlePressStartState": "press_start",
                "cMerceTitleDemoState": "demo", "cMerceTitleMainMenuState": "title_menu",
                "cMerceTitleCapcomLogoState": "loading", "cMerceTitleSystemCheckState": "loading",
                "cMerceTitleInitState": "loading", "cMerceTitleMainState": "loading", "cMerceTitleFinalState": "loading",
                "cMerceTitleDummyState": "loading", "cMerceTitleOptionMainState": "options",
                "cMerceTitleSpecialState": "special"}
MAIN_STATES = {"cMerceMainMainState": "mercs_main", "cMerceMainMissionSelectState": "select_stage",
               "cMerceMainCharacterSelectState": "select_player", "cMerceMainDuoMenuState": "duo_menu",
               "cMerceMainRecordState": "records", "cMerceMainInitState": "loading",
               "cMerceMainAutoSaveState": "saving", "cMerceMainFinalState": "loading"}
STAGE_STATES = {"cMerceStageInitState": "loading", "cMerceStageStartState": "loading", "cMerceStageMainState": "playing",
                "cMerceStageEndState": "results", "cMerceStageFailedState": "results",
                "cMerceStageYouAreDeadState": "dead", "cMerceStageFinalState": "loading"}
# The select screens' GUI (the flow state's +0x8): uGUI_MissionSelectSub lists the levels (LV.1-LV.5) and, once A opened
# one, its missions as tabs; uGUI_CharacterSelectSub the roster (live 2026-10-27, both screens shown).
STATE_GUI = 0x8
MS_LEVEL, MS_OPEN, MS_LEVELS, MS_TAB, MS_TABS = 0x328, 0x32C, 0x330, 0x334, 0x338
CS_CURSOR = 0x188
BOOT_KEY = "a"                          # the gore warning: the first screen RAM may not name yet
# The Mercenaries main menu (cMerceMainMainState): R opens the mission select, L the character select, START launches
# the mission sMission names; B there autosaves and leaves for the title, so it is never pressed on that screen.
STEPS = {"gore_warning": "a", "press_start": "start", "demo": "start", "title_menu": "a", "select_player": "a",
         "duo_menu": "b", "records": "b", "options": "b", "special": "b",
         "results": "a"}                    # the result screens after a round: A through them, back to the main menu
MENU_HANDOFF = ("results", "mercs_main", "select_stage", "select_player", "dead")
LEVELS = 5                              # LV.1-LV.5 in the select (the sixth, EX, is not in this list)
CHARACTERS: tuple = ()                  # the roster's order is read from the character select next
RELOAD_KEEP = ("PICK",)


class _Pick:
    """This menu visit's draws, kept until a round starts: a random open level, then a random mission tab in it (the
    tab count is known once the level is open), and whether the main menu still has to visit the mission select and
    the character select before START."""

    def __init__(self, rng=None):
        import random
        self.rng = rng or random.Random()
        self.reset()

    def reset(self) -> None:
        self.level = self.tab = None
        self.mission_done = self.chara_done = False

    def level_for(self, open_levels: int) -> int:
        if self.level is None or not 0 <= self.level < max(1, open_levels):
            self.level = self.rng.randrange(max(1, min(open_levels, LEVELS)))
        return self.level

    def tab_for(self, tabs: int) -> int:
        if self.tab is None or not 0 <= self.tab < tabs:
            self.tab = self.rng.randrange(tabs)
        return self.tab


PICK = _Pick()


def _u32(m, a) -> int:
    return struct.unpack("<I", m.rd(a, 4))[0]


def ptr_ok(p) -> bool:
    return isinstance(p, int) and HEAP[0] <= p < HEAP[1] and not p & 3


_NAMES: dict = {}


def class_name(m, obj) -> str | None:
    """The MT class of an object, from its vtable's getDTI (cached per vtable); None when it isn't an MT object."""
    try:
        vt = _u32(m, obj)
        if vt in _NAMES:
            return _NAMES[vt]
        stub = _u32(m, vt + GETDTI_SLOT)
        if _u32(m, stub) != GETDTI_STUB:
            return None
        name = m.rd(_u32(m, _u32(m, stub + 8) + DTI_NAME), 64).split(b"\0", 1)[0].decode("latin-1")
    except (ValueError, OSError, RuntimeError, struct.error):
        return None
    if name.isprintable() and name:
        _NAMES[vt] = name
        return name
    return None


def areas(m) -> list[tuple[int, str | None]]:
    """The area stack, bottom first: [(area, its class)]."""
    sa = _u32(m, S_AREA)
    if not ptr_ok(sa):
        return []
    depth = _u32(m, sa + AREA_DEPTH)
    if not 0 < depth <= AREA_MAX:
        return []
    out = []
    for a in struct.unpack(f"<{depth}I", m.rd(sa + AREA_STACK, 4 * depth)):
        if ptr_ok(a):
            out.append((a, class_name(m, a)))
    return out


def flow_state(m, area: int) -> tuple[str | None, int | None, int | None]:
    """(the current state's class, its index, the previous index) of an area's flow state machine."""
    f = area + AREA_FLOW
    if _u32(m, f) != FLOW_VT:
        return None, None, None
    arr, n, cur, prev = struct.unpack("<4I", m.rd(f + FLOW_STATES, 16))
    if not ptr_ok(arr) or not 0 < n <= 32 or cur >= n:
        return None, cur, prev
    st = _u32(m, arr + 4 * cur)
    return (class_name(m, st) if ptr_ok(st) else None), cur, prev


def player_unit(m) -> int | None:
    sp = _u32(m, S_PLAYER)
    if not ptr_ok(sp):
        return None
    node = _u32(m, sp + SP_FIRST)
    if not ptr_ok(node):
        return None
    p = _u32(m, node + NODE_OWNER)
    return p if ptr_ok(p) else None


def heading_of(q) -> float:
    return 2.0 * math.atan2(q[1], q[3])


def mission(m) -> dict | None:
    sm = _u32(m, S_MISSION)
    if not ptr_ok(sm):
        return None
    head = m.rd(sm + M_MISSION, 8)
    raw = m.rd(sm + M_ELAPSED, M_COMBO_T + 4 - M_ELAPSED)
    at = lambda off, fmt: struct.unpack_from(fmt, raw, off - M_ELAPSED)[0]
    return {"mission_id": struct.unpack_from("<i", head, 0)[0], "chara_id": struct.unpack_from("<i", head, 4)[0],
            "elapsed": round(at(M_ELAPSED, "<f"), 2), "timer": round(at(M_LEFT, "<f"), 2),
            "score": at(M_SCORE, "<i"), "combo_score": at(M_COMBO_SCORE, "<i"), "combo": at(M_COMBO, "<I"),
            "combo_timer": round(at(M_COMBO_T, "<f"), 2)}


def enemies(m) -> list[dict]:
    """The units on sEnemy's list: [{slot, ptr, pos, hp, hp_max, class}] (uCharaBase vitality, cm)."""
    se = _u32(m, S_ENEMY)
    if not ptr_ok(se):
        return []
    out, node, seen = [], _u32(m, se + SE_FIRST), set()
    while ptr_ok(node) and node != se + SE_SENTINEL and node not in seen and len(seen) < MAX_ENEMIES:
        seen.add(node)
        if _u32(m, node) != EN_NODE_VT:
            break
        u = _u32(m, node + EN_NODE_UNIT)
        if ptr_ok(u):
            try:
                pos = struct.unpack("<3f", m.rd(u + P_POS, 12))
                hp, = struct.unpack("<f", m.rd(u + P_VIT, 4))
                hp_max, = struct.unpack("<f", m.rd(u + P_VIT_MAX, 4))
            except (ValueError, OSError, RuntimeError, struct.error):
                pos = None
            if pos and all(math.isfinite(v) for v in pos):
                out.append({"slot": len(out), "ptr": u, "pos": pos, "hp": hp, "hp_max": hp_max,
                            "class": class_name(m, u)})
        node = _u32(m, node + NODE_NEXT)
    return out


def snapshot(m) -> dict:
    """The round from RAM: the player and the mission counters (None where a pointer is not)."""
    snap: dict = {"player": None, "enemies": [], "timer": None, "score": None, "kills": None, "combo": None,
                  "combo_timer": None, "elapsed": None}
    try:
        p = player_unit(m)
        if p:
            pos = struct.unpack("<3f", m.rd(p + P_POS, 12))
            rot = struct.unpack("<4f", m.rd(p + P_ROT, 16))
            hp, = struct.unpack("<f", m.rd(p + P_VIT, 4))
            hp_max, = struct.unpack("<f", m.rd(p + P_VIT_MAX, 4))
            snap["player"] = {"ptr": p, "pos": pos, "rot": heading_of(rot), "hp": hp, "hp_max": hp_max,
                              "class": class_name(m, p)}
        snap["enemies"] = enemies(m)
        mi = mission(m)
        if mi:
            snap.update({k: mi[k] for k in ("timer", "score", "combo", "combo_timer", "elapsed")},
                        mission_id=mi["mission_id"], chara_id=mi["chara_id"], combo_score=mi["combo_score"])
    except (ValueError, OSError, RuntimeError, struct.error):
        pass
    return snap


def screen(m, merc=None, now: float | None = None) -> dict:
    """The deployment's menus interface (gbox/mercs_bot.py): where the game is, from the top area's flow state."""
    out = {"where": "unknown", "cursor": None, "target": None}
    try:
        stack = areas(m)
    except (ValueError, OSError, RuntimeError, struct.error):
        return out
    if not stack:
        return out
    top, cls = stack[-1]
    try:
        state, index, prev = flow_state(m, top)
    except (ValueError, OSError, RuntimeError, struct.error):
        state, index, prev = None, None, None
    out.update(area=cls, state=state, state_index=index)
    if cls == "aMerceTitle":
        where = TITLE_STATES.get(state, "loading")
    elif cls == "aMerceMain":
        where = MAIN_STATES.get(state, "loading")
        try:
            out.update(_select(m, top, where))
        except (ValueError, OSError, RuntimeError, struct.error):
            pass
    elif cls == "aMerceResult":
        where = "results"
    elif state in STAGE_STATES:
        where = STAGE_STATES[state]
        if where == "playing" and (PICK.mission_done or PICK.chara_done):
            PICK.reset()                                # the round is up: the next selects draw anew
        if where == "playing":
            p = player_unit(m)
            try:
                if p and struct.unpack("<f", m.rd(p + P_VIT, 4))[0] <= 0:
                    where = "dead"
            except (ValueError, OSError, RuntimeError, struct.error):
                pass
    else:
        where = "loading" if state is None else "unknown"
    return out | {"where": where}


def _select(m, area: int, where: str) -> dict:
    """The selects' cursors and targets (and the mission sMission names now)."""
    out: dict = {}
    sm = _u32(m, S_MISSION)
    if ptr_ok(sm):
        out["mission_id"] = struct.unpack("<h", m.rd(sm + M_MISSION, 2))[0]
    if where not in ("select_stage", "select_player"):
        return out
    f = area + AREA_FLOW
    arr, n, cur = struct.unpack("<3I", m.rd(f + FLOW_STATES, 12))
    st = _u32(m, arr + 4 * cur)
    gui = _u32(m, st + STATE_GUI) if ptr_ok(st) else 0
    if not ptr_ok(gui):
        return out
    if where == "select_stage":
        level, open_, levels, tab, tabs = struct.unpack("<5i", m.rd(gui + MS_LEVEL, 20))
        if not 0 < open_ <= levels <= 8 or not 0 <= level < levels:
            return out
        out.update(level=level, open_levels=open_, levels=levels)
        if 0 < tabs <= 10 and 0 <= tab < tabs:          # a level is open: its missions as tabs
            out.update(inside=True, cursor=tab, target=PICK.tab_for(tabs), tabs=tabs)
        else:
            out.update(inside=False, cursor=level, target=PICK.level_for(open_))
    else:
        out["cursor"] = _u32(m, gui + CS_CURSOR)
    return out


def step(scr: dict) -> str | None:
    """One key toward the next round. Main menu: the mission select first (R), then the character select (L), then
    START. Mission select: the level cursor walks (down / up) to this visit's random open level, A opens it, the tab
    cursor walks (right / left) to a random mission, A picks it (back on the main menu)."""
    where = scr.get("where")
    if where == "mercs_main":
        if not PICK.mission_done:
            return "r"
        if not PICK.chara_done:
            return "l"
        return "start"
    if where == "select_stage":
        cursor, target = scr.get("cursor"), scr.get("target")
        if not isinstance(cursor, int) or not isinstance(target, int):
            return None
        if cursor == target:
            return "a"
        if scr.get("inside"):
            return "right" if cursor < target else "left"
        return "down" if cursor < target else "up"
    return STEPS.get(where)


def wandered(scr: dict) -> str | None:
    return None


def pressed(scr: dict, key: str) -> None:
    """The menus' memory of this visit: A on a mission tab picked the mission, A on the character select the
    character; a round's start (screen "playing") clears it for the next visit."""
    where = scr.get("where")
    if key == "a" and where == "select_stage" and scr.get("inside") and scr.get("cursor") == scr.get("target"):
        PICK.mission_done = True
    elif key == "a" and where == "select_player":
        PICK.chara_done = True


WARM_READY = ("press_start", "demo", "title_menu", "mercs_main", "select_stage", "select_player")


def warm_probe(m) -> dict:
    """gbox.mercs.warm_boot's boot observer (read only): a stable native screen where the warm pool may pause the boot:
    PRESS START (and its attract demo), the title menu, or the selects. The state object is the token."""
    out = {"ready": False, "screen": "unknown", "title": MAP_ID}
    scr = screen(m)
    where = scr.get("where")
    if where in WARM_READY:
        return out | {"ready": True, "screen": where, "token": (scr.get("area"), scr.get("state"), scr.get("state_index"))}
    return out | {"screen": where}


class Merc3D(Driver):
    map_id = MAP_ID
    solo_p1 = True                              # one pad: the bot alone on P1

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.stats: dict | None = None

    def snapshot(self, m) -> dict:
        return snapshot(m)

    def screen(self, m, snap: dict | None) -> str:
        where = screen(m).get("where")
        if where in ("playing", "dead", "results", "loading"):
            return where
        return "results" if where in MENU_HANDOFF else "loading"

    def mission_complete(self, m, snap) -> bool:
        """The mission ended on its own objective (cMerceStageEndState: "take down all hostiles" done, time left
        or not): a finished round for the engine and MercMode (mercmode.TITLES['merc3d'] native_complete)."""
        try:
            return screen(m).get("state") == "cMerceStageEndState"
        except (ValueError, OSError, RuntimeError, struct.error):
            return False

    def result_ready(self, snap, now) -> bool:
        return True                             # the end state is the tally: score and time are final there

    def menu_handoff(self, m, snap, where) -> bool:
        if where != "results":
            return False
        try:
            return screen(m).get("where") in MENU_HANDOFF
        except (ValueError, OSError, struct.error):
            return False

    round_counters = ("confirmed_shots", "point_blank_shots", "close_shots", "long_shots", "sky_corrections", "kites",
                      "los_blocks", "retargets")

    def brain(self, m, stats: dict, clock, learn_dir=None, nav=None):
        from .merc3d_bot import Bot
        self.stats = stats
        return Bot(stats=stats, clock=clock)

    def progress(self, snap: dict) -> dict:
        return {"timer": snap.get("timer"), "combo": snap.get("combo"), "score": snap.get("score"),
                "kills": snap.get("kills"), "elapsed": snap.get("elapsed")}


DRIVER = Merc3D
