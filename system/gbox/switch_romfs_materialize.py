"""Materialise the arcs a title's skin swap needs into the extracted RomFS tree `gbox.skin_swap` reads.

`gbox.skin_swap` builds its swaps from an extracted RomFS (`~/gBox_alt/switch/romfs/<TITLE_ID>`), which exists on the
node that originally extracted the library but not on a fresh client. The library's containers cannot be extracted by
the shipped hactool (`Invalid NCA header`), so this module uses `gbox.switch_nca`/`gbox.switch_extract` to pull exactly
the arcs a swap targets (`CHARACTER_ARCS`, `ENEMY_ARCS`, `PLAYER_AS_MAJINI`) out of the container - 16 arcs for RE6
instead of the 60,645-file RomFS - and writes them in the layout `skin_swap.romfs_root()` expects.

    python -m gbox.switch_romfs_materialize <container.nsp> <nca> --keys prod.keys --title 01002A000CD48000 \
        [--dest <dir>] [--print]
"""
import argparse
import sys
from pathlib import Path

from . import skin_swap, switch_extract, switch_nca


def wanted(title_id: str, include: tuple[str, ...] = ()) -> list[str]:
    """The RomFS paths a swap targets for this title: character bodies, enemies and the player-as-enemy texture arc.

    `include` adds every path whose *basename* starts with one of the given prefixes (e.g. `uPlTex`: RE6 keeps the
    characters' body textures in 41 separate `uPlTex####_N.arc` archives, 218 MB, not in the body arcs).
    """
    tid = str(title_id).upper()
    paths = list(skin_swap.CHARACTER_ARCS.get(tid, {}).values())
    paths += list(skin_swap.ZOMBIE_ARCS.get(tid, ()))
    major = skin_swap.PLAYER_AS_MAJINI.get(tid)
    if major:
        paths.append(major)
    return sorted(set(paths))


def select(by_path: dict, title_id: str, include: tuple[str, ...] = ()) -> list[str]:
    """The wanted paths plus every path whose basename starts with an `include` prefix (order: wanted first)."""
    chosen = list(wanted(title_id))
    if include:
        extra = sorted(p for p in by_path
                       if p.split("/")[-1].startswith(tuple(include)) and p not in chosen)
        chosen += extra
    return chosen


def materialize(container: str | Path, nca_name: str, keys_path: str | Path, title_id: str,
                dest: str | Path | None = None, include: tuple[str, ...] = ()) -> dict:
    """Extract the wanted arcs under `dest` (default: `skin_swap.romfs_root(title_id)`) and report what was written."""
    tid = str(title_id).upper()
    target = Path(dest) if dest else (skin_swap.romfs_root(tid)
                                      or Path.home() / "gBox_alt" / "switch" / "romfs" / tid)
    keys = switch_nca.load_keys(keys_path)
    nca = switch_extract.Nca(container, nca_name, keys)
    romfs = nca.romfs()
    by_path = {f["path"]: f for f in romfs["files"]}
    section = next(s for s in nca.header["sections"] if s["fs_type"] == switch_nca.FS_ROMFS)
    data_at = nca._romfs_at + romfs["header"]["data_offset"]
    written, skipped, total = [], [], 0
    for path in select(by_path, tid, include):
        entry = by_path.get(path)
        if entry is None:
            skipped.append(path)
            continue
        out = target / path
        out.parent.mkdir(parents=True, exist_ok=True)
        if not (out.is_file() and out.stat().st_size == entry["size"]):
            data = nca.read_section(section["index"], data_at + entry["offset"], entry["size"])
            out.write_bytes(data)
        written.append(path)
        total += entry["size"]
    return {"title_id": tid, "dest": str(target), "written": written, "skipped": skipped, "bytes": total}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gbox.switch_romfs_materialize", description=__doc__.splitlines()[0])
    parser.add_argument("container")
    parser.add_argument("nca")
    parser.add_argument("--keys", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--dest", default="")
    parser.add_argument("--include", action="append", default=[], help="also take every path whose basename starts with this prefix (repeatable)")
    parser.add_argument("--print", dest="show", action="store_true", help="print the wanted paths and exit")
    args = parser.parse_args(argv)
    if args.show:
        for path in wanted(args.title):
            print(path)
        return 0
    out = materialize(args.container, args.nca, args.keys, args.title, dest=args.dest or None, include=tuple(args.include))
    print(f"{out['title_id']}: wrote {len(out['written'])} arcs, {out['bytes']} bytes -> {out['dest']}")
    for path in out["skipped"]:
        print(f"  skipped (not in this container): {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

