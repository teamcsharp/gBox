"""PlayStation GTE (COP2) model for gbox.zn_tps_boot's R3000 interpreter.

Enough of the geometry coprocessor to run game code that builds and applies matrices: the register file with its
read/write quirks (sign-extended IR/VZ, the SXY / SZ FIFOs, IRGB/ORGB, LZCS/LZCR), MVMVA, RTPS/RTPT, NCLIP, SQR, OP,
AVSZ3/AVSZ4, GPF/GPL. The lighting/colour commands (NCS, NCDS, CC, DPCS, ...) are not modelled and raise, so a run
never silently computes something wrong. Arithmetic follows the documented hardware (psx-spx "Geometry Transformation
Engine"): MAC = (T << 12) + M * V, shifted right by 12 when sf is set, IR saturated to -0x8000/0..0x7fff (lm bit).
The 44-bit MAC overflow and most FLAG bits are not tracked (FLAG reads 0 unless a saturation happened).
"""
from __future__ import annotations

M32 = 0xFFFFFFFF


def _s16(x: int) -> int:
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def _s32(x: int) -> int:
    x &= M32
    return x - 0x100000000 if x & 0x80000000 else x


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


class GteError(RuntimeError):
    pass


class GTE:
    NAMES = {0x01: "RTPS", 0x06: "NCLIP", 0x0C: "OP", 0x12: "MVMVA", 0x28: "SQR", 0x2D: "AVSZ3", 0x2E: "AVSZ4",
             0x30: "RTPT", 0x3D: "GPF", 0x3E: "GPL"}

    def __init__(self):
        self.d = [0] * 32          # data registers, raw 32-bit
        self.c = [0] * 32          # control registers, raw 32-bit
        self.commands = 0

    # ---- register file -------------------------------------------------------------------------------------------
    def read_data(self, i: int) -> int:
        d = self.d
        if i in (1, 3, 5, 8, 9, 10, 11):
            return _s16(d[i]) & M32
        if i in (7, 16, 17, 18, 19):
            return d[i] & 0xFFFF
        if i == 15:
            return d[14]
        if i in (28, 29):
            r = _clamp(_s16(d[9]) >> 7, 0, 0x1F)
            g = _clamp(_s16(d[10]) >> 7, 0, 0x1F)
            b = _clamp(_s16(d[11]) >> 7, 0, 0x1F)
            return r | g << 5 | b << 10
        return d[i] & M32

    def write_data(self, i: int, v: int) -> None:
        v &= M32
        d = self.d
        if i == 15:
            d[12], d[13], d[14] = d[13], d[14], v
            return
        if i == 28:
            d[28] = v & 0x7FFF
            d[9], d[10], d[11] = (v & 0x1F) << 7, (v >> 5 & 0x1F) << 7, (v >> 10 & 0x1F) << 7
            return
        if i == 29 or i == 31:
            return
        if i == 30:
            d[30] = v
            x = v if not v & 0x80000000 else ~v & M32
            n = 0
            while n < 32 and not x & (0x80000000 >> n):
                n += 1
            d[31] = n
            return
        d[i] = v

    def read_ctrl(self, i: int) -> int:
        if i in (4, 12, 20, 26, 27, 29, 30):
            return _s16(self.c[i]) & M32
        return self.c[i] & M32

    def write_ctrl(self, i: int, v: int) -> None:
        self.c[i] = v & M32

    # ---- helpers ---------------------------------------------------------------------------------------------------
    def _matrix(self, base: int):
        c = self.c
        w = [c[base + k] for k in range(5)]
        return ((_s16(w[0]), _s16(w[0] >> 16), _s16(w[1])),
                (_s16(w[1] >> 16), _s16(w[2]), _s16(w[2] >> 16)),
                (_s16(w[3]), _s16(w[3] >> 16), _s16(w[4])))

    def matrix(self):
        """The rotation matrix RT as three rows of s16 (4.12)."""
        return self._matrix(0)

    def translation(self):
        return tuple(_s32(self.c[5 + k]) for k in range(3))

    def _vec(self, n: int):
        d = self.d
        if n == 3:
            return (_s16(d[9]), _s16(d[10]), _s16(d[11]))
        return (_s16(d[2 * n]), _s16(d[2 * n] >> 16), _s16(d[2 * n + 1]))

    def _set_mac_ir(self, macs, lm: int) -> None:
        lo = 0 if lm else -0x8000
        for k in range(3):
            self.d[25 + k] = macs[k] & M32
            ir = _clamp(macs[k], lo, 0x7FFF)
            if ir != macs[k]:
                self.c[31] |= 1 << (24 - k) | 0x80000000
            self.d[9 + k] = ir & M32

    def _rtp(self, n: int, sf: int, lm: int, last: bool) -> None:
        rt, tr = self.matrix(), self.translation()
        v = self._vec(n)
        sh = 12 * sf
        macs = [((tr[k] << 12) + rt[k][0] * v[0] + rt[k][1] * v[1] + rt[k][2] * v[2]) >> sh for k in range(3)]
        self._set_mac_ir(macs, lm)
        d = self.d
        d[16], d[17], d[18] = d[17], d[18], d[19]
        sz = _clamp(macs[2] >> (12 - sh), 0, 0xFFFF)
        d[19] = sz
        h = self.c[26] & 0xFFFF
        if sz > h // 2:
            q = min(0x1FFFF, ((h * 0x20000 // sz) + 1) // 2)
        else:
            q = 0x1FFFF
            self.c[31] |= 1 << 17 | 0x80000000
        ofx, ofy = _s32(self.c[24]), _s32(self.c[25])
        ir1, ir2 = _s16(d[9]), _s16(d[10])
        sx = _clamp((ofx + ir1 * q) >> 16, -0x400, 0x3FF)
        sy = _clamp((ofy + ir2 * q) >> 16, -0x400, 0x3FF)
        d[12], d[13], d[14] = d[13], d[14], (sx & 0xFFFF) | (sy & 0xFFFF) << 16
        if last:
            dqa, dqb = _s16(self.c[27]), _s32(self.c[28])
            mac0 = dqb + dqa * q
            d[24] = mac0 & M32
            d[8] = _clamp(mac0 >> 12, 0, 0x1000)

    # ---- command dispatch ------------------------------------------------------------------------------------------
    def command(self, ins: int) -> None:
        fn, sf, lm = ins & 0x3F, ins >> 19 & 1, ins >> 10 & 1
        self.c[31] = 0
        self.commands += 1
        d = self.d
        if fn == 0x12:
            mx, vn, cv = ins >> 17 & 3, ins >> 15 & 3, ins >> 13 & 3
            if mx == 3:
                raise GteError("MVMVA with the reserved matrix selector")
            m = self._matrix((0, 8, 16)[mx])
            v = self._vec(vn)
            t = (0, 0, 0) if cv == 3 else tuple(_s32(self.c[(5, 13, 21)[cv] + k]) for k in range(3))
            if cv == 2:
                raise GteError("MVMVA with the far-colour vector (hardware bug not modelled)")
            sh = 12 * sf
            self._set_mac_ir([((t[k] << 12) + m[k][0] * v[0] + m[k][1] * v[1] + m[k][2] * v[2]) >> sh
                              for k in range(3)], lm)
        elif fn == 0x01:
            self._rtp(0, sf, lm, True)
        elif fn == 0x30:
            for n in range(3):
                self._rtp(n, sf, lm, n == 2)
        elif fn == 0x06:
            sx = [_s16(d[12 + k]) for k in range(3)]
            sy = [_s16(d[12 + k] >> 16) for k in range(3)]
            mac0 = (sx[0] * sy[1] + sx[1] * sy[2] + sx[2] * sy[0] - sx[0] * sy[2] - sx[1] * sy[0] - sx[2] * sy[1])
            d[24] = mac0 & M32
        elif fn == 0x28:
            ir = self._vec(3)
            self._set_mac_ir([(ir[k] * ir[k]) >> (12 * sf) for k in range(3)], lm)
        elif fn == 0x0C:
            rt, ir = self.matrix(), self._vec(3)
            d1, d2, d3 = rt[0][0], rt[1][1], rt[2][2]
            sh = 12 * sf
            self._set_mac_ir([(d2 * ir[2] - d3 * ir[1]) >> sh, (d3 * ir[0] - d1 * ir[2]) >> sh,
                              (d1 * ir[1] - d2 * ir[0]) >> sh], lm)
        elif fn in (0x2D, 0x2E):
            if fn == 0x2D:
                mac0 = _s16(self.c[29]) * (d[17] + d[18] + d[19])
            else:
                mac0 = _s16(self.c[30]) * (d[16] + d[17] + d[18] + d[19])
            d[24] = mac0 & M32
            d[7] = _clamp(mac0 >> 12, 0, 0xFFFF)
        elif fn in (0x3D, 0x3E):
            ir0, ir = _s16(d[8]), self._vec(3)
            sh = 12 * sf
            base = [(_s32(d[25 + k]) << sh) if fn == 0x3E else 0 for k in range(3)]
            self._set_mac_ir([(base[k] + ir0 * ir[k]) >> sh for k in range(3)], lm)
        else:
            raise GteError(f"GTE command {fn:#x} is not modelled")

    def cop2(self, ins: int, regs: list) -> None:
        """Execute a COP2-major instruction (opcode 0x12) against the CPU register list."""
        if ins & (1 << 25):
            self.command(ins)
            return
        rs, rt, rd = ins >> 21 & 31, ins >> 16 & 31, ins >> 11 & 31
        if rs == 0:
            if rt:
                regs[rt] = self.read_data(rd)
        elif rs == 2:
            if rt:
                regs[rt] = self.read_ctrl(rd)
        elif rs == 4:
            self.write_data(rd, regs[rt])
        elif rs == 6:
            self.write_ctrl(rd, regs[rt])
        else:
            raise GteError(f"unsupported COP2 move {ins:#010x}")
