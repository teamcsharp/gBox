"""Read the room's exits from the corner minimap and walk through the chosen one.

The minimap is player-centred and north-up, so a green exit marker at (mx, my) in the crop points at a world direction of
(mx - cx, my - cy). This turns that into a walk target in front of the player and steers there with the empirical controller, so the bot
follows the map's doorways instead of aiming at a room centre it cannot see.

Why: the operator pointed out that a room can have a single exit (west), and an explorer aiming at the next room's centre walks into the
wall. The markers are the only local evidence of where the doorway actually is.

All input goes through pso_input, which honours the operator lock.
"""
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import capture_game as CG                                          # noqa: E402
import pso_input                                                   # noqa: E402
import session as S                                                # noqa: E402
import steer2 as STEER                                             # noqa: E402

BOX = (660, 80, 900, 275)
BOX_LEFT = 560                                                     # the crop origin, if a wider frame is captured
DEMO = Path(r"D:\gBox\pso-ds\demo")
GREEN = lambda p: p[1] > 200 and p[0] < 70 and p[2] < 70         # noqa: E731  marker green is (0,240,0); foliage is duller


def log(line):
    text = f"{time.strftime('%H:%M:%S')} {line}"
    print(text, flush=True)


def read_pos():
    import struct
    pointer = int.from_bytes(S.read_memory(0x8050EA10, 4), "big")
    if not pointer:
        return None
    blob = S.read_memory(pointer + 0x38, 12)
    if len(blob) != 12:
        return None
    x, _y, z = struct.unpack(">fff", blob)
    return (x, z)


def capture():
    CG.main()
    newest = sorted(DEMO.glob("*-game.png"), key=lambda p: p.stat().st_mtime)[-1]
    return newest


def markers(path, box=BOX):
    """Green clusters in the minimap crop: doors/exits, as (x, y, pixels) in crop space."""
    from PIL import Image
    image = Image.open(path).convert("RGB").crop(box)
    pixels = image.load()
    width, height = image.size
    points = [(x, y) for y in range(height) for x in range(width) if GREEN(pixels[x, y])]
    clusters = []
    for point in points:
        for cluster in clusters:
            if abs(point[0] - cluster[0][0]) <= 4 and abs(point[1] - cluster[0][1]) <= 4:
                cluster.append(point)
                break
        else:
            clusters.append([point])
    out = []
    for cluster in clusters:
        if len(cluster) < 6:
            continue
        xs = [p[0] for p in cluster]
        ys = [p[1] for p in cluster]
        out.append((sum(xs) / len(xs), sum(ys) / len(ys), len(cluster)))
    return out


def exits_from_map(path=None, box=BOX):
    """Exit markers as world direction vectors plus their bearings in degrees."""
    path = path or capture()
    from PIL import Image
    image = Image.open(path).convert("RGB").crop(box)
    width, height = image.size
    cx, cy = width / 2.0, height / 2.0
    out = []
    for mx, my, size in markers(path, box):
        dx, dy = mx - cx, my - cy
        length = math.hypot(dx, dy)
        if length < 4:
            continue
        out.append({"mx": round(mx, 1), "my": round(my, 1), "px": size,
                    "distance_px": round(length, 1),
                    "bearing": round(math.degrees(math.atan2(dy, dx)), 1),
                    "dir": (dx / length, dy / length)})
    return out


def heading(point, target):
    return math.degrees(math.atan2(target[1] - point[1], target[0] - point[0]))


def walk_through_exit(want_bearing=None, step_distance=45.0, rounds=4):
    """Walk out of the room by following the minimap exit marker closest to `want_bearing` (world degrees)."""
    for round_index in range(rounds):
        if not pso_input.allowed():
            log("  operator has the controller; waiting")
            if not pso_input.hold("up", 0.0, wait_for_operator=True):   # waits, sends nothing meaningful
                return False
        point = read_pos()
        if point is None:
            return False
        candidates = exits_from_map()
        if not candidates:
            log("  no exit markers on the minimap")
            return False
        marker = candidates[0]
        if want_bearing is not None:
            marker = min(candidates, key=lambda m: abs(((m["bearing"] - want_bearing) + 180) % 360 - 180))
        log(f"  exit marker at ({marker['mx']:.0f},{marker['my']:.0f}) bearing {marker['bearing']:+.0f} deg, "
            f"{marker['distance_px']:.0f}px")
        # the minimap is north-up: map +x is world +x and map +y is world +z
        target = (point[0] + marker["dir"][0] * step_distance, point[1] + marker["dir"][1] * step_distance)
        arrived, steps, final, reason = STEER.step_toward(pso_input.hold, read_pos, target, tolerance=8.0,
                                                          max_steps=8, log=None)
        log(f"  walked toward the exit: arrived={arrived} final={final if final is None else round(final)} ({reason})")
        now = read_pos()
        if now and math.dist(now, point) > 25:
            return True
    return False


if __name__ == "__main__":
    print("player:", read_pos())
    found = exits_from_map()
    print(f"exit markers: {len(found)}")
    for marker in found:
        print(f"  ({marker['mx']:6.1f},{marker['my']:6.1f}) {marker['distance_px']:6.1f}px "
              f"bearing {marker['bearing']:+7.1f} deg  pixels={marker['px']}")
