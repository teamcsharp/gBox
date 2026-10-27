from types import SimpleNamespace

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


def re6_game(**kw):
    return {'game_id': S.RE6_GAME_ID, 'platform': 'switch', 'title': 'Resident Evil 6',
            'launch': {'kind': 'emulator', 'platform': 'switch',
                       'path': '/x/Resident Evil 6/Resident Evil 6 [01002A000CD48000].nsp'}} | kw


def test_re6_switch_is_pinned_with_a_verified_post_launch_ram_profile():
    assert S.RE6_GAME_ID == '115f9cdbba115432' and S.RE6_UPDATE_GAME_ID == '5d50031f5c8057b1'   # the catalog ids
    for game in (re6_game(), re6_game(serial='0x01002a000cd48000'), re6_game(title='Biohazard 6')):
        info = S.capabilities(game)
        assert info['edition'] == 're6' and info['no_mercy_in_release']
        assert info['unlock_on_load']['available'] and info['unlock_on_load']['needed']
        assert info['autoplay']['available'] is True and info['autoplay']['driver'] == 'gbox.mercs.titles.re6_switch'
    profile = game_unlocks.profile_for(re6_game())
    assert profile['verified'] is True and profile['status'] == 'verified_profile'
    assert profile['apply'] == game_unlocks.POST_LAUNCH_RAM and profile['profile'] == 're6-switch-prologue-gate-ram-v1'
    ev = profile['evidence']
    assert ev['main_build_id'] == '061D2A06CD700785E987C42CE2D72231' and ev['update']['version'] == 131072
    assert set(ev['routines']) >= {'title_gate', 'native_setter', 'extra_content_enable'}


def test_re6_update_nsp_and_other_titles_are_not_editions():
    assert S.capabilities(re6_game(game_id=S.RE6_UPDATE_GAME_ID)) is None
    assert S.capabilities(re6_game(serial='01002A000CD48800')) is None   # the update's own title id
    assert S.capabilities(re6_game(platform='ps3')) is None
    assert S.capabilities(re6_game(title='Resident Evil 6 Origins', serial='')) is None
    assert S.capabilities(re6_game(serial=S.RE5_TITLE_ID))['edition'] == 're5'    # the title id decides


def test_re6_switch_pre_launch_arms_and_never_writes(monkeypatch):
    ctx = SimpleNamespace(server='', headers={}, config=SimpleNamespace(granted_permissions=['memory_write']))
    out = game_unlocks.pre_launch(re6_game(), ctx)
    assert out['state'] == 'armed' and out['applied'] is False and out['apply'] == 'post_launch_ram'


def test_re6_switch_session_start_watches_only_with_memory_access_and_permission(monkeypatch):
    started = []
    eden = SimpleNamespace(name='eden', supported={'read_memory', 'write_memory'}, _guest=lambda: None)
    ctx = SimpleNamespace(server='', headers={}, config=SimpleNamespace(granted_permissions=['memory_write']))
    out = game_unlocks.session_start('w-1', re6_game(), eden, ctx, start_watch=lambda ad, on_done: started.append(on_done))
    assert out['state'] == 'watching' and len(started) == 1 and game_unlocks.WATCHES['w-1']['state'] == 'watching'
    started[0]({'state': 'applied', 'writes': [{}, {}]})
    assert game_unlocks.WATCHES['w-1']['state'] == 'applied'
    no_perm = SimpleNamespace(server='', headers={}, config=SimpleNamespace(granted_permissions=['read']))
    assert game_unlocks.session_start('w-2', re6_game(), eden, no_perm)['state'] == 'permission_required'
    yuzu = SimpleNamespace(name='yuzu', supported={'launch_game'})
    assert game_unlocks.session_start('w-3', re6_game(), yuzu, ctx)['state'] == 'unsupported'
    re5 = {'game_id': S.RE5_GAME_ID, 'platform': 'switch', 'title': 'Resident Evil 5'}
    assert game_unlocks.session_start('w-4', re5, eden, ctx) is None
    assert game_unlocks.session_start('w-5', {'game_id': 'x', 'platform': 'ps3', 'title': 'Halo'}, eden, ctx) is None
    assert len(started) == 1


def test_re6_switch_operator_opt_out_is_authoritative(monkeypatch):
    from gbox import re6_tool
    monkeypatch.setattr(re6_tool, 'settings', lambda server, headers: {'everything_unlocked': False})
    ctx = SimpleNamespace(server='http://cp', headers={}, config=SimpleNamespace(granted_permissions=['memory_write']))
    eden = SimpleNamespace(name='eden', supported={'read_memory', 'write_memory'}, _guest=lambda: None)
    assert game_unlocks.pre_launch(re6_game(), ctx)['state'] == 'disabled'
    assert game_unlocks.session_start('w-6', re6_game(), eden, ctx,
                                      start_watch=lambda *a, **k: pytest.fail('must not start'))['state'] == 'disabled'
