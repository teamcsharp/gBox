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
               with the extras unlocked (pSys+4 & 0x40000000) the items are NEW GAME, ASSIGNMENT ADA, THE MERCENARIES,
               LOAD, OPTIONS (codes 6, 2, 3, 4, 5 in 0x801621f0), without them NEW GAME, LOAD, OPTIONS (1, 4, 5)
  TW+0x54 u8   The Mercenaries' menu (routine 6 step 4): 0 GAME START, 1 EXIT (up / down)
  TW+0x55 u8   Select Player (routine 6 step 8): 0 Leon, 1 Ada, 2 HUNK, 3 Krauser, 4 Wesker (left / right, wraps)
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
MENU_NAMES = {1: "NEW GAME", 2: "ASSIGNMENT ADA", 3: "THE MERCENARIES", 4: "LOAD", 5: "OPTIONS", 6: "NEW GAME"}
MERC_CODE = 3
PLAYERS = ("Leon", "Ada", "HUNK", "Krauser", "Wesker")
STAGES = ("Village", "Castle", "Base", "Waterworld")
LEON, VILLAGE = 0, 0

# title routine 5 (main menu) steps, from the routine's switch (0x801627C4) and what a pick leads to
MENU_STEPS = {0: "main_menu_setup", 1: "main_menu", 2: "new_game", 3: "story_starting", 4: "options", 7: "load"}
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


def screen(m, merc=None) -> dict:
    """Where RE4 is now: {"where", "cursor", "target", "title_routine", "title_step", "tw", "items", ...}.
    where: title (boot, logos, PRESS START) | main_menu | main_menu_setup | new_game | story_starting | options | load |
    extra_* (loading, menu setup, leaving) | extra_menu (The Mercenaries: GAME START / EXIT) | ada_menu | players_setup |
    select_player | players_leaving | stages_setup | select_stage | starting | game (a room; merc() tells which) |
    unknown. merc: re4_merc_bot.snapshot over the same memory, for "game" (round / results / dead / story)."""
    m = Mem(m) if not hasattr(m, "rd") else m
    out = {"where": "unknown", "cursor": None, "target": None}
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
        out["where"] = "game"
        if merc is not None:
            out.update(_game(merc, out))
        return out
    t = m.rd(w, TW_SIZE)
    routine, step = t[TW_ROUTINE], t[TW_SUB]
    out.update(tw=w, title_routine=routine, title_step=step)
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
    """In a room: a Mercenaries round, its results (the clock at 0), "You Are Dead", or the story (wandered off)."""
    s = merc
    room = s.get("room")
    if room is None:
        return {"phase": "loading"}
    if (room >> 8) != 4:
        return {"phase": "story" if base.get("game_routine") in (3, 4) and room != 0x120 else "loading"}
    if s.get("hp") is not None and s["hp"] <= 0 and s.get("player"):
        return {"phase": "dead"}
    if s.get("timer", 0) <= 0:
        return {"phase": "results"}
    return {"phase": "round" if s.get("player") else "loading"}


def wandered(scr: dict) -> str | None:
    """Why this screen is off the Mercenaries path for good (the bot ends the run: a bot demo is relaunched), or None."""
    if scr.get("where") == "story_starting":
        return "a story game was being started from the main menu"
    if scr.get("where") == "game" and scr.get("phase") == "story":
        return f"in the story (room {scr.get('room', 0):#05x}), not The Mercenaries"
    return None


# the pad: menus read the D-pad (the stick moves Leon); A / START pick, B backs out
DPAD = {"up": "dup", "down": "ddown", "left": "dleft", "right": "dright"}


def step(scr: dict) -> str | None:
    """The press that moves this screen towards the next Mercenaries round (a gBox pad key), or None: wait."""
    where, cur, target = scr.get("where"), scr.get("cursor"), scr.get("target")
    if where == "title":
        return "start"                                      # logos, the warning, PRESS START: all skip with START
    if where == "main_menu":
        if target is None:                                  # no THE MERCENARIES on this menu (extras locked): back
            return "b"
        if cur is None:
            return None
        return "a" if cur == target else DPAD["down"] if cur < target else DPAD["up"]
    if where in ("new_game", "options", "load") or where.startswith("ada_"):
        return "b"                                          # the wrong menu: back out, never pick in it
    if where == "extra_menu":
        return "a" if cur == 0 else DPAD["up"]              # GAME START, never EXIT
    if where == "select_player":
        if cur == LEON:
            return "a"
        return DPAD["left"] if cur in (1, 2) else DPAD["right"]    # wraps: Krauser / Wesker -> right to Leon
    if where == "select_stage":
        if cur == VILLAGE:
            return "a"
        return DPAD["up"] if cur in (2, 3) else DPAD["left"]
    if where == "game":
        phase = scr.get("phase")
        if phase in ("results", "dead"):
            return "a"                                      # Results: next; "You Are Dead": Continue Yes
    return None


class Navigator:
    """Closed loop over screen(): one press, then wait until RAM shows it took (the screen, step or cursor changed) or
    RETRY_S passed; menus need held presses (HOLD_S) and a moment between them. stats gets screen / cursor / presses /
    ram_progress (the black watch trusts RAM: gbox.tools._black_watch)."""
    HOLD_S, DIR_HOLD_S, RETRY_S, SETTLE_S = 0.3, 0.18, 1.2, 0.45

    def __init__(self, send, sleep=time.sleep, clock=time.time, stats: dict | None = None):
        self.send, self.sleep, self.clock = send, sleep, clock
        self.stats = stats if stats is not None else {}
        self.stats.setdefault("menu_presses", 0)
        self.stats.setdefault("ram_progress", 0)
        self.last_key, self.last_at, self.last_sig = None, float("-inf"), None

    def sig(self, scr: dict):
        return (scr.get("where"), scr.get("title_step"), scr.get("cursor"), scr.get("phase"))

    def observe(self, scr: dict) -> None:
        sig = self.sig(scr)
        if sig != self.last_sig:
            self.stats["ram_progress"] = self.stats.get("ram_progress", 0) + 1
            self.last_sig = sig
            self.last_key = None                            # the last press took: the next one may go at once
        self.stats["screen"] = scr.get("where") + (f":{scr['phase']}" if scr.get("phase") else "")
        if scr.get("cursor") is not None:
            self.stats["cursor"] = scr["cursor"]

    def tick(self, scr: dict) -> str | None:
        """Observe the screen, and press its step when the last press took (or RETRY_S passed). Returns the key."""
        self.observe(scr)
        key = step(scr)
        now = self.clock()
        if key is None:
            return None
        if self.last_key is not None and now - self.last_at < self.RETRY_S:
            return None                                     # the last press has not shown in RAM yet
        if now - self.last_at < self.SETTLE_S:
            return None
        hold = self.DIR_HOLD_S if key.startswith("d") else self.HOLD_S
        self.send([{"key": key, "down": True}])
        self.sleep(hold)
        self.send([{"key": key, "down": False}])
        self.last_key, self.last_at = key, self.clock()
        self.stats["menu_presses"] = self.stats.get("menu_presses", 0) + 1
        self.stats["menu_last"] = f"{scr.get('where')}: {key}"
        return key


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
