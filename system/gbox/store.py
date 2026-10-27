"""Persistence: SQLite doc store, hash-chained audit ledger, content-addressed artifact store."""
import hashlib
import json
import sqlite3
import threading
import time
import weakref
from contextlib import contextmanager
from pathlib import Path

from .models import ArtifactRef


# Request contexts are arbitrary JSON. Match the old Python truthiness filter,
# including empty containers, without treating literal strings '[]'/'{}' as empty.
_RESOLUTION_ID_TRUTHY = (
    "CASE json_type(body,'$.context.resolution_chat_id') "
    "WHEN 'array' THEN json_array_length(body,'$.context.resolution_chat_id') > 0 "
    "WHEN 'object' THEN json_extract(body,'$.context.resolution_chat_id') != '{}' "
    "ELSE json_extract(body,'$.context.resolution_chat_id') NOT IN ('',0) END"
)


READERS_MAX = 16                  # idle lock-free read connections kept open (one per concurrently reading thread)
WAL_AUTOCHECKPOINT_PAGES = 4000   # 16 MB: the writer folds the WAL back itself only if the checkpoint thread falls behind
WAL_SIZE_LIMIT = 64 * 1024 * 1024 # the WAL file is truncated to this after a reset (the Spark carried 79 MB for days)
WAL_TRUNCATE_BYTES = WAL_SIZE_LIMIT


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def append_audit(db, actor, action, subject, data=None, *, ts=None):
    """Append an audit event in the caller's transaction; never commit here."""
    # Serialize the read of the predecessor across processes, including maintenance CLIs.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")
    last = db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    prev = last[0] if last else "0" * 64
    ts = time.time() if ts is None else ts
    payload = canon({"ts": ts, "actor": actor, "action": action, "subject": subject, "data": data or {}})
    h = sha256(prev.encode() + payload)
    cur = db.execute("INSERT INTO audit(ts,actor,action,subject,data,prev,hash) VALUES(?,?,?,?,?,?,?)",
                     (ts, actor, action, subject, json.dumps(data or {}, default=str), prev, h))
    return cur.lastrowid


class _Writer(sqlite3.Connection):
    """The one shared read/write connection (store.db). Closing it, as every test teardown and maintenance CLI does,
    also closes the lock-free read connections the Store opened beside it, so a temp directory can be removed on
    Windows and no connection outlives the store. `on_close` is a weak method: the connection must not keep its
    Store alive (an unreferenced Store is collected and closed at once, as before)."""
    on_close: "weakref.WeakMethod | None" = None

    def close(self):
        hook = self.on_close() if self.on_close is not None else None
        if hook is not None:
            hook()
        super().close()


class Store:
    """One writer, many readers (2026-10-26). Every write and every compound read-modify-write holds `lock` and runs on
    `db`, as before. A plain read from a thread that does not hold the lock runs on a pooled read-only connection
    (`reading()`): in WAL mode readers never wait for the writer or for each other, so a GET no longer queues behind a
    commit or a long transaction. On the Spark the single lock made /api/workers take 6-10 s and /api/sessions 18-49 s
    with ~20 threads waiting at `with self.lock:` at any moment (py-spy); the lock-holder was a full scan of the 214 MB
    job kind (mercmode.control / autoplay_resume.latest_control, now indexed by docs_job_session)."""

    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        (self.dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "gbox.sqlite3"
        self.db = sqlite3.connect(self.path, check_same_thread=False, factory=_Writer)
        self.db.on_close = weakref.WeakMethod(self._close_side_connections)
        self.lock = threading.RLock()
        self._readers: list[sqlite3.Connection] = []     # idle lock-free read connections, any thread may take one
        self._readers_lock = threading.Lock()
        self._checkpointer: sqlite3.Connection | None = None
        self._checkpoint_lock = threading.Lock()
        self._versions: dict[str, int] = {}              # kind -> in-process writes so far (cache validators)
        self.closed = False
        # synchronous=NORMAL: in WAL mode a commit no longer fsyncs (the checkpoint does); a power cut can lose the last
        # commits, a process crash cannot. The writer's own checkpoint is a fallback: checkpoint() runs them off-lock.
        self.db.executescript(f"""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
            PRAGMA wal_autocheckpoint={WAL_AUTOCHECKPOINT_PAGES};
            PRAGMA journal_size_limit={WAL_SIZE_LIMIT};
            CREATE TABLE IF NOT EXISTS docs(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind, id));
            CREATE INDEX IF NOT EXISTS docs_kind ON docs(kind);
            CREATE INDEX IF NOT EXISTS docs_job_session ON docs(json_extract(body,'$.input.session_id')) WHERE kind='job';
            CREATE TRIGGER IF NOT EXISTS slabel_identity_insert AFTER INSERT ON docs
                WHEN NEW.kind='slabel' AND json_extract(NEW.body,'$.session_id') IS NOT NEW.id
                BEGIN UPDATE docs SET body=json_set(body,'$.session_id',NEW.id)
                    WHERE kind=NEW.kind AND id=NEW.id; END;
            CREATE TRIGGER IF NOT EXISTS slabel_identity_update AFTER UPDATE OF body,id,kind ON docs
                WHEN NEW.kind='slabel' AND json_extract(NEW.body,'$.session_id') IS NOT NEW.id
                BEGIN UPDATE docs SET body=json_set(body,'$.session_id',NEW.id)
                    WHERE kind=NEW.kind AND id=NEW.id; END;
            UPDATE docs SET body=json_set(body,'$.session_id',id)
                WHERE kind='slabel' AND json_extract(body,'$.session_id') IS NOT id;
            CREATE INDEX IF NOT EXISTS docs_queued_jobs ON docs(json_extract(body,'$.state')) WHERE kind='job';
            CREATE INDEX IF NOT EXISTS docs_session_state ON docs(json_extract(body,'$.state')) WHERE kind='session';
            CREATE INDEX IF NOT EXISTS docs_resolution_requests_created
                ON docs(COALESCE(json_extract(body,'$.created'),0) DESC)
                WHERE kind='request' AND {_RESOLUTION_ID_TRUTHY};
            CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY, ts REAL, actor TEXT, action TEXT,
                                             subject TEXT, data TEXT, prev TEXT, hash TEXT);
            CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
            CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
            CREATE TABLE IF NOT EXISTS catalog(game_id TEXT PRIMARY KEY, library TEXT, title TEXT, platform TEXT,
                                               system TEXT, year TEXT, body TEXT);
            CREATE INDEX IF NOT EXISTS catalog_platform ON catalog(platform);
            CREATE INDEX IF NOT EXISTS catalog_title ON catalog(title COLLATE NOCASE);
            CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(game_id UNINDEXED, title, system, collections,
                                                                      manufacturer, category, year, tokenize='unicode61 remove_diacritics 2');
        """)
        self._init_favorites()
        n_cat = self.db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
        n_fts = self.db.execute("SELECT COUNT(*) FROM catalog_fts").fetchone()[0]
        if n_cat != n_fts:                       # interrupted ingest / older index layout -> rebuild
            self.rebuild_fts()
        try:                                     # an inherited WAL (79 MB on the Spark) shrinks at startup, nobody reads yet
            self.checkpoint("TRUNCATE")
        except sqlite3.Error:
            pass

    # --- connections: one locked writer, pooled lock-free readers ---
    def _owns_lock(self) -> bool:
        owned = getattr(self.lock, "_is_owned", None)
        return bool(owned()) if owned is not None else True

    @contextmanager
    def reading(self):
        """The connection a read runs on. A thread holding the Store lock (a read-modify-write, a BEGIN IMMEDIATE
        transaction) keeps the shared connection: it must see its own uncommitted rows and never deadlock. Any other
        thread reads the last committed state on a pooled read-only connection without taking the lock at all."""
        if self._owns_lock():
            yield self.db
            return
        db = self._take_reader()
        try:
            yield db
        finally:
            self._return_reader(db)

    def _take_reader(self) -> sqlite3.Connection:
        with self._readers_lock:
            if self._readers:
                return self._readers.pop()
        db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False, timeout=5.0)
        db.execute("PRAGMA query_only=ON")
        return db

    def _return_reader(self, db: sqlite3.Connection):
        with self._readers_lock:
            if not self.closed and len(self._readers) < READERS_MAX:
                self._readers.append(db)
                return
        db.close()

    def _close_side_connections(self):
        self.closed = True
        with self._readers_lock:
            readers, self._readers = self._readers, []
            ckpt, self._checkpointer = self._checkpointer, None
        for db in readers + ([ckpt] if ckpt is not None else []):
            try:
                db.close()
            except sqlite3.Error:
                pass

    def close(self):
        self.db.close()                          # _Writer.close -> _close_side_connections

    def wal_bytes(self) -> int:
        try:
            return self.path.with_name(self.path.name + "-wal").stat().st_size
        except OSError:
            return 0

    def checkpoint(self, mode: str = "PASSIVE") -> tuple[int, int, int]:
        """Fold the WAL back into the database file on a connection of its own, so the writer never pays for it inside
        a commit and the Store lock is not held meanwhile (writers keep appending to the WAL while this copies).
        PASSIVE never waits; TRUNCATE also resets the file to zero bytes once no reader needs it, waiting at most
        a second for one. Returns SQLite's (busy, wal_frames, checkpointed_frames)."""
        if mode not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
            raise ValueError(mode)
        with self._readers_lock:                 # only the lookup: readers keep coming and going during the copy
            if self.closed:
                raise sqlite3.ProgrammingError("store is closed")
            if self._checkpointer is None:
                self._checkpointer = sqlite3.connect(self.path, check_same_thread=False, timeout=1.0)
                self._checkpointer.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT}")
            db = self._checkpointer
        with self._checkpoint_lock:
            return tuple(db.execute(f"PRAGMA wal_checkpoint({mode})").fetchone())

    def checkpoint_due(self) -> tuple[int, int, int]:
        """The periodic maintenance call (server thread store-checkpoint): a passive pass, then a truncating one when
        the WAL file has grown past WAL_TRUNCATE_BYTES anyway (a reader held a snapshot while writers kept going)."""
        out = self.checkpoint("PASSIVE")
        if self.wal_bytes() > WAL_TRUNCATE_BYTES:
            out = self.checkpoint("TRUNCATE")
        return out

    def version(self, kind: str) -> int:
        """How many documents of a kind this process has written (put/delete) since start: a cache validator for
        callers that re-read a whole kind on every poll (server.workers)."""
        return self._versions.get(kind, 0)

    # --- catalog (indexed, full-text searchable) ---
    STATUS = ("playable", "analysis", "asset_mapping", "autoplay", "modding")
    USER_FIELDS = ("favorite", "last_played")     # set by the operator/sessions, never by a library scan

    # --- favorites: one durable list for every client, PC and session (#1291) ---
    @contextmanager
    def _catalog_write(self):
        """Serialize catalog read/modify/write across threads and SQLite connections."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def _init_favorites(self):
        """Atomically migrate and re-apply both stars and unstars from the durable list."""
        with self._catalog_write():
            fresh = not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='favorites'").fetchone()
            self.db.execute("CREATE TABLE IF NOT EXISTS favorites(game_id TEXT PRIMARY KEY, favorite INTEGER NOT NULL, "
                            "title TEXT, platform TEXT, ts REAL)")
            if fresh:
                state = {}
                for (gid,) in self.db.execute("SELECT game_id FROM catalog WHERE json_extract(body,'$.favorite') = 1"):
                    state[gid] = (True, 0.0)
                for gid, data, ts in self.db.execute("SELECT subject, data, ts FROM audit WHERE action='catalog.favorite' ORDER BY seq"):
                    try:
                        event = json.loads(data or "{}")
                    except ValueError:
                        continue
                    on = event.get("on") if isinstance(event, dict) else None
                    if isinstance(on, bool) and gid:
                        state[gid] = (on, ts or 0.0)
                for gid, (on, ts) in state.items():
                    row = self.db.execute("SELECT title, platform FROM catalog WHERE game_id=?", (gid,)).fetchone() or (None, None)
                    self.db.execute("INSERT OR REPLACE INTO favorites(game_id,favorite,title,platform,ts) VALUES(?,?,?,?,?)",
                                    (gid, int(on), row[0], row[1], ts))
            self.db.execute("UPDATE catalog SET body=json_set(body,'$.favorite',json(CASE "
                            "(SELECT favorite FROM favorites WHERE game_id=catalog.game_id) "
                            "WHEN 1 THEN 'true' ELSE 'false' END)) WHERE game_id IN (SELECT game_id FROM favorites)")

    def _favorite_write(self, e: dict, on: bool):
        """Write a preference inside the caller's catalog transaction."""
        self.db.execute("INSERT OR REPLACE INTO favorites(game_id,favorite,title,platform,ts) VALUES(?,?,?,?,?)",
                        (e["game_id"], int(on), e.get("title"), e.get("platform"), time.time()))

    def _favorite_metadata(self, e: dict):
        self.db.execute("UPDATE favorites SET title=?,platform=? WHERE game_id=?",
                        (e.get("title"), e.get("platform"), e["game_id"]))

    def set_favorite(self, game_id: str, on: bool) -> dict | None:
        """Star/unstar a title. The favorites table outlives catalog refreshes, prunes and re-scans."""
        with self._catalog_write():
            e = self.catalog_get(game_id)
            if e is None:
                known = self.db.execute("SELECT title,platform FROM favorites WHERE game_id=?", (game_id,)).fetchone()
                if on or known is None:       # only an existing catalog title can acquire a new star
                    return None
                e = {"game_id": game_id, "title": known[0], "platform": known[1], "in_catalog": False}
            e["favorite"] = bool(on)
            self.db.execute("UPDATE catalog SET body=? WHERE game_id=?", (json.dumps(e), game_id))
            self._favorite_write(e, bool(on))
        return e

    def favorites(self) -> list[dict]:
        """Every starred title, including ones whose files are currently missing from the catalog."""
        with self.reading() as db:
            rows = db.execute("SELECT f.game_id, f.title, f.platform, f.ts, c.game_id IS NOT NULL FROM favorites f "
                              "LEFT JOIN catalog c ON c.game_id=f.game_id WHERE f.favorite=1 "
                              "ORDER BY f.title COLLATE NOCASE").fetchall()
        return [{"game_id": g, "title": t, "platform": p, "favorited": ts, "in_catalog": bool(c)} for g, t, p, ts, c in rows]

    @staticmethod
    def _fts_row(rid: int, e: dict) -> tuple:
        return (rid, e["game_id"], f'{e["title"]} {e.get("alt_title") or ""}'.strip(), e.get("system") or "", " ".join(e.get("collections", [])),
                e.get("manufacturer") or "", e.get("category") or "", e.get("year") or "")

    def upsert_catalog(self, entries: list[dict], chunk: int = 2000) -> int:
        """Insert/refresh entries, keeping status fields learned since earlier scans.

        FTS rows share the catalog rowid, so refreshes are indexed deletes (100k entries ingest in seconds).
        Work is chunked so API requests interleave with a large ingest.
        """
        for i in range(0, len(entries), chunk):
            with self._catalog_write():
                for e in entries[i:i + chunk]:
                    row = self.db.execute("SELECT rowid, body FROM catalog WHERE game_id=?", (e["game_id"],)).fetchone()
                    if row:
                        old = json.loads(row[1])
                        for k in self.STATUS:
                            if (k == "playable" and e.get("format") == "ps4_pkg"
                                    and e.get("playable") in ("copy_incomplete", "installation_required")):
                                continue  # package readiness is measured on this scan, not learned gameplay status
                            e[k] = old.get(k, e.get(k))
                        for k in self.USER_FIELDS:     # incoming scan defaults cannot replace operator/session values
                            if k in old:
                                e[k] = old[k]
                    fav = self.db.execute("SELECT favorite FROM favorites WHERE game_id=?", (e["game_id"],)).fetchone()
                    if fav is not None:
                        e["favorite"] = bool(fav[0])   # remembered unstars are authoritative too
                    elif isinstance(e.get("favorite"), bool):
                        self._favorite_write(e, e["favorite"])  # bootstrap/imported catalog preferences
                    self._favorite_metadata(e)
                    if row:
                        self.db.execute("UPDATE catalog SET library=?, title=?, platform=?, system=?, year=?, body=? WHERE rowid=?",
                                        (e.get("library"), e["title"], e["platform"], e.get("system"), e.get("year"),
                                         json.dumps(e), row[0]))
                        rid = row[0]
                        self.db.execute("DELETE FROM catalog_fts WHERE rowid=?", (rid,))
                    else:
                        rid = self.db.execute("INSERT INTO catalog(game_id,library,title,platform,system,year,body) VALUES(?,?,?,?,?,?,?)",
                                              (e["game_id"], e.get("library"), e["title"], e["platform"], e.get("system"),
                                               e.get("year"), json.dumps(e))).lastrowid
                    self.db.execute("INSERT INTO catalog_fts(rowid,game_id,title,system,collections,manufacturer,category,year) "
                                    "VALUES(?,?,?,?,?,?,?,?)", self._fts_row(rid, e))
        return len(entries)

    def rebuild_fts(self):
        with self.lock:
            self.db.execute("DELETE FROM catalog_fts")
            for rid, body in self.db.execute("SELECT rowid, body FROM catalog").fetchall():
                self.db.execute("INSERT INTO catalog_fts(rowid,game_id,title,system,collections,manufacturer,category,year) "
                                "VALUES(?,?,?,?,?,?,?,?)", self._fts_row(rid, json.loads(body)))
            self.db.commit()

    def catalog_get(self, game_id: str) -> dict | None:
        with self.reading() as db:
            row = db.execute("SELECT body FROM catalog WHERE game_id=?", (game_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def catalog_update(self, game_id: str, **fields):
        with self._catalog_write():
            e = self.catalog_get(game_id)
            if e is None:
                return
            e.update(fields)
            if isinstance(fields.get("favorite"), bool):
                self._favorite_write(e, fields["favorite"])
            else:
                fav = self.db.execute("SELECT favorite FROM favorites WHERE game_id=?", (game_id,)).fetchone()
                if fav is not None:
                    e["favorite"] = bool(fav[0])
            self._favorite_metadata(e)
            self.db.execute("UPDATE catalog SET body=? WHERE game_id=?", (json.dumps(e), game_id))

    SORTS = {"name": "title COLLATE NOCASE", "name_desc": "title COLLATE NOCASE DESC",
             "year": "CAST(NULLIF(year,'') AS INT) DESC, title COLLATE NOCASE", "year_asc": "CAST(NULLIF(year,'') AS INT) IS NULL, CAST(NULLIF(year,'') AS INT), title COLLATE NOCASE",
             "console": "platform, system, title COLLATE NOCASE",
             "recent": "json_extract(body,'$.last_played') IS NULL, json_extract(body,'$.last_played') DESC, title COLLATE NOCASE",
             "size": "CAST(json_extract(body,'$.size') AS INT) DESC, title COLLATE NOCASE",
             "size_asc": "CAST(json_extract(body,'$.size') AS INT) = 0, CAST(json_extract(body,'$.size') AS INT), title COLLATE NOCASE"}

    def search(self, q: str = "", platform: str = "", system: str = "", library: str = "",
               limit: int = 100, offset: int = 0, sort: str = "name", favorites: bool = False, recent: bool = False,
               local: str = "", letter: str = "", start_letter: str | None = None,
               exclude_platforms: str = "") -> tuple[int, list[dict]]:
        where, args = [], []
        hidden = [p for p in exclude_platforms.split(",") if p]
        if hidden:
            where.append(f"COALESCE(platform, '') NOT IN ({','.join('?' * len(hidden))})")
            args += hidden
        if platform and "," in platform:                       # carousel multi-select
            ps = [p for p in platform.split(",") if p]
            where.append(f"platform IN ({','.join('?' * len(ps))})")
            args += ps
            platform = ""
        if favorites:
            where.append("json_extract(body,'$.favorite') = 1")
        if recent:
            where.append("json_extract(body,'$.last_played') IS NOT NULL")
        if local:                                              # staged on that node's fast local cache
            where.append("EXISTS (SELECT 1 FROM json_each(body,'$.cached_on') WHERE value = ?)")
            args.append(local)
        if letter == "#":
            where.append("NOT (upper(substr(title,1,1)) BETWEEN 'A' AND 'Z')")
        elif letter:
            where.append("upper(substr(title,1,1)) = ?")
            args.append(letter.upper()[:1])
        if q.strip():
            # every word must prefix-match somewhere: "phantasy ver 2" -> "phantasy"* "ver"* "2"*
            terms = " ".join('"' + t.replace('"', '') + '"*' for t in q.split() if t.replace('"', ''))
            where.append("rowid IN (SELECT rowid FROM catalog_fts WHERE catalog_fts MATCH ?)")
            args.append(terms)
        for col, val in (("platform", platform), ("system", system), ("library", library)):
            if val:
                where.append(f"{col}=?")
                args.append(val)
        if start_letter is not None:                         # A-Z scrubber: how many titles sort before this letter
            w = " AND ".join(where + ["title < ? COLLATE NOCASE"])
            with self.reading() as db:
                n = db.execute(f"SELECT COUNT(*) FROM catalog WHERE {w}", args + [start_letter]).fetchone()[0]
            return n, []
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with self.reading() as db:
            total = db.execute(f"SELECT COUNT(*) FROM catalog {w}", args).fetchone()[0]
            rows = db.execute(f"SELECT body FROM catalog {w} ORDER BY {self.SORTS.get(sort, self.SORTS['name'])} LIMIT ? OFFSET ?",
                              args + [limit, offset]).fetchall()
        return total, [json.loads(r[0]) for r in rows]

    def prune_catalog(self, library: str, keep: set[str]) -> int:
        """Drop entries of `library` that a fresh scan no longer found (moved/deleted files, old duplicate ids)."""
        with self.lock:
            stale = [(gid, rid) for rid, gid in self.db.execute("SELECT rowid, game_id FROM catalog WHERE library=?", (library,))
                     if gid not in keep]
            for gid, rid in stale:
                self.db.execute("DELETE FROM catalog WHERE rowid=?", (rid,))
                self.db.execute("DELETE FROM catalog_fts WHERE rowid=?", (rid,))
            self.db.commit()
        return len(stale)

    def platform_summary(self) -> list[dict]:
        """Carousel data: per platform, game count and its biggest source systems (for the wheel logo)."""
        with self.reading() as db:
            rows = db.execute("SELECT platform, system, COUNT(*) FROM catalog GROUP BY platform, system").fetchall()
        out: dict[str, dict] = {}
        for plat, system, n in rows:
            p = out.setdefault(plat, {"platform": plat, "count": 0, "systems": []})
            p["count"] += n
            p["systems"].append({"name": system, "count": n})
        for p in out.values():
            p["systems"].sort(key=lambda s: -s["count"])
        return sorted(out.values(), key=lambda p: -p["count"])

    def facets(self) -> dict:
        with self.reading() as db:
            plat = db.execute("SELECT platform, COUNT(*) FROM catalog GROUP BY platform ORDER BY 2 DESC").fetchall()
            sysm = db.execute("SELECT system, COUNT(*) FROM catalog GROUP BY system ORDER BY system").fetchall()
            libs = db.execute("SELECT library, COUNT(*) FROM catalog GROUP BY library").fetchall()
        return {"platforms": dict(plat), "systems": dict(sysm), "libraries": dict(libs)}

    # --- docs ---
    def put(self, kind: str, id: str, body: dict):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?)", (kind, id, json.dumps(body, default=str)))
            self.db.commit()
            self._versions[kind] = self._versions.get(kind, 0) + 1

    def delete(self, kind: str, id: str):
        with self.lock:
            self.db.execute("DELETE FROM docs WHERE kind=? AND id=?", (kind, id))
            self.db.commit()
            self._versions[kind] = self._versions.get(kind, 0) + 1

    def get(self, kind: str, id: str) -> dict | None:
        with self.reading() as db:
            row = db.execute("SELECT body FROM docs WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def digest(self, kind: str) -> str:
        """A validator for all documents of a kind: it changes whenever one is added, changed or removed (any writer of
        this database, including scripts). Hashing the stored text is ~50x cheaper than decoding it (#712)."""
        h = hashlib.sha1()
        with self.reading() as db:
            for (body,) in db.execute("SELECT body FROM docs WHERE kind=? ORDER BY rowid", (kind,)):
                h.update(body.encode("utf-8", "surrogatepass"))
                h.update(b"\0")
        return h.hexdigest()

    def rows(self, kind: str) -> list[tuple[str, str]]:
        """(id, stored JSON text) of every document of a kind, undecoded, in rowid order: a caller that keeps its own
        decoded copies re-decodes only the texts that changed (server.workers: 21 of 23 registrations never do)."""
        with self.reading() as db:
            return db.execute("SELECT id, body FROM docs WHERE kind=? ORDER BY rowid", (kind,)).fetchall()

    def fields(self, kind: str, names: tuple[str, ...]) -> list[dict]:
        """Just these top-level fields of every document of a kind (nested values come back as JSON text); the
        bodies stay undecoded (built_mods, last_played, library_home read whole kinds this way on every poll)."""
        cols = ", ".join(f"json_extract(body,'$.{f}')" for f in names)
        with self.reading() as db:
            rows = db.execute(f"SELECT {cols} FROM docs WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [dict(zip(names, r)) for r in rows]

    def all(self, kind: str, *, reverse: bool = False, without: tuple[str, ...] = ()) -> list[dict]:
        """Every document of a kind. `without`: top-level fields SQLite drops (json_remove, off the GIL) before Python
        decodes the rest - the request message threads are most of that kind's text (GET /api/requests?lite=1)."""
        order = "DESC" if reverse else "ASC"
        if without:
            if not all(f.isidentifier() for f in without):
                raise ValueError("without names top-level fields")
            try:
                with self.reading() as db:
                    rows = db.execute(f"SELECT json_remove(body{', ?' * len(without)}) FROM docs WHERE kind=? "
                                      f"ORDER BY rowid {order}", [f"$.{f}" for f in without] + [kind]).fetchall()
                return [json.loads(r[0]) for r in rows]
            except sqlite3.Error:
                pass              # no JSON functions in this SQLite, or a body it cannot parse: drop them after decoding
        with self.reading() as db:
            rows = db.execute("SELECT body FROM docs WHERE kind=? ORDER BY rowid " + order, (kind,)).fetchall()
        docs = [json.loads(r[0]) for r in rows]
        return [{k: v for k, v in d.items() if k not in without} for d in docs] if without else docs

    def recent(self, kind: str, limit: int) -> list[dict]:
        """The newest `limit` documents of a kind (rowid order), without decoding the whole archive."""
        with self.reading() as db:
            rows = db.execute("SELECT body FROM docs WHERE kind=? ORDER BY rowid DESC LIMIT ?",
                              (kind, int(limit))).fetchall()
        return [json.loads(r[0]) for r in rows]

    def newest(self, kind: str, field: str, limit: int) -> list[dict]:
        """The `limit` documents of a kind with the largest numeric top-level `field` (a missing one counts as 0), ties
        in rowid order: sorted(all(kind), key=lambda d: -d.get(field, 0))[:limit] without decoding the others."""
        if not field.isidentifier():
            raise ValueError("field names a top-level field")
        with self.reading() as db:
            rows = db.execute(f"SELECT body FROM docs WHERE kind=? ORDER BY COALESCE(json_extract(body,'$.{field}'),0) "
                              "DESC, rowid ASC LIMIT ?", (kind, max(0, int(limit)))).fetchall()
        return [json.loads(r[0]) for r in rows]

    def running_sessions(self) -> list[dict]:
        """Live sessions only; admission polls must not decode the session archive."""
        with self.reading() as db:
            rows = db.execute("SELECT body FROM docs INDEXED BY docs_session_state "
                              "WHERE kind='session' AND json_extract(body,'$.state')='running'").fetchall()
        return [json.loads(r[0]) for r in rows]

    def jobs(self, *, states: tuple[str, ...] | None = None, exclude_states: tuple[str, ...] = (),
             exclude_tool: str | None = None, limit: int = 0, reverse: bool = False) -> list[dict]:
        """Filter and bound job documents before decoding their often large results.

        With reverse=True, limit has the historic /api/jobs slice semantics:
        positive returns the newest N, zero returns all, negative omits the
        oldest abs(N) matches. Ascending queries use the same selected rows.
        """
        where, args = ["kind='job'"], []
        if states is not None:
            if not states:
                return []
            where.append("json_extract(body,'$.state') IN (" + ",".join("?" for _ in states) + ")")
            args.extend(states)
        if exclude_states:
            where.append("(json_extract(body,'$.state') IS NULL OR json_extract(body,'$.state') NOT IN ("
                         + ",".join("?" for _ in exclude_states) + "))")
            args.extend(exclude_states)
        if exclude_tool is not None:
            where.append("(json_extract(body,'$.tool') IS NULL OR json_extract(body,'$.tool') != ?)")
            args.append(exclude_tool)
        # ORDER BY rowid can otherwise persuade SQLite to scan the kind index
        # and evaluate state on every historical job for a multi-state poll.
        source = "docs INDEXED BY docs_queued_jobs" if states is not None else "docs"
        query = "SELECT rowid,body FROM " + source + " WHERE " + " AND ".join(where)
        if limit < 0:
            query += " ORDER BY rowid ASC LIMIT -1 OFFSET ?"
            args.append(-limit)
        elif limit > 0:
            query += " ORDER BY rowid DESC LIMIT ?"
            args.append(limit)
        query = "SELECT body FROM (" + query + ") ORDER BY rowid " + ("DESC" if reverse else "ASC")
        with self.reading() as db:
            rows = db.execute(query, args).fetchall()
        return [json.loads(row[0]) for row in rows]

    def resolution_requests(self, limit: int = 20) -> list[dict]:
        """Newest auto-resolution reports, without decoding unrelated inbox threads."""
        with self.reading() as db:
            rows = db.execute("SELECT body FROM docs INDEXED BY docs_resolution_requests_created WHERE kind='request' AND "
                              + _RESOLUTION_ID_TRUTHY
                              + " ORDER BY COALESCE(json_extract(body,'$.created'),0) DESC,rowid ASC LIMIT ?",
                              (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def game_requests(self, game_id: str, statuses=("open", "in_progress", "blocked"), limit: int = 20) -> list[dict]:
        """Unfinished inbox requests targeting a game (context.game_id, or the Hermes favorite child request), newest
        first, as small rows: no body, thread or image is decoded (the session panel polls this every 5 s)."""
        marks = ",".join("?" for _ in statuses)
        with self.reading() as db:
            rows = db.execute(
                "SELECT json_extract(body,'$.id'), json_extract(body,'$.number'), json_extract(body,'$.title'), "
                "json_extract(body,'$.status'), json_extract(body,'$.context') FROM docs WHERE kind='request' AND "
                "(json_extract(body,'$.context.game_id')=? OR json_extract(body,'$.context.hermes_favorite_game')=?) "
                "AND json_extract(body,'$.status') IN (" + marks + ") ORDER BY rowid DESC LIMIT ?",
                (game_id, game_id, *statuses, limit)).fetchall()
        return [{"id": i, "number": n, "title": t, "status": s, "context": json.loads(c) if c else {}}
                for i, n, t, s, c in rows]
    def requests_for_game(self, game_id: str) -> list[dict]:
        """Inbox requests whose context names a game (context.game_id, or a context.build under "<game_id>/"), in rowid
        order. SQLite picks them out, so Python decodes only those bodies; the caller still applies its exact test (a
        build that is an object or array comes back too, as Python would compare its repr). inspection_builds decoded
        the whole kind (4,526 requests, 47.5 MB) for every plan on every 15 s tick: on the Spark (2026-10-27) that
        thread held the GIL in long stretches and its garbage made full collections that froze the event loop and
        every MJPEG stream 0.4-0.9 s at a time."""
        with self.reading() as db:
            rows = db.execute(
                "SELECT body FROM docs WHERE kind='request' AND (json_extract(body,'$.context.game_id') = ? "
                "OR instr(json_extract(body,'$.context.build'), ?) = 1 "
                "OR json_type(body,'$.context.build') IN ('object','array')) ORDER BY rowid",
                (game_id, game_id + "/")).fetchall()
        return [json.loads(row[0]) for row in rows]

    def request_jobs(self, rid: str, limit: int = 200) -> list[dict]:
        """Jobs an inbox request started (parent_request_id or input.request_id), oldest first, for its story."""
        with self.reading() as db:
            rows = db.execute("SELECT body FROM (SELECT rowid,body FROM docs WHERE kind='job' AND "
                              "(json_extract(body,'$.parent_request_id')=? OR json_extract(body,'$.input.request_id')=?) "
                              "ORDER BY rowid DESC LIMIT ?) ORDER BY rowid", (rid, rid, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def audit_for(self, subject: str, limit: int = 200) -> list[dict]:
        """Audit entries about one subject (a request id), oldest first."""
        with self.reading() as db:
            rows = db.execute("SELECT seq,ts,actor,action,data FROM audit WHERE subject=? ORDER BY seq LIMIT ?",
                              (subject, limit)).fetchall()
        return [dict(seq=r[0], ts=r[1], actor=r[2], action=r[3], data=json.loads(r[4])) for r in rows]

    def running_job_counts(self) -> dict[str, int]:
        """Running jobs per claiming worker id, so a worker whose reported slots don't match is visible (#1294)."""
        with self.reading() as db:
            rows = db.execute("SELECT json_extract(body,'$.worker_id'), COUNT(*) FROM docs INDEXED BY docs_queued_jobs "
                              "WHERE kind='job' AND json_extract(body,'$.state')='running' GROUP BY 1").fetchall()
        return {wid: n for wid, n in rows if wid}

    def queued_jobs(self) -> list[dict]:
        """Claim only queued work, in submission order, without decoding every completed job."""
        with self.reading() as db:
            rows = db.execute("SELECT body FROM docs INDEXED BY docs_queued_jobs WHERE kind='job' "
                              "AND json_extract(body,'$.state')='queued' ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    # --- audit ledger ---
    def audit(self, actor: str, action: str, subject: str, data: dict | None = None) -> int:
        with self.lock:
            seq = append_audit(self.db, actor, action, subject, data)
            self.db.commit()
            return seq

    def audit_log_last_seq(self) -> int:
        with self.reading() as db:
            r = db.execute("SELECT MAX(seq) FROM audit").fetchone()
        return r[0] or 0

    def audit_log(self, after: int = 0, limit: int = 200) -> list[dict]:
        with self.reading() as db:
            rows = db.execute("SELECT seq,ts,actor,action,subject,data,hash FROM audit WHERE seq>? ORDER BY seq LIMIT ?",
                              (after, limit)).fetchall()
        return [dict(seq=r[0], ts=r[1], actor=r[2], action=r[3], subject=r[4], data=json.loads(r[5]), hash=r[6]) for r in rows]

    def verify_audit(self) -> tuple[bool, int, str | None]:
        """Recompute the whole chain. Returns (ok, entries checked, first bad seq)."""
        prev, n = "0" * 64, 0
        with self.reading() as db:
            rows = db.execute("SELECT seq,ts,actor,action,subject,data,prev,hash FROM audit ORDER BY seq").fetchall()
        for seq, ts, actor, action, subject, data, p, h in rows:
            payload = canon({"ts": ts, "actor": actor, "action": action, "subject": subject, "data": json.loads(data)})
            if p != prev or sha256(prev.encode() + payload) != h:
                return False, n, str(seq)
            prev, n = h, n + 1
        return True, n, None

    # --- artifacts (content-addressed, immutable) ---
    def artifact_path(self, digest: str) -> Path:
        return self.dir / "artifacts" / digest[:2] / digest

    def put_artifact(self, data: bytes, name: str, media_type: str, provenance: dict) -> ArtifactRef:
        digest = sha256(data)
        p = self.artifact_path(digest)
        if not p.exists():
            p.parent.mkdir(exist_ok=True)
            p.write_bytes(data)
        ref = ArtifactRef(sha256=digest, name=name, size=len(data), media_type=media_type, provenance=provenance)
        self.put("artifact", digest, ref.model_dump())
        return ref

    def read_artifact(self, digest: str) -> bytes | None:
        p = self.artifact_path(digest)
        return p.read_bytes() if p.exists() else None
