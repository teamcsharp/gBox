"""Blender round trip without Blender: a collection character goes out as one GLB carrying its rig role names and
props (gbox.blender_roundtrip.export_glb), comes back from the add-on's "Send to gBox" as a variant (same skeleton),
a derived character (bones changed) or a brand-new donor (rig auto-detected: Mixamo, Rigify, VRoid/VRM, UE mannequin,
biped; or auto-rigged when it has no skeleton), and its attachments ride every writer's shared retarget rigidly on
their bone, with a budget report (gbox.attachments)."""
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import attachments, blender_roundtrip as RT, characters as C, rig_detect, sm64_swap as S
from tests import blender_rt_fixtures as fx


@pytest.fixture
def lib(tmp_path, monkeypatch):
    root = tmp_path / "characters"
    root.mkdir()
    monkeypatch.setenv("GBOX_CHARACTERS", str(root))
    ctx = SimpleNamespace(config=SimpleNamespace(cache=str(tmp_path / "cache")), progress=lambda *a, **k: None,
                          artifact=lambda *a, **k: None, server=None, headers={})
    return root, ctx


def add(ctx, path, name, **kw):
    return C.add_model(ctx, C.CharIn(op="add", character=name, path=str(path), **kw))


def library_char(root, tmp_path, slug="wrestler", names=fx.ROLE_NAMES, **kw):
    """A collection character as a reader would leave it (model + roles + preview)."""
    src = fx.humanoid(tmp_path / f"{slug}_src.glb", names, **kw)
    roles = {r: names[r] for r in fx.POS}
    return C.add(root, slug, slug.title(), [src], {"game_title": "WWF No Mercy", "game_id": "0123456789abcdef"},
                 "test reader", rig={"roles": roles})


# ---------------------------------------------------------------- rig detection

@pytest.mark.parametrize("names,rig", [(fx.MIXAMO, "mixamo"), (fx.RIGIFY, "rigify"), (fx.VRM, "vrm"), (fx.UE, "ue_mannequin"),
                                       (fx.BIPED, "biped")])
def test_common_rigs_are_recognised_by_their_bone_names(tmp_path, names, rig):
    det = rig_detect.detect(fx.humanoid(tmp_path / "m.glb", names))
    assert det["rig"] == rig and det["matched"] == 18 and not det["missing"]
    assert det["roles"] == {r: names[r] for r in fx.POS}                 # the character's left stays its left


def test_vrm_humanoid_extension_wins_over_names(tmp_path):
    det = rig_detect.detect(fx.humanoid(tmp_path / "v.glb", fx.GENERIC, vrm="0"))
    assert det["rig"] == "vrm" and det["evidence"] == "VRM humanoid extension"
    assert det["roles"]["l_upper"] == fx.GENERIC["l_upper"] and det["roles"]["chest"] == fx.GENERIC["chest"]


def test_unknown_names_fall_back_to_the_joint_tree(tmp_path):
    det = rig_detect.detect(fx.humanoid(tmp_path / "g.glb", fx.GENERIC))
    assert det["rig"] == "tree"
    assert det["roles"]["hip"] == fx.GENERIC["hip"] and det["roles"]["l_hand"] == fx.GENERIC["l_hand"]
    assert det["roles"]["r_foot"] == fx.GENERIC["r_foot"]


def test_an_unrigged_mesh_reports_no_skin(tmp_path):
    det = rig_detect.detect(fx.unrigged(tmp_path / "u.glb"))
    assert det["rig"] is None and det["why"].startswith("no skin")


@pytest.mark.parametrize("arms", ["T", "down"])
def test_auto_rig_gives_an_unrigged_humanoid_a_skeleton_every_writer_can_load(tmp_path, arms):
    out = tmp_path / "rigged.glb"
    src = fx.unrigged(tmp_path / "u.glb", arms)
    rep = rig_detect.auto_rig(src, out)
    assert rep["roles"]["hip"] == "hip" and len(rep["roles"]) == 18
    assert rep["pose"].startswith("T" if arms == "T" else "A")
    rig = S.load_rig(out, rep["roles"])                                 # the shared loader every writer uses
    assert len(rig["joints"]) == 18 and set(rig["roles"]) >= {"hip", "head", "l_hand", "r_foot"}
    P = np.concatenate([p["pos"] for p in rig["prims"]])
    own = np.concatenate([p["owner"] for p in rig["prims"]])
    names = np.array(rig["names"])[own]
    left = P[:, 0] > 0.15                                               # hands / arms on +X are the left arm's
    assert all(n.startswith("l_") for n in names[left])
    assert all(not n.startswith("l_") for n in names[P[:, 0] < -0.15])
    feet = P[:, 1] < 0.1
    assert set(names[feet]) <= {"l_foot", "r_foot", "l_shin", "r_shin"}
    head = P[:, 1] > 1.7
    assert set(names[head]) <= {"head", "neck"}
    # rest pose kept: skinning the rigged file gives the original positions back
    from gbox.re4gc_models import _gltf_load, _node_world
    gl0, acc, _img = _gltf_load(src)
    orig = rig_detect._mesh_points(gl0, acc, _node_world(gl0))
    assert np.allclose(np.sort(orig, axis=0), np.sort(P, axis=0), atol=1e-5)


# ---------------------------------------------------------------- out: export with extras

def test_export_carries_roles_props_and_textures(lib, tmp_path):
    root, _ctx = lib
    m = library_char(root, tmp_path, props={"Crown": ("head", (250, 200, 0))})
    m["props"] = [{"node": "Crown", "bone": "head", "role": "head"}]
    C.put_meta(root, m)
    data = RT.export_glb(root, "wrestler")
    f = tmp_path / "out.glb"
    f.write_bytes(data)
    gl = fx.read(f)
    by = {n["name"]: n for n in gl["nodes"]}
    assert by["l_upper"]["extras"]["gbox_role"] == "l_upper"
    assert by["Crown"]["extras"] == {"gbox_prop": True, "gbox_bone": "head"}
    assert by["Body"]["extras"]["gbox_part"] == "body"
    g = gl["scenes"][0]["extras"]["gbox"]
    assert g["slug"] == "wrestler" and g["base"] == "wrestler" and g["roles"]["head"] == "head"
    assert len(gl["images"]) == 2 and all("bufferView" in im for im in gl["images"])     # textures embedded
    assert len(gl["skins"][0]["joints"]) == 18 and "WEIGHTS_0" in gl["meshes"][0]["primitives"][0]["attributes"]


def test_export_packs_a_gltf_with_external_files(lib, tmp_path):
    root, _ctx = lib
    library_char(root, tmp_path)
    d = root / "wrestler"
    gl, blob = attachments.read_gltf(d / "wrestler_src.glb")
    (d / "bin.bin").write_bytes(blob)
    gl["buffers"] = [{"byteLength": len(blob), "uri": "bin.bin"}]
    (d / "model.gltf").write_text(json.dumps(gl))
    m = C.get(root, "wrestler")
    m["model"] = "model.gltf"
    C.put_meta(root, m)
    out = tmp_path / "x.glb"
    out.write_bytes(RT.export_glb(root, "wrestler"))
    assert len(S.load_rig(out, m["rig"]["roles"])["prims"]) == 1


# ---------------------------------------------------------------- in: variant / derived / new

def blender_edit(src: Path, dst: Path, hat_on="head", armature_extras=None, extra_bone=None):
    """What the add-on sends after an edit: the exported character + a hat parented to a bone (unskinned child node,
    own texture, marked by the add-on's custom properties)."""
    gl, blob = attachments.read_gltf(src)
    w = fx.Writer()
    w.gl, w.bin = gl, bytearray(blob)
    P, F = fx.box([-0.07, 0.2, -0.07], [0.07, 0.3, 0.07], 0.0)
    mesh = w.mesh("Hat", P, F, w.material("hat_felt", (20, 20, 160)))
    hat = w.node({"name": "Hat", "mesh": mesh, "extras": {"gbox_bone": hat_on}})
    j = next(i for i, n in enumerate(gl["nodes"]) if n.get("name") == hat_on)
    gl["nodes"][j].setdefault("children", []).append(hat)
    if armature_extras:
        a = next(i for i, n in enumerate(gl["nodes"]) if n.get("name") == "Armature")
        gl["nodes"][a]["extras"] = armature_extras
    if extra_bone:
        e = w.node({"name": extra_bone, "translation": [0, 0.1, 0]})
        gl["nodes"][j]["children"].append(e)
        gl["skins"][0]["joints"].append(e)                   # (inverse bind of the new joint: identity is fine here)
        acc = gl["accessors"][gl["skins"][0]["inverseBindMatrices"]]
        old = np.frombuffer(bytes(w.bin), np.float32, acc["count"] * 16, gl["bufferViews"][acc["bufferView"]]["byteOffset"])
        gl["skins"][0]["inverseBindMatrices"] = w.acc(np.concatenate([old, np.eye(4, dtype=np.float32).reshape(16)]).reshape(-1, 16),
                                                      5126, "MAT4")
    return w.save(dst)


def test_send_back_from_blender_makes_a_variant_linked_to_the_original(lib, tmp_path):
    root, ctx = lib
    library_char(root, tmp_path)
    out = tmp_path / "export.glb"
    out.write_bytes(RT.export_glb(root, "wrestler"))
    edited = blender_edit(out, tmp_path / "edited.glb")
    res = add(ctx, edited, "Wrestler with a hat")                       # no base given: the file's extras say it
    assert res["mode"] == "variant" and res["variant_of"] == "wrestler" and res["classified"]["from"] == "scene extras"
    meta = C.get(root, res["entry"]["slug"])
    assert meta["variant_of"] == "wrestler" and meta["rig"]["roles"]["l_hand"] == "l_hand"
    assert [(p["node"], p["bone"], p["role"]) for p in meta["props"]] == [("Hat", "head", "head")]
    stored = fx.read(root / meta["slug"] / meta["model"])
    hat = next(n for n in stored["nodes"] if n["name"] == "Hat")
    assert hat["extras"]["gbox_prop"] is True                            # marked in the file: every writer sees it
    # the hat's own texture is in the stored model
    assert any(m.get("name") == "hat_felt" and "baseColorTexture" in m["pbrMetallicRoughness"] for m in stored["materials"])
    # a re-send (Live Link) updates the same variant, revision 2
    res2 = add(ctx, edited, "Wrestler with a hat", base="wrestler", replace=meta["slug"])
    assert res2["entry"]["slug"] == meta["slug"] and res2["revision"] == 2


def test_armature_extras_from_a_blender_paste_name_the_base(lib, tmp_path):
    root, ctx = lib
    library_char(root, tmp_path)
    plain = fx.humanoid(tmp_path / "plain.glb")                         # no scene extras: a Ctrl+V paste re-exported
    edited = blender_edit(plain, tmp_path / "e.glb", armature_extras={"gbox_slug": "wrestler", "gbox_base": "wrestler"})
    res = add(ctx, edited, "Pasted and edited")
    assert res["mode"] == "variant" and res["classified"]["from"] == "armature extras"


def test_a_changed_skeleton_is_refused_as_a_variant_but_kept_as_a_derived_character(lib, tmp_path):
    root, ctx = lib
    library_char(root, tmp_path)
    out = tmp_path / "export.glb"
    out.write_bytes(RT.export_glb(root, "wrestler"))
    edited = blender_edit(out, tmp_path / "boned.glb", extra_bone="ponytail")
    with pytest.raises(ValueError, match="blocked: the skeleton changed"):
        add(ctx, edited, "Ponytail", base="wrestler")
    res = add(ctx, edited, "Ponytail", derived_ok=True)
    meta = C.get(root, res["entry"]["slug"])
    assert res["mode"] == "derived" and meta["derived_from"] == "wrestler" and "variant_of" not in meta
    assert meta["rig"]["roles"]["head"] == "head" and meta["rig"]["roles"]["l_foot"] == "l_foot"   # gbox_role bones
    assert [p["node"] for p in meta["props"]] == ["Hat"]


@pytest.mark.parametrize("names,rig", [(fx.MIXAMO, "mixamo"), (fx.RIGIFY, "rigify"), (fx.UE, "ue_mannequin")])
def test_a_character_modelled_in_blender_becomes_a_donor_every_writer_accepts(lib, tmp_path, names, rig):
    from gbox import cast_swap
    root, ctx = lib
    src = fx.humanoid(tmp_path / "new.glb", names, props={"Sword": ("r_hand", (180, 180, 190))})
    res = add(ctx, src, "My Knight")
    meta = C.get(root, res["entry"]["slug"])
    assert res["mode"] == "new" and res["donor_ready"] and meta["rig"]["detected"] == rig
    assert meta["rig"]["roles"]["hip"] == names["hip"]
    assert [(p["node"], p["bone"]) for p in meta["props"]] == [("Sword", names["r_hand"])]
    assert cast_swap.retarget_check(meta, root) is None                 # the cast build's donor gate
    rig_ = S.load_rig(root / meta["slug"] / meta["model"], meta["rig"]["roles"])     # no props passed: found in the file
    assert [p["prop_node"] for p in rig_["prims"] if p["prop"]] == ["Sword"]


def test_an_unrigged_blender_model_is_auto_rigged_on_import(lib, tmp_path):
    from gbox import cast_swap
    root, ctx = lib
    res = add(ctx, fx.unrigged(tmp_path / "statue.glb"), "Clay Statue")
    meta = C.get(root, res["entry"]["slug"])
    assert res["rig"]["rig"] == "auto" and meta["blender"]["auto_rig"]["joints"] == 18
    assert cast_swap.retarget_check(meta, root) is None
    res2 = add(ctx, fx.unrigged(tmp_path / "statue2.glb"), "Clay Statue 2", auto_rig=False)
    assert not res2["donor_ready"] and "no body roles" in res2["note"]


def test_a_data_uri_gltf_from_blender_is_accepted(lib, tmp_path):
    root, ctx = lib
    g = fx.data_uri_gltf(fx.humanoid(tmp_path / "m.glb", fx.MIXAMO), tmp_path / "m.gltf")
    res = add(ctx, g, "Gltf Guy")
    assert res["mode"] == "new" and C.get(root, res["entry"]["slug"])["model"].endswith(".glb")


# ---------------------------------------------------------------- writers carry attachments

TGT_POS = {r: fx.POS[r] for r in fx.POS if not r.endswith("_clav") and r != "neck"}
TGT_ORDER = list(TGT_POS)
JMAP = {r: i for i, r in enumerate(TGT_ORDER)}


def target():
    T = np.array([TGT_POS[r] for r in TGT_ORDER], float) * 50              # a game skeleton 90 units tall
    parent = [TGT_ORDER.index(fx.PARENT[r]) if fx.PARENT[r] in JMAP else
              (TGT_ORDER.index("chest") if fx.PARENT[r] else -1) for r in TGT_ORDER]
    return {"T": T, "ground": 0.0, "head_h": 12.0, "parent": parent, "joints": len(T)}


def test_the_shared_retarget_keeps_an_attachment_rigid_on_its_bone_and_reports_it(tmp_path):
    src = fx.humanoid(tmp_path / "k.glb", props={"Sword": ("r_hand", (180, 180, 190))})
    gl, blob = attachments.read_gltf(src)                                 # marked the way the add-on marks it
    next(n for n in gl["nodes"] if n["name"] == "Sword")["extras"] = {"gbox_prop": True, "gbox_bone": "r_hand"}
    src.write_bytes(attachments.glb_bytes(gl, blob))
    with attachments.ledger() as led:
        rig = S.load_rig(src, {r: r for r in fx.POS})
        prims, rep = S.retarget(rig, target(), None, jmap=JMAP)
        sword = [p for p in prims if p.get("prop")]
        assert len(sword) == 1 and sword[0]["prop_node"] == "Sword"
        assert set(sword[0]["J"][:, 0]) == {JMAP["r_hand"]} and np.all(sword[0]["W"][:, 0] == 1)   # rigid, one bone
        assert sword[0]["name"].startswith(attachments.PROP_MAT)
        rigged = S.write_rigged(prims, target(), tmp_path / "rigged.gltf", "k")
        back = S.read_rigged(rigged)                                    # after a (here: no-op) budget pass
        assert [p["prop_node"] for p in back if p.get("prop")] == ["Sword"]
    s = attachments.summary(led)
    row = s["models"]["k.glb"]["props"][0]
    assert row == {"node": "Sword", "triangles": 12, "kept": 12, "state": "kept"} and not s["dropped"]


def test_a_prop_lost_in_the_budget_pass_is_reported_dropped(tmp_path):
    src = fx.humanoid(tmp_path / "k.glb", props={"Cape": ("chest", (90, 0, 0))})
    with attachments.ledger() as led:
        rig = S.load_rig(src, {r: r for r in fx.POS}, props=["Cape"])    # listed in meta["props"]
        prims, _ = S.retarget(rig, target(), None, jmap=JMAP)
        body_only = [p for p in prims if not p.get("prop")]
        S.read_rigged(S.write_rigged(body_only, target(), tmp_path / "dec.gltf", "k"))   # the decimate dropped it
    s = attachments.summary(led)
    assert s["dropped"] == ["Cape"] and "Cape DROPPED for the budget" in s["message"]


def test_the_weighted_doa_loader_flags_marked_attachments_too(tmp_path):
    from gbox import doa2_weighted_retarget as WR
    src = fx.humanoid(tmp_path / "k.glb", props={"Hat": ("head", (0, 0, 0))})
    gl, blob = attachments.read_gltf(src)
    next(n for n in gl["nodes"] if n["name"] == "Hat")["extras"] = {"gbox_prop": True}
    src.write_bytes(attachments.glb_bytes(gl, blob))
    rig = WR.load_rig(src, {r: r for r in fx.POS})
    assert [p["prop_node"] for p in rig["prims"] if p["prop"]] == ["Hat"]


# ---------------------------------------------------------------- control-plane routes (the picker's copy / import)

@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.config import Config
    from gbox.server import create_app
    root = tmp_path / "characters"
    root.mkdir()
    monkeypatch.setenv("GBOX_CHARACTERS", str(root))
    library_char(root, tmp_path)
    cfg = Config(data_dir=tmp_path / "data", cache_dir=tmp_path / "cache")
    app = create_app(cfg)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {cfg.token()}"
        c.root, c.store = root, app.state.store
        yield c


def test_blender_route_serves_the_round_trip_glb(client, tmp_path):
    r = client.get("/api/characters/wrestler/blender")
    assert r.status_code == 200 and r.content[:4] == b"glTF"
    f = tmp_path / "w.glb"
    f.write_bytes(r.content)
    assert fx.read(f)["scenes"][0]["extras"]["gbox"]["slug"] == "wrestler"
    assert client.get("/api/characters/nobody/blender").status_code == 404


def test_copy_route_puts_the_character_on_the_gbox_clipboard(client):
    r = client.post("/api/characters/wrestler/blender/copy", json={})
    assert r.status_code == 200, r.text
    item = client.get("/api/clipboard").json()
    assert item["kind"] == "gltf" and item["meta"]["character"] == "wrestler" and item["meta"]["roundtrip"] == 1
    assert item["meta"]["roles"]["hip"] == "hip"
    assert client.get(f"/api/artifacts/{item['sha256']}").content[:4] == b"glTF"


def test_import_route_queues_a_characters_add_job_on_the_control_plane(client, tmp_path):
    import base64
    data = fx.humanoid(tmp_path / "n.glb", fx.MIXAMO).read_bytes()
    r = client.post("/api/characters/blender/import", json={"name": "Knight", "b64": base64.b64encode(data).decode(),
                                                             "props": [{"object": "Sword", "bone": "x"}]})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["tool"] == "characters" and j["require_os"] == "linux"
    inp = j["input"]
    assert inp["op"] == "add" and inp["character"] == "Knight" and inp["artifact"] and inp["auto_rig"] and inp["derived_ok"]
    assert client.post("/api/characters/blender/import", json={"name": "x"}).status_code == 422


# ---------------------------------------------------------------- live link: which running game shows it

def test_live_push_finds_the_session_showing_the_character_or_its_original():
    from gbox import live_link as L
    chars = [{"slug": "wrestler", "targets": {"g1": [{"slot": "Stone Cold", "mod": "nm_wrestler"}]}},
             {"slug": "wrestler_hat", "variant_of": "wrestler",
              "targets": {"g1": [{"slot": "Stone Cold", "needs_rebuild": True, "base_mod": "nm_wrestler"}]}},
             {"slug": "other", "targets": {"g2": [{"slot": "player", "mod": "sm64_other"}]}}]
    sessions = [{"session_id": "w1-a", "state": "running", "game_id": "g2", "mod": "sm64_other", "started": 5},
                {"session_id": "w1-b", "state": "running", "game_id": "g1", "mod": "nm_wrestler", "started": 3},
                {"session_id": "w1-c", "state": "stopped", "game_id": "g1", "mod": "nm_wrestler", "started": 9}]
    s, t = L.find_live_session(sessions, chars, chars[1])               # the variant: its original's mod is running
    assert s["session_id"] == "w1-b" and t["slot"] == "Stone Cold" and t["game_id"] == "g1"
    s, t = L.find_live_session(sessions, chars, {"slug": "lonely", "name": "x"})
    assert s is None and t == {}
    picked = [{"session_id": "w2-z", "state": "running", "game_id": "g3", "live_character": "wrestler", "started": 1}]
    s, t = L.find_live_session(picked, chars, chars[1])                 # put there by the pick whip
    assert s["session_id"] == "w2-z" and "picked" in t["why"]


def test_pick_replace_live_is_used_only_when_registered(monkeypatch):
    from gbox import live_link as L
    calls = []
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: [{"name": "characters", "workers": ["spark"]}])
    assert L.pick_replace_live(None, {"session_id": "w1-a"}, {"slug": "x"}, "player") == {"tried": False}
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: [{"name": "pick_replace", "workers": ["pc"]}])
    monkeypatch.setattr(C, "_job", lambda ctx, tool, inp, w, lim: calls.append((tool, inp, w)) or
                        {"id": "j1", "state": "succeeded", "output": {"result": {"ok": True}}})
    r = L.pick_replace_live(None, {"session_id": "w1-a"}, {"slug": "x"}, "player")
    assert r["ok"] and calls == [("pick_replace", {"session_id": "w1-a", "character": "x", "mode": "live", "slot": "player"}, "w1")]


def test_generic_push_rebuilds_then_session_swaps(monkeypatch):
    from gbox import live_link as L
    posted = []
    monkeypatch.setattr(C, "characters_tool", lambda inp, ctx: {"result": {"mod": "nm_hat", "status": "built",
                                                                            "slot": inp.slot, "rebuild": inp.rebuild}})

    def api(ctx, method, path, **kw):
        posted.append((method, path, kw.get("json")))
        return {"id": "j9", "state": "succeeded", "output": {"session_id": "w1-new", "state_loaded": True}}
    monkeypatch.setattr(C, "_api", api)
    stages = []
    r = L.generic_push(SimpleNamespace(progress=lambda *a: None), {"slug": "hat", "name": "Hat"},
                       {"game_id": "g1", "title": "No Mercy"}, {"session_id": "w1-b"}, "Stone Cold",
                       lambda n, p, m: stages.append(n), 0.0)
    assert r["status"] == "live" and r["session_id"] == "w1-new" and r["mod"] == "nm_hat"
    assert posted == [("POST", "/api/sessions/w1-b/swap", {"mod": "nm_hat", "keep_state": True})]
    assert stages == ["building", "validating", "reloading", "live"]
    monkeypatch.setattr(C, "characters_tool", lambda inp, ctx: {"result": {"status": "missing", "message": "no writer"}})
    r = L.generic_push(SimpleNamespace(progress=lambda *a: None), {"slug": "hat", "name": "Hat"},
                       {"game_id": "g9", "title": "Other"}, {"session_id": "w1-b"}, "player", lambda *a: None, 0.0)
    assert r["status"] == "missing" and r["message"] == "no writer"


def test_a_save_with_no_game_showing_the_character_is_just_stored(lib, tmp_path, monkeypatch):
    from gbox import live_link as L
    root, ctx = lib
    library_char(root, tmp_path)
    monkeypatch.setattr(C, "_session", lambda ctx, sid: {"session_id": sid, "state": "stopped"})
    monkeypatch.setattr(C, "_api", lambda ctx, m, p, **kw: [] if p in ("/api/sessions", "/api/characters") else {})
    r = L.push(ctx, L.LiveIn(op="push", character="wrestler", target="w1-old"))   # its session was replaced / stopped
    assert r["status"] == "stored" and "no running game" in r["message"]
    with pytest.raises(ValueError, match="isn't running"):
        L.push(ctx, L.LiveIn(op="push", character="wrestler", target="w1-old", auto_target=False))


def test_blender_copy_tags_the_paste_with_the_round_trip_metadata(lib, tmp_path):
    from gbox import blender_copy
    root, _ctx = lib
    m = library_char(root, tmp_path, props={"Crown": ("head", (250, 200, 0))})
    m["props"] = [{"node": "Crown", "bone": "head", "role": "head"}]
    C.put_meta(root, m)
    f = tmp_path / "c.glb"
    f.write_bytes(RT.export_glb(root, "wrestler"))
    t = blender_copy.gbox_tags(f)
    assert t["armature"]["gbox_slug"] == "wrestler" and json.loads(t["armature"]["gbox_roles"])["head"] == "head"
    assert t["bones"]["r_foot"] == "r_foot" and t["objects"]["Crown"]["gbox_prop"] is True
    assert t["objects"]["Body"] == {"gbox_part": "body"}
    assert blender_copy.gbox_tags(fx.unrigged(tmp_path / "u.glb")) == {}
