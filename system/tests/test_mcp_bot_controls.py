"""The Mercenaries bot's controls and the RAM mods as first-class MCP tools (operator 2026-10-26, request #3889): the pure
helpers (gbox.mcp_bot_controls) without the MCP SDK, and the tools' HTTP round trip through a fake control plane with it."""
import asyncio
import inspect
import json

import httpx
import pytest

from gbox import mcp_bot_controls as BC

RE5 = {"session_id": "w5-abc", "state": "running", "game_id": "e7ca89bbeb67360d", "title": "Resident Evil 5 Gold Edition", "adapter": "rpcs3"}
RE4 = {"session_id": "w4-def", "state": "running", "game_id": "78ab9efa2e310db4", "title": "Resident Evil 4 (USA) (Disc 1)", "adapter": "dolphin"}
OTHER = {"session_id": "w4-ghi", "state": "running", "game_id": "zzz", "title": "Sonic Adventure 2", "adapter": "dolphin"}
ENDED = {"session_id": "w5-old", "state": "ended", "ended": 5, "game_id": "e7ca89bbeb67360d", "title": "Resident Evil 5 Gold Edition"}


def test_the_mod_tool_follows_the_session_game_never_the_emulator_alone():
    assert BC.mod_tool_for(RE5) == "re5_mods"
    assert BC.mod_tool_for(RE4) == "re_mods"
    assert BC.mod_tool_for({"session_id": "x", "title": "Biohazard 4: Wii Edition"}) == "re_mods"
    assert BC.mod_tool_for({"session_id": "x", "game_id": "e42c9b780c07c437"}) == "re_mods"
    assert BC.mod_tool_for(OTHER, "re5_mods") == "re5_mods"                        # an explicit override is honoured
    with pytest.raises(ValueError, match="no RE4 / RE5 mod tool"):
        BC.mod_tool_for(OTHER)                                                     # a Dolphin game is not RE4
    with pytest.raises(ValueError, match="job_re6"):
        BC.mod_tool_for(RE5, "re6")


def test_the_catalog_is_honest_about_each_tools_ops_fields_and_retained_settings():
    from gbox import mercmode, re5_mods_tool, re_mods_tool
    re5_src, re4_src = inspect.getsource(re5_mods_tool._run), inspect.getsource(re_mods_tool._run)
    for op in BC.RE5_OPS:
        assert f'"{op}"' in re5_src or f"'{op}'" in re5_src, op                   # every listed op is dispatched by run()
    for op in BC.RE4_OPS:
        assert f'"{op}"' in re4_src or f"'{op}'" in re4_src or op in re_mods_tool.OPERATOR_SETTINGS, op
    assert set(BC.RE5_FIELDS) <= set(re5_mods_tool.RE5ModsIn.model_fields) - {"session_id", "op", "ops"}
    assert set(BC.RE4_FIELDS) == set(re_mods_tool.REModsIn.model_fields) - {"session_id", "op", "ops"}
    for tool, ops in BC.CATALOG.items():                                           # each op's params are that tool's fields
        for op, spec in ops["ops"].items():
            assert set(spec["params"]) <= set(ops["fields"]), (tool, op)
    assert set(BC.RETAINED_OPS["re5_mods"]) == set(re5_mods_tool.SAVED_OPS)        # what the tools keep as the operator's
    assert set(BC.RETAINED_OPS["re_mods"]) == set(re_mods_tool.SAVED_OPS)
    assert set(BC.MOD_TOOLS["re5_mods"]["game_ids"]) == set(mercmode.TITLES["re5"]["game_ids"])
    assert set(BC.MOD_TOOLS["re_mods"]["game_ids"]) == set(mercmode.TITLES["re4"]["game_ids"])
    assert set(BC.TEAM_GAME_IDS) >= set(mercmode.TITLES["re5"]["game_ids"]) | set(mercmode.TITLES["re6"]["game_ids"])
    described = BC.describe_ops("re5_mods")
    assert described["ops"]["mines"]["retained"] and not described["ops"]["add_time"]["retained"]


def test_mod_input_rejects_fields_the_tool_would_silently_drop():
    assert BC.mod_input("re5_mods", "w5-abc", " Fire-Rate ", {"multiplier": 80}) == {"session_id": "w5-abc", "op": "fire_rate", "multiplier": 80}
    with pytest.raises(ValueError, match="no field seconds.*kill_time takes: on, multiplier"):
        BC.mod_input("re5_mods", "w5-abc", "kill_time", {"seconds": 10})
    with pytest.raises(ValueError, match="arguments of game_mod"):
        BC.mod_input("re_mods", "w4-def", "give", {"session_id": "other"})
    with pytest.raises(ValueError, match="op is required"):
        BC.mod_input("re_mods", "w4-def", "", {})


def test_strategy_plan_covers_the_retained_mods_mercmode_and_team_and_nothing_invented():
    plan = BC.strategy_plan("re5_mods", RE5, {"mods": [{"op": "kill_time", "on": True, "multiplier": 10}],
                                              "mercmode": {"enabled": True, "titles": ["re5"]}, "team": {"role": "solo_p1"}})
    assert plan == [("mod", {"session_id": "w5-abc", "op": "kill_time", "on": True, "multiplier": 10}),
                    ("mercmode", {"enabled": True, "titles": ["re5"]}),
                    ("team", {"session_id": "w5-abc", "op": "configure", "role": "solo_p1"})]
    with pytest.raises(ValueError, match="not a setting the re5_mods bot keeps"):
        BC.strategy_plan("re5_mods", RE5, {"mods": [{"op": "add_time", "multiplier": 60}]})
    with pytest.raises(ValueError, match="Resident Evil 5 and 6"):
        BC.strategy_plan("re_mods", RE4, {"team": {"role": "solo_p1"}})
    with pytest.raises(ValueError, match="unknown settings aggression"):
        BC.strategy_plan("re_mods", RE4, {"aggression": 3})
    with pytest.raises(ValueError, match="unknown mercmode settings volume"):
        BC.strategy_plan("re_mods", RE4, {"mercmode": {"volume": 1}})
    with pytest.raises(ValueError, match="need an RE4 / RE5 session"):
        BC.strategy_plan(None, OTHER, {"mods": [{"op": "infinite_ammo"}]})
    assert BC.strategy_plan(None, OTHER, {"mercmode": {"enabled": False}}) == [("mercmode", {"enabled": False})]
    options = BC.strategy_options("re_mods")
    assert "spawn_multiplier" in options["mods"]["ops"] and "re5_policy" in options["not_settable"]
    assert "critical_radius_cm 350" in BC.NOT_SETTABLE["re5_policy"]


def test_bot_summary_and_session_rows_read_the_telemetry_and_the_pc():
    workers = [{"id": "w5", "name": "JAYBUILTFINALE", "online": True}, {"id": "w4", "name": "i9-NUC", "online": False}]
    tel = {"running": True, "age_s": 2.0, "mode": "mercs", "mission": "", "source_autoplay_job_id": "j1",
           "stats": {"phase": "fight", "rounds": 3, "directive_status": "acting: hunt", "mines_enabled": True, "_private": 1, "hp": 900}}
    row = BC.session_row(RE5, tel, workers)
    assert row["host"] == "JAYBUILTFINALE" and row["worker_id"] == "w5" and row["mod_tool"] == "re5_mods"
    assert row["bot"] == {"running": True, "telemetry": True, "age_s": 2.0, "mode": "mercs", "mission": "", "autoplay_job_id": "j1",
                          "phase": "fight", "rounds": 3, "directive_status": "acting: hunt", "mines_enabled": True}
    quiet = BC.session_row(OTHER, {}, workers)
    assert quiet["bot"] == {"running": False, "telemetry": False} and quiet["mod_tool"] is None and quiet["host_online"] is False


SPAWN_ROWS = [{"id": "a", "number": 3041, "title": "Mercenaries: spawn multiplier slider (up to 4x enemies) in the mod panel", "created": 1},
              {"id": "b", "number": 3888, "title": "in the middle of rounds of mercenaries, why does enemies stop spawning?", "created": 2},
              {"id": "c", "number": 3889, "status": "in_progress", "created": 3,
               "title": "i need to be able to make enemies appear and spawn whatever enemies i want. All of the mods we pipe"},
              {"id": "d", "number": 3900, "status": "open", "created": 4,
               "title": "RE5 PS3: spawn any enemy type on demand / a wave at each spawn point / never stop spawning (Ghidra)"},
              {"id": "e", "number": 3901, "status": "open", "created": 5,
               "title": "RE4 GC: spawn any enemy type on demand / a wave at each spawn point / never stop spawning (Ghidra)"}]


def test_spawn_tickets_are_the_spawn_requests_not_every_ticket_with_the_word():
    assert BC.spawn_tickets(SPAWN_ROWS[:3])["ticket"] == 3889                      # the operator's own request, before the per-title ones
    assert BC.spawn_tickets(SPAWN_ROWS[:2]) == {"ticket": None, "request": None, "requests": []}   # not filed yet: no number
    found = BC.spawn_tickets(SPAWN_ROWS, "re5_mods")
    assert found["ticket"] == 3900 and [r["number"] for r in found["requests"]] == [3901, 3900, 3889]
    assert BC.spawn_tickets(SPAWN_ROWS, "re_mods")["ticket"] == 3901
    assert BC.spawn_tickets(SPAWN_ROWS)["ticket"] == 3901                          # no title: the newest


def _plane(posted, jobs):
    """A fake control plane: two live sessions on two PCs, the RE5 bot playing, jobs finishing at once."""
    hosts = {"hosts": [{"name": "JAYBUILTFINALE", "id": "w5", "settings": {"enabled": False, "titles": ["re4", "re5", "re6"]},
                        "desired_settings": {"enabled": True, "titles": ["re5"]}, "settings_source": "this_control_plane"}]}
    requests = list(SPAWN_ROWS)

    def handler(req):
        path, method = req.url.path, req.method
        if path == "/api/registry":
            return httpx.Response(200, json={"tools": [{"name": n, "description": n, "input_schema": {"type": "object", "properties": {"session_id": {}}}}
                                                       for n in ("re5_mods", "re_mods", "mercs_team")]})
        if path == "/api/sessions":
            return httpx.Response(200, json=[RE5, RE4, OTHER, ENDED])
        if path == "/api/workers":
            return httpx.Response(200, json=[{"id": "w5", "name": "JAYBUILTFINALE", "online": True, "os": "windows", "active_jobs": 0},
                                             {"id": "w4", "name": "i9-NUC", "online": True, "os": "windows", "active_jobs": 1}])
        if path.startswith("/api/autoplay/telemetry/"):
            sid = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"running": True, "age_s": 1.5, "mode": "mercs", "mission": "", "stats": {
                "phase": "fight", "rounds": 2, "directive_status": "acting: hunt", "mines_enabled": True}} if sid == "w5-abc" else {})
        if path.endswith("/directive") and method == "POST":
            body = json.loads(req.content)
            posted.append((path, body))
            return httpx.Response(200, json={"directive": {"seq": len(posted), "command": body["command"], "at": 1.0,
                                                           "until": 1.0 + body.get("hold_s", 20), "source": "mcp"}})
        if path == "/api/jobs" and method == "GET":
            return httpx.Response(200, json=[])
        if path == "/api/jobs" and method == "POST":
            body = json.loads(req.content)
            posted.append((path, body))
            job = body | {"id": f"job-{len(jobs) + 1}", "state": "succeeded", "worker_id": body.get("require_worker"),
                          "output": {"result": {"verified": True, "op": body["input"].get("op")}}, "error": None}
            jobs.append(job)
            return httpx.Response(200, json=job)
        if path.startswith("/api/jobs/"):
            return httpx.Response(200, json=next(j for j in jobs if j["id"] == path.rsplit("/", 1)[1]))
        if path == "/api/mercmode" and method == "POST":
            posted.append((path, json.loads(req.content)))
            return httpx.Response(200, json=hosts)
        if path == "/api/mercmode":
            return httpx.Response(200, json=hosts)
        if path == "/api/requests":
            return httpx.Response(200, json=requests)
        raise AssertionError(f"{method} {path}")
    return handler


def test_mcp_bot_controls_round_trip(monkeypatch):
    pytest.importorskip("mcp")
    from mcp.client import Client
    from gbox import mcp_server

    posted, jobs = [], []
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: original(*args, **kwargs, transport=httpx.MockTransport(_plane(posted, jobs))))
    monkeypatch.setattr(mcp_server, "JOB_WAIT_SECONDS", 0)
    monkeypatch.delenv("GBOX_OPERATOR_WORKER", raising=False)
    monkeypatch.delenv("GBOX_TEST_WORKER", raising=False)

    async def call(client, name, args):
        r = await client.call_tool(name, args)
        return json.loads(r.content[0].text), r.is_error

    async def check():
        async with Client(mcp_server.build("http://fixture", "fixture")) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert {"bot_sessions", "bot_directive", "game_mod", "game_mod_ops", "bot_strategy", "spawn_enemies"} <= set(tools)
            assert "mine_trail" in tools["bot_directive"].input_schema["properties"]["command"]["enum"]
            assert "NOT available yet" in tools["spawn_enemies"].description

            out, err = await call(client, "bot_sessions", {})
            assert not err and [s["session_id"] for s in out["sessions"]] == ["w5-abc", "w4-def", "w4-ghi"]
            re5 = out["sessions"][0]
            assert re5["host"] == "JAYBUILTFINALE" and re5["mod_tool"] == "re5_mods" and re5["bot"]["running"] and re5["bot"]["phase"] == "fight"
            assert out["sessions"][1]["mod_tool"] == "re_mods" and not out["sessions"][1]["bot"]["running"]
            assert out["commands"]["mine_trail"].startswith("Drop mines while leaving")

            out, err = await call(client, "bot_directive", {"session_id": "w5-abc", "command": "hunt"})
            assert not err and out["directive"]["command"] == "hunt" and not out["matched_from_text"]
            out, err = await call(client, "bot_directive", {"session_id": "w5-abc", "text": "drop landmines while fleeing an area", "hold_s": 90})
            assert not err and out["directive"]["command"] == "mine_trail" and out["matched_from_text"] and out["directive"]["until"] == 91.0
            out, err = await call(client, "bot_directive", {"session_id": "w5-abc", "text": "nice shooting"})
            assert err and "no command matched" in out["error"]
            out, err = await call(client, "bot_directive", {"session_id": "w5-old", "command": "fight"})
            assert err and "not running" in out["error"]
            assert [b for p, b in posted if p.endswith("/directive")] == [{"command": "hunt"}, {"command": "mine_trail", "hold_s": 90}]

            out, err = await call(client, "game_mod", {"session_id": "w5-abc", "op": "fire_rate", "params": {"multiplier": 80}})
            assert not err and out["state"] == "succeeded" and out["mod_tool"] == "re5_mods" and out["output"]["result"]["verified"]
            out, err = await call(client, "game_mod", {"session_id": "w4-def", "op": "spawn_multiplier", "params": {"count": 3}})
            assert not err and out["mod_tool"] == "re_mods" and out["worker_id"] == "w4"
            out, err = await call(client, "game_mod", {"session_id": "w5-abc", "op": "kill_time", "params": {"seconds": 10}})
            assert err and "no field seconds" in out["error"]
            out, err = await call(client, "game_mod", {"session_id": "w4-ghi", "op": "status"})
            assert err and "no RE4 / RE5 mod tool" in out["error"]
            mods = [b for p, b in posted if p == "/api/jobs"]
            assert mods == [{"tool": "re5_mods", "input": {"session_id": "w5-abc", "op": "fire_rate", "multiplier": 80}, "agent_use": True, "require_worker": "w5"},
                            {"tool": "re_mods", "input": {"session_id": "w4-def", "op": "spawn_multiplier", "count": 3}, "agent_use": True, "require_worker": "w4"}]

            out, err = await call(client, "game_mod_ops", {"session_id": "w4-def"})
            assert not err and out["tool"] == "re_mods" and out["ops"]["spawn_multiplier"]["params"]["count"] == "factor 1 .. 8"
            out, err = await call(client, "game_mod_ops", {})
            assert not err and set(out) == {"re5_mods", "re_mods"} and out["re5_mods"]["ops"]["mines"]["retained"]

            out, err = await call(client, "bot_strategy", {"session_id": "w5-abc"})
            assert not err and out["host"] == "JAYBUILTFINALE" and out["mercmode_current"] == {"enabled": False, "titles": ["re4", "re5", "re6"]}
            assert "kill_time" in out["options"]["mods"]["ops"] and "re5_policy" in out["options"]["not_settable"]
            out, err = await call(client, "bot_strategy", {"session_id": "w5-abc", "settings": {
                "mods": [{"op": "kill_time", "on": True, "multiplier": 10}], "mercmode": {"enabled": True, "titles": ["re5"]},
                "team": {"role": "solo_p1", "training_profile": "assisted"}}})
            assert not err and [x["kind"] for x in out["applied"]] == ["mod", "mercmode", "team"]
            assert out["applied"][0]["job"]["state"] == "succeeded" and out["applied"][1]["desired_settings"] == {"enabled": True, "titles": ["re5"]}
            assert posted[-2:] == [("/api/mercmode", {"host": "JAYBUILTFINALE", "enabled": True, "titles": ["re5"]}),
                                   ("/api/jobs", {"tool": "mercs_team", "input": {"session_id": "w5-abc", "op": "configure", "role": "solo_p1",
                                                                                   "training_profile": "assisted"}, "agent_use": True, "require_worker": "w5"})]
            out, err = await call(client, "bot_strategy", {"session_id": "w5-abc", "settings": {"mods": [{"op": "add_time", "multiplier": 60}]}})
            assert err and "Apply it once with game_mod" in out["error"]

            out, err = await call(client, "spawn_enemies", {"session_id": "w5-abc", "enemy": "Executioner", "count": 2})
            assert not err and out["supported"] is False and out["ticket"] == 3900 and "No verified spawn address" in out["reason"]
            assert [r["number"] for r in out["requests"]] == [3901, 3900, 3889]
            assert out["requested"] == {"session_id": "w5-abc", "enemy": "Executioner", "count": 2}
            out, err = await call(client, "spawn_enemies", {"session_id": "w4-def"})
            assert not err and out["ticket"] == 3901
            out, err = await call(client, "spawn_enemies", {})
            assert not err and out["ticket"] == 3901 and "job" not in out            # nothing was sent to a worker
    asyncio.run(check())
