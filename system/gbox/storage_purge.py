"""Storage purge (operator 2026-10-26): "purge all of the games off of the D drive that are not being played and save
only the games that are being favorite ... delete every build that is old and unplayed that isn't being played that
was automatically sent."

The worker tool `storage_purge {dry_run=true, unplayed_days=14, include=["games","builds"], paths=[]}` runs on the PC
it cleans. It lists (dry run, the default) or deletes:

  games   per-game folders of this PC's cache, hot and cold tier: <cache>/<game_id>/ (staged library copies), dc|gc/
          <game_id> (disc extracts), romexport_base/<game_id>, and modbase/<game_id> (the base copy builds link to) once
          no kept build of that game remains - unless the game is a favorite, was played on this PC within unplayed_days,
          or a running game uses it.
  builds  <cache>/mods/<game_id>/<build>[~<staged copy>] on a Windows PC (a Linux node's mods/ is the central
          collection: never touched) that came from the Spark collection automatically: not a favorite build, no
          operator download receipt, not played on this PC within unplayed_days, older on this PC than that, not built
          here, and still in the Spark collection (so nothing deleted is the only copy).

Never touched: runtime/ (emulators, saves, memory cards, save states and jumpstates, recordings, play-disc copies),
data_dir (the database, tokens, artifacts), the operator's own files, the character libraries and anything hidden in
the cache, folders holding save-like files, links gBox did not make, and anything a running game holds (its session on
this PC, a staging copy in flight, an open file: Linux /proc, Windows refuses to move a folder with an open file).

Facts come from the control plane at submit (server.submit fills `facts`): the favorites (games and builds), the
operator's sessions on this PC (agents' and demos' sessions do not count as played), download receipts and the Spark
collection. A desktop's local authority adds its own favorites and sessions to the facts the Spark sent; deleting needs
the Spark's facts (sources contains "central"), and always the reviewed list: dry_run=false deletes only the `paths`
of a dry run that are still eligible when it runs.

POST /api/workers/{name}/storage-purge   {dry_run, unplayed_days, include, paths}: the job on that PC (the coordinator,
                                         the desktop's Workers menu "Free space")
GET  /api/workers/{name}/storage-purge   the newest result for that PC (or ?job_id=), titles from the catalog
MCP: job_storage_purge with require_worker=<PC>
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import stat as statmod
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import storage_policy as SP

GAME_ID_RX = re.compile(r"[0-9a-f]{16}|steam-[0-9]{1,12}")      # catalog ids (sha1 prefix) and Steam apps
PART_LABELS = {"": "staged library copy", "dc": "Dreamcast disc extract", "gc": "GameCube disc extract",
               "romexport_base": "ROM export base copy", "modbase": "base copy for builds"}
TRASH = ".gbox-purging"                   # <root>/.gbox-purging/<stamp>: a folder is moved here, then removed
RESERVED_TOPS = {"mods", "modbase", "dc", "gc", "romexport_base", "characters", "environments", "characters_mirror",
                 "characters_build", "fitting", "fitting-jobs", "extract"}
SAVE_DIRS = {".recomp-storage", "savedata", "saves", "memcards", "memory-cards", "memcard", "savestates", "states",
             "jumpstates", "gci"}
SAVE_SUFFIXES = {".srm", ".sav", ".mcr", ".mcd", ".gci", ".ps2", ".state", ".p2s", ".dsv", ".eep", ".sra", ".fla",
                 ".mpk", ".vmp", ".vms"}
SAVE_RX = re.compile(r"\.(?:state\d+|s\d{2})$", re.I)
KEPT_MAX = 500
DAY = 86400.0
RESULT_KIND = "job"                       # results live on the job (GET reads the newest succeeded one)


# ------------------------------------------------------------------------------------------------ the job's models

class PurgeFacts(BaseModel):
    """Filled by the control plane at submit (never trusted from a client to remove protection)."""
    pc: str = ""                                     # the worker name these facts are about
    sources: list[str] = []                          # "central" (the Spark) and/or "local" (a desktop's own authority)
    favorite_games: list[str] = []
    favorite_builds: list[str] = []                  # "game_id/build"
    receipts: list[str] = []                         # "game_id/build" the operator downloaded to this PC
    played: dict[str, float] = {}                    # game_id -> newest operator session on this PC
    played_builds: dict[str, float] = {}             # "game_id/build" -> newest operator session of it on this PC
    collection: list[str] = []                       # "game_id/build" in the Spark's central collection
    titles: dict[str, str] = {}


class StoragePurgeIn(BaseModel):
    dry_run: bool = True                             # list only (the default); false deletes `paths`
    unplayed_days: int = Field(14, ge=1, le=3650)
    include: list[Literal["games", "builds"]] = ["games", "builds"]
    paths: list[str] = []                            # deletion: the reviewed dry run's item paths (required)
    facts: PurgeFacts = PurgeFacts()


class StoragePurgeOut(BaseModel):
    dry_run: bool
    pc: str
    unplayed_days: int
    include: list[str]
    items: list[dict]                                # {kind, game, title, build, folder, part, path, size, last_played, reason, tier}
    kept: list[dict] = []                            # what stays and why (bounded)
    skipped: list[dict] = []                         # requested paths that were not deleted, and why
    totals: dict = {}                                # {items, bytes, freed_bytes, by_kind, kept, kept_bytes, deleted?}
    roots: dict = {}
    system_drive: list[dict] = []                    # gBox roots on a Windows system drive (storage_policy)
    warnings: list[str] = []


# ------------------------------------------------------------------------------------------------ control plane: facts

def worker_ids(store, name: str) -> set[str]:
    """Every worker id this PC has had (each restart registers a new one; worker_alias keeps the old ones)."""
    low, ids = str(name or "").lower(), set()
    for kind in ("worker", "worker_alias"):
        try:
            rows = store.rows(kind)
        except Exception:                                # noqa: BLE001 - another store implementation
            rows = [(d.get("id"), json.dumps(d)) for d in store.all(kind)]
        for key, body in rows:
            try:
                doc = json.loads(body) if isinstance(body, str) else body
            except ValueError:
                continue
            if str(doc.get("name") or "").lower() == low:
                ids.add(str(key if kind == "worker_alias" else (doc.get("id") or key)))
    return ids


def _session_build(s: dict) -> str:
    mod = s.get("collection_mod") or s.get("mod") or s.get("launch_mod") or s.get("staged_mod") or ""
    return str(mod).split("~")[0]


def _automated_session(store, s: dict) -> bool:
    """Agents' test sessions, demos (screensaver / MercMode / roulette), capture sessions and automatic relaunches
    are not the operator playing. A session whose launch job is gone counts as played (keeps more)."""
    from .last_played import is_agent_session
    try:
        if is_agent_session(store, s):
            return True
        job = store.get("job", (s.get("session_id") or "").split("-", 1)[-1]) or {}
    except Exception:                                    # noqa: BLE001
        return False
    return bool(job) and not SP.operator_job(job)


def compute_facts(store, worker: dict, *, central: bool = True, collection: list[str] | None = None) -> dict:
    """Facts about one PC from this control plane's store (see PurgeFacts)."""
    name = worker.get("name") or worker.get("id") or ""
    ids = worker_ids(store, name) | ({worker["id"]} if worker.get("id") else set())
    favs, titles = [], {}
    for f in store.favorites():                          # unreadable favorites fail the submit: never "no favorites"
        favs.append(f["game_id"])
        if f.get("title"):
            titles[f["game_id"]] = f["title"]
    try:
        from .built_mods import favorites as build_favorites
        fav_builds = sorted(build_favorites(store))
    except Exception:                                    # noqa: BLE001
        fav_builds = []
    receipts = set(SP.receipt_keys(store, name))
    receipts |= _download_history(store, ids)
    played, played_builds = {}, {}
    try:
        rows = store.fields("session", ("session_id", "game_id", "title", "mod", "collection_mod", "launch_mod",
                                        "staged_mod", "started", "ended", "state", "detail"))
    except Exception:                                    # noqa: BLE001
        rows = store.all("session")
    low = name.lower()
    for s in rows:
        sid, gid = s.get("session_id") or "", s.get("game_id") or ""
        if not sid or not gid or not s.get("started"):
            continue
        detail = s.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except ValueError:
                detail = {}
        on_pc = sid.split("-")[0] in ids or str((detail or {}).get("worker_name") or "").lower() == low
        if not on_pc or _automated_session(store, s | {"detail": detail if isinstance(detail, dict) else {}}):
            continue
        at = max(float(s.get("started") or 0), float(s.get("ended") or 0) if isinstance(s.get("ended"), (int, float)) else 0)
        played[gid] = max(played.get(gid, 0.0), at)
        if s.get("title") and gid not in titles:
            titles[gid] = s["title"]
        if b := _session_build(s):
            played_builds[f"{gid}/{b}"] = max(played_builds.get(f"{gid}/{b}", 0.0), at)
    return {"pc": name, "sources": ["central" if central else "local"], "favorite_games": sorted(set(favs)),
            "favorite_builds": fav_builds, "receipts": sorted(receipts), "played": played,
            "played_builds": played_builds, "collection": sorted(set(collection or [])) if central else [],
            "titles": titles}


def _download_history(store, ids: set[str]) -> set[str]:
    """Operator downloads of builds to this PC before receipts were recorded: succeeded build_local op=download jobs."""
    out = set()
    try:
        with store.lock:
            rows = store.db.execute(
                "SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='build_local' "
                "AND json_extract(body,'$.input.op')='download' AND json_extract(body,'$.state')='succeeded'").fetchall()
        jobs = [json.loads(r[0]) for r in rows]
    except Exception:                                    # noqa: BLE001 - another store implementation
        jobs = [j for j in store.all("job") if j.get("tool") == "build_local"
                and (j.get("input") or {}).get("op") == "download" and j.get("state") == "succeeded"]
    for j in jobs:
        inp = j.get("input") or {}
        if (j.get("worker_id") in ids or j.get("require_worker") in ids) and SP.operator_job(j) \
                and inp.get("game_id") and inp.get("name"):
            out.add(f"{inp['game_id']}/{inp['name']}")
    return out


def merge_facts(base: dict, extra: dict) -> dict:
    """Keep-facts add up (favorites, receipts, plays: more protection); the collection stays the Spark's."""
    out = dict(base)
    for k in ("favorite_games", "favorite_builds", "receipts", "sources"):
        out[k] = sorted(set(base.get(k) or []) | set(extra.get(k) or []))
    for k in ("played", "played_builds"):
        merged = dict(base.get(k) or {})
        for key, at in (extra.get(k) or {}).items():
            merged[key] = max(float(merged.get(key) or 0), float(at or 0))
        out[k] = merged
    out["titles"] = {**(extra.get("titles") or {}), **(base.get("titles") or {})}
    out["pc"] = base.get("pc") or extra.get("pc") or ""
    out["collection"] = list(base.get("collection") or [])
    return out


def prepare_input(app, store, inp: dict, worker: dict | None, origin) -> dict:
    """server.submit for storage_purge: the facts about the target PC. The Spark replaces whatever a client sent; a
    desktop's local authority adds its own favorites and sessions to the Spark's facts it relayed (a local request
    gets local facts only, which never allow deleting)."""
    from fastapi import HTTPException
    if not worker:
        raise HTTPException(422, "storage_purge cleans one PC: name it with require_worker (worker name or id)")
    central = getattr(app.state, "desktop_worker", None) is None
    relayed = isinstance(origin, dict) and "central_parent_request_id" in origin
    collection = []
    if central:
        index = getattr(app.state, "built_mods", None)
        try:
            collection = [f"{r['game_id']}/{r['name']}" for r in (index.records() if index else [])
                          if r.get("game_id") and r.get("name")]
        except Exception:                                # noqa: BLE001 - a cold index: no build is provably a copy
            collection = []
    mine = compute_facts(store, worker, central=central, collection=collection)
    sent = inp.get("facts") if isinstance(inp.get("facts"), dict) else {}
    facts = merge_facts(sent, mine) if (not central and relayed and "central" in (sent.get("sources") or [])) else mine
    return {**inp, "facts": facts}


# ------------------------------------------------------------------------------------------------ worker: the plan

@dataclass
class Cand:
    kind: str                     # game | build
    game: str
    build: str                    # the build's collection name ("" for games)
    folder: str                   # cache-relative folder ("mods/<gid>/<build~copy>", "dc/<gid>", "<gid>")
    part: str
    path: Path                    # what the listing shows (hot path; the cold path for a cold-only folder)
    real: Path                    # the folder measured and deleted (the cold copy behind a tier link)
    root: Path                    # the cache root it lives under (its trash goes there)
    link: Path | None = None      # the hot tier's link to remove too
    tier: str = "hot"
    own: int = 0
    shared: dict = field(default_factory=dict)      # (dev, ino) -> [size, nlink, links seen here]
    newest: float = 0.0
    save: str = ""
    arrived: float | None = None
    built: float | None = None
    built_here: bool = False
    keep: bool = False
    reason: str = ""
    last_played: float | None = None

    @property
    def size(self) -> int:
        return self.own + sum(v[0] for v in self.shared.values())

    def row(self, titles: dict) -> dict:
        out = {"kind": self.kind, "game": self.game, "title": titles.get(self.game, ""), "build": self.build,
               "folder": self.folder, "part": self.part, "path": str(self.path), "size": self.size,
               "last_played": self.last_played or None, "reason": self.reason, "tier": self.tier,
               "last_used": round(self.newest, 1) or None}
        if self.kind == "build":
            out["arrived"] = round(self.arrived, 1) if self.arrived else None
            out["built"] = self.built
        return out


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _inside(p: Path, root: Path) -> bool:
    try:
        rp, rr = _norm(os.path.realpath(p)), _norm(os.path.realpath(root))
    except (OSError, ValueError):
        return False
    return rp != rr and rp.startswith(rr.rstrip("\\/") + os.sep)


def _junction(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    return statmod.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & 0x400)


def _date(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else ""


def _measure(c: Cand, windows: bool) -> None:
    """Bytes (hard links counted once), the newest mtime and the first save-like path under the folder. Links are
    never followed."""
    stack = [c.real]
    while stack:
        d = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                low = e.name.lower()
                if e.is_dir(follow_symlinks=False):
                    if not c.save and low in SAVE_DIRS:
                        c.save = os.path.relpath(e.path, c.real)
                    stack.append(e.path)
                    continue
                st = os.lstat(e.path) if windows else e.stat(follow_symlinks=False)
            except OSError:
                continue
            if not c.save and (os.path.splitext(low)[1] in SAVE_SUFFIXES or SAVE_RX.search(low)):
                c.save = os.path.relpath(e.path, c.real)
            c.newest = max(c.newest, st.st_mtime)
            if st.st_nlink > 1 and st.st_ino:
                v = c.shared.setdefault((st.st_dev, st.st_ino), [st.st_size, st.st_nlink, 0])
                v[2] += 1
            else:
                c.own += st.st_size


def freed_bytes(cands) -> int:
    """What deleting these frees: unlinked files, and hard-linked files whose every link is among them."""
    total, seen = sum(c.own for c in cands), {}
    for c in cands:
        for k, (size, nlink, n) in c.shared.items():
            s = seen.setdefault(k, [size, nlink, 0])
            s[2] += n
    return total + sum(size for size, nlink, n in seen.values() if n >= nlink)


def _stage_tops(cache: Path) -> set[str]:
    """Top-level folders the staging cache recorded a copied library file in (catalog.STAGE_DB)."""
    from .catalog import STAGE_DB
    try:
        db = json.loads((cache / STAGE_DB).read_text())
    except (OSError, ValueError):
        return set()
    out, base = set(), _norm(cache).rstrip("\\/") + os.sep
    for key in db:
        k = _norm(key)
        if k.startswith(base):
            top = k[len(base):].split(os.sep, 1)[0]
            if top and not top.startswith(".") and top not in RESERVED_TOPS:
                out.add(top)
    return out


def _game_parts(hot: Path, cold: Path | None) -> list[tuple[str, str, str, Path]]:
    """(game_id, container, cache-relative folder, root) of every per-game folder: hot tier entries (real folders and
    links to the cold tier), then cold-only folders."""
    out, seen = [], set()
    for root in [hot] + ([cold] if cold else []):
        tops = _stage_tops(root) if root == hot else set()
        try:
            top = list(os.scandir(root))
        except OSError:
            continue
        for e in top:
            n = e.name
            if n.startswith(".") or n in RESERVED_TOPS:
                continue
            try:
                folder = e.is_symlink() or e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if folder and (GAME_ID_RX.fullmatch(n) or n.lower() in tops or n in tops):
                if root == hot or not os.path.lexists(hot / n):
                    if n not in seen:
                        seen.add(n)
                        out.append((n, "", n, root))
        for c in ("dc", "gc", "romexport_base", "modbase"):
            try:
                kids = list(os.scandir(root / c))
            except OSError:
                continue
            for e in kids:
                rel = f"{c}/{e.name}"
                if e.name.startswith(".") or rel in seen:
                    continue
                if root == hot or not os.path.lexists(hot / c / e.name):
                    seen.add(rel)
                    out.append((e.name, c, rel, root))
    return out


def _resolve(hot: Path, cold: Path | None, rel: str, root: Path) -> tuple[Path, Path, Path | None, str, str]:
    """(shown path, real folder, link to remove, tier, why it is left alone)."""
    if root != hot:
        return root / rel, root / rel, None, "unlinked", ""
    hp = hot / rel
    if os.path.islink(hp):
        from .cache_tiers import _link_target
        t = _link_target(hp)
        if cold is not None and t is not None and _norm(t) == _norm(cold / rel):
            if not os.path.isdir(t):
                return hp, hp, None, "foreign", "a tier link whose cold copy is missing (left alone)"
            return hp, t, hp, "cold", ""
        return hp, hp, None, "foreign", "a link gBox did not make (left alone)"
    if _junction(hp):
        return hp, hp, None, "foreign", "a junction gBox did not make (left alone)"
    return hp, hp, None, "hot", ""


def _builds(hot: Path, host: str) -> list[Cand]:
    """Every build folder (and staged copy, and unfinished download) in <hot>/mods/<game_id>/."""
    from .filemods import STAGED_MARK
    out, mods = [], hot / "mods"
    try:
        games = [g for g in os.scandir(mods) if g.is_dir(follow_symlinks=False) and not g.name.startswith(".")]
    except OSError:
        return out
    for g in games:
        try:
            entries = list(os.scandir(g.path))
        except OSError:
            continue
        for m in entries:
            try:
                if m.name.startswith(".") or not m.is_dir(follow_symlinks=False) or _junction(Path(m.path)):
                    continue
            except OSError:
                continue
            folder, marker, mark = Path(m.path), Path(m.path) / ".gbox-mod.json", Path(m.path) / STAGED_MARK
            base, meta, arrived, part = m.name.split("~")[0], {}, None, "build"
            try:
                if mark.is_file():
                    base, part = (mark.read_text(encoding="utf-8").strip()[:200] or base), "staged copy of the build"
                elif "~" in m.name:
                    part = "staged copy of the build"
                if marker.is_file():
                    st = marker.stat()
                    arrived = st.st_mtime
                    if st.st_size <= 4 << 20:
                        meta = json.loads(marker.read_text(encoding="utf-8"))
                else:
                    arrived, part = folder.stat().st_mtime, "unfinished download of the build"
            except (OSError, ValueError):
                meta = meta if isinstance(meta, dict) else {}
            meta = meta if isinstance(meta, dict) else {}
            on = meta.get("built_on") if isinstance(meta.get("built_on"), dict) else {}
            built = meta.get("built") if isinstance(meta.get("built"), (int, float)) else None
            out.append(Cand(kind="build", game=g.name, build=base, folder=f"mods/{g.name}/{m.name}", part=part,
                            path=folder, real=folder, root=hot, arrived=arrived, built=built,
                            built_here=bool(on.get("host")) and str(on.get("host")).lower() == host.lower()))
    return out


def _held(sessions, copies) -> tuple[set, set, list]:
    """What running games on this PC use: game ids, (game_id, build) pairs, and paths (a played file, a staging copy)."""
    games, builds, paths = set(), set(), []
    for value in list((sessions or {}).values()):
        try:
            _ad, g = value
        except (TypeError, ValueError):
            continue
        g = g if isinstance(g, dict) else {}
        if g.get("game_id"):
            games.add(g["game_id"])
            for k in ("mod", "collection_mod", "launch_mod"):
                if g.get(k):
                    builds.add((g["game_id"], str(g[k]).split("~")[0]))
        if g.get("_rom_path"):
            paths.append(Path(g["_rom_path"]))
    for dst in list(copies or ()):
        paths.append(Path(dst))
    return games, builds, paths


def plan(config, facts: PurgeFacts, *, unplayed_days: int = 14, include=("games", "builds"), sessions=None, copies=None,
         now: float | None = None, host: str | None = None, os_name: str | None = None) -> dict:
    """{items: [Cand to delete], kept: [Cand], warnings} for this PC."""
    now = time.time() if now is None else now
    host = host or platform.node()
    os_name = os_name or platform.system().lower()
    windows = os_name == "windows"
    cutoff = now - unplayed_days * DAY
    hot = Path(config.cache)
    cold = getattr(config, "cold_cache", None)
    cold = Path(cold) if cold else None
    warnings = []
    if not hot.is_dir():
        return {"items": [], "kept": [], "warnings": [f"this PC has no cache folder at {hot}"], "hot": hot, "cold": cold}
    pc = facts.pc or host
    fav_g, fav_b = set(facts.favorite_games), set(facts.favorite_builds)
    receipts, collection = set(facts.receipts), set(facts.collection)
    held_games, held_builds, held_paths = _held(sessions, copies)
    protected = [Path(p) for p in (getattr(config, "data_dir", None), getattr(config, "runtime", None)) if p]

    def holds(c: Cand) -> bool:
        return any(_norm(p) == _norm(c.real) or _norm(p).startswith(_norm(c.real).rstrip("\\/") + os.sep)
                   or _norm(p) == _norm(c.path) or _norm(p).startswith(_norm(c.path).rstrip("\\/") + os.sep)
                   for p in held_paths)

    def unsafe(c: Cand) -> str:
        if not (_inside(c.real, c.root) or (c.link is not None and cold is not None and _inside(c.real, cold))):
            return "outside the cache roots (left alone)"
        for p in protected:
            pn, rn = _norm(p), _norm(c.real).rstrip("\\/")
            if pn == rn or pn.startswith(rn + os.sep):
                return "holds gBox's own data or runtime (left alone)"
        return ""

    def ago(ts: float) -> str:
        days = max(0, int((now - ts) // DAY))
        return "today" if days == 0 else f"{days} day{'s' if days != 1 else ''} ago"

    builds_on = "builds" in include and windows
    if "builds" in include and not windows:
        warnings.append("builds are never purged on a Linux node: its mods/ folder is the central collection")
    if "central" not in facts.sources:
        warnings.append("no facts from the Spark (favorites, play history, collection): this is a preview only; "
                        "deleting needs the Spark's facts (run it from the Spark: POST /api/workers/<pc>/storage-purge)")
    builds = _builds(hot, host) if builds_on else []
    for c in builds:
        key = f"{c.game}/{c.build}"
        c.last_played = facts.played_builds.get(key)
        _measure(c, windows)
        if why := unsafe(c):
            c.keep, c.reason = True, why
        elif key in fav_b:
            c.keep, c.reason = True, "favorite build"
        elif key in receipts or SP.has_local_receipt(config, c.game, c.build):
            c.keep, c.reason = True, "downloaded by the operator"
        elif (c.game, c.build) in held_builds or holds(c):
            c.keep, c.reason = True, "a running game uses it"
        elif c.last_played and c.last_played >= cutoff:
            c.keep, c.reason = True, f"played on {pc} {ago(c.last_played)}"
        elif c.built_here:
            c.keep, c.reason = True, "built on this PC (the only copy)"
        elif key not in collection:
            c.keep, c.reason = True, "not in the Spark collection (this may be the only copy)"
        elif c.arrived and c.arrived >= cutoff:
            c.keep, c.reason = True, f"came to {pc} {ago(c.arrived)} (newer than {unplayed_days} days)"
        elif c.save:
            c.keep, c.reason = True, f"holds save data ({c.save})"
        else:
            c.reason = (f"sent automatically (no operator download); not a favorite; not played on {pc} for "
                        f"{unplayed_days}+ days" + (f" (last played {_date(c.last_played)})" if c.last_played else
                                                    " (never played there)"))
    kept_build_games = {c.game for c in builds if c.keep}
    games = []
    if "games" in include:
        for gid, container, rel, root in _game_parts(hot, cold):
            shown, real, link, tier, foreign = _resolve(hot, cold, rel, root)
            c = Cand(kind="game", game=gid, build="", folder=rel, part=PART_LABELS.get(container, container),
                     path=shown, real=real, root=(cold if tier in ("cold", "unlinked") and cold else hot), link=link,
                     tier=tier, last_played=facts.played.get(gid))
            games.append(c)
            if foreign:
                c.keep, c.reason = True, foreign
                continue
            _measure(c, windows)
            if why := unsafe(c):
                c.keep, c.reason = True, why
            elif gid in fav_g:
                c.keep, c.reason = True, "favorite"
            elif gid in held_games or holds(c):
                c.keep, c.reason = True, "a running game uses it"
            elif c.last_played and c.last_played >= cutoff:
                c.keep, c.reason = True, f"played on {pc} {ago(c.last_played)}"
            elif c.save:
                c.keep, c.reason = True, f"holds save data ({c.save})"
            elif container == "modbase" and not builds_on:
                c.keep, c.reason = True, "the base copy builds link to (builds are not purged here)"
            elif container == "modbase" and gid in kept_build_games:
                c.keep, c.reason = True, "the base copy of builds kept on this PC"
            else:
                c.reason = (f"not a favorite; not played on {pc} for {unplayed_days}+ days"
                            + (f" (last played {_date(c.last_played)})" if c.last_played else " (never played there)"))
    every = builds + games
    return {"items": [c for c in every if not c.keep], "kept": [c for c in every if c.keep], "warnings": warnings,
            "hot": hot, "cold": cold}


# ------------------------------------------------------------------------------------------------ worker: deleting

def _rmtree(p: Path) -> None:
    def retry(func, path, *_):
        try:
            os.chmod(path, statmod.S_IWRITE | statmod.S_IREAD)
            func(path)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=retry)
    else:                                                # pragma: no cover - older interpreters
        shutil.rmtree(p, onerror=retry)


def empty_trash(*roots) -> int:
    """Leftovers of an earlier purge (a folder half removed when a file was busy): gone now. Returns folders removed."""
    n = 0
    for root in roots:
        if root is None:
            continue
        t = Path(root) / TRASH
        try:
            kids = list(os.scandir(t))
        except OSError:
            continue
        for e in kids:
            _rmtree(Path(e.path)) if e.is_dir(follow_symlinks=False) else Path(e.path).unlink(missing_ok=True)
            n += 0 if os.path.lexists(e.path) else 1
    return n


def _forget_staged(cache: Path, folder: Path) -> None:
    """Stage-db rows of files under a deleted folder (catalog.STAGE_DB), in one write."""
    from . import catalog
    pre = _norm(folder).rstrip("\\/") + os.sep
    with catalog._STAGE_LOCK:
        db = catalog._db_load(cache)
        keep = {k: v for k, v in db.items() if not _norm(k).startswith(pre)}
        if len(keep) == len(db):
            return
        p = Path(cache) / catalog.STAGE_DB
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(keep))
        tmp.replace(p)


def open_paths(paths) -> list[str]:
    """Files some process holds open under these folders (Linux /proc, one pass; [] elsewhere)."""
    from . import cache_tiers
    hits = cache_tiers.open_files_under([Path(p) for p in paths], limit=10000) if paths else []
    return [h.split(": ", 1)[-1] for h in hits]


def delete(c: Cand, *, windows: bool, hot: Path, busy: list[str] | None = None) -> str | None:
    """Delete one planned folder: moved into its root's trash first (a folder Windows will not move holds an open
    file), then removed. None, or why it stayed (in whole or in part). `busy`: open paths found beforehand (Linux)."""
    from . import cache_tiers
    if not windows:
        held = open_paths([c.real]) if busy is None else busy
        pre = _norm(os.path.realpath(c.real)).rstrip("\\/")
        hit = next((p for p in held if _norm(p) == pre or _norm(p).startswith(pre + os.sep)), None)
        if hit:
            return f"in use: {hit}"
    trash = c.root / TRASH
    try:
        trash.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"cannot use {trash}: {e}"
    dst = trash / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    tiers, lock = cache_tiers.ACTIVE, None
    unit = cache_tiers.unit_of(c.folder) if c.kind == "game" else None
    if tiers is not None and unit and cache_tiers.safe_key(unit):
        lock = tiers._ulock(unit)
        if not lock.acquire(timeout=30):
            return "the two-tier cache is moving it right now"
    try:
        try:
            os.rename(c.real, dst)
        except OSError as e:
            return f"in use or locked, left whole ({e.strerror or e})"
        if c.link is not None:
            try:
                cache_tiers._remove_link(c.link)
            except OSError as e:
                return f"its copy is gone but the tier link stayed ({e})"
    finally:
        if lock is not None:
            lock.release()
    _rmtree(dst)
    if c.kind == "build":
        from . import filemods
        sidecar = c.path.parent / f".{c.path.name}.sha256.json"
        sidecar.unlink(missing_ok=True)
        filemods._LOCAL_CACHE.clear()
    else:
        try:
            _forget_staged(hot, c.path)
        except OSError:
            pass
    if os.path.lexists(dst):
        return f"partly removed: the rest is in {dst} (deleted on the next purge)"
    return None


# ------------------------------------------------------------------------------------------------ worker: the tool

def run(inp: StoragePurgeIn, ctx, *, sessions=None, copies=None, now: float | None = None, host: str | None = None,
        os_name: str | None = None) -> dict:
    cfg = ctx.config
    os_name = os_name or platform.system().lower()
    windows = os_name == "windows"
    facts = inp.facts
    if not inp.dry_run:
        if not inp.paths:
            raise ValueError("Deleting needs the reviewed list: run the dry run first and pass its item paths in `paths`")
        if "central" not in facts.sources:
            raise ValueError("Deleting needs the Spark's facts (favorites, play history, collection): run it from the "
                             "Spark (POST /api/workers/<pc>/storage-purge there), not from a PC's own authority")
    if copies is None:
        try:
            from . import catalog
            with catalog._STAGE_LOCK:
                copies = [d for c in catalog._COPIES.values() for d in (c.dst, c.part)]
        except Exception:                                # noqa: BLE001
            copies = []
    ctx.progress(5, "Reading this PC's cache")
    p = plan(cfg, facts, unplayed_days=inp.unplayed_days, include=tuple(inp.include), sessions=sessions, copies=copies,
             now=now, host=host, os_name=os_name)
    titles, items, kept = facts.titles, p["items"], p["kept"]
    pc = facts.pc or host or platform.node()
    roots = {"cache": str(p["hot"]), "cold": str(p["cold"]) if p["cold"] else None, "free": {}}
    skipped, deleted = [], []
    if not inp.dry_run:
        empty_trash(p["hot"], p["cold"])
        want = {_norm(x) for x in inp.paths}
        by_path = {_norm(c.path): c for c in items}
        reasons = {_norm(c.path): c.reason for c in kept}
        for x in inp.paths:
            if _norm(x) not in by_path:
                skipped.append({"path": x, "reason": reasons.get(_norm(x)) or "not found in this PC's cache any more"})
        chosen = [c for c in items if _norm(c.path) in want]
        free_before = _free(p["hot"])
        busy = [] if windows else open_paths([c.real for c in chosen])
        for i, c in enumerate(chosen):
            ctx.progress(10 + 85 * i / max(1, len(chosen)), f"Deleting {c.folder} ({c.size / 2**30:,.1f} GB)")
            games_now, builds_now, _paths = _held(sessions, copies)       # a game may have started since the plan
            if (c.game in games_now) if c.kind == "game" else ((c.game, c.build) in builds_now):
                skipped.append({"path": str(c.path), "reason": "a running game uses it"})
                continue
            why = delete(c, windows=windows, hot=p["hot"], busy=busy)
            (skipped.append({"path": str(c.path), "reason": why}) if why else deleted.append(c))
        items = deleted
        roots["freed_measured"] = max(0, _free(p["hot"]) - free_before) if free_before is not None else None
    for r in (p["hot"], p["cold"]):
        if r is not None:
            roots["free"][str(r)] = _free(r)
    by_kind = {}
    for c in items:
        k = by_kind.setdefault(c.kind, {"items": 0, "bytes": 0})
        k["items"] += 1
        k["bytes"] += c.size
    totals = {"items": len(items), "bytes": sum(c.size for c in items), "freed_bytes": freed_bytes(items),
              "by_kind": by_kind, "kept": len(kept), "kept_bytes": sum(c.size for c in kept)}
    if not inp.dry_run:
        totals["deleted"] = len(deleted)
    rows = sorted((c.row(titles) for c in items), key=lambda r: (-r["size"], r["path"]))
    if not inp.dry_run:
        for r in rows:
            r["deleted"] = True
    kept_rows = sorted((c.row(titles) for c in kept), key=lambda r: (-r["size"], r["path"]))[:KEPT_MAX]
    ctx.progress(100, (f"{len(rows)} item(s), {totals['freed_bytes'] / 2**30:,.1f} GB "
                       + ("can be freed (dry run)" if inp.dry_run else "freed")))
    return {"dry_run": inp.dry_run, "pc": pc, "unplayed_days": inp.unplayed_days, "include": list(inp.include),
            "items": rows, "kept": kept_rows, "skipped": skipped, "totals": totals, "roots": roots,
            "system_drive": SP.system_drive_report(cfg) if windows else [], "warnings": p["warnings"]}


def _free(root) -> int | None:
    try:
        return shutil.disk_usage(root).free
    except (OSError, TypeError):
        return None


# ------------------------------------------------------------------------------------------------ control plane: routes

def latest(store, name: str, job_id: str = "") -> dict | None:
    """The newest succeeded storage_purge job for this PC (or that job)."""
    if job_id:
        j = store.get("job", job_id)
        return j if j and j.get("tool") == "storage_purge" else None
    low = str(name or "").lower()
    try:
        with store.lock:
            rows = store.db.execute(
                "SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.tool')='storage_purge' "
                "AND json_extract(body,'$.state')='succeeded' ORDER BY rowid DESC LIMIT 200").fetchall()
        jobs = [json.loads(r[0]) for r in rows]
    except Exception:                                    # noqa: BLE001
        jobs = [j for j in store.all("job", reverse=True) if j.get("tool") == "storage_purge"
                and j.get("state") == "succeeded"][:200]
    return next((j for j in jobs if str((j.get("output") or {}).get("pc") or "").lower() == low), None)


def summary(job: dict | None) -> dict | None:
    """The Workers menu's "Free space: N GB unplayed": the newest dry run's totals."""
    if not job:
        return None
    out = job.get("output") or {}
    t = out.get("totals") or {}
    return {"job_id": job.get("id"), "at": job.get("finished") or job.get("created"), "dry_run": bool(out.get("dry_run")),
            "items": t.get("items", 0), "freed_bytes": t.get("freed_bytes", 0), "unplayed_days": out.get("unplayed_days"),
            "deletable": "central" in ((job.get("input") or {}).get("facts") or {}).get("sources", [])}


class StoragePurgeRequest(BaseModel):
    """POST /api/workers/{name}/storage-purge (module level: the route's annotations resolve here)."""
    dry_run: bool = True
    unplayed_days: int = Field(14, ge=1, le=3650)
    include: list[Literal["games", "builds"]] = ["games", "builds"]
    paths: list[str] = []


def routes(app, store, auth, *, submit, workers, wid, origin_dep, job_request, rejected_state):
    from fastapi import Depends, HTTPException

    def pc(name: str) -> dict:
        w = next((x for x in workers() if x["name"] == name or x["id"] == wid(name)), None)
        if not w:
            raise HTTPException(404, f"no gBox worker '{name}'")
        return w

    @app.post("/api/workers/{name}/storage-purge")
    def worker_storage_purge(name: str, body: StoragePurgeRequest | None = None, actor=Depends(auth),
                             origin=Depends(origin_dep)):
        """Queue `storage_purge` on that PC (worker name or id) and answer its job id. A dry run (the default) lists
        what would go; dry_run=false deletes only `paths` from a reviewed dry run that are still eligible."""
        body = body or StoragePurgeRequest()
        w = pc(name)
        if not w.get("online"):
            raise HTTPException(409, f"{w['name']} is offline: its storage can be checked once its worker is back")
        if not body.dry_run and not body.paths:
            raise HTTPException(422, "Deleting needs the reviewed list: run the dry run, then pass its item paths")
        origin = {**(origin if isinstance(origin, dict) else {}), "via": "storage_purge"}
        job = submit(job_request(tool="storage_purge", require_worker=w["id"], input=body.model_dump()), actor, origin)
        if job.state == rejected_state:
            hint = (" Its worker runs older code without the storage tool: rebuild & relaunch that PC once, then try "
                    "again.") if "storage_purge" in (job.error or "") else ""
            raise HTTPException(409, (job.error or "the storage purge job was rejected") + hint)
        store.audit(actor, "worker.storage_purge", w["id"], {"name": w["name"], "job": job.id, "dry_run": body.dry_run,
                                                             "unplayed_days": body.unplayed_days, "paths": len(body.paths)})
        return {"job_id": job.id, "worker": {"id": w["id"], "name": w["name"], "os": w.get("os")},
                "dry_run": body.dry_run}

    @app.get("/api/workers/{name}/storage-purge")
    def worker_storage_purge_result(name: str, job_id: str = "", actor=Depends(auth)):
        """The newest storage_purge result for that PC (or ?job_id=): its items with catalog titles, the totals."""
        w = next((x for x in workers() if x["name"] == name or x["id"] == wid(name)), None)
        j = latest(store, (w or {}).get("name") or name, job_id)
        if not j:
            raise HTTPException(404, f"no storage check has run on {name} yet")
        out = dict(j.get("output") or {})
        for group in ("items", "kept"):
            rows = []
            for r in out.get(group) or []:
                if not r.get("title") and r.get("game"):
                    try:
                        r = r | {"title": (store.catalog_get(r["game"]) or {}).get("title") or ""}
                    except Exception:                    # noqa: BLE001
                        pass
                rows.append(r)
            out[group] = rows
        return {"job_id": j.get("id"), "state": j.get("state"), "finished": j.get("finished"),
                "deletable": (summary(j) or {}).get("deletable", False), **out}
