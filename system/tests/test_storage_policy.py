"""Worker storage policy (operator 2026-10-26, gbox/storage_policy.py): no game data on a Windows system drive (fake
paths, the rule switched on per test), and builds are opt-in - agent / background / automatic work copies a build onto
a PC only with the operator's download receipt there ([builds] auto_send = false). Synthetic files only."""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from gbox import catalog, filemods, storage_policy as SP
from gbox.config import Config


@pytest.fixture
def windows(monkeypatch):
    """The rule as a Windows worker applies it: system drive C:, activated."""
    monkeypatch.setattr(SP, "system_drive", lambda *a, **k: "C:")
    monkeypatch.setitem(SP._ACTIVE, "on", True)


def cfg(cache="D:/gBox/cache", runtime="D:/gBox/runtime", data="C:/_tools/gBox/system/gbox-data", auto=False):
    return SimpleNamespace(cache=Path(cache), runtime=Path(runtime), data_dir=Path(data), cold_cache=None,
                           builds=SimpleNamespace(auto_send=auto))


# ------------------------------------------------------------------------------------------------ the system drive

def test_system_drive_parsing(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("sp_fresh", SP.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)                                   # an unstubbed copy
    assert fresh.system_drive("windows", {"SystemDrive": "D:"}) == "D:"
    assert fresh.system_drive("windows", {"SystemDrive": "e:\\"}) == "E:"
    assert fresh.system_drive("windows", {}) == "C:"
    assert fresh.system_drive("windows", {"SystemDrive": "nonsense"}) == "C:"
    assert fresh.system_drive("linux", {"SystemDrive": "C:"}) is None
    assert fresh._drive(None) is None, "the rule is off until a worker activates it"


def test_on_system_drive_with_fake_paths():
    for p in ("C:/gBox/cache", "c:\\Users\\me\\AppData\\Local\\Temp", "C:\\_tools\\gBox\\system\\gbox-data"):
        assert SP.on_system_drive(p, drive="C:"), p
    for p in ("D:/gBox/cache", "//10.89.1.246/ehm_eckx/gBox/system/gbox-data", "\\\\nas\\share\\x", "/home/ehm_eckx/x"):
        assert not SP.on_system_drive(p, drive="C:"), p
    assert not SP.on_system_drive("C:/x", drive=""), "no rule"
    assert SP.drive_of("D:/gBox/cache") == "D:" and SP.drive_of("//nas/share/x").replace("\\", "/") == "//NAS/SHARE"


def test_game_dir_redirects_to_the_configured_cache_or_refuses(windows):
    c = cfg()
    assert SP.game_dir(c, "C:/_tools/gBox/system/gbox-data/exports", "exports") == \
        Path("D:/gBox/cache") / SP.REDIRECT_DIR / "exports"
    assert SP.game_dir(c, "D:/gBox/runtime/extract", "extract") == Path("D:/gBox/runtime/extract"), "already off C:"
    on_c = cfg(cache="C:/_tools/gBox/system/gbox-data/cache")
    with pytest.raises(SP.SystemDriveRefused, match=r"system drive \(C:\).*cache_dirs = \{ windows = \"D:/gBox/cache\" \}"):
        SP.game_dir(on_c, "C:/_tools/gBox/system/gbox-data/runtime-windows-amd64/ring_record", "ring_record")
    assert SP.game_dir(on_c, "C:/x/extract", "extract", strict=False) == Path("C:/x/extract")
    with pytest.raises(SP.SystemDriveRefused):
        SP.require_off_system(on_c, on_c.cache / "mods" / "g" / "b", "build b")
    assert SP.require_off_system(c, c.cache / "mods", "builds") == c.cache / "mods"


def test_every_writer_routes_through_the_helper(windows):
    from gbox import doa3_native, rewind, ring_record, romexport
    c = cfg(runtime="C:/_tools/gBox/system/gbox-data/runtime-windows-amd64")
    red = Path("D:/gBox/cache") / SP.REDIRECT_DIR
    assert SP.extract_root(c) == red / "extract"
    assert ring_record.ring_dir(c, "w-1") == red / "ring_record" / "w-1"
    assert rewind.ring_dir(c, "w-1") == red / "rewind" / "w-1"
    assert romexport.exports_root(c) == red / "exports"
    assert doa3_native.play_root(c) == red / "doa3-native-play"
    from gbox.adapters import _extract_root
    assert _extract_root(c) == red / "extract"
    off = cfg()                                                      # runtime already on D:: unchanged
    assert ring_record.ring_dir(off, "s") == Path("D:/gBox/runtime/ring_record/s")
    assert romexport.exports_root(off) == red / "exports", "data_dir stays on C:, its exports do not"


def test_recording_and_rewind_say_why_instead_of_writing_to_c(windows, monkeypatch):
    from gbox import rewind, ring_record
    c = cfg(cache="C:/cache", runtime="C:/runtime")
    with pytest.raises(SP.SystemDriveRefused):
        ring_record.ring_dir(c, "s")
    ring_record.sweep(c)                                             # never raises
    rewind.sweep(c)
    monkeypatch.setattr(ring_record, "ffmpeg_cmd", lambda: ["python"])
    monkeypatch.setattr(ring_record, "HOST_OS", "windows")
    ad = SimpleNamespace(proc=SimpleNamespace(pid=1))
    out = ring_record.start("s", ad, SimpleNamespace(**vars(c), recording=None), threads=False)
    assert out["state"] == "unsupported" and "system drive" in out["reason"]


def test_staging_and_builds_refuse_a_cache_on_the_system_drive(windows, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)                       # off Windows "C:/..." is relative: any write would land here
    src = tmp_path / "share" / "game.iso"
    src.parent.mkdir()
    src.write_bytes(b"x" * 64)
    c = cfg(cache="C:/gbox-test-never-written/cache")
    with pytest.raises(SP.SystemDriveRefused, match="cache copy of game.iso"):
        catalog.stage_begin(src, "0123456789abcdef", c)
    with pytest.raises(SP.SystemDriveRefused, match="build b1"):
        filemods.build_image(c, "0123456789abcdef", src, "b1", {})
    with pytest.raises(SP.SystemDriveRefused, match="base copy"):
        filemods.ensure_base(c, "0123456789abcdef", src)
    assert not Path("C:/gbox-test-never-written").exists(), "nothing was written"
    if os.name != "nt":
        assert not (tmp_path / "C:").exists(), "nothing was written"


def test_launch_plays_from_the_share_when_staging_is_refused(monkeypatch, tmp_path):
    """A cache on the system drive: the big disc is not copied there; the game starts from the library share."""
    import sys
    from gbox import tools as T
    from gbox.config import EmulatorConfig, Library
    from gbox.models import CatalogEntry
    from gbox.registry import Ctx
    c = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c", stage_min_mb=0)
    c.libraries.append(Library(id="lib", kind="files", paths={"windows": str(tmp_path / "share"), "linux": str(tmp_path / "share")}))
    c.emulators["wii"] = EmulatorConfig(adapter="command", executable=sys.executable,
                                        args=["-c", "import time; time.sleep(30)", "{rom}"])
    src = tmp_path / "share" / "game.iso"
    src.parent.mkdir(parents=True)
    src.write_bytes(os.urandom(4096))
    game = CatalogEntry(game_id="g", title="Big", platform="wii", source_paths=[src.name], library="lib", rel_path=src.name,
                        hashes={}, size=src.stat().st_size, format="iso", runtimes={}, profile_id="g")

    def refuse(*a, **k):
        raise SP.SystemDriveRefused("gBox keeps game data off this PC's system drive (C:): the cache copy of game.iso")
    monkeypatch.setattr(T, "_stage_for_launch", refuse)
    monkeypatch.setattr(T, "SESSIONS", {})
    monkeypatch.setattr(T, "track_emulator", lambda *a, **k: None)
    ctx = Ctx(c, job_id="j1", worker="w1")
    out = T._launch_game(T.LaunchIn(game=game), ctx)
    try:
        assert out["detail"]["staging"]["refused"].startswith("gBox keeps game data off")
        assert T.SESSIONS[out["session_id"]][1]["_rom_path"] == str(src), "played from the library share"
        assert any("Playing it from the library share" in line for line in ctx.log)
    finally:
        for sid in list(T.SESSIONS):
            T.session_op(T.SessionIn(session_id=sid, op="stop_game"), Ctx(c, job_id="s", worker="w1"))


def test_redirect_temp_moves_python_temp_off_the_system_drive(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", None)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "Q:/Users/me/AppData/Local/Temp")
    c = SimpleNamespace(cache=tmp_path / "cache", runtime=tmp_path / "rt", data_dir=tmp_path / "d")
    target = tmp_path / "cache" / SP.REDIRECT_DIR / "tmp"
    target.mkdir(parents=True)
    old, fresh = target / "old-part", target / "fresh"
    old.write_text("x")
    fresh.write_text("y")
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    assert SP.redirect_temp(c, drive="Q:") == str(target)
    assert tempfile.tempdir == str(target) and not old.exists() and fresh.exists()
    assert SP.redirect_temp(c, drive="") is None, "no rule off Windows"
    on_q = SimpleNamespace(cache=Path("Q:/gbox-cache"))
    assert SP.redirect_temp(on_q, drive="Q:") is None, "nowhere to go: temp stays"


def test_system_drive_report_names_the_roots_on_it(monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: "C:/Users/me/AppData/Local/Temp")
    rows = SP.system_drive_report(cfg(), drive="C:")
    assert [r["root"] for r in rows] == ["data_dir", "temp"]
    assert SP.system_drive_report(cfg(), drive="") == []


# ------------------------------------------------------------------------------------------------ builds are opt-in

class Store:
    def __init__(self):
        self.docs = {}

    def put(self, kind, key, doc):
        self.docs[(kind, key)] = doc

    def get(self, kind, key):
        return self.docs.get((kind, key))

    def delete(self, kind, key):
        self.docs.pop((kind, key), None)

    def all(self, kind):
        return [d for (k, _), d in self.docs.items() if k == kind]


def test_operator_job_is_the_operators_own_request():
    assert SP.operator_job({"actor": "operator", "agent_use": False})
    assert SP.operator_job({"actor": "gbox-agent", "agent_use": True}), "the in-app chat agent speaks for the operator"
    for job in ({"actor": "operator", "agent_use": True}, {"actor": "mcp"}, {"actor": "hermes"}, {"actor": "agent"},
                {"actor": "gbox-auto"}, {"actor": "autoplay-screensaver", "agent_use": True}, {"actor": None}, {}):
        assert not SP.operator_job(job), job
    assert not SP.operator_job({"actor": "operator"}, parent={"actor": "hermes", "agent_use": True}), "a tool in an agent job"
    assert not SP.operator_job({"actor": "operator"}, parent={"actor": "gbox-auto"})
    assert SP.operator_job({"actor": "operator"}, parent={"actor": "operator", "agent_use": False})


def test_receipts_and_permits_per_pc():
    s = Store()
    SP.record_receipt(s, "i9-NUC", "g1", "cast_a", by="operator", job="j1")
    SP.record_receipt(s, "JAYBUILTFINALE", "g1", "cast_b")
    assert SP.receipt_keys(s, "i9-nuc") == ["g1/cast_a"], "by worker name, any case"
    assert SP.receipt_keys(s, "") == []
    job = {"actor": "hermes", "agent_use": True, "origin": {}}
    assert SP.permit(s, Config(), job, {"name": "i9-NUC"}) == {"operator": False, "auto_send": False, "receipts": ["g1/cast_a"]}
    s.put("job", "p1", {"actor": "mcp", "agent_use": True})
    child = {"actor": "operator", "agent_use": False, "origin": {"parent_job": "p1"}}
    assert SP.permit(s, Config(), child, {"name": "x"})["operator"] is False
    assert SP.permit(s, Config(builds={"auto_send": True}), job, None)["auto_send"] is True
    assert SP.forget_receipts(s, "g1", "cast_a", ["I9-NUC"]) == ["i9-NUC"] and SP.receipt_keys(s, "i9-NUC") == []
    assert SP.forget_receipts(s, "g1", "cast_b") == ["JAYBUILTFINALE"]


def ctx(**kw):
    return SimpleNamespace(server="http://spark", **kw)


def test_copy_refusal_follows_the_permit(tmp_path):
    c = SimpleNamespace(cache=tmp_path, builds=SimpleNamespace(auto_send=False))
    agent = ctx(actor="hermes", agent_use=True, build_permit={"operator": False, "auto_send": False, "receipts": []})
    why = SP.copy_refusal(c, "g1", "cast_a", agent)
    assert "has not downloaded it there" in why and "auto_send = false" in why and "hermes" in why
    assert SP.POLICY_RX.search(why)
    assert SP.copy_refusal(c, "g1", "cast_a", ctx(build_permit={"operator": True, "auto_send": False, "receipts": []})) is None
    assert SP.copy_refusal(c, "g1", "cast_a", ctx(build_permit={"operator": False, "auto_send": True, "receipts": []})) is None
    assert SP.copy_refusal(c, "g1", "cast_a", ctx(build_permit={"operator": False, "auto_send": False,
                                                                "receipts": ["g1/cast_a"]})) is None
    assert SP.copy_refusal(c, "g1", "cast_a", SimpleNamespace(server=None)) is None, "not a worker job"
    assert SP.copy_refusal(c, "g1", "cast_a", None) is None
    assert SP.write_local_receipt(c, "g1", "cast_a", job="j9") and SP.has_local_receipt(c, "g1", "cast_a")
    assert SP.copy_refusal(c, "g1", "cast_a", agent) is None, "the operator downloaded it on this PC"
    # a control plane that stamps no permit: the job's own actor, and this PC's config
    assert SP.copy_refusal(c, "g2", "b", ctx(actor="operator", agent_use=False, build_permit=None)) is None
    assert SP.copy_refusal(c, "g2", "b", ctx(actor="autoplay-screensaver", agent_use=True, build_permit=None))
    c.builds.auto_send = True
    assert SP.copy_refusal(c, "g2", "b", ctx(actor="mcp", agent_use=True, build_permit=None)) is None


NEW = {"game.iso": b"NEW-BUILD" * 4, ".gbox-mod.json": json.dumps({"name": "cast_a", "game_id": "g1", "image": "game.iso"}).encode()}


def serve(monkeypatch, data=NEW):
    files = [{"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()} for p, b in data.items()]
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(200, json={"files": files},
                                                                      request=httpx.Request("GET", "http://t")))
    streamed = []

    class Stream:
        def __init__(self, name):
            streamed.append(name)
            self.status_code, self.headers, self.content = 200, {}, data[name]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            yield self.content
    monkeypatch.setattr(httpx, "stream", lambda method, url, headers, **kw: Stream(url.rsplit("/", 1)[-1]))
    return streamed


def test_stage_refuses_before_the_first_byte_without_a_receipt(tmp_path, monkeypatch):
    streamed = serve(monkeypatch)
    c = SimpleNamespace(cache=tmp_path, builds=SimpleNamespace(auto_send=False))
    agent = ctx(actor="hermes", agent_use=True, build_permit={"operator": False, "auto_send": False, "receipts": []})
    token = SP.JOB.set(agent)
    try:
        with pytest.raises(SP.BuildNotOptedIn, match="has not downloaded it there"):
            filemods.stage(c, "http://t", {}, "g1", "cast_a")
        assert streamed == [] and not filemods.mod_dir(c, "g1", "cast_a").exists(), "nothing copied, no folder"
        with pytest.raises(SP.BuildNotOptedIn):
            filemods.fetch(c, "http://t", {}, "g1", "cast_a")
        assert streamed == []
    finally:
        SP.JOB.reset(token)
    operator = ctx(actor="operator", agent_use=False, build_permit={"operator": True, "auto_send": False, "receipts": []})
    token = SP.JOB.set(operator)
    try:
        assert filemods.stage(c, "http://t", {}, "g1", "cast_a") == "cast_a"
    finally:
        SP.JOB.reset(token)
    assert (filemods.mod_dir(c, "g1", "cast_a") / "game.iso").read_bytes() == NEW["game.iso"]
    token = SP.JOB.set(agent)                                        # already here and current: nothing to copy
    try:
        assert filemods.stage(c, "http://t", {}, "g1", "cast_a") == "cast_a"
    finally:
        SP.JOB.reset(token)


def test_registry_hands_the_job_to_filemods(tmp_path):
    from gbox import registry
    seen = []
    c = Config(data_dir=tmp_path / "d", cache_dir=tmp_path / "c")
    ctx_ = registry.Ctx(c, job_id="j1", worker="w1")
    ctx_.build_permit = {"operator": False}
    registry._run_with_fitting(lambda inp, cx: seen.append(SP.JOB.get()), None, ctx_)
    assert seen == [ctx_] and SP.JOB.get() is None


def test_delete_build_takes_the_local_receipt_along(tmp_path):
    c = SimpleNamespace(cache=tmp_path)
    d = filemods.mod_dir(c, "g1", "cast_a")
    d.mkdir(parents=True)
    (d / ".gbox-mod.json").write_text("{}")
    SP.write_local_receipt(c, "g1", "cast_a")
    assert filemods.delete_build(c, "g1", "cast_a")["removed"] == ["cast_a"]
    assert not SP.has_local_receipt(c, "g1", "cast_a")


def test_sendable_builds_for_automatic_work():
    s = Store()
    w = {"name": "i9-NUC", "os": "windows", "local_builds": [{"game_id": "g1", "name": "here"},
                                                             {"game_id": "g1", "name": "copy~ab12", "staged_of": "staged"}]}
    c = Config()
    assert SP.sendable(s, c, w, "g1", "here") and SP.sendable(s, c, w, "g1", "staged")
    assert not SP.sendable(s, c, w, "g1", "elsewhere")
    SP.record_receipt(s, "i9-NUC", "g1", "elsewhere")
    assert SP.sendable(s, c, w, "g1", "elsewhere")
    assert SP.sendable(s, c, {"name": "spark", "os": "linux"}, "g1", "anything"), "the collection host has them all"
    assert SP.sendable(s, Config(builds={"auto_send": True}), w, "g1", "zz")
