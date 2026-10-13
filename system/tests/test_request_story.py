"""GET /api/requests/{id}/story: the Detailed report's resolution story, assembled from real records only.

A synthetic ticket gets a dispatch step, a resolution chat with tool calls, a Hermes run with its final per-model
usage record (the hermes_accounting marker), a job, a published PR and the reconciler's merge notice; a local git
repository holds the merge commit. The story must carry those values in order, estimate cost only with a basis, and
leave everything unrecorded as null with a reason.
"""
import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from gbox import request_story
from gbox.server import create_app

RUN = "a" * 32
RUN2 = "b" * 32


def client_for(cfg):
    app = create_app(cfg)
    return app, TestClient(app, headers={"Authorization": "Bearer " + cfg.token()})


@pytest.fixture
def no_hermes(monkeypatch):
    monkeypatch.setattr(request_story, "hermes_runs_for", lambda rid: [])
    monkeypatch.setattr(request_story, "workspace_for", lambda rid: None)
    monkeypatch.setattr(request_story, "local_diff", lambda spec: None)


def git_repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git is not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (repo / "system" / "gbox").mkdir(parents=True)
    (repo / "system" / "gbox" / "a.py").write_text("def one():\n    return 1\n\n\ndef two():\n    return 2\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    base = run("rev-parse", "HEAD")
    (repo / "system" / "gbox" / "a.py").write_text("def one():\n    return 10\n\n\ndef two():\n    return 2\n    # done\n")
    (repo / "system" / "tests").mkdir()
    (repo / "system" / "tests" / "test_a.py").write_text("def test_one():\n    assert True\n")
    run("add", "-A")
    run("commit", "-q", "-m", "fix")
    return repo, base, run("rev-parse", "HEAD")


def test_parse_diff_counts_lines_and_hunks_per_file():
    text = ("diff --git a/system/gbox/a.py b/system/gbox/a.py\n--- a/system/gbox/a.py\n+++ b/system/gbox/a.py\n"
            "@@ -2 +2 @@ def one():\n-    return 1\n+    return 10\n@@ -6,0 +7 @@ def two():\n+    # done\n"
            "diff --git a/img.png b/img.png\nBinary files a/img.png and b/img.png differ\n")
    files = request_story.parse_diff(text)
    assert [f["path"] for f in files] == ["system/gbox/a.py", "img.png"]
    a = files[0]
    assert (a["added"], a["deleted"], a["folder"], a["hunks_total"]) == (2, 1, "system/gbox", 2)
    assert a["hunks"][0] == {"old": 2, "new": 2, "added": 1, "deleted": 1, "context": "def one():"}
    assert a["hunks"][1]["context"] == "def two():"
    assert files[1]["binary"] and files[1]["added"] is None and files[1]["deleted"] is None
    assert request_story.group_folders(files) == [{"path": "", "files": 1, "added": None, "deleted": None},
                                                   {"path": "system/gbox", "files": 1, "added": 2, "deleted": 1}]


def test_local_diff_reads_a_merge_commit_and_a_range_from_local_git(tmp_path):
    repo, base, head = git_repo(tmp_path)
    by_commit = request_story.local_diff({"commit": head[:12]}, repos=[repo])
    assert by_commit["source"] == "local git"
    files = {f["path"]: f for f in by_commit["files"]}
    assert files["system/gbox/a.py"]["added"] == 2 and files["system/gbox/a.py"]["deleted"] == 1
    assert files["system/tests/test_a.py"]["added"] == 2
    by_range = request_story.local_diff({"base": base, "head": head}, repos=[repo])
    assert {f["path"] for f in by_range["files"]} == set(files)
    assert request_story.local_diff({"commit": "0123456789ab"}, repos=[repo]) is None, "an unknown commit is not invented"


def test_cost_uses_the_ledger_first_then_the_price_table_and_never_guesses():
    prices = request_story.DEFAULT_PRICES | {"zai/glm-5.3": {"in": 1.0, "out": 4.0, "cache_read": 0.5}}
    assert request_story.cost_of(prices, "zai", "glm-5.3", 10, 10, actual=0.5)["kind"] == "actual"
    assert request_story.cost_of(prices, "zai", "glm-5.3", 10, 10, estimated=0.25) == {
        "usd": 0.25, "kind": "estimate", "basis": "provider ledger estimate"}
    c = request_story.cost_of(prices, "zai", "glm-5.3", 1_000_000, 500_000, cache_read=400_000)
    assert c["kind"] == "estimate" and c["usd"] == pytest.approx(0.6 + 0.2 + 2.0)
    assert "zai/glm-5.3" in c["basis"]
    unknown = request_story.cost_of(prices, "nous", "hermes-4", 10, 10)
    assert unknown["usd"] is None and unknown["kind"] == "unknown" and "nous/hermes-4" in unknown["basis"]
    assert request_story.cost_of(prices, "zai", None, None, 5)["usd"] is None


def test_story_endpoint_assembles_triage_steps_runs_usage_jobs_changes_and_resolution(cfg, tmp_path, monkeypatch):
    repo, base, head = git_repo(tmp_path)
    app, client = client_for(cfg)
    store = app.state.store
    r = client.post("/api/requests", json={"title": "Fix the menu", "body": "The menu is broken"}).json()
    rid = r["id"]
    t0 = time.time() - 1000            # the synthetic history happened before anything this test posts live
    doc = store.get("request", rid)
    doc["created"] = t0
    doc["messages"][0]["ts"] = t0
    doc["messages"].append({"author": "agent", "text": "Resolution agent dispatched (chat chat1).", "ts": t0 + 3, "attachments": [],
                            "task_step": {"action": "dispatch resolution", "attempt": "1", "result": "chat1", "status": "running"}})
    store.put("request", rid, doc)
    # a resolution chat with two tool calls
    store.put("chat", "chat1", {"id": "chat1", "model": "qwen3.6:35b", "created": t0 + 5, "busy": False, "events": [
        {"type": "user", "text": "go", "ts": t0 + 5},
        {"type": "tool_call", "name": "get_frame", "args": {"session_id": "s1"}, "ts": t0 + 6},
        {"type": "tool_result", "name": "get_frame", "text": '{"sha256": "abc"}', "ts": t0 + 8},
        {"type": "tool_call", "name": "pytest", "args": {"file": "tests/test_a.py"}, "ts": t0 + 9},
        {"type": "error", "text": "boom", "ts": t0 + 12}]})
    doc = store.get("request", rid)
    doc["context"]["resolution_chat_id"] = "chat1"
    store.put("request", rid, doc)
    client.post(f"/api/requests/{rid}/status", json={"status": "in_progress"})
    # Hermes: an exact final model record, as hermes_accounting writes it, plus the local agent's untagged usage
    record = {"run_id": RUN, "session_id": "s", "provider": "zai", "model": "glm-5.3", "task": "primary",
              "tokens_in_including_caches": 120_000, "input_cache_read": 100_000, "tokens_out": 3_000,
              "api_call_count": 7, "inference_session_duration_s": 300.0, "actual_cost_usd": None,
              "estimated_cost_usd": None, "cost_status": "estimate only; no measured bill"}
    marker = f"hermes_run_{RUN}_model_{'c' * 20}_final_recorded"
    client.post(f"/api/requests/{rid}/metrics", json={"provider": "zai", "model": "glm-5.3", "system": "Hermes",
                "tokens_in": 120_000, "tokens_out": 3_000, "tokens_detail": {marker: 1, marker + "_usage": record}, "turns": 0})
    client.post(f"/api/requests/{rid}/metrics", json={"tokens_in": 900, "tokens_out": 40, "tools": {"get_frame": 1}, "duration_s": 7})
    store.put("job", "j1", {"id": "j1", "tool": "launch_game", "state": "succeeded", "parent_request_id": rid,
                            "input": {"game_id": "g"}, "created": t0 + 20, "started": t0 + 21, "finished": t0 + 31})
    store.put("job", "j2", {"id": "j2", "tool": "other", "state": "succeeded", "input": {}, "created": t0})
    client.post(f"/api/requests/{rid}/messages", json={"author": "agent",
                "text": "Published tested task changes: https://github.com/teamcsharp/gBox/pull/77"})
    client.post(f"/api/requests/{rid}/messages", json={"author": "agent",
                "text": f"PR #77 merged to main as {head[:12]} at 2026-10-01 12:00:00 UTC.",
                "task_step": {"action": "reconcile published PR with GitHub", "attempt": "1", "result": "PR #77 merged", "status": "finished"}})
    client.post(f"/api/requests/{rid}/status", json={"status": "done", "note": "Verified in game."})
    runs = [{"id": RUN, "name": "gBox inbox task mode", "state": "completed", "started": t0 + 2, "finished": t0 + 400,
             "provider": "zai", "model": "glm-5.3", "request_ids": [rid, "f" * 16],
             "steps": [{"action": "mcp__gbox__get_request", "input": {"request_id": rid}, "result": "{}", "status": "finished"}]}]
    monkeypatch.setattr(request_story, "hermes_runs_for", lambda r_: runs if r_ == rid else [])
    monkeypatch.setattr(request_story, "workspace_for", lambda r_: None)
    real_diff = request_story.local_diff
    monkeypatch.setattr(request_story, "local_diff", lambda spec: real_diff(spec, repos=[repo]))
    resp = client.get(f"/api/requests/{rid}/story")
    assert resp.status_code == 200, resp.text
    s = resp.json()

    assert s["request"]["number"] == r["number"] and s["request"]["status"] == "done"
    tri = s["triage"]
    assert tri["by"] == "Hermes" and tri["agent"] == "zai/glm-5.3" and tri["at"] == pytest.approx(t0 + 2)
    assert tri["wait_s"] == pytest.approx(2, abs=0.2) and tri["candidates"] >= 3

    actions = [x["action"] for x in s["identification"]]
    assert actions[:4] == ["get_request", "dispatch resolution", "get_frame", "pytest"], actions
    assert s["identification"][0]["source"] == "Hermes run gBox inbox task mode"
    assert s["identification"][0]["input"] == f"request_id={rid}"
    frame = s["identification"][2]
    assert frame["input"] == "session_id=s1" and frame["result"] == "sha256=abc" and frame["duration_s"] == pytest.approx(2)
    assert s["identification"][3]["status"] == "failed"
    assert "reconcile published PR with GitHub" in actions

    hermes = next(w for w in s["runs"] if w["kind"] == "hermes")
    assert (hermes["tokens_in"], hermes["tokens_out"], hermes["api_calls"], hermes["duration_s"]) == (120_000, 3_000, 7, 300.0)
    assert hermes["shared_with"] == 1 and "exact" in hermes["usage_source"]
    assert hermes["cost"]["kind"] == "estimate"
    assert hermes["cost"]["usd"] == pytest.approx((20_000 * 0.60 + 100_000 * 0.11 + 3_000 * 2.20) / 1e6)
    local = next(w for w in s["runs"] if w["kind"] == "local_agent")
    assert (local["tokens_in"], local["tokens_out"], local["model"]) == (900, 40, "qwen3.6:35b")
    assert local["cost"]["usd"] == 0 and local["cost"]["kind"] == "estimate"
    assert not any(w["name"] == "Hermes usage not tied to a run" for w in s["runs"]), "the marker covers the Hermes metrics"

    assert [j["id"] for j in s["jobs"]] == ["j1"] and s["jobs"][0]["duration_s"] == 10

    (pr,) = s["changes"]
    assert (pr["number"], pr["state"], pr["merged_sha"], pr["source"]) == (77, "merged", head[:12], "local git")
    assert pr["url"] == "https://github.com/teamcsharp/gBox/pull/77"
    assert (pr["added"], pr["deleted"]) == (4, 1)
    assert [f["path"] for f in pr["folders"]] == ["system/gbox", "system/tests"]
    assert pr["merged_at"] == 1790856000.0

    assert s["resolution"]["status"] == "done" and s["resolution"]["final_message"] == "Verified in game."
    assert any(x["text"].startswith("PR #77 merged") for x in s["replies"])
    tot = s["totals"]
    assert (tot["tokens_in"], tot["tokens_out"]) == (120_900, 3_040) and tot["elapsed"] is False
    assert tot["cost"]["kind"] == "estimate" and tot["cost"]["usd"] == pytest.approx(hermes["cost"]["usd"])
    assert (tot["added"], tot["deleted"], tot["files"]) == (4, 1, 2)
    keys = [st["key"] for st in s["stages"]]
    assert keys[:3] == ["intake", "triage", "identify"] and keys[-1] == "resolution"
    assert keys.count("work") == 2 and keys.count("changes") == 1
    assert "Estimates" in s["prices"]["note"] or "estimates" in s["prices"]["note"]
    assert not any("not resolved" in m for m in s["missing"])


def test_story_of_an_untouched_request_says_what_is_missing(cfg, no_hermes):
    app, client = client_for(cfg)
    r = client.post("/api/requests", json={"title": "New idea", "body": "Please add X"}).json()
    s = client.get(f"/api/requests/{r['id']}/story").json()
    assert s["triage"] is None and s["identification"] == [] and s["runs"] == [] and s["changes"] == []
    assert s["totals"]["tokens_in"] == 0 and s["totals"]["cost"]["usd"] is None
    assert s["totals"]["elapsed"] is True and s["totals"]["duration_s"] >= 0
    text = " ".join(s["missing"])
    for phrase in ("Nobody has claimed", "No tool calls", "No agent run", "No code change", "not resolved"):
        assert phrase in text
    assert client.get("/api/requests/0000000000000000/story").status_code == 404


def test_unpriced_provider_and_uncached_pr_stay_null(cfg, no_hermes):
    app, client = client_for(cfg)
    r = client.post("/api/requests", json={"title": "T", "body": "b"}).json()
    rid = r["id"]
    client.post(f"/api/requests/{rid}/metrics", json={"provider": "nous", "model": "hermes-4", "system": "Claude Code",
                "tokens_in": 50, "tokens_out": 5})
    client.post(f"/api/requests/{rid}/messages", json={"author": "agent", "text": "PR #9 merged to main as deadbeefcafe at 2026-10-01 12:00:00 UTC."})
    s = client.get(f"/api/requests/{rid}/story").json()
    (agent,) = s["runs"]
    assert agent["kind"] == "agent" and agent["name"] == "Claude Code usage" and agent["cost"]["usd"] is None
    (pr,) = s["changes"]
    assert pr["files"] == [] and pr["added"] is None and pr["state"] == "merged"
    assert any("PR #9" in m for m in s["missing"])
    assert s["totals"]["cost"]["usd"] is None and "no price" in s["totals"]["cost"]["basis"]


def test_workspace_record_gives_files_without_counts_and_config_prices_override(cfg, monkeypatch):
    cfg.token_prices = {"nous": {"in": 2.0, "out": 8.0}}
    app, client = client_for(cfg)
    r = client.post("/api/requests", json={"title": "T", "body": "b"}).json()
    rid = r["id"]
    monkeypatch.setattr(request_story, "hermes_runs_for", lambda rid: (_ for _ in ()).throw(OSError("no db")))
    monkeypatch.setattr(request_story, "local_diff", lambda spec: None)
    monkeypatch.setattr(request_story, "workspace_for", lambda r_: {
        "request_id": rid, "branch": "hermes/request-1-1", "baseline": "1" * 40, "commit": "2" * 40,
        "files": ["system/gbox/x.py", "system/clients/desktop/y.js"], "pr_number": 5,
        "url": "https://github.com/teamcsharp/gBox/pull/5", "published_at": time.time()})
    client.post(f"/api/requests/{rid}/metrics", json={"provider": "nous", "model": "m", "system": "Other",
                "tokens_in": 1_000_000, "tokens_out": 1_000_000})
    s = client.get(f"/api/requests/{rid}/story").json()
    (pr,) = s["changes"]
    assert pr["number"] == 5 and pr["branch"] == "hermes/request-1-1" and pr["state"] == "unknown"
    assert [f["path"] for f in pr["files"]] == ["system/gbox/x.py", "system/clients/desktop/y.js"]
    assert all(f["added"] is None for f in pr["files"]) and "no line counts" in pr["source"]
    assert s["runs"][0]["cost"]["usd"] == pytest.approx(10.0)
    assert any("Hermes runs unavailable" in m for m in s["missing"])
