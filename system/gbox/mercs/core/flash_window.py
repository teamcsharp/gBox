"""The flash: where it goes off (never at his feet) and what he does while they reel - for every title with a flash.

The operator, 2026-11-10: "When the bot flashbangs, do not have the bot impacted by the explosion. Skip making them
stunned. Have the bot dropping landmines and running around during the flashbang making optimal use of their time";
"never let the bot get stunned by their own flash grenades. I want the bot able to use that time to plan mines and
throw grenades and clear the crowd. But they need to only be able to flashbang once a minute or on a slider."

  place()   the point a flash goes off: the crowd's centre round him (the nearer ones weigh more: 1 / d), pushed out to
            min_cm from him along the line to it and never past max_cm, on his floor - so the blast is on THEM and he
            stands min_cm or more from it. No one within from_cm on his level: None (no flash is wanted).
  Window    the seconds after a confirmed flash while they reel: plan() names this tick's step, in order -
              mine   a mine first, once a window (the title's own controller plants it, its clearances and the learned
                     blast reach kept; the reeling ones block nothing);
              throw  then a grenade at the stunned pack, once a window, when one lies outside his blast reach;
              move   then a step to open floor that puts them in front of him at a firing distance (spot()): at most
                     move_s of it, only to a spot the title's clear() allows;
              fire   then the fight on the stunned ones.
            Counted (stats flash_window_*): windows, mines, throws, moves, fires, kills (the kill count's rise inside it).
Positions in cm, his facing in radians (0 = +z, + toward +x): the title converts. Nothing here reads or writes the game.
"""
from __future__ import annotations

import math
import time
from collections import namedtuple

from . import combat

Step = namedtuple("Step", "kind point why")
COUNTERS = ("flash_window_windows", "flash_window_mines", "flash_window_throws", "flash_window_moves",
            "flash_window_fires", "flash_window_kills", "flash_window_idle")
FIRE_SPOT_CM = 500.0             # the spot is this far from the stunned ones' centre
TOO_CLOSE_CM = 220.0             # one of them nearer than this: step back before firing
SPREAD_RAD = math.radians(50.0)  # them wider than this either side of the line to their centre: step to bring them in
SPOT_TRIES_DEG = (0, 30, -30, 60, -60, 90, -90)


def _flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


def place(player, enemies, min_cm: float = 400.0, max_cm: float = 900.0, from_cm: float = 1200.0,
          level_cm: float = 200.0):
    """The flash's point (see the module text), or None. player / enemies: (x, y, z) cm."""
    if player is None:
        return None
    near = [q for q in enemies or () if q is not None and _flat(player, q) <= from_cm
            and abs(q[1] - player[1]) <= level_cm]
    if not near:
        return None
    w = [1.0 / max(_flat(player, q), 100.0) for q in near]
    cx = sum(wi * q[0] for wi, q in zip(w, near)) / sum(w)
    cz = sum(wi * q[2] for wi, q in zip(w, near)) / sum(w)
    dx, dz = cx - player[0], cz - player[2]
    d = math.hypot(dx, dz)
    if d < 1.0:                                        # round him on every side: toward the nearest
        q = min(near, key=lambda q: _flat(player, q))
        dx, dz = q[0] - player[0], q[2] - player[2]
        d = math.hypot(dx, dz)
        if d < 1.0:
            dx, dz, d = 0.0, 1.0, 1.0
    r = max(min_cm, min(max_cm, d))
    return (player[0] + dx / d * r, player[1], player[2] + dz / d * r)


def spot(player, stunned, clear=None, dist_cm: float = FIRE_SPOT_CM):
    """A firing spot dist_cm from the stunned ones' centre on his side of it (then turned 30 / 60 / 90 deg either way),
    the first one clear(player, spot) allows; None when none does or nobody reels."""
    if not stunned or player is None:
        return None
    cx = sum(q[0] for q in stunned) / len(stunned)
    cz = sum(q[2] for q in stunned) / len(stunned)
    base = combat.heading(player[0] - cx, player[2] - cz)
    for deg in SPOT_TRIES_DEG:
        h = base + math.radians(deg)
        s = (cx + dist_cm * math.sin(h), player[1], cz + dist_cm * math.cos(h))
        if clear is None or clear(player, s):
            return s
    return None


def needs_move(player, stunned) -> str | None:
    """Why he should step before firing on them: one too close, or them spread past SPREAD_RAD; None: fire from here."""
    if not stunned:
        return None
    if any(_flat(player, q) < TOO_CLOSE_CM for q in stunned):
        return "one of them at arm's length"
    cx = sum(q[0] for q in stunned) / len(stunned)
    cz = sum(q[2] for q in stunned) / len(stunned)
    h = combat.heading(cx - player[0], cz - player[2])
    if any(abs(combat.wrap(combat.heading(q[0] - player[0], q[2] - player[2]) - h)) > SPREAD_RAD for q in stunned):
        return "them spread round him"
    return None


class Window:
    """One flash's window (see the module text): opened by a confirmed flash, its steps counted once each."""

    def __init__(self, stats: dict | None = None, window_s: float = 3.5, move_s: float = 0.9):
        self.stats = stats if stats is not None else {}
        self.window_s, self.move_s = float(window_s), float(move_s)
        self.at = None                                   # the flash's time (the title's clock)
        self.mined = self.thrown = False
        self.move_since = None
        self.moved = False
        self.kills0 = None
        for k in COUNTERS:
            self.stats.setdefault(k, 0)

    def open(self, at: float, kills=None) -> None:
        if self.at is not None and abs(at - self.at) < 1e-6:
            return
        self.at, self.mined, self.thrown, self.move_since, self.moved = at, False, False, None, False
        self.kills0 = kills if isinstance(kills, int) and not isinstance(kills, bool) else None
        self.stats["flash_window_windows"] = self.stats.get("flash_window_windows", 0) + 1

    def active(self, now: float) -> bool:
        return self.at is not None and 0.0 <= now - self.at <= self.window_s

    def observe(self, now: float, kills) -> None:
        """The kill count inside the window: its rise is the window's (flash_window_kills)."""
        if self.at is None or self.kills0 is None or not isinstance(kills, int) or isinstance(kills, bool):
            return
        if kills > self.kills0 and now - self.at <= self.window_s + 0.5:
            self.stats["flash_window_kills"] = self.stats.get("flash_window_kills", 0) + (kills - self.kills0)
            self.kills0 = kills
        elif kills < self.kills0:
            self.kills0 = kills

    def plan(self, now: float, player, stunned, mine_ready: bool, throw_ready: bool, clear=None,
             blast_cm: float = 400.0) -> Step | None:
        """This tick's step (None: no window). player / stunned in cm."""
        if not self.active(now) or player is None:
            return None
        if not stunned:
            return Step("fire", None, "the flash: nobody reels within reach")
        if mine_ready and not self.mined:
            self.mined = True
            self.stats["flash_window_mines"] = self.stats.get("flash_window_mines", 0) + 1
            return Step("mine", tuple(player), f"the flash: a mine while {len(stunned)} reel")
        far = [q for q in stunned if _flat(player, q) >= blast_cm]
        if throw_ready and not self.thrown and len(far) >= 2:
            self.thrown = True
            self.stats["flash_window_throws"] = self.stats.get("flash_window_throws", 0) + 1
            cx = sum(q[0] for q in far) / len(far)
            cz = sum(q[2] for q in far) / len(far)
            return Step("throw", (cx, player[1], cz), f"the flash: a grenade at {len(far)} reeling")
        why = needs_move(player, stunned)
        if why is not None and not self.moved:
            if self.move_since is None:
                self.move_since = now
            if now - self.move_since <= self.move_s:
                s = spot(player, stunned, clear)
                if s is not None:
                    if now == self.move_since:
                        self.stats["flash_window_moves"] = self.stats.get("flash_window_moves", 0) + 1
                    return Step("move", s, f"the flash: to a firing spot ({why})")
            self.moved = True
        self.stats["flash_window_fires"] = self.stats.get("flash_window_fires", 0) + 1
        return Step("fire", None, f"the flash: fire on {len(stunned)} reeling")


# --- when a flash is allowed at all (the operator 2026-11-10: "flashes should only come in tight situations where the bot
# actually needs help. Some enemies can't be beaten by a flash and must be killed with weapons. Constant flashes are
# distracting and disorienting for viewers") ---------------------------------------------------------------------------
TIGHT_REASONS = ("grabbed", "windup", "surrounded", "low_falling")
TIGHT_N, TIGHT_CM, TIGHT_LOW, TIGHT_FALL_S = 4, 300.0, 0.35, 1.5


def tight(player, enemies, held: bool = False, hp_frac=None, fell_s_ago=None, escape_clear=None,
          n: int = TIGHT_N, r_cm: float = TIGHT_CM, low: float = TIGHT_LOW, fall_s: float = TIGHT_FALL_S) -> str | None:
    """The tight situation a flash answers, or None (a crowd alone is none). enemies: [{"pos" cm, "immune": the flash
    does not stop him (a boss, an armoured or heavy one: weapons, never a flash), "windup": a melee wind-up, "reach"}]:
      grabbed     a hold on him;
      windup      a flashable one winding up within his reach and no clear way out (escape_clear not True);
      surrounded  n or more flashable within r_cm and no clear way out;
      low_falling his health at low or under and falling within fall_s, a flashable one within r_cm."""
    if held:
        return "grabbed"
    if player is None:
        return None
    flashable = [e for e in enemies or () if e.get("pos") and not e.get("immune")]
    d = {id(e): _flat(player, e["pos"]) for e in flashable}
    near = [e for e in flashable if d[id(e)] <= r_cm]
    if escape_clear is not True and any(e.get("windup") and d[id(e)] <= float(e.get("reach") or r_cm) for e in flashable):
        return "windup"
    if escape_clear is not True and len(near) >= n:
        return "surrounded"
    if isinstance(hp_frac, (int, float)) and hp_frac <= low and isinstance(fell_s_ago, (int, float)) \
            and 0.0 <= fell_s_ago <= fall_s and near:
        return "low_falling"
    return None


GATE_COUNTERS = ("flash_gap_skips", "flash_untight_skips", "flashes_gated")


class FlashGate:
    """One flash clock for a title, every automatic flash path asking allow() and saying stamp() (stats): the last flash
    from any source - a path's stamp (flash_stamp_at) or a native receipt (native_flash_confirmed_at: his own, the
    ring's, the operator's emergency click, which is never gated but holds the next) - at least gap_s() ago (wall clock),
    and a tight reason (tight()) when need_reason. Skips counted (flash_gap_skips, flash_untight_skips, per path
    flash_skip_<path>); each flash's reason kept (flash_reason_last, flash_reasons {reason: n}, flash_paths {path: n})."""

    def __init__(self, stats: dict | None = None, gap_s=lambda: 60.0, need_reason=lambda: True, clock=time.time):
        self.stats = stats if stats is not None else {}
        self.gap_s, self.need_reason, self.clock = gap_s, need_reason, clock
        for k in GATE_COUNTERS:
            self.stats.setdefault(k, 0)

    def last(self) -> float:
        vals = [self.stats.get(k) for k in ("flash_stamp_at", "native_flash_confirmed_at")]
        return max([v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)] or [-math.inf])

    def on_gap(self) -> bool:
        return self.clock() - self.last() < float(self.gap_s())

    def allow(self, path: str, reason: str | None) -> bool:
        if self.on_gap():
            self.stats["flash_gap_skips"] = self.stats.get("flash_gap_skips", 0) + 1
            self.stats[f"flash_skip_{path}"] = self.stats.get(f"flash_skip_{path}", 0) + 1
            return False
        if reason is None and self.need_reason():
            self.stats["flash_untight_skips"] = self.stats.get("flash_untight_skips", 0) + 1
            self.stats[f"flash_skip_{path}"] = self.stats.get(f"flash_skip_{path}", 0) + 1
            return False
        return True

    def stamp(self, path: str, reason: str | None) -> None:
        self.stats["flash_stamp_at"] = self.clock()
        self.stats["flashes_gated"] = self.stats.get("flashes_gated", 0) + 1
        self.stats["flash_reason_last"] = f"{path}: {reason or 'no reason needed'}"[:120]
        for key, k in (("flash_reasons", reason or "none"), ("flash_paths", path)):
            d = self.stats.get(key)
            if not isinstance(d, dict):
                d = self.stats[key] = {}
            d[k] = d.get(k, 0) + 1
