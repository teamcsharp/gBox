"""RE4 (Switch) Mercenaries playbook: get to a round from the screen, start it, fight it from RAM, report its end.

This title has a verified **round entry** - three A presses once the stage draws - and a frame classifier for its menus
(`re4_switch_screens`). The round itself is read from RAM by the driver (`re4_switch.snapshot`): the round clock is
found live by `re4_switch.ClockFinder` (a float in the module's bss that falls by the wall time), and the player and the
Ganados come from the unit census once their class and offsets are measured (`re4_switch.PLAYER_CLASS` / `U_POS`).

What it does, and what it says it does:

* menus: the driver's walk, one press at a time, steering Select Player / Select Stage to MercMode's DJ pick
  (`game.launch.mercmode.selection`, `re4_switch.request`); a still picture before a stage runs the back-out escape;
* in a round with the player in RAM: `re4_switch.Bot` fights (turn, raise, fire through the operator's gates, the combo
  clock, crowd fire, locate by the map, never stand) and its keys go in as holds and taps;
* in a round without the player in RAM: the blunt frame-only cadence (advance, sweep the aim, fire) - `stats["fight"]`
  says which one ran;
* at the round's end it posts a MercMode round boundary (`round_boundary`, tools._start_playbook) with a RAM witness:
  the clock read 0 after it was seen counting (results), or the player's health read 0 (death). Nothing is claimed from
  the frame alone: without the clock the round ends by MercMode's no-progress cut, and `stats` says why.

The one thing it must get right is not mistaking a menu for a round: the classifier is the same one the driver uses, and
`unknown` only counts as in-round after a stage screen has been seen (`re4_switch`'s own rule).
"""
import time
import uuid

from .mercs.titles import re4_switch as driver
from .mercs.titles import re4_switch_screens as screens

GAME_IDS = ("270a15eb98dab4d7",)          # Resident Evil 4 (Switch) [UPDATE 1.0.2], the catalog entry MercMode uses
ROUND_ENTRY_PRESSES = 3
# The trapped-menu escape, one press per still picture: back out of the save list, then move the prompt's cursor off
# "No" and confirm it. A picture that changes resets the sequence, so a wrong guess costs one press, not the run.
# A trapped menu is left by pressing back, and only back: "a" on the save list *loads a save*, which returns to the same
# prompt one screen later. Four backs clear the "Cancel loading?" prompt, the list and the LOAD menu, and the walk then
# starts again from whatever named screen it lands on.
STALL_ESCAPE = ("b", "b", "b", "b")                    # measured: three A presses after the stage draws start the clock
IDLE_TICKS_BEFORE_ACTION = 2
# A cursor that moves on a named menu is the walk working, not a stall. Measured 2026-11-09 on lilspark (session
# ae02be4bd9974915-03aacc170e184c15, frames every 1 s): the main-menu walk from LOAD to EXTRAS takes four cursor steps at
# its 3 s gap, the escape fired 13 s after the menu appeared, exactly as the cursor reached EXTRAS, and its "b" put the
# game back on the title - the same loop three times in a row, so no round was ever reached. A change of cursor (or of
# a select screen's steering count) now restarts the stall clock, at most CURSOR_PROGRESS_MAX times per named screen: a
# cursor that keeps moving without the screen ever changing is still a stall.
CURSOR_PROGRESS_MAX = 12
MENU_POLL_S = 0.2                       # the menus are read this often (re4_switch.Pace says when a press may go in)
UNKNOWN_ROUND_S = 6.0                   # after a stage pick, an unnamed picture this long is the round (no black, no HUD)
FIGHT_TICK_S = 0.05                     # the RAM fight's loop
FRAME_EVERY = 5                         # ... which classifies a frame every this many ticks (the menus coming back)
TALLY_S = 1.0                           # the clock at 0 this long: the round is over (its results are up)
RESULTS_MIN_CLOCK_S = 60.0              # ... and only a clock seen this high first is the round's (it opens at 120.0)
MAP_ID = driver.MAP_ID


def matches(ad, g: dict) -> bool:
    """Switch RE4 only: the Mercenaries edition, whatever screen it is on."""
    if (g or {}).get("platform") != "switch":
        return False
    if str((g or {}).get("game_id") or "") in GAME_IDS:
        return True
    return "Resident Evil 4" in str((g or {}).get("title") or "")


def setup(ad) -> dict:
    """Nothing to install: RE4 Switch Mercenaries needs no unlock and this playbook applies no mods.

    Mods arrive as a LayeredFS build on the launch (`mod=`), which is where every other title's mods live too.
    """
    return {"hacks": [], "note": "screen-only until the units are mapped: round entry and movement; the fight reads "
                                 "RAM once re4_switch.PLAYER_CLASS / U_POS are measured"}


def _press(send, key: str, hold_s: float = 0.08, sleep=time.sleep) -> None:
    send([{"key": key, "down": True}])
    sleep(hold_s)
    send([{"key": key, "down": False}])


class Keys:
    """A bot's {"hold": keys, "tap": key} as pad events: a held key goes down once and up when the bot lets it go, a
    tap is down + up before the holds (the trigger is never held: re4_switch.Bot)."""

    def __init__(self, send):
        self.send, self.down = send, set()

    def apply(self, act: dict) -> None:
        want = set((act or {}).get("hold") or ())
        rows = [{"key": k, "down": False} for k in sorted(self.down - want)]
        rows += [{"key": k, "down": True} for k in sorted(want - self.down)]
        tap = (act or {}).get("tap")
        if tap:                                              # after the holds: the aim is down before the trigger
            rows += [{"key": tap, "down": True}, {"key": tap, "down": False}]
        if rows:
            self.send(rows)
        self.down = want

    def release(self) -> None:
        if self.down:
            self.send([{"key": k, "down": False} for k in sorted(self.down)])
        self.down = set()


def _memory(ad):
    """The session's RAM, read-only (gbox.mercs_bot._memory: Citron's /proc/<pid>/mem held open), or None."""
    if ad is None or not callable(getattr(ad, "_guest", None)):
        return None
    try:
        from .mercs_bot import _memory as memory
        return memory(ad)
    except Exception:                                        # noqa: BLE001 - no RAM: the frame-only playbook
        return None


def selection_of(game) -> dict | None:
    """MercMode's DJ pick for this launch (screensaver: game.launch.mercmode.selection), RE4's only."""
    merc = ((game or {}).get("launch") or {}).get("mercmode")
    pick = merc.get("selection") if isinstance(merc, dict) else None
    return pick if isinstance(pick, dict) and pick.get("title", "re4") == "re4" else None


class Round:
    """One round's RAM evidence and its boundary: the clock seen counting, the player seen, then the terminal witness
    (results: the clock at 0 for TALLY_S; dead: the player's health at 0). One boundary per round id."""

    def __init__(self, now: float):
        self.id = uuid.uuid4().hex
        self.started = now
        self.clock_counting = False
        self.last_timer = None
        self.high = None                        # (value, wall time) of the first reading >= RESULTS_MIN_CLOCK_S
        self.zero_since = None
        self.player_seen = False
        self.hud_seen = False
        self.posted = None

    def observe(self, snap: dict, now: float) -> None:
        timer = snap.get("timer")
        if isinstance(timer, (int, float)) and not isinstance(timer, bool):
            if self.last_timer is not None and 0 < timer < self.last_timer:
                self.clock_counting = True
            if self.high is None and timer >= RESULTS_MIN_CLOCK_S:
                self.high = (float(timer), now)
            self.last_timer = timer
            self.zero_since = (self.zero_since or now) if timer <= 0 else None
        p = snap.get("player")
        if isinstance(p, dict) and p.get("pos") is not None and p.get("hp") is not None and p["hp"] > 0:
            self.player_seen = True

    def clock_ran_out(self, now: float) -> bool:
        """The round's own clock ran down to 0: seen at RESULTS_MIN_CLOCK_S or more, then at 0 for TALLY_S, with at
        least the wall time between that the fastest emulation allows (a short countdown picked by mistake fails)."""
        if not (self.clock_counting and self.high is not None and self.zero_since is not None):
            return False
        value, at = self.high
        return now - self.zero_since >= TALLY_S and self.zero_since - at >= value / driver.CLOCK_RATE[1] * 0.9

    def terminal(self, snap: dict, now: float) -> dict | None:
        """The native witness of the round's end, or None while it runs."""
        if self.posted is not None:
            return None
        p = snap.get("player") or {}
        if self.player_seen and p.get("hp") is not None and p["hp"] <= 0:
            return {"screen": "dead", "hp": p["hp"]}
        if self.clock_ran_out(now):
            return {"screen": "results", "tally_ready": True, "timer": 0, "clock_high": round(self.high[0], 2)}
        return None


def _boundary(rnd: Round, end: dict, snap: dict, stats: dict, at: float) -> dict:
    pick = driver.SELECTION
    character = driver.CHARACTERS[pick.get("player") or 0]
    stage = driver.STAGES[pick.get("stage") or 0]
    witness = {**end, "playing_observed": rnd.clock_counting or rnd.player_seen,
               "player_verified": rnd.player_seen, "clock_verified": rnd.clock_counting,
               "kills": stats.get("kills_seen"), "kills_source": stats.get("kills_source"),
               "clock_addr": hex(snap["clock_addr"]) if isinstance(snap.get("clock_addr"), int) else None,
               "hud_seen": rnd.hud_seen, "character_source": "requested", "stage_source": "requested"}
    return {"round_id": rnd.id, "at": at, "map_id": MAP_ID, "role": "solo_p1", "source": "native_terminal_reader",
            "mode": "mercenaries", "stage": stage, "character": character, "witness": witness}


def play(ad, send, stopped, sleep=time.sleep, stats: dict | None = None, *, clock=time.time,
         max_seconds: float | None = None, still_s: float = 12.0, game=None, round_boundary=None, m=None,
         **_) -> dict:
    """Walk the menus to a round, start it, fight it, and keep going until `stopped()`.

    Returns a dict of what it did. `stats` (when given) is filled live for the watch panel.

    `still_s` is how long the picture may stay on one named screen (with no cursor progress) before the back-out escape
    is pressed. A stray confirm lands in LOAD and the save list then holds the walk for as long as nothing acts on it
    (measured on 2026-11-07: identical frames for 260 s); the escape is what gets the walk out.
    `game` carries MercMode's DJ pick; `round_boundary(body, stats)` posts a round's end (tools._start_playbook passes
    it); `m` is the session's RAM (default: the adapter's, read-only).
    """
    stats = stats if stats is not None else {}
    stats.update({"screen": None, "presses": 0, "rounds": 0, "started": clock(), "stage_seen": False,
                  "story_recoveries": 0, "stall_steps": 0, "fight": None, "boundaries_posted": 0})
    last_action, last_sig, cursor_steps = clock(), None, 0
    reader = screens.Reader()
    pick = selection_of(game)
    try:
        driver.begin_run(selection=pick)
        if pick:
            stats["queued_selection"] = (f"{driver.CHARACTERS[driver.SELECTION['player'] or 0]} / "
                                         f"{driver.STAGES[driver.SELECTION['stage'] or 0]}")
    except ValueError as exc:
        driver.begin_run()
        stats["queued_selection_error"] = str(exc)[:160]
    m = m if m is not None else _memory(ad)
    stats["ram"] = m is not None
    keys = Keys(send)
    bot = driver.Bot(stats=stats, clock=clock) if m is not None else None
    started = clock()
    last_step = 0.0
    ticks = 0
    in_round = False
    rnd: Round | None = None
    pace = driver.Pace()
    unknown_since = None
    seen_menu, prev_where = False, None             # title_returns: the title again after a menu (an idle return or
                                                    # a back press), the stat that tells a walk loop on the live panel

    screen = {"where": None}
    while not stopped():
        if max_seconds is not None and clock() - started > max_seconds:
            break
        ticks += 1
        # the RAM fight reads the frame every FRAME_EVERY ticks only (the round's own state is in RAM; the frame is
        # there to see the menus come back), everything else every tick
        if not (in_round and stats.get("fight") == "ram" and ticks % FRAME_EVERY):
            try:
                frame = ad.get_frame()
            except Exception:                                # noqa: BLE001 - a missing frame is not a screen
                sleep(0.5)
                continue
            screen = reader.read(frame)
        where = screen.get("where")
        stats["screen"] = where
        sig = (where, screen.get("cursor"), screen.get("moved"))
        if where is not None and sig != last_sig:
            # a change of named screen is progress, and so is a cursor (or a select screen's steering) that moved on
            # the same one - CURSOR_PROGRESS_MAX times: a cursor moving forever without the screen changing is a stall
            same_screen = last_sig is not None and last_sig[0] == where
            cursor_steps = cursor_steps + 1 if same_screen else 0
            if not same_screen or cursor_steps <= CURSOR_PROGRESS_MAX:
                stats["stall_steps"] = 0
                last_action = clock()
            last_sig = sig
        # a still picture before a stage is a trapped menu, whatever the classifier calls it: the save list itself is
        # "unknown" once it darkens its background, and skipping those left the bot on "Cancel loading? Yes/No" with No
        # selected for minutes at mean 19.4 (2026-11-07). The escape is a fixed sequence, one press per failure to
        # change the picture, and it restarts as soon as the picture moves.
        if not stats["stage_seen"] and clock() - last_action > still_s:
            step = min(stats["stall_steps"], len(STALL_ESCAPE) - 1)
            _press(send, STALL_ESCAPE[step], sleep=sleep)
            stats["presses"] += 1
            stats["stall_steps"] += 1
            if step == 0:
                stats["story_recoveries"] += 1
            last_action = clock()
            sleep(0.6)
            continue
        stats["stage_seen"] = stats["stage_seen"] or where == "select_stage"

        # --- menus: the same route the driver walks, one press at a time
        if where not in ("unknown", "playing"):
            if in_round:
                keys.release()
            in_round = False
            target = (driver.EXTRAS_ROW if where == "main_menu"
                      else driver.MERCENARIES_ROW if where == "extras_menu" else None)
            scr = {**screen, "target": target, "reader": reader}
            pace.observe(scr, clock())
            if where == "title" and seen_menu:
                stats["title_returns"] = stats.get("title_returns", 0) + (prev_where != "title")
            if where == "dead_continue" and prev_where != "dead_continue":
                stats["deaths"] = stats.get("deaths", 0) + 1     # the walk answers Continue: Yes (re4_switch.step)
            seen_menu = seen_menu or where in driver.CURSOR_MENUS
            prev_where = where
            # moves on a short cadence once the last one showed; a confirm once its screen has settled (and, on a
            # cursor menu, two reads agree it is on the target); the driver's per-screen gap keeps a second A off a
            # screen that is fading out (it would land on the next screen's default row)
            if pace.ready(scr, clock()):
                key = driver.step(scr, clock())               # the driver's per-screen gaps on this run's clock
                if key:
                    _press(send, key, sleep=sleep)
                    driver.pressed(scr, key, clock())
                    pace.pressed(scr, key, clock())
                    stats["presses"] += 1
                    stats["menu_presses"] = stats.get("menu_presses", 0) + 1
                    last_step = clock()
            sleep(MENU_POLL_S)
            continue

        # --- unknown / the HUD: in the stage (the classifier cannot read a live round's picture, only its HUD)
        if not stats["stage_seen"] and where != "playing":
            sleep(0.4)
            continue                       # a screen nobody can classify before a stage: do not press into the dark
        unknown_since = (unknown_since or clock()) if where == "unknown" else None
        if not in_round and where == "unknown" \
                and getattr(reader, "intro_presses", 0) < getattr(reader, "INTRO_MAX_PRESSES", 0) \
                and clock() - unknown_since < UNKNOWN_ROUND_S:
            # the fade after the stage's confirm is not the round: the reader names the intro once the load's black
            # has shown (and the walk pages it), the HUD names the round; only an unnamed picture that lasts
            # UNKNOWN_ROUND_S (no black seen, no HUD read) is taken for the round
            sleep(MENU_POLL_S)
            continue
        if not in_round:
            in_round = True
            stats["rounds"] += 1
            stats.setdefault("walk_s", round(clock() - started, 1))     # the boot's walk to its first round
            rnd = Round(clock())
            if where != "playing":                           # the HUD is up: the clock already runs, no entry presses
                for _ in range(ROUND_ENTRY_PRESSES):
                    if stopped():
                        break
                    _press(send, "a", sleep=sleep)
                    stats["presses"] += 1
                    sleep(0.8)
                continue
        if where == "playing" and rnd is not None:
            rnd.hud_seen = True

        snap = _snapshot(m, stats) if m is not None else None
        if rnd is not None and snap is not None:
            rnd.observe(snap, clock())
            _report(rnd, snap, stats, clock(), round_boundary, keys)
        p = (snap or {}).get("player")
        if bot is not None and p and p.get("pos") is not None:
            # --- the fight, from RAM
            stats["fight"] = "ram"
            keys.apply(bot.tick(snap, now=clock()))
            sleep(FIGHT_TICK_S)
            continue

        # --- no player in RAM: advance, sweep the aim, fire. Screen-only, so this is deliberately blunt.
        stats["fight"] = "frame"
        keys.release()
        if ticks % IDLE_TICKS_BEFORE_ACTION == 0:
            _press(send, "dup", sleep=sleep)            # aim up is harmless in a menu-free round and lifts the camera
            _press(send, "w", 0.35, sleep=sleep)        # advance
            _press(send, driver.ACTION_BTN, sleep=sleep)   # the action button (Y on Switch: kicks at a prompt)
            stats["presses"] += 3
        sleep(0.35)

    keys.release()
    stats["ended"] = clock()
    stats["seconds"] = round(stats["ended"] - started, 1)
    return {"ok": True, "mode": "re4-switch-ram" if stats.get("fight") == "ram" else "re4-switch-screen",
            "rounds": stats["rounds"], "presses": stats["presses"], "seconds": stats["seconds"],
            "boundaries_posted": stats["boundaries_posted"],
            "note": ("RAM fight: player, Ganados and the clock read from memory" if stats.get("fight") == "ram" else
                     "frame-only fight: the player and Ganados are not mapped in RAM yet (re4_switch.PLAYER_CLASS)")}


def _snapshot(m, stats: dict) -> dict | None:
    try:
        snap = driver.snapshot(m)
    except Exception as exc:                                 # noqa: BLE001 - a reader's error costs the tick
        stats["snapshot_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return None
    stats["timer"] = snap.get("timer")
    stats["clock_addr"] = hex(snap["clock_addr"]) if isinstance(snap.get("clock_addr"), int) else None
    stats["enemies_read"] = len(snap.get("enemies") or ())
    stats["player_read"] = bool(snap.get("player"))
    return snap


def _report(rnd: Round, snap: dict, stats: dict, now: float, round_boundary, keys: Keys) -> None:
    """The round's end, posted once with its RAM witness (mercmode.accept_boundary checks it on the control plane)."""
    end = rnd.terminal(snap, now)
    if end is None:
        return
    body = _boundary(rnd, end, snap, stats, now)
    rnd.posted = body
    stats["last_boundary"] = {k: body[k] for k in ("round_id", "stage", "character")} | {"screen": end["screen"]}
    if round_boundary is None:
        stats["mercmode_boundary_error"] = "no round_boundary sink: this run was not started by MercMode's autoplay"
        return
    keys.release()                                          # between rounds with released inputs (publish_boundary)
    if round_boundary(body, stats):
        stats["boundaries_posted"] += 1
