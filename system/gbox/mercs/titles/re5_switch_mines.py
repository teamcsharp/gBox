"""RE5 Switch Automine now drops native armed mines without equipping or input.

The default-on Automine switch is independent of inventory supply. Observed
movement queues one drop per twenty feet; hit/grab edges queue one defensive
drop. A single cancellable background worker leaves navigation and combat in
control. Only native arming/trigger observations count as placed mines. The
legacy controller below remains for replay tests, never automatic Bot admission.

Historical equip/plant calibration (operator 2026-10-27: "In RE5, I want them placing a landmine every X second as
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
  * not with a Majini within the margin (FOE_CLEAR_CM on time; an overdue bomb accepts a closer crowd, down to
    FOE_FLOOR_CM after RELAX_S, while he has RELAX_HP of his health), not within SPACING_CM of a bomb of his still
    down (or of an unconfirmed press's site, for UNCONFIRMED_SITE_S), not while held, healing or dying; ordinary
    fleeing can make room for the due placement;
  * the gun comes down and the pad rests NEUTRAL_S (the D-pad equip needs a neutral pad: the PS3's verified second),
    the bomb's D-pad slot, then ZL tapped PRESS_S; confirmed by a new native bomb actor on the ground near him,
    within PLACE_S;
  * the placing motion plays out (he cannot move in it), then he runs out through the widest gap among the Majini,
    the bomb counted among them (never back over it), until he is RETREAT_CM from it (15 m, the operator's standoff;
    RETREAT_S caps the run), and the gun comes back by its own D-pad slot;
  * the guard, all round: a Majini within TRIGGER_CM of a bomb of his while he is within BLAST_CM of it: he runs out of
    its blast the same way.
A placement counts (mines_placed) only when a new nearby uWp0a actor is observed. A count drop or placing motion alone
still sends him out of its way (mine_unconfirmed), but is not actor proof. An overdue placement blocked by clearance
buys a bounded run to a clearer site; it does not wait forever for stationary combat to create a gap.

What the bombs did (the round's counters): a bomb that leaves sUnit's line went off (mines_gone; the bot never picks one
up). The live blast showed the kills a poll before the units left the line, so a window from BLAST_BEFORE_S before the
first bomb seen gone to BLAST_AFTER_S after the last one is the blast: mine_kills the cGameSys kills gained in it,
mine_blast_hp_loss his health lost in it (his own bomb's damage, or a Majini's in the same second), mine_blasts the
windows.
"""
from __future__ import annotations

import collections
import math

from ..core import doctrine as _doctrine

MINE_ID = 0x10A
EVERY_S = 30.0                           # requested cadence; clearance/emergency actions can delay a placement
URGE_S = 3.0                             # Mines.urge: the doctrine's ask lets a plant skip the cadence this long
SPACING_CM = 600.0                       # never within this of the last site or of a bomb still down (a double blast)
FOE_CLEAR_CM = 500.0                     # a Majini this near: not now (out of the blast before it comes: a run of 8 m;
                                         # was 8 m - none were ever placed in a No Mercy crowd, 19:50 / 19:53)
# EQUIP_S / EQUIP_RETAP_S (2026-11-09): the bot turns the D-pad press into a native (RAM) equip request and swallows
# the press; when that request has not finished within its own NATIVE_EQUIP_GIVEUP_S (2.0 s) the next press goes
# through as a plain D-pad press. With one press and a 1.2 s window that next press never came: live that evening
# 36 of 88 attempts ended "the bomb did not come to hand", each ~3 s with the gun down. So the press repeats every
# EQUIP_RETAP_S while the bomb is not in hand, and the window outlasts the native give-up.
NEUTRAL_S, EQUIP_S, EQUIP_RETAP_S = 0.5, 2.6, 0.45
PRESS_S, PLACE_S = 0.25, 1.5             # ZL tapped (held, a second bomb at 1.25 s); the bomb shows by 0.7 s
MOTION_PLACE = 29                        # the placing motion (the same byte as a shot)
SETTLE_S = 1.6                           # the placing motion plays at most this long (live: 1.27-1.41 s from the press)
CONFIRM_CM = 200.0                       # a new bomb this near where he stood is his (it lands ~57 cm ahead)
# The operator, 2026-11-09: "the bot should place themself at least 15 meters from the mine to avoid hurting
# themselves" (the universal doctrine's MINE_STANDOFF_M). It was 8 m: live that day a Majini reached a bomb while he was
# 2-5 m off and the blast took 350 of his 1000. The run out lasts until he is that far (RETREAT_S is only its cap: 15 m
# is ~3.5 s of running plus the turn), and the guard keeps him that far from every bomb of his still down.
STANDOFF_CM = 100.0 * float(getattr(_doctrine, "MINE_STANDOFF_M", 15.0))
RETREAT_CM, RETREAT_S, RETREAT_GAP_R = STANDOFF_CM, 6.0, 800.0
BLAST_CM, TRIGGER_CM, CLOSE_MAJINI_CM = STANDOFF_CM, 350.0, 300.0
# The guard's two radii. A bomb with a Majini within DANGER_CM of it may go off any moment: he keeps the whole
# standoff (BLAST_CM). A bomb nobody is near just lies there (live 2026-11-09: one sat in a trench for two minutes):
# he only stays CALM_CM off it. With BLAST_CM alone, at the operator's 15 m, that bomb held him turning on the spot
# beside it - "in his own bomb's blast" for 116 s, three kills in six minutes. And a guard run that gains no ground
# for CLEAR_STUCK_S (a wall, a dead end) gives the pad back for CLEAR_YIELD_S: the fight and the map move him.
# CALM_DWELL_S, the same evening: a quiet bomb lay in a corridor between him and the Majini, the guard turned him
# back the moment he came within CALM_CM of it, and he went to and fro beside it for minutes (the operator's map:
# 234 kills at 14:01 and at 13:06, six Majini alive elsewhere). Walking past a bomb nobody is near is nothing (two
# seconds at a run); only standing beside it CALM_DWELL_S sends him off it.
DANGER_CM, CALM_CM, CLEAR_STUCK_S, CLEAR_YIELD_S, CLEAR_GAIN_CM = 800.0, 400.0, 2.5, 4.0, 100.0
CALM_DWELL_S = 4.0
# The combo and the bombs (operator 2026-11-09: "never ever lose the combo ... the amount of time left in it at all
# times"; and "I want the bot always placing mines"). A plant takes the gun out of his hand for 3 to 10 s, a combo
# window is 10: live that day 9 of 10 lost combos had a Majini in reach. So with a combo running a cycle starts only
# while COMBO_PLANT_MIN_S or more of its window is left (right after a kill), unless the bomb is COMBO_WAIT_S
# overdue; the run out ends once he is COMBO_STANDOFF_CM off and the window is down to COMBO_CUT_S (the gun back,
# the next kill); and the guard asks only COMBO_STANDOFF_CM of him while the window is that short. stats
# mine_combo_waits (ticks a due bomb waited for the window), mine_combo_cuts (runs out ended for the combo).
COMBO_PLANT_MIN_S, COMBO_WAIT_S, COMBO_CUT_S, COMBO_STANDOFF_CM = 8.0, 12.0, 4.0, 800.0
# A due bomb that is blocked (his last one too near, a Majini inside the margin) no longer takes the pad to run
# "to a clear placement site": that run went away from the last bomb into whatever wall was there, 1.5 s of every
# 4.5, against the fight's own heading - the standing the operator watched ("the bot should not sit idle and let
# these enemies sit idle"). The fight, the pursuit and the map move him; the bomb goes down the moment the site is
# clear (and the flash clears a crowd for it).
RELOCATE_RUN = False
# Bombs on the way (operator 2026-11-09: "as the bot is walking the level without enemies around, they need to be
# placing mines as they are navigating to the enemies to dispatch them"). With no Majini within TRAIL_CM of the bomb
# there is nothing to run from: no run out to the standoff (it took him back the way he came, up to 6 s) - the gun
# comes back and he goes on along his route, the bomb left behind him. stats mine_trail_plants.
TRAIL_CM = 2000.0
# the guard: a Majini this near a bomb of his, him within BLAST_CM of it: out. CLOSE_MAJINI_CM: a Majini this close
# to him while he is in the blast - he cannot run the gap through a close crowd (the cluster's remaining incidents),
# so the run is given up and the fight unloads on the threat instead. FOE_CLEAR_CM (5 m) is the placement's rule
# (a run of 8 m clears it); the guard's crowd rule is tighter and looser than the trigger: the recorded incident
# itself had the Majini at 300 cm, and he did run it (the replay keeps the run), while a tighter crowd is a death.
REARM_S = 1.2
RELOCATE_S, RELOCATE_PAUSE_S, RETRY_S = 1.5, 3.0, 3.0   # (was 3 s on, 1 s off: the gun down three seconds of four)
# No Mercy (operator 2026-11-09: "place them randomly every 30 seconds as they are traversing the level"). Live the same
# day on lilspark, MINE_FOE_CLEAR_CM 400: two rounds, 11 minutes, 80 kills and ONE bomb - a Majini stood inside the
# margin for 195 s on end, and the 40 s before that went on "moving away from the last bomb" whose blast was long over.
# All that time he ran for a clear site with the gun down, three seconds of every four, which the operator watched as
# "the bot just sits idle ... lets enemies close in on him without dispatching them". So: an overdue placement accepts
# a closer crowd second by second, down to a floor a grab does not cross during the plant (only while he has the
# health for the blast of a bomb a Majini reaches too soon), and the run for a clear site is a short burst that hands
# the pad back to the fight for longer than it took it.
RELAX_S = 10.0                           # overdue seconds over which the Majini margin shrinks to its floor
# Live the same evening at this floor: 13 bombs planted, about 8 of them went off on him (350 hp each) - a Majini
# 2.5 m off reaches the bomb while the placing motion still roots him. Asked whether to plant less, the operator:
# "mines are non negotiable ... I want it placing mines. Then flashbanging and running away and getting distance. I
# want the bot always placing mines" and "have him force his way out". So the margin has no health condition, and
# the answer to the crowd is the flash: the bot (re5_switch.Bot._mine_flash) sets one off the moment a bomb is down,
# and one to open the way when an overdue bomb is blocked at the floor; for FLASH_S after a flash the Majini around
# him are reeling and none of them blocks a plant (flash_until).
FOE_FLOOR_CM = 250.0                     # the least margin: the plant roots him ~1.3 s, a grab reaches ~1.5 m
RELAX_HP = 0.0                           # (no health condition: the operator's word; was 0.5, then 0.8)
FLASH_S = 3.5                            # a flash at his feet: this long nobody near him blocks a plant
UNCONFIRMED_SITE_S = 8.0                 # an unconfirmed press may have left a bomb nobody saw: its site blocks this long
GAP_S = 0.75                             # a tick gap longer than this (held, healing, a reload stall above this module)
                                         # pauses the cycle's clock: EQUIP_S/PLACE_S/SETTLE_S measure active control
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
        self.foe_clear_cm, self.spacing_cm = FOE_CLEAR_CM, SPACING_CM   # the driver may set its own each tick
        self.state, self.t = "idle", 0.0
        self.last_at, self.last_pos = None, None       # the last placement (confirmed, or its motion seen)
        self.round_t0 = None
        self.count0 = None
        self.ground0: set = set()                      # the uWp0a units before the press
        self.baseline = None                           # the uWp0a units up when the round's watch began: never his bombs
        self.site = None                               # where the bomb went down (the retreat's origin)
        self.bombs: dict = {}                          # his bombs still on the ground: unit -> position
        self.saw_place = False
        self.clear_from = None                         # the bomb the guard is running from
        self._clear_run = None                         # that run: {"ptr", "since", "best", "best_at"}
        self._clear_yield = -1e9                       # the guard gives the pad back until then (a run that stuck)
        self.gun_grid = None
        self.hist = collections.deque(maxlen=64)       # (t, kills, his health) of the recent ticks
        self.blast = None                              # the open blast window: {"t0", "until", "kills", "hp"}
        self._tracked_at = None
        self._retry_at = 0.0
        self._relocate_until, self._relocate_retry_at = None, 0.0
        self._blocked, self._avoid_site = None, None
        self._ground_observed = False
        self._tick_at = None                           # the previous tick's clock (the gap pause, GAP_S)
        self._site_until = None                        # last_pos blocks a placement until then (an unconfirmed press)
        self.flash_until = -1e9                        # a flash went off at his feet: no Majini blocks a plant until then
        self.close_in_blast_at = None                  # the tick the guard gave up a run for a close Majini (CRIT_FLASH)
        self.saw_spent = False
        self.native = None                            # created only after native live acceptance is enabled
        from .re5_native_mine_tactic import Cadence
        self.automine, self.cadence = True, Cadence()
        self._native_receipts = collections.deque(maxlen=32)
        self._native_receipt_census = {}
        self._native_hazards_seen = collections.deque(maxlen=80)
        self._native_escape = None
        for k in COUNTERS:
            self.stats.setdefault(k, 0)
        self.stats.setdefault("mine_last_actor", 0)
        self.stats.setdefault("mine_last_placed_at", 0.0)

    def configure(self, settings: dict) -> None:
        """The operator's `mines` op (re5_switch_mods.mines, through the driver's snapshot): on / off and the cadence."""
        self.enabled = bool(settings.get("enabled", True))
        self.automine = settings.get('automine', True) is not False
        self.stats['automine_enabled'] = self.automine
        try:
            self.every_s = max(2.0, float(settings.get("interval_s") or self.every_s))
        except (TypeError, ValueError):
            pass
        self.stats["mine_interval_s"] = self.every_s
        self.stats["mines_enabled"] = self.enabled

    def urge(self, now: float, secs: float = URGE_S) -> None:
        """The doctrine's ask (gbox.mercs.core.respond: they converge on him): for `secs` a placement need not wait out
        every_s - every clearance, spacing, combo and standoff rule of due() and the cycle still holds."""
        self._urge_until = now + secs
        self.stats["mine_urges"] = self.stats.get("mine_urges", 0) + 1

    def new_round(self, now: float) -> None:
        native = getattr(self, 'native', None)
        if native is not None:
            native.cancel()                            # never deliver the old attempt into a new round
        from .re5_native_mine_tactic import Cadence
        self.cadence = Cadence()
        self.state, self.t, self.round_t0 = "idle", now, now
        self._rearm_tap_at = -1e9
        self.last_at, self.last_pos, self.site, self.clear_from = None, None, None, None
        self.bombs, self.blast = {}, None
        self._native_receipt_census = {}
        self._native_hazards_seen.clear()
        self._native_escape = None
        self.baseline = None
        self._clear_run, self._clear_yield = None, -1e9
        self._calm_since = {}                          # quiet bombs he is beside: unit -> since when
        self.hist.clear()
        self._tracked_at = None
        self._retry_at = self._relocate_retry_at = 0.0
        self._tick_at = None
        self._site_until = None
        self._relocate_until = None
        self._blocked, self._avoid_site = None, None
        self._ground_observed = False
        self.saw_place = self.saw_spent = False
        self.stats.update(mine_overdue_s=0.0, mine_blocked_reason=None, mine_relocating=False,
                          mine_last_actor=0, mine_last_placed_at=0.0, mine_clearance_cm=self.foe_clear_cm)
        self.stats.pop("mine_last_confirmation", None)

    @staticmethod
    def stack(inv) -> dict | None:
        return next((s for s in inv or () if s.get("id") == MINE_ID and (s.get("rounds") or 0) > 0
                     and s.get("grid") in QUICK), None)

    @staticmethod
    def equipped(inv) -> dict | None:
        """The bomb in hand, whatever its grid record says.

        The D-pad equip can move the item's grid value (or hand it over from a record the loadout only just wrote),
        so requiring the quick-grid lookup here turned a successful press into "the bomb did not come to hand"
        (live 2026-11-09: mine_attempts 1 / mine_equip_failures 1 in the first round after the supply change).
        """
        return next((s for s in inv or () if s.get("id") == MINE_ID and (s.get("rounds") or 0) > 0
                     and s.get("hand")), None)

    def watch(self, p: dict, snap: dict, now: float) -> None:
        """Every tick, whatever the bot decided (held, healing, fighting): the bombs and their blasts (_track)."""
        self._track(p, snap, now)

    def _track(self, p: dict, snap: dict, now: float) -> None:
        """His bombs still down: one that left sUnit's line went off. Its blast window: the kills gained and his health
        lost from BLAST_BEFORE_S before it to BLAST_AFTER_S after the last bomb seen gone. Once a tick."""
        if self._tracked_at == now:
            return
        self._tracked_at = now
        if self.baseline is None and "ground_mines" in snap and self.state == "idle":   # (never mid-cycle)
            # What is on the line before he has planted anything is not a bomb of his: the stack keeps a dormant uWp0a
            # of its own there all round (Public Assembly: always at 557, 158, 1409). The guards skipped it only once
            # a press had recorded ground0, so until the round's first plant - and after a bot reload - he ran from it
            # whenever he came within BLAST_CM and gave up the placements he had started (live 2026-11-09, the day
            # BLAST_CM went from 8 m to the operator's 15: three attempts, none planted).
            self.baseline = {g["ptr"] for g in snap.get("ground_mines") or ()}
        kills, hp = snap.get("kills"), p.get("hp")
        self.hist.append((now, kills, hp))
        b = self.blast
        if b is not None and now >= b["until"]:
            if isinstance(kills, int) and isinstance(b["kills"], int):
                self.stats["mine_kills"] += max(0, kills - b["kills"])
            if isinstance(hp, int) and isinstance(b["hp"], int):
                self.stats["mine_blast_hp_loss"] += max(0, b["hp"] - max(hp, 0))
            self.blast = None
        if not self.bombs or snap.get('ground_mines') is None:
            return
        now_ptrs = {g["ptr"] for g in snap.get("ground_mines") or ()}
        # Engine reaction polling and Bot.tick can consume the same snapshot at
        # different clock times. Shallow decision copies retain the census list:
        # only a distinct read can contradict a receipt newer than that census.
        gone = [k for k in self.bombs if k not in now_ptrs
                and self._native_receipt_census.get(k) is not snap['ground_mines']]
        native_gone = {k for k in gone if k in self._native_receipt_census}
        observed_triggers = {r['ptr'] for r in snap.get('ground_mine_observations') or ()
                             if r.get('ptr') in native_gone and r.get('trigger_observed') is True
                             and r.get('native_owner') == p.get('ptr')}
        if self._native_escape is not None:
            for ptr in observed_triggers:
                self._native_escape['sites'].pop(ptr, None)
        if native_gone:
            self.stats['native_mine_removals_observed'] = self.stats.get('native_mine_removals_observed', 0) + len(native_gone)
            self.stats['native_mine_triggers_observed'] = self.stats.get('native_mine_triggers_observed', 0) + len(observed_triggers)
            self.stats['native_mine_removals_unattributed'] = self.stats.get('native_mine_removals_unattributed', 0) + len(native_gone - observed_triggers)
        for ptr in gone:
            del self.bombs[ptr]
            self._native_receipt_census.pop(ptr, None)
            self.stats["mines_gone"] += 1
        # Native disappearance may be recycling/inactivation; even an explosion
        # latch is a request, not damage proof. Keep legacy replay accounting,
        # but never turn native removals into inferred blasts, hits or healing.
        if set(gone) - native_gone:
            if self.blast is None:
                before = [h for h in self.hist if h[0] >= now - BLAST_BEFORE_S] or [self.hist[-1]]
                self.blast = {"t0": now, "until": now + BLAST_AFTER_S, "kills": before[0][1], "hp": before[0][2]}
                self.stats["mine_blasts"] += 1
            else:
                self.blast["until"] = now + BLAST_AFTER_S

    @staticmethod
    def combo_left(snap: dict) -> float | None:
        """Seconds left in a running combo's window, None without one (the doctrine's reading of the snapshot)."""
        read = getattr(_doctrine, "combo_left", None)
        if read is not None:
            return read(snap)
        combo, left = snap.get("combo"), snap.get("combo_timer")
        ok = type(combo) is int and combo > 0 and isinstance(left, (int, float)) and not isinstance(left, bool)
        return float(left) if ok and 0.0 < left < 600.0 else None

    def due(self, p: dict, snap: dict, live: list, now: float, *, native: bool = False) -> str | None:
        """Why a cycle may start now (None: not now)."""
        self._blocked, self._avoid_site = None, None
        self.stats["mine_blocked_reason"] = None
        start = self.last_at if self.last_at is not None else self.round_t0
        if start is None:
            self.round_t0 = start = now
        self.stats["mine_overdue_s"] = round(max(0.0, now - start - self.every_s), 2)
        if not self.enabled:
            self.stats["mine_blocked_reason"] = "disabled"
            return None
        if not native and self.stack(snap.get("inventory")) is None:
            self.stats["mine_blocked_reason"] = "no usable mine in a quick slot"
            return None
        if now - start < self.every_s and now >= getattr(self, "_urge_until", -1e9):
            return None
        if now < self._retry_at:
            self.stats["mine_blocked_reason"] = "retry cooldown"
            return None
        if "ground_mines" not in snap:
            self.stats["mine_blocked_reason"] = "ground mine observation unavailable"
            return None
        left = self.combo_left(snap)
        if not native and left is not None and left < COMBO_PLANT_MIN_S and self.stats["mine_overdue_s"] < COMBO_WAIT_S:
            self.stats["mine_blocked_reason"] = "the combo's window: after the next kill"
            self.stats["mine_combo_waits"] = self.stats.get("mine_combo_waits", 0) + 1
            return None
        if why := self._clearance(p, live, now, native=native):
            self.stats["mine_blocked_reason"] = self._blocked = why
            return None
        return "due"

    def margin(self, p: dict) -> float:
        """The Majini margin in force: foe_clear_cm on time, shrinking to FOE_FLOOR_CM over RELAX_S of overdue time.

        The full margin was never free in a No Mercy crowd (RELAX_S above), so an overdue bomb goes down with a Majini
        as near as the floor. Not below RELAX_HP of his health: a Majini who reaches the bomb before he is out of its
        blast costs up to a third of it, and the cadence is not worth the round."""
        full = self.foe_clear_cm
        floor = min(FOE_FLOOR_CM, full)
        over = float(self.stats.get("mine_overdue_s") or 0.0)
        hp, top = p.get("hp"), p.get("hp_max")
        hurt = isinstance(hp, (int, float)) and isinstance(top, (int, float)) and top > 0 and hp < RELAX_HP * top
        m = full if hurt or over <= 0.0 else max(floor, full - (full - floor) * min(1.0, over / RELAX_S))
        self.stats["mine_clearance_cm"] = round(m, 1)
        return m

    def _clearance(self, p: dict, live: list, now: float | None = None, committed: bool = False,
                   *, native: bool = False) -> str | None:
        """Keep the placement margins both before equip and immediately before pressing ZL.

        A bomb still down keeps its spacing (a double blast). The last site alone does not: once its bomb has gone
        off there is nothing there, and waiting to be SPACING_CM from it cost 40 s of a round (2026-11-09). Only an
        unconfirmed press, which may have left a bomb nobody saw, keeps its site, for UNCONFIRMED_SITE_S."""
        pos = p["pos"]
        sites = list(self.bombs.values())
        if self.last_pos is not None and self._site_until is not None and (now is None or now < self._site_until):
            sites.insert(0, self.last_pos)
        blocked = next((b for b in sites if flat(pos, b) < self.spacing_cm), None)
        if blocked is not None:
            self._avoid_site = blocked
            self.stats["mine_status"] = "moving away from the last bomb first"
            return "last bomb too close"
        # committed: the bomb is already in his hand (the gun came down for it half a second ago). Giving the plant
        # up there for a Majini at 3.5 m costs the same two seconds as planting and leaves nothing behind: live
        # 2026-11-09, eight attempts for one bomb. Only one inside the floor stops a plant that far along.
        margin = self.foe_clear_cm if native else min(self.margin(p), FOE_FLOOR_CM) if committed else self.margin(p)
        if not native and now is not None and now < self.flash_until:  # only the legacy placement's flash policy
            self.stats["mine_clearance_cm"] = margin = 0.0
        if any(flat(pos, e["pos"]) < margin for e in live):
            self.stats["mine_status"] = "a Majini too close to place one"
            return "enemy too close"
        return None

    def _relocate(self, p: dict, live: list, now: float) -> dict | None:
        """Seek clearance even in a close crowd; only planting requires the safety margin."""
        if self._relocate_until is not None and now >= self._relocate_until:
            self._relocate_until = None
            self._relocate_retry_at = now + RELOCATE_PAUSE_S
        if now < self._relocate_retry_at:
            self.stats["mine_relocating"] = False
            return None                                      # a bounded attempt, then combat can make space
        if self._relocate_until is None:
            self._relocate_until = now + RELOCATE_S
        self.stats["mine_relocating"] = True
        self.stats["mine_status"] = "mine due: running to a clear placement site"
        return self._run(p, live, self._avoid_site)

    def _clear(self, p: dict, snap: dict, live: list, now: float | None = None) -> dict | None:
        """The guard: the bot standing in an old bomb's blast while a Majini is at it, or simply in the blast.

        Out through the widest gap. The first case is the old guard (Majini closing, the bomb triggers on contact).
        The second is the live 2026-10-30 RE5 cluster: bomb_cm 26-416, no Majini at the bomb within TRIGGER_CM, yet his
        own proximity mine detonated and reached him - the mine detonates on its own timer, so the old guard
        (Majini-within-TRIGGER_CM) never fired and he stood in it. The bomb he just placed is skipped: the retreat
        state machine (place -> settle -> retreat) already walks him away from that one at RETREAT_CM; the danger is
        the *other* bombs still down when he drifts back into their radius on a later cycle.

        Also used mid-cycle (place/settle/retreat): the cluster's remaining incidents (2026-10-31, rate 1.131 vs
        baseline 0.833) show held=['zl'] - the bot was mid-place (bomb in hand) when the blast hit him. The idle-only
        _clear never fires during a cycle, so he stands in an old bomb's blast while placing a new one. This guard
        aborts the cycle and runs him out before the detonation.

        Uses ground_mines from the snapshot (all mines on the ground) rather than self.bombs: self.bombs only tracks
        confirmed placements from the current round, but the residual incidents (2026-11-02, rate 0.655 vs target
        0.524) show bombs 153-363 cm from the bot that were never confirmed (unconfirmed placements or from a prior
        round) and so are not in self.bombs. The guard must see every mine in the blast, not just the confirmed ones.
        """
        pos = p["pos"]
        in_blast, reason = False, None
        ptr, b = None, None
        ground = snap.get("ground_mines") or ()
        seen = set()
        for g in ground:
            b = tuple(g["pos"])
            if self.last_pos is not None and b == self.last_pos:
                continue                                     # the one he just placed: the retreat handles it
            if self.site is not None and flat(self.site, b) < CONFIRM_CM:
                continue                                     # the bomb he just placed (site not yet confirmed)
            if g["ptr"] in self.ground0 and g["ptr"] not in self.bombs:
                continue                                     # a mine from before this round, not his
            if self.baseline and g["ptr"] in self.baseline and g["ptr"] not in self.bombs:
                continue                                     # up before he planted anything: the stack's own unit
            threatened = any(flat(e["pos"], b) <= DANGER_CM for e in live)
            left = self.combo_left(snap)
            standoff = COMBO_STANDOFF_CM if left is not None and left <= COMBO_CUT_S else BLAST_CM
            calm = self.__dict__.setdefault("_calm_since", {})
            if flat(pos, b) >= (standoff if threatened else CALM_CM):
                calm.pop(g["ptr"], None)
                continue
            if not threatened and now is not None and now - calm.setdefault(g["ptr"], now) < CALM_DWELL_S:
                continue                                     # a quiet bomb: he may walk past it
            if g["ptr"] in seen:
                continue
            seen.add(g["ptr"])
            ptr = g["ptr"]
            if any(flat(e["pos"], b) <= TRIGGER_CM for e in live):
                reason = "a Majini at his bomb: out of its blast"
            elif threatened:
                reason = "a Majini nearing his bomb: out to the standoff"
            else:
                reason = "in his own bomb's blast: out before it detonates"
            in_blast = True
            break
        reeling = now is not None and now < self.flash_until
        for e in live:
            if flat(pos, e["pos"]) < CLOSE_MAJINI_CM and in_blast and not reeling:
                # The cluster's remaining incidents: he stood in the old bomb's blast (bomb_cm 8-95) while a Majini
                # was right on him. He cannot outrun the blast through a close crowd - the crowd fire unloads on him
                # and the blast finishes it (live: 5 within 2 m, 11 within 4 m, and the death). The bomb's timer is
                # already running, so the run is given up and the gun comes up: the fight unloads on the threat.
                # Unless a flash of his has them reeling (flash_until: the bot's CRIT_FLASH answers this very moment,
                # close_in_blast_at, with one): then nobody grabs him on the way, and he runs out as the operator
                # asked ("flashbanging and running away and getting distance"). The ledger, 2026-11-09: this was the
                # bomb guard's last word in 73 of the 270 deaths since 11-03, and 6 of the night's 13 deaths lost
                # health inside his own bombs' blast windows (mine_blast_hp_loss: 2,587 in all, up to 1,545 in one).
                self.close_in_blast_at = now
                self.stats["mine_status"] = "in the blast and a close Majini first: the gun up"
                # A neutral action still owns this tick and would suppress the
                # gun/combat on every subsequent tick. Yield actual control;
                # due() and relocation retain the stricter placement clearance.
                return None
        if in_blast:
            if now is not None:
                if now < self._clear_yield:
                    self.stats["mine_status"] = "no way out of the bomb's reach from here: the fight has the pad"
                    return None
                run, off = self._clear_run, flat(pos, b)
                if run is None or run["ptr"] != ptr:
                    run = self._clear_run = {"ptr": ptr, "best": off, "best_at": now}
                elif off > run["best"] + CLEAR_GAIN_CM:
                    run["best"], run["best_at"] = off, now
                elif now - run["best_at"] > CLEAR_STUCK_S:
                    self._clear_run, self._clear_yield = None, now + CLEAR_YIELD_S
                    self.stats["mine_clear_stuck"] = self.stats.get("mine_clear_stuck", 0) + 1
                    self.stats["mine_status"] = "no way out of the bomb's reach from here: the fight has the pad"
                    return None
            if self.clear_from != ptr:
                self.clear_from = ptr
                self.stats["mine_clear_runs"] += 1
            self.stats["mine_status"] = reason
            return self._run(p, live, b)
        self.clear_from, self._clear_run = None, None
        return None

    def _clear_mid_cycle(self, p: dict, snap: dict, live: list, now: float) -> dict | None:
        """Mid-cycle guard (place/settle/retreat): if the bot is in an OLD bomb's blast, abort the cycle and run out.

        The cluster's remaining incidents (2026-10-31): held=['zl'] means the bot was mid-place (bomb in hand) when
        the blast hit him. The idle-only _clear never fires during a cycle, so he stands in an old bomb's blast while
        placing a new one. This check aborts the place/settle/retreat and runs him out before the detonation.
        The bomb he just placed (last_pos) is skipped - the retreat state machine already handles that one.

        Checks the snapshot's ground_mines (all mines on the ground) rather than self.bombs: self.bombs only tracks
        confirmed placements from the current round, but the incident replay shows mines 8-285 cm from the bot that
        were never confirmed (unconfirmed placements or from a prior round) and so are not in self.bombs. The guard
        must see every mine in the blast, not just the ones the bot confirmed.
        """
        pos = p["pos"]
        ground = snap.get("ground_mines") or ()
        seen = set()
        for g in ground:
            b = tuple(g["pos"])
            if self.last_pos is not None and b == self.last_pos:
                continue
            # Also skip mines near the site (the bot's position when it started placing): the bomb he just
            # placed lands ~57 cm ahead of his feet, and last_pos is not set until confirmation.
            if self.site is not None and flat(self.site, b) < CONFIRM_CM:
                continue
            if flat(pos, b) >= (BLAST_CM if any(flat(e["pos"], b) <= DANGER_CM for e in live) else CALM_CM):
                continue
            # Skip mines that were already on the ground before this placement cycle AND are not the bot's
            # confirmed bombs: the stack's own uWp0a units (always in ground_mines, never in self.bombs) would
            # otherwise trigger the guard every tick. Confirmed bombs ARE in self.bombs, so they are checked.
            if g["ptr"] in self.ground0 and g["ptr"] not in self.bombs:
                continue
            if self.baseline and g["ptr"] in self.baseline and g["ptr"] not in self.bombs:
                continue                                     # (the stack's own unit: see _track)
            if g["ptr"] in seen:
                continue
            seen.add(g["ptr"])
            # He is in an old bomb's blast mid-cycle: abort and run out.
            if self.clear_from != g["ptr"]:
                self.clear_from = g["ptr"]
                self.stats["mine_clear_runs"] += 1
            self.state, self.t, self.site = "retreat", now, b
            self.stats["mine_status"] = "in an old bomb's blast mid-cycle: aborting and running out"
            return self._run(p, live, b)
        return None

    def tick(self, p: dict, snap: dict, live: list, now: float, *, busy: bool = False) -> dict | None:
        inv = snap.get("inventory") or ()
        mine = self.stack(inv)
        hand = self.equipped(inv)
        if self._tick_at is not None and now - self._tick_at > GAP_S:
            # The bot was held, healing or otherwise away from this module: the cycle's clock pauses with it, so
            # EQUIP_S/PLACE_S/SETTLE_S never expire over time the controller did not actually spend on the cycle.
            self.t += now - self._tick_at
        self._tick_at = now
        self._track(p, snap, now)
        if getattr(self, 'native', None) is not None:
            return self._native_tick(p, snap, live, now, busy=busy)
        if self.state == "idle":
            act = self._clear(p, snap, live, now)
            if act is not None or busy:
                if busy:
                    self.stats["mine_blocked_reason"] = "emergency action"
                    self.stats["mine_relocating"] = False
                return act
            if self.due(p, snap, live, now) is None:
                if RELOCATE_RUN and self._blocked in ("last bomb too close", "enemy too close"):
                    return self._relocate(p, live, now)
                self.stats["mine_relocating"] = False
                return None
            self._relocate_until = None
            self.stats["mine_relocating"] = False
            gun = next((s for s in inv if s.get("hand") and s.get("type") == 1 and s.get("item") not in THROWN), None)
            self.gun_grid = gun.get("grid") if gun else self.gun_grid
            self.state, self.t = "neutral", now
            self.stats["mine_status"] = "placing a bomb: the pad rests"
            return {"hold": ()}
        if busy and self.state in ("neutral", "equip"):
            self.state, self.t = "rearm", now            # held / ringed before the press: give it up, the gun back
            self._retry_at = now + RETRY_S
            return None
        if self.state == "neutral":
            if now - self.t < NEUTRAL_S:
                return {"hold": ()}
            if mine is None and hand is None:
                self.state = "idle"
                return None
            self.state, self.t = "equip", now
            self._equip_tap_at = now
            self.stats["mine_attempts"] += 1
            if mine is not None and hand is None:
                return {"tap": QUICK[mine["grid"]]}
            return {"hold": ()}                         # already in hand (a prior press landed)
        if self.state == "equip":
            if (hand is None and mine is not None and now - self.__dict__.get("_equip_tap_at", self.t) >= EQUIP_RETAP_S
                    and now - self.t <= EQUIP_S):
                self._equip_tap_at = now                   # again: the native request's fallback needs a press
                self.stats["mine_equip_retaps"] = self.stats.get("mine_equip_retaps", 0) + 1
                return {"tap": QUICK[mine["grid"]]}
            if hand is not None:
                why = self._clearance(p, live, now, committed=True)
                if why or "ground_mines" not in snap:
                    self.stats["mine_blocked_reason"] = why or "ground mine observation unavailable"
                    self.state, self.t = "rearm", now
                    self._retry_at = now + RETRY_S       # fight before another equip/abort cycle
                    return {"hold": ()}                 # no plant while a threat closed during equip
                self.state, self.t, self.saw_place = "place", now, False
                self.saw_spent = False
                self.count0 = hand.get("rounds")
                self.ground0 = {g["ptr"] for g in snap.get("ground_mines") or ()}
                self._ground_observed = True
                self.site = tuple(p["pos"])
                return {"hold": ("zl",)}
            if now - self.t > EQUIP_S:
                self.stats["mine_equip_failures"] += 1
                self.stats["mine_status"] = "the bomb did not come to hand"
                self.state, self.t = "rearm", now
                self._retry_at = now + RETRY_S             # a failed equip did not satisfy the mine cadence
                return None
            return {"hold": ()}
        if self.state == "place":
            mid = self._clear_mid_cycle(p, snap, live, now)
            if mid is not None:
                return mid
            self.saw_place = self.saw_place or p.get("motion") == MOTION_PLACE
            observed_mine = next((s for s in inv if s.get("id") == MINE_ID), None)
            spent = (observed_mine is not None and self.count0 is not None
                     and (observed_mine.get("rounds") or 0) < self.count0)
            self.saw_spent = self.saw_spent or spent
            new = [g for g in snap.get("ground_mines") or ()
                   if self._ground_observed and g.get("ptr") and g["ptr"] not in self.ground0
                   and self.site is not None and len(g.get("pos") or ()) == 3
                   and all(math.isfinite(v) for v in g["pos"])
                   and math.dist(self.site, g["pos"]) <= CONFIRM_CM]
            if new:
                self.stats["mines_placed"] += 1
                self.stats["mine_status"] = "bomb down: leaving it behind"
                self.site = tuple(new[0]["pos"])
                self.bombs[new[0]["ptr"]] = self.site
                self.stats["mine_last_confirmation"] = {"source": "native_uWp0a_actor", "ptr": new[0]["ptr"],
                    "pos": list(self.site), "at": now}
                self.stats["mine_last_actor"] = new[0]["ptr"]
                self.stats["mine_last_placed_at"] = now
                self.stats["mine_overdue_s"] = 0.0
                self.last_at, self.last_pos = now, self.site
                self._site_until = None                     # the bomb itself is tracked (self.bombs) while it is down
                self.state, self.t = "settle", now
                return {"hold": ()}
            if now - self.t > PLACE_S:
                self.stats["mine_unconfirmed"] += 1
                if self.saw_place or self.saw_spent:       # it may be down all the same: out of its way
                    self.last_at = now
                    self.stats["mine_status"] = "placement unconfirmed: leaving all the same"
                    self.last_pos = self.site
                    self._site_until = now + UNCONFIRMED_SITE_S
                    self.state, self.t = "retreat", now
                    return self._run(p, live, self.site)
                self.stats["mine_status"] = "placement unconfirmed"
                self._retry_at = now + RETRY_S
                self.state, self.t = "rearm", now
                return {"hold": ()}
            return {"hold": ("zl",)} if now - self.t < PRESS_S else {"hold": ()}
        if self.state == "settle":                        # the placing motion: he cannot move until it ends
            mid = self._clear_mid_cycle(p, snap, live, now)
            if mid is not None:
                return mid
            if p.get("motion") == MOTION_PLACE and now - self.t < SETTLE_S:
                return {"hold": ()}
            if self._trail(live):
                self.stats["mine_trail_plants"] = self.stats.get("mine_trail_plants", 0) + 1
                self.stats["mine_status"] = "bomb down on his way: nobody near it, on he goes"
                self.state, self.t = "rearm", now
                return {"hold": ()}
            self.state, self.t = "retreat", now
            return self._run(p, live, self.site)
        if self.state == "retreat":
            away = self.site is not None and flat(p["pos"], self.site) >= RETREAT_CM
            left = self.combo_left(snap)
            if (not away and left is not None and left <= COMBO_CUT_S and self.site is not None
                    and flat(p["pos"], self.site) >= COMBO_STANDOFF_CM):
                away = True                               # out of its blast and the combo's window nearly gone
                self.stats["mine_combo_cuts"] = self.stats.get("mine_combo_cuts", 0) + 1
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
            if now - self.__dict__.get('_rearm_tap_at', -1e9) >= EQUIP_RETAP_S:
                self._rearm_tap_at = now
                return {"tap": QUICK[gun["grid"]]}
            return {"hold": ()}                         # retry without extending the rearm deadline
        return None

    def observe_native(self, memory, snap, now):
        """Poll before any priority return; completion never runs on a worker's stats thread."""
        from . import re5_native_mine_tactic as native
        from ..re5_reactive_ring import observe_event
        if snap.get('mine_settings'):
            self.configure(snap['mine_settings'])
        observe_event(snap, self.stats, now)
        if memory is not None and callable(getattr(memory, 'rd', None)) and snap.get('module_base'):
            from .re5_traversal import observe as observe_traversal
            observe_traversal(memory, snap, self.stats, now)
        self.cadence.observe(snap, self.stats, now, self.automine)
        if getattr(self, 'native', None) is None and self.state == 'idle' and native.enabled(memory):
            self.native = native.Flight(memory)
        if getattr(self, 'native', None) is None:
            return
        self.native.clearance_cm = self.foe_clear_cm
        packet = self.native.poll(snap, self.stats)
        for row in self.native.take_deployments():
            self._merge_native_hazard(row, now, snap.get('ground_mines'))
        forced_hazards = self.stats.get('native_mine_force_hazards')
        if isinstance(forced_hazards, list):
            for row in forced_hazards[:40]:
                self._merge_native_hazard(row, now, snap.get('ground_mines'))
            del forced_hazards[:40]
        if packet is not None:
            self._merge_native(packet, now, census=snap.get('ground_mines'))
        forced = self.stats.get('native_mine_force_receipts')
        if isinstance(forced, list):
            for row in forced[:8]:
                if (isinstance(row, dict) and tuple(row.get('owner') or ()) == self.native.owner
                        and isinstance(row.get('receipt'), dict)):
                    self._merge_native(dict(row, archive=row.get('archive')), now, manual=True,
                                       census=snap.get('ground_mines'))
            del forced[:8]
        self._request_native(snap, now)

    def _start_native_escape(self, request_id, center, now, *, predicted=()):
        """One stable centre per request; nearby hazard identities do not flip the route."""
        old = self._native_escape
        if old is None or old['id'] != request_id:
            self._native_escape = {'id': request_id, 'center': tuple(center),
                'sites': dict(self.bombs) | (dict(old['sites']) if old else {}), 'predicted': tuple(predicted),
                'pending': True, 'started': now, 'report_at': now, 'replan': 0}
        self.site = self._native_escape['center']
        self.state, self.t = 'retreat', now
        self.stats['native_mine_escape_required'] = True

    def _merge_native_hazard(self, packet, now, census):
        from . import re5_native_mine_tactic as native
        if (not isinstance(packet, dict) or not packet.get('id') or self.native is None
                or tuple(packet.get('owner') or ()) != self.native.owner):
            return
        row = packet.get('mine')
        if (not isinstance(row, dict) or type(row.get('unit')) is not int
                or type(row.get('generation')) is not int or not native.position(row.get('pos'))
                or row.get('active') is not True):
            return
        key = (packet['id'], row['unit'], row['generation'])
        if key in self._native_hazards_seen:
            return
        self._native_hazards_seen.append(key)
        if self.native.guard is not None:
            self.native.guard['actors'][row['unit']] = row['generation']
        pos = tuple(row['pos'])
        self.bombs[row['unit']] = pos
        self._native_receipt_census[row['unit']] = census
        if self.baseline is not None:
            self.baseline.discard(row['unit'])
        center = packet.get('center')
        self._start_native_escape(packet['id'], center if native.position(center) else pos, now)
        self._native_escape['sites'][row['unit']] = pos
        self.stats['native_mine_deployed_hazards'] = self.stats.get('native_mine_deployed_hazards', 0) + 1
        self.stats['mine_status'] = 'native mine deployed; flee while it arms'

    def _merge_native(self, packet, now, *, manual=False, census=None):
        from . import re5_native_mine_tactic as native
        if not packet.get('id') or packet['id'] in self._native_receipts:
            return
        self._native_receipts.append(packet['id'])
        result = packet['receipt']
        self.stats['native_mine_last'] = {k: result.get(k) for k in
            ('state', 'verified', 'placed', 'armed', 'triggered', 'weapon_unchanged', 'elapsed_ms', 'reason')}
        self.stats['native_mine_last'].update(id=packet['id'], archive=packet['archive'])
        rows = [r for r in result.get('mines') or () if isinstance(r, dict) and type(r.get('unit')) is int
                and type(r.get('generation')) is int and native.position(r.get('pos'))]
        if self.native.guard is not None:
            for row in rows:
                self.native.guard['actors'][row['unit']] = row['generation']
        confirmed = [r for r in rows if r.get('armed_observed') is True or r.get('trigger_observed') is True]
        for row in rows:
            if not row.get('trigger_observed'):
                self.bombs[row['unit']] = tuple(row['pos'])  # uncertain active actors remain hazards
                self._native_receipt_census[row['unit']] = census
                if self.baseline is not None:
                    self.baseline.discard(row['unit'])
        if confirmed:
            self.stats['mines_placed'] += len(confirmed)
            self.stats['native_mines_placed'] = self.stats.get('native_mines_placed', 0) + len(confirmed)
            row = confirmed[-1]
            self.stats.update(mine_last_actor=row['unit'], mine_last_placed_at=now,
                mine_last_confirmation={'source': 'native_armed_uWp0a', 'ptr': row['unit'],
                                        'pos': list(row['pos']), 'at': now}, mine_overdue_s=0.)
        expected = result.get('requested', packet.get('requested', 1))
        complete = (result.get('state') == 'confirmed' and result.get('verified') is True
                    and result.get('weapon_unchanged') is True and type(expected) is int
                    and 1 <= expected <= 8 and len(confirmed) == expected)
        if result.get('state') == 'confirmed' and not complete:
            self.native.blocked_owner = packet['owner']
            self.stats['native_mine_last']['reason'] = 'native receipt did not confirm requested mines with unchanged weapon'
        if packet.get('reason') == 'traversal':
            self.stats['mine_landing_last'] = dict(self.stats['native_mine_last'],
                at=now, center=packet.get('center'), confirmed_armed=len(confirmed))
            self.stats['mine_landing_drops'] = self.stats.get('mine_landing_drops', 0) + len(confirmed)
        if not complete:
            self.stats['mine_unconfirmed'] += 1
            self._retry_at = now + RETRY_S
        active = [r for r in rows if not r.get('trigger_observed')]
        if active:
            for row in active:
                self._merge_native_hazard(dict(packet, center=packet.get('center') or result.get('center'),
                                               mine=dict(row, active=True)), now, census)
            self.last_at, self.last_pos = now, tuple(active[-1]['pos'])
            self._site_until = None
            if self._native_escape is not None:
                self.site = self._native_escape['center']
                self.state, self.t = 'retreat', now
                self.stats['mine_status'] = 'native mine down; keep moving clear of its blast'
        elif self._native_escape is None:
            self.state, self.site = 'idle', None
            if confirmed:
                self.last_at = now
        if self._native_escape is not None and self._native_escape['id'] == packet['id']:
            self._native_escape['pending'], self._native_escape['predicted'] = False, ()
            for row in rows:
                if row.get('trigger_observed'):
                    self._native_escape['sites'].pop(row['unit'], None)

    def _request_native(self, snap, now):
        """Background admission only: never lower a gun, equip, or hold an input."""
        from . import re5_native_mine_tactic as native
        flight, p = self.native, snap.get('player') or {}
        if not self.automine:
            flight.cancel()
            self.stats['mine_blocked_reason'] = 'automine disabled'
            return
        if flight.job is not None or now < self._retry_at:
            return
        demand = self.cadence.demand(snap, self.stats, now)
        if demand is None:
            return
        landing = demand[0] == 'traversal'
        event = self.stats.get('traversal_mine_event' if landing else 'automine_event') or {}
        reaction = demand[0] in ('hit', 'qte')
        count = 5 if reaction and (demand[0] == 'hit' or (event.get('damage') or 0) > 0) else 1
        center = tuple(event['pos']) if (reaction or landing) and native.position(event.get('pos')) else None
        if landing and center is None:
            self.stats['mine_blocked_reason'] = 'traversal landing position unavailable'
            return
        if count == 5 and center is None:
            self.stats['mine_blocked_reason'] = 'hit position unavailable; damage ring not relocated'
            return
        if self._native_escape is not None and not reaction:
            self.stats['mine_blocked_reason'] = 'finish native mine escape before another travel or landing drop'
            return
        if not native.enabled(flight.memory) or flight.owner == flight.blocked_owner:
            self.stats['mine_blocked_reason'] = 'native mine unavailable or previous placement uncertain'
            return
        if not native.position(p.get('pos')) or 'ground_mines' not in snap:
            self.stats['mine_blocked_reason'] = 'ground mine observation unavailable'
            return
        # A native drop does not root the runner in a planting animation. Nearby
        # pursuers are its purpose; only existing mine sites restrict placement.
        placement = dict(p, pos=center) if center is not None else p
        if why := self._clearance(placement, [], now, native=True):
            self.stats['mine_blocked_reason'] = why
            return
        if self.stats.get('ring_async_pending') or self.stats.get('bot_grenade_state') == 'requested':
            self.stats['mine_blocked_reason'] = 'another native defensive action is pending'
            return
        if flight.submit(snap, self.stats, now, reason=demand[0], count=count, center=center):
            self.cadence.claimed(demand, now)
            self.stats['mine_attempts'] += 1
            self.stats['automine_request_reason'] = demand[0]
            self.stats['automine_request_count'] = count
            if landing:
                self.stats['mine_landing_requests'] = self.stats.get('mine_landing_requests', 0) + 1
                self.stats['mine_landing_evidence'] = dict(event)
            self.stats['mine_status'] = 'native mine requested; movement and combat continue'
            if count == 5:
                from .re5_proximity_native import points
                self._start_native_escape(flight.job['id'], center, now, predicted=points(center, count))

    def automatic(self, p, snap, live, now):
        """Automatic play never falls back to the legacy equip/place sequence."""
        self._track(p, snap, now)
        if self.native is None:
            self.stats['mine_blocked_reason'] = 'native mine unavailable; no equipment fallback'
            return self._clear(p, snap, live, now)  # an existing physical hazard still matters
        return self._native_tick(p, snap, live, now)

    def native_sites(self, snap):
        """All physical mines constrain departure, including earlier completed drops.

        Receipt hazards survive a stale/unavailable census. Predicted ring points
        exist only until the allocation receipt arrives; they never count as mines.
        """
        from .re5_native_mine_tactic import position
        escape = self._native_escape or {}
        sites = dict(escape.get('sites', {})) | self.bombs
        for row in snap.get('ground_mines') or ():
            if (isinstance(row, dict) and position(row.get('pos'))
                    and row.get('active') is not False and row.get('trigger_observed') is not True):
                sites[row.get('ptr', row.get('unit', ('observed', tuple(row['pos']))))] = tuple(row['pos'])
        sites.update({('predicted', i): tuple(pos) for i, pos in enumerate(escape.get('predicted', ()))})
        return {key: tuple(pos) for key, pos in sites.items() if position(pos)}

    def _native_tick(self, p, snap, live, now, *, busy=False):
        """A request never neutralizes the pad or enters an equip/placing animation."""
        from . import re5_native_mine_tactic as native
        flight = self.native
        escape = self._native_escape
        if escape is not None:
            sites = list(self.native_sites(snap).values())
            clearance = min((flat(p['pos'], site) for site in sites), default=math.inf)
            away = clearance >= RETREAT_CM and (bool(sites) or not escape['pending'])
            self.stats['native_mine_escape_clearance_cm'] = round(clearance, 1) if math.isfinite(clearance) else None
            self.stats['native_mine_escape_hazards'] = len(sites)
            if away:
                if sites:
                    self.stats['mine_retreats_completed'] += 1
                self._native_escape = None
                self.state, self.site, self.last_pos = 'idle', None, None
                self.stats['native_mine_escape_required'] = False
            elif not busy:
                self.site = escape['center']
                self.native_retreat_distance = RETREAT_CM + max(
                    (flat(self.site, site) for site in sites), default=0.)
                if now - escape['report_at'] >= RETREAT_S:
                    escape['report_at'], escape['replan'] = now, escape['replan'] + 1
                    self.stats['native_mine_escape_replans'] = self.stats.get('native_mine_escape_replans', 0) + 1
                    self.stats['native_mine_escape_blocked'] = {'id': escape['id'], 'at': now,
                        'elapsed_s': round(now - escape['started'], 2), 'pos': list(p['pos']),
                        'center': list(self.site), 'clearance_cm': self.stats['native_mine_escape_clearance_cm'],
                        'required_cm': RETREAT_CM, 'actors': len(escape['sites'])}
                self.stats['mine_status'] = 'native mine escape: reach measured clearance from every deployed mine'
                return self._run(p, live, self.site)
        if flight.job is not None:
            self.stats['mine_status'] = 'native mine pending; movement and combat continue'
            return None                                  # pending allocation alone never owns the pad
        if self.state == 'retreat' and self.site is not None:
            away = flat(p['pos'], self.site) >= RETREAT_CM
            if away or self._trail(live) or now - self.t > RETREAT_S:
                if away:
                    self.stats['mine_retreats_completed'] += 1
                elif self._trail(live):
                    self.stats['mine_trail_plants'] = self.stats.get('mine_trail_plants', 0) + 1
                self.state, self.site, self.last_pos = 'idle', None, None
            elif not busy:
                return self._run(p, live, self.site)
        if busy:
            return None
        act = self._clear(p, snap, live, now)
        if act is not None:
            return act
        return None

    def close(self):
        if getattr(self, 'native', None) is not None:
            self.native.close()

    def _trail(self, live: list) -> bool:
        """The bomb just planted has no Majini within TRAIL_CM of it: left behind on his way, no run out."""
        return self.site is not None and not any(flat(e["pos"], self.site) <= TRAIL_CM for e in live)

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
