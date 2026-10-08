"""An old JSON thumbnail must not prevent the operator from capturing a real picture."""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from gbox.config import Config
from gbox.server import create_app


@pytest.mark.parametrize("old", ["json", "missing"])
def test_bad_thumbnail_can_be_replaced_without_force(tmp_path, old):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    store = app.state.store
    thumb = store.put_artifact(b"{}", "broken.png", "image/png", {}).sha256 if old == "json" else "missing"
    store.put("mod", "test-mod", {"id": "test-mod", "game_id": "game", "thumb": thumb})
    output = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(output, "PNG")
    png = output.getvalue()
    headers = {"Authorization": f"Bearer {cfg.token()}"}
    with TestClient(app) as client:
        assert client.get("/api/mods", headers=headers).json()[0]["thumb"] is None
        workbench = client.get("/api/games/game/workbench", headers=headers).json()
        assert workbench["mods"][0]["thumb"] is None
        response = client.post("/api/mods/test-mod/thumb", headers=headers, content=png)
        assert response.status_code == 200, response.text
        new_thumb = response.json()["thumb"]
        assert new_thumb != thumb
        assert store.read_artifact(new_thumb) == png
        # A good picture stays in place on ordinary capture requests.
        assert client.post("/api/mods/test-mod/thumb", headers=headers, json={}).json()["thumb"] == new_thumb


def test_json_body_is_not_saved_as_an_image(tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    app.state.store.put("mod", "test-mod", {"id": "test-mod", "game_id": "game"})
    with TestClient(app) as client:
        response = client.post("/api/mods/test-mod/thumb", json={},
                               headers={"Authorization": f"Bearer {cfg.token()}"})
    assert response.status_code == 400
    assert app.state.store.get("mod", "test-mod").get("thumb") is None
