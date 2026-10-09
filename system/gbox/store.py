"""Persistence: SQLite doc store, hash-chained audit ledger, content-addressed artifact store."""
import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path

from .models import ArtifactRef


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


class Store:
    # ponytail: small kinds (jobs, receipts, edges...) are JSON docs filtered in Python; the catalog has its own indexed table.
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        (self.dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.dir / "gbox.sqlite3", check_same_thread=False)
        self.lock = threading.RLock()
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS docs(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind, id));
            CREATE INDEX IF NOT EXISTS docs_queued_jobs ON docs(json_extract(body,'$.state')) WHERE kind='job';
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
        n_cat = self.db.execute("SELECT COUNT(*) FROM catalog").fetchone()[0]
        n_fts = self.db.execute("SELECT COUNT(*) FROM catalog_fts").fetchone()[0]
        if n_cat != n_fts:                       # interrupted ingest / older index layout -> rebuild
            self.rebuild_fts()

    # --- catalog (indexed, full-text searchable) ---
    STATUS = ("playable", "analysis", "asset_mapping", "autoplay", "modding")

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
            with self.lock:
                for e in entries[i:i + chunk]:
                    row = self.db.execute("SELECT rowid, body FROM catalog WHERE game_id=?", (e["game_id"],)).fetchone()
                    if row:
                        old = json.loads(row[1])
                        for k in self.STATUS:
                            e[k] = old.get(k, e.get(k))
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
                self.db.commit()
        return len(entries)

    def rebuild_fts(self):
        with self.lock:
            self.db.execute("DELETE FROM catalog_fts")
            for rid, body in self.db.execute("SELECT rowid, body FROM catalog").fetchall():
                self.db.execute("INSERT INTO catalog_fts(rowid,game_id,title,system,collections,manufacturer,category,year) "
                                "VALUES(?,?,?,?,?,?,?,?)", self._fts_row(rid, json.loads(body)))
            self.db.commit()

    def catalog_get(self, game_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM catalog WHERE game_id=?", (game_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def catalog_update(self, game_id: str, **fields):
        e = self.catalog_get(game_id)
        if e:
            e.update(fields)
            with self.lock:
                self.db.execute("UPDATE catalog SET body=? WHERE game_id=?", (json.dumps(e), game_id))
                self.db.commit()

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
            with self.lock:
                n = self.db.execute(f"SELECT COUNT(*) FROM catalog WHERE {w}", args + [start_letter]).fetchone()[0]
            return n, []
        w = ("WHERE " + " AND ".join(where)) if where else ""
        with self.lock:
            total = self.db.execute(f"SELECT COUNT(*) FROM catalog {w}", args).fetchone()[0]
            rows = self.db.execute(f"SELECT body FROM catalog {w} ORDER BY {self.SORTS.get(sort, self.SORTS['name'])} LIMIT ? OFFSET ?",
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
        with self.lock:
            rows = self.db.execute("SELECT platform, system, COUNT(*) FROM catalog GROUP BY platform, system").fetchall()
        out: dict[str, dict] = {}
        for plat, system, n in rows:
            p = out.setdefault(plat, {"platform": plat, "count": 0, "systems": []})
            p["count"] += n
            p["systems"].append({"name": system, "count": n})
        for p in out.values():
            p["systems"].sort(key=lambda s: -s["count"])
        return sorted(out.values(), key=lambda p: -p["count"])

    def facets(self) -> dict:
        with self.lock:
            plat = self.db.execute("SELECT platform, COUNT(*) FROM catalog GROUP BY platform ORDER BY 2 DESC").fetchall()
            sysm = self.db.execute("SELECT system, COUNT(*) FROM catalog GROUP BY system ORDER BY system").fetchall()
            libs = self.db.execute("SELECT library, COUNT(*) FROM catalog GROUP BY library").fetchall()
        return {"platforms": dict(plat), "systems": dict(sysm), "libraries": dict(libs)}

    # --- docs ---
    def put(self, kind: str, id: str, body: dict):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?)", (kind, id, json.dumps(body, default=str)))
            self.db.commit()

    def delete(self, kind: str, id: str):
        with self.lock:
            self.db.execute("DELETE FROM docs WHERE kind=? AND id=?", (kind, id))
            self.db.commit()

    def get(self, kind: str, id: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT body FROM docs WHERE kind=? AND id=?", (kind, id)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT body FROM docs WHERE kind=? ORDER BY rowid", (kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def queued_jobs(self) -> list[dict]:
        """Claim only queued work, in submission order, without decoding every completed job."""
        with self.lock:
            rows = self.db.execute("SELECT body FROM docs WHERE kind='job' AND json_extract(body,'$.state')='queued' ORDER BY rowid").fetchall()
        return [json.loads(row[0]) for row in rows]

    # --- audit ledger ---
    def audit(self, actor: str, action: str, subject: str, data: dict | None = None) -> int:
        with self.lock:
            last = self.db.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = last[0] if last else "0" * 64
            ts = time.time()
            payload = canon({"ts": ts, "actor": actor, "action": action, "subject": subject, "data": data or {}})
            h = sha256(prev.encode() + payload)
            cur = self.db.execute("INSERT INTO audit(ts,actor,action,subject,data,prev,hash) VALUES(?,?,?,?,?,?,?)",
                                  (ts, actor, action, subject, json.dumps(data or {}, default=str), prev, h))
            self.db.commit()
            return cur.lastrowid

    def audit_log_last_seq(self) -> int:
        with self.lock:
            r = self.db.execute("SELECT MAX(seq) FROM audit").fetchone()
        return r[0] or 0

    def audit_log(self, after: int = 0, limit: int = 200) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT seq,ts,actor,action,subject,data,hash FROM audit WHERE seq>? ORDER BY seq LIMIT ?",
                                   (after, limit)).fetchall()
        return [dict(seq=r[0], ts=r[1], actor=r[2], action=r[3], subject=r[4], data=json.loads(r[5]), hash=r[6]) for r in rows]

    def verify_audit(self) -> tuple[bool, int, str | None]:
        """Recompute the whole chain. Returns (ok, entries checked, first bad seq)."""
        prev, n = "0" * 64, 0
        with self.lock:
            rows = self.db.execute("SELECT seq,ts,actor,action,subject,data,prev,hash FROM audit ORDER BY seq").fetchall()
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
