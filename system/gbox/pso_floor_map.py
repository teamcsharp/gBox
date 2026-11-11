"""PSO floor id -> area and layout map names, from the executable's own table.

`FUN_80207E88(floor)` (decompiled) returns a `{char **names, u32 count}` entry from one of two 36-entry tables:
`0x804C8FC0` for an Episode 1 session and `0x804C9270` for Episode 2 - `FUN_8030A6A8` picks between them. The
entry holds `count` area/layout name pairs: `names[2i]` is the area's map name and `names[2i+1]` the layout's,
so floor 0 is `map_city00` layout `map_city00_00` and floor 3 (Cave 1) has six layouts (`map_cave01_00` .. `_05`).

This is the resolver `docs/research/pso-gc-executable.md` section 7.2 called open. It is what binds a floor to
its files without a live load: the editor, the area survey and the collision reader can name a floor's map and
layout from the floor id alone. Floor 1 -> `map_forest01`/`map_forest01` is consistent with the operator's
recorded Forest 1 session (floor 1, rooms 11-16) and with `pso_areas.EPISODE1`'s order for floors 0-11.

`derive(dol)` re-reads the two tables from a decompressed `PsoV3.dol` and compares them with the pinned data;
`tools/verify_pso_floors.py` runs it against the disc.
"""

from __future__ import annotations

import struct

EP1_TABLE, EP2_TABLE = 0x804C8FC0, 0x804C9270
FLOOR_COUNT = 36


class FloorError(ValueError):
    pass


#: ep1 floor table: (area/layout name pairs, layout count)
EP1_FLOORS = (
    (('map_city00', 'map_city00_00'), 1),
    (('map_forest01', 'map_forest01'), 1),
    (('map_forest02', 'map_forest02'), 1),
    (('map_cave01', 'map_cave01_00', 'map_cave01', 'map_cave01_01', 'map_cave01', 'map_cave01_02', 'map_cave01', 'map_cave01_03', 'map_cave01', 'map_cave01_04', 'map_cave01', 'map_cave01_05'), 6),
    (('map_cave02', 'map_cave02_00', 'map_cave02', 'map_cave02_01', 'map_cave02', 'map_cave02_02', 'map_cave02', 'map_cave02_03', 'map_cave02', 'map_cave02_04'), 5),
    (('map_cave03', 'map_cave03_00', 'map_cave03', 'map_cave03_01', 'map_cave03', 'map_cave03_02', 'map_cave03', 'map_cave03_03', 'map_cave03', 'map_cave03_04', 'map_cave03', 'map_cave03_05'), 6),
    (('map_machine01', 'map_machine01_00', 'map_machine01', 'map_machine01_01', 'map_machine01', 'map_machine01_02', 'map_machine01', 'map_machine01_03', 'map_machine01', 'map_machine01_04', 'map_machine01', 'map_machine01_05'), 6),
    (('map_machine02', 'map_machine02_00', 'map_machine02', 'map_machine02_01', 'map_machine02', 'map_machine02_02', 'map_machine02', 'map_machine02_03', 'map_machine02', 'map_machine02_04', 'map_machine02', 'map_machine02_05'), 6),
    (('map_ancient01', 'map_ancient01_00', 'map_ancient01', 'map_ancient01_01', 'map_ancient01', 'map_ancient01_02', 'map_ancient01', 'map_ancient01_03', 'map_ancient01', 'map_ancient01_04'), 5),
    (('map_ancient02', 'map_ancient02_00', 'map_ancient02', 'map_ancient02_01', 'map_ancient02', 'map_ancient02_02', 'map_ancient02', 'map_ancient02_03', 'map_ancient02', 'map_ancient02_04'), 5),
    (('map_ancient03', 'map_ancient03_00', 'map_ancient03', 'map_ancient03_01', 'map_ancient03', 'map_ancient03_02', 'map_ancient03', 'map_ancient03_03', 'map_ancient03', 'map_ancient03_04'), 5),
    (('map_boss01', 'map_boss01'), 1),
    (('map_boss02', 'map_boss02'), 1),
    (('map_boss03', 'map_boss03'), 1),
    (('map_darkfalz00', 'map_darkfalz00'), 1),
    (('map_lobby_01', 'map_lobby_01', 'map_lobby_02', 'map_lobby_02', 'map_lobby_03', 'map_lobby_03', 'map_lobby_04', 'map_lobby_04', 'map_lobby_05', 'map_lobby_05', 'map_lobby_06', 'map_lobby_06', 'map_lobby_07', 'map_lobby_07', 'map_lobby_08', 'map_lobby_08', 'map_lobby_09', 'map_lobby_09', 'map_lobby_10', 'map_lobby_10', 'map_lobby_red_be00', 'map_lobby_red_be00', 'map_lobby_yellow_be00', 'map_lobby_yellow_be00', 'map_lobby_green_be00', 'map_lobby_green_be00', 'map_soccer11', 'map_soccer11', 'map_soccer12', 'map_soccer12'), 15),
    (('map_vs01', 'map_vs01_00', 'map_vs01', 'map_vs01_01', 'map_vs01', 'map_vs01_02'), 3),
    (('map_vs02', 'map_vs02_00', 'map_vs02', 'map_vs02_01', 'map_vs02', 'map_vs02_02'), 3),
    (('map_labo00', 'map_labo00_00'), 1),
    (('map_ruins01', 'map_ruins01_00', 'map_ruins01', 'map_ruins01_01', 'map_ruins01', 'map_ruins01_02'), 3),
    (('map_ruins02', 'map_ruins02_00', 'map_ruins02', 'map_ruins02_01', 'map_ruins02', 'map_ruins02_02'), 3),
    (('map_space01', 'map_space01_00', 'map_space01', 'map_space01_01', 'map_space01', 'map_space01_02'), 3),
    (('map_space02', 'map_space02_00', 'map_space02', 'map_space02_01', 'map_space02', 'map_space02_02'), 3),
    (('map_jungle01', 'map_jungle01_00'), 1),
    (('map_jungle02', 'map_jungle02_00'), 1),
    (('map_jungle03', 'map_jungle03_00'), 1),
    (('map_jungle04', 'map_jungle04_00', 'map_jungle04', 'map_jungle04_01', 'map_jungle04', 'map_jungle04_02'), 3),
    (('map_jungle05', 'map_jungle05_00'), 1),
    (('map_seabed01', 'map_seabed01_00', 'map_seabed01', 'map_seabed01_01', 'map_seabed01', 'map_seabed01_02'), 3),
    (('map_seabed02', 'map_seabed02_00', 'map_seabed02', 'map_seabed02_01', 'map_seabed02', 'map_seabed02_02'), 3),
    (('map_boss05', 'map_boss05'), 1),
    (('map_boss06', 'map_boss06'), 1),
    (('map_boss07', 'map_boss07'), 1),
    (('map_boss08', 'map_boss08'), 1),
    (('map_jungle06', 'map_jungle06_00'), 1),
    (('map_jungle07', 'map_jungle07_00', 'map_jungle07', 'map_jungle07_01', 'map_jungle07', 'map_jungle07_02', 'map_jungle07', 'map_jungle07_03', 'map_jungle07', 'map_jungle07_04'), 5),
)

#: ep2 floor table: (area/layout name pairs, layout count)
EP2_FLOORS = (
    (('map_acity00', 'map_acity00_00'), 1),
    (('map_aforest01', 'map_aforest01'), 1),
    (('map_aforest02', 'map_aforest02'), 1),
    (('map_acave01', 'map_acave01_00', 'map_acave01', 'map_acave01_01', 'map_acave01', 'map_acave01_02', 'map_acave01', 'map_acave01_03', 'map_acave01', 'map_acave01_04', 'map_acave01', 'map_acave01_05'), 6),
    (('map_acave02', 'map_acave02_00', 'map_acave02', 'map_acave02_01', 'map_acave02', 'map_acave02_02', 'map_acave02', 'map_acave02_03', 'map_acave02', 'map_acave02_04'), 5),
    (('map_acave03', 'map_acave03_00', 'map_acave03', 'map_acave03_01', 'map_acave03', 'map_acave03_02', 'map_acave03', 'map_acave03_03', 'map_acave03', 'map_acave03_04', 'map_acave03', 'map_acave03_05'), 6),
    (('map_amachine01', 'map_amachine01_00', 'map_amachine01', 'map_amachine01_01', 'map_amachine01', 'map_amachine01_02', 'map_amachine01', 'map_amachine01_03', 'map_amachine01', 'map_amachine01_04', 'map_amachine01', 'map_amachine01_05'), 6),
    (('map_amachine02', 'map_amachine02_00', 'map_amachine02', 'map_amachine02_01', 'map_amachine02', 'map_amachine02_02', 'map_amachine02', 'map_amachine02_03', 'map_amachine02', 'map_amachine02_04', 'map_amachine02', 'map_amachine02_05'), 6),
    (('map_aancient01', 'map_aancient01_00', 'map_aancient01', 'map_aancient01_01', 'map_aancient01', 'map_aancient01_02', 'map_aancient01', 'map_aancient01_03', 'map_aancient01', 'map_aancient01_04'), 5),
    (('map_aancient02', 'map_aancient02_00', 'map_aancient02', 'map_aancient02_01', 'map_aancient02', 'map_aancient02_02', 'map_aancient02', 'map_aancient02_03', 'map_aancient02', 'map_aancient02_04'), 5),
    (('map_aancient03', 'map_aancient03_00', 'map_aancient03', 'map_aancient03_01', 'map_aancient03', 'map_aancient03_02', 'map_aancient03', 'map_aancient03_03', 'map_aancient03', 'map_aancient03_04'), 5),
    (('map_aboss01', 'map_aboss01'), 1),
    (('map_aboss02', 'map_aboss02'), 1),
    (('map_aboss03', 'map_aboss03'), 1),
    (('map_darkfalz00', 'map_darkfalz00'), 1),
    (('map_lobby_01', 'map_lobby_01', 'map_lobby_02', 'map_lobby_02', 'map_lobby_03', 'map_lobby_03', 'map_lobby_04', 'map_lobby_04', 'map_lobby_05', 'map_lobby_05', 'map_lobby_06', 'map_lobby_06', 'map_lobby_07', 'map_lobby_07', 'map_lobby_08', 'map_lobby_08', 'map_lobby_09', 'map_lobby_09', 'map_lobby_10', 'map_lobby_10', 'map_lobby_red_be00', 'map_lobby_red_be00', 'map_lobby_yellow_be00', 'map_lobby_yellow_be00', 'map_lobby_green_be00', 'map_lobby_green_be00', 'map_soccer11', 'map_soccer11', 'map_soccer12', 'map_soccer12'), 15),
    (('map_vs01', 'map_vs01_00', 'map_vs01', 'map_vs01_01', 'map_vs01', 'map_vs01_02'), 3),
    (('map_vs02', 'map_vs02_00', 'map_vs02', 'map_vs02_01', 'map_vs02', 'map_vs02_02'), 3),
    (('map_labo00', 'map_labo00_00'), 1),
    (('map_ruins01', 'map_ruins01_00', 'map_ruins01', 'map_ruins01_01', 'map_ruins01', 'map_ruins01_02'), 3),
    (('map_ruins02', 'map_ruins02_00', 'map_ruins02', 'map_ruins02_01', 'map_ruins02', 'map_ruins02_02'), 3),
    (('map_space01', 'map_space01_00', 'map_space01', 'map_space01_01', 'map_space01', 'map_space01_02'), 3),
    (('map_space02', 'map_space02_00', 'map_space02', 'map_space02_01', 'map_space02', 'map_space02_02'), 3),
    (('map_jungle01', 'map_jungle01_00'), 1),
    (('map_jungle02', 'map_jungle02_00'), 1),
    (('map_jungle03', 'map_jungle03_00'), 1),
    (('map_jungle04', 'map_jungle04_00', 'map_jungle04', 'map_jungle04_01', 'map_jungle04', 'map_jungle04_02'), 3),
    (('map_jungle05', 'map_jungle05_00'), 1),
    (('map_seabed01', 'map_seabed01_00', 'map_seabed01', 'map_seabed01_01', 'map_seabed01', 'map_seabed01_02'), 3),
    (('map_seabed02', 'map_seabed02_00', 'map_seabed02', 'map_seabed02_01', 'map_seabed02', 'map_seabed02_02'), 3),
    (('map_boss05', 'map_boss05'), 1),
    (('map_boss06', 'map_boss06'), 1),
    (('map_boss07', 'map_boss07'), 1),
    (('map_boss08', 'map_boss08'), 1),
    (('map_jungle06', 'map_jungle06_00'), 1),
    (('map_jungle07', 'map_jungle07_00', 'map_jungle07', 'map_jungle07_01', 'map_jungle07', 'map_jungle07_02', 'map_jungle07', 'map_jungle07_03', 'map_jungle07', 'map_jungle07_04'), 5),
)


def floor_entry(floor: int, episode2: bool = False):
    """The (names, count) row for `floor`, or None when the floor id is outside the table."""
    table = EP2_FLOORS if episode2 else EP1_FLOORS
    if not isinstance(floor, int) or not 0 <= floor < FLOOR_COUNT:
        return None
    return table[floor]


def floor_names(floor: int, episode2: bool = False):
    """(area map name, tuple of layout map names) for a floor, or None."""
    row = floor_entry(floor, episode2)
    if row is None:
        return None
    names, count = row
    return names[0], tuple(names[2 * i + 1] for i in range(count))


def area_for_floor(floor: int, episode2: bool = False):
    """The area's map name (e.g. "map_forest01"), or None."""
    names = floor_names(floor, episode2)
    return None if names is None else names[0]


def layouts_for_floor(floor: int, episode2: bool = False):
    """The floor's layout map names in id order (one name per layout), or None."""
    names = floor_names(floor, episode2)
    return None if names is None else names[1]


def layout_name(floor: int, layout: int = 0, episode2: bool = False):
    """One layout's map name, or None when the floor or layout id is outside the table."""
    layouts = layouts_for_floor(floor, episode2)
    if layouts is None or not isinstance(layout, int) or not 0 <= layout < len(layouts):
        return None
    return layouts[layout]


def area_id(floor: int, episode2: bool = False):
    """The area part of the map name: "forest01" for "map_forest01"."""
    name = area_for_floor(floor, episode2)
    return None if name is None else name[len("map_"):]


def derive(dol: bytes, tables=None):
    """Re-read both tables from a decompressed `PsoV3.dol` -> {EP1: rows, EP2: rows}, or raise FloorError."""
    offs, addrs, sizes = (struct.unpack_from(">18I", dol, o) for o in (0x00, 0x48, 0x90))
    sections = [(offs[i], addrs[i], sizes[i]) for i in range(18) if sizes[i]]

    def read(va, n):
        for off0, addr, size in sections:
            if addr <= va < addr + size:
                return dol[off0 + va - addr: off0 + va - addr + n]
        raise FloorError(f"address {va:#x} is not in a mapped section")

    def u32(va):
        return struct.unpack(">I", read(va, 4))[0]

    def cstr(va):
        raw = read(va, 32).split(b"\0")[0]
        try:
            return raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise FloorError(f"{va:#x} does not hold a name") from exc

    out = {}
    for label, base in (tables or (("EP1", EP1_TABLE), ("EP2", EP2_TABLE))):
        rows = []
        for i in range(FLOOR_COUNT):
            ptr, count = u32(base + i * 8), u32(base + i * 8 + 4)
            if count > 32:
                raise FloorError(f"{label} floor {i} has an implausible layout count {count}")
            names = tuple(cstr(u32(ptr + 4 * k)) for k in range(2 * count)) if count else ()
            rows.append((names, count))
        out[label] = tuple(rows)
    return out


def verify(dol: bytes, tables=None) -> dict:
    """Compare the pinned tables with a DOL's own -> {ok, mismatches}."""
    try:
        derived = derive(dol, tables=tables)
    except FloorError as exc:
        return {"ok": False, "mismatches": [{"why": str(exc)}]}
    mismatches = []
    for label, pinned in (("EP1", EP1_FLOORS), ("EP2", EP2_FLOORS)):
        if label not in derived:
            continue
        for i, (want, got) in enumerate(zip(pinned, derived[label])):
            if want != got:
                mismatches.append({"table": label, "floor": i, "pinned": want, "image": got})
    return {"ok": not mismatches, "mismatches": mismatches}

