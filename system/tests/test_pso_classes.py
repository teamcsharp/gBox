"""gbox.pso_classes: the executable's object-class registry, calibrated against the placement records."""
import struct
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
# ---- families, labels and the vtable census ---------------------------------------------------------------------------------

def test_family_groups_the_classes_the_editor_colours_by():
    dol = make_dol({0x46: "TObjCityDoor_Shop", 0x5C: "TObjCityMainWarp", 0x10: "TOSwitchAttack",
                    0x18: "TOTrap", 0x02: "TOSensor", 0x40: "TObjCamera", 0x00: "TORockCaveBL02",
                    0x4C: "TObjCity_Season_EasterEgg", 0xCF: "TObjWarpBoss", 0x60: "TObjBgmColCtrl",
                    0x63: "TObjCollision"})
    assert C.family(dol, 0x46) == "door" and C.family(dol, 0x5C) == "warp"
    assert C.family(dol, 0x10) == "switch" and C.family(dol, 0x18) == "trap"
    assert C.family(dol, 0x02) == "sensor" and C.family(dol, 0x40) == "effects"
    assert C.family(dol, 0x00) == "prop" and C.family(dol, 0x4C) == "decor"
    assert C.family(dol, 0xCF) == "warp" and C.family(dol, 0x60) == "effects"
    assert C.family(dol, 0x63) == "collision"
    assert C.family(dol, 0x05) == "unknown"                     # an empty slot
    assert C.family_of_name(None) == "unknown"
    assert C.family_of_name("TSomethingNew") == "object"


def test_label_names_a_hole_instead_of_inventing_one():
    dol = make_dol({0x46: "TObjCityDoor_Shop"})
    assert C.label(dol, 0x02000046) == "TObjCityDoor_Shop"
    assert C.label(dol, 0x05) == "class_0x05"
    assert C.label(dol, 0x05, unnamed="{id}") == "5"


def make_section_dol(names: dict[int, str], sections=((0x100, 0x8000C000, 0x400),), vtables=(),
                     table_at=0x100):
    """A DOL with a real section table: registry slots at ``table_at``, name strings after it, vtable headers anywhere."""
    body = bytearray(0x1000)
    head = bytearray(0x100)
    for i, (off, addr, size) in enumerate(sections):
        struct.pack_into(">I", head, 0x00 + 4 * i, off)
        struct.pack_into(">I", head, 0x48 + 4 * i, addr)
        struct.pack_into(">I", head, 0x90 + 4 * i, size)
    base_addr = sections[0][1]
    body_off = table_at
    strings_at = 0x600
    table = table_at
    for slot, name in names.items():
        struct.pack_into(">I", body, table + slot * 4 - 0x100, base_addr + (strings_at - 0x100))
        body[strings_at - 0x100:strings_at - 0x100 + len(name)] = name.encode() + b"\x00"
        strings_at += len(name) + 1
    for slot in vtables:
        slot_off = table + slot * 4
        slot_addr = base_addr + (slot_off - 0x100)
        struct.pack_into(">I", body, 0x800, slot_addr)                     # a vtable header
    return bytes(head) + bytes(body)


def test_the_vtable_census_finds_headers_and_skips_the_registry_itself():
    dol = make_section_dol({0x46: "TObjCityDoor_Shop", 0x06: "TORockCaveBL02"}, vtables=(0x06,))
    assert C.address_of(dol, C.table_offset(dol)) == 0x8000C000 + (C.table_offset(dol) - 0x100)
    census = C.vtable_census(dol)
    assert sorted(census) == [0x06]
    assert census[0x06] == [0x900]                                       # the header word, and not the slot itself
    assert C.instantiated(dol) == [0x06]


def test_the_section_table_is_the_address_mapping():
    dol = make_section_dol({0x46: "TObjCityDoor_Shop"}, sections=((0x100, 0x8000C000, 0x400),
                                                                 (0x500, 0x80434040, 0x800)))
    assert C.address_of(dol, 0x100) == 0x8000C000
    assert C.address_of(dol, 0x500) == 0x80434040
    assert C.offset_of(dol, 0x80434040) == 0x500
    assert C.offset_of(dol, 0x90000000) is None


def test_the_real_executable_has_38_instantiated_classes_and_no_named_placement_class():
    import pathlib as _p
    from gbox import gcdisc
    disc = _p.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                   r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    dol = gcdisc.GCDisc(str(disc)).read("PsoV3.dol")
    assert C.address_of(dol, C.table_offset(dol)) == 0x805D3138         # the registry, per the section table
    assert len(C.instantiated(dol)) == 38
    for named in (0x46, 0x48, 0x02, 0x10, 0x5C, 0x5D, 0xC9, 0xCA):
        assert named not in C.instantiated(dol), hex(named)
    assert C.name_of(dol, 0x46) == "TObjCityDoor_Shop" and C.family(dol, 0x46) == "door"


# ---- the independent cross-checks the duplicate branch brought (CP0 step 4) ---------------------------------------------------

def test_the_pinned_address_is_where_the_anchor_finds_the_table():
    """`ds-pso-class-registry-20261110` pinned the table at 0x805D3138; the anchor-derived module must agree."""
    import pathlib as _p
    from gbox import gcdisc
    disc = _p.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                   r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    dol = gcdisc.GCDisc(str(disc)).read("PsoV3.dol")
    assert C.table_offset(dol) == C.offset_of(dol, C.PINNED_ADDRESS)
    assert C.address_of(dol, C.table_offset(dol)) == C.PINNED_ADDRESS


def test_the_pinned_148_names_are_what_the_anchor_derives():
    import pathlib as _p
    from gbox import gcdisc
    disc = _p.Path(r"D:\gBox\cache\mods\436e0bb84d5337d1\pso_city_npc_moved"
                   r"\Phantasy Star Online Episode I & II Plus (USA).iso")
    if not disc.is_file():
        pytest.skip("the disc is not on this machine")
    dol = gcdisc.GCDisc(str(disc)).read("PsoV3.dol")
    derived = C.registry(dol, slots=len(C.PINNED_NAMES))
    assert len(C.PINNED_NAMES) == 240 and sum(1 for n in C.PINNED_NAMES if n) == 148
    assert derived == {i: name for i, name in enumerate(C.PINNED_NAMES)}
    for slot, name in enumerate(C.PINNED_NAMES):
        if name:
            assert C.label(dol, slot) == name
