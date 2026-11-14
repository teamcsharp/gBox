"""Aimed RE5 pitch survives the native camera's next update without changing its mode."""
import hashlib
import math
import os
from pathlib import Path
import struct

import pytest

from gbox.mercs.titles import re5_switch_aim as A
from test_re5_switch_aim import BASE, CTRL, PLAYER, Session, guest


MAIN, PAD, CONFIG, PARAMS = (0x5D40000000 + i*0x100000 for i in range(4))
QFPS = CTRL + A.CTRL_QFPS
INPUT_CTRL = 0x5D50000000


def floating(g, address, value):
    g.put(address, struct.pack('<f', value))


def number(g, address):
    return struct.unpack('<f', g.rd(address, 4))[0]


def normal(*, source=.0011226, offset=0., limits=(1., -1., 1., -1.)):
    g = guest(pitch=-(source+offset))
    g.q(PLAYER + 0x1A00, 17)
    g.q(QFPS + 0x130, PLAYER)
    g.put(QFPS + 0x195, b'\x01')
    g.q(BASE+A.S_MAIN, MAIN); g.q(BASE+A.S_PAD, PAD); g.q(BASE+A.S_AIM_PARAMS, PARAMS)
    g.q(MAIN+0x584E0, CONFIG)
    g.put(PARAMS+0x440, struct.pack('<4f', *limits))
    g.put(PLAYER+A.P_PITCH_DERIVED, struct.pack('<2f', source+offset, source))
    return g


def native_frame(g, offset=0.):
    """Behavioral fixture; the optional pinned ELF test below executes the real instructions."""
    derived = number(g, PLAYER+A.P_PITCH_INPUT)+offset
    floating(g, PLAYER+A.P_PITCH_DERIVED, derived)
    floating(g, QFPS+A.QF_PITCH, -derived)


def alternate(*, source=.1, limit=.997, via='pad'):
    g = normal()
    g.put(PAD+0x8D0C if via == 'pad' else CONFIG+0xA74, b'\x01')
    g.q(PLAYER+A.P_INPUT_CTRL, INPUT_CTRL)
    g.q(INPUT_CTRL, BASE+A.INPUT_CTRL_VT)
    g.q(INPUT_CTRL+A.C_AIM, BASE+A.INPUT_AIM_VT)
    g.q(INPUT_CTRL+0x48, PLAYER)
    floating(g, INPUT_CTRL+A.C_PITCH_INPUT, source)
    floating(g, PLAYER+A.P_ALT_PITCH, source)
    floating(g, PARAMS+0x29C, limit)
    floating(g, QFPS+A.QF_PITCH, -source)
    return g


@pytest.mark.parametrize('via', ['pad', 'config'])
def test_alternate_aim_uses_owned_persistent_controller_without_changing_sway(via):
    g = alternate(via=via)
    floating(g, INPUT_CTRL+0x800, .07)  # native sway remains separate
    floating(g, PLAYER+0x3F5C, .17)     # animated output is not persistent pitch
    writer = A.aim_writer(Session(g))
    assert writer(A.aim_state(g, BASE, PLAYER), -.4, None)
    assert [a for a, _ in g.writes] == [INPUT_CTRL+A.C_PITCH_INPUT]
    assert number(g, INPUT_CTRL+A.C_PITCH_INPUT) == pytest.approx(.4)
    assert number(g, PLAYER+A.P_ALT_PITCH) == pytest.approx(.1)
    assert number(g, QFPS+A.QF_PITCH) == pytest.approx(-.1)
    assert number(g, INPUT_CTRL+0x800) == pytest.approx(.07)
    assert number(g, PLAYER+0x3F5C) == pytest.approx(.17)
    assert writer.pitch_state['mode'] == 'controller'
    assert writer.pitch_state['offset'] == 0


@pytest.mark.parametrize('pitch,limit,expected', [(-1., .6, .6), (1., .6, -.6), (-1., 2., 1.)])
def test_alternate_accumulator_obeys_native_and_camera_bounds(pitch, limit, expected):
    g = alternate(limit=limit)
    assert A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), pitch, None)
    assert number(g, INPUT_CTRL+A.C_PITCH_INPUT) == pytest.approx(expected)


@pytest.mark.parametrize('changed', ['pointer', 'vtable', 'owner', 'embedded', 'control_mode',
                                    'nan_source', 'outside_source', 'nan_derived', 'limit', 'nan_limit',
                                    'short_config'])
def test_alternate_invalid_ownership_or_bounds_never_falls_back_to_camera(changed):
    g = alternate()
    if changed == 'pointer': g.q(PLAYER+A.P_INPUT_CTRL, 0)
    elif changed == 'vtable': g.q(INPUT_CTRL, BASE+A.INPUT_CTRL_VT+8)
    elif changed == 'owner': g.q(INPUT_CTRL+0x48, PLAYER+0x100000)
    elif changed == 'embedded': g.q(INPUT_CTRL+A.C_AIM, 0)
    elif changed == 'control_mode': g.put(INPUT_CTRL+0x34C, struct.pack('<i', 1))
    elif changed == 'nan_source': floating(g, INPUT_CTRL+A.C_PITCH_INPUT, math.nan)
    elif changed == 'outside_source': floating(g, INPUT_CTRL+A.C_PITCH_INPUT, 1.01)
    elif changed == 'nan_derived': floating(g, PLAYER+A.P_ALT_PITCH, math.nan)
    elif changed == 'limit': floating(g, PARAMS+0x29C, 0.)
    elif changed == 'nan_limit': floating(g, PARAMS+0x29C, math.nan)
    else:
        rd = g.rd
        g.rd = lambda a, n: b'' if a == CONFIG+0xA74 else rd(a, n)
    assert not A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), -.4, .7)
    assert g.writes == []


@pytest.mark.parametrize('changed', ['input', 'owner', 'pointer', 'control_mode', 'pad_mode', 'config_mode'])
def test_alternate_preflight_rejects_native_update_and_mode_races(changed):
    g = alternate(); state = A.aim_state(g, BASE, PLAYER)
    rd, done = g.rd, [False]
    def racing(a, n):
        value = rd(a, n)
        if a == PARAMS+0x29C and not done[0]:
            done[0] = True
            if changed == 'input': floating(g, INPUT_CTRL+A.C_PITCH_INPUT, .2)
            elif changed == 'owner': g.q(INPUT_CTRL+0x48, PLAYER+8)
            elif changed == 'pointer': g.q(PLAYER+A.P_INPUT_CTRL, INPUT_CTRL+0x10000)
            elif changed == 'control_mode': g.put(INPUT_CTRL+0x34C, struct.pack('<i', 1))
            elif changed == 'pad_mode': g.put(PAD+0x8D0C, b'\x02')
            else: g.put(CONFIG+0xA74, b'\x01')
        return value
    g.rd = racing
    assert not A.aim_writer(Session(g))(state, -.4, .7)
    assert g.writes == []


def test_alternate_controller_replaced_after_write_cannot_authorize_heading_or_fire():
    g = alternate(); write = g.write_memory
    def racing(a, data):
        write(a, data)
        g.q(PLAYER+A.P_INPUT_CTRL, INPUT_CTRL+0x10000)
    g.write_memory = racing
    assert not A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), -.4, .7)
    assert [a for a, _ in g.writes] == [INPUT_CTRL+A.C_PITCH_INPUT]


def test_normal_aim_updates_persistent_input_and_camera_consumes_it_next_frame():
    g = normal(offset=.01)
    writer = A.aim_writer(Session(g))
    assert writer(A.aim_state(g, BASE, PLAYER), -.4, None)
    assert [a for a, _ in g.writes] == [PLAYER+A.P_PITCH_INPUT]
    assert number(g, PLAYER+A.P_PITCH_INPUT) == pytest.approx(.39)
    # Until native code runs, its old camera/ray remains the only firing evidence.
    assert number(g, QFPS+A.QF_PITCH) == pytest.approx(-.0111226)
    native_frame(g, .01)
    assert number(g, QFPS+A.QF_PITCH) == pytest.approx(-.4)
    native_frame(g, .01)
    assert number(g, QFPS+A.QF_PITCH) == pytest.approx(-.4)
    assert writer.pitch_state['mode'] == 'player'


def test_clamps_accumulator_and_derived_pitch_to_both_native_limit_branches():
    g = normal(source=.1, offset=.1, limits=(.8, -.7, .6, -.5))
    writer = A.aim_writer(Session(g))
    assert writer(A.aim_state(g, BASE, PLAYER), -1., None)
    assert number(g, PLAYER+A.P_PITCH_INPUT) == pytest.approx(.5)
    native_frame(g, .1)
    assert number(g, QFPS+A.QF_PITCH) == pytest.approx(-.6)
    assert writer(A.aim_state(g, BASE, PLAYER), 1., None)
    assert number(g, PLAYER+A.P_PITCH_INPUT) == pytest.approx(-.5)
    native_frame(g, .1)
    assert number(g, QFPS+A.QF_PITCH) == pytest.approx(.4)


@pytest.mark.parametrize('changed', ['pad_alternate', 'config_alternate', 'camera_owner', 'params',
                                    'nan_input', 'nan_limits', 'inverted_limits', 'disjoint_limits',
                                    'outside_input', 'short_input', 'short_mode', 'native_reset'])
def test_unproved_or_invalid_native_source_refuses_without_camera_fallback(changed):
    g = normal()
    if changed == 'pad_alternate': g.put(PAD+0x8D0C, b'\x01')
    elif changed == 'config_alternate': g.put(CONFIG+0xA74, b'\x01')
    elif changed == 'camera_owner': g.q(QFPS+0x130, PLAYER+0x100000)
    elif changed == 'params': g.q(BASE+A.S_AIM_PARAMS, 0)
    elif changed == 'nan_input': floating(g, PLAYER+A.P_PITCH_INPUT, math.nan)
    elif changed == 'nan_limits': floating(g, PARAMS+0x440, math.nan)
    elif changed == 'inverted_limits': g.put(PARAMS+0x440, struct.pack('<2f', -.5, .5))
    elif changed == 'disjoint_limits': g.put(PARAMS+0x440, struct.pack('<4f', -.2, -.8, .8, .2))
    elif changed == 'outside_input': floating(g, PLAYER+A.P_PITCH_INPUT, 1.1)
    elif changed == 'native_reset': g.put(QFPS+0x195, b'\0'); g.put(QFPS+0x197, b'\x01')
    else:
        rd = g.rd
        address = PLAYER+A.P_PITCH_DERIVED if changed == 'short_input' else QFPS+0x194
        g.rd = lambda a, n: b'\0' if a == address else rd(a, n)
    assert not A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), -.4, .7)
    assert g.writes == []


@pytest.mark.parametrize('changed', ['input', 'alternate', 'owner', 'generation', 'limits', 'slow'])
def test_source_change_during_preflight_does_not_write_stale_pitch(monkeypatch, changed):
    g = normal(); state = A.aim_state(g, BASE, PLAYER)
    rd, done = g.rd, [False]
    def racing(a, n):
        value = rd(a, n)
        if a == PARAMS+0x440 and not done[0]:
            done[0] = True
            if changed == 'input': floating(g, PLAYER+A.P_PITCH_INPUT, .2)
            elif changed == 'alternate': g.put(PAD+0x8D0C, b'\x01')
            elif changed == 'owner': g.q(QFPS+0x130, PLAYER+0x100000)
            elif changed == 'generation': g.q(PLAYER+0x1A00, 18)
            elif changed == 'limits': floating(g, PARAMS+0x440, .5)
            else: state['sampled_at'] -= 1.
        return value
    g.rd = racing
    assert not A.aim_writer(Session(g))(state, -.4, .7)
    assert g.writes == []


@pytest.mark.parametrize('changed', ['input', 'alternate', 'generation'])
def test_changed_write_readback_never_reports_pitch_or_heading_success(changed):
    g = normal(); write = g.write_memory
    def racing(a, data):
        write(a, data)
        if changed == 'input': floating(g, a, .8)
        elif changed == 'alternate': g.put(PAD+0x8D0C, b'\x01')
        else: g.q(PLAYER+0x1A00, 18)
    g.write_memory = racing
    assert not A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), -.4, .7)
    assert [a for a, _ in g.writes] == [PLAYER+A.P_PITCH_INPUT]


def test_lost_native_accumulator_write_is_not_a_camera_success():
    g = normal(); g.sticky = False
    assert not A.aim_writer(Session(g))(A.aim_state(g, BASE, PLAYER), -.4, None)
    assert [a for a, _ in g.writes] == [PLAYER+A.P_PITCH_INPUT]


@pytest.mark.parametrize('flag', [0x194, 0x196])
def test_free_camera_flag_transition_invalidates_the_preflight(flag):
    g = guest(); state = A.aim_state(g, BASE, PLAYER)
    rd, done = g.rd, [False]
    def racing(a, n):
        value = rd(a, n)
        if a == QFPS+0x194 and not done[0]:
            done[0] = True
            g.put(QFPS+flag, b'\x01')
        return value
    g.rd = racing
    assert not A.aim_writer(Session(g))(state, -.4, None)
    assert not g.writes


def test_slow_postwrite_validation_cannot_authorize_fire_from_aged_camera(monkeypatch):
    g = normal(); clock = [1.]
    monkeypatch.setattr(A.time, 'monotonic', lambda: clock[0])
    state = A.aim_state(g, BASE, PLAYER); write = g.write_memory
    def slow(a, data):
        write(a, data)
        clock[0] += A.MAX_SAMPLE_AGE+.001
    g.write_memory = slow
    writer = A.aim_writer(Session(g))
    assert not writer(state, -.4, None)
    assert writer.pitch_state['writer_ms'] >= 150


def test_pinned_native_camera_counterwriter_consumes_the_production_source_write():
    """Optional asset proof runs on Spark; native game bytes are never vendored."""
    path = os.environ.get('RE5_MAIN_ELF')
    if not path:
        pytest.skip('pinned RE5 ELF stays on Spark')
    data = Path(path).read_bytes()
    assert hashlib.sha256(data).hexdigest() == '674c88288eda98b8974e4185853d0b7c2f3fe6b623c823124326d14834856f5c'
    U = pytest.importorskip('unicorn')
    from unicorn.arm64_const import (UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
        UC_ARM64_REG_X22, UC_ARM64_REG_X24, UC_ARM64_REG_X26, UC_ARM64_REG_X8,
        UC_ARM64_REG_SP, UC_ARM64_REG_S0, UC_ARM64_REG_S1, UC_ARM64_REG_S15, UC_ARM64_REG_S17)
    uc = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
    uc.mem_map(0, 0x3000000); uc.mem_map(0x5000000, 0x100000)
    ph = struct.unpack_from('<Q', data, 32)[0]; size, n = struct.unpack_from('<HH', data, 54)
    for k in range(n):
        typ, _, off, va, _, length, _, _ = struct.unpack_from('<II6Q', data, ph+k*size)
        if typ == 1: uc.mem_write(va, data[off:off+length])
    class Memory:
        def __init__(self): self.adapter = self
        def rd(self, a, n): return bytes(uc.mem_read(a, n))
        read_memory = rd
        def write_memory(self, a, data): uc.mem_write(a, data)
        put = write_memory
        def q(self, a, value): self.put(a, struct.pack('<Q', value))
    g = Memory()
    player, ctrl, pad, main, config, params, action, su, stack = (
        0x5000000, 0x5010000, 0x5020000, 0x5040000, 0x50A0000,
        0x50B0000, 0x50C0000, 0x50D0000, 0x50F0000)
    camera = ctrl+A.CTRL_QFPS
    g.q(A.S_UNIT, su); g.q(su+A.UNIT_LINES+A.LINE_STRIDE*A.CAM_LINE, ctrl)
    g.q(ctrl, A.CTRL_VT); g.q(ctrl+A.CTRL_ACTIVE, camera); g.q(ctrl+A.CTRL_PLAYER, player)
    g.q(camera, A.QFPS_VT); g.q(camera+0x130, player); g.q(player+0x1A00, 17)
    g.put(player+A.P_ROT, struct.pack('<4f', 0., 0., 0., 1.)); g.put(camera+0x195, b'\x01')
    g.q(A.S_MAIN, main); g.q(A.S_PAD, pad); g.q(A.S_AIM_PARAMS, params)
    g.q(0x1CD2C08, A.S_PAD); g.q(0x1CD2BE0, A.S_MAIN); g.q(main+0x584E0, config)
    g.put(params+0x440, struct.pack('<4f', 1., -1., 1., -1.))
    floating(g, player+A.P_PITCH_DERIVED, .0011226)
    floating(g, player+A.P_PITCH_INPUT, .0011226-.01)
    floating(g, camera+A.QF_PITCH, -.4)
    def camera_frame():
        uc.reg_write(UC_ARM64_REG_X19, camera); uc.reg_write(UC_ARM64_REG_X22, player)
        uc.emu_start(0x249518, 0x24961C, count=100)
    camera_frame()
    assert number(g, camera+A.QF_PITCH) == pytest.approx(-.0011226)
    assert A.aim_writer(g)(A.aim_state(g, 0, player), -.4, None)
    assert number(g, player+A.P_PITCH_INPUT) == pytest.approx(.39)
    floating(g, action+0x800, .01); g.q(stack+0x40, action)
    uc.reg_write(UC_ARM64_REG_X19, player); uc.reg_write(UC_ARM64_REG_X8, params)
    uc.reg_write(UC_ARM64_REG_SP, stack)
    uc.emu_start(0x79CB80, 0x79BA8C, count=100)
    camera_frame()
    assert number(g, camera+A.QF_PITCH) == pytest.approx(-.4)
    g.put(pad+0x8D0C, b'\x01'); floating(g, player+0x3F60, .23)
    camera_frame()
    assert number(g, camera+A.QF_PITCH) == pytest.approx(-.23)
    # The alternate angle is copied from cPlayerCtrl+350's persistent +4C8.
    # Its nearby player+3F5C is animated output and must never be treated as
    # the persistent input. Exercise production ownership and actual native
    # integration, clamp, action-output copy, then camera consumption.
    input_ctrl = 0x50E0000
    g.q(player+A.P_INPUT_CTRL, input_ctrl); g.q(input_ctrl, A.INPUT_CTRL_VT)
    g.q(input_ctrl+0x48, player); g.q(input_ctrl+A.C_AIM, A.INPUT_AIM_VT)
    floating(g, input_ctrl+A.C_PITCH_INPUT, .23)
    floating(g, input_ctrl+0x7B8, .3); floating(g, input_ctrl+0x800, .07)
    floating(g, params+0x29C, .997)
    floating(g, params+0x2D0, 1.); floating(g, params+0x2D4, 1.)
    g.q(0x1CF08A0, action); floating(g, action+0x34, 1.)
    floating(g, player+0x1A08, 1.)
    floating(g, stack+0x18, 1.5); floating(g, stack+8, 1.)
    g.put(stack+0x60, b'\x04')  # precomputed no per-player axis-inversion branch
    def reg_float(reg, value):
        uc.reg_write(reg, struct.unpack('<I', struct.pack('<f', value))[0])
    def alternate_frame():
        uc.reg_write(UC_ARM64_REG_X19, input_ctrl+A.C_AIM)
        uc.reg_write(UC_ARM64_REG_X20, player); uc.reg_write(UC_ARM64_REG_X21, 0)
        uc.reg_write(UC_ARM64_REG_X22, 0); uc.reg_write(UC_ARM64_REG_X8, params)
        uc.reg_write(UC_ARM64_REG_X24, 0x1CF0000); uc.reg_write(UC_ARM64_REG_X26, stack+0x60)
        uc.reg_write(UC_ARM64_REG_SP, stack)
        for reg, value in ((UC_ARM64_REG_S0, 0.), (UC_ARM64_REG_S1, 0.),
                           (UC_ARM64_REG_S15, 1.), (UC_ARM64_REG_S17, 2.)):
            reg_float(reg, value)
        uc.emu_start(0x7D9830, 0x7D99D4, count=200)
        uc.reg_write(UC_ARM64_REG_X19, player)
        uc.emu_start(0x7BD0BC, 0x7BD0FC, count=50)
        camera_frame()
    for pitch in (-.5, .5, -1.):
        expected = max(-.997, min(.997, -pitch))
        assert A.aim_writer(g)(A.aim_state(g, 0, player), pitch, None)
        for _ in range(3):
            alternate_frame()
            assert number(g, input_ctrl+A.C_PITCH_INPUT) == pytest.approx(expected)
            assert number(g, player+A.P_ALT_PITCH) == pytest.approx(expected)
            assert number(g, camera+A.QF_PITCH) == pytest.approx(-expected)
            assert number(g, input_ctrl+0x800) == pytest.approx(.07)
