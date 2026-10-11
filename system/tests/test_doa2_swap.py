"""Native joint-local reintegration, bind transforms and capability boundaries."""
import copy
import struct
import time
from types import SimpleNamespace

import numpy as np
import pytest

from gbox import doa2_geometry as G, doa2_swap as S


@pytest.mark.parametrize('family', ['LOR', 'MAM', 'PDG', 'WBA'])
def test_bound_native_variant_families_are_valid_retarget_targets(family):
    assert S.fighter_slot(family) == (family, None)
    assert S.fighter_slot(f'{family.lower()}:0') == (family, '00')
    with pytest.raises(ValueError, match='Unknown'):
        S.fighter_slot('YTI')


def native_fixture():
    h = bytearray(80)
    struct.pack_into("<4I", h, 0, 0x8000002c, 0x83000000, (4 << 29) | (5 << 26), 1 << 27)
    struct.pack_into("<2i", h, 32, 0, 1)
    mesh = {"header": bytes(h), "vertices": [(0, 0, 0, 0, 1, 0, 0, 0),
            (1, 0, 0, 0, 1, 0, 1, 0), (0, 1, 0, 0, 1, 0, 0, 1)], "triangles": [(0, 1, 2)]}
    model = G.encode_model({"global_flags": (1, 1)}, [mesh])
    struct.pack_into("<i", h, 32, -1)
    volume = G.encode_model({"global_flags": (1, 1)}, [{**mesh, "header": bytes(h)}])
    out = bytearray(24)
    pointers = []
    for body in [model] * 15 + [volume]:
        pointers.append(0x0c300000 + len(out) - 24)
        out.extend(body)
    out.extend(bytes(8))
    table = len(out)
    out.extend(struct.pack("<16I", *pointers))
    tex_table = len(out)
    out.extend(struct.pack("<3I", 8 | (8 << 16), 1 | (1 << 8), 0x0d200000))
    struct.pack_into("<6I", out, 0, 24, table, tex_table, 16, 1, 0)
    world = np.repeat(np.eye(4)[None], 15, axis=0)
    world[:, 0, 3] = np.arange(15) * 2
    profile = {"format": "doa2-native-rig-v1", "executable_sha256": S.EXECUTABLE_SHA256,
               "evidence": {"bind_transforms": "fixture", "part_mapping": "fixture"},
               "world": world.tolist(), "parent": [-1] + [0] * 14,
               "roles": dict(zip(sorted(S.REQUIRED_ROLES), range(15))),
               "emit_models": {str(j): j for j in range(15)}, "body_models": list(range(15)),
               "ground": 0, "head_h": 1}
    return bytes(out), bytes(128), profile


def donor():
    return {"pos": np.array([[2., 0, 0], [3, 0, 0], [2, 1, 0], [4, 1, 0]]),
            "nrm": np.tile([0., 1, 0], (4, 1)), "uv": np.zeros((4, 2)),
            "tris": np.array([[0, 1, 2], [0, 2, 3]]),
            "J": np.array([[1, 0, 0, 0], [1, 0, 0, 0], [2, 0, 0, 0], [2, 0, 0, 0]]),
            "tex": None, "color": (255, 0, 0, 255)}


def test_joint_local_world_roundtrip_and_unrelated_volume_preservation():
    chr_data, binary, profile = native_fixture()
    result = S.encode_parts(chr_data, binary, [donor()], profile, size_budget=len(chr_data))
    rebuilt, original = G.decode_chr(result["chr_data"]), G.decode_chr(chr_data)
    assert result["report"]["triangles"] == 2
    assert result["report"]["gameplay_verified"] is False
    assert len(result["bin_data"]) == len(binary)
    for joint, wanted in [(1, [0, 1, 2]), (2, [0, 2, 3])]:
        mesh = rebuilt["models"][joint]["meshes"][0]
        local = np.array(mesh["vertices"])[:, :3]
        world = np.array(profile["world"])[joint]
        posed = local @ world[:3, :3].T + world[:3, 3]
        assert np.allclose(posed, donor()["pos"][wanted], atol=1e-6)
    a, b = original["models"][15], rebuilt["models"][15]
    assert chr_data[a["offset"]:a["end_offset"]] == result["chr_data"][b["offset"]:b["end_offset"]]
    assert rebuilt["models"][0]["meshes"][0]["triangles"] == []
    assert rebuilt["models"][0]["vertex_count"] == 3


@pytest.mark.parametrize("mutation,match", [
    (lambda p: p.update(executable_sha256="wrong"), "different executable"),
    (lambda p: p.update(evidence={}), "evidence is missing"),
    (lambda p: p["roles"].pop("head"), "Missing target roles"),
    (lambda p: p["parent"].__setitem__(0, 1), "cycle"),
    (lambda p: p["world"][0][0].__setitem__(0, 0), "singular"),
    (lambda p: p["emit_models"].update({"0": 15}), "body model"),
])
def test_invalid_target_profiles_are_rejected(mutation, match):
    chr_data, _, profile = native_fixture()
    mutation(profile)
    with pytest.raises(ValueError, match=match):
        S.validate_profile(profile, G.decode_chr(chr_data))


def test_unknown_joint_or_invalid_donor_rejected_before_reintegration():
    chr_data, binary, profile = native_fixture()
    primitive = donor()
    primitive["J"][0, 0] = 17
    with pytest.raises(ValueError, match="without a native model"):
        S.encode_parts(chr_data, binary, [primitive], profile, size_budget=len(chr_data))
    primitive = donor()
    primitive["pos"][0, 0] = np.nan
    with pytest.raises(ValueError, match="finite triangle"):
        S.encode_parts(chr_data, binary, [primitive], profile, size_budget=len(chr_data))


@pytest.mark.parametrize("query,result", [("Kasumi", ("KAS", None)), ("KAS:00", ("KAS", "00")),
                                         ("Ein:1", ("KTE", "01")), ("fighter:KTE:01", ("KTE", "01")),
                                         ("fighter:Lei Fang:03", ("LEI", "03"))])
def test_fighter_names_and_costume_slots(query, result):
    assert S.fighter_slot(query) == result


@pytest.mark.parametrize("query", ["player", "Player", " default ", "", " ",
                                  "fighter:player", "fighter:default", "fighter:"])
def test_ambiguous_fighter_is_rejected_before_disc_build_or_launch(monkeypatch, query):
    from gbox import characters as C, filemods, gdrom
    build_fighter = S.build_fighter

    def unexpected(*args, **kwargs):
        pytest.fail("An unresolved DOA2 player must not read a disc, write a mod, record a target or launch")

    monkeypatch.setattr(gdrom, "GDRom", unexpected)
    monkeypatch.setattr(filemods, "mod_dir", unexpected)
    monkeypatch.setattr(S, "build_fighter", unexpected)
    monkeypatch.setattr(C, "_dc_gdi", unexpected)
    monkeypatch.setattr(C, "_api", unexpected)
    monkeypatch.setattr(C, "_launch", unexpected)
    with pytest.raises(ValueError, match="explicit fighter"):
        S.use(None, {"slug": "sa2_amy_rose"}, {"game_id": "1de2e7634f3161ff"},
              SimpleNamespace(slot=query, x=0.47, y=0.57))
    with pytest.raises(ValueError, match="ein:01"):
        build_fighter("unopened.gdi", "unopened-character", "unwritten-mod", query)


def test_public_characters_use_default_doa2_slot_rejects_before_build_or_launch(monkeypatch):
    from gbox import characters as C, filemods, oot_swap
    meta = {"slug": "sa2_amy_rose", "name": "Amy Rose", "aliases": [], "source": {"game_id": "sa2"}}

    def api(ctx, method, path, **kwargs):
        assert (method, path) == ("GET", "/api/characters")
        return [meta]

    def unexpected(*args, **kwargs):
        pytest.fail("The public DOA2 default route must not create or launch a Kasumi replacement")

    monkeypatch.setattr(C, "_api", api)
    monkeypatch.setattr(C, "_game", lambda *a: {"game_id": "1de2e7634f3161ff", "title": "DOA2LE"})
    monkeypatch.setattr(oot_swap, "tool", lambda *a: None)
    monkeypatch.setattr(filemods, "mod_dir", unexpected)
    monkeypatch.setattr(S, "build_fighter", unexpected)
    monkeypatch.setattr(C, "_launch", unexpected)
    inp = C.CharIn(op="use", character="sa2_amy_rose", game_id="1de2e7634f3161ff", x=0.47, y=0.57)
    assert inp.slot == "player"  # The generic default for other engines is preserved.
    with pytest.raises(ValueError, match="explicit fighter"):
        C.characters_tool(inp, None)


def test_public_characters_use_explicit_ein_c1_preserves_native_target(monkeypatch, tmp_path):
    from gbox import characters as C, filemods, oot_swap
    meta = {"slug": "sa2_amy_rose", "name": "Amy Rose", "aliases": [], "source": {"game_id": "sa2"}}
    observed = {"builds": [], "launches": [], "targets": []}

    def api(ctx, method, path, **kwargs):
        if (method, path) == ("GET", "/api/characters"):
            return [meta]
        assert (method, path) == ("POST", "/api/characters/sa2_amy_rose/targets")
        observed["targets"].append(kwargs["json"])

    def build(gdi, source, output, fighter, costume, **kwargs):
        observed["builds"].append((gdi, source, output, fighter, costume))
        return {"fixture": "native build delegated; no ROM or filesystem changes"}

    def launch(ctx, gid, mod, node):
        observed["launches"].append((gid, mod, node))
        return {"fixture": "launch delegated; no process started"}

    monkeypatch.setattr(C, "_api", api)
    monkeypatch.setattr(C, "_game", lambda *a: {"game_id": "1de2e7634f3161ff", "title": "DOA2LE"})
    monkeypatch.setattr(oot_swap, "tool", lambda *a: None)
    monkeypatch.setattr(C, "library_root", lambda *a: tmp_path / "characters")
    monkeypatch.setattr(C, "_dc_gdi", lambda *a: "owned-original.gdi")
    monkeypatch.setattr(filemods, "mod_dir", lambda *a: tmp_path / "mod-output")
    monkeypatch.setattr(S, "build_fighter", build)
    monkeypatch.setattr(C, "_launch", launch)
    ctx = SimpleNamespace(config=None, progress=lambda *a: None)
    result = C.characters_tool(C.CharIn(op="use", character="sa2_amy_rose", game_id="1de2e7634f3161ff",
                                      slot="ein:01"), ctx)["result"]
    assert observed["builds"] == [("owned-original.gdi", tmp_path / "characters" / "sa2_amy_rose",
                                    tmp_path / "mod-output", "KTE", "01")]
    assert observed["targets"][0]["slot"] == "fighter:KTE:01"
    assert observed["launches"] == [("1de2e7634f3161ff", "doa2_kte01_sa2_amy_rose", C.HOST_OS)]
    assert result["fighter"] == "KTE" and result["costume"] == "01"
    assert result["gameplay_verified"] is False


def test_rejected_doa2_job_auto_report_preserves_requested_model_and_point(cfg, monkeypatch):
    from fastapi.testclient import TestClient
    from gbox.agent import ChatHub
    from gbox.server import create_app

    # In-process fixture API only: no real provider, worker, save capture or session controls.
    dispatched = []
    monkeypatch.setattr(ChatHub, "post", lambda *args: dispatched.append(args))
    app = create_app(cfg)
    store = app.state.store
    store.put("session", "fixture-ended-session", {"session_id": "fixture-ended-session", "state": "ended",
              "game_id": "1de2e7634f3161ff", "title": "Dead or Alive 2 - Limited Edition (Japan)"})
    inp = {"op": "use", "character": "sa2_amy_rose", "session_id": "fixture-ended-session",
           "slot": "player", "x": 0.47, "y": 0.57}
    store.put("job", "fixture-doa2-rejection", {"id": "fixture-doa2-rejection", "tool": "characters",
              "input": inp, "worker_id": "fixture-worker", "state": "running", "started": time.time(),
              "parent_request_id": None})
    with pytest.raises(ValueError) as rejected:
        S.fighter_slot(inp["slot"])
    client = TestClient(app, headers={"Authorization": f"Bearer {cfg.token()}"})
    response = client.post("/api/workers/fixture-worker/result", json={"job_id": "fixture-doa2-rejection",
                           "ok": False, "error": f"ValueError: {rejected.value}"})
    assert response.status_code == 200 and response.json()["state"] == "failed"
    deadline = time.monotonic() + 2
    reports = []
    while time.monotonic() < deadline:
        reports = [r for r in store.all("request") if (r.get("context") or {}).get("job_id") == "fixture-doa2-rejection"]
        if reports and dispatched:
            break
        time.sleep(0.01)
    assert len(reports) == 1
    report = reports[0]
    assert report["context"]["model"] == "sa2_amy_rose"
    assert report["context"]["moment"] == "x=0.47, y=0.57"
    assert report["context"]["session_id"] == "fixture-ended-session"
    assert "Target: player" in report["body"] and "explicit fighter" in report["body"]
    assert "ein:01" in report["body"]
    assert report["context"]["auto_report"] is True


def test_invalid_costume_and_unknown_fighter_do_not_fall_back_to_kasumi():
    with pytest.raises(ValueError):
        S.fighter_slot("Tina:../1")
    with pytest.raises(ValueError):
        S.fighter_slot("unknown fighter")


def test_merges_costume_script_changes_without_overwriting_other_costumes():
    from gbox.doa2_swap import merge_executable_patches
    assert merge_executable_patches(b'0000', [b'0100', b'0002']) == b'0102'
    with pytest.raises(ValueError, match='Conflicting'):
        merge_executable_patches(b'0000', [b'0100', b'0200'])
    with pytest.raises(ValueError, match='resized'):
        merge_executable_patches(b'0000', [b'0'])


@pytest.mark.parametrize('current', [False, True])
def test_character_use_rebuilds_stale_writer_and_never_certifies_cached_gameplay(tmp_path, monkeypatch, current):
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock
    from gbox import characters, filemods
    (tmp_path / '.gbox-mod.json').write_text(json.dumps({
        'writer_sha256': S.writer_fingerprint() if current else 'older-writer',
        'gameplay_verified': False,
    }))
    build = Mock(return_value={'status': 'built_unverified'})
    monkeypatch.setattr(S, 'build_fighter', build)
    monkeypatch.setattr(filemods, 'mod_dir', lambda *args: tmp_path)
    monkeypatch.setattr(characters, 'library_root', lambda *args: tmp_path)
    monkeypatch.setattr(characters, '_dc_gdi', lambda *args: 'owned.gdi')
    monkeypatch.setattr(characters, '_api', lambda *args, **kwargs: {})
    ctx = SimpleNamespace(config=object(), progress=lambda *args: None)
    inp = SimpleNamespace(slot='Ein', rebuild=False, launch=False)
    result = S.use(ctx, {'slug': 'amy'}, {'game_id': next(iter(S.GAME_IDS))}, inp)
    assert result['status'] == 'built_unverified'
    assert result['gameplay_verified'] is False
    assert build.call_count == (0 if current else 1)
