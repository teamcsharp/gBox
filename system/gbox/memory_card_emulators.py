"""Native memory-card formats and emulator launch paths.

Existing images are only inspected/copied here, never reformatted.  VMUs are
cached in Flycast's Maple devices: changing files under a running core is not a
card swap.  Launch helpers use private paths; a cloud lease belongs to one game
process at a time.

Format references: KallistiOS dc/vmufs.h; Flycast core/hw/maple/maple_devs.cpp
and shell/libretro/libretro_core_options.h; Dolphin Core/HW/GCMemcard.
"""
from __future__ import annotations

import os
import re
import shutil
import struct
import time
from pathlib import Path

DC_SLOTS = tuple(f'{p}{n}' for p in 'ABCD' for n in (1, 2))
GC_SLOTS = ('A', 'B')
VMU_SIZE = 128 * 1024
GC_BLOCK = 8192
GC_MBITS = (4, 8, 16, 32, 64, 128)


def slots(platform: str) -> tuple[str, ...]:
    if platform == 'dreamcast':
        return DC_SLOTS
    if platform == 'gamecube':
        return GC_SLOTS
    raise ValueError('Memory cards are supported for Dreamcast and GameCube')


def _checksum(data: bytes) -> bytes:
    words = struct.unpack('>' + 'H' * (len(data) // 2), data)
    sums = (sum(words) & 0xffff, sum(v ^ 0xffff for v in words) & 0xffff)
    return struct.pack('>HH', *(0 if v == 0xffff else v for v in sums))


def blank(platform: str) -> bytes:
    """A new, formatted card; callers must save with exclusive creation.

    New GameCube cards use 16 Mbit / 251 save blocks for broad compatibility.
    Raw card identity is generated once and is retained in every cloud revision.
    """
    if platform == 'dreamcast':
        image = bytearray(VMU_SIZE)
        root = 255 * 512
        image[root:root + 16] = b'\x55' * 16
        # Root media information, per the VMU Maple GetMediaInfo layout.
        struct.pack_into('<HHHHHHHHHH', image, root + 0x40,
                         255, 0, 255, 254, 1, 253, 13, 0, 200, 31)
        struct.pack_into('<H', image, root + 0x56, 128)
        stamp = time.gmtime()
        bcd = lambda n: ((n // 10) << 4) | (n % 10)
        image[root + 0x30:root + 0x38] = bytes(bcd(n) for n in
            (stamp.tm_year // 100, stamp.tm_year % 100, stamp.tm_mon,
             stamp.tm_mday, stamp.tm_hour, stamp.tm_min, stamp.tm_sec, stamp.tm_wday))
        fat = [0xfffc] * 256
        for i in range(241, 256):
            fat[i] = 0xfffa
        for i in range(253, 241, -1):
            fat[i] = i - 1
        image[254 * 512:255 * 512] = struct.pack('<256H', *fat)
        return bytes(image)
    if platform != 'gamecube':
        raise ValueError('Memory cards are supported for Dreamcast and GameCube')
    mbits = 16
    image = bytearray(b'\xff' * (mbits * 131072))
    # Persistent native serial and creation time.  The format time uses GC ticks
    # since 2000; no existing card's serial is changed or synthesized on import.
    flash = os.urandom(12)
    format_time = max(0, int((time.time() - 946684800) * 40500000))
    rand = format_time
    for i in range(12):
        rand = ((rand * 0x41c64e6d + 0x3039) & 0xffffffffffffffff) >> 16
        image[i] = (flash[i] + rand) & 255
        rand = (((rand * 0x41c64e6d + 0x3039) & 0xffffffffffffffff) >> 16) & 0x7fff
    struct.pack_into('>QIIIHHH', image, 12, format_time, 0, 0, 0, 0, mbits, 0)
    image[0x1fc:0x200] = _checksum(image[:0x1fc])
    directory = bytearray(b'\xff' * GC_BLOCK)
    struct.pack_into('>h', directory, 0x1ffa, 0)
    directory[0x1ffc:] = _checksum(directory[:0x1ffc])
    bat = bytearray(GC_BLOCK)
    struct.pack_into('>HHH', bat, 4, 0, mbits * 16 - 5, 4)
    bat[:4] = _checksum(bat[4:])
    image[GC_BLOCK:3 * GC_BLOCK] = directory * 2
    image[3 * GC_BLOCK:5 * GC_BLOCK] = bat * 2
    return bytes(image)


def _vmu(data: bytes) -> dict:
    if len(data) != VMU_SIZE:
        raise ValueError('A Dreamcast VMU must be exactly 128 KiB')
    root = data[255 * 512:]
    bad = {'formatted': False, 'free_blocks': None, 'total_blocks': 200, 'files': []}
    if root[:16] != b'\x55' * 16:
        return bad
    fat_loc, fat_size, dir_loc, dir_size, _icon, count = struct.unpack_from('<6H', root, 0x46)
    if fat_size != 1 or not 0 < count <= 240 or not 0 <= fat_loc < 255 or not 0 < dir_size <= 16:
        return bad
    if dir_loc >= 255 or dir_loc - dir_size + 1 < count or fat_loc < count:
        return bad
    fat = struct.unpack_from('<256H', data, fat_loc * 512)
    files, occupied = [], set()
    for b in range(dir_loc, dir_loc - dir_size, -1):
        for off in range(b * 512, (b + 1) * 512, 32):
            row = data[off:off + 32]
            if row[0] == 0:
                continue
            if row[0] not in (0x33, 0xcc):
                return bad
            first = struct.unpack_from('<H', row, 2)[0]
            size = struct.unpack_from('<H', row, 24)[0]
            block, chain = first, set()
            for _ in range(size):
                if block >= count or block in chain or block in occupied:
                    return bad
                chain.add(block)
                block = fat[block]
            if not size or block != 0xfffa:
                return bad
            occupied.update(chain)
            files.append({'name': row[4:16].rstrip(b'\0 ').decode('ascii', 'replace'),
                          'blocks': size, 'copy_protected': row[1] == 255})
    free = sum(v == 0xfffc for v in fat[:count])
    if free + len(occupied) != count:
        return bad
    return {'formatted': True, 'free_blocks': free, 'total_blocks': count, 'files': files}


def _gamecube(data: bytes) -> dict:
    mbits = len(data) // 131072
    if mbits not in GC_MBITS or len(data) != mbits * 131072:
        raise ValueError('A GameCube raw card must be 4, 8, 16, 32, 64 or 128 Mbit')
    count = mbits * 16 - 5
    bad = {'formatted': False, 'free_blocks': None, 'total_blocks': count, 'files': []}
    if struct.unpack_from('>H', data, 0x22)[0] != mbits or data[0x1fc:0x200] != _checksum(data[:0x1fc]):
        return bad
    dirs, bats, invalid = [], [], 0
    for i in (1, 2):
        part = data[i * GC_BLOCK:(i + 1) * GC_BLOCK]
        if part[0x1ffc:] == _checksum(part[:0x1ffc]):
            dirs.append((struct.unpack_from('>h', part, 0x1ffa)[0], -i, part))
        else:
            invalid += 1
    for i in (3, 4):
        part = data[i * GC_BLOCK:(i + 1) * GC_BLOCK]
        free = struct.unpack_from('>H', part, 6)[0]
        entries = struct.unpack_from('>' + 'H' * count, part, 10)
        if part[:4] == _checksum(part[4:]) and free == sum(v == 0 for v in entries):
            bats.append((struct.unpack_from('>h', part, 4)[0], -i, part))
        else:
            invalid += 1
    # The GC BIOS treats two corrupt directory/BAT copies as a corrupt card.
    if invalid > 1 or not dirs or not bats:
        return bad
    directory, bat = max(dirs)[2], max(bats)[2]
    occupied, files = set(), []
    for off in range(0, 127 * 64, 64):
        row = directory[off:off + 64]
        if row[:4] == b'\xff' * 4:
            continue
        block, size = struct.unpack_from('>HH', row, 0x36)
        chain = set()
        for _ in range(size):
            if not 5 <= block < count + 5 or block in chain or block in occupied:
                return bad
            chain.add(block)
            block = struct.unpack_from('>H', bat, 10 + (block - 5) * 2)[0]
        if not size or block != 0xffff:
            return bad
        occupied.update(chain)
        encoding = 'shift_jis' if struct.unpack_from('>H', data, 0x24)[0] else 'cp1252'
        files.append({'name': row[8:40].split(b'\0')[0].decode(encoding, 'replace'),
                      'blocks': size, 'game_code': row[:6].decode('ascii', 'replace')})
    free = struct.unpack_from('>H', bat, 6)[0]
    if free + len(occupied) != count:
        return bad
    return {'formatted': True, 'free_blocks': free, 'total_blocks': count, 'files': files}


def describe(data: bytes, platform: str) -> dict:
    if platform == 'dreamcast':
        return _vmu(bytes(data))
    if platform == 'gamecube':
        return _gamecube(bytes(data))
    raise ValueError('Memory cards are supported for Dreamcast and GameCube')


def copy_saves(source: bytes, destination: bytes, names: list[str]) -> bytes:
    """Copy explicitly selected VMU files to a *new image*, preserving both inputs.

    No replacement or deletion is implicit. Source file headers, copy-protection
    flags and payloads survive byte-for-byte; only first-block pointers and the
    destination FAT/directory change. The caller still owns cloud revision/lease
    checks and must never install this under a live Maple device.
    """
    source, destination = bytes(source), bytes(destination)
    src_info, dst_info = describe(source, 'dreamcast'), describe(destination, 'dreamcast')
    if not src_info['formatted'] or not dst_info['formatted']:
        raise ValueError('Both VMUs must be valid formatted cards before copying saves')
    if not names or len(names) > 208 or len(set(names)) != len(names):
        raise ValueError('Select distinct save filenames to copy')
    src_names = {r['name'] for r in src_info['files']}
    dst_names = {r['name'] for r in dst_info['files']}
    if not set(names) <= src_names:
        raise ValueError('A selected save is not on the source card')
    if set(names) & dst_names:
        raise ValueError('The destination already has a selected save; no saves were overwritten')
    result = bytearray(destination)
    src_root, dst_root = source[255 * 512:], destination[255 * 512:]
    src_fatloc, _sfatsz, src_dirloc, src_dirsz = struct.unpack_from('<4H', src_root, 0x46)
    dst_fatloc, _dfatsz, dst_dirloc, dst_dirsz, _icon, dst_count = struct.unpack_from('<6H', dst_root, 0x46)
    src_fat = struct.unpack_from('<256H', source, src_fatloc * 512)
    dst_fat = list(struct.unpack_from('<256H', result, dst_fatloc * 512))
    free = [i for i in range(dst_count) if dst_fat[i] == 0xfffc]
    empty = [off for b in range(dst_dirloc, dst_dirloc - dst_dirsz, -1)
             for off in range(b * 512, (b + 1) * 512, 32) if result[off] == 0]
    requested = set(names)
    rows = []
    for b in range(src_dirloc, src_dirloc - src_dirsz, -1):
        for off in range(b * 512, (b + 1) * 512, 32):
            row = source[off:off + 32]
            if row[0] and row[4:16].rstrip(b'\0 ').decode('ascii', 'replace') in requested:
                rows.append(row)
    if len(rows) != len(names):
        raise ValueError('Source filenames are ambiguous; no saves were copied')
    sizes = [struct.unpack_from('<H', row, 24)[0] for row in rows]
    if len(rows) > len(empty) or sum(sizes) > len(free):
        raise ValueError('The selected saves do not fit on the destination VMU')
    for row, size in zip(rows, sizes):
        allocated, free = free[:size], free[size:]
        block = struct.unpack_from('<H', row, 2)[0]
        for i, target in enumerate(allocated):
            result[target * 512:(target + 1) * 512] = source[block * 512:(block + 1) * 512]
            dst_fat[target] = allocated[i + 1] if i + 1 < len(allocated) else 0xfffa
            block = src_fat[block]
        off, empty = empty[0], empty[1:]
        result[off:off + 32] = row
        struct.pack_into('<H', result, off + 2, allocated[0])
    struct.pack_into('<256H', result, dst_fatloc * 512, *dst_fat)
    output = bytes(result)
    if not describe(output, 'dreamcast')['formatted']:
        raise ValueError('Copied VMU failed filesystem validation; neither input was changed')
    return output


def _cfg(path: Path) -> dict[str, str]:
    try:
        return dict((m[1], m[2]) for line in path.read_text(errors='replace').splitlines()
                    if (m := re.match(r'^\s*([\w-]+)\s*=\s*"([^"\r\n]*)"', line)))
    except OSError:
        return {}


def discover(adapter, game: dict | None = None) -> list[dict]:
    """Known legacy or leased files, with no network writes or process changes."""
    context = getattr(adapter, 'memory_card_context', None)
    if context:
        return [{'slot': s, 'path': str(row['path']), 'platform': context['platform']}
                for s, row in context.get('slots', {}).items() if Path(row['path']).is_file()]
    platform = getattr(adapter, 'platform', None) or (game or {}).get('platform')
    config = getattr(adapter, 'config', None)
    if not config:
        return []
    runtime = Path(config.runtime)
    found = []
    if platform == 'dreamcast':
        port = getattr(adapter, 'addr', (None, 0))[1]
        cfg = _cfg(runtime / 'retroarch' / f'session-{port}.cfg')
        system = Path(cfg.get('system_directory') or runtime / 'system')
        # Never infer an active slot from arbitrary similarly named save files.
        core = _cfg(Path(cfg.get('core_options_path') or runtime / 'retroarch' / 'core-options.cfg'))
        mode = core.get('reicast_per_content_vmus', 'disabled')
        for slot in DC_SLOTS:
            port, expansion = 'ABCD'.index(slot[0]) + 1, slot[1]
            device = core.get(f'reicast_device_port{port}_slot{expansion}',
                              'VMU' if expansion == '1' else 'Purupuru')
            if device != 'VMU' or cfg.get(f'input_libretro_device_p{port}') == '0':
                continue
            if mode != 'disabled' and (mode == 'All VMUs' or slot == 'A1'):
                continue
            path = system / 'dc' / f'vmu_save_{slot}.bin'
            if path.is_file():
                found.append({'slot': slot, 'path': str(path), 'platform': platform})
    elif platform == 'gamecube':
        rom = (game or {}).get('_rom_path') or getattr(adapter, 'memory_card_rom', None)
        try:
            region = gc_region(adapter, rom) if rom else 'USA'
        except ValueError:
            return []
        roots = [runtime / 'dolphin-user']
        argv = getattr(getattr(adapter, 'proc', None), 'args', None)
        if isinstance(argv, (list, tuple)):
            # Read the actual launch configuration without calling _exe(),
            # which may create a renamed portable executable on Windows.
            if argv and str(argv[0]).lower().endswith('.exe'):
                roots.insert(0, Path(argv[0]).parent / 'User')
            for slot in GC_SLOTS:
                prefix = f'Dolphin.Core.Memcard{slot}Path='
                explicit = next((str(a)[len(prefix):] for a in argv if str(a).startswith(prefix)), None)
                if explicit:
                    path = Path(explicit)
                    stem = re.sub(r'\.(USA|EUR|JAP|DEV)$', '', path.stem)
                    path = path.with_name(stem + '.' + region + path.suffix)
                    if path.is_file():
                        found.append({'slot': slot, 'path': str(path), 'platform': platform})
        roots += [runtime / 'dolphin' / 'Dolphin-x64' / 'User']
        for root in roots:
            for slot in GC_SLOTS:
                path = root / 'GC' / f'MemoryCard{slot}.{region}.raw'
                if path.is_file() and not any(r['slot'] == slot for r in found):
                    found.append({'slot': slot, 'path': str(path), 'platform': platform})
    return found


def retroarch_options(adapter, opts: dict, core_options_path: Path) -> dict:
    context = getattr(adapter, 'memory_card_context', None)
    if not context or context.get('platform') != 'dreamcast':
        return opts
    if getattr(adapter, 'tas_playback', None) or getattr(adapter, 'capture_backend', None):
        raise ValueError('Replay and capture sessions keep their own memory-card sandbox')
    work = Path(context['work_dir'])
    system = work / 'system'
    dc = system / 'dc'
    dc.mkdir(parents=True, exist_ok=True)
    source = Path(opts['system_directory']) / 'dc'
    # Only immutable Dreamcast firmware is copied. Existing VMUs, flash/NVRAM
    # and arbitrary symlinked user files are never linked into the leased card.
    for name in ('dc_boot.bin', 'dc_flash.bin', 'dc_nvmem.bin', 'dc_nvmem.bin.net'):
        src, dst = source / name, dc / name
        if src.is_file() and not dst.exists():
            shutil.copyfile(src, dst)
    selected = context.get('slots', {})
    for slot, row in selected.items():
        if slot not in DC_SLOTS:
            raise ValueError('Invalid Dreamcast VMU slot')
        src, dst = Path(row['path']), dc / f'vmu_save_{slot}.bin'
        if not describe(src.read_bytes(), 'dreamcast')['formatted']:
            raise ValueError('The selected VMU is not a valid formatted memory card')
        if src.resolve() != dst.resolve():
            if dst.exists():
                raise ValueError('The memory-card runtime path already exists; refusing to overwrite it')
            shutil.copyfile(src, dst)
        row['path'] = str(dst)
    values = {'reicast_per_content_vmus': 'disabled'}
    for i, p in enumerate('ABCD', 1):
        for n in (1, 2):
            values[f'reicast_device_port{i}_slot{n}'] = 'VMU' if f'{p}{n}' in selected else 'None'
    current = _cfg(Path(core_options_path))
    current.update(values)
    co = work / 'core-options.cfg'
    co.write_text(''.join(f'{k} = "{v}"\n' for k, v in current.items()))
    opts.update(system_directory=system, core_options_path=co,
                sort_savefiles_enable='false', sort_savefiles_by_content_enable='false')
    return opts


def gc_region(adapter, rom: str) -> str:
    try:
        serial = adapter._disc_id(rom)
    except (OSError, ValueError, struct.error) as exc:
        raise ValueError('Cannot verify the GameCube disc region for its cloud memory card') from exc
    code = serial[3:4] if serial else ''
    if code in ('J', 'K'):
        return 'JAP'
    if code == 'E':
        return 'USA'
    if code in ('P', 'D', 'F', 'I', 'S', 'U', 'H', 'X', 'Y', 'R'):
        return 'EUR'
    raise ValueError('Cannot verify this GameCube image region; cloud memory cards require an ISO, GCM or GCZ with a recognized disc ID')


def dolphin_options(adapter, rom: str | None = None) -> dict:
    context = getattr(adapter, 'memory_card_context', None)
    if not context or context.get('platform') != 'gamecube':
        return {}
    region = gc_region(adapter, rom or getattr(adapter, 'memory_card_rom', ''))
    # MemoryCardSize=-1 gives Dolphin's standard unsuffixed filename even for
    # an existing smaller raw image. The file's actual capacity remains native.
    out = {'Dolphin.Core.MemoryCardSize': '-1'}
    for slot in GC_SLOTS:
        row = context.get('slots', {}).get(slot)
        out[f'Dolphin.Core.Slot{slot}'] = '1' if row else '255'
        if row:
            path = Path(row['path'])
            if not describe(path.read_bytes(), 'gamecube')['formatted']:
                raise ValueError('The selected GameCube card is not a valid formatted raw card')
            folder = Path(context['work_dir']) / 'dolphin'
            folder.mkdir(parents=True, exist_ok=True)
            native = folder / f'{slot}.{region}.raw'
            if path.resolve() != native.resolve():
                if native.exists():
                    raise ValueError('The native GameCube card path already exists; refusing to overwrite it')
                shutil.copyfile(path, native)
            row['path'] = str(native)
            out[f'Dolphin.Core.Memcard{slot}Path'] = str(native)
    context['dolphin_region'] = region
    return out
