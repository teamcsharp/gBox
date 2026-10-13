"""Focused tests for the bevy_scene tool's reactive live-scene support (request #87).

The scene-spec helpers must be pure so the live-ops logic is testable without building
the Rust viewer or opening a window: op=add/remove/set_camera mutating a spec in place,
scene round-trips, and the model accepting the new op/index fields.
"""
import json
from pathlib import Path

from gbox.tools import BevyIn, BevyOut, _abs, _bevy_write


class _FakeCtx:
    def __init__(self, tmp: Path):
        self.config = type("C", (), {"data_dir": tmp})()
        self.progress = lambda *a, **k: None


def _spec(items=2):
    return {"assets_root": "/data/uap",
            "items": [{"gltf": f"/data/uap/pkg{i}/pkg{i}.gltf", "scale": 1.0} for i in range(items)],
            "camera": {"eye": [900, 700, 900], "target": [0, 0, 0]}}


def test_bevy_model_new_ops():
    i = BevyIn.model_validate({"name": "s", "op": "open", "items": [{"package": "x"}]})
    assert i.op == "open" and i.screenshot is True
    i = BevyIn.model_validate({"name": "s", "op": "snapshot", "items": []})
    assert i.op == "snapshot"
    i = BevyIn.model_validate({"name": "s", "op": "remove", "index": 2})
    assert i.index == 2
    # old-style call stays valid: items required before, optional now
    i = BevyIn.model_validate({"name": "s", "op": "list"})
    assert i.items == []
    o = BevyOut.model_validate({"live": [{"name": "a", "pid": 1}], "scenes": [], "renders": []})
    assert o.live[0]["pid"] == 1


def test_bevy_write_roundtrip(tmp_path):
    scene = tmp_path / "bevy" / "demo.json"
    scene.parent.mkdir(parents=True, exist_ok=True)
    spec = _spec()
    _bevy_write(spec, scene)
    back = json.loads(scene.read_text())
    assert back == spec
    assert [i["gltf"] for i in back["items"]] == ["/data/uap/pkg0/pkg0.gltf", "/data/uap/pkg1/pkg1.gltf"]


def test_live_ops_mutate_spec(tmp_path):
    # the exact mutation sequence bevy_scene performs on a live session's spec
    scene = tmp_path / "demo.json"
    spec = _spec()
    _bevy_write(spec, scene)

    spec["camera"] = {"eye": [0, 500, 900], "target": [50, 0, 50]}          # op=set_camera
    _bevy_write(spec, scene)

    spec["items"].append({"gltf": _abs(tmp_path / "new.gltf"), "scale": 2.0})  # op=add
    _bevy_write(spec, scene)

    spec["items"].pop(0)                                                     # op=remove index=0
    _bevy_write(spec, scene)

    back = json.loads(scene.read_text())
    assert back["camera"]["eye"] == [0, 500, 900]
    assert len(back["items"]) == 2
    assert back["items"][0]["gltf"] == "/data/uap/pkg1/pkg1.gltf"
    assert back["items"][1]["gltf"] == _abs(tmp_path / "new.gltf")
    assert back["items"][1]["scale"] == 2.0


def test_scene_spec_keeps_portable_src(tmp_path):
    # cross-node reuse: _src carries the original {package}/{character} references
    from gbox import tools
    from gbox.tools import _bevy_scene_spec
    orig = tools._bevy_resolve
    try:
        tools._bevy_resolve = lambda ctx, items: [(Path("/data/uap/pso/pso.gltf"), {}) for _ in items]
        spec = _bevy_scene_spec(_FakeCtx(tmp_path), [{"package": "pso_dc_forest01"}])
    finally:
        tools._bevy_resolve = orig
    assert spec["_src"] == [{"package": "pso_dc_forest01"}]
    assert spec["items"][0]["gltf"] == _abs(Path("/data/uap/pso/pso.gltf"))   # C:/data/... on Windows


def test_abs_forward_slashes():
    p = _abs(Path("/tmp/a/b.gltf"))
    assert "\\" not in p and p.endswith("/tmp/a/b.gltf")


class _Proc:
    """A live viewer process stand-in: running until wait() (the viewer saw <name>.quit) or terminate()."""
    _pid = 4000

    def __init__(self, args, cwd=None):
        _Proc._pid += 1
        self.args, self.pid, self.code = args, _Proc._pid, None

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        self.code = 0
        return 0

    def terminate(self):
        self.code = -1


def _drive(monkeypatch, tmp_path):
    """bevy_scene with the viewer build, glTF resolution and process start replaced; returns (call, artifacts)."""
    from gbox import tools
    arts = []
    ctx = _FakeCtx(tmp_path)
    ctx.config.runtime = tmp_path / "runtime"
    ctx.artifact = lambda name, data, mime, **kw: arts.append((name, data))
    monkeypatch.setattr(tools, "BEVY", {})
    monkeypatch.setattr(tools, "_bevy_build", lambda ctx, target, exe: None)
    monkeypatch.setattr(tools, "_bevy_resolve",
                        lambda ctx, items: [(tmp_path / "m" / f"{list(i.values())[0]}.gltf", {k: v for k, v in i.items() if k == "scale"})
                                            for i in items])
    monkeypatch.setattr(tools.subprocess, "Popen", _Proc)
    call = lambda **kw: tools.bevy_scene(BevyIn.model_validate(kw), ctx)   # @tool returns the function itself
    return call, arts, tools


def test_live_ops_drive_the_open_window(monkeypatch, tmp_path):
    call, arts, tools = _drive(monkeypatch, tmp_path)
    scene = tmp_path / "bevy" / "demo.json"
    out = call(name="demo", op="open", items=[{"package": "a"}, {"package": "b", "scale": 2.0}],
               camera={"eye": [1, 2, 3], "target": [0, 0, 0]})
    proc = tools.BEVY["demo"]["proc"]
    assert out["pid"] == proc.pid and "--live" in proc.args and len(out["items"]) == 2
    assert json.loads(scene.read_text())["camera"]["eye"] == [1, 2, 3]

    out = call(name="demo", op="set_camera", camera={"eye": [9, 9, 9], "target": [1, 1, 1]})
    assert json.loads(scene.read_text())["camera"] == {"eye": [9, 9, 9], "target": [1, 1, 1]}
    out = call(name="demo", op="add", items=[{"package": "c"}])
    assert [i["gltf"].rsplit("/", 1)[1] for i in json.loads(scene.read_text())["items"]] == ["a.gltf", "b.gltf", "c.gltf"]
    out = call(name="demo", op="remove", index=0)
    assert [i["gltf"].rsplit("/", 1)[1] for i in out["items"]] == ["b.gltf", "c.gltf"]
    assert json.loads(scene.read_text())["items"] == out["items"]

    listed = call(name="demo", op="list")
    assert [(l["name"], l["items"]) for l in listed["live"]] == [("demo", 2)]
    assert [s["name"] for s in listed["scenes"]] == ["demo"]

    call(name="demo", op="close")
    assert "demo" not in tools.BEVY and proc.poll() == 0
    assert (tmp_path / "bevy" / "demo.quit").exists()        # the request the --live viewer polls for
    assert call(name="demo", op="list")["live"] == []


def test_live_ops_without_a_window_are_refused(monkeypatch, tmp_path):
    import pytest
    call, arts, tools = _drive(monkeypatch, tmp_path)
    for op in ("snapshot", "set_camera", "add", "remove"):
        with pytest.raises(ValueError, match="no live viewer named ghost"):
            call(name="ghost", op=op, items=[{"package": "x"}])
    with pytest.raises(ValueError, match="needs items"):
        call(name="never_saved", op="open")
    assert call(name="ghost", op="close")["scene"].endswith("ghost.json")   # closing nothing is a no-op


def test_snapshot_returns_the_live_window_png(monkeypatch, tmp_path):
    call, arts, tools = _drive(monkeypatch, tmp_path)
    call(name="demo", op="open", items=[{"package": "a"}])
    png = tmp_path / "bevy" / "demo.png"

    def viewer_saves(path, timeout_s=60.0):                   # the viewer answers <name>.shot with the PNG
        assert (tmp_path / "bevy" / "demo.shot").read_text() == _abs(png)
        png.write_bytes(b"\x89PNG-live")
        return png
    monkeypatch.setattr(tools, "_bevy_wait_png", viewer_saves)
    out = call(name="demo", op="snapshot")
    assert out["screenshot"] == str(png) and arts == [("bevy.png", b"\x89PNG-live")]


def test_agent_pins_live_ops_to_the_worker_that_opened_the_window():
    from gbox.agent import Agent
    a = Agent.__new__(Agent)
    jobs = []

    def job(tool, inp, node=None, limit=900, worker=None):
        jobs.append((inp.get("op"), node, worker))
        return {"state": "succeeded", "worker_id": "nuc" if inp.get("op") == "open" else worker,
                "output": {"scene": "s", "live": [{"name": "s"}]}, "receipt_id": None}
    a._job = job
    a.api = type("Api", (), {"get": lambda self, *x, **k: (_ for _ in ()).throw(RuntimeError("no receipts"))})()
    a.bevy_scene(items=[{"package": "a"}], name="s", op="open")
    a.bevy_scene(name="s", op="snapshot")
    assert a.bevy_scene(name="s", op="list")["live"] == [{"name": "s"}]
    a.bevy_scene(name="s", op="close")
    a.bevy_scene(name="s", op="snapshot")
    assert jobs == [("open", "windows", None), ("snapshot", None, "nuc"), ("list", "windows", None),
                    ("close", None, "nuc"), ("snapshot", "windows", None)]


def test_snapshot_wait_returns_only_a_finished_png(tmp_path, monkeypatch):
    from gbox import tools
    png, sizes = tmp_path / "s.png", iter([0, 10, 25, 25])
    monkeypatch.setattr(tools.time, "sleep", lambda s: png.write_bytes(b"x" * next(sizes, 25)))
    assert tools._bevy_wait_png(png, timeout_s=30) == png and png.stat().st_size == 25
