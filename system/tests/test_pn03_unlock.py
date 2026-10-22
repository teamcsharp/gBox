"""Focused tests for the P.N. 03 (USA) / GPNE08 unlock research profile."""
import hashlib

from gbox import game_unlocks
from gbox import pn03_unlock

GAME = {'game_id': pn03_unlock.GAME_ID, 'platform': pn03_unlock.PLATFORM,
        'title': pn03_unlock.TITLE}


def test_owned_disc_identity_is_pinned():
    ev = pn03_unlock.disc_evidence()
    assert ev['disc_id'] == 'GPNE08'
    assert ev['game_id'] == '0369bdbf9347869a'
    assert ev['platform'] == 'gamecube'
    assert len(ev['main_dol_sha256']) == 64
    assert ev['main_dol_size'] == 1593280
    assert ev['main_elf_sha256'] != ev['main_dol_sha256']


def test_revision_guard_accepts_only_the_owned_dol():
    assert pn03_unlock.revision_ok(b'\x00' * pn03_unlock.MAIN_DOL_SIZE) is False
    assert pn03_unlock.revision_ok(b'not the dol') is False
    # the pinned digest is the one the profile was researched against
    assert hashlib.sha256(b'x').hexdigest() != pn03_unlock.MAIN_DOL_SHA256


def test_profile_is_unverified_and_states_its_reason():
    prof = pn03_unlock.profile()
    assert prof['verified'] is False
    assert prof['status'] == 'research_pending'
    assert prof['game_id'] == pn03_unlock.GAME_ID
    assert prof['disc_id'] == 'GPNE08'
    assert prof['reason']
    assert prof['save_effect'].startswith('None')


def test_profile_for_registers_the_exact_game():
    prof = game_unlocks.profile_for(GAME)
    assert prof['verified'] is False
    assert prof['profile'] == 'pn03-gc-revision-guard-v1'
    assert prof['game_id'] == pn03_unlock.GAME_ID
    assert prof['status'] == 'research_pending'


def test_pre_launch_never_writes_for_this_game():
    result = game_unlocks.pre_launch(GAME, None)
    assert result.get('applied') is False
    assert result.get('state') in ('research_pending', 'implementation_pending')


def test_inventory_covers_every_operator_category():
    inv = pn03_unlock.inventory()
    assert set(inv) == set(pn03_unlock.CATEGORIES)
    for name, entry in inv.items():
        assert entry['status'] in ('unknown', 'present_on_disc_unverified', 'not_present')
        assert entry['evidence']
        assert isinstance(entry['entries'], list)


def test_save_tables_are_real_disc_files_with_evidence():
    tables = pn03_unlock.save_tables()
    names = {t['file'] for t in tables}
    assert {'etc/card.dat', 'etc/continue.dat', 'etc/title.dat',
            'etc/allResult.dat', 'etc/result00.dat'} <= names
    card = next(t for t in tables if t['file'] == 'etc/card.dat')
    cont = next(t for t in tables if t['file'] == 'etc/continue.dat')
    assert card['loader'] == 'FUN_8001c5ac'
    assert cont['loader'] == 'FUN_8007a290'
    assert '0x104' in card['load_call']


def test_no_unlock_write_ops_are_advertised():
    assert pn03_unlock.unlock_ops() == []
