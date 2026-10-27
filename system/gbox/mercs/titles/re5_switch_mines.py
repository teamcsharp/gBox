"""RE5 Switch proximity bombs left behind (operator 2026-10-27: "In RE5, I want them placing a landmine every X second as
they navigate the level leaving behind the mine for it to be used on the enemy").

The supply: re5_switch_mods.mine_loadout puts the proximity bomb x5 (0x10A, WP0A) at grid 1 (D-pad up) in Chris
(BSAA)'s loadout template, and infinite_ammo's no-ammo flag (WP0A +0x1C) keeps a placement from spending one; if the
count still falls, the bot keeps it from emptying (the spray's count-keeping, never a record replay).

Mines (the bot's) places one every EVERY_S seconds of the round (the PS3's re5_mines rules, re5-mine-settings.json's
idea, for a Majini crowd that comes to him):
  * not with a Majini within FOE_CLEAR_CM (a grab or the blast mid-placement), not within SPACING_CM of the last site,
    not while held, healing, escaping or dying;
  * the gun comes down and the pad rests NEUTRAL_S (the D-pad equip needs a neutral pad: the PS3's verified second),
    the bomb's D-pad slot, then ZL held ("ZL Place", Type D) until the count falls or a new ground bomb shows near him,
    at most PLACE_S;
  * then he runs RETREAT_S out through the widest gap among the Majini (away from the bomb: never standing on it), at
    least RETREAT_CM from it, and the gun comes back by its own D-pad slot.
A placement is counted only when it is confirmed (mines_placed); an unconfirmed one waits EVERY_S again.
"""
from __future__ import annotations

import math

MINE_ID = 0x10A
EVERY_S = 9.0                            # one this often while he plays the round (tunable)
SPACING_CM = 300.0                       # never within this of the last bomb's site
FOE_CLEAR_CM = 150.0                     # a Majini this near: not now
NEUTRAL_S, EQUIP_S, PLACE_S = 0.5, 1.2, 1.3
CONFIRM_CM = 200.0                       # a new ground bomb this near him is his
RETREAT_CM, RETREAT_S, RETREAT_GAP_R = 350.0, 1.6, 800.0
REARM_S = 1.2
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
RUN = ("b", "lup")
KNIVES = frozenset({0x01, 0x0E, 0x14, 0x23, 0x24})


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


class Mines:
    """The placement cycle: idle -> neutral -> equip -> place -> retreat -> rearm -> idle. tick() returns this tick's
    pad action while a cycle runs (the bot's survival rules come first), None when idle."""

    def __init__(self, stats: dict, every_s: float = EVERY_S):
        self.stats = stats
        self.every_s = every_s
        self.state, self.t = "idle", 0.0
        self.last_at, self.last_pos = None, None       # the last confirmed placement
        self.round_t0 = None
        self.count0 = None
        self.ground0: set = set()
        self.site = None                               # where the bomb went down (the retreat's origin)
        self.gun_grid = None
        for k in ("mines_placed", "mine_attempts", "mine_unconfirmed", "mine_retreats_completed", "mine_equip_failures"):
            self.stats.setdefault(k, 0)

    def new_round(self, now: float) -> None:
        self.state, self.t, self.round_t0 = "idle", now, now
        self.last_at, self.last_pos, self.site = None, None, None

    @staticmethod
    def stack(inv) -> dict | None:
        return next((s for s in inv or () if s.get("id") == MINE_ID and (s.get("rounds") or 0) > 0
                     and s.get("grid") in QUICK), None)

    def due(self, p: dict, snap: dict, live: list, now: float) -> str | None:
        """Why a cycle may start now (None: not now)."""
        if self.stack(snap.get("inventory")) is None:
            return None
        start = self.last_at if self.last_at is not None else self.round_t0
        if start is None:
            self.round_t0 = start = now
        if now - start < self.every_s:
            return None
        pos = p["pos"]
        if self.last_pos is not None and flat(pos, self.last_pos) < SPACING_CM:
            self.stats["mine_status"] = "moving away from the last bomb first"
            return None
        if any(flat(pos, e["pos"]) < FOE_CLEAR_CM for e in live):
            self.stats["mine_status"] = "a Majini too close to place one"
            return None
        return "due"

    def tick(self, p: dict, snap: dict, live: list, now: float, *, busy: bool = False) -> dict | None:
        inv = snap.get("inventory") or ()
        mine = self.stack(inv)
        if self.state == "idle":
            if busy or self.due(p, snap, live, now) is None:
                return None
            gun = next((s for s in inv if s.get("hand") and s.get("type") == 1 and s.get("id") != MINE_ID), None)
            self.gun_grid = gun.get("grid") if gun else self.gun_grid
            self.state, self.t = "neutral", now
            self.stats["mine_status"] = "placing a bomb: the pad rests"
            return {"hold": ()}
        if busy and self.state in ("neutral", "equip", "place"):
            self.state, self.t = "rearm", now            # held / hit mid-cycle: give it up, the gun back
            return None
        if self.state == "neutral":
            if now - self.t < NEUTRAL_S:
                return {"hold": ()}
            if mine is None:
                self.state = "idle"
                return None
            self.state, self.t = "equip", now
            self.stats["mine_attempts"] += 1
            return {"tap": QUICK[mine["grid"]]}
        if self.state == "equip":
            if mine is not None and mine.get("hand"):
                self.state, self.t = "place", now
                self.count0 = mine.get("rounds")
                self.ground0 = {tuple(round(v) for v in g) for g in snap.get("ground_mines") or ()}
                self.site = tuple(p["pos"])
                return {"hold": ("zl",)}
            if now - self.t > EQUIP_S:
                self.stats["mine_equip_failures"] += 1
                self.stats["mine_status"] = "the bomb did not come to hand"
                self.state, self.t = "rearm", now
                self.last_at = now                        # wait a whole interval before the next try
                return None
            return {"hold": ()}
        if self.state == "place":
            placed = mine is None or (self.count0 is not None and (mine.get("rounds") or 0) < self.count0)
            new = [g for g in snap.get("ground_mines") or ()
                   if tuple(round(v) for v in g) not in self.ground0 and flat(p["pos"], g) <= CONFIRM_CM]
            if placed or new:
                self.stats["mines_placed"] += 1
                self.stats["mine_status"] = "bomb down: leaving it behind"
                self.site = tuple(new[0]) if new else self.site
                self.last_at, self.last_pos = now, self.site
                self.state, self.t = "retreat", now
                return self._run(p, live)
            if now - self.t > PLACE_S:
                self.stats["mine_unconfirmed"] += 1
                self.stats["mine_status"] = "placement unconfirmed"
                self.last_at = now
                self.state, self.t = "rearm", now
                return {"hold": ()}
            return {"hold": ("zl",)}
        if self.state == "retreat":
            if (self.site is not None and flat(p["pos"], self.site) >= RETREAT_CM) or now - self.t > RETREAT_S:
                if self.site is not None and flat(p["pos"], self.site) >= RETREAT_CM:
                    self.stats["mine_retreats_completed"] += 1
                self.state, self.t = "rearm", now
                return {"hold": ()}
            return self._run(p, live)
        if self.state == "rearm":
            gun = next((s for s in inv if s.get("type") == 1 and s.get("grid") == self.gun_grid
                        and s.get("item") not in KNIVES), None) \
                or next((s for s in inv if s.get("type") == 1 and s.get("grid") in QUICK and s.get("id") != MINE_ID
                         and s.get("item") not in KNIVES), None)
            if gun is None or gun.get("hand") or now - self.t > REARM_S:
                self.state = "idle"
                return None
            if now - self.t < 0.3:
                return {"hold": ()}                       # (a neutral pad before the D-pad)
            self.t = now - REARM_S + 0.6                  # one tap, then wait for it
            return {"tap": QUICK[gun["grid"]]}
        return None

    def _run(self, p: dict, live: list) -> dict:
        """Run out through the widest gap among the Majini within RETREAT_GAP_R, never back over the bomb."""
        pos = p["pos"]
        near = sorted(heading(e["pos"][0] - pos[0], e["pos"][2] - pos[2]) for e in live
                      if flat(pos, e["pos"]) < RETREAT_GAP_R)
        if self.site is not None and flat(pos, self.site) > 1.0:
            near = sorted(near + [heading(self.site[0] - pos[0], self.site[2] - pos[2])])   # the bomb is a "Majini"
        if near:
            gaps = [((near[(i + 1) % len(near)] - a) % (2 * math.pi) or 2 * math.pi, a) for i, a in enumerate(near)]
            gap, start = max(gaps)
            out = wrap(start + gap / 2)
        else:
            out = p["rot"]
        err = wrap(out - p["rot"])
        turn = () if abs(err) < math.radians(15) else (("rleft",) if err > 0 else ("rright",))
        return {"hold": RUN + turn}
