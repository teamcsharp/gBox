"""Every Mercenaries round's route on a superimposed 2D map (operator 2026-10-24: "whenever I tell you about it running
into a wall, you should be able to look at the last round and see that Leon spent the primary majority of his time
running in the same place, and that place was indeed a wall").

A RoundTrace samples the player's ground position through one round, with the round's stuck events, and on finish writes
<out>/<stamp>-<round>.json (the samples, the time spent per map cell, the hotspots - where most of the round went and
whether that cell is a learned wall or touches one) and a matching .svg: learned floor (grey), learned walls (red), the
route (blue, fading in with time), time-spent heat (orange discs) and stuck events (black crosses). Title-agnostic: the
caller passes its learned map's cells (walked / blocked, cell size). The newest MAX_KEEP rounds per folder are kept.

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


class RoundTrace:
    def __init__(self, out_dir: Path | None, title: str, room: str, round_id: str, cell: float):
        self.out_dir, self.title, self.room, self.round_id, self.cell = out_dir, title, room, round_id, float(cell)
        self.samples: list[tuple] = []          # (t, x, z, y)
        self.events: list[dict] = []            # stuck / kill / death markers
        self.started = None
        self.last = -math.inf

    def add(self, now: float, x: float, z: float, y: float = 0.0) -> None:
        if now - self.last < SAMPLE_S:
            return
        self.last = now
        self.started = self.started if self.started is not None else now
        self.samples.append((round(now, 2), round(x, 1), round(z, 1), round(y, 1)))

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
        return {"title": self.title, "room": self.room, "round_id": self.round_id, "started": self.started,
                "seconds": round(total, 1), "samples": len(self.samples), "distance": round(moved),
                "cells_visited": len(dwell), "hotspots": hotspots, "verdict": verdict,
                "stuck_events": sum(e["kind"] == "stuck" for e in self.events)}

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
            (self.out_dir / f"{stem}.json").write_text(json.dumps(s | {"route": self.samples, "events": self.events}))
            (self.out_dir / f"{stem}.svg").write_text(svg(self, s, walked, blocked))
            s["files"] = [str(self.out_dir / f"{stem}.json"), str(self.out_dir / f"{stem}.svg")]
            for old in sorted(self.out_dir.glob("*.json"))[:-MAX_KEEP]:
                old.unlink(missing_ok=True)
                old.with_suffix(".svg").unlink(missing_ok=True)
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
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H + 60:.0f}" '
           f'viewBox="0 0 {W:.0f} {H + 60:.0f}" font-family="sans-serif" font-size="13">',
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
    for e in trace.events:
        if e["kind"] == "stuck":
            x, z = X(e["x"]), Z(e["z"])
            out.append(f'<path d="M{x - 5:.1f},{z - 5:.1f}L{x + 5:.1f},{z + 5:.1f}M{x - 5:.1f},{z + 5:.1f}L{x + 5:.1f},{z - 5:.1f}" stroke="#000" stroke-width="2.5"/>')
    label = (f'{s["title"]} {s["room"]} round {s["round_id"][:8]} - {s["seconds"]:g} s, {s["distance"]} units, '
             f'{s["cells_visited"]} cells, {s["stuck_events"]} stuck' + (f' - {s["verdict"]}' if s["verdict"] else ""))
    out.append(f'<text x="8" y="{H + 22:.0f}" fill="#e6e6e6">{_esc(label)}</text>')
    out.append(f'<text x="8" y="{H + 44:.0f}" fill="#9aa0a6">green start, white end, blue route, orange time spent, red learned wall, black stuck</text>')
    return "".join(out) + "</svg>"


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def latest(folder: Path) -> dict | None:
    files = sorted(Path(folder).glob("*.json"))
    return json.loads(files[-1].read_text()) if files else None


if __name__ == "__main__":
    import sys
    r = latest(Path(sys.argv[1]))
    print(json.dumps({k: v for k, v in (r or {}).items() if k not in ("route", "events")}, indent=2))
