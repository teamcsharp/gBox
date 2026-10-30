"""The RE bots' self-improvement loop (gbox/mercs/learning.py): rounds joined to hits, round faults, changes that went
live, their measured effect, and the follow-up of closed batches; the incident replay harness."""
import json
import math
from pathlib import Path
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gbox import player_damage as P
from gbox.mercs import damage_clusters as C, incident_replay, learning as L
from gbox.store import Store

RE5, RE5T = '52d15709be0fda1a', '010018100CD46000'
FIXTURES = Path(__file__).parent / 'fixtures' / 'mercs_incidents'


def enemy(dist_cm, deg, hp=800):
    a = math.radians(deg)
    return {'ptr': int(dist_cm * 1000 + deg + 7), 'hp': hp, 'hp_max': 800, 'pos': [dist_cm * math.sin(a), 0.0,
                                                                                     dist_cm * math.cos(a)]}


CROWD = [enemy(d, a) for d, a in ((60, 0), (90, 100), (120, -100), (190, 180))]


def event(eid, at, *, run='run_000000001', hp=(800, 700), enemies=CROWD, held=('zl', 'zr'), logic=None):
    return {'schema': 'gbox.player_damage/1', 'session_id': 'worker-session', 'event_id': eid, 'run_id': run,
            'round_id': 'round_00000001', 'title': RE5T, 'observed_at': at, 'hp_before': hp[0], 'hp_after': hp[1],
            'hp_max': 1000, 'loss': hp[0] - hp[1], 'held': list(held), 'logic': dict(logic or {}),
            'snapshot': {'player': {'ptr': 1, 'pos': [0.0, 0.0, 0.0], 'rot': 0.0, 'hp': hp[1], 'hp_max': 1000},
                         'enemies': list(enemies)},
            'raw': {'state': 'unsupported'}, 'frame_at_hit': {'state': 'unavailable-at-hit'},
            'tactical': {'v': 1, 'title': RE5T, 'stage': 's', 'units': 'cm', 'screen': 'playing',
                         'player': {'pos': [0, 0, 0], 'hp': hp[1]}}}


class Notebook:
    """The Notebook's rounds table (gbox/mercs/notebook.py) with just the columns the loop reads."""
    def __init__(self, root, title=RE5T):
        path = Path(root) / 'mercs/curriculum' / title
        path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path / 'rounds.sqlite')
        self.db.execute('CREATE TABLE rounds(id TEXT PRIMARY KEY, ts REAL, stage TEXT, mode TEXT, character TEXT, '
                        'outcome TEXT, data TEXT, vector BLOB)')
        self.n = 0

    def add(self, ts, outcome='completed', turn='job_1', **observed):
        self.n += 1
        rid = f'{self.n:032x}'
        data = {'source_session_id': 'worker-session', 'source_autoplay_job_id': turn, **observed}
        self.db.execute('INSERT INTO rounds VALUES(?,?,?,?,?,?,?,NULL)',
                        (rid, ts, 'unknown', 'mercenaries', 'Chris', outcome, json.dumps(data)))
        self.db.commit()
        return rid


@pytest.fixture
def loop(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.put('session', 'worker-session', {'session_id': 'worker-session', 'state': 'running', 'adapter': 'rpcs3',
                                            'game_id': RE5})
    monkeypatch.setattr(P.E, 'render_map', lambda frame, stage: b'<svg xmlns="http://www.w3.org/2000/svg"/>')
    monkeypatch.setattr(C, 'MIN_BATCH', 3)
    clock = [100_000.0]

    def create(body, actor):
        n = len(store.all('request')) + 1
        req = dict(body, id=f'single{n}', number=n, messages=[], status='open', created=clock[0])
        store.put('request', req['id'], req)
        return req
    runner = C.Clusters(store, tmp_path, now=lambda: clock[0])
    book = Notebook(tmp_path)

    def deliver(ev):
        P.ingest(store, 'worker-session', ev, lambda sid: {'stream': {}, 'tactical': {}}, now=ev['observed_at'])
        return P.materialize(store, create, None, P.key('worker-session', ev['event_id']))
    yield store, runner, clock, deliver, book
    store.db.close()


def play(deliver, book, start, rounds, hits_per_round, *, turn='job_1', bonuses=(0, 0), tag='a'):
    """`rounds` rounds of 60 s, each with `hits_per_round` crowd hits 5 s apart, ended in the Notebook."""
    t = start
    for r in range(rounds):
        for h in range(hits_per_round):
            deliver(event(f'event_{tag}{r:03d}{h:03d}', t + 5 + 5 * h))
        book.add(t + 60, turn=turn, round_bonuses_seen=bonuses[0], round_bonuses_taken=bonuses[1])
        t += 61
    return t


def test_hits_join_their_rounds_and_rates_count_rounds_without_hits(loop):
    store, runner, clock, deliver, book = loop
    t = play(deliver, book, 90_000.0, 4, 2)                         # 8 hits over 4 rounds
    play(deliver, book, t, 4, 0)                                    # 4 clean rounds
    labelled, _deaths = C.label_all(store.all(C.INCIDENT))
    joined, unmatched = L.assign(labelled, runner.learning.rounds(RE5T))
    assert unmatched == 0 and sum(len(v) for v in joined.values()) == 8 and len(joined) == 4
    clusters, _t = C.summarize(store.all(C.INCIDENT), now=clock[0])
    runner.learning.enrich(clusters, store.all(C.INCIDENT), window_s=C.WINDOW_S)
    c = clusters[(RE5, 'crowd_4_in_2m')]
    assert (c['rounds'], c['rate_per_round'], c['marked_rounds']) == (8, 1.0, 4)
    assert c['round_turns'][0]['rounds'] == 8 and len(c['example_rounds']) == 4


def test_round_faults_name_bonus_misses_with_a_rate_and_example_rounds(loop):
    store, runner, clock, deliver, book = loop
    play(deliver, book, 90_000.0, 12, 0, bonuses=(3, 1))
    play(deliver, book, 91_000.0, 8, 0, bonuses=(0, 0), turn='job_2')
    faults = runner.learning.enrich({}, [], window_s=C.WINDOW_S)
    f = faults[(RE5, 'round:bonus_missed')]
    assert (f['rounds'], f['marked_rounds'], f['rate_per_round']) == (20, 12, 1.2)
    assert f['batchable'] and f['kind'] == 'round' and len(f['examples']) == C.EXAMPLES
    assert f['examples'][0]['reviewer'].startswith('/api/mercs/reviewer/round?title=010018100CD46000&id=')
    assert [t['marked'] for t in f['turns']] == [12, 0]
    assert faults[(RE5, 'round:wall_aim')]['batchable'] is False
    runner.poll()
    batch = store.get('request', C.request_id_for(f['id']))
    assert batch['title'] == 'Damage batch: RE5 Switch - time bonus seen, not taken'
    assert batch['body'].startswith('Round fault of RE5 Switch') and 'Bot._bonus_tick' in batch['body']
    assert 'Target: 0.96 or less' in batch['body']


def test_a_bot_reload_or_a_restart_of_the_titles_code_is_a_change(loop):
    store, runner, clock, deliver, book = loop
    store.put('job', 'j1', {'id': 'j1', 'tool': 'bot_reload', 'state': 'succeeded', 'finished': 99_000.0,
                            'worker_id': 'w1', 'result': {'ok': True, 'reloaded': ['gbox.mercs.titles.re5_switch']}})
    store.put('job', 'j2', {'id': 'j2', 'tool': 'bot_reload', 'state': 'succeeded', 'finished': 99_100.0,
                            'worker_id': 'w1', 'result': {'ok': True, 'reloaded': ['gbox.mercs.titles.re4_gc']}})
    store.put('worker', 'w1', {'id': 'w1', 'build_sources': {'gbox/mercs/titles/re5_switch.py': 'a',
                                                               'gbox/server.py': 'x'}})
    found = runner.learning.track_changes([RE5T])
    assert [(c['kind'], c['modules']) for c in found] == [('reload', ['gbox.mercs.titles.re5_switch'])]
    assert runner.learning.track_changes([RE5T]) == []              # each job once; the first hashes are a baseline
    store.put('worker', 'w1', {'id': 'w1', 'build_sources': {'gbox/mercs/titles/re5_switch.py': 'b',
                                                               'gbox/server.py': 'y'}})
    again = runner.learning.track_changes([RE5T])
    assert [(c['kind'], c['files']) for c in again] == [('restart', ['gbox/mercs/titles/re5_switch.py'])]
    assert len(runner.learning.changes(RE5T)) == 2


def close(store, rid, at):
    req = store.get('request', rid)
    req.update(status='done', completed=at)
    store.put('request', rid, req)


def test_a_closed_batch_stays_closed_when_the_live_fix_cuts_its_rate(loop):
    store, runner, clock, deliver, book = loop
    t = play(deliver, book, 60_000.0, 12, 2)                        # 2 per round before the fix
    runner.poll()
    rid = C.request_id_for(C.cluster_id(RE5, 'crowd_4_in_2m'))
    close(store, rid, t)
    store.put('job', 'fix', {'id': 'fix', 'tool': 'bot_reload', 'state': 'succeeded', 'finished': t + 10,
                             'worker_id': 'w1', 'result': {'ok': True, 'reloaded': ['gbox.mercs.titles.re5_switch']}})
    runner.poll()
    play(deliver, book, t + 20, 12, 1, tag='b')                     # 1 per round after it
    clock[0] = t + 2000
    runner.poll()
    req = store.get('request', rid)
    assert req['status'] == 'done' and req['messages'][-1]['text'].startswith('Effect measured')
    change = runner.learning.changes(RE5T)[0]
    assert change['effects']['crowd_4_in_2m']['verdict'] == 'improved'
    assert (change['effects']['crowd_4_in_2m']['before'], change['effects']['crowd_4_in_2m']['after']) == (2.0, 1.0)
    assert store.get(C.CLUSTER, C.cluster_id(RE5, 'crowd_4_in_2m'))['last_verdict'] == 'improved'
    runner.poll()
    assert len([m for m in store.get('request', rid)['messages'] if m.get('id', '').startswith('follow-up')]) == 1


def test_a_closed_batch_reopens_when_the_rate_did_not_drop_or_no_change_went_live(loop):
    store, runner, clock, deliver, book = loop
    t = play(deliver, book, 60_000.0, 12, 2)
    runner.poll()
    rid = C.request_id_for(C.cluster_id(RE5, 'crowd_4_in_2m'))
    close(store, rid, t)
    store.put('job', 'fix', {'id': 'fix', 'tool': 'bot_reload', 'state': 'succeeded', 'finished': t + 10,
                             'worker_id': 'w1', 'result': {'ok': True, 'reloaded': ['gbox.mercs.titles.re5_switch']}})
    runner.poll()
    t2 = play(deliver, book, t + 20, 12, 2, tag='b')                # the same rate after the change
    clock[0] = t2 + 100
    runner.poll()
    req = store.get('request', rid)
    assert req['status'] == 'open' and req['messages'][-1]['text'].startswith('Reopened: after the reload')
    assert '2.0 per round over 12 rounds, against 2.0' in req['messages'][-1]['text']
    # closed again with no bot change after it: reopened once NO_CHANGE_S has passed and the cause goes on
    close(store, rid, clock[0])
    play(deliver, book, clock[0] + 100, 3, 2, tag='c')
    clock[0] += 3600
    runner.poll()
    assert store.get('request', rid)['status'] == 'done'
    clock[0] += L.NO_CHANGE_S
    play(deliver, book, clock[0] - 600, 3, 2, tag='d')
    runner.poll()
    req = store.get('request', rid)
    assert req['status'] == 'open' and 'no RE5 Switch bot change went live' in req['messages'][-1]['text']


def test_replay_fixtures_come_from_the_cluster_examples_and_drive_the_bot(loop):
    store, runner, clock, deliver, book = loop
    play(deliver, book, 90_000.0, 3, 2)
    runner.poll()
    app = FastAPI()
    C.install(app, store, type('Config', (), {'data_dir': store.dir})(), lambda: 'agent', runner=runner)
    client = TestClient(app)
    cid = C.cluster_id(RE5, 'crowd_4_in_2m')
    page = client.get(f'/api/mercs/damage-clusters/{cid}/replay?n=2').json()
    assert len(page['fixtures']) == 2 and page['missing'] == []
    fx = page['fixtures'][0]
    assert fx['schema'] == incident_replay.SCHEMA and fx['cluster']['signature'] == 'crowd_4_in_2m'
    assert len(fx['snapshot']['enemies']) == 4 and fx['held'] == ['zl', 'zr']
    result = incident_replay.replay(fx, ticks=4)
    assert len(result['ticks']) == 4 and all(isinstance(t['act'], dict) for t in result['ticks'])
    learning = client.get('/api/mercs/learning?game=re5').json()
    assert learning['titles'][RE5T]['rounds_24h'] == 3
    assert learning['clusters'][0]['rate_per_round'] == 2.0
    assert client.get('/api/mercs/damage-clusters/0000000000000000/replay').status_code == 404


@pytest.mark.parametrize('name', ['re5_switch_hold_in_crowd', 're6_switch_crowd_gun_down'])
def test_real_incident_fixtures_replay_deterministically(name):
    """Two fixtures cut from the Spark's receipts of 2026-10-27 (the replay test pattern a batch PR copies)."""
    fx = json.loads((FIXTURES / f'{name}.json').read_text())
    first, second = incident_replay.replay(fx, ticks=12), incident_replay.replay(fx, ticks=12)
    assert [t['act'] for t in first['ticks']] == [t['act'] for t in second['ticks']]
    assert incident_replay.keys(first) and all(isinstance(k, str) for k in incident_replay.keys(first))
    ev = {k: fx[k] for k in ('title', 'snapshot', 'held', 'hp_before', 'hp_after', 'hp_max', 'loss', 'observed_at',
                             'preceding_history')}
    assert C.classify(C.features(dict(ev, logic=fx['counters']), fx['cluster']['game_id']))[0] == \
        fx['cluster']['signature']


def test_crowd_gun_down_fixture_fights_instead_of_escaping():
    """#5078: 4+ within 2 m with the gun lowered — the bot escapes (gun down) instead of crowd-firing.

    The fix: _escape returns None when 4+ enemies are within 2 m, so the decision falls through to
    _rampage (CROWD_FIRE) which keeps the gun up and firing until the circle is clear.
    """
    fx = json.loads((FIXTURES / 're5_switch_crowd_gun_down.json').read_text())
    result = incident_replay.replay(fx, ticks=15)
    keys = incident_replay.keys(result)
    # The gun must come up and fire (zl + zr), not stay down through an escape
    assert 'zl' in keys, f'gun never raised: {[t["doing"] for t in result["ticks"]]}'
    assert 'zr' in keys, f'never fired: {[t["doing"] for t in result["ticks"]]}'
    # The bot should reach crowd fire, not stay in escape
    doings = [t['doing'] for t in result['ticks']]
    assert 'fire' in doings, f'never reached crowd fire: {doings}'
    assert 'escape' not in doings, f'escaped instead of fighting: {doings}'


def test_a_fixture_needs_its_schema_and_a_replayable_title():
    with pytest.raises(ValueError):
        incident_replay.replay({'schema': 'other'})
    with pytest.raises(ValueError):
        incident_replay.bot('BLUS30491')


def test_re6_switch_bomb_wait_fights_close_enemies():
    """bomb_act_damage: during 'thrown'/'det_wait', enemies on him make the bot fight instead of waiting."""
    from gbox.mercs.titles.re6_switch import Bot, BOMB_FIGHT_R

    # --- thrown phase: enemy within BOMB_FIGHT_R -> fight (None), not wait ---
    b = Bot(clock=lambda: 10.0)
    b.bomb_phase = "thrown"
    b.bomb_phase_at = 8.0
    b.bomb_at = (0.0, 0.0)
    b.bomb_since = 8.0
    b.bomb_from = (0.0, 0.0)

    live = [{"pos": [100.0, 0.0, 0.0], "hp": 500}]
    p = {"pos": [0.0, 0.0, 0.0]}
    result = b._bomb_press(5, 10.0, live=live, p=p)
    assert result is None, f"thrown with enemy at 100cm should fight, got {result}"

    # --- det_wait phase: enemy within BOMB_FIGHT_R -> fight (None), not wait ---
    b2 = Bot(clock=lambda: 10.0)
    b2.bomb_phase = "det_wait"
    b2.bomb_phase_at = 8.0
    b2.bomb_at = (0.0, 0.0)
    b2.bomb_since = 8.0
    b2.bomb_from = (0.0, 0.0)

    result2 = b2._bomb_press(5, 10.0, detonate=True, live=live, p=p)
    assert result2 is None, f"det_wait with enemy at 100cm should fight, got {result2}"

    # --- thrown phase: no enemies -> keep waiting ---
    b3 = Bot(clock=lambda: 10.0)
    b3.bomb_phase = "thrown"
    b3.bomb_phase_at = 8.0
    b3.bomb_at = (0.0, 0.0)
    b3.bomb_since = 8.0
    b3.bomb_from = (0.0, 0.0)

    result3 = b3._bomb_press(5, 10.0, live=[], p=p)
    assert result3 is not None and result3.get("hold") == (), \
        f"thrown with no enemies should wait, got {result3}"

    # --- det_wait phase: no enemies -> keep waiting ---
    b4 = Bot(clock=lambda: 10.0)
    b4.bomb_phase = "det_wait"
    b4.bomb_phase_at = 8.0
    b4.bomb_at = (0.0, 0.0)
    b4.bomb_since = 8.0
    b4.bomb_from = (0.0, 0.0)

    result4 = b4._bomb_press(5, 10.0, detonate=True, live=[], p=p)
    assert result4 is not None and result4.get("hold") == (), \
        f"det_wait with no enemies should wait, got {result4}"

    # --- enemy just outside BOMB_FIGHT_R -> keep waiting ---
    b5 = Bot(clock=lambda: 10.0)
    b5.bomb_phase = "thrown"
    b5.bomb_phase_at = 8.0
    b5.bomb_at = (0.0, 0.0)
    b5.bomb_since = 8.0
    b5.bomb_from = (0.0, 0.0)

    far_live = [{"pos": [BOMB_FIGHT_R + 50.0, 0.0, 0.0], "hp": 500}]
    result5 = b5._bomb_press(5, 10.0, live=far_live, p=p)
    assert result5 is not None and result5.get("hold") == (), \
        f"thrown with enemy at {BOMB_FIGHT_R + 50}cm should wait, got {result5}"


def test_re6_switch_bomb_act_damage_fixture_replays_deterministically():
    """The synthetic bomb_act_damage fixture replays deterministically."""
    fx = json.loads((FIXTURES / "re6_switch_bomb_act_damage.json").read_text())
    first, second = incident_replay.replay(fx, ticks=12), incident_replay.replay(fx, ticks=12)
    assert [t['act'] for t in first['ticks']] == [t['act'] for t in second['ticks']]
    assert incident_replay.keys(first) and all(isinstance(k, str) for k in incident_replay.keys(first))


def test_wall_los_aim_cluster_fixture_drives_the_bot_and_the_wall_gate_fires():
    """#5540 batch: laser locked on a wall while the bot aims out of sight (cluster wall_los_aim, game 115f9cdbba115432).

    The representative example: the player is at the origin, the camera is 2 m behind (0,140,-200) facing +z, and the
    one live enemy is 9 m out at (0,0,900). The laser is up but its ray ends at (0,115,700) - a wall 7 m from the
    muzzle - so the bot's lock is on the wall, not the zombie. The fix (the wall gate in _los_tick) sees the laser's
    ray end short of the targeted zombie, marks him out of sight for WALL_BLOCK_S (wall_blocks), and drops the target
    so the bot breaks free and walks around instead of holding the aim on the wall and eating the wall's recoil kick.
    """
    fx = json.loads((FIXTURES / "re6_switch_wall_los_aim.json").read_text())
    assert fx["cluster"]["signature"] == "wall_los_aim" and fx["cluster"]["game_id"] == "115f9cdbba115432"
    first, second = incident_replay.replay(fx, ticks=40), incident_replay.replay(fx, ticks=40)
    assert [t['act'] for t in first['ticks']] == [t['act'] for t in second['ticks']]   # deterministic
    assert incident_replay.keys(first) and all(isinstance(k, str) for k in incident_replay.keys(first))

    # The wall gate banks aim-on-wall time, then (once it crosses WALL_DROP_S) drops the target and marks the
    # zombie out of sight, so the bot breaks free and walks around instead of holding the aim on the wall.
    res = incident_replay.replay(fx, ticks=40)
    bot, stats = res["bot"], res["stats"]
    e = fx["snapshot"]["enemies"][0]
    assert bot._ray_short((0.0, 0.0, 0.0), (0.0, 115.0, 700.0), e)      # the ray ends short of his chest: a wall between
    assert stats.get("wall_aim_s", 0.0) > 0.0                            # the aim-on-wall time is banked
    assert bot.target is None, f"target not dropped by the wall gate: {bot.target}"
    assert bot.is_blocked(e, bot.clock()), "the wall-gated target is not out of sight"

    # Guardrail: the same scene with a clear ray (the laser reaches him) is NOT wall-gated - no false positive.
    clear = json.loads(json.dumps(fx))
    clear["snapshot"]["laser"]["at"] = [0.0, 115.0, 895.0]              # 5 cm short of his chest: through, not a wall
    r2 = incident_replay.replay(clear, ticks=4)
    assert r2["stats"].get("wall_aim_s", 0.0) == 0.0, \
        f"clear ray must not trip the wall gate: {r2['stats'].get('wall_aim_s')}"
