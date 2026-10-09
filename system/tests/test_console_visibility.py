from fastapi.testclient import TestClient

from gbox.server import create_app
from gbox.store import Store


def test_hidden_consoles_filter_search_pages_and_letter_offsets(cfg):
    store = Store(cfg.data_dir)
    store.upsert_catalog([
        {"game_id": str(i), "title": title, "platform": platform, "system": platform,
         "favorite": True, "cached_on": ["pc"], "last_played": i + 1}
        for i, (title, platform) in enumerate([
            ("Alpha", "nes"), ("Beta", "snes"), ("Delta", "nes"), ("Zelda", "snes")])
    ])
    client = TestClient(create_app(cfg), headers={"Authorization": f"Bearer {cfg.token()}"})
    filters = {"exclude_platforms": "nes", "limit": 1, "favorites": True, "local": "pc", "recent": True}
    page = client.get("/api/catalog", params=filters).raise_for_status().json()
    assert page["total"] == 2 and page["items"][0]["title"] == "Beta"
    page = client.get("/api/catalog", params=filters | {"offset": 1}).json()
    assert page["items"][0]["title"] == "Zelda"
    assert client.get("/api/catalog/letter_offset", params=filters | {"letter": "Z"}).json()["offset"] == 1
    assert client.get("/api/catalog", params=filters | {"q": "Alpha"}).json()["total"] == 0
    assert client.get("/api/catalog", params=filters | {"platform": "nes,snes,"}).json()["total"] == 2
    assert client.get("/api/catalog", params={"exclude_platforms": "nes,snes"}).json()["total"] == 0
    assert client.get("/api/catalog").json()["total"] == 4
    store.db.close()
