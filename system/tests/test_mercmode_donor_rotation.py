"""The MercMode donor rotation (operator 2026-11-10: "continue seeing new and randomized characters from the database
... swapped frequently"): each title block draws a verified donor build from its pool (gbox.donor_rotation)."""
import json
import random

import pytest

from gbox import donor_rejects as R, donor_rotation as DR, donor_swap as D, mercmode as M, screensaver as S
from test_mercmode import rig, boundary

RE4, RE5 = M.TITLES['re4']['game_ids'][0], M.TITLES['re5']['game_ids'][0]


def entry(title, game_id, players=None, enemies=None):
    return {'title': title, 'game_id': game_id,
            'players': {slot: {'donor': donor, 'label': slot, 'verdict': 'pass',
                               'files': [{'path': f'romfs/{slot}.arc', 'size': 10}]}
                        for slot, donor in (players or {}).items()},
            'enemies': {cls: {'donors': list(donors), 'files': [{'path': f'romfs/{cls}.arc', 'size': 10}]}
                        for cls, donors in (enemies or {}).items()}, 'receipts': []}


AUDITED = {
    'cast-a': entry('re5', RE5, {'chris': 'sonic', 'sheva': 'tifa', 'jill': 'aerith'}, {'uEm10': ['mario']}),
    'cast-b': entry('re5', RE5, {'chris': 'goji', 'sheva': 'ryo', 'jill': 'luigi'}, {'uEm10': ['yoshi']}),
    'cast-c': entry('re5', RE5, {'chris': 'knuckles', 'sheva': 'amy'}, {'uEm10': ['peach']}),
    'cast-a-blueprint': entry('re5', RE5, {'chris': 'sonic', 'sheva': 'tifa', 'jill': 'aerith'}, {'uEm10': ['mario']}),
    'cast-a-subset': entry('re5', RE5, {'chris': 'sonic'}),                     # its donors are all in cast-a
    'cast-probe-x': entry('re5', RE5, {'chris': 'bowser'}),                    # an experiment by name
    'cast-bad': entry('re5', RE5, {'chris': 'vincent', 'sheva': 'zelda'}),     # a rejected donor
    'roster-native': entry('re5', RE5, {'chris': 'sheva/Normal'}),             # native costumes only
    'cast-missing': entry('re5', RE5, {'chris': 'link'}),                      # not on this PC
    'other-title': entry('re4', RE4, {'leon': 'cloud'}),
}
ON_PC = ['cast-a', 'cast-a-blueprint', 'cast-b', 'cast-c', 'cast-a-subset', 'cast-probe-x', 'cast-bad', 'roster-native',
         'default-build', 'queued-build', 'other-title']


@pytest.fixture
def rejects(tmp_path, monkeypatch):
    path = tmp_path / 'donor_rejects.json'
    path.write_text(json.dumps({'format': 1, 'titles': {'re5': {'vincent': {'reason': 'oversized', 'codes': ['tall'],
                                                                             'source': {'by': 'audit'}}}},
                                'audited_builds': AUDITED}), encoding='utf-8')
    monkeypatch.setenv(R.ENV, str(path))
    return path


def builds(names=ON_PC):
    return lambda gid: [{'name': n, 'game_id': gid} for n in names]


def re5_rig(**settings):
    store, w, saver, calls, now, tick = rig()
    saver.builds = builds()
    M.configure(store, w['name'], {'enabled': True, 'titles': ['re5'], 'keep_warm': 0, 'rounds_per_title': 5,
                                   'default_mods': {'re5': 'default-build'}, **settings})
    return store, w, saver, calls, now, tick


def up(store, saver, calls, now, tick):
    """The last launch's session is up and its bot started: the run is playing, its autoplay job succeeded."""
    launch = calls[-1]
    assert launch['tool'] == 'launch_game'
    sid = 'w1-' + launch['id']
    store.put('session', sid, {'session_id': sid, 'game_id': launch['input']['game']['game_id'], 'state': 'running'})
    tick(1)
    tick(S.START_GRACE)
    run = store.get(S.STATE, 'lilspark')
    job = store.get('job', run['autoplay_job']) | {'state': 'succeeded'}
    store.put('job', job['id'], job)
    S.telemetry_put(sid, {'running': True, 'stats': {}}, now=now[0])
    return run, job


def play_round(store, saver, now, n, job):
    now[0] += 200
    run = store.get(S.STATE, 'lilspark')
    S.telemetry_put(run['session_id'], {'running': True, 'stats': {}}, now=now[0])
    return saver.round_boundary(boundary(run, now[0]) | {'round_id': f'{n:032x}'}, job, now[0])


# --- settings ---------------------------------------------------------------------------------------------------

def test_settings_default_to_the_pool_and_are_validated():
    cfg = M.normalize({})
    assert cfg['donor_rotation'] == 'pool' and cfg['donor_rounds'] == 0 and cfg['donor_pool'] == {}
    assert M.normalize({'donor_rotation': 'fresh', 'donor_rounds': 2,
                        'donor_pool': {'re5': ['a', 'a', 'b'], 're6': []}})['donor_pool'] == {'re5': ['a', 'b']}
    for bad in ({'donor_rotation': 'random'}, {'donor_rounds': -1}, {'donor_rounds': 21}, {'donor_rounds': True},
                {'donor_pool': {'re9': ['a']}}, {'donor_pool': {'re5': 'a'}}, {'donor_pool': {'re5': ['../x']}}):
        with pytest.raises(ValueError, match='donor'):
            M.normalize(bad)
    assert S.MercModeSettings(host='x', donor_rotation='fresh', donor_rounds=1).donor_rounds == 1


# --- the fit gate and the pool -----------------------------------------------------------------------------------

def test_the_fit_gate_refuses_unaudited_rejected_native_and_foreign_builds(rejects):
    doc = R.load()
    assert DR.fit_gate('re5', 'cast-a', doc, RE5) == (True, '')
    assert DR.fit_gate('re5', 'cast-a-blueprint', doc, RE5)[0]
    assert 'not in the donor fit audit' in DR.fit_gate('re5', 'never-audited', doc)[1]
    assert 'vincent' in DR.fit_gate('re5', 'cast-bad', doc)[1]
    assert 'no library donor' in DR.fit_gate('re5', 'roster-native', doc)[1]
    assert 'audited as a re4 build' in DR.fit_gate('re5', 'other-title', doc)[1]
    refused = dict(doc['audited_builds']['cast-c'])
    refused['players'] = {'chris': {'donor': 'knuckles', 'verdict': 'reject', 'files': []}}
    doc['audited_builds']['cast-c'] = refused
    assert 'refused slot' in DR.fit_gate('re5', 'cast-c', doc)[1]


def test_the_pool_is_per_title_verified_and_on_this_pc(rejects):
    store, w, saver, calls, now, tick = re5_rig()
    cfg = M.settings(store, 'lilspark')
    why = {}
    assert DR.pool(store, 'lilspark', cfg, 're5', RE5, builds=builds(), refused=why) == ['cast-a', 'cast-b', 'cast-c']
    assert 'vincent' in why['cast-bad'] and why['cast-missing'] == 'not on this PC'
    assert 'cast-a' in why['cast-a-subset'] and 'roster-native' in why
    assert 'cast-probe-x' not in why and 'cast-a-blueprint' not in why          # experiments / companions: not offered
    assert DR.pool(store, 'lilspark', cfg, 're4', RE4, builds=builds()) == ['other-title']   # each title its own
    assert DR.pool(store, 'lilspark', cfg, 're4', RE5, builds=builds()) == []   # ... audited for its own game
    assert DR.pool(store, 'lilspark', cfg, 're5', RE5, builds=None) == []       # no build index: nothing is verified
    # an explicit list narrows the pool and is still gated
    cfg = M.configure(store, 'lilspark', {'donor_pool': {'re5': ['cast-b', 'cast-bad', 'cast-probe-x']}})
    assert DR.pool(store, 'lilspark', cfg, 're5', RE5, builds=builds()) == ['cast-b', 'cast-probe-x']
    # the operator's donor swap superseded a build: its variant plays in its place
    store.put(D.SUPERSEDE, RE5, {'cast-b': 'cast-b-fix1'})
    R.merge({}, {'cast-b-fix1': entry('re5', RE5, {'chris': 'goji2'})})
    cfg = M.configure(store, 'lilspark', {'donor_pool': {}})
    assert 'cast-b-fix1' not in DR.pool(store, 'lilspark', cfg, 're5', RE5, builds=builds())   # not on this PC yet
    assert 'cast-b-fix1' in DR.pool(store, 'lilspark', cfg, 're5', RE5, builds=builds(ON_PC + ['cast-b-fix1']))


def test_draws_are_a_shuffle_bag_with_no_immediate_repeat(rejects):
    store, w, saver, calls, now, tick = re5_rig()
    cfg = M.settings(store, 'lilspark')
    for seed in range(12):
        store.delete(DR.STATE, 'lilspark')
        rng = random.Random(seed)
        picks = [DR.draw(store, 'lilspark', cfg, 're5', RE5, rng, builds=builds()) for _ in range(9)]
        assert all(a != b for a, b in zip(picks, picks[1:])), picks
        for cycle in (picks[0:3], picks[3:6], picks[6:9]):
            assert sorted(cycle) == ['cast-a', 'cast-b', 'cast-c'], picks
    assert DR.draw(store, 'lilspark', cfg, 're5', RE5, random.Random(1), builds=builds(),
                   avoid={'cast-a', 'cast-b', 'cast-c'}, strict=True) is None
    one = M.configure(store, 'lilspark', {'donor_pool': {'re5': ['cast-a']}})
    assert {DR.draw(store, 'lilspark', one, 're5', RE5, random.Random(2), builds=builds()) for _ in range(3)} == {'cast-a'}


# --- the scheduler -----------------------------------------------------------------------------------------------

def test_a_block_launches_a_pool_build_in_place_of_default_mods(rejects):
    store, w, saver, calls, now, tick = re5_rig()
    tick()
    launch = calls[-1]
    assert launch['input']['mod'] in ('cast-a', 'cast-b', 'cast-c')
    run = store.get(S.STATE, 'lilspark')
    assert run['mercmode']['donor'] == {'build': launch['input']['mod'], 'drawn': True}
    assert DR.title_state(store, 'lilspark', 're5')['current'] == launch['input']['mod']


def test_rotation_off_or_an_empty_pool_plays_default_mods(rejects):
    store, w, saver, calls, now, tick = re5_rig(donor_rotation='off')
    tick()
    assert calls[-1]['input']['mod'] == 'default-build' and 'donor' not in store.get(S.STATE, 'lilspark')['mercmode']
    store, w, saver, calls, now, tick = re5_rig(donor_pool={'re5': ['cast-bad', 'roster-native']})
    tick()
    assert calls[-1]['input']['mod'] == 'default-build'


def test_the_blueprint_look_plays_the_drawn_builds_companion_or_falls_back(rejects):
    store, w, saver, calls, now, tick = re5_rig(blueprint_look=True, donor_pool={'re5': ['cast-a']})
    tick()
    assert calls[-1]['input']['mod'] == 'cast-a-blueprint'
    store, w, saver, calls, now, tick = re5_rig(blueprint_look=True, donor_pool={'re5': ['cast-b']})
    tick()                                                       # this PC has no cast-b-blueprint: the plain build
    assert calls[-1]['input']['mod'] == 'cast-b' and store.get(S.STATE, 'lilspark')['blueprint_fallback'] is True


def test_the_dj_queue_build_wins_and_a_queued_round_without_a_build_draws(rejects):
    store, w, saver, calls, now, tick = re5_rig(repeat_queue=True,
                                                queue=[{'title': 're5', 'character': 'Chris (BSAA)', 'mod': 'queued-build'}])
    tick()
    assert calls[-1]['input']['mod'] == 'queued-build'
    assert 'donor' not in store.get(S.STATE, 'lilspark')['mercmode'] and not DR.title_state(store, 'lilspark', 're5')
    store, w, saver, calls, now, tick = re5_rig(queue=[{'title': 're5', 'character': 'Chris (BSAA)'}])
    tick()
    assert calls[-1]['input']['mod'] in ('cast-a', 'cast-b', 'cast-c')
    assert calls[-1]['input']['game']['launch']['mercmode']['selection']['character'] == 'Chris (BSAA)'


def test_the_warm_preload_promise_carries_the_build_the_next_block_plays(rejects):
    store, w, saver, calls, now, tick = rig()
    saver.builds = builds()
    w['features'] = [M.WARM_FEATURE]
    cfg = M.configure(store, w['name'], {'enabled': True, 'titles': ['re4', 're5'], 'keep_warm': 1})
    run = {'worker': w['name'], 'worker_id': w['id'], 'game_id': RE4, 'session_id': 'w1-x', 'title': 'RE4',
           'phase': 'playing', 'started': now[0], 'mercmode': {'title': 're4', 'map_id': 'G4BE08'}}
    store.put(S.STATE, w['name'], run)
    saver._prelaunch(w, run, cfg, now[0])
    promised = store.get(M.NEXT, w['name'])
    assert promised['title'] == 're5' and promised['donor'] is True and promised['cold'] is True
    drawn = promised['selection']['mod']
    assert drawn in ('cast-a', 'cast-b', 'cast-c')
    pick = M.choose(store, w, random.Random(9), M.settings(store, w['name']), builds=saver.builds)
    assert pick['selection']['mod'] == drawn and pick['_donor_drawn'] is True
    assert DR.title_state(store, w['name'], 're5')['history'] == [drawn]        # no second draw at the switch


def test_donor_rounds_relaunch_inside_the_block_and_the_block_still_counts_five(rejects):
    store, w, saver, calls, now, tick = re5_rig(donor_rounds=2)
    tick()
    first = calls[-1]['input']['mod']
    run, job = up(store, saver, calls, now, tick)
    assert play_round(store, saver, now, 1, job)['rotate_requested'] is False
    # a quick death is the second completed attempt and triggers the next donor
    now[0] += 10
    quick = saver.round_boundary(boundary(store.get(S.STATE, 'lilspark'), now[0], screen='dead', hp=0)
                                 | {'round_id': 'd' * 32}, job, now[0])
    assert quick['rotate_requested'] is True
    promise = store.get(M.NEXT, 'lilspark')
    assert promise['title'] == 're5' and promise['block_played'] == 2 and promise['selection']['mod'] != first
    tick(1)
    assert calls[-1]['input']['op'] == 'stop_game'
    store.put('session', run['session_id'], store.get('session', run['session_id']) | {'state': 'ended'})
    tick(1)
    assert calls[-1]['tool'] == 'launch_game' and calls[-1]['input']['mod'] == promise['selection']['mod'], (promise, calls[-1], store.get(M.NEXT, 'lilspark'))
    second = store.get(S.STATE, 'lilspark')
    assert second['mercmode_rounds'] == 2 and second['mercmode']['donor']['drawn'] is True
    run, job = up(store, saver, calls, now, tick)
    assert play_round(store, saver, now, 3, job)['rotate_requested'] is False
    assert play_round(store, saver, now, 4, job)['rotate_requested'] is True
    assert store.get(M.NEXT, 'lilspark')['block_played'] == 4


def test_a_single_title_gets_a_new_build_each_block_and_a_pool_of_one_plays_on(rejects):
    store, w, saver, calls, now, tick = re5_rig(rounds_per_title=2)
    tick()
    first = calls[-1]['input']['mod']
    run, job = up(store, saver, calls, now, tick)
    assert play_round(store, saver, now, 1, job)['rotate_requested'] is False
    assert play_round(store, saver, now, 2, job)['rotate_requested'] is True       # the block's end: a new build
    promise = store.get(M.NEXT, 'lilspark')
    assert promise['block_played'] == 0 and promise['selection']['mod'] != first
    store, w, saver, calls, now, tick = re5_rig(rounds_per_title=2, donor_rounds=1, donor_pool={'re5': ['cast-a']})
    tick()
    run, job = up(store, saver, calls, now, tick)
    assert play_round(store, saver, now, 1, job)['rotate_requested'] is False      # nothing new to show: no reboot


def test_with_other_titles_the_block_end_switches_title_not_build(rejects):
    store, w, saver, calls, now, tick = rig()
    saver.builds = builds()
    M.configure(store, w['name'], {'enabled': True, 'titles': ['re4', 're5'], 'keep_warm': 0, 'rounds_per_title': 1})
    M.configure(store, w['name'], {'queue': [{'title': 're5'}]})
    tick()
    assert calls[-1]['input']['mod'] in ('cast-a', 'cast-b', 'cast-c')
    run, job = up(store, saver, calls, now, tick)
    assert play_round(store, saver, now, 1, job)['rotate_requested'] is True
    assert store.get(M.NEXT, 'lilspark') is None                                   # the title rotation decides
    assert not store.get(S.STATE, 'lilspark').get('mercmode_mod_rotate')


# --- fresh builds -----------------------------------------------------------------------------------------------

def test_fresh_mode_asks_for_a_redraw_when_the_bag_runs_out_and_the_build_joins_the_pool(rejects):
    store, w, saver, calls, now, tick = re5_rig(donor_rotation='fresh')
    cfg = M.settings(store, 'lilspark')
    rng = random.Random(3)
    DR.draw(store, 'lilspark', cfg, 're5', RE5, rng, builds=builds())
    assert DR.fresh_request(store, 'lilspark', cfg, 're5', RE5, rng=rng, builds=builds(), now=now[0]) is None
    DR.draw(store, 'lilspark', cfg, 're5', RE5, rng, builds=builds())
    DR.draw(store, 'lilspark', cfg, 're5', RE5, rng, builds=builds())                 # the cycle is done
    inp = DR.fresh_request(store, 'lilspark', cfg, 're5', RE5, rng=rng, builds=builds(), now=now[0])
    assert inp['op'] == 'donor_variant' and inp['build'] in ('cast-a', 'cast-b', 'cast-c')
    assert inp['new_name'] == inp['build'] + '-rot1'
    spec = inp['changes']
    source = AUDITED[inp['build']]
    assert spec['swap_id'].startswith('rot') and spec['enemies'] == [] and spec['title'] == 're5'
    assert {p['slot'] for p in spec['players']} <= set(source['players']) and 1 <= len(spec['players']) <= DR.FRESH_SLOTS
    assert {'vincent', 'sonic', 'goji', 'knuckles', 'mario', 'yoshi'} <= set(spec['exclude'])   # rejected + shown
    assert DR.fresh_request(store, 're6', cfg, 're6', 'x', rng=rng) is None
    assert 'no in-service redraw' in DR.fresh_due(store, 'lilspark', cfg, 're6')
    DR.fresh_submitted(store, 'lilspark', 're5', inp, 'job-f', now=now[0])
    assert 'on its way' in DR.fresh_due(store, 'lilspark', cfg, 're5', now=now[0] + 60)
    # the job lands (switch_mods' on_accept): the redrawn slots are indexed, the build is the next block's first draw
    from gbox import switch_mods as SM
    slot = spec['players'][0]['slot']
    result = {'op': 'donor_variant', 'swap_id': spec['swap_id'], 'variant': inp['new_name'], 'of': inp['build'],
              'blueprint': None, 'game_id': RE5, 'rejected_during': [],
              'slots': [{'slot': slot, 'old': spec['players'][0]['donor'], 'new': 'shadow', 'how': 'redrawn'}]}
    SM._accept(store, SM.SwitchModsOut(result=result), 'worker')
    row = DR.title_state(store, 'lilspark', 're5')
    assert row['fresh']['state'] == 'ready' and row['fresh_builds'] == [inp['new_name']]
    assert R.build_index(inp['new_name'])['players'][slot]['donor'] == 'shadow'
    assert D.variant(store, RE5, inp['new_name'])['of'] == inp['build']
    assert not D.superseded(store, RE5)                                              # the source stays in the pool
    assert DR.draw(store, 'lilspark', cfg, 're5', RE5, rng, builds=builds()) == inp['new_name']
    # one at a time, FRESH_MIN_INTERVAL_S apart; a failed job is settled
    assert 'less than' in DR.fresh_due(store, 'lilspark', cfg, 're5', now=now[0] + 60)
    DR.fresh_submitted(store, 'lilspark', 're5', inp, 'job-g', now=now[0])
    store.put('job', 'job-g', {'id': 'job-g', 'state': 'failed', 'error': 'no RomFS'})
    DR.fresh_due(store, 'lilspark', cfg, 're5', now=now[0] + 60)
    assert DR.title_state(store, 'lilspark', 're5')['fresh']['state'] == 'failed'


def test_the_scheduler_submits_the_fresh_job_and_it_never_holds_a_launch(rejects):
    store, w, saver, calls, now, tick = re5_rig(donor_rotation='fresh', donor_pool={'re5': ['cast-a']})
    tick()
    fresh = [c for c in calls if c['tool'] == 'switch_mods']
    assert len(fresh) == 1 and fresh[0]['input']['op'] == 'donor_variant' and fresh[0]['require_worker'] == w['id']
    assert fresh[0]['actor'] == S.ACTOR and fresh[0]['agent_use'] is True
    assert S.offline_job(fresh[0]) is True and S.offline_job({'tool': 'switch_mods', 'input': {'op': 'write'}}) is False
    assert DR.title_state(store, 'lilspark', 're5')['fresh']['job'] == fresh[0]['id']


def test_status_names_the_pool_what_plays_and_why_builds_were_left_out(rejects):
    store, w, saver, calls, now, tick = re5_rig(donor_rotation='fresh')
    tick()
    status = saver.mercmode_status(fresh=True)
    rot = next(h for h in status['hosts'] if h['name'] == 'lilspark')['donor_rotation']
    re5 = rot['titles']['re5']
    assert rot['mode'] == 'fresh' and re5['pool'] == ['cast-a', 'cast-b', 'cast-c']
    assert re5['current'] == calls[0]['input']['mod'] and 'cast-bad' in re5['refused']
    assert M.settings(store, 'lilspark')['donor_rotation'] == 'fresh'
