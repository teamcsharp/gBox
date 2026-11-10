import os
import socket
import sys
import threading
import time

import httpx
import pytest
import uvicorn

# The suite's test modules import each other by bare top-level name (204 sibling imports, e.g.
# `from test_pso_gc_adventure import memory`), so `tests/` itself must be importable. pytest's
# rootdir does not put the `tests` directory on sys.path on its own; without this, a plain
# `pytest tests/test_pso_campaign.py` (as the publish validator runs it) fails the very first
# import with ModuleNotFoundError. Put this directory at the head of sys.path before any test
# module can be collected.
_SYS_PATH_KEY = "_gbox_tests_dir_on_path"
if _SYS_PATH_KEY not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, _SYS_PATH_KEY)

from gbox import uap, worker
from gbox.config import Config
from gbox.server import create_app


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def _private_character_library(monkeypatch):
    """Tests never write the real character library. On the Spark GBOX_CHARACTERS is exported for the tests that
    read real HUcast / Snake models (module-level paths, read at import); while it stayed set,
    characters.library_root(cfg) ignored each test's temporary cache and test_parallel_builds_preserve_all_
    character_targets wrote its 'shared' slug + targets folder into ~/gBox_alt/gbox-cache/characters, which made
    /api/characters return 500 (2026-10-13). A test that wants a library sets GBOX_CHARACTERS itself."""
    monkeypatch.delenv("GBOX_CHARACTERS", raising=False)


@pytest.fixture(autouse=True)
def _fresh_re5_pace(monkeypatch):
    """RE5's between-rounds plan (gbox.mercs.titles.re5_ps3.PACE: the turn's mode, the same-round streak, the path since
    the last round ended) is module state kept across bot reloads: every test starts with a fresh one."""
    import sys
    mod = sys.modules.get("gbox.mercs.titles.re5_ps3")
    if mod is not None and hasattr(mod, "Pace"):
        monkeypatch.setattr(mod, "PACE", mod.Pace())


@pytest.fixture(autouse=True)
def _fresh_menu_learners(monkeypatch):
    """The menus' learners (gbox.mercs.menu_speed: one per title and process, each screen's learned waits, its RAM
    cursor-jump record, the transition being timed) are process state: every test starts with none, so one test's
    learned waits or open transition never times another's walk."""
    import sys
    mod = sys.modules.get("gbox.mercs.menu_speed")
    if mod is not None and hasattr(mod, "_CACHE"):
        monkeypatch.setattr(mod, "_CACHE", {})
    r5 = sys.modules.get("gbox.mercs.titles.re5_switch")
    if r5 is not None and isinstance(getattr(r5, "_MENU", None), dict):
        monkeypatch.setattr(r5, "_MENU", {"speed": None, "knob": True, "run": None, "stats_at": float("-inf")})
        monkeypatch.setattr(r5, "_JUMP", {})
        monkeypatch.setattr(r5, "_SEEN_CURSOR", {})


@pytest.fixture(autouse=True)
def _private_enemy_knowledge(tmp_path_factory):
    """Tests never write the real enemy knowledge database (gbox.mercs.enemy_db): its default home is the deployment's
    gbox-data/mercs/knowledge, and a bot test's shots and hits (re5_switch reports every pull) would land in the live
    database of whatever checkout runs the tests (the Spark's share). Every test gets its own; a test that wants a
    particular one configures it itself."""
    try:
        from gbox.mercs import enemy_db
    except ImportError:
        yield
        return

    def point(path):
        # Not enemy_db.configure: its flush starts the writer thread, and a test may have replaced threading.Thread
        # (test_mercs_team_integration's ImmediateThread takes no name): the queued facts of a test are dropped.
        enemy_db.reset()
        s = enemy_db._state()
        with s["lock"]:
            s["root"] = path
            enemy_db._forget(s)
    point(tmp_path_factory.mktemp("enemy_knowledge"))
    yield
    point(tmp_path_factory.mktemp("enemy_knowledge_after"))


@pytest.fixture(autouse=True)
def _private_re4_mods(tmp_path_factory, monkeypatch):
    """Tests never read or write the real RE4 Switch mods settings (re4_switch_mods.SETTINGS_FILE: the operator's saved
    sidebar choices, which every new session loads); each test starts from none."""
    try:
        from gbox.mercs.titles import re4_switch_mods as mod
    except Exception:                                        # noqa: BLE001 - a checkout without it
        return
    monkeypatch.setattr(mod, "SETTINGS_FILE", tmp_path_factory.mktemp("re4_mods") / "re4-mods.json")
    mod.ORIG.clear()
    monkeypatch.setattr(mod.D, "FIRE_GAP_S", mod.D.FIRE_GAP_S)     # Fire rate x paces the fight: put back after each test
    if hasattr(mod.D, "HAND_REQUEST"):                              # the bot's grenade asks: none carried between tests
        monkeypatch.setattr(mod.D, "HAND_REQUEST", {})
        monkeypatch.setattr(mod.D, "HAND_STATE", {})


@pytest.fixture(autouse=True)
def _private_re5_doors(tmp_path_factory, monkeypatch):
    """Tests never write the real RE5 Switch door memory (re5_switch.DOOR_FILE: the doors, windows and ledges each stage
    showed, which the bot walks to when nobody is left to fight) nor its log (DOOR_LOG): a test's synthetic door would
    land in the live memory of whatever checkout runs the tests (the Spark's share) and be walked to there. A test that
    wants particular ones points them itself."""
    import sys
    mod = sys.modules.get("gbox.mercs.titles.re5_switch")
    if mod is not None and hasattr(mod, "DOOR_FILE"):
        root = tmp_path_factory.mktemp("re5_doors")
        monkeypatch.setattr(mod, "DOOR_FILE", root / "door_spots.json")
        monkeypatch.setattr(mod, "DOOR_LOG", root / "re5-switch-doors.jsonl")



@pytest.fixture(autouse=True)
def _private_re4_menu_pace(tmp_path_factory, monkeypatch):
    """Tests never read or write the real learned RE4 menu pace (re4_switch.PACE_FILE): each starts from the hand-set
    waits, so one test's learned speed never times another's walk, and none lands in the live file."""
    try:
        from gbox.mercs.titles import re4_switch
    except Exception:                                        # noqa: BLE001 - a checkout without it
        return
    if hasattr(re4_switch, "PACE_FILE"):
        monkeypatch.setattr(re4_switch, "PACE_FILE", tmp_path_factory.mktemp("re4_pace") / "menu_pace.json")
        monkeypatch.setattr(re4_switch, "_PACE", {"screens": None, "dirty": False, "saved": float("-inf")})


@pytest.fixture(autouse=True)
def _private_re5_threats(tmp_path_factory, monkeypatch):
    """Tests never read or write the real learned threats (re5_switch.THREAT_FILE: who hurt the bot, per enemy class,
    which a new session loads): a test's synthetic hits would teach the live bot. Imported here, so a test that first
    imports the bot inside its body is covered too."""
    try:
        from gbox.mercs.titles import re5_switch
    except Exception:                                        # noqa: BLE001 - a checkout without it
        return
    if hasattr(re5_switch, "THREAT_FILE"):
        monkeypatch.setattr(re5_switch, "THREAT_FILE", tmp_path_factory.mktemp("re5_threats") / "re5-switch-threats.json")


@pytest.fixture(autouse=True)
def _private_re4_re6_threats(tmp_path_factory, monkeypatch):
    """The same for RE4 and RE6 Switch (re4_switch.THREAT_FILE / re6_switch.THREAT_FILE: the universal core's threat
    memory, gbox.mercs.core.combat.Threats): no test reads or teaches the live bot's learned threats."""
    for name in ("re4_switch", "re6_switch"):
        try:
            mod = __import__(f"gbox.mercs.titles.{name}", fromlist=["THREAT_FILE"])
        except Exception:                                    # noqa: BLE001 - a checkout without it
            continue
        if hasattr(mod, "THREAT_FILE"):
            monkeypatch.setattr(mod, "THREAT_FILE", tmp_path_factory.mktemp(f"{name}_threats") / f"{name}-threats.json")


@pytest.fixture(autouse=True)
def _no_system_drive_rule(monkeypatch):
    """A worker refuses game data on a Windows system drive (gbox/storage_policy.py); tests keep their temporary
    folders wherever pytest puts them (C: on a Windows box), so the rule only applies where a test asks for it
    (drive="C:" or its own system_drive)."""
    from gbox import storage_policy
    monkeypatch.setattr(storage_policy, "system_drive", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _re5_switch_rampage_off(request, monkeypatch):
    """The 5 m rampage (re5_switch.RAMPAGE) takes every fight with a Majini within 5 m; the older Switch fight tests
    drive the aim paths it skips there (which still run past 5 m), so they run with it off;
    tests/test_re5_switch_rampage.py runs with it on."""
    mod = request.module.__name__
    if "re5_switch" in mod and "rampage" not in mod:
        from gbox.mercs.titles import re5_switch
        monkeypatch.setattr(re5_switch, "RAMPAGE", False)


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache", api_port=free_port())


@pytest.fixture
def plane(cfg):
    """Real HTTP control plane + real worker thread, talking over localhost."""
    app = create_app(cfg)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cfg.api_port, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    url = f"http://127.0.0.1:{cfg.api_port}"
    # Wait for each condition with a deadline and fail loudly: a fixed 5 s of polls ran out on a loaded
    # machine (the worker's first describe() imports every tool module), and the test then ran against
    # a plane with no registered worker (test_unavailable_tool_never_claimed: KeyError 'test-worker').
    end = time.time() + 60
    while True:
        try:
            httpx.get(url + "/api/health")
            break
        except httpx.TransportError:
            if time.time() > end:
                raise RuntimeError("test control plane did not start") from None
            time.sleep(0.05)
    stop = threading.Event()
    threading.Thread(target=worker.run, args=(url, cfg.token(), cfg, "test-worker", stop, 0.05), daemon=True).start()
    client = httpx.Client(base_url=url, headers={"authorization": f"Bearer {cfg.token()}"}, timeout=30)
    while not any(w.get("name") == "test-worker" and w.get("online") for w in client.get("/api/workers").json()):
        if time.time() > end:
            stop.set()
            srv.should_exit = True
            raise RuntimeError("test worker did not register with the control plane")
        time.sleep(0.05)
    client.app = app
    yield client
    stop.set()
    srv.should_exit = True


def run_job(client, tool, inp, timeout=30):
    job = client.post("/api/jobs", json={"tool": tool, "input": inp}).raise_for_status().json()
    end = time.time() + timeout
    while job["state"] in ("queued", "running") and time.time() < end:
        time.sleep(0.05)
        job = client.get(f"/api/jobs/{job['id']}").json()
    return job


def make_cube(name="cube") -> uap.Manifest:
    """8-vertex cube skinned to a 2-bone chain with one clip."""
    P = [[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    idx = [i for a, b, c, d in faces for i in (a, b, c, a, c, d)]
    return uap.Manifest(
        name=name, source={"game_id": "fixture", "resource_ids": ["cube"], "extraction_method": "synthetic"},
        meshes=[uap.Mesh(name="cube", positions=P, normals=[[v / 3 ** .5 for v in p] for p in P],
                         uvs=[[(p[0] + 1) / 2, (p[1] + 1) / 2] for p in P], indices=idx, material=0,
                         joints=[[0 if p[1] < 0 else 1, 0, 0, 0] for p in P], weights=[[1, 0, 0, 0]] * 8)],
        materials=[uap.Material(name="grey", base_color=[.5, .5, .5, 1])],
        skeleton=[uap.Bone(name="root"), uap.Bone(name="tip", parent=0, translation=[0, 1, 0])],
        animations=[uap.Clip(name="bend", channels=[uap.Channel(
            bone=1, path="rotation", times=[0, 0.5, 1], values=[[0, 0, 0, 1], [0, 0, .3826834, .9238795], [0, 0, 0, 1]])])],
        nodes=[uap.Node(name="cube", mesh=0, skinned=True)], roots=[0],
        confidence={"geometry": "verified", "skeleton": "verified", "animations": "verified", "textures": "missing"},
        provenance=[{"by": "tests/conftest.py", "note": "synthetic fixture"}])
