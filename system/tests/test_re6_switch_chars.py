"""re6_switch_chars: the RE6 Switch native body reader for characters op=collect.

Registration (DEDICATED + the game-id gate), the roster fallback when the RomFS dump is absent,
and the id->joint binding math on synthetic data - the parts that must hold on any node. The
arc-to-GLB path itself is exercised on a node with the RomFS dump (tests/test_re6_switch_models.py
skips there the same way).
"""
import numpy as np
import pytest

from gbox import characters, re6_switch_chars


def test_registered_in_dedicated():
    names = [name for name, _t, _r, _run in characters.DEDICATED]
    assert "re6_switch" in names


def test_reader_matches_switch_edition_only():
    game = {"title": "Resident Evil 6", "platform": "switch", "game_id": "115f9cdbba115432"}
    hit = [n for n, test, _r, _run in characters.DEDICATED
           if characters.reader_matches(n, test, game)]
    assert hit == ["re6_switch"]
    for other in ({"title": "Resident Evil 6", "platform": "ps3"},
                  {"title": "Resident Evil 6", "platform": "x360"},
                  {"title": "Resident Evil 5", "platform": "switch"}):
        assert "re6_switch" not in [n for n, test, _r, _run in characters.DEDICATED
                                    if characters.reader_matches(n, test, other)]


def test_game_id_gate_blocks_other_re6_builds():
    assert characters.dedicated_entries(_cfg(), {"title": "Resident Evil 6", "platform": "switch",
                                                 "game_id": "deadbeefdeadbeef"}, "re6_switch",
                                        re6_switch_chars.roster) == []
    entries = characters.dedicated_entries(_cfg(), {"title": "Resident Evil 6", "platform": "switch",
                                                    "game_id": "115f9cdbba115432"}, "re6_switch",
                                           re6_switch_chars.roster)
    assert entries and all(e["slug"].startswith("re6sw_") for e in entries)


def _cfg():
    class C:
        cache = "/nonexistent"
    return C()


def test_roster_fallback_without_romfs(monkeypatch, tmp_path):
    monkeypatch.delenv("GBOX_RE6_SWITCH_ROMFS", raising=False)
    monkeypatch.setattr(re6_switch_chars, "locate_romfs", lambda *a: None)
    entries = re6_switch_chars.roster()
    assert len(entries) == 9                                  # one default slot per canonical character
    assert all(e["key"].endswith(":default") for e in entries)
    leon = next(e for e in entries if e["key"] == "leon:default")
    assert leon["slug"] == "re6sw_leon_default" and "Leon" in leon["name"]


def test_roster_uses_romfs_slots(monkeypatch, tmp_path):
    monkeypatch.setenv("GBOX_RE6_SWITCH_ROMFS", str(tmp_path))
    (tmp_path / "nativeNXx64" / "arc" / "NX").mkdir(parents=True)
    (tmp_path / "nativeNXx64" / "arc" / "NX" / "uPl00LeonUsa.arc").write_bytes(b"x")
    entries = re6_switch_chars.roster()
    assert [(e["key"], e["slug"]) for e in entries] == [("leon:Usa", "re6sw_leon_usa")]


def test_id_to_index_prefers_first():
    assert re6_switch_chars._id_to_index([1, 2, 2, 255]) == {1: 0, 2: 1, 255: 3}


def test_bind_maps_ids_and_normalises_weights():
    ids_to_idx = {1: 0, 7: 3}
    J, W = re6_switch_chars._bind([(1, 7), (255, 0), (1, 0)],
                                  [(0.75, 0.25), (1.0, 0.0), (0.5, 0.5)], ids_to_idx, fallback=9, count=3)
    assert J[0].tolist() == [0, 3, 9, 9]                      # ids via the anim map, unfilled slots fall back
    assert W[0].tolist() == [0.75, 0.25, 0.0, 0.0]
    assert J[1].tolist() == [9, 9, 9, 9] and abs(W[1, 0] - 1.0) < 1e-6   # unknown id -> fallback, weight 1
    assert J[2].tolist() == [0, 9, 9, 9]                      # zero-weight influence dropped


def test_bind_without_weights_binds_to_id():
    J, W = re6_switch_chars._bind([(7,), (1,)], [], {1: 0, 7: 3}, fallback=9, count=2)
    assert J[0].tolist() == [3, 9, 9, 9] and J[1].tolist() == [0, 9, 9, 9]
    assert np.allclose(W.sum(axis=1), 1.0)


def test_reader_version_registered():
    assert characters.reader_version("re6_switch") == re6_switch_chars.READER_VERSION


def test_extract_run_requires_romfs(monkeypatch):
    monkeypatch.delenv("GBOX_RE6_SWITCH_ROMFS", raising=False)
    monkeypatch.setattr(re6_switch_chars, "locate_romfs", lambda *a: None)

    class Ctx:
        config = None
        def progress(self, *_a):
            pass
    with pytest.raises(Exception, match="RomFS"):
        re6_switch_chars.extract_run(Ctx(), {"title": "Resident Evil 6"}, {"key": "leon:default",
                                                                            "slug": "re6sw_leon_default"}, None)


def test_default_slot_prefers_usa_over_debug(monkeypatch):
    """Live acceptance on the real RomFS picked DebugId arcs over the real default bodies once;
    the fallback must prefer *Usa, then a plain *A body, over sorted-first debug slots."""
    from pathlib import Path
    slots = {("leon", "DebugId"): Path("uPl00LeonDebugId.arc"), ("leon", "Usa"): Path("uPl00LeonUsa.arc"),
             ("ada", "Omake00"): Path("uPl06AdaOmake00.arc"), ("ada", "A"): Path("uPl06AdaA.arc")}
    chosen = {}
    monkeypatch.setattr(re6_switch_chars, "_arc_slots", lambda _romfs: slots)
    monkeypatch.setattr(re6_switch_chars, "locate_romfs", lambda *a: Path("romfs"))

    def fake_extract(path, _out, _name):
        chosen["path"] = path
        return {"gltf": _out, "vertices": 1, "triangles": 1, "joints": 1, "roles": {}}

    monkeypatch.setattr(re6_switch_chars, "extract", fake_extract)

    class Ctx:
        config = None
        def progress(self, *_a):
            pass
    for key, want in [("leon:default", "uPl00LeonUsa.arc"), ("ada:default", "uPl06AdaA.arc")]:
        re6_switch_chars.extract_run(Ctx(), {"title": "Resident Evil 6"},
                                     {"key": key, "slug": key.replace(":", "_"), "name": key.split(":")[0]},
                                     Path("."))
        assert chosen["path"].name == want
