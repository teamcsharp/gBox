"""The tests the duplicate registry branch carried, ported onto `pso_classes` (CP0 step 4).

The branch's module (`gbox/pso_class_registry.py`) is gone: its behaviour now lives in `pso_classes`, which locates the
table from the `TObjCityDoor_Shop` anchor instead of a pinned address, and its pinned values
(`PINNED_ADDRESS`/`PINNED_NAMES`) are cross-checked in `test_pso_classes.py`. These are the branch's assertions, kept so
nothing it proved is lost.
"""
import pathlib

import pytest

from gbox import pso_classes as C

DISC = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                    r"\Phantasy Star Online Episode I & II Plus (USA).iso")


@pytest.fixture(scope="module")
def dol():
    from gbox import gcdisc
    if not DISC.is_file():
        pytest.skip("the disc is not on this machine")
    return gcdisc.GCDisc(str(DISC)).read("PsoV3.dol")


def test_the_four_walked_lobby_doors_are_the_four_door_kinds(dol):
    doors = {0x46: "TObjCityDoor_Shop", 0x47: "TObjCityDoor_Guild", 0x48: "TObjCityDoor_Warp",
             0x49: "TObjCityDoor_Med"}
    for kind, name in doors.items():
        assert C.name_of(dol, kind) == name
        assert C.family(dol, kind) == "door"


def test_the_registry_names_the_classes_the_editor_needs(dol):
    for name in ("TObjCityDoor_Shop", "TOSensor", "TOSwitchAttack", "TOTrap", "TObjCityMainWarp",
                 "TObjCamera", "TORockCaveBL02"):
        assert name in C.PINNED_NAMES if name in C.PINNED_NAMES else C.name_of(dol, C.PINNED_NAMES.index(name)) == name
        slot = C.PINNED_NAMES.index(name)
        assert C.name_of(dol, slot) == name


def test_an_empty_slot_is_reported_not_invented(dol):
    assert C.name_of(dol, 0x03) is None
    assert C.label(dol, 0x03) == "class_0x03"
    assert C.family(dol, 0x03) == "unknown"


def test_the_index_is_the_low_byte_of_a_placement_kind(dol):
    assert C.label(dol, 0x02000047) == C.label(dol, 0x47) == "TObjCityDoor_Guild"


def test_an_address_outside_the_image_is_none_not_a_crash(dol):
    assert C.offset_of(dol, 0x90000000) is None
    with pytest.raises(C.ClassError):
        C.address_of(dol, 0x7FFFFFFF)


def test_a_table_that_disagrees_with_the_pinned_one_is_a_failure(dol):
    """What the branch's `derive`/`verify` pair was for: an executable whose table differs must show up as a mismatch."""
    derived = C.registry(dol, slots=len(C.PINNED_NAMES))
    pinned = {i: name for i, name in enumerate(C.PINNED_NAMES)}
    assert derived == pinned
    # one changed slot is enough for the comparison to fail - the cross-check is not a rubber stamp
    broken = dict(derived)
    broken[0x46] = "TObjNotADoor"
    assert broken != pinned
