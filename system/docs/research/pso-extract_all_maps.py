"""Extract every collision map from the disc, so any area can be mapped the moment the bot is in it.

The Cave 1 pipeline - identify the loaded layout by matching live objects to walkable cells, then segment rooms, build heights and write the room
database - needs only that area's collision file. Extracting them all now means a future visit to any area costs one identification step instead of a
disc read, and the layouts for an area are already local when the bot arrives.

Collision files follow `<area>_<layout>c.rel`. They are small (100-600 KB each), so the whole set is a few tens of megabytes.
"""
import pathlib
import sys

sys.path.insert(0, r"C:\_tools\gBox\.tmp")

import gc_extract2 as G                                            # noqa: E402

OUT = pathlib.Path(r"D:\gBox\pso-ds\rel")
OUT.mkdir(parents=True, exist_ok=True)


def main():
    rows = [row for row in G.entries()
            if row[1] is not None and row[0].lower().endswith("c.rel") and "/map_" in "/" + row[0].lower()]
    print(f"collision maps in the image: {len(rows)}")
    extracted = 0
    skipped = 0
    total = 0
    with G.ISO.open("rb") as handle:
        for path, offset, size in rows:
            name = path.split("/")[-1]
            target = OUT / name
            if target.exists() and target.stat().st_size == size:
                skipped += 1
                continue
            handle.seek(offset)
            target.write_bytes(handle.read(size))
            extracted += 1
            total += size
            if extracted % 20 == 0:
                print(f"  ... {extracted} extracted")
    print(f"extracted {extracted} new maps ({total / 1e6:.1f} MB), {skipped} already present")
    names = sorted(p.name for p in OUT.glob("*c.rel"))
    areas = sorted({name.split("_")[1] for name in names if name.count("_") >= 2})
    print(f"areas now available ({len(areas)}): {', '.join(areas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
