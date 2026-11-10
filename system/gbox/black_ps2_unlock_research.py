"""Black (USA, PS2, SLUS-213.76) unlock research: static string-table evidence.

Static only. Locates the front-end unlock/lock/medal/difficulty script symbols in the
boot ELF and reports their virtual addresses. It does not patch anything and is not
runtime acceptance of an unlock-on-load recipe.
"""
import hashlib
import re
import struct

GAME_ID = '858ac1ab12044c9c'
ELF_SHA256 = '141b05209570458af9c8e27ab1911f258da6353909d813cd572df026254ffe4c'
ANCHORS = {
    'FE_CURRENTUNLOCKLEVEL': 0x3fc330,
    'FE_YOUHAVEUNLOCKED': 0x3fc360,
    'FE_LOCKED': 0x3fae60,
    'FELevelUnlocked1': 0x3fac10,
    'FELevelUnlocked8': 0x3facb8,
    'FE_LEVELUNLOCKEDFORMAT': 0x3fc448,
    'FE_UNLOCK_M16A2': 0x3fc438,
    'FEAK47IsUnlocked': 0x3fc768,
    'FEDC3EliteIsUnlocked': 0x3fc8b0,
    'FE_BLACKMEDALAWARDED': 0x3fbb18,
    'FE_DIFFICULTYDESC_BLACK': 0x3fae38,
}
_KEYS = re.compile(rb'(IsUnlocked|unlock|FE_LOCKED|LEVELLOCKED|MEDALAWARDED|FE_DIFFICULTYDESC)', re.I)
_STR = re.compile(rb'[\x20-\x7e]{4,}')


def _segments(d):
    if d[:4] != b'\x7fELF':
        raise ValueError('not an ELF')
    phoff, = struct.unpack_from('<I', d, 0x1c)
    ent, num = struct.unpack_from('<HH', d, 0x2a)
    out = []
    for i in range(num):
        t, off, va, _pa, fs, _ms, _fl, _al = struct.unpack_from('<IIIIIIII', d, phoff + i * ent)
        if t == 1:
            out.append((off, va, fs))
    return out


def unlock_symbols(d):
    segs = _segments(d)
    res = {}
    for m in _STR.finditer(d):
        if not _KEYS.search(m.group()):
            continue
        for off, va, fs in segs:
            if off <= m.start() < off + fs:
                res[m.group().decode()] = va + m.start() - off
                break
    return res


def weapons_unlockable(symbols):
    return sorted(k[2:-10] for k in symbols if k.startswith('FE') and k.endswith('IsUnlocked'))


def report(d):
    sym = unlock_symbols(d)
    return {'game_id': GAME_ID, 'sha256': hashlib.sha256(d).hexdigest(), 'symbols': sym,
            'unlockable_weapons': weapons_unlockable(sym),
            'anchors_ok': all(sym.get(k) == v for k, v in ANCHORS.items()),
            'runtime_verified': False}
