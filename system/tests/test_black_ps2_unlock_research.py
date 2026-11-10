import os
import struct

import pytest
from gbox import black_ps2_unlock_research as B

ELF = os.path.join(os.path.expanduser('~'), 'gBox/system/gbox-data/analysis/re', B.GAME_ID, 'SLUS_213.76.elf')


def fake_elf(strings):
    body = b'\0'.join(strings) + b'\0'
    hdr = bytearray(0x34 + 32)
    hdr[:4] = b'\x7fELF'
    struct.pack_into('<I', hdr, 0x1c, 0x34)
    struct.pack_into('<HH', hdr, 0x2a, 32, 1)
    struct.pack_into('<IIIIIIII', hdr, 0x34, 1, 0x54, 0x100000, 0, len(body), len(body), 5, 16)
    return bytes(hdr) + body


def test_symbols_get_virtual_addresses_and_weapon_list():
    d = fake_elf([b'junkjunk', b'FEAK47IsUnlocked', b'FEUziIsUnlocked', b'FE_LOCKED'])
    s = B.unlock_symbols(d)
    assert s['FEAK47IsUnlocked'] == 0x100000 + 9
    assert B.weapons_unlockable(s) == ['AK47', 'Uzi']
    assert B.report(d)['runtime_verified'] is False and not B.report(d)['anchors_ok']


def test_non_elf_rejected():
    with pytest.raises(ValueError):
        B.unlock_symbols(b'nope' * 20)


@pytest.mark.skipif(not os.path.exists(ELF), reason='owned Black ELF not present')
def test_owned_black_elf_anchors():
    d = open(ELF, 'rb').read()
    r = B.report(d)
    assert r['sha256'] == B.ELF_SHA256 and r['anchors_ok']
    assert len(r['unlockable_weapons']) == 16
