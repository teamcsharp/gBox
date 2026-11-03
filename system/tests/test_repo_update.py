"""The worker repo_update tool is fast-forward-only, ref-validated, and reports before/after
HEAD. (The control-plane route /api/workers/{name}/update-repo gates automation exactly like
bot-reload; verified by mirroring that handler.)"""
from gbox import tools


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def test_invalid_ref_runs_no_git(monkeypatch):
    called = []
    monkeypatch.setattr(tools.subprocess, "run", lambda *a, **k: called.append(a) or R())
    out = tools.repo_update(tools.RepoUpdateIn(ref="bad; rm -rf x"), None)["result"]
    assert out["ok"] is False and out["updated"] is False and not called


def test_fast_forward_happy_path_uses_ff_only(monkeypatch):
    state = {"head": "aaaaaaaaaaaa"}
    cmds = []

    def fake_run(cmd, **k):
        args = tuple(cmd[3:])                    # drop ["git","-C",<repo>]
        cmds.append(args)
        if args[:2] == ("rev-parse", "HEAD"):
            return R(0, state["head"] + "\n")
        if args[0] == "rev-parse":
            return R(0, "main\n")
        if args[0] == "status":
            return R(0, "")
        if args[0] == "fetch":
            return R(0, "")
        if args[0] == "merge":
            state["head"] = "bbbbbbbbbbbb"
            return R(0, "Updating aaaa..bbbb\n")
        return R(0, "")
    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    out = tools.repo_update(tools.RepoUpdateIn(), None)["result"]
    assert out["ok"] is True and out["updated"] is True
    assert out["before"].startswith("a") and out["after"].startswith("b") and out["ref"] == "origin/main"
    assert ("fetch", "origin") in cmds and ("merge", "--ff-only", "origin/main") in cmds
    # never a destructive op
    assert not any(a[0] in ("reset", "checkout", "clean", "push") for a in cmds)


def test_fetch_failure_is_reported_without_merging(monkeypatch):
    cmds = []

    def fake_run(cmd, **k):
        args = tuple(cmd[3:]); cmds.append(args)
        if args[:2] == ("rev-parse", "HEAD"):
            return R(0, "aaaaaaaaaaaa\n")
        if args[0] == "rev-parse":
            return R(0, "main\n")
        if args[0] == "status":
            return R(0, "")
        if args[0] == "fetch":
            return R(1, "", "could not resolve host github.com")
        return R(0, "")
    monkeypatch.setattr(tools.subprocess, "run", fake_run)
    out = tools.repo_update(tools.RepoUpdateIn(), None)["result"]
    assert out["ok"] is False and out["updated"] is False and "fetch failed" in out["reason"]
    assert not any(a[0] == "merge" for a in cmds)


def test_route_and_tool_registered():
    from gbox.registry import REGISTRY
    from gbox import bot_control
    assert "repo_update" in REGISTRY
    assert hasattr(bot_control, "RepoUpdateBody") and bot_control.RepoUpdateBody().ref == "origin/main"
