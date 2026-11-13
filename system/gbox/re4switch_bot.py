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
import math
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
BOW_ITEM = 0x52                         # ...and its ITEM id (re4_weapons.CLASS_OF[0x52] is 0x1C)


def is_bow(snap) -> bool:
    """The bow, by EITHER witness: the class byte (0x1C) or the equipped item (0x52).

    Live 2026-11-12: the 20x loop hung on `snap["weapon_class"] == BOW_CLASS` at all four call sites, so a bow whose
    class byte did not read 0x1C kept the gun's 0.05 s loop - the operator's "the bow is supposed to be firing 20x" and
    it never was. The title module already treats either witness as the bow (_bow_in_hand); the driver's tick and tap
    hold must agree with it or the fast path is decided by a byte that may be wrong.
    """
    s = snap or {}
    return s.get("weapon_class") == BOW_CLASS or s.get("equipped_id") == BOW_ITEM


def bonus_goal(bot, snap, now) -> bool:
    """Mark the nearest reachable TIME BONUS he has not been sent to yet, when he has no mark of his own.

    The operator: "traversing the level, going after the objectives ... going for all of the time bonuses". Nothing had
    to be built for the walking: re4_walk.attach already wraps Bot.tick and operator_goal_act routes a 'point' goal and
    FIGHTS the ones on the way, and every stage json already carries the bonuses (r400 8, r402 9, r403 15, r404 15) with
    the walkable `stand` approach. What was missing was anyone issuing the mark.

    A row is marked once per round (the id is in bot._bonus_issued) so an unreachable one cannot pin him to it for the
    whole round: if the point goal expires, the next tick takes the next nearest.
    """
    try:
        goals = re4_walk.goals_of(bot)
        terminal = getattr(re4_walk.map_goals, "TERMINAL", ())
        if (snap or {}).get('module_base') is not None and 'nav' not in snap:
            re4_walk.re4_nav.attach(snap)
        nav = (snap or {}).get('nav')
        pos = ((snap or {}).get('player') or {}).get('pos')
        if nav is None or not pos:
            return False
        # A sticky picker can temporarily retain the previous stage during a
        # load. Do not issue its objectives until the player's actual floor
        # supports that geometry. Never infer the room from queued selection.
        scope = (goals.round, getattr(nav, 'room', None), getattr(nav, 'sig', None))
        if bot.__dict__.get('_bonus_scope') != scope:
            bot.__dict__.update(_bonus_scope=scope, _bonus_issued=set(), _bonus_prev=None)
            if goals.goal and goals.goal.get('source') == 'time_bonus':
                goals.goal.update(state='unavailable', reason='Stage geometry changed; selecting this room\'s time bonuses')
                stats = getattr(bot, 'stats', None)
                if isinstance(stats, dict):
                    stats['bonus_stage_invalidations'] = stats.get('bonus_stage_invalidations', 0)+1
        on_floor = getattr(nav, 'on_floor', None)
        if callable(on_floor) and not on_floor(pos):
            # A verified native ladder/fall also leaves the ordinary floor.
            # Defer selection without cancelling a same-geometry objective;
            # the final movement gate owns non-traversal off-floor commands.
            return False
        # Reaching a route endpoint proves approach only. It does not prove
        # the game's time bonus was activated or the clock increased.
        prev = bot.__dict__.get("_bonus_prev")
        if isinstance(prev, dict) and goals.goal and goals.goal.get("id") == prev.get("id") \
                and goals.goal.get("state") == "completed":
            stats = getattr(bot, "stats", None)
            if isinstance(stats, dict):
                stats["bonus_approaches"] = stats.get("bonus_approaches", 0) + 1
                if goals.goal.get('confirmation') == 'clock_gain_without_kills':
                    stats['bonus_clock_credits'] = stats.get('bonus_clock_credits', 0) + 1
                    stats['bonus_seconds_observed'] = stats.get('bonus_seconds_observed', 0) + float(prev.get('seconds') or 0)
                else:
                    stats["bonus_unconfirmed"] = stats.get("bonus_unconfirmed", 0) + 1
            bot.__dict__["_bonus_prev"] = None
        if goals.goal is not None and goals.goal.get("state") not in terminal:
            return False                                  # his own mark, or a bonus still on its way
        issued = bot.__dict__.setdefault("_bonus_issued", set())
        best = None
        for row in getattr(nav, "bonuses", ()) or ():
            if row.get('kind') != 'time_bonus' or row.get("reachable") is False:
                continue
            bid = f"bonus-{row.get('source') or '?'}"
            if bid in issued:
                continue
            at = row.get("stand") or row.get("pos")
            if not at or len(at) < 3:
                continue
            d = math.hypot(at[0] - pos[0], at[2] - pos[2])
            if best is None or d < best[0]:
                best = (d, row, bid, at)
        if best is None:
            return False
        _d, row, bid, at = best
        bot.receive_map_goal({"id": bid, "round": goals.round, "kind": "point", "entity_id": 0,
                              "pos": [float(at[0]), float(at[1]), float(at[2])],
                              "label": f"time bonus +{row.get('seconds') or '?'}s"})
        # Native stage data supplies a real 3D approach. A map click's inferred
        # floor is inappropriate here, especially for stairs and upper floors.
        if goals.goal is not None and goals.goal.get("id") == bid:
            goals.goal["floor_y"] = float(at[1])
            goals.goal['source'] = 'time_bonus'
            goals.goal['seconds'] = row.get('seconds')
            goals.goal['geometry'] = list(scope)
        issued.add(bid)
        bot.__dict__["_bonus_prev"] = {"id": bid, "seconds": row.get("seconds")}
        stats = getattr(bot, "stats", None)
        if isinstance(stats, dict):
            stats["bonus_goals"] = stats.get("bonus_goals", 0) + 1
            stats["bonus_goal_m"] = round(_d / 1000.0, 1)
        return True
    except Exception as exc:                              # noqa: BLE001 - a mark never costs the fight
        stats = getattr(bot, "stats", None)
        if isinstance(stats, dict):
            stats["bonus_error"] = f"{type(exc).__name__}: {exc}"[:120]
        return False


def walk_track(stats: dict, snap, now: float) -> None:
    """How he is MOVING, for the run reviewer: metres walked, net displacement, how straight the path is, and how long
    he has been still. The operator, live 2026-11-12: "they're just turning back and forth in place while stumbling
    backwards. I need the bot able to walk the level confidently." That failure is exactly `walk_straight` near 0 with
    `walk_still_s` climbing, so the two numbers together say traversing vs turning on the spot - the next change to the
    walk can be judged on them instead of on a description.
    """
    p = ((snap or {}).get("player") or {}).get("pos")
    if not p or len(p) < 3:
        return
    pos = (float(p[0]), float(p[1]), float(p[2]))
    rnd = stats.get("rounds")
    tr = stats.get("_walk")
    if not isinstance(tr, dict) or stats.get("_walk_round") != rnd:
        stats["_walk_round"] = rnd
        stats["_walk"] = tr = {"last": pos, "start": pos, "path": 0.0, "moved": now, "sample_at": now}
    step = math.dist(pos, tr["last"])
    dt = now - tr.get('sample_at', now)
    # A normal run can travel >500 mm between observations. The old fixed
    # cutoff reset the entire round's distance, reporting 0.8 m for a 148 m run.
    discontinuity = dt < 0 or dt > 2.0 or step > 500.0 + max(0.0, dt) * 12000.0
    if discontinuity:
        tr.update(last=pos, moved=now)
        stats['walk_discontinuities'] = stats.get('walk_discontinuities', 0) + 1
    elif step > 1.0:
        tr["path"] += step
        tr["moved"] = now
        tr["last"] = pos
    tr['sample_at'] = now
    net = math.dist(pos, tr["start"])
    stats["walk_m"] = round(tr["path"] / 1000.0, 1)                       # the ground he covered
    stats["walk_net_m"] = round(net / 1000.0, 1)                          # how far he got from where the round began
    stats["walk_straight"] = round(net / tr["path"], 2) if tr["path"] > 10.0 else None
    stats["walk_still_s"] = round(now - tr["moved"], 1)
    # ...and under the names the run reviewer already reads (gbox.mercs.round_reports' route/checkpoint groups), so a
    # round's maneuvering reaches the report instead of being published in my own vocabulary and lost.
    still_s = stats["walk_still_s"]
    stats["navigation_distance_m"] = stats["walk_m"]
    stats["motion_idle_spin_s"] = still_s                                 # standing, and turning on the spot
    if still_s >= 1.0:                                                    # a full second without moving a millimetre
        if not tr.get("counted_still"):
            tr["counted_still"] = True
            stats["nav_oscillations"] = stats.get("nav_oscillations", 0) + 1
    elif still_s < 0.2:
        tr["counted_still"] = False
# The bow's loop: the operator asked for 20x (2026-11-10 #9508, and again 2026-11-11: "have the bow able to fire at
# 20x speed ... rain arrows"). It was 0.025 - only 2x the rifle's 0.05, which is why 20x never appeared however the
# trigger was tuned. 0.05 / 20 = 0.0025: one decision every 2.5 ms, twenty times the gun's loop.
BOW_FIGHT_TICK_S = 0.0025
GUN_TAP_HOLD_S = 0.02                   # explicit pulse; bypass the keyboard adapter's implicit 60 ms batch hold
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
        self.native_selection = None

    def observe(self, snap: dict, now: float) -> None:
        game = snap.get("game")
        if isinstance(game, dict):
            if not self.phases or self.phases[-1] != game.get("phase"):
                self.phases.append(game.get("phase"))
            if game.get("in_control") and game.get("clock_running"):
                self.live_seen = True
                stage, character = game.get('stage'), game.get('mode')
                if self.native_selection is None and type(stage) is int and type(character) is int \
                        and 0 <= stage < len(driver.STAGES) and 0 <= character < len(driver.CHARACTERS):
                    self.native_selection = {'stage': stage, 'player': character}
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


def _round_selection(rnd):
    pick = getattr(rnd, 'native_selection', None) or driver.SELECTION
    character = driver.CHARACTERS[pick.get("player") or 0]
    stage = driver.STAGES[pick.get("stage") or 0]
    return stage, character, 'native_mercsys' if getattr(rnd, 'native_selection', None) else 'requested'


def _boundary(rnd: Round, end: dict, snap: dict, stats: dict, at: float) -> dict:
    stage, character, source = _round_selection(rnd)
    witness = {**end, "playing_observed": rnd.clock_counting or rnd.player_seen,
               "player_verified": rnd.player_seen, "clock_verified": rnd.clock_counting,
               "kills": stats.get("kills_seen"), "kills_source": stats.get("kills_source"),
               "clock_addr": hex(snap["clock_addr"]) if isinstance(snap.get("clock_addr"), int) else None,
               "hud_seen": rnd.hud_seen, "character_source": source, "stage_source": source}
    return {"round_id": rnd.id, "at": at, "map_id": MAP_ID, "role": "solo_p1", "source": "native_terminal_reader",
            "mode": "mercenaries", "stage": stage, "character": character, "witness": witness}


def _ring_step(ad, stats):
    """The bot's own grenade ring for this title (gbox.mercs.grenade_ring): its per-tick step, or None.

    The rule refuses on its own (the flash minute, the learned blast reach, no player); this hook only gives it the
    playbook's tick and keys. Built once per run so its history and cooldown survive the round.
    """
    try:
        from .mercs import grenade_ring
        # units_per_cm: RE4's snapshot positions are the game's millimetres (re4_switch.MM_PER_CM = 10), and the ring
        # rule speaks centimetres. Without it every distance the rule saw was 10x too big, so an 8 m boss never
        # counted as "within 800 cm" and the defensive/periodic rings could not see it.
        step = grenade_ring.control(ad, {"map_id": MAP_ID, "menus": "gbox.mercs.titles.re4_switch",
                                         "units_per_cm": driver.MM_PER_CM})
        if step is None and stats is not None:
            # A None here means the rule declined this title (never a game refusal). It used to be a silent None, and
            # the operator could not tell "the ring never armed" from "the ring is waiting" (live 2026-11-12: no
            # ring_armed key at all on RE4). Name the ids so the next read is an answer, not a hypothesis.
            stats["grenade_ring_error"] = (f"the ring rule declined map_id {MAP_ID!r}: "
                                           f"RING_TITLES={sorted(getattr(grenade_ring, 'RING_TITLES', ()))}")[:300]
        return step
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
        driver.begin_run(selection=pick, mercmode=((game or {}).get('launch') or {}).get('mercmode'))
        if pick:
            stats["queued_selection"] = (f"{driver.CHARACTERS[driver.SELECTION['player'] or 0]} / "
                                         f"{driver.STAGES[driver.SELECTION['stage'] or 0]}")
    except ValueError as exc:
        driver.begin_run()
        stats["queued_selection_error"] = str(exc)[:160]
    m = m if m is not None else _memory(ad)
    stats["ram"] = m is not None
    bot = driver.Bot(stats=stats, clock=clock) if m is not None else None
    driver.WEAPON_ASK.clear()                        # a weapon request never survives from the run before this one
    ring_step = _ring_step(ad, stats)                # the bot's own ring rule (gbox.mercs.grenade_ring)
    started = clock()
    last_step = 0.0
    ticks = 0
    in_round = False
    rnd: Round | None = None
    transport_send = send
    def recorded_send(events):
        receipt = transport_send(events)
        cap = getattr(rnd, 'capture', None)
        if cap is not None:
            try:
                cap.input(clock(), events, receipt)
            except Exception as exc:
                # Evidence is downstream of the accepted pad command. A stale
                # recorder during activation must never terminate gameplay.
                stats['input_record_error'] = f'{type(exc).__name__}: {exc}'[:160]
                stats['input_record_failures'] = stats.get('input_record_failures', 0) + 1
        return receipt
    send = recorded_send
    keys = Keys(send, sleep=sleep)
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
        if bot is not None and hasattr(bot, "new_round"):
            bot.new_round()
        walk.round_start()
        walk_stats(True)

    def round_ended() -> None:
        walk.round_end()
        walk_stats(True)
        if any(driver.RANDOM_SELECTION.values()):
            stats['selection_redraw_pending'] = True
    unknown_since = None
    seen_menu, prev_where = False, None             # title_returns: the title again after a menu (an idle return or
                                                    # a back press), the stat that tells a walk loop on the live panel

    screen = {"where": None}
    last_phase, off_round = None, 0
    checker = CrossCheck(stats, clock)
    try:
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
            from .mercs.titles import re4_switch_weapon_native
            re4_switch_weapon_native.observe_round(getattr(ad, '_re4_switch_harness', None), gs, time.monotonic())
            phase = gs.get("phase") if gs else None
            live = bool(gs) and phase in ("playing", "grabbed") and bool(gs.get("clock_running"))
            ram_round = (bool(gs) and phase in driver.ROUND_PHASES and (live or where in FRAME_UNSURE)
                         and (in_round or phase not in ('dead', 'results')))
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
                    if rnd is not None and rnd.posted is None:
                        _record_round(rnd, {"screen": "interrupted"}, stats)
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
                    from .mercs import primary_weapon
                    native_player = dict(snap.get("player") or {})
                    native_player["generation"] = native_player.get("generation", native_player.get("id"))
                    if primary_weapon.release_for_handover(stats, dict(snap, player=native_player),
                                                          lambda _keys: (keys.release() or True)):
                        _capture_round(rnd, snap, bot, stats, clock())
                        sleep(FIGHT_TICK_S)
                        continue
                    _maintain_mods(ad, snap, stats, keys.release)
                    if rnd is not None:
                        rnd.observe(snap, clock())
                        if live and where == "playing":
                            rnd.hud_seen = True
                        if rnd.terminal(snap, clock()) is not None:
                            _capture_round(rnd, snap, bot, stats, clock())
                        _report(rnd, snap, stats, clock(), round_boundary, keys)
                if bot is not None and snap is not None:
                    stats["fight"] = "ram"
                    if ring_step is not None:
                        try:
                            ring_out = ring_step(snap, stats, clock(), lambda _keys: (keys.release() or True))
                            stats["ring_armed"] = True
                            stats["ring_step_reason"] = str(ring_out.get("reason") or "")[:200]
                            if ring_out.get("fired"):
                                _capture_round(rnd, snap, bot, stats, clock())
                                sleep(FIGHT_TICK_S)
                                continue
                        except Exception as exc:
                            stats["ring_error"] = f"{type(exc).__name__}: {exc}"[:160]
                    bonus_goal(bot, snap, clock())            # the nearest time bonus as a point goal (BONUS_ROUTE)
                    keys.apply(bot.tick(snap, now=clock()),
                               tap_hold=BOW_TAP_HOLD_S if is_bow(snap) else GUN_TAP_HOLD_S)
                    _capture_round(rnd, snap, bot, stats, clock())
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
                if where == 'select_player' and stats.pop('selection_redraw_pending', False):
                    stats['next_selection'] = driver.next_selection()
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
                    if bot is not None and hasattr(bot, "record_death"):
                        bot.record_death(clock())
                    # What killed him. This posted hp=None, so a death reached the round report with no health and no
                    # position (ten Krauser/Waterworld rounds read outcome=died with round_threat_hits=0 - no damage
                    # counted - and nothing to say why), which is exactly the "instant kill or slow bleed?" question. The
                    # last snapshot has both: his life and how close the nearest live Ganado was.
                    _dsnap = last_snap or {}
                    _dpl = _dsnap.get("player") or {}
                    _dp = _dpl.get("pos")
                    _dnear = None
                    if _dp:
                        _dds = [math.dist(_dp, e["pos"]) for e in (_dsnap.get("enemies") or ())
                                if e.get("pos") and (e.get("hp") or 0) > 0]
                        _dnear = round(min(_dds) / 1000.0, 1) if _dds else None
                    stats["death_hp"] = _dpl.get("hp")
                    stats["death_hp_max"] = _dpl.get("hp_max")
                    stats["death_nearest_m"] = _dnear
                    if rnd is not None and rnd.posted is None and rnd.player_seen:
                        # the round's end, witnessed by the game's own death screen (mercmode.accept_boundary)
                        _post(rnd, {"screen": "dead", "death_screen": True, "hp": _dpl.get("hp"),
                                    "nearest_m": _dnear}, _dsnap, stats, clock(), round_boundary, keys)
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
                if rnd is not None and rnd.posted is None:
                    _record_round(rnd, {"screen": "interrupted"}, stats)
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
                _maintain_mods(ad, snap, stats, keys.release)
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
                        stats["ring_step_reason"] = str(ring_out.get("reason") or "")[:200]
                        if ring_out.get("fired"):
                            re4_walk.publish(pub, snap, bot, "playing")
                            sleep(BOW_FIGHT_TICK_S if is_bow(snap) else FIGHT_TICK_S)
                            continue
                bonus_goal(bot, snap, clock())                # the nearest time bonus as a point goal (BONUS_ROUTE)
                keys.apply(bot.tick(snap, now=clock()),
                           tap_hold=BOW_TAP_HOLD_S if is_bow(snap) else GUN_TAP_HOLD_S)
                _capture_round(rnd, snap, bot, stats, clock())
                re4_walk.publish(pub, snap, bot, "playing")
                sleep(BOW_FIGHT_TICK_S if is_bow(snap) else FIGHT_TICK_S)
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

    finally:
        keys.release()
        if rnd is not None and rnd.posted is None:
            _record_round(rnd, {"screen": "interrupted"}, stats)
        cap = getattr(rnd, "capture", None)
        if cap is not None:
            cap.wait(2.0)
        if pub is not None:
            pub.close()
    stats["ended"] = clock()
    stats["seconds"] = round(stats["ended"] - started, 1)
    return {"ok": True, "mode": "re4-switch-ram" if stats.get("fight") == "ram" else "re4-switch-screen",
            "rounds": stats["rounds"], "presses": stats["presses"], "seconds": stats["seconds"],
            "boundaries_posted": stats["boundaries_posted"],
            "note": ("RAM fight: player, Ganados and the clock read from memory" if stats.get("fight") == "ram" else
                     "frame-only fight: the player and Ganados are not mapped in RAM yet (re4_switch.PLAYER_CLASS)")}


def _maintain_mods(ad, snap: dict, stats: dict, release_inputs=None) -> None:
    """The live sidebar's RE4 mods (re4_switch_mods.maintain: health caps, time per kill) on this snapshot."""
    try:
        from .mercs.titles import re4_switch_mods
        done = re4_switch_mods.maintain(ad, snap, release_inputs=release_inputs)
    except Exception as exc:                                 # noqa: BLE001 - a mod never costs the fight
        stats["mods_error"] = f"{type(exc).__name__}: {exc}"[:160]
        return
    for k, v in (done or {}).items():
        key = "mods_" + k
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            stats[key] = v                                   # a record (a round's weapon): shown, never summed
            continue
        stats[key] = stats.get(key, 0) + v
    if ad is not None and (snap.get('game') or {}).get('phase') in ('playing', 'grabbed'):
        try:
            from .mercs.interventions import native_controller
            ctl = native_controller(ad)
            if ctl is not None and callable(getattr(ctl, 'maintain_mines', None)):
                ctl.maintain_mines(snap, stats)
        except (OSError, ValueError, RuntimeError) as exc:
            stats['mine_dart_error'] = f'{type(exc).__name__}: {exc}'[:180]
    # The live states the mods keep (not numeric: shown, never summed): the bow's class/routine and the aim lock's
    # counters, so the watch panel can say whether the 40x / the steady aim is actually on (live 2026-11-11: the
    # Krauser rounds' shots/hits needed exactly this to be readable).
    try:
        st = re4_switch_mods._state(ad)
    except Exception:                                        # noqa: BLE001 - a read never costs the fight
        return
    if (snap or {}).get("weapon_class") is not None:
        stats["weapon_class"] = (snap or {}).get("weapon_class")
    # The bow's two witnesses, published so a round can say which one (if either) named the bow: the operator's "the bow
    # is supposed to be firing 20x" has to be answerable from telemetry instead of inferred from the same silence.
    if (snap or {}).get("equipped_id") is not None:
        stats["equipped_id"] = (snap or {}).get("equipped_id")
    stats["bow"] = is_bow(snap)
    # Why the laser line was refused, when it was: the aim ticket's per-class evidence (the steady aim needs the line,
    # and the ~40% rounds could not say whether the class byte, the ray's origin or its length was refusing).
    if (snap or {}).get("laser_gate"):
        stats["laser_gate"] = (snap or {}).get("laser_gate")
    # Whether the round's weapon actually landed in his hand - a refused give leaves him on his stock loadout (Wesker's
    # Samurai Edge), which reads as a pistol round and kills nothing. Never published before, so a "0 kills" round could
    # not say whether it had a magnum at all.
    given = st.get("weapon_given")
    if isinstance(given, dict):
        stats["weapon_given"] = (f"{given.get('name') or given.get('id')} verified={given.get('verified')} "
                                 f"{given.get('reason') or ''}").strip()[:160]
    # heal_below proves the threshold heal's setting actually loaded (it was dropped twice: once by SAVED_KEYS, once by
    # the cached state) and heals proves it acted - both were invisible, so a heal that never ran looked like a heal that
    # ran and never triggered.
    for key in ("motion_rate_kind", "motion_rate_class", "motion_rate_routine", "aim_ram_writes", "aim_sway_zeroed",
                "heal_below", "heals", "first_aid_stock", "first_aid_last", "round_weapon", "crowd_weapon",
                "gun_rate_state", "gun_rate_error", "gun_rate_configured_x", "gun_rate_applied_x",
                "gun_rate_scaled_frames", "gun_rate_restores", "gun_rate_observation"):
        if st.get(key) is not None:
            stats[key] = st[key]
    # Whether the bow's 40x motion write is ON, and why it was refused: the state keeps it under st["motion_rate"]
    # ({"kind", "speed", "addrs"}), which nothing published - so every round read motion=8/ with the speed blank and the
    # operator's "the bow isn't 20x" could not be checked from telemetry at all.
    mr = st.get("motion_rate")
    if isinstance(mr, dict):
        stats["motion_rate_speed"] = mr.get("speed")
        stats["motion_rate_kind"] = stats.get("motion_rate_kind") or mr.get("kind")
    for key in ("motion_rate_restores", "motion_rate_refused", "motion_rate_refused_last"):
        if st.get(key) is not None:
            stats[key] = st[key]
    # How he is manoeuvring, so a run can be reviewed on numbers: metres walked, how straight the path was, and how long
    # he has stood still (see walk_track).
    walk_track(stats, snap, time.time())
    # His health, which the snapshot reads (re4_switch.player_life, module PLAYER_LIFE) and nothing published. The
    # objective is "I dont want the bot getting hurt", and a round report could not show it: round_threat_hits is the
    # doctrine's count of his health FALLING (respond._hurt), so 0 with outcome=died means the death was a single
    # transition the counter never saw - an instant kill, not a slow loss. hp/hp_max make that checkable live.
    pl = (snap or {}).get("player") or {}
    if isinstance(pl.get("hp"), int):
        prev = stats.get("hp")
        stats["hp"] = pl["hp"]
        if isinstance(pl.get("hp_max"), int):
            stats["hp_max"] = pl["hp_max"]
        # How big each blow was, not just that one happened. A death otherwise reads "dmg=1" whether a single hit took
        # him from full to zero or three did, and those need opposite fixes (avoidance versus more healing). Last hit as
        # "before->after", its size, the largest of the round, and how many landed (live 2026-11-12: a 68-kill round died
        # and nothing could say whether it was a one-shot).
        if isinstance(prev, int) and pl["hp"] < prev:
            took = prev - pl["hp"]
            stats["last_hit"] = f"{prev}->{pl['hp']}"
            stats["last_hit_dmg"] = took
            stats["max_hit_dmg"] = max(int(stats.get("max_hit_dmg") or 0), took)
            stats["hit_events"] = int(stats.get("hit_events") or 0) + 1
            # WHO dealt it. max_hit_dmg 1860 says a single attack takes the whole bar, but not which enemy - and six
            # rounds died at 13-25 kills with that number and nothing to point at (live 2026-11-12). The nearest living
            # enemy at the instant the health fell is the best attribution available without the game's own damage
            # event, so its size, class and distance go on the record.
            try:
                me = pl.get("pos")
                foes = [e for e in (snap.get("enemies") or ()) if (e.get("hp") or 0) > 0 and e.get("pos")]
                if me and foes:
                    near = min(foes, key=lambda e: math.hypot(e["pos"][0] - me[0], e["pos"][2] - me[2]))
                    stats["last_hit_foe_hp_max"] = near.get("hp_max")
                    stats["last_hit_foe_class"] = near.get("class")
                    stats["last_hit_foe_m"] = round(
                        math.hypot(near["pos"][0] - me[0], near["pos"][2] - me[2]) / 100.0, 1)
            except (TypeError, KeyError, ValueError, IndexError):
                pass
    elif "life_raw" in pl:
        # The read refused: these are the three u16s at PLAYER_LIFE - 2 (life in the middle). Without them a blank hp
        # is indistinguishable from a missing player or a bad base, and both damage tracking and the heal need hp.
        stats["life_raw"] = pl["life_raw"]
    # The doctrine's damage answer counters, so a round says whether he was hurt at all (respond.py owns them).
    for key in ("threat_hits", "hurt_while_idle", "threat_unanswered", "threat_forced_fire", "threat_ticks"):
        if st.get(key) is not None:
            stats[key] = st[key]
    # The stage's TIME BONUSES, which the operator wants him going after ("traversing the level, going after the
    # objectives"). Every stage json carries them (r400 8, r402 9, r403 15, r404 15) and nothing read them until now, so
    # a round could not say whether an objective was even on the map. bonus_nearest_* is where the route will aim.
    nav = (snap or {}).get("nav")
    if nav is not None and hasattr(nav, "nearest_bonus"):
        try:
            nb = nav.nearest_bonus(((snap or {}).get("player") or {}).get("pos"))
            stats["bonus_n"] = len(getattr(nav, "bonuses", ()) or ())
            if nb is not None:
                stats["bonus_nearest_m"] = round(nb[0] / 1000.0, 1)
                stats["bonus_nearest_s"] = nb[1].get("seconds")
        except Exception as exc:                     # noqa: BLE001 - a bonus read never costs the fight
            stats["bonus_error"] = f"{type(exc).__name__}: {exc}"[:120]


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
    re4_walk.re4_nav.attach(snap)
    if snap.get("weapon_unmapped") is not None:              # (named on the snap: snapshot() has no stats to write)
        stats["weapon_unmapped"] = snap["weapon_unmapped"]
    else:
        stats.pop('weapon_unmapped', None)
    stats['equipped_item'] = snap.get('equipped_id')
    stats['equipped_class'] = snap.get('weapon_class')
    stats['weapon_object_item'] = (snap.get('aim') or {}).get('item')
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
    stats.update(round_evidence_id=rnd.id, round_evidence_closed=False)
    rnd.counter_base = {key: stats.get(key, 0) for key in ROUND_COUNTERS}
    from .mercs import lessons, run_capture
    rnd.capture = run_capture.RunCapture(lessons.ROOT.parent / "round_maps", MAP_ID, rnd.id,
                                        provenance=stats, position_scale_to_cm=.1)
    return rnd


def _capture_round(rnd, snap, bot, stats, now):
    cap = getattr(rnd, "capture", None)
    if cap is not None and snap is not None:
        hp = (snap.get("player") or {}).get("hp")
        dead = isinstance(hp, (int, float)) and hp <= 0
        cap.observe(now, "dead" if dead else "playing", snap, bot, stats)


def _record_round(rnd: Round, end: dict, stats: dict) -> None:
    """Write this round's curriculum row (`gbox.mercs.notebook`): the round reports' source, which RE4 had none of.

    The row carries the provenance `round_reports.provenance` checks for a native solo round (the exact session id and
    the autoplay job that started the run, seeded by `play`), this round's own counter amounts (round_<key>) and the
    round's telemetry, so the next report shows the raise/lower, the tangents and the stand breaks the operator judges a
    block by. Best effort: a failure is a stat, never the round's end.
    """
    if getattr(rnd, "evidence_recorded", False):
        return
    rnd.evidence_recorded = True
    stats['round_evidence_closed'] = True
    outcome = {"results": "completed", "dead": "died"}.get(end.get("screen"), "interrupted")
    stage, character, selection_source = _round_selection(rnd)
    cap = getattr(rnd, "capture", None)
    if cap is not None:
        stats.update(cap.finish(time.time(), outcome, stage=stage))
    sid, jid = stats.get("source_session_id"), _job_id(stats.get("source_autoplay_job_id"))
    if not isinstance(sid, str) or not sid or not jid:
        stats["round_notebook"] = "skipped: no exact session/autoplay start to attribute the round to"
        return
    try:
        from .mercs import lessons as lesson_store
        from .mercs.notebook import Notebook
        observed = dict(stats)
        observed.update(round_stage_source=selection_source, round_character_source=selection_source)
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
            stage, "mercenaries", character,
            outcome, observed, round_id=rnd.id)
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
