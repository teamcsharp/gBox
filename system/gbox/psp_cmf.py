"""PSP Peace Walker USRDIR/CAMO/*.cmf container header (observed on owned ULES01372 CSO).

Layout (little endian, offset base = start of file), verified on 40 CAMO files:
  0x00 'CMF\\x10'   0x04 u32 total file size   0x0C u32 header size
  0x30 u32 N (entry count)   0x40 N x (u32 id, u32 length)   body starts at header size.
Entry meaning / body codec are NOT yet established; sum(length) != body size.
"""
import struct


def parse_cmf(b):
    if b[:4] != b'CMF\x10':
        raise ValueError('not a CMF container')
    total, _, hdr = struct.unpack_from('<III', b, 4)
    n, = struct.unpack_from('<I', b, 0x30)
    if total != len(b):
        raise ValueError('size field %d != file size %d' % (total, len(b)))
    if 0x40 + 8 * n > hdr or hdr > len(b):
        raise ValueError('entry table overruns header')
    entries = [struct.unpack_from('<II', b, 0x40 + 8 * i) for i in range(n)]
    return {'total': total, 'header_size': hdr, 'count': n, 'entries': entries, 'body_size': total - hdr}
