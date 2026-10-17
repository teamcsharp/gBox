"""RE5 Gold PS3 ARC v8: bounded reader and lossless, hash-guarded writer.

Verified with owned USA v02.00 Chris/Sheva packs. Big-endian 8-byte header,
80-byte entries, raw size in size_word >> 3, low three bits preserved.
Bodies are stored when compressed size equals raw size, otherwise zlib.
This differs from Xbox 360 LZX and 3DS ARC headers. MOD/TEX conversion,
unlocks, equipment operations and gameplay acceptance remain separate work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_MEMBER = 128 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024


def sha(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Entry:
    name: str
    type_hash: int
    compressed_size: int
    size_word: int
    offset: int
    table_offset: int

    @property
    def size(self):
        return self.size_word >> 3

    @property
    def key(self):
        return self.name, self.type_hash


class Arc:
    def __init__(self, data):
        self.data = bytes(data)
        if not 8 <= len(data) <= MAX_ARCHIVE or data[:4] != b'\0CRA':
            raise ValueError('not a bounded PS3 ARC')
        version, count = struct.unpack_from('>HH', data, 4)
        if version != 8:
            raise ValueError('expected RE5 PS3 ARC v8')
        table_end = 8 + count * 80
        if table_end > len(data):
            raise ValueError('ARC table outside source extent')
        self.entries = []
        seen, spans, total = set(), [], 0
        for i in range(count):
            at = 8 + i * 80
            raw_name = data[at:at + 64]
            if b'\0' not in raw_name:
                raise ValueError('unterminated ARC member name')
            try:
                name = raw_name.split(b'\0', 1)[0].decode('ascii')
            except UnicodeDecodeError as e:
                raise ValueError('non-ASCII ARC member name') from e
            if not name or any(ord(c) < 32 for c in name):
                raise ValueError('invalid ARC member name')
            typ, compressed, size_word, offset = struct.unpack_from('>4I', data, at + 64)
            entry = Entry(name, typ, compressed, size_word, offset, at)
            if entry.key in seen:
                raise ValueError('duplicate ARC member identity')
            seen.add(entry.key)
            if offset < table_end or offset > len(data) or compressed > len(data) - offset:
                raise ValueError('ARC payload outside source extent')
            if entry.size > MAX_MEMBER:
                raise ValueError('ARC member exceeds decoded size limit')
            total += entry.size
            if total > MAX_TOTAL:
                raise ValueError('ARC total exceeds decoded size limit')
            if compressed:
                spans.append((offset, offset + compressed))
            self.entries.append(entry)
        spans.sort()
        if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
            raise ValueError('overlapping ARC payloads')

    def find(self, name, type_hash):
        for entry in self.entries:
            if entry.key == (name, type_hash):
                return entry
        raise KeyError((name, type_hash))

    def read(self, entry):
        if not any(entry is e for e in self.entries):
            raise ValueError('member does not belong to this ARC')
        raw = self.data[entry.offset:entry.offset + entry.compressed_size]
        if entry.compressed_size == entry.size:
            return raw
        decoder = zlib.decompressobj()
        try:
            result = decoder.decompress(raw, entry.size + 1)
        except zlib.error as e:
            raise ValueError('invalid ARC zlib member') from e
        if len(result) != entry.size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('ARC zlib output does not match exact declared extent')
        return result

    def build(self):
        return self.data

    def replace(self, name, type_hash, replacement, *, expected_sha256):
        """Replace one resource without recompressing unrelated members.

        Retain the original slot if the encoded replacement fits; otherwise
        append and change only that entry's size and offset. Unknown flags,
        member order, name padding and gaps remain byte-identical.
        """
        if sha(self.data) != expected_sha256:
            raise ValueError('source hash does not match requested archive revision')
        entry = self.find(name, type_hash)
        old = self.read(entry)
        replacement = bytes(replacement)
        if len(replacement) > MAX_MEMBER:
            raise ValueError('replacement exceeds decoded size limit')
        if replacement == old:
            return self.data
        payload = replacement
        if entry.compressed_size != entry.size:
            raw = self.data[entry.offset:entry.offset + entry.compressed_size]
            # A successful decode above already validated CMF/FLG. Preserve
            # its window size; PS3 retail samples use a 16 KiB window.
            compressor = zlib.compressobj(level=6, wbits=(raw[0] >> 4) + 8)
            compressed = compressor.compress(replacement) + compressor.flush()
            if len(compressed) < len(replacement):
                payload = compressed
        out = bytearray(self.data)
        offset = entry.offset
        if len(payload) > entry.compressed_size:
            offset = len(out)
            if offset + len(payload) > MAX_ARCHIVE:
                raise ValueError('replacement exceeds archive size limit')
            out.extend(payload)
        else:
            out[offset:offset + len(payload)] = payload
        struct.pack_into('>3I', out, entry.table_offset + 68, len(payload),
                         (len(replacement) << 3) | (entry.size_word & 7), offset)
        result = bytes(out)
        checked = Arc(result)
        if checked.read(checked.find(name, type_hash)) != replacement:
            raise ValueError('ARC writer readback mismatch')
        return result

    def inventory(self):
        members = []
        for entry in self.entries:
            data = self.read(entry)
            row = {'name': entry.name, 'type_hash': f'{entry.type_hash:08x}', 'bytes': len(data),
                   'sha256': sha(data), 'stored': entry.size == entry.compressed_size}
            if data[:4] == b'\0DOM' and len(data) >= 24:
                version, bones, meshes, materials, vertices, indices = struct.unpack_from('>4H2I', data, 4)
                row['model_header'] = dict(version=version, bones=bones, meshes=meshes,
                                           materials=materials, vertices=vertices, indices=indices)
            members.append(row)
        return {'archive_sha256': sha(self.data), 'version': 8, 'members': members,
                'noop_identical': self.build() == self.data, 'gameplay_verified': False,
                'scope': 'PS3 archive reader/writer; model header counts only, not a geometry or texture decoder.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--member')
    parser.add_argument('--type-hash', type=lambda s: int(s, 16))
    parser.add_argument('--replace', type=Path)
    parser.add_argument('--expected-sha256')
    args = parser.parse_args()
    if args.source.stat().st_size > MAX_ARCHIVE:
        parser.error('archive exceeds size limit')
    arc = Arc(args.source.read_bytes())
    if args.replace:
        if not args.member or args.type_hash is None or not args.expected_sha256:
            parser.error('--replace requires --member, --type-hash and --expected-sha256')
        if args.replace.stat().st_size > MAX_MEMBER:
            parser.error('replacement exceeds size limit')
        changed = arc.replace(args.member, args.type_hash, args.replace.read_bytes(), expected_sha256=args.expected_sha256)
        with args.out.open('xb') as f:
            f.write(changed)
        if args.out.read_bytes() != changed:
            raise OSError('ARC file readback mismatch')
        print(json.dumps({'output': str(args.out), 'sha256': sha(changed),
                          'readback_verified': True, 'gameplay_verified': False}))
    else:
        with args.out.open('x', encoding='utf-8') as f:
            json.dump(arc.inventory(), f, indent=2)
        print(json.dumps({'manifest': str(args.out), 'members': len(arc.entries)}))


if __name__ == '__main__':
    main()
