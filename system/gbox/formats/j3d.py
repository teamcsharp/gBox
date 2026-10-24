"""Bounded read-only Nintendo J3D (JSystem) model container chunk walker (Wind Waker .bdl/.bmd).

Layout (zeldaret/tww J3DModelLoader.h, J3DModelFileData): 0x20-byte header
  'J3D2' | type 'bdl4'/'bmd3'/'bmd2' | u32 file size | u32 chunk count | 16 bytes sub-version,
then chunk_count chunks, each 'TAG4' | u32 size (incl. 8-byte header), big-endian, 32-byte aligned.
Chunk walk only: no vertex/shape decode, no writer. Unknown chunk bytes are preserved by offset.
"""
import struct


class J3DError(ValueError):
    pass


def chunks(raw, max_chunks=64):
    """Return {'type': str, 'size': int, 'chunks': [(tag, offset, size)]}; every extent bounded by len(raw)."""
    if len(raw) < 0x20 or raw[:4] != b'J3D2':
        raise J3DError('Truncated or invalid J3D2 header')
    kind = raw[4:8].decode('latin-1')
    size, n = struct.unpack_from('>II', raw, 8)
    if size != len(raw) or n == 0 or n > max_chunks:
        raise J3DError('J3D size or chunk count mismatch')
    out, off = [], 0x20
    for _ in range(n):
        if off + 8 > size:
            raise J3DError('Truncated J3D chunk header')
        tag = raw[off:off + 4]
        csz = struct.unpack_from('>I', raw, off + 4)[0]
        if csz < 8 or csz > size - off or not all(32 <= c < 127 for c in tag):
            raise J3DError('Invalid J3D chunk extent')
        out.append((tag.decode('ascii'), off, csz))
        off += csz
    if off != size:
        raise J3DError('J3D chunks do not cover the file')
    return {'type': kind, 'size': size, 'chunks': out}
