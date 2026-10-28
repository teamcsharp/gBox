"""Split screen on RE5 / RE6 Switch, the app side: the roles (teamplay), the input fence for two bots
(SessionRuntime), the team tool's Player 2 restart, mercs_bot's split-screen session, the human-controls gate and
MercMode's optional bot+bot turns (docs/research/switch-coop-bot.md). Fixtures only: no live two-player run yet."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

import test_mercmode as TM
from gbox import mercmode as M, mercs_team_tool as TOOL, screensaver as S, tools
from gbox.mercs import session_runtime as SR, teamplay as T
from gbox.mercs.titles import switch_team

SID = 'lilspark-coop'
PROOF = {'p2_verified': True, 'p2_actor_verified': True, 'controller2_verified': True, 'camera2_verified': True,
         'prompt2_verified': True, 'human_observer_verified': True,
         'active_players': [{'id': f'p{slot}', 'slot': slot, 'actor': 0x5D0000 + slot,
                             'provenance': {'native_actor_verified': True}} for slot in (1, 2)]}
P1_ONLY = {**PROOF, 'p2_verified': False, 'p2_actor_verified': False, 'active_players': PROOF['active_players'][:1],
           'reason': 'Player 2 has not joined the round (split screen, a prepared Player 2 pad)'}


@pytest.fixture(autouse=True)
def fresh_evidence():
    T._EVIDENCE.clear()
    yield
    T._EVIDENCE.clear()


# --- roles -------------------------------------------------------------------------------------------------------------

def test_bots_on_both_players_is_a_switch_role():
    store = T.TeamStore('unused')
    for gid in (T.RE5, T.RE6):
        with pytest.raises(ValueError, match='split screen'):
            T.TeamStore.configure(store, 'x-1', {'role': 'bots_p1_p2'}, game_id=gid)


def test_switch_status_follows_player_twos_proof(tmp_path):
    store, ad = T.TeamStore(tmp_path), SimpleNamespace(name='citron')
    assert store.status(SID, game_id=T.RE5_SWITCH, adapter=ad)['control_player'] == 1            # solo as always
    store.configure(SID, {'role': 'teammate_p2'}, game_id=T.RE5_SWITCH)
    status = store.status(SID, game_id=T.RE5_SWITCH, adapter=ad)
    assert (status['control_player'], status['phase'], status['split_screen']) == (None, 'waiting_p2', True)
    T.publish_runtime(SID, ad, PROOF, now=10)
    assert store.status(SID, game_id=T.RE5_SWITCH, adapter=ad, now=11)['control_player'] == 2
    for change in ({'controller2_verified': False}, {'active_players': PROOF['active_players'][:1]},
                   {'active_players': [dict(p, actor=7) for p in PROOF['active_players']]}):
        T.publish_runtime(SID, ad, {**PROOF, **change}, now=10)
        assert store.status(SID, game_id=T.RE5_SWITCH, adapter=ad, now=11)['control_player'] is None
    store.configure(SID, {'role': 'bots_p1_p2'}, game_id=T.RE5_SWITCH)
    T.publish_runtime(SID, ad, P1_ONLY, now=10)
    status = store.status(SID, game_id=T.RE5_SWITCH, adapter=ad, now=11)
    assert (status['control_player'], status['partner_player'], status['phase']) == (1, None, 'active_p1_waiting_p2')
    assert status['capabilities']['bots_p1_p2']['available'] and not status['capabilities']['bots_p1_p2']['verified']
    T.publish_runtime(SID, ad, PROOF, now=10)
    status = store.status(SID, game_id=T.RE5_SWITCH, adapter=ad, now=11)
    assert (status['control_player'], status['partner_player'], status['phase']) == (1, 2, 'active')
    assert store.status(SID, game_id=T.RE5_SWITCH, adapter=SimpleNamespace(name='rpcs3'), now=11)['phase'] == 'unsupported'
    store.configure(SID, {'training_profile': 'unmodified_evaluation'}, game_id=T.RE5_SWITCH)
    assert store.status(SID, game_id=T.RE5_SWITCH, adapter=ad, now=11)['control_player'] is None


# --- the input fence for two bots --------------------------------------------------------------------------------------

def runtime(tmp_path, role, evidence, *, fixed=False):
    sent = []

    class Adapter:
        name = 'citron'
        config = SimpleNamespace(data_dir=tmp_path)

        def send_input(self, rows):
            sent.append((1, deepcopy(rows)))

        def send_input_player(self, rows, *, player):
            sent.append((player, deepcopy(rows)))

    ad = Adapter()
    if not fixed:
        T.TeamStore(tmp_path).configure(SID, {'role': role}, game_id=T.RE6_SWITCH)

    class Native:
        def readiness(self, memory):
            return deepcopy(evidence)

        def participants(self, memory, snap):
            return deepcopy(evidence['active_players'])

    rt = SR.SessionRuntime(ad, SID, T.RE6_SWITCH, '01002A000CD48000', ad.send_input, {}, clock=lambda: 1.0,
                           role=role if fixed else None)
    memory = SimpleNamespace(adapter=ad)
    rt.poll(memory, Native(), {'player': {'ptr': 1}})
    return rt, sent, memory


def test_two_bots_route_player_twos_prefixed_keys_to_its_pad(tmp_path):
    rt, sent, memory = runtime(tmp_path, 'bots_p1_p2', PROOF, fixed=True)
    assert rt.config['role'] == 'bots_p1_p2' and memory.mercs_no_modifications is False   # the bots keep their mods
    rt.send([{'key': 'zl', 'down': True}, {'key': 'p2:zl', 'down': True}, {'key': 'p2:a', 'down': True}])
    assert sent == [(1, [{'key': 'zl', 'down': True, 'player': 1}]),
                    (2, [{'key': 'zl', 'down': True, 'player': 2}, {'key': 'a', 'down': True, 'player': 2}])]
    sent.clear()
    rt.send([{'key': 'p2:zl', 'down': False}, {'key': 'zl', 'down': False}])
    assert sent == [(1, [{'key': 'zl', 'down': False, 'player': 1}]), (2, [{'key': 'zl', 'down': False, 'player': 2}])]
    sent.clear()
    rt.release()
    assert sent == [(2, [{'key': 'a', 'down': False, 'player': 2}])]


def test_player_two_gets_nothing_until_proved_and_player_one_plays_on(tmp_path):
    rt, sent, _ = runtime(tmp_path, 'bots_p1_p2', P1_ONLY)
    rt.send([{'key': 'p2:zr', 'down': True}, {'key': 'zr', 'down': True}])
    assert sent == [(1, [{'key': 'zr', 'down': True, 'player': 1}])]


def test_a_teammate_bot_sends_only_to_player_two(tmp_path):
    rt, sent, memory = runtime(tmp_path, 'teammate_p2', PROOF)
    assert memory.mercs_no_modifications is False                                   # its mods help the operator
    rt.send([{'key': 'zl', 'down': True}, {'key': 'p2:zl', 'down': True}])
    assert sent == [(2, [{'key': 'zl', 'down': True, 'player': 2}])]                # never P1, the human's
    rt2, sent2, memory2 = runtime(tmp_path / 'obs', 'observe_human', PROOF)
    assert memory2.mercs_no_modifications is True
    rt2.send([{'key': 'zl', 'down': True}])
    assert sent2 == []


# --- the team tool ---------------------------------------------------------------------------------------------------

def test_the_tool_connects_player_two_by_a_restart_on_switch(tmp_path, monkeypatch):
    asked = []

    class Adapter:
        name = 'citron'
        proc = SimpleNamespace(poll=lambda: None)

        def prepare_teammate_pad(self, player=2, enabled=True, restart=False):
            asked.append((player, enabled, restart))
            return {'player': 2, 'prepared': True, 'verified': False, 'reason': 'restarting'}

        def teammate_pad_status(self):
            return {'player': 2, 'prepared': True, 'verified': False}

        def restart_title(self, **kw):
            return {}
    monkeypatch.setattr(tools, 'SESSIONS', {SID: (Adapter(), {'game_id': T.RE6_SWITCH})})
    ctx = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    out = TOOL.mercs_team(TOOL.TeamIn(session_id=SID, op='prepare_player2', restart=True), ctx)['result']['status']
    assert asked == [(2, True, True)] and out['player2_preparation']['reason'] == 'restarting'
    prep = out['capabilities']['prepare_player2']
    assert prep['available'] is True and prep['restart_available'] is True
    TOOL.mercs_team(TOOL.TeamIn(session_id=SID, op='configure', role='bots_p1_p2'), ctx)
    assert T.TeamStore(tmp_path).get(SID)['role'] == 'bots_p1_p2'


# --- mercs_bot's split-screen session ---------------------------------------------------------------------------------

def test_a_split_screen_session_starts_only_for_a_team_role_or_a_coop_turn(tmp_path):
    ad = SimpleNamespace(name='citron', config=SimpleNamespace(data_dir=tmp_path))
    prof = {'map_id': '010018100CD46000'}
    m = SimpleNamespace(adapter=ad)
    solo = {'game_id': T.RE5_SWITCH, 'launch': {'mercmode': {'random_stages': True}}}
    assert switch_team.Session.start(ad, SID, solo, prof, m, lambda rows: None, {}) is None
    assert not getattr(m, 'mercs_split_screen', False)
    assert switch_team.Session.start(ad, SID, solo, {'map_id': 'BLUS30491'}, m, lambda rows: None, {}) is None
    turn = {'game_id': T.RE5_SWITCH, 'launch': {'mercmode': {'random_stages': True, 'coop': 'bots'}}}
    stats = {}
    coop = switch_team.Session.start(ad, SID, turn, prof, m, lambda rows: None, stats)
    assert coop.role == 'bots_p1_p2' and coop.runtime.fixed_role == 'bots_p1_p2' and m.mercs_split_screen is True
    assert isinstance(coop.driver, switch_team.CoopDriver) and coop.driver.mode == switch_team.PAIR
    assert stats['coop_mode'] == switch_team.PAIR
    assert coop.follow('observe_human') is None and m.mercs_split_screen is False
    T.TeamStore(tmp_path).configure('other', {'role': 'teammate_p2'}, game_id=T.RE5_SWITCH)
    mate = switch_team.Session.start(ad, 'other', solo, prof, SimpleNamespace(adapter=ad), lambda rows: None, {})
    assert mate.driver.mode == switch_team.TEAMMATE and mate.partner.after_s == switch_team.TEAMMATE_MENU_WAIT_S


def test_human_controls_mean_a_human_holds_player_one(tmp_path, monkeypatch):
    ad = SimpleNamespace(config=SimpleNamespace(data_dir=tmp_path))
    monkeypatch.setattr(tools, 'SESSIONS', {SID: (ad, {'game_id': T.RE5_SWITCH})})
    assert tools._mercs_human_controls(SID) is False
    for role, human in (('teammate_p2', True), ('observe_human', True), ('bots_p1_p2', False)):
        T.TeamStore(tmp_path).configure(SID, {'role': role}, game_id=T.RE5_SWITCH)
        assert tools._mercs_human_controls(SID) is human


# --- MercMode's bot+bot turns ----------------------------------------------------------------------------------------

def test_coop_ratio_is_off_by_default_and_draws_per_turn_for_the_switch_editions():
    import random
    cfg = M.normalize({})
    assert cfg['coop_ratio'] == 'off'
    for bad in ('7:1', True, 6, '6'):
        with pytest.raises(ValueError, match='coop_ratio'):
            M.normalize({'coop_ratio': bad})
    rng = random.Random(7)
    six = M.normalize({'coop_ratio': '6:1'})
    draws = [M.draw_coop(six, '01002A000CD48000', rng) for _ in range(7000)]
    share = sum(1 for d in draws if d == {'coop': 'bots'}) / len(draws)
    assert 0.82 < share < 0.89                                    # six co-op turns to one solo
    assert M.draw_coop(six, 'BLUS30491', rng) == {} and M.draw_coop(six, 'G4BE08', rng) == {}
    assert all(M.draw_coop(cfg, '010018100CD46000', rng) == {} for _ in range(50))
    only = M.normalize({'coop_ratio': 'only'})
    assert all(M.draw_coop(only, '010018100CD46000', rng) == {'coop': 'bots'} for _ in range(50))
    assert M.coop_weights(only) == (1, 0) and M.coop_weights(six) == (6, 1) and M.coop_weights(cfg) == (0, 1)
    assert M.launch_block(six, coop={'coop': 'bots'})['coop'] == 'bots'
    assert 'coop' not in M.launch_block(six, coop={}) and 'coop' not in M.launch_block(six)


def test_a_coop_turn_counts_its_team_rounds_and_only_a_coop_turn_does():
    store, w, saver, calls, now, tick, run, job = TM.playing()
    run = store.get(S.STATE, w['name'])
    team = TM.boundary(run, now[0]) | {'role': 'bots_p1_p2'}
    with pytest.raises(ValueError, match='solo native terminal-round witness'):
        M.accept_boundary(store, run, team, parent_job=job, now=now[0])
    run['mercmode'] = dict(run['mercmode'], coop='bots')
    store.put(S.STATE, w['name'], run)
    assert M.accept_boundary(store, run, team, parent_job=job, now=now[0])['round_id'] == 'a' * 32
    with pytest.raises(ValueError):
        M.accept_boundary(store, run, team | {'role': 'teammate_p2', 'round_id': 'b' * 32}, parent_job=job, now=now[0])


# --- mercs_bot's loop in split screen ---------------------------------------------------------------------------------

def coop_play(tmp_path, monkeypatch, where, *, role=None, turn=False, rounds=1):
    import sys
    from gbox import mercs_bot as MB
    sent, boots, engines = [], [], []

    class Adapter:
        name = 'citron'
        config = SimpleNamespace(data_dir=tmp_path)
        supported = {'send_input'}

        def send_input(self, rows):
            sent.append((1, deepcopy(rows)))

        def send_input_player(self, rows, *, player):
            sent.append((player, deepcopy(rows)))
    ad = Adapter()
    if role:
        T.TeamStore(tmp_path).configure(SID, {'role': role}, game_id=T.RE6_SWITCH)
    name = 'gbox.tests_coop_menus'
    monkeypatch.setitem(sys.modules, name, SimpleNamespace(screen=lambda m: {'where': where}))
    prof = {'map_id': '01002A000CD48000', 'menus': name, 'playing_ops': [['infinite_ammo', True]]}
    monkeypatch.setattr(MB, 'profile_for', lambda *_: prof)
    monkeypatch.setattr(MB, 'lessons_writer', lambda *_: None)
    monkeypatch.setattr(MB, 'tactical_publisher', lambda *_: None)
    applied = []
    monkeypatch.setattr(MB, 'apply_ops', lambda ad_, ops, prof_, *rest: applied.extend(ops) or [])

    class Boot:
        def __init__(self, menus, m, send, **kw):
            boots.append(send)
            self.nav = SimpleNamespace(poll_s=lambda scr, d: d, last_key=None)

        def tick(self, now, scr=None):
            boots.append(('tick', scr['where']))
    monkeypatch.setattr(MB, 'Boot', Boot)

    def engine(prof_, m, send, stopped, stats, lessons, **kw):
        engines.append(kw)
        return 'stopped'
    monkeypatch.setattr(MB, 'title_engine', lambda _: SimpleNamespace(play_round=engine))
    clock, slept = [100.0], []

    def sleep(s):
        slept.append(s)
        clock[0] += max(s, 0.5)
    game = {'game_id': T.RE6_SWITCH, 'launch': {'mercmode': {'coop': 'bots'}} if turn else {}}
    stats = MB.play(ad, ad.send_input, lambda: len(slept) > 40, {}, game, m=SimpleNamespace(adapter=ad),
                    sleep=sleep, clock=lambda: clock[0], session_id=SID)
    return sent, boots, engines, applied, stats


def test_teammate_menus_belong_to_the_operator_and_player_two_takes_its_character(tmp_path, monkeypatch):
    sent, boots, engines, applied, stats = coop_play(tmp_path, monkeypatch, 'select_player', role='teammate_p2')
    assert [b for b in boots if isinstance(b, tuple)] == []                       # no menus walk: the human's P1
    assert sent and all(player == 2 for player, _ in sent)                       # Player 2's A on its own pad
    assert sent[0] == (2, [{'key': 'a', 'down': True, 'player': 2}]) and not engines
    assert stats['team_role'] == 'teammate_p2' and stats['coop_mode'] == switch_team.TEAMMATE


def test_a_bot_pair_turn_walks_player_ones_menus_with_the_raw_pad(tmp_path, monkeypatch):
    sent, boots, engines, applied, stats = coop_play(tmp_path, monkeypatch, 'main_menu', turn=True)
    assert boots[0].__name__ == 'send_input' and not isinstance(boots[0].__self__, SR.SessionRuntime)   # P1's own pad
    assert ('tick', 'main_menu') in boots and not engines and not sent        # the walk presses P1 through Boot
    assert stats['team_role'] == 'bots_p1_p2'


def test_a_bot_pair_round_runs_the_pair_driver_with_the_profiles_mods(tmp_path, monkeypatch):
    sent, boots, engines, applied, stats = coop_play(tmp_path, monkeypatch, 'playing', turn=True)
    assert engines and isinstance(engines[0]['driver'], switch_team.CoopDriver)
    assert engines[0]['driver'].mode == switch_team.PAIR and engines[0]['session_runtime'].config['role'] == 'bots_p1_p2'
    assert ['infinite_ammo', True] in [list(op) for op in applied]              # the bots keep the session's mods
