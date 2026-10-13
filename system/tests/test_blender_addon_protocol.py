"""The gBox Blender add-on without Blender: a stub bpy is enough to import it, then its protocol helpers are checked
against the control plane's side (what "Send to gBox" submits is a valid characters op=add, the tags it reads from a
round-trip GLB are the ones gbox.blender_roundtrip writes, saves in a row coalesce into one live push)."""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ADDON = Path(__file__).resolve().parents[1] / "clients" / "blender" / "gbox_addon.py"


def _stub_bpy():
    def prop(*_a, **_k):
        return None

    class _Base:
        pass
    bpy = types.ModuleType("bpy")
    bpy.types = types.SimpleNamespace(Operator=_Base, Panel=_Base, AddonPreferences=_Base, Scene=type("Scene", (), {}))
    bpy.props = types.SimpleNamespace(StringProperty=prop, BoolProperty=prop, EnumProperty=prop, FloatProperty=prop)
    handlers = types.ModuleType("bpy.app.handlers")
    handlers.persistent = lambda f: f
    handlers.save_post = []
    app = types.ModuleType("bpy.app")
    app.handlers = handlers
    app.timers = types.SimpleNamespace(register=lambda *a, **k: None, is_registered=lambda f: False)
    bpy.app = app
    bpy.context = types.SimpleNamespace()
    bpy.data = types.SimpleNamespace(filepath="")
    mathutils = types.ModuleType("mathutils")
    mathutils.Matrix = mathutils.Vector = object
    return {"bpy": bpy, "bpy.app": app, "bpy.app.handlers": handlers, "mathutils": mathutils}


@pytest.fixture
def addon(monkeypatch):
    for k, v in _stub_bpy().items():
        monkeypatch.setitem(sys.modules, k, v)
    spec = importlib.util.spec_from_file_location("gbox_addon_under_test", ADDON)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_saves_in_a_row_coalesce_into_one_push(addon):
    d = addon.Debounce(1.5)
    assert d.left(0.0) is None and not d.due(100.0)
    d.hit(10.0)
    assert not d.due(11.0) and d.left(11.0) == pytest.approx(0.5)
    d.hit(11.2)                                                  # saved again: the wait restarts
    assert not d.due(12.0) and d.due(12.7)
    d.clear()
    assert not d.due(99.0)


def test_send_to_gbox_submits_a_valid_characters_add(addon):
    from gbox.characters import CharIn
    inp = addon.add_input("Knight – variant", "ab" * 32, base="wrestler", props=[{"object": "Hat", "bone": "head", "how": "x"}],
                          roles={"hip": "hip"}, scale={"head": 1.2}, auto_rig=False)
    c = CharIn.model_validate(inp)
    assert c.op == "add" and c.base == "wrestler" and c.props == [{"object": "Hat", "bone": "head"}]
    assert c.rig_roles == {"hip": "hip"} and c.scale == {"head": 1.2} and not c.auto_rig and c.derived_ok


def test_the_addon_reads_the_tags_the_control_plane_writes(addon, tmp_path, monkeypatch):
    from gbox import blender_roundtrip as RT, characters as C
    from tests import blender_rt_fixtures as fx
    root = tmp_path / "characters"
    root.mkdir()
    src = fx.humanoid(tmp_path / "s.glb", props={"Crown": ("head", (1, 2, 3))})
    m = C.add(root, "wrestler", "Wrestler", [src], {"game_title": "No Mercy"}, "t", rig={"roles": {r: r for r in fx.POS}})
    m["props"] = [{"node": "Crown", "bone": "head", "role": "head"}]
    C.put_meta(root, m)
    f = tmp_path / "x.glb"
    f.write_bytes(RT.export_glb(root, "wrestler"))
    t = addon.gbox_tags(addon.glb_json(str(f)))
    assert t["info"]["slug"] == "wrestler" and t["info"]["roles"]["l_hand"] == "l_hand"
    assert t["bones"]["head"] == "head" and t["objects"]["Crown"] == {"gbox_prop": True, "gbox_bone": "head"}
    assert addon.gbox_tags(addon.glb_json(str(fx.unrigged(tmp_path / "u.glb")))) == {}


def test_status_lines_for_each_import_mode(addon):
    v = addon.describe_add({"entry": {"name": "W hat", "slug": "w_hat"}, "mode": "variant", "variant_of": "wrestler",
                            "props": [{"node": "Hat", "bone": "head"}]})
    assert "variant of wrestler" in v and "Hat→head" in v
    n = addon.describe_add({"entry": {"name": "Statue", "slug": "statue"}, "mode": "new", "rig": {"rig": "auto"}})
    assert "auto-rigged" in n
    d = addon.describe_add({"entry": {"name": "P", "slug": "p"}, "mode": "derived", "derived_from": "wrestler",
                            "note": "no body roles"})
    assert "derived from wrestler" in d and "⚠" in d
