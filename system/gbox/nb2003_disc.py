"""Build a modded NFL Blitz 2003 disc image: decode the owned GCZ to a COPY and splice a same-size file.

The source GCZ is only read. A replaced file must keep its exact size (FST offsets/sizes untouched).
"""
import hashlib
import os

from .gcdisc import GCDisc
from .gcz import GCZ

CHUNK = 1 << 24


def decode_gcz(src: str, dst: str) -> str:
    """Stream-decode a .gcz to a plain ISO at dst (refuses to overwrite). Returns sha256 of the ISO."""
    if os.path.exists(dst):
        raise FileExistsError(dst)
    h = hashlib.sha256()
    with GCZ(src) as z, open(dst, "wb") as out:
        pos, total = 0, z.data_size
        while pos < total:
            b = z.read(pos, min(CHUNK, total - pos))
            z._cache.clear()
            out.write(b)
            h.update(b)
            pos += len(b)
    return h.hexdigest()


def splice_file(iso: str, name: str, new_data: bytes) -> tuple[int, int]:
    """Overwrite FST file `name` in a plain ISO with same-size new_data. Returns (offset, size)."""
    d = GCDisc(iso)
    off, size = d.files[name]
    d.f.close()
    if len(new_data) != size:
        raise ValueError(f"{name}: size {len(new_data)} != {size}")
    with open(iso, "r+b") as f:
        f.seek(off)
        f.write(new_data)
    return off, size


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(CHUNK):
            h.update(b)
    return h.hexdigest()
