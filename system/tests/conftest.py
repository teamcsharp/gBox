import socket
import threading
import time

import httpx
import pytest
import uvicorn

from gbox import uap, worker
from gbox.config import Config
from gbox.server import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", api_port=free_port())


@pytest.fixture
def plane(cfg):
    """Real HTTP control plane + real worker thread, talking over localhost."""
    app = create_app(cfg)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cfg.api_port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    url = f"http://127.0.0.1:{cfg.api_port}"
    # Wait for each condition with a deadline and fail loudly: a fixed 5 s of polls ran out on a loaded
    # machine (the worker's first describe() imports every tool module), and the test then ran against
    # a plane with no registered worker (test_unavailable_tool_never_claimed: KeyError 'test-worker').
    end = time.time() + 60
    while True:
        try:
            httpx.get(url + "/api/health")
            break
        except httpx.TransportError:
            if time.time() > end:
                raise RuntimeError("test control plane did not start") from None
            time.sleep(0.05)
    stop = threading.Event()
    threading.Thread(target=worker.run, args=(url, cfg.token(), cfg, "test-worker", stop, 0.05), daemon=True).start()
    client = httpx.Client(base_url=url, headers={"authorization": f"Bearer {cfg.token()}"}, timeout=30)
    while not any(w.get("name") == "test-worker" and w.get("online") for w in client.get("/api/workers").json()):
        if time.time() > end:
            stop.set()
            srv.should_exit = True
            raise RuntimeError("test worker did not register with the control plane")
        time.sleep(0.05)
    client.app = app
    yield client
    stop.set()
    srv.should_exit = True


def run_job(client, tool, inp, timeout=30):
    job = client.post("/api/jobs", json={"tool": tool, "input": inp}).raise_for_status().json()
    end = time.time() + timeout
    while job["state"] in ("queued", "running") and time.time() < end:
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job['id']}").json()
    return job


def make_cube(name="cube") -> uap.Manifest:
    """8-vertex cube skinned to a 2-bone chain with one clip."""
    P = [[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    idx = [i for a, b, c, d in faces for i in (a, b, c, a, c, d)]
    return uap.Manifest(
        name=name, source={"game_id": "fixture", "resource_ids": ["cube"], "extraction_method": "synthetic"},
        meshes=[uap.Mesh(name="cube", positions=P, normals=[[v / 3 ** .5 for v in p] for p in P],
                         uvs=[[(p[0] + 1) / 2, (p[1] + 1) / 2] for p in P], indices=idx, material=0,
                         joints=[[0 if p[1] < 0 else 1, 0, 0, 0] for p in P], weights=[[1, 0, 0, 0]] * 8)],
        materials=[uap.Material(name="grey", base_color=[.5, .5, .5, 1])],
        skeleton=[uap.Bone(name="root"), uap.Bone(name="tip", parent=0, translation=[0, 1, 0])],
        animations=[uap.Clip(name="bend", channels=[uap.Channel(
            bone=1, path="rotation", times=[0, 0.5, 1], values=[[0, 0, 0, 1], [0, 0, .3826834, .9238795], [0, 0, 0, 1]])])],
        nodes=[uap.Node(name="cube", mesh=0, skinned=True)], roots=[0],
        confidence={"geometry": "verified", "skeleton": "verified", "animations": "verified", "textures": "missing"},
        provenance=[{"by": "tests/conftest.py", "note": "synthetic fixture"}])
