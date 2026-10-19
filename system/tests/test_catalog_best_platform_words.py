"""#2375: "Resident Evil 2 Dual Shock PS1 USA" finds the PS1 disc. Every word must prefix-match a title in
store.search, and platform or region words rarely do: rank_games drops them when the full query has no hit, keeps the
platform as a filter (then a bonus) and ranks as before. The agent's re_dossier and the spoken "load <game>" use it."""
from fastapi.testclient import TestClient

from gbox.server import create_app


def entry(gid, title, platform, system):
    return {"game_id": gid, "title": title, "platform": platform, "library": "lib", "system": system}


def test_platform_and_region_words_do_not_sink_the_query(cfg):
    app = create_app(cfg)
    app.state.store.upsert_catalog([
        entry("a" * 16, "Resident Evil 2 - Dual Shock Edition (Disc 1)", "psx", "Sony PlayStation"),
        entry("b" * 16, "Resident Evil 2 (USA)", "gamecube", "Nintendo GameCube"),
        entry("c" * 16, "Resident Evil 2 - Dual Shock Edition (Disc 1)", "psp", "Sony PSP")])
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    best = client.get("/api/catalog/best", params={"q": "Resident Evil 2 Dual Shock PS1 USA", "limit": 3}).json()
    assert best and best[0]["game_id"] == "a" * 16, best
    best = client.get("/api/catalog/best", params={"q": "resident evil 2 dual shock psp"}).json()
    assert best and best[0]["game_id"] == "c" * 16, "the platform word picks the PSP release"
    assert client.get("/api/catalog/best", params={"q": "Resident Evil 2 Dual Shock"}).json(), "a plain query still works"
    assert client.get("/api/catalog/best", params={"q": "PS1 USA"}).json() == [], "only platform and region words: nothing to match"
    assert client.get("/api/catalog/best", params={"q": "Jet Set Radio xbox"}).json() == [], "a title that is not there stays not there"
