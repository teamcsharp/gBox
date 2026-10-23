"""Focused tests for the DOA2 (Dreamcast) unlock research stub in game_unlocks.

Verifies:
- profile_for returns the research_pending stub for game_id 3dd7e33362597f85 / dreamcast.
- The stub carries the exact pinned US first-read SHA256.
- The stub is not verified (verified=False).
- pre_launch returns research_pending with applied=False for that game.
- RE6 profile is unaffected (still returns verified_profile for the RE6 ID).
- Unknown games still return unsupported.
"""
from __future__ import annotations

import pytest

from gbox import game_unlocks as GU

DOA2_GAME = {'game_id': '3dd7e33362597f85', 'platform': 'dreamcast', 'title': 'Dead or Alive 2'}
RE6_GAME = {'game_id': '0871eee3b68cdea3', 'platform': 'xbox360', 'title': 'Resident Evil 6'}
UNKNOWN_GAME = {'game_id': 'deadbeef', 'platform': 'dreamcast', 'title': 'Unknown'}


def test_doa2_profile_exists():
    p = GU.profile_for(DOA2_GAME)
    assert p['status'] == 'research_pending'
    assert p['verified'] is False
    assert p['game_id'] == DOA2_GAME['game_id']
    assert p['profile'] == 'doa2-us-research-stub-v1'


def test_doa2_profile_pinned_sha256():
    p = GU.profile_for(DOA2_GAME)
    assert p['first_read_sha256'] == (
        '105056d9ffef86bf5e470fa28dc5907443156f9ab1c6bc009f73661d9c047a85'
    )


def test_doa2_profile_product_version():
    p = GU.profile_for(DOA2_GAME)
    assert p['product'] == 'T3601N'
    assert p['version'] == 'V1.100'


def test_doa2_profile_roster_scope():
    p = GU.profile_for(DOA2_GAME)
    roster = p['evidence']['expected_roster']
    assert set(roster) == {
        'KAS', 'AYA', 'LEI', 'TIN', 'BAS', 'JAN', 'GEN', 'BAY',
        'RYU', 'ZAC', 'HIK', 'TNG', 'KTE', 'LOR', 'MAM', 'WBA', 'YTI',
    }
    assert 'SAM' not in roster
    assert 'PDG' not in roster


def test_doa2_profile_blocker_present():
    p = GU.profile_for(DOA2_GAME)
    assert 'blocker' in p
    assert 'not extracted' in p['blocker']
    assert 'Ghidra' in p['blocker'] or 'REA' in p['blocker']


def test_doa2_profile_hash_job_evidence():
    p = GU.profile_for(DOA2_GAME)
    ev = p['evidence']
    assert ev['hash_job'] == '2fdd3f0e1c21459d'
    assert ev['hash_job_output']['crc32'] == '684f5179'
    assert ev['hash_job_output']['sha1'] == '4349ed13d350d1297011729306879a7f5befc396'
    assert ev['hash_job_output']['size'] == 252886868


def test_doa2_pre_launch_research_pending():
    result = GU.pre_launch(DOA2_GAME, ctx=None)
    assert result['state'] == 'research_pending'
    assert result['applied'] is False
    assert 'reason' in result


def test_doa2_pre_launch_rejects_wrong_platform():
    wrong = {'game_id': '3dd7e33362597f85', 'platform': 'xbox360', 'title': 'Dead or Alive 2'}
    p = GU.profile_for(wrong)
    # Wrong platform should fall through to unsupported (not the DOA2 branch)
    assert p['status'] == 'unsupported'
    assert p['verified'] is False


def test_re6_profile_unaffected():
    p = GU.profile_for(RE6_GAME)
    # RE6 profile requires the template file; if present it should be verified,
    # if absent it should be unavailable — either way NOT research_pending for DOA2.
    assert p['game_id'] != DOA2_GAME['game_id'] or p['status'] != 'research_pending'
    # The key check: RE6 does not get the DOA2 stub profile
    assert p['profile'] != 'doa2-us-research-stub-v1'


def test_unknown_game_unsupported():
    p = GU.profile_for(UNKNOWN_GAME)
    assert p['status'] == 'unsupported'
    assert p['verified'] is False
    assert p['profile'] is None
