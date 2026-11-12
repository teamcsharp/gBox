"""What map coverage exists, and for which areas?

`D:\\gBox\\pso-ds\\routes\\` holds scanned room data: `forest1-rooms.json`, `forest1-rooms-mesh.json`, and more. This inventories every file, what it contains
(room count, points, bounds), and which areas it covers - so "the map is analysed" is a fact with a coverage list rather than a claim.

The operator is in Cave 1, so cave coverage matters most.
"""
import json
import pathlib
import re

ROOT = pathlib.Path(r"D:\gBox\pso-ds\routes")


def summarise(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:                                       # noqa: BLE001
        return f"unreadable ({type(exc).__name__})"
    if isinstance(data, dict):
        keys = list(data)[:6]
        rooms = data.get("rooms")
        if isinstance(rooms, dict):
            return f"dict, {len(rooms)} rooms, keys {keys}"
        if isinstance(rooms, list):
            return f"dict, {len(rooms)} rooms, keys {keys}"
        return f"dict, keys {keys}"
    if isinstance(data, list):
        first = data[0] if data else None
        kind = type(first).__name__
        if isinstance(first, dict):
            return f"list of {len(data)} {kind}, fields {list(first)[:8]}"
        return f"list of {len(data)} {kind}"
    return type(data).__name__


if __name__ == "__main__":
    print("routes root:", ROOT, "| exists:", ROOT.is_dir())
    files = sorted(ROOT.glob("*.json")) if ROOT.is_dir() else []
    print(f"{len(files)} files\n")

    areas = {}
    for path in files:
        match = re.match(r"([a-z]+)(\d+)-rooms", path.stem)
        area = match.group(1) if match else path.stem.split("-")[0]
        areas.setdefault(area, []).append(path)
        print(f"  {path.name:34s} {path.stat().st_size / 1024:8.1f} KB  {summarise(path)[:110]}")

    print("\n=== coverage by area ===")
    for area, paths in sorted(areas.items()):
        numbers = sorted({int(m.group(2)) for p in paths if (m := re.match(r"([a-z]+)(\d+)-rooms", p.stem))})
        print(f"  {area:10s} {len(paths)} files, rooms {numbers}")

    print("\n=== is Cave covered? ===")
    cave = [p for p in files if "cave" in p.name.lower()]
    print(f"  cave files: {len(cave)}", [p.name for p in cave[:6]])
    mine = [p for p in files if "mine" in p.name.lower() or "ruins" in p.name.lower()]
    print(f"  mine/ruins files: {len(mine)}", [p.name for p in mine[:6]])
