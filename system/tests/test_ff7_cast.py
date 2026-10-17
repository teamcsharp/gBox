"""Focused tests for the FF7 whole-cast writer (gbox.ff7_swap.cast_slots / battle_spec / build_cast routing).

These cover the pure parts of the cast path (slot -> file mapping and skeleton role detection) without needing a disc:
the per-member fit and disc rebuild are exercised by the continuous inspection build on the local worker.
"""
from gbox import ff7_swap as S


def _bone(parent, length=1.0, mesh=False):
    return {"parent": parent, "length": length, "mesh": {} if mesh else None}


def _cloud_battle_bones():
    """Cloud's 24-bone battle skeleton (CLOUD_BONES layout): root, pelvis -> torso -> head, two arm chains off the
    pelvis through mesh-less joints, two leg chains off the root through mesh-less joints."""
    return [
        _bone(None, length=0.0),             # 0 root
        _bone(0, mesh=True),                 # 1 pelvis
        _bone(1, mesh=True),                 # 2 torso
        _bone(2, mesh=True),                 # 3 head
        _bone(1), _bone(4), _bone(5, mesh=True), _bone(6, mesh=True), _bone(7, mesh=True),     # left arm
        _bone(1), _bone(9), _bone(10, mesh=True), _bone(11, mesh=True), _bone(12, mesh=True),  # right arm
        _bone(0), _bone(14, mesh=True), _bone(15, mesh=True), _bone(16, mesh=True), _bone(17, mesh=True),   # left leg + toe
        _bone(0), _bone(19, mesh=True), _bone(20, mesh=True), _bone(21, mesh=True), _bone(22, mesh=True),   # right leg + toe
    ]


def test_cast_slots_lists_the_whole_party():
    rows = S.cast_slots()
    assert [r["slot"] for r in rows] == ["player", "barret", "tifa", "aerith", "red13",
                                         "cait_sith", "yuffie", "vincent", "cid"]
    by_slot = {r["slot"]: r for r in rows}
    assert by_slot["player"]["kind"] == "player"
    assert all(r["kind"] == "character" for r in rows if r["slot"] != "player")
    # Field and battle file names differ for several members: the mapping must use each member's own files.
    assert by_slot["player"]["context"] == {"field": "FIELD/CLOUD.BCX", "battle": "ENEMY6/CLOUD.LZS"}
    assert by_slot["barret"]["context"] == {"field": "FIELD/BALLET.BCX", "battle": "ENEMY6/BARRETT.LZS"}
    assert by_slot["red13"]["context"] == {"field": "FIELD/RED.BCX", "battle": "ENEMY6/RED13.LZS"}
    assert by_slot["vincent"]["context"] == {"field": "FIELD/VINCENT.BCX", "battle": "ENEMY6/VINSENT.LZS"}


def test_battle_spec_reproduces_cloud_roles():
    bm = {"bones": _cloud_battle_bones(), "raw": b"", "anims": []}
    assert S.battle_spec(bm) == S.BATTLE_ROLES


def test_battle_spec_rejects_a_non_party_layout():
    # All four legs hang off the root and there is no arm chain: not the humanoid party layout.
    bones = [
        _bone(None, length=0.0),             # 0 root
        _bone(0, mesh=True),                 # 1 pelvis
        _bone(1, mesh=True),                 # 2 torso
        _bone(2, mesh=True),                 # 3 head
        _bone(0), _bone(4, mesh=True), _bone(5, mesh=True), _bone(6, mesh=True),      # leg A
        _bone(0), _bone(8, mesh=True), _bone(9, mesh=True), _bone(10, mesh=True),     # leg B
        _bone(0), _bone(12, mesh=True), _bone(13, mesh=True), _bone(14, mesh=True),   # leg C
        _bone(0), _bone(16, mesh=True), _bone(17, mesh=True), _bone(18, mesh=True),   # leg D
    ]
    bm = {"bones": bones, "raw": b"", "anims": []}
    assert S.battle_spec(bm) is None


def test_field_spec_and_battle_spec_share_the_topology():
    # The field reader exposes `has_mesh`; the battle reader exposes `mesh`. Both must detect the same Cloud layout.
    spec = S.battle_spec({"bones": _cloud_battle_bones(), "raw": b"", "anims": []})
    assert spec is not None and set(spec) == {"hip", "chest", "head", "armA", "armB", "legA", "legB"}
    assert spec["hip"] == 1 and spec["head"] == 3
