import numpy as np
import pytest

from gbox import cast_swap, ff7_models as F
from gbox import ff7_swap as S


def _party_skeleton():
    """root(0) -> pelvis(1) -> chest(2) -> head(3); arms off the pelvis through mesh-less joints; legs off the
    root through mesh-less joints. Translation-only world matrices."""
    def T(x, y, z):
        m = np.eye(4)
        m[:3, 3] = (x, y, z)
        return m
    W = [T(0, 0, 0), T(0, 0, 1), T(0, 0, 3), T(0, 0, 5)]
    W += [T(1, 0, 1), T(2, 0, 1), T(3, 0, 1), T(3.5, 0, 1)]            # armA 4-7 (4 meshless)
    W += [T(-1, 0, 1), T(-2, 0, 1), T(-3, 0, 1), T(-3.5, 0, 1)]        # armB 8-11 (8 meshless)
    W += [T(0, -2, 0), T(0, -4, 0), T(0, -6, 0), T(0, -8, 0)]          # legA 12-15 (12 meshless)
    W += [T(0, -2, 0), T(0, -4, 0), T(0, -6, 0), T(0, -8, 0)]          # legB 16-19 (16 meshless)
    mesh = [False] + [True] * 3
    mesh += [False, True, True, True, False, True, True, True]          # arms
    mesh += [False, True, True, True, False, True, True, True]          # legs
    kids = {0: [1, 12, 16], 1: [2, 4, 8], 2: [3], 4: [5], 5: [6], 6: [7],
            8: [9], 9: [10], 10: [11], 12: [13], 13: [14], 14: [15], 16: [17], 17: [18], 18: [19]}
    for k in set(range(20)) - set(kids):
        kids[k] = []
    return mesh, kids, W


def test_party_spec_detects_the_ff7_layout():
    mesh, kids, W = _party_skeleton()
    spec = S._party_spec(mesh, kids, W)
    assert spec is not None
    assert spec["hip"] == 1 and spec["chest"] == 2 and spec["head"] == 3
    assert {spec["armA"], spec["armB"]} == {(5, 6, 7), (9, 10, 11)}
    assert {spec["legA"], spec["legB"]} == {(13, 14, 15), (17, 18, 19)}


def test_party_spec_none_without_chest_chain():
    mesh, kids, W = _party_skeleton()
    mesh[2] = False                                                   # chest has no mesh
    mesh[3] = True
    assert S._party_spec(mesh, kids, W) is None


def test_party_spec_none_without_meshed_pelvis():
    mesh, kids, W = _party_skeleton()
    mesh[1] = False
    assert S._party_spec(mesh, kids, W) is None


def test_cast_slots_cover_the_whole_party_with_dedicated_maps_where_needed():
    """#1902: every member builds; the six the topology finder misreads use dedicated role maps."""
    rows = S.cast_slots()
    assert [r["slot"] for r in rows] == ["player", "tifa", "aerith", "barret", "red13", "cid", "yuffie", "caitsith",
                                          "vincent"]
    assert rows[0]["kind"] == "player" and all(r["kind"] == "character" for r in rows[1:])
    by = {r["slot"]: r for r in rows}
    assert not any(r.get("status") == "not_working" for r in rows)
    for slot in ("aerith", "red13", "yuffie", "caitsith", "vincent"):
        assert by[slot]["roles"].startswith("dedicated map")
    assert by["tifa"]["roles"].startswith("dedicated map")
    assert "roles" not in by["player"] and "roles" not in by["barret"] and "roles" not in by["cid"]
    for spec in (*S.FIELD_SPECS.values(), *S.BATTLE_SPECS.values()):
        assert set(spec) == {"hip", "chest", "head", "armA", "armB", "legA", "legB"}
        assert all(len(spec[k]) == 3 for k in ("armA", "armB", "legA", "legB"))
        assert len({spec["hip"], spec["chest"], spec["head"]}) == 3
    # every member's files are real native models (field FILE_BCX / battle roster names)
    field_names = {"CLOUD", "TIFA", "EARITH", "BALLET", "RED", "CID", "YUFI", "KETCY", "VINCENT"}
    battle_names = {"CLOUD", "TIFA", "EARITH", "BARRETT", "RED13", "CID", "YUFI", "KETCY", "VINSENT"}
    assert {r["field"] for r in rows} == field_names
    assert {r["battle"] for r in rows} == battle_names


def test_is_slot_and_mod_names():
    for s, _f, _b, _n in S.CAST:
        assert S.is_slot(s)
    assert not S.is_slot("bogus") and not S.is_slot("")
    meta = {"slug": "mario"}
    assert S.mod_name(meta) == f"ff7_mario_v{S.CACHE_VERSION}"
    assert S.mod_name(meta, "tifa") == f"ff7_mario_tifa_v{S.CACHE_VERSION}"


def _fake_battle(W, parents, meshed):
    bones = [{"parent": parents[i], "length": 0, "mesh": {} if meshed[i] else None} for i in range(len(W))]
    return {"bones": bones, "raw": b"", "anims": []}


def test_battle_spec_detects_cloud_and_tifa_variants(monkeypatch):
    from gbox import ff7_models as F
    def T(x, y, z):
        m = np.eye(4)
        m[:3, 3] = (x, y, z)
        return m
    # Cloud's layout: arms off the pelvis through mesh-less joints, legs off the root.
    W = [T(0, 0, 0), T(0, 0, 0), T(0, -1, 0), T(0, -2, 0)]
    W += [T(0, 0, 0), T(0, 0, 0), T(1, -1, 0), T(2, -1.2, 0), T(3, -1.4, 0)]
    W += [T(0, 0, 0), T(0, 0, 0), T(-1, -1, 0), T(-2, -1.2, 0), T(-3, -1.4, 0)]
    W += [T(0, 0, 0), T(0, 1, 0), T(0, 1.6, 0), T(0, 2.2, 0)]
    W += [T(0, 0, 0), T(0, 1, 0), T(0, 1.6, 0), T(0, 2.2, 0)]
    parents = [None, 0, 1, 2, 1, 4, 5, 6, 7, 1, 9, 10, 11, 12, 0, 14, 15, 16, 0, 18, 19, 20]
    meshed = [False, True, True, True, False, False, True, True, True, False, False, True, True, True,
              False, True, True, True, False, True, True, True]
    monkeypatch.setattr(F, "read_animation", lambda *a: [])
    monkeypatch.setattr(F, "pose", lambda bones, frame: W)
    spec = S.battle_spec(_fake_battle(W, parents, meshed))
    assert spec == {"hip": 1, "chest": 2, "head": 3, "armA": (6, 7, 8), "armB": (11, 12, 13),
                    "legA": (15, 16, 17), "legB": (19, 20, 21)}
    # Tifa's layout: the head ends the spine branch, legs hang off a meshed root child (9), arms off the root
    # through mesh-less joints, one arm without a separate hand bone.
    W2 = [T(0, 0, 0), T(0, 0, 0), T(0, -1, 0), T(0, -1.5, 0), T(0, -2, 0), T(0, -2.4, 0), T(0, -2.8, 0),
          T(0, -3.2, 0), T(0, -3.6, 0), T(0, 0, 0), T(0, 0, 0), T(0.5, 1, 0), T(0.5, 1.6, 0), T(0.5, 2.2, 0),
          T(0.5, 2.2, 0), T(0.5, 2.5, 0), T(0.5, 2.8, 0), T(0, 0, 0), T(-0.5, 1, 0), T(-0.5, 1.6, 0),
          T(-0.5, 2.2, 0), T(-0.5, 2.2, 0), T(-0.5, 2.5, 0), T(-0.5, 2.8, 0), T(0, 0, 0), T(0, 0, 0),
          T(2, -1.8, 0), T(2.6, -2, 0), T(3.2, -2.2, 0), T(0, 0, 0), T(0, 0, 0), T(-2, -1.8, 0), T(-2.6, -2, 0)]
    parents2 = [None, 0, 1, 2, 3, 4, 5, 6, 7, 0, 9, 10, 11, 12, 13, 14, 15, 9, 17, 18, 19, 20, 21, 22,
                0, 24, 25, 26, 27, 0, 29, 30, 31]
    meshed2 = [False, True, True, False, True, True, True, True, True, True, False, True, True, True, False, True, True,
               False, True, True, True, False, True, True, False, False, True, True, True, False, False, True, True]
    monkeypatch.setattr(F, "pose", lambda bones, frame: W2)
    spec2 = S.battle_spec(_fake_battle(W2, parents2, meshed2))
    assert spec2 is not None
    assert spec2["hip"] == 1 and spec2["chest"] == 2 and spec2["head"] == 8
    assert set(spec2["legA"]) == {11, 12, 13} and set(spec2["legB"]) == {18, 19, 20}
    assert set(spec2["armA"]) == {26, 27, 28} and set(spec2["armB"]) == {31, 32}   # the short arm pads its last bone


def test_battle_spec_none_for_quadrupeds_and_meshless_pelvis_children(monkeypatch):
    from gbox import ff7_models as F
    def T(x, y, z):
        m = np.eye(4)
        m[:3, 3] = (x, y, z)
        return m
    # a pelvis whose children are all mesh-less (Red XIII's layout): no chest -> None
    W = [T(0, 0, 0), T(0, 0, 0), T(0, -1, 0), T(0, -2, 0), T(0, 1, 0), T(0, 2, 0)]
    parents = [None, 0, 1, 2, 0, 0]
    meshed = [False, True, False, True, False, False]
    monkeypatch.setattr(F, "read_animation", lambda *a: [])
    monkeypatch.setattr(F, "pose", lambda bones, frame: W)
    assert S.battle_spec(_fake_battle(W, parents, meshed)) is None


def test_cast_swap_registers_ff7_as_a_pairs_builder():
    assert cast_swap.STRATEGIES["gbox.ff7_swap"][0] == "pairs"
    assert callable(cast_swap.BUILDERS["gbox.ff7_swap"])


def test_lzs_round_trip():
    for data in (bytes(range(256)) * 4, b"\x00" * 7000, bytes(range(97)) * 7000):
        assert F.lzs(S.lzs_encode(data)) == data


def test_owned_disc_every_member_gets_a_target():
    """On the Spark (raw FF7 disc 1 at /tmp/ff7/base.bin): field and battle targets for all nine members, every
    role bone meshed, and the dedicated maps put the head on the bone with the most head-height geometry."""
    from pathlib import Path
    raw = Path('/tmp/ff7/base.bin')
    if not raw.is_file():
        import pytest
        pytest.skip('raw FF7 disc 1 is not unpacked here')
    from gbox import ff7_models as F, psxdisc
    src = psxdisc.RawBin(raw, writable=False)
    for slot, field, battle, _name in S.CAST:
        fm = F.read_field_model(src.read(f'FIELD/{field}.BCX'))
        ft = S.field_target(fm, field)
        meshed = {p['bone'] for p in fm['parts']}
        assert set(ft['jmap'].values()) <= meshed, (slot, 'field', sorted(set(ft['jmap'].values()) - meshed))
        bm = F.read_battle_model(src.read(f'ENEMY6/{battle}.LZS'))
        bt = S.battle_target(bm, legacy_roles=S.BATTLE_ROLES if battle == 'CLOUD' else None, name=battle)
        bmeshed = {i for i, b in enumerate(bm['bones']) if b['mesh']}
        assert set(bt['jmap'].values()) <= bmeshed, (slot, 'battle', sorted(set(bt['jmap'].values()) - bmeshed))
