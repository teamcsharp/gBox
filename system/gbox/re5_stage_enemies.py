"""Which enemy classes each RE5 Switch Mercenaries stage can spawn, read from the stage archives' layout files.

A stage archive `sNNN.arc` carries one folder per game mode under `stage\\sNNN\\soft\\`, and in it the enemy layouts
`sNNN_emXX` (resource type 0x15302EF4, an XFS object tree). Every placed enemy is a `mSetInfos` row that names the
class the game spawns (`mUnitClass`, e.g. `uEm10` - also the stem of the archive that holds its model) and, for the
Majini classes, the model type and the montage number of the spawn.

    read_xfs(raw)                -> the object tree of one layout
    spawns(raw)                  -> [{'class', 'info_class', 'model_type', 'montage'}] for its enemies
    census(layouts)              -> {mode: {class: {count, layouts, model_types, montages}}}
    stage_layouts(arc_bytes)     -> {mode: {layout name: raw}} from a whole stage archive

Measured 2026-11-09 on s400-s407 (all eight Mercenaries stages, 363 layouts, every one read to its last byte). The
census is what the layouts CAN spawn in a mode; which layouts a round activates is decided by the mode's FSM files,
so it is an upper bound per mode, not a per-round list. Nothing here touches a running game.
"""
from __future__ import annotations

import re
import struct
import zlib

from . import mt_arc

LAYOUT_HASH = 0x15302EF4
#: The Mercenaries stage archives in menu order. s400 is confirmed by the navigation mesh work; the others follow the
#: menu order and agree with what their layouts spawn (see the research note for how sure each row is).
STAGES = {'s400': 'Public Assembly', 's401': 'The Mines', 's402': 'Village', 's403': 'Ancient Ruins',
          's404': 'Experimental Facility', 's405': 'Missile Area', 's406': 'Ship Deck', 's407': 'Prison'}
#: Mode folders under `soft`. The names are the game's; the reading of each is from their content and the PC edition.
MODES = {'merce': 'The Mercenaries', 'merceex': 'No Mercy (three times the layouts, 30 enemies each)',
         'mercedc': 'The Mercenaries Reunion', 'vsm': 'Versus (same layouts as merce)', 'vss': 'Versus (slayers)'}
RANDOM_MONTAGE = 0xFFFFFFFF

_SCALARS = {3: '<?', 4: '<B', 5: '<H', 6: '<I', 7: '<Q', 8: '<b', 9: '<h', 10: '<i', 11: '<q', 12: '<f', 13: '<d'}
_VECTORS = {15: 4, 16: 8, 17: 8, 18: 16, 19: 64, 20: 16, 21: 16, 22: 16}        # bytes; decoded as floats
_STRINGS, _OBJECTS = (14, 32), (1, 2)


class XfsError(ValueError):
    """The bytes are not an XFS object tree in the measured 64-bit layout."""


def read_xfs(raw: bytes) -> dict:
    """Decode one XFS resource into nested dicts ({property: value}, plus `__class` = the class index).

    Layout, measured on the layouts of s400-s407: `XFS\\0`, u16 version 16, u16 4, u32 property total, u32 0, u32
    class count, u32 definition bytes; from 0x18 one u64 offset per class, then per class a u64 hash, a u64 property
    count and 80 bytes per property (u64 name offset, u8 type, u8 attributes, u16 bytes); offsets are relative to
    0x18. The data follows: an object is i16 `class * 2 + 1`, u16 serial, u64 size (counted from itself), then per
    property a u32 count and that many values. The whole input must be consumed exactly.
    """
    if len(raw) < 0x18 or raw[:4] != b'XFS\0':
        raise XfsError('not an XFS resource')
    version, kind, _, zero, count, defs = struct.unpack_from('<HHIIII', raw, 4)
    base = 0x18
    if (version, kind, zero) != (16, 4, 0) or not 1 <= count <= 256 or base + defs > len(raw):
        raise XfsError('not the measured XFS 64-bit layout')
    classes = []
    for offset in struct.unpack_from(f'<{count}Q', raw, base):
        at = base + offset
        if at + 16 > base + defs:
            raise XfsError('a class definition runs outside the definition block')
        _, properties = struct.unpack_from('<QQ', raw, at)
        if properties > 512 or at + 16 + 80 * properties > base + defs:
            raise XfsError('a class definition runs outside the definition block')
        rows = []
        for i in range(properties):
            name_at, type_, _, _ = struct.unpack_from('<QBBH', raw, at + 16 + 80 * i)
            end = raw.find(b'\0', base + name_at, base + defs)
            if end < 0:
                raise XfsError('a property name is not terminated')
            rows.append((raw[base + name_at:end].decode('ascii', 'replace'), type_))
        classes.append(rows)

    def value(type_: int, at: int):
        if type_ in _OBJECTS:
            tag = struct.unpack_from('<h', raw, at)[0]
            if tag < 0 or not tag & 1:                    # an empty reference: four bytes and no object
                return None, at + 4
            return obj(at)
        if type_ in _STRINGS:
            end = raw.find(b'\0', at)
            if end < 0:
                raise XfsError('a string is not terminated')
            return raw[at:end].decode('ascii', 'replace'), end + 1
        if type_ in _SCALARS:
            return struct.unpack_from(_SCALARS[type_], raw, at)[0], at + struct.calcsize(_SCALARS[type_])
        if type_ in _VECTORS:
            size = _VECTORS[type_]
            return struct.unpack_from(f'<{size // 4}f', raw, at), at + size
        raise XfsError(f'property type {type_} is not measured')

    def obj(at: int):
        tag, _, size = struct.unpack_from('<hHQ', raw, at)
        if tag < 0 or not tag & 1 or tag >> 1 >= len(classes) or at + 4 + size > len(raw):
            raise XfsError('an object header is outside the measured layout')
        out, cursor = {'__class': tag >> 1}, at + 12
        for name, type_ in classes[tag >> 1]:
            items = struct.unpack_from('<I', raw, cursor)[0]
            cursor += 4
            values = []
            for _ in range(items):
                item, cursor = value(type_, cursor)
                values.append(item)
            out[name] = values[0] if items == 1 else values
        if cursor != at + 4 + size:
            raise XfsError('an object does not end where its size says')
        return out, cursor
    try:
        root, end = obj(base + defs)
    except struct.error as exc:
        raise XfsError('the object data is truncated') from exc
    if end != len(raw):
        raise XfsError('bytes follow the root object')
    return root


def spawns(raw: bytes) -> list[dict]:
    """The enemies one layout places: class, set-info class, model type and montage number (None where absent)."""
    rows = read_xfs(raw).get('mSetInfos') or []
    out = []
    for row in rows if isinstance(rows, list) else [rows]:
        unit = (row or {}).get('mUnitClass')
        if not isinstance(unit, str) or not re.fullmatch(r'uEm[0-9a-f]{2,4}', unit):
            continue
        info = row.get('mpInfo') if isinstance(row.get('mpInfo'), dict) else {}
        out.append({'class': unit, 'info_class': row.get('mInfoClass'), 'model_type': info.get('mModelType'),
                    'montage': info.get('mMontageNo')})
    return out


def census(layouts: dict[str, dict[str, bytes]]) -> dict:
    """{mode: {class: {'count', 'layouts', 'model_types', 'montages'}}} over {mode: {layout name: XFS bytes}}."""
    out = {}
    for mode in sorted(layouts):
        classes = {}
        for name in sorted(layouts[mode]):
            for row in spawns(layouts[mode][name]):
                entry = classes.setdefault(row['class'], {'count': 0, 'layouts': [], 'info_classes': [],
                                                          'model_types': [], 'montages': []})
                entry['count'] += 1
                for key, item in (('layouts', name), ('info_classes', row['info_class']),
                                  ('model_types', row['model_type']), ('montages', row['montage'])):
                    if item not in entry[key]:
                        entry[key].append(item)
        for entry in classes.values():
            entry['montages'] = sorted(entry['montages'], key=lambda v: (v is None, v or 0))
            entry['random_montage'] = RANDOM_MONTAGE in entry['montages']
        out[mode] = dict(sorted(classes.items()))
    return out


def stage_layouts(archive: bytes) -> dict[str, dict[str, bytes]]:
    """{mode: {layout name: decompressed XFS}} for the enemy layouts (`sNNN_emXX`) of one stage archive."""
    out: dict[str, dict[str, bytes]] = {}
    for entry in mt_arc.parse(archive).entries:
        match = re.fullmatch(r'stage\\(s\d{3})\\soft\\(\w+)\\(\1_em\d+)', entry.name)
        if match and entry.hash == LAYOUT_HASH:
            out.setdefault(match.group(2), {})[match.group(3)] = zlib.decompress(entry.data)
    return out


def archives_needed(stage_census: dict, mode: str) -> list[str]:
    """The enemy archives a build must replace for every enemy of one mode of one stage to be a donor."""
    return [f'{name}.arc' for name in sorted(stage_census.get(mode, {}))]


def main(argv=None) -> int:
    """CLI: stage archive paths (sNNN.arc) or folders of extracted layouts -> the census as JSON."""
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description='Enemy classes the RE5 Switch Mercenaries stages can spawn')
    parser.add_argument('paths', nargs='+', help='sNNN.arc files, or folders <stage>/<mode>/<layout>.lot')
    args = parser.parse_args(argv)
    result = {}
    for text in args.paths:
        path = Path(text)
        if path.is_dir():
            layouts = {mode.name: {f.stem: f.read_bytes() for f in sorted(mode.glob('*_em*.lot'))}
                       for mode in sorted(p for p in path.iterdir() if p.is_dir())}
            stage = path.name
        else:
            layouts, stage = stage_layouts(path.read_bytes()), path.stem
        result[stage] = {'name': STAGES.get(stage), 'modes': census({m: v for m, v in layouts.items() if v})}
    print(json.dumps(result, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
