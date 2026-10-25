"""PS4 release content cannot confer Xbox 360 unlock/model-writer support."""
import pytest

from gbox import game_unlocks, re_ps4


@pytest.mark.parametrize('serial,edition,modes', [
    ('CUSA04437', 're5', ['mercenaries_united', 'no_mercy']),
    ('CUSA03856', 're6', ['mercenaries', 'no_mercy']),
])
def test_ps4_release_content_is_separate_from_runtime_capabilities(serial, edition, modes):
    game = {'game_id': 'ps4-game', 'platform': 'ps4', 'serial': serial,
            'launch': {'app_ver': '01.00'}}
    info = re_ps4.capabilities(game)
    assert info['edition'] == edition and info['modes_in_release'] == modes
    assert info['no_mercy_in_release'] and info['app_ver'] == '01.00'
    assert not info['full_playback_verified']
    for operation in ('unlock_on_load', 'autoplay', 'character_replacement'):
        assert info[operation]['available'] is False
    assert info['evidence']['report_serial'] == serial
    assert info['evidence']['runtime_verified_in_gbox'] is False


@pytest.mark.parametrize('title', ['Resident Evil 5', 'RESIDENT EVIL5', 'Resident Evil 6 (USA)', 'BIOHAZARD 6'])
def test_title_identifies_pending_research_only(title):
    profile = game_unlocks.profile_for({'game_id': 'unknown-revision', 'platform': 'ps4', 'title': title})
    assert profile['status'] == 'research_pending' and not profile['verified']
    assert profile['profile'] is None and profile['save_effect'].startswith('None;')


@pytest.mark.parametrize('game', [
    {'platform': 'ps3', 'title': 'Resident Evil 5'},
    {'platform': 'xbox360', 'title': 'Resident Evil 6'},
    {'platform': 'ps4', 'title': 'Resident Evil 50'},
    {'platform': 'ps4', 'title': 'Resident Evil Collection'},
    {'platform': 'ps4', 'title': 'Unknown', 'serial': 'CUSA99999'},
])
def test_unrelated_builds_do_not_inherit_ps4_release_metadata(game):
    assert re_ps4.capabilities(game) is None


def test_ps4_prelaunch_never_uses_x360_writer_even_with_x360_catalog_id(monkeypatch):
    # No context is supplied: a real writer would access it and fail. The PS4
    # launch reports what remains to be verified, and performs no save I/O.
    game = {'game_id': game_unlocks.RE6_ID, 'platform': 'ps4', 'serial': 'CUSA03856'}
    out = game_unlocks.pre_launch(game, None)
    assert out['state'] == 'research_pending' and out['applied'] is False
    assert out['capabilities']['no_mercy_in_release'] is True
    plan = game_unlocks.launch_plan(game, {'id': 'test', 'name': 'JAYBUILTFINALE'},
                                    enable_unlock=True, allow_save_upgrade=True)
    assert plan['status'] == 'unsupported_unlock' and plan['jobs'] == []


def test_x360_re6_retains_exact_profile_and_no_mercy_exclusion():
    profile = game_unlocks.profile_for({'game_id': game_unlocks.RE6_ID, 'platform': 'xbox360'})
    assert profile['verified'] and 'Mercenaries No Mercy' in profile['exclusions']
