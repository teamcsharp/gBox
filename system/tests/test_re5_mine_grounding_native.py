"""Execute the pinned native ground-before-arm contract, without a live game.

Set GBOX_RE5_ELF to the user-owned extracted ELF on Spark. No game bytes or
decompiler outputs are bundled here. The actual detach and ground instructions
execute; only quaternion accessors and the world collision service are stubbed.
Thus these tests prove hit propagation/order, not a particular map's geometry.
"""
import gc
import hashlib
import os
from pathlib import Path
import struct

import pytest

from gbox.mercs.titles import re5_proximity_native as M


@pytest.fixture(autouse=True)
def release_native_engine():
    yield
    gc.collect()


@pytest.fixture(scope='module')
def image():
    path = Path(os.environ.get('GBOX_RE5_ELF', ''))
    if not path.is_file():
        pytest.skip('set GBOX_RE5_ELF to the pinned user-owned RE5 ELF on Spark')
    ELFFile = pytest.importorskip('elftools.elf.elffile').ELFFile
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        chunks = [(s['p_vaddr'], s.data()) for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    def read(start, end):
        return next(raw[start-at:end-at] for at, raw in chunks if at <= start < end <= at+len(raw))
    assert hashlib.sha256(read(M.GROUND, M.GROUND+M.GROUND_SIZE)).hexdigest() == M.GROUND_SHA256
    return read


class GroundMachine:
    def __init__(self, image, base, *, hit, floor):
        U = pytest.importorskip('unicorn')
        from unicorn import arm64_const as A
        self.u, self.A, self.base = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM), A, base
        self.u.mem_map(base, 0x2000000)
        self.unit, self.stack, self.world = base+0x2100000, base+0x2110000, base+0x2120000
        for at in (self.unit, self.stack, self.world):
            self.u.mem_map(at, 0x10000)
        self.u.mem_write(base+M.GROUND, image(M.GROUND, M.GROUND+M.GROUND_SIZE))
        self.u.mem_write(base+0x793BC0, image(0x793BC0, 0x793F40))
        self.u.mem_write(base+0x60CC80, image(0x60CC80, 0x60CCC8))
        self.put(base+0x1CF1C30, 'Q', self.world)
        self.put(self.world+0xA0, 'f', 100000.)
        self.put(base+0x1CD2C00, 'Q', self.world+0x100)
        self.put(self.world+0x100, 'Q', self.world+0x200)
        self.put(self.unit+0x60, '4f', 1865.2962646484375, -474.8830871582031, 264.5469970703125, 7.)
        self.put(self.unit+0x2680, '4f', 1865.2962646484375, -474.8830871582031, 264.5469970703125, 0.)
        self.before = bytes(self.u.mem_read(self.unit+0x60, 16))
        self.stop, self.hit, self.floor = base+0x1000, hit, floor
        self.calls = []
        self.u.hook_add(U.UC_HOOK_CODE, self.hook)

    def reg(self, n):
        return getattr(self.A, f'UC_ARM64_REG_X{n}')

    def put(self, at, fmt, *args):
        self.u.mem_write(at, struct.pack('<'+fmt, *args))

    def get(self, at, fmt):
        return struct.unpack('<'+fmt, self.u.mem_read(at, struct.calcsize('<'+fmt)))

    def hook(self, uc, at, _size, _data):
        off = at-self.base
        if off not in (0xD22650, 0xD22880, 0x169170):
            return
        assert self.get(self.unit+0x27B9, 'B') == (0,)
        assert self.get(self.unit+0x28C1, 'B') == (0,)
        self.calls.append(off)
        if off == 0xD22650:
            self.put(uc.reg_read(self.reg(8)), '4f', 0, 0, 0, 1)
        elif off == 0xD22880:
            assert uc.reg_read(self.reg(0)) == self.unit
        else:
            assert uc.reg_read(self.reg(0)) == self.world+0x200
            assert self.get(uc.reg_read(self.reg(1)), '4f') == (0., 100., 0., 0.)
            assert self.get(uc.reg_read(self.reg(2)), '4f') == (0., -100000., 0., 0.)
            assert self.get(uc.reg_read(self.reg(3)), '3f') == struct.unpack('<3f', self.before[:12])
            assert uc.reg_read(self.reg(7)) == 1
            assert self.get(uc.reg_read(self.A.UC_ARM64_REG_SP), 'I') == (0x3FFFFFFF,)
            # Native service's real contract: nonzero W0 and a world hit point.
            if self.hit:
                self.put(uc.reg_read(self.reg(4)), '4f', 1865.2962646484375, self.floor, 264.5469970703125, 0.)
            uc.reg_write(self.reg(0), self.hit)
        uc.reg_write(self.A.UC_ARM64_REG_PC, uc.reg_read(self.A.UC_ARM64_REG_LR))

    def run(self, offset):
        self.u.reg_write(self.reg(0), self.unit)
        self.u.reg_write(self.reg(1), 1)
        self.u.reg_write(self.A.UC_ARM64_REG_SP, self.stack+0x8000)
        self.u.reg_write(self.A.UC_ARM64_REG_LR, self.stop)
        self.u.emu_start(self.base+offset, self.stop, count=2000)
        assert self.u.reg_read(self.A.UC_ARM64_REG_PC) == self.stop
        assert self.u.reg_read(self.A.UC_ARM64_REG_SP) == self.stack+0x8000
        return self.u.reg_read(self.reg(0)) & 0xFFFFFFFF


@pytest.mark.parametrize('base', [0x10000000, 0x3CA7C04000])
@pytest.mark.parametrize('hit,floor', [(0, -474.8830871582031), (1, -484.8830871582031), (1, -1929.005126953125)])
def test_native_ground_reports_hit_and_changes_only_height_before_activation(image, base, hit, floor):
    m = GroundMachine(image, base, hit=hit, floor=floor)
    # The mine's actual reset virtual60CC80 clears activation; it does not
    # discard either position. Do not substitute a flag-write for this reset.
    m.put(m.unit+0x27B9, 'B', 1)
    m.run(0x60CC80)
    assert bytes(m.u.mem_read(m.unit+0x60, 16)) == m.before
    assert m.run(M.GROUND) == hit
    actual = m.get(m.unit+0x60, '4f')
    assert actual[1] == (floor if hit else struct.unpack('<4f', m.before)[1])
    assert actual[0] == struct.unpack('<4f', m.before)[0]
    assert actual[2] == struct.unpack('<4f', m.before)[2]
    assert actual[3] == (0. if hit else 7.)
    assert m.get(m.unit+0x27B9, 'B') == (0,)
    assert m.get(m.unit+0x28C1, 'B') == (0,)
    assert m.calls == [0xD22650, 0xD22880, 0x169170]
