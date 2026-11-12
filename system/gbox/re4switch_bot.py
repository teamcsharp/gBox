"""RE4 (Switch) Mercenaries playbook: get to a round from the screen, start it, fight it from RAM, report its end.

This title has a frame classifier for its menus (`re4_switch_screens`). The round itself is read from RAM by the driver
(`re4_switch.snapshot`): the game's own state and its HUD clock (`re4_switch.game_state`, the CountDown; ClockFinder's
search only when that cannot be read), the player and the Ganados from the unit census (`re4_switch.PLAYER_CLASS` /
`U_POS`).

What it does, and what it says it does:

* menus: the driver's walk, one press at a time, steering Select Player / Select Stage to MercMode's DJ pick
  (`game.launch.mercmode.selection`, `re4_switch.request`); a still picture before a stage runs the back-out escape;
* in a round with the player in RAM: `re4_switch.Bot` fights (turn, raise, fire through the operator's gates, the combo
  clock, crowd fire, locate by the map, never stand) and its keys go in as holds and taps;
* in a round without the player in RAM: the blunt frame-only cadence (advance, sweep the aim, fire) - `stats["fight"]`
  says which one ran;
* at the round's end it posts a MercMode round boundary (`round_boundary`, tools._start_playbook) with a RAM witness,
  and writes the same round's curriculum row (`gbox.mercs.notebook`, the source the round reports read):
  the game's results sequence after the round was seen live, or the clock read 0 after it was seen counting (results),
  or the player's health read 0 (death). Nothing is claimed from
  the frame alone: without the clock the round ends by MercMode's no-progress cut, and `stats` says why.

The one thing it must get right is where the game is. With the session's RAM (always, on Citron) that comes from the
game's own state (`re4_switch.game_state`: the Mercenaries scenario task's intro / round / results runs, pG's event,
suspend, death-camera and case flags, the pad mask, and the HUD's CountDown): a round is live only while the game says
the player is in control and its clock runs, the intro card is paged with A by the Bot until it is, and the telemetry's
`screen`, the tactical map and MercMode's now_playing say the same phase. The frame classifier stays the menus' reader and
the cross-check: a disagreement (RAM says X, the frame says Y) is logged to STATE_LOG. A named reference menu (title,
the menus, the selects) or the death screen still wins over a RAM round that is not live (stale fields after a reset).
Without RAM the old frame rules run: `unknown` only counts as in-round after a stage screen has been seen, after
UNKNOWN_ROUND_S (the fallback's guess, never used while the game's state can be read).

2026-11-10 (Krauser on Waterworld, live): the intro card "Eliminate as many Ganados ..." held the round for minutes
while the runner took the unnamed picture for the round after 6 s, the Bot fired at the Ganados the round had already
placed in RAM ("crowd fire", 620 shots, 0 hits) and the map's clock was a matrix float ClockFinder had picked. The same
intro read as "playing" on the frame (the HUD test fires on Waterworld's horizon) and the Bot fired during it again.
"""
import json
import time
import uuid

from .mercs.core import menu_pace
from .mercs.titles import re4_switch as driver
from .mercs.titles import re4_switch_screens as screens
from .mercs.titles import re4_walk

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
MENU_POLL_S = 0.1                       # the menus are read this often (re4_switch.Pace, learned per screen, says
                                        # when a press may go in; 0.2 until 2026-11-10: "never ... slowly")
UNKNOWN_ROUND_S = 6.0                   # WITHOUT RAM only: after a stage pick, an unnamed picture this long is taken for
                                        # the round (no black, no HUD); with the game's state read nothing is guessed
# Frames that cannot say whether a round runs (a gameplay picture has no reference; the HUD test also fires on the intro
# and on Waterworld's horizon; the reader's round_intro is a guess from the load's black): the game's state decides
FRAME_UNSURE = (None, "unknown", "playing", "loading", "round_intro", "menu")
# Named, measured screens that win over a RAM round that is not live (the fields can be stale after a reset)
FRAME_MENUS = ("title", "main_menu", "extras_menu", "mercs_title", "select_player", "select_stage", "dead_continue",
               "story", "story_prompt")
STATE_LOG = driver.WALK_LOG.with_name("re4-state-disagreements.jsonl")
STATE_LOG_EVERY_S = 5.0                 # one row per (RAM phase, frame screen) pair at most this often
ROUND_END_TICKS = 3                     # the game's state reads no round this many ticks in a row: the round is over
FIGHT_TICK_S = 0.05                     # the RAM fight's loop
BOW_CLASS = 0x1C                        # Krauser's bow (re4_weapons.MOTION_RATE_CLASSES)
# The bow's loop: the operator asked for 20x (2026-11-10 #9508, and again 2026-11-11: "have the bow able to fire at
# 20x speed ... rain arrows"). It was 0.025 - only 2x the rifle's 0.05, which is why 20x never appeared however the
# trigger was tuned. 0.05 / 20 = 0.0025: one decision every 2.5 ms, twenty times the gun's loop.
BOW_FIGHT_TICK_S = 0.0025
BOW_TAP_HOLD_S = 0.02                   # the bow's trigger is held through its draw: a down+up in one batch is a
                                        # zero-length press the game never fires (the operator 2026-11-11: "the bot
                                        # never fires the arrows in RE4") - the guns fire on the press edge, the bow
                                        # needs the hold
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
    try:                                                    # every press of the walk, whoever made it (driver.WALK_LOG)
        import inspect
        caller = inspect.stack()[1].lineno
        with driver.WALK_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": round(time.time(), 2), "runner_press": key, "line": caller}) + chr(10))
    except Exception:                                        # noqa: BLE001 - a log never costs a press
        pass
    send([{"key": key, "down": True}])
    sleep(hold_s)
    send([{"key": key, "down": False}])


class Keys:
    """A bot's {"hold": keys, "tap": key} as pad events: a held key goes down once and up when the bot lets it go, a
    tap is down + up before the holds (the trigger is never held: re4_switch.Bot).

    A tap with `tap_hold` > 0 keeps the trigger down that long before the up (the bow's draw: a zero-length press
    never fires an arrow - live 2026-11-11 "the bot never fires the arrows in RE4"); a gun's tap stays the batch of
    down + up the game treats as a press edge.
    """

    def __init__(self, send, sleep=time.sleep):
        self.send, self.sleep, self.down = send, sleep, set()

    def apply(self, act: dict, tap_hold: float = 0.0) -> None:
        want = set((act or {}).get("hold") or ())
        rows = [{"key": k, "down": False} for k in sorted(self.down - want)]
        rows += [{"key": k, "down": True} for k in sorted(want - self.down)]
        tap = (act or {}).get("tap")
        if tap and tap_hold > 0:
            rows.append({"key": tap, "down": True})       # after the holds: the aim is down before the trigger
        elif tap:
            rows += [{"key": tap, "down": True}, {"key": tap, "down": False}]
        if rows:
            self.send(rows)
        self.down = want
        if tap and tap_hold > 0:
            self.sleep(tap_hold)
            self.send([{"key": tap, "down": False}])

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
        self.live_seen = False                  # the game said in control with its clock running (game_state)
        self.phases: list = []                  # the game's phases in the order seen
        self.posted = None

    def observe(self, snap: dict, now: float) -> None:
        game = snap.get("game")
        if isinstance(game, dict):
            if not self.phases or self.phases[-1] != game.get("phase"):
                self.phases.append(game.get("phase"))
            if game.get("in_control") and game.get("clock_running"):
                self.live_seen = True
        timer = snap.get("timer")
        if isinstance(timer, (int, float)) and not isinstance(timer, bool):
            if self.last_timer is not None and 0 < timer < self.last_timer:
                self.clock_counting = True
            if self.high is None and timer >= RESULTS_MIN_CLOCK_S:
                self.high = (float(timer), now)
            self.last_timer = timer
            self.zero_since = (self.zero_since or now) if timer <= 0 else None
        p = snap.get("player")
        # the player unit read through the bss pointer and checked by its class (re4_switch.player_unit); his life is
        # not in that unit on Switch, so a position is the evidence (a health, when one is read, must be above 0)
        if isinstance(p, dict) and p.get("pos") is not None and (p.get("hp") is None or p["hp"] > 0):
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
        game = snap.get("game")
        if isinstance(game, dict) and self.live_seen and game.get("phase") == "results":
            # the game's own results sequence (MercSysResultMove) after a round seen live: the clock ran out
            return {"screen": "results", "tally_ready": True, "timer": 0, "state_source": "ram",
                    "clock_left": game.get("clock"), "phases": list(self.phases)}
        if self.player_seen and p.get("hp") is not None and p["hp"] <= 0:
            out = {"screen": "dead", "hp": p["hp"]}
            if isinstance(game, dict):
                out.update(state_source="ram", death_camera=game.get("phase") == "dead", phases=list(self.phases))
            return out
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


def _ring_step(ad, stats):
    """The bot's own grenade ring for this title (gbox.mercs.grenade_ring): its per-tick step, or None.

    The rule refuses on its own (the flash minute, the learned blast reach, no player); this hook only gives it the
    playbook's tick and keys. Built once per run so its history and cooldown survive the round.
    """
    try:
        from .mercs import grenade_ring
        return grenade_ring.control(ad, {"map_id": MAP_ID, "menus": "gbox.mercs.titles.re4_switch"})
    except Exception as exc:                             # noqa: BLE001 - a rule that cannot load never ends a run
        stats["grenade_ring_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return None


def play(ad, send, stopped, sleep=time.sleep, stats: dict | None = None, *, clock=time.time,
         max_seconds: float | None = None, still_s: float = 12.0, game=None, round_boundary=None, m=None,
         tactical=None, session_id: str = "", source_job_id: str = "", **_) -> dict:
    """Walk the menus to a round, start it, fight it, and keep going until `stopped()`.

    Returns a dict of what it did. `stats` (when given) is filled live for the watch panel. `session_id` and
    `source_job_id` (the autoplay job, tools._start_playbook passes both) are the round Notebook's provenance: the round
    reports only use a round that names its exact session and owning autoplay start (`round_reports.provenance`).

    `still_s` is how long the picture may stay on one named screen (with no cursor progress) before the back-out escape
    is pressed. A stray confirm lands in LOAD and the save list then holds the walk for as long as nothing acts on it
    (measured on 2026-11-07: identical frames for 260 s); the escape is what gets the walk out.
    `game` carries MercMode's DJ pick; `round_boundary(body, stats)` posts a round's end (tools._start_playbook passes
    it); `m` is the session's RAM (default: the adapter's, read-only).
    """
    stats = stats if stats is not None else {}
    stats.update({"screen": None, "presses": 0, "rounds": 0, "started": clock(), "stage_seen": False,
                  "story_recoveries": 0, "stall_steps": 0, "fight": None, "boundaries_posted": 0})
    if isinstance(session_id, str) and session_id:
        stats["source_session_id"] = session_id
    if _job_id(source_job_id):
        stats["source_autoplay_job_id"] = _job_id(source_job_id)
    # the tactical map (tools._start_playbook passes the worker's sink): a frame a tick in a round with the player in
    # RAM - re4_walk.publish(pub, snap, bot, "playing") where the RAM fight ticks - else the screen once a second
    pub = re4_walk.publisher(tactical)
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
    keys = Keys(send, sleep=sleep)
    bot = driver.Bot(stats=stats, clock=clock) if m is not None else None
    ring_step = _ring_step(ad, stats)                # the bot's own ring rule (gbox.mercs.grenade_ring)
    started = clock()
    last_step = 0.0
    ticks = 0
    in_round = False
    rnd: Round | None = None
    last_snap: dict | None = None
    pace = driver.Pace()
    # the walk's clock (gbox.mercs.core.menu_pace.Clock): the boot from the session's launch (the game dict's
    # _launched_at, tools.launch_game) or this start, every round's end to the next round's first tick. Wall time of
    # its own (the launch is a wall time), so the run's clock() is read exactly as often as before.
    walk = menu_pace.Clock(driver.pace_table(), wall=time.time, pace=driver.pace_summary)
    walk.begin("boot", launched_at=(game or {}).get("_launched_at"), up_at=(game or {}).get("_up_at"))
    walk_stats_at = float("-inf")

    def walk_stats(force: bool = False) -> None:
        nonlocal walk_stats_at
        if force or time.monotonic() - walk_stats_at >= 0.5:
            walk_stats_at = time.monotonic()
            stats.update(walk.stats())

    def round_started() -> None:
        walk.round_start()
        walk_stats(True)

    def round_ended() -> None:
        walk.round_end()
        walk_stats(True)
    unknown_since = None
    seen_menu, prev_where = False, None             # title_returns: the title again after a menu (an idle return or
                                                    # a back press), the stat that tells a walk loop on the live panel

    screen = {"where": None}
    last_phase, off_round = None, 0
    checker = CrossCheck(stats, clock)
    while not stopped():
        if max_seconds is not None and clock() - started > max_seconds:
            break
        ticks += 1
        # the RAM fight reads the frame every FRAME_EVERY ticks only (the round's own state is in RAM; the frame is
        # there to see the menus come back), everything else every tick
        fresh = not (in_round and stats.get("fight") == "ram" and ticks % FRAME_EVERY)
        if fresh:
            try:
                frame = ad.get_frame()
            except Exception:                                # noqa: BLE001 - a missing frame is not a screen
                sleep(0.5)
                continue
            screen = reader.read(frame)
        where = screen.get("where")
        # --- where the game is, from its own state (re4_switch.game_state), the frame as the cross-check
        gs = _game(m, stats) if m is not None else None
        phase = gs.get("phase") if gs else None
        live = bool(gs) and phase in ("playing", "grabbed") and bool(gs.get("clock_running"))
        ram_round = bool(gs) and phase in driver.ROUND_PHASES and (live or where in FRAME_UNSURE)
        if fresh:
            checker.check(gs, where)
        stats["frame_screen"], stats["state_source"] = where, "ram" if gs is not None else "frame"
        if ram_round:
            stats["screen"] = driver.PHASE_SCREEN.get(phase) or phase
            if not in_round or (phase == "intro" and last_phase not in (None, "intro")):
                # a round's scenario task runs (its intro, or a round already under way when the bot came in): the
                # round starts here, and no entry press is guessed - the Bot pages the intro while the game says so
                if in_round:
                    round_ended()                            # a replay's intro (Continue: Yes) without a menu between
                in_round, rnd = True, _new_round(stats, clock())
                round_started()
                stats["rounds"] += 1
                stats["stage_seen"] = True
                stats.setdefault("walk_s", round(clock() - started, 1))
            last_phase = phase
            last_action = clock()                            # a round is progress: the menus' stall clock waits
            snap = _snapshot(m, stats)
            if snap is not None:
                snap.setdefault("game", gs)                  # (a snapshot whose own state read failed: this tick's)
                last_snap = snap
                _maintain_mods(ad, snap, stats)
                if rnd is not None:
                    rnd.observe(snap, clock())
                    if live and where == "playing":
                        rnd.hud_seen = True
                    _report(rnd, snap, stats, clock(), round_boundary, keys)
            if bot is not None and snap is not None:
                stats["fight"] = "ram"
                keys.apply(bot.tick(snap, now=clock()),
                           tap_hold=BOW_TAP_HOLD_S if (snap or {}).get("weapon_class") == BOW_CLASS else 0.0)
                re4_walk.publish(pub, snap, bot, stats["screen"])
            else:
                keys.release()
                re4_walk.publish(pub, None, None, stats["screen"])
            off_round = 0
            sleep(FIGHT_TICK_S)
            continue
        if in_round and gs is not None:
            keys.release()                                   # the game says the round is over (or a menu is named):
            off_round += 1                                   # ROUND_END_TICKS reads in a row end it (one torn read
            if off_round >= ROUND_END_TICKS:                 # never splits a round in two)
                in_round = False
                round_ended()
        last_phase = phase
        if gs is not None and where in ("playing", "round_intro"):
            where = "unknown"                                # no round runs: the HUD test or the reader's intro guess
        stats["screen"] = where                              # is a load, a fade or the intro's camera, not play
        if where != "playing" or not in_round:
            re4_walk.publish(pub, None, None, where or "unknown")
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
        if where in ("main_menu", "extras_menu", "mercs_title", "select_player", "select_stage") \
                and not stats.get("pre_round_done"):
            # the saved RE4 mods into this boot before its round is built (the loadouts, the weapon tables)
            stats["pre_round_done"] = True
            try:
                from .mercs.titles import re4_switch_mods
                stats["pre_round"] = re4_switch_mods.pre_round(ad, m)
            except Exception as exc:                         # noqa: BLE001 - a mod never costs the walk
                stats["pre_round_error"] = f"{type(exc).__name__}: {exc}"[:160]
        if where in ("story", "story_prompt", "title", "main_menu", "extras_menu"):
            # back before the stage select: no dark picture is a round until a stage is picked again (live 2026-11-10
            # 23:26: after Yes on Cancel loading? the black was taken for a round and its three entry A presses went
            # into the main menu's LOAD - the walk's press log, runner line 337 - for the whole turn)
            stats["stage_seen"] = False

        # --- menus: the same route the driver walks, one press at a time
        if where not in ("unknown", "playing"):
            if in_round:
                keys.release()
                round_ended()
            in_round = False
            target = (driver.EXTRAS_ROW if where == "main_menu"
                      else driver.MERCENARIES_ROW if where == "extras_menu" else None)
            scr = {**screen, "target": target, "reader": reader}
            pace.observe(scr, clock())
            walk.screen(where)
            walk_stats()
            if where == "title" and seen_menu:
                stats["title_returns"] = stats.get("title_returns", 0) + (prev_where != "title")
            if where == "dead_continue" and prev_where != "dead_continue":
                stats["deaths"] = stats.get("deaths", 0) + 1     # the walk answers Continue: Yes (re4_switch.step)
                if rnd is not None and rnd.posted is None and rnd.player_seen:
                    # the round's end, witnessed by the game's own death screen (mercmode.accept_boundary)
                    _post(rnd, {"screen": "dead", "death_screen": True, "hp": None}, last_snap or {}, stats,
                          clock(), round_boundary, keys)
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
                    missed = pace.misses
                    pace.pressed(scr, key, clock())
                    walk.press(where, key)
                    if pace.misses > missed:
                        walk.miss(where)                      # the game dropped the last one (pressed again)
                    stats["presses"] += 1
                    stats["menu_presses"] = stats.get("menu_presses", 0) + 1
                    last_step = clock()
            sleep(MENU_POLL_S)
            continue

        # --- unknown / the HUD: in the stage (the classifier cannot read a live round's picture, only its HUD)
        if not in_round:
            walk.screen(where or "unknown")                  # a load or a fade on the walk's timeline
        if not stats["stage_seen"] and where != "playing":
            sleep(0.4)
            continue                       # a screen nobody can classify before a stage: do not press into the dark
        if gs is not None:
            # the game's state is read and no round runs: an unnamed picture is the stage's load, a fade or a screen
            # the reader does not know - never a round, however long it lasts, and nothing is pressed into it
            unknown_since = None
            stats["waits_no_round"] = stats.get("waits_no_round", 0) + 1
            sleep(MENU_POLL_S)
            continue
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
            rnd = _new_round(stats, clock())
            round_started()
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
        if snap is not None:
            last_snap = snap
        if snap is not None:
            _maintain_mods(ad, snap, stats)
        if rnd is not None and snap is not None:
            rnd.observe(snap, clock())
            _report(rnd, snap, stats, clock(), round_boundary, keys)
        p = (snap or {}).get("player")
        if bot is not None and p and p.get("pos") is not None:
            # --- the fight, from RAM
            stats["fight"] = "ram"
            if ring_step is not None:                    # the ring takes its own tick: keys released first
                try:
                    ring_out = ring_step(snap, stats, clock(), lambda _keys: (keys.release() or True))
                except Exception as exc:                 # noqa: BLE001 - a ring never ends the round
                    stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:160]
                else:
                    # The engine publishes these for the Switch titles; this driver is RE4's own loop, so without them
                    # the operator's panel and the round reads showed no ring at all (live 2026-11-11: RE4 rounds 9-17
                    # with empty ring_armed / ring_decision while the ring step was wired and running).
                    stats["ring_armed"] = True
                    stats["ring_decision"] = str(ring_out.get("reason") or "")[:200]
                    if ring_out.get("fired"):
                        re4_walk.publish(pub, snap, bot, "playing")
                        sleep(BOW_FIGHT_TICK_S if (snap or {}).get("weapon_class") == BOW_CLASS else FIGHT_TICK_S)
                        continue
            keys.apply(bot.tick(snap, now=clock()),
                       tap_hold=BOW_TAP_HOLD_S if (snap or {}).get("weapon_class") == BOW_CLASS else 0.0)
            re4_walk.publish(pub, snap, bot, "playing")
            sleep(BOW_FIGHT_TICK_S if (snap or {}).get("weapon_class") == BOW_CLASS else FIGHT_TICK_S)
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
    if pub is not None:
        pub.close()
    stats["ended"] = clock()
    stats["seconds"] = round(stats["ended"] - started, 1)
    return {"ok": True, "mode": "re4-switch-ram" if stats.get("fight") == "ram" else "re4-switch-screen",
            "rounds": stats["rounds"], "presses": stats["presses"], "seconds": stats["seconds"],
            "boundaries_posted": stats["boundaries_posted"],
            "note": ("RAM fight: player, Ganados and the clock read from memory" if stats.get("fight") == "ram" else
                     "frame-only fight: the player and Ganados are not mapped in RAM yet (re4_switch.PLAYER_CLASS)")}


def _maintain_mods(ad, snap: dict, stats: dict) -> None:
    """The live sidebar's RE4 mods (re4_switch_mods.maintain: health caps, time per kill) on this snapshot."""
    try:
        from .mercs.titles import re4_switch_mods
        done = re4_switch_mods.maintain(ad, snap)
    except Exception as exc:                                 # noqa: BLE001 - a mod never costs the fight
        stats["mods_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return
    for k, v in (done or {}).items():
        key = "mods_" + k
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            stats[key] = v                                   # a record (a round's weapon): shown, never summed
            continue
        stats[key] = stats.get(key, 0) + v
    # The live states the mods keep (not numeric: shown, never summed): the bow's class/routine and the aim lock's
    # counters, so the watch panel can say whether the 40x / the steady aim is actually on (live 2026-11-11: the
    # Krauser rounds' shots/hits needed exactly this to be readable).
    try:
        st = re4_switch_mods._state(ad)
    except Exception:                                        # noqa: BLE001 - a read never costs the fight
        return
    if (snap or {}).get("weapon_class") is not None:
        stats["weapon_class"] = (snap or {}).get("weapon_class")
    # Why the laser line was refused, when it was: the aim ticket's per-class evidence (the steady aim needs the line,
    # and the ~40% rounds could not say whether the class byte, the ray's origin or its length was refusing).
    if (snap or {}).get("laser_gate"):
        stats["laser_gate"] = (snap or {}).get("laser_gate")
    for key in ("motion_rate_kind", "motion_rate_class", "motion_rate_routine", "aim_ram_writes", "aim_sway_zeroed"):
        if st.get(key) is not None:
            stats[key] = st[key]


def _game(m, stats: dict) -> dict | None:
    """The game's own state (re4_switch.game_state), or None when it cannot be read (then the frame rules run). Its
    phase, control, clock and the game's own counters go to stats for the watch panel."""
    try:
        gs = driver.game_state(m)
    except Exception as exc:                                 # noqa: BLE001 - a reader's error: the frame decides
        stats["game_state_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return None
    if not isinstance(gs, dict):
        stats["game_phase"] = None
        return None
    stats.update(game_phase=gs.get("phase"), in_control=gs.get("in_control"), game_clock=gs.get("clock"),
                 clock_running=gs.get("clock_running"), game_step=gs.get("game_step"))
    if gs.get("phase") in driver.ROUND_PHASES:
        # the game's own counters (MercSysWk, measured live): MercMode's progress rule and now_playing read these
        stats.update(kills=gs.get("kills"), score=gs.get("score"), combo=gs.get("combo"))
    return gs


class CrossCheck:
    """The frame against the game's own state, every read: a disagreement (RAM says X, the frame says Y) is counted
    (stats state_disagreements, last_disagreement) and logged to STATE_LOG, one row per pair every STATE_LOG_EVERY_S, so
    the classifier and the state can be audited against each other."""

    def __init__(self, stats: dict, clock):
        self.stats, self.clock = stats, clock
        self.logged: dict = {}

    @staticmethod
    def disagrees(gs: dict, where) -> str | None:
        phase = gs.get("phase")
        if where == "playing" and phase not in ("playing", "grabbed", "held", "case"):
            return f"the frame reads the HUD, the game says {phase}"
        if where in FRAME_MENUS and where != "dead_continue" and phase in driver.ROUND_PHASES:
            return f"the frame names {where}, the game runs a round ({phase})"
        if where == "dead_continue" and phase in ("playing", "grabbed", "intro"):
            return f"the frame names the death screen, the game says {phase}"
        if where == "loading" and phase in ("playing", "grabbed"):
            return "a black frame while the game says in control"
        if where == "round_intro" and phase not in ("intro", None):
            return f"the reader guesses the intro, the game says {phase}"
        return None

    def check(self, gs, where) -> str | None:
        if not isinstance(gs, dict):
            return None
        why = self.disagrees(gs, where)
        if why is None:
            return None
        self.stats["state_disagreements"] = self.stats.get("state_disagreements", 0) + 1
        now = self.clock()
        pair = (gs.get("phase"), where)
        if now - self.logged.get(pair, float("-inf")) < STATE_LOG_EVERY_S:
            return why
        self.logged[pair] = now
        row = {"t": round(time.time(), 2), "ram": gs.get("phase"), "frame": where, "why": why,
               "in_control": gs.get("in_control"), "clock": gs.get("clock"), "clock_running": gs.get("clock_running"),
               "intro_step": gs.get("intro_step"), "flags": gs.get("flags")}
        self.stats["last_disagreement"] = {k: row[k] for k in ("ram", "frame", "why")}
        try:
            STATE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with STATE_LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + chr(10))
        except OSError:
            pass
        return why


def _snapshot(m, stats: dict) -> dict | None:
    try:
        snap = driver.snapshot(m)
    except Exception as exc:                                 # noqa: BLE001 - a reader's error costs the tick
        stats["snapshot_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return None
    driver.watch_into(m, snap, stats)                        # the E3 .bss watch (the harness's mailbox evidence)
    stats["timer"] = snap.get("timer")
    stats["clock_addr"] = hex(snap["clock_addr"]) if isinstance(snap.get("clock_addr"), int) else None
    stats["enemies_read"] = len(snap.get("enemies") or ())
    stats["player_read"] = bool(snap.get("player"))
    if snap.get("kill_candidates"):
        stats["kill_candidates"] = " ".join(f"{k}={v}" for k, v in snap["kill_candidates"].items())
    if snap.get("player") and snap["player"].get("class") is not None:
        stats["player_class"] = hex(snap["player"]["class"])
    return snap


def _report(rnd: Round, snap: dict, stats: dict, now: float, round_boundary, keys: Keys) -> None:
    """The round's end, posted once with its RAM witness (mercmode.accept_boundary checks it on the control plane)."""
    end = rnd.terminal(snap, now)
    if end is None:
        return
    _post(rnd, end, snap, stats, now, round_boundary, keys)


def _job_id(value) -> str:
    """A 16-hex autoplay job id, or '' (never a partial or foreign id in a round's provenance)."""
    value = str(value or "")
    return value if len(value) == 16 and all(c in "0123456789abcdef" for c in value) else ""


# the driver's turn-long counters (Driver.round_counters): each round's amount is written as round_<key>, the shape the
# engine's rounds use and round_reports.METRICS reads (round_gun_downs, round_unwall_tangents, round_shots, ...)
ROUND_COUNTERS = tuple(getattr(getattr(driver, "DRIVER", None), "round_counters", ()) or ())


def _new_round(stats: dict, at: float) -> Round:
    """A round with the counters' starting values, so its end can record this round's own amounts."""
    rnd = Round(at)
    rnd.counter_base = {key: stats.get(key, 0) for key in ROUND_COUNTERS}
    return rnd


def _record_round(rnd: Round, end: dict, stats: dict) -> None:
    """Write this round's curriculum row (`gbox.mercs.notebook`): the round reports' source, which RE4 had none of.

    The row carries the provenance `round_reports.provenance` checks for a native solo round (the exact session id and
    the autoplay job that started the run, seeded by `play`), this round's own counter amounts (round_<key>) and the
    round's telemetry, so the next report shows the raise/lower, the tangents and the stand breaks the operator judges a
    block by. Best effort: a failure is a stat, never the round's end.
    """
    sid, jid = stats.get("source_session_id"), _job_id(stats.get("source_autoplay_job_id"))
    if not isinstance(sid, str) or not sid or not jid:
        stats["round_notebook"] = "skipped: no exact session/autoplay start to attribute the round to"
        return
    try:
        from .mercs import lessons as lesson_store
        from .mercs.notebook import Notebook
        pick = driver.SELECTION
        observed = dict(stats)
        base = getattr(rnd, "counter_base", None)
        if isinstance(base, dict):
            for key in ROUND_COUNTERS:
                before, after = base.get(key), stats.get(key)
                before = before if isinstance(before, (int, float)) and not isinstance(before, bool) else 0
                after = after if isinstance(after, (int, float)) and not isinstance(after, bool) else 0
                observed[f"round_{key}"] = max(0, after - before)
        observed.update(team_role="solo_p1", scoring_scope="solo",
                        source_session_id=sid, source_autoplay_job_id=jid)
        Notebook(lesson_store.ROOT.parent, MAP_ID).finish(
            driver.STAGES[pick.get("stage") or 0], "mercenaries", driver.CHARACTERS[pick.get("player") or 0],
            "completed" if end.get("screen") == "results" else "died", observed, round_id=rnd.id)
        stats["round_notebook"] = "recorded"
    except Exception as exc:                                   # noqa: BLE001 - evidence never ends a round
        stats["round_notebook_error"] = f"{type(exc).__name__}: {exc}"[:200]


def _post(rnd: Round, end: dict, snap: dict, stats: dict, now: float, round_boundary, keys: Keys) -> None:
    """Post this round's end once (its RAM / screen witness) to MercMode, and record it for the round reports."""
    body = _boundary(rnd, end, snap, stats, now)
    rnd.posted = body
    stats["last_boundary"] = {k: body[k] for k in ("round_id", "stage", "character")} | {"screen": end["screen"]}
    if round_boundary is None:
        stats["mercmode_boundary_error"] = "no round_boundary sink: this run was not started by MercMode's autoplay"
    else:
        keys.release()                                      # between rounds with released inputs (publish_boundary)
        if round_boundary(body, stats):
            stats["boundaries_posted"] += 1
    _record_round(rnd, end, stats)
