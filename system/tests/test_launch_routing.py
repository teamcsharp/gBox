"""PS2 play must not silently move from a gaming PC to the Spark's ARM backend."""
import pytest
from fastapi.testclient import TestClient

from gbox.config import Config
from gbox.server import create_app


@pytest.mark.parametrize("platform,node,expected", [
    ("ps2", "auto", "windows"),
    ("ps3", "auto", "windows"),
    ("ps2", "linux", "linux"),
    ("ps2", "windows", "windows"),
    ("psp", "auto", "linux"),
    ("switch", "auto", "windows"),
])
def test_launch_host(tmp_path, platform, node, expected):
    cfg = Config(data_dir=tmp_path)
    app = create_app(cfg)
    app.state.store.upsert_catalog([{
        "game_id": "test-game", "title": "Test game", "platform": platform,
        "source_paths": ["test.iso"], "format": "iso", "profile_id": "test-game",
        "core": "pcsx2" if platform == "ps2" else "ppsspp",
        "launch": {"kind": "attract", "path": "test.iso"},
    }])
    with TestClient(app) as client:
        response = client.post(f"/api/games/test-game/launch?node={node}&mod=sonic",
                               headers={"Authorization": f"Bearer {cfg.token()}"}, json={})
    assert response.status_code == 200, response.text
    assert response.json()["require_os"] == expected
    assert response.json()["input"]["mod"] == "sonic"
