"""Tasks window Providers view: which Hermes provider did the work, which is out of credit (2026-10-13).

Synthetic agent.log / usage_audit.jsonl / feedback.json fixtures in Hermes's real formats: runs that
fall through routes are attributed to the provider whose call succeeded last, failed calls are counted
once, cooldowns and error texts give each route's status, OpenRouter's balance comes from its API
(mocked here) and the key never reaches the client.
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from gbox import hermes_providers as hp
from gbox.server import create_app

TZ = timezone(timedelta(hours=-5))          # the Spark's local time (CDT); log stamps are local
KEY = "sk-or-v1-" + "f" * 48
OPUS = "anthropic/claude-opus-5.5"
QWEN = "Qwen3.6-35B-A3B-UD-Q4_K_M"
NOUS_URL = "https://inference-api.nousresearch.com/v1"
REAL_HTTP_GET = hp._http_get


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    hp._SCANNERS.clear(); hp._DB_CACHE.clear()
    hp._BALANCE.update(at=0.0, data=None, busy=False, home=None)
    monkeypatch.setenv("GBOX_HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("GBOX_HERMES_DISPATCH_STATE", str(tmp_path / "dispatch"))
    monkeypatch.setenv("GBOX_HERMES_LOG_TZ", "-05:00")
    for name in ("GBOX_HERMES_AGENT_LOG", "GBOX_HERMES_USAGE_AUDIT", "GBOX_HERMES_ENV_FILE", "GBOX_HERMES_LOCAL_PROVIDERS"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    def fake_get(url, key):
        calls.append((url, key))
        if url.endswith("/credits"):
            return 200, {"data": {"total_credits": 125, "total_usage": 124.88}}
        return 200, {"data": {"label": "sk-or-v1-fff...fff", "limit": 150, "limit_remaining": 25.12, "usage": 124.88,
                              "usage_daily": 2.5, "usage_weekly": 30.0, "usage_monthly": 124.88}}
    monkeypatch.setattr(hp, "_http_get", fake_get)
    yield calls
    hp._SCANNERS.clear(); hp._DB_CACHE.clear()


def line(t, msg, tag=None, level="INFO", logger="run_agent"):
    return f"{t.astimezone(TZ):%Y-%m-%d %H:%M:%S},{t.microsecond // 1000:03d} {level}{f' [{tag}]' if tag else ''} {logger}: {msg}\n"


def ctx(provider, model, url):
    return f"thread=Thread-9 (<lambda>):123 provider={provider} base_url={url} model={model}"


def created(t, provider, model, url, tag=None):
    return line(t, f"OpenAI client created (chat_completion_stream_request, shared=False) {ctx(provider, model, url)}", tag)


def cleanup(t, provider, model, url):
    return line(t, f"OpenAI client closed (stream_error_cleanup, shared=False, tcp_force_closed=0) {ctx(provider, model, url)}")


def failed(t, tag, provider, model, url, summary):
    return line(t, f"API call failed (attempt 1/3) error_type=APIStatusError {ctx(provider, model, url)} summary={summary}",
                tag, "WARNING")


def ok(t, tag, provider, model, n_in, n_out):
    return line(t, f"API call #1: model={model} provider={provider} in={n_in} out={n_out} total={n_in + n_out} latency=4.0s id=x",
                tag, logger="agent.conversation_loop")


def tag(job, start):
    return f"cron_{job}_{start.astimezone(TZ):%Y%m%d_%H%M%S}"


def build(tmp_path, base, *, rotate=False):
    """Run A falls through nous (402) and ollama-cloud (429 monthly limit) to openrouter, which completes it.
    Run B: EhmBird fails (HTTP 500) and the local llama.cpp model completes it. Run C (a day earlier) is
    deepseek's; an audit-only fire D has no log session and failed on deepseek."""
    home = tmp_path / ".hermes"
    (home / "logs").mkdir(parents=True, exist_ok=True); (home / "cron").mkdir(exist_ok=True)
    a, b, c = base, base + timedelta(hours=1), base - timedelta(days=1)
    ta, tb, tc = tag("inbox01", a), tag("inbox01", b), tag("maint02", c)
    s = lambda t, sec: t + timedelta(seconds=sec)
    older = [created(s(c, 1), "deepseek", "deepseek-v4", "https://api.deepseek.com/v1"),
             ok(s(c, 30), tc, "deepseek", "deepseek-v4", 700, 70)]
    run_a = [created(s(a, 1), "nous", OPUS, NOUS_URL),
             cleanup(s(a, 2), "nous", OPUS, NOUS_URL),
             failed(s(a, 2.5), ta, "nous", OPUS, NOUS_URL, "HTTP 402: Insufficient available credits"),
             line(s(a, 3), f"Fallback activated: {OPUS} → kimi-k2.6 (ollama-cloud)", ta, logger="agent.chat_completion_helpers"),
             created(s(a, 4), "ollama-cloud", "kimi-k2.6", "https://ollama.com/v1"),
             cleanup(s(a, 5), "ollama-cloud", "kimi-k2.6", "https://ollama.com/v1"),
             failed(s(a, 5.5), ta, "ollama-cloud", "kimi-k2.6", "https://ollama.com/v1",
                    "HTTP 429: you (gbox) have reached your monthly usage limit"),
             created(s(a, 6), "openrouter", OPUS, "https://openrouter.ai/api/v1"),
             ok(s(a, 60), ta, "openrouter", OPUS, 1000, 200),
             created(s(a, 61), "openrouter", OPUS, "https://openrouter.ai/api/v1"),
             ok(s(a, 120), ta, "openrouter", OPUS, 2000, 300),
             line(s(a, 121), "tool web_fetch failed: HTTP 500 from example.org", ta, "WARNING", "agent.tool_executor")]
    run_b = [created(s(b, 1), "EhmBird", "ehm-1", "https://ehmbird.example/v1"),
             cleanup(s(b, 2), "EhmBird", "ehm-1", "https://ehmbird.example/v1"),
             failed(s(b, 2.2), tb, "EhmBird", "ehm-1", "https://ehmbird.example/v1", "HTTP 500: no user query found"),
             created(s(b, 3), "llamacpp", QWEN, "http://127.0.0.1:8080/v1"),
             ok(s(b, 50), tb, "llamacpp", QWEN, 500, 50)]
    if rotate:
        (home / "logs" / "agent.log.1").write_text("".join(older + run_a), encoding="utf-8")
        (home / "logs" / "agent.log").write_text("".join(run_b), encoding="utf-8")
    else:
        (home / "logs" / "agent.log").write_text("".join(older + run_a + run_b), encoding="utf-8")
    utc = lambda t: t.astimezone(timezone.utc).isoformat()
    audit = [{"ts": utc(s(a, 125)), "job_id": "inbox01", "model": OPUS, "total_tokens": 3600, "duration_ms": 125000, "error": None},
             {"ts": utc(s(b, 55)), "job_id": "inbox01", "model": QWEN, "total_tokens": 600, "duration_ms": 55000, "error": ""},
             {"ts": utc(s(c, 40)), "job_id": "maint02", "model": "deepseek-v4", "total_tokens": 800, "duration_ms": 40000, "error": None},
             {"ts": utc(s(c, 3600)), "job_id": "other", "model": "deepseek-v4", "total_tokens": 10, "duration_ms": 5000,
              "error": "HTTP 402: Insufficient Balance"}]
    (home / "cron" / "usage_audit.jsonl").write_text("".join(json.dumps(x) + "\n" for x in audit), encoding="utf-8")
    (home / "cron" / "jobs.json").write_text(json.dumps({"jobs": [{"id": "inbox01", "name": "gBox inbox task mode"},
                                                                  {"id": "maint02", "name": "nightly maintenance"}]}))
    ex = sqlite3.connect(home / "cron" / "executions.db")
    ex.execute("CREATE TABLE executions (id TEXT, job_id TEXT, status TEXT, started_at TEXT, finished_at TEXT, error TEXT)")
    for i, (job, t, dur) in enumerate((("inbox01", a, 125), ("inbox01", b, 55), ("maint02", c, 40))):
        ex.execute("INSERT INTO executions VALUES (?,?,?,?,?,?)", (f"{i:032x}", job, "completed", t.isoformat(),
                                                                   (t + timedelta(seconds=dur)).isoformat(), None))
    ex.commit(); ex.close()
    state = tmp_path / "dispatch"; state.mkdir(exist_ok=True)
    now = (b + timedelta(hours=1)).timestamp()
    (state / "feedback.json").write_text(json.dumps({
        "routes": [{"provider": "openrouter", "model": OPUS}, {"provider": "nous", "model": OPUS},
                   {"provider": "ollama-cloud", "model": "kimi-k2.6"}, {"provider": "zai", "model": "glm-5.3"}],
        "current_route": {"provider": "openrouter", "model": OPUS},
        "cooldowns": {f"nous/{OPUS}": now + 3600, "zai/glm-5.3": now + 86400, "deepseek/deepseek-v4": now - 10},
        "cooldown_details": {f"nous/{OPUS}": {"until": now + 3600, "category": "quota", "source": "scheduler_backoff"},
                             "zai/glm-5.3": {"until": now + 86400, "category": "rate_limit"}}}))
    (home / ".env").write_text(f"# Hermes keys\nexport OPENROUTER_API_KEY=\"{KEY}\"\nNOUS_API_KEY=abc\n")
    return home, now


BASE = datetime(2026, 10, 13, 9, 0, tzinfo=TZ)


def route(data, key):
    return next(r for r in data["routes"] if r["key"] == key)


def test_runs_are_attributed_to_the_provider_whose_call_succeeded_last(tmp_path):
    _, now = build(tmp_path, BASE)
    data = hp.summary("today", now, wait_balance=True)
    rows = {r["key"]: r for r in data["routes"]}
    assert list(rows)[:4] == [f"openrouter/{OPUS}", f"nous/{OPUS}", "ollama-cloud/kimi-k2.6", "zai/glm-5.3"]
    orr = rows[f"openrouter/{OPUS}"]
    assert orr["current"] and orr["in_routes"] and not orr["local"]
    assert (orr["runs_completed"], orr["runs_failed"], orr["calls_ok"], orr["calls_failed"]) == (1, 0, 2, 0)
    assert orr["tokens"] == 3500 and orr["wall_s"] == 125
    assert orr["status"]["state"] == "working"
    # nous and ollama-cloud were tried by run A but did not serve it.
    for key in (f"nous/{OPUS}", "ollama-cloud/kimi-k2.6"):
        assert (rows[key]["runs_completed"], rows[key]["calls_ok"], rows[key]["calls_failed"]) == (0, 0, 1)
    qwen = rows[f"llamacpp/{QWEN}"]
    assert qwen["local"] and not qwen["in_routes"] and qwen["runs_completed"] == 1 and qwen["tokens"] == 550
    assert rows["EhmBird/ehm-1"]["calls_failed"] == 1 and rows["EhmBird/ehm-1"]["runs_completed"] == 0
    # Yesterday's deepseek work is outside "today".
    assert "deepseek/deepseek-v4" not in rows
    runs = {r["session_id"]: r for r in data["runs"]}
    a = runs[tag("inbox01", BASE)]
    assert (a["provider"], a["model"], a["status"], a["tokens"], a["name"]) == ("openrouter", OPUS, "completed", 3600, "gBox inbox task mode")
    assert a["tried"] == [f"nous/{OPUS}", "ollama-cloud/kimi-k2.6"]
    assert runs[tag("inbox01", BASE + timedelta(hours=1))]["provider"] == "llamacpp"
    assert hp.session_providers(now)[tag("inbox01", BASE)] == {"provider": "openrouter", "model": OPUS, "attribution": "log"}


def test_status_from_errors_and_cooldowns_and_the_recommendation(tmp_path):
    _, now = build(tmp_path, BASE)
    data = hp.summary("today", now, wait_balance=True)
    nous = route(data, f"nous/{OPUS}")
    assert nous["status"]["state"] == "out_of_credit" and nous["status"]["label"].startswith("Out of credit · cooling until ")
    assert nous["cooldown"]["category"] == "quota"
    assert nous["last_error"]["text"] == "HTTP 402: Insufficient available credits" and nous["last_error"]["code"] == 402
    assert nous["balance"]["note"].startswith("Balance not available")
    kimi = route(data, "ollama-cloud/kimi-k2.6")
    assert kimi["status"]["state"] == "usage_limit" and kimi["last_error"]["kind"] == "usage_limit"
    zai = route(data, "zai/glm-5.3")
    assert zai["status"]["state"] == "cooling" and zai["status"]["label"].startswith("Cooling until ")
    ehm = route(data, "EhmBird/ehm-1")
    assert ehm["status"]["state"] == "failing" and "no user query found" in ehm["status"]["label"]
    # The tool's HTTP 500 is not a provider error.
    assert route(data, f"openrouter/{OPUS}")["last_error"] is None
    assert route(data, f"llamacpp/{QWEN}")["balance"]["note"].startswith("Local model")
    assert {e["provider"]: e["state"] for e in data["exhausted"]} == {"nous": "out_of_credit", "ollama-cloud": "usage_limit"}
    assert data["recommendation"] == ("openrouter did the most completed work per dollar (today): 1 run for $2.50, "
                                      "$2.50 a run. Exhausted: nous (out of credit), ollama-cloud (usage limit).")


def test_openrouter_balance_from_its_api_never_exposes_the_key(tmp_path, _fresh):
    _, now = build(tmp_path, BASE)
    data = hp.summary("7d", now, wait_balance=True)
    bal = route(data, f"openrouter/{OPUS}")["balance"]
    assert bal["available"] and bal["total_credits"] == 125 and bal["credits_remaining"] == pytest.approx(0.12)
    assert bal["key_limit"] == 150 and bal["key_limit_remaining"] == 25.12 and bal["remaining_usd"] == pytest.approx(0.12)
    assert (bal["usage_daily"], bal["usage_weekly"]) == (2.5, 30.0)
    assert [u for u, _ in _fresh] == ["https://openrouter.ai/api/v1/credits", "https://openrouter.ai/api/v1/key"]
    assert all(k == KEY for _, k in _fresh)
    text = json.dumps(data)
    assert KEY not in text and "sk-or-v1" not in text and "label" not in json.dumps(bal)
    provider = next(p for p in data["providers"] if p["provider"] == "openrouter")
    assert (provider["spend_usd"], provider["spend_source"]) == (30.0, "OpenRouter account")
    # Cached for five minutes: a second poll does not call OpenRouter again.
    hp.summary("7d", now + 60, wait_balance=True)
    assert len(_fresh) == 2
    hp.summary("7d", now + 400, wait_balance=True)
    assert len(_fresh) == 4
    # The 7 day window includes yesterday's deepseek run and the audit-only fire, attributed by model.
    deepseek = route(data, "deepseek/deepseek-v4")
    assert deepseek["runs_completed"] == 1 and deepseek["runs_failed"] == 1 and deepseek["tokens"] == 780
    # Its later audit-only 402 says the balance is gone, though the log no longer has that call.
    assert deepseek["status"]["state"] == "out_of_credit" and deepseek["last_error"]["text"] == "HTTP 402: Insufficient Balance"
    assert "deepseek (out of credit)" in data["recommendation"]


def test_out_of_credit_from_a_zero_balance_and_http_failures(tmp_path, monkeypatch):
    _, now = build(tmp_path, BASE)
    monkeypatch.setattr(hp, "_http_get", lambda url, key: (200, {"data": {"total_credits": 125, "total_usage": 125}})
                        if url.endswith("/credits") else (200, {"data": {"limit": None, "usage": 125}}))
    data = hp.summary("today", now, wait_balance=True)
    assert route(data, f"openrouter/{OPUS}")["status"]["state"] == "out_of_credit"
    assert "openrouter (out of credit)" in data["recommendation"]
    hp._BALANCE.update(at=0.0, data=None)
    monkeypatch.setattr(hp, "_http_get", lambda url, key: (401, None))
    bal = hp.openrouter_balance(now=now, wait=True)
    assert not bal["available"] and "HTTP 401" in bal["note"] and KEY not in json.dumps(bal)


def test_http_get_sends_the_key_only_as_a_header_and_reports_only_the_status(monkeypatch):
    import urllib.error
    import urllib.request
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, auth=request.get_header("Authorization"))
        raise urllib.error.HTTPError(request.full_url, 402, "Payment Required", {}, None)
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert REAL_HTTP_GET("https://openrouter.ai/api/v1/credits", KEY) == (402, None)
    assert seen == {"url": "https://openrouter.ai/api/v1/credits", "auth": "Bearer " + KEY}


def test_logs_are_read_incrementally_and_survive_rotation(tmp_path):
    home, now = build(tmp_path, BASE)
    first = hp.summary("today", now)
    scan = hp.scanner(home)
    count = len(scan.events)
    hp.summary("today", now)
    assert len(scan.events) == count, "an unchanged log is not parsed again"
    # The log rotates and a new run starts on the fresh file.
    log = home / "logs" / "agent.log"
    log.replace(home / "logs" / "agent.log.1")
    t = BASE + timedelta(hours=1, minutes=30)
    log.write_text(created(t, "openrouter", OPUS, "https://openrouter.ai/api/v1")
                   + ok(t + timedelta(seconds=9), tag("inbox01", t), "openrouter", OPUS, 10, 5)
                   + "2026-10-13 10:31:00,000 INFO partial line without newline", encoding="utf-8")
    data = hp.summary("today", now)
    orr, before = route(data, f"openrouter/{OPUS}"), route(first, f"openrouter/{OPUS}")
    assert orr["calls_ok"] == before["calls_ok"] + 1 and orr["tokens"] == before["tokens"] + 15
    assert len(scan.events) == count + 2


def test_tagged_call_lines_without_api_call_counts(tmp_path):
    """A log that only tags client creation and stream cleanup: a call that did not fail returned."""
    home, now = build(tmp_path, BASE)
    t, sid = BASE + timedelta(minutes=20), tag("inbox01", BASE + timedelta(minutes=20))
    url = "https://openrouter.ai/api/v1"
    (home / "logs" / "agent.log").write_text("".join([
        created(t, "nous", OPUS, NOUS_URL, sid),
        line(t + timedelta(seconds=1), f"OpenAI client closed (stream_error_cleanup, shared=False, tcp_force_closed=0) "
                                       f"{ctx('nous', OPUS, NOUS_URL)}", sid),
        line(t + timedelta(seconds=1), f"HTTP 402: Insufficient available credits {ctx('nous', OPUS, NOUS_URL)}", sid, "ERROR"),
        created(t + timedelta(seconds=2), "openrouter", OPUS, url, sid),
        created(t + timedelta(seconds=40), "openrouter", OPUS, url, sid)]), encoding="utf-8")
    data = hp.summary("today", now)
    assert (route(data, f"nous/{OPUS}")["calls_ok"], route(data, f"nous/{OPUS}")["calls_failed"]) == (0, 1)
    assert route(data, f"nous/{OPUS}")["last_error"]["text"] == "HTTP 402: Insufficient available credits"
    assert route(data, f"openrouter/{OPUS}")["calls_ok"] == 2
    run = next(r for r in data["runs"] if r["session_id"] == sid)
    assert (run["provider"], run["attribution"], run["tried"]) == ("openrouter", "log_inferred", [f"nous/{OPUS}"])


def test_rotated_files_are_read_on_first_scan(tmp_path):
    _, now = build(tmp_path, BASE, rotate=True)
    data = hp.summary("today", now)
    assert route(data, f"openrouter/{OPUS}")["runs_completed"] == 1
    assert route(data, f"llamacpp/{QWEN}")["runs_completed"] == 1


def test_missing_files_give_an_empty_view(tmp_path):
    data = hp.summary("today", datetime(2026, 10, 13, 12, tzinfo=TZ).timestamp(), wait_balance=True)
    assert data["routes"] == [] and data["providers"] == [] and data["runs"] == []
    assert data["sources"] == {"agent_log": False, "usage_audit": False, "feedback": False, "executions": False}
    assert data["recommendation"] == "No paid provider completed a run (today). No route is exhausted."
    with pytest.raises(ValueError):
        hp.summary("month")


def test_error_kinds_and_redaction():
    assert hp.error_kind("HTTP 402: Insufficient available credits") == "out_of_credit"
    assert hp.error_kind("HTTP 403: Key limit exceeded (total limit)") == "out_of_credit"
    assert hp.error_kind("HTTP 429: you have reached your monthly usage limit") == "usage_limit"
    assert hp.error_kind("HTTP 429: Too Many Requests") == "rate_limited"
    assert hp.error_kind("HTTP 500: no user query found") == "failing"
    assert KEY not in hp.redact(f"auth failed for Bearer {KEY} and api_key={KEY}")
    assert hp.is_local("custom", "http://10.89.1.246:11434/v1") and hp.is_local("llamacpp")
    assert not hp.is_local("ollama-cloud", "https://ollama.com/v1") and not hp.is_local("nous", NOUS_URL)


def _state_db(home, base):
    st = sqlite3.connect(home / "state.db")
    st.execute("CREATE TABLE sessions (id TEXT, source TEXT, started_at REAL, model TEXT, billing_provider TEXT, "
               "input_tokens INTEGER, output_tokens INTEGER, actual_cost_usd REAL, estimated_cost_usd REAL)")
    st.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, "
               "tool_calls TEXT, tool_call_id TEXT)")
    st.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
               (tag("inbox01", base), "cron", base.timestamp() + 1, OPUS, "nous", 3000, 500, 0, 1.25))
    st.commit(); st.close()


def test_endpoint_and_task_runs_show_the_serving_provider(cfg, tmp_path, monkeypatch):
    import time
    base = datetime.fromtimestamp(time.time() - 3 * 3600, TZ).replace(microsecond=0)
    home, _ = build(tmp_path, base)
    _state_db(home, base)
    app = create_app(cfg)
    client = TestClient(app, headers={"authorization": f"Bearer {cfg.token()}"})
    assert TestClient(app).get("/api/hermes/providers").status_code == 401
    assert client.get("/api/hermes/providers?window=month").status_code == 422
    data = client.get("/api/hermes/providers?window=7d").json()
    assert data["window"] == "7d" and route(data, f"openrouter/{OPUS}")["runs_completed"] == 1
    assert KEY not in json.dumps(data)
    nous = next(p for p in data["providers"] if p["provider"] == "nous")
    assert (nous["spend_usd"], nous["spend_source"]) == (1.25, "Hermes recorded cost")
    runs = client.get("/api/tasks").json()["hermes"]
    run = next(r for r in runs if r["session_id"] == tag("inbox01", base))
    # The session started on nous; openrouter served its last successful call.
    assert (run["provider"], run["billing_provider"], run["model"]) == ("openrouter", "nous", OPUS)
    assert run["provider_attribution"] == "log"
