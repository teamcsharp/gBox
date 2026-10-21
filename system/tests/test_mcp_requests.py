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
        if path == '/api/tasks':
            return httpx.Response(200, json={'jobs': [{'id': 'worker-job', 'state': 'running'}], 'hermes': [
                {'id': 'live-run', 'name': 'Investigation #42', 'state': 'running'},
                {'id': 'old-run', 'state': 'completed'}]})
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
            active = json.loads((await client.call_tool('list_tasks', {})).content[0].text)
            assert active['hermes'] == [{'id': 'live-run', 'name': 'Investigation #42', 'state': 'running'}]
            assert active['jobs'][0]['id'] == 'worker-job'
            history = json.loads((await client.call_tool('list_tasks', {'include_finished': True})).content[0].text)
            assert len(history['hermes']) == 2
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


def test_advertised_metrics_schema_types_dynamic_tool_counts_and_nested_fields(monkeypatch):
    pytest.importorskip("mcp")
    from jsonschema import Draft202012Validator
    from mcp.client import Client
    from gbox.mcp_server import build

    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"tools": []}))
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=transport))

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            tool = next(t for t in (await client.list_tools()).tools if t.name == "record_request_metrics")
            schema = tool.input_schema
            props = schema["properties"]
            assert props["tools"]["additionalProperties"] == {"type": "integer", "minimum": 0}
            assert props["metrics"]["properties"]["tools"] == props["tools"]
            validator = Draft202012Validator(schema)
            token_metadata = {"source": "SDK", "cost": None, "nested": {"cache": 3},
                              "token_count_unavailable": 1}
            for nested in (False, True):
                fields = {"tools": {"ghidra_http_scripted_queries": 8000, "unused": 0},
                          "tokens_detail": token_metadata, "duration_s": 1.25}
                valid = {"request_id": "req1", **({"metrics": fields} if nested else fields)}
                assert not list(validator.iter_errors(valid))
                for bad in ("~8000 (bulk read-only)", -1, True, None, {"count": 1}):
                    fields = {"tools": {"ghidra_http_scripted_queries": bad}}
                    invalid = {"request_id": "req1", **({"metrics": fields} if nested else fields)}
                    assert list(validator.iter_errors(invalid))

    asyncio.run(check())


@pytest.mark.parametrize("bad", ["~8000 (bulk read-only)", "8000", -1, True, 1.5, 1.0, None, []])
@pytest.mark.parametrize("nested", [False, True])
def test_metrics_counter_validation_is_early_and_names_the_bad_field(bad, nested):
    pytest.importorskip("mcp")
    from gbox.mcp_server import _request_metrics

    fields = {"tools": {"ghidra_http_scripted_queries": bad}}
    arguments = {"request_id": "req1", **({"metrics": fields} if nested else fields)}
    with pytest.raises(ValueError, match="tools.ghidra_http_scripted_queries.*nonnegative integer"):
        _request_metrics(arguments)


@pytest.mark.parametrize("arguments", [
    {"request_id": "req1", "metrics": []},
    {"request_id": "req1", "metrics": None},
    {"request_id": "req1", "tools": []},
    {"request_id": "req1", "metrics": {"tools": None}},
    # Do not silently hide an invalid flat counter behind a nested override.
    {"request_id": "req1", "tools": {"ghidra": "unknown"}, "metrics": {"tools": {"ghidra": 3}}},
])
def test_metrics_validation_rejects_bad_containers_and_overridden_bad_counts(arguments):
    pytest.importorskip("mcp")
    from gbox.mcp_server import _request_metrics

    with pytest.raises(ValueError):
        _request_metrics(arguments)


def test_real_failed_counter_submission_does_not_reach_http(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.client import Client
    from gbox.mcp_server import build

    posted = []

    def handler(req):
        if req.url.path == "/api/registry":
            return httpx.Response(200, json={"tools": []})
        posted.append(req.url.path)
        return httpx.Response(200, json={"ok": True})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            for nested in (False, True):
                fields = {"tools": {"ghidra_http_scripted_queries": "~8000 (bulk read-only)"}}
                result = await client.call_tool("record_request_metrics", {
                    "request_id": "req1", **({"metrics": fields} if nested else fields)})
                assert result.is_error
                assert "ghidra_http_scripted_queries" in result.content[0].text
                assert "integer" in result.content[0].text

    asyncio.run(check())
    assert posted == []


def test_mutation_receipts_keep_actual_message_attachments_and_metrics_without_history(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.client import Client
    from gbox.mcp_server import build

    historical = "OLD REPORT CONTENT " * 4000
    report = {"id": "req1", "number": 1216, "status": "in_progress", "body": historical,
              "messages": [{"author": "operator", "text": historical}],
              "metrics": {"tokens_in": 100, "tokens_out": 5, "tools": {"ghidra": 2}}}
    step = {"action": "inspect", "attempt": "R5", "result": "producer still unresolved", "status": "in_progress"}
    attachment = {"name": "trace.json", "sha256": "abc", "type": "application/json", "size": 8}
    posted_message = {"author": "agent", "text": "Verified trace correction", "ts": 42,
                      "task_step": step, "attachments": [attachment]}
    token_metadata = {"source": "SDK", "cost": None, "nested": {"cached_tokens": 9}}
    posted = []

    def handler(req):
        path = req.url.path
        if path == "/api/registry":
            return httpx.Response(200, json={"tools": []})
        if path == "/api/requests/req1":
            return httpx.Response(200, json=report)
        body = json.loads(req.content)
        posted.append((path, body))
        if path == "/api/requests/req1/messages":
            report["messages"].append(posted_message)
        elif path == "/api/requests/req1/metrics":
            report["metrics"] = {"tokens_in": 103, "tokens_out": 6, "tools": {"ghidra": 8002},
                                 "tokens_detail": token_metadata, "model": "test", "provider": "nous"}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=report)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            reply = await client.call_tool("reply_request", {"request_id": "req1", "body": "Verified trace correction", "task_step": step})
            assert not reply.is_error
            receipt = json.loads(reply.content[0].text)
            assert receipt == {"ok": True, "request_id": "req1", "id": "req1", "number": 1216,
                               "status": "in_progress", "message_count": 2, "posted_message": posted_message}
            assert len(reply.content[0].text) < 2000 and "OLD REPORT CONTENT" not in reply.content[0].text
            metrics = await client.call_tool("record_request_metrics", {"request_id": "req1", "tokens_in": 3,
                "tokens_out": 1, "model": "test", "provider": "nous", "metrics": {
                    "tools": {"ghidra": 8000}, "tokens_detail": token_metadata}})
            assert not metrics.is_error
            receipt = json.loads(metrics.content[0].text)
            assert receipt["metrics"] == report["metrics"]
            assert receipt["metrics"]["tools"]["ghidra"] == 8002  # Stored aggregate, not an echo of 8000.
            assert receipt["status"] == "in_progress"
            assert len(metrics.content[0].text) < 2000 and "OLD REPORT CONTENT" not in metrics.content[0].text
            full = await client.call_tool("get_request", {"request_id": "req1"})
            assert json.loads(full.content[0].text) == report
            assert len(full.content[0].text) > 65_000

    asyncio.run(check())
    assert posted == [("/api/requests/req1/messages", {"author": "agent", "text": "Verified trace correction", "task_step": step}),
                      ("/api/requests/req1/metrics", {"tokens_in": 3, "tokens_out": 1, "model": "test", "provider": "nous",
                        "tools": {"ghidra": 8000}, "tokens_detail": token_metadata})]


def test_failed_mutation_never_returns_success_receipt(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.client import Client
    from gbox.mcp_server import build

    def handler(req):
        if req.url.path == "/api/registry":
            return httpx.Response(200, json={"tools": []})
        return httpx.Response(422, json={"detail": "rejected by server"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            for tool, args in (("reply_request", {"text": "Progress"}),
                               ("record_request_metrics", {"tools": {"ghidra": 1}})):
                result = await client.call_tool(tool, {"request_id": "req1", **args})
                assert result.is_error
                receipt = json.loads(result.content[0].text)
                assert "422" in receipt["error"] and "ok" not in receipt

    asyncio.run(check())


def test_mcp_compact_receipts_match_actual_http_persistence(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from fastapi.testclient import TestClient
    from mcp.client import Client
    from gbox.config import Config
    from gbox.mcp_server import build
    from gbox.server import create_app

    cfg = Config(data_dir=tmp_path)
    with TestClient(create_app(cfg), headers={"Authorization": "Bearer " + cfg.token()}) as backend:
        report = backend.post("/api/requests", json={"title": "Trace review", "body": "Original instructions",
                                                    "source": "api"}).json()
        rid = report["id"]
        backend.post(f"/api/requests/{rid}/metrics", json={"tokens_in": 100, "tools": {"ghidra": 2}}).raise_for_status()

        def handler(req):
            response = backend.request(req.method, req.url.path, content=req.content,
                                       headers={"content-type": "application/json"})
            return httpx.Response(response.status_code, content=response.content,
                                  headers={"content-type": "application/json"})

        original = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))

        async def check():
            async with Client(build("http://fixture", "fixture")) as client:
                reply = await client.call_tool("reply_request", {"request_id": rid, "text": "Result still pending",
                    "task_step": {"action": "trace", "status": "in_progress"}})
                assert not reply.is_error, reply.content[0].text
                receipt = json.loads(reply.content[0].text)
                stored = backend.get(f"/api/requests/{rid}").json()
                assert receipt["posted_message"] == stored["messages"][-1]
                assert receipt["id"] == rid and receipt["number"] == stored["number"]
                assert "messages" not in receipt and "body" not in receipt
                result = await client.call_tool("record_request_metrics", {"request_id": rid,
                    "metrics": {"tokens_in": 3, "tools": {"ghidra": 4},
                                "tokens_detail": {"source": "SDK", "cost": None}}})
                assert not result.is_error
                receipt = json.loads(result.content[0].text)
                stored = backend.get(f"/api/requests/{rid}").json()
                assert receipt["metrics"] == stored["metrics"]
                assert receipt["metrics"]["tools"]["ghidra"] == 6
                assert receipt["metrics"]["tokens_in"] == 103
                assert receipt["metrics"]["tokens_detail"] == {"source": "SDK", "cost": None}
                assert receipt["status"] == stored["status"] == "open"
                # The HTTP API continues returning full reports; compaction is MCP-only.
                assert stored["body"] == "Original instructions" and len(stored["messages"]) == 2

        asyncio.run(check())


def test_status_tool_schema_matches_solver_http_limits():
    pytest.importorskip("mcp")
    from jsonschema import Draft202012Validator
    from gbox.mcp_server import CONVENIENCE, _request_status

    schema = CONVENIENCE["set_request_status"][1]
    validate = Draft202012Validator(schema)
    base = {"request_id": "req1", "status": "done",
            "solved_by": {"service": "Hermes", "verification": "Acceptance verified from recorded evidence."}}
    for name, limit in {"service": 80, "model": 160, "system": 80, "verified_by": 80,
                        "verification": 2000, "run_id": 80}.items():
        exact = base | {"solved_by": base["solved_by"] | {name: "x" * limit}}
        assert not list(validate.iter_errors(exact))
        assert _request_status(exact)["solved_by"][name] == "x" * limit
        too_long = base | {"solved_by": base["solved_by"] | {name: "x" * (limit + 1)}}
        assert list(validate.iter_errors(too_long))
        with pytest.raises(ValueError, match=rf"solved_by\.{name} exceeds {limit}.*preserve"):
            _request_status(too_long)
    for name in ("service", "verification"):
        empty = base | {"solved_by": base["solved_by"] | {name: ""}}
        assert list(validate.iter_errors(empty))
        with pytest.raises(ValueError, match="must not be empty"):
            _request_status(empty)
    nullable = base | {"solved_by": base["solved_by"] | {"run_id": None}}
    assert not list(validate.iter_errors(nullable)) and _request_status(nullable)["solved_by"]["run_id"] is None
    with pytest.raises(ValueError, match="only valid for done"):
        _request_status(base | {"status": "in_progress"})


def test_status_tool_prevents_oversized_credit_http_call_and_preserves_corrected_evidence(tmp_path, monkeypatch):
    pytest.importorskip("mcp")
    from fastapi.testclient import TestClient
    from mcp.client import Client
    from gbox.config import Config
    from gbox.mcp_server import build
    from gbox.server import create_app

    cfg = Config(data_dir=tmp_path)
    backend = TestClient(create_app(cfg), headers={"Authorization": "Bearer " + cfg.token()})
    report = backend.post("/api/requests", json={"title": "Verified observer", "body": "Verify the observer",
                                                "source": "api"}).json()
    rid, posts = report["id"], []
    def handler(req):
        if req.method == "POST": posts.append(json.loads(req.content))
        response = backend.request(req.method, req.url.path, content=req.content,
                                   headers={"content-type": "application/json"})
        return httpx.Response(response.status_code, content=response.content,
                              headers={"content-type": "application/json"})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: original(*a, **kw, transport=httpx.MockTransport(handler)))
    evidence = "e" * 2000
    detail = "Longer recorded test and runtime evidence. " * 100
    solver = {"service": "Hermes", "verified_by": "r" * 80, "verification": evidence, "run_id": None}

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            bad = await client.call_tool("set_request_status", {"request_id": rid, "status": "done",
                "solved_by": solver | {"verified_by": "r" * 81}})
            assert bad.is_error and "verified_by" in bad.content[0].text
            assert posts == [] and backend.get(f"/api/requests/{rid}").json()["status"] == "open"
            good = await client.call_tool("set_request_status", {"request_id": rid, "status": "done",
                "solved_by": solver, "note": detail})
            assert not good.is_error, good.content[0].text
    asyncio.run(check())
    assert len(posts) == 1 and posts[0]["solved_by"] == solver and posts[0]["note"] == detail
    stored = backend.get(f"/api/requests/{rid}").json()
    assert stored["status"] == "done" and stored["solved_by"]["verification"] == evidence
    assert stored["solved_by"]["verified_by"] == "r" * 80 and stored["messages"][-1]["text"] == detail
