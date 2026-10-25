"""Focused tests for the Sonic Heroes (USA) unlock research evidence."""
import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ELF = Path('/home/ehm_eckx/gBox/system/gbox-data/analysis/re/f2c5f36ae6845713/main.dol.elf')


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sh = _load('sonic_heroes_unlock', ROOT / 'gbox' / 'sonic_heroes_unlock.py')


def _elf():
    if not ELF.is_file():
        pytest.skip('owned executable is not present on this host')
    return ELF.read_bytes()


def test_pinned_revision_matches_the_owned_executable():
    data = _elf()
    assert hashlib.sha256(data).hexdigest() == sh.EXECUTABLE_SHA256
    assert sh.GAME_ID == 'f2c5f36ae6845713'
    assert sh.PLATFORM == 'gamecube'


def test_elf_layout_is_32_bit_big_endian_with_a_loadable_text_segment():
    segs = sh.segments(_elf())
    assert segs
    text = [s for s in segs if s['vaddr'] == 0x80011c20]
    assert text and text[0]['filesz'] > 0x100000


def test_stage_identifier_table_is_inventoried():
    names = sorted(set(sh.stage_names(_elf()).values()))
    assert len(names) == 46
    for expected in ('ACTIONSTAGE_PRACTICE_00', 'ACTIONSTAGE_SKYEGG2_14',
                     'BOSSSTAGE_EGGHAWK_20', 'BOSSSTAGE_LASTBOSS2ND_28',
                     'TUTORIALSTAGE_29', 'SPECIALSTAGE_46', 'BOUNUSSTAGE_89'):
        assert expected in names


def test_inventory_marks_unproved_categories_unknown():
    inv = sh.content_inventory(_elf())
    assert inv['revision_matches_pin'] is True
    assert inv['categories']['stages']['status'] == 'present_in_binary'
    assert inv['categories']['stages']['count'] == 46
    for name in sh.CATEGORIES:
        assert name in inv['categories']
    for name in ('characters', 'hidden_characters', 'modes', 'costumes'):
        assert inv['categories'][name]['status'] == 'unknown'
    assert inv['unlock_targets'] == []


def test_profile_is_honest_about_unproven_locks():
    prof = sh.profile()
    assert prof['verified'] is False
    assert prof['status'] == 'pending_research'
    assert prof['reason']
    assert prof['scope'] == list(sh.CATEGORIES)


def test_game_unlocks_routes_this_game_to_pending_research():
    sys.path.insert(0, str(ROOT))
    try:
        from gbox import game_unlocks
    except Exception as exc:                       # pragma: no cover - package import guard
        pytest.skip(f'gbox package is not importable here: {exc}')
    game = {'game_id': sh.GAME_ID, 'platform': sh.PLATFORM}
    prof = game_unlocks.profile_for(game)
    assert prof['verified'] is False
    assert prof['status'] == 'pending_research'
    assert prof['executable_sha256'] == sh.EXECUTABLE_SHA256
    hook = game_unlocks.pre_launch(game, None)
    assert hook['applied'] is False
    assert hook['state'] == 'research_pending'
