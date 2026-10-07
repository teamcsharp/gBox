"""Assemble the RE4 GC cave routines for explosive_melee / super_melee / auto_spin (keystone), print hex."""
import struct
import sys

sys.path.insert(0, "//10.89.1.246/ehm_eckx/gBox/system")
from gbox import re_games as R  # noqa: E402
from ppc_asm import asm, b  # noqa: E402  (pip install keystone-engine; run from scripts/)

VB = 0x80001F00
OWNED_GRENADE, OWNED_FLASH, OWNED_BLAST = 0x80001800, 0x800018A0, 0x80001970
MELEE_WRAP, LAUNCH_START, LAUNCH_HOOK, SPIN_HOOK = 0x80001990, 0x80001A40, 0x80001BE0, 0x80001D00
SLOTS, SLOT_SZ, NSLOT = VB + 0x40, 0x1C, 4
F_IMPACT, GRENADE_AT = 0x80104604, R.GRENADE_AT


def reloc(code, src, dst):
    out = bytearray()
    for i in range(0, len(code), 4):
        w = struct.unpack(">I", code[i:i + 4])[0]
        if w >> 26 == 18:
            off = w & 0x3FFFFFC
            if off & 0x2000000:
                off -= 0x4000000
            tgt = src + i + off
            w = (18 << 26) | ((tgt - (dst + i)) & 0x3FFFFFC) | (w & 3)
        out += struct.pack(">I", w)
    return out


def owned_grenade():
    c = reloc(R.GRENADE_AT_CODE, R.GRENADE_AT, OWNED_GRENADE)
    assert c[0x60:0x78].hex() == "3d20801ec0290b7c386000007fc4f3787fc5f37838c00013", c[0x60:0x78].hex()
    c[0x60:0x64] = asm("lis 9, 0x8000", OWNED_GRENADE + 0x60)
    c[0x64:0x68] = asm(f"lfs 1, {VB + 8 - 0x80000000:#x}(9)", OWNED_GRENADE + 0x64)
    c[0x68:0x6C] = asm("lwz 3, -0x673c(13)", OWNED_GRENADE + 0x68)
    c[0x74:0x78] = asm(f"lbz 6, {VB + 5 - 0x80000000:#x}(9)", OWNED_GRENADE + 0x74)
    return bytes(c)


def owned_flash():
    c = reloc(R.FLASH_AT_CODE, R.FLASH_AT, OWNED_FLASH)
    assert c[0x98:0x9C].hex() == "38600000"
    c[0x98:0x9C] = asm("lwz 3, -0x673c(13)", OWNED_FLASH + 0x98)
    return bytes(c)


def owned_blast():
    c = asm(f"""
    lis 9, 0x8000
    lbz 0, {VB + 4 - 0x80000000:#x}(9)
    cmpwi 0, 1
    """, OWNED_BLAST)
    a = OWNED_BLAST + len(c)
    c += struct.pack(">I", 0x40820008)                     # bne +8
    c += b(a + 4, OWNED_FLASH)                              # b OWNED_FLASH
    c += b(a + 8, OWNED_GRENADE)                            # b OWNED_GRENADE
    return c


def melee_wrap():
    v = VB - 0x80000000
    p = []
    def emit(src):
        p.append(("asm", src))
    def call(t):
        p.append(("bl", t))
    emit("""stwu 1, -0x20(1)
    mflr 0
    stw 0, 0x24(1)
    stmw 30, 0x18(1)
    mr 31, 3
    mr 30, 6""")
    call(F_IMPACT)
    emit(f"""cmplwi 30, 0x1f
    bgt lbl_done
    li 10, 1
    slw 10, 10, 30
    lis 9, 0x8000
    lwz 0, 0x2f34(9)
    and. 0, 0, 10
    beq lbl_melee
    mr 3, 31""")
    call(GRENADE_AT)
    emit(f"""b lbl_done
lbl_melee:
    lwz 0, {v:#x}(9)
    and. 0, 0, 10
    beq lbl_done
    lbz 0, {v + 6:#x}(9)
    cmpwi 0, 0
    beq lbl_nolaunch
    mr 3, 31""")
    call(LAUNCH_START)
    emit(f"""lis 9, 0x8000
    lbz 0, {v + 7:#x}(9)
    cmpwi 0, 0
    bne lbl_done
lbl_nolaunch:
    lis 9, 0x8000
    lbz 0, {v + 4:#x}(9)
    cmpwi 0, 0xff
    beq lbl_done
    mr 3, 31""")
    call(OWNED_BLAST)
    emit("""lbl_done:
    lmw 30, 0x18(1)
    lwz 0, 0x24(1)
    mtlr 0
    addi 1, 1, 0x20
    blr""")
    return assemble(p, MELEE_WRAP)


def assemble(parts, base):
    """Concatenate asm chunks and bl's; labels are resolved per whole program by assembling with placeholder bl's."""
    # assemble everything in one keystone pass: replace bl with 'bl <abs>' which keystone resolves relative to base
    src = []
    for kind, x in parts:
        src.append(x if kind == "asm" else f"bl {x:#x}")
    code = asm("\n".join(src), base)
    return code


def launch_start():
    v = VB - 0x80000000
    s = f"""
    stwu 1, -0x40(1)
    mflr 0
    stw 0, 0x44(1)
    stmw 25, 0x20(1)
    mr 31, 3
    lis 9, 0x8028
    lwz 30, -0x20e0(9)
    lwz 29, -0x20dc(9)
    lwz 28, -0x20d8(9)
    li 27, 0
    lis 0, 0x4874
    ori 0, 0, 0x2400
    stw 0, 0x10(1)
    lfs 13, 0x10(1)
    li 26, 1
lbl_loop:
    cmpw 26, 29
    bge lbl_endloop
    mullw 25, 26, 28
    add 25, 25, 30
    lwz 0, 0(25)
    andi. 0, 0, 0x601
    beq lbl_next
    lbz 0, 0x398(25)
    cmpwi 0, 0xff
    beq lbl_next
    lfs 0, 0x94(25)
    lfs 1, 0(31)
    fsubs 0, 0, 1
    fmuls 2, 0, 0
    lfs 0, 0x98(25)
    lfs 1, 4(31)
    fsubs 0, 0, 1
    fmadds 2, 0, 0, 2
    lfs 0, 0x9c(25)
    lfs 1, 8(31)
    fsubs 0, 0, 1
    fmadds 2, 0, 0, 2
    fcmpu 0, 2, 13
    bge lbl_next
    fmr 13, 2
    mr 27, 25
lbl_next:
    addi 26, 26, 1
    b lbl_loop
lbl_endloop:
    cmpwi 27, 0
    beq lbl_out
    lis 9, 0x8000
    ori 9, 9, {SLOTS & 0xffff:#x}
    li 26, {NSLOT}
    li 25, 0
lbl_sloop:
    lwz 0, 4(9)
    cmpwi 0, 0
    beq lbl_free
    lwz 0, 0(9)
    cmpw 0, 27
    beq lbl_out
    b lbl_snext
lbl_free:
    cmpwi 25, 0
    bne lbl_snext
    mr 25, 9
lbl_snext:
    addi 9, 9, {SLOT_SZ}
    addic. 26, 26, -1
    bne lbl_sloop
    cmpwi 25, 0
    beq lbl_out
    lwz 9, -0x673c(13)
    cmpwi 9, 0
    beq lbl_out
    stw 27, 0(25)
    lfs 0, 0x94(27)
    lfs 1, 0x94(9)
    fsubs 3, 0, 1
    lfs 0, 0x9c(27)
    lfs 1, 0x9c(9)
    fsubs 4, 0, 1
    fmuls 5, 3, 3
    fmadds 5, 4, 4, 5
    lis 9, 0x8000
    lfs 0, {v + 0x28:#x}(9)
    fcmpu 0, 5, 0
    bge lbl_dirok
    lfs 3, {v + 0x2c:#x}(9)
    lfs 4, {v + 0x2c:#x}(9)
    fmr 6, 3
    b lbl_dirdone
lbl_dirok:
    frsqrte 6, 5
lbl_dirdone:
    fmuls 3, 3, 6
    fmuls 4, 4, 6
    lfs 0, {v + 0x10:#x}(9)
    fmuls 3, 3, 0
    fmuls 4, 4, 0
    stfs 3, 8(25)
    lfs 0, {v + 0x0c:#x}(9)
    stfs 0, 12(25)
    stfs 4, 16(25)
    lfs 0, 0x98(27)
    stfs 0, 20(25)
    stfs 0, 24(25)
    lwz 0, {v + 0x30:#x}(9)
    stw 0, 4(25)
lbl_out:
    lmw 25, 0x20(1)
    lwz 0, 0x44(1)
    mtlr 0
    addi 1, 1, 0x40
    blr
    """
    return asm(s, LAUNCH_START)


def launch_hook():
    v = VB - 0x80000000
    s = f"""
    stwu 1, -0x30(1)
    mflr 0
    stw 0, 0x34(1)
    stmw 28, 0x20(1)
    lwz 9, -0x7500(13)
    lbz 0, 0x20(9)
    cmpwi 0, 3
    bne lbl_out
    lis 31, 0x8000
    ori 31, 31, {SLOTS & 0xffff:#x}
    li 30, {NSLOT}
lbl_loop:
    lwz 12, 4(31)
    cmpwi 12, 0
    beq lbl_next
    addi 12, 12, -1
    stw 12, 4(31)
    lwz 29, 0(31)
    lwz 0, 0(29)
    andi. 0, 0, 0x601
    beq lbl_release
    lfs 0, 20(31)
    lfs 1, 12(31)
    fadds 0, 0, 1
    stfs 0, 20(31)
    lis 9, 0x8000
    lfs 2, {v + 0x14:#x}(9)
    fsubs 1, 1, 2
    stfs 1, 12(31)
    lfs 3, 0x94(29)
    lfs 4, 8(31)
    fadds 3, 3, 4
    stfs 3, 0x94(29)
    lfs 3, 0x9c(29)
    lfs 4, 16(31)
    fadds 3, 3, 4
    stfs 3, 0x9c(29)
    lfs 5, 24(31)
    fcmpu 0, 0, 5
    bge lbl_fly
    stfs 5, 0x98(29)
    li 0, 0
    stw 0, 4(31)
    lbz 0, {v + 7:#x}(9)
    cmpwi 0, 0
    beq lbl_next
    addi 3, 29, 0x94
    bl {OWNED_BLAST:#x}
    b lbl_next
lbl_fly:
    stfs 0, 0x98(29)
    lwz 0, 4(31)
    cmpwi 0, 0
    bne lbl_next
    stfs 5, 0x98(29)
    b lbl_next
lbl_release:
    li 0, 0
    stw 0, 4(31)
lbl_next:
    addi 31, 31, {SLOT_SZ}
    addic. 30, 30, -1
    bne lbl_loop
lbl_out:
    lmw 28, 0x20(1)
    lwz 0, 0x34(1)
    mtlr 0
    addi 1, 1, 0x30
    blr
    """
    return asm(s, LAUNCH_HOOK)


def spin_hook():
    v = VB - 0x80000000
    s = f"""
    lis 9, 0x8000
    lbz 0, {v + 0x1c:#x}(9)
    cmpwi 0, 0
    beqlr
    lwz 10, -0x7500(13)
    lbz 11, 0x20(10)
    cmpwi 11, 3
    bnelr
    cmpwi 0, 2
    beq lbl_spin
    lis 11, 0x8028
    lhz 11, 0x7e9e(11)
    lhz 12, {v + 0x1e:#x}(9)
    and 11, 11, 12
    cmpw 11, 12
    bnelr
lbl_spin:
    lwz 10, -0x673c(13)
    cmpwi 10, 0
    beqlr
    lfs 0, 0xa4(10)
    lfs 1, {v + 0x18:#x}(9)
    fadds 0, 0, 1
    lfs 2, {v + 0x20:#x}(9)
    fcmpu 0, 0, 2
    ble lbl_st
    lfs 3, {v + 0x24:#x}(9)
    fsubs 0, 0, 3
lbl_st:
    stfs 0, 0xa4(10)
    blr
    """
    return asm(s, SPIN_HOOK)


if __name__ == "__main__":
    parts = {"OWNED_GRENADE": (OWNED_GRENADE, owned_grenade()), "OWNED_FLASH": (OWNED_FLASH, owned_flash()),
             "OWNED_BLAST": (OWNED_BLAST, owned_blast()), "MELEE_WRAP": (MELEE_WRAP, melee_wrap()),
             "LAUNCH_START": (LAUNCH_START, launch_start()), "LAUNCH_HOOK": (LAUNCH_HOOK, launch_hook()),
             "SPIN_HOOK": (SPIN_HOOK, spin_hook())}
    order = sorted(parts.values())
    for (a, c), (a2, _) in zip(order, order[1:]):
        assert a + len(c) <= a2, (hex(a), len(c), hex(a2))
    assert order[-1][0] + len(order[-1][1]) <= VB
    import json
    json.dump({k: [hex(a), c.hex()] for k, (a, c) in parts.items()}, open("gc_cave.json", "w"), indent=1)
    for k, (a, c) in parts.items():
        print(k, hex(a), len(c))
