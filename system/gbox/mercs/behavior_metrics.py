"""Per-round behaviour metrics for the Mercenaries bots, so the round map explains the wayward actions the operator sees
(2026-10-26, watching RE4: "instead of walking down a path, I'm watching him progress down a path in a sine wave";
"waving the gun around randomly and then sometimes shooting the target"; "always running into the entrances of
locations instead of going inside"; "walk past time bonuses"; "pick up ammo that they do not need"; "if he's going to
shoot these chickens, he's going to need to aim at these chickens"; "I just like them blasting like mad"). Per round:

  * path weave: while a planned path is run, the lateral deviation from the planned leg (mm) and the steering stick's
    sign reversals a second (a sine wave is many reversals and a wide deviation);
  * aim jitter: while the gun is up, the reticle-to-target error, the aim's angular speed, its reversals, the target
    switches with the gun up, the time from raising the gun to its first shot, the shots outside the on-target window;
  * doorways: per portal (a narrow passage on the stage map) the passes through it and the bumps (stucks) at it;
  * pickups taken, by kind - ammo flagged unneeded (infinite ammo is on);
  * time bonuses passed within reach and left there;
  * chicken shots with and without the aim on the chicken;
  * the fire rate: shots a second with the trigger held on target, per weapon class (the visible "blasting");
  * what each shot's aim line met (a foe, a wall, the floor, nothing) and how the shots ended (hit / miss:<cause>, the
    gbox.mercs.bot_look outcomes), and the time spent standing among foes without moving or shooting (operator
    2026-10-26: "They are shooting at walls and just sitting here amongst foes").

    m = BehaviorMetrics()          # the bot feeds it each tick; reset() at a round's start
    m.summary()                    # the round map's "behavior" block; gbox.mercs.round_audit checks it
Nothing here reads or writes the game.
"""
from __future__ import annotations

import math
from collections import Counter

# RE4 GameCube (re_games.ITEMS): the weapon classes a Mercenaries round hands out, and the item kinds a pickup can be
RE4_WEAPON_CLASS = {0x21: "handgun", 0x23: "handgun", 0x25: "handgun", 0x27: "handgun", 0x40: "handgun",
                    0x29: "magnum", 0x2A: "magnum", 0x2B: "magnum", 0x37: "handcannon",
                    0x2C: "shotgun", 0x2D: "shotgun", 0x94: "shotgun", 0x2E: "rifle", 0x2F: "rifle",
                    0x30: "machine gun", 0x31: "machine gun", 0x33: "machine gun", 0x3E: "machine gun",
                    0x34: "machine gun", 0x53: "machine gun", 0x17: "launcher", 0x6D: "launcher", 0x36: "launcher"}
RE4_AMMO = frozenset({0x00, 0x04, 0x07, 0x18, 0x1A, 0x20, 0x46, 0x6A, 0x72, 0xA0})
RE4_TIME_BONUS, RE4_COMBO_BONUS = 0x73, 0x75
PASS_R, LEAVE_R = 1500.0, 3000.0     # mm: a time bonus this near is within reach; this far again: passed by
PORTAL_R = 700.0                     # mm: inside a portal (a doorway's centre) this near
REVERSAL_MIN_S = 0.0                 # (a reversal is any sign change of the held turn key between two turning ticks)


def re4_weapon_class(iid) -> str:
    if not iid or iid == 0x800:
        return "none"
    return RE4_WEAPON_CLASS.get(iid, "other")


def re4_item_kind(iid) -> str:
    if iid == RE4_TIME_BONUS:
        return "time bonus"
    if iid == RE4_COMBO_BONUS:
        return "combo bonus"
    if iid in RE4_AMMO:
        return "ammo"
    try:
        from .. import re_games
        k = re_games.item_kind(iid)
    except Exception:                         # noqa: BLE001 - a tree without the item table
        k = None
    return k or "other"


def _q(values, q):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(q * len(s)))]


class BehaviorMetrics:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.run_s, self.dev, self.turns, self.reversals, self._sign = 0.0, [], 0, 0, None
        self.aim_s, self.err, self.rate, self.aim_reversals, self._aim_sign = 0.0, [], [], 0, None
        self.switches, self._target, self._raised, self.ttf, self._fired = 0, None, None, [], False
        self.shots_on = self.shots_off = 0
        self.portals: dict = {}
        self._in_portal = None
        self.pickups: Counter = Counter()
        self.pickup_rows: list = []
        self.bonus_passed: list = []
        self._bonus_near: dict = {}
        self.chicken_aimed = self.chicken_unaimed = 0
        self.fire: dict = {}
        self.lines: Counter = Counter()             # what each shot's aim line met (bot_look.DOT_ON)
        self.outcomes: Counter = Counter()          # "hit" / "miss:<cause>"
        self.idle_s = self.idle_max_s = self._idle_run = 0.0

    # --- path weave ---
    def run_tick(self, dt: float, lateral, turn: int) -> None:
        """A tick of running a planned path: the lateral deviation (mm, None unknown) and the turn key (+1 left, -1 right,
        0 none)."""
        self.run_s += max(0.0, dt)
        if lateral is not None and math.isfinite(lateral):
            self.dev.append(abs(lateral))
        if turn:
            self.turns += 1
            if self._sign is not None and turn != self._sign:
                self.reversals += 1
            self._sign = turn

    def run_break(self) -> None:
        self._sign = None

    # --- aim ---
    def raise_gun(self, now: float) -> None:
        if self._raised is None:
            self._raised, self._fired = now, False

    def lower_gun(self) -> None:
        self._raised, self._aim_sign, self._target = None, None, None

    def aim_tick(self, dt: float, err, rate, turn: int, target) -> None:
        """A tick with the gun up: the reticle-to-target error (radians), the aim's angular speed (rad/s, None unknown),
        the aim turn key (+1 / -1 / 0) and the target's id."""
        self.aim_s += max(0.0, dt)
        if err is not None and math.isfinite(err):
            self.err.append(abs(err))
        if rate is not None and math.isfinite(rate):
            self.rate.append(abs(rate))
        if turn:
            if self._aim_sign is not None and turn != self._aim_sign:
                self.aim_reversals += 1
            self._aim_sign = turn
        if target is not None:
            if self._target is not None and target != self._target:
                self.switches += 1
            self._target = target

    def shot(self, now: float, on_target: bool, small: bool = False) -> None:
        """A shot the game fired: inside the on-target window or not; at a small animal (a chicken) or not."""
        if on_target:
            self.shots_on += 1
        else:
            self.shots_off += 1
        if self._raised is not None and not self._fired:
            self.ttf.append(max(0.0, now - self._raised))
            self._fired = True
        if small:
            if on_target:
                self.chicken_aimed += 1
            else:
                self.chicken_unaimed += 1

    # --- doorways ---
    def portal_tick(self, portals, pos) -> None:
        """portals: [(id, (x, z))] of the stage; pos: (x, z). Entering one and leaving it again is a pass."""
        here = None
        for pid, (x, z) in portals or ():
            if math.hypot(pos[0] - x, pos[1] - z) < PORTAL_R:
                here = pid
                self.portals.setdefault(pid, {"pos": [round(x), round(z)], "passes": 0, "bumps": 0})
                break
        if self._in_portal is not None and here != self._in_portal:
            self.portals[self._in_portal]["passes"] += 1
        self._in_portal = here

    def portal_bump(self, portals, pos, reach: float = 1000.0) -> str | None:
        """A stuck at pos: counted against the portal it happened at (within reach), if any; its id."""
        best = None
        for pid, (x, z) in portals or ():
            d = math.hypot(pos[0] - x, pos[1] - z)
            if d < reach and (best is None or d < best[0]):
                best = (d, pid, x, z)
        if best is None:
            return None
        row = self.portals.setdefault(best[1], {"pos": [round(best[2]), round(best[3])], "passes": 0, "bumps": 0})
        row["bumps"] += 1
        return best[1]

    # --- pickups and time bonuses ---
    def pickup(self, kind: str, iid=None, pos=None) -> None:
        self.pickups[kind] += 1
        if len(self.pickup_rows) < 50:
            self.pickup_rows.append({"kind": kind, "id": f"{iid:#x}" if isinstance(iid, int) else iid,
                                     **({"at": [round(pos[0]), round(pos[1])]} if pos else {})})

    def bonus_tick(self, pos, bonuses) -> None:
        """bonuses: [(id, (x, z))] of the time bonuses still on the stage. One within PASS_R that he then leaves LEAVE_R
        behind, still standing, was passed by."""
        live = {bid for bid, _ in bonuses or ()}
        for bid in list(self._bonus_near):
            if bid not in live:
                self._bonus_near.pop(bid)                  # taken (or gone)
        for bid, (x, z) in bonuses or ():
            d = math.hypot(pos[0] - x, pos[1] - z)
            if d < PASS_R:
                self._bonus_near[bid] = min(self._bonus_near.get(bid, d), d)
            elif d > LEAVE_R and bid in self._bonus_near:
                closest = self._bonus_near.pop(bid)
                if len(self.bonus_passed) < 50:
                    self.bonus_passed.append({"id": bid, "at": [round(x), round(z)], "closest_mm": round(closest)})

    # --- the fire rate ---
    def fire_tick(self, weapon_class: str, dt: float, held_on_target: bool, shots: int, mode: str = "hold") -> None:
        """A tick with the trigger working on target (the time counts: "held_s") and the shots the game fired in it, per
        class and per trigger mode ("hold": A held, "tap": rapid presses)."""
        if not held_on_target:
            return
        row = self.fire.setdefault(weapon_class or "other", {"held_s": 0.0, "shots": 0, "modes": {}})
        row["held_s"] += max(0.0, dt)
        row["shots"] += max(0, int(shots))
        m = row.setdefault("modes", {}).setdefault(mode or "hold", [0.0, 0])
        m[0] += max(0.0, dt)
        m[1] += max(0, int(shots))

    # --- the shots' lines and outcomes, idling among foes ---
    def shot_line(self, dot_on: str) -> None:
        """What a shot's aim line met as it left the gun: target / wall / floor / none / off."""
        self.lines[dot_on or "none"] += 1

    def shot_result(self, outcome: str) -> None:
        """How a shot ended: 'hit:<kind>' counts as "hit", a miss by its cause ('miss:wall')."""
        self.outcomes["hit" if str(outcome).startswith("hit:") else str(outcome)] += 1

    def idle_tick(self, dt: float, idle: bool) -> None:
        """A tick standing among foes without moving or shooting (idle), or not."""
        if idle:
            self.idle_s += max(0.0, dt)
            self._idle_run += max(0.0, dt)
            self.idle_max_s = max(self.idle_max_s, self._idle_run)
        else:
            self._idle_run = 0.0

    # --- the round's block ---
    def summary(self) -> dict:
        deg = math.degrees
        fire = {cls: {"held_s": round(r["held_s"], 2), "shots": r["shots"],
                      "shots_per_s": round(r["shots"] / r["held_s"], 2) if r["held_s"] >= 0.5 else None,
                      "by_mode": {m: {"s": round(v[0], 2), "shots": v[1],
                                      "shots_per_s": round(v[1] / v[0], 2) if v[0] >= 0.5 else None}
                                  for m, v in (r.get("modes") or {}).items()}}
                for cls, r in self.fire.items()}
        portals = [{"id": pid, **row} for pid, row in self.portals.items()]
        return {
            "path": {"run_s": round(self.run_s, 1),
                     "lateral_mm_median": round(_q(self.dev, 0.5)) if self.dev else None,
                     "lateral_mm_p90": round(_q(self.dev, 0.9)) if self.dev else None,
                     "stick_turns": self.turns, "stick_reversals": self.reversals,
                     "stick_reversals_per_s": round(self.reversals / self.run_s, 2) if self.run_s >= 1 else None},
            "aim": {"aim_s": round(self.aim_s, 1),
                    "error_deg_median": round(deg(_q(self.err, 0.5)), 1) if self.err else None,
                    "error_deg_p90": round(deg(_q(self.err, 0.9)), 1) if self.err else None,
                    "speed_deg_s_median": round(deg(_q(self.rate, 0.5)), 1) if self.rate else None,
                    "reversals": self.aim_reversals,
                    "reversals_per_s": round(self.aim_reversals / self.aim_s, 2) if self.aim_s >= 1 else None,
                    "target_switches": self.switches,
                    "switches_per_min": round(self.switches / (self.aim_s / 60), 1) if self.aim_s >= 5 else None,
                    "time_to_first_shot_s_median": round(_q(self.ttf, 0.5), 2) if self.ttf else None,
                    "shots_on_target": self.shots_on, "shots_off_target": self.shots_off},
            "portals": portals, "portal_passes": sum(r["passes"] for r in portals),
            "portal_bumps": sum(r["bumps"] for r in portals),
            "pickups": dict(self.pickups), "ammo_pickups": self.pickups.get("ammo", 0), "pickup_rows": self.pickup_rows,
            "bonuses_passed": len(self.bonus_passed), "bonuses_passed_at": self.bonus_passed,
            "chicken_shots": {"aimed": self.chicken_aimed, "unaimed": self.chicken_unaimed},
            "fire_rate": fire,
            "shot_lines": dict(self.lines), "walls_shot": self.lines.get("wall", 0),
            "shot_outcomes": dict(self.outcomes),
            "idle_among_foes": {"total_s": round(self.idle_s, 1), "max_s": round(self.idle_max_s, 1)},
        }
