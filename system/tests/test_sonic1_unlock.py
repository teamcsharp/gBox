import zipfile
from pathlib import Path

import pytest

from gbox import game_unlocks as GU, sonic1_unlock as U

REAL = Path.home() / 'gBox_alt/gbox-cache/1fff93531f10c256/source.zip'
GAME = {'game_id': U.GAME_ID, 'platform': 'genesis'}


def _rom():
    if not REAL.is_file():
        pytest.skip('owned ROM not present')
    return zipfile.ZipFile(REAL).read('Shadow In Sonic 1.bin')


def test_guard_accepts_the_owned_rom_and_refuses_moved_engine():
    rom = _rom()
    g = U.guard(rom)
    assert g['ok'] and g['exact'] and g['sha256'] == U.ROM_SHA256
    bad = bytearray(rom)
    bad[0x33AA] = 0
    out = U.guard(bytes(bad))
    assert not out['ok'] and not out['exact'] and 'f_levselcheat' in out['problems'][0]
    assert not U.guard(rom[:1000])['ok']


def test_ops_are_four_monotonic_ram_byte_writes():
    ops = U.unlock_ops()
    assert [o['address'] for o in ops] == [0xFFFFE0, 0xFFFFE1, 0xFFFFE2, 0xFFFFE3]
    assert all(o['hex_bytes'] == '01' and o['width'] == 1 and not o['gameplay_verified'] for o in ops)


def test_levelselect_table_lists_every_zone_and_sound_test():
    entries = U.levelselect_entries(_rom())
    assert entries[0] == (0, 0) and entries[-1] == (0x80, 0) and (7, 0) in entries and len(entries) == 21


def test_inventory_covers_every_category_without_claiming_runtime_proof():
    inv = U.inventory()
    assert set(inv) == set(U.CATEGORIES)
    assert U.profile()['verified'] is False


def test_game_unlocks_registration_is_honestly_pending():
    assert GU.profile_for(GAME)['verified'] is False
    assert GU.profile_for(GAME)['status'] == 'candidate_pending_verification'
    out = GU.pre_launch(GAME, None)
    assert out['state'] == 'candidate_pending_verification' and out['applied'] is False
    assert GU.profile_for(GAME | {'platform': 'nds'})['status'] == 'unsupported'
