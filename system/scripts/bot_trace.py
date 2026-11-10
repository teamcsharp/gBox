"""Record and draw a live Mercenaries bot's path, decisions and controls (RE4 / RE5 Switch; any title whose tactical
frame the bot publishes).

    python scripts/bot_trace.py record <session id> <seconds> <out.jsonl>
        poll the session's tactical frame and telemetry every 0.2 s (read only, actor "agent"); one row per poll
    python scripts/bot_trace.py draw <in.jsonl> <out.png> [room.json]
        the path over the room's collision walls (gbox/data/re4_switch_room_map/r4xx.json, re5_switch_room_map/s40N.json;
        found from the frame's stage key when not given) coloured by phase, his facing, the planned routes, the enemies,
        a phase timeline, and the controls strip under it: one row per key held (the left stick, B, ZL ...), a tick for
        each tap (ZR, Y, A ...); prints the time per phase, the distance walked and the top reasons

The API token comes from gbox-data/api_token (or GBOX_TOKEN) and is never printed; GBOX_SERVER overrides the server.
The controls are the frame's plan.keys / plan.tap / plan.stick (gbox.mercs.tactical.controls), published by the bot.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

SYSTEM = Path(__file__).resolve().parent.parent
SERVER = os.environ.get("GBOX_SERVER", "http://10.89.1.246:8765")
TEL_KEYS = ("doing", "why", "shots", "hits", "kills", "kills_seen", "room_map", "room_map_steps_refused",
            "room_map_route_legs", "room_map_route_turns", "walls_pressed", "unwalls", "stand_breaks", "flanks",
            "flank_los_opens", "flank_los_goals", "pack_keeps", "camera_dist_mm", "camera_collapses",
            "room_map_refused_last", "mesh_crossings_refused", "mesh_shortcuts", "mesh_avoid_forgiven",
            "mesh_stall_foe_skips", "mesh_no_route", "nav_status", "walk_how", "screen")
PHASE_COLOURS = {"fire": (230, 60, 60), "aim": (240, 140, 40), "turn": (250, 190, 90), "flank": (60, 120, 240),
                 "locate": (40, 170, 200), "walk": (60, 200, 120), "step": (120, 200, 60), "unwall": (200, 60, 200),
                 "escape": (250, 220, 40), "evade": (250, 220, 40), "retreat": (250, 220, 40), "melee": (255, 0, 120),
                 "sweep": (150, 150, 220), "dead": (90, 90, 90), "frozen": (140, 140, 140)}
KEY_ROWS = ("lup", "ldown", "lleft", "lright", "b", "zl", "rleft", "rright", "rup", "rdown")
TAP_KEYS = ("zr", "y", "a", "l", "r", "x")
ROOM_TRIS = {}                          # the RE4 stage meshes' triangle counts -> their room (the frame's stage key)


def token() -> str:
    if os.environ.get("GBOX_TOKEN"):
        return os.environ["GBOX_TOKEN"]
    for p in (SYSTEM / "gbox-data" / "api_token", Path("//10.89.1.246/ehm_eckx/gBox/system/gbox-data/api_token")):
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    raise SystemExit("no API token (gbox-data/api_token or GBOX_TOKEN)")


def get(path: str, tok: str, timeout: float = 5.0):
    req = urllib.request.Request(SERVER + path, headers={"Authorization": "Bearer " + tok, "x-gbox-actor": "agent"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"null")


def record(sid: str, seconds: float, out: str) -> int:
    tok = token()
    end, n = time.time() + seconds, 0
    with open(out, "w", encoding="utf-8") as fh:
        while time.time() < end:
            t = time.time()
            try:
                f = get(f"/api/autoplay/tactical/{sid}", tok) or {}
                s = (get(f"/api/autoplay/telemetry/{sid}", tok) or {}).get("stats") or {}
            except Exception as exc:                         # noqa: BLE001 - a missed poll is a row with the error
                f, s = {"error": str(exc)[:200]}, {}
            p = f.get("player") or {}
            pl = f.get("plan") or {}
            row = {"t": round(t, 2), "pos": p.get("pos"), "facing": p.get("facing"), "hp": p.get("hp"),
                   "plan": pl, "stage": f.get("stage"), "error": f.get("error"),
                   "keys": pl.get("keys"), "tap": pl.get("tap"), "stick": pl.get("stick"),
                   "enemies": [{"pos": e.get("pos"), "hp": e.get("hp"), "name": e.get("name") or e.get("kind")}
                               for e in (f.get("enemies") or []) if e.get("pos")][:40],
                   "tel": {k: s.get(k) for k in TEL_KEYS}}
            fh.write(json.dumps(row) + "\n")
            n += 1
            time.sleep(max(0.0, 0.2 - (time.time() - t)))
    print(f"recorded {n} rows -> {out}")
    return n


def room_for(stage: str | None) -> Path | None:
    """The room map table for a tactical stage key (<title>.nav<triangles>.<hash>), or None."""
    if not stage or ".nav" not in stage:
        return None
    title = stage.split(".")[0]
    try:
        tris = int(stage.split(".nav")[1].split(".")[0])
    except (IndexError, ValueError):
        return None
    data = SYSTEM / "gbox" / "data"
    if title == "010099A00BC1E000":
        for f in sorted((data / "re4_switch_nav").glob("r4*.json")):
            try:
                if json.loads(f.read_text(encoding="utf-8"))["counts"]["tris"] == tris:
                    return data / "re4_switch_room_map" / f.name
            except (OSError, ValueError, KeyError):
                continue
    if title == "010018100CD46000":
        sys.path.insert(0, str(SYSTEM))
        from gbox.mercs import ss_ledger
        from gbox.mercs.titles import re5_room_map
        name = next((n for s, n in ss_ledger.SIGNATURES.items() if s.split("-")[1] == str(tris)), None)
        arch = re5_room_map.STAGE_ARCHIVE.get(name)
        return re5_room_map.path_of(arch) if arch else None
    return None


def _phase(r) -> str | None:
    return (r.get("plan") or {}).get("phase") or (r.get("tel") or {}).get("doing")


def colour(phase) -> tuple:
    for k, c in PHASE_COLOURS.items():
        if phase and k in phase:
            return c
    return (120, 120, 120)


def _keys(r) -> tuple:
    """(keys held, key tapped) of a row: the row's own, else the frame's plan.keys / plan.tap, else a bot's raw
    plan.controls (a replay's)."""
    pl = r.get("plan") or {}
    ctl = pl.get("controls") if isinstance(pl.get("controls"), dict) else {}
    keys = next((v for v in (r.get("keys"), pl.get("keys"), ctl.get("keys")) if v is not None), ())
    tap = next((v for v in (r.get("tap"), pl.get("tap"), ctl.get("tap")) if v), None)
    return set(keys or ()), tap


def draw(src: str, out: str, room: str | None = None) -> dict:
    from PIL import Image, ImageDraw
    rows = [json.loads(line) for line in open(src, encoding="utf-8") if line.strip()]
    rows = [r for r in rows if r.get("pos")]
    if not rows:
        raise SystemExit("no positions recorded")
    units = 10.0 if (rows[0].get("stage") or "").startswith("010018100CD46000") else 1.0   # RE5: cm -> mm
    P3 = [(r["pos"][0] * units, r["pos"][1] * units, r["pos"][2] * units) for r in rows]
    y0, pad = P3[0][1], 4000.0
    x_lo, x_hi = min(p[0] for p in P3) - pad, max(p[0] for p in P3) + pad
    z_lo, z_hi = min(p[2] for p in P3) - pad, max(p[2] for p in P3) + pad
    W = H = 1100
    TL, KR = 60, 14                                          # the phase timeline, one controls row's height
    strip = TL + KR * (len(KEY_ROWS) + 1) + 90
    sc = min(W / (x_hi - x_lo), H / (z_hi - z_lo))

    def P(x, z):
        return (x - x_lo) * sc, (z - z_lo) * sc
    img = Image.new("RGB", (W, H + strip), (250, 250, 250))
    full = ImageDraw.Draw(img)
    panel = Image.new("RGB", (W, H), (250, 250, 250))         # the map, clipped to its own panel
    g = ImageDraw.Draw(panel)
    room = room or room_for(rows[0].get("stage"))
    walls = 0
    if room and Path(room).exists():
        for x0, z0, x1, z1, ylo, yhi, flag in json.loads(Path(room).read_text(encoding="utf-8"))["walls"]:
            if ylo <= y0 + 1700 and yhi >= y0 + 300:          # a wall at his body's height
                g.line([P(x0, z0), P(x1, z1)], fill=(170, 170, 255) if flag else (40, 40, 40), width=3)
                walls += 1
    for r in rows[::10]:                                       # the planned routes (thin), every 10th row
        rt = (r.get("plan") or {}).get("route") or []
        pts = [P(p[0] * units, p[2] * units) for p in [r["pos"]] + rt]
        if len(pts) > 1:
            g.line(pts, fill=(160, 200, 255), width=1)
    for e in rows[-1].get("enemies") or []:
        ex, ez = P(e["pos"][0] * units, e["pos"][2] * units)
        g.ellipse([ex - 4, ez - 4, ex + 4, ez + 4], outline=(200, 0, 0))
    for (a, b), r in zip(zip(P3, P3[1:]), rows):
        g.line([P(a[0], a[2]), P(b[0], b[2])], fill=colour(_phase(r)), width=3)
    for r, p in list(zip(rows, P3))[::5]:
        f = r.get("facing")
        if isinstance(f, (int, float)):
            fx, fz = P(p[0], p[2])
            g.line([(fx, fz), (fx + 14 * math.sin(f), fz + 14 * math.cos(f))], fill=(0, 0, 0), width=1)
    for p, c in ((P3[0], (0, 150, 0)), (P3[-1], (200, 0, 0))):
        x, z = P(p[0], p[2])
        g.rectangle([x - 5, z - 5, x + 5, z + 5], outline=c, width=2)
    img.paste(panel, (0, 0))
    g = full
    g.line([(0, H), (W, H)], fill=(120, 120, 120), width=1)
    t0, t1 = rows[0]["t"], rows[-1]["t"]
    span = max(1e-6, t1 - t0)
    X = lambda t: (t - t0) / span * (W - 60) + 60               # noqa: E731 - the timeline's x (labels on the left)
    for a, b in zip(rows, rows[1:]):
        g.rectangle([X(a["t"]), H + 10, X(b["t"]), H + 10 + TL - 20], fill=colour(_phase(a)))
    g.text((4, H + 20), "phase", fill=(0, 0, 0))
    top = H + TL
    for i, k in enumerate(KEY_ROWS):                            # the controls strip: a row per key held
        y = top + i * KR
        g.text((4, y), k, fill=(0, 0, 0))
        for a, b in zip(rows, rows[1:]):
            if k in _keys(a)[0]:
                g.rectangle([X(a["t"]), y + 2, X(b["t"]), y + KR - 2], fill=(50, 50, 50))
    y = top + len(KEY_ROWS) * KR
    g.text((4, y), "taps", fill=(0, 0, 0))
    tap_colours = {"zr": (220, 0, 0), "y": (0, 140, 0), "a": (0, 0, 200)}
    for r in rows:
        tap = _keys(r)[1]
        if tap:
            g.line([(X(r["t"]), y + 1), (X(r["t"]), y + KR - 1)], fill=tap_colours.get(tap, (120, 0, 160)), width=2)
    last = rows[-1].get("tel") or {}
    info = (f"{len(rows)} samples, {span:.0f} s, stage {rows[0].get('stage')}, walls drawn {walls} (green box start, red "
            f"box end)")
    counts = (f"refused {last.get('room_map_steps_refused')} route legs {last.get('room_map_route_legs')} walls_pressed "
              f"{last.get('walls_pressed')} stand_breaks {last.get('stand_breaks')} flanks {last.get('flanks')} "
              f"shots {last.get('shots')} hits {last.get('hits')} kills {last.get('kills', last.get('kills_seen'))} "
              f"shortcuts {last.get('mesh_shortcuts')} forgiven {last.get('mesh_avoid_forgiven')}")
    g.text((10, y + KR + 8), info, fill=(0, 0, 0))
    g.text((10, y + KR + 26), counts, fill=(0, 0, 0))
    g.text((10, y + KR + 44), "phases: " + "  ".join(PHASE_COLOURS), fill=(0, 0, 0))
    img.save(out)
    per = Counter()
    for a, b in zip(rows, rows[1:]):
        per[_phase(a)] += b["t"] - a["t"]
    dist = sum(math.hypot(b[0] - a[0], b[2] - a[2]) for a, b in zip(P3, P3[1:]))
    net = math.hypot(P3[-1][0] - P3[0][0], P3[-1][2] - P3[0][2])
    summary = {"seconds": round(span, 1), "time_per_phase_s": {k: round(v, 1) for k, v in per.most_common()},
               "walked_m": round(dist / 1000, 1), "net_m": round(net / 1000, 1), "walls_drawn": walls,
               "top_reasons": Counter(str((r.get("tel") or {}).get("why"))[:70] for r in rows).most_common(6)}
    print(json.dumps(summary, indent=1))
    return summary


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 4 and argv[0] == "record":
        record(argv[1], float(argv[2]), argv[3])
        return 0
    if len(argv) >= 3 and argv[0] == "draw":
        draw(argv[1], argv[2], argv[3] if len(argv) > 3 else None)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
