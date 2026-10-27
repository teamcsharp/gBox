"""Ballistic reports and the first aim calibration for the Mercenaries bots.

Operator 2026-10-26: "If they are shooting and missing then i want you seeing why and how they missed so you can adjust
the aimbot to be more accurate. Every attack should be informing you about shortcomings ... I want the characters able
to longshot foes from across the stage and be able to dispatch with greater and greater accuracy due to our
calibrations." Earlier: "Every landed shot should better inform and train the system on how to aim".

  * a shot record: every shot the combat layer fires, with the aim it had at the trigger (titles/re5_combat.Combat
    builds them: weapon, character, ground distance, height difference, zone and aim point, where the laser dot sat,
    the yaw / pitch error at the trigger, the player's pitch, his body's turn rate, the target's speed, the fire gate,
    the aim state) and what it did (hit / miss / headshot, time to hit). The round map keeps the whole round ("shots");
  * report(records): the round's ballistic report - hit rate by weapon, distance band, zone, dot, gate and aim state;
    the error at hits vs misses; the top miss causes (MISS_CAUSES, first match wins); longshots; the time spent turning
    with the gun down and the hits he took meanwhile. RoundTrace.finish keeps it in the round map ("ballistics"),
    writes it beside it (ballistics/<stem>.json / .md) and draws its two lines under the map;
  * Calibration: per (character, weapon, distance band) the aim correction learned from the hits (their centre around
    the nominal aim point, bounded, an EMA over rounds), the band's last WINDOW shots (the trigger's tolerance) and the
    hits' trigger errors (the p90 gate), in the learn dir (CALIBRATION_FILE; re5_combat.json is left alone).

Round maps written before the records existed still get a report: from the 0.25 s state samples alone (approximate:
no distances), or joined with the run lessons' shot rows (each shot's distance, dot and result):

    python -m gbox.mercs.ballistics <round_map.json> [lessons.jsonl ...] [--markdown]
"""
from __future__ import annotations

import bisect
import json
import math
import os
import re
import statistics
import time
from collections import Counter
from pathlib import Path

BANDS = ((200.0, "0-2"), (500.0, "2-5"), (1000.0, "5-10"), (2000.0, "10-20"), (math.inf, "20+"))   # ground cm -> m band
BAND_NAMES = tuple(name for _, name in BANDS)
BAND_NEAR = {"0-2": 100.0, "2-5": 200.0, "5-10": 500.0, "10-20": 1000.0, "20+": 2000.0}   # a band's near edge (cm)
LONG_CM = 1000.0                 # a shot from this far is a longshot in the report
SWING_DEG = 45.0                 # the body this far off him: the gun down, turning (re5_combat.SWING_TURN)
TURNING_DEG_S = 45.0             # the body turning faster than this at the trigger (aiming turns ~30 deg/s)
FAST_CM_S = 250.0                # the target moving faster than this: running (re5_ps3.RUN_SPEED)
WILD_YAW_DEG, WILD_PITCH_DEG = 30.0, 25.0   # re5_combat.WILD_YAW / WILD_PITCH: a torn read, not an aim
FIGHT_PHASES = frozenset({"fight", "clear_nearby", "stand"})   # the phases where the combat line is the live decision
STALL_DEG = 3.0                  # a gun-down swing whose angle to him moves less than this per sample: not turning
MISS_CAUSES = ("gun down / turning", "fired while turning", "wild error", "line blocked", "too far for the weapon",
               "target moving fast", "dot off him", "dot on him (moved / late)", "no ray at the trigger")
CALIBRATION_FILE = "aim_calibration.json"
YAW_MAX, PITCH_MAX = 3.0, 4.0           # degrees: the correction's bounds, and never past the body's half width /
BODY_HALF_W, BODY_HALF_H = 36.0, 50.0   # half height at the band's near edge (re5_combat.BODY_R, (SHOULDER_H-KNEE_H)/2)
EMA = 0.3                               # a round's weight in the correction
MIN_HITS = 3                            # a round teaches a band with this many steady hits there
WINDOW, WINDOW_MIN = 20, 10             # the band's last shots (the tolerance rules wait for WINDOW_MIN of them)
WIDE_AT, STRICT_BELOW = 0.90, 0.50      # the window's hit rate: a wider trigger / the dot required on him
P90_KEEP, P90_MIN = 50, 10              # the hits' trigger errors kept per band / needed before the p90 gate
BLAST_GATE = "threat: blasting"         # the operator's close-threat blast: its own policy, never calibrated


def blasted(rec: dict) -> bool:
    """A close-threat blast (the laser path's BLAST_GATE, or the laserless one's "threat: blasting (laserless)"): fired by
    policy whatever the aim, so never in the calibration's windows."""
    return str(rec.get("gate") or "").startswith(BLAST_GATE)


def band(dist) -> str | None:
    d = _num(dist)
    if d is None:
        return None
    return next(name for edge, name in BANDS if d < edge)


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


def turn_point(origin, point, dyaw: float, dpitch: float) -> tuple:
    """point turned about origin by dyaw (radians of heading, re5_combat.heading's sense) and raised by dpitch."""
    if not dyaw and not dpitch:
        return tuple(point)
    ox, oy, oz = origin
    dx, dz = point[0] - ox, point[2] - oz
    flat = math.hypot(dx, dz)
    if flat < 1.0:
        return tuple(point)
    h = math.atan2(dx, dz) + dyaw
    e = max(-1.4, min(1.4, math.atan2(point[1] - oy, flat) + dpitch))
    return (ox + flat * math.sin(h), oy + flat * math.tan(e), oz + flat * math.cos(h))


# --- the aim at the trigger, from a round map's combat line -----------------------------------------------------
_AIM = re.compile(r"^(?P<char>\S+) w(?P<wid>0x[0-9a-f]+|unknown) (?P<zone>\w+) dot (?P<where>\w+) "
                  r"yaw (?P<yaw>[-+]?\d+(?:\.\d+)?) pitch (?P<pitch>[-+]?\d+(?:\.\d+)?)(?P<rest>.*)$")
_SWING = re.compile(r"swinging round to him \(gun down\): (?P<deg>[-+]?\d+(?:\.\d+)?)")
_LASERLESS = re.compile(r"yaw (?P<yaw>[-+]?\d+(?:\.\d+)?) pitch (?P<pitch>[-+]?\d+(?:\.\d+)?)")


def aim_state(combat) -> str | None:
    """The aim state a combat line names: aim (steering the laser ray), readying (the gun coming up, no ray), swing
    (the gun down while the body turns to him: the laser path's swing and quick turn, the laserless / longbow turn,
    the front-candidate turn), laserless, reacquire, out of range, other."""
    c = str(combat or "")
    if not c:
        return None
    if c.startswith(("swinging round", "turning toward", "quick turn")) or "lower weapon and turn" in c \
            or "finish committed body turn" in c:
        return "swing"
    if c.startswith("readying"):
        return "readying"
    if " dot " in c and " yaw " in c:
        return "aim"
    if c.startswith(("laserless", "longbow", "rotten egg")):
        return "laserless"
    if c.startswith(("reacquire", "reposition")):
        return "reacquire"
    if c.startswith("target outside"):
        return "out of range"
    return "other"


def parse_combat(combat) -> dict:
    """What a combat line says about the aim (re5_combat.Combat's stats["combat"])."""
    c = str(combat or "")
    out = {"state": aim_state(c)}
    m = _AIM.match(c)
    if m:
        out.update(character=m["char"], zone=m["zone"], yaw_err=float(m["yaw"]), pitch_err=float(m["pitch"]),
                   where=None if m["where"] == "None" else m["where"], fire="FIRE" in m["rest"])
        if m["wid"] != "unknown":
            out["wid"] = int(m["wid"], 16)
        if " guard " in m["rest"]:
            out["guard"] = m["rest"].rsplit(" guard ", 1)[1].strip()
        return out
    m = _SWING.search(c)
    if m:
        out["facing"] = float(m["deg"])
        return out
    if out["state"] == "laserless":
        m = _LASERLESS.search(c)
        if m:
            out.update(cam_yaw=float(m["yaw"]), cam_pitch=float(m["pitch"]))
        out["fire"] = "TRIGGER" in c
    elif out["state"] == "readying":
        out["fire"] = "FIRE" in c
    return out


def steady(rec: dict) -> bool:
    """An aimed shot whose trigger error describes the aim: the laser ray steering, the body not swinging or turning
    fast, the error no torn read."""
    ye, pe = _num(rec.get("yaw_err")), _num(rec.get("pitch_err"))
    return (rec.get("state") == "aim" and rec.get("steer", True) is not False and ye is not None and pe is not None
            and abs(ye) <= WILD_YAW_DEG and abs(pe) <= WILD_PITCH_DEG
            and (_num(rec.get("turn")) or 0.0) <= TURNING_DEG_S and abs(_num(rec.get("facing")) or 0.0) <= SWING_DEG)


def causes(rec: dict) -> list:
    """Why a shot missed, in MISS_CAUSES order (the first is the round report's count)."""
    out = []
    facing = _num(rec.get("facing"))
    if rec.get("state") == "swing" or (facing is not None and abs(facing) > SWING_DEG):
        out.append("gun down / turning")
    if (_num(rec.get("turn")) or 0.0) > TURNING_DEG_S:
        out.append("fired while turning")
    ye, pe = _num(rec.get("yaw_err")), _num(rec.get("pitch_err"))
    has_err = ye is not None and pe is not None
    wild = has_err and (abs(ye) > WILD_YAW_DEG or abs(pe) > WILD_PITCH_DEG)
    if wild:
        out.append("wild error")
    where = rec.get("where")
    on_him = where in ("head", "body", "leg")
    if not on_him and rec.get("reach") == "short":
        out.append("line blocked")
    rng, dist = _num(rec.get("rng")), _num(rec.get("dist"))
    if rng and dist and dist > rng:
        out.append("too far for the weapon")
    if (_num(rec.get("speed")) or 0.0) > FAST_CM_S:
        out.append("target moving fast")
    if on_him:
        out.append("dot on him (moved / late)")
    elif has_err and not wild:
        out.append("dot off him")
    elif not has_err:
        out.append("no ray at the trigger")
    return out


# --- the report -------------------------------------------------------------------------------------------------
def _rate(hits, misses):
    return round(hits / (hits + misses), 3) if hits + misses else None


def _tally(recs, key, order=None) -> dict:
    out: dict = {}
    for r in recs:
        k = key(r)
        row = out.setdefault("?" if k is None else str(k), {"shots": 0, "hits": 0, "misses": 0})
        row["shots"] += 1
        row["hits"] += r.get("result") == "hit"
        row["misses"] += r.get("result") == "miss"
    for row in out.values():
        row["rate"] = _rate(row["hits"], row["misses"])
    if order:
        return {k: out[k] for k in (*order, "?") if k in out} | {k: v for k, v in out.items() if k not in order}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["shots"]))


def _errors(recs) -> dict:
    pairs = [(_num(r.get("yaw_err")), _num(r.get("pitch_err"))) for r in recs]
    pairs = [(y, p) for y, p in pairs if y is not None and p is not None]
    if not pairs:
        return {"n": 0}
    ys, ps = [y for y, _ in pairs], [p for _, p in pairs]
    mags = [math.hypot(y, p) for y, p in pairs]
    return {"n": len(pairs), "yaw_mean": round(statistics.fmean(ys), 2), "yaw_median": round(statistics.median(ys), 2),
            "pitch_mean": round(statistics.fmean(ps), 2), "pitch_median": round(statistics.median(ps), 2),
            "abs_mean": round(statistics.fmean(mags), 2), "abs_median": round(statistics.median(mags), 2)}


def _weapon_key(r):
    wid = r.get("wid")
    if not isinstance(wid, int):
        return None
    return f"{wid:#x} {r['weapon']}" if r.get("weapon") else f"{wid:#x}"


def _gate_key(r):
    g = r.get("gate")
    return re.sub(r"\d+(\.\d+)?", "#", str(g))[:60] if g else None


def turning(states, samples) -> dict:
    """Time spent turning with the gun down while fighting, and the hits he took then: the damage counter
    (player_damage_events, RE4's hits_taken) rising at a sample whose combat line is a swing. The engine counts the
    damage before the bot's tick, so a sample's combat line is the decision that was running when the hit landed.
    A swing whose angle to him stays within STALL_DEG from one sample to the next is not turning at all (stalled_s:
    Prison 2026-10-26 12:38 held "-71 deg" for 36 samples)."""
    fight_s = swing_s = stalled_s = 0.0
    taken = taken_swing = 0
    known, prev, prev_facing = False, None, None
    for k, st in enumerate(states or ()):
        dt = min(samples[k + 1][0] - samples[k][0], 2.0) if k + 1 < len(samples or ()) else 0.0
        fighting = st.get("phase") in FIGHT_PHASES
        swinging = fighting and aim_state(st.get("combat")) == "swing"
        facing = parse_combat(st.get("combat")).get("facing") if swinging else None
        if fighting:
            fight_s += dt
            swing_s += dt if swinging else 0.0
            stalled_s += dt if facing is not None and prev_facing is not None and abs(facing - prev_facing) <= STALL_DEG else 0.0
        prev_facing = facing
        n = _num(st.get("player_damage_events", st.get("hits_taken")))
        if n is None:
            continue
        known = True
        if prev is not None and n > prev:
            taken += int(n - prev)
            taken_swing += int(n - prev) if swinging else 0
        prev = n
    return {"fight_s": round(fight_s, 2), "swing_s": round(swing_s, 2), "swing_stalled_s": round(stalled_s, 2),
            "swing_share": round(swing_s / fight_s, 3) if fight_s else None,
            "hits_taken": taken if known else None, "hits_taken_swinging": taken_swing if known else None}


def report(records, *, states=None, samples=None, started=None, meta=None, source=None) -> dict:
    """The round's ballistic report from its shot records (or, with none, from the round map's state samples)."""
    recs = [r for r in records or () if isinstance(r, dict)]
    src = source or "shot records"
    if not recs and states:
        recs = records_from_trace(states, samples or (), started)
        src = "state samples (approximate: 0.25 s samples, no distances)"
    rep: dict = {"version": 1, **(meta or {}), "source": src, "shots": len(recs)}
    hits = [r for r in recs if r.get("result") == "hit"]
    misses = [r for r in recs if r.get("result") == "miss"]
    rep.update(hits=len(hits), misses=len(misses), hit_rate=_rate(len(hits), len(misses)),
               headshots=sum(1 for r in hits if r.get("headshot")),
               unattributed=sum(1 for r in recs if r.get("result") == "unattributed"),
               unconfirmed=sum(1 for r in recs if r.get("result") == "unconfirmed"),
               pending=sum(1 for r in recs if r.get("result") in (None, "pending")))
    rep["by_weapon"] = _tally(recs, _weapon_key)
    rep["by_band"] = _tally(recs, lambda r: band(r.get("dist")), BAND_NAMES)
    gated = [r for r in recs if not blasted(r) and not r.get("pb")]   # what the calibration decides
    rep["by_band_gated"] = _tally(gated, lambda r: band(r.get("dist")), BAND_NAMES)
    rep["by_zone"] = _tally(recs, lambda r: r.get("zone"))
    rep["by_dot"] = _tally(recs, lambda r: r.get("where") or "off him")
    rep["by_gate"] = _tally(recs, _gate_key)
    rep["by_state"] = _tally(recs, lambda r: r.get("state"))
    rep["error_deg"] = {"hits": _errors(hits), "misses": _errors(misses)}
    primary, contributing = Counter(), Counter()
    for r in misses:
        cs = r.get("causes") or causes(r)
        primary[cs[0] if cs else "unknown"] += 1
        contributing.update(cs)
    rep["miss_causes"] = [[k, v] for k, v in primary.most_common(3)]
    rep["miss_causes_all"] = dict(primary.most_common())
    rep["miss_causes_contributing"] = dict(contributing.most_common())
    far = [r for r in recs if (_num(r.get("dist")) or 0.0) >= LONG_CM]
    far_hits = [r for r in far if r.get("result") == "hit"]
    beyond = [r for r in recs if r.get("longshot")]
    rep["longshots"] = {"from_m": LONG_CM / 100, "shots": len(far), "hits": len(far_hits),
                        "rate": _rate(len(far_hits), sum(1 for r in far if r.get("result") == "miss")),
                        "longest_hit_m": round(max(_num(r.get("dist")) for r in far_hits) / 100, 1) if far_hits else None,
                        "beyond_engage_shots": len(beyond),
                        "beyond_engage_hits": sum(1 for r in beyond if r.get("result") == "hit")}
    turn = turning(states, samples or ()) if states else {}
    swung = [r for r in recs if "gun down / turning" in (r.get("causes") or causes(r))]
    turn.update(shots_swinging=len(swung), hits_swinging=sum(1 for r in swung if r.get("result") == "hit"))
    rep["turning"] = turn
    tth = [_num(r.get("tth")) for r in hits if _num(r.get("tth")) is not None]
    rep["time_to_hit_s"] = {"n": len(tth), "mean": round(statistics.fmean(tth), 3) if tth else None,
                            "median": round(statistics.median(tth), 3) if tth else None}
    cal: dict = {}
    for r in recs:
        if r.get("character") is not None and isinstance(r.get("wid"), int) and band(r.get("dist")):
            key = f"{r['character']}:{r['wid']:#x}:{band(r['dist'])}"
            cal[key] = {k: r.get(k) for k in ("corr", "mode", "p90") if r.get(k) is not None}
    rep["calibration_in_effect"] = {k: v for k, v in cal.items() if v}
    rep["advice"] = advice(rep)
    rep["line"] = line(rep)
    rep["svg_lines"] = svg_lines(rep)
    rep["markdown"] = markdown(rep)
    return rep


def _frac(row) -> str:
    n = row["hits"] + row["misses"]
    return f"{row['hits']}/{n}" + (f" {row['rate']:.0%}" if n >= 10 and row["rate"] is not None else "")


def line(rep: dict) -> str:
    """One line for stats["ballistics"]."""
    if not rep.get("shots"):
        return "no shots"
    parts = [f"{rep['shots']} shots {rep['hits']} hit" + (f" {rep['hit_rate']:.0%}" if rep.get("hit_rate") is not None else "")]
    bands = " ".join(f"{k}m {_frac(v)}" for k, v in rep["by_band"].items() if k != "?" and v["hits"] + v["misses"])
    if bands:
        parts.append(bands)
    if rep["miss_causes"]:
        parts.append("miss: " + ", ".join(f"{k} {v}" for k, v in rep["miss_causes"]))
    lo = rep["longshots"]
    if lo["shots"]:
        parts.append(f"10m+ {lo['hits']}/{lo['shots']}" + (f" best {lo['longest_hit_m']:g}m" if lo["longest_hit_m"] else ""))
    tu = rep.get("turning") or {}
    if tu.get("swing_s"):
        parts.append(f"gun-down turning {tu['swing_s']:g}s" + (f", hit {tu['hits_taken_swinging']} of {tu['hits_taken']} times"
                                                            if tu.get("hits_taken") is not None else ""))
    return " | ".join(parts)


def svg_lines(rep: dict) -> list:
    if not rep.get("shots"):
        return []
    first = f"ballistics: {rep['shots']} shots, {rep['hits']} hits" + (f" ({rep['hit_rate']:.0%})" if rep.get("hit_rate") is not None else "")
    bands = "  ".join(f"{k} m {_frac(v)}" for k, v in rep["by_band"].items() if k != "?" and v["hits"] + v["misses"])
    second = []
    if rep["miss_causes"]:
        second.append("misses: " + ", ".join(f"{k} {v}" for k, v in rep["miss_causes"]))
    lo, tu = rep["longshots"], rep.get("turning") or {}
    if lo["shots"]:
        second.append(f"10 m+ {lo['hits']}/{lo['shots']}")
    if tu.get("swing_s"):
        second.append(f"gun-down turning {tu['swing_s']:g} s" + (f" (hit {tu['hits_taken_swinging']}x)"
                                                              if tu.get("hits_taken_swinging") is not None else ""))
    return [first + (" - " + bands if bands else ""), " | ".join(second)] if second else [first + (" - " + bands if bands else "")]


def advice(rep: dict) -> list:
    """What the numbers ask of the aim (the next correction to make), most pressing first."""
    out = []
    say = {"gun down / turning": "came with the gun down or the body swinging (> 45 deg off him): hold the trigger until "
                                 "the turn ends and the dot is back on him",
           "fired while turning": "left while the body turned faster than 45 deg/s: let the aim settle after a turn",
           "wild error": "had a wild error (a torn read or the dot on something else): the aim guard should hold these",
           "line blocked": "hit something between (the dot short of him): reposition instead of firing into cover",
           "too far for the weapon": "were beyond the weapon's range: switch to a magnum / rifle or close in",
           "target moving fast": "were at a running Majini: lead him more (HEAD_LEAD_S) or wait for him to stop",
           "dot off him": "had the dot off him at a moderate error: steer longer before the trigger (the band's p90 gate)",
           "dot on him (moved / late)": "had the dot on him and still missed: he moved, or the dot was a frame old",
           "no ray at the trigger": "left without a laser ray (the gun coming up, or laserless): no aim was measured"}
    for cause, n in rep.get("miss_causes") or ():
        if n >= 2:
            out.append(f"{n} misses {say.get(cause, cause)}")
    for name, row in (rep.get("by_band_gated") or {}).items():
        n = row["hits"] + row["misses"]
        if name != "?" and n >= 10 and row["rate"] is not None and row["rate"] < STRICT_BELOW:
            out.append(f"{name} m: {row['rate']:.0%} of the {n} shots the gates decide hit: the calibration asks for "
                       f"the dot on him there")
    blast = (rep.get("by_gate") or {}).get(BLAST_GATE)
    if blast and blast["hits"] + blast["misses"] >= 10 and (blast["rate"] or 0) < STRICT_BELOW:
        out.append(f"the close-threat blast hit {blast['rate']:.0%} of {blast['hits'] + blast['misses']} (it fires "
                   f"whatever the aim, by operator policy; its misses are counted in the causes above)")
    tu = rep.get("turning") or {}
    if tu.get("hits_taken"):
        out.append(f"he was hit {tu['hits_taken']} times, {tu['hits_taken_swinging']} of them while turning with the "
                   f"gun down ({tu['swing_s']:g} s of {tu['fight_s']:g} s fighting)")
    if (tu.get("swing_stalled_s") or 0) >= 5:
        out.append(f"{tu['swing_stalled_s']:g} s of gun-down swinging did not turn him (the angle to the Majini stood "
                   f"still): the turn input is not reaching the body there")
    return out[:7]


def markdown(rep: dict) -> str:
    title = " - ".join(str(rep[k]) for k in ("room", "round_id") if rep.get(k))
    out = [f"### Ballistics{' - ' + title if title else ''}", ""]
    if not rep.get("shots"):
        return "\n".join(out + ["No shots this round."])
    pct = lambda v: f"{v:.0%}" if v is not None else "-"
    tth = rep["time_to_hit_s"]
    out.append(f"{rep['shots']} shots, {rep['hits']} hits ({pct(rep['hit_rate'])}), {rep['misses']} misses, "
               f"{rep['headshots']} headshots" + (f"; time to hit {tth['median']:.2f} s median" if tth.get("median") is not None else "")
               + (f"; {rep['unattributed']} unattributed" if rep.get("unattributed") else "") + f". Source: {rep['source']}.")
    gated = rep.get("by_band_gated") or {}
    out += ["", "| distance | shots | hits | misses | rate | the gates' shots (no blast / point blank) |",
            "|---|---|---|---|---|---|"]
    out += [f"| {k} m | {v['shots']} | {v['hits']} | {v['misses']} | {pct(v['rate'])} | "
            f"{_frac(gated[k]) if k in gated else '-'} |" for k, v in rep["by_band"].items()]
    out.append("")
    for label, key in (("By weapon", "by_weapon"), ("By gate", "by_gate"), ("By dot at the trigger", "by_dot"),
                       ("By zone", "by_zone"), ("By aim state", "by_state")):
        rows = [f"{k} {_frac(v)}" for k, v in list(rep[key].items())[:6]]
        if rows:
            out.append(f"- {label}: " + "; ".join(rows))
    e = rep["error_deg"]
    fmt = lambda s: (f"yaw {s['yaw_mean']:+.1f} (median {s['yaw_median']:+.1f}), pitch {s['pitch_mean']:+.1f} "
                     f"(median {s['pitch_median']:+.1f}), |error| median {s['abs_median']:.1f} (mean {s['abs_mean']:.1f}) "
                     f"deg, n {s['n']}") if s.get("n") else "n 0"
    out.append(f"- Error at the trigger: hits {fmt(e['hits'])}; misses {fmt(e['misses'])}")
    if rep["miss_causes"]:
        out.append("- Top miss causes: " + " / ".join(f"{k} {v}" for k, v in rep["miss_causes"]))
    lo = rep["longshots"]
    out.append(f"- Longshots ({lo['from_m']:g} m+): {lo['hits']}/{lo['shots']} hit"
               + (f", longest {lo['longest_hit_m']:g} m" if lo["longest_hit_m"] else "")
               + (f"; beyond the engage range (dot on him): {lo['beyond_engage_hits']}/{lo['beyond_engage_shots']}"
                  if lo["beyond_engage_shots"] else ""))
    tu = rep.get("turning") or {}
    if tu:
        bits = []
        if tu.get("fight_s") is not None:                     # the round map's samples: time and the hits he took
            bits.append(f"{tu['swing_s']:g} s of {tu['fight_s']:g} s fighting"
                        + (f" ({tu['swing_stalled_s']:g} s of it not turning)" if tu.get("swing_stalled_s") else ""))
            bits.append(f"hits taken while turning {tu['hits_taken_swinging']} of {tu['hits_taken']}"
                        if tu.get("hits_taken") is not None else "hits taken not in this round map")
        bits.append(f"shots fired while turning {tu.get('shots_swinging', 0)} ({tu.get('hits_swinging', 0)} hit)")
        out.append("- Gun-down turning: " + "; ".join(bits))
    if rep.get("calibration_in_effect"):
        out.append("- Calibration in effect: " + "; ".join(
            f"{k} {v}" for k, v in list(rep["calibration_in_effect"].items())[:6]))
    if rep.get("advice"):
        out += ["", "Next corrections:"] + [f"- {a}" for a in rep["advice"]]
    return "\n".join(out)


# --- records for round maps written before the records existed --------------------------------------------------
def records_from_trace(states, samples, started=None) -> list:
    """One approximate record per shot from a round map's state samples: a sample where the shot counter rose, with
    the aim of the sample before it (the trigger held) and the result as the hit / miss counters rose after it
    (oldest shot first; misses expire before hits score, as aim.Shots does)."""
    out, pending = [], []
    prev = h_prev = m_prev = None
    t0 = started if started is not None else (samples[0][0] if samples else 0.0)
    for k, st in enumerate(states or ()):
        n, h, mi = _num(st.get("shots")), _num(st.get("hits")), _num(st.get("misses"))
        if n is not None and prev is not None and n > prev:
            ctx = states[k - 1] if k and aim_state(states[k - 1].get("combat")) else st
            aim = {key: v for key, v in parse_combat(ctx.get("combat")).items() if v is not None}
            weapon = str(ctx.get("weapon") or "")
            for _ in range(int(min(n - prev, 200))):
                rec = {"t": round(samples[k][0] - t0, 2) if k < len(samples) else None, "approx": True,
                       "result": "pending", "gate": ctx.get("fire_gate"), "phase": ctx.get("phase"), **aim}
                if weapon and "wid" not in rec:
                    rec["weapon"] = weapon.split(" ")[0]
                out.append(rec)
                pending.append(rec)
        if mi is not None and m_prev is not None and mi > m_prev:
            for _ in range(int(mi - m_prev)):
                if pending:
                    r = pending.pop(0)
                    r["result"], r["miss"] = "miss", st.get("last_shot")
        if h is not None and h_prev is not None and h > h_prev:
            for _ in range(int(h - h_prev)):
                if pending:
                    pending.pop(0)["result"] = "hit"
        prev = n if n is not None else prev
        h_prev = h if h is not None else h_prev
        m_prev = mi if mi is not None else m_prev
    return out


def records_from_lessons(rows, states, samples, started=None) -> list:
    """Per-shot records from the run lessons' shot rows (exact result, dot, reach and distance from the muzzle to his
    head) inside the round's time, each with the aim of the state sample just before it."""
    times = [s[0] for s in samples or ()]
    if not times:
        return []
    t0 = started if started is not None else times[0]
    out = []
    for row in rows:
        t = _num(row.get("t"))
        res = str(row.get("result") or "")
        if t is None or not (times[0] - 0.5 <= t <= times[-1] + 1.0) or res.startswith(("bow ", "egg ")):
            continue
        k = max(0, bisect.bisect_right(times, t) - 1)
        aim = {key: v for key, v in parse_combat(states[k].get("combat")).items() if v is not None}
        rec = {"t": round(t - t0, 2), "approx": True, "gate": states[k].get("fire_gate"), "phase": states[k].get("phase"),
               **aim, "dist": row.get("dist_cm"), "where": row.get("dot"), "reach": row.get("reach")}
        if isinstance(row.get("weapon"), int):
            rec["wid"] = row["weapon"]
        if row.get("character"):
            rec["character"] = row["character"]
        if res in ("hit", "headshot"):
            rec["result"], rec["headshot"] = "hit", res == "headshot"
        elif res.startswith("miss"):
            rec["result"], rec["miss"] = "miss", res
        else:
            rec["result"], rec["miss"] = "unattributed", res
        out.append(rec)
    return out


def report_for_map(d: dict, lesson_rows=()) -> dict:
    """The ballistic report for a round map: its shot records, else its lessons' shots joined with its state samples,
    else its state samples alone."""
    meta = {k: d.get(k) for k in ("title", "room", "round_id", "seconds") if d.get(k) is not None}
    states, samples, started = d.get("states") or [], d.get("route") or [], d.get("started")
    if d.get("shots"):
        return report(d["shots"], states=states, samples=samples, started=started, meta=meta)
    recs = records_from_lessons(lesson_rows, states, samples, started) if lesson_rows else []
    if recs:
        return report(recs, states=states, samples=samples, started=started, meta=meta,
                      source="run lessons (per-shot dot, distance and result) + 0.25 s state samples (the aim)")
    return report([], states=states, samples=samples, started=started, meta=meta)


# --- the calibration --------------------------------------------------------------------------------------------
def bounds(band_name: str) -> tuple:
    """The correction's bounds (degrees) in a band: YAW_MAX / PITCH_MAX, never past the body's half width / height
    seen from the band's near edge."""
    near = BAND_NEAR.get(band_name, 100.0)
    return (min(YAW_MAX, math.degrees(math.atan2(BODY_HALF_W, near))),
            min(PITCH_MAX, math.degrees(math.atan2(BODY_HALF_H, near))))


def _clamp(v, lim):
    return max(-lim, min(lim, v))


class Calibration:
    """Per (character, weapon, distance band): the aim correction (degrees: the centre of the hits around the nominal
    aim point, EMA over rounds, bounded), the last WINDOW shots ("H"/"M": the trigger's tolerance) and the hits'
    trigger errors (the p90 gate). Kept in learn_dir / CALIBRATION_FILE."""

    def __init__(self, learn_dir, file: str = CALIBRATION_FILE):
        self.path = Path(learn_dir) / file if learn_dir else None
        self.d: dict = {"version": 1, "cells": {}}
        self.dirty = False
        if self.path and self.path.is_file():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict) and isinstance(d.get("cells"), dict):
                    self.d = d
            except (OSError, ValueError):
                pass

    @staticmethod
    def key(character, wid, dist) -> str:
        return f"{character}:{int(wid or 0):#x}:{band(dist) or '?'}"

    def get(self, character, wid, dist) -> dict:
        return self.d["cells"].get(self.key(character, wid, dist)) or {}

    def _cell(self, key) -> dict:
        return self.d["cells"].setdefault(key, {"yaw": 0.0, "pitch": 0.0, "rounds": 0, "shots": 0, "hits": 0,
                                                "recent": "", "hit_err": []})

    def correction(self, character, wid, dist) -> tuple:
        c = self.get(character, wid, dist)
        return float(c.get("yaw") or 0.0), float(c.get("pitch") or 0.0)

    def mode(self, character, wid, dist) -> tuple:
        """("wide" | "strict" | "normal", the window's hit rate or None)."""
        recent = self.get(character, wid, dist).get("recent") or ""
        if len(recent) < WINDOW_MIN:
            return "normal", None
        rate = recent.count("H") / len(recent)
        return ("wide" if rate >= WIDE_AT else "strict" if rate < STRICT_BELOW else "normal"), round(rate, 3)

    def p90(self, character, wid, dist):
        """The 90th percentile (degrees) of the band's steady hits' trigger errors, or None (too few)."""
        errs = self.get(character, wid, dist).get("hit_err") or []
        if len(errs) < P90_MIN:
            return None
        s = sorted(errs)
        return s[min(len(s) - 1, math.ceil(0.9 * len(s)) - 1)]

    def observe(self, rec: dict) -> None:
        """One resolved, attributed shot the trigger gates could have held (not the close-threat blast, not point
        blank): the band's window, and a steady hit's trigger error."""
        if rec.get("result") not in ("hit", "miss") or _num(rec.get("dist")) is None or rec.get("character") is None:
            return
        if blasted(rec) or rec.get("pb"):
            return
        c = self._cell(self.key(rec["character"], rec.get("wid"), rec["dist"]))
        hit = rec["result"] == "hit"
        c["shots"] += 1
        c["hits"] += int(hit)
        c["recent"] = (c.get("recent", "") + ("H" if hit else "M"))[-WINDOW:]
        if hit and steady(rec):
            c["hit_err"] = (list(c.get("hit_err") or ()) + [round(math.hypot(rec["yaw_err"], rec["pitch_err"]), 2)])[-P90_KEEP:]
        self.dirty = True

    def learn(self, records) -> dict:
        """The round's steady hits per band (MIN_HITS or more): the correction moves EMA of the way to their centre
        around the nominal aim point (-mean of the nominal error: want - have), within bounds(). {key: (yaw, pitch, n)}"""
        groups: dict = {}
        for r in records or ():
            if r.get("result") != "hit" or not steady(r) or r.get("character") is None \
                    or _num(r.get("nom_yaw")) is None or _num(r.get("nom_pitch")) is None or band(r.get("dist")) is None:
                continue
            groups.setdefault(self.key(r["character"], r.get("wid"), r["dist"]), []).append(r)
        changed = {}
        for key, hits in groups.items():
            if len(hits) < MIN_HITS:
                continue
            ymax, pmax = bounds(key.rsplit(":", 1)[1])
            c = self._cell(key)
            centre_y = _clamp(-statistics.fmean(h["nom_yaw"] for h in hits), ymax)
            centre_p = _clamp(-statistics.fmean(h["nom_pitch"] for h in hits), pmax)
            c["yaw"] = round(_clamp((1 - EMA) * float(c.get("yaw") or 0.0) + EMA * centre_y, ymax), 3)
            c["pitch"] = round(_clamp((1 - EMA) * float(c.get("pitch") or 0.0) + EMA * centre_p, pmax), 3)
            c["rounds"] = int(c.get("rounds") or 0) + 1
            c["updated"] = int(time.time())
            changed[key] = (c["yaw"], c["pitch"], len(hits))
            self.dirty = True
        return changed

    def describe(self, character, wid, dist) -> str | None:
        """A short line for the live stats, or None while the band has nothing learned."""
        c = self.get(character, wid, dist)
        if not c:
            return None
        mode, rate = self.mode(character, wid, dist)
        p90 = self.p90(character, wid, dist)
        return (f"{band(dist)} m: corr {float(c.get('yaw') or 0):+.1f}/{float(c.get('pitch') or 0):+.1f} deg"
                + (f", last {len(c.get('recent') or '')} {rate:.0%} ({mode})" if rate is not None else "")
                + (f", hits' p90 {p90:.1f} deg" if p90 is not None else ""))

    def save(self) -> None:
        if not self.path or not self.dirty:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.d, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass


def main(argv=None) -> int:
    import argparse
    import glob
    ap = argparse.ArgumentParser(description="A ballistic report for a Mercenaries round map.")
    ap.add_argument("round_map")
    ap.add_argument("lessons", nargs="*", help="run lessons (.jsonl) whose shot rows fall inside the round")
    ap.add_argument("--markdown", action="store_true", help="print the Markdown section instead of the JSON")
    args = ap.parse_args(argv)
    d = json.loads(Path(args.round_map).read_text(encoding="utf-8"))
    rows = []
    for pattern in args.lessons:
        for f in sorted(glob.glob(pattern)) or [pattern]:
            for ln in Path(f).read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("kind") == "shot":
                    rows.append(row)
    rep = report_for_map(d, rows)
    print(rep["markdown"] if args.markdown else json.dumps({k: v for k, v in rep.items() if k != "markdown"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
