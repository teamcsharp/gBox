"""TimeSplitters 2 (GameCube) P4CK/P8CK pak directory reader.

Layout (little-endian, verified on the USA ISO GTSE4F):
  P4CK: 0x00 magic, 0x04 u32 dir_offset, 0x08 u32 dir_size, 0x0c u32 0
  P8CK (chr.pak): magic, u32 size, u32 count, u32 name_table_off, u32 name_table_len;
    entry records are in-line from 0x14 (not yet decoded); only the NUL-separated
    name table is read by parse_p8ck_names().
  files at absolute offsets inside the pak; directory = dir_size/60 records:
  char name[48] (NUL padded), u32 offset, u32 size, u32 0
"""
import struct
from collections import Counter
REC = 60

def parse_pak(d: bytes):
    if d[:4] != b'P4CK':
        raise ValueError('not a P4CK pak')
    diro, dsz, _ = struct.unpack_from('<3I', d, 4)
    if dsz % REC or diro + dsz > len(d):
        raise ValueError('bad directory bounds')
    out = []
    for i in range(dsz // REC):
        r = d[diro + i * REC: diro + (i + 1) * REC]
        name = r[:48].split(b'\0')[0].decode('latin-1')
        off, size = struct.unpack_from('<II', r, 48)
        if off + size > diro:
            raise ValueError('entry %d out of bounds: %s' % (i, name))
        out.append({'name': name, 'offset': off, 'size': size})
    return out

def census(entries):
    return Counter(e['name'].rsplit('.', 1)[-1].lower() if '.' in e['name'] else '' for e in entries)


def parse_p8ck_names(d: bytes):
    if d[:4] != b'P8CK':
        raise ValueError('not a P8CK pak')
    size, count, nto, ntl = struct.unpack_from('<4I', d, 4)
    names = d[nto:nto + ntl].split(b'\0')
    names = [n.decode('latin-1') for n in names if n]
    if len(names) != count:
        raise ValueError('name count %d != header %d' % (len(names), count))
    return names
