"""Each Mercenaries round's own verdict, written without anyone watching (operator 2026-10-26: "I want you troubleshooting
each and every one of these runs to make sure that they're running the way that they're supposed to, because I don't
like seeing the character lose").

RoundAudit.start(stats) at the round's first frame keeps the run's counters; RoundAudit.finish(summary, trace, stats) at
its end (the round map's summary, the RoundTrace, the bot's stats) returns

    {"verdict": "OK" | "problems", "problems": ["accuracy 31% < 40% (9/29)", ...], "metrics": {...}}

which the round map keeps as "audit" and the bot as stats["round_audit"]. The checks:
  * the character unchanged from the last round (both known), or unknown;
  * RE4: the round's loadout not verified in his hands, its x80 fire interval not applied, no gun in his hands;
  * RE5: the laser read missing for more than LASERLESS_MAX of the gun-up time (the aim is blind then), the rapid-fire
    package not verified, gun-down turning more than SWING_MAX of the fighting; from the round's "combat_look" (the
    bot's own): the gun down turning with a Majini within 4 m over GUN_DOWN_CLOSE_MAX seconds, shots with the dot on the
    floor short of him (WALLS_MIN / WALLS_SHARE, as the walls); the walls shot and the idle streak among foes come from
    the behaviour block (gbox.mercs.behavior_metrics, below), the same for every title;
  * accuracy under ACCURACY_MIN (with at least MIN_SHOTS shots), more than DAMAGE_MAX hits taken, every standstill
    over STILL_S, wall bumps (stuck events) over BUMPS_PER_MIN a minute, a death (with its cause).
Nothing here reads or writes the game.
"""
from __future__ import annotations

import math
from collections import Counter

ACCURACY_MIN, MIN_SHOTS = 0.40, 5
DAMAGE_MAX = 12                       # hits taken in one round
STILL_S = 5.0                         # a standstill this long is a problem
BUMPS_PER_MIN = 3.0                   # stuck events a minute
LASERLESS_MAX = 0.25                  # RE5: share of gun-up samples without a laser ray
SWING_MAX = 0.30                      # RE5: share of fighting spent turning with the gun down
# the behaviour block (gbox.mercs.behavior_metrics): a sine-wave run, a waving gun, shots off target, a slow trigger
WEAVE_P90_MM, STICK_REV_S = 900.0, 1.0
AIM_REV_S, SWITCHES_MIN, OFF_TARGET_SHARE = 1.5, 6.0, 0.30
BLAST_MIN_S = 5.0                     # shots a second with the trigger held on target: under it, no "blasting like mad"
WALLS_MIN, WALLS_SHARE = 5, 0.10      # this many shots (and this share of them) with the aim line on a wall
IDLE_AMONG_FOES_S = 3.0               # standing this long among foes without moving or shooting
GUN_DOWN_CLOSE_MAX = 5.0              # RE5 (the round's "combat_look"): seconds turning with the gun down while a Majini
                                      # stood within 4 m (operator 2026-10-26: "she lowered her gun ... circled around him")
COUNTERS = ("shots", "hits", "misses", "kills", "hits_taken", "player_damage_events", "deaths", "stuck_events", "stuck",
            "vaults", "detours", "backoffs", "evades", "quick_turns")
UNKNOWN = (None, "", "Unknown", "unknown", "?")


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    try:
        f = float(str(v).strip())
    except ValueError:
        return None
    return f if math.isfinite(f) else None


class RoundAudit:
    def __init__(self, title: str):
        self.title = title
        self.base: dict = {}
        self.prev: dict | None = None             # the last finished round's {character, weapon}
        self.last: dict | None = None             # the last audit

    def start(self, stats: dict) -> None:
        self.base = {k: _num(stats.get(k)) for k in COUNTERS}

    def delta(self, stats: dict, key: str):
        """The counter's growth this round (the whole value when the run's counters started over)."""
        now, was = _num(stats.get(key)), self.base.get(key)
        if now is None:
            return None
        return now if was is None or now < was else now - was

    def finish(self, summary: dict, trace, stats: dict) -> dict:
        problems: list = []
        metrics: dict = {"seconds": summary.get("seconds")}
        minutes = max((summary.get("seconds") or 0.0) / 60.0, 1e-6)
        states = list(getattr(trace, "states", None) or [])
        events = list(getattr(trace, "events", None) or [])

        character = summary.get("character") if summary.get("character") not in UNKNOWN else stats.get("character")
        metrics["character"] = character
        if character in UNKNOWN:
            problems.append("character unknown (no Select Player read this round)")
        elif self.prev and self.prev.get("character") == character:
            problems.append(f"character unchanged: {character} again")
        weapons = Counter(str(s.get("weapon")).split(" (")[0] for s in states if s.get("weapon"))
        weapon = weapons.most_common(1)[0][0] if weapons else None
        metrics["weapon"] = weapon

        # shots: the round's ballistic report (RE5's shot records), else the counters' growth this round
        rep = summary.get("ballistics") or {}
        if rep.get("source") == "shot records" and rep.get("shots"):
            shots, hits = rep.get("hits", 0) + rep.get("misses", 0), rep.get("hits", 0)
        else:
            hits, misses = self.delta(stats, "hits"), self.delta(stats, "misses")
            shots = (hits or 0) + (misses or 0) if hits is not None or misses is not None else self.delta(stats, "shots")
            hits = hits or 0
        metrics.update(shots=int(shots or 0), hits=int(hits or 0),
                       accuracy=round(hits / shots, 3) if shots else None)
        if shots and shots >= MIN_SHOTS and hits / shots < ACCURACY_MIN:
            problems.append(f"accuracy {hits / shots:.0%} < {ACCURACY_MIN:.0%} ({int(hits)}/{int(shots)})")
        if not shots and summary.get("seconds", 0) >= 30:
            problems.append("no shot fired in the round")

        taken = self.delta(stats, "hits_taken")
        if taken is None:
            taken = self.delta(stats, "player_damage_events")
        if taken is None:
            taken = sum(1 for e in events if e.get("kind") == "hit")
        metrics["hits_taken"] = int(taken or 0)
        if taken and taken > DAMAGE_MAX:
            problems.append(f"{int(taken)} hits taken (> {DAMAGE_MAX})")

        if summary.get("operator_s"):                     # a pad takeover (gbox.pad_takeover): the operator's time
            metrics["operator_s"] = summary["operator_s"]
        still = [s for s in summary.get("standstills") or () if (s.get("seconds") or 0) > STILL_S and not s.get("operator")]
        metrics["standstills_over_5s"] = len(still)
        metrics["standstill_s"] = round(sum(s["seconds"] for s in still), 1)
        if still:
            worst = max(still, key=lambda s: s["seconds"])
            problems.append(f"{len(still)} standstill(s) over {STILL_S:g} s ({metrics['standstill_s']:g} s; worst "
                            f"{worst['seconds']:g} s in {worst.get('phase')})")

        bumps = self.delta(stats, "stuck_events")
        if bumps is None:
            bumps = summary.get("stuck_events") or 0
        metrics["wall_bumps"] = int(bumps or 0)
        metrics["wall_bumps_per_min"] = round((bumps or 0) / minutes, 2)
        if bumps and bumps / minutes > BUMPS_PER_MIN:
            problems.append(f"{bumps / minutes:.1f} wall bumps a minute ({int(bumps)} stuck events)")

        died = [e for e in events if e.get("kind") == "death"]
        deaths = self.delta(stats, "deaths")
        metrics["deaths"] = max(len(died), int(deaths or 0))
        if metrics["deaths"]:
            cause = (died[-1].get("cause") if died else None) or stats.get("death_cause") or "cause unknown"
            problems.append(f"died: {str(cause)[:120]}")

        if self.title == "G4BE08":
            self._re4(stats, states, problems, metrics)
        elif self.title == "BLUS30491":
            self._re5(summary, stats, states, problems, metrics)
        if isinstance(summary.get("behavior"), dict):
            self._behavior(summary["behavior"], problems, metrics)

        out = {"verdict": "problems" if problems else "OK", "problems": problems, "metrics": metrics}
        self.prev = {"character": character if character not in UNKNOWN else None, "weapon": weapon}
        self.last = out
        return out

    @staticmethod
    def _behavior(b: dict, problems: list, metrics: dict) -> None:
        """The round map's "behavior" block (gbox.mercs.behavior_metrics): the weave, the aim, the doorways, pickups, time
        bonuses passed, chicken shots and the fire rate per weapon class."""
        path, aim = b.get("path") or {}, b.get("aim") or {}
        metrics["behavior"] = {"lateral_mm_p90": path.get("lateral_mm_p90"),
                               "stick_reversals_per_s": path.get("stick_reversals_per_s"),
                               "aim_reversals_per_s": aim.get("reversals_per_s"),
                               "switches_per_min": aim.get("switches_per_min"),
                               "shots_off_target": aim.get("shots_off_target"),
                               "portal_passes": b.get("portal_passes"), "portal_bumps": b.get("portal_bumps"),
                               "ammo_pickups": b.get("ammo_pickups"), "bonuses_passed": b.get("bonuses_passed"),
                               "fire_rate": {k: v.get("shots_per_s") for k, v in (b.get("fire_rate") or {}).items()},
                               "walls_shot": b.get("walls_shot"),
                               "idle_among_foes_max_s": (b.get("idle_among_foes") or {}).get("max_s")}
        if (path.get("lateral_mm_p90") or 0) > WEAVE_P90_MM or (path.get("stick_reversals_per_s") or 0) > STICK_REV_S:
            problems.append(f"path weave: {path.get('lateral_mm_p90')} mm off the planned path (p90), "
                            f"{path.get('stick_reversals_per_s')} stick reversals a second")
        if (aim.get("reversals_per_s") or 0) > AIM_REV_S or (aim.get("switches_per_min") or 0) > SWITCHES_MIN:
            problems.append(f"gun waving: {aim.get('reversals_per_s')} aim reversals a second, "
                            f"{aim.get('switches_per_min')} target switches a minute with the gun up")
        on, off = aim.get("shots_on_target") or 0, aim.get("shots_off_target") or 0
        if on + off >= 10 and off / (on + off) > OFF_TARGET_SHARE:
            problems.append(f"{off} of {on + off} shots outside the on-target window")
        bad = [p for p in b.get("portals") or () if p.get("bumps", 0) >= 2 and p["bumps"] > p.get("passes", 0)]
        if bad:
            problems.append(f"doorways: {len(bad)} portal(s) bumped more than passed (worst {max(p['bumps'] for p in bad)} "
                            f"bumps at {bad[0].get('pos')})")
        if b.get("ammo_pickups"):
            problems.append(f"{b['ammo_pickups']} ammo pickup(s) (infinite ammo: never needed)")
        if b.get("bonuses_passed"):
            problems.append(f"{b['bonuses_passed']} time bonus(es) passed within reach and not taken")
        chick = b.get("chicken_shots") or {}
        if chick.get("unaimed"):
            problems.append(f"{chick['unaimed']} chicken shot(s) without the aim on the chicken")
        slow = {k: v.get("shots_per_s") for k, v in (b.get("fire_rate") or {}).items()
                if (v.get("held_s") or 0) >= 2 and v.get("shots_per_s") is not None and v["shots_per_s"] < BLAST_MIN_S}
        if slow:
            problems.append("not blasting: " + ", ".join(f"{k} {v:g} shots/s held" for k, v in slow.items()))
        lines = b.get("shot_lines") or {}
        walls, fired = b.get("walls_shot") or 0, sum(v for v in lines.values() if isinstance(v, (int, float)))
        if walls >= WALLS_MIN and fired and walls / fired >= WALLS_SHARE:
            problems.append(f"shooting walls: {walls} of {fired} shots had the aim line on a wall")
        idle = b.get("idle_among_foes") or {}
        if (idle.get("max_s") or 0) >= IDLE_AMONG_FOES_S:
            problems.append(f"sat among foes: {idle['max_s']:g} s without moving or shooting with a foe near "
                            f"({idle.get('total_s'):g} s in the round)")

    @staticmethod
    def _re4(stats, states, problems, metrics):
        lo = stats.get("round_loadout") if isinstance(stats.get("round_loadout"), dict) else None
        metrics["round_loadout"] = {k: lo.get(k) for k in ("gun", "equipped", "fire_x", "fire_interval_frames",
                                                           "fire_applied", "equipped_ok", "verified")} if lo else None
        if lo is None or lo.get("round") != stats.get("rounds"):
            problems.append("loadout not verified: no round loadout recorded for this round")
        else:
            if lo.get("verified") is not True:
                problems.append(f"loadout not verified: {lo.get('reason') or 'unverified'}")
            if lo.get("fire_applied") is False:
                problems.append(f"fire rate not applied: interval {lo.get('fire_interval_frames')} frames, want "
                                f"{lo.get('fire_want_frames')}")
        no_gun = sum(1 for s in states if str(s.get("weapon") or "").startswith(("item 0x800", "none")))
        if states and no_gun > 0.5 * len(states):
            problems.append(f"no gun in his hands for {no_gun / len(states):.0%} of the round")
        if stats.get("trigger_mode", "").startswith("tap: A held"):
            problems.append(f"rapid fire fell back to presses: {stats['trigger_mode']}")

    @staticmethod
    def _re5(summary, stats, states, problems, metrics):
        up = [s for s in states if str(s.get("aim_feedback") or "") in
              ("ray direction", "near-origin ray; correction paused", "laserless gun camera direction; no projectile ray")]
        laserless = sum(1 for s in up if "laserless" in str(s.get("aim_feedback")))
        metrics["laserless_share"] = round(laserless / len(up), 3) if up else None
        if len(up) >= 10 and laserless / len(up) > LASERLESS_MAX:
            rate = metrics.get("accuracy")
            problems.append(f"no laser ray for {laserless / len(up):.0%} of the gun-up time ({metrics.get('weapon')}"
                            + (f", hit rate {rate:.0%}" if rate is not None else "") + ")")
        if stats.get("rapid_fire_verified") is False:
            problems.append("rapid fire not verified (the weapon table's interval is not 0)")
        turning = (summary.get("ballistics") or {}).get("turning") or {}
        share = turning.get("swing_share")
        metrics["swing_share"] = share
        if isinstance(share, (int, float)) and share > SWING_MAX and (turning.get("fight_s") or 0) >= 20:
            problems.append(f"gun-down turning {share:.0%} of {turning.get('fight_s'):g} s fighting")
        look = summary.get("combat_look") if isinstance(summary.get("combat_look"), dict) else None
        if look is None:
            return
        walls, floor = int(_num(look.get("walls_shot")) or 0), int(_num(look.get("floor_shots")) or 0)
        idle, idle_max = _num(look.get("idle_among_foes_s")) or 0.0, _num(look.get("idle_max_s")) or 0.0
        down, close = _num(look.get("gun_down_close_s")) or 0.0, _num(look.get("foes_close_s")) or 0.0
        metrics.update(walls_shot=walls, floor_shots=floor, idle_among_foes_s=round(idle, 1),
                       idle_among_foes_max_s=round(idle_max, 1), gun_down_close_s=round(down, 1),
                       foes_close_s=round(close, 1))
        lines = (summary.get("behavior") or {}).get("shot_lines") or {}
        fired = sum(v for v in lines.values() if isinstance(v, (int, float))) or metrics.get("shots") or 0
        if floor >= WALLS_MIN and fired and floor / fired >= WALLS_SHARE:
            problems.append(f"shooting the floor: {floor} of {int(fired)} shots had the dot on the floor short of him")
        if down > GUN_DOWN_CLOSE_MAX:
            problems.append(f"gun-down turning with a Majini within 4 m: {down:g} s of {close:g} s with one that close")
