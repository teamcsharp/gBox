"""Execute the authored per-frame guard, not a Python copy of its decisions."""
import struct
import threading
from types import SimpleNamespace

import pytest

from gbox.mercs.native.re4_82c2a04a import code as C
from gbox.mercs.native.re4_82c2a04a import build_dispatch as B
from gbox.mercs.titles import re4_weapon_rate as G
from gbox.mercs.titles import re4_switch_native as N

BASE, PLAYER, WEP, OBJ, BOX = 0x100000000, 0x200000000, 0x210000000, 0x220000000, 0x230000000


class Machine:
    def __init__(self, cls=7, routine=(0, 6, 2, 1)):
        uc = pytest.importorskip('unicorn')
        from unicorn import arm64_const as A
        self.A = A
        self.u = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
        for at in (BASE + (C.CAVE_AT & ~0xfff), BASE + 0x1279000,
                   BASE + 0x124d000, PLAYER, WEP, OBJ, BOX):
            self.u.mem_map(at, 0x1000)
        self.u.mem_write(BASE + C.WEAPON_RATE_AT, C.WEAPON_RATE[4])
        self.u.mem_write(BASE + C.CAVE_AT, C.DISPATCH[4])
        self.put(PLAYER + 0x110, '<I', 7)
        self.put(PLAYER + 0x938, '<Q', WEP)
        self.put(WEP + 0x38, '<Q', OBJ)
        self.put(OBJ + 0x110, '<I', 19)
        self.put(PLAYER + 0x304, '<f', 1.0)
        self.put(OBJ + 0x304, '<f', 1.0)
        self.put(BASE + 0x1279360, '<H', 1000)
        self.put(BASE + 0x127936c, '<B', cls)
        self.put(BASE + 0x124d930, '<H', 44)
        self.u.mem_write(PLAYER + 0x114, bytes(routine))
        self.put(BOX + C.RATE['player_id'], '<I', 7)
        self.put(BOX + C.RATE['desired'], '<f', 20.0)
        self.put(BOX + C.RATE['lease'], '<I', 60)

    def put(self, at, fmt, value):
        self.u.mem_write(at, struct.pack(fmt, value))

    def get(self, at, fmt):
        return struct.unpack(fmt, self.u.mem_read(at, struct.calcsize(fmt)))[0]

    def field(self, name, fmt='<I'):
        return self.get(BOX + C.RATE[name], fmt)

    def tick(self):
        self.u.reg_write(self.A.UC_ARM64_REG_X0, PLAYER)
        self.u.reg_write(self.A.UC_ARM64_REG_X1, BOX)
        self.u.reg_write(self.A.UC_ARM64_REG_X30, BASE + C.SELFTEST_AT)
        self.u.emu_start(BASE + C.WEAPON_RATE_AT, BASE + C.SELFTEST_AT, count=200)


def test_authored_native_images_reproduce():
    pytest.importorskip('keystone')
    assert B.check()['ok']


@pytest.mark.parametrize('cls', sorted(G.GUN_CLASSES))
@pytest.mark.parametrize('stage', [0, 1, 2, 3])
def test_each_native_firearm_action_owns_both_rates(cls, stage):
    m = Machine(cls, (0, 6, stage, 1))
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 20
    assert m.get(OBJ + 0x304, '<f') == 20
    assert m.field('owned') == 3
    assert m.field('frames') == 1
    assert m.field('sequence') == 2
    assert m.field('class') == cls


@pytest.mark.parametrize('routine', [(0, 0, 0, 0), (0, 1, 4, 0), (1, 6, 2, 1),
                                     (2, 0, 0, 1), (0, 6, 4, 0), (0, 6, 5, 0), (0, 7, 2, 1)])
def test_native_transition_restores_before_next_routine_update(routine):
    m = Machine()
    m.tick()
    m.u.mem_write(PLAYER + 0x114, bytes(routine))
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.get(OBJ + 0x304, '<f') == 1
    assert m.field('owned') == 0
    assert m.field('restores') == 1
    assert m.field('frames') == 1


def test_dispatch_keeps_call_abi_and_original_tick_after_passive_guard():
    m = Machine()
    stack, clone = 0x240000000, BOX + 0x200
    m.u.mem_map(stack, 0x1000)
    m.put(PLAYER, '<Q', clone)
    m.put(clone + C.CLONE_MAILBOX_OFF, '<Q', BOX)
    m.put(clone + C.CLONE_ORIGINAL_OFF, '<Q', BASE + C.CAVE_END - 8)
    m.u.mem_write(BASE + C.CAVE_END - 8, bytes.fromhex('c0035fd6'))
    m.put(BOX + C.MAILBOX['target'], '<Q', BASE + C.SELFTEST_AT)
    m.put(BOX + C.MAILBOX['args'], '<Q', 0x12345678)
    m.put(BOX + C.MAILBOX['state'], '<I', C.STATE['requested'])
    m.put(BOX + C.MAILBOX['generation'], '<Q', 91)
    m.u.reg_write(m.A.UC_ARM64_REG_SP, stack + 0x800)
    m.u.reg_write(m.A.UC_ARM64_REG_X0, PLAYER)
    m.u.reg_write(m.A.UC_ARM64_REG_X30, BASE + C.CAVE_END - 4)
    for reg, value in [(m.A.UC_ARM64_REG_X19, 19), (m.A.UC_ARM64_REG_X20, 20),
                       (m.A.UC_ARM64_REG_X21, 21), (m.A.UC_ARM64_REG_X22, 22)]:
        m.u.reg_write(reg, value)
    m.u.emu_start(BASE + C.CAVE_AT, BASE + C.CAVE_END - 4, count=300)
    assert m.get(BOX + C.MAILBOX['result'], '<Q') == 0x12345678
    assert m.get(BOX + C.MAILBOX['state'], '<I') == C.STATE['done']
    assert m.get(BOX + C.MAILBOX['generation'], '<Q') == 91
    assert m.get(BOX + C.MAILBOX['ticks'], '<Q') == 1
    assert m.u.reg_read(m.A.UC_ARM64_REG_X0) == PLAYER
    assert [m.u.reg_read(reg) for reg in (m.A.UC_ARM64_REG_X19, m.A.UC_ARM64_REG_X20,
            m.A.UC_ARM64_REG_X21, m.A.UC_ARM64_REG_X22)] == [19, 20, 21, 22]
    assert m.u.reg_read(m.A.UC_ARM64_REG_SP) == stack + 0x800
    assert m.field('frames') == 1


@pytest.mark.parametrize('cls', [0, 16, 19, 22, 23, 25, 28, 32, 34, 45, 47, 255])
def test_non_firearms_do_not_acquire_rate(cls):
    m = Machine(cls)
    m.tick()
    assert m.field('owned') == 0
    assert m.get(PLAYER + 0x304, '<f') == 1


@pytest.mark.parametrize('value', [1.0, 0.0, -20.0, 20.1, float('nan'), float('inf')])
def test_invalid_or_disabled_desired_rate_restores(value):
    m = Machine()
    m.tick()
    m.put(BOX + C.RATE['desired'], '<f', value)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.get(OBJ + 0x304, '<f') == 1


def test_lease_is_bounded_without_host_ticks():
    m = Machine()
    m.put(BOX + C.RATE['lease'], '<I', 2)
    m.tick()
    m.tick()
    assert m.field('lease') == 0 and m.field('frames') == 2
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.field('owned') == 0


def test_dead_player_relinquishes_ownership():
    m = Machine()
    m.tick()
    m.put(BASE + 0x1279360, '<H', 0)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.get(OBJ + 0x304, '<f') == 1


def test_external_rate_is_never_claimed_or_overwritten():
    m = Machine()
    m.put(PLAYER + 0x304, '<f', 0.5)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 0.5
    assert m.field('owned') == 0
    m.put(PLAYER + 0x304, '<f', 1.0)
    m.tick()
    m.put(PLAYER + 0x304, '<f', 0.25)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 0.25
    assert m.get(OBJ + 0x304, '<f') == 1
    assert m.field('owned') == 0


def test_external_object_rate_is_preserved_when_player_returns_to_baseline():
    m = Machine()
    m.tick()
    m.put(OBJ + 0x304, '<f', 0.5)
    m.u.mem_write(PLAYER + 0x114, bytes([0, 0, 0, 0]))
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.get(OBJ + 0x304, '<f') == 0.5


def test_recycled_actor_is_not_written():
    m = Machine()
    m.tick()
    m.put(PLAYER + 0x110, '<I', 8)
    m.put(PLAYER + 0x304, '<f', 0.5)
    m.put(OBJ + 0x304, '<f', 0.25)
    m.tick()
    assert m.field('owned') == 0
    assert m.get(PLAYER + 0x304, '<f') == 0.5
    assert m.get(OBJ + 0x304, '<f') == 0.25


def test_recycled_object_is_not_restored():
    m = Machine()
    m.tick()
    m.put(OBJ + 0x110, '<I', 20)
    m.put(OBJ + 0x304, '<f', 0.5)
    m.put(BOX + C.RATE['lease'], '<I', 0)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.get(OBJ + 0x304, '<f') == 0.5


def test_no_invalid_weapon_pointer_dereference():
    m = Machine()
    m.put(PLAYER + 0x938, '<Q', 3)
    m.tick()
    assert m.field('owned') == 1
    m.put(BOX + C.RATE['lease'], '<I', 0)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1


def test_rate_change_retains_owned_baseline():
    m = Machine()
    m.tick()
    m.put(BOX + C.RATE['desired'], '<f', 10)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 10
    assert m.get(OBJ + 0x304, '<f') == 10
    m.put(BOX + C.RATE['lease'], '<I', 0)
    m.tick()
    assert m.get(PLAYER + 0x304, '<f') == 1
    assert m.get(OBJ + 0x304, '<f') == 1


def test_controller_lease_preserves_request_mailbox_and_detach_restores(monkeypatch):
    from test_re4_native import fake_controller, put, PLAYER as P, MAILBOX as MB
    ctl = fake_controller(monkeypatch)
    ctl.ready()
    before = ctl.rd(MB, 0x60)
    row = G.configure(ctl, 20, (P, 7))
    assert row['state'] == 'pending'
    assert ctl.rd(MB, 0x60) == before
    assert ctl.w(MB + C.RATE['lease']) == 60
    put(ctl.mem, MB + C.RATE['owned'], struct.pack('<I', 1))
    put(ctl.mem, MB + C.RATE['applied'], struct.pack('<f', 20))
    put(ctl.mem, P + 0x304, struct.pack('<f', 20))
    ctl.detach()
    assert struct.unpack('<f', ctl.rd(P + 0x304, 4))[0] == 1
    assert ctl.w(MB + C.RATE['lease']) == 0


def test_busy_controller_never_blocks_or_changes_combat(monkeypatch):
    from gbox.mercs import interventions
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(interventions, 'native_controller', lambda ad: SimpleNamespace(lock=lock))
    snap = {'player': {'ptr': PLAYER, 'id': 7}, 'game': {'phase': 'playing'}}
    st = {'fire_rate': 20}
    G.maintain(object(), snap, st)
    assert st == {'fire_rate': 20, 'gun_rate_state': 'busy'}


def test_coherent_native_observation_and_torn_read(monkeypatch):
    m = Machine()
    m.tick()
    ctl = SimpleNamespace(mailbox=BOX, player=PLAYER, player_id=7,
                          rd=lambda at, n: bytes(m.u.mem_read(at, n)),
                          w=lambda at: m.get(at, '<I'))
    row = G.observation(ctl)
    assert row['state'] == 'native' and row['applied_x'] == 20
    assert row['scaled_frames'] == 1 and row['routine'] == [0, 6, 2, 1]
    assert 'shots' not in row
    m.put(BOX + C.RATE['sequence'], '<I', 3)
    assert G.observation(ctl)['state'] == 'unknown'


def test_new_binding_clears_old_passive_lease(monkeypatch):
    from test_re4_native import fake_controller, put, MAILBOX as MB
    ctl = fake_controller(monkeypatch)
    put(ctl.mem, MB + C.RATE['desired'], struct.pack('<f', 20))
    put(ctl.mem, MB + C.RATE['lease'], struct.pack('<I', 60))
    ctl.attach()
    assert ctl.rd(MB + 0x60, C.MAILBOX_SIZE - 0x60) == bytes(C.MAILBOX_SIZE - 0x60)


def test_stale_player_cannot_refresh_lease(monkeypatch):
    from test_re4_native import fake_controller
    ctl = fake_controller(monkeypatch)
    with pytest.raises(RuntimeError, match='player changed'):
        G.configure(ctl, 20, (PLAYER, 999))
    assert not ctl.attached()


def test_bow_handoff_cannot_capture_native_gun_boost_as_baseline():
    from test_re4_switch_bow_rate import world, snap, f32, set_routine, PLAYER as P, OBJ as O
    from gbox.mercs.titles import re4_switch_mods as M
    ad, st = world(speed=20.0, obj_speed=20.0), {'fire_rate': 20.0}
    assert M._motion_rate(ad, snap(), st) == 0
    assert st['motion_rate']['addrs'] == {}
    # The next native update sees the bow class and restores its own gun rate.
    struct.pack_into('<f', ad.at[P], 0x304, 1.0)
    struct.pack_into('<f', ad.at[O], 0x304, 1.0)
    assert M._motion_rate(ad, snap(), st) == 2
    set_routine(ad, (0, 1, 0, 0))
    M._motion_rate(ad, snap(), st)
    assert f32(ad, P + 0x304) == 1 and f32(ad, O + 0x304) == 1


def test_bow_item_fallback_does_not_accelerate_walking():
    from test_re4_switch_bow_rate import world, snap
    from gbox.mercs.titles import re4_switch_mods as M, re4_weapons as W
    ad = world(routine=(0, 1, 0, 0))
    s = dict(snap(5), equipped_id=W.BOW_ITEM)
    assert M._motion_rate(ad, s, {'fire_rate': 20}) == 0
    assert ad.writes == []
