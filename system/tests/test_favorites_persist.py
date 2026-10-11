"""#1291: favorites are one durable list that library refreshes, prunes and restarts never erase."""
import re
from pathlib import Path

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
