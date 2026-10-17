"""gbox.zn_tps_boot: the R3000 interpreter, the CAT702 model and the BIOS guard. Synthetic only (the owned-ROM decode
is exercised by tests/test_doapp_inventory.py when GBOX_DOAPP_ROMS points at the zips)."""

import pytest

from gbox import zn_tps_boot as Z


def _cpu(code_words, ram_at=0x1000):
    mem = Z.ZNMemory(b"\0" * 16, b"", b"\0" * 8, b"\0" * 8)
    for i, w in enumerate(code_words):
        mem.w32(0x80000000 + ram_at + 4 * i, w)
    return mem, Z.R3000(mem)


def test_interpreter_loop_branch_delay_and_return():
    # v0 = 0; for (a0 = 5; a0; a0--) v0 += a0;  -> 15, with the add in a branch delay slot
    code = [
        0x00001021,  # move v0, zero
        0x00441021,  # loop: addu v0, v0, a0
        0x2484FFFF,  # addiu a0, a0, -1
        0x1480FFFD,  # bnez a0, loop
        0x00000000,  # nop
        0x03E00008,  # jr ra
        0x00000000,
    ]
    mem, cpu = _cpu(code)
    assert cpu.call(0x80001000, (5,)) == 15


def test_interpreter_loads_stores_and_signed_ops():
    code = [
        0x3C088000,  # lui t0, 0x8000
        0x35082000,  # ori t0, t0, 0x2000
        0x2409FF80,  # addiu t1, zero, -128
        0xA1090000,  # sb t1, 0(t0)
        0x81020000,  # lb v0, 0(t0)        -> sign-extended
        0x91030000,  # lbu v1, 0(t0)
        0x00431021,  # addu v0, v0, v1     -> -128 + 128 = 0
        0x03E00008,
        0x24420007,  # addiu v0, v0, 7 (delay slot)
    ]
    mem, cpu = _cpu(code)
    assert cpu.call(0x80001000) == 7
    assert mem.r8(0x80002000) == 0x80


def test_interpreter_refuses_unknown_opcode_and_runaway():
    mem, cpu = _cpu([0xFC000000])          # opcode 0x3f
    with pytest.raises(Z.DecodeError):
        cpu.call(0x80001000)
    mem, cpu = _cpu([0x1000FFFF, 0])       # b . (forever)
    with pytest.raises(Z.DecodeError):
        cpu.call(0x80001000, limit=1000)


def _cat702_bitlevel(transform, data):
    """MAME cat702_device clock-level behaviour, written independently of Cat702.xfer."""
    def coef(sel, bit):
        if not sel:
            return transform[bit]
        r = coef((sel - 1) & 7, (bit - 1) & 7)
        r = ((r << 1) | (((r >> 7) & 1) ^ ((r >> 6) & 1))) & 0xFF
        return r ^ coef(sel, 0) if bit == 7 else r

    def apply(state, box):
        out = 0
        for i in range(8):
            if state >> i & 1:
                out ^= box[i]
        return out
    state, bit, outs = 0xFC, 0, []
    for byte in data:
        o = 0
        for k in range(8):
            if bit == 0:                    # falling clock at bit 0: initial sbox
                state = apply(state, Z.CAT702_INITIAL)
            o |= (state >> bit & 1) << k
            if not (byte >> k & 1):         # rising clock with data 0
                state = apply(state, [coef(bit, b) for b in range(8)])
            bit = (bit + 1) & 7
        outs.append(o)
    return outs


@pytest.mark.parametrize("transform", [bytes(range(8)), bytes([0x5A, 0x11, 0xC3, 0x07, 0xF0, 0x2E, 0x99, 0x40])])
def test_cat702_byte_transfer_matches_clock_level_model(transform):
    chip = Z.Cat702(transform)
    chip.set_select(0)
    data = [0x00, 0xFF, 0x12, 0xA5, 0x3C, 0x00, 0x7E, 0x81]
    assert [chip.xfer(b) for b in data] == _cat702_bitlevel(transform, data)
    chip.set_select(1)
    assert chip.xfer(0x00) == 0xFF        # deselected chip drives the line high


def test_sio_reads_and_selects_through_znsecsel():
    mem = Z.ZNMemory(b"\0" * 16, b"", bytes(range(8)), bytes(range(8, 16)))
    mem.w8(0x1FA10300, 0x88)               # bit2 low: CPU-board chip selected, ROM-board chip not
    assert mem.r16(0x1F801044) & 2 == 0    # nothing received yet
    mem.w8(0x1F801040, 0x5A)
    assert mem.r16(0x1F801044) & 2
    ref = Z.Cat702(bytes(range(8)))
    ref.set_select(0)
    assert mem.r8(0x1F801040) == ref.xfer(0x5A)


def test_bank_window_and_bios_guard():
    banked = bytes(range(256)) * 0x10000 * 2
    mem = Z.ZNMemory(b"\0" * 16, banked, b"\0" * 8, b"\0" * 8)
    mem.w8(0x1FB00006, 1)
    assert mem.r8(0x1F000003) == banked[0x800003]
    with pytest.raises(Z.DecodeError):
        Z.decode_program(b"not the bios", banked, b"\0" * 8, b"\0" * 8)
