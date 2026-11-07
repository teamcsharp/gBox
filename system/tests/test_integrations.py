"""The integrations box: registry, recipes, and calls through one generic MCP client.

Exercised against a stand-in server, because the registry's job is bookkeeping (what is registered, what starts it) and
the client's job is the protocol - neither needs a real target.
"""
import json
import pathlib
import sys

import pytest

from gbox import integrations as G
from gbox.mcp_stdio import McpError, McpServer, split_command

SERVER = '''
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
            "serverInfo": {"name": "stub", "version": "1.2.3"}}}), flush=True)
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [
            {"name": "echo", "description": "say it back"},
            {"name": "explode", "description": "always fails"}]}}), flush=True)
    elif method == "tools/call":
        name = (message.get("params") or {}).get("name")
        if name == "explode":
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "error": {"message": "boom"}}), flush=True)
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": {
                "content": [{"type": "text", "text": "echo:" + json.dumps((message.get("params") or {}).get("arguments") or {})}]}}), flush=True)
'''


@pytest.fixture
def stub(tmp_path, monkeypatch):
    script = tmp_path / "stub_mcp.py"
    script.write_text(SERVER, encoding="utf-8")
    registry = tmp_path / "integrations.json"
    monkeypatch.setenv("GBOX_INTEGRATIONS", str(registry))
    yield {"command": f"{sys.executable} {script}", "registry": registry, "tmp": tmp_path}
    G.close_all()


def test_split_command_accepts_one_registry_line():
    assert split_command("npx -y @playwright/mcp --browser chromium") == ["npx", "-y", "@playwright/mcp",
                                                                        "--browser", "chromium"]


def test_add_load_remove_round_trip(stub):
    entry = G.add("stub", stub["command"], source="test", note="a stand-in")
    assert entry["name"] == "stub" and entry["enabled"] is True
    assert G.load()["stub"]["command"] == stub["command"]
    assert json.loads(stub["registry"].read_text())["integrations"]["stub"]["note"] == "a stand-in"
    assert G.remove("stub") is True and G.load() == {}
    assert G.remove("stub") is False


def test_an_integration_without_a_name_or_command_is_refused(stub):
    with pytest.raises(ValueError, match="needs a name and a command"):
        G.add("", stub["command"])
    with pytest.raises(ValueError, match="needs a name and a command"):
        G.add("stub", "   ")


def test_the_catalogue_probes_what_is_registered(stub):
    G.add("stub", stub["command"])
    rows = G.catalogue(probe=True)
    assert len(rows) == 1 and rows[0]["ok"] is True
    assert rows[0]["tools"] == 2 and rows[0]["server"]["name"] == "stub"


def test_a_broken_integration_is_reported_not_raised(stub):
    G.add("broken", "/nonexistent/binary --mcp")
    rows = G.catalogue(probe=True)
    assert rows[0]["ok"] is False and "could not be started" in rows[0]["error"]


def test_calls_go_through_the_shared_client(stub):
    G.add("stub", stub["command"])
    client = G.client("stub")
    assert client.text("echo", {"hello": "world"}) == 'echo:{"hello": "world"}'
    assert G.client("stub") is client                      # one process per integration, not one per call
    with pytest.raises(McpError, match="boom"):
        client.call("explode")


def test_a_disabled_or_unknown_integration_is_named(stub):
    G.add("off", stub["command"], enabled=False)
    with pytest.raises(McpError, match="disabled"):
        G.client("off")
    with pytest.raises(McpError, match="no such integration"):
        G.client("nothing")


def test_recipe_matching_covers_the_known_repositories():
    assert G.recipe_for("https://github.com/morluto/rea")["name"] == "rea"
    assert G.recipe_for("git@github.com:morluto/rea.git")["name"] == "rea"
    assert G.recipe_for("https://example.com/something-else") is None


def test_installing_from_a_repo_is_a_dry_run_by_default(stub):
    out = G.install_from_repo("https://github.com/morluto/rea")
    assert out["ok"] and out["dry_run"] and out["would_register"]["name"] == "rea"
    assert G.load() == {}                                  # nothing registered without being asked
    unknown = G.install_from_repo("https://example.com/nope")
    assert unknown["ok"] is False and "no recipe" in unknown["reason"]
