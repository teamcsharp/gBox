"""`.nup` titles in the library: identity without keys, launch readiness, extraction and model sources.

NUP is plaintext (gbox.nup), so a Switch 1/2 dump tells its own title id, name, publisher, version and build id -
no prod.keys, no CNMT, no ticket. This module is what `gbox.catalog` reads for a `.nup` row, what the Switch adapter
checks before a launch, and what `switch_mods` uses to find an extracted RomFS for LayeredFS.

A materialised NUP (gbox.nup.NupReader.materialize) is a deconstructed title folder: `exefs/`, `romfs/` and a
`.gbox-nup.json` marker at its root. That folder is catalogued as a game of its own (`materialized()`), launched by
path (Eden's AppLoader_DeconstructedRomDirectory), and its `romfs/` becomes the base for mods. The `.nup` row stays in
the library as the source archive and refuses to launch directly, with the one command that fixes it.

    python -m gbox.switch_nup info      <file.nup>
    python -m gbox.switch_nup materialize <file.nup> <folder>
    python -m gbox.switch_nup models    <file.nup|folder> <out> [--convert]
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import nup

MARKER = nup.MARKER
_REGISTRY = "switch-nup-romfs.json"          # node-local: title id -> extracted folder (switch_mods.base_romfs)
_CACHE: dict[tuple[str, int, int], dict] = {}
_CACHE_MAX = 64


def is_nup(path: str | Path) -> bool:
    return nup.is_nup(path)


def _cache_key(path: Path) -> tuple[str, int, int]:
    st = path.stat()
    return str(path), st.st_size, st.st_mtime_ns


def _uncached_info(path: Path, *, light: bool) -> dict:
    with nup.NupReader(path, light=light) as reader:
        return reader.describe()


def info(path: str | Path, *, light: bool = True, refresh: bool = False) -> dict:
    """The container's metadata, cached by (path, size, mtime) so a library scan reads each TOC once per process.

    `light` skips the tree: enough for title identity and package/meta. Pass light=False for per-package file counts.
    """
    p = Path(path)
    key = _cache_key(p)
    if not refresh and key in _CACHE and _CACHE[key].get("light") == light:
        return _CACHE[key]["info"]
    data = _uncached_info(p, light=light)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = {"light": light, "info": data}
    return data


def clear_cache() -> None:
    _CACHE.clear()


def title_id(path: str | Path) -> str | None:
    """The base application title id from the container itself (meta package first), filename tag as fallback."""
    p = Path(path)
    try:
        data = info(p)
        return data.get("title_id") or nup.title_id_from_name(p)
    except (OSError, nup.NupError):
        return nup.title_id_from_name(p)


def catalog_fields(path: str | Path) -> tuple[str | None, dict]:
    """(serial, launch extras) for a catalog row, the same contract `switch_nsp.catalog_fields` supplies.

    The extras ride in CatalogEntry.launch: `nup` marks the row, `nup_title`/`nup_display_version` are what the menu
    and the extraction action show, and an update keeps the base title id the emulator layers it under.
    """
    p = Path(path)
    try:
        data = info(p)
    except (OSError, nup.NupError) as exc:
        tid = nup.title_id_from_name(p)
        return tid, ({"nup": True, "nup_error": str(exc)[:300], "title_id": tid} if tid else
                     {"nup": True, "nup_error": str(exc)[:300]})
    tid = data.get("title_id") or nup.title_id_from_name(p)
    primary = data.get("primary") or {}
    extra = {
        "nup": True,
        "nup_title": data.get("title"),
        "nup_publisher": data.get("publisher"),
        "nup_display_version": primary.get("display_version"),
        "nup_kind": data.get("kind"),
        "nup_packages": len(data.get("packages") or []),
        "nup_standalone_update": bool(data.get("standalone_update")),
        "nup_extract_required": True,
        "switch_generation": 2 if str(tid or "").upper().startswith("04") else 1,
    }
    if tid:
        extra["title_id"] = tid
    if primary.get("kind") == "update" or data.get("standalone_update"):
        extra |= {"title_update": True, "base_title_id": data.get("base_title_id")}
    return tid, extra


def materialized(folder: str | Path) -> dict | None:
    """The marker of a materialised NUP folder, or None when the folder is not one."""
    p = Path(folder)
    marker = p / MARKER
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("kind") == "nup-materialized" else None


def npdm_title_id(path: str | Path) -> str | None:
    """The program id in a `main.npdm` (the ACI0 header's program id), upper-case 16 hex digits, or None.

    An extracted Switch dump has no NUP metadata: its `exefs/main.npdm` is the authoritative identity, and the ACI0
    section begins with the magic "ACI0" then its program id at +8.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    at = data.find(b"ACI0")
    if at < 0 or at + 0x18 > len(data):
        return None
    # ACI0: magic 4, reserved 4, version 4, reserved 4, then the program id (u64 LE) at +0x10 (Donkey Kong Bananza:
    # ACI0 + 0x10 = 040074A01BF12000).
    value = int.from_bytes(data[at + 0x10:at + 0x18], "little")
    return f"{value:016X}" if value else None


def title_id_for(folder_or_file: str | Path) -> str | None:
    """Title id of a `.nup`, a materialised folder (marker), or a Switch container (gbox.switch_nsp)."""
    p = Path(folder_or_file)
    if p.is_dir():
        marker = materialized(p)
        return str(marker.get("title_id")).upper() if marker and marker.get("title_id") else None
    if p.suffix.lower() == ".nup":
        return title_id(p)
    from . import switch_nsp
    try:
        return switch_nsp.title_id(p)
    except (OSError, ValueError):
        return None


def launchable(path: str | Path) -> tuple[bool, str]:
    """(True, "") for a materialised title folder; (False, why) for the `.nup` archive itself.

    An archive is not a boot image: the base package has to become `exefs/` + `romfs/` first, which is one command
    (or the library's Extract action). Saying so is better than handing Eden a 25 GB NUP it cannot open.
    """
    p = Path(path)
    if p.is_dir():
        marker = materialized(p)
        if marker is None:
            return False, f"{p.name} is a folder but not an extracted NUP (no {MARKER})"
        if not (p / "exefs" / "main").is_file():
            return False, (f"{p.name} has no exefs/main: the container had no usable base package (an update-only "
                           "container cannot boot without its base)")
        return True, ""
    if p.suffix.lower() == ".nup":
        return False, (f"{p.name} is a NUP container, not a bootable folder: extract it first with the library's "
                       "'Extract NUP' action or switch_nup op=materialize")
    return True, ""


# --- extracted RomFS registry (switch_mods.base_romfs) ----------------------------------------------------------------

def _registry_path(cfg) -> Path:
    return Path(cfg.runtime) / _REGISTRY


def register_romfs(cfg, title_id: str | None, folder: str | Path) -> None:
    """Remember that `folder` holds the extracted title for `title_id`, for this node's LayeredFS base."""
    if not title_id:
        return
    p = Path(folder)
    data = {}
    path = _registry_path(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        data = {}
    data[str(title_id).upper()] = {"folder": str(p), "romfs": str(p / "romfs"), "at": time.time()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    except OSError:
        pass


def romfs_for(cfg, title_id: str | None) -> Path | None:
    """The extracted RomFS of a materialised NUP on this node (`<folder>/romfs`), if it still exists."""
    if not title_id:
        return None
    try:
        data = json.loads(_registry_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    row = data.get(str(title_id).upper()) or {}
    for candidate in (row.get("romfs"), Path(row.get("folder") or "") / "romfs", row.get("folder")):
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


# --- models -----------------------------------------------------------------------------------------------------------

def extract_models(nup_path: str | Path, out: str | Path, *, package: int | str | None = None,
                   subtree: str = "romfs", extra_patterns: list[str] | None = None,
                   progress=None, cancel=None) -> dict:
    """Pull the title's model sources out of a `.nup` into `<out>/models_src`, with a manifest and a hand-off plan.

    RE Engine titles (RE4 Remake included) keep their meshes inside `re_chunk_000.pak*`; MT Framework titles (RE5/RE6
    on Switch 1) keep them in `.arc` files; other engines ship loose model files. This extracts the containers and the
    loose models, identifies each container's magic, and says which gBox reader/converter takes it next. Converting a
    PAK into GLBs is the existing Windows toolchain (gbox.re4r: ree-pak-cli + RE Mesh Editor in Blender), which needs
    the Switch title's own PAK list - reported as the next step rather than guessed here.
    """
    from . import nup_models
    src = Path(nup_path)
    if src.is_dir():
        marker = materialized(src)
        if marker is None:
            raise nup.NupError(f"{src} is not a materialised NUP folder (no {MARKER})")
        result = nup_models.extract_from_folder(src, out, extra_patterns=extra_patterns, progress=progress,
                                                cancel=cancel)
        result["source"] = str(src)
        result["title_id"] = marker.get("title_id")
        result["title"] = marker.get("title")
        return result
    with nup.NupReader(src) as reader:
        if package is None or package == "":
            # base + updates, in order: the later package shadows the earlier at the same path (SPEC Appendix A)
            packages = [p for p in reader.packages if p.is_game] or [reader.primary_package()]
        else:
            packages = [reader.package_of(package)]
        result = nup_models.extract_from_reader(reader, packages, out, subtree=subtree,
                                                extra_patterns=extra_patterns, progress=progress, cancel=cancel)
    result["source"] = str(src)
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m gbox.switch_nup", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("info"); p.add_argument("file"); p.add_argument("--full", action="store_true")
    p = sub.add_parser("materialize"); p.add_argument("file"); p.add_argument("folder")
    p = sub.add_parser("models"); p.add_argument("file"); p.add_argument("out")
    p.add_argument("--package", default=None); p.add_argument("--subtree", default="romfs")
    args = parser.parse_args(argv)
    if args.cmd == "info":
        print(json.dumps(info(args.file, light=not args.full), indent=2, ensure_ascii=False))
    elif args.cmd == "materialize":
        with nup.NupReader(args.file) as reader:
            print(json.dumps(reader.materialize(args.folder), indent=2, ensure_ascii=False))
    elif args.cmd == "models":
        print(json.dumps(extract_models(args.file, args.out, package=args.package, subtree=args.subtree),
                         indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
