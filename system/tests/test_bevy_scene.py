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
    assert spec["items"][0]["gltf"] == "/data/uap/pso/pso.gltf"


def test_abs_forward_slashes():
    p = _abs(Path("/tmp/a/b.gltf"))
    assert "\\" not in p and p.endswith("/tmp/a/b.gltf")
