import asyncio
import base64
import json

import httpx
import pytest


def test_hermes_can_select_other_pc_and_read_its_desktop(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.client import Client
    from gbox.mcp_server import build

    png = b"\x89PNG\r\n\x1a\nremote-desktop"
    posted = []

    def handler(req):
        path = req.url.path
        if path == "/api/registry":
            return httpx.Response(200, json={"tools": []})
        if path == "/api/workers/idle":
            assert req.url.params["tool"] in ("launch_game", "get_frame")
            return httpx.Response(200, json={"id": "other", "name": "Test PC", "os": "windows", "online": True})
        if path == "/api/workers":
            return httpx.Response(200, json=[{"id": "main"}, {"id": "other"}])
        if path == '/api/jobs' and req.method == 'GET':
            return httpx.Response(200, json=[])
        if path == "/api/jobs" and req.method == "POST":
            posted.append((path, json.loads(req.content)))
            return httpx.Response(200, json={"id": "frame-job", "state": "succeeded", "worker_id": "other",
                                             "output": {"sha256": "frame-sha"}})
        if path == "/api/artifacts/frame-sha":
            return httpx.Response(200, content=png, headers={"content-type": "image/png"})
        if path == "/api/requests/report/messages":
            posted.append((path, json.loads(req.content)))
            return httpx.Response(200, json={"ok": True})
        raise AssertionError(path)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: original(*args, **kwargs, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"list_workers", "select_idle_worker", "capture_worker_screen"} <= names
            chosen = await client.call_tool("select_idle_worker", {"tool": "get_frame"})
            assert json.loads(chosen.content[0].text)["id"] == "other"
            image = await client.call_tool("capture_worker_screen", {"request_id": "report", "text": "Game setup on test PC"})
            assert image.content[1].type == "image" and base64.b64decode(image.content[1].data) == png

    asyncio.run(check())
    assert posted[0][1]["require_worker"] == "other" and posted[0][1]["agent_use"]
    assert posted[1][1]["attachments"][0]["b64"] == base64.b64encode(png).decode()
