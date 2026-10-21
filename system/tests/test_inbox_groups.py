"""#1788: automated inbox tickets collapse into one entry per kind (gbox.inbox.group_key/grouped, /api/requests?group=1,
agent_ledger.py list --group). Presentation only: nothing is closed or deleted, and the plain list is unchanged."""
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from gbox import inbox
from gbox.server import create_app

TESTS = Path(__file__).resolve().parent
CASES = json.loads((TESTS / "fixtures" / "inbox_groups_cases.json").read_text(encoding="utf-8"))["cases"]


def test_shared_cases_match_the_desktop_rules():
    for case in CASES:
        assert inbox.group_key(case["request"]) == case["key"], case["request"]["title"]
        assert case["key"] is None or case["key"] in inbox.GROUP_LABELS


def _req(i, title, **extra):
    return {"id": f"r{i}", "number": i, "title": title, "status": "done", "created": 1000 - i, "source": "chat",
            "author": "operator", **extra}


def test_grouped_keeps_order_counts_and_every_id():
    lf = dict(source="automation", author="system", automated=True, context={"launch_failure": True})
    rows = [_req(1, "operator ask"), _req(2, "Launch failed: A", status="open", **lf), _req(3, "Build report: m (g): broken", source="app"),
            _req(4, "Launch failed: B", **lf), _req(5, "Character replacement readiness: X", source="automation", author="agent", automated=True)]
    out = inbox.grouped(rows)
    assert [e.get("group") or e["title"] for e in out] == ["operator ask", "launch_failure", "Build report: m (g): broken",
                                                            "Character replacement readiness: X"]
    g = out[1]
    assert g == {"group": "launch_failure", "label": "Launch failures", "count": 2, "pending": 1, "newest": 998,
                 "ids": ["r2", "r4"], "latest": {"id": "r2", "number": 2, "title": "Launch failed: A", "status": "open", "created": 998}}
    assert out[3] is rows[4], "a kind with one ticket stays a plain request"
    assert inbox.grouped([]) == []


def test_api_group_view_is_opt_in_and_the_plain_list_is_unchanged(cfg):
    app = create_app(cfg)
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    mine = client.post("/api/requests", json={"title": "Group the inbox", "body": "please", "source": "chat"}).json()["id"]
    failures = [client.post("/api/requests", json={"title": f"Launch failed: Game {i} on i9-NUC", "body": "boot timeout",
                                                    "source": "automation", "author": "system", "automated": True,
                                                    "context": {"launch_failure": True, "auto_report": True}}).json()["id"]
                for i in range(3)]
    plain = client.get("/api/requests")
    assert plain.status_code == 200 and len(plain.json()) == 4 and all("group" not in r for r in plain.json())
    grouped = client.get("/api/requests?group=1")
    assert grouped.status_code == 200 and grouped.headers["etag"] != plain.headers["etag"]
    body = grouped.json()
    groups = [e for e in body if "group" in e]
    assert len(groups) == 1 and groups[0]["group"] == "launch_failure" and groups[0]["count"] == 3
    assert sorted(groups[0]["ids"]) == sorted(failures)
    assert [e["id"] for e in body if "group" not in e] == [mine]
    assert client.get("/api/requests?group=1", headers={"if-none-match": grouped.headers["etag"]}).status_code == 304
    assert len(client.get("/api/requests").json()) == 4, "grouping closes and deletes nothing"


def test_ledger_list_group_prints_one_line_per_automated_kind(monkeypatch, capsys):
    sys.path.insert(0, str(TESTS.parent / "scripts"))
    import agent_ledger
    metrics = {"tokens_in": 0, "tokens_out": 0, "files_changed": [], "tools": {}}
    rows = [_req(i, f"Launch failed: Game {i}", status="open", source="automation", author="system", automated=True,
                 context={"launch_failure": True}, kind="text", messages=[], metrics=metrics) for i in range(10, 25)]
    rows.insert(0, _req(1, "Group the inbox", status="open", kind="text", messages=[], metrics=metrics))
    monkeypatch.setattr(agent_ledger, "api", lambda path, *a, **k: rows)
    monkeypatch.setattr(sys, "argv", ["agent_ledger.py", "list", "--group"])
    agent_ledger.main()
    out = capsys.readouterr().out
    assert out.startswith("#1 [open] Group the inbox")
    assert out.count("Launch failed") == 1, "the 15 launch failures are one line plus the newest title"
    assert "[Launch failures] 15 automated (15 not done)" in out and "#10 #11" in out and "(+3 more)" in out
    monkeypatch.setattr(sys, "argv", ["agent_ledger.py", "list"])
    agent_ledger.main()
    assert capsys.readouterr().out.count("Launch failed") == 15, "without --group the list is unchanged"


STANDING = json.loads((TESTS / "fixtures" / "inbox_standing_cases.json").read_text(encoding="utf-8"))["cases"]


def test_standing_background_work_matches_the_desktop_rules():
    """#2801: per-game tasks the Hermes queue keeps open are Background work, not inbox messages."""
    for case in STANDING:
        assert inbox.standing_key(case["request"]) == case["key"], case["request"]["title"]
        assert case["key"] is None or case["key"] in inbox.STANDING_LABELS
