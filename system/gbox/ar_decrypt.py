"""Encrypted GameCube Action Replay codes (XXXX-XXXX-XXXXX) decrypted to raw code pairs.

A port of Dolphin's Source/Core/Core/ARDecrypt.cpp (GPL-2.0-or-later): published Action Replay codes for
GameCube titles are almost always in the encrypted 13-character form that Dolphin's own code dialog decrypts.
gBox's cheats decoder works on raw pairs ("04XXXXXX YYYYYYYY"), so a published list decrypts here first. Each
batch's first pair is its verification code: a CRC over the batch plus the game id and region, which only
matches when every character was read right, so a decrypted batch that verifies is trustworthy.
"""
from __future__ import annotations

import re

FILTER = "0123456789ABCDEFGHJKMNPQRTUVWXYZILOS"
ENCRYPTED = re.compile(r"^[0-9A-Za-z]{4}-?[0-9A-Za-z]{4}-?[0-9A-Za-z]{5}$")
M = 0xFFFFFFFF

_GENTABLE0 = (0x39, 0x31, 0x29, 0x21, 0x19, 0x11, 0x09, 0x01, 0x3A, 0x32, 0x2A, 0x22, 0x1A, 0x12,
              0x0A, 0x02, 0x3B, 0x33, 0x2B, 0x23, 0x1B, 0x13, 0x0B, 0x03, 0x3C, 0x34, 0x2C, 0x24,
              0x3F, 0x37, 0x2F, 0x27, 0x1F, 0x17, 0x0F, 0x07, 0x3E, 0x36, 0x2E, 0x26, 0x1E, 0x16,
              0x0E, 0x06, 0x3D, 0x35, 0x2D, 0x25, 0x1D, 0x15, 0x0D, 0x05, 0x1C, 0x14, 0x0C, 0x04)
_GENTABLE1 = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)
_GENTABLE2 = (0x01, 0x02, 0x04, 0x06, 0x08, 0x0A, 0x0C, 0x0E, 0x0F, 0x11, 0x13, 0x15, 0x17, 0x19, 0x1B, 0x1C)
_GENTABLE3 = (0x0E, 0x11, 0x0B, 0x18, 0x01, 0x05, 0x03, 0x1C, 0x0F, 0x06, 0x15, 0x0A, 0x17, 0x13, 0x0C, 0x04,
              0x1A, 0x08, 0x10, 0x07, 0x1B, 0x14, 0x0D, 0x02, 0x29, 0x34, 0x1F, 0x25, 0x2F, 0x37, 0x1E, 0x28,
              0x33, 0x2D, 0x21, 0x30, 0x2C, 0x31, 0x27, 0x38, 0x22, 0x35, 0x2E, 0x2A, 0x32, 0x24, 0x1D, 0x20)
_CRC0 = (0x0000, 0x1081, 0x2102, 0x3183, 0x4204, 0x5285, 0x6306, 0x7387,
         0x8408, 0x9489, 0xA50A, 0xB58B, 0xC60C, 0xD68D, 0xE70E, 0xF78F)
_CRC1 = (0x0000, 0x1189, 0x2312, 0x329B, 0x4624, 0x57AD, 0x6536, 0x74BF,
         0x8C48, 0x9DC1, 0xAF5A, 0xBED3, 0xCA6C, 0xDBE5, 0xE97E, 0xF8F7)
_GENSUB = (0x34, 0x1C, 0x84, 0x9E, 0xFD, 0xA4, 0xB6, 0x7B)
_T0 = (0x01010400, 0x00000000, 0x00010000, 0x01010404, 0x01010004, 0x00010404, 0x00000004, 0x00010000,
       0x00000400, 0x01010400, 0x01010404, 0x00000400, 0x01000404, 0x01010004, 0x01000000, 0x00000004,
       0x00000404, 0x01000400, 0x01000400, 0x00010400, 0x00010400, 0x01010000, 0x01010000, 0x01000404,
       0x00010004, 0x01000004, 0x01000004, 0x00010004, 0x00000000, 0x00000404, 0x00010404, 0x01000000,
       0x00010000, 0x01010404, 0x00000004, 0x01010000, 0x01010400, 0x01000000, 0x01000000, 0x00000400,
       0x01010004, 0x00010000, 0x00010400, 0x01000004, 0x00000400, 0x00000004, 0x01000404, 0x00010404,
       0x01010404, 0x00010004, 0x01010000, 0x01000404, 0x01000004, 0x00000404, 0x00010404, 0x01010400,
       0x00000404, 0x01000400, 0x01000400, 0x00000000, 0x00010004, 0x00010400, 0x00000000, 0x01010004)
_T1 = (0x80108020, 0x80008000, 0x00008000, 0x00108020, 0x00100000, 0x00000020, 0x80100020, 0x80008020,
       0x80000020, 0x80108020, 0x80108000, 0x80000000, 0x80008000, 0x00100000, 0x00000020, 0x80100020,
       0x00108000, 0x00100020, 0x80008020, 0x00000000, 0x80000000, 0x00008000, 0x00108020, 0x80100000,
       0x00100020, 0x80000020, 0x00000000, 0x00108000, 0x00008020, 0x80108000, 0x80100000, 0x00008020,
       0x00000000, 0x00108020, 0x80100020, 0x00100000, 0x80008020, 0x80100000, 0x80108000, 0x00008000,
       0x80100000, 0x80008000, 0x00000020, 0x80108020, 0x00108020, 0x00000020, 0x00008000, 0x80000000,
       0x00008020, 0x80108000, 0x00100000, 0x80000020, 0x00100020, 0x80008020, 0x80000020, 0x00100020,
       0x00108000, 0x00000000, 0x80008000, 0x00008020, 0x80000000, 0x80100020, 0x80108020, 0x00108000)
_T2 = (0x00000208, 0x08020200, 0x00000000, 0x08020008, 0x08000200, 0x00000000, 0x00020208, 0x08000200,
       0x00020008, 0x08000008, 0x08000008, 0x00020000, 0x08020208, 0x00020008, 0x08020000, 0x00000208,
       0x08000000, 0x00000008, 0x08020200, 0x00000200, 0x00020200, 0x08020000, 0x08020008, 0x00020208,
       0x08000208, 0x00020200, 0x00020000, 0x08000208, 0x00000008, 0x08020208, 0x00000200, 0x08000000,
       0x08020200, 0x08000000, 0x00020008, 0x00000208, 0x00020000, 0x08020200, 0x08000200, 0x00000000,
       0x00000200, 0x00020008, 0x08020208, 0x08000200, 0x08000008, 0x00000200, 0x00000000, 0x08020008,
       0x08000208, 0x00020000, 0x08000000, 0x08020208, 0x00000008, 0x00020208, 0x00020200, 0x08000008,
       0x08020000, 0x08000208, 0x00000208, 0x08020000, 0x00020208, 0x00000008, 0x08020008, 0x00020200)
_T3 = (0x00802001, 0x00002081, 0x00002081, 0x00000080, 0x00802080, 0x00800081, 0x00800001, 0x00002001,
       0x00000000, 0x00802000, 0x00802000, 0x00802081, 0x00000081, 0x00000000, 0x00800080, 0x00800001,
       0x00000001, 0x00002000, 0x00800000, 0x00802001, 0x00000080, 0x00800000, 0x00002001, 0x00002080,
       0x00800081, 0x00000001, 0x00002080, 0x00800080, 0x00002000, 0x00802080, 0x00802081, 0x00000081,
       0x00800080, 0x00800001, 0x00802000, 0x00802081, 0x00000081, 0x00000000, 0x00000000, 0x00802000,
       0x00002080, 0x00800080, 0x00800081, 0x00000001, 0x00802001, 0x00002081, 0x00002081, 0x00000080,
       0x00802081, 0x00000081, 0x00000001, 0x00002000, 0x00800001, 0x00002001, 0x00802080, 0x00800081,
       0x00002001, 0x00002080, 0x00800000, 0x00802001, 0x00000080, 0x00800000, 0x00002000, 0x00802080)
_T4 = (0x00000100, 0x02080100, 0x02080000, 0x42000100, 0x00080000, 0x00000100, 0x40000000, 0x02080000,
       0x40080100, 0x00080000, 0x02000100, 0x40080100, 0x42000100, 0x42080000, 0x00080100, 0x40000000,
       0x02000000, 0x40080000, 0x40080000, 0x00000000, 0x40000100, 0x42080100, 0x42080100, 0x02000100,
       0x42080000, 0x40000100, 0x00000000, 0x42000000, 0x02080100, 0x02000000, 0x42000000, 0x00080100,
       0x00080000, 0x42000100, 0x00000100, 0x02000000, 0x40000000, 0x02080000, 0x42000100, 0x40080100,
       0x02000100, 0x40000000, 0x42080000, 0x02080100, 0x40080100, 0x00000100, 0x02000000, 0x42080000,
       0x42080100, 0x00080100, 0x42000000, 0x42080100, 0x02080000, 0x00000000, 0x40080000, 0x42000000,
       0x00080100, 0x02000100, 0x40000100, 0x00080000, 0x00000000, 0x40080000, 0x02080100, 0x40000100)
_T5 = (0x20000010, 0x20400000, 0x00004000, 0x20404010, 0x20400000, 0x00000010, 0x20404010, 0x00400000,
       0x20004000, 0x00404010, 0x00400000, 0x20000010, 0x00400010, 0x20004000, 0x20000000, 0x00004010,
       0x00000000, 0x00400010, 0x20004010, 0x00004000, 0x00404000, 0x20004010, 0x00000010, 0x20400010,
       0x20400010, 0x00000000, 0x00404010, 0x20404000, 0x00004010, 0x00404000, 0x20404000, 0x20000000,
       0x20004000, 0x00000010, 0x20400010, 0x00404000, 0x20404010, 0x00400000, 0x00004010, 0x20000010,
       0x00400000, 0x20004000, 0x20000000, 0x00004010, 0x20000010, 0x20404010, 0x00404000, 0x20400000,
       0x00404010, 0x20404000, 0x00000000, 0x20400010, 0x00000010, 0x00004000, 0x20400000, 0x00404010,
       0x00004000, 0x00400010, 0x20004010, 0x00000000, 0x20404000, 0x20000000, 0x00400010, 0x20004010)
_T6 = (0x00200000, 0x04200002, 0x04000802, 0x00000000, 0x00000800, 0x04000802, 0x00200802, 0x04200800,
       0x04200802, 0x00200000, 0x00000000, 0x04000002, 0x00000002, 0x04000000, 0x04200002, 0x00000802,
       0x04000800, 0x00200802, 0x00200002, 0x04000800, 0x04000002, 0x04200000, 0x04200800, 0x00200002,
       0x04200000, 0x00000800, 0x00000802, 0x04200802, 0x00200800, 0x00000002, 0x04000000, 0x00200800,
       0x04000000, 0x00200800, 0x00200000, 0x04000802, 0x04000802, 0x04200002, 0x04200002, 0x00000002,
       0x00200002, 0x04000000, 0x04000800, 0x00200000, 0x04200800, 0x00000802, 0x00200802, 0x04200800,
       0x00000802, 0x04000002, 0x04200802, 0x04200000, 0x00200800, 0x00000000, 0x00000002, 0x04200802,
       0x00000000, 0x00200802, 0x04200000, 0x00000800, 0x04000002, 0x04000800, 0x00000800, 0x00200002)
_T7 = (0x10001040, 0x00001000, 0x00040000, 0x10041040, 0x10000000, 0x10001040, 0x00000040, 0x10000000,
       0x00040040, 0x10040000, 0x10041040, 0x00041000, 0x10041000, 0x00041040, 0x00001000, 0x00000040,
       0x10040000, 0x10000040, 0x10001000, 0x00001040, 0x00041000, 0x00040040, 0x10040040, 0x10041000,
       0x00001040, 0x00000000, 0x00000000, 0x10040040, 0x10000040, 0x10001000, 0x00041040, 0x00040000,
       0x00041040, 0x00040000, 0x10041000, 0x00001000, 0x00000040, 0x10040040, 0x00001000, 0x00041040,
       0x10001000, 0x00000040, 0x10000040, 0x10040000, 0x10040040, 0x10000000, 0x00040000, 0x10001040,
       0x00000000, 0x10041040, 0x00040040, 0x10000040, 0x10040000, 0x10001000, 0x10001040, 0x00000000,
       0x10041040, 0x00041000, 0x00041000, 0x00001040, 0x00001040, 0x00040040, 0x10000000, 0x10041000)


def _rotl(x: int, n: int) -> int:
    n &= 31
    return ((x << n) | (x >> (32 - n))) & M if n else x


def _rotr(x: int, n: int) -> int:
    n &= 31
    return ((x >> n) | (x << (32 - n))) & M if n else x


def _bswap(x: int) -> int:
    return int.from_bytes((x & M).to_bytes(4, "little"), "big")


def _genseeds() -> list[int]:
    array0 = [0] * 0x38
    for i in range(0x38):
        tmp = (_GENTABLE0[i] - 1) & 0xFF
        array0[i] = 1 if (_GENSUB[tmp >> 3] & _GENTABLE1[tmp & 7]) else 0
    seeds = [0] * 0x30
    for i in range(0x10):
        array1 = [0] * 0x38
        array2 = [0] * 8
        tmp2 = _GENTABLE2[i]
        for j in range(0x38):
            tmp = (tmp2 + j) & 0xFF
            if j > 0x1B:
                if tmp > 0x37:
                    tmp -= 0x1C
            elif tmp > 0x1B:
                tmp -= 0x1C
            array1[j] = array0[tmp]
        for j in range(0x30):
            if array1[_GENTABLE3[j] - 1] == 0:
                continue
            tmp = ((j * 0x2AAB) >> 16) & 0xFF
            array2[tmp] |= _GENTABLE1[j - tmp * 6] >> 2
        seeds[i << 1] = ((array2[0] << 24) | (array2[2] << 16) | (array2[4] << 8) | array2[6]) & M
        seeds[(i << 1) + 1] = ((array2[1] << 24) | (array2[3] << 16) | (array2[5] << 8) | array2[7]) & M
    j = 0x1F
    for i in range(0, 16, 2):
        seeds[i], seeds[j - 1] = seeds[j - 1], seeds[i]
        seeds[i + 1], seeds[j] = seeds[j], seeds[i + 1]
        j -= 2
    return seeds


SEEDS = _genseeds()


def _crc16(codes: list[int]) -> int:
    ret = 0
    for code in codes:
        for i in range(4):
            tmp = ((code >> (i << 3)) ^ ret) & 0xFF
            ret = ((_CRC0[(tmp >> 4) & 0x0F] ^ _CRC1[tmp & 0x0F]) ^ (ret >> 8)) & 0xFFFF
    return ret


def _verify(codes: list[int]) -> int:
    tmp = _crc16(codes)
    return ((tmp >> 12) ^ (tmp >> 8) ^ (tmp >> 4) ^ tmp) & 0x0F


def _unscramble1(addr: int, val: int) -> tuple[int, int]:
    val = _rotl(val, 4)
    tmp = (addr ^ val) & 0xF0F0F0F0
    addr ^= tmp
    val = _rotr(val ^ tmp, 0x14)
    tmp = (addr ^ val) & 0xFFFF0000
    addr ^= tmp
    val = _rotr(val ^ tmp, 0x12)
    tmp = (addr ^ val) & 0x33333333
    addr ^= tmp
    val = _rotr(val ^ tmp, 6)
    tmp = (addr ^ val) & 0x00FF00FF
    addr ^= tmp
    val = _rotl(val ^ tmp, 9)
    tmp = (addr ^ val) & 0xAAAAAAAA
    addr = _rotl(addr ^ tmp, 1)
    val ^= tmp
    return addr & M, val & M


def _unscramble2(addr: int, val: int) -> tuple[int, int]:
    val = _rotr(val, 1)
    tmp = (addr ^ val) & 0xAAAAAAAA
    val ^= tmp
    addr = _rotr(addr ^ tmp, 9)
    tmp = (addr ^ val) & 0x00FF00FF
    val ^= tmp
    addr = _rotl(addr ^ tmp, 6)
    tmp = (addr ^ val) & 0x33333333
    val ^= tmp
    addr = _rotl(addr ^ tmp, 0x12)
    tmp = (addr ^ val) & 0xFFFF0000
    val ^= tmp
    addr = _rotl(addr ^ tmp, 0x14)
    tmp = (addr ^ val) & 0xF0F0F0F0
    val ^= tmp
    addr = _rotr(addr ^ tmp, 4)
    return addr & M, val & M


def _mix(x: int, y: int) -> int:
    return (_T6[x & 0x3F] ^ _T4[(x >> 8) & 0x3F] ^ _T2[(x >> 16) & 0x3F] ^ _T0[(x >> 24) & 0x3F]
            ^ _T7[y & 0x3F] ^ _T5[(y >> 8) & 0x3F] ^ _T3[(y >> 16) & 0x3F] ^ _T1[(y >> 24) & 0x3F]) & M


def _decrypt_pair(a: int, b: int) -> tuple[int, int]:
    addr, val = _bswap(a), _bswap(b)
    addr, val = _unscramble1(addr, val)
    i = 0
    while i < 32:
        tmp, tmp2 = _rotr(val, 4) ^ SEEDS[i], val ^ SEEDS[i + 1]
        addr ^= _mix(tmp, tmp2)
        tmp, tmp2 = _rotr(addr, 4) ^ SEEDS[i + 2], addr ^ SEEDS[i + 3]
        val ^= _mix(tmp, tmp2)
        i += 4
    addr, val = _unscramble2(addr, val)
    return _bswap(val), _bswap(addr)           # SetCode(code, val, addr): the pair comes back swapped


def _getval(ch: str) -> int:
    idx = FILTER.find(ch.upper())
    if idx < 0:
        raise ValueError(f"not an Action Replay code character: {ch!r}")
    return {32: 1, 33: 1, 34: 0, 35: 5}.get(idx, idx)


def _alpha_to_binary(lines: list[str]) -> list[int]:
    out = []
    for n, raw in enumerate(lines):
        line = raw.replace("-", "").strip().upper()
        if len(line) != 13:
            raise ValueError(f"line {n + 1}: an encrypted Action Replay code has 13 characters: {raw!r}")
        a = _getval(line[6]) >> 3
        b = _getval(line[12]) >> 1
        for i in range(6):
            a |= _getval(line[i]) << ((5 - i) * 5 + 2)
            b |= _getval(line[i + 6]) << ((5 - i) * 5 + 4)
        a, b = a & M, b & M
        if (bin(a ^ b).count("1") & 1) != (_getval(line[12]) & 1):
            raise ValueError(f"line {n + 1}: parity check failed (a character is wrong): {raw!r}")
        out += [a, b]
    return out


def _bits(ctrl: list[int], length: int) -> int:
    """GetBitString over the first word (ctrl = [word, 0, bit, size]); the stream never crosses the first word here."""
    out = 0
    for _ in range(length):
        if ctrl[2] > 0x1F:
            ctrl[2] = 0
            ctrl[1] += 1
        if ctrl[1] >= ctrl[3]:
            return out
        out = ((out << 1) | ((ctrl[0] >> (0x1F - ctrl[2])) & 1)) & M
        ctrl[2] += 1
    return out


def is_encrypted(line: str) -> bool:
    return bool(ENCRYPTED.match(line.strip()))


def decrypt(lines: list[str]) -> dict:
    """One published code (its lines in order, the first being the verification line) -> raw pairs.

    {'codes': [(addr, value)...], 'raw': ['04XXXXXX YYYYYYYY'...], 'verified': bool, 'game_id': int|None,
     'region': int|None, 'master': bool}. verified=False means the batch CRC did not match (a wrong or missing
    verification line): the pairs are still returned, as Dolphin does, but are not to be trusted."""
    words = _alpha_to_binary([ln for ln in lines if ln.strip()])
    if not words:
        raise ValueError("no code lines")
    codes = []
    for i in range(0, len(words), 2):
        codes += list(_decrypt_pair(words[i], words[i + 1]))
    head = codes[0]
    codes[0] &= 0x0FFFFFFF
    verified = (head >> 28) == _verify(codes)
    info = {"verified": verified, "game_id": None, "region": None, "master": False}
    if verified:
        ctrl = [codes[0], 0, 4, len(codes)]
        info["game_id"] = _bits(ctrl, 11)
        _bits(ctrl, 17)                                   # code id
        info["master"] = bool(_bits(ctrl, 1))
        _bits(ctrl, 1)
        info["region"] = _bits(ctrl, 2)
        pairs = [(codes[i], codes[i + 1]) for i in range(2, len(codes), 2)]
    else:
        pairs = [(codes[i], codes[i + 1]) for i in range(0, len(codes), 2)]
    return info | {"codes": pairs, "raw": [f"{a:08X} {v:08X}" for a, v in pairs]}
