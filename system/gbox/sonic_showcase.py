"""Sonic showcase: a background service on the control plane (the Spark) that keeps a test build of the operator's
favorite and recently played titles with their key people replaced by the Sonic Adventure 1 + 2 cast.

Every pass (docs/sonic_showcase.md):

  * titles: favorites first (most recently played first), then recently played ones, each list capped by settings;
    the donor games themselves (Sonic Adventure 1 / 2) are left out;
  * a title with a routed character writer: the SA1 / SA2 donors are collected first (characters op=collect on the
    Spark), the cast-swap plan is made here (gbox.cast_swap.plan, source=sonic, the whole cast when it is small, else
    the player + main cast) and, when its plan hash differs from the last build, ONE low-priority job
    `characters op=cast_swap source=sonic mod_name=showcase_sonic_<title> showcase=true launch=false` is queued on the
    Spark worker. An unchanged plan is never built again;
  * a title without a writer: it is put in Hermes's readiness queue (gbox.hermes_work_queue.ensure_item) with the
    assimilate fingerprint attached, so the inventory -> analysis (Ghidra / REA) -> reader -> writer stages proceed,
    and the record says what is missing;
  * a record per title (store kind "showcase"): stage reached, mod, plan hash, build time, slots replaced, fitting
    previews; the Mods page ("Sonic showcase" filter) and the game menu's Special builds show it.

Limits: nothing runs while the operator plays on the Spark or a launch is in flight (the deploy cron's session rule,
gbox.hermes_activation); one job at a time; builds_per_hour; a pause switch; builds only when the mod cache is on the
external HDD with min_free_gb free; a disk budget (budget_gb) enforced by LRU eviction of showcase builds ONLY
(folders named showcase_sonic_* whose marker carries the showcase record, never one a running session uses or a mod
card the operator saved); identical files of a new build are hard-linked to the game's base copy / other showcase
builds (dedupe).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from pydantic import BaseModel

SOURCE = "sonic"
PREFIX = "showcase_sonic_"
DONOR_READERS = ("sa1", "sa2")             # characters.DEDICATED names of the donor games' readers
MARKER = ".gbox-mod.json"
KIND = "showcase"                          # store docs: one record per title
SETTING = "showcase"                       # store setting: the operator's overrides of [showcase]
STATE = "showcase_state"                   # store setting: the service's own status
FOREGROUND = ("launch_game", "session_swap")   # a launch in flight: wait (it stages the disc on the same HDD)
READINESS_PER_PASS = 2                     # fingerprints read owned files: at most this many titles per pass
DEFAULT_ESTIMATE = 2 << 30                 # a first build's size guess for the budget (bytes)
LAST_RESULTS = 20
EDITABLE = {"enabled": bool, "paused": bool, "favorites": int, "recent": int, "budget_gb": float,
            "builds_per_hour": int, "whole_cast_max_slots": int, "interval_s": float, "dedupe": bool,
            "pause_while_playing_anywhere": bool}
LIMITS = {"favorites": (0, 200), "recent": (0, 100), "budget_gb": (1, 4000), "builds_per_hour": (0, 60),
          "whole_cast_max_slots": (1, 400), "interval_s": (30, 86400)}
# stages a record can be in; "due" ones are looked at again on the next pass
WAITING = {"queued", "building", "deferred", "collecting_donors", "waiting_storage", "rate_limited", "over_budget",
           "readiness_pending", "no_donors"}


# ------------------------------------------------------------------------------------------------- settings

def settings(store, config) -> dict:
    """[showcase] from gbox.toml with the operator's saved overrides (the Settings card / PUT /api/showcase)."""
    from .config import ShowcaseConfig
    base = (getattr(config, "showcase", None) or ShowcaseConfig()).model_dump()
    saved = (store.get("setting", SETTING) or {}) if store is not None else {}
    for k, kind in EDITABLE.items():
        if k in saved and saved[k] is not None:
            base[k] = clamp(k, kind(saved[k]))
    return base


def clamp(key: str, value):
    lo, hi = LIMITS.get(key, (None, None))
    if lo is None or isinstance(value, bool):
        return value
    return type(value)(min(hi, max(lo, value)))


def validate(body: dict) -> dict:
    """The editable fields of a PUT body, typed and clamped; ValueError names an unknown or bad field."""
    out = {}
    for k, v in (body or {}).items():
        if v is None:
            continue
        if k not in EDITABLE:
            raise ValueError(f"{k} is not a showcase setting (editable: {', '.join(EDITABLE)})")
        kind = EDITABLE[k]
        if kind is bool and not isinstance(v, bool):
            raise ValueError(f"{k} must be true or false")
        try:
            out[k] = clamp(k, kind(v))
        except (TypeError, ValueError):
            raise ValueError(f"{k}={v!r} is not a {kind.__name__}") from None
    return out


# ------------------------------------------------------------------------------------------------- names, titles

def mod_name_for(game: dict) -> str:
    """showcase_sonic_<title words>: one stable folder per title (the plan hash in its marker decides a rebuild)."""
    words = "_".join(re.findall(r"[a-z0-9]+", str(game.get("title") or "").lower()))[:48].strip("_")
    return PREFIX + (words or str(game.get("game_id") or "game"))


def donor_reader(game: dict) -> str | None:
    """'sa1' / 'sa2' when this catalog title is one of the donor games, else None."""
    from . import characters as C
    t, plat = (game.get("title") or "").lower(), game.get("platform") or ""
    for name, test, _roster, _run in C.DEDICATED:
        if name in DONOR_READERS:
            try:
                if test(t, plat):
                    return name
            except Exception:                              # noqa: BLE001 - a reader test never breaks the pass
                continue
    return None


def select_titles(store, s: dict) -> list[dict]:
    """Favorites first (most recently played first, then most recently starred), then recently played titles that are
    not favorites; each list capped (s.favorites, s.recent). Rows are catalog entries + origin."""
    favs = []
    for f in store.favorites():
        if not f.get("in_catalog"):
            continue
        g = store.catalog_get(f["game_id"])
        if g:
            favs.append(g | {"origin": "favorite", "favorited": f.get("favorited") or 0})
    favs.sort(key=lambda g: (-(g.get("last_played") or 0), -(g.get("favorited") or 0), (g.get("title") or "").lower()))
    favs = favs[:max(0, int(s.get("favorites", 0)))]
    seen = {g["game_id"] for g in favs}
    n = max(0, int(s.get("recent", 0)))
    recent = []
    if n:
        _total, rows = store.search(recent=True, sort="recent", limit=n + len(seen))
        recent = [g | {"origin": "recent"} for g in rows if g["game_id"] not in seen][:n]
    return favs + recent


# ------------------------------------------------------------------------------------------------- idle gating

def idle_reason(sessions: list[dict], jobs: list[dict], workers: list[dict], s: dict) -> str:
    """'' when a showcase job may start / keep running, else why not: a game running on the Spark (the deploy cron's
    rule, gbox.hermes_activation.idle_reason: "Waiting for the Spark game session to finish."), a launch queued or
    running anywhere (it stages the disc on the same HDD), or - with pause_while_playing_anywhere - any running game.
    A session on a worker this list doesn't know counts as the Spark's (conservative)."""
    os_of = {}
    for w in workers or []:
        for k in (w.get("id"), w.get("name")):
            if k:
                os_of[k] = w.get("os")
    for x in sessions or []:
        if x.get("state") != "running":
            continue
        sid = str(x.get("session_id") or "")
        wid = x.get("worker_id") or sid.split("-", 1)[0]
        where = os_of.get(wid)
        if where != "windows":
            return "Waiting for the Spark game session to finish."
        if s.get("pause_while_playing_anywhere"):
            return f"Waiting for the game on {wid} to finish (pause_while_playing_anywhere)."
    for j in jobs or []:
        if j.get("tool") in FOREGROUND and j.get("state") in ("queued", "running"):
            return "Waiting for a game launch to finish."
    return ""


# ------------------------------------------------------------------------------------------------- disk

def _is_showcase(folder: Path) -> dict | None:
    """The showcase record in a folder's marker when the folder is one of ours (name prefix + marker + not a link)."""
    try:
        if not folder.name.startswith(PREFIX) or folder.is_symlink() or not folder.is_dir():
            return None
        meta = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) and isinstance(meta.get("showcase"), dict) else None


def showcase_folders(root: Path) -> list[dict]:
    """Every showcase build under <cache>/mods: {game_id, name, path, meta}. Other folders are never listed."""
    out = []
    try:
        games = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        return out
    for g in games:
        try:
            if not g.is_dir(follow_symlinks=False):
                continue
            mods = sorted(os.scandir(g.path), key=lambda e: e.name)
        except OSError:
            continue
        for m in mods:
            if not m.name.startswith(PREFIX):
                continue
            meta = _is_showcase(Path(m.path))
            if meta is not None:
                out.append({"game_id": g.name, "name": m.name, "path": Path(m.path), "meta": meta})
    return out


def _files(folder: Path):
    for d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if not os.path.islink(os.path.join(d, x))]
        for f in files:
            p = os.path.join(d, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if os.path.isfile(p) and not os.path.islink(p):
                yield Path(p), st


def usage(folders: list[dict]) -> dict:
    """Bytes the showcase builds hold: a file counts when every hard link to it is inside showcase builds (deleting
    them frees it), once per inode, charged to the folders sharing it; a file linked to a base copy or another mod
    frees nothing and costs nothing. -> {total, per: {key: bytes}, linked: bytes shared with the outside}."""
    inodes: dict = {}
    for f in folders:
        key = f"{f['game_id']}/{f['name']}"
        for _p, st in _files(f["path"]):
            ino = (st.st_dev, st.st_ino) if st.st_ino else (key, str(_p))
            r = inodes.setdefault(ino, {"size": st.st_size, "nlink": max(1, st.st_nlink), "seen": 0, "keys": set()})
            r["seen"] += 1
            r["keys"].add(key)
    per: dict = {f"{f['game_id']}/{f['name']}": 0 for f in folders}
    total = linked = 0
    for r in inodes.values():
        if r["seen"] >= r["nlink"]:
            total += r["size"]
            share = r["size"] // len(r["keys"])
            for k in r["keys"]:
                per[k] += share
        else:
            linked += r["size"]
    return {"total": total, "per": per, "linked": linked}


def _sha256(path: Path, cache: dict) -> str:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in cache:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        cache[key] = h.hexdigest()
    return cache[key]


def dedupe(folder: Path, refs: list[Path], min_bytes: int, hashes: dict | None = None) -> dict:
    """Replace files of a new showcase build that are byte-identical to a file under refs (the game's base copy, its
    unpacked disc, other showcase builds: folders that are never written in place) with a hard link to it. Only files
    inside `folder` change; the marker is never linked. -> {linked, saved}."""
    hashes = {} if hashes is None else hashes
    todo = [(p, st) for p, st in _files(folder) if p.name != MARKER and st.st_nlink <= 1 and st.st_size >= min_bytes]
    if not todo:
        return {"linked": 0, "saved": 0}
    sizes = {st.st_size for _p, st in todo}
    by_size: dict[int, list[tuple[Path, os.stat_result]]] = {}
    for ref in refs:
        if not ref.is_dir():
            continue
        for p, st in _files(ref):
            if st.st_size in sizes and p.name != MARKER:
                by_size.setdefault(st.st_size, []).append((p, st))
    linked = saved = 0
    for p, st in todo:
        for r, rst in by_size.get(st.st_size, []):
            if rst.st_dev != st.st_dev or (rst.st_ino and rst.st_ino == st.st_ino):
                continue
            try:
                if _sha256(r, hashes) != _sha256(p, hashes):
                    continue
                tmp = p.with_name(p.name + ".showcase-link")
                if tmp.exists():
                    tmp.unlink()
                os.link(r, tmp)
                os.replace(tmp, p)
            except OSError:
                continue
            linked += 1
            saved += st.st_size
            break
    return {"linked": linked, "saved": saved}


# ------------------------------------------------------------------------------------------------- the service

class Showcase:
    """One instance per control plane. tick() is one pass; the thread calls it every interval_s (or when woken).
    The hooks (writer_of, planner, chars, fingerprint, is_mount, disk_free, slot_rows) are what the tests replace."""

    def __init__(self, store, config, submit=None, workers=None, clock=time.time):
        self.store, self.config, self.submit = store, config, submit
        self.workers = workers or (lambda: [])
        self.clock = clock
        self.lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._hashes: dict = {}
        self._usage = {"at": 0.0, "data": None}
        self.is_mount = os.path.ismount
        self.disk_free = lambda p: shutil.disk_usage(p).free
        self.writer_of = self._writer_of
        self.planner = self._plan
        self.chars = self._chars
        self.fingerprint = self._fingerprint
        self.slot_rows = self._slot_rows

    # ---- plumbing
    @property
    def mods_root(self) -> Path:
        return Path(self.config.cache) / "mods"

    def settings(self) -> dict:
        return settings(self.store, self.config)

    def state(self) -> dict:
        return dict(self.store.get("setting", STATE) or {})

    def _save_state(self, st: dict):
        self.store.put("setting", STATE, st)

    def record(self, gid: str) -> dict:
        return dict(self.store.get(KIND, gid) or {})

    def _put(self, game: dict, rec: dict, **kw) -> dict:
        rec = rec | kw | {"game_id": game["game_id"], "title": game.get("title") or rec.get("title"),
                          "platform": game.get("platform") or rec.get("platform"),
                          "origin": game.get("origin") or rec.get("origin"), "updated": self.clock()}
        self.store.put(KIND, game["game_id"], rec)
        return rec

    def update(self, body: dict, actor: str = "operator") -> dict:
        changes = validate(body)
        with self.lock:
            saved = dict(self.store.get("setting", SETTING) or {})
            saved.update(changes)
            self.store.put("setting", SETTING, saved)
        self.store.audit(actor, "showcase.settings", SETTING, changes)
        self.wake()
        return changes

    # ---- default hooks (the real planner / writer lookup / collection)
    def _writer_of(self, game):
        from . import char_coverage as CC
        return CC.writer_for(game)

    def _chars(self):
        from . import characters as C
        root = C.library_root(self.config)
        return C.list_all(root) if root.is_dir() else []

    def _slot_rows(self, game):
        from . import char_coverage as CC
        return CC.cast_slots(game)

    def _plan(self, game, slots_spec):
        from . import cast_swap as CS, characters as C
        root = C.library_root(self.config)
        return CS.plan(game, self.chars(), SOURCE, "auto", "showcase", slots_spec, None, root if root.is_dir() else None)

    def _fingerprint(self, game):
        from .assimilate import ticket_fingerprint
        gid = game["game_id"]

        def api(path):
            return (self.store.catalog_get(gid) or {}) if path == f"/api/catalog/{gid}" else {}
        return ticket_fingerprint(gid, game.get("title") or "", game.get("platform") or "", api=api,
                                  config=self.config, max_files=1500)

    # ---- the checks
    def storage_problem(self, s: dict) -> str:
        """'' when builds may be written, else why not: the mod cache must be on the external HDD (never the NVMe),
        mounted, with min_free_gb free."""
        from .config import HOST_OS
        cache = Path(self.config.cache)
        if s.get("require_hdd", True):
            hdd = (s.get("hdd_root") or {}).get(HOST_OS)
            if not hdd:
                return (f"no HDD mount configured for {HOST_OS} ([showcase] hdd_root): showcase builds are only "
                        "written to the external HDD")
            h = Path(hdd)
            try:
                inside = cache.resolve().is_relative_to(h.resolve())
            except OSError:
                inside = False
            if not inside:
                return (f"the mod cache ({cache}) is not on the HDD ({hdd}): showcase builds wait until "
                        "cache_dirs points there")
            if not self.is_mount(str(h)):
                return f"the HDD ({hdd}) is not mounted"
        try:
            free = self.disk_free(str(cache if cache.exists() else cache.parent))
        except OSError as e:
            return f"the mod cache ({cache}) can't be read: {e}"
        if free < float(s.get("min_free_gb", 0)) * 2 ** 30:
            return f"only {free / 2 ** 30:.1f} GB free on the HDD (min_free_gb = {s.get('min_free_gb')})"
        return ""

    def disk(self, fresh: bool = False) -> dict:
        """Showcase bytes on the HDD (walks only showcase folders; reused for 60 s)."""
        if not fresh and self._usage["data"] is not None and self.clock() - self._usage["at"] < 60:
            return self._usage["data"]
        folders = showcase_folders(self.mods_root)
        u = usage(folders)
        data = {"used": u["total"], "linked": u["linked"], "builds": len(folders), "per": u["per"]}
        self._usage = {"at": self.clock(), "data": data}
        return data

    def last_used(self, f: dict, sessions: list[dict]) -> float:
        """LRU time of a showcase build: its build time or the start of the newest session that played it."""
        meta = f.get("meta") or {}
        t = meta.get("built") if isinstance(meta.get("built"), (int, float)) else 0
        if not t:
            try:
                t = (f["path"] / MARKER).stat().st_mtime
            except OSError:
                t = 0
        for x in sessions:
            if x.get("game_id") == f["game_id"] and f["name"] in (x.get("mod"), x.get("collection_mod")):
                t = max(t, x.get("started") or 0)
        return float(t)

    def protected(self, f: dict, sessions: list[dict], cards: list[dict], keep: set) -> str:
        """Why a showcase build must not be evicted now, else ''."""
        from .built_mods import card_mod
        if (f["game_id"], f["name"]) in keep:
            return "being built or just built"
        for x in sessions:
            if x.get("state") == "running" and x.get("game_id") == f["game_id"] and \
                    f["name"] in (x.get("mod"), x.get("collection_mod")):
                return "a running game uses it"
        for c in cards:
            if c.get("game_id") == f["game_id"] and card_mod(c) == f["name"] and not c.get("auto_registered"):
                return "the operator saved a mod card for it"
        return ""

    def evict(self, need: int, budget: int, keep: set) -> dict:
        """Delete the least recently used showcase builds until used + need fits the budget. Only folders
        showcase_folders() lists (showcase_sonic_* with the showcase marker); never a protected one; the cards the
        gallery auto-registered for them go too. -> {fits, used, evicted: [...]}."""
        from .built_mods import card_mod
        folders = showcase_folders(self.mods_root)
        u = usage(folders)
        used = u["total"]
        evicted = []
        if used + need <= budget:
            return {"fits": True, "used": used, "evicted": evicted}
        sessions = self.store.all("session")
        cards = self.store.all("mod")
        order = sorted(folders, key=lambda f: self.last_used(f, sessions))
        for f in order:
            if used + need <= budget:
                break
            if self.protected(f, sessions, cards, keep):
                continue
            if not self._remove(f):
                continue
            used -= u["per"].get(f"{f['game_id']}/{f['name']}", 0)
            evicted.append({"game_id": f["game_id"], "mod": f["name"]})
            for c in cards:
                if c.get("auto_registered") and c.get("game_id") == f["game_id"] and card_mod(c) == f["name"]:
                    self.store.delete("mod", c["id"])
            rec = self.record(f["game_id"])
            if rec.get("mod") == f["name"]:
                self.store.put(KIND, f["game_id"], rec | {"stage": "evicted", "evicted_at": self.clock(),
                                                          "message": "evicted (disk budget, least recently used)"})
            self.store.audit("gbox-showcase", "showcase.evict", f"{f['game_id']}/{f['name']}", {"budget": budget})
        self._usage["at"] = 0.0
        return {"fits": used + need <= budget, "used": used, "evicted": evicted}

    def _remove(self, f: dict) -> bool:
        """rmtree one showcase build after checking again that it is ours and inside <cache>/mods/<game>/."""
        p = Path(f["path"])
        try:
            root = self.mods_root.resolve()
            if (p.is_symlink() or not p.resolve().is_relative_to(root / f["game_id"]) or not p.name.startswith(PREFIX)
                    or _is_showcase(p) is None):
                return False
            shutil.rmtree(p)
            return True
        except OSError:
            return False

    # ---- the pass
    def tick(self) -> dict:
        with self.lock:
            s = self.settings()
            st = self.state()
            now = self.clock()
            st["last_tick"] = now
            if not s["enabled"]:
                st.update(phase="disabled", current=None, message="Turned off (Settings > Sonic showcase)")
                self._save_state(st)
                return st
            sessions = self.store.all("session")
            jobs = self.store.jobs(states=("queued", "running"))
            reason = idle_reason(sessions, jobs, self.workers(), s)
            st["idle_reason"] = reason
            if self._reconcile(st, s, reason):
                self._save_state(st)
                return st
            if s["paused"]:
                st.update(phase="paused", current=None, message="Paused: nothing new is planned, built or queued")
                self._save_state(st)
                return st
            if reason:
                st.update(phase="waiting", current=None, message=reason)
                self._save_state(st)
                return st
            st["builds"] = [t for t in st.get("builds") or [] if now - t < 3600]
            storage = self.storage_problem(s)
            titles = select_titles(self.store, s)
            st["queue"] = []
            readiness_left = READINESS_PER_PASS
            started = False
            phase, message = "idle", "Every showcase title is up to date"
            for g in titles:
                rec = self.record(g["game_id"])
                if started:
                    st["queue"].append(self._row(g, rec))
                    continue
                if donor_reader(g):
                    rec = self._put(g, rec, stage="donor_game", message="a donor game (Sonic Adventure): not swapped")
                    st["queue"].append(self._row(g, rec))
                    continue
                w = self.writer_of(g)
                if not w or not w.get("routed"):
                    if readiness_left and self._due(rec, s):
                        readiness_left -= 1
                        rec = self._no_writer(g, w, rec)
                    st["queue"].append(self._row(g, rec))
                    continue
                if not self._due(rec, s):
                    st["queue"].append(self._row(g, rec))
                    continue
                if storage:
                    rec = self._put(g, rec, stage="waiting_storage", message=storage, writer=w["writer"])
                    phase, message = "storage", storage
                elif len(st["builds"]) >= int(s["builds_per_hour"]):
                    rec = self._put(g, rec, stage="rate_limited", writer=w["writer"],
                                    message=f"{s['builds_per_hour']} builds per hour reached")
                    phase, message = "rate_limited", f"{len(st['builds'])} builds in the last hour (cap {s['builds_per_hour']})"
                else:
                    donors = self._ensure_donors(st)
                    if donors.get("waiting"):
                        rec = self._put(g, rec, stage="collecting_donors", writer=w["writer"], message=donors["message"])
                        phase, message, started = "collecting_donors", donors["message"], True
                        st["current"] = {"game_id": g["game_id"], "title": g.get("title"), "stage": "collecting_donors"}
                    elif not donors.get("ready"):
                        rec = self._put(g, rec, stage="no_donors", writer=w["writer"], message=donors["message"])
                        phase, message = "no_donors", donors["message"]
                    else:
                        rec, started = self._plan_and_build(g, w, rec, s, st)
                        if started:
                            phase, message = "building", f"Building {g.get('title')}"
                        elif rec.get("stage") == "over_budget":
                            phase, message = "over_budget", rec.get("message")
                st["queue"].append(self._row(g, rec))
            if not started:
                st["current"] = None
            st.update(phase=phase, message=message)
            self._save_state(st)
            return st

    def _row(self, g: dict, rec: dict) -> dict:
        return {"game_id": g["game_id"], "title": g.get("title"), "origin": g.get("origin"),
                "stage": rec.get("stage") or "pending", "mod": rec.get("mod")}

    def _due(self, rec: dict, s: dict) -> bool:
        if not rec or rec.get("stage") in WAITING or rec.get("stage") is None:
            return True
        return self.clock() - float(rec.get("checked") or 0) >= float(s["recheck_hours"]) * 3600

    # ---- a title without a writer: readiness
    def _no_writer(self, g: dict, w: dict | None, rec: dict) -> dict:
        from . import char_coverage as CC, hermes_work_queue as Q
        missing = []
        if not w:
            missing.append("writer: no character writer for this game yet (characters op=coverage)")
        else:
            missing.append(f"writer: {w['writer']} exists but characters op=use doesn't route to it yet")
        try:
            ex, _roster = CC.extractor_for(g)
        except Exception:                                  # noqa: BLE001
            ex = None
        if not ex:
            missing.append("reader: no dedicated model reader (characters op=collect can't extract its cast yet)")
        backlog = self.store.get("capability_backlog", g["game_id"]) or []
        for task in backlog[:3]:
            if isinstance(task, dict) and (task.get("title") or task.get("task")):
                missing.append(f"backlog: {task.get('title') or task.get('task')}")
        try:
            have = Q.item_state(g["game_id"])
            fp = None if have and have.get("fingerprint") else self.fingerprint(g)
            row = Q.ensure_item(g | {"in_catalog": True}, fingerprint=fp)
        except OSError as e:                               # the Hermes tick holds the queue lock: next pass
            return self._put(g, rec, stage="readiness_pending", missing=missing, checked=self.clock(),
                             message=f"readiness queue busy ({type(e).__name__}); retried next pass")
        except ValueError as e:
            return self._put(g, rec, stage="no_writer", missing=missing, checked=self.clock(), message=str(e))
        stage = row.get("next_stage")
        missing.append(f"readiness: next stage {stage}" if stage else "readiness: every stage verified")
        return self._put(g, rec, stage="readiness_queued", missing=missing, checked=self.clock(),
                         readiness={k: row.get(k) for k in ("next_stage", "stages", "request_id", "number",
                                                             "dispatch_state", "fingerprint", "start_from", "new")},
                         message=("no writer yet: queued for readiness (inventory -> analysis with Ghidra / REA -> "
                                  f"reader -> writer -> runtime), next stage {stage}") if stage else
                                 "readiness verified; waiting for the writer to be routed")

    # ---- donors
    def _ensure_donors(self, st: dict) -> dict:
        """The SA1 / SA2 cast in the collection: a collect job on the Spark for a donor game whose entries are missing
        (one at a time); proceeds with the donors there are once no collection is pending."""
        from . import cast_swap as CS
        chars = self.chars()
        have: dict[str, int] = {}
        for m in CS._candidates(chars):
            ex = CS.extractor_of(m)
            if ex in DONOR_READERS:
                have[ex] = have.get(ex, 0) + 1
        missing = [r for r in DONOR_READERS if not have.get(r)]
        notes = []
        for reader in missing:
            games = [g for g in self.store.search(q="sonic adventure", limit=50)[1] if donor_reader(g) == reader]
            if not games:
                notes.append(f"{reader}: no Sonic Adventure {reader[-1]} disc in the catalog")
                continue
            g = games[0]
            col = self.store.get("character_collection", g["game_id"]) or {}
            job = self.store.get("job", col["job_id"]) if col.get("job_id") else None
            state = (job or {}).get("state") or col.get("state")
            if state in ("queued", "running"):
                return {"waiting": True, "ready": False, "have": have,
                        "message": f"collecting the {g.get('title')} cast (job {col.get('job_id')})"}
            if state in ("succeeded", "failed", "unsupported"):
                notes.append(f"{reader}: {g.get('title')} collection {state} without usable entries")
                continue
            if self.submit is None:
                notes.append(f"{reader}: {g.get('title')} not collected")
                continue
            j = self.submit({"tool": "characters", "input": {"op": "collect", "game_id": g["game_id"]},
                             "require_os": "linux", "agent_use": True, "low_priority": True})
            st.setdefault("collect_jobs", []).append(j.get("id"))
            return {"waiting": True, "ready": False, "have": have,
                    "message": f"collecting the {g.get('title')} cast first (job {j.get('id')})"}
        ready = any(have.values())
        msg = (f"donors: {', '.join(f'{k} {v}' for k, v in sorted(have.items()))}" if ready else
               "no Sonic Adventure characters in the collection") + (f" ({'; '.join(notes)})" if notes else "")
        return {"waiting": False, "ready": ready, "have": have, "message": msg}

    # ---- plan + build
    def slots_for(self, game: dict, s: dict) -> tuple[str, str]:
        """(slots spec, why): the whole cast when it has at most whole_cast_max_slots, else the player + main cast,
        else the first slots (player first) up to that many."""
        from . import cast_swap as CS
        rows = [r for r in CS.slot_rows(game, self.slot_rows(game)) if r.get("status") != "not_working"]
        cap = int(s["whole_cast_max_slots"])
        if len(rows) <= cap:
            return "all", f"whole cast ({len(rows)} slots)"
        main = [r for r in rows if r["kind"] in CS.MAIN_KINDS]
        if main and len(main) <= cap:
            return "main", f"player + main cast ({len(main)} of {len(rows)} slots)"
        pick = sorted(main or rows, key=lambda r: (r["kind"] != "player", not r.get("lead_slot")))[:cap]
        return ",".join(r["slot"] for r in pick), f"player + first {len(pick)} of {len(rows)} slots"

    def _plan_and_build(self, g: dict, w: dict, rec: dict, s: dict, st: dict) -> tuple[dict, bool]:
        from . import cast_swap as CS
        now = self.clock()
        gid, name = g["game_id"], mod_name_for(g)
        try:
            spec, why = self.slots_for(g, s)
            p = self.planner(g, spec)
        except (ValueError, KeyError, OSError) as e:
            return self._put(g, rec, stage="no_plan", writer=w["writer"], checked=now, message=str(e)[:300]), False
        if p.get("status") != "planned":
            return self._put(g, rec, stage="no_plan", writer=w["writer"], checked=now,
                             message=p.get("message") or p.get("status")), False
        h = CS.plan_digest(p["assignments"])
        planned = [{"slot": r["slot"], "slot_name": r.get("slot_name"), "character": r["character"],
                    "donor": r.get("donor"), "preview_url": r.get("preview_url")} for r in p["assignments"]]
        base = dict(writer=w["writer"], checked=now, plan_hash=h, mod=name, slots_spec=spec, slots_why=why,
                    strategy=p.get("strategy"), planned=planned, refused=len(p.get("refused") or []))
        folder = self.mods_root / gid / name
        meta = _is_showcase(folder)
        if meta is not None and meta.get("cast_plan") == h:
            stage = "built" if rec.get("plan_hash") == h and rec.get("stage") == "built" else "unchanged"
            return self._put(g, rec, **base, stage=stage,
                             message=f"plan {h} unchanged since its build: not rebuilt"), False
        if rec.get("plan_hash") == h and rec.get("stage") == "evicted":
            return self._put(g, rec, **base, stage="evicted",
                             message=f"plan {h} unchanged; its build was evicted for the disk budget"), False
        if (rec.get("plan_hash") == h and rec.get("stage") == "failed"
                and now - float(rec.get("failed_at") or 0) < float(s["retry_failed_hours"]) * 3600):
            return self._put(g, rec, **base, stage="failed",
                             message=rec.get("message") or f"plan {h} failed; retried after {s['retry_failed_hours']} h"), False
        size_of = self.disk().get("per", {})
        estimate = int(rec.get("size") or (sorted(size_of.values())[len(size_of) // 2] if size_of else 0)
                       or DEFAULT_ESTIMATE)
        room = self.evict(estimate, int(float(s["budget_gb"]) * 2 ** 30), keep={(gid, name)})
        if not room["fits"]:
            return self._put(g, rec, **base, stage="over_budget",
                             message=(f"the next build (~{estimate / 2 ** 30:.1f} GB) doesn't fit the "
                                      f"{s['budget_gb']} GB showcase budget ({room['used'] / 2 ** 30:.1f} GB used by "
                                      "builds that can't be evicted now)")), False
        if meta is not None:                               # our old build of another plan: replaced, never patched
            self._remove({"game_id": gid, "name": name, "path": folder})
        job = self.submit({"tool": "characters", "require_os": "linux", "agent_use": True, "low_priority": True,
                           "input": {"op": "cast_swap", "target_game": gid, "source": SOURCE, "mapping": "auto",
                                     "seed": "showcase", "slots": spec, "launch": False, "showcase": True,
                                     "mod_name": name,
                                     "assignments": [{"slot": r["slot"], "character": r["character"]} for r in planned]}})
        if job.get("state") not in ("queued", "running"):
            return self._put(g, rec, **base, stage="failed", failed_at=now,
                             message=f"job not admitted: {job.get('error') or job.get('state')}"), False
        st["job_id"] = job["id"]
        st["builds"] = [*(st.get("builds") or []), now]
        st["current"] = {"game_id": gid, "title": g.get("title"), "stage": "building", "job_id": job["id"], "mod": name}
        self.store.audit("gbox-showcase", "showcase.build", gid, {"mod": name, "plan": h, "job": job["id"], "slots": spec,
                                                                   "evicted": room["evicted"]})
        return self._put(g, rec, **base, stage="building", job_id=job["id"], queued_at=now,
                         evicted=room["evicted"], message=f"building {len(planned)} slots ({why}) as {name}"), True

    # ---- the job in flight
    def _reconcile(self, st: dict, s: dict, reason: str) -> bool:
        """True while the showcase's job is queued / running (one at a time). The operator starting a game on the
        Spark or a launch defers it: a queued job is dropped, a running one is asked to stop."""
        jid = st.get("job_id")
        if not jid:
            return False
        j = self.store.get("job", jid)
        if not j:
            st.pop("job_id", None)
            return False
        gid = (j.get("input") or {}).get("target_game") or ""
        game = {"game_id": gid, **({k: (self.store.catalog_get(gid) or {}).get(k) for k in ("title", "platform")}
                                   if gid else {})}
        if j.get("state") in ("queued", "running"):
            if reason or s.get("paused") or not s.get("enabled"):
                why = reason or "paused"
                with self.store.lock:
                    j = self.store.get("job", jid) or j
                    if j.get("state") == "queued":
                        j.update(state="failed", finished=self.clock(), error=f"showcase deferred: {why}")
                    elif j.get("state") == "running":
                        j["cancel"] = True
                    self.store.put("job", jid, j)
                if j.get("state") == "failed":
                    self._put(game, self.record(gid), stage="deferred", message=f"deferred: {why}")
                    st.pop("job_id", None)
                    st["builds"] = (st.get("builds") or [])[:-1]          # a deferred build doesn't count
                    st["current"] = None
                    return False
                st["current"] = (st.get("current") or {}) | {"stage": "deferring"}
                st.update(phase="deferring", message=f"stopping the build: {why}")
                return True
            st.update(phase="building", message=f"building {game.get('title') or gid}")
            st["current"] = (st.get("current") or {}) | {"stage": "building", "job_state": j.get("state")}
            return True
        self.finish(game, j, st, s)
        st.pop("job_id", None)
        st["current"] = None
        return False

    def finish(self, game: dict, j: dict, st: dict, s: dict) -> dict:
        """A finished showcase job -> the title's record (stage, mod, build time, slots replaced, fitting previews),
        dedupe + marker previews for a build, budget re-check (evicting older showcase builds only)."""
        gid = game["game_id"]
        rec = self.record(gid)
        res = ((j.get("output") or {}).get("result") or {}) if isinstance(j.get("output"), dict) else {}
        took = (j.get("finished") or self.clock()) - (j.get("started") or j.get("created") or self.clock())
        report = [r for r in res.get("report") or [] if isinstance(r, dict)]
        slots = [{"slot": r.get("slot"), "slot_name": r.get("slot_name"), "donor": r.get("donor"),
                  "character": r.get("character"), "status": r.get("status"), **({"reason": r["reason"]} if r.get("reason") else {})}
                 for r in report]
        previews = fit_previews(j.get("fitting"), rec.get("planned") or [])
        mod = res.get("mod")
        if str(j.get("error") or "").startswith("showcase deferred") or (j.get("cancel") and j.get("state") != "succeeded"):
            rec = self._put(game, rec, stage="deferred", job_id=j.get("id"), message=f"deferred: {j.get('error') or 'stopped'}")
        elif j.get("state") == "succeeded" and mod and res.get("status") in ("built", "partial", "ready"):
            folder = self.mods_root / gid / mod
            dd = {"linked": 0, "saved": 0}
            if s.get("dedupe", True) and _is_showcase(folder) is not None:
                refs = [Path(self.config.cache) / "modbase" / gid, Path(self.config.cache) / "dc" / gid,
                        *[f["path"] for f in showcase_folders(self.mods_root) if f["path"] != folder]]
                try:
                    dd = dedupe(folder, refs, int(s.get("dedupe_min_mb", 4)) << 20, self._hashes)
                except OSError:
                    pass
            self._mark(folder, previews, slots)
            n = sum(1 for r in slots if r["status"] in ("built", "partial"))
            rec = self._put(game, rec, stage="built", mod=mod, job_id=j.get("id"), built_at=j.get("finished") or self.clock(),
                            build_time=round(took, 1), slots_replaced=slots, previews=previews, dedupe=dd,
                            status=res.get("status"), failed_at=None,
                            message=f"{n}/{len(slots) or n} slots replaced with Sonic characters in {mod}"
                                    + ("" if res.get("status") != "ready" else " (already built)"))
            self._usage["at"] = 0.0
            size = self.disk(fresh=True).get("per", {}).get(f"{gid}/{mod}")
            if size is not None:
                rec = self._put(game, rec, size=size)
            room = self.evict(0, int(float(s["budget_gb"]) * 2 ** 30), keep={(gid, mod)})
            if room["evicted"]:
                rec = self._put(game, rec, evicted_after=room["evicted"])
        else:
            rec = self._put(game, rec, stage="failed", job_id=j.get("id"), failed_at=self.clock(), build_time=round(took, 1),
                            slots_replaced=slots, previews=previews, status=res.get("status") or j.get("state"),
                            message=str(j.get("error") or res.get("message") or res.get("status") or "build failed")[:500])
        results = [*(st.get("last_results") or []),
                   {"game_id": gid, "title": rec.get("title"), "stage": rec.get("stage"), "mod": rec.get("mod"),
                    "message": rec.get("message"), "at": self.clock(), "build_time": rec.get("build_time")}]
        st["last_results"] = results[-LAST_RESULTS:]
        self.store.audit("gbox-showcase", "showcase.result", gid, {"stage": rec.get("stage"), "mod": rec.get("mod"),
                                                                    "job": j.get("id")})
        return rec

    def _mark(self, folder: Path, previews: list[dict], slots: list[dict]):
        """The fitting previews + slot report in the build's own marker (the Mods page shows them)."""
        meta = _is_showcase(folder)
        if meta is None:
            return
        meta["showcase"] = meta["showcase"] | {"previews": previews[:24], "slots": slots}
        path = folder / MARKER
        try:
            if path.stat().st_nlink > 1:
                path.unlink()
            path.write_text(json.dumps(meta, default=str), encoding="utf-8")
        except OSError:
            pass

    # ---- status + thread
    def status(self) -> dict:
        s = self.settings()
        st = self.state()
        storage = self.storage_problem(s) if s["enabled"] else ""
        d = self.disk()
        try:
            free = self.disk_free(str(Path(self.config.cache) if Path(self.config.cache).exists() else Path(self.config.cache).parent))
        except OSError:
            free = None
        records = sorted(self.store.all(KIND), key=lambda r: -(r.get("updated") or 0))
        now = self.clock()
        return {"enabled": s["enabled"], "paused": s["paused"], "settings": {k: s[k] for k in EDITABLE},
                "limits": {k: s[k] for k in ("hdd_root", "require_hdd", "min_free_gb", "recheck_hours",
                                             "retry_failed_hours", "dedupe_min_mb")},
                "phase": st.get("phase") or ("disabled" if not s["enabled"] else "starting"),
                "message": st.get("message") or "", "idle_reason": st.get("idle_reason") or "",
                "current": st.get("current"), "job_id": st.get("job_id"), "last_tick": st.get("last_tick"),
                "queue": st.get("queue") or [], "last_results": list(reversed(st.get("last_results") or [])),
                "disk": {"used": d["used"], "budget": int(float(s["budget_gb"]) * 2 ** 30), "builds": d["builds"],
                         "linked": d["linked"], "free": free, "cache_dir": str(self.config.cache),
                         "storage_problem": storage},
                "rate": {"last_hour": len([t for t in st.get("builds") or [] if now - t < 3600]),
                         "cap": s["builds_per_hour"]},
                "records": records[:100]}

    def game(self, gid: str) -> dict:
        rec = self.record(gid)
        try:
            from . import hermes_work_queue as Q
            readiness = Q.item_state(gid)
        except (OSError, ValueError):
            readiness = None
        mod = rec.get("mod")
        exists = bool(mod) and _is_showcase(self.mods_root / gid / mod) is not None
        return {"game_id": gid, "record": rec or None, "readiness": readiness, "mod_exists": exists}

    def wake(self):
        self._wake.set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sonic-showcase", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _loop(self):
        self._stop.wait(20)                                # let the server finish starting
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:                         # noqa: BLE001 - the service never dies on one bad pass
                try:
                    st = self.state()
                    st.update(phase="error", message=f"{type(e).__name__}: {e}"[:300], last_tick=self.clock())
                    self._save_state(st)
                except Exception:                          # noqa: BLE001
                    pass
            try:
                wait = float(self.settings()["interval_s"])
            except Exception:                              # noqa: BLE001
                wait = 300.0
            if self.state().get("job_id"):
                wait = min(wait, 30.0)                     # a build in flight: notice its end (and the operator) soon
            self._wake.wait(wait)
            self._wake.clear()


def fit_previews(fitting, planned: list[dict]) -> list[dict]:
    """Preview pictures of a build from its job's fitting record (gbox.fit_events: per slot, the writer's fitted
    snapshot / preview), each with the donor's collection preview beside it."""
    rows = []
    donor = {r.get("slot"): r for r in planned or []}
    fit = fitting if isinstance(fitting, dict) else {}
    models = fit.get("models") or {}
    for key in fit.get("order") or list(models):
        m = models.get(key) or {}
        if not (m.get("preview") or m.get("snapshot")):
            continue
        rows.append({"slot": key, "label": m.get("label") or key, "preview": m.get("preview"),
                     "snapshot": m.get("snapshot"), "state": m.get("state"),
                     "donor_preview": (donor.get(key) or {}).get("preview_url")})
    return rows


# ------------------------------------------------------------------------------------------------- routes

class ShowcaseIn(BaseModel):
    """PUT /api/showcase: the editable settings (the safety limits - hdd_root, require_hdd, min_free_gb - are
    gbox.toml only)."""
    enabled: bool | None = None
    paused: bool | None = None
    favorites: int | None = None
    recent: int | None = None
    budget_gb: float | None = None
    builds_per_hour: int | None = None
    whole_cast_max_slots: int | None = None
    interval_s: float | None = None
    dedupe: bool | None = None
    pause_while_playing_anywhere: bool | None = None


def routes(app, store, config, auth, submit, workers):
    """GET/PUT /api/showcase (+ POST, for clients without PUT), POST /api/showcase/run, GET /api/showcase/{game_id}."""
    from fastapi import Depends, HTTPException

    svc = Showcase(store, config, submit, workers)
    app.state.showcase = svc

    @app.get("/api/showcase")
    def showcase_status(actor=Depends(auth)):
        """The Sonic showcase: settings, phase, current title / stage, queue, disk used vs budget, last results."""
        return svc.status()

    def _set(body: ShowcaseIn, actor: str):
        try:
            svc.update(body.model_dump(exclude_none=True), actor)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return svc.status()

    @app.put("/api/showcase")
    def showcase_put(body: ShowcaseIn, actor=Depends(auth)):
        """Turn the showcase on / off, pause it, or change its counts, budget and rate."""
        return _set(body, actor)

    @app.post("/api/showcase")
    def showcase_post(body: ShowcaseIn, actor=Depends(auth)):
        return _set(body, actor)

    @app.post("/api/showcase/run")
    def showcase_run(actor=Depends(auth)):
        """Run a pass now (in the background thread); poll GET /api/showcase."""
        svc.start()
        svc.wake()
        return {"ok": True, "phase": svc.state().get("phase")}

    @app.get("/api/showcase/{game_id}")
    def showcase_game(game_id: str, actor=Depends(auth)):
        """One title's showcase record (the game menu's Special builds) and its readiness row."""
        if not re.fullmatch(r"[0-9a-f]{16}", game_id or ""):
            raise HTTPException(404, "no such game")
        return svc.game(game_id)

    @app.on_event("startup")
    async def _showcase_start():
        svc.start()

    @app.on_event("shutdown")
    async def _showcase_stop():
        svc.stop()

    return svc
