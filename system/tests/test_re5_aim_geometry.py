"""Native low-model aiming follows the actual uEm32 center, without claiming a damage hitbox."""
import math
import struct

import pytest

from gbox.mercs.titles import re5_aim_geometry as G, re5_combat as C, re5_ps3 as R
from test_re5_laserless_fire import scene
from test_re5_mercs import ENEMIES, world


def put(memory, address, data):
    if hasattr(memory, "write"):
        memory.write(address, data)
    else:
        memory.put(address, data)


def native(memory, enemy, *, center=None, radius=140.):
    actor = enemy["ptr"]
    center = center or (enemy["pos"][0] + 10., enemy["pos"][1] + 35., enemy["pos"][2])
    put(memory, actor, struct.pack(">I", G.LICKER_VT))
    put(memory, actor + 0x30, struct.pack(">3f", *enemy["pos"]))
    put(memory, actor + G.MODEL_ACTIVE, struct.pack(">I", 1))
    put(memory, actor + G.BOUNDS, struct.pack(">4f", *center, radius))
    for slot, opd, entry in G.VT_SLOTS:
        put(memory, G.LICKER_VT + slot * 4, struct.pack(">I", opd))
        put(memory, opd, struct.pack(">I", entry))
    for address, code in G.CODE:
        put(memory, address, code)
    return actor


def low_scene():
    memory, state = scene()
    enemy = state["enemies"][0]
    enemy["pos"] = (0., 0., 200.)
    native(memory, enemy, center=(0., 35., 200.))
    enemy["native_aim"] = G.read(memory, enemy)
    return memory, state, enemy


def test_snapshot_reads_the_native_center_instead_of_inventing_a_species_height():
    memory = world(enemies=[((100., 20., 300.), 900, 900)])
    enemy = {"ptr": ENEMIES[0], "pos": (100., 20., 300.)}
    native(memory, enemy, center=(126., 59., 310.), radius=149.)
    observed = R.snapshot(memory)["enemies"][0]
    assert observed["native_aim"]["point"] == [126., 59., 310.]
    assert G.point(observed) == (126., 59., 310.)
    assert observed["native_aim"]["damage_hitbox_verified"] is False
    assert "model bounds" in observed["native_aim"]["source"]


@pytest.mark.parametrize("change", ["code", "vtable_slot", "opd", "inactive", "nan", "radius_zero",
                                     "radius_huge", "distant", "root_mismatch", "short_read"])
def test_unsafe_or_unverified_native_geometry_is_not_a_chest_fallback(change):
    memory, state, enemy = low_scene()
    actor = enemy["ptr"]
    if change == "code": put(memory, G.CODE[0][0], b"\x00")
    elif change == "vtable_slot": put(memory, G.LICKER_VT + 11*4, struct.pack(">I", 0))
    elif change == "opd": put(memory, G.VT_SLOTS[1][1], struct.pack(">I", 0))
    elif change == "inactive": put(memory, actor + G.MODEL_ACTIVE, struct.pack(">I", 0))
    elif change == "nan": put(memory, actor + G.BOUNDS, struct.pack(">f", float("nan")))
    elif change == "radius_zero": put(memory, actor + G.BOUNDS + 12, struct.pack(">f", 0.))
    elif change == "radius_huge": put(memory, actor + G.BOUNDS + 12, struct.pack(">f", 3000.))
    elif change == "distant": put(memory, actor + G.BOUNDS, struct.pack(">3f", 5000., 35., 200.))
    elif change == "root_mismatch": enemy["pos"] = (5000., 0., 200.)
    else:
        original = memory.rd
        memory.rd = lambda address, size: b"\x00" if address == actor + G.BOUNDS else original(address, size)
    enemy["native_aim"] = G.read(memory, enemy)
    assert enemy["native_aim"]["verified"] is False
    assert G.point(enemy) is None


@pytest.mark.parametrize("change", ["type", "active", "center"])
def test_actor_identity_or_geometry_changes_during_read_reject_the_point(change):
    memory, _, enemy = low_scene()
    actor, original, reads = enemy["ptr"], memory.rd, [0]

    def racing(address, size):
        data = original(address, size)
        if address == actor + G.BOUNDS:
            reads[0] += 1
            if reads[0] == 1:
                if change == "type": put(memory, actor, struct.pack(">I", 0x016172B8))
                elif change == "active": put(memory, actor + G.MODEL_ACTIVE, struct.pack(">I", 0))
                else: put(memory, actor + G.BOUNDS, struct.pack(">f", 20.))
        return data

    memory.rd = racing
    assert G.read(memory, enemy)["verified"] is False


def test_unreadable_actor_type_cannot_silently_restore_the_high_aim_estimate():
    memory, _, enemy = low_scene()
    original = memory.rd
    memory.rd = lambda address, size: (_ for _ in ()).throw(OSError("unreadable")) \
        if address == enemy["ptr"] else original(address, size)
    geometry = G.read(memory, enemy)
    assert geometry["requires_native_center"] is True and geometry["verified"] is False


def test_bow_aligned_at_old_humanoid_chest_corrects_down_without_firing(tmp_path):
    memory, state, enemy = low_scene()
    state["camera"] = {"eye": (0., 140., 0.), "at": (0., 110., 200.)}
    memory.writes.clear()
    combat = C.Combat(memory, {}, learn_dir=tmp_path)
    action = combat.tick(state, state["player"], enemy, 1.)
    assert {"l1", "rdown"} <= action["hold"] and "r1" not in action["hold"]
    assert combat.stats["bow_aim_point"] == [0., 35., 200.]
    assert combat.stats["bow_aim_error_deg"][1] < -15.
    assert "damage hitbox unverified" in combat.stats["bow_aim_point_source"]
    assert not memory.writes


def test_bow_releases_at_native_center_and_tracks_changed_animation_center(tmp_path):
    memory, state, enemy = low_scene()
    state["camera"] = {"eye": (0., 140., 0.), "at": (0., 35., 200.)}
    combat = C.Combat(memory, {}, learn_dir=tmp_path)
    assert {"l1", "r1"} <= combat.tick(state, state["player"], enemy, 1.)["hold"]
    native(memory, enemy, center=(35., 50., 200.))
    enemy["native_aim"] = G.read(memory, enemy)
    action = combat.tick(state, state["player"], enemy, 1.1)
    assert "l1" in action["hold"] and "rleft" in action["hold"] and "r1" not in action["hold"]
    assert combat.bow_aim["aim_point"] == [35., 50., 200.]
    assert combat.bow_aim["target_pos"] == [0., 0., 200.]


def test_missing_known_creature_geometry_has_a_bounded_neutral_reacquisition(tmp_path):
    memory, state, enemy = low_scene()
    enemy["native_aim"]["verified"] = False
    combat = C.Combat(memory, {}, learn_dir=tmp_path)
    assert combat.tick(state, state["player"], enemy, 1.) == {"hold": {"l1"}}
    assert combat.tick(state, state["player"], enemy, 1.5) == {"hold": set()}
    assert combat.needs_firing_position and combat.bow_aim is None
    assert "bow_aim_point" not in combat.stats


def test_model_bounds_radius_never_becomes_damage_tolerance(tmp_path):
    memory, state, enemy = low_scene()
    state["camera"] = {"eye": (0., 140., 0.), "at": (0., 35., 200.)}
    combat = C.Combat(memory, {}, learn_dir=tmp_path)
    combat.tick(state, state["player"], enemy, 1.)
    expected = [round(math.degrees(x), 3) for x in C.bow_tolerance(math.dist((0., 140., 0.), (0., 35., 200.)))]
    assert combat.stats["bow_aim_tolerance_deg"] == expected
    native(memory, enemy, center=(0., 35., 200.), radius=1000.)
    enemy["native_aim"] = G.read(memory, enemy)
    combat.tick(state, state["player"], enemy, 1.1)
    assert combat.stats["bow_aim_tolerance_deg"] == expected


def test_other_actor_classes_keep_existing_behavior_without_claiming_native_geometry():
    memory = world(enemies=[((0., 0., 1000.), 800, 800)])
    observed = R.snapshot(memory)["enemies"][0]
    assert "native_aim" not in observed
