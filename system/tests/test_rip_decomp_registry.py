"""#443 / #90: ninja_ripper, decomp_me, ida and n64recomp are registry tools (so MCP lists them as job_<name>), the
in-app agent offers them with matching methods, and their permissions are ones the deployed gBox grants."""
import inspect

from gbox import agent, registry, tools
from gbox.config import Config
from gbox.models import Permission as P

NEW = ("ninja_ripper", "decomp_me", "ida", "n64recomp")


def _spec(name):
    return next(t["function"] for t in agent.tool_specs() if t["function"]["name"] == name)


def test_modules_load_and_register_the_tools():
    assert {"ninja_ripper", "decomp_tools"} <= set(tools._load_tool_modules.__defaults__[0])
    tools._load_tool_modules(("ninja_ripper", "decomp_tools"))
    assert not {k: v for k, v in tools.LOAD_ERRORS.items() if k in ("ninja_ripper", "decomp_tools")}
    for n in NEW:
        assert n in registry.REGISTRY, n
    assert "decompme" not in registry.REGISTRY and "ida_pro" not in registry.REGISTRY   # the PR #154 names are replaced


def test_permissions_are_granted_by_the_deployed_config():
    granted = {"read", "execute", "stage", "network", "install", "memory_write"}       # gbox.toml granted_permissions
    for n in NEW:
        t = registry.REGISTRY[n]
        assert {str(p) for p in t.permissions} <= granted, (n, t.permissions)
        assert P.FILE_MUTATION not in t.permissions and P.INSTALL not in t.permissions
    assert P.NETWORK in registry.REGISTRY["decomp_me"].permissions
    assert registry.REGISTRY["ninja_ripper"].platforms == ["windows"]


def test_check_hooks_name_the_missing_program(tmp_path, monkeypatch):
    from gbox import decomp_tools as dt, ninja_ripper as nr
    monkeypatch.setattr(nr, "search_roots", lambda cfg: [])
    monkeypatch.setattr(dt, "ida_search_roots", lambda cfg: [])
    monkeypatch.setattr(dt.shutil, "which", lambda n: None)
    for v in ("NINJA_RIPPER_HOME", "IDA_HOME", "IDADIR", "N64RECOMP"):
        monkeypatch.delenv(v, raising=False)
    nr._FOUND.clear()
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(dt, "find_n64recomp", lambda c: None)
    assert "NinjaRipper" in (registry.REGISTRY["ninja_ripper"].check(cfg) or "Windows")
    assert "IDA Pro is not installed" in registry.REGISTRY["ida"].check(cfg)
    assert "N64Recomp is not installed" in registry.REGISTRY["n64recomp"].check(cfg)
    assert registry.REGISTRY["decomp_me"].check is None                    # always listed; network is opt-in per call


def test_agent_offers_each_tool_with_a_method_that_takes_its_parameters():
    for n in NEW:
        spec = _spec(n)
        params = set(inspect.signature(getattr(agent.Agent, n)).parameters) - {"self"}
        assert set(spec["parameters"]["properties"]) <= params, (n, set(spec["parameters"]["properties"]) - params)
        assert set(spec["parameters"]["required"]) <= params
    assert "PUBLIC" in _spec("decomp_me")["description"] and "dry_run" in _spec("decomp_me")["description"]
    assert "operator" in _spec("ninja_ripper")["description"]


def test_system_prompt_routes_ripping_and_decomp_work():
    s = agent.SYSTEM
    assert "ninja_ripper op=launch" in s and "op=import" in s and "RenderDoc can't" in s
    assert "n64recomp op=run" in s and "ida (IDA Pro headless" in s and "decomp_me" in s and "opt-in" in s


def test_ninja_import_stores_the_glb_in_the_collection_on_the_spark():
    a = object.__new__(agent.Agent)
    sent = []

    def job(tool, inp, node=None, limit=900, worker=None):
        sent.append((tool, inp.get("op"), node, worker))
        if tool == "ninja_ripper":
            return {"state": "succeeded", "worker_id": "pc2", "output": {"op": "import", "result": {"glb": "ab" * 32}}}
        return {"state": "succeeded", "output": {"result": {"status": "added", "entry": {"slug": "crate"}}}}
    a._job = job
    r = a.ninja_ripper(op="import", worker="pc2", name="crate", kind="object")
    assert r["collection"]["status"] == "added" and r["worker"] == "pc2"
    assert sent == [("ninja_ripper", "import", None, "pc2"), ("characters", "add", "linux", None)]


def test_ninja_launch_goes_to_an_idle_background_testing_pc():
    a = object.__new__(agent.Agent)
    sent = []
    a._job = lambda tool, inp, node=None, limit=900, worker=None: sent.append((node, worker)) or {
        "state": "succeeded", "worker_id": "pc2", "output": {"result": {"pid": 9}}}
    assert a.ninja_ripper(op="launch", exe="C:/Games/x.exe") == {"pid": 9, "worker": "pc2"}
    assert sent == [(None, "idle")]
    a.ninja_ripper(op="rip", session_id="pc3-abc")
    assert sent[-1] == (None, "pc3")


def test_decomp_me_agent_call_stays_dry_unless_told_otherwise():
    a = object.__new__(agent.Agent)
    seen = []
    a._job = lambda tool, inp, node=None, limit=900, worker=None: seen.append(inp) or {"state": "succeeded", "output": {"ok": 1}}
    a.decomp_me(op="fetch", slug="abc")
    a.decomp_me(op="fetch", slug="abc", dry_run=False)
    assert [s["dry_run"] for s in seen] == [True, False]
