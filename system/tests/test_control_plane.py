"""Phase 0 exit criterion: a typed tool executes on a remote worker and yields a validated artifact + receipt."""
import hashlib
import sqlite3

import httpx

from conftest import make_cube, run_job


def test_dummy_tool_remote_receipt(plane):
    job = run_job(plane, "echo_artifact", {"message": "hello g-box"})
    assert job["state"] == "succeeded", job
    r = plane.get(f"/api/receipts/{job['receipt_id']}").json()
    assert r["validation_ok"] and r["worker_id"] == job["worker_id"]
    art = r["artifacts"][0]
    data = plane.get(f"/api/artifacts/{art['sha256']}").content
    assert data == b"hello g-box" and hashlib.sha256(data).hexdigest() == art["sha256"]
    assert art["provenance"]["tool"] == "echo_artifact" and art["provenance"]["job"] == job["id"]
    assert plane.get("/api/audit/verify").json()["ok"]


def test_auth_required(plane):
    assert httpx.get(str(plane.base_url) + "/api/jobs").status_code == 401


def test_input_typed(plane):
    assert plane.post("/api/jobs", json={"tool": "echo_artifact", "input": {"msg": 1}}).status_code == 422
    assert plane.post("/api/jobs", json={"tool": "nope", "input": {}}).status_code == 404


def test_mutation_requires_permission(plane):
    job = plane.post("/api/jobs", json={"tool": "write_memory",
                                        "input": {"session_id": "w-1", "address": 0, "hex_bytes": "00"}}).json()
    assert job["state"] == "rejected" and "memory_write" in job["error"]


def test_unavailable_tool_never_claimed(monkeypatch, request):
    from gbox import provision
    monkeypatch.setattr(provision, 'find_blender', lambda config: None)
    plane = request.getfixturevalue('plane')
    # This test owns its missing-program condition, independent of host tools.
    t = next(t for t in plane.get("/api/tools").json() if t["name"] == "open_in_blender")
    assert t["workers"] == [] and "blender_path" in t["unavailable"]["test-worker"]


def test_failure_explicit(plane):
    job = run_job(plane, "launch_game", {"game": {"game_id": "x", "title": "x", "platform": "dreamcast",
                                                  "source_paths": ["x"], "format": "gdi", "profile_id": "x",
                                                  "launch": {"kind": "emulator", "path": "x"}}})
    assert job["state"] == "failed" and "no runtime for platform 'dreamcast'" in job["error"]


def test_audit_tamper_detected(plane, cfg):
    run_job(plane, "echo_artifact", {"message": "x"})
    db = sqlite3.connect(cfg.data_dir / "gbox.sqlite3")
    try:
        db.execute("UPDATE audit SET actor='evil' WHERE seq=1")
        raise AssertionError("append-only trigger did not fire")
    except sqlite3.DatabaseError:
        pass
    db.execute("DROP TRIGGER audit_no_update")
    db.execute("UPDATE audit SET actor='evil' WHERE seq=1")
    db.commit()
    v = plane.get("/api/audit/verify").json()
    assert not v["ok"] and v["first_bad_seq"] == "1"


def test_export_asset_end_to_end(plane, tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(make_cube().model_dump_json())
    job = run_job(plane, "export_asset", {"package_dir": str(pkg)})
    assert job["state"] == "succeeded", job
    assert set(job["output"]["exported"]) == {"gltf", "obj"}


def test_knowledge_requires_evidence(plane):
    e = {"game_id": "g", "src": "player", "rel": "hp_at", "dst": "0x8c000000", "source": "test", "status": "validated"}
    assert plane.post("/api/knowledge", json=e).status_code == 422
    job = run_job(plane, "echo_artifact", {"message": "evidence"})
    ev = job["output"]["sha256"]
    assert plane.post("/api/knowledge", json=e | {"evidence": [ev]}).status_code == 200
    assert plane.post("/api/knowledge", json=e | {"status": "hypothesis"}).status_code == 200


def test_run_needs_independent_evaluator(plane):
    r = plane.post("/api/runs", json={"game_id": "g", "objective": "clear forest 1", "policy_version": "p1",
                                      "proposer": "autoplay", "evaluation": {"passed": True}}).json()
    assert r["evaluation"] is None
    bad = {"evaluator": "autoplay", "passed": True}
    assert plane.post(f"/api/runs/{r['id']}/evaluation", json=bad).status_code == 422
    ok = plane.post(f"/api/runs/{r['id']}/evaluation", json=bad | {"evaluator": "validator"}).json()
    assert ok["evaluation"]["passed"]
    assert plane.get("/api/metrics").json()["runs_evaluated"] == 1


# A worker that lies about its output must not get credit (plan §2.3).
from gbox.registry import tool as _tool
from gbox.tools import EchoIn, EchoOut, _echo_validate


@_tool("lying_echo", "0", EchoIn, EchoOut, validate=_echo_validate)
def _lying(inp, ctx):
    ctx.artifact("echo.txt", b"something else")
    return {"sha256": "0" * 64, "length": 3, "host_os": "x"}


def test_lying_worker_marked_invalid(plane):
    job = run_job(plane, "lying_echo", {"message": "hi"})
    assert job["state"] == "invalid"
    r = plane.get(f"/api/receipts/{job['receipt_id']}").json()
    assert not r["validation_ok"] and r["validation_problems"]
