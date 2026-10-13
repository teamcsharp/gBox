"""Tecmo TPS (Sony ZN, BIOS coh1002m) program decoder: runs the BIOS's own decode code on a tiny R3000 interpreter.

A TPS game ROM does not hold its main program in the clear. bankedroms+0 is a 4-byte header, the SCEI licence string and
an encoded image; the BIOS (m534002c-61.ic353) checks the licence and calls its kernel function B0:0x63, which decodes
the program into RAM 0x80010000.. through the two CAT702 security chips on the SIO0 port (mg01 on the CPU board, mg05 /
mgNN on the ROM board) and returns the entry point. The kernel itself sits encoded in the BIOS at 0x30000 (header
0x08100080: 8 x 16 x 128-byte blocks) and is decoded by the same scheme (BIOS routine 0xbfc0638c, chip mg01).

Nothing here re-implements that cipher: decode_program() executes the BIOS's code (kernel decode, then B0:0x63) on the
interpreter below with the bankedroms window (0x1f000000, 8 MiB banks, bank byte at 0x1fb00006) and a CAT702 model
(MAME src/devices/machine/cat702.cpp, the transfer is SIO0 byte exchange) wired the way MAME's zn.cpp wires them
(znsecsel 0x1fa10300 bit 2 = mg01 select, bit 3 = ROM-board select, active low). The decoders call rand() for their
work order; the result does not depend on the seed. ~10 M instructions, about 40 s of CPU in CPython.

Pinned to the TPS BIOS below; another BIOS has other entry points and is refused.
"""
from __future__ import annotations

import hashlib

TPS_BIOS_SHA1 = "03eb2febfab3fcde716defff291babd9392de965"   # m534002c-61.ic353 (MAME TECMO_TPS_SYSTEM_BIOS)
KERNEL_DECODE = 0xBFC0638C       # BIOS: decode(src=a0, dst=a1); used by the boot path on the kernel image
KERNEL_IMAGE = 0xBFC30000        # encoded kernel image (decodes to RAM 0x500..)
KERNEL_DEST = 0xA0000500
B0_TABLE, A0_TABLE, C0_TABLE = 0x874, 0x200, 0x674
B0_BOOT_GAME = 0x63              # kernel B0:0x63 = decode the game program from bankedroms, returns the entry point
DISPATCH = 0x801FF000            # scratch spot for the A0/B0/C0 table dispatcher the real kernel init would install
STOP = 0xDEAD0000
M32 = 0xFFFFFFFF
CAT702_INITIAL = (0xFF, 0xFE, 0xFC, 0xF8, 0xF0, 0xE0, 0xC0, 0x7F)


class DecodeError(RuntimeError):
    pass


def _s16(x: int) -> int:
    return x - 0x10000 if x & 0x8000 else x


def _s32(x: int) -> int:
    return x - 0x100000000 if x & 0x80000000 else x


class Cat702:
    """CAT702 serial latch at byte level: per byte the initial s-box, then per input bit (LSB first) the state bit is
    sent and a 0 input applies that bit's s-box (derived from the chip's 8-byte transform)."""

    def __init__(self, transform: bytes):
        if len(transform) != 8:
            raise ValueError("a CAT702 transform is 8 bytes")
        coef: dict[tuple[int, int], int] = {}

        def c(sel: int, bit: int) -> int:
            if (sel, bit) not in coef:
                if not sel:
                    r = transform[bit]
                else:
                    r = c((sel - 1) & 7, (bit - 1) & 7)
                    r = ((r << 1) | (((r >> 7) ^ (r >> 6)) & 1)) & 0xFF
                    if bit == 7:
                        r ^= c(sel, 0)
                coef[sel, bit] = r
            return coef[sel, bit]
        self.sbox = [[c(s, b) for b in range(8)] for s in range(8)]
        self.select = 1
        self.state = 0

    @staticmethod
    def _apply(state: int, box) -> int:
        r = 0
        for i in range(8):
            if state >> i & 1:
                r ^= box[i]
        return r

    def set_select(self, v: int) -> None:
        if v != self.select and not v:
            self.state = 0xFC
        self.select = v

    def xfer(self, byte: int) -> int:
        if self.select:
            return 0xFF
        s = self._apply(self.state, CAT702_INITIAL)
        out = 0
        for bit in range(8):
            out |= (s >> bit & 1) << bit
            if not (byte >> bit & 1):
                s = self._apply(s, self.sbox[bit])
        self.state = s
        return out


class ZNMemory:
    """2 MiB RAM (mirrored), 1 KiB scratchpad, BIOS, the bankedroms window, SIO0 + two CAT702s. Other I/O reads 0."""

    def __init__(self, bios: bytes, banked: bytes, cat_cpu: bytes, cat_rom: bytes):
        self.ram = bytearray(0x200000)
        self.scratch = bytearray(0x400)
        self.bios = bytes(bios)
        self.banked = banked
        self.bank = 0
        self.secsel = 0
        self.cats = (Cat702(cat_cpu), Cat702(cat_rom))
        self.rx: list[int] = []

    def _where(self, a: int):
        p = a & 0x1FFFFFFF
        if p < 0x800000:
            return self.ram, p & 0x1FFFFF
        if 0x1F800000 <= p < 0x1F800400:
            return self.scratch, p - 0x1F800000
        if 0x1FC00000 <= p < 0x1FC80000:
            return self.bios, p - 0x1FC00000
        if 0x1F000000 <= p < 0x1F800000:
            return None, self.bank * 0x800000 + p - 0x1F000000
        return None, None

    def r8(self, a: int) -> int:
        p = a & 0x1FFFFFFF
        if p == 0x1F801040:
            return self.rx.pop(0) if self.rx else 0xFF
        if p == 0x1FA10300:
            return self.secsel
        buf, o = self._where(a)
        if buf is not None:
            return buf[o]
        if o is not None:
            return self.banked[o] if o < len(self.banked) else 0xFF
        return 0

    def r16(self, a: int) -> int:
        if (a & 0x1FFFFFFF) == 0x1F801044:
            return 0x7 if self.rx else 0x5      # TX ready + TX done, RX pending
        return self.r8(a) | self.r8(a + 1) << 8

    def r32(self, a: int) -> int:
        if (a & 0x1FFFFFFF) == 0x1F801044:
            return 0x7 if self.rx else 0x5
        buf, o = self._where(a)
        if buf is not None:
            return int.from_bytes(buf[o:o + 4], "little")
        if o is not None:
            return int.from_bytes(self.banked[o:o + 4], "little") if o + 4 <= len(self.banked) else M32
        return 0

    def w8(self, a: int, v: int) -> None:
        p = a & 0x1FFFFFFF
        if p == 0x1FA10300:
            self.secsel = v & 0xFF
            self.cats[0].set_select(v >> 2 & 1)
            self.cats[1].set_select(v >> 3 & 1)
        elif p == 0x1F801040:
            self.rx.append(self.cats[0].xfer(v & 0xFF) & self.cats[1].xfer(v & 0xFF))
        elif p == 0x1FB00006:
            self.bank = v & 0xFF
        else:
            buf, o = self._where(a)
            if buf is not None and buf is not self.bios:
                buf[o] = v & 0xFF

    def w16(self, a: int, v: int) -> None:
        if (a & 0x1FFFFFFF) == 0x1FB00006:
            self.bank = v & 0xFF
            return
        self.w8(a, v)
        self.w8(a + 1, v >> 8)

    def w32(self, a: int, v: int) -> None:
        buf, o = self._where(a)
        if buf is not None and buf is not self.bios:
            buf[o:o + 4] = (v & M32).to_bytes(4, "little")
        elif (a & 0x1FFFFFFC) == 0x1FB00004:
            self.bank = (v >> 16) & 0xFF


class R3000:
    """Integer R3000A with branch delay slots. COP0 moves are no-ops; COP2 (GTE) moves read 0 unless a GTE model is
    attached (gte=gbox.psx_gte.GTE()), which then also executes GTE commands and lwc2/swc2 (game code that builds
    matrices, e.g. gbox.doapp_motion)."""

    def __init__(self, mem: ZNMemory, gte=None):
        self.m = mem
        self.r = [0] * 32
        self.hi = self.lo = 0
        self.steps = 0
        self.gte = gte

    def call(self, pc: int, args=(), *, sp: int = 0x801FFF00, limit: int = 60_000_000) -> int:
        r, m, gte = self.r, self.m, self.gte
        for i, a in enumerate(args):
            r[4 + i] = a & M32
        r[29], r[31] = sp, STOP
        npc = (pc + 4) & M32
        n = 0
        while pc != STOP:
            n += 1
            if n > limit:
                raise DecodeError(f"no return after {limit} instructions (pc {pc:08x})")
            ins = m.r32(pc)
            cur, pc, npc = pc, npc, (npc + 4) & M32
            op, rs, rt = ins >> 26, (ins >> 21) & 31, (ins >> 16) & 31
            if op == 0:
                rd, fn, sa = (ins >> 11) & 31, ins & 63, (ins >> 6) & 31
                a, b = r[rs], r[rt]
                if fn in (0x20, 0x21):
                    v = (a + b) & M32
                elif fn in (0x22, 0x23):
                    v = (a - b) & M32
                elif fn == 0x24:
                    v = a & b
                elif fn == 0x25:
                    v = a | b
                elif fn == 0x26:
                    v = a ^ b
                elif fn == 0x27:
                    v = ~(a | b) & M32
                elif fn == 0x00:
                    v = (b << sa) & M32
                elif fn == 0x02:
                    v = b >> sa
                elif fn == 0x03:
                    v = (_s32(b) >> sa) & M32
                elif fn == 0x04:
                    v = (b << (a & 31)) & M32
                elif fn == 0x06:
                    v = b >> (a & 31)
                elif fn == 0x07:
                    v = (_s32(b) >> (a & 31)) & M32
                elif fn == 0x2A:
                    v = int(_s32(a) < _s32(b))
                elif fn == 0x2B:
                    v = int(a < b)
                elif fn == 0x08:
                    npc = a
                    continue
                elif fn == 0x09:
                    r[rd] = (cur + 8) & M32
                    npc = a
                    r[0] = 0
                    continue
                elif fn == 0x10:
                    v = self.hi
                elif fn == 0x12:
                    v = self.lo
                elif fn == 0x11:
                    self.hi = a
                    continue
                elif fn == 0x13:
                    self.lo = a
                    continue
                elif fn in (0x18, 0x19):
                    p = _s32(a) * _s32(b) if fn == 0x18 else a * b
                    self.lo, self.hi = p & M32, (p >> 32) & M32
                    continue
                elif fn == 0x1A:
                    x, y = _s32(a), _s32(b)
                    if y:
                        q = abs(x) // abs(y) * (-1 if (x < 0) != (y < 0) else 1)
                        self.lo, self.hi = q & M32, (x - q * y) & M32
                    continue
                elif fn == 0x1B:
                    if b:
                        self.lo, self.hi = a // b, a % b
                    continue
                else:
                    raise DecodeError(f"unsupported SPECIAL {fn:#x} at {cur:08x}")
                if rd:
                    r[rd] = v
                continue
            imm = ins & 0xFFFF
            ea = (r[rs] + _s16(imm)) & M32
            if op in (0x08, 0x09):
                if rt:
                    r[rt] = ea
            elif op == 0x0F:
                if rt:
                    r[rt] = imm << 16
            elif op == 0x23:
                v = m.r32(ea)
                if rt:
                    r[rt] = v
            elif op == 0x2B:
                m.w32(ea, r[rt])
            elif op == 0x0D:
                if rt:
                    r[rt] = r[rs] | imm
            elif op == 0x0C:
                if rt:
                    r[rt] = r[rs] & imm
            elif op == 0x0E:
                if rt:
                    r[rt] = r[rs] ^ imm
            elif op == 0x24:
                if rt:
                    r[rt] = m.r8(ea)
            elif op == 0x20:
                v = m.r8(ea)
                if rt:
                    r[rt] = v | 0xFFFFFF00 if v & 0x80 else v
            elif op == 0x25:
                if rt:
                    r[rt] = m.r16(ea)
            elif op == 0x21:
                v = m.r16(ea)
                if rt:
                    r[rt] = v | 0xFFFF0000 if v & 0x8000 else v
            elif op == 0x28:
                m.w8(ea, r[rt])
            elif op == 0x29:
                m.w16(ea, r[rt] & 0xFFFF)
            elif op == 0x0A:
                if rt:
                    r[rt] = int(_s32(r[rs]) < _s16(imm))
            elif op == 0x0B:
                if rt:
                    r[rt] = int(r[rs] < (_s16(imm) & M32))
            elif op == 0x04:
                if r[rs] == r[rt]:
                    npc = (cur + 4 + (_s16(imm) << 2)) & M32
            elif op == 0x05:
                if r[rs] != r[rt]:
                    npc = (cur + 4 + (_s16(imm) << 2)) & M32
            elif op == 0x06:
                if _s32(r[rs]) <= 0:
                    npc = (cur + 4 + (_s16(imm) << 2)) & M32
            elif op == 0x07:
                if _s32(r[rs]) > 0:
                    npc = (cur + 4 + (_s16(imm) << 2)) & M32
            elif op == 0x01:
                take = (_s32(r[rs]) >= 0) == bool(rt & 1)
                if rt & 0x10:
                    r[31] = (cur + 8) & M32
                if take:
                    npc = (cur + 4 + (_s16(imm) << 2)) & M32
            elif op in (0x02, 0x03):
                if op == 0x03:
                    r[31] = (cur + 8) & M32
                npc = ((cur + 4) & 0xF0000000) | ((ins & 0x3FFFFFF) << 2)
            elif op in (0x22, 0x26):            # lwl / lwr
                w, sh = m.r32(ea & ~3), ea & 3
                if rt:
                    if op == 0x22:
                        r[rt] = ((r[rt] & (0x00FFFFFF >> (sh * 8))) | (w << (24 - sh * 8))) & M32
                    else:
                        r[rt] = ((r[rt] & ((0xFFFFFF00 << ((3 - sh) * 8)) & M32)) | (w >> (sh * 8))) & M32
            elif op in (0x2A, 0x2E):            # swl / swr
                w, sh = m.r32(ea & ~3), ea & 3
                if op == 0x2A:
                    w = (w & ((0xFFFFFF00 << (sh * 8)) & M32)) | (r[rt] >> (24 - sh * 8))
                else:
                    w = (w & (0x00FFFFFF >> ((3 - sh) * 8))) | ((r[rt] << (sh * 8)) & M32)
                m.w32(ea & ~3, w)
            elif op == 0x12 and gte is not None:
                gte.cop2(ins, r)
                r[0] = 0
            elif op == 0x32 and gte is not None:  # lwc2
                gte.write_data(rt, m.r32(ea))
            elif op == 0x3A and gte is not None:  # swc2
                m.w32(ea, gte.read_data(rt))
            elif op in (0x10, 0x12):            # COP0 / GTE: moves from read 0
                if rs == 0 and rt:
                    r[rt] = 0
            else:
                raise DecodeError(f"unsupported opcode {op:#x} at {cur:08x}")
        self.steps += n
        return r[2]


def decode_program(bios: bytes, banked: bytes, cat_cpu: bytes, cat_rom: bytes, *,
                   limit: int = 60_000_000) -> tuple[bytes, int]:
    """(2 MiB main RAM after the BIOS decoded the game program, the entry point it returned)."""
    if hashlib.sha1(bios).hexdigest() != TPS_BIOS_SHA1:
        raise DecodeError("not the Tecmo TPS BIOS m534002c-61.ic353 these entry points belong to")
    if len(banked) < 0x40 or b"Licensed by Sony Computer Entertainment Inc." not in banked[:0x40]:
        raise DecodeError("bankedroms does not start with the SCEI licence block the BIOS boots")
    mem = ZNMemory(bios, banked, cat_cpu, cat_rom)
    cpu = R3000(mem)
    cpu.call(KERNEL_DECODE, (KERNEL_IMAGE, KERNEL_DEST), limit=limit)
    # the A0/B0/C0 vectors the kernel's own init would install: t0 = table, t1 = function number
    for vec, table in ((0xA0, A0_TABLE), (0xB0, B0_TABLE), (0xC0, C0_TABLE)):
        for i, w in enumerate((0x24080000 | table, 0x08000000 | ((DISPATCH & 0x3FFFFFF) >> 2), 0)):
            mem.w32(vec + 4 * i, w)
    for i, w in enumerate((0x00094880, 0x01094021, 0x8D080000, 0, 0x01000008, 0)):
        mem.w32(DISPATCH + 4 * i, w)          # sll t1,t1,2; addu t0,t0,t1; lw t0,0(t0); nop; jr t0; nop
    boot = mem.r32(B0_TABLE + 4 * B0_BOOT_GAME)
    if not 0x500 <= boot < 0x10000:
        raise DecodeError(f"kernel decode failed (B0:{B0_BOOT_GAME:#x} = {boot:#x})")
    entry = cpu.call(0x80000000 | boot, limit=limit)
    if not 0x80010000 <= entry < 0x80200000:
        raise DecodeError(f"program decode returned no entry point ({entry:#x})")
    return bytes(mem.ram), entry
