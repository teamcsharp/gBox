"""gbox.pso_classes: the executable's object-class registry, calibrated against the placement records."""
from pathlib import Path

import pytest

from gbox import pso_classes as C

DISC = Path(r"D:\gBox\cache\436e0bb84d5337d1\Phantasy Star Online Episode I & II Plus (USA).gcz")


def make_dol(names: dict[int, str], base=0x8000C000, code_start=0x100):
    """A synthetic executable whose registry holds ``names`` at their slots and names them at the end of the file."""
    table = bytearray(0x400)
    blob = bytearray()
    # the blob's *address* is the base plus its distance from the code start, i.e. len(table) + 0x100
    addr_base = base + len(table) + 0x100
    for slot, name in names.items():
        addr = addr_base + len(blob)
        table[slot * 4:slot * 4 + 4] = addr.to_bytes(4, "big")
        blob += name.encode("ascii") + b"\x00"
    head = bytearray(code_start)
    head[0:4] = code_start.to_bytes(4, "big")
    head[0x48:0x4C] = base.to_bytes(4, "big")
    return bytes(head) + bytes(table) + b"\x00" * 0x100 + bytes(blob)


def test_the_registry_is_found_from_the_shop_anchor_and_names_its_slots():
    dol = make_dol({0x46: "TObjCityDoor_Shop", 0x47: "TObjCityDoor_Guild", 0x48: "TObjCityDoor_Warp"})
    reg = C.registry(dol)
    assert reg[0x46] == "TObjCityDoor_Shop"
    assert reg[0x47] == "TObjCityDoor_Guild"
    assert reg[0x48] == "TObjCityDoor_Warp"
    assert reg[0x40] is None


def test_name_of_masks_the_flags_out_of_a_kind_word():
    # the Shop anchor is what locates the table, so a synthetic registry must carry it
    dol = make_dol({0x46: "TObjCityDoor_Shop", 0x47: "TObjCityDoor_Guild"})
    assert C.name_of(dol, 0x02000047) == "TObjCityDoor_Guild"
    assert C.name_of(dol, 0x47) == "TObjCityDoor_Guild"
    assert C.name_of(dol, 0x02000040) is None


def test_an_executable_without_the_anchor_is_refused():
    with pytest.raises(C.ClassError, match="is not in this executable"):
        C.table_offset(b"\x00" * 0x200)


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_real_registry_names_the_city_classes_in_the_order_round_46_measured():
    """The calibration is the whole claim: Shop/Guild/Warp/Med must land on 0x46..0x49 in the real executable."""
    from gbox import gcdisc

    d = gcdisc.GCDisc(str(DISC))
    dol = d.read("PsoV3.dol")
    reg = C.registry(dol)
    assert reg[0x46] == "TObjCityDoor_Shop"
    assert reg[0x47] == "TObjCityDoor_Guild"
    assert reg[0x48] == "TObjCityDoor_Warp"
    assert reg[0x49] == "TObjCityDoor_Med"
    assert reg[0x4A] == "TObjCityDoor_Lobby"
    assert reg[0x44] == "TObjCityAirCar_Ctrl"
    assert reg[0x45] == "TObjCityAirCar_Car"
    assert reg[0x40] == "TObjCamera"
    # the two objects round 46 called a plain `TObject` are a flying car and its controller
    assert C.name_of(dol, 0x02000044) == "TObjCityAirCar_Ctrl"
    assert sum(1 for n in reg.values() if n) < len(reg)      # the array is sparse, not ragged
