"""The narrow Peach repair and exact donor/source cache identity, without redistributing owned assets."""
import copy
import hashlib
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from gbox import soulcalibur_dc as D, soulcalibur_swap as W


def donor(root, slug="peach_hd", *, external=False):
    directory = root / slug
    directory.mkdir(parents=True, exist_ok=True)
    gl = {"asset": {"version": "2.0"}}
    if external:
        gl["buffers"] = [{"uri": "mesh.bin", "byteLength": 4}]
        gl["images"] = [{"uri": "texture.png"}]
        (directory / "mesh.bin").write_bytes(b"mesh")
        (directory / "texture.png").write_bytes(b"texture")
        model, data = "model.gltf", json.dumps(gl).encode()
    else:
        model = "peach_hd.glb" if slug == "peach_hd" else "model.glb"
        chunk = json.dumps(gl).encode()
        chunk += b" " * (-len(chunk) % 4)
        data = struct.pack("<III", 0x46546C67, 2, 20 + len(chunk)) + struct.pack("<I4s", len(chunk), b"JSON") + chunk
    (directory / model).write_bytes(data)
    meta = {"slug": slug, "character": "peach" if slug == "peach_hd" else slug, "model": model,
            "rig": {"roles": {"hip": "hip", "head": "head"}}}
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory, data


def plan(slug="peach_hd"):
    return [{"fighter": "IVY", "costume": 1, "entry": 101, "character": slug}]


def test_repair_changes_exactly_three_legacy_choices(tmp_path, monkeypatch):
    _directory, data = donor(tmp_path)
    monkeypatch.setattr(W, "COMPLETE_PEACH_SHA256", hashlib.sha256(data).hexdigest())
    original = copy.deepcopy(W.SONIC_VS_MARIO)
    fixed = W.repaired_assignments(tmp_path)
    changed = {(key, c) for key, choices in original.items() for c, slug in enumerate(choices)
               if fixed[key][c] != slug}
    assert changed == W.PEACH_REPAIR_SLOTS == {("SEU", 1), ("SOP", 1), ("IVY", 1)}
    assert all(fixed[key][c] == "peach_hd" for key, c in changed)
    assert original == W.SONIC_VS_MARIO


def test_missing_or_unreviewed_peach_never_falls_back_to_ds(tmp_path, monkeypatch):
    donor(tmp_path, "sm64ds_peach")
    with pytest.raises(ValueError, match="incomplete sm64ds_peach"):
        W.repaired_assignments(tmp_path)
    directory, data = donor(tmp_path)
    with pytest.raises(ValueError, match="reviewed complete peach_hd"):
        W.repaired_assignments(tmp_path)
    monkeypatch.setattr(W, "COMPLETE_PEACH_SHA256", hashlib.sha256(data).hexdigest())
    meta = json.loads((directory / "meta.json").read_text())
    meta["character"] = "mario"
    (directory / "meta.json").write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="reviewed complete peach_hd"):
        W.repaired_assignments(tmp_path)


def test_recipe_covers_profiles_model_external_assets_source_and_intent(tmp_path):
    directory, _data = donor(tmp_path, "custom", external=True)
    def recipe(**kw):
        return W.build_recipe(tmp_path, kw.get("plan", plan("custom")), kw.get("human", b"human"),
                              kw.get("exe", b"exe"), random_select=kw.get("random", True))
    original = recipe()
    assert recipe() == original
    for name in ("texture.png", "mesh.bin", "model.gltf", "meta.json"):
        path = directory / name
        before = path.read_bytes()
        if path.suffix in (".json", ".gltf"):
            obj = json.loads(before)
            obj["retarget_profiles"] = {"game": {"*": {"head": 1.2}}}
            path.write_text(json.dumps(obj))
        else:
            path.write_bytes(before + b"changed")
        assert recipe()["sha256"] != original["sha256"], name
        path.write_bytes(before)
    assert recipe(human=b"other")["sha256"] != original["sha256"]
    assert recipe(exe=b"other")["sha256"] != original["sha256"]
    assert recipe(random=False)["sha256"] != original["sha256"]
    assert recipe(plan=[plan("custom")[0] | {"costume": 0, "entry": 100}])["sha256"] != original["sha256"]


@pytest.mark.parametrize("uri", ["../outside.png", "https://example.test/a.png", "%2e%2e/outside.png"])
def test_recipe_refuses_external_dependency_escape(tmp_path, uri):
    directory, _data = donor(tmp_path, "custom", external=True)
    gl = json.loads((directory / "model.gltf").read_text())
    gl["images"][0]["uri"] = uri
    (directory / "model.gltf").write_text(json.dumps(gl))
    with pytest.raises(ValueError, match="donor dependenc"):
        W.build_recipe(tmp_path, plan("custom"), b"human", b"exe", random_select=True)


def test_cache_requires_exact_complete_recipe_and_present_image(tmp_path):
    donor(tmp_path)
    recipe = W.build_recipe(tmp_path, plan(), b"human", b"exe", random_select=True)
    cached = {"image": "mod.gdi", "recipe": recipe, "verification": {"ok": True},
              "report": {"costumes": plan(), "failures": []}}
    assert not W.cache_matches(cached, recipe, tmp_path)
    (tmp_path / "mod.gdi").write_text("0\n")
    assert W.cache_matches(cached, recipe, tmp_path)
    for patch in ({"recipe": None}, {"verification": {"ok": False}}, {"image": "../mod.gdi"},
                  {"report": {"costumes": [], "failures": []}},
                  {"report": {"costumes": plan(), "failures": [{"entry": 101}]}},
                  {"report": {"costumes": [plan()[0] | {"character": "sm64ds_peach"}], "failures": []}}):
        assert not W.cache_matches(cached | patch, recipe, tmp_path)


def test_use_roster_default_repaired_identity_and_source_aware_reuse(tmp_path, monkeypatch):
    from gbox import characters as C, filemods, gdrom
    library = tmp_path / "library"
    _directory, data = donor(library)
    monkeypatch.setattr(W, "COMPLETE_PEACH_SHA256", hashlib.sha256(data).hexdigest())
    for slug in {s for choices in W.SONIC_VS_MARIO.values() for s in choices} - {"sm64ds_peach"}:
        donor(library, slug)
    entries = [b""] * (21 * D.GROUP)
    for fighter, costume in W.PEACH_REPAIR_SLOTS:
        entries[W.group_of(fighter) * D.GROUP] = b"costume"
        entries[W.group_of(fighter) * D.GROUP + costume] = b"costume"
    human = D.build_olnk(entries)
    monkeypatch.setattr(gdrom, "GDRom", lambda _path: SimpleNamespace(read=lambda key: human if key == D.HUMAN else b"exe"))
    monkeypatch.setattr(C, "_dc_gdi", lambda *_args: tmp_path / "source.gdi")
    monkeypatch.setattr(C, "library_root", lambda _cfg: library)
    monkeypatch.setattr(C, "_api", lambda *_a, **_kw: None)
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(filemods, "mod_dir", lambda *_args: out)
    builds = []
    def build(_gdi, root, _out, name, rows, **kw):
        builds.append(rows)
        image = out / (name + ".gdi")
        image.write_text("0\n")
        return {"image": image, "reports": rows, "failures": [], "verification": {"ok": True},
                "random_select": None, "recipe": W.build_recipe(root, rows, human, b"exe", random_select=True)}
    monkeypatch.setattr(W, "build_roster", build)
    ctx = SimpleNamespace(config=object(), progress=lambda *_args: None)
    inp = SimpleNamespace(pairs=[], source="", rebuild=False, launch=False)
    game = {"game_id": "c747331797369f74", "title": "SoulCalibur"}
    first = W.use_roster(ctx, {}, game, inp)
    assert first["mod"] == W.PEACH_REPAIR_MOD
    assert len(builds) == 1
    assert {r["character"] for r in builds[0] if r["costume"] == 1} == {"peach_hd"}
    assert W.use_roster(ctx, {}, game, inp)["build"] is None and len(builds) == 1
    meta_path = library / "peach_hd" / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta["retarget_profiles"] = {game["game_id"]: {"*": {"head": 1.1}}}
    meta_path.write_text(json.dumps(meta))
    assert W.use_roster(ctx, {}, game, inp)["build"] is not None and len(builds) == 2
    # Explicit mapping is preserved; the repair only replaces the built-in default's three Peach choices.
    inp.pairs = [{"slot": "fighter:IVY:1", "character": "sonic"}]
    custom = W.use_roster(ctx, {}, game, inp)
    assert custom["roster"] == [{"fighter": "IVY", "costume": 1, "character": "sonic"}]
    assert custom["mod"].startswith("sc_roster_")
    published = (out / ".gbox-mod.json").read_bytes()
    inp.rebuild = True
    def changed_after_plan(*args, **kw):
        result = build(*args, **kw)
        result["recipe"]["sha256"] = "other revision"
        return result
    monkeypatch.setattr(W, "build_roster", changed_after_plan)
    with pytest.raises(ValueError, match="sources changed after planning"):
        W.use_roster(ctx, {}, game, inp)
    assert (out / ".gbox-mod.json").read_bytes() == published


def test_donor_change_during_fitting_stops_before_disc_write(tmp_path, monkeypatch):
    from gbox import gdrom
    directory, _data = donor(tmp_path, "custom")
    monkeypatch.setattr(gdrom, "GDRom", lambda _path: SimpleNamespace(read=lambda key: b"human" if key == D.HUMAN else b"exe"))
    monkeypatch.setattr(D, "EXECUTABLE_SHA256", hashlib.sha256(b"exe").hexdigest())
    monkeypatch.setattr(D, "olnk", lambda _data: [b"costume"])
    def change(*_args):
        meta = directory / "meta.json"
        meta.write_text(meta.read_text() + " ")
        return b"new costume", {"fit": {}}
    monkeypatch.setattr(W, "fit_and_build", change)
    monkeypatch.setattr(gdrom, "patch_gdi", lambda *_a, **_kw: pytest.fail("must not write an unstable source"))
    rows = [plan("custom")[0] | {"entry": 0, "name": "Ivy"}]
    with pytest.raises(ValueError, match="sources changed during fitting"):
        W.build_roster(tmp_path / "source.gdi", tmp_path, tmp_path / "out", "test", rows)


OWNED_LIBRARY = Path("D:/gBox/cache/characters_mirror")


@pytest.mark.skipif(not (OWNED_LIBRARY / "peach_hd/meta.json").is_file(), reason="private complete donor unavailable")
def test_owned_complete_donor_matches_reviewed_hash_and_slots():
    assert W.complete_peach(OWNED_LIBRARY) == "peach_hd"
    fixed = W.repaired_assignments(OWNED_LIBRARY)
    assert {key for key, choices in fixed.items() if "peach_hd" in choices} == {"SEU", "SOP", "IVY"}
