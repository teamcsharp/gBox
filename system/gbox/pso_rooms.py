"""GameCube room pieces: each `Scene/map_<area>_<room>r.rel` opens with the room's floor quad.

CP8 asks for "a reader that lists Forest 1's rooms with their origins". Forest 1 has no GameCube `r.rel` (CP7.3), but the
GameCube areas that do have one carry the room's rectangle in the clearest possible form: the first **twelve floats** are
four corner points, all on `y = 0`:

    Scene/map_aancient01_00r.rel  (-100, 0, -150) (-100, 0, 150) (100, 0, -150) (100, 0, 150)
    Scene/map_aancient01_03r.rel  (-75, 0, -20) (-55, 0, -20) (-55, 0, 20) (-75, 0, 20)
    Scene/map_aancient01_04r.rel  (150, 0, 55) (175, 0, 55) (175, 0, 95) (150, 0, 95)

i.e. an axis-aligned rectangle in the x/z plane: its centre is the room's **origin**, its extent its **size**. That is what
this module reads; the `r.rel`'s remaining data (its sections and their transforms) is not decoded.
"""
from __future__ import annotations

import struct

CORNERS = 4
FLOATS = CORNERS * 3
REL_SUFFIX = "r.rel"


class RoomError(ValueError):
    """The bytes do not start with a room quad."""


def room_quad(data: bytes) -> dict:
    """{corners, origin, size, min, max, y, flat, slope} for a room `r.rel`'s opening four points.

    The four points are the room's **footprint corners**, not necessarily a horizontal rectangle: 12 of the 141 GameCube
    `Scene/*r.rel` files slope (e.g. `map_boss05r.rel` spans y 1.23..7.00, `map_jungle03_00r.rel` spans -40..15). So a
    non-flat quad is data, not an error; `flat` records whether it is horizontal and `slope` the y range.
    """
    if len(data) < FLOATS * 4:
        raise RoomError(f"{len(data)} bytes is smaller than the {FLOATS * 4}-byte quad")
    values = struct.unpack_from(f">{FLOATS}f", data, 0)
    corners = [tuple(values[i:i + 3]) for i in range(0, FLOATS, 3)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    zs = [c[2] for c in corners]
    if max(xs) - min(xs) <= 0 or max(zs) - min(zs) <= 0:
        raise RoomError("the quad has no footprint (zero x or z extent)")
    origin = (round((min(xs) + max(xs)) / 2, 3), round(sum(ys) / len(ys), 3),
              round((min(zs) + max(zs)) / 2, 3))
    size = (round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), round(max(zs) - min(zs), 3))
    return {"corners": corners, "origin": origin, "size": size,
            "min": (min(xs), min(ys), min(zs)), "max": (max(xs), max(ys), max(zs)),
            "y": origin[1], "flat": max(ys) - min(ys) <= 0.5, "slope": (min(ys), max(ys))}


def rooms(paths: list[str], read) -> list[dict]:
    """List rooms from `(name, read(name))`: [{name, origin, size}] in the given order."""
    out = []
    for name in paths:
        try:
            quad = room_quad(read(name))
        except RoomError:
            continue
        out.append({"name": name, "origin": quad["origin"], "size": quad["size"]})
    return out


# ---------------------------------------------------------------- joining placements to rooms
def contains(quad: dict, x: float, z: float, *, margin: float = 0.0) -> bool:
    """Is (x, z) inside the room's footprint (optionally with a margin)?"""
    return (quad["min"][0] - margin <= x <= quad["max"][0] + margin
            and quad["min"][2] - margin <= z <= quad["max"][2] + margin)


def translate(quad: dict, dx: float, dz: float) -> dict:
    """The footprint moved by (dx, dz) - the room's placement in the area's coordinates."""
    def move(p):
        return (p[0] + dx, p[1], p[2] + dz)
    return {"corners": [move(c) for c in quad["corners"]], "origin": move(quad["origin"]),
            "size": quad["size"], "min": move(quad["min"]), "max": move(quad["max"]),
            "y": quad["y"], "flat": quad["flat"], "slope": quad["slope"]}


def count_inside(quad: dict, points: list[tuple], *, margin: float = 0.0) -> int:
    return sum(1 for x, z in points if contains(quad, x, z, margin=margin))


def best_offset(quad: dict, points: list[tuple], *, step: float = 25.0, span: float = 2500.0) -> dict:
    """The translation that puts the most points inside the footprint.

    Measured on the real data: an area's placement set spans about +-2000 units while a room's footprint is 20-300 units,
    so the room sits somewhere in the area and needs its own offset (CP8 step 3's per-room transform). This is the coarse
    version of that solve: grid search, returning {dx, dz, inside}.
    """
    best = {"dx": 0.0, "dz": 0.0, "inside": count_inside(quad, points)}
    n = int(span / step)
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            inside = count_inside(translate(quad, i * step, j * step), points)
            if inside > best["inside"]:
                best = {"dx": i * step, "dz": j * step, "inside": inside}
    return best
