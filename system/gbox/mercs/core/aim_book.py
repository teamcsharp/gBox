"""The aim book: the truth about every shot, and the learning that closes on every miss - one for every Mercenaries
title (docs/research/universal-mercs-architecture.md, section 11).

The operator, 2026-11-10: "Every missed shot should train the bot to how they need to adjust their fire to make
corrections. The bot should learn and improve from every missed shot ... I need hooks analyzing and improving the
aimbot so it is missing shots less"; and "this is also why i wanted the aimbot universal. I want it improving and
learning across these titles so they all get better."

  Shot / Ledger  one record per trigger pull or tap: what was meant (the target, his class and body kind, the body point
                 aimed at, his distance band, the weapon family), what the gun did (the measured line of the shot - RE4's
                 laser line read from RAM, RE5's and RE6's laser - its error from the point asked for, where it crossed
                 his body), whether the line was clear, and - once its window closes - what the game says happened: his
                 health fell (a hit), reached 0 or he left the census as the kill count rose (a kill), or neither (a
                 miss, with its cause). The ledger keeps the round's measures in the stats (prefix "aimbook", apart
                 from the titles' own aim_* counters): aimbook_shots, _hits, _kills, _misses, _hit_rate, _err_deg /
                 _err_p90_deg (the line's angle from the point meant), _miss_<cause> (CAUSES), _<band>_shots / _hits,
                 _last_miss, _book (the busiest cells), _book_change (the last lesson).
  AimBook        the lessons, kept on disk in two layers (gbox-data/mercs/learned/):
                   <title id>/aim_book.json     cells (family, enemy class, band): this title's own evidence
                   _universal/aim_book.json     cells (family, body kind, band), one sub-cell per title: every title's
                                                shots, normalised - the cross-title prior
                 Each cell learns four things, all in units that mean the same in every title:
                   bias    the gun's residual yaw / pitch from where it was asked to point (radians): a windowed median,
                           misses counted twice, moved only when it stands out of its own noise (else it decays to 0),
                           a bounded step a shot, never past BIAS_MAX. The correction is minus the bias.
                   point   where on his body to aim: (u, v) - u a share of his radius across the line of sight (+ toward
                           the larger heading, the + yaw side), v a share of his knee-to-shoulder half span above his
                           chest. Hits pull it to themselves, a miss with the line on him pushes it away.
                   tol     the share of his body within which a shot on him hits (1.0: anywhere on it); a miss inside it
                           shrinks it, a hit outside it grows it. A title may hold fire outside it.
                   lead    seconds of his motion to aim ahead of a moving target: a miss with the line behind him (along
                           his motion) adds a step, one ahead of him takes one away; hits leave it.
                 Never learned from: a shot with no line of sight (los False), an unresolved one (the target lost
                 without a kill count), a shot whose line was not measured (for bias / point / tol).
  Correction     what a title applies now: each field the title cell's own value blended with the other titles'
                 sub-cells of the same (family, kind, band): value = (n_title x own + w_prior x prior) / (n_title +
                 w_prior), w_prior = PRIOR_N[field] x min(1, n_others / PRIOR_FULL_N) - a prior is worth at most
                 PRIOR_N shots of the title's own (bias 4, point 12, tol 12, lead 6), and only once the other titles
                 have PRIOR_FULL_N shots there; the title's own evidence takes over as it grows.
  AimCore        a title's hookup in three calls: tick() each tick (his census: velocities, resolutions, the learning,
                 the saves), plan() for the aim point (the body point, the lead, the angular correction), shot() at the
                 trigger (the record). Positions in the title's own units go through its combat.TitleProfile.

  Shot log       every resolved shot, one JSON line, in gbox-data/mercs/shots/<title id>/<YYYYMMDD>.jsonl (the round's
                 evidence id / number on each line): the per-round record of what was meant, what the gun did and what
                 the game answered, for the round reports and for checking the book against the truth.

Nothing here reads or writes the game or presses a key.
"""
from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime
from collections import namedtuple
from pathlib import Path

from . import combat

DATA = Path(__file__).resolve().parents[3] / "gbox-data" / "mercs" / "learned"
UNIVERSAL = "_universal"
FILE = "aim_book.json"
VERSION = 1

BANDS = ((300.0, "0-3m"), (800.0, "3-8m"), (1500.0, "8-15m"), (math.inf, "15m+"))   # ground cm -> band
BAND_NEAR = {"0-3m": 150.0, "3-8m": 300.0, "8-15m": 800.0, "15m+": 1500.0}
HIT_S = 0.45                    # a target's health falling within this of the trigger is the shot's hit
MOVER_CM_S = 80.0               # a target moving this fast across the ground is a mover (the lead)
VEL_DT = (0.02, 0.6)            # census reads this far apart give a velocity
VEL_EMA = 0.5
# the bias (radians)
BIAS_WINDOW, BIAS_MIN_N = 16, 5
BIAS_SIG = 2.5                  # the window's median must stand this many standard errors out of its noise
BIAS_ETA, BIAS_DECAY_ETA = 0.35, 0.12
BIAS_STEP = math.radians(1.0)   # at most this much a shot
BIAS_MAX = math.radians(10.0)
MISS_WEIGHT = 2                 # a miss counts this many times in the window ("every miss adjusts it")
# the body point (shares of his radius / half span)
PT_ETA_HIT, PT_ETA_MISS, PT_MISS_MIN = 0.12, 0.06, 0.15
PU_MAX, PV_MIN, PV_MAX = 0.5, -0.6, 0.9
TOL_STEP, TOL_MIN, TOL_MAX = 0.04, 0.35, 1.0
GATE_V = 0.8                    # the gate's ellipse: tol of his radius across, GATE_V x tol of his half span up / down
# the lead (seconds)
LEAD_STEP, LEAD_MAX = 0.01, 0.30
LEAD_PRIOR_S = 0.08
LEAD_BEHIND, LEAD_AHEAD = 0.3, 0.6     # the line's u along his motion: under this behind (lead more), over this ahead
# the cross-title prior
PRIOR_N = {"bias": 4.0, "point": 12.0, "tol": 12.0, "lead": 6.0}
PRIOR_FULL_N = 30.0
N_CAP = 400                     # a cell's evidence counts at most this many shots (the blend stays responsive)
RECENT_N, LOG_N = 24, 12
SAVE_S = 15.0
CAUSES = ("no_los", "off_body", "moved", "on_body", "unmeasured")
ERRS_KEPT = 400

Correction = namedtuple("Correction", "yaw pitch pu pv tol lead_s n n_prior source")
NO_CORRECTION = Correction(0.0, 0.0, 0.0, 0.0, 1.0, LEAD_PRIOR_S, 0, 0.0, "none")
Plan = namedtuple("Plan", "point point0 chest corr key ukey band kind family cls dist_cm vel")


def band(dist_cm) -> str:
    d = float(dist_cm) if isinstance(dist_cm, (int, float)) and not isinstance(dist_cm, bool) else 0.0
    return next(name for edge, name in BANDS if d < edge)


def kind_of(prof, e) -> str:
    """The body kind a class aims as in every title: its KIND_BODIES name, "big" for a measured body that stands apart
    from a man, else "human"."""
    table = getattr(prof, "bodies", None)
    cls = (e or {}).get("class") if isinstance(e, dict) else None
    got = None
    if table is not None and cls is not None:
        try:
            got = table.classes.get(cls)
        except (TypeError, AttributeError):
            got = None
    if isinstance(got, str):
        return got if got in combat.KIND_BODIES else "human"
    if isinstance(got, combat.Body):
        if got.head < combat.HUMAN.head - 2 * combat.HEAD_R_CM:
            return "crawler" if got.chest < 40.0 else "dog"
        return "big" if combat.differs(got) else "human"
    return "human"


def class_key(prof, e) -> str:
    try:
        k = prof.class_key(e) if prof is not None and callable(getattr(prof, "class_key", None)) else None
    except Exception:                                    # noqa: BLE001 - a class read never costs the shot
        k = None
    if k is None:
        k = (e or {}).get("class")
    return "?" if k is None else str(k)


# --- the geometry (cm, radians) -------------------------------------------------------------------------------------
def frame(origin, foot):
    """(the heading from origin to foot, the lateral unit (+ = the larger heading), the forward unit) on the ground."""
    h = combat.heading(foot[0] - origin[0], foot[2] - origin[2])
    return h, (math.cos(h), 0.0, -math.sin(h)), (math.sin(h), 0.0, math.cos(h))


def half_span(b) -> float:
    return max(1.0, (b.shoulder - b.knee) / 2.0)


def body_point(origin, foot, b, u: float = 0.0, v: float = 0.0, lead=(0.0, 0.0, 0.0)) -> tuple:
    """The point on a body standing at foot: his chest, u of his radius across the line of sight, v of his half span up,
    moved by lead (cm)."""
    _h, lat, _fw = frame(origin, foot)
    r, hs = b.r, half_span(b)
    return (foot[0] + u * r * lat[0] + lead[0], foot[1] + b.chest + v * hs + lead[1],
            foot[2] + u * r * lat[2] + lead[2])


def angles(origin, point) -> tuple:
    dx, dy, dz = point[0] - origin[0], point[1] - origin[1], point[2] - origin[2]
    return combat.heading(dx, dz), math.atan2(dy, max(math.hypot(dx, dz), 1e-6))


def turn_point(origin, point, dyaw: float, dpitch: float) -> tuple:
    """point turned about origin by dyaw (heading's sense) and raised by dpitch (the same distance on the ground)."""
    if not dyaw and not dpitch:
        return tuple(point)
    dx, dz = point[0] - origin[0], point[2] - origin[2]
    flat = math.hypot(dx, dz)
    if flat < 1.0:
        return tuple(point)
    h = math.atan2(dx, dz) + dyaw
    e = max(-1.4, min(1.4, math.atan2(point[1] - origin[1], flat) + dpitch))
    return (origin[0] + flat * math.sin(h), origin[1] + flat * math.tan(e), origin[2] + flat * math.cos(h))


def crossing(origin, at, foot, b) -> tuple | None:
    """(u, v) where the line origin -> at crosses the upright plane through his chest facing the shooter, in shares of his
    radius / half span (u + toward the larger heading); None when the line runs along or away from it."""
    n = math.dist(origin, at)
    if n < 1.0:
        return None
    d = tuple((at[k] - origin[k]) / n for k in range(3))
    _h, lat, fw = frame(origin, foot)
    chest = (foot[0], foot[1] + b.chest, foot[2])
    den = d[0] * fw[0] + d[2] * fw[2]
    if den < 1e-3:
        return None
    t = ((chest[0] - origin[0]) * fw[0] + (chest[2] - origin[2]) * fw[2]) / den
    if t <= 0:
        return None
    x = tuple(origin[k] + t * d[k] for k in range(3))
    u = ((x[0] - chest[0]) * lat[0] + (x[2] - chest[2]) * lat[2]) / max(b.r, 1.0)
    return u, (x[1] - chest[1]) / half_span(b)


def _median(vals) -> float:
    s = sorted(vals)
    n = len(s)
    return 0.0 if not n else s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def robust_bias(window) -> tuple:
    """(estimate, standard error, significant) of the window's centre: the median, the MAD's standard error."""
    if len(window) < BIAS_MIN_N:
        return 0.0, math.inf, False
    est = _median(window)
    mad = _median([abs(x - est) for x in window]) * 1.4826
    se = 1.2533 * mad / math.sqrt(len(window)) + 1e-5
    return est, se, abs(est) > BIAS_SIG * se


# --- a cell ---------------------------------------------------------------------------------------------------------------
def new_cell() -> dict:
    return {"n": 0, "hits": 0, "misses": 0, "recent": "", "res": [], "bias": [0.0, 0.0], "pt": [0.0, 0.0],
            "tol": TOL_MAX, "lead_s": None, "movers": 0, "updated": None, "log": []}


def _cell_ok(c) -> bool:
    return isinstance(c, dict) and isinstance(c.get("bias"), list) and len(c["bias"]) == 2 \
        and isinstance(c.get("pt"), list) and len(c["pt"]) == 2


def learn_cell(c: dict, shot: dict, now: float) -> list:
    """One resolved shot into a cell; the changes it made (for the log)."""
    changes = []
    hit = shot.get("outcome") in ("hit", "kill")
    c["n"] = min(N_CAP, c.get("n", 0) + 1)
    c["hits" if hit else "misses"] = c.get("hits" if hit else "misses", 0) + 1
    c["recent"] = (c.get("recent", "") + ("H" if hit else "M"))[-RECENT_N:]
    c["updated"] = round(now, 1)
    res = shot.get("resid")
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)   # noqa: E731
    if res is not None and len(res) == 2 and num(res[0]):
        win = c.setdefault("res", [])
        for _ in range(1 if hit else MISS_WEIGHT):     # an unread pitch (RE4's facing alone) is kept as None
            win.append([round(float(res[0]), 5), round(float(res[1]), 5) if num(res[1]) else None])
        del win[:-BIAS_WINDOW]
        for axis in (0, 1):
            vals = [w[axis] for w in win if num(w[axis])]
            if axis == 1 and not num(res[1]):
                continue                                   # this shot says nothing about the pitch
            est, _se, sig = robust_bias(vals)
            old = c["bias"][axis]
            target, eta = (est, BIAS_ETA) if sig else (0.0, BIAS_DECAY_ETA)
            new = _clip(old + _clip(eta * (target - old), -BIAS_STEP, BIAS_STEP), -BIAS_MAX, BIAS_MAX)
            c["bias"][axis] = round(new, 5)
            if abs(new - old) >= math.radians(0.05):
                changes.append(("yaw" if axis == 0 else "pitch") + f" bias {math.degrees(old):+.2f} -> "
                               f"{math.degrees(new):+.2f} deg ({'stands out' if sig else 'decays'})")
    uv = shot.get("uv")
    if uv is not None and shot.get("contact") and all(isinstance(x, (int, float)) and math.isfinite(x) for x in uv):
        pu, pv = c["pt"]
        u, v = _clip(uv[0], -1.5, 1.5), _clip(uv[1], -1.5, 1.5)
        r = math.hypot(u - pu, v - pv)
        if hit:
            pu, pv = pu + PT_ETA_HIT * (u - pu), pv + PT_ETA_HIT * (v - pv)
            if r > c.get("tol", TOL_MAX):
                c["tol"] = round(min(TOL_MAX, c.get("tol", TOL_MAX) + TOL_STEP), 3)
        else:
            if r > PT_MISS_MIN:
                pu, pv = pu - PT_ETA_MISS * (u - pu) / r * min(r, 1.0), pv - PT_ETA_MISS * (v - pv) / r * min(r, 1.0)
            if r < c.get("tol", TOL_MAX):
                c["tol"] = round(max(TOL_MIN, c.get("tol", TOL_MAX) - TOL_STEP), 3)
        new = [round(_clip(pu, -PU_MAX, PU_MAX), 4), round(_clip(pv, PV_MIN, PV_MAX), 4)]
        if max(abs(new[0] - c["pt"][0]), abs(new[1] - c["pt"][1])) >= 0.02:
            changes.append(f"point ({c['pt'][0]:+.2f}, {c['pt'][1]:+.2f}) -> ({new[0]:+.2f}, {new[1]:+.2f})")
        c["pt"] = new
    vlat = shot.get("vlat")
    if (isinstance(vlat, (int, float)) and abs(vlat) >= MOVER_CM_S and uv is not None
            and all(isinstance(x, (int, float)) and math.isfinite(x) for x in uv)):
        c["movers"] = c.get("movers", 0) + 1
        if not hit and abs(uv[1]) <= 1.5:
            lead = c["lead_s"] if isinstance(c.get("lead_s"), (int, float)) else shot.get("lead_s", LEAD_PRIOR_S)
            along = uv[0] * (1.0 if vlat > 0 else -1.0)      # the line on him at the trigger, along his motion
            new = lead + LEAD_STEP if along <= LEAD_BEHIND else lead - LEAD_STEP if along >= LEAD_AHEAD else lead
            new = round(_clip(new, 0.0, LEAD_MAX), 3)
            if new != lead:
                changes.append(f"lead {lead:.2f} -> {new:.2f} s ({'behind' if new > lead else 'ahead of'} him)")
            c["lead_s"] = new
    if changes:
        c.setdefault("log", []).append([round(now, 1), shot.get("outcome"), "; ".join(changes)[:200]])
        del c["log"][:-LOG_N]
    return changes


# --- the book -------------------------------------------------------------------------------------------------------------
def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("cells"), dict) else {}


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


class _Lock:
    """A best-effort lock file beside the universal book (several titles' bots save into it)."""

    def __init__(self, path: Path, wait_s: float = 1.0):
        self.path, self.wait_s, self.fd = Path(str(path) + ".lock"), wait_s, None

    def __enter__(self):
        end = time.monotonic() + self.wait_s
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > 10.0:      # a dead holder's lock
                        self.path.unlink()
                        continue
                except OSError:
                    pass
                if time.monotonic() >= end:
                    return self                                # write anyway: losing a lock beats losing the lessons
                time.sleep(0.02)
            except OSError:
                return self

    def __exit__(self, *exc):
        if self.fd is not None:
            try:
                os.close(self.fd)
                self.path.unlink()
            except OSError:
                pass


class AimBook:
    """The two layers for one title (see the module text). key / ukey name the cells; correction() blends them;
    learn() takes a resolved shot; save() writes the title's file and its own sub-cells of the universal one."""

    def __init__(self, title_id: str, root: Path | str | None = None, clock=time.time, lead_prior_s: float = LEAD_PRIOR_S):
        self.title_id = str(title_id)
        self.root = Path(root) if root is not None else DATA
        self.clock = clock
        self.lead_prior_s = float(lead_prior_s)
        self.path = self.root / self.title_id / FILE
        self.upath = self.root / UNIVERSAL / FILE
        self.cells: dict = {k: v for k, v in (_load(self.path).get("cells") or {}).items() if _cell_ok(v)}
        self.others: dict = {}                             # ukey -> {title: cell} of the OTHER titles (the prior)
        self.mine: dict = {}                               # ukey -> this title's universal sub-cell
        self._read_universal()
        self.dirty = False
        self.saved_at = -math.inf

    @staticmethod
    def key(family, cls, band_name) -> str:
        return f"{family or 'gun'}|{cls or '?'}|{band_name}"

    @staticmethod
    def ukey(family, kind, band_name) -> str:
        return f"{family or 'gun'}|{kind or 'human'}|{band_name}"

    def _read_universal(self) -> None:
        cells = _load(self.upath).get("cells") or {}
        others, mine = {}, {}
        for uk, per in cells.items():
            if not isinstance(per, dict):
                continue
            for title, c in per.items():
                if not _cell_ok(c):
                    continue
                if title == self.title_id:
                    mine[uk] = c
                else:
                    others.setdefault(uk, {})[title] = c
        self.others = others
        self.mine = {**mine, **self.mine}

    # --- what to apply now ---
    def _prior(self, uk: str):
        """(the other titles' sub-cells pooled: n, bias, pt, tol, lead) or None."""
        per = self.others.get(uk) or {}
        n = sum(c.get("n", 0) for c in per.values())
        if n <= 0:
            return None
        w = lambda c: c.get("n", 0) / n
        bias = [sum(w(c) * c["bias"][i] for c in per.values()) for i in (0, 1)]
        pt = [sum(w(c) * c["pt"][i] for c in per.values()) for i in (0, 1)]
        tol = sum(w(c) * c.get("tol", TOL_MAX) for c in per.values())
        leads = [(c.get("movers", 0), c["lead_s"]) for c in per.values() if isinstance(c.get("lead_s"), (int, float))]
        lm = sum(m for m, _l in leads)
        lead = sum(m * l for m, l in leads) / lm if lm > 0 else None
        return n, bias, pt, tol, lead, lm, sorted(per)

    def correction(self, family, cls, kind, band_name) -> Correction:
        c = self.cells.get(self.key(family, cls, band_name))
        pr = self._prior(self.ukey(family, kind, band_name))
        n = min(N_CAP, c.get("n", 0)) if c else 0
        if pr is None:
            if not c:
                return NO_CORRECTION._replace(lead_s=self.lead_prior_s)
            lead = c["lead_s"] if isinstance(c.get("lead_s"), (int, float)) else self.lead_prior_s
            return Correction(-c["bias"][0], -c["bias"][1], c["pt"][0], c["pt"][1], c.get("tol", TOL_MAX), lead, n,
                              0.0, "title")
        pn, pbias, ppt, ptol, plead, pmovers, titles = pr
        mature = min(1.0, pn / PRIOR_FULL_N)

        def blend(field, own, prior):
            wp = PRIOR_N[field] * mature
            if n + wp <= 0:
                return own
            return (n * own + wp * prior) / (n + wp)
        own_bias = c["bias"] if c else [0.0, 0.0]
        own_pt = c["pt"] if c else [0.0, 0.0]
        own_tol = c.get("tol", TOL_MAX) if c else TOL_MAX
        yaw, pitch = (-blend("bias", own_bias[i], pbias[i]) for i in (0, 1))
        pu, pv = (blend("point", own_pt[i], ppt[i]) for i in (0, 1))
        tol = blend("tol", own_tol, ptol)
        own_lead = c["lead_s"] if c and isinstance(c.get("lead_s"), (int, float)) else None
        movers = c.get("movers", 0) if c else 0
        if plead is not None:
            wl = PRIOR_N["lead"] * min(1.0, pmovers / PRIOR_FULL_N)
            base = own_lead if own_lead is not None else self.lead_prior_s
            lead = (movers * base + wl * plead) / (movers + wl) if movers + wl > 0 else base
        else:
            lead = own_lead if own_lead is not None else self.lead_prior_s
        return Correction(yaw, pitch, pu, pv, tol, lead, n, round(PRIOR_N["point"] * mature, 2),
                          ("title+" if c else "") + "prior:" + ",".join(titles))

    # --- learning ---
    def learn(self, shot: dict) -> list:
        """A resolved shot into the title cell and this title's universal sub-cell; [] when it teaches nothing (no line
        of sight, lost, unresolved)."""
        if shot.get("los") is False or shot.get("outcome") not in ("hit", "kill", "miss"):
            return []
        now = self.clock()
        c = self.cells.setdefault(self.key(shot.get("family"), shot.get("cls"), shot.get("band")), new_cell())
        changes = learn_cell(c, shot, now)
        u = self.mine.setdefault(self.ukey(shot.get("family"), shot.get("kind"), shot.get("band")), new_cell())
        learn_cell(u, shot, now)
        self.dirty = True
        return changes

    # --- persistence ---
    def save(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not self.dirty or (not force and now - self.saved_at < SAVE_S):
            return False
        self.saved_at = now
        try:
            _atomic_write(self.path, {"version": VERSION, "title": self.title_id, "saved": round(self.clock(), 1),
                                      "cells": self.cells})
            with _Lock(self.upath):
                data = _load(self.upath) or {"version": VERSION, "cells": {}}
                cells = data.setdefault("cells", {})
                for uk, c in self.mine.items():
                    cells.setdefault(uk, {})[self.title_id] = c
                data["saved"] = round(self.clock(), 1)
                _atomic_write(self.upath, data)
            self._read_universal()
            self.dirty = False
            return True
        except OSError:
            return False

    def summary(self, limit: int = 4) -> str:
        """The busiest cells, one line each (stats aim_book)."""
        rows = sorted(self.cells.items(), key=lambda kv: -kv[1].get("n", 0))[:limit]
        out = []
        for k, c in rows:
            hits, n = c.get("hits", 0), c.get("hits", 0) + c.get("misses", 0)
            lead = c.get("lead_s")
            out.append(f"{k}: {100 * hits // max(n, 1)} % of {n}, bias {math.degrees(c['bias'][0]):+.1f}/"
                       f"{math.degrees(c['bias'][1]):+.1f} deg, point ({c['pt'][0]:+.2f}, {c['pt'][1]:+.2f}), "
                       f"tol {c.get('tol', TOL_MAX):.2f}" + (f", lead {lead:.2f} s" if lead is not None else ""))
        return " | ".join(out)


# --- the ledger -----------------------------------------------------------------------------------------------------------
LOG_KEYS = ("target", "family", "cls", "kind", "band", "dist_cm", "los", "contact", "uv", "vlat", "lead_s", "corr",
            "outcome", "cause", "hits", "hp_delta", "hp0", "cam", "gun", "source")


def shot_row(s: dict, title_id: str, round_key=None) -> dict:
    """A resolved shot as its log line: wall time, the round, the errors in degrees, the rest as recorded."""
    row = {"ts": round(time.time(), 2), "title": title_id, "round": round_key}
    for k in LOG_KEYS:
        v = s.get(k)
        if v is None:
            continue
        if isinstance(v, float):
            v = round(v, 3)
        elif isinstance(v, (tuple, list)):
            v = [round(x, 4) if isinstance(x, float) else x for x in v]
        row[k] = v
    for k in ("err", "resid"):
        if s.get(k) is not None:
            row[k + "_deg"] = [None if x is None else round(math.degrees(x), 2) for x in s[k]]
    return row


LOG_FLUSH_N, LOG_FLUSH_S = 32, 10.0


class ShotLog:
    """The per-round shot lines (see the module text): kept as each shot resolves and appended LOG_FLUSH_N at a time or
    every LOG_FLUSH_S (and at save), a file a day per title."""

    def __init__(self, title_id: str, root: Path | str | None = None):
        self.title_id = str(title_id)
        self.root = Path(root) if root is not None else None
        self.errors = 0
        self.rows: list = []
        self.flushed_at = time.monotonic()

    def path(self) -> Path:
        base = self.root if self.root is not None else DATA.parent / "shots"
        return base / self.title_id / f"{datetime.now():%Y%m%d}.jsonl"

    def write(self, s: dict, round_key=None) -> None:
        try:
            self.rows.append(json.dumps(shot_row(s, self.title_id, round_key), separators=(",", ":")))
        except (TypeError, ValueError):
            self.errors += 1
            return
        if len(self.rows) >= LOG_FLUSH_N or time.monotonic() - self.flushed_at >= LOG_FLUSH_S:
            self.flush()

    def flush(self) -> None:
        self.flushed_at = time.monotonic()
        if not self.rows:
            return
        rows, self.rows = self.rows, []
        try:
            p = self.path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
        except OSError:
            self.errors += 1


class Ledger:
    """The open shots, resolved by the census: a target's health falling within window_s of a shot is its hit (each fall
    goes to the latest open shot on him), reaching 0 - or leaving the census as the game's kill count rises - its kill;
    neither, a miss with its cause. Stats under prefix (see the module text); each resolved shot to log (a ShotLog)."""

    def __init__(self, stats: dict | None = None, prefix: str = "aimbook", window_s: float = HIT_S, book: AimBook | None = None,
                 log: ShotLog | None = None):
        self.stats = stats if stats is not None else {}
        self.prefix = prefix
        self.window_s = float(window_s)
        self.book = book
        self.log = log
        self.open: list = []
        self.hp: dict = {}
        self.kills = None
        self.kill_at = []                                   # (when, how many) of the game's kill count rises
        self._errs: list = []
        for k in ("shots", "hits", "kills", "misses", "lost", "learned") + tuple("miss_" + c for c in CAUSES):
            self.stats.setdefault(f"{prefix}_{k}", 0)

    def _s(self, k, v=1):
        name = f"{self.prefix}_{k}"
        self.stats[name] = self.stats.get(name, 0) + v

    def fired(self, shot: dict) -> dict:
        shot.setdefault("hits", 0)
        shot.setdefault("hp_delta", 0)
        shot["outcome"] = None
        self.open.append(shot)
        del self.open[:-64]
        self._s("shots")
        b = shot.get("band")
        if b:
            self._s(f"{b}_shots")
        err = shot.get("err")
        if err is not None:
            d = math.degrees(math.hypot(err[0], err[1] if err[1] is not None else 0.0))
            if d < 90.0:
                self._errs = (self._errs + [d])[-ERRS_KEPT:]
                self.stats[f"{self.prefix}_err_deg"] = round(sum(self._errs) / len(self._errs), 2)
                self.stats[f"{self.prefix}_err_p90_deg"] = round(sorted(self._errs)[int(0.9 * (len(self._errs) - 1))], 2)
        return shot

    def observe(self, now: float, enemies, kills=None, key=None) -> list:
        """This tick's census ([{ptr / slot, hp, pos}]) and the game's kill count: falls given to the open shots, the
        shots whose window closed resolved (and learned). -> the shots resolved now."""
        key = key or (lambda e: e.get("ptr", e.get("slot")))
        hp = {}
        for e in enemies or ():
            k = key(e)
            if k is not None:
                hp[k] = e.get("hp") or 0
        if isinstance(kills, int) and not isinstance(kills, bool):
            if self.kills is not None and kills > self.kills:
                self.kill_at.append((now, kills - self.kills))
                del self.kill_at[:-16]
            self.kills = kills
        for k, was in self.hp.items():
            h = hp.get(k)
            if h is None or h >= was or was <= 0:
                continue
            shot = next((s for s in reversed(self.open) if s.get("target") == k and s["t"] <= now
                         and now - s["t"] <= self.window_s), None)
            if shot is not None:
                shot["hits"] += 1
                shot["hp_delta"] -= was - h
                if h <= 0:
                    shot["killed"] = True
        for s in self.open:                              # left the census inside the window while the kills rose
            k = s.get("target")
            if k is not None and k in self.hp and k not in hp and self.hp.get(k, 0) > 0 and s.get("left") is None:
                s["left"] = now
        self.hp = hp
        done = [s for s in self.open if now - s["t"] > self.window_s]
        self.open = [s for s in self.open if now - s["t"] <= self.window_s]
        for s in done:
            self._resolve(s, now)
        return done

    def _resolve(self, s: dict, now: float) -> None:
        rose = any(s["t"] <= t <= s["t"] + self.window_s + 0.2 for t, _n in self.kill_at)
        if s.get("killed") or (s.get("left") is not None and rose):
            s["outcome"] = "kill"
        elif s["hits"]:
            s["outcome"] = "hit"
        elif s.get("left") is not None:
            s["outcome"] = "lost"                          # gone with no kill count to say how: neither hit nor miss
        else:
            s["outcome"] = "miss"
            s["cause"] = ("no_los" if s.get("los") is False else "off_body" if s.get("contact") is False else
                          "moved" if s.get("contact") and abs(s.get("vlat") or 0.0) >= MOVER_CM_S else
                          "on_body" if s.get("contact") else "unmeasured")
        s["resolved_at"] = now
        out = s["outcome"]
        if self.log is not None:
            self.log.write(s, self.stats.get("round_evidence_id") or self.stats.get("rounds"))
        if out == "lost":
            self._s("lost")
            return
        if out in ("hit", "kill"):
            self._s("hits")
            if out == "kill":
                self._s("kills")
            if s.get("band"):
                self._s(f"{s['band']}_hits")
        else:
            self._s("misses")
            self._s("miss_" + s["cause"])
            self.stats[f"{self.prefix}_last_miss"] = (
                f"{s.get('family') or 'gun'} at {s.get('cls')} {(s.get('dist_cm') or 0) / 100:.1f} m: {s['cause']}"
                + (f", the line {math.degrees(s['err'][0]):+.1f}/{math.degrees(s['err'][1] or 0.0):+.1f} deg off"
                   if s.get("err") is not None else ""))[:160]
        judged = self.stats[f"{self.prefix}_hits"] + self.stats[f"{self.prefix}_misses"]
        self.stats[f"{self.prefix}_hit_rate"] = round(self.stats[f"{self.prefix}_hits"] / max(judged, 1), 3)
        if self.book is not None:
            ch = self.book.learn(s)
            if s.get("los") is not False:
                self._s("learned")
            if ch:
                self.stats[f"{self.prefix}_book_change"] = f"{s.get('family') or 'gun'}|{s.get('cls')}|{s.get('band')}: " \
                                                           + "; ".join(ch)[:200]


# --- a title's hookup -----------------------------------------------------------------------------------------------------
class AimCore:
    """One title's aim book and ledger (see the module text). prof: its combat.TitleProfile (units, bodies, class key);
    positions handed in are in the title's units, everything kept is in cm."""

    def __init__(self, prof, stats: dict | None = None, root=None, prefix: str = "aimbook", window_s: float = HIT_S,
                 lead_prior_s: float = LEAD_PRIOR_S, apply: bool = True, clock=time.time, log: bool = True):
        self.prof = prof
        self.stats = stats if stats is not None else {}
        self.apply = bool(apply)
        self.book = AimBook(prof.title_id or prof.title, root, clock=clock, lead_prior_s=lead_prior_s)
        self.log = ShotLog(prof.title_id or prof.title, None if root is None else Path(root) / "_shots") if log else None
        self.ledger = Ledger(self.stats, prefix, window_s, self.book, self.log)
        self.prefix = prefix
        self._seen: dict = {}                              # target key -> (when, pos cm, velocity cm/s)
        self._summary_at = -math.inf

    @staticmethod
    def target_key(e):
        return (e or {}).get("ptr", (e or {}).get("slot"))

    def velocity(self, e) -> tuple:
        got = self._seen.get(self.target_key(e))
        return got[2] if got else (0.0, 0.0, 0.0)

    def tick(self, now: float, enemies, kills=None) -> list:
        """The census this tick: velocities (cm/s) per target, the ledger's resolutions (each one learned), the book saved
        at most every SAVE_S. A fault never reaches the caller (stats <prefix>_error)."""
        try:
            seen = {}
            for e in enemies or ():
                k = self.target_key(e)
                if k is None or not e.get("pos") or (e.get("hp") or 0) <= 0:
                    continue
                pos = self.prof.pos_cm(e["pos"])
                last = self._seen.get(k)
                vel = last[2] if last else (0.0, 0.0, 0.0)
                if last is not None and VEL_DT[0] <= now - last[0] <= VEL_DT[1]:
                    dt = now - last[0]
                    raw = tuple((pos[i] - last[1][i]) / dt for i in range(3))
                    vel = tuple(VEL_EMA * raw[i] + (1 - VEL_EMA) * vel[i] for i in range(3))
                    seen[k] = (now, pos, vel)
                elif last is not None and now - last[0] < VEL_DT[0]:
                    seen[k] = last
                else:
                    seen[k] = (now, pos, vel if last is not None and now - last[0] <= 1.0 else (0.0, 0.0, 0.0))
            self._seen = seen
            done = self.ledger.observe(now, enemies, kills, self.target_key)
            if done:
                self.book.save()
            if self.log is not None and self.log.rows and time.monotonic() - self.log.flushed_at >= LOG_FLUSH_S:
                self.log.flush()
            if now - self._summary_at >= 5.0:
                self._summary_at = now
                self.stats[f"{self.prefix}_book"] = self.book.summary()
                self.stats[f"{self.prefix}_book_cells"] = len(self.book.cells)
            return done
        except Exception as exc:                          # noqa: BLE001 - the book never costs a tick
            self.stats[f"{self.prefix}_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return []

    def plan(self, e, origin, family=None, now: float | None = None, body=None, extra=(0.0, 0.0, 0.0)) -> Plan | None:
        """The aim at e from origin (the title's units): point0 the body point meant (his chest moved by the book's body
        point and his lead), point the one to steer the gun onto (point0 turned by the book's angular correction),
        chest his plain chest; all in the title's units. extra: an offset (cm) added to point0 (the fire pattern's
        scatter). None for a target with no position."""
        try:
            if not e or not e.get("pos") or origin is None:
                return None
            prof = self.prof
            o, foot = prof.pos_cm(origin), prof.pos_cm(e["pos"])
            b = body if body is not None else prof.body(e)
            dist = math.hypot(foot[0] - o[0], foot[2] - o[2])
            bn, kind, cls = band(dist), kind_of(prof, e), class_key(prof, e)
            corr = self.book.correction(family, cls, kind, bn) if self.apply else NO_CORRECTION
            vel = self.velocity(e)
            lead = tuple(v * corr.lead_s for v in (vel[0], 0.0, vel[2])) if self.apply else (0.0, 0.0, 0.0)
            p0 = body_point(o, foot, b, corr.pu, corr.pv, lead)
            p0 = tuple(p0[i] + float(extra[i]) for i in range(3))
            p1 = turn_point(o, p0, corr.yaw, corr.pitch)
            chest = (foot[0], foot[1] + b.chest, foot[2])
            k = prof.units_per_cm
            back = lambda q: tuple(v * k for v in q)
            return Plan(back(p1), back(p0), back(chest), corr, self.book.key(family, cls, bn),
                        self.book.ukey(family, kind, bn), bn, kind, family, cls, dist, vel)
        except Exception as exc:                          # noqa: BLE001
            self.stats[f"{self.prefix}_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return None

    def shot(self, now: float, e, plan: Plan | None, origin=None, at=None, contact=None, los=None, actual=None,
             family=None, body=None, extra: dict | None = None) -> dict | None:
        """A trigger pull / tap at e under plan: origin -> at the measured line of the shot (the title's units), or
        actual = (yaw, pitch) radians where only angles are read (RE4's facing); contact: the title's own "the line is
        on him" (None: computed from the line); los: the title's line-of-sight verdict (False: never learned from)."""
        try:
            if plan is None or not e:
                return None
            prof = self.prof
            k = prof.units_per_cm
            b = body if body is not None else prof.body(e)
            foot = prof.pos_cm(e["pos"])
            o = prof.pos_cm(origin) if origin is not None else None
            a = prof.pos_cm(at) if at is not None else None
            p0 = tuple(v / k for v in plan.point0)
            p1 = tuple(v / k for v in plan.point)
            err = resid = uv = None
            if o is not None and a is not None and math.dist(o, a) >= 1.0:
                ay, ap = angles(o, a)
                iy, ip = angles(o, p0)
                cy, cp = angles(o, p1)
                err = (combat.wrap(ay - iy), ap - ip)
                resid = (combat.wrap(ay - cy), ap - cp)
                uv = crossing(o, a, foot, b)
                if contact is None:
                    contact = combat.segment_hits(o, a, foot, b)
            elif actual is not None and o is not None:
                iy, ip = angles(o, p0)
                cy, cp = angles(o, p1)
                ay = actual[0]
                ap = actual[1] if len(actual) > 1 and actual[1] is not None else None
                err = (combat.wrap(ay - iy), (ap - ip) if ap is not None else None)
                resid = (combat.wrap(ay - cy), (ap - cp) if ap is not None else None)
            vel = plan.vel or (0.0, 0.0, 0.0)
            ref = o if o is not None else foot
            _h, lat, _fw = frame(ref, foot)
            vlat = vel[0] * lat[0] + vel[2] * lat[2]
            s = {"t": now, "target": self.target_key(e), "family": family, "cls": plan.cls, "kind": plan.kind,
                 "band": plan.band, "dist_cm": round(plan.dist_cm, 1), "los": los,
                 "contact": None if contact is None else bool(contact), "err": err, "resid": resid, "uv": uv,
                 "vlat": round(vlat, 1), "lead_s": plan.corr.lead_s, "hp0": e.get("hp"),
                 "corr": (round(plan.corr.yaw, 5), round(plan.corr.pitch, 5), round(plan.corr.pu, 3),
                          round(plan.corr.pv, 3)),
                 "source": "line" if a is not None else "angles" if actual is not None else "none"}
            if extra:
                s.update(extra)
            self.ledger.fired(s)
            return s
        except Exception as exc:                          # noqa: BLE001
            self.stats[f"{self.prefix}_error"] = f"{type(exc).__name__}: {exc}"[:160]
            return None

    def contact_ok(self, plan: Plan | None, origin, at, e, body=None) -> bool | None:
        """Whether the measured line crosses him inside the book's tolerance ellipse round its point: tol of his radius
        across, GATE_V x tol of his half span up and down - his torso while tol is 1 (None: not measured)."""
        if plan is None or origin is None or at is None or not e:
            return None
        prof = self.prof
        b = body if body is not None else prof.body(e)
        uv = crossing(prof.pos_cm(origin), prof.pos_cm(at), prof.pos_cm(e["pos"]), b)
        if uv is None:
            return None
        tol = max(plan.corr.tol, TOL_MIN)
        return ((uv[0] - plan.corr.pu) / tol) ** 2 + ((uv[1] - plan.corr.pv) / (GATE_V * tol)) ** 2 <= 1.0

    def save(self, force: bool = True) -> bool:
        if self.log is not None:
            self.log.flush()
        return self.book.save(force=force)
