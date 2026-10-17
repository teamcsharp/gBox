"""Online cover art for a library game (#1067)."""
from fastapi.testclient import TestClient

from gbox import cover_art
from gbox.server import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_candidates_try_the_likely_spellings_first():
    c = cover_art.candidates("Legend of Zelda, The: Ocarina of Time (USA) (Rev 2)")
    assert c[0] == "Legend of Zelda, The: Ocarina of Time (USA) (Rev 2)"
    assert c[1] == "Legend of Zelda, The - Ocarina of Time (USA) (Rev 2)"
    assert "Legend of Zelda, The - Ocarina of Time (USA)" in c
    assert c[-1] == "Legend of Zelda, The: Ocarina of Time"


def test_urls_follow_the_repository_layout():
    u = cover_art.urls("Crazy Taxi (USA)", "dreamcast")
    assert u[0] == "https://thumbnails.libretro.com/Sega%20-%20Dreamcast/Named_Boxarts/Crazy%20Taxi%20%28USA%29.png"
    assert cover_art.urls("x", "unknown") == []
    assert cover_art.libretro_name('A: B/C "D"') == "A_ B_C _D_"


def test_find_returns_the_first_existing_picture():
    calls = []

    def fetch(url):
        calls.append(url)
        if "Ocarina%20of%20Time%20%28USA%29.png" in url and "The%20-%20" in url:
            return PNG
        raise OSError("404")
    url, data, tried = cover_art.find("Legend of Zelda, The: Ocarina of Time (USA)", "n64", fetch=fetch)
    assert data == PNG and "The%20-%20Ocarina" in url and len(tried) == 1
    assert cover_art.find("Nothing", "n64", fetch=lambda u: (_ for _ in ()).throw(OSError("404")))[1] is None


def test_image_type_and_fetch_guards(monkeypatch):
    assert cover_art.image_type(PNG) == "png" and cover_art.image_type(b"\xff\xd8\xff\xe0") == "jpg"
    assert cover_art.image_type(b"<html>") is None
    try:
        cover_art.fetch("file:///etc/passwd")
        raise AssertionError("file URLs must be refused")
    except ValueError:
        pass


def test_cover_route_stores_the_picture_and_serves_it(cfg, monkeypatch):
    app = create_app(cfg)
    gid = "0123456789abcdef"
    monkeypatch.setattr(app.state.store, "catalog_get", lambda g: {"game_id": g, "title": "Crazy Taxi (USA)", "platform": "dreamcast"} if g == gid else None)
    monkeypatch.setattr(cover_art, "find", lambda title, platform, kind="boxart", fetch=None: ("https://x/cover.png", PNG, []))
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    r = client.post(f"/api/catalog/{gid}/cover", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "boxart" and body["bytes"] == len(PNG) and body["source"] == "https://x/cover.png"
    assert (cfg.data_dir / "art" / gid / "boxart.png").read_bytes() == PNG
    served = client.get(f"/api/media/{gid}/boxart")
    assert served.status_code == 200 and served.content == PNG
    best = client.get(f"/api/media/{gid}/best")
    assert best.status_code == 200 and best.content == PNG

    monkeypatch.setattr(cover_art, "find", lambda title, platform, kind="boxart", fetch=None: (None, None, ["https://x/a.png: HTTPError"]))
    miss = client.post("/api/catalog/fedcba9876543210/cover", json={})
    assert miss.status_code == 404
    monkeypatch.setattr(app.state.store, "catalog_get", lambda g: {"game_id": g, "title": "T", "platform": "n64"})
    miss = client.post("/api/catalog/fedcba9876543210/cover", json={})
    assert miss.status_code == 404 and "tried" in miss.json()["detail"]

    monkeypatch.setattr(cover_art, "fetch", lambda url, timeout=20: PNG if url == "https://pick/me.png" else (_ for _ in ()).throw(ValueError("no")))
    chosen = client.post(f"/api/catalog/{gid}/cover", json={"url": "https://pick/me.png", "kind": "snap"})
    assert chosen.status_code == 200 and chosen.json()["source"] == "https://pick/me.png"
    assert (cfg.data_dir / "art" / gid / "snap.png").exists()
    bad = client.post(f"/api/catalog/{gid}/cover", json={"url": "https://pick/other.png"})
    assert bad.status_code == 400
