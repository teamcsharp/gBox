"""PsoV3's own floor -> area/layout table (the resolver the executable uses)."""
import struct

import pytest

from gbox import pso_areas, pso_floor_map as F


def test_the_episode1_floors_match_the_area_table_order():
    # floors 0-11 are the city, the two forest floors, the caves, the machines, the ruins and the first boss
    areas = [F.area_id(floor) for floor in range(12)]
    assert areas == ["city00", "forest01", "forest02", "cave01", "cave02", "cave03",
                     "machine01", "machine02", "ancient01", "ancient02", "ancient03", "boss01"]
    assert areas == list(pso_areas.EPISODE1[:12])


def test_a_floor_carries_its_layout_names():
    assert F.floor_names(0) == ("map_city00", ("map_city00_00",))
    assert F.floor_names(1) == ("map_forest01", ("map_forest01",))
    assert F.floor_names(3) == ("map_cave01", tuple(f"map_cave01_{i:02d}" for i in range(6)))
    assert len(F.layouts_for_floor(15)) == 15                 # the lobby's fifteen rooms
    assert F.layout_name(3, 2) == "map_cave01_02"
    assert F.layout_name(3, 6) is None


def test_episode2_is_the_a_prefixed_table_with_the_shared_tail():
    assert F.floor_names(1, episode2=True) == ("map_aforest01", ("map_aforest01",))
    assert F.area_id(3, episode2=True) == "acave01"
    # the lobby and battle floors are shared between episodes
    assert F.floor_names(15, episode2=True) == F.floor_names(15)
    assert F.floor_names(16) == ("map_vs01", ("map_vs01_00", "map_vs01_01", "map_vs01_02"))


def test_out_of_range_floors_and_layouts_are_none():
    for floor in (-1, 36, 99):
        assert F.floor_names(floor) is None
        assert F.area_for_floor(floor) is None
        assert F.layouts_for_floor(floor) is None
    assert F.layout_name(0, 1) is None
    assert F.floor_entry("3") is None


# ---- the derivation from a DOL image ---------------------------------------------------------------------------------------

def _synthetic_dol(rows):
    """A minimal DOL with one section holding a 36-entry table like the executable's."""
    section_va, section_off, section_size = 0x80000000, 0x2000, 0x2000
    header = bytearray(0x100)
    struct.pack_into(">I", header, 0x00, section_off)          # section 0 file offset
    struct.pack_into(">I", header, 0x48, section_va)           # section 0 address
    struct.pack_into(">I", header, 0x90, section_size)         # section 0 size
    body = bytearray(section_size)
    strings_at = 0x80000400
    names_at = 0x80000200
    table_at = 0x80000000
    cursor = strings_at
    for i, (names, count) in enumerate(rows):
        struct.pack_into(">II", body, table_at - section_va + i * 8, names_at + i * 0x40, count)
        for k, name in enumerate(names):
            struct.pack_into(">I", body, names_at - section_va + i * 0x40 + 4 * k, cursor)
            encoded = name.encode() + b"\0"
            body[cursor - section_va:cursor - section_va + len(encoded)] = encoded
            cursor += len(encoded)
    return bytes(header) + bytes(section_off - len(header)) + bytes(body)


def test_derive_reads_a_table_built_in_the_executable_s_layout():
    rows = [(("map_city00", "map_city00_00"), 1), (("map_forest01", "map_forest01"), 1)] + [((), 0)] * 34
    image = _synthetic_dol(rows)
    derived = F.derive(image, tables=(("EP1", 0x80000000),))
    assert derived["EP1"][:2] == ((("map_city00", "map_city00_00"), 1), (("map_forest01", "map_forest01"), 1))
    assert derived["EP1"][3] == ((), 0)


def test_a_changed_table_is_reported_instead_of_trusted():
    rows = [(("map_wrong", "map_wrong_00"), 1)] + [((), 0)] * 35
    report = F.verify(_synthetic_dol(rows), tables=(("EP1", 0x80000000),))
    assert report["ok"] is False
    assert report["mismatches"][0]["table"] == "EP1" and report["mismatches"][0]["floor"] == 0


def test_an_address_outside_the_image_is_an_error_not_a_crash():
    with pytest.raises(F.FloorError):
        F.derive(bytes(0x100))
