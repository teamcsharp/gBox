"""REA as a gBox tool, exercised against a stand-in MCP server.

The client's real job is the stdio protocol: one JSON-RPC line in, one line back, replies matched by id, notifications
and log noise skipped. A tiny Python server that speaks exactly that pins it without needing REA or a target.
"""
import json
import pathlib
import sys

import pytest

from gbox import rea as R

SERVER = '''
import json, sys

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    message = json.loads(line)
    method = message.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {
            "protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
            "serverInfo": {"name": "rea", "version": "6.8.0"}}})
    elif method == "notifications/initialized":
        continue
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": message["id"], "result": {"tools": [
            {"name": "binary_session", "description": "Open a binary target"},
            {"name": "analyze", "description": "Get an overview of an app"},
            {"name": "close_binary", "description": "Close the open target"}]}})
    elif method == "tools/call":
        name = (message.get("params") or {}).get("name")
        if name == "boom":
            send({"jsonrpc": "2.0", "id": message["id"], "error": {"message": "provider_timeout"}})
        else:
            send({"jsonrpc": "2.0", "id": message["id"], "result": {
                "content": [{"type": "text", "text": "called " + str(name)}]}})
    else:
        send({"jsonrpc": "2.0", "id": message.get("id"), "error": {"message": "unknown method"}})
'''


@pytest.fixture
def server(tmp_path, monkeypatch):
    script = tmp_path / "fake_rea.py"
    script.write_text(SERVER, encoding="utf-8")
    monkeypatch.setenv("GBOX_REA_COMMAND", f"{sys.executable} {script}")
    client = R.Rea()
    yield client
    client.close()


def test_available_names_the_command_and_where_it_lives(monkeypatch):
    monkeypatch.delenv("GBOX_REA_COMMAND", raising=False)
    state = R.available()
    assert "installed" in state and state["dir"].endswith("rea")
    assert "npm install rea-agents" in state["note"]


def test_start_reports_the_server_identity(server):
    info = server.start()
    assert info["name"] == "rea" and info["version"] == "6.8.0"


def test_list_tools_reads_the_catalog_and_find_searches_it(server):
    names = [tool["name"] for tool in server.list_tools()]
    assert names == ["binary_session", "analyze", "close_binary"]
    assert [tool["name"] for tool in server.find("binary")] == ["binary_session", "close_binary"]
    assert server.find("overview")[0]["name"] == "analyze"


def test_call_returns_the_result_and_text_flattens_it(server):
    result = server.call("analyze", {"path": "/tmp/x"})
    assert result["content"][0]["text"] == "called analyze"
    assert server.text("binary_session") == "called binary_session"


def test_a_refused_call_surfaces_reas_own_error(server):
    with pytest.raises(R.ReaError, match="provider_timeout"):
        server.call("boom")


def test_starting_twice_reuses_one_server_process(server):
    first = server.start()
    process = server.process
    second = server.start()
    assert second == first and server.process is process


def test_a_missing_install_is_named_not_guessed(tmp_path, monkeypatch):
    monkeypatch.setenv("GBOX_REA", str(tmp_path / "nowhere"))
    monkeypatch.delenv("GBOX_REA_COMMAND", raising=False)
    monkeypatch.setattr(R.shutil, "which", lambda name: None)
    assert R.command() is None
    with pytest.raises(R.ReaError, match="not installed"):
        R.Rea().list_tools()
