"""The game-hooked console: emulator log tailing, session transitions and freeze reports."""
import json
import time

from gbox.harness_console import HarnessConsole


class Store:
    def __init__(self, rows):
        self.rows = rows

    def get(self, kind, key):
        return self.rows.get((kind, key))


class Config:
    def __init__(self, root):
        self.data_dir = root


def make(tmp_path, log_text="", **detail):
    log = tmp_path / "eden.log"
    log.write_text(log_text, encoding="utf-8")
    sid = "spark-1"
    row = {"session_id": sid, "game_id": "52d15709be0fda1a", "title": "Resident Evil 5", "state": "running",
           "mod": "harness-test", "adapter": "eden", "validation": "guest memory mapped",
           "detail": {"log": str(log), "overlay": {"build": "harness-test", "selection": "applied", "files": 1},
                      "autoplay_job": "job-1"} | detail}
    service = HarnessConsole(Store({("session", sid): row}), Config(tmp_path))
    return service, sid, log, row


def test_the_console_tails_the_emulator_log_from_the_current_end(tmp_path):
    service, sid, log, _ = make(tmp_path, "old line\n[   1.000] boot ok\n")
    first = service.tail(sid, 0)
    assert first["seq"] >= 1
    assert any("boot ok" in line["text"] and line["source"] == "game" for line in first["lines"])
    before = first["seq"]
    log.write_text(log.read_text() + "[   9.000] NOW LOADING\n", encoding="utf-8")
    time.sleep(0.01)
    more = service.tail(sid, before)
    assert more["seq"] > before
    assert any("NOW LOADING" in line["text"] for line in more["lines"])
    assert not any("boot ok" in line["text"] for line in more["lines"]), "already-seen lines are not repeated"


def test_a_session_transition_is_one_line_not_a_poll_storm(tmp_path):
    service, sid, _, _ = make(tmp_path)
    first = service.tail(sid, 0)
    runtime = [line for line in first["lines"] if line["source"] == "runtime"]
    assert any("build:" in line["text"] for line in runtime)
    after = first["seq"]
    second = service.tail(sid, after)
    assert [line for line in second["lines"] if line["source"] == "runtime"] == [], "an unchanged state is not repeated"


def test_an_autoplay_failure_is_named_in_the_console(tmp_path):
    service, sid, _, row = make(tmp_path)
    service.store.rows[("job", "job-1")] = {"id": "job-1", "state": "failed", "error": "xdotool keydown c"}
    first = service.tail(sid, 0)
    assert any("autoplay job job-1: failed" in line["text"] and "xdotool" in line["text"] for line in first["lines"])


def test_a_freeze_report_is_written_beside_the_console_and_keeps_the_witness(tmp_path):
    service, sid, _, _ = make(tmp_path, "boot\n")
    service.collect(sid)
    out = service.write_freeze(sid, {"frame_sha": "abc", "unchanged_s": 14, "screen": "playing", "timer": 119.5})
    path = tmp_path / "harness" / out["report"].split("/")[-1]
    assert path.is_file()
    saved = json.loads(path.read_text())
    assert saved["witness"]["frame_sha"] == "abc"
    assert saved["witness"]["unchanged_s"] == 14
    assert saved["session"]["session_id"] == sid
    assert saved["console"], "the report keeps the console tail"
    assert service.freeze_state(sid)["count"] == 1


def test_probe_returns_the_session_overlay_and_log_tail(tmp_path):
    service, sid, _, _ = make(tmp_path, "last line before probe\n")
    out = service.probe(sid)
    assert out["session"]["mod"] == "harness-test"
    assert out["session"]["overlay"]["build"] == "harness-test"
    assert "last line before probe" in out["emulator_log_tail"]


def test_the_ghidra_hook_resolves_the_analyzed_switch_main(tmp_path):
    from gbox.harness_console import _title_elf
    elf = tmp_path / "analysis" / "switch" / "re5" / "re5_switch_main_EBFFDB22.elf"
    elf.parent.mkdir(parents=True)
    elf.write_bytes(b"ELF")
    assert _title_elf(Config(tmp_path), {"game_id": "52d15709be0fda1a"}) == elf
    assert _title_elf(Config(tmp_path), {"detail": {}}) is None
    assert _title_elf(Config(tmp_path), {"game_id": "270a15eb98dab4d7"}) != elf
    assert _title_elf(Config(tmp_path), {"game_id": "115f9cdbba115432"}) != elf


def test_re4_hook_uses_its_extracted_elf_and_refuses_conflicting_identity(tmp_path):
    from gbox.harness_console import _title_elf
    elf = tmp_path / "cache/exefs/010099A00BC1E000/main.elf"
    elf.parent.mkdir(parents=True)
    elf.write_bytes(b"ELF")
    assert _title_elf(Config(tmp_path), {"game_id": "270a15eb98dab4d7"}) == elf
    assert _title_elf(Config(tmp_path), {"game_id": "52d15709be0fda1a",
                                       "title_id": "010099A00BC1E000"}) is None


def test_the_routes_are_installed_on_the_app(tmp_path):
    from fastapi import FastAPI
    from gbox.harness_console import install
    service, sid, _, _ = make(tmp_path)
    app = FastAPI()
    install(app, service.store, Config(tmp_path), lambda: "test")
    paths = {route.path for route in app.routes}
    assert "/api/sessions/{sid}/harness/console" in paths
    assert "/api/sessions/{sid}/harness/probe" in paths
    assert "/api/sessions/{sid}/harness/freeze" in paths
    assert "/api/sessions/{sid}/harness/ghidra" in paths
    assert "/api/harness/ghidra" in paths


def test_the_ghidra_hook_route_submits_open_on_the_session_worker(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from gbox.harness_console import install
    service, sid, _, _ = make(tmp_path)
    elf = tmp_path / "analysis" / "switch" / "re5" / "re5_switch_main_EBFFDB22.elf"
    elf.parent.mkdir(parents=True)
    elf.write_bytes(b"ELF")
    calls = []

    def submit(tool, inp, worker):
        calls.append((tool, inp, worker))
        return {"id": "job-ghidra", "state": "queued"}

    app = FastAPI()
    install(app, service.store, Config(tmp_path), lambda: "test", submit_job=submit)
    client = TestClient(app)
    answer = client.post(f"/api/sessions/{sid}/harness/ghidra", json={"op": "open"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["job"]["id"] == "job-ghidra"
    assert calls and calls[0][0] == "ghidra_bridge"
    assert calls[0][1]["op"] == "open"
    assert calls[0][1]["binary_path"] == str(elf)
    answer = client.post(f"/api/sessions/{sid}/harness/ghidra", json={"op": "decompile", "target": "0x1000"})
    assert answer.status_code == 200
    import hashlib
    assert calls[-1][1]["expected_binary_path"] == str(elf)
    assert calls[-1][1]["expected_sha256"] == hashlib.sha256(b"ELF").hexdigest()


def test_a_session_that_does_not_exist_is_a_404_not_an_empty_console(tmp_path):
    service, _, _, _ = make(tmp_path)
    try:
        service.tail("missing", 0)
    except Exception as exc:                       # HTTPException from the route contract
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("a missing session must be refused")
