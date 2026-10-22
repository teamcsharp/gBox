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
BOOT_PRESS_S = 3.0          # a title's BOOT_KEY goes in this often while RAM can't name the screen (a cold boot's dialogs)
BOOT_LOST_S = 600.0         # before the boot's first named screen: an emulator's first run builds its shader caches and
                            # a PS3 game installs its data (RPCS3 on JAYBUILTFINALE, 2026-10-22: "Precompiling shader
                            # interpreter variants" > 30 s, then "Installing RESIDENT EVIL 5 GOLD EDITION" for minutes)
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
                 game=None, hooks=None, jump_at: str = "select_player", round_hooks=None):
        self.menus, self.m, self.ad, self.game, self.clock = menus, m, ad, game, clock
        self.stats = stats if stats is not None else {}
        self.nav = Navigator(send, menus.step, sleep=sleep, clock=clock, stats=self.stats)
        self.hooks, self.jump_at, self.round_hooks = hooks, jump_at, round_hooks
        self.hooked, self.moment_tried, self.at_jump = False, False, False
        self.lost_since, self.still_since, self.progress = None, None, None
        self.boot_pressed, self.named = float("-inf"), False

    def tick(self, now: float | None = None, merc=None, scr: dict | None = None) -> str | None:
        now = self.clock() if now is None else now
        scr = scr if scr is not None else self.menus.screen(self.m, merc=merc)
        why = self.menus.wandered(scr)
        if why:
            return why
        if scr.get("where") == self.jump_at and not self.at_jump and self.round_hooks is not None:
            # every visit (a new round's selects): the profile's round_ops (the per-round randomizer, the loadout)
            failed = self.round_hooks() or []
            self.stats["rounds_hooked"] = self.stats.get("rounds_hooked", 0) + 1
            if failed:
                self.stats["round_hooks_failed"] = "; ".join(failed)[:300]
        self.at_jump = scr.get("where") == self.jump_at
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
            if now - self.lost_since > (MENU_LOST_S if self.named else BOOT_LOST_S):
                return "RAM did not name the screen for %.0f s" % (now - self.lost_since)
            # a cold boot (no menu moment on this PC yet: RPCS3 states don't move between machines) opens on dialogs
            # the title's units don't name, e.g. RE5's "HDD access indicator" notice (live JAYBUILTFINALE 2026-10-22:
            # no press, hung at 30 s, relaunched into the same notice, a loop): the title's BOOT_KEY confirms them
            key = getattr(self.menus, "BOOT_KEY", None)
            if key and now - self.lost_since >= BOOT_PRESS_S and now - self.boot_pressed >= BOOT_PRESS_S:
                self.nav.send([{"key": key, "down": True}])
                self.nav.sleep(Navigator.HOLD_S)
                self.nav.send([{"key": key, "down": False}])
                self.boot_pressed = self.clock()
                self.stats["boot_presses"] = self.stats.get("boot_presses", 0) + 1
        else:
            self.lost_since, self.named = None, True
        self.nav.tick(scr)
        if self.stats.get("ram_progress") != self.progress or scr.get("where") in WAITS:
            self.progress, self.still_since = self.stats.get("ram_progress"), now
        elif now - (self.still_since or now) > (MENU_STUCK_S if self.named else BOOT_LOST_S):
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


def title_engine(prof: dict | None):
    """The engine for this title: engine() once READY; before that, for a title whose mercs block says "ready": true
    (built on the engine, no playbook of its own to beat: RE5), the installed engine anyway."""
    E = engine()
    if E is not None or (prof or {}).get("ready") is not True:
        return E
    try:
        from .mercs import engine as E2
    except ImportError:
        return None
    return E2 if callable(getattr(E2, "play_round", None)) else None


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


def apply_ops(ad, ops, prof: dict | None = None, stats: dict | None = None) -> list[str]:
    """Run [[op, kwargs], ...] through the title's mods tool in this process (re_mods for RE4 on GameCube / Wii,
    re5_mods for RE5 on PS3, by the profile's platform); returns the ones that failed. An op's result that carries
    "telemetry" (what the randomizer picked) lands in stats["cheats"] for the operator."""
    if (prof or {}).get("platform") == "ps3":
        from . import re5_mods_tool as RM
        make = RM.RE5
    else:
        from . import re_mods_tool as RM
        make = RM.RE4
    failed = []
    try:
        g = make(ad)
    except Exception as e:                                  # noqa: BLE001 - this title has no mods tool: say so
        return [f"{op}: {e}" for op, _ in ops]
    for op, kw in ops:
        try:
            res = RM.run(ad, op, g=g, **dict(kw or {}))
            if stats is not None and isinstance(res, dict) and res.get("telemetry"):
                stats["cheats"] = res["telemetry"]
        except Exception as e:                              # noqa: BLE001 - one failed mod never stops the run
            failed.append(f"{op}: {e}")
    return failed


class ProcMem:
    """A PS3 guest's RAM through one open /proc/<pid>/mem (RPCS3 on Linux): rd(addr, n) without opening the file per
    read (a Mercenaries tick reads a few hundred small fields)."""

    def __init__(self, pid: int, base: int):
        self.f, self.base = open(f"/proc/{pid}/mem", "rb", 0), base

    def rd(self, addr: int, n: int) -> bytes:
        self.f.seek(self.base + addr)
        data = self.f.read(n)
        if len(data) != n:
            raise ValueError(f"guest address {addr:#x} is not mapped")
        return data


def _memory(ad):
    """The session's RAM, read-only, with rd(addr, n): its own Dolphin's shared view, an RPCS3's /proc/<pid>/mem held
    open, else the adapter's reads."""
    guest = getattr(ad, "_guest", None)
    if callable(guest) and getattr(ad, "MEM", "").startswith("/proc/"):
        try:
            pid, base = guest()
            m = ProcMem(pid, base)
            m.adapter = ad
            return m
        except Exception:                                   # noqa: BLE001 - still booting: the adapter's reads
            pass
    from .re4_merc_bot import memory
    m = memory(ad)
    m.adapter = ad
    return m


def matches(ad, g: dict) -> bool:
    """Any title whose RAM map has a "mercs" block, once the engine is installed (READY, or the title "ready")."""
    prof = profile_for(ad, g)
    return prof is not None and title_engine(prof) is not None


def setup(ad) -> list[str]:
    return []                                               # play() applies the profile's ops: it knows the game


def tactical_publisher(sink, prof: dict):
    """The tactical map's publisher for this title (gbox.mercs.tactical) over the worker's sink, or None (no sink)."""
    if sink is None:
        return None
    from .mercs import tactical as T
    return T.Publisher(sink, prof["map_id"], prof.get("units") or T.units_for(prof["map_id"]))


def play(ad, send, stopped, stats: dict | None = None, game=None, sleep=time.sleep, clock=time.time, m=None,
         tactical=None, **_kw) -> dict:
    """Boot to a round from RAM, hand each round to the engine, back to the menus for the next; stats is filled
    live (screen, cursor, menu_presses, rounds, ram_progress, hooks, menu_moment; hung + wandered when it ends early).
    tactical: the tactical map's sink (gbox.mercs.tactical.HttpSink): each round's frames, the screen between rounds."""
    stats = stats if stats is not None else {}
    prof = profile_for(ad, game or {})
    if prof is None:
        raise ValueError("this title has no Mercenaries profile (a RAM map with a mercs block)")
    menus = importlib.import_module(prof["menus"])
    m = m or _memory(ad)
    # Keep reads fast while title-specific, verified maintenance writes use the owning adapter.
    if ad is not None:
        m.adapter = ad
    E = title_engine(prof)
    package = [tuple(x) for x in prof.get("package") or []]
    early = set(prof.get("early_ops") or [])
    if ad is not None and early:
        failed = apply_ops(ad, [x for x in package if x[0] in early], prof)
        if failed:
            stats["early_failed"] = "; ".join(failed)[:300]
    round_ops = [tuple(x) for x in prof.get("round_ops") or []]
    boot = Boot(menus, m, send, sleep=sleep, clock=clock, stats=stats, ad=ad, game=game,
                hooks=(lambda: apply_ops(ad, [x for x in package if x[0] not in early], prof)) if ad is not None else None,
                jump_at=prof.get("jump_at") or "select_player",
                round_hooks=(lambda: apply_ops(ad, round_ops, prof, stats)) if ad is not None and round_ops else None)
    run = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    lessons = lessons_writer(prof["map_id"], run)
    stats.setdefault("rounds", 0)
    stats["profile"] = prof["map_id"]
    pub = tactical_publisher(tactical, prof)
    damage_outbox = None
    if callable(getattr(tactical, "damage", None)):
        from pathlib import Path
        import hashlib
        import uuid
        from .mercs import damage as damage_reports
        root = Path(ad.config.data_dir) / "player-damage-outbox" / hashlib.sha256(tactical.sid.encode()).hexdigest()
        damage_outbox = damage_reports.Outbox(root, tactical.sid, tactical, stats)
        if damage_outbox.capacity_blocked:
            stats.update(player_damage_status="backpressure", stopped_reason="pending reserved damage receipt must be delivered before play")
            damage_outbox.close()
            if pub is not None:
                pub.close()
            return stats
        damage_run = uuid.uuid4().hex
        stats["player_damage_run"] = damage_run
    fresh = True                                            # a round counts once, however often the engine hands back
    playing_ops = [tuple(x) for x in prof.get("playing_ops") or []]
    playing_initialized = False
    try:
        while not stopped():
            scr = menus.screen(m)
            if scr.get("where") == "playing" and E is not None:
                if not playing_initialized and ad is not None and playing_ops:
                    failed = apply_ops(ad, playing_ops, prof, stats)
                    stats["playing_hooks"] = "applied" if not failed else "; ".join(failed)[:300]
                    playing_initialized = not failed
                if fresh:
                    stats["rounds"] += 1
                    fresh = False
                options = {"tactical": pub} if pub else {}
                if damage_outbox is not None:
                    options["damage"] = damage_reports.Observer(damage_outbox.emit, damage_run, prof["map_id"], stats)
                out = E.play_round(prof, m, send, stopped, stats, lessons, **options)
                if out == "evidence_backpressure":
                    stats["stopped_reason"] = "damage evidence could not be retained; pending events were not evicted"
                    break
                if out == "lost":
                    stats.update(hung=True, wandered="the round was lost (no player, or black too long)")
                    break
                if out == "stopped":
                    break
                sleep(POLL_S)                               # never a busy loop on an engine that hands straight back
                continue
            fresh = True
            if pub is not None:
                pub.idle(scr.get("where"))                  # the map says where the game is between rounds
            why = boot.tick(clock(), scr=scr)
            if why:
                stats.update(hung=True, wandered=why)
                break
            sleep(POLL_S)
    finally:
        if damage_outbox is not None:
            damage_outbox.close()
        if pub is not None:
            pub.close()
    return stats
