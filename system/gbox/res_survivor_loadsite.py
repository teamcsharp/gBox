"""KERNEL.BIN NOISE.BIN load-site facts derived from owned bytes (PS-X EXE, file 0x800 header)."""
import struct
HDR = 0x800
BASE = 0x80010000


def va_to_off(va):
    return va - BASE + HDR


def find_string_xrefs(data, string_off):
    """lui/addiu(-style) references to the VA of a string at file offset string_off."""
    va = BASE + string_off - HDR
    hi, lo = va >> 16, va & 0xFFFF
    if lo >= 0x8000:
        hi += 1
    out = []
    for k in range(HDR, len(data) - 4, 4):
        w = struct.unpack_from('<I', data, k)[0]
        if w >> 26 == 0x0F and (w & 0xFFFF) == hi:
            for j in range(k + 4, min(k + 32, len(data) - 4), 4):
                v = struct.unpack_from('<I', data, j)[0]
                if v >> 26 == 9 and (v & 0xFFFF) == lo:
                    out.append(BASE + k - HDR)
                    break
    return va, out
