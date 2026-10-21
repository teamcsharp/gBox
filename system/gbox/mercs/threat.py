"""The threat engine (docs/mercenaries_engine.md, section 3): every tick, who can hurt the player and how soon, from
the enemies' signatures - never from the picture.

    from gbox.mercs.threat import ThreatEngine
    te = ThreatEngine(lookahead=driver.lookahead)        # lookahead(enemy) -> exact seconds to the hit, or None
    threats = te.update(world, now)                      # most urgent first

An enemy whose state / act signature is an attack (`attack`: melee / grab / charge / throw / projectile / explosive)
is ranked by its time to land: 0 while its `active` bit is on, else the title's look-ahead (RE4: the motion's own
per-frame event words), else the signature's `lead_s` minus the time it has been in that value, plus the time to
close to its `reach`; one holding the player (`hold`) is 0; projectiles by their time to the closest approach
(velocity from consecutive reads; slow ones are lying on the ground); the rest by distance. `dying` / `gone` enemies
are never threats, `down` ones come after the standing ones. stats: attacks seen / prevented (died in it) / avoided
(over with no hit on the player) / landed, projectiles seen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .vocab import MELEE_KINDS

APPROACH, CLOSE_SPEED = 2000.0, 2500.0      # a melee attack this far beyond its reach still counts, closing this fast
PROJ_HIT_R, PROJ_MIN_SPEED = 900.0, 800.0   # a projectile passing this close is coming; slower than this: not flying


@dataclass
class Threat:
    slot: int
    kind: str                       # the attack kind, "hold", "thrown" (a projectile), "near" or "down"
    eta: float                      # seconds until it can land (math.inf: not coming)
    pos: tuple                      # where to shoot (led for its velocity), world units
    dist: float                     # ground distance from the player now
    state: tuple = ()
    since: float = 0.0              # when the enemy started this value
    vel: tuple = (0.0, 0.0, 0.0)
    why: str = ""
    enemy: object = field(default=None, repr=False)


def _attr(e, name, default=None):
    return e.get(name, default) if isinstance(e, dict) else getattr(e, name, default)


class ThreatEngine:
    """Memory across ticks: when each enemy started its current value, its velocity, the projectiles' flights."""

    def __init__(self, lookahead=None, lead_s: float = 0.15):
        self.lookahead, self.lead_s = lookahead, lead_s
        self.acts: dict = {}                       # enemy id -> (key, since, sig)
        self.track: dict = {}                      # id -> (t, pos, vel); projectiles under negative ids
        self.flights: dict = {}
        self.player_hit, self.player_hit_at = False, -math.inf
        self.stats = {"attacks_seen": 0, "thrown_seen": 0, "prevented": 0, "avoided": 0, "landed": 0}

    def _vel(self, key, pos, now) -> tuple:
        prev = self.track.get(key)
        vel = None
        if prev is not None and 0.02 < now - prev[0] < 0.6:
            dt = now - prev[0]
            raw = tuple((pos[i] - prev[1][i]) / dt for i in range(3))
            if math.hypot(raw[0], raw[2]) < 20000:
                vel = raw if prev[2] is None else tuple(0.6 * raw[i] + 0.4 * prev[2][i] for i in range(3))
        elif prev is not None and now - prev[0] <= 0.02:
            vel = prev[2]
        self.track[key] = (now, pos, vel)
        return vel or (0.0, 0.0, 0.0)

    def _ended(self, act, now, killed):
        landed = self.player_hit_at >= act[1] - 0.05
        key = "prevented" if killed and not landed else ("landed" if landed else "avoided")
        self.stats[key] += 1

    def update(self, player, enemies, projectiles, now: float) -> list[Threat]:
        """player: pos + tags ("hit" / "held" when the player is being hit); enemies / projectiles: objects or dicts
        with id (or slot), pos, and for enemies tags, sig (the attack signature), events, the routine key."""
        if player is None:
            return []
        px, py, pz = _attr(player, "pos")
        hit = bool(set(_attr(player, "tags", ()) or ()) & {"hit", "held"})
        if hit and not self.player_hit:
            self.player_hit_at = now
        self.player_hit = hit
        out, live = [], set()
        for e in enemies:
            k = _attr(e, "id", _attr(e, "slot"))
            live.add(k)
            pos = tuple(_attr(e, "pos"))
            vel = self._vel(k, pos, now)
            tags = set(_attr(e, "tags", ()) or ())
            hp = _attr(e, "hp")
            sig = _attr(e, "sig")
            key = (_attr(e, "state"), _attr(e, "act"))
            if (hp is not None and hp <= 0) or tags & {"dying", "gone"}:
                was = self.acts.pop(k, None)
                if was is not None and was[2]:
                    self._ended(was, now, killed=True)
                continue
            prev = self.acts.get(k)
            if prev is None or prev[0] != key:
                if prev is not None and prev[2]:
                    self._ended(prev, now, killed=False)
                prev = (key, now, sig)
                self.acts[k] = prev
                if sig:
                    self.stats["attacks_seen"] += 1
            since = prev[1]
            d = math.hypot(pos[0] - px, pos[2] - pz)
            lead = (pos[0] + vel[0] * self.lead_s, pos[1], pos[2] + vel[2] * self.lead_s)
            if "hold" in tags:
                out.append(Threat(k, "hold", 0.0, lead, d, key, since, vel, "holding the player", e))
                continue
            if sig:
                kind = sig.get("attack", "melee")
                reach = float(sig.get("reach") or 1200.0)
                active = sig.get("active") or {}
                mask = int(str(active.get("mask", 0)), 0) if isinstance(active.get("mask"), str) else int(active.get("mask") or 0)
                if mask and int(_attr(e, "events", 0) or 0) & mask:
                    eta = 0.0                                # the hit frames are on now
                else:
                    ahead = self.lookahead(e) if self.lookahead else None
                    eta = ahead if ahead is not None else max(0.0, float(sig.get("lead_s") or 0.7) - (now - since))
                    if kind in MELEE_KINDS and d > reach:
                        eta = max(eta, (d - reach) / CLOSE_SPEED)
                if d <= reach + APPROACH or kind not in MELEE_KINDS:
                    out.append(Threat(k, kind, eta, lead, d, key, since, vel, f"{key}", e))
                    continue
            out.append(Threat(k, "down" if "down" in tags else "near", math.inf, lead, d, key, since, vel, "", e))
        for k in list(self.acts):
            if k not in live:
                self.acts.pop(k, None)
        for k in list(self.track):
            if isinstance(k, int) and k >= 0 and k not in live:
                self.track.pop(k, None)
        out += self._projectiles(projectiles, (px, py, pz), now)
        return sorted(out, key=lambda t: (t.eta, t.dist))

    def _projectiles(self, items, leon, now) -> list[Threat]:
        out, seen = [], set()
        px, py, pz = leon
        for it in items:
            k = _attr(it, "id", _attr(it, "slot"))
            seen.add(k)
            if k not in self.flights:
                self.flights[k] = {"t0": now, "p0": tuple(_attr(it, "pos"))}
                self.stats["thrown_seen"] += 1
            f = self.flights[k]
            vel = self._vel(-1 - k, tuple(_attr(it, "pos")), now)
            x, y, z = _attr(it, "pos")
            vx, vz = vel[0], vel[2]
            sp2 = vx * vx + vz * vz
            if sp2 < PROJ_MIN_SPEED ** 2:
                continue
            tca = max(0.0, -((x - px) * vx + (z - pz) * vz) / sp2)
            miss = math.hypot(x + vx * tca - px, z + vz * tca - pz)
            d = math.hypot(x - px, z - pz)
            if miss > PROJ_HIT_R and d > PROJ_HIT_R:
                continue
            lead = (x + vx * self.lead_s, y + vel[1] * self.lead_s, z + vz * self.lead_s)
            out.append(Threat(k, "thrown", tca, lead, d, (), f["t0"], vel, f"miss {miss:.0f} in {tca:.2f}s", it))
        for k in list(self.flights):
            if k not in seen:
                self.flights.pop(k, None)
                self.track.pop(-1 - k, None)
        return out
