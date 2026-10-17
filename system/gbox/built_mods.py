"""Built mods gallery: every mod folder a writer built in the configured cache, joined with its mod card.

Writers build launchable mods straight into <cache>/mods/<game_id>/<mod>/ with a .gbox-mod.json marker (cast swaps,
PSO enemies, Crazy Taxi, JGR, Def Jam, PE2, Clay Fighter, SmackDown 2, MGS VR, DOA2 rosters, Vice City, ...). Many are
never saved as a mod card (/api/mods), so the operator could not see or launch them. This module

  * scans the control plane's own cache (config.cache, never a hardcoded path) for built folders,
  * normalizes each writer's marker into one shape: writer, donor -> slot rows (the per-slot report for cast swaps),
    built time, size, verified flag, last launch result, preview images, ticket numbers,
  * joins the mod cards (thumbnail, in-game shots, saved moment), the frames captured from sessions that ran the build
    (get_frame, save-state pictures, observations, task evidence; covered captures skipped) and the donors' previews,
  * registers a mod card for any built folder that lacks one (idempotent), so every build launches the usual way
    (@launch mod=<name>).

GET  /api/mods/built                                    the gallery (filters + pagination), from the persistent index
POST /api/mods/built/refresh                            re-read new / changed markers now (in the background)
GET  /api/mods/built/{game_id}/{mod}/image/{name}       a preview picture from the mod folder (path-checked)

The cache lives on a USB disk that may be busy with large copies, and some builds are whole disc-image folders, so a
request never touches the mod folders: an index (data_dir/built_mods_index.json) holds each folder's marker facts and,
once a background thread has walked it, its size (keyed by folder + marker mtime). A timer and POST .../refresh re-read
only new or changed markers; sizes of new builds arrive later (size: null until known); a cold index answers with what
it has and `indexing: true`.
"""
import hashlib
import json
import os
import re
import stat as statmod
import threading
import time
from pathlib import Path

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse

MARKER = ".gbox-mod.json"
STAGED_MARK = ".gbox-staged-of"            # a local staging copy of a collection mod (filemods.STAGED_MARK)
STAGED_SEP = "~"                           # <mod>~<build>: a rebuilt mod staged beside a copy a running game holds open
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
PREVIEW_DIRS = ("preview", "previews")     # subfolders some writers put their pictures in
PREVIEW_KEYS = ("previews", "preview", "images", "screenshots")      # marker keys that list a build's pictures
# the pictures writers drop at the top of a build folder under a fixed name (clayfighter/pso frames_preview.png,
# gta preview.png, atlas.png ...): stat'ed by name, the folder itself is never listed
KNOWN_PREVIEWS = ("frames_preview.png", "preview.png", "preview.jpg", "preview.webp", "thumb.png", "thumb.jpg",
                  "atlas.png", "screenshot.png")
MAX_IMAGES = 24
TTL = 20.0                                 # seconds a joined answer is reused (sessions / jobs change without a hook)
REFRESH_EVERY = 60.0                       # seconds between incremental marker passes
SAVE_EVERY = 5.0                           # the index file is rewritten at most this often while sizes arrive
INDEX_FILE = "built_mods_index.json"       # under the control plane's data dir (not the busy cache disk)
INDEX_VERSION = 1
VERIFIED_KEYS = ("verified", "verified_in_game", "gameplay_verified")
TICKET_KEYS = ("requests", "request", "tickets", "ticket", "request_number")


# ------------------------------------------------------------------------------------------------- folder facts

def mods_root(config) -> Path:
    return Path(config.cache) / "mods"


def _safe_component(value) -> bool:
    return isinstance(value, str) and bool(value) and value not in (".", "..") and not any(c in value for c in "/\\:\0")


def _picture_name(value, folder: Path) -> str:
    """A marker's picture entry -> a name the image route serves (top level or preview(s)/x), else ''."""
    if isinstance(value, dict):
        value = value.get("name") or value.get("path") or value.get("file") or ""
    if not isinstance(value, str) or not value.strip():
        return ""
    v = value.strip().replace("\\", "/")
    if v.startswith("/") or re.match(r"^[A-Za-z]:/", v):              # an absolute path: only inside this folder
        prefix = str(folder).replace("\\", "/").rstrip("/") + "/"
        if not v.startswith(prefix):
            return ""
        v = v[len(prefix):]
    parts = v.split("/")
    if (not parts or len(parts) > 2 or any(not _safe_component(p) for p in parts)
            or (len(parts) == 2 and parts[0] not in PREVIEW_DIRS) or Path(v).suffix.lower() not in IMAGE_TYPES):
        return ""
    return v


def _images(folder: Path, meta: dict | None = None) -> list[str]:
    """Preview pictures of a build: the ones its marker lists plus the fixed preview names, each stat'ed by name (no
    directory listing: a folder may be a whole disc image on a busy disk). Symlinks and missing files are left out."""
    names = []
    for k in PREVIEW_KEYS:
        for v in _as_list((meta or {}).get(k)):
            n = _picture_name(v, folder)
            if n and n not in names:
                names.append(n)
    names += [n for n in KNOWN_PREVIEWS if n not in names]
    found = []
    for n in names:
        try:
            st = os.lstat(folder.joinpath(*n.split("/")))
        except OSError:
            continue
        if statmod.S_ISREG(st.st_mode):
            found.append(n)
    # pictures named like a preview first (frames_preview.png, preview.png, atlas.png ...)
    found.sort(key=lambda n: (0 if re.search(r"preview|thumb|shot|frame", n, re.I) else 1, n.lower()))
    return found[:MAX_IMAGES]


def folder_size(folder: Path, stop: threading.Event | None = None) -> tuple[int, int, int] | None:
    """(bytes, own bytes, files): own bytes leave out hard links to the shared base copy (filemods' folder games).
    The background sizer's walk; None when stopped part way."""
    total = own = count = 0
    stack = [folder]
    while stack:
        if stop is not None and stop.is_set():
            return None
        d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError:
            continue
        for e in it:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    total += st.st_size
                    count += 1
                    if st.st_nlink <= 1:
                        own += st.st_size
            except OSError:
                continue
    return total, own, count


_size = folder_size

DIFF_SKIP = {MARKER, STAGED_MARK, *KNOWN_PREVIEWS}
DIFF_BYTES = 8 << 20                       # equal-size files up to this are compared byte for byte
DIFF_LIST = 20


def base_diff(folder: Path, base: Path, stop: threading.Event | None = None) -> dict | None:
    """What a build folder changes against its game's base copy (modbase/<game_id>, filemods): each file is the same
    (a hard link to the base file, or equal bytes), changed (another size or other bytes), new (not in the base), or
    unverified (the same size but too large to compare here). {"base": False} when there is no base copy to compare
    with; None when stopped part way. The background sizer's walk (#1656: "What this changes" for builds whose marker
    records nothing)."""
    try:
        if not base.is_dir():
            return {"base": False}
    except OSError:
        return {"base": False}
    out = {"base": True, "changed": [], "new": [], "unverified": [], "changed_n": 0, "new_n": 0, "unverified_n": 0, "same_n": 0}

    def add(kind, rel):
        out[f"{kind}_n"] += 1
        if len(out[kind]) < DIFF_LIST:
            out[kind].append(rel)
    stack = [folder]
    while stack:
        if stop is not None and stop.is_set():
            return None
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if not (d == folder and e.name in PREVIEW_DIRS):
                        stack.append(Path(e.path))
                    continue
                rel = Path(e.path).relative_to(folder).as_posix()
                if (d == folder and e.name in DIFF_SKIP) or e.name.endswith(".part"):
                    continue
                st = e.stat(follow_symlinks=False)
                b = base / rel
                try:
                    bst = b.stat()
                except OSError:
                    add("new", rel)
                    continue
                if (st.st_ino, st.st_dev) == (bst.st_ino, bst.st_dev):
                    out["same_n"] += 1
                elif st.st_size != bst.st_size:
                    add("changed", rel)
                elif st.st_size > DIFF_BYTES:
                    add("unverified", rel)
                else:
                    with open(e.path, "rb") as x, open(b, "rb") as y:
                        same = x.read() == y.read()
                    if same:
                        out["same_n"] += 1
                    else:
                        add("changed", rel)
            except (OSError, ValueError):
                continue
    return out

_FOLDER_CACHE: dict = {}
_FOLDER_LOCK = threading.Lock()


def read_folder(folder: Path, st: os.stat_result | None = None) -> dict | None:
    """One built mod folder -> its marker facts (marker, listed pictures; size unknown here), cached until the marker
    changes. Reads the small marker and stats its known pictures, never walks the folder."""
    marker = folder / MARKER
    if st is None:
        try:
            st = marker.stat()
        except OSError:
            return None
    if STAGED_SEP in folder.name or (folder / STAGED_MARK).exists():
        return None
    key = (str(folder), st.st_mtime_ns, st.st_size)
    with _FOLDER_LOCK:
        hit = _FOLDER_CACHE.get(str(folder))
    if hit and hit[0] == key:
        return hit[1]
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    rec = {"name": folder.name, "game_id": folder.parent.name, "meta": meta, "images": _images(folder, meta),
           "size": None, "own_size": None, "files": None, "marker_mtime": st.st_mtime,
           "marker": [st.st_mtime_ns, st.st_size]}
    with _FOLDER_LOCK:
        _FOLDER_CACHE[str(folder)] = (key, rec)
    return rec


def _tier_link(path: str) -> bool:
    from . import cache_tiers
    return cache_tiers.is_tier_link(path)


def _mod_dirs(root: Path):
    """(game_id, mod, path, marker stat) of every candidate build: two directory levels and one marker stat each."""
    try:
        games = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return
    for g in games:
        try:
            if not _safe_component(g.name) or not (g.is_dir(follow_symlinks=False) or _tier_link(g.path)):
                continue                                             # (a game demoted to the cold tier is a symlink)
            mods = sorted(os.scandir(g.path), key=lambda e: e.name)
        except OSError:
            yield g.name, None, None, None                         # this game's folder could not be listed
            continue
        for m in mods:
            if not _safe_component(m.name) or STAGED_SEP in m.name:
                continue
            try:
                if not m.is_dir(follow_symlinks=False):
                    continue
                st = os.stat(os.path.join(m.path, MARKER))
            except OSError:
                continue
            yield g.name, m.name, Path(m.path), st


def scan(root: Path) -> list[dict]:
    """Every built mod under <cache>/mods/<game_id>/<mod>/ (a .gbox-mod.json marker; staging copies left out), from
    the markers only (sizes come from the index's background sizer)."""
    out = []
    for _gid, name, path, st in _mod_dirs(Path(root)):
        if name is not None:
            rec = read_folder(path, st)
            if rec:
                out.append(rec)
    return out


# ------------------------------------------------------------------------------------------------- the index

class Index:
    """The gallery's persistent view of the cache: marker facts per build plus sizes walked in the background.

    Readers (the request) only take a snapshot of memory; a scanner thread re-reads new / changed markers every
    REFRESH_EVERY seconds or when asked, and a sizer thread walks folders whose size is unknown for their marker."""

    def __init__(self, root: Path, path: Path | None, library: Path | None = None, every: float = REFRESH_EVERY):
        self.root, self.path, self.library, self.every = Path(root), (Path(path) if path else None), library, every
        self.lock = threading.Lock()
        self.recs: dict[str, dict] = {}            # "game_id/mod" -> record (replaced, never changed in place)
        self.version = 0                           # bumps on every change readers should see
        self.passes = 0                            # marker passes finished by this process
        self.scanning = False
        self.cycling = False                       # a pass and its card registration are under way
        self.asked = False                        # a refresh was asked for and has not finished yet
        self.sizing: str | None = None             # the folder being walked
        self.scanned_at = 0.0
        self.error = ""
        self._want = threading.Event()
        self._sized = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._saved_at = 0.0
        self._save_lock = threading.Lock()
        self.on_change = None                      # called with the records after a pass that changed them
        self.load()

    # -- persistence
    def load(self):
        if not self.path:
            return
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(doc, dict) or doc.get("version") != INDEX_VERSION or doc.get("root") != str(self.root):
            return                                 # another cache dir (or format): rebuilt from the markers
        mods = doc.get("mods")
        if isinstance(mods, dict):
            self.recs = {k: r for k, r in mods.items() if isinstance(r, dict) and r.get("name") and r.get("game_id")}
            self.scanned_at = float(doc.get("scanned_at") or 0)
            self.version += 1

    def save(self):
        if not self.path:
            return
        with self.lock:
            doc = {"version": INDEX_VERSION, "root": str(self.root), "scanned_at": self.scanned_at, "mods": dict(self.recs)}
        with self._save_lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_name(self.path.name + ".tmp")
                tmp.write_text(json.dumps(doc, separators=(",", ":"), default=str), encoding="utf-8")
                os.replace(tmp, self.path)
                self._saved_at = time.time()
            except OSError as e:
                self.error = f"index not saved: {e}"

    # -- readers (memory only)
    def forget(self, game_id: str, name: str) -> list[str]:
        """Drop a deleted build and its staged copies (<name>~<build>) from the index now (DELETE /api/builds);
        -> the keys dropped. The next marker pass would find them gone anyway."""
        with self.lock:
            gone = [k for k, r in self.recs.items() if r.get("game_id") == game_id
                    and (r.get("name") == name or str(r.get("name") or "").startswith(name + STAGED_SEP))]
            for k in gone:
                self.recs.pop(k, None)
            if gone:
                self.version += 1
        if gone:
            self.save()
        return gone

    def records(self) -> list[dict]:
        with self.lock:
            return [r for r in self.recs.values() if not r.get("staged")]

    def unsized(self) -> list[tuple[str, dict]]:
        with self.lock:
            todo = [(k, r) for k, r in self.recs.items() if not r.get("staged")
                    and (r.get("size_key") != r.get("marker") or r.get("diff_key") != r.get("marker"))]
        return sorted(todo, key=lambda kr: -(_built_of(kr[1]) or 0))      # newest builds get their size first

    def status(self) -> dict:
        with self.lock:
            pending = sum(1 for r in self.recs.values() if not r.get("staged") and r.get("size_key") != r.get("marker"))
            return {"indexing": self.passes == 0 or self.asked, "sizing": pending, "indexed_at": self.scanned_at,
                    **({"index_error": self.error} if self.error else {})}

    def idle(self) -> bool:
        with self.lock:
            busy = self.passes == 0 or self.scanning or self.cycling or self.asked or self.sizing is not None
        return not busy and not self._want.is_set() and not self.unsized()

    def wait(self, timeout: float = 10.0) -> bool:
        """Until a marker pass and every size walk are done (tests; the server never waits)."""
        end = time.time() + timeout
        while time.time() < end:
            if self.idle():
                return True
            time.sleep(0.01)
        return False

    # -- the marker pass
    def _read(self, path: Path, st, old: dict | None) -> dict:
        gid, name = path.parent.name, path.name
        sig = [st.st_mtime_ns, st.st_size]
        if (path / STAGED_MARK).exists():
            return {"name": name, "game_id": gid, "marker": sig, "staged": True}
        rec = dict(read_folder(path, st) or {"name": name, "game_id": gid, "meta": {}, "images": [],
                                               "marker_mtime": st.st_mtime})
        rec["marker"] = sig
        rec["donor_previews"] = donor_previews(changes_of(rec.get("meta") or {}), self.library)
        if old and old.get("size_key") == sig:     # same marker: the walked size still holds
            rec.update({k: old.get(k) for k in ("size", "own_size", "files", "size_key", "diff", "diff_key")})
        else:
            rec.update(size=None, own_size=None, files=None, size_key=None, diff=None, diff_key=None)
        return rec

    def refresh(self) -> bool:
        """Re-read new / changed markers (one stat per build otherwise); drop builds that are gone."""
        with self.lock:
            self.scanning = True
        changed = False
        try:
            if not self.root.is_dir():
                self.error = f"no mods folder at {self.root}"
                return False
            found, unlisted = {}, set()
            for gid, name, path, st in _mod_dirs(self.root):
                if self._stop.is_set():
                    return False
                if name is None:
                    unlisted.add(gid)
                    continue
                key = f"{gid}/{name}"
                with self.lock:
                    old = self.recs.get(key)
                if old is not None and old.get("marker") == [st.st_mtime_ns, st.st_size]:
                    found[key] = old
                    continue
                found[key] = self._read(path, st, old)
            with self.lock:
                for k, r in self.recs.items():     # a game folder that could not be listed keeps its builds
                    if r.get("game_id") in unlisted:
                        found.setdefault(k, r)
                changed = found.keys() != self.recs.keys() or any(found[k] is not self.recs[k] for k in found)
                if changed:
                    self.recs = found
                    self.version += 1
                self.scanned_at = time.time()
                self.error = ""
            if changed or not self._saved_at:
                self.save()
            if changed:
                self._sized.set()
            return changed
        finally:
            with self.lock:
                self.scanning = False
                self.passes += 1

    # -- threads
    def ask(self):
        """Refresh soon, in the background (POST .../refresh, ?fresh=true)."""
        with self.lock:
            self.asked = True
        self._want.set()
        self.start()

    def _scan_loop(self):
        while not self._stop.is_set():
            self._want.clear()
            with self.lock:
                asked, self.cycling = self.asked, True
            try:
                if self.refresh() and self.on_change:
                    self.on_change(self.records())
            except Exception as e:                 # noqa: BLE001 - the next pass retries
                self.error = f"index pass failed: {e}"
            with self.lock:
                self.cycling = False
                if asked and not self._want.is_set():
                    self.asked = False
            self._want.wait(self.every)

    def _size_loop(self):
        while not self._stop.is_set():
            todo = self.unsized()
            if not todo:
                self._sized.wait(self.every)
                self._sized.clear()
                continue
            key, rec = todo[0]
            with self.lock:
                self.sizing = key
            try:
                folder = self.root / rec["game_id"] / rec["name"]
                got = folder_size(folder, self._stop)
                diff = base_diff(folder, self.root.parent / "modbase" / rec["game_id"], self._stop) if got else None
            finally:
                with self.lock:
                    self.sizing = None
            if got is None or (diff is None and self._stop.is_set()):
                return
            with self.lock:
                cur = self.recs.get(key)
                if cur is not None and cur.get("marker") == rec.get("marker"):
                    self.recs[key] = {**cur, "size": got[0], "own_size": got[1], "files": got[2], "size_key": cur["marker"],
                                      "diff": diff, "diff_key": cur["marker"]}
                    self.version += 1
                else:                              # rebuilt or removed while walking: the next round sees it
                    continue
            if time.time() - self._saved_at >= SAVE_EVERY or not self.unsized():
                self.save()

    def start(self):
        with self.lock:
            if any(t.is_alive() for t in self._threads):
                return
            self._stop.clear()
            self._threads = [threading.Thread(target=self._scan_loop, name="built-mods-index", daemon=True),
                             threading.Thread(target=self._size_loop, name="built-mods-sizes", daemon=True)]
            threads = list(self._threads)
        for t in threads:
            t.start()

    def stop(self, timeout: float = 2.0):
        self._stop.set()
        self._want.set()
        self._sized.set()
        for t in self._threads:
            t.join(timeout)
        if self.passes:
            self.save()                            # sizes walked since the last save survive a restart


def _built_of(rec: dict) -> float:
    b = (rec.get("meta") or {}).get("built")
    return float(b) if isinstance(b, (int, float)) else float(rec.get("marker_mtime") or 0)


# ------------------------------------------------------------------------------------------------- normalizing

def writer_of(meta: dict, name: str) -> str:
    """Which writer built it: the marker's own `writer`, else the (gbox.<module>) its file notes name, else the
    mod name's prefix."""
    w = meta.get("writer")
    if isinstance(w, str) and w.strip():
        m = re.match(r"gbox\.([a-z0-9_]+)", w.strip())
        return m[1] if m else w.strip().split()[0]
    for f in meta.get("files") or []:
        m = re.search(r"\(gbox\.([a-z0-9_]+)", str(f))
        if m:
            return m[1]
    if meta.get("cast"):
        return "cast_swap"
    if "_" in name:
        return name.split("_", 1)[0]
    return "file mod" if meta.get("files") else "unknown"


def _as_list(v) -> list:
    if v is None or v == "":
        return []
    return list(v) if isinstance(v, (list, tuple)) else [v]


def changes_of(meta: dict) -> list[dict]:
    """donor -> slot rows from whichever shape the writer recorded (cast plan rows keep their status / reason)."""
    rows = []
    if isinstance(meta.get("cast"), list):                       # cast_swap: the per-slot report
        for r in meta["cast"]:
            if isinstance(r, dict):
                rows.append({"donor": r.get("character") or r.get("donor") or "", "slot": str(r.get("slot") or ""),
                             "status": r.get("status") or "", **({"reason": str(r["reason"])} if r.get("reason") else {})})
        return rows
    if isinstance(meta.get("roster"), list):                     # doa2 roster: [{fighter, character}]
        for r in meta["roster"]:
            if isinstance(r, dict):
                rows.append({"donor": r.get("character") or "", "slot": str(r.get("fighter") or r.get("slot") or "")})
        if rows:
            return rows
    donors = _as_list(meta.get("characters")) or _as_list(meta.get("character"))
    slots = _as_list(meta.get("replaces"))
    if not slots:
        enemies = meta.get("enemies")
        if isinstance(enemies, dict):                            # pso_enemy cast: {enemy: donor}
            return [{"donor": str(d), "slot": f"enemy:{k}"} for k, d in enemies.items()]
        slots = ([meta["slot"]] if meta.get("slot") else
                 [f"enemy:{e}" for e in enemies] if isinstance(enemies, list) else
                 [o if isinstance(o, str) else (o.get("name") or o.get("slot") or "") for o in _as_list(meta.get("outfits"))]
                 if meta.get("outfits") else [])
    if not donors and not slots:
        return rows
    if len(donors) == len(slots):
        return [{"donor": str(d), "slot": str(s)} for d, s in zip(donors, slots)]
    if len(donors) == 1:
        return [{"donor": str(donors[0]), "slot": ", ".join(str(s) for s in slots) or "player"}]
    return [{"donor": ", ".join(str(d) for d in donors), "slot": ", ".join(str(s) for s in slots)}]


def verified_of(meta: dict, card: dict | None) -> bool:
    if card and card.get("verified"):
        return True
    return any(meta.get(k) is True for k in VERIFIED_KEYS)


def tickets_of(meta: dict, card: dict | None) -> list[int]:
    out = set()
    for v in [*(card or {}).get("requests", [])] + [x for k in TICKET_KEYS for x in _as_list(meta.get(k))]:
        try:
            n = int(str(v).lstrip("#"))
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.add(n)
    return sorted(out)


def session_build(s: dict) -> str:
    """The build a session shows now: a model hot-swapped into memory (live_mod), else the collection build it booted.
    A staged copy (<mod>~<build>, launched while an older copy was held open) is that same build. "" = the original game.
    The clients' twin: clients/web/viz/build-shot.js sessionBuild."""
    mod = s.get("live_mod") or s.get("collection_mod") or s.get("mod") or ""
    return str(mod).split(STAGED_SEP)[0]


def card_mod(card: dict) -> str:
    """The file mod a card boots (its @launch call), if any."""
    for c in card.get("calls") or []:
        if c.get("tool") == "@launch" and (c.get("input") or {}).get("mod"):
            return c["input"]["mod"]
    return ""


def card_index(cards: list[dict]) -> dict:
    idx = {}
    for c in sorted(cards, key=lambda c: c.get("ts") or 0):     # newest card wins
        mod = card_mod(c)
        if mod:
            idx[(c.get("game_id") or "", mod)] = c
    return idx


def launch_index(sessions: list[dict], jobs: list[dict]) -> dict:
    """(game_id, mod) -> the newest launch result: a session (running / ended + its exit) or a failed launch job."""
    out = {}
    for s in sessions:
        mod = s.get("collection_mod") or s.get("mod")
        if not mod:
            continue
        k = (s.get("game_id") or "", mod)
        t = s.get("started") or 0
        if k not in out or t > out[k]["ts"]:
            ex = s.get("exit")
            out[k] = {"ts": t, "state": s.get("state") or "", "session_id": s.get("session_id"),
                      "ended": s.get("ended"), "adapter": s.get("adapter"),
                      **({"exit": ex if isinstance(ex, str) else json.dumps(ex, default=str)[:300]} if ex else {})}
    for j in jobs:
        if j.get("tool") != "launch_game" or j.get("state") not in ("failed", "cancelled"):
            continue
        inp = j.get("input") or {}
        mod = inp.get("mod")
        gid = (inp.get("game") or {}).get("game_id") if isinstance(inp.get("game"), dict) else ""
        if not mod or not gid:
            continue
        k, t = (gid, mod), j.get("finished") or j.get("updated") or j.get("created") or 0
        if k not in out or t > out[k]["ts"]:
            out[k] = {"ts": t, "state": j["state"], "job_id": j.get("id"), "error": str(j.get("error") or "")[:400]}
    return out


def play_counts(store, sessions: list[dict]) -> dict:
    """Recorded player starts per collection build, excluding failed launches and agent tests."""
    labels = {r.get('session_id'): r.get('owner') for r in _fields(store, 'slabel', ('session_id', 'owner'))}
    try:
        with store.lock:
            rows = store.db.execute("SELECT json_extract(body,'$.id'), json_extract(body,'$.output.session_id') "
                                    "FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='launch_game' "
                                    "AND json_extract(body,'$.agent_use')=1").fetchall()
        agent_jobs = {r[0] for r in rows}
        agent_sessions = {r[1] for r in rows if r[1]}
    except Exception:  # alternate store implementations
        jobs = [j for j in store.all('job') if j.get('tool') == 'launch_game' and j.get('agent_use')]
        agent_jobs = {j.get('id') for j in jobs}
        agent_sessions = {(j.get('output') or {}).get('session_id') for j in jobs}
    out, seen = {}, set()
    for session in sessions:
        sid = session.get('session_id')
        if not sid or sid in seen or not session.get('started') or session.get('state') not in ('running', 'paused', 'ended', 'stopped', 'completed'):
            continue
        seen.add(sid)
        owner = labels.get(sid)
        if owner != 'you' and (owner == 'agent' or sid in agent_sessions or sid.split('-', 1)[-1] in agent_jobs):
            continue
        mod = str(session.get('collection_mod') or session.get('mod') or '').split(STAGED_SEP)[0]
        if not mod:
            continue
        row = out.setdefault((session.get('game_id') or '', mod), {'play_count': 0, 'last_played': 0})
        row['play_count'] += 1
        row['last_played'] = max(row['last_played'], session['started'])
    return out


def donor_previews(changes: list[dict], library: Path | None) -> list[dict]:
    out, seen = [], set()
    if not library:
        return out
    for r in changes:
        for slug in str(r.get("donor") or "").split(","):
            slug = slug.strip()
            if not slug or slug in seen or not _safe_component(slug):
                continue
            seen.add(slug)
            if (Path(library) / slug / "preview.png").is_file():
                out.append({"slug": slug, "url": f"/api/characters/{slug}/preview"})
    return out


def game_title_of(gid: str, meta: dict, card: dict | None, catalog: dict | None) -> str:
    """The game's name: the catalog's title, else what the card or the writer's marker recorded, else the id."""
    for v in ((catalog or {}).get("title"), (card or {}).get("game_title"), meta.get("game_title"),
              meta.get("game") if isinstance(meta.get("game"), str) else None,
              (meta.get("game") or {}).get("title") if isinstance(meta.get("game"), dict) else None):
        if isinstance(v, str) and v.strip():
            return v.strip()
    return gid


FRAME_LIMIT = 12                           # newest in-game frames joined per build


def _source_of(name: str, prov: dict) -> str:
    if prov.get("task_evidence"):
        return "task evidence"
    if "captured" in prov and str(name).startswith("observation"):
        return "live observation"
    if prov.get("slot") is not None or str(name).startswith("state"):
        return f"save state {prov['slot']}" if prov.get("slot") is not None else "save state"
    return str(prov.get("tool") or "frame")


def session_frames(store, sessions: list[dict], limit: int = FRAME_LIMIT) -> dict:
    """(game_id, mod) -> the newest real frames captured from sessions that ran that build: get_frame grabs, save-state
    pictures, live observations and task evidence. A build launched and watched but never saved as a card still shows
    what it looked like running. Captures with a window over the game (covered > 0) are skipped - they hold desktop
    pixels, not the build."""
    by_sid = {}
    for s in sessions:
        mod = s.get("collection_mod") or s.get("mod")
        if s.get("session_id") and mod:
            by_sid[s["session_id"]] = (s.get("game_id") or "", mod)
    if not by_sid:
        return {}
    out: dict = {}
    for a in reversed(_fields(store, "artifact", ("sha256", "name", "media_type", "provenance"))):   # newest first
        prov = a.get("provenance")
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except ValueError:
                continue
        if not isinstance(prov, dict) or not str(a.get("media_type") or "").startswith("image/") or not a.get("sha256"):
            continue
        key = by_sid.get(prov.get("session") or prov.get("session_id"))
        if not key:
            continue
        try:
            if int(prov.get("covered") or 0) > 0:
                continue
        except (TypeError, ValueError):
            continue
        got = out.setdefault(key, [])
        if len(got) < limit and all(f["sha256"] != a["sha256"] for f in got):
            got.append({"sha256": a["sha256"], "url": f"/api/artifacts/{a['sha256']}",
                        "session_id": prov.get("session") or prov.get("session_id"),
                        "source": _source_of(a.get("name") or "", prov)})
    return out


def entry(rec: dict, card: dict | None, launch: dict | None, catalog: dict | None, requests: dict, library,
          frames: list[dict] | None = None, display_name: str = "", launch_report: dict | None = None,
          favorite: bool = False, reported: dict | None = None) -> dict:
    meta, gid, name = rec.get("meta") or {}, rec["game_id"], rec["name"]
    changes = changes_of(meta)
    built = meta.get("built")
    built = float(built) if isinstance(built, (int, float)) else rec.get("marker_mtime") or 0
    base = f"/api/mods/built/{gid}/{name}/image/"
    shots = [s for s in [*(card or {}).get("shots", [])] if s]
    if card and card.get("thumb") and card["thumb"] not in shots:
        shots.insert(0, card["thumb"])
    tickets = tickets_of(meta, card)
    if launch_report and launch_report.get("number") and launch_report["number"] not in tickets:
        tickets = tickets + [launch_report["number"]]       # its "Open request" lookup finds the launch failure ticket
    title = game_title_of(gid, meta, card, catalog)
    sc = meta.get("showcase") if isinstance(meta.get("showcase"), dict) else None
    fits = [{"slot": str(p.get("slot") or ""), "label": str(p.get("label") or p.get("slot") or ""), "url": p["preview"]}
            for p in (sc or {}).get("previews") or []
            if isinstance(p, dict) and isinstance(p.get("preview"), str) and p["preview"].startswith("/api/")]
    original = meta.get("title") or (card or {}).get("title") or name
    return {
        "key": f"{gid}/{name}", "name": name, "game_id": gid, "title": title, "game_title": title,
        "platform": (catalog or {}).get("platform") or "",
        # the operator's own name for the build (Builds view, the Mods card ✎) wins everywhere a build is listed
        "mod_title": display_name or original, "display_name": display_name, "original_title": original,
        "favorite": bool(favorite),                # ☆/★ on the Mods page and in Builds (FAV_KIND): listed first
        # "What this changes" (#1656): recorded facts, else the file comparison with the base copy, else inferred
        "what": what_of(rec, card), "diff": rec.get("diff"), "reported": reported or None,
        "writer": writer_of(meta, name), "changes": changes, "cast": isinstance(meta.get("cast"), list),
        "report": meta.get("cast") if isinstance(meta.get("cast"), list) else None,
        "cast_source": meta.get("cast_source") or "",
        "built": built, "size": rec.get("size"), "own_size": rec.get("own_size"), "files": rec.get("files"),
        "image": meta.get("image") or "",
        "verified": verified_of(meta, card), "last_launch": launch,
        "images": [{"name": n, "url": base + n} for n in rec.get("images") or []],
        "donor_previews": rec["donor_previews"] if "donor_previews" in rec else donor_previews(changes, library),
        "shots": [{"sha256": s, "url": f"/api/artifacts/{s}"} for s in shots],
        "frames": [f for f in frames or [] if f["sha256"] not in shots],
        "card_id": (card or {}).get("id") or "", "state_slot": (card or {}).get("state_slot"),
        "video": (card or {}).get("video") or "",
        # a Sonic showcase test build (gbox.sonic_showcase): the Mods page's "Sonic showcase" filter
        "showcase": bool(sc) and name.startswith("showcase_"), "fit_previews": fits[:MAX_IMAGES],
        "tickets": [{"number": n, **({k: requests[n].get(k) for k in ("id", "title", "status")} if n in requests else {})}
                    for n in tickets],
        # the launch failure ticket for this build (gbox/launch_failures.py): "Reported as #N" / "Fixed, verified"
        "launch_report": launch_report or None,
    }


def card_for(rec: dict, existing: dict, catalog: dict | None) -> tuple[str, dict]:
    """A mod card that launches this built folder (the shape POST /api/mods saves)."""
    meta, gid, name = rec["meta"], rec["game_id"], rec["name"]
    changes = changes_of(meta)
    title = str(meta.get("title") or name)[:120]
    mid = hashlib.sha1(f"{gid}:{title.lower()}".encode()).hexdigest()[:12]
    other = existing.get(mid)
    if other and card_mod(other) != name:                         # same title, another mod: keep both cards
        title = f"{title} [{name}]"
        mid = hashlib.sha1(f"{gid}:{title.lower()}".encode()).hexdigest()[:12]
    what = "; ".join(f"{r['donor'] or '?'} -> {r['slot'] or '?'}" for r in changes)[:500]
    built = meta.get("built") if isinstance(meta.get("built"), (int, float)) else rec.get("marker_mtime") or time.time()
    return mid, {"id": mid, "title": title, "calls": [{"tool": "@launch", "input": {"mod": name}}], "game_id": gid,
                 "game_title": (catalog or {}).get("title") or meta.get("game_title") or "",
                 "desc": f"Built by {writer_of(meta, name)}" + (f": {what}" if what else "") + " (registered from the built mod folder)",
                 "verified": verified_of(meta, None), "requests": tickets_of(meta, None),
                 "by": "mods-gallery", "auto_registered": True, "ts": float(built)}


def register_missing(store, records: list[dict]) -> list[str]:
    """Save a mod card for every built folder no card launches yet; returns the new card ids (idempotent)."""
    made = []
    with store.lock:
        cards = store.all("mod")
        have = card_index(cards)
        by_id = {c.get("id"): c for c in cards}
        for rec in records:
            if (rec["game_id"], rec["name"]) in have:
                continue
            mid, doc = card_for(rec, by_id, catalog_of(store, rec["game_id"], rec.get("meta") or {}, {}))
            if mid in by_id and card_mod(by_id[mid]) == rec["name"]:
                continue
            store.put("mod", mid, doc)
            by_id[mid] = doc
            have[(rec["game_id"], rec["name"])] = doc
            made.append(mid)
    for mid in made:
        store.audit("mods-gallery", "mod.register", mid, {"from": "built folder"})
    return made


def supersede(store, doc: dict) -> dict:
    """A card saved through POST /api/mods for a build the gallery registered first: drop the stand-in card (keeping its
    in-game shots, thumb and tickets on the new one) so a build has one card."""
    doc = {k: v for k, v in doc.items() if k != "auto_registered"}     # saved over a stand-in with the same title
    mod = card_mod(doc)
    if not mod:
        return doc
    for old in store.all("mod"):
        if (old.get("auto_registered") and old.get("id") != doc.get("id") and old.get("game_id") == doc.get("game_id")
                and card_mod(old) == mod):
            shots = [*(doc.get("shots") or []), *[s for s in old.get("shots") or [] if s not in (doc.get("shots") or [])]]
            doc = doc | ({"shots": shots[:24]} if shots else {}) | ({"thumb": old["thumb"]} if old.get("thumb") and not doc.get("thumb") else {})
            doc["requests"] = sorted(set(doc.get("requests") or []) | set(old.get("requests") or []))
            store.delete("mod", old["id"])
    return doc


def _fields(store, kind: str, fields: tuple[str, ...]) -> list[dict]:
    """Just these top-level fields of every document of a kind (inbox threads, session logs stay undecoded)."""
    try:
        cols = ", ".join(f"json_extract(body,'$.{f}')" for f in fields)
        with store.lock:
            rows = store.db.execute(f"SELECT {cols} FROM docs WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [dict(zip(fields, r)) for r in rows]
    except Exception:                                            # noqa: BLE001 - another store: decode them all
        return [{f: d.get(f) for f in fields} for d in store.all(kind)]


def _failed_launches(store) -> list[dict]:
    try:
        return store.jobs(states=("failed", "cancelled"))
    except Exception:                                            # noqa: BLE001
        return [j for j in store.all("job") if j.get("state") in ("failed", "cancelled")]


def library_of(config):
    try:
        from . import characters
        return characters.library_root(config)
    except Exception:                                            # noqa: BLE001 - previews are a convenience
        return None


def catalog_of(store, gid: str, meta: dict, seen: dict) -> dict | None:
    """The catalog entry for a build's game: its folder's game_id, else the game_id its marker names."""
    keys = [gid] + [k for k in [meta.get("game_id")] if isinstance(k, str) and k and k != gid]
    for k in keys:
        if k not in seen:
            try:
                seen[k] = store.catalog_get(k)
            except Exception:                                    # noqa: BLE001
                seen[k] = None
        if seen[k]:
            return seen[k]
    return None


NAME_KIND = "build_name"                   # store kind: "game_id/mod" -> {key, display_name, by, ts} (gbox.builds)


def display_names(store) -> dict:
    """"game_id/mod" -> the operator's display name for that build (folders are never renamed)."""
    try:
        rows = _fields(store, NAME_KIND, ("key", "display_name"))
    except Exception:                                            # noqa: BLE001
        return {}
    return {r["key"]: r["display_name"].strip() for r in rows if r.get("key") and isinstance(r.get("display_name"), str)
            and r["display_name"].strip()}


FAV_KIND = "build_favorite"                # store kind: "game_id/mod" -> {key, by, ts} (gbox.builds): the operator's ★
REPORT_KIND = "build_report"               # store kind: "game_id/mod" -> {key, number, id, reason, ts}: "Reported #N"


def build_reports(store) -> dict:
    """"game_id/mod" -> {number, id, reason} of the newest ⚑ report filed on that build."""
    try:
        rows = _fields(store, REPORT_KIND, ("key", "number", "id", "reason"))
    except Exception:                                            # noqa: BLE001
        return {}
    return {r["key"]: {k: r.get(k) for k in ("number", "id", "reason")} for r in rows if isinstance(r.get("key"), str)}


def favorites(store) -> set[str]:
    """The "game_id/mod" keys the operator starred: listed first, a Favorites group at the top of Special builds, and
    never evicted by a disk budget (protected())."""
    try:
        return {r["key"] for r in _fields(store, FAV_KIND, ("key",)) if isinstance(r.get("key"), str) and r["key"]}
    except Exception:                                            # noqa: BLE001
        return set()


def is_favorite(store, game_id: str, mod: str) -> bool:
    try:
        return store.get(FAV_KIND, f"{game_id}/{mod}") is not None
    except Exception:                                            # noqa: BLE001
        return False


def label_of(store, game_id: str, mod: str, fallback: str = "") -> str:
    """The name a build shows under (launch bar, loader, sessions, Mini window title): the operator's display name,
    else `fallback`, else the folder name."""
    if not mod:
        return fallback
    try:
        doc = store.get(NAME_KIND, f"{game_id}/{mod}") or {}
    except Exception:                                            # noqa: BLE001
        doc = {}
    v = doc.get("display_name") if isinstance(doc.get("display_name"), str) else ""
    return v.strip() or fallback or mod


def what_of(rec: dict, card: dict | None = None) -> dict:
    """The build's "What this changes" summary (gbox.build_summary); never fails a listing."""
    meta = rec.get("meta") or {}
    try:
        from . import build_summary
        return build_summary.summarize(rec["name"], rec["game_id"], meta, card, rec.get("diff"),
                                       writer_of(meta, rec["name"]),
                                       meta.get("recipe") if isinstance(meta.get("recipe"), dict) else None)
    except Exception as e:                                       # noqa: BLE001
        return {"lines": [], "where": "", "status": "unknown", "badge": "Changes not recorded", "inferred": False,
                "sources": [], "error": str(e)[:200]}


def protected(store, game_id: str, mod: str) -> str:
    """Why a disk budget (the Sonic showcase's LRU eviction, any later sweep of built mods) must never remove this
    build, else ''. The cache's own eviction (catalog.evict) never touches mods/ at all (catalog.EVICT_KEEP)."""
    return "the operator favorited it" if is_favorite(store, game_id, mod) else ""


def gallery(store, config, records: list[dict] | None = None, *, register: bool = True) -> dict:
    """The whole gallery, newest build first: the index's records (or a marker scan) joined with the store. Touches
    no mod folder when records are given."""
    root = mods_root(config)
    library = library_of(config)
    if records is None:
        records = scan(root)
    made = register_missing(store, records) if register and records else []
    cards = card_index(store.all("mod"))
    sessions = _fields(store, "session", ("session_id", "game_id", "mod", "collection_mod", "started", "ended",
                                          "state", "adapter", "exit"))
    for s in sessions:
        if isinstance(s.get("exit"), str) and s["exit"][:1] in "{[":
            try:
                s["exit"] = json.loads(s["exit"])
            except ValueError:
                pass
    launches = launch_index(sessions, _failed_launches(store))
    plays = play_counts(store, sessions)
    names = display_names(store)
    favs, reported = favorites(store), build_reports(store)
    broken = {r['key']: r for r in _fields(store, 'build_broken', ('key', 'state', 'number', 'request_id', 'built', 'error'))}
    try:
        frames = session_frames(store, sessions)
    except Exception:                                            # noqa: BLE001 - frames are a convenience
        frames = {}
    requests = {}
    for r in _fields(store, "request", ("id", "number", "title", "status")):
        if isinstance(r.get("number"), int):
            requests[r["number"]] = r
    try:
        from . import launch_failures
        reports = launch_failures.index(store)
    except Exception:                                            # noqa: BLE001 - the badge is a convenience
        reports = {}
    catalogs: dict = {}
    items = []
    from .custom_build_unlocks import badge
    for rec in records:
        gid = rec["game_id"]
        items.append(entry(rec, cards.get((gid, rec["name"])), launches.get((gid, rec["name"])),
                           catalog_of(store, gid, rec.get("meta") or {}, catalogs), requests, library,
                           frames=frames.get((gid, rec["name"])), display_name=names.get(f"{gid}/{rec['name']}", ""),
                           launch_report=reports.get((gid, rec["name"])),
                           favorite=f"{gid}/{rec['name']}" in favs, reported=reported.get(f"{gid}/{rec['name']}")))
        items[-1]['unlocks'] = badge(store, rec)
        items[-1].update(plays.get((gid, rec['name']), {'play_count': 0, 'last_played': 0}))
    for item in items:
        flag = broken.get(item['key'])
        if flag and flag.get('state') != 'deleted' and (not flag.get('built') or item.get('built') == flag['built']):
            item['broken'] = flag
    items.sort(key=lambda m: -(m["built"] or 0))
    return {"items": items, "registered": made, "cache_dir": str(root)}


def select(items: list[dict], game_id: str = "", writer: str = "", q: str = "", kind: str = "",
           favorite: bool = False) -> list[dict]:
    """kind=showcase: only the Sonic showcase builds; kind=other: everything else; favorite: only the ★ ones."""
    words = [w for w in q.lower().split() if w]
    if kind in ("showcase", "other"):
        items = [m for m in items if bool(m.get("showcase")) == (kind == "showcase")]

    def hay(m):
        return " ".join([m["name"], m["game_id"], m["title"], m["mod_title"], m.get("original_title") or "", m["writer"],
                         *(f"{r.get('donor')} {r.get('slot')}" for r in m["changes"]),
                         *(f"#{t['number']}" for t in m["tickets"])]).lower()
    return [m for m in items if (not game_id or m["game_id"] == game_id) and (not writer or m["writer"] == writer)
            and (not favorite or m.get("favorite")) and all(w in hay(m) for w in words)]


def facets(items: list[dict]) -> dict:
    games, writers = {}, {}
    for m in items:
        g = games.setdefault(m["game_id"], {"game_id": m["game_id"], "title": m["title"], "count": 0})
        g["count"] += 1
        writers[m["writer"]] = writers.get(m["writer"], 0) + 1
    return {"games": sorted(games.values(), key=lambda g: g["title"].lower()),
            "writers": [{"writer": w, "count": n} for w, n in sorted(writers.items())],
            "showcase": sum(1 for m in items if m.get("showcase"))}


# ------------------------------------------------------------------------------------------------- routes

def image_path(config, game_id: str, mod: str, name: str) -> Path:
    """The preview picture a gallery card links to, or ValueError (outside the folder, not a picture, staged copy)."""
    if not (_safe_component(game_id) and _safe_component(mod)) or STAGED_SEP in mod:
        raise ValueError("bad mod")
    root = mods_root(config).resolve()
    folder = (root / game_id / mod)
    if not folder.resolve().is_relative_to((root / game_id).resolve()) or not (folder / MARKER).is_file() or (folder / STAGED_MARK).exists():
        raise ValueError("no such built mod")
    parts = name.split("/") if isinstance(name, str) else []
    if not parts or len(parts) > 2 or any(not _safe_component(p) for p in parts) or (len(parts) == 2 and parts[0] not in PREVIEW_DIRS):
        raise ValueError("bad picture name")
    f = folder.joinpath(*parts)
    if f.suffix.lower() not in IMAGE_TYPES or f.is_symlink() or not f.resolve().is_relative_to(folder.resolve()) or not f.is_file():
        raise ValueError("no such picture")
    return f


def routes(app, store, config, auth):
    index = Index(mods_root(config), Path(config.data_dir) / INDEX_FILE, library_of(config))
    app.state.built_mods = index
    cache = {"at": 0.0, "version": -1, "data": None}
    lock = threading.Lock()

    def current(fresh: bool = False) -> dict:
        """The joined gallery for the index's current records: rebuilt when the index changes, a card is saved
        (built_mods_invalidate) or after TTL (sessions / jobs). Memory + the store only, never the mod folders."""
        with lock:
            if (fresh or cache["data"] is None or cache["version"] != index.version
                    or time.time() - cache["at"] > TTL):
                version = index.version
                cache["data"], cache["at"], cache["version"] = gallery(store, config, index.records()), time.time(), version
            return cache["data"]

    app.state.built_mods_invalidate = lambda: cache.update(at=0.0)
    app.state.built_mods_current = current             # the joined gallery (gbox.special_builds groups it per game)

    @app.get("/api/mods/built")
    def built_list(game_id: str = "", writer: str = "", q: str = "", offset: int = 0, limit: int = 0,
                   fresh: bool = False, kind: str = "", favorite: bool = False, actor=Depends(auth)):
        """Every built mod folder in this node's cache, newest first, joined with its mod card (filters + pages).
        Answers from the index at once; `indexing` while a marker pass is due, `sizing` = folders still being sized
        (size: null). fresh=true rejoins the cards now and asks for an incremental pass in the background."""
        index.start()
        if fresh:
            index.ask()
        data = current(fresh)
        items = data["items"]
        picked = select(items, game_id, writer, q, kind, favorite)
        offset = max(0, offset)
        page = picked[offset:offset + limit] if limit > 0 else picked[offset:]
        return {"total": len(picked), "all": len(items), "offset": offset, "limit": limit, "items": page,
                **facets(items), "registered": data["registered"], "cache_dir": data["cache_dir"], **index.status()}

    @app.post("/api/mods/built/refresh")
    def built_refresh(actor=Depends(auth)):
        """Re-read new / changed build markers (and size new folders) in the background; poll GET for the result."""
        index.ask()
        cache.update(at=0.0)
        return {"ok": True, **index.status()}

    @app.get("/api/mods/built/{game_id}/{mod}/image/{name:path}")
    def built_image(game_id: str, mod: str, name: str, actor=Depends(auth)):
        try:
            f = image_path(config, game_id, mod, name)
        except (ValueError, OSError):
            raise HTTPException(404, "no such picture") from None
        return FileResponse(f, media_type=IMAGE_TYPES[f.suffix.lower()], headers={"cache-control": "max-age=300"})

    def registered(records: list[dict]):
        # cards for builds nobody saved, without waiting for a gallery visit (store only, after each changed pass)
        if register_missing(store, records):
            cache.update(at=0.0)

    index.on_change = registered

    @app.on_event("startup")
    async def _index_built():
        index.start()

    @app.on_event("shutdown")
    async def _stop_index():
        index.stop()
