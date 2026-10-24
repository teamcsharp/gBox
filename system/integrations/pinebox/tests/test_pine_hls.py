import concurrent.futures
import hashlib
import importlib.util
import inspect
import json
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hls = load("pine_hls", ROOT / "gbox_hls.py")
installer = load("pine_installer", ROOT / "install.py")
PLAYLIST = b"#EXTM3U\n#EXT-X-VERSION:6\n#EXTINF:1,\nseg_00001.ts\n"


class Hub:
    @staticmethod
    def tile_view(row, t, broadcast):
        return {"key": row["key"], "broadcast": broadcast}

    def __init__(self):
        self.allowed = {"pc-spark1"}
        self.seen_rows = []
        self.gw = SimpleNamespace(base="http://gbox:8765", url=lambda p: "http://gbox:8765" + p,
                                  headers=lambda: {"Authorization": "Bearer private-server-secret"})

    def pictures(self):
        return {"pc-spark1": "/api/broadcast/pc/lilspark.mjpg", "s-private": "/api/broadcast/session/priv.mjpg"}

    def allowed_keys(self):
        return set(self.allowed)

    def seen(self, who):
        self.seen_rows.append(who)


def application(fetch=None):
    hub = Hub()
    # A new class per installation avoids test monkeypatch inheritance.
    class FreshHub:
        tile_view = staticmethod(lambda row, t, broadcast: {"key": row["key"]})
    stream = SimpleNamespace(HUB=hub, Hub=FreshHub, PREVIEW_KEY="gbox-preview", KEY_RE=re.compile(r"^[A-Za-z0-9_-]{1,96}$"))
    valid = {"live-token"}
    reads = []

    def auth(authorization):
        reads.append(authorization)
        if authorization != "Bearer house":
            raise HTTPException(401)

    app = FastAPI()
    app.get("/healthz")(lambda: {"ok": True})
    relay = hls.BoundedRelay(fetch or (lambda url, headers, limit: PLAYLIST if url.endswith("m3u8") else b"ts-data"))
    hls.install(app, {"listen_ok": lambda t: t in valid, "media_sign": lambda k: "preview-signature",
                      "require_read_auth": auth}, stream, relay)
    return TestClient(app), hub, stream, valid, reads, relay


def test_public_playlist_and_segment_use_only_selected_stage_and_server_header():
    calls = []
    def fetch(url, headers, limit):
        calls.append((url, headers, limit))
        return PLAYLIST if url.endswith("m3u8") else b"ts-data"
    client, hub, stream, _, _, _ = application(fetch)
    public = {"x-pinebox-public": "1"}
    tile = stream.Hub.tile_view({"key": "pc-spark1"}, "live-token", True)
    assert tile["hls_fps"] == 30
    response = client.get(tile["hls"], headers=public)
    assert response.status_code == 200
    assert "/api/gbox/hls?k=pc-spark1&name=seg_00001.ts&t=live-token" in response.text
    assert "private-server-secret" not in response.text
    assert client.get(response.text.splitlines()[-1], headers=public).content == b"ts-data"
    assert all(c[1] == {"Authorization": "Bearer private-server-secret"} for c in calls)
    assert calls[0][0] == "http://gbox:8765/api/broadcast/pc/lilspark/hls/index.m3u8"
    assert client.get("/api/gbox/hls?k=s-private&t=live-token", headers=public).status_code == 404


@pytest.mark.parametrize("query,status", [("k=pc-spark1", 403), ("k=pc-spark1&t=bad", 403),
                                         ("k=pc-spark1&s=preview-signature", 403),
                                         ("k=../private&t=live-token", 404),
                                         ("k=pc-spark1&t=live-token&name=../../api_token", 404)])
def test_public_auth_and_object_paths(query, status):
    client, *_ = application()
    assert client.get("/api/gbox/hls?" + query, headers={"x-pinebox-public": "1"}).status_code == status


def test_house_read_and_preview_auth_preserve_existing_contract():
    client, *_ = application()
    assert client.get("/api/gbox/hls?k=pc-spark1").status_code == 401
    assert client.get("/api/gbox/hls?k=pc-spark1", headers={"Authorization": "Bearer house"}).status_code == 200
    assert client.get("/api/gbox/hls?k=s-private&s=preview-signature").status_code == 200
    assert client.get("/api/gbox/hls?k=pc-spark1&s=wrong").status_code == 403


def test_cached_segments_still_require_live_token_and_current_stage_membership():
    client, hub, _, valid, _, relay = application()
    url = "/api/gbox/hls?k=pc-spark1&name=seg_00001.ts&t=live-token"
    assert client.get(url).status_code == 200
    assert relay.cache
    valid.clear()
    assert client.get(url).status_code == 403
    valid.add("live-token")
    hub.allowed.clear()
    assert client.get(url).status_code == 404


def test_token_revoked_during_encoder_start_never_returns_media():
    holder = {}
    def fetch(*_):
        holder["valid"].clear()
        return PLAYLIST
    client, _, _, valid, *_ = application(fetch)
    holder["valid"] = valid
    assert client.get("/api/gbox/hls?k=pc-spark1&t=live-token").status_code == 403


@pytest.mark.parametrize("bad", [b"not-hls", b"#EXTM3U\nhttps://evil/steal.ts\n", b"#EXTM3U\n../api_token\n",
                                b"#EXTM3U\nseg_00001.ts?token=secret\n", b'#EXTM3U\n#EXT-X-KEY:URI="https://evil"\n'])
def test_playlist_cannot_leak_credentials_or_relay_external_paths(bad):
    with pytest.raises(ValueError):
        hls.rewrite_playlist(bad, "pc-spark1", "live-token")


def test_bounded_cache_and_single_flight_dont_duplicate_segment_downloads():
    entered, release = threading.Event(), threading.Event()
    calls = []
    def fetch(*args):
        calls.append(args)
        entered.set()
        assert release.wait(2)
        return b"segment"
    relay = hls.BoundedRelay(fetch)
    hub = Hub()
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        a = pool.submit(relay.read, hub, "/segment", False)
        assert entered.wait(1)
        b = pool.submit(relay.read, hub, "/segment", False)
        release.set()
        assert a.result() == b.result() == b"segment"
    assert len(calls) == 1
    relay.fetch = lambda *_: b"12345"
    for i in range(100):
        relay.read(hub, f"/segment{i}", False)
    assert len(relay.cache) <= 64 and relay.bytes <= hls.MAX_CACHE


def test_blocked_upstream_does_not_block_pine_event_loop_or_leak_errors():
    entered, release = threading.Event(), threading.Event()
    def fetch(*_):
        entered.set()
        assert release.wait(2)
        raise RuntimeError("Authorization Bearer secret")
    client, *_ = application(fetch)
    endpoint = next(route.endpoint for route in client.app.routes if route.path == "/api/gbox/hls")
    assert not inspect.iscoroutinefunction(endpoint)
    with concurrent.futures.ThreadPoolExecutor() as pool:
        response = pool.submit(client.get, "/api/gbox/hls?k=pc-spark1&t=live-token")
        assert entered.wait(1)
        assert client.get("/healthz").json() == {"ok": True}
        release.set()
        result = response.result()
    assert result.status_code == 503 and "secret" not in result.text


def test_assets_are_pinned_and_route_does_not_serve_arbitrary_files():
    client, *_ = application()
    manifest = json.loads((ROOT / "vendor-manifest.json").read_text())
    for row in manifest["files"]:
        assert hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() == row["sha256"]
    response = client.get("/gbox-hls/hls-1.7.3.min.js")
    assert response.status_code == 200 and len(response.content) > 600000
    assert client.get("/gbox-hls/app.py").status_code == 404
    assert client.get("/gbox-hls/hls-1.7.3.min.js", headers={"if-none-match":response.headers["etag"]}).status_code == 304


def test_installer_is_idempotent_backs_up_original_and_never_changes_station_settings(tmp_path):
    target = tmp_path / "pine"
    (target / "frontend").mkdir(parents=True)
    original = ('import os\n_PUBLIC_GET = set()\ngboxstream.install(app, globals())  # original\n'
                'async def _startup_public_door() -> None:\n'
                '    config = uvicorn.Config(PublicListenerGate(app), host="0.0.0.0", port=PUBLIC_PORT)\n')
    (target / "app.py").write_text(original)
    (target / "gboxstream.py").write_text("# original stream\n")
    (target / "frontend/gbox-tune.js").write_text("old-js")
    (target / "frontend/gbox-tune.css").write_text("old-css")
    (target / "data").mkdir()
    config = target / "data/gbox-stream.json"
    config.write_text('{"on":false,"fps":12}')
    compose=tmp_path/'compose.yaml';compose.write_bytes(b'services:\n  spark-agent:\n    environment:\n      SECRET: unchanged\n')
    original_compose=compose.read_bytes()
    receipt = installer.install(target, package=ROOT)
    assert (Path(receipt["backup"]) / "app.py").read_text() == original
    assert (target / "app.py").read_text().count(installer.MARK) == 1
    assert config.read_text() == '{"on":false,"fps":12}'
    assert compose.read_bytes()==original_compose and receipt['gateway_config_applied'] is False
    assert 'host="0.0.0.0"' in (target/'app.py').read_text()
    assert 'PINE_GBOX_PUBLIC_BACKEND_HOST' not in (target/'app.py').read_text()
    for name in ('media_gateway.py','install_gateway.py'):
        assert (target/name).read_bytes()==(ROOT/name).read_bytes()
    assert 'opt-in hash-guarded' in receipt['gateway_activation']
    assert 'container restart' in receipt['activation']
    assert installer.install(target, package=ROOT)["changed"] == []
    (target / 'frontend/pine-hls.js').write_text('old helper')
    static = installer.install(target, package=ROOT)
    assert [row['file'] for row in static['changed']] == ['frontend/pine-hls.js']
    assert 'served immediately' in static['activation']
    with pytest.raises(ValueError):
        installer.patched_app("wrong application")
