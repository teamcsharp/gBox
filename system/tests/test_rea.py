"""REA catalog parity, boundaries, and real installed-runtime workflows."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import validators
from pydantic import ValidationError

from gbox import rea, rea_tool
from gbox.config import load
from gbox.models import Permission
from gbox.registry import Ctx, REGISTRY, execute


def test_complete_catalog_and_contracts():
    names = {t["name"] for t in rea_tool.CATALOG["tools"]}
    assert len(names) == 139
    assert {"rea_" + name for name in names} <= REGISTRY.keys()
    for contract in rea_tool.CATALOG["tools"]:
        for schema in (contract["inputSchema"], contract["outputSchema"]):
            validators.validator_for(schema).check_schema(schema)
        assert REGISTRY["rea_" + contract["name"]].info().input_schema == contract["inputSchema"]


def test_upstream_inputs_retain_defaults_and_reject_unknown_fields():
    model = REGISTRY["rea_open_binary"].In
    assert model.model_validate({"path": "/tmp/input.exe"}).model_dump() == {"path": "/tmp/input.exe"}
    for bad in ({}, {"path": 42}, {"path": "/tmp/input.exe", "unexpected": True}):
        with pytest.raises(ValidationError):
            model.model_validate(bad)
    assert REGISTRY["rea_get_evidence_bundle"].In.model_validate({}).model_dump() == {}


def test_explicit_effects_drive_permission_gates():
    assert Permission.FILE_MUTATION in REGISTRY["rea_export_evidence_bundle"].permissions
    assert Permission.MEMORY_WRITE in REGISTRY["rea_annotate_native_function"].permissions
    assert Permission.NETWORK in REGISTRY["rea_capture_process_scenario"].permissions
    assert Permission.FILE_MUTATION not in REGISTRY["rea_analyze_javascript_application"].permissions


def test_large_results_preserve_artifact_and_bound_polling_response():
    result = {"content": [{"type": "text", "text": "x" * 1000000}],
              "structuredContent": {"result": {"graph": [{"source": "x" * 10000} for _ in range(1000)]}, "evidence_id": "fixture"}}
    summary = rea_tool.inline_result(result)
    assert len(json.dumps(summary).encode()) <= 32768
    assert summary["_gbox_truncated"] and summary["_gbox_full_result"] == "rea-result.json"
    assert result["structuredContent"]["result"]["graph"][999]["source"] == "x" * 10000


def test_evidence_reader_paginates_without_losing_large_items(cfg, monkeypatch):
    import httpx
    data = json.dumps({"a/b": "x" * 10000, "items": [{"large": "y" * 100000}, {"small": "retained"}]}).encode()
    digest = hashlib.sha256(data).hexdigest()
    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: httpx.Response(200, content=data, request=httpx.Request("GET", args[0])))
    ctx = Ctx(cfg)
    ctx.server = "http://fixture"
    first = execute("read_rea_result", {"sha256": digest, "pointer": "/a~1b"}, ctx)
    second = execute("read_rea_result", {"sha256": digest, "pointer": "/a~1b", "offset": first["next_offset"]}, ctx)
    assert first["value"] + second["value"] == "x" * 10000 and second["next_offset"] is None
    page = execute("read_rea_result", {"sha256": digest, "pointer": "/items"}, ctx)
    assert page["value"][0]["pointer"] == "/items/0" and page["value"][1] == {"small": "retained"}
    assert page["truncated"] and len(json.dumps(page).encode()) < 32768
    with pytest.raises(ValueError, match="content hash"):
        execute("read_rea_result", {"sha256": "0" * 64}, ctx)
    with pytest.raises(ValueError, match="non-negative"):
        execute("read_rea_result", {"sha256": digest, "pointer": "/items/-1"}, ctx)


def test_discovery_does_not_require_a_runtime(cfg):
    result = execute("rea_tools", {"name": "rea_verify_reconstruction"}, Ctx(cfg))
    assert len(result["tools"]) == 1
    assert result["tools"][0]["gbox_name"] == "rea_verify_reconstruction"
    assert "specification" in result["tools"][0]["inputSchema"]["required"]
    assert execute("rea_tools", {"query": "javascript"}, Ctx(cfg))["tools"]
    assert rea.unavailable(cfg)


def test_agent_discovers_native_functions_and_keeps_worker_affinity(monkeypatch):
    import httpx
    from gbox.agent import Agent
    agent = Agent("http://fixture", "fixture", "http://fixture-llm", "fixture", "http://fixture-search")
    agent.api.close()
    agent.api = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[])), base_url="http://fixture")
    monkeypatch.setattr(agent, "recall", lambda query: {"hits": []})
    monkeypatch.setattr(agent, "_learn", lambda *args: None)
    jobs, advertised = [], []

    def job(name, inp, **kwargs):
        jobs.append((name, inp, kwargs))
        return {"state": "succeeded", "worker_id": "fixture-worker", "output": {"result": "fixture"}}

    monkeypatch.setattr(agent, "_job", job)
    calls = [("rea_tools", {"name": "binary_session"}), ("rea_binary_session", {}), ("rea_binary_session", {})]

    def completion(url, **kwargs):
        advertised.append({t["function"]["name"] for t in kwargs["json"]["tools"]})
        if calls:
            name, args = calls.pop(0)
            message = {"tool_calls": [{"id": str(len(advertised)), "function": {"name": name, "arguments": json.dumps(args)}}]}
        else:
            message = {"content": "done"}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    monkeypatch.setattr(httpx, "post", completion)
    agent.run([{"role": "user", "content": "inspect the fixture"}], lambda event: None, {"request_id": "711"}, max_steps=5)
    assert "rea_binary_session" not in advertised[0] and "rea_binary_session" in advertised[1]
    assert len(jobs) == 2 and all(name == "rea_binary_session" for name, _, _ in jobs)
    assert jobs[1][2]["worker"] == "fixture-worker"
    agent.run_tool("rea_binary_session", {}, node="linux")
    assert jobs[-1][2]["worker"] is None and jobs[-1][2]["node"] == "linux"
    agent.api.close()


def test_mcp_preserves_union_contract_and_routes_worker(monkeypatch):
    pytest.importorskip("mcp")
    import asyncio
    import httpx
    from mcp.client import Client
    from gbox.mcp_server import build
    info = REGISTRY["rea_project_managed_application_graph"].info().model_dump(mode="json")
    assert "anyOf" in info["input_schema"]
    submitted = []

    def handler(request):
        if request.url.path == "/api/registry":
            return httpx.Response(200, json={"tools": [info | {"workers": ["fixture-worker"]}]})
        if request.url.path == "/api/jobs":
            submitted.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "fixture-job", "state": "succeeded", "worker_id": "fixture-worker"})
        raise AssertionError(request.url)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: original(*args, **kwargs, transport=httpx.MockTransport(handler)))
    contract = next(t for t in rea_tool.CATALOG["tools"] if t["name"] == "project_managed_application_graph")
    arguments = contract["examples"][0]["input"]

    async def check():
        async with Client(build("http://fixture", "fixture")) as client:
            listed = await client.list_tools()
            exposed = next(t for t in listed.tools if t.name == "job_" + info["name"])
            assert exposed.input_schema["properties"]["input"] == info["input_schema"]
            result = await client.call_tool(exposed.name, {"input": arguments, "require_os": "windows", "require_worker": "fixture-worker", "parent_request_id": "711"})
            assert not result.is_error

    asyncio.run(check())
    assert submitted == [{"tool": info["name"], "input": arguments, "require_os": "windows", "require_worker": "fixture-worker", "parent_request_id": "711"}]


@pytest.fixture
def live_runtime():
    cfg = load()
    if reason := rea.unavailable(cfg):
        pytest.skip(reason)
    yield cfg
    rea.close_all()


def call(cfg, name, args):
    ctx = Ctx(cfg, worker="rea-test")
    output = execute("rea_" + name, args, ctx)
    errors = REGISTRY["rea_" + name].validate(rea_tool.Result.model_validate(output), {a[0]: a[1] for a in ctx.artifacts})
    assert not errors, (errors, output["result"].get("structuredContent"))
    return output, ctx


def test_live_catalog_matches_every_pinned_input(live_runtime):
    def semantics(value):
        if isinstance(value, dict):
            return {k: semantics(v) for k, v in value.items() if k not in ("$schema", "examples", "description", "title")}
        if isinstance(value, list):
            return [semantics(v) for v in value]
        return value
    remote = rea.session(live_runtime).request("tools/list")
    tools = remote["tools"]
    assert {t["name"] for t in tools} == {t["name"] for t in rea_tool.CATALOG["tools"]}
    for item in tools:
        schema = REGISTRY["rea_" + item["name"]].info().input_schema
        # SDK and canonical Zod export carry equivalent input contracts.
        assert semantics(item["inputSchema"]) == semantics(schema), item["name"]


def test_live_analysis_state_evidence_and_tamper_detection(live_runtime, tmp_path):
    source = tmp_path / "main.js"
    source.write_text("export function move(y) { return -y; }\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"rea-fixture","type":"module","main":"main.js"}')
    out, ctx = call(live_runtime, "analyze_javascript_application", {"input_path": str(tmp_path), "format": "auto"})
    assert out["worker_id"] == "rea-test"
    assert out["result"]["structuredContent"]["evidence"]["subject"]["digest"]["sha256"]
    artifact = ctx.artifacts[0][1]
    assert hashlib.sha256(artifact).hexdigest() == out["evidence_sha256"]
    corrupted = copy.deepcopy(out)
    corrupted["result"] = {}
    assert rea_tool.validate_result(rea_tool.Result.model_validate(corrupted), {"rea-result.json": artifact})
    call(live_runtime, "open_binary", {"path": str(source)})
    inspected, _ = call(live_runtime, "inspect_artifact", {})
    assert source.resolve() == Path(inspected["result"]["structuredContent"]["evidence"]["subject"]["local_path"]).resolve()
    bundle, _ = call(live_runtime, "get_evidence_bundle", {})
    assert bundle["result"]["structuredContent"]
    # An unsupported MCP method must not discard the open analysis target.
    with pytest.raises(rea.RpcError):
        rea.session(live_runtime).request("not/a/method", timeout=10)
    inspected_again, _ = call(live_runtime, "inspect_artifact", {})
    assert source.resolve() == Path(inspected_again["result"]["structuredContent"]["evidence"]["subject"]["local_path"]).resolve()


def test_live_missing_provider_is_invalid_with_preserved_evidence(live_runtime, tmp_path):
    # This upstream capability is explicitly Linux x64-only, even when Node works.
    import platform
    if platform.system() == "Linux" and platform.machine() == "x86_64":
        pytest.skip("This lane checks unsupported Windows/Linux arm64 recovery")
    source = tmp_path / "source.js"
    source.write_text("export const answer = 42;", encoding="utf-8")
    ctx = Ctx(live_runtime)
    out = execute("rea_recover_javascript_sources", {"path": str(source), "output_directory": str(tmp_path / "recovered")}, ctx)
    errors = rea_tool.validate_result(rea_tool.Result.model_validate(out), {a[0]: a[1] for a in ctx.artifacts})
    assert errors and out["result"]["isError"]
    assert "Linux x64" in json.dumps(out)
    assert ctx.artifacts and not (tmp_path / "recovered").exists()


def test_live_bundle_preserves_unknowns_across_restart(live_runtime, tmp_path):
    source = tmp_path / "main.js"
    source.write_text("export const answer = 42;", encoding="utf-8")
    call(live_runtime, "open_binary", {"path": str(source)})
    call(live_runtime, "inspect_artifact", {})
    contract = next(t for t in rea_tool.CATALOG["tools"] if t["name"] == "record_unknown")
    args = dict(contract["examples"][0]["input"], question="gBox integration unknown survives restart")
    call(live_runtime, "record_unknown", args)
    bundle = tmp_path / "evidence.json"
    call(live_runtime, "export_evidence_bundle", {"path": str(bundle)})
    assert bundle.is_file()
    rea.close_all()
    call(live_runtime, "import_evidence_bundle", {"path": str(bundle)})
    result, _ = call(live_runtime, "list_unknowns", {})
    assert args["question"] in json.dumps(result)


def test_live_native_decompilation_preserves_executable(live_runtime):
    import sys
    from gbox.provision import ghidra_home
    if sys.platform != "win32" or not ghidra_home(live_runtime):
        pytest.skip("Native PE lane requires Windows x64 and configured Ghidra")
    executable = Path(sys.executable)
    original = hashlib.sha256(executable.read_bytes()).hexdigest()
    call(live_runtime, "open_binary", {"path": str(executable), "provider_id": "ghidra"})
    listed, listing_ctx = call(live_runtime, "list_procedures", {})
    # Discovery may be excerpted inline; use the complete preserved evidence.
    procedures = json.loads(listing_ctx.artifacts[0][1])["result"]["structuredContent"]["result"]
    procedure = next(p for p in procedures if not p.get("procedure", {}).get("external") and not p.get("procedure", {}).get("thunk"))
    output, _ = call(live_runtime, "procedure_pseudo_code", {"procedure": procedure["address"]})
    assert len(json.dumps(output["result"]["structuredContent"]["result"])) > 100
    assert hashlib.sha256(executable.read_bytes()).hexdigest() == original


def test_live_process_comparison_and_reconstruction(live_runtime):
    import sys
    if sys.platform != "linux":
        pytest.skip("REA process capture is supported on Linux/macOS, not native Windows")
    args = {"executable": "/usr/bin/python3", "arguments": ["-c", "import time; print('gBox reconstruction fixture', flush=True); time.sleep(1)"], "working_directory": "/tmp",
            "normalization": {"paths": False, "pids": True, "ports": True, "time_bucket_ms": 10000, "patterns": []}}
    first, _ = call(live_runtime, "capture_process_scenario", args)
    second, _ = call(live_runtime, "capture_process_scenario", args)
    comparison, _ = call(live_runtime, "compare_process_captures", {
        "left": first["result"]["structuredContent"]["evidence"], "right": second["result"]["structuredContent"]["evidence"]})
    eid = comparison["result"]["structuredContent"]["evidence_id"]
    verified, _ = call(live_runtime, "verify_reconstruction", {"specification": {"name": "matching terminal behavior", "claims": [
        {"claim_id": "terminal", "title": "reconstruction prints identically", "comparison_evidence_id": eid, "kind": "behavioral", "dimension": "terminal"}]}})
    report = verified["result"]["structuredContent"]["result"]
    assert comparison["result"]["structuredContent"]["result"]["terminal"] == "unchanged"
    # Matching stdout is observed; REA correctly retains broader environment/
    # process unknowns rather than falsely proving reconstruction equivalence.
    assert report["status"] == "unknown"
    assert report["claims"]["items"][0]["observed_status"] == "unchanged"
    assert report["claims"]["items"][0]["unknown_ids"]
