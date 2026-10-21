"""The Mercenaries on any title and any PC: the deployment playbook and the boot / menu layer it shares with the
title playbooks (operator 2026-10-20: "a unified system able to be deployed on any instance of resident evil
mercenaries ... working across games, consoles, systems and titles"; "the system should be able to know what screen is
up on the game by the very game hook and ram / hex signature ... from the internal state machine of the game itself").

A title takes part when its RAM map (profiles/gamedata/<map id>-ram.json, docs/ram_maps.md) carries a "mercs" block.
This layer reads these keys of it (the engine's own keys sit beside them: gbox/mercs, docs/mercenaries_engine.md):
  menus      the module that names the title's screens from its own state machine in RAM, checked against code
             signatures (never vision): screen(m, merc=None) -> {"where", "cursor", "target", ...}, step(scr) -> pad
             key | None (the one press towards the next round), wandered(scr) -> why the run is off the Mercenaries
             path for good (a story game) | None. In a room, where is playing | results | dead | loading | story.
             RE4 GameCube: gbox.re4_menus.
  package    [[op, kwargs], ...] re_mods ops (the hack package): the code hooks go in once per boot at `jump_at`
  early_ops  ops of the package that go in at once (RAM only: the unlock bits that put the mode on the menu)
  jump_at    the menu screen where gBox's menu moment is saved, before any hook (gbox.jumpstate: a bot demo boots there)
The playbook (matches / setup / play, tools.PLAYBOOKS) takes a session whose RAM map has the block once the engine is
installed (gbox.mercs.engine.play_round); until then each title keeps its own playbook (re4_merc_bot), which uses
Boot below for its menus. It boots through the title's menus from RAM, saves the menu moment and applies the hooks at
`jump_at`, hands each round to the engine and comes back to the menus for the next. A story game, a lost round or
menus RAM can't name end the run with stats["hung"]: a bot demo is relaunched, into its menu moment. It runs in the
worker, beside the emulator; menus are polled every POLL_S, rounds run on the engine's frame-synced tick.
"""
from __future__ import annotations

import importlib
import time

MENU_LOST_S = 30.0          # out of a round and RAM can't name the screen this long: end the run
MENU_STUCK_S = 120.0        # out of a round and nothing in RAM moved this long: end the run
WAITS = ("attract",)        # screens that run their own length (movies): never "stuck"
POLL_S = 0.25               # how often the menus are read out of a round


class Navigator:
    """Closed loop over a menus module's step(): one press, then wait until RAM shows it took (the screen, its step or
    the cursor changed) or RETRY_S passed. A screen is pressed on only once RAM has shown it for STABLE_S: a moment
    between two screens is never acted on (live 2026-10-20: a round's first frames read as its results, the clock not
    set yet, and A went in). Menus need held presses (HOLD_S; the D-pad shorter: the repeat word would step twice) and
    a moment between them. stats gets screen / cursor / menu_presses / menu_last / ram_progress (the black watch
    trusts RAM: gbox.tools._black_watch)."""
    HOLD_S, DIR_HOLD_S, RETRY_S, SETTLE_S, STABLE_S = 0.3, 0.18, 1.2, 0.45, 0.5

    def __init__(self, send, step, sleep=time.sleep, clock=time.time, stats: dict | None = None):
        self.send, self.step, self.sleep, self.clock = send, step, sleep, clock
        self.stats = stats if stats is not None else {}
        self.stats.setdefault("menu_presses", 0)
        self.stats.setdefault("ram_progress", 0)
        self.last_key, self.last_at, self.last_sig, self.sig_at = None, float("-inf"), None, float("-inf")

    @staticmethod
    def sig(scr: dict):
        return (scr.get("where"), scr.get("title_step"), scr.get("title_sub"), scr.get("cursor"))

    def observe(self, scr: dict, now: float | None = None) -> None:
        sig = self.sig(scr)
        if sig != self.last_sig:
            self.stats["ram_progress"] = self.stats.get("ram_progress", 0) + 1
            self.last_sig, self.sig_at = sig, self.clock() if now is None else now
            self.last_key = None                            # the last press took: the next one may go at once
        self.stats["screen"] = scr.get("where")
        if scr.get("cursor") is not None:
            self.stats["cursor"] = scr["cursor"]

    def tick(self, scr: dict) -> str | None:
        """Observe the screen, and press its step when the last press took (or RETRY_S passed). Returns the key."""
        now = self.clock()
        self.observe(scr, now)
        key = self.step(scr)
        if key is None:
            return None
        if now - self.sig_at < self.STABLE_S:
            return None                                     # RAM has only just shown this screen: it may be passing
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


def save_menu_moment(ad, game) -> str | None:
    """gBox's own "menu moment" (operator: "one game session needs a maximum of two save states... one to get you back
    to the menu screen"): this game and build's jump state (gbox.jumpstate, Dolphin's demo slot 10: the operator's
    slots are never written), taken at the profile's `jump_at` screen before any hook. A bot-demo launch, and the
    relaunch of a frozen one, boots straight into it. Returns the file, or None (no jump states here)."""
    from . import jumpstate
    if ad is None or not game or jumpstate.strategy(ad) != "boot":
        return None
    p = jumpstate.path_for(ad, game)
    if jumpstate.booted(ad, game) and p.is_file():
        return p.name                                       # booted from it: it is the menu moment already
    jumpstate.save(ad, p)
    return p.name


class Boot:
    """Out of a round: the RAM-driven way to the next one over a title's menus module. At `jump_at`, once per boot:
    the menu moment, then the hooks (hooks stacked on hooks are untested: a live check froze in a stage load after a
    second set, 2026-10-20; a relaunch boots into the menu moment, before any hook, and applies them once again).
    tick() returns why the run must end (a story game, menus RAM can't name, nothing moving), else None."""

    def __init__(self, menus, m, send, sleep=time.sleep, clock=time.time, stats: dict | None = None, ad=None,
                 game=None, hooks=None, jump_at: str = "select_player"):
        self.menus, self.m, self.ad, self.game, self.clock = menus, m, ad, game, clock
        self.stats = stats if stats is not None else {}
        self.nav = Navigator(send, menus.step, sleep=sleep, clock=clock, stats=self.stats)
        self.hooks, self.jump_at = hooks, jump_at
        self.hooked, self.moment_tried = False, False
        self.lost_since, self.still_since, self.progress = None, None, None

    def tick(self, now: float | None = None, merc=None, scr: dict | None = None) -> str | None:
        now = self.clock() if now is None else now
        scr = scr if scr is not None else self.menus.screen(self.m, merc=merc)
        why = self.menus.wandered(scr)
        if why:
            return why
        if scr.get("where") == self.jump_at and not self.hooked:
            if not self.moment_tried:                       # before any hook: the state restores cleanly
                self.moment_tried = True
                try:
                    self.stats["menu_moment"] = save_menu_moment(self.ad, self.game) or "none (no jump states here)"
                except Exception as e:                      # noqa: BLE001 - no moment: the menus still work
                    self.stats["menu_moment"] = f"failed: {type(e).__name__}: {e}"[:160]
            if self.hooks is not None:
                failed = self.hooks() or []
                self.stats["hooks"] = "applied" + (f" ({len(failed)} failed)" if failed else "")
                if failed:
                    self.stats["hooks_failed"] = "; ".join(failed)[:300]
            self.hooked = True
        if scr.get("where") == "unknown":
            self.lost_since = self.lost_since or now
            if now - self.lost_since > MENU_LOST_S:
                return "RAM did not name the screen for %.0f s" % (now - self.lost_since)
        else:
            self.lost_since = None
        self.nav.tick(scr)
        if self.stats.get("ram_progress") != self.progress or scr.get("where") in WAITS:
            self.progress, self.still_since = self.stats.get("ram_progress"), now
        elif now - (self.still_since or now) > MENU_STUCK_S:
            return "nothing moved in RAM for %.0f s on %s" % (now - self.still_since, scr.get("where"))
        return None


# --- the deployment playbook --------------------------------------------------------------------------------------------
def profile_for(ad, g: dict | None) -> dict | None:
    """The title's Mercenaries profile: its RAM map's "mercs" block (+ map_id, platform), found by the session's game
    (catalog id, disc id) or the game's own memory (ram_map.detect); None for a title without one."""
    from . import ram_map
    rm = None
    try:
        rm = ram_map.find(g or {})
    except Exception:                                       # noqa: BLE001 - no map by the catalog: try the memory
        rm = None
    if rm is None and ad is not None:
        try:
            from .ram_reader import for_adapter
            mid = ram_map.detect(for_adapter(ad), (g or {}).get("platform", ""))
            rm = ram_map.find(mid) if mid else None
        except Exception:                                   # noqa: BLE001
            rm = None
    block = (getattr(rm, "spec", None) or {}).get("mercs") if rm is not None else None
    if not isinstance(block, dict) or not block.get("menus"):
        return None
    return dict(block, map_id=rm.id, platform=rm.platform)


def engine():
    """gbox.mercs.engine when it is installed, has play_round and says it is READY (the engine keeps READY False until
    a title plays at least as well through it as through its own playbook), else None."""
    try:
        from .mercs import engine as E
    except ImportError:
        return None
    return E if callable(getattr(E, "play_round", None)) and getattr(E, "READY", True) else None


def lessons_writer(map_id: str, run: str | None = None):
    """entry -> the title's run-lessons log (gbox.mercs.lessons.append), or None before the engine is installed."""
    try:
        from .mercs import lessons as L
    except ImportError:
        return None
    if not callable(getattr(L, "append", None)):
        return None
    return lambda entry: L.append(map_id, entry, run=run)


# --- coaching notes and improvement reports -> the run-lessons log ------------------------------------------------------
LESSON_KEYS = ("ts", "kind", "text", "session_id", "worker", "telemetry", "captures", "summary", "request_id", "note")


def lesson(kind: str, text: str, **kw) -> dict:
    """One entry of a title's run-lessons log in the schema agreed with the engine (LESSON_KEYS): kind "coach" (a live
    coaching note typed while the bot played: gbox.coaching) or "report" (a ⚑ report filed on a session of the title:
    POST /api/requests/issue); note is the coaching note's number."""
    e = dict.fromkeys(LESSON_KEYS)
    e.update({k: v for k, v in kw.items() if k in LESSON_KEYS})
    e.update(kind=kind, text=text, ts=e["ts"] if e["ts"] is not None else round(time.time(), 3))
    return e


def map_id_for(g: dict | None) -> str | None:
    """The RAM map id of a Mercenaries title (its map has a "mercs" block) by the game / session dict, else None."""
    from . import ram_map
    try:
        rm = ram_map.find(g or {})
    except Exception:                                       # noqa: BLE001 - a map that does not load: no lessons
        return None
    block = (getattr(rm, "spec", None) or {}).get("mercs") if rm is not None else None
    return rm.id if isinstance(block, dict) else None


def note_lesson(g: dict | None, entry: dict) -> bool:
    """Append a coaching note or a report on a Mercenaries title to its run-lessons log, which the engine reads before
    its next round. False when nothing was written (another title, or the engine's lessons module not installed);
    never raises: the note or report is filed either way."""
    try:
        mid = map_id_for(g)
        write = lessons_writer(mid) if mid else None
        if write is None:
            return False
        write(entry)
        return True
    except Exception:                                       # noqa: BLE001
        return False


def apply_ops(ad, ops) -> list[str]:
    """Run [[op, kwargs], ...] through re_mods in this process; returns the ones that failed."""
    from . import re_mods_tool as RM
    failed = []
    try:
        g = RM.RE4(ad)
    except Exception as e:                                  # noqa: BLE001 - this title has no re_mods: say so
        return [f"{op}: {e}" for op, _ in ops]
    for op, kw in ops:
        try:
            RM.run(ad, op, g=g, **dict(kw or {}))
        except Exception as e:                              # noqa: BLE001 - one failed mod never stops the run
            failed.append(f"{op}: {e}")
    return failed


def _memory(ad):
    """The session's RAM, read-only, with rd(addr, n): its own Dolphin's shared view, else the adapter's reads."""
    from .re4_merc_bot import memory
    return memory(ad)


def matches(ad, g: dict) -> bool:
    """Any title whose RAM map has a "mercs" block, once the engine is installed."""
    return engine() is not None and profile_for(ad, g) is not None


def setup(ad) -> list[str]:
    return []                                               # play() applies the profile's ops: it knows the game


def play(ad, send, stopped, stats: dict | None = None, game=None, sleep=time.sleep, clock=time.time, m=None,
         **_kw) -> dict:
    """Boot to a round from RAM, hand each round to the engine, back to the menus for the next; stats is filled
    live (screen, cursor, menu_presses, rounds, ram_progress, hooks, menu_moment; hung + wandered when it ends early)."""
    stats = stats if stats is not None else {}
    prof = profile_for(ad, game or {})
    if prof is None:
        raise ValueError("this title has no Mercenaries profile (a RAM map with a mercs block)")
    menus = importlib.import_module(prof["menus"])
    m = m or _memory(ad)
    E = engine()
    package = [tuple(x) for x in prof.get("package") or []]
    early = set(prof.get("early_ops") or [])
    if ad is not None and early:
        failed = apply_ops(ad, [x for x in package if x[0] in early])
        if failed:
            stats["early_failed"] = "; ".join(failed)[:300]
    boot = Boot(menus, m, send, sleep=sleep, clock=clock, stats=stats, ad=ad, game=game,
                hooks=(lambda: apply_ops(ad, [x for x in package if x[0] not in early])) if ad is not None else None,
                jump_at=prof.get("jump_at") or "select_player")
    run = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    lessons = lessons_writer(prof["map_id"], run)
    stats.setdefault("rounds", 0)
    stats["profile"] = prof["map_id"]
    fresh = True                                            # a round counts once, however often the engine hands back
    while not stopped():
        scr = menus.screen(m)
        if scr.get("where") == "playing" and E is not None:
            if fresh:
                stats["rounds"] += 1
                fresh = False
            out = E.play_round(prof, m, send, stopped, stats, lessons)
            if out == "lost":
                stats.update(hung=True, wandered="the round was lost (no player, or black too long)")
                break
            if out == "stopped":
                break
            sleep(POLL_S)                                   # never a busy loop on an engine that hands straight back
            continue
        fresh = True
        why = boot.tick(clock(), scr=scr)
        if why:
            stats.update(hung=True, wandered=why)
            break
        sleep(POLL_S)
    return stats
