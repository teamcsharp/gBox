"""The Mercenaries stalemate rule, shared by the RE4 (gbox.re4_merc_bot) and RE5 (gbox.mercs.titles.re5_ps3) bots.

Operator 2026-10-26: "in mercenaries mode, sometimes the match ends up in a stalemate where the bot has nothing but
time and no enemies ... the ability to set the time left in the mercenaries timer to a custom time like 5 seconds".
While a round plays, when no living enemy has been seen for STALEMATE_S (none appeared in that time) and the clock
still shows more than STALEMATE_CLOCK_S, the bot cuts the clock to the configured seconds (DEFAULT_CUT_S) once per
round, through each title's verified clock write (RE5: re5_mods_tool.set_clock, the aGame owner path; RE4:
re4_merc_bot.cut_clock, the MERC_TIMER word). A round that never showed an enemy is never cut (a slow spawn at the
start is not a stalemate).

Settings reach the bots the way MercMode's other options do (rounds_per_title): the host's MercMode settings
(gbox.mercmode: stalemate_cut on/off, stalemate_cut_s) ride in the launch payload (game.launch.mercmode) and
configure() copies them into the run's stats, which both bots share with their engine (stats["stalemate_cut_enabled"],
stats["stalemate_cut_s"]). Without a launch setting the rule is on, at DEFAULT_CUT_S.
"""
from __future__ import annotations

STALEMATE_S = 15.0           # no living enemy for this long ...
STALEMATE_CLOCK_S = 10.0     # ... while the clock shows more than this: a stalemate
HUNT_STALEMATE_S = 45.0      # ... or this long where the bot can hunt the stage's spawn points first (RE5's spawn hunt,
                             # re5_ps3.LULL_S / _hunt_spawns: the clock is cut only once the hunt has had its chance)
DEFAULT_CUT_S = 5            # the clock is cut to this many seconds (operator: "like 5 seconds")
CUT_MIN_S, CUT_MAX_S = 1, 60 # the configurable range (the UI's "Set clock to N s" uses the same bounds)
RETRY_S, ATTEMPTS = 2.0, 3   # an unverified write is tried again this much later, this many times per round
ENABLED_KEY, SECONDS_KEY = "stalemate_cut_enabled", "stalemate_cut_s"


def cut_seconds(value, default: int = DEFAULT_CUT_S) -> int:
    """A whole number of seconds in CUT_MIN_S..CUT_MAX_S, else the default."""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return n if CUT_MIN_S <= n <= CUT_MAX_S else default


def settings(launch_mercmode) -> dict:
    """{"enabled", "seconds"} from a launch payload's mercmode block (gbox.screensaver puts the host's MercMode
    stalemate_cut / stalemate_cut_s there); anything missing or malformed takes the default (on, DEFAULT_CUT_S)."""
    cfg = launch_mercmode if isinstance(launch_mercmode, dict) else {}
    enabled = cfg.get("stalemate_cut")
    return {"enabled": enabled if type(enabled) is bool else True,
            "seconds": cut_seconds(cfg.get("stalemate_cut_s"))}


def configure(stats: dict, game=None) -> dict:
    """The run's rule settings into stats (the bots read them each tick), from game.launch.mercmode."""
    cfg = settings(((game or {}).get("launch") or {}).get("mercmode"))
    stats[ENABLED_KEY], stats[SECONDS_KEY] = cfg["enabled"], cfg["seconds"]
    return cfg


class Rule:
    """One bot's stalemate watch. observe() each tick with the living enemy count and the clock; it returns the target
    seconds when the cut is due (at most ATTEMPTS writes per round, RETRY_S apart while unverified); record() keeps
    the result in stats ("stalemate_cut": clock before / after, when, how long without enemies) and on the round map."""

    def __init__(self, stats, stalemate_s: float = STALEMATE_S, clock_s: float = STALEMATE_CLOCK_S):
        # stats: the run's dict, or a callable returning it (the engines rebind bot.stats after construction)
        self._stats = stats
        self.stalemate_s, self.clock_s = float(stalemate_s), float(clock_s)
        self.new_round()

    @property
    def stats(self) -> dict:
        return self._stats() if callable(self._stats) else self._stats

    def new_round(self) -> None:
        self.no_enemy_since = None       # when the field emptied (None while an enemy is alive or none was seen yet)
        self.seen_enemy = False          # an enemy has been alive this round (a slow start is not a stalemate)
        self.attempts = 0
        self.done = False                # a verified cut, or every attempt used
        self.last_attempt = None
        self.target = None

    @property
    def enabled(self) -> bool:
        value = self.stats.get(ENABLED_KEY, True)
        return value if type(value) is bool else True

    @property
    def seconds(self) -> int:
        return cut_seconds(self.stats.get(SECONDS_KEY))

    def idle_s(self, now: float) -> float:
        return round(now - self.no_enemy_since, 1) if self.no_enemy_since is not None else 0.0

    def observe(self, now: float, living: int, timer, patience=None) -> int | None:
        """The target seconds when a cut is due now, else None. living: enemies alive this tick; timer: the clock;
        patience: the seconds without enemies this tick needs (default stalemate_s; a bot that can hunt spawn points
        passes HUNT_STALEMATE_S so the hunt goes first)."""
        wait = self.stalemate_s if patience is None else float(patience)
        self.stats["stalemate_patience_s"] = wait
        if living > 0:
            self.seen_enemy = True
            self.no_enemy_since = None
            self.stats["stalemate_idle_s"] = 0.0
            return None
        if not self.seen_enemy:
            return None
        if self.no_enemy_since is None:
            self.no_enemy_since = now
        idle = now - self.no_enemy_since
        self.stats["stalemate_idle_s"] = round(idle, 1)
        if self.done or not self.enabled or idle < wait:
            return None
        if not isinstance(timer, (int, float)) or timer <= self.clock_s:
            return None
        if self.last_attempt is not None and now - self.last_attempt < RETRY_S:
            return None
        if self.attempts >= ATTEMPTS:
            self.done = True
            return None
        self.attempts += 1
        self.last_attempt = now
        self.target = max(CUT_MIN_S, min(self.seconds, int(timer)))   # never add time: a clock under the target stays
        return self.target

    def record(self, now: float, result: dict, trace=None, pos=None) -> dict:
        """What the write did, into stats and the round map (a 'stalemate_cut' event where he stood)."""
        verified = bool(result.get("verified"))
        before, after = result.get("clock_before"), result.get("clock_after")
        idle = self.idle_s(now)
        row = {"at": round(now, 2), "idle_s": idle, "target_s": self.target, "clock_before": before,
               "clock_after": after, "verified": verified, "attempt": self.attempts}
        if result.get("reason"):
            row["reason"] = str(result["reason"])[:160]
        self.stats["stalemate_cut"] = row
        if verified:
            self.done = True
            self.stats["stalemate_cuts"] = self.stats.get("stalemate_cuts", 0) + 1
            self.stats["stalemate_status"] = (f"stalemate: no enemies for {idle:g} s, clock cut {before} -> {after} s")
        else:
            self.stats["stalemate_status"] = f"stalemate cut not verified: {row.get('reason', 'write not confirmed')}"
            if self.attempts >= ATTEMPTS:
                self.done = True
        if trace is not None and pos is not None:
            try:
                trace.event(now, "stalemate_cut", pos[0], pos[-1], clock_before=before, clock_after=after,
                            target_s=self.target, idle_s=idle, verified=verified)
            except Exception:                        # noqa: BLE001 - the map never stops the bot
                pass
        return row
