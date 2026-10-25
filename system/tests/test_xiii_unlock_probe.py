"""Focused checks for the XIII (USA) unlock probe (gamecode GX3E41)."""
import hashlib
import os

import pytest

from gbox import game_unlocks
from gbox import xiii_unlock_probe as probe

ROM = ('/mnt/gbox/hyperspin/Arcade/collections/Nintendo GameCube/roms/'
       'XIII (USA).gcz')


def test_config_digests_match_pinned_revision():
    for name in ('System/MSL.ini', 'System/custom.txt'):
        assert probe.config_ok(name), name
        assert probe.config_digest(name) == probe.CONFIG_SHA256[name]


def test_character_inventory_matches_disc_config():
    inv = probe.character_inventory()
    assert len(inv) == 10
    assert [c['name'] for c in inv] == ['XIII', 'Shinyaku', 'Trystan', 'Carrington',
                                        'John', 'Densetsu', 'Roger', 'Robert',
                                        'Armael', 'Mongoose']
    assert [c['code'] for c in inv] == ['S13M', 'DANH', 'SCAN', 'CARR', 'GAMI',
                                        'NIHE', 'FR1M', 'FR2M', 'RAST', 'MONG']
    assert all(c['skin'].startswith('XIIIPersos.') for c in inv)
    assert all(isinstance(c['code_mesh'], int) for c in inv)


def test_map_inventory_matches_disc_config():
    maps = probe.map_inventory()
    assert len(maps['solo']) == 35
    assert len(maps['multi']) == 23
    assert maps['solo'][0]['name'] == 'mapmenu'
    assert maps['solo'][-1]['name'] == 'usa02'
    assert maps['multi'][0]['name'] == 'ctf_base'
    assert maps['multi'][-1]['name'] == 'dm_warehouse'


def test_category_inventory_covers_roster_and_levels():
    inv = probe.category_inventory()
    assert inv['characters'] == 10
    assert inv['levels'] == 58
    assert inv['modes'] == 23


def test_save_surface_is_named_not_written():
    assert probe.save_name_pattern() == 'Save%i.usa'
    assert 'Save%i.usa' in probe.DOL_STRING_OFFSETS
    for key in ('profilestats', 'SavePath', 'SaveExt', 'SaveBind'):
        assert key in probe.DOL_STRING_OFFSETS


def test_profile_gate_is_honest_and_unverified():
    gate = probe.profile_gate()
    assert gate['verified'] is False
    assert gate['categories'] == list(probe.CATEGORIES)
    assert gate['blockers'] and gate['next']
    assert probe.DOL_SHA256 in gate['evidence']['executable']


def test_game_unlocks_registers_xiii_without_a_writer():
    game = {'game_id': probe.GAME_ID, 'platform': probe.PLATFORM}
    profile = game_unlocks.profile_for(game)
    assert profile['verified'] is False
    assert profile['status'] == 'pending_research'
    assert profile['scope'] == list(probe.CATEGORIES)
    launch = game_unlocks.pre_launch(game, None)
    assert launch['applied'] is False
    assert launch['state'] == 'research_pending'


def test_dol_strings_verified_against_owned_disc():
    if not os.path.exists(ROM):
        pytest.skip('owned XIII disc not mounted')
    from gbox.gcdisc import GCDisc
    data = GCDisc(ROM).dol()
    assert len(data) == probe.DOL_SIZE
    assert hashlib.sha256(data).hexdigest() == probe.DOL_SHA256
    for name, offsets in probe.DOL_STRING_OFFSETS.items():
        for offset in offsets:
            assert data[offset:offset + len(name)] == name.encode()
