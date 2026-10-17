"""#847: Ghidra Bridge, ReAgent loop and Ariane's in-game ops (gta_live), all exercised with fakes (no Ghidra, no LLM,
no emulator). Live checks are in docs/re_tool_integrations.md."""
import io
import json
import struct
import sys

import pytest

from gbox import agent, ghidra_bridge as gb, ghidra_bridge_server as srv, gta_live, re_agent
from gbox.ghidra_bridge_tool import GhidraBridgeIn, run as bridge_run
from gbox.registry import REGISTRY, Ctx, ToolUnavailable, execute

# --- a fake Ghidra Bridge server: the real protocol, canned program -----------------------------------------------------

FAKE_SERVER = r'''
import json, sys
prog = None
FUN = {"0x401000": {"address": "0x401000", "name": "CPed::Update", "signature": "void CPed::Update(CPed *this)",
       "decompiled": "void CPed::Update(CPed *this)\n{\n  if (this->health < 0) { Die(this); }\n  Move(this);\n}\n",
       "callers": [{"from": "0x402010", "type": "UNCONDITIONAL_CALL", "function": "CWorld::Process", "function_address": "0x402000"}],
       "callees": [{"address": "0x403000", "name": "Die"}, {"address": "0x404000", "name": "Move"}]}}
for line in sys.stdin:
    req = json.loads(line)
    op, a = req["op"], req.get("args") or {}
    try:
        if op == "crash":
            sys.exit(3)
        if op == "open":
            prog = {"name": "game.elf", "language": "MIPS:LE:32:default", "functions": 1, "args": a}
            res = prog
        elif prog is None:
            raise RuntimeError("no program open: call op=open first")
        elif op == "decompile":
            if a["target"] not in FUN:
                raise LookupError("no function at or containing " + a["target"])
            res = FUN[a["target"]]
        elif op == "functions":
            res = {"total": 1, "functions": [{"address": "0x401000", "name": "CPed::Update", "size": 64}]}
        elif op == "xrefs_to":
            res = {"target": a["target"], "xrefs": FUN["0x401000"]["callers"]}
        elif op == "xrefs_from":
            res = {"address": "0x401000", "name": "CPed::Update", "callees": FUN["0x401000"]["callees"], "data_refs": []}
        elif op == "run_script":
            res = {"script": a["script"], "stdout": "ran with " + " ".join(a["args"]), "stderr": "", "dirs": a["script_dirs"]}
        elif op == "close":
            prog, res = None, {"closed": True}
        else:
            res = {"op": op, "args": a}
        print(json.dumps({"id": req["id"], "result": res}), flush=True)
    except Exception as e:
        print(json.dumps({"id": req["id"], "error": type(e).__name__ + ": " + str(e)}), flush=True)
'''


@pytest.fixture
def bridge(cfg, tmp_path):
    script = tmp_path / "fake_bridge.py"
    script.write_text(FAKE_SERVER, encoding="utf-8")
    s = gb.Session(cfg, command=[sys.executable, "-I", str(script)])
    yield s
    s.stop()


def q(cfg, s, **kw):
    return bridge_run(GhidraBridgeIn(**kw), cfg, "w1", sess=s)


def test_bridge_lifecycle_queries_and_errors(cfg, bridge, tmp_path):
    assert q(cfg, bridge, op="status")["result"]["running"] is False
    with pytest.raises(ToolUnavailable):                      # nothing open and no export: say what to do
        q(cfg, bridge, op="decompile", target="0x401000")
    assert q(cfg, bridge, op="start")["result"]["running"] is True
    elf = tmp_path / "game.elf"
    elf.write_bytes(b"\x7fELF")
    opened = q(cfg, bridge, op="open", binary_path=str(elf), processor="MIPS:LE:32:default")
    assert opened["source"] == "live" and opened["result"]["args"]["processor"] == "MIPS:LE:32:default"
    assert opened["result"]["args"]["project_dir"].endswith("ghidra_bridge")    # gBox-owned project, not next to the game
    d = q(cfg, bridge, op="decompile", target="0x401000")["result"]
    assert d["name"] == "CPed::Update" and "Die(this)" in d["decompiled"] and len(d["callees"]) == 2
    assert q(cfg, bridge, op="xrefs_to", target="0x401000")["result"]["xrefs"][0]["function"] == "CWorld::Process"
    assert q(cfg, bridge, op="functions", query="CPed")["result"]["total"] == 1
    with pytest.raises(gb.BridgeError):                        # one bad request does not lose the open program
        q(cfg, bridge, op="decompile", target="0x999999")
    assert q(cfg, bridge, op="info")["source"] == "live"
    r = q(cfg, bridge, op="run_script", script="FindRefs.java", args=["0x401000"])["result"]
    assert r["stdout"] == "ran with 0x401000" and any(d.endswith("ghidra") for d in r["dirs"])
    st = q(cfg, bridge, op="status")["result"]
    assert st["running"] and st["open"]["program"]["name"] == "game.elf"
    assert q(cfg, bridge, op="stop")["result"]["stopped"] is True
    assert not bridge.running() and bridge.opened is None


def test_bridge_process_loss_is_reported_not_hidden(cfg, bridge, tmp_path):
    elf = tmp_path / "game.elf"
    elf.write_bytes(b"\x7fELF")
    q(cfg, bridge, op="open", binary_path=str(elf))
    with pytest.raises(RuntimeError, match="exited"):
        bridge.request("crash")
    assert bridge.opened is None
    with pytest.raises(ToolUnavailable):                       # the open program is gone: the caller must reopen
        q(cfg, bridge, op="decompile", target="0x401000")


def test_bridge_open_validates_inputs(cfg, bridge):
    with pytest.raises(ValueError, match="binary_path"):
        q(cfg, bridge, op="open")
    with pytest.raises(FileNotFoundError):
        q(cfg, bridge, op="open", binary_path="Z:/no/such/game.elf")
    with pytest.raises(ValueError, match="unknown op"):
        q(cfg, bridge, op="patch_bytes")


def test_server_loop_survives_errors():
    class Fake:
        def info(self):
            return {"name": "x"}

        def decompile(self, target):
            raise LookupError(f"no function {target}")
    out = io.StringIO()
    srv.serve(Fake(), io.StringIO('{"id":1,"op":"info"}\n{"id":2,"op":"decompile","args":{"target":"nope"}}\n'
                                  '{"id":3,"op":"rm_rf"}\n\n{"id":4,"op":"info"}\n'), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3, 4]
    assert replies[0]["result"] == {"name": "x"} and "LookupError" in replies[1]["error"]
    assert "unknown op" in replies[2]["error"] and replies[3]["result"] == {"name": "x"}


def write_export(d):
    d.mkdir()
    (d / "_index.json").write_text(json.dumps({"00401000": {"name": "CPed::Update", "address": "00401000", "num_callers": 1,
                                                            "num_callees": 2},
                                               "00402000": {"name": "CWorld::Process", "address": "00402000", "num_callers": 0,
                                                            "num_callees": 1}}))
    (d / "00401000.json").write_text(json.dumps({"address": "00401000", "name": "CPed::Update", "signature": "void f(void)",
                                                 "decompiled": "void f(void)\n{\n  Die();\n  Move();\n}\n",
                                                 "callers": [{"addr": "00402000", "name": "CWorld::Process", "ref_type": "CALL"}],
                                                 "callees": [{"addr": "00403000", "name": "Die"}, {"addr": "00404000", "name": "Move"}]}))
    (d / "_strings.json").write_text(json.dumps({"00500000": {"address": "00500000", "value": "PLAYER_WANTED", "type": "string",
                                                              "references": [{"func_addr": "00401000", "func_name": "CPed::Update",
                                                                              "ref_addr": "00401010"}]}}))
    return d


def test_export_backend_answers_like_the_live_bridge(tmp_path):
    e = gb.ExportBackend(write_export(tmp_path / "exp"))
    for t in ("0x401000", "401000", "00401000", "CPed::Update"):
        assert e.decompile(t)["name"] == "CPed::Update"
    assert e.decompile("0x401000")["callers"][0]["function_address"] == "0x402000"
    assert e.xrefs_from("0x401000")["callees"][1]["name"] == "Move"
    assert e.containing("0x401234")["function"]["name"] == "CPed::Update"
    assert e.strings("wanted")["strings"][0]["references"][0]["function"] == "CPed::Update"
    assert e.functions(query="world")["functions"][0]["callers"] == 0
    with pytest.raises(LookupError):
        e.decompile("0x999")
    with pytest.raises(FileNotFoundError):
        gb.ExportBackend(tmp_path)


def test_registered_tool_runs_over_an_export(cfg, tmp_path):
    exp = write_export(tmp_path / "exp")
    ctx = Ctx(cfg)
    out = execute("ghidra_bridge", {"op": "decompile", "target": "0x401000", "export_dir": str(exp)}, ctx)
    assert out["source"] == "export" and out["result"]["name"] == "CPed::Update"
    assert ctx.artifacts[0][0] == "ghidra_bridge.json"


def test_unavailable_names_the_fix(cfg, tmp_path, monkeypatch):
    monkeypatch.delenv("GHIDRA_INSTALL_DIR", raising=False)
    assert "ghidra_home" in gb.unavailable(cfg)
    home = tmp_path / "ghidra_12.1.4_PUBLIC"
    (home / "Ghidra" / "Features" / "PyGhidra" / "pypkg" / "dist").mkdir(parents=True)
    cfg.ghidra_home = str(home)
    monkeypatch.setattr(gb, "pyghidra_version", lambda py: None)
    assert "ghidra-bridge-install" in gb.unavailable(cfg)
    monkeypatch.setattr(gb, "pyghidra_version", lambda py: "3.1.0")
    assert gb.unavailable(cfg) is None


# --- ReAgent loop ----------------------------------------------------------------------------------------------------------

DECOMP = {"address": "0x401000", "name": "CPed::Update",
          "decompiled": "void CPed::Update(CPed *this)\n{\n  if (this->health < 0) {\n    Die(this);\n  }\n  Move(this);\n}\n",
          "callers": [{"function": "CWorld::Process"}], "callees": [{"address": "0x403000", "name": "Die"},
                                                                    {"address": "0x404000", "name": "Move"}]}
GOOD = "```cpp\nvoid CPed::Update() {\n  if (m_fHealth < 0) {\n    Die();\n  }\n  Move();\n}\n```\nREVERSED_FUNCTION: CPed::Update (0x401000)"
BAD = "```cpp\nvoid CPed::Update() {\n  Move();\n}\n```"


def fake_query(log):
    def query(op, **args):
        log.append((op, args))
        if op == "decompile":
            return DECOMP if args["target"] in ("0x401000", "CPed::Update") else dict(DECOMP, address=args["target"], name="Die")
        if op == "xrefs_to":
            return {"xrefs": [{"function_address": "0x402000"}, {"function_address": "0x402100"}] if args["target"] == "0x401000" else []}
        if op == "xrefs_from":
            return {"callees": [{"address": "0x403000"}] if args["target"] == "0x401000" else []}
        if op == "functions":
            return {"functions": [{"address": "0x401000", "name": "CPed::Update"}, {"address": "0x403000", "name": "CPed::Die"}]}
        return {}
    return query


def scripted(*replies):
    seen = []

    def llm(messages):
        seen.append(messages)
        return replies[len(seen) - 1]
    llm.seen = seen
    return llm


def test_verdict_code_and_action_parsing():
    assert re_agent.parse_verdict('{"verdict":"pass","summary":"ok","issues":[],"fix_instructions":[]}')["verdict"] == "PASS"
    v = re_agent.parse_verdict("VERDICT: FAIL\nSUMMARY: missing branch\nISSUES:\n- no health check\n- none\nFIX_INSTRUCTIONS:\n- add it\n")
    assert v == {"verdict": "FAIL", "summary": "missing branch", "issues": ["no health check"], "fix_instructions": ["add it"]}
    assert re_agent.parse_verdict("no idea")["verdict"] == "UNKNOWN"
    assert re_agent.extract_code(GOOD).startswith("void CPed::Update()")
    assert re_agent.parse_actions('{"actions":[{"tool":"decompile","target":"0x403000"},{"tool":"rm","target":"/"}]}') == \
        [{"tool": "decompile", "target": "0x403000"}]
    assert re_agent.parse_actions(GOOD) is None


def test_structural_verifier_is_conservative():
    assert re_agent.objective("", DECOMP["decompiled"], 2)["verdict"] == "FAIL"
    assert re_agent.objective(re_agent.extract_code(GOOD), DECOMP["decompiled"], 2)["verdict"] == "PASS"
    many = "void f(void)\n{\n  a(); b(); c(); d();\n  if (x) {} if (y) {} if (z) {}\n}"
    bad = re_agent.objective("void f() {\n  a();\n}", many, 4)
    assert bad["verdict"] == "FAIL" and len(bad["findings"]) == 2
    assert re_agent.objective("int f() { return 2; }", "int f(void)\n{\n  return 3;\n}", None)["verdict"] == "FAIL"


def test_pick_strategies():
    fns = [{"address": "0x1", "name": "a", "callers": 5}, {"address": "0x2", "name": "b", "callers": 1},
           {"address": "0x3", "name": "c", "callers": 3}]
    assert [f["name"] for f in re_agent.pick(fns, "high-impact")] == ["a", "c", "b"]
    assert [f["name"] for f in re_agent.pick(fns, "easiest-first", done=["0x2"])] == ["c", "a"]
    deps = {"0x2": ["0x1"], "0x1": ["0x3"], "0x3": []}
    assert [f["name"] for f in re_agent.pick(fns, "dependency-order", deps=lambda a: deps[a])] == ["c", "a", "b"]
    with pytest.raises(ValueError):
        re_agent.pick(fns, "random")


def test_loop_investigates_fixes_and_passes():
    log = []
    rev = scripted('{"actions":[{"tool":"decompile","target":"0x403000"}]}', BAD, GOOD)
    chk = scripted('{"verdict":"FAIL","summary":"health branch missing","issues":["no Die call"],"fix_instructions":["add the branch"]}',
                   '{"verdict":"PASS","summary":"matches","issues":[],"fix_instructions":[]}')
    r = re_agent.run_loop("0x401000", fake_query(log), rev, chk, max_rounds=4)
    assert r["success"] and r["rounds_used"] == 2 and r["investigations"] == 1 and r["llm_calls"] == 5
    assert ("decompile", {"target": "0x403000"}) in log                 # the reverser's evidence request was served
    assert "no Die call" in rev.seen[2][-1]["content"]                   # issues fed back into the fix round
    assert r["status"] == "hypothesis" and "Die();" in r["code"]


def test_loop_stops_on_repeat_and_budget():
    same = scripted(BAD, BAD, BAD, BAD)
    fail = '{"verdict":"FAIL","summary":"x","issues":["y"],"fix_instructions":[]}'
    r = re_agent.run_loop("0x401000", fake_query([]), same, scripted(fail, fail, fail), max_rounds=4)
    assert not r["success"] and r["rounds_used"] == 2 and "identical" in r["stopped"]
    r = re_agent.run_loop("0x401000", fake_query([]), scripted(BAD, BAD), scripted(fail), max_llm_calls=3)
    assert "budget" in r["stopped"] and r["llm_calls"] == 3
    # the checker's PASS is vetoed by a strong structural mismatch (4 callees and 3 branches vs one call)
    big = dict(DECOMP, decompiled="void f(void)\n{\n  if (a) { b(); }\n  if (c) { d(); }\n  if (e) { g(); h(); }\n}\n",
               callees=[{"name": n} for n in "bdgh"])
    r = re_agent.run_loop("0x401000", lambda op, **a: big, scripted(BAD), scripted(
        '{"verdict":"PASS","summary":"ok","issues":[],"fix_instructions":[]}'), max_rounds=1)
    assert r["checker"]["verdict"] == "PASS" and r["objective"]["verdict"] == "FAIL" and not r["success"]


def test_re_agent_ops(cfg):
    query = fake_query([])
    picked = re_agent.run(re_agent.ReAgentIn(op="pick", strategy="high-impact"), cfg, query=query)
    assert picked["candidates"][0]["address"] == "0x401000" and picked["candidates"][0]["callers"] == 2
    dep = re_agent.run(re_agent.ReAgentIn(op="pick", strategy="dependency-order"), cfg, query=query)
    assert [c["address"] for c in dep["candidates"]] == ["0x403000", "0x401000"]
    v = re_agent.run(re_agent.ReAgentIn(op="verify", target="0x401000", code=re_agent.extract_code(GOOD)), cfg, query=query)
    assert v["objective"]["verdict"] == "PASS"
    c = re_agent.run(re_agent.ReAgentIn(op="check", target="0x401000", code="x"), cfg, query=query,
                     llm=scripted('{"verdict":"FAIL","summary":"wrong","issues":["all"],"fix_instructions":[]}'))
    assert c["checker"]["verdict"] == "FAIL"
    with pytest.raises(ToolUnavailable):                                # no llm_endpoints: say so, never fake a model
        re_agent.run(re_agent.ReAgentIn(op="reverse", target="0x401000"), cfg, query=query)
    assert "dependency-order" in re_agent.run(re_agent.ReAgentIn(), cfg, query=query)["strategies"]


# --- gta_live --------------------------------------------------------------------------------------------------------------

class FakeEE:
    """pcsx2_libretro-like EE RAM view (offset = native address)."""
    def __init__(self):
        self.ram = bytearray(0x800000)

    def read_memory(self, a, n):
        return bytes(self.ram[a:a + n])

    def write_memory(self, a, data):
        self.ram[a:a + len(data)] = data

    def w32(self, a, v):
        self.ram[a:a + 4] = struct.pack("<I", v)


PED, VEH, WANTED = 0x700000, 0x720000, 0x740000


def gta3_ram():
    ee = FakeEE()
    ee.w32(0x00510380, PED)                                     # CWorld::Players[0].m_pPed
    ee.ram[PED + 0x30:PED + 0x3C] = struct.pack("<3f", 100.0, -200.0, 10.0)
    ee.ram[PED + 0x2C0:PED + 0x2C4] = struct.pack("<f", 75.0)
    ee.w32(0x0041685C, 0x600000)                                 # vehicle pool: 4 slots, slot 0 used
    ee.ram[0x600000:0x60000C] = struct.pack("<3I", VEH, 0x601000, 4)
    ee.ram[0x601000:0x601004] = bytes([0x01, 0x80, 0x80, 0x80])
    ee.ram[VEH + 0x70:VEH + 0x72] = struct.pack("<h", 122)
    ee.ram[VEH + 0x30:VEH + 0x3C] = struct.pack("<3f", 1.0, 2.0, 3.0)
    ee.w32(0x00416858, 0x610000)                                 # ped pool: 2 slots, both used
    ee.ram[0x610000:0x61000C] = struct.pack("<3I", PED, 0x611000, 2)
    return ee


def symtab_elf():
    """A minimal PS2-style ELF: CClock/CWeather/CPools symbols + CPlayerPed::SetWantedLevel (lw a0, 0x53C(a0))."""
    syms = {"_6CClock.ms_nGameClockHours": 0x5F0000, "_6CClock.ms_nGameClockMinutes": 0x5F0001,
            "_8CWeather.OldWeatherType": 0x5F0010, "_8CWeather.NewWeatherType": 0x5F0012,
            "_8CWeather.ForcedWeatherType": 0x5F0014, "SetWantedLevel__10CPlayerPedi": 0x100010}
    strtab, entries = b"\0", b"\0" * 16
    for name, value in syms.items():
        entries += struct.pack("<3IBBH", len(strtab), value, 8, 0x12, 0, 1)
        strtab += name.encode() + b"\0"
    code = struct.pack("<4I", 0, 0, 0, 0) + struct.pack("<2I", 0x27BDFFF0, (0x23 << 26) | (4 << 21) | (4 << 16) | 0x53C)
    data = bytearray(0x800)
    data[0:16] = b"\x7fELF\x01\x01\x01" + b"\0" * 9
    struct.pack_into("<HHIIIIIHHHHHH", data, 16, 2, 8, 1, 0x100000, 52, 0x600, 0, 52, 32, 1, 40, 3, 0)
    struct.pack_into("<8I", data, 52, 1, 0x100, 0x100000, 0x100000, 0x100, 0x100, 5, 16)
    data[0x100:0x100 + len(code)] = code
    data[0x200:0x200 + len(entries)] = entries
    data[0x400:0x400 + len(strtab)] = strtab
    struct.pack_into("<10I", data, 0x600 + 40, 0, 2, 0, 0, 0x200, len(entries), 2, 0, 4, 16)
    struct.pack_into("<10I", data, 0x600 + 80, 0, 3, 0, 0, 0x400, len(strtab), 0, 0, 1, 0)
    return bytes(data)


def test_gta_live_detection_and_refusals():
    assert gta_live.detect("Grand Theft Auto III (USA)") == "gta3"
    assert gta_live.detect("Grand Theft Auto - Liberty City Stories") == "lcs"
    assert gta_live.detect("Grand Theft Auto - Vice City Stories (USA)") == "vcs"
    assert gta_live.detect("Grand Theft Auto: Vice City (USA)") == "vc"
    assert gta_live.detect(game_id="5eacc9f11d9a5956") == "vc"
    assert gta_live.detect(serial="slus-20062") == "gta3"
    with pytest.raises(ValueError, match="Definitive Edition"):
        gta_live.detect("Grand Theft Auto Vice City", game_id="1fd42f50b10252e6")
    with pytest.raises(ValueError, match="no gta_live table"):
        gta_live.detect("Grand Theft Auto V")
    for g in gta_live.GAMES.values():                           # every address names its source; none claims a live check
        assert all(f["source"] and f["live_checked"] is False for f in g["fields"].values())


def test_gta_live_player_vehicles_pools_teleport():
    ee = gta3_ram()
    title = "Grand Theft Auto III (USA)"
    p = gta_live.run(ee, title, "player")["result"]
    assert p["pos"] == [100.0, -200.0, 10.0] and p["health"] == 75.0 and p["in_vehicle"] is False
    v = gta_live.run(ee, title, "vehicles")["result"]
    assert v["vehicles"] == [{"slot": 0, "addr": hex(VEH), "model": 122, "pos": [1.0, 2.0, 3.0]}]
    pools = gta_live.run(ee, title, "pools")["result"]
    assert pools["veh"]["used"] == 1 and pools["ped"]["used"] == 2
    t = gta_live.run(ee, title, "teleport", x=5, y=6, z=7)
    assert t["result"]["pos"] == [5.0, 6.0, 7.0] and t["writes"][0]["before"] == struct.pack("<3f", 100, -200, 10).hex()
    ee.ram[PED + 0x358] = 1                                      # in a car: the car moves with the player
    ee.w32(PED + 0x354, VEH)
    assert gta_live.run(ee, title, "teleport", x=9, y=9, z=9)["result"]["moved"] == hex(VEH)
    assert gta_live.run(ee, title, "player")["result"]["vehicle"]["pos"] == [9.0, 9.0, 9.0]


def test_gta_live_unmapped_fields_say_how_to_map_them(cfg):
    ee = gta3_ram()
    with pytest.raises(gta_live.Unmapped, match="memory_search"):
        gta_live.run(ee, "Grand Theft Auto III", "weather", cfg, value="rainy")
    with pytest.raises(gta_live.Unmapped):
        gta_live.run(ee, "Vice City Stories", "player", cfg)
    with pytest.raises(gta_live.Unmapped, match="spawn"):
        gta_live.run(ee, "Liberty City Stories", "spawn", cfg, model=130)


def test_gta_live_resolve_then_weather_time_wanted(cfg, tmp_path):
    elf = tmp_path / "SLUS_200.62"
    elf.write_bytes(symtab_elf())
    title = "Grand Theft Auto III (USA)"
    ee = gta3_ram()
    r = gta_live.run(ee, title, "resolve", cfg, elf_path=str(elf))
    assert r["found"]["clock_hours"]["addr"] == 0x5F0000 and r["found"]["off_wanted_ptr"]["addr"] == 0x53C
    assert "CPools::ms_pObjectPool" in r["missing"] and r["found"]["weather_forced"]["live_checked"] is False
    assert gta_live.table(cfg, "gta3")["players"]["source"].startswith("gbox/gta_games.py")   # curated table wins
    w = gta_live.run(ee, title, "weather", cfg, value="rainy")
    assert w["result"]["forced"] == w["result"]["old"] == w["result"]["new"] == "rainy" and len(w["writes"]) == 3
    assert gta_live.run(ee, title, "weather", cfg, value="release")["result"]["forced"] == "released"
    with pytest.raises(ValueError):
        gta_live.run(ee, title, "weather", cfg, value="hurricane")      # a Vice City weather, not GTA III's
    assert gta_live.run(ee, title, "time", cfg, hours=21, minutes=30)["result"]["clock"] == "21:30"
    with pytest.raises(ValueError):
        gta_live.run(ee, title, "time", cfg, hours=24)
    ee.w32(PED + 0x53C, WANTED)
    wanted = gta_live.run(ee, title, "wanted", cfg, level=4)
    assert wanted["result"]["level"] == 4 and wanted["result"]["chaos"] == 1220
    assert gta_live.run(ee, title, "player", cfg)["result"]["wanted"]["level"] == 4
    assert wanted["provenance"]["off_wanted_ptr"]["source"].startswith("the game's ELF")


def test_gta_live_registered_and_games_listing(cfg):
    out = execute("gta_live", {"session_id": "w-1", "op": "games"}, Ctx(cfg))
    assert set(out["result"]["games"]) == {"gta3", "lcs", "vc", "vcs"} and "1fd42f50b10252e6" in out["result"]["unsupported"]
    assert REGISTRY["gta_live"].permissions[-1].value == "memory_write"


# --- agent wiring ----------------------------------------------------------------------------------------------------------

def test_agent_specs_and_worker_pinning(monkeypatch):
    names = {t["function"]["name"] for t in agent.tool_specs()}
    assert {"gta_live", "ghidra_bridge", "re_agent"} <= names
    assert "gta_live" in agent.WORKER_TOOLS and "gta_live" in agent.MODIFIES
    assert not agent._modifies_game("gta_live", {"op": "player"})
    assert not agent._modifies_game("gta_live", {"op": "time"})
    assert agent._modifies_game("gta_live", {"op": "time", "hours": 6})
    assert agent._modifies_game("gta_live", {"op": "teleport"})
    a = agent.Agent.__new__(agent.Agent)
    calls = []

    def job(tool, inp, node=None, limit=900, worker=None):
        calls.append((tool, inp, worker))
        return {"state": "succeeded", "worker_id": "pc-7", "output": {"result": {"ok": True}}}
    monkeypatch.setattr(a, "_job", job, raising=False)
    a.ghidra_bridge(op="open", binary_path="/x/game.elf", query="")
    a.re_agent(op="reverse", target="0x401000")
    assert calls[0][1] == {"op": "open", "binary_path": "/x/game.elf"} and calls[0][2] is None
    assert calls[1][0] == "re_agent" and calls[1][2] == "pc-7"          # same worker as the open program
