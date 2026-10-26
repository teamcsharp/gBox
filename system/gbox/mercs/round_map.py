"""Every Mercenaries round's route on a superimposed 2D map (operator 2026-10-24: "whenever I tell you about it running
into a wall, you should be able to look at the last round and see that Leon spent the primary majority of his time
running in the same place, and that place was indeed a wall").

A RoundTrace samples the player's ground position through one round, with the round's stuck events, and on finish writes
<out>/<stamp>-<round>.json (the samples, the time spent per map cell, the hotspots - where most of the round went and
whether that cell is a learned wall or touches one) and a matching .svg: learned floor (grey), learned walls (red), the
route (blue, fading in with time), time-spent heat (orange discs) and stuck events (black crosses). Title-agnostic: the
caller passes its learned map's cells (walked / blocked, cell size). The newest MAX_KEEP rounds per folder are kept.
The combat layer's shot records (shot()) are kept for the whole round ("shots") and become the round's ballistic report
(gbox.mercs.ballistics: "ballistics" in the JSON, ballistics/<stem>.json / .md beside it, two lines under the map).

    python -m gbox.mercs.round_map <folder>     # the newest round's hotspots
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

SAMPLE_S = 0.25           # one position sample this often
MAX_KEEP = 60             # rounds kept per folder
HOT_SHARE = 0.25          # a cell holding this share of the round is a hotspot worth naming
STILL_R, STILL_S = 120.0, 3.0   # within this radius for this long: standing still (operator 2026-10-24: "why does the bot
                                # stand still ... read this round information and be able to see the code that was being
                                # executed for these areas so that we can make corrections to the logic")
MINE_R = 250.0            # a ground mine this near a standstill: he stood on / by a bomb
STATE_KEYS = ("phase", "fire_gate", "weapon_policy", "mine_status", "mine_retreat_status", "combat", "weapon",
              "bonus_target", "route", "stuck_reason", "shots", "hits", "misses", "kills", "last_shot", "target_evidence",
              "aim_feedback", "qte_presses", "hits_taken", "combo", "enemies", "spawns", "hunt", "aim_guard", "boss",
              "last_hit_by", "death_cause", "trigger_mode", "heal_deferred",
              "player_damage_events")   # the engine's HP-loss count: hits he took, and
                          # in which decision (gbox.mercs.ballistics.turning: the hits taken while turning, gun down)
SHOTS_KEPT = 20           # the last shots of a round, each with the aim and gate the bot had when it fired (operator
                          # 2026-10-26: "see ... the aiming of the last 20 shots in a run ... how the aimbot will aim at a
                          # person then aim away and begin firing which misses")
SHOT_RECORDS_KEPT = 3000  # the combat layer's structured shot records: the whole round (the "shots" list)
BALLISTICS = "ballistics"    # <folder>/ballistics/<stem>.json / .md beside the round maps: each one's ballistic report
                             # (a subfolder: a round-map folder keeps one .json per round for whoever lists them)


class RoundTrace:
    def __init__(self, out_dir: Path | None, title: str, room: str, round_id: str, cell: float, code: dict | None = None):
        self.out_dir, self.title, self.room, self.round_id, self.cell = out_dir, title, room, round_id, float(cell)
        self.code = code or {}                  # phase -> "file:line function" that runs it (the caller's own map)
        self.samples: list[tuple] = []          # (t, x, z, y)
        self.states: list[dict] = []            # the bot's decision state at each sample (STATE_KEYS)
        self.mines: list[list] = []             # ground mine positions [x, z] at each sample
        self.events: list[dict] = []            # stuck / kill / death markers
        self.shot_records: list[dict] = []      # every resolved shot the combat layer reported (shot())
        self.shot_records_dropped = 0
        self.started = None
        self.last = -math.inf
        self.annex: dict = {}                   # extra top-level fields for the round's JSON (round_loadout, impacts ...)
        self.auditor = None                     # (summary, trace) -> the round's audit (gbox.mercs.round_audit), kept as
                                                # "audit": every round checked without anyone watching (operator 2026-10-26)

    def shot(self, record: dict) -> None:
        """A resolved shot record from the combat layer (gbox.mercs.ballistics): the round keeps them all."""
        if len(self.shot_records) < SHOT_RECORDS_KEPT:
            self.shot_records.append(dict(record))
        else:
            self.shot_records_dropped += 1

    def add(self, now: float, x: float, z: float, y: float = 0.0, state: dict | None = None, mines=()) -> None:
        if now - self.last < SAMPLE_S:
            return
        self.last = now
        self.started = self.started if self.started is not None else now
        self.samples.append((round(now, 2), round(x, 1), round(z, 1), round(y, 1)))
        self.states.append({k: str(state[k])[:120] for k in STATE_KEYS if state and state.get(k) not in (None, "")})
        self.mines.append([[round(m[0]), round(m[-1])] for m in mines][:16])

    def standstills(self) -> list[dict]:
        """Every stretch of STILL_S or more inside STILL_R: when, where, how long, what the bot was doing (its
        dominant phase / fire gate / mine status, with the code that runs that phase) and whether a mine was there."""
        out, i, n = [], 0, len(self.samples)
        while i < n:
            j = i
            while j + 1 < n and math.hypot(self.samples[j + 1][1] - self.samples[i][1],
                                           self.samples[j + 1][2] - self.samples[i][2]) <= STILL_R:
                j += 1
            secs = self.samples[j][0] - self.samples[i][0]
            if secs >= STILL_S:
                cx = sum(p[1] for p in self.samples[i:j + 1]) / (j - i + 1)
                cz = sum(p[2] for p in self.samples[i:j + 1]) / (j - i + 1)
                states = self.states[i:j + 1]

                def top(key):
                    counts = {}
                    for st in states:
                        if st.get(key):
                            counts[st[key]] = counts.get(st[key], 0) + 1
                    return max(counts, key=counts.get) if counts else None
                near = [m for row in self.mines[i:j + 1] for m in row if math.hypot(m[0] - cx, m[1] - cz) <= MINE_R]
                phase = top("phase")
                out.append({"from_s": round(self.samples[i][0] - (self.started or 0), 1), "seconds": round(secs, 1),
                            "at": [round(cx), round(cz)], "phase": phase, "fire_gate": top("fire_gate"),
                            "mine_status": top("mine_status"), "mine_retreat_status": top("mine_retreat_status"),
                            "combat": top("combat"), "on_mine": bool(near), "code": self.code.get(phase)})
            i = j + 1
        return out

    def shots(self) -> list[dict]:
        """The last SHOTS_KEPT shots: each sample where the shot count rose, with the aim (combat line: target, yaw /
        pitch error), the fire gate, what the last shot did (hit / miss and why) and the 0.5 s of aim before it."""
        out, prev = [], None
        for k, st in enumerate(self.states):
            try:
                n = int(float(st.get("shots", "")))
            except ValueError:
                continue
            if prev is not None and n > prev:
                lead = [self.states[j].get("combat") for j in range(max(0, k - 2), k)]
                out.append({"t": round(self.samples[k][0] - (self.started or 0), 2), "shots": n,
                            "at": [round(self.samples[k][1]), round(self.samples[k][2])],
                            "combat": st.get("combat"), "fire_gate": st.get("fire_gate"), "last_shot": st.get("last_shot"),
                            "hits": st.get("hits"), "misses": st.get("misses"), "weapon": st.get("weapon"),
                            "aim_before": lead})
            prev = n
        return out[-SHOTS_KEPT:]

    def time_by_phase(self) -> dict:
        out: dict[str, float] = {}
        for k, (a, b) in enumerate(zip(self.samples, self.samples[1:])):
            ph = (self.states[k] if k < len(self.states) else {}).get("phase") or "?"
            out[ph] = round(out.get(ph, 0.0) + min(b[0] - a[0], 2.0), 1)
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def event(self, now: float, kind: str, x: float, z: float, **info) -> None:
        self.events.append({"t": round(now, 2), "kind": kind, "x": round(x, 1), "z": round(z, 1), **info})

    def dwell(self) -> dict:
        """Seconds spent in each map cell (each sample holds until the next one)."""
        out: dict[tuple, float] = {}
        for (t0, x, z, _), (t1, *_r) in zip(self.samples, self.samples[1:]):
            k = (math.floor(x / self.cell), math.floor(z / self.cell))
            out[k] = out.get(k, 0.0) + min(t1 - t0, 2.0)       # a gap (a menu, a grab) never counts as time there
        return out

    def summary(self, blocked=()) -> dict:
        dwell = self.dwell()
        total = sum(dwell.values()) or 1.0
        walls = set(map(tuple, blocked))
        near = lambda k: any((k[0] + dx, k[1] + dz) in walls for dx in (-1, 0, 1) for dz in (-1, 0, 1))
        hot = sorted(dwell.items(), key=lambda kv: -kv[1])[:5]
        hotspots = [{"cell": list(k), "seconds": round(s, 1), "share": round(s / total, 3),
                     "center": [round((k[0] + .5) * self.cell), round((k[1] + .5) * self.cell)],
                     "wall": k in walls, "touches_wall": near(k)} for k, s in hot]
        moved = sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in zip(self.samples, self.samples[1:]))
        top = hotspots[0] if hotspots else None
        verdict = None
        if top and top["share"] >= HOT_SHARE:
            verdict = (f"{top['share']:.0%} of the round in one {self.cell:g}-unit cell {tuple(top['cell'])}"
                       + (" - a learned wall" if top["wall"] else " - against a learned wall" if top["touches_wall"] else ""))
        still = self.standstills()
        still_s = round(sum(x["seconds"] for x in still), 1)
        worst = max(still, key=lambda x: (x["on_mine"], x["seconds"])) if still else None
        if worst and (worst["on_mine"] or still_s >= 0.2 * total):   # standing on his own bomb outranks a hotspot
            verdict = (f"stood still {still_s:g} s ({still_s / total:.0%}) in {len(still)} stretch(es); worst "
                       f"{worst['seconds']:g} s in phase {worst['phase']}" + (" ON A MINE" if worst["on_mine"] else "")
                       + (f" ({worst['code']})" if worst.get("code") else "") + (f"; {verdict}" if verdict else ""))
        from . import ballistics
        meta = {"title": self.title, "room": self.room, "round_id": self.round_id, "seconds": round(total, 1)}
        report = ballistics.report(self.shot_records, states=self.states, samples=self.samples, started=self.started,
                                   meta=meta)
        if self.shot_records_dropped:
            report["records_dropped"] = self.shot_records_dropped
        out = {"title": self.title, "room": self.room, "round_id": self.round_id, "started": self.started,
               "seconds": round(total, 1), "samples": len(self.samples), "distance": round(moved),
               "cells_visited": len(dwell), "hotspots": hotspots, "verdict": verdict,
               "stuck_events": sum(e["kind"] == "stuck" for e in self.events),
               "hits_taken_events": sum(e["kind"] == "hit" for e in self.events),
               "standstills": still, "standing_still_s": still_s, "time_by_phase": self.time_by_phase(),
               "last_shots": self.shots(), "shots": self.shot_records, "ballistics": report, "code": self.code}
        out.update({k: v for k, v in self.annex.items() if k not in out})
        if self.auditor is not None:
            try:
                out["audit"] = self.auditor(out, self)
            except Exception as exc:              # noqa: BLE001 - a failed audit never loses the round's map
                out["audit"] = {"verdict": "unknown", "problems": [f"audit failed: {type(exc).__name__}: {exc}"[:160]]}
        return out

    def finish(self, walked=(), blocked=()) -> dict | None:
        """Write the round's JSON + SVG (when it has an out_dir and enough samples); the summary either way."""
        if len(self.samples) < 4:
            return None
        s = self.summary(blocked)
        if self.out_dir is None:
            return s
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            stem = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.started or time.time())) + "-" + self.round_id[:8]
            (self.out_dir / f"{stem}.json").write_text(json.dumps(s | {"route": self.samples, "states": self.states,
                                                                          "events": self.events}))
            (self.out_dir / f"{stem}.svg").write_text(svg(self, s, walked, blocked))
            report, reports = s["ballistics"], self.out_dir / BALLISTICS
            reports.mkdir(exist_ok=True)
            (reports / f"{stem}.json").write_text(json.dumps({k: v for k, v in report.items() if k != "markdown"},
                                                             indent=1))
            (reports / f"{stem}.md").write_text(report["markdown"] + "\n", encoding="utf-8")
            s["files"] = [str(self.out_dir / f"{stem}.json"), str(self.out_dir / f"{stem}.svg")]
            s["ballistics_files"] = [str(reports / f"{stem}.json"), str(reports / f"{stem}.md")]
            for old in rounds(self.out_dir)[:-MAX_KEEP]:
                for f in (old, old.with_suffix(".svg"), reports / old.name, reports / (old.stem + ".md")):
                    f.unlink(missing_ok=True)
        except OSError as exc:
            s["write_error"] = str(exc)[:160]
        return s


def svg(trace: RoundTrace, s: dict, walked=(), blocked=()) -> str:
    c = trace.cell
    xs = [p[1] for p in trace.samples] + [(k[0] + .5) * c for k in list(walked) + list(blocked)]
    zs = [p[2] for p in trace.samples] + [(k[1] + .5) * c for k in list(walked) + list(blocked)]
    x0, x1, z0, z1 = min(xs) - c, max(xs) + c, min(zs) - c, max(zs) + c
    scale = 900.0 / max(x1 - x0, z1 - z0, 1.0)
    W, H = (x1 - x0) * scale, (z1 - z0) * scale
    X = lambda x: (x - x0) * scale
    Z = lambda z: (z1 - z) * scale                       # +z up the page
    shots = (s.get("ballistics") or {}).get("svg_lines") or []   # the round's ballistic report, under the legend
    foot = 60 + 22 * len(shots)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + foot:.0f}" '
           f'viewBox="0 0 {W:.0f} {H + foot:.0f}" font-family="sans-serif" font-size="13">',
           f'<rect width="100%" height="100%" fill="#0e1116"/>']
    for k in walked:
        out.append(f'<rect x="{X(k[0] * c):.1f}" y="{Z((k[1] + 1) * c):.1f}" width="{c * scale:.1f}" height="{c * scale:.1f}" fill="#2a2f38"/>')
    for k in blocked:
        out.append(f'<rect x="{X(k[0] * c):.1f}" y="{Z((k[1] + 1) * c):.1f}" width="{c * scale:.1f}" height="{c * scale:.1f}" fill="#b3261e"/>')
    peak = max((h["seconds"] for h in s["hotspots"]), default=1.0) or 1.0
    for h in s["hotspots"]:
        r = 6 + 30 * h["seconds"] / peak
        out.append(f'<circle cx="{X(h["center"][0]):.1f}" cy="{Z(h["center"][1]):.1f}" r="{r:.1f}" fill="#f29900" fill-opacity="0.45"/>')
    pts = trace.samples
    for i, (a, b) in enumerate(zip(pts, pts[1:])):
        op = 0.25 + 0.75 * i / max(len(pts) - 1, 1)
        out.append(f'<line x1="{X(a[1]):.1f}" y1="{Z(a[2]):.1f}" x2="{X(b[1]):.1f}" y2="{Z(b[2]):.1f}" '
                   f'stroke="#4ea1ff" stroke-width="2" stroke-opacity="{op:.2f}"/>')
    if pts:
        out.append(f'<circle cx="{X(pts[0][1]):.1f}" cy="{Z(pts[0][2]):.1f}" r="6" fill="#3ddc84"/>')
        out.append(f'<circle cx="{X(pts[-1][1]):.1f}" cy="{Z(pts[-1][2]):.1f}" r="6" fill="#ffffff"/>')
    for st in s.get("standstills") or ():
        x, z = X(st["at"][0]), Z(st["at"][1])
        col = "#ff4d4d" if st["on_mine"] else "#ffd166"
        tag = _esc(f'{st["seconds"]:g}s {st["phase"] or "?"}' + (" on mine" if st["on_mine"] else ""))
        out.append(f'<circle cx="{x:.1f}" cy="{z:.1f}" r="{8 + min(st["seconds"], 30):.1f}" fill="none" stroke="{col}" stroke-width="2"/>')
        out.append(f'<text x="{x + 10:.1f}" y="{z - 10:.1f}" fill="{col}" font-size="11">{tag}</text>')
    for e in trace.events:
        if e["kind"] == "stuck":
            x, z = X(e["x"]), Z(e["z"])
            out.append(f'<path d="M{x - 5:.1f},{z - 5:.1f}L{x + 5:.1f},{z + 5:.1f}M{x - 5:.1f},{z + 5:.1f}L{x + 5:.1f},{z - 5:.1f}" stroke="#000" stroke-width="2.5"/>')
    label = (f'{s["title"]} {s["room"]} round {s["round_id"][:8]} - {s["seconds"]:g} s, {s["distance"]} units, '
             f'{s["cells_visited"]} cells, {s["stuck_events"]} stuck' + (f' - {s["verdict"]}' if s["verdict"] else ""))
    out.append(f'<text x="8" y="{H + 22:.0f}" fill="#e6e6e6">{_esc(label)}</text>')
    out.append(f'<text x="8" y="{H + 44:.0f}" fill="#9aa0a6">green start, white end, blue route, orange time spent, red learned wall, black stuck, yellow ring standing still (red: on a mine)</text>')
    for i, text in enumerate(shots):
        out.append(f'<text x="8" y="{H + 66 + 22 * i:.0f}" fill="#7fd1b9">{_esc(text)}</text>')
    return "".join(out) + "</svg>"


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def code_map(phases: dict, *classes) -> dict:
    """{phase: "path:line Class.method"} for {phase: "Class.method"} over the given classes (inspect)."""
    import inspect
    by_name = {c.__name__: c for c in classes}
    out = {}
    for phase, ref in phases.items():
        cls_name, _, meth = ref.partition(".")
        fn = getattr(by_name.get(cls_name), meth, None)
        try:
            path = Path(inspect.getsourcefile(fn)).name
            out[phase] = f"{path}:{inspect.getsourcelines(fn)[1]} {ref}"
        except (TypeError, OSError):
            out[phase] = ref
    return out


def rounds(folder: Path) -> list:
    """The round maps in a folder, oldest first (their ballistic reports live in the BALLISTICS subfolder)."""
    return sorted(Path(folder).glob("*.json"))


def latest(folder: Path) -> dict | None:
    files = rounds(folder)
    return json.loads(files[-1].read_text()) if files else None


if __name__ == "__main__":
    import sys
    r = latest(Path(sys.argv[1]))
    print(json.dumps({k: v for k, v in (r or {}).items() if k not in ("route", "events", "shots")}, indent=2))
