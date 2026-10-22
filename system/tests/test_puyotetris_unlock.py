"""Honesty guards for the Puyo Puyo Tetris (USA, Switch) registration (#2221)."""
from types import SimpleNamespace

import pytest

from gbox import game_unlocks as G, puyotetris_unlock as P

REV = 'a' * 64


def teardown_function(_):
    P.PROVEN_REVISIONS.clear()
    for c in P.INVENTORY:
        P.INVENTORY[c] = []


def test_profile_unverified_without_evidence():
    p = P.profile()
    assert p['verified'] is False and p['complete_unlock_profile'] is False
    assert p['proven_revisions'] == [] and set(p['inventory']) == set(P.CATEGORIES)


def test_pre_launch_never_applies():
    r = G.pre_launch({'game_id': G.PUYOTETRIS_ID, 'platform': 'switch'}, SimpleNamespace())
    assert r['applied'] is False and r['state'] == 'research_pending'
    assert r['proven_revisions'] == []


def test_same_id_other_platform_not_routed():
    r = G.pre_launch({'game_id': G.PUYOTETRIS_ID, 'platform': 'ps4'}, SimpleNamespace())
    assert 'proven_revisions' not in r and r['applied'] is False


def test_revision_guard_rejects_unproven_and_malformed():
    assert P.revision_guard(REV)['ok'] is False
    assert P.revision_guard('xx' * 32)['ok'] is False
    P.PROVEN_REVISIONS[REV] = {'artifact': 'art1'}
    assert P.revision_guard(REV.upper())['ok'] is True


def test_entry_needs_evidence_on_proven_revision():
    with pytest.raises(ValueError):
        P.add_entry('characters', 'Arle', 'unlocked', 'art1', REV)
    P.PROVEN_REVISIONS[REV] = {'artifact': 'art1'}
    assert P.add_entry('characters', 'Arle', 'unlocked', 'art1', REV)['status'] == 'unlocked'
    P.add_entry('modes', 'Swap', 'unknown', None)
    assert P.profile()['unknown_counts']['modes'] == 1
    with pytest.raises(ValueError):
        P.add_entry('bogus', 'x', 'unknown', None)
