"""One server request binds a query to the program that was actually imported."""
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from gbox import ghidra_bridge_server as server
from gbox import ghidra_bridge_tool as tool
from gbox.config import Config
from gbox.registry import ToolUnavailable

SHA_A, SHA_B = "a" * 64, "b" * 64


def program(path, digest):
    return SimpleNamespace(getExecutablePath=lambda: str(path), getExecutableSHA256=lambda: digest,
        getExecutableMD5=lambda: "m" * 32, getName=lambda: "game.elf", getLanguageID=lambda: "PowerPC:BE:32:default",
        getCompilerSpec=lambda: SimpleNamespace(getCompilerSpecID=lambda: "default"), getImageBase=lambda: "80000000",
        getFunctionManager=lambda: SimpleNamespace(getFunctionCount=lambda: 0))


class RecordingBridge(server.Bridge):
    def __init__(self):
        super().__init__()
        self.calls = []

    def open(self, binary_path, sha256=SHA_A, **kwargs):
        self.program = program(binary_path, sha256)
        return {"executable_path": binary_path, "executable_sha256": sha256}

    def functions(self, **kwargs):
        self.calls.append(self.program.getExecutablePath())
        return {"functions": [], "executed_path": self.program.getExecutablePath()}


def guard(path, digest=SHA_A):
    return {"expected_binary_path": str(path), "expected_sha256": digest}


def protocol(bridge, requests):
    stdout = io.StringIO()
    server.serve(bridge, io.StringIO("\n".join(json.dumps(request) for request in requests)), stdout)
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_open_a_then_b_refuses_a_query_before_method_without_reopening(tmp_path):
    a, b = tmp_path / "first" / "game.elf", tmp_path / "second" / "game.elf"
    bridge = RecordingBridge()
    replies = protocol(bridge, [
        {"id": 1, "op": "open", "args": {"binary_path": str(a)}},
        {"id": 2, "op": "open", "args": {"binary_path": str(b), "sha256": SHA_B}},
        {"id": 3, "op": "guarded", "args": {"operation": "functions", "query": "player", **guard(a)}},
        {"id": 4, "op": "guarded", "args": {"operation": "functions", **guard(b, SHA_B)}},
    ])
    assert "target changed" in replies[2]["error"]
    assert replies[3]["result"]["executed_path"] == str(b)
    assert bridge.calls == [str(b)] and bridge.program.getExecutablePath() == str(b)


@pytest.mark.parametrize("operation", sorted(server.GUARDED_OPS))
def test_every_guarded_operation_checks_target_before_calling_method(tmp_path, operation):
    bridge = RecordingBridge()
    bridge.program = program(tmp_path / "other.elf", SHA_B)
    calls = []
    setattr(bridge, operation, lambda **kwargs: calls.append(kwargs) or {"ok": True})
    with pytest.raises(RuntimeError, match="target changed"):
        bridge.dispatch(operation, guard(tmp_path / "expected.elf"))
    assert not calls


def test_loaded_program_sha_is_checked_even_if_disk_path_now_contains_expected_bytes(tmp_path):
    source = tmp_path / "game.elf"
    source.write_bytes(b"new file revision")
    bridge = RecordingBridge()
    bridge.program = program(source, hashlib.sha256(b"older imported revision").hexdigest())
    with pytest.raises(RuntimeError, match="SHA-256 differs"):
        bridge.dispatch("functions", guard(source, hashlib.sha256(source.read_bytes()).hexdigest()))
    assert not bridge.calls


def test_missing_import_sha_fails_closed_and_info_reports_it(tmp_path):
    bridge = RecordingBridge()
    bridge.program = program(tmp_path / "game.elf", None)
    assert bridge.info()["executable_sha256"] is None
    with pytest.raises(RuntimeError, match="unavailable"):
        bridge.dispatch("functions", guard(tmp_path / "game.elf"))
    assert not bridge.calls


def test_exact_query_accepts_equivalent_lexical_path_and_uppercase_digest(tmp_path):
    bridge = RecordingBridge()
    path = tmp_path / "game.elf"
    bridge.program = program(path, SHA_A)
    expected = tmp_path / "directory" / ".." / "game.elf"
    assert bridge.dispatch("functions", guard(expected, SHA_A.upper()))["executed_path"] == str(path)


@pytest.mark.parametrize("params", [
    {"expected_binary_path": "relative/game.elf", "expected_sha256": SHA_A},
    {"expected_binary_path": "file://host/game.elf", "expected_sha256": SHA_A},
    {"expected_binary_path": "bad\npath", "expected_sha256": SHA_A},
    {"expected_binary_path": "x" * 4097, "expected_sha256": SHA_A},
    {"expected_sha256": SHA_A}, {"expected_binary_path": "missing-hash"},
])
def test_malformed_protocol_guards_do_not_reach_query(tmp_path, params):
    bridge = RecordingBridge()
    bridge.program = program(tmp_path / "game.elf", SHA_A)
    with pytest.raises(ValueError):
        bridge.dispatch("functions", params)
    assert not bridge.calls


def test_target_guard_is_not_silently_ignored_on_open(tmp_path):
    bridge = RecordingBridge()
    a, b = tmp_path / "a.elf", tmp_path / "b.elf"
    bridge.program = program(a, SHA_A)
    with pytest.raises(ValueError, match="lifecycle"):
        bridge.dispatch("open", {"binary_path": str(b), **guard(a)})
    assert bridge.program.getExecutablePath() == str(a)


def test_unguarded_existing_queries_remain_backwards_compatible(tmp_path):
    bridge = RecordingBridge()
    bridge.program = program(tmp_path / "game.elf", None)
    assert bridge.dispatch("functions", {"query": "player"})["executed_path"].endswith("game.elf")


def test_dispatch_holds_target_and_query_under_one_lock(tmp_path):
    bridge = RecordingBridge()
    a, b = tmp_path / "a.elf", tmp_path / "b.elf"
    bridge.program = program(a, SHA_A)
    entered, release, open_attempted, opened = (threading.Event() for _ in range(4))
    result = []
    def functions(**kwargs):
        entered.set()
        assert release.wait(3)
        return {"executed_path": bridge.program.getExecutablePath()}
    bridge.functions = functions
    query = threading.Thread(target=lambda: result.append(bridge.dispatch("functions", guard(a))))
    def replace():
        open_attempted.set()
        bridge.dispatch("open", {"binary_path": str(b), "sha256": SHA_B})
        opened.set()
    query.start()
    assert entered.wait(1)
    replacement = threading.Thread(target=replace)
    replacement.start()
    try:
        assert open_attempted.wait(1)
        assert not opened.wait(0.05)
        assert bridge.program.getExecutablePath() == str(a)
    finally:
        release.set()
        query.join(3)
        replacement.join(3)
    assert result == [{"executed_path": str(a)}] and opened.is_set()


@pytest.mark.parametrize("operation", sorted(tool.QUERY_OPS | {"run_script", "export"}))
def test_worker_propagates_pins_inside_the_actual_operation(tmp_path, operation):
    calls = []
    def request(op, args=None, **kwargs):
        calls.append((op, args))
        return {"ok": True}
    session = SimpleNamespace(opened={"program": {}}, running=lambda: True, request=request)
    path = tmp_path / "game.elf"
    inp = tool.GhidraBridgeIn(op=operation, target="0x80000000", script="script.java", export_dir=str(tmp_path), **guard(path))
    out = tool.run(inp, Config(data_dir=tmp_path), worker="analysis-worker", sess=session)
    assert out["source"] == "live" and out["worker_id"] == "analysis-worker"
    assert len(calls) == 1 and calls[0][0] == "guarded"
    assert calls[0][1]["operation"] == operation
    assert calls[0][1]["expected_binary_path"] == str(path) and calls[0][1]["expected_sha256"] == SHA_A


def test_closed_guarded_query_does_not_start_or_use_export_fallback(tmp_path):
    session = SimpleNamespace(opened=None, running=lambda: False,
                              request=lambda *args, **kwargs: pytest.fail("Unexpected bridge start/request"))
    inp = tool.GhidraBridgeIn(op="functions", export_dir=str(tmp_path), **guard(tmp_path / "game.elf"))
    with pytest.raises(ToolUnavailable, match="no longer open"):
        tool.run(inp, Config(data_dir=tmp_path), sess=session)


@pytest.mark.parametrize("kwargs", [{"expected_binary_path": "somewhere"}, {"expected_sha256": SHA_A},
                                      {"expected_binary_path": "somewhere", "expected_sha256": "bad"}])
def test_tool_schema_requires_complete_paired_target_guards(kwargs):
    with pytest.raises(ValueError):
        tool.GhidraBridgeIn(op="functions", **kwargs)


def test_wrapped_operation_checks_before_query_and_rejects_missing_guard(tmp_path):
    bridge = RecordingBridge()
    path = tmp_path / "game.elf"
    bridge.program = program(path, SHA_A)
    assert bridge.dispatch("guarded", {"operation": "functions", **guard(path)})["executed_path"] == str(path)
    with pytest.raises(ValueError):
        bridge.dispatch("guarded", {"operation": "functions"})
    assert bridge.calls == [str(path)]


def test_old_server_rejects_guarded_script_before_ignoring_target_kwargs(tmp_path):
    executed = []
    def old_request(op, args=None, **kwargs):
        # The old dispatcher checks the verb before calling a permissive
        # run_script(**kwargs) implementation.
        if op not in {"open", "close", "info", "functions", "run_script"}:
            raise RuntimeError("unknown op")
        executed.append(op)
        return {"stdout": "wrong program"}
    session = SimpleNamespace(opened={"program": {}}, running=lambda: True, request=old_request)
    inp = tool.GhidraBridgeIn(op="run_script", script="script.java", **guard(tmp_path / "game.elf"))
    with pytest.raises(RuntimeError, match="unknown op"):
        tool.run(inp, Config(data_dir=tmp_path), sess=session)
    assert not executed
