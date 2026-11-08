"""Swap whole character body archives in RE6 (Switch): the same MT Framework route RE5 proved.

RE6 keeps a playable character's body, head and hands in separate `uPl` archives under `nativeNXx64/arc/NX`. The body
archives are ordinary MTF `.arc` containers (measured 2026-11-08: `uPl00LeonUsa.arc` holds one 25,784-vertex MOD at
`data\\chara\\pl\\pl0000\\model\\pl0000`), so the operation RE5's `re5_char_swap` performs applies unchanged: write one
body archive over another, keep the destination's entry table and let the loader draw the donor's body. Head and hand
archives are separate and are not moved by this module.

The archive mapping for the No Mercy cast lives in `gbox.skin_swap.CHARACTER_ARCS`; this module reads the same tree so
the two features cannot drift apart.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ARCHIVE_DIR = Path("nativeNXx64") / "arc" / "NX"
DEFAULT_BUILD = "mercmode-swap"
RE6_GAME_ID = "115f9cdbba115432"
RE6_TITLE_ID = "01002A000CD48000"
PLAYER_RE = re.compile(r"^uPl[0-9A-Fa-f]{2}", re.IGNORECASE)
ENEMY_RE = re.compile(r"^uEm[0-9A-Fa-f]{2}", re.IGNORECASE)


class SwapError(RuntimeError):
    """The swap cannot be built; the message names the file and the reason."""


@dataclass
class SwapReport:
    pairs: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    build: str = ""
    written: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"build": self.build, "pairs": self.pairs, "skipped": self.skipped, "written": self.written,
                "effective": "the title's next boot (MercMode applies this build)"}


def archive_root(romfs: Path) -> Path:
    root = Path(romfs) / ARCHIVE_DIR
    if not root.is_dir():
        raise SwapError(f"{root} is not a directory: is this the RE6 RomFS with nativeNXx64/arc/NX?")
    return root


def catalogue(romfs: Path) -> dict:
    """The body slots the title offers, split into characters and enemies, from the archive names."""
    root = archive_root(romfs)
    names = sorted(p.name for p in root.glob("uP*.arc")) + sorted(p.name for p in root.glob("uE*.arc"))
    players = [n for n in names if PLAYER_RE.match(n)]
    enemies = [n for n in names if ENEMY_RE.match(n)]
    return {"characters": players, "enemies": enemies,
            "counts": {"characters": len(players), "enemies": len(enemies)}}


def plan(romfs: Path, pairs: list[tuple[str, str]]) -> SwapReport:
    root = archive_root(romfs)
    report = SwapReport()
    for donor, target in pairs:
        src, dst = root / donor, root / target
        missing = [p.name for p in (src, dst) if not p.is_file()]
        if missing:
            report.skipped.append({"donor": donor, "target": target, "reason": f"missing {', '.join(missing)}"})
            continue
        report.pairs.append({"donor": donor, "target": target, "bytes": dst.stat().st_size,
                             "donor_bytes": src.stat().st_size,
                             "kind": "character" if PLAYER_RE.match(target) else "enemy"})
    return report


def build(config, romfs: Path, pairs: list[tuple[str, str]], *, build_name: str = DEFAULT_BUILD,
          game_id: str = RE6_GAME_ID, title_id: str = RE6_TITLE_ID, write: bool = True) -> SwapReport:
    """Write the overlay: every target body archive replaced by its donor's bytes."""
    root = archive_root(romfs)
    report = plan(romfs, pairs)
    report.build = build_name
    if not report.pairs:
        raise SwapError(f"nothing to swap: {report.skipped or 'no pairs given'}")
    changes = {f"romfs/{ARCHIVE_DIR.as_posix()}/{row['target']}": {"bytes": (root / row["donor"]).read_bytes()}
               for row in report.pairs}
    if write:
        from . import switch_mods
        result = switch_mods.write_files(config, game_id, build_name, changes,
                                         create={"title_id": title_id, "kind": "file", "game_title": "re6"},
                                         note="RE6 body archive swap: " + ", ".join(
                                             f"{r['target']}<-{r['donor']}" for r in report.pairs))
        report.written = list(result.get("files") or changes)
    else:
        report.written = list(changes)
    return report


def main(argv=None) -> int:
    """CLI: --romfs <dir> --pairs donor.arc=target.arc[,donor.arc=target.arc] [--build name] [--dry-run]"""
    import argparse
    import json
    import sys
    parser = argparse.ArgumentParser(description="Swap whole RE6 character body archives")
    parser.add_argument("--romfs", required=True)
    parser.add_argument("--pairs", required=True, help="donor.arc=target.arc,...")
    parser.add_argument("--build", default=DEFAULT_BUILD)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--catalogue", action="store_true", help="list the slots and exit")
    args = parser.parse_args(argv)
    romfs = Path(os.path.expanduser(args.romfs))
    try:
        if args.catalogue:
            print(json.dumps(catalogue(romfs), indent=1))
            return 0
        pairs = [tuple(v.strip() for v in p.split("=", 1)) for p in args.pairs.split(",") if "=" in p]
        if not pairs:
            print("pairs must look like donor.arc=target.arc")
            return 2
        config = type("Config", (), {"cache": os.path.expanduser("~/gBox_alt/gbox-cache")})()
        report = build(config, romfs, [(a, b) for a, b in pairs], build_name=args.build, write=not args.dry_run)
        print(json.dumps(report.as_dict(), indent=1))
    except SwapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
