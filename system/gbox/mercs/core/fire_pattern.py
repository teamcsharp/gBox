"""The fire pattern: the PS3 magnum's "nice scatter and very rapid repeat" on every title, Switch, PS3 and GameCube
alike (docs/research/universal-mercs-architecture.md, section 10).

The operator, 2026-11-10: "if the agent is universal, I want it able to work with even the ps3, and gamecube versions.
The ps3 mercenary work was some of my favorite because the bot fired the magnum with a nice scatter and a very rapid
repeat and i want that across all these titles."

What the RE5 PS3 bot did (gbox/mercs/titles/re5_combat.py, the fight re5_ps3.Bot hands over; MEASURED from its round
maps on the Spark, gbox-data/mercs/round_maps/BLUS30491, 382 rounds 2026-10-26 .. 11-06, 820 magnum shot records):
  * the trigger HELD, never tapped, for every hitscan gun: re5_combat._decide `if direct: trig.mode = "hold"` and
    `keys |= {"r1"} if fire` once the rapid-fire package is verified (PS3IO.rapid_fire: the fire action's FPS
    constant 0x0169E098 >= 120 and the weapon's interval offset +0x90 == 0). The game repeats the held R1 itself:
    re5_mods_tool.fire_rate x80 (the timer 60 -> 4800 fps, the firing-speed table / 80, the offset 0) and, for the
    magnums (M29 0x0B, Lightning Hawk 0x1A, M500 0x1B), re5_fire_animation's three firing motion layers (0x51D, 0x51E,
    0x51C) at x8 playback - the recovery animation cut, the "very rapid repeat". (The old own-aim path, re5_ps3
    TAP_ON / TAP_OFF = 1, 2, a press a tick down then two up - 6.7 presses a second at 20 Hz - is not what ran: the
    combat layer is ENABLED.)
  * the cadence, measured from the shots' timestamps (consecutive shots under 0.4 s apart = one burst): the magnums'
    gap median 0.22 / 0.24 / 0.22 s (4.2 - 4.5 shots a second through a burst), p10 0.08 - 0.10 s (10 - 12 a
    second at its quickest), bursts of 2 (median) to 4 - 7 shots (p90 / max), the burst rate p90 11.1 - 12.5 a second;
  * the scatter: the stick kept slewing the aim onto him while R1 stayed down (re5_engage.window: his half width
    + 15 cm, DEADBAND_SHARE 0.35; "threat: blasting" inside 5 m held the trigger on the window, not the dot - 54 - 63 %
    of the magnum shots), so each repeat left from a different point of the sweep: the yaw error at the shot median
    2.0 - 4.2 deg, p90 11.6 - 18.4 deg; the pitch error median 1.5 - 2.3 deg; on one target the aim point moved
    median 1.7 - 9.5 cm, p90 34 - 59 cm a shot; only 4 - 7 % of consecutive shots in a burst went to another Majini
    (the dot drifting onto him: "on another Majini"); hits 34 - 53 % of the shots (Barry's handgun 75 %).
  So the scatter was never a random number: it was a held trigger the game repeated fast while the aim moved across
  the body (and now and then onto the next one).

What this module makes of it, title-agnostic (positions in cm, angles in radians, the title's profile converting):
  * FireSpec / SPECS: per weapon family the rapid repeat and the scatter (none for the automatics: they hold and the
    game repeats already). A family not listed gets no pattern.
  * Trigger: the rapid repeat in the title's own trigger style - "hold" (the game repeats a held trigger: RE5 PS3 /
    Switch), "edge" (a fresh press a shot: down a tick, up a tick - RE6, RE4 GC) or "tap" (down + up in one batch:
    RE4 Switch's engine) - never a press closer than the title's own floor (its fire gap, its native cooldown).
  * the scatter: shot k's aim point on his body, from a low-discrepancy sequence (R2: successive shots far apart, the
    whole body covered, never random): a lateral share of his body's radius and a height between the knee and the
    head, every point inside the body the title's hit test uses (combat.dot_on), so no shot is thrown away. It is
    EARNED: only while his shots have an effect (an enemy's health fell within earn_s) - before that, and whenever
    nothing reacts (an intro card, a death camera, a wall), every shot goes to the chest, so combat.NotInControl and
    the titles' no-effect rules see exactly what they saw before.
  * the crowd hop: after hop_every shots on one living target, the next goes to a neighbour already inside hop_cone of
    the gun's line and within hop_r_cm of him, on his level - no turn, only the aim shifted (the PS3's "on another
    Majini"); never away from a priority pick (the caller says so).
  * drivers per aim model, each title binding them to its own trigger, aim and stick:
      TankDriver    tank_heading (RE4 Switch, RE4 GC): no pitch, so the scatter is a yaw offset - the facing the aim
                    lock / the aim stick goes for is the bearing plus it; the fire gate stays the body's half-angle;
      LaserDriver   laser_ray (RE5 Switch, RE5 PS3): the scatter point the laser is steered onto while it is on him;
      CameraDriver  laser_camera_geometry (RE6 Switch, RE6 PS3): the offset added to the lock's / the camera's aim point.
Nothing here reads or writes the game or presses a key.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# --- what was measured on the RE5 PS3 bot (the module text) ---------------------------------------------------------------
PS3_MAGNUM = {
    "source": "gbox-data/mercs/round_maps/BLUS30491 (382 rounds 2026-10-26..11-06), shot records' t / target / errors",
    "trigger": "R1 held (re5_combat._decide: direct guns hold once PS3IO.rapid_fire verifies the package)",
    "mods": "re5_mods_tool.fire_rate x80 (timer 60 -> 4800 fps, firing-speed table / 80, interval offset 0); "
            "re5_fire_animation magnum layers x8 (MAX_MULTIPLIER)",
    "gap_s_median": (0.22, 0.24, 0.22), "gap_s_p10": (0.10, 0.09, 0.08),        # Lightning Hawk, M29, M500
    "shots_per_s_burst_median": (4.3, 4.2, 6.2), "shots_per_s_burst_p90": (11.1, 11.1, 12.5),
    "burst_len_median": 2, "burst_len_p90": (6, 4, 3),
    "yaw_err_deg_median": (2.81, 1.98, 4.18), "yaw_err_deg_p90": (17.04, 11.64, 18.40),
    "pitch_err_deg_median": (2.27, 1.54, 2.29),
    "aim_move_cm_median": (1.7, 9.5, 6.4), "aim_move_cm_p90": (43.0, 59.4, 34.5),
    "target_hop_share": (0.04, 0.06, 0.07), "hit_rate": (0.34, 0.51, 0.53),
}

# R2, the plastic number's low-discrepancy sequence: consecutive points far apart, the square filled evenly.
_G = 1.32471795724474602596
_A1, _A2 = 1.0 / _G, 1.0 / (_G * _G)


@dataclass(frozen=True)
class FireSpec:
    """One weapon family's pattern. Shares, not lengths: the scatter is the body's, at any distance and in any unit."""
    family: str
    scatter_w: float = 0.0          # the lateral reach: this share of his body's radius each side (0: no scatter)
    scatter_lo: float = 0.45        # the height band, shares from his knee (0) to his head's centre (1)
    scatter_hi: float = 0.95
    hop_every: int = 0              # after this many shots on one living target the next goes to a neighbour (0: never)
    hop_cone: float = math.radians(6.0)   # ... one already this near the gun's line (seen from him) ...
    hop_r_cm: float = 250.0               # ... and this near the target
    earn_s: float = 2.0             # the scatter only within this long of an effect (an enemy's health falling)
    min_cm: float = 150.0           # never scattered nearer than this (point blank: the chest)
    step_hz: float = 8.0            # a held trigger with no shot signal steps the scatter this often


SPECS = {
    # the PS3's magnum: the widest scatter (its yaw error median 2 - 4 deg at 3 - 4 m), a hop every third shot
    "magnum": FireSpec("magnum", scatter_w=0.6, scatter_lo=0.45, scatter_hi=0.95, hop_every=3),
    "handgun": FireSpec("handgun", scatter_w=0.45, scatter_lo=0.5, scatter_hi=0.9, hop_every=4),
    # the shotgun's pellets are its own spread: the hop only
    "shotgun": FireSpec("shotgun", scatter_w=0.0, hop_every=2, hop_cone=math.radians(10.0)),
    # the rifle is the long shot: a touch of scatter, never a hop
    "rifle": FireSpec("rifle", scatter_w=0.15, scatter_lo=0.6, scatter_hi=0.9, hop_every=0, min_cm=300.0),
}
FAMILIES = frozenset(SPECS)           # "the magnum (and other single-shot guns)"; automatics, launchers, bows: none


def spec(family) -> FireSpec | None:
    return SPECS.get(family)


def wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


def heading(dx: float, dz: float) -> float:
    return math.atan2(dx, dz)


# --- the scatter: where shot k goes on his body ---------------------------------------------------------------------------
def r2(k: int) -> tuple:
    """The k-th R2 point in the unit square (k = 0: the centre)."""
    return (0.5 + _A1 * k) % 1.0, (0.5 + _A2 * k) % 1.0


def offset(sp: FireSpec, body, k: int) -> tuple:
    """(lateral, height) of shot k on a body (both in the body's unit; height above his feet): k = 0 the chest, the
    rest R2 points - the lateral within scatter_w x his radius (never past 0.9 of it), the height between
    scatter_lo and scatter_hi of the knee-to-head span (never above shoulder + 15: every point inside dot_on's body)."""
    if k <= 0 or sp is None:
        return 0.0, float(body.chest)
    x, y = r2(k)
    w = min(max(sp.scatter_w, 0.0), 0.9)
    lat = (2.0 * x - 1.0) * w * float(body.r)
    lo, hi = sorted((min(max(sp.scatter_lo, 0.0), 1.0), min(max(sp.scatter_hi, 0.0), 1.0)))
    span = float(body.head) - float(body.knee)
    h = float(body.knee) + (lo + y * (hi - lo)) * span
    unit = float(body.r) / 36.0 if body.r else 1.0       # the body's own scale: 15 cm on a human-sized body
    h = max(float(body.knee) + 5.0 * unit, min(h, float(body.shoulder) + 15.0 * unit, float(body.head)))
    if w == 0.0:
        h = float(body.chest)                               # no scatter: the chest, every shot
    return lat, h


def across(shooter, foot) -> tuple:
    """The unit vector across the line of fire (shooter -> foot), toward the larger heading (heading = atan2(dx, dz):
    the titles' "rleft = larger heading" side); (0, 0) when they stand on one spot."""
    dx, dz = foot[0] - shooter[0], foot[2] - shooter[2]
    n = math.hypot(dx, dz)
    return (0.0, 0.0) if n < 1e-6 else (dz / n, -dx / n)


def yaw_offset(lat: float, dist: float) -> float:
    """A lateral offset (+ = toward the larger heading, as across()) at a distance as the heading change it takes."""
    return math.atan2(lat, max(dist, 1.0))


# --- the rapid repeat ----------------------------------------------------------------------------------------------------
STYLES = ("hold", "edge", "tap")


class Trigger:
    """The trigger at the title's fastest accepted cadence. tick(now, on, style, gap_s) -> True when the trigger is down
    this tick ("tap": a tap this tick). hold: down while on (the game repeats it); edge: down one tick, up the next,
    a press no sooner than gap_s after the last; tap: a tap no sooner than gap_s after the last. presses counts them."""

    def __init__(self):
        self.down = False
        self.at = -1e9
        self.presses = 0

    def tick(self, now: float, on: bool, style: str = "hold", gap_s: float = 0.0) -> bool:
        if not on:
            self.down = False
            return False
        if style == "hold":
            if not self.down:
                self.presses += 1
                self.at = now
            self.down = True
            return True
        if style == "edge" and self.down:
            self.down = False                               # the up tick: the next press is a fresh edge
            return False
        if now - self.at < gap_s - 1e-9:                    # (a tick's float sum a hair under the gap is the gap)
            return False
        self.at = now
        self.presses += 1
        self.down = style == "edge"
        return True


def cadence_hz(style: str, tick_s: float, gap_s: float = 0.0, cap_hz: float = 0.0) -> float:
    """The presses a second a trigger style reaches at a tick rate and a floor (and under the game's own cap, when
    known): what each title's bot can deliver, for the reports and the tests."""
    tick_s = max(tick_s, 1e-3)
    if style == "hold":
        return float(cap_hz) if cap_hz > 0 else 0.0           # the game's own repeat: unknown until measured
    else:
        per = max(math.ceil(max(gap_s, 0.0) / tick_s - 1e-9), 2 if style == "edge" else 1)
        rate = 1.0 / (per * tick_s)
    return min(rate, cap_hz) if cap_hz > 0 else rate


# --- the pattern's state ------------------------------------------------------------------------------------------------
COUNTERS = ("shots", "scattered", "centred", "hops", "unearned")


class FirePattern:
    """One bot's fire pattern: which shot of the scatter is next, how many shots the current target took, whether the
    shots are having an effect. Stats (prefix_): shots, scattered (shots aimed off the chest), centred, hops,
    unearned (shots kept on the chest for want of an effect), and prefix_family / prefix_k."""

    def __init__(self, stats: dict | None = None, prefix: str = "fire_pattern"):
        self.stats = stats if stats is not None else {}
        self.prefix = prefix
        self.trigger = Trigger()
        self.k = 0                                          # the scatter's index (the next shot's point)
        self.key = None                                     # the target the shots are on
        self.on_n = 0                                       # shots on him in a row
        self.effect_at = -1e9
        self._hp: dict = {}
        self._kills = None
        self.step_at = None
        for c in COUNTERS:
            self.stats.setdefault(f"{prefix}_{c}", 0)

    def _count(self, c: str, n: int = 1) -> None:
        key = f"{self.prefix}_{c}"
        self.stats[key] = self.stats.get(key, 0) + n

    # -- evidence --
    def effect(self, at) -> None:
        """The title's own evidence of an effect (its last hit / kill time)."""
        if isinstance(at, (int, float)) and not isinstance(at, bool) and at > self.effect_at:
            self.effect_at = float(at)

    def observe(self, now: float, enemies=None, hit: bool = False, kills=None) -> None:
        """Every tick: an enemy's health falling, the kill count rising (or the title's own hit) is an effect: the
        scatter is earned."""
        if hit:
            self.effect_at = now
        if isinstance(kills, int) and not isinstance(kills, bool):
            last = getattr(self, "_kills", None)
            if isinstance(last, int) and kills > last:
                self.effect_at = now
            self._kills = kills
        if enemies is None:
            return
        seen = {}
        for e in enemies:
            if not isinstance(e, dict):
                continue
            k, hp = e.get("ptr", e.get("slot")), e.get("hp")
            if k is None or not isinstance(hp, (int, float)) or isinstance(hp, bool):
                continue
            if hp < self._hp.get(k, hp):
                self.effect_at = now
            seen[k] = hp
        self._hp = seen

    def earned(self, sp: FireSpec | None, now: float) -> bool:
        return sp is not None and now - self.effect_at <= sp.earn_s

    # -- shots --
    def shot(self, now: float, key=None, family=None) -> None:
        """A shot left (a press, a tap, a shot motion): the next point of the scatter, the target's count."""
        self.k += 1
        if key != self.key:
            self.key, self.on_n = key, 0
        self.on_n += 1
        self.step_at = now
        self._count("shots")
        if family is not None:
            self.stats[f"{self.prefix}_family"] = family

    def hold_tick(self, now: float, firing: bool, sp: FireSpec | None, key=None, family=None) -> bool:
        """A held trigger with no shot signal: the scatter steps every 1 / step_hz while it fires. True on a step."""
        if not firing or sp is None:
            self.step_at = None
            return False
        if self.step_at is None or now - self.step_at >= 1.0 / max(sp.step_hz, 0.1):
            self.shot(now, key, family)
            return True
        return False

    def point_k(self, sp: FireSpec | None, now: float, dist_cm: float) -> int:
        """The scatter index this shot uses: 0 (the chest) until earned, or up close; else the running index."""
        if sp is None or sp.scatter_w <= 0.0 or dist_cm < sp.min_cm:
            return 0
        if not self.earned(sp, now):
            return 0
        return max(self.k, 1)

    def note(self, k: int, sp: FireSpec | None, now: float) -> None:
        """The shot about to leave: scattered, centred, or kept on the chest for want of an effect (the stats)."""
        if sp is None:
            return
        if k > 0:
            self._count("scattered")
        else:
            self._count("centred" if self.earned(sp, now) or sp.scatter_w <= 0.0 else "unearned")
        self.stats[f"{self.prefix}_k"] = k

    def lateral(self, sp: FireSpec | None, body, now: float, dist_cm: float) -> tuple:
        """(k, lateral, height) of this shot on the body (the body's unit)."""
        k = self.point_k(sp, now, dist_cm)
        lat, h = offset(sp, body, k)
        return k, lat, h

    # -- the hop --
    def hop(self, sp: FireSpec | None, now: float, shooter, target, enemies, *, level_dy: float, units_per_cm: float = 1.0,
            locked: bool = False):
        """The neighbour the next shot goes to, or None (see the module text). shooter / positions in the title's unit."""
        if sp is None or sp.hop_every <= 0 or locked or target is None or self.on_n < sp.hop_every:
            return None
        if target.get("ptr", target.get("slot")) != self.key or (target.get("hp") or 0) <= 0:
            return None
        if not self.earned(sp, now):
            return None
        tp = target["pos"]
        bt = heading(tp[0] - shooter[0], tp[2] - shooter[2])
        best = None
        for e in enemies or ():
            if not isinstance(e, dict) or e is target or (e.get("hp") or 0) <= 0 or not e.get("pos"):
                continue
            if e.get("ptr", e.get("slot")) == self.key:
                continue
            q = e["pos"]
            if abs(q[1] - shooter[1]) > level_dy:
                continue
            if math.hypot(q[0] - tp[0], q[2] - tp[2]) > sp.hop_r_cm * units_per_cm:
                continue
            off = abs(wrap(heading(q[0] - shooter[0], q[2] - shooter[2]) - bt))
            if off > sp.hop_cone:
                continue
            if best is None or off < best[0]:
                best = (off, e)
        if best is None:
            return None
        self.on_n = 0
        self._count("hops")
        return best[1]


# --- the drivers: one per aim model, each title binding it to its own keys ----------------------------------------------
class _Driver:
    """The pattern for one title: its profile (units, bodies, the trigger's style and floor), the family of the gun in
    hand (the title's own map). FIRE_PATTERN off in the title: the title never builds one."""
    model = ""

    def __init__(self, stats: dict | None = None, prefix: str = "fire_pattern"):
        self.fp = FirePattern(stats, prefix)
        self.stats = self.fp.stats

    def spec(self, family):
        return spec(family)

    def observe(self, now: float, enemies=None, hit: bool = False, kills=None) -> None:
        self.fp.observe(now, enemies, hit, kills)

    def fired(self, now: float, key=None, family=None) -> None:
        self.fp.shot(now, key, family)

    def trigger(self, prof, now: float, on: bool, gap_s: float | None = None) -> bool:
        """The rapid repeat in the profile's style (fire_style) at its floor (fire_gap_s, or gap_s)."""
        return self.fp.trigger.tick(now, on, getattr(prof, "fire_style", "hold"),
                                    prof.fire_gap_s if gap_s is None else gap_s)

    def hop(self, prof, family, now: float, shooter, target, enemies, locked: bool = False):
        return self.fp.hop(self.spec(family), now, shooter, target, enemies,
                           level_dy=prof.units(prof.level_dy_cm), units_per_cm=prof.units_per_cm, locked=locked)


class TankDriver(_Driver):
    """tank_heading (RE4 Switch, RE4 GC): the scatter as a yaw offset. aim(...) -> (the error to steer / request, the
    offset): steer the facing to the bearing + offset (err + offset; err = bearing - facing); the fire gate stays the
    body's half-angle on err, so a scattered shot is the same shot the gate allowed before."""
    model = "tank_heading"

    def aim(self, prof, family, e, dist, err: float, now: float, shot: bool = False) -> tuple:
        sp = self.spec(family)
        if sp is None:
            return err, 0.0
        body = prof.body_units(e)
        k, lat, _h = self.fp.lateral(sp, body, now, prof.cm(dist))
        if shot:
            self.fp.note(k, sp, now)
        off = yaw_offset(lat, dist)
        return err + off, off


class LaserDriver(_Driver):
    """laser_ray (RE5 Switch, RE5 PS3): the point to steer the laser onto while it is on him - the title's own aim
    point (its chest, its learned aim height) moved by the scatter; the title's own ray_error steers to it. The point's
    height stays inside his body: the title's aim height plus the scatter's rise over the chest, held between knee + 5
    and the lower of his head and shoulder + 15 (a title aiming at a special site - the head, the thighs - gets the
    lateral scatter only)."""
    model = "laser_ray"
    SITE_SHARE = 0.3            # an aim height this share of the knee-to-head span off his chest: a site of its own

    def point(self, prof, family, e, shooter, aim_pt, now: float, shot: bool = False) -> tuple:
        sp = self.spec(family)
        if sp is None:
            return tuple(aim_pt)
        body = prof.body_units(e)
        foot = e["pos"]
        k, lat, h = self.fp.lateral(sp, body, now, prof.cm(math.hypot(foot[0] - shooter[0], foot[2] - shooter[2])))
        if shot:
            self.fp.note(k, sp, now)
        if k == 0:
            return tuple(aim_pt)
        span = float(body.head) - float(body.knee)
        have = float(aim_pt[1]) - float(foot[1])            # the title's own aim height over his feet
        rise = 0.0 if abs(have - float(body.chest)) > self.SITE_SHARE * span else h - float(body.chest)
        unit = float(body.r) / 36.0 if body.r else 1.0
        top = min(float(body.head), float(body.shoulder) + 15.0 * unit)
        want = max(float(body.knee) + 5.0 * unit, min(have + rise, top))
        ax, az = across(shooter, foot)
        return aim_pt[0] + lat * ax, float(foot[1]) + want, aim_pt[2] + lat * az


class CameraDriver(LaserDriver):
    """laser_camera_geometry (RE6 Switch, RE6 PS3): the scatter as an offset added to the title's own aim point (the
    lock's and the sticks'); offset(...) -> (dx, dy, dz) in the title's unit, (0, 0, 0) without a pattern."""
    model = "laser_camera_geometry"

    def offset(self, prof, family, e, shooter, aim_pt, now: float, shot: bool = False) -> tuple:
        p = self.point(prof, family, e, shooter, aim_pt, now, shot=shot)
        return p[0] - aim_pt[0], p[1] - aim_pt[1], p[2] - aim_pt[2]


DRIVERS = {d.model: d for d in (TankDriver, LaserDriver, CameraDriver)}


def driver(prof, stats: dict | None = None, prefix: str = "fire_pattern") -> _Driver:
    """The driver for the profile's aim model (laser_ray when unknown)."""
    return DRIVERS.get(getattr(prof, "aim_model", ""), LaserDriver)(stats, prefix)
