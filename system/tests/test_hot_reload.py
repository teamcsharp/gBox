"""Bot hot reload (gbox/hot_reload.py, docs/hot-update.md): a bot-only deploy reloads the bot modules in the running
worker - the games keep running, each autobot stops (inputs released), the modules reload in dependency order and the
bot starts again with the same input and job - instead of restarting gbox.service.

Operator 2026-10-26: "Every time I look at the system, it's loading the game. Instead of playing the game, it's always
loading the game. I'm trying to reduce loading to be as short as possible to not at all."

The fake bot modules live in a throwaway package on disk (importlib.reload needs real files); the allow-list is swapped
for one naming that package.
"""
import os
import sys
import threading
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from gbox import bot_control as B, hot_reload as H, screensaver as S
from gbox.models import Job
from gbox.store import Store

HELPER = "SPEED = 1\n\n\ndef speed():\n    return SPEED\n"


@pytest.mark.parametrize('name', ['re4_gc_native', 're5_switch_native', 're6_switch_native'])
def test_native_controller_locks_require_process_restart(name):
    assert not H.allowed('gbox.mercs.titles.' + name)
    assert H.classify(['gbox/mercs/titles/' + name + '.py'])['action'] == 'restart'


BOT = "from .helper import speed\n\nVERSION = 'v1'\n\n\ndef tick():\n    return (VERSION, speed())\n"
MENUS = ("class Roster:\n    def __init__(self):\n        self.played = {}\n\n    def label(self):\n        return 'old'\n\n\n"
         "ROSTER = Roster()\n")
COV = ("class Cov:\n    def who(self):\n        return 'old'\n\n\n_C = None\n\n\ndef get():\n    global _C\n"
       "    if _C is None:\n        _C = Cov()\n    return _C\n")
PLAYBOOK = '''"""Fake Mercenaries playbook: presses A every tick, says which code plays."""
import time

VERSION = 'v1'


def matches(ad, g):
    return True


def setup(ad):
    return []


def play(ad, send, stopped, stats=None, **_kw):
    stats = stats if stats is not None else {}
    while not stopped():
        stats['version'] = VERSION
        send([{'key': 'a', 'down': True}])
        time.sleep(0.01)
    return stats
'''


class Pkg:
    def __init__(self, root):
        self.name = f"hrfake_{uuid.uuid4().hex[:8]}"
        self.dir = root / self.name
        self.dir.mkdir()
        for fname, text in (("__init__.py", ""), ("helper.py", HELPER), ("bot.py", BOT), ("menus.py", MENUS),
                            ("cov.py", COV), ("playbook.py", PLAYBOOK)):
            (self.dir / fname).write_text(text, encoding="utf-8")
        sys.path.insert(0, str(root))
        import importlib
        for m in ("helper", "bot", "menus", "cov", "playbook"):
            importlib.import_module(f"{self.name}.{m}")

    def m(self, short):
        return f"{self.name}.{short}"

    def allowed(self, name):
        return name == self.name or name.startswith(self.name + ".")

    def write(self, fname, text):
        path = self.dir / fname
        path.write_text(text, encoding="utf-8")
        st = path.stat()
        os.utime(path, (st.st_atime + 5, st.st_mtime + 5))      # never a same-second, same-size rewrite

    def registry(self):
        return {H._rel(n, H._source_path(sys.modules[n])): H._digest(H._source_path(sys.modules[n]).read_bytes())
                for n in list(sys.modules) if self.allowed(n) and H._source_path(sys.modules[n])}


@pytest.fixture
def pkg(tmp_path):
    p = Pkg(tmp_path)
    yield p
    for n in [n for n in sys.modules if p.allowed(n)]:
        sys.modules.pop(n, None)
    sys.path.remove(str(tmp_path))


def until(cond, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


class FakeHost:
    """Bots as threads calling module.tick() every few ms until stopped; records stop / release / start."""

    def __init__(self, module, sessions=("w1-a",)):
        self.module, self.events, self.prepare, self.lost = module, [], False, False
        self.runs = {sid: self._run(sid, object(), SimpleNamespace(job_id=f"J-{sid}")) for sid in sessions}

    def _run(self, sid, inp, ctx):
        run = {"sid": sid, "inp": inp, "ctx": ctx, "stopped": False, "ticks": [], "result": None}

        def go():
            mod = sys.modules[self.module]
            try:
                while not run["stopped"]:
                    run["ticks"].append(mod.tick())
                    time.sleep(0.005)
                run["result"] = {"ok": True}
            except Exception as exc:
                run["result"] = {"ok": False, "error": repr(exc)}
        run["thread"] = threading.Thread(target=go, daemon=True)
        run["thread"].start()
        return run

    def bots(self):
        return [(sid, r) for sid, r in self.runs.items() if r["thread"].is_alive() and not r["stopped"]]

    def busy(self):
        return "a MercMode round preparation is running on w1-p" if self.prepare else None

    def stop(self, sid, run):
        self.events.append(("stop", sid))
        run["stopped"] = True

    def join(self, run, timeout):
        run["thread"].join(timeout)
        return not run["thread"].is_alive()

    def release(self, sid):
        self.events.append(("release", sid))

    def playbook(self, sid):
        return None if self.lost else self.module

    def playbook_of(self, run):
        return self.module

    def start(self, sid, run, since):
        self.events.append(("start", sid))
        self.runs[sid] = self._run(sid, run["inp"], run["ctx"])
        return {"session_id": sid, "restarted": True, "job_id": run["ctx"].job_id}

    def start_later(self, sid, run, since):
        self.events.append(("start_later", sid))

    def crashed(self, sid):
        r = self.runs[sid]
        if not r["thread"].is_alive() and (r["result"] or {}).get("ok") is False:
            return r["result"]["error"]
        return None

    def stop_all(self):
        for r in self.runs.values():
            r["stopped"] = True
            r["thread"].join(2)


def reload(host, pkg, **kw):
    kw.setdefault("allowed", pkg.allowed)
    kw.setdefault("registry", {})
    kw.setdefault("settle_s", 0.2)
    return H.reload_bots(host, **kw)


# --- the reload op ---------------------------------------------------------------------------------------------------------

def test_a_changed_bot_module_reloads_and_its_bot_restarts_with_the_same_input_and_job(pkg):
    host = FakeHost(pkg.m("bot"))
    before = host.runs["w1-a"]
    assert until(lambda: before["ticks"]) and before["ticks"][-1] == ("v1", 1)
    pkg.write("bot.py", BOT.replace("'v1'", "'v2'"))
    out = reload(host, pkg, modules=[pkg.m("bot")])
    try:
        assert out["ok"], out
        assert out["reloaded"] == [pkg.m("bot")] and out["restarted"][0]["restarted"]
        assert host.events == [("stop", "w1-a"), ("release", "w1-a"), ("start", "w1-a")], 'inputs released, then back'
        after = host.runs["w1-a"]
        assert after is not before and not before["thread"].is_alive()
        assert after["inp"] is before["inp"] and after["ctx"] is before["ctx"], "the same input and autoplay job"
        assert until(lambda: after["ticks"]) and after["ticks"][-1] == ("v2", 1)
        assert H.verdict({"state": "succeeded", "result": out})[0] == "reloaded"
    finally:
        host.stop_all()


def test_only_changed_modules_and_their_importers_reload_dependencies_first(pkg):
    registry = pkg.registry()                         # what the worker loaded (its build_sources)
    host = FakeHost(pkg.m("bot"))
    pkg.write("helper.py", HELPER.replace("SPEED = 1", "SPEED = 7"))
    p = H.plan(allowed=pkg.allowed, registry=registry)
    assert p.names == [pkg.m("helper"), pkg.m("bot")], "bot bound speed() from helper at import: it reloads after it"
    assert p.why[pkg.m("bot")].startswith("binds names from") and pkg.m("menus") not in p.why
    out = reload(host, pkg, registry=registry)
    try:
        assert out["ok"] and out["reloaded"] == p.names, out
        assert until(lambda: host.runs["w1-a"]["ticks"]) and host.runs["w1-a"]["ticks"][-1] == ("v1", 7)
        assert registry[f"{pkg.name}/helper.py"] == H._digest((pkg.dir / "helper.py").read_bytes()), 'now loaded'
        assert H.plan(allowed=pkg.allowed, registry=registry).names == [], "nothing left to reload"
    finally:
        host.stop_all()


def test_staged_imports_see_this_reloads_new_names(pkg):
    host = FakeHost(pkg.m("bot"))
    pkg.write("helper.py", HELPER + "\nBOOST = 3\n")
    pkg.write("bot.py", "from .helper import speed, BOOST\n\nVERSION = 'v3'\n\n\ndef tick():\n"
                        "    return (VERSION, speed() * BOOST)\n")
    out = reload(host, pkg, modules=[pkg.m("bot"), pkg.m("helper")])
    try:
        assert out["ok"], out
        assert out["reloaded"] == [pkg.m("helper"), pkg.m("bot")]
        assert until(lambda: host.runs["w1-a"]["ticks"]) and host.runs["w1-a"]["ticks"][-1] == ("v3", 3)
    finally:
        host.stop_all()


@pytest.mark.parametrize("broken", ["def tick(:\n", "raise RuntimeError('boom at import')\n",
                                    "from .helper import missing_name\n"])
def test_a_bot_module_that_does_not_import_is_refused_and_the_old_bot_keeps_driving(pkg, broken):
    host = FakeHost(pkg.m("bot"))
    run = host.runs["w1-a"]
    pkg.write("bot.py", broken)
    out = reload(host, pkg, modules=[pkg.m("bot")])
    try:
        assert not out["ok"] and not out["retry"] and not out["restart"], out
        assert "does not import" in out["reason"] and out["module"] == pkg.m("bot")
        assert host.events == [], "the bot was never stopped: nothing released, nothing restarted"
        assert run["thread"].is_alive() and sys.modules[pkg.m("bot")].tick() == ("v1", 1)
        assert H.verdict({"result": out})[0] == "refused"
    finally:
        host.stop_all()


def test_a_reload_that_fails_after_staging_restores_every_module_and_restarts_the_bots(pkg, monkeypatch):
    host = FakeHost(pkg.m("bot"))
    pkg.write("helper.py", HELPER.replace("SPEED = 1", "SPEED = 9"))
    pkg.write("bot.py", BOT.replace("'v1'", "'v2'"))
    real = H.importlib.reload

    def flaky(mod):
        if mod.__name__ == pkg.m("bot"):
            raise OSError("disk went away")
        return real(mod)
    monkeypatch.setattr(H.importlib, "reload", flaky)
    out = reload(host, pkg, modules=[pkg.m("helper"), pkg.m("bot")])
    try:
        assert not out["ok"] and "failed to reload" in out["reason"], out
        assert sys.modules[pkg.m("helper")].SPEED == 1, "helper (reloaded first) is back as it was"
        assert host.events == [("stop", "w1-a"), ("release", "w1-a"), ("start", "w1-a")]
        assert until(lambda: host.runs["w1-a"]["ticks"]) and host.runs["w1-a"]["ticks"][-1] == ("v1", 1)
    finally:
        host.stop_all()


def test_a_bot_that_dies_on_the_new_code_brings_the_old_modules_back(pkg):
    registry = pkg.registry()
    host = FakeHost(pkg.m("bot"))
    pkg.write("bot.py", BOT.replace("return (VERSION, speed())", "raise NameError('a typo only a round finds')"))
    out = reload(host, pkg, registry=registry, settle_s=3)
    try:
        assert not out["ok"] and out["rolled_back"], out
        assert "old bot modules are back" in out["reason"] and "a typo" in out["reason"]
        assert sys.modules[pkg.m("bot")].tick() == ("v1", 1)
        assert until(lambda: host.runs["w1-a"]["ticks"]) and host.runs["w1-a"]["ticks"][-1] == ("v1", 1)
        assert host.runs["w1-a"]["thread"].is_alive(), "the game has its bot again"
        assert registry[f"{pkg.name}/bot.py"] != H._digest((pkg.dir / "bot.py").read_bytes()), "not recorded as loaded"
        assert H.verdict({"result": out})[0] == "refused"
    finally:
        host.stop_all()


def test_new_code_that_no_longer_matches_its_game_is_rolled_back(pkg):
    host = FakeHost(pkg.m("bot"))
    host.lost = True
    pkg.write("bot.py", BOT.replace("'v1'", "'v2'"))
    out = reload(host, pkg, modules=[pkg.m("bot")])
    try:
        assert not out["ok"] and "no bot playbook takes" in out["reason"], out
        assert sys.modules[pkg.m("bot")].VERSION == "v1"
        assert until(lambda: host.runs["w1-a"]["ticks"]) and host.runs["w1-a"]["ticks"][-1] == ("v1", 1)
    finally:
        host.stop_all()


def test_kept_state_survives_with_the_new_classes(pkg):
    menus, cov = sys.modules[pkg.m("menus")], sys.modules[pkg.m("cov")]
    menus.ROSTER.played["Chris (BSAA)"] = 3
    cov.get()
    old_cov = cov._C
    pkg.write("menus.py", MENUS.replace("return 'old'", "return 'new'"))
    pkg.write("cov.py", COV.replace("return 'old'", "return 'new'"))
    host = FakeHost(pkg.m("bot"), sessions=())
    out = reload(host, pkg, modules=[pkg.m("menus"), pkg.m("cov")],
                 keep={pkg.m("menus"): ("ROSTER",), pkg.m("cov"): ("_C",)})
    assert out["ok"], out
    assert menus.ROSTER.label() == "new" and menus.ROSTER.played == {"Chris (BSAA)": 3}, "the new code, the old data"
    assert type(menus.ROSTER) is menus.Roster
    assert cov._C is old_cov and type(cov._C) is cov.Cov and cov._C.who() == "new", "a lazy singleton: kept, new class"


def test_a_rollback_gives_kept_objects_their_old_classes_back(pkg):
    cov = sys.modules[pkg.m("cov")]
    kept = cov.get()
    old_cls = type(kept)
    pkg.write("cov.py", COV.replace("return 'old'", "return 'new'"))
    p = H.plan([pkg.m("cov")], allowed=pkg.allowed, registry={})
    done = H.swap(p, keep={pkg.m("cov"): ("_C",)})
    assert kept.who() == "new" and done.rebound == ((kept, old_cls),)
    H.restore(done)
    assert type(kept) is old_cls and kept.who() == "old" and cov.Cov is old_cls and cov._C is kept


def test_a_round_preparation_makes_the_reload_wait_then_answer_busy_with_nothing_changed(pkg):
    host = FakeHost(pkg.m("bot"))
    host.prepare = True
    pkg.write("bot.py", BOT.replace("'v1'", "'v2'"))
    out = reload(host, pkg, modules=[pkg.m("bot")], drain_s=0.2, sleep=lambda s: time.sleep(0.01))
    try:
        assert out["retry"] and not out["ok"] and "round preparation" in out["reason"], out
        assert host.events == [] and sys.modules[pkg.m("bot")].VERSION == "v1"
        assert H.verdict({"result": out})[0] == "busy"
    finally:
        host.stop_all()


def test_only_bot_modules_reload_in_place(pkg):
    host = FakeHost(pkg.m("bot"), sessions=())
    out = reload(host, pkg, modules=["gbox.server"])
    assert not out["ok"] and out["restart"] and "not bot modules" in out["reason"]
    assert H.verdict({"result": out})[0] == "failed", "the deploy falls back to the service restart"
    pkg.write("plane.py", "from .bot import tick\n")
    __import__(pkg.m("plane"))
    out = reload(host, pkg, modules=[pkg.m("bot")], allowed=lambda n: pkg.allowed(n) and not n.endswith(".plane"))
    assert out["restart"] and pkg.m("plane") in out["reason"], "a non-bot module holding bot names: restart only"


def test_nothing_changed_is_a_no_op(pkg):
    host = FakeHost(pkg.m("bot"))
    try:
        out = reload(host, pkg, registry=pkg.registry())
        assert out["ok"] and out["reloaded"] == [] and host.events == []
        out = reload(host, pkg, modules=["hrfake_never_loaded.bot"], allowed=lambda n: True)
        assert out["ok"] and out["not_loaded"] == ["hrfake_never_loaded.bot"]
    finally:
        host.stop_all()


def test_starts_wait_for_a_reload_and_the_reloads_own_restarts_go_through():
    gate = H.Gate()
    seen = []
    with gate.exclusive(1) as got:
        assert got and gate.reloading
        with gate.start():
            seen.append("own restart")

        def other():
            try:
                with gate.start(timeout=0.1):
                    seen.append("other started")
            except RuntimeError as exc:
                seen.append(str(exc))
        t = threading.Thread(target=other)
        t.start()
        t.join()
    assert seen[0] == "own restart" and "bot reload is still running" in seen[1]
    with gate.start():
        with gate.exclusive(0.05) as got:
            assert not got, "a start still setting up keeps the reload out"
    with gate.exclusive(0.05) as got:
        assert got


@pytest.mark.parametrize("paths,action", [
    (["gbox/mercs/titles/re5_combat.py", "gbox/mercs/titles/re5_ps3.py", "docs/hot-update.md"], "reload"),
    (["gbox/re4_merc_bot.py", "gbox/re4_threats.py", "gbox/re4_menus.py", "gbox/mercs_bot.py"], "reload"),
    (["system/gbox/mercs/round_map.py", "gbox\\mercs\\stalemate.py"], "reload"),
    (["gbox/mercs/titles/re5_combat.py", "gbox/screensaver.py"], "restart"),
    (["gbox/server.py"], "restart"), (["gbox/hot_reload.py"], "restart"), (["gbox/tools.py"], "restart"),
    (["gbox/mercs/warm_boot.py"], "restart"), (["gbox/re5_mods_tool.py"], "restart"),
    (["gbox/mercs/titles/re5_switch_native.py"], "restart"),
    (["gbox/mercs/titles/re6_switch_native.py"], "restart"),
    (["profiles/gamedata/BLUS30491-ram.json"], "restart"), (["adapters/x.py"], "restart"), (["gbox.toml"], "restart"),
    (["gbox/mercs/notes.json"], "restart"), (["hermes/gbox/SKILL.md"], "restart"),
    (["docs/hot-update.md", "clients/desktop/app.js", "tests/test_hot_reload.py"], "none"),
    ([], "none"),
])
def test_deploy_classification_reloads_only_a_pure_bot_change(paths, action):
    out = H.classify(paths)
    assert out["action"] == action, out
    if action == "restart":
        assert out["other"]


def test_the_classifier_command_prints_the_action(capsys):
    assert H.main(["classify", "gbox/mercs/titles/re5_combat.py"]) == 0
    assert capsys.readouterr().out.strip() == "reload"
    assert H.main(["classify", "gbox/mercs/titles/re5_combat.py", "gbox/server.py"]) == 0
    assert capsys.readouterr().out.strip() == "restart"


@pytest.mark.parametrize("answer,kind", [
    ({"state": "succeeded", "result": {"ok": True, "reason": "1 bot module(s) reloaded"}}, "reloaded"),
    ({"result": {"ok": False, "retry": True, "reason": "a MercMode round preparation is running"}}, "busy"),
    ({"result": {"ok": False, "reason": "gbox.mercs_bot does not import: SyntaxError"}}, "refused"),
    ({"result": {"ok": False, "restart": True, "reason": "not bot modules"}}, "failed"),
    ({"detail": "lilspark is offline: its bots can't be reloaded now."}, "failed"),
    (None, "failed"),
])
def test_the_deploy_reads_the_routes_answer(answer, kind):
    assert H.verdict(answer)[0] == kind


def test_a_standalone_launch_records_what_re_adoption_needs(tmp_path, monkeypatch):
    """docs/hot-update.md part 2: the emulator pid, its Xvfb display and that display's pid, the debug port."""
    from gbox import adapters, memory_card_sessions, provision
    from gbox.config import Config

    class Emu(adapters.StandaloneAdapter):
        name = "fakeemu"

        def _ensure(self):
            pass

        def _argv(self, rom):
            return ["fakeemu", rom]

        def _debugger(self):
            return object()
    monkeypatch.setattr(adapters, "HOST_OS", "linux")
    monkeypatch.setattr(adapters, "Display", lambda w, h: SimpleNamespace(name=":97", w=w, h=h, close=lambda: None,
                                                                         proc=SimpleNamespace(pid=4321)))
    monkeypatch.setattr(adapters.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=1234, poll=lambda: None))
    monkeypatch.setattr(provision, "linux_audio_env", lambda *a, **k: {})
    monkeypatch.setattr(memory_card_sessions, "launched", lambda ad: None)
    ad = Emu(Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache"), "gamecube")
    d = ad.launch_game("game.iso")
    assert (d["pid"], d["display"], d["display_pid"], d["debug_port"]) == (1234, ":97", 4321, ad.port)


def test_the_allow_list_is_bot_logic_only():
    for name in ("gbox.mercs_bot", "gbox.re4_merc_bot", "gbox.re4_threats", "gbox.re4_menus",
                 "gbox.mercs.titles.re5_ps3", "gbox.mercs.titles.re5_combat", "gbox.mercs.engine", "gbox.mercs"):
        assert H.allowed(name), name
    for name in ("gbox.tools", "gbox.server", "gbox.store", "gbox.adapters", "gbox.screensaver", "gbox.hot_reload",
                 "gbox.mercs.warm_boot", "gbox.mercs.directives", "gbox.mercs.damage", "gbox.mercs.teamplay",
                 "gbox.re5_mods_tool", "gbox.mercmode", "gbox.mercsx"):
        assert not H.allowed(name), name


def test_the_real_allow_list_holds_no_module_with_names_bound_by_a_non_bot_module():
    """Every real bot module can reload: no non-bot gbox module imported it with `from bot import name` at import
    time (which would keep the old objects and refuse every reload of it)."""
    import importlib
    import pkgutil
    import gbox.mercs
    for name in ("gbox.server", "gbox.tools", "gbox.screensaver", "gbox.mercmode", "gbox.coaching", "gbox.worker",
                 "gbox.mercs_team_tool", "gbox.re5_mods_tool", "gbox.re_mods_tool"):
        importlib.import_module(name)                  # the non-bot modules that use the bots
    names = [m.name for m in pkgutil.walk_packages(gbox.mercs.__path__, "gbox.mercs.")] + sorted(H.BOT_MODULES)
    for name in names:
        if H.allowed(name):
            importlib.import_module(name)
    for name in names:
        if H.allowed(name):
            bad = [b for b in H._binders(name) if not H.allowed(b)]
            assert not bad, f"{name} is bound by {bad}"


# --- the worker's host (gbox.tools) --------------------------------------------------------------------------------------

class FakeAdapter:
    name = "fake"
    supported = {"send_input"}

    def __init__(self):
        self.sent = []

    def send_input(self, rows):
        self.sent.extend(rows)
        return {"sent": len(rows)}


@pytest.fixture
def worker_bot(pkg, monkeypatch):
    """A MercMode autobot started through tools.autoplay on a fake game, its playbook from the fake package."""
    from gbox import tools
    from gbox.mercs import directives
    sid = "w1-merc"
    ad = FakeAdapter()
    posts = []
    monkeypatch.setitem(tools.SESSIONS, sid, (ad, {"game_id": "fake-merc", "title": "Fake Mercs",
                                                   "platform": "gamecube"}))
    monkeypatch.setattr(tools, "_playbook", lambda ad, g: sys.modules[pkg.m("playbook")])
    monkeypatch.setattr(tools, "_cursor", lambda: None)
    monkeypatch.setattr(tools.httpx, "post", lambda url, **kw: posts.append((url, kw))
                        or SimpleNamespace(status_code=200, json=lambda: {}, text=""))
    monkeypatch.setattr(directives, "poll_loop", lambda *a, **k: None)
    monkeypatch.setattr(H, "allowed", pkg.allowed)           # the tools host asks hot_reload.allowed
    ctx = SimpleNamespace(server="http://cp.test", job_id="J1", agent_use=True, config=None,
                          headers={"authorization": "Bearer t", "x-gbox-parent-job": "J1"})
    inp = tools.AutoplayIn(session_id=sid, op="start", mode="auto", screensaver=True, style={"pace": 1.0})
    assert tools.autoplay(inp, ctx)["result"]["mode"] == "playbook"
    run = tools.AUTOPLAY[sid]
    assert until(lambda: (run.get("live") or {}).get("version") == "v1")
    yield SimpleNamespace(tools=tools, sid=sid, ad=ad, posts=posts, ctx=ctx, inp=inp, pkg_bot=pkg.m("playbook"))
    cur = tools.AUTOPLAY.pop(sid, None)
    if cur:
        cur["driver"].stopped = True
        cur["thread"].join(2)
    tools._AUTOPLAY_STOPS.pop(sid, None)


def test_the_worker_reloads_a_mercmode_bot_in_place_and_mercmode_keeps_its_run(worker_bot, pkg, tmp_path):
    from gbox import mercmode
    t = worker_bot.tools
    old = t.AUTOPLAY[worker_bot.sid]
    old_telemetry = [th for th in threading.enumerate() if th.name == f"autoplay-telemetry-{worker_bot.sid}"]
    assert len(old_telemetry) == 1
    pkg.write("playbook.py", PLAYBOOK.replace("'v1'", "'v2'"))
    worker_bot.ad.sent.clear()
    out = H.reload_bots(t._RELOAD_HOST, modules=[pkg.m("playbook")], allowed=pkg.allowed, registry={}, settle_s=0.3)
    assert out["ok"], out
    old_telemetry[0].join(8)                          # its loop notices the old bot ended (it posts every 5 s)
    assert not old_telemetry[0].is_alive()
    new = t.AUTOPLAY[worker_bot.sid]
    assert new is not old and not old["thread"].is_alive() and new["thread"].is_alive()
    assert new["inp"] is worker_bot.inp and new["ctx"] is worker_bot.ctx, "the same AutoplayIn and job context"
    assert out["restarted"] == [{"session_id": worker_bot.sid, "restarted": True, "mission": "playbook: playbook",
                                 "mode": "playbook", "job_id": "J1"}]
    released = [r for r in worker_bot.ad.sent if r.get("down") is False]
    assert {"key": "a", "down": False} in released, "the stopped bot's keys were released before the restart"
    assert until(lambda: (new.get("live") or {}).get("version") == "v2"), "the new code plays"
    # the old run's telemetry never said "stopped" (the restarted bot reports on its own), always under job J1
    assert until(lambda: any(kw["json"].get("running") for url, kw in worker_bot.posts
                             if "/api/autoplay/telemetry/" in url and kw["json"].get("mode") == "playbook"))
    tele = [kw for url, kw in worker_bot.posts if "/api/autoplay/telemetry/" in url]
    assert not any(kw["json"]["running"] is False for kw in tele)
    assert {kw["json"]["source_autoplay_job_id"] for kw in tele} == {"J1"}
    assert {kw["headers"]["x-gbox-parent-job"] for kw in tele} == {"J1"}
    # MercMode accepts this bot's next native round boundary: its parent job is still the run's autoplay job
    store = Store(tmp_path / "store")
    try:
        now = time.time()
        store.put("job", "J1", {"id": "J1", "tool": "autoplay", "state": "succeeded", "created": now - 300,
                                "require_worker": "w1", "input": {"session_id": worker_bot.sid, "op": "start"}})
        run = {"session_id": worker_bot.sid, "worker_id": "w1", "autoplay_job": "J1", "mercmode": {"title": "re5"},
               "playing_since": now - 200}
        body = {"session_id": worker_bot.sid, "round_id": "a" * 32, "at": now, "map_id": "BLUS30491",
                "role": "solo_p1", "source": "native_terminal_reader",
                "witness": {"playing_observed": True, "player_verified": True, "screen": "dead", "hp": 0}}
        parent = store.get("job", new["ctx"].job_id)
        assert mercmode.accept_boundary(store, run, body, parent_job=parent, now=now)["round_id"] == "a" * 32
    finally:
        store.db.close()


def test_an_operator_stop_during_the_reload_is_never_undone(worker_bot):
    t = worker_bot.tools
    run = t.AUTOPLAY[worker_bot.sid]
    since = time.time()
    t._ReloadHost().stop(worker_bot.sid, run)
    run["thread"].join(2)
    t.autoplay(t.AutoplayIn(session_id=worker_bot.sid, op="stop"), worker_bot.ctx)
    worker_bot.posts.clear()
    out = t._ReloadHost().start(worker_bot.sid, run, since)
    assert out == {"session_id": worker_bot.sid, "restarted": False, "reason": "autoplay was stopped during the reload"}
    assert t.AUTOPLAY[worker_bot.sid] is run, "no new bot"
    stopped = [kw for url, kw in worker_bot.posts if "/telemetry/" in url and kw["json"]["running"] is False]
    assert len(stopped) == 1, "the control plane hears that this bot is off"


def test_the_tools_host_sees_only_bot_playbooks_and_preparations(worker_bot):
    t = worker_bot.tools
    host = t._ReloadHost()
    run = t.AUTOPLAY[worker_bot.sid]
    assert [sid for sid, _ in host.bots()] == [worker_bot.sid] and host.busy() is None
    assert host.playbook(worker_bot.sid) == host.playbook_of(run) == run["playbook_module"] == worker_bot.pkg_bot
    alive = SimpleNamespace(is_alive=lambda: True)
    t.AUTOPLAY["w1-prep"] = {"thread": alive, "prepare": object(), "mode": "prepare"}
    t.AUTOPLAY["w1-vision"] = {"thread": alive, "mode": "vision", "mission": "vision: make progress",
                               "driver": SimpleNamespace(stopped=False), "inp": object(), "ctx": object()}
    try:
        assert "round preparation" in host.busy()
        assert [sid for sid, _ in host.bots()] == [worker_bot.sid], "a vision bot uses no bot module: left alone"
    finally:
        t.AUTOPLAY.pop("w1-prep")
        t.AUTOPLAY.pop("w1-vision")


# --- the control plane: POST /api/workers/{name}/bot-reload --------------------------------------------------------------

SID = "w1-launch"


class Rig:
    """BotControl over a real store with a scripted worker (every submitted job finishes at once)."""

    def __init__(self, store, answer):
        self.store, self.jobs, self.clock, self.answer = store, [], time.time(), answer
        self.ctl = B.BotControl(store, submit=self.submit, workers=self.workers, wid=lambda w: w, saver=None,
                                clock=lambda: self.clock, sleep=self.sleep, spawn=lambda fn: fn())

    def sleep(self, s):
        self.clock += s

    def workers(self):
        return [w | {"online": time.time() - w["last_seen"] < 30} for w in self.store.all("worker")]

    def submit(self, req, actor, origin):
        job = Job(tool=req.tool, input=req.input, require_worker=req.require_worker, agent_use=req.agent_use,
                  actor=actor, origin=origin or {})
        rec = job.model_dump(mode="json") | {"state": "succeeded", "output": self.answer(req.tool, req.input)}
        self.jobs.append(rec)
        self.store.put("job", job.id, rec)
        return job


@pytest.fixture
def store(tmp_path):
    st = Store(tmp_path / "data")
    st.put("worker", "w1", {"id": "w1", "name": "lilspark", "os": "linux", "tools": ["autoplay", "bot_reload"],
                            "last_seen": time.time()})
    st.put("session", SID, {"session_id": SID, "game_id": "re5", "title": "Resident Evil 5", "state": "running",
                            "started": time.time() - 600})
    S.TELEMETRY.clear()
    yield st
    S.TELEMETRY.clear()


def test_the_route_runs_the_workers_reload_and_returns_its_result(store):
    result = {"ok": True, "reloaded": ["gbox.mercs.titles.re5_combat"], "reason": "1 bot module(s) reloaded",
              "restarted": [{"session_id": SID, "restarted": True, "job_id": "J1"}]}
    rig = Rig(store, lambda tool, inp: {"result": result})
    out = rig.ctl.bot_reload("lilspark", B.ReloadIn(wait_s=60), "deploy", {"client": "curl"})
    assert out["state"] == "succeeded" and out["result"] == result and out["recovered"] == []
    assert out["worker"]["name"] == "lilspark"
    job = rig.jobs[0]
    assert (job["tool"], job["require_worker"], job["actor"], job["agent_use"]) == ("bot_reload", "w1", "deploy", False)
    assert job["input"] == {"modules": [], "settle_s": 5.0} and job["origin"]["via"] == "bot reload"
    assert H.verdict(out)[0] == "reloaded"


def test_a_bot_that_did_not_come_back_goes_through_f5s_mercmode_restart(store):
    run = {"worker": "lilspark", "worker_id": "w1", "session_id": SID, "phase": "playing", "game_id": "re5",
           "title": "Resident Evil 5", "started": 1, "autoplay_job": "J1", "knobs": {"pace": 1.0},
           "mercmode": {"title": "re5"}}
    store.put(S.STATE, "lilspark", run)
    store.put("job", "J1", {"id": "J1", "tool": "autoplay", "state": "succeeded", "created": 10, "actor": S.ACTOR,
                            "agent_use": True, "input": {"session_id": SID, "op": "start", "screensaver": True}})
    S.TELEMETRY[SID] = {"running": False, "mode": "playbook", "stats": {}, "at": time.time() - 2}

    def answer(tool, inp):
        if tool == "bot_reload":
            return {"result": {"ok": True, "reloaded": ["gbox.mercs_bot"], "restarted": [
                {"session_id": SID, "restarted": False, "recover": True, "error": "RuntimeError: emulator busy"}]}}
        if inp.get("op") == "status":
            return {"result": {"running": False}}
        return {"result": {"started": "playbook: mercs_bot", "mode": "playbook"}}
    rig = Rig(store, answer)
    rig.ctl.saver = S.Screensaver(store, None, lambda req, actor, origin: rig.submit(req, actor, origin), rig.workers)
    out = rig.ctl.bot_reload("lilspark", B.ReloadIn(wait_s=60), "deploy")
    assert out["recovered"] and out["recovered"][0]["session_id"] == SID and out["recovered"][0]["state"] == "succeeded"
    start = rig.jobs[-1]
    assert (start["tool"], start["input"]["op"], start["actor"]) == ("autoplay", "start", S.ACTOR)
    assert start["input"]["screensaver"] is True and start["input"]["style"] == {"pace": 1.0}
    assert store.get(S.STATE, "lilspark")["autoplay_job"] == start["id"], "MercMode owns the restarted bot"


@pytest.fixture
def app(tmp_path):
    from gbox import server
    from gbox.config import Config
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    application = server.create_app(cfg)
    st = application.state.store
    st.put("worker", "w1", {"id": "w1", "name": "lilspark", "os": "linux", "tools": ["autoplay", "bot_reload"],
                            "last_seen": time.time()})
    st.put("worker", "w2", {"id": "w2", "name": "i9-NUC", "os": "windows", "tools": ["autoplay"],
                            "last_seen": time.time()})
    st.put("worker", "w3", {"id": "w3", "name": "old-pc", "os": "linux", "tools": ["bot_reload"], "last_seen": 0})
    return cfg, application


def test_the_route_queues_the_workers_bot_reload_and_refuses_automation(app):
    cfg, application = app
    with TestClient(application, headers={"Authorization": "Bearer " + cfg.token()}) as client:
        r = client.post("/api/workers/lilspark/bot-reload", json={"modules": ["gbox.mercs.titles.re5_combat"]},
                        headers={"x-gbox-actor": "deploy"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "queued" and body["worker"] == {"id": "w1", "name": "lilspark", "os": "linux"}
        job = client.get("/api/jobs/" + body["job_id"]).json()
        assert (job["tool"], job["require_worker"], job["actor"]) == ("bot_reload", "w1", "deploy")
        assert job["input"] == {"modules": ["gbox.mercs.titles.re5_combat"], "settle_s": 5.0}
        assert client.post("/api/workers/lilspark/bot-reload", json={},
                           headers={"x-gbox-actor": "hermes"}).status_code == 403
        assert client.post("/api/workers/nope/bot-reload", json={}).status_code == 404
        older = client.post("/api/workers/i9-NUC/bot-reload", json={})
        assert older.status_code == 409 and "service restart" in older.json()["detail"]
        assert client.post("/api/workers/old-pc/bot-reload", json={}).status_code == 409
