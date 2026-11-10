"""gbox.skin_swap's whole-model fallback: the path RE6 player arcs take (model payload, not BM/MM/NM map groups)."""
import pytest

from gbox import mt_arc, skin_swap


def test_model_swap_arc_refuses_a_non_arc(tmp_path):
    target = tmp_path / "target.arc"
    donor = tmp_path / "donor.arc"
    target.write_bytes(b"NOT AN ARC")
    donor.write_bytes(b"NOT AN ARC EITHER")
    data, slot, donor_name = skin_swap.model_swap_arc(target, donor)
    assert data is None and slot == "" and donor_name == ""


def test_model_swap_arc_logs_the_failure(tmp_path):
    target = tmp_path / "t.arc"
    donor = tmp_path / "d.arc"
    target.write_bytes(b"NOPE")
    donor.write_bytes(b"NOPE")
    seen = []
    skin_swap.model_swap_arc(target, donor, log=lambda *a, **k: seen.append((a, k)))
    assert seen and seen[0][0][0] == "model_swap_failed"


def test_swap_arc_still_refuses_re6_style_names():
    # a body whose model entries are all named the same has no BM/MM/NM groups, which is what the fallback is for
    assert skin_swap.body_group({}) is None
    with pytest.raises(mt_arc.ArcError):
        mt_arc.parse(b"not an archive")

def test_seed_from_base_copies_exefs_and_romfs(tmp_path, monkeypatch):
    from gbox import switch_mods
    base = tmp_path / "bases" / "base-build"
    (base / "exefs").mkdir(parents=True)
    (base / "exefs" / "main").write_bytes(b"MAIN")
    (base / "romfs" / "nativeNXx64").mkdir(parents=True)
    (base / "romfs" / "nativeNXx64" / "a.arc").write_bytes(b"ARC")
    (base / ".gbox-mod.json").write_text("{}")
    monkeypatch.setattr(switch_mods, "build_dir", lambda cfg, gid, name: base)
    dest = tmp_path / "dest"
    dest.mkdir()
    copied = skin_swap._seed_from_base(object(), "115f9cdbba115432", dest, "base-build")
    assert copied == 2
    assert (dest / "exefs" / "main").read_bytes() == b"MAIN"
    assert (dest / "romfs" / "nativeNXx64" / "a.arc").read_bytes() == b"ARC"
    assert not (dest / ".gbox-mod.json").exists()          # the new build keeps its own marker


def test_seed_from_base_is_a_noop_without_a_base(tmp_path):
    assert skin_swap._seed_from_base(object(), "115f9cdbba115432", tmp_path, "") == 0
    assert skin_swap._seed_from_base(object(), "115f9cdbba115432", tmp_path, "no-such-build") == 0

def test_seed_from_base_is_a_noop_without_a_base(tmp_path, monkeypatch):
    from gbox import switch_mods
    monkeypatch.setattr(switch_mods, "build_dir", lambda cfg, gid, name: tmp_path / "missing")
    assert skin_swap._seed_from_base(object(), "115f9cdbba115432", tmp_path, "") == 0
    assert skin_swap._seed_from_base(object(), "115f9cdbba115432", tmp_path, "no-such-build") == 0

def test_character_code_reads_the_model_path():
    from gbox import mt_arc
    arc = mt_arc.Arc(version=7, entries=[mt_arc.Entry(name="data\\chara\\pl\\pl0200\\model\\pl0200",
                                                     hash=0x241F5DEB, tag=0x40055E3C, size=4, offset=0, data=b"MOD0")])
    blob = mt_arc.build(arc)
    assert skin_swap._character_code(blob) == "0200"
    assert skin_swap._character_code(b"not an arc") is None

def test_swap_models_exposes_the_keep_tag_option():
    import inspect

    from gbox import model_swap
    sig = inspect.signature(model_swap.swap_models)
    assert "keep_tag" in sig.parameters
    assert sig.parameters["keep_tag"].default is True      # the merged-tag behaviour stays the default
