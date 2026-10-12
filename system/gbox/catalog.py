"""Game library scanner (read-only), Steam library reader, and bounded LRU staging cache."""
import hashlib
import json
import os
import re
import shutil
import time
import zlib
from pathlib import Path

from . import systems
from .config import Config
from .models import CatalogEntry

EXT_PLATFORM = {
    ".nes": "nes", ".fds": "nes", ".sfc": "snes", ".smc": "snes", ".gb": "gb", ".gbc": "gbc", ".gba": "gba",
    ".n64": "n64", ".z64": "n64", ".v64": "n64", ".md": "genesis", ".gen": "genesis", ".smd": "genesis", ".sms": "sms",
    ".gg": "gamegear", ".pce": "pce", ".gdi": "dreamcast", ".cdi": "dreamcast", ".gcm": "gamecube", ".gcz": "gamecube",
    ".rvz": "gamecube_wii", ".wbfs": "wii", ".wua": "wiiu", ".pbp": "psp", ".cso": "psp", ".nds": "nds",
    ".3ds": "3ds", ".xci": "switch", ".nsp": "switch", ".lst": "naomi",
}
SNIFF_EXT = {".iso", ".bin", ".img", ".cue", ".chd"}   # container formats: platform needs header sniffing
REGION_TAGS = {"USA": "US", "Europe": "EU", "Japan": "JP", "World": "World", "Korea": "KR", "Australia": "AU"}


def _read(path: Path, offset: int, n: int) -> bytes:
    with open(path, "rb") as f:
        f.seek(offset)
        return f.read(n)


def param_sfo(b: bytes) -> dict:
    """PS3/PSP PARAM.SFO -> {key: value} (TITLE, TITLE_ID, ...)."""
    import struct
    if b[:4] != b"\x00PSF":
        return {}
    kt, dt, n = struct.unpack("<III", b[8:20])
    out = {}
    for i in range(n):
        ko, fmt, ln, _, do = struct.unpack("<HHIII", b[20 + 16 * i:36 + 16 * i])
        key = b[kt + ko:b.index(b"\x00", kt + ko)].decode()
        v = b[dt + do:dt + do + ln]
        out[key] = struct.unpack("<I", v[:4])[0] if fmt == 0x0404 else v.rstrip(b"\x00").decode("utf-8", "replace")
    return out


def sniff(path: Path) -> tuple[str | None, dict]:
    """Identify platform from disc/ROM headers. Returns (platform, metadata)."""
    head = _read(path, 0, 0x40000)
    if b"PLAYSTATION" in head:
        head = _read(path, 0, 4 * 1024**2)
    return sniff_head(head, path.stat().st_size)


def sniff_head(head: bytes, size: int) -> tuple[str | None, dict]:
    if head[:8] == b"MComprHD":
        return None, {"note": "CHD container; platform requires chdman/libchdr inspection"}
    # Sega IP.BIN at sector start (cooked 2048 at 0, raw 2352 at 0x10)
    for base in (0, 0x10):
        sig = head[base:base + 16]
        if sig.startswith(b"SEGA SEGAKATANA"):
            ip = head[base:base + 0x100]
            return "dreamcast", {"serial": ip[0x40:0x4A].decode("ascii", "replace").strip(),
                                 "region_code": ip[0x30:0x38].decode("ascii", "replace").strip(),
                                 "title": ip[0x80:0x100].decode("ascii", "replace").strip()}
        if sig.startswith(b"SEGA SEGASATURN"):
            return "saturn", {}
    if head[0x1C:0x20] == b"\xc2\x33\x9f\x3d":
        return "gamecube", {"serial": head[:6].decode("ascii", "replace"), "title": head[0x20:0x60].split(b"\0")[0].decode("ascii", "replace")}
    if head[0x18:0x1C] == b"\x5d\x1c\x9e\xa3":
        return "wii", {"serial": head[:6].decode("ascii", "replace"), "title": head[0x20:0x60].split(b"\0")[0].decode("ascii", "replace")}
    # ISO9660 primary volume descriptor: cooked at 0x8000, raw MODE2 at 16*2352+0x18
    for pvd in (0x8000, 16 * 2352 + 0x18, 16 * 2352 + 0x10):
        if head[pvd + 1:pvd + 6] == b"CD001":
            system = head[pvd + 8:pvd + 40].decode("ascii", "replace").strip()
            volume = head[pvd + 40:pvd + 72].decode("ascii", "replace").strip()
            if system.startswith("PLAYSTATION"):
                if re.search(rb"BOOT2\s*=\s*cdrom", head, re.I):
                    return "ps2", {"volume": volume, "boot_platform": "ps2"}
                if re.search(rb"BOOT\s*=\s*cdrom", head, re.I):
                    return "ps1", {"volume": volume, "boot_platform": "ps1"}
                return ("ps2" if size > 900_000_000 else "ps1"), {"volume": volume}
            if volume == "PSP GAME" or system == "PSP GAME":
                return "psp", {"volume": volume}
            return None, {"iso_system": system, "volume": volume}
    return None, {}


def zip_platform(path: Path) -> str | None:
    """A zipped cartridge ROM (No-Intro sets come zipped; RetroArch loads them as they are): the platform of the ROM
    inside, read from the zip's directory only."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if p := EXT_PLATFORM.get(os.path.splitext(n)[1].lower()):
                    return p
    except (OSError, zipfile.BadZipFile, ValueError):
        pass
    return None


def title_from_name(name: str) -> tuple[str, str | None]:
    stem = Path(name).stem
    region = next((r for tag, r in REGION_TAGS.items() if re.search(rf"\b{tag}\b", stem)), None)
    title = re.sub(r"\s*[\(\[].*?[\)\]]", "", stem).strip() or stem
    return title, region


def file_hashes(path: Path, cache: dict) -> dict[str, str]:
    st = path.stat()
    key = f"{path}|{st.st_size}|{st.st_mtime_ns}"
    if key in cache:
        return cache[key]
    sha1, crc = hashlib.sha1(), 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            sha1.update(chunk)
            crc = zlib.crc32(chunk, crc)
    cache[key] = {"sha1": sha1.hexdigest(), "crc32": f"{crc:08x}"}
    return cache[key]


def _referenced_tracks(path: Path) -> set[Path]:
    """Files referenced by .cue/.gdi sheets; these are cataloged as part of the sheet, not separately."""
    out = set()
    text = path.read_text(errors="replace")
    names = re.findall(r'FILE\s+"([^"]+)"', text) if path.suffix.lower() == ".cue" else \
        [m[4] for m in (re.findall(r'"[^"]+"|\S+', ln) for ln in text.splitlines()[1:]) if len(m) >= 5]
    for n in names:
        out.add((path.parent / n.strip('"')).resolve())
    return out


GD_LIST_LINE = re.compile(r'^\d+\s+\d+\s+\d+\s+\d+\s+(?:"[^"]*"|\S+)\s+\d+$')


def is_gd_list(path: Path) -> bool:
    """True when a .lst file looks like a NAOMI/Atomiswave GD-ROM track list
    (Demul/Flycast format: session mode type sectorsize "filename" offset)."""
    try:
        text = path.read_text(errors="replace")[:4096]
    except OSError:
        return False
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", ";"))]
    return bool(lines) and all(GD_LIST_LINE.match(ln) for ln in lines)


def _lst_tracks(path: Path) -> set[Path]:
    """Data files referenced by a .lst GD-ROM list; cataloged as part of the set, not separately."""
    out = set()
    for ln in path.read_text(errors="replace").splitlines():
        m = re.findall(r'"[^"]+"|\S+', ln)
        if len(m) >= 5:
            out.add((path.parent / m[4].strip('"')).resolve())
    return out


def scan(roots: list[Path], runtimes: dict[str, str], hash_cache: dict | None = None,
         lib_id: str | None = None, do_hash: bool = True, platform_hint: str | None = None,
         recursive: bool = True, exclude_dirs: list[str] | None = None,
         exclude_files: list[str] | None = None) -> tuple[list[CatalogEntry], list[str]]:
    """Walk library roots without modifying anything. Returns (deduped entries, problems).

    do_hash=False (network libraries): identity = library + relative path; content hashes come later on demand.
    """
    hash_cache = {} if hash_cache is None else hash_cache
    problems, files = [], []
    for root in roots:
        if not Path(root).exists():
            problems.append(f"library path not reachable: {root}")
            continue
        from fnmatch import fnmatch
        for dirpath, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if recursive and not any(
                fnmatch((Path(dirpath, d).relative_to(root).as_posix()).lower(), pattern.lower())
                for pattern in (exclude_dirs or []))]
            files += [Path(dirpath, n) for n in names if not any(
                fnmatch(Path(dirpath, n).relative_to(root).as_posix().lower(), pattern.lower())
                for pattern in (exclude_files or []))]
    sheets = [f for f in files if f.suffix.lower() in (".cue", ".gdi")]
    lsts = [f for f in files if f.suffix.lower() == ".lst" and is_gd_list(f)]
    tracks = set().union(*(_referenced_tracks(s) for s in sheets), *(_lst_tracks(s) for s in lsts)) \
        if sheets or lsts else set()

    by_hash: dict[str, CatalogEntry] = {}
    ps3 = {f.parents[2] for f in files if f.name.upper() == "EBOOT.BIN" and f.parent.name.upper() == "USRDIR"
           and f.parents[1].name.upper() == "PS3_GAME"}           # extracted PS3 disc folders (JB format)
    for f in files:
        ext = f.suffix.lower()
        disc = next((d for d in ps3 if f.is_relative_to(d)), None)
        if disc and not (f.name.upper() == "EBOOT.BIN" and f.parents[1].name.upper() == "PS3_GAME"):
            continue                                       # a PS3 game's own data files are not games
        if disc:
            try:
                sfo = param_sfo((disc / "PS3_GAME" / "PARAM.SFO").read_bytes())
                root = next(Path(r) for r in roots if f.is_relative_to(r))
                rel = f.relative_to(root).as_posix()
                title, region = title_from_name(disc.name)
                gid = hashlib.sha1(f"{lib_id}:{rel}".encode()).hexdigest()[:16]
                by_hash[gid] = CatalogEntry(
                    game_id=gid, title=title, alt_title=sfo.get("TITLE") if sfo.get("TITLE", "").lower() != title.lower() else None,
                    platform="ps3", platform_confidence="header", region=region, serial=sfo.get("TITLE_ID"),
                    source_paths=[str(f)], library=lib_id, rel_path=rel, system="ps3", collections=[lib_id] if lib_id else [],
                    core=None, hashes={}, size=f.stat().st_size, format="ps3_folder", runtimes={"ps3": "rpcs3"},
                    launch={"kind": "emulator", "platform": "ps3", "path": str(f)}, profile_id=gid)
            except OSError as e:
                problems.append(f"{f}: {e}")
            continue
        archive = None
        archive_meta = {}
        zplat = None
        if ext in (".zip", ".7z"):
            from . import rom_archives
            try:
                contents = rom_archives.members(f)
                archive = rom_archives.boot_member(contents)
                if not archive:
                    continue
                zplat = EXT_PLATFORM.get(Path(archive).suffix.lower()) or platform_hint
                if "/ps3_game/usrdir/eboot.bin" in ("/" + archive.lower()):
                    zplat = "ps3"
                if zplat in ("psx", "ps1", "ps2"):
                    track = next((e for e in sorted(contents, key=lambda e: e["size"], reverse=True)
                                  if Path(e["name"]).suffix.lower() in (".bin", ".iso", ".img")), None)
                    if track:
                        _, archive_meta = sniff_head(rom_archives.prefix(f, track["name"], 4 * 1024**2), track["size"])
                        if archive_meta.get("boot_platform"):
                            zplat = "psx" if archive_meta["boot_platform"] == "ps1" else "ps2"
                if not zplat:
                    problems.append(f"archive needs a console mapping: {f}")
                    continue
            except (OSError, ValueError, RuntimeError) as exc:
                problems.append(f"{f}: {exc}")
                continue
        if f.resolve() in tracks or (ext not in EXT_PLATFORM and ext not in SNIFF_EXT and not archive):
            continue
        try:
            platform_, conf, meta = EXT_PLATFORM.get(ext) or zplat or platform_hint, "extension" if not archive else "archive contents", archive_meta
            candidates, hash_target = [f], f
            if ext in (".cue", ".gdi"):
                candidates = [r for r in sorted(_referenced_tracks(f)) if r.exists()]
                if not candidates:
                    problems.append(f"sheet references no existing tracks: {f}")
                    continue
                hash_target = max(candidates, key=lambda r: r.stat().st_size)
            if ext == ".lst":
                # NAOMI/Atomiswave GD-ROM list sets: the .lst is the game, its data files are not separate entries.
                if not is_gd_list(f):
                    continue
                if not (platform_hint in ("naomi", "naomi2", "atomiswave")
                        or re.search(r"naomi|atomiswave", str(f).lower())):
                    problems.append(f"unidentified platform: {f}")
                    continue
                candidates = [r for r in sorted(_lst_tracks(f)) if r.exists()]
                if not candidates:
                    problems.append(f"list references no existing tracks: {f}")
                    continue
                hash_target = max(candidates, key=lambda r: r.stat().st_size)
                platform_ = platform_hint if platform_hint in ("naomi", "naomi2", "atomiswave") else "naomi"
                conf = "extension"
            if ext in SNIFF_EXT or ext in (".gdi", ".gcm"):
                for c in candidates:
                    p2, meta = sniff(c)
                    if p2:
                        platform_, conf = p2, "header"
                        # PS1 and PS2 use the same ISO system id; an explicit library mapping outranks the size heuristic.
                        if p2 == "ps1" and platform_hint and meta.get("boot_platform"):
                            platform_ = "psx"
                        elif p2 in ("ps1", "ps2") and platform_hint in ("psx", "ps1", "ps2") and not meta.get("boot_platform"):
                            platform_ = platform_hint
                        break
            if not platform_:
                problems.append(f"unidentified platform: {f}")
                platform_ = "unknown"
            root = next(Path(r) for r in roots if f.is_relative_to(r))
            rel = f.relative_to(root).as_posix()
            hashes = file_hashes(hash_target, hash_cache) if do_hash else {}
            title, region = title_from_name(f.name)
            gid = hashes["sha1"][:16] if do_hash else hashlib.sha1(f"{lib_id}:{rel}".encode()).hexdigest()[:16]
            if gid in by_hash:                       # dedupe: same content, another path
                by_hash[gid].source_paths.append(str(f))
                continue
            core, _ = systems.core_for(platform_)
            by_hash[gid] = CatalogEntry(
                game_id=gid, title=title, alt_title=meta.get("title") if meta.get("title", "").lower() != title.lower() else None,
                platform=platform_, platform_confidence=conf,
                region=region or meta.get("region_code"), serial=meta.get("serial"), source_paths=[str(f)],
                library=lib_id, rel_path=rel, system=platform_, collections=[lib_id] if lib_id else [], core=core,
                hashes=hashes, size=f.stat().st_size, format=ext.lstrip("."),
                runtimes={platform_: runtimes[platform_]} if platform_ in runtimes else
                         ({f"retroarch/{core}": "auto-install"} if core else {}),
                launch={"kind": "emulator", "platform": platform_, "path": str(f),
                        **({"archive_member": archive} if archive else {})}, profile_id=gid)
        except OSError as e:
            problems.append(f"{f}: {e}")
    return list(by_hash.values()), problems


# --- HyperSpin / Attract-Mode ----------------------------------------------------------------

def parse_attract_cfg(text: str) -> dict:
    """emulators/<name>.cfg: 'key   value' lines; 'artwork  <kind>  <path>' lines collected separately."""
    kv: dict = {"artwork": {}}
    for ln in text.splitlines():
        parts = ln.strip().split(None, 1)
        if len(parts) < 2 or parts[0].startswith("#"):
            continue
        if parts[0] == "artwork":
            kind_path = parts[1].split(None, 1)
            if len(kind_path) == 2:
                kv["artwork"][kind_path[0]] = kind_path[1].strip().replace("\\", "/")
        else:
            kv[parts[0]] = parts[1].strip()
    return kv


def parse_romlist(text: str) -> list[dict]:
    """romlists/<name>.txt: '#Name;Title;Emulator;CloneOf;Year;Manufacturer;Category;Players;...'"""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("#"):
        return []
    header = lines[0][1:].split(";")
    return [dict(zip(header, ln.split(";"))) for ln in lines[1:] if ln.strip() and not ln.startswith("#")]


def _exts(romext: str) -> tuple[set[str], bool]:
    exts, dirs = set(), False
    for e in romext.split(";"):
        e = e.strip().lower().rstrip(".")
        if e == "<dir>":
            dirs = True
        elif e:
            exts.add(e if e.startswith(".") else "." + e)
    return exts, dirs


def _listdir(path: Path, cache: dict) -> list[tuple[str, bool]]:
    """Cached directory listing keyed by path+mtime (SMB listings of 40k-file dirs take ~10s)."""
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return []
    key = f"ls2|{path}"
    if cache.get(key, {}).get("mtime") == mtime:
        return cache[key]["items"]
    items = []
    for e in os.scandir(path):
        d = e.is_dir()
        try:
            size = 0 if d else e.stat().st_size
        except OSError:
            size = 0
        items.append((e.name, d, size))
    cache[key] = {"mtime": mtime, "items": items}
    return items


def scan_attract(root: Path, lib_id: str, cache: dict | None = None,
                 progress=lambda msg: None) -> tuple[list[CatalogEntry], list[str], dict]:
    """Index a HyperSpin/Attract-Mode tree from its emulator configs + romlists, read-only.

    One entry per physical ROM file; every collection listing it is recorded in `collections`.
    Arcade folders only include romlist-listed sets (unlisted zips there are BIOS/device/clone sets);
    other folders also include unlisted files, titled from the filename.
    """
    cache = {} if cache is None else cache
    root = Path(root)
    problems, games = [], {}
    stats = {"emulators": 0, "romlists": 0, "listed_missing": 0, "unlisted_added": 0, "unlisted_arcade_skipped": 0}
    emu_dir = root / "emulators"
    if not emu_dir.is_dir():
        return [], [f"not an Attract-Mode tree (no emulators/): {root}"], stats
    folder_owner: dict[str, tuple] = {}
    canon: dict[str, str] = {}
    sizes: dict[str, int] = {}
    for cfg_path in sorted(emu_dir.glob("*.cfg")):
        emu = cfg_path.stem
        cfg = parse_attract_cfg(cfg_path.read_text(errors="replace"))
        rompaths = [p.strip().replace("\\", "/").strip("/") for p in cfg.get("rompath", "").split(";") if p.strip()]
        if not rompaths:
            continue
        # SMB paths are case-insensitive: "collections/Mame/roms" and ".../MAME/roms" are one folder, one identity
        rompaths = [canon.setdefault(rp.lower(), rp) for rp in rompaths]
        stats["emulators"] += 1
        progress(f"{emu}")
        system = cfg.get("system") or emu
        # each ROM folder decides its own platform (a "Crash Bandicoot Collection" spans PS1, GBA, ... folders)
        cls = {rp: systems.classify(system, emu, rp)[:2] for rp in rompaths}
        exts, dirs = _exts(cfg.get("romext", ""))
        files: dict[str, tuple[str, str]] = {}
        listed_dirs: dict[str, tuple[str, str]] = {}   # romlist names that are folders (MAME CHD sets, PC/TeknoParrot games)
        for rp in rompaths:
            for name, is_dir, size in _listdir(root / rp, cache):
                stem, ext = os.path.splitext(name)
                if (is_dir and dirs) or (not is_dir and ext.lower() in exts):
                    files.setdefault(stem.lower(), (rp, name))
                    sizes[f"{rp}/{name}"] = size
                    k, own = f"{rp}/{name}", (emu, system, *cls[rp], cfg["artwork"])
                    # unlisted files belong to the folder's real system, not a franchise collection that also scans it
                    if k not in folder_owner or ("collection" in folder_owner[k][1].lower() and "collection" not in system.lower()):
                        folder_owner[k] = own
                elif is_dir:
                    listed_dirs.setdefault(name.lower(), (rp, name))
        rl = root / "romlists" / f"{emu}.txt"
        rows = parse_romlist(rl.read_text(errors="replace")) if rl.exists() else []
        stats["romlists"] += bool(rows)
        for row in rows:
            key = row.get("Name", "").lower()
            hit = files.get(key) or listed_dirs.get(key)
            if not hit:
                stats["listed_missing"] += 1
                continue
            _add(games, lib_id, hit, emu, system, *cls[hit[0]], cfg["artwork"], row)
    for key, (emu, system, plat, core, art) in folder_owner.items():
        rp, name = key.rsplit("/", 1)
        gid = _gid(lib_id, key)
        if gid in games:
            continue
        if plat.startswith("arcade"):
            stats["unlisted_arcade_skipped"] += 1
            continue
        stats["unlisted_added"] += 1
        _add(games, lib_id, (rp, name), emu, system, plat, core, art, None)
    for e in games.values():
        e.size = sizes.get(e.rel_path, 0)
    return list(games.values()), problems, stats


def _gid(lib_id: str, rel: str) -> str:
    return hashlib.sha1(f"{lib_id}:{rel}".encode()).hexdigest()[:16]


ART_KINDS = {"boxart": "boxart", "snap": "snap", "wheel": "logo", "cartart": "cartart"}   # kind -> sibling folder


def _media(rp: str, stem: str, artwork: dict, into: dict[str, list[str]]):
    """Candidate art stems: the collection's configured artwork dirs, then folders beside the physical ROM folder
    (virtual MAME collections have empty art dirs; the real art is in collections/MAME/...)."""
    parent = rp.rsplit("/", 1)[0] if "/" in rp else rp
    if parent.lower().endswith("/roms"):                     # PacMAME/roms/roms
        parent = parent.rsplit("/", 1)[0]
    cands = [(("wheel" if k == "wheel" else k), f"{v}/{stem}") for k, v in artwork.items() if k in ART_KINDS]
    cands += [(k, f"{parent}/{d}/{stem}") for k, d in ART_KINDS.items()]
    for kind, path in cands:
        lst = into.setdefault(kind, [])
        if path.lower() not in (p.lower() for p in lst):
            lst.append(path)


def _add(games, lib_id, hit, emu, system, plat, core, artwork, row):
    rp, name = hit
    rel = f"{rp}/{name}"
    gid = _gid(lib_id, rel)
    stem = os.path.splitext(name)[0]
    if gid in games:
        if emu not in games[gid].collections:
            games[gid].collections.append(emu)
            _media(rp, stem, artwork, games[gid].media)
        return
    media: dict[str, list[str]] = {}
    _media(rp, stem, artwork, media)
    title, region = title_from_name(name)
    row = row or {}
    games[gid] = CatalogEntry(
        game_id=gid, title=(row.get("Title") or title).strip().strip('"').strip() or title, platform=plat,
        platform_confidence="collection",
        region=region, source_paths=[rel], library=lib_id, rel_path=rel, system=system, collections=[emu], core=core,
        year=row.get("Year") or None, manufacturer=row.get("Manufacturer") or None, category=row.get("Category") or None,
        clone_of=row.get("CloneOf") or None, players=row.get("Players") or None,
        media=media, format=os.path.splitext(name)[1].lstrip(".").lower() or "dir",
        runtimes=({f"retroarch/{core}": "auto-install"} if core else {}) | {"rocketlauncher": "windows-node"},
        launch={"kind": "attract", "library": lib_id, "rel_path": rel, "emulator": emu, "name": stem},
        profile_id=gid)


# --- Steam ---------------------------------------------------------------------------------

def parse_vdf(text: str) -> dict:
    """Minimal Valve KeyValues parser (text VDF/ACF)."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    def block(i):
        d = {}
        while i < len(tokens):
            s, brace = tokens[i]
            if brace == "}":
                return d, i + 1
            key = s
            nxt_s, nxt_brace = tokens[i + 1]
            if nxt_brace == "{":
                d[key], i = block(i + 2)
            else:
                d[key], i = nxt_s, i + 2
        return d, i
    return block(0)[0]


def scan_steam(steam_root: Path) -> tuple[list[CatalogEntry], list[str]]:
    lf = Path(steam_root) / "steamapps" / "libraryfolders.vdf"
    if not lf.exists():
        return [], [f"no libraryfolders.vdf under {steam_root}"]
    libs = [Path(v["path"]) for v in parse_vdf(lf.read_text(errors="replace")).get("libraryfolders", {}).values()
            if isinstance(v, dict) and "path" in v]
    entries, problems = [], []
    for lib in libs:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            try:
                st = parse_vdf(acf.read_text(errors="replace"))["AppState"]
            except (KeyError, OSError) as e:
                problems.append(f"{acf}: {e}")
                continue
            gid = f"steam-{st['appid']}"
            entries.append(CatalogEntry(
                game_id=gid, title=st.get("name", gid), platform="pc_steam", platform_confidence="manifest",
                source_paths=[str(lib / "steamapps" / "common" / st.get("installdir", ""))],
                hashes={"steam_buildid": st.get("buildid", "")}, size=int(st.get("SizeOnDisk", 0) or 0),
                format="steam_app", runtimes={"steam": "configured"},
                launch={"kind": "steam", "appid": st["appid"]}, profile_id=gid))
    return entries, problems


# --- bounded staging cache -----------------------------------------------------------------

def stage(src: Path, game_id: str, config: Config, progress=None) -> dict:
    """Copy a source file into the LRU cache (never touching the original). Returns a staging receipt.
    progress(done_bytes, total_bytes) is called while copying."""
    cache = config.cache
    try:
        inside = Path(src).resolve().is_relative_to(Path(cache).resolve())
    except OSError:
        inside = False
    if inside:              # a built file mod (or anything already on the local disk): use it in place. Copying it to
        os.utime(src)       # <cache>/<game>/<name> made every mod of a game collide with the plain game's staged copy.
        return {"src": str(src), "dst": str(src), "size": Path(src).stat().st_size, "copied": False,
                "sha1": file_hashes(Path(src), {})["sha1"],
                "staged_at": time.time(), "evicted": [], "in_cache": True}
    dst = cache / game_id / src.name
    copied = not dst.exists() or dst.stat().st_size != src.stat().st_size
    if copied:
        dst.parent.mkdir(parents=True, exist_ok=True)
        total, done, tmp = src.stat().st_size, 0, dst.with_suffix(dst.suffix + ".part")
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while chunk := fi.read(8 << 20):
                fo.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        shutil.copystat(src, tmp)
        tmp.replace(dst)
    os.utime(dst)                                         # mtime = last use, drives LRU
    evicted = evict(cache, int(config.cache_limit * 1024**3), keep=dst)
    return {"src": str(src), "dst": str(dst), "size": dst.stat().st_size, "copied": copied,
            "sha1": file_hashes(dst, {})["sha1"], "staged_at": time.time(), "evicted": evicted}


def evict(cache: Path, limit: int, keep: Path | None = None) -> list[str]:
    mods = (cache / "mods").resolve()                     # built mods are not a cache of anything: never evict them
    files = sorted((p for p in cache.rglob("*") if p.is_file() and not p.resolve().is_relative_to(mods)), key=lambda p: p.stat().st_mtime)
    total, evicted = sum(p.stat().st_size for p in files), []
    for p in files:
        if total <= limit:
            break
        if keep and p == keep:
            continue
        total -= p.stat().st_size
        p.unlink()
        evicted.append(str(p))
    return evicted


def cache_hash_db(config: Config) -> tuple[dict, Path]:
    p = config.data_dir / "hash_cache.json"
    return (json.loads(p.read_text()) if p.exists() else {}), p
