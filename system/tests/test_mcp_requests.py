"""Inbox work must be possible through Hermes' gBox MCP connection."""
import asyncio
import json

import httpx
import pytest


def test_mcp_inbox_round_trip_and_request_image(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.client import Client
    from gbox.mcp_server import build

    posted = []
    request = {"id": "req1", "number": 42, "title": "Touch game", "body": "Tap the game picture",
               "status": "open", "source": "app", "created": 1, "messages": [], "image": "abc"}
    recurring = {"id": "recurring", "number": 43, "title": "gBox request review (recurring, scheduled)",
                 "body": "Review reports", "status": "in_progress", "source": "app", "created": 2}

    def handler(req):
        path = req.url.path
        if path == "/api/registry":
            return httpx.Response(200, json={"tools": []})
        if path == "/api/requests":
            return httpx.Response(200, json=[recurring, request])
        if path == "/api/requests/req1":
            return httpx.Response(200, json=request)
        if path == "/api/artifacts/abc":
            return httpx.Response(200, content=b"\x89PNG\r\n\x1a\n", headers={"content-type": "image/png"})
        if path in ("/api/requests/req1/messages", "/api/requests/req1/status", "/api/requests/req1/metrics",
                    "/api/requests/req1/capture"):
            posted.append((path, json.loads(req.content)))
            return httpx.Response(200, json=request)
        raise AssertionError(path)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: original(*args, **kwargs, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"list_requests", "get_request", "read_request_artifact", "reply_request", "capture_request_screenshot",
                    "set_request_status", "record_request_metrics"} <= names
            page = await client.call_tool("list_requests", {"status": "open", "limit": 1})
            assert json.loads(page.content[0].text)["items"][0]["number"] == 42
            all_rows = await client.call_tool("list_requests", {"include_recurring": True, "limit": 2})
            assert json.loads(all_rows.content[0].text)["items"][0]["number"] == 43
            detail = await client.call_tool("get_request", {"request_id": "req1"})
            assert json.loads(detail.content[0].text)["body"] == "Tap the game picture"
            image = await client.call_tool("read_request_artifact", {"request_id": "req1", "sha256": "abc"})
            assert image.content[0].type == "image" and image.content[0].mime_type == "image/png"
            denied = await client.call_tool("read_request_artifact", {"request_id": "req1", "sha256": "other"})
            assert denied.is_error
            await client.call_tool("reply_request", {"request_id": "req1", "text": "Verified"})
            await client.call_tool("reply_request", {"request_id": "req1", "body": "Progress"})
            await client.call_tool("reply_request", {"request_id": "req1", "message": "Result"})
            await client.call_tool("capture_request_screenshot", {"request_id": "req1", "session_id": "s1",
                "text": "Verified frame", "task_step": {"action": "verify", "attempt": "1", "result": "visible", "status": "finished"}})
            await client.call_tool("record_request_metrics", {"request_id": "req1", "model": "test", "tokens_in": 10, "tokens_out": 2})
            await client.call_tool("record_request_metrics", {"request_id": "req1", "metrics": {"tokens_in": 3, "tokens_out": 1}})
            await client.call_tool("record_request_metrics", {"request_id": "req1", "metrics": {},
                "model": "test", "tokens_in": 4, "tokens_out": 2,
                "tokens_detail": {"token_count_unavailable": 1}, "tools": {"chat_review": 1}})
            await client.call_tool("set_request_status", {"request_id": "req1", "status": "done"})

    asyncio.run(check())
    assert posted == [
        ("/api/requests/req1/messages", {"author": "agent", "text": "Verified"}),
        ("/api/requests/req1/messages", {"author": "agent", "text": "Progress"}),
        ("/api/requests/req1/messages", {"author": "agent", "text": "Result"}),
        ("/api/requests/req1/capture", {"session_id": "s1", "text": "Verified frame",
            "task_step": {"action": "verify", "attempt": "1", "result": "visible", "status": "finished"}}),
        ("/api/requests/req1/metrics", {"model": "test", "tokens_in": 10, "tokens_out": 2}),
        ("/api/requests/req1/metrics", {"tokens_in": 3, "tokens_out": 1}),
        ("/api/requests/req1/metrics", {"model": "test", "tokens_in": 4, "tokens_out": 2,
            "tokens_detail": {"token_count_unavailable": 1}, "tools": {"chat_review": 1}}),
        ("/api/requests/req1/status", {"status": "done", "note": ""}),
    ]
