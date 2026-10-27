"""Resident Evil 4 (GameCube G4BE08): where the game is between boot and a Mercenaries round, read from RAM, and the one
pad press that moves it on towards the next round (operator 2026-10-20: "why cant Ghidra see the game is on the title
screen?"). The RE4 playbook (gbox/re4_merc_bot.py) asks screen() every tick out of a round and presses what step() says;
it never presses blind, so it never selects New Game, Load, Options, Assignment Ada or EXIT.

Found by static analysis of main.dol (capstone over the disc's own main.dol; docs/re4-menus.md has the routines) and
checked against a MEM1 taken from a Dolphin save state at Select Player:

  the scheduler (scheduler.cpp) keeps its tasks at TASKS, TASK_STRIDE bytes each: +0x4 state, +0x18 an OSThread
  (+0x18+0x4 its saved sp, +0x18+0x304 its stack base), +0x33C the task's entry. While the title and its menus run,
  task 0 is title.cpp's task (entry TITLE_ENTRY); outside them (the game's own rooms) it is another task.
  The title task loops `routine[TW[0]](TW)` with the routine table (TITLE_ROUTINES) in r30 and its work area TW (0x60
  bytes on the heap) in r31; whenever it waits for the next frame those two registers are saved next to each other on
  its stack, so TW is the word after TITLE_ROUTINES there (tw()).

  TW+0x00 u8   title routine: 0 init, 1-4 boot (memory card, logos, the warning, PRESS START: START skips them),
               5 the main menu, 6 the extra games (Assignment Ada / The Mercenaries menus), 7 a game starting
  TW+0x01 u8   the routine's step
  TW+0x24 u32  main menu: items;  TW+0x28 u32 main menu: cursor (routine 5 step 1: up / down, A or START picks)
               with the extras unlocked (pSys+4 & 0x40000000) the items are START (a new game), ASSIGNMENT ADA, THE MERCENARIES,
               LOAD, OPTIONS (codes 6, 2, 3, 4, 5 in 0x801621f0), without them START, LOAD, OPTIONS (1, 4, 5)
  TW+0x54 u8   The Mercenaries' menu (routine 6 step 4): 0 GAME START, 1 EXIT (up / down)
  TW+0x55 u8   Select Player (routine 6 step 8): 0 Leon, 1 Ada, 2 Krauser, 3 HUNK, 4 Wesker (the portraits left to right; left / right, wraps)
  TW+0x56 u8   Select Stage (routine 6 step 0xC): a 2 x 2 grid, 0 the Village (up / down 2, left / right 1)
  pG+0x54      bit 0x40000000: the extra game chosen is The Mercenaries (bit 0x80000000: Assignment Ada)

Outside the title task the game is in a room (pG+0x20 = 3; 4 changing rooms): room 0x04RR is a Mercenaries stage
(re4_merc_bot.in_mercenaries), any other room is the story, which the bot never plays (wandered()).
"""
from __future__ import annotations

import struct
import time

PG = 0x802B2280                    # pG: the GLOBAL work area
PSYS = 0x802B2284                  # pSys: the system save (unlock bits at +4)
TASKS, TASK_STRIDE = 0x80289F50, 0x348
TASK_ENTRY, TASK_THREAD = 0x33C, 0x18
THREAD_SP, THREAD_STACK_BASE = 0x4, 0x304
TITLE_ENTRY = 0x80161738           # title.cpp's task
TITLE_ROUTINES = 0x8020CC10        # its routine table (r30 beside TW in r31)
STACK_SCAN = 0x400                 # bytes of the title task's stack searched for TW (the frames above its wait)
TW_SIZE = 0x60
TW_ROUTINE, TW_SUB = 0x0, 0x1
TW_MENU_COUNT, TW_MENU_CURSOR = 0x24, 0x28
TW_EXTRA_CURSOR, TW_PLAYER_CURSOR, TW_STAGE_CURSOR = 0x54, 0x55, 0x56
G_ROUTINE, G_ROOM, G_HP, G_EXTRA = 0x20, 0x4FA8, 0x4FB0, 0x54
EXTRA_ADA, EXTRA_MERC = 0x80000000, 0x40000000
UNLOCKED = 0x40000000              # pSys+4: the extra games are on the main menu
MENU_EXTRAS = (6, 2, 3, 4, 5)      # main menu codes by cursor, extras unlocked
MENU_PLAIN = (1, 4, 5)
MENU_NAMES = {1: "START", 2: "ASSIGNMENT ADA", 3: "THE MERCENARIES", 4: "LOAD", 5: "OPTIONS", 6: "START"}   # START = a new game
MERC_CODE = 3
PLAYERS = ("Leon", "Ada", "Krauser", "HUNK", "Wesker")       # the portraits, left to right (live frame)
STAGES = ("Village", "Castle", "Base", "Waterworld")
STAGE_ROOMS = (0x400, 0x402, 0x403, 0x404)   # each stage's room (pG+0x4FA8): r400 Village, r402 Castle (Garrador),
                                             # r403 Base (J.J.), r404 Waterworld (the disc's omake01 / omake02 ESLs)
LEON, VILLAGE = 0, 0

# title routine 5 (main menu) steps, from the routine's switch (0x801627C4) and what a pick leads to
MENU_STEPS = {0: "main_menu_setup", 1: "main_menu", 2: "new_game", 3: "story_starting", 4: "options",
              5: "attract", 6: "attract", 7: "load", 8: "press_start"}
MOVIE_PLAYING = 2                  # routine 5 steps 5 / 6 (the menu idled into an attract movie): TW+2 while it plays
# title routine 6 (the extra games) steps (0x801633BC)
EXTRA_STEPS = {0: "extra_loading", 1: "extra_loading", 2: "extra_loading", 3: "extra_menu_setup", 4: "extra_menu",
               5: "extra_leaving", 6: "players_setup", 7: "players_setup", 8: "select_player", 9: "players_leaving",
               10: "stages_setup", 11: "stages_setup", 12: "select_stage", 13: "starting"}


class Mem:
    """read(addr, n) -> bytes over any reader the bot uses (ShmMem / OwnShm / AdMem: rd; a plain function)."""

    def __init__(self, m):
        self.m = m

    def rd(self, a: int, n: int) -> bytes:
        if hasattr(self.m, "rd"):
            return self.m.rd(a, n)
        return bytes(self.m(a, n))


def _ok(p: int) -> bool:
    return 0x80000000 <= p < 0x81800000


def _u32(m, a: int) -> int:
    return struct.unpack(">I", m.rd(a, 4))[0]


# Code signatures (main.dol words, read live from RAM): the title task's entry, the menu handlers and its routine table.
# The screen is named only when RAM holds this exact code, so another build or a patched title never gets misread.
SIGNATURES = {
    TITLE_ENTRY: bytes.fromhex("9421fff07c0802a6bfc1000890010014"),          # the title task: stwu / mflr / stmw / stw
    0x801621F0: bytes.fromhex("9421fff07c0802a693e1000c90010014"),           # the main menu handler
    0x801633BC: bytes.fromhex("9421ffc07c0802a6bf61002c90010044"),           # the extra games' routine
    0x801644C0: bytes.fromhex("9421ff487c0802a6be810088900100bc"),           # Select Stage's cursor
    TITLE_ROUTINES: bytes.fromhex("801617b48016192c80161b4c80161c8480161da0801627c4801633bc80164934"),
}


def signed(m) -> bool:
    """RAM holds the main.dol code this module was built from (SIGNATURES). A match is remembered on the memory view;
    a miss is asked again next time (the code is not in RAM yet while the disc boots)."""
    if getattr(m, "_re4_signed", False):
        return True
    try:
        ok = all(m.rd(a, len(sig)) == sig for a, sig in SIGNATURES.items())
    except Exception:                                        # noqa: BLE001 - unreadable now: ask again next time
        return False
    if ok:
        try:
            m._re4_signed = True
        except AttributeError:                               # a view that takes no attributes: checked every time
            pass
    return ok


def in_room(m) -> bool:
    """The game runs a room (pG+0x20 = 3, or 4 changing rooms): a round can be on. While a stage loads (0-2) the
    Mercenaries clock still reads the last round's value, so the clock alone can't tell (live 2026-10-20: 9.8 s left
    from the round before showed through the Village's load)."""
    pg = _u32(m, PG)
    return _ok(pg) and m.rd(pg + G_ROUTINE, 1)[0] in (3, 4)


def title_running(m) -> bool:
    """Task 0 is title.cpp's (the title and its menus); else the game's own loop runs a room."""
    return _u32(m, TASKS + TASK_ENTRY) == TITLE_ENTRY


def tw(m) -> int | None:
    """The title task's work area, or None when task 0 is not the title's (the game's rooms) or it can't be found."""
    t = TASKS
    if not title_running(m):
        return None
    th = t + TASK_THREAD
    sp, base = _u32(m, th + THREAD_SP), _u32(m, th + THREAD_STACK_BASE)
    if not (_ok(sp) and _ok(base) and sp < base):
        return None
    lo = max(sp, base - STACK_SCAN)
    data = m.rd(lo, base - lo)
    words = struct.unpack(f">{len(data) // 4}I", data[:len(data) // 4 * 4])
    for i in range(len(words) - 1):
        if words[i] == TITLE_ROUTINES and _ok(words[i + 1]):
            p = words[i + 1]
            if m.rd(p, 1)[0] <= 7:
                return p
    return None


ROOM_WHERE = ("playing", "results", "dead", "loading", "story")   # where, in one of the game's rooms


def screen(m, merc=None) -> dict:
    """Where RE4 is now: {"where", "cursor", "target", "title_routine", "title_step", "tw", "items", ...}. Cheap enough
    to ask every tick in a round (a few words; the title task's stack only while the title runs).
    where, out of a room: title (boot, logos, PRESS START) | attract | main_menu | main_menu_setup | new_game |
    story_starting | options | load | press_start | extra_* (loading, menu setup, leaving) | extra_menu (The
    Mercenaries: GAME START / EXIT) | ada_* | players_setup | select_player | players_leaving | stages_setup |
    select_stage | starting | unknown;
    in a room (ROOM_WHERE): playing (a Mercenaries round) | results (the clock at 0) | dead ("You Are Dead") |
    loading (a stage still loading) | story (any other room: wandered off).
    merc: re4_merc_bot.snapshot over the same memory (read here when not given)."""
    m = Mem(m) if not hasattr(m, "rd") else m
    out = {"where": "unknown", "cursor": None, "target": None}
    if not signed(m):                                        # not the code these addresses come from: name nothing
        out["error"] = "RAM does not hold the G4BE08 main.dol code this reader was built from (re4_menus.SIGNATURES)"
        return out
    try:
        pg = _u32(m, PG)
        if _ok(pg):
            g = m.rd(pg + G_ROUTINE, 4)
            out.update(game_routine=g[0], room=struct.unpack(">H", m.rd(pg + G_ROOM, 2))[0],
                       extra=_u32(m, pg + G_EXTRA))
        title = title_running(m)
        w = tw(m) if title else None
    except Exception as e:                                   # noqa: BLE001 - a read during a load: next tick
        out["error"] = f"{type(e).__name__}: {e}"[:120]
        return out
    if w is None:
        if title or out.get("game_routine") is None:         # the title runs but its work area isn't on its stack
            return out
        if merc is None:
            try:
                from .re4_merc_bot import snapshot
                merc = snapshot(m)
            except Exception as e:                           # noqa: BLE001 - a read during a load: next tick
                out["error"] = f"{type(e).__name__}: {e}"[:120]
                return out
        out.update(_game(merc, out))
        return out
    t = m.rd(w, TW_SIZE)
    routine, step = t[TW_ROUTINE], t[TW_SUB]
    out.update(tw=w, title_routine=routine, title_step=step, title_sub=t[2])
    if routine <= 4:
        out["where"] = "title"
    elif routine == 5:
        out["where"] = MENU_STEPS.get(step, f"main_menu_{step}")
        count, cursor = struct.unpack_from(">II", t, TW_MENU_COUNT)
        unlocked = None
        try:
            ps = _u32(m, PSYS)
            unlocked = bool(_u32(m, ps + 4) & UNLOCKED) if _ok(ps) else None
        except Exception:                                    # noqa: BLE001
            pass
        codes = MENU_EXTRAS if count == len(MENU_EXTRAS) else MENU_PLAIN if count == len(MENU_PLAIN) else ()
        out.update(cursor=cursor, count=count, unlocked=unlocked,
                   items=[MENU_NAMES.get(c, str(c)) for c in codes],
                   target=codes.index(MERC_CODE) if MERC_CODE in codes else None)
    elif routine == 6:
        extra = out.get("extra") or 0
        where = EXTRA_STEPS.get(step, f"extra_{step}")
        if extra & EXTRA_ADA and not extra & EXTRA_MERC:
            where = "ada_" + where.replace("extra_", "")    # Assignment Ada: never played, backed out of
        out["where"] = where
        if step == 4:
            out.update(cursor=t[TW_EXTRA_CURSOR], target=0, items=["GAME START", "EXIT"])
        elif step == 8:
            out.update(cursor=t[TW_PLAYER_CURSOR], target=LEON, items=list(PLAYERS))
        elif step == 12:
            out.update(cursor=t[TW_STAGE_CURSOR], target=VILLAGE, items=list(STAGES))
    elif routine == 7:
        out["where"] = "starting"
    return out


def _game(merc, base) -> dict:
    """In a room: a Mercenaries round (playing), its results (the clock at 0), "You Are Dead", a stage still loading,
    or the story (wandered off)."""
    s = merc
    room = s.get("room")
    if room is None:
        return {"where": "loading"}
    if (room >> 8) != 4:
        return {"where": "story" if base.get("game_routine") in (3, 4) and room != 0x120 else "loading"}
    if base.get("game_routine") not in (None, 3, 4):        # the stage is still loading (routines 0-2): the clock
        return {"where": "loading"}                         # reads the last round's there, not this round's (live
                                                            # 2026-10-20: A was pressed while the Village loaded)
    if s.get("hp") is not None and s["hp"] <= 0 and s.get("player"):
        return {"where": "dead"}
    if s.get("timer", 0) <= 0:
        return {"where": "results"}
    return {"where": "playing" if s.get("player") else "loading"}


def wandered(scr: dict) -> str | None:
    """Why this screen is off the Mercenaries path for good (the bot ends the run: a bot demo is relaunched), or None."""
    if scr.get("where") == "story_starting":
        return "a story game was being started from the main menu"
    if scr.get("where") == "story":
        return f"in the story (room {scr.get('room', 0):#05x}), not The Mercenaries"
    return None


# the pad: menus read the D-pad (the stick moves Leon); A / START pick, B backs out
DPAD = {"up": "dup", "down": "ddown", "left": "dleft", "right": "dright"}


def step(scr: dict) -> str | None:
    """The press that moves this screen towards the next Mercenaries round (a gBox pad key), or None: wait."""
    where, cur, target = scr.get("where"), scr.get("cursor"), scr.get("target")
    if where == "title":
        return "start"                                      # logos, the warning, PRESS START: all skip with START
    if where == "attract":                                  # the menu idled into a movie: START skips it while it plays
        return "start" if scr.get("title_sub") == MOVIE_PLAYING else None   # (never as it ends: the menu would pick)
    if where == "press_start":                              # back from a game: START returns to the extras' menu,
        return "start" if (scr.get("extra") or 0) & EXTRA_MERC else None    # anything else would start a game
    if where == "main_menu":
        if target is None:                                  # no THE MERCENARIES on this menu (built before the unlock
            return None                                     # bits went in): wait for it to idle back to the title
                                                            # and be built again with them; never pick on it
        if cur is None:
            return None
        return "a" if cur == target else DPAD["down"] if cur < target else DPAD["up"]
    if where in ("new_game", "options", "load") or where.startswith("ada_"):
        return "b"                                          # the wrong menu: back out, never pick in it
    if where == "extra_menu":
        return "a" if cur == 0 else DPAD["up"]              # GAME START, never EXIT
    if where == "select_player":
        target = LEON if target is None else target
        if type(cur) is not int or type(target) is not int or not 0 <= cur < 5 or not 0 <= target < 5:
            return None
        if cur == target:
            return "a"
        return DPAD['right'] if (target-cur)%5<=2 else DPAD['left']
    if where == "select_stage":
        target = VILLAGE if target is None else target
        if type(cur) is not int or type(target) is not int or not 0 <= cur < 4 or not 0 <= target < 4:
            return None
        if cur == target:
            return "a"
        return DPAD['down' if target&2 else 'up'] if (cur^target)&2 \
            else DPAD['right' if target&1 else 'left']
    if where in ("results", "dead"):
        return "a"                                          # Results: next; "You Are Dead": Continue Yes
    return None


# The next round someone asked for (the MercMode DJ queue, re_mods mercs_select): adapter key -> {"player", "stage"}
# (indexes into PLAYERS / STAGES, None = random). RandomSelections takes it at the next Select Player / Select Stage.
REQUESTS: dict = {}
# The request the round now playing fulfils (moved out of REQUESTS when that round starts, RandomSelections.round_up /
# the instant rounds' load): a death in it keeps Continue Yes (re4_merc_bot.Bot._continue_answer) - the DJ's round is
# replayed - until a round that is not the DJ's starts. Survives a bot hot reload like REQUESTS.
ASKED: dict = {}
RELOAD_KEEP = ("ASKED",)


def request(key, character=None, stage=None) -> dict:
    player = PLAYERS.index(character) if character in PLAYERS else None
    if character is not None and player is None:
        raise ValueError(f"character: {', '.join(PLAYERS)}")
    if stage is not None and (type(stage) is not int or not 0 <= stage < len(STAGES)):
        raise ValueError(f"stage: 0..{len(STAGES) - 1} ({', '.join(STAGES)})")
    REQUESTS[key] = {"player": player, "stage": stage}
    return {"character": PLAYERS[player] if player is not None else "random",
            "stage": STAGES[stage] if stage is not None else "random"}


class RandomSelections:
    """Per-run cursor targets: random each round, or the requested next round (REQUESTS[key]). No blind counting."""
    BOOT_KEY = 'start'
    wandered = staticmethod(wandered)

    def __init__(self,rng=None,key=None):
        import random
        self.rng=rng or random.Random()
        self.key=key
        self.player=self.stage=None
        self.previous_player=self.previous_stage=None
        self.where=None
        self.no_selected=False                   # "You Are Dead": No already highlighted (step pressed right)
        self.planned=None                        # the next round's targets (plan_next), {"player", "stage"}

    def plan_next(self,player=None,stage=None):
        """The next round's targets, taken at the next Select Player / Select Stage like a request (None = random)
        but without a request's Continue Yes: gbox.re4_merc_bot's instant rounds walk the menus to a stage and
        character the round-state library lacks, so it is captured there. A DJ request still comes first."""
        self.planned={'player':player,'stage':stage}

    def round_up(self,player=None,stage=None,keep_asked=False):
        """A round started. The playbook never asks screen() in a round, so this is where a DJ request taken at the
        selects is done with (it stayed in REQUESTS and replayed every round before: now it moves to ASKED for the round
        it started, whose deaths keep Continue Yes) and a plan is spent; player / stage: a round that started from a save
        state names its own (the next draw avoids them). keep_asked: the round is the DJ's still (a Continue Yes reload,
        an instant retry of the DJ's round); any other round ends the DJ's."""
        if self.key is not None and REQUESTS.get(self.key) and self.player is not None:
            ASKED[self.key]=REQUESTS.pop(self.key)
        elif self.key is not None and not keep_asked:
            ASKED.pop(self.key,None)
        self.planned=None
        player=self.player if player is None else player
        stage=self.stage if stage is None else stage
        if player is not None:self.previous_player=player
        if stage is not None:self.previous_stage=stage
        self.player=self.stage=None

    def screen(self,m,merc=None):
        out=screen(m,merc=merc)
        where=out.get('where')
        asked=REQUESTS.get(self.key) if self.key is not None else None
        planned=self.planned or {}
        if where=='select_player':
            if asked and asked.get('player') is not None:
                self.player=asked['player']
            elif self.player is None and planned.get('player') is not None:
                self.player=planned['player']
            if self.player is None:
                self.player=self.rng.choice([i for i in range(5) if i!=self.previous_player])
            out['target']=self.player
        elif where=='select_stage':
            if asked and asked.get('stage') is not None:
                self.stage=asked['stage']
            elif self.stage is None and planned.get('stage') is not None:
                self.stage=planned['stage']
            if self.stage is None:
                self.stage=self.rng.choice([i for i in range(4) if i!=self.previous_stage])
            out['target']=self.stage
        elif where=='playing' and asked and self.player is not None:
            REQUESTS.pop(self.key,None)          # the requested round is up: later rounds are random again
            self.planned=None
        elif where in ('playing','results','dead'):
            if where=='playing':
                self.planned=None                # the planned round is up (or another one started): random again
            if self.player is not None:self.previous_player=self.player
            if self.stage is not None:self.previous_stage=self.stage
            self.player=self.stage=None
        if where!='dead':
            self.no_selected=False
        self.where=where
        return out

    def step(self,scr):
        """The module's step, except "You Are Dead": No (right, then A) instead of Continue Yes - Yes replays the stage
        with the same character, so every death kept him; No goes back through Select Player, where a different one is
        drawn (operator 2026-10-26: "why dont the character change between rounds? Stop picking the same character").
        A round someone asked for (REQUESTS) keeps Continue Yes."""
        if scr.get('where')=='dead' and not (self.key is not None and (REQUESTS.get(self.key) or ASKED.get(self.key))):
            if not self.no_selected:
                self.no_selected=True
                return DPAD['right']
            return 'a'
        return step(scr)


def Navigator(send, sleep=time.sleep, clock=time.time, stats: dict | None = None):
    """The closed-loop menu presser (gbox.mercs_bot.Navigator) over RE4's step()."""
    from .mercs_bot import Navigator as N
    return N(send, step, sleep=sleep, clock=clock, stats=stats)


def main(argv=None) -> int:
    """Read-only: print where a running RE4 is (python -m gbox.re4_menus [--pid PID] [--every S])."""
    import argparse
    import json
    from . import re4_merc_bot as R
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument("--pid", type=int, default=0, help="the Dolphin to read (default: the one running G4BE08)")
    ap.add_argument("--every", type=float, default=0.0, help="repeat every S seconds (Ctrl+C ends)")
    a = ap.parse_args(argv)
    if a.pid:
        from .ram_dump import ShmRam
        ram = ShmRam.find_pid(a.pid)
        if ram is None:
            raise SystemExit(f"no Dolphin MEM1 view in process {a.pid}")
        m = R.OwnShm(ram)
    else:
        m = R.ShmMem()
    while True:
        try:
            snap = R.snapshot(m)
        except Exception:                                    # noqa: BLE001
            snap = {}
        scr = screen(m, merc=snap)
        print(json.dumps({k: (hex(v) if k in ("tw", "extra") and isinstance(v, int) else v) for k, v in scr.items()}
                         | {"step": step(scr)}), flush=True)
        if not a.every:
            return 0
        time.sleep(a.every)


if __name__ == "__main__":
    raise SystemExit(main())
