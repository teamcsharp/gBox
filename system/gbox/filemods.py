"""File-replacement mods for folder games (PS3 disc folders and the like) without touching the original.

A local base copy of the game is made once (cache/modbase/<game_id>); each mod is a tree of hard links to it in which
only the replaced/patched files are real copies (cache/mods/<game_id>/<mod>), so a mod costs only its own files.
Rollback = delete the mod folder. Launch with `launch_game(mod=<name>)`.
"""
import json
import os
import shutil
import time
import threading
import hashlib
import re
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

_FETCH_LOCKS = {}
_FETCH_GUARD = threading.Lock()
_HASHES = {}


def game_root(rom: Path) -> Path:
    """The folder that makes up the game: a PS3 disc folder (…/PS3_GAME/USRDIR/EBOOT.BIN -> disc root), else the rom's folder."""
    p = Path(rom)
    if p.name.upper() == "EBOOT.BIN" and p.parent.name.upper() == "USRDIR" and p.parents[1].name.upper() == "PS3_GAME":
        return p.parents[2]
    return p.parent


def base_dir(cfg, game_id: str) -> Path:
    return Path(cfg.cache) / "modbase" / game_id


def mod_dir(cfg, game_id: str, name: str) -> Path:
    for value in (game_id, name):
        if not isinstance(value, str) or not value or value in (".", "..") or any(c in value for c in "/\\:\0"):
            raise ValueError("game and mod names must be single cache-folder components")
    root = (Path(cfg.cache) / "mods").resolve()
    out = root / game_id / name
    if not out.resolve().is_relative_to((root / game_id).resolve()):   # (root/game_id may link to the cold tier)
        raise ValueError("mod folder must stay inside its game cache")
    return out


def ensure_base(cfg, game_id: str, rom: Path, progress=None) -> Path:
    base, src = base_dir(cfg, game_id), game_root(rom)
    done = base / ".gbox-base-complete"
    if done.exists():
        return base
    files = [f for f in src.rglob("*") if f.is_file()]
    total, copied = sum(f.stat().st_size for f in files) or 1, 0
    for f in files:
        t = base / f.relative_to(src)
        if not t.exists() or t.stat().st_size != f.stat().st_size:
            t.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, t)
        copied += f.stat().st_size
        if progress:
            progress(5 + 70 * copied / total, f"base copy {copied / 2**30:.1f} / {total / 2**30:.1f} GB")
    done.write_text(str(src))
    return base


def build(cfg, game_id: str, rom: Path, name: str, changes: dict, progress=None) -> dict:
    """changes: {relative path: {"from": local file} | {"bytes": raw} | {"patch": [{"offset": int, "hex": str}]}}."""
    base = ensure_base(cfg, game_id, rom, progress)
    out = mod_dir(cfg, game_id, name)
    if out.exists():
        shutil.rmtree(out)
    norm = {Path(k).as_posix().lower(): (k, v) for k, v in changes.items()}
    applied, rows = [], []
    for f in base.rglob("*"):
        if f.name == ".gbox-base-complete":
            continue
        rel = f.relative_to(base)
        t = out / rel
        if f.is_dir():
            t.mkdir(parents=True, exist_ok=True)
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        hit = norm.pop(rel.as_posix().lower(), None)
        if not hit:
            os.link(f, t)                                  # shared with the base copy: no extra space
            continue
        key, ch = hit
        if "from" in ch:
            shutil.copy2(ch["from"], t)
        elif "bytes" in ch:
            t.write_bytes(ch["bytes"])
        else:
            data = bytearray(f.read_bytes())
            for p in ch.get("patch", []):
                off, b = int(str(p["offset"]), 0), bytes.fromhex(p["hex"])
                if off + len(b) > len(data):
                    raise ValueError(f"{key}: patch at {off:#x} runs past the end of the file")
                data[off:off + len(b)] = b
            t.write_bytes(bytes(data))
        applied.append(key)
        rows.append(_change_row(key, ch, t, f.stat().st_size))
    for key, ch in norm.values():                          # new files the game didn't have
        t = out / key
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ch["from"], t) if "from" in ch else t.write_bytes(ch.get("bytes", b""))
        applied.append(key + " (new)")
        rows.append(_change_row(key, ch, t, None, new=True))
    (out / ".gbox-mod.json").write_text(json.dumps(_record({"name": name, "game_id": game_id, "files": applied,
                                                            "built": time.time()}, rows)))
    return {"mod": name, "dir": str(out), "files": applied}


def _change_row(key: str, ch: dict, written: Path, base_size: int | None, new: bool = False) -> dict:
    """One changed file for the build record (gbox.build_record.file_changes): what changed and the sizes."""
    from . import build_record
    try:
        size = written.stat().st_size
    except OSError:
        size = None
    change = "new" if new else "patched" if ch.get("patch") and not ("from" in ch or "bytes" in ch) else "replaced"
    return build_record.file_change(key, change, size, base_size, ch.get("patch") if change == "patched" else None)


def _record(meta: dict, rows: list[dict]) -> dict:
    """The marker with the per-file changes; byte patches make it a ROM hack in the Builds view."""
    from . import build_record
    kind = "romhack" if any(r["change"] == "patched" or r.get("patches") for r in rows) else "file"
    return build_record.stamp(meta, kind=kind, file_changes=rows)


def is_folder_game(rom: Path) -> bool:
    return Path(rom).name.upper() == "EBOOT.BIN"


def gcz_to_iso(src: Path, dst: Path, progress=None):
    """Dolphin GCZ -> plain disc image (header, block pointers with bit 63 = stored, zlib blocks)."""
    import struct
    import zlib
    with open(src, "rb") as f, open(dst, "wb") as out:
        magic, _sub, csize, dsize, bsize, n = struct.unpack("<IIQQII", f.read(32))
        if magic != 0xB10BC001:
            raise ValueError("not a GCZ image")
        ptrs = struct.unpack(f"<{n}Q", f.read(8 * n))
        base = 32 + 12 * n
        for i, p in enumerate(ptrs):
            start = p & ~(1 << 63)
            end = (ptrs[i + 1] & ~(1 << 63)) if i + 1 < n else csize
            f.seek(base + start)
            raw = f.read(end - start)
            out.write(raw if p >> 63 else zlib.decompress(raw))
            if progress and i % 512 == 0:
                progress(5 + 60 * i / n, f"decompressing {Path(src).name}")
        out.truncate(dsize)


def build_image(cfg, game_id: str, rom: Path, name: str, changes: dict, progress=None) -> dict:
    """Single-image games: copy the image (GCZ -> ISO) and apply changes. Keys: "@image" = byte patches on the image;
    a GameCube disc path (e.g. "PSO/ItemPMT.prs") = replace (in its slot when it fits, else moved after the last
    file; the FST entry gets the new offset/size)
    or patch inside that file."""
    rom = Path(rom)
    out_dir = mod_dir(cfg, game_id, name)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    img = out_dir / (rom.stem + (".iso" if rom.suffix.lower() == ".gcz" else rom.suffix))
    if rom.suffix.lower() == ".gcz":
        gcz_to_iso(rom, img, progress)
    else:
        shutil.copy2(rom, img)
    from . import build_record
    applied, disc, rows = [], None, []
    with open(img, "r+b") as f:
        for key, ch in changes.items():
            if key == "@image":
                for p in ch.get("patch", []):
                    f.seek(int(str(p["offset"]), 0))
                    f.write(bytes.fromhex(p["hex"]))
                applied.append("@image")
                rows.append(build_record.file_change(img.name, "patched", None, None, ch.get("patch"), "byte patches on the image"))
                continue
            if disc is None:
                from .gcdisc import GCDisc
                disc = GCDisc(img)
            if key not in disc.files:
                raise ValueError(f"{key} is not on this disc")
            off, size = disc.files[key]
            if "patch" in ch:
                for p in ch["patch"]:
                    o, b = int(str(p["offset"]), 0), bytes.fromhex(p["hex"])
                    if o + len(b) > size:
                        raise ValueError(f"{key}: patch at {o:#x} runs past the end of the file")
                    f.seek(off + o)
                    f.write(b)
            else:
                data = Path(ch["from"]).read_bytes() if "from" in ch else ch["bytes"]
                from .romexport import gc_put_file          # in its slot, or moved to free space after the last file
                gc_put_file(f, disc, key, data)
            applied.append(key)
            rows.append(build_record.file_change(key, "patched" if "patch" in ch else "replaced",
                                                 size if "patch" in ch else len(data), size, ch.get("patch")))
    if disc is not None:
        disc.f.close()
    (out_dir / ".gbox-mod.json").write_text(json.dumps(_record({"name": name, "game_id": game_id, "image": img.name,
                                                                "files": applied, "built": time.time()}, rows)))
    return {"mod": name, "dir": str(out_dir), "image": str(img), "files": applied}


def launch_path(cfg, game_id: str, rom: Path, name: str) -> Path:
    out = mod_dir(cfg, game_id, name)
    marker = _file_path(out, ".gbox-mod.json")
    if not marker.exists():
        raise ValueError(f"no built mod {name!r} for this game")
    meta = json.loads(marker.read_text())
    if meta.get("launchable") is False:                # universal-modder staged files (um_mod): an overlay, not a game copy
        raise ValueError(f"mod {name!r} is a staged file set ({meta.get('kind', 'files')}), not a launchable copy of the "
                         "game: install its files with the game's mod loader (see its README)")
    if meta.get("image"):
        return _file_path(out, meta["image"])
    return out / Path(rom).relative_to(game_root(rom))


def _hash_sidecar(d: Path) -> Path:
    """Digests of a mod folder's files, kept beside it (not inside: the folder's file list is its manifest), so a
    restart doesn't re-hash a multi-GB disc image before the first launch can fetch the manifest."""
    return d.parent / f".{d.name}.sha256.json"


def _files(d: Path, hashes: bool = False) -> list[dict]:
    files, saved, dirty = [], {}, False
    if hashes:
        try:
            saved = json.loads(_hash_sidecar(d).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
    for p in sorted(d.rglob('*')):
        if not p.is_file() or p.name.endswith('.part'): continue
        stat = p.stat(); item = {'path': p.relative_to(d).as_posix(), 'size': stat.st_size}
        if hashes:
            key = (str(p.resolve()), stat.st_mtime_ns, stat.st_size)
            row = saved.get(item['path'])
            if key not in _HASHES and isinstance(row, list) and row[:2] == [stat.st_mtime_ns, stat.st_size]:
                _HASHES[key] = row[2]
            if key not in _HASHES:
                with p.open('rb') as stream: _HASHES[key] = hashlib.file_digest(stream, 'sha256').hexdigest()
            item['sha256'] = _HASHES[key]
            if row != [stat.st_mtime_ns, stat.st_size, item['sha256']]:
                saved[item['path']], dirty = [stat.st_mtime_ns, stat.st_size, item['sha256']], True
        files.append(item)
    if dirty:
        try:
            tmp = _hash_sidecar(d).with_suffix('.tmp')
            tmp.write_text(json.dumps(saved), encoding='utf-8')
            os.replace(tmp, _hash_sidecar(d))
        except OSError:
            pass                                    # a read-only cache still answers, it just re-hashes next restart
    return files


STAGED_SEP = "~"                     # <mod>~<build>: a rebuilt mod staged beside a copy the running game holds open
STAGED_MARK = ".gbox-staged-of"     # inside such a folder: the collection name it mirrors (never pushed back or listed)


class ModInUse(PermissionError):
    """A file of the mod can't be replaced because a running emulator holds it open (Windows WinError 5/32)."""


def fetch(cfg, server: str, headers: dict, game_id: str, name: str, progress=None, dest: Path | None = None) -> bool:
    key = str((dest or mod_dir(cfg, game_id, name)).resolve())
    with _FETCH_GUARD:
        lock = _FETCH_LOCKS.setdefault(key, threading.Lock())
    with lock:
        return _fetch(cfg, server, headers, game_id, name, progress, dest=dest)


def _build_key(files: list[dict]) -> str:
    # Metadata is part of a build: equal track bytes with a different image or
    # provenance must never reuse the previous manifest.
    return hashlib.sha256(json.dumps(sorted(files, key=lambda f: f["path"]),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]


def _file_path(root: Path, path: str) -> Path:
    if (not isinstance(path, str) or not path or "\\" in path or ":" in path or "\0" in path or
            PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute() or
            any(p in ("", ".", "..") for p in path.split("/"))):
        raise ValueError("mod file must stay inside its cache folder")
    out = root / path
    if not out.resolve().is_relative_to(root.resolve()) or out.is_symlink():
        raise ValueError("mod file must stay inside its cache folder")
    return out


def _manifest(files, out: Path) -> list[dict]:
    if not isinstance(files, list):
        raise ValueError("mod collection must provide a file manifest")
    clean, seen = [], set()
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("invalid mod file manifest")
        path, size, digest = row.get("path"), row.get("size"), row.get("sha256")
        _file_path(out, path)
        key = path.casefold()  # Workers can have case-insensitive filesystems.
        if key in seen or path == STAGED_MARK or path.endswith(".part"):
            raise ValueError("duplicate or reserved mod manifest path")
        if type(size) is not int or size < 0 or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest):
            raise ValueError("mod manifest requires exact sizes and SHA256 hashes")
        seen.add(key)
        clean.append({"path": path, "size": size, "sha256": digest})
    if ".gbox-mod.json" not in {f["path"] for f in clean}:
        raise ValueError("mod collection omitted its completed metadata marker")
    return clean


def _matches(out: Path, files: list[dict]) -> bool:
    expected = {row["path"].casefold() for row in files}
    actual = set()
    for path in out.rglob("*"):
        if path.is_symlink():
            return False
        if path.is_file():
            relative = path.relative_to(out).as_posix()
            if relative == STAGED_MARK or relative.endswith(".part"):
                continue  # Local provenance/resumable downloads are not game assets.
            actual.add(relative.casefold())
    if actual != expected:
        return False
    for row in files:
        path = _file_path(out, row["path"])
        if not path.is_file() or path.stat().st_size != row["size"] or _sha(path) != row["sha256"]:
            return False
    return True


def stage(cfg, server: str, headers: dict, game_id: str, name: str, progress=None) -> str:
    """Prepare a pinned build without modifying any existing game copy or checkpoint.

    Changed builds go beside the previous folder on every OS, before probing any
    file lock. Old stages are retained because an open handle cannot prove that a
    game, rollback, or another worker no longer needs them.
    """
    import httpx
    src = mod_dir(cfg, game_id, name)
    key = str(src.resolve())
    with _FETCH_GUARD:
        lock = _FETCH_LOCKS.setdefault(key, threading.Lock())
    with lock:
        if progress:
            progress(20, f"Checking build {name} against the central collection (Spark)")
        # the Spark hashes a new or just-restarted build's disc image (1+ GB on its HDD) before answering
        r = httpx.get(f"{server}/api/modfiles/{game_id}/{name}", headers=headers, timeout=900)
        if r.status_code == 404:
            return name  # Local-only mods still have a local completed marker.
        r.raise_for_status()
        files = _manifest(r.json().get("files"), src)
        if src.exists() and _matches(src, files):
            return name
        alias = f"{name}{STAGED_SEP}{_build_key(files)}" if src.exists() else name
        out = mod_dir(cfg, game_id, alias)
        if out.exists():
            if ((out / STAGED_MARK).is_file() and (out / STAGED_MARK).read_text() == name and _matches(out, files)):
                return alias
            # A partial/corrupt/colliding folder may also be live; never repair it
            # in place or erase its metadata. Claim a fresh exclusive sibling.
            alias += "-" + uuid.uuid4().hex[:12]
            out = mod_dir(cfg, game_id, alias)
        out.mkdir(parents=True, exist_ok=False)
        if alias != name:
            (out / STAGED_MARK).write_text(name)
        if progress:
            progress(20, f"Preserving the existing game copy: staging the new build as {alias}")
        for row in files:
            if row["path"] == ".gbox-mod.json":
                continue
            have, dst = _file_path(src, row["path"]), _file_path(out, row["path"])
            if have.is_file() and have.stat().st_size == row["size"] and _sha(have) == row["sha256"]:
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(have, dst)  # No hard-link alias to an independently rebuilt source.
                except OSError:
                    pass  # The pinned download can still supply a read-locked resource.
        _fetch(cfg, server, headers, game_id, name, progress, dest=out, files=files)
        if not _matches(out, files):
            raise RuntimeError("prepared mod does not match its pinned build manifest")
        return alias


def _sha(p: Path) -> str:
    with p.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _replace(tmp: Path, dst: Path, out: Path):
    try:
        os.replace(tmp, dst)
    except PermissionError as e:
        if not dst.exists():
            raise
        raise ModInUse(e.errno, f"{dst.name} is open in a running game", str(dst)) from e


_FETCH_RETRIES = 5                     # resume attempts after a transient drop on a multi-GB mod download
_FETCH_RETRY_DELAY = 2.0               # seconds to wait before each resume attempt


def _download_file(cfg, server, headers, game_id, name, row, tmp, dst, out, progress,
                   base, total, reported) -> None:
    """Download one manifest file into `tmp` (a `.part` beside its real path), resuming a partial
    download and retrying transient transport drops. The collection serves multi-GB images and can
    close a stream before its Content-Length is fully sent (`httpx.RemoteProtocolError`); resuming
    from the `.part` offset recovers without re-fetching the bytes already on disk."""
    import httpx
    size, digest = row["size"], row.get("sha256")
    reason = "incomplete"
    for _ in range(_FETCH_RETRIES + 1):
        offset = tmp.stat().st_size if tmp.exists() else 0
        if offset > size:
            tmp.unlink(missing_ok=True)
            offset = 0
        if offset == size:
            with tmp.open("rb") as stream:
                valid = not digest or hashlib.file_digest(stream, "sha256").hexdigest() == digest
            if valid:
                _replace(tmp, dst, out)
                return
            tmp.unlink(missing_ok=True)
            offset = 0
        request_headers = dict(headers)
        if offset:
            request_headers["Range"] = f"bytes={offset}-"
        written = offset
        try:
            with httpx.stream("GET", f"{server}/api/modfiles/{game_id}/{name}/file/{row['path']}",
                              headers=request_headers, timeout=httpx.Timeout(60, connect=30)) as s:
                s.raise_for_status()
                if offset and s.status_code == 206:
                    if not s.headers.get("Content-Range", "").startswith(f"bytes {offset}-"):
                        raise ValueError("mod server returned an unexpected resume range")
                else:
                    offset = 0
                written = offset
                with open(tmp, "ab" if offset else "wb") as fh:
                    for chunk in s.iter_bytes(1 << 20):
                        fh.write(chunk)
                        written += len(chunk)
                        now = time.monotonic()
                        if progress and now - reported[0] >= .5:
                            progress(20 + round(8 * (base + written) / total, 2),
                                     f"Fetching mod {name} from the collection: {(base + written) >> 20}/{total >> 20} MB")
                            reported[0] = now
        except httpx.TransportError:
            reason = "incomplete"
            time.sleep(_FETCH_RETRY_DELAY)
            continue
        if tmp.stat().st_size != size:
            reason = "incomplete"
            time.sleep(_FETCH_RETRY_DELAY)
            continue
        if digest:
            with tmp.open("rb") as stream:
                valid = hashlib.file_digest(stream, "sha256").hexdigest() == digest
            if not valid:
                tmp.unlink(missing_ok=True)
                reason = "checksum"
                time.sleep(_FETCH_RETRY_DELAY)
                continue
        _replace(tmp, dst, out)
        return
    raise (ValueError(f"Mod checksum mismatch: {row['path']}") if reason == "checksum"
           else ValueError(f"incomplete mod transfer: {row['path']}"))


def _fetch(cfg, server: str, headers: dict, game_id: str, name: str, progress=None, dest: Path | None = None,
           files: list[dict] | None = None) -> bool:
    """A mod built elsewhere: download it from the central collection (the Spark) into this machine's cache. Resumable:
    files already here with the right size are kept, and a dropped transfer resumes from its `.part`. Returns False if
    the collection doesn't have it either."""
    import httpx
    out = dest or mod_dir(cfg, game_id, name)
    if files is None:
        r = httpx.get(f"{server}/api/modfiles/{game_id}/{name}", headers=headers, timeout=900)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        files = r.json()["files"]
    # Check every path before creating even the first partial download.
    for row in files:
        dst = _file_path(out, row["path"])
        _file_path(out, row["path"] + ".part")
    total, done = sum(f["size"] for f in files) or 1, 0
    reported = [0.0]
    for f in sorted(files, key=lambda f: f["path"] == ".gbox-mod.json"):    # the marker last: a half copy isn't a mod
        dst = _file_path(out, f["path"])
        if dst.exists() and dst.stat().st_size == f["size"]:
            with dst.open('rb') as stream:
                valid = not f.get('sha256') or hashlib.file_digest(stream, 'sha256').hexdigest() == f['sha256']
            if valid:
                done += f["size"]; continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        _download_file(cfg, server, headers, game_id, name, f, tmp, dst, out, progress,
                       base=done, total=total, reported=reported)
        done += f["size"]
    return (out / ".gbox-mod.json").exists()


def push_missing(cfg, server: str, headers: dict) -> list[str]:
    """Mods this machine built that the central collection lacks: upload them (worker start, in the background)."""
    import httpx
    sent, root = [], Path(cfg.cache) / "mods"
    if not root.exists():
        return sent
    for meta in root.glob("*/*/.gbox-mod.json"):
        d, game_id, name = meta.parent, meta.parent.parent.name, meta.parent.name
        if (d / STAGED_MARK).exists():
            continue                                       # a local staging copy of a collection mod, not a new build
        r = httpx.get(f"{server}/api/modfiles/{game_id}/{name}", headers=headers, timeout=900)
        have = {f["path"]: f["size"] for f in r.json().get("files", [])} if r.status_code == 200 else {}
        todo = [f for f in _files(d) if have.get(f["path"]) != f["size"] and not f["path"].endswith(".part")]
        for f in sorted(todo, key=lambda f: f["path"] == ".gbox-mod.json"):
            with open(d / f["path"], "rb") as fh:
                httpx.put(f"{server}/api/modfiles/{game_id}/{name}/file/{f['path']}", content=fh, headers=headers,
                          timeout=None).raise_for_status()
        if todo:
            sent.append(f"{game_id}/{name}")
    return sent


LOCAL_MAX = 400                     # builds a worker reports with its heartbeat (newest first)
LOCAL_TTL = 60.0
_LOCAL_CACHE: dict = {}


def local_builds(cfg, now: float | None = None) -> list[dict]:
    """This machine's built mods, newest first: {game_id, name, built (marker mtime), staged_of?}. Two directory levels
    and one marker stat per build (no marker is read beyond a staging copy's tiny mark file); cached LOCAL_TTL s."""
    now = time.time() if now is None else now
    root = Path(cfg.cache) / "mods"
    hit = _LOCAL_CACHE.get(str(root))
    if hit and now - hit[0] < LOCAL_TTL:
        return hit[1]
    out = []
    try:
        games = [g for g in os.scandir(root) if g.is_dir(follow_symlinks=False)]
    except OSError:
        games = []
    for g in games:
        try:
            mods = list(os.scandir(g.path))
        except OSError:
            continue
        for m in mods:
            try:
                if not m.is_dir(follow_symlinks=False):
                    continue
                st = os.stat(os.path.join(m.path, ".gbox-mod.json"))
            except OSError:
                continue
            row = {"game_id": g.name, "name": m.name, "built": round(st.st_mtime, 1)}
            mark = Path(m.path) / STAGED_MARK
            if mark.is_file():
                try:
                    row["staged_of"] = mark.read_text(encoding="utf-8").strip()[:200]
                except OSError:
                    row["staged_of"] = m.name.split(STAGED_SEP)[0]
            elif STAGED_SEP in m.name:
                row["staged_of"] = m.name.split(STAGED_SEP)[0]
            out.append(row)
    out.sort(key=lambda r: -r["built"])
    out = out[:LOCAL_MAX]
    _LOCAL_CACHE[str(root)] = (now, out)
    return out


def list_mods(cfg, game_id: str) -> list[dict]:
    d = Path(cfg.cache) / "mods" / game_id
    return [json.loads((m / ".gbox-mod.json").read_text()) for m in sorted(d.iterdir())
            if (m / ".gbox-mod.json").exists() and not (m / STAGED_MARK).exists()] if d.exists() else []


def copies_of(cfg, game_id: str, name: str) -> list[str]:
    """This machine's folders of one build: the build itself and its staged copies (<name>~<build>, or a folder whose
    staging mark names it). Never the base copy (modbase/) or another build."""
    root = Path(cfg.cache) / "mods" / game_id
    out = []
    try:
        entries = list(os.scandir(root))
    except OSError:
        return out
    for e in entries:
        if not e.is_dir(follow_symlinks=False):
            continue
        mark = Path(e.path) / STAGED_MARK
        try:
            of = mark.read_text(encoding="utf-8").strip() if mark.is_file() else ""
        except OSError:
            of = ""
        if e.name == name or e.name.startswith(name + STAGED_SEP) or of == name:
            out.append(e.name)
    return sorted(out, key=lambda n: (n != name, n))


def delete_build(cfg, game_id: str, name: str, in_use=()) -> dict:
    """Delete one build's local copies (Builds ▸ Delete, file_mod op=delete_build): every staged copy too, with their
    hash sidecars. Refuses (ModInUse) while a running game uses any of them (in_use: the mod folder names running
    sessions hold); a folder a process still holds open is left whole and reported."""
    names = copies_of(cfg, game_id, name)
    busy = sorted(set(names) & set(in_use or ()))
    if busy:
        raise ModInUse(16, f"{name} is in use by a running game ({', '.join(busy)}): stop that game first, then delete it")
    removed, errors = [], []
    for n in names:
        out = mod_dir(cfg, game_id, n)
        try:
            from .build_retention import linked
            root = Path(cfg.cache).resolve() / 'mods'
            if (linked(root) or linked(out.parent) or linked(out) or not out.resolve().is_relative_to(root.resolve())
                    or any(linked(p) for p in out.rglob('*'))):
                raise OSError('refusing deletion through a linked build path')
            shutil.rmtree(out)
            removed.append(n)
        except FileNotFoundError:
            continue
        except OSError as e:
            errors.append(f"{n}: {e}")
            continue
        try:
            _hash_sidecar(out).unlink(missing_ok=True)
        except OSError:
            pass
    _LOCAL_CACHE.clear()                             # the next heartbeat reports the build gone
    return {"removed": removed, "errors": errors}


def remove(cfg, game_id: str, name: str) -> bool:
    out = mod_dir(cfg, game_id, name)
    if out.exists():
        shutil.rmtree(out)
        return True
    return False


def _selftest():
    import tempfile
    import types
    td = Path(tempfile.mkdtemp())
    src = td / "lib" / "Game" / "PS3_GAME" / "USRDIR"
    src.mkdir(parents=True)
    (src / "EBOOT.BIN").write_bytes(b"ELF0")
    (src / "data.bin").write_bytes(b"\x00\x01\x02\x03")
    cfg = types.SimpleNamespace(cache=td / "cache")
    r = build(cfg, "g1", src / "EBOOT.BIN", "test", {"PS3_GAME/USRDIR/data.bin": {"patch": [{"offset": 1, "hex": "ff"}]}})
    p = launch_path(cfg, "g1", src / "EBOOT.BIN", "test")
    assert p.read_bytes() == b"ELF0" and (p.parent / "data.bin").read_bytes() == b"\x00\xff\x02\x03"
    assert (src / "data.bin").read_bytes() == b"\x00\x01\x02\x03"                 # original untouched
    assert os.stat(p).st_nlink >= 2 and r["files"] == ["PS3_GAME/USRDIR/data.bin"] # unchanged files are hard links
    assert list_mods(cfg, "g1")[0]["name"] == "test" and remove(cfg, "g1", "test") and not list_mods(cfg, "g1")
    # single-file image: byte patch, original untouched
    rom = td / "lib" / "game.z64"
    rom.write_bytes(bytes(16))
    r = build_image(cfg, "g2", rom, "lives", {"@image": {"patch": [{"offset": "0x4", "hex": "6363"}]}})
    p = launch_path(cfg, "g2", rom, "lives")
    assert p.read_bytes()[4:6] == b"cc" and rom.read_bytes() == bytes(16)
    # GCZ -> ISO round trip (one stored block + one zlib block)
    import struct
    import zlib
    blocks = [b"A" * 32, b"B" * 32]
    c1, c2 = blocks[0], zlib.compress(blocks[1])
    gcz = td / "lib" / "t.gcz"
    gcz.write_bytes(struct.pack("<IIQQII", 0xB10BC001, 0, len(c1) + len(c2), 64, 32, 2) +
                    struct.pack("<QQ", (1 << 63) | 0, len(c1)) + bytes(8) + c1 + c2)
    gcz_to_iso(gcz, td / "t.iso")
    assert (td / "t.iso").read_bytes() == b"A" * 32 + b"B" * 32
    print("filemods selftest ok")


if __name__ == "__main__":
    _selftest()
