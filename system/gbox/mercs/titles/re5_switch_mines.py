"""RE5 Switch proximity bombs left behind (operator 2026-10-27: "In RE5, I want them placing a landmine every X second as
they navigate the level leaving behind the mine for it to be used on the enemy").

The supply: re5_switch_mods.mine_loadout puts the proximity bomb x5 (0x10A, WP0A MINE_B) at grid 1 (D-pad up) in Chris
(BSAA)'s loadout template. infinite_ammo's no-ammo flag on WP0A keeps the stack at 5: the HUD shows infinity and a
placement spends none.

How a bomb goes down (live 2026-10-27, two private Citron runs on the Spark; docs/evidence/re5-switch-mines):
  * D-pad up with a neutral pad: the bomb is in hand within 0.2 s (the slot's hand flag), motion 20;
  * ZL alone places it. Tapped 0.25 s: one bomb. The placing motion (29) starts 0.02-0.17 s after the press; the bomb
    shows 0.57-0.69 s after it (and the count falls then, when the flag is off); the motion ends at ~1.3 s. ZL held
    places another every ~1.25 s (1.5 s held: two). ZL+ZR does exactly what ZL alone does: nothing is thrown;
  * the bomb lies ~57 cm ahead of his feet, on the ground: a new unit of class uWp0a on sUnit's move line 11
    (re5_switch.ground_mines -> snapshot "ground_mines"). "Proximity bomb / Y Pick up" shows beside it;
  * a Majini within ~1 m sets it off: two stacked bombs killed 3 (score 0 -> 900) and took 700 of Chris's 1000 at 3.8 m.
    His own bombs hurt him: never two together, never one with a Majini near, and out of the blast before one comes.

Mines (the bot's) places one every EVERY_S seconds of the round:
  * not with a Majini within FOE_CLEAR_CM, not within SPACING_CM of the last site or of a bomb of his still down, not
    while held, healing, escaping or dying;
  * the gun comes down and the pad rests NEUTRAL_S (the D-pad equip needs a neutral pad: the PS3's verified second),
    the bomb's D-pad slot, then ZL tapped PRESS_S; confirmed by a new bomb on the ground near him or the count falling,
    within PLACE_S;
  * the placing motion plays out (he cannot move in it), then he runs RETREAT_S out through the widest gap among the
    Majini, the bomb counted among them (never back over it), at least RETREAT_CM from it, and the gun comes back by
    its own D-pad slot;
  * the guard, all round: a Majini within TRIGGER_CM of a bomb of his while he is within BLAST_CM of it: he runs out of
    its blast the same way.
A placement counts (mines_placed) only when confirmed. One whose placing motion was seen but no bomb or count drop came
still sends him out of its way (mine_unconfirmed); one with neither waits EVERY_S again.

What the bombs did (the round's counters): a bomb that leaves sUnit's line went off (mines_gone; the bot never picks one
up). The live blast showed the kills a poll before the units left the line, so a window from BLAST_BEFORE_S before the
first bomb seen gone to BLAST_AFTER_S after the last one is the blast: mine_kills the cGameSys kills gained in it,
mine_blast_hp_loss his health lost in it (his own bomb's damage, or a Majini's in the same second), mine_blasts the
windows.
"""
from __future__ import annotations

import collections
import math

MINE_ID = 0x10A
EVERY_S = 120.0                          # one every two minutes while he plays the round (tunable)
SPACING_CM = 600.0                       # never within this of the last site or of a bomb still down (a double blast)
FOE_CLEAR_CM = 500.0                     # a Majini this near: not now (out of the blast before it comes: a run of 8 m;
                                         # was 8 m - none were ever placed in a No Mercy crowd, 19:50 / 19:53)
NEUTRAL_S, EQUIP_S = 0.5, 1.2
PRESS_S, PLACE_S = 0.25, 1.5             # ZL tapped (held, a second bomb at 1.25 s); the bomb shows by 0.7 s
MOTION_PLACE = 29                        # the placing motion (the same byte as a shot)
SETTLE_S = 1.6                           # the placing motion plays at most this long (live: 1.27-1.41 s from the press)
CONFIRM_CM = 200.0                       # a new bomb this near where he stood is his (it lands ~57 cm ahead)
RETREAT_CM, RETREAT_S, RETREAT_GAP_R = 800.0, 3.0, 800.0
BLAST_CM, TRIGGER_CM = 800.0, 350.0      # the guard: a Majini this near a bomb of his, him within BLAST_CM of it: out
REARM_S = 1.2
QUICK = {1: "dup", 3: "dleft", 5: "dright", 7: "ddown"}
RUN = ("b", "lup")
KNIVES = frozenset({0x01, 0x0E, 0x14, 0x23, 0x24})
THROWN = frozenset({0x06, 0x07, 0x08, 0x0A})        # grenades and the bomb: never the gun to go back to
BLAST_BEFORE_S, BLAST_AFTER_S = 0.6, 0.4  # the blast window around the bombs leaving the line (kills show first)
COUNTERS = ("mines_placed", "mine_attempts", "mine_unconfirmed", "mine_retreats_completed", "mine_equip_failures",
            "mines_gone", "mine_clear_runs", "mine_blasts", "mine_kills", "mine_blast_hp_loss")


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


def flat(a, b) -> float:
    return math.hypot(b[0] - a[0], b[2] - a[2])


class Mines:
    """The placement cycle: idle -> neutral -> equip -> place -> settle -> retreat -> rearm -> idle, and the blast guard
    while idle. tick() returns this tick's pad action while a cycle or the guard runs (the bot's survival rules come
    first), None otherwise."""

    def __init__(self, stats: dict, every_s: float = EVERY_S):
        self.stats = stats
        self.every_s = every_s
        self.enabled = True                            # the `mines` op can switch new placements off (configure)
        self.state, self.t = "idle", 0.0
        self.last_at, self.last_pos = None, None       # the last placement (confirmed, or its motion seen)
        self.round_t0 = None
        self.count0 = None
        self.ground0: set = set()                      # the uWp0a units before the press
        self.site = None                               # where the bomb went down (the retreat's origin)
        self.bombs: dict = {}                          # his bombs still on the ground: unit -> position
        self.saw_place = False
        self.clear_from = None                         # the bomb the guard is running from
        self.gun_grid = None
        self.hist = collections.deque(maxlen=64)       # (t, kills, his health) of the recent ticks
        self.blast = None                              # the open blast window: {"t0", "until", "kills", "hp"}
        self._tracked_at = None
        for k in COUNTERS:
            self.stats.setdefault(k, 0)

    def configure(self, settings: dict) -> None:
        """The operator's `mines` op (re5_switch_mods.mines, through the driver's snapshot): on / off and the cadence."""
        self.enabled = bool(settings.get("enabled", True))
        try:
            self.every_s = max(2.0, float(settings.get("interval_s") or self.every_s))
        except (TypeError, ValueError):
            pass
        self.stats["mine_interval_s"] = self.every_s
        self.stats["mines_enabled"] = self.enabled

    def new_round(self, now: float) -> None:
        self.state, self.t, self.round_t0 = "idle", now, now
        self.last_at, self.last_pos, self.site, self.clear_from = None, None, None, None
        self.bombs, self.blast = {}, None
        self.hist.clear()

    @staticmethod
    def stack(inv) -> dict | None:
        return next((s for s in inv or () if s.get("id") == MINE_ID and (s.get("rounds") or 0) > 0
                     and s.get("grid") in QUICK), None)

    def watch(self, p: dict, snap: dict, now: float) -> None:
        """Every tick, whatever the bot decided (held, healing, fighting): the bombs and their blasts (_track)."""
        self._track(p, snap, now)

    def _track(self, p: dict, snap: dict, now: float) -> None:
        """His bombs still down: one that left sUnit's line went off. Its blast window: the kills gained and his health
        lost from BLAST_BEFORE_S before it to BLAST_AFTER_S after the last bomb seen gone. Once a tick."""
        if self._tracked_at == now:
            return
        self._tracked_at = now
        kills, hp = snap.get("kills"), p.get("hp")
        self.hist.append((now, kills, hp))
        b = self.blast
        if b is not None and now >= b["until"]:
            if isinstance(kills, int) and isinstance(b["kills"], int):
                self.stats["mine_kills"] += max(0, kills - b["kills"])
            if isinstance(hp, int) and isinstance(b["hp"], int):
                self.stats["mine_blast_hp_loss"] += max(0, b["hp"] - max(hp, 0))
            self.blast = None
        if not self.bombs or "ground_mines" not in snap:
            return
        now_ptrs = {g["ptr"] for g in snap.get("ground_mines") or ()}
        gone = [k for k in self.bombs if k not in now_ptrs]
        for ptr in gone:
            del self.bombs[ptr]
            self.stats["mines_gone"] += 1
        if gone:
            if self.blast is None:
                before = [h for h in self.hist if h[0] >= now - BLAST_BEFORE_S] or [self.hist[-1]]
                self.blast = {"t0": now, "until": now + BLAST_AFTER_S, "kills": before[0][1], "hp": before[0][2]}
                self.stats["mine_blasts"] += 1
            else:
                self.blast["until"] = now + BLAST_AFTER_S

    def due(self, p: dict, snap: dict, live: list, now: float) -> str | None:
        """Why a cycle may start now (None: not now)."""
        if not self.enabled or self.stack(snap.get("inventory")) is None:
            return None
        start = self.last_at if self.last_at is not None else self.round_t0
        if start is None:
            self.round_t0 = start = now
        if now - start < self.every_s:
            return None
        pos = p["pos"]
        sites = ([self.last_pos] if self.last_pos is not None else []) + list(self.bombs.values())
        if any(flat(pos, b) < SPACING_CM for b in sites):
            self.stats["mine_status"] = "moving away from the last bomb first"
            return None
        if any(flat(pos, e["pos"]) < FOE_CLEAR_CM for e in live):
            self.stats["mine_status"] = "a Majini too close to place one"
            return None
        return "due"

    def _clear(self, p: dict, live: list) -> dict | None:
        """The guard: a Majini at a bomb of his while he stands in its blast: out through the widest gap."""
        pos = p["pos"]
        for ptr, b in self.bombs.items():
            if flat(pos, b) < BLAST_CM and any(flat(e["pos"], b) <= TRIGGER_CM for e in live):
                if self.clear_from != ptr:
                    self.clear_from = ptr
                    self.stats["mine_clear_runs"] += 1
                self.stats["mine_status"] = "a Majini at his bomb: out of its blast"
                return self._run(p, live, b)
        self.clear_from = None
        return None

    def tick(self, p: dict, snap: dict, live: list, now: float, *, busy: bool = False) -> dict | None:
        inv = snap.get("inventory") or ()
        mine = self.stack(inv)
        self._track(p, snap, now)
        if self.state == "idle":
            act = self._clear(p, live)
            if act is not None or busy or self.due(p, snap, live, now) is None:
                return act
            gun = next((s for s in inv if s.get("hand") and s.get("type") == 1 and s.get("item") not in THROWN), None)
            self.gun_grid = gun.get("grid") if gun else self.gun_grid
            self.state, self.t = "neutral", now
            self.stats["mine_status"] = "placing a bomb: the pad rests"
            return {"hold": ()}
        if busy and self.state in ("neutral", "equip"):
            self.state, self.t = "rearm", now            # held / ringed before the press: give it up, the gun back
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
                self.state, self.t, self.saw_place = "place", now, False
                self.count0 = mine.get("rounds")
                self.ground0 = {g["ptr"] for g in snap.get("ground_mines") or ()}
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
            self.saw_place = self.saw_place or p.get("motion") == MOTION_PLACE
            spent = mine is None or (self.count0 is not None and (mine.get("rounds") or 0) < self.count0)
            new = [g for g in snap.get("ground_mines") or ()
                   if g["ptr"] not in self.ground0 and self.site is not None and flat(self.site, g["pos"]) <= CONFIRM_CM]
            if spent or new:
                self.stats["mines_placed"] += 1
                self.stats["mine_status"] = "bomb down: leaving it behind"
                if new:
                    self.site = tuple(new[0]["pos"])
                    self.bombs[new[0]["ptr"]] = self.site
                self.last_at, self.last_pos = now, self.site
                self.state, self.t = "settle", now
                return {"hold": ()}
            if now - self.t > PLACE_S:
                self.stats["mine_unconfirmed"] += 1
                self.last_at = now
                if self.saw_place:                        # it may be down all the same: out of its way
                    self.stats["mine_status"] = "placement unconfirmed: leaving all the same"
                    self.last_pos = self.site
                    self.state, self.t = "retreat", now
                    return self._run(p, live, self.site)
                self.stats["mine_status"] = "placement unconfirmed"
                self.state, self.t = "rearm", now
                return {"hold": ()}
            return {"hold": ("zl",)} if now - self.t < PRESS_S else {"hold": ()}
        if self.state == "settle":                        # the placing motion: he cannot move until it ends
            if p.get("motion") == MOTION_PLACE and now - self.t < SETTLE_S:
                return {"hold": ()}
            self.state, self.t = "retreat", now
            return self._run(p, live, self.site)
        if self.state == "retreat":
            away = self.site is not None and flat(p["pos"], self.site) >= RETREAT_CM
            if away or now - self.t > RETREAT_S:
                if away:
                    self.stats["mine_retreats_completed"] += 1
                self.state, self.t = "rearm", now
                return {"hold": ()}
            return self._run(p, live, self.site)
        if self.state == "rearm":
            guns = [s for s in inv if s.get("type") == 1 and s.get("grid") in QUICK
                    and s.get("item") not in KNIVES and s.get("item") not in THROWN]
            gun = next((s for s in guns if s.get("grid") == self.gun_grid), None) or next(iter(guns), None)
            if gun is None or gun.get("hand") or now - self.t > REARM_S:
                self.state = "idle"                       # (re5_switch.Bot._gun_back keeps at it after this)
                return None
            if now - self.t < 0.3:
                return {"hold": ()}                       # (a neutral pad before the D-pad)
            self.t = now - REARM_S + 0.6                  # one tap, then wait for it
            return {"tap": QUICK[gun["grid"]]}
        return None

    def _run(self, p: dict, live: list, site) -> dict:
        """Run out through the widest gap among the Majini within RETREAT_GAP_R, the bomb at site counted among them."""
        pos = p["pos"]
        near = sorted(heading(e["pos"][0] - pos[0], e["pos"][2] - pos[2]) for e in live
                      if flat(pos, e["pos"]) < RETREAT_GAP_R)
        if site is not None and flat(pos, site) > 1.0:
            near = sorted(near + [heading(site[0] - pos[0], site[2] - pos[2])])   # the bomb is a "Majini"
        if near:
            gaps = [((near[(i + 1) % len(near)] - a) % (2 * math.pi) or 2 * math.pi, a) for i, a in enumerate(near)]
            gap, start = max(gaps)
            out = wrap(start + gap / 2)
        else:
            out = p["rot"]
        err = wrap(out - p["rot"])
        turn = () if abs(err) < math.radians(15) else (("rleft",) if err > 0 else ("rright",))
        return {"hold": RUN + turn}
