"""RE damage incidents -> cause clusters -> one batch request per cause per game (gbox/mercs/damage_clusters.py)."""
import copy
import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import player_damage as P
from gbox.mercs import damage_clusters as C
from gbox.store import Store

RE5, RE6 = '52d15709be0fda1a', '115f9cdbba115432'          # RE5 / RE6 No Mercy on Switch (game ids)


def enemy(dist_cm, deg, hp=800, dy=0.0, cls='uEm10'):
    """A live enemy dist_cm from a player at the origin facing +z (rot 0), deg off his facing (+ = toward +x)."""
    a = math.radians(deg)
    return {'ptr': int(dist_cm * 1000 + deg + 7), 'hp': hp, 'hp_max': 800, 'class': cls,
            'pos': [dist_cm * math.sin(a), dy, dist_cm * math.cos(a)]}


def event(title='010018100CD46000', *, hp=(800, 700), enemies=(), held=(), player=None, logic=None, snap=None,
          at=100.0, eid='event_00000001', run='run_000000001', rnd='round_00000001', history=None):
    p = {'ptr': 1, 'pos': [0.0, 0.0, 0.0], 'rot': 0.0, 'hp': hp[1], 'hp_max': 1000, **(player or {})}
    s = {'player': p, 'enemies': list(enemies), **(snap or {})}
    return {'schema': 'gbox.player_damage/1', 'session_id': 'worker-session', 'event_id': eid, 'run_id': run,
            'round_id': rnd, 'title': title, 'observed_at': at, 'hp_before': hp[0], 'hp_after': hp[1],
            'hp_max': 1000, 'loss': hp[0] - hp[1], 'snapshot': s, 'logic': dict(logic or {}), 'held': list(held),
            'preceding_history': history or [], 'raw': {'state': 'unsupported'},
            'tactical': {'v': 1, 'title': title, 'stage': 'stage1', 'units': 'cm', 'screen': 'playing',
                         'player': {'pos': [0, 0, 0], 'hp': hp[1]}},
            'frame_at_hit': {'state': 'unavailable-at-hit'}}


def sig(ev, game=RE5, prev=None):
    return C.classify(C.features(ev, game), prev)


# --- the rules ---------------------------------------------------------------------------------------------------------

def test_bearing_is_off_his_facing_in_the_drivers_heading_convention():
    inc = C.features(event(enemies=[enemy(100, 0), enemy(300, 180), enemy(150, 90)]), RE5)
    assert [(n['d'], abs(n['deg'])) for n in inc['near']] == [(100, 0), (150, 90), (300, 180)]
    assert inc['near'][1]['deg'] == 90                              # + is toward his right (+x)
    turned = C.features(event(enemies=[enemy(100, 0)], player={'rot': math.pi}), RE5)
    assert abs(turned['near'][0]['deg']) == 180                       # the same enemy is behind him once he turns
    off_level = C.features(event(enemies=[enemy(100, 0, dy=450), enemy(100, 0, hp=0)]), RE5)
    assert off_level['near'] == [] and off_level['live'] == 0         # rooftops and the dead never count


@pytest.mark.parametrize('ev,game,expected', [
    # a strangle (RE5 motion 100) with the Majini behind: grabbed from behind beats the crowd around him
    (event(player={'motion': 100}, enemies=[enemy(5, 170)] + [enemy(150, d) for d in (0, 40, 80, 120)]), RE5,
     'grabbed_from_behind'),
    (event('01002A000CD48000', player={'state': 8}, enemies=[enemy(60, 10)]), RE6, 'grabbed_front'),
    (event('01002A000CD48000', player={'action': 'cEm1000ActAtkDangerCatchFinish_Knife_PL'},
           enemies=[enemy(40, -20)]), RE6, 'grabbed_front'),
    # his own remote bomb 3 m away with nobody at arm's length (RE6) / his proximity mine 2 m away (RE5)
    (event('01002A000CD48000', snap={'bomb_pos': [0.0, 0.0, 300.0]}, enemies=[enemy(240, 30)]), RE6, 'own_bomb'),
    (event(snap={'ground_mines': [{'ptr': 9, 'pos': [200.0, 0.0, 0.0]}]}, hp=(900, 200)), RE5, 'own_bomb'),
    (event('01002A000CD48000', player={'action': 'cPlAction_pl_act_buttobi_damage_common'},
           enemies=[enemy(150, 0)]), RE6, 'fall_knockdown'),
    (event(hp=(1, 0), enemies=[enemy(80, 0)]), RE5, 'fall_knockdown'),           # killed while dying at 1 HP
    (event(enemies=[enemy(d, a) for d, a in ((60, 0), (90, 100), (120, -100), (190, 180))]), RE5, 'crowd_gun_down'),
    (event(held=['zl', 'zr'], enemies=[enemy(d, a) for d, a in ((60, 0), (90, 100), (120, -100), (190, 180))]), RE5,
     'crowd_4_in_2m'),
    (event(enemies=[enemy(10, 30), enemy(150, 0)]), RE5, 'grabbed_front'),          # on him, no motion byte (HELD_R)
    (event(player={'motion': 0}, enemies=[enemy(10, 30), enemy(150, 0)]), RE5, 'faced_melee'),   # the motion says free
    (event(held=['zl'], enemies=[enemy(300, 120)]), RE5, 'aimed_away_or_behind'),  # gun up, the nearest 120 deg off
    (event(enemies=[enemy(120, -150)]), RE5, 'aimed_away_or_behind'),              # one close behind him
    (event(hp=(250, 150), enemies=[enemy(100, 0)], snap={'inventory': [{'id': 0x305, 'rounds': 0}]}), RE5,
     'low_hp_no_heal'),
    (event(hp=(250, 150), enemies=[enemy(100, 0)], snap={'inventory': [{'id': 0x304, 'rounds': 1}]}), RE5,
     'low_hp_heal_unused'),
    (event('01002A000CD48000', hp=(200, 100), player={'tablets': 6}, enemies=[enemy(100, 0)]), RE6,
     'low_hp_heal_unused'),
    (event(enemies=[enemy(900, 0)]), RE5, 'ranged'),
    (event(enemies=[]), RE5, 'ranged'),
    (event(held=['zl', 'zr'], enemies=[enemy(120, 10), enemy(180, -20)]), RE5, 'faced_melee'),
])
def test_each_rule_names_its_cause(ev, game, expected):
    assert sig(ev, game)[0] == expected


def test_a_hit_keeps_every_rule_it_matched_as_tags():
    ev = event(hp=(250, 100), held=['zl'], snap={'inventory': [{'id': 0x305, 'rounds': 0}]},
               enemies=[enemy(d, a) for d, a in ((60, 120), (90, 100), (120, -100), (190, 180))])
    signature, tags = sig(ev)
    assert signature == 'crowd_4_in_2m'
    assert tags == ['crowd_4_in_2m', 'aimed_away_or_behind', 'low_hp_no_heal']


def test_wall_and_aim_away_counters_count_only_when_they_rose_just_before_this_hit_in_its_round():
    first = C.features(event(logic={'wall_aim_s': 1.0}, enemies=[enemy(900, 0)], at=100.0), RE5)
    later = C.features(event(logic={'wall_aim_s': 1.6}, enemies=[enemy(900, 0)], at=102.0, eid='event_00000002'), RE5)
    assert C.classify(later, first)[0] == 'wall_los_aim'
    stale = dict(later, observed_at=100.0 + C.PREV_S + 1)
    assert C.classify(stale, first)[0] == 'ranged'
    other_round = dict(later, round_id='round_00000002')
    assert C.classify(other_round, first)[0] == 'ranged'
    flat = C.features(event(logic={'wall_aim_s': 1.0}, enemies=[enemy(900, 0)], at=101.0), RE5)
    assert C.classify(flat, first)[0] == 'ranged'


def test_a_fall_is_read_from_the_preceding_path():
    history = [{'at': 99.0, 'pos': [0, 220.0, 0], 'hp': 800}, {'at': 99.8, 'pos': [0, 0.0, 0], 'hp': 800}]
    assert sig(event(enemies=[enemy(900, 0)], history=history))[0] == 'fall_knockdown'


# --- deaths, episodes, trend -------------------------------------------------------------------------------------------

def inc(ev, game=RE5):
    out = C.features(ev, game)
    out['id'] = ev['event_id']
    return out


def test_a_death_goes_to_the_hit_that_put_him_down_and_re6_death_log_names_a_hold():
    crowd = [enemy(d, a) for d, a in ((60, 0), (90, 100), (120, -100), (190, 180))]
    down = inc(event(hp=(400, 1), enemies=crowd, at=100.0, eid='event_00000001'))
    kill = inc(event(hp=(1, 0), enemies=[enemy(80, 0)], at=104.0, eid='event_00000002'))
    labelled, deaths = C.label_run([kill, down])
    assert [s for _i, s, _t in labelled] == ['crowd_gun_down', 'fall_knockdown']
    assert [(d[0]['event_id'], d[1]) for d in deaths] == [('event_00000001', 'crowd_gun_down')]
    # RE6: a killing hit with nobody close, and the driver's death_log for that death says a zombie held him
    entry = {'held': True, 'doing': 'nade', 'near_2m': 1, 'near_4m': 3, 'bomb_phase': None, 'bomb_cm': None}
    k6 = inc(event('01002A000CD48000', hp=(300, 0), enemies=[enemy(500, 0)], logic={'deaths': 4}, at=200.0,
                   eid='event_00000003'), RE6)
    after = inc(event('01002A000CD48000', hp=(900, 800), enemies=[enemy(500, 0)], at=230.0, eid='event_00000004',
                      rnd='round_00000002', logic={'deaths': 5, 'death_log': [{'held': False}, entry]}), RE6)
    _l, deaths6 = C.label_run([k6, after])
    assert deaths6[0][1] == 'grabbed_front' and deaths6[0][2]['held'] is True


def test_grab_drains_are_one_episode_and_the_summary_carries_trend_examples_and_code():
    rows = []
    for turn, start in ((1, 1000.0), (2, 5000.0)):
        run = f'run_{turn:09d}'
        for n in range(3):                                   # one strangle: three drains 0.3 s apart
            rows.append(inc(event(player={'motion': 100}, enemies=[enemy(5, 170)], at=start + 0.3 * n, run=run,
                                  eid=f'event_{turn}{n:07d}', hp=(900 - 50 * n, 850 - 50 * n))))
        rows.append(inc(event(player={'motion': 100}, enemies=[enemy(5, 170)], at=start + 30, run=run,
                              rnd='round_00000002', eid=f'event_{turn}9999999')))
    clusters, totals = C.summarize(rows, now=6000.0)
    c = clusters[(RE5, 'grabbed_from_behind')]
    assert (c['hits'], c['episodes'], c['deaths']) == (8, 4, 0)
    assert [t['episodes'] for t in c['turns']] == [2, 2] and c['turns'][0]['rounds'] == 2
    assert totals[RE5]['hits'] == 8 and c['share_of_hits'] == 1.0
    assert c['code'][0] == {'file': 'gbox/mercs/titles/re5_switch.py', 'function': 'Bot._threat_pick'}
    assert 1 <= len(c['examples']) <= C.EXAMPLES
    assert len({e['event_id'] for e in c['examples']}) == len(c['examples'])
    assert {e['run_id'] for e in c['examples']} == {'run_000000001', 'run_000000002'}   # spread over the turns
    assert c['examples'][0]['ledger'].startswith('/api/sessions/worker-session/damage/runs/')
    text = C.render(dict(c, members=[]))
    assert 'ONE logic change' in text and 'Bot._threat_pick' in text and 'Trend per turn' in text


# --- the store: incidents at ingest, batches, members ------------------------------------------------------------------

@pytest.fixture
def world(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.put('session', 'worker-session', {'session_id': 'worker-session', 'state': 'running', 'adapter': 'rpcs3',
                                            'game_id': RE5})
    monkeypatch.setattr(P.E, 'render_map', lambda frame, stage: b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    monkeypatch.setattr(C, 'MIN_BATCH', 3)                        # small fixtures: three episodes make a batch
    made = []

    def create(body, actor):
        made.append(body)
        n = len(store.all('request')) + 1
        req = dict(body, id=f'single{n}', number=n, messages=[], status='open', created=clock[0])
        store.put('request', req['id'], req)
        return req
    clock = [10_000.0]
    priority = []
    runner = C.Clusters(store, tmp_path, now=lambda: clock[0],
                        priority=lambda open_ids, shut: priority.append((sorted(open_ids), sorted(shut))))

    def deliver(ev):
        P.ingest(store, 'worker-session', ev, lambda sid: {'stream': {}, 'tactical': {}}, now=ev['observed_at'])
        return P.materialize(store, create, None, P.key('worker-session', ev['event_id']))
    yield store, runner, clock, deliver, made, priority
    store.db.close()


def crowd_event(n, run='run_000000001', at=9_000.0):
    return event(eid=f'event_{run[-3:]}{n:05d}', run=run, at=at + n * 5.0, held=['zl', 'zr'],
                 enemies=[enemy(d, a) for d, a in ((60, 0), (90, 100), (120, -100), (190, 180))])


def test_ingest_records_the_incident_and_a_pass_batches_singles_into_one_request_per_cause(world):
    store, runner, clock, deliver, made, priority = world
    for run in ('run_000000001', 'run_000000002'):
        for n in range(3):
            deliver(crowd_event(n, run))
    deliver(event(eid='event_ranged001', run='run_000000002', at=9_100.0, enemies=[enemy(900, 0)]))
    assert len(store.all(C.INCIDENT)) == 7                        # recorded at ingest, no receipt read back
    singles = [r for r in store.all('request') if r['source'] == 'player_damage']
    assert len(singles) == 2 and all(r['status'] == 'open' for r in singles)
    result = runner.poll()
    assert result['batches'] == 1 and result['singles_closed'] == 2
    batch = next(r for r in store.all('request') if r['source'] == C.SOURCE)
    cid = C.cluster_id(RE5, 'crowd_4_in_2m')
    assert batch['id'] == C.request_id_for(cid) and batch['kind'] == 'report' and batch['author'] == 'agent'
    assert batch['context'] == {**batch['context'], 'damage_cluster': True, 'damage_cluster_id': cid,
                                'signature': 'crowd_4_in_2m', 'game_id': RE5, 'auto_report': True,
                                'operator_requested': True}
    assert batch['title'] == 'Damage batch: RE5 Switch - swarmed (4+ within 2 m) with the gun up'
    assert 'ONE logic change' in batch['body'] and 'Bot._keep_moving' in batch['body']
    # both runs are closed into the batch; run 2's ranged hit is a cause too small to batch yet, and says so
    first, second = sorted(singles, key=lambda r: r['context']['damage_run_id'])
    first, second = store.get('request', first['id']), store.get('request', second['id'])
    for single in (first, second):
        assert single['status'] == 'done' and single['context']['batched_into'] == [batch['id']]
        assert single['messages'][-1]['text'].startswith(
            f"Batched into #{batch['number']} (swarmed (4+ within 2 m) with the gun up)")
    assert 'too small to batch yet' in second['messages'][-1]['text'] and 'ranged' in second['messages'][-1]['text']
    assert 'too small' not in first['messages'][-1]['text']
    assert sorted(store.get(C.CLUSTER, cid)['members']) == sorted([first['id'], second['id']])
    assert priority == [([batch['id']], [])]
    # two more ranged hits make that cause a batch of its own; nothing is deleted, the singles stay closed
    for n in range(2):
        deliver(event(eid=f'event_ranged00{n + 2}', run='run_000000002', at=9_200.0 + 5 * n, enemies=[enemy(900, 0)]))
    clock[0] += 60
    assert runner.poll()['batches'] == 2
    assert store.get('request', second['id'])['status'] == 'done'
    assert len(store.all('request')) == 4                          # 2 singles + 2 batches; never deleted
    assert len(made) == 2                                          # the singles' own creation only
    assert len(priority) == 2 and len(priority[-1][0]) == 2       # both batches on the Hermes priority list


def test_rolling_window_updates_the_batch_in_place(world):
    store, runner, clock, deliver, made, priority = world
    for n in range(3):
        deliver(crowd_event(n))
    runner.poll()
    rid = C.request_id_for(C.cluster_id(RE5, 'crowd_4_in_2m'))
    for n in range(3, 6):
        deliver(crowd_event(n, at=9_100.0))
    clock[0] += C.UPDATE_S + 1
    runner.poll()
    batches = [r for r in store.all('request') if r['source'] == C.SOURCE]
    assert [b['id'] for b in batches] == [rid]                     # updated, not a new batch
    req = store.get('request', rid)
    summary = [m for m in req['messages'] if m.get('id') == 'damage-cluster-summary']
    assert len(summary) == 1 and summary[0]['damage_cluster']['hits'] == 6
    assert 'The PR must add a replay test' in req['body'] and '/replay' in req['body']
    # closed by Hermes: more of the same cause does not reopen it by itself (learning.follow_up judges the effect)
    req.update(status='done', completed=clock[0])
    store.put('request', rid, req)
    for n in range(6, 12):
        deliver(crowd_event(n, at=clock[0] + 600))
    clock[0] += 900
    runner.poll()
    assert store.get('request', rid)['status'] == 'done'
    assert len([r for r in store.all('request') if r['source'] == C.SOURCE]) == 1


def test_a_batched_single_stays_closed_when_its_run_takes_more_damage(world):
    store, runner, clock, deliver, made, priority = world
    for n in range(3):
        deliver(crowd_event(n))
    runner.poll()
    single = next(r for r in store.all('request') if r['source'] == 'player_damage')
    assert store.get('request', single['id'])['status'] == 'done'
    deliver(crowd_event(7))
    single = store.get('request', single['id'])
    assert single['status'] == 'done' and single['context']['batched_into']
    assert any(m.get('id') == 'player-damage-run' for m in single['messages'])     # the ledger summary still updates


def test_backfill_reads_back_receipts_of_rows_recorded_before_this_module(world):
    store, runner, clock, deliver, made, priority = world
    for n in range(3):
        deliver(crowd_event(n))
    for row in store.all(C.INCIDENT):
        store.delete(C.INCIDENT, row['id'])
    store.put(P.KIND, 'broken', {**store.all(P.KIND)[0], 'id': 'broken', 'event_id': 'event_broken01',
                                 'receipt': 'f' * 64, 'observed_at': 9_050.0})
    assert runner.backfill([]) == 4
    rows = {r['id']: r for r in store.all(C.INCIDENT)}
    assert rows['broken']['receipt_error'] and C.classify(rows['broken'])[0] == 'ranged'
    good = [r for k, r in rows.items() if k != 'broken']
    assert all(C.classify(r)[0] == 'crowd_4_in_2m' for r in good)
    assert runner.backfill([]) == 0                                # each row once


def test_an_old_open_single_is_classified_from_its_newest_events_and_closed(world, monkeypatch):
    store, runner, clock, deliver, made, priority = world
    monkeypatch.setattr(C, 'BACKLOG_PER_RUN', 3)
    for n in range(5):
        deliver(crowd_event(n, at=1_000.0))                        # long before the window
    for row in store.all(C.INCIDENT):
        store.delete(C.INCIDENT, row['id'])
    clock[0] = 1_000.0 + C.WINDOW_S + 3600
    runner.poll()
    assert len(store.all(C.INCIDENT)) == 3
    single = next(r for r in store.all('request') if r['source'] == 'player_damage')
    single = store.get('request', single['id'])
    assert single['status'] == 'done' and '3 of 5 events classified' in single['messages'][-1]['text']


def test_routes_list_what_kills_him_and_one_cluster(world):
    store, runner, clock, deliver, made, priority = world
    for n in range(3):
        deliver(crowd_event(n))
    deliver(event(eid='event_dying0001', at=9_020.0, hp=(1, 0), enemies=[enemy(80, 0)]))
    runner.poll()
    app = FastAPI()
    config = type('Config', (), {'data_dir': store.dir})()
    C.install(app, store, config, lambda: 'agent', runner=runner)
    with TestClient(app) as client:
        page = client.get('/api/mercs/damage-clusters?game=re5').json()
        assert page['game'] == RE5 and page['clusters'][0]['signature'] == 'fall_knockdown'   # the death first
        crowd = next(c for c in page['clusters'] if c['signature'] == 'crowd_4_in_2m')
        assert crowd['request_id'] == C.request_id_for(crowd['id']) and crowd['status'] == 'open'
        assert page['what_kills_him'][0].startswith('RE5 Switch: fall, knockdown or dying chain - 1 deaths')
        assert client.get('/api/mercs/damage-clusters/' + crowd['id']).json()['request_id'] == crowd['request_id']
        assert client.get('/api/mercs/damage-clusters/0000000000000000').status_code == 404
        assert client.get('/api/mercs/damage-clusters?game=re6').json()['clusters'] == []


# --- Hermes: the batch is dispatched first on sparkDeux, the RE single never --------------------------------------------

def test_hermes_admits_only_the_real_batch_holds_re_singles_and_shares_the_busy_game(world, monkeypatch):
    from gbox import hermes_work_queue as Q
    store, runner, clock, deliver, made, priority = world
    for n in range(3):
        deliver(crowd_event(n))
    deliver(event(eid='event_ranged001', at=9_100.0, run='run_000000002', enemies=[enemy(900, 0)]))
    runner.poll()
    app = FastAPI()
    config = type('Config', (), {'data_dir': store.dir})()
    C.install(app, store, config, lambda: 'agent', runner=runner)
    client = TestClient(app)
    monkeypatch.setattr(Q, '_api', lambda path: client.get(path).raise_for_status().json())
    monkeypatch.setattr(Q, 're_games', lambda: {RE5, RE6})
    requests = store.all('request')
    batch = next(r for r in requests if r['source'] == C.SOURCE)
    single = next(r for r in requests if r['source'] == 'player_damage' and r['status'] == 'open')
    assert Q.requested_damage_cluster(batch)
    data = {'items': {}}
    Q.sync(data, {'count': 0, 'items': []}, requests, now=clock[0])
    assert list(data['items']) == ['inbox:' + batch['id']]          # the open RE single is held: batched by cause
    item = data['items']['inbox:' + batch['id']]
    assert item['damage_cluster_verified'] is True and item['operator_requested'] is True
    assert not Q.launches_emulator(item) and Q.re_report(item, batch, {RE5})
    # MercMode keeps RE5 busy: the batch still gets one of its shared slots, up to DAMAGE_CLUSTERS_PER_GAME
    busy = [{'input': {'game_id': RE5}}]
    assert Q.candidates(data, requests, busy, set(), set(), now=clock[0])
    for n in range(Q.DAMAGE_CLUSTERS_PER_GAME):
        data['items'][f'inbox:other{n}'] = {'lane': 'inbox', 'game_id': RE5, 'damage_cluster_verified': True,
                                           'dispatch_state': 'queued', 'request_id': f'other{n}'}
    assert not [k for k, _i in Q.candidates(data, requests, busy, set(), set(), now=clock[0])
                if k == 'inbox:' + batch['id']]
    prompt = Q._prompt(dict(item, number=batch['number']))
    assert 'ONE logic change' in prompt and 'damage-clusters?game=' + RE5 in prompt
    # a copied context is not a batch, nor is a batch whose server is unreachable
    forged = copy.deepcopy(batch)
    forged['id'] = 'forged-request'
    assert not Q.requested_damage_cluster(forged)
    fresh = {'items': {}}
    Q.sync(fresh, {'count': 0, 'items': []}, [forged], now=clock[0])
    assert not fresh['items']
    monkeypatch.setattr(Q, '_api', lambda path: (_ for _ in ()).throw(OSError('offline')))
    Q.sync(data, {'count': 0, 'items': []}, requests, now=clock[0] + 1)
    assert data['items']['inbox:' + batch['id']]['damage_cluster_verified'] is False


def test_queue_priority_appends_batches_after_the_operators_list_and_drops_closed_ones(tmp_path, monkeypatch):
    from gbox import hermes_delivery, hermes_work_queue as Q
    monkeypatch.setattr(hermes_delivery, 'state_dir', lambda: tmp_path)
    saved = {'priority': ['operator-1', 'old-batch']}
    monkeypatch.setattr(Q, '_read', lambda: dict(saved))
    monkeypatch.setattr(Q, '_save', lambda data: saved.update(data))
    C.queue_priority(['batch-a', 'batch-b'], ['old-batch'])
    assert saved['priority'] == ['operator-1', 'batch-a', 'batch-b']
    C.queue_priority(['batch-a', 'batch-b'], [])
    assert saved['priority'] == ['operator-1', 'batch-a', 'batch-b']


def test_only_the_deadliest_batches_of_each_game_go_on_the_priority_list(world, monkeypatch):
    store, runner, clock, deliver, made, priority = world
    monkeypatch.setattr(C, 'PRIORITY_TOP', 1)
    for n in range(3):
        deliver(crowd_event(n))
        deliver(event(eid=f'event_far{n:06d}', at=9_500.0 + 5 * n, enemies=[enemy(900, 0)], hp=(800, 300)))
    runner.poll()
    batches = {r['context']['signature']: r['id'] for r in store.all('request') if r['source'] == C.SOURCE}
    assert set(batches) == {'crowd_4_in_2m', 'ranged'}
    assert priority[-1] == ([batches['ranged']], [batches['crowd_4_in_2m']])      # more HP lost ranks first
    runner.poll()
    assert len(priority) == 1                                      # unchanged: the queue lock is not taken again
