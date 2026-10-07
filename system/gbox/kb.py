"""gBox knowledge base: what the agent learned (web pages, wiki articles, verified answers, RAM addresses) as embedded
chunks, so repeated questions are answered from here before searching the web again.

SQLite + float32 vectors from the local embedding model (Ollama nomic-embed-text); cosine search in numpy.
ponytail: brute-force scan over all rows; switch to an ANN index (sqlite-vec / faiss) past ~200k chunks.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx
import numpy as np

MODEL = "nomic-embed-text"


class KB:
    def __init__(self, path: Path, llm_url: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("create table if not exists chunk(id integer primary key, game text, kind text, source text, title text,"
                        " text text, vec blob, ts real, uses integer default 0)")
        self.db.execute("create unique index if not exists chunk_dedupe on chunk(source, text)")
        self.url, self.lock = llm_url.rstrip("/"), threading.Lock()
        self._m = None

    def embed(self, texts: list[str], query=False) -> np.ndarray:
        pre = "search_query: " if query else "search_document: "            # nomic task prefixes
        r = httpx.post(f"{self.url}/embeddings", json={"model": MODEL, "input": [pre + t[:4000] for t in texts]}, timeout=120)
        r.raise_for_status()
        v = np.array([d["embedding"] for d in r.json()["data"]], dtype=np.float32)
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)

    def add(self, text: str, source: str = "", title: str = "", game: str = "", kind: str = "note") -> int:
        """Split into ~900-char chunks (paragraph-aware) and store; returns the number of new chunks."""
        parts, cur = [], ""
        for para in text.replace("\r", "").split("\n"):
            for i in range(0, max(1, len(para)), 900):
                p = para[i:i + 900]
                if len(cur) + len(p) > 900 and cur:
                    parts.append(cur.strip())
                    cur = ""
                cur += p + "\n"
        if cur.strip():
            parts.append(cur.strip())
        parts = [p for p in parts if len(p) > 40][:60]
        if not parts:
            return 0
        vecs = self.embed(parts)
        with self.lock:
            n = self.db.total_changes
            self.db.executemany("insert or ignore into chunk(game, kind, source, title, text, vec, ts) values (?,?,?,?,?,?,?)",
                                [(game.lower(), kind, source, title, p, v.tobytes(), time.time()) for p, v in zip(parts, vecs)])
            self.db.commit()
            self._m = None
            return self.db.total_changes - n

    def search(self, query: str, game: str = "", k: int = 6, min_score: float = 0.55) -> list[dict]:
        with self.lock:
            if self._m is None:
                rows = self.db.execute("select id, game, kind, source, title, text, vec from chunk").fetchall()
                self._m = (rows, np.stack([np.frombuffer(r[6], dtype=np.float32) for r in rows]) if rows else None)
            rows, mat = self._m
        if mat is None:
            return []
        s = mat @ self.embed([query], query=True)[0]
        if game:                                                   # prefer facts about the game being played
            s = s + 0.05 * np.array([1.0 if r[1] and r[1] in game.lower() or game.lower() in (r[1] or "") else 0.0 for r in rows])
        out = []
        for i in np.argsort(-s)[:k]:
            if s[i] < min_score:
                break
            r = rows[i]
            out.append({"id": r[0], "score": round(float(s[i]), 3), "game": r[1], "kind": r[2], "source": r[3], "title": r[4], "text": r[5]})
        if out:
            with self.lock:
                self.db.executemany("update chunk set uses = uses + 1 where id = ?", [(o["id"],) for o in out])
                self.db.commit()
        return out

    def stats(self) -> dict:
        with self.lock:
            n, games = self.db.execute("select count(*), count(distinct game) from chunk").fetchone()
            kinds = dict(self.db.execute("select kind, count(*) from chunk group by kind").fetchall())
        return {"chunks": n, "games": games, "kinds": kinds}


def _selftest():
    import tempfile
    kb = KB(Path(tempfile.mkdtemp()) / "kb.sqlite", "http://127.0.0.1:11434/v1")
    kb.embed = lambda texts, query=False: np.array([[1.0, 0.0] if "wolf" in t.lower() else [0.0, 1.0] for t in texts], dtype=np.float32)
    assert kb.add("The Savage Wolf appears in Forest 1 and has 120 HP in Normal mode." * 2, "wiki", "Savage Wolf", "pso") == 1
    assert kb.add("The Savage Wolf appears in Forest 1 and has 120 HP in Normal mode." * 2, "wiki", "Savage Wolf", "pso") == 0   # dedupe
    hits = kb.search("savage wolf hp", "pso")
    assert hits and hits[0]["title"] == "Savage Wolf", hits
    assert kb.search("unrelated thing") == []
    print("kb ok", json.dumps(kb.stats()))


if __name__ == "__main__":
    _selftest()
