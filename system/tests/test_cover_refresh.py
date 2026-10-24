"""A chosen cover reaches every PC at once: artwork is revalidated (ETag / 304) instead of cached as immutable for a week,
and a game whose only art is an attached cover still gets an image on its library card."""
import time

from fastapi.testclient import TestClient

from gbox import server
from gbox.config import Config


def test_artwork_revalidates_and_a_new_cover_is_served_at_once(tmp_path):
    cfg = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    app = server.create_app(cfg)
    store = app.state.store
    store.upsert_catalog([{"game_id": "g1", "title": "Resident Evil 5", "platform": "ps3", "system": "PlayStation 3",
                           "library": None, "rel_path": None}])
    art = cfg.data_dir / "art" / "g1"
    art.mkdir(parents=True)
    (art / "boxart.png").write_bytes(b"\x89PNG first")
    with TestClient(app, headers={"Authorization": "Bearer " + cfg.token()}) as c:
        items = c.get("/api/catalog?q=resident").json()["items"]
        assert items and items[0]["media"] == {"boxart": "attached"}
        r = c.get("/api/media/g1/boxart")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.content == b"\x89PNG first"
        tag = r.headers["etag"]
        assert c.get("/api/media/g1/boxart", headers={"if-none-match": tag}).status_code == 304
        time.sleep(0.01)
        (art / "boxart.png").write_bytes(b"\x89PNG second cover")
        r2 = c.get("/api/media/g1/boxart", headers={"if-none-match": tag})
        assert r2.status_code == 200 and r2.content == b"\x89PNG second cover" and r2.headers["etag"] != tag
