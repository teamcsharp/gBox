"""The object-class registry: a placement's class index -> its class name (A3)."""
import struct

import pytest

from gbox import pso_class_registry as R


def test_the_four_walked_lobby_doors_are_the_four_door_kinds():
    # measured live (docs/research/pso-gc-pioneer2-rooms.md, round 22/29): kind 0x46 Shop, 0x47 Guild, 0x48 Warp,
    # 0x49 Med. They are what pinned the table's base and stride.
    assert [R.label(k) for k in (0x46, 0x47, 0x48, 0x49)] == [
        "TObjCityDoor_Shop", "TObjCityDoor_Guild", "TObjCityDoor_Warp", "TObjCityDoor_Med"]
    assert R.label(0x4a) == "TObjCityDoor_Lobby"


def test_the_registry_names_the_classes_the_editor_needs():
    assert R.name(0x00) == "TORockCaveBL02"
    assert R.name(0x02) == "TOSensor"
    assert R.name(0x10) == "TOSwitchAttack"
    assert R.name(0x11) == "TOSwitchAttackSub"
    assert R.name(0x12) == "TOSwitchItem"
    assert R.name(0x18) == "TOTrap"
    assert R.name(0x40) == "TObjCamera"
    assert R.name(0x44) == "TObjCityAirCar_Ctrl"
    assert R.index_of("TObjCityDoor_Guild") == 0x47
    assert R.index_of("no such class") is None


def test_an_empty_slot_is_reported_not_invented():
    holes = [i for i in (0x05, 0x06, 0x08, 0x0a, 0x0c, 0x0e, 0x13, 0x1e, 0x22, 0x4b, 0x61, 0x67, 0x74, 0xc4, 0xc5, 0xc8)]
    assert all(R.name(i) is None for i in holes)
    assert R.label(0x06) == "class_0x06"
    assert sum(1 for t in R.CLASS_NAMES if t) == 148


def test_the_index_is_the_low_byte_of_a_placement_kind():
    # kinds carry flags in the high bits (SETDATA documents 12 distinct flag patterns)
    assert R.class_index(0x2000000 | 0x47) == 0x47
    assert R.label(0x2000100 | 0x12) == "TOSwitchItem"
    assert R.label(0xFF) == "class_0xff"                      # out of the named range
    assert R.name(-1) is None and R.name(240) is None


# ---- the derivation from a DOL image ---------------------------------------------------------------------------------------

def _synthetic_dol(names, base=0x80000000):
    """A minimal DOL with a class table of `names` (None = empty slot) at `base`."""
    section_off, section_size = 0x2000, 0x2000
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x00, section_off)
    struct.pack_into(">I", header, 0x48, base)
    struct.pack_into(">I", header, 0x90, section_size)
    body = bytearray(section_size)
    strings_at = base + R.SLOTS * 4 + 0x40
    cursor = strings_at
    for i, name in enumerate(names):
        if name is None:
            struct.pack_into(">I", body, i * 4, 0)
            continue
        struct.pack_into(">I", body, i * 4, cursor)
        encoded = name.encode() + b"\0"
        body[cursor - base:cursor - base + len(encoded)] = encoded
        cursor += len(encoded)
    return bytes(header) + bytes(section_off - len(header)) + bytes(body)


def _patched_table(names):
    """R.derive reads TABLE_ADDRESS; point it at the synthetic base for the test."""
    return list(names)


def test_derive_reads_a_table_in_the_executable_layout(monkeypatch):
    names = ["TORockCaveBL02", "TOSensor", None, "TOSwitchAttack"] + [None] * (R.SLOTS - 4)
    image = _synthetic_dol(names)
    monkeypatch.setattr(R, "TABLE_ADDRESS", 0x80000000)
    assert R.derive(image) == tuple(names)


def test_a_changed_table_is_reported_instead_of_trusted(monkeypatch):
    names = ["TOSwitchItem"] + [None] * (R.SLOTS - 1)
    image = _synthetic_dol(names)
    monkeypatch.setattr(R, "TABLE_ADDRESS", 0x80000000)
    report = R.verify(image)
    assert report["ok"] is False
    assert report["mismatches"][0]["slot"] == 0 and report["mismatches"][0]["image"] == "TOSwitchItem"


def test_an_address_outside_the_image_is_an_error_not_a_crash():
    with pytest.raises(R.RegistryError):
        R.derive(bytes(0x100))


# ---- the vtable census: which classes this build actually instantiates -----------------------------------------------------

def test_the_executable_instantiates_only_a_third_of_its_class_names():
    assert len(R.instantiated()) == 38
    assert R.VTABLES[6] == 0x804B4280 and R.VTABLES[8] == 0x804B4308
    assert R.VTABLES[46] == 0x804B53D8 and R.VTABLES[197] == 0x804B9000


def test_the_object_classes_are_not_cpp_objects_with_vtables():
    # no vtable header anywhere points at these slots - the finding that redirected A7 to the event/AreaWarp path
    for index in (0x5C, 0x5D, 0x5E, 0x48, 0x02, 0x10, 0xC9, 0xCA, 0xCB):
        assert R.vtable(index) is None
    assert "TObjCityMainWarp" == R.name(0x5C) and "TObjCityAreaWarp" == R.name(0x5D)


def test_the_named_classes_are_not_the_vtable_ones():
    named = {index for index in R.instantiated() if R.name(index)}
    assert named == set()                      # every vtable slot is a slot this name table leaves empty
    assert len(R.instantiated()) < sum(1 for name in R.CLASS_NAMES if name)


def _dol_with_vtable_headers(slots):
    """A DOL with one data section holding a vtable header for each slot."""
    section_va, section_off, section_size = 0x804B0000, 0x200, 0x100
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x00, section_off)
    struct.pack_into(">I", header, 0x48, section_va)
    struct.pack_into(">I", header, 0x90, section_size)
    body = bytearray(section_size)
    for i, slot in enumerate(slots):
        struct.pack_into(">I", body, i * 0x40, R.TABLE_ADDRESS + slot * 4)
    return bytes(header) + bytes(section_off - len(header)) + bytes(body)


def test_derive_vtables_reads_a_header_census():
    image = _dol_with_vtable_headers([6, 8, 46])
    found = R.derive_vtables(image)
    assert sorted(found) == [6, 8, 46]
    assert found[46] == [0x804B0080]


def test_a_census_that_differs_from_the_pinned_one_is_reported():
    image = _dol_with_vtable_headers([6])
    report = R.verify_vtables(image)
    assert report["ok"] is False
    assert any(m.get("why") == "no vtable header in the image" for m in report["mismatches"])


def test_the_real_disc_census_matches_the_pinned_one():
    import pathlib
    from gbox import gcdisc
    disc = pathlib.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                        r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    dol = gcdisc.GCDisc(str(disc)).read("PsoV3.dol")
    report = R.verify_vtables(dol)
    assert report["ok"] is True, report["mismatches"][:3]
