"""The RE4 dispatcher image (E0(c)): the pinned bytes, their tail call, and their behaviour under unicorn.

The dispatcher is the only guest-side code the RE4 harness installs. It is reached through data (the player
object's cloned vtable at slot +0xA0), reads the mailbox pointer from the clone, performs one native call per
request and tail-calls the game's own transform every entry. These tests decode the pinned image, reproduce it from
`dispatch.S` (keystone), and execute it on a synthetic memory map (unicorn) - no game.
"""
import gc
import struct

import pytest

from gbox.mercs.native.re4_82c2a04a import build_dispatch as B
from gbox.mercs.native.re4_82c2a04a import code as C

_ENGINES = []


@pytest.fixture(autouse=True)
def _dispose_engines():
    """Free every unicorn engine inside the test, not at interpreter shutdown (a Windows exit crash otherwise)."""
    yield
    _ENGINES.clear()
    gc.collect()

# hand-encoded stubs for the unicorn map (checked by test_the_fake_stubs_are_what_they_claim)
ORIGINAL_STUB = struct.pack("<3I", 0xF9001000, 0xD2800AA0, 0xD65F03C0)   # str x0,[x0,#0x20]; mov x0,#0x55; ret
SUM_STUB = struct.pack("<3I", 0x8B010009, 0x8B020120, 0xD65F03C0)        # x0 = x0 + x1 + x2; ret
RET_STUB = struct.pack("<I", 0xD65F03C0)

UNIT, CLONE, MAILBOX, STACK, RETURN = 0x800000, 0x800100, 0x900000, 0x700000, 0x500000
MAPS = (0x310000, 0x500000, 0x655000, 0x700000, 0x800000, 0x900000, 0xA00000)


def test_the_fake_stubs_are_what_they_claim():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    assert [i.mnemonic for i in md.disasm(ORIGINAL_STUB, C.ORIGINAL_TICK)] == ["str", "mov", "ret"]
    assert [i.mnemonic for i in md.disasm(SUM_STUB, 0xA00000)] == ["add", "add", "ret"]


def test_the_image_fits_the_cave_and_starts_on_a_fresh_line():
    size = C.DISPATCH[2]
    assert len(C.IMAGES["dispatch"]) == size <= C.CAVE_SIZE
    assert C.CAVE_AT % 64 == 0
    assert C.CAVE_AT + size <= 0x656000                      # the RX page that ends the vetted tail padding
    # the clone vtable lives in the same cave: 64-byte aligned, clear of the dispatcher, inside the page
    assert C.CLONE_AT % 64 == 0 and C.CLONE_AT >= C.CAVE_AT + size
    assert C.CLONE_AT + C.CLONE_SIZE <= C.CAVE_END == 0x656000


def test_the_tail_call_lands_on_the_original_tick():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    md.detail = True
    insns = list(md.disasm(C.IMAGES["dispatch"], C.CAVE_AT))
    assert len(insns) * 4 == len(C.IMAGES["dispatch"])       # every word decodes
    assert insns[-1].mnemonic == "ret" and insns[-2].mnemonic == "br"
    tail = None
    for index, ins in enumerate(insns):
        if ins.mnemonic == "adrp" and "x9" in ins.op_str:
            nxt = insns[index + 1]
            if nxt.mnemonic == "add" and nxt.op_str.startswith("x9, x9, #"):
                tail = ins.op_str.rsplit("#", 1)[1] + " + " + nxt.op_str.rsplit("#", 1)[1]
    assert tail is not None
    page = int(tail.split(" + ")[0], 0)
    off = int(tail.split(" + ")[1], 0)
    assert page + off == C.ORIGINAL_TICK
    assert C.ORIGINAL_TICK == 0x312600


def test_the_pinned_image_reproduces_from_source():
    pytest.importorskip("keystone")
    report = B.check()
    assert report["ok"], report["problems"]
    assert report["size"] == C.DISPATCH[2] and report["sha256"] == C.DISPATCH[3]
    assert report["tail_call"] == C.ORIGINAL_TICK


# ---- the dispatcher on a synthetic memory map -------------------------------------------------------------------------

def machine(mailbox=True):
    pytest.importorskip("unicorn")
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_LR, UC_ARM64_REG_SP
    mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for base in MAPS:
        mu.mem_map(base, 0x10000)
    mu.mem_write(C.CAVE_AT, C.IMAGES["dispatch"])
    mu.mem_write(C.ORIGINAL_TICK, ORIGINAL_STUB)
    mu.mem_write(0xA00000, SUM_STUB)
    mu.mem_write(RETURN, RET_STUB)
    mu.mem_write(UNIT, struct.pack("<Q", CLONE))
    mu.mem_write(CLONE + C.CLONE_MAILBOX_OFF, struct.pack("<Q", MAILBOX if mailbox else 0))
    mu.reg_write(UC_ARM64_REG_SP, STACK + 0x8000)
    mu.reg_write(UC_ARM64_REG_LR, RETURN)
    _ENGINES.append(mu)
    return mu


def enter(mu):
    from unicorn import UC_ARCH_ARM64
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_X0
    mu.reg_write(UC_ARM64_REG_X0, UNIT)
    mu.emu_start(C.CAVE_AT, RETURN)


def mailbox_words(mu):
    return {name: struct.unpack_from("<Q", mu.mem_read(MAILBOX + off, 8), 0)[0] for name, off in C.MAILBOX.items()}


def publish(mu, target, args=()):
    mu.mem_write(MAILBOX, struct.pack("<I", C.STATE["requested"]) + b"\0\0\0\0")
    mu.mem_write(MAILBOX + C.MAILBOX["target"], struct.pack("<Q", target))
    padded = tuple(args) + (0,) * (7 - len(args))
    mu.mem_write(MAILBOX + C.MAILBOX["args"], struct.pack("<7Q", *padded))


def test_an_idle_entry_ticks_and_runs_the_original():
    mu = machine()
    enter(mu)
    words = mailbox_words(mu)
    assert words["state"] == C.STATE["idle"] and words["ticks"] == 1
    assert struct.unpack("<Q", mu.mem_read(UNIT + 0x20, 8))[0] == UNIT       # the original got the unit in x0


def test_a_request_calls_the_target_with_the_arguments_and_stores_the_result():
    mu = machine()
    publish(mu, 0xA00000, (7, 8, 9))
    enter(mu)
    words = mailbox_words(mu)
    assert words["state"] == C.STATE["done"] and words["result"] == 24 and words["ticks"] == 1
    assert struct.unpack("<Q", mu.mem_read(UNIT + 0x20, 8))[0] == UNIT       # the original still ran


def test_a_request_without_a_target_completes_without_calling():
    mu = machine()
    mu.mem_write(MAILBOX, struct.pack("<I", C.STATE["requested"]) + b"\0\0\0\0")
    enter(mu)
    words = mailbox_words(mu)
    assert words["state"] == C.STATE["done"] and words["result"] == 0


def test_a_null_mailbox_still_runs_the_original():
    mu = machine(mailbox=False)
    enter(mu)
    assert struct.unpack("<Q", mu.mem_read(UNIT + 0x20, 8))[0] == UNIT


def test_the_callee_saved_registers_survive():
    from unicorn.arm64_const import (UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21, UC_ARM64_REG_X22,
                                     UC_ARM64_REG_X28)
    mu = machine()
    for reg, value in ((UC_ARM64_REG_X19, 0x1111), (UC_ARM64_REG_X20, 0x2222),
                       (UC_ARM64_REG_X21, 0x3333), (UC_ARM64_REG_X22, 0x4444), (UC_ARM64_REG_X28, 0x5555)):
        mu.reg_write(reg, value)
    publish(mu, 0xA00000, (1, 2, 3))
    enter(mu)
    assert [mu.reg_read(r) for r in (UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
                                     UC_ARM64_REG_X22, UC_ARM64_REG_X28)] == [0x1111, 0x2222, 0x3333, 0x4444, 0x5555]


def test_two_requests_run_in_sequence():
    mu = machine()
    publish(mu, 0xA00000, (1, 2, 3))
    enter(mu)
    assert mailbox_words(mu)["result"] == 6
    publish(mu, 0xA00000, (4, 5, 6))
    enter(mu)
    words = mailbox_words(mu)
    assert words["result"] == 15 and words["state"] == C.STATE["done"] and words["ticks"] == 2


def test_the_self_test_target_is_a_ret_inside_the_cave():
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    assert C.SELFTEST_AT == C.CAVE_AT + 132
    assert C.SELFTEST_AT + 4 <= C.CAVE_AT + C.DISPATCH[2]
    words = list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(C.IMAGES["dispatch"][132:136], C.SELFTEST_AT))
    assert len(words) == 1 and words[0].mnemonic == "ret"


def test_a_selftest_call_returns_zero_through_the_mailbox():
    mu = machine()
    publish(mu, C.SELFTEST_AT)                                  # the dispatcher's own ret, no game code
    enter(mu)
    words = mailbox_words(mu)
    assert words["state"] == C.STATE["done"] and words["result"] == 0
