import pytest

from gbox import game_unlocks, re_switch as S


def test_pinned_switch_no_mercy_has_its_own_driver_not_the_ps3_one():
    game = {'game_id': S.RE5_GAME_ID, 'platform': 'switch', 'serial': '0x010018100cd46000', 'title': 'Resident Evil 5'}
    info = S.capabilities(game)
    assert info['serial'] == S.RE5_TITLE_ID and info['no_mercy_in_release']
    assert info['autoplay']['available'] and info['autoplay']['driver'] == 'gbox.mercs.titles.re5_switch'
    assert not info['unlock_on_load']['available'] and info['unlock_on_load']['needed'] is False
    assert info['evidence']['main_build_id'] == 'EBFFDB223149A725A93CD9B60979F6AA'
    assert S.RE5_GAME_ID == '52d15709be0fda1a'                    # the catalog id of the share's NSP
    profile = game_unlocks.profile_for(game)
    assert profile['platform'] == 'switch' and profile['verified'] is False


def test_preference_is_explicit_and_host_settings_are_unchanged():
    native = {'platform': 'ps3', 'playable': True}
    assert S.preferred_spec('re5', native, {}) is native
    preferred = {'re5': {'platform': 'switch', 'mode': 'no_mercy', 'title_id': S.RE5_TITLE_ID}}
    spec = S.preferred_spec('re5', native, {'preferred_editions': preferred})
    assert spec['platform'] == 'switch' and spec['playable'] is True and 'reason' not in spec
    assert spec['modes'] == ['no_mercy'] and spec['map_id'] == S.RE5_TITLE_ID != 'BLUS30491'
    assert spec['game_ids'] == (S.RE5_GAME_ID,) and spec['driver'] == 'gbox.mercs.titles.re5_switch'
    assert S.normalize_preferences(preferred) == preferred
    assert native == {'platform': 'ps3', 'playable': True}


@pytest.mark.parametrize('value', [None, [], {'re6': {}}, {'re5': {'platform': 'ps4'}},
                                  {'re5': {'platform': 'switch', 'mode': 'no_mercy', 'title_id': 'BAD'}}])
def test_unverified_preferences_are_not_accepted(value):
    with pytest.raises(ValueError):
        S.normalize_preferences(value)


def test_unrelated_platform_or_title_is_not_matched():
    assert S.capabilities({'platform': 'ps3', 'title': 'Resident Evil 5'}) is None
    assert S.capabilities({'platform': 'switch', 'title': 'Resident Evil 50'}) is None
