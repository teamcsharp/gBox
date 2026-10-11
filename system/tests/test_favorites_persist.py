"""#1291: favorites are one durable list that library refreshes, prunes and restarts never erase."""
import re
import sqlite3
import threading
from pathlib import Path

import pytest

from gbox.store import Store

ROOT = Path(__file__).resolve().parents[1]


def entry(gid, title="Game", library="lib", **kw):
    return {"game_id": gid, "title": title, "platform": "dreamcast", "library": library, "system": "Sega Dreamcast", **kw}


def fav_ids(store):
    _, rows = store.search("", "", "", "", 100, 0, favorites=True)
    return {r["game_id"] for r in rows}


def test_rescan_keeps_favorite_and_last_played(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", "Alpha"), entry("b", "Beta")])
    assert s.set_favorite("a", True)["favorite"] is True
    s.catalog_update("a", last_played=123.0)
    s.upsert_catalog([entry("a", "Alpha (rescanned)"), entry("b", "Beta")])   # a scan row has no favorite field
    got = s.catalog_get("a")
    assert got["favorite"] is True and got["last_played"] == 123.0 and got["title"] == "Alpha (rescanned)"
    assert fav_ids(s) == {"a"}


def test_unfavorite_is_remembered(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a")])
    s.set_favorite("a", True)
    s.set_favorite("a", False)
    s.upsert_catalog([entry("a")])
    assert fav_ids(s) == set() and s.favorites() == []
    assert s.set_favorite("missing", True) is None


def test_pruned_favorite_survives_and_returns(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", "Alpha"), entry("b")])
    s.set_favorite("a", True)
    assert s.prune_catalog("lib", {"b"}) == 1                       # file temporarily missing from a scan
    assert s.favorites() == [{"game_id": "a", "title": "Alpha", "platform": "dreamcast",
                              "favorited": s.favorites()[0]["favorited"], "in_catalog": False}]
    s.upsert_catalog([entry("a", "Alpha"), entry("b")])             # found again
    assert s.catalog_get("a")["favorite"] is True and s.favorites()[0]["in_catalog"] is True


def test_restart_and_backfill_from_audit(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", "Alpha"), entry("b", "Beta"), entry("c", "Gamma"), entry("d", "Delta")])
    s.catalog_update("d", favorite=True)                           # starred before the favorites table existed
    for gid, on in (("a", True), ("b", True), ("b", False), ("c", True)):
        s.audit("operator", "catalog.favorite", gid, {"on": on})
    s.upsert_catalog([entry("a", "Alpha"), entry("b", "Beta"), entry("c", "Gamma")])  # old refresh bug: wipe a,c
    s.catalog_update("a", favorite=None); s.catalog_update("c", favorite=None)
    s.db.execute("DROP TABLE favorites"); s.db.commit(); s.db.close()
    s2 = Store(tmp_path)                                            # upgrade: rebuild from audit + catalog
    assert fav_ids(s2) == {"a", "c", "d"}
    assert {f["game_id"] for f in s2.favorites()} == {"a", "c", "d"}
    s2.db.close()
    s3 = Store(tmp_path)                                            # plain restart: nothing changes
    assert fav_ids(s3) == {"a", "c", "d"}


def test_session_header_star_uses_server_favorites():
    html = (ROOT / "clients/web/index.html").read_text(encoding="utf-8")
    head = html[html.index('id="session-head"'):]
    assert head.index('id="session-fav"') < head.index('id="pausebtn"')    # where the operator marked it
    body = html[html.index("async function toggleSessionFav"):]
    assert re.search(r"/api/catalog/\$\{btn\.dataset\.gid\}/favorite\?on=", body[:600])
    after = html[html.index("sessionsView.after = "):][:200]
    assert "syncSessionFav()" in after
    server = (ROOT / "gbox/server.py").read_text(encoding="utf-8")
    assert "store.set_favorite(gid, on)" in server and '"/api/favorites"' in server


@pytest.mark.parametrize("incoming", [False, None, 0])
def test_scan_cannot_override_operator_fields(tmp_path, incoming):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a")])
    s.set_favorite("a", True)
    s.catalog_update("a", last_played=123)
    s.upsert_catalog([entry("a", favorite=incoming, last_played=incoming)])
    assert s.catalog_get("a")["favorite"] is True
    assert s.catalog_get("a")["last_played"] == 123
    assert fav_ids(s) == {f["game_id"] for f in s.favorites()} == {"a"}


def test_durable_unstar_wins_over_rescan_and_restart(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a")])
    s.set_favorite("a", False)
    s.prune_catalog("lib", set())
    s.upsert_catalog([entry("a", favorite=True)])
    assert s.catalog_get("a")["favorite"] is False
    s.db.close()
    reopened = Store(tmp_path)
    assert fav_ids(reopened) == set() and reopened.favorites() == []


def test_bootstrap_and_metadata_update_keep_favorites_consistent(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", favorite=True)])
    assert {f["game_id"] for f in s.favorites()} == fav_ids(s) == {"a"}
    s.upsert_catalog([entry("a", "New name", platform="saturn")])
    assert s.favorites()[0]["title"] == "New name"
    assert s.favorites()[0]["platform"] == "saturn"
    s.catalog_update("a", favorite=False)
    assert s.favorites() == [] and fav_ids(s) == set()
    s.catalog_update("a", favorite=True, title="Operator name")
    assert s.favorites()[0]["title"] == "Operator name"
    assert fav_ids(s) == {"a"}


def test_legacy_audit_unstar_overrides_stale_catalog_true(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", favorite=True)])
    s.audit("operator", "catalog.favorite", "a", {"on": False})
    s.db.execute("DROP TABLE favorites")
    s.db.commit()
    s.db.close()
    s = Store(tmp_path)
    assert s.catalog_get("a")["favorite"] is False
    assert fav_ids(s) == set() and s.favorites() == []


class FailingConnection:
    """One failure at a real SQLite write/commit, with normal rollback support."""
    def __init__(self, db, *, sql=None, commit=False):
        self.db, self.sql, self.fail_commit = db, sql, commit

    def __getattr__(self, name):
        return getattr(self.db, name)

    def execute(self, sql, *args):
        if self.sql and self.sql in sql:
            self.sql = None
            raise sqlite3.OperationalError("injected favorites write failure")
        return self.db.execute(sql, *args)

    def commit(self):
        if self.fail_commit:
            self.fail_commit = False
            raise sqlite3.OperationalError("injected commit failure")
        return self.db.commit()


@pytest.mark.parametrize("commit", [False, True])
def test_failed_toggle_rolls_back_before_unrelated_write(tmp_path, commit):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a")])
    s.db = FailingConnection(s.db, sql=None if commit else "INTO favorites", commit=commit)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        s.set_favorite("a", True)
    assert not s.db.in_transaction
    s.put("unrelated", "x", {"ok": True})
    assert not s.catalog_get("a").get("favorite")
    assert s.favorites() == [] and fav_ids(s) == set()
    s.db.close()
    assert Store(tmp_path).favorites() == []


def test_failed_migration_rolls_back_table_and_can_retry(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a")])
    s.audit("operator", "catalog.favorite", "a", {"on": True})
    s.db.execute("DROP TABLE favorites")
    s.db.commit()
    s.db = FailingConnection(s.db, sql="INTO favorites")
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        s._init_favorites()
    assert not s.db.in_transaction
    assert not s.db.execute("SELECT 1 FROM sqlite_master WHERE name='favorites'").fetchone()
    s._init_favorites()
    assert {f["game_id"] for f in s.favorites()} == fav_ids(s) == {"a"}


def test_failed_refresh_rolls_back_favorites_metadata_catalog_and_fts(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", "Original", favorite=True)])
    s.db = FailingConnection(s.db, sql="INSERT INTO catalog_fts")
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        s.upsert_catalog([entry("a", "New name", platform="saturn", favorite=False)])
    assert not s.db.in_transaction
    s.put("unrelated", "x", {})
    assert s.catalog_get("a")["title"] == "Original"
    assert s.catalog_get("a")["favorite"] is True
    assert s.favorites()[0]["title"] == "Original"
    assert s.favorites()[0]["platform"] == "dreamcast"
    assert s.search("Original")[0] == 1 and s.search("New name")[0] == 0


def test_failed_metadata_favorite_update_rolls_back_durable_map(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", favorite=True)])
    s.db = FailingConnection(s.db, sql="UPDATE catalog SET body")
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        s.catalog_update("a", favorite=False, playable="failed write")
    assert not s.db.in_transaction
    s.put("unrelated", "x", {})
    assert s.catalog_get("a")["favorite"] is True
    assert "playable" not in s.catalog_get("a")
    assert {f["game_id"] for f in s.favorites()} == {"a"}


def test_pruned_known_favorite_can_be_unstarred_but_unknown_cannot_be_created(tmp_path):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a", "Alpha")])
    s.set_favorite("a", True)
    s.prune_catalog("lib", set())
    result = s.set_favorite("a", False)
    assert result and result["game_id"] == "a" and result["favorite"] is False
    assert s.catalog_get("a") is None and s.favorites() == []
    for on in (True, False):
        assert s.set_favorite("unknown", on) is None
    assert not s.db.execute("SELECT 1 FROM favorites WHERE game_id='unknown'").fetchone()
    s.upsert_catalog([entry("a", favorite=True)])
    assert s.catalog_get("a")["favorite"] is False


@pytest.mark.parametrize("same_store", [True, False])
def test_metadata_read_modify_write_serializes_favorite_toggle(tmp_path, same_store):
    s = Store(tmp_path)
    s.upsert_catalog([entry("a")])
    s.set_favorite("a", True)
    other = s if same_store else Store(tmp_path)
    entered, release, toggled = threading.Event(), threading.Event(), threading.Event()
    get = s.catalog_get
    errors = []

    def held_get(gid):
        value = get(gid)
        entered.set()
        if not release.wait(5):
            raise RuntimeError("metadata test barrier timed out")
        return value

    s.catalog_get = held_get

    def metadata():
        try:
            s.catalog_update("a", playable="verified")
        except BaseException as exc:
            errors.append(exc)

    def toggle():
        try:
            other.set_favorite("a", False)
        except BaseException as exc:
            errors.append(exc)
        finally:
            toggled.set()

    first = threading.Thread(target=metadata)
    second = threading.Thread(target=toggle)
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert not toggled.wait(.1), "toggle must wait for metadata's read/write transaction"
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
        s.catalog_get = get
    assert not errors and not first.is_alive() and not second.is_alive()
    assert s.catalog_get("a")["favorite"] is False
    assert s.catalog_get("a")["playable"] == "verified"
    assert s.favorites() == [] and fav_ids(s) == set()


def test_favorite_route_unstars_pruned_and_rejects_unknown_without_audit(cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.character_collection import AutoCollection
    from gbox.server import create_app

    collected = []
    monkeypatch.setattr(AutoCollection, "after_favorite", lambda self, game, submit: collected.append(game))
    monkeypatch.setattr(AutoCollection, "status", lambda self, gid: {"game_id": gid})
    app = create_app(cfg)
    s = app.state.store
    s.upsert_catalog([entry("a")])
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    starred = client.post("/api/catalog/a/favorite?on=true")
    assert starred.status_code == 200 and starred.json()["favorite"] is True
    assert len(collected) == 1
    s.prune_catalog("lib", set())
    unstarred = client.post("/api/catalog/a/favorite?on=false")
    assert unstarred.status_code == 200 and unstarred.json()["favorite"] is False
    assert client.get("/api/favorites").json() == {"count": 0, "items": []}
    before = s.audit_log_last_seq()
    for on in ("true", "false"):
        assert client.post(f"/api/catalog/unknown/favorite?on={on}").status_code == 404
    assert s.audit_log_last_seq() == before
    assert s.catalog_get("unknown") is None
    assert not s.db.execute("SELECT 1 FROM favorites WHERE game_id='unknown'").fetchone()
    assert len(collected) == 1
    assert s.verify_audit()[0]
