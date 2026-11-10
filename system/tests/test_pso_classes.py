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


@pytest.mark.skipif(not DISC.is_file(), reason="the disc is not on this machine")
def test_the_kind_word_of_a_real_record_names_its_class():
    """The field claim: `kind`'s low byte is the class id, checked on the four city doors in the disc's own set.

    Round 46 identified these four records by position; this asserts that the registry agrees with that identification, so
    the two independent methods -- where a record sits, and what its kind says -- name the same class.
    """
    from gbox import gcdisc, pso_editor as E, pso_setdata as P

    d = gcdisc.GCDisc(str(DISC))
    dol = d.read("PsoV3.dol")
    data, _ = E.W.read_set(d, "map_city00_00o.dat")
    recs = P.records(data)
    expected = {17: "TObjCityDoor_Med", 18: "TObjCityDoor_Shop", 20: "TObjCityDoor_Guild", 21: "TObjCityDoor_Warp"}
    for idx, name in expected.items():
        kind = recs[idx]["kind"]
        assert kind & 0xFF == {"TObjCityDoor_Med": 0x49, "TObjCityDoor_Shop": 0x46,
                              "TObjCityDoor_Guild": 0x47, "TObjCityDoor_Warp": 0x48}[name]
        assert C.name_of(dol, kind) == name
    # and the ids this table leaves empty are the ones the southwest cluster and the pedestal use
    reg = C.registry(dol)
    assert reg[0x41] is None and reg[0x57] is None
    assert recs[13]["kind"] & 0xFF == 0x41 and recs[27]["kind"] & 0xFF == 0x57


# ---- CP7.2: the placement coverage, measured against every set on the disc --------------------------------

def test_the_named_coverage_of_every_placement_on_the_disc():
    """Coverage is bounded by the registry: an id this build leaves empty cannot be labelled, and the holes are named.

    The object-create path (CP7.2) does not dispatch by class id at all - `FUN_8010542c` picks one of five
    constructors from the *payload type* at record+0x10 (table `0x8049eee8`) and the class id only gates creation and
    registers the object (`FUN_80102424`). So there is no per-class constructor table to mine for the remaining ids:
    the named fraction is exactly the registry's.
    """
    import pathlib as _p
    from gbox import gcdisc, pso_classes as C, pso_map_write as W, pso_setdata as P

    disc = _p.Path(r"D:\\gBox\\cache\\mods\\436e0bb84d5337d1\\pso_city_npc_moved"
                   r"\\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    d = gcdisc.GCDisc(str(disc))
    dol = d.read("PsoV3.dol")
    registry = C.registry(dol, slots=0x100)

    sets = dict(W.set_archive_files(d, "object"))
    for name in d.files:
        if name.lower().endswith("o.dat") and name.lower().split("/")[-1].startswith("map_"):
            sets.setdefault(name, (name, 0, d.files[name][1]))
    counts = {}
    total = 0
    for name in sets:
        try:
            data, _where = W.read_set(d, name)
            recs = P.records(data)
        except Exception:                                  # noqa: BLE001 - not every .dat is a placement set
            continue
        for rec in recs:
            index = P.kind_class(rec["kind"])
            name_of = registry.get(index)
            counts[name_of or f"id_{index:#04x}"] = counts.get(name_of or f"id_{index:#04x}", 0) + 1
            total += 1
    assert total > 20000, total                            # every placement set on the disc
    named = sum(n for k, n in counts.items() if not k.startswith("id_"))
    coverage = named / total
    # Measured, disc-wide: 11,963 of 23,371 placements are labelled (0.512). The lane's earlier 84.4 % was a narrower
    # scope; this test pins the whole-disc figure so a change in the registry or the sets shows up as a diff.
    assert 0.50 <= coverage <= 0.52, (round(coverage, 4), total, named)
    for key in counts:
        if key.startswith("id_"):
            index = int(key[3:], 0)
            assert registry.get(index) is None, (key, registry.get(index))
