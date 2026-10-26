"""Two-tier node cache: a capped fast tier (NVMe) in front of a big slow tier (HDD), transparent to the rest of gBox.

config.cache (the hot dir) stays the one path every module builds on (Path(cfg.cache) / ...). The cold dir mirrors its
layout. A per-game *unit* lives in exactly one tier at a time:

  * on the hot tier its folders are real directories;
  * on the cold tier the hot path is a symlink to the cold copy, so every existing code path keeps working, just slower.

A unit is everything that hard-links together and belongs to one game: <gid>/, dc/<gid>/, gc/<gid>/, modbase/<gid>/,
mods/<gid>/ (each mod is a hard-link tree onto modbase, gbox/filemods.py) and romexport_base/<gid>/. Other top-level
folders (RE workspaces, sprite captures...) are one unit each, and characters_build/<child> (build scratch) is one unit
per child. A unit is copied with its hard links preserved, so mods never duplicate their base across the move.

Pinned on the hot tier, never demoted: the character and environment libraries (characters/, environments/,
characters_mirror/), top-level files (.gbox-staged.json and other indexes), and anything hidden. The built mods index
and asset index live in data_dir already. Markers (.gbox-mod.json) and hash sidecars (.<mod>.sha256.json) belong to
their mod folder; they move with the unit because a mod folder is checked to be one real tree (filemods._matches).

Moves:
  * demotion (hot -> cold) runs only while the node is idle (no game session, no job running on this worker, no stage
    copy in flight, for cache_tier_idle_minutes) and the unit was not touched for as long, least recently used first,
    until the hot tier is under hot_cache_limit_gb. A unit with a file open in any process is skipped. The copy runs
    at idle I/O priority, is verified (size + SHA-256 re-read from the cold disk), and gives way the moment the node
    gets busy or the unit is asked for.
  * promotion (cold -> hot) happens on access: a job naming the game (builds, writers, collect, ...) waits for it;
    a launch waits only when it fits in cache_tier_promote_wait_s, else the unit moves up once the node is idle again.
  * each move is journaled under <hot>/.gbox-tiers/journal, and the switch is an atomic renameat2(RENAME_EXCHANGE) of
    the real folder and the symlink. A crash leaves either the hot copy or the cold copy authoritative, never neither;
    start-up rolls every journal back (before the switch) or forward (after it).

docs/cache-tiers.md has the operator view, the migration and the deploy notes.
"""
from __future__ import annotations

import contextlib
import ctypes
import errno
import hashlib
import json
import os
import platform
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qsl, unquote

STATE_DIR = ".gbox-tiers"                     # under both roots: journal, staging, trash (and the state on the hot one)
MIGRATED = ".migrated-to-hot"                 # suffix of a cold original that was copied to the hot tier (kept, ignored)
STAGE_DB = ".gbox-staged.json"                # catalog.STAGE_DB: keys are absolute paths under the cache root
BUILT_MODS_INDEX = "built_mods_index.json"    # built_mods.INDEX_FILE: its "root" names the cache it indexed
PINNED_DIRS = ("characters", "environments", "characters_mirror")
GAME_CONTAINERS = ("dc", "gc", "modbase", "mods", "romexport_base")   # <container>/<gid> joins the unit <gid>
SPLIT_CONTAINERS = ("characters_build",)      # <container>/<child> is a unit of its own
BLOCK = 8 << 20
LOW_WATER = 0.9                               # a demotion pass stops once the hot tier is under this share of the cap
MOVES_KEPT = 40
USAGE_TTL_S = 300.0
NAMES_TTL_S = 30.0
TICK_S = 30.0
LAUNCH_TOOLS = ("launch_game",)
FAIL_BACKOFF_S = 6 * 3600                     # a unit whose background move failed is left alone this long
PINNED_BACKOFF_S = 600.0
SPACE_MARGIN = 2 << 30                        # a move needs its size plus this free on the target disk
MAX_PROMOTE_PER_JOB = 4                       # a job naming more units (a sweep, a batch) only marks them used
IS_LINUX = sys.platform.startswith("linux")

ACTIVE: "Tiers | None" = None
_INSTALL_LOCK = threading.Lock()


class Cancelled(Exception):
    """A background move gave way: the node got busy, or the unit was asked for."""


def _log(msg: str) -> None:
    print(f"gBox cache tiers: {msg}", flush=True)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


# ------------------------------------------------------------------------------------------------ filesystem helpers

def _link_target(p: Path) -> Path | None:
    try:
        t = os.readlink(p)
    except OSError:
        return None
    return Path(t[4:] if t.startswith("\\\\?\\") else t)


def _remove_link(p: Path) -> None:
    try:
        os.unlink(p)
    except (IsADirectoryError, PermissionError):      # Windows: a directory symlink goes with rmdir
        os.rmdir(p)


def _make_link(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(str(target), str(link), target_is_directory=target.is_dir())


def _rmtree(p: Path) -> None:
    if os.path.islink(p):
        _remove_link(p)
    elif p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif os.path.lexists(p):
        with contextlib.suppress(OSError):
            os.unlink(p)


def _aside(p: Path, suffix: str) -> Path:
    """Rename p to p<suffix> (or p<suffix>-<stamp> when taken); the new path."""
    dst = p.with_name(p.name + suffix)
    if os.path.lexists(dst):
        dst = p.with_name(f"{p.name}{suffix}-{_stamp()}")
    os.rename(p, dst)
    return dst


_RENAMEAT2 = None


def _exchange(a: Path, b: Path) -> bool:
    """Atomically swap two paths on one filesystem (Linux renameat2 RENAME_EXCHANGE); False where unsupported."""
    global _RENAMEAT2
    if not IS_LINUX:
        return False
    if _RENAMEAT2 is None:
        try:
            fn = ctypes.CDLL(None, use_errno=True).renameat2
            fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
            _RENAMEAT2 = fn
        except (OSError, AttributeError):
            _RENAMEAT2 = False
    if not _RENAMEAT2:
        return False
    if _RENAMEAT2(-100, os.fsencode(str(a)), -100, os.fsencode(str(b)), 2) == 0:
        return True
    e = ctypes.get_errno()
    if e in (errno.ENOSYS, errno.EINVAL, getattr(errno, "ENOTSUP", -1), getattr(errno, "EOPNOTSUPP", -1)):
        return False
    raise OSError(e, os.strerror(e), str(b))


def _io_priority(idle: bool) -> None:
    """This thread's disk priority: idle class for demotions, best-effort lowest otherwise (Linux; no-op elsewhere)."""
    if not IS_LINUX:
        return
    nr = {"aarch64": 30, "arm64": 30, "x86_64": 251}.get(platform.machine().lower())
    if not nr:
        return
    with contextlib.suppress(Exception):
        ctypes.CDLL(None, use_errno=True).syscall(nr, 1, threading.get_native_id(), (3 << 13) if idle else (2 << 13) | 7)


def _nice_thread(n: int = 10) -> None:
    if IS_LINUX:
        with contextlib.suppress(OSError, AttributeError):
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), n)


def open_files_under(roots: list[Path], limit: int = 3) -> list[str]:
    """Paths under roots that some process holds open, mapped or as its working dir (Linux /proc; [] elsewhere)."""
    if not IS_LINUX:
        return []
    prefixes = [os.path.realpath(r) for r in roots]

    def hit(t: str) -> bool:
        t = t.removesuffix(" (deleted)")
        return any(t == p or t.startswith(p + "/") for p in prefixes)
    found: list[str] = []
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return []
    for pid in pids:
        base = f"/proc/{pid}"
        got = None
        try:
            for fd in os.listdir(base + "/fd"):
                with contextlib.suppress(OSError):
                    t = os.readlink(f"{base}/fd/{fd}")
                    if hit(t):
                        got = t
                        break
        except OSError:
            continue
        if got is None:
            with contextlib.suppress(OSError):
                t = os.readlink(base + "/cwd")
                if hit(t):
                    got = t
        if got is None:
            with contextlib.suppress(OSError), open(base + "/maps", encoding="utf-8", errors="replace") as f:
                for line in f:
                    parts = line.rstrip("\n").split(None, 5)
                    if len(parts) == 6 and parts[5].startswith("/") and hit(parts[5]):
                        got = parts[5]
                        break
        if got is not None:
            found.append(f"pid {pid}: {got}")
            if len(found) >= limit:
                break
    return found


def _walk(base: Path, rel: str):
    """(rel path, kind) under base/rel without following symlinks; kind: 'dir' | 'file' | 'link'. Dirs come first."""
    top = base / rel
    if os.path.islink(top):
        yield rel, "link"
        return
    if top.is_file():
        yield rel, "file"
        return
    if not top.is_dir():
        return
    stack = [rel]
    while stack:
        r = stack.pop()
        yield r, "dir"
        try:
            entries = sorted(os.scandir(base / r), key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            child = f"{r}/{e.name}" if r else e.name
            try:
                if e.is_symlink():
                    yield child, "link"
                elif e.is_dir(follow_symlinks=False):
                    stack.append(child)
                elif e.is_file(follow_symlinks=False):
                    yield child, "file"
            except OSError:
                continue


def tree_size(base: Path, rels: list[str]) -> int:
    """Bytes under base/rels, each hard-linked file counted once, symlinks not followed."""
    seen, total = set(), 0
    for rel in rels:
        for r, kind in _walk(base, rel):
            if kind != "file":
                continue
            with contextlib.suppress(OSError):
                st = os.lstat(base / r)
                key = (st.st_dev, st.st_ino) if st.st_nlink > 1 else None
                if key in seen:
                    continue
                if key:
                    seen.add(key)
                total += st.st_size
    return total


def _sha256(p: Path, cancel=None, drop_cache: bool = False) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        if drop_cache and hasattr(os, "posix_fadvise"):          # read what the disk holds, not the page cache
            with contextlib.suppress(OSError):
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
        while chunk := f.read(BLOCK):
            if cancel:
                cancel()
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ the copier

class Copier:
    """Copy unit parts from src_root to dst_root with hard links preserved inside the set, catch up with late changes
    (delta passes), then verify the destination against what was read (file list, sizes, SHA-256 re-read).

    manifest: rel -> {"size", "mtime" (source ns), "sha", "dmtime" (destination ns), "link" (rel of the first path of
    a hard-linked inode or None)} for files, {"sym": target} for symlinks inside the unit."""

    def __init__(self, src_root: Path, dst_root: Path, parts: list[str], cancel=None, progress=None,
                 verify: str = "hash", drop_cache: bool = False):
        self.src_root, self.dst_root, self.parts = Path(src_root), Path(dst_root), list(parts)
        self.cancel, self.progress, self.verify_mode, self.drop_cache = cancel, progress, verify, drop_cache
        self.man: dict[str, dict] = {}
        self.links: dict[tuple, str] = {}
        self.done = 0
        self.total = 0
        self._dirs: list[tuple[str, os.stat_result]] = []
        self._reported = 0.0

    def check(self) -> None:
        if self.cancel:
            self.cancel()

    def _tick(self, n: int) -> None:
        self.done += n
        if self.progress and time.monotonic() - self._reported >= 1.0:
            self._reported = time.monotonic()
            self.progress(self.done, self.total)

    def run(self) -> dict:
        if not self.total:
            self.total = tree_size(self.src_root, self.parts)
        for p in self.parts:
            self._copy_part(p)
        for _ in range(4):                        # writes that landed while we copied
            if not self.delta():
                break
        else:
            raise RuntimeError("the unit kept changing while it was copied")
        self._dir_times()
        self.verify()
        return self.man

    def _copy_part(self, part: str) -> None:
        for rel, kind in _walk(self.src_root, part):
            self.check()
            src, dst = self.src_root / rel, self.dst_root / rel
            if kind == "dir":
                dst.mkdir(parents=True, exist_ok=True)
                with contextlib.suppress(OSError):
                    self._dirs.append((rel, os.lstat(src)))
            elif kind == "link":
                self._copy_link(rel)
            else:
                with contextlib.suppress(FileNotFoundError):        # deleted under us: the delta pass agrees
                    self._copy_file(rel, os.lstat(src), allow_link=True)

    def _copy_link(self, rel: str) -> None:
        target = os.readlink(self.src_root / rel)
        dst = self.dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(dst):
            _rmtree(dst)
        os.symlink(target, dst)
        self.man[rel] = {"sym": target}

    def _copy_file(self, rel: str, st: os.stat_result, allow_link: bool) -> None:
        src, dst = self.src_root / rel, self.dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(dst):
            os.unlink(dst)
        key = (st.st_dev, st.st_ino) if st.st_nlink > 1 else None
        first = self.links.get(key) if key else None
        if allow_link and first is not None and first in self.man:
            os.link(self.dst_root / first, dst)                  # the same inode on the destination too
            self.man[rel] = dict(self.man[first], link=first)
            return
        h = hashlib.sha256()
        with open(src, "rb") as fi, open(dst, "wb") as fo:
            while chunk := fi.read(BLOCK):
                self.check()
                h.update(chunk)
                fo.write(chunk)
                self._tick(len(chunk))
            fo.flush()
            os.fsync(fo.fileno())
        shutil.copystat(src, dst)
        self.man[rel] = {"size": st.st_size, "mtime": st.st_mtime_ns, "sha": h.hexdigest(),
                         "dmtime": os.stat(dst).st_mtime_ns, "link": None}
        if key and allow_link:
            self.links[key] = rel

    def delta(self) -> int:
        """Re-walk the source; copy what changed since its entry was copied, drop what went away. Changed paths."""
        seen, changed = set(), 0
        for p in self.parts:
            for rel, kind in _walk(self.src_root, p):
                self.check()
                if kind == "dir":
                    (self.dst_root / rel).mkdir(parents=True, exist_ok=True)
                    continue
                seen.add(rel)
                m = self.man.get(rel)
                if kind == "link":
                    with contextlib.suppress(OSError):
                        if m is None or m.get("sym") != os.readlink(self.src_root / rel):
                            self._copy_link(rel)
                            changed += 1
                    continue
                try:
                    st = os.lstat(self.src_root / rel)
                except FileNotFoundError:
                    seen.discard(rel)
                    continue
                if m is None or "sym" in m or m["size"] != st.st_size or m["mtime"] != st.st_mtime_ns:
                    self._copy_file(rel, st, allow_link=False)
                    changed += 1
        for rel in [r for r in self.man if r not in seen]:
            _rmtree(self.dst_root / rel)
            del self.man[rel]
            changed += 1
            for m in self.man.values():                  # other names of that inode keep their own copy
                if m.get("link") == rel:
                    m["link"] = None
        return changed

    def _dir_times(self) -> None:
        for rel, st in reversed(self._dirs):
            with contextlib.suppress(OSError):
                os.utime(self.dst_root / rel, ns=(st.st_atime_ns, st.st_mtime_ns))

    def verify(self) -> None:
        actual = set()
        for p in self.parts:
            for rel, kind in _walk(self.dst_root, p):
                if kind != "dir":
                    actual.add(rel)
        if actual != set(self.man):
            diff = sorted(actual ^ set(self.man))
            raise RuntimeError(f"copy verification failed: {len(diff)} path(s) differ, e.g. {diff[:3]}")
        for rel, m in self.man.items():
            self.check()
            dst = self.dst_root / rel
            if "sym" in m:
                if os.readlink(dst) != m["sym"]:
                    raise RuntimeError(f"copy verification failed: link {rel}")
                continue
            if os.lstat(dst).st_size != m["size"]:
                raise RuntimeError(f"copy verification failed: size of {rel}")
            if m.get("link"):
                if not os.path.samefile(dst, self.dst_root / m["link"]):
                    raise RuntimeError(f"copy verification failed: hard link {rel}")
                continue
            if self.verify_mode == "hash" and _sha256(dst, self.check, self.drop_cache) != m["sha"]:
                raise RuntimeError(f"copy verification failed: content of {rel}")

    def catch_up(self, old_of: dict[str, Path], new_root: Path) -> tuple[int, list[str]]:
        """After the switch: writes that reached the old location between the last delta pass and the switch are
        carried over, unless the new copy was itself written since (then the new copy wins and it is reported).
        old_of: unit part -> where its old copy is now."""
        moved, kept, seen = 0, [], set()
        for p, old in old_of.items():
            for rel, kind in _walk(old, ""):
                if kind != "file":
                    continue
                urel = f"{p}/{rel}" if rel else p
                seen.add(urel)
                src = old / rel if rel else old
                try:
                    st = os.lstat(src)
                except OSError:
                    continue
                m = self.man.get(urel)
                if m and "sym" not in m and m["size"] == st.st_size and m["mtime"] == st.st_mtime_ns:
                    continue
                dst = new_root / urel
                try:
                    cur = os.lstat(dst)
                except OSError:
                    cur = None
                if cur is not None and (m is None or "sym" in m or (cur.st_size, cur.st_mtime_ns) != (m["size"], m["dmtime"])):
                    kept.append(urel)
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".gbox-tier-tmp")
                shutil.copy2(src, tmp)
                os.replace(tmp, dst)
                moved += 1
        for urel, m in self.man.items():
            if urel in seen or "sym" in m or not any(urel == p or urel.startswith(p + "/") for p in old_of):
                continue
            dst = new_root / urel
            with contextlib.suppress(OSError):
                cur = os.lstat(dst)
                if (cur.st_size, cur.st_mtime_ns) == (m["size"], m["dmtime"]):
                    os.unlink(dst)                                 # deleted at the old place just before the switch
                    moved += 1
        return moved, kept


# ------------------------------------------------------------------------------------------------ units

def unit_paths(key: str) -> list[str]:
    """Every path (relative to a root) that can belong to a unit."""
    if "/" in key or key in PINNED_DIRS or key.startswith("."):
        return [key]
    return [key] + [f"{c}/{key}" for c in GAME_CONTAINERS]


def unit_of(rel: str) -> str | None:
    """The unit a cache-relative path belongs to; None for pinned data, top-level files and container roots."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if not parts or _pinned_top(parts[0]):
        return None
    if parts[0] in GAME_CONTAINERS or parts[0] in SPLIT_CONTAINERS:
        if len(parts) < 2:
            return None
        return parts[1] if parts[0] in GAME_CONTAINERS else f"{parts[0]}/{parts[1]}"
    return parts[0]


def safe_key(key) -> bool:
    """A unit key is a single cache-folder name, or <split container>/<name>: never a path that leaves the roots."""
    if not isinstance(key, str) or not key or any(c in key for c in ("\\", ":", "\x00")):
        return False
    parts = key.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    return len(parts) == 1 or (len(parts) == 2 and parts[0] in SPLIT_CONTAINERS)


def _pinned_top(name: str) -> bool:
    return name in PINNED_DIRS or name.startswith(".") or name.endswith(MIGRATED) or MIGRATED + "-" in name


def _base_mid(name: str) -> str:
    return name.removesuffix("-undo").removesuffix("-abort")


# ------------------------------------------------------------------------------------------------ the manager

class Tiers:
    """One node's two-tier cache. Thread-safe; one instance per process (ACTIVE), made by install()."""

    def __init__(self, hot: Path, cold: Path, cap_bytes: int, *, idle_s: float = 1800.0, warm_fraction: float = 0.5,
                 promote_wait_s: float = 60.0, data_dir: Path | None = None, open_check=None, probes=None,
                 verify: str = "hash", clock=time.time, tick_s: float = TICK_S):
        self.hot, self.cold = Path(hot), Path(cold)
        if os.path.normcase(os.path.abspath(self.hot)) == os.path.normcase(os.path.abspath(self.cold)):
            raise ValueError("the hot and cold cache dirs must differ")
        self.cap = int(cap_bytes)
        self.idle_s, self.warm_fraction, self.promote_wait_s = float(idle_s), float(warm_fraction), float(promote_wait_s)
        self.data_dir = Path(data_dir) if data_dir else None
        self.open_check = open_check or open_files_under
        self.probes = list(probes) if probes is not None else [_sessions_probe, _stage_probe]
        self.verify, self.clock, self.tick_s = verify, clock, tick_s
        self.state_dir = self.hot / STATE_DIR
        self.journal_dir = self.state_dir / "journal"
        self.state_path = self.state_dir / "state.json"
        self._lock = threading.RLock()
        self._ulocks: dict[str, threading.Lock] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._busy = 0
        self._last_busy = clock()
        self._dirty = False
        self._names: tuple[float, dict[str, set[str]]] = (0.0, {})
        self._usage: dict | None = None
        self._queue: set[str] = set()
        self._moving: dict[str, dict] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self.thread: threading.Thread | None = None
        self.cold_rate = 80e6                         # bytes/s read from the cold disk; learnt from promotions
        self.last_error = ""
        self.state = self._load_state()

    # -- state
    def _load_state(self) -> dict:
        try:
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        st = st if isinstance(st, dict) else {}
        st.setdefault("version", 1)
        for k, v in (("units", {}), ("moves", []), ("conflicts", []), ("migration", {})):
            if not isinstance(st.get(k), type(v)):
                st[k] = v
        return st

    def flush(self, force: bool = False) -> None:
        with self._lock:
            if not (self._dirty or force):
                return
            doc = json.dumps(self.state, separators=(",", ":"))
            self._dirty = False
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_name(self.state_path.name + ".tmp")
            tmp.write_text(doc, encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError as e:
            self.last_error = f"state not saved: {e}"

    def _unit_rec(self, key: str) -> dict:
        return self.state["units"].setdefault(key, {})

    def touch(self, key: str, at: float | None = None) -> None:
        if not safe_key(key):
            return
        with self._lock:
            self._unit_rec(key)["atime"] = self.clock() if at is None else at
            self._dirty = True
        ev = self._cancel.get(key)
        if ev is not None:
            ev.set()                                  # a demotion of this unit gives way

    def set_pin(self, key: str, pin: bool) -> dict:
        if not safe_key(key) or _pinned_top(key.split("/")[0]):
            raise ValueError("not a movable cache unit")
        with self._lock:
            self._unit_rec(key)["pin"] = bool(pin)
            self._dirty = True
        if pin and self.tier(key) in ("cold", "mixed"):
            self._queue.add(key)
            self._wake.set()
        self.flush()
        return {"unit": key, "pin": bool(pin), "tier": self.tier(key)}

    # -- where things are
    def cold_ok(self) -> bool:
        return self.cold.is_dir()

    def where(self, rel: str) -> str:
        """'hot' (real on the hot tier), 'cold' (the hot path links to the cold copy), 'unlinked' (only on the cold
        tier), 'foreign' (a symlink gBox did not make), or 'missing'."""
        h = self.hot / rel
        if os.path.islink(h):
            t = _link_target(h)
            same = t is not None and os.path.normcase(str(t)) == os.path.normcase(str(self.cold / rel))
            return "cold" if same else "foreign"
        if os.path.lexists(h):
            return "hot"
        if os.path.lexists(self.cold / rel):
            return "unlinked"
        return "missing"

    def parts(self, key: str) -> dict[str, str]:
        return {p: w for p in unit_paths(key) if (w := self.where(p)) != "missing"}

    def tier(self, key: str) -> str:
        ws = {w for w in self.parts(key).values() if w != "foreign"}
        if not ws:
            return "missing"
        if ws <= {"hot"}:
            return "hot"
        if ws <= {"cold", "unlinked"}:
            return "cold"
        return "mixed"

    def unit_keys(self) -> set[str]:
        """Units seen on the hot tier (cold ones are symlinks there since the migration)."""
        keys = set()
        try:
            top = list(os.scandir(self.hot))
        except OSError:
            return keys
        for e in top:
            if _pinned_top(e.name):
                continue
            if e.name in GAME_CONTAINERS or e.name in SPLIT_CONTAINERS:
                with contextlib.suppress(OSError):
                    for c in os.scandir(e.path):
                        if not c.name.startswith("."):
                            keys.add(c.name if e.name in GAME_CONTAINERS else f"{e.name}/{c.name}")
            elif e.is_symlink() or e.is_dir(follow_symlinks=False):
                keys.add(e.name)
        return keys

    def names(self) -> dict[str, set[str]]:
        """Match name -> unit keys (a game id, a top-level folder, the child of a split container)."""
        at, names = self._names
        if names and self.clock() - at < NAMES_TTL_S:
            return names
        names = {}
        for k in self.unit_keys():
            names.setdefault(k.rsplit("/", 1)[-1], set()).add(k)
        self._names = (self.clock(), names)
        return names

    def keys_in(self, obj, limit: int = 4000) -> set[str]:
        """Units a job input names: any string equal to a unit's name, or a path under either root."""
        names, found, stack, n = self.names(), set(), [(obj, 0)], 0
        pres = [os.path.normcase(str(r)) + os.sep for r in (self.hot, self.cold)]
        while stack and n < limit:
            v, depth = stack.pop()
            n += 1
            if isinstance(v, str):
                if v in names:
                    found |= names[v]
                elif len(v) > 3 and (v[0] in "/\\" or v[1:3] in (":\\", ":/")):
                    nv = os.path.normcase(os.path.normpath(v))
                    for pre in pres:
                        if nv.startswith(pre) and (k := unit_of(nv[len(pre):])):
                            found.add(k)
            elif depth < 6 and isinstance(v, dict):
                stack.extend((x, depth + 1) for x in v.values())
            elif depth < 6 and isinstance(v, (list, tuple)):
                stack.extend((x, depth + 1) for x in v)
        return found

    def touch_request(self, path: str, query: bytes | str = b"") -> set[str]:
        """An API request: units named by a path segment or a query value count as used now."""
        names = self.names()
        words = [unquote(w) for w in path.split("/") if w]
        if query:
            q = query.decode("latin-1") if isinstance(query, bytes) else query
            words += [v for _, v in parse_qsl(q)]
        keys = set()
        for w in words:
            keys |= names.get(w, set())
        for k in keys:
            self.touch(k)
        return keys

    # -- idleness
    @contextlib.contextmanager
    def busy(self):
        with self._lock:
            self._busy += 1
            self._last_busy = self.clock()
        try:
            yield
        finally:
            with self._lock:
                self._busy -= 1
                self._last_busy = self.clock()

    def busy_reason(self) -> str | None:
        """Why the node is in use right now (None: nothing runs)."""
        if self._busy:
            return f"{self._busy} job(s) running on this node"
        for probe in self.probes:
            with contextlib.suppress(Exception):
                if r := probe():
                    return r
        return None

    def idle_reason(self) -> str | None:
        """Why demotions must wait (None: idle for long enough)."""
        if r := self.busy_reason():
            with self._lock:
                self._last_busy = self.clock()
            return r
        quiet = self.clock() - self._last_busy
        if quiet < self.idle_s:
            return f"quiet for {int(quiet)} s of {int(self.idle_s)} s"
        return None

    # -- sizes
    def usage(self, fresh: bool = False) -> dict:
        """Real bytes on the hot tier: total, pinned, per unit (symlinked cold data is not counted)."""
        with self._lock:
            u = self._usage
        if u is not None and not fresh and self.clock() - u["at"] < USAGE_TTL_S:
            return u
        seen, total, pinned, other, units = set(), 0, 0, 0, {}
        for rel, kind in _walk(self.hot, ""):
            if kind != "file" or not rel:
                continue
            try:
                st = os.lstat(self.hot / rel)
            except OSError:
                continue
            ino = (st.st_dev, st.st_ino) if st.st_nlink > 1 else None
            if ino in seen:
                continue
            if ino:
                seen.add(ino)
            total += st.st_size
            top = rel.split("/", 1)[0]
            if top == STATE_DIR:
                other += st.st_size
            elif _pinned_top(top) or "/" not in rel:
                pinned += st.st_size
            elif k := unit_of(rel):
                units[k] = units.get(k, 0) + st.st_size
            else:
                other += st.st_size
        u = {"at": self.clock(), "total": total, "pinned": pinned, "other": other, "units": units}
        hot_units = {k: s for k, s in units.items() if self.tier(k) == "hot"}
        with self._lock:
            self._usage = u
            for k, s in hot_units.items():
                self._unit_rec(k)["size"] = s
            self._dirty = True
        return u

    def unit_size(self, key: str) -> int | None:
        return (self.state["units"].get(key) or {}).get("size")

    def measure(self, key: str) -> int:
        """Walk a unit on both tiers for its size (the cold walk is slow: idle time or a launch decision)."""
        parts = self.parts(key)
        size = tree_size(self.hot, [p for p, w in parts.items() if w == "hot"]) + \
            tree_size(self.cold, [p for p, w in parts.items() if w in ("cold", "unlinked")])
        with self._lock:
            self._unit_rec(key)["size"] = size
            self._dirty = True
        return size

    def _initial_atime(self, key: str) -> float:
        """LRU order for a unit never seen used: the newest modification time of its folders."""
        best = 0.0
        for p in unit_paths(key):
            for root in (self.cold, self.hot):
                with contextlib.suppress(OSError):
                    if not os.path.islink(root / p):
                        best = max(best, os.lstat(root / p).st_mtime)
        return best

    # -- locks
    def _failed(self, key: str, op: str, e: BaseException, backoff: float = FAIL_BACKOFF_S) -> None:
        """A background move failed (not gave way): leave the unit alone for a while instead of re-reading it every tick."""
        self.last_error = f"{op} {key}: {type(e).__name__}: {e}"
        _log(self.last_error)
        with self._lock:
            rec = self._unit_rec(key)
            rec["failed"] = {"op": op, "error": f"{type(e).__name__}: {e}"[:300], "at": self.clock()}
            rec["skip_until"] = self.clock() + backoff
            self._dirty = True

    def _skipped(self, key: str) -> bool:
        return self.clock() < ((self.state["units"].get(key) or {}).get("skip_until") or 0)

    def _ulock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._ulocks.setdefault(key, threading.Lock())

    # -- journal
    def _write_json(self, p: Path, doc) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.replace(tmp, p)

    def _journal(self, j: dict) -> None:
        self._write_json(self.journal_dir / f"{j['id']}.json", j)

    def _journal_done(self, mid: str) -> None:
        for name in (f"{mid}.json", f"{mid}.manifest.json"):
            with contextlib.suppress(OSError):
                os.unlink(self.journal_dir / name)

    def _area(self, root: Path, kind: str, mid: str) -> Path:
        return root / STATE_DIR / kind / mid

    # -- moves
    def promote(self, key: str, progress=None, cancel=None, aside: bool = False, background: bool = False) -> dict | None:
        """Bring a unit's cold parts to the hot tier (the caller waits). None when nothing was cold."""
        if not safe_key(key):
            raise ValueError(f"not a cache unit: {key!r}")
        ev = self._cancel.get(key)
        if ev is not None:
            ev.set()                                   # a demotion of this unit stops; then we take its lock
        with self._ulock(key):
            parts = [p for p, w in self.parts(key).items() if w in ("cold", "unlinked")]
            if not parts:
                return None
            if not self.cold_ok():
                raise RuntimeError(f"the cold cache dir {self.cold} is not available")
            if background:
                _io_priority(False)
            return self._move(key, "promote", parts, progress=progress, cancel=cancel, aside=aside)

    def demote(self, key: str, cancel=None) -> dict | None:
        """Move a unit's hot parts to the cold tier, leaving symlinks (idle time). None when nothing was hot."""
        if not safe_key(key) or _pinned_top(key.split("/")[0]):
            raise ValueError(f"not a movable cache unit: {key!r}")
        ev = self._cancel[key] = threading.Event()
        lock = self._ulock(key)
        if not lock.acquire(timeout=1):
            return None
        try:
            parts = [p for p, w in self.parts(key).items() if w == "hot"]
            if not parts or not self.cold_ok():
                return None
            if held := self.open_check([self.hot / p for p in parts]):
                raise Cancelled(f"{key} is open ({held[0]})")

            def stop():
                if ev.is_set():
                    raise Cancelled(f"{key} was asked for")
                if cancel:
                    cancel()
            _io_priority(True)
            return self._move(key, "demote", parts, cancel=stop)
        finally:
            lock.release()
            if self._cancel.get(key) is ev:
                self._cancel.pop(key, None)

    def _move(self, key: str, op: str, parts: list[str], progress=None, cancel=None, aside: bool = False) -> dict:
        src_root, dst_root = (self.hot, self.cold) if op == "demote" else (self.cold, self.hot)
        total = tree_size(src_root, parts)
        free = shutil.disk_usage(dst_root).free
        if free < total + SPACE_MARGIN:
            raise OSError(errno.ENOSPC, f"{key} needs {total / 2**30:.1f} GB; {dst_root} has {free / 2**30:.1f} GB free")
        mid = _stamp()
        staging = self._area(dst_root, "incoming", mid)
        j = {"id": mid, "op": op, "unit": key, "parts": parts, "phase": "copying", "aside": aside, "at": self.clock()}
        self._journal(j)
        t0 = time.monotonic()
        live = self._moving[key] = {"unit": key, "op": op, "done": 0, "total": None, "since": self.clock()}

        def prog(done, total):
            live.update(done=done, total=total)
            if progress:
                progress(done, total)
        copier = Copier(src_root, staging, parts, cancel=cancel, progress=prog, verify=self.verify,
                        drop_cache=(op == "demote"))
        copier.total = total
        try:
            try:
                man = copier.run()
                self._write_json(self.journal_dir / f"{mid}.manifest.json", man)
                if op == "demote":
                    self._fix_sidecars(staging, parts, man)
                    j["phase"] = "placing"
                    self._journal(j)
                    for p in parts:
                        if os.path.lexists(self.cold / p):            # a stale copy from an older move: kept aside
                            self._trash(self.cold, p, mid)
                        (self.cold / p).parent.mkdir(parents=True, exist_ok=True)
                        os.rename(staging / p, self.cold / p)
                    if cancel:
                        cancel()
                    if held := self.open_check([self.hot / p for p in parts]):
                        raise Cancelled(f"{key} was opened ({held[0]})")
            except BaseException:
                self._abort(j, staging)
                raise
            j["phase"] = "swapping"
            self._journal(j)
            if op == "demote":
                old_of = {p: self._swap_to_link(p, mid, i) for i, p in enumerate(parts)}
                moved, kept = copier.catch_up(old_of, self.cold)
                self._fix_stage_db(man)
            else:
                for p in parts:
                    self._swap_to_real(p, staging / p)
                moved, kept = copier.catch_up({p: self.cold / p for p in parts}, self.hot)
            j["phase"] = "cleanup"
            self._journal(j)
            self._cleanup(j)
        finally:
            self._moving.pop(key, None)
        secs = time.monotonic() - t0
        size = sum(m["size"] for m in man.values() if "size" in m and not m.get("link"))
        if op == "promote" and secs > 1 and size > 64 << 20:
            self.cold_rate = 0.7 * self.cold_rate + 0.3 * (size / secs)
        rec = {"unit": key, "op": op, "bytes": size, "files": len(man), "seconds": round(secs, 1), "at": self.clock(),
               **({"late": moved} if moved else {}), **({"kept_newer": kept[:5]} if kept else {})}
        with self._lock:
            self._unit_rec(key)["size"] = size         # (last use is touch()'s: a warm-up is not a use)
            self.state["moves"] = (self.state["moves"] + [rec])[-MOVES_KEPT:]
            self._usage = None
            self._names = (0.0, {})
            self._dirty = True
        self.flush()
        _log(f"{op}d {key}: {size / 2**30:.2f} GB in {secs:.0f} s")
        return rec

    def _trash(self, root: Path, rel: str, mid: str) -> Path:
        dst = self._area(root, "trash", mid) / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(root / rel, dst)
        return dst

    def _swap_to_link(self, p: str, mid: str, i: int) -> Path:
        """hot/p (real) becomes a symlink to cold/p; the old real folder ends up in the hot trash, returned."""
        h = self.hot / p
        tmp = self._area(self.hot, "trash", mid) / f"part{i}"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        if os.path.islink(tmp):                        # left by a swap a crash interrupted before the exchange
            _remove_link(tmp)
        _make_link(self.cold / p, tmp)
        if _exchange(tmp, h):
            return tmp                                 # tmp now holds the real folder
        _remove_link(tmp)
        os.rename(h, tmp)                              # (a crash here: recovery links the cold copy)
        _make_link(self.cold / p, h)
        return tmp

    def _swap_to_real(self, p: str, staged: Path) -> None:
        """hot/p (symlink to cold, or nothing) becomes the staged real folder."""
        h = self.hot / p
        if os.path.islink(h):
            if _exchange(staged, h):
                _remove_link(staged)                   # staged now holds the symlink
                return
            _remove_link(h)                            # (a crash here: recovery renames the staged copy in)
        h.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staged, h)

    def _drop(self, root: Path, path: Path, mid: str) -> None:
        """Remove a partial copy: instantly on the hot disk; on the cold disk it is renamed and purged when idle."""
        if not os.path.lexists(path):
            return
        if root == self.cold and os.path.basename(path) == mid:
            dst = self._area(self.cold, "trash", mid + "-abort")
            dst.parent.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(OSError):
                os.rename(path, dst)
                return
        _rmtree(path)

    def _abort(self, j: dict, staging: Path) -> None:
        """Before the switch nothing changed for readers: drop what was copied (the source stays authoritative)."""
        if j["op"] == "demote" and j.get("phase") == "placing":
            for p in j["parts"]:
                if self.where(p) == "hot" and os.path.lexists(self.cold / p):
                    self._trash(self.cold, p, j["id"] + "-undo")
        self._drop(self.cold if j["op"] == "demote" else self.hot, staging, j["id"])
        self._journal_done(j["id"])

    def _cleanup(self, j: dict) -> None:
        mid = j["id"]
        if j["op"] == "demote":
            old = self._area(self.hot, "trash", mid)
            if not self.open_check([old]):                # opened in the last instant: purged once closed
                _rmtree(old)
            _rmtree(self._area(self.cold, "incoming", mid))          # only empty container folders are left
        else:
            for p in j["parts"]:
                c = self.cold / p
                if self.where(p) == "hot" and os.path.lexists(c) and not os.path.islink(c):
                    if j.get("aside"):
                        _aside(c, MIGRATED)            # pinned data: the operator's original stays on the disk
                    else:
                        self._trash(self.cold, p, mid)
            _rmtree(self._area(self.hot, "incoming", mid))
        self._journal_done(mid)

    def recover(self) -> list[str]:
        """Finish or undo moves a crash interrupted (start-up, before anything reads the cache)."""
        done = []
        try:
            journals = sorted(p for p in self.journal_dir.glob("*.json") if not p.name.endswith(".manifest.json"))
        except OSError:
            return done
        for jp in journals:
            try:
                j = json.loads(jp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not self.cold_ok():
                _log(f"journal {jp.name} waits: the cold dir is not available")
                continue
            try:
                done.append(self._recover_one(j))
            except Exception as e:                     # noqa: BLE001 - left for the next start, reported
                self.last_error = f"recovering {j.get('unit')}: {type(e).__name__}: {e}"
                _log(self.last_error)
        return done

    def _recover_one(self, j: dict) -> str:
        mid, op, parts, phase = j["id"], j["op"], j["parts"], j.get("phase")
        staging = self._area(self.cold if op == "demote" else self.hot, "incoming", mid)
        man = {}
        with contextlib.suppress(OSError, ValueError):
            man = json.loads((self.journal_dir / f"{mid}.manifest.json").read_text(encoding="utf-8"))
        if phase in ("copying", "placing"):
            self._abort(j, staging)                    # the source is complete and was never switched away from
            return f"{j['unit']}: {op} rolled back"
        if phase == "swapping":
            for i, p in enumerate(parts):
                w = self.where(p)
                if op == "demote":
                    old = self._area(self.hot, "trash", mid) / f"part{i}"
                    if w == "hot" and os.path.lexists(self.cold / p):
                        old = self._swap_to_link(p, mid, i)
                    elif w in ("missing", "unlinked") and os.path.lexists(self.cold / p):
                        _make_link(self.cold / p, self.hot / p)
                    if man and os.path.isdir(old) and not os.path.islink(old):
                        c = Copier(self.hot, self.cold, [p])
                        c.man = man
                        c.catch_up({p: old}, self.cold)
                else:
                    st = staging / p
                    if w in ("cold", "missing", "unlinked") and os.path.isdir(st):
                        self._swap_to_real(p, st)
                    elif w == "missing" and os.path.lexists(self.cold / p):
                        _make_link(self.cold / p, self.hot / p)
                    if man and self.where(p) == "hot" and os.path.isdir(self.cold / p):
                        c = Copier(self.cold, self.hot, [p])
                        c.man = man
                        c.catch_up({p: self.cold / p}, self.hot)
        self._cleanup(j)
        return f"{j['unit']}: {op} finished"

    # -- fix-ups after a demotion (the cold disk keeps mtimes at 100 ns, so stat-keyed caches would re-hash)
    def _fix_sidecars(self, staging: Path, parts: list[str], man: dict) -> None:
        """filemods hash sidecars (.<mod>.sha256.json, rows [mtime_ns, size, sha256]) follow the copied files' mtimes."""
        for p in parts:
            if not p.startswith("mods/"):
                continue
            try:
                sidecars = list((staging / p).glob(".*.sha256.json"))
            except OSError:
                continue
            for sc in sidecars:
                mod = sc.name[1:-len(".sha256.json")]
                try:
                    rows = json.loads(sc.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(rows, dict):
                    continue
                changed = False
                for path, row in rows.items():
                    m = man.get(f"{p}/{mod}/{path}")
                    if (m and "sha" in m and isinstance(row, list) and len(row) == 3 and row[0] == m["mtime"]
                            and row[1] == m["size"] and row[2] == m["sha"] and m["dmtime"] != row[0]):
                        row[0] = m["dmtime"]
                        changed = True
                if changed:
                    st = os.stat(sc)
                    sc.write_text(json.dumps(rows), encoding="utf-8")
                    os.utime(sc, ns=(st.st_atime_ns, st.st_mtime_ns))
                    rel = f"{p}/{sc.name}"
                    if rel in man:
                        man[rel] = dict(man[rel], dmtime=os.stat(sc).st_mtime_ns)

    def _fix_stage_db(self, man: dict) -> None:
        """catalog's stage db keeps [size, mtime_ns] per staged file; moved files keep their known hashes."""
        catalog = sys.modules.get("gbox.catalog")
        if catalog is None:
            return
        pre = str(self.hot) + os.sep
        with catalog._STAGE_LOCK:
            db = catalog._db_load(self.hot)
            changed = False
            for k, rec in db.items():
                if not (isinstance(rec, dict) and k.startswith(pre)):
                    continue
                m = man.get(k[len(pre):].replace(os.sep, "/"))
                if m and "size" in m and rec.get("ident") == [m["size"], m["mtime"]] and m["dmtime"] != m["mtime"]:
                    rec["ident"] = [m["size"], m["dmtime"]]
                    changed = True
            if changed:
                p = self.hot / STAGE_DB
                tmp = p.with_name(p.name + ".tmp")
                tmp.write_text(json.dumps(db))
                tmp.replace(p)

    # -- trash
    def purge_trash(self) -> int:
        """Delete old copies of finished moves that nothing holds open any more (idle time)."""
        n = 0
        for root in (self.hot, self.cold):
            for kind in ("trash", "incoming"):
                try:
                    olds = list((root / STATE_DIR / kind).iterdir())
                except OSError:
                    continue
                for d in olds:
                    if (self.journal_dir / f"{_base_mid(d.name)}.json").exists():
                        continue                       # a move still running, or waiting for recovery
                    if self.open_check([d]):
                        continue
                    _rmtree(d)
                    n += 1
        return n

    # -- migration (start-up, idempotent)
    def migrate(self) -> dict:
        """Make the hot dir a complete view: link every cold unit that has no hot entry, copy the top-level files
        (indexes), and point the built mods index and the stage db at the hot dir. Heavy copies run later."""
        out = {"linked": 0, "conflicts": [], "files": [], "at": self.clock()}
        self.hot.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.cold_ok():
            out["error"] = f"cold dir {self.cold} not available"
            self.last_error = out["error"]
            return out
        first = not self.state["migration"].get("done_at")
        for e in sorted(os.scandir(self.cold), key=lambda e: e.name):
            name = e.name
            if name == STATE_DIR or name.endswith(MIGRATED) or MIGRATED + "-" in name or e.is_symlink():
                continue
            try:
                if e.is_file(follow_symlinks=False):
                    if self._migrate_file(name, first):
                        out["files"].append(name)
                    continue
                if not e.is_dir(follow_symlinks=False):
                    continue
                if name in GAME_CONTAINERS or name in SPLIT_CONTAINERS:
                    hc = self.hot / name
                    if os.path.islink(hc):                  # a container is never linked as a whole
                        out["conflicts"].append({"path": name, "kept": "hot", "note": "container is a symlink"})
                        continue
                    hc.mkdir(parents=True, exist_ok=True)
                    for c in sorted(os.scandir(e.path), key=lambda c: c.name):
                        if not c.is_symlink() and not c.name.endswith(MIGRATED) and not c.name.startswith(".gbox-tier"):
                            self._link_one(f"{name}/{c.name}", first, out)
                else:
                    self._link_one(name, first, out)
            except OSError as err:
                out["conflicts"].append({"path": name, "error": str(err)})
        self._rewrite_index()
        self._names = (0.0, {})
        keys = self.unit_keys()
        with self._lock:
            mig = self.state["migration"]
            mig.setdefault("started_at", self.clock())
            mig["done_at"] = self.clock()
            mig["linked"] = mig.get("linked", 0) + out["linked"]
            if out["conflicts"]:
                self.state["conflicts"] = (self.state["conflicts"] + out["conflicts"])[-100:]
            self._dirty = True
        for k in keys:
            if "atime" not in (self.state["units"].get(k) or {}):
                at = self._initial_atime(k)
                with self._lock:
                    self._unit_rec(k)["atime"] = at
        self.flush(force=True)
        if out["linked"] or out["conflicts"] or out["files"]:
            _log(f"migration: {out['linked']} folder(s) linked to the cold tier, {len(out['files'])} file(s) copied, "
                 f"{len(out['conflicts'])} conflict(s)")
        return out

    def _link_one(self, rel: str, first: bool, out: dict) -> None:
        h, c = self.hot / rel, self.cold / rel
        if os.path.islink(h):
            return
        if os.path.lexists(h):
            if not first:                               # later: the hot copy is authoritative, the cold one reported
                out["conflicts"].append({"path": rel, "kept": "hot", "at": self.clock()})
                return
            # first migration: the cold dir is what the service used since the cutover; a hot leftover goes aside
            dst = self.state_dir / "conflicts" / _stamp() / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(h, dst)
            out["conflicts"].append({"path": rel, "kept": "cold", "hot_copy": str(dst), "at": self.clock()})
        _make_link(c, h)
        out["linked"] += 1

    def _migrate_file(self, name: str, first: bool) -> bool:
        h, c = self.hot / name, self.cold / name
        if name == STAGE_DB:                            # keys are absolute paths: re-rooted at the hot dir and merged
            try:
                cold_db = json.loads(c.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                cold_db = {}
            pre_c, pre_h = str(self.cold) + os.sep, str(self.hot) + os.sep
            cold_db = {(pre_h + k[len(pre_c):] if k.startswith(pre_c) else k): v for k, v in cold_db.items()} \
                if isinstance(cold_db, dict) else {}
            try:
                hot_db = json.loads(h.read_text(encoding="utf-8")) if h.exists() else {}
            except (OSError, ValueError):
                hot_db = {}
            hot_db = hot_db if isinstance(hot_db, dict) else {}
            merged = hot_db | cold_db if first else cold_db | hot_db
            tmp = h.with_name(h.name + ".tmp")
            tmp.write_text(json.dumps(merged))
            os.replace(tmp, h)
            _aside(c, MIGRATED)
            return True
        if os.path.lexists(h):
            if not first:
                return False
            dst = self.state_dir / "conflicts" / _stamp() / name
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(h, dst)
        tmp = h.with_name(h.name + ".gbox-tier-tmp")
        shutil.copy2(c, tmp)
        if os.path.getsize(tmp) != os.path.getsize(c) or _sha256(tmp) != _sha256(c):
            os.unlink(tmp)
            raise OSError(f"the copy of {name} did not verify")
        os.replace(tmp, h)
        _aside(c, MIGRATED)
        return True

    def _rewrite_index(self) -> None:
        """The built mods index names the cache it indexed; the same mods seen through the hot dir keep their facts."""
        if not self.data_dir:
            return
        p = self.data_dir / BUILT_MODS_INDEX
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(doc, dict) and doc.get("root") == str(self.cold / "mods"):
            doc["root"] = str(self.hot / "mods")
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(json.dumps(doc, separators=(",", ":"), default=str), encoding="utf-8")
            os.replace(tmp, p)

    def pinned_pending(self) -> list[str]:
        """Pinned folders still on the cold tier (the character library right after the migration)."""
        out = [n for n in PINNED_DIRS if self.where(n) in ("cold", "unlinked")]
        with contextlib.suppress(OSError):
            for e in os.scandir(self.hot):
                if e.name.startswith(".") and e.name != STATE_DIR and self.where(e.name) == "cold":
                    out.append(e.name)
        return out

    def promote_pinned(self) -> list[dict]:
        """Copy the pinned libraries off the cold tier (not idle-gated: they are what made the HDD slow to use)."""
        done = []
        for name in self.pinned_pending():
            if self._skipped(name):
                continue
            try:
                rec = self.promote(name, aside=True, background=True)
                if rec:
                    done.append(rec)
                    _invalidate_characters(self.hot / name)
            except Exception as e:                     # noqa: BLE001 - retried after a pause
                self._failed(name, "pinning", e, PINNED_BACKOFF_S)
        return done

    # -- the background loop
    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self._stop.clear()
        self.thread = threading.Thread(target=self._loop, name="cache-tiers", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        _nice_thread(10)
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:                     # noqa: BLE001 - the loop must survive anything
                self.last_error = f"{type(e).__name__}: {e}"
                _log(f"maintenance failed: {self.last_error}")
            self._wake.wait(self.tick_s)
            self._wake.clear()
        self.flush()

    def tick(self) -> dict:
        """One maintenance pass: pinned libraries; then, only when idle: trash, queued promotions, demotions, warm-up."""
        out: dict = {}
        self.flush()
        if not self.cold_ok():
            return {"skipped": "cold dir not available"}
        if self.pinned_pending():
            out["pinned"] = self.promote_pinned()
        if reason := self.idle_reason():
            out["waiting"] = reason
            return out
        out["purged"] = self.purge_trash()

        def give_way():
            if r := self.busy_reason():
                raise Cancelled(r)
        kept = {k for k, r in list(self.state["units"].items()) if r.get("pin")}
        now = self.clock()
        for key in sorted(self._queue | kept):
            if self.tier(key) not in ("cold", "mixed"):
                self._queue.discard(key)
                continue
            if now - ((self.state["units"].get(key) or {}).get("atime") or 0) < self.idle_s:
                continue                                # still in use (a remote download, a session): later
            self._queue.discard(key)
            if self._skipped(key):
                continue
            size = self.unit_size(key)
            if size is None:
                size = self.measure(key)
            if key not in kept and size > self.cap * LOW_WATER:
                continue
            if key not in kept and self.usage()["total"] + size > self.cap and not self._newer_than_lru(key):
                continue                                # it would only push out something used more recently
            try:
                self.promote(key, cancel=give_way, background=True)
                out.setdefault("promoted", []).append(key)
            except Cancelled:
                self._queue.add(key)
                return out
            except Exception as e:                     # noqa: BLE001 - next unit; reported in the status
                self._failed(key, "promoting", e)
        u = self.usage()
        if u["total"] > self.cap:
            out["demoted"] = self._demote_lru(u, give_way)
        elif not self.state.get("warm_done"):
            out["warmed"] = self._warm(u, give_way)
        return out

    def _newer_than_lru(self, key: str) -> bool:
        """Was key used more recently than the least recently used demotable unit on the hot tier?"""
        at = (self.state["units"].get(key) or {}).get("atime") or 0
        hot = [(self.state["units"].get(k) or {}) for k in self.usage()["units"]]
        olds = [r.get("atime") or 0 for r in hot if not r.get("pin")]
        return bool(olds) and at > min(olds)

    def _demote_lru(self, u: dict, give_way) -> list[str]:
        total, target, done, now = u["total"], self.cap * LOW_WATER, [], self.clock()
        cands = []
        for key, size in u["units"].items():
            rec = self.state["units"].get(key) or {}
            if rec.get("pin") or now - rec.get("atime", 0) < self.idle_s or self._skipped(key):
                continue
            cands.append((rec.get("atime", 0), key, size))
        for _at, key, size in sorted(cands):
            if total <= target:
                break
            try:
                if self.demote(key, cancel=give_way):
                    total -= size
                    done.append(key)
            except Cancelled as e:
                _log(f"demotion of {key} gave way: {e}")
                if self.busy_reason():
                    break
            except Exception as e:                     # noqa: BLE001 - next unit; reported in the status
                self._failed(key, "demoting", e)
        if total > self.cap and not cands:
            self.last_error = "the hot tier is over its cap and nothing can be demoted (pinned or recently used)"
        return done

    def _warm(self, u: dict, give_way) -> list[str]:
        """After the migration: promote the most recently used cold units up to warm_fraction of the cap."""
        budget, total, done = self.cap * self.warm_fraction, u["total"], []
        cold = sorted((-(r.get("atime") or 0), k) for k, r in list(self.state["units"].items()) if self.tier(k) == "cold")
        finished = True
        for _neg, key in cold:
            if total >= budget:
                break
            if self.busy_reason():
                finished = False
                break
            if self._skipped(key):
                continue
            size = self.unit_size(key)
            if size is None:
                size = self.measure(key)
            if total + size > budget:
                continue
            try:
                if self.promote(key, cancel=give_way, background=True):
                    total += size
                    done.append(key)
            except Cancelled:
                finished = False
                break
            except Exception as e:                     # noqa: BLE001 - next unit
                self._failed(key, "promoting", e)
        if finished:
            with self._lock:
                self.state["warm_done"] = self.clock()
                self._dirty = True
        return done

    # -- job hook
    def promote_for(self, tool: str, raw_input, progress=None) -> list[dict]:
        """Units a job names come up before it runs; a launch waits only for a quick one (the rest: when idle)."""
        # These jobs consume a captured image or an explicit analysis file, not
        # the game's ROM/mod unit. A game_id in their provenance must not move
        # several GiB before the first RAM read or Ghidra query. job_scope still
        # marks the node busy, so idle cache maintenance continues to give way.
        if tool in {"analyze_binary", "ghidra_script", "ghidra_bridge", "read_rea_result"} or tool.startswith("rea_"):
            return []
        if tool == "re_executable" and isinstance(raw_input, dict) and raw_input.get("source") in {"ram", "path"}:
            return []
        if tool == 'title_assets':
            # This reader resolves an already available source and streams only
            # selected members. Do not move the entire ROM/mod unit first.
            return []
        if tool == 'storage_purge':
            # The purge lists / deletes units where they are (gbox/storage_purge.py): the game ids in its facts and
            # paths must neither move a unit up nor count as a use of it.
            return []
        out, keys = [], sorted(self.keys_in(raw_input))
        for key in keys:
            self.touch(key)
            if self.tier(key) not in ("cold", "mixed"):
                continue
            if len(keys) > MAX_PROMOTE_PER_JOB:
                out.append({"unit": key, "skipped": f"the job names {len(keys)} units"})
                continue
            size = self.unit_size(key)
            if size is None:
                size = self.measure(key)
            if size > self.cap * LOW_WATER:
                out.append({"unit": key, "skipped": "larger than the hot tier"})
                continue
            if tool in LAUNCH_TOOLS and size / self.cold_rate > self.promote_wait_s:
                self._queue.add(key)                   # plays from the cold disk now; moves up once idle
                out.append({"unit": key, "queued": True})
                continue

            def prog(done, total, key=key):
                if progress:
                    progress(2, f"Moving {key} to the fast drive: {done / 2**30:.1f} / {(total or 0) / 2**30:.1f} GB")
            rec = self.promote(key, progress=prog)
            if rec:
                out.append(rec)
        return out

    # -- status
    def status(self) -> dict:
        u = self.usage()
        units, tiers = [], {"hot": 0, "cold": 0, "mixed": 0}
        for k in self.unit_keys():
            t = self.tier(k)
            if t in tiers:
                tiers[t] += 1
            rec = self.state["units"].get(k) or {}
            units.append({"unit": k, "tier": t, "size": u["units"].get(k) if t == "hot" else rec.get("size"),
                          "last_used": rec.get("atime"), "pin": bool(rec.get("pin")),
                          **({"failed": rec["failed"]} if rec.get("failed") and self._skipped(k) else {})})
        units.sort(key=lambda r: -(r["last_used"] or 0))
        warnings = []
        if not self.cold_ok():
            warnings.append(f"the cold cache dir {self.cold} is not available (drive not mounted?)")
        if self.cap and u["pinned"] >= 0.8 * self.cap:
            warnings.append(f"pinned data alone is {u['pinned'] / 2**30:.1f} GB of the {self.cap / 2**30:.0f} GB hot cap")
        if u["total"] > self.cap * 1.1:
            warnings.append("the hot tier is over its cap; demotion waits for idle time")
        disk = {}
        for name, root in (("hot", self.hot), ("cold", self.cold)):
            with contextlib.suppress(OSError):
                du = shutil.disk_usage(root)
                disk[name] = {"disk_free": du.free, "disk_total": du.total}
        return {
            "enabled": True,
            "hot": {"root": str(self.hot), "used": u["total"], "cap": self.cap, "pinned": u["pinned"],
                    "other": u["other"], "measured_at": u["at"], **disk.get("hot", {})},
            "cold": {"root": str(self.cold), "available": self.cold_ok(), **disk.get("cold", {})},
            "units": tiers, "top": units[:60], "moving": list(self._moving.values()), "queued": sorted(self._queue),
            "pinned_pending": self.pinned_pending(), "moves": list(reversed(self.state["moves"][-15:])),
            "conflicts": self.state["conflicts"][-10:], "migration": self.state["migration"],
            "warm_done": self.state.get("warm_done"), "idle": self.idle_reason() or "idle",
            "idle_minutes": self.idle_s / 60, "warnings": warnings, "error": self.last_error,
        }


# ------------------------------------------------------------------------------------------------ probes

def _sessions_probe() -> str | None:
    tools = sys.modules.get("gbox.tools")
    sessions = getattr(tools, "SESSIONS", None) if tools else None
    return f"{len(sessions)} game session(s) on this node" if sessions else None


def _stage_probe() -> str | None:
    catalog = sys.modules.get("gbox.catalog")
    copies = getattr(catalog, "_COPIES", None) if catalog else None
    return f"{len(copies)} launch copy(ies) in flight" if copies else None


def _invalidate_characters(root: Path) -> None:
    mod = sys.modules.get("gbox.characters")
    if mod is not None:
        with contextlib.suppress(Exception):
            mod._invalidate_list(root)


# ------------------------------------------------------------------------------------------------ module API

def install(config) -> Tiers | None:
    """Turn tiering on for this process when the config names a cold dir for this OS (idempotent; start-up)."""
    global ACTIVE
    cold = getattr(config, "cold_cache", None)
    with _INSTALL_LOCK:
        if cold is None:
            if ACTIVE is not None:
                ACTIVE.stop()
                ACTIVE = None
            return None
        hot = Path(config.cache)
        if ACTIVE is not None and ACTIVE.hot == hot and ACTIVE.cold == Path(cold):
            return ACTIVE
        if ACTIVE is not None:
            ACTIVE.stop()
            ACTIVE = None
        try:
            t = Tiers(hot, Path(cold), int(config.hot_cache_limit * 1024**3),
                      idle_s=config.cache_tier_idle_minutes * 60, warm_fraction=config.cache_tier_warm_fraction,
                      promote_wait_s=config.cache_tier_promote_wait_s, data_dir=config.data_dir)
            t.hot.mkdir(parents=True, exist_ok=True)
            for r in t.recover():
                _log(f"recovered: {r}")
            t.migrate()
            t.start()
        except Exception as e:                         # noqa: BLE001 - a tiering fault must not stop the service
            _log(f"disabled: {type(e).__name__}: {e}")
            return None
        ACTIVE = t
        return t


def cold_root() -> Path | None:
    t = ACTIVE
    return t.cold if t is not None else None


def is_tier_link(path) -> bool:
    """A symlink this module made (a hot path pointing at its cold copy)."""
    t = ACTIVE
    if t is None or not os.path.islink(path):
        return False
    target = _link_target(Path(path))
    if target is None:
        return False
    tn, cn = os.path.normcase(str(target)), os.path.normcase(str(t.cold))
    return tn.startswith(cn + os.sep)


@contextlib.contextmanager
def job_scope(tool: str, raw_input, ctx=None):
    """Around every tool run on this node: the node counts as busy, and the units the input names come up first."""
    t = ACTIVE
    if t is None:
        yield
        return
    with t.busy():
        try:
            t.promote_for(tool, raw_input, getattr(ctx, "progress", None))
        except Exception as e:                         # noqa: BLE001 - the job still runs (from the cold copy)
            if type(e).__name__ == "Cancelled" and not isinstance(e, Cancelled):
                raise                                  # the operator cancelled the job while it waited
            t.last_error = f"promotion before {tool}: {type(e).__name__}: {e}"
            _log(t.last_error)
        yield


def ensure_hot(*keys: str) -> None:
    """Writes are about to land in these units: bring them to the hot tier first (no-op without tiering)."""
    t = ACTIVE
    if t is None:
        return
    for k in keys:
        if not safe_key(k) or t.tier(k) == "missing":
            continue
        t.touch(k)
        if t.tier(k) in ("cold", "mixed"):
            try:
                t.promote(k)
            except Exception as e:                     # noqa: BLE001 - the write still works on the cold copy
                t.last_error = f"promoting {k}: {type(e).__name__}: {e}"
                _log(t.last_error)


def touch(*keys: str, queue: bool = False) -> None:
    """These units were used: keep them off the demotion list; queue=True also moves a cold one up when idle."""
    t = ACTIVE
    if t is None:
        return
    for k in keys:
        if not safe_key(k) or t.tier(k) == "missing":
            continue
        t.touch(k)
        if queue and t.tier(k) in ("cold", "mixed"):
            t._queue.add(k)


class TouchMiddleware:
    """ASGI: an API request naming a unit (path segment or query value) marks it used. Never wraps the response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        t = ACTIVE
        if t is not None and scope.get("type") == "http":
            with contextlib.suppress(Exception):
                t.touch_request(scope.get("path", ""), scope.get("query_string", b""))
        await self.app(scope, receive, send)


def routes(app, config, auth) -> None:
    from fastapi import Body, Depends, HTTPException

    @app.get("/api/cache/tiers")
    def cache_tiers_status(actor=Depends(auth)):
        """This node's two-tier cache (docs/cache-tiers.md); enabled: false on a single-tier node."""
        t = ACTIVE
        if t is None:
            return {"enabled": False, "cache": str(config.cache), "cap": int(config.cache_limit * 1024**3)}
        return t.status()

    @app.post("/api/cache/tiers/pin")
    def cache_tiers_pin(body: dict = Body(...), actor=Depends(auth)):
        """{unit, pin}: keep a unit (a game id) on the fast drive: never demoted; moved up when the node is idle."""
        t = ACTIVE
        if t is None:
            raise HTTPException(409, "this node has a single-tier cache")
        try:
            return t.set_pin(body.get("unit"), bool(body.get("pin", True)))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
