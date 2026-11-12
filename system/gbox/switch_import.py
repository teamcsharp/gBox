r"""Bring Switch dumps onto this node: SD card / USB folder -> switch2 library -> extracted emulator folder.

The operator's flow: put the card in the PC (or point at a folder the Switch wrote over FTP/MTP), run one command, and
get the title in gBox's switch2 library (and, for a `.nup`, a bootable/loose title folder under the Switch 2 runtime).
No keys are needed for a NUP; NSP/XCI are copied as they are and the emulator uses the share's prod.keys.

    python -m gbox.switch_import scan   --from E:\
    python -m gbox.switch_import import --from E:\ --to "\\\\10.89.1.125\\QuickSwap2\\Emulation\\switch2"
    python -m gbox.switch_import import --from E:\ --to ... --extract --games "D:/gBox/runtime/switch2/games"

`scan` never writes. `import` copies only `.nup/.nsp/.xci` that are not already there (same name and size), streams a
SHA-256 while copying, and skips files whose size changed during the read (a download still in progress). `--extract`
materialises each NUP into `<games>/<title> [<title id>]` with gbox.nup, so the emulator's game list and gBox's model
pipeline have a loose `exefs/` + `romfs/` tree.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import time
from pathlib import Path

from . import nup, switch_nup

TITLE_EXTS = (".nup", ".nsp", ".xci")
SKIP_PARTS = (".part", ".tmp", ".crdownload", ".download")
SKIP_DIRS = {"system volume information", "$recycle.bin", "recycler", "lost+found", ".git", "__pycache__", "loz"}


def _stable(path: Path, wait: float = 0.8) -> bool:
    """A file whose size is unchanged after `wait` (a download that is still growing is skipped)."""
    try:
        first = path.stat().st_size
        if first <= 0:
            return False
        time.sleep(wait)
        return path.stat().st_size == first
    except OSError:
        return False


def removable_drives() -> list[Path]:
    """The card readers currently holding media on Windows (`GetDriveType` = DRIVE_REMOVABLE)."""
    if os.name != "nt":
        return []
    try:
        mask = ctypes.windll.kernel32.GetLogicalDrives()
    except AttributeError:
        return []
    out = []
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        try:
            if ctypes.windll.kernel32.GetDriveTypeW(root) == 2 and Path(root).exists():
                out.append(Path(root))
        except OSError:
            continue
    return out


def installed_content(source: str | Path) -> dict | None:
    """Describe a card that holds Switch **installed** content instead of titles, so a scan can say why nothing imports.

    A Switch 2 SD has `Nintendo/Contents/registered/<group>/<nca id>.nca.CONCAT/00..`, NAX1-encrypted for that console
    (SD seed; no titles/tickets in the filenames). It is not an NSP/NUP and cannot be converted on a PC without the
    console's keys; the scan reports it instead of returning an unexplained empty list.
    """
    root = Path(source)
    for candidate in (root, *root.parents):
        registered = candidate / "Nintendo" / "Contents" / "registered"
        if registered.is_dir():
            groups = [d for d in registered.iterdir() if d.is_dir()]
            return {"registered": str(registered), "content_groups": len(groups),
                    "nca_concat": len(list(registered.rglob("*.nca.CONCAT"))),
                    "tickets": len(list((candidate / "Nintendo").rglob("*.tik"))),
                    "note": ("Switch installed SD content (NAX1, console-bound), not a NUP/NSP: dump the title on the "
                             "console to an NSP/NUP first; a PC cannot decrypt the card")}
    return None


def find_titles(source: str | Path, *, min_mb: float = 4.0, stable: bool = True) -> list[Path]:
    """Every `.nup/.nsp/.xci` under a card/folder, ignoring OS junk and partial downloads.

    `min_mb=0` still ignores files under 1 KiB (a marker/placeholder is not a title); a real demo is megabytes.
    """
    root = Path(source)
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix.lower() in TITLE_EXTS else []
    min_bytes = max(1024, int(min_mb * 1024 * 1024))
    found = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TITLE_EXTS:
            continue
        if any(part.lower() in SKIP_DIRS for part in path.parts):
            continue
        if path.name.lower().endswith(SKIP_PARTS):
            continue
        try:
            if path.stat().st_size < min_bytes:
                continue
        except OSError:
            continue
        if stable and not _stable(path):
            continue
        found.append(path)
    return sorted(found)


def _already(dest: Path, src: Path) -> bool:
    try:
        return dest.is_file() and dest.stat().st_size == src.stat().st_size
    except OSError:
        return False


def import_titles(sources: list[str | Path], dest: str | Path, *, extract: bool = False,
                  games_dir: str | Path | None = None, min_mb: float = 4.0, progress=None,
                  cancel=None) -> dict:
    """Copy every title found under `sources` into `dest`; optionally materialise each NUP into `games_dir`."""
    target = Path(dest)
    target.mkdir(parents=True, exist_ok=True)
    found: list[Path] = []
    for source in sources:
        found += find_titles(source, min_mb=min_mb)
    seen = set()
    unique = []
    for path in found:
        key = (path.name.lower(), path.stat().st_size)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    titles, copied = [], []
    games = Path(games_dir) if games_dir else None
    for i, src in enumerate(unique, 1):
        if cancel and cancel():
            raise RuntimeError("cancelled")
        if progress:
            progress(5 + 85 * i / max(1, len(unique)), f"{src.name} ({i}/{len(unique)})")
        out = target / src.name
        if _already(out, src):
            row = {"source": str(src), "name": src.name, "bytes": src.stat().st_size, "copied": False}
        else:
            before = src.stat().st_size
            digest = hashlib.sha256()
            tmp = out.with_name(out.name + ".part")
            with open(src, "rb") as fh, open(tmp, "wb") as w:
                for block in iter(lambda: fh.read(4 << 20), b""):
                    w.write(block)
                    digest.update(block)
            if src.stat().st_size != before or src.stat().st_size != tmp.stat().st_size:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"{src.name} changed while copying (still downloading?); try again")
            tmp.replace(out)
            copied.append(out)
            row = {"source": str(src), "name": src.name, "bytes": out.stat().st_size, "copied": True,
                   "sha256": digest.hexdigest(), "library_path": str(out)}
        if extract and src.suffix.lower() == ".nup":
            try:
                row["extracted"] = materialize(out, games) if games else None
            except (OSError, nup.NupError) as exc:
                row["extract_error"] = str(exc)[:300]
        titles.append(row)
    return {"sources": [str(s) for s in sources], "dest": str(target), "found": len(unique),
            "copied": len(copied), "titles": titles,
            "note": "rescan the switch2 library in gBox to add the copied titles; Play uses the .nup directly"}


def materialize(nup_path: str | Path, games_dir: str | Path, *, progress=None) -> dict:
    """Extract a NUP into `<games_dir>/<title> [<title id>]` (a loose exefs/ + romfs/ title)."""
    src = Path(nup_path)
    with nup.NupReader(src) as reader:
        info = reader.describe()
        tid = info.get("title_id") or "unknown"
        title = info.get("title") or src.stem
        safe = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in title).strip(" .") or src.stem
        dest = Path(games_dir) / f"{safe} [{tid}]"
        result = reader.materialize(dest, progress=(lambda ev: progress(ev.get("percent", 0.0),
                                                                        f"{title}: {ev.get('file', '')}")
                                                     if progress else None))
    return result | {"nup": str(src), "games_dir": str(Path(games_dir))}


def watch_titles(dest: str | Path, *, sources: list[str | Path] | None = None, all_drives: bool = False,
                 extract: bool = False, games_dir: str | Path | None = None, min_mb: float = 4.0,
                 timeout_s: float = 3600.0, interval_s: float = 8.0, progress=None,
                 cancel=None) -> dict:
    """Wait for a card (or a folder) to show titles, then import once; returns what was imported.

    `all_drives` watches every mounted removable drive, so the operator can plug the Switch's microSD reader in and walk
    away: the first card with a `.nup/.nsp/.xci` is copied into the library (and extracted, with `extract`) exactly as
    `import` would. A card with no titles yet keeps waiting until `timeout_s`; cancellation is checked each interval.
    """
    seen: set[str] = set()
    deadline = time.time() + max(1.0, timeout_s)
    started = time.time()
    while time.time() < deadline:
        if cancel and cancel():
            raise RuntimeError("cancelled")
        roots = [Path(s) for s in sources] if sources else []
        if all_drives:
            roots += [d for d in removable_drives() if d not in roots]
        roots = [r for r in roots if r.exists()]
        if progress:
            progress(2.0, "Waiting for a Switch card" + (f" ({', '.join(str(r) for r in roots)})" if roots else
                                                          " (no removable media yet)"))
        for root in roots:
            titles = [p for p in find_titles(root, min_mb=min_mb) if str(p) not in seen]
            if not titles:
                continue
            if progress:
                progress(10.0, f"{len(titles)} title(s) on {root}; importing")
            result = import_titles([root], dest, extract=extract, games_dir=games_dir, min_mb=min_mb,
                                   progress=progress, cancel=cancel)
            seen.update(str(p) for p in titles)
            result |= {"root": str(root), "waited_s": round(time.time() - started, 1)}
            return result
        time.sleep(max(1.0, interval_s))
    raise TimeoutError(f"no Switch title appeared within {timeout_s / 60:.0f} minutes")


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(prog="python -m gbox.switch_import", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="list the Switch titles on a card/folder (no writes)")
    p.add_argument("--from", dest="source", required=True)
    p = sub.add_parser("import", help="copy the titles into the switch2 library, optionally extract NUPs")
    p.add_argument("--from", dest="source", required=True)
    p.add_argument("--to", dest="dest", required=True)
    p.add_argument("--extract", action="store_true")
    p.add_argument("--games", default=None, help="where extracted NUPs go (with --extract)")
    p = sub.add_parser("watch", help="wait for a card to appear, then import it once")
    p.add_argument("--from", dest="sources", action="append", default=None,
                   help="a folder/drive to watch (repeatable); omit with --all-drives")
    p.add_argument("--all-drives", action="store_true", help="watch every mounted removable drive")
    p.add_argument("--to", dest="dest", required=True)
    p.add_argument("--extract", action="store_true")
    p.add_argument("--games", default=None)
    p.add_argument("--timeout", dest="timeout_s", type=float, default=3600)
    p.add_argument("--interval", dest="interval_s", type=float, default=15.0,
                   help="seconds between card/folder scans (default 15)")
    args = parser.parse_args(argv)
    if args.cmd == "scan":
        rows = find_titles(args.source)
        print(json.dumps({"source": args.source,
                          "titles": [{"path": str(p), "bytes": p.stat().st_size} for p in rows],
                          "installed_content": installed_content(args.source)}, indent=2))
        return 0
    if args.cmd == "watch":
        out = watch_titles(args.dest, sources=args.sources, all_drives=args.all_drives, extract=args.extract,
                           games_dir=args.games, timeout_s=args.timeout_s, interval_s=args.interval_s,
                           progress=lambda pct, msg: print(f"{pct:5.1f}% {msg}", flush=True))
        print(json.dumps(out, indent=1))
        return 0
    out = import_titles([args.source], args.dest, extract=args.extract, games_dir=args.games,
                        progress=lambda pct, msg: print(f"{pct:5.1f}% {msg}", flush=True))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
