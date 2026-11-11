"""Record the operator's own route through the game, then turn it into a mission the bot can walk.

    python pso_route.py record --session <sid> --seconds 600
    python pso_route.py convert --file D:\\gBox\\pso-ds\\routes\\route-*.json

`record` samples the player's world position (`pso_ram`: actor + 0x38/0x3C/0x40 from the player slot table) and the operator's pad
together at 8 Hz. `convert` simplifies the path to waypoints (Douglas-Peucker, in world units) and writes an autoplay mission whose
steps are `navigate {to: [x, z]}` - the bot walking the same route the operator walked, which is what "the way I am playing" means
for moving through a city.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp\imitate-wt\system")
sys.path.insert(0, r"C:\_tools\gBox\.tmp\tools")

from gbox import pso_ram                                          # noqa: E402
from pso_boot import Plane, Reader                                # noqa: E402

OUT = Path(r"D:\gBox\pso-ds\routes")
GID = "436e0bb84d5337d1"
BUTTONS = {0x1000: "a", 0x2000: "b", 0x4000: "x", 0x8000: "y", 0x0010: "start", 0x0020: "back",
           0x0001: "dup", 0x0002: "ddown", 0x0004: "dleft", 0x0008: "dright"}
OFF_X, OFF_Y, OFF_Z = 0x038, 0x03C, 0x040


def pad_keys() -> frozenset:
    from gbox import xinput
    fn = xinput.load()
    for slot in range(4):
        st = xinput.read(fn, slot)
        if st is None:
            continue
        g = st.gamepad
        if g.buttons or abs(g.lx) > 7849 or abs(g.ly) > 7849:
            keys = {name for bit, name in BUTTONS.items() if g.buttons & bit}
            if abs(g.lx) > 7849:
                keys.add("right" if g.lx > 0 else "left")
            if abs(g.ly) > 7849:
                keys.add("down" if g.ly > 0 else "up")
            return frozenset(keys)
    return frozenset()


def actor(reader) -> int:
    import struct
    slots = struct.unpack(">4I", reader.read(pso_ram.PLAYER_SLOTS, 16))
    return next((s for s in slots if s), 0)


def record(session: str, seconds: float, hz: float = 8.0) -> Path:
    import struct
    plane = Plane()
    reader = Reader(plane, session)
    rows = []
    start = time.time()
    actor_ptr, missing = 0, 0
    print(f"recording route for {seconds:.0f}s at {hz:.0f} Hz", flush=True)
    while time.time() - start < seconds:
        now = time.time() - start
        try:
            if not actor_ptr or missing > 20:
                actor_ptr = actor(reader)
                missing = 0
            if not actor_ptr:
                missing += 1
            else:
                x, y, z = struct.unpack(">3f", reader.read(actor_ptr + OFF_X, 12))
                rows.append({"t": round(now, 3), "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
                             "floor": pso_ram.floor(reader), "keys": sorted(pad_keys())})
                missing = 0
        except Exception as exc:                                  # noqa: BLE001
            missing += 1
            if missing == 1:
                print("read error:", exc, flush=True)
        time.sleep(1 / hz)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"route-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"session": session, "rows": rows}, indent=0), encoding="utf-8")
    print(f"{len(rows)} samples -> {path}")
    return path


def _simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker on (x, z)."""
    if len(points) < 3:
        return points
    (x1, z1), (x2, z2) = points[0], points[-1]
    dx, dz = x2 - x1, z2 - z1
    norm = (dx * dx + dz * dz) ** 0.5 or 1.0
    worst, index = -1.0, 0
    for i in range(1, len(points) - 1):
        px, pz = points[i]
        distance = abs(dz * (px - x1) - dx * (pz - z1)) / norm
        if distance > worst:
            worst, index = distance, i
    if worst <= tolerance:
        return [points[0], points[-1]]
    left = _simplify(points[: index + 1], tolerance)
    right = _simplify(points[index:], tolerance)
    return left[:-1] + right


def convert(path: Path, tolerance: float = 8.0) -> Path:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in data.get("rows") or [] if r.get("x") is not None]
    if len(rows) < 4:
        raise SystemExit("route too short to convert")
    points = [(r["x"], r["z"]) for r in rows]
    waypoints = _simplify(points, tolerance)
    moves = sum(1 for a, b in zip(rows, rows[1:]) if abs(a["x"] - b["x"]) + abs(a["z"] - b["z"]) > 1.0)
    steps = [{"op": "navigate", "to": [round(x, 1), round(z, 1)], "radius": 12} for x, z in waypoints[1:]]
    mission = {"name": f"route-{path.stem.split('-')[-1]}", "game_id": GID,
               "objective": "Walk the route the operator walked (recorded from their own play)",
               "policy": "learned-from-operator-route",
               "provenance": {"source": str(path), "samples": len(rows), "moving_samples": moves,
                              "waypoints": len(waypoints), "tolerance": tolerance},
               "steps": steps}
    out = path.with_name(path.stem + "-mission.json")
    out.write_text(json.dumps(mission, indent=1), encoding="utf-8")
    print(f"{len(waypoints)} waypoints from {len(rows)} samples -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--session", required=True)
    rec.add_argument("--seconds", type=float, default=600)
    con = sub.add_parser("convert")
    con.add_argument("--file", required=True)
    con.add_argument("--tolerance", type=float, default=8.0)
    args = ap.parse_args()
    if args.cmd == "record":
        record(args.session, args.seconds)
    else:
        convert(Path(args.file), args.tolerance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
