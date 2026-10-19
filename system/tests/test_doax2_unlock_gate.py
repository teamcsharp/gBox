from types import SimpleNamespace

import pytest
from gbox import game_unlocks as G, doax2_unlock as D


DOAX2 = {'game_id': D.GAME_ID, 'platform': D.PLATFORM}


def test_doax2_gate_reports_pending_honestly_and_never_verified():
    profile = G.profile_for(DOAX2)
    assert profile['verified'] is False and profile['status'] == 'pending_research'
    assert profile['game_id'] == D.GAME_ID and profile['requires']
    # The gate carries the evidence chain a future promotion must satisfy.
    assert 'owned_executable_sha256' in profile['requires']
    assert 'native_unlock_routine' in profile['requires']


def test_doax2_pre_launch_and_launch_plan_reach_no_writer():
    # No REA/Ghidra/memory writer may be reachable for an unverified revision.
    result = G.pre_launch(DOAX2, SimpleNamespace())
    assert result['applied'] is False and result['state'] == 'research_pending'
    worker = {'id': 'w' * 16, 'name': 'JAYBUILTFINALE'}
    plan = G.launch_plan(DOAX2, worker, enable_unlock=True, allow_save_upgrade=True)
    assert plan['status'] == 'unsupported_unlock' and plan['jobs'] == [] and plan['executed'] is False


def test_doax2_gate_cannot_be_bypassed_by_a_similar_title_string():
    for game in ({'title': 'Dead Or Alive - Xtreme 2'},
                 {'game_id': D.GAME_ID, 'platform': 'xbox'},
                 {'game_id': 'e50f98c6e603dab5', 'platform': 'xbox360'}):
        assert G.profile_for(game)['verified'] is False


def test_gate_has_no_write_targets_and_pins_identity():
    gate = D.profile_gate()
    assert gate['verified'] is False and gate['status'] == 'pending_research'
    text = repr(gate).lower()
    assert '0x' not in text  # no memory addresses staged as if verified
    assert D.GAME_ID == 'e50f98c6e603dab4' and D.PLATFORM == 'xbox360'
