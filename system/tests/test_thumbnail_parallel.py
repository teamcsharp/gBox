from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

from fastapi.testclient import TestClient

from gbox.config import Library
from gbox.server import create_app


def test_parallel_thumbnail_requests_use_separate_temporary_files(cfg, tmp_path, monkeypatch):
    cfg.libraries = [Library(id="art", paths={"windows": str(tmp_path), "linux": str(tmp_path)})]
    (tmp_path / "cover.png").write_bytes(b"source fixture")
    app = create_app(cfg)
    app.state.store.upsert_catalog([{"game_id": "game", "title": "Game", "platform": "nes", "system": "nes",
                                    "library": "art", "media": {"boxart": ["cover"]}}])
    barrier = threading.Barrier(2)
    output_paths = []
    def render(args, **_):
        path = Path(args[-1])
        output_paths.append(path)
        path.write_bytes(b"thumbnail")
        barrier.wait(timeout=5)
        return type("Result", (), {"returncode": 0})()
    monkeypatch.setattr("gbox.server.subprocess.run", render)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: client.get("/api/media/game/best?w=360"), range(2)))
    assert [r.status_code for r in replies] == [200, 200]
    assert all(r.content == b"thumbnail" for r in replies)
    assert len(set(output_paths)) == 2
