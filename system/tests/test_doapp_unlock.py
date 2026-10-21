"""Focused tests for the DOA++ (Korea) arcade unlock registration (request #2088).

These guard the honesty rules: nothing may be reported verified or applied
without recorded REA/Ghidra evidence on an exact revision hash.
"""
from types import SimpleNamespace

import pytest

from gbox import doapp_unlock as D, game_unlocks as G

REV = 'a' * 64


def teardown_function(_):
    D.PROVEN_REVISIONS.clear()
    for category in D.INVENTORY:
        D.INVENTORY[category] = []


def test_profile_is_honest_before_any_evidence():
    p = D.profile()
    assert p['game_id'] == D.GAME_ID and p['platform'] == 'arcade'
    assert p['verified'] is False and p['complete_unlock_profile'] is False
    assert p['proven_revisions'] == []
    assert set(p['inventory']) == set(D.CATEGORIES)


def test_pre_launch_never_applies_for_the_arcade_title():
    result = G.pre_launch({'game_id': G.DOAPP_ID, 'platform': 'arcade'},
                          SimpleNamespace())
    assert result['applied'] is False
    assert result['state'] == 'research_pending'
    assert result['proven_revisions'] == []


def test_pre_launch_for_other_games_unchanged():
    result = G.pre_launch({'game_id': 'f' * 16, 'platform': 'arcade'},
                          SimpleNamespace())
    assert result == {'state': 'research_pending', 'applied': False,
                      'reason': result['reason']}


def test_write_plan_refused_without_proven_revision():
    errors = D.validate_write([('w', 0x2000, b'\x01\x00')], REV)
    assert any('binary_session' in e for e in errors)


def test_write_plan_bounds():
    D.accept_revision(REV, 'rea-artifact-1', {})
    assert D.validate_write([('w', 0x2000, b'\x01\x00')], REV) == []
    assert D.validate_write([('r', 0x2000, b'\x01')], REV)  # unsupported op
    assert D.validate_write([('w', 0x2000, b'')], REV)      # empty write
    assert D.validate_write([('w', 0x2000, b'\x01' * 5)], REV)
    assert D.validate_write([('w', 0x0800_0000, b'\x01')], REV)


def test_accept_revision_rejects_bad_input():
    with pytest.raises(ValueError):
        D.accept_revision('nope', 'art', {})
    with pytest.raises(ValueError):
        D.accept_revision(REV, ' ', {})
    with pytest.raises(ValueError):
        D.accept_revision(REV, 'art', {'bogus_category': []})
    with pytest.raises(ValueError):  # claims need evidence
        D.accept_revision(REV, 'art',
                          {'characters': [{'name': 'Kasumi', 'status': 'unlocked'}]})
    with pytest.raises(ValueError):
        D.accept_revision(REV, 'art',
                          {'characters': [{'name': 'Kasumi', 'status': 'maybe'}]})


def test_accept_revision_records_evidence_and_dedupes_names():
    out = D.accept_revision(REV, 'rea-42', {
        'characters': [{'name': 'Kasumi', 'status': 'unlocked',
                        'evidence': 'ghidra:lock_check_0x1000'}],
        'hidden_characters': [{'name': 'Leif', 'status': 'unknown'}],
    })
    assert out['verified'] is False and out['recorded'] == REV
    p = D.profile()
    assert p['proven_revisions'] == [REV]
    assert p['inventory']['characters'][0]['name'] == 'Kasumi'
    assert p['unknown_counts']['hidden_characters'] == 1
    # replacing an entry by name keeps the inventory unique
    D.accept_revision(REV, 'rea-42', {
        'characters': [{'name': 'Kasumi', 'status': 'not_present',
                        'evidence': 'rea:roster_scan'}]})
    assert len(D.profile()['inventory']['characters']) == 1
    assert D.profile()['inventory']['characters'][0]['status'] == 'not_present'
