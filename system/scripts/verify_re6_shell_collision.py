"""Execute two native RE6 functions in isolated emulation, using the owner's ELF.

Usage: python verify_re6_shell_collision.py /path/to/re6sw_main_061D2A06.elf
Requires Unicorn 2.1.4. No process attachment, game writes or proprietary bytes in
this script. Tests actual F45AB0 -> F45340 with zero velocity and unchanged position.
Game services are bounded stubs; this establishes impact dispatch, not live VFX.
"""
import hashlib
import struct
import sys
from pathlib import Path

import unicorn as U
from unicorn import arm64_const as A

ELF_SHA256 = "441516ee1a4f26720e92956ecdb6cedcf253022cad7cbae239ad7e8ba002dd78"


def execute(elf, base, forced):
    assert hashlib.sha256(elf).hexdigest() == ELF_SHA256, "wrong native build"
    # The pinned ELF's text load segment is main-relative and begins at file 0x10000.
    phoff = struct.unpack_from("<Q", elf, 0x20)[0]
    assert struct.unpack_from("<IIQQQQQQ", elf, phoff)[:4] == (1, 5, 0x10000, 0)
    u = U.Uc(U.UC_ARCH_ARM64, U.UC_MODE_ARM)
    u.mem_map(base, 0x3000000)
    unit, world, stack, player = (base + n for n in (0x4000000, 0x4100000, 0x4200000, 0x4300000))
    for at, size in ((unit, 0x10000), (world, 0x60000), (stack, 0x10000), (player, 0x10000)):
        u.mem_map(at, size)

    def put(at, fmt, *values):
        u.mem_write(at, struct.pack("<" + fmt, *values))

    def reg(i):
        return u.reg_read(getattr(A, "UC_ARM64_REG_X" + str(i)))

    vt, player_vt, player_dti = (base + n for n in (0x283A3E8, 0x2800000, 0x2801000))
    put(unit, "Q", vt)
    put(unit + 0xC, "I", 0x201)
    put(unit + 0x1300, "Q", player)
    put(unit + 0x3958, "I", 0x101)
    put(unit + 0x3954, "I", 4 if forced else 0)
    pos = struct.pack("<4f", 700., 100., 10., 0.)
    u.mem_write(unit + 0x60, pos)
    u.mem_write(unit + 0x3890, pos)
    put(unit + 0x38B0, "f", 3.0)
    put(base + 0x2A5F580, "Q", world)
    put(world + 0x583D8, "f", .016)
    put(player, "Q", player_vt)
    put(player_vt + 0x28, "Q", base + 0x1070)
    put(player_dti + 0x37, "B", 1)
    for slot, stub in ((0x1E8, 0x1000), (0x400, 0x1010), (0x3D8, 0x1020),
                       (0x410, 0x1030), (0x3E8, 0xF45340), (0x420, 0x1050),
                       (0x3E0, 0x1060), (0x3F8, 0x1080), (0x188, 0x1090)):
        put(vt + slot, "Q", base + stub)
    for start, end in ((0xF45AB0, 0xF466F8), (0xF45340, 0xF456D0)):
        u.mem_write(base + start, elf[0x10000 + start:0x10000 + end])
    calls, requests = [], []

    def hook(uc, at, _size, _data):
        off = at - base
        if off == 0xF45340:
            calls.append("native_impact")
            return  # Execute the real native impact routine too.
        if off not in (0x1000, 0x1010, 0x1020, 0x1030, 0x1050, 0x1060,
                       0x1070, 0x1080, 0x1090, 0xF43900):
            return
        result = 0
        if off == 0x1000:
            result = 1  # Native ownership query: this is the local player's shell.
        elif off == 0x1070:
            result = player_dti
        elif off == 0x1010:
            # Native movement ABI: indirect vector return through x8. Zero velocity
            # leaves the world position exactly unchanged on this frame.
            assert bytes(uc.mem_read(reg(3), 12)) == bytes(12)
            assert bytes(uc.mem_read(reg(4), 12)) == bytes(12)
            uc.mem_write(reg(8), bytes(uc.mem_read(reg(1), 16)))
        elif off == 0x1020:
            uc.mem_write(reg(1), bytes(16))  # No geometric collision.
            uc.mem_write(reg(2), bytes(8))
        elif off == 0x1080:
            uc.mem_write(reg(0) + 0x60, bytes(uc.mem_read(reg(1), 16)))
        elif off == 0x1090:
            requests.append(tuple(reg(i) for i in range(6)))
        uc.reg_write(A.UC_ARM64_REG_X0, result)
        uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))

    u.hook_add(U.UC_HOOK_CODE, hook)
    u.reg_write(A.UC_ARM64_REG_CPACR_EL1, 0x300000)
    u.reg_write(A.UC_ARM64_REG_X0, unit)
    u.reg_write(A.UC_ARM64_REG_SP, stack + 0x8000)
    u.reg_write(A.UC_ARM64_REG_LR, base + 0x1100)
    u.emu_start(base + 0xF45AB0, base + 0x1100, count=10000)
    assert u.reg_read(A.UC_ARM64_REG_PC) == base + 0x1100
    assert u.reg_read(A.UC_ARM64_REG_SP) == stack + 0x8000
    assert bytes(u.mem_read(unit + 0x60, 16)) == pos
    assert requests == ([(unit, 17, 0, 0, 0xFFFFFFFF, 0)] if forced else [])
    assert calls == (["native_impact"] if forced else [])
    phase = struct.unpack("<I", u.mem_read(unit + 0xC, 4))[0]
    collision = struct.unpack("<I", u.mem_read(unit + 0x2C18, 4))[0]
    assert phase == (0x10201 if forced else 0x201)
    assert collision & 1 == int(forced)
    return {"base": hex(base), "forced": forced, "position_unchanged": True,
            "native_impact_called": forced, "requested_action": 17 if forced else None}


if __name__ == "__main__":
    elf = Path(sys.argv[1]).read_bytes()
    for base in (0x10000000, 0x3CA7C04000):
        for forced in (False, True):
            print(execute(elf, base, forced))
    print("PASS: native stationary shells dispatch impact/action17 only when forced")
