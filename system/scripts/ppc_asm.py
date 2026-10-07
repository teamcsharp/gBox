import struct
from keystone import Ks, KS_ARCH_PPC, KS_MODE_PPC32, KS_MODE_BIG_ENDIAN
KS = Ks(KS_ARCH_PPC, KS_MODE_PPC32 | KS_MODE_BIG_ENDIAN)


def asm(src: str, addr: int) -> bytes:
    enc, _ = KS.asm(src, addr)
    return bytes(enc)


def b(src, dst, link=False):
    return struct.pack(">I", (18 << 26) | ((dst - src) & 0x3FFFFFC) | (1 if link else 0))


def logger(stub, fn, first_word, log, regs=("r6", "r3", "r7")):
    """Entry logger: ring of 31 x 16-byte records {regs[0], lr, regs[1], regs[2]} at log+16.."""
    hi, lo = log >> 16, log & 0xFFFF
    src = f"""
    lis 11, {hi:#x}
    ori 11, 11, {lo:#x}
    lwz 12, 0(11)
    addi 12, 12, 1
    cmpwi 12, 31
    ble lbl_ok
    li 12, 1
lbl_ok:
    stw 12, 0(11)
    slwi 12, 12, 4
    add 12, 12, 11
    stw {regs[0][1:]}, 0(12)
    mflr 0
    stw 0, 4(12)
    stw {regs[1][1:]}, 8(12)
    stw {regs[2][1:]}, 12(12)
    """
    code = asm(src, stub)
    code += struct.pack(">I", first_word)
    code += b(stub + len(code), fn + 4)
    return code


def ret_logger(stub, fn, first_word, log):
    """Wrap fn: call the original through a trampoline, log {r6 class, r3 attacker, result, lr} in a ring at log."""
    hi, lo = log >> 16, log & 0xFFFF
    tramp = stub + 0x80
    src = f"""
    stwu 1, -0x20(1)
    mflr 0
    stw 0, 0x24(1)
    stw 31, 0x1c(1)
    stw 30, 0x18(1)
    stw 29, 0x14(1)
    mr 31, 6
    mr 30, 3
    mr 29, 0
    """
    code = asm(src, stub)
    code += b(stub + len(code), tramp, link=True)
    src2 = f"""
    lis 11, {hi:#x}
    ori 11, 11, {lo:#x}
    lwz 12, 0(11)
    addi 12, 12, 1
    cmpwi 12, 31
    ble lbl_ok
    li 12, 1
lbl_ok:
    stw 12, 0(11)
    slwi 12, 12, 4
    add 12, 12, 11
    stw 31, 0(12)
    stw 30, 4(12)
    stw 3, 8(12)
    stw 29, 12(12)
    lwz 29, 0x14(1)
    lwz 30, 0x18(1)
    lwz 31, 0x1c(1)
    lwz 0, 0x24(1)
    mtlr 0
    addi 1, 1, 0x20
    blr
    """
    code += asm(src2, stub + len(code))
    assert len(code) <= 0x80, len(code)
    code = code.ljust(0x80, b"\0")
    code += struct.pack(">I", first_word) + b(tramp + 4, fn + 4)
    return code
