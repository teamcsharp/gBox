"""Exact-build RE2 GameCube static analysis and read-only MEM1 state reader.

This is research support, not an unlock profile or a live inventory writer.
See docs/re2gc-state.md for owned-code evidence and remaining runtime gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from .re2gc_native import DISC_ID, DOL_SHA256, GAME_ID

RAM_BASE = 0x80000000
RAM_SIZE = 24 * 1024 * 1024
DOL_SIZE = 800672
REL_SIZES = {'leon': 2330660, 'claire': 2330228}
MODULE_POINTER = 0x8015FCFC
INVENTORY = 0x80168C6C
ITEM_BOX = 0x80168C98
CAPACITY = 0x801688DC
REL_SHA256 = {
    'leon': '84bc991038949d0452a5ac7999f67e761323f8ba30bca333163cb2ba345808e8',
    'claire': '58de2056e8b625575617cb2220829a7d4998bf642f99aec67e6be42c6954e437',
}
# These are BSS-relative offsets, not addresses in a running emulator.
EQUIPPED_SLOT = 0x13534
EQUIPPED_ITEM = 0x13536
END_RESULT_FLAGS = 0x1E724
PENDING = [
    'Capture an idle, authorized test session and confirm both scenario readers against the native inventory.',
    'Trace persistent save/menu eligibility for HUNK, Tofu and Extreme Battle; the ending result word is not that profile.',
    'Verify native equipment reload and per-character PLW coverage before enabling sidebar writes.',
    'Test clean boot, second launch, save integrity and rollback before registering unlock-on-load.',
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _u32(data, offset):
    return struct.unpack_from('>I', data, offset)[0]


def _extent(data, start, count):
    if start < 0 or count < 0 or start > len(data) or count > len(data) - start:
        raise ValueError('range outside source')
    return data[start:start + count]


def _ram(data, address, count):
    return _extent(data, address - RAM_BASE, count)


def _allocation(address, size, label):
    if type(address) is not int or not 0 <= address <= 0xffffffff or address & 31:
        raise ValueError(f'{label} requires a 32-byte-aligned 32-bit address')
    if type(size) is not int or size <= 0 or address < RAM_BASE or size > RAM_BASE + RAM_SIZE - address:
        raise ValueError(f'{label} allocation lies outside GameCube MEM1')


def _source_bytes(data, sizes, label):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError(f'{label} requires a byte buffer')
    size = data.nbytes if isinstance(data, memoryview) else len(data)
    if size not in sizes:
        raise ValueError(f'unrecognized GHAE08 {label} size')
    return bytes(data)


def _read_bounded(path, sizes, label):
    # Never trust stat followed by read_bytes: files can grow between them.
    # Reading one sentinel byte beyond the largest exact size detects excess
    # without allocating the remainder of an oversized or growing file.
    with path.open('rb') as stream:
        data = stream.read(max(sizes) + 1)
    if len(data) not in sizes:
        raise ValueError(f'{label} size differs from exact supported size(s) {sorted(sizes)}')
    return data


class Build:
    """Owned DOL and one scenario REL, validated before interpreting any offsets."""

    def __init__(self, dol: bytes, rel: bytes):
        self.dol = _source_bytes(dol, {DOL_SIZE}, 'DOL')
        self.rel = _source_bytes(rel, set(REL_SIZES.values()), 'REL')
        if sha(self.dol) != DOL_SHA256:
            raise ValueError('unrecognized GHAE08 DOL SHA-256')
        self.scenario = next((n for n, h in REL_SHA256.items() if h == sha(self.rel)), None)
        if self.scenario is None:
            raise ValueError('unrecognized GHAE08 scenario REL SHA-256')
        self.module_id = _u32(self.rel, 0)
        self.section_count = _u32(self.rel, 0x0c)
        self.table_offset = _u32(self.rel, 0x10)
        self.sections = [struct.unpack_from('>II', self.rel, self.table_offset + i * 8)
                         for i in range(self.section_count)]
        self.bss_size = _u32(self.rel, 0x20)

    def identity(self):
        return {'game_id': GAME_ID, 'disc_id': DISC_ID, 'scenario': self.scenario,
                'dol_sha256': sha(self.dol), 'rel_sha256': sha(self.rel)}

    def linked_rel(self, base, bss):
        """Relocate the hash-guarded module at explicit image/BSS addresses.

        OSLink allocates BSS separately. A live address must come from its
        relocated section table, never the synthetic analysis ELF layout.
        """
        _allocation(base, len(self.rel), 'REL image')
        _allocation(bss, self.bss_size, 'REL BSS')
        if base < bss + self.bss_size and bss < base + len(self.rel):
            raise ValueError('REL BSS overlaps module image')
        main_addresses, main_sizes = (struct.unpack_from('>18I', self.dol, x)
                                     for x in (0x48, 0x90))
        main_bss, main_size = struct.unpack_from('>II', self.dol, 0xd8)
        for start, size in [(a, n) for a, n in zip(main_addresses, main_sizes) if n] + [(main_bss, main_size)]:
            for allocated, count in ((base, len(self.rel)), (bss, self.bss_size)):
                if start < allocated + count and allocated < start + size:
                    raise ValueError('REL allocation overlaps main executable state')
        image = bytearray(self.rel)
        addresses = [bss if size and not (off & ~1) else base + (off & ~1)
                     for off, size in self.sections]
        imp, count = struct.unpack_from('>II', self.rel, 0x28)
        for k in range(count // 8):
            module, at = struct.unpack_from('>II', self.rel, imp + k * 8)
            if module not in (0, self.module_id):
                raise ValueError('unsupported external REL dependency')
            current = None
            while True:
                delta, kind, section, addend = struct.unpack_from('>HBBI', self.rel, at)
                at += 8
                if kind == 203:
                    break
                if kind == 202:
                    current = addresses[section]
                    continue
                if current is None:
                    raise ValueError('relocation without target section')
                current += delta
                if kind in (0, 201):
                    continue
                target = addresses[section] + addend if module else addend
                offset = current - base
                _extent(image, offset, 4 if kind in (1, 2, 10, 11) else 2)
                if kind == 1:
                    struct.pack_into('>I', image, offset, target & 0xffffffff)
                elif kind in (4, 5, 6):
                    value = target if kind == 4 else target >> 16 if kind == 5 else (target + 0x8000) >> 16
                    struct.pack_into('>H', image, offset, value & 0xffff)
                elif kind in (2, 10, 11):
                    word = _u32(image, offset)
                    mask = 0xfffc if kind == 11 else 0x3fffffc
                    value = target if kind == 2 else target - current
                    struct.pack_into('>I', image, offset, (word & ~mask) | (value & mask))
                else:
                    raise ValueError(f'unsupported REL relocation {kind}')
        return bytes(image)

    def analysis_elf(self, base=0x80400000):
        """DOL + REL at an explicit synthetic base, with nonoverlapping BSS.

        Paired-single operations are reduced by existing gcdisc.depair for
        integer-data-flow analysis. This artifact must never be launched.
        """
        from .gcdisc import depair
        _allocation(base, len(self.rel), 'analysis REL image')
        bss = (base + len(self.rel) + 31) & ~31
        image = self.linked_rel(base, bss)
        offsets, addresses, sizes = (struct.unpack_from('>18I', self.dol, x)
                                     for x in (0, 0x48, 0x90))
        segs = [(self.dol[o:o + n], a, n, 5 if i < 7 else 6)
                for i, (o, a, n) in enumerate(zip(offsets, addresses, sizes)) if n]
        start, size, entry = struct.unpack_from('>III', self.dol, 0xd8)
        cursor = start
        for _, a, n, _ in sorted(segs, key=lambda x: x[1]):
            if a + n <= start or a >= start + size:
                continue
            if a > cursor:
                segs.append((b'', cursor, a - cursor, 6))
            cursor = max(cursor, a + n)
        if cursor < start + size:
            segs.append((b'', cursor, start + size - cursor, 6))
        for off, n in self.sections:
            if n:
                a = base + (off & ~1) if off & ~1 else bss
                data = image[off & ~1:(off & ~1) + n] if off & ~1 else b''
                segs.append((data, a, n, 5 if off & 1 else 6))
        ranges = sorted((a, a + n) for _, a, n, _ in segs)
        if any(a < previous_end for (_, previous_end), (a, _) in zip(ranges, ranges[1:])):
            raise ValueError('synthetic REL overlaps DOL or another analysis segment')
        ph, body = bytearray(), bytearray()
        data_offset = 52 + 32 * len(segs)
        for data, a, n, flags in segs:
            data = depair(data) if flags == 5 else data
            if data:
                body += bytes((a - data_offset - len(body)) % 4)
            # Ghidra rejects some filesz=0 segments whose offset equals EOF.
            ph += struct.pack('>8I', 1, data_offset + len(body) if data else 0,
                              a, a, len(data), n, flags, 4)
            body += data
        header = b'\x7fELF' + bytes([1, 2, 1, 0]) + bytes(8)
        header += struct.pack('>HHIIIIIHHHHHH', 2, 20, 1, entry, 52, 0, 0, 52, 32, len(segs), 40, 0, 0)
        return header + ph + body

    def read_snapshot(self, ram: bytes):
        """Read an immutable, complete native-byte-order 24 MiB MEM1 snapshot.

        Verifies the active linked REL header, every section location, and all
        executable REL bytes against relocation at the *captured* BSS base.
        Dolphin's single documented REL audio NOP is accepted explicitly.
        No emulator attachment or mutation is performed.
        """
        if len(ram) != RAM_SIZE or ram[:6] != DISC_ID.encode('ascii'):
            raise ValueError('expected complete GHAE08 native-byte-order MEM1 snapshot')
        dol_audio = []
        offsets, addresses, sizes = (struct.unpack_from('>18I', self.dol, x)
                                     for x in (0, 0x48, 0x90))
        for o, a, n in list(zip(offsets, addresses, sizes))[:7]:
            if not n:
                continue
            actual, wanted = _ram(ram, a, n), self.dol[o:o + n]
            if actual != wanted:
                at = 0x800339e4 - a
                patched = bytearray(wanted)
                if not 0 <= at <= len(patched) - 4:
                    raise ValueError('active DOL executable bytes differ from owned source')
                patched[at:at + 4] = b'\x60\x00\x00\x00'
                if actual != patched:
                    raise ValueError('active DOL executable bytes differ from owned source')
                dol_audio.append({'address': 0x800339e4, 'patch': 'Dolphin GHAE08 audio NOP'})
        base = _u32(_ram(ram, MODULE_POINTER, 4), 0)
        if base & 31:
            raise ValueError('unaligned active REL pointer')
        # The loader leaves its cached pointer behind after OSUnlink. Require
        # membership in the currently linked module list, not stale freed bytes.
        current = _u32(_ram(ram, 0x800030c8, 4), 0)
        previous, modules = 0, set()
        while current:
            if current in modules or len(modules) >= 64 or current & 31:
                raise ValueError('invalid active REL module list')
            node = _ram(ram, current, 12)
            if _u32(node, 8) != previous:
                raise ValueError('inconsistent active REL module list')
            modules.add(current)
            previous, current = current, _u32(node, 4)
        if base not in modules or previous != _u32(_ram(ram, 0x800030cc, 4), 0):
            raise ValueError('selected REL is not in the active linked module list')
        header = _ram(ram, base, 0x48)
        for offset in (0, 0x0c, 0x18, 0x1c, 0x20, 0x2c, 0x40, 0x44):
            if header[offset:offset + 4] != self.rel[offset:offset + 4]:
                raise ValueError('active REL header differs from the selected owned scenario')
        table = _u32(header, 0x10)
        if table != base + self.table_offset:
            raise ValueError('active REL section-table pointer differs')
        _ram(ram, base, len(self.rel))
        live_sections = [struct.unpack('>II', _ram(ram, table + i * 8, 8))
                         for i in range(self.section_count)]
        bss = None
        for (off, size), (address, live_size) in zip(self.sections, live_sections):
            if size != live_size:
                raise ValueError('active REL section size differs')
            if size and not (off & ~1):
                if bss is not None or address & 31:
                    raise ValueError('invalid dynamic REL BSS')
                bss = address
                _ram(ram, bss, self.bss_size)
                if bss < base + len(self.rel) and base < bss + self.bss_size:
                    raise ValueError('dynamic REL BSS overlaps module image')
            elif address != (base + off if size else off):
                raise ValueError('active REL section address differs')
        if bss is None:
            raise ValueError('active REL has no BSS section')
        main_bss, main_size = struct.unpack_from('>II', self.dol, 0xd8)
        for start, size in [(a, n) for a, n in zip(addresses, sizes) if n] + [(main_bss, main_size)]:
            for allocated, count in ((base, len(self.rel)), (bss, self.bss_size)):
                if start < allocated + count and allocated < start + size:
                    raise ValueError('active REL allocation overlaps main executable state')
        expected = self.linked_rel(base, bss)
        # Owned call sites, not Dolphin's absolute runtime addresses. The stock
        # addresses correspond to allocation 0x803ca8c0; this reader still
        # resolves allocation from RAM rather than assuming that address.
        audio_offset = 0x1903fc if self.scenario == 'leon' else 0x190294
        allowed_audio = dol_audio
        for off, size in self.sections:
            if not (off & 1):
                continue
            start = off & ~1
            actual = _ram(ram, base + start, size)
            wanted = expected[start:start + size]
            if actual != wanted:
                patched = bytearray(wanted)
                at = audio_offset - start
                if not 0 <= at <= len(patched) - 4:
                    raise ValueError('audio patch outside code section')
                patched[at:at + 4] = b'\x60\x00\x00\x00'
                if actual != patched:
                    raise ValueError('active REL executable bytes differ from owned source')
                allowed_audio.append({'rel_offset': audio_offset, 'patch': 'Dolphin GHAE08 audio NOP'})
        capacity = _ram(ram, CAPACITY, 1)[0]
        if capacity not in (8, 10):
            raise ValueError('inventory is not initialized with a known capacity')

        def records(address, count):
            out = []
            for i in range(count):
                raw = _ram(ram, address + 4 * i, 4)
                item, quantity, marker, unknown = raw
                if item >= 0x68 or marker > 3:
                    raise ValueError('inventory record outside statically observed ID/marker range')
                out.append({'slot': i, 'address': address + 4 * i, 'item_id': item,
                            'quantity': quantity, 'size_marker': marker,
                            'unknown_byte': unknown, 'raw_hex': raw.hex()})
            return out

        inv = records(INVENTORY, 11)
        box = records(ITEM_BOX, 64)
        slot = _ram(ram, bss + EQUIPPED_SLOT, 1)[0]
        item = _ram(ram, bss + EQUIPPED_ITEM, 1)[0]
        if slot == 0x80:
            coherent = item == 0
        else:
            coherent = slot < capacity and 1 <= item < 0x14 and inv[slot]['item_id'] == item
        return {**self.identity(), 'snapshot_sha256': sha(ram), 'module_base': base, 'bss_base': bss,
                'source_code_verified': True, 'allowed_audio_patches': allowed_audio,
                'capacity': capacity, 'inventory': inv[:10], 'reserved_item': inv[10], 'item_box': box,
                'equipped': {'slot': slot, 'item_id': item, 'coherent': coherent,
                             'loaded_weapon_word': struct.unpack('>H', _ram(ram, 0x80163f36, 2))[0]},
                'saved_equipment': {'item_id': _ram(ram, 0x801688ec, 1)[0],
                                    'slot': _ram(ram, 0x801688ed, 1)[0]},
                'ending_result_flags': _u32(_ram(ram, bss + END_RESULT_FLAGS, 4), 0),
                'save_clear_flags_raw': _ram(ram, 0x80168c5c, 8).hex(),
                'live_writes_enabled': False, 'unlock_profile_verified': False,
                'gameplay_verified': False, 'pending': list(PENDING)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dol', required=True, type=Path)
    p.add_argument('--rel', required=True, type=Path)
    operation = p.add_mutually_exclusive_group(required=True)
    operation.add_argument('--analysis-elf', type=Path)
    operation.add_argument('--snapshot', type=Path)
    p.add_argument('--out', type=Path, help='New JSON receipt file; otherwise print JSON')
    args = p.parse_args()
    build = Build(_read_bounded(args.dol, {DOL_SIZE}, 'DOL'),
                  _read_bounded(args.rel, set(REL_SIZES.values()), 'REL'))
    if args.analysis_elf:
        data = build.analysis_elf()
        with args.analysis_elf.open('xb') as stream:
            stream.write(data)
        report = {**build.identity(), 'analysis_elf': str(args.analysis_elf), 'sha256': sha(data),
                  'synthetic_rel_base': 0x80400000, 'executable_artifact': False,
                  'paired_single_reduced': True, 'pending': list(PENDING)}
    else:
        report = build.read_snapshot(_read_bounded(args.snapshot, {RAM_SIZE}, 'snapshot'))
    text = json.dumps(report, indent=2)
    if args.out:
        with args.out.open('x', encoding='utf8') as stream:
            stream.write(text + '\n')
    else:
        print(text)


if __name__ == '__main__':
    main()
