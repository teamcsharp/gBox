"""Can the cave layouts' placement sets be read from the owned disc? That identifies the loaded layout.

The live session is floor 3 = `map_cave01`, six layouts, and the player's position falls outside all of them because a room is translated when loaded. To resolve
**which** layout is loaded and by how much, the strongest evidence is the placements: the 125 live entities have world positions, and a layout's set data lists
where its objects belong. Matching the two gives both answers at once.

That needs the set archive from the disc. This opens the disc, lists the cave sets, and decodes one - the enabling step, reported honestly if it fails.
"""
import sys

sys.path.insert(0, r"C:\_tools\gBox\system")

DISC = r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz"

try:
    from gbox import gcdisc
    print("gcdisc members:", [name for name in dir(gcdisc) if not name.startswith("_")][:14])
except Exception as exc:                                            # noqa: BLE001
    raise SystemExit(f"gcdisc import failed: {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    from pathlib import Path

    path = Path(DISC)
    print("disc:", path.name, "| exists:", path.is_file(), "|", round(path.stat().st_size / 2**30, 2), "GB" if path.is_file() else "")

    opener = getattr(gcdisc, "GCDisc", None) or getattr(gcdisc, "open_disc", None)
    print("opener:", opener)
    if opener is None:
        raise SystemExit("no disc opener found")

    try:
        disc = opener(path)
    except Exception as exc:                                        # noqa: BLE001
        raise SystemExit(f"could not open the disc: {type(exc).__name__}: {str(exc)[:200]}")

    files = getattr(disc, "files", None) or {}
    print("files in the disc:", len(files))
    cave = [name for name in files if "cave01" in name.lower() or "cave01" in str(name).lower()]
    print(f"cave01 entries: {len(cave)}")
    for name in sorted(cave)[:20]:
        print("  ", name)

    from gbox import pso_setdata
    for name in sorted(cave):
        if not str(name).endswith("d.dat"):
            continue
        try:
            data = disc.read(str(name)) if hasattr(disc, "read") else None
        except Exception as exc:                                    # noqa: BLE001
            print("  read failed:", type(exc).__name__, str(exc)[:80])
            break
        if data is None:
            print("  disc has no read()")
            break
        recs = pso_setdata.records(data)
        print(f"  {name}: {len(data)} bytes, {len(recs)} placements")
        if recs:
            print("    first:", {k: recs[0].get(k) for k in ("kind", "x", "y", "z")})
        break
