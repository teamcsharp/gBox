"""Render a gallery of floor minimaps from the room database.

The 2D map is the level, so the useful artifact is pictures of it: each floor's rooms shaded by height on a common scale, labelled, with the room
count and navigability. This renders every mapped floor into one image so the whole of Episode I can be seen at once.
"""
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOMS = Path(r"D:\gBox\pso-ds\rooms")
ROUTES = Path(r"D:\gBox\pso-ds\routes")
OUT = Path(r"D:\gBox\pso-ds\rooms\ep1-gallery.png")

NAMES = {1: "Forest 1", 2: "Forest 2", 3: "Cave 1", 4: "Cave 2", 5: "Cave 3", 6: "Mines 1",
         7: "Mines 2", 8: "Ruins 1", 9: "Ruins 2", 10: "Ruins 3", 11: "Dragon", 12: "De Rol Le",
         13: "Vol Opt", 14: "Dark Falz"}


def load(floor):
    index = json.loads((ROOMS / "index.json").read_text(encoding="utf-8"))
    entry = index.get(str(floor))
    if not entry:
        return None
    return json.loads((ROOMS / entry["file"]).read_text(encoding="utf-8"))


def audit(floor):
    try:
        rows = json.loads((ROUTES / "map-audit.json").read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    for row in rows if isinstance(rows, list) else [rows]:
        if int(row.get("floor", -1)) == floor:
            return row
    return None


def draw_floor(canvas, draw, payload, floor, box):
    x0, y0, x1, y1 = box
    rooms = payload.get("rooms") or []
    cells = [(c[0], c[1]) for room in rooms for c in room.get("cell_list") or []]
    if not cells:
        draw.text((x0 + 8, y0 + 8), f"{NAMES.get(floor, floor)}: no cells", fill=(150, 150, 150))
        return
    min_x, max_x = min(c[0] for c in cells), max(c[0] for c in cells)
    min_z, max_z = min(c[1] for c in cells), max(c[1] for c in cells)
    scale = min((x1 - x0 - 20) / max(1.0, max_x - min_x), (y1 - y0 - 40) / max(1.0, max_z - min_z))
    heights = [r["height"]["median"] for r in rooms if r.get("height", {}).get("median") is not None]
    low, high = (min(heights), max(heights)) if heights else (0.0, 1.0)
    for room in rooms:
        median = room.get("height", {}).get("median")
        ratio = 0.0 if high == low or median is None else (median - low) / (high - low)
        colour = (int(30 + 90 * ratio), int(70 + 90 * ratio), int(140 + 60 * ratio))
        for cell in room.get("cell_list") or []:
            cx = x0 + 10 + (cell[0] - min_x) * scale
            cz = y0 + 30 + (cell[1] - min_z) * scale
            draw.rectangle([cx - 1.5, cz - 1.5, cx + 1.5, cz + 1.5], fill=colour)
        centre = room["centre"]
        tx = x0 + 10 + (centre[0] - min_x) * scale
        tz = y0 + 30 + (centre[1] - min_z) * scale
        draw.text((tx - 4, tz - 4), str(room["room"]), fill=(220, 225, 230))
    verdict = audit(floor)
    note = ""
    if verdict:
        note = f" {verdict.get('reachable_cells', '?')}/{verdict.get('free_cells', '?')} cells reachable"
        if verdict.get("ok"):
            note += " PASS"
    draw.rectangle([x0, y0, x1 - 1, y1 - 1], outline=(40, 45, 55))
    draw.text((x0 + 8, y0 + 8), f"F{floor} {NAMES.get(floor, '')} - {len(rooms)} rooms{note}",
              fill=(200, 205, 210))


def main():
    floors = [floor for floor in range(1, 15) if load(floor)]
    columns, rows = 4, 4
    tw, th = 420, 330
    width, height = columns * tw, rows * th
    image = Image.new("RGB", (width, height), (13, 17, 23))
    draw = ImageDraw.Draw(image)
    for index, floor in enumerate(floors):
        col, row = index % columns, index // columns
        draw_floor(image, draw, load(floor), floor,
                   (col * tw, row * th, (col + 1) * tw, (row + 1) * th))
    image.save(OUT)
    print(f"wrote {OUT} ({width}x{height}, {len(floors)} floors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
