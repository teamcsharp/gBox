"""Swap whole character archives in RE5 (Switch): the one route that really changes who a slot draws.

Measured 2026-11-08: `uPl00ChrisNormal.arc` overwritten with `uPl02JillCos1.arc` boots, enters Mercenaries and renders **Jill** in
Chris's slot, HUD still saying "Chris". That is a character replacement, not a skin: the mesh came from the donor archive. RE5
tolerates substitution at the archive level, which RE4 does not (there a player pack over an enemy pack hung the load).

This module turns that measurement into an operation:

    plan(...)   -> the pairs it would write, and which side is missing
    build(...)  -> the LayeredFS overlay for one or more pairs, filed under the catalog game id
    catalogue() -> the slots the title offers, split into characters and enemies, from the archive names

Two rules come from measurement rather than taste:
  * the **target** must exist (it is the slot the game loads), the **donor** only has to exist too - both are read from the
    extracted RomFS, and a pair whose files are absent is skipped with a reason instead of written blind;
  * the build is named `mercmode-swap` by default because that is the build MercMode applies at a title's next boot, so a swap
    made here lands the same way the panel's own swaps do.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ARCHIVE_DIR = Path("nativeNXx64") / "ImgNX" / "Archive"
DEFAULT_BUILD = "mercmode-swap"
# uPl00ChrisNormal.arc, uPl01ShebaNormal.arc, uEm6c.arc ...: a player slot is uPlNN, an enemy is uEmNN
PLAYER_RE = re.compile(r"^uPl[0-9a-f]{2}", re.IGNORECASE)
ENEMY_RE = re.compile(r"^uEm[0-9a-f]{2}", re.IGNORECASE)


class SwapError(RuntimeError):
    """The swap cannot be built; the message names the file and the reason."""


@dataclass
class SwapReport:
    pairs: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    build: str = ""
    written: list[str] = field(default_factory=list)
    pending: bool = False

    def as_dict(self) -> dict:
        return {"build": self.build, "pairs": self.pairs, "skipped": self.skipped, "written": self.written,
                "pending_restart": self.pending,
                "effective": "the title's next boot (MercMode applies this build)"}


def archive_root(romfs: Path) -> Path:
    """The archive folder of an extracted RE5 RomFS."""
    root = Path(romfs) / ARCHIVE_DIR
    if not root.is_dir():
        raise SwapError(f"{root} is not a directory: is this the RE5 RomFS with nativeNXx64/ImgNX/Archive?")
    return root


def catalogue(romfs: Path) -> dict:
    """The slots this title offers, as the names the game uses."""
    root = archive_root(romfs)
    names = sorted(p.name for p in root.glob("uP*.arc")) + sorted(p.name for p in root.glob("uE*.arc"))
    players = [n for n in names if PLAYER_RE.match(n)]
    enemies = [n for n in names if ENEMY_RE.match(n)]
    return {"characters": players, "enemies": enemies, "counts": {"characters": len(players), "enemies": len(enemies)}}


def plan(romfs: Path, pairs: list[tuple[str, str]]) -> SwapReport:
    """Which pairs can be written: donor file -> target file, both by archive name."""
    root = archive_root(romfs)
    report = SwapReport()
    for donor, target in pairs:
        if any(not name or "/" in name or "\\" in name or ":" in name or name in (".", "..")
               for name in (donor, target)):
            raise SwapError("donor and target must be archive basenames inside the RE5 archive folder")
        src, dst = root / donor, root / target
        missing = [str(p.name) for p in (src, dst) if not p.is_file()]
        if missing:
            report.skipped.append({"donor": donor, "target": target, "reason": f"missing {', '.join(missing)}"})
            continue
        report.pairs.append({"donor": donor, "target": target, "bytes": dst.stat().st_size,
                             "donor_bytes": src.stat().st_size,
                             "kind": "character" if PLAYER_RE.match(target) else "enemy",
                             **({"class_rebind": "uEm11->uEm10"}
                                if (donor, target) == ("uEm10.arc", "uEm11.arc") else {})})
    return report


def rebind_main(config) -> bytes:
    """Read the existing expanded main for this measured patch; never extract executable content here."""
    from .re5_ips import TITLE_ID, assert_supported_main
    from . import provision, re_switch
    paths = [Path(config.cache) / "exefs" / TITLE_ID / "main.bin"]
    try:
        paths.append(provision.switch_linux_dir(config) / "dump" / TITLE_ID / "nso"
                     / f"main-{re_switch.RE5_MAIN_BUILD_ID}.nso")
    except AttributeError:
        pass  # Minimal callers can supply just the canonical cache directory.
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
            assert_supported_main(data)
        except (OSError, ValueError) as exc:
            raise SwapError(f"uEm11 replacement needs an existing verified main; {path}: {exc}") from exc
        return data
    raise SwapError(f"uEm11 replacement needs an existing verified main at {' or '.join(map(str, paths))}")


def plan_changes(romfs: Path, pairs: list[tuple[str, str]], *, main: bytes | None = None) -> tuple[SwapReport, dict]:
    """Prepare the complete overlay edit, including the IPS required by the measured uEm11 replacement."""
    root = archive_root(romfs)
    report = plan(romfs, pairs)
    changes = {}
    for row in report.pairs:
        archive = (root / row["donor"]).read_bytes()
        if row.get("class_rebind"):
            from .re5_ips import rebind_changes
            if main is None:
                raise SwapError("uEm11 replacement requires the existing verified decompressed NSO main.bin")
            changes.update(rebind_changes(archive, main=main))
        else:
            changes[f"romfs/{ARCHIVE_DIR.as_posix()}/{row['target']}"] = {"bytes": archive}
    return report, changes


def build(config, romfs: Path, game_id: str, title_id: str, pairs: list[tuple[str, str]],
          build_name: str = DEFAULT_BUILD, write: bool = True) -> SwapReport:
    """Write the overlay: every target archive replaced by its donor's bytes."""
    needs_rebind = ("uEm10.arc", "uEm11.arc") in pairs
    if needs_rebind:
        from .re5_ips import TITLE_ID
        if title_id.upper() != TITLE_ID:
            raise SwapError(f"the uEm11 class rebind is only measured for RE5 Switch {TITLE_ID}")
    report, changes = plan_changes(romfs, pairs, main=rebind_main(config) if needs_rebind else None)
    report.build = build_name
    if not report.pairs:
        raise SwapError(f"nothing to swap: {report.skipped or 'no pairs given'}")
    if write:
        from . import switch_mods
        result = switch_mods.write_files(config, game_id, build_name, changes,
                                         in_use=bool(switch_mods.running_users(game_id, build_name)),
                                         create={"title_id": title_id, "kind": "file", "game_title": "re5"},
                                         note="character archive swap: " + ", ".join(
                                             f"{r['target']}<-{r['donor']}" for r in report.pairs))
        report.written = list(result.get("files") or changes)
        report.pending = bool(result.get("pending"))
    else:
        report.written = list(changes)
    return report


def main(argv=None) -> int:
    """CLI: --romfs <dir> --pairs donor=target[,donor=target] [--build name] [--dry-run]"""
    import argparse
    import json
    import sys
    parser = argparse.ArgumentParser(description="Swap whole RE5 character archives")
    parser.add_argument("--romfs", required=True)
    parser.add_argument("--pairs", required=True, help="donor.arc=target.arc,...")
    parser.add_argument("--build", default=DEFAULT_BUILD)
    parser.add_argument("--game-id", default="52d15709be0fda1a")
    parser.add_argument("--title-id", default="010018100CD46000")
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
        report = build(config, romfs, args.game_id, args.title_id, [(a, b) for a, b in pairs],
                       build_name=args.build, write=not args.dry_run)
        print(json.dumps(report.as_dict(), indent=1))
    except SwapError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
