"""Mine-thrower darts in the exact RE4 Switch object pool.

Spawn 1B43C0 creates type 5F with vtable AED720. Weapon 2DBAB0 uses
subtypes 0/1; rocket paths 348D30/351B60 use 2/3 and must be excluded.
1B4D20 initiates the real explosion; state 6 performs the area attack.
"""
from __future__ import annotations

import math
import struct

POOL, STRIDE, VTABLE = 0xAE6EF8, 0x10C8, 0xAED720
FUSE_S = 3.0
DETONATE = 0x1B4D20
DETONATE_PROLOGUE = bytes.fromhex('ff0301d1f44f02a9fd7b03a9fdc30091f30300aa686644391f0d00717f860779')


def read_mines(ctl) -> list[dict]:
    from . import re4_switch as R
    pool = bytes(ctl.rd(ctl.base + POOL, 0x18))
    array, count, stride = struct.unpack_from('<QII', pool, 8)
    if not R.ptr_ok(array) or not 1 <= count <= 512 or stride != STRIDE or not R.ptr_ok(array + count * stride - 1):
        raise ValueError('mine projectile pool layout is unavailable')
    rows = []
    # Bounded contiguous reads avoid hundreds of adapter round trips per tick.
    chunk, chunk_at = b'', 0
    for index in range(count):
        ptr = array + index * stride
        if index % 16 == 0:
            chunk_at = ptr
            size = min(16, count - index) * stride
            chunk = bytes(ctl.rd(ptr, size))
            if len(chunk) != size:
                raise ValueError('incomplete mine projectile pool read')
        offset = ptr - chunk_at
        head = chunk[offset:offset + 0x120]
        vt, flags = struct.unpack_from('<QI', head)
        if vt != ctl.base + VTABLE or flags & 0x201 != 1 or head[0x118] != 0x5F:
            continue
        if head[0x119] not in (0, 1) or head[0x114] != 1 or head[0x115] > 4:
            continue
        behavior = chunk[offset + 0x540:offset + 0x542]
        pos = struct.unpack_from('<3f', head, 0xA4)
        if not all(math.isfinite(v) for v in pos):
            continue
        generation = struct.unpack_from('<I', head, 0x110)[0]
        rows.append({'ptr': ptr, 'generation': generation, 'pos': pos,
                     'state': head[0x115], 'subtype': head[0x119], 'wall_attached': bool(behavior[0]),
                     'safe_mm': (2000.0 if behavior[1] == 0 else 4000.0 if behavior[1] == 1 else 6000.0) + 1000.0})
    return rows


class Fuses:
    """Three seconds from first observed spawn; expose polling lateness honestly.

    Keys include the native generation, so a reused slot receives a new fuse.
    A submitted request is consumed even if its completion becomes uncertain.
    """
    def __init__(self):
        self.identity = None
        self.first_seen = {}
        self.submitted = set()

    def observe(self, identity, rows, now):
        if identity != self.identity:
            self.identity, self.first_seen, self.submitted = identity, {}, set()
        live = {(row['ptr'], row['generation']) for row in rows}
        self.first_seen = {key: self.first_seen.get(key, now) for key in live}
        self.submitted.intersection_update(live)
        return [dict(row, fuse_due_at=self.first_seen[(row['ptr'], row['generation'])] + FUSE_S)
                for row in rows]

    def claim(self, rows, now, *, manual=False):
        due = []
        for row in rows:
            key = row['ptr'], row['generation']
            if key not in self.submitted and (manual or now >= row['fuse_due_at']):
                self.submitted.add(key)
                due.append(row)
        return due
