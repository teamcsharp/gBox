"""Execute the title's actual mine activation and proximity-trigger gate.

Uses the locally extracted, pinned-build NSO (never a live emulator). Only
resource/vtable and base-update callees are stubbed; the primary-enable writes,
proximity-contact decision, and explosion-latch branch execute native ARM64.
The test stops at the explosion latch, before damage/effect publication.
"""
import os
import gc
from pathlib import Path
import struct

import pytest

ENABLE, UPDATE, CONFIGURE, PUT = 0x60D430, 0x81F700, 0x60D6D0, 0x91E6D0
ENABLE_PROLOGUE = bytes.fromhex('f50f1df8f44f01a9fd7b02a9fd830091')
UPDATE_PROLOGUE = bytes.fromhex('ff8303d1e84300fdfb4700f9fa6709a9')


@pytest.fixture(autouse=True)
def release_native_engines():
    yield
    gc.collect()  # Unicorn's callback cycle must be released before Windows shutdown.


@pytest.fixture(scope='module')
def image():
    local = Path(__file__).resolve().parents[2] / '.scratch-merc-recovery/assets/re5-existing-main.nso'
    path = Path(os.environ.get('GBOX_RE5_NSO', str(local)))
    if not path.is_file():
        pytest.skip('requires the user-owned extracted RE5 EBFFDB22 NSO; set GBOX_RE5_NSO')
    raw = path.read_bytes()
    assert raw[:4] == b'NSO0'
    assert raw[ENABLE + 0x100:ENABLE + 0x110] == ENABLE_PROLOGUE
    assert raw[UPDATE + 0x100:UPDATE + 0x110] == UPDATE_PROLOGUE
    return raw


class Machine:
    def __init__(self, raw, base):
        U = pytest.importorskip('unicorn')
        from unicorn import arm64_const as A
        self.U, self.A, self.base = U, A, base
        self.u = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
        self.u.mem_map(base, 0x2000000)
        self.unit, self.primary, self.secondary = base + 0x2100000, base + 0x2110000, base + 0x2120000
        self.descriptor, self.table, self.manager = base + 0x2130000, base + 0x2140000, base + 0x2150000
        self.stack, self.vtable, self.actor_table = base + 0x2160000, base + 0x2170000, base + 0x2180000
        self.action = base + 0x2190000
        for at in (self.unit, self.primary, self.secondary, self.descriptor, self.table,
                   self.manager, self.stack, self.vtable, self.actor_table, self.action):
            self.u.mem_map(at, 0x10000)
        self.u.mem_write(base + ENABLE, raw[ENABLE + 0x100:0x60D524 + 0x100])
        self.u.mem_write(base + UPDATE, raw[UPDATE + 0x100:0x8209E4 + 0x100])
        self.u.mem_write(base + CONFIGURE, raw[CONFIGURE + 0x100:0x60D860 + 0x100])
        self.u.mem_write(base + PUT, raw[PUT + 0x100:0x91E800 + 0x100])
        self.stop, self.describe = base + 0x1000, base + 0x1100
        self.put(self.unit, 'Q', self.vtable)
        self.put(self.vtable + 0x28, 'Q', self.describe)
        self.put(self.descriptor + 0x34, 'I', 0x07010A00)
        self.put(base + 0x1AA7E20 + 8, 'Q', self.table)
        self.put(self.table + 10 * 0x50 + 0x26, 'B', 1)
        self.put(self.unit + 0x134, 'I', 0x1234567)
        self.put(self.unit + 0x2710, 'Q', self.primary)
        self.put(self.unit + 0x2718, 'I', 0xFFFFFFFF)
        self.put(self.unit + 0x28C8, 'Q', self.secondary)
        self.put(self.secondary + 0x14, 'B', 1)
        self.put(self.primary + 0x18, 'I', 7)
        self.put(self.unit + 0x27B9, 'B', 1)  # native placed/grounded state
        self.put(base + 0x1CF1408, 'Q', self.manager)
        self.put(self.manager + 0xC0, 'Q', self.actor_table)
        self.put(self.actor_table + 8, 'Q', self.unit)
        # Native contact-owner check: the entry's owner byte matches the
        # current player's identity. No enemy/contact branch is stubbed.
        self.put(base + 0x1CD2BE0, 'Q', base + 0x1900000)
        self.put(base + 0x1900000, 'Q', base + 0x1901000)
        self.put(base + 0x1901000 + 0x584E0, 'Q', base + 0x1902000)
        self.put(base + 0x1902000 + 0x838, 'Q', 0)
        self.calls, self.explosion_latched = [], False
        self.u.hook_add(U.UC_HOOK_CODE, self.hook)

    def reg(self, i):
        return getattr(self.A, f'UC_ARM64_REG_X{i}')

    def put(self, addr, fmt, *values):
        self.u.mem_write(addr, struct.pack('<' + fmt, *values))

    def get(self, addr, fmt):
        return struct.unpack('<' + fmt, self.u.mem_read(addr, struct.calcsize('<' + fmt)))[0]

    def hook(self, uc, addr, size, data):
        if addr == self.base + 0x81FB8C:
            # The actual update just set unit+0x28C1=1. Subsequent code
            # publishes explosion damage/effects and is outside this gate test.
            self.explosion_latched = True
            uc.emu_stop()
        elif addr in (self.describe, self.base + 0xD0C360, self.base + 0x7E4720):
            self.calls.append((addr - self.base, uc.reg_read(self.reg(0)), uc.reg_read(self.reg(1))))
            for n in range(19):
                uc.reg_write(self.reg(n), 0xDEAD0000 + n)
            if addr == self.describe:
                uc.reg_write(self.reg(0), self.descriptor)
            uc.reg_write(self.A.UC_ARM64_REG_PC, uc.reg_read(self.A.UC_ARM64_REG_LR))

    def run(self, offset, arg=0, *, args=None):
        for i, value in enumerate(args if args is not None else (self.unit, arg)):
            self.u.reg_write(self.reg(i), value)
        self.u.reg_write(self.A.UC_ARM64_REG_SP, self.stack + 0x8000)
        self.u.reg_write(self.A.UC_ARM64_REG_LR, self.stop)
        self.u.emu_start(self.base + offset, self.stop, count=2000)
        if not self.explosion_latched:
            assert self.u.reg_read(self.A.UC_ARM64_REG_PC) == self.stop
            assert self.u.reg_read(self.A.UC_ARM64_REG_SP) == self.stack + 0x8000


@pytest.mark.parametrize('base', [0x10000000, 0x3CA7C04000])
def test_native_enable_sets_primary_volume_resource_flag_and_owner(image, base):
    m = Machine(image, base)
    m.run(ENABLE, 1)
    assert m.get(m.primary + 0x14, 'B') == 1
    assert m.get(m.secondary + 0x14, 'B') == 1
    assert m.get(m.primary + 0x18, 'I') == 7  # enabling preserves accumulated contact
    assert m.get(m.unit + 0x134, 'I') == 0x1234567 | (1 << 27)
    assert m.get(m.unit + 0x2720, 'B') == 1
    assert m.get(m.unit + 0x2721, 'B') == 1
    assert m.get(m.unit + 0x2728, 'Q') == m.unit
    assert (0xD0C360, m.unit, 0) in m.calls


def test_native_disable_clears_primary_contact_and_enable_fields(image):
    m = Machine(image, 0x10000000)
    m.run(ENABLE, 1)
    m.run(ENABLE, 0)
    assert m.get(m.primary + 0x14, 'B') == 0
    assert m.get(m.primary + 0x18, 'I') == 0
    assert m.get(m.unit + 0x134, 'I') == 0x1234567
    assert m.get(m.unit + 0x2721, 'B') == 0
    assert m.get(m.secondary + 0x14, 'B') == 1  # a distinct proximity volume
    assert (0xD0C360, m.unit, 1) in m.calls


@pytest.mark.parametrize('base', [0x10000000, 0x3CA7C04000])
@pytest.mark.parametrize('enabled', [False, True])
def test_real_proximity_contact_only_reaches_explosion_latch_with_primary_enabled(image, base, enabled):
    m = Machine(image, base)
    m.put(m.secondary + 0x18, 'I', 1)  # native collision system reports a proximity contact
    if enabled:
        m.run(ENABLE, 1)
    m.run(UPDATE)
    assert m.get(m.secondary + 0x14, 'B') == 1
    assert bool(m.get(m.unit + 0x24CC, 'B') & 1) is enabled
    assert bool(m.get(m.unit + 0x28C1, 'B')) is enabled
    assert m.explosion_latched is enabled


def test_enabling_without_contact_does_not_invent_an_explosion(image):
    m = Machine(image, 0x10000000)
    m.run(ENABLE, 1)
    m.run(UPDATE)
    assert not m.explosion_latched
    assert m.get(m.unit + 0x28C1, 'B') == 0


@pytest.mark.parametrize('base', [0x10000000, 0x3CA7C04000])
@pytest.mark.parametrize('enable_on_put', [0, 1])
def test_native_configure_and_put_chain_arms_only_when_third_argument_requests_it(image, base, enable_on_put):
    m = Machine(image, base)
    # The actual factory setup call, followed by the actual state-3 action.
    # No explicit enable60D430 call, primary-volume write or latch override.
    m.run(CONFIGURE, args=(m.unit, 1, enable_on_put, 0x10A, 1))
    assert m.get(m.primary + 0x14, 'B') == 0
    assert m.get(m.unit + 0x273F, 'B') == enable_on_put
    m.run(PUT, args=(m.action, m.unit))
    assert m.get(m.action + 0x28, 'B') == 1
    assert m.get(m.primary + 0x14, 'B') == enable_on_put
    assert m.get(m.unit + 0x2721, 'B') == enable_on_put
    assert bool(m.get(m.unit + 0x134, 'I') & (1 << 27)) is bool(enable_on_put)
    assert m.get(m.secondary + 0x14, 'B') == 1
    m.put(m.secondary + 0x18, 'I', 1)
    m.run(UPDATE)
    assert m.explosion_latched is bool(enable_on_put)


def test_late_enable_on_put_flag_cannot_replay_already_consumed_put_action(image):
    m = Machine(image, 0x10000000)
    m.run(CONFIGURE, args=(m.unit, 1, 0, 0x10A, 1))
    m.run(PUT, args=(m.action, m.unit))
    m.run(CONFIGURE, args=(m.unit, 1, 1, 0x10A, 1))
    m.run(PUT, args=(m.action, m.unit))
    assert m.get(m.unit + 0x273F, 'B') == 1
    assert m.get(m.action + 0x28, 'B') == 1
    assert m.get(m.primary + 0x14, 'B') == 0
